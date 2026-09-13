#!/usr/bin/env python3
import os
import re
import stat
import html
import json
import tempfile
import subprocess
import time
import threading
from datetime import datetime
from functools import wraps

from flask import Flask, request, Response, url_for, redirect, session, send_file

app = Flask(__name__)

# --- Secret für Session-Cookies ---
app.secret_key = os.environ.get("RETRO_WEB_SECRET", "retrophone-change-me")

# --- Pfade ---
CONFIG_PATH = os.environ.get("RETRO_CONFIG_PATH", "/etc/retrophone/config.json")
try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as startup_config_file:
        STARTUP_CONFIG = json.load(startup_config_file)
    if not isinstance(STARTUP_CONFIG, dict):
        STARTUP_CONFIG = {}
except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError):
    STARTUP_CONFIG = {}
PATH_CONFIG = STARTUP_CONFIG.get("paths", {}) if isinstance(STARTUP_CONFIG.get("paths", {}), dict) else {}
RUNTIME_DIR = str(PATH_CONFIG.get("runtime_dir", "/run/retrophone"))
PHONE_LOG = os.path.join(RUNTIME_DIR, "phone.log")
RING_LOG  = os.path.join(RUNTIME_DIR, "ring.log")
CALL_LOG  = str(PATH_CONFIG.get("call_log", "/var/log/retrophone/calls.jsonl"))
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

# Backup kann via Environment überschrieben werden.
BACKUP_SCRIPT = os.environ.get("RETRO_BACKUP_SCRIPT", str(PATH_CONFIG.get("backup_script", "/usr/local/retrophone/backup_retrophone.sh")))
BACKUP_DIR = os.environ.get("RETRO_BACKUP_DIR", str(PATH_CONFIG.get("backup_dir", "/home/pi/retrophone-backups")))
FAVICON_PATH = str(PATH_CONFIG.get("favicon", "/usr/local/retrophone/favicon.ico"))

DEFAULT_ACCOUNTS  = str(PATH_CONFIG.get("baresip_accounts", "/etc/retrophone/baresip/accounts"))
FALLBACK_ACCOUNTS = "/home/pi/.baresip/accounts"

def accounts_path():
    return DEFAULT_ACCOUNTS if os.path.exists(DEFAULT_ACCOUNTS) else FALLBACK_ACCOUNTS

# --- Services für Übersicht ---
SERVICES = {
    "phone":   "phone-daemon.service",
    "baresip": "baresip.service",
    "web":     "retrophone-web.service",
}

# --- Login-Konfig aus Environment (Service-File) ---
WEB_USER = os.environ.get("RETRO_WEB_USER", "admin")
WEB_PASS = os.environ.get("RETRO_WEB_PASS", "changeme")

def is_logged_in():
    return session.get("logged_in") is True

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            nxt = request.path if request.path != "/health" else "/"
            return redirect(url_for("login", next=nxt))
        return f(*args, **kwargs)
    return wrapper

