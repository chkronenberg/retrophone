#!/usr/bin/env python3
import os
import re
import stat
import html
import subprocess
from datetime import datetime
from functools import wraps

from flask import Flask, request, Response, url_for, redirect, session

app = Flask(__name__)

# --- Secret fuer Session-Cookies ---
app.secret_key = os.environ.get("RETRO_WEB_SECRET", "retrophone-change-me")

# --- Pfade ---
PHONE_LOG = "/var/log/retrophone/phone.log"
RING_LOG  = "/var/log/retrophone/ring.log"

DEFAULT_ACCOUNTS  = "/home/pi/.baresip/accounts"
FALLBACK_ACCOUNTS = "/etc/baresip/accounts"

def accounts_path():
    return DEFAULT_ACCOUNTS if os.path.exists(DEFAULT_ACCOUNTS) else FALLBACK_ACCOUNTS

# --- Services fuer Uebersicht ---
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
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;margin:0;background:#0f172a;color:#e5e7eb}
a{text-decoration:none;color:inherit}
.header{background:#020617;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #1e293b}
.brand{font-weight:700;font-size:1.1rem;color:#e5e7eb}
.nav{display:flex;gap:8px}
.nav a{padding:6px 10px;border-radius:8px;font-size:0.9rem;color:#cbd5f5}
.nav a.active{background:#1e293b;color:#f9fafb}
.nav a:hover{background:#111827}
.main{padding:18px 20px}
.card{background:#020617;border:1px solid #1f2937;border-radius:12px;padding:16px;margin-bottom:16px;box-shadow:0 8px 20px rgba(0,0,0,0.35)}
h1{font-size:1.4rem;margin:0 0 10px}
h2{font-size:1.2rem;margin:0 0 10px}
pre{background:#020617;color:#e5e7eb;padding:10px;border-radius:8px;overflow:auto;max-height:70vh;border:1px solid #1f2937;font-size:0.8rem}
label{display:block;margin-top:10px;margin-bottom:2px;font-weight:600;font-size:0.9rem}
input,select{padding:7px 9px;margin-bottom:4px;width:100%;border-radius:8px;border:1px solid #1f2937;background:#020617;color:#e5e7eb;font-size:0.9rem}
input:focus,select:focus{outline:none;border-color:#3b82f6}
.btn-row{margin-top:14px;display:flex;flex-wrap:wrap;gap:8px}
.btn{display:inline-flex;align-items:center;justify-content:center;padding:7px 11px;border-radius:999px;border:1px solid #374151;font-size:0.9rem;background:#111827;color:#e5e7eb;cursor:pointer}
.btn.primary{background:#2563eb;border-color:#2563eb}
.btn.danger{background:#7f1d1d;border-color:#b91c1c}
.btn:disabled{opacity:0.5;cursor:default}
.subtle{font-size:0.8rem;color:#9ca3af}
.grid-2{display:grid;grid-template-columns:1.1fr 1fr;gap:16px}
@media(max-width:900px){.grid-2{grid-template-columns:1fr}}
.tabs{display:flex;gap:4px;margin-bottom:10px}
.tab{padding:6px 10px;border-radius:999px;border:1px solid #374151;font-size:0.85rem;background:#020617;color:#9ca3af}
.tab.active{background:#2563eb;border-color:#2563eb;color:#f9fafb}
.badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;font-size:0.75rem;border:1px solid #1f2937;background:#020617;color:#9ca3af}
.badge.ok{border-color:#16a34a;color:#bbf7d0}
.badge.warn{border-color:#f59e0b;color:#fef3c7}
.badge.err{border-color:#b91c1c;color:#fecaca}
.table{width:100%;border-collapse:collapse;font-size:0.9rem;margin-top:6px}
.table th,.table td{padding:6px 8px;border-bottom:1px solid #1f2937;text-align:left}
.table th{font-weight:600;color:#9ca3af}
.errtext{color:#fecaca;font-size:0.85rem;margin-bottom:8px}
"""

def render_page(title, active, body_html, auto_refresh=None, show_nav=True):
    refresh = f'<meta http-equiv="refresh" content="{int(auto_refresh)}">' if auto_refresh else ""
    if show_nav and is_logged_in():
        nav_html = f"""
<div class="header">
  <div class="brand">RetroPhone</div>
  <div class="nav">
    <a href="{url_for('index')}" class="{ 'active' if active=='home' else '' }">Dashboard</a>
    <a href="{url_for('account_form')}" class="{ 'active' if active=='account' else '' }">SIP Account</a>
    <a href="{url_for('logs_phone')}" class="{ 'active' if active=='logs' else '' }">Logs</a>
    <a href="{url_for('services_overview')}" class="{ 'active' if active=='services' else '' }">Services</a>
    <a href="{url_for('auth_info')}" class="{ 'active' if active=='auth' else '' }">Login-Info</a>
    <a href="{url_for('logout')}" class="{ 'active' if active=='logout' else '' }">Logout</a>
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

# --- Log Helfer ---
def tail_file(path, lines=200):
    if not os.path.exists(path):
        return f"{path} not found"
    try:
        out = subprocess.check_output(["tail", "-n", str(lines), path], text=True, timeout=2)
        return out
    except Exception as e:
        return f"tail failed: {e}"

def tail_baresip(lines=200):
    try:
        out = subprocess.check_output(
            ["journalctl", "-u", "baresip", "-n", str(lines), "--no-pager"],
            text=True, timeout=3
        )
        return out
    except Exception as e:
        return f"journalctl failed: {e}"

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

# --- Health ---
@app.get("/health")
def health():
    return {"status": "ok"}

# --- Login / Logout ---
@app.get("/login")
def login():
    if is_logged_in():
        return redirect(url_for("index"))
    error = request.args.get("error", "")
    err_html = f'<p class="errtext">{html.escape(error)}</p>' if error else ""
    next_url = request.args.get("next", "/")
    body = f"""
<div class="card" style="max-width:420px;margin:40px auto;">
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
    acc_line = read_account_line()
    acc = parse_account(acc_line)
    acc_status = "konfiguriert" if acc.get("user") and acc.get("domain") else "nicht konfiguriert"
    badge_class = "ok" if acc_status == "konfiguriert" else "err"
    body = f"""
<div class="grid-2">
  <div class="card">
    <h1>Uebersicht</h1>
    <p class="subtle">Schnellzugriff auf wichtigste Funktionen.</p>
    <p><span class="badge {badge_class}">SIP Account: {html.escape(acc_status)}</span></p>
    <ul class="subtle">
      <li>User: <code>{html.escape(acc.get('user') or '-')}</code></li>
      <li>Domain: <code>{html.escape(acc.get('domain') or '-')}</code></li>
      <li>Transport: <code>{html.escape(acc.get('transport') or '-')}</code></li>
    </ul>
    <div class="btn-row">
      <a class="btn primary" href="{url_for('account_form')}">SIP Account bearbeiten</a>
      <a class="btn" href="{url_for('logs_phone')}">Logs ansehen</a>
    </div>
  </div>
  <div class="card">
    <h2>System</h2>
    <p class="subtle">Infos zu baresip, Diensten und Logs.</p>
    <ul class="subtle">
      <li>Accounts Datei: <code>{html.escape(accounts_path())}</code></li>
      <li>Phone Log: <code>{html.escape(PHONE_LOG)}</code></li>
      <li>Ring Log: <code>{html.escape(RING_LOG)}</code></li>
    </ul>
    <div class="btn-row">
      <a class="btn" href="{url_for('logs_baresip')}">baresip Log</a>
      <a class="btn" href="{url_for('services_overview')}">Service Uebersicht</a>
    </div>
  </div>
</div>
"""
    return render_page("Dashboard", "home", body)

# --- Login-Info Seite (nur Info, kein Edit) ---
@app.get("/auth-info")
@login_required
def auth_info():
    user = WEB_USER or "(nicht gesetzt)"
    service_file = "/etc/systemd/system/retrophone-web.service"
    body = f"""
<div class="card">
  <h1>Login / Authentifizierung</h1>
  <p class="subtle">Die Weboberflaeche nutzt ein Login-Formular. Die Zugangsdaten werden im Service-File gesetzt.</p>
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
    Aenderung: <code>sudo nano {html.escape(service_file)}</code><br>
    Danach: <code>sudo systemctl daemon-reload</code> und <code>sudo systemctl restart retrophone-web.service</code>.
  </p>
  <div class="btn-row">
    <a class="btn" href="{url_for('index')}">Zurueck zum Dashboard</a>
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
    Letzte Eintraege.{" Seite aktualisiert automatisch." if auto else " Auto-Refresh ist pausiert."}
  </p>
  <div class="tabs">
    <a class="tab active" href="{url_for('logs_phone', auto=('1' if auto else '0'))}">Phone</a>
    <a class="tab" href="{url_for('logs_ring', auto=('1' if auto else '0'))}">Ring</a>
    <a class="tab" href="{url_for('logs_baresip', auto=('1' if auto else '0'))}">baresip</a>
  </div>
  <pre>{data}</pre>
  <div class="btn-row">
    <a class="btn" href="{toggle_url}">{toggle_label}</a>
    <a class="btn" href="{url_for('index')}">Zurueck zum Dashboard</a>
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
    Letzte Eintraege.{" Seite aktualisiert automatisch." if auto else " Auto-Refresh ist pausiert."}
  </p>
  <div class="tabs">
    <a class="tab" href="{url_for('logs_phone', auto=('1' if auto else '0'))}">Phone</a>
    <a class="tab active" href="{url_for('logs_ring', auto=('1' if auto else '0'))}">Ring</a>
    <a class="tab" href="{url_for('logs_baresip', auto=('1' if auto else '0'))}">baresip</a>
  </div>
  <pre>{data}</pre>
  <div class="btn-row">
    <a class="btn" href="{toggle_url}">{toggle_label}</a>
    <a class="btn" href="{url_for('index')}">Zurueck zum Dashboard</a>
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
    Ausgabe von journalctl fuer baresip.{" Seite aktualisiert automatisch." if auto else " Auto-Refresh ist pausiert."}
  </p>
  <div class="tabs">
    <a class="tab" href="{url_for('logs_phone', auto=('1' if auto else '0'))}">Phone</a>
    <a class="tab" href="{url_for('logs_ring', auto=('1' if auto else '0'))}">Ring</a>
    <a class="tab active" href="{url_for('logs_baresip', auto=('1' if auto else '0'))}">baresip</a>
  </div>
  <pre>{data}</pre>
  <div class="btn-row">
    <a class="btn" href="{toggle_url}">{toggle_label}</a>
    <a class="btn" href="{url_for('index')}">Zurueck zum Dashboard</a>
  </div>
</div>
"""
    return render_page("baresip Log", "logs", body, auto_refresh=auto_refresh)

# --- Account ---
@app.get("/account")
@login_required
def account_form():
    acc = parse_account(read_account_line())
    def esc(x): return html.escape(x or "")
    transports = ["udp", "tcp", "tls"]
    opts = "".join(
        f'<option value="{t}" {"selected" if (acc.get("transport") or "udp")==t else ""}>{t}</option>'
        for t in transports
    )
    body = f"""
<div class="card">
  <h1>SIP Account</h1>
  <p class="subtle">Konfiguration des baresip Accounts. Nach Aenderung baresip neu starten.</p>
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
      <a class="btn" href="{url_for('index')}">Abbrechen</a>
    </div>
    <p class="subtle" style="margin-top:8px;">Accounts Datei: <code>{html.escape(accounts_path())}</code></p>
  </form>
</div>
"""
    return render_page("SIP Account", "account", body)

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
    p = write_accounts_file(line)

    body = f"""
<div class="card">
  <h2>Gespeichert</h2>
  <p class="subtle">Accounts Datei aktualisiert.</p>
  <p><code>{html.escape(p)}</code></p>
  <pre>{html.escape(line)}</pre>
  <div class="btn-row">
    <a class="btn primary" href="{url_for('action_restart_baresip')}">baresip jetzt neu starten</a>
    <a class="btn" href="{url_for('account_form')}">Zurueck zum Account</a>
    <a class="btn" href="{url_for('index')}">Zurueck zum Dashboard</a>
  </div>
</div>
"""
    return render_page("Gespeichert", "account", body)

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
    <a class="btn" href="{url_for('account_form')}">Zurueck zum Account</a>
    <a class="btn" href="{url_for('index')}">Zurueck zum Dashboard</a>
  </div>
</div>
"""
    return render_page("Restart", "home", body)

# --- Service Uebersicht ---
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
    <a class="btn" href="{url_for('index')}">Zurueck zum Dashboard</a>
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
    <a class="btn" href="{url_for('services_overview')}">Zurueck zur Service Uebersicht</a>
    <a class="btn" href="{url_for('index')}">Zurueck zum Dashboard</a>
  </div>
</div>
"""
    return render_page("Service Restart", "services", body)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
