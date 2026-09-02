"""Tests for the factory snapshot builder.

Pure: every test builds its own base snapshot in memory and reads back what
the builder produced. Nothing here touches a rig, a shipped .zss or a
sequencer.

The builder's whole promise is "touch only what the manifest names", so most
of these tests are about what did NOT change.
"""

import base64
import importlib.util
import json
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(ROOT, "ctrldev"))

from maschine_mk2_lib import maschine_mk2_lib as lib      # noqa: E402
from techno_lib import techno_lib as tlib                 # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), os.path.join(TOOLS, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _load("build-factory-snapshot")

PORT = builder.CTRLDEV_PORT
KITS = {"Roland TR909": [36, 40, 50, 42, 46],
        "Roland CR78": [36, 40, 40, 42, 44]}


def riff(tempo=125):
    """A vers block and eight patn blocks, the shape the rig writes."""
    out = bytearray()
    vers = bytearray(16)
    vers[4:6] = struct.pack(">H", tempo)
    out += b"vers" + struct.pack(">I", len(vers)) + vers
    for _ in range(8):
        # One template event, which is what the builder copies every other
        # event's untouched bytes from.
        body = bytearray(builder.genre.PATN_HEADER + builder.genre.PATN_EVENT)
        body[builder.genre.PATN_HEADER + 12] = 0x90
        out += b"patn" + struct.pack(">I", len(body)) + bytes(body)
    return bytes(out)


def events(raw, index):
    """(step, note, velocity) for one pattern, read back out of the riff."""
    patns = [b for b in builder.genre.parse_blocks(raw) if b[0] == "patn"]
    body = patns[index][1]
    header, size = builder.genre.PATN_HEADER, builder.genre.PATN_EVENT
    out = []
    for off in range(header, len(body), size):
        ev = body[off:off + size]
        out.append((struct.unpack(">I", bytes(ev[0:4]))[0], ev[13], ev[14]))
    return out


def base_snapshot():
    chains, procs = {}, {}
    for i in range(8):
        cid = str(i + 1)
        engine, delay, reverb = str(10 + i), str(20 + i), str(30 + i)
        chains[cid] = {
            "title": f"CH{i}",
            "midi_chan": i,
            "slots": [{engine: "JV/Engine"},
                      {delay: "JV/TAP Stereo Echo"},
                      {reverb: "JV/TAP Reverberator"}],
        }
        procs[engine] = {"preset_info": ["a/preset.ttl", 0, "P", "lv2", "P"],
                         "controllers": {"_decay": {"value": 0.0},
                                         "_cutoff": {"value": 0.6}}}
        if cid == "7":                       # the chain the preset tests swap
            chains[cid]["slots"][0] = {engine: "JV/Obxd"}
            procs[engine]["controllers"] = {
                f"c{n}": {"value": 0.5} for n in range(82)}
        procs[delay] = {"controllers": {
            "ldelay": {"value": 241.9}, "rhaasdelay": {"value": 241.9},
            "lecholevel": {"value": -70.0}, "recholevel": {"value": -70.0},
            "dryLevel": {"value": 0.0}}}
        procs[reverb] = {"controllers": {
            "wetlevel": {"value": -70.0}, "drylevel": {"value": 0.0},
            "decay": {"value": 6700.0}}}
    return {
        "last_snapshot_fpath": "/somewhere/else/017.zss",
        "chains": chains,
        "zynseq_riff_b64": base64.b64encode(riff()).decode("ascii"),
        "zs3": {"zs3-0": {
            "title": "Base",
            "processors": procs,
            "mixer": {f"chan_{i:02d}": {"level": 0.19} for i in range(8)},
            "midi_capture": {PORT: {"ctrldev_state": {
                "globals": {"root": 0, "scale": 0, "bpm": 125, "master": 80},
                "kinds": {"4": "voice"},
                "owners": {str(i): "gen" for i in range(8)},
                "mode": "STEP", "pages": {}, "selected": 0, "stash": {},
                "voices": {}, "drums": {},
            }}},
        }},
    }


