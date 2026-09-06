"""Tests for the genre/drone pack builder.

Two kinds live here and the split is deliberate:

* **Unit tests** build their own base snapshot in memory, the way
  `test_build_factory_snapshot.py` does, so they say what one lever means
  without depending on anything shipped.

* **One regression test rebuilds both SHIPPED manifests and compares against
  the 71 shipped `.zss` files, byte for byte.** That is the guard the seven
  new levers were added behind: every one of them is opt-in, and an absent key
  must produce exactly the file the builder produced before it existed. It
  reads from `snapshot/` and writes nothing there.
"""

import base64
import copy
import importlib.util
import json
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(ROOT, "ctrldev"))

from maschine_mk2_lib import maschine_mk2_lib as lib      # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), os.path.join(TOOLS, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _load("build-genre-snapshots")
sys.path.insert(0, TOOLS)
from zss_riff import parse_blocks, build_blocks           # noqa: E402

KITS = {"Roland TR909": [36, 40, 50, 42, 46]}


def riff(tempo=125):
    """A vers block and eight patn blocks, the shape the rig writes: 4 beats
    at 4 steps per beat, one event each so the template exists."""
    out = bytearray()
    vers = bytearray(16)
    struct.pack_into(">H", vers, 4, tempo)
    out += b"vers" + struct.pack(">I", len(vers)) + vers
    for pid in range(10, 18):
        body = bytearray(builder.PATN_HEADER)
        struct.pack_into(">I", body, 0, pid)
        struct.pack_into(">I", body, builder.PATN_BEATS, 4)
        struct.pack_into(">H", body, builder.PATN_SPB, 4)
        body[builder.PATN_SWING_DIV] = 1
        builder.write_bcd(body, builder.PATN_CHANCE, 1.0)
        event = bytearray(builder.PATN_EVENT)
        event[13] = 60
        event[14] = 100
        out += b"patn" + struct.pack(">I", len(body) + len(event)) + body + event
    return bytes(out)


def base_snapshot():
    chains = {str(i): {"slots": [{f"p{i}": "LS"}, {f"e{i}a": "JV/TAP Stereo Echo"},
                                 {f"e{i}b": "JV/TAP Reverberator"}]}
              for i in range(1, 9)}
    procs = {}
    for i in range(1, 9):
        procs[f"p{i}"] = {"bank_info": None, "preset_info": None,
                          "bank_subdir_info": None, "preset_subdir_info": None,
                          "controllers": {}}
        for suffix in ("a", "b"):
            procs[f"e{i}{suffix}"] = {"bank_info": None, "preset_info": None,
                                      "bank_subdir_info": None,
                                      "preset_subdir_info": None, "controllers": {}}
    mixer = {f"chan_{i:02d}": {"level": 0.19} for i in range(8)}
    mixer["chan_16"] = {"level": 0.77}
    return {
        "chains": chains,
        "zs3": {"zs3-0": {
            "title": "base",
            "processors": procs,
            "mixer": mixer,
            "midi_capture": {builder.CTRLDEV_PORT: {"ctrldev_state": {
                "globals": {"root": 9, "scale": 0, "bpm": 132, "master": 80,
                            "walk": 0, "wspan": 2, "revsize": 25, "revtype": 3,
                            "dlytime": 1, "dlyfbk": 35},
            }}},
        }},
        "zynseq_riff_b64": base64.b64encode(riff()).decode("ascii"),
        "last_snapshot_fpath": "/x/017.zss",
    }


