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

    def test_rhythm_is_column_seven_on_the_drum_step_page(self):
        # The DRUM traded its SWING column for RHYTHM on 2026-08-31, exactly as
        # the voice traded its own for the second generator in 2026-08-16.
        # Swing did not go away on either: it is the STEP ring's spread page,
        # all eight channels at once, which is where it is wanted in a jam.
        st = self.drum_state()
        self.assertEqual(tl.columns(_desc("STEP", "drum"), "drum", st)[6]["name"],
                         "RHYTHM")

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

    def test_ratchet_is_LIVE_on_the_drum_step_page(self):
        # CHANGED 2026-08-19, SP10 step 3. This column was the page's dead
        # eighth slot from the prototype onwards, drawn `----` and greyed
        # because nothing wrote it. RATCHET fills it.
        col = tl.columns(_desc("STEP", "drum"), "drum", self.drum_state())[7]
        self.assertEqual(col["name"], "RATCH")
        self.assertFalse(col["grey"])
        self.assertEqual(col["value"], "OFF")

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
            ("hits", "rotate", "div", "length", "velo", "chance", "rhythm",
             "ratchet"))
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
                swing=50, rhythm=0, level=19, reverb=0, delay=0, kit="909",
                sample="BD", pending=set())
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
                          "CHANCE", "RHYTHM", "RATCH"])
        # No longer greyed: SP10 step 3 gave the slot a verb, 2026-08-19.
        self.assertFalse(cols[7]["grey"])

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
        # [1:4], not [1:] - the ring gained a GEN page on 2026-08-31 and a
        # channel-shaped page carries no single `verb`.
        ring = tl.PAGE_RINGS[("STEP", "voice")]
        self.assertEqual([d["verb"] for d in ring[1:4]],
                         ["swing", "chance", "rhythm"])

    def test_the_drum_step_ring_keeps_its_two_spread_pages(self):
        # REVERSED BY THE OWNER, 2026-08-31. This test used to read "a drum's
        # rhythm is HITS and ROTATE, already exact - euclidean channels get no
        # second generator", and the drum rhythm register is exactly that
        # second generator. The RING is still swing and chance; what changed is
        # the CHANNEL page, where encoder 7 traded SWING for RHYTHM - the same
        # trade the owner already made on the voice page, and for the same
        # reason: swing is on the spread page below, reachable for all eight
        # channels at once, which is where it is wanted in a jam.
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

    def test_the_rhythm_spread_page_now_reaches_a_drum_too(self):
        # It used to grey a drum, because a drum view carried no `rhythm` key
        # and spread_columns draws dead where the source does not exist. The
        # drum rhythm register puts the key on the drum state, so this page
        # lights up for all eight channels with NO change to the page itself -
        # the grey was never a rule, it was the absence of a value.
        desc = tl.PAGE_RINGS[("STEP", "voice")][3]
        views = [("A", "KICK", _drum_view()), ("F", "BASS", _voice_view())]
        views += [("X", "----", _drum_view())] * 6
        cols = tl.columns(desc, None, views)
        self.assertFalse(cols[0]["grey"])
        self.assertEqual(cols[0]["value"], "0000")
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
        # The two later single-button captures.
        self.assertEqual(sorted(tl.CCS_MEASURED_SINGLE), [10, 35])
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

    def test_the_reroll_buttons_are_bound_and_stateful(self):
        # Stateful, not press-only: hold-to-fire needs the release.
        self.assertEqual(tl.BUTTONS_STATEFUL[25], "reroll_scene")
        self.assertEqual(tl.BUTTONS_STATEFUL[26], "reroll_pattern")

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
        self.assertEqual(verbs[:3], ["swing", "chance", "rhythm"])
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
        desc = tl.PAGE_RINGS[("STEP", "drum")][0]
        self.assertEqual(desc["verbs"][7], "ratchet")

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
        self.assertEqual(cols[7]["value"], "OFF")

    def test_a_ratchet_column_shows_its_count(self):
        state = _drum_step_state()
        state["ratchet"] = 3
        cols = tl.columns(tl.PAGE_RINGS[("STEP", "drum")][0], "drum", state)
        self.assertIn("3", cols[7]["value"])

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
    """Taking the F row is the only part of switch exposure that is not
    additive, so what the row means is a table, tested."""

    def test_control_unmodified_is_switches(self):
        self.assertEqual(tl.f_row_kind("CONTROL", False, False, False),
                         tl.F_ROW_SWITCH)

    def test_every_other_mode_keeps_mute(self):
        for mode in ("STEP", "ALL", "MIXER", "FILTER"):
            self.assertEqual(tl.f_row_kind(mode, False, False, False),
                             tl.F_ROW_MUTE)

    def test_shift_hands_mute_back_inside_control(self):
        self.assertEqual(tl.f_row_kind("CONTROL", True, False, False),
                         tl.F_ROW_MUTE)

    def test_solo_still_solos_inside_control(self):
        self.assertEqual(tl.f_row_kind("CONTROL", False, True, False),
                         tl.F_ROW_MUTE)

    def test_mod_makes_the_row_inert_rather_than_switching(self):
        self.assertEqual(tl.f_row_kind("CONTROL", False, False, True),
                         tl.F_ROW_INERT)

    def test_mod_outside_control_is_still_mute(self):
        # MOD only takes a row that switch exposure had taken in the first
        # place; outside CONTROL nothing about the row changed.
        self.assertEqual(tl.f_row_kind("STEP", False, False, True),
                         tl.F_ROW_MUTE)

    def test_shift_outranks_mod(self):
        self.assertEqual(tl.f_row_kind("CONTROL", True, False, True),
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
                                    "macro", "walk")))


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
        for desc in tl.PAGE_RINGS[tl.ring_key("STEP", "voice")]:
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
        for desc in tl.PAGE_RINGS[tl.ring_key("ALL", None)]:
            if desc["shape"] == tl.SHAPE_PENDING:
                self.assertIsNone(desc.get("verbs"))
                break
        else:
            self.fail("no PENDING page on the ALL ring")

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

    def test_the_page_is_on_the_ALL_ring(self):
        titles = [d["title"] for d in tl.PAGE_RINGS[tl.ring_key("ALL", None)]]
        self.assertIn("PENDING", titles)
        # The ring had exactly one page before this, so the big encoder did
        # nothing at all on ALL.
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
    """The GEN page: one new page in the voice STEP ring carrying three of
    P1's five features. A new page in an existing ring is the cheapest surface
    this instrument has - no button, no measurement, no overlay."""

    def _state(self, **over):
        st = tl.default_channel_state("voice")
        st.update(over)
        return st

    def test_the_voice_step_ring_gains_a_gen_page(self):
        titles = [d["title"] for d in tl.PAGE_RINGS[("STEP", "voice")]]
        self.assertIn("GEN", titles)

    def test_the_gen_page_verbs_match_what_it_draws(self):
        # verbs decide what an encoder WRITES, _columns_inner what it DRAWS,
        # and nothing checks they agree at runtime. This is that check.
        desc = [d for d in tl.PAGE_RINGS[("STEP", "voice")]
                if d["title"] == "GEN"][0]
        self.assertEqual(desc["verbs"],
                         ("rotate", "model", "walk_span", "walk_stride",
                          "feed", "amount", None, None))
        # On the WALK model every one of the six is live. On the register
        # model SPAN and STRIDE draw dead - see the test below.
        cols = tl.columns(desc, "voice", self._state(model=tl.MODEL_WALK))
        self.assertEqual([c["name"] for c in cols][:6],
                         ["ROTATE", "MODEL", "SPAN", "STRIDE", "FEED", "AMT"])

    def test_the_two_unused_columns_draw_dead(self):
        # A lit column that does nothing is the fault this surface must never
        # commit - law L4, draw dead rather than a number the knob cannot move.
        desc = [d for d in tl.PAGE_RINGS[("STEP", "voice")]
                if d["title"] == "GEN"][0]
        cols = tl.columns(desc, "voice", self._state())
        self.assertTrue(cols[6]["grey"])
        self.assertTrue(cols[7]["grey"])

    def test_a_new_voice_reads_as_the_register_model(self):
        desc = [d for d in tl.PAGE_RINGS[("STEP", "voice")]
                if d["title"] == "GEN"][0]
        cols = tl.columns(desc, "voice", self._state())
        self.assertEqual(cols[1]["value"], "REG")

    def test_the_walk_model_says_so(self):
        desc = [d for d in tl.PAGE_RINGS[("STEP", "voice")]
                if d["title"] == "GEN"][0]
        cols = tl.columns(desc, "voice", self._state(model=tl.MODEL_WALK))
        self.assertEqual(cols[1]["value"], "WALK")

    def test_no_feed_reads_as_off(self):
        # A silent channel must say why - and so must a coupling that is not
        # coupled to anything.
        desc = [d for d in tl.PAGE_RINGS[("STEP", "voice")]
                if d["title"] == "GEN"][0]
        cols = tl.columns(desc, "voice", self._state())
        self.assertEqual(cols[4]["value"], "OFF")


