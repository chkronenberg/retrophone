# Changelog

## v2.0 — 2026-09-13

### Highlights

- Completely redesigned responsive Web UI with live service, temperature and WLAN status
- Central `/etc/retrophone/config.json` for SIP, GPIO, audio, logging and expert settings
- Configurable phone-daemon log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)
- Persistent history of the last 20 calls
- Web-based ALSA handset and microphone volume controls
- Disaster-recovery backups with progress display
- Reduced repetitive phone-daemon and baresip log output
- Updated systemd-networkd and wpa_supplicant backup coverage
- New RetroPhone favicon

### Installation and migration

- Updated installer for the current `/etc/retrophone/baresip` layout
- Added a safe example configuration without SIP credentials
- Added runtime-directory creation and the required restricted sudo rules
- Existing installations retain their local `/etc/retrophone/config.json`

## v1.0

- Initial public RetroPhone release
