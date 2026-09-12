"""The twenty of item 41 - `snapshot/dub-round-manifest.json`.

A listening round is worth exactly what its CONTROLS are worth. The owner
hears twenty files and replies with one number, so anything that is not a
deliberate variable has to be provably the same in all twenty, and anything
that IS a variable has to be provably different. Neither is visible by
reading a 2,000-line manifest, which is what this file is for.

Three of these tests exist because of a law this project has already paid for:

* CHECK THE VOICE COUNT AND THE MONO FLAG BEFORE ASKING A PATCH FOR A CHORD.
  Every Obxd patch in the shipped preset packs ships `voicecount` 0.25, which
  sits between the scale points for two and three voices - so a three-note
  chord silently loses a note. The round forces 1.0, and
  `test_every_chord_channel_is_polyphonic` is what says it still does.
* A MODULATOR POINTED AT A GUI-HOSTED PLUGIN COSTS 70 % OF A CORE. The round
  never swaps the insert pair, so every modulator lands on a mixer fader or a
  TAP insert, neither of which has an LV2 UI.
* MELODIES ARE FIXED - owner's instruction, 2026-09-12, "modulation is
  allowed, but keep melodys fixed in the first place". `random` and `rhythm`
  are 0 everywhere and no modulator drives a DRIFT verb.
"""