def entry(**over):
    e = {
        "file": "900-test", "title": "Test", "genre": "test", "tempo": 125,
        "root": 0, "scale": 0,
        "drums": {"kits": ["Roland TR909"] * 5,
                  "steps": [[0, 4, 8, 12], [4, 12], [4, 12], [2, 6, 10, 14], [6, 14]],
                  "velo": [110, 96, 100, 84, 88],
                  "gate": [40, 40, 40, 25, 70]},
        "voices": {"engines": ["JV/JC303", "JV/Obxd", "JV/padthv1"],
                   "rhythm_reg": [4369, 17476, 1], "register": [40, 24222, 9974],
                   "length": [16, 16, 16], "octave": [0, 0, 1], "range": [1, 2, 1],
                   "velo": [110, 96, 80], "gate": [35, 45, 800]},
        "fx": ["JV/TAP Stereo Echo", "JV/TAP Reverberator"],
    }
    e.update(over)
    return e


def built(**over):
    return builder.build_one(base_snapshot(), entry(**over), KITS)


def state_of(doc):
    return doc["zs3"]["zs3-0"]["midi_capture"][builder.CTRLDEV_PORT]["ctrldev_state"]


def patns_of(doc):
    return [b for b in parse_blocks(base64.b64decode(doc["zynseq_riff_b64"]))
            if b[0] == "patn"]


def steps_of(body):
    n = (len(body) - builder.PATN_HEADER) // builder.PATN_EVENT
    out = []
    for i in range(n):
        off = builder.PATN_HEADER + i * builder.PATN_EVENT
        out.append(struct.unpack(">I", bytes(body[off:off + 4]))[0])
    return out


class FixedPointCase(unittest.TestCase):
    """zynseq calls it BCD and it is not: u16 of the fraction x 10000, then
    u16 of the units."""

    def test_round_trip(self):
        body = bytearray(32)
        for value in (0.0, 0.16, 0.5, 1.0, 2.75, 8.0, 99.9999):
            builder.write_bcd(body, 0, value)
            self.assertAlmostEqual(builder.read_bcd(body, 0), value, places=4)

    def test_the_fraction_carries_instead_of_overflowing(self):
        # 0.99996 rounds to 10000/10000, which would write a fraction field
        # that is not a fraction. It has to become the next whole unit.
        body = bytearray(32)
        builder.write_bcd(body, 0, 0.99996)
        frac, units = struct.unpack(">HH", bytes(body[0:4]))
        self.assertLess(frac, 10000)
        self.assertEqual(units, 1)

    def test_it_is_the_layout_the_rig_writes(self):
        body = bytearray(32)
        builder.write_bcd(body, 0, 1.0)
        self.assertEqual(bytes(body[0:4]), struct.pack(">HH", 0, 1))


class DivisionCase(unittest.TestCase):
    def test_labels_and_indices_both_resolve(self):
        self.assertEqual(builder.div_index("1/16"), 1)
        self.assertEqual(builder.div_index(1), 1)
        self.assertEqual(builder.div_index("1/4"), 5)

    def test_an_unknown_division_is_refused(self):
        with self.assertRaises(ValueError):
            builder.div_index("1/3")
        with self.assertRaises(ValueError):
            builder.div_index(99)

    def test_beats_comes_from_the_table_not_the_manifest(self):
        # A voice is re-stamped to DIVISIONS[div][2] within a second of every
        # load, so any other beat count is a file that disagrees with itself.
        for idx, (_label, spb, beats) in enumerate(lib.DIVISIONS):
            body = bytearray(32)
            count = builder.set_division(body, idx)
            self.assertEqual(struct.unpack(">I", bytes(body[4:8]))[0], beats)
            self.assertEqual(struct.unpack(">H", bytes(body[8:10]))[0], spb)
            self.assertEqual(count, spb * beats)

    def test_one_over_four_is_a_four_bar_loop(self):
        # The lever the drone pack needed and could not reach: 16 steps that
        # are beats, so gate 800 holds two bars instead of half of one.
        body = bytearray(32)
        self.assertEqual(builder.set_division(body, builder.div_index("1/4")), 16)
        self.assertEqual(struct.unpack(">I", bytes(body[4:8]))[0], 16)   # beats

    def test_a_channel_at_one_over_four_gets_the_new_header(self):
        doc = built(div=["1/4"] * 8)
        for body in patns_of(doc):
            self.assertEqual(struct.unpack(">I", bytes(body[1][4:8]))[0], 16)
            self.assertEqual(struct.unpack(">H", bytes(body[1][8:10]))[0], 1)

    def test_channels_may_differ(self):
        doc = built(div=["1/16"] * 5 + ["1/4", "1/8", "1/4"])
        bodies = [b[1] for b in patns_of(doc)]
        spb = [struct.unpack(">H", bytes(b[8:10]))[0] for b in bodies]
        self.assertEqual(spb, [4, 4, 4, 4, 4, 1, 2, 1])

    def test_div_needs_eight_entries(self):
        with self.assertRaises(ValueError):
            built(div=["1/16"] * 5)

    def test_a_step_past_the_division_is_refused(self):
        # 1/8T is twelve steps, so a step list reaching 14 is a groove written
        # for a grid this channel does not have.
        e = entry(div=["1/8T"] * 8)
        e["drums"]["steps"][3] = [2, 6, 10, 14]
        with self.assertRaises(ValueError):
            builder.build_one(base_snapshot(), e, KITS)


