"""What a button MEANS: the driver's own routing, tested off the rig.

THE GAP THIS FILLS. Every defect the owner has found by playing the instrument
has been a routing defect - a pad that edited a pattern under a modifier that
was supposed to be inert, a chord whose release latched an overlay it had just
cancelled, a press swallowed by a filter above the handler that wanted it. None
of it was testable, because the position was that the driver could not be
imported; twelve AST guards read its source as text instead. `rig_stub` shows
the premise was wrong, and this is what that buys: the dispatcher exercised
event by event, in the order a hand produces them.

WHAT IS ASSERTED, AND WHAT IS NOT. These tests drive real MIDI bytes into
`midi_event` and check WHICH handler ran. They do not check what the handler
did: libseq is a recorder and the mixer is a dict, so an assertion about a note
or an LED would be an assertion about the fake. The rig gate is still the rig
gate.

NO CC NUMBER IS WRITTEN DOWN HERE. Every one is looked up in
`techno_lib.BUTTONS_*` at run time (`rig_stub.cc_for`), because the CC map is
measured hardware fact, it has moved before, and a test carrying its own copy
of a number is a test that will one day disagree with the instrument and be
believed over it.
"""

import unittest
from unittest.mock import patch

import rig_stub


class DispatchCase(unittest.TestCase):
    """One driver per test, constructed but not started."""

    @classmethod
    def setUpClass(cls):
        cls.mod = rig_stub.load_driver()

    def setUp(self):
        self.d = rig_stub.make_driver()
        self.base = self.mod.GROUP_NOTE_BASE[self.d.group]

    # --- the events, as the daemon sends them ---------------------------

    def press(self, action, down=True):
        cc = rig_stub.cc_for(action, self.mod)
        return self.d.midi_event(bytes([0xB0, cc, 127 if down else 0]))

    def tap(self, action):
        """A tap latches. Both edges, one after the other."""
        self.press(action, True)
        return self.press(action, False)

    def pad(self, step, velocity=100):
        """A pad NoteOn for a STEP of the selected channel.

        note = base + step, because that is how `_midi_event` decodes it.
        PAD_OFFSETS is the other direction - step to physical pad - and is for
        lighting the LED, not for addressing the note.
        """
        return self.d.midi_event(bytes([0x90, self.base + step, velocity]))

    def cc(self, number, value):
        return self.d.midi_event(bytes([0xB0, number, value]))


