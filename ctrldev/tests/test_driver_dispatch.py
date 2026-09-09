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
from unittest.mock import MagicMock, patch

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



class TheWetColumnsShowThePluginNotTheStaleCopy(unittest.TestCase):
    """Todo item 59. LEVEL's defect, on its two neighbours in MIX_PARAMS.

    `state[ch]["reverb"]` starts at 0, the snapshot's driver block does not
    carry it, and nothing reads it back - so a preset with an audible send drew
    0. Worse, `apply()` skips a write whose value already matches, so the first
    detent of REVERB wrote 1 and collapsed the send in one click.

    LEVEL was fixed on 2026-09-02 by reading the mixer strip. These two read
    the plugin."""

    def setUp(self):
        self.driver = rig_stub.make_driver()

    def _set_port(self, procs, which, percent):
        tl = rig_stub.tlib()
        spec = tl.FX_ROLES[procs[which].engine.name]
        for symbol, value in tl.fx_wet_values(spec, percent):
            procs[which].controllers_dict[symbol].value = value

    def test_the_column_reads_the_plugins_own_wet(self):
        procs = rig_stub.fit_insert_pair(self.driver, 0)
        self._set_port(procs, "reverb", 34)
        self.assertEqual(self.driver.state_view(0)["reverb"], 34)

    def test_it_reads_a_non_db_plugin_too(self):
        procs = rig_stub.fit_insert_pair(self.driver, 0,
                                         reverb="Dragonfly Room Reverb")
        self._set_port(procs, "reverb", 20)
        self.assertEqual(self.driver.state_view(0)["reverb"], 20)

    def test_the_delay_column_reads_its_own_plugin(self):
        procs = rig_stub.fit_insert_pair(self.driver, 0)
        self._set_port(procs, "delay", 45)
        self.assertEqual(self.driver.state_view(0)["delay"], 45)

    def test_the_stale_copy_does_not_win(self):
        """The discrimination: the stored value is deliberately set to
        something else, and the plugin must still be what shows."""
        procs = rig_stub.fit_insert_pair(self.driver, 0)
        self.driver.state[0]["reverb"] = 0
        self._set_port(procs, "reverb", 34)
        self.assertEqual(self.driver.state_view(0)["reverb"], 34)

    def test_a_turn_starts_from_the_send_that_is_there(self):
        """THE CONSEQUENCE THAT IS WORSE THAN A WRONG NUMBER. Reading the
        stale 0 made the first detent write 1, so one click took a 34% send to
        almost nothing. `_live_mix` is the one reader the encoder's increment,
        the modulator's base capture and `state_view` all go through."""
        procs = rig_stub.fit_insert_pair(self.driver, 0)
        self.driver.state[0]["reverb"] = 0
        self._set_port(procs, "reverb", 34)
        self.assertEqual(self.driver._live_mix(0, "reverb"), 34)

    def test_turning_the_encoder_starts_from_the_live_send(self):
        """THE WHOLE POINT, DRIVEN THROUGH THE ENCODER RATHER THAN A HELPER.
        Asserting `_live_mix` alone left the increment site untested: a
        mutation that reverted it to the stored copy passed the whole suite.

        NO CC NUMBER IS WRITTEN DOWN - the column comes from the page ring and
        the CC from the driver's own ENCODER_CCS."""
        driver = self.driver
        procs = rig_stub.fit_insert_pair(driver, 0)
        self._set_port(procs, "reverb", 34)
        driver.state[0]["reverb"] = 0           # the stale copy, as loaded

        page = None
        for mode in ("VOLUME", "CONTROL", "STEP", "AUTO"):
            driver.mode = mode
            verbs = driver._page()["verbs"]
            if "reverb" in verbs:
                page = verbs
                break
        self.assertIsNotNone(page, "no page carries the REVERB column")
        mod = rig_stub.load_driver()
        enc = mod.ENCODER_CCS[page.index("reverb")]

        for value in range(64, 80, 4):
            driver.midi_event(bytes([0xB0, enc, value]))

        # One detent up from 34 is 35 and change. What it must NOT be is 1,
        # which is what incrementing the stale 0 produced.
        self.assertGreater(driver._live_mix(0, "reverb"), 30)

    def test_a_channel_with_no_insert_falls_back_to_the_stored_value(self):
        """No chain, no ports, no crash - and no confident wrong number
        either: what is drawn is the only thing there is."""
        self.driver.state[0]["reverb"] = 7
        self.assertEqual(self.driver.state_view(0)["reverb"], 7)



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

    def test_a_kind_switch_does_not_survive_a_snapshot_load(self):
        """ITEM 69. A channel switched by hand stayed switched across every
        snapshot load, silently and for ever.

        `set_state` only SETS the channels present in the saved dict and never
        clears the ones absent from it - while the save side's own comment says
        the opposite: *"Only channels that were actually switched appear - an
        absent entry means 'ask the chain'."* The two halves disagreed, and the
        load half won.

        Every shipped pack preset stores `kinds: {}`, so **no preset could ever
        put a switched channel back.** Found at the rig 2026-09-06: the owner
        loaded `031-house-classic` fresh and reported *"preset 31 group is
        already knid swithed - grid is blinking"*."""

        self.d.kind_override[0] = "voice"
        self.d.set_state({"globals": {}})
        self.assertIsNone(self.d.kind_override[0],
                          "an absent entry means 'ask the chain', so the load "
                          "must clear an override the snapshot does not carry")

    def test_a_kind_the_snapshot_DOES_carry_is_restored(self):
        """And the clear must not throw away what was saved - the round trip is
        what makes a switched channel survive being saved on purpose."""

        self.d.kind_override[0] = None
        self.d.set_state({"globals": {}, "kinds": {"0": "voice"}})
        self.assertEqual(self.d.kind_override[0], "voice")

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


