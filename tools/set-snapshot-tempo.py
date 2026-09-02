#!/usr/bin/env python3
"""Set a snapshot's tempo, in both places that hold it, and prove nothing else moved.

A .zss carries the tempo TWICE and they must agree:

  1. the zynseq riff's `vers` block, bytes 4:6, big-endian uint16 - what the
     sequencer plays at
  2. `zs3/zs3-0/midi_capture/<ctrldev port>/ctrldev_state/globals/bpm` - what
     the driver restores on load

Writing one and not the other gives a snapshot whose surface disagrees with its
own sequencer, which is the family of bug this project has paid for repeatedly.

Why a tool rather than a one-line edit: it edits a SHIPPED artefact. The proof
that only the tempo moved is the point. After writing, this re-reads the file,
sets both fields back to the old values, and requires the result to be
byte-identical to the original - so any incidental reformatting, float repr
change or key reorder fails loudly instead of landing in a commit.

    tools/set-snapshot-tempo.py --tempo 125 snapshot/017-generative-techno.zss
    tools/set-snapshot-tempo.py --check snapshot/*.zss     # report, change nothing

At 48 kHz zynseq truncates frames-per-clock to a whole frame, so the error is
the fractional part of 30000/tempo and is ZERO only when the tempo divides
30000. --check prints it per file. See
notes/findings/2026-08-21-the-3896-ppm-is-zynseq-integer-truncation.md
"""
import argparse
import base64
import json
import os
import struct
import sys

# THE RIFF READER LIVES IN `zss_riff.py`, since 2026-09-02. There were three
# independent copies of it across four tools and they had already drifted -
# see that module's docstring for the table.
#
# THE sys.path LINE IS NOT DECORATION. A script's own directory is on the path
# when it is run as a script, and is NOT when it is loaded by
# `spec_from_file_location` - which is how the tests load these, because the
# filenames have dashes in them. Without it the import works from the command
# line and fails in the suite, which is the worst of both.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zss_riff import parse_blocks, build_blocks  # noqa: E402

TICKS_PER_BEAT = 1920
PPQN = 96
SAMPLE_RATE = 48000






def riff_tempo(blocks):
    for bid, body in blocks:
        if bid == "vers":
            return struct.unpack(">H", body[4:6])[0]
    raise ValueError("no vers block")


def set_riff_tempo(blocks, tempo):
    for bid, body in blocks:
        if bid == "vers":
            body[4:6] = struct.pack(">H", tempo)
            return
    raise ValueError("no vers block")


def globals_dict(d):
    """The driver's own state, or None if this snapshot has no ctrldev state."""
    for zs3 in (d.get("zs3") or {}).values():
        for port, cap in (zs3.get("midi_capture") or {}).items():
            state = (cap or {}).get("ctrldev_state")
            if isinstance(state, dict) and isinstance(state.get("globals"), dict):
                return state["globals"]
    return None