# --- Layout / UI ---
BASE_CSS = """
:root{
  --bg:#07111f;
  --bg-soft:#0b1628;
  --panel:#0f1d31;
  --panel-2:#12233a;
  --border:#203651;
  --text:#eef6ff;
  --muted:#8fa7c2;
  --blue:#2f80ed;
  --blue-2:#5aa7ff;
  --blue-dark:#1857a4;
  --green:#36c98f;
  --amber:#f4b942;
  --red:#ff6b7a;
  --shadow:0 18px 45px rgba(0,0,0,.28);
}
*{box-sizing:border-box}
html{min-height:100%}
body{
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  margin:0;
  min-height:100vh;
  background:
    radial-gradient(circle at 15% 0%,rgba(47,128,237,.14),transparent 30%),
    radial-gradient(circle at 85% 10%,rgba(90,167,255,.08),transparent 28%),
    var(--bg);
  color:var(--text);
}
a{text-decoration:none;color:inherit}
code{font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace;color:#cfe5ff}
.header{
  position:sticky;top:0;z-index:20;
  min-height:72px;padding:12px 26px;
  display:flex;align-items:center;justify-content:space-between;gap:18px;
  background:rgba(7,17,31,.9);backdrop-filter:blur(14px);
  border-bottom:1px solid rgba(97,137,180,.18);
}
.brand{display:flex;align-items:center;gap:12px;font-weight:800;font-size:1.12rem;letter-spacing:.01em;color:#fff}
.ui-icon{width:18px;height:18px;display:inline-block;vertical-align:-3px;flex:0 0 auto;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.nav a{display:flex;align-items:center;gap:10px}.nav .ui-icon{width:17px;height:17px}.title-row{display:flex;align-items:center;gap:10px}.title-row .ui-icon{width:20px;height:20px;color:#184b3a}.title-row.icon-box{position:relative;min-height:40px;padding-left:10px;gap:20px}.title-row.icon-box:before{content:"";position:absolute;left:0;top:50%;transform:translateY(-50%);width:40px;height:40px;border-radius:11px;background:#edf5f0;z-index:0}.title-row.icon-box .ui-icon{position:relative;z-index:1;width:20px;height:20px;margin:0}.title-row.icon-box h2{position:relative;z-index:1;margin:0}
.brand:before{
  content:"☎";width:38px;height:38px;border-radius:12px;display:grid;place-items:center;
  background:linear-gradient(135deg,var(--blue),var(--blue-2));
  box-shadow:0 9px 24px rgba(47,128,237,.28);font-size:1rem;
}
.nav{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.nav a{
  padding:9px 13px;border-radius:12px;font-size:.87rem;font-weight:650;color:#a9bdd4;
  border:1px solid transparent;transition:.18s ease;
}
.nav a:hover{color:#fff;background:#10233c;border-color:#274564;transform:translateY(-1px)}
.nav a.active{
  color:#fff;border-color:rgba(90,167,255,.45);
  background:linear-gradient(135deg,rgba(47,128,237,.95),rgba(41,105,191,.92));
  box-shadow:0 8px 20px rgba(47,128,237,.22);
}
.main{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:28px 0 42px}
.card{
  background:linear-gradient(180deg,rgba(17,34,57,.94),rgba(12,27,47,.96));
  border:1px solid rgba(81,117,153,.32);border-radius:20px;padding:22px;margin-bottom:18px;
  box-shadow:var(--shadow);
}
.card:hover{border-color:rgba(90,167,255,.28)}
h1{font-size:1.48rem;line-height:1.25;margin:0 0 8px;letter-spacing:-.02em}
h2{font-size:1.18rem;line-height:1.3;margin:0 0 8px;letter-spacing:-.01em}
p{line-height:1.55}
ul{padding-left:20px}
pre{
  background:#081422;color:#dbeafe;padding:15px;border-radius:14px;overflow:auto;max-height:70vh;
  border:1px solid #1d3551;font-size:.79rem;line-height:1.5;box-shadow:inset 0 1px 0 rgba(255,255,255,.02)
}
label{display:block;margin-top:13px;margin-bottom:5px;font-weight:650;font-size:.88rem;color:#c8d9ea}
input,select{
  padding:10px 12px;margin-bottom:3px;width:100%;border-radius:12px;border:1px solid #2a4463;
  background:#091728;color:#eef6ff;font-size:.92rem;transition:.16s ease;
}
input:hover,select:hover{border-color:#3b5e86}
input:focus,select:focus{outline:none;border-color:var(--blue-2);box-shadow:0 0 0 3px rgba(47,128,237,.15)}
input[readonly]{color:#a7bdd5;background:#0a1421}
.btn-row{margin-top:16px;display:flex;flex-wrap:wrap;gap:9px}
.btn{
  display:inline-flex;align-items:center;justify-content:center;padding:9px 14px;border-radius:12px;
  border:1px solid #31506f;font-size:.88rem;font-weight:650;background:#10223a;color:#dceaf8;cursor:pointer;
  transition:.18s ease;box-shadow:0 5px 14px rgba(0,0,0,.12)
}
.btn:hover{transform:translateY(-1px);background:#153052;border-color:#42719f;color:#fff}
.btn.primary{
  background:linear-gradient(135deg,var(--blue),#2469c8);border-color:#4d9cff;color:#fff;
  box-shadow:0 8px 20px rgba(47,128,237,.24)
}
.btn.primary:hover{background:linear-gradient(135deg,#3b8cf3,#2c76d6)}
.btn.danger{background:#401c28;border-color:#7d3142;color:#ffd7dc}
.btn.danger:hover{background:#562334;border-color:#a44257}
.btn:disabled{opacity:.5;cursor:default;transform:none}
.subtle{font-size:.83rem;color:var(--muted)}
.grid-2{display:grid;grid-template-columns:1.1fr 1fr;gap:18px}
.tabs{display:flex;gap:7px;margin:14px 0 12px;flex-wrap:wrap}
.tab{
  padding:7px 12px;border-radius:11px;border:1px solid #294865;font-size:.82rem;font-weight:650;
  background:#0a1727;color:#8fa8c3;transition:.16s ease
}
.tab:hover{color:#fff;border-color:#3c6c98}
.tab.active{background:linear-gradient(135deg,var(--blue),#2469c8);border-color:#4b99ef;color:#fff;box-shadow:0 6px 16px rgba(47,128,237,.2)}
.badge{
  display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border-radius:999px;font-size:.73rem;font-weight:750;
  border:1px solid #29435e;background:#0a1727;color:#a9bdd4
}
.badge:before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor;box-shadow:0 0 10px currentColor}
.badge.ok{border-color:rgba(54,201,143,.45);color:#66e3b2;background:rgba(54,201,143,.08)}
.badge.warn{border-color:rgba(244,185,66,.45);color:#ffd36d;background:rgba(244,185,66,.08)}
.badge.err{border-color:rgba(255,107,122,.45);color:#ff9da8;background:rgba(255,107,122,.08)}
.table{width:100%;border-collapse:separate;border-spacing:0;font-size:.88rem;margin-top:10px;overflow:hidden;border-radius:14px;border:1px solid #203b58}
.table th,.table td{padding:11px 12px;border-bottom:1px solid #20364f;text-align:left}
.table th{font-weight:700;color:#9db4cc;background:#0a1727}
.table tr:last-child td{border-bottom:0}
.table tbody tr{background:rgba(12,28,48,.7)}
.table tbody tr:hover{background:rgba(20,47,78,.72)}
.errtext{color:#ff9da8;font-size:.85rem;margin-bottom:8px}
.info-tip{display:inline-grid;place-items:center;width:18px;height:18px;margin-left:6px;border:1px solid #4b759e;border-radius:50%;color:#9dccff;font-size:.72rem;font-weight:800;cursor:help;vertical-align:middle;background:#0a1727}
.info-tip:hover,.info-tip:focus{color:#fff;border-color:var(--blue-2);outline:none;box-shadow:0 0 0 3px rgba(47,128,237,.15)}
.toggle-pair{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:9px;align-items:end}
.toggle-pair label{min-width:0}.hz-compact{min-width:88px;margin-bottom:3px;padding:10px 11px;border:1px solid #2a4463;border-radius:12px;background:#091728;text-align:center;color:#cfe5ff;font-size:.84rem;font-weight:750;white-space:nowrap}
.hero{margin-bottom:18px}
.hero h1{font-size:1.7rem;margin-bottom:5px}
.hero p{margin:0;color:var(--muted);font-size:.92rem}
.dashboard-hero{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.dashboard-hero .system-info-strip{padding-top:1px}
.metric-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:16px}
.metric{padding:14px;border-radius:15px;background:rgba(8,23,40,.75);border:1px solid #203d5d}
.metric .k{display:block;color:#7f9bb8;font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px}
.metric .v{display:block;color:#f2f8ff;font-size:.98rem;font-weight:750;word-break:break-word}

.section-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:26px 0 12px}
.section-head h2{margin:0}.section-head .subtle{margin:0}
.status-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:18px}
.status-card{position:relative;overflow:hidden;background:linear-gradient(180deg,rgba(17,34,57,.94),rgba(10,24,42,.98));border:1px solid rgba(81,117,153,.32);border-radius:18px;padding:18px;box-shadow:var(--shadow)}
.status-card:after{content:"";position:absolute;right:-42px;top:-42px;width:120px;height:120px;border-radius:50%;background:radial-gradient(circle,rgba(47,128,237,.18),transparent 68%);pointer-events:none}
.status-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:18px}
.status-title{font-size:.85rem;color:#9cb3ca;font-weight:700}.status-main{font-size:1.12rem;font-weight:800;color:#fff;margin-bottom:4px}.status-meta{font-size:.78rem;color:var(--muted)}
.dot{width:10px;height:10px;border-radius:50%;background:#70849a;box-shadow:0 0 12px rgba(112,132,154,.4)}.dot.ok{background:var(--green);box-shadow:0 0 14px rgba(54,201,143,.65)}.dot.err{background:var(--red);box-shadow:0 0 14px rgba(255,107,122,.55)}.dot.warn{background:var(--amber);box-shadow:0 0 14px rgba(244,185,66,.55)}
.split-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px}.wide-card{min-width:0}
.log-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.log-box{background:#081422;border:1px solid #1d3551;border-radius:15px;padding:14px;min-width:0}.log-box h3{font-size:.9rem;margin:0 0 8px;color:#dceaff}.log-box pre{margin:0;max-height:180px;white-space:pre-wrap;word-break:break-word;border:0;padding:0;background:transparent;box-shadow:none}
.backup-row{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 0;border-top:1px solid rgba(81,117,153,.24)}.backup-row:first-of-type{border-top:0}.backup-value{text-align:right;font-weight:750;color:#eaf4ff}.empty-state{padding:16px;border-radius:14px;border:1px dashed #31516f;background:rgba(8,23,40,.55);color:var(--muted);font-size:.84rem}
.section-actions{display:flex;flex-direction:column;align-items:flex-end;gap:8px}.system-info-strip{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:9px;margin:0}.system-info-chip{display:flex;align-items:center;gap:9px;min-height:38px;padding:7px 11px;border:1px solid rgba(81,117,153,.32);border-radius:12px;background:rgba(10,23,39,.82);box-shadow:0 6px 18px rgba(0,0,0,.14)}.system-info-chip .k{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.system-info-chip .v{font-size:.83rem;font-weight:750;color:#eef6ff}
.login-shell{max-width:440px;margin:7vh auto 0}
@media(max-width:900px){
  .grid-2,.split-grid{grid-template-columns:1fr}.metric-grid{grid-template-columns:1fr}.status-grid,.log-grid{grid-template-columns:1fr}
  .header{align-items:flex-start;flex-direction:column;padding:14px 16px}.nav{width:100%;justify-content:flex-start}
  .main{width:min(100% - 22px,1180px);padding-top:20px}
  .section-head{align-items:flex-start;flex-direction:column}.section-actions{align-items:flex-start}.system-info-strip{justify-content:flex-start}
  .dashboard-hero{flex-direction:column}.dashboard-hero .system-info-strip{padding-top:0}
}
@media(max-width:620px){
  .nav a{font-size:.8rem;padding:8px 10px}.card{padding:17px;border-radius:16px}
  .btn{width:100%}.btn-row{display:grid;grid-template-columns:1fr}.table{display:block;overflow-x:auto}
  .toggle-pair{grid-template-columns:minmax(0,1fr) auto}
}

/* KI-Protection-inspiriertes RetroPhone Theme */
:root{
  --bg:#f3f7f4;--bg-soft:#edf3ef;--panel:#ffffff;--panel-2:#f7faf8;
  --border:#d5dfd9;--text:#0b2019;--muted:#70837a;
  --blue:#a8ff3e;--blue-2:#bcff68;--blue-dark:#0b2c22;
  --green:#58c713;--amber:#ef8b3c;--red:#dc5a5a;
  --shadow:0 12px 32px rgba(12,44,34,.055)
}
body{background:linear-gradient(135deg,#f8faf9 0%,#eef4f0 100%);color:var(--text)}
code{color:#315c4d}.header{position:fixed;inset:0 auto 0 0;width:245px;min-height:100vh;padding:25px 18px;align-items:stretch;justify-content:flex-start;flex-direction:column;gap:30px;background:linear-gradient(180deg,#0c3025,#08261d);border:0;box-shadow:8px 0 28px rgba(7,35,27,.08);backdrop-filter:none}
.brand{font-size:1.14rem;padding:0 7px}.brand:before{content:"☎";background:linear-gradient(135deg,#b9ff55,#91ef2a);color:#103424;box-shadow:0 8px 22px rgba(155,244,48,.22)}
.nav{display:flex;flex-direction:column;gap:5px;justify-content:flex-start;flex-wrap:nowrap}.nav a{padding:12px 13px;border-radius:11px;color:#afc4ba;font-size:.9rem}.nav a:hover{color:#fff;background:rgba(255,255,255,.075);border-color:transparent;transform:none}.nav a.active{color:#b8ff53;background:rgba(255,255,255,.105);border-color:transparent;box-shadow:none}
.main{width:auto;max-width:1500px;margin:0 0 0 245px;padding:30px 40px 48px}.card,.status-card{background:#fff;border:1px solid var(--border);box-shadow:var(--shadow);border-radius:19px}.card:hover,.status-card:hover{border-color:#bdcec4}.status-card:after{background:radial-gradient(circle,rgba(164,242,76,.14),transparent 68%)}
h1,h2,h3{color:#081c16}.hero h1{font-size:1.85rem}.subtle,.hero p,.status-meta{color:var(--muted)}.status-title{color:#62786d}.status-main,.metric .v,.backup-value,.system-info-chip .v{color:#0b2019}
.metric,.system-info-chip,.empty-state{background:#f6f9f7;border-color:#dbe4df}.metric .k,.system-info-chip .k{color:#72877c}.system-info-chip{box-shadow:none}.dot.ok{background:#59cb16;box-shadow:0 0 0 5px rgba(89,203,22,.12)}
label{color:#29473c}input,select{background:#fbfdfb;color:#102820;border-color:#cbd8d0}input:hover,select:hover{border-color:#9eb7a8}input:focus,select:focus{border-color:#86d431;box-shadow:0 0 0 3px rgba(151,229,60,.2)}input[readonly]{color:#6f8279;background:#f0f4f1}
.btn{background:#eef4f0;color:#173b2e;border-color:#d1ddd6;box-shadow:none}.btn:hover{background:#e4ede7;border-color:#b9cbbf;color:#09271d}.btn.primary{background:#0b3024;border-color:#0b3024;color:#fff;box-shadow:0 7px 18px rgba(8,43,32,.14)}.btn.primary:hover{background:#124636;border-color:#124636}.btn.danger{background:#fff0f0;border-color:#e7bcbc;color:#a23838}.btn.danger:hover{background:#fde4e4;border-color:#dc9999}
.badge{background:#eef4f0;border-color:#d8e3dc;color:#3c6253}.badge.ok{color:#317d0b;background:#effbe7;border-color:#d9f1c9}.badge.warn{color:#a65b20;background:#fff4e9;border-color:#f3d8bd}.badge.err{color:#a83d3d;background:#fff0f0;border-color:#efcece}
.tabs .tab{background:#f0f5f2;color:#557065;border-color:#d5e0da}.tabs .tab:hover{color:#14392b;border-color:#b9ccc0}.tabs .tab.active{background:#0b3024;color:#fff;border-color:#0b3024;box-shadow:none}
.table{border-color:#dbe3de}.table th{color:#60776c;background:#f4f7f5}.table th,.table td{border-bottom-color:#e1e8e4}.table tbody tr{background:#fff}.table tbody tr:hover{background:#f6faf7}
.dashboard-surface{margin:0 0 18px;background:#fff;border-radius:19px;box-shadow:var(--shadow)}
.detail-list{margin-top:15px;border:1px solid #dbe3de;border-radius:13px;overflow:hidden}.detail-row{display:grid;grid-template-columns:minmax(130px,.75fr) 1.25fr;gap:14px;padding:10px 12px;border-bottom:1px solid #e1e8e4;font-size:.84rem}.detail-row:last-child{border-bottom:0}.detail-row .k{color:#61766c}.detail-row .v{color:#17382c;font-weight:650;word-break:break-word}.compact-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.compact-card-head .subtle{margin:2px 0 0}.dashboard-table{font-size:.8rem}.dashboard-table th,.dashboard-table td{padding:9px 10px}.log-message{max-width:440px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.progress-track{height:18px;border-radius:999px;background:#e4ebe7;overflow:hidden;margin:18px 0 10px}.progress-bar{height:100%;width:0;background:linear-gradient(90deg,#76d62f,#b8ff53,#76d62f);background-size:200% 100%;border-radius:999px;transition:width .45s ease;animation:progress-flow 1.4s linear infinite}.progress-bar.done{animation:none;background:#45bd24}.progress-bar.error{animation:none;background:#e05252}@keyframes progress-flow{to{background-position:-200% 0}}
.info-tip{border-color:#a8beb2;color:#3d6b59;background:#f2f7f4}.info-tip:hover,.info-tip:focus{color:#183d2f;border-color:#82cc35;box-shadow:0 0 0 3px rgba(151,229,60,.18)}.hz-compact{background:#f8fbf9;color:#315c4d;border-color:#cbd8d0}
.log-box{background:#102d24;border-color:#1d493a}.log-box h3{color:#eaffdf}.log-box pre,pre{background:#102d24;color:#dff2e8;border-color:#224a3d}
@media(max-width:900px){.header{position:sticky;inset:auto;width:100%;min-height:auto;padding:14px 16px;gap:12px;flex-direction:column}.nav{width:100%;flex-direction:row;flex-wrap:wrap}.nav a{padding:8px 10px}.main{width:min(100% - 22px,1180px);margin:0 auto;padding:20px 0 42px}}
"""

