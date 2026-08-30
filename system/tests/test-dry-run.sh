#!/usr/bin/env bash
#
# Tests for what --dry-run PRINTS. Both installers have one and both were
# trusted by eye. Runs on WSL, needs no Pi.
#
# The point is not that --dry-run exits 0. It is that the commands it names are
# the right ones in the right ORDER, that it names none of the ones it must
# never send, and that it genuinely runs nothing: ssh, scp, systemctl and
# apt-get are shadowed by poison stubs that exit 99 if called, so a dry run
# that actually executed something fails here rather than on somebody's rig.
#
# Run:  bash system/tests/test-dry-run.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || exit 1
REPO="$(cd "$HERE/../.." 2>/dev/null && pwd)"                     || exit 1
[ -f "$REPO/install.sh" ] || { echo "not in the repo: $REPO has no install.sh" >&2; exit 1; }

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; [ $# -gt 1 ] && printf '       %s\n' "$2"; }
head_() { printf '\n%s\n' "$1"; }

# Anything that would touch a machine. If a --dry-run calls one, it exits 99
# and every assertion about that run fails loudly.
POISON="ssh scp systemctl udevadm apt-get cargo install rsync"
BIN=$(mktemp -d); trap 'rm -rf "$BIN" "$FAKE"' EXIT
for c in $POISON; do
    printf '#!/bin/sh\necho "POISON: %s was actually run: $*" >&2\nexit 99\n' "$c" > "$BIN/$c"
    chmod 755 "$BIN/$c"
done

# has <label> <haystack> <pattern>   /   hasnt <label> <haystack> <pattern>
has()   { if grep -Eq -- "$3" <<<"$2"; then ok "$1"; else bad "$1" "no line matching /$3/"; fi; }
hasnt() { if grep -Eq -- "$3" <<<"$2"; then bad "$1" "unexpected: $(grep -Em1 -- "$3" <<<"$2")"; else ok "$1"; fi; }
# before <label> <haystack> <first-pattern> <second-pattern>
before() {
    local a b
    a=$(grep -n -Em1 -- "$3" <<<"$2" | cut -d: -f1)
    b=$(grep -n -Em1 -- "$4" <<<"$2" | cut -d: -f1)
    if [ -z "$a" ] || [ -z "$b" ]; then bad "$1" "one side absent (a=${a:-none} b=${b:-none})"
    elif [ "$a" -lt "$b" ]; then ok "$1"
    else bad "$1" "line $a is not before line $b"; fi
}

################################################################################
head_ "deploy-to-pi.sh --dry-run"
################################################################################
# --skip-tests because the unit suite is covered by its own runner; this is
# about what the script would SEND.
D=$(PATH="$BIN:$PATH" PI=root@10.0.0.9 bash "$REPO/tools/deploy-to-pi.sh" --dry-run --skip-tests 2>&1)
rc=$?
if [ $rc -eq 0 ]; then ok "exits 0"; else bad "exits 0" "rc=$rc
$D"; fi
has "says it is a dry run"          "$D" 'DRY RUN - nothing will be changed\.'
has "honours PI= for the target"    "$D" '^Target: +root@10\.0\.0\.9$'
has "names the repo"                "$D" '^Repository: '

# The three driver files, each backed up to .prev before it is overwritten, and
# none of them anywhere but the Pi's ctrldev directory.
CD=/zynthian/zynthian-ui/zyngine/ctrldev
for f in zynthian_ctrldev_maschine_mk2.py techno_lib.py maschine_mk2_lib.py; do
    has "$f is copied to .prev first" "$D" "\[dry-run\] ssh .*cp $CD/$f $CD/$f\.prev"
    has "$f is sent by scp"           "$D" "\[dry-run\] scp -q '.*/ctrldev/$f' '[^ ]*:$CD/$f'"
    before "$f: .prev is taken BEFORE the scp" "$D" \
           "cp $CD/$f $CD/$f\.prev" "scp -q '.*/ctrldev/$f'"
done
n=$(grep -c '\[dry-run\] scp -q' <<<"$D")
if [ "$n" = 3 ]; then ok "exactly three scp lines (got 3)"; else bad "exactly three scp lines" "got $n"; fi

# THE law of this rig. Daemon first, UI second, with the settle in between.
# Restarting the daemon alone leaves the driver bound to a dead zmip slot and
# the rig goes silent with no error in any log.
head_ "deploy-to-pi.sh restart order — daemon FIRST, UI second"
has    "restarts the daemon"                 "$D" '\[dry-run\] ssh .*systemctl restart maschine-mk2'
has    "restarts the UI"                     "$D" '\[dry-run\] ssh .*systemctl restart zynthian'
before "daemon is restarted BEFORE the UI"   "$D" 'systemctl restart maschine-mk2' 'systemctl restart zynthian'
before "the settle sits between the two"     "$D" 'systemctl restart maschine-mk2' '\[dry-run\] sleep 8'
before "the settle sits between the two (2)" "$D" '\[dry-run\] sleep 8' 'systemctl restart zynthian'

# maschine.json carries external_pad_leds. Overwriting the Pi's copy from here
# is a silent way to lose it, so this script must never send it - nor the units
# or the udev rule, which are install.sh's job.
head_ "deploy-to-pi.sh sends nothing that install.sh owns"
hasnt "never sends maschine.json"  "$D" 'maschine\.json'
hasnt "never sends a systemd unit" "$D" '\.service'
hasnt "never sends the udev rule"  "$D" '99-maschine\.rules'
# The UI ordering drop-in is a systemd file, so it is install.sh's to place.
hasnt "never sends the UI ordering drop-in" "$D" 'zynthian-maschine-order|10-maschine-order'
hasnt "never touches udev"         "$D" 'udevadm'

head_ "deploy-to-pi.sh flags"
S=$(PATH="$BIN:$PATH" bash "$REPO/tools/deploy-to-pi.sh" --dry-run --skip-tests --with-system 2>&1)
for f in maschine-jack-connect.sh maschine-clock-bridge.py maschine-clock-connect.sh; do
    has "--with-system sends $f" "$S" "\[dry-run\] scp -q '.*/system/$f' '[^ ]*:/usr/local/bin/$f'"
done
hasnt "--with-system still never sends maschine.json" "$S" 'scp.*maschine\.json'
has   "--with-system says what it withheld"           "$S" 'NOT sent: maschine\.json'

R=$(PATH="$BIN:$PATH" bash "$REPO/tools/deploy-to-pi.sh" --dry-run --skip-tests --no-restart 2>&1)
hasnt "--no-restart issues no restart" "$R" '\[dry-run\] ssh .*systemctl restart'
has   "--no-restart hands the order back to the reader" "$R" \
      'restart maschine-mk2.*sleep 8.*restart zynthian'

# --with-daemon exists because install.sh SKIPS the cargo build when a binary
# is already there, so nothing in the project refreshed a daemon change. The
# properties worth pinning are that it changes nothing on a dry run (cargo is a
# poison stub, so a real build here fails the run), that it finds the daemon's
# path by ASKING the unit rather than guessing, and that it still withholds
# maschine.json.
W=$(PATH="$BIN:$PATH" bash "$REPO/tools/deploy-to-pi.sh" --dry-run --skip-tests --with-daemon 2>&1)
has   "--with-daemon has a daemon section"          "$W" 'Daemon source -> the Pi'
has   "--with-daemon asks the UNIT where the daemon lives" "$W" \
      "\[dry-run\] ssh .*systemctl show -p ExecStart --value maschine-mk2"
has   "--with-daemon sends the Rust sources"        "$W" "\[dry-run\] scp .*/daemon/src/.*\.rs"
has   "--with-daemon sends the lockfile too"        "$W" "\[dry-run\].*Cargo\.lock"
has   "--with-daemon builds ON the Pi"              "$W" "\[dry-run\] ssh .*cargo build --release"
has   "--with-daemon verifies the binary moved"     "$W" "mtime moved, abort if it did not"
hasnt "--with-daemon still never sends maschine.json" "$W" 'scp.*maschine\.json'
has   "--with-daemon says why maschine.json is withheld" "$W" \
      'NOT sent: maschine\.json.*(external_pad_leds|send_aftertouch)'
before "--with-daemon builds BEFORE any restart"    "$W" 'cargo build --release' 'systemctl restart maschine-mk2'
hasnt "a plain deploy has no daemon section"        "$D" 'Daemon source -> the Pi'

PATH="$BIN:$PATH" bash "$REPO/tools/deploy-to-pi.sh" --dry-run --wat >/dev/null 2>&1
rc=$?
if [ $rc -eq 2 ]; then ok "an unknown flag exits 2"; else bad "an unknown flag exits 2" "rc=$rc"; fi

################################################################################
head_ "install.sh refuses to run off a Pi"
################################################################################
# The guard is a safety property worth pinning: the script installs into
# /zynthian and restarts services, and a laptop has neither.
G=$(PATH="$BIN:$PATH" ZYNTHIAN_ROOT="$BIN/nowhere" bash "$REPO/install.sh" --dry-run 2>&1)
rc=$?
if [ $rc -eq 1 ]; then ok "exits 1 with no ZynthianOS"; else bad "exits 1 with no ZynthianOS" "rc=$rc"; fi
has "says why"                 "$G" 'not a ZynthianOS install'
has "says where to run it"     "$G" 'Run this on the Pi, not on your laptop'
hasnt "prints no install step" "$G" '\[dry-run\]'

################################################################################
head_ "install.sh --dry-run against a fake ZynthianOS root"
################################################################################
FAKE=$(mktemp -d)
mkdir -p "$FAKE/zynthian-ui/zyngine/ctrldev" "$FAKE/zynthian-ui/zynautoconnect"
echo "Oram-2601-1 fake" > "$FAKE/build_info.txt"
: > "$FAKE/zynthian-ui/zynautoconnect/zynthian_autoconnect.py"

I=$(PATH="$BIN:$PATH" ZYNTHIAN_ROOT="$FAKE" bash "$REPO/install.sh" --dry-run 2>&1)
rc=$?
if [ $rc -eq 0 ]; then ok "exits 0"; else bad "exits 0" "rc=$rc
$I"; fi
has "reports the ZynthianOS build" "$I" '^ZynthianOS: Oram-2601-1 fake$'
has "says it is a dry run"         "$I" 'DRY RUN - nothing will be changed\.'

has "installs the udev rule"       "$I" "\[dry-run\] install -m 0644 '.*/system/99-maschine\.rules' /etc/udev/rules\.d/99-maschine\.rules"
has "reloads udev rules"           "$I" '\[dry-run\] udevadm control --reload-rules'
for f in maschine-jack-connect.sh maschine-clock-bridge.py maschine-clock-connect.sh; do
    has "installs $f in /usr/local/bin" "$I" "\[dry-run\] install -m 0755 '.*/system/$f' /usr/local/bin/$f"
done
for u in maschine-mk2.service maschine-clock.service maschine-web.service; do
    has "installs unit $u" "$I" "\[dry-run\] install -m 0644 '[^']*$u[^']*' /etc/systemd/system/$u"
done
has "installs the UI ordering drop-in" "$I" \
    "\\[dry-run\\] install -m 0644 -D '.*/system/zynthian-maschine-order\\.conf'.*zynthian\\.service\\.d/10-maschine-order\\.conf"
before "the drop-in is in place before daemon-reload" "$I" \
    '10-maschine-order\.conf' '\[dry-run\] systemctl daemon-reload'
has "enables the three units"      "$I" '\[dry-run\] systemctl enable maschine-mk2 maschine-web maschine-clock'
has "reloads systemd"              "$I" '\[dry-run\] systemctl daemon-reload'
for f in zynthian_ctrldev_maschine_mk2.py techno_lib.py maschine_mk2_lib.py; do
    has "installs driver $f" "$I" "\[dry-run\] install -m 0644 '.*/ctrldev/$f' '.*/zyngine/ctrldev/$f'"
done
has "patches zynautoconnect"       "$I" "\[dry-run\] python3 '.*/tools/patch-autoconnect-maschine\.py' '.*zynthian_autoconnect\.py'"
# One-time .bak baseline before the first overwrite, and never a second time.
has "takes a .bak of zynautoconnect" "$I" "\[dry-run\] cp '$FAKE/zynthian-ui/zynautoconnect/zynthian_autoconnect\.py' '.*\.bak'"

head_ "bootstrap.sh --dry-run: the factory snapshot is 018, with 017 beside it"
################################################################################
# The fresh-install path is the one nobody can rehearse: it runs once, on a Pi
# nobody has yet. So the snapshot it places is asserted here rather than
# discovered by a reader whose MAIN page is missing.
BFAKE=$(mktemp -d)
mkdir -p "$BFAKE/zynthian"
echo "Oram-2601-1 fake" > "$BFAKE/zynthian/build_info.txt"

B=$(PATH="$BIN:$PATH" ZYNTHIAN_ROOT="$BFAKE/zynthian" REPO_DIR="$REPO"     bash "$REPO/bootstrap.sh" --dry-run 2>&1)
rc=$?
if [ $rc -eq 0 ]; then ok "exits 0"; else bad "exits 0" "rc=$rc
$B"; fi
has "reports the ZynthianOS build"  "$B" '^== ZynthianOS: Oram-2601-1 fake$'
has "says it is a dry run"          "$B" 'DRY RUN - nothing will be changed\.'

# 018 is the factory snapshot: in the bank AND over default.zss.
has "puts 018 in bank 000"          "$B"     '\[dry-run\] install -m 0644 .*/snapshot/018-generative-techno-main-insert\.zss .*/snapshots/000/$'
has "makes 018 the default"         "$B"     '\[dry-run\] install -m 0644 .*/snapshot/018-generative-techno-main-insert\.zss .*/snapshots/default\.zss$'
# 017 is the way back from a master filter that ate the mix - present, never
# the default. Both halves matter, so both are asserted.
has "puts 017 in bank 000 too"      "$B"     '\[dry-run\] install -m 0644 .*/snapshot/017-generative-techno\.zss .*/snapshots/000/$'
hasnt "never makes 017 the default" "$B"     'install -m 0644 .*/snapshot/017-generative-techno\.zss .*default\.zss'
# A genre snapshot over default.zss would boot a fresh Pi into a fixed
# arrangement instead of the instrument.
hasnt "no genre snapshot as default" "$B"     'install .*/snapshot/(genre-pack|drone-ambient)/.*default\.zss'
has "names 018 in the closing help" "$B"     'bank 000 > 018-generative-techno-main-insert'
has "points at 017 as the way back" "$B" '017-generative-techno, in the same bank'
rm -rf "$BFAKE"

################################################################################
head_ "install.sh restart order — daemon FIRST, UI second"
has    "restarts the daemon"               "$I" '\[dry-run\] systemctl restart maschine-mk2'
has    "restarts the UI"                   "$I" '\[dry-run\] systemctl restart zynthian'
before "daemon is restarted BEFORE the UI" "$I" 'systemctl restart maschine-mk2' 'systemctl restart zynthian'
before "the settle sits between the two"   "$I" 'systemctl restart maschine-mk2' '\[dry-run\] sleep 8'
before "the settle sits between the two (2)" "$I" '\[dry-run\] sleep 8' 'systemctl restart zynthian'

head_ "install.sh hands the reader the checks that work"
# Both of these were published wrong for weeks and both were found by RUNNING
# them. The awk form distinguishes a route from a port by indentation; the
# grep -A3 form reports a healthy rig as broken.
has   "the route check uses the awk form" "$I" 'awk .*capture.*: Pads MIDI'
has   "it warns off grep -A3"             "$I" 'Do NOT use .grep -A3'
has   "it warns off the journal check"    "$I" 'Do not look for a "Loaded" line'
hasnt "it never suggests grep -A3 as the check" "$I" '^  jack_lsp -c \| grep -A3'

head_ "install.sh leaves an edited maschine.json alone"
# config.rs reads maschine.json from the daemon's working directory. A rig whose
# config has been edited by hand must survive a reinstall, so the template is
# copied only when the live file is absent.
if [ -f "$REPO/daemon/maschine.json" ]; then
    hasnt "does not overwrite an existing daemon/maschine.json" "$I" \
          "\[dry-run\] cp '.*/system/maschine\.json' '.*/daemon/maschine\.json'"
    has   "says it is already present"                          "$I" 'already present: daemon/maschine\.json'
else
    has "copies the template in when absent" "$I" \
        "\[dry-run\] cp '.*/system/maschine\.json' '.*/daemon/maschine\.json'"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
