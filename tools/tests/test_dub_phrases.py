"""Five dub pieces built on phrases and fills - `snapshot/dub-phrases-manifest.json`.

Round two's rules apply unchanged and are INHERITED, not copied: every piece is
its own piece, every take is in its key, every chord sits on a read polyphonic
patch, no generator moves by itself, the insert pair is never swapped.

What this file adds is the thing these five are FOR. Every earlier dub piece is
one bar looping; here the drums run a 2-, 3- or 4-bar PHRASE with a FILL on its
last bar, and the pitched takes run across 2 or 4 bars at 1/8 or 1/4, so the
two kinds of part repeat at different lengths.

The main fader is PROVISIONAL until the rig measures it, exactly as in round
three, and `test_a_provisional_trim_says_so` keeps a copied number from passing
for a measured one.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_dub_round as r2                                      # noqa: E402
from test_dub_round import ROOT, tlib, lib                       # noqa: E402

MANIFEST = os.path.join(ROOT, "snapshot", "dub-phrases-manifest.json")
EARLIER = (r2.MANIFEST,
           os.path.join(ROOT, "snapshot", "dub-round-3-manifest.json"))
DRUM_CHANNELS = ("0", "1", "2", "3")
BARS = {"1/16": 1, "1/8": 2, "1/4": 4}


def take_bars(entry):
    """How many bars the longest pitched take of this entry loops over."""
    div = entry.get("div") or [None] * 8
    return max((BARS.get(div[int(ch)] or "1/16", 1) for ch in entry["chords"]),
               default=1)


class ThePhraseCase(r2.TheRoundCase):
    """Round two's whole case, pointed at the five phrase pieces."""

    @classmethod
    def setUpClass(cls):
        with open(MANIFEST, encoding="utf-8") as fh:
            cls.round = json.load(fh)
        cls.earlier = []
        for path in EARLIER:
            with open(path, encoding="utf-8") as fh:
                cls.earlier += json.load(fh)

    # -- the inherited tests whose NUMBERS are round two's, restated ---------

    def test_there_are_twenty_and_they_are_distinct(self):
        self.assertEqual(len(self.round), 5)
        for key in ("file", "title"):
            vals = [e[key] for e in self.round]
            self.assertEqual(len(set(vals)), 5, vals)
        earlier = {e["file"] for e in self.earlier}
        self.assertFalse(earlier & {e["file"] for e in self.round})

    def test_the_round_spreads_across_the_genre(self):
        keys = {(e["globals"]["root"], e["globals"]["scale"])
                for e in self.round}
        self.assertEqual(len(keys), 5, "two pieces share a key and mode")
        self.assertGreaterEqual(
            len({e["globals"]["scale"] for e in self.round}), 2)
        self.assertEqual({e["tempo"] for e in self.round}, {120, 125})

    def test_the_main_fader_is_a_measured_trim(self):
        for e in self.round:
            main = float(e["levels"]["16"])
            self.assertEqual(e["globals"]["master"], round(main * 100),
                             f"{e['file']}: master and main fader disagree")

    def test_a_provisional_trim_says_so(self):
        for e in self.round:
            why = e["levels_why"]
            measured = "MEASURED" in why and "PROVISIONAL" not in why
            provisional = why.startswith("PROVISIONAL")
            self.assertTrue(measured or provisional, e["file"])

    # -- what only these five have to answer ---------------------------------

    def test_no_piece_is_an_earlier_one(self):
        seen = {json.dumps(self._piece(e), sort_keys=True): e["file"]
                for e in self.earlier}
        for e in self.round:
            key = json.dumps(self._piece(e), sort_keys=True)
            self.assertNotIn(key, seen,
                             f"{e['file']} is the same piece as "
                             f"{seen.get(key)}")

    def test_every_piece_phrases_its_drums_and_fills_the_last_bar(self):
        for e in self.round:
            phrased = [k for k, v in e["drums"].items()
                       if v.get("phrase", 1) > 1 and v.get("fill", 0) > 0]
            self.assertGreaterEqual(
                len(phrased), 2,
                f"{e['file']} phrases fewer than two drum channels")

    def test_phrase_and_fill_are_legal_and_never_dead(self):
        """A fill with no phrase never fires (is_fill_bar is False for 1), and
        a fill on a player-owned channel is written over nothing, so both are
        dead data that looks like a setting."""
        for e in self.round:
            for ch, spec in list(e["drums"].items()) + [
                    (k, v) for k, v in e["voices"].items()]:
                phrase, fill = spec.get("phrase", 1), spec.get("fill", 0)
                self.assertIn(phrase, (1, 2, 3, 4), f"{e['file']} ch{ch}")
                self.assertTrue(0 <= fill <= 100, f"{e['file']} ch{ch}")
                if fill:
                    self.assertGreater(phrase, 1,
                                       f"{e['file']} ch{ch}: fill with no "
                                       f"phrase never sounds")
                    self.assertIn(ch, DRUM_CHANNELS,
                                  f"{e['file']} ch{ch}: a take is never "
                                  f"rewritten, so its fill draws dead")

    def test_a_fill_never_reaches_a_beat(self):
        """MEASURED ON THE RIG 2026-10-09, not derived. The fill is written on
        the poll thread a few tens of milliseconds after the bar line, so a
        fill hit on STEP 0 is missed in the fill bar and sounds at the start of
        the NEXT bar: a clap with fill 100 played 15 hits in its fill bar and 1
        in the plain bar after it, where the manifest says that channel is
        silent. The fill reaches the beat only at high amounts (it adds furthest
        from the beat first), so the amount is capped by this test."""
        for e in self.round:
            for ch, spec in e["drums"].items():
                if spec.get("phrase", 1) < 2 or not spec.get("fill"):
                    continue
                base = tlib.drum_steps(
                    lib.build_pattern_steps(16, spec["hits"],
                                            spec.get("rotate", 0)),
                    spec.get("rhythm_reg", 0xFFFF), spec.get("hand_reg", 0))
                fill = tlib.fill_line(tuple(bool(x) for x in base),
                                      spec["fill"])
                grid = tlib.beat_grid(16)
                added = [i for i, (b, f) in enumerate(zip(base, fill))
                         if f and not b]
                self.assertEqual(
                    [i for i in added if i in grid], [],
                    f"{e['file']} ch{ch}: fill {spec['fill']} adds a hit on "
                    f"a beat")

    def test_the_round_reaches_two_three_and_four_bar_phrases(self):
        lengths = {v["phrase"] for e in self.round for v in e["drums"].values()
                   if v.get("phrase", 1) > 1}
        self.assertEqual(lengths, {2, 3, 4})

    def test_the_takes_run_longer_than_a_bar(self):
        """Mixed lengths is the point: the pitched parts must not repeat at the
        drums' length, or the two are one loop twice."""
        for e in self.round:
            self.assertGreater(take_bars(e), 1,
                               f"{e['file']} has no take over more than a bar")
        mixed = [e["file"] for e in self.round
                 if any(v.get("phrase", 1) not in (1, take_bars(e))
                        for v in e["drums"].values())]
        self.assertGreaterEqual(len(mixed), 3, mixed)

    def test_a_take_stays_inside_its_loop(self):
        for e in self.round:
            for ch, events in e["chords"].items():
                for stab in events:
                    self.assertTrue(0 <= stab["step"] < 16,
                                    f"{e['file']} ch{ch} step {stab['step']}")
                    self.assertLessEqual(
                        stab["step"] + stab["duration"], 16 + 1e-9,
                        f"{e['file']} ch{ch}: a note outlives the loop")

    def test_every_piece_says_how_to_start_it(self):
        for e in self.round:
            self.assertIn("PLAY button", e["notes"], e["file"])