def manifest(**over):
    m = {
        "file": "019-test", "title": "Test", "base": "unused",
        "tempo": 120,
        "globals": {"root": 7, "scale": 0},
        "delay_ms": 250.0,
        "drums": {"0": {"kit": "Roland TR909", "hits": 4, "rotate": 0,
                        "velo": 108, "gate": 45},
                  "3": {"kit": "Roland CR78", "hits": 4, "rotate": 2,
                        "velo": 66, "gate": 25}},
        "voices": {"5": {"register": 58, "length": 16, "rhythm_reg": 17473,
                         "random": 0, "rhythm": 0, "gate": 150,
                         "octave": -1, "range": 1, "velo": 110},
                   "6": {"register": 179, "length": 16, "rhythm_reg": 16448,
                         "random": 0, "rhythm": 0, "gate": 75,
                         "octave": 1, "range": 1, "velo": 96},
                   "7": {"empty": True}},
        "chords": {"6": [
            {"step": 6, "notes": [55, 58, 62], "velo": 96, "duration": 0.75},
            {"step": 14, "notes": [57, 60, 65], "velo": 84, "duration": 0.75},
        ]},
        "presets": {"7": {"engine": "JV/Obxd",
                          "bundle": "Obxd_003-KVR_Brass_Synths",
                          "file": "003-KVR_Brass_Synths_Analog_Brass_Chrds.ttl",
                          "name": "Analog Brass Chrds",
                          "controllers": {"voicecount": 0.575}}},
        "wets": {"3": {"delay": 30, "reverb": 22}},
        "controllers": {"6": {"_decay": 0.35}},
        "mods": [{"channel": 0, "verb": "level", "depth": 6, "rate": 0,
                  "shape": "tri", "phase0": 0.0, "seed": 1},
                 {"channel": 2, "verb": "delay", "depth": 28, "rate": 2,
                  "shape": "tri", "phase0": 0.55, "seed": 3}],
    }
    m.update(over)
    return m


def build(**over):
    d, report = builder.build(base_snapshot(), manifest(**over), KITS)
    state = d["zs3"]["zs3-0"]["midi_capture"][PORT]["ctrldev_state"]
    return d, state, report


class TheDrumPatternIsDerivedNotListed(unittest.TestCase):

    def test_four_on_the_floor_from_hits_alone(self):
        d, _state, _r = build()
        raw = base64.b64decode(d["zynseq_riff_b64"])
        self.assertEqual([e[0] for e in events(raw, 0)], [0, 4, 8, 12])

    def test_a_rotation_moves_the_line_the_way_the_instrument_does(self):
        d, _state, _r = build()
        raw = base64.b64decode(d["zynseq_riff_b64"])
        self.assertEqual([e[0] for e in events(raw, 3)], [2, 6, 10, 14])

    def test_it_agrees_with_the_real_generator(self):
        # The point of deriving rather than listing: one generator, and this
        # is it. If build_pattern_steps ever changes, this changes with it.
        want = [i for i, on in
                enumerate(lib.build_pattern_steps(16, 4, 2)) if on]
        d, _state, _r = build()
        raw = base64.b64decode(d["zynseq_riff_b64"])
        self.assertEqual([e[0] for e in events(raw, 3)], want)

    def test_the_rhythm_register_can_thin_the_line(self):
        m = manifest()
        m["drums"]["0"]["rhythm_reg"] = 0xFFFF & ~(1 << 4)
        d = builder.build(base_snapshot(), m, KITS)[0]
        raw = base64.b64decode(d["zynseq_riff_b64"])
        self.assertEqual([e[0] for e in events(raw, 0)], [0, 8, 12])

    def test_the_hand_register_can_add_a_step_euclid_never_placed(self):
        m = manifest()
        m["drums"]["0"]["hand_reg"] = 1 << 3
        d = builder.build(base_snapshot(), m, KITS)[0]
        raw = base64.b64decode(d["zynseq_riff_b64"])
        self.assertEqual([e[0] for e in events(raw, 0)], [0, 3, 4, 8, 12])


class TheDrumNoteComesFromTheKitScan(unittest.TestCase):

    def test_each_channel_takes_its_own_slot_from_the_kit(self):
        d, _state, _r = build()
        raw = base64.b64decode(d["zynseq_riff_b64"])
        self.assertEqual({e[1] for e in events(raw, 0)}, {36})   # TR909 kick
        self.assertEqual({e[1] for e in events(raw, 3)}, {42})   # CR78 chat

    def test_a_kit_the_scan_does_not_know_is_refused(self):
        m = manifest()
        m["drums"]["0"]["kit"] = "Not A Real Kit"
        with self.assertRaises(ValueError):
            builder.build(base_snapshot(), m, KITS)

    def test_the_kit_path_is_written_for_restore(self):
        d, _state, _r = build()
        slot = d["chains"]["1"]["slots"][0]
        proc = d["zs3"]["zs3-0"]["processors"][next(iter(slot))]
        self.assertTrue(proc["preset_info"][0].endswith("Roland TR909.sfz"))

    def test_the_velocity_is_the_one_the_manifest_asked_for(self):
        d, _state, _r = build()
        raw = base64.b64decode(d["zynseq_riff_b64"])
        self.assertEqual({e[2] for e in events(raw, 0)}, {108})


class TheDrumStateAgreesWithThePattern(unittest.TestCase):

    def test_hits_and_rotate_are_both_saved(self):
        _d, state, _r = build()
        self.assertEqual(state["drums"]["3"]["hits"], 4)
        self.assertEqual(state["drums"]["3"]["rotate"], 2)

    def test_every_field_the_driver_reads_is_written(self):
        # A factory snapshot that leans on load defaults changes sound the
        # next time a default changes, silently.
        _d, state, _r = build()
        for field in ("hits", "rotate", "rhythm", "rhythm_reg", "hand_reg",
                      "lean", "lane", "move", "exit", "rule", "phrase", "fill"):
            self.assertIn(field, state["drums"]["0"], field)

    def test_a_channel_the_manifest_leaves_alone_keeps_its_state(self):
        _d, state, _r = build()
        self.assertNotIn("1", state["drums"])