class GrooveCase(unittest.TestCase):
    def test_the_three_fields_round_trip(self):
        doc = built(groove={"swing": [0.16] * 8, "human_time": [0.03] * 8,
                            "human_velo": [8.0] * 8})
        body = patns_of(doc)[0][1]
        self.assertAlmostEqual(builder.read_bcd(body, builder.PATN_SWING_AMT),
                               0.16, places=4)
        self.assertAlmostEqual(builder.read_bcd(body, builder.PATN_HUMAN_TIME),
                               0.03, places=4)
        self.assertAlmostEqual(builder.read_bcd(body, builder.PATN_HUMAN_VELO),
                               8.0, places=4)

    def test_swing_is_per_channel(self):
        # Swung hats over a straight kick is the whole point, and swingAmount
        # is per pattern, so it costs one number per channel.
        doc = built(groove={"swing": [0.0, 0.0, 0.0, 0.20, 0.0, 0.0, 0.0, 0.0]})
        bodies = [b[1] for b in patns_of(doc)]
        self.assertAlmostEqual(builder.read_bcd(bodies[0], builder.PATN_SWING_AMT), 0.0)
        self.assertAlmostEqual(builder.read_bcd(bodies[3], builder.PATN_SWING_AMT),
                               0.20, places=4)

    def test_swing_div_is_always_one(self):
        # `_force_swing_div()` sets it to 1 on init AND on every snapshot
        # restore, so writing 2 or 4 would be overwritten in silence.
        doc = built(groove={"swing": [0.16] * 8})
        for _bid, body in patns_of(doc):
            self.assertEqual(body[builder.PATN_SWING_DIV], builder.FORCED_SWING_DIV)

    def test_a_negative_swing_is_refused_rather_than_wrapped(self):
        # The field is unsigned fixed point; a negative would be written as a
        # very large positive and the pattern would fall apart.
        with self.assertRaises(ValueError):
            built(groove={"swing": [-0.1] * 8})


class MixerCase(unittest.TestCase):
    def test_the_faders_are_written(self):
        levels = [0.78, 0.62, 0.66, 0.44, 0.38, 0.58, 0.34, 0.28]
        doc = built(mix=levels)
        for i, want in enumerate(levels):
            self.assertAlmostEqual(
                doc["zs3"]["zs3-0"]["mixer"][f"chan_{i:02d}"]["level"], want)

    def test_the_main_strip_is_chan_16(self):
        doc = built(main=0.80)
        self.assertAlmostEqual(
            doc["zs3"]["zs3-0"]["mixer"]["chan_16"]["level"], 0.80)

    def test_an_absent_mix_leaves_the_base_alone(self):
        doc = built()
        for i in range(8):
            self.assertAlmostEqual(
                doc["zs3"]["zs3-0"]["mixer"][f"chan_{i:02d}"]["level"], 0.19)

    def test_out_of_range_is_refused(self):
        with self.assertRaises(ValueError):
            built(mix=[1.4] + [0.5] * 7)
        with self.assertRaises(ValueError):
            built(mix=[0.5] * 7)