def ui_icon(name):
    paths = {
        "dashboard": '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
        "settings": '<path d="M4 21v-7"/><path d="M4 10V3"/><path d="M12 21v-9"/><path d="M12 8V3"/><path d="M20 21v-5"/><path d="M20 12V3"/><path d="M1 14h6"/><path d="M9 8h6"/><path d="M17 16h6"/>',
        "logs": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8"/><path d="M8 17h8"/>',
        "phone": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.9.33 1.78.62 2.63a2 2 0 0 1-.45 2.11L8 9.73a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.85.29 1.73.5 2.63.62A2 2 0 0 1 22 16.92z"/>',
        "services": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06-2.83 2.83-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21h-4v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06-2.83-2.83.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3v-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06 2.83-2.83.06.06A1.65 1.65 0 0 0 8.92 4.6a1.65 1.65 0 0 0 1-1.51V3h4v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06 2.83 2.83-.06.06A1.65 1.65 0 0 0 19.4 9c.12.37.2.75.24 1.14H21v4h-1.36c-.04.29-.12.58-.24.86z"/>',
        "user": '<path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="7" r="4"/>',
        "logout": '<path d="M10 17l5-5-5-5"/><path d="M15 12H3"/><path d="M21 19V5a2 2 0 0 0-2-2h-6"/>',
        "monitor": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/>',
        "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"/>',
    }
    return f'<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true">{paths.get(name, paths["dashboard"])}</svg>'

def render_page(title, active, body_html, auto_refresh=None, show_nav=True):
    refresh = f'<meta http-equiv="refresh" content="{int(auto_refresh)}">' if auto_refresh else ""
    if show_nav and is_logged_in():
        nav_html = f"""
<div class="header">
  <div class="brand">RetroPhone</div>
  <div class="nav">
    <a href="{url_for('index')}" class="{ 'active' if active=='home' else '' }">{ui_icon('dashboard')}Dashboard</a>
    <a href="{url_for('calls_overview')}" class="{ 'active' if active=='calls' else '' }">{ui_icon('phone')}Anrufe</a>
    <a href="{url_for('logs_phone')}" class="{ 'active' if active=='logs' else '' }">{ui_icon('logs')}Logs</a>
    <a href="{url_for('services_overview')}" class="{ 'active' if active=='services' else '' }">{ui_icon('services')}Services</a>
    <a href="{url_for('settings_overview')}" class="{ 'active' if active=='settings' else '' }">{ui_icon('settings')}Einstellungen</a>
    <a href="{url_for('auth_info')}" class="{ 'active' if active=='auth' else '' }">{ui_icon('user')}Login-Info</a>
    <a href="{url_for('logout')}" class="{ 'active' if active=='logout' else '' }">{ui_icon('logout')}Logout</a>
  </div>
</div>
"""
    else:
        nav_html = """
<div class="header">
  <div class="brand">RetroPhone</div>
</div>
"""
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="{url_for('favicon')}" sizes="any">
<title>{html.escape(title)} - RetroPhone</title>
{refresh}
<style>{BASE_CSS}</style>
</head>
<body>
{nav_html}
<div class="main">
{body_html}
</div>
</body>
</html>"""

@app.get("/favicon.ico")
def favicon():
    if not os.path.isfile(FAVICON_PATH):
        return Response(status=404)
    return send_file(FAVICON_PATH, mimetype="image/x-icon", max_age=86400)

# --- Log Helfer ---
def tail_file(path, lines=200):
    if not os.path.exists(path):
        return f"{path} not found"
    try:
        read_lines = max(lines * 10, 2000) if path == PHONE_LOG else lines
        out = subprocess.check_output(["tail", "-n", str(read_lines), path], text=True, timeout=2)
        data = out.splitlines()
        if path == PHONE_LOG and configured_phone_log_level() != "DEBUG":
            data = [line for line in data if "baresip resp (listcalls)" not in line]
        return "\n".join(data[-lines:])
    except Exception as e:
        return f"tail failed: {e}"

def tail_baresip(lines=200):
    try:
        out = subprocess.check_output(
            ["journalctl", "-u", "baresip", "-n", str(max(lines * 10, 2000)), "--no-pager"],
            text=True, timeout=3
        )
        noise = (
            "ua: using best effort AF: af=AF_INET",
            "selected for ",
        )
        data = [line for line in out.splitlines() if not any(item in line for item in noise)]
        return "\n".join(data[-lines:])
    except Exception as e:
        return f"journalctl failed: {e}"

def read_calls(limit=20):
    limit = min(max(1, int(limit)), 20)
    calls = []
    try:
        with open(CALL_LOG, "r", encoding="utf-8") as call_file:
            for line in call_file:
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        calls.append(item)
                except (ValueError, TypeError):
                    continue
    except (FileNotFoundError, PermissionError, OSError):
        pass

    # Ältere Daemon-Versionen schrieben eingehende Anrufe noch nicht nach
    # calls.jsonl. baresip enthält die Rufnummer dennoch dauerhaft im Journal.
    # Diese Einträge ergänzen wir als verpasst und vermeiden dabei Duplikate.
    try:
        output = subprocess.check_output(
            ["journalctl", "-u", "baresip", "--since", "90 days ago", "--no-pager", "--output=short-iso"],
            text=True, timeout=5
        )
        known = {
            (str(call.get("timestamp", ""))[:16], str(call.get("number", "")))
            for call in calls
        }
        pattern = re.compile(
            r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})\S*.*Incoming call from:\s*([^\s]+)",
            re.IGNORECASE,
        )
        for line in output.splitlines():
            match = pattern.search(line)
            if not match:
                continue
            timestamp = f"{match.group(1)}T{match.group(2)}"
            number = match.group(3).strip()
            key = (timestamp[:16], number)
            if key not in known:
                item = {
                    "timestamp": timestamp,
                    "direction": "incoming",
                    "number": number,
                    "status": "verpasst",
                    "duration_sec": 0,
                }
                calls.append(item)
                persist_call(item)
                known.add(key)
    except (subprocess.SubprocessError, OSError):
        pass

    calls.sort(key=lambda call: str(call.get("timestamp", "")), reverse=True)
    return calls[:limit]

_call_log_lock = threading.Lock()

def persist_call(item):
    """Einen Anruf dauerhaft ablegen; standardmässig bleiben die letzten 20."""
    key = (str(item.get("timestamp", ""))[:16], str(item.get("number", "")))
    if not key[1]:
        return False
    with _call_log_lock:
        try:
            os.makedirs(os.path.dirname(CALL_LOG), exist_ok=True)
            existing_calls = []
            try:
                with open(CALL_LOG, "r", encoding="utf-8") as existing_file:
                    for line in existing_file:
                        try:
                            existing = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        if isinstance(existing, dict):
                            existing_calls.append(existing)
                            if (str(existing.get("timestamp", ""))[:16], str(existing.get("number", ""))) == key:
                                return False
            except FileNotFoundError:
                pass
            existing_calls.append(item)
            existing_calls.sort(key=lambda call: str(call.get("timestamp", "")))
            existing_calls = existing_calls[-20:]
            temp_path = CALL_LOG + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as call_file:
                for call in existing_calls:
                    call_file.write(json.dumps(call, ensure_ascii=False, separators=(",", ":")) + "\n")
                call_file.flush()
                os.fsync(call_file.fileno())
            os.chmod(temp_path, 0o640)
            os.replace(temp_path, CALL_LOG)
            return True
        except (PermissionError, OSError):
            return False

def collect_incoming_calls():
    """baresip live verfolgen, damit Rufnummern einen Neustart überstehen."""
    pattern = re.compile(
        r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})\S*.*Incoming call from:\s*([^\s]+)",
        re.IGNORECASE,
    )
    while True:
        try:
            process = subprocess.Popen(
                ["journalctl", "-f", "-n", "0", "-u", "baresip", "--output=short-iso"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
            if process.stdout is not None:
                for line in process.stdout:
                    match = pattern.search(line)
                    if match:
                        persist_call({
                            "timestamp": f"{match.group(1)}T{match.group(2)}",
                            "direction": "incoming",
                            "number": match.group(3).strip(),
                            "status": "eingegangen",
                            "duration_sec": 0,
                        })
            process.wait(timeout=2)
        except Exception:
            time.sleep(3)

def format_duration(seconds):
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        total = 0
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:d}:{secs:02d}"

def calls_table_rows(calls):
    if not calls:
        return '<tr><td colspan="5"><span class="subtle">Noch keine Anrufe protokolliert.</span></td></tr>'
    rows = []
    for call in calls:
        direction = call.get("direction", "unknown")
        label = "Eingehend" if direction == "incoming" else "Ausgehend" if direction == "outgoing" else "Unbekannt"
        badge = "ok" if direction == "incoming" else "warn"
        rows.append(f"""