class AVoiceIsAuthoredAsItsRegister(unittest.TestCase):

    def test_the_register_produces_the_line_we_intended(self):
        _d, state, _r = build()
        saved = state["voices"]["5"]
        notes = tlib.line(saved["register"], saved["length"], 16, 7, 0,
                          saved["octave"], saved["range"])
        steps = [s for s in range(16) if saved["rhythm_reg"] >> s & 1]
        self.assertEqual(steps, [0, 6, 10, 14])
        self.assertEqual([notes[s] for s in steps], [31, 31, 41, 36])

    def test_generation_is_off(self):
        _d, state, _r = build()
        self.assertEqual(state["voices"]["5"]["random"], 0)
        self.assertEqual(state["voices"]["5"]["rhythm"], 0)

    def test_empty_is_a_zero_rhythm_register_and_no_notes(self):
        d, state, _r = build()
        self.assertEqual(state["voices"]["7"]["rhythm_reg"], 0)
        raw = base64.b64decode(d["zynseq_riff_b64"])
        self.assertEqual(events(raw, 7), [])

    def test_empty_also_switches_generation_off(self):
        # An empty channel that was still evolving would fill itself in the
        # moment anything moved the register.
        _d, state, _r = build()
        self.assertEqual(state["voices"]["7"]["random"], 0)
        self.assertEqual(state["voices"]["7"]["rhythm"], 0)

    def test_the_courtesy_notes_match_the_register_mask(self):
        d, _state, _r = build()
        raw = base64.b64decode(d["zynseq_riff_b64"])
        self.assertEqual([e[0] for e in events(raw, 5)], [0, 6, 10, 14])

    def test_every_field_the_driver_reads_is_written(self):
        _d, state, _r = build()
        for field in ("register", "ring", "length", "random", "rhythm",
                      "rhythm_reg", "gate", "octave", "range", "kit_range",
                      "velo", "rotate", "model", "rule", "move", "exit",
                      "phrase", "fill", "walk_span", "walk_stride",
                      "walk_seed", "feed", "amount"):
            self.assertIn(field, state["voices"]["5"], field)


