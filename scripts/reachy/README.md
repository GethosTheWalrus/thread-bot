# Reachy Local Install Scripts

Use the script that matches the machine running the Reachy worker/bridge.

## Debian / Ubuntu

```bash
bash scripts/reachy/install-debian-ubuntu.sh
```

## Fedora

```bash
bash scripts/reachy/install-fedora.sh
```

## macOS

```bash
bash scripts/reachy/install-macos.sh
```

## Raspberry Pi

```bash
bash scripts/reachy/install-raspberry-pi.sh
```

Notes:
- Linux scripts install the Reachy SDK's GStreamer/WebRTC dependencies.
- macOS installs the Python overlay only; Reachy hardware/media support may be limited depending on your setup.
- After installing, use `backend/requirements-reachy.txt` on the local Reachy host.
