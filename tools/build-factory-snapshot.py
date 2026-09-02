#!/usr/bin/env python3
"""Build the FACTORY snapshot from a manifest, offline, on the .zss JSON.

    python3 tools/build-factory-snapshot.py \
        --manifest snapshot/factory-manifest.json \
        --out /tmp/factory

The factory snapshot used to be hand-built on the touchscreen (017) and then
patched by script (018 added the main-bus filter). That made it the one
snapshot in the project nothing could reproduce. This makes it data.

WHY THIS IS NOT build-genre-snapshots.py, which already builds snapshots from a
manifest: that tool's brief is a FIXED ARRANGEMENT. It forces `random` and
`rhythm` to 0 on every voice, it rewrites all three voice engines from the
entry, and an engine that differs by a character clears the processor - which
would throw away the seventeen hand-dialled JC303 controllers and the two LV2
presets that ARE the factory sound. The factory snapshot needs the opposite
default: touch only what the manifest names, and leave every byte it does not.

WHAT THIS ONE DOES DIFFERENTLY, and why each one is the way it is:

* THE DRUM PATTERN IS DERIVED, NEVER LISTED. The manifest gives HITS and
  ROTATE and the tool runs the instrument's OWN euclid - the real
  maschine_mk2_lib.build_pattern_steps and the real techno_lib.drum_steps - to
  find the steps. Listing steps instead is how a pattern and the HITS encoder
  come to disagree: the pattern in the riff plays what it was given while the
  knob reads whatever the driver last held, and the first touch of HITS snaps
  the bar to something nobody asked for. Deriving it means the two cannot
  disagree, because there is one generator and this is it.

* DRUM PATTERNS SURVIVE A LOAD; VOICE PATTERNS DO NOT. set_state ends by
  calling _write_voice_pattern() for every voice, so any notes written here for
  F, G or H are gone within a second of loading. A voice is therefore authored
  as its REGISTER - `register` decides the pitches, `rhythm_reg` decides which
  steps sound - and the notes this tool writes for it are a courtesy so the
  file is never internally inconsistent.

* A MODULATOR'S BASE IS COMPUTED FROM WHAT THIS TOOL JUST WROTE, never taken
  from the manifest. `level` reads the mixer strip, `reverb` and `delay` read
  the wet this run set on that chain's insert. A base that disagrees with the
  plugin makes the first modulator tick after a load YANK the parameter to
  wherever the number said - which is the defect _mod_base_get's own docstring
  records for the live path.

* A CONTROLLER OVERRIDE MUST NAME A SYMBOL THE PROCESSOR ALREADY HAS. A typo
  would otherwise add a dead key that no plugin reads, and nothing would say
  so. Refused loudly instead.

* THE SNAPSHOT MUST NAME ITSELF. `last_snapshot_fpath` is inherited by every
  snapshot built from another, and Zynthian reads that field - not the
  filename - when it restores last_state.zss, which is the boot path. Seventy
  two of seventy three shipped files once claimed to be 017 because of it.
"""

import argparse
import base64
import copy
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "ctrldev"))

from maschine_mk2_lib import maschine_mk2_lib as lib      # noqa: E402
from techno_lib import techno_lib as tlib                 # noqa: E402


def _sibling(name):
    """Import a tools/ script whose filename has dashes in it."""
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The riff readers and writers, the kit path builder and the processor
# accessors are already measured and already shipped in the pack builder.
# Reusing them rather than copying them: two decoders of one binary format
# drift, and the riff is the part of a .zss that cannot be eyeballed.
genre = _sibling("build-genre-snapshots")

STEPS = 16
DRUM_CHAINS = ["1", "2", "3", "4", "5"]
VOICE_CHAINS = ["6", "7", "8"]
CTRLDEV_PORT = genre.CTRLDEV_PORT
REVERB_NAME = "TAP Reverberator"
DELAY_NAME = "TAP Stereo Echo"
# 0-100 on the surface onto the plugin's dB range, exactly as the driver's
# _set_wet does it. Kept as one pair of functions so the tool and the
# instrument cannot disagree about what "30% wet" means.
WET_LO, WET_HI = -70.0, 10.0


def wet_db(percent):
    return WET_LO + (WET_HI - WET_LO) * (percent / 100.0)


def wet_percent(db):
    return int(round((db - WET_LO) / (WET_HI - WET_LO) * 100.0))


