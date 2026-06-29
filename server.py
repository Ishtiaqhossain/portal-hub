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

import glob
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import urllib.request
import uuid
import zipfile
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
# Per-package update sources (any app -> where to fetch its candidate APK from).
SOURCES_FILE = os.path.join(BASE, "sources.json")
DL_DIR = os.path.join(tempfile.gettempdir(), "portal-hub-downloads")
os.makedirs(DL_DIR, exist_ok=True)

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


# ------------------------------------------------------------- app updates
# "Is an update available?" is decided by comparing versionCode (the integer the OS
# itself orders by, and what `install -r` enforces) of a candidate APK against what's
# installed on each Portal. Nothing is app-specific: any package can have a source.

def _axml_strings(data, off):
    str_count, _style, flags, str_start, _ss = struct.unpack_from("<IIIII", data, off + 8)
    utf8 = (flags & (1 << 8)) != 0
    offs, base, out = off + 28, off + str_start, []
    for i in range(str_count):
        p = base + struct.unpack_from("<I", data, offs + i * 4)[0]
        if utf8:
            cl = data[p]; p += 1
            if cl & 0x80:
                p += 1
            bl = data[p]; p += 1
            if bl & 0x80:
                bl = ((bl & 0x7f) << 8) | data[p]; p += 1
            out.append(data[p:p + bl].decode("utf-8", "replace"))
        else:
            cl = struct.unpack_from("<H", data, p)[0]; p += 2
            if cl & 0x8000:
                cl = ((cl & 0x7fff) << 16) | struct.unpack_from("<H", data, p)[0]; p += 2
            out.append(data[p:p + cl * 2].decode("utf-16-le", "replace"))
    return out


def apk_version(path):
    """Read {package, versionCode:int, versionName} from an APK's binary AndroidManifest.xml
    using only the stdlib (zipfile + a minimal AXML parser). Returns None on failure."""
    try:
        with zipfile.ZipFile(path) as z:
            data = z.read("AndroidManifest.xml")
        off, strings, res = 8, None, {}
        while off + 8 <= len(data):
            ctyp, _h, csize = struct.unpack_from("<HHI", data, off)
            if csize <= 0:
                break
            if ctyp == 0x0001:  # string pool
                strings = _axml_strings(data, off)
            elif ctyp == 0x0102 and strings is not None:  # START_TAG
                name_idx = struct.unpack_from("<i", data, off + 20)[0]
                attr_start = struct.unpack_from("<H", data, off + 24)[0]
                attr_count = struct.unpack_from("<H", data, off + 28)[0]
                if 0 <= name_idx < len(strings) and strings[name_idx] == "manifest":
                    ab = off + 16 + attr_start
                    for i in range(attr_count):
                        a = ab + i * 20
                        an = struct.unpack_from("<i", data, a + 4)[0]
                        araw = struct.unpack_from("<i", data, a + 8)[0]
                        adata = struct.unpack_from("<I", data, a + 16)[0]
                        nm = strings[an] if 0 <= an < len(strings) else ""
                        if nm == "versionCode":
                            res["versionCode"] = adata
                        elif nm == "versionName":
                            res["versionName"] = strings[araw] if 0 <= araw < len(strings) else str(adata)
                        elif nm == "package":
                            res["package"] = strings[araw] if 0 <= araw < len(strings) else ""
                    break
            off += csize
        if "package" in res and "versionCode" in res:
            res.setdefault("versionName", "")
            return res
    except Exception:
        pass
    return None


# Signer pre-check: `install -r` is rejected (INSTALL_FAILED_UPDATE_INCOMPATIBLE) if the candidate
# is signed with a different key than what's installed. We compare SHA-256 cert digests via
# `apksigner` (from the Android SDK). If apksigner isn't found, the check degrades to "unknown".
_apksigner = None
_signer_cache = {}
_inst_signer_cache = {}


def apksigner_path():
    global _apksigner
    if _apksigner is None:
        cand = os.environ.get("APKSIGNER") or shutil.which("apksigner")
        if not (cand and os.path.isfile(cand)):
            roots = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
                     os.path.expanduser("~/Library/Android/sdk"), os.path.expanduser("~/Android/Sdk")]
            hits = []
            for r in roots:
                if r:
                    hits += glob.glob(os.path.join(r, "build-tools", "*", "apksigner"))
            cand = sorted(hits)[-1] if hits else ""
        _apksigner = cand or ""
    return _apksigner or None


def apk_signer(path):
    """SHA-256 of the APK's signing certificate (first signer), or None if unknown."""
    if not (path and os.path.isfile(path)):
        return None
    tool = apksigner_path()
    if not tool:
        return None
    key = (os.path.abspath(path), os.path.getmtime(path))
    if key in _signer_cache:
        return _signer_cache[key]
    sha = None
    try:
        p = subprocess.run([tool, "verify", "--print-certs", path], capture_output=True, text=True, timeout=60)
        m = re.search(r"certificate SHA-256 digest:\s*([0-9a-fA-F]+)", p.stdout)
        sha = m.group(1).lower() if m else None
    except Exception:
        sha = None
    _signer_cache[key] = sha
    return sha


def installed_signer(ip, pkg, code):
    """SHA-256 signer of the app installed on a device (pulls its base.apk once, cached)."""
    if not apksigner_path():
        return None
    key = (ip, pkg, code)
    if key in _inst_signer_cache:
        return _inst_signer_cache[key]
    _, out, _ = adb("-s", serial(ip), "shell", "pm", "path", pkg, timeout=20)
    dev_apk = next((l.split("package:", 1)[1].strip() for l in out.splitlines() if l.startswith("package:")), "")
    sha = None
    if dev_apk:
        local = os.path.join(DL_DIR, "installed-" + hashlib.sha1(("%s|%s|%s" % key).encode()).hexdigest()[:12] + ".apk")
        rc, _o, _e = adb("-s", serial(ip), "pull", dev_apk, local, timeout=180)
        if rc == 0:
            sha = apk_signer(local)
        try:
            os.remove(local)
        except OSError:
            pass
    _inst_signer_cache[key] = sha
    return sha


def signer_status(candidate_sha, installed_sha):
    if candidate_sha and installed_sha:
        return "ok" if candidate_sha == installed_sha else "mismatch"
    return "unknown"


# App icons: resolve the launcher icon's path with the SDK's `aapt`/`aapt2` (which works even for
# R8-shrunk APKs where the file is renamed), then extract it from the APK zip. Degrades to no icon
# if aapt isn't found and the icon isn't at a guessable path. Pulls the device's base.apk once,
# caches the (tiny) extracted bytes by package.
_aapt = None
_icon_cache = {}
_ICON_DENSITY = {"xxxhdpi": 6, "xxhdpi": 5, "xhdpi": 4, "hdpi": 3, "tvdpi": 2, "mdpi": 1}


def aapt_path():
    global _aapt
    if _aapt is None:
        cand = ""
        for name in ("aapt2", "aapt"):
            cand = shutil.which(name) or ""
            if cand:
                break
        if not cand:
            hits = []
            for r in [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
                      os.path.expanduser("~/Library/Android/sdk"), os.path.expanduser("~/Android/Sdk")]:
                if r:
                    hits += glob.glob(os.path.join(r, "build-tools", "*", "aapt2"))
            cand = sorted(hits)[-1] if hits else ""
        _aapt = cand or ""
    return _aapt or None


def _aapt_icon_entry(apk):
    tool = aapt_path()
    if not tool:
        return None
    try:
        out = subprocess.run([tool, "dump", "badging", apk], capture_output=True, text=True, timeout=60).stdout
        best = (-1, None)
        for m in re.finditer(r"application-icon-(\d+):'([^']+)'", out):
            path = m.group(2)
            if path.lower().endswith((".png", ".webp")) and int(m.group(1)) > best[0]:
                best = (int(m.group(1)), path)
        if best[1]:
            return best[1]
        m = re.search(r"application:\s+label='[^']*'\s+icon='([^']+)'", out)
        if m and m.group(1).lower().endswith((".png", ".webp")):
            return m.group(1)
    except Exception:
        pass
    return None


def _heuristic_icon_entry(z):
    best = (-1, None)
    for n in z.namelist():
        ln = n.lower()
        if ln.endswith((".png", ".webp")) and "ic_launcher" in ln and "round" not in ln:
            score = max((v for k, v in _ICON_DENSITY.items() if k in ln), default=0)
            if score > best[0]:
                best = (score, n)
    return best[1]


def extract_icon(apk):
    try:
        with zipfile.ZipFile(apk) as z:
            entry = _aapt_icon_entry(apk) or _heuristic_icon_entry(z)
            if not entry or entry not in z.namelist():
                return None, None
            ct = "image/webp" if entry.lower().endswith(".webp") else "image/png"
            return z.read(entry), ct
    except Exception:
        return None, None


