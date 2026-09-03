#!/usr/bin/env bash
# Deploy this repository's driver to a running Zynthian Pi, by file copy.
#
# This repository is the source of truth. The Pi's /zynthian/zynthian-ui is on
# upstream branch oram-2601.1 with the three Maschine files as UNTRACKED
# drop-ins, so a git operation there destroys the working instrument. Copy files.
#
#   ./tools/deploy-to-pi.sh                 driver, then restart daemon and UI
#   ./tools/deploy-to-pi.sh --with-system   also the helper scripts in /usr/local/bin
#   ./tools/deploy-to-pi.sh --with-daemon   also the Rust daemon: send src, build ON the Pi
#   ./tools/deploy-to-pi.sh --no-restart    copy only, restart yourself
#   ./tools/deploy-to-pi.sh --rollback      put the .prev driver files back
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
DAEMON=0
TESTS=1
ROLLBACK=0

for arg in "$@"; do
    case "$arg" in
        --dry-run)     DRY=1 ;;
        --no-restart)  RESTART=0 ;;
        --with-system) SYSTEM=1 ;;
        --with-daemon) DAEMON=1 ;;
        --skip-tests)  TESTS=0 ;;
        # A rollback runs no tests: it is a recovery, and what it puts back
        # is whatever was on the rig before - not something this repository is
        # in a position to vouch for anyway.
        --rollback)    ROLLBACK=1; TESTS=0 ;;
        -h|--help)     sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *@*)           PI="$arg" ;;
        *)             echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

