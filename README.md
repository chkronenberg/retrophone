# ☎️ RetroPhone

Convert a classic Swiss rotary telephone into a working SIP phone using a Raspberry Pi Zero 2 W, Debian Trixie, baresip and Python 3.

[![Release v2.0](https://img.shields.io/badge/release-v2.0-brightgreen.svg)](CHANGELOG.md)
[![Python 3](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

## Overview

RetroPhone connects the original handset switch, rotary dial and mechanical bell to modern VoIP services while preserving the authentic operation of the telephone.

- Incoming and outgoing SIP calls through baresip
- Pulse-dial decoding through Raspberry Pi GPIO
- Mechanical ringing with configurable cadence and frequency
- Dial tone through an ALSA audio device
- Responsive Web UI for configuration and monitoring
- Persistent history of the last 20 calls
- Disaster-recovery backups with progress reporting

## Hardware

The reference build uses:

- Swiss PTT Modell 29 rotary telephone
- Raspberry Pi Zero 2 W
- Two D4184 MOSFET channels for the bell coils
- Two 1N4007 flyback diodes
- 12 V power supply with 5 V step-down and bell-voltage boost converters
- Logitech H340 USB headset electronics for handset audio

The complete wiring diagram is available in [media/20251110_wiring_diagram.png](media/20251110_wiring_diagram.png). A printable internal holder is included as [media/holder.stl](media/holder.stl).

### Default GPIO mapping

| Signal | BCM GPIO | Function |
|---|---:|---|
| Hook | 18 | Handset switch |
| Pulse | 23 | Rotary-dial pulses |
| Dial position | 24 | Dial return contact |
| Ring A | 17 | First bell coil |
| Ring B | 27 | Second bell coil |

All GPIO assignments can be changed later in the Web UI.

## Installation

Start with Raspberry Pi OS Lite or Debian Trixie, enable SSH and connect the Pi to the network. Then run:

```bash
cd /tmp
wget -O install_retrophone.sh \
  https://raw.githubusercontent.com/chkronenberg/retrophone/main/install_retrophone.sh
chmod +x install_retrophone.sh
sudo ./install_retrophone.sh
```

The installer:

- installs Python, Flask, GPIO, ALSA, sox and baresip
- installs the application under `/usr/local/retrophone`
- creates `/etc/retrophone/config.json`
- configures baresip under `/etc/retrophone/baresip`
- creates persistent log and call-history files
- installs restricted sudo rules for the Web UI
- installs and enables the required systemd services

Existing `/etc/retrophone/config.json` and baresip account files are retained.

After installation, open:

```text
http://<raspberry-pi-address>:8080
```

The initial Web UI credentials are defined in `retrophone-web.service`. Change the default password before exposing the interface beyond a trusted network.

## Configuration

The central configuration file is:

```text
/etc/retrophone/config.json
```

A safe template without credentials is provided as [files/config.example.json](files/config.example.json).

Most values can be changed directly in the Web UI:

- SIP user, domain, password, outbound proxy and transport
- GPIO assignments
- handset and microphone volume
- phone-daemon log level
- dialing and debounce timing
- pulse limits and call polling
- baresip control host, port and timeouts
- bell toggle interval, frequency and cadence

The active baresip files are stored under:

```text
/etc/retrophone/baresip
```

Do not commit the active `config.json`, baresip account file, WLAN password or Web UI password to Git.

## Web interface

The v2 dashboard provides:

- live status and restart controls for phone daemon, baresip and Web UI
- CPU temperature and WLAN connection information
- SIP configuration summary
- backup status and creation
- recent calls and combined recent logs
- separate pages for calls, logs, services and settings
- ALSA playback and microphone controls
- responsive desktop and mobile layout

## Call history

The last 20 calls are stored in:

```text
/var/log/retrophone/calls.jsonl
```

New incoming calls are written immediately and synchronized to disk. The history is loaded again after a reboot and is included in disaster-recovery backups.

## Backup and recovery

Backups can be started from the dashboard. The progress view reports preparation, data collection, archive creation and completion.

The default destination is:

```text
/home/pi/retrophone-backups
```

The backup includes the RetroPhone application, central configuration, baresip configuration, systemd units, sudo rules, `systemd-networkd`, `wpa_supplicant` and persistent logs.

The progress percentage is phase-based because the final compressed archive size is not known in advance.

Manual backup:

```bash
sudo /usr/local/retrophone/backup_retrophone.sh backup
```

Restore a selected archive:

```bash
sudo /usr/local/retrophone/backup_retrophone.sh restore \
  /home/pi/retrophone-backups/<backup-file>.tar.gz
```

Review a backup before restoring it. A restore overwrites system configuration files contained in the archive.

## Services and logs

| Service | Purpose |
|---|---|
| `baresip.service` | SIP client and audio connection |
| `phone-daemon.service` | Hook, rotary dial and call control |
| `retrophone-web.service` | Web dashboard and configuration |

Useful commands:

```bash
systemctl status baresip.service phone-daemon.service retrophone-web.service
journalctl -u baresip.service -f
tail -f /run/retrophone/phone.log
tail -f /run/retrophone/ring.log
tail -f /var/log/retrophone/calls.jsonl
```

The phone-daemon log level can be set to `DEBUG`, `INFO`, `WARNING` or `ERROR` in the Web UI. Repetitive baresip polling messages are hidden at normal log levels.

Diagnostic tools are included in `files/`:

- `gpio_monitor.py`
- `gpio_hook_monitor.py`
- `ring_control.py`
- `persist_logs.sh`

## WLAN stability

The current reference setup uses `wpa_supplicant` for WLAN authentication and `systemd-networkd` for IP configuration.

For a hidden SSID, add `scan_ssid=1` to its `network` block in `/etc/wpa_supplicant/wpa_supplicant.conf`.

For stable 2.4 GHz operation, consider:

- WPA2-PSK with AES/CCMP
- disabling WPA2/WPA3 transition mode if rekeying fails
- disabling 802.11r/Fast Roaming for this device
- disabling WLAN power saving
- avoiding weak signal levels

Check the current connection:

```bash
ip -4 address show wlan0
ip route
cat /proc/net/wireless
journalctl -b | grep -Ei 'wlan0|wpa|dhcp|deauth|disconnect'
```

A static address belongs in a `systemd-networkd` `.network` file, not in `wpa_supplicant.conf`.

## Audio troubleshooting

List available ALSA devices:

```bash
aplay -l
arecord -l
```

Test the dial tone:

```bash
aplay -D plughw:0,0 /usr/local/retrophone/dialtone.wav
```

If the configured USB device is temporarily unavailable, the Web UI continues to start and reports the mixer issue without stopping the telephone services.

## Project files

| File | Purpose |
|---|---|
| `files/phone_daemon.py` | Rotary dial, hook and call control |
| `files/ring_control.py` | Mechanical bell control |
| `files/webapp.py` | Flask Web UI |
| `files/backup_retrophone.sh` | Backup and restore |
| `files/persist_logs.sh` | Runtime-log persistence |
| `files/config.example.json` | Credential-free configuration template |
| `files/favicon.ico` | Browser icon |
| `install_retrophone.sh` | Automated installation |

## Release history

See [CHANGELOG.md](CHANGELOG.md) and the [GitHub releases](https://github.com/chkronenberg/retrophone/releases).

## License

Released under the [MIT License](LICENSE). Third-party components retain their respective licenses.

## Credits

- Electronics and wiring inspired by [CrazyRobMiles/RaspberryPi-DialTelephone](https://github.com/CrazyRobMiles/RaspberryPi-DialTelephone)
- SIP engine: [baresip](https://github.com/baresip/baresip)

If this project helped you, consider starring the repository or sharing your build through an issue or pull request.
