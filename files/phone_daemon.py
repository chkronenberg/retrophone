#!/usr/bin/env python3
import time, os, socket, json, logging, logging.handlers, subprocess
import RPi.GPIO as GPIO

CONFIG_PATH = os.environ.get("RETRO_CONFIG_PATH", "/etc/retrophone/config.json")

def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError):
        return {}

CONFIG = load_config()
GPIO_CONFIG = CONFIG.get("gpio", {}) if isinstance(CONFIG.get("gpio", {}), dict) else {}
PHONE_CONFIG = CONFIG.get("phone_daemon", {}) if isinstance(CONFIG.get("phone_daemon", {}), dict) else {}
BARESIP_CONFIG = CONFIG.get("baresip_control", {}) if isinstance(CONFIG.get("baresip_control", {}), dict) else {}
PATH_CONFIG = CONFIG.get("paths", {}) if isinstance(CONFIG.get("paths", {}), dict) else {}

# --- GPIO Definitionen ---
PIN_PULSE = int(GPIO_CONFIG.get("pulse", 23))
PIN_HOOK  = int(GPIO_CONFIG.get("hook", 18))
PIN_POS1  = int(GPIO_CONFIG.get("dial_position", 24))

# --- Zeiten und Parameter ---
DIAL_TIMEOUT      = float(PHONE_CONFIG.get("dial_timeout", 2.5))
DEBOUNCE          = float(PHONE_CONFIG.get("debounce", 0.006))
MIN_PULSE_LOW     = float(PHONE_CONFIG.get("min_pulse", 0.004))
MAX_PULSE_LOW     = float(PHONE_CONFIG.get("max_pulse", 0.08))

CALLS_POLL_SEC    = float(PHONE_CONFIG.get("calls_poll_interval", 0.6))
RING_WATCHDOG_SEC = float(PHONE_CONFIG.get("ring_watchdog", 2.0))

# --- baresip Steuerung (ctrl_tcp, JSON + Netstring) ---
BS_HOST            = str(BARESIP_CONFIG.get("host", "127.0.0.1"))
BS_PORT            = int(BARESIP_CONFIG.get("port", 4444))
BS_READ_TIMEOUT    = float(BARESIP_CONFIG.get("read_timeout", 0.8))
BS_CONNECT_TIMEOUT = float(BARESIP_CONFIG.get("connect_timeout", 1.0))
BS_RECONNECT_PAUSE = float(BARESIP_CONFIG.get("reconnect_pause", 0.8))

# --- Dialtone Datei ---
DIALTONE_WAV = str(PATH_CONFIG.get("dialtone", "/usr/local/retrophone/dialtone.wav"))

# --- Logging ---
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}

def configured_log_level():
    """Log-Level aus der gemeinsamen RetroPhone-Konfiguration lesen."""
    try:
        level = str(PHONE_CONFIG.get("log_level", "INFO")).upper()
        return level if level in VALID_LOG_LEVELS else "INFO"
    except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError):
        return "INFO"

#LOG_DIR  = "/var/log/retrophone"
LOG_DIR  = str(PATH_CONFIG.get("runtime_dir", "/run/retrophone"))
LOG_PATH = os.path.join(LOG_DIR, "phone.log")
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("retrophone")
LOG_LEVEL = configured_log_level()
logger.setLevel(getattr(logging, LOG_LEVEL))
handler = logging.handlers.TimedRotatingFileHandler(
    LOG_PATH, when="midnight", backupCount=7, encoding="utf-8"
)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)
logger.propagate = False

# globaler Status fuer Dialtone und Call
dialtone_proc = None
call_in_progress = False


# ---------- GPIO ----------
def gpio_setup():
    GPIO.setmode(GPIO.BCM)
    for p in (PIN_PULSE, PIN_HOOK, PIN_POS1):
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    logger.info(
        "GPIO init: HOOK=%d PULSE=%d POS1=%d",
        PIN_HOOK, PIN_PULSE, PIN_POS1
    )

