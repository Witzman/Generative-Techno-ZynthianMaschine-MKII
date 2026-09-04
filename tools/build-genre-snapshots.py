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
import atomic_write  # noqa: E402

# THE DIVISIONS TABLE IS THE DRIVER'S, NOT A COPY. A voice channel is
# re-stamped to DIVISIONS[div][1] and [2] on every pattern rewrite - which
# happens within a second of every snapshot load - so a second copy here that
# drifted would produce a file that rewrites itself into disagreement.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ctrldev"))
from maschine_mk2_lib import maschine_mk2_lib as lib  # noqa: E402

SFZ_BANK = "/zynthian/zynthian-data/soundfonts/sfz/Drum Machines"
DRUM_CHAINS = ["1", "2", "3", "4", "5"]      # Kick, Snare, Clap, Closed Hat, Open Hat
VOICE_CHAINS = ["6", "7", "8"]               # BASS, LEAD, PADS
CTRLDEV_PORT = "virtual:maschine.rs/Maschine MK2 Pads"
PATN_HEADER = 32                             # measured on the rig's v10 riff
PATN_EVENT = 21
STEPS = 16

# THE patn HEADER, FIELD BY FIELD. Taken from zynseq.cpp's own writer
# (`fwrite("patnxxxx", ...)` onward) rather than guessed, because three of
# these are four-byte fixed point and a slice off by two bytes is a value that
# still parses. Offsets are into the block BODY, after the 8-byte id+length.
#
#   0-3   pattern id (u32)          16-18  swingAmount (BCD)
#   4-7   beatsInPattern (u32)      19-22  humanTime   (BCD)
#   8-9   stepsPerBeat (u16)        23-26  humanVelo   (BCD)
#   10    scale                     27-30  playChance  (BCD)
#   11    tonic                     31     pad
#   12    refNote
#   13    quantizeNotes
#   14    swingDiv
PATN_BEATS = 4
PATN_SPB = 8
PATN_SWING_DIV = 14
PATN_SWING_AMT = 15
PATN_HUMAN_TIME = 19
PATN_HUMAN_VELO = 23
PATN_CHANCE = 27

# DO NOT WRITE swingDiv FROM A MANIFEST. `_force_swing_div()` in the driver
# loops all eight patterns and sets it to 1, from init() AND from the
# snapshot-restore handler - so a 2 or a 4 written here is overwritten within a
# second of loading, in silence. Only the 16th shuffle exists on this
# instrument, and swingAmount is the half that survives.
# See notes/findings/2026-09-04-the-preset-packs-are-one-preset.md.
FORCED_SWING_DIV = 1


# --- the zynseq RIFF -------------------------------------------------------





def write_bcd(body, offset, value):
    """zynseq's four-byte fixed point: big-endian u16 of the fraction x 10000,
    then u16 of the whole units (`fileWriteBCD`). Not decimal BCD at all,
    despite the name upstream gives it."""
    value = max(0.0, float(value))
    units = int(value)
    frac = int(round((value - units) * 10000))
    if frac >= 10000:                 # 0.99996 rounds to 10000/10000
        units, frac = units + 1, 0
    body[offset:offset + 4] = struct.pack(">HH", frac, units)


def read_bcd(body, offset):
    frac, units = struct.unpack(">HH", bytes(body[offset:offset + 4]))
    return units + frac / 10000.0


def div_index(name):
    """A division label onto its index in the driver's own DIVISIONS table.

    Accepts an int so a manifest may say either. The table is imported rather
    than copied: `_write_voice_pattern` re-stamps a voice from
    DIVISIONS[div][1] and [2] within a second of every load, so a builder that
    disagreed with it would write a file that rewrites itself."""
    if isinstance(name, int):
        if not 0 <= name < len(lib.DIVISIONS):
            raise ValueError(f"division index {name} out of range")
        return name
    for i, (label, _spb, _beats) in enumerate(lib.DIVISIONS):
        if label == name:
            return i
    raise ValueError(f"unknown division {name!r}; have "
                     f"{[d[0] for d in lib.DIVISIONS]}")