class ThePhraseBuildsCase(unittest.TestCase):
    """All five build through the shipped builder, with phrase and fill saved."""

    def test_all_five_build_and_carry_phrase_and_fill(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "build_factory_snapshot",
            os.path.join(ROOT, "tools", "build-factory-snapshot.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with open(os.path.join(ROOT, "tools", "drum-kit-notes.json")) as fh:
            kits = json.load(fh)["notes"]
        with open(MANIFEST, encoding="utf-8") as fh:
            entries = json.load(fh)
        port = "virtual:maschine.rs/Maschine MK2 Pads"
        for entry in entries:
            with open(os.path.join(ROOT, entry["base"]), encoding="utf-8") as fh:
                base = json.load(fh)
            built, report = mod.build(base, entry, kits)
            self.assertTrue(
                built["last_snapshot_fpath"].endswith(entry["file"] + ".zss"),
                f"{entry['file']} does not name itself")
            self.assertEqual(
                [line for line in report if "outside the pad notes" in line],
                [], f"{entry['file']} authors a note the pads cannot show")
            state = built["zs3"]["zs3-0"]["midi_capture"][port]["ctrldev_state"]
            for ch, spec in entry["drums"].items():
                saved = state["drums"][ch]
                self.assertEqual(saved["phrase"], spec.get("phrase", 1),
                                 f"{entry['file']} ch{ch} phrase not saved")
                self.assertEqual(saved["fill"], spec.get("fill", 0),
                                 f"{entry['file']} ch{ch} fill not saved")
            for ch in entry["chords"]:
                self.assertEqual(state["owners"][ch], "player", entry["file"])


class TheFillLandsOnTheLastBarCase(unittest.TestCase):
    def test_the_fill_bar_of_each_phrase_length(self):
        for phrase in (2, 3, 4):
            bars = [b for b in range(24) if tlib.is_fill_bar(b, phrase)]
            self.assertEqual(bars, list(range(phrase - 1, 24, phrase)),
                             f"phrase {phrase}")
        self.assertFalse(any(tlib.is_fill_bar(b, 1) for b in range(24)))

    def test_a_fill_only_adds(self):
        line = tuple(i % 4 == 0 for i in range(16))
        filled = tlib.fill_line(line, 60)
        self.assertTrue(all(f or not o for o, f in zip(line, filled)))
        self.assertGreater(sum(filled), sum(line))


if __name__ == "__main__":
    unittest.main()
