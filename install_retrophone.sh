#!/bin/bash
set -e

echo "=== RetroPhone Installer ==="

# --- Einstellungen anpassen ---------------------------------------------------

# Linux-User, unter dem baresip, Phone-Daemon und Webapp laufen (Standard: pi)
RETRO_USER="${SUDO_USER:-pi}"
RETRO_HOME="$(getent passwd "$RETRO_USER" | cut -d: -f6)"

# HIER ANPASSEN: Basis-URL zu deinem GitHub-Repo (raw)
# Beispiel: https://raw.githubusercontent.com/deinuser/retrophone/main
RAW_BASE="https://github.com/chkronenberg/retrophone/tree/main/files"

# Datei-Liste, die aus dem Repo geholt wird
PY_FILES=(
  "phone_daemon.py"
  "ring_control.py"
  "webapp.py"
  "gpio_monitor.py"
  "gpio_hook_monitor.py"
)

RETRO_DIR="/usr/local/retrophone"
RETRO_LOG_DIR="/var/log/retrophone"
RETRO_RUN_DIR="/run/retrophone"

# --- Helpers -------------------------------------------------------------------

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Fehler: Befehl '$1' nicht gefunden. Bitte installieren oder PATH prüfen."
    exit 1
  fi
}

# --- Root-Prüfung --------------------------------------------------------------

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte als root oder mit sudo ausführen."
  exit 1
fi

echo "Installiere für User: $RETRO_USER (Home: $RETRO_HOME)"

# --- 2. Pakete -----------------------------------------------------------------

echo "==> Pakete installieren (apt-get)..."

sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y \  
  python3 python3-pip python3-flask python3-gpiozero python3-rpi.gpio \  
  alsa-utils sox git \  
  build-essential libasound2-dev libssl-dev libz-dev libopus-dev libavformat-dev \  
  libavcodec-dev libavutil-dev libre-dev libspandsp-dev libreadline-dev \  
  uuid-dev libedit-dev libmicrohttpd-dev systemd python3-venv \ 
  baresip libasound2


# --- 3. baresip kompilieren (falls nicht vorhanden) ---------------------------

require_cmd baresip

# --- 4. baresip initial starten, um Konfig zu erzeugen ------------------------

echo "==> baresip Konfiguration für $RETRO_USER erzeugen (falls nötig)..."

sudo -u "$RETRO_USER" bash -c '
  if [ ! -d "/etc/retrophone/baresip/config" ]; then
    mkdir -p "/etc/retrophone/baresip"
  fi
  if [ ! -f "/etc/retrophone/baresip/config" ]; then
    echo "Starte baresip einmalig zur Konfig-Erzeugung..."
    baresip -e "quit" || true
  fi
'

BARESIP_CONFIG="/etc/retrophone/baresip/config"
BARESIP_ACCOUNTS="/etc/retrophone/baresip/accounts"

if [ ! -f "$BARESIP_CONFIG" ]; then
  echo "Fehler: /etc/retrophone/baresip/config wurde nicht erzeugt. baresip-Start überprüfen."
  exit 1
fi

# --- 5. baresip config anpassen ------------------------------------------------

echo "==> baresip Konfiguration anpassen..."

# Audio und ctrl_tcp in config setzen oder ersetzen
modify_or_add() {
  local key="$1"
  local value="$2"
  if grep -q "^$key" "$BARESIP_CONFIG"; then
    sed -i "s#^$key .*#$key $value#" "$BARESIP_CONFIG"
  else
    echo "$key $value" >>"$BARESIP_CONFIG"
  fi
}

# alte ring_aufile Zeilen entfernen
sed -i '/^ring_aufile /d' "$BARESIP_CONFIG"

modify_or_add "audio_player" "alsa,plughw:0,0"
modify_or_add "audio_source" "alsa,plughw:0,0"
modify_or_add "audio_alert"  "alsa,null"
modify_or_add "audio_srate"  "48000"
echo "ring_aufile none" >>"$BARESIP_CONFIG"
modify_or_add "ctrl_tcp_listen" "0.0.0.0:4444"

# --- 6. zentrale Accounts-Datei unter /etc ------------------------------------

echo "==> SIP-Accounts nach /etc/retrophone/baresip verschieben..."

ETC_BARESIP_DIR="/etc/retrophone/baresip"
ETC_ACCOUNTS="$ETC_BARESIP_DIR/accounts"

mkdir -p "$ETC_BARESIP_DIR"

# falls alte Accounts im Home liegen und /etc noch leer ist -> verschieben
if [ -f "$BARESIP_ACCOUNTS" ] && [ ! -f "$ETC_ACCOUNTS" ]; then
  mv "$BARESIP_ACCOUNTS" "$ETC_ACCOUNTS"
fi

# wenn /etc noch keine Accounts hat, leere Vorlage erzeugen
if [ ! -f "$ETC_ACCOUNTS" ]; then
  cat >"$ETC_ACCOUNTS" <<EOF
