# CLAUDE.md

Guidance for AI assistants (and humans) working in this repo.

## What this is

**Portal Hub** — a single-file web app to control and manage a fleet of **Meta Portal** devices
over Wi‑Fi `adb` from one page: discover devices, manage installed apps (install / uninstall /
launch / stop / clear), run controls (screenshot, reboot, key events, shell), and check & apply
app **updates** across the fleet. It runs on any machine on the same LAN as the Portals.

There is no backend service, no database, no build step. It's `server.py` and a README.

## The #1 rule: no dependencies

The entire value proposition is **zero install friction**. Keep it that way:

- **Python 3.7+ standard library only.** No `pip install`, ever. No `requirements.txt`.
- **No JavaScript build tooling.** No npm, no node_modules, no bundler, no CDN/external fonts or
  CSS/JS frameworks. The UI is hand-written HTML/CSS/JS with inline SVG icons.
- **The only runtime requirement is `adb`** (Android platform-tools) on `PATH`.
- **Optional, soft** integrations that must *degrade gracefully when absent*: the Android SDK's
  `apksigner` (used for the signing-key check — falls back to "unknown" if not found).

Before adding anything, ask: can the stdlib do this? It almost always can (`http.server`,
`urllib.request`, `zipfile`, `struct`, `socket`, `concurrent.futures`, `subprocess`). Do **not**
add `metavr` or anything from the Portal Claude *skill* — this tool is deliberately independent.

## Run

```bash
python3 server.py          # -> http://<this-machine-ip>:8080  (binds 0.0.0.0)
```

Env overrides: `PORT` (8080), `HOST` (0.0.0.0), `ADB` (path to adb), `DEBUG_APK` (optional path to
an APK for the one-click "use latest debug build" / update candidate), `APKSIGNER` (override the
auto-discovered apksigner), plus `ANDROID_HOME` / `ANDROID_SDK_ROOT` (searched for `apksigner`).

## Architecture (all in `server.py`)

- **`ThreadingHTTPServer` + `Handler`** — a small JSON API under `/api/*`, plus `GET /` which serves
  the embedded page. Every action shells out to `adb` via the `adb()` / `adb_bytes()` helpers
  (list-args, never `shell=True`; they never raise).
- **`PAGE`** — the *entire* frontend (HTML + CSS + JS) as one big `r"""..."""` string near the
  bottom of the file. See "Editing the UI" below.
- Logical groups of functions:
  - adb helpers: `adb`, `adb_bytes`, `serial`, `adb_states`, `usb_serials`, `valid_ip`.
  - device store (`devices.json`): `load_devices` / `save_devices` / `upsert_device`,
    `list_devices_with_state`, `connect`, `bootstrap_usb`, `scan_lan`.
  - per-device: `device_info`, `list_apps`, `install`, `app_action`.
  - **app updates**: `apk_version` (a stdlib binary-AXML parser — reads `versionCode`/`versionName`/
    `package` straight from `AndroidManifest.xml`), `apk_signer` / `installed_signer` /
    `signer_status` (SHA-256 cert check via `apksigner`), update sources (`sources.json`:
    `load_sources` / `save_sources` / `resolve_candidate` / `github_latest_apk`),
    `installed_versions`, `update_status`, `diff_apk`, `check_sources`, `apply_source`.

## Hard constraints — read before changing behavior

1. **Portals run Android 9/10** (no Android-11 wireless-pairing). Network adb needs a **one-time USB
   bootstrap** (`adb tcpip 5555`) per device; it resets on reboot. That's the whole reason **＋ USB**
   exists — don't assume devices can self-enable Wi‑Fi adb.
2. **Update freshness is decided by `versionCode`** (the integer the OS orders by and `install -r`
   enforces), never `versionName`. Keep it that way.
3. **Signing key must match for `install -r`.** A different key → `INSTALL_FAILED_UPDATE_INCOMPATIBLE`.
   The signer pre-check warns and excludes those devices; don't silently bulk-install over a mismatch.
4. **This server is unauthenticated and runs `adb` (shell + reboot) on the user's behalf.** It's a
   trusted-LAN tool. Don't add features that make it more dangerous to expose without saying so, and
   keep the in-app security warning. Validate device IPs (`valid_ip`) and package names before use.

## Editing the UI

The page is the `PAGE = r"""...""` string. Because it's a **raw** Python string:

- It must not contain `"""` anywhere.
- Backslashes are literal — write JS escapes as you want them in the browser (`\'` for an escaped
  quote, **not** `\\'`). Over-escaping is the most common bug here.
- `${...}` JS template literals are fine (Python doesn't touch them in a raw string).

Lint the embedded JS before trusting it:

```bash
python3 - <<'PY'
import re; open("/tmp/hub.js","w").write(re.search(r"<script>(.*)</script>", open("server.py").read(), re.S).group(1))
PY
node --check /tmp/hub.js      # node is only a dev convenience, NOT a runtime dep
```

## Conventions & gotchas

- **Runtime state is git-ignored:** `devices.json` (saved Portals) and `sources.json` (per-app update
  sources). Don't commit them. Uploaded APKs and downloaded candidates live in the system temp dir.
- The background poll patches device **status in place** (via `data-ip` / `.st-badge` / `#panelState`)
  and only re-renders the panel on a membership change — so the app list / screenshot / inputs never
  flash. Preserve that when touching `poll()` / `renderDevs()`.
- `installed_signer` pulls the device's `base.apk` once and caches by `(ip, pkg, versionCode)`; only
  computed for `update`-status devices. Keep it lazy — don't pull APKs eagerly.
- Test against a real Portal: `adb connect <ip>:5555`, then exercise endpoints with `curl`
  (e.g. `curl -s -X POST localhost:8080/api/updates-check`). There are no unit tests; verify on device.
- Match the existing style: small focused functions, list-arg `subprocess`, JSON responses
  `{ok, msg}` / `{...data}`, friendly user-facing strings.
