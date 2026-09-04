"""Tests for the manifest validator.

The validator's whole job is to DISCRIMINATE, so most of these take a clean
entry and break exactly one thing. Two of them are the other direction: the
71 shipped presets must all fail, and the plan's rebuilt template must pass -
a checker that passes everything or fails everything is worth nothing.
"""

import copy
import glob
import importlib.util
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(ROOT, "ctrldev"))

from techno_lib import techno_lib as tlib                 # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), os.path.join(TOOLS, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vm = _load("validate-manifest")

KITS = {"Roland TR909": [36, 40, 50, 42, 46],
        "Alesis HR16": [36, 53, 53, 77, 77]}

# The plan's five-layer drone template, which the validator must pass.
CLEAN = {
    "file": "900-clean", "genre": "drone", "tempo": 60, "root": 7, "scale": 0,
    "div": ["1/4", "1/4", "1/8", "1/16", "1/16", "1/4", "1/8", "1/16"],
    "mix": [0.58, 0.46, 0.36, 0.0, 0.0, 0.28, 0.12, 0.0],
    "main": 0.78,
    "drums": {"kits": ["Roland TR909"] * 5, "hits": [0] * 5,
              "rotate": [0] * 5, "velo": [70] * 5, "gate": [40] * 5},
    "overrides": {
        "0": {"engine": "JV/amsynth", "register": 3, "length": 8,
              "rhythm_reg": 257, "octave": -1, "range": 1, "velo": 90,
              "gate": 800, "chord": 0},
        "1": {"engine": "JV/String machine", "register": 4, "length": 8,
              "rhythm_reg": 1028, "octave": 0, "range": 1, "velo": 84,
              "gate": 800, "chord": 2},
        "2": {"engine": "JV/Mutated Instruments", "register": 119,
              "length": 8, "rhythm_reg": 4228, "octave": 1, "range": 1,
              "velo": 76, "gate": 800, "chord": 3},
    },
    "voices": {"engines": ["JV/Helm", "JV/Kars", "JV/padthv1"],
               "register": [183, 6, 1], "length": [8, 8, 8],
               "rhythm_reg": [2056, 8224, 0], "octave": [2, 2, 0],
               "range": [1, 2, 1], "velo": [68, 60, 60],
               "gate": [800, 800, 800], "chord": [5, 0, 0]},
    "fx": ["JV/TAP Stereo Echo", "JV/TAP Reverberator"],
}


def fails(entry):
    return [m for sev, m in vm.check(entry, KITS) if sev == "FAIL"]


def warns(entry):
    return [m for sev, m in vm.check(entry, KITS) if sev == "WARN"]


def broken(**changes):
    e = copy.deepcopy(CLEAN)
    for path, value in changes.items():
        node = e
        parts = path.split("__")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return e


class MinIntervalCase(unittest.TestCase):
    def test_it_widens_as_it_descends(self):
        self.assertEqual(vm.min_interval(30), 12)
        self.assertEqual(vm.min_interval(40), 7)
        self.assertEqual(vm.min_interval(50), 3)
        self.assertEqual(vm.min_interval(65), 2)
        self.assertEqual(vm.min_interval(80), 1)

    def test_it_is_monotonic(self):
        wants = [vm.min_interval(n) for n in range(0, 128)]
        self.assertEqual(wants, sorted(wants, reverse=True))


class TheCleanTemplateCase(unittest.TestCase):
    def test_the_plans_template_passes(self):
        self.assertEqual(fails(CLEAN), [])

    def test_it_passes_in_every_non_pentatonic_scale(self):
        # PENT is the known exception - five degrees make a TRI span 1.6
        # octaves, so MID reaches into HIGH. It needs the four-layer variant
        # and there is a test for that below.
        for scale in range(len(tlib.SCALES)):
            if tlib.SCALES[scale][0] == "PENT":
                continue
            for root in range(12):
                e = broken(scale=scale, root=root)
                self.assertEqual(fails(e), [],
                                 f"{tlib.NOTE_NAMES[root]} "
                                 f"{tlib.SCALES[scale][0]}")

    def test_pentatonic_needs_the_sparse_variant(self):
        five = broken(scale=5)
        self.assertNotEqual(fails(five), [])
        four = copy.deepcopy(five)
        # Drop HIGH and take MID down to a fifth: the four-layer template.
        four["voices"]["rhythm_reg"][0] = 0
        four["overrides"]["2"]["chord"] = 2
        four["voices"]["register"][1] = 4
        self.assertEqual(fails(four), [])


