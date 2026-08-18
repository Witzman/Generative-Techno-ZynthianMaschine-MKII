#!/usr/bin/env python3
"""Build the genre snapshot pack from a manifest, offline, on the .zss JSON.

    python3 tools/build-genre-snapshots.py \
        --manifest notes/design/<manifest>.json \
        --base snapshot/017-generative-techno.zss \
        --kits tools/drum-kit-notes.json \
        --out /tmp/genre-pack

Every snapshot is 017 with four things replaced: the five drum kits, the three
voice engines, the insert pair on every chain, and the driver's own state. The
patterns are rewritten in the zynseq RIFF.

WHY EACH PART IS THE WAY IT IS - these were measured, not assumed:

* DRUM patterns live in the RIFF and survive a load. VOICE patterns do not:
  set_state ends by calling _write_voice_pattern() for every voice, so anything
  this script writes into patterns 15-17 is overwritten within a second of
  loading. Voices are therefore authored as REGISTERS (`rhythm_reg` decides
  which steps sound, `register`+`length`+`octave`+`range` decide the pitches)
  and the notes this script writes for them are a courtesy, not the source of
  truth.

* Drum note numbers come from tools/drum-kit-notes.json, never from General
  MIDI. The kits do not share a note map and none of them is GM - see
  tools/scan-drum-kits.py. A wrong note is a silent channel.

* A drum note's DURATION does not matter and is copied from the template
  unexamined. The drum chains are LinuxSampler one-shots, which play a sample
  to its end whether or not the note-off arrives.

* Changing a chain's engine CLEARS that processor's controllers and nulls its
  bank/preset info. Obxd's 82 controller symbols mean nothing to Helm, and a
  preset_info pointing into the old plugin's bundle is worse than none. Proven
  on the rig 2026-08-16 before the first pack was built.

* preset_info[1] - the index - is IGNORED on restore. zynthian_processor's
  set_preset() gets a list, takes preset_info[0] as the id, and re-derives the
  index with find_preset_index_by_id(). The path is what selects the kit, so
  the index is written as 0 rather than faked.

* Evolution is forced OFF everywhere: `random` and `rhythm` are 0 on every
  voice and `mods` is empty. These snapshots are fixed arrangements.
"""

import argparse
import base64
import copy
import json
import os
import struct
import sys

SFZ_BANK = "/zynthian/zynthian-data/soundfonts/sfz/Drum Machines"
DRUM_CHAINS = ["1", "2", "3", "4", "5"]      # Kick, Snare, Clap, Closed Hat, Open Hat
VOICE_CHAINS = ["6", "7", "8"]               # BASS, LEAD, PADS
CTRLDEV_PORT = "virtual:maschine.rs/Maschine MK2 Pads"
PATN_HEADER = 32                             # measured on the rig's v10 riff
PATN_EVENT = 21
STEPS = 16


# --- the zynseq RIFF -------------------------------------------------------

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


def build_blocks(blocks):
    out = bytearray()
    for bid, body in blocks:
        out += bid.encode("latin1") + struct.pack(">I", len(body)) + body
    return bytes(out)


def make_event(template, step, note, velocity):
    """One note event. Only start, note and velocity are ours; every other
    byte - duration, the stutter fields, the per-note play chance - is copied
    from a template event the rig itself wrote."""
    ev = bytearray(template)
    ev[0:4] = struct.pack(">I", step)
    ev[13] = note & 0x7F          # value 1 start  = note
    ev[14] = max(1, min(127, velocity))
    ev[15] = note & 0x7F          # value 1 end    = the same note
    return ev


def set_pattern(body, steps, note, velocity, template):
    header = bytes(body[:PATN_HEADER])
    out = bytearray(header)
    for step in sorted(set(steps)):
        if not 0 <= step < STEPS:
            raise ValueError(f"step {step} outside 0..{STEPS - 1}")
        out += make_event(template, step, note, velocity)
    return out


def set_tempo(blocks, tempo):
    for bid, body in blocks:
        if bid == "vers":
            body[4:6] = struct.pack(">H", tempo)
            return
    raise ValueError("no vers block")


# --- the snapshot ----------------------------------------------------------

def proc_of(chain):
    slot = chain["slots"][0]
    if len(slot) != 1:
        raise ValueError(f"expected one processor in slot 0, got {slot}")
    return next(iter(slot))


def clear_processor(proc):
    """A processor whose plugin just changed keeps nothing from the old one."""
    proc["bank_info"] = None
    proc["bank_subdir_info"] = None
    proc["preset_info"] = None
    proc["preset_subdir_info"] = None
    proc["controllers"] = {}


def set_kit(proc, kit):
    proc["bank_info"] = [SFZ_BANK, None, "Drum Machines", None, "Drum Machines"]
    # Index 0 deliberately: it is re-derived from the path on restore.
    proc["preset_info"] = [f"{SFZ_BANK}/{kit}.sfz", 0, kit, "sfz", f"{kit}.sfz"]
    proc["preset_subdir_info"] = None


