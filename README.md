# ☎️ Retro Rotary SIP Phone  
**Old Swiss Rotary Phone revived with Raspberry Pi Zero 2W, Debian Trixie, baresip, Python and real bells**

---

## 🧭 Overview

This project transforms an original Swiss rotary telephone into a **fully working SIP phone** with:

- 📞 Incoming and outgoing VoIP calls via **baresip**
- 🔔 Authentic **mechanical ringing** driven by GPIOs
- ⚙️ **Pulse dialing** recognition and SIP dialing
- 🧠 A Flask-based **web interface** to manage SIP accounts, logs, and services
- 🔊 Real **dial tone** playback and full audio via USB headset

> Built on a Raspberry Pi Zero 2 W (Debian Trixie / Bookworm Lite), but works on any modern Pi.

---

## 🧩 Features

| Function | Description |
|-----------|--------------|
| ✅ Incoming calls | Mechanical bells ring; picking up the handset answers automatically |
| ✅ Outgoing calls | Rotary dial impulses detected and sent to SIP provider |
| ✅ Dial tone | Simulated analog line tone on handset |
| ✅ Web interface | Configure SIP, view logs, restart services |
| ✅ GPIO monitoring | For testing hook, dial and return switch |
| ✅ Persistent logs | All actions stored in `/var/log/retrophone` |
| ✅ Systemd services | Auto-start on boot, isolated and restart-safe |

---

## 🪛 Hardware Setup

| Component | GPIO (BCM) | Description | Logic |
|------------|------------|-------------|-------|
| HOOK | 18 | Handset switch | 0 = offhook, 1 = onhook |
| PULSE | 23 | Dial pulses | 1 = pulse active |
| POS1 | 24 | Return contact | 0 = dial turning, 1 = idle |
| RING_A | 17 | Bell coil A | controlled by `ring_control.py` |
| RING_B | 27 | Bell coil B | controlled by `ring_control.py` (optional) |

> The pulse logic and hook wiring follow the original Swiss rotary system — all contacts pull to **GND**.

---

## ⚙️ Software Installation (Step by Step)

### 1️⃣ Base System

Minimal Debian Trixie / Bookworm Lite.  
Enable SSH and network.

### 2️⃣ Dependencies

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y \  python3 python3-pip python3-flask python3-gpiozero python3-rpi.gpio \  alsa-utils sox git \  build-essential libasound2-dev libssl-dev libz-dev libopus-dev libavformat-dev \  libavcodec-dev libavutil-dev libre-dev libspandsp-dev libreadline-dev \  uuid-dev libedit-dev libmicrohttpd-dev systemd python3-venv \ baresip libasound2
```

---

### 3️⃣ Create folders for **retrophone** and **baresip**

```bash
sudo mkdir -p /etc/retrophone/baresip
sudo mkdir -p /usr/local/retrophone
sudo mkdir -p /var/log/retrophone
```

Run once to generate default config:

```bash
baresip
# CTRL+C to exit
```

---

### 4️⃣ Configure baresip

**Create the initial config-file for baresip**
Edit `/etc/retrophone/baresip/config`:

```bash
sudo tee /etc/retrophone/baresip/config >/dev/null <<'EOF'
# UI Modules
module                  stdio.so
module                  httpd.so

# Audio driver Modules
module                  alsa.so

# Media NAT modules
module                  stun.so
module                  turn.so
module                  ice.so

#------------------------------------------------------------------------------
# Temporary Modules (loaded then unloaded)

module_tmp              uuid.so
module_tmp              account.so


#------------------------------------------------------------------------------
# Application Modules

module_app              auloop.so
module_app              contact.so
module_app              debug_cmd.so
module_app              menu.so
module_app              ctrl_tcp.so
module_app              vidloop.so

#------------------------------------------------------------------------------
# Module parameters


# UI Modules parameters
cons_listen             0.0.0.0:5555 # cons - Console UI UDP/TCP sockets

http_listen             127.0.0.1:8000 # httpd - HTTP Server

ctrl_tcp_listen         127.0.0.1:4444 # ctrl_tcp - TCP interface JSON

evdev_device            /dev/input/event0

# Opus codec parameters
opus_bitrate            28000 # 6000-510000

vumeter_stderr          yes

# Selfview
video_selfview          window # {window,pip}

