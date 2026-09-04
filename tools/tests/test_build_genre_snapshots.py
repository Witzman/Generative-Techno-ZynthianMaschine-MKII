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