def set_division(body, div_idx):
    """Write beatsInPattern and stepsPerBeat, and return the step count.

    THIS IS THE ONLY WAY A PRESET GETS A LOOP LONGER THAN ONE BAR, and it was
    unreachable from a manifest until 2026-09-04: the builder copied 017's
    header untouched, so all 71 shipped presets are 4 beats at 4 steps - one
    bar at 1/16 - on every channel. That is also the sustain ceiling, because
    note_duration clamps a note to the loop point: at 1/16 the longest note
    this instrument can hold is 8 of 16 steps, half a bar. At 1/4 the same 16
    steps span FOUR bars.

    beats comes from the table, never from the manifest: a voice is re-stamped
    to DIVISIONS[div][2] on every rewrite, so any other value is a file that
    disagrees with itself one second after it loads."""
    _label, spb, beats = lib.DIVISIONS[div_idx]
    body[PATN_BEATS:PATN_BEATS + 4] = struct.pack(">I", beats)
    body[PATN_SPB:PATN_SPB + 2] = struct.pack(">H", spb)
    return spb * beats


def set_groove(body, swing=0.0, human_time=0.0, human_velo=0.0):
    """The three per-pattern groove fields, zero in all 71 shipped presets.

    swingAmount is a fraction of a step added to the offset of the steps
    swingDiv selects; humanTime and humanVelo are the sigmas of a
    normal_distribution, in fractions of a step and in velocity units
    (`track.cpp`). The driver writes NONE of these three, so they survive a
    load - unlike swingDiv, which it asserts."""
    if not -1.0 <= swing <= 1.0:
        raise ValueError(f"swing {swing} outside -1.0..1.0")
    body[PATN_SWING_DIV] = FORCED_SWING_DIV
    # swingAmount is signed on the surface (the SWING verb is 50-75 onto
    # -1..+1) but the field is unsigned fixed point, so a negative swing is
    # not expressible here. Refuse rather than write a huge positive.
    if swing < 0:
        raise ValueError("a negative swingAmount cannot be written to the riff")
    write_bcd(body, PATN_SWING_AMT, swing)
    write_bcd(body, PATN_HUMAN_TIME, human_time)
    write_bcd(body, PATN_HUMAN_VELO, human_velo)


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


def set_pattern(body, steps, note, velocity, template, step_count=STEPS):
    """Replace a pattern's events, keeping its 32-byte header.

    `step_count` is the division's, not the module constant: a channel at 1/4
    has sixteen steps that are beats, and a step list written for 1/16 would
    silently land in the wrong bar. The header is copied whole, so whatever
    set_division() and set_groove() wrote into it survives - they must be
    called BEFORE this."""
    header = bytes(body[:PATN_HEADER])
    out = bytearray(header)
    for step in sorted(set(steps)):
        if not 0 <= step < step_count:
            raise ValueError(f"step {step} outside 0..{step_count - 1}")
        out += make_event(template, step, note, velocity)
    return out


def euclid_steps(step_count, hits, rotate, rhythm_reg=0xFFFF, hand_reg=0):
    """The steps a drum channel sounds, the way the DRIVER computes them.

    Written as hits/rotate/registers rather than as a literal step list
    because the packs carry no `drums` block at all, so HITS and ROT on the
    panel are whatever the panel last held - and the first turn of the HITS
    encoder discards the hand-written list and replaces it with a euclid line
    the surface was already claiming to show.

    `rhythm_reg` is SUBTRACTIVE over the euclid line (a 0 bit silences that
    step) and `hand_reg` is ADDITIVE on top - the two defaults are opposite
    for that reason, and they are the driver's own."""
    pattern = lib.euclid(step_count, hits)
    pattern = lib.rotate(pattern, rotate)
    out = []
    for step in range(step_count):
        on = pattern[step] and bool(rhythm_reg >> step & 1)
        if on or (hand_reg >> step & 1):
            out.append(step)
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


def _per_voice(src, key, i, default):
    """One voice's value for an OPTIONAL per-voice list.

    A manifest may give a list of three, or omit the key entirely. It may not
    give a scalar: every other per-voice field here is a list, and one field
    that is sometimes a number is how a builder comes to read `gate` as an
    index."""
    if key not in src:
        return default
    values = src[key]
    if not isinstance(values, list):
        raise ValueError(f"voices.{key} must be a list, got {type(values).__name__}")
    return values[i]


