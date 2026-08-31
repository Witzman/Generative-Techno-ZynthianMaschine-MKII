#!/usr/bin/env python3
"""Export a snapshot's eight patterns as a standard MIDI file.

    python3 tools/export-patterns-midi.py snapshot/018-generative-techno-main-insert.zss
    python3 tools/export-patterns-midi.py <snapshot.zss> -o /tmp/out.mid

It reads the SAVED SNAPSHOT, never the running instrument. Nothing is sent to
the rig, no service is touched, and it can run while a session is playing or
while the Pi is switched off - which is the whole reason it is a tool and not a
driver feature.

Output is one type-1 file: a tempo track, then one track per channel, each on
its own MIDI channel and named for its group.

TWO HONEST LIMITS, both declared rather than papered over.

Note LENGTH is not exported. The riff's duration field was never decoded - it
is not consistent across channels (0x190 on a gate-40 drum, 0x0fa00000 on a
gate-40 voice) and it never needed to be, because the drum chains are
LinuxSampler one-shots that play a sample to its end whether or not a note-off
arrives, and voice patterns are rewritten on load. Every note here is given a
uniform one-step gate. A uniform gate you are told about is worth more than a
duration invented from a field nobody has decoded.

Per-note PLAY CHANCE is not exported either. A step that plays four times in
five is not a thing a MIDI file can say, so the note is written as certain. The
file is what the pattern WOULD play with every chance at 100.
"""

import argparse
import base64
import json
import struct
import sys

# Measured on the rig's v10 riff, 2026-08-18. Neither number is in the v11
# spec's arithmetic; both were derived from block sizes and confirmed against
# musical content - pattern 10 decoded to steps 0, 4, 8, 12, a kick.
PATN_HEADER = 32
PATN_EVENT = 21

# Four beats of four. The driver can reach other lengths at other divisions,
# but every pattern a snapshot has ever carried is sixteen steps, and the
# builder that writes them hardcodes the same number.
STEPS = 16
STEPS_PER_BEAT = 4

PPQ = 96
TICKS_PER_STEP = PPQ // STEPS_PER_BEAT

GROUPS = ("A", "B", "C", "D", "E", "F", "G", "H")


# ---- the riff -------------------------------------------------------------

def parse_blocks(raw):
    blocks, off = [], 0
    while off + 8 <= len(raw):
        bid = raw[off:off + 4].decode("latin1")
        size = struct.unpack(">I", raw[off + 4:off + 8])[0]
        blocks.append([bid, bytearray(raw[off + 8:off + 8 + size])])
        off += 8 + size
    if off != len(raw):
        raise ValueError(f"riff has {len(raw) - off} trailing bytes")
    return blocks


def riff_tempo(blocks):
    for bid, body in blocks:
        if bid == "vers":
            return struct.unpack(">H", body[4:6])[0]
    raise ValueError("no vers block")


def read_patterns(blocks):
    """Eight lists of (step, note, velocity), one per channel, in file order."""

    out = []
    for bid, body in blocks:
        if bid != "patn":
            continue
        events = []
        for off in range(PATN_HEADER, len(body) - PATN_EVENT + 1, PATN_EVENT):
            ev = body[off:off + PATN_EVENT]
            if ev[12] != 0x90:
                # Not a note on. Guessing what else it might be would put
                # invented notes in a file somebody is about to trust.
                continue
            step = struct.unpack(">I", ev[0:4])[0]
            if step >= STEPS:
                raise ValueError(
                    f"event at step {step} in a {STEPS}-step pattern - this "
                    f"snapshot is not the shape this tool understands")
            events.append((step, ev[13], ev[14]))
        out.append(events)
    if len(out) != 8:
        raise ValueError(f"expected 8 patterns, found {len(out)}")
    return out


# ---- the MIDI file --------------------------------------------------------

def vlq(n):
    """A MIDI variable-length quantity."""
    if n < 0:
        raise ValueError("negative delta")
    out = bytearray([n & 0x7F])
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def read_vlq(data):
    n = 0
    for byte in data:
        n = (n << 7) | (byte & 0x7F)
        if not byte & 0x80:
            break
    return n


def track_events(events, channel):
    """(tick, message) pairs for one channel, sorted, note-offs included."""

    out = []
    for step, note, velo in events:
        tick = step * TICKS_PER_STEP
        out.append((tick, bytes([0x90 | channel, note, velo])))
        out.append((tick + TICKS_PER_STEP, bytes([0x80 | channel, note, 0])))
    # Sorted by tick, and by the message after it so a note-off never sorts
    # ahead of the note-on it belongs to on a shared tick.
    return sorted(out, key=lambda e: (e[0], e[1]))


def build_track(events, name, tempo=None):
    body = bytearray()
    body += vlq(0) + b"\xff\x03" + vlq(len(name)) + name.encode("ascii", "replace")
    if tempo is not None:
        us = round(60_000_000 / tempo)
        body += vlq(0) + b"\xff\x51\x03" + us.to_bytes(3, "big")
    last = 0
    for tick, msg in events:
        body += vlq(tick - last) + msg
        last = tick
    body += vlq(0) + b"\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def build_midi(patterns, tempo):
    tracks = [build_track([], "tempo", tempo=tempo)]
    for channel, events in enumerate(patterns):
        tracks.append(build_track(track_events(events, channel),
                                  f"Group {GROUPS[channel]}"))
    head = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), PPQ)
    return head + b"".join(tracks)


# ---- cli ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("snapshot")
    ap.add_argument("-o", "--out", help="default: the snapshot's name, .mid")
    args = ap.parse_args()

    with open(args.snapshot, encoding="utf-8") as fh:
        d = json.load(fh)
    if "zynseq_riff_b64" not in d:
        sys.exit(f"{args.snapshot}: no zynseq_riff_b64 - not a Zynthian snapshot")

    blocks = parse_blocks(base64.b64decode(d["zynseq_riff_b64"]))
    tempo = riff_tempo(blocks)
    patterns = read_patterns(blocks)

    out = args.out or (args.snapshot.rsplit(".", 1)[0] + ".mid")
    with open(out, "wb") as fh:
        fh.write(build_midi(patterns, tempo))

    total = sum(len(p) for p in patterns)
    print(f"{out}: {total} notes across 8 channels at {tempo} BPM")
    for i, events in enumerate(patterns):
        steps = ",".join(str(e[0]) for e in events) or "-"
        print(f"  Group {GROUPS[i]}  {len(events):2d} notes  steps {steps}")
    print("note lengths are a uniform one step; per-note chance is not exported")


if __name__ == "__main__":
    main()