def chain_of_channel(channel):
    """The chain id carrying channel 0-7. The tables are 1-based and in order."""
    return str(channel + 1)


def insert_procs(chain, procs):
    """(reverb processor, delay processor) for a chain, or None for each that
    is not there. Found by the plugin's own name, never by slot index: a
    snapshot whose insert pair is in the other order is still correct."""
    found = {"reverb": None, "delay": None}
    for slot in chain["slots"][1:]:
        pid, code = next(iter(slot.items()))
        if REVERB_NAME in code:
            found["reverb"] = procs[pid]
        elif DELAY_NAME in code:
            found["delay"] = procs[pid]
    return found


def set_wet(proc, which, percent):
    """Write a wet level as the driver would. The echo's two sides are ganged,
    which is what _set_wet does on the rig."""
    symbols = ["wetlevel"] if which == "reverb" else ["lecholevel", "recholevel"]
    ctrls = proc.setdefault("controllers", {})
    for symbol in symbols:
        if symbol not in ctrls:
            raise ValueError(f"{which} insert has no {symbol!r} controller")
        ctrls[symbol]["value"] = wet_db(percent)


def read_wet(proc, which):
    ctrls = (proc or {}).get("controllers") or {}
    symbol = "wetlevel" if which == "reverb" else "lecholevel"
    if symbol not in ctrls:
        return None
    return wet_percent(ctrls[symbol]["value"])


def drum_pattern(spec):
    """The steps a drum channel sounds, through the instrument's own
    generators: euclid, rotated, thinned by the subtractive rhythm register,
    then the hand register laid on top."""
    hits = int(spec["hits"])
    rotate = int(spec.get("rotate", 0))
    rhythm_reg = int(spec.get("rhythm_reg", 0xFFFF))
    hand_reg = int(spec.get("hand_reg", 0))
    line = lib.build_pattern_steps(STEPS, hits, rotate)
    sounding = tlib.drum_steps(line, rhythm_reg, hand_reg)
    return [i for i, on in enumerate(sounding) if on]


def voice_state(spec):
    """One voice's saved state, with every key the current driver writes.

    An absent key would fall back to a default on load, which is legal - but a
    factory snapshot that leans on defaults changes sound the next time a
    default changes, silently. So every field is written."""
    if spec.get("empty"):
        # Empty is rhythm_reg 0: the mask is all zero, _write_voice_pattern
        # skips addNote for every step, and the pads draw an empty line with
        # RHYTHM reading 0. Silent, and it says why.
        spec = dict(spec, rhythm_reg=0, random=0, rhythm=0)
    return {
        "register": int(spec.get("register", 179)),
        "ring": list(spec.get("ring", [])),
        "length": int(spec.get("length", 16)),
        "random": int(spec.get("random", 0)),
        "rhythm": int(spec.get("rhythm", 0)),
        "rhythm_reg": int(spec.get("rhythm_reg", 0xFFFF)),
        "gate": int(spec.get("gate", 40)),
        "octave": int(spec.get("octave", 0)),
        "range": int(spec.get("range", 1)),
        "kit_range": int(spec.get("kit_range", 4)),
        "velo": int(spec.get("velo", 110)),
        "rotate": int(spec.get("rotate", 0)),
        "model": spec.get("model", tlib.MODEL_REGISTER),
        "rule": spec.get("rule", tlib.RULE_RANDOM),
        "move": int(spec.get("move", 100)),
        "exit": int(spec.get("exit", 0)),
        "phrase": int(spec.get("phrase", 1)),
        "fill": int(spec.get("fill", 0)),
        "walk_span": int(spec.get("walk_span", 32)),
        "walk_stride": int(spec.get("walk_stride", 4)),
        "walk_seed": int(spec.get("walk_seed", 0)),
        "feed": spec.get("feed"),
        "amount": int(spec.get("amount", 0)),
    }