def drift_ppm(tempo, sample_rate=SAMPLE_RATE):
    """What zynseq's integer truncation costs at this tempo, in ppm."""
    exact = 60.0 * sample_rate / (tempo * TICKS_PER_BEAT) * (TICKS_PER_BEAT // PPQN)
    used = int(exact)
    return exact, used, (exact - used) / used * 1e6


# The shipped snapshots are not written the same way: 017 is compact on one
# line, 018 is pretty-printed with indent=2. Rewriting one in the other's style
# would reformat a 55 KB artefact and bury a two-byte change in a whole-file
# diff, so the file's own style is detected and reused. Nothing is written in a
# style that cannot reproduce the file it came from.
DUMP_STYLES = [
    dict(),
    dict(indent=2),
    dict(indent=4),
    dict(indent=1),
    dict(separators=(",", ":")),
]


def detect_style(text, d):
    """The json.dumps kwargs, and trailing newline, that reproduce `text`."""
    for style in DUMP_STYLES:
        for nl in ("", "\n"):
            if json.dumps(d, **style) + nl == text:
                return style, nl
    return None, None


def read(path):
    text = open(path, encoding="utf-8").read()
    d = json.loads(text)
    blocks = parse_blocks(base64.b64decode(d["zynseq_riff_b64"]))
    g = globals_dict(d)
    return text, d, blocks, g


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--tempo", type=int, help="new tempo in BPM")
    ap.add_argument("--check", action="store_true",
                    help="report each file's tempo and its drift; change nothing")
    a = ap.parse_args()

    if a.check:
        for path in a.files:
            _, _, blocks, g = read(path)
            t = riff_tempo(blocks)
            exact, used, ppm = drift_ppm(t)
            gb = None if g is None else g.get("bpm")
            agree = "" if gb in (None, t) else f"  ** globals/bpm={gb} DISAGREES **"
            print(f"{path:56} {t:>4} BPM  {exact:>9.4f} -> {used:<4} {ppm:>7.0f} ppm"
                  f"{'  EXACT' if ppm == 0 else ''}{agree}")
        return 0

    if a.tempo is None:
        ap.error("--tempo is required unless --check is given")
    tempo = a.tempo
    if not 20 <= tempo <= 400:
        ap.error(f"tempo {tempo} is outside 20-400")
    exact, used, ppm = drift_ppm(tempo)
    print(f"Target {tempo} BPM: frames/clock {exact:.4f} -> {used}, "
          f"{ppm:.0f} ppm{'  (EXACT)' if ppm == 0 else ''}")

    for path in a.files:
        text, d, blocks, g = read(path)
        old_riff = riff_tempo(blocks)
        old_bpm = None if g is None else g.get("bpm")

        style, nl = detect_style(text, d)
        if style is None:
            print(f"  {path}: REFUSED - this file's JSON formatting is not one this "
                  f"tool can reproduce, so writing it would reformat the whole "
                  f"snapshot", file=sys.stderr)
            return 1

        set_riff_tempo(blocks, tempo)
        d["zynseq_riff_b64"] = base64.b64encode(build_blocks(blocks)).decode("ascii")
        if g is not None:
            g["bpm"] = tempo
        new_text = json.dumps(d, **style) + nl

        # Prove that only the tempo moved: put both fields back and require the
        # bytes to match the file we read.
        chk = json.loads(new_text)
        chk_blocks = parse_blocks(base64.b64decode(chk["zynseq_riff_b64"]))
        set_riff_tempo(chk_blocks, old_riff)
        chk["zynseq_riff_b64"] = base64.b64encode(build_blocks(chk_blocks)).decode("ascii")
        chk_g = globals_dict(chk)
        if chk_g is not None and old_bpm is not None:
            chk_g["bpm"] = old_bpm
        if json.dumps(chk, **style) + nl != text:
            print(f"  {path}: REFUSED - a round trip does not reproduce the original "
                  f"byte for byte, so this edit would change more than the tempo",
                  file=sys.stderr)
            return 1

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)

        # The guard above proves nothing EXTRA changed. This proves the two
        # things that were supposed to change actually did - read back off
        # disk, not off the objects we just wrote. Skipping one of the two
        # fields is exactly the failure that makes a snapshot's surface
        # disagree with its own sequencer, and it passes a "nothing else
        # moved" check trivially.
        _, _, back_blocks, back_g = read(path)
        got_riff = riff_tempo(back_blocks)
        got_bpm = None if back_g is None else back_g.get("bpm")
        if got_riff != tempo or (old_bpm is not None and got_bpm != tempo):
            print(f"  {path}: WROTE THE WRONG THING - vers={got_riff} "
                  f"globals/bpm={got_bpm}, both should be {tempo}", file=sys.stderr)
            return 1

        bpm_note = "" if old_bpm is None else f", globals/bpm {old_bpm} -> {tempo}"
        print(f"  {path}: vers {old_riff} -> {tempo}{bpm_note}  verified on read-back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