class APadFindsItsOwner(DispatchCase):
    def test_a_bare_pad_in_step_mode_edits_the_step(self):
        with patch.object(self.d, "_toggle_step") as toggle:
            self.assertTrue(self.pad(0))
        self.assertEqual(toggle.call_args[0][0], 0)

    def test_a_pad_that_decodes_out_of_range_is_refused_not_guessed(self):
        # The Group-rebase desync: the daemon re-bases the pads on every Group
        # press and the driver's idea of the base drifts. This is the one
        # failure that used to be entirely silent, so it must stay explicit.
        with patch.object(self.d, "_toggle_step") as toggle:
            self.assertFalse(self.d.midi_event(bytes([0x90, self.base + 40, 100])))
        toggle.assert_not_called()

    def test_shift_takes_the_pads_from_the_step_editor(self):
        # SHIFT + pad sets a step's probability. If it ever fell through to the
        # step editor it would silently edit the pattern instead.
        self.press("shift")
        with patch.object(self.d, "_shift_pad") as shift_pad, \
             patch.object(self.d, "_toggle_step") as toggle:
            self.pad(3)
        self.assertEqual(shift_pad.call_args[0][0], 3)
        toggle.assert_not_called()

    def test_mod_takes_the_pads_from_the_step_editor(self):
        self.press("mod")
        with patch.object(self.d, "_mod_pad") as mod_pad, \
             patch.object(self.d, "_toggle_step") as toggle:
            self.pad(5)
        self.assertEqual(mod_pad.call_args[0][0], 5)
        toggle.assert_not_called()

    def test_shift_outranks_mod(self):
        # OVERLAY_PRIORITY's order, and the reason is in the driver: MOD
        # LATCHES, so a momentary gesture takes the pads from a latched state
        # and hands them back on release.
        self.press("mod")
        self.press("shift")
        with patch.object(self.d, "_shift_pad") as shift_pad, \
             patch.object(self.d, "_mod_pad") as mod_pad:
            self.pad(1)
        self.assertEqual(shift_pad.call_count, 1)
        mod_pad.assert_not_called()

    def test_arm_alone_takes_the_pads(self):
        self.press("arm")
        with patch.object(self.d, "_arm_pad") as arm_pad, \
             patch.object(self.d, "_toggle_step") as toggle:
            self.pad(2)
        self.assertEqual(arm_pad.call_args[0][0], 2)
        toggle.assert_not_called()

    def test_mod_latched_plus_arm_held_stays_on_mod(self):
        # THE ONE EXCEPTION to OVERLAY_PRIORITY, and it is deliberate: MOD+ARM
        # is how a modulator is made one-shot, so the pads must go on showing
        # the rate and shape legend being read. Sending them to ARM's macro
        # picker would take the menu away at the moment it is being used.
        self.tap("mod")
        self.press("arm")
        self.assertEqual(self.d._pad_owner(), "mod")
        with patch.object(self.d, "_mod_pad") as mod_pad, \
             patch.object(self.d, "_arm_pad") as arm_pad:
            self.pad(2)
        self.assertEqual(mod_pad.call_count, 1)
        arm_pad.assert_not_called()

    def test_a_navigate_pad_is_inert(self):
        # AN OVERLAY TAKES THE PADS WHOLE. NAVIGATE paints the phrase over the
        # sixteen pads; a press used to fall through and edit the step it was
        # drawn over. It is a page to READ.
        self.press("navigate")
        with patch.object(self.d, "_toggle_step") as toggle, \
             patch.object(self.d, "_pad_down") as pad_down:
            self.assertTrue(self.pad(11))
        toggle.assert_not_called()
        pad_down.assert_not_called()

    def test_erase_and_a_pad_erases_the_step(self):
        self.press("erase")
        with patch.object(self.d, "_erase_step") as erase, \
             patch.object(self.d, "_toggle_step") as toggle:
            self.pad(7)
        self.assertEqual(erase.call_args[0][0], 7)
        toggle.assert_not_called()


class AModifierTapLatchesAndAHoldIsMomentary(DispatchCase):
    def test_a_tap_latches(self):
        self.tap("mod")
        self.assertTrue(self.d.mod_down, "a tap must leave the modifier on")

    def test_a_second_tap_is_the_way_out(self):
        self.tap("mod")
        self.tap("mod")
        self.assertFalse(self.d.mod_down)

    def test_a_hold_is_momentary(self):
        self.press("mod", True)
        self.assertTrue(self.d.mod_down)
        # Held past the threshold, then released: the latch must not stick.
        self.d.latches["mod"]._at -= 1.0
        self.press("mod", False)
        self.assertFalse(self.d.mod_down)


class AChordIsSwallowedWhole(DispatchCase):
    def test_erase_plus_arm_cancels_everything_pending(self):
        self.press("erase")
        with patch.object(self.d, "_cancel_all_pending") as cancel:
            self.press("arm", True)
        cancel.assert_called_once()

    def test_the_release_of_a_swallowed_press_is_swallowed_too(self):
        # Without this the chord ate the press and the release still reached
        # latch.edge(), which measured it against the timestamp of some
        # EARLIER, unrelated press - and if that was under the threshold, it
        # FLIPPED the latch. A panic gesture that occasionally leaves an
        # overlay latched behind it is worse than no panic gesture.
        #
        # The setup is what makes this reproducible rather than incidental: two
        # quick taps leave ARM unlatched with a RECENT timestamp, which is the
        # state that turns a stray release into a latch.
        self.tap("arm")
        self.assertTrue(self.d.arm_down, "a tap latches")
        self.tap("arm")
        self.assertFalse(self.d.arm_down, "a second tap is the way out")
        self.press("erase")
        with patch.object(self.d, "_cancel_all_pending") as cancel:
            self.press("arm", True)
        cancel.assert_called_once()
        self.press("arm", False)
        self.assertFalse(self.d.arm_down,
                         "the cancel gesture must not leave ARM latched")

    def test_mod_plus_erase_plus_all_drops_every_modulator(self):
        self.press("mod")
        self.press("erase")
        with patch.object(self.d, "_mod_clear_all") as clear, \
             patch.object(self.d, "_set_mode") as set_mode:
            self.press("lens", True)
        clear.assert_called_once()
        # AND it must not also change mode: the chord used to fall through to
        # the mode dispatch that owned the same CC.
        set_mode.assert_not_called()