# Menu
ring_aufile             none
EOF
```

**Create config file for the useraccount**
Edit `/etc/retrophone/baresip/accounts`:
```bash
sudo tee /etc/retrophone/baresip/accounts >/dev/null <<'EOF'
; YOUR ACCOUNT
<sip:phonenumber@sip.domain.url>;auth_user=USERNAME;auth_pass=YOUR_PASSWORD;outbound="sip:sip.domain.url;transport=udp";regint=300
EOF
```

---

### 5️⃣ Directory Structure

```bash
sudo mkdir -p /usr/local/retrophone /var/log/retrophone /run/retrophone
sudo chown -R pi:pi /usr/local/retrophone /var/log/retrophone /run/retrophone
```

Copy all Python files:

```bash
sudo cp gpio_monitor.py gpio_hook_monitor.py ring_control.py phone_daemon.py webapp.py /usr/local/retrophone/
sudo chmod +x /usr/local/retrophone/*.py
```

---

### 6️⃣ Create a Dial Tone

```bash
sox -n -r 8000 -c 1 /usr/local/retrophone/dialtone.wav synth 10 sin 425
```

---

### 7️⃣ Sudo Permissions

```bash
sudo visudo
```

Add:

```text
pi ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart baresip.service
pi ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart phone-daemon.service
pi ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart retrophone-web.service
```

Permission for the webapp to change usernames in the account-file
```bash
sudo chown -R pi:pi /etc/retrophone/baresip
sudo chmod 640 /etc/retrophone/baresip/accounts
```

---

### 8️⃣ Systemd Services

#### 📞 `/etc/systemd/system/phone-daemon.service`
```bash
sudo tee /etc/systemd/system/phone-daemon.service >/dev/null <<'EOF'
[Unit]
Description=RetroPhone Dial/Hook Daemon
After=network.target sound.target baresip.service

[Service]
ExecStart=/usr/bin/python3 /usr/local/retrophone/phone_daemon.py
Restart=on-failure
User=pi
Group=pi
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now phone-daemon.service
```

#### 🔔 `/etc/systemd/system/retrophone-web.service`
```bash
sudo tee /etc/systemd/system/retrophone-web.service >/dev/null <<'EOF'
[Unit]
Description=RetroPhone Web UI
After=network.target

[Service]
ExecStart=/usr/bin/python3 /usr/local/retrophone/webapp.py
WorkingDirectory=/usr/local/retrophone
User=pi
Group=pi
Environment=RETRO_WEB_USER=admin
Environment=RETRO_WEB_PASS=secret
Restart=on-failure
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now retrophone-web.service
```

#### 📡 `/etc/systemd/system/baresip.service`
Edit `/etc/systemd/system/baresip.service`:

```bash
sudo tee /etc/systemd/system/baresip.service >/dev/null <<'EOF'
[Unit]
Description=baresip SIP client
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/baresip -f /etc/retrophone/baresip
Restart=always
RestartSec=2
# Root ist ok für GPIO-Setup und einfachen Start; alternativ eigenen User anlegen.
User=root

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now baresip.service
```

**check**
You should see "registered" messages.

```bash
journalctl -u baresip -b --no-pager | tail -n 50
```


---

### 📝 Configure logrotate

```bash
sudo tee /etc/logrotate.d/retrophone >/dev/null <<'EOF'
/var/log/retrophone/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    create 0640 root root
    sharedscripts
    postrotate
        systemctl kill -s HUP phone-daemon.service 2>/dev/null || true
    endscript
}
EOF
```

## 🖥️ Web Interface

Accessible at:  
👉 `http://<raspberrypi-ip>:8080`

### Features:
- SIP account configuration  
- View logs (auto-refresh)  
- Restart services  
- View service status (baresip, daemon, web)

Environment variables in `retrophone-web.service` control login credentials.

---

## 🧾 Log Files

| Path | Description |
|------|--------------|
| `tail -f /var/log/retrophone/phone.log` | Main rotary daemon (dial, hook, call states) |
| `tail -f /var/log/retrophone/ring.log` | Bell control |
| `journalctl -u baresip` | baresip SIP logs |

---

## 🧩 Helper Tools

| Script | Purpose |
|---------|----------|
| `gpio_monitor.py` | Realtime GPIO monitor for all pins |
| `gpio_hook_monitor.py` | Shows only hook state |
| `ring_control.py` | Manual ring test (`sudo /usr/local/retrophone/ring_control.py oneshot 1000`) |

---

## 🎧 Audio Troubleshooting

If baresip logs errors like `Unknown error -22`:

```text
audio_player alsa,plughw:0,0
audio_source alsa,plughw:0,0
audio_alert  alsa,null
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
|  Rotary Dial  |  Hook Switch  |  Bell Coils  |  USB Audio    |
|--------------------------------------------------------------|
|    GPIO 23    |    GPIO 18    |  GPIO 17/27  | Logitech H340 |
|               |               |              |    Headset    |
|--------------------------------------------------------------|
|  phone_daemon.py (Pulse/Hooks)  -> baresip (SIP stack)       |
|  ring_control.py (Bells)         -> GPIO Driver              |
|  webapp.py (Flask UI)            -> SIP + Logs + Control     |
+--------------------------------------------------------------+
```
---

## 🧠 Credits & References

- Original rotary wiring idea based on [**CrazyRobMiles** / RaspberryPi-DialTelephone](https://github.com/CrazyRobMiles/RaspberryPi-DialTelephone)
- SIP core powered by [**baresip**](https://github.com/baresip/baresip)
- Hardware testing and refinement by **Christian (Switzerland)** 👏

---

## 🪪 License

This project is released under the **MIT License**.  
All third-party components retain their original licenses.

---

## 📸 Screenshot Placeholder

*(Add your project photos here)*  
`![RetroPhone Setup](docs/retrophone.jpg)`

---

## ✅ Status

✔️ Incoming & outgoing calls  
✔️ Real bells working  
✔️ Audio via USB headset  
✔️ SIP over Netvoip  
✔️ Full Web-GUI with Logs and Restart  
✔️ Fully automatic startup via systemd  

> **Retro Rotary SIP Phone – where analog charm meets digital tech.**
