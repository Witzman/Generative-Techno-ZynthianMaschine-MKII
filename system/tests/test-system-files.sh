#!/usr/bin/env bash
#
# Tests for system/ — the units, the udev rule, the helper scripts and the
# maschine.json template. Runs on WSL, needs no Pi and no hardware.
#
# Why this exists: every other test in this project is Python against
# techno_lib.py. Nothing checked system/ at all, so a typo in a unit or a bad
# ExecStart= path was caught by deploying it to the rig and watching it fail.
#
# The unit half builds a fake root under mktemp -d, stubs every binary any
# ExecStart=/ExecStartPost= names with /bin/true, writes a passwd/group so
# User= would resolve, and hands the lot to systemd-analyze verify. That is
# skipped, not failed, where systemd-analyze is absent.
#
# Run:  bash system/tests/test-system-files.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || exit 1
SYS="$(cd "$HERE/.." 2>/dev/null && pwd)"  || exit 1
REPO="$(cd "$SYS/.." 2>/dev/null && pwd)"  || exit 1
[ -f "$REPO/install.sh" ] || { echo "not in the repo: $REPO has no install.sh" >&2; exit 1; }

PASS=0; FAIL=0; SKIP=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; [ $# -gt 1 ] && printf '       %s\n' "$2"; }
skip() { SKIP=$((SKIP+1)); printf '  skip %s\n' "$1"; }
head_() { printf '\n%s\n' "$1"; }

# A missing file must FAIL every assertion about it. grep on an absent file
# also "finds nothing", which would make a no-match assertion pass.
have() { [ -f "$1" ] || { bad "$2" "no such file: $1"; return 1; }; }
# assert_grep <label> <pattern> <file>
assert_grep() {
    have "$3" "$1" || return
    if grep -Eq -- "$2" "$3"; then ok "$1"; else bad "$1" "no match for /$2/ in $(basename "$3")"; fi
}
# assert_no_grep <label> <pattern> <file>
assert_no_grep() {
    have "$3" "$1" || return
    if grep -Eq -- "$2" "$3"; then bad "$1" "unexpected match for /$2/ in $(basename "$3")"; else ok "$1"; fi
}
# assert_eq <label> <expected> <actual>
assert_eq() {
    if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected [$2], got [$3]"; fi
}

UNITS="maschine-mk2.service maschine-clock.service"

# ---------------------------------------------------------------- files exist
head_ "system/ ships what system/README.md says it does"
for f in 99-maschine.rules maschine.json README.md zynthian-maschine-order.conf \
         maschine-jack-connect.sh maschine-clock-connect.sh maschine-clock-bridge.py \
         $UNITS; do
    if [ -f "$SYS/$f" ]; then ok "$f present"; else bad "$f present" "missing"; fi
done

# --------------------------------------------------------- syntax of helpers
head_ "Helper scripts parse"
for f in maschine-jack-connect.sh maschine-clock-connect.sh; do
    if err=$(bash -n "$SYS/$f" 2>&1); then ok "bash -n $f"; else bad "bash -n $f" "$err"; fi
done
if command -v python3 >/dev/null 2>&1; then
    if err=$(python3 -m py_compile "$SYS/maschine-clock-bridge.py" 2>&1); then
        ok "py_compile maschine-clock-bridge.py"
    else
        bad "py_compile maschine-clock-bridge.py" "$err"
    fi
else
    skip "py_compile maschine-clock-bridge.py (no python3)"
fi

# maschine-jack-connect.sh must NOT connect the port. A second connection from
# here was the cause of the duplicate-route fault that made every pad tap fire
# twice; patched zynautoconnect owns the routing. It sets an alias only.
head_ "maschine-jack-connect.sh sets an alias and does not route"
assert_no_grep "no live jack_connect" '^[^#]*jack_connect' "$SYS/maschine-jack-connect.sh"
assert_no_grep "no live aconnect"     '^[^#]*[^_]aconnect'  "$SYS/maschine-jack-connect.sh"
assert_grep    "sets the JACK alias"  'set_alias\("virtual:maschine\.rs/'  "$SYS/maschine-jack-connect.sh"

# ------------------------------------------------------------- the udev rule
head_ "udev rule: /dev/maschine, and hotplug both ways"
RULES="$SYS/99-maschine.rules"
assert_eq "three rules, one per line" 3 "$(grep -c 'SUBSYSTEM=="hidraw"' "$RULES")"
# NARROWED 2026-09-04: matched on idVendor/idProduct alone until then, which
# claimed EVERY hidraw node the device presents. KERNELS on the HID parent
# encodes bus, vendor and product in one key on ONE parent - which is what
# makes it expressible at all, because udev requires every parent-matching key
# in a rule to resolve on the same parent and bInterfaceNumber does not.
assert_eq "every rule matches the MK2's HID interface" 3 \
    "$(grep -v '^#' "$RULES" | grep -c 'KERNELS=="0003:17CC:1140')"
# THE OLD FORM MUST NOT COME BACK. Reintroducing it would silently re-widen
# the rule, and nothing about the running rig would look different.
assert_eq "no rule matches on vendor/product alone" 0 \
    "$(grep -v '^#' "$RULES" | grep -c 'ATTRS{idVendor}')"
# AND bInterfaceNumber MUST NOT BE ADDED. Tested on the rig with `udevadm
# test`: combined with the ATTRS above it matches NOTHING, silently, leaving
# /dev/maschine absent and the instrument dead with no error anywhere.
# Comments are excluded on purpose: the rule file EXPLAINS why
# bInterfaceNumber cannot be used, so the word is in the file deliberately.
assert_eq "no rule mixes parents with bInterfaceNumber" 0 \
    "$(grep -v '^#' "$RULES" | grep -c 'bInterfaceNumber')"
assert_grep "symlink is /dev/maschine"  'SYMLINK\+="maschine"'      "$RULES"
assert_grep "mode 0664"                 'MODE="0664"'               "$RULES"
assert_grep "group audio"               'GROUP="audio"'             "$RULES"
assert_grep "add restarts the daemon"   'ACTION=="add".*restart maschine-mk2\.service'  "$RULES"
assert_grep "remove stops the daemon"   'ACTION=="remove".*stop maschine-mk2\.service'  "$RULES"
# --no-block or udev waits on systemd while systemd waits on udev.
assert_eq "both RUN+= use --no-block" 2 "$(grep -c 'systemctl --no-block' "$RULES")"

# ------------------------------------------------------- maschine.json template
head_ "maschine.json template"
JSON="$SYS/maschine.json"
if command -v python3 >/dev/null 2>&1; then
    out=$(python3 - "$JSON" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
pads, ccs = d["pad_notes"], d["encoder_ccs"]
print("pads_len", len(pads))
print("pads_perm", sorted(pads) == list(range(16)))
print("pads_first", pads[0])
print("ccs", ",".join(str(c) for c in ccs))
print("ext_leds", d["external_pad_leds"])
print("bright", d["screen_brightness"])
print("contrast", d["screen_contrast"])
PY
)   || { bad "maschine.json parses as JSON" "$out"; out=""; }
    if [ -n "$out" ]; then
        ok "maschine.json parses as JSON"
        assert_eq "16 pad notes"                16      "$(awk '/^pads_len/{print $2}'   <<<"$out")"
        assert_eq "pad notes are a permutation of 0-15" True "$(awk '/^pads_perm/{print $2}' <<<"$out")"
        # Step 0 is the TOP-LEFT pad, and the daemon's base makes that note 12.
        assert_eq "first pad note is 12 (top-left)" 12  "$(awk '/^pads_first/{print $2}' <<<"$out")"
        # Measured, not inferred. Never read an encoder CC off a token name.
        assert_eq "encoder CCs are 16-23"  "16,17,18,19,20,21,22,23" "$(awk '/^ccs/{print $2}' <<<"$out")"
        # Without this the daemon repaints pads on press and release in its own
        # colour, and the first touch destroys the per-channel picture.
        assert_eq "external_pad_leds is true" True      "$(awk '/^ext_leds/{print $2}'  <<<"$out")"
        # The panel's factory values, measured off the hardware 2026-08-31 via
        # GET_FEATURE 0xF8/0xF9. These are the RECOVERY values, and they are in
        # the template so a dark panel is fixed by restoring this file and
        # restarting the daemon - not by finding a number in a note somewhere.
        # The daemon skips the write when the device already holds them, so a
        # rig on the factory settings issues no HID feature write at all.
        # These fields are Non-volatile on the device: a bad write survives a
        # power cycle, which is why the shipped pair must stay the factory pair.
        assert_eq "screen_brightness is the factory 72" 72 "$(awk '/^bright/{print $2}'   <<<"$out")"
        assert_eq "screen_contrast is the factory 50"   50 "$(awk '/^contrast/{print $2}' <<<"$out")"
        # `ws_bind` and `internal_sequencer` LEFT this template on 2026-09-05
        # with the web editor and the internal sequencer. An existing rig's
        # maschine.json still carries both, and that must stay harmless:
        # MaschineConfig::load fails OPEN into the defaults on a parse error,
        # where external_pad_leds is false and the panel goes dark. A daemon
        # test pins that serde ignores the two rather than rejecting the file.
        assert_no_grep "ws_bind is gone from the template" \
            'ws_bind' "$REPO/system/maschine.json"
        assert_no_grep "internal_sequencer is gone from the template" \
            'internal_sequencer' "$REPO/system/maschine.json"
    fi
else
    skip "maschine.json checks (no python3)"
fi

# ------------------------------------------------------------ unit ordering
head_ "Unit ordering that the rig depends on"
assert_grep "daemon waits for jack2"        '^Requires=.*jack2\.service' "$SYS/maschine-mk2.service"
assert_grep "daemon is After jack2"         '^After=.*jack2\.service'    "$SYS/maschine-mk2.service"
assert_grep "clock bridge is After the daemon" '^After=.*maschine-mk2\.service' "$SYS/maschine-clock.service"
assert_grep "clock bridge only Wants the daemon" '^Wants=maschine-mk2\.service'  "$SYS/maschine-clock.service"
for u in $UNITS; do
    assert_grep "$u is WantedBy multi-user.target" '^WantedBy=multi-user\.target' "$SYS/$u"
    assert_grep "$u restarts"                     '^Restart='                    "$SYS/$u"
done
# THE law of this rig, now expressed in a unit rather than only in prose.
# Starting the daemon after the UI leaves the driver bound to a dead zmip slot
# and the rig goes silent with no error in any log.
head_ "The UI is ordered after the daemon"
DROPIN="$SYS/zynthian-maschine-order.conf"
assert_grep "drop-in orders the UI After the daemon" '^After=maschine-mk2\.service$'  "$DROPIN"
assert_grep "drop-in Wants the daemon"                '^Wants=maschine-mk2\.service$'  "$DROPIN"
# Requires= would tie the UI's fate to the daemon's, and the udev rule stops the
# daemon on unplug - so Requires would make unplugging the cable kill the rig.
assert_no_grep "drop-in does NOT Requires the daemon" '^Requires='  "$DROPIN"
# PartOf= would make a daemon stop stop the UI and a daemon restart restart it;
# the udev rule fires both on ordinary cable handling.
assert_no_grep "drop-in does NOT use PartOf"          '^PartOf='    "$DROPIN"
assert_no_grep "drop-in does NOT use BindsTo"         '^BindsTo='   "$DROPIN"
assert_grep    "drop-in only touches [Unit]"          '^\[Unit\]$'  "$DROPIN"
if [ "$(grep -c '^\[' "$DROPIN")" = 1 ]; then
    ok "drop-in has exactly one section"
else
    bad "drop-in has exactly one section" "$(grep '^\[' "$DROPIN" | tr '\n' ' ')"
fi
assert_grep "install.sh installs the drop-in" \
    'zynthian\.service\.d/10-maschine-order\.conf' "$REPO/install.sh"

# install.sh enables exactly these two.
head_ "install.sh enables exactly the units that ship"
enabled=$(grep -oP 'systemctl enable \K[^"]+' "$REPO/install.sh" | tr -s ' ' '\n' | grep -v '^$' | sort | tr '\n' ' ')
assert_eq "install.sh enables the two shipped units" \
    "maschine-clock maschine-mk2 " "$enabled"

# ------------------------------------------- install.sh rewrites every path
# The units ship with absolute paths under /root. install.sh rewrites them to
# wherever the repo was cloned. Nothing asserted that the sed expressions
# still match the templates, so a renamed field would silently install a unit
# pointing at a directory that does not exist.
head_ "install.sh's path rewrite still matches the templates"
FAKEREPO=/opt/gtzm-test
for f in $UNITS; do
    rewritten=$(sed -e "s#^ExecStart=.*/daemon/target/release/maschine#ExecStart=$FAKEREPO/daemon/target/release/maschine#" \
                    -e "s#^WorkingDirectory=.*/daemon\$#WorkingDirectory=$FAKEREPO/daemon#" \
                    -e "s#--directory .*/web#--directory $FAKEREPO/daemon/web#" \
                    "$SYS/$f")
    # Every absolute path the rewritten unit names must be inside the fake repo,
    # a system location, or Zynthian's own venv. A leftover /root path means the
    # sed missed it.
    have "$SYS/$f" "$f: no unrewritten /root or /home path" || continue
    strays=$(grep -oE '(/root|/home)[^ ]*' <<<"$rewritten" || true)
    if [ -z "$strays" ]; then
        ok "$f: no unrewritten /root or /home path"
    else
        bad "$f: no unrewritten /root or /home path" "$strays"
    fi
done

# ------------------------------------------------- systemd-analyze verify
head_ "systemd-analyze verify against a fake root"
if ! command -v systemd-analyze >/dev/null 2>&1; then
    skip "systemd-analyze verify (not installed)"
else
    FAKE=$(mktemp -d)
    trap 'rm -rf "$FAKE"' EXIT
    mkdir -p "$FAKE/etc/systemd/system" "$FAKE/usr/lib/systemd/system" "$FAKE/etc"
    # The distro's own units, so After=/Requires= on real targets resolve.
    for d in /usr/lib/systemd/system /lib/systemd/system; do
        [ -d "$d" ] && cp -a "$d/." "$FAKE/usr/lib/systemd/system/" 2>/dev/null
    done
    # User= and Group= must resolve inside the root.
    printf 'root:x:0:0:root:/root:/bin/bash\n'  > "$FAKE/etc/passwd"
    printf 'root:x:0:\naudio:x:29:\n'           > "$FAKE/etc/group"

    # Install the units exactly as install.sh would, rewritten to a path inside
    # the fake root, then stub every binary they name.
    STUBREPO="$FAKE/opt/gtzm"
    mkdir -p "$STUBREPO/daemon/web"
    for f in $UNITS; do
        sed -e "s#^ExecStart=.*/daemon/target/release/maschine#ExecStart=/opt/gtzm/daemon/target/release/maschine#" \
            -e "s#^WorkingDirectory=.*/daemon\$#WorkingDirectory=/opt/gtzm/daemon#" \
            -e "s#--directory .*/web#--directory /opt/gtzm/daemon/web#" \
            "$SYS/$f" > "$FAKE/etc/systemd/system/$f"
    done
    # Stub the first token of every Exec* line. /bin/true for all of them: this
    # verifies the unit, not the program.
    while read -r bin; do
        case "$bin" in
            /*) install -D -m 755 /bin/true "$FAKE$bin" ;;
        esac
    done < <(grep -hoP '^Exec[A-Za-z]*=-?\K/[^ ]+' "$FAKE"/etc/systemd/system/*.service | sort -u)

    verify_out=$(systemd-analyze --root="$FAKE" verify \
                    --recursive-errors=no --generators=no --man=no \
                    "$FAKE/etc/systemd/system/maschine-mk2.service" \
                    "$FAKE/etc/systemd/system/maschine-clock.service" 2>&1)
    rc=$?
    # Warnings about units outside the root's search path are noise here; a
    # non-zero exit or any line naming one of our own units is not.
    ours=$(grep -E 'maschine-(mk2|clock)\.service' <<<"$verify_out" || true)
    if [ $rc -eq 0 ] && [ -z "$ours" ]; then
        ok "systemd-analyze verify clean for both units"
    else
        bad "systemd-analyze verify clean for all three units" "rc=$rc ${ours:-$verify_out}"
    fi
fi

# ------------------------------------------------------------------- summary
printf '\n%d passed, %d failed, %d skipped\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" -eq 0 ]