class ThePressOnlyFilterIsBelowEverythingStateful(DispatchCase):
    def test_a_release_of_an_unbound_cc_is_not_claimed(self):
        free = self.mod.tlib.CCS_MEASURED_AND_UNCLAIMED
        self.assertTrue(free, "the free-CC list is what this test is for")
        for cc in free:
            self.assertFalse(self.cc(cc, 0), f"CC {cc} claimed a release")

    def test_a_stateful_action_still_sees_its_release(self):
        # ERASE is the one modifier that CANNOT latch - law L3, because a
        # latched ERASE is a surface where the next thing you touch disappears.
        # So it is also the clearest proof that the press-only filter sits
        # BELOW the stateful table: without that, the hold could never end.
        self.assertNotIn("erase", self.d.latches)
        self.press("erase", True)
        self.assertTrue(self.d.erase_down)
        self.press("erase", False)
        self.assertFalse(self.d.erase_down)


class TheGroupButtonsAnswerToTheModifierHeld(DispatchCase):
    def group(self, index, value=127):
        return self.cc(self.mod.GROUP_CC_FIRST + index, value)

    def test_a_bare_group_press_selects_it(self):
        self.group(3)
        self.assertEqual(self.d.group, 3)

    def test_erase_and_a_group_silences_that_channel(self):
        with patch.object(self.d, "_silence_channel") as silence:
            self.press("erase")
            self.group(2)
        self.assertEqual(silence.call_args[0][0], 2)
        self.assertEqual(self.d.group, 0, "silencing must not also select")

    def test_arm_and_a_group_nominates_a_survivor(self):
        self.press("arm")
        self.group(5)
        self.assertIn(5, self.d._drop_survivors)
        self.group(5)
        self.assertNotIn(5, self.d._drop_survivors, "a second press takes it back")

    def test_a_group_under_a_modifier_asks_for_the_pad_base_back(self):
        # The daemon re-bases the pads on EVERY Group press, on both edges,
        # whatever the driver does with the button - and the correction has to
        # be sent from the poll thread, so all this edge can do is ask.
        self.press("arm")
        self.d._note_base_due = False
        self.group(1)
        self.assertTrue(self.d._note_base_due)


class HomeIsTheWayBack(DispatchCase):
    def test_home_drops_every_latch_and_lands_on_step_page_one(self):
        self.tap("mod")
        self.tap("navigate")
        self.d._set_mode("CONTROL")
        self.cc(self.mod.CC_BIG_PRESS, 127)
        self.assertEqual(self.d.mode, "STEP")
        self.assertEqual(set(self.d.page_idx.values()), {0},
                         "every ring must be back on its first page")
        self.assertFalse(self.d.mod_down)
        self.assertFalse(self.d.navigate_down)


class TheEncodersReachTheirColumn(DispatchCase):
    def test_an_encoder_cc_is_handled_before_the_press_only_filter(self):
        # Encoders carry a POSITION, so a `down = value == 127` filter above
        # them throws every value away.
        for column, cc in enumerate(self.mod.ENCODER_CCS):
            with patch.object(self.d, "_encoder_column") as enc:
                self.assertTrue(self.cc(cc, 64))
            self.assertEqual(enc.call_args[0][0], column)

    def test_the_big_encoder_is_handled_before_the_press_only_filter(self):
        # CC 15 maxes at 120 and could never satisfy `value == 127`, which is
        # why the knob was inert rather than broken.
        with patch.object(self.d, "_big_encoder") as big:
            self.assertTrue(self.cc(self.mod.CC_BIG_TURN, 64))
        big.assert_called_once()


