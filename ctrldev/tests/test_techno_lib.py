import os
import random
import sys
import unittest
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from techno_lib import techno_lib as tl  # noqa: E402


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


class TestColumnModel(unittest.TestCase):

    def drum_state(self, **over):
        s = dict(kit="T808", sample="KICK", level=82, reverb=24, delay=36,
                 hits=4, rotate=0, div=1, length=16, velo=110, chance=100,
                 swing=50, pending=set())
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
        s = dict(root=9, scale=0, bpm=132, master=88,
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

    def test_swing_is_column_seven_on_the_drum_step_page(self):
        st = self.drum_state()
        self.assertEqual(tl.columns(_desc("STEP", "drum"), "drum", st)[6]["name"],
                         "SWING")

    def test_rhythm_is_column_four_on_the_voice_step_page(self):
        # The voice traded its SWING column for DENSITY. Swing did not go
        # away: it is the STEP ring's spread page, all eight channels at once.
        st = self.voice_state()
        # Encoder 4, beside MELODY on 3: the owner put the two generators
        # side by side at the rig, because they are one idea.
        self.assertEqual(tl.columns(_desc("STEP", "voice"), "voice", st)[3]["name"],
                         "RHYTHM")

    def test_drum_control_has_three_greyed_columns(self):
        cols = tl.columns(_desc("CONTROL", "drum"), "drum", self.drum_state())
        grey = [c for c in cols if c["grey"]]
        self.assertEqual([c["name"] for c in grey], ["tune", "decay", "filtr"])
        for c in grey:
            self.assertEqual(c["value"], "----")
            self.assertIsNone(c["bar"])

    def test_voice_control_has_no_greyed_column(self):
        cols = tl.columns(_desc("CONTROL", "voice"), "voice", self.voice_state())
        self.assertEqual([c["name"] for c in cols if c["grey"]], [])

    def test_ratchet_is_drawn_greyed_on_the_drum_step_page(self):
        col = tl.columns(_desc("STEP", "drum"), "drum", self.drum_state())[7]
        self.assertEqual(col["name"], "ratchet")
        self.assertTrue(col["grey"])
        self.assertEqual(col["value"], "----")

    def test_random_zero_reads_lock_not_a_number(self):
        col = tl.columns(_desc("STEP", "voice"), "voice", self.voice_state(random=0))[2]
        self.assertEqual(col["value"], "LOCK")
        self.assertEqual(len(col["value"]), 4)

    def test_pending_value_is_wrapped_in_angle_brackets(self):
        st = self.drum_state(div=2, pending={"div"})
        col = tl.columns(_desc("STEP", "drum"), "drum", st)[2]
        self.assertTrue(col["pending"])
        self.assertTrue(col["value"].startswith(">") and col["value"].endswith("<"))

    def test_all_page_is_the_same_for_both_kinds(self):
        gl = self.globals_state()
        a = [c["name"] for c in tl.columns(_desc("ALL", "drum"), "drum", gl)]
        b = [c["name"] for c in tl.columns(_desc("ALL", "voice"), "voice", gl)]
        self.assertEqual(a, b)
        self.assertEqual(a, ["ROOT", "SCALE", "BPM", "MASTER",
                             "REVSIZE", "REVTYPE", "DLYTIME", "DLYFBK"])

    def test_every_value_fits_the_cell(self):
        for page, kind, st in (("CONTROL", "drum", self.drum_state()),
                               ("CONTROL", "voice", self.voice_state()),
                               ("STEP", "drum", self.drum_state()),
                               ("STEP", "voice", self.voice_state()),
                               ("ALL", "drum", self.globals_state())):
            for c in tl.columns(_desc(page, kind), kind, st):
                self.assertLessEqual(len(c["value"].strip("><")), 4,
                                     f"{page}/{kind}/{c['name']}={c['value']}")

    def test_octave_draws_a_bipolar_bar(self):
        # Encoder 6 since the 2026-08-16 reorder, was 5.
        col = tl.columns(_desc("STEP", "voice"), "voice", self.voice_state())[5]
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
        self.assertEqual(tl.ring_key("MIXER", "drum"), ("MIXER", None))
        self.assertEqual(tl.ring_key("FILTER", "voice"), ("FILTER", None))
        self.assertEqual(tl.ring_key("ALL", "drum"), ("ALL", None))

    def test_ring_key_keeps_kind_for_control_and_step(self):
        self.assertEqual(tl.ring_key("CONTROL", "drum"), ("CONTROL", "drum"))
        self.assertEqual(tl.ring_key("STEP", "voice"), ("STEP", "voice"))

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
        for key, ring in tl.PAGE_RINGS.items():
            for desc in ring:
                if desc["shape"] == tl.SHAPE_SPREAD:
                    self.assertIsInstance(desc["verb"], str)
                    self.assertIsNone(desc["verbs"])

    def test_mixer_ring_is_level_reverb_delay(self):
        ring = tl.PAGE_RINGS[("MIXER", None)]
        self.assertEqual([d["verb"] for d in ring], ["level", "reverb", "delay"])

    def test_filter_ring_is_cutoff_reso(self):
        ring = tl.PAGE_RINGS[("FILTER", None)]
        self.assertEqual([d["verb"] for d in ring], ["cutoff", "reso"])

    def test_step_ring_keeps_its_channel_page_first(self):
        for kind in ("drum", "voice"):
            ring = tl.PAGE_RINGS[("STEP", kind)]
            self.assertEqual(ring[0]["shape"], tl.SHAPE_CHANNEL)
            self.assertEqual([d["verb"] for d in ring[1:3]], ["swing", "chance"])

    def test_step_channel_page_verbs_match_the_shipped_layout(self):
        self.assertEqual(
            tl.PAGE_RINGS[("STEP", "drum")][0]["verbs"],
            ("hits", "rotate", "div", "length", "velo", "chance", "swing", None))
        # Reordered by the owner at the rig, 2026-08-16: pattern time first,
        # then the two generators SIDE BY SIDE, then pitch, then velocity.
        # Encoder 3 is MELODY on the panel but keeps the key `random`.
        # THIS ORDER MUST MATCH _columns_inner's list position for position -
        # verbs decide what an encoder writes, that list what it draws, and
        # nothing checks they agree at runtime.
        self.assertEqual(
            tl.PAGE_RINGS[("STEP", "voice")][0]["verbs"],
            ("div", "gate", "random", "rhythm", "length", "octave",
             "range", "velo"))

    def test_control_channel_page_verbs_match_the_shipped_layout(self):
        self.assertEqual(
            tl.PAGE_RINGS[("CONTROL", "drum")][0]["verbs"],
            ("kit", "sample", None, None, None, "level", "reverb", "delay"))
        self.assertEqual(
            tl.PAGE_RINGS[("CONTROL", "voice")][0]["verbs"],
            ("preset", "cutoff", "reso", "env", "decay", "level", "reverb", "delay"))

    def test_all_page_one_keeps_every_shipped_global(self):
        # The four FX globals stay here. dlytime is a musical division resolved
        # against live tempo and revtype is a room index - neither is a raw
        # plugin port, so neither can move to a generated page.
        self.assertEqual(
            tl.PAGE_RINGS[("ALL", None)][0]["verbs"],
            ("root", "scale", "bpm", "master", "revsize", "revtype",
             "dlytime", "dlyfbk"))


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
    view = dict(hits=4, rotate=0, div=1, length=16, velo=110, chance=100,
                swing=50, level=19, reverb=0, delay=0, kit="909", sample="BD",
                pending=set())
    view.update(over)
    return view


def _voice_view(**over):
    view = dict(length=8, div=1, random=0, gate=40, octave=0, range=2,
                swing=50, velo=110, level=19, reverb=0, delay=0, chance=100,
                rhythm=0, rhythm_reg=0xFFFF, preset="SAW", cutoff=64, reso=32, env=64, decay=40,
                pending=set())
    view.update(over)
    return view


class TestColumnsByShape(unittest.TestCase):

    def test_channel_shape_still_renders_the_shipped_step_page(self):
        desc = tl.PAGE_RINGS[("STEP", "drum")][0]
        cols = tl.columns(desc, "drum", _drum_view())
        self.assertEqual([c["name"] for c in cols],
                         ["HITS", "ROTATE", "DIVIDE", "LENGTH", "VELO",
                          "CHANCE", "SWING", "ratchet"])
        self.assertTrue(cols[7]["grey"])

    def test_global_shape_still_renders_the_shipped_all_page(self):
        desc = tl.PAGE_RINGS[("ALL", None)][0]
        state = dict(root=9, scale=0, bpm=132, master=80, revsize=25,
                     revtype=3, dlytime=1, dlyfbk=35, pending=set())
        cols = tl.columns(desc, "drum", state)
        self.assertEqual([c["name"] for c in cols],
                         ["ROOT", "SCALE", "BPM", "MASTER", "REVSIZE",
                          "REVTYPE", "DLYTIME", "DLYFBK"])

    def test_spread_shape_labels_each_column_with_its_channel(self):
        desc = tl.PAGE_RINGS[("MIXER", None)][0]
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
        desc = tl.PAGE_RINGS[("FILTER", None)][0]
        views = [("A", "KICK", _drum_view()), ("F", "BASS", _voice_view())]
        views += [("X", "----", _drum_view())] * 6
        cols = tl.columns(desc, None, views)
        self.assertTrue(cols[0]["grey"])
        self.assertEqual(cols[0]["value"], "----")
        self.assertIsNone(cols[0]["bar"])
        self.assertFalse(cols[1]["grey"])
        self.assertEqual(cols[1]["value"], "0064")

    def test_spread_swing_uses_the_shipped_swing_fraction(self):
        desc = tl.PAGE_RINGS[("STEP", "drum")][1]
        views = [("A", "KICK", _drum_view(swing=75))] * 8
        cols = tl.columns(desc, "drum", views)
        self.assertAlmostEqual(cols[0]["frac"], 1.0)

    def test_spread_chance_reads_a_voice_too(self):
        desc = tl.PAGE_RINGS[("STEP", "voice")][2]
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

    def test_the_voice_step_ring_gains_a_rhythm_page(self):
        ring = tl.PAGE_RINGS[("STEP", "voice")]
        self.assertEqual([d["verb"] for d in ring[1:]],
                         ["swing", "chance", "rhythm"])

    def test_the_drum_step_ring_is_unchanged(self):
        # A drum's rhythm is HITS and ROTATE, already exact. Euclidean
        # channels get no second generator.
        ring = tl.PAGE_RINGS[("STEP", "drum")]
        self.assertEqual([d["verb"] for d in ring[1:]], ["swing", "chance"])

    def test_rhythm_sits_beside_melody_on_the_voice_channel_page(self):
        self.assertEqual(
            tl.PAGE_RINGS[("STEP", "voice")][0]["verbs"],
            ("div", "gate", "random", "rhythm", "length", "octave",
             "range", "velo"))

    def test_the_spread_spec_maps_the_full_range(self):
        _, to_frac = tl.SPREAD_SPECS["rhythm"]
        self.assertEqual(to_frac(0), 0.0)
        self.assertEqual(to_frac(100), 1.0)

    def test_the_rhythm_spread_page_greys_a_drum(self):
        desc = tl.PAGE_RINGS[("STEP", "voice")][3]
        views = [("A", "KICK", _drum_view()), ("F", "BASS", _voice_view())]
        views += [("X", "----", _drum_view())] * 6
        cols = tl.columns(desc, None, views)
        self.assertTrue(cols[0]["grey"])
        self.assertEqual(cols[0]["value"], "----")
        self.assertFalse(cols[1]["grey"])
        # 0 is LOCK: a voice starts with its rhythm frozen, where DENSITY
        # started at 100. The steps it sounds come from the register, which
        # starts with every bit set - so the SOUND is unchanged, only the
        # number on this page moves.
        self.assertEqual(cols[1]["value"], "0000")


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

    def test_the_free_ccs_stay_free(self):
        # Measured free at G4 and re-verified 2026-08-14. SWING 50 is claimed
        # by MOD, and NOTE REPEAT 10 by the register undo, so neither is here.
        # DUPLICATE 29 joined the list 2026-08-15 when the register undo moved
        # off it onto NOTE REPEAT.
        for cc in (5, 6, 12, 25, 26, 29, 30, 34):
            self.assertNotIn(cc, tl.BUTTONS_STATEFUL)
            self.assertNotIn(cc, tl.BUTTONS_PRESS)

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
        # SELECT (CC 30) was the design's first home for this and the owner
        # moved it to TEMPO. SELECT stays free surface.
        self.assertNotIn(30, tl.BUTTONS_STATEFUL)
        self.assertNotIn(30, tl.BUTTONS_PRESS)

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

    def test_generation_verbs_are_refused_in_v1(self):
        # HITS/ROTATE/DENSITY/CHANCE are the DRIFT targets. Drift is deferred
        # and blocked on the SP2-ownership rule, so MOD refuses them for now.
        for verb in ("hits", "rotate", "rhythm", "chance"):
            self.assertFalse(tl.mod_allowed(verb), verb)

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
        desc = {"title": "CTRL", "shape": tl.SHAPE_CHANNEL,
                "verbs": [None] * 8}
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

    def test_the_pattern_verbs_are_refused(self):
        # HITS, ROTATE, DENSITY and CHANCE rewrite the pattern, and velo/gate
        # were removed from MOD_TIMBRE after an LFO on VELO destroyed a
        # recorded take every 200 ms.
        state = _drum_step_state()
        cols = tl.columns(self.STEP, "drum", state, mod=True)
        for i, verb in enumerate(self.STEP["verbs"]):
            if verb in ("hits", "rotate", "chance", "velo"):
                self.assertIsNone(cols[i]["bar"], verb)
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
        cols = tl.columns(desc, None, views, mod=True)
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
    """The two generators must read as one idea on the panel: MELODY on
    encoder 3, RHYTHM on encoder 7, each with LOCK at zero."""

    def test_the_voice_step_page_names_both_generators(self):
        verbs = tl.PAGE_RINGS[("STEP", "voice")][0]["verbs"]
        self.assertEqual(verbs[2], "random")     # MELODY keeps its state key
        self.assertEqual(verbs[3], "rhythm")     # right beside it
        self.assertNotIn("density", verbs)

    def test_the_columns_are_labelled_melody_and_rhythm(self):
        desc = tl.PAGE_RINGS[("STEP", "voice")][0]
        cols = tl.columns(desc, "voice", _voice_view())
        self.assertEqual(cols[2]["name"], "MELODY")
        self.assertEqual(cols[3]["name"], "RHYTHM")

    def test_the_density_spread_page_became_a_rhythm_page(self):
        verbs = [d.get("verb") for d in tl.PAGE_RINGS[("STEP", "voice")][1:]]
        self.assertEqual(verbs, ["swing", "chance", "rhythm"])
        self.assertIn("rhythm", tl.SPREAD_SPECS)
        self.assertNotIn("density", tl.SPREAD_SPECS)

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
    VOICE_STEP = (
        ("div", "DIVIDE"), ("gate", "GATE"), ("random", "MELODY"),
        ("rhythm", "RHYTHM"), ("length", "LENGTH"), ("octave", "OCTAVE"),
        ("range", "RANGE"), ("velo", "VELO"),
    )

    def test_every_voice_step_column_draws_its_own_verb(self):
        desc = tl.PAGE_RINGS[("STEP", "voice")][0]
        cols = tl.columns(desc, "voice", _voice_view())
        for index, (verb, name) in enumerate(self.VOICE_STEP):
            self.assertEqual(desc["verbs"][index], verb, f"verb at {index}")
            self.assertEqual(cols[index]["name"], name, f"name at {index}")

    def test_the_two_generators_are_adjacent(self):
        # The owner's reason for the layout: they are one idea, so the hand
        # finds them together. A reorder that separates them is a regression.
        verbs = tl.PAGE_RINGS[("STEP", "voice")][0]["verbs"]
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

    def test_the_hue_is_constant_across_rungs(self):
        # Brightness carries the value; the hue must stay recognisable at every
        # level it is dimmed to, so it must not change with the value.
        hues = {tl.probability_pad(True, c)[0] for c in (100, 75, 50, 25)}
        self.assertEqual(len(hues), 1)

    def test_the_hue_is_not_a_group_colour(self):
        # Group colours are not reserved during an overlay, but reusing one
        # while the step picture is suppressed still invites misreading.
        self.assertNotIn(tl.probability_pad(True, 100)[0],
                         {c for _, _, _, c, _, _ in tl.CHANNELS})