class ADrumTakesAmberSurvivesWhatCannotReconstructIt(DispatchCase):
    """ITEM 35, decided 2026-09-04: PERSIST, because nothing can derive it.

    Amber is the surface's one signal for "this hit is yours, and handing the
    channel back destroys it". On a VOICE it is derived - a keyboard pitch is
    not a Turing pitch, so `_rebuild_notes` finds the take by probing. On a
    DRUM it cannot be, ever: `claim_clears` is False there deliberately, so an
    overdub sits AMONG the euclid hits at the same pitch, and the probe's
    candidate note is the only note the channel plays.

    THE ITEM SAID THE COLOUR DID NOT SURVIVE A RELOAD. It did not survive
    anything: the drum branch of `_rebuild_notes` returned `{}` for every
    channel it was ever called on, and `_take_tap` queues a rebuild - so one
    pad tap took the amber off a REC take in the same session, with the notes
    still sounding. These tests pin both halves.
    """

    ch = 0

    def setUp(self):
        super().setUp()
        self.libseq = self.d.libseq
        self.libseq.getSteps = lambda: 16
        self.note = self.d._group_note(self.ch)
        self.d.owner[self.ch] = "player"

    def sound(self, *steps):
        for step in steps:
            self.libseq.notes[step] = [(self.note, 100)]

    def test_the_kind_this_is_for_is_a_drum(self):
        # If a future change makes channel 0 a voice, every assertion below
        # would pass by testing the derivable half instead.
        self.assertEqual(self.d.channel_kind(self.ch), "drum")

    def test_a_rebuild_keeps_a_take_it_cannot_reconstruct(self):
        self.sound(3, 7)
        self.d.notes[self.ch] = {3: (self.note, 100, 1.0)}
        self.d._rebuild_notes(self.ch)
        self.assertEqual(sorted(self.d.notes[self.ch]), [3],
                         "the rebuild deleted a take it had no way to rebuild")

    def test_a_remembered_step_that_no_longer_sounds_is_dropped(self):
        # THE VALIDATION, and its exact reach: it proves a step still SOUNDS,
        # never who wrote it. Amber over silence is a lie the pads cannot
        # explain, so liveness is the one thing worth checking.
        self.sound(3)
        self.d.notes[self.ch] = {3: (self.note, 100, 1.0),
                                 9: (self.note, 100, 1.0)}
        self.d._rebuild_notes(self.ch)
        self.assertEqual(sorted(self.d.notes[self.ch]), [3])

    def test_a_step_past_the_end_of_the_pattern_is_dropped(self):
        self.sound(3)
        self.d.notes[self.ch] = {3: (self.note, 100, 1.0)}
        self.d._played_seed[self.ch] = {3, 99}
        self.d._rebuild_notes(self.ch)
        self.assertEqual(sorted(self.d.notes[self.ch]), [3])

    def test_the_velocity_is_read_back_and_not_carried(self):
        # The half zynseq DOES own. Remembering the note would be the
        # CHANCE/SWING mistake in a new place; remembering only the step and
        # re-reading the rest is what keeps one truth.
        self.libseq.notes[3] = [(self.note, 42)]
        self.d.notes[self.ch] = {3: (self.note, 100, 1.0)}
        self.d._rebuild_notes(self.ch)
        self.assertEqual(self.d.notes[self.ch][3][1], 42)

    def restore(self, state):
        """A second driver, loaded from `state`, with the pattern put back
        AFTER the load.

        `rig_stub`'s libseq is one shared note store for all eight patterns -
        `selectPattern` is a recorder - so `set_state` rewriting the seven
        generator-owned channels overwrites whatever channel 0 was holding.
        Seeding afterwards is the fake's constraint, not the driver's."""

        fresh = rig_stub.make_driver()
        fresh.libseq.getSteps = lambda: 16
        fresh.set_state(state)
        fresh.libseq.notes.clear()
        for step in (3, 11):
            fresh.libseq.notes[step] = [(fresh._group_note(self.ch), 100)]
        fresh._rebuild_notes(self.ch)
        return fresh

    def test_a_take_survives_the_snapshot_it_is_saved_into(self):
        self.sound(3, 11)
        self.d.notes[self.ch] = {3: (self.note, 100, 1.0),
                                 11: (self.note, 100, 1.0)}
        state = self.d.get_state()
        self.assertEqual(state["played"][str(self.ch)], [3, 11])

        fresh = self.restore(state)
        self.assertEqual(sorted(fresh.notes[self.ch]), [3, 11])
        self.assertEqual(fresh.owner[self.ch], "player")

    def test_a_snapshot_written_before_the_key_restores_no_amber(self):
        # ABSENT IS NOT EMPTY, and here the two happen to look the same on the
        # pads - which is the point. An old snapshot recorded that a channel
        # was the player's and never recorded which of its steps were, so the
        # honest answer is to claim nothing rather than to claim all of it.
        self.sound(3, 11)
        self.d.notes[self.ch] = {3: (self.note, 100, 1.0)}
        state = self.d.get_state()
        state.pop("played")
        self.assertEqual(self.restore(state).notes[self.ch], {})

    def test_a_hand_edited_played_list_cannot_reach_the_pattern(self):
        # These indices come out of a file a hand can edit and end up indexing
        # a pattern. Same class as every other set_state validation.
        self.d.set_state({"played": {"0": [3, "x", None, 4.5, True, -1],
                                     "not a channel": [1]}})
        self.libseq.notes.clear()
        self.sound(3)
        self.d._rebuild_notes(self.ch)
        self.assertEqual(sorted(self.d.notes[self.ch]), [3])

    def test_a_handback_still_takes_the_colour_with_the_take(self):
        # _handback clears the map, and the rebuild must not put it back.
        self.sound(3)
        self.d.notes[self.ch] = {3: (self.note, 100, 1.0)}
        self.d._handback(self.ch)
        self.d._rebuild_notes(self.ch)
        self.assertEqual(self.d.notes[self.ch], {})

    def test_a_voice_still_derives_and_ignores_the_seed(self):
        # The seed exists for the branch that cannot probe. A voice can, so a
        # stale or wrong seed must not survive its rebuild.
        ch = 5
        self.assertEqual(self.d.channel_kind(ch), "voice")
        self.d._played_seed[ch] = {0, 1, 2, 3}
        self.d._rebuild_notes(ch)
        self.assertEqual(self.d.notes[ch], {})


class ATakeTapMovesTheColourWithTheNote(DispatchCase):
    """The other half of item 35. `_take_tap` writes the pattern and queues a
    rebuild, and on a drum that rebuild can only keep what the map already
    says - so the tap has to say it."""

    ch = 0

    def setUp(self):
        super().setUp()
        self.libseq = self.d.libseq
        self.libseq.getSteps = lambda: 16
        self.note = self.d._group_note(self.ch)
        self.d.owner[self.ch] = "player"

    def test_a_tap_that_adds_a_step_makes_it_amber(self):
        self.d._take_tap(4, velocity=100)
        self.assertIn(4, self.d.notes[self.ch])
        self.d._rebuild_notes(self.ch)
        self.assertIn(4, self.d.notes[self.ch],
                      "the tap's own step lost its colour on the next rebuild")

    def test_a_tap_that_removes_a_step_takes_its_colour_too(self):
        self.libseq.notes[4] = [(self.note, 100)]
        self.d.notes[self.ch] = {4: (self.note, 100, 1.0)}
        self.d._take_tap(4)
        self.assertNotIn(4, self.d.notes[self.ch])

    def test_the_tap_records_the_velocity_it_wrote(self):
        self.d._take_tap(4, velocity=63)
        self.assertEqual(self.d.notes[self.ch][4][1], 63)


