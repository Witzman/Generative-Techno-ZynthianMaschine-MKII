#!/usr/bin/env bash
# Generative-Techno ZynthianMaschine MKII - installer.
# Runs exactly what section 4 of the guide documents, in the same order.
# The guide is authoritative; this is a wrapper. --dry-run prints and changes
# nothing.
set -eu

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

REPO="$(cd "$(dirname "$0")" && pwd)"
# Everything Zynthian owns hangs off one prefix. It is /zynthian on a rig and
# is only ever overridden by system/tests/test-dry-run.sh, which points it at a
# fake root so --dry-run can be asserted off the Pi. The guard below still
# demands a real build_info.txt inside the prefix, so this does not make the
# installer runnable anywhere it was not runnable before.
ZYNTHIAN_ROOT="${ZYNTHIAN_ROOT:-/zynthian}"
CTRLDEV=$ZYNTHIAN_ROOT/zynthian-ui/zyngine/ctrldev
AUTOCONNECT=$ZYNTHIAN_ROOT/zynthian-ui/zynautoconnect/zynthian_autoconnect.py

# `run` builds a command line as a STRING and evals it, because several steps
# need a redirect or a `cd &&`. That is safe exactly as long as the paths going
# into it cannot re-quote the line, so it is checked once here rather than
# hoped about: a repository path containing a space, a quote, a backtick or a $
# would either break the eval or, worse, execute part of itself.
case "$REPO$ZYNTHIAN_ROOT" in
    *[\'\"\`\$\ ]*)
        echo "Refusing to run: a path here contains a space or a shell" >&2
        echo "metacharacter, and this script builds command lines as text." >&2
        echo "  repo:     $REPO" >&2
        echo "  zynthian: $ZYNTHIAN_ROOT" >&2
        exit 1
        ;;
esac

say() { printf "\n== %s\n" "$1"; }
run() {
    if [ "$DRY" = 1 ]; then printf "  [dry-run] %s\n" "$*"; else printf "  %s\n" "$*"; eval "$@"; fi
}
backup() {
    [ -f "$1" ] || return 0
    [ -f "$1.bak" ] && return 0
    run "cp '$1' '$1.bak'"
}

# --- refuse to run anywhere but a ZynthianOS Pi --------------------------------
if [ ! -f "$ZYNTHIAN_ROOT/build_info.txt" ]; then
    echo "This is not a ZynthianOS install ($ZYNTHIAN_ROOT/build_info.txt missing)." >&2
    echo "Run this on the Pi, not on your laptop." >&2
    exit 1
fi
echo "ZynthianOS: $(head -1 "$ZYNTHIAN_ROOT/build_info.txt")"
echo "Repository: $REPO"
[ "$DRY" = 1 ] && echo "DRY RUN - nothing will be changed."

# --- 1. packaged LV2 plugins ---------------------------------------------------
say "LV2 plugins from Debian"
for pkg in obxd-lv2 padthv1-lv2 tap-lv2; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then
        echo "  already installed: $pkg"
    else
        run "apt-get install -y $pkg"
    fi
done

# --- 1b. the Rust toolchain ---------------------------------------------------
# MEASURED 2026-09-20, after a fresh install off a clean ZynthianOS reported the
# failure. `apt install rustc cargo` on Bookworm gives cargo 1.65, and 1.65
# cannot even READ daemon/Cargo.lock:
#     error: failed to parse lock file at: .../daemon/Cargo.lock
#     Caused by: lock file version `4` was found, but this version of Cargo
#     does not understand this lock file
# Rewriting the lock back to version 3 does NOT rescue it - the pinned tree
# under tungstenite reaches idna_adapter, which is edition 2024. Measured on
# x86_64: 1.65 cannot parse the lock, 1.85 cannot resolve (icu_* and
# idna_adapter demand rustc 1.86), 1.86 builds clean. So the toolchain comes
# from rustup, and Debian's is removed first: two cargos on PATH is how this
# error comes back with no visible reason.
RUST_MIN_MINOR=86
# `set -e` is on, so this is an `if` and not an `&&`: a missing ~/.cargo/bin
# would end the installer on a true statement about a fresh Pi.
CARGO_HOME_BIN="${HOME:-/root}/.cargo/bin"
if [ -d "$CARGO_HOME_BIN" ]; then PATH="$CARGO_HOME_BIN:$PATH"; fi

cargo_version() { cargo --version 2>/dev/null | awk '{print $2}'; }
# 0 = cargo is absent or older than 1.$RUST_MIN_MINOR, i.e. rustup is needed.
cargo_too_old() {
    command -v cargo >/dev/null 2>&1 || return 0
    v=$(cargo_version); [ -n "$v" ] || return 0
    maj=${v%%.*}; rest=${v#*.}; min=${rest%%.*}
    case "$maj:$min" in *[!0-9:]*|:*|*:) return 0 ;; esac
    [ "$maj" -gt 1 ] && return 1
    [ "$maj" -eq 1 ] && [ "$min" -ge "$RUST_MIN_MINOR" ] && return 1
    return 0
}

say "Rust toolchain (cargo 1.$RUST_MIN_MINOR or newer - Debian's is 1.65 and cannot build this)"
if [ "$DRY" = 1 ]; then
    echo "  [dry-run] cargo --version, and IF it is absent or older than 1.$RUST_MIN_MINOR:"
    run "apt-get remove -y rustc cargo"
    run "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal"
    echo "  [dry-run] PATH=\$HOME/.cargo/bin:\$PATH, then re-check the version"
elif cargo_too_old; then
    have=$(cargo_version)
    echo "  cargo is ${have:-absent}, need 1.$RUST_MIN_MINOR or newer - installing rustup"
    for p in rustc cargo; do
        if dpkg -s "$p" >/dev/null 2>&1; then run "apt-get remove -y $p"; fi
    done
    run "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal"
    PATH="$CARGO_HOME_BIN:$PATH"
    hash -r 2>/dev/null || true
    if cargo_too_old; then
        have=$(cargo_version)
        echo "rustup ran and cargo is still ${have:-absent}. Stopping before the" >&2
        echo "build, which would fail on the lock file. Open a new shell, check" >&2
        echo "'cargo --version', and run this script again." >&2
        exit 1
    fi
    echo "  now: $(cargo --version)"
else
    echo "  already present: $(cargo --version)"
fi

# --- 2. build the daemon -------------------------------------------------------
# ALWAYS, since 2026-09-03. This used to skip the build when a binary already
# existed and print "already built", so re-running the installer after a git
# pull left the OLD daemon in place and said nothing - the reason
# deploy-to-pi.sh needed a --with-daemon of its own. cargo is incremental: with
# nothing to do this costs a second and prints "Finished".
say "Build the HID daemon (minutes on a fresh clone - do not interrupt)"
run "cd '$REPO/daemon' && cargo build --release"

# --- 3. daemon config ----------------------------------------------------------
say "Daemon config (external_pad_leds must be true)"
if [ -f "$REPO/daemon/maschine.json" ]; then
    echo "  already present: daemon/maschine.json"
else
    run "cp '$REPO/system/maschine.json' '$REPO/daemon/maschine.json'"
fi

# --- 4. udev ------------------------------------------------------------------
say "udev rule: /dev/maschine plus hotplug restart"
run "install -m 0644 '$REPO/system/99-maschine.rules' /etc/udev/rules.d/99-maschine.rules"
run "udevadm control --reload-rules"
run "udevadm trigger --subsystem-match=hidraw"

# --- 5. helper scripts ---------------------------------------------------------
say "Helper scripts in /usr/local/bin"
for f in maschine-jack-connect.sh maschine-clock-bridge.py maschine-clock-connect.sh \
         maschine-plugin-guis.sh maschine-vnc-ui.sh; do
    run "install -m 0755 '$REPO/system/$f' /usr/local/bin/$f"
done

# --- 6. systemd units ---------------------------------------------------------
# The unit ships with an absolute path. Rewrite it to wherever this repository
# actually is, so a clone anywhere works rather than only under /root.
say "systemd units (daemon paths rewritten to $REPO)"
# A PRIVATE DIRECTORY, not /tmp/<unit>.gtzm. That name was predictable and
# world-writable, and root then installed whatever was at it into
# /etc/systemd/system - so any local account could have pre-created it (or won
# the race) and had its own unit file installed as a system service. mktemp -d
# makes a 0700 directory nobody else can reach.
UNITDIR=$(mktemp -d)
trap 'rm -rf "$UNITDIR"' EXIT
for f in maschine-mk2.service maschine-clock.service maschine-vnc-ui.service; do
    tmp="$UNITDIR/$f"
    run "sed -e 's#^ExecStart=.*/daemon/target/release/maschine#ExecStart=$REPO/daemon/target/release/maschine#' \
             -e 's#^WorkingDirectory=.*/daemon\$#WorkingDirectory=$REPO/daemon#' \
             -e 's#--directory .*/web#--directory $REPO/daemon/web#' \
             '$REPO/system/$f' > '$tmp'"
    run "install -m 0644 '$tmp' /etc/systemd/system/$f"
done
# The UI must start after the daemon. A drop-in rather than an edit to
# zynthian.service: the unit is Zynthian's, and a drop-in survives a ZynthianOS
# update by construction - unlike the zynautoconnect patch, there is nothing to
# re-run afterwards.
say "Order the UI after the daemon (drop-in, does not touch zynthian.service)"
run "install -m 0644 -D '$REPO/system/zynthian-maschine-order.conf' \
         /etc/systemd/system/zynthian.service.d/10-maschine-order.conf"

run "systemctl daemon-reload"
run "systemctl enable maschine-mk2 maschine-clock maschine-vnc-ui"

# --- 6b. plugin GUIs off ------------------------------------------------------
# MEASURED, 2026-09-07: a plugin Zynthian hosts in jalv.gtk3 (because it ships
# an LV2 UI) and that a modulator writes to spins its GTK idle loop at ~70-80 %
# of a core doing no audio work - 031-house-classic cost 189.3 % of a core with
# the GUIs on and 97.2 % with them off, the modulated instance falling from
# 80.1 % to its siblings' 10 %. Eight of the twelve pack effects carry a UI and
# 50 of the 71 presets aim a modulator at one.
#
# The lever is Zynthian's own config, not a patch: config_remote_display()
# picks jalv.gtk3 only while vncserver1 is running. vncserver0 - the UI on
# :6080 - takes no part in that choice, and maschine-vnc-ui.service keeps it up.
#
# Reactivation is one command, and the guide says so: maschine-plugin-guis.sh on
say "Plugin GUIs off (frees ~0.7 of a core per modulated GUI-hosted plugin)"
run "/usr/local/bin/maschine-plugin-guis.sh off"

# --- 7. the ctrldev driver ----------------------------------------------------
say "ctrldev driver files"
for f in zynthian_ctrldev_maschine_mk2.py techno_lib.py maschine_mk2_lib.py; do
    backup "$CTRLDEV/$f"
    run "install -m 0644 '$REPO/ctrldev/$f' '$CTRLDEV/$f'"
done

# --- 8. the one core patch ----------------------------------------------------
say "Patch zynautoconnect (idempotent)"
backup "$AUTOCONNECT"
run "python3 '$REPO/tools/patch-autoconnect-maschine.py' '$AUTOCONNECT'"
# The second edit to the same file: every chain's MIDI also leaves by the
# MK2's DIN OUT socket. No second .bak - the one taken above is the baseline.
run "python3 '$REPO/tools/patch-autoconnect-din-out.py' '$AUTOCONNECT'"

# --- 9. restart, daemon FIRST -------------------------------------------------
say "Restart: daemon first, UI second"
echo "  Order matters. Restarting the daemon alone makes a2j re-register its"
echo "  port on a new zmip slot while the driver stays bound to the dead one,"
echo "  and the rig goes silent with no error."
run "systemctl restart maschine-mk2"
run "sleep 8"
run "systemctl restart zynthian"

# --- 10. hand back to the guide ----------------------------------------------
say "Verify (this script does not verify anything itself)"
cat <<'EOF'
  bash tools/check-prereqs.sh

  # exactly one ZynMidiRouter:devN_in under the Pads port
  jack_lsp -c | awk '/\(capture\): Pads MIDI/{f=1;next} /^[^ \t]/{f=0} f{print}'

  Two or more means a stale route: restart the daemon, then the UI.

  Do NOT use `grep -A3 "Pads MIDI"`. That form reports a HEALTHY rig as a broken
  one: it matches the Pads port twice - once as a port, once as another port's
  connection - and then prints unrelated ports that sit at the left margin, so a
  working rig shows four devN_in lines under a header saying "want exactly one".
  Indentation is the whole distinction: a route is indented under its port, a
  port is not. Measured on the rig 2026-08-15.

  Do not look for a "Loaded" line in the journal either. Zynthian logs it at
  INFO and ZYNTHIAN_LOG_LEVEL defaults to WARNING, so it is never written on a
  stock rig whether the driver bound or not. The JACK route above is the real
  check.
EOF
