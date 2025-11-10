# ☎️ Retro Rotary SIP Phone  
**Convert a classic rotary dial phone into a working SIP VoIP phone using a Raspberry Pi Zero 2 W, Debian Trixie, Baresip and Python 3**

[![Python 3](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Raspberry Pi Zero 2 W](https://img.shields.io/badge/Hardware-Raspberry%20Pi%20Zero%202%20W-red.svg)](https://www.raspberrypi.com/)
[![Flask](https://img.shields.io/badge/Flask-Web%20UI-green.svg)](https://flask.palletsprojects.com/)
[![License MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📚 Table of Contents
- [Overview](#-overview)
- [Features](#-features)
- [Hardware Setup](#-hardware-setup)
- [Software Installation](#-software-installation-step-by-step)
- [WLAN & Network Stability](#-wlan--network-stability)
- [Web Interface](#️-web-interface)
- [Log Files & Helper Tools](#-log-files--helper-tools)
- [Troubleshooting (Audio & SIP)](#-audio-troubleshooting)
- [Architecture Diagram](#-architecture-diagram-conceptual)
- [Credits & References](#-credits--references)
- [License](#-license)
- [Keywords & Support](#-keywords-for-discoverability)

---

## 🧭 Overview
This open-source project demonstrates how to interface **classic telephony hardware** — rotary dial, hook switch, and mechanical bells — with **modern VoIP systems**.  
Built on **Raspberry Pi Zero 2 W** running **Debian Trixie**, **Baresip**, and **Python 3**.

- 📞 Incoming / outgoing VoIP calls via Baresip  
- 🔔 Authentic mechanical ringing driven by GPIO  
- ⚙️ Pulse-dial decoding and SIP dialing  
- 🧠 Flask-based web interface for SIP, logs & services  
- 🔊 Dial-tone playback and full audio through USB headset  

---

## 🧩 Features
| Function | Description |
|-----------|--------------|
| ✅ Incoming calls | Mechanical bells ring; lifting handset answers |
| ✅ Outgoing calls | Rotary pulses decoded & sent to SIP |
| ✅ Dial tone | Analog-like dial tone playback |
| ✅ Web UI | Manage SIP, logs & restart services |
| ✅ GPIO monitoring | Check hook / dial / return contacts |
| ✅ Systemd services | Autostart & self-recovery |

---

## 🪛 Hardware Setup
| Signal | GPIO (BCM) | Description | Logic |
|---------|-------------|--------------|-------|
| HOOK | 18 | Handset switch | 0 = off-hook  1 = on-hook |
| PULSE | 23 | Rotary dial impulses | 1 = pulse active |
| POS1 | 24 | Dial return contact | 0 = dial turning |
| RING_A | 17 | Bell coil A | controlled by `ring_control.py` |
| RING_B | 27 | Bell coil B | optional second coil |

> The original Swiss pulse logic pulls to GND — no extra resistors required.

---

## ⚙️ Software Installation (Step by Step)
*(Keep your detailed setup commands and systemd service definitions here — they are already correct in your current repo.)*

---

## 📡 WLAN & Network Stability
The **Raspberry Pi Zero 2 W** uses the **Broadcom brcmfmac** Wi-Fi driver, which by default enables **power-saving**.  
During idle phases this can cause 🔻 lost SIP registrations, dropped Flask sessions, or temporary SSH timeouts.

### 1️⃣ Temporarily disable Power Save
```bash
sudo iw dev wlan0 set power_save off
```

### 2️⃣ Make it permanent (NetworkManager method)
```bash
sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf >/dev/null <<'EOF'
[connection]
wifi.powersave = 2
EOF

sudo systemctl restart NetworkManager
```

### 3️⃣ Without NetworkManager (Raspberry Pi OS Lite)
Edit `/etc/rc.local` and add before `exit 0`:
```bash
iw dev wlan0 set power_save off
```

### 4️⃣ Driver tuning for brcmfmac
```bash
sudo rmmod brcmfmac
sudo modprobe brcmfmac roamoff=1 feature_disable=0x82000
```

### 5️⃣ Firmware update
```bash
sudo apt install --reinstall firmware-brcm80211 -y
```

### 6️⃣ Verify
```bash
iw wlan0 get power_save
# Expected → Power save: off
```

✅ This completely stabilizes Wi-Fi connections for 24/7 operation — essential for baresip, the phone daemon and the web UI.

---

## 🖥️ Web Interface
Accessible at `http://<raspberrypi-ip>:8080`  

**Features**
- Edit SIP accounts  
- View logs (auto-refresh)  
- Restart services  
- Check service status (baresip / daemon / web)  

Credentials set via `retrophone-web.service` environment variables.

---

## 🧾 Log Files & Helper Tools
| File | Purpose |
|------|----------|
| `/var/log/retrophone/phone.log` | Main daemon (dial, hook, call state) |
| `/var/log/retrophone/ring.log` | Bell control |
| `journalctl -u baresip` | baresip logs |

**Helper scripts**
| Script | Function |
|---------|----------|
| `gpio_monitor.py` | Show live GPIO states |
| `gpio_hook_monitor.py` | Hook only |
| `ring_control.py` | Manual ring test |

---

## 🎧 Audio Troubleshooting
If baresip reports `Unknown error -22`, check your ALSA config:
```text
audio_player alsa,plughw:0,0
audio_source alsa,plughw:0,0
audio_alert alsa,null
audio_srate 48000
```
Playback test:
```bash
aplay -D plughw:0,0 /usr/local/retrophone/dialtone.wav
```

---

## 🔬 Architecture Diagram (conceptual)
```
+--------------------------------------------------------------+
|                     Retro Rotary SIP Phone                   |
|--------------------------------------------------------------|
| Rotary Dial | Hook Switch | Bell Coils | USB Audio |
|--------------------------------------------------------------|
| GPIO 23    | GPIO 18     | GPIO 17/27 | USB Headset |
|--------------------------------------------------------------|
| phone_daemon.py → baresip (SIP stack) |
| ring_control.py → GPIO driver |
| webapp.py (Flask UI) → SIP + Logs + Control |
+--------------------------------------------------------------+
```

---

## 🧠 Credits & References
- Inspired by [CrazyRobMiles / RaspberryPi-DialTelephone](https://github.com/CrazyRobMiles/RaspberryPi-DialTelephone)  
- VoIP engine [baresip](https://github.com/baresip/baresip)  
- Community resources: [baresip Discussions](https://github.com/baresip/baresip/discussions) · [r/raspberry_pi](https://reddit.com/r/raspberry_pi)

---

## 🪪 License
Released under the **MIT License**.  
Third-party components retain their original licenses.

---

## 🔎 Keywords for Discoverability
Retro rotary phone Raspberry Pi • Raspberry Pi Zero 2 W SIP phone • baresip python integration • GPIO pulse dialing • retro VoIP hardware project • mechanical bell driver • Flask web UI • Debian Trixie Raspberry Pi • DIY vintage telephone • embedded Linux telephony

---

## ⭐ Support & Collaboration
If you love vintage hardware and open-source telephony, give this project a ⭐ on GitHub or share your own build via pull request or issue!
