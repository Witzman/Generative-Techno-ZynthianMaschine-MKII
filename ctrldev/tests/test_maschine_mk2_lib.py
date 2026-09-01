import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from maschine_mk2_lib import maschine_mk2_lib as lib  # noqa: E402


class TestDivisions(unittest.TestCase):

    def test_divisions_in_order(self):
        labels = [d[0] for d in lib.DIVISIONS]
        self.assertEqual(labels, ["1/32", "1/16", "1/8", "1/16T", "1/8T", "1/4"])

    def test_straight_divisions_have_16_steps(self):
        self.assertEqual(lib.step_count(0), 16)
        self.assertEqual(lib.step_count(1), 16)
        self.assertEqual(lib.step_count(2), 16)

    def test_triplet_divisions_have_12_steps(self):
        self.assertEqual(lib.step_count(3), 12)
        self.assertEqual(lib.step_count(4), 12)

    def test_steps_per_beat_matches_division(self):
        self.assertEqual(lib.DIVISIONS[0][1], 8)
        self.assertEqual(lib.DIVISIONS[1][1], 4)
        self.assertEqual(lib.DIVISIONS[2][1], 2)
        self.assertEqual(lib.DIVISIONS[3][1], 6)
        self.assertEqual(lib.DIVISIONS[4][1], 3)

    def test_beats_times_spb_equals_step_count(self):
        for idx, (_, spb, beats) in enumerate(lib.DIVISIONS):
            self.assertEqual(spb * beats, lib.step_count(idx))


class TestEuclid(unittest.TestCase):

    def test_zero_hits_is_empty(self):
        self.assertEqual(lib.euclid(16, 0), [False] * 16)

    def test_all_hits_is_full(self):
        self.assertEqual(lib.euclid(16, 16), [True] * 16)

    def test_four_hits_evenly_spaced(self):
        p = lib.euclid(16, 4)
        self.assertEqual([i for i, v in enumerate(p) if v], [0, 4, 8, 12])

    def test_three_hits_matches_daemon_bresenham(self):
        p = lib.euclid(16, 3)
        self.assertEqual([i for i, v in enumerate(p) if v], [0, 5, 10])

    def test_first_hit_always_on_step_zero(self):
        self.assertTrue(lib.euclid(16, 1)[0])

    def test_hits_clamped_to_steps(self):
        self.assertEqual(sum(lib.euclid(12, 20)), 12)


class TestRotate(unittest.TestCase):

    def test_rotation_zero_is_identity(self):
        p = lib.euclid(16, 4)
        self.assertEqual(lib.rotate(p, 0), p)

    def test_rotation_shifts_hits_later(self):
        p = lib.rotate(lib.euclid(16, 4), 1)
        self.assertEqual([i for i, v in enumerate(p) if v], [1, 5, 9, 13])

    def test_rotation_wraps_around(self):
        p = lib.rotate(lib.euclid(16, 4), 16)
        self.assertEqual([i for i, v in enumerate(p) if v], [0, 4, 8, 12])

    def test_rotation_preserves_hit_count(self):
        p = lib.rotate(lib.euclid(12, 5), 7)
        self.assertEqual(sum(p), 5)


class TestBuildPattern(unittest.TestCase):

    def test_build_uses_division_step_count(self):
        self.assertEqual(len(lib.build_pattern(3, 4, 0)), 12)

    def test_build_applies_hits_and_rotation(self):
        p = lib.build_pattern(1, 4, 2)
        self.assertEqual([i for i, v in enumerate(p) if v], [2, 6, 10, 14])


class TestClamp(unittest.TestCase):

    def test_clamp_reduces_value_over_step_count(self):
        self.assertEqual(lib.clamp_to_steps(16, 3), 12)

    def test_clamp_leaves_value_in_range(self):
        self.assertEqual(lib.clamp_to_steps(5, 3), 5)

    def test_clamp_floors_at_zero(self):
        self.assertEqual(lib.clamp_to_steps(-3, 1), 0)