<tr><td><span class="badge {badge}">{html.escape(label)}</span></td>
<td><code>{html.escape(str(call.get('number') or '-'))}</code></td>
<td>{html.escape(str(call.get('timestamp') or '-').replace('T', ' '))}</td>
<td>{html.escape(format_duration(call.get('duration_sec', 0)))}</td>
<td>{html.escape(str(call.get('status') or '-'))}</td></tr>""")
    return "".join(rows)

# --- Service Status / Restart ---
def service_status(unit):
    info = {"unit": unit, "active": "unknown", "enabled": "unknown", "detail": ""}
    try:
        state = subprocess.check_output(["systemctl", "is-active", unit], text=True, timeout=2).strip()
        info["active"] = state
    except Exception:
        info["active"] = "unknown"
    try:
        en = subprocess.check_output(["systemctl", "is-enabled", unit], text=True, timeout=2).strip()
        info["enabled"] = en
    except Exception:
        info["enabled"] = "unknown"
    try:
        detail = subprocess.check_output(
            ["systemctl", "status", unit, "--no-pager", "-n", "3"],
            text=True, timeout=3
        )
        info["detail"] = detail
    except Exception as e:
        info["detail"] = f"status failed: {e}"
    return info

def restart_service(unit):
    try:
        proc = subprocess.run(
            ["sudo", "systemctl", "restart", unit],
            text=True,
            capture_output=True,
            timeout=15,
        )
        if proc.returncode == 0:
            msg = proc.stdout.strip() or f"{unit} neu gestartet"
            return True, msg
        else:
            msg = (
                f"systemctl exitcode {proc.returncode}\n"
                f"STDOUT:\n{proc.stdout}\n"
                f"STDERR:\n{proc.stderr}"
            )
            return False, msg
    except Exception as e:
        return False, f"restart fehlgeschlagen: {e}"

# --- Gemeinsame RetroPhone-Konfiguration ---
def read_retrophone_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
        return config if isinstance(config, dict) else {}
    except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError):
        return {}

def configured_phone_log_level():
    config = read_retrophone_config()
    phone_config = config.get("phone_daemon", {})
    if not isinstance(phone_config, dict):
        return "INFO"
    level = str(phone_config.get("log_level", "INFO")).upper()
    return level if level in VALID_LOG_LEVELS else "INFO"

def configured_gpio():
    gpio = read_retrophone_config().get("gpio", {})
    if not isinstance(gpio, dict):
        gpio = {}
    return {
        "pulse": int(gpio.get("pulse", 23)),
        "hook": int(gpio.get("hook", 18)),
        "dial_position": int(gpio.get("dial_position", 24)),
        "ring_a": int(gpio.get("ring_a", 17)),
        "ring_b": int(gpio.get("ring_b", 27)),
    }

def configured_expert():
    config = read_retrophone_config()
    phone = config.get("phone_daemon", {}) if isinstance(config.get("phone_daemon", {}), dict) else {}
    baresip = config.get("baresip_control", {}) if isinstance(config.get("baresip_control", {}), dict) else {}
    ring = config.get("ring", {}) if isinstance(config.get("ring", {}), dict) else {}
    return {
        "toggle_interval": float(ring.get("toggle_interval", 0.02)),
        "bs_host": str(baresip.get("host", "127.0.0.1")),
        "bs_port": int(baresip.get("port", 4444)),
        "bs_read_timeout": float(baresip.get("read_timeout", 0.8)),
        "bs_connect_timeout": float(baresip.get("connect_timeout", 1.0)),
        "bs_reconnect_pause": float(baresip.get("reconnect_pause", 0.8)),
        "dial_timeout": float(phone.get("dial_timeout", 2.5)),
        "debounce": float(phone.get("debounce", 0.006)),
        "min_pulse": float(phone.get("min_pulse", 0.004)),
        "max_pulse": float(phone.get("max_pulse", 0.08)),
        "calls_poll_interval": float(phone.get("calls_poll_interval", 0.6)),
        "ring_watchdog": float(phone.get("ring_watchdog", 2.0)),
    }

def audio_config():
    audio = read_retrophone_config().get("audio", {})
    return audio if isinstance(audio, dict) else {}

def mixer_percent(control, fallback):
    card = str(audio_config().get("card", "H340"))
    try:
        result = subprocess.run(
            ["amixer", "-c", card, "sget", control], text=True,
            capture_output=True, timeout=3, check=True
        )
        match = re.search(r"\[(\d{1,3})%\]", result.stdout)
        return max(0, min(100, int(match.group(1)))) if match else fallback
    except Exception:
        return fallback

def set_mixer_percent(control, value):
    card = str(audio_config().get("card", "H340"))
    result = subprocess.run(
        ["amixer", "-q", "-c", card, "sset", control, f"{value}%", "unmute"],
        text=True, capture_output=True, timeout=4
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"ALSA-Regler {control} konnte nicht gesetzt werden")

def write_retrophone_config(config):
    config_dir = os.path.dirname(CONFIG_PATH) or "."
    os.makedirs(config_dir, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=config_dir, prefix=".config-",
            suffix=".json", delete=False
        ) as config_file:
            temp_path = config_file.name
            json.dump(config, config_file, ensure_ascii=False, indent=2)
            config_file.write("\n")
            config_file.flush()
            os.fsync(config_file.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, CONFIG_PATH)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

def write_phone_log_level(level):
    config = read_retrophone_config()
    phone_config = config.get("phone_daemon")
    if not isinstance(phone_config, dict):
        phone_config = {}
        config["phone_daemon"] = phone_config
    phone_config["log_level"] = level
    write_retrophone_config(config)

# --- baresip Account Parsing ---
ACC_RE = re.compile(
    r'^\s*(?:"(?P<display>[^"]*)"\s*)?'
    r'<sip:(?P<aor>[^>]+)>\s*(?P<params>.*)$'
)

def read_account_line():
    p = accounts_path()
    if not os.path.exists(p):
        return ""
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                return line
    except Exception:
        pass
    return ""

def parse_account(line: str):
    acc = {
        "display":   "",
        "user":      "",
        "domain":    "",
        "transport": "udp",
        "auth_user": "",
        "auth_pass": "",
        "outbound":  "",
        "regint":    "3600",
    }
    if not line:
        return acc

    m = ACC_RE.match(line)
    if not m:
        return acc

    g = m.groupdict()
    acc["display"] = g.get("display") or ""
    aor            = g.get("aor") or ""
    params         = g.get("params") or ""

    if "@" in aor:
        userpart, dompart = aor.split("@", 1)
        if ":" in userpart:
            user, uri_pw = userpart.split(":", 1)
            acc["user"] = user
            if uri_pw:
                acc["auth_pass"] = uri_pw
        else:
            acc["user"] = userpart
        acc["domain"] = dompart
    else:
        acc["user"] = aor

    m_au = re.search(r';\s*auth_user\s*=\s*([^\s;]+)', params)
    if m_au:
        acc["auth_user"] = m_au.group(1)

    m_ap = re.search(r';\s*auth_pass\s*=\s*([^\s;]+)', params)
    if m_ap:
        acc["auth_pass"] = m_ap.group(1)

    m_ri = re.search(r';\s*regint\s*=\s*(\d+)', params)
    if m_ri:
        acc["regint"] = m_ri.group(1)

    m_ob = re.search(r';\s*outbound\s*=\s*"([^"]+)"', params)
    if m_ob:
        acc["outbound"] = m_ob.group(1)

    m_tr_uri = re.search(r';\s*transport=([\w]+)', params)
    if m_tr_uri:
        acc["transport"] = m_tr_uri.group(1)
    elif acc["outbound"]:
        m_tr_out = re.search(r';\s*transport=([\w]+)', acc["outbound"])
        if m_tr_out:
            acc["transport"] = m_tr_out.group(1)

    if not acc["auth_user"]:
        acc["auth_user"] = acc["user"]
    if not acc["regint"]:
        acc["regint"] = "3600"
    if not acc["transport"]:
        acc["transport"] = "udp"

    return acc

def build_account_line(acc):
    display   = acc.get("display", "").strip()
    user      = acc.get("user", "").strip()
    domain    = acc.get("domain", "").strip()
    transport = acc.get("transport", "udp").strip() or "udp"
    auth_user = acc.get("auth_user", "").strip() or user
    auth_pass = acc.get("auth_pass", "").strip()
    regint    = acc.get("regint", "").strip() or "300"
    outbound  = acc.get("outbound", "").strip()

    sip_uri = f"<sip:{user}@{domain}>"

    params = []
    if auth_user:
        params.append(f"auth_user={auth_user}")
    if auth_pass:
        params.append(f"auth_pass={auth_pass}")

    if outbound:
        if "transport=" not in outbound and transport:
            if ";" in outbound:
                outbound = outbound + f";transport={transport}"
            else:
                outbound = outbound + f";transport={transport}"
        params.append(f'outbound="{outbound}"')
    if regint:
        params.append(f"regint={regint}")

    disp_prefix = f"\"{display}\" " if display else ""
    if params:
        return f"{disp_prefix}{sip_uri};" + ";".join(params)
    else:
        return f"{disp_prefix}{sip_uri}"

def write_accounts_file(line: str):
    p = accounts_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if os.path.exists(p):
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        subprocess.call(["cp", "-a", p, f"{p}.bak.{ts}"])
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(line.strip() + "\n")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, p)
    return p

def configured_account():
    config = read_retrophone_config()
    sip = config.get("sip", {})
    if isinstance(sip, dict) and sip.get("user") and sip.get("domain"):
        return {
            "display": str(sip.get("display", "")),
            "user": str(sip.get("user", "")),
            "domain": str(sip.get("domain", "")),
            "transport": str(sip.get("transport", "udp")),
            "auth_user": str(sip.get("auth_user", sip.get("user", ""))),
            "auth_pass": str(sip.get("auth_pass", "")),
            "outbound": str(sip.get("outbound", "")),
            "regint": str(sip.get("registration_interval", 3600)),
        }
    return parse_account(read_account_line())

def save_account_config(acc):
    config = read_retrophone_config()
    config["sip"] = {
        "display": acc.get("display", ""),
        "user": acc.get("user", ""),
        "domain": acc.get("domain", ""),
        "transport": acc.get("transport", "udp"),
        "auth_user": acc.get("auth_user", ""),
        "auth_pass": acc.get("auth_pass", ""),
        "outbound": acc.get("outbound", ""),
        "registration_interval": int(acc.get("regint", 3600)),
    }
    write_retrophone_config(config)

# --- Dashboard Helfer ---
def service_badge(state):
    if state == "active":
        return "ok", "aktiv"
    if state in ("inactive", "failed", "deactivating"):
        return "err", state
    return "warn", state or "unbekannt"

def file_mtime_text(path):
    try:
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "-"

def latest_backup():
    if not os.path.isdir(BACKUP_DIR):
        return None
    try:
        candidates = []
        for name in os.listdir(BACKUP_DIR):
            full = os.path.join(BACKUP_DIR, name)
            if not os.path.isfile(full):
                continue
            low = name.lower()
            if "retrophone" in low and (low.endswith(".img") or low.endswith(".img.gz") or low.endswith(".gz")):
                candidates.append(full)
        if not candidates:
            return None
        latest = max(candidates, key=os.path.getmtime)
        return {
            "path": latest,
            "name": os.path.basename(latest),
            "time": file_mtime_text(latest),
            "size": os.path.getsize(latest),
        }
    except Exception:
        return None

def cpu_temperature():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="ascii") as temp_file:
            return round(int(temp_file.read().strip()) / 1000.0, 1)
    except (FileNotFoundError, PermissionError, OSError, ValueError):
        return None

def wifi_status():
    result = {"connected": False, "ssid": "nicht verbunden", "signal_dbm": None, "ip": "-"}
    try:
        link = subprocess.run(
            ["/sbin/iw", "dev", "wlan0", "link"], text=True,
            capture_output=True, timeout=3
        ).stdout
        ssid_match = re.search(r"^\s*SSID:\s*(.+)$", link, re.MULTILINE)
        signal_match = re.search(r"^\s*signal:\s*(-?\d+)\s*dBm", link, re.MULTILINE)
        if ssid_match:
            result["connected"] = True
            result["ssid"] = ssid_match.group(1).strip()
        if signal_match:
            result["signal_dbm"] = int(signal_match.group(1))
    except Exception:
        pass
    try:
        address = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "wlan0"], text=True,
            capture_output=True, timeout=3
        ).stdout
        ip_match = re.search(r"\binet\s+([0-9.]+)/", address)
        if ip_match:
            result["ip"] = ip_match.group(1)
    except Exception:
        pass
    return result

def human_size(num):
    try:
        value = float(num)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
    except Exception:
        return "-"

def log_preview(path, lines=8):
    text = tail_file(path, lines)
    return html.escape(text)

def baresip_preview(lines=8):
    try:
        out = subprocess.check_output(
            ["journalctl", "-u", "baresip", "-n", str(lines), "--no-pager", "--output=short-iso"],
            text=True, timeout=3
        )
        return html.escape(out)
    except Exception as e:
        return html.escape(f"journalctl failed: {e}")

def recent_log_rows(limit=6):
    events = []
    for service, path in (("phone-daemon", PHONE_LOG), ("ring", RING_LOG)):
        for line in tail_file(path, 30).splitlines():
            match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[,\d]*\s+\w+\s+(.*)", line)
            if match:
                events.append((match.group(1), service, match.group(2)))
    try:
        output = subprocess.check_output(
            ["journalctl", "-u", "baresip", "-n", "80", "--no-pager", "--output=short-iso"],
            text=True, timeout=3
        )
        for line in output.splitlines():
            if "selected for " in line or "using best effort AF" in line:
                continue
            match = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})\S*\s+\S+\s+[^:]+:\s*(.*)", line)
            if match:
                events.append((f"{match.group(1)} {match.group(2)}", "baresip", match.group(3)))
    except Exception:
        pass
    events.sort(key=lambda item: item[0], reverse=True)
    if not events:
        return '<tr><td colspan="3"><span class="subtle">Keine aktuellen Logeinträge.</span></td></tr>'
    rows = []
    for ts, service, message in events[:limit]:
        try:
            display_ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y, %H:%M:%S")
        except ValueError:
            display_ts = ts
        rows.append(
            f'<tr><td>{html.escape(display_ts)}</td><td>{html.escape(service)}</td>'
            f'<td class="log-message" title="{html.escape(message)}">{html.escape(message)}</td></tr>'
        )
    return "".join(rows)

# --- Health ---
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/system-info")
@login_required
def system_info_api():
    return {"temperature_c": cpu_temperature(), "wifi": wifi_status()}

# --- Login / Logout ---
@app.get("/login")
def login():
    if is_logged_in():
        return redirect(url_for("index"))
    error = request.args.get("error", "")
    err_html = f'<p class="errtext">{html.escape(error)}</p>' if error else ""
    next_url = request.args.get("next", "/")
    body = f"""