class AChordIsATakeBecauseTheGeneratorIsMonophonic(unittest.TestCase):
    """_write_voice_pattern writes one note per step and the "chord walker"
    walks the shared ROOT, so real chords can only be a player-owned take."""

    def chord_events(self, index=6):
        d, _state, _r = build()
        raw = base64.b64decode(d["zynseq_riff_b64"])
        patns = [b for b in builder.genre.parse_blocks(raw) if b[0] == "patn"]
        body = patns[index][1]
        header, size = builder.genre.PATN_HEADER, builder.genre.PATN_EVENT
        out = []
        for off in range(header, len(body), size):
            ev = body[off:off + size]
            if len(ev) < size:
                break
            frac, units = struct.unpack_from(">HH", bytes(ev), 8)
            out.append({"step": struct.unpack(">I", bytes(ev[0:4]))[0],
                        "note": ev[13], "velo": ev[14],
                        "dur": units + frac / 10000.0,
                        "cmd": ev[12], "chance": ev[19]})
        return out

    def test_three_notes_land_on_one_step(self):
        evs = [e for e in self.chord_events() if e["step"] == 6]
        self.assertEqual([e["note"] for e in evs], [55, 58, 62])

    def test_both_stabs_are_written(self):
        self.assertEqual(sorted({e["step"] for e in self.chord_events()}),
                         [6, 14])

    def test_each_stab_keeps_its_own_velocity(self):
        evs = self.chord_events()
        self.assertEqual({e["velo"] for e in evs if e["step"] == 6}, {96})
        self.assertEqual({e["velo"] for e in evs if e["step"] == 14}, {84})

    def test_the_duration_is_written_not_inherited(self):
        # The template event carries the pattern it came from, and this
        # project's MIDI exporter records that the duration field "was never
        # decoded and never mattered". For a stab it is the whole point.
        for e in self.chord_events():
            self.assertAlmostEqual(e["dur"], 0.75, places=4)

    def test_the_fixed_point_encoding_round_trips(self):
        for value in (0.05, 0.4, 0.75, 1.0, 1.5, 8.0):
            frac, units = struct.unpack(">HH", builder.bcd(value))
            self.assertAlmostEqual(units + frac / 10000.0, value, places=4)

    def test_every_event_is_a_note_on_at_full_play_chance(self):
        for e in self.chord_events():
            self.assertEqual(e["cmd"], 0x90)
            self.assertEqual(e["chance"], 100)

    def test_a_note_cannot_outlive_its_pattern(self):
        # tlib.note_duration's own rule, and its reason: libzynseq STORES a
        # duration longer than the pattern and the note-off after the wrap was
        # never proved. "A stuck pad drone is the worst failure this
        # instrument has."
        m = manifest(chords={"6": [{"step": 14, "notes": [55],
                                    "duration": 99.0}]})
        d, _r = builder.build(base_snapshot(), m, KITS)
        raw = base64.b64decode(d["zynseq_riff_b64"])
        patns = [b for b in builder.genre.parse_blocks(raw) if b[0] == "patn"]
        frac, units = struct.unpack_from(">HH", bytes(patns[6][1]), 
                                         builder.genre.PATN_HEADER + 8)
        self.assertAlmostEqual(units + frac / 10000.0, 2.0, places=4)

    def test_a_zero_length_note_is_floored(self):
        m = manifest(chords={"6": [{"step": 0, "notes": [55],
                                    "duration": 0.0}]})
        d, _r = builder.build(base_snapshot(), m, KITS)
        raw = base64.b64decode(d["zynseq_riff_b64"])
        patns = [b for b in builder.genre.parse_blocks(raw) if b[0] == "patn"]
        frac, units = struct.unpack_from(">HH", bytes(patns[6][1]),
                                         builder.genre.PATN_HEADER + 8)
        self.assertAlmostEqual(units + frac / 10000.0, 0.05, places=4)

    def test_a_whole_bar_note_from_step_zero_is_allowed(self):
        m = manifest(chords={"6": [{"step": 0, "notes": [55],
                                    "duration": 16.0}]})
        d, _r = builder.build(base_snapshot(), m, KITS)
        raw = base64.b64decode(d["zynseq_riff_b64"])
        patns = [b for b in builder.genre.parse_blocks(raw) if b[0] == "patn"]
        frac, units = struct.unpack_from(">HH", bytes(patns[6][1]),
                                         builder.genre.PATN_HEADER + 8)
        self.assertAlmostEqual(units + frac / 10000.0, 16.0, places=4)

    def test_the_channel_becomes_player_owned(self):
        # WITHOUT THIS THE CHORDS ARE GONE within a second of loading:
        # set_state calls _write_voice_pattern for every voice, and it only
        # returns early on a player-owned channel.
        _d, state, _r = build()
        self.assertEqual(state["owners"]["6"], "player")

    def test_no_other_channel_is_taken_from_the_generator(self):
        _d, state, _r = build()
        self.assertEqual([c for c, who in state["owners"].items()
                          if who == "player"], ["6"])

    def test_a_chord_channel_must_have_a_voice_entry(self):
        # The pads colour a take against pad_notes at the channel's octave,
        # so the octave has to come from somewhere.
        m = manifest()
        del m["voices"]["6"]
        with self.assertRaises(ValueError):
            builder.build(base_snapshot(), m, KITS)

    def test_a_step_outside_the_pattern_is_refused(self):
        m = manifest(chords={"6": [{"step": 16, "notes": [55]}]})
        with self.assertRaises(ValueError):
            builder.build(base_snapshot(), m, KITS)

    def test_every_shipped_chord_tone_is_reachable_from_the_pads(self):
        # A tone outside pad_notes still SOUNDS, but _rebuild_notes cannot
        # find it, so the step draws in the group colour instead of amber.
        # The shipped manifest is voiced to avoid that; this is the guard.
        with open(os.path.join(ROOT, "snapshot", "factory-manifest.json"),
                  encoding="utf-8") as fh:
            m = json.load(fh)
        for key, stabs in (m.get("chords") or {}).items():
            pads = tlib.pad_notes(m["globals"]["root"], m["globals"]["scale"],
                                  m["voices"][key]["octave"])
            for stab in stabs:
                for note in stab["notes"]:
                    self.assertIn(note, pads,
                                  f"channel {key} step {stab['step']}")

    def test_the_report_says_the_channel_is_player_owned(self):
        _d, _state, report = build()
        self.assertTrue(any("PLAYER-OWNED" in line for line in report))