class TestOscMessage(unittest.TestCase):

    def test_path_is_null_terminated_and_padded_to_4(self):
        msg = lib.osc_message("/ab", [])
        self.assertEqual(msg[:4], b"/ab\x00")

    def test_type_tag_for_int_and_float(self):
        msg = lib.osc_message("/x", [1, 2.0])
        self.assertIn(b",if", msg)

    def test_int_argument_is_big_endian(self):
        msg = lib.osc_message("/x", [1])
        self.assertEqual(msg[-4:], b"\x00\x00\x00\x01")

    def test_total_length_is_multiple_of_four(self):
        for path in ("/a", "/abc", "/abcd", "/abcde"):
            self.assertEqual(len(lib.osc_message(path, [3, 0.5])) % 4, 0)

    def test_pad_osc_targets_pad_path_with_three_args(self):
        msg = lib.pad_osc(3, 0xFF8800, 0.7)
        self.assertEqual(msg[:16], b"/maschine/pad\x00\x00\x00")
        self.assertIn(b",iif", msg)

    def test_button_osc_targets_named_button_path(self):
        msg = lib.button_osc("f1", 0xFFFFFF, 1.0)
        self.assertTrue(msg.startswith(b"/maschine/button/f1"))
        self.assertIn(b",if", msg)

    def test_path_not_aligned_pads_with_terminator_and_filler(self):
        # "/abc" (4 bytes) + null terminator = 5 bytes -> needs 3 filler bytes to
        # reach the next 4-byte boundary (8 total).
        msg = lib.osc_message("/abc", [])
        self.assertEqual(msg, b"/abc\x00\x00\x00\x00,\x00\x00\x00")

    def test_path_already_aligned_with_terminator_needs_no_filler(self):
        # "/ab" (3 bytes) + null terminator = 4 bytes -> already on the boundary,
        # so no filler bytes are added. This is the case a buggy padder using
        # "4 - len(data) % 4" (missing the outer "% 4") gets wrong: it would add
        # 4 spurious zero bytes here instead of 0.
        msg = lib.osc_message("/ab", [])
        self.assertEqual(msg, b"/ab\x00,\x00\x00\x00")

    def test_full_packet_with_args_is_byte_exact(self):
        # Pins down the whole packet position-by-position: path padding, the
        # type-tag string's own padding (",if" + null is already 4-aligned, the
        # same edge case the off-by-one padder above gets wrong), and the
        # big-endian int/float argument bytes.
        msg = lib.osc_message("/x", [1, 2.0])
        self.assertEqual(msg, b"/x\x00\x00,if\x00\x00\x00\x00\x01\x40\x00\x00\x00")


class TestLedCache(unittest.TestCase):

    def test_first_write_is_a_change(self):
        cache = lib.led_cache()
        self.assertTrue(cache.changed("pad3", (0xFF0000, 1.0)))

    def test_same_value_twice_is_not_a_change(self):
        cache = lib.led_cache()
        cache.changed("pad3", (0xFF0000, 1.0))
        self.assertFalse(cache.changed("pad3", (0xFF0000, 1.0)))

    def test_different_value_is_a_change(self):
        cache = lib.led_cache()
        cache.changed("pad3", (0xFF0000, 1.0))
        self.assertTrue(cache.changed("pad3", (0xFF0000, 0.1)))

    def test_clear_forgets_everything(self):
        cache = lib.led_cache()
        cache.changed("pad3", (0xFF0000, 1.0))
        cache.clear()
        self.assertTrue(cache.changed("pad3", (0xFF0000, 1.0)))


class TestLedCacheTtl(unittest.TestCase):
    """A suppressed write must eventually be retried.

    The cache is what stops the driver flooding the daemon, and until
    2026-08-22 it was also what made a LOST write permanent: the pad LED went
    one way, the cache believed it had already said so, and nothing ever sent
    it again. Measured on the rig - a pad read dark for minutes while the
    driver's own picture said lit. A TTL on the key turns that from permanent
    into at most one refresh period."""

    def setUp(self):
        self.clock = [100.0]
        self.cache = lib.led_cache(now=lambda: self.clock[0])

    def test_no_ttl_still_suppresses_forever(self):
        # Every existing caller passes no TTL and must be unaffected.
        self.cache.changed("disp0", "x")
        self.clock[0] += 3600.0
        self.assertFalse(self.cache.changed("disp0", "x"))

    def test_inside_the_ttl_it_suppresses(self):
        self.cache.changed("pad3", (1, 1.0), ttl=3.0)
        self.clock[0] += 2.9
        self.assertFalse(self.cache.changed("pad3", (1, 1.0), ttl=3.0))

    def test_past_the_ttl_it_resends_the_same_value(self):
        self.cache.changed("pad3", (1, 1.0), ttl=3.0)
        self.clock[0] += 3.1
        self.assertTrue(self.cache.changed("pad3", (1, 1.0), ttl=3.0))

    def test_a_resend_restarts_the_clock(self):
        self.cache.changed("pad3", (1, 1.0), ttl=3.0)
        self.clock[0] += 3.1
        self.cache.changed("pad3", (1, 1.0), ttl=3.0)
        self.clock[0] += 1.0
        self.assertFalse(self.cache.changed("pad3", (1, 1.0), ttl=3.0))

    def test_a_real_change_restarts_the_clock_too(self):
        self.cache.changed("pad3", (1, 1.0), ttl=3.0)
        self.clock[0] += 2.0
        self.assertTrue(self.cache.changed("pad3", (1, 0.1), ttl=3.0))
        self.clock[0] += 2.0
        self.assertFalse(self.cache.changed("pad3", (1, 0.1), ttl=3.0))

    def test_keys_expire_independently(self):
        self.cache.changed("pad3", (1, 1.0), ttl=3.0)
        self.clock[0] += 2.0
        self.cache.changed("pad4", (1, 1.0), ttl=3.0)
        self.clock[0] += 1.5
        self.assertTrue(self.cache.changed("pad3", (1, 1.0), ttl=3.0))
        self.assertFalse(self.cache.changed("pad4", (1, 1.0), ttl=3.0))


