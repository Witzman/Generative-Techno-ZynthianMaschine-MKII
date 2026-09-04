import os
import random
import sys
import unittest
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from techno_lib import techno_lib as tl  # noqa: E402
import techno_lib as tl_mod  # noqa: E402  - for the module's own classes


class TestTuringRegister(unittest.TestCase):

    def test_zero_chance_is_the_identity(self):
        reg = 0b10110011
        self.assertEqual(tl.mutate(reg, 8, 0.0), reg)

    def test_zero_chance_is_the_identity_forever(self):
        reg = 0b1011001110100101
        for _ in range(500):
            reg = tl.mutate(reg, 16, 0.0)
        self.assertEqual(reg, 0b1011001110100101)

    def test_full_chance_inverts_every_bit(self):
        self.assertEqual(tl.mutate(0b1111, 4, 1.0), 0b0000)

    def test_register_stays_inside_its_length(self):
        reg = 0xFFFF
        for _ in range(50):
            reg = tl.mutate(reg, 5, 1.0)
            self.assertLess(reg, 1 << 5)

    def test_low_chance_drifts_a_little(self):
        rng = random.Random(7).random
        reg = 0b10110011
        changed = sum(1 for _ in range(20) if tl.mutate(reg, 8, 0.05, rng) != reg)
        self.assertGreater(changed, 0)
        self.assertLess(changed, 20)

    def test_rotations_does_not_advance_the_register(self):
        reg = 0b1010
        vals = tl.rotations(reg, 4, 6)
        self.assertEqual(len(vals), 6)
        self.assertEqual(vals[0], reg)
        self.assertEqual(vals[4], reg)  # wraps at length


class TestRegisterRing(unittest.TestCase):

    def test_ring_is_four_deep(self):
        ring = deque(maxlen=4)
        for r in (1, 2, 3, 4, 5):
            tl.ring_push(ring, r)
        self.assertEqual(list(ring), [2, 3, 4, 5])

    def test_pop_returns_most_recent_first(self):
        ring = deque(maxlen=4)
        for r in (10, 20, 30):
            tl.ring_push(ring, r)
        self.assertEqual(tl.ring_pop(ring), 30)
        self.assertEqual(tl.ring_pop(ring), 20)

    def test_pop_on_empty_ring_returns_none(self):
        self.assertIsNone(tl.ring_pop(deque(maxlen=4)))


class TestPitch(unittest.TestCase):

    def test_six_scales_in_the_ratified_order(self):
        self.assertEqual([s[0] for s in tl.SCALES],
                         ["MIN", "MAJ", "DOR", "PHR", "HMIN", "PENT"])

    def test_zero_value_lands_on_the_root(self):
        self.assertEqual(tl.pitch(0, 8, root=0, scale_idx=0, octave=0, range_octaves=1), 36)

    def test_root_transposes_the_whole_line(self):
        a = tl.pitch(0, 8, root=0, scale_idx=0, octave=0, range_octaves=1)
        b = tl.pitch(0, 8, root=7, scale_idx=0, octave=0, range_octaves=1)
        self.assertEqual(b - a, 7)

    def test_octave_transposes_by_twelve(self):
        a = tl.pitch(200, 8, root=0, scale_idx=0, octave=0, range_octaves=2)
        b = tl.pitch(200, 8, root=0, scale_idx=0, octave=1, range_octaves=2)
        self.assertEqual(b - a, 12)

    def test_every_note_is_in_the_scale(self):
        intervals = tl.SCALES[0][1]
        for value in range(256):
            note = tl.pitch(value, 8, root=2, scale_idx=0, octave=0, range_octaves=3)
            self.assertIn((note - 2 - 36) % 12, intervals)

    def test_range_controls_the_spread(self):
        narrow = [tl.pitch(v, 8, 0, 0, 0, 1) for v in range(256)]
        wide = [tl.pitch(v, 8, 0, 0, 0, 4) for v in range(256)]
        self.assertLess(max(narrow) - min(narrow), max(wide) - min(wide))

    def test_notes_stay_inside_midi_range(self):
        for value in range(256):
            note = tl.pitch(value, 8, root=11, scale_idx=1, octave=2, range_octaves=4)
            self.assertTrue(0 <= note <= 127)

    def test_line_has_one_note_per_step(self):
        notes = tl.line(0b10110011, 8, 16, root=0, scale_idx=0, octave=0, range_octaves=2)
        self.assertEqual(len(notes), 16)


class TestChannelTable(unittest.TestCase):

    def test_eight_channels_five_drums_three_voices(self):
        self.assertEqual(len(tl.CHANNELS), 8)
        kinds = [c[2] for c in tl.CHANNELS]
        self.assertEqual(kinds.count("drum"), 5)
        self.assertEqual(kinds.count("voice"), 3)

    def test_channel_names_fit_the_four_character_cell(self):
        for c in tl.CHANNELS:
            self.assertLessEqual(len(c[1]), 4)

    def test_midi_channels_are_zero_to_seven(self):
        self.assertEqual([c[5] for c in tl.CHANNELS], list(range(8)))

    def test_every_voice_engine_has_all_four_symbols(self):
        for c in tl.CHANNELS:
            if c[2] == "voice":
                syms = tl.VOICE_SYMBOLS[c[4]]
                self.assertEqual(len(syms), 4)
                self.assertTrue(all(syms))


class TestFxMaps(unittest.TestCase):

    def test_reverb_roles_present(self):
        for role in ("WET", "DRY", "REVSIZE", "REVTYPE"):
            self.assertIn(role, tl.FX_REVERB)

    def test_delay_roles_present(self):
        for role in ("WET", "WET_R", "DRY", "DLYTIME", "DLYFBK"):
            self.assertIn(role, tl.FX_DELAY)

    def test_wet_is_a_true_level_not_a_blend(self):
        # gate G3: separate dB level ports, dry survives a full wet sweep
        self.assertEqual(tl.FX_REVERB["WET"][0], "wetlevel")
        self.assertEqual(tl.FX_REVERB["DRY"][0], "drylevel")
        self.assertEqual(tl.FX_DELAY["WET"][0], "lecholevel")
        self.assertEqual(tl.FX_DELAY["DRY"][0], "dryLevel")


class TestDelayTime(unittest.TestCase):

    def test_six_musical_divisions(self):
        self.assertEqual([d[0] for d in tl.DELAY_DIVISIONS],
                         ["1/16", "1/8", "3/16", "1/4", "3/8", "1/2"])

    def test_eighth_at_120_bpm_is_250_ms(self):
        self.assertAlmostEqual(tl.delay_ms(120.0, 1), 250.0, places=3)

    def test_quarter_at_132_bpm(self):
        self.assertAlmostEqual(tl.delay_ms(132.0, 3), 60000.0 / 132.0, places=3)

    def test_never_exceeds_the_plugin_maximum(self):
        self.assertLessEqual(tl.delay_ms(30.0, 5), tl.FX_DELAY["DLYTIME"][2])


def _desc(mode, kind):
    """Page 1 of a ring, for tests written before columns() took a descriptor."""
    return tl.PAGE_RINGS[tl.ring_key(mode, kind)][0]


def _page(mode, kind, title):
    """A page by name, so a test survives a page moving in its ring."""
    for desc in tl.PAGE_RINGS[tl.ring_key(mode, kind)]:
        if desc["title"] == title:
            return desc
    raise AssertionError(f"no page {title!r} in {mode}/{kind}")


class TestColumnModel(unittest.TestCase):

    def drum_state(self, **over):
        # `range` joined the fixture 2026-09-01 with the page: the kit-walk
        # window is a real drum verb, so a view without it is an INCOMPLETE
        # drum rather than a drum that lacks the control, and leaving it out
        # would have had law L4 draw a live column dead.
        s = dict(kit="T808", sample="KICK", level=82, reverb=24, delay=36,
                 range=2, hits=4, rotate=0, div=1, length=16, velo=110,
                 chance=100, swing=50, pending=set())
        s.update(over)
        return s

    def voice_state(self, **over):
        s = dict(preset="SUBB", cutoff=44, reso=71, env=96, decay=30, level=90,
                 reverb=12, delay=64, length=8, div=1, random=35, gate=40,
                 octave=-1, range=2, swing=58, velo=100, rhythm=0, rhythm_reg=0xFFFF,
                 pending=set())
        s.update(over)
        return s

    def globals_state(self, **over):
        # WALK and SPAN joined the fixture 2026-09-01, when they landed on the
        # GLOBAL page in place of REVTYPE and DLYFBK. Those two are kept in
        # the fixture: they are still globals, they just draw on the generated
        # REV and DLY pages now.
        s = dict(root=9, scale=0, bpm=132, master=88, walk=0, wspan=2,
                 revsize=72, revtype=3, dlytime=2, dlyfbk=58, pending=set())
        s.update(over)
        return s

    def test_every_page_returns_eight_columns(self):
        for page in tl.PAGES:
            for kind in ("drum", "voice"):
                st = self.globals_state() if page == "ALL" else (
                    self.drum_state() if kind == "drum" else self.voice_state())
                self.assertEqual(len(tl.columns(_desc(page, kind), kind, st)), 8, f"{page}/{kind}")

    def test_right_hand_trio_is_level_reverb_delay_on_control(self):
        for kind, st in (("drum", self.drum_state()), ("voice", self.voice_state())):
            cols = tl.columns(_desc("CONTROL", kind), kind, st)
            self.assertEqual([c["name"] for c in cols[5:]], ["LEVEL", "REVERB", "DELAY"])

    def test_rhythm_is_column_three_on_the_drum_auto_page(self):
        # MOVED 2026-09-01: RHYTHM left the drum STEP page for AUTO, because
        # AUTO is the one question "what does the machine do to this channel
        # by itself" and RHYTHM is one of six answers to it. SWING took the
        # slot it vacated on STEP - the spread page swing used to own is gone,
        # and the lens can only spread a verb that lives on a channel page.
        st = self.drum_state()
        self.assertEqual(
            tl.columns(_page("AUTO", "drum", "AUTO"), "drum", st)[2]["name"],
            "RHYTHM")

    def test_rhythm_is_column_four_on_the_voice_auto_page(self):
        # MOVED 2026-09-01 with the drum's, and it kept its neighbour: MELODY
        # is column three on the same page, so the owner's "the two generators
        # are one idea, put them side by side" survived the collapse.
        st = self.voice_state()
        self.assertEqual(
            tl.columns(_page("AUTO", "voice", "AUTO"), "voice", st)[3]["name"],
            "RHYTHM")

    def test_drum_control_has_three_greyed_columns(self):
        cols = tl.columns(_desc("CONTROL", "drum"), "drum", self.drum_state())
        grey = [c for c in cols if c["grey"]]
        # RANGE landed on slot 3 on 2026-09-01 to close a real gap - the
        # kit-walk window was reachable from no page at all - and it opened a
        # worse one, found at the rig within the hour: the kit walk only runs
        # when a channel is driven by the Turing register, so on a euclidean
        # drum RANGE is a column showing a number the knob cannot move. It
        # draws dead here and comes alive the moment the channel is switched
        # to voice behaviour.
        #
        # The names are the page title plus the slot number since 2026-09-01.
        # A slot with no verb has nothing else to be called, and a made-up
        # instrument name ("tune", "filtr") on a control that does not exist
        # was a promise the sampler could never keep.
        self.assertEqual([c["name"] for c in grey],
                         ["range", "ctrl4", "ctrl5"])
        for c in grey:
            self.assertEqual(c["value"], "----")
            self.assertIsNone(c["bar"])

    def test_voice_control_has_no_greyed_column(self):
        cols = tl.columns(_desc("CONTROL", "voice"), "voice", self.voice_state())
        self.assertEqual([c["name"] for c in cols if c["grey"]], [])

    def test_ratchet_is_LIVE_on_the_drum_step_page(self):
        # CHANGED 2026-08-19, SP10 step 3. This column was the page's dead
        # eighth slot from the prototype onwards, drawn `----` and greyed
        # because nothing wrote it. RATCHET fills it.
        # Column seven since 2026-09-01, was eight: RHYTHM left this page for
        # AUTO and SWING came back onto it in the last slot.
        col = tl.columns(_desc("STEP", "drum"), "drum", self.drum_state())[6]
        self.assertEqual(col["name"], "RATCH")
        self.assertFalse(col["grey"])
        self.assertEqual(col["value"], "OFF")

    def test_random_zero_reads_lock_not_a_number(self):
        # MELODY moved to the AUTO page with the rest of the generator on
        # 2026-09-01; it is column three there, still beside RHYTHM.
        col = tl.columns(_page("AUTO", "voice", "AUTO"), "voice",
                         self.voice_state(random=0))[2]
        self.assertEqual(col["value"], "LOCK")
        self.assertEqual(len(col["value"]), 4)

    def test_pending_value_is_wrapped_in_angle_brackets(self):
        st = self.drum_state(div=2, pending={"div"})
        col = tl.columns(_desc("STEP", "drum"), "drum", st)[2]
        self.assertTrue(col["pending"])
        self.assertTrue(col["value"].startswith(">") and col["value"].endswith("<"))

    def test_global_page_is_the_same_for_both_kinds(self):
        # The ALL ring became the VOLUME ring on 2026-09-01 - ALL is no longer
        # a mode, it is the held lens - and the GLOBAL page traded REVTYPE and
        # DLYFBK for WALK and SPAN, which is what emptied the old WALK page.
        # The point of the test is unchanged: a page with no channel must not
        # vary by the kind of channel that happens to be selected.
        gl = self.globals_state()
        a = [c["name"] for c in tl.columns(_desc("VOLUME", "drum"), "drum", gl)]
        b = [c["name"] for c in tl.columns(_desc("VOLUME", "voice"), "voice", gl)]
        self.assertEqual(a, b)
        self.assertEqual(a, ["ROOT", "SCALE", "BPM", "WALK", "SPAN",
                             "MASTER", "REVSIZE", "DLYTIME"])

    def test_every_value_fits_the_cell(self):
        for page, kind, st in (("CONTROL", "drum", self.drum_state()),
                               ("CONTROL", "voice", self.voice_state()),
                               ("STEP", "drum", self.drum_state()),
                               ("STEP", "voice", self.voice_state()),
                               ("AUTO", "drum", self.drum_state()),
                               ("AUTO", "voice", self.voice_state()),
                               ("VOLUME", "drum", self.globals_state())):
            for c in tl.columns(_desc(page, kind), kind, st):
                self.assertLessEqual(len(c["value"].strip("><")), 4,
                                     f"{page}/{kind}/{c['name']}={c['value']}")

    def test_octave_draws_a_bipolar_bar(self):
        # Encoder 4 since the 2026-09-01 collapse, was 6: the two generator
        # columns left the voice STEP page for AUTO and everything after them
        # shifted left.
        col = tl.columns(_desc("STEP", "voice"), "voice", self.voice_state())[3]
        self.assertEqual(col["name"], "OCTAVE")
        self.assertEqual(col["bar"], "bi")

    def test_a_greyed_column_never_carries_a_bar(self):
        for page, kind, st in (("CONTROL", "drum", self.drum_state()),
                               ("STEP", "drum", self.drum_state())):
            for c in tl.columns(_desc(page, kind), kind, st):
                if c["grey"]:
                    self.assertIsNone(c["bar"])


class TestPageRings(unittest.TestCase):

    def test_ring_key_drops_kind_for_modes_not_keyed_by_kind(self):
        # Was MIXER, FILTER and ALL. All three stopped being modes on
        # 2026-09-01 - the two spread rings became the lens, and ALL became
        # the lens button - so VOLUME is now the only ring that asks nothing
        # about the selected channel.
        self.assertEqual(tl.ring_key("VOLUME", "drum"), ("VOLUME", None))
        self.assertEqual(tl.ring_key("VOLUME", "voice"), ("VOLUME", None))

    def test_ring_key_keeps_kind_for_control_step_and_auto(self):
        self.assertEqual(tl.ring_key("CONTROL", "drum"), ("CONTROL", "drum"))
        self.assertEqual(tl.ring_key("STEP", "voice"), ("STEP", "voice"))
        # AUTO joined the keyed set 2026-09-01: a drum's generator and a
        # voice's are different instruments, so its pages differ by kind.
        self.assertEqual(tl.ring_key("AUTO", "drum"), ("AUTO", "drum"))

    def test_every_mode_has_a_ring_for_every_kind(self):
        for mode in tl.MODES:
            for kind in ("drum", "voice"):
                key = tl.ring_key(mode, kind)
                self.assertIn(key, tl.PAGE_RINGS, f"no ring for {key}")
                self.assertGreater(len(tl.PAGE_RINGS[key]), 0)

    def test_channel_and_global_pages_carry_eight_verb_slots(self):
        for key, ring in tl.PAGE_RINGS.items():
            for desc in ring:
                if desc["shape"] in (tl.SHAPE_CHANNEL, tl.SHAPE_GLOBAL):
                    self.assertEqual(len(desc["verbs"]), 8, f"{key} {desc['title']}")
                    self.assertIsNone(desc["verb"])

    def test_spread_pages_carry_one_verb_and_no_verb_list(self):
        # No ring holds a spread page any more - the lens builds them on
        # demand - so the ring sweep alone would pass vacuously. The lens
        # descriptors are checked beside it, which is where the shape now
        # comes from.
        for key, ring in tl.PAGE_RINGS.items():
            for desc in ring:
                if desc["shape"] == tl.SHAPE_SPREAD:
                    self.assertIsInstance(desc["verb"], str)
                    self.assertIsNone(desc["verbs"])
        for verb in ("level", "reverb", "delay", "cutoff", "reso"):
            desc = tl.lens_desc(verb)
            self.assertEqual(desc["shape"], tl.SHAPE_SPREAD)
            self.assertEqual(desc["verb"], verb)
            self.assertIsNone(desc["verbs"])

    def test_the_lens_reaches_level_reverb_and_delay(self):
        # WAS test_mixer_ring_is_level_reverb_delay. The MIXER ring's three
        # pages were level, reverb and delay across eight channels; the ring
        # went on 2026-09-01 because "one verb across eight channels" is a
        # direction of looking, not a place. The same three views are still
        # reachable - now from any level, by holding ALL after turning one of
        # them - so the test checks the lens rather than the ring.
        for verb, label in (("level", "LEVEL"), ("reverb", "REVERB"),
                            ("delay", "DELAY")):
            self.assertEqual(tl.lens_verb(verb), verb)
            self.assertEqual(tl.lens_desc(verb)["title"], f"ALL {label}")
        # And LEVEL is what the lens shows before a hand has moved anything,
        # which is the page MIXER opened on.
        self.assertEqual(tl.lens_verb(None), "level")

    def test_the_lens_reaches_cutoff_and_reso(self):
        # WAS test_filter_ring_is_cutoff_reso, and gone for the same reason as
        # the MIXER ring. Both verbs still spread across all eight channels.
        for verb, label in (("cutoff", "CUTOFF"), ("reso", "RESO")):
            self.assertEqual(tl.lens_verb(verb), verb)
            self.assertEqual(tl.lens_desc(verb)["title"], f"ALL {label}")

    def test_step_ring_is_one_channel_page_on_both_kinds(self):
        # WAS test_step_ring_keeps_its_channel_page_first, which also asserted
        # the SWING and CHANCE spread pages behind it. Those two became lens
        # views on 2026-09-01, and both verbs moved onto the channel page so
        # the lens has somewhere to read them from.
        for kind in ("drum", "voice"):
            ring = tl.PAGE_RINGS[("STEP", kind)]
            self.assertEqual(ring[0]["shape"], tl.SHAPE_CHANNEL)
            self.assertEqual(len(ring), 1)
            self.assertIn("swing", ring[0]["verbs"])
            self.assertIn("chance", ring[0]["verbs"])

    def test_step_channel_page_verbs_match_the_shipped_layout(self):
        # Reordered 2026-09-01 by the collapse from 24 pages to 9: the two
        # generator columns went to AUTO, and SWING and CHANCE came back onto
        # the page from the spread pages that no longer exist.
        self.assertEqual(
            tl.PAGE_RINGS[("STEP", "drum")][0]["verbs"],
            ("hits", "rotate", "div", "length", "velo", "chance", "ratchet",
             "swing"))
        # The voice keeps the owner's 2026-08-16 principle - pattern time
        # first, then how the note is played, then pitch - minus MELODY and
        # RHYTHM, which now sit side by side on AUTO instead.
        #
        # CHORD took RANGE's slot on 2026-09-02 and RANGE moved to the LINE
        # page. It is the same slot on purpose: both answer "what pitches",
        # and the hand that used to find RANGE fifth now finds CHORD there.
        self.assertEqual(
            tl.PAGE_RINGS[("STEP", "voice")][0]["verbs"],
            ("div", "length", "gate", "octave", "chord", "velo",
             "chance", "swing"))

    def test_control_channel_page_verbs_match_the_shipped_layout(self):
        # RANGE took slot 3 on the drum page, 2026-09-01: the kit-walk window
        # was reachable from no page at all, and it is a sound parameter, so
        # it fills one of the three slots a sampler could never fill.
        self.assertEqual(
            tl.PAGE_RINGS[("CONTROL", "drum")][0]["verbs"],
            ("kit", "sample", "range", None, None, "level", "reverb", "delay"))
        self.assertEqual(
            tl.PAGE_RINGS[("CONTROL", "voice")][0]["verbs"],
            ("preset", "cutoff", "reso", "env", "decay", "level", "reverb", "delay"))

    def test_global_page_one_keeps_every_shipped_global(self):
        # The ALL ring became the VOLUME ring on 2026-09-01. REVTYPE and
        # DLYFBK left this page so WALK and SPAN could land on it, which is
        # what emptied the old four-dead-column WALK page; they are not lost,
        # because every port GLOBAL does not name appears on the generated REV
        # and DLY pages. DLYTIME stays: it is a musical division resolved
        # against live tempo, not a raw plugin port.
        self.assertEqual(
            tl.PAGE_RINGS[("VOLUME", None)][0]["verbs"],
            ("root", "scale", "bpm", "walk", "wspan", "master",
             "revsize", "dlytime"))


class TestPageIndexArithmetic(unittest.TestCase):

    def test_step_index_wraps_forward(self):
        self.assertEqual(tl.step_index(2, 1, 3), 0)

    def test_step_index_wraps_backward(self):
        self.assertEqual(tl.step_index(0, -1, 3), 2)

    def test_step_index_on_a_single_page_ring_stays_put(self):
        self.assertEqual(tl.step_index(0, 1, 1), 0)
        self.assertEqual(tl.step_index(0, -1, 1), 0)

    def test_clamp_index_pulls_an_out_of_range_index_into_the_ring(self):
        self.assertEqual(tl.clamp_index(7, 3), 2)
        self.assertEqual(tl.clamp_index(-4, 3), 0)

    def test_clamp_index_of_an_empty_ring_is_zero(self):
        self.assertEqual(tl.clamp_index(3, 0), 0)


def _drum_view(**over):
    # `kind` joined both fixtures 2026-09-01: spread_columns takes the kind
    # from the view now, one per channel, because the lens shows drums and
    # voices side by side and there is no single kind to pass it.
    view = dict(kind="drum", hits=4, rotate=0, div=1, length=16, velo=110,
                chance=100, swing=50, rhythm=0, level=19, reverb=0, delay=0,
                range=2, kit="909", sample="BD", pending=set())
    view.update(over)
    return view


def _voice_view(**over):
    view = dict(kind="voice", length=8, div=1, random=0, gate=40, octave=0, range=2,
                swing=50, velo=110, level=19, reverb=0, delay=0, chance=100,
                rhythm=0, rhythm_reg=0xFFFF, preset="SAW", cutoff=64, reso=32, env=64, decay=40,
                chord=0, pending=set())
    view.update(over)
    return view


class TestColumnsByShape(unittest.TestCase):

    def test_channel_shape_still_renders_the_shipped_step_page(self):
        desc = tl.PAGE_RINGS[("STEP", "drum")][0]
        cols = tl.columns(desc, "drum", _drum_view())
        # RHYTHM left for AUTO and SWING came back off its spread page in the
        # 2026-09-01 collapse, so RATCH moved from slot 8 to slot 7.
        self.assertEqual([c["name"] for c in cols],
                         ["HITS", "ROTATE", "DIVIDE", "LENGTH", "VELO",
                          "CHANCE", "RATCH", "SWING"])
        # No longer greyed: SP10 step 3 gave the slot a verb, 2026-08-19.
        self.assertFalse(cols[6]["grey"])

    def test_global_shape_still_renders_the_shipped_global_page(self):
        # The ALL ring became the VOLUME ring, and REVTYPE and DLYFBK gave up
        # their slots to WALK and SPAN, 2026-09-01.
        desc = tl.PAGE_RINGS[("VOLUME", None)][0]
        state = dict(root=9, scale=0, bpm=132, master=80, revsize=25,
                     walk=0, wspan=2, revtype=3, dlytime=1, dlyfbk=35,
                     pending=set())
        cols = tl.columns(desc, "drum", state)
        self.assertEqual([c["name"] for c in cols],
                         ["ROOT", "SCALE", "BPM", "WALK", "SPAN",
                          "MASTER", "REVSIZE", "DLYTIME"])

    def test_spread_shape_labels_each_column_with_its_channel(self):
        # The MIXER ring's LEVEL page is a lens view since 2026-09-01. What is
        # under test is unchanged: a spread column is named for its CHANNEL,
        # because the verb is already in the page title.
        desc = tl.lens_desc("level")
        views = [(chr(ord("A") + i), name, _drum_view(level=10 * i))
                 for i, name in enumerate(
                     ["KICK", "SNAR", "CLAP", "CHAT", "OHAT", "BASS", "LEAD", "PADS"])]
        cols = tl.columns(desc, None, views)
        self.assertEqual(len(cols), 8)
        self.assertEqual(cols[0]["name"], "A KICK")
        self.assertEqual(cols[5]["name"], "F BASS")
        self.assertEqual(cols[3]["value"], "0030")

    def test_spread_greys_a_channel_that_lacks_the_verb(self):
        # A drum has no cutoff: LinuxSampler publishes no controllers and the
        # SoundFont CC 74 route is a measured dead end. The column says so.
        # Through the lens since 2026-09-01, where the FILTER ring used to be.
        desc = tl.lens_desc("cutoff")
        views = [("A", "KICK", _drum_view()), ("F", "BASS", _voice_view())]
        views += [("X", "----", _drum_view())] * 6
        cols = tl.columns(desc, None, views)
        self.assertTrue(cols[0]["grey"])
        self.assertEqual(cols[0]["value"], "----")
        self.assertIsNone(cols[0]["bar"])
        self.assertFalse(cols[1]["grey"])
        self.assertEqual(cols[1]["value"], "0064")

    def test_spread_swing_uses_the_shipped_swing_fraction(self):
        # The STEP ring's SWING spread page became a lens view, 2026-09-01.
        desc = tl.lens_desc("swing")
        views = [("A", "KICK", _drum_view(swing=75))] * 8
        cols = tl.columns(desc, "drum", views)
        self.assertAlmostEqual(cols[0]["frac"], 1.0)

    def test_spread_chance_reads_a_voice_too(self):
        # The STEP ring's CHANCE spread page became a lens view, 2026-09-01.
        desc = tl.lens_desc("chance")
        views = [("F", "BASS", _voice_view(chance=0))] * 8
        cols = tl.columns(desc, "voice", views)
        self.assertEqual(cols[0]["value"], "0000")
        self.assertFalse(cols[0]["grey"])


class TestPageLabel(unittest.TestCase):

    def test_single_page_ring_shows_no_position(self):
        self.assertEqual(tl.page_label("CTRL", 0, 1), "CTRL")

    def test_multi_page_ring_shows_one_based_position(self):
        self.assertEqual(tl.page_label("LEVEL", 0, 3), "LEVEL 1/3")
        self.assertEqual(tl.page_label("DELAY", 2, 3), "DELAY 3/3")


class TestMeterQuantisation(unittest.TestCase):

    def test_quantise_snaps_to_whole_pixels(self):
        self.assertEqual(tl.quantise_frac(0.5, 52), round(0.5 * 52) / 52)

    def test_two_values_inside_one_pixel_quantise_equal(self):
        # This is the whole point: a steady signal must stop repainting, or
        # mixer mode pushes ~50 OSC packets per screen per 100 ms forever.
        a = tl.quantise_frac(0.5000, 52)
        b = tl.quantise_frac(0.5090, 52)
        self.assertEqual(a, b)

    def test_quantise_clamps_out_of_range_input(self):
        self.assertEqual(tl.quantise_frac(-3.0, 52), 0.0)
        self.assertEqual(tl.quantise_frac(9.0, 52), 1.0)


class TestPortFilter(unittest.TestCase):

    def test_drops_ports_with_no_range(self):
        ports = [("cutoff", 0.0, 1.0), ("bypass", 1.0, 1.0)]
        self.assertEqual([p[0] for p in tl.usable_ports(ports)], ["cutoff"])

    def test_drops_excluded_symbols(self):
        ports = [("cutoff", 0.0, 1.0), ("resonance", 0.0, 1.0)]
        got = tl.usable_ports(ports, exclude=("cutoff",))
        self.assertEqual([p[0] for p in got], ["resonance"])

    def test_drops_non_numeric_bounds(self):
        ports = [("good", 0.0, 1.0), ("bad", None, 1.0)]
        self.assertEqual([p[0] for p in tl.usable_ports(ports)], ["good"])

    def test_preserves_order(self):
        ports = [("z", 0.0, 1.0), ("a", 0.0, 1.0)]
        self.assertEqual([p[0] for p in tl.usable_ports(ports)], ["z", "a"])


class TestPortLabel(unittest.TestCase):

    def test_uppercases_and_truncates_to_eight(self):
        self.assertEqual(tl.port_label("filterenvamount"), "FILTEREN")

    def test_strips_a_leading_underscore(self):
        # JC303 publishes _cutoff, _resonance, _envmod, _decay.
        self.assertEqual(tl.port_label("_cutoff"), "CUTOFF")

    def test_short_symbol_survives_intact(self):
        self.assertEqual(tl.port_label("decay"), "DECAY")


class TestGeneratedPages(unittest.TestCase):

    def _ports(self, n):
        return [(f"p{i}", 0.0, 1.0) for i in range(n)]

    def test_no_usable_ports_yields_no_pages(self):
        # A LinuxSampler drum chain publishes nothing. Its ring stays length 1
        # and DL/DR do nothing there, which is honest.
        self.assertEqual(
            tl.generated_pages([], (), tl.SHAPE_CHANNEL, tl.VERB_LV2, "EXTRA"),
            ())

    def test_nine_ports_make_two_pages(self):
        pages = tl.generated_pages(self._ports(9), (), tl.SHAPE_CHANNEL,
                                   tl.VERB_LV2, "EXTRA")
        self.assertEqual(len(pages), 2)

    def test_a_short_final_page_is_padded_with_none(self):
        pages = tl.generated_pages(self._ports(9), (), tl.SHAPE_CHANNEL,
                                   tl.VERB_LV2, "EXTRA")
        self.assertEqual(len(pages[1]["verbs"]), 8)
        self.assertEqual(pages[1]["verbs"][1:], (None,) * 7)

    def test_verbs_carry_the_prefix_and_the_symbol(self):
        pages = tl.generated_pages(self._ports(2), (), tl.SHAPE_CHANNEL,
                                   tl.VERB_LV2, "EXTRA")
        self.assertEqual(pages[0]["verbs"][0], "lv2:p0")

    def test_fx_pages_are_global_shaped_and_carry_the_role(self):
        pages = tl.generated_pages(self._ports(2), (), tl.SHAPE_GLOBAL,
                                   tl.VERB_FX + "reverb:", "REVERB")
        self.assertEqual(pages[0]["shape"], tl.SHAPE_GLOBAL)
        self.assertEqual(pages[0]["verbs"][0], "fx:reverb:p0")

    def test_titles_number_only_when_there_is_more_than_one_page(self):
        one = tl.generated_pages(self._ports(3), (), tl.SHAPE_CHANNEL,
                                 tl.VERB_LV2, "EXTRA")
        many = tl.generated_pages(self._ports(20), (), tl.SHAPE_CHANNEL,
                                  tl.VERB_LV2, "EXTRA")
        self.assertEqual(one[0]["title"], "EXTRA")
        self.assertEqual([p["title"] for p in many], ["EXTRA1", "EXTRA2", "EXTRA3"])

    def test_generated_columns_render_from_a_view(self):
        pages = tl.generated_pages(self._ports(2), (), tl.SHAPE_CHANNEL,
                                   tl.VERB_LV2, "EXTRA")
        cols = tl.columns(pages[0], "voice", {"lv2:p0": 50, "pending": set()})
        self.assertEqual(cols[0]["name"], "P0")
        self.assertEqual(cols[0]["value"], "0050")
        # p1 has no value in the view: a port that vanished with a preset
        # change says so rather than showing a stale number.
        self.assertTrue(cols[1]["grey"])
        # the six padding slots draw nothing at all
        self.assertEqual(cols[7]["name"], "")

    def test_generated_pages_are_flagged(self):
        pages = tl.generated_pages(self._ports(1), (), tl.SHAPE_CHANNEL,
                                   tl.VERB_LV2, "EXTRA")
        self.assertTrue(pages[0]["generated"])


class TestRegisterRotate(unittest.TestCase):

    def test_a_full_rotation_is_the_identity(self):
        reg = 0b10110011
        self.assertEqual(tl.rotate(reg, 8, 8), reg)

    def test_no_rotation_is_the_identity(self):
        self.assertEqual(tl.rotate(0b1011, 4, 0), 0b1011)

    def test_one_rotation_moves_the_top_bit_to_the_bottom(self):
        self.assertEqual(tl.rotate(0b1000, 4, 1), 0b0001)

    def test_rotation_stays_inside_the_register_width(self):
        self.assertEqual(tl.rotate(0b1111, 4, 3), 0b1111)


class TestGateValues(unittest.TestCase):

    def test_it_yields_one_value_per_step(self):
        self.assertEqual(len(tl.gate_values(0b1011, 4, 16)), 16)

    def test_it_is_periodic_in_the_register_length(self):
        vals = tl.gate_values(0b10110011, 8, 16)
        self.assertEqual(vals[:8], vals[8:])

    def test_it_is_offset_from_the_pitch_stream(self):
        # The whole point of the tap: rhythm and pitch read the same register
        # at different points, so the two do not move in lockstep.
        reg, length = 0b10110011, 8
        self.assertNotEqual(tl.gate_values(reg, length, 8),
                            tl.rotations(reg, length, 8))

    def test_the_offset_is_half_the_register_length(self):
        reg, length = 0b10110011, 8
        self.assertEqual(tl.gate_values(reg, length, 4),
                         tl.rotations(reg, length, 8)[4:8])

    def test_a_degenerate_register_yields_one_repeated_value(self):
        self.assertEqual(set(tl.gate_values(0b1111, 4, 16)), {0b1111})


class TestGateMask(unittest.TestCase):

    def test_full_density_sounds_every_step(self):
        for reg in (0b0000, 0b1011, 0b1111, 0b0110):
            mask = tl.gate_mask(reg, 4, 16, 1.0)
            self.assertEqual(mask, (True,) * 16, f"register {reg:04b}")

    def test_zero_density_sounds_nothing(self):
        for reg in (0b0000, 0b1011, 0b1111):
            mask = tl.gate_mask(reg, 4, 16, 0.0)
            self.assertEqual(mask, (False,) * 16, f"register {reg:04b}")

    def test_the_count_is_round_density_times_steps(self):
        reg, length, steps = 0b1011001110100101, 16, 16
        for percent in range(0, 101):
            mask = tl.gate_mask(reg, length, steps, percent / 100.0)
            self.assertEqual(sum(mask), round(percent / 100.0 * steps),
                             f"density {percent}")

    def test_lowering_density_only_removes_steps(self):
        # Monotonic: turning the knob down thins the line, it never
        # rearranges it.
        for reg in (0b1011001110100101, 0b1100110011001100, 0b0000000000000001):
            previous = None
            for percent in range(100, -1, -1):
                mask = tl.gate_mask(reg, 16, 16, percent / 100.0)
                on = {i for i, bit in enumerate(mask) if bit}
                if previous is not None:
                    self.assertTrue(on <= previous,
                                    f"register {reg:016b} density {percent}")
                previous = on

    def test_a_degenerate_all_ones_register_takes_the_first_n_steps(self):
        # Every rotation is equal, so the tie-break decides and it is the step
        # index. Deterministic, audible for what it is, one nudge of RANDOM
        # away from resolving.
        mask = tl.gate_mask(0b1111, 4, 16, 0.25)
        self.assertEqual(mask, (True,) * 4 + (False,) * 12)

    def test_a_degenerate_all_zeros_register_takes_the_first_n_steps(self):
        mask = tl.gate_mask(0b0000, 4, 16, 0.5)
        self.assertEqual(mask, (True,) * 8 + (False,) * 8)

    def test_the_quietest_steps_are_the_ones_that_sound(self):
        reg, length, steps = 0b1011001110100101, 16, 16
        values = tl.gate_values(reg, length, steps)
        mask = tl.gate_mask(reg, length, steps, 0.25)
        chosen = [v for v, bit in zip(values, mask) if bit]
        rejected = [v for v, bit in zip(values, mask) if not bit]
        self.assertLessEqual(max(chosen), min(rejected))

    def test_a_single_step_pattern_survives(self):
        self.assertEqual(tl.gate_mask(0b10, 2, 1, 1.0), (True,))
        self.assertEqual(tl.gate_mask(0b10, 2, 1, 0.0), (False,))


class TestRhythmPage(unittest.TestCase):
    """Was TestDensityPage. DENSITY became RHYTHM on 2026-08-16 - same
    encoder, same spread page, a generator instead of a count."""

    def test_the_lens_spreads_rhythm(self):
        # WAS test_the_voice_step_ring_gains_a_rhythm_page. The RHYTHM spread
        # page went with every other one on 2026-09-01; the view it gave is
        # now the lens over the RHYTHM verb, reachable from AUTO where the
        # verb itself lives.
        self.assertEqual(tl.lens_verb("rhythm"), "rhythm")
        self.assertEqual(tl.lens_desc("rhythm")["title"], "ALL RHYTHM")

    def test_the_drum_auto_page_carries_rhythm(self):
        # REVERSED BY THE OWNER, 2026-08-31. This test used to read "a drum's
        # rhythm is HITS and ROTATE, already exact - euclidean channels get no
        # second generator", and the drum rhythm register is exactly that
        # second generator.
        #
        # RETARGETED 2026-09-01: it read the drum STEP ring's two spread pages
        # and the GEN page behind them. The rings collapsed from 24 pages to
        # 9, the spread pages became the lens, and the generative verbs moved
        # to AUTO - so RHYTHM on a drum is now a column on the AUTO page.
        self.assertIn("rhythm", _page("AUTO", "drum", "AUTO")["verbs"])
        self.assertEqual(len(tl.PAGE_RINGS[("STEP", "drum")]), 1)

    def test_rhythm_sits_beside_melody_on_the_voice_auto_page(self):
        # The owner's "the two generators are one idea, put them side by side"
        # survived the 2026-09-01 collapse: both moved from the voice STEP
        # page to the voice AUTO page, still adjacent.
        self.assertEqual(
            _page("AUTO", "voice", "AUTO")["verbs"],
            ("rule", "model", "random", "rhythm", "move", "phrase",
             "fill", "exit"))

    def test_the_spread_spec_maps_the_full_range(self):
        # Reads VERB_COLS, not SPREAD_SPECS: since 2026-09-01 a spread column
        # comes from the same table the channel pages read, which is what let
        # the lens spread every verb instead of the twelve SPREAD_SPECS held.
        _, _, to_frac, _ = tl.VERB_COLS["rhythm"]
        self.assertEqual(to_frac(0), 0.0)
        self.assertEqual(to_frac(100), 1.0)

    def test_the_rhythm_lens_reaches_a_drum_too(self):
        # It used to grey a drum, because a drum view carried no `rhythm` key
        # and spread_columns draws dead where the source does not exist. The
        # drum rhythm register puts the key on the drum state, so this view
        # lights up for all eight channels with NO change to the page itself -
        # the grey was never a rule, it was the absence of a value.
        desc = tl.lens_desc("rhythm")
        views = [("A", "KICK", _drum_view()), ("F", "BASS", _voice_view())]
        views += [("X", "----", _drum_view())] * 6
        cols = tl.columns(desc, None, views)
        self.assertFalse(cols[0]["grey"])
        # The word, not 0000, since 2026-09-01: a spread column now comes from
        # VERB_COLS, which has always formatted a frozen generator as LOCK on
        # the channel pages. The old SPREAD_SPECS entry had no formatter, so
        # the two surfaces disagreed about the same value.
        self.assertEqual(cols[0]["value"], "LOCK")
        self.assertFalse(cols[1]["grey"])
        # 0 is LOCK: a voice starts with its rhythm frozen, where DENSITY
        # started at 100. The steps it sounds come from the register, which
        # starts with every bit set - so the SOUND is unchanged, only the
        # number on this page moves.
        self.assertEqual(cols[1]["value"], "LOCK")


class TestQuarterDivisionLabel(unittest.TestCase):

    def test_label_table_gains_the_quarter_division_last(self):
        self.assertEqual(tl.DIVISION_LABELS[5], "1/4")

    def test_label_table_matches_the_division_table_in_length(self):
        import maschine_mk2_lib as mlib
        self.assertEqual(len(tl.DIVISION_LABELS),
                         len(mlib.maschine_mk2_lib.DIVISIONS))

    def test_the_first_five_labels_are_unchanged(self):
        self.assertEqual(list(tl.DIVISION_LABELS[:5]),
                         ["1/32", "1/16", "1/8", "1/16T", "1/8T"])


class TestGateRange(unittest.TestCase):

    def test_gate_max_is_eight_steps_worth(self):
        # duration = gate / 100, measured in steps. 800 is eight steps, which
        # at the 1/4 division is a two-bar note.
        self.assertEqual(tl.GATE_MAX, 800)

    def test_gate_column_renders_the_new_maximum(self):
        state = _voice_view(gate=800)
        cols = tl.columns(tl.PAGE_RINGS[("STEP", "voice")][0], "voice", state)
        gate_col = next(c for c in cols if c["name"] == "GATE")
        self.assertEqual(gate_col["value"], "0800")
        self.assertAlmostEqual(gate_col["frac"], 1.0)

    def test_gate_column_bar_is_scaled_to_the_new_maximum(self):
        # A gate of 100 used to fill the bar. It is now one eighth of it, and
        # that is the point: the bar shows note length, not knob travel.
        state = _voice_view(gate=100)
        cols = tl.columns(tl.PAGE_RINGS[("STEP", "voice")][0], "voice", state)
        gate_col = next(c for c in cols if c["name"] == "GATE")
        self.assertAlmostEqual(gate_col["frac"], 0.125)


class TestNoteDuration(unittest.TestCase):

    def test_a_note_early_in_the_pattern_gets_its_full_length(self):
        self.assertAlmostEqual(tl.note_duration(800, 0, 16), 8.0)

    def test_a_note_is_clamped_to_the_steps_remaining(self):
        # Step 14 of a 16-step pattern has two steps left, so eight is not
        # available. The clamp is conservative on purpose: it makes a note
        # that outlives its pattern unreachable while the note-off behaviour
        # at the loop point is unproven.
        self.assertAlmostEqual(tl.note_duration(800, 14, 16), 2.0)

    def test_a_note_on_the_last_step_gets_one_step(self):
        self.assertAlmostEqual(tl.note_duration(800, 15, 16), 1.0)

    def test_a_short_gate_is_unaffected_by_the_clamp(self):
        self.assertAlmostEqual(tl.note_duration(50, 15, 16), 0.5)

    def test_duration_never_reaches_zero(self):
        # A zero-length note is a note that never sounds, which is silence
        # with no explanation - the failure this instrument has a law about.
        self.assertGreaterEqual(tl.note_duration(0, 15, 16), 0.05)
        self.assertGreaterEqual(tl.note_duration(5, 0, 16), 0.05)

    def test_it_matches_the_old_behaviour_for_every_legacy_gate(self):
        # Gate 5..100 on step 0 behaved as gate/100 before this change and
        # must still, or every existing pattern changes character.
        for gate in range(5, 101):
            self.assertAlmostEqual(tl.note_duration(gate, 0, 16), gate / 100.0)


class TestPortDenyList(unittest.TestCase):

    def test_drops_the_lv2_freewheel_host_port(self):
        # Drawn as LV2_FREE on the surface, does nothing, took a column.
        ports = [("lv2_freewheel", 0.0, 1.0), ("cutoff", 0.0, 1.0)]
        self.assertEqual([p[0] for p in tl.usable_ports(ports)], ["cutoff"])

    def test_drops_every_lv2_prefixed_port(self):
        ports = [("lv2_port_1", 0.0, 1.0), ("lv2_anything", 0.0, 5.0)]
        self.assertEqual(tl.usable_ports(ports), [])

    def test_drops_unused_ports(self):
        ports = [("unused_1", 0.0, 1.0), ("unused", 0.0, 1.0)]
        self.assertEqual(tl.usable_ports(ports), [])

    def test_drops_host_control_ports_by_exact_name(self):
        ports = [("latency", 0.0, 100.0), ("enabled", 0.0, 1.0),
                 ("bypass", 0.0, 1.0), ("freeWheeling", 0.0, 1.0)]
        self.assertEqual(tl.usable_ports(ports), [])

    def test_keeps_a_musical_enabled_toggle(self):
        # padthv1 publishes DCF1_ENABLED and LFO1_ENABLED - genuine section
        # switches a player wants. Exact matching is what keeps them alive
        # while "enabled" on its own is dropped.
        ports = [("DCF1_ENABLED", 0.0, 1.0), ("LFO1_ENABLED", 0.0, 1.0)]
        self.assertEqual([p[0] for p in tl.usable_ports(ports)],
                         ["DCF1_ENABLED", "LFO1_ENABLED"])

    def test_deny_matching_ignores_case(self):
        ports = [("Latency", 0.0, 100.0), ("LV2_Freewheel", 0.0, 1.0)]
        self.assertEqual(tl.usable_ports(ports), [])


class TestDiscretePorts(unittest.TestCase):

    def test_an_integer_toggle_is_discrete(self):
        # 0-1 integer: one percent of it is 0.01, and _set_value() truncates
        # integer controls, so a percentage knob can never move it.
        self.assertTrue(tl.port_is_discrete(0.0, 1.0, True))

    def test_a_float_port_of_the_same_range_is_continuous(self):
        # A 0.0-1.0 volume does NOT truncate, so percentage stepping is right.
        # Range width alone is the wrong question - this is the case that a
        # span-only rule got wrong on hardware.
        self.assertFalse(tl.port_is_discrete(0.0, 1.0, False))

    def test_a_small_integer_enum_is_discrete(self):
        self.assertTrue(tl.port_is_discrete(0.0, 4.0, True))

    def test_a_wide_integer_port_is_continuous(self):
        # 1% of 0-127 is 1.27, which survives truncation.
        self.assertFalse(tl.port_is_discrete(0.0, 127.0, True))

    def test_a_wide_float_port_is_continuous(self):
        self.assertFalse(tl.port_is_discrete(20.0, 20000.0, False))

    def test_the_boundary_is_one_unit_per_percent(self):
        self.assertTrue(tl.port_is_discrete(0.0, 99.0, True))
        self.assertFalse(tl.port_is_discrete(0.0, 100.0, True))

    def test_step_moves_a_toggle_by_a_whole_unit(self):
        self.assertEqual(tl.step_port_value(0.0, 0.0, 1.0, 1), 1.0)
        self.assertEqual(tl.step_port_value(1.0, 0.0, 1.0, -1), 0.0)

    def test_step_clamps_at_both_ends(self):
        self.assertEqual(tl.step_port_value(1.0, 0.0, 1.0, 3), 1.0)
        self.assertEqual(tl.step_port_value(0.0, 0.0, 1.0, -3), 0.0)


class TestRecordStep(unittest.TestCase):

    def test_the_start_of_a_step_is_that_step(self):
        self.assertEqual(tl.record_step(0, 24, 16), 0)
        self.assertEqual(tl.record_step(48, 24, 16), 2)

    def test_just_before_the_midpoint_stays_on_the_step(self):
        self.assertEqual(tl.record_step(11, 24, 16), 0)

    def test_the_midpoint_rounds_up(self):
        self.assertEqual(tl.record_step(12, 24, 16), 1)

    def test_a_late_strike_wraps_to_step_zero(self):
        # Step 15 of 16, past its midpoint: the loop wraps within a step, so
        # step 0 of the next pass IS the nearest grid line in time.
        self.assertEqual(tl.record_step(15 * 24 + 13, 24, 16), 0)

    def test_a_degenerate_pattern_never_raises(self):
        self.assertEqual(tl.record_step(100, 0, 16), 0)
        self.assertEqual(tl.record_step(100, 24, 0), 0)


class TestRecordDuration(unittest.TestCase):

    def test_a_short_tap_is_one_step(self):
        self.assertEqual(tl.record_duration(3, 24, 0, 16), 1.0)

    def test_a_hold_rounds_to_whole_steps(self):
        self.assertEqual(tl.record_duration(24 * 4, 24, 0, 16), 4.0)
        self.assertEqual(tl.record_duration(24 * 4 + 13, 24, 0, 16), 5.0)

    def test_it_never_crosses_the_loop_point(self):
        # SP5's clamp: a note at step 15 of 16 can only be one step long.
        self.assertEqual(tl.record_duration(24 * 8, 24, 15, 16), 1.0)
        self.assertEqual(tl.record_duration(24 * 8, 24, 12, 16), 4.0)

    def test_a_full_length_hold_from_step_zero_fills_the_pattern(self):
        self.assertEqual(tl.record_duration(24 * 16, 24, 0, 16), 16.0)

    def test_a_degenerate_pattern_never_raises(self):
        self.assertEqual(tl.record_duration(100, 0, 0, 16), 1.0)


class TestPadKeyboard(unittest.TestCase):

    def test_pad_zero_is_the_root(self):
        # MIN, root C, octave 0 -> BASE_NOTE itself.
        self.assertEqual(tl.pad_note(0, 0, 0, 0), tl.BASE_NOTE)

    def test_pads_walk_up_the_scale(self):
        # MIN intervals are (0, 2, 3, 5, 7, 8, 10).
        got = [tl.pad_note(p, 0, 0, 0) for p in range(7)]
        self.assertEqual(got, [tl.BASE_NOTE + i for i in (0, 2, 3, 5, 7, 8, 10)])

    def test_the_scale_repeats_an_octave_up(self):
        self.assertEqual(tl.pad_note(7, 0, 0, 0), tl.pad_note(0, 0, 0, 0) + 12)

    def test_root_and_octave_transpose(self):
        self.assertEqual(tl.pad_note(0, 3, 0, 0), tl.BASE_NOTE + 3)
        self.assertEqual(tl.pad_note(0, 0, 0, 1), tl.BASE_NOTE + 12)

    def test_a_pentatonic_spans_more_octaves(self):
        # PENT is index 5, five notes: pad 5 is one octave up.
        self.assertEqual(tl.pad_note(5, 0, 5, 0), tl.pad_note(0, 0, 5, 0) + 12)

    def test_notes_are_clamped_into_midi_range(self):
        self.assertLessEqual(tl.pad_note(15, 11, 0, 2), 127)
        self.assertGreaterEqual(tl.pad_note(0, 0, 0, -2), 0)

    def test_pad_notes_gives_sixteen_ascending(self):
        notes = tl.pad_notes(0, 0, 0)
        self.assertEqual(len(notes), 16)
        self.assertEqual(list(notes), sorted(notes))


class TestCandidateNotes(unittest.TestCase):

    def test_a_drum_has_exactly_one_candidate(self):
        self.assertEqual(tl.candidate_notes("drum", 38), (38,))

    def test_a_voice_covers_its_keyboard_and_its_line(self):
        got = tl.candidate_notes("voice", 36, pads=(36, 38), line=(40, 38))
        self.assertEqual(got, (36, 38, 40))

    def test_the_voice_set_is_deduplicated_and_sorted(self):
        got = tl.candidate_notes("voice", 60, pads=(64, 60), line=(62, 64))
        self.assertEqual(got, (60, 62, 64))


class TestHandback(unittest.TestCase):

    def test_the_drum_content_knobs_hand_back(self):
        for verb in ("hits", "rotate", "div"):
            self.assertTrue(tl.hands_back("drum", verb))

    def test_drum_length_does_not_hand_back(self):
        # _set_length preserves the steps that fit, so it destroys nothing.
        self.assertFalse(tl.hands_back("drum", "length"))

    def test_the_voice_content_knobs_hand_back(self):
        for verb in ("length", "div"):
            self.assertTrue(tl.hands_back("voice", verb))

    def test_voice_length_is_the_register_not_the_bar_count(self):
        # Same verb name, opposite answer per kind - this is the whole reason
        # the rule is a table and not one list.
        self.assertTrue(tl.hands_back("voice", "length"))
        self.assertFalse(tl.hands_back("drum", "length"))

    def test_random_hands_back_only_when_it_moves_off_lock(self):
        self.assertTrue(tl.hands_back("voice", "random", 40))
        self.assertFalse(tl.hands_back("voice", "random", 0))

    def test_random_does_nothing_on_a_drum(self):
        self.assertFalse(tl.hands_back("drum", "random", 40))

    def test_an_unrelated_verb_never_hands_back(self):
        self.assertFalse(tl.hands_back("drum", "level"))
        self.assertFalse(tl.hands_back("voice", "gate"))


class TestOwnerLabel(unittest.TestCase):

    def test_a_generated_channel_shows_the_page_only(self):
        self.assertEqual(tl.owner_label("LEVEL 1/3", "gen", False, True),
                         "LEVEL 1/3")

    def test_a_player_owned_channel_says_so(self):
        self.assertEqual(tl.owner_label("LEVEL 1/3", "player", False, True),
                         "LEVEL 1/3 PLAY")

    def test_recording_wins_over_ownership(self):
        self.assertEqual(tl.owner_label("LEVEL 1/3", "player", True, True),
                         "LEVEL 1/3 REC")

    def test_rec_held_while_stopped_says_nothing_is_being_captured(self):
        self.assertEqual(tl.owner_label("LEVEL 1/3", "gen", True, False),
                         "LEVEL 1/3 REC-STOP")


class TestKitLine(unittest.TestCase):

    def test_every_step_lands_on_a_real_kit_note(self):
        kit = [36, 38, 42, 46]
        got = tl.kit_line(0b10110011, 8, 16, kit)
        self.assertEqual(len(got), 16)
        for note in got:
            self.assertIn(note, kit)

    def test_an_empty_kit_gives_an_empty_line(self):
        # The caller falls back to the channel's own note; the library does
        # not invent one.
        self.assertEqual(tl.kit_line(0b1011, 4, 8, []), [])

    def test_a_one_note_kit_repeats_that_note(self):
        self.assertEqual(tl.kit_line(0b1011, 4, 4, [38]), [38, 38, 38, 38])

    def test_the_walk_uses_the_whole_kit(self):
        # A register that rotates through many values must not sit on one
        # drum: that would be a dead channel wearing a generator's name.
        kit = [36, 38, 42, 46, 49]
        got = set(tl.kit_line(0b1011001110100101, 16, 32, kit))
        self.assertGreater(len(got), 1)

    def test_it_is_deterministic(self):
        kit = [36, 38, 42, 46]
        a = tl.kit_line(0b10110011, 8, 16, kit)
        b = tl.kit_line(0b10110011, 8, 16, kit)
        self.assertEqual(a, b)

    def test_the_same_register_walks_like_the_pitch_line(self):
        # kit_line and line are the same walk with a different mapping, so
        # equal register values must give equal positions.
        kit = [36, 38, 42, 46, 49, 51, 53]
        got = tl.kit_line(0b10110011, 8, 8, kit)
        rot = tl.rotations(0b10110011, 8, 8)
        for note, value in zip(got, rot):
            self.assertEqual(note, kit[(value * len(kit)) >> 8])


class TestKindResolution(unittest.TestCase):

    def test_no_override_uses_the_chain(self):
        self.assertEqual(tl.resolve_kind(None, "drum"), "drum")
        self.assertEqual(tl.resolve_kind(None, "voice"), "voice")

    def test_an_override_wins(self):
        self.assertEqual(tl.resolve_kind("voice", "drum"), "voice")
        self.assertEqual(tl.resolve_kind("drum", "voice"), "drum")

    def test_a_nonsense_override_is_ignored(self):
        # A snapshot written by another version must not be able to invent a
        # third kind.
        self.assertEqual(tl.resolve_kind("banjo", "drum"), "drum")

    def test_next_kind_is_a_two_state_toggle(self):
        self.assertEqual(tl.next_kind("drum"), "voice")
        self.assertEqual(tl.next_kind("voice"), "drum")


class TestTypeLabel(unittest.TestCase):

    def test_no_override_adds_nothing(self):
        self.assertEqual(tl.type_label("STEP 1/2", None), "STEP 1/2")

    def test_an_override_is_marked(self):
        self.assertEqual(tl.type_label("STEP 1/2", "voice"), "STEP 1/2 VOX")
        self.assertEqual(tl.type_label("STEP 1/2", "drum"), "STEP 1/2 DRM")

    def test_it_composes_with_the_ownership_label(self):
        # SP2's owner_label runs first; this appends after it.
        label = tl.owner_label("STEP 1/2", "player", False, True)
        self.assertEqual(tl.type_label(label, "voice"), "STEP 1/2 PLAY VOX")


class TestDefaultChannelState(unittest.TestCase):

    COMMON = ("level", "reverb", "delay", "swing", "velo", "chance", "pending")

    def test_both_kinds_carry_the_common_keys(self):
        for kind in ("drum", "voice"):
            st = tl.default_channel_state(kind)
            for key in self.COMMON:
                self.assertIn(key, st, f"{kind} is missing {key}")

    def test_a_drum_set_is_complete(self):
        st = tl.default_channel_state("drum")
        for key in ("kit", "sample"):
            self.assertIn(key, st)

    def test_a_voice_set_is_complete(self):
        # columns() indexes these directly, so a missing one is a KeyError on
        # the render path - the crash R2 exists to prevent.
        st = tl.default_channel_state("voice")
        for key in ("preset", "cutoff", "reso", "env", "decay", "random",
                    "gate", "octave", "range", "rhythm", "rhythm_reg", "length",
                    "register", "ring"):
            self.assertIn(key, st, f"voice is missing {key}")

    def test_pending_is_a_fresh_set_each_call(self):
        a = tl.default_channel_state("drum")
        b = tl.default_channel_state("drum")
        a["pending"].add("div")
        self.assertEqual(b["pending"], set())

    def test_the_ring_is_a_fresh_bounded_deque_each_call(self):
        a = tl.default_channel_state("voice")
        b = tl.default_channel_state("voice")
        a["ring"].append(1)
        self.assertEqual(len(b["ring"]), 0)
        self.assertEqual(a["ring"].maxlen, 4)

    def test_a_voice_starts_locked_with_every_step_sounding(self):
        st = tl.default_channel_state("voice")
        self.assertEqual(st["random"], 0)
        # Both generators start at LOCK, and the rhythm register starts
        # with every bit set - the same sound density=100 gave.
        self.assertEqual(st["rhythm"], 0)
        self.assertEqual(tl.rhythm_mask(st["rhythm_reg"], 16), tuple([True] * 16))

    def test_the_voice_register_keeps_the_shipped_seed(self):
        # The driver seeded this inline before SP4 moved the builder here.
        # Changing it would change what every voice plays on a cold start.
        self.assertEqual(tl.default_channel_state("voice")["register"],
                         0b10110011)


class TestDeadSynthColumns(unittest.TestCase):

    def _voice_state(self, has_synth_ctrl=None):
        st = tl.default_channel_state("voice")
        if has_synth_ctrl is not None:
            st["has_synth_ctrl"] = has_synth_ctrl
        return st

    @staticmethod
    def _control_page():
        return tl.PAGE_RINGS[("CONTROL", "voice")][0]

    def test_a_synth_draws_its_four_control_columns(self):
        cols = tl.columns(self._control_page(), "voice", self._voice_state(True))
        live = [c["name"].upper() for c in cols if not c["grey"]]
        for want in ("CUTOFF", "RESO", "ENV", "DECAY"):
            self.assertIn(want, live)

    def test_a_sampler_in_voice_mode_draws_them_dead(self):
        # Law L4: a column whose source does not exist draws dead rather than
        # drawing a lie. LinuxSampler publishes no filter controls at all.
        cols = tl.columns(self._control_page(), "voice", self._voice_state(False))
        for col in cols:
            if col["name"].upper() in ("CUTOFF", "RESO", "ENV", "DECAY"):
                self.assertTrue(col["grey"], f"{col['name']} should be dead")

    def test_a_missing_flag_is_treated_as_present(self):
        # Every caller before SP4 omits the key; omitting it must not grey a
        # working synth.
        cols = tl.columns(self._control_page(), "voice", self._voice_state())
        live = [c["name"].upper() for c in cols if not c["grey"]]
        self.assertIn("CUTOFF", live)

    def test_columns_die_one_at_a_time(self):
        # A swapped-in engine may publish a filter and no envelope amount.
        st = self._voice_state()
        st["synth_ctrl"] = (True, True, False, True)
        cols = {c["name"].upper(): c for c in
                tl.columns(self._control_page(), "voice", st)}
        self.assertFalse(cols["CUTOFF"]["grey"])
        self.assertFalse(cols["RESO"]["grey"])
        self.assertFalse(cols["DECAY"]["grey"])
        self.assertTrue(cols["ENV"]["grey"])

    def test_per_column_truth_beats_the_old_flag(self):
        st = self._voice_state(False)
        st["synth_ctrl"] = (True, True, True, True)
        cols = tl.columns(self._control_page(), "voice", st)
        live = [c["name"].upper() for c in cols if not c["grey"]]
        self.assertIn("CUTOFF", live)


class TestVoiceSymbolResolution(unittest.TestCase):
    """Page 1's four synth columns must follow the plugin that is loaded, not
    the engine named in the CHANNELS table."""

    # A synth the measured table has never seen.
    UNKNOWN = [
        ("lv2_freewheel", 0.0, 1.0),
        ("lfo1_freq", 0.0, 20.0),
        ("filter_cutoff", 20.0, 20000.0),
        ("filter_resonance", 0.0, 1.0),
        ("filter_env_amount", -1.0, 1.0),
        ("amp_decay", 0.0, 5.0),
    ]

    def test_the_measured_table_wins_over_any_guess(self):
        # Gate G2 measured these; a pattern match must never override them.
        self.assertEqual(tl.voice_symbols("JV/JC303", self.UNKNOWN),
                         ("_cutoff", "_resonance", "_envmod", "_decay"))

    def test_an_unknown_engine_is_resolved_from_its_own_ports(self):
        self.assertEqual(
            tl.voice_symbols("JV/MutatedInstrument", self.UNKNOWN),
            ("filter_cutoff", "filter_resonance", "filter_env_amount",
             "amp_decay"))

    def test_the_filter_column_never_lands_on_an_lfo(self):
        # 'freq' alone is not a cutoff. Only the LFO here publishes one.
        symbols = tl.discover_voice_symbols([("lfo1_freq", 0.0, 20.0),
                                             ("lfo1_depth", 0.0, 1.0)])
        self.assertEqual(symbols, (None, None, None, None))

    def test_a_role_never_steals_a_symbol_an_earlier_role_took(self):
        ports = [("cutoff", 0.0, 1.0), ("filterenv_decay", 0.0, 1.0)]
        cut, reso, env, decay = tl.discover_voice_symbols(ports)
        self.assertEqual(cut, "cutoff")
        self.assertIsNone(reso)
        self.assertEqual(env, "filterenv_decay")
        self.assertIsNone(decay)

    def test_host_ports_are_never_offered_to_a_role(self):
        # PORT_DENY drops these before matching, as it does on generated pages.
        symbols = tl.discover_voice_symbols([("lv2_freewheel", 0.0, 1.0),
                                             ("enabled", 0.0, 1.0),
                                             ("vcf_freq", 20.0, 20000.0)])
        self.assertEqual(symbols[0], "vcf_freq")

    def test_a_port_with_no_range_is_not_offered_to_a_role(self):
        symbols = tl.discover_voice_symbols([("cutoff", None, None),
                                             ("dcf_freq", 20.0, 20000.0)])
        self.assertEqual(symbols[0], "dcf_freq")

    def test_a_sampler_publishes_nothing_and_stays_dead(self):
        # LinuxSampler's _ctrls is empty - the SP4 case, unchanged.
        self.assertEqual(tl.voice_symbols("LS/LinuxSampler", []),
                         (None, None, None, None))

    def test_flags_follow_the_resolved_symbols(self):
        symbols = tl.voice_symbols("JV/Unknown", [("cutoff", 0.0, 1.0)])
        flags = tl.synth_ctrl_flags({"synth_ctrl": [bool(s) for s in symbols]})
        self.assertEqual(flags, (True, False, False, False))


class TestButtonTables(unittest.TestCase):

    def test_no_cc_is_claimed_twice(self):
        self.assertEqual(tl.button_conflicts(), [])

    def test_stateful_and_press_are_disjoint(self):
        both = set(tl.BUTTONS_STATEFUL) & set(tl.BUTTONS_PRESS)
        self.assertEqual(both, set())

    def test_measured_bindings_are_preserved(self):
        # The shipped chain, transcribed. A change here is a surface change.
        self.assertEqual(tl.BUTTONS_STATEFUL[2], "erase")
        self.assertEqual(tl.BUTTONS_STATEFUL[3], "rec")
        self.assertEqual(tl.BUTTONS_STATEFUL[49], "shift")
        self.assertEqual(tl.BUTTONS_STATEFUL[31], "solo")
        self.assertEqual(tl.BUTTONS_STATEFUL[35], "coarse")
        self.assertEqual(tl.BUTTONS_PRESS[1], "play")
        self.assertEqual(tl.BUTTONS_PRESS[4], "grid")
        self.assertEqual(tl.BUTTONS_PRESS[7], "restart")
        self.assertEqual(tl.BUTTONS_PRESS[10], "register_undo")
        self.assertEqual(tl.BUTTONS_PRESS[47], "page_prev")
        self.assertEqual(tl.BUTTONS_PRESS[48], "page_next")
        self.assertEqual(tl.BUTTONS_PRESS[13], "sound_prev")
        self.assertEqual(tl.BUTTONS_PRESS[14], "sound_next")

    def test_no_button_lands_on_an_encoder_or_a_group_or_an_f_button(self):
        for cc in list(tl.BUTTONS_STATEFUL) + list(tl.BUTTONS_PRESS):
            self.assertNotIn(cc, range(16, 24), f"CC {cc} is an encoder")
            self.assertNotIn(cc, range(39, 47), f"CC {cc} is an F button")
            self.assertNotIn(cc, range(80, 88), f"CC {cc} is a Group button")

    def test_every_bound_cc_has_a_provenance(self):
        # WORKING RULE 7, mechanically. Every CC this instrument binds must be
        # one somebody actually measured, or one verified by daily use. A CC
        # that is in neither set is UNKNOWN, and binding it is the mistake this
        # test exists to make impossible.
        #
        # This replaced test_the_free_ccs_stay_free on 2026-08-21. That test
        # asserted three numbers were unbound and called itself a statement
        # about the surface; it was a list of buttons somebody happened to
        # press. TEMPO is the proof: CC 35, absent from the entire G4 capture
        # because nobody pressed TEMPO that day, so it was UNKNOWN rather than
        # free - and nothing in the tests or the driver said so.
        bound = set(tl.BUTTONS_STATEFUL) | set(tl.BUTTONS_PRESS)
        unknown = sorted(bound - tl.CCS_KNOWN)
        self.assertEqual(
            unknown, [],
            f"CC(s) {unknown} are bound but appear in no capture log and are "
            f"not verified by use. An unlisted CC is UNKNOWN, not free - "
            f"capture it before binding it.")

    def test_the_measured_sets_match_the_capture_logs(self):
        # The G4 capture contains exactly 24 distinct controller numbers. If
        # this count ever moves, somebody edited the set by hand rather than
        # from the log, which is how a guess becomes a fact in this project.
        self.assertEqual(len(tl.CCS_MEASURED_G4), 24)
        # G5 is REC plus the eight encoders.
        self.assertEqual(sorted(tl.CCS_MEASURED_G5), [3] + list(range(16, 24)))
        # The later single-button captures: NOTE REPEAT and TEMPO, then
        # BROWSE, SAMPLING and ENTER measured at the rig on 2026-09-01 with
        # the owner pressing them one at a time in a stated order.
        self.assertEqual(sorted(tl.CCS_MEASURED_SINGLE), [8, 9, 10, 35, 36])
        # TEMPO is the whole reason this file has provenance sets: measured,
        # but NOT by G4.
        self.assertIn(35, tl.CCS_MEASURED)
        self.assertNotIn(35, tl.CCS_MEASURED_G4)
        # The three sets must not overlap, or a number's provenance is ambiguous.
        self.assertEqual(tl.CCS_MEASURED_G4 & tl.CCS_MEASURED_G5, frozenset())
        self.assertEqual(tl.CCS_MEASURED_G4 & tl.CCS_MEASURED_SINGLE, frozenset())
        self.assertEqual(tl.CCS_MEASURED_G5 & tl.CCS_MEASURED_SINGLE, frozenset())
        # Verified-by-use is a DIFFERENT kind of evidence and must stay separate,
        # so that "it is in a capture log" is never confused with "it is verified".
        self.assertEqual(tl.CCS_MEASURED & tl.CCS_VERIFIED_BY_USE, frozenset())

    def test_the_whole_panel_was_captured_2026_09_04(self):
        # THE ROUND todo item 15 OWED SINCE 2026-08-21. Every physical button
        # pressed one at a time with the owner at the rig, both edges, read off
        # the daemon's ALSA output port. Forty-eight buttons and every one
        # matched the tables - so this test is the record of that, and it turns
        # red if anybody edits a CC without a fresh capture.
        self.assertEqual(len(tl.CCS_MEASURED_PANEL), 48)
        # Every bound CC is now a measured one. This is the assertion the
        # provenance machinery existed to make possible.
        for cc in set(tl.BUTTONS_STATEFUL) | set(tl.BUTTONS_PRESS):
            self.assertIn(cc, tl.CCS_MEASURED_PANEL,
                          f"CC {cc} is bound but was not in the panel round")
        # The big encoder's PRESS is CC 12 and it is HOME. The daemon emits it
        # from its "nav" token (main.rs:1103), which is why blinking `nav` lit
        # nothing: the big encoder has no LED at all.
        self.assertEqual(tl.BUTTONS_PRESS[12], "home")
        self.assertIn(12, tl.CCS_MEASURED_PANEL)
        # CC 28 is emitted by the daemon's `view` token, and NO button on this
        # panel is wired to it - blinked and named by nobody. Measured as
        # unemitted is a stronger statement than unknown, and it must not be
        # confused with a button nobody happened to press.
        self.assertEqual(tl.CCS_MEASURED_UNEMITTED, frozenset({28}))
        self.assertNotIn(28, tl.CCS_MEASURED_PANEL)
        self.assertNotIn(28, tl.BUTTONS_STATEFUL)
        self.assertNotIn(28, tl.BUTTONS_PRESS)
        # Verified-by-use is empty now: the round measured everything that had
        # only been inferred. The set stays so a future uncaptured binding has
        # somewhere honest to sit.
        self.assertEqual(tl.CCS_VERIFIED_BY_USE, frozenset())

    def test_the_unclaimed_ccs_are_measured_and_really_unclaimed(self):
        # The only numbers a new feature may take without a fresh capture.
        for cc in tl.CCS_MEASURED_AND_UNCLAIMED:
            self.assertIn(cc, tl.CCS_MEASURED,
                          f"CC {cc} is offered as available but was never measured")
            self.assertNotIn(cc, tl.BUTTONS_STATEFUL,
                             f"CC {cc} is offered as available but is bound")
            self.assertNotIn(cc, tl.BUTTONS_PRESS,
                             f"CC {cc} is offered as available but is bound")
        # 27, 30, 33 and 34 were unclaimed and are now spent - FREEZE, ARM, the
        # mute grid and the NAVIGATE phrase page. They must not drift back onto
        # the offer list.
        for cc in (27, 30, 33, 34):
            self.assertNotIn(cc, tl.CCS_MEASURED_AND_UNCLAIMED,
                             f"CC {cc} is spent and must not be offered again")

    def test_the_reroll_button_fires_on_a_press(self):
        # PRESS-ONLY since 2026-09-01. They were stateful and fired on a
        # release past 250 ms - the fifth grammar for "do a thing" on a panel
        # that already had four, and the only one of its kind here. The
        # comment that justified it called hold-to-fire "already this
        # instrument's law"; nothing else on the surface did it.
        #
        # The window the hold bought is now the BAR: the reroll lands at the
        # wrap and a second press before then takes it back, which is longer
        # than a finger could hold and is the same second-press-cancels the
        # bank grid and the mute queue already use.
        self.assertEqual(tl.BUTTONS_PRESS[26], "reroll")
        self.assertNotIn(26, tl.BUTTONS_STATEFUL)

    def test_one_button_regenerates_and_scene_is_free(self):
        # ONE BUTTON, both kinds, 2026-09-01. A bare press already ignored
        # which of the two you pressed - reroll_scope takes the selected
        # channel either way - so the pair differed in exactly one situation,
        # SHIFT. The selected channel names its own engine type now.
        self.assertNotIn(25, tl.BUTTONS_PRESS)
        self.assertNotIn(25, tl.BUTTONS_STATEFUL)
        self.assertIn(25, tl.CCS_MEASURED_AND_UNCLAIMED)
        self.assertIn(25, tl.CCS_MEASURED)

    def test_coarse_lives_on_tempo_and_carries_both_edges(self):
        # TEMPO = CC 35, MEASURED 2026-08-16 by aseqdump on the daemon's Pads
        # port: 127 on press, 0 on release. The daemon's token name said 35
        # too, but this project has been wrong twice reading a CC off a token
        # name (DL/DR, and the whole LED index table), so it was captured.
        # Both edges matter: COARSE is held, so the release IS an event,
        # which is why it sits in BUTTONS_STATEFUL and not BUTTONS_PRESS.
        self.assertEqual(tl.BUTTONS_STATEFUL[35], "coarse")
        self.assertNotIn(35, tl.BUTTONS_PRESS)

    def test_coarse_did_not_land_on_select(self):
        # SELECT (CC 30) was the design's first home for COARSE and the owner
        # moved it to TEMPO. The guard survives the move that spent SELECT on
        # ARM: what it exists to catch is COARSE drifting back onto SELECT, so
        # it now asserts the OWNER of CC 30 rather than that CC 30 is empty.
        self.assertEqual(tl.BUTTONS_STATEFUL[30], "arm")
        self.assertNotIn(30, tl.BUTTONS_PRESS)
        self.assertEqual(tl.BUTTONS_STATEFUL[35], "coarse")

    def test_mod_lives_on_swing_not_auto(self):
        self.assertEqual(tl.BUTTONS_STATEFUL[50], "mod")
        # AUTO is CC_MODE_FILTER. Binding MOD there would shadow a mode.
        self.assertNotIn(37, tl.BUTTONS_STATEFUL)
        self.assertNotIn(37, tl.BUTTONS_PRESS)


class TestModulatorMaths(unittest.TestCase):

    def test_timbre_verbs_are_allowed(self):
        for verb in ("level", "reverb", "delay", "cutoff", "reso",
                     "env", "decay"):
            self.assertTrue(tl.mod_allowed(verb), verb)

    def test_gate_and_velo_are_refused(self):
        # They read as timbre and were allowed once. Both are written by
        # regenerating the WHOLE pattern (_apply_generator/_write_pattern: a
        # clear() plus an addNote loop), so an LFO on either fired a full
        # pattern rewrite every 200 ms forever - and on a player-owned DRUM
        # channel the generator's drum branch has no ownership check, so it
        # destroyed the recorded take over and over with nobody touching the
        # panel.
        for verb in ("gate", "velo"):
            self.assertFalse(tl.mod_allowed(verb), verb)

    def test_no_allowed_verb_rewrites_a_pattern(self):
        # The set's whole contract in one assertion: everything in MOD_TIMBRE
        # lands on a mixer strip or a plugin port. If a verb is added here it
        # must be checked against _apply_generator/_write_pattern first.
        rewrites = {"hits", "rotate", "div", "length", "rhythm", "chance",
                    "gate", "velo", "octave", "range", "random", "root",
                    "scale", "kit", "preset", "sample"}
        self.assertEqual(tl.MOD_TIMBRE & rewrites, frozenset())

    def test_generated_plugin_ports_are_allowed(self):
        self.assertTrue(tl.mod_allowed("lv2:surge_xt_a_filter1_cutoff"))
        self.assertTrue(tl.mod_allowed("fx:reverb:decay"))

    def test_structure_verbs_are_refused(self):
        # These rewrite the pattern. An LFO on one of them thrashes zynseq.
        for verb in ("div", "length", "kit", "preset", "sample",
                     "root", "scale", "octave", "range"):
            self.assertFalse(tl.mod_allowed(verb), verb)

    def test_generation_verbs_now_depend_on_OWNERSHIP(self):
        # CHANGED 2026-08-19: drift shipped. These used to be refused
        # unconditionally because drift was deferred and blocked on the
        # SP2-ownership rule; the owner confirmed that rule, so they are
        # bindable on an UNOWNED channel and refused on an owned one.
        for verb in ("hits", "rotate", "chance"):
            self.assertTrue(tl.mod_allowed(verb, owned=False), verb)
            self.assertFalse(tl.mod_allowed(verb, owned=True), verb)
        # RHYTHM is still refused outright: it is a voice's evolve knob, not a
        # pattern verb drift targets, and it is not in DRIFT_VERBS.
        self.assertFalse(tl.mod_allowed("rhythm"))

    def test_none_is_refused(self):
        self.assertFalse(tl.mod_allowed(None))

    def test_no_modulatable_verb_hands_the_pattern_back(self):
        # A modulated verb is steered at its base and never reaches the
        # handback check, so nothing in this set may be a handback verb.
        for kind in tl.KINDS:
            for verb in tl.MOD_TIMBRE:
                self.assertFalse(tl.hands_back(kind, verb, 100), (kind, verb))

    def test_fx_verbs_are_global_and_lv2_verbs_are_not(self):
        # An fx: insert is ganged across every channel, so its modulator must
        # be keyed with no channel: keyed per group it went invisible the
        # moment the selected group changed, and a second modulator could be
        # bound to the same port.
        self.assertTrue(tl.mod_is_global("fx:reverb:decay"))
        self.assertFalse(tl.mod_is_global("lv2:surge_xt_a_filter1_cutoff"))
        self.assertFalse(tl.mod_is_global("cutoff"))
        self.assertFalse(tl.mod_is_global(None))

    def test_phase_advances_one_cycle_per_rate_in_bars(self):
        # 2 bars per cycle, 8 beats elapsed at 4 beats to the bar = one cycle.
        self.assertAlmostEqual(tl.mod_pos(0.0, 8.0, 2.0), 1.0)
        self.assertAlmostEqual(tl.mod_pos(0.25, 8.0, 2.0), 1.25)

    def test_triangle_runs_from_minus_one_up_and_back(self):
        self.assertAlmostEqual(tl.mod_wave("tri", 0.0), -1.0)
        self.assertAlmostEqual(tl.mod_wave("tri", 0.25), 0.0)
        self.assertAlmostEqual(tl.mod_wave("tri", 0.5), 1.0)
        self.assertAlmostEqual(tl.mod_wave("tri", 0.75), 0.0)

    def test_ramp_and_square(self):
        self.assertAlmostEqual(tl.mod_wave("ramp", 0.0), -1.0)
        self.assertAlmostEqual(tl.mod_wave("ramp", 0.5), 0.0)
        self.assertAlmostEqual(tl.mod_wave("squ", 0.25), 1.0)
        self.assertAlmostEqual(tl.mod_wave("squ", 0.75), -1.0)

    def test_every_shape_stays_inside_minus_one_to_one(self):
        for shape in tl.MOD_SHAPES:
            for i in range(0, 400):
                v = tl.mod_wave(shape, i / 97.0, seed=7)
                self.assertGreaterEqual(v, -1.0)
                self.assertLessEqual(v, 1.0)

    def test_sample_and_hold_is_deterministic_and_holds(self):
        # Same (seed, cycle) always gives the same value, so a saved jam
        # reloads sounding identical. Within a cycle it does not move.
        a = tl.mod_wave("s&h", 3.1, seed=42)
        b = tl.mod_wave("s&h", 3.9, seed=42)
        self.assertEqual(a, b)
        self.assertEqual(a, tl.mod_wave("s&h", 3.5, seed=42))
        self.assertNotEqual(a, tl.mod_wave("s&h", 4.1, seed=42))

    def test_depth_zero_never_moves_the_value(self):
        for wave in (-1.0, -0.3, 0.0, 0.6, 1.0):
            self.assertEqual(tl.mod_value(64, wave, 0, 0, 127), 64)

    def test_full_depth_sweeps_half_the_range_each_way(self):
        # depth is -100..100 percent. At 100 the offset is half the span.
        self.assertAlmostEqual(
            tl.mod_value(64, 1.0, 100, 0, 127), 127.0)
        self.assertAlmostEqual(
            tl.mod_value(64, -1.0, 100, 0, 127), 0.5)

    def test_value_is_clamped_to_the_verbs_own_range(self):
        self.assertEqual(tl.mod_value(120, 1.0, 100, 0, 127), 127)
        self.assertEqual(tl.mod_value(4, -1.0, 100, 0, 127), 0)

    def test_negative_depth_mirrors_positive(self):
        up = tl.mod_value(64, 0.5, 50, 0, 127)
        down = tl.mod_value(64, 0.5, -50, 0, 127)
        self.assertAlmostEqual(up - 64, 64 - down)

    def test_span_is_the_range_the_bar_should_draw_dashed(self):
        lo, hi = tl.mod_span(64, 50, 0, 127)
        self.assertAlmostEqual(lo, (64 - 31.75) / 127.0)
        self.assertAlmostEqual(hi, (64 + 31.75) / 127.0)

    def test_span_clamps_at_the_ends_rather_than_running_off(self):
        lo, hi = tl.mod_span(0, 100, 0, 127)
        self.assertAlmostEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.5)

    def test_span_of_zero_depth_is_a_point(self):
        lo, hi = tl.mod_span(64, 0, 0, 127)
        self.assertAlmostEqual(lo, hi)

    def test_twelve_rates_and_four_shapes_fill_the_sixteen_pads(self):
        # Every table entry must be reachable from a pad. A table with more
        # entries than pads is a table that lies about what the surface can do.
        self.assertEqual(len(tl.MOD_RATES), 12)
        self.assertEqual(len(tl.MOD_SHAPES), 4)
        self.assertEqual(
            len(tl.MOD_RATES) + len(tl.MOD_SHAPES), 16)

    def test_rates_run_slowest_first_and_are_all_positive(self):
        self.assertEqual(sorted(tl.MOD_RATES, reverse=True),
                         list(tl.MOD_RATES))
        for rate in tl.MOD_RATES:
            self.assertGreater(rate, 0.0)

    def test_one_bar_is_in_the_rate_table(self):
        # The default rate at bind. Absent, the driver would index a rate that
        # does not exist.
        self.assertIn(1.0, tl.MOD_RATES)


class TestModulationMarks(unittest.TestCase):

    def test_a_modulated_column_gets_a_tilde_on_its_name(self):
        col = tl.mark_modulated(tl._col("CUTOFF", "0064", "uni", 0.5),
                                (0.25, 0.75))
        self.assertTrue(col["name"].endswith("~"))
        self.assertEqual(col["mod"], (0.25, 0.75))

    def test_an_unmodulated_column_is_unchanged(self):
        col = tl._col("CUTOFF", "0064", "uni", 0.5)
        self.assertEqual(col["name"], "CUTOFF")
        self.assertIsNone(col["mod"])

    def test_the_tilde_does_not_push_the_name_past_the_cell(self):
        col = tl.mark_modulated(tl._col("LFO1_ENAB", "0064", "uni", 0.5),
                                (0.0, 1.0))
        self.assertLessEqual(len(col["name"]), tl.NAME_CHARS)
        self.assertTrue(col["name"].endswith("~"))

    def test_the_value_cell_still_shows_the_base(self):
        # Not the modulated value: the base is the thing the knob steers.
        col = tl.mark_modulated(tl._col("CUTOFF", "0064", "uni", 0.5),
                                (0.1, 0.9))
        self.assertEqual(col["value"], "0064")

    def test_a_dead_column_carries_no_modulation(self):
        self.assertIsNone(tl._dead("CUTOFF")["mod"])

    def test_marking_adds_the_span_and_the_tilde(self):
        col = tl._col("CUTOFF", "0064", "uni", 0.5)
        out = tl.mark_modulated(col, (0.25, 0.75))
        self.assertEqual(out["mod"], (0.25, 0.75))
        self.assertTrue(out["name"].endswith("~"))

    def test_marking_with_no_span_returns_the_column_untouched(self):
        col = tl._col("CUTOFF", "0064", "uni", 0.5)
        self.assertIs(tl.mark_modulated(col, None), col)

    def test_a_dead_column_refuses_the_mark(self):
        dead = tl._dead("CUTOFF")
        self.assertIs(tl.mark_modulated(dead, (0.1, 0.9)), dead)

    def test_marking_does_not_mutate_the_original(self):
        col = tl._col("CUTOFF", "0064", "uni", 0.5)
        tl.mark_modulated(col, (0.25, 0.75))
        self.assertIsNone(col["mod"])
        self.assertEqual(col["name"], "CUTOFF")


class TestModBaseOr(unittest.TestCase):
    """The view-substitution rule state_view() and _generated_view() both
    call through _mod_override(): a modulated verb's display must read the
    base the knob is set to, never the value _mod_write() just swept it to.
    Exercised here directly, not just through _col(), so a regression on the
    substitution itself - as opposed to the tilde/span cosmetics - fails a
    test rather than only showing up on hardware."""

    def test_value_passes_through_when_nothing_is_bound(self):
        self.assertEqual(tl.mod_base_or({}, (0, "cutoff"), 42), 42)

    def test_a_bound_key_reports_its_base_not_the_passed_value(self):
        mods = {(0, "cutoff"): {"base": 64, "depth": 50}}
        # 99 stands in for whatever the swept/live value currently is - it
        # must never come back out.
        self.assertEqual(tl.mod_base_or(mods, (0, "cutoff"), 99), 64)

    def test_only_the_exact_key_is_overridden(self):
        mods = {(0, "cutoff"): {"base": 64}}
        self.assertEqual(tl.mod_base_or(mods, (1, "cutoff"), 99), 99)
        self.assertEqual(tl.mod_base_or(mods, (0, "reso"), 99), 99)


class TestModSteer(unittest.TestCase):
    """A hand turn on a modulated verb steers the BASE, not the engine.

    Written as the whole loop rather than one helper in isolation: the defect
    this guards against was invisible to a helper test, because every piece
    was correct on its own and only the wiring - reading `current` back out of
    the store _mod_write() had just swept - was wrong."""

    KEY = (0, "cutoff")
    LO, HI = 0, 127

    def _mods(self, base=64, depth=50):
        return {self.KEY: {"base": base, "depth": depth, "rate": 6,
                           "shape": "tri", "phase0": 0.0, "seed": 1}}

    def _tick(self, mods, beats):
        """One _mod_write() tick: what the engine is given, in surface units."""
        e = mods[self.KEY]
        pos = tl.mod_pos(e["phase0"], beats, tl.MOD_RATES[e["rate"]])
        wave = tl.mod_wave(e["shape"], pos, e["seed"])
        return tl.mod_value(e["base"], wave, e["depth"], self.LO, self.HI)

    def test_an_unmodulated_verb_still_goes_to_the_engine(self):
        value, to_base = tl.mod_steer({}, self.KEY, 40, 5, self.LO, self.HI)
        self.assertEqual(value, 45)
        self.assertFalse(to_base)

    def test_a_modulated_verb_steers_the_base_and_writes_nothing(self):
        mods = self._mods(base=64)
        value, to_base = tl.mod_steer(mods, self.KEY, None, 5, self.LO, self.HI)
        self.assertEqual(value, 69)
        self.assertTrue(to_base)

    def test_the_swept_value_can_never_become_the_starting_point(self):
        # THE DEFECT. _mod_write stores base+offset into the driver's own
        # parameter store, and the encoder path used to read it straight back
        # as `current`. Even handed that swept number, the turn must start
        # from the base.
        mods = self._mods(base=64)
        swept = self._tick(mods, beats=1.7)
        self.assertNotEqual(swept, 64)          # the LFO really has moved it
        value, _ = tl.mod_steer(mods, self.KEY, swept, 5, self.LO, self.HI)
        self.assertEqual(value, 69)

    def test_the_knob_walks_and_the_lfo_never_walks_it_back(self):
        # Turn, tick, turn, tick. Ten detents up must be ten detents up,
        # whatever the modulator did in between - the shipped bug made every
        # turn start from wherever the sweep was, so the base wandered.
        mods = self._mods(base=64)
        beats = 0.0
        for _ in range(10):
            value, to_base = tl.mod_steer(mods, self.KEY, self._tick(mods, beats),
                                          1, self.LO, self.HI)
            self.assertTrue(to_base)
            mods[self.KEY]["base"] = value
            beats += 0.37                       # a tick lands between turns
        self.assertEqual(mods[self.KEY]["base"], 74)

    def test_ticking_on_its_own_never_moves_the_base(self):
        mods = self._mods(base=64)
        for i in range(50):
            self._tick(mods, beats=i * 0.21)
        self.assertEqual(mods[self.KEY]["base"], 64)

    def test_the_display_follows_the_knob_not_the_sweep(self):
        # mod_base_or is what state_view()/_generated_view() substitute with.
        mods = self._mods(base=64)
        value, _ = tl.mod_steer(mods, self.KEY, None, 5, self.LO, self.HI)
        mods[self.KEY]["base"] = value
        swept = self._tick(mods, beats=1.7)
        self.assertEqual(tl.mod_base_or(mods, self.KEY, swept), 69)

    def test_the_base_is_clamped_to_the_verbs_own_range(self):
        mods = self._mods(base=125)
        self.assertEqual(
            tl.mod_steer(mods, self.KEY, None, 20, self.LO, self.HI)[0], 127)
        mods = self._mods(base=3)
        self.assertEqual(
            tl.mod_steer(mods, self.KEY, None, -20, self.LO, self.HI)[0], 0)

    def test_no_readable_source_steers_nothing(self):
        value, to_base = tl.mod_steer({}, self.KEY, None, 5, self.LO, self.HI)
        self.assertIsNone(value)
        self.assertFalse(to_base)


class TestModLabel(unittest.TestCase):

    def test_mod_is_named_on_the_page_indicator(self):
        self.assertEqual(tl.mod_label("CUTOFF 1/2", True), "CUTOFF 1/2 MOD")

    def test_nothing_is_added_when_mod_is_off(self):
        self.assertEqual(tl.mod_label("CUTOFF 1/2", False), "CUTOFF 1/2")


class TestShortLabel(unittest.TestCase):
    """Truncation that keeps what tells two presets apart.

    Group H's bank is 67 padthv1 patches and 48 of them shared a 4-character
    label with an alphabetical neighbour - Dusk, Dusk2 ... Dusk6 all drew as
    "Dusk". Stepping walks the list alphabetically, so the player pressed the
    button six times, saw one word and heard six variants of one pad, and
    reported the button as broken. Measured on the rig 2026-08-16."""

    def test_short_names_are_untouched(self):
        self.assertEqual(tl.short_label("Dusk", 9), "Dusk")
        self.assertEqual(tl.short_label("Castle", 9), "Castle")

    def test_a_name_exactly_at_the_budget_is_untouched(self):
        self.assertEqual(tl.short_label("Kawai R50", 9), "Kawai R50")

    def test_trailing_digits_survive_truncation(self):
        # The whole point: the digit is the only thing that differs.
        self.assertEqual(tl.short_label("GettinRezd2", 9), "GettinRe2")
        self.assertEqual(tl.short_label("GettinRezd3", 9), "GettinRe3")
        self.assertEqual(tl.short_label("OrganSpecial2", 9), "OrganSpe2")

    def test_a_bare_name_still_truncates_plainly(self):
        self.assertEqual(tl.short_label("GlassyChorused", 9), "GlassyCho")

    def test_the_whole_bank_gets_distinct_labels(self):
        # The regression this exists to prevent. These are the real names,
        # read off the rig; every 4-character collision must be gone.
        names = ["Dusk", "Dusk2", "Dusk3", "Dusk4", "Dusk5", "Dusk6",
                 "GettinRezd", "GettinRezd2", "GettinRezd3",
                 "GlassyChorused", "GlassyChorused2",
                 "OrganSpecial", "OrganSpecial2", "OrganSpecial3",
                 "PdKey1", "PdKey2", "PdKey3", "PdKey4", "PdKey05",
                 "Moteef1", "Moteef2", "Moteef3", "Moteef4", "Moteef1Mod"]
        labels = [tl.short_label(n, 9) for n in names]
        self.assertEqual(len(set(labels)), len(labels), sorted(labels))

    def test_never_exceeds_the_budget(self):
        for name in ("x", "SpaceLandings01", "ChristmasCheer", "Randomize02"):
            self.assertLessEqual(len(tl.short_label(name, 9)), 9, name)

    def test_empty_and_none_are_safe(self):
        self.assertEqual(tl.short_label("", 9), "")
        self.assertEqual(tl.short_label(None, 9), "")

    def test_a_digit_run_longer_than_the_budget_cannot_eat_the_name(self):
        # Degenerate, but it must not return only digits or an empty string.
        out = tl.short_label("A123456789012", 9)
        self.assertEqual(len(out), 9)
        self.assertTrue(out.startswith("A"))


class TestNameColumnsDrawSmall(unittest.TestCase):
    """PRESET, KIT and SAMPLE carry names, not numbers, so they draw in the
    small font and get the wider budget. Every other column keeps the
    double-height value that reads at a glance while playing."""

    def _cols(self, kind, state):
        # The real descriptor, not a stub with eight empty slots. Since
        # 2026-09-01 a page IS its verbs tuple, so a stub with no verbs draws
        # eight dead columns - which is correct, and useless as a test of what
        # the shipped CONTROL page does.
        desc = tl.PAGE_RINGS[("CONTROL", kind)][0]
        return tl.columns(desc, kind, state)

    def test_preset_column_is_small_and_shortened(self):
        state = dict(_voice_state(), preset="GettinRezd2")
        col = self._cols("voice", state)[0]
        self.assertEqual(col["name"], "PRESET")
        self.assertTrue(col["small"])
        self.assertEqual(col["value"], "GettinRe2")

    def test_kit_and_sample_columns_are_small(self):
        state = dict(_drum_state(), kit="Roland TR909", sample="ClosedHat2")
        cols = self._cols("drum", state)
        self.assertTrue(cols[0]["small"])
        self.assertTrue(cols[1]["small"])

    def test_numeric_columns_are_not_small(self):
        state = _voice_state()
        for col in self._cols("voice", state)[5:]:
            self.assertFalse(col["small"], col["name"])

    def test_pending_brackets_fit_inside_the_budget(self):
        # ">value<" costs two characters. Shortening after wrapping would
        # either overflow the column or cut the closing bracket off.
        state = dict(_voice_state(), preset="GettinRezd2",
                     pending={"preset"})
        col = self._cols("voice", state)[0]
        self.assertLessEqual(len(col["value"]), 9)
        self.assertTrue(col["value"].startswith(">"))
        self.assertTrue(col["value"].endswith("<"))
        self.assertIn("2", col["value"])


class TestModAwareGreying(unittest.TestCase):
    """While MOD is down, a column that cannot take a modulator loses its BAR.

    Before this, MOD + encoder on a refused verb did nothing and said nothing:
    _mod_encoder's docstring claimed a refused verb draws dead, and only the
    "does nothing" half was implemented. Under MOD the HITS column looked
    exactly like the LEVEL column and one of them worked, which is why binding
    "sometimes works and sometimes does not".

    The value stays - it is still a live parameter, it just cannot be
    modulated - so under MOD the rule is: a bar means you can bind here."""

    CTRL = {"title": "CTRL", "shape": tl.SHAPE_CHANNEL,
            "verbs": ("preset", "cutoff", "reso", "env", "decay",
                      "level", "reverb", "delay")}
    STEP = {"title": "STEP", "shape": tl.SHAPE_CHANNEL,
            "verbs": ("hits", "rotate", "div", "length", "velo", "chance",
                      "swing", None)}

    def test_without_mod_nothing_changes(self):
        state = _voice_state()
        plain = tl.columns(self.CTRL, "voice", state)
        again = tl.columns(self.CTRL, "voice", state, mod=False)
        self.assertEqual(plain, again)

    def test_a_modulatable_verb_keeps_its_bar(self):
        state = _voice_state()
        cols = tl.columns(self.CTRL, "voice", state, mod=True)
        for i, verb in enumerate(self.CTRL["verbs"]):
            if verb in ("cutoff", "reso", "env", "decay", "level",
                        "reverb", "delay"):
                self.assertIsNotNone(cols[i]["bar"], verb)
                self.assertFalse(cols[i]["grey"], verb)

    def test_a_refused_verb_loses_its_bar_but_keeps_its_value(self):
        state = _voice_state()
        plain = tl.columns(self.CTRL, "voice", state)
        cols = tl.columns(self.CTRL, "voice", state, mod=True)
        # PRESET is not modulatable - it rewrites what the engine is playing.
        self.assertIsNone(cols[0]["bar"])
        self.assertTrue(cols[0]["grey"])
        self.assertEqual(cols[0]["value"], plain[0]["value"])
        self.assertEqual(cols[0]["name"], plain[0]["name"])

    def test_the_pattern_verbs_are_refused_ON_AN_OWNED_CHANNEL(self):
        # CHANGED 2026-08-19: drift shipped, so HITS/ROTATE/CHANCE are bindable
        # on an unowned channel. They stay refused on an owned one, which is
        # the whole rule - rewriting a pattern with no hands on the panel is
        # how a recorded take gets erased, exactly as the velo defect did.
        state = _drum_step_state()
        cols = tl.columns(self.STEP, "drum", state, mod=True, owned=True)
        for i, verb in enumerate(self.STEP["verbs"]):
            if verb in ("hits", "rotate", "chance", "velo"):
                self.assertIsNone(cols[i]["bar"], verb)
                self.assertTrue(cols[i]["grey"], verb)

    def test_the_pattern_verbs_are_offered_on_an_unowned_channel(self):
        state = _drum_step_state()
        cols = tl.columns(self.STEP, "drum", state, mod=True, owned=False)
        for i, verb in enumerate(self.STEP["verbs"]):
            if verb in ("hits", "rotate", "chance"):
                self.assertFalse(cols[i]["grey"], verb)
            if verb == "velo":
                # VELO stays refused whatever the ownership: it is written by
                # regenerating the whole pattern and is not a drift target.
                self.assertTrue(cols[i]["grey"], verb)

    def test_an_already_dead_column_is_left_alone(self):
        # A column with no source at all keeps the ---- vocabulary; MOD must
        # not invent a second look for it.
        state = dict(_voice_state(), synth_ctrl=(False, False, False, False))
        cols = tl.columns(self.CTRL, "voice", state, mod=True)
        self.assertEqual(cols[1]["value"], "----")

    def test_a_spread_page_uses_its_single_verb(self):
        desc = {"title": "LEVEL", "shape": tl.SHAPE_SPREAD, "verb": "level"}
        views = [("A", "KICK", {"level": 50}) for _ in range(8)]
        cols = tl.columns(desc, None, views, mod=True)
        self.assertTrue(all(c["bar"] is not None for c in cols))

    def test_a_spread_page_on_a_refused_verb_greys_all_eight(self):
        desc = {"title": "CHANCE", "shape": tl.SHAPE_SPREAD, "verb": "chance"}
        views = [("A", "KICK", {"chance": 100}) for _ in range(8)]
        # owned=True: CHANCE is a drift verb now, so it is refused only there.
        cols = tl.columns(desc, None, views, mod=True, owned=True)
        self.assertTrue(all(c["bar"] is None for c in cols))
        self.assertTrue(all(c["grey"] for c in cols))


def _drum_step_state():
    return {"hits": 4, "rotate": 0, "div": 2, "length": 16, "velo": 100,
            "chance": 100, "swing": 50, "pending": set()}


def _voice_state():
    return {"preset": "Init", "cutoff": 64, "reso": 64, "env": 64,
            "decay": 64, "level": 50, "reverb": 0, "delay": 0,
            "synth_ctrl": (True, True, True, True), "pending": set()}


def _drum_state():
    return {"kit": "Kit", "sample": "Snare", "level": 50, "reverb": 0,
            "delay": 0, "pending": set()}


class TheDurationRule(unittest.TestCase):
    """A tap latches, a hold is momentary - for EVERY modifier, 2026-09-01.

    It is law L1 out of this project's oldest plan and it was true of three
    buttons out of twenty. SHIFT, SELECT, DUPLICATE, MUTE and NAVIGATE were
    hold-only; MOD was latch-only; SCENE and PATTERN fired on a release past
    the threshold. Five grammars for entering a state, on a panel a player
    has to read in the dark."""

    HOLD = 0.25

    def test_a_press_turns_it_on_immediately(self):
        latch = tl_mod.latch()
        latch.edge(True, 0.0, self.HOLD)
        self.assertTrue(latch.down)
        self.assertTrue(latch.held)

    def test_a_tap_latches(self):
        latch = tl_mod.latch()
        latch.edge(True, 0.0, self.HOLD)
        latch.edge(False, 0.1, self.HOLD)
        self.assertTrue(latch.down)
        self.assertTrue(latch.latched)
        self.assertFalse(latch.held)

    def test_a_hold_is_momentary(self):
        latch = tl_mod.latch()
        latch.edge(True, 0.0, self.HOLD)
        latch.edge(False, 0.5, self.HOLD)
        self.assertFalse(latch.down)
        self.assertFalse(latch.latched)

    def test_a_second_tap_is_the_way_out(self):
        # No gesture on this panel enters a state and needs a different one to
        # leave it.
        latch = tl_mod.latch()
        latch.edge(True, 0.0, self.HOLD)
        latch.edge(False, 0.1, self.HOLD)
        latch.edge(True, 1.0, self.HOLD)
        latch.edge(False, 1.1, self.HOLD)
        self.assertFalse(latch.down)

    def test_holding_a_latched_modifier_leaves_the_latch_alone(self):
        # The press is always a press; only the release decides what it meant,
        # and a long one meant nothing but itself.
        latch = tl_mod.latch()
        latch.edge(True, 0.0, self.HOLD)
        latch.edge(False, 0.1, self.HOLD)       # latched
        latch.edge(True, 1.0, self.HOLD)
        latch.edge(False, 1.9, self.HOLD)       # a long hold
        self.assertTrue(latch.latched)

    def test_the_edge_reports_whether_the_state_changed(self):
        latch = tl_mod.latch()
        self.assertTrue(latch.edge(True, 0.0, self.HOLD))
        self.assertFalse(latch.edge(False, 0.1, self.HOLD))   # tap: still on
        self.assertFalse(latch.edge(True, 1.0, self.HOLD))    # still on
        self.assertTrue(latch.edge(False, 1.1, self.HOLD))    # tap: off

    def test_clear_drops_the_latch_and_leaves_the_hold(self):
        # HOME calls this. A finger still on the button is a fact about the
        # world, and clearing it would leave the driver disagreeing with the
        # hand until it let go.
        latch = tl_mod.latch()
        latch.edge(True, 0.0, self.HOLD)
        latch.edge(False, 0.1, self.HOLD)
        latch.edge(True, 1.0, self.HOLD)
        latch.clear()
        self.assertFalse(latch.latched)
        self.assertTrue(latch.held)
        self.assertTrue(latch.down)


class TheLens(unittest.TestCase):
    """ALL held or latched: one verb across all eight channels.

    It replaced five spread pages and two whole modes. "One verb over eight
    channels" was never a place - it is a direction of looking, and building
    it as a page meant one page per verb forever."""

    def _views(self, verb, values, kinds=None):
        kinds = kinds or ["drum"] * 5 + ["voice"] * 3
        out = []
        for i, value in enumerate(values):
            view = {"kind": kinds[i]}
            if value is not None:
                view[verb] = value
            out.append((chr(ord("A") + i), tl.CHANNELS[i][1], view))
        return out

    def test_nothing_moved_yet_shows_level(self):
        # The one answer that is always useful and always live on all eight.
        self.assertEqual(tl.lens_verb(None), tl.LENS_DEFAULT)
        self.assertEqual(tl.LENS_DEFAULT, "level")

    def test_a_channel_verb_is_what_it_spreads(self):
        self.assertEqual(tl.lens_verb("chance"), "chance")
        self.assertEqual(tl.lens_verb("cutoff"), "cutoff")
        self.assertEqual(tl.lens_verb("move"), "move")

    def test_a_global_verb_is_refused(self):
        # There is one BPM. Laying it side by side eight times says nothing.
        for verb in ("bpm", "root", "scale", "master", "walk"):
            self.assertIsNone(tl.lens_verb(verb), verb)

    def test_a_name_verb_is_refused(self):
        # Eight kit lists share no index, so a spread of them is eight
        # unrelated words under one heading.
        for verb in ("kit", "sample", "preset"):
            self.assertIsNone(tl.lens_verb(verb), verb)

    def test_a_ganged_effect_port_is_refused(self):
        # An fx: port is already one control for all eight.
        self.assertIsNone(tl.lens_verb("fx:reverb:decay"))

    def test_a_plugin_port_is_refused(self):
        # It IS per channel, so it looks spreadable in principle and is wrong
        # in every particular: VERB_COLS has no entry for it, so all eight
        # columns would draw dead and every encoder would refuse; the title
        # would read the raw symbol; and the eight channels run three
        # different synths, so column 4's `lv2:cutoff` and column 6's are not
        # the same control even when the symbol matches. A page of eight dead
        # columns under a held button is what law L4 exists to prevent.
        self.assertIsNone(tl.lens_verb("lv2:cutoff"))
        self.assertIsNone(tl.lens_verb("lv2:DCF1_CUTOFF"))

    def test_the_lens_only_ever_holds_a_verb_it_can_draw(self):
        # The closing invariant, and the one that catches the next verb added
        # to a page without an entry in VERB_COLS.
        for verb in list(tl.VERB_COLS) + ["lv2:x", "fx:reverb:x", "kit",
                                          "bpm", "nonsense", None, ""]:
            held = tl.lens_verb(verb)
            if held is None:
                continue
            self.assertIn(held, tl.VERB_COLS, f"{verb!r} -> {held!r}")

    def test_a_refusal_leaves_the_lens_where_it_was(self):
        # None is the signal to KEEP the previous verb, not to blank the page.
        # A lens that empties when you touch the wrong knob is one nobody
        # trusts mid-bar.
        self.assertIsNone(tl.lens_verb("bpm"))

    def test_the_page_it_draws_is_a_spread(self):
        desc = tl.lens_desc("chance")
        self.assertEqual(desc["shape"], tl.SHAPE_SPREAD)
        self.assertEqual(desc["verb"], "chance")

    def test_the_title_names_the_verb(self):
        # The label row is where G7 is satisfied: nothing about the lens is
        # invisible, including which of forty verbs it happens to hold.
        self.assertEqual(tl.lens_desc("chance")["title"], "ALL CHANCE")
        self.assertEqual(tl.lens_desc("random")["title"], "ALL MELODY")

    def test_it_draws_one_column_per_channel(self):
        views = self._views("chance", [0, 25, 50, 75, 100, 10, 20, 30])
        cols = tl.columns(tl.lens_desc("chance"), None, views)
        self.assertEqual(len(cols), 8)
        self.assertEqual(cols[0]["name"], "A KICK")
        self.assertEqual(cols[7]["name"], "H PADS")

    def test_a_channel_without_the_verb_draws_dead(self):
        # Law L4, and the lens is the first page on which live and dead
        # columns sit side by side as an ordinary picture rather than as a
        # fault: CUTOFF over five drums and three voices is four of each.
        views = self._views("cutoff", [None] * 5 + [64, 64, 64])
        cols = tl.columns(tl.lens_desc("cutoff"), None, views)
        for col in cols[:5]:
            self.assertTrue(col["grey"])
            self.assertEqual(col["value"], "----")
            self.assertIsNone(col["bar"])
        for col in cols[5:]:
            self.assertFalse(col["grey"])

    def test_lane_spreads_over_the_drums_and_draws_dead_on_the_voices(self):
        views = self._views("lane", [40] * 5 + [None] * 3)
        cols = tl.columns(tl.lens_desc("lane"), None, views)
        self.assertFalse(cols[0]["grey"])
        self.assertTrue(cols[5]["grey"])

    def test_a_dead_channel_still_says_WHICH_one(self):
        # The label stays the channel, lower-cased. A reader has to be able to
        # tell which of the eight cannot take the verb.
        views = self._views("cutoff", [None] * 8)
        cols = tl.columns(tl.lens_desc("cutoff"), None, views)
        self.assertEqual(cols[0]["name"], "a kick")

    def test_every_verb_on_a_channel_page_is_one_the_lens_can_hold(self):
        # THE CLOSING ARGUMENT for deleting the spread pages. Five of them
        # went; every verb they carried has to be reachable through the lens,
        # or the redesign lost a control.
        for (mode, kind), ring in tl.PAGE_RINGS.items():
            if mode == "VOLUME":
                continue
            for desc in ring:
                for verb in desc["verbs"] or ():
                    if verb is None or verb in tl.NAME_VERBS:
                        continue
                    self.assertEqual(tl.lens_verb(verb), verb,
                                     f"{mode}/{kind} {desc['title']}: {verb}")

    def test_the_five_deleted_spread_verbs_are_all_reachable(self):
        for verb in ("level", "reverb", "delay", "cutoff", "reso",
                     "swing", "chance", "rhythm", "move", "lane",
                     "exit", "phrase", "fill"):
            self.assertEqual(tl.lens_verb(verb), verb, verb)


class NoFeatureLostItsWayIn(unittest.TestCase):
    """THE COVERAGE PROOF, as a test rather than as a table in a document.

    The 2026-09-01 redesign moved almost every page. A table in a spec that
    says "nothing was lost" is a claim; this is the check, and it fails the
    moment a verb loses its last route to a knob.

    It exists because this project has been burned twice by the opposite -
    a document describing the code, believed, and wrong: `apply()` was
    documented as the single write path and had no branch for HITS or ROTATE,
    and a library slot was costed at zero because a spec said a button already
    reached it when no button did."""

    # Every key in default_channel_state that is NOT a parameter: registers,
    # bookkeeping and history. Each is here with the reason it can never be a
    # knob, because "why is this one exempt" is exactly the question a future
    # reader will ask.
    NOT_PARAMETERS = {
        "pending",       # law L2's bookkeeping set
        "rhythm_reg",    # the register itself; `rhythm` is its evolve rate
        # The steps a player tapped IN. Written by the pads and by nothing
        # else - there is no knob for "which steps did somebody choose", and
        # a verb that tried to be one would be a number standing for sixteen
        # independent decisions.
        "hand_reg",
        "register",      # the Turing register; `random` is its evolve rate
        "ring",          # the four-deep undo history behind NOTE REPEAT
        "kit_range",     # reached through the `range` alias on a sampler
        "walk_seed",     # bumped by a reroll, never dialled
    }

    def _page_verbs(self):
        out = set()
        for ring in tl.PAGE_RINGS.values():
            for desc in ring:
                for verb in desc["verbs"] or ():
                    if verb is not None:
                        out.add(verb)
                if desc["verb"]:
                    out.add(desc["verb"])
        return out

    def test_every_channel_parameter_has_a_knob(self):
        reachable = self._page_verbs()
        for kind in ("drum", "voice"):
            state = tl.default_channel_state(kind)
            missing = sorted(key for key in state
                             if key not in self.NOT_PARAMETERS
                             and key not in reachable)
            self.assertEqual(missing, [],
                             f"{kind}: state nothing can reach: {missing}")

    def test_the_kit_walk_window_is_reachable_through_range(self):
        # It was reachable from NO page before 2026-09-01 - a value in every
        # snapshot with no way to set it. RANGE on CONTROL/drum is that knob,
        # aliased to kit_range on a sampler by param_get and apply together.
        drum = tl.PAGE_RINGS[("CONTROL", "drum")][0]
        self.assertIn("range", drum["verbs"])

    def test_every_verb_a_page_names_is_one_the_column_table_can_draw(self):
        # The other direction, and the cheaper bug: a page naming a verb that
        # VERB_COLS has never heard of draws a dead column forever, silently.
        for (mode, kind), ring in tl.PAGE_RINGS.items():
            for desc in ring:
                for verb in desc["verbs"] or ():
                    if verb is None:
                        continue
                    self.assertIn(verb, tl.VERB_COLS,
                                  f"{mode}/{kind} {desc['title']}: {verb}")

    def test_page_one_of_every_ring_is_full_or_nearly(self):
        """Law G5's second half, 2026-09-01, and it is about PAGE ONE.

        Drawing a dead column honestly is the right answer to a control that
        cannot exist. Three of them on the page you land on without turning
        anything is a LAYOUT error that the honest drawing was hiding - which
        is what CONTROL/drum (three dead) and GEN/drum (six) were.

        Page one is what the mode button shows, so it is the one that has to
        earn its eight slots. A second page is an extension and may be
        emptier: the voice's thirteen generative verbs do not divide into
        sixteen slots, and pretending they do would mean padding page one
        with something that belongs elsewhere."""

        for (mode, kind), ring in tl.PAGE_RINGS.items():
            verbs = ring[0]["verbs"]
            if not verbs:
                continue
            dead = sum(1 for verb in verbs if verb is None)
            self.assertLessEqual(dead, 2,
                                 f"{mode}/{kind} page 1 "
                                 f"({ring[0]['title']}): {dead} empty slots")

    def test_a_later_page_still_earns_most_of_its_slots(self):
        # An extension page may be emptier than page one, but a page that is
        # half empty is two pages' worth of turning for four knobs.
        for (mode, kind), ring in tl.PAGE_RINGS.items():
            for desc in ring[1:]:
                verbs = desc["verbs"]
                if not verbs:
                    continue
                dead = sum(1 for verb in verbs if verb is None)
                self.assertLessEqual(dead, 3,
                                     f"{mode}/{kind} {desc['title']}: "
                                     f"{dead} empty slots")

    def test_no_ring_is_longer_than_two_static_pages(self):
        # The rings were 24 pages, five of them one-verb spreads, and the
        # generative page sat at depth six of the longest one. Generated LV2
        # and FX pages are appended at runtime and are not counted here -
        # they are as long as the plugin is.
        for key, ring in tl.PAGE_RINGS.items():
            self.assertLessEqual(len(ring), 2, f"{key}: {len(ring)} pages")

    def test_every_mode_still_has_a_ring_for_every_kind(self):
        for mode in tl.MODES:
            for kind in ("drum", "voice"):
                key = tl.ring_key(mode, kind)
                self.assertIn(key, tl.PAGE_RINGS, f"no ring for {key}")
                self.assertGreater(len(tl.PAGE_RINGS[key]), 0)

    def test_the_lens_is_not_a_mode(self):
        # It is a stateful button, and a CC in both places is exactly the
        # collision button_conflicts() exists to find.
        self.assertNotIn(tl.MODE_LENS, tl.MODES)
        self.assertEqual(tl.BUTTONS_STATEFUL[38], "lens")
        self.assertEqual(tl.button_conflicts(), [])

    def test_home_is_bound_and_the_free_ccs_are_still_offered(self):
        self.assertEqual(tl.BUTTONS_PRESS[12], "home")
        self.assertNotIn(12, tl.CCS_MEASURED_AND_UNCLAIMED)
        # FOUR free controls since 2026-09-01: CC 5 was the only one until
        # BROWSE, SAMPLING and ENTER were measured at the rig and turned out
        # to emit, both edges. Each is a whole control - a button, both edges,
        # and an LED index the daemon accepts and the driver has never
        # written.
        self.assertEqual(tl.CCS_MEASURED_AND_UNCLAIMED,
                         frozenset({5, 8, 9, 25, 36}))

    def test_nothing_binds_a_cc_that_is_offered_as_free(self):
        # The direction that actually costs something. An offered CC that is
        # bound is a number two features will claim, and the second claimant
        # is unreachable with no runtime symptom - which is the collision this
        # whole family of tests exists to catch.
        bound = (set(tl.BUTTONS_STATEFUL) | set(tl.BUTTONS_PRESS)
                 | tl.RESERVED_CCS | {11, 32, 37, 51})
        clash = sorted(tl.CCS_MEASURED_AND_UNCLAIMED & bound)
        self.assertEqual(clash, [], f"offered as free but bound: {clash}")

    def test_every_offered_cc_has_actually_been_measured(self):
        for cc in tl.CCS_MEASURED_AND_UNCLAIMED:
            self.assertIn(cc, tl.CCS_MEASURED,
                          f"CC {cc} is offered as free without a measurement")


class TheArrowsSteerTheLens(unittest.TestCase):
    """DL and DR step the lens's VERB while it is open.

    They are otherwise dark there - the lens is one page and has no ring to
    walk - so this costs no button and no new gesture. It is also what makes
    "the verb your hand last moved" safe: that rule is perfect for the knob
    you were just on and arbitrary for the one you want next. Before it,
    being on the wrong verb meant leaving the lens, finding a page carrying
    the right one, turning it, and coming back."""

    def _drum_ring(self):
        return (tl.PAGE_RINGS[("CONTROL", "drum")]
                + tl.PAGE_RINGS[("STEP", "drum")]
                + tl.PAGE_RINGS[("AUTO", "drum")])

    def test_the_walk_is_every_spreadable_verb_the_channel_has(self):
        verbs = tl.lens_verbs(self._drum_ring())
        for expected in ("hits", "chance", "swing", "rule", "lane", "move",
                         "level", "reverb", "delay", "range"):
            self.assertIn(expected, verbs, expected)

    def test_a_global_never_enters_the_walk(self):
        # There is one BPM. An arrow that stopped on it would be an arrow
        # that stops on nothing.
        verbs = tl.lens_verbs(tl.PAGE_RINGS[("VOLUME", None)])
        self.assertEqual(verbs, ())

    def test_a_name_verb_never_enters_the_walk(self):
        verbs = tl.lens_verbs(self._drum_ring())
        for name in ("kit", "sample", "preset"):
            self.assertNotIn(name, verbs, name)

    def test_a_verb_on_two_pages_appears_once(self):
        # `chance` is on both STEP pages. A verb that came round twice in one
        # walk would make the arrows feel broken rather than thorough.
        verbs = tl.lens_verbs(self._drum_ring() + tl.PAGE_RINGS[("STEP", "voice")])
        self.assertEqual(verbs.count("chance"), 1)

    def test_the_order_follows_the_pages(self):
        # Left to right across the panel, rather than an order nobody chose.
        verbs = tl.lens_verbs(tl.PAGE_RINGS[("STEP", "drum")])
        self.assertEqual(verbs[:4], ("hits", "rotate", "div", "length"))

    def test_stepping_forward_and_back(self):
        verbs = ("hits", "rotate", "div")
        self.assertEqual(tl.lens_step("hits", verbs, 1), "rotate")
        self.assertEqual(tl.lens_step("rotate", verbs, -1), "hits")

    def test_it_wraps_both_ways(self):
        verbs = ("hits", "rotate", "div")
        self.assertEqual(tl.lens_step("div", verbs, 1), "hits")
        self.assertEqual(tl.lens_step("hits", verbs, -1), "div")

    def test_an_unknown_verb_starts_the_walk_rather_than_refusing(self):
        # The lens can be holding a verb from a page the player has since
        # left - a voice verb after selecting a drum. A dead arrow at exactly
        # the moment they want to move is the failure this exists to fix.
        verbs = ("hits", "rotate", "div")
        self.assertEqual(tl.lens_step("gate", verbs, 1), "hits")
        self.assertEqual(tl.lens_step("gate", verbs, -1), "div")

    def test_an_empty_walk_leaves_the_verb_alone(self):
        self.assertEqual(tl.lens_step("hits", (), 1), "hits")

    def test_every_verb_in_a_walk_is_one_the_lens_accepts(self):
        # The closing check: lens_verbs and lens_verb must agree, or an arrow
        # could land somewhere the lens then refuses to draw.
        for key, ring in tl.PAGE_RINGS.items():
            for verb in tl.lens_verbs(ring):
                self.assertEqual(tl.lens_verb(verb), verb, f"{key}: {verb}")


class TheOneColumnAnswerMatchesTheEightColumnOne(unittest.TestCase):
    """A spread's dead-column question, asked twice, must answer once.

    The driver's `_column_dead` gates every encoder turn on the MIDI thread.
    On a spread it asks about ONE channel through verb_col + verb_is_dead
    rather than building all eight columns to read one of them - eight
    state_view copies per encoder report, under the lock, would be a real
    cost on a surface that has been thrown off the USB bus by load once.

    That shortcut is only safe while the two paths agree, so this checks
    them against each other rather than against a hand-written expectation.
    If a third rule for deadness is ever added to spread_columns, this goes
    red instead of the encoder quietly moving a channel the screen says is
    dead - which is this project's whole catalogue of expensive bugs."""

    def _views(self, verb, values, kinds):
        out = []
        for i, value in enumerate(values):
            view = {"kind": kinds[i]}
            if value is not None:
                view[verb] = value
            out.append((chr(ord("A") + i), tl.CHANNELS[i][1], view))
        return out

    def _one(self, verb, view):
        """What the driver's single-column path computes."""
        col = tl.verb_col(verb, view, view.get("kind"))
        return (col is None or bool(col.get("grey"))
                or tl.verb_is_dead(verb, view.get("kind"), view))

    def _eight(self, verb, views):
        """What the painter computes, for all eight."""
        cols = tl.columns(tl.lens_desc(verb), None, views)
        return [bool(c.get("grey")) for c in cols]

    def _check(self, verb, values, kinds=None):
        kinds = kinds or ["drum"] * 5 + ["voice"] * 3
        views = self._views(verb, values, kinds)
        painted = self._eight(verb, views)
        for i, (_letter, _name, view) in enumerate(views):
            self.assertEqual(self._one(verb, view), painted[i],
                             f"{verb} column {i}: one says "
                             f"{self._one(verb, view)}, eight say {painted[i]}")

    def test_a_verb_every_channel_has(self):
        self._check("chance", [0, 25, 50, 75, 100, 10, 20, 30])

    def test_a_verb_only_the_voices_have(self):
        self._check("cutoff", [None] * 5 + [64, 64, 64])

    def test_a_verb_only_the_drums_have(self):
        self._check("lane", [40] * 5 + [None] * 3)

    def test_a_verb_nobody_has(self):
        self._check("cutoff", [None] * 8)

    def test_a_verb_whose_deadness_depends_on_another_value(self):
        # SPAN is dead unless MODEL is on WALK. The one-column path has to
        # reach verb_is_dead for this, not just verb_col.
        views = [("A", "X", {"kind": "voice", "walk_span": 32,
                             "model": tl.MODEL_REGISTER})] * 4
        views += [("B", "Y", {"kind": "voice", "walk_span": 32,
                              "model": tl.MODEL_WALK})] * 4
        painted = [bool(c.get("grey"))
                   for c in tl.columns(tl.lens_desc("walk_span"), None, views)]
        self.assertEqual(painted, [True] * 4 + [False] * 4)
        for i, (_l, _n, view) in enumerate(views):
            self.assertEqual(self._one("walk_span", view), painted[i], i)

    def test_a_verb_that_takes_its_default(self):
        # A view that simply has not brought the key is an INCOMPLETE view,
        # not a channel without the verb, so neither path may call it dead.
        self._check("move", [None] * 8)


class AutoIsAPageAndNotADrawer(unittest.TestCase):
    """AUTO carries eight verbs off four old pages. That is the shape a
    drawer has, and the thing that stops it being one is a seam you can see.

    LEFT SCREEN: what the machine draws - which generator, how fast it changes
    its mind, how far out it may go. RIGHT SCREEN: when and for how long - how
    often it may act at all, how the phrase is built, how the part leaves. Two
    questions on two time bases, and the hardware already puts a physical gap
    between columns 4 and 5.

    The seam holds today by accident of the order somebody typed. These tests
    are what make it a rule, because the next verb added to this page will be
    dropped into the first empty slot unless something objects."""

    def _auto(self, kind):
        return _page("AUTO", kind, "AUTO")["verbs"]

    def test_the_left_screen_is_what_the_machine_draws(self):
        for kind in ("drum", "voice"):
            for verb in self._auto(kind)[:4]:
                self.assertIn(verb, tl.AUTO_DRAWS,
                              f"AUTO/{kind}: {verb} is on the left screen "
                              "but is not a drawing verb")

    def test_the_right_screen_is_when_and_for_how_long(self):
        for kind in ("drum", "voice"):
            for verb in self._auto(kind)[4:]:
                self.assertIn(verb, tl.AUTO_TIMES,
                              f"AUTO/{kind}: {verb} is on the right screen "
                              "but is not an arrangement verb")

    def test_both_kinds_put_the_same_four_on_the_right(self):
        # The arrangement half is kind-agnostic - a phrase is a phrase - so a
        # player who learns the right-hand screen on the drums has learnt it
        # on the voices too.
        self.assertEqual(self._auto("drum")[4:], self._auto("voice")[4:])
        self.assertEqual(set(self._auto("drum")[4:]), tl.AUTO_TIMES)

    def test_the_two_halves_do_not_overlap(self):
        self.assertEqual(tl.AUTO_DRAWS & tl.AUTO_TIMES, frozenset())

    def test_page_two_is_generative_only(self):
        # A second page exists to hold generator verbs that would otherwise
        # crowd page one - never to hold arrangement, which would put the same
        # question on two pages and make the seam meaningless.
        for kind in ("drum", "voice"):
            for desc in tl.PAGE_RINGS[tl.ring_key("AUTO", kind)][1:]:
                for verb in desc["verbs"] or ():
                    if verb is None:
                        continue
                    self.assertIn(verb, tl.AUTO_DRAWS,
                                  f"AUTO/{kind} {desc['title']}: {verb}")

    def test_every_auto_verb_is_claimed_by_one_half_or_the_other(self):
        # A verb in neither set is one nobody decided about. That is exactly
        # how the old GEN page ended up with six dead columns.
        for kind in ("drum", "voice"):
            for desc in tl.PAGE_RINGS[tl.ring_key("AUTO", kind)]:
                for verb in desc["verbs"] or ():
                    if verb is None:
                        continue
                    self.assertTrue(verb in tl.AUTO_DRAWS
                                    or verb in tl.AUTO_TIMES, verb)

    def test_no_arrangement_verb_leaks_onto_step(self):
        # STEP is what the channel plays. The moment MOVE or PHRASE appears
        # there, AUTO stops being the answer to "what does it do by itself".
        for kind in ("drum", "voice"):
            for verb in _page("STEP", kind, "STEP")["verbs"]:
                self.assertNotIn(verb, tl.AUTO_TIMES, f"STEP/{kind}: {verb}")


class ALatchedOverlaySaysWhoseThePadsAre(unittest.TestCase):
    """Six overlays compete for the same sixteen pads, and the obvious fix -
    one colour family each - DOES NOT FIT THIS HARDWARE.

    Measured rather than assumed: the eight channel hues sit at 0, 23, 45, 75,
    120, 187, 225 and 270 degrees, which leaves exactly two gaps wider than
    fifty degrees, and both are already spent (ARM's length ring at 143, the
    top chance rung at 313). There is no room for six disjoint families, so
    the pads cannot say whose they are by colour alone.

    Since the duration rule an overlay can be LATCHED, which means the hand
    that set it has left the button. The indicator is then the one surface
    that can say which one is up."""

    def test_a_latched_overlay_names_itself(self):
        self.assertEqual(tl.overlay_label("STEP", "bank", True), "STEP BANK")
        self.assertEqual(tl.overlay_label("STEP", "mute", True), "STEP MUTE")

    def test_a_held_overlay_says_nothing(self):
        # Your finger is on the button. The indicator would be telling you
        # what your own hand already says, on a row that truncates silently.
        self.assertEqual(tl.overlay_label("STEP", "bank", False), "STEP")

    def test_no_overlay_at_all_says_nothing(self):
        self.assertEqual(tl.overlay_label("STEP", None, True), "STEP")
        self.assertEqual(tl.overlay_label("STEP", "", True), "STEP")

    def test_it_uses_the_word_a_player_can_find_on_the_panel(self):
        # BANK is printed DUPLICATE and MOD is printed SWING, so the word has
        # to be the one that leads back to the right button rather than the
        # driver's internal name.
        self.assertEqual(tl.OVERLAY_WORDS["bank"], "BANK")
        self.assertEqual(tl.OVERLAY_WORDS["mod"], "MOD")
        self.assertEqual(tl.OVERLAY_WORDS["shift"], "ODDS")

    def test_every_pad_overlay_has_a_word(self):
        # A latched overlay with no word is one the player cannot name, which
        # is the whole failure this exists to prevent.
        for owner in tl.OVERLAY_PRIORITY:
            self.assertIn(owner, tl.OVERLAY_WORDS, owner)

    def test_the_lens_is_deliberately_absent(self):
        # It takes the ENCODERS, not the pads, and already renames the page -
        # a latched lens reads ALL CHANCE where the page name goes.
        self.assertNotIn("lens", tl.OVERLAY_WORDS)
        self.assertNotIn("lens", tl.OVERLAY_PRIORITY)

    def test_it_composes_like_every_other_suffix(self):
        label = tl.overlay_label("STEP 2/2", "mod", True)
        label = tl.freeze_label(label, True, False)
        self.assertEqual(label, "STEP 2/2 MOD FRZ")

    def test_the_words_are_short_enough_to_stack(self):
        # The indicator is 42 characters and eleven composers can append to
        # it. A long word here is one that pushes something else off the end.
        for word in tl.OVERLAY_WORDS.values():
            self.assertLessEqual(len(word), 6, word)


class _Panel:
    """A simulated surface, built ONLY out of the real predicates.

    Not a second implementation of the driver - that is the duplication this
    project has been burned by. It holds the seven latches (which are
    tlib.latch, the shipped object) and a mode, and every question it answers
    is delegated to the same pure function the driver asks. What it adds is
    SEQUENCE: the driver's own tests can only reach one function at a time,
    and every gesture a player makes is three or four of them composed.

    `t` is a clock in seconds. Gestures take it explicitly so a tap and a hold
    differ by a number rather than by a sleep."""

    HOLD = 0.25

    def __init__(self, mode="STEP", kind="drum"):
        self.latches = {name: tl_mod.latch() for name in
                        ("shift", "mod", "lens", "arm", "bank", "mute",
                         "navigate")}
        self.mode = mode
        self.kind = kind
        self.lens_verb = None
        self.t = 0.0

    # --- gestures -------------------------------------------------------
    def tap(self, name):
        self.latches[name].edge(True, self.t, self.HOLD)
        self.t += 0.05
        self.latches[name].edge(False, self.t, self.HOLD)
        self.t += 0.05
        return self

    def hold(self, name):
        self.latches[name].edge(True, self.t, self.HOLD)
        self.t += 0.05
        return self

    def release(self, name):
        self.t += 0.5                      # past the threshold: a real hold
        self.latches[name].edge(False, self.t, self.HOLD)
        self.t += 0.05
        return self

    def press_mode(self, mode):
        # A mode press drops the latched lens, whichever branch it takes.
        self.latches["lens"].clear()
        self.mode = mode
        return self

    def turn(self, verb):
        """A hand on a knob. Only a channel verb sets the lens."""
        if tl.lens_verb(verb) == verb:
            self.lens_verb = verb
        return self

    def home(self):
        self.mode = "STEP"
        for latch in self.latches.values():
            latch.clear()
        return self

    # --- what the surface says ------------------------------------------
    def pads(self):
        return tl.pad_owner(**{n: self.latches[n].down for n in
                               tl.OVERLAY_PRIORITY})

    def page(self):
        """The descriptor showing, lens included - the driver's _page()."""
        if self.latches["lens"].down:
            verb = self._lens_now()
            if verb is not None:
                return tl.lens_desc(verb)
        return tl.PAGE_RINGS[tl.ring_key(self.mode, self.kind)][0]

    def _lens_now(self):
        verb = tl.lens_verb(self.lens_verb)
        if verb is None:
            return None
        return verb if verb in self.lens_ring() else \
            tl.lens_verb(tl.LENS_DEFAULT)

    def lens_ring(self):
        ring = ()
        for mode in ("CONTROL", "STEP", "AUTO"):
            ring = ring + tuple(tl.PAGE_RINGS[tl.ring_key(mode, self.kind)])
        return tl.lens_verbs(ring)

    def arrow(self, delta):
        if self.latches["lens"].down:
            self.lens_verb = tl.lens_step(self._lens_now(),
                                          self.lens_ring(), delta)
        return self

    def light(self, name):
        latch = self.latches[name]
        return tl.state_light(latch.held, latch.latched, self.t)

    def label(self, base=None):
        base = base or self.page()["title"]
        owner = self.pads()
        return tl.overlay_label(base, owner,
                                bool(owner) and self.latches[owner].latched)


class TheJourneysAPlayerActuallyMakes(unittest.TestCase):
    """The gestures from the design's interaction-cost table, played through.

    Every other test here checks one function. A player never uses one: they
    hold a thing, turn a thing, let go, and expect the surface to have kept up.
    Composition is where a surface fails, and it is the only kind of failure
    the driver's own tests cannot reach at all."""

    def test_starting_a_jam_lands_on_the_step_picture(self):
        p = _Panel()
        self.assertIsNone(p.pads())
        self.assertEqual(p.page()["title"], "STEP")

    def test_reaching_the_generator_is_one_press(self):
        p = _Panel().press_mode("AUTO")
        self.assertEqual(p.page()["title"], "AUTO")
        self.assertIn("rule", p.page()["verbs"])
        self.assertIn("lean", p.page()["verbs"])

    def test_a_held_lens_hands_the_pages_back_on_release(self):
        p = _Panel().press_mode("AUTO").turn("rule")
        before = p.page()["title"]
        p.hold("lens")
        self.assertEqual(p.page()["title"], "ALL RULE")
        p.release("lens")
        self.assertEqual(p.page()["title"], before)

    def test_a_latched_lens_survives_the_finger_and_says_so(self):
        p = _Panel().turn("chance").tap("lens")
        self.assertEqual(p.page()["title"], "ALL CHANCE")
        self.assertEqual(p.light("lens"),
                         tl.state_light(False, True, p.t))
        p.tap("lens")
        self.assertEqual(p.page()["title"], "STEP")

    def test_a_mode_press_gets_you_out_of_a_latched_lens(self):
        # The failure this was written for: the mode LED moved and the screen
        # did not, because the lens outranks the mode.
        p = _Panel().turn("chance").tap("lens").press_mode("CONTROL")
        self.assertEqual(p.page()["title"], "CTRL")
        self.assertFalse(p.latches["lens"].down)

    def test_the_arrows_walk_the_verbs_inside_the_lens(self):
        p = _Panel().turn("hits").hold("lens")
        self.assertEqual(p.page()["title"], "ALL HITS")
        p.arrow(1)
        self.assertEqual(p.page()["verb"], "rotate")
        p.arrow(-1)
        self.assertEqual(p.page()["verb"], "hits")

    def test_the_lens_follows_you_to_the_other_kind(self):
        # Hold a drum-only verb, select a voice: it falls back rather than
        # showing eight columns that cannot answer.
        p = _Panel().press_mode("AUTO").turn("lane").hold("lens")
        self.assertEqual(p.page()["verb"], "lane")
        p.kind = "voice"
        self.assertEqual(p.page()["verb"], tl.LENS_DEFAULT)

    def test_a_global_leaves_the_lens_where_it_was(self):
        p = _Panel().turn("chance").turn("bpm").hold("lens")
        self.assertEqual(p.page()["verb"], "chance")

    def test_muting_from_the_grid_is_a_tap_and_the_light_says_so(self):
        p = _Panel().tap("mute")
        self.assertEqual(p.pads(), "mute")
        self.assertTrue(p.label().endswith("MUTE"))
        p.tap("mute")
        self.assertIsNone(p.pads())

    def test_launching_a_bank_leaves_the_hand_free(self):
        # A bank press lands on the bar, so the latch is the useful half:
        # nothing to do until the boundary arrives.
        p = _Panel().tap("bank")
        self.assertEqual(p.pads(), "bank")
        self.assertEqual(p.light("bank"), tl.state_light(False, True, p.t))

    def test_shift_still_outranks_everything(self):
        p = _Panel().tap("mod").tap("bank").hold("shift")
        self.assertEqual(p.pads(), "shift")
        p.release("shift")
        self.assertEqual(p.pads(), "bank")

    def test_mod_and_arm_together_stay_on_mod(self):
        # Building a one-shot modulator: the rate-and-shape menu must not be
        # taken away at the moment it is being read.
        p = _Panel().tap("mod").hold("arm")
        self.assertEqual(p.pads(), "mod")

    def test_home_gets_you_out_of_everything_latched(self):
        p = (_Panel().press_mode("AUTO").turn("rule")
             .tap("lens").tap("mute").tap("navigate"))
        p.home()
        self.assertEqual(p.mode, "STEP")
        self.assertIsNone(p.pads())
        self.assertEqual(p.page()["title"], "STEP")

    def test_home_leaves_a_finger_that_is_still_down_alone(self):
        p = _Panel().hold("shift")
        p.home()
        self.assertEqual(p.pads(), "shift")
        p.release("shift")
        self.assertIsNone(p.pads())

    def test_a_held_overlay_does_not_name_itself(self):
        # Your finger is on it; the indicator would repeat what your hand says
        # on a row that truncates silently.
        p = _Panel().hold("mute")
        self.assertEqual(p.label(), "STEP")
        p.release("mute")
        p.tap("mute")
        self.assertEqual(p.label(), "STEP MUTE")

    def test_every_overlay_is_reachable_by_both_routes(self):
        # The duration rule's whole promise: you never have to decide which
        # you meant before you start.
        for name in tl.OVERLAY_PRIORITY:
            held = _Panel().hold(name)
            self.assertEqual(held.pads(), name, f"{name} held")
            tapped = _Panel().tap(name)
            self.assertEqual(tapped.pads(), name, f"{name} tapped")

    def test_every_overlay_leaves_by_the_button_it_came_in_on(self):
        for name in tl.OVERLAY_PRIORITY:
            p = _Panel().tap(name).tap(name)
            self.assertIsNone(p.pads(), name)

    def test_reaching_the_eight_channel_view_never_loses_the_channel(self):
        # The lens's whole point, and the interaction-cost table's largest
        # claim: two gestures, and the page underneath is untouched.
        p = _Panel().press_mode("CONTROL").turn("level")
        p.hold("lens")
        self.assertEqual(p.page()["shape"], tl.SHAPE_SPREAD)
        p.release("lens")
        self.assertEqual(p.page()["title"], "CTRL")
        self.assertEqual(p.mode, "CONTROL")


class EveryPageCanActuallyBeDrawn(unittest.TestCase):
    """Render every page of every ring and assert the driver can consume it.

    THE TEST THAT WAS MISSING, and its absence cost a frozen display at the
    rig. PHRASE and EXIT gave a seg bar a FLOAT fraction where the driver
    unpacks `index, count = frac`. They are columns 6 and 8 of the AUTO page,
    so screen 0 built and screen 1 raised TypeError - inside the poll thread's
    catch-all, which logs one traceback and then counts. The right-hand
    display sat frozen on the previous page, showing four values that were no
    longer true and could not be moved.

    Every other test here checks one verb, one column or one predicate. None
    of them walked a whole page and asked whether the SHAPE of what came out
    is what the consumer expects - and the consumer is in the driver, which
    cannot be imported off the rig.

    So this encodes the driver's contract instead: a seg bar's frac is an
    (index, count) pair, a uni or bi bar's is a float in 0..1, a dead column
    has no bar at all. It is a second copy of a rule, which this project
    treats as a cost - but the alternative was finding it by playing."""

    def _drum(self):
        st = dict(tl.default_channel_state("drum"))
        st.update(kit="909", sample="BD", hits=4, rotate=0, div=1, length=16,
                  kind="drum")
        return st

    def _voice(self):
        st = dict(tl.default_channel_state("voice"))
        st.update(preset="SAW", kind="voice", synth_ctrl=(1, 1, 1, 1))
        return st

    def _globals(self):
        return dict(root=0, scale=0, bpm=125, master=80, revsize=25,
                    revtype=3, dlytime=1, dlyfbk=35, walk=0, wspan=2,
                    pending=set())

    def _check(self, where, cols):
        self.assertEqual(len(cols), 8, where)
        for i, col in enumerate(cols):
            bar, frac = col["bar"], col["frac"]
            at = f"{where} column {i + 1} ({col['name']})"
            if bar is None:
                continue
            if bar == "seg":
                self.assertIsInstance(
                    frac, tuple,
                    f"{at}: a seg bar's frac must be (index, count) - the "
                    f"driver unpacks it - and this is {frac!r}")
                self.assertEqual(len(frac), 2, at)
                index, count = frac
                self.assertIsInstance(index, int, at)
                self.assertGreater(count, 0, at)
                self.assertLessEqual(index, count, at)
            else:
                self.assertIsInstance(frac, float, f"{at}: {bar} wants a float")
                self.assertGreaterEqual(frac, -0.01, at)
                self.assertLessEqual(frac, 1.01, at)

    def test_every_static_page_of_every_ring(self):
        for (mode, kind), ring in tl.PAGE_RINGS.items():
            for desc in ring:
                if desc["shape"] == tl.SHAPE_PENDING:
                    continue
                if desc["shape"] == tl.SHAPE_SPREAD:
                    views = [(chr(65 + i), tl.CHANNELS[i][1],
                              self._drum() if i < 5 else self._voice())
                             for i in range(8)]
                    cols = tl.columns(desc, None, views)
                elif desc["shape"] == tl.SHAPE_GLOBAL:
                    cols = tl.columns(desc, None, self._globals())
                else:
                    state = self._drum() if kind == "drum" else self._voice()
                    cols = tl.columns(desc, kind, state)
                self._check(f"{mode}/{kind} {desc['title']}", cols)

    def test_every_page_the_lens_can_open(self):
        # The lens draws any channel verb across eight channels, so it can
        # reach a shape no hand-written page ever put on screen.
        views = [(chr(65 + i), tl.CHANNELS[i][1],
                  self._drum() if i < 5 else self._voice()) for i in range(8)]
        for verb in tl.VERB_COLS:
            if tl.lens_verb(verb) != verb:
                continue
            desc = tl.lens_desc(verb)
            self._check(f"lens {verb}", tl.columns(desc, None, views))

    def test_it_holds_at_the_ends_of_every_range(self):
        # A frac is easy to get right in the middle and wrong at a bound.
        for verb, spec in tl.VERB_COLS.items():
            for value in (0, 1, 4, 16, 100, 127, -2):
                state = {verb: value, "kind": "drum", "model": "reg"}
                col = tl.verb_col(verb, state, "drum")
                if col is None or col["bar"] is None:
                    continue
                at = f"{verb} at {value}"
                if col["bar"] == "seg":
                    self.assertIsInstance(col["frac"], tuple, at)
                else:
                    self.assertIsInstance(col["frac"], float, at)


class RangeIsLiveOnlyWhereTheKitWalkRuns(unittest.TestCase):
    """RANGE edits the kit-walk window, and the kit walk only runs on a
    channel driven by the Turing register.

    Two defects in one afternoon, both at the rig, both about this column.
    First it was LIVE on a euclidean drum, where nothing reads it - a knob
    showing a number it cannot move. Then the refusal was keyed on the wrong
    kind and it stayed dead on a drum switched to VOICE behaviour, which is
    the one case where it is the live control.

    The trap underneath both: **CONTROL passes the ENGINE kind, every other
    mode passes the BEHAVIOUR.** That is deliberate - a sampler has kits and
    samples however it is played - and it means `kind` on the drum CONTROL
    page is always "drum". The behaviour travels in the view instead."""

    def test_dead_on_a_drum_behaving_as_a_drum(self):
        self.assertTrue(tl.verb_is_dead(
            "range", "drum", {"kind": "drum", "range": 4}))

    def test_live_on_a_drum_behaving_as_a_voice(self):
        # The case CONTROL's engine-kind hid. SHIFT + GRID puts a sampler on
        # the Turing register, and then the kit walk is what draws the line.
        self.assertFalse(tl.verb_is_dead(
            "range", "drum", {"kind": "voice", "range": 4}))

    def test_live_on_a_voice(self):
        self.assertFalse(tl.verb_is_dead(
            "range", "voice", {"kind": "voice", "range": 2}))

    def test_the_argument_is_the_fallback_when_a_view_omits_the_kind(self):
        # Callers that build a partial state - every test written before the
        # lens needed the behaviour in the view - must keep their meaning.
        self.assertFalse(tl.verb_is_dead("range", "voice", {"range": 2}))
        self.assertTrue(tl.verb_is_dead("range", "drum", {"range": 4}))

    def test_the_column_says_so_either_way(self):
        drum = tl.columns(_page("CONTROL", "drum", "CTRL"), "drum",
                          dict(tl.default_channel_state("drum"),
                               kind="drum", kit="909", sample="BD"))
        self.assertTrue(drum[2]["grey"])
        self.assertEqual(drum[2]["value"], "----")
        switched = tl.columns(_page("CONTROL", "drum", "CTRL"), "drum",
                              dict(tl.default_channel_state("drum"),
                                   kind="voice", kit="909", sample="BD"))
        self.assertFalse(switched[2]["grey"])
        self.assertEqual(switched[2]["name"], "RANGE")


class AKindSwitchMustNotResetTheChannel(unittest.TestCase):
    """Switching what a channel BEHAVES AS must not touch what the channel IS.

    Found at the rig 2026-09-01, by the owner, from the sound. A first switch
    to a kind built a fresh state dict, which carries chance=100 - and CHANCE
    IS NOT A PROPERTY OF THE KIND. It is a per-pattern zynseq property; the
    sequencer kept the real value while the driver's mirror said 100. The
    display read 100 and the channel played thinner than that.

    That is the one failure this surface may not have. A thinned or silent
    channel must say why, and the number a player checks first was the number
    that lied. It was found only by nudging the knob off 100 and back, which
    wrote the mirror through.

    The rule is a category, not a list: a SEQUENCER property belongs to the
    pattern, a MIXER property to the strip, an ARRANGEMENT property to the
    part, and none of them changes meaning when a channel starts behaving as
    something else. `div` and `beats` were already carried for exactly this
    reason - the comment saying so sits one line below where the bug was."""

    def _played(self, kind):
        st = dict(tl.default_channel_state(kind))
        st.update(chance=40, swing=62, level=77, reverb=30, delay=12,
                  move=50, phrase=4, fill=80, exit=2, velo=96, rule="r110")
        return st

    def test_a_sequencer_property_survives(self):
        # The one that was actually wrong, and the most dangerous because
        # CHANCE is what you read when a channel goes quiet.
        new = tl.carry_channel_scoped(self._played("drum"),
                                      tl.default_channel_state("voice"))
        self.assertEqual(new["chance"], 40)
        self.assertEqual(new["swing"], 62)

    def test_a_mixer_property_survives(self):
        new = tl.carry_channel_scoped(self._played("drum"),
                                      tl.default_channel_state("voice"))
        self.assertEqual((new["level"], new["reverb"], new["delay"]),
                         (77, 30, 12))

    def test_an_arrangement_property_survives(self):
        new = tl.carry_channel_scoped(self._played("voice"),
                                      tl.default_channel_state("drum"))
        self.assertEqual((new["move"], new["phrase"], new["fill"],
                          new["exit"]), (50, 4, 80, 2))

    def test_what_belongs_to_the_kind_is_rebuilt(self):
        # The other half of the rule. A voice's GATE means nothing to a drum,
        # and a drum's KIT means nothing to a voice, so those must NOT carry.
        new = tl.carry_channel_scoped(self._played("voice"),
                                      tl.default_channel_state("drum"))
        self.assertNotIn("gate", new)
        self.assertNotIn("octave", new)
        self.assertIn("kit", new)
        self.assertEqual(new["kit"], "----")

    def test_the_registers_are_rebuilt_not_carried(self):
        # rhythm_reg is per kind: subtractive on a drum, and which steps sound
        # on a voice. Carrying one into the other is not a mirror problem, it
        # is a different meaning wearing the same key.
        old = dict(tl.default_channel_state("drum"))
        old["rhythm_reg"] = 0x00FF
        new = tl.carry_channel_scoped(old, tl.default_channel_state("voice"))
        self.assertEqual(new["rhythm_reg"], 0xFFFF)

    def test_pending_is_not_carried(self):
        # Law L2's bookkeeping. The arriving state gets its own empty set, or
        # a change that landed under the old kind would show as pending under
        # the new one forever.
        old = dict(tl.default_channel_state("drum"))
        old["pending"] = {"div", "length"}
        new = tl.carry_channel_scoped(old, tl.default_channel_state("voice"))
        self.assertEqual(new["pending"], set())

    def test_a_partial_state_plants_nothing(self):
        # A caller with a half-built dict must not put a None where the new
        # kind expects a number.
        new = tl.carry_channel_scoped({"chance": 25},
                                      tl.default_channel_state("voice"))
        self.assertEqual(new["chance"], 25)
        self.assertEqual(new["level"], tl.default_channel_state("voice")["level"])

    def test_every_carried_key_exists_on_both_kinds(self):
        # A key that only one kind has would be carried onto a state that has
        # no use for it - which is how a stale mirror gets a second home.
        for kind in ("drum", "voice"):
            state = tl.default_channel_state(kind)
            for key in tl.CHANNEL_SCOPED:
                self.assertIn(key, state, f"{key} missing on {kind}")

    def test_a_round_trip_changes_nothing_that_belongs_to_the_channel(self):
        start = self._played("drum")
        there = tl.carry_channel_scoped(start, tl.default_channel_state("voice"))
        back = tl.carry_channel_scoped(there, tl.default_channel_state("drum"))
        for key in tl.CHANNEL_SCOPED:
            self.assertEqual(back[key], start[key], key)


class OneButtonRegenerates(unittest.TestCase):
    """PATTERN does both kinds and the selected channel decides which.

    The owner proposed it at the rig; reading reroll_scope made the case
    stronger than the argument. **A bare press already ignored which of the
    two buttons you pressed** - it takes the selected channel either way,
    because refusing with "this is the drum button and you are on a voice"
    would be a rule to remember for no benefit. The pair differed in exactly
    one situation, SHIFT, where the word chose samplers or synths.

    So one button loses one thing and nothing else: rerolling every drum while
    a voice is selected now needs you to select a drum first."""

    SAMPLERS = {0: True, 1: True, 2: True, 3: True, 4: True,
                5: False, 6: False, 7: False}
    MACHINE = {ch: "gen" for ch in range(8)}

    def _which(self, channel):
        """What the driver derives: the selected channel's ENGINE type."""
        return "pattern" if self.SAMPLERS[channel] else "scene"

    def test_a_bare_press_takes_the_selected_channel_whatever_it_is(self):
        for channel in range(8):
            got = tl.reroll_scope(self._which(channel), self.SAMPLERS,
                                  self.MACHINE, channel, False)
            self.assertEqual(got, (channel,), f"channel {channel}")

    def test_that_was_already_true_of_both_old_buttons(self):
        # The finding that justified the merge: with no SHIFT, the word does
        # not enter into it. Both spellings give the same answer.
        for channel in (0, 6):
            drum_word = tl.reroll_scope("pattern", self.SAMPLERS,
                                        self.MACHINE, channel, False)
            synth_word = tl.reroll_scope("scene", self.SAMPLERS,
                                         self.MACHINE, channel, False)
            self.assertEqual(drum_word, synth_word)

    def test_shift_takes_the_selected_channel_s_own_engine_type(self):
        on_a_drum = tl.reroll_scope(self._which(0), self.SAMPLERS,
                                    self.MACHINE, 0, True)
        self.assertEqual(on_a_drum, (0, 1, 2, 3, 4))
        on_a_voice = tl.reroll_scope(self._which(6), self.SAMPLERS,
                                     self.MACHINE, 6, True)
        self.assertEqual(on_a_voice, (5, 6, 7))

    def test_the_one_thing_it_costs(self):
        # Stated as a test rather than buried in a comment: from a voice, a
        # SHIFT press can no longer reach the drums. Select one first.
        from_a_voice = tl.reroll_scope(self._which(6), self.SAMPLERS,
                                       self.MACHINE, 6, True)
        for drum in range(5):
            self.assertNotIn(drum, from_a_voice)

    def test_engine_not_kind(self):
        # A sampler driven by the Turing register is still a sampler. The
        # scope is keyed on the engine, so SHIFT on it reaches the drums.
        got = tl.reroll_scope("pattern", self.SAMPLERS, self.MACHINE, 4, True)
        self.assertEqual(got, (0, 1, 2, 3, 4))

    def test_a_channel_you_have_played_is_skipped(self):
        owners = dict(self.MACHINE)
        owners[2] = "player"
        alone = tl.reroll_scope("pattern", self.SAMPLERS, owners, 2, False)
        self.assertEqual(alone, ())
        wide = tl.reroll_scope("pattern", self.SAMPLERS, owners, 0, True)
        self.assertEqual(wide, (0, 1, 3, 4))

    def test_the_light_can_say_a_press_would_do_nothing(self):
        """The refusal above was SILENT until 2026-09-01, and the owner hit it
        at the rig: pressed the button, watched nothing happen, had to be told
        why. This surface's one law is that a silent channel says why, and a
        refused gesture that says nothing is the same failure in other
        clothes. The driver lights the button from exactly this predicate."""

        owners = dict(self.MACHINE)
        owners[2] = "player"
        would_act = tl.reroll_scope("pattern", self.SAMPLERS, owners, 2, False)
        self.assertEqual(tl.action_light(bool(would_act)), tl.LIGHT_OFF)
        # ...and SHIFT widens the scope, so the same button lights again.
        wider = tl.reroll_scope("pattern", self.SAMPLERS, owners, 2, True)
        self.assertEqual(tl.action_light(bool(wider)), tl.LIGHT_DIM)


class ANameColumnWithNothingToStepDrawsDead(unittest.TestCase):
    """`KIT ----` in upper case with a bar is a LIE, not a silence.

    Found while sweeping for silent refusals on 2026-09-01, and the rig had
    been in exactly this state an hour earlier - the deploy printed "no kits
    (no synth processor)" into the journal while the column looked completely
    normal. The knob above it did nothing.

    The distinction that matters: **"----" is a name this driver could not
    read**, and the knob can still walk past it to one it can. **An empty list
    is a knob that cannot move at all**, and this surface has a precise way of
    saying that - lower case, no bar, and the encoder refused by the same
    flag. This case was not using it.

    The driver decides which by passing None into the view, never by inspecting
    the string, because "----" is a legitimate name for a kit somebody could
    author."""

    def _kit(self, value):
        state = dict(tl.default_channel_state("drum"))
        state["kind"] = "drum"
        if value is None:
            state.pop("kit", None)
        else:
            state["kit"] = value
        return tl.verb_col("kit", state, "drum")

    def test_a_real_kit_draws_live(self):
        col = self._kit("Roland 909")
        self.assertFalse(col["grey"])
        self.assertEqual(col["name"], "KIT")
        self.assertIsNotNone(col["bar"])

    def test_an_unreadable_name_still_draws_live(self):
        # The knob can walk past it. This is the case "----" is FOR.
        col = self._kit("----")
        self.assertFalse(col["grey"])
        self.assertEqual(col["name"], "KIT")

    def test_nothing_to_step_draws_dead(self):
        col = self._kit(None)
        self.assertTrue(col["grey"])
        self.assertEqual(col["name"], "kit")
        self.assertEqual(col["value"], "----")
        self.assertIsNone(col["bar"])

    def test_the_same_holds_for_sample_and_preset(self):
        for verb, kind in (("sample", "drum"), ("preset", "voice")):
            state = dict(tl.default_channel_state(kind))
            state["kind"] = kind
            state.pop(verb, None)
            col = tl.verb_col(verb, state, kind)
            self.assertTrue(col["grey"], verb)
            self.assertIsNone(col["bar"], verb)

    def test_a_dead_name_column_refuses_its_encoder_too(self):
        # The painter and the encoder read the same flag, so a column that
        # says it cannot act cannot then be turned. That is the half of law
        # L4 that stops a silent refusal being possible at all.
        col = self._kit(None)
        self.assertTrue(col["grey"])
        live = self._kit("Roland 909")
        self.assertFalse(live["grey"])


class AVerbDrawsDeadOnAKindThatDoesNotHaveIt(unittest.TestCase):
    """Law L4 across kinds, which the LENS made reachable and VERB_DEFAULTS
    had quietly broken.

    Before the lens a kind-specific verb only ever appeared on a page of its
    own kind, so nothing tested this. The lens spreads one verb across all
    eight channels, and five verbs then drew LIVE on channels that have no key
    for them: RATCHET and LEAN on the voices, MODEL, FEED and AMOUNT on the
    drums. The cause was VERB_DEFAULTS handing them a value, which is exactly
    what its own comment warns against.

    **Three of the five were worse than silent.** `ratchet`, `lean` and
    `amount` are in VERB_RANGES or SWITCH_VERBS, so apply() stored them and
    the number on screen MOVED, while _apply_generator's arm for each is gated
    on the kind and did nothing. A knob that moves a value and changes no
    sound is the worst object this surface can produce."""

    def _views(self):
        drum = dict(tl.default_channel_state("drum"))
        drum.update(kind="drum", hits=4, kit="909", sample="BD")
        voice = dict(tl.default_channel_state("voice"))
        voice.update(kind="voice", hits=4, preset="SAW",
                     synth_ctrl=(1, 1, 1, 1))
        return [(chr(65 + i), tl.CHANNELS[i][1], drum if i < 5 else voice)
                for i in range(8)]

    def _picture(self, verb):
        cols = tl.columns(tl.lens_desc(verb), None, self._views())
        return "".join("." if c["grey"] else "#" for c in cols)

    def test_a_drum_only_verb_is_dead_on_the_voices(self):
        for verb in ("hits", "ratchet", "lean", "lane"):
            self.assertEqual(self._picture(verb), "#####...", verb)

    def test_a_voice_only_verb_is_dead_on_the_drums(self):
        for verb in ("model", "feed", "amount"):
            self.assertEqual(self._picture(verb), ".....###", verb)

    def test_a_shared_verb_is_live_on_all_eight(self):
        for verb in ("chance", "level", "swing", "move", "velo"):
            self.assertEqual(self._picture(verb), "########", verb)

    def test_the_table_agrees_with_the_state_it_describes(self):
        """The guard against drift, and the reason this is a table rather than
        a list of special cases.

        A verb that lives in one kind's default state and not the other's IS
        kind-specific, whatever anybody wrote down. Where the two disagree the
        table is wrong - either a verb moved and nobody told it, or somebody
        added an entry that is not true.

        The exemptions are named with their reasons rather than skipped
        silently: the four legacy verbs do not live in the state dict at all,
        and `range` is decided by BEHAVIOUR rather than by which dict holds
        it."""

        drum = tl.default_channel_state("drum")
        voice = tl.default_channel_state("voice")
        LEGACY = {"hits", "rotate", "div", "length"}   # per-group arrays
        BY_BEHAVIOUR = {"range"}                       # see verb_is_dead
        INTERNAL = {"register", "ring", "rhythm_reg", "hand_reg",
                    "kit_range", "pending"}
        for verb in set(drum) | set(voice):
            if verb in LEGACY | BY_BEHAVIOUR | INTERNAL:
                continue
            on_drum, on_voice = verb in drum, verb in voice
            if on_drum and on_voice:
                self.assertNotIn(verb, tl.VERB_KINDS,
                                 f"{verb} is on both kinds but the table "
                                 "calls it specific")
                continue
            expected = frozenset({"drum"} if on_drum else {"voice"})
            self.assertEqual(tl.VERB_KINDS.get(verb), expected,
                             f"{verb} lives only on "
                             f"{'drum' if on_drum else 'voice'}")

    def test_a_dead_column_refuses_its_encoder(self):
        # The half that stops it being a lie rather than merely a silence.
        # The painter and _column_dead read the same flag.
        drum = dict(tl.default_channel_state("drum"))
        drum["kind"] = "drum"
        self.assertTrue(tl.verb_is_dead("model", "drum", drum))
        self.assertTrue(tl.verb_is_dead("amount", "drum", drum))
        voice = dict(tl.default_channel_state("voice"))
        voice["kind"] = "voice"
        self.assertTrue(tl.verb_is_dead("ratchet", "voice", voice))
        self.assertTrue(tl.verb_is_dead("lean", "voice", voice))


class ADrumTapAddsAStep(unittest.TestCase):
    """The same gesture means the same thing on both kinds, 2026-09-01.

    It did not. On a voice a pad tap adds a step; on a drum the rhythm
    register is SUBTRACTIVE - HITS and ROTATE draw the line and the register
    may take a hit away and never invent one - so a tap did nothing wherever
    euclid had not already placed one.

    It was invisible until the same day, because the tap previewed the drum
    whether or not it had done anything: the instrument made a sound that said
    it had worked. The owner found the limitation within a minute of that
    preview being made honest, on a channel with HITS at 2 where fourteen of
    the sixteen pads were inert.

    TWO REGISTERS RATHER THAN ONE MEANING CHANGED. The subtractive register
    keeps its exact behaviour, so RHYTHM's evolution and every existing
    snapshot are untouched; `hand_reg` is a separate set of steps the player
    put in, and zero is the migration."""

    LINE = (True, False, False, False, True, False, False, False)
    ALL_KEPT = 0xFF

    def test_a_channel_nobody_has_tapped_is_unchanged(self):
        # The migration, and the reason this was cheap: hand_reg defaults to
        # zero, and zero adds nothing.
        self.assertEqual(tl.drum_steps(self.LINE, self.ALL_KEPT, 0),
                         tl.drum_steps(self.LINE, self.ALL_KEPT))

    def test_tapping_where_euclid_has_nothing_adds_a_step(self):
        reg, hand, added = tl.drum_tap(self.ALL_KEPT, 0, 2, False)
        self.assertTrue(added)
        self.assertTrue(tl.drum_steps(self.LINE, reg, hand)[2])

    def test_tapping_it_again_takes_it_back_out(self):
        reg, hand, _ = tl.drum_tap(self.ALL_KEPT, 0, 2, False)
        reg, hand, added = tl.drum_tap(reg, hand, 2, True)
        self.assertFalse(added)
        self.assertFalse(tl.drum_steps(self.LINE, reg, hand)[2])

    def test_tapping_a_euclid_hit_removes_it(self):
        reg, hand, added = tl.drum_tap(self.ALL_KEPT, 0, 0, True)
        self.assertFalse(added)
        self.assertFalse(tl.drum_steps(self.LINE, reg, hand)[0])

    def test_tapping_a_removed_hit_puts_it_back_where_it_came_from(self):
        # Restored through the register it was taken from rather than added a
        # second time by hand, so the two registers go on meaning what they
        # say.
        reg, hand, _ = tl.drum_tap(self.ALL_KEPT, 0, 0, True)
        reg, hand, added = tl.drum_tap(reg, hand, 0, False)
        self.assertTrue(added)
        self.assertEqual(hand, 0)
        self.assertTrue(tl.drum_steps(self.LINE, reg, hand)[0])

    def test_only_adding_reports_added(self):
        # The preview follows this flag. Previewing a step you have just
        # removed was contradictory since the day it shipped.
        self.assertTrue(tl.drum_tap(self.ALL_KEPT, 0, 3, False)[2])
        self.assertFalse(tl.drum_tap(self.ALL_KEPT, 0, 0, True)[2])

    def test_a_hand_step_survives_an_evolving_rhythm(self):
        """The promise the guide already makes, and the reason the hand
        register is added AFTER the subtraction rather than folded into it."""
        _, hand, _ = tl.drum_tap(self.ALL_KEPT, 0, 2, False)
        for reg in (0x00, 0x0F, 0xAA, 0xFF):     # whatever RHYTHM leaves
            self.assertTrue(tl.drum_steps(self.LINE, reg, hand)[2], hex(reg))

    def test_a_hand_step_survives_a_lane_that_prunes_everything(self):
        # lane_filter prunes the GENERATED line, which is the argument the
        # writer already makes for the subtractive register. It has to hold
        # for the additive one too.
        pruned = (False,) * 8
        _, hand, _ = tl.drum_tap(self.ALL_KEPT, 0, 5, False)
        self.assertTrue(tl.drum_steps(pruned, self.ALL_KEPT, hand)[5])

    def test_a_removed_step_still_cannot_be_revived_by_the_generator(self):
        # The other half, unchanged: a step tapped OUT stays out however busy
        # the line gets.
        reg, hand, _ = tl.drum_tap(self.ALL_KEPT, 0, 0, True)
        busy = (True,) * 8
        self.assertFalse(tl.drum_steps(busy, reg, hand)[0])

    def test_only_the_pattern_s_own_bits_are_read(self):
        # A 12-step triplet division must not pick up hand bits 12-15 left
        # behind by a 16-step one, exactly as the subtractive register says.
        short = (False,) * 4
        self.assertEqual(len(tl.drum_steps(short, self.ALL_KEPT, 0xFFFF)), 4)

    def test_the_hand_register_is_drum_only(self):
        self.assertIn("hand_reg", tl.default_channel_state("drum"))
        self.assertNotIn("hand_reg", tl.default_channel_state("voice"))
        self.assertEqual(tl.default_channel_state("drum")["hand_reg"], 0)



if __name__ == "__main__":
    unittest.main()


class TestTwoGenerators(unittest.TestCase):
    """MELODY and RHYTHM: one Turing register per voice for pitch, one for
    which steps sound. Replaces DENSITY, which set how many steps sounded but
    never which - the owner's actual need was to tap steps 1 and 9 and evolve
    only the notes on them."""

    def test_the_rhythm_register_is_one_bit_per_step(self):
        # Bit N set means step N sounds. 16 bits covers every division:
        # step_count() is 16 straight, 12 triplet, and never more.
        self.assertEqual(tl.rhythm_mask(0b0000001000000010, 16),
                         tuple(i in (1, 9) for i in range(16)))

    def test_a_shorter_pattern_reads_only_its_own_bits(self):
        # A triplet division has 12 steps; bits 12-15 must not leak in.
        self.assertEqual(len(tl.rhythm_mask(0xFFFF, 12)), 12)
        self.assertTrue(all(tl.rhythm_mask(0xFFFF, 12)))

    def test_no_bits_set_is_a_silent_channel(self):
        self.assertEqual(tl.rhythm_mask(0, 16), tuple([False] * 16))

    def test_locking_rhythm_freezes_the_steps_exactly(self):
        # mutate() at chance 0 is the identity over a full rotation. That is
        # what makes LOCK exact rather than approximate, and it has to hold for
        # the rhythm register the same way it holds for the pitch one.
        reg = 0b0000001000000010
        self.assertEqual(tl.mutate(reg, 16, 0.0), reg)

    def test_evolving_rhythm_keeps_step_positions_and_flips_bits(self):
        # The knob must read as "steps appear and disappear", NOT as a
        # rotation - rotating the melody is a separate request and this must
        # not quietly consume it. A full rotation returns to the same
        # positions, so any difference is a flipped bit, never a shift.
        reg = 0b0000001000000010
        flipped = tl.mutate(reg, 16, 1.0, rng=lambda: 0.0)   # flip every time
        self.assertNotEqual(flipped, reg)
        rotations = {tl.rotate(reg, 16, n) for n in range(16)}
        self.assertNotIn(flipped, rotations - {reg})

    def test_toggling_a_step_flips_exactly_one_bit(self):
        self.assertEqual(tl.rhythm_toggle(0, 3), 0b1000)
        self.assertEqual(tl.rhythm_toggle(0b1000, 3), 0)

    def test_toggling_leaves_every_other_step_alone(self):
        reg = 0b0000001000000010
        for step in range(16):
            out = tl.rhythm_toggle(reg, step)
            self.assertEqual(out ^ reg, 1 << step, f"step {step}")


class TestDensityMigration(unittest.TestCase):
    """A snapshot saved before this change has `density` and no rhythm
    register. It must sound IDENTICAL after the change - the CHANCE/SWING law
    applied before it bites, not after."""

    def test_seeding_reproduces_the_old_mask_exactly(self):
        for density in (0, 25, 50, 75, 100):
            for reg in (0b10110011, 0b11111111, 0b00000001):
                old = tl.gate_mask(reg, 8, 16, density / 100.0)
                seeded = tl.rhythm_seed(reg, 8, 16, density)
                self.assertEqual(tl.rhythm_mask(seeded, 16), old,
                                 f"register {reg:08b} density {density}")

    def test_full_density_seeds_every_step(self):
        self.assertEqual(tl.rhythm_mask(tl.rhythm_seed(0b10110011, 8, 16, 100), 16),
                         tuple([True] * 16))

    def test_zero_density_seeds_silence(self):
        self.assertEqual(tl.rhythm_seed(0b10110011, 8, 16, 0), 0)

    def test_a_new_voice_starts_with_every_step_sounding_and_locked(self):
        # Exactly what density=100 and random=0 gave before.
        st = tl.default_channel_state("voice")
        self.assertEqual(tl.rhythm_mask(st["rhythm_reg"], 16), tuple([True] * 16))
        self.assertEqual(st["rhythm"], 0)
        self.assertEqual(st["random"], 0)

    def test_density_is_gone_from_a_fresh_voice(self):
        self.assertNotIn("density", tl.default_channel_state("voice"))


class TestGeneratorSurface(unittest.TestCase):
    """The two generators must read as one idea on the panel: MELODY and
    RHYTHM side by side, each with LOCK at zero. They sat on encoders 3 and 4
    of the voice STEP page until 2026-09-01 and are on encoders 3 and 4 of the
    voice AUTO page now - the pair moved together, which is the point."""

    def test_the_voice_auto_page_names_both_generators(self):
        verbs = _page("AUTO", "voice", "AUTO")["verbs"]
        self.assertEqual(verbs[2], "random")     # MELODY keeps its state key
        self.assertEqual(verbs[3], "rhythm")     # right beside it
        self.assertNotIn("density", verbs)

    def test_the_columns_are_labelled_melody_and_rhythm(self):
        desc = _page("AUTO", "voice", "AUTO")
        cols = tl.columns(desc, "voice", _voice_view())
        self.assertEqual(cols[2]["name"], "MELODY")
        self.assertEqual(cols[3]["name"], "RHYTHM")

    def test_the_density_spread_page_became_a_rhythm_lens(self):
        # WAS test_the_density_spread_page_became_a_rhythm_page. The spread
        # page itself went with all the others on 2026-09-01; what it showed
        # is the lens over RHYTHM, and the verb it draws comes from VERB_COLS
        # rather than the SPREAD_SPECS table the lens replaced.
        self.assertEqual(tl.lens_verb("rhythm"), "rhythm")
        self.assertEqual(tl.lens_desc("rhythm")["verb"], "rhythm")
        self.assertIn("rhythm", tl.VERB_COLS)
        self.assertNotIn("density", tl.VERB_COLS)

    def test_rhythm_hands_the_pattern_back_only_when_moved_off_lock(self):
        # Same rule RANDOM already has: turning it DOWN to LOCK must not be
        # destructive, or the one gesture that says "stop changing my pattern"
        # would destroy it.
        self.assertTrue(tl.hands_back("voice", "rhythm", 40))
        self.assertFalse(tl.hands_back("voice", "rhythm", 0))

    def test_rhythm_is_not_modulatable(self):
        # It rewrites the whole pattern through _apply_generator, which is
        # EXACTLY the velo defect that destroyed a recorded take every 200ms
        # unattended. MOD_TIMBRE is an allow-list so this is refused by
        # default - asserted anyway, because that defect reached the hardware
        # gate through a wrong deny list.
        self.assertFalse(tl.mod_allowed("rhythm"))
        self.assertFalse(tl.mod_allowed("random"))


class TestVerbColumnAlignment(unittest.TestCase):
    """The verbs tuple decides which encoder WRITES what; _columns_inner's
    list decides what each encoder DRAWS. Nothing checks at runtime that they
    agree, so a reorder of one without the other would silently point a knob
    at a parameter its own label denies. This is that check."""

    # verb -> the name its column must draw. Deliberately explicit: `random`
    # draws MELODY and `div` draws DIVIDE, so a mechanical comparison would
    # not catch a swap.
    #
    # Reordered 2026-09-01 by the collapse from 24 pages to 9: MELODY and
    # RHYTHM left this page for AUTO, and CHANCE and SWING came back onto it
    # off the spread pages that became the lens.
    VOICE_STEP = (
        ("div", "DIVIDE"), ("length", "LENGTH"), ("gate", "GATE"),
        ("octave", "OCTAVE"), ("chord", "CHORD"), ("velo", "VELO"),
        ("chance", "CHANCE"), ("swing", "SWING"),
    )

    # The same check on the page the two generators moved to.
    VOICE_AUTO = (
        ("rule", "RULE"), ("model", "MODEL"), ("random", "MELODY"),
        ("rhythm", "RHYTHM"), ("move", "MOVE"), ("phrase", "PHRASE"),
        ("fill", "FILL"), ("exit", "EXIT"),
    )

    def test_every_voice_step_column_draws_its_own_verb(self):
        desc = tl.PAGE_RINGS[("STEP", "voice")][0]
        cols = tl.columns(desc, "voice", _voice_view())
        for index, (verb, name) in enumerate(self.VOICE_STEP):
            self.assertEqual(desc["verbs"][index], verb, f"verb at {index}")
            self.assertEqual(cols[index]["name"], name, f"name at {index}")

    def test_every_voice_auto_column_draws_its_own_verb(self):
        desc = _page("AUTO", "voice", "AUTO")
        cols = tl.columns(desc, "voice", _voice_view())
        for index, (verb, name) in enumerate(self.VOICE_AUTO):
            self.assertEqual(desc["verbs"][index], verb, f"verb at {index}")
            self.assertEqual(cols[index]["name"], name, f"name at {index}")

    def test_the_two_generators_are_adjacent(self):
        # The owner's reason for the layout: they are one idea, so the hand
        # finds them together. A reorder that separates them is a regression.
        # They live on AUTO since 2026-09-01, together, which is what the
        # collapse had to preserve.
        verbs = _page("AUTO", "voice", "AUTO")["verbs"]
        self.assertEqual(abs(verbs.index("random") - verbs.index("rhythm")), 1)


class TestStateUpgrade(unittest.TestCase):
    """A state dict out of an older snapshot, brought up to the current key
    set.

    The bug this exists to stop: a voice stash written before the rhythm
    generator carries DENSITY and no `rhythm`/`rhythm_reg`. It was restored
    verbatim, so the first SHIFT+GRID pulled it into self.state, columns()
    indexed state["rhythm"], and the KeyError killed the playhead poll thread
    - every voice stopped evolving for the rest of the session with nothing on
    the surface saying so."""

    # Exactly the keys measured in 030-maschine-house.zss, channel 0.
    PRE_RHYTHM_VOICE = {
        "chance": 100, "cutoff": 70, "decay": 40, "delay": 0, "density": 60,
        "env": 64, "gate": 40, "length": 8, "level": 19, "octave": 0,
        "preset": "Bass", "random": 25, "range": 2, "register": 0b10110011,
        "reso": 32, "reverb": 0, "ring": [], "swing": 50, "velo": 110,
    }

    def test_a_pre_rhythm_voice_gains_every_current_key(self):
        out = tl.upgrade_state("voice", self.PRE_RHYTHM_VOICE, 16)
        for key in tl.default_channel_state("voice"):
            self.assertIn(key, out, f"missing {key}")

    def test_it_keeps_what_the_snapshot_said(self):
        out = tl.upgrade_state("voice", self.PRE_RHYTHM_VOICE, 16)
        self.assertEqual(out["register"], 0b10110011)
        self.assertEqual(out["random"], 25)
        self.assertEqual(out["cutoff"], 70)
        self.assertEqual(out["preset"], "Bass")

    def test_rhythm_is_seeded_from_density_not_defaulted(self):
        # 0xFFFF would turn a sparse line into every step sounding. The seed
        # runs the same gate_mask the old writer did, so it sounds identical.
        out = tl.upgrade_state("voice", self.PRE_RHYTHM_VOICE, 16)
        self.assertEqual(out["rhythm_reg"],
                         tl.rhythm_seed(0b10110011, 8, 16, 60))
        # A snapshot made before rhythm evolution existed was not evolving.
        self.assertEqual(out["rhythm"], 0)

    def test_a_current_dict_is_unchanged(self):
        saved = dict(tl.default_channel_state("voice"))
        saved["ring"] = []
        saved.pop("pending")
        saved["rhythm"] = 40
        saved["rhythm_reg"] = 0x00FF
        out = tl.upgrade_state("voice", saved, 16)
        self.assertEqual(out["rhythm"], 40)
        self.assertEqual(out["rhythm_reg"], 0x00FF)

    def test_a_drum_dict_survives(self):
        saved = {"chance": 100, "delay": 0, "kit": "Techno", "level": 19,
                 "reverb": 0, "sample": "BD", "swing": 50, "velo": 110}
        out = tl.upgrade_state("drum", saved, 16)
        self.assertEqual(out["kit"], "Techno")
        for key in tl.default_channel_state("drum"):
            self.assertIn(key, out, f"missing {key}")

    def test_retired_keys_are_dropped(self):
        # DENSITY was retired by the rhythm generator and nothing reads it.
        out = tl.upgrade_state("voice", self.PRE_RHYTHM_VOICE, 16)
        self.assertNotIn("density", out)

    def test_ring_comes_back_a_bounded_deque(self):
        saved = dict(self.PRE_RHYTHM_VOICE, ring=[(1, 2), (3, 4)])
        out = tl.upgrade_state("voice", saved, 16)
        self.assertIsInstance(out["ring"], deque)
        self.assertEqual(out["ring"].maxlen, 4)

    def test_pending_comes_back_empty(self):
        # It holds parameters waiting for the next bar, and a snapshot load
        # has no bar to wait for.
        saved = dict(self.PRE_RHYTHM_VOICE, pending={"div"})
        out = tl.upgrade_state("voice", saved, 16)
        self.assertEqual(out["pending"], set())

    def test_the_upgraded_dict_survives_columns(self):
        # The actual failure: columns() on the restored dict.
        out = tl.upgrade_state("voice", self.PRE_RHYTHM_VOICE, 16)
        for mode in ("STEP", "CONTROL", "MIXER"):
            for desc in tl.PAGE_RINGS.get((mode, "voice"), ()):
                if desc["shape"] == tl.SHAPE_SPREAD:
                    # SHAPE_SPREAD reads eight channels, not one - a
                    # different argument shape, not a different state.
                    continue
                # `div` lives in the driver, not the state dict - the view
                # merges the two, so the test does the same.
                tl.columns(desc, "voice", dict(out, div=1))


class TestThrottle(unittest.TestCase):
    """The rate limiter behind every error log on the 30 Hz poll thread.

    Without it, one persistent fault writes 30 journal lines a second for as
    long as it lasts. With it, a NEW message is always reported - with its
    traceback - and a repeat is counted and reported at most once per window."""

    def setUp(self):
        self.seen = {}

    def test_a_new_message_is_always_emitted_and_marked_fresh(self):
        emit, suppressed, fresh = tl.throttle(self.seen, "poll", "boom", 0.0, 30.0)
        self.assertTrue(emit)
        self.assertTrue(fresh)
        self.assertEqual(suppressed, 0)

    def test_an_immediate_repeat_is_suppressed(self):
        tl.throttle(self.seen, "poll", "boom", 0.0, 30.0)
        emit, _, fresh = tl.throttle(self.seen, "poll", "boom", 0.1, 30.0)
        self.assertFalse(emit)
        self.assertFalse(fresh)

    def test_a_repeat_after_the_window_reports_the_count(self):
        tl.throttle(self.seen, "poll", "boom", 0.0, 30.0)
        for i in range(1, 5):
            tl.throttle(self.seen, "poll", "boom", i * 0.1, 30.0)
        emit, suppressed, fresh = tl.throttle(self.seen, "poll", "boom", 31.0, 30.0)
        self.assertTrue(emit)
        self.assertFalse(fresh)          # no second traceback for the same fault
        self.assertEqual(suppressed, 5)  # the four above plus this one

    def test_the_count_resets_after_a_report(self):
        tl.throttle(self.seen, "poll", "boom", 0.0, 30.0)
        tl.throttle(self.seen, "poll", "boom", 0.1, 30.0)
        tl.throttle(self.seen, "poll", "boom", 31.0, 30.0)
        emit, suppressed, _ = tl.throttle(self.seen, "poll", "boom", 62.0, 30.0)
        self.assertTrue(emit)
        self.assertEqual(suppressed, 1)

    def test_a_different_message_is_fresh_again(self):
        tl.throttle(self.seen, "poll", "boom", 0.0, 30.0)
        emit, _, fresh = tl.throttle(self.seen, "poll", "bang", 0.1, 30.0)
        self.assertTrue(emit)
        self.assertTrue(fresh)

    def test_keys_do_not_shadow_each_other(self):
        # One failing channel must not silence the report for another.
        tl.throttle(self.seen, "wrap 5", "boom", 0.0, 30.0)
        emit, _, fresh = tl.throttle(self.seen, "wrap 6", "boom", 0.1, 30.0)
        self.assertTrue(emit)
        self.assertTrue(fresh)


class TestPadOverlay(unittest.TestCase):
    """The pad-overlay policy: who owns the sixteen pads, and what they show.

    Three features want the same takeover — probability on SHIFT, the rate/shape
    legend on MOD, the ring map on NAVIGATE. Deciding it once here, in the
    unit-tested half, is the whole point: the driver cannot be imported on WSL,
    so anything left in the driver is checked by py_compile and the rig only."""

    def test_no_modifier_means_no_overlay(self):
        self.assertIsNone(tl.overlay_owner(shift=False, mod=False, navigate=False))

    def test_shift_owns_the_pads(self):
        self.assertEqual(tl.overlay_owner(shift=True, mod=False, navigate=False), "shift")

    def test_shift_beats_a_latched_mod(self):
        # MOD latches, so MOD-active and SHIFT-held genuinely co-occur. Owner's
        # rule, 2026-08-19: a momentary gesture takes the pads from a latched
        # state and gives them back on release.
        self.assertEqual(tl.overlay_owner(shift=True, mod=True, navigate=False), "shift")

    def test_mod_owns_the_pads_when_shift_is_up(self):
        self.assertEqual(tl.overlay_owner(shift=False, mod=True, navigate=False), "mod")

    def test_navigate_ranks_below_both(self):
        self.assertEqual(tl.overlay_owner(shift=False, mod=False, navigate=True), "navigate")
        self.assertEqual(tl.overlay_owner(shift=True, mod=False, navigate=True), "shift")
        self.assertEqual(tl.overlay_owner(shift=False, mod=True, navigate=True), "mod")


class TestChanceLadder(unittest.TestCase):
    """SHIFT + pad steps a step's play chance down a short ladder.

    A ladder rather than a hold-and-turn: pads are discrete on this surface and
    encoders carry magnitudes, and four rungs are four brightness levels, which
    the pad painter can already show."""

    def test_it_descends(self):
        self.assertEqual(tl.chance_ladder(100), 75)
        self.assertEqual(tl.chance_ladder(75), 50)
        self.assertEqual(tl.chance_ladder(50), 25)

    def test_it_wraps_to_full(self):
        # Back to 100, never to 0: a step you cannot hear is indistinguishable
        # from a step that is off, and "a silent channel must say why".
        self.assertEqual(tl.chance_ladder(25), 100)

    def test_an_unrecognised_value_snaps_to_the_nearest_rung(self):
        # Chance is also settable from the touchscreen and from older snapshots,
        # so the ladder must not get stuck on a value it did not produce.
        self.assertEqual(tl.chance_ladder(90), 75)
        self.assertEqual(tl.chance_ladder(60), 50)
        self.assertEqual(tl.chance_ladder(10), 100)

    def test_every_rung_is_reachable_by_pressing(self):
        seen, v = set(), 100
        for _ in range(8):
            seen.add(v)
            v = tl.chance_ladder(v)
        self.assertEqual(seen, {100, 75, 50, 25})


class TestProbabilityPads(unittest.TestCase):
    """What the pads draw while SHIFT is held."""

    def test_brightness_tracks_chance(self):
        full = tl.probability_pad(True, 100)[1]
        half = tl.probability_pad(True, 50)[1]
        low = tl.probability_pad(True, 25)[1]
        self.assertGreater(full, half)
        self.assertGreater(half, low)

    def test_no_rung_is_white(self):
        # White is the playhead, drawn over the overlay. Standing rule.
        for chance in tl.CHANCE_RUNGS:
            self.assertNotEqual(tl.probability_pad(True, chance)[0], 0xFFFFFF)

    def test_full_chance_is_full_scale(self):
        # The daemon halves brightness (set_rgb_light: brightness * 0.5), so
        # 2.0 is full. Measured in the daemon, not guessed.
        self.assertAlmostEqual(tl.probability_pad(True, 100)[1], 2.0)

    def test_an_off_step_is_dark_whatever_its_chance(self):
        # An off step has no note to roll for; drawing it lit would claim a
        # probability that cannot fire.
        self.assertEqual(tl.probability_pad(False, 100)[1], 0.0)

    def test_a_low_chance_step_is_still_visibly_lit(self):
        # The silent-channel law: a step at the bottom rung must not read as
        # "off". It is dimmer, never dark.
        self.assertGreater(tl.probability_pad(True, 25)[1], 0.0)

    def test_it_never_paints_white(self):
        # White belongs to the playhead - owner's standing rule, 2026-08-19.
        for chance in (100, 75, 50, 25):
            self.assertNotEqual(tl.probability_pad(True, chance)[0], 0xFFFFFF)

    def test_every_rung_has_its_own_hue(self):
        # REVERSED 2026-08-19 by the hardware. This test used to assert ONE hue
        # across all rungs, on the theory that brightness carried the value and
        # a moving hue would be a second encoding of the same thing. On the pads
        # the four brightness levels were "nearly indistinguishable" - LED bytes
        # 111/159/207/255 look like ~1.32:1 to an eye that perceives brightness
        # as roughly a cube root. Redundant coding is now deliberate.
        hues = [tl.probability_pad(True, c)[0] for c in (100, 75, 50, 25)]
        self.assertEqual(len(set(hues)), 4)

    def test_brightness_still_falls_with_chance(self):
        # The second code, agreeing with the first. Either alone reads.
        levels = [tl.probability_pad(True, c)[1] for c in (100, 75, 50, 25)]
        self.assertEqual(levels, sorted(levels, reverse=True))

    def test_a_value_between_rungs_shows_the_rung_below(self):
        # Chance is settable from the touchscreen and arrives from old
        # snapshots; it must still show a look the ladder can produce.
        self.assertEqual(tl.probability_pad(True, 90), tl.probability_pad(True, 75))
        self.assertEqual(tl.probability_pad(True, 10), tl.probability_pad(True, 25))

    def test_the_hue_is_not_a_group_colour(self):
        # Group colours are not reserved during an overlay, but reusing one
        # while the step picture is suppressed still invites misreading.
        self.assertNotIn(tl.probability_pad(True, 100)[0],
                         {c for _, _, _, c, _, _ in tl.CHANNELS})


class TestModLegend(unittest.TestCase):
    """The MOD pad legend: while MOD owns the pads they stop drawing steps and
    become the modulation menu they already secretly are.

    Today the pads LIE - a pad hit under MOD sets a rate or a shape while the
    pads still draw the step picture. Gesture and display disagree, which is the
    one thing this surface is not allowed to do."""

    def test_the_band_is_monotonic_left_to_right(self):
        # "Further right and further down = faster" must stay true even though
        # the absolute rate does not.
        p = tl.MOD_LEGEND_PERIODS
        self.assertEqual(len(p), len(tl.MOD_RATES))
        self.assertEqual(list(p), sorted(p, reverse=True))

    def test_the_band_is_legible_at_both_ends(self):
        # MOD_RATES spans 250:1 - 31 s per cycle down to 0.12 s at 124 BPM.
        # The slow end is indistinguishable from a static LED; the fast end is
        # 8.3 Hz against a 30 Hz repaint, which aliases into jitter rather than
        # reading as speed. The band is a LEGIBILITY MAP, not a measurement.
        self.assertLessEqual(max(tl.MOD_LEGEND_PERIODS), 3.0)
        self.assertGreaterEqual(min(tl.MOD_LEGEND_PERIODS), 0.30)

    def test_unbound_means_still_pads(self):
        # _mod_pad returns immediately when nothing is bound, so the gesture is
        # inert. Pads dancing while nothing can happen is exactly the sin the
        # dashed tab row exists to prevent.
        a = [tl.mod_legend_pad(i, 0.0, 3, "tri", bound=False) for i in range(16)]
        b = [tl.mod_legend_pad(i, 0.7, 3, "tri", bound=False) for i in range(16)]
        self.assertEqual(a, b)
        self.assertEqual(len({x[1] for x in a}), 1)

    def test_bound_rate_pads_move(self):
        over_time = {tl.mod_legend_pad(0, t / 10.0, 3, "tri", bound=True)[1]
                     for t in range(20)}
        self.assertGreater(len(over_time), 1)

    def test_the_selected_rate_is_steady_at_full(self):
        # Owner, 2026-08-19: the active pad is LIT, not swinging widest. An
        # amplitude cannot be compared across pads moving at different speeds,
        # so "widest swing" was a mark you had to work out. Steady and full is
        # read at a glance, and it is the only still pad on the grid.
        sel = {tl.mod_legend_pad(5, t / 20.0, 5, "tri", bound=True)[1] for t in range(40)}
        self.assertEqual(sel, {tl.PAD_FULL})

    def test_the_selected_shape_is_steady_at_full(self):
        sel = {tl.mod_legend_pad(12, t / 20.0, 5, "tri", bound=True)[1] for t in range(40)}
        self.assertEqual(sel, {tl.PAD_FULL})

    def test_unselected_pads_still_move(self):
        other = {tl.mod_legend_pad(6, t / 20.0, 5, "tri", bound=True)[1] for t in range(40)}
        self.assertGreater(len(other), 1)
        self.assertLess(max(other), tl.PAD_FULL)

    def test_shape_pads_fade_in_their_own_shape(self):
        # Teaches the four shapes without a word of text: tri breathes, ramp
        # saws and snaps, squ hard-blinks, s&h steps randomly.
        squ = [tl.mod_legend_pad(14, t / 30.0, 5, "squ", bound=True)[1] for t in range(60)]
        tri = [tl.mod_legend_pad(12, t / 30.0, 5, "squ", bound=True)[1] for t in range(60)]
        self.assertLessEqual(len(set(squ)), len(set(tri)))

    def test_rate_and_shape_pads_are_different_colours(self):
        self.assertNotEqual(tl.mod_legend_pad(0, 0.0, 3, "tri", bound=True)[0],
                            tl.mod_legend_pad(12, 0.0, 3, "tri", bound=True)[0])

    def test_no_pad_is_ever_white(self):
        # White is the playhead. Standing rule.
        for i in range(16):
            for t in range(10):
                self.assertNotEqual(
                    tl.mod_legend_pad(i, t / 10.0, 3, "tri", bound=True)[0], 0xFFFFFF)

    def test_brightness_is_quantised(self):
        # Fading twelve pads at 30 Hz is up to 360 pad messages a second, on a
        # daemon whose own comment records being flooded off the USB bus once.
        # Quantising means led_cache.changed() swallows most ticks.
        seen = {tl.mod_legend_pad(0, t / 200.0, 0, "tri", bound=True)[1]
                for t in range(400)}
        self.assertLessEqual(len(seen), 20)

    def test_brightness_never_exceeds_full_scale(self):
        for i in range(16):
            for t in range(40):
                self.assertLessEqual(
                    tl.mod_legend_pad(i, t / 20.0, 3, "tri", bound=True)[1], tl.PAD_FULL)


class TestOverlayIsStepwise(unittest.TestCase):
    """Does the playhead belong on top of this overlay?

    Only if the pads still MEAN steps. Under SHIFT they do - pad 3 is step 3
    with a probability - so the white sweep is useful and the framework draws it
    over the top. Under MOD they do not: pad 3 is a RATE, and a playhead marker
    on it would point at nothing. The rule is not "always draw the playhead",
    it is "draw it where the pads are still the pattern"."""

    def test_shift_is_stepwise(self):
        self.assertTrue(tl.overlay_is_stepwise("shift"))

    def test_mod_is_not_stepwise(self):
        self.assertFalse(tl.overlay_is_stepwise("mod"))

    def test_no_overlay_is_stepwise(self):
        # The ordinary step picture is the most stepwise thing there is.
        self.assertTrue(tl.overlay_is_stepwise(None))


class TestBigEncoderDelta(unittest.TestCase):
    """The big encoder's signed delta.

    CC 15 is a 16-position counter times 8, wrapping 120 -> 0. It is emitted
    from the daemon's "A8" branch as `status * 8` and NEVER passes
    send_encoder_cc, so it never meets is_encoder_jump - there is no rejection
    threshold to fight here, which the 2026-08-16 round established after a
    trap note had claimed the opposite."""

    def test_one_detent_forward(self):
        self.assertEqual(tl.big_delta(0, 8), 8)

    def test_one_detent_back(self):
        self.assertEqual(tl.big_delta(8, 0), -8)

    def test_the_wrap_forward_is_one_detent_not_fifteen(self):
        # 120 -> 0 is the counter wrapping, not a leap backwards.
        self.assertEqual(tl.big_delta(120, 0), 8)

    def test_the_wrap_back_is_one_detent(self):
        self.assertEqual(tl.big_delta(0, 120), -8)

    def test_a_fast_spin_still_reads_forward(self):
        self.assertEqual(tl.big_delta(112, 8), 24)

    def test_no_movement_is_zero(self):
        self.assertEqual(tl.big_delta(64, 64), 0)


class TestBigEncoderDetents(unittest.TestCase):
    """Turning it must step ONE page per detent, not eight."""

    def test_a_detent_is_one_step(self):
        self.assertEqual(tl.big_detents(8), (1, 0))

    def test_a_partial_turn_banks_the_remainder(self):
        steps, carry = tl.big_detents(5)
        self.assertEqual(steps, 0)
        self.assertEqual(carry, 5)

    def test_the_remainder_completes_a_detent(self):
        self.assertEqual(tl.big_detents(5 + 3), (1, 0))

    def test_backwards_works_the_same(self):
        self.assertEqual(tl.big_detents(-8), (-1, 0))
        self.assertEqual(tl.big_detents(-5), (0, -5))

    def test_a_fast_spin_gives_every_page_it_passed(self):
        # Three detents in one report must not collapse into one page.
        self.assertEqual(tl.big_detents(24), (3, 0))


class TestDriftAllowed(unittest.TestCase):
    """Drift refuses to bind on a player-owned channel — owner confirmed
    2026-08-19, settling the question that blocked drift since 2026-08-14.

    ONE PREDICATE, NOT TWO LISTS. columns() greys whatever fails this, and
    _column_dead() reads that same flag, so the painter and the refusal agree by
    construction. The `velo` defect reached the surface through a deny list that
    disagreed with the code."""

    def test_timbre_verbs_are_unaffected_by_ownership(self):
        # They do not rewrite the pattern, so a take is never at risk.
        for verb in ("level", "reverb", "delay", "cutoff"):
            self.assertTrue(tl.mod_allowed(verb, owned=False))
            self.assertTrue(tl.mod_allowed(verb, owned=True))

    def test_drift_verbs_bind_on_an_unowned_channel(self):
        for verb in ("hits", "rotate", "chance"):
            self.assertTrue(tl.mod_allowed(verb, owned=False))

    def test_drift_verbs_refuse_on_an_owned_channel(self):
        for verb in ("hits", "rotate", "chance"):
            self.assertFalse(tl.mod_allowed(verb, owned=True))

    def test_density_is_not_resurrected(self):
        # The 2026-08-14 spec named it; the rhythm generator replaced it on
        # 2026-08-16, so it is dropped rather than brought back.
        self.assertFalse(tl.mod_allowed("density", owned=False))

    def test_structure_verbs_stay_out_of_v1(self):
        # LENGTH and DIV are handback verbs too, but they change the pattern's
        # SHAPE and land through `pending`. A bar whose length changes under
        # the player is a different feature.
        for verb in ("length", "div"):
            self.assertFalse(tl.mod_allowed(verb, owned=False))

    def test_the_default_is_unowned_so_old_callers_are_unchanged(self):
        self.assertTrue(tl.mod_allowed("cutoff"))
        self.assertTrue(tl.mod_allowed("hits"))

    def test_lv2_and_fx_verbs_still_pass(self):
        self.assertTrue(tl.mod_allowed("lv2:cutoff", owned=True))
        self.assertTrue(tl.mod_allowed("fx:0:wet", owned=True))


class TestDriftIsWrapRate(unittest.TestCase):
    """Drift is applied at the pattern wrap, never on the 200 ms tick.

    A pattern verb written every 200 ms means clear() plus an addNote loop under
    the lock, five times a second, forever. That IS the velo defect."""

    def test_drift_verbs_are_named(self):
        self.assertEqual(tl.DRIFT_VERBS, frozenset({"hits", "rotate", "chance"}))

    def test_a_drift_verb_is_wrap_rate(self):
        for verb in tl.DRIFT_VERBS:
            self.assertTrue(tl.is_drift(verb))

    def test_a_timbre_verb_is_not(self):
        for verb in ("level", "reverb", "delay", "cutoff", "reso", "env", "decay"):
            self.assertFalse(tl.is_drift(verb))

    def test_plugin_verbs_are_not(self):
        self.assertFalse(tl.is_drift("lv2:cutoff"))
        self.assertFalse(tl.is_drift("fx:0:wet"))


class TestKitWindow(unittest.TestCase):
    """SP8 — RANGE confines the Turing kit walk to part of the kit.

    kit_line() mapped the register across EVERY note in the kit, so a hats
    channel switched to Turing wandered onto kicks. RANGE now sets a window
    width, centred on the channel's own note, so narrowing closes in around the
    drum the channel already plays."""

    KIT = [36, 38, 39, 42, 44, 46, 49, 51]      # eight notes, kick .. crash

    def test_range_4_is_the_whole_kit_and_is_the_default(self):
        # THE COMPATIBILITY RULE: drum RANGE starts at maximum, so existing
        # snapshots sound IDENTICAL the day this ships. SP8 is a pure option.
        wide = tl.kit_line(0b10110011, 8, 16, self.KIT, kit_range=4, centre=42)
        old = tl.kit_line(0b10110011, 8, 16, self.KIT)
        self.assertEqual(wide, old)

    def test_narrowing_shrinks_the_set_of_notes_used(self):
        wide = set(tl.kit_line(0b10110011, 8, 16, self.KIT, kit_range=4, centre=42))
        narrow = set(tl.kit_line(0b10110011, 8, 16, self.KIT, kit_range=1, centre=42))
        self.assertLess(len(narrow), len(wide))

    def test_the_window_is_centred_on_the_channels_own_note(self):
        # A hats channel narrowed stays on hats rather than sliding to kicks.
        notes = set(tl.kit_line(0b10110011, 8, 16, self.KIT, kit_range=1, centre=44))
        self.assertTrue(all(abs(self.KIT.index(n) - self.KIT.index(44)) <= 1 for n in notes),
                        notes)

    def test_the_narrowest_window_still_makes_a_sound(self):
        # Never empty: a silent channel must say why, and an empty window would
        # be silence with nothing to explain it.
        notes = tl.kit_line(0b10110011, 8, 16, self.KIT, kit_range=1, centre=42)
        self.assertTrue(notes)
        self.assertTrue(all(n in self.KIT for n in notes))

    def test_a_centre_outside_the_kit_still_works(self):
        # The channel's note can be absent from the kit list after a kit swap.
        notes = tl.kit_line(0b10110011, 8, 16, self.KIT, kit_range=2, centre=99)
        self.assertTrue(notes)

    def test_an_empty_kit_is_still_empty(self):
        self.assertEqual(tl.kit_line(0b10110011, 8, 16, [], kit_range=1, centre=42), [])

    def test_old_callers_are_unchanged(self):
        # Default arguments mean every existing call site keeps its meaning.
        self.assertEqual(tl.kit_line(179, 8, 16, self.KIT),
                         tl.kit_line(179, 8, 16, self.KIT, kit_range=4, centre=None))


class TestDrumRangeDefault(unittest.TestCase):
    """RANGE already exists and voices use it as octave spread, defaulting to 2
    of 4. Reusing that number on drums would make every existing channel walk
    HALF ITS KIT the moment SP8 lands. Drum RANGE is its own value and starts
    at maximum."""

    def test_a_voice_keeps_its_octave_spread_default(self):
        self.assertEqual(tl.default_channel_state("voice")["range"], 2)

    def test_a_drum_starts_at_the_whole_kit(self):
        self.assertEqual(tl.default_channel_state("drum")["range"], 4)


class TestRatchet(unittest.TestCase):
    """SP10 step 3 — RATCHET fills the drum STEP page's dead eighth column.
    A step fires 2, 3 or 4 times inside its own slot.

    Implemented as zynseq's NATIVE STUTTER, not as stacked notes: Pattern::
    addEvent deletes overlapping events with the same note, so three addNote
    calls on one step leave one note, not three. The event already carries a
    stutter count and duration, and the .so exports setStutterCount /
    setStutterDur - a ratchet is what those fields are for."""

    def test_the_drum_step_page_has_a_ratchet_column(self):
        # Slot 7 since 2026-09-01, was 8: RHYTHM left this page for AUTO and
        # SWING came back off its spread page into the last slot.
        desc = tl.PAGE_RINGS[("STEP", "drum")][0]
        self.assertEqual(desc["verbs"][6], "ratchet")

    def test_one_is_off(self):
        self.assertEqual(tl.ratchet_stutter(1, clocks_per_step=24), (0, 0))

    def test_two_fires_twice_in_the_slot(self):
        count, dur = tl.ratchet_stutter(2, clocks_per_step=24)
        self.assertEqual(count, 2)
        # cps / 2n, not cps / n: a retrigger costs a note-off AND a note-on.
        self.assertEqual(dur, 6)

    def test_three_divides_the_slot_three_ways(self):
        count, dur = tl.ratchet_stutter(3, clocks_per_step=24)
        self.assertEqual(count, 3)
        self.assertEqual(dur, 4)

    def test_four_divides_the_slot_four_ways(self):
        self.assertEqual(tl.ratchet_stutter(4, clocks_per_step=24), (4, 3))

    def test_the_duration_never_rounds_to_zero(self):
        # A zero-length stutter is a step that makes no sound - silence with
        # nothing to explain it, which this instrument must never produce.
        for cps in (1, 2, 3, 5, 7):
            for n in (2, 3, 4):
                self.assertGreaterEqual(tl.ratchet_stutter(n, cps)[1], 1)

    def test_a_ratchet_column_reads_off_at_one(self):
        state = _drum_step_state()
        state["ratchet"] = 1
        cols = tl.columns(tl.PAGE_RINGS[("STEP", "drum")][0], "drum", state)
        self.assertEqual(cols[6]["value"], "OFF")

    def test_a_ratchet_column_shows_its_count(self):
        state = _drum_step_state()
        state["ratchet"] = 3
        cols = tl.columns(tl.PAGE_RINGS[("STEP", "drum")][0], "drum", state)
        self.assertIn("3", cols[6]["value"])

    def test_a_drum_starts_with_ratchet_off(self):
        self.assertEqual(tl.default_channel_state("drum")["ratchet"], 1)


class TestReroll(unittest.TestCase):
    """SP10 step 3 — SCENE rerolls the drum channels, PATTERN the voices.

    Two floors are non-negotiable: a reroll may never leave a channel silent
    with nothing to say why. Silence is the failure this instrument is built to
    explain, and a reroll that mutes a channel by accident is that failure with
    a new cause."""

    def test_hits_never_reach_zero(self):
        rng = random.Random(1)
        for _ in range(200):
            new = tl.reroll_drum(steps=16, rng=rng.random)
            self.assertGreaterEqual(new["hits"], 1)
            self.assertLessEqual(new["hits"], 16)

    def test_rotation_stays_inside_the_pattern(self):
        rng = random.Random(2)
        for _ in range(200):
            new = tl.reroll_drum(steps=16, rng=rng.random)
            self.assertTrue(0 <= new["rotate"] < 16)

    def test_a_voice_reroll_keeps_chance_above_the_floor(self):
        rng = random.Random(3)
        for _ in range(200):
            new = tl.reroll_voice(rng=rng.random)
            self.assertGreaterEqual(new["chance"], tl.REROLL_CHANCE_FLOOR)
            self.assertLessEqual(new["chance"], 100)

    def test_a_voice_reroll_never_empties_the_rhythm_register(self):
        # No bits set is the "no steps at all" silence the tab row exists to
        # explain. A reroll must not create it.
        rng = random.Random(4)
        for _ in range(200):
            new = tl.reroll_voice(rng=rng.random)
            self.assertNotEqual(new["rhythm_reg"] & 0xFFFF, 0)

    def test_a_voice_reroll_always_LOCKS_melody(self):
        # REVERSED 2026-08-19 by the owner. This asserted that RANDOM was
        # rerolled too, straight from the 2026-08-14 spec - but that let a
        # pattern button switch a held line into an evolving one, which is a
        # mode change nobody asked for by pressing it. A reroll now hands you a
        # new line and freezes it.
        rng = random.Random(5)
        vals = {tl.reroll_voice(rng=rng.random)["random"] for _ in range(50)}
        self.assertEqual(vals, {0})

    def test_a_voice_reroll_always_LOCKS_rhythm_too(self):
        # Owner, 2026-09-02: the same argument that locks MELODY. This reroll
        # hands the channel a NEW rhythm register, and leaving RHYTHM running
        # meant that register started evolving away before it had been heard.
        rng = random.Random(7)
        vals = {tl.reroll_voice(rng=rng.random)["rhythm"] for _ in range(50)}
        self.assertEqual(vals, {0})

    def test_a_voice_reroll_locks_BOTH_generators(self):
        # Stated as one assertion because the asymmetry was an omission, not a
        # decision, and this is the shape that would have caught it.
        new = tl.reroll_voice(rng=random.Random(8).random)
        self.assertEqual((new["random"], new["rhythm"]), (0, 0))

    def test_a_voice_reroll_touches_exactly_four_things(self):
        # A reroll that grew a fifth field without anybody noticing is a
        # reroll whose undo is incomplete - the driver saves these four keys
        # and replays them, so the sets have to match.
        self.assertEqual(sorted(tl.reroll_voice(rng=random.Random(9).random)),
                         ["chance", "random", "rhythm", "rhythm_reg"])

    def test_a_tiny_pattern_still_gets_a_hit(self):
        # step_count is 12 on a triplet division and could be smaller still.
        for steps in (1, 2, 3, 4):
            new = tl.reroll_drum(steps=steps, rng=random.Random(6).random)
            self.assertGreaterEqual(new["hits"], 1)
            self.assertLessEqual(new["hits"], steps)


class TestRerollScope(unittest.TestCase):
    """Owner, 2026-08-19, replacing "the button owns a fixed set of channels".

    A bare press rerolls the ACTIVE group only. SHIFT rerolls every channel of
    that button's ENGINE type - SCENE the samplers, PATTERN the synths.

    ENGINE, not kind, and that is the whole point: a drum sampler running in
    Turing mode is still a SAMPLER, so it answers to SCENE. Asking for a global
    synth sequence change must not hand you a new drum pattern as well."""

    # channel -> is it a sampler engine
    RIG = {0: True, 1: True, 2: True, 3: True, 4: True,
           5: False, 6: False, 7: False}
    ALL_GEN = {i: "gen" for i in range(8)}

    def test_a_bare_press_takes_the_active_group_only(self):
        self.assertEqual(
            tl.reroll_scope("scene", self.RIG, self.ALL_GEN, selected=2, shift=False),
            (2,))

    def test_a_bare_press_works_on_a_voice_too(self):
        self.assertEqual(
            tl.reroll_scope("pattern", self.RIG, self.ALL_GEN, selected=6, shift=False),
            (6,))

    def test_the_button_does_not_gate_a_bare_press(self):
        # Pressing either button acts on what you are looking at. Refusing
        # because "this is the drum button and you are on a voice" would be a
        # rule the player has to remember for no benefit.
        self.assertEqual(
            tl.reroll_scope("scene", self.RIG, self.ALL_GEN, selected=6, shift=False),
            (6,))

    def test_shift_PATTERN_takes_every_sampler(self):
        self.assertEqual(
            tl.reroll_scope("pattern", self.RIG, self.ALL_GEN, selected=6, shift=True),
            (0, 1, 2, 3, 4))

    def test_shift_SCENE_takes_every_synth(self):
        self.assertEqual(
            tl.reroll_scope("scene", self.RIG, self.ALL_GEN, selected=0, shift=True),
            (5, 6, 7))

    def test_a_sampler_in_turing_mode_still_answers_to_SCENE(self):
        # The case that motivated the change. Channel 4 is a drum sampler
        # switched to voice behaviour; it is still a sampler, so SHIFT+PATTERN
        # must leave it alone and SHIFT+SCENE must include it.
        self.assertIn(4, tl.reroll_scope("pattern", self.RIG, self.ALL_GEN, 0, True))
        self.assertNotIn(4, tl.reroll_scope("scene", self.RIG, self.ALL_GEN, 0, True))

    def test_owned_channels_are_skipped_either_way(self):
        owners = dict(self.ALL_GEN)
        owners.update({2: "player", 6: "player"})
        self.assertEqual(tl.reroll_scope("pattern", self.RIG, owners, 0, True), (0, 1, 3, 4))
        self.assertEqual(tl.reroll_scope("pattern", self.RIG, owners, 2, False), ())

    def test_an_all_synth_rig_gives_PATTERN_nothing(self):
        rig = {i: False for i in range(8)}
        self.assertEqual(tl.reroll_scope("pattern", rig, self.ALL_GEN, 0, True), ())


class TestSwitchSpec(unittest.TestCase):
    """An enumerated or toggled port is a SWITCH. What counts as one is
    decided here rather than in the driver, which cannot be imported on WSL."""

    def test_a_toggle_is_a_switch(self):
        self.assertEqual(tl.switch_spec(["off", "on"], [0, 1]),
                         (("off", "on"), (0, 1)))

    def test_an_enum_is_a_switch(self):
        spec = tl.switch_spec(["LP24", "LP12", "BP", "HP"], [0, 1, 2, 3])
        self.assertEqual(len(spec[0]), 4)

    def test_a_trigger_is_not_a_switch(self):
        # One label is a one-shot. Firing it off a mute button is a different
        # feature and is refused rather than half-supported.
        self.assertIsNone(tl.switch_spec(["trig"], [0]))

    def test_a_plain_numeric_port_is_not_a_switch(self):
        self.assertIsNone(tl.switch_spec(None, None))
        self.assertIsNone(tl.switch_spec([], []))

    def test_labels_without_ticks_are_not_a_switch(self):
        self.assertIsNone(tl.switch_spec(["a", "b"], None))

    def test_mismatched_lengths_truncate_rather_than_raise(self):
        # A column that indexed past the end of one of them would take the
        # whole render down, and the render runs on the poll thread.
        labels, ticks = tl.switch_spec(["a", "b", "c"], [0, 1])
        self.assertEqual((labels, ticks), (("a", "b"), (0, 1)))


class TestSwitchIndex(unittest.TestCase):

    def test_an_exact_tick_is_its_own_index(self):
        self.assertEqual(tl.switch_index(2, (0, 1, 2, 3)), 2)

    def test_a_value_between_ticks_takes_the_nearest(self):
        self.assertEqual(tl.switch_index(30, (0, 32, 64)), 1)

    def test_sparse_ticks_are_not_assumed_evenly_spaced(self):
        self.assertEqual(tl.switch_index(0.9, (0.0, 0.25, 1.0)), 2)

    def test_descending_ticks_work(self):
        # zynthian_controller sets range_reversed for a descending scale, so
        # the order cannot be assumed.
        self.assertEqual(tl.switch_index(10, (100, 50, 10, 0)), 2)

    def test_a_label_string_resolves_through_the_labels(self):
        # jalv seeds a toggle with 'off' / 'on', so the first read of a port
        # can be a word rather than a number.
        self.assertEqual(tl.switch_index("on", (0, 1), ("off", "on")), 1)

    def test_an_unknown_label_falls_back_to_the_first_position(self):
        self.assertEqual(tl.switch_index("weird", (0, 1), ("off", "on")), 0)


class TestSwitchMovement(unittest.TestCase):
    """The button wraps and the knob clamps, deliberately: one button has to
    reach every position, and no knob on this surface jumps from the last
    position to the first on one detent."""

    def test_the_button_advances(self):
        self.assertEqual(tl.switch_next(0, 4), 1)

    def test_the_button_wraps(self):
        self.assertEqual(tl.switch_next(3, 4), 0)

    def test_a_two_state_button_is_a_toggle(self):
        self.assertEqual(tl.switch_next(1, 2), 0)

    def test_the_knob_clamps_at_both_ends(self):
        self.assertEqual(tl.switch_step(3, 4, 1), 3)
        self.assertEqual(tl.switch_step(0, 4, -1), 0)

    def test_the_knob_takes_a_multi_step_delta(self):
        self.assertEqual(tl.switch_step(0, 6, 3), 3)

    def test_an_empty_switch_cannot_move(self):
        self.assertEqual(tl.switch_next(0, 0), 0)
        self.assertEqual(tl.switch_step(0, 0, 1), 0)


class TestSwitchColumns(unittest.TestCase):
    """A switch column draws the plugin's own WORD over a segmented bar - the
    vocabulary the surface already has - instead of a number over a fill."""

    def _page(self, count=2):
        ports = [(f"p{i}", 0.0, 1.0) for i in range(count)]
        return tl.generated_pages(ports, (), tl.SHAPE_CHANNEL,
                                  tl.VERB_LV2, "EXTRA")[0]

    def test_a_switch_column_shows_the_label(self):
        page = self._page()
        cols = tl.columns(page, "voice", {
            "lv2:p0": 100, "pending": set(),
            "switch": {"lv2:p0": (1, 2, "on")}})
        self.assertEqual(cols[0]["value"], "on")
        self.assertEqual(cols[0]["bar"], "seg")
        self.assertEqual(cols[0]["frac"], (1, 2))
        # A word needs the small font, exactly as a preset name does.
        self.assertTrue(cols[0]["small"])

    def test_the_name_is_still_the_port(self):
        page = self._page()
        cols = tl.columns(page, "voice", {
            "lv2:p0": 0, "pending": set(),
            "switch": {"lv2:p0": (0, 4, "LP24")}})
        self.assertEqual(cols[0]["name"], "P0")
        self.assertEqual(cols[0]["value"], "LP24")

    def test_a_port_that_is_not_a_switch_is_untouched(self):
        page = self._page()
        cols = tl.columns(page, "voice", {
            "lv2:p0": 50, "lv2:p1": 50, "pending": set(),
            "switch": {"lv2:p0": (0, 2, "off")}})
        self.assertEqual(cols[1]["value"], "0050")
        self.assertEqual(cols[1]["bar"], "uni")

    def test_a_view_with_no_switches_at_all_still_renders(self):
        # Every caller that predates switches omits the key.
        page = self._page()
        cols = tl.columns(page, "voice", {"lv2:p0": 50, "pending": set()})
        self.assertEqual(cols[0]["value"], "0050")

    def test_a_dead_port_outranks_a_stale_switch_entry(self):
        # Law L4: no value in the view means the port is gone, and a switch
        # entry left over from the previous plugin must not draw over it.
        page = self._page()
        cols = tl.columns(page, "voice", {
            "pending": set(), "switch": {"lv2:p0": (1, 2, "on")}})
        self.assertTrue(cols[0]["grey"])
        self.assertEqual(cols[0]["value"], "----")

    def test_a_long_label_is_shortened_to_the_small_font_budget(self):
        page = self._page()
        cols = tl.columns(page, "voice", {
            "lv2:p0": 0, "pending": set(),
            "switch": {"lv2:p0": (0, 3, "Ladder 24dB LP")}})
        self.assertLessEqual(len(cols[0]["value"]), tl.SWITCH_LABEL_CHARS)


class TestFRowKind(unittest.TestCase):
    """ONE ROW, ONE MEANING, since 2026-09-01.

    CONTROL used to take the row for the page's parameter switches. That
    needed an exception of its own (SHIFT + Fn handed mute back) and a third
    state on top of it (MOD made the row inert) - three meanings on the eight
    buttons a player hits without looking, told apart by a mode AND a
    modifier.

    Nothing was lost giving it back: a switch column's ENCODER already steps
    that switch through its own ticks, so the button was a second way to do
    what the knob above it did, bought at the price of the row's only
    meaning."""

    def test_every_mode_is_mute(self):
        for mode in ("CONTROL", "STEP", "AUTO", "VOLUME"):
            self.assertEqual(tl.f_row_kind(mode, False, False, False),
                             tl.F_ROW_MUTE, mode)

    def test_control_no_longer_takes_the_row(self):
        # The regression this whole change exists to prevent.
        self.assertEqual(tl.f_row_kind("CONTROL", False, False, False),
                         tl.F_ROW_MUTE)

    def test_no_modifier_changes_what_the_row_is(self):
        # SHIFT used to be the way BACK to mute inside CONTROL, and MOD used
        # to make the row inert. Neither has anything left to do here: the row
        # never leaves, so it never has to be handed back.
        for shift in (False, True):
            for mod in (False, True):
                self.assertEqual(
                    tl.f_row_kind("CONTROL", shift, False, mod),
                    tl.F_ROW_MUTE, f"shift={shift} mod={mod}")

    def test_solo_is_not_a_different_row(self):
        # SOLO changes what a press MEANS - mute or solo - and that is
        # _f_button's business, not the row's. The row is still the eight
        # channels either way, which is why soloing does not appear here.
        self.assertEqual(tl.f_row_kind("STEP", False, True, False),
                         tl.F_ROW_MUTE)


class TestWrapLabel(unittest.TestCase):
    """A port name does not fit one row. The tab box above the column carries
    the first line and the name row the second, so a column has sixteen
    characters instead of eight - owner, 2026-08-19, at the rig, where
    PITCH_BEND_RANGE and PITCH_BEND_STEP both drew as "PITCH_BE"."""

    def test_a_short_name_uses_one_line(self):
        self.assertEqual(tl.wrap_label("Gain"), ("Gain", ""))

    def test_it_breaks_on_a_space(self):
        self.assertEqual(tl.wrap_label("Master Tune"), ("Master", "Tune"))

    def test_neighbours_stop_colliding(self):
        # The pair that motivated it: same first eight characters, different
        # second line.
        self.assertEqual(tl.wrap_label("ModWheel Range")[1], "Range")
        self.assertEqual(tl.wrap_label("ModWheel Assign")[1], "Assign")

    def test_an_underscore_is_a_break_and_survives(self):
        self.assertEqual(tl.wrap_label("MOD_WHEEL_ASSIGN"), ("MOD_", "WHEEL_"))

    def test_one_long_word_is_hard_split(self):
        self.assertEqual(tl.wrap_label("OSCILLATORSYNC"), ("OSCILLAT", "ORSYNC"))

    def test_a_third_line_is_dropped_rather_than_drawn_nowhere(self):
        first, second = tl.wrap_label("One Two Three Four Five")
        self.assertLessEqual(len(first), tl.TAB_LABEL_CHARS)
        self.assertLessEqual(len(second), tl.TAB_LABEL_CHARS)

    def test_nothing_wraps_to_nothing(self):
        self.assertEqual(tl.wrap_label(""), ("", ""))
        self.assertEqual(tl.wrap_label(None), ("", ""))


class TestGeneratedTabs(unittest.TestCase):

    def test_a_tab_carries_the_label_and_no_channel_styling(self):
        tabs = tl.generated_tabs(("Cutoff", "Engine", "", "Poly/Mon"))
        self.assertEqual(len(tabs), 4)
        letter, name, selected, muted, armed = tabs[0]
        # No letter: a parameter is not a channel, so none of the channel
        # styles - selected, dashed, dotted - apply to it.
        self.assertEqual((letter, name), ("", "Cutoff"))
        self.assertFalse(selected or muted or armed)


class TestGeneratedColumnNames(unittest.TestCase):

    def _page(self):
        return tl.generated_pages([("mod_wheel_assign", 0.0, 1.0)], (),
                                  tl.SHAPE_CHANNEL, tl.VERB_LV2, "EXTRA")[0]

    def test_the_name_row_is_the_second_line_of_the_name(self):
        cols = tl.columns(self._page(), "voice", {
            "lv2:mod_wheel_assign": 50, "pending": set(),
            "names": {"lv2:mod_wheel_assign": "ModWheel Assign"}})
        self.assertEqual(cols[0]["name"], "Assign")

    def test_without_a_name_it_falls_back_to_the_symbol(self):
        cols = tl.columns(self._page(), "voice",
                          {"lv2:mod_wheel_assign": 50, "pending": set()})
        self.assertEqual(cols[0]["name"], "MOD_WHEE")

    def test_a_dead_column_still_names_itself(self):
        cols = tl.columns(self._page(), "voice", {
            "pending": set(), "names": {"lv2:mod_wheel_assign": "ModWheel Assign"}})
        self.assertTrue(cols[0]["grey"])
        self.assertEqual(cols[0]["value"], "----")
        self.assertEqual(cols[0]["name"], "assign")


class TestPhraseClock(unittest.TestCase):

    def test_at_the_anchor_it_is_bar_zero(self):
        self.assertEqual(tl.phrase_pos(10.0, 10.0), (0, 0.0))

    def test_one_bar_after_the_anchor(self):
        self.assertEqual(tl.phrase_pos(14.0, 10.0), (1, 0.0))

    def test_half_way_through_bar_two(self):
        bar, frac = tl.phrase_pos(20.0, 10.0)
        self.assertEqual(bar, 2)
        self.assertAlmostEqual(frac, 0.5)

    def test_before_the_anchor_never_goes_negative(self):
        self.assertEqual(tl.phrase_pos(5.0, 10.0), (0, 0.0))

    def test_a_three_beat_bar_is_honoured(self):
        self.assertEqual(tl.phrase_pos(6.0, 0.0, beats_per_bar=3), (2, 0.0))

    def test_bar_zero_of_the_phrase(self):
        self.assertEqual(tl.phrase_bar(0), 0)

    def test_the_phrase_wraps(self):
        self.assertEqual(tl.phrase_bar(16), 0)
        self.assertEqual(tl.phrase_bar(17), 1)

    def test_a_shorter_phrase_wraps_sooner(self):
        self.assertEqual(tl.phrase_bar(4, phrase_bars=4), 0)

    def test_a_nonsense_phrase_length_does_not_divide_by_zero(self):
        self.assertEqual(tl.phrase_bar(5, phrase_bars=0), 0)


class TestPendingQueue(unittest.TestCase):

    def setUp(self):
        self.q = tl.PendingQueue()

    def test_a_fresh_queue_has_nothing_pending(self):
        self.assertEqual(self.q.pending(), [])

    def test_nothing_is_due_before_the_landing_bar(self):
        self.q.arm("drop", 4, at_bar=0)
        self.assertEqual(self.q.due(3), [])

    def test_it_fires_on_the_landing_bar(self):
        self.q.arm("drop", 4, at_bar=0)
        self.assertEqual(self.q.due(4), ["drop"])

    def test_firing_removes_it(self):
        self.q.arm("drop", 4, at_bar=0)
        self.q.due(4)
        self.assertEqual(self.q.pending(), [])

    def test_a_late_poll_still_fires_it(self):
        self.q.arm("drop", 4, at_bar=0)
        self.assertEqual(self.q.due(7), ["drop"])

    def test_arming_the_same_macro_replaces_it(self):
        self.q.arm("drop", 4, at_bar=0)
        self.q.arm("drop", 8, at_bar=0)
        self.assertEqual(self.q.pending(), ["drop"])
        self.assertEqual(self.q.due(4), [])
        self.assertEqual(self.q.due(8), ["drop"])

    def test_two_different_macros_coexist(self):
        self.q.arm("drop", 4, at_bar=0)
        self.q.arm("chance", 8, at_bar=0)
        self.assertEqual(sorted(self.q.pending()), ["chance", "drop"])

    def test_both_due_at_once_come_back_together(self):
        self.q.arm("drop", 4, at_bar=0)
        self.q.arm("chance", 4, at_bar=0)
        self.assertEqual(sorted(self.q.due(4)), ["chance", "drop"])

    def test_bars_remaining_counts_down(self):
        self.q.arm("drop", 4, at_bar=0)
        self.assertEqual(self.q.remaining("drop", 1), 3)

    def test_bars_remaining_is_none_for_nothing_pending(self):
        self.assertIsNone(self.q.remaining("drop", 1))

    def test_bars_remaining_never_goes_negative(self):
        self.q.arm("drop", 4, at_bar=0)
        self.assertEqual(self.q.remaining("drop", 9), 0)

    def test_clear_cancels_everything(self):
        self.q.arm("drop", 4, at_bar=0)
        self.q.arm("chance", 8, at_bar=0)
        self.q.clear()
        self.assertEqual(self.q.pending(), [])

    def test_a_zero_bar_arm_fires_on_the_next_bar_not_now(self):
        self.q.arm("drop", 0, at_bar=5)
        self.assertEqual(self.q.due(5), [])
        self.assertEqual(self.q.due(6), ["drop"])


class TestArmOverlay(unittest.TestCase):

    def test_arm_owns_the_pads_when_held_alone(self):
        self.assertEqual(tl.overlay_owner(arm=True), "arm")

    def test_shift_still_outranks_arm(self):
        self.assertEqual(tl.overlay_owner(shift=True, arm=True), "shift")

    def test_arm_outranks_mod(self):
        self.assertEqual(tl.overlay_owner(mod=True, arm=True), "arm")

    def test_arm_outranks_navigate(self):
        self.assertEqual(tl.overlay_owner(navigate=True, arm=True), "arm")

    def test_arm_pads_are_not_steps(self):
        self.assertFalse(tl.overlay_is_stepwise("arm"))

    def test_every_existing_caller_is_unaffected(self):
        self.assertIsNone(tl.overlay_owner())
        self.assertEqual(tl.overlay_owner(shift=True), "shift")
        self.assertEqual(tl.overlay_owner(mod=True), "mod")
        self.assertEqual(tl.overlay_owner(navigate=True), "navigate")


class TestPhraseLabel(unittest.TestCase):

    def test_it_appends_the_bar_of_the_phrase(self):
        self.assertEqual(tl.phrase_label("LEVEL 1/3", 0), "LEVEL 1/3 1/16")

    def test_it_counts_from_one_for_the_player(self):
        self.assertEqual(tl.phrase_label("LEVEL 1/3", 3), "LEVEL 1/3 4/16")

    def test_a_shorter_phrase_says_so(self):
        self.assertEqual(tl.phrase_label("X", 1, phrase_bars=4), "X 2/4")

    def test_no_bar_means_no_suffix(self):
        self.assertEqual(tl.phrase_label("LEVEL 1/3", None), "LEVEL 1/3")

    # THE COUNTER IS WHY THE SURFACE REPAINTED EVERY BAR. Measured on the rig
    # 2026-09-02: idle traffic 63 OSC msg/s with nobody touching the
    # controller, one full clear-and-redraw of BOTH screens per bar, and two
    # controller stalls in one session. The number changes on its own, so it
    # changed the display's change-detection key on its own, and a moving
    # value must not be in that key - the same law that took the live tick out
    # of it on 2026-08-20 and the modulator's rate out of it on 2026-08-31.
    #
    # It is not deleted, because its purpose is real: a timed gesture needs
    # something to resolve against. It is shown only while there IS a timed
    # gesture waiting to land.
    def test_it_is_silent_when_nothing_is_waiting_to_land(self):
        self.assertEqual(tl.phrase_label("LEVEL 1/3", 3, show=False),
                         "LEVEL 1/3")

    def test_it_appears_when_a_gesture_is_waiting(self):
        self.assertEqual(tl.phrase_label("LEVEL 1/3", 3, show=True),
                         "LEVEL 1/3 4/16")

    def test_showing_still_needs_a_bar(self):
        self.assertEqual(tl.phrase_label("X", None, show=True), "X")


class TestArmLegendPad(unittest.TestCase):
    """The ARM overlay's sixteen pads: a picker, or a countdown ruler."""

    def test_macro_pads_are_lit_and_the_picked_one_is_full(self):
        for index, macro in enumerate(tl.ARM_MACROS):
            colour, bright = tl.arm_legend_pad(index, picked=macro)
            self.assertEqual(colour, tl.COLOR_ARM_MACRO)
            self.assertEqual(bright, tl.PAD_FULL)
            _c, other = tl.arm_legend_pad(index, picked=None)
            self.assertEqual(other, tl.ARM_DIM)

    def test_pads_between_the_macros_and_the_lengths_are_dark(self):
        # The whole point: pads 2-7 have no macro behind them, and a lit pad
        # that does nothing is the fault this surface must never commit.
        for index in range(len(tl.ARM_MACROS), 8):
            _colour, bright = tl.arm_legend_pad(index, picked="drop")
            self.assertEqual(bright, tl.PAD_OFF)

    def test_the_length_ring_is_lit_whether_or_not_a_macro_is_picked(self):
        for index in range(8, 16):
            for picked in (None, "drop"):
                colour, bright = tl.arm_legend_pad(index, picked=picked)
                self.assertEqual(colour, tl.COLOR_ARM_LENGTH)
                self.assertEqual(bright, tl.ARM_DIM)

    def test_the_length_ring_has_one_pad_per_length(self):
        self.assertEqual(len(tl.ARM_LENGTHS), 8)

    def test_a_full_ruler_lights_exactly_the_armed_bars(self):
        lit = [i for i in range(16)
               if tl.arm_legend_pad(i, armed_bars=4, remaining=4)[1]]
        self.assertEqual(lit, [0, 1, 2, 3])

    def test_the_ruler_extinguishes_from_the_top_left(self):
        # Three bars left of four: pad 0 has gone out, 1-3 remain. Extinguishing
        # from the left is what makes the lit pads READ as the time remaining.
        lit = [i for i in range(16)
               if tl.arm_legend_pad(i, armed_bars=4, remaining=3)[1]]
        self.assertEqual(lit, [1, 2, 3])
        lit = [i for i in range(16)
               if tl.arm_legend_pad(i, armed_bars=4, remaining=1)[1]]
        self.assertEqual(lit, [3])

    def test_a_spent_ruler_is_entirely_dark(self):
        for i in range(16):
            self.assertEqual(tl.arm_legend_pad(i, armed_bars=4, remaining=0)[1],
                             tl.PAD_OFF)

    def test_the_ruler_never_lights_a_pad_that_does_not_exist(self):
        # 16 bars is the longest ARM_LENGTHS offers and it fills the grid
        # exactly. Anything beyond has to clamp rather than index past the end.
        lit = [i for i in range(16)
               if tl.arm_legend_pad(i, armed_bars=16, remaining=16)[1]]
        self.assertEqual(lit, list(range(16)))
        lit = [i for i in range(16)
               if tl.arm_legend_pad(i, armed_bars=99, remaining=99)[1]]
        self.assertEqual(lit, list(range(16)))

    def test_the_ruler_replaces_the_picker_entirely(self):
        # Reading the countdown must not also offer to change it, so no macro
        # pad and no length pad survives underneath.
        picker = [tl.arm_legend_pad(i, picked="drop") for i in range(16)]
        ruler = [tl.arm_legend_pad(i, picked="drop", armed_bars=2, remaining=2)
                 for i in range(16)]
        self.assertNotEqual(picker, ruler)
        for i in range(2, 16):
            self.assertEqual(ruler[i][1], tl.PAD_OFF)

    def test_arm_macros_are_append_only_in_the_documented_order(self):
        # A snapshot may store the name, so an existing entry never moves.
        self.assertEqual(tl.ARM_MACROS[:2], ("drop", "chance"))

    def test_arm_is_registered_as_a_stateful_button(self):
        self.assertEqual(tl.BUTTONS_STATEFUL[30], "arm")
        self.assertNotIn(30, tl.BUTTONS_PRESS)

    def test_arm_sits_between_shift_and_mod_in_the_overlay_order(self):
        order = tl.OVERLAY_PRIORITY
        self.assertLess(order.index("shift"), order.index("arm"))
        self.assertLess(order.index("arm"), order.index("mod"))
        self.assertFalse(tl.overlay_is_stepwise("arm"))

    def test_arm_wins_over_mod_and_loses_to_shift(self):
        self.assertEqual(tl.overlay_owner(arm=True, mod=True), "arm")
        self.assertEqual(tl.overlay_owner(shift=True, arm=True), "shift")
        self.assertEqual(tl.overlay_owner(arm=True), "arm")


class TestChanceRamp(unittest.TestCase):
    """The breakdown that thins instead of muting."""

    def test_it_starts_at_the_players_own_value(self):
        self.assertEqual(tl.chance_ramp(100, 25, 0, 8), 100)

    def test_it_reaches_the_floor_half_way(self):
        self.assertEqual(tl.chance_ramp(100, 25, 4, 8), 25)

    def test_it_returns_to_the_players_own_value(self):
        self.assertEqual(tl.chance_ramp(100, 25, 8, 8), 100)

    def test_it_returns_to_SEVENTY_not_one_hundred(self):
        # The whole point: a channel the player left at 70 comes back at 70.
        # Assuming 100 is the original bug that made a saved channel come back
        # silent while the surface read full.
        self.assertEqual(tl.chance_ramp(70, 25, 8, 8), 70)

    def test_it_thins_on_the_way_down(self):
        self.assertLess(tl.chance_ramp(100, 25, 2, 8), 100)
        self.assertGreater(tl.chance_ramp(100, 25, 2, 8), 25)

    def test_it_is_symmetric_about_the_middle(self):
        for step in range(9):
            self.assertEqual(tl.chance_ramp(100, 25, step, 8),
                             tl.chance_ramp(100, 25, 8 - step, 8))

    def test_a_base_below_the_floor_never_rises_to_meet_it(self):
        # A breakdown that made a quiet channel louder would be the gesture
        # backwards.
        self.assertEqual(tl.chance_ramp(10, 25, 4, 8), 10)

    def test_a_zero_length_ramp_is_the_identity(self):
        self.assertEqual(tl.chance_ramp(100, 25, 0, 0), 100)

    def test_it_never_leaves_the_legal_range(self):
        for bars in (1, 2, 3, 4, 8, 16):
            for step in range(bars + 2):
                value = tl.chance_ramp(100, 25, step, bars)
                self.assertGreaterEqual(value, 0)
                self.assertLessEqual(value, 100)

    def test_past_the_end_it_is_back_at_base(self):
        # A missed poll must not strand a channel thinned forever.
        self.assertEqual(tl.chance_ramp(100, 25, 99, 8), 100)

    def test_the_floor_is_the_lowest_chance_rung(self):
        # Reuses CHANCE_RUNGS' own vocabulary rather than inventing a number.
        self.assertEqual(tl.CHANCE_RUNGS[-1], 25)


class TestRise(unittest.TestCase):
    """A modulator shape that runs ONCE and holds, instead of cycling."""

    def test_it_starts_at_zero(self):
        self.assertAlmostEqual(tl.mod_once_pos(0.0, 0.0, 4.0), 0.0)

    def test_it_is_half_way_at_half_the_span(self):
        self.assertAlmostEqual(tl.mod_once_pos(0.0, 8.0, 4.0), 0.5)

    def test_it_reaches_exactly_one_at_the_end(self):
        self.assertAlmostEqual(tl.mod_once_pos(0.0, 16.0, 4.0), 1.0)

    def test_it_CLAMPS_and_never_wraps(self):
        # The whole difference from mod_pos: a free LFO would be back at 0.0.
        self.assertAlmostEqual(tl.mod_once_pos(0.0, 32.0, 4.0), 1.0)
        self.assertAlmostEqual(tl.mod_once_pos(0.0, 999.0, 4.0), 1.0)

    def test_a_negative_position_is_clamped_to_zero(self):
        self.assertAlmostEqual(tl.mod_once_pos(-1.0, 0.0, 4.0), 0.0)

    def test_a_zero_span_lands_at_the_end_rather_than_dividing(self):
        self.assertAlmostEqual(tl.mod_once_pos(0.0, 5.0, 0.0), 1.0)

    def test_the_endpoint_cannot_be_passed_to_mod_wave_directly(self):
        # THE TRAP, asserted so it cannot come back. mod_wave takes pos % 1.0
        # and 1.0 % 1.0 is 0.0, which puts a FINISHED ramp at its MINIMUM -
        # the exact opposite of landing on the downbeat. _mod_write must
        # substitute the endpoint rather than passing 1.0 through.
        self.assertAlmostEqual(tl.mod_wave("ramp", 1.0),
                               tl.mod_wave("ramp", 0.0))
        self.assertGreater(tl.mod_wave("ramp", tl.MOD_ONCE_END),
                           tl.mod_wave("ramp", 0.5))

    def test_the_endpoint_constant_is_just_under_one(self):
        self.assertLess(tl.MOD_ONCE_END, 1.0)
        self.assertGreater(tl.MOD_ONCE_END, 0.999)

    def test_phase0_can_start_the_sweep_from_anywhere(self):
        # _arm_once stores a negative phase0 so the sweep begins at the
        # moment of arming rather than at driver start-up.
        self.assertAlmostEqual(tl.mod_once_pos(-1.0, 16.0, 4.0), 0.0)
        self.assertAlmostEqual(tl.mod_once_pos(-1.0, 32.0, 4.0), 1.0)


class TestPadOwnerChord(unittest.TestCase):
    """MOD latched + ARM held is MOD, and it is the only chord exception."""

    def test_mod_and_arm_together_are_mod(self):
        # RISE lives here: the pads must keep showing the rate/shape legend
        # the player is choosing from, not ARM's macro picker.
        self.assertEqual(tl.pad_owner(mod=True, arm=True), "mod")

    def test_arm_alone_is_still_arm(self):
        self.assertEqual(tl.pad_owner(arm=True), "arm")

    def test_mod_alone_is_still_mod(self):
        self.assertEqual(tl.pad_owner(mod=True), "mod")

    def test_shift_still_outranks_everything(self):
        self.assertEqual(tl.pad_owner(shift=True, arm=True, mod=True), "shift")
        self.assertEqual(tl.pad_owner(shift=True, arm=True), "shift")

    def test_nothing_held_is_the_step_picture(self):
        self.assertIsNone(tl.pad_owner())

    def test_it_agrees_with_overlay_owner_everywhere_else(self):
        # The chord is the ONLY divergence. If a future overlay changes the
        # priority table, this catches a pad_owner that quietly stopped
        # following it.
        for shift in (False, True):
            for mod in (False, True):
                for arm in (False, True):
                    if mod and arm and not shift:
                        continue
                    self.assertEqual(
                        tl.pad_owner(shift=shift, mod=mod, arm=arm),
                        tl.overlay_owner(shift=shift, mod=mod, arm=arm),
                        f"shift={shift} mod={mod} arm={arm}")


class TestPhrasePad(unittest.TestCase):
    """NAVIGATE's phrase page: one pad per bar, past dim, now full."""

    def test_stopped_draws_every_pad_dark(self):
        # A phrase page showing bar 1 lit while nothing plays reads as a
        # running clock that has stuck.
        for pad in range(16):
            self.assertEqual(tl.phrase_pad(pad, None)[1], tl.PAD_OFF)

    def test_the_current_bar_is_the_only_full_pad(self):
        full = [i for i in range(16) if tl.phrase_pad(i, 5)[1] == tl.PAD_FULL]
        self.assertEqual(full, [5])

    def test_the_bars_already_played_are_dim(self):
        for pad in range(5):
            self.assertEqual(tl.phrase_pad(pad, 5)[1], tl.PHRASE_PAST)

    def test_the_bars_still_to_come_are_dark(self):
        for pad in range(6, 16):
            self.assertEqual(tl.phrase_pad(pad, 5)[1], tl.PAD_OFF)

    def test_it_wraps_with_the_phrase(self):
        # Bar 16 is bar 0 of the next phrase, not a seventeenth pad.
        full = [i for i in range(16) if tl.phrase_pad(i, 16)[1] == tl.PAD_FULL]
        self.assertEqual(full, [0])
        full = [i for i in range(16) if tl.phrase_pad(i, 21)[1] == tl.PAD_FULL]
        self.assertEqual(full, [5])

    def test_only_two_brightnesses_are_used(self):
        # Three levels would need a legend; two read at a glance.
        seen = {tl.phrase_pad(i, 7)[1] for i in range(16)}
        self.assertEqual(seen, {tl.PAD_FULL, tl.PHRASE_PAST, tl.PAD_OFF})

    def test_navigate_is_bound_and_not_stepwise(self):
        self.assertEqual(tl.BUTTONS_STATEFUL[34], "navigate")
        self.assertFalse(tl.overlay_is_stepwise("navigate"))
        self.assertEqual(tl.pad_owner(navigate=True), "navigate")

    def test_navigate_loses_to_every_other_overlay(self):
        # Last in OVERLAY_PRIORITY: it is a glance, not a gesture.
        self.assertEqual(tl.pad_owner(navigate=True, mod=True), "mod")
        self.assertEqual(tl.pad_owner(navigate=True, arm=True), "arm")
        self.assertEqual(tl.pad_owner(navigate=True, shift=True), "shift")
class TestModDepthScale(unittest.TestCase):

    def test_unity_is_the_identity(self):
        self.assertAlmostEqual(tl.mod_depth_scale(50.0, 1.0), 50.0)

    def test_it_halves(self):
        self.assertAlmostEqual(tl.mod_depth_scale(50.0, 0.5), 25.0)

    def test_it_doubles(self):
        self.assertAlmostEqual(tl.mod_depth_scale(50.0, 2.0), 100.0)

    def test_a_NEGATIVE_depth_keeps_its_sign(self):
        # Depths are signed. Scaling magnitude must not flip a modulator.
        self.assertAlmostEqual(tl.mod_depth_scale(-50.0, 2.0), -100.0)

    def test_zero_multiplier_parks_it(self):
        self.assertAlmostEqual(tl.mod_depth_scale(50.0, 0.0), 0.0)

    def test_a_parked_modulator_COMES_BACK(self):
        # The whole reason the multiplier is stored separately: if the stored
        # depth were multiplied in place, 0 x anything = 0 would strand every
        # modulator at zero with no way back.
        depth = -37.0
        self.assertAlmostEqual(tl.mod_depth_scale(depth, 0.0), 0.0)
        self.assertAlmostEqual(tl.mod_depth_scale(depth, 1.0), -37.0)

    def test_a_negative_multiplier_cannot_invert(self):
        self.assertAlmostEqual(tl.mod_depth_scale(50.0, -1.0), 0.0)


class TestRecLedState(unittest.TestCase):
    """REC's LED, from every fact at once. ONE predicate, no second writer."""

    def test_not_possible_is_off(self):
        # In STEP mode, and while MOD owns the pads, holding REC does nothing
        # at all - a lit REC would be promising a take it cannot make.
        self.assertEqual(tl.rec_led_state(False, False, False), "off")

    def test_possible_and_idle_is_ready(self):
        self.assertEqual(tl.rec_led_state(True, False, False), "ready")

    def test_overdub_armed(self):
        self.assertEqual(tl.rec_led_state(True, True, False), "overdub")

    def test_recording_to_disk(self):
        self.assertEqual(tl.rec_led_state(True, False, True), "recording")

    def test_both_at_once_is_its_own_state(self):
        # If overdub and capture each wrote the LED they would fight and it
        # would lie about which mode the instrument is in.
        self.assertEqual(tl.rec_led_state(True, True, True), "both")

    def test_capture_outranks_impossible_overdub(self):
        # THE CASE THAT MATTERS. Capture is running, but the player has
        # switched to STEP mode where overdub is not possible. The LED must
        # still say a recording is in progress - going dark would hide a
        # running capture, and a file quietly filling the disk with nothing on
        # the panel saying so is the unexplained-silence law in reverse.
        self.assertEqual(tl.rec_led_state(False, False, True), "recording")

    def test_every_state_is_distinct(self):
        seen = {tl.rec_led_state(p, o, r)
                for p in (False, True)
                for o in (False, True)
                for r in (False, True)}
        self.assertEqual(seen, {"off", "ready", "overdub", "recording", "both"})


class TestFreeze(unittest.TestCase):
    """Two stages on one button, mapped onto law L1: tap latches, hold is
    momentary."""

    def test_nothing_is_blocked_when_thawed(self):
        self.assertFalse(tl.freeze_blocks("melody", False, False))
        self.assertFalse(tl.freeze_blocks("lfo", False, False))

    def test_a_tap_freezes_pattern_generation(self):
        self.assertTrue(tl.freeze_blocks("melody", True, False))
        self.assertTrue(tl.freeze_blocks("rhythm", True, False))
        self.assertTrue(tl.freeze_blocks("drift", True, False))
        self.assertTrue(tl.freeze_blocks("reroll", True, False))

    def test_a_tap_LEAVES_THE_LFOS_SWEEPING(self):
        # The owner's choice: the notes stop changing under you while the
        # sound keeps breathing. A rig with everything parked sounds dead
        # rather than held.
        self.assertFalse(tl.freeze_blocks("lfo", True, False))

    def test_a_hold_parks_the_lfos_too(self):
        self.assertTrue(tl.freeze_blocks("lfo", True, True))

    def test_a_hold_alone_parks_the_lfos_without_a_latch(self):
        self.assertTrue(tl.freeze_blocks("lfo", False, True))

    def test_a_hold_alone_also_freezes_generation(self):
        # A hold is the TOTAL hold - everything the tap freezes, plus the
        # LFOs. If a hold parked the LFOs but let the pattern keep evolving,
        # the deeper gesture would be doing less than the shallower one.
        self.assertTrue(tl.freeze_blocks("melody", False, True))

    def test_an_unknown_subject_is_never_blocked(self):
        # A typo must not silently freeze something, and must not silently
        # unfreeze it either.
        self.assertFalse(tl.freeze_blocks("nonsense", True, True))

    def test_the_frozen_subjects_are_the_documented_set(self):
        # "macro" joined 2026-08-20: an armed DROP fired while frozen and
        # muted every channel.
        # "walk" joined 2026-08-31 with the chord walker, on the same argument
        # that put "macro" here in 2026-08-20.
        self.assertEqual(tl.FREEZE_GENERATIVE,
                         frozenset(("melody", "rhythm", "drift", "reroll",
                                    "macro", "walk", "fill")))


class TestFreezeLabel(unittest.TestCase):

    def test_thawed_says_nothing(self):
        self.assertEqual(tl.freeze_label("CTRL", False, False), "CTRL")

    def test_the_latch_says_frz(self):
        self.assertEqual(tl.freeze_label("CTRL", True, False), "CTRL FRZ")

    def test_the_total_hold_says_frz_bang(self):
        # Two words, not one: the stages stop different things and a player
        # who cannot tell them apart cannot tell whether the LFOs still move.
        self.assertEqual(tl.freeze_label("CTRL", True, True), "CTRL FRZ!")

    def test_a_hold_without_a_latch_still_says_the_total_hold(self):
        self.assertEqual(tl.freeze_label("CTRL", False, True), "CTRL FRZ!")


class TestFreezeGreysTheGenerativeColumns(unittest.TestCase):
    """FREEZE reuses MOD's grammar for 'this control cannot act right now'."""

    def _page(self):
        # The page that actually carries RANDOM and RHYTHM - found rather than
        # hard-coded, so a layout change moves the test with it instead of
        # breaking it.
        # The AUTO ring since 2026-09-01 - the generative verbs moved there
        # when the rings collapsed from 24 pages to 9.
        for desc in tl.PAGE_RINGS[tl.ring_key("AUTO", "voice")]:
            if "random" in (desc.get("verbs") or ()):
                return desc
        self.fail("no voice page carries RANDOM")

    def _cols(self, frozen):
        return tl.columns(self._page(), "voice",
                          TestColumnModel().voice_state(), frozen=frozen)

    def _verb_index(self, verb):
        return self._page()["verbs"].index(verb)

    def test_thawed_leaves_every_bar_alone(self):
        live = self._cols(False)
        for verb in tl.FREEZE_VERBS:
            self.assertIsNotNone(live[self._verb_index(verb)].get("bar"), verb)

    def test_frozen_strips_the_bar_off_random_and_rhythm(self):
        cold = self._cols(True)
        for verb in tl.FREEZE_VERBS:
            self.assertIsNone(cold[self._verb_index(verb)].get("bar"), verb)

    def test_frozen_leaves_every_other_column_untouched(self):
        live, cold = self._cols(False), self._cols(True)
        frozen_at = {self._verb_index(v) for v in tl.FREEZE_VERBS}
        for index in range(8):
            if index in frozen_at:
                continue
            self.assertEqual(live[index], cold[index],
                             f"column {index} changed under FREEZE")

    def test_the_value_survives_the_freeze(self):
        # The bar goes, the value stays: it is still the value that resumes
        # the moment the machine thaws.
        index = self._verb_index("random")
        self.assertEqual(self._cols(True)[index].get("value"),
                         self._cols(False)[index].get("value"))

    def test_only_the_two_generative_verbs_are_frozen(self):
        self.assertEqual(tl.FREEZE_VERBS, frozenset(("random", "rhythm")))


class TestPendingPage(unittest.TestCase):
    """The audit surface that makes every armed macro safe to use on stage."""

    def test_nothing_armed_says_NONE(self):
        # Eight blank columns admit nothing, and law L4 is about controls that
        # do nothing and do not say so. A page is the same object as a knob in
        # that respect.
        cols = tl.pending_columns([])
        self.assertEqual(cols[0]["name"], "NONE")
        self.assertEqual(cols[0]["value"], "----")
        self.assertTrue(cols[0]["grey"])

    def test_it_always_returns_eight_columns(self):
        for entries in ([], [("drop", 1, 4)], [("drop", 1, 4)] * 3):
            self.assertEqual(len(tl.pending_columns(entries)), 8)

    def test_a_macro_draws_its_name_and_its_bars_left(self):
        cols = tl.pending_columns([("drop", 3, 4)])
        self.assertEqual(cols[0]["name"], "DROP")
        self.assertEqual(cols[0]["value"], "0003")
        self.assertEqual(cols[0]["bar"], "uni")
        self.assertAlmostEqual(cols[0]["frac"], 0.75)

    def test_the_bar_never_leaves_0_to_1(self):
        # A "seg" bar divides by (count - 1), so a FULL ruler gave a fraction
        # above 1.0 and drew past its own box. Caught on the rig.
        for armed in (1, 2, 4, 8, 16):
            for left in range(0, armed + 2):
                frac = tl.pending_columns([("drop", left, armed)])[0]["frac"]
                self.assertGreaterEqual(frac, 0.0)
                self.assertLessEqual(frac, 1.0, f"{left}/{armed}")

    def test_a_page_with_no_verbs_is_a_real_case(self):
        # PENDING is the first page whose columns are not verbs. The renderer
        # subscripted desc["verbs"] unconditionally and took the whole UI down
        # every render tick once this page was reached.
        # On the VOLUME ring since 2026-09-01: ALL stopped being a mode when
        # it became the lens button, and its global pages moved to VOLUME.
        for desc in tl.PAGE_RINGS[tl.ring_key("VOLUME", None)]:
            if desc["shape"] == tl.SHAPE_PENDING:
                self.assertIsNone(desc.get("verbs"))
                break
        else:
            self.fail("no PENDING page on the VOLUME ring")

    def test_soonest_first(self):
        cols = tl.pending_columns([("drop", 8, 8), ("chance", 2, 4)])
        self.assertEqual([c["name"] for c in cols[:2]], ["THIN", "DROP"])

    def test_ties_break_by_name_so_the_page_does_not_shuffle(self):
        a = tl.pending_columns([("drop", 4, 4), ("chance", 4, 8)])
        b = tl.pending_columns([("chance", 4, 8), ("drop", 4, 4)])
        self.assertEqual([c["name"] for c in a], [c["name"] for c in b])

    def test_more_than_eight_are_truncated_not_crashed(self):
        entries = [(f"m{i}", i, 16) for i in range(12)]
        self.assertEqual(len(tl.pending_columns(entries)), 8)

    def test_an_unknown_macro_still_gets_a_word(self):
        # A page that drew a blank for a macro it did not recognise would be
        # hiding exactly the thing it exists to show.
        cols = tl.pending_columns([("wibble", 1, 2)])
        self.assertTrue(cols[0]["name"])

    def test_the_bar_cannot_exceed_its_length(self):
        cols = tl.pending_columns([("drop", 99, 4)])
        self.assertAlmostEqual(cols[0]["frac"], 1.0)

    def test_the_page_is_on_the_VOLUME_ring(self):
        # Was the ALL ring. ALL stopped being a mode on 2026-09-01 - it is the
        # held lens now - and the global pages it carried are the VOLUME ring.
        titles = [d["title"] for d in tl.PAGE_RINGS[tl.ring_key("VOLUME", None)]]
        self.assertIn("PENDING", titles)
        # The ring had exactly one page before this, so the big encoder did
        # nothing at all on the globals.
        self.assertGreater(len(titles), 1)


class TestPendingQueueCancel(unittest.TestCase):

    def test_cancel_removes_only_that_macro(self):
        q = tl.PendingQueue()
        q.arm("drop", 4, 0)
        q.arm("chance", 8, 0)
        self.assertTrue(q.cancel("drop"))
        self.assertEqual(q.pending(), ["chance"])

    def test_cancel_does_not_move_the_survivors(self):
        # The reason cancel() exists rather than rebuilding the queue at the
        # caller: arm() takes a LENGTH and floors it at one, so re-arming the
        # survivors would push every one of them by at least a bar.
        q = tl.PendingQueue()
        q.arm("drop", 4, 0)
        q.arm("chance", 8, 0)
        q.cancel("drop")
        self.assertEqual(q.remaining("chance", 0), 8)

    def test_cancelling_something_not_armed_is_false_not_an_error(self):
        self.assertFalse(tl.PendingQueue().cancel("nothing"))


class TestTimeScale(unittest.TestCase):
    """Half-time is NOT a DIV move, and DIVISIONS is not sorted by speed."""

    IDX = {"1/32": 0, "1/16": 1, "1/8": 2, "1/16T": 3, "1/8T": 4, "1/4": 5}

    def test_half_time_halves_spb_and_doubles_the_beats(self):
        # 16 steps over 4 beats becomes 16 steps over 8 beats: the identical
        # rhythm, played at half speed.
        self.assertEqual(tl.time_scale(self.IDX["1/16"], 4, 0.5),
                         (self.IDX["1/8"], 8))

    def test_double_time_doubles_spb_and_halves_the_beats(self):
        self.assertEqual(tl.time_scale(self.IDX["1/8"], 8, 2.0),
                         (self.IDX["1/16"], 4))

    def test_the_step_count_is_invariant(self):
        # THE WHOLE POINT. beats * spb is what the sixteen pads draw, so a
        # transform that preserves it always fits the grid exactly and
        # _clamp_params never truncates anything.
        for name, idx in self.IDX.items():
            spb = tl.DIVISION_SPB[idx]
            for beats in range(1, 16 // spb + 1):
                for factor in (0.5, 2.0):
                    got = tl.time_scale(idx, beats, factor)
                    if got is None:
                        continue
                    new_idx, new_beats = got
                    self.assertEqual(tl.DIVISION_SPB[new_idx] * new_beats,
                                     spb * beats,
                                     f"{name} {beats} beats x{factor}")

    def test_it_never_crosses_between_straight_and_triplet(self):
        # div + 1 from 1/8 lands on 1/16T - FASTER, and triplet. A half-time
        # that turned a straight channel into a triplet one would be a
        # different feature arriving unannounced.
        self.assertEqual(tl.time_scale(self.IDX["1/16T"], 2, 0.5),
                         (self.IDX["1/8T"], 4))
        self.assertEqual(tl.time_scale(self.IDX["1/8T"], 4, 2.0),
                         (self.IDX["1/16T"], 2))

    def test_the_four_unreachable_edges_return_None(self):
        self.assertIsNone(tl.time_scale(self.IDX["1/32"], 2, 2.0))   # no spb 16
        self.assertIsNone(tl.time_scale(self.IDX["1/16T"], 2, 2.0))  # no spb 12
        self.assertIsNone(tl.time_scale(self.IDX["1/8T"], 4, 0.5))   # no spb 1.5
        self.assertIsNone(tl.time_scale(self.IDX["1/4"], 8, 0.5))    # no spb 0.5

    def test_a_one_beat_pattern_cannot_double_time(self):
        # Not a table edge: halving the beat count would go below MIN_BEATS.
        self.assertIsNone(tl.time_scale(self.IDX["1/16"], 1, 2.0))

    def test_an_odd_beat_count_cannot_double_time(self):
        # 3 beats halved is 1.5, which is not a length zynseq can hold.
        self.assertIsNone(tl.time_scale(self.IDX["1/8"], 3, 2.0))

    def test_odd_beat_counts_CAN_half_time(self):
        # Polymeter already ships; half-timing a 3-beat channel must work.
        self.assertEqual(tl.time_scale(self.IDX["1/8"], 3, 0.5),
                         (self.IDX["1/4"], 6))

    def test_a_round_trip_returns_the_original(self):
        for idx in self.IDX.values():
            spb = tl.DIVISION_SPB[idx]
            for beats in range(1, 16 // spb + 1):
                down = tl.time_scale(idx, beats, 0.5)
                if down is None:
                    continue
                self.assertEqual(tl.time_scale(down[0], down[1], 2.0),
                                 (idx, beats))

    def test_an_unknown_factor_is_refused_rather_than_guessed(self):
        self.assertIsNone(tl.time_scale(self.IDX["1/16"], 4, 3.0))


class TestDivisionTablesAgree(unittest.TestCase):

    def test_division_spb_mirrors_the_hardware_lib(self):
        # Two tables that must agree and are not compared will not.
        import maschine_mk2_lib as mlib
        self.assertEqual(tl.DIVISION_SPB,
                         tuple(d[1] for d in mlib.maschine_mk2_lib.DIVISIONS))

    def test_division_labels_mirror_it_too(self):
        import maschine_mk2_lib as mlib
        self.assertEqual(tl.DIVISION_LABELS,
                         tuple(d[0] for d in mlib.maschine_mk2_lib.DIVISIONS))

    def test_the_table_really_is_not_sorted_by_speed(self):
        # The assumption that broke the feature entry, asserted so nobody
        # re-derives it: stepping this table by index is not a tempo change.
        self.assertNotEqual(list(tl.DIVISION_SPB),
                            sorted(tl.DIVISION_SPB, reverse=True))

    def test_the_two_families_share_no_steps_per_beat(self):
        # time_scale matches on spb alone and needs no family tag. That is
        # only safe while the straight set and the triplet set are disjoint.
        straight = {8, 4, 2, 1}
        triplet = {6, 3}
        self.assertFalse(straight & triplet)
        self.assertEqual(set(tl.DIVISION_SPB), straight | triplet)


class TestGeneratedChannels(unittest.TestCase):
    """The scope a pattern-rewriting macro takes."""

    def test_all_eight_by_default(self):
        self.assertEqual(tl.generated_channels({}), tuple(range(8)))

    def test_player_owned_channels_are_skipped(self):
        # Not a courtesy - these macros regenerate from euclid, so on a
        # recorded take there is nothing to regenerate from and it would be
        # gone.
        owners = {0: "gen", 3: "player", 7: "player"}
        self.assertEqual(tl.generated_channels(owners), (0, 1, 2, 4, 5, 6))

    def test_an_absent_channel_counts_as_generated(self):
        self.assertIn(5, tl.generated_channels({0: "player"}))


class TestScopeLabel(unittest.TestCase):

    def test_a_full_take_says_only_the_name(self):
        self.assertEqual(tl.scope_label("CTRL", "HALF", 8, 8), "CTRL HALF")

    def test_a_partial_take_shows_the_count(self):
        # Four of the six divisions cannot move in one direction, so a partial
        # result is ordinary here - and a macro that silently did nothing to
        # three of eight channels is the unexplained-silence law in disguise.
        self.assertEqual(tl.scope_label("CTRL", "HALF", 5, 8), "CTRL HALF 5/8")

    def test_taking_nothing_still_says_so(self):
        self.assertEqual(tl.scope_label("CTRL", "DOUBLE", 0, 8),
                         "CTRL DOUBLE 0/8")


class TestRatchetRamp(unittest.TestCase):
    """The roll into the drop: every note subdivides, 1 through 4."""

    def test_it_starts_at_one_which_is_OFF(self):
        self.assertEqual(tl.ratchet_rung(0, 4), 1)

    def test_it_reaches_the_maximum_on_the_last_bar(self):
        # The ramp always ARRIVES. A build that reached x3 because the player
        # armed three bars is a build that does not land.
        for bars in (1, 2, 3, 4, 6, 8, 12, 16):
            self.assertEqual(tl.ratchet_rung(bars - 1, bars), tl.RATCHET_MAX,
                             f"{bars} bars")

    def test_a_four_bar_ramp_walks_one_two_three_four(self):
        self.assertEqual([tl.ratchet_rung(s, 4) for s in range(4)],
                         [1, 2, 3, 4])

    def test_a_one_bar_ramp_is_just_the_maximum(self):
        self.assertEqual(tl.ratchet_rung(0, 1), tl.RATCHET_MAX)

    def test_it_never_goes_backwards(self):
        for bars in (2, 3, 4, 6, 8, 12, 16):
            values = [tl.ratchet_rung(s, bars) for s in range(bars)]
            self.assertEqual(values, sorted(values), f"{bars} bars")

    def test_it_stays_inside_the_legal_range(self):
        for bars in (1, 2, 4, 8, 16):
            for step in range(-2, bars + 3):
                value = tl.ratchet_rung(step, bars)
                self.assertGreaterEqual(value, 1)
                self.assertLessEqual(value, tl.RATCHET_MAX)

    def test_past_the_end_it_holds_the_maximum(self):
        # A missed poll must not drop the roll back to nothing mid-build.
        self.assertEqual(tl.ratchet_rung(99, 4), tl.RATCHET_MAX)

    def test_a_zero_length_ramp_is_the_maximum_not_a_division_by_zero(self):
        self.assertEqual(tl.ratchet_rung(0, 0), tl.RATCHET_MAX)


class TestArmMacroTable(unittest.TestCase):
    """ARM's pad row, which a snapshot may store by index."""

    def test_it_is_append_only_in_the_shipped_order(self):
        self.assertEqual(tl.ARM_MACROS[:2], ("drop", "chance"))
        self.assertEqual(tl.ARM_MACROS[2:6],
                         ("half", "double", "break", "ratchet"))
        # Gate collapse took pad 6 on 2026-08-31 - the FIRST of the two free
        # macro slots, and the only one of the owner's twelve that is
        # armed-macro-shaped: it lands on a bar and returns. Pad 7 stays free
        # for TURN, retrograde, velocity swell or punch-in, all of which are
        # the same shape and already on the list.
        self.assertEqual(tl.ARM_MACROS[6], "gate")

    def test_it_still_fits_the_top_half_of_the_grid(self):
        # Pads 0-7 are the macros and 8-15 the length ring. A seventh entry is
        # fine; a ninth would silently land on a length pad.
        self.assertLessEqual(len(tl.ARM_MACROS), 8)

    def test_every_macro_has_a_word_on_the_pending_page(self):
        # A page that drew a blank for an armed macro would be hiding exactly
        # what it exists to show.
        for macro in tl.ARM_MACROS:
            self.assertIn(macro, tl.PENDING_NAMES, macro)

    def test_the_mutepath_pair_is_both_macros_and_both_return_legs(self):
        for name in tl.MUTEPATH_MACROS:
            self.assertIn(name, tl.PENDING_NAMES, name)


class TestMuteGrid(unittest.TestCase):
    """MUTE held: the eight channels twice over, now and queued."""

    def test_the_top_half_is_the_channels_now(self):
        for pad in range(8):
            self.assertEqual(tl.mute_pad_channel(pad), (pad, False))

    def test_the_bottom_half_is_the_same_channels_queued(self):
        # SAME ORDER, so the queued pad sits directly under its own channel.
        for pad in range(8, 16):
            self.assertEqual(tl.mute_pad_channel(pad), (pad - 8, True))

    def test_a_pad_outside_the_grid_is_None(self):
        self.assertIsNone(tl.mute_pad_channel(16))
        self.assertIsNone(tl.mute_pad_channel(-1))

    def test_an_audible_channel_is_full_and_a_muted_one_is_dark(self):
        hue = 0xFF0000
        self.assertEqual(tl.mute_pad_state(hue, False), (hue, tl.PAD_FULL))
        self.assertEqual(tl.mute_pad_state(hue, True), (hue, tl.PAD_OFF))

    def test_the_hue_is_always_the_channels_own(self):
        # Hue is identity on this surface and has been since the Group LEDs.
        for group, spec in enumerate(tl.CHANNELS):
            colour = spec[3]
            self.assertEqual(tl.mute_pad_state(colour, False)[0], colour)
            self.assertEqual(
                tl.mute_pad_state(colour, False, True, is_queue_row=True)[0],
                colour)

    def test_a_queue_row_pad_shows_the_CHANGE_not_the_state(self):
        # Otherwise the bottom half would duplicate the top half and say
        # nothing the top row does not.
        hue = 0xFF0000
        self.assertEqual(
            tl.mute_pad_state(hue, False, None, is_queue_row=True)[1],
            tl.PAD_OFF)
        self.assertEqual(
            tl.mute_pad_state(hue, True, None, is_queue_row=True)[1],
            tl.PAD_OFF)
        self.assertEqual(
            tl.mute_pad_state(hue, False, True, is_queue_row=True)[1],
            tl.MUTE_QUEUED)
        self.assertEqual(
            tl.mute_pad_state(hue, True, False, is_queue_row=True)[1],
            tl.MUTE_QUEUED)

    def test_the_three_brightnesses_are_distinct(self):
        self.assertEqual(len({tl.PAD_FULL, tl.MUTE_QUEUED, tl.PAD_OFF}), 3)

    def test_mute_is_bound_and_not_stepwise(self):
        self.assertEqual(tl.BUTTONS_STATEFUL[33], "mute")
        self.assertNotIn(33, tl.BUTTONS_PRESS)
        self.assertFalse(tl.overlay_is_stepwise("mute"))

    def test_mute_sits_below_arm_and_above_mod(self):
        order = tl.OVERLAY_PRIORITY
        self.assertLess(order.index("arm"), order.index("mute"))
        self.assertLess(order.index("mute"), order.index("mod"))
        self.assertEqual(tl.pad_owner(mute=True, mod=True), "mute")
        self.assertEqual(tl.pad_owner(mute=True, arm=True), "arm")
        self.assertEqual(tl.pad_owner(mute=True, shift=True), "shift")
        self.assertEqual(tl.pad_owner(mute=True), "mute")


class TestRepeatLabel(unittest.TestCase):

    def test_inactive_says_nothing(self):
        self.assertEqual(tl.repeat_label("CTRL", False), "CTRL")

    def test_active_says_how_many_channels_it_took(self):
        # Beat repeat skips player-owned channels because a take has no euclid
        # parameters to regenerate from. A gesture that quietly missed two of
        # eight must say so.
        self.assertEqual(tl.repeat_label("CTRL", True, 8), "CTRL RPT8")
        self.assertEqual(tl.repeat_label("CTRL", True, 6), "CTRL RPT6")

    def test_the_floor_is_one_beat(self):
        # There is no half-bar repeat: getLength() is beats * PPQN.
        self.assertEqual(tl.REPEAT_BEATS, 1)

    def test_one_beat_is_a_different_number_of_steps_per_division(self):
        # The floor is stated in beats and FELT in steps: one step at 1/4,
        # eight at 1/32. A limit stated without its division is how the
        # polymeter claim came to be false.
        self.assertEqual(tl.DIVISION_SPB[tl.DIVISION_LABELS.index("1/4")], 1)
        self.assertEqual(tl.DIVISION_SPB[tl.DIVISION_LABELS.index("1/32")], 8)

    def test_repeat_is_bound_stateful_because_the_release_is_the_event(self):
        self.assertEqual(tl.BUTTONS_STATEFUL[6], "repeat")
        self.assertNotIn(6, tl.BUTTONS_PRESS)


class TestFxGanging(unittest.TestCase):
    """One knob, how many objects."""

    def test_the_per_chain_inserts_are_ganged(self):
        # reverb and delay sit on all eight chains, so a knob writes eight
        # times - which is also why an effect there costs eight times what it
        # looks like.
        self.assertTrue(tl.fx_is_ganged("reverb"))
        self.assertTrue(tl.fx_is_ganged("delay"))

    def test_the_master_insert_is_not(self):
        # One processor on chain 0. One write.
        self.assertFalse(tl.fx_is_ganged(tl.FX_MAIN))

    def test_an_unknown_family_is_not_ganged(self):
        # Fail closed: writing once to something unrecognised is recoverable,
        # writing eight times to it is not.
        self.assertFalse(tl.fx_is_ganged("nonsense"))

    def test_a_main_verb_is_global_so_MOD_keys_it_without_a_channel(self):
        verb = tl.VERB_FX + tl.FX_MAIN + ":freq"
        self.assertTrue(tl.mod_is_global(verb))
        self.assertTrue(tl.mod_allowed(verb))


class TestNoteBaseOsc(unittest.TestCase):
    """The message that keeps the daemon's pad octave and ours agreeing."""

    def test_it_carries_the_base_as_an_integer(self):
        import maschine_mk2_lib as mlib
        msg = mlib.maschine_mk2_lib.note_base_osc(48)
        self.assertIn(b"/maschine/midi_note_base", msg)

    def test_every_group_has_a_base_twelve_apart(self):
        # The daemon's own table: group N starts at 24 + 12N. A mismatch here
        # is invisible until a pad press decodes out of range and is dropped
        # without a sound or a log.
        bases = [24 + 12 * n for n in range(8)]
        self.assertEqual(bases, [24, 36, 48, 60, 72, 84, 96, 108])


class TestClaimClears(unittest.TestCase):
    """Does the first captured note wipe what the generator wrote?

    Measured on the rig 2026-08-22: it did not, so a REC take on a voice
    landed ON TOP of the Turing line instead of replacing it, and the player
    heard both at once. On a DRUM it must still stack - a drum overdub is how
    a euclidean pattern gets a hand-placed accent, and clearing there would
    silence the whole channel on the first tap."""

    def test_a_voice_take_replaces_the_line(self):
        self.assertTrue(tl.claim_clears("voice"))

    def test_a_drum_take_stacks(self):
        self.assertFalse(tl.claim_clears("drum"))

    def test_an_unknown_kind_stacks(self):
        # The safe side: stacking loses nothing, clearing loses a pattern.
        self.assertFalse(tl.claim_clears(None))
        self.assertFalse(tl.claim_clears("mystery"))


class TestArmLabel(unittest.TestCase):
    """The picker has to say what it is about to arm."""

    def test_nothing_while_arm_is_not_held(self):
        self.assertEqual(tl.arm_label("CTRL", False, "drop"), "CTRL")

    def test_held_with_nothing_picked_asks(self):
        self.assertEqual(tl.arm_label("CTRL", True, None), "CTRL ARM?")

    def test_held_names_the_macro(self):
        self.assertEqual(tl.arm_label("CTRL", True, "drop"), "CTRL ARM DROP")
        self.assertEqual(tl.arm_label("CTRL", True, "break"), "CTRL ARM BREAK")
        self.assertEqual(tl.arm_label("CTRL", True, "chance"), "CTRL ARM THIN")

    def test_every_armable_macro_has_a_name_to_show(self):
        for macro in tl.ARM_MACROS:
            out = tl.arm_label("X", True, macro)
            self.assertNotEqual(out, "X ARM?")
            self.assertTrue(out.startswith("X ARM "))


class TestModRateLabel(unittest.TestCase):
    """A number instead of a moving marker - owner's idea, 2026-08-20."""

    def test_bars_above_one_read_as_a_count(self):
        self.assertEqual(tl.rate_word(16.0), "16B")
        self.assertEqual(tl.rate_word(4.0), "4B")
        self.assertEqual(tl.rate_word(1.0), "1B")

    def test_below_one_reads_as_a_fraction(self):
        # "0.25B" is a number nobody thinks in; 1/4 is already the word on the
        # DIVIDE column.
        self.assertEqual(tl.rate_word(0.5), "1/2")
        self.assertEqual(tl.rate_word(0.25), "1/4")
        self.assertEqual(tl.rate_word(0.0625), "1/16")

    def test_every_shipped_rate_has_a_word(self):
        for rate in tl.MOD_RATES:
            self.assertTrue(tl.rate_word(rate))

    def test_the_label_is_untouched_when_mod_is_off(self):
        self.assertEqual(tl.mod_rate_label("CTRL", False, 4.0), "CTRL")

    def test_mod_on_with_nothing_bound_still_says_MOD(self):
        self.assertEqual(tl.mod_rate_label("CTRL", True, None), "CTRL MOD")

    def test_mod_on_with_a_binding_names_the_rate(self):
        self.assertEqual(tl.mod_rate_label("CTRL", True, 8.0), "CTRL MOD 8B")
        self.assertEqual(tl.mod_rate_label("CTRL", True, 0.25), "CTRL MOD 1/4")


class TestFreezeHoldsMacros(unittest.TestCase):
    """An armed macro must not land while the machine is frozen."""

    def test_a_tap_freezes_macros(self):
        # Found by playing it: an armed DROP fired while frozen and muted
        # every channel. FREEZE promises nothing changes under you, and a
        # macro landing is the largest change this instrument makes.
        self.assertTrue(tl.freeze_blocks("macro", True, False))

    def test_a_hold_freezes_macros_too(self):
        self.assertTrue(tl.freeze_blocks("macro", False, True))

    def test_thawed_lets_them_through(self):
        self.assertFalse(tl.freeze_blocks("macro", False, False))

    def test_macros_are_in_the_generative_set(self):
        self.assertIn("macro", tl.FREEZE_GENERATIVE)


class TestFreezeMemo(unittest.TestCase):
    """A countdown must not keep counting while the machine is held.

    Measured 2026-08-21: the landing bar went by under a FREEZE, remaining()
    floored at zero, and the ruler advertised zero bars left for nine bars
    while nothing landed."""

    def test_unfrozen_the_memo_is_empty(self):
        self.assertEqual(tl.freeze_memo({"drop": 2}, {"drop": 1}, False), {})

    def test_frozen_it_takes_the_first_value_it_sees(self):
        self.assertEqual(tl.freeze_memo({}, {"drop": 2}, True), {"drop": 2})

    def test_frozen_it_does_not_follow_the_live_value_down(self):
        # The whole point: the live number falls to zero and stays there.
        self.assertEqual(tl.freeze_memo({"drop": 2}, {"drop": 0}, True),
                         {"drop": 2})

    def test_a_macro_armed_during_a_freeze_is_held_from_where_it_started(self):
        memo = tl.freeze_memo({"drop": 2}, {"drop": 0, "break": 4}, True)
        self.assertEqual(memo, {"drop": 2, "break": 4})

    def test_a_macro_that_leaves_the_queue_leaves_the_memo(self):
        # Keyed off `live`, so a cancelled macro cannot strand an entry that
        # would then be reused by a later macro of the same name.
        self.assertEqual(tl.freeze_memo({"drop": 2}, {"break": 1}, True),
                         {"break": 1})

    def test_thawing_clears_it_so_the_live_numbers_take_over(self):
        held = tl.freeze_memo({}, {"drop": 3}, True)
        self.assertEqual(tl.freeze_memo(held, {"drop": 0}, False), {})


class TestPendingColumnsFrozen(unittest.TestCase):
    """The PENDING page says HELD rather than a countdown that is not
    counting."""

    def test_frozen_a_column_says_held(self):
        col = tl.pending_columns([("drop", 0, 4)], frozen=True)[0]
        self.assertEqual(col["value"], "HELD")

    def test_unfrozen_it_still_says_the_number(self):
        col = tl.pending_columns([("drop", 2, 4)])[0]
        self.assertEqual(col["value"], "0002")

    def test_the_name_and_the_bar_are_untouched_by_the_freeze(self):
        # Only the number is a lie while frozen; the macro's name and how far
        # through it is are both still true.
        live = tl.pending_columns([("drop", 2, 4)])[0]
        held = tl.pending_columns([("drop", 2, 4)], frozen=True)[0]
        self.assertEqual(live["name"], held["name"])
        self.assertEqual(live["frac"], held["frac"])

    def test_an_empty_page_still_says_none_when_frozen(self):
        col = tl.pending_columns([], frozen=True)[0]
        self.assertEqual(col["name"], "NONE")
class TestSessionLine(unittest.TestCase):
    """The play-session log's grammar. The driver owns the file; this owns
    the line, so it can be read on WSL where the driver cannot be imported."""

    STAMP = 1755770000.123

    def _line(self, tag, **fields):
        return tl.session_line(self.STAMP, tag, fields)

    def test_the_stamp_carries_milliseconds(self):
        # Ordering is the question this log answers - did the freeze latch
        # before or after the tick that should have fired the macro - and a
        # one-second stamp cannot answer it.
        head = self._line("tick").split(" ")[0]
        self.assertRegex(head, r"^\d\d:\d\d:\d\d\.\d\d\d$")

    def test_fields_keep_the_order_they_were_given(self):
        line = self._line("arm", macro="drop", bars=4)
        self.assertTrue(line.endswith("arm macro=drop bars=4\n"))

    def test_a_missing_value_prints_a_dash_and_keeps_its_column(self):
        # A field that vanishes when it is None makes a log that cannot be
        # counted by column.
        self.assertIn("chan=-", self._line("mute", chan=None))

    def test_booleans_print_as_one_and_zero(self):
        self.assertIn("frozen=1", self._line("tick", frozen=True))
        self.assertIn("frozen=0", self._line("tick", frozen=False))

    def test_a_collection_prints_sorted_and_comma_joined(self):
        self.assertIn("survivors=0,1", self._line("drop", survivors={1, 0}))

    def test_an_empty_collection_is_a_dash_not_an_empty_column(self):
        # DROP with no survivors mutes all eight - the exact state that took
        # the rig silent. It must not read as a blank.
        self.assertIn("survivors=-", self._line("drop", survivors=[]))

    def test_every_line_ends_in_exactly_one_newline(self):
        line = self._line("tick", bar=3)
        self.assertTrue(line.endswith("\n"))
        self.assertFalse(line.rstrip("\n").endswith("\n"))


class TestPhaseError(unittest.TestCase):
    """The phrase clock's correction term. Measured drift is 3,896 ppm and
    linear; this is the signed, wrapped distance it is corrected against."""

    def test_no_error_when_the_position_is_the_reference(self):
        self.assertEqual(tl.phase_error(96, 96, 384), 0.0)

    def test_ahead_reads_positive(self):
        self.assertEqual(tl.phase_error(100, 96, 384), 4.0)

    def test_behind_reads_negative(self):
        self.assertEqual(tl.phase_error(92, 96, 384), -4.0)

    def test_a_small_error_across_the_loop_point_stays_small(self):
        # The one that matters. Unwrapped this reads as 380 and jerks the
        # clock most of a bar the wrong way, once per pattern, for ever.
        self.assertEqual(tl.phase_error(2, 382, 384), 4.0)
        self.assertEqual(tl.phase_error(382, 2, 384), -4.0)

    def test_it_never_leaves_the_half_open_half_circle(self):
        for pos in range(0, 384):
            err = tl.phase_error(pos, 0, 384)
            self.assertGreaterEqual(err, -192.0)
            self.assertLess(err, 192.0)

    def test_exactly_half_a_pattern_reads_negative_not_positive(self):
        # Half is arbitrary but must be DECIDED, or the correction oscillates
        # between two equally valid readings on adjacent bars.
        self.assertEqual(tl.phase_error(192, 0, 384), -192.0)

    def test_an_unusable_length_gives_no_correction_rather_than_a_wrong_one(self):
        self.assertIsNone(tl.phase_error(10, 0, 0))
        self.assertIsNone(tl.phase_error(10, 0, None))


class TestDeviceReconnected(unittest.TestCase):
    """The decision behind the full repaint after a replug.

    The udev rule restarts the daemon when the MK2 is plugged in and
    deliberately leaves the UI alone, so the driver keeps a cache describing a
    surface that no longer exists and correctly judges every write redundant.
    The device node is the evidence: udev recreates /dev/maschine on every
    plug, so a token built from it moves exactly when the surface has been
    wiped."""

    def test_an_unchanged_token_is_not_a_reconnect(self):
        self.assertFalse(tl.device_reconnected(("hidraw1", 42), ("hidraw1", 42)))

    def test_a_new_node_is_a_reconnect(self):
        self.assertTrue(tl.device_reconnected(("hidraw1", 42), ("hidraw2", 43)))

    def test_the_same_name_with_a_new_inode_is_a_reconnect(self):
        # A replug can land on the same hidraw number. The inode is what
        # distinguishes "still the device I painted" from "a fresh one".
        self.assertTrue(tl.device_reconnected(("hidraw1", 42), ("hidraw1", 43)))

    def test_a_vanished_device_is_not_a_reconnect(self):
        # Unplugged. There is nothing to repaint and nothing to be wrong
        # about - the repaint is owed when it comes BACK.
        self.assertFalse(tl.device_reconnected(("hidraw1", 42), None))

    def test_coming_back_after_a_vanish_is_a_reconnect(self):
        self.assertTrue(tl.device_reconnected(None, ("hidraw1", 43)))

    def test_still_absent_is_not_a_reconnect(self):
        self.assertFalse(tl.device_reconnected(None, None))

    def test_an_unplugged_replug_cycle_owes_exactly_one_repaint(self):
        # The poll tick runs at 1 Hz, so a replug is seen as several ticks of
        # absence and then presence. Only the first present tick may repaint;
        # anything else is a full surface rewrite once a second, which is the
        # traffic that wedges the controller.
        seen = [("hidraw1", 42)] + [None] * 4 + [("hidraw1", 77)] * 5
        repaints = sum(
            tl.device_reconnected(seen[i - 1], seen[i])
            for i in range(1, len(seen)))
        self.assertEqual(repaints, 1)


class TestPadPressure(unittest.TestCase):
    """Pad aftertouch -> a positive offset over the knob.

    The MK2's pads stream 12-bit pressure and the daemon shipped it disabled
    from its first commit until 2026-08-30. These are the pure parts: the
    driver does the plumbing, and this is everything that can be tested off
    the rig."""

    def test_zero_pressure_is_no_offset(self):
        self.assertEqual(tl.pressure_offset(0, 0, 127), 0.0)

    def test_full_pressure_reaches_the_top_of_the_span(self):
        # A hand mashing a pad must be able to reach the end stop, or the
        # gesture reads as broken.
        self.assertAlmostEqual(tl.pressure_offset(127, 0, 127), 127.0)

    def test_offset_is_monotonic_in_pressure(self):
        last = -1.0
        for v in range(0, 128):
            off = tl.pressure_offset(v, 0, 127)
            self.assertGreaterEqual(off, last)
            last = off

    def test_offset_scales_with_the_span_not_the_midi_range(self):
        # A verb with a 0-100 span must not be pushed to 127.
        self.assertAlmostEqual(tl.pressure_offset(127, 0, 100), 100.0)

    def test_offset_never_exceeds_the_span_width(self):
        for lo, hi in ((0, 127), (0, 100), (20, 80)):
            self.assertLessEqual(tl.pressure_offset(127, lo, hi), hi - lo)

    def test_depth_scales_the_offset(self):
        self.assertAlmostEqual(tl.pressure_offset(127, 0, 127, depth=0.5), 63.5)

    def test_zero_depth_disables_it_without_a_branch(self):
        self.assertEqual(tl.pressure_offset(127, 0, 127, depth=0.0), 0.0)

    def test_value_is_base_plus_offset(self):
        self.assertAlmostEqual(tl.pressure_value(40, 20, 0, 127), 60.0)

    def test_value_clamps_to_the_top_of_the_span(self):
        # Base near the ceiling plus a full squeeze must not wrap or overshoot.
        self.assertAlmostEqual(tl.pressure_value(120, 60, 0, 127), 127.0)

    def test_value_clamps_to_the_bottom_of_the_span(self):
        self.assertAlmostEqual(tl.pressure_value(10, -40, 20, 80), 20.0)

    def test_value_with_no_offset_is_the_base_exactly(self):
        # The restore write. If this drifts, letting go of a pad leaves the
        # knob somewhere the player never put it.
        self.assertEqual(tl.pressure_value(64, 0, 0, 127), 64.0)

    def test_decay_sheds_part_of_the_offset(self):
        self.assertLess(tl.pressure_decay(100.0), 100.0)
        self.assertGreater(tl.pressure_decay(100.0), 0.0)

    def test_decay_reaches_exactly_zero(self):
        # It must SNAP, not asymptote: a residual 0.4 of cutoff would sit on
        # the channel forever and nothing would ever restore the base.
        off = 127.0
        for _ in range(100):
            off = tl.pressure_decay(off)
        self.assertEqual(off, 0.0)

    def test_decay_of_zero_stays_zero(self):
        self.assertEqual(tl.pressure_decay(0.0), 0.0)

    def test_decay_is_monotonic_down(self):
        off, seen = 127.0, []
        for _ in range(20):
            off = tl.pressure_decay(off)
            seen.append(off)
        self.assertEqual(seen, sorted(seen, reverse=True))

    def test_decay_never_goes_negative(self):
        for start in (0.0, 0.1, 0.6, 1.0, 5.0, 127.0):
            self.assertGreaterEqual(tl.pressure_decay(start), 0.0)

    def test_the_target_verb_is_a_timbre_verb(self):
        # The modulation law: a modulator may only drive a verb that does NOT
        # rewrite the pattern. Pressure is a modulator by another name, so it
        # inherits the law - and GATE and VELO were removed from that set for
        # destroying a recorded take.
        self.assertIn(tl.PRESSURE_VERB, tl.MOD_TIMBRE)

    def test_the_target_verb_is_not_a_drift_verb(self):
        self.assertFalse(tl.is_drift(tl.PRESSURE_VERB))


class TestGeneratorMayWrite(unittest.TestCase):
    """The one guard every pattern-rewriting generator asks.

    Three of P1's five features rewrite the pattern at the wrap - the path that
    destroyed a recorded take through the velo defect. _drift_channel already
    solved it and shipped; this is that solution as one predicate, so a fourth
    generator cannot get it subtly wrong."""

    def test_an_idle_generator_on_a_generated_channel_may_write(self):
        self.assertTrue(tl.generator_may_write("drift", False, False, None))

    def test_a_player_owned_channel_is_refused(self):
        self.assertFalse(tl.generator_may_write("drift", False, False,
                                                "player"))

    def test_freeze_refuses_a_generated_channel(self):
        self.assertFalse(tl.generator_may_write("drift", True, False, None))

    def test_a_deep_freeze_refuses_it_too(self):
        self.assertFalse(tl.generator_may_write("drift", False, True, None))

    def test_ownership_is_refused_even_while_thawed(self):
        self.assertFalse(tl.generator_may_write("melody", False, False,
                                                "player"))

    def test_a_generator_freeze_does_not_name_is_still_owner_gated(self):
        # "lfo" is not in FREEZE_GENERATIVE, so a latched freeze does not hold
        # it - but ownership still does. The two gates are independent.
        self.assertTrue(tl.generator_may_write("lfo", True, False, None))
        self.assertFalse(tl.generator_may_write("lfo", True, False, "player"))

    def test_a_generator_owned_channel_is_not_a_player_owned_one(self):
        self.assertTrue(tl.generator_may_write("drift", False, False,
                                               "generator"))


class TestRotateLine(unittest.TestCase):
    """ROTATE on a voice - owner's decision, 2026-08-31: rotate the LINE.

    The same melody, starting somewhere else in the bar. NOT clocking the pitch
    register, which walks to a different melody; that reading was rejected
    because a voice's neighbourhood is already reachable through REROLL."""

    NOTES = [60, 62, 64, 65]
    MASK = (True, False, True, True)

    def test_no_rotation_is_the_identity(self):
        notes, mask = tl.rotate_line(self.NOTES, self.MASK, 0)
        self.assertEqual(notes, list(self.NOTES))
        self.assertEqual(mask, tuple(self.MASK))

    def test_one_step_moves_the_line_forward(self):
        notes, mask = tl.rotate_line(self.NOTES, self.MASK, 1)
        self.assertEqual(notes, [65, 60, 62, 64])
        self.assertEqual(mask, (True, True, False, True))

    def test_notes_and_rests_rotate_together(self):
        # The failure this function exists to prevent: a melody that slides
        # while its rhythm stands still is not the same melody moved.
        for count in range(1, 8):
            notes, mask = tl.rotate_line(self.NOTES, self.MASK, count)
            for i, sounding in enumerate(mask):
                origin = (i - count) % len(self.NOTES)
                self.assertEqual(sounding, self.MASK[origin])
                self.assertEqual(notes[i], self.NOTES[origin])

    def test_a_full_rotation_returns_the_original(self):
        notes, mask = tl.rotate_line(self.NOTES, self.MASK, len(self.NOTES))
        self.assertEqual(notes, list(self.NOTES))
        self.assertEqual(mask, tuple(self.MASK))

    def test_rotation_wraps_past_the_pattern_length(self):
        self.assertEqual(tl.rotate_line(self.NOTES, self.MASK, 5),
                         tl.rotate_line(self.NOTES, self.MASK, 1))

    def test_it_rotates_the_same_way_the_drum_verb_does(self):
        # ROTATE must mean ONE thing on this instrument. If these two ever
        # disagree, the same word moves two kinds of channel in opposite
        # directions and nothing in the surface would say so.
        import maschine_mk2_lib as _m
        drum = _m.maschine_mk2_lib.rotate(list(self.MASK), 1)
        _, mask = tl.rotate_line(self.NOTES, self.MASK, 1)
        self.assertEqual(list(mask), drum)

    def test_an_empty_line_rotates_to_nothing(self):
        self.assertEqual(tl.rotate_line([], (), 3), ([], ()))

    def test_a_negative_rotation_moves_the_line_backward(self):
        notes, mask = tl.rotate_line(self.NOTES, self.MASK, -1)
        self.assertEqual(notes, [62, 64, 65, 60])


class TestChordWalker(unittest.TestCase):
    """The walker that moves the shared root every N bars.

    The global-scale half of this feature shipped long ago - ROOT and SCALE are
    already global verbs, already drive all three voices, and a key change
    already lands on the bar. Only the walker was ever missing."""

    def test_walk_at_zero_never_comes_due(self):
        # 0 is LOCK, the same grammar as MELODY and RHYTHM at zero.
        for bar in range(64):
            self.assertFalse(tl.walk_due(bar, 0))

    def test_a_negative_rate_is_locked_too(self):
        self.assertFalse(tl.walk_due(4, -1))

    def test_every_fourth_bar_comes_due_four_bars_apart(self):
        due = [bar for bar in range(16) if tl.walk_due(bar, 4)]
        self.assertEqual(due, [0, 4, 8, 12])

    def test_a_span_of_zero_holds_the_root_still(self):
        rng = random.Random(1).random
        self.assertEqual(tl.walk_next(0, 0, rng), 0)

    def test_the_walk_stays_inside_its_span(self):
        rng = random.Random(3).random
        degree = 0
        for _ in range(500):
            degree = tl.walk_next(degree, 2, rng)
            self.assertGreaterEqual(degree, -2)
            self.assertLessEqual(degree, 2)

    def test_the_walk_moves_one_degree_at_a_time(self):
        rng = random.Random(5).random
        degree = 0
        for _ in range(200):
            nxt = tl.walk_next(degree, 3, rng)
            self.assertEqual(abs(nxt - degree), 1)
            degree = nxt

    def test_the_walk_reaches_both_sides_of_its_base(self):
        rng = random.Random(11).random
        seen, degree = set(), 0
        for _ in range(400):
            degree = tl.walk_next(degree, 2, rng)
            seen.add(degree)
        self.assertIn(-2, seen)
        self.assertIn(2, seen)

    def test_an_edge_reflects_rather_than_sticking(self):
        # At the top of its span the walk must come back, not sit there. A
        # clamp would park the key at the edge and read as a broken walker.
        rng = random.Random(2).random
        self.assertEqual(tl.walk_next(2, 2, rng), 1)

    def test_degree_zero_is_the_root_the_player_set(self):
        self.assertEqual(tl.walk_root(5, 0, 0), 5)

    def test_the_walker_moves_along_the_scale_not_by_semitones(self):
        # A progression stays in key: the root steps by the scale's own
        # intervals. Stepping by semitones would transpose out of the scale
        # the three voices are sharing, which is the opposite of the request.
        intervals = tl.SCALES[0][1]
        self.assertEqual(tl.walk_root(0, 1, 0), intervals[1])
        self.assertEqual(tl.walk_root(0, 2, 0), intervals[2])

    def test_walking_below_the_root_stays_in_key(self):
        intervals = tl.SCALES[0][1]
        self.assertEqual(tl.walk_root(0, -1, 0), intervals[-1] - 12)


class TestDrumRhythmRegister(unittest.TestCase):
    """Reading (b) of the soft randomiser: drums get the evolving generator the
    voices already have. Reading (a), per-step probability, shipped 2026-08-19.

    On a voice the rhythm register decides which steps sound outright. On a
    drum, euclid already decided - so the register is SUBTRACTIVE, and that is
    what keeps HITS meaning the number of hits."""

    def test_a_new_drum_channel_is_locked_and_full(self):
        st = tl.default_channel_state("drum")
        self.assertEqual(st["rhythm"], 0)
        self.assertEqual(st["rhythm_reg"], 0xFFFF)

    def test_an_old_snapshot_gains_the_defaults(self):
        # The class of bug that took the instrument silent for three hours on
        # 2026-08-18: a dict short a key is a KeyError on the repaint path.
        old = {"kit": "808", "sample": "BD", "level": 19, "range": 4}
        st = tl.upgrade_state("drum", old, 16)
        self.assertEqual(st["rhythm"], 0)
        self.assertEqual(st["rhythm_reg"], 0xFFFF)
        self.assertEqual(st["kit"], "808")

    def test_the_default_register_changes_no_existing_pattern(self):
        pattern = [True, False, False, True, False, False, True, False]
        self.assertEqual(tl.drum_steps(pattern, 0xFFFF), tuple(pattern))

    def test_a_cleared_bit_silences_that_step(self):
        pattern = [True, True, True, True]
        self.assertEqual(tl.drum_steps(pattern, 0b1101),
                         (True, False, True, True))

    def test_the_register_can_never_add_a_hit(self):
        # If it could, HITS would stop meaning the number of hits and the
        # euclid encoder would be lying about its own pattern.
        pattern = [False, False, False, False]
        self.assertEqual(tl.drum_steps(pattern, 0xFFFF),
                         (False, False, False, False))

    def test_only_the_pattern_s_own_bits_are_read(self):
        # A 12-step triplet division must not pick up bits 12-15 left behind
        # by a 16-step one - the same rule rhythm_mask already obeys.
        pattern = [True] * 12
        self.assertEqual(len(tl.drum_steps(pattern, 0xFFFF)), 12)

    def test_an_evolving_register_only_ever_thins_the_line(self):
        rng = random.Random(9).random
        pattern = [True, False, True, True, False, True, False, False]
        reg = 0xFFFF
        for _ in range(50):
            reg = tl.mutate(reg, len(pattern), 0.2, rng)
            out = tl.drum_steps(pattern, reg)
            for i, step in enumerate(out):
                if step:
                    self.assertTrue(pattern[i])


class TestWanderingVoice(unittest.TestCase):
    """A fourth way for a channel to behave: a bounded random walk instead of a
    shift register.

    Shipped as a per-voice MODEL switch, NOT a third channel kind - 42 binary
    kind tests and six driver sites written `!= "voice"` would have routed a
    third kind down the DRUM path with no error and no log. The walk produces
    values in the register's own domain, so pitch, scale, octave and range are
    untouched downstream."""

    def test_it_yields_one_value_per_step(self):
        rng = random.Random(1).random
        self.assertEqual(len(tl.walk_values(64, 8, 12, 20, 3, rng)), 12)

    def test_a_span_of_zero_holds_one_note(self):
        # Audible and honest: a walk with nowhere to go is a held note, not a
        # silent channel. A silent channel must say why; this one has nothing
        # to explain because it is sounding.
        rng = random.Random(1).random
        self.assertEqual(tl.walk_values(100, 8, 8, 0, 4, rng), [100] * 8)

    def test_a_stride_of_zero_holds_one_note_too(self):
        rng = random.Random(1).random
        self.assertEqual(tl.walk_values(100, 8, 8, 30, 0, rng), [100] * 8)

    def test_it_starts_where_it_was_told_to(self):
        rng = random.Random(1).random
        self.assertEqual(tl.walk_values(77, 8, 6, 20, 3, rng)[0], 77)

    def test_the_walk_stays_inside_its_span(self):
        rng = random.Random(4).random
        for value in tl.walk_values(128, 8, 400, 10, 3, rng):
            self.assertGreaterEqual(value, 118)
            self.assertLessEqual(value, 138)

    def test_the_walk_stays_inside_the_register_domain(self):
        # pitch() shifts by `length`, so a value outside 0..2^length-1 would
        # quantise to a degree that does not exist.
        rng = random.Random(6).random
        for value in tl.walk_values(2, 8, 500, 200, 7, rng):
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 255)

    def test_a_span_wider_than_the_register_is_bounded_by_the_register(self):
        rng = random.Random(8).random
        for value in tl.walk_values(4, 4, 300, 999, 2, rng):
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 15)

    def test_it_actually_wanders(self):
        rng = random.Random(12).random
        values = tl.walk_values(64, 8, 64, 40, 5, rng)
        self.assertGreater(len(set(values)), 1)

    def test_the_same_seed_walks_the_same_way(self):
        # A walk you cannot reproduce is a walk you cannot save.
        a = tl.walk_values(64, 8, 32, 20, 3, random.Random(21).random)
        b = tl.walk_values(64, 8, 32, 20, 3, random.Random(21).random)
        self.assertEqual(a, b)

    def test_a_new_voice_uses_the_register_and_not_the_walk(self):
        # Zero must be bit-identical to today, exactly as the rhythm generator
        # shipped without changing any existing voice.
        st = tl.default_channel_state("voice")
        self.assertEqual(st["model"], tl.MODEL_REGISTER)

    def test_an_old_snapshot_comes_back_on_the_register(self):
        st = tl.upgrade_state("voice", {"register": 0b1011, "length": 4,
                                        "rhythm_reg": 0xFFFF}, 16)
        self.assertEqual(st["model"], tl.MODEL_REGISTER)


class TestVoiceCrossCoupling(unittest.TestCase):
    """One voice's register feeds another's, so three voices that evolve apart
    can be made to drift together.

    Two other couplings were considered and rejected: reciprocal XOR, which
    makes two voices IDENTICAL inside one tick, and making the target's mutate
    chance depend on the source's bit, which is statistically indistinguishable
    from a slightly different MELODY setting - the player cannot hear it, so it
    is not a feature."""

    REG = 0b10110011
    SRC = 0b11001010

    def test_no_coupling_is_exactly_todays_behaviour(self):
        # Zero must be bit-identical to today, and that includes not disturbing
        # the random stream - an extra rng() call per bit would change every
        # evolving voice on the instrument the day this shipped.
        a = tl.mutate(self.REG, 8, 0.3, random.Random(17).random)
        b = tl.mutate_coupled(self.REG, 8, 0.3, self.SRC, 8, 0.0,
                              random.Random(17).random)
        self.assertEqual(a, b)

    def test_no_coupling_is_the_identity_at_lock(self):
        self.assertEqual(
            tl.mutate_coupled(self.REG, 8, 0.0, self.SRC, 8, 0.0), self.REG)

    def test_full_coupling_at_lock_copies_the_source(self):
        # The degenerate end of the range, and it is reachable on purpose: at
        # full amount the target IS the source, one bar behind. Naming it here
        # so nobody reports it as a bug.
        self.assertEqual(
            tl.mutate_coupled(self.REG, 8, 0.0, self.SRC, 8, 1.0), self.SRC)

    def test_coupling_never_changes_the_source(self):
        source = self.SRC
        tl.mutate_coupled(self.REG, 8, 0.5, source, 8, 0.5,
                          random.Random(1).random)
        self.assertEqual(source, self.SRC)

    def test_the_result_stays_inside_the_target_s_length(self):
        rng = random.Random(2).random
        reg = 0xFFFF
        for _ in range(50):
            reg = tl.mutate_coupled(reg, 5, 0.4, 0xFFFF, 16, 0.6, rng)
            self.assertLess(reg, 1 << 5)

    def test_a_shorter_source_still_feeds_a_longer_target(self):
        # Lengths need not agree: the feed is ONE BIT, not a register copy.
        reg = tl.mutate_coupled(0b10110011, 8, 0.0, 0b101, 3, 1.0)
        self.assertLess(reg, 1 << 8)

    def test_a_cycle_cannot_iterate_within_one_tick(self):
        # A feeds B feeds A is a musically real request. Both reads are of the
        # registers as they were at the START of the tick, so the pair cannot
        # run away inside one wrap.
        a0, b0 = self.REG, self.SRC
        a1 = tl.mutate_coupled(a0, 8, 0.0, b0, 8, 1.0)
        b1 = tl.mutate_coupled(b0, 8, 0.0, a0, 8, 1.0)
        self.assertEqual(a1, b0)
        self.assertEqual(b1, a0)


class TestWalkLine(unittest.TestCase):
    """The walk rendered as notes - line()'s counterpart, so the writer asks
    one function whichever model a voice is on."""

    def test_it_yields_one_note_per_step(self):
        rng = random.Random(1).random
        notes = tl.walk_line(64, 8, 12, 0, 0, 0, 2, 30, 4, rng)
        self.assertEqual(len(notes), 12)

    def test_every_note_is_in_the_scale(self):
        rng = random.Random(3).random
        notes = tl.walk_line(64, 8, 64, 0, 0, 0, 2, 60, 5, rng)
        intervals = tl.SCALES[0][1]
        for note in notes:
            self.assertIn((note - tl.BASE_NOTE) % 12, intervals)

    def test_every_note_is_a_legal_midi_note(self):
        rng = random.Random(5).random
        for note in tl.walk_line(200, 8, 64, 11, 1, 3, 4, 255, 9, rng):
            self.assertGreaterEqual(note, 0)
            self.assertLessEqual(note, 127)

    def test_a_held_walk_repeats_one_note(self):
        notes = tl.walk_line(64, 8, 8, 0, 0, 0, 2, 0, 4)
        self.assertEqual(len(set(notes)), 1)


class TestGenPage(unittest.TestCase):
    """The GEN page carried three of P1's five features in the voice STEP
    ring. It went in the 2026-09-01 collapse and its verbs did not: MODEL and
    RULE are columns on the voice AUTO page, and the walk's own four numbers
    plus the line rotation are the WALK page behind it on the same ring."""

    def _state(self, **over):
        st = tl.default_channel_state("voice")
        st.update(over)
        return st

    def test_the_voice_auto_ring_carries_a_line_page(self):
        # Titled WALK until 2026-09-02. The old title named the half of the
        # page that draws dead most of the time; every live column answers one
        # question - how is this voice's line of pitches built.
        titles = [d["title"] for d in tl.PAGE_RINGS[("AUTO", "voice")]]
        self.assertIn("LINE", titles)
        self.assertNotIn("WALK", titles)

    def test_the_walk_page_verbs_match_what_it_draws(self):
        # verbs decide what an encoder WRITES, _columns_inner what it DRAWS,
        # and nothing checks they agree at runtime. This is that check.
        desc = _page("AUTO", "voice", "LINE")
        self.assertEqual(desc["verbs"],
                         ("rotate", "walk_span", "walk_stride", "feed",
                          "amount", "range", None, None))
        # On the WALK model every one of the six is live. On the register
        # model SPAN and STRIDE draw dead - see the test below.
        cols = tl.columns(desc, "voice", self._state(model=tl.MODEL_WALK))
        self.assertEqual([c["name"] for c in cols][:6],
                         ["ROTATE", "SPAN", "STRIDE", "FEED", "AMT", "RANGE"])
        # MODEL and RULE moved to the AUTO page in front of this one, and are
        # still two separate verbs: RULE was deliberately NOT folded into
        # MODEL when it arrived on 2026-09-01.
        auto = _page("AUTO", "voice", "AUTO")["verbs"]
        self.assertEqual(auto[0], "rule")
        self.assertEqual(auto[1], "model")

    def test_the_UNUSED_columns_draw_dead(self):
        # A lit column that does nothing is the fault this surface must never
        # commit - law L4, draw dead rather than a number the knob cannot move.
        # TWO slots are spare since RANGE arrived here on 2026-09-02, and
        # both are honest about it. It was three.
        desc = _page("AUTO", "voice", "LINE")
        cols = tl.columns(desc, "voice", self._state())
        for index in (6, 7):
            self.assertTrue(cols[index]["grey"], f"column {index + 1}")
        # And the column RANGE landed in is LIVE, which is the point of
        # moving it here rather than dropping it.
        self.assertFalse(cols[5]["grey"])
        self.assertEqual(cols[5]["name"], "RANGE")
        # RULE is live where it moved to, not merely gone from here.
        auto = tl.columns(_page("AUTO", "voice", "AUTO"), "voice",
                          self._state())
        self.assertFalse(auto[0]["grey"])
        self.assertEqual(auto[0]["name"], "RULE")

    def test_a_new_voice_reads_as_the_register_model(self):
        # MODEL is column two of the AUTO page now, which is the index it had
        # on the GEN page - the verb moved, its neighbour count did not.
        desc = _page("AUTO", "voice", "AUTO")
        cols = tl.columns(desc, "voice", self._state())
        self.assertEqual(cols[1]["value"], "REG")

    def test_the_walk_model_says_so(self):
        desc = _page("AUTO", "voice", "AUTO")
        cols = tl.columns(desc, "voice", self._state(model=tl.MODEL_WALK))
        self.assertEqual(cols[1]["value"], "WALK")

    def test_no_feed_reads_as_off(self):
        # A silent channel must say why - and so must a coupling that is not
        # coupled to anything. FEED is column four of the WALK page since the
        # collapse, was column five of GEN.
        desc = _page("AUTO", "voice", "LINE")
        cols = tl.columns(desc, "voice", self._state())
        self.assertEqual(cols[3]["value"], "OFF")


class TestWalkPage(unittest.TestCase):
    """The chord walker's two globals, beside the globals they move.

    They had a page of their own on the ALL ring until 2026-09-01, four of
    whose eight columns were dead. The collapse put WALK and SPAN straight
    onto the GLOBAL page - which is what emptied that page and let it go -
    and the ALL ring became the VOLUME ring when ALL became the lens."""

    def _globals(self, **over):
        g = dict(root=0, scale=0, bpm=125, master=80, revsize=50, revtype=0,
                 dlytime=2, dlyfbk=30, walk=0, wspan=2, pending=set())
        g.update(over)
        return g

    def test_the_walker_is_on_the_global_page(self):
        verbs = _page("VOLUME", None, "GLOBAL")["verbs"]
        self.assertIn("walk", verbs)
        self.assertIn("wspan", verbs)

    def test_the_global_page_draws_root_scale_and_the_walker(self):
        desc = _page("VOLUME", None, "GLOBAL")
        cols = tl.columns(desc, None, self._globals())
        # BPM sits between them now: the walker moved onto the shipped page
        # rather than the page being rebuilt around it.
        self.assertEqual([c["name"] for c in cols][:5],
                         ["ROOT", "SCALE", "BPM", "WALK", "SPAN"])

    def test_a_locked_walker_says_lock_rather_than_a_number(self):
        # 0 is LOCK everywhere else on this instrument; reading "0000" here
        # would invite turning it down looking for off.
        desc = _page("VOLUME", None, "GLOBAL")
        cols = tl.columns(desc, None, self._globals())
        self.assertEqual(cols[3]["value"], "LOCK")

    def test_a_running_walker_shows_its_bar_count(self):
        desc = _page("VOLUME", None, "GLOBAL")
        cols = tl.columns(desc, None, self._globals(walk=4))
        self.assertEqual(cols[3]["value"], "4bar")

    def test_the_global_page_made_room_for_the_walker(self):
        # WAS test_the_shipped_global_page_is_untouched, which held while the
        # walker had a page of its own. It does not now: REVTYPE and DLYFBK
        # gave up these two slots on 2026-09-01. Neither is lost - every port
        # GLOBAL does not name appears on the generated REV and DLY pages.
        desc = tl.PAGE_RINGS[("VOLUME", None)][0]
        cols = tl.columns(desc, None, self._globals())
        self.assertEqual([c["name"] for c in cols],
                         ["ROOT", "SCALE", "BPM", "WALK", "SPAN",
                          "MASTER", "REVSIZE", "DLYTIME"])


class TestGenPageDeadColumns(unittest.TestCase):
    """SPAN and STRIDE belong to the walk. On the register model they are not
    dimmed-but-turnable, they are DEAD - law L4, draw dead rather than a number
    the knob cannot make audible."""

    def _desc(self):
        # The WALK page of the voice AUTO ring since 2026-09-01, where the GEN
        # page's walk verbs went. SPAN and STRIDE are columns 2 and 3 there,
        # one left of where they sat on GEN because MODEL moved to AUTO.
        return _page("AUTO", "voice", "LINE")

    def test_span_and_stride_are_dead_on_the_register_model(self):
        st = tl.default_channel_state("voice")
        cols = tl.columns(self._desc(), "voice", st)
        self.assertTrue(cols[1]["grey"])
        self.assertTrue(cols[2]["grey"])

    def test_they_come_alive_on_the_walk_model(self):
        st = tl.default_channel_state("voice")
        st["model"] = tl.MODEL_WALK
        cols = tl.columns(self._desc(), "voice", st)
        self.assertFalse(cols[1]["grey"])
        self.assertFalse(cols[2]["grey"])


class TestGenStateKeys(unittest.TestCase):
    """Every GEN verb needs a home in the state dict, or apply() has nowhere to
    write and the snapshot has nothing to save."""

    def test_a_new_voice_carries_every_gen_verb(self):
        st = tl.default_channel_state("voice")
        for key in ("rotate", "model", "walk_span", "walk_stride", "feed",
                    "amount"):
            self.assertIn(key, st)

    def test_a_new_voice_is_unrotated_uncoupled_and_on_the_register(self):
        # Zero is bit-identical to today on all three, which is what lets this
        # ship without changing any existing voice.
        st = tl.default_channel_state("voice")
        self.assertEqual(st["rotate"], 0)
        self.assertIsNone(st["feed"])
        self.assertEqual(st["amount"], 0)
        self.assertEqual(st["model"], tl.MODEL_REGISTER)

    def test_an_old_snapshot_gains_them_all(self):
        st = tl.upgrade_state("voice", {"register": 0b1011, "length": 4,
                                        "rhythm_reg": 0xFFFF}, 16)
        self.assertEqual(st["rotate"], 0)
        self.assertIsNone(st["feed"])
        self.assertEqual(st["amount"], 0)

    def test_a_drum_does_not_grow_voice_only_keys(self):
        st = tl.default_channel_state("drum")
        self.assertNotIn("model", st)
        self.assertNotIn("feed", st)


class TestWalkerFreezes(unittest.TestCase):
    """The chord walker is a bar-rate machine and FREEZE must hold it.

    A key change is one of the largest things that can happen under a player
    who has asked for nothing to change - the same argument that put "macro"
    in this set on 2026-08-20, found by playing it."""

    def test_walk_is_a_generative_subject(self):
        self.assertIn("walk", tl.FREEZE_GENERATIVE)

    def test_a_latched_freeze_holds_the_walker(self):
        self.assertTrue(tl.freeze_blocks("walk", True, False))

    def test_a_deep_freeze_holds_it_too(self):
        self.assertTrue(tl.freeze_blocks("walk", False, True))

    def test_a_thawed_walker_runs(self):
        self.assertFalse(tl.freeze_blocks("walk", False, False))

    def test_the_rhythm_subject_now_has_a_caller(self):
        # It sat in this set with NO caller until 2026-08-31 - correct only by
        # accident of an early return elsewhere. The drum rhythm register asks
        # it through generator_may_write, so the entry means something now.
        self.assertFalse(tl.generator_may_write("rhythm", True, False, None))


class TestPageVerbsNameRealStateKeys(unittest.TestCase):
    """Every channel-page verb must be a key the state dict actually carries.

    A verb that names nothing is a knob that silently does nothing: _verb looks
    it up in the driver's range table and param_get reads it straight out of
    the state dict, and neither raises - it just returns. This caught
    `wspan`/`wstride` on the GEN page the day it was written."""

    HANDLED_ELSEWHERE = {
        # Dispatched by name in _verb before any table is consulted.
        "kit", "sample", "preset", "div", "length", "hits", "rotate",
        "model", "feed",
    }

    def test_every_channel_page_verb_is_a_state_key(self):
        for (mode, kind), ring in tl.PAGE_RINGS.items():
            if kind is None:
                continue
            state = tl.default_channel_state(kind)
            for desc in ring:
                if desc["shape"] != tl.SHAPE_CHANNEL:
                    continue
                for verb in desc["verbs"]:
                    if verb is None or verb in self.HANDLED_ELSEWHERE:
                        continue
                    self.assertIn(verb, state,
                                  f"{mode}/{kind} page {desc['title']}: "
                                  f"verb {verb!r} names no state key")


class TestModPhaseReset(unittest.TestCase):
    """Re-phasing: put a modulator at the start of its cycle at a chosen
    moment, so several of them run in lockstep instead of scattered.

    This is the whole of the sidechain pump. A bar-rate gain LFO already ships
    - `level` is in MOD_TIMBRE, 1.0 bars is the DEFAULT rate a bind takes, and
    a negative-depth ramp is an instant rise falling to the bar line. What was
    missing is that phase0 is captured at BIND time, deliberately, so eight
    strips bound one after another pump in eight different phases: smear, not
    glue."""

    def test_a_reset_puts_the_modulator_at_the_start_of_its_cycle(self):
        phase0 = tl.phase_reset(37.5, 1.0)
        self.assertAlmostEqual(tl.mod_pos(phase0, 37.5, 1.0) % 1.0, 0.0)

    def test_it_works_at_every_shipped_rate(self):
        for rate in tl.MOD_RATES:
            phase0 = tl.phase_reset(13.25, rate)
            self.assertAlmostEqual(tl.mod_pos(phase0, 13.25, rate) % 1.0, 0.0,
                                   msg=f"rate {rate}")

    def test_two_modulators_reset_together_stay_together(self):
        # The point of the feature: same rate, same moment, same phase from
        # then on. Scattered phases are what a spread-page bind gives today.
        a = tl.phase_reset(9.0, 1.0)
        b = tl.phase_reset(9.0, 1.0)
        for elapsed in (9.0, 10.5, 21.25, 100.0):
            self.assertAlmostEqual(tl.mod_pos(a, elapsed, 1.0),
                                   tl.mod_pos(b, elapsed, 1.0))

    def test_modulators_bound_apart_are_NOT_together_without_it(self):
        # The defect being fixed, asserted so it cannot quietly stop being
        # true: binding at two moments is what scatters them.
        a = tl.phase_reset(9.0, 1.0)
        b = tl.phase_reset(9.7, 1.0)
        self.assertNotAlmostEqual(tl.mod_pos(a, 20.0, 1.0) % 1.0,
                                  tl.mod_pos(b, 20.0, 1.0) % 1.0)

    def test_the_phase_is_a_fraction_of_one_cycle(self):
        for elapsed in (0.0, 3.3, 77.9):
            self.assertGreaterEqual(tl.phase_reset(elapsed, 2.0), 0.0)
            self.assertLess(tl.phase_reset(elapsed, 2.0), 1.0)

    def test_a_zero_rate_does_not_divide_by_zero(self):
        self.assertEqual(tl.phase_reset(5.0, 0.0), 0.0)


class TestGateCollapse(unittest.TestCase):
    """Every note shortens across the armed bars, then returns.

    NOT built on changeDurationAll, which was measured and is asymmetric: it
    returns out of the whole loop the moment any event would go to <= 0, so a
    decrement can leave the pattern half changed, and it clamps at 0.1, so the
    inverse does not restore the original. Capture and rebuild instead."""

    def test_it_starts_at_full_length(self):
        self.assertEqual(tl.gate_ramp(0, 4), 1.0)

    def test_it_shortens_every_bar(self):
        values = [tl.gate_ramp(bar, 8) for bar in range(8)]
        for a, b in zip(values, values[1:]):
            self.assertGreater(a, b)

    def test_the_last_bar_reaches_the_floor(self):
        self.assertAlmostEqual(tl.gate_ramp(7, 8), tl.GATE_COLLAPSE_FLOOR)

    def test_the_landing_restores_full_length(self):
        # The macro RESOLVES. A build that left the pattern collapsed would be
        # a gesture with no way back except by hand.
        self.assertEqual(tl.gate_ramp(8, 8), 1.0)

    def test_a_missed_poll_cannot_strand_it_collapsed(self):
        # Past the end returns full rather than continuing past it - the same
        # reasoning as chance_ramp's and PendingQueue.due()'s >= over ==.
        self.assertEqual(tl.gate_ramp(99, 8), 1.0)

    def test_a_zero_length_ramp_does_nothing(self):
        self.assertEqual(tl.gate_ramp(0, 0), 1.0)

    def test_the_factor_is_never_zero_and_never_over_one(self):
        for bars in (1, 2, 3, 4, 8, 16):
            for bar in range(bars + 2):
                factor = tl.gate_ramp(bar, bars)
                self.assertGreater(factor, 0.0)
                self.assertLessEqual(factor, 1.0)


class TestCollapseDuration(unittest.TestCase):
    """One note's duration under the ramp."""

    def test_a_full_factor_is_the_identity(self):
        self.assertEqual(tl.collapse_duration(2.5, 1.0), 2.5)

    def test_it_scales_the_duration(self):
        self.assertAlmostEqual(tl.collapse_duration(2.0, 0.5), 1.0)

    def test_it_never_goes_below_the_libseq_floor(self):
        # zynseq clamps a duration at 0.1 and returns out of its own loop at
        # <= 0. Writing anything under the floor means the value that comes
        # back is not the value written, and the restore would then be
        # rebuilding from a lie.
        self.assertGreaterEqual(tl.collapse_duration(0.2, 0.01),
                                tl.NOTE_DURATION_MIN)

    def test_a_note_already_at_the_floor_survives_a_full_collapse(self):
        self.assertEqual(tl.collapse_duration(tl.NOTE_DURATION_MIN, 0.1),
                         tl.NOTE_DURATION_MIN)


class SessionLogPath(unittest.TestCase):
    """Where the play-session log goes, decided from the environment.

    The log is OFF by default and always has been - a log that writes for
    every player is a cost paid for a problem they do not have. What changes
    is HOW it is turned on: editing a constant on the rig leaves the deployed
    file one line different from every commit, which cost a checksum hunt on
    2026-08-31. An environment variable is a systemd drop-in instead, and the
    source stays byte-identical to what was shipped.
    """

    VAR = "MASCHINE_SESSION_LOG"

    def test_an_absent_variable_leaves_the_log_off(self):
        # The default must not move. Every player who has never heard of this
        # gets exactly the behaviour they have today.
        self.assertIsNone(tl.session_log_path({}))

    def test_an_empty_value_leaves_the_log_off(self):
        # `Environment=MASCHINE_SESSION_LOG=` in a unit file is how somebody
        # turns it back off without deleting the line, so it must read as off
        # rather than as a path called "".
        self.assertIsNone(tl.session_log_path({self.VAR: ""}))
        self.assertIsNone(tl.session_log_path({self.VAR: "   "}))

    def test_an_absolute_path_turns_it_on(self):
        self.assertEqual(tl.session_log_path({self.VAR: "/tmp/session.log"}),
                         "/tmp/session.log")

    def test_surrounding_whitespace_is_ignored(self):
        # A drop-in written by hand is the normal way this arrives.
        self.assertEqual(tl.session_log_path({self.VAR: "  /tmp/s.log \n"}),
                         "/tmp/s.log")

    def test_a_relative_path_is_REFUSED_rather_than_resolved(self):
        # The driver's working directory is whatever systemd gave it, so a
        # relative path writes somewhere nobody chose and nobody can find.
        # Refusing is louder than guessing.
        self.assertIsNone(tl.session_log_path({self.VAR: "session.log"}))
        self.assertIsNone(tl.session_log_path({self.VAR: "./session.log"}))

    def test_a_directory_is_REFUSED(self):
        # open(dir, "a") raises IsADirectoryError, which the driver catches and
        # turns into one warning - so this would read as "logging is on" while
        # nothing was ever written.
        self.assertIsNone(tl.session_log_path({self.VAR: "/tmp/"}))

    def test_the_journal_cannot_be_asked_for_by_accident(self):
        # The one path that must never work. Six log lines a second through
        # journald made the daemon's reader run late and wedged the controller
        # off the USB bus on 2026-08-20, and this log exists BECAUSE of that.
        self.assertIsNone(tl.session_log_path({self.VAR: "/dev/stdout"}))
        self.assertIsNone(tl.session_log_path({self.VAR: "/dev/stderr"}))


class WalkIsDeterministic(unittest.TestCase):
    """The walk model has to be a pure function of stored state, like the
    register is.

    THE BUG THIS PREVENTS, found by the owner at the rig on 2026-08-31: the
    pads flashed about five times a second and showed a line that was never
    the one playing. `_voice_line` is called by the WRITER and by both PAD
    RENDERERS, and each call re-ran the walk with the module rng - so every
    repaint invented a different melody. `_voice_line`'s own docstring
    predicted the failure: "if the two disagree the pads query a note that is
    not there and every step reads as empty."

    It also mattered for the hardware. The flashing measured 109 OSC messages
    a second against 6.6 idle, and the write-budget finding puts 100/s
    survivable and 160/s wedging the controller off the USB bus.

    The register model could never hit this: line() is a pure function of the
    register. The walk was a function of nothing.
    """

    ARGS = dict(start=64, length=8, steps=16, span=32, stride=4)

    def _walk(self, seed):
        return tl.walk_values(rng=tl.walk_rng(seed), **self.ARGS)

    def test_the_same_seed_gives_the_same_line_every_time(self):
        # The writer and the two renderers each call this independently. If
        # they disagree the pads lie about what is playing.
        self.assertEqual(self._walk(7), self._walk(7))

    def test_ten_calls_with_one_seed_never_differ(self):
        first = self._walk(3)
        for _ in range(10):
            self.assertEqual(self._walk(3), first)

    def test_a_different_seed_gives_a_different_line(self):
        # Otherwise advancing the seed at the wrap would not evolve anything.
        lines = {tuple(self._walk(s)) for s in range(8)}
        self.assertGreater(len(lines), 1)

    def test_the_seed_survives_being_a_plain_integer(self):
        # It is stored in the channel state and goes into a snapshot, so it has
        # to be JSON-representable - no rng objects, no tuples of state.
        self.assertIsInstance(0, int)
        self.assertEqual(self._walk(0), self._walk(0))

    def test_it_still_respects_the_bounds_it_always_did(self):
        top = (1 << self.ARGS["length"]) - 1
        for value in self._walk(11):
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, top)

    def test_a_seeded_walk_does_not_disturb_the_module_rng(self):
        # walk_values used the module rng by default, so a repaint consumed
        # randomness that the register's own mutation was also drawing from.
        import random as _r
        _r.seed(1234)
        before = _r.random()
        _r.seed(1234)
        self._walk(99)
        self.assertEqual(_r.random(), before)


class PressureDoesNotAnimateTheDisplay(unittest.TestCase):
    """A live squeeze must not make the display's number move.

    THE BUG THIS PREVENTS, measured at the rig 2026-08-31 with pad pressure
    switched on: 110 OSC messages a second, of which 104 were DISPLAY - 61
    rect/s, 40 text/s, 3 fbclear/s - against 5.6 for the pads. The screens were
    repainting about thirty times a second because pressure writes the SWEPT
    value into state and the display renders state.

    This surface has already learned this once. _render_display's own comment,
    about the MOD tick that was removed: "a number that changes when you change
    it, rather than an animation that rebuilt both screens six times a second
    and killed the controller." Pressure reintroduced it at five times the
    rate.

    And it breaks a written law. notes/traps/MODULATION.md: "Base and offset
    are separate - the driver owns the base and writes base + offset; writing
    the swept value back kills the knob." Pressure keeps its base in
    _press_base so the KNOB survives, but nothing kept the DISPLAY off the
    swept value.
    """

    def test_no_squeeze_leaves_the_view_alone(self):
        view = {"cutoff": 70, "reso": 20}
        self.assertEqual(tl.pressure_display(view, "cutoff", None), view)

    def test_a_live_squeeze_shows_the_BASE_not_the_swept_value(self):
        # The knob is at 70; the squeeze has pushed the engine to 118. The
        # glass must say 70, because that is where the knob is and where the
        # sound returns to when the finger lifts.
        view = {"cutoff": 118, "reso": 20}
        got = tl.pressure_display(view, "cutoff", 70)
        self.assertEqual(got["cutoff"], 70)

    def test_it_does_not_mutate_the_view_it_was_given(self):
        # state_view() hands out a dict the caller owns; writing through it
        # would put the base into the driver's own state and lose the sweep.
        view = {"cutoff": 118}
        tl.pressure_display(view, "cutoff", 70)
        self.assertEqual(view["cutoff"], 118)

    def test_every_other_column_is_untouched(self):
        view = {"cutoff": 118, "reso": 20, "level": 90}
        got = tl.pressure_display(view, "cutoff", 70)
        self.assertEqual(got["reso"], 20)
        self.assertEqual(got["level"], 90)

    def test_the_value_is_STEADY_while_the_squeeze_varies(self):
        # The whole point: forty pressure steps, one display value. Without
        # this each step is a repaint of both screens.
        base = 70
        seen = {tl.pressure_display({"cutoff": v}, "cutoff", base)["cutoff"]
                for v in range(70, 110)}
        self.assertEqual(seen, {70})

    def test_a_base_of_zero_is_honoured_and_not_read_as_absent(self):
        # `if base:` would show the swept value at the bottom of the range,
        # which is exactly where a filter sweep is most audible.
        got = tl.pressure_display({"cutoff": 40}, "cutoff", 0)
        self.assertEqual(got["cutoff"], 0)


class TheBankIsPinnedNotFollowed(unittest.TestCase):
    """The driver used to READ `zynseq.bank` at ten call sites and assert it
    nowhere, so an external bank change - the touchscreen, a snapshot, a CUIA -
    repointed every zynseq call while every Python-side cache still described
    the old bank, with no log and no symptom until something sounded wrong.
    `todo.md` carried it as a latent defect and as the hard prerequisite for
    banks-as-scenes.

    BankPin holds the bank the driver is working in and reports a drift instead
    of absorbing it."""

    def test_a_fresh_pin_holds_the_bank_it_was_given(self):
        pin = tl.BankPin()
        pin.pin(1)
        self.assertEqual(pin.bank, 1)

    def test_observing_the_same_bank_says_nothing(self):
        pin = tl.BankPin()
        pin.pin(1)
        self.assertIsNone(pin.observe(1))
        self.assertEqual(pin.drifts, 0)

    def test_a_drift_is_ADOPTED_not_refused(self):
        # Refusing would be worse than following: the driver would keep
        # writing into a bank the sequencer is no longer playing, which is
        # silence with no explanation - the one law this surface cannot break.
        pin = tl.BankPin()
        pin.pin(1)
        pin.observe(3)
        self.assertEqual(pin.bank, 3)

    def test_a_drift_RETURNS_a_message_naming_both_banks(self):
        pin = tl.BankPin()
        pin.pin(1)
        msg = pin.observe(3)
        self.assertIsNotNone(msg)
        self.assertIn("1", msg)
        self.assertIn("3", msg)

    def test_a_drift_is_reported_ONCE_not_on_every_tick(self):
        # The check runs once a second forever. A message per tick would bury
        # the journal and teach the next reader to ignore it.
        pin = tl.BankPin()
        pin.pin(1)
        self.assertIsNotNone(pin.observe(3))
        self.assertIsNone(pin.observe(3))
        self.assertIsNone(pin.observe(3))

    def test_drifting_BACK_is_reported_again(self):
        pin = tl.BankPin()
        pin.pin(1)
        pin.observe(3)
        self.assertIsNotNone(pin.observe(1))

    def test_drifts_are_COUNTED_so_a_flapping_bank_is_visible(self):
        pin = tl.BankPin()
        pin.pin(1)
        pin.observe(3)
        pin.observe(1)
        pin.observe(3)
        self.assertEqual(pin.drifts, 3)

    def test_an_explicit_pin_is_SILENT_even_when_it_moves_the_bank(self):
        # A snapshot load pins deliberately and resyncs everything anyway.
        # That is not a drift and must not read like one.
        pin = tl.BankPin()
        pin.pin(1)
        pin.pin(4)
        self.assertEqual(pin.bank, 4)
        self.assertEqual(pin.drifts, 0)
        self.assertIsNone(pin.observe(4))

    def test_a_bank_outside_1_to_64_is_REFUSED_and_reported(self):
        # zynseq's own select_bank refuses anything outside 1..64. A zero or a
        # None here means something upstream is unset, and adopting it would
        # address a bank that cannot exist.
        pin = tl.BankPin()
        pin.pin(1)
        for bad in (0, 65, -1, None):
            with self.subTest(bad=bad):
                msg = pin.observe(bad)
                self.assertIsNotNone(msg)
                self.assertEqual(pin.bank, 1)

    def test_an_unpinned_pin_has_no_bank_and_adopts_the_first_it_is_given(self):
        # init() pins from zynseq once it is wired up; before that there is no
        # answer, and guessing 1 would be a fact this class does not have.
        pin = tl.BankPin()
        self.assertIsNone(pin.bank)
        self.assertIsNone(pin.observe(2))
        self.assertEqual(pin.bank, 2)
        self.assertEqual(pin.drifts, 0)

    def test_pinning_a_bank_that_cannot_EXIST_is_taken_and_reported(self):
        # It is still taken: refusing leaves the driver with no bank at all.
        # But a rig that pins a 0 has something wrong upstream, and finding
        # that out a second later as a "drift" would name the wrong fault.
        pin = tl.BankPin()
        msg = pin.pin(0)
        self.assertIsNotNone(msg)
        self.assertEqual(pin.bank, 0)
        self.assertEqual(pin.drifts, 0)

    def test_pinning_a_normal_bank_is_silent(self):
        pin = tl.BankPin()
        self.assertIsNone(pin.pin(1))


class HowMuchTheMachineMayMoveAChannel(unittest.TestCase):
    """MOVE, 2026-09-01. One number per channel: how much the machine's own
    gestures may touch it. 0 is LOCK, 100 is today's behaviour.

    A PROBABILITY, not a switch - the owner decision. As a boolean it is
    per-channel FREEZE renamed, and this instrument already has that button."""

    def test_full_move_always_allows_and_needs_no_roll(self):
        self.assertTrue(tl.move_allows(100, None))

    def test_lock_never_allows_whatever_the_roll_says(self):
        for roll in (0, 50, 99):
            with self.subTest(roll=roll):
                self.assertFalse(tl.move_allows(0, roll))

    def test_a_partial_move_is_the_probability_the_gesture_lands(self):
        self.assertTrue(tl.move_allows(50, 49))
        self.assertFalse(tl.move_allows(50, 50))
        self.assertFalse(tl.move_allows(50, 99))

    def test_a_missing_roll_ALLOWS_rather_than_silently_holding(self):
        # A gesture that vanished because a caller forgot an argument would be
        # a channel that goes quiet with nothing to explain it. The driver
        # always passes a real roll; the default is the safe direction.
        self.assertTrue(tl.move_allows(50, None))

    def test_a_missing_move_reads_as_full(self):
        # An older snapshot, or any caller that has not been taught the verb.
        self.assertTrue(tl.move_allows(None, 99))

    def test_out_of_range_moves_are_clamped_not_believed(self):
        self.assertTrue(tl.move_allows(140, 99))
        self.assertFalse(tl.move_allows(-20, 0))


class MoveGatesEveryAutomaticGesture(unittest.TestCase):
    """The gate lives in the two places every automatic gesture already passes
    through, so a fifth generator inherits it instead of re-deriving it."""

    def test_generator_may_write_refuses_a_locked_channel(self):
        self.assertFalse(tl.generator_may_write("melody", False, False, None,
                                                move=0))

    def test_generator_may_write_is_unchanged_at_full_move(self):
        self.assertTrue(tl.generator_may_write("melody", False, False, None,
                                               move=100, roll=99))

    def test_move_defaults_to_full_so_every_existing_caller_is_unchanged(self):
        self.assertTrue(tl.generator_may_write("melody", False, False, None))

    def test_ownership_still_wins_over_a_full_move(self):
        self.assertFalse(tl.generator_may_write("melody", False, False,
                                                "player", move=100))

    def test_freeze_still_wins_over_a_full_move(self):
        self.assertFalse(tl.generator_may_write("melody", True, False, None,
                                                move=100))

    def test_generated_channels_drops_the_locked_ones(self):
        moves = {0: 100, 1: 0, 2: 100, 3: 0, 4: 100, 5: 100, 6: 100, 7: 100}
        got = tl.generated_channels({}, moves=moves)
        self.assertEqual(got, (0, 2, 4, 5, 6, 7))

    def test_generated_channels_is_unchanged_when_nothing_is_locked(self):
        self.assertEqual(tl.generated_channels({}), tuple(range(8)))

    def test_generated_channels_still_drops_player_owned_first(self):
        moves = {ch: 100 for ch in range(8)}
        got = tl.generated_channels({2: "player"}, moves=moves)
        self.assertNotIn(2, got)

    def test_a_partial_move_uses_the_roll_the_caller_supplies(self):
        moves = {ch: 50 for ch in range(8)}
        # One roll per channel, in channel order.
        rolls = iter([10, 90, 10, 90, 10, 90, 10, 90])
        got = tl.generated_channels({}, moves=moves, roll=lambda: next(rolls))
        self.assertEqual(got, (0, 2, 4, 6))


class MoveIsOnTheSurfaceAndInTheSnapshot(unittest.TestCase):

    def test_both_kinds_start_at_full_move(self):
        # The migration: 100 is exactly today's behaviour, so an existing
        # snapshot plays bit for bit what it played before this shipped.
        for kind in ("drum", "voice"):
            with self.subTest(kind=kind):
                self.assertEqual(tl.default_channel_state(kind)["move"], 100)

    def test_an_older_snapshot_gains_move_at_full(self):
        old = tl.default_channel_state("drum")
        del old["move"]
        got = tl.upgrade_state("drum", old, 16)
        self.assertEqual(got["move"], 100)

    def test_a_saved_move_survives_the_upgrade(self):
        saved = tl.default_channel_state("voice")
        saved["move"] = 0
        self.assertEqual(tl.upgrade_state("voice", saved, 16)["move"], 0)

    def test_MOVE_is_a_verb_on_the_AUTO_page_of_both_kinds(self):
        # WAS test_the_ALL_ring_carries_a_MOVE_page. MOVE had a spread page of
        # its own on the ALL ring; the rings collapsed from 24 pages to 9 on
        # 2026-09-01 and every generative verb landed on AUTO, which is the
        # one question it answers - what may the machine do to this channel.
        for kind in ("drum", "voice"):
            with self.subTest(kind=kind):
                self.assertIn("move", _page("AUTO", kind, "AUTO")["verbs"])

    def test_the_MOVE_lens_is_a_spread_over_all_eight_channels(self):
        # The spread page became the lens: hold ALL after turning MOVE and the
        # same eight-channel view is there, from any level.
        page = tl.lens_desc("move")
        self.assertEqual(tl.lens_verb("move"), "move")
        self.assertEqual(page["shape"], tl.SHAPE_SPREAD)
        self.assertEqual(page["verb"], "move")

    def test_zero_reads_LOCK_through_the_lens_not_a_bare_zero(self):
        # The LOCK grammar this instrument already uses for RANDOM, RHYTHM and
        # WALK. A channel the machine may not touch has to say so.
        views = [("A", "KICK", {"move": 0})] * 8
        cols = tl.spread_columns(tl.lens_desc("move"), views)
        self.assertEqual(cols[0]["value"], "LOCK")

    def test_a_non_zero_move_still_reads_as_a_number(self):
        views = [("A", "KICK", {"move": 70})] * 8
        # Four characters, zero padded - the shipped spread value format.
        self.assertEqual(
            tl.spread_columns(tl.lens_desc("move"), views)[0]["value"], "0070")


class TheCellularAutomaton(unittest.TestCase):
    """A third way for a channel to invent, 2026-09-01. It is an EVOLUTION
    rule and it replaces `mutate` - not a pitch source, so it is NOT on the
    MODEL column, which chooses where a voice's pitch values come from. That
    was the PM decision: merged, picking a rule would silently also decide the
    pitch source."""

    def test_the_rule_set_is_the_three_named_ones_plus_the_shift_register(self):
        self.assertEqual(tl.RULES[0], tl.RULE_RANDOM)
        self.assertEqual(set(tl.CA_RULES), {"r30", "r90", "r110"})

    def test_chance_zero_is_the_IDENTITY_so_LOCK_stays_exact(self):
        # mutate's promise, kept: "a full rotation is the identity at chance 0,
        # which is what makes LOCK exact rather than approximate".
        for rule in tl.CA_RULES:
            with self.subTest(rule=rule):
                self.assertEqual(tl.ca_step(0b1011001110001111, 16, rule, 0.0),
                                 0b1011001110001111)

    def test_rule_90_is_the_xor_of_the_two_neighbours(self):
        # One bit set in the middle of a wide register becomes two.
        got = tl.ca_step(0b00010000, 8, "r90", 1.0)
        self.assertEqual(got, 0b00101000)

    def test_the_neighbourhood_WRAPS_at_the_register_edge(self):
        # Bit 0 and bit width-1 are neighbours: the pattern is a loop, and a
        # shape that travels has to be able to leave one end and arrive at the
        # other.
        got = tl.ca_step(0b00000001, 8, "r90", 1.0)
        self.assertEqual(got, 0b10000010)

    def test_no_rule_ever_sets_a_bit_OUTSIDE_the_width(self):
        # A 12-step triplet division must never pick up bits 12-15 left behind
        # by a 16-step one - the trap drum_steps' own docstring documents.
        for rule in tl.CA_RULES:
            for width in (2, 3, 12, 16):
                with self.subTest(rule=rule, width=width):
                    got = tl.ca_step(0xFFFF, width, rule, 1.0)
                    self.assertEqual(got & ~((1 << width) - 1), 0)

    def test_width_two_is_stable_and_does_not_raise(self):
        for rule in tl.CA_RULES:
            with self.subTest(rule=rule):
                got = tl.ca_step(0b10, 2, rule, 1.0)
                self.assertIsInstance(got, int)
                self.assertLessEqual(got, 0b11)

    def test_NO_RULE_CAN_LEAVE_THE_REGISTER_EMPTY(self):
        # THE risk, and it is a test rather than a comment. Every elementary
        # rule this instrument offers maps 000 -> 0, so a register that reaches
        # empty would stay empty forever with the knob reading whatever it
        # read - a silent channel with nothing explaining it, which is the one
        # law this surface cannot break.
        for rule in tl.CA_RULES:
            for width in (2, 8, 12, 16):
                with self.subTest(rule=rule, width=width):
                    self.assertNotEqual(tl.ca_step(0, width, rule, 1.0), 0)

    def test_a_register_that_would_die_this_step_is_reseeded_DETERMINISTICALLY(self):
        # Same input, same output: a CA is bought for "some rules never repeat,
        # some grow shapes", and a random rescue would make the whole thing
        # unreproducible.
        a = tl.ca_step(0, 16, "r90", 1.0)
        b = tl.ca_step(0, 16, "r90", 1.0)
        self.assertEqual(a, b)

    def test_a_full_chance_step_needs_no_randomness_at_all(self):
        # The rng must not even be consulted at chance 1 - that is what makes
        # the automaton reproducible from a seed.
        def boom():
            raise AssertionError("the rng was consulted at chance 1.0")
        tl.ca_step(0b0110, 4, "r110", 1.0, rng=boom)

    def test_a_partial_chance_applies_the_rule_to_SOME_bits(self):
        # The owner decision: RANDOM is the probability the rule is applied to
        # each bit, the rest held. LOCK stays exact at 0, 100 is the pure
        # automaton, and the knob keeps one meaning on every channel kind.
        held = tl.ca_step(0b00010000, 8, "r90", 0.5, rng=lambda: 0.9)
        self.assertEqual(held, 0b00010000)
        applied = tl.ca_step(0b00010000, 8, "r90", 0.5, rng=lambda: 0.1)
        self.assertEqual(applied, 0b00101000)

    def test_an_unknown_rule_holds_the_register_rather_than_inventing_one(self):
        self.assertEqual(tl.ca_step(0b1010, 4, "r7", 1.0), 0b1010)
        self.assertEqual(tl.ca_step(0b1010, 4, tl.RULE_RANDOM, 1.0), 0b1010)


class TheRuleIsAVerbOnBothKinds(unittest.TestCase):

    def test_both_kinds_start_on_the_shift_register(self):
        # The migration: `rand` is what every channel has always done.
        for kind in ("drum", "voice"):
            with self.subTest(kind=kind):
                self.assertEqual(tl.default_channel_state(kind)["rule"],
                                 tl.RULE_RANDOM)

    def test_an_older_snapshot_gains_the_verb_on_the_shift_register(self):
        old = tl.default_channel_state("voice")
        del old["rule"]
        self.assertEqual(tl.upgrade_state("voice", old, 16)["rule"],
                         tl.RULE_RANDOM)

    def test_the_voice_AUTO_page_carries_RULE(self):
        # The GEN pages went in the 2026-09-01 collapse and RULE went to AUTO
        # with the rest of the generator, on both kinds.
        self.assertIn("rule", _page("AUTO", "voice", "AUTO")["verbs"])

    def test_the_drum_ring_has_an_AUTO_page_carrying_RULE(self):
        titles = [d["title"] for d in tl.PAGE_RINGS[("AUTO", "drum")]]
        self.assertIn("AUTO", titles)
        self.assertIn("rule", _page("AUTO", "drum", "AUTO")["verbs"])

    def test_RULE_is_NOT_on_the_model_column(self):
        # The PM decision of 2026-09-01, and the reason it is worth a test:
        # MODEL chooses a voice's pitch source. A rule folded into it would
        # mean picking R110 silently also decides where the notes come from.
        # They are still two columns after the collapse, now side by side on
        # the voice AUTO page.
        page = _page("AUTO", "voice", "AUTO")
        self.assertIn("model", page["verbs"])
        self.assertNotEqual(page["verbs"].index("model"),
                            page["verbs"].index("rule"))

    def test_the_column_says_which_rule_is_running(self):
        state = tl.default_channel_state("voice")
        state["rule"] = "r110"
        cols = tl.columns(_page("AUTO", "voice", "AUTO"), "voice", state)
        rule_col = [c for c in cols if c["name"].startswith("RULE")][0]
        self.assertEqual(rule_col["value"], "R110")

    def test_the_shift_register_setting_says_RAND_not_a_blank(self):
        state = tl.default_channel_state("voice")
        cols = tl.columns(_page("AUTO", "voice", "AUTO"), "voice", state)
        rule_col = [c for c in cols if c["name"].startswith("RULE")][0]
        self.assertEqual(rule_col["value"], "RAND")


class TheGeneratorThatLeans(unittest.TestCase):
    """A THIRD PLACEMENT generator beside euclid, 2026-09-01. Euclid spaces
    hits evenly and cannot write a hat line that leans; this weights the
    positions by what the part is for, so a part has an accent shape of its
    own.

    DETERMINISTIC BY CONSTRUCTION - the strongest positions win, ties break on
    index. A weighted RANDOM pick would need a seed, and a pattern that changed
    on every rewrite is not a pattern."""

    def test_off_is_not_a_lean_and_the_caller_keeps_euclid(self):
        self.assertIsNone(tl.lean(16, 4, tl.LEAN_OFF))

    def test_an_unknown_profile_refuses_rather_than_inventing_one(self):
        self.assertIsNone(tl.lean(16, 4, "sideways"))

    def test_a_lean_places_exactly_the_hits_it_was_asked_for(self):
        for profile in tl.LEANS[1:]:
            for hits in (0, 1, 3, 4, 7, 16):
                with self.subTest(profile=profile, hits=hits):
                    got = tl.lean(16, hits, profile)
                    self.assertEqual(sum(got), hits)
                    self.assertEqual(len(got), 16)

    def test_more_hits_than_steps_fills_the_bar_and_does_not_raise(self):
        got = tl.lean(16, 40, tl.LEAN_BEAT)
        self.assertEqual(sum(got), 16)

    def test_the_floor_lean_puts_four_hits_on_the_four_beats(self):
        got = tl.lean(16, 4, tl.LEAN_BEAT)
        self.assertEqual([i for i, on in enumerate(got) if on], [0, 4, 8, 12])

    def test_the_floor_lean_fills_the_HALF_bar_first_when_it_has_two(self):
        # Metric hierarchy: step 0 is stronger than step 8, which is stronger
        # than steps 4 and 12.
        got = tl.lean(16, 2, tl.LEAN_BEAT)
        self.assertEqual([i for i, on in enumerate(got) if on], [0, 8])

    def test_the_eighth_lean_reaches_the_offbeat_eighths_before_the_16ths(self):
        got = tl.lean(16, 8, tl.LEAN_EIGHTH)
        self.assertEqual([i for i, on in enumerate(got) if on],
                         [0, 2, 4, 6, 8, 10, 12, 14])

    def test_the_offbeat_lean_AVOIDS_the_downbeat(self):
        # The whole point of the profile: it is the part that syncopates, and
        # it must not quietly write a four-to-the-floor.
        got = tl.lean(16, 4, tl.LEAN_OFFBEAT)
        self.assertFalse(got[0])
        self.assertEqual(sum(got), 4)

    def test_the_three_profiles_do_not_agree_with_each_other(self):
        shapes = {p: tuple(tl.lean(16, 6, p)) for p in tl.LEANS[1:]}
        self.assertEqual(len(set(shapes.values())), 3)

    def test_a_lean_is_the_same_pattern_every_time_it_is_asked_for(self):
        a = tl.lean(16, 5, tl.LEAN_EIGHTH)
        b = tl.lean(16, 5, tl.LEAN_EIGHTH)
        self.assertEqual(a, b)

    def test_a_TRIPLET_division_leans_over_its_own_twelve_steps(self):
        got = tl.lean(12, 3, tl.LEAN_BEAT)
        self.assertEqual(len(got), 12)
        self.assertEqual(sum(got), 3)
        self.assertTrue(got[0])

    def test_a_two_step_pattern_does_not_raise(self):
        self.assertEqual(sum(tl.lean(2, 1, tl.LEAN_OFFBEAT)), 1)


class TheLeanIsAVerbOnTheDrums(unittest.TestCase):

    def test_a_drum_starts_on_euclid(self):
        # The migration: OFF is bit for bit what every drum channel did before
        # this generator existed.
        self.assertEqual(tl.default_channel_state("drum")["lean"], tl.LEAN_OFF)

    def test_an_older_snapshot_gains_the_verb_on_euclid(self):
        old = tl.default_channel_state("drum")
        del old["lean"]
        self.assertEqual(tl.upgrade_state("drum", old, 16)["lean"], tl.LEAN_OFF)

    def test_the_drum_AUTO_page_carries_LEAN_in_column_two(self):
        # It was column two of the drum GEN page; GEN went in the 2026-09-01
        # collapse and LEAN kept the slot on AUTO, still beside RULE.
        self.assertEqual(_page("AUTO", "drum", "AUTO")["verbs"][1], "lean")

    def test_the_column_names_the_profile_and_says_EUCL_when_off(self):
        state = tl.default_channel_state("drum")
        page = _page("AUTO", "drum", "AUTO")
        cols = tl.columns(page, "drum", state)
        self.assertEqual(cols[1]["name"], "LEAN")
        self.assertEqual(cols[1]["value"], "EUCL")
        state["lean"] = tl.LEAN_OFFBEAT
        self.assertEqual(tl.columns(page, "drum", state)[1]["value"], "OFFB")

    def test_a_voice_has_no_lean_verb_and_the_page_does_not_offer_one(self):
        # Placement on a voice is the rhythm register's job. A column that did
        # nothing would be law L4's exact complaint. Checked on every page of
        # the voice AUTO ring rather than one index into it, so the statement
        # survives the next time a page moves.
        for desc in tl.PAGE_RINGS[tl.ring_key("AUTO", "voice")]:
            self.assertNotIn("lean", desc["verbs"] or ())

    def test_extra_hits_SPREAD_across_the_grid_rather_than_piling_up(self):
        # Eight hits on the floor profile are a flam on each beat, not four
        # hits crowded onto beat one. The round robin is the difference
        # between a part that leans and a part that stumbles.
        got = [i for i, on in enumerate(tl.lean(16, 8, tl.LEAN_BEAT)) if on]
        self.assertEqual(got, [0, 1, 4, 5, 8, 9, 12, 13])

    def test_a_lean_pushes_LATE_rather_than_early(self):
        # A hit that arrives just after the beat is a push, which is what
        # these parts do; the pickup before the beat comes second.
        got = tl.lean(16, 5, tl.LEAN_BEAT)
        self.assertTrue(got[1])
        self.assertFalse(got[15])

    def test_the_offbeat_lean_sits_on_the_ands(self):
        got = [i for i, on in enumerate(tl.lean(16, 4, tl.LEAN_OFFBEAT)) if on]
        self.assertEqual(got, [2, 6, 10, 14])


class HowFarTheGeneratorsMayStray(unittest.TestCase):
    """LANE, 2026-09-01. One number per channel for how narrow the danceable
    lane is: at the top a bar is measured before it is allowed out and the
    weakest hits are removed until it holds together; at 0 you get the raw
    field, which is exactly what shipped before this existed."""

    def test_syncopation_is_zero_when_every_hit_is_on_a_strong_position(self):
        four_floor = tuple(i % 4 == 0 for i in range(16))
        self.assertEqual(tl.syncopation(four_floor), 0)

    def test_syncopation_is_high_when_every_hit_is_off_the_grid(self):
        offs = tuple(i % 4 == 1 for i in range(16))
        self.assertGreater(tl.syncopation(offs), 60)

    def test_an_empty_bar_has_no_syncopation_rather_than_dividing_by_zero(self):
        self.assertEqual(tl.syncopation((False,) * 16), 0)

    def test_lane_zero_is_the_RAW_field_and_changes_nothing(self):
        wild = tuple(i % 4 == 1 for i in range(16))
        self.assertEqual(tl.lane_filter(wild, 0), wild)

    def test_a_narrow_lane_removes_the_weakest_hits(self):
        pattern = [i % 4 == 0 for i in range(16)]
        pattern[3] = True
        pattern[13] = True
        got = tl.lane_filter(tuple(pattern), 100)
        self.assertEqual([i for i, on in enumerate(got) if on], [0, 4, 8, 12])

    def test_a_narrow_lane_leaves_a_pattern_that_ALREADY_holds_together(self):
        four_floor = tuple(i % 4 == 0 for i in range(16))
        self.assertEqual(tl.lane_filter(four_floor, 100), four_floor)

    def test_a_middling_lane_removes_SOME_of_the_strays_not_all(self):
        pattern = [i % 4 == 0 for i in range(16)]
        for i in (1, 3, 5, 7):
            pattern[i] = True
        got = tl.lane_filter(tuple(pattern), 60)
        self.assertLess(sum(got), 8)
        self.assertGreater(sum(got), 4)

    def test_A_CHANNEL_IS_NEVER_EMPTIED(self):
        # The one law this surface cannot break. A constraint that silenced a
        # channel would be a silence whose explanation is on another page.
        wild = tuple(i % 8 == 3 for i in range(16))
        self.assertGreaterEqual(sum(tl.lane_filter(wild, 100)), 1)

    def test_it_is_deterministic(self):
        wild = tuple(i % 3 == 1 for i in range(16))
        self.assertEqual(tl.lane_filter(wild, 70), tl.lane_filter(wild, 70))

    def test_a_triplet_length_is_measured_over_its_own_twelve_steps(self):
        pattern = tuple(i % 3 == 0 for i in range(12))
        self.assertEqual(tl.lane_filter(pattern, 100), pattern)

    def test_it_never_ADDS_a_step(self):
        for lane in (0, 25, 50, 75, 100):
            wild = tuple(i % 5 == 2 for i in range(16))
            got = tl.lane_filter(wild, lane)
            with self.subTest(lane=lane):
                for i, on in enumerate(got):
                    if on:
                        self.assertTrue(wild[i])


class TheLaneIsOnTheDrumsOnly(unittest.TestCase):
    """A voice's placement IS the rhythm register, and a pad tap on a voice
    writes into that register. A constraint that pruned it would silently undo
    a hand-tapped step - the defect the engineering review named before this
    was built. So the verb exists on drums, where it prunes the GENERATED line
    before the hand register subtracts from it, and the voices draw dead."""

    def test_a_drum_starts_on_the_raw_field(self):
        self.assertEqual(tl.default_channel_state("drum")["lane"], 0)

    def test_a_voice_has_NO_lane_at_all(self):
        self.assertNotIn("lane", tl.default_channel_state("voice"))

    def test_an_older_snapshot_gains_the_verb_at_raw(self):
        old = tl.default_channel_state("drum")
        del old["lane"]
        self.assertEqual(tl.upgrade_state("drum", old, 16)["lane"], 0)

    def test_LANE_is_a_verb_on_the_DRUM_auto_page_only(self):
        # WAS test_the_ALL_ring_carries_a_LANE_spread. The spread page went
        # with the rest on 2026-09-01; LANE is a column on the drum AUTO page
        # now and is absent from the voice one, which is the same statement
        # this class exists to make.
        self.assertIn("lane", _page("AUTO", "drum", "AUTO")["verbs"])
        self.assertNotIn("lane", _page("AUTO", "voice", "AUTO")["verbs"])

    def test_the_LANE_lens_is_a_spread_over_all_eight_channels(self):
        page = tl.lens_desc("lane")
        self.assertEqual(tl.lens_verb("lane"), "lane")
        self.assertEqual(page["shape"], tl.SHAPE_SPREAD)
        self.assertEqual(page["verb"], "lane")

    def test_a_voice_column_draws_DEAD_through_the_lane_lens(self):
        views = [("A", "KICK", {"lane": 40})] * 7 + [("H", "LEAD", {})]
        cols = tl.spread_columns(tl.lens_desc("lane"), views)
        self.assertFalse(cols[0]["grey"])
        self.assertTrue(cols[7]["grey"])

    def test_zero_reads_RAW_rather_than_a_bare_number(self):
        views = [("A", "KICK", {"lane": 0})] * 8
        self.assertEqual(
            tl.spread_columns(tl.lens_desc("lane"), views)[0]["value"], "RAW")


class ChannelsThatLeaveThroughAFilter(unittest.TestCase):
    """EXIT, 2026-09-01. A part that stops does not vanish - it closes. The
    MUTE grid's QUEUED row becomes the closing exit and its instant row stays
    hard, so the gesture is the one that already ships and the two rows finally
    mean different things.

    Without it, an arrangement the machine makes sounds exactly like somebody
    pressing mute buttons, which is the thing that gives a machine away."""

    def test_a_close_starts_open_and_ends_shut(self):
        self.assertEqual(tl.exit_factor(0, 8, closing=True), 1.0)
        self.assertEqual(tl.exit_factor(8, 8, closing=True), 0.0)

    def test_an_open_starts_shut_and_ends_open(self):
        self.assertEqual(tl.exit_factor(0, 8, closing=False), 0.0)
        self.assertEqual(tl.exit_factor(8, 8, closing=False), 1.0)

    def test_it_moves_monotonically(self):
        seen = [tl.exit_factor(i, 8, closing=True) for i in range(9)]
        self.assertEqual(seen, sorted(seen, reverse=True))

    def test_past_the_end_it_STAYS_landed_rather_than_overshooting(self):
        self.assertEqual(tl.exit_factor(99, 8, closing=True), 0.0)
        self.assertEqual(tl.exit_factor(99, 8, closing=False), 1.0)

    def test_a_zero_length_close_is_INSTANT_and_does_not_divide_by_zero(self):
        self.assertEqual(tl.exit_factor(0, 0, closing=True), 0.0)
        self.assertEqual(tl.exit_factor(0, 0, closing=False), 1.0)

    def test_the_cutoff_closes_FURTHER_than_the_level_does(self):
        # A filter close is heard as the part getting darker before it gets
        # quieter. Both reach zero, but the filter leads.
        mid = tl.exit_factor(4, 8, closing=True)
        self.assertLess(tl.exit_cutoff(mid), mid)

    def test_the_cutoff_curve_still_reaches_both_ends(self):
        self.assertEqual(tl.exit_cutoff(1.0), 1.0)
        self.assertEqual(tl.exit_cutoff(0.0), 0.0)

    def test_both_kinds_carry_the_verb_and_start_HARD(self):
        # 0 bars is exactly today's behaviour: the mute lands the moment the
        # wrap arrives, so an existing snapshot mutes as it always did.
        for kind in ("drum", "voice"):
            with self.subTest(kind=kind):
                self.assertEqual(tl.default_channel_state(kind)["exit"], 0)

    def test_an_older_snapshot_gains_the_verb_HARD(self):
        old = tl.default_channel_state("voice")
        del old["exit"]
        self.assertEqual(tl.upgrade_state("voice", old, 16)["exit"], 0)

    def test_EXIT_is_a_verb_on_the_AUTO_page_of_both_kinds(self):
        # WAS test_the_ALL_ring_carries_an_EXIT_spread. Its spread page went in
        # the 2026-09-01 collapse and the verb landed on AUTO, in the last
        # slot on both kinds.
        for kind in ("drum", "voice"):
            with self.subTest(kind=kind):
                self.assertEqual(_page("AUTO", kind, "AUTO")["verbs"][7],
                                 "exit")

    def test_the_EXIT_lens_is_a_spread_over_all_eight_channels(self):
        page = tl.lens_desc("exit")
        self.assertEqual(tl.lens_verb("exit"), "exit")
        self.assertEqual(page["shape"], tl.SHAPE_SPREAD)
        self.assertEqual(page["verb"], "exit")

    def test_zero_reads_HARD_rather_than_a_bare_number(self):
        views = [("A", "KICK", {"exit": 0})] * 8
        self.assertEqual(
            tl.spread_columns(tl.lens_desc("exit"), views)[0]["value"], "HARD")

    def test_a_length_reads_in_BARS_because_that_is_what_it_is(self):
        views = [("A", "KICK", {"exit": 2})] * 8
        self.assertEqual(
            tl.spread_columns(tl.lens_desc("exit"), views)[0]["value"], "2bar")


class TheScreensAreCoalescedWhileAControlIsStillMoving(unittest.TestCase):
    """2026-09-02. The big encoder steps a page per detent and every page
    draws different content, so a hand walking a ring paid a full both-screen
    repaint per detent: 674 OSC messages a second measured at the rig, and a
    wedged controller in the jam that followed. Display traffic is what wedges
    this hardware.

    NOT the phrase counter's bug, and the difference decides the fix. That one
    redrew IDENTICAL content on a timer, so a self-moving value came out of
    the change-detection key. This one redraws DIFFERENT content as fast as a
    hand can turn, so the answer is to draw the page the hand STOPS on."""

    def test_a_hold_that_has_not_expired_holds(self):
        self.assertTrue(tl.display_held(100.0, 100.1))

    def test_a_hold_that_has_expired_does_not(self):
        self.assertFalse(tl.display_held(100.2, 100.1))

    def test_the_instant_it_expires_it_draws(self):
        # The poll thread asks at 30 Hz, so the boundary is asked about often
        # enough to matter: `now == until` must DRAW rather than wait another
        # tick, or the page lands 33 ms later than the settle promises.
        self.assertFalse(tl.display_held(100.1, 100.1))

    def test_an_unset_hold_never_holds(self):
        # The driver arms this only from the controls that can outrun the
        # screens; every other repaint must pass through untouched, and the
        # initial value is 0.0.
        self.assertFalse(tl.display_held(0.0, 0.0))
        self.assertFalse(tl.display_held(12345.0, 0.0))

    def test_the_settle_swallows_a_DELIBERATE_turn_not_just_a_fast_one(self):
        # REWRITTEN 2026-09-04, and the old bound is the defect.
        #
        # This used to assert only `>= 1/8`, because the settle was tuned
        # against "a fast walk, about eight detents a second". A hold
        # coalesces only detents that arrive CLOSER TOGETHER than the hold, so
        # 0.15 bought nothing at all for an ordinary deliberate walk - and the
        # gesture that wedged the controller in a jam was an ordinary walk.
        #
        # Measured at the rig 2026-09-04: three fast ring walks put 934 msg/s
        # sustained and 3,852 in one second on the wire, against a 43/s idle.
        # 934/s is above the 674/s that wedged it.
        #
        # A third of a second between detents is a deliberate turn. That is
        # what this now has to cover.
        self.assertGreaterEqual(tl.DISPLAY_SETTLE_S, 1.0 / 3.0)

    def test_the_settle_is_shorter_than_a_page_can_be_read(self):
        # And it must not become a lag the hand can feel as a broken control.
        # Half a second is where a page step stops reading as "the panel
        # answered" - the owner judged the FEEL of the previous value fine at
        # the rig, so the room being spent here is small on purpose.
        self.assertLessEqual(tl.DISPLAY_SETTLE_S, 0.5)


class ALockedChannelSaysSoFromEveryPage(unittest.TestCase):
    """2026-09-02, from the rig: MOVE at 0 stops the machine rewriting a
    channel, and the owner could only see it on the page that set it. The
    panel's word for a standing decision is a 1 Hz blink, and the Group row is
    the one per-channel light that is visible in every mode."""

    def test_an_unlocked_channel_holds_its_level(self):
        self.assertEqual(tl.locked_light(0.67, False, 0.0), 0.67)
        self.assertEqual(tl.locked_light(0.67, False, 0.6), 0.67)

    def test_a_locked_channel_blinks_between_its_level_and_dim(self):
        self.assertEqual(tl.locked_light(0.67, True, 0.0), 0.67)
        self.assertEqual(tl.locked_light(0.67, True, 0.6), tl.LIGHT_DIM)

    def test_the_dip_is_low_enough_to_SEE(self):
        # The Group row's own floor is 0.10, and 0.12 was measured against
        # the owner's eyes as NEARLY FULL. A blink whose dark half is 0.10 is
        # bytes moving, not a light blinking.
        self.assertLess(tl.locked_light(1.0, True, 0.6), 0.10)

    def test_a_quiet_locked_channel_still_blinks(self):
        # A channel near the bottom of the fader is already close to the dip,
        # so the blink is at its least visible exactly where a player is
        # least likely to be looking. It still has to be a blink and not a
        # steady light: the lit half is the channel's own level, whatever
        # that is.
        self.assertNotEqual(tl.locked_light(0.12, True, 0.0),
                            tl.locked_light(0.12, True, 0.6))

    def test_it_blinks_at_the_panel_rate_and_no_other(self):
        # One rate on the whole panel: a second rate would read as a second
        # meaning. Same phase as every other latched light, from the clock.
        for now in (0.0, 0.25, 0.49, 0.5, 0.75, 1.0):
            self.assertEqual(tl.locked_light(1.0, True, now) == 1.0,
                             tl.blink_phase(now))


class AHandTappedStepOnATakeUsesTheTakesOwnMaterial(unittest.TestCase):
    """2026-09-02. A bare tap in STEP mode used to CLEAR a hand-authored chord
    take and regenerate the whole pattern from the shift register. The fix
    edits the pattern in place instead - and then has to answer a question the
    old path never asked: what PITCH does a tapped-in step take?

    The take's own nearest note, not the generator's line. A pitch from the
    register would be a note nothing else in the take uses, and the pads would
    draw it in the group colour rather than the player amber - so the step the
    player tapped would look like one the machine placed."""

    def test_the_nearest_note_before_wins(self):
        self.assertEqual(tl.take_pitch({0: 43, 12: 50}, 2, 99), 43)

    def test_the_nearest_note_after_wins_when_it_is_nearer(self):
        self.assertEqual(tl.take_pitch({0: 43, 6: 50}, 5, 99), 50)

    def test_a_TIE_goes_to_the_EARLIER_step(self):
        # The note the player just heard is the one they are answering.
        self.assertEqual(tl.take_pitch({0: 43, 8: 50}, 4, 99), 43)

    def test_an_EMPTY_take_falls_back(self):
        # A real case: ownership survives erasing every step, so an owned
        # channel with nothing in it has no material to copy.
        self.assertEqual(tl.take_pitch({}, 5, 99), 99)

    def test_the_step_being_tapped_is_not_its_own_source(self):
        # It is empty by construction - this is the ADD branch - but a caller
        # that passed the whole picture must not get the step's own stale
        # pitch handed back.
        self.assertEqual(tl.take_pitch({5: 60}, 5, 99), 99)

    def test_the_dub_factory_case_end_to_end(self):
        # H holds ONE chord, at step 0, rooted on G2. A tap anywhere else must
        # answer with G2 rather than with whatever the register says.
        self.assertEqual(tl.take_pitch({0: 43}, 8, 71), 43)


class ATappedStepShortensTheNoteBeforeIt(unittest.TestCase):
    """The other half of the same fix. A note may not reach the next SOUNDING
    step - zynseq deletes it when that step writes the same pitch - so adding
    a step has to clamp the note that now runs into it.

    These are note_duration's own rules, pinned against the numbers the dub
    factory actually ships, because that is where the defect was seen."""

    def test_H_holds_its_pad_for_the_whole_bar_when_nothing_follows(self):
        # gate 1500 is fifteen steps, and with only step 0 sounding it keeps
        # every one of them.
        mask = [True] + [False] * 15
        self.assertEqual(tl.note_duration(1500, 0, 16, mask), 15.0)

    def test_a_tap_at_step_4_cuts_it_to_four(self):
        # THE DEFECT THE OWNER HEARD, as arithmetic: the held pad becomes a
        # blip the moment another step sounds.
        mask = [True, False, False, False, True] + [False] * 11
        self.assertEqual(tl.note_duration(1500, 0, 16, mask), 4.0)

    def test_the_clamp_never_reaches_zero(self):
        # Adjacent steps still leave a note that sounds; a zero-length note is
        # a note that never plays.
        mask = [True, True] + [False] * 14
        self.assertEqual(tl.note_duration(1500, 0, 16, mask), 1.0)


class EveryDrumVerbThatRegeneratesTakesThePatternBack(unittest.TestCase):
    """2026-09-02, from the owner's instruction to route every
    `_write_pattern` caller rather than guard the writer.

    The survey found the writer needs no guard: the wrap rewrite, the fill,
    the beat repeat, the reroll and ERASE + Group are all already gated, and
    the pad tap was routed the day before. **What was missing was three verbs
    in the handback set.** LEAN, LANE and RHYTHM each regenerate a drum's
    whole pattern - `clear()` and rewrite - so on a take they deleted it and
    left ownership set, while HITS and ROTATE on the same page handed it back.

    One rule now: a drum verb that regenerates the pattern takes the pattern
    back."""

    # Extend this when a verb starts rewriting a drum's pattern. It is a
    # deliberate hand-written list: the alternative is deriving it from
    # `_apply_generator`, which is in the driver, and the driver does not
    # import off the Pi.
    REGENERATES = ("hits", "rotate", "div", "lean", "lane", "rhythm")

    def test_every_one_of_them_is_in_the_drum_handback_set(self):
        missing = [v for v in self.REGENERATES
                   if v not in tl.HANDBACK_VERBS["drum"]]
        self.assertEqual(
            missing, [],
            "these rewrite a drum's pattern and would destroy a take without "
            f"handing it back: {missing}")

    def test_LEAN_hands_back_when_it_leaves_OFF(self):
        self.assertTrue(tl.hands_back("drum", "lean", "beat"))

    def test_LEAN_turned_back_to_OFF_keeps_the_take(self):
        # Its off value is a NAME, not a zero, which is why it cannot share
        # the numeric exception.
        self.assertFalse(tl.hands_back("drum", "lean", tl.LEAN_OFF))

    def test_LANE_hands_back_when_it_leaves_the_raw_field(self):
        self.assertTrue(tl.hands_back("drum", "lane", 40))

    def test_LANE_turned_down_to_nothing_keeps_the_take(self):
        self.assertFalse(tl.hands_back("drum", "lane", 0))

    def test_RHYTHM_on_a_DRUM_now_hands_back_like_it_does_on_a_voice(self):
        self.assertTrue(tl.hands_back("drum", "rhythm", 50))
        self.assertFalse(tl.hands_back("drum", "rhythm", 0))

    def test_a_verb_that_only_shapes_still_keeps_the_take(self):
        # The other half of the promise, and the guide prints it as a table:
        # VELO, CHANCE and SWING change how a pattern sounds without asking
        # the generator for a new one.
        for verb in ("velo", "chance", "swing", "length"):
            self.assertFalse(tl.hands_back("drum", verb, 50), verb)


class TheWatchdogSaysWhenTheMachineStopped(unittest.TestCase):
    """2026-09-01. The three-hour silence this was written from - a poll thread
    that died by raising - CANNOT recur: that thread has carried an exception
    guard since 643659f. What remains is a thread that stops by BLOCKING, on
    the LinuxSampler socket with no timeout, and no exception handler catches
    that. So the watchdog is a HEARTBEAT, not a try/except."""

    def test_a_fresh_beat_is_not_a_stall(self):
        self.assertFalse(tl.stalled(100.0, 100.0))

    def test_a_beat_inside_the_window_is_not_a_stall(self):
        self.assertFalse(tl.stalled(102.0, 100.0, after=3.0))

    def test_a_beat_older_than_the_window_IS_a_stall(self):
        self.assertTrue(tl.stalled(104.0, 100.0, after=3.0))

    def test_a_beat_that_has_never_happened_is_not_a_stall(self):
        # Before the poll thread's first tick there is nothing to compare
        # against, and reporting a stall at start-up would cry wolf on every
        # boot.
        self.assertFalse(tl.stalled(100.0, None))

    def test_the_window_is_long_enough_not_to_fire_on_a_slow_tick(self):
        # The poll tick is 33 ms and the shipped sub-rate is ~200 ms. A window
        # under a second would fire on a kit change that merely took a while.
        self.assertGreaterEqual(tl.STALL_AFTER_S, 2.0)

    def test_the_banner_says_the_machine_stopped_and_for_how_long(self):
        self.assertEqual(tl.stall_label(114.0, 100.0), "GEN STOPPED 14s")

    def test_the_banner_REPLACES_the_page_label_rather_than_appending(self):
        # The page indicator already composes up to eleven suffixes onto a
        # 42-character line and truncates silently - a logged defect. The one
        # message that must never be the one truncated is this one.
        # 3.5s: past the window, and the banner still says whole seconds.
        self.assertEqual(tl.stall_label(103.5, 100.0, "STEP 1/5"),
                         "GEN STOPPED 3s")

    def test_no_stall_leaves_the_label_exactly_as_it_was(self):
        self.assertEqual(tl.stall_label(100.5, 100.0, "STEP 1/5"), "STEP 1/5")

    def test_a_stall_with_no_beat_leaves_the_label_alone(self):
        self.assertEqual(tl.stall_label(100.0, None, "STEP 1/5"), "STEP 1/5")

    def test_the_seconds_are_whole_because_a_moving_decimal_is_an_animation(self):
        # Never animate a value on the screens. A tenth of a second ticking on
        # the label would repaint both screens ten times a second, which is
        # how this controller has been wedged before.
        self.assertEqual(tl.stall_label(103.9, 100.0), "GEN STOPPED 3s")


class BanksAsScenes(unittest.TestCase):
    """2026-09-01. The sequencer has 64 banks and this instrument has always
    used one. A bank is a complete eight-channel pattern set, so sixteen pads
    are sixteen whole arrangements.

    The published entry said they are "all already in the snapshot". THEY ARE
    NOT: every shipped .zss carries exactly one bank block, and asking zynseq
    for a missing one makes it invent a sixteen-pad grid on MIDI channels 0-3.
    So a bank this instrument uses has to be AUTHORED in this instrument's
    layout, and the picture must never be drawn from a read that allocates."""

    def test_the_overlay_sits_under_ARM_and_over_MUTE(self):
        pri = list(tl.OVERLAY_PRIORITY)
        self.assertIn("bank", pri)
        self.assertLess(pri.index("arm"), pri.index("bank"))
        self.assertLess(pri.index("bank"), pri.index("mute"))

    def test_holding_the_bank_button_owns_the_pads(self):
        self.assertEqual(tl.pad_owner(bank=True), "bank")

    def test_ARM_still_wins_because_its_countdown_must_stay_readable(self):
        self.assertEqual(tl.pad_owner(bank=True, arm=True), "arm")

    def test_the_bank_pads_are_NOT_steps(self):
        # No playhead sweep over an arrangement picker.
        self.assertFalse(tl.overlay_is_stepwise("bank"))

    def test_sixteen_pads_are_sixteen_banks_on_page_one(self):
        self.assertEqual(tl.bank_of_pad(0, 0), 1)
        self.assertEqual(tl.bank_of_pad(15, 0), 16)

    def test_the_big_encoder_walks_four_pages_of_sixteen(self):
        self.assertEqual(tl.bank_of_pad(0, 1), 17)
        self.assertEqual(tl.bank_of_pad(15, 3), 64)

    def test_a_page_outside_the_four_is_refused_rather_than_wrapped(self):
        self.assertIsNone(tl.bank_of_pad(0, 4))
        self.assertIsNone(tl.bank_of_pad(16, 0))

    def test_the_live_bank_is_the_one_bright_pad(self):
        colour, level = tl.bank_pad_look(3, live=3, queued=None, stocked=(1, 3))
        self.assertEqual(level, tl.PAD_FULL)

    def test_a_queued_bank_is_GREEN_because_green_already_means_soon(self):
        colour, _ = tl.bank_pad_look(5, live=3, queued=5, stocked=(1, 3, 5))
        self.assertEqual(colour, tl.COLOR_ARM_LENGTH)

    def test_a_stocked_bank_is_the_same_hue_DIMMER_not_a_new_colour(self):
        live, _ = tl.bank_pad_look(3, live=3, queued=None, stocked=(1, 3))
        stocked, level = tl.bank_pad_look(1, live=3, queued=None,
                                          stocked=(1, 3))
        self.assertEqual(stocked, live)
        self.assertLess(level, tl.PAD_FULL)

    def test_an_empty_bank_is_DARK_so_a_press_claims_nothing(self):
        _, level = tl.bank_pad_look(9, live=3, queued=None, stocked=(1, 3))
        self.assertEqual(level, 0.0)

    def test_the_label_says_which_page_of_banks_is_showing(self):
        self.assertEqual(tl.bank_label(0, 3), "BANK 1/4 . 3")
        self.assertEqual(tl.bank_label(2, 17), "BANK 3/4 . 17")


class APhraseNotABar(unittest.TestCase):
    """2026-09-01. A channel plays four bars where the fourth differs.

    THE MECHANISM IS A REWRITE AT THE BOUNDARY, NOT A TIMELINE, and the
    difference is worth being plain about. zynseq's track really is a
    position->pattern map, so a true timeline exists - but the driver
    hardcodes track 0 / position 0 in ten places, and a wrap would then fire
    once per PHRASE rather than once per bar, silently changing six shipped
    generators. That is the L+ this entry was costed at. What ships here is the
    musical outcome for a fraction of the risk: the generator writes a fill on
    the last bar of the phrase and writes the plain line back on the next one."""

    def test_a_phrase_of_one_is_OFF_and_no_bar_is_ever_a_fill(self):
        for bar in range(8):
            with self.subTest(bar=bar):
                self.assertFalse(tl.is_fill_bar(bar, 1))

    def test_the_LAST_bar_of_the_phrase_is_the_fill(self):
        self.assertFalse(tl.is_fill_bar(0, 4))
        self.assertFalse(tl.is_fill_bar(1, 4))
        self.assertFalse(tl.is_fill_bar(2, 4))
        self.assertTrue(tl.is_fill_bar(3, 4))

    def test_it_repeats_every_phrase(self):
        self.assertTrue(tl.is_fill_bar(7, 4))
        self.assertTrue(tl.is_fill_bar(11, 4))
        self.assertFalse(tl.is_fill_bar(8, 4))

    def test_a_two_bar_phrase_fills_every_other_bar(self):
        self.assertEqual([tl.is_fill_bar(b, 2) for b in range(4)],
                         [False, True, False, True])

    def test_a_fill_of_zero_returns_the_line_UNTOUCHED(self):
        line = tuple(i % 4 == 0 for i in range(16))
        self.assertEqual(tl.fill_line(line, 0), line)

    def test_a_fill_ADDS_steps_and_never_removes_one(self):
        line = tuple(i % 4 == 0 for i in range(16))
        got = tl.fill_line(line, 50)
        for i, on in enumerate(line):
            if on:
                self.assertTrue(got[i])
        self.assertGreater(sum(got), sum(line))

    def test_a_fill_reaches_for_the_OFFBEATS_first(self):
        # A fill that added on the beats would just be a louder version of the
        # bar it is supposed to answer.
        line = tuple(i % 4 == 0 for i in range(16))
        got = tl.fill_line(line, 25)
        added = [i for i in range(16) if got[i] and not line[i]]
        self.assertTrue(added)
        for i in added:
            self.assertNotIn(i, tl.beat_grid(16))

    def test_a_full_fill_does_not_overflow_the_bar(self):
        line = tuple(i % 4 == 0 for i in range(16))
        self.assertEqual(len(tl.fill_line(line, 100)), 16)
        self.assertLessEqual(sum(tl.fill_line(line, 100)), 16)

    def test_it_is_deterministic(self):
        line = tuple(i % 4 == 0 for i in range(16))
        self.assertEqual(tl.fill_line(line, 60), tl.fill_line(line, 60))

    def test_a_triplet_bar_fills_over_its_own_twelve_steps(self):
        line = tuple(i % 3 == 0 for i in range(12))
        got = tl.fill_line(line, 50)
        self.assertEqual(len(got), 12)

    def test_both_kinds_carry_the_verbs_and_start_OFF(self):
        for kind in ("drum", "voice"):
            with self.subTest(kind=kind):
                state = tl.default_channel_state(kind)
                self.assertEqual(state["phrase"], 1)
                self.assertEqual(state["fill"], 0)

    def test_an_older_snapshot_gains_them_OFF(self):
        old = tl.default_channel_state("drum")
        del old["phrase"]
        del old["fill"]
        got = tl.upgrade_state("drum", old, 16)
        self.assertEqual((got["phrase"], got["fill"]), (1, 0))

    def test_PHRASE_is_a_verb_on_the_AUTO_page_of_both_kinds(self):
        # WAS test_the_ALL_ring_carries_a_PHRASE_spread. Its spread page went
        # in the 2026-09-01 collapse; the verb is on AUTO beside FILL, which
        # is the bar it decides the shape of.
        for kind in ("drum", "voice"):
            with self.subTest(kind=kind):
                verbs = _page("AUTO", kind, "AUTO")["verbs"]
                self.assertIn("phrase", verbs)
                self.assertEqual(abs(verbs.index("phrase")
                                     - verbs.index("fill")), 1)

    def test_a_phrase_of_one_reads_BAR_rather_than_a_bare_one(self):
        page = tl.lens_desc("phrase")
        self.assertEqual(page["verb"], "phrase")
        views = [("A", "KICK", {"phrase": 1})] * 8
        self.assertEqual(tl.spread_columns(page, views)[0]["value"], "BAR")
        views = [("A", "KICK", {"phrase": 4})] * 8
        self.assertEqual(tl.spread_columns(page, views)[0]["value"], "4bar")


class TheLightAlphabet(unittest.TestCase):
    """Three levels and two movements, and nothing else is invented.

    Thirty-one of this panel's buttons are single-colour - report 0x82 is one
    byte each and the daemon discards the colour argument - so the whole
    vocabulary is brightness plus time. Before 2026-09-01 it was neither: four
    buttons were lit permanently and said nothing, while four modifiers that
    took the sixteen pads showed nothing while they did it."""

    def test_the_three_levels_are_distinct_and_ordered(self):
        self.assertLess(tl.LIGHT_OFF, tl.LIGHT_DIM)
        self.assertLess(tl.LIGHT_DIM, tl.LIGHT_ON)
        self.assertEqual(tl.LIGHT_OFF, 0.0)
        self.assertEqual(tl.LIGHT_ON, 1.0)

    def test_dim_is_low_enough_to_be_seen_as_dim(self):
        """MEASURED ON THE PANEL, and the first value was wrong by a factor
        of ten.

        These LEDs saturate early: on the rig 0.30 and 0.35 are
        indistinguishable from full and 0.12 is still nearly full. The
        alphabet shipped with DIM at 0.35, which made a held button and an
        idle one look identical - three levels collapsed into two, and the
        whole vocabulary with them.

        The ceiling here is not a style rule. Anything above it is a value a
        person cannot tell from full, which means it is not a level."""

        self.assertLessEqual(tl.LIGHT_DIM, 0.08,
                             "dim above 0.08 reads as full on this hardware")
        self.assertGreater(tl.LIGHT_DIM, 0.0,
                           "dim has to actually light")

    def test_brightness_never_exceeds_one(self):
        # set_button_light clamps at 1.0 (daemon mikro.rs:960), so a 2.0 sent
        # for "more than full" is INDISTINGUISHABLE from 1.0 on the hardware.
        # Two shipped states relied on exactly that and were invisible: the
        # deep FREEZE hold, and REC while an audio capture ran under an
        # overdub. Nothing in this alphabet may ask for more than the panel
        # can draw.
        for value in (tl.LIGHT_OFF, tl.LIGHT_DIM, tl.LIGHT_ON):
            self.assertLessEqual(value, 1.0)

    def test_a_state_button_is_dim_when_it_is_merely_available(self):
        self.assertEqual(tl.state_light(False, False), tl.LIGHT_DIM)

    def test_held_is_bright(self):
        self.assertEqual(tl.state_light(True, False), tl.LIGHT_ON)

    def test_latched_blinks(self):
        lit = tl.state_light(False, True, now=0.0)
        dark = tl.state_light(False, True, now=tl.BLINK_S)
        self.assertEqual(lit, tl.LIGHT_ON)
        self.assertEqual(dark, tl.LIGHT_OFF)

    def test_held_outranks_latched(self):
        # A player holding a button that is also latched is making the short
        # decision NOW, and a steady light is what says the release will
        # change something. A blink there would advertise the standing state
        # while the hand is busy overriding it.
        for now in (0.0, tl.BLINK_S):
            self.assertEqual(tl.state_light(True, True, now=now), tl.LIGHT_ON)

    def test_a_state_button_with_nothing_to_act_on_is_dark(self):
        self.assertEqual(tl.state_light(False, False, available=False),
                         tl.LIGHT_OFF)

    def test_the_blink_phase_comes_from_the_clock(self):
        self.assertTrue(tl.blink_phase(0.0))
        self.assertFalse(tl.blink_phase(tl.BLINK_S))
        self.assertTrue(tl.blink_phase(2 * tl.BLINK_S))

    def test_one_blink_rate_for_the_whole_panel(self):
        # A second rate would read as a second meaning. The panel already had
        # two, and the older one - SELECT's countdown - is driven by the BAR
        # rather than by a timer, so it is a different thing entirely and is
        # allowed to look different.
        self.assertEqual(tl.BLINK_S, 0.5)

    def test_an_action_is_dim_or_dark_and_never_bright(self):
        # Bright is reserved for "acting now", and an action is never acting -
        # it happened and it is over.
        self.assertEqual(tl.action_light(True), tl.LIGHT_DIM)
        self.assertEqual(tl.action_light(False), tl.LIGHT_OFF)

    def test_a_toggle_is_bright_when_true_and_dim_when_reachable(self):
        self.assertEqual(tl.toggle_light(True), tl.LIGHT_ON)
        self.assertEqual(tl.toggle_light(False), tl.LIGHT_DIM)

    def test_a_toggle_with_nothing_behind_it_is_dark(self):
        self.assertEqual(tl.toggle_light(True, available=False), tl.LIGHT_OFF)

    def test_a_toggle_never_blinks(self):
        # Blink means latched-and-your-hand-has-left. PLAY, a mute and a mode
        # are plain facts, not modes a player could be trapped in.
        self.assertEqual(tl.toggle_light(True, True),
                         tl.toggle_light(True, True))
        for now in (0.0, tl.BLINK_S, 2 * tl.BLINK_S):
            self.assertEqual(tl.toggle_light(True), tl.LIGHT_ON)



class ChordsAreStacksOfScaleDegrees(unittest.TestCase):
    """CHORD, 2026-09-02. The design is
    notes/specs/2026-09-02-chords-on-the-surface-design.md; these are the
    claims it rests on.

    The load-bearing one is the FIRST test: shape 0 must be
    bit-identical to the single note, because that is what makes every
    snapshot already written - 017, 018, 019 and both packs - sound exactly
    as it did on the day this shipped."""

    ROOT, SCALE, OCT, RANGE, LEN = 7, 0, 0, 1, 16
    VALUES = (0, 1, 58, 179, 4354, 24222, 40000, 61260, 65535)

    def test_shape_zero_is_the_single_note_and_nothing_else(self):
        for value in self.VALUES:
            self.assertEqual(
                tl.chord_notes(value, self.LEN, self.ROOT, self.SCALE,
                               self.OCT, self.RANGE, 0),
                (tl.pitch(value, self.LEN, self.ROOT, self.SCALE,
                          self.OCT, self.RANGE),),
                f"value {value}")

    def test_a_chord_line_with_chords_off_is_the_old_line(self):
        for register in (58, 179, 61260):
            for octave in (-1, 0, 1):
                line = tl.line(register, 16, 16, self.ROOT, self.SCALE,
                               octave, self.RANGE)
                chords = tl.chord_line(register, 16, 16, self.ROOT,
                                       self.SCALE, octave, self.RANGE, 0)
                self.assertEqual([c[0] for c in chords], list(line))
                self.assertTrue(all(len(c) == 1 for c in chords))

    def test_the_chord_sits_on_the_note_the_line_already_played(self):
        # Turning CHORD up must never MOVE the line - the single note stays
        # and notes are added above it. A chord whose root wanders is a
        # transpose wearing a chord's name.
        for value in self.VALUES:
            root = tl.pitch(value, self.LEN, self.ROOT, self.SCALE,
                            self.OCT, self.RANGE)
            for shape in range(len(tl.CHORD_SHAPES)):
                notes = tl.chord_notes(value, self.LEN, self.ROOT, self.SCALE,
                                       self.OCT, self.RANGE, shape)
                self.assertIn(root, notes, f"value {value} shape {shape}")
                self.assertEqual(min(notes), root)

    def test_a_triad_in_natural_minor_is_root_flat_third_fifth(self):
        notes = tl.chord_notes(179, self.LEN, self.ROOT, self.SCALE,
                               self.OCT, self.RANGE, 3)
        self.assertEqual(notes, (43, 46, 50))          # G2, Bb2, D3
        self.assertEqual([n - notes[0] for n in notes], [0, 3, 7])

    def test_the_fifth_shape_is_a_fifth(self):
        notes = tl.chord_notes(179, self.LEN, self.ROOT, self.SCALE,
                               self.OCT, self.RANGE, 2)
        self.assertEqual([n - notes[0] for n in notes], [0, 7])

    def test_the_octave_shape_is_an_octave(self):
        notes = tl.chord_notes(179, self.LEN, self.ROOT, self.SCALE,
                               self.OCT, self.RANGE, 1)
        self.assertEqual([n - notes[0] for n in notes], [0, 12])

    def test_a_seventh_adds_the_flat_seventh_and_a_ninth_the_ninth(self):
        seventh = tl.chord_notes(179, self.LEN, self.ROOT, self.SCALE,
                                 self.OCT, self.RANGE, 5)
        ninth = tl.chord_notes(179, self.LEN, self.ROOT, self.SCALE,
                               self.OCT, self.RANGE, 6)
        self.assertEqual([n - seventh[0] for n in seventh], [0, 3, 7, 10])
        self.assertEqual([n - ninth[0] for n in ninth], [0, 3, 7, 10, 14])

    def test_a_sus_shape_has_a_fourth_and_no_third(self):
        notes = tl.chord_notes(179, self.LEN, self.ROOT, self.SCALE,
                               self.OCT, self.RANGE, 4)
        self.assertEqual([n - notes[0] for n in notes], [0, 5, 7])

    def test_every_shape_is_diatonic_in_every_scale(self):
        # THE WHOLE REASON SHAPES ARE DEGREES AND NOT SEMITONES. The three
        # voices share one ROOT and one SCALE, and a key change lands on the
        # bar for all of them; a chromatic stack would walk out of the key
        # they are sharing.
        for scale_idx, (name, intervals) in enumerate(tl.SCALES):
            allowed = {(self.ROOT + i) % 12 for i in intervals}
            for shape in range(len(tl.CHORD_SHAPES)):
                for value in self.VALUES:
                    for note in tl.chord_notes(value, self.LEN, self.ROOT,
                                               scale_idx, self.OCT, 2, shape):
                        self.assertIn(note % 12, allowed,
                                      f"{name} shape {shape} value {value}")

    def test_a_pentatonic_triad_is_a_pentatonic_stack(self):
        # Not a bug: in a five-note scale "the third degree up" is a fourth.
        # Diatonic in PENT beats in-tune-in-five-scales-and-wrong-in-the-sixth.
        notes = tl.chord_notes(179, self.LEN, self.ROOT, 5, self.OCT, 1, 3)
        self.assertEqual([n - notes[0] for n in notes], [0, 5, 10])

    def test_an_octave_doubling_follows_the_scale_length(self):
        # The reason octaves are a separate field: an octave is
        # len(intervals) degrees, SEVEN in five scales and FIVE in PENT, so a
        # literal degree offset of 7 would be an octave in MIN and a sixth in
        # PENT.
        for scale_idx in range(len(tl.SCALES)):
            notes = tl.chord_notes(179, self.LEN, self.ROOT, scale_idx,
                                   self.OCT, 1, 1)
            self.assertEqual([n - notes[0] for n in notes], [0, 12],
                             tl.SCALES[scale_idx][0])

    def test_the_notes_come_back_sorted_and_unique(self):
        for scale_idx in range(len(tl.SCALES)):
            for shape in range(len(tl.CHORD_SHAPES)):
                for octave in (-3, 0, 3):
                    notes = tl.chord_notes(60000, self.LEN, self.ROOT,
                                           scale_idx, octave, 2, shape)
                    self.assertEqual(list(notes), sorted(set(notes)))

    def test_no_note_ever_leaves_the_midi_range(self):
        for shape in range(len(tl.CHORD_SHAPES)):
            for octave in (-9, -4, 0, 4, 8):
                for value in self.VALUES:
                    for note in tl.chord_notes(value, self.LEN, self.ROOT,
                                               self.SCALE, octave, 4, shape):
                        self.assertGreaterEqual(note, 0)
                        self.assertLessEqual(note, 127)

    def test_a_shape_index_out_of_range_falls_back_to_off(self):
        # The render and write paths must not throw: a snapshot from a later
        # version, or a clamp that slipped, becomes a single note rather than
        # an exception on the poll thread.
        for shape in (-1, len(tl.CHORD_SHAPES), 99, 1000):
            self.assertEqual(
                tl.chord_notes(179, self.LEN, self.ROOT, self.SCALE,
                               self.OCT, self.RANGE, shape),
                tl.chord_notes(179, self.LEN, self.ROOT, self.SCALE,
                               self.OCT, self.RANGE, 0))

    def test_the_advertised_maximum_is_the_real_one(self):
        # The write burst is steps * CHORD_MAX_NOTES addNote calls under one
        # lock hold, and that is the number a rig gate needs.
        widest = max(
            len(tl.chord_notes(v, self.LEN, self.ROOT, s, self.OCT, 2, shape))
            for v in self.VALUES
            for s in range(len(tl.SCALES))
            for shape in range(len(tl.CHORD_SHAPES)))
        self.assertEqual(widest, tl.CHORD_MAX_NOTES)
        self.assertEqual(tl.CHORD_MAX_NOTES, 5)

    def test_off_is_the_first_shape_because_zero_reads_as_off(self):
        # This instrument's grammar everywhere else: MELODY and RHYTHM at zero
        # hold their registers still, walk_due reads 0 as LOCK.
        self.assertEqual(tl.CHORD_SHAPES[0][0], "OFF")
        self.assertEqual(tl.CHORD_SHAPES[0][1], (0,))
        self.assertEqual(tl.CHORD_SHAPES[0][2], ())

    def test_every_label_fits_the_value_field(self):
        for label, _degrees, _octaves in tl.CHORD_SHAPES:
            self.assertLessEqual(len(label), 4, label)

    def test_the_shapes_only_ever_stack_upward(self):
        for label, degrees, octaves in tl.CHORD_SHAPES:
            self.assertEqual(degrees[0], 0, label)
            self.assertEqual(list(degrees), sorted(set(degrees)), label)
            self.assertTrue(all(o > 0 for o in octaves), label)

    def test_a_chord_line_rotates_exactly_as_the_old_line_does(self):
        chords = tl.chord_line(179, 16, 16, self.ROOT, self.SCALE, self.OCT,
                               self.RANGE, 3)
        roots = [c[0] for c in chords]
        self.assertEqual(roots, list(tl.line(179, 16, 16, self.ROOT,
                                             self.SCALE, self.OCT,
                                             self.RANGE)))
        self.assertTrue(all(len(c) == 3 for c in chords))

    def test_degree_note_is_what_the_keyboard_already_used(self):
        # Extracted from pitch() and pad_note(), which carried identical
        # copies. Three copies of one formula is how a scale gains an
        # off-by-one in exactly one of the places it is used.
        for degree in range(16):
            self.assertEqual(
                tl.degree_note(degree, self.ROOT, self.SCALE, 1),
                tl.pad_note(degree, self.ROOT, self.SCALE, 1))

    def test_the_line_itself_did_not_move_when_chords_arrived(self):
        # A golden regression: these are the pitches 019's BASS register
        # produced before chords existed, read off the shipped snapshot.
        self.assertEqual(
            [tl.line(58, 16, 16, 7, 0, -1, 1)[s] for s in (0, 6, 10, 14)],
            [31, 31, 41, 36])


class ChordRefusesWhereItCannotAct(unittest.TestCase):
    """Law L4 for CHORD. Both refusals were found by reading the code before
    it was built, and both would otherwise have been the exact fault the
    2026-09-01 sweep called worse than a silence: a number that moves on
    screen while the sound does not change."""

    def _view(self, **over):
        view = _voice_view()
        view.update(over)
        return view

    def _dead(self, verb, **over):
        # RANGE lives on the voice's SECOND AUTO page since 2026-09-02, when
        # CHORD took its slot on STEP - so the page has to be looked up rather
        # than assumed, or a verb that moved reads as a verb that vanished.
        for key in (("STEP", "voice"), ("AUTO", "voice")):
            for desc in tl.PAGE_RINGS[key]:
                if verb in desc["verbs"]:
                    cols = tl.columns(desc, "voice", self._view(**over))
                    return cols[desc["verbs"].index(verb)]["grey"]
        raise AssertionError(f"no voice page carries {verb!r}")

    def test_chord_is_live_on_an_ordinary_voice(self):
        self.assertFalse(self._dead("chord"))

    def test_chord_is_dead_on_a_player_owned_channel(self):
        # _write_voice_pattern returns early on a take, by design, so the
        # generator would never write the new shape. This is also the answer
        # to whether the generator retires 019's hand-authored chords: it does
        # not, and the surface says why.
        self.assertTrue(self._dead("chord", owner="player"))

    def test_chord_is_dead_on_a_sampler_behaving_as_a_voice(self):
        # A note number on a kit selects WHICH DRUM sounds, so a stack of
        # scale degrees would add unrelated drum hits rather than thicken
        # anything. Same argument RANGE already makes.
        self.assertTrue(self._dead("chord", sampler=True))

    def test_a_take_does_not_kill_the_whole_page(self):
        # The refusal has to be surgical: a player-owned channel still wants
        # its gate, its swing and its odds.
        #
        # VELO CAME OUT OF THIS LIST ON 2026-09-02, and the line it was on was
        # a BELIEF rather than a measurement - the shape of claim this project
        # keeps catching in its own comments. Every read of a voice's `velo`
        # was found: `_write_voice_pattern`, which returns early on a take,
        # and one unreachable fallback in the step editor. It moved a number
        # and changed no sound. The three below are different and each was
        # checked the same way - `gate` is read by the in-place step editor,
        # and `swing` and `chance` are native per-pattern zynseq properties
        # that act whoever owns the notes.
        for verb in ("gate", "swing", "chance"):
            self.assertFalse(self._dead(verb, owner="player"), verb)

    def test_VELO_and_RANGE_are_dead_on_a_voice_take(self):
        # Both are written ONLY by the generator, and the generator does not
        # write a take. RANGE is read from the LINE page, where it now lives.
        self.assertTrue(self._dead("velo", owner="player"))
        self.assertTrue(self._dead("range", owner="player"))

    def test_and_they_are_live_again_once_the_channel_is_handed_back(self):
        self.assertFalse(self._dead("velo"))
        self.assertFalse(self._dead("range"))

    def test_OCTAVE_stays_live_on_a_take_because_the_PADS_read_it(self):
        # `_pad_note` asks for it on every strike, so it decides what a pad
        # PLAYS whether or not the generator is writing. Greying it would be
        # the opposite lie to the one this round is fixing.
        self.assertFalse(self._dead("octave", owner="player"))

    def test_chord_is_dead_on_every_drum(self):
        drum = _drum_view()
        cols = tl.columns(tl.lens_desc("chord"), None,
                          [(chr(65 + i), tl.CHANNELS[i][1],
                            drum if i < 5 else _voice_view())
                           for i in range(8)])
        self.assertEqual("".join("." if c["grey"] else "#" for c in cols),
                         ".....###")

    def test_chord_may_not_take_a_modulator(self):
        # It rewrites the pattern, which is why gate and velo are out of
        # MOD_TIMBRE. It is not a drift verb either: drift on a PITCH verb has
        # never been played, and shipping it in the same round as the verb
        # itself would mean two untested things at once.
        self.assertFalse(tl.mod_allowed("chord"))
        self.assertFalse(tl.mod_allowed("chord", owned=True))
        self.assertFalse(tl.is_drift("chord"))
        self.assertNotIn("chord", tl.MOD_TIMBRE)
        self.assertNotIn("chord", tl.DRIFT_VERBS)


class ChordMigratesSilently(unittest.TestCase):
    """Every snapshot already written - 017, 018, 019, the genre pack, the
    drone pack - must sound bit for bit as it did. `chord` absent reads 0,
    and shape 0 is the single note."""

    def test_a_new_voice_starts_with_chords_off(self):
        self.assertEqual(tl.default_channel_state("voice")["chord"], 0)

    def test_a_drum_has_no_chord_key_at_all(self):
        self.assertNotIn("chord", tl.default_channel_state("drum"))

    def test_an_old_voice_dict_is_upgraded_to_chords_off(self):
        # upgrade_state builds from default_channel_state, which is what makes
        # a key added today cover a snapshot written months ago.
        old = {"register": 179, "length": 16, "random": 0, "gate": 40,
               "octave": 0, "range": 2, "velo": 110, "density": 100}
        upgraded = tl.upgrade_state("voice", old, 16)
        self.assertEqual(upgraded["chord"], 0)

    def test_the_upgraded_state_still_plays_the_single_note(self):
        upgraded = tl.upgrade_state("voice", {"register": 58, "length": 16,
                                              "octave": -1, "range": 1}, 16)
        self.assertEqual(
            tl.chord_notes(58, upgraded["length"], 7, 0, upgraded["octave"],
                           upgraded["range"], upgraded["chord"]),
            (tl.pitch(58, upgraded["length"], 7, 0, upgraded["octave"],
                      upgraded["range"]),))


class ANoteMayNotReachTheNextSoundingStep(unittest.TestCase):
    """Found by ear on the rig, 2026-09-02, with gate 150 and RHYTHM on.

    zynseq DELETES an overlapping note when the following step writes the same
    pitch. The saved pattern for F kept exactly ONE note of a five-note chord
    on two steps - the one pitch the next step did not re-use - so four notes
    out of five were gone from the pattern itself, not merely from playback.

    NOT a chord bug. A single long note followed by the same pitch on the next
    step has always been eaten this way; a chord shares four pitches with its
    neighbour where a single note shares one or none, so chords made it
    visible. Adjacent sounding steps are rare until RHYTHM moves the register,
    which is why months of play never hit it."""

    FULL = [True] * 16

    def test_the_old_behaviour_is_unchanged_without_a_mask(self):
        # Every existing caller passes no mask and must keep its lengths.
        for gate, step in ((40, 0), (150, 0), (800, 3), (1600, 0), (5, 15)):
            self.assertEqual(tl.note_duration(gate, step, 16),
                             tl.note_duration(gate, step, 16, None))

    def test_a_note_is_cut_at_the_next_sounding_step(self):
        mask = [False] * 16
        mask[0] = mask[1] = True
        self.assertEqual(tl.note_duration(150, 0, 16, mask), 1.0)

    def test_a_note_keeps_its_length_when_the_next_step_is_silent(self):
        mask = [False] * 16
        mask[0] = mask[7] = True
        self.assertEqual(tl.note_duration(150, 0, 16, mask), 1.5)

    def test_the_gap_to_the_next_hit_is_the_ceiling(self):
        mask = [False] * 16
        mask[0] = mask[4] = True
        self.assertEqual(tl.note_duration(800, 0, 16, mask), 4.0)
        self.assertEqual(tl.note_duration(150, 0, 16, mask), 1.5)

    def test_the_loop_point_still_clamps_on_the_last_step(self):
        # The original clamp, unchanged: a note may not outlive its pattern.
        self.assertEqual(tl.note_duration(800, 15, 16, self.FULL), 1.0)

    def test_a_lone_note_in_the_bar_keeps_the_full_gate(self):
        mask = [False] * 16
        mask[0] = True
        self.assertEqual(tl.note_duration(1500, 0, 16, mask), 15.0)

    def test_the_floor_still_holds(self):
        mask = [True] * 16
        self.assertEqual(tl.note_duration(1, 0, 16, mask), 0.05)

    def test_no_note_ever_reaches_its_successor_on_any_mask(self):
        # The property, over every mask a 16-step pattern can have bits for.
        import random as _r
        rng = _r.Random(20260902)
        for _ in range(400):
            reg = rng.randrange(1, 1 << 16)
            mask = [bool(reg >> i & 1) for i in range(16)]
            hits = [i for i, on in enumerate(mask) if on]
            for step in hits:
                dur = tl.note_duration(1600, step, 16, mask)
                later = [h for h in hits if h > step]
                if later:
                    self.assertLessEqual(dur, later[0] - step,
                                         f"step {step} reaches {later[0]}")
                self.assertLessEqual(dur, 16 - step)

    def test_the_defect_that_was_measured_on_the_rig(self):
        # rhythm_reg 28803 is what the owner's save carried: bits 0, 1, 7, 12,
        # 13 and 14. At gate 150 steps 0 and 13 each reached their neighbour,
        # and each lost four of its five chord notes.
        mask = tl.rhythm_mask(28803, 16)
        self.assertEqual([i for i, on in enumerate(mask) if on],
                         [0, 1, 7, 12, 13, 14])
        self.assertEqual(tl.note_duration(150, 0, 16, mask), 1.0)
        self.assertEqual(tl.note_duration(150, 13, 16, mask), 1.0)
        # The two that were never in danger keep their full length.
        self.assertEqual(tl.note_duration(150, 7, 16, mask), 1.5)
        self.assertEqual(tl.note_duration(150, 14, 16, mask), 1.5)


class TheWetLawIsAnAudioTaper(unittest.TestCase):
    """2026-09-04, found by ear at the rig: the owner could not hear the dub
    factory's clap echo, and the reason was arithmetic rather than the mix.

    The old law was linear in dB across the port's -70..+10 range, and BOTH
    halves of the project implemented it identically - the driver's `_set_wet`
    and the snapshot builder's `wet_db` - which is exactly why nothing caught
    it. Two agreeing implementations of one wrong idea look like a verified
    one.
    """

    def test_a_wet_percent_is_an_amplitude(self):
        # The ordinary audio taper: halving the number is -6 dB.
        self.assertAlmostEqual(tl.wet_db(100), 0.0, places=2)
        self.assertAlmostEqual(tl.wet_db(50), -6.02, places=2)
        self.assertAlmostEqual(tl.wet_db(25), -12.04, places=2)
        self.assertAlmostEqual(tl.wet_db(10), -20.0, places=2)

    def test_the_defect_this_replaced_cannot_come_back(self):
        # THE NUMBERS FROM THE RIG. Under the old law 30% was -46 dB and -10 dB
        # needed 75% of the knob, so every reverb and delay in the instrument
        # was inaudible while the surface claimed otherwise.
        self.assertGreater(tl.wet_db(30), -12.0)
        self.assertLess(tl.wet_db(30), -9.0)

    def test_zero_is_off_and_a_hundred_is_unity(self):
        # An off send must be OFF - the port's floor, which is also what every
        # existing snapshot stores for a send nobody turned up.
        self.assertEqual(tl.wet_db(0), tl.WET_OFF)
        # And the top of the knob is unity, NOT the port's +10. A wet send
        # louder than the signal feeding it is not something this surface
        # should be able to ask for by accident, and the top of a knob is
        # exactly where an accident lands.
        self.assertEqual(tl.wet_db(100), tl.WET_UNITY)

    def test_the_round_trip_is_exact_on_every_whole_percent(self):
        for percent in range(101):
            self.assertEqual(tl.wet_percent(tl.wet_db(percent)), percent)

    def test_a_value_stored_under_the_old_law_reads_honestly(self):
        # THE MIGRATION IS THAT THERE ISN'T ONE. Nothing rewrites a stored dB;
        # the read-back is the inverse of the new law, so `019`'s clap - saved
        # at -56.71 dB and heard as silence - now DISPLAYS as the silence it
        # always was instead of claiming 30.
        self.assertEqual(tl.wet_percent(-56.71), 0)
        self.assertEqual(tl.wet_percent(-46.0), 1)

    def test_it_is_clamped_at_both_ends(self):
        self.assertEqual(tl.wet_db(-5), tl.WET_OFF)
        self.assertEqual(tl.wet_db(150), tl.WET_UNITY)


class TheModLegendSaysWhenNothingIsBound(unittest.TestCase):
    """2026-09-04: the owner held MOD after a snapshot load, saw twelve blue
    pads and four violet, pressed one and nothing happened."""

    def test_the_inert_legend_is_dim_by_the_panels_own_measurement(self):
        # It was 0.25, and this panel's eye calibration says 0.30 and 0.35 both
        # read as FULL while 0.12 is "nearly full". So "inert" was painting a
        # menu indistinguishable from a live one.
        self.assertLessEqual(tl.MOD_LEGEND_INERT, 0.08)

    def test_an_unbound_pad_is_dimmer_than_a_bound_one(self):
        inert = tl.mod_legend_pad(0, 0.0, 0, tl.MOD_SHAPES[0], bound=False)
        live = tl.mod_legend_pad(0, 0.0, 0, tl.MOD_SHAPES[0], bound=True)
        self.assertLess(inert[1], live[1])


class TheModDepthMultiplierIsVisible(unittest.TestCase):
    """2026-09-04: it scales every live modulator at once, sits on the most
    prominent control, and had no readout anywhere. One half-revolution
    out-and-back left it at ~0.84 and nothing said so.

    The three-eyes runbook claimed "you cannot leave this wrong by accident".
    It was left wrong by accident on the first attempt.
    """

    def test_unity_is_not_drawn(self):
        # At 1.0 it is the absence of a setting, and drawing it would put a
        # word in the change key for nothing. This display has been broken
        # four times by exactly that.
        self.assertNotIn("x", tl.mod_rate_label("STEP", True, 1.0, 1.0))

    def test_a_drifted_multiplier_is_drawn(self):
        label = tl.mod_rate_label("STEP", True, 1.0, 0.84)
        self.assertIn("x0.84", label)

    def test_it_is_drawn_even_with_no_modulator_bound(self):
        # THE FIX. The rate needs a bound modulator to talk about; the
        # multiplier does not - it is a global over all of them. Gating both
        # on `mod_last` is why the big encoder under MOD moved a value nothing
        # displayed.
        self.assertIn("x0.8", tl.mod_rate_label("STEP", True, None, 0.8))

    def test_nothing_is_drawn_when_mod_is_not_active(self):
        self.assertEqual(tl.mod_rate_label("STEP", False, 1.0, 0.5), "STEP")


# --------------------------------------------------------------- FX_ROLES
#
# The table that replaced resolving REVERB and DELAY by plugin NAME. The
# guards here are the ones that would have caught the original defect: an
# insert that appears in a shipped manifest and is in NEITHER the role table
# nor the explicit no-role set is a plugin whose knobs silently do nothing.

class FXRolesCase(unittest.TestCase):
    def test_every_entry_declares_a_role_and_a_blend(self):
        for plugin, spec in tl.FX_ROLES.items():
            self.assertIn(spec.get("role"), ("reverb", "delay"), plugin)
            self.assertIn(spec.get("blend"), ("send", "crossfade"), plugin)

    def test_every_entry_has_at_least_one_wet_port(self):
        for plugin, spec in tl.FX_ROLES.items():
            self.assertTrue(spec.get("WET"), plugin)
            for port in spec["WET"]:
                symbol, kind, lo, hi = port
                self.assertTrue(symbol, plugin)
                self.assertIn(kind, ("db", "lin"), plugin)
                self.assertLess(lo, hi, plugin)

    def test_a_crossfade_has_no_dry_port(self):
        # That IS what makes it a crossfade: there is nothing separate to
        # leave alone, which is why the wet is ceilinged.
        for plugin, spec in tl.FX_ROLES.items():
            if spec["blend"] == "crossfade":
                self.assertNotIn("DRY", spec, plugin)

    def test_a_send_has_a_dry_port(self):
        for plugin, spec in tl.FX_ROLES.items():
            if spec["blend"] == "send":
                self.assertIn("DRY", spec, plugin)

    def test_revtype_exists_on_exactly_one_plugin(self):
        # `mode` 0..42 is TAP Reverberator's alone. If a second plugin ever
        # claims REVTYPE, somebody has mapped it onto a port that is not a
        # room list and the global will pick rooms nobody asked for.
        have = [p for p, s in tl.FX_ROLES.items() if "REVTYPE" in s]
        self.assertEqual(have, ["TAP Reverberator"])

    def test_a_dlytime_entry_declares_its_unit(self):
        # Three unit systems exist and only milliseconds can take a
        # tempo-derived value. An entry without the unit would be written to
        # as if it were ms.
        for plugin, spec in tl.FX_ROLES.items():
            if "DLYTIME" not in spec:
                continue
            entry = spec["DLYTIME"]
            self.assertEqual(len(entry), 4, plugin)
            self.assertEqual(entry[3], "ms", plugin)

    def test_no_plugin_is_in_both_the_table_and_the_no_role_set(self):
        self.assertEqual(set(tl.FX_ROLES) & set(tl.FX_NO_ROLE), set())

    def test_lookup_tolerates_the_engine_name_prefix(self):
        self.assertIsNone(tl.fx_role_of(""))
        self.assertIsNone(tl.fx_role_of(None))
        self.assertIsNone(tl.fx_role_of("JV/Nothing At All"))
        for name in ("TAP Reverberator", "JV/TAP Reverberator",
                     "Jalv/TAP Reverberator x"):
            found = tl.fx_role_of(name)
            self.assertIsNotNone(found, name)
            self.assertEqual(found[1]["role"], "reverb")

    def test_a_db_wet_is_the_audio_taper(self):
        spec = tl.FX_ROLES["TAP Reverberator"]
        got = dict(tl.fx_wet_values(spec, 100))
        self.assertAlmostEqual(got["wetlevel"], 0.0, places=2)
        got = dict(tl.fx_wet_values(spec, 50))
        self.assertAlmostEqual(got["wetlevel"], -6.02, places=2)
        got = dict(tl.fx_wet_values(spec, 0))
        self.assertAlmostEqual(got["wetlevel"], tl.WET_OFF, places=2)

    def test_a_linear_wet_spans_its_own_range(self):
        spec = tl.FX_ROLES["Tal-Reverb-III"]
        self.assertAlmostEqual(dict(tl.fx_wet_values(spec, 100))["wet"], 1.0)
        self.assertAlmostEqual(dict(tl.fx_wet_values(spec, 50))["wet"], 0.5)
        self.assertAlmostEqual(dict(tl.fx_wet_values(spec, 0))["wet"], 0.0)

    def test_dragonflys_two_wet_ports_are_early_and_late(self):
        # NOT a stereo pair, which is the reason WET is a tuple of ports
        # rather than a symbol plus an optional WET_R.
        spec = tl.FX_ROLES["Dragonfly Hall Reverb"]
        got = dict(tl.fx_wet_values(spec, 100))
        self.assertEqual(sorted(got), ["early_level", "late_level"])

    def test_a_crossfade_never_reaches_full_wet(self):
        # A full knob on a plugin with no dry port would delete the channel's
        # dry signal, and a channel that vanishes without saying why is the
        # one thing this surface may not do.
        for plugin, spec in tl.FX_ROLES.items():
            if spec["blend"] != "crossfade":
                continue
            for symbol, value in tl.fx_wet_values(spec, 100):
                _sym, _kind, lo, hi = next(
                    p for p in spec["WET"] if p[0] == symbol)
                self.assertLess(value, hi, f"{plugin}.{symbol}")
                self.assertAlmostEqual(
                    value, lo + (hi - lo) * tl.CROSSFADE_CEILING, places=4,
                    msg=f"{plugin}.{symbol}")

    def test_every_wet_value_stays_inside_its_port(self):
        for plugin, spec in tl.FX_ROLES.items():
            for percent in (-50, 0, 1, 37, 100, 250):
                for symbol, value in tl.fx_wet_values(spec, percent):
                    _s, _k, lo, hi = next(
                        p for p in spec["WET"] if p[0] == symbol)
                    self.assertGreaterEqual(value, lo, f"{plugin} {percent}")
                    self.assertLessEqual(value, hi, f"{plugin} {percent}")


class EveryShippedInsertIsAccountedForCase(unittest.TestCase):
    """THE GUARD THAT WOULD HAVE CAUGHT THE ORIGINAL DEFECT.

    An insert plugin named by a shipped manifest must be in FX_ROLES or in
    FX_NO_ROLE. Anything else is a chain whose REVERB and DELAY knobs do
    nothing, whose reverb and delay modulators are inert, and whose four FX
    globals are dead - in silence, which is how 41 of 71 presets shipped that
    way for weeks."""

    def manifests(self):
        import glob
        import json
        import os
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        found = []
        for path in sorted(glob.glob(os.path.join(root, "snapshot",
                                                  "*-manifest.json"))):
            with open(path) as fh:
                doc = json.load(fh)
            # THE FACTORY MANIFEST IS ONE ENTRY, NOT A LIST, and it names no
            # inserts at all - it builds on 018, which already carries them.
            # Normalising here rather than filtering by filename, so a third
            # shape shows up as a failure instead of being skipped in silence.
            entries = doc if isinstance(doc, list) else [doc]
            found.append((os.path.basename(path), entries))
        return found

    def test_there_is_at_least_one_manifest_to_check(self):
        self.assertTrue(self.manifests())

    def test_every_insert_is_in_the_table_or_named_as_roleless(self):
        known = set(tl.FX_ROLES) | set(tl.FX_NO_ROLE)
        unknown = {}
        for name, entries in self.manifests():
            for entry in entries:
                for plugin in entry.get("fx") or ():
                    bare = str(plugin).split("/")[-1]
                    if bare not in known:
                        unknown.setdefault(bare, []).append(
                            f"{name}:{entry.get('file')}")
        self.assertEqual(unknown, {},
                         "insert plugins in no FX table: "
                         + ", ".join(sorted(unknown)))
