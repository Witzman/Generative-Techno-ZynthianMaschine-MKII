"""Facts about the SHIPPED factory snapshot, as a file on disk.

Deliberately not in test_build_factory_snapshot.py: that file's header
promises "nothing here touches a rig, a shipped .zss or a sequencer", and it
is worth keeping. These tests do the opposite job - they read the bytes that
actually get installed on a fresh Pi.

WHY THIS EXISTS. `019-dub-factory` became the factory snapshot on 2026-09-06,
and the promotion moved exactly one audible number: the main fader, 1.0 ->
0.28. That number is the whole reason the promotion was safe, it lives in two
places that can drift apart (the .zss and the manifest that describes it), and
nothing anywhere would have said so. The arithmetic that chose it is written
into the test rather than into a comment, because a comment cannot fail a
build - which is the sentence this project has now earned four times.
"""

import json
import math
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SNAPDIR = os.path.join(ROOT, "snapshot")

FACTORY = "019-dub-factory.zss"
GENERIC = "018-generative-techno-main-insert.zss"
FALLBACK = "017-generative-techno.zss"

# The main mixer strip. zynmixer's last channel is the main bus, and its
# `level` is a straight linear multiplier on the samples - mixer.c:169-192,
# no curve, no taper - which is what makes the dB arithmetic below legal.
MAIN_STRIP = "chan_16"

# Measured on zynmixer:output_17a with nobody at the panel, main fader at 1.0.
# Both readings are of the SAME FILE; the 11 dB between them is the wet-law
# fix of 2026-09-04, which let 019's four modulated sends self-correct on load.
#
# CONFIRMED ON THE RIG 2026-09-06, and the confirmation is why this number is
# still +7.0 after a day of being argued with. 019 was loaded and playing and
# the bus was read over 96 s - FORTY-EIGHT BARS, the LCM of the six modulator
# periods (16, 8, 6, 8, 4 and 3 bars) - at a known fader of 0.45:
#
#     peak -0.39 dBFS, RMS -18.36, crest 18.0 dB, 0 of 9,216,000 clipped
#     per-bar peak over 48 bars: max -0.39, min -1.97, spread 1.59 dB
#
# Back-computed, that is a unity peak of +6.55 dBFS, which agrees with the gate's
# +7.0 within 0.45 dB. So +7.0 stands and is slightly conservative.
#
# A SHORTER WINDOW IS NOT A SMALLER VERSION OF THIS MEASUREMENT, IT IS A
# DIFFERENT ONE. Locking to a BAR is what the trap file says and it is not
# enough here: a 10-bar read of the same file at 0.28 returned -8.11 dBFS,
# 3.6 dB below what the 48-bar figure predicts, and that reading was used to
# "correct" this constant to +2.95 and the fader to 0.45 - which put the peak
# 0.4 dB from full scale. Both were reverted. LOCK THE WINDOW TO THE LONGEST
# THING THAT MOVES, not to the bar.
PEAK_AT_UNITY_DBFS = +7.0      # 2026-09-05; +6.55 measured 2026-09-06, agrees
OWNER_CEILING_DBFS = -3.99     # 2026-09-02, 40 s, zero samples near full scale