<div class="card login-shell">
  <h1>Login</h1>
  <p class="subtle">Bitte mit den im Service-File gesetzten Zugangsdaten anmelden.</p>
  {err_html}
  <form method="post" action="{url_for('login_post')}">
    <input type="hidden" name="next" value="{html.escape(next_url)}">
    <label>Benutzername</label>
    <input name="username" autofocus>
    <label>Passwort</label>
    <input type="password" name="password">
    <div class="btn-row">
      <button class="btn primary" type="submit">Anmelden</button>
    </div>
    <p class="subtle" style="margin-top:8px;">
      Benutzername aktuell: <code>{html.escape(WEB_USER or '')}</code><br>
      Passwort wird in <code>/etc/systemd/system/retrophone-web.service</code> via Environment gesetzt.
    </p>
  </form>
</div>
"""
    return render_page("Login", "login", body, show_nav=False)

@app.post("/login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    next_url = request.form.get("next") or "/"
    if username == WEB_USER and password == WEB_PASS:
        session["logged_in"] = True
        return redirect(next_url)
    else:
        return redirect(url_for("login", error="Login fehlgeschlagen", next=next_url))

@app.get("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))

# --- Dashboard ---
@app.get("/")
@login_required
def index():
    acc = configured_account()
    expert = configured_expert()
    acc_ok = bool(acc.get("user") and acc.get("domain"))
    acc_status = "konfiguriert" if acc_ok else "nicht konfiguriert"
    acc_badge = "ok" if acc_ok else "err"
    recent_calls = read_calls(5)
    temperature = cpu_temperature()
    wifi = wifi_status()
    temperature_text = f"{temperature:.1f} °C" if temperature is not None else "– °C"
    wifi_text = f"{wifi['ssid']} · {wifi['signal_dbm']} dBm · {wifi['ip']}" if wifi["connected"] else "nicht verbunden"

    service_cards = []
    for key, unit in SERVICES.items():
        info = service_status(unit)
        css, label = service_badge(info["active"])
        display = {"phone": "Phone Daemon", "baresip": "baresip", "web": "Web GUI"}.get(key, key)
        icon = {"phone": "services", "baresip": "phone", "web": "monitor"}.get(key, "services")
        service_cards.append(f"""
<div class="status-card">
  <div class="status-top"><span class="status-title title-row">{ui_icon(icon)}{html.escape(display)}</span><span class="dot {css}"></span></div>
  <div class="status-main">{html.escape(label)}</div>
  <div class="status-meta">{html.escape(unit)} · {html.escape(info['enabled'])}</div>
  <div class="btn-row"><a class="btn" href="{url_for('service_restart', name=key)}">Neu starten</a></div>
</div>""")

    backup = latest_backup()
    backup_script_ready = os.path.isfile(BACKUP_SCRIPT) and os.access(BACKUP_SCRIPT, os.X_OK)
    if backup:
        backup_info = f"""
<div class="detail-row"><span class="k">Letztes Backup</span><span class="v">{html.escape(backup['time'])}</span></div>
<div class="detail-row"><span class="k">Datei</span><span class="v"><code>{html.escape(backup['name'])}</code></span></div>
<div class="detail-row"><span class="k">Grösse</span><span class="v">{human_size(backup['size'])}</span></div>
<div class="detail-row"><span class="k">Speicherort</span><span class="v">{html.escape(BACKUP_DIR)}</span></div>"""
    else:
        backup_info = '<div class="empty-state">Im konfigurierten Backup-Verzeichnis wurde noch kein RetroPhone-Image gefunden.</div>'

    if backup_script_ready:
        backup_button = f'<a class="btn primary" href="{url_for("backup_now")}">Jetzt Backup erstellen</a>'
        backup_state = '<span class="badge ok">bereit</span>'
    else:
        backup_button = '<span class="btn" style="opacity:.45;cursor:not-allowed">Backup nicht konfiguriert</span>'
        backup_state = '<span class="badge warn">Script fehlt</span>'

    body = f"""
<div class="hero dashboard-hero">
  <div><h1>RetroPhone Dashboard</h1><p>Telefonie, Dienste, Backup und Logs auf einen Blick.</p></div>
  <div class="system-info-strip">
    <div class="system-info-chip"><span class="dot ok"></span><span class="k">Temperatur</span><span class="v" id="dashboard-temperature">{html.escape(temperature_text)}</span></div>
    <div class="system-info-chip"><span class="dot {'ok' if wifi['connected'] else 'err'}" id="dashboard-wifi-dot"></span><span class="k">WLAN</span><span class="v" id="dashboard-wifi">{html.escape(wifi_text)}</span></div>
  </div>
</div>

<div class="section-head"><div><h2>Systemstatus</h2><p class="subtle">Live-Status der zentralen RetroPhone-Dienste.</p></div><a class="btn" href="{url_for('services_overview')}">Alle Services</a></div>
<div class="status-grid">{''.join(service_cards)}</div>

<div class="split-grid">
  <div class="card wide-card">
    <div class="title-row icon-box">{ui_icon('phone')}<h2>Telefonie &amp; SIP</h2></div>
    <p class="subtle">Aktuelle baresip-Konfiguration des RetroPhone.</p>
    <p><span class="badge {acc_badge}">SIP Account: {html.escape(acc_status)}</span></p>
    <div class="detail-list">
      <div class="detail-row"><span class="k">SIP-Status</span><span class="v"><span class="dot {'ok' if acc_ok else 'err'}" style="display:inline-block;margin-right:8px"></span>{html.escape(acc_status)}</span></div>
      <div class="detail-row"><span class="k">SIP-Account</span><span class="v">{html.escape((acc.get('user') or '-') + '@' + (acc.get('domain') or '-'))}</span></div>
      <div class="detail-row"><span class="k">Transport</span><span class="v">{html.escape((acc.get('transport') or '-').upper())}</span></div>
      <div class="detail-row"><span class="k">Steuerung</span><span class="v">{html.escape(str(expert['bs_host']))}:{expert['bs_port']}</span></div>
    </div>
    <div class="btn-row"><a class="btn primary" href="{url_for('account_form')}">SIP Account bearbeiten</a><a class="btn" href="{url_for('logs_baresip')}">baresip Log</a></div>
  </div>

  <div class="card wide-card">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px"><div><div class="title-row icon-box">{ui_icon('database')}<h2>Backup</h2></div><p class="subtle">SD-Image / Systemsicherung.</p></div>{backup_state}</div>
    <div class="detail-list">{backup_info}</div>
    <div class="btn-row">{backup_button}</div>
    <p class="subtle" style="margin-bottom:0">Verzeichnis: <code>{html.escape(BACKUP_DIR)}</code><br>Script: <code>{html.escape(BACKUP_SCRIPT)}</code></p>
  </div>

</div>

<div class="section-head"><div><div class="title-row">{ui_icon('phone')}<h2>Letzte Anrufe</h2></div><p class="subtle">Die fünf neuesten ein- und ausgehenden Anrufe.</p></div><a class="btn" href="{url_for('calls_overview')}">Alle Anrufe</a></div>
<table class="table dashboard-surface"><thead><tr><th>Richtung</th><th>Rufnummer</th><th>Zeitpunkt</th><th>Dauer</th><th>Status</th></tr></thead>
<tbody>{calls_table_rows(recent_calls)}</tbody></table>

<div class="section-head"><div><div class="title-row">{ui_icon('logs')}<h2>Aktuelle Logs</h2></div><p class="subtle">Die letzten Einträge der drei wichtigsten Logquellen.</p></div><a class="btn" href="{url_for('logs_phone')}">Logs öffnen</a></div>
<table class="table dashboard-table dashboard-surface"><thead><tr><th>Zeit</th><th>Dienst</th><th>Nachricht</th></tr></thead><tbody>{recent_log_rows(6)}</tbody></table>
<script>
(() => {{
  const updateSystemInfo = async () => {{
    try {{
      const response = await fetch('{url_for("system_info_api")}', {{cache: 'no-store'}});
      if (!response.ok) return;
      const data = await response.json();
      document.getElementById('dashboard-temperature').textContent = data.temperature_c === null ? '– °C' : `${{data.temperature_c.toFixed(1)}} °C`;
      document.getElementById('dashboard-wifi').textContent = data.wifi.connected ? `${{data.wifi.ssid}} · ${{data.wifi.signal_dbm ?? '–'}} dBm · ${{data.wifi.ip}}` : 'nicht verbunden';
      document.getElementById('dashboard-wifi-dot').className = `dot ${{data.wifi.connected ? 'ok' : 'err'}}`;
    }} catch (_) {{}}
  }};
  window.setInterval(updateSystemInfo, 10000);
}})();
</script>
"""
    return render_page("Dashboard", "home", body)

@app.get("/settings")
@login_required
def settings_overview():
    gpio = configured_gpio()
    expert = configured_expert()
    stored_audio = audio_config()
    handset_volume = mixer_percent("PCM", int(stored_audio.get("handset_volume", 100)))
    microphone_volume = mixer_percent("Mic", int(stored_audio.get("microphone_volume", 100)))
    phone_log_level = configured_phone_log_level()
    level_options = "".join(
        f'<option value="{level}"{(" selected" if level == phone_log_level else "")}>{level}</option>'
        for level in VALID_LOG_LEVELS
    )
    def info_tip(description, default):
        text = f"{description} Standardwert: {default}."
        return f'<span class="info-tip" tabindex="0" role="img" aria-label="{html.escape(text)}" title="{html.escape(text)}">i</span>'
    body = f"""