# `run` builds a command line as a STRING and evals it, because most steps here
# are an ssh whose remote command needs its own quoting. That is safe exactly as
# long as the paths and the host going into it cannot re-quote the line, so it
# is checked rather than hoped about.
case "$REPO$PI" in
    *[\'\"\`\$\ ]*)
        echo "Refusing to run: the repository path or the target contains a" >&2
        echo "space or a shell metacharacter, and this script builds command" >&2
        echo "lines as text.  repo: $REPO  target: $PI" >&2
        exit 1
        ;;
esac

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
    if [ "$DAEMON" = 1 ]; then
        # Same rule for the Rust half: the Pi is not where you find out.
        ( cd "$REPO/daemon" && cargo test --offline -q )
    fi
    echo "  ok"
fi

# --- 2. reachable? ------------------------------------------------------------
say "Check the Pi"
if [ "$DRY" = 0 ]; then
    ssh -o ConnectTimeout=5 "$PI" 'test -d '"$CTRLDEV"'' \
        || { echo "cannot reach $PI, or $CTRLDEV is missing - is Zynthian installed?" >&2; exit 1; }
    ssh "$PI" 'head -1 /zynthian/build_info.txt' | sed 's/^/  ZynthianOS: /'
fi

# --- 2b. the way back ---------------------------------------------------------
# THE .prev FILES WERE WRITE-ONLY until 2026-09-03. Every deploy took them and
# nothing could put them back, so recovering from a bad driver meant a hand
# `cp` over ssh under whatever pressure had just made it necessary. Same order
# as a deploy - daemon first, UI second - because the reason for that order has
# nothing to do with which files moved.
if [ "$ROLLBACK" = 1 ]; then
    say "Roll back to the .prev driver files on $PI"
    for f in zynthian_ctrldev_maschine_mk2.py techno_lib.py maschine_mk2_lib.py; do
        run "ssh '$PI' 'test -f $CTRLDEV/$f.prev'" \
            || { echo "no $f.prev on the Pi - nothing to roll back to" >&2; exit 1; }
    done
    for f in zynthian_ctrldev_maschine_mk2.py techno_lib.py maschine_mk2_lib.py; do
        # The current file becomes .rej rather than being thrown away: whatever
        # is being rolled back is also what somebody will want to look at.
        run "ssh '$PI' 'cp $CTRLDEV/$f $CTRLDEV/$f.rej && cp $CTRLDEV/$f.prev $CTRLDEV/$f'"
        echo "  restored $f  (the rejected one is now $f.rej)"
    done
    if [ "$RESTART" = 1 ]; then
        say "Restart: daemon first, UI second"
        run "ssh '$PI' 'systemctl restart maschine-mk2'"
        run "sleep 8"
        run "ssh '$PI' 'systemctl restart zynthian'"
    fi
    echo
    echo "Rolled back. The .prev files are unchanged, so this is repeatable."
    exit 0
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

# CHECKSUMS, since 2026-09-03. scp reports its own success and that is not the
# same as the rig running what is in this repository: a deploy that half
# happened, or a file edited on the Pi and forgotten, both look like a clean
# send. Finding that out cost a checksum hunt against five commits on
# 2026-08-31, by hand, after the fact.
if [ "$DRY" = 0 ]; then
    say "Checksums (the repo's copy against the Pi's)"
    for f in zynthian_ctrldev_maschine_mk2.py techno_lib.py maschine_mk2_lib.py; do
        here=$(md5sum "$REPO/ctrldev/$f" | cut -d' ' -f1)
        there=$(ssh "$PI" "md5sum $CTRLDEV/$f" | cut -d' ' -f1)
        if [ "$here" = "$there" ]; then
            printf '  ok   %-38s %s\n' "$f" "$here"
        else
            printf '  FAIL %-38s repo %s  pi %s\n' "$f" "$here" "$there" >&2
            echo "The Pi is not running what this repository holds. Not restarting." >&2
            exit 1
        fi
    done
fi

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

# --- 4b. the Rust daemon, on request ------------------------------------------
# There is no cross-compile in this project: the daemon is built ON the Pi, by
# install.sh on a fresh one. But install.sh SKIPS the build when a binary
# already exists, so it will not refresh a daemon change - which is why this
# section exists, and why it verifies the binary actually moved. A failed build
# leaves the old binary in place and every check after a restart would then be
# testing the PREVIOUS daemon while looking like a pass.
if [ "$DAEMON" = 1 ]; then
    say "Daemon source -> the Pi, then build THERE"
    if [ "$DRY" = 1 ]; then
        echo "  [dry-run] ssh '$PI' systemctl show -p ExecStart --value maschine-mk2"
        echo "  [dry-run] scp '$REPO/daemon/src/'*.rs '$PI:<daemon>/src/'"
        echo "  [dry-run] scp Cargo.toml Cargo.lock '$PI:<daemon>/'"
        echo "  [dry-run] ssh '$PI' 'cd <daemon> && cargo build --release'   (minutes)"
        echo "  [dry-run] verify the binary's mtime moved, abort if it did not"
    else
        # Ask the unit where the binary is rather than guessing the repo path.
        # The path is rewritten by install.sh per machine, so it is the only
        # thing on the Pi that actually knows.
        EXEC=$(ssh "$PI" 'systemctl show -p ExecStart --value maschine-mk2' \
               | grep -o 'path=[^ ;]*' | head -1 | cut -d= -f2)
        [ -n "$EXEC" ] || { echo "cannot find the daemon's ExecStart on $PI" >&2; exit 1; }
        PIDAEMON="${EXEC%/target/release/maschine}"
        [ "$PIDAEMON" != "$EXEC" ] \
            || { echo "unexpected ExecStart path: $EXEC" >&2; exit 1; }
        echo "  daemon on the Pi: $PIDAEMON"

        BEFORE=$(ssh "$PI" "stat -c %Y '$EXEC' 2>/dev/null || echo 0")

        ssh "$PI" "mkdir -p '$PIDAEMON/src/base' '$PIDAEMON/src/devices/mk2'"
        scp -q "$REPO/daemon/src/"*.rs            "$PI:$PIDAEMON/src/"
        scp -q "$REPO/daemon/src/base/"*.rs       "$PI:$PIDAEMON/src/base/"
        scp -q "$REPO/daemon/src/devices/"*.rs    "$PI:$PIDAEMON/src/devices/"
        scp -q "$REPO/daemon/src/devices/mk2/"*.rs "$PI:$PIDAEMON/src/devices/mk2/"
        scp -q "$REPO/daemon/Cargo.toml" "$REPO/daemon/Cargo.lock" "$PI:$PIDAEMON/"
        echo "  sent daemon sources"

        echo "  building on the Pi - this takes minutes, do not interrupt"
        ssh "$PI" "cd '$PIDAEMON' && cargo build --release" \
            || { echo "BUILD FAILED on the Pi. The OLD binary is still in place and" >&2
                 echo "nothing was restarted. Fix it before deploying again." >&2; exit 1; }

        AFTER=$(ssh "$PI" "stat -c %Y '$EXEC' 2>/dev/null || echo 0")
        if [ "$BEFORE" = "$AFTER" ]; then
            echo "the binary's mtime did not change - the build produced nothing new." >&2
            echo "Refusing to restart into a daemon you have not actually deployed." >&2
            exit 1
        fi
        echo "  binary refreshed"
    fi
    echo "  NOT sent: maschine.json - it carries external_pad_leds and send_aftertouch"
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
# No devN_in on the Pads port means the driver never got a zmip slot - the rig
# then does nothing at all, with no error. More than one means a stale JACK
# route, which makes every pad tap play a phantom sound.
#
# Do NOT check for a "Loaded" line in the journal. Zynthian logs both "Found
# ctrldev driver" and "Loaded ctrldev driver" at INFO, and ZYNTHIAN_LOG_LEVEL
# defaults to WARNING, so neither is ever written on a stock rig - their absence
# proves nothing. Measured 2026-08-13. Any driver WARNING lines are shown below
# because those do come through, and they are worth seeing after a deploy.
if [ "$RESTART" = 1 ] && [ "$DRY" = 0 ]; then
    say "Verify"
    # NOT `grep -A3 "Pads MIDI"`. That form reports a HEALTHY rig as a broken
    # one: it matches the Pads port twice - once as a port, once as another
    # port's connection - and then prints unrelated ports that sit at the left
    # margin, so a working rig shows four devN_in lines under a header saying
    # "want exactly one". A verify step that cries wolf on every deploy trains
    # you to ignore the one check that catches a real duplicate route, and a
    # real duplicate route recurred on 2026-08-15. Indentation is the whole
    # distinction: a route is indented under its port, a port is not.
    echo "-- Pads MIDI routing (want exactly one devN_in):"
    ssh "$PI" 'jack_lsp -c | awk "/\(capture\): Pads MIDI/{f=1;next} /^[^ \t]/{f=0} f{print}"' \
        || echo "  (port not found)"
    echo "   two or more means a stale route - restart the daemon, then the UI"
    echo "-- driver warnings, if any (INFO is invisible at the default log level):"
    ssh "$PI" 'journalctl -u zynthian --since -2min | grep -i "ctrldev_maschine" | tail -5' \
        || echo "  (none - not an error)"
    echo
    echo "Then play it. Neither check above proves a note sounds."
fi