class TestBuildPatternSteps(unittest.TestCase):
    """Pattern length is independent of division, so an explicit step count
    has to work for lengths a division would never produce."""

    def test_length_is_the_requested_step_count(self):
        for steps in range(1, 17):
            self.assertEqual(len(lib.build_pattern_steps(steps, 2, 0)), steps)

    def test_short_pattern_places_hits_evenly(self):
        self.assertEqual(lib.build_pattern_steps(4, 2, 0),
                         [True, False, True, False])

    def test_rotation_applies_at_short_lengths(self):
        self.assertEqual(lib.build_pattern_steps(4, 1, 1),
                         [False, True, False, False])

    def test_hits_are_capped_at_the_step_count(self):
        self.assertEqual(lib.build_pattern_steps(4, 99, 0), [True] * 4)

    def test_agrees_with_build_pattern_at_a_division_length(self):
        self.assertEqual(lib.build_pattern(1, 5, 2),
                         lib.build_pattern_steps(lib.step_count(1), 5, 2))


class TestOscStrings(unittest.TestCase):

    def test_string_arg_is_tagged_and_null_padded(self):
        msg = lib.osc_message("/x", ["AB"])
        self.assertIn(b",s", msg)
        self.assertTrue(msg.endswith(b"AB\x00\x00"))

    def test_every_message_length_is_a_multiple_of_four(self):
        for args in ([], [1], [1.0], ["ABC"], [0, 1, "ABCD"]):
            self.assertEqual(len(lib.osc_message("/maschine/display/text", args)) % 4, 0)