class TestWalkPage(unittest.TestCase):
    """The WALK page: the chord walker's four numbers, in the ALL ring beside
    the globals it moves."""

    def _globals(self, **over):
        g = dict(root=0, scale=0, bpm=125, master=80, revsize=50, revtype=0,
                 dlytime=2, dlyfbk=30, walk=0, wspan=2, pending=set())
        g.update(over)
        return g

    def test_the_all_ring_gains_a_walk_page(self):
        self.assertIn("WALK", [d["title"] for d in tl.PAGE_RINGS[("ALL", None)]])

    def test_the_walk_page_draws_root_scale_and_the_walker(self):
        desc = [d for d in tl.PAGE_RINGS[("ALL", None)]
                if d["title"] == "WALK"][0]
        cols = tl.columns(desc, None, self._globals())
        self.assertEqual([c["name"] for c in cols][:4],
                         ["ROOT", "SCALE", "WALK", "SPAN"])

    def test_a_locked_walker_says_lock_rather_than_a_number(self):
        # 0 is LOCK everywhere else on this instrument; reading "0000" here
        # would invite turning it down looking for off.
        desc = [d for d in tl.PAGE_RINGS[("ALL", None)]
                if d["title"] == "WALK"][0]
        cols = tl.columns(desc, None, self._globals())
        self.assertEqual(cols[2]["value"], "LOCK")

    def test_a_running_walker_shows_its_bar_count(self):
        desc = [d for d in tl.PAGE_RINGS[("ALL", None)]
                if d["title"] == "WALK"][0]
        cols = tl.columns(desc, None, self._globals(walk=4))
        self.assertEqual(cols[2]["value"], "4bar")

    def test_the_shipped_global_page_is_untouched(self):
        desc = tl.PAGE_RINGS[("ALL", None)][0]
        cols = tl.columns(desc, None, self._globals())
        self.assertEqual([c["name"] for c in cols],
                         ["ROOT", "SCALE", "BPM", "MASTER", "REVSIZE",
                          "REVTYPE", "DLYTIME", "DLYFBK"])


class TestGenPageDeadColumns(unittest.TestCase):
    """SPAN and STRIDE belong to the walk. On the register model they are not
    dimmed-but-turnable, they are DEAD - law L4, draw dead rather than a number
    the knob cannot make audible."""

    def _desc(self):
        return [d for d in tl.PAGE_RINGS[("STEP", "voice")]
                if d["title"] == "GEN"][0]

    def test_span_and_stride_are_dead_on_the_register_model(self):
        st = tl.default_channel_state("voice")
        cols = tl.columns(self._desc(), "voice", st)
        self.assertTrue(cols[2]["grey"])
        self.assertTrue(cols[3]["grey"])

    def test_they_come_alive_on_the_walk_model(self):
        st = tl.default_channel_state("voice")
        st["model"] = tl.MODEL_WALK
        cols = tl.columns(self._desc(), "voice", st)
        self.assertFalse(cols[2]["grey"])
        self.assertFalse(cols[3]["grey"])


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
