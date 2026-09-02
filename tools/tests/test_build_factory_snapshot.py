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
                   "6": {"empty": True}},
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
        self.assertEqual(state["voices"]["6"]["rhythm_reg"], 0)
        raw = base64.b64decode(d["zynseq_riff_b64"])
        self.assertEqual(events(raw, 6), [])

    def test_empty_also_switches_generation_off(self):
        # An empty channel that was still evolving would fill itself in the
        # moment anything moved the register.
        _d, state, _r = build()
        self.assertEqual(state["voices"]["6"]["random"], 0)
        self.assertEqual(state["voices"]["6"]["rhythm"], 0)

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