def build_one(base, entry, kit_notes):
    d = copy.deepcopy(base)
    zs3 = d["zs3"]["zs3-0"]
    procs = zs3["processors"]
    chains = d["chains"]

    zs3["title"] = entry["title"]

    # --- drums: keep LS, switch the kit, take the notes from the scan --------
    drum_notes = []
    for i, cid in enumerate(DRUM_CHAINS):
        kit = entry["drums"]["kits"][i]
        if kit not in kit_notes:
            raise ValueError(f"{entry['file']}: kit {kit!r} is not usable")
        pid = proc_of(chains[cid])
        set_kit(procs[pid], kit)
        drum_notes.append(kit_notes[kit][i])

    # --- voices: swap the engine, and wipe what belonged to the old one ------
    for i, cid in enumerate(VOICE_CHAINS):
        engine = entry["voices"]["engines"][i]
        pid = proc_of(chains[cid])
        if chains[cid]["slots"][0][pid] != engine:
            chains[cid]["slots"][0] = {pid: engine}
            clear_processor(procs[pid])

    # --- the insert pair on every chain -------------------------------------
    for cid, chain in chains.items():
        for slot_index, wanted in ((1, entry["fx"][0]), (2, entry["fx"][1])):
            if len(chain["slots"]) <= slot_index:
                continue
            slot = chain["slots"][slot_index]
            pid = next(iter(slot))
            if slot[pid] != wanted:
                chain["slots"][slot_index] = {pid: wanted}
                clear_processor(procs[pid])

    # --- the driver's own state ---------------------------------------------
    state = zs3["midi_capture"][CTRLDEV_PORT]["ctrldev_state"]
    state["globals"] = dict(state.get("globals") or {})
    state["globals"].update(bpm=entry["tempo"], root=entry["root"], scale=entry["scale"])
    v = entry["voices"]
    state["voices"] = {
        str(5 + i): {
            "register": v["register"][i],
            "length": v["length"][i],
            "rhythm_reg": v["rhythm_reg"][i],
            # Evolution OFF. These are fixed arrangements, by the owner's brief.
            "random": 0,
            "rhythm": 0,
            "gate": v["gate"][i],
            "octave": v["octave"][i],
            "range": v["range"][i],
            "velo": v["velo"][i],
            "ring": [],
        }
        for i in range(3)
    }
    state["owners"] = {str(i): "gen" for i in range(8)}
    state["mods"] = {}          # no automated modulation, by the owner's brief
    state["mod_seed"] = 0
    state["kinds"] = {}         # no kind overrides: drums stay drums, voices voices
    state["stash"] = {}         # nothing sleeping, so nothing stale to upgrade
    state["selected"] = 0

    # --- the patterns --------------------------------------------------------
    blocks = parse_blocks(base64.b64decode(d["zynseq_riff_b64"]))
    set_tempo(blocks, entry["tempo"])
    patns = [b for b in blocks if b[0] == "patn"]
    if len(patns) != 8:
        raise ValueError(f"expected 8 patterns in the base, found {len(patns)}")
    template = bytes(patns[0][1][PATN_HEADER:PATN_HEADER + PATN_EVENT])

    for i in range(5):                                   # drum channels A-E
        patns[i][1] = set_pattern(patns[i][1], entry["drums"]["steps"][i],
                                  drum_notes[i], entry["drums"]["velo"][i], template)
    for i in range(3):                                   # voice channels F-H
        steps = [s for s in range(STEPS) if v["rhythm_reg"][i] >> s & 1]
        # Overwritten by _write_voice_pattern on load; written anyway so the
        # file is never internally inconsistent with the registers beside it.
        patns[5 + i][1] = set_pattern(patns[5 + i][1], steps, 60, v["velo"][i], template)

    d["zynseq_riff_b64"] = base64.b64encode(build_blocks(blocks)).decode("ascii")
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--base", default="snapshot/017-generative-techno.zss")
    ap.add_argument("--kits", default="tools/drum-kit-notes.json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    base = json.load(open(args.base))
    kit_notes = json.load(open(args.kits))["notes"]
    manifest = json.load(open(args.manifest))
    os.makedirs(args.out, exist_ok=True)

    written = 0
    for entry in manifest:
        d = build_one(base, entry, kit_notes)
        path = os.path.join(args.out, entry["file"] + ".zss")
        with open(path, "w") as fh:
            json.dump(d, fh, indent=2)
        written += 1
        print(f"  {entry['file']:28} {entry['genre']:11} {entry['tempo']:3} BPM  "
              f"{'/'.join(e.split('/')[-1] for e in entry['voices']['engines'])}")
    print(f"{written} snapshots -> {args.out}")


if __name__ == "__main__":
    main()