import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys
sys.path.insert(0, os.path.join(ROOT, "ctrldev"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from techno_lib import techno_lib as tlib                       # noqa: E402

MANIFEST = os.path.join(ROOT, "snapshot", "dub-round-manifest.json")
OBXD = "JV/Obxd"
PADTHV1 = "JV/padthv1"
# The padthv1 patches this round uses, each read off its own .ttl on the rig
# on 2026-09-12 and each DEF1_MONO 0. Pinned by name because the .ttl is on
# the Pi and this test runs on WSL: a patch added here without being read is
# the "choose a patch by its name" mistake for the fourth time.
PADTHV1_POLY = {
    "67Padthv1Patches_TapeStrings.ttl",
    "67Padthv1Patches_TapeStrings2.ttl",
    "67Padthv1Patches_Choir1.ttl",
    "67Padthv1Patches_Dusk5.ttl",
    "67Padthv1Patches_Randomize01.ttl",
}


class TheRoundCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(MANIFEST, encoding="utf-8") as fh:
            cls.round = json.load(fh)

    def test_there_are_twenty_and_they_are_distinct(self):
        self.assertEqual(len(self.round), 20)
        files = [e["file"] for e in self.round]
        titles = [e["title"] for e in self.round]
        self.assertEqual(len(set(files)), 20, files)
        self.assertEqual(len(set(titles)), 20, titles)

    def test_every_entry_says_what_it_varies(self):
        """A variant with no sentence is a variant the vote cannot use."""
        for e in self.round:
            self.assertGreater(len(e.get("notes") or ""), 120,
                               f"{e['file']} has no usable note")

    # ---------------------------------------------------------------- controls

    def test_the_music_is_the_same_in_all_twenty(self):
        """Everything the round is NOT about is identical.

        The drum PATTERN (not the kit), the bass figure, the two stab chords
        and the pad chord, the tempo, the key and the mix. If one of these
        moves, the owner is voting on two things at once and the round teaches
        nothing."""
        def music(e):
            return {
                "tempo": e["tempo"],
                "root": e["globals"]["root"],
                "scale": e["globals"]["scale"],
                "drums": {k: {n: v[n] for n in ("hits", "rotate", "velo")}
                          for k, v in e["drums"].items() if k != "4"},
                "bass": {n: e["voices"]["5"][n] for n in
                         ("register", "length", "rhythm_reg", "gate",
                          "octave", "range", "velo", "chord")},
                "chords6": [(s["step"], tuple(s["notes"]), s["velo"])
                            for s in e["chords"]["6"]],
                "chords7": [(s["step"], tuple(s["notes"]), s["velo"])
                            for s in e["chords"]["7"]],
                "levels": {k: v for k, v in e["levels"].items()
                           if k not in ("4",)},
                "mods": [{n: m[n] for n in ("channel", "verb", "depth",
                                            "rate", "shape", "phase0")}
                         for m in e["mods"]],
            }
        first = music(self.round[0])
        for e in self.round[1:]:
            self.assertEqual(music(e), first,
                             f"{e['file']} moves something the round holds still")

    def test_every_variant_differs_from_every_other(self):
        """And the other half: no two of the twenty are the same file."""
        def sound(e):
            return json.dumps({
                "globals": e["globals"],
                "kits": {k: v["kit"] for k, v in e["drums"].items()},
                "presets": {k: v["file"] for k, v in e["presets"].items()},
                "engines": {k: v["engine"] for k, v in (e.get("engines") or {}).items()},
                "wets": e["wets"],
                "kinds": e.get("kinds"),
                "e_level": e["levels"].get("4"),
            }, sort_keys=True)
        seen = {}
        for e in self.round:
            key = sound(e)
            self.assertNotIn(key, seen,
                             f"{e['file']} is the same sound as {seen.get(key)}")
            seen[key] = e["file"]

    # ------------------------------------------------------------- polyphony

    def _chord_channels(self, entry):
        """The chains carrying an authored chord, as chain ids."""
        return {str(int(ch) + 1) for ch, stabs in entry["chords"].items()
                if any(len(s["notes"]) > 1 for s in stabs)}

    def test_a_chord_is_only_ever_authored_on_a_polyphonic_engine(self):
        for e in self.round:
            engines = dict(base_engines())
            for cid, spec in (e.get("engines") or {}).items():
                engines[cid] = spec["engine"]
            for cid in self._chord_channels(e):
                engine = engines[cid]
                self.assertIn(engine, (OBXD, PADTHV1),
                              f"{e['file']} chain {cid} holds a chord on "
                              f"{engine}, whose polyphony is unread")
                spec = e["presets"].get(cid)
                self.assertIsNotNone(
                    spec, f"{e['file']} chain {cid} holds a chord on a patch "
                          f"nobody chose - a plugin default may be mono")
                if engine == OBXD:
                    self.assertEqual(
                        spec["controllers"].get("voicecount"), 1.0,
                        f"{e['file']} chain {cid}: Obxd ships this patch at "
                        f"voicecount 0.25, which is two voices - a triad "
                        f"would lose a note in silence")
                    self.assertEqual(spec["controllers"].get("unison"), 0.0)
                else:
                    self.assertIn(
                        spec["file"], PADTHV1_POLY,
                        f"{e['file']} chain {cid}: this padthv1 patch's "
                        f"DEF1_MONO has not been read")

    def test_every_padthv1_patch_used_anywhere_is_a_read_one(self):
        for e in self.round:
            for cid, spec in e["presets"].items():
                if spec["engine"] == PADTHV1:
                    self.assertIn(spec["file"], PADTHV1_POLY, e["file"])

    # ------------------------------------------------- fixed melody, free FX

    def test_no_generator_moves_by_itself(self):
        for e in self.round:
            for ch, v in e["voices"].items():
                if v.get("empty"):
                    continue
                self.assertEqual(v.get("random", 0), 0,
                                 f"{e['file']} voice {ch} has RANDOM on")
                self.assertEqual(v.get("rhythm", 0), 0,
                                 f"{e['file']} voice {ch} has RHYTHM on")

    def test_every_modulator_is_free_and_none_of_them_drifts(self):
        for e in self.round:
            for m in e["mods"]:
                self.assertIn(m["verb"], ("level", "reverb", "delay"),
                              f"{e['file']} modulates {m['verb']!r}: only the "
                              f"mixer fader and the two TAP inserts are free "
                              f"of the 70 %-of-a-core GUI cost")
                self.assertFalse(tlib.is_drift(m["verb"]))
                self.assertLessEqual(abs(m["depth"]), tlib.MOD_DEPTH_MAX)
                self.assertLess(m["rate"], len(tlib.MOD_RATES))
                self.assertIn(m["shape"], tlib.MOD_SHAPES)

    def test_the_insert_pair_is_never_swapped(self):
        """Which is what keeps the modulators free AND the levels comparable.

        A swap calls clear_processor, and TAP Reverberator's `drylevel`
        defaults to -4 dB - so swapping the reverb on some variants and not
        others would put a 4 dB step between them that nobody chose."""
        for e in self.round:
            self.assertNotIn("fx", e, f"{e['file']} swaps the insert pair")
            for cid in (e.get("engines") or {}):
                self.assertIn(cid, ("5", "6", "7", "8"),
                              f"{e['file']} swaps an engine on chain {cid}, "
                              f"which is not a voice chain")

    # ------------------------------------------------------------ the kinds

    def test_a_channel_overridden_to_a_voice_has_voice_parameters(self):
        for e in self.round:
            for ch, kind in (e.get("kinds") or {}).items():
                self.assertIn(kind, tlib.KINDS)
                if kind == "voice":
                    self.assertIn(ch, e["voices"],
                                  f"{e['file']} makes channel {ch} a voice "
                                  f"with no voice block")

    def test_every_entry_settles_channel_e_one_way_or_the_other(self):
        """E is the one channel whose ROLE varies, so no entry may leave it
        to the base. A drum pattern is not rewritten on load, so an entry
        that names E in neither block ships 018's leftover line."""
        for e in self.round:
            named = ("4" in e["drums"]) or ("4" in e["voices"])
            self.assertTrue(named, f"{e['file']} says nothing about channel E")
            self.assertIn("kinds", e, f"{e['file']} inherits 018's kind for E")

    def test_the_globals_name_a_room_and_a_division_everywhere(self):
        for e in self.round:
            g = e["globals"]
            for key in ("revsize", "revtype", "dlytime", "dlyfbk"):
                self.assertIn(key, g, f"{e['file']} leaves {key} to the base")
            self.assertLessEqual(g["revtype"], 42)
            self.assertLess(g["dlytime"], len(tlib.DELAY_DIVISIONS))
            self.assertLessEqual(g["dlyfbk"], 75,
                                 f"{e['file']}: TAP's feedback runs away "
                                 f"near 100")

    def test_the_tempo_is_exact_at_48_khz(self):
        for e in self.round:
            self.assertEqual(30000 % e["tempo"], 0,
                             f"{e['file']} is at {e['tempo']} BPM, which "
                             f"zynseq cannot clock exactly")


def base_engines():
    """The base snapshot's engine per chain - what a variant inherits."""
    with open(os.path.join(ROOT, "snapshot",
                           "018-generative-techno-main-insert.zss"),
              encoding="utf-8") as fh:
        base = json.load(fh)
    return {cid: list(chain["slots"][0].values())[0]
            for cid, chain in base["chains"].items()}


class TheRoundBuildsCase(unittest.TestCase):
    """Every one of the twenty builds, and the builder is the shipped one."""

    def test_all_twenty_build_and_name_themselves(self):
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
        for entry in entries:
            with open(os.path.join(ROOT, entry["base"]), encoding="utf-8") as fh:
                base = json.load(fh)
            built, _report = mod.build(base, entry, kits)
            self.assertTrue(
                built["last_snapshot_fpath"].endswith(entry["file"] + ".zss"),
                f"{entry['file']} does not name itself")
            port = "virtual:maschine.rs/Maschine MK2 Pads"
            state = built["zs3"]["zs3-0"]["midi_capture"][port]["ctrldev_state"]
            # A chord only survives the load on a player-owned channel.
            for ch in entry["chords"]:
                self.assertEqual(state["owners"][ch], "player", entry["file"])
            # And nothing else may be owned, or its generator is refused.
            for ch, who in state["owners"].items():
                if ch not in entry["chords"]:
                    self.assertEqual(who, "gen", f"{entry['file']} ch{ch}")


if __name__ == "__main__":
    unittest.main()