<sip:USER@sip.provider.tld>;auth_user=USER;auth_pass=PASSWORD;outbound="sip:sip.provider.tld;transport=udp";regint=300
EOF
fi

chown -R "$RETRO_USER:$RETRO_USER" /etc/retrophone
chmod 640 "$ETC_ACCOUNTS"

# Symlink zurück ins Home, damit baresip dieselbe Datei nutzt
ln -sf "$ETC_ACCOUNTS" "$BARESIP_ACCOUNTS"

# --- 7. Projektverzeichnisse --------------------------------------------------

echo "==> Projektverzeichnisse anlegen..."

mkdir -p "$RETRO_DIR" "$RETRO_LOG_DIR" "$RETRO_RUN_DIR"
chown -R "$RETRO_USER:$RETRO_USER" "$RETRO_DIR" "$RETRO_LOG_DIR" "$RETRO_RUN_DIR"

# --- 8. Python-Files von GitHub laden ----------------------------------------

echo "==> Python-Files von GitHub laden..."

for f in "${PY_FILES[@]}"; do
  echo "   -> $f"
  wget -q -O "$RETRO_DIR/$f" "$RAW_BASE/$f"
done

chmod +x "$RETRO_DIR"/*.py
chown "$RETRO_USER:$RETRO_USER" "$RETRO_DIR"/*.py

# --- 9. Dialtone erzeugen -----------------------------------------------------

DIALTONE="$RETRO_DIR/dialtone.wav"
if [ ! -f "$DIALTONE" ]; then
  echo "==> Dialtone erzeugen..."
  sox -n -r 8000 -c 1 "$DIALTONE" synth 10 sin 425
  chown "$RETRO_USER:$RETRO_USER" "$DIALTONE"
fi

# --- 10. sudoers für Service-Restarts ----------------------------------------

echo "==> sudoers-Regeln für Service-Restarts anlegen..."

SUDOERS_FILE="/etc/sudoers.d/retrophone"
cat >"$SUDOERS_FILE" <<EOF
$RETRO_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart baresip.service
$RETRO_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart phone-daemon.service
$RETRO_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart retrophone-web.service
EOF

chmod 440 "$SUDOERS_FILE"

# --- 11. logrotate für Retrophone-Logs ---------------------------------------

echo "==> logrotate Konfiguration für Retrophone-Logs..."

LOGROTATE_FILE="/etc/logrotate.d/retrophone"
cat >"$LOGROTATE_FILE" <<EOF
/var/log/retrophone/phone.log /var/log/retrophone/ring.log {
    daily
    rotate 7
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
    create 640 $RETRO_USER $RETRO_USER
}
EOF

# Rechte sofort einmal korrigieren
touch "$RETRO_LOG_DIR/phone.log" "$RETRO_LOG_DIR/ring.log"
chown "$RETRO_USER:$RETRO_USER" "$RETRO_LOG_DIR/phone.log" "$RETRO_LOG_DIR/ring.log"
chmod 640 "$RETRO_LOG_DIR/phone.log" "$RETRO_LOG_DIR/ring.log"

# --- 12. systemd Units --------------------------------------------------------

echo "==> systemd Units anlegen..."

# baresip.service
cat >/etc/systemd/system/baresip.service <<EOF
[Unit]
Description=Baresip SIP Client
After=network.target sound.target

[Service]
User=$RETRO_USER
ExecStart=/usr/local/bin/baresip -f $RETRO_HOME/.baresip
Restart=on-failure
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF

# phone-daemon.service
cat >/etc/systemd/system/phone-daemon.service <<EOF
[Unit]
Description=RetroPhone Dial/Hook Daemon
After=network.target sound.target baresip.service

[Service]
ExecStart=/usr/bin/python3 $RETRO_DIR/phone_daemon.py
Restart=on-failure
User=$RETRO_USER
Group=$RETRO_USER
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF

# retrophone-web.service
cat >/etc/systemd/system/retrophone-web.service <<EOF
[Unit]
Description=RetroPhone Web UI
After=network.target

[Service]
ExecStart=/usr/bin/python3 $RETRO_DIR/webapp.py
WorkingDirectory=$RETRO_DIR
User=$RETRO_USER
Group=$RETRO_USER
Environment=RETRO_WEB_USER=admin
Environment=RETRO_WEB_PASS=secret
Restart=on-failure
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF

# --- 13. systemd reload & enable ---------------------------------------------

echo "==> systemd neu laden und Services aktivieren..."

systemctl daemon-reload
systemctl enable baresip.service phone-daemon.service retrophone-web.service
systemctl restart baresip.service
systemctl restart phone-daemon.service
systemctl restart retrophone-web.service

echo "=== Installation abgeschlossen ==="
echo "Weboberfläche: http://<IP-des-Pi>:8080  (Login: admin / secret)"
echo "SIP-Account-Datei: /etc/retrophone/baresip/accounts"