class OneThingBrokenCase(unittest.TestCase):
    def test_a_unison_between_channels_is_caught(self):
        # Put AIR back where the expert's first draft had it: exactly on the
        # MID chord's top note.
        e = broken(voices__register=[183, 201, 1])
        self.assertTrue(any("UNISON" in m for m in fails(e)), fails(e))

    def test_a_semitone_in_the_bass_is_caught(self):
        # Two channels an octave apart is fine; a semitone apart down there is
        # one rough tone beating at 4 Hz.
        e = copy.deepcopy(CLEAN)
        e["overrides"]["1"]["register"] = 3      # onto SUB's own degree
        e["overrides"]["1"]["octave"] = -1
        e["overrides"]["1"]["chord"] = 0
        e["overrides"]["1"]["rhythm_reg"] = 257  # and at the same instant
        self.assertTrue(any("UNISON" in m or "gap" in m for m in fails(e)))

    def test_an_octave_apart_is_never_a_clash(self):
        self.assertFalse(any("gap" in m or "UNISON" in m for m in fails(CLEAN)))

    def test_attacks_landing_together_are_caught(self):
        # Move BASS back onto beat 1, where MID already is.
        e = copy.deepcopy(CLEAN)
        e["overrides"]["1"]["rhythm_reg"] = 514
        self.assertTrue(any("attack together" in m for m in fails(e)), fails(e))

    def test_the_onset_budget_bites(self):
        e = broken(voices__rhythm_reg=[65535, 8224, 0])
        self.assertTrue(any("onsets/bar" in m for m in fails(e)), fails(e))

    def test_a_second_channel_in_the_low_register_is_caught(self):
        e = copy.deepcopy(CLEAN)
        e["voices"]["octave"] = [-1, 2, 0]       # HIGH dragged into the bass
        e["voices"]["chord"] = [0, 0, 0]
        self.assertTrue(any("below MIDI 48" in m for m in fails(e)), fails(e))

    def test_a_step_outside_the_division_is_caught(self):
        e = copy.deepcopy(CLEAN)
        del e["drums"]["hits"]
        e["div"] = ["1/8T"] * 8                  # twelve steps, not sixteen
        e["drums"]["steps"] = [[0], [], [], [2, 6, 10, 14], []]
        self.assertTrue(any("outside" in m for m in fails(e)), fails(e))

    def test_two_drum_channels_on_one_kit_note_are_caught(self):
        # 035-house-garage's real defect: snare and clap are both HR16 note 53
        # on identical steps, so one sample plays twice.
        e = copy.deepcopy(CLEAN)
        e["genre"] = "house"
        e["div"] = ["1/16"] * 8
        del e["overrides"]
        e["drums"]["kits"] = ["Alesis HR16"] * 5
        e["drums"]["hits"] = [4, 2, 2, 0, 0]
        e["drums"]["rotate"] = [0, 4, 4, 0, 0]
        e["voices"]["rhythm_reg"] = [0, 0, 0]
        self.assertTrue(any("one sample played twice" in m for m in fails(e)),
                        fails(e))

    def test_a_level_modulator_that_disagrees_with_its_fader_is_caught(self):
        e = broken(mods=[{"channel": 2, "verb": "level", "depth": 18,
                          "rate": 0, "shape": "tri", "base": 22, "seed": 1}])
        self.assertTrue(any("overwrites the fader" in m for m in fails(e)),
                        fails(e))

    def test_a_level_modulator_that_agrees_passes(self):
        e = broken(mods=[{"channel": 2, "verb": "level", "depth": 18,
                          "rate": 0, "shape": "tri", "base": 36, "seed": 1}])
        self.assertEqual(fails(e), [])

    def test_a_modulator_on_a_pattern_verb_is_caught(self):
        e = broken(mods=[{"channel": 2, "verb": "velo", "depth": 18,
                          "rate": 0, "shape": "tri", "base": 50, "seed": 1}])
        self.assertTrue(any("rewrites the pattern" in m for m in fails(e)),
                        fails(e))

    def test_a_rate_index_out_of_range_is_caught(self):
        e = broken(mods=[{"channel": 2, "verb": "reverb", "depth": 18,
                          "rate": 99, "shape": "tri", "base": 40, "seed": 1}])
        self.assertTrue(any("rate index" in m for m in fails(e)), fails(e))

    def test_an_insert_in_no_table_is_caught(self):
        e = broken(fx=["JV/Nothing At All", "JV/TAP Reverberator"])
        self.assertTrue(any("neither FX_ROLES" in m for m in fails(e)), fails(e))

    def test_a_missing_role_warns_rather_than_fails(self):
        # A pack MAY ship without a delay - it is a choice, not a corruption -
        # but the knob is dead and somebody has to have been told.
        e = broken(fx=["JV/YK Chorus", "JV/TAP Reverberator"])
        self.assertEqual(fails(e), [])
        self.assertTrue(any("dead on all eight chains" in m for m in warns(e)))

    def test_a_gate_above_the_encoder_ceiling_warns(self):
        e = copy.deepcopy(CLEAN)
        e["voices"]["gate"] = [1600, 800, 800]
        self.assertTrue(any("GATE_MAX" in m for m in warns(e)), warns(e))


