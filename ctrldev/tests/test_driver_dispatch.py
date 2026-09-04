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


class ABankSwitchSurvivesAKindSwitchedChannel(DispatchCase):
    """`_bank_switch` upgraded a channel against `tlib.CHANNELS[ch][2]` - what
    it was BUILT as - so a channel switched with SHIFT + GRID was rebuilt from
    the wrong kind's defaults, `upgrade_state` dropped `register`, and the
    `_render_all()` at the end of the switch raised `KeyError: 'register'`.

    THE BANK HAS ALREADY MOVED BY THEN. The raise lands on the poll thread,
    whose handler catches and returns, so the switch half-completes and the
    surface never repaints again - a dead panel over music that keeps
    playing."""

    def setUp(self):
        super().setUp()
        zs = self.d.zynseq
        zs.select_bank.side_effect = (
            lambda b, force=False: setattr(zs, "bank", b))

    def test_a_switched_channel_keeps_its_register_across_a_bank(self):
        self.d.kind_override[0] = "voice"
        self.d.state[0] = self.mod.tlib.default_channel_state("voice")
        self.d._bank_switch(3)              # raised KeyError before the fix
        self.assertIn("register", self.d.state[0])
        self.d._bank_switch(1)
        self.assertIn("register", self.d.state[0])

    def test_an_untouched_channel_is_unaffected(self):
        self.d._bank_switch(3)
        self.assertEqual(self.d.channel_kind(0), "drum")
        self.d._bank_switch(1)


class ALoadClearsThePreviousSnapshotsScenes(DispatchCase):
    """`_bank_state` was never cleared anywhere, so loading a second snapshot
    left the FIRST one's registers in the stash - and the next switch to a bank
    that session had visited played music from a file no longer loaded."""

    def setUp(self):
        super().setUp()
        zs = self.d.zynseq
        zs.select_bank.side_effect = (
            lambda b, force=False: setattr(zs, "bank", b))

    def test_the_stash_is_empty_after_a_load(self):
        self.d._bank_switch(3)
        self.assertTrue(self.d._bank_state, "nothing was stashed to clear")
        self.d.set_state({"globals": {}})
        self.assertEqual(self.d._bank_state, {})

    def test_a_bank_visited_before_the_load_comes_back_blank(self):
        # BLANK rather than WRONG. A bank's state is not in the snapshot yet -
        # that is todo item 8 - so the honest answer after a load is defaults.
        self.d.state[0]["lean"] = 2
        self.d._bank_switch(3)
        self.d._bank_switch(1)
        self.assertEqual(self.d.state[0]["lean"], 2)
        self.d.set_state({"globals": {}})
        self.d._bank_switch(3)
        self.assertEqual(self.d.state[0]["lean"], self.mod.tlib.LEAN_OFF)


class TheKeyWalkerHoldsWhenEveryVoiceIsLocked(DispatchCase):
    """ITEM 11. The walker moves ROOT, which is ONE global for all three
    voices; MOVE is a per-channel lock. A global cannot be gated per channel
    without a per-channel root, so the honest rule is the unanimous one."""

    def voices(self):
        return [i for i, ch in enumerate(self.mod.tlib.CHANNELS)
                if ch[2] == "voice"]

    def arm_walk(self):
        self.d.globals["walk"] = 1
        self.d.globals["root"] = 0
        self.d.walk_base = None
        self.d.walk_degree = 0

    def test_it_walks_when_the_voices_are_open(self):
        self.arm_walk()
        for ch in self.voices():
            self.d.state[ch]["move"] = 100
        self.d._walk_tick(bar=1)
        self.assertNotEqual(self.d.walk_degree, 0)

    def test_it_HOLDS_when_every_voice_is_locked(self):
        self.arm_walk()
        for ch in self.voices():
            self.d.state[ch]["move"] = 0
        self.d._walk_tick(bar=1)
        self.assertEqual(self.d.walk_degree, 0)

    def test_one_open_voice_is_enough_to_walk(self):
        # The residue of the scope mismatch, pinned deliberately: a LOCKED
        # channel is not locked against the walker while its neighbours are
        # open, because there is only one root between them.
        self.arm_walk()
        voices = self.voices()
        for ch in voices:
            self.d.state[ch]["move"] = 0
        self.d.state[voices[0]]["move"] = 100
        self.d._walk_tick(bar=1)
        self.assertNotEqual(self.d.walk_degree, 0)

    def test_freeze_still_holds_it(self):
        # The GLOBAL lock was already honoured and must stay so.
        self.arm_walk()
        for ch in self.voices():
            self.d.state[ch]["move"] = 100
        self.d.frozen = True
        self.d._walk_tick(bar=1)
        self.assertEqual(self.d.walk_degree, 0)


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


