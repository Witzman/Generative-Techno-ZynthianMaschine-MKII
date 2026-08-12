#!/usr/bin/env bash
# Generative-Techno ZynthianMaschine MKII - installer.
# Runs exactly what guide/03-install-driver.md documents, in the same order.
# The guide is authoritative; this is a wrapper. --dry-run prints and changes
# nothing.
set -eu

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

REPO="$(cd "$(dirname "$0")" && pwd)"
CTRLDEV=/zynthian/zynthian-ui/zyngine/ctrldev
AUTOCONNECT=/zynthian/zynthian-ui/zynautoconnect/zynthian_autoconnect.py

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
if [ ! -f /zynthian/build_info.txt ]; then
    echo "This is not a ZynthianOS install (/zynthian/build_info.txt missing)." >&2
    echo "Run this on the Pi, not on your laptop." >&2
    exit 1
fi
echo "ZynthianOS: $(head -1 /zynthian/build_info.txt)"
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

# --- 2. build the daemon -------------------------------------------------------
say "Build the HID daemon (minutes - do not interrupt)"
if [ -x "$REPO/daemon/target/release/maschine" ]; then
    echo "  already built: daemon/target/release/maschine"
else
    run "cd '$REPO/daemon' && cargo build --release"
    run "cp '$REPO/daemon/picturetest.png' '$REPO/daemon/target/release/'"
fi

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
for f in maschine-jack-connect.sh maschine-clock-bridge.py maschine-clock-connect.sh; do
    run "install -m 0755 '$REPO/system/$f' /usr/local/bin/$f"
done

# --- 6. systemd units ---------------------------------------------------------
# The unit ships with an absolute path. Rewrite it to wherever this repository
# actually is, so a clone anywhere works rather than only under /root.
say "systemd units (daemon paths rewritten to $REPO)"
for f in maschine-mk2.service maschine-web.service maschine-clock.service; do
    tmp="/tmp/$f.gtzm"
    run "sed -e 's#^ExecStart=.*/daemon/target/release/maschine#ExecStart=$REPO/daemon/target/release/maschine#' \
             -e 's#^WorkingDirectory=.*/daemon\$#WorkingDirectory=$REPO/daemon#' \
             -e 's#--directory .*/web#--directory $REPO/daemon/web#' \
             '$REPO/system/$f' > '$tmp'"
    run "install -m 0644 '$tmp' /etc/systemd/system/$f"
done
run "systemctl daemon-reload"
run "systemctl enable maschine-mk2 maschine-web maschine-clock"

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
  journalctl -u zynthian --since -3min | grep -i ctrldev     # want "Loaded", not just "Found"
  jack_lsp -c | grep -A3 "Pads MIDI"                          # exactly one devN_in
EOF