class TestEncoderMovement(unittest.TestCase):

    def test_first_value_is_not_a_movement(self):
        self.assertEqual(lib.encoder_delta(None, 90), 0)

    def test_movement_is_signed(self):
        self.assertEqual(lib.encoder_delta(64, 67), 3)
        self.assertEqual(lib.encoder_delta(64, 61), -3)

    def test_repeat_at_the_end_stop_is_no_movement(self):
        # The daemon keeps reporting 127 while the knob turns past its top;
        # that must not keep pushing the parameter.
        self.assertEqual(lib.encoder_delta(127, 127), 0)

    def test_recentre_message_carries_index_and_value(self):
        self.assertEqual(lib.encoder_osc(3, 64),
                         lib.osc_message("/maschine/encoder", [3, 64]))

    def test_sensitivity_matches_the_absolute_sweep(self):
        # 17 hit values (0-16) across the 128-unit sweep is what the absolute
        # mapping gave; the relative one has to cost the same movement.
        self.assertAlmostEqual(lib.units_per_step(17), 128 / 17)
        self.assertAlmostEqual(lib.units_per_step(5), 25.6)
        self.assertAlmostEqual(lib.units_per_step(4), 32.0)

    def test_zero_values_does_not_divide_by_zero(self):
        self.assertEqual(lib.units_per_step(0), 128)

    def test_the_step_factor_is_two(self):
        # Pinned here and nowhere else. It has moved twice already - x10 as a
        # FINE modifier, then x3 as the default - each time by playing the
        # rig, so the tests below derive from the constant and only this one
        # asserts the number. A change here is a change to the whole feel of
        # the surface and should be a deliberate line in a diff.
        self.assertEqual(lib.STEP_FACTOR, 2)

    def test_the_default_steps_finer_by_the_factor(self):
        self.assertAlmostEqual(lib.step_units(8, False), 8 * lib.STEP_FACTOR)
        self.assertAlmostEqual(lib.step_units(lib.units_per_step(17), False),
                               lib.STEP_FACTOR * 128 / 17)

    def test_coarse_is_exactly_the_old_feel(self):
        # COARSE must return the raw units unchanged - identically, not
        # "close enough" after a float round trip. The whole promise is that
        # holding TEMPO gives back the sensitivity that shipped before this,
        # so a drum gesture that used to take one sweep still takes one.
        self.assertEqual(lib.step_units(8, True), 8)
        self.assertEqual(lib.step_units(lib.units_per_step(17), True),
                         lib.units_per_step(17))

    def test_nothing_is_faster_than_coarse(self):
        # COARSE is the ceiling, not an overdrive: the default may never
        # out-run it, or the surface would have got twitchier than it was.
        for values in (2, 5, 17, 128):
            units = lib.units_per_step(values)
            self.assertGreaterEqual(lib.step_units(units, False),
                                    lib.step_units(units, True))

    def test_the_default_still_reaches_a_step(self):
        # A fraction of a step per detent is the point; never reaching one at
        # all would be a dead knob, which is the failure this guards.
        carry, taken = 0, 0
        for _ in range(8 * lib.STEP_FACTOR):
            steps, carry = lib.encoder_steps(carry, 1, lib.step_units(8, False))
            taken += steps
        self.assertEqual(taken, 1)

    def test_a_full_sweep_covers_a_fraction_of_the_range(self):
        # 128 units of travel walks a 17-value parameter end to end under
        # COARSE (test_a_full_sweep_covers_the_whole_range below); by default
        # the same travel must move it 17/STEP_FACTOR, truncated.
        carry, taken = 0, 0
        units = lib.step_units(lib.units_per_step(17), False)
        for _ in range(128):
            steps, carry = lib.encoder_steps(carry, 1, units)
            taken += steps
        self.assertEqual(taken, 17 // lib.STEP_FACTOR)

    def test_small_movement_takes_no_step(self):
        self.assertEqual(lib.encoder_steps(0, 1, 8)[0], 0)

    def test_movement_accumulates_into_a_step(self):
        carry = 0
        taken = 0
        for _ in range(8):
            steps, carry = lib.encoder_steps(carry, 1, 8)
            taken += steps
        self.assertEqual(taken, 1)

    def test_remainder_is_carried_not_dropped(self):
        steps, carry = lib.encoder_steps(0, 10, 8)
        self.assertEqual(steps, 1)
        self.assertAlmostEqual(carry, 2)

    def test_backwards_movement_steps_backwards(self):
        self.assertEqual(lib.encoder_steps(0, -8, 8)[0], -1)

    def test_a_full_sweep_covers_the_whole_range(self):
        # 128 units of movement has to walk a 17-value parameter end to end.
        carry, taken = 0, 0
        for _ in range(128):
            steps, carry = lib.encoder_steps(carry, 1, lib.units_per_step(17))
            taken += steps
        self.assertEqual(taken, 17)

    def test_carry_does_not_leak_across_a_direction_change(self):
        steps, carry = lib.encoder_steps(0, 3, 8)
        self.assertEqual(steps, 0)
        self.assertEqual(lib.encoder_steps(carry, -3, 8), (0, 0))


class TestScreenLayout(unittest.TestCase):

    TABS = tuple(("ABCD"[i], "KICK", i == 0, i == 3) for i in range(4))
    COLS = (("HITS", "5", "u", 0.3), ("ROT", "2", "s", 0.2),
            ("DIV", "1/16", "s", 0.25), ("LEN", "16", "u", 1.0))

    def test_screen_starts_with_a_clear(self):
        packets = lib.screen_packets(0, self.TABS, self.COLS)
        self.assertEqual(packets[0], lib.display_clear_osc(0))

    def test_a_numeric_value_stays_double_height(self):
        packets = lib.screen_packets(0, self.TABS, self.COLS)
        self.assertIn(lib.display_text_osc(0, 3, lib.VALUE_Y, 2, False, "5"),
                      packets)

    def test_a_name_column_draws_small_and_wide(self):
        # PRESET, KIT and SAMPLE carry names. Four double-height characters
        # cannot separate Dusk from Dusk2, so a flagged column drops to the
        # small font and nine characters.
        cols = (("PRESET", "GettinRe2", "s", 0.0, None, None, True),
                ) + self.COLS[1:]
        packets = lib.screen_packets(0, self.TABS, cols)
        self.assertIn(
            lib.display_text_osc(0, 3, lib.VALUE_Y, 1, False, "GettinRe2"),
            packets)

    def test_a_small_value_is_capped_at_nine_characters(self):
        cols = (("PRESET", "AbcdefghijKLM", "s", 0.0, None, None, True),
                ) + self.COLS[1:]
        packets = lib.screen_packets(0, self.TABS, cols)
        self.assertIn(
            lib.display_text_osc(0, 3, lib.VALUE_Y, 1, False, "Abcdefghi"),
            packets)

    def test_columns_without_the_flag_are_unchanged(self):
        # The seventh field is optional, exactly as mod and tick are: every
        # existing caller passes a 4-tuple and must keep working.
        short = lib.screen_packets(0, self.TABS, self.COLS)
        explicit = lib.screen_packets(
            0, self.TABS,
            tuple(c + (None, None, False) for c in self.COLS))
        self.assertEqual(short, explicit)

    def test_selected_tab_is_inverted_and_muted_tab_is_dashed(self):
        packets = lib.screen_packets(0, self.TABS, self.COLS)
        self.assertIn(lib.display_rect_osc(0, 1, 0, lib.SCREEN_COL - 4,
                                           lib.TAB_H, lib.RECT_INVERT), packets)
        self.assertIn(lib.display_rect_osc(0, 3 * lib.SCREEN_COL + 1, 0,
                                           lib.SCREEN_COL - 4, lib.TAB_H,
                                           lib.RECT_DASHED), packets)

    def test_nothing_is_drawn_past_the_right_edge(self):
        # x=255 is in the byte stride but not on glass, so a layout that
        # reaches it has silently lost a pixel column.
        for screen in (0, 1):
            for x in (0, lib.SCREEN_COL, 2 * lib.SCREEN_COL, 3 * lib.SCREEN_COL):
                self.assertLessEqual(x + lib.SCREEN_COL - 4, lib.SCREEN_W)

    def test_empty_column_draws_no_bar(self):
        self.assertEqual(lib.bar_packets(1, 0, 56, "", 0.5), [])

    def test_bipolar_bar_at_centre_still_draws_something(self):
        packets = lib.bar_packets(1, 0, 56, "b", 0.5)
        self.assertEqual(len(packets), 2)      # outline plus a 1 px stub

    def test_segment_bar_draws_eight_segments(self):
        packets = lib.bar_packets(1, 0, 56, "s", 1.0)
        self.assertEqual(len(packets), 9)      # outline plus eight segments

    def test_unknown_bar_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            lib.bar_packets(0, 0, 56, "z", 0.5)

    def test_bar_fraction_is_clamped(self):
        self.assertEqual(lib.bar_packets(0, 0, 56, "u", 5.0),
                         lib.bar_packets(0, 0, 56, "u", 1.0))
        self.assertEqual(lib.bar_packets(0, 0, 56, "u", -1.0),
                         lib.bar_packets(0, 0, 56, "u", 0.0))


class TestModulationBar(unittest.TestCase):
    """The span and the tick have to be visible against a filled bar.

    Every modulatable verb draws bar kind 'u' - solid from the left out to
    the base - and the span is centred on the base, so its lower half and the
    whole negative half of the tick's travel stand on already-lit pixels. A
    dashed outline there sets pixels that are already set, and a filled tick
    there is a filled block inside a filled block: both were drawn every
    frame and neither could be seen for half of every cycle."""

    X, W, FRAC = 0, 56, 0.5

    # x=1, width 54 inner; fill runs 1..27 inclusive, so the fill edge is 28.
    IX, IW = 1, 54
    IY, IH = lib.BAR_Y + 2, lib.BAR_H - 4
    FILL_END = 28

    def _packets(self, mod, tick=None):
        return lib.bar_packets(0, self.X, self.W, "u", self.FRAC,
                               mod=mod, tick=tick)

    def test_the_tick_is_inverted_not_filled(self):
        packets = self._packets((0.25, 0.75), tick=0.3)
        tick_x = self.IX + int(self.IW * 0.3)     # 0.3 < 0.5: stands on fill
        self.assertLess(tick_x, self.FILL_END)
        self.assertIn(
            lib.display_rect_osc(0, tick_x, self.IY, 2, self.IH, lib.RECT_INVERT),
            packets)
        self.assertNotIn(
            lib.display_rect_osc(0, tick_x, self.IY, 2, self.IH, lib.RECT_FILL),
            packets)

    def test_the_tick_is_inverted_above_the_fill_too(self):
        # One style for the whole sweep, so the mark does not change
        # appearance as it crosses the base.
        packets = self._packets((0.25, 0.75), tick=0.7)
        tick_x = self.IX + int(self.IW * 0.7)
        self.assertGreater(tick_x, self.FILL_END)
        self.assertIn(
            lib.display_rect_osc(0, tick_x, self.IY, 2, self.IH, lib.RECT_INVERT),
            packets)

    def test_the_span_is_split_at_the_fill_edge(self):
        packets = self._packets((0.25, 0.75))
        span_x = self.IX + int(self.IW * 0.25)
        span_w = int(self.IW * 0.5)
        lit = self.FILL_END - span_x
        self.assertIn(
            lib.display_rect_osc(0, span_x, self.IY, lit, self.IH, lib.RECT_INVERT),
            packets)
        self.assertIn(
            lib.display_rect_osc(0, self.FILL_END, self.IY, span_w - lit,
                                 self.IH, lib.RECT_DASHED),
            packets)
        # And never the old single dashed rect across the whole span, whose
        # lower half landed inside the fill and vanished.
        self.assertNotIn(
            lib.display_rect_osc(0, span_x, self.IY, span_w, self.IH,
                                 lib.RECT_DASHED),
            packets)

    def test_a_span_entirely_inside_the_fill_is_all_inverted(self):
        packets = self._packets((0.0, 0.2))
        span_w = int(self.IW * 0.2)
        self.assertIn(
            lib.display_rect_osc(0, self.IX, self.IY, span_w, self.IH,
                                 lib.RECT_INVERT),
            packets)
        # Nothing dashed at all: every pixel of this span stands on fill.
        self.assertNotIn(
            lib.display_rect_osc(0, self.IX, self.IY, span_w, self.IH,
                                 lib.RECT_DASHED),
            packets)
        self.assertEqual(len(packets), 4)   # outline, fill, span, tick

    def test_a_span_entirely_above_the_fill_stays_dashed(self):
        packets = self._packets((0.7, 0.9))
        span_x = self.IX + int(self.IW * 0.7)
        span_w = int(self.IW * 0.2)
        self.assertIn(
            lib.display_rect_osc(0, span_x, self.IY, span_w, self.IH,
                                 lib.RECT_DASHED),
            packets)
        self.assertNotIn(
            lib.display_rect_osc(0, span_x, self.IY, span_w, self.IH,
                                 lib.RECT_INVERT),
            packets)

    def test_an_unmodulated_bar_is_untouched(self):
        self.assertEqual(lib.bar_packets(0, self.X, self.W, "u", self.FRAC),
                         lib.bar_packets(0, self.X, self.W, "u", self.FRAC,
                                         None, None))


class TestSfzParsing(unittest.TestCase):

    KIT = r"""<group>
pitch_keytrack=0

<region> sample=Samples\Roland TR808\808 Kick_short.wav
lokey=36
hikey=36

<region> sample=Samples\Roland TR808\808 Snare_lo1.wav
lokey=40
hikey=40
lovel=70
hivel=127

<region> sample=Samples\Roland TR808\808 Snare_lo2.wav
lokey=40
hikey=40
lovel=0
hivel=69
"""

    def test_one_entry_per_distinct_key(self):
        self.assertEqual([n for n, _ in lib.parse_sfz_notes(self.KIT)], [36, 40])

    def test_name_comes_from_the_sample_filename(self):
        notes = dict(lib.parse_sfz_notes(self.KIT))
        self.assertEqual(notes[36], "808 KICK SHORT")

    def test_velocity_layers_keep_the_first_sample(self):
        notes = dict(lib.parse_sfz_notes(self.KIT))
        self.assertEqual(notes[40], "808 SNARE LO1")

    def test_notes_are_sorted(self):
        text = "<region> sample=a\\Z.wav\nlokey=50\n<region> sample=a\\A.wav\nlokey=30\n"
        self.assertEqual([n for n, _ in lib.parse_sfz_notes(text)], [30, 50])

    def test_region_without_a_key_is_skipped(self):
        text = "<region> sample=a\\NoKey.wav\n<region> sample=a\\Ok.wav\nlokey=42\n"
        self.assertEqual(lib.parse_sfz_notes(text), [(42, "OK")])

    def test_key_is_accepted_as_well_as_lokey(self):
        self.assertEqual(lib.parse_sfz_notes("<region> sample=a\\B.wav\nkey=44\n"),
                         [(44, "B")])

    def test_empty_text_gives_no_notes(self):
        self.assertEqual(lib.parse_sfz_notes(""), [])

    def test_hikey_is_not_confused_with_key(self):
        text = "<region> sample=a\\Drum.wav\nlokey=47\nhikey=48\n"
        self.assertEqual(lib.parse_sfz_notes(text), [(47, "DRUM")])


class TestKitNames(unittest.TestCase):

    def test_known_machines_get_their_familiar_short_names(self):
        self.assertEqual(lib.kit_short_name("Roland TR808"), "808")
        self.assertEqual(lib.kit_short_name("Roland TR909"), "909")
        self.assertEqual(lib.kit_short_name("LINN9000 1"), "LN90")
        self.assertEqual(lib.kit_short_name("SP1200 1"), "1200")

    def test_unknown_names_fall_back_to_initials_and_last_word(self):
        """Verify the mechanical fallback: initials of leading words plus the last word."""
        self.assertEqual(lib.kit_short_name("Tama Tech Star 3"), "TTS3")
        self.assertEqual(lib.kit_short_name("Electro Puff"), "EPUF")
        self.assertEqual(lib.kit_short_name("Retrobox"), "RETR")
        self.assertEqual(lib.kit_short_name("SCI Tom"), "STOM")

    def test_result_is_never_longer_than_four_characters(self):
        for name in ["Acetone Rhythm Ace", "Tama Tech Star 3", "DYNOSAUR-808",
                     "Fricke MSB512", "Electro Puff", "Boss DR220", "E Ave"]:
            self.assertLessEqual(len(lib.kit_short_name(name)), 4, name)

    def test_empty_name_gives_a_dash(self):
        self.assertEqual(lib.kit_short_name(""), "-")


class TestNearestNote(unittest.TestCase):

    def test_exact_match_is_kept(self):
        self.assertEqual(lib.nearest_note([36, 38, 42], 38), 38)

    def test_missing_note_lands_on_the_closest(self):
        self.assertEqual(lib.nearest_note([36, 38, 42], 39), 38)

    def test_ties_go_to_the_lower_note(self):
        self.assertEqual(lib.nearest_note([36, 40], 38), 36)

    def test_below_the_range_lands_on_the_lowest(self):
        self.assertEqual(lib.nearest_note([36, 40], 20), 36)

    def test_above_the_range_lands_on_the_highest(self):
        self.assertEqual(lib.nearest_note([36, 40], 90), 40)

    def test_empty_kit_gives_none(self):
        self.assertIsNone(lib.nearest_note([], 38))


class TestPageLabelRow(unittest.TestCase):

    def _tabs(self):
        return [("A", "KICK", True, False)] * 4

    def _cols(self):
        # screen_packets takes the short bar kind; the driver's BAR_KINDS maps
        # techno_lib's "uni" onto "u" before it gets here.
        return [("HITS", "0004", "u", 0.25)] * 4

    def test_label_is_drawn_when_given(self):
        packets = lib.screen_packets(0, self._tabs(), self._cols(), "LEVEL 1/3")
        self.assertTrue(any("LEVEL 1/3" in str(p) for p in packets))

    def test_no_label_draws_no_extra_text(self):
        with_label = lib.screen_packets(0, self._tabs(), self._cols(), "X")
        without = lib.screen_packets(0, self._tabs(), self._cols(), "")
        self.assertEqual(len(with_label), len(without) + 1)

    def test_label_defaults_to_empty_so_old_calls_still_work(self):
        packets = lib.screen_packets(0, self._tabs(), self._cols())
        self.assertGreater(len(packets), 0)

    def test_rows_do_not_overlap(self):
        cls = lib
        self.assertLess(cls.TAB_H, cls.RULE_Y)
        self.assertLess(cls.RULE_Y, cls.LABEL_Y)
        self.assertLessEqual(cls.LABEL_Y + 8, cls.NAME_Y)
        self.assertLessEqual(cls.NAME_Y + 8, cls.VALUE_Y)
        self.assertLessEqual(cls.VALUE_Y + 16, cls.BAR_Y)
        self.assertLessEqual(cls.BAR_Y + cls.BAR_H, 64)


class TestQuarterNoteDivision(unittest.TestCase):

    def test_quarter_division_is_appended_last(self):
        # Appended, never inserted: snapshots persist the division as an INDEX
        # into this tuple, so inserting in musical order would silently
        # re-point every saved pattern at a different division.
        self.assertEqual(lib.DIVISIONS[5], ("1/4", 1, 16))

    def test_the_first_five_indices_are_unchanged(self):
        self.assertEqual([d[0] for d in lib.DIVISIONS[:5]],
                         ["1/32", "1/16", "1/8", "1/16T", "1/8T"])

    def test_quarter_division_has_16_steps(self):
        self.assertEqual(lib.step_count(5), 16)

    def test_quarter_division_steps_are_one_beat_each(self):
        # steps_per_beat 1 means one step IS one beat. 16 of them is 4 bars,
        # and it is the slowest step this API can express: steps_per_beat is
        # an integer >= 1.
        self.assertEqual(lib.DIVISIONS[5][1], 1)
        self.assertEqual(lib.DIVISIONS[5][2], 16)


if __name__ == "__main__":
    unittest.main()


class TheScreensDrawTheCurve(unittest.TestCase):
    """2026-09-01. The pads say how fast a modulator moves; the screens now say
    what SHAPE it is. A width-1 filled rect is a vertical line, and the rect
    primitive has shipped since the displays did - so this needed no daemon
    change at all, which is what took it from M to S."""

    def test_every_modulator_shape_has_a_glyph(self):
        for shape in ("tri", "ramp", "squ", "s&h"):
            with self.subTest(shape=shape):
                self.assertTrue(lib.glyph_packets(0, 0, shape))

    def test_an_unknown_shape_draws_NOTHING_rather_than_a_lie(self):
        self.assertEqual(lib.glyph_packets(0, 0, "spiral"), [])
        self.assertEqual(lib.glyph_packets(0, 0, None), [])

    def test_a_glyph_stays_inside_its_own_box(self):
        for shape in ("tri", "ramp", "squ", "s&h"):
            for packet in lib.glyph_packets(0, 0, shape):
                # /maschine/display/rect: screen, x, y, w, h, style
                self.assertGreaterEqual(packet.count(b"rect"), 1)

    def test_a_glyph_is_CHEAP_because_the_write_budget_is_the_hazard(self):
        # Six rects a shape, not twenty-four. Every one is a message, and
        # display traffic is the prime suspect for every wedge this
        # controller has had.
        for shape in ("tri", "ramp", "squ", "s&h"):
            with self.subTest(shape=shape):
                self.assertLessEqual(len(lib.glyph_packets(0, 0, shape)), 8)

    def test_the_glyph_is_drawn_where_the_column_asks(self):
        a = lib.glyph_packets(0, 0, "ramp")
        b = lib.glyph_packets(0, 40, "ramp")
        self.assertNotEqual(a, b)
        self.assertEqual(len(a), len(b))

    def test_a_modulated_column_carries_its_glyph_into_the_packets(self):
        plain = lib.screen_packets(0, [], [("CUTOFF", "0064", "u", 0.5)])
        moded = lib.screen_packets(
            0, [], [("CUTOFF~", "0064", "u", 0.5, (0.2, 0.8), None, False,
                     "tri")])
        self.assertGreater(len(moded), len(plain))

    def test_an_UNmodulated_column_draws_no_glyph_at_all(self):
        cols = [("CUTOFF", "0064", "u", 0.5, None, None, False, None)]
        with_none = lib.screen_packets(0, [], cols)
        without = lib.screen_packets(0, [], [("CUTOFF", "0064", "u", 0.5)])
        self.assertEqual(len(with_none), len(without))


class EveryLedNameTheDriverWritesIsOneTheDaemonAccepts(unittest.TestCase):
    """The FREEZE indicator never lit, and nothing said so.

    `LED_FREEZE` was "padmode" from the day FREEZE shipped until 2026-09-01.
    The daemon's `osc_button_to_btn_map` accepts "pad_mode" alone, returns None
    for anything else, and drops the message - so the light was dead, in
    silence, while the published guide told the reader a frozen instrument says
    so three times.

    A comment could not have caught it. This can: it reads the names the driver
    puts on the wire out of the driver's own source, reads the names the daemon
    answers to out of the daemon's own source, and fails on any that is not in
    both. The driver cannot be imported on WSL, so both sides are read as text -
    which is exactly why this belongs here rather than in a hardware gate."""

    ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
    DRIVER = os.path.join(os.path.dirname(__file__), "..",
                          "zynthian_ctrldev_maschine_mk2.py")
    DAEMON = os.path.join(ROOT, "daemon", "src", "main.rs")

    def _daemon_names(self):
        """Every string osc_button_to_btn_map answers to."""

        import re
        src = open(self.DAEMON, encoding="utf-8").read()
        start = src.index("fn osc_button_to_btn_map")
        end = src.index("\n}", start)
        return set(re.findall(r'"([a-z0-9_]+)"\s*=>', src[start:end]))

    def _driver_names(self):
        """Every literal LED name the driver sends, from its own source.

        Two shapes: a bare string constant assigned to an LED_* name, and the
        tuples/dicts of names the render helpers walk. Both are literals in the
        source, which is the point - a name computed at runtime could not be
        checked here and must not exist."""

        import ast
        tree = ast.parse(open(self.DRIVER, encoding="utf-8").read())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                target = node.targets[0]
                label = getattr(target, "id", None) or getattr(target, "attr", "")
                if not (label.startswith("LED_")
                        or label in ("STATIC_LEDS", "MODE_LED_NAMES",
                                     "F_BUTTON_NAMES")):
                    continue
                # A dict's KEYS are the driver's own vocabulary
                # (MODE_LED_NAMES maps "CONTROL" -> "control"); only the
                # values go on the wire.
                sources = (node.value.values if isinstance(node.value, ast.Dict)
                           else [node.value])
                for source in sources:
                    for leaf in ast.walk(source):
                        if isinstance(leaf, ast.Constant) and isinstance(leaf.value, str):
                            names.add(leaf.value)
        return names

    def test_the_daemon_map_is_readable(self):
        found = self._daemon_names()
        self.assertIn("pad_mode", found)
        self.assertIn("select", found)
        self.assertGreater(len(found), 20, found)

    def test_pad_mode_carries_the_underscore(self):
        src = open(self.DRIVER, encoding="utf-8").read()
        self.assertIn('LED_FREEZE = "pad_mode"', src)
        self.assertNotIn('LED_FREEZE = "padmode"', src)

    def test_no_driver_led_name_is_unknown_to_the_daemon(self):
        accepted = self._daemon_names()
        unknown = sorted(n for n in self._driver_names() if n not in accepted)
        self.assertEqual(unknown, [],
                         f"driver writes LED names the daemon drops: {unknown}")


if __name__ == "__main__":
    unittest.main()
