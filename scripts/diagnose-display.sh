#!/bin/bash
# Diagnose what X display is available on this host and whether Docker can use it.
# Run as the nrm user (not root).

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
warn() { echo -e "${YELLOW}[??]${NC}  $*"; }
fail() { echo -e "${RED}[!!]${NC}  $*"; }

echo "═══════════════════════════════════════════════════"
echo " TV-Automator — X11 Display Diagnostic"
echo "═══════════════════════════════════════════════════"
echo ""

# ── 1. What owns the X socket? ──────────────────────────────────
echo "── X socket ────────────────────────────────────────"
if [ -S /tmp/.X11-unix/X0 ]; then
    ok "/tmp/.X11-unix/X0 exists"
    OWNER=$(sudo fuser /tmp/.X11-unix/X0 2>/dev/null)
    if [ -n "$OWNER" ]; then
        echo "    PIDs using X0: $OWNER"
        for pid in $OWNER; do
            CMD=$(ps -p "$pid" -o comm= 2>/dev/null)
            echo "      PID $pid → $CMD"
        done
    else
        warn "fuser returned nothing (may need sudo, or socket is stale)"
    fi
else
    fail "/tmp/.X11-unix/X0 does not exist — no X server running?"
fi
echo ""

# ── 2. What display-related processes are running? ──────────────
echo "── Display-related processes ───────────────────────"
ps aux | grep -iE 'Xorg|Xwayland|gdm|lightdm|sddm|weston|mutter|gnome-shell|startx|xinit' \
       | grep -v grep \
       | while read -r line; do
    echo "    $line"
done
echo ""

# ── 3. Where is XAUTHORITY? ─────────────────────────────────────
echo "── XAUTHORITY candidates ───────────────────────────"
candidates=(
    "$HOME/.Xauthority"
    "/run/user/$(id -u)/gdm/Xauthority"
    "/run/user/$(id -u)/Xauthority"
    "/var/run/lightdm/root/:0"
    "/var/run/lightdm/${USER}/xauthority"
    "/var/lib/gdm3/.Xauthority"
    "/var/lib/gdm/.Xauthority"
    "/tmp/.Xauthority"
)
# Wayland/Xwayland: mutter creates a randomly-named auth file
mutter_auth=$(ls "/run/user/$(id -u)"/.mutter-Xwaylandauth.* 2>/dev/null | head -1)
[ -n "$mutter_auth" ] && candidates=("$mutter_auth" "${candidates[@]}")
FOUND_AUTH=""
for f in "${candidates[@]}"; do
    if [ -f "$f" ]; then
        ok "Found: $f"
        FOUND_AUTH="$f"
    fi
done
if [ -z "$FOUND_AUTH" ]; then
    warn "No Xauthority file found in common locations."
    warn "Try: sudo find /run /var /tmp -name '*authority*' -o -name '.Xauthority' 2>/dev/null"
fi
echo ""

# ── 4. Tail Xorg log for clues ──────────────────────────────────
echo "── Xorg.0.log (last 20 lines) ──────────────────────"
for log in /var/log/Xorg.0.log /run/user/$(id -u)/xorg.log; do
    if [ -f "$log" ]; then
        echo "    ($log)"
        tail -20 "$log" | sed 's/^/    /'
        break
    fi
done
echo ""

# ── 5. Test if we can reach the display ─────────────────────────
echo "── Display connectivity test ────────────────────────"
if [ -n "$FOUND_AUTH" ]; then
    export XAUTHORITY="$FOUND_AUTH"
    export DISPLAY=:0
    if xdpyinfo -display :0 &>/dev/null; then
        ok "xdpyinfo succeeded — X server is reachable"
        RESOLUTION=$(xdpyinfo -display :0 | grep -A1 'screen #0' | grep dimensions | awk '{print $2}')
        echo "    Resolution: $RESOLUTION"
    else
        fail "xdpyinfo failed even with XAUTHORITY=$FOUND_AUTH"
        echo "    Try running the script with sudo to find the right auth file."
    fi
else
    warn "Skipping display test — no XAUTHORITY found."
fi
echo ""

# ── 6. Is the docker group reachable? ───────────────────────────
echo "── Docker group ────────────────────────────────────"
if groups | grep -q docker; then
    ok "Current user is in the docker group"
else
    fail "Current user is NOT in the docker group — xhost trick won't work as-is"
fi
echo ""

# ── 7. Summary / next steps ─────────────────────────────────────
echo "═══════════════════════════════════════════════════"
echo " Next steps:"
echo "  1. Confirm the XAUTHORITY path above."
echo "  2. Run: ./scripts/setup-xhost.sh"
echo "  3. Then: cd docker && DISPLAY=:0 docker compose up -d"
echo "  4. Verify: docker exec tv-automator google-chrome --no-sandbox \\"
echo "       --disable-gpu https://google.com &"
echo "═══════════════════════════════════════════════════"