class PadPressureStoresAndReturns(DispatchCase):
    def voice(self):
        """Select a channel the table calls a voice - F, the first one."""
        for index, channel in enumerate(self.mod.tlib.CHANNELS):
            if channel[2] == "voice":
                self.cc(self.mod.GROUP_CC_FIRST + index, 127)
                return index
        raise AssertionError("no voice channel in the table")

    def test_aftertouch_stores_and_returns(self):
        # THE MIDI THREAD HOLDS THE LOCK FOR THE WHOLE EVENT and the daemon can
        # deliver one of these per held pad every 25 ms, so this handler must
        # store and get out. The poll thread does the writing.
        channel = self.voice()
        with patch.object(self.d, "_pressure_write") as write:
            self.d.midi_event(bytes([0xA0, self.base, 90]))
        write.assert_not_called()
        self.assertEqual(self.d._press_raw[channel], 90)

    def test_aftertouch_on_a_drum_is_ignored(self):
        # A one-shot runs to the end regardless and the drum filter is shelved,
        # so there is no verb for pressure to move.
        self.assertEqual(self.mod.tlib.CHANNELS[self.d.group][2], "drum")
        self.d.midi_event(bytes([0xA0, self.base, 90]))
        self.assertEqual(self.d._press_raw[self.d.group], 0)


if __name__ == "__main__":
    unittest.main()


class TheRigGateOf20260904(DispatchCase):
    """Seven defects the owner found by playing, 2026-09-04.

    Every one of these began with a person saying that something did not sound
    or look right, and none of them was reachable by any test that existed.
    `notes/findings/2026-09-04-combined-gate.md` carries the measurements.
    """

    def test_solo_is_a_latch_like_every_other_modifier(self):
        # ITEM 47. SOLO kept its own attributes and reimplemented the duration
        # rule by hand, so `_act_home` - which iterates self.latches - walked
        # straight past it. The owner pressed HOME with four modifiers latched
        # and reported "now only solo blinking".
        self.assertIn("solo", self.d.latches)

    def test_home_clears_a_latched_solo(self):
        self.tap("solo")
        self.assertTrue(self.d.solo_mode)
        self.d._act_home()
        self.assertFalse(self.d.solo_mode)

    def test_home_clears_every_latch_there_is(self):
        # The general form, so a NINTH modifier added without joining the
        # table turns this red rather than being found at the rig.
        for name in self.d.latches:
            self.tap(name)
        self.d._act_home()
        still = [n for n, l in self.d.latches.items() if l.latched]
        self.assertEqual(still, [])

    def test_a_held_solo_is_not_a_latched_one(self):
        # The LED needs the two apart: held is bright, latched is a 1 Hz blink.
        self.press("solo", True)
        self.assertTrue(self.d.solo_down)
        self.assertFalse(self.d.solo_mode)

    def test_home_keeps_the_big_encoders_anchor(self):
        # ITEM 46. `_act_home` used to clear `_big_last`, and `_big_encoder`
        # returns without acting when it is None - so "press HOME to get
        # un-lost, then turn to find a page" always lost its first detent, on
        # the button whose whole job is to be pressed when you are lost.
        self.cc(15, 64)                      # establish the anchor
        self.assertIsNotNone(self.d._big_last)
        self.d._act_home()
        self.assertIsNotNone(self.d._big_last)
        # The CARRY still goes: a fraction of a detent belongs to the ring the
        # hand has just left.
        self.assertEqual(self.d._big_carry, 0)

    def test_a_dead_column_refusal_is_logged_with_a_reason(self):
        # ITEM 42. The owner reported "group f cutoff is not doing anything"
        # and the driver's own number did not move, because `_column_dead`
        # returned in silence. It still refuses - that is law L4 - but it now
        # says why.
        self.d.group = 5
        self.d.mode = "CONTROL"
        with patch.object(self.d, "_slog") as slog:
            self.cc(17, 70)
            self.cc(17, 80)
        events = [c for c in slog.call_args_list
                  if c[1].get("event") == "dead_column"]
        self.assertTrue(events, "a dead column refused an encoder in silence")
        self.assertIn("reason", events[0][1])
        # ONE line per column, not one per MIDI report: this runs on the MIDI
        # thread and a knob held against a dead column would flood the log.
        self.assertEqual(len(events), 1)

    def test_the_mod_pad_refusal_is_logged_when_nothing_is_bound(self):
        # ITEM 43. After every snapshot load `mod_last` is None, and the pad
        # overlay drew a fully lit sixteen-pad menu that ignored every press.
        self.d.mod_last = None
        with patch.object(self.d, "_slog") as slog:
            self.d._mod_pad(0)
        events = [c for c in slog.call_args_list
                  if c[1].get("event") == "pad_inert"]
        self.assertTrue(events, "MOD + pad refused in silence")