class AnEngineSwapClearsWhatBelongedToTheOldPlugin(unittest.TestCase):
    """Measured on the rig 2026-08-16 and recorded in the pack builder: the
    old plugin's controller symbols mean nothing to the new one, and a
    preset_info pointing into the old bundle is worse than none."""

    def proc(self, d, cid):
        pid = next(iter(d["chains"][cid]["slots"][0]))
        return d["zs3"]["zs3-0"]["processors"][pid]

    def build_with(self, engines, **over):
        m = manifest(engines=engines, **over)
        return builder.build(base_snapshot(), m, KITS)

    def test_the_engine_in_slot_zero_changes(self):
        d, _r = self.build_with({"6": {"engine": "JV/Obxd"}}, controllers={})
        self.assertEqual(list(d["chains"]["6"]["slots"][0].values()),
                         ["JV/Obxd"])

    def test_the_old_plugins_controllers_and_preset_are_gone(self):
        d, _r = self.build_with({"6": {"engine": "JV/Obxd"}},
                                controllers={})
        proc = self.proc(d, "6")
        self.assertEqual(proc["controllers"], {})
        self.assertIsNone(proc["preset_info"])
        self.assertIsNone(proc["bank_info"])

    def test_a_bare_string_is_accepted_as_well_as_a_dict(self):
        d, _r = self.build_with({"6": "JV/Obxd"}, controllers={})
        self.assertEqual(list(d["chains"]["6"]["slots"][0].values()),
                         ["JV/Obxd"])

    def test_swapping_to_the_engine_already_there_is_a_no_op(self):
        d, report = self.build_with({"6": {"engine": "JV/Engine"}},
                                    controllers={})
        proc = self.proc(d, "6")
        # Nothing cleared, so the chain keeps what it had.
        self.assertEqual(proc["preset_info"][0], "a/preset.ttl")
        self.assertTrue(any("already runs" in line for line in report))

    def test_a_chain_that_does_not_exist_is_refused(self):
        with self.assertRaises(ValueError):
            self.build_with({"99": {"engine": "JV/Obxd"}}, controllers={})

    def test_a_chain_cannot_be_in_engines_and_controllers_at_once(self):
        # The swap clears the processor, so a plain controllers entry would be
        # asserting against symbols this run just deleted. Found by a test:
        # it failed loudly, but the error named a missing controller rather
        # than the real cause.
        with self.assertRaises(ValueError):
            self.build_with({"6": {"engine": "JV/Obxd"}})

    def test_a_preset_lands_on_the_engine_the_swap_just_installed(self):
        # ORDER: engines before presets, or the preset's own engine assertion
        # would fire against the engine being replaced.
        m = manifest(engines={"6": {"engine": "JV/Obxd"}}, controllers={})
        m["presets"]["6"] = {"engine": "JV/Obxd",
                             "bundle": "Obxd_003-KVR_Brass_Synths",
                             "file": "003-KVR_Brass_Synths_BzSYN_PolySynth.ttl",
                             "name": "BzSYN PolySynth",
                             "controllers": {"voicecount": 1.0}}
        d, _r = builder.build(base_snapshot(), m, KITS)
        proc = self.proc(d, "6")
        self.assertTrue(proc["preset_info"][0].endswith("BzSYN_PolySynth.ttl"))
        self.assertEqual(proc["controllers"]["voicecount"]["value"], 1.0)

    def test_a_chain_the_manifest_leaves_alone_keeps_its_engine(self):
        d, _r = self.build_with({"6": {"engine": "JV/Obxd"}}, controllers={})
        self.assertEqual(list(d["chains"]["8"]["slots"][0].values()),
                         ["JV/Engine"])


class TheChordShapeTravelsInTheSnapshot(unittest.TestCase):

    def test_a_voice_entry_carries_its_chord(self):
        m = manifest()
        m["voices"]["5"]["chord"] = 3
        d, _r = builder.build(base_snapshot(), m, KITS)
        state = d["zs3"]["zs3-0"]["midi_capture"][PORT]["ctrldev_state"]
        self.assertEqual(state["voices"]["5"]["chord"], 3)

    def test_saying_nothing_about_chords_builds_chords_off(self):
        # Shape 0 is bit-identical to the single note, so a manifest written
        # before the verb existed builds a snapshot that sounds the same.
        _d, state, _r = build()
        self.assertEqual(state["voices"]["7"]["chord"], 0)

    def test_the_report_shows_what_the_driver_will_actually_write(self):
        m = manifest()
        m["voices"]["5"]["chord"] = 3
        _d, report = builder.build(base_snapshot(), m, KITS)
        line = next(l for l in report if "channel 5" in l)
        self.assertIn("chord TRI", line)
        # Three notes per step, not one - a report that showed the single note
        # while the rig played a triad could not verify a build.
        # The fixture voice sits at octave -1, so the triad is G1 Bb1 D2.
        self.assertIn("[31, 34, 38]", line)

    def test_every_chord_the_shipped_manifest_asks_for_is_a_real_shape(self):
        with open(os.path.join(ROOT, "snapshot", "factory-manifest.json"),
                  encoding="utf-8") as fh:
            m = json.load(fh)
        for key, spec in (m.get("voices") or {}).items():
            shape = spec.get("chord", 0)
            self.assertIsInstance(shape, int, key)
            self.assertGreaterEqual(shape, 0, key)
            self.assertLess(shape, len(tlib.CHORD_SHAPES), key)

    def test_no_shipped_chord_sits_on_a_channel_where_it_draws_dead(self):
        # CHORD is refused on a take and on a sampler. A manifest that set a
        # shape on one of those would be asking for something the surface
        # says is impossible - and it would be right.
        with open(os.path.join(ROOT, "snapshot", "factory-manifest.json"),
                  encoding="utf-8") as fh:
            m = json.load(fh)
        takes = set(m.get("chords") or {})
        for key, spec in (m.get("voices") or {}).items():
            if spec.get("chord"):
                self.assertNotIn(key, takes,
                                 f"channel {key} has both a chord shape and "
                                 f"hand-authored chords")


