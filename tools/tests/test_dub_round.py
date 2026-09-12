"""The twenty of item 41 - `snapshot/dub-round-manifest.json`.

ROUND TWO, and this file was inverted to build it. Round one held the music
identical in all twenty so the vote would isolate instrumentation and effects,
and a test here enforced that. The owner heard it and said they "all sound the
same" - the ask was *variations inside the genre per snapshot*, not a vote on
the best-sounding preset. So the strongest test in this file now asserts the
OPPOSITE of what it used to: no two of the twenty may be the same piece.

What did NOT flip, because it was never what "the same" meant: every generator
is still fixed. `random` and `rhythm` are 0 on every voice, and
`_rewrite_voice` returns early when both are 0, so each piece plays its own
line bit-identically bar after bar. Twenty different fixed melodies.

Three tests exist because of a law this project has already paid for:

* CHECK THE VOICE COUNT AND THE MONO FLAG BEFORE ASKING A PATCH FOR A CHORD.
  Every Obxd patch in the shipped preset packs ships `voicecount` 0.25, which
  sits between the scale points for two and three voices, so a three-note
  chord silently loses a note.
* A MODULATOR POINTED AT A GUI-HOSTED PLUGIN COSTS 70 % OF A CORE. The round
  never swaps the insert pair, so every modulator lands on a mixer fader or a
  TAP insert, neither of which has an LV2 UI.
* A NOTE THAT LEAVES THE KEY IS A CLAIM NOBODY CHECKED. Every take here is
  authored from SCALE DEGREES through the instrument's own keyboard mapping,
  and `test_no_authored_note_leaves_the_key` is what says it stayed there.
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "ctrldev"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from techno_lib import techno_lib as tlib                       # noqa: E402
from maschine_mk2_lib import maschine_mk2_lib as lib            # noqa: E402

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


def base_engines():
    with open(os.path.join(ROOT, "snapshot",
                           "018-generative-techno-main-insert.zss"),
              encoding="utf-8") as fh:
        base = json.load(fh)
    return {cid: list(chain["slots"][0].values())[0]
            for cid, chain in base["chains"].items()}


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
        for e in self.round:
            self.assertGreater(len(e.get("notes") or ""), 150,
                               f"{e['file']} has no usable note")

    # ------------------------------------------------- twenty PIECES, not one

    def _piece(self, e):
        """Everything that makes this entry a different piece of music.

        Deliberately NOT the instrumentation: two entries could legitimately
        share a kit or a patch. What may not repeat is the MUSIC - the tempo,
        the key, the groove, the phrase lengths, the drum placement and every
        authored note."""
        return {
            "tempo": e["tempo"],
            "key": (e["globals"]["root"], e["globals"]["scale"]),
            "div": tuple(e.get("div") or [None] * 8),
            "swing": tuple((e.get("groove") or {}).get("swing") or [0] * 8),
            "drums": tuple(sorted(
                (k, v["hits"], v.get("rotate", 0), v["velo"],
                 v.get("rhythm_reg"), v.get("hand_reg"))
                for k, v in e["drums"].items())),
            "voices": tuple(sorted(
                (k, v.get("rhythm_reg"), v.get("gate"), v.get("octave"),
                 v.get("register"), v.get("length"))
                for k, v in e["voices"].items() if not v.get("empty"))),
            "takes": tuple(sorted(
                (k, tuple((s["step"], tuple(s["notes"])) for s in stabs))
                for k, stabs in e["chords"].items())),
        }

    def test_no_two_entries_are_the_same_piece(self):
        """THE TEST THIS ROUND EXISTS FOR.

        Round one failed this in spirit and passed in letter: every entry was
        the same bar under a different mix, and the owner heard exactly that.
        A round whose pieces repeat teaches nothing, so it fails the build."""
        seen = {}
        for e in self.round:
            key = json.dumps(self._piece(e), sort_keys=True)
            self.assertNotIn(key, seen,
                             f"{e['file']} is the same PIECE as "
                             f"{seen.get(key)}")
            seen[key] = e["file"]

    def test_the_round_spreads_across_the_genre(self):
        """And not merely 'not identical'. Twenty near-neighbours would pass
        the test above and still be one piece with twenty spellings, so the
        axes themselves are counted."""
        keys = {(e["globals"]["root"], e["globals"]["scale"]) for e in self.round}
        self.assertGreaterEqual(len(keys), 6, f"only {len(keys)} keys")
        scales = {e["globals"]["scale"] for e in self.round}
        self.assertGreaterEqual(len(scales), 4, f"only {len(scales)} modes")
        self.assertEqual({e["tempo"] for e in self.round}, {120, 125})
        kicks = {e["drums"]["0"]["hits"] for e in self.round}
        self.assertGreaterEqual(len(kicks), 3,
                                "every piece has the same kick placement")
        # At least a quarter of the round must run a phrase longer than one
        # bar, or `div` is a feature nothing uses.
        longer = [e["file"] for e in self.round
                  if any(d not in (None, "1/16") for d in (e.get("div") or []))]
        self.assertGreaterEqual(len(longer), 5, longer)
        self.assertTrue(any(e.get("groove") for e in self.round),
                        "nothing in the round swings")

    # ------------------------------------------------------------- polyphony

    def _chord_channels(self, entry):
        """The chains carrying an authored CHORD - more than one note on a
        step. A single-note bass take needs no polyphony."""
        return {str(int(ch) + 1) for ch, stabs in entry["chords"].items()
                if any(len(s["notes"]) > 1 for s in stabs)}

    def test_a_chord_is_only_ever_authored_on_a_polyphonic_engine(self):
        base = base_engines()
        for e in self.round:
            engines = dict(base)
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

    # -------------------------------------------------------------- the keys

    def test_no_authored_note_leaves_the_key(self):
        """Every take is written from scale degrees, so every note must come
        back as one. A chord tone outside the scale is the one mistake a
        listening round cannot survive - it does not read as a variation, it
        reads as broken."""
        for e in self.round:
            root, scale = e["globals"]["root"], e["globals"]["scale"]
            degrees = set(tlib.SCALES[scale][1])
            for ch, stabs in e["chords"].items():
                for stab in stabs:
                    for note in stab["notes"]:
                        self.assertIn(
                            (note - root) % 12, degrees,
                            f"{e['file']} channel {ch} step {stab['step']}: "
                            f"note {note} is not in "
                            f"{tlib.SCALES[scale][0]} on root {root}")

    def test_every_authored_note_reads_as_a_take_on_the_pads(self):
        """`_rebuild_notes` probes only the keyboard notes at the channel's
        octave plus the generated line, so a tone in neither cannot be found
        and its step draws in the GROUP colour instead of the player amber.
        The builder warns; here it is a rule."""
        for e in self.round:
            root, scale = e["globals"]["root"], e["globals"]["scale"]
            for ch, stabs in e["chords"].items():
                octave = e["voices"][ch]["octave"]
                pads = set(tlib.pad_notes(root, scale, octave))
                for stab in stabs:
                    outside = [n for n in stab["notes"] if n not in pads]
                    self.assertEqual(
                        outside, [],
                        f"{e['file']} channel {ch} step {stab['step']}: "
                        f"{outside} is outside the pad notes at octave "
                        f"{octave} - it will sound, and the pad will not read "
                        f"as a take")

    # ------------------------------------------- fixed generators, free FX

    def test_no_generator_moves_by_itself(self):
        for e in self.round:
            for ch, v in e["voices"].items():
                if v.get("empty"):
                    continue
                self.assertEqual(v.get("random", 0), 0,
                                 f"{e['file']} voice {ch} has RANDOM on")
                self.assertEqual(v.get("rhythm", 0), 0,
                                 f"{e['file']} voice {ch} has RHYTHM on")

    def test_nothing_is_humanised(self):
        """HUMAN and HUMNV are per-EVENT randomisation: they change what is
        heard between one repeat and the next, which is the thing the owner
        asked to be held still. SWING does not - it is a fixed offset on the
        same steps every bar - so the round swings and does not humanise."""
        for e in self.round:
            g = e.get("groove") or {}
            self.assertEqual(sum(g.get("human_time") or [0]), 0, e["file"])
            self.assertEqual(sum(g.get("human_velo") or [0]), 0, e["file"])

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
        for e in self.round:
            self.assertNotIn("fx", e, f"{e['file']} swaps the insert pair")
            for cid in (e.get("engines") or {}):
                self.assertIn(cid, ("5", "6", "7", "8"),
                              f"{e['file']} swaps an engine on chain {cid}, "
                              f"which is not a voice chain")

    # -------------------------------------------------- kinds, E, and the div

    def test_a_channel_overridden_to_a_voice_has_voice_parameters(self):
        for e in self.round:
            for ch, kind in (e.get("kinds") or {}).items():
                self.assertIn(kind, tlib.KINDS)
                if kind == "voice":
                    self.assertIn(ch, e["voices"],
                                  f"{e['file']} makes channel {ch} a voice "
                                  f"with no voice block")

    def test_every_entry_settles_channel_e_one_way_or_the_other(self):
        for e in self.round:
            named = ("4" in e["drums"]) or ("4" in e["voices"])
            self.assertTrue(named, f"{e['file']} says nothing about channel E")
            self.assertIn("kinds", e, f"{e['file']} inherits 018's kind for E")

    def test_a_long_division_only_lands_where_it_survives(self):
        """`_derive_params` reads stepsPerBeat back only for F, G and H, so a
        drum-table channel at any other division would play one bar length
        under a panel reading another. The exception is a PLAYER-OWNED
        channel, whose pattern nothing rewrites."""
        for e in self.round:
            for channel, d in enumerate(e.get("div") or []):
                if d in (None, "1/16"):
                    continue
                self.assertIn(d, [lab for lab, _s, _b in lib.DIVISIONS],
                              f"{e['file']}: {d!r} is not a division")
                if tlib.CHANNELS[channel][2] != "voice":
                    self.assertIn(
                        str(channel), e["chords"],
                        f"{e['file']} puts channel {channel} at {d} and does "
                        f"not author a take on it")

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

    def test_the_main_fader_is_a_measured_trim(self):
        """It is the only number in the mix that is not a musical choice, so
        it has to say why. A fader identical in all twenty means the trim
        never ran and the round is partly a loudness vote."""
        mains = []
        for e in self.round:
            main = float(e["levels"]["16"])
            self.assertTrue(0.0 < main <= 1.0, f"{e['file']} main {main}")
            self.assertEqual(e["globals"]["master"], round(main * 100),
                             f"{e['file']}: the master global and the main "
                             f"fader disagree")
            mains.append(main)
        self.assertGreater(len(set(mains)), 1,
                           "every main fader is the same - the measured trim "
                           "never ran")


class TheRoundBuildsCase(unittest.TestCase):
    """Every one of the twenty builds, through the shipped builder."""

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
            for ch in entry["chords"]:
                self.assertEqual(state["owners"][ch], "player", entry["file"])
            for ch, who in state["owners"].items():
                if ch not in entry["chords"]:
                    self.assertEqual(who, "gen", f"{entry['file']} ch{ch}")


if __name__ == "__main__":
    unittest.main()