<div class="hero"><h1>Einstellungen</h1><p>Telefonie, Hardware und erweiterte Systemparameter.</p></div>
<div class="card"><div class="title-row">{ui_icon('phone')}<h2>SIP-Account</h2></div><p class="subtle">Zugangsdaten, Domain, Transport und Registrierung für baresip.</p>
<div class="btn-row"><a class="btn primary" href="{url_for('account_form')}">SIP-Account öffnen</a></div></div>

<div class="card"><div class="title-row">{ui_icon('settings')}<h2>GPIO-Einstellungen</h2></div><p class="subtle">BCM-Portnummern für Telefon und Klingel.</p>
<form method="post" action="{url_for('save_gpio')}"><div class="metric-grid">
<label>Wählimpulse<input required type="number" min="0" max="27" name="pulse" value="{gpio['pulse']}"></label>
<label>Hörer<input required type="number" min="0" max="27" name="hook" value="{gpio['hook']}"></label>
<label>Rücklaufkontakt<input required type="number" min="0" max="27" name="dial_position" value="{gpio['dial_position']}"></label>
<label>Klingel A<input required type="number" min="0" max="27" name="ring_a" value="{gpio['ring_a']}"></label>
<label>Klingel B<input required type="number" min="0" max="27" name="ring_b" value="{gpio['ring_b']}"></label></div>
<div class="btn-row"><button class="btn primary" type="submit">GPIO speichern &amp; neu starten</button></div></form></div>

<div class="card"><div class="title-row">{ui_icon('monitor')}<h2>Audio</h2></div><p class="subtle">Lautstärke des Logitech-Headsets direkt über ALSA einstellen.</p>
<form method="post" action="{url_for('save_audio_settings')}"><div class="grid-2">
<label>Hörerlautstärke <span class="badge" id="handset-volume-label">{handset_volume} %</span><input id="handset-volume" type="range" min="0" max="100" step="1" name="handset_volume" value="{handset_volume}"></label>
<label>Mikrofonlautstärke <span class="badge" id="microphone-volume-label">{microphone_volume} %</span><input id="microphone-volume" type="range" min="0" max="100" step="1" name="microphone_volume" value="{microphone_volume}"></label>
</div><div class="btn-row"><button class="btn primary" type="submit">Audiopegel übernehmen</button></div></form></div>

<div class="card"><div class="title-row">{ui_icon('logs')}<h2>Logging</h2></div><p class="subtle">Detailgrad des technischen Phone-Logs.</p>
<form method="post" action="{url_for('save_phone_log_level')}"><label>Log-Level</label>
<select name="log_level">{level_options}</select><div class="btn-row"><button class="btn primary" type="submit">Speichern &amp; neu starten</button></div></form></div>

<div class="card"><div class="title-row">{ui_icon('services')}<h2>Experte</h2></div><p class="subtle">Diese Werte beeinflussen Zeitverhalten, Impulserkennung und baresip-Steuerung. Nur ändern, wenn ihre Wirkung bekannt ist.</p>
<form method="post" action="{url_for('save_expert_settings')}">
<div class="metric-grid">
<div class="toggle-pair"><label>Toggle-Intervall {info_tip('Zeit in Sekunden zwischen den elektrischen Umschaltungen der Klingelspulen. Ein vollständiger Zyklus besteht aus zwei Umschaltungen.', '0.02 s = 25 Hz')}<input id="toggle-interval" required type="number" step="0.001" min="0.001" name="toggle_interval" value="{expert['toggle_interval']}"></label><div class="hz-compact" id="toggle-frequency">{1 / (2 * expert['toggle_interval']):.2f} Hz</div></div>
<label>BS Host {info_tip('IP-Adresse der lokalen baresip-Steuerschnittstelle.', '127.0.0.1')}<input required name="bs_host" value="{html.escape(expert['bs_host'])}"></label>
<label>BS Port {info_tip('TCP-Port der baresip-Steuerschnittstelle ctrl_tcp.', '4444')}<input required type="number" min="1" max="65535" name="bs_port" value="{expert['bs_port']}"></label>
<label>BS Read Timeout {info_tip('Maximale Wartezeit in Sekunden auf eine baresip-Antwort.', '0.8 s')}<input required type="number" step="0.1" min="0.1" name="bs_read_timeout" value="{expert['bs_read_timeout']}"></label>
<label>BS Connect Timeout {info_tip('Maximale Wartezeit in Sekunden beim Aufbau der Steuerverbindung.', '1.0 s')}<input required type="number" step="0.1" min="0.1" name="bs_connect_timeout" value="{expert['bs_connect_timeout']}"></label>
<label>BS Reconnect Pause {info_tip('Mindestpause in Sekunden vor einem erneuten Verbindungsversuch.', '0.8 s')}<input required type="number" step="0.1" min="0.1" name="bs_reconnect_pause" value="{expert['bs_reconnect_pause']}"></label>
<label>Dial Timeout {info_tip('Pause in Sekunden nach der letzten Ziffer, bevor die Nummer gewählt wird.', '2.5 s')}<input required type="number" step="0.1" min="0.1" name="dial_timeout" value="{expert['dial_timeout']}"></label>
<label>Debounce {info_tip('Entprellzeit in Sekunden für mechanische Kontakte.', '0.006 s')}<input required type="number" step="0.001" min="0.001" name="debounce" value="{expert['debounce']}"></label>
<label>Min Pulse Low {info_tip('Kürzeste gültige Dauer eines Wählimpulses in Sekunden.', '0.004 s')}<input required type="number" step="0.001" min="0.001" name="min_pulse" value="{expert['min_pulse']}"></label>
<label>Max Pulse Low {info_tip('Längste gültige Dauer eines Wählimpulses in Sekunden.', '0.08 s')}<input required type="number" step="0.001" min="0.001" name="max_pulse" value="{expert['max_pulse']}"></label>
<label>Calls Poll-Intervall {info_tip('Abstand in Sekunden zwischen Statusabfragen bei baresip.', '0.6 s')}<input required type="number" step="0.1" min="0.1" name="calls_poll_interval" value="{expert['calls_poll_interval']}"></label>
<label>Ring Watchdog {info_tip('Zeit in Sekunden ohne eingehenden Status, nach der die Klingel gestoppt wird.', '2.0 s')}<input required type="number" step="0.1" min="0.1" name="ring_watchdog" value="{expert['ring_watchdog']}"></label>
</div><div class="btn-row"><button class="btn primary" type="submit">Experteneinstellungen speichern &amp; neu starten</button></div></form></div>
<script>
(() => {{
  const interval = document.getElementById('toggle-interval');
  const frequency = document.getElementById('toggle-frequency');
  const updateFrequency = () => {{
    const value = Number.parseFloat(interval.value);
    frequency.textContent = Number.isFinite(value) && value > 0
      ? `${{(1 / (2 * value)).toFixed(2)}} Hz`
      : '– Hz';
  }};
  interval.addEventListener('input', updateFrequency);
  updateFrequency();
  for (const name of ['handset-volume', 'microphone-volume']) {{
    const slider = document.getElementById(name);
    const label = document.getElementById(`${{name}}-label`);
    slider.addEventListener('input', () => label.textContent = `${{slider.value}} %`);
  }}
}})();
</script>
"""
    return render_page("Einstellungen", "settings", body)

@app.get("/calls")
@login_required
def calls_overview():
    body = f"""
<div class="card"><h1>Anrufprotokoll</h1>
<p class="subtle">Die letzten 20 Anrufe werden dauerhaft gespeichert und nach einem Neustart wieder angezeigt.</p>
<table class="table"><thead><tr><th>Richtung</th><th>Rufnummer</th><th>Zeitpunkt</th><th>Dauer</th><th>Status</th></tr></thead>
<tbody>{calls_table_rows(read_calls(20))}</tbody></table>
<div class="btn-row"><a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a></div></div>"""
    return render_page("Anrufe", "calls", body)

@app.post("/settings/log-level")
@login_required
def save_phone_log_level():
    level = (request.form.get("log_level") or "").strip().upper()
    if level not in VALID_LOG_LEVELS:
        return Response("Ungültiger Log-Level", 400)

    try:
        write_phone_log_level(level)
    except Exception as e:
        body = f"""
<div class="card"><h2>Log-Level konnte nicht gespeichert werden</h2>
<p><span class="badge err">Fehler</span></p>
<p class="subtle">Die Webapp benötigt Schreibrechte auf das Konfigurationsverzeichnis.</p>
<pre>{html.escape(str(e))}</pre>
<div class="btn-row"><a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a></div></div>"""
        return render_page("Konfigurationsfehler", "home", body), 500

    ok, msg = restart_service(SERVICES["phone"])
    badge = "ok" if ok else "warn"
    heading = "Log-Level gespeichert" if ok else "Log-Level gespeichert – Neustart fehlgeschlagen"
    body = f"""
<div class="card"><h2>{heading}</h2>
<p><span class="badge {badge}">{html.escape(level)}</span></p>
<p class="subtle">Die Einstellung wurde dauerhaft in <code>{html.escape(CONFIG_PATH)}</code> gespeichert.</p>
<pre>{html.escape(msg)}</pre>
<div class="btn-row"><a class="btn primary" href="{url_for('settings_overview')}">Zurück zu Einstellungen</a></div></div>"""
    return render_page("Log-Level", "settings", body), (200 if ok else 503)

@app.post("/settings/gpio")
@login_required
def save_gpio():
    names = ("pulse", "hook", "dial_position", "ring_a", "ring_b")
    try:
        values = {name: int(request.form.get(name, "")) for name in names}
    except ValueError:
        return Response("GPIO-Werte müssen ganze Zahlen sein.", 400)
    if any(value < 0 or value > 27 for value in values.values()):
        return Response("GPIO-Werte müssen zwischen 0 und 27 liegen.", 400)
    if len(set(values.values())) != len(values):
        return Response("Jeder GPIO-Port darf nur einmal verwendet werden.", 400)
    config = read_retrophone_config()
    config["gpio"] = values
    write_retrophone_config(config)
    ok, msg = restart_service(SERVICES["phone"])
    badge = "ok" if ok else "warn"
    body = f"""<div class="card"><h2>GPIO-Konfiguration gespeichert</h2>