class TheHitsColumnIsPinnedToWhatTheWriterWrote(DispatchCase):
    """Todo item 9. HITS is euclid's count; the subtractive rhythm register
    thins the line under it and the hand register adds to it, so what sounds
    is a different number - and nothing on the surface said so.

    THIS IS THE TEST THAT STOPS THE TWO DRIFTING. The count the column reads
    is recorded by `_write_pattern` from the pattern it is about to write, and
    every assertion below compares it against the steps the writer actually
    put into the sequencer - `libseq.notes`, counted, not recomputed. A second
    implementation of the composition (lean, lane, fill, both rotations, both
    registers) that agreed with the first until it did not is this project's
    most expensive recurring bug, and a test that recomputed the answer would
    be exactly that bug wearing a green tick.

    The fake sequencer is a recorder, so this asserts nothing about a note
    sounding. It asserts that the number on the glass is the number of
    addNote calls, which is the whole claim."""

    def setUp(self):
        super().setUp()
        self.ch = 0
        self.assertEqual(self.d.channel_kind(self.ch), "drum")
        self.d.group = self.ch
        self.d.mode = "STEP"

    def written(self):
        """How many steps the writer put in the pattern, from the sequencer."""
        return len(self.d.libseq.notes)

    def shown(self):
        """What the HITS column draws, through the real render path."""
        return self.d._page_columns(self.d._page())[0]

    def test_the_recorded_count_is_the_number_of_steps_written(self):
        self.d.hits[self.ch] = 16
        self.d.state[self.ch]["rhythm_reg"] = 0b11111
        self.d.state[self.ch]["hand_reg"] = 0
        self.d._write_pattern(self.ch)
        self.assertEqual(self.d._sounding[self.ch], self.written())

    def test_it_stays_the_number_written_across_every_generator_stage(self):
        # The stages the composition runs through: a lean instead of euclid, a
        # lane pruning it, a rotation carrying both registers with the line.
        # Whatever they do between them, the recorded number is the count of
        # what came out.
        for lean in tuple(self.mod.tlib.LEANS):
            for lane in (0, 40, 80):
                for rot in (0, 3, 7):
                    with self.subTest(lean=lean, lane=lane, rot=rot):
                        self.d.hits[self.ch] = 11
                        self.d.rot[self.ch] = rot
                        self.d.state[self.ch]["lean"] = lean
                        self.d.state[self.ch]["lane"] = lane
                        self.d.state[self.ch]["rhythm_reg"] = 0b1011011101101
                        self.d.state[self.ch]["hand_reg"] = 0b10
                        self.d._write_pattern(self.ch)
                        self.assertEqual(self.d._sounding[self.ch],
                                         self.written())

    def test_the_column_marks_a_line_the_register_thinned(self):
        self.d.hits[self.ch] = 16
        self.d.state[self.ch]["rhythm_reg"] = 0b11111
        self.d.state[self.ch]["hand_reg"] = 0
        self.d._write_pattern(self.ch)
        col = self.shown()
        self.assertEqual(col["name"], "HITS-")
        # The value cell still shows what the knob is set to. One detent of
        # HITS clears the register, so a value cell showing the sounding count
        # would jump from 5 to 15 on a single click.
        self.assertEqual(col["value"], "0016")
        self.assertLess(self.written(), self.d.param_get(self.ch, "hits"))

    def test_the_column_marks_a_line_the_hand_register_added_to(self):
        self.d.hits[self.ch] = 4
        self.d.state[self.ch]["rhythm_reg"] = 0xFFFF
        self.d.state[self.ch]["hand_reg"] = 0b1010
        self.d._write_pattern(self.ch)
        self.assertEqual(self.shown()["name"], "HITS+")
        self.assertGreater(self.written(), self.d.param_get(self.ch, "hits"))

    def test_an_unmasked_channel_draws_exactly_what_it_always_did(self):
        # The migration property. Every channel that has never been tapped or
        # evolved is byte for byte the column that shipped before this.
        self.d.hits[self.ch] = 4
        self.d.state[self.ch]["rhythm_reg"] = 0xFFFF
        self.d.state[self.ch]["hand_reg"] = 0
        self.d._write_pattern(self.ch)
        self.assertEqual(self.shown()["name"], "HITS")
        self.assertEqual(self.written(), self.d.param_get(self.ch, "hits"))

    def test_turning_hits_clears_the_mark_because_it_clears_the_register(self):
        # HITS, DIV and LENGTH are the start-again knobs: _reset_rhythm_mask
        # puts every step back. DIV and LENGTH only mark the change PENDING,
        # so the rewrite that would refresh the count does not happen until the
        # wrap - and the mark must not be shown against the new grid meanwhile.
        self.d.hits[self.ch] = 16
        self.d.state[self.ch]["rhythm_reg"] = 0b11111
        self.d._write_pattern(self.ch)
        self.assertEqual(self.shown()["name"], "HITS-")
        self.d._reset_rhythm_mask(self.ch)
        self.assertIsNone(self.d._sounding[self.ch])
        self.assertEqual(self.shown()["name"], "HITS")

    def test_a_fill_bar_does_not_move_the_number(self):
        # THE ONE EXCEPTION, and it is a performance rule. The fill adds steps
        # for one bar of the phrase and takes them away again, so counting it
        # would change a value that reaches _render_display's body change key
        # twice a phrase with nobody touching the panel - and that draw opens
        # with a CLEAR. It is also honest: the fill has its own column, its own
        # amount and the phrase counter, so it is not a gap nobody can see.
        self.d.hits[self.ch] = 4
        self.d.state[self.ch]["rhythm_reg"] = 0xFFFF
        self.d.state[self.ch]["hand_reg"] = 0
        self.d.state[self.ch]["fill"] = 100
        self.d._write_pattern(self.ch)
        standing = self.d._sounding[self.ch]
        self.d._fill_now.add(self.ch)
        self.d._write_pattern(self.ch)
        self.assertGreater(self.written(), standing)     # the fill did land
        self.assertEqual(self.d._sounding[self.ch], standing)
        self.assertEqual(self.shown()["name"], "HITS")

    def test_the_count_is_not_saved_into_the_snapshot(self):
        # It is a fact about the last write, derivable from registers the
        # snapshot already carries. A saved key nothing reads back is one of
        # the things an AST guard exists to catch.
        self.d.hits[self.ch] = 16
        self.d.state[self.ch]["rhythm_reg"] = 0b11111
        self.d._write_pattern(self.ch)
        self.assertNotIn("sounding", self.d.state[self.ch])
        state = self.d.get_state()
        self.assertNotIn("sounding", state["drums"]["0"])
