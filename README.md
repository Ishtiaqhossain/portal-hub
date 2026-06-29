# Portal Hub

One web page to control and manage every **Meta Portal** in your house. Run it on a machine on the
same Wi‑Fi as your Portals, open the page in a browser (from that machine, or your laptop/phone),
and manage them all from one place — over Wi‑Fi, no cable per action.

- **See every Portal** + live status. Add them three ways: **Scan LAN** (auto-find Portals already
  on Wi‑Fi adb), **＋ USB** one-time bootstrap, or type a name + IP.
- **Apps:** see what's installed (with versions), **install** any APK (to one or several Portals at
  once), and **uninstall / launch / force-stop / clear data**.
- **Controls:** **screenshot**, **reboot**, key events (**Home / Back / Wake / Sleep**), and a
  **shell** box for any `adb shell` command.
- **Info:** model, Android version, battery, foreground app.
- **Updates:** check any app across the fleet against a newer APK and update the Portals that are
  behind. Drop in an APK for a one-off comparison, or attach a per-app **update source** (GitHub
  repo / direct APK URL / local path) and "Check all" to see who's outdated. Newer-ness is decided
  by `versionCode` (the integer the OS itself orders by); APK versions are read with a stdlib-only
  parser. Nothing is app-specific — any package can have a source. Before an update, the Hub
  compares signing-certificate SHA-256 fingerprints (via the SDK's `apksigner`, if present) and
  **warns when the candidate is signed with a different key** than what's installed — the cause of
  `INSTALL_FAILED_UPDATE_INCOMPATIBLE` — excluding those Portals from the bulk update.

## Why the one-time USB step

Portals run Android 9/10, which predates Android 11's "wireless debugging with pairing code." There
is no on-device toggle to start network adb, so each Portal needs a **one-time USB bootstrap** to
flip adb into Wi‑Fi (TCP/IP) mode. After that, everything is wireless. **＋ USB** does that for you.

## Requirements

- **Python 3.7+** — standard library only. No `pip`, no `npm`, no other tools.
- **`adb`** (Android platform-tools) on your `PATH`. Set `ADB=/path/to/adb` to override.

That's the complete dependency list.

## Run

```bash
python3 server.py
# -> open http://<this-machine-ip>:8080  (shown in the console)
```

Environment overrides: `PORT` (default 8080), `HOST` (default `0.0.0.0`, so other machines on the LAN
can reach it), `ADB` (path to adb), and `DEBUG_APK` (optional path to an APK you rebuild often — set
it to get a one-click "use latest debug build" checkbox in the install panel).

## First-time setup per Portal

1. Plug the Portal into this machine via USB and enable *Settings → Debug → ADB Enabled*.
2. Click **＋ USB** — the Hub reads the Portal's Wi‑Fi IP, flips adb into TCP/IP mode, connects, and
   saves it. Unplug the cable. Repeat for each Portal, or just click **Scan LAN** afterward to pick
   up any Portal already in Wi‑Fi adb mode.

Tip: give each Portal a **DHCP reservation** on your router so its IP never changes.

## Caveats

- **A reboot resets Wi‑Fi adb.** TCP/IP mode drops when a Portal reboots (Android 9/10 can't persist
  it without root). Re-run **＋ USB** once after a reboot.
- **Trusted networks only.** This server is unauthenticated and runs adb on your behalf — including a
  shell and reboot. Anyone who can reach it controls your Portals. Run it only on your home LAN; don't
  expose it to the internet or untrusted networks.
- **Same subnet, no client isolation.** This machine and the Portals must be on the same subnet, and
  the router's AP/client isolation (common on guest Wi‑Fi) must be off.

## How it works

`server.py` is a single-file `http.server` that serves the embedded HTML/JS UI and exposes a small
JSON API; every action shells out to `adb` (`connect`, `devices`, `install -r`, `uninstall`,
`shell pm/am/monkey/input`, `exec-out screencap`, `reboot`, `tcpip`). The LAN scan TCP-probes
`:5555` across your /24 in parallel, then `adb connect`s the responders. Your saved Portal list lives
in `devices.json` next to the script (git-ignored); uploaded APKs go to a temp dir.