class GlobalsCase(unittest.TestCase):
    def test_the_seven_keys_are_written(self):
        g = {"master": 78, "revsize": 70, "revtype": 19, "dlytime": 3,
             "dlyfbk": 55, "walk": 8, "wspan": 2}
        got = state_of(built(globals=g))["globals"]
        for k, v in g.items():
            self.assertEqual(got[k], v)

    def test_bpm_root_and_scale_still_come_from_the_top_level(self):
        got = state_of(built())["globals"]
        self.assertEqual((got["bpm"], got["root"], got["scale"]), (125, 0, 0))

    def test_an_unknown_global_is_not_written(self):
        # `set_state` drops a key it does not already hold, in silence. A
        # builder that passed it through would put a value in the file that
        # nothing reads and the surface never shows.
        got = state_of(built(globals={"nonsense": 1}))["globals"]
        self.assertNotIn("nonsense", got)


class VoiceCase(unittest.TestCase):
    def test_chord_is_written_when_asked(self):
        v = dict(entry()["voices"], chord=[0, 3, 0])
        got = state_of(built(voices=v))["voices"]
        self.assertEqual(got["6"]["chord"], 3)

    def test_chord_zero_is_absent_because_absent_reads_zero(self):
        # Shape 0 returns exactly what pitch() returned, so a file with no
        # `chord` key and a file with 0 are the same instrument. Keeping the
        # key out is what makes the old manifests build byte-identically.
        got = state_of(built())["voices"]
        self.assertNotIn("chord", got["5"])

    def test_random_and_rhythm_come_from_the_manifest(self):
        v = dict(entry()["voices"], random=[0, 0, 12], rhythm=[0, 4, 8])
        got = state_of(built(voices=v))["voices"]
        self.assertEqual((got["7"]["random"], got["6"]["rhythm"]), (12, 4))

    def test_they_default_to_off(self):
        got = state_of(built())["voices"]
        self.assertEqual((got["5"]["random"], got["5"]["rhythm"]), (0, 0))

    def test_a_scalar_is_refused(self):
        v = dict(entry()["voices"], chord=3)
        with self.assertRaises(ValueError):
            built(voices=v)


class DrumsBlockCase(unittest.TestCase):
    def test_euclid_matches_the_drivers_own_placement(self):
        self.assertEqual(builder.euclid_steps(16, 4, 0), [0, 4, 8, 12])
        self.assertEqual(builder.euclid_steps(16, 2, 4), [4, 12])
        self.assertEqual(builder.euclid_steps(16, 1, 12), [12])
        self.assertEqual(builder.euclid_steps(16, 8, 0), list(range(0, 16, 2)))

    def test_the_rhythm_register_subtracts(self):
        # 61439 clears bit 12: the three-kick bar.
        self.assertEqual(builder.euclid_steps(16, 4, 0, 61439), [0, 4, 8])

    def test_the_hand_register_adds(self):
        self.assertEqual(builder.euclid_steps(16, 4, 0, 0xFFFF, 1 << 3),
                         [0, 3, 4, 8, 12])

    def test_a_hits_manifest_writes_the_drums_block(self):
        e = entry()
        e["drums"]["hits"] = [4, 2, 1, 8, 2]
        e["drums"]["rotate"] = [0, 4, 12, 0, 6]
        got = state_of(builder.build_one(base_snapshot(), e, KITS))["drums"]
        self.assertEqual(got["0"]["hits"], 4)
        self.assertEqual(got["1"]["rotate"], 4)
        self.assertEqual(got["2"]["rhythm_reg"], 0xFFFF)
        self.assertEqual(got["0"]["hand_reg"], 0)

    def test_the_pattern_agrees_with_the_block(self):
        # The whole reason the block exists: the panel's HITS and the riff's
        # steps must be the same groove, or the first encoder turn destroys it.
        e = entry()
        e["drums"]["hits"] = [4, 2, 1, 8, 2]
        e["drums"]["rotate"] = [0, 4, 12, 0, 6]
        doc = builder.build_one(base_snapshot(), e, KITS)
        bodies = [b[1] for b in patns_of(doc)]
        self.assertEqual(steps_of(bodies[0]), [0, 4, 8, 12])
        self.assertEqual(steps_of(bodies[1]), [4, 12])
        self.assertEqual(steps_of(bodies[2]), [12])

    def test_no_block_when_the_manifest_is_the_old_literal_kind(self):
        self.assertNotIn("drums", state_of(built()))