<p><span class="badge {badge}">{html.escape('aktiv' if ok else 'Neustart fehlgeschlagen')}</span></p>
<pre>{html.escape(msg)}</pre><div class="btn-row"><a class="btn" href="{url_for('settings_overview')}">Zurück zu Einstellungen</a></div></div>"""
    return render_page("GPIO", "settings", body), (200 if ok else 503)

@app.post("/settings/audio")
@login_required
def save_audio_settings():
    try:
        handset = int(request.form.get("handset_volume", ""))
        microphone = int(request.form.get("microphone_volume", ""))
    except ValueError:
        return Response("Audiopegel müssen ganze Prozentwerte sein.", 400)
    if not (0 <= handset <= 100 and 0 <= microphone <= 100):
        return Response("Audiopegel müssen zwischen 0 und 100 Prozent liegen.", 400)
    try:
        set_mixer_percent("PCM", handset)
        set_mixer_percent("Mic", microphone)
        config = read_retrophone_config()
        audio = config.setdefault("audio", {})
        audio.update({
            "card": "H340", "playback_control": "PCM", "capture_control": "Mic",
            "handset_volume": handset, "microphone_volume": microphone,
        })
        write_retrophone_config(config)
    except Exception as e:
        body = f"""<div class="card"><h2>Audiopegel konnten nicht gesetzt werden</h2>
<p><span class="badge err">Fehler</span></p><pre>{html.escape(str(e))}</pre>
<div class="btn-row"><a class="btn" href="{url_for('settings_overview')}">Zurück zu Einstellungen</a></div></div>"""
        return render_page("Audiofehler", "settings", body), 500
    body = f"""<div class="card"><h2>Audiopegel übernommen</h2><p><span class="badge ok">aktiv</span></p>
<p>Hörer: <code>{handset} %</code><br>Mikrofon: <code>{microphone} %</code></p>
<div class="btn-row"><a class="btn primary" href="{url_for('settings_overview')}">Zurück zu Einstellungen</a></div></div>"""
    return render_page("Audio", "settings", body)

@app.post("/settings/expert")
@login_required
def save_expert_settings():
    try:
        bs_host = (request.form.get("bs_host") or "").strip()
        bs_port = int(request.form.get("bs_port", ""))
        values = {
            "toggle_interval": float(request.form.get("toggle_interval", "")),
            "bs_read_timeout": float(request.form.get("bs_read_timeout", "")),
            "bs_connect_timeout": float(request.form.get("bs_connect_timeout", "")),
            "bs_reconnect_pause": float(request.form.get("bs_reconnect_pause", "")),
            "dial_timeout": float(request.form.get("dial_timeout", "")),
            "debounce": float(request.form.get("debounce", "")),
            "min_pulse": float(request.form.get("min_pulse", "")),
            "max_pulse": float(request.form.get("max_pulse", "")),
            "calls_poll_interval": float(request.form.get("calls_poll_interval", "")),
            "ring_watchdog": float(request.form.get("ring_watchdog", "")),
        }
    except ValueError:
        return Response("Expertenwerte haben ein ungültiges Zahlenformat.", 400)
    if not bs_host or not (1 <= bs_port <= 65535):
        return Response("BS Host oder Port ist ungültig.", 400)
    if any(value <= 0 for value in values.values()):
        return Response("Zeitwerte müssen größer als null sein.", 400)
    if values["min_pulse"] >= values["max_pulse"]:
        return Response("Min Pulse Low muss kleiner als Max Pulse Low sein.", 400)

    config = read_retrophone_config()
    config.setdefault("ring", {})["toggle_interval"] = values["toggle_interval"]
    config["baresip_control"] = {
        "host": bs_host, "port": bs_port,
        "read_timeout": values["bs_read_timeout"],
        "connect_timeout": values["bs_connect_timeout"],
        "reconnect_pause": values["bs_reconnect_pause"],
    }
    phone = config.setdefault("phone_daemon", {})
    phone.update({
        "dial_timeout": values["dial_timeout"], "debounce": values["debounce"],
        "min_pulse": values["min_pulse"], "max_pulse": values["max_pulse"],
        "calls_poll_interval": values["calls_poll_interval"],
        "ring_watchdog": values["ring_watchdog"],
    })
    write_retrophone_config(config)
    ok, msg = restart_service(SERVICES["phone"])
    badge = "ok" if ok else "warn"
    body = f"""<div class="card"><h2>Experteneinstellungen gespeichert</h2>
<p><span class="badge {badge}">{html.escape('aktiv' if ok else 'Neustart fehlgeschlagen')}</span></p>
<pre>{html.escape(msg)}</pre><div class="btn-row"><a class="btn" href="{url_for('settings_overview')}">Zurück zu Einstellungen</a></div></div>"""
    return render_page("Experteneinstellungen", "settings", body), (200 if ok else 503)

@app.get("/action/backup")
@login_required
def backup_now():
    if not (os.path.isfile(BACKUP_SCRIPT) and os.access(BACKUP_SCRIPT, os.X_OK)):
        body = f"""
<div class="card"><h2>Backup nicht konfiguriert</h2>
<p class="subtle">Das erwartete Backup-Script ist nicht vorhanden oder nicht ausführbar.</p>
<pre>{html.escape(BACKUP_SCRIPT)}</pre>
<div class="btn-row"><a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a></div></div>"""
        return render_page("Backup", "home", body), 503
    try:
        backup_log = os.path.join(str(PATH_CONFIG.get("runtime_dir", "/run/retrophone")), "backup.log")
        log_handle = open(backup_log, "a", encoding="utf-8")
        proc = subprocess.Popen(
            ["sudo", "-n", BACKUP_SCRIPT, "backup"],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log_handle.close()
        time.sleep(0.35)
        return_code = proc.poll()
        if return_code is not None:
            try:
                with open(backup_log, "r", encoding="utf-8", errors="replace") as backup_log_file:
                    detail = "\n".join(backup_log_file.read().splitlines()[-12:])
            except OSError:
                detail = "Keine Detailmeldung verfügbar."
            body = f"""
<div class="card"><h2>Backup konnte nicht gestartet werden</h2>
<p><span class="badge err">Start fehlgeschlagen</span></p>
<p class="subtle">Der Webdienst benötigt eine passwortlose Freigabe ausschließlich für das RetroPhone-Backup-Script.</p>
<pre>{html.escape(detail)}</pre>
<div class="btn-row"><a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a></div></div>"""
            return render_page("Backup Fehler", "home", body), 503
        body = f"""
<div class="card"><h2>Backup gestartet</h2>
<p><span class="badge ok" id="backup-badge">gestartet</span></p>
<div class="progress-track"><div class="progress-bar" id="backup-progress"></div></div>
<p><strong id="backup-percent">0 %</strong> · <span id="backup-message">Backup wird gestartet …</span></p>
<p class="subtle">Das Backup läuft im Hintergrund (PID {proc.pid}). Diese Anzeige aktualisiert sich automatisch. Meldungen werden in <code>{html.escape(backup_log)}</code> geschrieben.</p>
<div class="btn-row"><a class="btn primary" href="{url_for('index')}">Zurück zum Dashboard</a></div></div>"""
        body += f"""
<script>
(() => {{
  const poll = async () => {{
    try {{
      const response = await fetch('{url_for("backup_status_api")}', {{cache: 'no-store'}});
      const data = await response.json();
      const percent = Math.max(0, Math.min(100, Number(data.percent || 0)));
      const bar = document.getElementById('backup-progress');
      bar.style.width = `${{percent}}%`;
      document.getElementById('backup-percent').textContent = `${{percent}} %`;
      document.getElementById('backup-message').textContent = data.message || 'Status wird ermittelt …';
      if (data.state === 'complete') {{
        bar.classList.add('done');
        document.getElementById('backup-badge').textContent = 'fertig';
        return;
      }}
      if (data.state === 'error') {{
        bar.classList.add('error');
        document.getElementById('backup-badge').className = 'badge err';
        document.getElementById('backup-badge').textContent = 'fehlgeschlagen';
        return;
      }}
      window.setTimeout(poll, 1000);
    }} catch (_) {{ window.setTimeout(poll, 2000); }}
  }};
  poll();
}})();
</script>"""
        return render_page("Backup gestartet", "home", body)
    except Exception as e:
        body = f"""
<div class="card"><h2>Backup konnte nicht gestartet werden</h2>
<p><span class="badge err">Fehler</span></p><pre>{html.escape(str(e))}</pre>
<div class="btn-row"><a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a></div></div>"""
        return render_page("Backup Fehler", "home", body), 500

@app.get("/api/backup-status")
@login_required
def backup_status_api():
    status_file = os.path.join(str(PATH_CONFIG.get("runtime_dir", "/run/retrophone")), "backup-status.json")
    try:
        with open(status_file, "r", encoding="utf-8") as status_handle:
            status = json.load(status_handle)
        if isinstance(status, dict):
            return status
    except (FileNotFoundError, PermissionError, OSError, ValueError, TypeError):
        pass
    return {"state": "starting", "percent": 0, "message": "Backup wird gestartet …"}

# --- Login-Info Seite (nur Info, kein Edit) ---
@app.get("/auth-info")
@login_required
def auth_info():
    user = WEB_USER or "(nicht gesetzt)"
    service_file = "/etc/systemd/system/retrophone-web.service"
    body = f"""
<div class="card">
  <h1>Login / Authentifizierung</h1>
  <p class="subtle">Die Weboberfläche nutzt ein Login-Formular. Die Zugangsdaten werden im Service-File gesetzt.</p>
  <form>
    <label>Benutzername (RETRO_WEB_USER)</label>
    <input value="{html.escape(user)}" readonly>
    <label>Passwort (RETRO_WEB_PASS)</label>
    <input type="password" value="{ '********' if WEB_PASS else '' }" readonly>
  </form>
  <p class="subtle" style="margin-top:10px;">
    Quelle: <code>{html.escape(service_file)}</code><br>
    Beispiel:
  </p>
  <pre>[Service]
User=pi
Group=pi
Environment=RETRO_WEB_USER={html.escape(user)}
Environment=RETRO_WEB_PASS=&lt;dein_passwort&gt;
ExecStart=/usr/bin/python3 /usr/local/retrophone/webapp.py
...</pre>
  <p class="subtle">
    Änderung: <code>sudo nano {html.escape(service_file)}</code><br>
    Danach: <code>sudo systemctl daemon-reload</code> und <code>sudo systemctl restart retrophone-web.service</code>.
  </p>
  <div class="btn-row">
    <a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a>
  </div>
</div>
"""
    return render_page("Login-Info", "auth", body)

# Alias, damit Nav-Links funktionieren
auth_info = app.view_functions["auth_info"]

# --- Logs mit Auto-Refresh Toggle ---
@app.get("/logs/phone")
@login_required
def logs_phone():
    auto = (request.args.get("auto", "1") == "1")
    auto_refresh = 2 if auto else None
    toggle_auto = "0" if auto else "1"
    toggle_label = "Auto-Refresh pausieren" if auto else "Auto-Refresh aktivieren"
    toggle_url = url_for('logs_phone', auto=toggle_auto)

    try:
        data = html.escape(tail_file(PHONE_LOG))
    except Exception as e:
        data = f"Fehler beim Lesen des Logs: {html.escape(str(e))}"

    body = f"""