def offhook_from_raw(hook_raw: int) -> bool:
    # 0 = abgehoben, 1 = aufgelegt
    return hook_raw == 0


# ---------- baresip ctrl_tcp (JSON + Netstring) ----------
class BaresipCtrl:
    def __init__(self, host, port, read_timeout):
        self.host = host
        self.port = port
        self.read_timeout = read_timeout
        self.sock = None
        self.last_connect_fail = 0.0

    def _connect(self):
        now = time.time()
        if self.sock:
            return True
        if now - self.last_connect_fail < BS_RECONNECT_PAUSE:
            return False
        try:
            s = socket.create_connection(
                (self.host, self.port),
                timeout=BS_CONNECT_TIMEOUT
            )
            s.settimeout(self.read_timeout)
            self.sock = s
            logger.info("Mit baresip ctrl_tcp (JSON+Netstring) verbunden (%s:%d)", self.host, self.port)
            return True
        except Exception as e:
            self.last_connect_fail = now
            logger.error("baresip connect fehlgeschlagen: %s", e)
            self.sock = None
            return False

    def _send_netstring(self, payload: str):
        """
        Sende einen Netstring:
          <len>:<payload>,
        wobei payload ein JSON-String ist.
        """
        if not self.sock:
            return
        data = payload.encode("utf-8")
        header = f"{len(data)}:".encode("ascii")
        packet = header + data + b","
        self.sock.sendall(packet)

    def cmd(self, command: str, params: str = "", token: str = "retrophone") -> str:
        """
        Schickt ein JSON-Kommando wie:
          {"command":"dial","params":"078...","token":"retrophone"}
        verpackt als Netstring. Liefert die Rohantwort als String.
        """
        if not self._connect():
            return ""
        obj = {"command": command}
        if params:
            obj["params"] = params
        if token:
            obj["token"] = token
        try:
            payload = json.dumps(obj, separators=(",", ":"))
            self._send_netstring(payload)
            try:
                data = self.sock.recv(4096)
            except Exception:
                return ""
            resp = data.decode("utf-8", "ignore")
            logger.debug("baresip resp (%s): %s", command, resp.strip().replace("\n", " | "))
            return resp
        except Exception as e:
            logger.error("baresip cmd fehlgeschlagen (%s): %s", command, e)
            self.close()
            return ""

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except:
            pass
        self.sock = None

bs = BaresipCtrl(BS_HOST, BS_PORT, BS_READ_TIMEOUT)


# ---------- Telefonsteuerung ----------
def dial_number(num: str):
    global call_in_progress
    call_in_progress = True
    dialtone_stop()
    logger.info("Waehle via baresip (JSON): %s", num)
    bs.cmd("dial", num)

def hangup_all():
    global call_in_progress
    logger.info("Haenge auf (baresip JSON)")
    bs.cmd("hangup")
    call_in_progress = False
    dialtone_stop()

def answer_call():
    global call_in_progress
    logger.info("Nehme an (baresip JSON)")
    bs.cmd("accept")
    call_in_progress = True
    dialtone_stop()


# ---------- Klingelsteuerung (ueber ring_control.py) ----------
def ring_start():
    subprocess.Popen(
        ["/usr/local/retrophone/ring_control.py", "start"],
        close_fds=True
    )

def ring_stop():
    subprocess.call(
        ["/usr/local/retrophone/ring_control.py", "stop"]
    )