class TheCarpetRuleCase(unittest.TestCase):
    """A channel on half its steps or more already occupies every beat, so
    counting it leaves the per-step budget one smaller everywhere. Reasoning
    said three channels per step; rendering the classic house bar - kick,
    rimshot and clap together on the four, hat underneath - said the hat is
    texture, not a fourth transient."""

    def house(self, **drums):
        e = copy.deepcopy(CLEAN)
        e.update(genre="house", tempo=125, root=0, scale=0,
                 div=["1/16"] * 8,
                 mix=[0.78, 0.62, 0.66, 0.44, 0.38, 0.58, 0.34, 0.28])
        del e["overrides"]
        e["drums"] = {"kits": ["Roland TR909"] * 5,
                      "hits": drums.get("hits", [4, 1, 2, 8, 2]),
                      "rotate": drums.get("rotate", [0, 12, 4, 0, 6]),
                      "velo": [118, 88, 104, 76, 92],
                      "gate": [40, 40, 40, 25, 70]}
        e["voices"] = {"engines": ["JV/Monique", "JV/Obxd", "JV/padthv1"],
                       "register": [40, 119, 183], "length": [16, 8, 8],
                       "rhythm_reg": [17476, 1028, 8], "octave": [0, 1, 3],
                       "range": [1, 1, 1], "velo": [110, 96, 80],
                       "gate": [55, 200, 700], "chord": [0, 5, 2],
                       "random": [0, 0, 0], "rhythm": [0, 0, 0]}
        e["mods"] = []
        return e

    def test_the_classic_house_bar_passes(self):
        # kick + rim + clap on the four, an eighth hat running underneath.
        self.assertEqual(fails(self.house()), [])

    def test_an_eighth_hat_is_named_as_a_carpet_when_something_does_break(self):
        # Add a fourth real transient on the four and the budget bites - and
        # the message has to say the hat was not one of the four counted, or
        # the reader goes looking for a fault in the hat.
        e = self.house(hits=[4, 1, 2, 8, 4], rotate=[0, 12, 4, 0, 4])
        msgs = fails(e)
        self.assertTrue(any("attack together" in m for m in msgs), msgs)
        self.assertTrue(any("carpet" in m for m in msgs), msgs)

    def test_a_sparse_hat_is_not_a_carpet(self):
        # Six of sixteen is a groove, not a texture, and it counts.
        e = self.house(hits=[4, 1, 2, 6, 2])
        carpeted = [m for m in fails(e) if "carpet" in m]
        self.assertEqual(carpeted, [])


