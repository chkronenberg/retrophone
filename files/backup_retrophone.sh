#!/bin/bash
set -euo pipefail

BACKUP_DIR="/home/pi/retrophone-backups"
MODE="${1:-backup}"
STATUS_FILE="/run/retrophone/backup-status.json"

write_status() {
  local state="$1"
  local percent="$2"
  local message="$3"
  local tmp="${STATUS_FILE}.tmp"
  mkdir -p "$(dirname "$STATUS_FILE")"
  printf '{"state":"%s","percent":%s,"message":"%s","updated":"%s"}\n' \
    "$state" "$percent" "$message" "$(date -Iseconds)" > "$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$STATUS_FILE"
}

backup_failed() {
  write_status "error" 100 "Backup fehlgeschlagen"
}

usage() {
  echo "Usage:"
  echo "  $0 backup"
  echo "  sudo $0 restore <backupfile.tar.gz>"
}

backup() {
  trap backup_failed ERR
  DATE="$(date +%Y%m%d-%H%M%S)"
  WORK_DIR="/tmp/retrophone-backup-$DATE"
  ARCHIVE="$BACKUP_DIR/retrophone-disaster-recovery-$DATE.tar.gz"

  mkdir -p "$BACKUP_DIR"
  mkdir -p "$WORK_DIR"

  write_status "running" 5 "Backup wird vorbereitet"
  echo "RetroPhone Backup startet: $DATE"

  if [ -x /usr/local/retrophone/persist_logs.sh ]; then
    /usr/local/retrophone/persist_logs.sh || true
  fi

  write_status "running" 15 "Protokolle und Zeitpläne werden gesichert"

  sudo crontab -l > "$WORK_DIR/root-crontab.txt" 2>/dev/null || true
  crontab -l > "$WORK_DIR/pi-crontab.txt" 2>/dev/null || true

  mkdir -p "$WORK_DIR/systemd-cat"
  for svc in phone-daemon.service retrophone-web.service baresip.service retrophone-persist-logs.service; do
    systemctl cat "$svc" > "$WORK_DIR/systemd-cat/$svc.txt" 2>/dev/null || true
    systemctl status "$svc" --no-pager -l > "$WORK_DIR/systemd-cat/$svc.status.txt" 2>/dev/null || true
  done

  write_status "running" 30 "System- und Netzwerkinformationen werden gesammelt"

  dpkg --get-selections > "$WORK_DIR/packages.txt" 2>/dev/null || true
  apt-mark showmanual > "$WORK_DIR/manual-packages.txt" 2>/dev/null || true

  ip addr > "$WORK_DIR/ip-addr.txt" 2>/dev/null || true
  ip route > "$WORK_DIR/ip-route.txt" 2>/dev/null || true
  iwconfig > "$WORK_DIR/iwconfig.txt" 2>/dev/null || true
  iw dev > "$WORK_DIR/iw-dev.txt" 2>/dev/null || true
  rfkill list > "$WORK_DIR/rfkill.txt" 2>/dev/null || true
  nmcli connection show > "$WORK_DIR/nmcli-connections.txt" 2>/dev/null || true
  nmcli device status > "$WORK_DIR/nmcli-device-status.txt" 2>/dev/null || true

  id pi > "$WORK_DIR/id-pi.txt" 2>/dev/null || true
  groups pi > "$WORK_DIR/groups-pi.txt" 2>/dev/null || true

  {
    echo "DATE=$DATE"
    echo
    echo "Hostname:"
    hostname || true
    echo
    echo "Kernel:"
    uname -a || true
    echo
    echo "OS:"
    cat /etc/os-release || true
    echo
    echo "Mounts:"
    findmnt || true
    echo
    echo "Swap:"
    swapon --show || true
    echo
    echo "Journal disk usage:"
    journalctl --disk-usage || true
    echo
    echo "Runtime:"
    ls -lah /run/retrophone 2>/dev/null || true
    echo
    echo "RetroPhone logs:"
    ls -lah /var/log/retrophone 2>/dev/null || true
  } > "$WORK_DIR/system-info.txt"

  write_status "running" 45 "Backup-Archiv wird erstellt"
  BACKUP_PATHS=(
    /usr/local/retrophone
    /etc/retrophone
    /etc/systemd
    /etc/tmpfiles.d
    /etc/sudoers.d
    /etc/systemd/network
    /etc/wpa_supplicant
    /etc/network
    /etc/modprobe.d
    /etc/udev/rules.d
    /etc/hostname
    /etc/hosts
    /etc/modules
    /home/pi/.baresip
    /boot/firmware
    /var/log/retrophone
    "$WORK_DIR"
  )
  EXISTING_PATHS=()
  for path in "${BACKUP_PATHS[@]}"; do
    if [ -e "$path" ]; then
      EXISTING_PATHS+=("$path")
    fi
  done
  sudo tar czf "$ARCHIVE" "${EXISTING_PATHS[@]}"

  write_status "running" 92 "Archiv wird abgeschlossen"
  sudo chown pi:pi "$ARCHIVE"
  rm -rf "$WORK_DIR"

  write_status "complete" 100 "Backup erfolgreich erstellt"
  trap - ERR

  echo "Backup fertig:"
  echo "$ARCHIVE"
  ls -lh "$ARCHIVE"
}

restore() {
  BACKUP_FILE="${2:-}"

  if [ -z "$BACKUP_FILE" ]; then
    usage
    exit 1
  fi

  if [ ! -f "$BACKUP_FILE" ]; then
    echo "Backup-Datei nicht gefunden: $BACKUP_FILE"
    exit 1
  fi

  echo "RetroPhone Restore startet:"
  echo "$BACKUP_FILE"

  sudo tar xzf "$BACKUP_FILE" -C /

  WORK_DIR="$(tar tzf "$BACKUP_FILE" | grep '^tmp/retrophone-backup-' | head -1 | cut -d/ -f1-2 || true)"

  if [ -n "$WORK_DIR" ] && [ -d "/$WORK_DIR" ]; then
    if [ -f "/$WORK_DIR/root-crontab.txt" ]; then
      sudo crontab "/$WORK_DIR/root-crontab.txt"
    fi

    if [ -f "/$WORK_DIR/pi-crontab.txt" ]; then
      crontab "/$WORK_DIR/pi-crontab.txt"
    fi
  fi

  sudo chmod +x /usr/local/retrophone/*.py 2>/dev/null || true
  sudo chmod +x /usr/local/retrophone/*.sh 2>/dev/null || true
  sudo chown -R pi:pi /usr/local/retrophone 2>/dev/null || true
  sudo chown -R pi:pi /home/pi/.baresip 2>/dev/null || true

  sudo systemctl daemon-reload
  sudo systemd-tmpfiles --create /etc/tmpfiles.d/retrophone.conf 2>/dev/null || true

  sudo systemctl enable baresip.service 2>/dev/null || true
  sudo systemctl enable phone-daemon.service 2>/dev/null || true
  sudo systemctl enable retrophone-web.service 2>/dev/null || true
  sudo systemctl enable retrophone-persist-logs.service 2>/dev/null || true

  echo "Restore abgeschlossen."
  echo "Bitte danach neu starten:"
  echo "sudo reboot"
}

case "$MODE" in
  backup)
    backup
    ;;
  restore)
    restore "$@"
    ;;
  *)
    usage
    exit 1
    ;;
esac