class APresetSwapHasToTakeTheControllersWithIt(unittest.TestCase):
    """zynthian_processor.set_state calls set_preset FIRST and then writes
    every saved controller over the top, so a swap that keeps the old values
    loads the new patch and is then overwritten by the old one."""

    def proc(self, d, cid="7"):
        pid = next(iter(d["chains"][cid]["slots"][0]))
        return d["zs3"]["zs3-0"]["processors"][pid]

    def test_the_preset_path_is_built_in_the_lv2_shape(self):
        d, _state, _r = build()
        info = self.proc(d)["preset_info"]
        self.assertEqual(len(info), 4)
        self.assertTrue(info[0].endswith(
            "Obxd_003-KVR_Brass_Synths.presets.lv2/"
            "003-KVR_Brass_Synths_Analog_Brass_Chrds.ttl"))
        self.assertEqual(info[2], "Analog Brass Chrds")

    def test_the_index_is_null_because_it_is_re_derived_on_restore(self):
        d, _state, _r = build()
        self.assertIsNone(self.proc(d)["preset_info"][1])

    def test_the_bank_matches_the_bundle(self):
        d, _state, _r = build()
        proc = self.proc(d)
        self.assertTrue(proc["bank_info"][0].endswith(
            "Obxd_bank_003-KVR_Brass_Synths"))
        self.assertEqual(proc["bank_info"][2], "003-KVR_Brass_Synths")
        self.assertEqual(proc["preset_info"][3], proc["bank_info"][0])

    def test_the_old_presets_controllers_are_gone(self):
        d, _state, _r = build()
        self.assertEqual(sorted(self.proc(d)["controllers"]), ["voicecount"])

    def test_what_must_win_over_the_preset_survives(self):
        # 018 sat at voicecount 0.25, which is TWO voices on Obxd's own scale
        # points - a three-note chord would silently lose a note.
        d, _state, _r = build()
        self.assertEqual(
            self.proc(d)["controllers"]["voicecount"]["value"], 0.575)

    def test_a_preset_for_the_wrong_plugin_is_refused(self):
        m = manifest()
        m["presets"]["7"]["engine"] = "JV/padthv1"
        with self.assertRaises(ValueError):
            builder.build(base_snapshot(), m, KITS)

    def test_a_bundle_that_is_not_that_engines_is_refused(self):
        m = manifest()
        m["presets"]["7"]["bundle"] = "padthv1_67Padthv1Patches"
        with self.assertRaises(ValueError):
            builder.build(base_snapshot(), m, KITS)

    def test_a_chain_cannot_be_in_presets_and_controllers_at_once(self):
        m = manifest()
        m["controllers"]["7"] = {"voicecount": 0.1}
        with self.assertRaises(ValueError):
            builder.build(base_snapshot(), m, KITS)

    def test_an_untouched_chains_preset_is_still_untouched(self):
        d, _state, _r = build()
        self.assertEqual(self.proc(d, "8")["preset_info"][0], "a/preset.ttl")


class TheTempoIsWrittenInBothPlaces(unittest.TestCase):

    def test_the_riff_carries_it(self):
        d, _state, _r = build()
        blocks = builder.genre.parse_blocks(
            base64.b64decode(d["zynseq_riff_b64"]))
        vers = next(body for bid, body in blocks if bid == "vers")
        self.assertEqual(struct.unpack(">H", bytes(vers[4:6]))[0], 120)

    def test_the_drivers_own_globals_carry_it(self):
        _d, state, _r = build()
        self.assertEqual(state["globals"]["bpm"], 120)

    def test_the_report_says_whether_the_tempo_is_exact(self):
        _d, _state, report = build()
        self.assertIn("exact at 48 kHz", report[0])

    def test_an_inexact_tempo_is_called_out(self):
        _d, _state, report = build(tempo=137)
        self.assertIn("INEXACT", report[0])

    def test_the_globals_the_manifest_names_land(self):
        _d, state, _r = build()
        self.assertEqual(state["globals"]["root"], 7)

    def test_a_global_the_manifest_leaves_alone_survives(self):
        _d, state, _r = build()
        self.assertEqual(state["globals"]["master"], 80)


