#!/usr/bin/env python3
"""Portal Hub — one web page to control and manage every Meta Portal in your house.

Run it on a machine on the same Wi-Fi as your Portals, open the page in a browser, and:
  - see all your Portals + live status, add them by USB bootstrap, manual IP, or LAN scan
  - see installed apps per device; install (any APK), uninstall, launch, force-stop, clear data
  - common ADB controls: screenshot, reboot, key events (Home/Back/Wake/Sleep), a shell box

Dependencies: Python 3.7+ standard library, and `adb` (Android platform-tools) on PATH.
No metavr, no pip installs, no node_modules. Set ADB=/path/to/adb to override.

  python3 server.py            # then open http://<this-machine-ip>:8080

SECURITY: this server is UNAUTHENTICATED and runs adb (including a shell + reboot) on your
behalf. Run it only on a trusted home LAN.
"""

import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ADB = os.environ.get("ADB", "adb")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))
ADB_PORT = 5555  # Portals (Android 9/10) have no wireless-pairing; classic tcpip on 5555

BASE = os.path.dirname(os.path.abspath(__file__))
DEVICES_FILE = os.path.join(BASE, "devices.json")
# Optional convenience: point DEBUG_APK at an APK you rebuild often to get a one-click
# "use latest debug build" checkbox in the install panel. Unset = just use the file picker.
DEBUG_APK = os.environ.get("DEBUG_APK", "")
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "portal-hub-uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Known Portal codenames (ro.product.device) for tagging LAN-scan finds.
PORTAL_CODENAMES = {"terry", "aloha", "ripcurrent", "kong", "rosie"}

IP_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
KEYS = {  # friendly button -> Android keycode name
    "home": "KEYCODE_HOME", "back": "KEYCODE_BACK", "wake": "KEYCODE_WAKEUP",
    "sleep": "KEYCODE_SLEEP", "menu": "KEYCODE_MENU", "appswitch": "KEYCODE_APP_SWITCH",
}
_lock = threading.Lock()


# ----------------------------------------------------------------- adb helpers

def valid_ip(ip):
    m = IP_RE.match(ip or "")
    return bool(m) and all(0 <= int(p) <= 255 for p in m.groups())