def _drums_euclid(entry):
    """The euclid form of a drum groove, or None if the manifest is the old
    literal-step kind.

    `hits` is the switch: an entry that names it is written as euclid plus the
    two registers, gets a `drums` block, and can be played without destroying
    itself. An entry that does not is built exactly as before."""
    drums = entry.get("drums") or {}
    if "hits" not in drums:
        return None
    out = []
    for i in range(5):
        out.append({
            "hits": drums["hits"][i],
            "rotate": (drums.get("rotate") or [0] * 5)[i],
            "rhythm": (drums.get("rhythm") or [0] * 5)[i],
            "rhythm_reg": (drums.get("rhythm_reg") or [0xFFFF] * 5)[i],
            "hand_reg": (drums.get("hand_reg") or [0] * 5)[i],
        })
    return out


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
    drums_euclid = _drums_euclid(entry)

    # ONE DIVISION INDEX PER CHANNEL, or None to leave 017's header alone.
    # `div` is eight entries because a channel is a channel here - the drum
    # five and the voice three take the same key, and an overridden drum
    # channel is a voice that still lives at its own index.
    divs = entry.get("div")
    if divs is not None:
        if len(divs) != 8:
            raise ValueError(f"div needs 8 entries, got {len(divs)}")
        divs = [div_index(x) for x in divs]

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
    # THE MIX AND SPACE GLOBALS, and the key walker. Absent in all 71 shipped
    # presets, which is why none of them sets a master level or a reverb type
    # and none of them walks its key. `set_state` drops a key that is not
    # already in self.globals, so an unknown name here is silently ignored
    # rather than an error - the reason this is a fixed list and not a
    # passthrough of whatever the manifest holds.
    for key in ("master", "revsize", "revtype", "dlytime", "dlyfbk",
                "walk", "wspan"):
        if key in (entry.get("globals") or {}):
            state["globals"][key] = entry["globals"][key]
    v = entry["voices"]
    def _voice_block(src, i):
        """One voice's saved state. `chord`, `random` and `rhythm` default to
        the values the 71 shipped presets carry, so a manifest that names
        none of them builds exactly what it built before.

        CHORD IS ZERO IN ALL 71 AND ZERO IS OFF - chords shipped 2026-09-02,
        the packs were built 2026-08-22, and `chord_notes` at shape 0 returns
        precisely what `pitch()` returned, so absent and 0 are the same file."""
        block = {
            "register": src["register"][i],
            "length": src["length"][i],
            "rhythm_reg": src["rhythm_reg"][i],
            # Evolution OFF unless the manifest asks. `random` moves the top
            # bits of the pitch register, so it walks a curated voicing
            # anywhere in its band; keep it off pitched drone layers.
            "random": _per_voice(src, "random", i, 0),
            "rhythm": _per_voice(src, "rhythm", i, 0),
            "gate": src["gate"][i],
            "octave": src["octave"][i],
            "range": src["range"][i],
            "velo": src["velo"][i],
            "ring": [],
        }
        chord = _per_voice(src, "chord", i, 0)
        if chord:
            block["chord"] = chord
        return block

    state["voices"] = {str(5 + i): _voice_block(v, i) for i in range(3)}
    # A channel the entry overrides needs its voice parameters too, or it comes
    # up as a voice running whatever default_channel_state built.
    for channel, over in overrides.items():
        block = {
            "register": over["register"],
            "length": over["length"],
            "rhythm_reg": over["rhythm_reg"],
            "random": over.get("random", 0),
            "rhythm": over.get("rhythm", 0),
            "gate": over["gate"],
            "octave": over["octave"],
            "range": over["range"],
            "velo": over["velo"],
            "ring": [],
        }
        if over.get("chord"):
            block["chord"] = over["chord"]
        state["voices"][str(channel)] = block
    # THE `drums` BLOCK, ABSENT IN ALL 71 SHIPPED PRESETS - which is why HITS
    # and ROT on the panel are whatever the panel last held, while the literal
    # step list lives only in the riff. The first turn of the HITS encoder
    # therefore discards a hand-written groove and replaces it with a euclid
    # line the surface was already claiming to show. Written only when the
    # manifest gives the euclid form, so an old manifest still builds the file
    # it built before - byte for byte, absent block included.
    if drums_euclid:
        state["drums"] = {
            str(i): {
                "hits": drums_euclid[i]["hits"],
                "rotate": drums_euclid[i]["rotate"],
                "rhythm": drums_euclid[i].get("rhythm", 0),
                "rhythm_reg": drums_euclid[i].get("rhythm_reg", 0xFFFF),
                "hand_reg": drums_euclid[i].get("hand_reg", 0),
            }
            for i in range(5) if i not in overrides
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

    # --- the mixer -----------------------------------------------------------
    # ALL 71 SHIPPED PRESETS HAVE EVERY FADER AT 0.19, inherited from 017 and
    # never touched: a flat board is not neutral, it is the absence of a
    # decision, and it is most of why the packs sound like eight things
    # competing. 019 runs its drums at 0.67-0.78 and its voices at 0.21-0.34.
    #
    # The mixer - not the driver's own `level` - is where the mix actually
    # lives: `state[ch]["level"]` is stale by design and the driver reads the
    # strip instead. A `level` MODULATOR overwrites the fader within 200 ms of
    # load, so a modulated channel's `base` must equal 100x its fader here or
    # the two disagree and the modulator wins.
    mix = entry.get("mix")
    if mix is not None:
        if len(mix) != 8:
            raise ValueError(f"mix needs 8 entries, got {len(mix)}")
        for i, level in enumerate(mix):
            if not 0.0 <= level <= 1.0:
                raise ValueError(f"mix[{i}] = {level} outside 0.0..1.0")
            chan = zs3["mixer"].get(f"chan_{i:02d}")
            if chan is None:
                raise ValueError(f"base snapshot has no mixer strip chan_{i:02d}")
            chan["level"] = float(level)
    if entry.get("main") is not None:
        main = float(entry["main"])
        if not 0.0 <= main <= 1.0:
            raise ValueError(f"main {main} outside 0.0..1.0")
        # chan_16 is the main strip on this build - MAX_NUM_CHANNELS - 1.
        zs3["mixer"]["chan_16"]["level"] = main

    # --- the patterns --------------------------------------------------------
    blocks = parse_blocks(base64.b64decode(d["zynseq_riff_b64"]))
    set_tempo(blocks, entry["tempo"])
    patns = [b for b in blocks if b[0] == "patn"]
    if len(patns) != 8:
        raise ValueError(f"expected 8 patterns in the base, found {len(patns)}")
    template = bytes(patns[0][1][PATN_HEADER:PATN_HEADER + PATN_EVENT])

    drums = entry.get("drums") or {}

    def _prepare(channel):
        """Division and groove for one channel, returning its step count.

        Both write into the 32-byte header, and set_pattern() copies that
        header whole - so this must run BEFORE the events are replaced, and
        the step count it returns is what the step list is checked against."""
        body = patns[channel][1]
        step_count = STEPS
        if divs is not None:
            step_count = set_division(body, divs[channel])
        else:
            # No `div` key: keep 017's header, but read the step count out of
            # it rather than assuming 16. A base with a different header would
            # otherwise have its step lists validated against the wrong number.
            spb = struct.unpack(">H", bytes(body[PATN_SPB:PATN_SPB + 2]))[0]
            beats = struct.unpack(">I", bytes(body[PATN_BEATS:PATN_BEATS + 4]))[0]
            step_count = spb * beats
        groove = entry.get("groove")
        if groove:
            set_groove(body,
                       swing=(groove.get("swing") or [0.0] * 8)[channel],
                       human_time=(groove.get("human_time") or [0.0] * 8)[channel],
                       human_velo=(groove.get("human_velo") or [0.0] * 8)[channel])
        return step_count

    for i in range(5):                                   # drum channels A-E
        step_count = _prepare(i)
        over = overrides.get(i)
        if over:
            # Behaving as a voice: the steps come from its register, and
            # _write_voice_pattern rewrites the notes on load anyway.
            steps = [s for s in range(step_count) if over["rhythm_reg"] >> s & 1]
            patns[i][1] = set_pattern(patns[i][1], steps, 60, over["velo"],
                                      template, step_count)
            continue
        if drums_euclid:
            steps = euclid_steps(step_count,
                                 drums_euclid[i]["hits"],
                                 drums_euclid[i]["rotate"],
                                 drums_euclid[i]["rhythm_reg"],
                                 drums_euclid[i]["hand_reg"])
        else:
            steps = drums["steps"][i]
        patns[i][1] = set_pattern(patns[i][1], steps, drum_notes[i],
                                  drums["velo"][i], template, step_count)
    for i in range(3):                                   # voice channels F-H
        step_count = _prepare(5 + i)
        steps = [s for s in range(step_count) if v["rhythm_reg"][i] >> s & 1]
        # Overwritten by _write_voice_pattern on load; written anyway so the
        # file is never internally inconsistent with the registers beside it.
        patns[5 + i][1] = set_pattern(patns[5 + i][1], steps, 60, v["velo"][i],
                                      template, step_count)

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
        atomic_write.write_json(path, d)
        written += 1
        print(f"  {entry['file']:28} {entry['genre']:11} {entry['tempo']:3} BPM  "
              f"{'/'.join(e.split('/')[-1] for e in entry['voices']['engines'])}")
    print(f"{written} snapshots -> {args.out}")


if __name__ == "__main__":
    main()