class TheWetLevelsUseTheDriversOwnScale(unittest.TestCase):

    def test_zero_percent_is_minus_seventy_db(self):
        self.assertEqual(builder.wet_db(0), -70.0)

    def test_a_hundred_percent_is_plus_ten_db(self):
        self.assertEqual(builder.wet_db(100), 10.0)

    def test_the_round_trip_returns_the_percentage(self):
        for percent in (0, 8, 22, 30, 35, 100):
            self.assertEqual(builder.wet_percent(builder.wet_db(percent)),
                             percent)

    def test_the_echos_two_sides_are_ganged(self):
        d, _state, _r = build()
        pid = next(iter(d["chains"]["3"]["slots"][1]))
        ctrls = d["zs3"]["zs3-0"]["processors"][pid]["controllers"]
        self.assertEqual(ctrls["lecholevel"]["value"],
                         ctrls["recholevel"]["value"])

    def test_the_dry_side_is_never_touched(self):
        d, _state, _r = build()
        pid = next(iter(d["chains"]["3"]["slots"][2]))
        ctrls = d["zs3"]["zs3-0"]["processors"][pid]["controllers"]
        self.assertEqual(ctrls["drylevel"]["value"], 0.0)

    def test_the_delay_time_lands_on_both_taps(self):
        d, _state, _r = build()
        pid = next(iter(d["chains"]["3"]["slots"][1]))
        ctrls = d["zs3"]["zs3-0"]["processors"][pid]["controllers"]
        self.assertEqual(ctrls["ldelay"]["value"], 250.0)
        self.assertEqual(ctrls["rhaasdelay"]["value"], 250.0)

    def test_the_delay_time_lands_on_every_chain_not_just_the_wet_ones(self):
        d, _state, _r = build()
        pid = next(iter(d["chains"]["7"]["slots"][1]))
        ctrls = d["zs3"]["zs3-0"]["processors"][pid]["controllers"]
        self.assertEqual(ctrls["ldelay"]["value"], 250.0)


class AModulatorsBaseIsComputedNeverDeclared(unittest.TestCase):

    def test_a_level_base_is_the_mixer_strip(self):
        _d, state, _r = build()
        self.assertEqual(state["mods"]["0|level"]["base"], 19)

    def test_a_wet_base_is_the_wet_this_run_wrote(self):
        _d, state, _r = build()
        self.assertEqual(state["mods"]["2|delay"]["base"], 30)

    def test_the_manifest_cannot_declare_a_base(self):
        m = manifest()
        m["mods"][0]["base"] = 99
        d, _r = builder.build(base_snapshot(), m, KITS)
        state = d["zs3"]["zs3-0"]["midi_capture"][PORT]["ctrldev_state"]
        self.assertEqual(state["mods"]["0|level"]["base"], 19)

    def test_the_key_is_channel_pipe_verb(self):
        _d, state, _r = build()
        self.assertEqual(sorted(state["mods"]), ["0|level", "2|delay"])

    def test_the_seed_counter_matches_the_number_of_modulators(self):
        _d, state, _r = build()
        self.assertEqual(state["mod_seed"], 2)

    def test_the_depth_multiplier_defaults_to_one(self):
        _d, state, _r = build()
        self.assertEqual(state["mod_depth_mult"], 1.0)

    def test_a_verb_the_instrument_refuses_is_refused_here(self):
        # gate and velo rewrite the pattern. An LFO on velo destroyed a
        # recorded take every 200 ms, unattended, and that is why they are out.
        for verb in ("gate", "velo"):
            m = manifest(mods=[{"channel": 0, "verb": verb, "depth": 10,
                                "rate": 0, "shape": "tri"}])
            with self.assertRaises(ValueError, msg=verb):
                builder.build(base_snapshot(), m, KITS)

    def test_a_drift_verb_is_refused_until_this_tool_can_place_one(self):
        m = manifest(mods=[{"channel": 0, "verb": "hits", "depth": 10,
                            "rate": 0, "shape": "tri"}])
        with self.assertRaises(ValueError):
            builder.build(base_snapshot(), m, KITS)


class ItRefusesWhatItCannotExpress(unittest.TestCase):

    def test_a_controller_the_processor_does_not_have(self):
        m = manifest(controllers={"6": {"_nonsense": 0.5}})
        with self.assertRaises(ValueError):
            builder.build(base_snapshot(), m, KITS)

    def test_a_controller_it_does_have(self):
        d, _r = builder.build(base_snapshot(), manifest(), KITS)
        pid = next(iter(d["chains"]["6"]["slots"][0]))
        ctrls = d["zs3"]["zs3-0"]["processors"][pid]["controllers"]
        self.assertEqual(ctrls["_decay"]["value"], 0.35)

    def test_a_controller_it_leaves_alone_keeps_its_value(self):
        d, _r = builder.build(base_snapshot(), manifest(), KITS)
        pid = next(iter(d["chains"]["6"]["slots"][0]))
        ctrls = d["zs3"]["zs3-0"]["processors"][pid]["controllers"]
        self.assertEqual(ctrls["_cutoff"]["value"], 0.6)

    def test_a_base_with_the_wrong_number_of_patterns(self):
        base = base_snapshot()
        blocks = builder.genre.parse_blocks(
            base64.b64decode(base["zynseq_riff_b64"]))
        blocks = [b for b in blocks if b[0] != "patn"][:1] + \
                 [b for b in blocks if b[0] == "patn"][:3]
        base["zynseq_riff_b64"] = base64.b64encode(
            builder.genre.build_blocks(blocks)).decode("ascii")
        with self.assertRaises(ValueError):
            builder.build(base, manifest(), KITS)


