#!/bin/bash
set -e

echo "╔══════════════════════════════════════════╗"
echo "║      📺 TV-Automator Starting...         ║"
echo "╚══════════════════════════════════════════╝"

# ── Start SSH server ────────────────────────────────────────────
echo "[*] Starting SSH server..."
/usr/sbin/sshd

# ── Start D-Bus ─────────────────────────────────────────────────
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    eval $(dbus-launch --sh-syntax)
    export DBUS_SESSION_BUS_ADDRESS
    echo "[*] D-Bus started: $DBUS_SESSION_BUS_ADDRESS"
fi

# ── Ensure DISPLAY is set ──────────────────────────────────────
if [ -z "$DISPLAY" ]; then
    export DISPLAY=:0
    echo "[*] DISPLAY defaulting to :0"
else
    echo "[*] DISPLAY is $DISPLAY"
fi

# ── Start Openbox window manager ───────────────────────────────
echo "[*] Starting Openbox window manager..."
openbox --sm-disable &
sleep 1

# ── Create data directories ────────────────────────────────────
mkdir -p /data/cookies /data/config /data/logs

# ── Start PulseAudio (for HDMI audio) ──────────────────────────
echo "[*] Starting PulseAudio..."
pulseaudio --start --exit-idle-time=-1 2>/dev/null || true

# ── Launch TV-Automator ────────────────────────────────────────
echo "[*] Launching TV-Automator..."
echo "[*] Connect via SSH to control: ssh root@<tailscale-ip>"
echo "[*] Default password: tvautomator"
echo ""

# If connected interactively (docker run -it), launch TUI directly
# Otherwise, start as a background service and keep the container alive
if [ -t 0 ]; then
    exec python -m tv_automator.main
else
    echo "[*] Running in background mode."
    echo "[*] SSH in and run 'tv-automator' to start the TUI."
    # Keep container alive
    exec tail -f /dev/null
fi