class TheBoardCase(unittest.TestCase):
    def test_a_flat_board_is_refused(self):
        # What all 71 shipped presets had: every fader at 0.19, inherited and
        # never touched.
        e = broken(mix=[0.19] * 8)
        self.assertTrue(any("flat board" in m for m in fails(e)), fails(e))

    def test_no_mix_at_all_is_refused(self):
        e = copy.deepcopy(CLEAN)
        del e["mix"]
        self.assertTrue(any("flat board" in m for m in fails(e)), fails(e))


class SomethingMustOutliveABarCase(unittest.TestCase):
    """THE drone fault. `note_duration` clamps a note to the loop point, so at
    1/16 the longest note the instrument can hold is half a bar - and all
    twenty shipped drone presets sat at gate 800 on a 1/16 grid."""

    def test_a_drone_entirely_at_one_sixteenth_is_refused(self):
        e = broken(div=["1/16"] * 8)
        self.assertTrue(any("outlives one bar" in m for m in fails(e)), fails(e))

    def test_the_rebuilt_template_passes(self):
        self.assertFalse(any("outlives one bar" in m for m in fails(CLEAN)))

    def test_a_techno_family_is_not_asked_to_sustain(self):
        # A one-bar loop at 1/16 is CORRECT for house; the check is only for
        # the two families whose whole proposition is sustain.
        e = broken(genre="house", div=["1/16"] * 8)
        self.assertFalse(any("outlives one bar" in m for m in fails(e)))


class TheShippedPacksAllPassCase(unittest.TestCase):
    """THE STANDING GUARD ON THE PACKS.

    This test asserted the OPPOSITE until 2026-09-04 and the inversion is the
    record of the rebuild: every one of the 71 shipped entries used to fail,
    because every one was a one-bar loop on a flat board with eight channels
    attacking the same step. They all pass now, and this is what says they
    still do - a preset that goes back to the old shape fails the build rather
    than shipping and being discovered by ear.

    It is a floor, not a verdict. Clean here means no collision, no mud and no
    silent refusal; whether a preset is any GOOD is the ear gate's question.
    """

    def packs(self):
        with open(os.path.join(ROOT, "tools", "drum-kit-notes.json")) as fh:
            kits = json.load(fh)["notes"]
        for path in sorted(glob.glob(os.path.join(ROOT, "snapshot",
                                                  "*-manifest.json"))):
            with open(path) as fh:
                doc = json.load(fh)
            if not isinstance(doc, list):
                continue                  # the factory manifest is one entry
            yield os.path.basename(path), doc, kits

    def test_there_are_packs_to_check(self):
        names = [n for n, _e, _k in self.packs()]
        self.assertEqual(sorted(names),
                         ["drone-ambient-manifest.json",
                          "genre-pack-manifest.json"])

    def test_the_packs_still_hold_seventy_one_entries(self):
        total = sum(len(entries) for _n, entries, _k in self.packs())
        self.assertEqual(total, 71)

    def test_every_shipped_entry_passes(self):
        broke = {}
        for name, entries, kits in self.packs():
            for entry in entries:
                msgs = [m for sev, m in vm.check(entry, kits) if sev == "FAIL"]
                if msgs:
                    broke[f"{name}:{entry['file']}"] = msgs
        self.assertEqual(broke, {})

    def test_no_shipped_entry_even_warns(self):
        # A warning is a dead knob or an unrecoverable value - fine in a
        # one-off, not in a pack somebody is meant to play through.
        warned = {}
        for name, entries, kits in self.packs():
            for entry in entries:
                msgs = [m for sev, m in vm.check(entry, kits) if sev == "WARN"]
                if msgs:
                    warned[f"{name}:{entry['file']}"] = msgs
        self.assertEqual(warned, {})

    def test_every_entry_has_a_distinct_file_and_title(self):
        files, titles = [], []
        for _n, entries, _k in self.packs():
            for entry in entries:
                files.append(entry["file"])
                titles.append(entry["title"])
        self.assertEqual(len(files), len(set(files)))
        self.assertEqual(len(titles), len(set(titles)))

    def test_no_two_entries_are_the_same_music(self):
        # ELEVEN OF THE OLD FIFTY-ONE WERE BIT-IDENTICAL to another entry -
        # the whole fx-* series was a copy of an 031-060 entry with a
        # different insert pair. Padding, and it is what the SPACE re-scope
        # replaced.
        seen = {}
        for _n, entries, _k in self.packs():
            for entry in entries:
                key = json.dumps({k: entry.get(k) for k in
                                  ("tempo", "root", "scale", "div", "drums",
                                   "voices", "overrides", "groove")},
                                 sort_keys=True)
                self.assertNotIn(key, seen,
                                 f"{entry['file']} is the same music as "
                                 f"{seen.get(key)}")
                seen[key] = entry["file"]