def app_icon(ip, pkg):
    """(bytes, content_type) of an installed app's launcher icon, or (None, None). Cached by package."""
    if pkg in _icon_cache:
        return _icon_cache[pkg]
    out = (None, None)
    _, o, _ = adb("-s", serial(ip), "shell", "pm", "path", pkg, timeout=20)
    dev = next((l.split("package:", 1)[1].strip() for l in o.splitlines() if l.startswith("package:")), "")
    if dev:
        _, sz, _ = adb("-s", serial(ip), "shell", "stat", "-c", "%s", dev, timeout=15)
        try:
            if int(sz.strip()) > 200 * 1024 * 1024:  # don't pull a giant APK just for an icon
                _icon_cache[pkg] = out
                return out
        except ValueError:
            pass
        local = os.path.join(DL_DIR, "icon-" + hashlib.sha1((ip + pkg).encode()).hexdigest()[:12] + ".apk")
        rc, _a, _b = adb("-s", serial(ip), "pull", dev, local, timeout=180)
        if rc == 0:
            out = extract_icon(local)
        try:
            os.remove(local)
        except OSError:
            pass
    _icon_cache[pkg] = out
    return out


def load_sources():
    try:
        with open(SOURCES_FILE) as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def save_sources(s):
    with _lock:
        tmp = SOURCES_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f, indent=2)
        os.replace(tmp, SOURCES_FILE)


def _http_get(url, token=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "portal-hub"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _download(url, token=None):
    dest = os.path.join(DL_DIR, hashlib.sha1(url.encode()).hexdigest()[:16] + ".apk")
    if not os.path.isfile(dest):
        with open(dest, "wb") as f:
            f.write(_http_get(url, token, timeout=180))
    return dest


def github_latest_apk(repo, token=None):
    """'owner/name' -> download URL of the first .apk asset on the latest release."""
    rel = json.loads(_http_get("https://api.github.com/repos/%s/releases/latest" % repo.strip("/"), token))
    for a in rel.get("assets", []):
        if a.get("name", "").lower().endswith(".apk"):
            return a["browser_download_url"]
    raise ValueError("latest release has no .apk asset")


def resolve_candidate(src):
    """An update source -> (apk_path, error). Downloads URL/GitHub sources (cached)."""
    try:
        t = src.get("type")
        if t == "path":
            p = src.get("value", "")
            return (p, None) if os.path.isfile(p) else (None, "file not found")
        if t == "url":
            return _download(src["value"], src.get("token")), None
        if t == "github":
            return _download(github_latest_apk(src["value"], src.get("token")), src.get("token")), None
        return None, "unknown source type"
    except Exception as e:
        return None, str(e)


def installed_versions(ip, pkgs):
    """{pkg: (versionCode:int|None, versionName:str)} in one round trip; None = not installed."""
    safe = [re.sub(r"[^A-Za-z0-9_.]", "", p) for p in pkgs if p]
    if not safe:
        return {}
    cmd = ("for p in %s; do d=$(dumpsys package \"$p\" 2>/dev/null); "
           "c=$(echo \"$d\" | grep -m1 versionCode | sed 's/.*versionCode=//;s/ .*//'); "
           "n=$(echo \"$d\" | grep -m1 versionName | sed 's/.*versionName=//'); "
           "echo \"$p|$c|$n\"; done") % " ".join(safe)
    _, out, _ = adb("-s", serial(ip), "shell", cmd, timeout=45)
    res = {}
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) >= 3:
            c = parts[1].strip()
            res[parts[0]] = (int(c) if c.isdigit() else None, parts[2].strip())
    return res


def update_status(installed_code, candidate_code):
    if installed_code is None:
        return "new"          # not installed -> fresh install
    if installed_code < candidate_code:
        return "update"       # behind -> update available
    if installed_code == candidate_code:
        return "current"      # up to date
    return "newer"            # device has a newer build (install -r would refuse)


def diff_apk(apk_path):
    """Compare one APK's versionCode against every saved Portal."""
    info = apk_version(apk_path)
    if not info:
        return {"ok": False, "msg": "could not read the APK's version"}
    pkg, cand, states, devs = info["package"], info["versionCode"], adb_states(), []
    cand_sig = apk_signer(apk_path)
    for d in load_devices():
        if states.get(serial(d["ip"])) != "device":
            devs.append({"ip": d["ip"], "name": d["name"], "status": "offline"})
            continue
        iv = installed_versions(d["ip"], [pkg]).get(pkg, (None, ""))
        st = update_status(iv[0], cand)
        e = {"ip": d["ip"], "name": d["name"], "installedCode": iv[0], "installedName": iv[1], "status": st}
        if st == "update":  # only an update-over-existing can hit a signer mismatch
            e["signer"] = signer_status(cand_sig, installed_signer(d["ip"], pkg, iv[0]))
        devs.append(e)
    return {"ok": True, "package": pkg, "versionCode": cand,
            "versionName": info.get("versionName", ""), "path": apk_path, "devices": devs}


def check_sources():
    """For each configured package, fetch its candidate and report fleet status."""
    states = adb_states()
    online = [d for d in load_devices() if states.get(serial(d["ip"])) == "device"]
    rows = []
    for pkg, src in load_sources().items():
        apk, err = resolve_candidate(src)
        info = apk_version(apk) if apk and not err else None
        if not info:
            rows.append({"package": pkg, "source": src, "error": err or "could not read candidate APK"})
            continue
        cand = info["versionCode"]
        cand_sig = apk_signer(apk)
        devs = []
        for d in online:
            iv = installed_versions(d["ip"], [pkg]).get(pkg, (None, ""))
            st = update_status(iv[0], cand)
            e = {"ip": d["ip"], "name": d["name"], "installedCode": iv[0], "installedName": iv[1], "status": st}
            if st == "update":
                e["signer"] = signer_status(cand_sig, installed_signer(d["ip"], pkg, iv[0]))
            devs.append(e)
        rows.append({"package": pkg, "source": src, "path": apk, "candidateCode": cand,
                     "candidateName": info.get("versionName", ""), "devices": devs})
    return rows


