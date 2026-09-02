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
  voice and `mods` is empty - UNLESS the entry carries a `mods` list, which the
  drone and ambient packs do. Those are the opposite instrument: barely any
  pattern, everything moving.

* A channel plays as a voice only when `kinds` says so. _chain_kind() returns
  "drum" for channels 0-4 from the CHANNELS table and never looks at the loaded
  engine, so putting a synth on chain 1 does NOT make channel A a voice - the
  override is what does, and it is what SHIFT + GRID sets on the panel. An
  override with no matching voice parameters would come up on defaults, so
  `overrides` carries both.

* A modulator whose port does not exist is INERT, not an error: _mod_write()
  takes `span is None` as "skip". So binding cutoff on a synth that publishes no
  cutoff costs nothing - but it also does nothing, which is why level, reverb
  and delay carry the weight here. Those three always resolve: level is the
  mixer strip, reverb and delay are the two insert wets every chain has.
"""

import argparse
import base64
import copy
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

SFZ_BANK = "/zynthian/zynthian-data/soundfonts/sfz/Drum Machines"
DRUM_CHAINS = ["1", "2", "3", "4", "5"]      # Kick, Snare, Clap, Closed Hat, Open Hat
VOICE_CHAINS = ["6", "7", "8"]               # BASS, LEAD, PADS
CTRLDEV_PORT = "virtual:maschine.rs/Maschine MK2 Pads"
PATN_HEADER = 32                             # measured on the rig's v10 riff
PATN_EVENT = 21
STEPS = 16


# --- the zynseq RIFF -------------------------------------------------------





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

    # `overrides` turns a drum channel into a voice - the SHIFT + GRID gesture,
    # persisted. An entry may give that channel its own synth engine, or leave
    # it on LinuxSampler to be a sampler walked by a Turing register, which is
    # what the factory snapshot does with channel E.
    overrides = {int(k): v for k, v in (entry.get("overrides") or {}).items()}

    # --- drums: keep LS, switch the kit, take the notes from the scan --------
    drum_notes = []
    for i, cid in enumerate(DRUM_CHAINS):
        pid = proc_of(chains[cid])
        over = overrides.get(i)
        if over and over.get("engine"):
            # This chain stops being a sampler, so it has no kit and no kit
            # note - its pattern comes from the register instead.
            if chains[cid]["slots"][0][pid] != over["engine"]:
                chains[cid]["slots"][0] = {pid: over["engine"]}
                clear_processor(procs[pid])
            drum_notes.append(None)
            continue
        kit = entry["drums"]["kits"][i]
        if kit not in kit_notes:
            raise ValueError(f"{entry['file']}: kit {kit!r} is not usable")
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
    # A channel the entry overrides needs its voice parameters too, or it comes
    # up as a voice running whatever default_channel_state built.
    for channel, over in overrides.items():
        state["voices"][str(channel)] = {
            "register": over["register"],
            "length": over["length"],
            "rhythm_reg": over["rhythm_reg"],
            "random": 0,
            "rhythm": 0,
            "gate": over["gate"],
            "octave": over["octave"],
            "range": over["range"],
            "velo": over["velo"],
            "ring": [],
        }
    state["owners"] = {str(i): "gen" for i in range(8)}
    # Keyed "<channel>|<verb>", which is what set_state partitions back apart.
    # Absent means no modulation at all, which is the genre pack's brief.
    state["mods"] = {
        f"{m['channel']}|{m['verb']}": {
            "depth": m["depth"], "rate": m["rate"], "shape": m["shape"],
            "phase0": float(m.get("phase0", 0.0)), "base": m["base"],
            "seed": int(m.get("seed", 0)),
        }
        for m in (entry.get("mods") or [])
    }
    state["mod_seed"] = len(state["mods"])
    state["kinds"] = {str(k): "voice" for k in overrides}
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
        over = overrides.get(i)
        if over:
            # Behaving as a voice: the steps come from its register, and
            # _write_voice_pattern rewrites the notes on load anyway.
            steps = [s for s in range(STEPS) if over["rhythm_reg"] >> s & 1]
            patns[i][1] = set_pattern(patns[i][1], steps, 60, over["velo"], template)
            continue
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
        # A snapshot must say it is ITSELF. Every field here is inherited from
        # the base, and `last_snapshot_fpath` inherited unchanged is how 72 of
        # 73 shipped snapshots came to claim they were 017: Zynthian reads that
        # field - not the filename - when it restores last_state.zss, which is
        # the boot path, so the rig came up playing one snapshot and naming
        # another. It also lands in every audio capture's filename.
        # See tools/fix-snapshot-identity.py, which repaired the shipped files.
        d["last_snapshot_fpath"] = (
            "/zynthian/zynthian-my-data/snapshots/000/" + entry["file"] + ".zss")
        with open(path, "w") as fh:
            json.dump(d, fh, indent=2)
        written += 1
        print(f"  {entry['file']:28} {entry['genre']:11} {entry['tempo']:3} BPM  "
              f"{'/'.join(e.split('/')[-1] for e in entry['voices']['engines'])}")
    print(f"{written} snapshots -> {args.out}")


if __name__ == "__main__":
    main()
