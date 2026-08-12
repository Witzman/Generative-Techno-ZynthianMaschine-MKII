#!/usr/bin/env bash
# Re-copy the ctrldev driver and its tests from the development checkout.
# Development happens in ~/zynth/zynthian-ui on branch vangelis; this repo is a
# release target. Run this, then `git diff` - that diff IS the drift report.
set -eu

SRC="${1:-/home/witzman/zynth/zynthian-ui/zyngine/ctrldev}"
DST="$(cd "$(dirname "$0")/.." && pwd)/ctrldev"

[ -d "$SRC" ] || { echo "no such source: $SRC" >&2; exit 1; }

for f in zynthian_ctrldev_maschine_mk2.py techno_lib.py maschine_mk2_lib.py; do
    cp "$SRC/$f" "$DST/$f"
    echo "synced $f"
done
for f in test_techno_lib.py test_maschine_mk2_lib.py; do
    cp "$SRC/tests/$f" "$DST/tests/$f"
    echo "synced tests/$f"
done

echo
echo "Now run the suite and read the diff:"
echo "  (cd '$DST' && python3 -m unittest discover -s tests -q)"
echo "  git -C '$(dirname "$DST")' diff --stat ctrldev"