class WetsCase(unittest.TestCase):
    """The STATIC SEND lever - todo item 50.

    Until it existed nothing but a modulator ever wrote a wet port, so five to
    seven channels of every pack entry were dry on load whatever the entry's
    globals said about the room. The lever is opt-in: an entry with no `wets`
    key writes no wet, which is what keeps the 71 shipped files byte-identical.

    IT RESOLVES THE PORT THROUGH tlib.FX_ROLES, NEVER BY PLUGIN NAME. Twelve of
    the nineteen insert pairs the two packs use are not the TAP pair, and their
    wets are different symbols in different units - Dragonfly's is TWO linear
    ports (early and late reflections, not left and right), Tal's is one 0..1.
    A hardcoded `wetlevel` would have written nothing on 30 of 71 entries and
    said nothing about it."""

    def inserts(self, doc, cid):
        chain = doc["chains"][cid]
        out = {}
        for slot in chain["slots"][1:]:
            pid, code = next(iter(slot.items()))
            out[code.split("/")[-1]] = doc["zs3"]["zs3-0"]["processors"][pid]
        return out

    def test_a_reverb_send_is_written_in_the_plugins_own_units(self):
        doc = built(wets={"6": {"reverb": 30}})
        procs = self.inserts(doc, "6")
        self.assertAlmostEqual(
            procs["TAP Reverberator"]["controllers"]["wetlevel"]["value"],
            builder.tlib.wet_db(30))

    def test_a_delay_send_writes_both_ganged_ports(self):
        doc = built(wets={"6": {"delay": 45}})
        ctrls = self.inserts(doc, "6")["TAP Stereo Echo"]["controllers"]
        want = builder.tlib.wet_db(45)
        self.assertAlmostEqual(ctrls["lecholevel"]["value"], want)
        self.assertAlmostEqual(ctrls["recholevel"]["value"], want)

    def test_it_follows_the_role_table_onto_a_non_tap_insert(self):
        doc = built(fx=["JV/TAP Stereo Echo", "JV/Dragonfly Room Reverb"],
                    wets={"6": {"reverb": 50}})
        ctrls = self.inserts(doc, "6")["Dragonfly Room Reverb"]["controllers"]
        self.assertAlmostEqual(ctrls["early_level"]["value"], 50.0)
        self.assertAlmostEqual(ctrls["late_level"]["value"], 50.0)
        self.assertNotIn("wetlevel", ctrls)

    def test_a_crossfade_is_held_below_the_ceiling(self):
        doc = built(fx=["JV/TAP Stereo Echo", "JV/Shiroverb"],
                    wets={"6": {"reverb": 100}})
        ctrls = self.inserts(doc, "6")["Shiroverb"]["controllers"]
        self.assertAlmostEqual(ctrls["mix"]["value"],
                               100.0 * builder.tlib.CROSSFADE_CEILING)

    def test_zero_writes_the_floor_rather_than_nothing(self):
        doc = built(wets={"6": {"reverb": 0}})
        ctrls = self.inserts(doc, "6")["TAP Reverberator"]["controllers"]
        self.assertEqual(ctrls["wetlevel"]["value"], builder.tlib.WET_OFF)

    def test_an_absent_key_writes_no_wet_at_all(self):
        ctrls = self.inserts(built(), "6")["TAP Reverberator"]["controllers"]
        self.assertEqual(ctrls, {})

    def test_it_writes_only_the_chains_it_names(self):
        doc = built(wets={"6": {"reverb": 30}})
        self.assertEqual(
            self.inserts(doc, "7")["TAP Reverberator"]["controllers"], {})

    def test_a_role_the_pair_cannot_serve_is_refused(self):
        with self.assertRaises(ValueError):
            built(fx=["JV/TAP Reverberator", "JV/TAP Reverberator"],
                  wets={"6": {"delay": 20}})

    def test_an_unknown_role_name_is_refused(self):
        with self.assertRaises(ValueError):
            built(wets={"6": {"chorus": 20}})

    def test_a_percent_outside_the_surface_is_refused(self):
        with self.assertRaises(ValueError):
            built(wets={"6": {"reverb": 130}})
        with self.assertRaises(ValueError):
            built(wets={"6": {"reverb": -1}})

    def test_a_chain_that_is_not_there_is_refused(self):
        with self.assertRaises(ValueError):
            built(wets={"9": {"reverb": 20}})

    def test_a_wet_that_disagrees_with_its_modulator_is_refused(self):
        """The same law as `mix` against a `level` modulator: the driver writes
        base+offset within 200 ms of load, so a static send that disagrees is
        overwritten and the file is not what it sounds like."""
        with self.assertRaises(ValueError):
            built(wets={"6": {"reverb": 30}},
                  mods=[{"channel": 5, "verb": "reverb", "depth": 10,
                         "rate": 3, "shape": "tri", "base": 60}])

    def test_a_wet_that_agrees_with_its_modulator_is_allowed(self):
        doc = built(wets={"6": {"reverb": 60}},
                    mods=[{"channel": 5, "verb": "reverb", "depth": 10,
                           "rate": 3, "shape": "tri", "base": 60}])
        ctrls = self.inserts(doc, "6")["TAP Reverberator"]["controllers"]
        self.assertAlmostEqual(ctrls["wetlevel"]["value"], builder.tlib.wet_db(60))