def adb(*args, timeout=60):
    """Run `adb <args>`; return (rc, stdout, stderr) as text. Never raises."""
    try:
        p = subprocess.run([ADB, *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError:
        return 127, "", "adb not found. Install Android platform-tools, or set ADB=/path/to/adb."
    except subprocess.TimeoutExpired:
        return 124, "", "adb timed out"


def adb_bytes(*args, timeout=30):
    """Run adb and return (rc, stdout_bytes, stderr_text) — for binary output like screencap."""
    try:
        p = subprocess.run([ADB, *args], capture_output=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr.decode(errors="replace").strip()
    except FileNotFoundError:
        return 127, b"", "adb not found"
    except subprocess.TimeoutExpired:
        return 124, b"", "adb timed out"


def serial(ip):
    return "%s:%d" % (ip, ADB_PORT)


def adb_states():
    _, out, _ = adb("devices")
    states = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            states[parts[0]] = parts[1]
    return states


def usb_serials():
    _, out, _ = adb("devices")
    return [p[0] for p in (l.split() for l in out.splitlines()[1:])
            if len(p) >= 2 and p[1] == "device" and ":" not in p[0]]


# --------------------------------------------------------------- device store

def load_devices():
    try:
        with open(DEVICES_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, ValueError):
        return []


def save_devices(devices):
    with _lock:
        tmp = DEVICES_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(devices, f, indent=2)
        os.replace(tmp, DEVICES_FILE)


def upsert_device(name, ip):
    devices = load_devices()
    for d in devices:
        if d["ip"] == ip:
            if name:
                d["name"] = name
            save_devices(devices)
            return
    devices.append({"name": name or ip, "ip": ip})
    save_devices(devices)


# ------------------------------------------------------------------- actions

def list_devices_with_state():
    states = adb_states()
    return [{"name": d["name"], "ip": d["ip"], "state": states.get(serial(d["ip"]), "disconnected")}
            for d in load_devices()]


def connect(ip):
    if not valid_ip(ip):
        return {"ok": False, "msg": "invalid IP"}
    _, out, err = adb("connect", serial(ip), timeout=20)
    msg = (out or err).strip()
    ok = "connected" in msg.lower() or adb_states().get(serial(ip)) == "device"
    return {"ok": ok, "msg": msg or ("connected" if ok else "no response")}


def bootstrap_usb():
    """For each USB device: read Wi-Fi IP, flip adbd to tcpip:5555, connect, and save it."""
    results = []
    for s in usb_serials():
        _, out, _ = adb("-s", s, "shell", "ip", "-f", "inet", "addr", "show", "wlan0", timeout=20)
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        ip = m.group(1) if m else None
        _, model, _ = adb("-s", s, "shell", "getprop", "ro.product.model", timeout=15)
        model = model.strip() or "Portal"
        if not ip:
            results.append({"ok": False, "msg": "%s: no wlan0 IP — is it on Wi-Fi?" % s})
            continue
        adb("-s", s, "tcpip", str(ADB_PORT), timeout=20)
        c = connect(ip)
        upsert_device(model, ip)
        results.append({"ok": c["ok"], "msg": "added %s (%s) — %s" % (model, ip, c["msg"])})
    if not results:
        results.append({"ok": False, "msg": "No USB devices. Plug a Portal in and enable ADB."})
    return results


def scan_lan():
    """Find Portals on the local /24: TCP-probe :5555, adb-connect responders, tag Portals."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local = s.getsockname()[0]
        s.close()
    except OSError:
        return {"error": "could not determine local subnet"}
    base = local.rsplit(".", 1)[0]

    def probe(n):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as so:
            so.settimeout(0.3)
            try:
                so.connect(("%s.%d" % (base, n), ADB_PORT))
                return "%s.%d" % (base, n)
            except OSError:
                return None

    with ThreadPoolExecutor(max_workers=64) as ex:
        responders = [r for r in ex.map(probe, range(1, 255)) if r]

    found = []
    for ip in responders:
        adb("connect", serial(ip), timeout=10)
        rc, model, _ = adb("-s", serial(ip), "shell", "getprop", "ro.product.model", timeout=10)
        _, dev, _ = adb("-s", serial(ip), "shell", "getprop", "ro.product.device", timeout=10)
        if rc != 0:
            continue  # answered on 5555 but adb handshake failed; skip
        portal = ("portal" in (model + dev).lower()) or dev.strip() in PORTAL_CODENAMES
        name = model.strip() or "Device"
        upsert_device(name, ip)
        found.append({"ip": ip, "name": name, "portal": portal})
    return {"found": found, "subnet": base + ".0/24"}


def device_info(ip):
    s = serial(ip)
    cmd = ("echo M:$(getprop ro.product.model); echo R:$(getprop ro.build.version.release); "
           "echo S:$(getprop ro.build.version.sdk); "
           "echo B:$(dumpsys battery 2>/dev/null | sed -n 's/.*level: //p' | head -1)")
    _, out, _ = adb("-s", s, "shell", cmd, timeout=20)
    info = {"ip": ip, "serial": s}
    keymap = {"M": "model", "R": "android", "S": "sdk", "B": "battery"}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k in keymap:
                info[keymap[k]] = v.strip()
    _, out2, _ = adb("-s", s, "shell", "dumpsys window | grep -m1 mCurrentFocus", timeout=15)
    m = re.search(r"u0\s+(\S+)/", out2)
    info["focus"] = m.group(1) if m else ""
    return info


def list_apps(ip, system=False):
    s = serial(ip)
    if system:
        _, out, _ = adb("-s", s, "shell", "pm list packages -s", timeout=30)
        pkgs = sorted(l.split("package:", 1)[1].strip() for l in out.splitlines() if l.startswith("package:"))
        return [{"pkg": p, "version": ""} for p in pkgs]
    # one round trip: emit "pkg|versionName" for each third-party app
    cmd = ("for p in $(pm list packages -3 | sed 's/package://'); do "
           "v=$(dumpsys package \"$p\" 2>/dev/null | grep -m1 versionName | sed 's/.*versionName=//'); "
           "echo \"$p|$v\"; done")
    _, out, _ = adb("-s", s, "shell", cmd, timeout=60)
    apps = []
    for line in out.splitlines():
        if "|" in line:
            p, v = line.split("|", 1)
            apps.append({"pkg": p.strip(), "version": v.strip()})
    return sorted(apps, key=lambda a: a["pkg"])


def install(apk_path, targets):
    results = []
    if not (apk_path and os.path.isfile(apk_path)):
        return [{"ip": ip, "ok": False, "msg": "APK not found on server"} for ip in targets]
    for ip in targets:
        if not valid_ip(ip):
            results.append({"ip": ip, "ok": False, "msg": "invalid IP"})
            continue
        adb("connect", serial(ip), timeout=20)
        rc, out, err = adb("-s", serial(ip), "install", "-r", apk_path, timeout=300)
        blob = (out + "\n" + err).strip()
        ok = rc == 0 and "Success" in blob
        if ok:
            msg = "Success"
        else:
            fail = [ln for ln in blob.splitlines() if "Failure" in ln or "error" in ln.lower()]
            msg = fail[-1] if fail else (blob.splitlines()[-1] if blob else "exit %d" % rc)
        results.append({"ip": ip, "ok": ok, "msg": msg})
    return results


def app_action(ip, pkg, action):
    if not (valid_ip(ip) and re.match(r"^[A-Za-z0-9_.]+$", pkg or "")):
        return {"ok": False, "msg": "bad device/package"}
    s = serial(ip)
    if action == "uninstall":
        rc, out, err = adb("-s", s, "uninstall", pkg, timeout=60)
    elif action == "launch":
        rc, out, err = adb("-s", s, "shell", "monkey", "-p", pkg, "-c",
                           "android.intent.category.LAUNCHER", "1", timeout=20)
        ok = rc == 0 and "Events injected: 1" in (out + err)
        return {"ok": ok, "msg": "launched" if ok else "couldn't launch (no launchable activity?)"}
    elif action == "stop":
        rc, out, err = adb("-s", s, "shell", "am", "force-stop", pkg, timeout=20)
    elif action == "clear":
        rc, out, err = adb("-s", s, "shell", "pm", "clear", pkg, timeout=30)
    else:
        return {"ok": False, "msg": "unknown action"}
    blob = (out + " " + err).strip()
    ok = rc == 0 and "Failure" not in blob and "Error" not in blob
    return {"ok": ok, "msg": blob or ("done" if ok else "exit %d" % rc)}


# ---------------------------------------------------------------- HTTP server

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self):
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode())
        except ValueError:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        ip = (q.get("ip", [""])[0]).strip()
        if u.path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif u.path == "/api/devices":
            self._send(200, {"devices": list_devices_with_state(),
                             "debugApk": DEBUG_APK if os.path.isfile(DEBUG_APK) else None})
        elif u.path == "/api/info":
            self._send(200, device_info(ip))
        elif u.path == "/api/apps":
            self._send(200, {"apps": list_apps(ip, q.get("system", ["0"])[0] == "1")})
        elif u.path == "/api/screenshot":
            rc, png, err = adb_bytes("-s", serial(ip), "exec-out", "screencap", "-p", timeout=30)
            if rc == 0 and png[:8] == b"\x89PNG\r\n\x1a\n":
                self._send(200, png, "image/png")
            else:
                self._send(502, {"ok": False, "msg": err or "screencap failed"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/add":
            b = self._json()
            ip = (b.get("ip") or "").strip()
            if not valid_ip(ip):
                return self._send(400, {"ok": False, "msg": "invalid IP"})
            upsert_device((b.get("name") or "").strip(), ip)
            self._send(200, {"ok": True, **connect(ip)})
        elif path == "/api/remove":
            ip = (self._json().get("ip") or "").strip()
            save_devices([d for d in load_devices() if d["ip"] != ip])
            self._send(200, {"ok": True})
        elif path == "/api/connect":
            self._send(200, connect((self._json().get("ip") or "").strip()))
        elif path == "/api/connect-all":
            self._send(200, [dict(ip=d["ip"], **connect(d["ip"])) for d in load_devices()])
        elif path == "/api/disconnect":
            ip = (self._json().get("ip") or "").strip()
            adb("disconnect", serial(ip))
            self._send(200, {"ok": True})
        elif path == "/api/bootstrap":
            self._send(200, bootstrap_usb())
        elif path == "/api/scan":
            self._send(200, scan_lan())
        elif path == "/api/upload":
            n = int(self.headers.get("Content-Length", 0))
            name = os.path.basename(self.headers.get("X-Filename", "upload.apk")) or "upload.apk"
            if not name.lower().endswith(".apk"):
                name += ".apk"
            dest = os.path.join(UPLOAD_DIR, uuid.uuid4().hex + "-" + re.sub(r"[^A-Za-z0-9._-]", "_", name))
            with open(dest, "wb") as f:
                remaining = n
                while remaining > 0:
                    chunk = self.rfile.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            self._send(200, {"ok": True, "path": dest, "name": name})
        elif path == "/api/install":
            b = self._json()
            apk = b.get("path") or (DEBUG_APK if b.get("useDebug") else None)
            targets = [t for t in (b.get("targets") or []) if t]
            if not targets:
                return self._send(400, {"ok": False, "msg": "no targets selected"})
            self._send(200, {"ok": True, "results": install(apk, targets)})
        elif path == "/api/app":
            b = self._json()
            self._send(200, app_action((b.get("ip") or "").strip(), (b.get("pkg") or "").strip(),
                                       b.get("action") or ""))
        elif path == "/api/key":
            b = self._json()
            ip = (b.get("ip") or "").strip()
            key = KEYS.get(b.get("key") or "")
            if not (valid_ip(ip) and key):
                return self._send(400, {"ok": False, "msg": "bad device/key"})
            rc, out, err = adb("-s", serial(ip), "shell", "input", "keyevent", key, timeout=15)
            self._send(200, {"ok": rc == 0, "msg": (out or err or key)})
        elif path == "/api/reboot":
            ip = (self._json().get("ip") or "").strip()
            if not valid_ip(ip):
                return self._send(400, {"ok": False, "msg": "invalid IP"})
            adb("-s", serial(ip), "reboot", timeout=20)
            self._send(200, {"ok": True, "msg": "reboot sent (device will drop off Wi-Fi adb until re-bootstrapped)"})
        elif path == "/api/shell":
            b = self._json()
            ip = (b.get("ip") or "").strip()
            cmd = b.get("cmd") or ""
            if not (valid_ip(ip) and cmd.strip()):
                return self._send(400, {"ok": False, "msg": "device + command required"})
            rc, out, err = adb("-s", serial(ip), "shell", cmd, timeout=30)
            blob = (out + ("\n" + err if err else "")).strip()
            self._send(200, {"ok": rc == 0, "out": blob[:20000] or "(no output)"})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        return


PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portal Hub</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; background:#121419; color:#e7e9ee;
    font:15px/1.5 -apple-system, system-ui, "Segoe UI", Roboto, sans-serif; }
  header { padding:16px 22px; border-bottom:1px solid #262a33; display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  header h1 { margin:0; font-size:19px; } .warn { color:#f0b86c; font-size:12px; }
  .layout { display:grid; grid-template-columns:320px 1fr; gap:18px; padding:18px 22px; align-items:start; }
  .card { background:#1a1d24; border:1px solid #262a33; border-radius:12px; padding:16px; }
  h2 { margin:0 0 12px; font-size:13px; color:#c7ccd6; text-transform:uppercase; letter-spacing:.04em; }
  button { font:inherit; background:#2563eb; color:#fff; border:0; border-radius:8px; padding:8px 13px; cursor:pointer; }
  button:hover{ background:#1d4ed8; } button.ghost{ background:#2a2e37; } button.ghost:hover{ background:#343a45; }
  button.sm{ padding:4px 9px; font-size:12px; } button.danger{ background:#b91c1c; } button.danger:hover{ background:#991b1b; }
  button:disabled{ opacity:.5; cursor:default; }
  input[type=text]{ background:#121419; border:1px solid #353a45; color:#e7e9ee; border-radius:8px; padding:8px 10px; }
  .dev { padding:10px; border:1px solid #262a33; border-radius:10px; margin-bottom:9px; cursor:pointer; }
  .dev.sel { border-color:#2563eb; background:#16223c; }
  .dev .top { display:flex; align-items:center; gap:8px; }
  .dot{ width:9px;height:9px;border-radius:50%; display:inline-block; }
  .device{ background:#4ade80; } .offline,.disconnected{ background:#6b7280; } .unauthorized{ background:#f59e0b; }
  .meta{ color:#9aa0ae; font-size:12px; margin-top:3px; }
  .row{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .muted{ color:#9aa0ae; font-size:13px; } .grow{ flex:1; min-width:120px; }
  .tabs{ display:flex; gap:6px; margin-bottom:14px; }
  .tab{ background:#222631; color:#c7ccd6; } .tab.on{ background:#2563eb; color:#fff; }
  table{ width:100%; border-collapse:collapse; } th,td{ text-align:left; padding:7px 6px; border-bottom:1px solid #232730; font-size:13px; }
  th{ color:#8b91a0; font-size:11px; }
  .res{ font-size:13px; padding:6px 10px; border-radius:8px; margin-top:7px; }
  .res.ok{ background:#14361f; color:#86efac; } .res.bad{ background:#3a1b1b; color:#fca5a5; }
  pre{ background:#0e1014; border:1px solid #262a33; border-radius:8px; padding:10px; overflow:auto; max-height:320px; font-size:12px; white-space:pre-wrap; }
  img.shot{ max-width:100%; border:1px solid #262a33; border-radius:10px; margin-top:10px; }
  code{ background:#0e1014; padding:1px 6px; border-radius:5px; }
</style></head>
<body>
<header>
  <h1>🛰️ Portal Hub</h1>
  <span class="muted">control &amp; manage every Portal in the house</span>
  <span class="warn">⚠ unauthenticated — trusted LAN only</span>
</header>
<div class="layout">
  <div class="card">
    <h2>Portals</h2>
    <div id="devs"><div class="muted">Loading…</div></div>
    <div class="row" style="margin-top:12px">
      <button class="ghost sm" id="connAll">Connect all</button>
      <button class="ghost sm" id="scan">Scan LAN</button>
      <button class="ghost sm" id="boot">＋ USB</button>
    </div>
    <div class="row" style="margin-top:10px">
      <input type="text" id="nm" placeholder="Name" class="grow">
      <input type="text" id="ip" placeholder="192.168.1.50" style="width:130px">
      <button class="sm" id="addBtn">Add</button>
    </div>
    <div id="devMsg"></div>
  </div>

  <div class="card" id="panel">
    <div class="muted">Select a Portal on the left to manage it.</div>
  </div>
</div>
<script>
const $ = s => document.querySelector(s);
const api = (p, body, method) => fetch(p, {method: method || (body ? 'POST' : 'GET'),
  headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined}).then(r=>r.json());
const esc = s => (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

let devices = [], sel = null, tab = 'apps', debugApk = null, showSys = false;

async function loadDevices() {
  const d = await api('/api/devices'); devices = d.devices; debugApk = d.debugApk;
  if (sel && !devices.find(x=>x.ip===sel)) sel = null;
  renderDevs();
  if (sel) renderPanel();
}
function renderDevs() {
  const el = $('#devs');
  if (!devices.length) { el.innerHTML = '<div class="muted">No Portals yet. Use Scan LAN, ＋USB, or add an IP.</div>'; return; }
  el.innerHTML = devices.map(x => `
    <div class="dev ${x.ip===sel?'sel':''}" data-ip="${x.ip}" onclick="pick('${x.ip}')">
      <div class="top">
        <input type="checkbox" class="pick" value="${x.ip}" ${x.state==='device'?'checked':''} onclick="event.stopPropagation()">
        <span class="dot ${x.state}"></span><b>${esc(x.name)}</b>
      </div>
      <div class="meta">${x.ip} · <span class="st">${x.state}</span>
        <a href="#" onclick="event.stopPropagation();rm('${x.ip}');return false" style="color:#7f8694;float:right">remove</a></div>
    </div>`).join('');
}
window.pick = ip => { sel = ip; renderDevs(); renderPanel(); };
window.rm = async ip => { await api('/api/remove', {ip}); if (sel===ip) sel=null; loadDevices(); };

$('#addBtn').onclick = async () => { const ip=$('#ip').value.trim(); if(!ip) return;
  const r = await api('/api/add', {name:$('#nm').value.trim(), ip}); if(!r.ok&&r.msg) note(r.msg,false);
  $('#ip').value=''; $('#nm').value=''; loadDevices(); };
$('#connAll').onclick = async () => { await api('/api/connect-all', {}); loadDevices(); };
$('#boot').onclick = async () => { note('USB bootstrap working…', true);
  const r = await api('/api/bootstrap', {}); $('#devMsg').innerHTML = r.map(x=>`<div class="res ${x.ok?'ok':'bad'}">${esc(x.msg)}</div>`).join(''); loadDevices(); };
$('#scan').onclick = async () => { note('Scanning the LAN for Portals on :5555…', true);
  const r = await api('/api/scan', {});
  if (r.error) return note(r.error, false);
  $('#devMsg').innerHTML = `<div class="res ok">Scanned ${esc(r.subnet)} — found ${r.found.length}</div>` +
    r.found.map(f=>`<div class="muted">${f.portal?'🛰️':'📱'} ${esc(f.name)} (${f.ip})</div>`).join(''); loadDevices(); };
function note(msg, ok){ $('#devMsg').innerHTML = `<div class="res ${ok?'ok':'bad'}">${esc(msg)}</div>`; }

function renderPanel() {
  const d = devices.find(x=>x.ip===sel); if(!d){ $('#panel').innerHTML='<div class="muted">Select a Portal.</div>'; return; }
  $('#panel').innerHTML = `
    <div class="row" style="justify-content:space-between">
      <h2 style="margin:0">${esc(d.name)} <span class="muted">· ${d.ip} · <span id="panelState">${d.state}</span></span></h2>
      <div class="row">
        <button class="tab ${tab==='apps'?'on':''}" onclick="setTab('apps')">Apps</button>
        <button class="tab ${tab==='controls'?'on':''}" onclick="setTab('controls')">Controls</button>
        <button class="tab ${tab==='info'?'on':''}" onclick="setTab('info')">Info</button>
      </div>
    </div>
    <div id="tabBody" style="margin-top:14px"></div>`;
  if (tab==='apps') renderApps(); else if (tab==='controls') renderControls(); else renderInfo();
}
window.setTab = t => { tab = t; renderPanel(); };

function targets(){ const c=[...document.querySelectorAll('.pick:checked')].map(x=>x.value); return c.length?c:[sel]; }

function renderApps() {
  const body = $('#tabBody');
  body.innerHTML = `
    <div class="card" style="background:#15181f">
      <h2>Install an app</h2>
      <div class="row"><input type="file" id="apk" accept=".apk">
        ${debugApk?`<label class="muted"><input type="checkbox" id="useDebug"> use latest debug build</label>`:''}</div>
      <div class="row" style="margin-top:10px">
        <button id="instBtn">Install</button>
        <span class="muted">→ to <b id="tcount"></b> (the ticked Portals, else this one)</span></div>
      <div id="instRes"></div>
    </div>
    <div class="row" style="margin:16px 0 8px"><h2 style="margin:0">Installed apps</h2>
      <label class="muted" style="margin-left:auto"><input type="checkbox" id="sys" ${showSys?'checked':''}> show system</label>
      <button class="ghost sm" id="reapps">Refresh</button></div>
    <div id="appList"><div class="muted">Loading…</div></div>`;
  $('#tcount').textContent = targets().length + ' device(s)';
  document.querySelectorAll('.pick').forEach(c=>c.addEventListener('change',()=>{ const t=$('#tcount'); if(t) t.textContent=targets().length+' device(s)';}));
  $('#sys').onchange = e => { showSys = e.target.checked; loadApps(); };
  $('#reapps').onclick = loadApps;
  $('#instBtn').onclick = doInstall;
  loadApps();
}
async function loadApps() {
  const el = $('#appList'); el.innerHTML = '<div class="muted">Loading apps…</div>';
  const r = await api('/api/apps?ip='+sel+'&system='+(showSys?1:0));
  if (!r.apps || !r.apps.length) { el.innerHTML = '<div class="muted">No apps found (device offline?).</div>'; return; }
  el.innerHTML = `<table><thead><tr><th>Package</th><th>Version</th><th></th></tr></thead><tbody>` +
    r.apps.map(a=>`<tr><td><code>${esc(a.pkg)}</code></td><td class="muted">${esc(a.version)}</td>
      <td class="row" style="justify-content:flex-end">
        <button class="ghost sm" onclick="appAct('${a.pkg}','launch')">Launch</button>
        <button class="ghost sm" onclick="appAct('${a.pkg}','stop')">Stop</button>
        <button class="ghost sm" onclick="appAct('${a.pkg}','clear')">Clear</button>
        <button class="danger sm" onclick="appAct('${a.pkg}','uninstall')">Uninstall</button></td></tr>`).join('') +
    `</tbody></table>`;
}
window.appAct = async (pkg, action) => {
  if (action==='uninstall' && !confirm('Uninstall '+pkg+' from this Portal?')) return;
  if (action==='clear' && !confirm('Clear all data for '+pkg+'?')) return;
  const r = await api('/api/app', {ip:sel, pkg, action});
  note((r.ok?'✓ ':'✗ ')+action+' '+pkg+' — '+(r.msg||''), r.ok);
  if (action==='uninstall') loadApps();
};
async function doInstall() {
  const t = targets(); const btn=$('#instBtn'); btn.disabled=true; const out=$('#instRes');
  let path=null, useDebug=false; const file=$('#apk').files[0];
  if (file) { out.innerHTML='<div class="muted">Uploading '+esc(file.name)+'…</div>';
    const up=await fetch('/api/upload',{method:'POST',headers:{'X-Filename':file.name},body:file}).then(r=>r.json());
    if(!up.ok){ out.innerHTML='<div class="res bad">upload failed</div>'; btn.disabled=false; return;} path=up.path;
  } else if (debugApk && $('#useDebug') && $('#useDebug').checked) { useDebug=true; }
  else { out.innerHTML='<div class="res bad">Pick an APK (or tick debug build).</div>'; btn.disabled=false; return; }
  out.innerHTML='<div class="muted">Installing to '+t.length+' device(s)…</div>';
  const r = await api('/api/install', {path, useDebug, targets:t});
  out.innerHTML = (r.results||[]).map(x=>`<div class="res ${x.ok?'ok':'bad'}"><b>${x.ip}</b> — ${esc(x.msg)}</div>`).join('');
  btn.disabled=false; loadApps();
}

function renderControls() {
  $('#tabBody').innerHTML = `
    <div class="row">
      <button class="ghost" onclick="shot()">📷 Screenshot</button>
      <button class="ghost" onclick="key('home')">Home</button>
      <button class="ghost" onclick="key('back')">Back</button>
      <button class="ghost" onclick="key('wake')">Wake</button>
      <button class="ghost" onclick="key('sleep')">Sleep</button>
      <button class="danger" onclick="reboot()">Reboot</button>
    </div>
    <div id="shotWrap"></div>
    <div style="margin-top:18px"><h2>Shell</h2>
      <div class="row"><input type="text" id="cmd" class="grow" placeholder="e.g. dumpsys battery  /  settings get secure screensaver_components"
        onkeydown="if(event.key==='Enter')runShell()"><button onclick="runShell()">Run</button></div>
      <pre id="shOut" style="margin-top:10px">adb -s ${sel}:5555 shell …</pre></div>`;
}
window.shot = async () => { const w=$('#shotWrap'); w.innerHTML='<div class="muted" style="margin-top:10px">Capturing…</div>';
  const r = await fetch('/api/screenshot?ip='+sel); if(!r.ok){ w.innerHTML='<div class="res bad">screenshot failed</div>'; return; }
  const b = await r.blob(); w.innerHTML = '<img class="shot" src="'+URL.createObjectURL(b)+'">'; };
window.key = async k => { const r = await api('/api/key', {ip:sel, key:k}); if(!r.ok) note('key '+k+' failed', false); };
window.reboot = async () => { if(!confirm('Reboot this Portal? It will drop off Wi-Fi adb until you re-bootstrap it.')) return;
  const r = await api('/api/reboot', {ip:sel}); note(r.msg||'reboot sent', true); };
window.runShell = async () => { const cmd=$('#cmd').value.trim(); if(!cmd) return;
  $('#shOut').textContent='running…'; const r=await api('/api/shell',{ip:sel,cmd}); $('#shOut').textContent=r.out||r.msg||''; };

async function renderInfo() {
  $('#tabBody').innerHTML = '<div class="muted">Loading device info…</div>';
  const i = await api('/api/info?ip='+sel);
  $('#tabBody').innerHTML = `<table>
    <tr><th>Model</th><td>${esc(i.model||'—')}</td></tr>
    <tr><th>Android</th><td>${esc(i.android||'—')} (API ${esc(i.sdk||'—')})</td></tr>
    <tr><th>Battery</th><td>${esc(i.battery||'—')}%</td></tr>
    <tr><th>Foreground</th><td><code>${esc(i.focus||'—')}</code></td></tr>
    <tr><th>adb serial</th><td><code>${esc(i.serial||'')}</code></td></tr></table>`;
}

// Background refresh: patch device status IN PLACE so the selected panel / app list
// (and your target checkboxes) are never torn down. Only a membership change re-renders.
async function poll() {
  const d = await api('/api/devices'); debugApk = d.debugApk;
  const sameSet = d.devices.length === devices.length && d.devices.every((x,i)=>devices[i] && devices[i].ip===x.ip);
  devices = d.devices;
  if (sel && !devices.find(x=>x.ip===sel)) { sel=null; renderDevs(); renderPanel(); return; }
  if (!sameSet) { renderDevs(); if (sel) renderPanel(); return; }
  devices.forEach(x => {
    const c = document.querySelector('.dev[data-ip="'+x.ip+'"]'); if (!c) return;
    const dot = c.querySelector('.dot'); if (dot) dot.className = 'dot '+x.state;
    const st = c.querySelector('.st'); if (st) st.textContent = x.state;
  });
  const ps = document.getElementById('panelState');
  if (ps && sel) { const sd = devices.find(z=>z.ip===sel); if (sd) ps.textContent = sd.state; }
}
loadDevices();
setInterval(poll, 8000);
</script>
</body></html>
"""


def main():
    print("Portal Hub")
    print("  adb:     %s" % ADB)
    print("  serving: http://%s:%d  (open from any machine on the LAN)" % (HOST, PORT))
    print("  devices: %s" % DEVICES_FILE)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
