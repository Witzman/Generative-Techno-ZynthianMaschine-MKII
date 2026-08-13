#!/usr/bin/env bash
# Deploy this repository's driver to a running Zynthian Pi, by file copy.
#
# This repository is the source of truth. The Pi's /zynthian/zynthian-ui is on
# upstream branch oram-2601.1 with the three Maschine files as UNTRACKED
# drop-ins, so a git operation there destroys the working instrument. Copy files.
#
#   ./tools/deploy-to-pi.sh                 driver, then restart daemon and UI
#   ./tools/deploy-to-pi.sh --with-system   also the helper scripts in /usr/local/bin
#   ./tools/deploy-to-pi.sh --no-restart    copy only, restart yourself
#   ./tools/deploy-to-pi.sh --dry-run       print every command, change nothing
#
# Host defaults to root@192.168.2.123 - mDNS .local does not resolve from WSL2.
# Override with PI=root@host, or pass it as the last argument.
#
# For a first install on a fresh Pi use install.sh ON the Pi instead; this script
# only refreshes what is already installed, and never touches udev, systemd or
# the zynautoconnect patch.
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PI="${PI:-root@192.168.2.123}"
CTRLDEV=/zynthian/zynthian-ui/zyngine/ctrldev

DRY=0
RESTART=1
SYSTEM=0
TESTS=1

for arg in "$@"; do
    case "$arg" in
        --dry-run)     DRY=1 ;;
        --no-restart)  RESTART=0 ;;
        --with-system) SYSTEM=1 ;;
        --skip-tests)  TESTS=0 ;;
        -h|--help)     sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *@*)           PI="$arg" ;;
        *)             echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

say() { printf "\n== %s\n" "$1"; }
run() {
    if [ "$DRY" = 1 ]; then printf "  [dry-run] %s\n" "$*"; else printf "  %s\n" "$*"; eval "$@"; fi
}

echo "Repository: $REPO"
echo "Target:     $PI"
[ "$DRY" = 1 ] && echo "DRY RUN - nothing will be changed."

# --- 1. do not ship a broken driver -------------------------------------------
# The driver itself cannot be imported off the Pi (zynlibs.zynseq is Pi-only),
# so the unit tests on techno_lib plus a compile check are the whole safety net.
if [ "$TESTS" = 1 ]; then
    say "Unit tests and compile check (--skip-tests to bypass)"
    ( cd "$REPO/ctrldev" && python3 -m unittest discover -s tests -q )
    ( cd "$REPO/ctrldev" && python3 -m py_compile zynthian_ctrldev_maschine_mk2.py \
                                                  techno_lib.py maschine_mk2_lib.py )
    echo "  ok"
fi

# --- 2. reachable? ------------------------------------------------------------
say "Check the Pi"
if [ "$DRY" = 0 ]; then
    ssh -o ConnectTimeout=5 "$PI" 'test -d '"$CTRLDEV"'' \
        || { echo "cannot reach $PI, or $CTRLDEV is missing - is Zynthian installed?" >&2; exit 1; }
    ssh "$PI" 'head -1 /zynthian/build_info.txt' | sed 's/^/  ZynthianOS: /'
fi

# --- 3. the driver ------------------------------------------------------------
# install.sh keeps a one-time .bak as the pre-Maschine baseline. Do not disturb
# it - keep a separate .prev holding whatever was running before this deploy.
say "Driver files -> $CTRLDEV"
for f in zynthian_ctrldev_maschine_mk2.py techno_lib.py maschine_mk2_lib.py; do
    run "ssh '$PI' 'test -f $CTRLDEV/$f && cp $CTRLDEV/$f $CTRLDEV/$f.prev || true'"
    run "scp -q '$REPO/ctrldev/$f' '$PI:$CTRLDEV/$f'"
    echo "  sent $f"
done

# --- 4. helper scripts, on request --------------------------------------------
# maschine.json is deliberately NOT deployed: it lives in daemon/ on the Pi and
# carries external_pad_leds, without which the first pad touch destroys the LED
# picture. Overwriting it from here would be a silent way to lose that flag.
if [ "$SYSTEM" = 1 ]; then
    say "Helper scripts -> /usr/local/bin"
    for f in maschine-jack-connect.sh maschine-clock-bridge.py maschine-clock-connect.sh; do
        run "scp -q '$REPO/system/$f' '$PI:/usr/local/bin/$f'"
        run "ssh '$PI' 'chmod 0755 /usr/local/bin/$f'"
        echo "  sent $f"
    done
    echo "  NOT sent: maschine.json, systemd units, udev rule - those are install.sh's job"
fi

# --- 5. restart, daemon FIRST -------------------------------------------------
if [ "$RESTART" = 1 ]; then
    say "Restart: daemon first, UI second"
    echo "  Order matters. Restarting the daemon alone makes a2j re-register its"
    echo "  port on a new zmip slot while the driver stays bound to the dead one,"
    echo "  and the rig goes silent with no error."
    run "ssh '$PI' 'systemctl restart maschine-mk2'"
    run "sleep 8"
    run "ssh '$PI' 'systemctl restart zynthian'"
    run "sleep 20"
else
    say "Not restarting (--no-restart). The Pi still runs the old driver until you do:"
    echo "  ssh $PI 'systemctl restart maschine-mk2' && sleep 8 && ssh $PI 'systemctl restart zynthian'"
fi

# --- 6. verify ----------------------------------------------------------------
# "Found" without "Loaded" means the driver has no zmip slot - the rig then does
# nothing at all, with no error. More than one devN_in on the Pads port means a
# stale JACK route, which makes every pad tap play a phantom sound.
if [ "$RESTART" = 1 ] && [ "$DRY" = 0 ]; then
    say "Verify"
    echo "-- ctrldev load lines (want Loaded, not just Found):"
    ssh "$PI" 'journalctl -u zynthian --since -2min | grep -i ctrldev | tail -5' || echo "  (nothing logged)"
    echo "-- Pads MIDI routing (want exactly one devN_in):"
    ssh "$PI" 'jack_lsp -c | grep -A3 "Pads MIDI"' || echo "  (port not found)"
    echo
    echo "Then play it. Neither check above proves a note sounds."
fi