class BankScenesCase(DispatchCase):
    """Item 8: what a bank remembers, and what a snapshot carries.

    THE MEASURED DEFECTS these pin, from
    `notes/findings/2026-09-04-banks-as-scenes-loses-five-things.md`:

    (a) `hits`, `rot` and `owner` live in the per-group arrays rather than in
        `self.state`, so the stash never saw them - they LEAKED into the
        incoming bank and were LOST from the outgoing one. Measured before the
        fix: bank 1 rotated 5, bank 3 rotated 1, back to bank 1 read 1.
    (d) the snapshot carried no bank state at all.
    (e) `zynseq.load()` ends with `select_bank(1, True)`, so a set saved on
        bank 3 came back as bank 1's patterns under bank 3's registers.

    These assert the driver's own bookkeeping, not the sequencer's - libseq is
    a recorder here. What a bank SOUNDS like is still the rig's question.
    """

    def test_switch_keeps_rotate_per_bank(self):
        """The exact leak that was measured, in the order it was measured."""

        self.d.rot[0] = 5
        self.d._bank_switch(3)
        self.assertEqual(self.d.rot[0], 0,
                         "a never-visited bank must be blank, not a copy")
        self.d.rot[0] = 1
        self.d._bank_switch(1)
        self.assertEqual(self.d.rot[0], 5, "bank 1's rotation came back wrong")
        self.d._bank_switch(3)
        self.assertEqual(self.d.rot[0], 1, "bank 3's rotation came back wrong")

    def test_switch_keeps_hits_per_bank(self):
        """HITS matters more than ROTATE: `_recount_hits` REFUSES to read it
        back off a thinned pattern, so the stash is the only copy."""

        self.d.hits[2] = 11
        self.d._bank_switch(4)
        self.assertEqual(self.d.hits[2], 0)
        self.d.hits[2] = 3
        self.d._bank_switch(1)
        self.assertEqual(self.d.hits[2], 11)

    def test_switch_keeps_ownership_per_bank(self):
        self.d.owner[5] = self.mod.tlib.OWNER_PLAYER
        self.d._bank_switch(2)
        self.assertEqual(self.d.owner[5], "gen",
                         "a fresh bank has patterns nobody recorded on")
        self.d._bank_switch(1)
        self.assertEqual(self.d.owner[5], self.mod.tlib.OWNER_PLAYER)

    def test_capture_is_verb_agnostic(self):
        """A verb added tomorrow is bank-scoped for free - the capture takes
        the state dict wholesale rather than a field list, which is the thing
        every field list in this file has had to be taught."""

        self.d.state[0]["a_verb_invented_by_this_test"] = 42
        got = self.d._bank_capture()
        self.assertEqual(
            got["channels"][0]["a_verb_invented_by_this_test"], 42)

    def test_capture_survives_a_json_round_trip(self):
        """`_stash_out` runs at CAPTURE time, so no set or deque can reach the
        file. A `pending` set in the state would raise on json.dumps."""

        import json
        self.d.state[0]["pending"] = {1, 2, 3}
        got = self.d._bank_capture()
        json.dumps(got["channels"][0])          # must not raise
        self.assertNotIn("pending", got["channels"][0])

    # --- the snapshot -----------------------------------------------------

    def test_banks_round_trip_through_a_snapshot(self):
        self.d.rot[1] = 7
        self.d.hits[1] = 9
        self.d._bank_switch(3)
        saved = self.d.get_state()
        self.assertIn("banks", saved)
        self.assertIn("1", saved["banks"], "keys are strings in the file")

        fresh = rig_stub.make_driver()
        fresh.set_state(saved)
        self.assertIn(1, fresh._bank_state, "keys are ints in the stash")
        self.assertEqual(fresh._bank_state[1]["rot"][1], 7)
        self.assertEqual(fresh._bank_state[1]["hits"][1], 9)

    def test_the_live_bank_is_not_in_banks(self):
        """The live bank is described by the FLAT blocks. Writing it into
        `banks` as well would be two truths, and the one in `banks` would be
        the stale copy."""

        saved = self.d.get_state()
        self.assertNotIn(str(self.d.bank), saved.get("banks", {}))

    def test_absent_banks_restores_none(self):
        """ABSENT MEANS "THERE WAS NOTHING". Every pre-`banks` snapshot has one
        zynseq bank block and its flat blocks ARE that bank, so every other
        bank in such a file genuinely is blank."""

        self.d._bank_switch(3)                  # put something in the stash
        self.assertTrue(self.d._bank_state)
        self.d.set_state({})
        self.assertEqual(self.d._bank_state, {})

    def test_a_load_replaces_the_outgoing_scenes(self):
        """Defect (c), which shipped separately - kept here because `banks`
        must not quietly reintroduce it by MERGING instead of replacing."""

        self.d._bank_switch(3)
        self.d.set_state({"banks": {"7": {"channels": {}, "hits": [],
                                          "rot": [], "owners": {}}}})
        self.assertEqual(set(self.d._bank_state), {7},
                         "bank 1 came from a file that is no longer loaded")

    def test_malformed_bank_entries_are_dropped_not_half_built(self):
        """A raise here takes the whole snapshot load with it."""

        got = self.d._banks_in({
            "notanumber": {"channels": {}},
            "2": "not a dict",
            "3": {"channels": {"x": {}, "1": "not a dict", "2": {"hits": 1}}},
            "4": {"owners": {"0": "nonsense", "1": "player"}},
        })
        self.assertNotIn("notanumber", got)
        self.assertNotIn(2, got)
        self.assertEqual(set(got[3]["channels"]), {2})
        self.assertEqual(got[4]["owners"], {1: "player"})

    def test_banks_in_refuses_a_non_dict(self):
        self.assertEqual(self.d._banks_in(None), {})
        self.assertEqual(self.d._banks_in([1, 2, 3]), {})

    def test_a_truncated_legacy_list_lands_on_the_blank_value(self):
        """These lists can arrive from a hand-edited file. A raise lands on the
        poll thread, whose handler catches - and the surface then stops
        repainting, which is this instrument's worst failure shape."""

        self.d._bank_state[3] = {"channels": {}, "hits": [1], "rot": ["x"],
                                 "owners": {}}
        self.d._bank_switch(3)
        self.assertEqual(self.d.hits[0], 1)
        self.assertEqual(self.d.hits[7], 0, "past the end of a short list")
        self.assertEqual(self.d.rot[0], 0, "unparseable, not a raise")

    # --- landing on the saved bank ----------------------------------------

    def test_a_snapshot_lands_on_the_bank_it_was_saved_on(self):
        """Defect (e). `zynseq.load()` always lands on bank 1."""

        self.d.libseq.banks[3] = 8              # bank 3 exists in this file
        self.d.set_state({"bank": 3})
        self.assertEqual(self.d.bank, 1, "set_state must not move it itself")
        self.d._on_snapshot()
        self.assertEqual(self.d.bank, 3)

    def test_landing_does_not_stash_the_live_state_under_bank_one(self):
        """THE SUBTLETY, and the reason this does not go through
        `_bank_switch`. The live state after a load is the SAVED bank's, so a
        switch would file bank 3's registers under bank 1 and then overwrite
        bank 3's own restored record with them."""

        self.d.libseq.banks[3] = 8
        self.d.set_state({"bank": 3})
        self.d.rot[0] = 6                       # bank 3's rotation, restored
        self.d._on_snapshot()
        self.assertEqual(self.d.bank, 3)
        self.assertEqual(self.d.rot[0], 6, "the state was already correct")
        self.assertNotIn(1, self.d._bank_state,
                         "bank 3's registers were filed under bank 1")

    def test_landing_refuses_a_bank_that_does_not_exist(self):
        """`select_bank` AUTHORS a missing bank as somebody else's 4x4 default
        on MIDI channels 0-3, so following a bad number writes that layout
        into the riff."""

        self.d.set_state({"bank": 9})           # not in libseq.banks
        self.d._on_snapshot()
        self.assertEqual(self.d.bank, 1)

    def test_landing_ignores_a_non_integer_bank(self):
        for bad in ("3", 3.5, True, None, [3]):
            self.d.set_state({"bank": bad})
            self.assertIsNone(self.d._saved_bank, f"accepted {bad!r}")

    def test_landing_happens_once(self):
        """`_saved_bank` is consumed. A later `_on_snapshot` - the once-a-
        second drift check calls `_resync_all` the same way - must not drag the
        player back to the bank a previous file was saved on."""

        self.d.libseq.banks[3] = 8
        self.d.set_state({"bank": 3})
        self.d._on_snapshot()
        self.d._bank_switch(1)
        self.assertEqual(self.d.bank, 1)
        self.d._on_snapshot()
        self.assertEqual(self.d.bank, 1, "landed twice off one snapshot")