<div class="card">
  <h2>Phone Log</h2>
  <p class="subtle">
    Letzte Einträge.{" Seite aktualisiert automatisch." if auto else " Auto-Refresh ist pausiert."}
  </p>
  <div class="tabs">
    <a class="tab active" href="{url_for('logs_phone', auto=('1' if auto else '0'))}">Phone</a>
    <a class="tab" href="{url_for('logs_ring', auto=('1' if auto else '0'))}">Ring</a>
    <a class="tab" href="{url_for('logs_baresip', auto=('1' if auto else '0'))}">baresip</a>
  </div>
  <pre>{data}</pre>
  <div class="btn-row">
    <a class="btn" href="{toggle_url}">{toggle_label}</a>
    <a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a>
  </div>
</div>
"""
    return render_page("Phone Log", "logs", body, auto_refresh=auto_refresh)

@app.get("/logs/ring")
@login_required
def logs_ring():
    auto = (request.args.get("auto", "1") == "1")
    auto_refresh = 2 if auto else None
    toggle_auto = "0" if auto else "1"
    toggle_label = "Auto-Refresh pausieren" if auto else "Auto-Refresh aktivieren"
    toggle_url = url_for('logs_ring', auto=toggle_auto)

    try:
        data = html.escape(tail_file(RING_LOG))
    except Exception as e:
        data = f"Fehler beim Lesen des Logs: {html.escape(str(e))}"

    body = f"""
<div class="card">
  <h2>Ring Log</h2>
  <p class="subtle">
    Letzte Einträge.{" Seite aktualisiert automatisch." if auto else " Auto-Refresh ist pausiert."}
  </p>
  <div class="tabs">
    <a class="tab" href="{url_for('logs_phone', auto=('1' if auto else '0'))}">Phone</a>
    <a class="tab active" href="{url_for('logs_ring', auto=('1' if auto else '0'))}">Ring</a>
    <a class="tab" href="{url_for('logs_baresip', auto=('1' if auto else '0'))}">baresip</a>
  </div>
  <pre>{data}</pre>
  <div class="btn-row">
    <a class="btn" href="{toggle_url}">{toggle_label}</a>
    <a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a>
  </div>
</div>
"""
    return render_page("Ring Log", "logs", body, auto_refresh=auto_refresh)

@app.get("/logs/baresip")
@login_required
def logs_baresip():
    auto = (request.args.get("auto", "1") == "1")
    auto_refresh = 3 if auto else None
    toggle_auto = "0" if auto else "1"
    toggle_label = "Auto-Refresh pausieren" if auto else "Auto-Refresh aktivieren"
    toggle_url = url_for('logs_baresip', auto=toggle_auto)

    try:
        data = html.escape(tail_baresip())
    except Exception as e:
        data = f"Fehler beim Lesen des Logs: {html.escape(str(e))}"

    body = f"""
<div class="card">
  <h2>baresip Log</h2>
  <p class="subtle">
    Ausgabe von journalctl für baresip.{" Seite aktualisiert automatisch." if auto else " Auto-Refresh ist pausiert."}
  </p>
  <div class="tabs">
    <a class="tab" href="{url_for('logs_phone', auto=('1' if auto else '0'))}">Phone</a>
    <a class="tab" href="{url_for('logs_ring', auto=('1' if auto else '0'))}">Ring</a>
    <a class="tab active" href="{url_for('logs_baresip', auto=('1' if auto else '0'))}">baresip</a>
  </div>
  <pre>{data}</pre>
  <div class="btn-row">
    <a class="btn" href="{toggle_url}">{toggle_label}</a>
    <a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a>
  </div>
</div>
"""
    return render_page("baresip Log", "logs", body, auto_refresh=auto_refresh)

# --- Account ---
@app.get("/account")
@login_required
def account_form():
    acc = configured_account()
    def esc(x): return html.escape(x or "")
    transports = ["udp", "tcp", "tls"]
    opts = "".join(
        f'<option value="{t}" {"selected" if (acc.get("transport") or "udp")==t else ""}>{t}</option>'
        for t in transports
    )
    body = f"""
<div class="card">
  <h1>SIP Account</h1>
  <p class="subtle">Konfiguration des baresip Accounts. Nach Änderung baresip neu starten.</p>
  <form method="post" action="{url_for('account_save')}">
    <label>Display Name (optional)</label>
    <input name="display" value="{esc(acc.get('display'))}">
    <label>Benutzername (User)</label>
    <input required name="user" value="{esc(acc.get('user'))}">
    <label>Passwort (auth_pass)</label>
    <input type="password" name="auth_pass" value="{esc(acc.get('auth_pass'))}">
    <label>Domain (z. B. sip.netvoip.ch)</label>
    <input required name="domain" value="{esc(acc.get('domain'))}">
    <label>Auth User (optional, meist gleich wie User)</label>
    <input name="auth_user" value="{esc(acc.get('auth_user'))}">
    <label>Transport</label>
    <select name="transport">{opts}</select>
    <label>Outbound Proxy (z. B. sip:sip.netvoip.ch;transport=udp)</label>
    <input name="outbound" value="{esc(acc.get('outbound'))}">
    <label>Registrierintervall (regint, Sekunden)</label>
    <input name="regint" value="{esc(acc.get('regint') or "300")}">
    <div class="btn-row">
      <button class="btn primary" type="submit">Speichern</button>
      <a class="btn" href="{url_for('action_restart_baresip')}">baresip neu starten</a>
      <a class="btn" href="{url_for('settings_overview')}">Abbrechen</a>
    </div>
    <p class="subtle" style="margin-top:8px;">Accounts Datei: <code>{html.escape(accounts_path())}</code></p>
  </form>
</div>
"""
    return render_page("SIP Account", "settings", body)

@app.post("/account")
@login_required
def account_save():
    fields = {
        "display":   (request.form.get("display")   or "").strip(),
        "user":      (request.form.get("user")      or "").strip(),
        "domain":    (request.form.get("domain")    or "").strip(),
        "transport": (request.form.get("transport") or "").strip() or "udp",
        "auth_user": (request.form.get("auth_user") or "").strip(),
        "auth_pass": (request.form.get("auth_pass") or "").strip(),
        "outbound":  (request.form.get("outbound")  or "").strip(),
        "regint":    (request.form.get("regint")    or "").strip() or "300",
    }
    if not fields["user"] or not fields["domain"]:
        return Response("user und domain sind Pflicht.", 400)
    if fields["regint"] and not fields["regint"].isdigit():
        return Response("regint muss numerisch sein.", 400)
    if not fields["auth_user"]:
        fields["auth_user"] = fields["user"]

    line = build_account_line(fields)
    save_account_config(fields)
    p = write_accounts_file(line)

    body = f"""
<div class="card">
  <h2>Gespeichert</h2>
  <p class="subtle">Accounts Datei aktualisiert.</p>
  <p><code>{html.escape(p)}</code></p>
  <pre>{html.escape(line)}</pre>
  <div class="btn-row">
    <a class="btn primary" href="{url_for('action_restart_baresip')}">baresip jetzt neu starten</a>
    <a class="btn" href="{url_for('account_form')}">Zurück zum Account</a>
    <a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a>
  </div>
</div>
"""
    return render_page("Gespeichert", "settings", body)

@app.get("/action/restart")
@login_required
def action_restart_baresip():
    ok, msg = restart_service(SERVICES["baresip"])
    badge = "ok" if ok else "err"
    body = f"""
<div class="card">
  <h2>baresip Restart</h2>
  <p><span class="badge {badge}">{html.escape("Erfolg" if ok else "Fehler")}</span></p>
  <pre>{html.escape(msg)}</pre>
  <div class="btn-row">
    <a class="btn" href="{url_for('services_overview')}">Zu Services</a>
    <a class="btn" href="{url_for('account_form')}">Zurück zum Account</a>
    <a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a>
  </div>
</div>
"""
    return render_page("Restart", "home", body)

# --- Service Übersicht ---
@app.get("/services")
@login_required
def services_overview():
    rows = []
    for key, unit in SERVICES.items():
        info = service_status(unit)
        st = info["active"]
        if st == "active":
            badge = '<span class="badge ok">running</span>'
        elif st in ("inactive", "failed", "deactivating"):
            badge = '<span class="badge err">' + html.escape(st) + '</span>'
        else:
            badge = '<span class="badge warn">' + html.escape(st) + '</span>'

        enabled = info["enabled"]
        rows.append(f"""
<tr>
  <td><code>{html.escape(unit)}</code></td>
  <td>{badge}</td>
  <td><span class="subtle">{html.escape(enabled)}</span></td>
  <td>
    <a class="btn" href="{url_for('service_restart', name=key)}">Restart</a>
  </td>
</tr>
""")
    table_rows = "\n".join(rows)
    body = f"""
<div class="card">
  <h1>Services</h1>
  <p class="subtle">Status der wichtigsten RetroPhone Dienste. Restart nutzt systemctl via sudo.</p>
  <table class="table">
    <thead>
      <tr><th>Service</th><th>Status</th><th>Enabled</th><th>Aktion</th></tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
  <div class="btn-row">
    <a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a>
  </div>
</div>
"""
    return render_page("Services", "services", body, auto_refresh=5)

@app.get("/services/restart/<name>")
@login_required
def service_restart(name):
    if name not in SERVICES:
        return Response("Unbekannter Service", 400)
    unit = SERVICES[name]
    ok, msg = restart_service(unit)
    badge = "ok" if ok else "err"
    body = f"""
<div class="card">
  <h2>Restart {html.escape(unit)}</h2>
  <p><span class="badge {badge}">{html.escape("Erfolg" if ok else "Fehler")}</span></p>
  <pre>{html.escape(msg)}</pre>
  <div class="btn-row">
    <a class="btn" href="{url_for('services_overview')}">Zurück zur Service Übersicht</a>
    <a class="btn" href="{url_for('index')}">Zurück zum Dashboard</a>
  </div>
</div>
"""
    return render_page("Service Restart", "services", body)

def apply_stored_audio_settings():
    audio = audio_config()
    try:
        if "handset_volume" in audio:
            set_mixer_percent(str(audio.get("playback_control", "PCM")), int(audio["handset_volume"]))
        if "microphone_volume" in audio:
            set_mixer_percent(str(audio.get("capture_control", "Mic")), int(audio["microphone_volume"]))
    except Exception:
        # Ein fehlendes/abgezogenes USB-Headset darf den Start des WebGUI nicht verhindern.
        pass

apply_stored_audio_settings()
# Noch vorhandene baresip-Ereignisse beim Start in die persistente Historie übernehmen.
read_calls(20)
threading.Thread(target=collect_incoming_calls, name="retrophone-call-log", daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