def apply_source(pkg, targets):
    src = load_sources().get(pkg)
    if not src:
        return {"ok": False, "msg": "no source for " + pkg}
    apk, err = resolve_candidate(src)
    if err or not apk:
        return {"ok": False, "msg": err or "no candidate APK"}
    return {"ok": True, "results": install(apk, targets)}


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
        elif u.path == "/api/sources":
            self._send(200, {"sources": load_sources()})
        elif u.path == "/api/icon":
            pkg = (q.get("pkg", [""])[0]).strip()
            if not (valid_ip(ip) and re.match(r"^[A-Za-z0-9_.]+$", pkg)):
                return self._send(404, {"error": "bad params"})
            data, ct = app_icon(ip, pkg)
            if data:
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Cache-Control", "max-age=86400")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._send(404, {"error": "no icon"})
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
        elif path == "/api/diff":
            b = self._json()
            apk = b.get("path") or (DEBUG_APK if b.get("useDebug") else None)
            if not apk:
                return self._send(400, {"ok": False, "msg": "no APK provided"})
            self._send(200, diff_apk(apk))
        elif path == "/api/source":
            b = self._json()
            pkg = (b.get("pkg") or "").strip()
            typ = b.get("type") or ""
            val = (b.get("value") or "").strip()
            if not (re.match(r"^[A-Za-z0-9_.]+$", pkg) and typ in ("github", "url", "path") and val):
                return self._send(400, {"ok": False, "msg": "package, type and value are required"})
            s = load_sources()
            s[pkg] = {"type": typ, "value": val}
            if b.get("token"):
                s[pkg]["token"] = b["token"].strip()
            save_sources(s)
            self._send(200, {"ok": True})
        elif path == "/api/source-remove":
            pkg = (self._json().get("pkg") or "").strip()
            s = load_sources()
            s.pop(pkg, None)
            save_sources(s)
            self._send(200, {"ok": True})
        elif path == "/api/updates-check":
            self._send(200, {"rows": check_sources()})
        elif path == "/api/updates-apply":
            b = self._json()
            targets = [t for t in (b.get("targets") or []) if t]
            if not (b.get("pkg") and targets):
                return self._send(400, {"ok": False, "msg": "pkg and targets required"})
            self._send(200, apply_source(b["pkg"].strip(), targets))
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
  :root{
    color-scheme:dark;
    --bg:#0b0d12; --surface:#13161d; --surface-2:#1a1e27; --surface-3:#222734;
    --border:#242a35; --border-strong:#323948;
    --text:#e7e9f0; --dim:#9aa2b1; --faint:#697185;
    --accent:#6366f1; --accent-hover:#5457e6; --accent-soft:rgba(99,102,241,.16);
    --green:#34d399; --green-soft:rgba(52,211,153,.14);
    --amber:#fbbf24; --amber-soft:rgba(251,191,36,.14);
    --red:#f87171; --red-hover:#ef4444; --red-soft:rgba(248,113,113,.13);
    --radius:14px; --radius-sm:9px; --shadow:0 1px 2px rgba(0,0,0,.5),0 12px 32px rgba(0,0,0,.35);
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;background:radial-gradient(1200px 600px at 80% -10%,#161a24 0,var(--bg) 55%) fixed;color:var(--text);
    font:14px/1.55 ui-sans-serif,-apple-system,system-ui,"Segoe UI",Roboto,Inter,sans-serif;-webkit-font-smoothing:antialiased}
  a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
  ::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-thumb{background:#2a3140;border-radius:6px}
  /* ---------- app bar ---------- */
  .appbar{display:flex;align-items:center;gap:14px;padding:13px 22px;border-bottom:1px solid var(--border);
    background:rgba(12,14,19,.7);backdrop-filter:blur(10px);position:sticky;top:0;z-index:30}
  .brand{display:flex;align-items:center;gap:11px}
  .logo{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;
    background:linear-gradient(135deg,#6366f1,#8b5cf6);box-shadow:0 4px 14px rgba(99,102,241,.4);font-size:18px}
  .brand b{font-size:15px;letter-spacing:.2px} .brand .tag{font-size:11.5px;color:var(--faint);margin-top:-2px}
  .spacer{flex:1}
  .stat-pill{display:flex;align-items:center;gap:8px;padding:6px 12px;background:var(--surface);border:1px solid var(--border);
    border-radius:999px;font-size:12.5px;color:var(--dim)}
  .stat-pill b{color:var(--text)}
  /* ---------- layout ---------- */
  .layout{display:grid;grid-template-columns:340px 1fr;gap:20px;padding:20px 22px;max-width:1320px;margin:0 auto;align-items:start}
  @media(max-width:880px){.layout{grid-template-columns:1fr}}
  .panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow)}
  .panel-pad{padding:16px}
  .section-h{display:flex;align-items:center;gap:9px;margin:0 0 13px;font-size:12px;font-weight:600;letter-spacing:.06em;
    text-transform:uppercase;color:var(--dim)}
  .count{background:var(--surface-3);color:var(--dim);border-radius:999px;padding:1px 8px;font-size:11px;font-weight:600}
  .hint{color:var(--faint);font-size:12px;line-height:1.5}
  /* ---------- buttons ---------- */
  .btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;font:inherit;font-weight:550;font-size:13px;
    border:1px solid transparent;border-radius:var(--radius-sm);padding:8px 13px;cursor:pointer;color:#fff;background:var(--accent);
    transition:background .12s,border-color .12s,opacity .12s;white-space:nowrap}
  .btn:hover{background:var(--accent-hover)} .btn svg{width:15px;height:15px}
  .btn.ghost{background:var(--surface-2);color:var(--text);border-color:var(--border-strong)}
  .btn.ghost:hover{background:var(--surface-3)}
  .btn.subtle{background:transparent;color:var(--dim);border-color:transparent;padding:7px 9px}
  .btn.subtle:hover{background:var(--surface-2);color:var(--text)}
  .btn.danger{background:var(--red-soft);color:#fecaca;border-color:rgba(248,113,113,.35)}
  .btn.danger:hover{background:rgba(248,113,113,.22)}
  .btn.sm{padding:5px 10px;font-size:12px;border-radius:7px} .btn.sm svg{width:13px;height:13px}
  .btn.block{width:100%}
  .btn:disabled{opacity:.45;cursor:default;pointer-events:none}
  .iconbtn{display:grid;place-items:center;width:30px;height:30px;border-radius:8px;background:transparent;border:1px solid transparent;
    color:var(--dim);cursor:pointer} .iconbtn:hover{background:var(--surface-2);color:var(--text)} .iconbtn svg{width:16px;height:16px}
  /* ---------- inputs ---------- */
  .input{width:100%;background:var(--bg);border:1px solid var(--border-strong);color:var(--text);border-radius:8px;padding:9px 11px;font:inherit}
  .input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
  .input::placeholder{color:var(--faint)}
  .field-lbl{font-size:12px;color:var(--dim);margin-bottom:5px;display:block}
  /* ---------- device cards ---------- */
  .dev{display:flex;align-items:center;gap:11px;padding:11px 12px;border:1px solid var(--border);border-radius:11px;margin-bottom:9px;
    cursor:pointer;transition:border-color .12s,background .12s;position:relative}
  .dev:hover{border-color:var(--border-strong);background:var(--surface-2)}
  .dev.sel{border-color:var(--accent);background:linear-gradient(0deg,var(--accent-soft),transparent)}
  .dev .av{width:34px;height:34px;border-radius:9px;background:var(--surface-3);display:grid;place-items:center;font-size:15px;flex:none}
  .dev .nm{font-weight:600;font-size:13.5px;display:flex;align-items:center;gap:7px}
  .dev .sub{font-size:11.5px;color:var(--faint);margin-top:1px}
  .dev .kebab{margin-left:auto}
  .badge{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid}
  .badge .dot{width:6px;height:6px;border-radius:50%}
  .b-online{color:#6ee7b7;background:var(--green-soft);border-color:rgba(52,211,153,.3)} .b-online .dot{background:var(--green)}
  .b-off{color:#9aa2b1;background:var(--surface-2);border-color:var(--border-strong)} .b-off .dot{background:var(--faint)}
  .b-warn{color:#fcd34d;background:var(--amber-soft);border-color:rgba(251,191,36,.3)} .b-warn .dot{background:var(--amber)}
  /* dropdown menu */
  .menu{position:absolute;right:10px;top:46px;background:var(--surface-2);border:1px solid var(--border-strong);border-radius:10px;
    box-shadow:var(--shadow);padding:5px;z-index:20;min-width:150px}
  .menu button{display:flex;align-items:center;gap:9px;width:100%;background:transparent;border:0;color:var(--text);font:inherit;font-size:13px;
    padding:8px 10px;border-radius:7px;cursor:pointer;text-align:left}
  .menu button:hover{background:var(--surface-3)} .menu button.danger{color:#fca5a5} .menu svg{width:14px;height:14px;color:var(--dim)}
  /* segmented add actions */
  .addgrid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
  .addgrid .btn{flex-direction:column;gap:6px;padding:11px 6px;font-size:11.5px} .addgrid .btn svg{width:17px;height:17px}
  /* ---------- device detail header ---------- */
  .dh{display:flex;align-items:center;gap:14px;padding:16px 18px;border-bottom:1px solid var(--border)}
  .dh .av{width:46px;height:46px;border-radius:12px;background:var(--surface-3);display:grid;place-items:center;font-size:21px}
  .dh h2{margin:0;font-size:18px} .dh .meta{font-size:12.5px;color:var(--faint);margin-top:2px;display:flex;gap:8px;flex-wrap:wrap}
  .dh-actions{margin-left:auto;display:flex;gap:7px}
  /* tabs */
  .tabs{display:flex;gap:4px;padding:10px 16px 0}
  .tab{display:flex;align-items:center;gap:7px;background:transparent;border:0;border-bottom:2px solid transparent;color:var(--dim);
    font:inherit;font-weight:550;font-size:13.5px;padding:9px 12px;cursor:pointer} .tab svg{width:15px;height:15px}
  .tab:hover{color:var(--text)} .tab.on{color:var(--text);border-bottom-color:var(--accent)}
  .tabbody{padding:18px}
  /* sub-card */
  .sub-card{background:var(--surface-2);border:1px solid var(--border);border-radius:12px;padding:15px;margin-bottom:16px}
  .sub-card h3{margin:0 0 4px;font-size:14px} .sub-card .desc{font-size:12.5px;color:var(--faint);margin-bottom:12px}
  /* dropzone */
  .drop{border:1.5px dashed var(--border-strong);border-radius:11px;padding:20px;text-align:center;color:var(--dim);cursor:pointer;
    transition:border-color .12s,background .12s} .drop:hover,.drop.drag{border-color:var(--accent);background:var(--accent-soft);color:var(--text)}
  .drop svg{width:24px;height:24px;color:var(--faint);margin-bottom:6px}
  .filechip{display:inline-flex;align-items:center;gap:8px;background:var(--surface-3);border:1px solid var(--border-strong);
    border-radius:8px;padding:6px 10px;font-size:12.5px;margin-top:10px}
  .seg{display:inline-flex;background:var(--bg);border:1px solid var(--border-strong);border-radius:9px;padding:3px;gap:3px}
  .seg button{background:transparent;border:0;color:var(--dim);font:inherit;font-size:12.5px;font-weight:550;padding:6px 12px;border-radius:6px;cursor:pointer}
  .seg button.on{background:var(--accent);color:#fff}
  /* apps table */
  .toolbar{display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}
  .search{position:relative;flex:1;min-width:160px} .search svg{position:absolute;left:10px;top:50%;transform:translateY(-50%);width:15px;height:15px;color:var(--faint)}
  .search input{padding-left:32px}
  .switch{display:inline-flex;align-items:center;gap:8px;font-size:12.5px;color:var(--dim);cursor:pointer;user-select:none}
  .switch input{display:none} .track{width:34px;height:19px;border-radius:999px;background:var(--surface-3);position:relative;transition:background .15s}
  .track::after{content:"";position:absolute;width:15px;height:15px;border-radius:50%;background:#cbd5e1;top:2px;left:2px;transition:left .15s}
  .switch input:checked+.track{background:var(--accent)} .switch input:checked+.track::after{left:17px;background:#fff}
  .applist{border:1px solid var(--border);border-radius:11px;overflow:hidden}
  .approw{display:flex;align-items:center;gap:12px;padding:11px 14px;border-bottom:1px solid var(--border)}
  .approw:last-child{border-bottom:0} .approw:hover{background:var(--surface-2)}
  .approw .pk{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;word-break:break-all}
  .approw .vr{font-size:11.5px;color:var(--faint)} .approw .acts{margin-left:auto;display:flex;gap:6px;flex:none}
  .app-ico{position:relative;width:36px;height:36px;border-radius:9px;background:var(--surface-3);display:grid;place-items:center;flex:none;overflow:hidden;color:var(--faint)}
  .app-ico img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}
  .skel{height:44px;background:linear-gradient(90deg,var(--surface-2),var(--surface-3),var(--surface-2));
    background-size:200% 100%;animation:sh 1.2s infinite;border-radius:8px;margin-bottom:8px}
  @keyframes sh{to{background-position:-200% 0}}
  /* controls */
  .ctl-group{margin-bottom:18px} .ctl-group .gl{font-size:12px;font-weight:600;color:var(--dim);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}
  .ctl-row{display:flex;gap:9px;flex-wrap:wrap}
  pre.out{background:#0a0c10;border:1px solid var(--border);border-radius:10px;padding:12px;font-size:12px;
    font-family:ui-monospace,Menlo,monospace;white-space:pre-wrap;word-break:break-word;max-height:320px;overflow:auto;color:#c7d0de}
  img.shot{max-width:100%;border:1px solid var(--border);border-radius:12px;margin-top:12px;display:block}
  /* info */
  .kv{display:grid;grid-template-columns:140px 1fr;gap:0}
  .kv>div{padding:11px 4px;border-bottom:1px solid var(--border);font-size:13.5px} .kv .k{color:var(--dim)}
  .kv>div:nth-last-child(-n+2){border-bottom:0}
  .batt{display:inline-flex;align-items:center;gap:9px} .batt .bar{width:90px;height:7px;border-radius:4px;background:var(--surface-3);overflow:hidden}
  .batt .fill{height:100%;background:var(--green)}
  /* empty / onboarding */
  .empty{padding:46px 30px;text-align:center;max-width:560px;margin:0 auto}
  .empty .big{width:60px;height:60px;border-radius:16px;margin:0 auto 16px;display:grid;place-items:center;font-size:28px;
    background:linear-gradient(135deg,#6366f1,#8b5cf6);box-shadow:0 8px 24px rgba(99,102,241,.35)}
  .empty h2{margin:0 0 8px;font-size:20px} .empty p{color:var(--dim);margin:0 auto 22px;max-width:440px}
  .steps{text-align:left;display:grid;gap:12px;max-width:420px;margin:0 auto}
  .step{display:flex;gap:12px;align-items:flex-start;background:var(--surface-2);border:1px solid var(--border);border-radius:11px;padding:13px 14px}
  .step .n{width:24px;height:24px;border-radius:50%;background:var(--accent);color:#fff;display:grid;place-items:center;font-size:12.5px;font-weight:700;flex:none}
  .step b{font-size:13.5px} .step p{margin:2px 0 0;font-size:12.5px;color:var(--faint);max-width:none}
  /* toasts */
  #toasts{position:fixed;top:16px;right:16px;z-index:200;display:flex;flex-direction:column;gap:9px;max-width:380px}
  .toast{display:flex;align-items:flex-start;gap:10px;background:var(--surface-2);border:1px solid var(--border-strong);border-left-width:3px;
    border-radius:10px;padding:11px 13px;box-shadow:var(--shadow);animation:slidein .18s ease;font-size:13px}
  .toast.ok{border-left-color:var(--green)} .toast.err{border-left-color:var(--red)} .toast.info{border-left-color:var(--accent)}
  .toast svg{width:16px;height:16px;flex:none;margin-top:1px} .toast.ok svg{color:var(--green)} .toast.err svg{color:var(--red)} .toast.info svg{color:var(--accent)}
  .toast .x{margin-left:6px;color:var(--faint);cursor:pointer}
  @keyframes slidein{from{transform:translateX(20px);opacity:0}}
  /* modal */
  .overlay{position:fixed;inset:0;background:rgba(4,6,10,.66);backdrop-filter:blur(3px);display:grid;place-items:center;z-index:150;padding:20px}
  .modal{background:var(--surface);border:1px solid var(--border-strong);border-radius:16px;box-shadow:var(--shadow);max-width:560px;width:100%;
    max-height:86vh;overflow:auto}
  .modal-h{display:flex;align-items:center;gap:10px;padding:18px 20px;border-bottom:1px solid var(--border)} .modal-h h3{margin:0;font-size:16px}
  .modal-b{padding:20px} .modal-f{display:flex;justify-content:flex-end;gap:9px;padding:16px 20px;border-top:1px solid var(--border)}
  .help-sec{margin-bottom:18px} .help-sec h4{margin:0 0 5px;font-size:13.5px;display:flex;align-items:center;gap:8px}
  .help-sec p{margin:0;font-size:13px;color:var(--dim)}
  .warnbox{display:flex;gap:10px;background:var(--amber-soft);border:1px solid rgba(251,191,36,.3);border-radius:10px;padding:11px 13px;font-size:12.5px;color:#fcd34d}
  .warnbox svg{width:16px;height:16px;flex:none;margin-top:1px}
  .res-line{font-size:12.5px;padding:7px 11px;border-radius:8px;margin-top:7px}
  .res-line.ok{background:var(--green-soft);color:#86efac} .res-line.err{background:var(--red-soft);color:#fca5a5}
</style></head>
<body>
<div class="appbar">
  <div class="brand"><div class="logo">🛰️</div><div><b>Portal Hub</b><div class="tag">manage your Meta Portals over Wi-Fi</div></div></div>
  <div class="spacer"></div>
  <div class="stat-pill" id="statPill"><span class="dot" style="width:7px;height:7px;border-radius:50%;background:var(--green)"></span><span id="statTxt">—</span></div>
  <button class="btn ghost sm" onclick="showUpdates()" id="updBtn"></button>
  <button class="btn ghost sm" onclick="openHelp()" id="helpBtn"></button>
</div>

<div class="layout">
  <!-- ============ sidebar ============ -->
  <aside class="panel panel-pad">
    <div class="section-h">Devices <span class="count" id="devCount">0</span>
      <span class="spacer" style="flex:1"></span>
      <button class="iconbtn" title="Refresh status" onclick="loadDevices(true)" id="refreshBtn"></button>
    </div>
    <div id="devs"></div>

    <div style="margin-top:14px">
      <div class="section-h">Add a Portal</div>
      <div class="addgrid">
        <button class="btn ghost" onclick="scan()" title="Find Portals already on Wi-Fi adb" id="scanBtn"></button>
        <button class="btn ghost" onclick="bootstrap()" title="One-time USB setup: enable Wi-Fi adb" id="usbBtn"></button>
        <button class="btn ghost" onclick="toggleAdd()" title="Add a Portal by its IP address" id="ipBtn"></button>
      </div>
      <div id="addForm" style="display:none;margin-top:10px">
        <label class="field-lbl">Name (optional)</label>
        <input class="input" id="nm" placeholder="e.g. Kitchen Portal" style="margin-bottom:8px">
        <label class="field-lbl">IP address</label>
        <input class="input" id="ip" placeholder="192.168.1.50" style="margin-bottom:8px">
        <button class="btn block" onclick="addDevice()">Add &amp; connect</button>
        <p class="hint" style="margin:8px 0 0">The Portal must already be in Wi-Fi adb mode (use <b>USB setup</b> first if not).</p>
      </div>
    </div>
    <div id="sideMsg"></div>
  </aside>

  <!-- ============ detail ============ -->
  <main class="panel" id="panel"></main>
</div>

<div id="toasts"></div>
<div id="modalRoot"></div>

<script>
const $=s=>document.querySelector(s);
const api=(p,b,m)=>fetch(p,{method:m||(b?'POST':'GET'),headers:b?{'Content-Type':'application/json'}:{},body:b?JSON.stringify(b):undefined}).then(r=>r.json());
const esc=s=>(s==null?'':''+s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* ---------- icon set (inline SVG) ---------- */
const I={
  refresh:'<path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6"/>',
  scan:'<path d="M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0"/><circle cx="12" cy="19" r="1"/>',
  usb:'<path d="M12 3v15M9 7l3-4 3 4M7 12h10M7 12v3a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-3"/><circle cx="12" cy="20" r="1.5"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  apps:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  sliders:'<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.5"/>',
  cam:'<path d="M3 8a2 2 0 0 1 2-2h2l1.5-2h7L19 6h0a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><circle cx="12" cy="12.5" r="3.2"/>',
  home:'<path d="M3 11l9-8 9 8M5 10v10h14V10"/>',
  back:'<path d="M19 12H5M12 19l-7-7 7-7"/>',
  sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19"/>',
  moon:'<path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.5 6.5 0 0 0 9.8 9.8z"/>',
  power:'<path d="M12 3v9M6.4 6.4a8 8 0 1 0 11.2 0"/>',
  term:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M13 15h4"/>',
  trash:'<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/>',
  x:'<path d="M18 6L6 18M6 6l12 12"/>',
  search:'<circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/>',
  up:'<path d="M12 19V5M5 12l7-7 7 7"/>',
  play:'<path d="M6 4l14 8-14 8z"/>',
  stop:'<rect x="6" y="6" width="12" height="12" rx="2"/>',
  eraser:'<path d="M7 21h10M5 16l6-6 8 8-4 4H9zM11 10l5-5 3 3-5 5"/>',
  link:'<path d="M9 12h6M10 7H7a5 5 0 0 0 0 10h3M14 7h3a5 5 0 0 1 0 10h-3"/>',
  unlink:'<path d="M7 7a5 5 0 0 0 0 10h2M17 17a5 5 0 0 0 0-10h-2M8 4v2M16 18v2M4 8h2M18 16h2"/>',
  dots:'<circle cx="12" cy="5" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="19" r="1.6"/>',
  check:'<path d="M20 6L9 17l-5-5"/>',
  alert:'<path d="M12 9v4M12 17v.5"/><path d="M10.3 3.8L2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.8a2 2 0 0 0-3.4 0z"/>',
  help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.9.4-1 .9-1 1.7M12 17v.4"/>',
  dl:'<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
  updates:'<path d="M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8M12 13v8"/>',
};
const svg=(n,w)=>'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"'+(w?' style="width:'+w+'px;height:'+w+'px"':'')+'>'+I[n]+'</svg>';

/* ---------- toast + confirm ---------- */
function toast(msg,kind){kind=kind||'info';const t=document.createElement('div');t.className='toast '+kind;
  const ic=kind==='ok'?'check':kind==='err'?'alert':'info';
  t.innerHTML=svg(ic)+'<div style="flex:1">'+esc(msg)+'</div><span class="x">'+svg('x',14)+'</span>';
  t.querySelector('.x').onclick=()=>t.remove();$('#toasts').appendChild(t);setTimeout(()=>t.remove(),4200);}
function confirmDialog(title,body,danger){return new Promise(res=>{
  const o=document.createElement('div');o.className='overlay';
  o.innerHTML='<div class="modal" style="max-width:440px"><div class="modal-h">'+svg(danger?'alert':'info')+'<h3>'+esc(title)+'</h3></div>'+
    '<div class="modal-b" style="color:var(--dim);font-size:13.5px">'+body+'</div>'+
    '<div class="modal-f"><button class="btn ghost" data-x>Cancel</button><button class="btn '+(danger?'danger':'')+'" data-ok>Confirm</button></div></div>';
  const close=v=>{o.remove();res(v)};o.querySelector('[data-x]').onclick=()=>close(false);
  o.querySelector('[data-ok]').onclick=()=>close(true);o.addEventListener('click',e=>{if(e.target===o)close(false)});
  document.addEventListener('keydown',function k(e){if(e.key==='Escape'){close(false);document.removeEventListener('keydown',k)}});
  $('#modalRoot').appendChild(o);});}

/* ---------- state ---------- */
let devices=[],sel=null,tab='apps',debugApk=null,showSys=false,appQuery='',apps=[],installTarget='this',openMenu=null,view='device',diffState=null;
const stateMap={device:['Online','b-online'],offline:['Offline','b-off'],unauthorized:['Unauthorized','b-warn'],disconnected:['Not connected','b-off']};
const badge=s=>{const m=stateMap[s]||['Unknown','b-off'];return '<span class="badge '+m[1]+'"><span class="dot"></span>'+m[0]+'</span>';};
const onlineCount=()=>devices.filter(d=>d.state==='device').length;

/* ---------- top buttons (icon labels) ---------- */
$('#helpBtn').innerHTML=svg('help')+'Help';
$('#updBtn').innerHTML=svg('updates')+'Updates';
$('#refreshBtn').innerHTML=svg('refresh');
$('#scanBtn').innerHTML=svg('scan')+'Scan network';
$('#usbBtn').innerHTML=svg('usb')+'USB setup';
$('#ipBtn').innerHTML=svg('plus')+'Add by IP';

/* ---------- devices ---------- */
async function loadDevices(toastOnDone){
  const d=await api('/api/devices');devices=d.devices;debugApk=d.debugApk;
  if(sel&&!devices.find(x=>x.ip===sel))sel=null;
  renderDevs();renderPanel();updateStat();
  if(toastOnDone)toast('Status refreshed','info');
}
function updateStat(){$('#devCount').textContent=devices.length;
  $('#statTxt').innerHTML='<b>'+onlineCount()+'</b> online · '+devices.length+' total';}
function renderDevs(){
  const el=$('#devs');
  if(!devices.length){el.innerHTML='<p class="hint">No Portals added yet. Use the buttons below to find or add one.</p>';return;}
  el.innerHTML=devices.map(x=>{const on=x.state==='device';return `
    <div class="dev ${x.ip===sel?'sel':''}" data-ip="${x.ip}" onclick="pick('${x.ip}')">
      <div class="av">🛰️</div>
      <div style="min-width:0;flex:1">
        <div class="nm">${esc(x.name)} <span class="st-badge">${badge(x.state)}</span></div>
        <div class="sub">${x.ip}</div>
      </div>
      <button class="iconbtn kebab" title="Actions" onclick="event.stopPropagation();menu('${x.ip}',event)">${svg('dots')}</button>
    </div>`;}).join('');
}
window.pick=ip=>{sel=ip;tab='apps';view='device';if(decodeURIComponent(location.hash.slice(1))!==ip)location.hash=encodeURIComponent(ip);renderDevs();renderPanel();};
function menu(ip,e){
  closeMenu();const card=document.querySelector('.dev[data-ip="'+ip+'"]');if(!card)return;
  const m=document.createElement('div');m.className='menu';openMenu=m;
  const on=devices.find(d=>d.ip===ip)?.state==='device';
  m.innerHTML=(on
    ?'<button onclick="rowAct(\''+ip+'\',\'disconnect\')">'+svg('unlink')+'Disconnect</button>'
    :'<button onclick="rowAct(\''+ip+'\',\'connect\')">'+svg('link')+'Connect</button>')+
    '<button class="danger" onclick="rowAct(\''+ip+'\',\'remove\')">'+svg('trash')+'Remove</button>';
  card.appendChild(m);
  setTimeout(()=>document.addEventListener('click',closeMenu,{once:true}),0);
}
function closeMenu(){if(openMenu){openMenu.remove();openMenu=null;}}
window.rowAct=async(ip,act)=>{closeMenu();
  if(act==='remove'){if(!await confirmDialog('Remove this Portal?','It will be removed from your list. The device itself isn\'t changed.',true))return;
    await api('/api/remove',{ip});if(sel===ip)sel=null;toast('Removed','ok');loadDevices();return;}
  if(act==='connect'){const r=await api('/api/connect',{ip});toast(r.ok?'Connected':'Couldn\'t connect: '+(r.msg||''),r.ok?'ok':'err');loadDevices();}
  if(act==='disconnect'){await api('/api/disconnect',{ip});toast('Disconnected','info');loadDevices();}
};

async function addDevice(){const ip=$('#ip').value.trim();if(!ip)return toast('Enter an IP address','err');
  const r=await api('/api/add',{name:$('#nm').value.trim(),ip});
  if(r.ok){toast('Added '+ip,'ok');$('#ip').value='';$('#nm').value='';toggleAdd();sel=ip;}else toast(r.msg||'Failed','err');loadDevices();}
function toggleAdd(){const f=$('#addForm');f.style.display=f.style.display==='none'?'block':'none';if(f.style.display==='block')$('#nm').focus();}
async function scan(){busy('#scanBtn',true);toast('Scanning your network for Portals…','info');
  const r=await api('/api/scan',{});busy('#scanBtn',false);
  if(r.error)return toast(r.error,'err');
  const ps=r.found.filter(f=>f.portal).length;
  toast('Scanned '+r.subnet+' — found '+r.found.length+' device(s)'+(ps?', '+ps+' Portal(s)':''),r.found.length?'ok':'info');
  loadDevices();}
async function bootstrap(){busy('#usbBtn',true);toast('USB setup: reading IP & enabling Wi-Fi adb…','info');
  const r=await api('/api/bootstrap',{});busy('#usbBtn',false);
  r.forEach(x=>toast(x.msg,x.ok?'ok':'err'));loadDevices();}
function busy(sel,on){const b=$(sel);if(b)b.disabled=on;}

/* ---------- detail panel ---------- */
function renderPanel(){
  const p=$('#panel');
  if(view==='updates'){renderUpdates();return;}
  const d=devices.find(x=>x.ip===sel);
  if(!d){p.innerHTML=emptyState();return;}
  p.innerHTML=`
    <div class="dh">
      <div class="av">🛰️</div>
      <div style="min-width:0">
        <h2>${esc(d.name)}</h2>
        <div class="meta"><span id="hdBadge">${badge(d.state)}</span><span>${d.ip}:5555</span></div>
      </div>
      <div class="dh-actions">
        <button class="btn ghost sm" onclick="setTab('controls');setTimeout(shot,50)" title="Screenshot">${svg('cam')}</button>
        <button class="btn ghost sm" onclick="key('wake')" title="Wake screen">${svg('sun')}</button>
        <button class="btn ghost sm" onclick="key('home')" title="Home">${svg('home')}</button>
      </div>
    </div>
    <div class="tabs">
      <button class="tab ${tab==='apps'?'on':''}" onclick="setTab('apps')">${svg('apps')}Apps</button>
      <button class="tab ${tab==='controls'?'on':''}" onclick="setTab('controls')">${svg('sliders')}Controls</button>
      <button class="tab ${tab==='info'?'on':''}" onclick="setTab('info')">${svg('info')}Info</button>
    </div>
    <div class="tabbody" id="tabbody"></div>`;
  if(d.state!=='device'){$('#tabbody').innerHTML='<div class="warnbox">'+svg('alert')+'<div>This Portal is <b>'+stateMap[d.state][0]+'</b>. Connect it first (⋯ menu → Connect, or it may need <b>USB setup</b> after a reboot).</div></div>';return;}
  if(tab==='apps')renderApps();else if(tab==='controls')renderControls();else renderInfo();
}
window.setTab=t=>{tab=t;renderPanel();};

function emptyState(){return `<div class="empty">
  <div class="big">🛰️</div>
  <h2>Welcome to Portal Hub</h2>
  <p>Control and manage every Meta Portal in your home from one place — install apps, take screenshots, run controls, all over Wi-Fi.</p>
  <div class="steps">
    <div class="step"><div class="n">1</div><div><b>Plug a Portal in via USB</b><p>Just once. Enable <i>Settings → Debug → ADB</i> on the Portal, then click <b>USB setup</b> in the sidebar — it switches the Portal to Wi-Fi adb and saves it.</p></div></div>
    <div class="step"><div class="n">2</div><div><b>Or find ones already set up</b><p>Click <b>Scan network</b> to auto-discover Portals already on Wi-Fi adb, or <b>Add by IP</b> if you know the address.</p></div></div>
    <div class="step"><div class="n">3</div><div><b>Select a Portal to manage it</b><p>Pick it from the list on the left to install apps, view what's installed, and use the controls.</p></div></div>
  </div>
  <p style="margin-top:22px;font-size:12.5px">New here? <a href="#" onclick="openHelp();return false">Read the quick guide →</a></p>
</div>`;}

/* ---------- APPS ---------- */
function renderApps(){
  $('#tabbody').innerHTML=`
    <div class="sub-card">
      <h3>Install an app</h3>
      <div class="desc">Push an APK to this Portal (or all online Portals) over Wi-Fi.</div>
      <div class="drop" id="drop">${svg('up')}<div><b>Drop an APK here</b> or click to browse</div></div>
      <input type="file" id="apk" accept=".apk" style="display:none">
      <div id="fileWrap"></div>
      ${debugApk?'<label class="switch" style="margin-top:12px"><input type="checkbox" id="useDebug"><span class="track"></span>Use latest debug build</label>':''}
      <div style="display:flex;align-items:center;gap:12px;margin-top:14px;flex-wrap:wrap">
        <span class="field-lbl" style="margin:0">Install to</span>
        <div class="seg" id="tgtSeg">
          <button class="${installTarget==='this'?'on':''}" onclick="setTarget('this')">This Portal</button>
          <button class="${installTarget==='all'?'on':''}" onclick="setTarget('all')">All online (${onlineCount()})</button>
        </div>
        <button class="btn" id="instBtn" onclick="doInstall()" style="margin-left:auto">${svg('up')}Install</button>
      </div>
      <div id="instRes"></div>
    </div>
    <div class="toolbar">
      <div class="search">${svg('search')}<input class="input" id="appq" placeholder="Search installed apps…" value="${esc(appQuery)}"></div>
      <label class="switch"><input type="checkbox" id="sys" ${showSys?'checked':''}><span class="track"></span>System apps</label>
      <button class="iconbtn" title="Refresh" onclick="loadApps()">${svg('refresh')}</button>
    </div>
    <div id="appList"></div>`;
  setupDrop();
  $('#appq').oninput=e=>{appQuery=e.target.value;renderAppRows();};
  $('#sys').onchange=e=>{showSys=e.target.checked;loadApps();};
  loadApps();
}
function setTarget(t){installTarget=t;document.querySelectorAll('#tgtSeg button').forEach((b,i)=>b.classList.toggle('on',(i===0)===(t==='this')));}
function setupDrop(){const dz=$('#drop'),fi=$('#apk');
  dz.onclick=()=>fi.click();
  fi.onchange=()=>showFile(fi.files[0]);
  ['dragover','dragenter'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add('drag');}));
  ['dragleave','drop'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.remove('drag');}));
  dz.addEventListener('drop',e=>{const f=e.dataTransfer.files[0];if(f){fi.files=e.dataTransfer.files;showFile(f);}});
}
let chosenFile=null;
function showFile(f){chosenFile=f||null;$('#fileWrap').innerHTML=f?'<div class="filechip">'+svg('check',14)+esc(f.name)+' · '+(f.size/1048576).toFixed(1)+' MB</div>':'';}
function installTargets(){return installTarget==='all'?devices.filter(d=>d.state==='device').map(d=>d.ip):[sel];}
async function doInstall(){
  const t=installTargets();if(!t.length)return toast('No online Portals to install to','err');
  const useDebug=$('#useDebug')&&$('#useDebug').checked;
  if(!chosenFile&&!useDebug)return toast('Choose an APK first (or tick the debug build)','err');
  const btn=$('#instBtn');btn.disabled=true;const out=$('#instRes');let path=null;
  if(chosenFile){out.innerHTML='<div class="res-line">Uploading '+esc(chosenFile.name)+'…</div>';
    const up=await fetch('/api/upload',{method:'POST',headers:{'X-Filename':chosenFile.name},body:chosenFile}).then(r=>r.json());
    if(!up.ok){out.innerHTML='<div class="res-line err">Upload failed</div>';btn.disabled=false;return;}path=up.path;}
  out.innerHTML='<div class="res-line">Installing to '+t.length+' Portal(s)…</div>';
  const r=await api('/api/install',{path,useDebug,targets:t});
  out.innerHTML=(r.results||[]).map(x=>'<div class="res-line '+(x.ok?'ok':'err')+'"><b>'+x.ip+'</b> — '+esc(x.msg)+'</div>').join('');
  const okN=(r.results||[]).filter(x=>x.ok).length;toast(okN+'/'+(r.results||[]).length+' installed',okN?'ok':'err');
  btn.disabled=false;loadApps();
}
async function loadApps(){
  const el=$('#appList');el.innerHTML='<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
  const r=await api('/api/apps?ip='+sel+'&system='+(showSys?1:0));apps=r.apps||[];renderAppRows();
}
function renderAppRows(){
  const el=$('#appList');if(!el)return;
  const list=apps.filter(a=>a.pkg.toLowerCase().includes(appQuery.toLowerCase()));
  if(!apps.length){el.innerHTML='<p class="hint">No apps found (is the device online?).</p>';return;}
  if(!list.length){el.innerHTML='<p class="hint">No apps match “'+esc(appQuery)+'”.</p>';return;}
  el.innerHTML='<div class="hint" style="margin-bottom:8px">'+list.length+' app'+(list.length>1?'s':'')+(showSys?' (incl. system)':'')+'</div><div class="applist">'+
    list.map(a=>`<div class="approw">
      <span class="app-ico">${svg('apps',16)}<img loading="lazy" src="/api/icon?ip=${encodeURIComponent(sel)}&pkg=${encodeURIComponent(a.pkg)}" onerror="this.remove()"></span>
      <div style="min-width:0"><div class="pk">${esc(a.pkg)}</div>${a.version?'<div class="vr">v'+esc(a.version)+'</div>':''}</div>
      <div class="acts">
        <button class="btn subtle sm" title="Launch" onclick="appAct('${a.pkg}','launch')">${svg('play')}</button>
        <button class="btn subtle sm" title="Force-stop" onclick="appAct('${a.pkg}','stop')">${svg('stop')}</button>
        <button class="btn subtle sm" title="Clear data" onclick="appAct('${a.pkg}','clear')">${svg('eraser')}</button>
        <button class="btn danger sm" title="Uninstall" onclick="appAct('${a.pkg}','uninstall')">${svg('trash')}</button>
      </div></div>`).join('')+'</div>';
}
window.appAct=async(pkg,action)=>{
  if(action==='uninstall'&&!await confirmDialog('Uninstall app?','Remove <code>'+esc(pkg)+'</code> from this Portal?',true))return;
  if(action==='clear'&&!await confirmDialog('Clear app data?','Erase all data &amp; cache for <code>'+esc(pkg)+'</code>? This cannot be undone.',true))return;
  const r=await api('/api/app',{ip:sel,pkg,action});
  toast((r.ok?'✓ ':'✗ ')+action+': '+pkg+(r.msg&&!r.ok?' — '+r.msg:''),r.ok?'ok':'err');
  if(action==='uninstall')loadApps();
};

/* ---------- CONTROLS ---------- */
function renderControls(){
  $('#tabbody').innerHTML=`
    <div class="ctl-group"><div class="gl">Display</div><div class="ctl-row">
      <button class="btn ghost" onclick="shot()">${svg('cam')}Screenshot</button>
      <button class="btn ghost" onclick="key('wake')">${svg('sun')}Wake</button>
      <button class="btn ghost" onclick="key('sleep')">${svg('moon')}Sleep</button>
    </div><div id="shotWrap"></div></div>
    <div class="ctl-group"><div class="gl">Navigation</div><div class="ctl-row">
      <button class="btn ghost" onclick="key('home')">${svg('home')}Home</button>
      <button class="btn ghost" onclick="key('back')">${svg('back')}Back</button>
    </div></div>
    <div class="ctl-group"><div class="gl">Power</div><div class="ctl-row">
      <button class="btn danger" onclick="reboot()">${svg('power')}Reboot Portal</button>
    </div><p class="hint" style="margin-top:7px">Rebooting drops the Portal off Wi-Fi adb until you re-run <b>USB setup</b> (Android 9/10 limitation).</p></div>
    <div class="ctl-group"><div class="gl">Shell <span style="color:var(--faint);font-weight:400;text-transform:none">— advanced</span></div>
      <div class="ctl-row"><input class="input" id="cmd" placeholder="e.g. dumpsys battery   ·   settings get secure screensaver_components" onkeydown="if(event.key==='Enter')runShell()">
        <button class="btn" onclick="runShell()">${svg('term')}Run</button></div>
      <p class="hint" style="margin:7px 0 9px">Runs <code>adb shell &lt;command&gt;</code> on this Portal.</p>
      <pre class="out" id="shOut">Output will appear here.</pre>
    </div>`;
}
window.shot=async()=>{const w=$('#shotWrap');if(!w)return;w.innerHTML='<div class="skel" style="height:200px;margin-top:12px"></div>';
  const r=await fetch('/api/screenshot?ip='+sel);if(!r.ok){w.innerHTML='<div class="res-line err">Screenshot failed</div>';return;}
  const b=await r.blob();const u=URL.createObjectURL(b);
  w.innerHTML='<img class="shot" src="'+u+'"><div style="margin-top:8px"><a class="btn ghost sm" href="'+u+'" download="portal-'+sel+'.png">'+svg('dl',13)+'Download</a></div>';};
window.key=async k=>{const r=await api('/api/key',{ip:sel,key:k});if(!r.ok)toast('Key '+k+' failed','err');else toast(k+' sent','info');};
window.reboot=async()=>{if(!await confirmDialog('Reboot this Portal?','It will restart and <b>drop off Wi-Fi adb</b> until you re-run USB setup.',true))return;
  const r=await api('/api/reboot',{ip:sel});toast(r.msg||'Reboot sent','info');};
window.runShell=async()=>{const c=$('#cmd').value.trim();if(!c)return;$('#shOut').textContent='Running…';
  const r=await api('/api/shell',{ip:sel,cmd:c});$('#shOut').textContent=r.out||r.msg||'(no output)';};

/* ---------- INFO ---------- */
async function renderInfo(){
  $('#tabbody').innerHTML='<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
  const i=await api('/api/info?ip='+sel);const b=parseInt(i.battery||'0',10)||0;
  $('#tabbody').innerHTML=`<div class="kv">
    <div class="k">Model</div><div>${esc(i.model||'—')}</div>
    <div class="k">Android</div><div>${esc(i.android||'—')} <span class="hint">(API ${esc(i.sdk||'—')})</span></div>
    <div class="k">Battery</div><div><span class="batt"><span class="bar"><span class="fill" style="width:${b}%;background:${b<20?'var(--red)':b<50?'var(--amber)':'var(--green)'}"></span></span>${esc(i.battery||'—')}%</span></div>
    <div class="k">Foreground app</div><div><code>${esc(i.focus||'—')}</code></div>
    <div class="k">adb serial</div><div><code>${esc(i.serial||'')}</code></div>
  </div>
  <p class="hint" style="margin-top:14px">Tip: set a DHCP reservation on your router so this Portal keeps the same IP.</p>`;
}

/* ---------- help modal ---------- */
function openHelp(){const o=document.createElement('div');o.className='overlay';
  o.innerHTML=`<div class="modal"><div class="modal-h">${svg('help')}<h3>Quick guide</h3><span class="spacer" style="flex:1"></span><button class="iconbtn" data-x>${svg('x')}</button></div>
  <div class="modal-b">
    <div class="warnbox" style="margin-bottom:16px">${svg('alert')}<div><b>Trusted network only.</b> This hub is unauthenticated and runs adb (including a shell and reboot) on your Portals. Anyone who can reach this page can control them. Keep it on your home LAN.</div></div>
    <div class="help-sec"><h4>${svg('usb')} USB setup (one-time per Portal)</h4><p>Portals run Android 9/10, which can't enable network adb from a menu. Plug the Portal in via USB once, enable <i>Settings → Debug → ADB</i>, and click <b>USB setup</b>. The hub reads its Wi-Fi IP, switches adb to wireless, and saves it. After that it's cable-free.</p></div>
    <div class="help-sec"><h4>${svg('scan')} Scan network</h4><p>Finds Portals already in Wi-Fi adb mode by probing your local network. Great after you've set a Portal up once, or to re-find one whose IP changed.</p></div>
    <div class="help-sec"><h4>${svg('apps')} Apps</h4><p>Install any APK to one Portal or all online Portals at once. Manage installed apps: launch, force-stop, clear data, or uninstall.</p></div>
    <div class="help-sec"><h4>${svg('power')} Reboot caveat</h4><p>A reboot drops the Portal off Wi-Fi adb (the wireless mode doesn't survive a restart). Re-run <b>USB setup</b> once to bring it back.</p></div>
    <div class="help-sec"><h4>${svg('info')} Tip</h4><p>Give each Portal a DHCP reservation on your router so its IP never changes.</p></div>
  </div>
  <div class="modal-f"><button class="btn" data-x>Got it</button></div></div>`;
  const close=()=>o.remove();o.querySelectorAll('[data-x]').forEach(b=>b.onclick=close);
  o.addEventListener('click',e=>{if(e.target===o)close()});
  document.addEventListener('keydown',function k(e){if(e.key==='Escape'){close();document.removeEventListener('keydown',k)}});
  $('#modalRoot').appendChild(o);}

/* ---------- background poll (in-place, no flashing) ---------- */
async function poll(){
  const d=await api('/api/devices');debugApk=d.debugApk;
  const same=d.devices.length===devices.length&&d.devices.every((x,i)=>devices[i]&&devices[i].ip===x.ip);
  devices=d.devices;updateStat();
  if(sel&&!devices.find(x=>x.ip===sel)){sel=null;renderDevs();renderPanel();return;}
  if(!same){renderDevs();renderPanel();return;}
  devices.forEach(x=>{const c=document.querySelector('.dev[data-ip="'+x.ip+'"]');if(!c)return;
    const sb=c.querySelector('.st-badge');if(sb)sb.innerHTML=badge(x.state);});
  const hb=$('#hdBadge');if(hb&&sel){const sd=devices.find(z=>z.ip===sel);if(sd)hb.outerHTML='<span id="hdBadge">'+badge(sd.state)+'</span>';}
}

/* ---------- UPDATES (fleet view) ---------- */
function showUpdates(){view='updates';sel=null;location.hash='updates';renderDevs();renderPanel();}
function uBadge(s){const m={update:['Update available','b-warn'],current:['Up to date','b-online'],new:['Not installed','b-off'],newer:['Newer on device','b-warn'],offline:['Offline','b-off']}[s]||['—','b-off'];return '<span class="badge '+m[1]+'"><span class="dot"></span>'+m[0]+'</span>';}
function isBehind(d){return d.status==='new'||(d.status==='update'&&d.signer!=='mismatch');}
function sigChip(d){return d.signer==='mismatch'?' <span class="badge b-warn" title="Different signing key — Android will reject the update"><span class="dot"></span>signing differs</span>':'';}
function blockedNote(n){return n?'<div class="warnbox" style="margin-top:10px">'+svg('alert')+'<div><b>'+n+'</b> Portal(s) have this app signed with a different key, so the update would be rejected. Uninstall the app there first to switch signing keys.</div></div>':'';}
function renderUpdates(){
  $('#panel').innerHTML=`
    <div class="dh">
      <div class="av">${svg('updates',22)}</div>
      <div style="min-width:0"><h2>Updates</h2><div class="meta">Compare installed apps against a newer APK and update your Portals — versionCode decides what's newer.</div></div>
      <div class="dh-actions"><button class="btn ghost sm" onclick="view='device';location.hash='';renderDevs();renderPanel()">${svg('back')}Done</button></div>
    </div>
    <div class="tabbody">
      <div class="sub-card">
        <h3>Check an APK against your Portals</h3>
        <div class="desc">Drop in any APK — the Hub reads its version and shows which Portals are behind, missing it, or already up to date.</div>
        <div class="drop" id="udrop">${svg('up')}<div><b>Drop an APK here</b> or click to browse</div></div>
        <input type="file" id="uapk" accept=".apk" style="display:none">
        <div id="ufile"></div><div id="diffRes"></div>
      </div>
      <div class="sub-card">
        <h3>Update sources <span class="hint" style="font-weight:400">— optional, per app</span></h3>
        <div class="desc">Attach a source to any package — a GitHub repo, a direct APK URL, or a file on this machine. “Check all” fetches the latest version from each and flags Portals that are behind. Nothing is app-specific.</div>
        <div class="ctl-row" style="margin-bottom:12px">
          <button class="btn" id="checkBtn" onclick="checkSources()">${svg('refresh')}Check all sources</button>
          <button class="btn ghost" onclick="toggleSrcForm()">${svg('plus')}Add source</button>
        </div>
        <div id="srcForm" style="display:none"></div>
        <div id="srcList"></div><div id="checkRes"></div>
      </div>
    </div>`;
  const dz=$('#udrop'),fi=$('#uapk');dz.onclick=()=>fi.click();fi.onchange=()=>doDiff(fi.files[0]);
  ['dragover','dragenter'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add('drag');}));
  ['dragleave','drop'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.remove('drag');}));
  dz.addEventListener('drop',e=>{const f=e.dataTransfer.files[0];if(f)doDiff(f);});
  loadSources();
}
async function doDiff(file){if(!file)return;
  $('#ufile').innerHTML='<div class="filechip">'+svg('check',14)+esc(file.name)+'</div>';
  $('#diffRes').innerHTML='<div class="res-line">Uploading &amp; comparing…</div>';
  const up=await fetch('/api/upload',{method:'POST',headers:{'X-Filename':file.name},body:file}).then(r=>r.json());
  if(!up.ok)return $('#diffRes').innerHTML='<div class="res-line err">Upload failed</div>';
  const r=await api('/api/diff',{path:up.path});
  if(!r.ok)return $('#diffRes').innerHTML='<div class="res-line err">'+esc(r.msg||'Could not read APK')+'</div>';
  diffState=r;renderDiff(r);
}
function renderDiff(r){
  const behind=r.devices.filter(isBehind);
  const blocked=r.devices.filter(d=>d.status==='update'&&d.signer==='mismatch').length;
  $('#diffRes').innerHTML=`<div style="margin:12px 0 8px"><b class="pk">${esc(r.package)}</b> · candidate <b>v${esc(r.versionName)}</b> <span class="hint">(code ${r.versionCode})</span></div>`+
    '<div class="applist">'+r.devices.map(d=>`<div class="approw"><div style="min-width:0">
      <div class="nm">${esc(d.name)}</div><div class="vr">${d.installedName?('installed v'+esc(d.installedName)+' · code '+d.installedCode):(d.status==='offline'?'offline':'not installed')}</div></div>
      <div class="acts">${uBadge(d.status)}${sigChip(d)}</div></div>`).join('')+'</div>'+blockedNote(blocked)+
    (behind.length?'<button class="btn" style="margin-top:12px" onclick="applyDiff()">'+svg('up')+'Install to '+behind.length+' Portal(s)</button>'
      :(blocked?'':'<div class="res-line ok" style="margin-top:10px">Every online Portal is already up to date.</div>'));
}
async function applyDiff(){if(!diffState)return;
  const t=diffState.devices.filter(isBehind).map(d=>d.ip);
  toast('Installing to '+t.length+' Portal(s)…','info');
  const r=await api('/api/install',{path:diffState.path,targets:t});
  const ok=(r.results||[]).filter(x=>x.ok).length;toast(ok+'/'+(r.results||[]).length+' installed',ok?'ok':'err');
  (r.results||[]).filter(x=>!x.ok).forEach(x=>toast(x.ip+': '+x.msg,'err'));
  const rr=await api('/api/diff',{path:diffState.path});if(rr.ok){diffState=rr;renderDiff(rr);}
}
async function loadSources(){const r=await api('/api/sources');const s=r.sources||{};const keys=Object.keys(s);const el=$('#srcList');if(!el)return;
  if(!keys.length){el.innerHTML='<p class="hint">No sources yet — add one to enable automatic update checks.</p>';return;}
  el.innerHTML='<div class="applist">'+keys.map(p=>`<div class="approw"><div style="min-width:0">
    <div class="pk">${esc(p)}</div><div class="vr">${esc(s[p].type)} · ${esc(s[p].value)}</div></div>
    <div class="acts"><button class="btn danger sm" title="Remove source" onclick="removeSource('${p}')">${svg('trash')}</button></div></div>`).join('')+'</div>';
}
function toggleSrcForm(){const f=$('#srcForm');if(f.style.display==='none'){f.innerHTML=srcFormHtml();f.style.display='block';bindSrc();}else f.style.display='none';}
function srcFormHtml(){return `<div class="sub-card" style="background:var(--bg)">
  <div class="ctl-row"><div style="flex:1;min-width:150px"><label class="field-lbl">Package name</label><input class="input" id="sPkg" placeholder="com.example.app"></div>
  <div style="width:150px"><label class="field-lbl">Source type</label><select class="input" id="sType"><option value="github">GitHub repo</option><option value="url">APK URL</option><option value="path">Local path</option></select></div></div>
  <div style="margin-top:10px"><label class="field-lbl" id="sValLbl">owner / repo</label><input class="input" id="sVal" placeholder="owner/repo"></div>
  <div style="margin-top:10px" id="sTokWrap"><label class="field-lbl">GitHub token <span class="hint">(optional — private repos / higher rate limit)</span></label><input class="input" id="sTok" placeholder="ghp_…"></div>
  <button class="btn block" style="margin-top:12px" onclick="addSource()">Save source</button>
  <p class="hint" style="margin:8px 0 0">The package name must match the app's id exactly (see it on the Apps tab).</p></div>`;}
function bindSrc(){const t=$('#sType');t.onchange=()=>{const v=t.value;
  $('#sValLbl').textContent=v==='github'?'owner / repo':v==='url'?'APK URL (https)':'Local file path on this machine';
  $('#sVal').placeholder=v==='github'?'owner/repo':v==='url'?'https://…/app.apk':'/path/to/app.apk';
  $('#sTokWrap').style.display=v==='github'?'block':'none';};}
async function addSource(){const pkg=$('#sPkg').value.trim(),type=$('#sType').value,value=$('#sVal').value.trim(),token=($('#sTok')||{}).value;
  if(!pkg||!value)return toast('Package and value are required','err');
  const r=await api('/api/source',{pkg,type,value,token:(token||'').trim()});
  if(!r.ok)return toast(r.msg||'Failed','err');
  toast('Source saved','ok');$('#srcForm').style.display='none';loadSources();
}
window.removeSource=async p=>{if(!await confirmDialog('Remove source?','Stop tracking updates for <code>'+esc(p)+'</code>? (The app itself is not touched.)',true))return;
  await api('/api/source-remove',{pkg:p});toast('Source removed','ok');loadSources();};
async function checkSources(){const btn=$('#checkBtn');if(btn)btn.disabled=true;
  $('#checkRes').innerHTML='<div class="res-line">Fetching latest versions &amp; comparing across your Portals… this can take a few seconds.</div>';
  const r=await api('/api/updates-check',{});if(btn)btn.disabled=false;const rows=r.rows||[];
  if(!rows.length){$('#checkRes').innerHTML='<p class="hint" style="margin-top:10px">Add a source above, then check.</p>';return;}
  $('#checkRes').innerHTML=rows.map(row=>{
    if(row.error)return '<div class="sub-card" style="background:var(--bg)"><b class="pk">'+esc(row.package)+'</b><div class="res-line err" style="margin-top:8px">'+esc(row.error)+'</div></div>';
    const behind=row.devices.filter(isBehind);
    const blocked=row.devices.filter(d=>d.status==='update'&&d.signer==='mismatch').length;
    return `<div class="sub-card" style="background:var(--bg)">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap"><b class="pk">${esc(row.package)}</b>
        <span class="badge b-warn" style="background:var(--accent-soft);color:#c7d2fe;border-color:rgba(99,102,241,.4)"><span class="dot" style="background:var(--accent)"></span>latest v${esc(row.candidateName)} · code ${row.candidateCode}</span>
        <span class="hint">via ${esc(row.source.type)}</span></div>
      <div class="applist" style="margin-top:10px">${row.devices.length?row.devices.map(d=>`<div class="approw"><div style="min-width:0"><div class="nm">${esc(d.name)}</div><div class="vr">${d.installedName?('installed v'+esc(d.installedName)):'not installed'}</div></div><div class="acts">${uBadge(d.status)}${sigChip(d)}</div></div>`).join(''):'<div class="approw"><span class="hint">No online Portals.</span></div>'}</div>${blockedNote(blocked)}
      ${behind.length?'<button class="btn" style="margin-top:12px" onclick="applySource(\''+row.package+'\',['+behind.map(d=>'\''+d.ip+'\'').join(',')+'])">'+svg('up')+'Update '+behind.length+' Portal(s)</button>':(blocked?'':'<div class="res-line ok" style="margin-top:10px">All online Portals up to date.</div>')}
    </div>`;}).join('');
}
window.applySource=async(pkg,targets)=>{toast('Updating '+targets.length+' Portal(s)…','info');
  const r=await api('/api/updates-apply',{pkg,targets});if(!r.ok)return toast(r.msg||'Update failed','err');
  const ok=(r.results||[]).filter(x=>x.ok).length;toast(ok+'/'+(r.results||[]).length+' updated',ok?'ok':'err');
  (r.results||[]).filter(x=>!x.ok).forEach(x=>toast(x.ip+': '+x.msg,'err'));checkSources();};

loadDevices().then(()=>{const h=decodeURIComponent(location.hash.slice(1));if(h==='updates')showUpdates();else if(h&&devices.find(d=>d.ip===h))pick(h);});
window.addEventListener('hashchange',()=>{const h=decodeURIComponent(location.hash.slice(1));if(h&&h!==sel&&devices.find(d=>d.ip===h))pick(h);});
setInterval(poll,8000);
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