class RestoredFxGlobalsCase(unittest.TestCase):
    """A restored room has to be written, not only drawn.

    `set_state` puts `revsize`, `revtype` and `dlyfbk` into `self.globals` and
    nothing else touched them, so the GLOBAL page showed a room the instrument
    was not in. Found 2026-09-05 by playing `064-space-cathedral` and
    `079-space-closet` back to back: they hold BIT-IDENTICAL plugin state and
    differ only in these numbers, and the owner said they were not different
    rooms.

    `dlytime` is not asserted here on purpose - `_push_delay_time()` already
    runs on the poll thread every VOLUME_POLL_TICKS, so it was the one of the
    four that always arrived.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = rig_stub.load_driver()

    def setUp(self):
        self.d = rig_stub.make_driver()

    def test_a_restore_marks_the_room_owed(self):
        self.d._fx_globals_due = False
        self.d._on_snapshot()
        self.assertTrue(self.d._fx_globals_due,
                        "a restore left the room as numbers only")

    def test_the_push_writes_every_global_that_has_a_role(self):
        self.d.globals.update(revsize=47, revtype=27, dlyfbk=55)
        seen = []
        with patch.object(type(self.d), "_set_ganged",
                          lambda _s, which, role, value:
                          seen.append((which, role, value))):
            self.d._push_fx_globals()
        self.assertEqual(seen, [("reverb", "REVSIZE", 47),
                                ("reverb", "REVTYPE", 27),
                                ("delay", "DLYFBK", 55)])

    def test_the_cathedral_and_the_closet_push_different_rooms(self):
        """The two snapshots that found this, as the numbers they differ by."""

        rooms = {}
        for name, g in (("cathedral", dict(revsize=47, revtype=27, dlyfbk=55)),
                        ("closet", dict(revsize=20, revtype=0, dlyfbk=15))):
            self.d.globals.update(g)
            seen = []
            with patch.object(type(self.d), "_set_ganged",
                              lambda _s, which, role, value:
                              seen.append((role, value))):
                self.d._push_fx_globals()
            rooms[name] = seen
        self.assertNotEqual(rooms["cathedral"], rooms["closet"])

    def test_a_missing_global_is_skipped_not_written_as_none(self):
        self.d.globals.pop("revtype", None)
        seen = []
        with patch.object(type(self.d), "_set_ganged",
                          lambda _s, which, role, value:
                          seen.append(role)):
            self.d._push_fx_globals()
        self.assertNotIn("REVTYPE", seen)


class TheCutoffKnobOnALiveVoice(DispatchCase):
    """Todo item 42 - "channel F's CUTOFF moves nothing, not even the driver's
    own number", reported at the rig and never reproduced there.

    THE ENTRY SAID THIS WAS ANSWERABLE OFF THE RIG, and it is: the driver
    constructs, so the encoder CC can be driven into `midi_event` and the
    driver's OWN number read back. Four causes had already been eliminated by
    hand (the top clamp, `_enc_delta`'s re-centre, a dead column, and the whole
    downstream half); none of them is re-derived here.

    Nothing below asserts a sound. `set_value` on the fake zctrl records that
    the driver ATTEMPTED a write, which is a different claim from "the filter
    moved" - the rig gate is still the rig gate.

    NO CC NUMBER IS WRITTEN DOWN. The encoder CCs come from the driver's own
    ENCODER_CCS and the column from techno_lib's page ring, so a surface
    reorder moves this test with it rather than leaving it addressing the
    wrong knob and passing.
    """

    def setUp(self):
        super().setUp()
        # F is the first voice in the table. Selected the way a hand selects
        # it, through the Group button, so the driver does whatever a real
        # selection does.
        self.channel = next(i for i, ch in enumerate(self.mod.tlib.CHANNELS)
                            if ch[2] == "voice")
        self.cc(self.mod.GROUP_CC_FIRST + self.channel, 127)
        self.d.mode = "CONTROL"
        self.proc = rig_stub.fit_voice_chain(self.d, self.channel)
        self.zctrl = self.proc.controllers_dict[
            self.mod.tlib.VOICE_SYMBOLS["JV/Obxd"][0]]
        verbs = self.d._page()["verbs"]
        self.column = verbs.index("cutoff")
        self.enc = self.mod.ENCODER_CCS[self.column]
        self.base = self.mod.GROUP_NOTE_BASE[self.d.group]

    def shown(self):
        """The number the CUTOFF column DRAWS - not the stored one.

        The two are different claims and this defect lives in the gap: the
        display reads `state_view`, which substitutes a pressure base over the
        stored value."""
        return self.d.state_view(self.channel)["cutoff"]

    def sweep(self):
        """Two full encoder sweeps, up then down, as the owner reported doing.

        Absolute knob: the second sweep is what defeats `_enc_delta`'s
        re-centre, which is one of the four causes already eliminated."""
        for value in list(range(64, 128, 4)) + list(range(64, 0, -4)):
            self.cc(self.enc, value)

    def test_the_column_is_live_when_the_chain_publishes_the_port(self):
        self.assertFalse(self.d._column_dead(self.column))

    def test_the_number_moves_and_the_write_is_attempted(self):
        # The entry's own question, answered: with a chain that publishes
        # `cutoff`, the driver's own number moves and it tries to write.
        before = self.shown()
        self.sweep()
        self.assertNotEqual(self.shown(), before)
        self.assertTrue(self.zctrl.writes)

    def test_a_pad_release_ends_the_squeeze(self):
        """THE DEFECT. The daemon sends NO zero-pressure message on release -
        `pad_released` in `daemon/src/main.rs` sends a NoteOff and nothing
        else, and `pad_aftertouch` is change-gated so the last value it ever
        sent is non-zero by construction.

        `_pressure_write` decays the offset only while the raw pressure has
        FALLEN below it, so a raw value that never returns to zero pins the
        offset, pins the base, and the restore write never happens. The verb
        is left displaced and the knob is dead for the rest of the session."""

        self.cc(self.enc, 64)                       # anchor the encoder
        self.d.midi_event(bytes([0x90, self.base, 100]))         # pad down
        self.d.midi_event(bytes([0xA0, self.base, 90]))          # squeeze
        self.d._pressure_write()
        self.assertGreater(self.d._press_off[self.channel], 0.0)
        self.d.midi_event(bytes([0x80, self.base, 0]))           # pad up
        for _ in range(50):                         # ~10 s of poll ticks
            self.d._pressure_write()
        self.assertEqual(self.d._press_off[self.channel], 0.0)
        self.assertIsNone(self.d._press_base[self.channel])

    def test_the_knob_still_works_after_a_pad_has_been_played(self):
        """The owner's symptom, in the state that produces it: the column
        draws LIVE with a number, the number does not move, and nothing is
        logged on any of the four refusal paths."""

        self.cc(self.enc, 64)
        self.d.midi_event(bytes([0x90, self.base, 100]))
        self.d.midi_event(bytes([0xA0, self.base, 90]))
        self.d._pressure_write()
        self.d.midi_event(bytes([0x80, self.base, 0]))
        for _ in range(50):
            self.d._pressure_write()
        before = self.shown()
        self.sweep()
        self.d._pressure_write()                    # the poll thread's answer
        self.assertNotEqual(self.shown(), before)

    def test_the_knob_works_DURING_the_release_decay(self):
        """ITEM 62. The owner, at the rig on 2026-09-06: *"after hitting the
        pad hard, it took 1-2 seconds for the encoder to become responsive -
        before it was stuck"*.

        1.2 to 1.5 s is exactly the release decay - `PRESSURE_DECAY = 0.35`
        of the remaining offset per ~200 ms tick, down to `PRESSURE_FLOOR`.
        Six ticks from a full squeeze.

        `_press_base` is captured ONCE, at line 6128 of the driver, and no
        encoder path touches it. So every tick of the decay re-asserts
        `pressure_value(stale_base, off)` over whatever the knob just set,
        and the restore write at the end puts the stale base back - erasing
        the turn completely.

        The sibling test above sweeps only AFTER fifty ticks, which is after
        the decay has finished. That is why the suite was green over this."""

        self.cc(self.enc, 64)
        self.d.midi_event(bytes([0x90, self.base, 100]))         # pad down
        self.d.midi_event(bytes([0xA0, self.base, 90]))          # squeeze
        self.d._pressure_write()
        self.d.midi_event(bytes([0x80, self.base, 0]))           # pad up
        self.d._pressure_write()                    # tick 1 of the decay
        self.assertGreater(self.d._press_off[self.channel], 0.0,
                           "the decay must still be live for this to test it")

        during = self.shown()
        self.sweep()                                # the hand turns CUTOFF
        moved = self.shown()
        self.assertNotEqual(moved, during, "the knob moved the drawn number")

        # ...and the decay must not take it away again.
        for _ in range(50):
            self.d._pressure_write()
        self.assertEqual(self.d._press_off[self.channel], 0.0)
        self.assertEqual(
            self.shown(), moved,
            "the decay restored a base captured before the knob was turned, "
            "so the turn was erased - item 62")

    def test_a_squeeze_on_a_step_mode_pad_ends_too(self):
        """THE HALF THE OBVIOUS FIX MISSES, and it is why the clear sits above
        the early return rather than below it.

        In STEP mode a pad press goes to the step editor, so `self.held` never
        gains an entry and `_pad_up` returns before it reaches the note. The
        finger is on the pad all the same, `_pad_pressure` stores its reading
        whatever the mode is, and `_pressure_write` sweeps CUTOFF from it - so
        the one place a squeeze can be stranded forever is the one place a
        release does the least work.

        Written after a mutation survived: moving the clear two lines down left
        the whole suite green."""

        self.d.mode = "STEP"
        self.d.midi_event(bytes([0x90, self.base, 100]))    # -> _toggle_step
        self.d.midi_event(bytes([0xA0, self.base, 90]))     # squeeze anyway
        self.d._pressure_write()
        self.assertGreater(self.d._press_off[self.channel], 0.0)
        self.assertFalse(self.d.held, "STEP mode holds no note")
        self.d.midi_event(bytes([0x80, self.base, 0]))
        for _ in range(50):
            self.d._pressure_write()
        self.assertEqual(self.d._press_off[self.channel], 0.0)
        self.assertIsNone(self.d._press_base[self.channel])


class ThePageRingDrawsOnlyThePageTheHandStopsOn(DispatchCase):
    """Todo item 41, the half the message-rate fix did not reach.

    The owner, cycling the page ring: *"all screens show, while i cycle"*. The
    coalescing was built correctly and every place the entry looked was right -
    `_step_page` ends in `_display_soon()`, the poll thread suppresses its
    periodic repaint while one is owed, and the LENS branch had already been
    coalesced on 2026-09-04. **The synchronous repaint came in through the
    LEDs**: `_step_page` calls `_render_all()`, `_render_all` ends in
    `_render_pads()`, and `_render_pads` ended in `_render_display()` - which
    drew both screens on the MIDI thread AND cleared `_display_due` on the way
    past, so the coalesce that was armed a line later had nothing left to
    coalesce.

    THE ASSERTION IS A CALL COUNT, NOT A PACKET COUNT. `_render_display` is
    change-keyed, so counting bytes on the wire would measure the cache rather
    than the defect; what has to be pinned is that the walk does not REACH the
    draw once a repaint has been promised.
    """

    def setUp(self):
        super().setUp()
        self.drawn = []
        real = self.d._render_display
        self.d._render_display = lambda: (self.drawn.append(1), real())[1]

    def detents(self, count, first=0):
        """`count` detents of the big encoder, as fast as the loop can run.

        CC 15 is a POSITION - eight units per detent - so the first report only
        establishes the anchor and is sent separately."""

        self.cc(self.mod.CC_BIG_TURN, first)
        self.drawn.clear()
        for n in range(1, count + 1):
            self.cc(self.mod.CC_BIG_TURN,
                    (first + n * self.mod.tlib.BIG_UNITS_PER_DETENT) % 128)

    def test_a_ring_walk_draws_once_not_once_per_detent(self):
        self.detents(8)
        self.assertEqual(
            len(self.drawn), 1,
            "every page the hand passed through was drawn synchronously")

    def test_the_walk_leaves_a_repaint_owed(self):
        """Suppressing the draw is only half of it: the page the hand STOPPED
        on has to still be coming, or the screens would keep the first page of
        the walk until something else happened to repaint them."""

        self.detents(8)
        self.assertTrue(self.d._display_due)

    def test_the_first_detent_still_lands_at_once(self):
        """DL and DR come through the same function. Nothing is owed on the
        first step, so it must not wait for a settle that a single press will
        never end."""

        self.detents(1)
        self.assertEqual(len(self.drawn), 1)

    def test_a_walk_slower_than_the_settle_draws_every_page(self):
        """The suppression is the SETTLE, not a rate limiter. A hand putting
        more than DISPLAY_SETTLE_S between detents is reading each page, and
        each one must be drawn - otherwise the guard would be hiding pages the
        player is actually looking at."""

        self.cc(self.mod.CC_BIG_TURN, 0)
        self.drawn.clear()
        for n in range(1, 4):
            self.cc(self.mod.CC_BIG_TURN,
                    n * self.mod.tlib.BIG_UNITS_PER_DETENT)
            # The hand pauses: expire the hold rather than sleep for it.
            self.d._display_hold_until = 0.0
        self.assertEqual(len(self.drawn), 3)

    def test_the_lens_ring_coalesces_too(self):
        """The lens's arrows step a VERB and the big encoder is inert there,
        so the walk is DL/DR - but it goes through the same `_render_all()`
        and had the same defect behind it."""

        self.press("lens", True)
        self.drawn.clear()
        for _ in range(6):
            self.d._act_page_next()
        self.assertEqual(len(self.drawn), 1)

    def test_a_direct_repaint_is_never_suppressed(self):
        """HOME, a mode press and a snapshot load all repaint directly and
        must land at once whatever is owed - which is why the guard is at the
        one call site that is REACHED rather than inside `_render_display`."""

        self.d._display_soon()
        self.drawn.clear()
        self.d._render_display()
        self.assertEqual(len(self.drawn), 1)


class TheMixerIsHeardRatherThanPolled(DispatchCase):
    """Item 71. zynmixer dispatches on every change - set_level
    (zynthian_engine_audio_mixer.py:206), set_balance (:221), set_mute (:256),
    toggle_mute (:279), set_solo (:334) and the solo clear (:341) - and until
    2026-09-08 this driver re-read it at 5 Hz instead, so a fader moved on the
    touchscreen was up to 200 ms late on the LEDs.

    WHAT THESE DO NOT TEST: that the LEDs are right. The mixer is a dict here.
    They test that the callback EXISTS, that it repaints the two rows the mixer
    owns, that it survives the argument shape register_queued will hand it, and
    that init and end are symmetric - a registration without its unregister
    leaks a handler into a driver that has been unbound.
    """

    def test_the_driver_has_a_mixer_callback(self):
        self.assertTrue(callable(getattr(self.d, "_on_mixer_strip", None)))

    def test_the_callback_repaints_the_rows_the_mixer_owns(self):
        painted = []
        self.d._render_groups = lambda: painted.append("groups")
        self.d._render_mutes = lambda: painted.append("mutes")
        self.d._display_soon = lambda: painted.append("display")
        self.d._on_mixer_strip(0, "level", 0.5)
        self.assertEqual(painted, ["groups", "mutes", "display"])

    def test_it_survives_the_signals_own_argument_shape(self):
        # register_queued forwards whatever the emitter sent; a signature that
        # pinned three positionals would raise on the SIGNAL thread, where the
        # only symptom is a surface that quietly stops following.
        self.d._render_groups = lambda: None
        self.d._render_mutes = lambda: None
        self.d._display_soon = lambda: None
        self.d._on_mixer_strip(chan=3, symbol="mute", value=1)

    def test_the_display_is_coalesced_and_never_drawn_here(self):
        # A touchscreen fader drag emits per pixel. A full both-screen repaint
        # per emission is the 674 msg/s shape that wedged the controller.
        drawn = []
        self.d._render_groups = lambda: None
        self.d._render_mutes = lambda: None
        self.d._render_display = lambda: drawn.append("drawn")
        self.d._on_mixer_strip(0, "level", 0.5)
        self.assertEqual(drawn, [])
        self.assertTrue(self.d._display_due)

    # A SOURCE GUARD NEVER ASSERTS ON THE SOURCE ITSELF. `assertIn` against a
    # 500 KB string prints the whole file on a failure, which buries the one
    # line that says what went wrong. Reduce to a bool first, every time.
    @staticmethod
    def _src():
        with open(rig_stub.DRIVER_PATH, encoding="utf-8") as fh:
            return fh.read()

    def test_init_registers_and_end_unregisters_the_mixer_signal(self):
        """A registration without its unregister leaks a handler into a driver
        that has been unbound, and this driver is unbound and rebound by every
        snapshot load that changes the MIDI device list.

        PARSED, NOT COUNTED. The first version of this guard counted the name
        in the text and failed at 5 != 3 - because the comments in init() and
        above VOLUME_POLL_TICKS both NAME the handler, which is exactly what
        they should do. A guard that forbids explaining itself is a guard that
        will be deleted.
        """

        import ast
        tree = ast.parse(self._src())
        defs, registered, unregistered = 0, [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_on_mixer_strip":
                defs += 1
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "attr", None)
            if called not in ("register_queued", "unregister"):
                continue
            names = [getattr(a, "attr", None) for a in node.args]
            if "_on_mixer_strip" not in names:
                continue
            (registered if called == "register_queued" else unregistered).append(node)
        self.assertEqual(defs, 1, "expected exactly one def _on_mixer_strip")
        self.assertEqual(len(registered), 1, "expected one register_queued")
        self.assertEqual(len(unregistered), 1, "expected one unregister")
        self.assertTrue("S_AUDIO_MIXER" in self._src(),
                        "S_AUDIO_MIXER is not used")

    def test_the_comment_no_longer_says_nothing_signals(self):
        """The comment above VOLUME_POLL_TICKS covered two different facts in
        one sentence - plugin ports do not signal, the mixer does - and that is
        how the mixer came to be polled for a month. Item 71's second bullet."""

        src = self._src()
        self.assertFalse("because nothing\n# signals a zctrl change" in src,
                         "the over-general sentence is still there")
        self.assertTrue("PLUGIN PORTS DO NOT SIGNAL" in src,
                        "the plugin-port half of the fact is not stated")
        self.assertTrue("THE MIXER DOES SIGNAL" in src,
                        "the mixer half of the fact is not stated")


