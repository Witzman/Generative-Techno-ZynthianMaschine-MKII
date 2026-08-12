#!/usr/bin/env bash
# Preflight for the Generative-Techno ZynthianMaschine MKII.
# Run ON THE PI. Prints one line per dependency; exits non-zero on any miss.
set -u

miss=0
ok()   { printf "  PRESENT  %s\n" "$1"; }
bad()  { printf "  MISSING  %s\n" "$1"; miss=$((miss+1)); }

echo "ZynthianOS"
if [ -f /zynthian/build_info.txt ]; then
    ok "$(head -1 /zynthian/build_info.txt)"
else
    bad "/zynthian/build_info.txt - is this a ZynthianOS install?"
fi

echo "LV2 plugins"
for pkg in obxd-lv2 padthv1-lv2 tap-lv2; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then ok "$pkg"; else bad "$pkg (apt install $pkg)"; fi
done
for b in /usr/lib/lv2/Obxd.lv2 /usr/lib/lv2/padthv1.lv2 \
         /usr/lib/lv2/tap-reverb.lv2 /usr/lib/lv2/tap-echo.lv2 \
         /zynthian/zynthian-plugins/lv2/JC303.lv2; do
    if [ -d "$b" ]; then ok "$b"; else bad "$b"; fi
done

echo "Drum kits"
KITS="/zynthian/zynthian-data/soundfonts/sfz/Drum Machines"
if [ -d "$KITS" ]; then
    n=$(find "$KITS" -maxdepth 1 -type f -name '*.sfz' 2>/dev/null | wc -l)
    if [ "$n" -gt 0 ]; then ok "$n SFZ kits in $KITS"; else bad "no .sfz files in $KITS"; fi
else
    bad "$KITS"
fi

echo "Driver"
for f in zynthian_ctrldev_maschine_mk2.py techno_lib.py maschine_mk2_lib.py; do
    if [ -f "/zynthian/zynthian-ui/zyngine/ctrldev/$f" ]; then ok "$f"; else bad "$f"; fi
done
if grep -q "maschine rs.*Pads MIDI" /zynthian/zynthian-ui/zynautoconnect/zynthian_autoconnect.py 2>/dev/null
then ok "zynautoconnect patched"
else bad "zynautoconnect NOT patched (run tools/patch-autoconnect-maschine.py)"
fi

echo "Services"
for u in maschine-mk2 maschine-web maschine-clock; do
    if systemctl is-active --quiet "$u"; then ok "$u active"; else bad "$u not active"; fi
done
if [ -e /dev/maschine ]; then ok "/dev/maschine"; else bad "/dev/maschine (udev rule, or the MK2 is unplugged)"; fi

echo "JACK routing"
pads=$(jack_lsp 2>/dev/null | grep -c "Pads MIDI")
if [ "$pads" -gt 0 ]; then ok "daemon MIDI port visible in JACK"; else bad "no 'Pads MIDI' port in JACK"; fi
taps=$(jack_lsp 2>/dev/null | grep -c TAP)
if [ "$taps" -eq 64 ]; then ok "64 TAP ports (16 inserts)"; else bad "$taps TAP ports, expected 64 - is the snapshot loaded?"; fi

echo "Snapshot"
SNAP=/zynthian/zynthian-my-data/snapshots/000/017-generative-techno.zss
if [ -f "$SNAP" ]; then ok "$SNAP"; else bad "$SNAP (section 5 copies it)"; fi

echo
if [ "$miss" -eq 0 ]; then echo "All dependencies present."; else echo "$miss missing."; fi
exit "$miss"