def drum_state(spec):
    """One drum channel's saved state, same argument as voice_state.

    ROTATE IS IN HERE, and it was not in the driver's own drums block until
    2026-09-02. Without it a rotated line plays rotated and the ROT encoder
    reads 0, so the first touch of ROT jumps the bar."""
    return {
        "hits": int(spec["hits"]),
        "rotate": int(spec.get("rotate", 0)),
        "rhythm": int(spec.get("rhythm", 0)),
        "rhythm_reg": int(spec.get("rhythm_reg", 0xFFFF)),
        "hand_reg": int(spec.get("hand_reg", 0)),
        "lean": spec.get("lean", tlib.LEAN_OFF),
        "lane": int(spec.get("lane", 0)),
        "move": int(spec.get("move", 100)),
        "exit": int(spec.get("exit", 0)),
        "rule": spec.get("rule", tlib.RULE_RANDOM),
        "phrase": int(spec.get("phrase", 1)),
        "fill": int(spec.get("fill", 0)),
    }


def build(base, manifest, kit_notes):
    """The whole snapshot. Returns (snapshot dict, report lines)."""
    d = copy.deepcopy(base)
    zs3 = d["zs3"]["zs3-0"]
    procs = zs3["processors"]
    chains = d["chains"]
    state = zs3["midi_capture"][CTRLDEV_PORT]["ctrldev_state"]
    report = []

    zs3["title"] = manifest["title"]

    # --- tempo, in BOTH places a .zss holds it ------------------------------
    # The riff's vers block is what the sequencer plays; the driver's own
    # globals are what the surface shows. Writing one without the other gives
    # a snapshot whose panel disagrees with its own sequencer - the trap
    # tools/set-snapshot-tempo.py exists to prevent.
    tempo = int(manifest["tempo"])
    blocks = genre.parse_blocks(base64.b64decode(d["zynseq_riff_b64"]))
    genre.set_tempo(blocks, tempo)
    state["globals"] = dict(state.get("globals") or {})
    state["globals"]["bpm"] = tempo
    state["globals"].update(manifest.get("globals") or {})
    exact = 30000 % tempo == 0
    report.append(f"tempo {tempo} BPM  ({'exact at 48 kHz' if exact else 'INEXACT at 48 kHz'})")

    patns = [b for b in blocks if b[0] == "patn"]
    if len(patns) != 8:
        raise ValueError(f"expected 8 patterns in the base, found {len(patns)}")
    template = bytes(patns[0][1][genre.PATN_HEADER:
                                 genre.PATN_HEADER + genre.PATN_EVENT])

    # --- the drums ----------------------------------------------------------
    drums_out = dict(state.get("drums") or {})
    for key, spec in sorted((manifest.get("drums") or {}).items()):
        channel = int(key)
        chain = chains[chain_of_channel(channel)]
        pid = genre.proc_of(chain)
        kit = spec["kit"]
        if kit not in kit_notes:
            raise ValueError(f"kit {kit!r} is not usable - see tools/scan-drum-kits.py")
        genre.set_kit(procs[pid], kit)
        note = kit_notes[kit][channel]
        steps = drum_pattern(spec)
        patns[channel][1] = genre.set_pattern(
            patns[channel][1], steps, note, int(spec["velo"]), template)
        drums_out[str(channel)] = drum_state(spec)
        report.append(
            f"  {chain['title']:11} {kit:14} note {note:3}  "
            f"hits {spec['hits']} rot {spec.get('rotate', 0)}  "
            f"steps {steps}  velo {spec['velo']}")
    state["drums"] = drums_out

    # --- the voices ---------------------------------------------------------
    voices_out = dict(state.get("voices") or {})
    for key, spec in sorted((manifest.get("voices") or {}).items()):
        channel = int(key)
        voices_out[str(channel)] = voice_state(spec)
        saved = voices_out[str(channel)]
        steps = [s for s in range(STEPS) if saved["rhythm_reg"] >> s & 1]
        # A courtesy write - _write_voice_pattern replaces it on load.
        patns[channel][1] = genre.set_pattern(
            patns[channel][1], steps, 60, saved["velo"], template)
        if spec.get("empty"):
            report.append(f"  channel {channel} EMPTY (rhythm_reg 0)")
        else:
            notes = tlib.line(saved["register"], saved["length"], STEPS,
                              state["globals"].get("root", 0),
                              state["globals"].get("scale", 0),
                              saved["octave"], saved["range"])
            report.append(
                f"  channel {channel} register {saved['register']} "
                f"steps {steps} notes {[notes[s] for s in steps]} "
                f"gate {saved['gate']}")
    state["voices"] = voices_out

    # --- gate the note-off writes back into the riff ------------------------
    d["zynseq_riff_b64"] = base64.b64encode(genre.build_blocks(blocks)).decode("ascii")

    # --- the insert wets, and the delay time --------------------------------
    delay_ms = manifest.get("delay_ms")
    for cid, chain in chains.items():
        if chain.get("midi_chan") is None:
            continue
        inserts = insert_procs(chain, procs)
        if delay_ms is not None and inserts["delay"] is not None:
            ctrls = inserts["delay"]["controllers"]
            for symbol in ("ldelay", "rhaasdelay"):
                if symbol in ctrls:
                    ctrls[symbol]["value"] = float(delay_ms)
    for cid, wants in sorted((manifest.get("wets") or {}).items()):
        chain = chains[cid]
        inserts = insert_procs(chain, procs)
        for which, percent in sorted(wants.items()):
            if inserts[which] is None:
                raise ValueError(f"chain {cid} has no {which} insert")
            set_wet(inserts[which], which, percent)
        report.append(f"  {chain['title']:11} wet "
                      + "  ".join(f"{w} {p}%" for w, p in sorted(wants.items())))
    if delay_ms is not None:
        report.append(f"delay time {delay_ms} ms on every chain "
                      f"(1/8 at {tempo} BPM is {30000.0 / tempo:.1f} ms)")

    # --- plugin controllers -------------------------------------------------
    for cid, wants in sorted((manifest.get("controllers") or {}).items()):
        chain = chains[cid]
        pid = genre.proc_of(chain)
        ctrls = procs[pid].get("controllers") or {}
        for symbol, value in sorted(wants.items()):
            if symbol not in ctrls:
                raise ValueError(
                    f"chain {cid} processor has no controller {symbol!r} - "
                    f"it has {sorted(ctrls)}")
            was = ctrls[symbol]["value"]
            ctrls[symbol]["value"] = value
            report.append(f"  {chain['title']:11} {symbol:14} {was:.3f} -> {value}")

    # --- the modulators -----------------------------------------------------
    mixer = zs3.get("mixer") or {}
    mods_out = {}
    for m in (manifest.get("mods") or []):
        channel, verb = int(m["channel"]), m["verb"]
        if not tlib.mod_allowed(verb):
            raise ValueError(f"{verb!r} is not a verb a modulator may drive")
        if tlib.is_drift(verb):
            raise ValueError(f"{verb!r} is a DRIFT verb - not supported here yet")
        if verb == "level":
            level = (mixer.get(f"chan_{channel:02d}") or {}).get("level")
            if level is None:
                raise ValueError(f"channel {channel} has no mixer strip")
            base_value = int(round(level * 100))
        else:
            chain = chains[chain_of_channel(channel)]
            base_value = read_wet(insert_procs(chain, procs)[verb], verb)
            if base_value is None:
                raise ValueError(f"channel {channel} has no {verb} insert")
        mods_out[f"{channel}|{verb}"] = {
            "depth": int(m["depth"]),
            "rate": int(m["rate"]),
            "shape": m["shape"],
            "phase0": float(m.get("phase0", 0.0)),
            "base": base_value,
            "seed": int(m.get("seed", 0)),
        }
        report.append(
            f"  channel {channel} {verb:7} depth {m['depth']:+4} "
            f"base {base_value:3} {tlib.MOD_RATES[int(m['rate'])]:g} bars "
            f"{m['shape']:4} phase {float(m.get('phase0', 0.0)):.2f}")
    state["mods"] = mods_out
    state["mod_seed"] = len(mods_out)
    state["mod_depth_mult"] = float(manifest.get("mod_depth_mult", 1.0))

    d["last_snapshot_fpath"] = (
        "/zynthian/zynthian-my-data/snapshots/000/" + manifest["file"] + ".zss")
    return d, report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="snapshot/factory-manifest.json")
    ap.add_argument("--base", default=None,
                    help="overrides the manifest's own base")
    ap.add_argument("--kits", default=os.path.join(HERE, "drum-kit-notes.json"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    manifest = json.load(open(args.manifest))
    base_path = args.base or manifest["base"]
    base = json.load(open(base_path))
    kit_notes = json.load(open(args.kits))["notes"]

    d, report = build(base, manifest, kit_notes)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, manifest["file"] + ".zss")
    with open(path, "w") as fh:
        json.dump(d, fh, indent=2)

    print(f"base     {base_path}")
    for line in report:
        print(line)
    print(f"\nwritten  {path}  ({os.path.getsize(path)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