# ---------- Dialtone Steuerung ----------
def dialtone_start():
    global dialtone_proc
    if not os.path.exists(DIALTONE_WAV):
        return
    if dialtone_proc is not None and dialtone_proc.poll() is None:
        return
    try:
        dialtone_proc = subprocess.Popen(
            ["aplay", "-q", DIALTONE_WAV],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        logger.info("Dialtone gestartet")
    except Exception as e:
        logger.error("Dialtone start fehlgeschlagen: %s", e)
        dialtone_proc = None

def dialtone_stop():
    global dialtone_proc
    if dialtone_proc is not None:
        try:
            dialtone_proc.terminate()
        except Exception:
            pass
        dialtone_proc = None


# ---------- Incoming-Call-Parsing ----------
def parse_call_states(resp: str):
    """
    Sehr einfache Auswertung der baresip-Antwort (JSON-Events im Text).
    Wir suchen nur nach Stichwoertern im Text.
    """
    if not resp:
        return False, False, False
    low = resp.lower()
    incoming = ("call_incoming" in low) or (" incoming " in low)
    active = ("call_established" in low or
              "call_confirmed" in low or
              "call_answered" in low or
              " connected " in low)
    ended  = ("call_closed" in low or
              " terminated" in low or
              " idle " in low)
    return incoming, active, ended


# ---------- Hauptprogramm ----------
def main():
    global call_in_progress
    gpio_setup()

    number = ""
    pulse_count = 0
    last_digit_time = 0.0

    # letzte Zustände fuer Aenderungs Logik
    last_hook_raw    = GPIO.input(PIN_HOOK)
    last_pulse_state = GPIO.input(PIN_PULSE)
    last_pos1_state  = GPIO.input(PIN_POS1)
    last_hook        = offhook_from_raw(last_hook_raw)

    # Klingel- / Call-Status (persistente Flags)
    ringing_now = False
    last_calls_poll = 0.0
    last_incoming_seen = 0.0
    incoming_flag = False
    active_flag   = False
    ended_flag    = False

    logger.info(
        "RetroPhone Daemon gestartet (Log-Level %s), Initial GPIO Status: HOOK=%d PULSE=%d POS1=%d",
        LOG_LEVEL, last_hook_raw, last_pulse_state, last_pos1_state
    )

    try:
        while True:
            now = time.time()

            # Rohwerte lesen
            hook_raw    = GPIO.input(PIN_HOOK)
            pulse_state = GPIO.input(PIN_PULSE)
            pos1_state  = GPIO.input(PIN_POS1)
            cur_hook    = offhook_from_raw(hook_raw)

            # GPIO Aenderungen loggen
            if (hook_raw != last_hook_raw or
                pulse_state != last_pulse_state or
                pos1_state != last_pos1_state):
                logger.info(
                    "GPIO Status: HOOK=%d PULSE=%d POS1=%d",
                    hook_raw, pulse_state, pos1_state
                )
                last_hook_raw    = hook_raw
                last_pos1_state  = pos1_state

            # --- baresip listcalls pollen fuer eingehende/aktive Calls ---
            if now - last_calls_poll >= CALLS_POLL_SEC:
                resp = bs.cmd("listcalls")
                inc, act, end = parse_call_states(resp)
                incoming_flag = inc
                active_flag   = act
                ended_flag    = end
                last_calls_poll = now
                if inc:
                    last_incoming_seen = now
                if end and not act:
                    # Call wirklich beendet
                    call_in_progress = False

            # --- Klingellogik fuer eingehende Calls ---
            need_ring = incoming_flag and not cur_hook  # nur klingeln, wenn Hoerer aufliegt

            if ringing_now:
                must_stop = False

                # Watchdog: laenger keine incoming Info -> stoppen
                if (now - last_incoming_seen) > RING_WATCHDOG_SEC:
                    must_stop = True

                # Call beendet oder bereits aktiv -> Klingel aus
                if ended_flag or active_flag:
                    must_stop = True

                if cur_hook:
                    # Hoerer abgehoben -> Klingel aus, Anruf annehmen (in Hook-Block)
                    must_stop = True

                if must_stop:
                    logger.info("Klingel AUS (incoming=%s active=%s ended=%s)",
                                incoming_flag, active_flag, ended_flag)
                    ring_stop()
                    ringing_now = False

            if not ringing_now and need_ring:
                logger.info("Klingel AN (incoming call erkannt)")
                ring_start()
                ringing_now = True

            # --- Hook-Erkennung (Booleans) ---
            if cur_hook != last_hook:
                logger.info("Hook-Status: %s", "OFFHOOK" if cur_hook else "ONHOOK")
                if not cur_hook:
                    # Hoerer aufgelegt
                    if number or pulse_count:
                        logger.info("Wahl abgebrochen (Onhook)")
                        number = ""
                        pulse_count = 0
                    hangup_all()
                else:
                    # Hoerer abgehoben
                    if incoming_flag or active_flag:
                        # Egal ob Klingel noch aktiv ist oder nicht:
                        logger.info("OFFHOOK bei Call (incoming=%s active=%s) -> annehmen",
                                    incoming_flag, active_flag)
                        ring_stop()
                        ringing_now = False
                        answer_call()
                    elif not call_in_progress:
                        # kein Call -> Dialtone ueber Logik weiter unten
                        pass
                last_hook = cur_hook

            # --- Waehl-Logik nur bei abgehobenem Hoerer ---
            if cur_hook:
                # Impulsflanke erfassen (STEIGENDE Flanke: 0 -> 1, da 1 = Impuls aktiv)
                if pulse_state == 1 and last_pulse_state == 0:
                    t0 = time.time()
                    while GPIO.input(PIN_PULSE) == 1:
                        time.sleep(DEBOUNCE)
                    high_dur = time.time() - t0
                    if MIN_PULSE_LOW <= high_dur <= MAX_PULSE_LOW:
                        pulse_count += 1
                        logger.info(
                            "Impuls erkannt, Pulse-Count=%d (high_dur=%.4f)",
                            pulse_count, high_dur
                        )

                # Ende der Impulsreihe (Pause nach LOW, da Ruhe = 0)
                if last_pulse_state == 1 and pulse_state == 0:
                    pause_start = time.time()
                    new_impulse = False
                    while time.time() - pause_start < 0.25:
                        if GPIO.input(PIN_PULSE) == 1:
                            new_impulse = True
                            break
                        time.sleep(0.01)
                    if not new_impulse and pulse_count > 0:
                        digit = pulse_count % 10
                        if digit == 0:
                            digit = 0
                        number += str(digit)
                        last_digit_time = time.time()
                        logger.info("Ziffer erkannt: %s  Nummer bisher: %s", digit, number)
                        pulse_count = 0

                # Timeout: komplette Nummer waehlen
                if number and (time.time() - last_digit_time) > DIAL_TIMEOUT:
                    dial_number(number)
                    number = ""
                    pulse_count = 0
            else:
                # Hoerer aufgelegt, sicherheitshalber alles resetten
                if number or pulse_count:
                    logger.info("Wahl abgebrochen (Hoerer aufgelegt)")
                number = ""
                pulse_count = 0

            # Dialtone Status steuern
            # Nur wenn:
            #  - Hoerer abgehoben
            #  - keine Nummer in Eingabe
            #  - kein Call aktiv
            #  - kein eingehender Call
            want_dialtone = (cur_hook and
                             (not number) and
                             pulse_count == 0 and
                             (not call_in_progress) and
                             (not incoming_flag) and
                             (not active_flag))

            if want_dialtone:
                dialtone_start()
            else:
                dialtone_stop()

            # letzten Puls Zustand aktualisieren
            last_pulse_state = pulse_state

            time.sleep(0.03)

    except KeyboardInterrupt:
        logger.info("Daemon beendet (KeyboardInterrupt)")
    except Exception as e:
        logger.exception("Fehler im Daemon: %s", e)
    finally:
        try:
            ring_stop()
        except Exception:
            pass
        dialtone_stop()
        bs.close()
        GPIO.cleanup()
        logger.info("GPIO cleanup abgeschlossen")

if __name__ == "__main__":
    main()
