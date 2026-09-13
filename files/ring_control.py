#!/usr/bin/env python3
import os, sys, time, signal, json, logging, logging.handlers

import RPi.GPIO as GPIO

CONFIG_PATH = os.environ.get("RETRO_CONFIG_PATH", "/etc/retrophone/config.json")
try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
        CONFIG = json.load(config_file)
    if not isinstance(CONFIG, dict):
        CONFIG = {}
except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError):
    CONFIG = {}

GPIO_CONFIG = CONFIG.get("gpio", {}) if isinstance(CONFIG.get("gpio", {}), dict) else {}
RING_CONFIG = CONFIG.get("ring", {}) if isinstance(CONFIG.get("ring", {}), dict) else {}
PATH_CONFIG = CONFIG.get("paths", {}) if isinstance(CONFIG.get("paths", {}), dict) else {}

# === Pins ===
RING_A_PIN = int(GPIO_CONFIG.get("ring_a", 17))
RING_B_PIN = int(GPIO_CONFIG.get("ring_b", 27))

# Wenn du nur 1 Spule hast, auf True setzen
SINGLE_COIL = bool(RING_CONFIG.get("single_coil", False))

# Umschaltintervall der Spulen (Sekunden)
TOGGLE_INTERVAL = float(RING_CONFIG.get("toggle_interval", 0.02))

#LOG_DIR = "/var/log/retrophone"
LOG_DIR  = str(PATH_CONFIG.get("runtime_dir", "/run/retrophone"))
PID_DIR = LOG_DIR
PID_FILE = os.path.join(PID_DIR, "ring.pid")
LOG_PATH = os.path.join(LOG_DIR, "ring.log")

# === Logging ===
os.makedirs(LOG_DIR, exist_ok=True)
logger = logging.getLogger("ring")
logger.setLevel(logging.INFO)
handler = logging.handlers.TimedRotatingFileHandler(LOG_PATH, when="midnight", backupCount=7, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)

stop_flag = False

def sigterm_handler(signum, frame):
    global stop_flag
    stop_flag = True
    logger.info("Signal %s empfangen -> stop", signum)

def gpio_setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(RING_A_PIN, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(RING_B_PIN, GPIO.OUT, initial=GPIO.LOW)

def gpio_all_low():
    try:
        GPIO.output(RING_A_PIN, GPIO.LOW)
        GPIO.output(RING_B_PIN, GPIO.LOW)
    except Exception:
        pass

def gpio_cleanup():
    try:
        gpio_all_low()
        GPIO.cleanup()
    except Exception:
        pass

def ensure_pid_dir():
    os.makedirs(PID_DIR, exist_ok=True)

def read_pid():
    try:
        with open(PID_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return None

def write_own_pid():
    ensure_pid_dir()
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

def remove_pid():
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass

def parse_cadence():
    cad = str(RING_CONFIG.get("cadence", os.environ.get("RINGCADENCE", "1000,3000")))
    try:
        on_ms, off_ms = [int(x.strip()) for x in cad.split(",")]
        on_ms = max(100, min(on_ms, 10000))
        off_ms = max(100, min(off_ms, 10000))
        return on_ms/1000.0, off_ms/1000.0
    except Exception:
        logger.warning("Ungültige RINGCADENCE '%s' -> 1000,3000", cad)
        return 1.0, 3.0

def ring_burst(duration_s):
    """Lässt für duration_s Sekunden klingeln."""
    end_t = time.time() + duration_s
    if SINGLE_COIL:
        # Eine Spule rhythmisch pulsen
        while not stop_flag and time.time() < end_t:
            GPIO.output(RING_A_PIN, GPIO.HIGH)
            time.sleep(TOGGLE_INTERVAL)
            GPIO.output(RING_A_PIN, GPIO.LOW)
            time.sleep(TOGGLE_INTERVAL)
    else:
        # Zwei Spulen alternierend
        state = False
        while not stop_flag and time.time() < end_t:
            state = not state
            GPIO.output(RING_A_PIN, GPIO.HIGH if state else GPIO.LOW)
            GPIO.output(RING_B_PIN, GPIO.LOW  if state else GPIO.HIGH)
            time.sleep(TOGGLE_INTERVAL)
        gpio_all_low()

def cmd_start():
    # Bereits laufend?
    old = read_pid()
    if old:
        try:
            os.kill(old, 0)
            logger.info("ring_control läuft bereits (PID %d)", old)
            # Safety: Pins auf Low
            gpio_setup(); gpio_all_low(); gpio_cleanup()
            return 0
        except Exception:
            # Stale PID
            remove_pid()

    # Im Vordergrund laufen, PID direkt vom echten Prozess schreiben
    signal.signal(signal.SIGTERM, sigterm_handler)
    signal.signal(signal.SIGINT,  sigterm_handler)

    write_own_pid()

    gpio_setup()
    gpio_all_low()

    on_s, off_s = parse_cadence()
    logger.info("Start ring loop (on=%.3fs off=%.3fs single=%s)", on_s, off_s, SINGLE_COIL)

    try:
        while not stop_flag:
            ring_burst(on_s)
            if stop_flag:
                break
            gpio_all_low()
            # Off-Phase abbrechbar schlafen
            slept = 0.0
            while not stop_flag and slept < off_s:
                time.sleep(0.05)
                slept += 0.05
    finally:
        logger.info("Stop ring loop, GPIO cleanup")
        gpio_cleanup()
        remove_pid()
    return 0

def cmd_stop():
    pid = read_pid()
    # Immer sofort pins low ziehen, egal was mit PID ist
    try:
        gpio_setup(); gpio_all_low(); gpio_cleanup()
    except Exception:
        pass

    if not pid:
        logger.info("ring_control nicht aktiv (kein PID)")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
        # Wartet bis zu 1.5 s
        for _ in range(30):
            try:
                os.kill(pid, 0)
                time.sleep(0.05)
            except OSError:
                break
        else:
            logger.warning("SIGTERM wirkungslos -> SIGKILL")
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception as e:
        logger.warning("Stop-Fehler: %s", e)
    finally:
        remove_pid()
        # Sicherheit
        try:
            gpio_setup(); gpio_all_low(); gpio_cleanup()
        except Exception:
            pass
        logger.info("ring_control gestoppt")
    return 0

def cmd_status():
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, 0)
            print("running")
            return 0
        except Exception:
            pass
    print("stopped")
    return 1

def cmd_oneshot(ms):
    gpio_setup()
    try:
        logger.info("Oneshot %d ms", ms)
        ring_burst(ms/1000.0)
        gpio_all_low()
    finally:
        gpio_cleanup()
    return 0

def main():
    if len(sys.argv) < 2:
        print("Usage: ring_control.py {start|stop|status|oneshot <ms>}", file=sys.stderr)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "start":
        sys.exit(cmd_start())
    elif cmd == "stop":
        sys.exit(cmd_stop())
    elif cmd == "status":
        sys.exit(cmd_status())
    elif cmd == "oneshot":
        if len(sys.argv) != 3:
            print("Usage: ring_control.py oneshot <ms>", file=sys.stderr)
            sys.exit(2)
        try:
            ms = int(sys.argv[2])
        except ValueError:
            print("Ungültige Zahl", file=sys.stderr)
            sys.exit(2)
        sys.exit(cmd_oneshot(ms))
    else:
        print("Usage: ring_control.py {start|stop|status|oneshot <ms>}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