class TheTouchscreenKeymapFollowsTheSurface(DispatchCase):
    """Item 73. setScale (zynseq.h:625) and setTonic (:635) are per-pattern and
    read by nothing but the GUI, so this is display-only and cannot change a
    note - and the driver never wrote either, so the stock pattern editor's
    keymap contradicted the surface's own ROOT and SCALE.

    WHAT THESE CANNOT SEE: whether the tonic row on the touchscreen actually
    moves. libseq is a recorder here. They check that the write HAPPENS, on
    every channel, from every path that changes the key - which is the half
    that has been wrong eight times in this project under the name STORED,
    DRAWN, NEVER WRITTEN.
    """

    def setUp(self):
        super().setUp()
        # What _probe_keymap() decides on the rig. False on an unbound driver,
        # so every write path below would return early - which is correct
        # behaviour and useless as a test.
        self.d.has_keymap = True

    def _wrote(self, name):
        return [c for c in self.d.libseq.calls if c[0] == name]

    def test_pushing_the_keymap_writes_both_on_every_channel(self):
        self.d.libseq.calls.clear()
        self.d._push_keymap()
        self.assertEqual(len(self._wrote("setTonic")), 8)
        self.assertEqual(len(self._wrote("setScale")), 8)

    def test_it_writes_the_mapped_index_and_not_our_own(self):
        # Our PENT is index 5; zynseq's Pentatonic Minor is 9. A pass-through
        # would write 5 and the editor would draw Harmonic Minor.
        self.d.globals["scale"] = [s[0] for s in self.mod.tlib.SCALES].index("PENT")
        self.d.libseq.calls.clear()
        self.d._push_keymap()
        self.assertEqual({c[1][0] for c in self._wrote("setScale")}, {9})

    def test_the_tonic_is_the_root_the_player_dialled(self):
        self.d.globals["root"] = 7
        self.d.libseq.calls.clear()
        self.d._push_keymap()
        self.assertEqual({c[1][0] for c in self._wrote("setTonic")}, {7})

    def test_an_unmapped_scale_writes_no_scale_but_still_writes_the_tonic(self):
        tlib = self.mod.tlib
        original = dict(tlib.ZYNSEQ_SCALE)
        try:
            for key in tlib.ZYNSEQ_SCALE:
                tlib.ZYNSEQ_SCALE[key] = None
            self.d.libseq.calls.clear()
            self.d._push_keymap()
            self.assertEqual(self._wrote("setScale"), [])
            self.assertEqual(len(self._wrote("setTonic")), 8)
        finally:
            tlib.ZYNSEQ_SCALE.clear()
            tlib.ZYNSEQ_SCALE.update(original)

    def test_a_resync_pushes_it(self):
        """A snapshot load and a bank switch both replace the patterns under
        the driver, and both go through _resync_all - so the keymap has to be
        rewritten there or it describes the outgoing bank."""

        self.d.libseq.calls.clear()
        self.d._resync_all()
        self.assertTrue(self._wrote("setTonic"))

    def test_every_path_that_changes_the_key_pushes_it(self):
        """THREE of four broken is this project's commonest shape, so the call
        sites are counted rather than sampled: _resync_all (snapshot, bank
        switch, drift), the bar-synced landing in _voice_wraps, and
        apply_global for the case where there is no voice to wait for."""

        import ast
        with open(rig_stub.DRIVER_PATH, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        callers = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for leaf in ast.walk(node):
                if (isinstance(leaf, ast.Call)
                        and getattr(leaf.func, "attr", None) == "_push_keymap"):
                    callers.add(node.name)
        # _key_taken is where a voice STOPS owing a pending key - the
        # bar-synced landing, reached from _wrap_channel, and since item 76
        # also from _toggle_kind when the last voice ceases to be one. Not
        # _voice_wraps, which only dispatches to _wrap_channel.
        for expected in ("_resync_all", "_key_taken", "apply_global", "init"):
            self.assertIn(expected, callers,
                          f"{expected} does not push the keymap; callers are "
                          f"{sorted(callers)}")


class ABracketThatNothingCanClear(DispatchCase):
    """Item 76. The bracket beside ROOT and SCALE means "dialled, not yet
    sounding": `apply_global` marks the verb pending and builds `_key_dirty`
    from the voices, each of which discards itself at its own wrap, the last
    one clearing the marker. Two shapes have no last voice.

    ALL EIGHT ON DRUM KINDS is a legal instrument, and there is then no wrap
    to land the key on - so the marker was set and nothing could ever clear
    it, describing for the rest of the session a landing that had already
    happened.

    A KIND SWITCH WHILE THE KEY IS IN FLIGHT is the worse half, found while
    settling the first: `_toggle_kind` never touched `_key_dirty`, and
    `_wrap_channel` returns at `if not voice` before the discard - so a voice
    switched to drum between the dial and its own wrap stranded the marker
    AND the keymap push that rides on it, leaving the stock pattern editor in
    the old key with nothing on the surface to say why.

    THE RULE THE BRACKET NOW KEEPS: it is drawn only while some voice has not
    yet taken the key. Where no voice can, the key has already landed
    everywhere it can land and the bracket is never drawn at all.
    """

    def setUp(self):
        super().setUp()
        # What _probe_keymap() decides on the rig. False off it, and every
        # push below would return early.
        self.d.has_keymap = True

    def _wrote(self, name):
        return [c for c in self.d.libseq.calls if c[0] == name]

    def _all_drums(self):
        for channel in range(8):
            self.d.kind_override[channel] = "drum"

    def _switch_to_drum(self, channel):
        """The player's own gesture, SHIFT + GRID, not a poke at the field."""
        self.d.group = channel
        self.d._toggle_kind()
        self.assertEqual(self.d.channel_kind(channel), "drum")

    # --- with voices, nothing changes -----------------------------------

    def test_a_voice_still_gets_the_bracket(self):
        self.d.apply_global("root", 5)
        self.assertEqual(self.d.globals["pending"], {"root"})
        self.assertEqual(self.d._key_dirty, {5, 6, 7})

    def test_scale_gets_it_too(self):
        self.d.apply_global("scale", 3)
        self.assertEqual(self.d.globals["pending"], {"scale"})

    # --- all eight on drums ---------------------------------------------

    def test_no_voice_means_no_bracket(self):
        self._all_drums()
        self.d.apply_global("root", 5)
        self.assertEqual(self.d.globals["pending"], set(),
                         "a bracket nothing can clear is a bracket that "
                         "describes a landing which already happened")

    def test_no_voice_means_no_bracket_for_scale_either(self):
        self._all_drums()
        self.d.apply_global("scale", 3)
        self.assertEqual(self.d.globals["pending"], set())

    def test_no_voice_pushes_the_keymap_at_once(self):
        """The other half of the same rule: the bracket may only go away
        because the key HAS landed. Item 73's immediate push is what makes
        that true, so it is asserted beside it."""

        self._all_drums()
        self.d.libseq.calls.clear()
        self.d.apply_global("root", 5)
        self.assertEqual({c[1][0] for c in self._wrote("setTonic")}, {5})

    # --- a kind switch with the key in flight ---------------------------

    def test_switching_one_of_three_voices_away_keeps_the_bracket(self):
        self.d.apply_global("root", 5)
        self._switch_to_drum(5)
        self.assertEqual(self.d.globals["pending"], {"root"},
                         "two voices still owe the key")
        self.assertEqual(self.d._key_dirty, {6, 7})

    def test_switching_the_last_voice_away_clears_the_bracket(self):
        self.d.apply_global("root", 5)
        for channel in (5, 6, 7):
            self._switch_to_drum(channel)
        self.assertEqual(self.d._key_dirty, set())
        self.assertEqual(self.d.globals["pending"], set())

    def test_switching_the_last_voice_away_pushes_the_keymap(self):
        """The push rides on the LAST voice out of `_key_dirty`, and a
        channel that leaves by changing kind is out of it just as finally as
        one that leaves by wrapping."""

        self.d.apply_global("root", 5)
        self._switch_to_drum(5)
        self._switch_to_drum(6)
        self.d.libseq.calls.clear()
        self._switch_to_drum(7)
        self.assertEqual({c[1][0] for c in self._wrote("setTonic")}, {5})

    def test_a_kind_switch_with_no_key_in_flight_touches_nothing(self):
        """The guard against the opposite defect: `_key_taken` clears the
        globals' whole pending set, so calling it for a channel that owes
        nothing would drop a marker some other verb is waiting on."""

        self.d.globals["pending"].add("scale")
        self.d._key_dirty = set()
        self._switch_to_drum(5)
        self.assertEqual(self.d.globals["pending"], {"scale"})


class SleepStaysAsleep(DispatchCase):
    """Item 74, against the CORRECTED premise. The entry said `sleep_on` and
    `sleep_off` were unimplemented; they are not. The base class's defaults
    call this driver's own `light_off()` and `refresh()`
    (zynthian_ctrldev_base.py:173, :178), both of which exist here.

    The two real faults, neither of which the entry named:

    1. `light_off()` calls `self.leds.clear()`, so on the next poll tick every
       renderer sees a changed value and writes - the panel and both screens
       came back inside 200 ms, which is why a glance at the rig would have
       reported sleep as simply broken.
    2. `light_off()` darkened the pads, the Group buttons, PLAY and the
       screens, and nothing else. The F row, the transport and the mode
       buttons stayed lit through the screensaver.
    """

    def test_sleep_sets_the_flag_and_wake_clears_it(self):
        self.d.sleep_on()
        self.assertTrue(self.d.asleep)
        self.d.sleep_off()
        self.assertFalse(self.d.asleep)

    def test_the_flag_is_set_before_the_panel_is_darkened(self):
        """ORDER, not just presence. light_off() clears the LED cache, so a
        poll tick already in flight between the darkening and the flag would
        repaint the whole panel and both screens - and then stop, leaving a
        surface that is lit, stale and unattended.

        This test exists because the ordering was documented in a comment and
        a mutation that swapped the two lines passed the whole suite. A comment
        cannot fail a build."""

        seen = []
        self.d.light_off = lambda: seen.append(self.d.asleep)
        self.d.sleep_on()
        self.assertEqual(seen, [True],
                         "light_off ran before asleep was set")

    def test_wake_clears_the_flag_before_repainting(self):
        """The mirror image: refresh() paints, and _poll_render and both
        signal handlers refuse to paint while asleep - so a repaint that ran
        before the flag cleared would be a no-op through most of its callees
        and the surface would come back partly drawn."""

        self.d.sleep_on()
        seen = []
        self.d.refresh = lambda: seen.append(self.d.asleep)
        self.d.sleep_off()
        self.assertEqual(seen, [False], "refresh ran while still asleep")

    def test_the_poll_thread_paints_nothing_while_asleep(self):
        self.d.sleep_on()
        painted = []
        for name in ("_render_groups", "_render_mutes", "_render_grid",
                     "_render_pads", "_render_display", "_render_mod"):
            setattr(self.d, name, lambda n=name: painted.append(n))
        self.d._poll_render(tick=0)
        self.assertEqual(painted, [], painted)

    def test_it_paints_again_once_awake(self):
        self.d.sleep_on()
        self.d.sleep_off()
        painted = []
        for name in ("_render_groups", "_render_mutes"):
            setattr(self.d, name, lambda n=name: painted.append(n))
        self.d._poll_render(tick=0)
        self.assertTrue(painted)

    def test_a_mixer_signal_while_asleep_does_not_light_the_panel(self):
        """The signal threads are the other way back onto the panel: item 71's
        mixer callback and the playhead's repaint both fire on an EVENT with no
        tick involved, so gating _poll_render alone would leave two doors."""

        self.d.sleep_on()
        painted = []
        self.d._render_groups = lambda: painted.append("groups")
        self.d._render_mutes = lambda: painted.append("mutes")
        self.d._display_soon = lambda: painted.append("display")
        self.d._on_mixer_strip(0, "level", 0.5)
        self.assertEqual(painted, [])

    def test_a_progress_signal_while_asleep_does_not_light_the_pads(self):
        self.d.sleep_on()
        painted = []
        self.d._render_pads = lambda: painted.append("pads")
        self.d._render_transport = lambda: painted.append("transport")
        self.d._on_progress()
        self.assertEqual(painted, [])

    def test_wake_drops_the_led_cache_so_the_repaint_is_not_swallowed(self):
        """`light_off` cleared it on the way in and the poll thread has been
        silent since, but a wake must not TRUST that: the cache is the thing
        that decides whether a write reaches the wire, and a stale one leaves
        a surface that looks exactly like a driver fault."""

        self.d.sleep_on()
        self.d.leds.changed("mute0", ("x", 1.0))   # something survives sleep
        self.d.sleep_off()
        self.assertTrue(self.d.leds.changed("mute0", ("x", 1.0)),
                        "the wake trusted the LED cache")

    def test_light_off_darkens_every_led_the_driver_can_write(self):
        """There was no single list of them before item 74 - the panel was
        darkened row by row, and three rows were missing. ALL_LED_NAMES is the
        list, and this asserts light_off walks all of it."""

        sent = []
        self.d._send_osc = lambda payload: sent.append(payload)
        self.d.light_off()
        blob = b"".join(p for p in sent if isinstance(p, bytes))
        for name in self.mod.ALL_LED_NAMES:
            self.assertIn(f"/maschine/button/{name}".encode(), blob, name)
        # The two surfaces that are not buttons.
        self.assertIn(b"/maschine/pad", blob)
        self.assertIn(b"/maschine/display/fbclear", blob)

    def test_the_named_rows_that_used_to_be_missed_are_in_the_list(self):
        """Named explicitly as well as walked, because ALL_LED_NAMES being
        complete is the claim - and a test that only walks whatever the tuple
        holds would pass over a tuple with three rows deleted."""

        names = set(self.mod.ALL_LED_NAMES)
        for missed in self.mod.F_BUTTON_NAMES:
            self.assertIn(missed, names, missed)
        for missed in self.mod.MODE_LED_NAMES.values():
            self.assertIn(missed, names, missed)
        for missed in ("page_left", "page_right", "nav_left", "nav_right",
                       "shift", "mute", "navigate", "duplicate",
                       "rec", "grid", "solo", "swing", "stop"):
            self.assertIn(missed, names, missed)


class PlayingThePanelCountsAsBeingAwake(DispatchCase):
    """The half item 74 did not ask for and cannot ship without.

    Zynthian's power save fires after ZYNTHIAN_UI_POWER_SAVE_MINUTES, default
    SIXTY (zynthian_gui_config.py:614), and the idle timer is reset only by
    set_event_flag() - every caller of which is a touchscreen, hardware-encoder
    or CUIA path in zyngui/. NOTHING in the MIDI-in path sets it, and no
    upstream ctrldev driver calls it either.

    So before item 74 the screensaver was invisible on this instrument: it
    fired, and the poll thread relit the panel within 200 ms. Making sleep
    STICK without this would mean an hour of playing the MK2 turns the panel
    off under the player's hands and leaves it off until somebody touches a
    screen that is not required to be connected.

    One call fixes both directions, because power_save_check() clears the mode
    on the same flag it uses to defer it: playing the panel keeps it awake, and
    the first press on a sleeping panel wakes it.
    """

    def test_a_pad_marks_the_instrument_as_in_use(self):
        self.d.state_manager.set_event_flag = MagicMock()
        self.pad(0)
        self.d.state_manager.set_event_flag.assert_called()

    def test_a_button_marks_the_instrument_as_in_use(self):
        self.d.state_manager.set_event_flag = MagicMock()
        self.press("shift", True)
        self.d.state_manager.set_event_flag.assert_called()

    def test_an_encoder_marks_the_instrument_as_in_use(self):
        self.d.state_manager.set_event_flag = MagicMock()
        self.cc(16, 1)
        self.d.state_manager.set_event_flag.assert_called()

    def test_a_state_manager_without_the_method_does_not_raise(self):
        """Older builds may not have it, and a driver that crashes on every
        MIDI event because of a screensaver nicety is worse than a panel that
        sleeps at the wrong time."""

        # `getattr(..., None)` is the guard, so an absent method and a None
        # attribute take the same branch; None is the one a test can produce
        # without deleting a method off the fake's class.
        self.d.state_manager.set_event_flag = None
        self.pad(0)

    def test_a_raising_state_manager_does_not_kill_the_midi_thread(self):
        boom = MagicMock(side_effect=RuntimeError("no"))
        self.d.state_manager.set_event_flag = boom
        self.pad(0)          # must not raise
        boom.assert_called()

    def test_it_is_marked_even_while_asleep(self):
        """This is the wake path. The flag must be set BEFORE the driver's own
        asleep gate is consulted, or the first press on a dark panel would be
        swallowed and the player would press harder."""

        self.d.sleep_on()
        self.d.state_manager.set_event_flag = MagicMock()
        self.pad(0)
        self.d.state_manager.set_event_flag.assert_called()


class HumanReachesTheAudioThread(DispatchCase):
    """The law this is under: STORED, DRAWN, NEVER WRITTEN - eight occurrences
    in this project, and three of four broken is its commonest shape. So every
    path is asserted separately: the dial, the read-back, and the restore.

    setHumanTime / setHumanVelo take a FLOAT 0..1 and the surface reads 0-100,
    so the conversion is asserted too - a verb whose surface number and plugin
    number are different claims is the other law on this list.
    """

    def _args(self, name):
        return [c[1] for c in self.d.libseq.calls if c[0] == name]

    def test_setting_human_writes_it_to_the_pattern(self):
        self.d.libseq.calls.clear()
        self.d.apply(0, "human", 40)
        self.assertTrue(self._args("setHumanTime"), self.d.libseq.calls)

    def test_setting_human_velo_writes_the_other_one(self):
        self.d.libseq.calls.clear()
        self.d.apply(0, "humanvelo", 40)
        self.assertTrue(self._args("setHumanVelo"), self.d.libseq.calls)

    def test_each_verb_is_scaled_by_its_own_measured_ceiling(self):
        """Item 78: they took `value / 100.0` each, and the two values are in
        different units - steps for one, raw velocity for the other. A shared
        conversion made HUMAN four times too strong and HUMNV inert."""

        tlib = self.mod.tlib
        self.d.libseq.calls.clear()
        self.d.apply(0, "human", 50)
        self.assertEqual(self._args("setHumanTime"),
                         [(tlib.human_native(50),)])
        self.assertAlmostEqual(self._args("setHumanTime")[0][0], 0.30, places=6)

        self.d.libseq.calls.clear()
        self.d.apply(0, "humanvelo", 100)
        self.assertEqual(self._args("setHumanVelo"),
                         [(tlib.humanvelo_native(100),)])
        self.assertGreater(self._args("setHumanVelo")[0][0], 10.0)

    def test_zero_still_writes_exactly_zero(self):
        # A ceiling change must not make a pattern that reads 0 humanise.
        self.d.apply(0, "human", 40)
        self.d.libseq.calls.clear()
        self.d.apply(0, "human", 0)
        self.assertEqual(self._args("setHumanTime"), [(0.0,)])

    def test_it_selects_the_channels_own_pattern_first(self):
        """Per pattern via the selection, like everything else in this API. A
        write without the select lands on whichever pattern was last touched."""

        self.d.libseq.calls.clear()
        self.d.apply(3, "human", 20)
        names = [c[0] for c in self.d.libseq.calls]
        self.assertIn("selectPattern", names)
        self.assertLess(names.index("selectPattern"),
                        names.index("setHumanTime"))

    def test_it_is_read_back_through_param_get(self):
        # A VERB WHOSE STORAGE IS NOT self.state MUST BE READ THROUGH
        # param_get - seven occurrences. Every surface agreeing while only the
        # audio is wrong is the dangerous shape.
        self.d.apply(0, "human", 40)
        self.assertEqual(self.d.param_get(0, "human"), 40)
        self.d.apply(0, "humanvelo", 70)
        self.assertEqual(self.d.param_get(0, "humanvelo"), 70)

    def test_a_restore_READS_both_back_rather_than_pushing_them(self):
        """The direction matters and it is the opposite of the usual law here.
        These live in the PATTERN and the pattern is saved into the .zss
        (zynseq.cpp:1267), so after a load the snapshot is the source of truth
        and the surface must follow it - exactly as CHANCE and SWING do.

        Pushing the driver's remembered value would overwrite what the
        snapshot carries, which is the mirror image of STORED, DRAWN, NEVER
        WRITTEN and just as wrong."""

        self.d.libseq.calls.clear()
        self.d._derive_params(0)
        names = [c[0] for c in self.d.libseq.calls]
        self.assertIn("getHumanTime", names)
        self.assertIn("getHumanVelo", names)
        self.assertNotIn("setHumanTime", names)
        self.assertNotIn("setHumanVelo", names)

    def test_every_channel_is_read_back_on_a_resync(self):
        self.d.libseq.calls.clear()
        self.d._resync_all()
        self.assertEqual(len(self._args("getHumanTime")), 8)
        self.assertEqual(len(self._args("getHumanVelo")), 8)

    def test_the_read_back_INVERTS_the_ceiling_rather_than_rescaling(self):
        """The stub answers 0 for every getter, and 0 converts to 0 under any
        scale - so a test that only reads the default cannot see a wrong
        conversion here. A mutation that put `* 100` back passed the whole
        suite until this existed.

        0.30 steps is what the surface's 50 writes, so 50 is what must come
        back. Under the old `* 100` it would read 30 and the column would move
        on every snapshot load."""

        self.d.libseq.getHumanTime = lambda: 0.30
        self.d.libseq.getHumanVelo = lambda: 10.0
        self.d._derive_params(0)
        self.assertEqual(self.d.param_get(0, "human"), 50)
        self.assertEqual(self.d.param_get(0, "humanvelo"), 50)

    def test_the_read_back_lands_in_the_state_the_surface_draws(self):
        self.d.apply(0, "human", 40)
        self.d._derive_params(0)
        # FakeLibseq answers 0 for an unnamed getter, so the restored value is
        # 0 - the point is that the STATE moved to what the pattern said, not
        # that it kept what the driver remembered.
        self.assertEqual(self.d.param_get(0, "human"), 0)


class TheCapturedNoteCarriesItsOffset(DispatchCase):
    """Item 75. A live strike was rounded to the nearest step and written with
    offset 0.0, so the played timing was gone the moment it was stored and
    quantise could never be turned back off. Now the fraction is stored and
    zynseq rounds at PLAYBACK instead, gated per pattern by setQuantizeNotes.

    WHAT THIS CANNOT SEE: where the note sounds. libseq is a recorder. It
    checks that the number handed over is the played one rather than zero, and
    that the flag which makes today's placement identical is actually set.
    """

    STEPS = 16

    def setUp(self):
        super().setUp()
        self.d.has_quantise = True
        self.d.cps[0] = 24                       # 24 clocks per step
        # FakeLibseq's catch-all answers 0 for getSteps, and `_capture` opens
        # with `if steps <= 0: return` - so the live-recording path is
        # unreachable off the rig unless a test says how long the pattern is.
        # Patched here rather than in the stub: giving every test a 16-step
        # pattern breaks two bank-scene tests that rest on the empty shape,
        # and that is a separate piece of work (todo.md 77).
        self.d.libseq.getSteps = lambda: self.STEPS

    def _added(self):
        return [c[1] for c in self.d.libseq.calls if c[0] == "addNote"]

    def test_a_hit_off_the_line_is_not_written_as_if_it_were_on_it(self):
        self.d.libseq.calls.clear()
        self.d._capture(0, note=36, velocity=100, start=52, end=None)
        added = self._added()
        self.assertTrue(added, self.d.libseq.calls)
        self.assertNotEqual(added[-1][-1], 0.0,
                            "the remainder was thrown away again")

    def test_the_offset_written_is_the_one_the_pure_function_derived(self):
        self.d.libseq.calls.clear()
        self.d._capture(0, note=36, velocity=100, start=52, end=None)
        expected = self.mod.tlib.record_offset(52, 24, self.STEPS)
        self.assertAlmostEqual(self._added()[-1][-1], expected, places=6)

    def test_a_dead_on_hit_still_writes_zero(self):
        self.d.libseq.calls.clear()
        self.d._capture(0, note=36, velocity=100, start=48, end=None)
        self.assertEqual(self._added()[-1][-1], 0.0)

    def test_quantise_is_turned_on_for_the_pattern(self):
        """NOT OPTIONAL. With an offset stored and quantise off, the note plays
        where it was PLAYED - which is a different instrument from the one the
        player has today. On, it plays exactly where it does now, and the
        fraction is only there to be given back."""

        self.d.libseq.calls.clear()
        self.d._capture(0, note=36, velocity=100, start=52, end=None)
        names = [c[0] for c in self.d.libseq.calls]
        self.assertIn("setQuantizeNotes", names)
        flags = [c[1] for c in self.d.libseq.calls if c[0] == "setQuantizeNotes"]
        self.assertEqual(flags[-1], (True,), flags)

    def test_the_flag_is_set_before_the_note_is_added(self):
        """Order matters: a note added while the flag is still off would be
        placed by its offset for as long as it took the next write to arrive."""

        self.d.libseq.calls.clear()
        self.d._capture(0, note=36, velocity=100, start=52, end=None)
        names = [c[0] for c in self.d.libseq.calls]
        self.assertLess(names.index("setQuantizeNotes"), names.index("addNote"))

    def test_a_build_without_the_flag_writes_no_offset_either(self):
        """If setQuantizeNotes is unavailable, storing an offset would MOVE
        every recorded note - so the old destructive behaviour is the correct
        fallback, not a degraded one."""

        self.d.has_quantise = False
        self.d.libseq.calls.clear()
        self.d._capture(0, note=36, velocity=100, start=52, end=None)
        self.assertEqual(self._added()[-1][-1], 0.0)
        self.assertNotIn("setQuantizeNotes",
                         [c[0] for c in self.d.libseq.calls])


class APresetListOutlivesItsChain(DispatchCase):
    """Item 80. `_resync_all` says it drops every cache and did not drop
    `preset_cache`, so a voice's preset list - and the emptiness of one -
    survived the snapshot that replaced the chain it was read from.

    THE VISIBLE HALF IS A NAME THAT IS NOT THERE. `state_view` draws the
    PRESET column dead where the cache PROVES the list empty, which is
    correct for a chain with nothing to step through and wrong for the
    chain that replaced it. `_preset_list` caches `[]` for any processor
    whose `load_preset_list()` returns nothing - a chain saved with no
    bank selected, which is what `030-maschine-house` holds on F and G -
    so ONE detent on the preset encoder there marks that column dead for
    the rest of the session, across every later snapshot load, while
    every other knob on the page keeps changing the sound.

    Measured on the rig 2026-09-09, reading the MK2's own displays off
    the wire: on `030` channel F drew `PRESET ----` after the load and
    `preset` - lower case, the dead form - after a single detent.
    """

    def _dead_channel(self):
        """A voice whose cached preset list proves there is nothing to step
        through, as `_preset_list` leaves it for a chain with no bank."""

        channel = next(c for c in range(8) if not self.d._is_sampler(c))
        self.d.preset_cache[channel] = []
        self.assertIsNone(self.d.state_view(channel)["preset"],
                          "the column is meant to draw dead here")
        return channel

    def test_a_resync_drops_it(self):
        channel = self._dead_channel()
        self.d._resync_all()
        self.assertEqual(self.d.preset_cache, {})
        self.assertIsNotNone(self.d.state_view(channel)["preset"])

    def test_a_refresh_drops_it(self):
        """A chain added, removed or moved is the other way the processor
        under a channel changes without a snapshot."""

        channel = self._dead_channel()
        self.d.refresh()
        self.assertEqual(self.d.preset_cache, {})
        self.assertIsNotNone(self.d.state_view(channel)["preset"])

    def test_a_pending_load_does_not_cross_a_snapshot(self):
        """`preset_pending` is an INDEX into the list this cache held. Left
        alone it lands on the new chain's engine a fifth of a second after
        the load, loading whatever sits at the old list's position."""

        self.d.preset_pending = (5, 12, 0.0)
        self.d._resync_all()
        self.assertIsNone(self.d.preset_pending)