class ItTouchesNothingItWasNotAskedTo(unittest.TestCase):

    def test_an_lv2_preset_on_an_untouched_chain_survives(self):
        # The reason this is not build-genre-snapshots.py: that tool clears a
        # processor whenever the engine differs, which would throw away the
        # presets that ARE the factory sound.
        d, _r = builder.build(base_snapshot(), manifest(), KITS)
        pid = next(iter(d["chains"]["8"]["slots"][0]))
        proc = d["zs3"]["zs3-0"]["processors"][pid]
        self.assertEqual(proc["preset_info"][0], "a/preset.ttl")

    def test_the_kinds_override_survives(self):
        _d, state, _r = build()
        self.assertEqual(state["kinds"], {"4": "voice"})

    def test_ownership_survives(self):
        _d, state, _r = build()
        self.assertEqual(state["owners"]["7"], "gen")

    def test_the_mixer_is_not_restaged(self):
        d, _r = builder.build(base_snapshot(), manifest(), KITS)
        self.assertEqual(d["zs3"]["zs3-0"]["mixer"]["chan_00"]["level"], 0.19)

    def test_the_base_snapshot_itself_is_not_mutated(self):
        base = base_snapshot()
        builder.build(base, manifest(), KITS)
        state = base["zs3"]["zs3-0"]["midi_capture"][PORT]["ctrldev_state"]
        self.assertEqual(state["globals"]["bpm"], 125)
        self.assertEqual(state["voices"], {})


class TheSnapshotNamesItself(unittest.TestCase):

    def test_the_inherited_path_is_replaced(self):
        d, _r = builder.build(base_snapshot(), manifest(), KITS)
        self.assertEqual(
            d["last_snapshot_fpath"],
            "/zynthian/zynthian-my-data/snapshots/000/019-test.zss")

    def test_the_title_is_the_manifests_own(self):
        d, _r = builder.build(base_snapshot(), manifest(), KITS)
        self.assertEqual(d["zs3"]["zs3-0"]["title"], "Test")


class TheShippedManifestIsValid(unittest.TestCase):
    """Not a fixture - the file that actually builds the factory snapshot."""

    def setUp(self):
        path = os.path.join(ROOT, "snapshot", "factory-manifest.json")
        with open(path, encoding="utf-8") as fh:
            self.m = json.load(fh)

    def test_it_names_a_base_that_exists(self):
        self.assertTrue(os.path.exists(os.path.join(ROOT, self.m["base"])))

    def test_its_tempo_is_exact_at_48_kilohertz(self):
        # zynseq truncates frames-per-clock to a whole frame with no
        # accumulator, so the error is zero only when the tempo divides 30000.
        self.assertEqual(30000 % self.m["tempo"], 0)

    def test_every_kit_it_names_is_one_the_scan_knows(self):
        with open(os.path.join(TOOLS, "drum-kit-notes.json"),
                  encoding="utf-8") as fh:
            known = json.load(fh)["notes"]
        for spec in self.m["drums"].values():
            self.assertIn(spec["kit"], known)

    def test_every_modulated_verb_is_one_a_modulator_may_drive(self):
        for mod in self.m["mods"]:
            self.assertTrue(tlib.mod_allowed(mod["verb"]), mod["verb"])
            self.assertFalse(tlib.is_drift(mod["verb"]), mod["verb"])

    def test_every_rate_and_shape_is_one_a_pad_can_reach(self):
        for mod in self.m["mods"]:
            self.assertLess(mod["rate"], len(tlib.MOD_RATES))
            self.assertIn(mod["shape"], tlib.MOD_SHAPES)

    def test_the_delay_time_is_an_eighth_at_its_own_tempo(self):
        # 1/8 in ms is 30000 / BPM. A dub echo that is not in time is not a
        # dub echo.
        self.assertAlmostEqual(self.m["delay_ms"], 30000.0 / self.m["tempo"],
                               places=1)

    def test_it_builds(self):
        with open(os.path.join(ROOT, self.m["base"]), encoding="utf-8") as fh:
            base = json.load(fh)
        with open(os.path.join(TOOLS, "drum-kit-notes.json"),
                  encoding="utf-8") as fh:
            kits = json.load(fh)["notes"]
        d, report = builder.build(base, self.m, kits)
        self.assertTrue(report)
        self.assertIn("zynseq_riff_b64", d)


if __name__ == "__main__":
    unittest.main()