def _snapshot(name):
    with open(os.path.join(SNAPDIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def _zs3(doc):
    return doc["zs3"]["zs3-0"]


def _driver_globals(doc):
    """The driver's own saved block, wherever the MIDI capture put it."""
    for key, cap in _zs3(doc)["midi_capture"].items():
        state = cap.get("ctrldev_state")
        if state and "globals" in state:
            return state["globals"]
    raise AssertionError("no ctrldev_state/globals in the snapshot")


class TheFactorySnapshotIsOnDisk(unittest.TestCase):

    def test_all_three_placed_snapshots_exist(self):
        """bootstrap.sh installs three files. A missing one fails on a Pi
        nobody can rehearse on, which is the worst place to find out."""
        for name in (FACTORY, GENERIC, FALLBACK):
            self.assertTrue(os.path.isfile(os.path.join(SNAPDIR, name)),
                            f"snapshot/{name} is not in the repository")


class BootstrapNamesTheFactorySnapshot(unittest.TestCase):
    """The installer is the only thing that makes a file "the factory
    snapshot". A .zss nobody places is just a file in a directory."""

    def setUp(self):
        with open(os.path.join(ROOT, "bootstrap.sh"), encoding="utf-8") as fh:
            self.text = fh.read()

    def _assign(self, var):
        m = re.search(rf"^{var}=(\S+)$", self.text, re.M)
        self.assertIsNotNone(m, f"bootstrap.sh does not set {var}")
        return m.group(1)

    def test_snap_is_the_factory_snapshot(self):
        self.assertEqual(self._assign("SNAP"), FACTORY)

    def test_the_other_two_are_named_and_are_not_the_default(self):
        self.assertEqual(self._assign("SNAP_GENERIC"), GENERIC)
        self.assertEqual(self._assign("SNAP_FALLBACK"), FALLBACK)
        # Only $SNAP may ever be written over default.zss. Asserted here as
        # well as in test-dry-run.sh because the two answer different
        # questions: that one reads what a dry run PRINTS, this one reads
        # what the script SAYS.
        # Real install commands only. Matching the word "install" anywhere
        # catches the prose above it, which says "fresh-install".
        for line in self.text.splitlines():
            if "default.zss" not in line:
                continue
            if not re.search(r"install -m 0644 ", line):
                continue
            self.assertRegex(line, r"\$SNAP[ \"]",
                             f"something other than $SNAP reaches "
                             f"default.zss: {line.strip()}")


class TheMainFaderLeavesTheHeadroomItWasGiven(unittest.TestCase):
    """019 at unity clipped 1.21 % of its samples. The promotion's one audible
    change is this fader, and the number was DERIVED rather than picked: pull
    it far enough that the measured peak lands back on the ceiling the owner
    chose by ear on 2026-09-02, and no further, so the mix keeps its level."""

    def setUp(self):
        self.doc = _snapshot(FACTORY)
        self.level = _zs3(self.doc)["mixer"][MAIN_STRIP]["level"]

    def test_the_main_fader_is_not_at_unity(self):
        self.assertLess(self.level, 1.0,
                        "the main fader is back at unity - 019 clips 1.21 % "
                        "of its samples there")

    def test_the_predicted_peak_is_at_or_under_the_owners_ceiling(self):
        predicted = PEAK_AT_UNITY_DBFS + 20 * math.log10(self.level)
        self.assertLessEqual(
            round(predicted, 2), round(OWNER_CEILING_DBFS, 2) + 0.1,
            f"main at {self.level} puts the measured peak at "
            f"{predicted:+.2f} dBFS, above the {OWNER_CEILING_DBFS:+.2f} the "
            f"owner settled on. Raising this fader needs a fresh read of "
            f"zynmixer:output_17a, not arithmetic")

    def test_it_is_not_pulled_so_far_the_instrument_is_quiet(self):
        """The other half of the same judgement. A fader low enough to be
        safe against any input is also a factory default nobody can hear."""
        predicted = PEAK_AT_UNITY_DBFS + 20 * math.log10(self.level)
        self.assertGreater(predicted, OWNER_CEILING_DBFS - 6.0)


class TheFileAgreesWithItselfAboutTheMaster(unittest.TestCase):
    """`master` is DEAD DATA in the driver - globals_view() overrides it from
    the mixer on every draw, so nothing reads the saved copy. Dead data that
    disagrees is still how a reader gets misled, and this file is one people
    are now going to open."""

    def test_the_saved_master_matches_the_main_strip(self):
        doc = _snapshot(FACTORY)
        level = _zs3(doc)["mixer"][MAIN_STRIP]["level"]
        self.assertEqual(_driver_globals(doc)["master"],
                         int(round(level * 100)))


class TheManifestAndTheFileAgreeOnTheMix(unittest.TestCase):
    """The mix is the one part of the factory snapshot that lives in two
    files. It got its own manifest key on 2026-09-02 precisely because an
    ear-tuned mix that exists only in a .zss is reverted by the next build
    without saying so - so the two must not be allowed to drift back apart."""

    def setUp(self):
        with open(os.path.join(SNAPDIR, "factory-manifest.json"),
                  encoding="utf-8") as fh:
            self.manifest = json.load(fh)
        self.mixer = _zs3(_snapshot(FACTORY))["mixer"]

    def test_the_manifest_builds_the_file_it_names(self):
        self.assertEqual(self.manifest["file"], FACTORY[:-len(".zss")])

    def test_every_unmodulated_level_matches(self):
        # Channels 0 and 3 carry LEVEL modulators, and for those the manifest
        # holds the modulator's BASE while the .zss holds wherever the LFO
        # happened to be at save time. Comparing them is a category error -
        # levels_why says so in the manifest itself.
        modulated = {str(m["channel"]) for m in self.manifest.get("mods", [])
                     if m["verb"] == "level"}
        for channel, level in self.manifest["levels"].items():
            if channel in modulated:
                continue
            strip = f"chan_{int(channel):02d}"
            self.assertAlmostEqual(
                self.mixer[strip]["level"], float(level), places=6,
                msg=f"{strip}: manifest says {level}, the shipped file says "
                    f"{self.mixer[strip]['level']}")

    def test_the_gap_to_a_rebuild_is_declared(self):
        """A rebuild does NOT reproduce this file - nineteen FX wet ports come
        out 20-45 dB louder, because the .zss predates the wet-law fix. That
        is deliberate and it is item 49/50's work to close. An undeclared gap
        of that size is indistinguishable from rot, so the manifest has to say
        it out loud."""
        note = self.manifest.get("reproduces_shipped_file", "")
        self.assertTrue(note, "the manifest no longer reproduces the shipped "
                              ".zss and does not say so")
        self.assertIn("wet law", note.lower())


if __name__ == "__main__":
    unittest.main()