class ShippedPacksCase(unittest.TestCase):
    """THE REGRESSION GUARD for all seven new levers.

    Every one is opt-in, and the two shipped manifests use none of them - so
    they must still produce the 71 shipped files byte for byte. This is the
    test that says the levers were ADDED rather than the builder changed."""

    def rebuild(self, manifest, shipped):
        def _read(*parts):
            with open(os.path.join(ROOT, *parts)) as fh:
                return json.load(fh)

        base = _read("snapshot", "017-generative-techno.zss")
        kits = _read("tools", "drum-kit-notes.json")["notes"]
        entries = _read("snapshot", manifest)
        self.assertGreater(len(entries), 0)
        for e in entries:
            doc = builder.build_one(copy.deepcopy(base), e, kits)
            doc["last_snapshot_fpath"] = (
                "/zynthian/zynthian-my-data/snapshots/000/" + e["file"] + ".zss")
            with open(os.path.join(ROOT, "snapshot", shipped,
                                   e["file"] + ".zss")) as fh:
                want = fh.read()
            self.assertEqual(json.dumps(doc, indent=2), want,
                             f"{e['file']} no longer builds byte-identically")

    def test_the_genre_pack_is_unchanged(self):
        self.rebuild("genre-pack-manifest.json", "genre-pack")

    def test_the_drone_ambient_pack_is_unchanged(self):
        self.rebuild("drone-ambient-manifest.json", "drone-ambient")


if __name__ == "__main__":
    unittest.main()
