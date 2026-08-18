#!/usr/bin/env python3
"""Map every SFZ kit in LinuxSampler's "Drum Machines" bank to the five notes
the instrument's drum channels play.

Run ON THE PI - it reads the sample set, which is not in this repository:

    scp tools/scan-drum-kits.py root@<pi>:/tmp/
    ssh root@<pi> 'python3 /tmp/scan-drum-kits.py' > tools/drum-kit-notes.json

Why this exists: the kits DO NOT share a note map, and none of them is General
MIDI. Roland TR909 is kick 36 / snare 40 / clap 50 / closed hat 42 / open hat
46; Yamaha RX11 puts its clap at 64; Korg DDD1 calls its kick "bass1" and
Alesis HR16 calls it "kik". Writing a snapshot with a hardcoded GM map silences
whichever channels guessed wrong, and a silent channel with the surface
reporting it healthy is the one failure this instrument must not produce.

The classifier reads the SAMPLE FILE NAMES, because that is the only thing that
says what a region is. Three ordering rules are load-bearing:

  1. Separators are normalised first. The names use "hat_closed" and "hat_open"
     with underscores; a pattern expecting whitespace matches neither, which
     silently excluded TR909 and TR808 - the two most important kits here.
  2. Open hat is matched BEFORE closed hat. The closed-hat patterns end in a
     bare "hat" catch-all, which would otherwise swallow every open hat.
  3. A missing role borrows from a named neighbour rather than falling back to
     "some region" - a clap borrowing the snare is a musical choice, a clap
     landing on whatever note sorted lowest is a bug that sounds like a kick.

A kit that cannot cover all five roles is EXCLUDED rather than faked."""

import json
import os
import re
import sys

BANK = "/zynthian/zynthian-data/soundfonts/sfz/Drum Machines"

# The order the instrument's channels are in: A KICK, B SNAR, C CLAP, D CHAT, E OHAT.
ORDER = ["kick", "snare", "clap", "chat", "ohat"]
# The order they are MATCHED in, which is deliberately different - see rule 2.
MATCH_ORDER = ["kick", "snare", "clap", "ohat", "chat"]

PATTERNS = {
    "kick":  [r"kick", r"\bkik", r"\bbd\d*\b", r"bd\d{6}", r"bass ?drum", r"bass ?\d+"],
    "snare": [r"snare", r"\bsnr\b", r"sn\b", r"sd ?\d*", r"(lite|med|hevy) +sn"],
    "clap":  [r"clap", r"finger ?sn", r"hand ?clap", r"\bcp\d*\b"],
    "ohat":  [r"op ?hat", r"open ?hat", r"hat ?open", r"hat ?long", r"ophh", r"ohh",
              r"\bohat\b", r"open ?hh", r"hat ?o\b"],
    "chat":  [r"cl ?hat", r"closed ?hat", r"hat ?closed", r"hat ?med", r"clhh", r"chh",
              r"closed ?hh", r"hihat", r"\bhh ?\d*\b", r"\bhat\b"],
}
# Only ever borrow from something musically adjacent.
FALLBACK = {"clap": ["snare"], "ohat": ["chat"], "chat": ["ohat"], "snare": ["clap"], "kick": []}


def normalise(name):
    return re.sub(r"[_\-]+", " ", name)


def regions_of(path):
    """(note, sample name) for every region. Accepts lokey= and key=; kits use both."""
    text = open(path, errors="ignore").read()
    out = []
    for block in text.split("<region>")[1:]:
        sample = re.search(r"sample=([^\r\n]+)", block)
        key = re.search(r"lokey=(\d+)", block) or re.search(r"\bkey=(\d+)", block)
        if sample and key:
            name = sample.group(1).strip().replace("\\", "/").split("/")[-1].lower()
            out.append((int(key.group(1)), name))
    return out


def main():
    bank = sys.argv[1] if len(sys.argv) > 1 else BANK
    notes, borrowed, excluded = {}, {}, {}
    for entry in sorted(os.listdir(bank)):
        if not entry.endswith(".sfz"):
            continue
        kit, full = entry[:-4], os.path.join(bank, entry)
        if os.path.isdir(full):
            # One kit ships as a directory with the .sfz inside it.
            inner = [f for f in sorted(os.listdir(full)) if f.endswith(".sfz")]
            if not inner:
                continue
            full = os.path.join(full, inner[0])
        regions = regions_of(full)
        if not regions:
            continue
        found, subs = {}, []
        for role in MATCH_ORDER:
            for note, name in regions:
                if any(re.search(p, normalise(name)) for p in PATTERNS[role]):
                    found[role] = note
                    break
        for role in MATCH_ORDER:
            if role in found:
                continue
            for alt in FALLBACK[role]:
                if alt in found:
                    found[role] = found[alt]
                    subs.append(f"{role}<-{alt}")
                    break
        missing = [r for r in ORDER if r not in found]
        if missing:
            excluded[kit] = missing
            continue
        notes[kit] = [found[r] for r in ORDER]
        if subs:
            borrowed[kit] = subs
    json.dump({"notes": notes, "borrowed": borrowed, "excluded": excluded},
              sys.stdout, indent=1, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
