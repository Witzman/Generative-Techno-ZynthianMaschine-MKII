#!/usr/bin/env python3
"""Make a snapshot say it is itself, in the one field Zynthian reads it from.

A `.zss` carries `last_snapshot_fpath`, and every snapshot built from another
one inherits the SOURCE's value. 72 of the 73 shipped here claimed to be
`017-generative-techno`, including the factory snapshot `018` and every entry
in the genre and drone packs.

**When it bites.** `zynthian_state_manager.load_snapshot()` sets
`last_snapshot_fpath = fpath` when you load a snapshot by its own path - so
loading from the touchscreen shows the right name. But loading `last_state.zss`
takes the value from INSIDE the file, which is the boot path and the
stop/write/start path. So the rig comes up playing one snapshot and naming
another.

**Why it is not only cosmetic.** `get_next_filename()` appends
`basename(last_snapshot_fpath)` to every audio capture, so a jam recorded on
`101-dub-mutated` was written as `..._017-generative-techno.wav`. A mislabelled
recording is not recoverable by looking at it later.

Nothing writes back over the named file, so no snapshot was ever at risk of
being overwritten. This is a naming bug with a filing consequence.

    tools/fix-snapshot-identity.py --check snapshot/*.zss snapshot/*/*.zss
    tools/fix-snapshot-identity.py snapshot/genre-pack/101-dub-mutated.zss

Same discipline as `set-snapshot-tempo.py`, and for the same reason - these are
SHIPPED artefacts. After writing, the file is re-read, the field is put back to
its old value, and the result must be byte-identical to the original. Any
incidental reformatting or key reorder fails loudly here instead of landing in
a commit as a diff nobody can read.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atomic_write  # noqa: E402

# Where a snapshot lives on the Pi. The field is an absolute path on the
# target, not a path in this repo - bank 000 is where every installer puts
# them, and a snapshot at the snapshots root is invisible in the UI.
SNAP_DIR = "/zynthian/zynthian-my-data/snapshots/000"
FIELD = "last_snapshot_fpath"


def own_path(path):
    return f"{SNAP_DIR}/{os.path.basename(path)}"


def read(path):
    with open(path) as fh:
        return json.load(fh)


def write(path, doc):
    atomic_write.write_json(path, doc)


def check_one(path):
    doc = read(path)
    have = doc.get(FIELD, "")
    want = own_path(path)
    ok = have == want
    print(f"{path:58} {'ok' if ok else 'CLAIMS ' + os.path.basename(have or '(unset)')}")
    return ok


def fix_one(path):
    """Rewrite the field, then prove nothing else in the file moved."""
    with open(path, "rb") as fh:
        original = fh.read()
    doc = read(path)
    old, want = doc.get(FIELD, ""), own_path(path)
    if old == want:
        print(f"  {path}: already itself")
        return True

    doc[FIELD] = want
    write(path, doc)

    # The proof: put it back and require byte-identity with what we started
    # from. Anything else this write touched shows up here.
    #
    # IN MEMORY, since 2026-09-03. This used to write the comparison to
    # `<path>.verify` and unlink it, which left that file behind on any
    # interruption - beside the snapshot, matching no gitignore rule, and
    # looking exactly like a real one. `json.dumps` is the same serialiser
    # `write` uses, so the comparison is unchanged.
    again = read(path)
    again[FIELD] = old
    round_trip = json.dumps(again, indent=2).encode()
    if round_trip != original:
        # Restore and refuse: a file we cannot round-trip is a file we do not
        # understand well enough to edit.
        with open(path, "wb") as fh:
            fh.write(original)
        print(f"  {path}: REFUSED - round trip is not byte-identical, "
              f"nothing written", file=sys.stderr)
        return False
    print(f"  {path}: {os.path.basename(old) or '(unset)'} -> "
          f"{os.path.basename(want)}  verified on read-back")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report only, change nothing")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()

    if args.check:
        bad = [p for p in args.files if not check_one(p)]
        print(f"\n{len(args.files) - len(bad)} of {len(args.files)} name themselves")
        if bad:
            print(f"{len(bad)} do not - run without --check to fix")
        return 1 if bad else 0

    failed = [p for p in args.files if not fix_one(p)]
    print(f"\n{len(args.files) - len(failed)} of {len(args.files)} fixed or already correct")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