class ANoteIsAClaimCase(unittest.TestCase):
    """EVERY FALSIFIABLE SENTENCE IN A `notes` STRING IS CHECKED AGAINST THE
    DATA.

    The old pack's `049-dub-chord` was named "the offbeat chord stab" and was a
    single note on step 0 with chords switched off. That is not a cosmetic
    fault: it teaches the player the instrument cannot do the thing. **And the
    rebuild committed three of its own** - a promised sample-and-hold that did
    not exist, a "delay-led" preset on the default feedback, and a "walking
    bass" whose wording read as a claim about the key walker. This test is what
    caught them, so it stays.

    Only sentences that can be checked are checked. "Brooding" is not testable
    and is nobody's business."""

    def entries(self):
        with open(os.path.join(ROOT, "tools", "drum-kit-notes.json")) as fh:
            json.load(fh)
        for path in sorted(glob.glob(os.path.join(ROOT, "snapshot",
                                                  "*-manifest.json"))):
            with open(path) as fh:
                doc = json.load(fh)
            if isinstance(doc, list):
                for e in doc:
                    yield e

    def claims(self, entry):
        """[(claim, holds)] for every checkable sentence in `notes`."""
        note = (entry.get("notes") or "").lower()
        mods = entry.get("mods") or []
        shapes = {m["shape"] for m in mods}
        g = entry.get("globals") or {}
        v = entry["voices"]
        chords = set(v.get("chord") or [])
        for o in (entry.get("overrides") or {}).values():
            chords.add(o.get("chord", 0))
        swing = max((entry.get("groove") or {}).get("swing") or [0])
        stab = [s for s in range(16) if v["rhythm_reg"][1] >> s & 1]
        scale = tlib.SCALES[entry["scale"]][0]
        out = []

        def claim(trigger, name, holds):
            if trigger in note:
                out.append((name, holds))

        claim("sample-and-hold", "an s&h modulator exists", "s&h" in shapes)
        claim("chord", "some chord shape is on", bool(chords - {0}))
        claim("offbeat", "the stab avoids the beat positions",
              all(s % 4 for s in stab))
        claim("riser", "a ramp modulator exists", "ramp" in shapes)
        claim("shuffle", "swingAmount is nonzero", swing > 0)
        claim("swing", "swingAmount is nonzero", swing > 0)
        claim("no reverb", "the room is short", g.get("revsize", 0) <= 30)
        claim("delay-led", "the feedback is high", g.get("dlyfbk", 0) >= 50)
        claim("delay is the instrument", "the feedback is high",
              g.get("dlyfbk", 0) >= 50)
        claim("nothing else moves", "at most three modulators", len(mods) <= 3)
        for word, code in (("pentatonic", "PENT"), ("phrygian", "PHR"),
                           ("harmonic minor", "HMIN"), ("dorian", "DOR"),
                           ("major", "MAJ")):
            claim(word, f"the scale is {code}", scale == code)
        if "every voice" in note and "mutated" in note:
            out.append(("every voice is a Mutated Instrument",
                        set(v["engines"]) == {"JV/Mutated Instruments"}))
        return out

    def test_there_are_notes_to_check(self):
        checked = sum(len(self.claims(e)) for e in self.entries())
        # If this drops to nothing, the notes strings have been rewritten into
        # prose that says nothing checkable - which is its own kind of lie.
        self.assertGreater(checked, 20)

    def test_every_checkable_claim_holds(self):
        broken = []
        for e in self.entries():
            for name, holds in self.claims(e):
                if not holds:
                    broken.append(f"{e['file']}: {name}")
        self.assertEqual(broken, [])


if __name__ == "__main__":
    unittest.main()
