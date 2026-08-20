# -*- coding: utf-8 -*-
# ******************************************************************************
# ZYNTHIAN PROJECT: Techno machine library
#
# Pure functions for the techno machine: the Turing shift register, register to
# pitch quantisation, the channel role table, the FX role maps and the page and
# column model. No Zynthian imports, no I/O, no state - everything here is unit
# tested on WSL with no Pi and no hardware, the same way euclid() and the screen
# layout already are.
#
# ******************************************************************************

import random
import re
from collections import deque


class techno_lib:

    # zynthian_ctrldev_manager globs every *.py in this directory and takes
    # getattr(module, module_name) as a driver class, then reads .dev_ids off
    # it. Without this the whole UI crash-loops on startup. dev_ids is empty,
    # so no device ever matches this class. Same guard as maschine_mk2_lib.
    dev_ids = []

    # ------------------------------------------------------------------ Turing

    @staticmethod
    def mutate(register, length, chance, rng=random.random):
        """Clock the register one full rotation, flipping the fed-back bit with
        probability `chance`.

        A full rotation is the identity at chance 0, which is what makes LOCK
        exact rather than approximate: the line being heard is the line kept,
        bit for bit, for as long as the knob stays down.
        """
        mask = (1 << length) - 1
        reg = register & mask
        for _ in range(length):
            bit = (reg >> (length - 1)) & 1
            if rng() < chance:
                bit ^= 1
            reg = ((reg << 1) | bit) & mask
        return reg

    @staticmethod
    def rotations(register, length, steps):
        """The `steps` values the pattern is built from, read without advancing
        the persistent register."""
        mask = (1 << length) - 1
        reg = register & mask
        out = []
        for _ in range(steps):
            out.append(reg)
            reg = ((reg << 1) | ((reg >> (length - 1)) & 1)) & mask
        return out

    @staticmethod
    def rotate(register, length, count):
        """The register rotated left `count` times. rotations() walks this same
        path but keeps every intermediate value; this returns the endpoint."""
        mask = (1 << length) - 1
        reg = register & mask
        for _ in range(count % length):
            reg = ((reg << 1) | ((reg >> (length - 1)) & 1)) & mask
        return reg

    @staticmethod
    def gate_values(register, length, steps):
        """The density tap: `steps` rotations of the register offset by half
        its length.

        Rhythm and pitch read the same memory at different points, which is
        what the hardware Turing Machine's Pulses expander does. They are not
        independent - they cannot be, or the mask would stop being a function
        of the register and LOCK would no longer freeze the rests - but they
        are offset, so contour and rhythm do not move in lockstep."""
        offset = max(1, length // 2)
        return techno_lib.rotations(
            techno_lib.rotate(register, length, offset), length, steps)

    @staticmethod
    def gate_mask(register, length, steps, density):
        """Which steps sound. `density` is 0.0-1.0, matching mutate()'s chance
        argument; the driver divides its 0-100 surface value exactly as
        setPlayChance already does.

        The N lowest gate values sound, N = round(density * steps), ties broken
        by step index. Rank rather than threshold because the requirement is a
        count: density 1.0 is every step and 0.0 is none, exactly, and lowering
        density can only remove a step - never move one.

        RETAINED FOR MIGRATION ONLY since 2026-08-16. DENSITY is gone from the
        surface and the writer now reads a rhythm register, but rhythm_seed()
        calls this to reproduce a pre-change snapshot's mask exactly. Deleting
        it would silently change how every old snapshot sounds."""
        count = int(round(max(0.0, min(1.0, density)) * steps))
        values = techno_lib.gate_values(register, length, steps)
        order = sorted(range(steps), key=lambda i: (values[i], i))
        chosen = set(order[:count])
        return tuple(i in chosen for i in range(steps))

    # ------------------------------------------------------- rhythm generator
    #
    # A voice has TWO Turing registers: `register` drives pitch, `rhythm_reg`
    # drives which steps sound. One bit per step, and 16 bits covers every
    # division because step_count() is 16 straight, 12 triplet, and never more.
    #
    # This replaces DENSITY, which set how many steps sounded but never WHICH.
    # The need it could not meet: tap steps 1 and 9, then evolve only the notes
    # on them. Rhythm and pitch used to be one register read at two points
    # (gate_values), so mutating for a new melody moved the rhythm with it.
    #
    # gate_values' docstring defended that coupling: "they cannot be [
    # independent], or the mask would stop being a function of the register and
    # LOCK would no longer freeze the rests". THAT DEFENCE SURVIVES. With two
    # registers the mask is still a function of a register - just not the same
    # one. Being register-derived was the requirement; sharing one was not.

    @staticmethod
    def rhythm_mask(rhythm_reg, steps):
        """Which steps sound: bit N of the rhythm register is step N.

        Only the pattern's own bits are read, so a 12-step triplet division
        cannot pick up bits 12-15 left behind by a 16-step one."""

        return tuple(bool(rhythm_reg >> i & 1) for i in range(steps))

    @staticmethod
    def rhythm_toggle(rhythm_reg, step):
        """Flip one step on or off, leaving every other step alone.

        A pad tap in STEP mode lands here instead of writing a note into the
        pattern. That is what makes a hand-chosen rhythm survive: the steps
        become the generator's own state rather than an edit sitting on top of
        it, so nothing wipes them and they persist in the snapshot for free.
        Before this, _toggle_step's own docstring warned that the next encoder
        turn would wipe them."""

        return rhythm_reg ^ (1 << step)

    @staticmethod
    def rhythm_seed(register, length, steps, density):
        """The rhythm register a pre-2026-08-16 snapshot should load with.

        Exact, not approximate: it runs the same gate_mask() on the same
        inputs the old writer used, so a snapshot saved before the rhythm
        generator existed sounds IDENTICAL after it. This is the CHANCE/SWING
        law applied before it bites rather than after - a mirrored value that
        reads back absent is silence, or motion, with nothing explaining it.

        gate_mask() is kept alive for exactly this reason and must not be
        deleted with DENSITY."""

        mask = techno_lib.gate_mask(register, length, steps, density / 100.0)
        return sum(1 << i for i, on in enumerate(mask) if on)

    @staticmethod
    def note_duration(gate, step, steps):
        """A note's length in steps, clamped so it cannot cross the loop point.

        The Pi probe proved libzynseq STORES a duration longer than its
        pattern; it did not prove the player still emits the note-off after
        the loop wraps. Until hardware answers that, a note is not allowed to
        outlive its pattern - a stuck pad drone is the worst failure this
        instrument has.

        The floor of 0.05 is the shipped one: a zero-length note is a note
        that never sounds."""
        duration = gate / 100.0
        remaining = max(1, steps - step)
        return max(0.05, min(duration, float(remaining)))

    @staticmethod
    def record_step(playpos, cps, steps):
        """Which step a live strike belongs to: the nearest grid line, wrapping.

        A strike past the midpoint of the last step lands on step 0 of the next
        pass, and that is not a delay - the loop wraps within one step, so the
        note fires immediately, at the position the player meant."""
        if cps <= 0 or steps <= 0:
            return 0
        return int((playpos + cps // 2) // cps) % steps

    @staticmethod
    def record_duration(held_clocks, cps, step, steps):
        """A played note's length in steps: how long the pad was held, rounded
        to whole steps, never shorter than one and never past the loop point.

        The clamp is SP5's Change 3 (`min(duration, steps - step)`), inherited
        rather than fought: a note that outlives its pattern may hang, and a
        stuck pad drone is the worst failure this instrument has."""
        if cps <= 0:
            return 1.0
        held = int((held_clocks + cps // 2) // cps)
        remaining = max(1, steps - step)
        return float(max(1, min(held, remaining)))

    @staticmethod
    def ring_push(ring, register):
        """`ring` is a collections.deque(maxlen=4) - four wraps of human
        reaction time, which is all the undo the prototype needs."""
        ring.append(register)

    @staticmethod
    def ring_pop(ring):
        return ring.pop() if ring else None

    # ------------------------------------------------------------------- pitch

    BASE_NOTE = 36          # C2 - BASS sits here with OCTAVE at 0

    SCALES = (
        ("MIN",  (0, 2, 3, 5, 7, 8, 10)),
        ("MAJ",  (0, 2, 4, 5, 7, 9, 11)),
        ("DOR",  (0, 2, 3, 5, 7, 9, 10)),
        ("PHR",  (0, 1, 3, 5, 7, 8, 10)),
        ("HMIN", (0, 2, 3, 5, 7, 8, 11)),
        ("PENT", (0, 3, 5, 7, 10)),
    )

    NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

    @staticmethod
    def pitch(value, length, root, scale_idx, octave, range_octaves):
        """Scale the register value across `range_octaves`, quantise it to the
        scale, transpose by root and octave. Returns a MIDI note number."""
        intervals = techno_lib.SCALES[scale_idx][1]
        degrees = len(intervals) * max(1, range_octaves)
        degree = (value * degrees) >> length
        if degree >= degrees:
            degree = degrees - 1
        oct_i, idx = divmod(degree, len(intervals))
        note = techno_lib.BASE_NOTE + root + 12 * (octave + oct_i) + intervals[idx]
        return max(0, min(127, note))

    @staticmethod
    def line(register, length, steps, root, scale_idx, octave, range_octaves):
        return [techno_lib.pitch(v, length, root, scale_idx, octave, range_octaves)
                for v in techno_lib.rotations(register, length, steps)]

    @staticmethod
    def kit_line(register, length, steps, kit_notes, kit_range=4, centre=None):
        """The Turing walk across a drum kit instead of across a scale.

        On the shipped SFZ kits a note number selects WHICH SAMPLE sounds -
        key=/lokey= maps notes to different drums - so quantising to ROOT and
        SCALE would land most steps on empty keys. An empty key is silence
        with nothing to explain it, which is the one thing this instrument
        must never do.

        Same rotations as line(), mapped onto the kit's own notes. Returns []
        for an empty kit; the caller falls back to the channel's own note
        rather than the library inventing one.

        SP8: `kit_range` 1-4 confines the walk to a WINDOW of the kit instead
        of all of it, centred on `centre` - the channel's own current note - so
        narrowing closes in around the drum the channel already plays rather
        than sliding somewhere else. Without it a hats channel switched to
        Turing wanders onto kicks.

        **4 is the whole kit and it is the drum default**, so existing
        snapshots sound identical the day this ships and SP8 is a pure option.
        That is also why the signature defaults this way: every existing call
        site keeps its meaning untouched."""
        if not kit_notes:
            return []
        count = len(kit_notes)
        lo, hi = 0, count - 1
        if kit_range is not None and kit_range < 4:
            # WIDTH FIRST, THEN PLACE IT. The first version computed a half-
            # width around the centre and clamped both ends, which had two
            # faults the rig showed immediately on an 11-note kit centred on
            # the kick at index 0: the widths crawled (2, 3, 4 notes for
            # ranges 1, 2, 3) and then jumped to all 11 at range 4, and
            # because the kick sits at the EDGE of the list the window was
            # truncated to half its size - so a narrow setting was narrower
            # still, and never the width that was asked for.
            #
            # Now the width is a clean fraction of the kit and the window is
            # SLID INWARD when it would overhang, so the full width is always
            # used. On that kit the progression is 3, 6, 8, 11 rather than
            # 2, 3, 4, 11.
            # 1 IS ONE NOTE - the channel plays its own drum and the Turing
            # register drives only WHICH STEPS SOUND. Owner, 2026-08-19: that
            # is the default a drum sampler in voice mode should have, because
            # what it buys is rhythm design, not sample roulette. Widening from
            # there is the option, not the starting point.
            width = 1 if kit_range <= 1 else int(round(count * kit_range / 4.0))
            width = min(max(1, width), count)
            middle = count // 2
            if centre is not None and centre in kit_notes:
                middle = kit_notes.index(centre)
            lo = min(max(0, middle - width // 2), count - width)
            hi = lo + width - 1
        span = hi - lo + 1
        out = []
        for value in techno_lib.rotations(register, length, steps):
            idx = lo + ((value * span) >> length)
            out.append(kit_notes[min(hi, max(lo, idx))])
        return out

    @staticmethod
    def pad_note(pad, root, scale_idx, octave):
        """The note pad `pad` plays on a voice: scale degree `pad` counting up
        from the root.

        Deliberately independent of the generator - it follows neither RANGE
        nor the running line. A keyboard has to lie still under the hands, and
        both alternatives move the mapping while you play, while coupling hand
        play to the very generator the recording is about to switch off."""
        intervals = techno_lib.SCALES[scale_idx][1]
        oct_i, idx = divmod(pad, len(intervals))
        note = techno_lib.BASE_NOTE + root + 12 * (octave + oct_i) + intervals[idx]
        return max(0, min(127, note))

    @staticmethod
    def pad_notes(root, scale_idx, octave, count=16):
        return tuple(techno_lib.pad_note(p, root, scale_idx, octave)
                     for p in range(count))

    @staticmethod
    def candidate_notes(kind, group_note, pads=(), line=()):
        """Every note a channel's pattern can legitimately contain.

        This is what makes rebuilding the note map cheap. The installed
        libzynseq has no getNoteAtIndex(), so a step's contents can only be
        probed note by note - but not all 128 need probing. A drum channel is
        one sound; a voice can only hold what its keyboard or its generator
        can produce."""
        if kind != "voice":
            return (group_note,)
        return tuple(sorted(set(pads) | set(line) | {group_note}))

    # Which knobs take a pattern back from the player. The rule is exactly
    # "the knobs that rewrite the pattern", and it differs per kind because
    # LENGTH means two different things: on a drum it is the bar count and
    # _set_length preserves the steps that fit, on a voice it is the shift
    # register and it regenerates the whole line.
    HANDBACK_VERBS = {
        "drum": frozenset(("hits", "rotate", "div")),
        # `rhythm` joins the voice set: it rewrites the whole pattern, so it
        # takes it back from a player the same way `random` does - and under
        # the same exception, moving DOWN to LOCK is not destructive.
        "voice": frozenset(("length", "div", "random", "rhythm")),
    }

    @staticmethod
    def hands_back(kind, verb, value=None):
        """Does turning `verb` on a `kind` channel take the pattern back from
        the player?

        RANDOM only does so when it moves OFF lock. Turning it down to LOCK is
        what a recording does to itself, and that must not immediately undo the
        recording."""
        if verb not in techno_lib.HANDBACK_VERBS.get(kind, frozenset()):
            return False
        if verb in ("random", "rhythm"):
            return (value or 0) > 0
        return True

    KINDS = ("drum", "voice")

    @staticmethod
    def default_channel_state(kind):
        """A complete starting state set for one kind.

        Complete is the point: columns() indexes state["cutoff"] and friends
        directly, so a half-built voice set is a KeyError on the render path.
        The driver's __init__ and SP4's first switch both build through here
        so the two can never drift apart.

        chance is common to both kinds: setPlayChance is a per-pattern zynseq
        property and kind-agnostic, so STEP's spread page reaches a voice too."""
        state = dict(level=19, reverb=0, delay=0, swing=50, velo=110,
                     chance=100, pending=set())
        if kind == "drum":
            # RANGE on a DRUM is SP8's kit-walk window, and it starts at 4 -
            # the whole kit - so a channel walks exactly as it did before SP8
            # existed. A voice's RANGE is octave spread and keeps its own
            # default of 2; sharing that number here would have narrowed every
            # existing drum channel to half its kit the day this shipped.
            state.update(kit="----", sample="----", range=4, kit_range=1,
                         # 1 = off. A step fires once, as it always has.
                         ratchet=1)
        else:
            state.update(
                preset="----", cutoff=64, reso=32, env=64, decay=40,
                random=0, gate=40, octave=0, range=2,
                # The rhythm generator. `rhythm` is its evolve knob, 0 = LOCK,
                # exactly like `random` is the melody generator's. `rhythm_reg`
                # is its register: one bit per step, all 16 set, which is every
                # step sounding - precisely what density=100 gave before, so a
                # new voice is unchanged.
                #
                # `random` keeps its key although the panel now reads MELODY:
                # renaming it would move the data in every saved snapshot for a
                # cosmetic gain.
                rhythm=0, rhythm_reg=0xFFFF,
                # LENGTH on a voice is the shift register's length in bits,
                # not the pattern's length in beats - a different parameter
                # wearing the same word, so it lives in the dict and never in
                # the legacy beats array.
                length=8, register=0b10110011, ring=deque(maxlen=4),
                # SP8's kit-walk window. Lives on the voice set too because a
                # SAMPLER channel switched to voice behaviour is the case it
                # exists for, and that channel carries a voice state.
                #
                # DEFAULT 1 = ONE NOTE. A drum sampler played by the Turing
                # register should give rhythm variation on its own drum, not a
                # walk across the kit - owner, 2026-08-19.
                kit_range=1)
        return state

    # ------------------------------------------------------- pad overlays
    #
    # Three features want the same takeover: hold a modifier and the sixteen
    # pads stop being the step picture and become something else - probability
    # on SHIFT, the rate/shape legend on MOD, the ring map on NAVIGATE. The
    # policy lives here rather than in the driver because the driver cannot be
    # imported on WSL: anything left there is checked by py_compile and the rig
    # only, and "which modifier owns the pads" is exactly the kind of rule that
    # drifts when three features each decide it separately.

    # Highest priority first. MOD LATCHES, so mod-active and shift-held really
    # do co-occur; the owner's rule (2026-08-19) is that a momentary gesture
    # takes the pads from a latched state and hands them back on release.
    # ARM sits above MOD and below SHIFT. SHIFT is the oldest and most-used
    # binding and must not move; a player holding ARM has committed to
    # scheduling, so it outranks the timbre overlay underneath it.
    OVERLAY_PRIORITY = ("shift", "arm", "mute", "mod", "navigate")

    # Whether an overlay's pads still MEAN steps. The playhead is drawn over
    # the top only where they do: under SHIFT pad 3 is step 3 carrying a
    # probability, so the sweep helps; under MOD pad 3 is a RATE and a playhead
    # marker on it would point at nothing. Under ARM a pad is a macro or a bar
    # count, which is the same story again.
    OVERLAY_STEPWISE = {"shift": True, "arm": False, "mute": False,
                        "mod": False, "navigate": False}

    @staticmethod
    def overlay_is_stepwise(owner):
        """True when the pads under this overlay still stand for steps."""
        return techno_lib.OVERLAY_STEPWISE.get(owner, True)

    # The phrase page's two brightnesses. TWO, not three: past and now read at
    # a glance, and a third level for "ahead" would need a legend to be read
    # at all. Ahead is simply dark.
    COLOR_PHRASE = 0x00D0FF
    PHRASE_PAST = 0.4

    @staticmethod
    def phrase_pad(index, bar, phrase_bars=16):
        """(colour, brightness) for one pad of the NAVIGATE phrase page.

        `bar` is the absolute bar count, or None when the transport is
        stopped. Stopped draws EVERY pad dark rather than freezing the last
        picture: a phrase page showing bar 1 lit while nothing plays reads as
        a running clock that has stuck, which is the unexplained-silence law
        wearing a display."""

        if bar is None:
            return (techno_lib.COLOR_PHRASE, techno_lib.PAD_OFF)
        now = techno_lib.phrase_bar(bar, phrase_bars)
        if index == now:
            return (techno_lib.COLOR_PHRASE, techno_lib.PAD_FULL)
        if index < now:
            return (techno_lib.COLOR_PHRASE, techno_lib.PHRASE_PAST)
        return (techno_lib.COLOR_PHRASE, techno_lib.PAD_OFF)

    @staticmethod
    def pad_owner(shift=False, mod=False, arm=False, navigate=False,
                  mute=False):
        """Which overlay the PADS obey, chord exceptions included.

        THE SINGLE PREDICATE for the pad dispatcher, the pad painter and the
        poll loop, for the reason _switch_row exists: a second approximation
        of "what do the pads mean right now" drifts from the first, and pads
        that disagree with what a press does is the worst object this surface
        can produce.

        The one exception to OVERLAY_PRIORITY: **MOD latched AND ARM held is
        MOD**, not ARM. MOD+ARM is how a modulator is made one-shot, so the
        pads must go on showing the rate and shape legend the player is
        choosing from. Sending them to ARM's macro picker would take the menu
        away at the exact moment it is being read.

        It is safe as a CHORD where SHIFT+button was not, because MOD LATCHES:
        the player is not holding two things at once, they pressed MOD earlier
        and are now holding ARM.

        **SHIFT still outranks the chord.** SHIFT is the oldest and most-used
        binding on this surface and the exception is not allowed to move it -
        a player holding SHIFT gets SHIFT, whatever else is latched."""

        if mod and arm and not shift:
            return "mod"
        return techno_lib.overlay_owner(shift=shift, mod=mod, arm=arm,
                                        navigate=navigate, mute=mute)

    @staticmethod
    def overlay_owner(shift=False, mod=False, navigate=False, arm=False,
                      mute=False):
        """Which modifier owns the pads, or None for the ordinary step picture.

        `arm` defaults False so every existing caller keeps its meaning."""
        held = {"shift": shift, "arm": arm, "mute": mute, "mod": mod,
                "navigate": navigate}
        for name in techno_lib.OVERLAY_PRIORITY:
            if held[name]:
                return name
        return None

    # MUTE's grid: the eight channels twice over. The top two rows act NOW,
    # the bottom two queue the same change to the channel's next wrap.
    MUTE_ROWS_INSTANT = 8

    # Half brightness for a queued change, full for audible, dark for muted.
    # THREE levels here where the phrase page allows only two, and the reason
    # is that this grid is read while you are holding it rather than glanced
    # at: the hand is already on the pads, so the third level has a gesture to
    # explain it.
    MUTE_QUEUED = 0.6

    @staticmethod
    def mute_pad_channel(pad, count=8):
        """(channel, queued) for a pad of the MUTE grid, or None.

        Pads 0-7 are the channels now; 8-15 are the same channels queued. The
        two halves are the SAME ORDER, so the queued row sits directly under
        its own channel and the grid reads as one row of eight with two ways
        to press it."""
        pad = int(pad)
        if not 0 <= pad < 2 * count:
            return None
        if pad < techno_lib.MUTE_ROWS_INSTANT:
            return (pad, False)
        return (pad - techno_lib.MUTE_ROWS_INSTANT, True)

    @staticmethod
    def mute_pad_state(colour, muted, queued=None, is_queue_row=False):
        """(colour, brightness) for one pad of the MUTE grid.

        The GROUP HUE, because the pads are channels here and this instrument
        has said "hue is identity" since the Group LEDs were written. Only the
        brightness carries the state.

        `queued` is the pending change for that channel, or None for no
        change. A queue-row pad shows the CHANGE, not the current state: half
        bright when something is queued, dark when nothing is. Otherwise the
        bottom half would duplicate the top half and the row would say nothing
        the top row does not."""

        if is_queue_row:
            if queued is None:
                return (colour, techno_lib.PAD_OFF)
            return (colour, techno_lib.MUTE_QUEUED)
        return (colour, techno_lib.PAD_OFF if muted else techno_lib.PAD_FULL)

    # The rungs SHIFT + pad walks, in order, wrapping back to the top.
    #
    # It stops at 25 and does NOT include 0. A step that never fires is
    # indistinguishable from a step that is off, and "a silent channel must say
    # why" is the law that cost this project a jam. Turning a step off is what a
    # bare tap is for, and that reads differently on the pads.
    CHANCE_RUNGS = (100, 75, 50, 25)

    # What a FREEZE tap stops. Everything here rewrites notes; the LFOs do
    # not, which is why they are not in the set and need the deeper gesture.
    FREEZE_GENERATIVE = frozenset(("melody", "rhythm", "drift", "reroll"))

    # Ice blue, and nothing else on the panel uses it.
    COLOR_FREEZE = 0x60D0FF

    @staticmethod
    def freeze_blocks(what, frozen, deep):
        """Is `what` held still right now?

        TWO STAGES ON ONE BUTTON, and they map onto law L1 exactly, which is
        the reason to prefer them over a second button - nothing new has to be
        learned or documented as an exception:

            tap PAD MODE   -> `frozen`, LATCHED. Pattern generation holds and
                              the LFOs keep sweeping, so the notes stop
                              changing under you while the sound keeps
                              breathing.
            hold PAD MODE  -> `deep`, MOMENTARY. Everything above PLUS the
                              LFOs, released on let-go.

        A hold is the TOTAL hold: it blocks everything a tap blocks as well as
        the LFOs. A deeper gesture that did less than the shallower one would
        be a rule nobody could remember.

        An unrecognised subject is never blocked. A typo must not silently
        freeze something, and it must not silently thaw it either."""

        if what == "lfo":
            return bool(deep)
        if what in techno_lib.FREEZE_GENERATIVE:
            return bool(frozen or deep)
        return False

    @staticmethod
    def rec_led_state(possible, overdub, recording):
        """What REC's LED means, from ALL THREE facts at once.

        REC's LED already meant "an overdub is possible here" - dark in STEP
        mode and while MOD owns the pads, because holding REC does nothing
        there. Audio capture is a SECOND meaning on the same LED, and two
        writers would fight over it, so there is one predicate taking every
        fact and no second writer anywhere. That is the same rule that made
        _switch_row the single predicate for the F row.

        CAPTURE OUTRANKS POSSIBILITY. A capture running while the player is in
        STEP mode must still light the button: a file quietly filling the disk
        with nothing on the panel saying so is the unexplained-silence law
        pointed the other way."""

        if recording and overdub:
            return "both"
        if recording:
            return "recording"
        if not possible:
            return "off"
        if overdub:
            return "overdub"
        return "ready"

    @staticmethod
    def chance_ramp(base, floor, bar, bars):
        """Play chance `bar` bars into a ramp that dips to `floor` and back.

        Down over the first half, up over the second, landing exactly on
        `base` - THE PLAYER'S OWN VALUE, never 100. CHANCE lives in the
        snapshot's own riff and is read back on load; assuming 100 is the
        original bug that made a channel saved at chance 0 come back silent
        while the surface read full.

        A base already at or below the floor is left alone: a breakdown that
        made a quiet channel louder would be the gesture backwards.

        Past the end it returns `base` rather than continuing past it, so a
        missed poll cannot strand a channel thinned forever - the same
        reasoning as PendingQueue.due() using >= rather than ==."""

        base = int(base)
        if bars <= 0 or base <= floor:
            return base
        half = bars / 2.0
        # 1.0 at both ends, 0.0 in the middle, clamped so a step past the end
        # lands back on base instead of overshooting above it.
        pos = min(1.0, abs(bar - half) / half)
        return int(round(floor + (base - floor) * pos))

    # The macros ARM can compose, one per pad from 0. The remaining pads stay
    # dark and unbound, because a lit pad that does nothing is the fault this
    # surface must never commit. APPEND-ONLY - a snapshot may store the name,
    # so an existing entry never moves index. drop and chance shipped with
    # package 1; half and double joined them with package 3.
    ARM_MACROS = ("drop", "chance", "half", "double", "break",
                  "ratchet")

    # Pads 8-15, the length ring, in bars. Eight lengths for eight pads, and
    # the odd ones (3, 6, 12) are there because a build does not have to be a
    # power of two.
    ARM_LENGTHS = (1, 2, 3, 4, 6, 8, 12, 16)

    # ARM's three colours, and they are three because the grid says three
    # different kinds of thing. Amber for "which macro", green for "how many
    # bars", red for the countdown - red only ever means time running out, so
    # it cannot be confused with either picker.
    COLOR_ARM_MACRO = 0xFF6000
    COLOR_ARM_LENGTH = 0x00FF60
    COLOR_ARM_COUNT = 0xFF2000
    ARM_DIM = 0.35
    PAD_OFF = 0.0

    @staticmethod
    def arm_legend_pad(index, picked=None, armed_bars=None, remaining=None):
        """(colour, brightness) for one pad of the ARM overlay.

        TWO pictures on one grid, chosen by whether anything is pending.

        Nothing pending - a PICKER. Pads 0..len(ARM_MACROS)-1 are the macros,
        the picked one at full and the others dim; pads 8-15 are the length
        ring. **Everything between them is dark**, because pads 2-7 have no
        macro behind them yet and a lit pad that does nothing is the fault
        this surface must never commit.

        Something pending - the COUNTDOWN RULER. One pad per bar of the armed
        length, extinguishing from the top left as the bars pass, so the pads
        still lit ARE the bars still to come. The picker is not drawn at all:
        reading the countdown must not also offer to change it.

        Brightness 0.0 rather than None for a dark pad - _paint_pad wants a
        tuple, and an unlit pad still has to be WRITTEN or the previous
        picture stays on the hardware."""

        off = (techno_lib.COLOR_ARM_COUNT, techno_lib.PAD_OFF)
        if armed_bars is not None and remaining is not None:
            bars = max(1, min(16, int(armed_bars)))
            left = max(0, min(bars, int(remaining)))
            if index >= bars or index < bars - left:
                return off
            return (techno_lib.COLOR_ARM_COUNT, techno_lib.PAD_FULL)

        if index < len(techno_lib.ARM_MACROS):
            macro = techno_lib.ARM_MACROS[index]
            bright = (techno_lib.PAD_FULL if macro == picked
                      else techno_lib.ARM_DIM)
            return (techno_lib.COLOR_ARM_MACRO, bright)
        if index >= 8:
            # The whole ring is lit whether or not a macro is picked. It is a
            # menu of lengths, not a confirmation - dimming it until a macro
            # was chosen would hide the choice the player is about to make.
            return (techno_lib.COLOR_ARM_LENGTH, techno_lib.ARM_DIM)
        return (techno_lib.COLOR_ARM_MACRO, techno_lib.PAD_OFF)

    @staticmethod
    def chance_ladder(chance):
        """The next rung strictly BELOW `chance`, wrapping back to full.

        One rule, no special case. It gives 100 -> 75 -> 50 -> 25 -> 100 for the
        ladder's own values, and it also lands any OTHER value on a rung in a
        single press - chance is settable from the touchscreen and arrives out
        of older snapshots, so a ladder that only moved between its own outputs
        would stick on 90 or 60 forever."""

        below = [r for r in techno_lib.CHANCE_RUNGS if r < chance]
        return max(below) if below else max(techno_lib.CHANCE_RUNGS)

    # The daemon halves brightness (set_rgb_light: `brightness * 0.5`), so 2.0
    # is full scale. Derived from daemon/src/devices/mk2/mikro.rs:529.
    PAD_FULL = 2.0

    # ONE LOOK PER RUNG: colour AND brightness both carry the value, so either
    # alone is enough to read it.
    #
    # Brightness alone did NOT work, and arithmetic says why rather than taste.
    # The four rungs gave LED bytes 111 / 159 / 207 / 255 - a 2.29:1 ratio - but
    # brightness perception follows roughly a cube-root power law, so the EYE
    # sees about 1.32:1 across the WHOLE scale and some 10% between neighbours.
    # The owner reported them "nearly indistinguishable", which is exactly what
    # 10% predicts. Measured 2026-08-19, on the hardware, by the owner's eye.
    #
    # Hue does the real work now. The group colours are NOT reserved here,
    # because the step picture is suppressed while the overlay owns the pads;
    # the one hard rule is that no rung may be WHITE, which is the playhead
    # drawn over the top.
    #
    # Blinking was considered and rejected: it needs a 30 Hz repaint of up to
    # sixteen pads on a daemon whose own comment records being "flooded off the
    # USB bus once"; it is fatiguing to read sixteen of them at a glance; and it
    # would collide with both the playhead sweep and the MOD legend's fade. This
    # is static, so led_cache swallows every repeat and it costs nothing.
    CHANCE_LOOKS = {
        100: (0xFF00C8, 2.00),   # magenta, full - "always"
        75:  (0xFF2000, 1.40),   # red
        50:  (0xFF8000, 0.95),   # orange
        25:  (0x40C0FF, 0.65),   # pale blue, deliberately the odd one out so
    }                            # "barely ever" is unmistakable at a glance

    @staticmethod
    def probability_pad(step_on, chance):
        """(colour, brightness) for one pad while SHIFT is held.

        Redundant coding on purpose - see CHANCE_LOOKS for why brightness alone
        was not readable."""

        if not step_on:
            # No note to roll for. Drawing it lit would claim a probability that
            # cannot fire.
            return (techno_lib.CHANCE_LOOKS[100][0], 0.0)
        # Snap to the nearest rung AT OR BELOW, so a value set from the
        # touchscreen or restored from an older snapshot still shows the look of
        # the rung the ladder would give it. Never below the bottom rung: a step
        # that sounds must never read as one that is off.
        rung = max((r for r in techno_lib.CHANCE_RUNGS if r <= chance),
                   default=min(techno_lib.CHANCE_RUNGS))
        return techno_lib.CHANCE_LOOKS[rung]

    # -------------------------------------------------------------- REROLL
    #
    # SCENE rerolls the drum channels, PATTERN the voices. Both buttons are
    # measured free and named right on the panel.
    #
    # TWO FLOORS, NON-NEGOTIABLE. A reroll may never leave a channel silent
    # with nothing to say why: hits stay >= 1, play chance stays above a floor,
    # and a voice's rhythm register never comes back empty. Silence is the
    # failure this instrument is built to explain, and a reroll that mutes a
    # channel by accident is that failure with a new cause.
    REROLL_CHANCE_FLOOR = 40

    # The floor a beat repeat collapses to. ONE BEAT, and there is no
    # half-bar repeat: getLength() is beats * PPQN, so a length is whole
    # beats and always will be.
    #
    # NOTE WHAT ONE BEAT MEANS, because it is not what a reader expects: at
    # 1/4 a beat is ONE STEP and at 1/32 it is EIGHT. The floor is stated in
    # beats and felt in steps, so the same gesture is a single repeated hit on
    # a coarse channel and a tight stutter on a fine one. The guide has to say
    # this - a limit stated without its division is how the polymeter claim
    # came to be false.
    REPEAT_BEATS = 1

    @staticmethod
    def repeat_label(label, active, count=0):
        """The page indicator says the loop is being squeezed.

        Carries the channel COUNT because beat repeat skips player-owned
        channels: a take has no euclid parameters to regenerate from, so
        there is nothing to put back afterwards. A gesture that quietly missed
        two of eight channels must say so."""
        if not active:
            return label
        return f"{label} RPT{int(count)}"

    @staticmethod
    def arm_label(label, arm_down, picked):
        """Name the macro the player has picked, while ARM is held.

        Added 2026-08-20 after the first play test: the picker brightened the
        pad it picked and said NOTHING ELSE, so with six macros on the grid a
        player had no way to know what they were about to arm short of arming
        it and reading the PENDING page afterwards. A control that will not
        say what it is about to do is the same fault as one that does nothing
        and will not admit it.

        Only while ARM is HELD. Once armed, the countdown ruler, the LED and
        the PENDING page all carry it, and a stale name on the label would
        outlive the gesture."""

        if not arm_down:
            return label
        if picked is None:
            return f"{label} ARM?"
        name = techno_lib.PENDING_NAMES.get(picked, str(picked).upper())
        return f"{label} ARM {name}"

    @staticmethod
    def freeze_label(label, frozen, deep):
        """The page indicator says the machine is being held.

        FRZ for the latch, FRZ! for the total hold - two words rather than
        one, because the two stages stop different things and a player who
        cannot tell them apart cannot tell whether their LFOs are still
        moving.

        A frozen instrument must never read as a broken one. This is one of
        three independent things saying so, alongside PAD MODE's LED and the
        frozen columns losing their bars."""
        if deep:
            return f"{label} FRZ!"
        if frozen:
            return f"{label} FRZ"
        return label

    @staticmethod
    def reroll_label(label, pending):
        """Mark the strip while a reroll waits for the bar.

        Without a pending marker the player presses again thinking it missed -
        and the second press is the cancel, so they would silently undo their
        own gesture."""
        return f"{label} REROLL>" if pending else label

    @staticmethod
    def phrase_label(label, bar, phrase_bars=16):
        """Append bar N of the phrase to the page indicator.

        Counts from ONE. The player is reading a bar number, not an array
        index, and every other number on this surface is one-based.

        `bar` is None when the transport is stopped: there is no bar to be on,
        and a frozen "1/16" would read as a running clock that had stuck."""
        if bar is None:
            return label
        return f"{label} {techno_lib.phrase_bar(bar, phrase_bars) + 1}/{phrase_bars}"

    @staticmethod
    def reroll_scope(which, samplers, owners, selected, shift):
        """The channels a reroll will touch.

        A BARE PRESS takes the ACTIVE group only, whichever button it was -
        pressing a button acts on what you are looking at, and refusing because
        "this is the drum button and you are on a voice" would be a rule to
        remember for no benefit.

        SHIFT takes every channel of that button's ENGINE type: PATTERN the
        samplers, SCENE the synths. **Engine, not kind** - owner, 2026-08-19.
        A drum sampler running in Turing mode is still a sampler, so it answers
        to PATTERN; asking for a global synth sequence change must not hand you
        a new drum pattern with it. Kind still decides WHAT is rerolled on each
        channel, because a drum-kind channel has hits and rotation while a
        voice-kind one has registers - but it no longer decides WHO.

        Owned channels are skipped either way: drums have no undo, so a reroll
        that included them would be a data-loss button.
        """

        if shift:
            # PATTERN is the drum word and SCENE the melodic one - the owner's
            # reading of the panel, 2026-08-19.
            want = bool(which == "pattern")
            channels = tuple(ch for ch in sorted(samplers)
                             if bool(samplers[ch]) == want)
        else:
            channels = (selected,) if selected is not None else ()
        return tuple(ch for ch in channels if owners.get(ch, "gen") != "player")

    @staticmethod
    def reroll_drum(steps, rng=random.random):
        """New hits and rotation for one drum channel.

        Hits are floored at 1 and capped at the pattern's own step count - a
        triplet division has 12 steps, not 16, and a reroll that wrote 14 would
        silently do nothing with two of them."""
        steps = max(1, int(steps))
        hits = 1 + int(rng() * steps)
        return {"hits": min(steps, hits), "rotate": int(rng() * steps) % steps}

    @staticmethod
    def reroll_voice(rng=random.random):
        """New play chance, rhythm register and RANDOM value for one voice.

        The register is rerolled rather than the notes: a voice's steps ARE its
        rhythm register, so this is the same gesture the drum reroll makes on
        hits and rotation. It cannot come back empty - no bits set is the "no
        steps at all" silence the tab row exists to explain."""
        reg = int(rng() * 0xFFFF) & 0xFFFF
        if not reg:
            reg = 1
        span = 100 - techno_lib.REROLL_CHANCE_FLOOR
        return {
            "chance": techno_lib.REROLL_CHANCE_FLOOR + int(rng() * (span + 1)),
            "rhythm_reg": reg,
            # MELODY GOES TO LOCK, ALWAYS - owner, 2026-08-19, overriding the
            # 2026-08-14 spec, which said to reroll "the RANDOM value itself".
            # Doing that literally meant pressing PATTERN could turn a held
            # line into an evolving one: a MODE change smuggled into a pattern
            # gesture. Locking instead hands you a new line and FREEZES it, so
            # you can hear what you got before deciding to let it move. It is
            # also what _duplicate already does when it gives a register back.
            "random": 0,
        }

    # ------------------------------------------------------------- RATCHET
    #
    # A step fires 2, 3 or 4 times inside its own slot. Implemented as zynseq's
    # NATIVE STUTTER rather than as stacked notes, because Pattern::addEvent
    # DELETES overlapping events carrying the same note - three addNote calls on
    # one step leave one note, not three. The event already has a stutter count
    # and a stutter duration, and the installed .so exports setStutterCount and
    # setStutterDur; a ratchet is exactly what those fields are for.
    RATCHET_MAX = 4

    @staticmethod
    def ratchet_rung(step, bars):
        """The ratchet setting `step` bars into a `bars`-long ramp.

        ONE RUNG PER BAR, spread across the armed length, and it ALWAYS
        ARRIVES: the last bar is RATCHET_MAX whatever the length. A build that
        reached x3 because the player armed three bars is a build that does
        not land.

        A two-bar arm therefore gives 1 then 4 rather than 1 then 3 - the
        rungs are distributed, not walked. Arriving matters more than the
        shape of the approach.

        The entry describes all four rungs inside the FINAL bar instead. The
        clock can serve that - phrase_pos returns a fraction and a quarter-bar
        at 124 BPM is 484 ms against a ~33 ms tick - but PendingQueue is
        bar-granular and no other payload in three packages wants sub-bar
        timing. Build it once, when a second one does.

        Past the end it HOLDS the maximum rather than falling back: a missed
        poll must not drop the roll to nothing mid-build."""

        top = techno_lib.RATCHET_MAX
        bars = int(bars)
        step = int(step)
        if bars <= 1:
            return top
        if step <= 0:
            return 1
        if step >= bars - 1:
            return top
        return 1 + int(round((top - 1) * step / float(bars - 1)))

    @staticmethod
    def ratchet_stutter(ratchet, clocks_per_step):
        """(stutter count, stutter duration in clocks) for a ratchet setting.

        1 means OFF and returns (0, 0) - no stutter fields written at all, so a
        pattern with the feature unused is byte-identical to one written before
        it existed.

        The duration is FLOORED AT ONE CLOCK. At a fast division a step can be
        few enough clocks that dividing it four ways rounds to zero, and a
        zero-length stutter is a step that makes no sound: silence with nothing
        to explain it, which is the failure this instrument exists to avoid."""

        n = int(ratchet)
        if n <= 1:
            return (0, 0)
        n = min(n, techno_lib.RATCHET_MAX)
        # THE DURATION IS HALVED AGAIN, and the reason is in the player rather
        # than in the header. track.cpp schedules stutter events that ALTERNATE
        # note-off and note-on:
        #
        #     command = (nStutterCount % 2 ? NOTE_ON : NOTE_OFF)
        #     stutter_time = (offset + StutterDur) * ++nStutterCount * spc
        #     if (stutter_time < noteOffTime && 2 * StutterCount >= nStutterCount)
        #
        # So one audible retrigger costs TWO events, and events only fire while
        # they fall inside the note's own length. With dur = cps / n the events
        # ran out of room before the second note-on: x2 emitted a note-off and
        # nothing else, which on a LinuxSampler one-shot is silence - the
        # sample plays to its end regardless. That is why x2 sounded identical
        # to OFF while x3 and x4 did something.
        #
        # For n audible hits we need 2n-1 events inside the note, so the
        # spacing is cps / 2n. Derived from the player, after guessing by ear
        # twice and being wrong both times.
        return (n, max(1, int(clocks_per_step) // (2 * n)))

    # ------------------------------------------------------- the big encoder
    #
    # CC 15 is a 16-position counter TIMES 8, wrapping 120 -> 0. It comes from
    # the daemon's "A8" branch (main.rs:911) as `status as u8 * 8` and NEVER
    # passes send_encoder_cc, so is_encoder_jump never sees it. There is no
    # rejection threshold to fight - a trap note once claimed it "sits exactly
    # on the rejection threshold", which described a code path CC 15 does not
    # take. The exact signed delta needs no guard at all.
    BIG_UNITS_PER_DETENT = 8

    @staticmethod
    def big_delta(previous, current):
        """Signed units moved, wrap-safe. 120 -> 0 is one detent forward, not
        fifteen backwards."""
        return ((int(current) - int(previous) + 64) % 128) - 64

    @staticmethod
    def big_detents(units):
        """(whole detents, remainder to bank).

        A fast spin arrives as several detents in ONE report, and every page it
        passed must be stepped rather than collapsed into one - the knob is the
        page ring now, and skipping pages on a quick turn would make it feel
        like it missed the gesture."""
        per = techno_lib.BIG_UNITS_PER_DETENT
        steps = int(units / per) if units >= 0 else -int(-units / per)
        return (steps, units - steps * per)

    # ------------------------------------------------- the MOD pad legend
    #
    # While MOD owns the pads they stop drawing the step picture and become the
    # modulation menu. Today the pads LIE: a pad hit under MOD sets a rate or a
    # shape (midi_event, ahead of the STEP branch) while the pads still draw
    # steps. Gesture and display disagree, which this surface is not allowed to
    # do.
    #
    # THE PERIODS ARE A LEGIBILITY MAP, NOT A MEASUREMENT, and the difference
    # matters enough to say twice. MOD_RATES spans 250:1 - at 124 BPM one bar is
    # 1.94 s, so the twelve rates run from 31 s per cycle down to 0.12 s. The
    # slowest four are indistinguishable from a static LED, and the fastest is
    # 8.3 Hz against a 30 Hz repaint: 3.6 samples per cycle, which aliases into
    # jitter rather than reading as speed. So the fades run on a compressed band
    # instead. "Further right and further down is faster" stays TRUE; the
    # absolute rate does not. Never quote these as what a modulator does.
    MOD_LEGEND_PERIODS = (2.00, 1.70, 1.45, 1.25, 1.05, 0.90,
                          0.78, 0.66, 0.56, 0.48, 0.41, 0.35)

    # One hue for the twelve rate pads, another for the four shape pads. Neither
    # is white - that is the playhead, drawn over the top.
    COLOR_MOD_RATE = 0x00D0FF        # cyan
    COLOR_MOD_SHAPE = 0xC000FF       # violet

    # THE SELECTED PAD IS STEADY AT FULL, and is the only still pad on the grid.
    # Owner, 2026-08-19, replacing "swings widest": an amplitude cannot be
    # compared across pads moving at different speeds, so the widest swing was a
    # mark you had to work out rather than see. The cost is that the selected
    # rate no longer demonstrates its own speed - which is the one rate you
    # already know, because you chose it.
    MOD_LEGEND_BAND = 0.30
    # Floor, so an unselected pad still reads as lit rather than dead.
    MOD_LEGEND_FLOOR = 0.35
    # Nothing bound: _mod_pad returns immediately, so the gesture is inert.
    # Pads dancing while nothing can happen is the sin the dashed tab row
    # exists to prevent. Still, dim, and identical.
    MOD_LEGEND_INERT = 0.25
    # Quantised so led_cache.changed() swallows most ticks. Fading twelve pads
    # at 30 Hz is up to 360 pad messages a second, and the daemon has been
    # "flooded off the USB bus once".
    #
    # QUANTISING ALONE WAS NOT ENOUGH. On 2026-08-20 this wedged the controller
    # three times in one session, each within seconds of MOD being latched:
    # the daemon's reader starves, the device stops streaming HID reports, and
    # it does NOT come back from a daemon restart or from USB re-enumeration -
    # only from a physical replug. The repaint is now also THROTTLED, in the
    # driver, by MOD_LEGEND_TICKS. Both mitigations are needed; neither is
    # decoration.
    MOD_LEGEND_LEVELS = 12

    @staticmethod
    def mod_legend_pad(index, elapsed, selected_rate, selected_shape, bound=True):
        """(colour, brightness) for one pad of the MOD legend.

        `index` 0-11 are the rate pads, 12-15 the shapes - the same order
        _mod_pad already reads them in, and step 0 is the top-left pad, so the
        twelve rates fill the top three rows and the shapes the bottom one.

        `elapsed` is seconds. The legend is a display of what a rate FEELS like
        and is deliberately not tempo-locked to the modulator it depicts."""

        rates = len(techno_lib.MOD_LEGEND_PERIODS)
        is_rate = index < rates
        colour = techno_lib.COLOR_MOD_RATE if is_rate else techno_lib.COLOR_MOD_SHAPE
        if not bound:
            return (colour, techno_lib.MOD_LEGEND_INERT)

        if is_rate:
            period = techno_lib.MOD_LEGEND_PERIODS[index]
            shape = "tri"
            selected = index == selected_rate
        else:
            shape = techno_lib.MOD_SHAPES[index - rates]
            # A fixed, middling period so the four shapes are compared by their
            # SHAPE and not by their speed.
            period = 1.20
            selected = shape == selected_shape

        if selected:
            # Steady, full, and the only pad on the grid not moving.
            return (colour, techno_lib.PAD_FULL)
        wave = techno_lib.mod_wave(shape, (elapsed / period) % 1.0, seed=index)
        # wave is bipolar; fold to 0..1 so the pad swells rather than inverting.
        level = techno_lib.MOD_LEGEND_FLOOR + techno_lib.MOD_LEGEND_BAND * (wave + 1.0) / 2.0
        level = min(level, 1.0) * techno_lib.PAD_FULL
        step = techno_lib.PAD_FULL / techno_lib.MOD_LEGEND_LEVELS
        return (colour, round(level / step) * step)

    @staticmethod
    def throttle(seen, key, message, now, seconds):
        """Should this repeating log line be emitted now?

        Returns `(emit, suppressed, fresh)`. A NEW message is always emitted
        and marked `fresh`, which is the caller's cue to attach a traceback; a
        repeat is counted and emitted at most once per `seconds`, carrying the
        number suppressed since the last report.

        `seen` is the caller's own dict of per-key state and IS mutated - that
        is the memory the decision needs, and threading it back through every
        call site would put the same three lines of bookkeeping in each one.
        `now` is passed in rather than read here so the windows are testable
        without sleeping.

        This exists because the poll thread runs at 30 Hz. An unguarded
        logging.error on a persistent fault writes 30 lines a second for as
        long as the fault lasts, and the fault that motivated all of this was
        found IN the journal - burying it under its own repeats would have
        hidden the evidence that explained it."""

        entry = seen.get(key)
        if entry is None or entry["message"] != message:
            seen[key] = {"message": message, "at": now, "count": 0}
            return True, 0, True
        entry["count"] += 1
        if now - entry["at"] < seconds:
            return False, entry["count"], False
        suppressed = entry["count"]
        entry["at"] = now
        entry["count"] = 0
        return True, suppressed, False

    @staticmethod
    def upgrade_state(kind, saved, steps):
        """A state dict out of an older snapshot, brought up to the current
        key set.

        columns() indexes state["rhythm"] and its neighbours directly, so a
        dict short one key is a KeyError on the repaint path - and the repaint
        runs on the playhead poll thread. The snapshot `voices` block has
        upgraded its dicts since the rhythm generator shipped; the `stash`
        block restored them verbatim, so a channel's ALTERNATE kind kept its
        pre-2026-08-16 key set until a SHIFT+GRID pulled it into service. That
        is not a theoretical window: it took an instrument silent for three
        hours on 2026-08-18.

        Built from default_channel_state, so a key added tomorrow is covered
        here the day it exists rather than the day a snapshot proves it is
        not. Unknown keys are dropped rather than carried - DENSITY was
        retired by the rhythm generator and nothing reads it any more."""

        state = techno_lib.default_channel_state(kind)
        for key in state:
            # pending holds parameters waiting for the next bar, and a
            # snapshot load has no bar to wait for. It stays the empty set
            # default_channel_state just built.
            if key != "pending" and key in saved:
                state[key] = saved[key]
        if "ring" in saved:
            # A deque survives neither JSON nor a verbatim restore.
            state["ring"] = deque(saved["ring"], maxlen=4)
        if kind == "voice" and "rhythm_reg" not in saved:
            # The same seed the `voices` block applies, for the same reason:
            # the pre-rhythm dict describes its steps with DENSITY, and
            # reading them back as the 0xFFFF default would turn a sparse
            # line into every step sounding. `rhythm` stays 0 - a snapshot
            # made before rhythm evolution existed was not evolving.
            state["rhythm_reg"] = techno_lib.rhythm_seed(
                state["register"], state["length"], steps,
                saved.get("density", 100))
        return state

    @staticmethod
    def resolve_kind(override, chain_kind):
        """Which kind a channel behaves as.

        The override wins when it is set, and is otherwise absent - never a
        stored copy of the chain. Storing a derived value and watching the
        source move underneath it is the CHANCE/SWING defect of 2026-08-11,
        where the driver and zynseq agreed on the wrong answer.

        An unrecognised override is ignored rather than trusted: a snapshot
        written by another version must not be able to invent a third kind."""
        if override in techno_lib.KINDS:
            return override
        return chain_kind

    @staticmethod
    def next_kind(current):
        """Two states, no third."""
        return "voice" if current == "drum" else "drum"

    @staticmethod
    def type_label(label, override):
        """The page indicator marks a channel that is behaving differently
        from what its engine suggests. Absent when no override is set, which
        is also when the channel agrees with its chain."""
        if override == "voice":
            return f"{label} VOX"
        if override == "drum":
            return f"{label} DRM"
        return label

    @staticmethod
    def mod_label(label, active):
        """The page indicator says so while MOD is active.

        MOD makes the pads inert and turns all eight encoders from "set this
        value" into "set how it moves". A modifier that changes what every
        knob on the panel does, with nothing on the surface saying it is on,
        is the unexplained-behaviour law in another form - and MOD latches, so
        it can be on with nobody touching it."""
        return f"{label} MOD" if active else label

    @staticmethod
    def owner_label(label, owner, recording, playing):
        """The page indicator also carries who owns the channel and whether a
        take is being captured.

        REC held while the sequence is stopped must say REC-STOP: nothing is
        being captured, and silence with no explanation is the one thing this
        instrument must never do."""
        if recording:
            return f"{label} REC" if playing else f"{label} REC-STOP"
        if owner == "player":
            return f"{label} PLAY"
        return label

    # ---------------------------------------------------------------- channels

    # letter, 4-char name, kind, colour, engine code, midi channel (0-based).
    # Roles stay a table so 5+3, 4+4 and a degrade to six channels are config
    # lines rather than a redesign.
    CHANNELS = (
        ("A", "KICK", "drum",  0xFF0000, "LS/LinuxSampler", 0),
        ("B", "SNAR", "drum",  0xFF6000, "LS/LinuxSampler", 1),
        ("C", "CLAP", "drum",  0xFFC000, "LS/LinuxSampler", 2),
        ("D", "CHAT", "drum",  0xC0FF00, "LS/LinuxSampler", 3),
        ("E", "OHAT", "drum",  0x00FF00, "LS/LinuxSampler", 4),
        ("F", "BASS", "voice", 0x0040FF, "JV/JC303",        5),
        ("G", "LEAD", "voice", 0x8000FF, "JV/Obxd",         6),
        ("H", "PADS", "voice", 0x00E0FF, "JV/padthv1",      7),
    )

    # engine code -> (CUTOFF, RESO, ENV, DECAY/ATTACK), measured at gate G2 with
    # zynthian_lv2.get_plugin_ports - what the chain really publishes, not an
    # ENABLED flag in engine_config.json.
    VOICE_SYMBOLS = {
        "JV/JC303":   ("_cutoff", "_resonance", "_envmod", "_decay"),
        "JV/Obxd":    ("cutoff", "resonance", "filterenvamount", "decay"),
        "JV/padthv1": ("DCF1_CUTOFF", "DCF1_RESO", "DCF1_ENVELOPE", "DCA1_ATTACK"),
    }

    # Role patterns for a plugin the table has never seen. Swapping a chain's
    # synth from the touchscreen is a normal thing to do, and until this
    # existed the four page-1 columns kept pointing at the symbols of the
    # engine named in CHANNELS - so a channel moved off JC303 drew four numbers
    # whose knobs moved nothing.
    #
    # One tuple per role, patterns tried in order; a pattern matches a symbol
    # when every fragment of it appears in the symbol, lower-cased. Order is
    # the whole guard against a false positive: the unambiguous name is tried
    # first, so a plugin publishing both `cutoff` and `lfo_freq` cannot land
    # the filter column on its LFO.
    VOICE_ROLE_PATTERNS = (
        (("cutoff",), ("filter", "freq"), ("vcf", "freq"), ("dcf", "freq"),
         ("flt", "freq")),
        (("resonance",), ("reso",), ("vcf", "res"), ("dcf", "res"),
         ("filter", "res"), ("flt", "res")),
        (("envmod",), ("filterenv",), ("env", "mod"), ("env", "amount"),
         ("dcf", "env"), ("vcf", "env"), ("filter", "env")),
        (("decay",), ("attack",)),
    )

    @staticmethod
    def discover_voice_symbols(ports):
        """Guess (CUTOFF, RESO, ENV, DECAY) from what a plugin publishes.

        Strictly the fallback: the measured table wins wherever it has an
        entry, because a pattern match is a guess and gate G2's numbers are
        not. A role that matches nothing comes back None so its column can
        draw dead - law L4, never a number the knob cannot move - and a role
        never steals a symbol an earlier role already took."""
        usable = techno_lib.usable_ports(ports)
        claimed = set()
        found = []
        for patterns in techno_lib.VOICE_ROLE_PATTERNS:
            symbol = None
            for fragments in patterns:
                for candidate, _, _ in usable:
                    if candidate in claimed:
                        continue
                    name = str(candidate).lower()
                    if all(fragment in name for fragment in fragments):
                        symbol = candidate
                        break
                if symbol is not None:
                    break
            if symbol is not None:
                claimed.add(symbol)
            found.append(symbol)
        return tuple(found)

    @staticmethod
    def voice_symbols(eng_code, ports):
        """The four page-1 synth symbols for a chain running `eng_code`.

        Always four entries, any of which may be None. `eng_code` is the
        processor's, never the CHANNELS table's - the table says what the
        snapshot loaded, the processor says what is running now."""
        measured = techno_lib.VOICE_SYMBOLS.get(eng_code)
        if measured:
            return tuple(measured)
        return techno_lib.discover_voice_symbols(ports)

    @staticmethod
    def synth_ctrl_flags(state):
        """Which of the four page-1 synth columns are reachable.

        `synth_ctrl` is the per-column truth, `has_synth_ctrl` the
        all-or-nothing flag that predates it, and an absent key means a synth
        with all four - every caller before SP4 omitted it."""
        flags = state.get("synth_ctrl")
        if flags is not None:
            return tuple(bool(flag) for flag in flags)[:4]
        return (bool(state.get("has_synth_ctrl", True)),) * 4

    # --------------------------------------------------------------------- FX

    # role -> (plugin symbol, lo, hi). Gates G1 and G3 between them left exactly
    # one affordable stereo pair with a true wet level: TAP Reverberator and TAP
    # Stereo Echo. Every MDA and CAPS candidate turned out to be a crossfade.
    FX_REVERB = {
        "WET":     ("wetlevel", -70.0, 10.0),
        "DRY":     ("drylevel", -70.0, 10.0),
        "REVSIZE": ("decay", 0.0, 10000.0),
        "REVTYPE": ("mode", 0.0, 42.0),
    }

    FX_DELAY = {
        "WET":     ("lecholevel", -70.0, 10.0),
        "WET_R":   ("recholevel", -70.0, 10.0),
        "DRY":     ("dryLevel", -70.0, 10.0),
        "DLYTIME": ("ldelay", 0.0, 2000.0),
        "DLYFBK":  ("lfeedback", 0.0, 100.0),
    }

    # label, fraction of a beat
    DELAY_DIVISIONS = (
        ("1/16", 0.25), ("1/8", 0.5), ("3/16", 0.75),
        ("1/4", 1.0), ("3/8", 1.5), ("1/2", 2.0),
    )

    @staticmethod
    def delay_ms(bpm, div_idx):
        """TAP Stereo Echo takes milliseconds, so the driver computes them from
        getTempo() on the display tick - never per encoder event."""
        beat_ms = 60000.0 / max(1e-6, bpm)
        ms = beat_ms * techno_lib.DELAY_DIVISIONS[div_idx][1]
        return min(ms, techno_lib.FX_DELAY["DLYTIME"][2])

    # ------------------------------------------------------------------ pages

    # PAGES is the pass-one name and is kept so an older snapshot's saved page
    # string still validates in set_state(). MODES is what the surface uses.
    PAGES = ("CONTROL", "STEP", "ALL")

    MODES = ("CONTROL", "STEP", "ALL", "MIXER", "FILTER")

    # ------------------------------------------------- button dispatch tables
    #
    # SP10 step 0 / SP9 section 7. The driver's midi_event used to carry these
    # as a chain of `if cc_num == CC_X`. Moving them here buys one thing that
    # matters: a test can prove no two buttons claim the same CC, which is how
    # two bindings were wrong for four days in 2026-08.
    #
    # CC numbers are MEASURED (gate G4, 2026-08-11, aseqdump). The daemon's
    # token names sit on the opposite physical buttons from what they suggest -
    # never re-derive these from the daemon source.
    #
    # MOD lives on SWING (CC 50), NOT on AUTO (CC 37). AUTO is CC_MODE_FILTER
    # today and is only free after FILTER moves into the SPREAD ring - which
    # is the three-focus collapse, and that is deferred. Putting MOD on SWING
    # is what makes the collapse optional instead of a prerequisite.

    # Buttons whose release is also an event: the driver tracks them across
    # press and release, so they are dispatched before the press-only filter.
    BUTTONS_STATEFUL = {
        2: "erase",
        # SCENE and PATTERN, both measured free in the G4 capture and both
        # named right on the panel for what they do. STATEFUL rather than
        # press-only because a reroll is hold-to-fire: the press arms nothing,
        # the RELEASE past the threshold does. Hold-to-fire is already this
        # instrument's law, it is self-cancelling - let go early and nothing
        # happens - and the hold buys a disclosure window for free.
        # Named after the PHYSICAL BUTTONS, not after what they reroll. The
        # mapping was swapped once (owner, 2026-08-19: PATTERN is the better
        # word for drums, SCENE for melody) and handler names that encode the
        # meaning would have had to be renamed with it - or, worse, would not
        # have been, and then lied.
        25: "reroll_scene",
        26: "reroll_pattern",
        3: "rec",
        49: "shift",
        31: "solo",
        50: "mod",              # SWING. Verified free and unreferenced.
        # TEMPO. CC 35 MEASURED 2026-08-16 by aseqdump on the daemon's Pads
        # port - press 127, release 0 - not read off the daemon's token name,
        # which has been wrong twice (DL/DR, and the LED index table). CC 35
        # appears nowhere in the G4 capture: TEMPO was simply never pressed
        # that day, so it was unknown rather than free.
        # Held, it restores the pre-2026-08-16 encoder feel. Every encoder is
        # half as sensitive by default now; see lib.STEP_FACTOR.
        35: "coarse",
        # STEP > , the transport arrow. CC 6 MEASURED at G4 (both edges), LED
        # index 51 MEASURED 2026-08-15, and grep of daemon/src finds nothing
        # acting on it - so it is free on every one of the three counts that
        # matter.
        #
        # HELD, never latched: a beat repeat that latched would be a broken
        # instrument until the player found the button again, and the release
        # is the natural restore trigger.
        6: "repeat",
        # MUTE. CC 33 MEASURED at G4 (both edges), LED index 24 MEASURED
        # 2026-08-15 - the ONE index the daemon had guessed right. Both halves
        # of working rule 7 satisfied, and this is the only feature in four
        # packages that had no blocking measurement at all.
        #
        # Held like SHIFT. A latched mute overlay is state a player can walk
        # away from, and the pads would stop being the step picture until they
        # noticed.
        33: "mute",
        # SELECT. CC 30 MEASURED in notes/findings/2026-08-11-g4-capture.log,
        # LED index 22 MEASURED 2026-08-15 - both halves of working rule 7 are
        # satisfied, and neither was read off the daemon's token name.
        #
        # STATEFUL and HELD, never latched. Deliberately unlike MOD: MOD
        # latches because both hands then go to encoders, while ARM is composed
        # with the pads under the same hand. A latched ARM would leave armed
        # state a player can walk away from and trip four bars later.
        30: "arm",
        # NAVIGATE. CC 34 MEASURED in the G4 runbook, LED index 20 MEASURED
        # 2026-08-16 in the third round of the LED probe - it was carried as
        # "inferred, high" in a stale summary block for four days, which is
        # what blocked this page.
        #
        # Held, never latched: the phrase page is something you glance at
        # mid-bar, and a latched one would hide the step picture until you
        # noticed it had.
        34: "navigate",
        # PAD MODE. CC 27 MEASURED at G4; LED index 19 MEASURED 2026-08-16.
        #
        # SAFE, and that was checked rather than assumed: daemon/src/main.rs
        # gates its own pad_mode handling on `modpress`, its SHIFT state. Bare
        # PAD MODE emits CC 27 and the daemon does nothing else with it.
        # SHIFT + PAD MODE never reaches us at all - the daemon eats it and
        # enters its own sequencer mode - so FREEZE must never be a SHIFT
        # chord on this button.
        27: "freeze",
    }

    # Buttons that act on press only.
    BUTTONS_PRESS = {
        1: "play",
        4: "grid",
        7: "restart",
        13: "sound_prev",
        14: "sound_next",
        # NOTE REPEAT, master section, right of the big encoder. CC 10
        # MEASURED 2026-08-15 by capture, not read off the daemon's token
        # name. It carries the Turing register undo, which used to sit on
        # DUPLICATE (CC 29) - that button is now free surface.
        10: "register_undo",
        47: "page_prev",
        48: "page_next",
    }

    # CCs that belong to something other than a named button. A named button
    # landing on one of these would be swallowed by the range check above it.
    RESERVED_CCS = frozenset(
        list(range(16, 24))          # the eight encoders
        + list(range(39, 47))        # F1..F8
        + list(range(80, 88))        # Groups A..H
        + [11, 32, 38, 51, 37])      # CONTROL, STEP, ALL, MIXER(VOLUME), FILTER(AUTO)

    @staticmethod
    def button_conflicts():
        """Every CC claimed by more than one thing, as readable strings.

        Returns [] when the map is sound. A non-empty list is a surface bug:
        the second claimant is unreachable and there is no runtime symptom."""
        problems = []
        for cc in sorted(set(techno_lib.BUTTONS_STATEFUL)
                         & set(techno_lib.BUTTONS_PRESS)):
            problems.append(f"CC {cc}: stateful and press-only")
        for table, label in ((techno_lib.BUTTONS_STATEFUL, "stateful"),
                             (techno_lib.BUTTONS_PRESS, "press")):
            for cc in sorted(set(table) & techno_lib.RESERVED_CCS):
                problems.append(f"CC {cc}: {label} button on a reserved CC")
        return problems

    # A page's shape decides what encoder n means. This is the whole trick:
    # three layouts, one dispatch.
    #   channel - 8 verbs, one selected channel      (today's CONTROL and STEP)
    #   spread  - 1 verb, all 8 channels             (mixer, filter, swing, chance)
    #   global  - 8 verbs, no channel                (today's ALL)
    SHAPE_CHANNEL = "channel"
    SHAPE_SPREAD = "spread"
    SHAPE_GLOBAL = "global"
    # The audit page. Its columns are whatever is armed right now, so it is
    # the first page whose vocabulary is not fixed - which is why it is a
    # shape of its own rather than a GLOBAL page with rewritten verb names.
    # `verbs` is a static tuple in a page descriptor and four other pages read
    # it as one; making it dynamic for this page alone would put a special
    # case in code they all share.
    SHAPE_PENDING = "pending"

    # Keying is a property of the RING, not of the shapes inside it. A ring is
    # keyed on kind when its content differs by kind. STEP is keyed on kind
    # even though its pages 2 and 3 are spread, because its page 1 is
    # channel-shaped and differs by kind: a mixed ring takes the keying its
    # page 1 requires.
    KEYED_BY_KIND = frozenset({"CONTROL", "STEP"})

    @staticmethod
    def ring_key(mode, kind):
        return (mode, kind if mode in techno_lib.KEYED_BY_KIND else None)

    @staticmethod
    def page_desc(shape, title, verbs=None, verb=None):
        """One page. `verbs` for channel and global shapes, `verb` for spread.
        `title` is what the page indicator draws."""
        return {"shape": shape, "title": title,
                "verbs": tuple(verbs) if verbs is not None else None,
                "verb": verb}

    @staticmethod
    def step_index(index, delta, count):
        """DL / DR move here. Wrapping, because a ring you cannot cycle is a
        list with a dead end at each side."""
        if count <= 0:
            return 0
        return (index + delta) % count

    @staticmethod
    def clamp_index(index, count):
        """A saved or remembered index landing in a shorter ring."""
        if count <= 0:
            return 0
        return max(0, min(count - 1, index))

    # Mirrors maschine_mk2_lib.DIVISIONS and is append-only for the same
    # reason: a snapshot stores the index, not the label.
    DIVISION_LABELS = ("1/32", "1/16", "1/8", "1/16T", "1/8T", "1/4")

    # Steps per beat for each of those, in the same order. Mirrors
    # maschine_mk2_lib.DIVISIONS[i][1] and is checked against it by a test,
    # because two tables that must agree and are not compared will not.
    #
    # NOTE THE ORDER: the table is grouped BY FAMILY, not sorted by speed.
    # 1/32-1/16-1/8 are straight and 1/4 is too, but 1/16T and 1/8T sit
    # BETWEEN them at indices 3 and 4. So `div + 1` from 1/8 lands on 1/16T -
    # faster, and triplet. Never step this table by index.
    DIVISION_SPB = (8, 4, 2, 6, 3, 1)

    # DROP and BREAK are the same mechanism with its ends swapped and they
    # share one capture of the mute picture, so only ONE of them may be live.
    # Arming either cancels the other and its return leg.
    #
    # Mutual exclusion rather than a refcounted shared capture: the entry's
    # own trap is that two of them pending at once can each hold a different
    # idea of the pre-mute state and the second restore undoes the first. A
    # refcount is more expressive - a BREAK inside a DROP becomes meaningful -
    # but it is a second lifetime rule beside the queue's own, and a
    # half-restored mute is exactly the failure being avoided.
    MUTEPATH_MACROS = ("drop", "drop_end", "break", "break_end")

    @staticmethod
    def generated_channels(owners, count=8):
        """Every channel a pattern-rewriting macro may touch.

        ALL EIGHT, minus the player-owned ones - and the skip is not a
        courtesy, it is the ownership rule. These macros regenerate from
        euclid, so on a channel whose notes are a recorded take there is
        nothing to regenerate them from and the take would be gone.

        reroll_scope is the wrong function for this even though it looks
        right: a bare press there means the SELECTED channel and SHIFT means
        one engine type, and neither is "all eight". A macro armed bars in
        advance has no button under the player's finger to read a scope from.
        """
        return tuple(ch for ch in range(count)
                     if owners.get(ch, "gen") != "player")

    @staticmethod
    def scope_label(label, name, moved, asked):
        """Say how many channels a macro actually took.

        A macro that silently did nothing to three of eight channels is the
        unexplained-silence law wearing a different hat. Four of the six
        divisions cannot half-time or cannot double-time at all, so a partial
        result is ORDINARY here rather than exceptional, and the surface has
        to be able to say so without the player counting tabs."""
        if moved == asked:
            return f"{label} {name}"
        return f"{label} {name} {int(moved)}/{int(asked)}"

    @staticmethod
    def time_scale(div_idx, beats, factor):
        """(division, beats) at half or double speed, or None if unreachable.

        `factor` is 0.5 for half-time and 2.0 for double.

        HALF-TIME HALVES STEPS-PER-BEAT AND DOUBLES THE BEAT COUNT. Neither
        half alone is half-time, and the feature entry that said "DIV already
        exists, only the automatic return is new" was wrong twice over:

        - Halving spb with the beat count unchanged gives a COARSER PATTERN OF
          THE SAME DURATION - a different rhythm, not a slower one.
        - Stepping the division by index crosses between the straight and
          triplet families, because DIVISION_SPB is grouped rather than
          sorted.

        Because `beats * spb` is invariant, the step count the sixteen pads
        draw never changes: the transform always fits the grid exactly, the
        regenerated euclid pattern from the unchanged hits/rot is the
        IDENTICAL rhythm, and _clamp_params - which silently truncates beats,
        hits and rot to fit - never fires. Under the naive div-only route it
        would, and a self-returning half-time would quietly halve the
        channel's length every time it was used.

        Returns None rather than approximating. Four edges are genuinely
        unreachable - no spb 16, 12, 1.5 or 0.5 exists - and double-time also
        refuses any beat count it cannot halve into a whole number at or above
        one. A channel that cannot make the move is skipped and SAYS SO; a
        macro that silently did nothing to three of eight channels is the
        unexplained-silence law wearing a different hat."""

        if factor not in (0.5, 2.0):
            return None
        try:
            spb = techno_lib.DIVISION_SPB[int(div_idx)]
        except (IndexError, TypeError, ValueError):
            return None
        beats = int(beats)
        # Half speed needs HALF the steps per beat and TWICE as many beats,
        # which is factor on the spb and its inverse on the count. Getting
        # this pair the wrong way round still round-trips and still preserves
        # the step count, so it passes a careless test while playing the wrong
        # thing - which is why the test asserts the concrete divisions by name
        # rather than only the invariant.
        want_spb = spb * factor
        want_beats = beats / factor
        if want_spb != int(want_spb) or want_beats != int(want_beats):
            return None
        want_spb, want_beats = int(want_spb), int(want_beats)
        if want_beats < 1:
            return None
        # Matched inside the SAME FAMILY. Straight divisions have even spb
        # except 1/4, triplets are 6 and 3 - so a plain spb lookup would map
        # 1/16T (6) down to nothing and up to nothing, which is right, while
        # never offering a straight division to a triplet channel or the
        # reverse. The families do not share an spb value, so equality is
        # enough and no family tag is needed.
        for idx, candidate in enumerate(techno_lib.DIVISION_SPB):
            if candidate == want_spb:
                return (idx, want_beats)
        return None

    @staticmethod
    def _num(v):
        return f"{int(round(v)):04d}"

    # A name-valued column draws in the small font, so it gets nine
    # characters instead of the four a double-height value fits.
    SMALL_VALUE_CHARS = 9

    @staticmethod
    def short_label(name, width):
        """Shorten a name to `width`, keeping the trailing digits.

        Plain truncation throws away the only character that distinguishes
        neighbours in a preset bank, and stepping walks a bank in alphabetical
        order, so the collisions are always adjacent. Measured on the rig
        2026-08-16: of the 67 padthv1 patches on group H, 48 shared a
        four-character label with a neighbour - Dusk, Dusk2 ... Dusk6 all drew
        as "Dusk". The player pressed the button six times, saw one word,
        heard six variants of one pad, and reported the button as broken.

        Nine characters plus this rule gives all 67 a distinct label; nine
        alone still collides on sixteen of them."""

        text = "" if name is None else str(name)
        if width <= 0:
            return ""
        if len(text) <= width:
            return text
        match = re.search(r"\d+$", text)
        tail = match.group(0) if match else ""
        # A digit run longer than half the budget IS the name (Randomize01
        # style is fine; "A123456789012" is not) - keeping it would return
        # mostly digits and lose what the reader actually recognises.
        if len(tail) > width // 2:
            tail = ""
        return text[:width - len(tail)] + tail

    @staticmethod
    def _col(name, value, bar=None, frac=0.0, grey=False, pending=False,
             small=False):
        # No `mod` parameter: the tilde and the span are stamped afterwards by
        # mark_modulated(), which is the one path production uses. A second
        # copy of that logic here was used by nothing but its own tests.
        if small:
            # Shorten BEFORE the brackets go on. The other order either
            # overflows the column or cuts the closing bracket off, and the
            # bracket is the whole signal that a load is still pending.
            budget = techno_lib.SMALL_VALUE_CHARS - (2 if pending else 0)
            value = techno_lib.short_label(value, budget)
        if pending:
            value = f">{value}<"
        return {"name": name, "value": value, "bar": bar, "frac": frac,
                "grey": grey, "pending": pending, "mod": None, "small": small}

    @staticmethod
    def _dead(name):
        """Law L4: a column whose source does not exist draws lower-case, shows
        ---- , carries no bar, and its encoder does nothing. A knob that does
        nothing and does not admit it is the worst object on a control surface."""
        return techno_lib._col(name, "----", None, 0.0, grey=True)

    # verb -> (bar kind, value -> 0..1 fraction). The formulas are lifted
    # verbatim from the shipped channel pages so a parameter looks identical
    # whichever shape shows it.
    SPREAD_SPECS = {
        "level":  ("uni", lambda v: v / 100.0),
        "reverb": ("uni", lambda v: v / 100.0),
        "delay":  ("uni", lambda v: v / 100.0),
        "chance": ("uni", lambda v: v / 100.0),
        "rhythm": ("uni", lambda v: v / 100.0),
        "swing":  ("uni", lambda v: (v - 50) / 25.0),
        "cutoff": ("uni", lambda v: v / 127.0),
        "reso":   ("uni", lambda v: v / 127.0),
    }

    @staticmethod
    def page_label(title, index, count):
        """What the indicator row draws. A one-page ring says only its name -
        showing 1/1 on a ring that cannot move is noise."""
        return title if count <= 1 else f"{title} {index + 1}/{count}"

    @staticmethod
    def quantise_frac(frac, steps):
        """Snap a bar fraction to the bar's real pixel resolution BEFORE the
        change comparison in _render_display. Without this a live meter
        reports a new value every frame and mixer mode repaints forever."""
        frac = max(0.0, min(1.0, float(frac)))
        if steps <= 0:
            return frac
        return round(frac * steps) / steps

    # ---------------------------------------------------------- modulation
    #
    # SP10 step 1. A modulator is (depth, rate, shape, phase0, base, seed)
    # against one verb on one channel. Everything below is pure: the driver
    # owns the store and the clock, this owns the shape of the motion.

    MOD_SHAPES = ("tri", "ramp", "squ", "s&h")

    # Bars per cycle, slowest first. TWELVE, not sixteen: the sixteen pads
    # carry twelve rates (pads 0-11) and four shapes (pads 12-15), and an
    # entry no pad can reach is a table that lies about the surface.
    #
    # Bar-synced rather than free-running so a modulator lines up with the
    # pattern it is colouring - this instrument already lands structure on
    # the bar everywhere else.
    MOD_RATES = (16.0, 8.0, 6.0, 4.0, 3.0, 2.0,
                 1.0, 0.75, 0.5, 0.25, 0.125, 0.0625)

    # Verbs an LFO may drive. This set contains ONLY verbs that do not rewrite
    # a pattern: each one lands on a mixer strip or a plugin port, where a
    # change is allowed to arrive instantly and costs nothing but a
    # set_value(). Everything else rewrites the pattern, and an LFO on a
    # pattern rewrite thrashes zynseq under a lock.
    #
    # GATE and VELO were in this set and are OUT. They read as timbre - note
    # length and note loudness - but on this instrument they are written by
    # regenerating the whole pattern (_apply_generator/_write_pattern: a
    # clear() plus an addNote loop). An LFO on VELO fired that rewrite every
    # 200 ms forever, and on a player-owned DRUM channel the generator's drum
    # branch has no ownership check, so it destroyed the recorded take over
    # and over with nobody touching the panel.
    #
    # HITS, ROTATE, DENSITY and CHANCE are absent for the same structural
    # reason plus one more: they are the bar-rate DRIFT targets, and drift
    # does not ship until the SP2 ownership rule is settled.
    MOD_TIMBRE = frozenset({
        "level", "reverb", "delay", "cutoff", "reso", "env", "decay"})

    # Depth is a signed percentage. 100 sweeps half the verb's range each way,
    # so a centred base at full depth reaches both end stops and no further.
    MOD_DEPTH_MAX = 100

    # DRIFT: the pattern verbs a modulator may drive, applied at the WRAP.
    #
    # The 2026-08-14 spec named HITS / ROTATE / DENSITY / CHANCE. DENSITY no
    # longer exists - the rhythm generator replaced it on 2026-08-16 - so it is
    # dropped rather than resurrected. LENGTH and DIV stay out of v1: they are
    # handback verbs too, but they change the pattern's STRUCTURE, land on the
    # bar through `pending` and rescale note positions, so drifting them means a
    # bar whose length changes under the player. Different feature.
    DRIFT_VERBS = frozenset({"hits", "rotate", "chance"})

    @staticmethod
    def is_drift(verb):
        """True when this verb rewrites the PATTERN and so must be applied at
        the wrap rather than on the 200 ms modulator tick.

        Writing one every 200 ms means clear() plus an addNote loop under the
        lock, five times a second, forever - which IS the `velo` defect that
        destroyed a recorded take unattended in v1."""
        return verb in techno_lib.DRIFT_VERBS

    @staticmethod
    def mod_allowed(verb, owned=False):
        """True when MOD may bind a modulator to this verb on this channel.

        A refused verb is drawn dead (law L4) rather than silently ignoring
        the gesture - a knob that does nothing without saying so is the one
        thing this surface must never do.

        `owned` is whether the PLAYER owns this channel's pattern. It matters
        only for drift: those verbs rewrite the pattern, and rewriting it with
        no hands on the panel is exactly how a recorded take gets erased. Drift
        refuses there and is drawn dead - owner's confirmed rule, 2026-08-19,
        the simplest one that cannot destroy a take. Timbre verbs do not
        rewrite anything, so ownership is irrelevant to them.

        Defaults to unowned so every existing caller keeps its meaning."""
        if not verb:
            return False
        if verb.startswith(techno_lib.VERB_LV2) or verb.startswith(techno_lib.VERB_FX):
            return True
        if verb in techno_lib.DRIFT_VERBS:
            return not owned
        return verb in techno_lib.MOD_TIMBRE

    @staticmethod
    def mod_is_global(verb):
        """True when a modulator on this verb addresses ONE object however
        many channels exist, so its key must not carry a channel.

        `fx:` verbs do: the driver resolves them through fx_handle(0, which) -
        a single insert, ganged across every channel - so keying one by the
        selected group hid its tilde and its span the moment the group
        changed, and let a second modulator be bound to the same port to fight
        the first. `lv2:` verbs do NOT: they address the selected channel's
        own synth processor and stay per channel."""
        return bool(verb) and verb.startswith(techno_lib.VERB_FX)

    @staticmethod
    def mod_pos(phase0, elapsed_beats, rate_bars, beats_per_bar=4):
        """Unwrapped position in cycles: the integer part is the cycle count
        (which sample-and-hold needs) and the fraction is the phase.

        Driven by BEATS, not seconds, so every modulator follows the tempo
        without being told the tempo changed."""
        span = float(rate_bars) * float(beats_per_bar)
        if span <= 0.0:
            return float(phase0)
        return float(phase0) + float(elapsed_beats) / span

    @staticmethod
    def phrase_pos(elapsed_beats, anchor_beats, beats_per_bar=4):
        """Bars since the anchor as (bar_index, fraction through that bar).

        Anchored to the TRANSPORT rather than to any channel's own length:
        each channel owns its length, and a polymetric rig has eight
        different bars. One channel-derived count would be a lie on seven of
        them. Derived from beats rather than seconds so it follows a tempo
        change without being told about it.

        Clamps at zero: the anchor is set on transport start, and a poll that
        lands a hair before it must read bar 0, not bar -1."""
        span = float(beats_per_bar)
        if span <= 0.0:
            return (0, 0.0)
        delta = float(elapsed_beats) - float(anchor_beats)
        if delta <= 0.0:
            return (0, 0.0)
        bars = delta / span
        index = int(bars)
        return (index, bars - index)

    @staticmethod
    def phrase_bar(bar_index, phrase_bars=16):
        """Which bar of the phrase, 0..phrase_bars-1."""
        if phrase_bars <= 0:
            return 0
        return int(bar_index) % int(phrase_bars)

    @staticmethod
    def mod_sh(seed, cycle):
        """Deterministic sample-and-hold in -1.0..1.0.

        The same (seed, cycle) always gives the same value, so a saved jam
        reloads sounding identical. A random() here would make the snapshot a
        lie, which is exactly the CHANCE/SWING mistake of 2026-08-11."""
        h = (int(seed) * 6364136223846793005
             + int(cycle) * 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        h ^= h >> 33
        h = (h * 0xFF51AFD7ED558CCD) & 0xFFFFFFFFFFFFFFFF
        h ^= h >> 33
        return (h / float(0xFFFFFFFFFFFFFFFF)) * 2.0 - 1.0

    # The position a FINISHED one-shot is evaluated at. Not 1.0, and the
    # reason is a real trap: mod_wave takes pos % 1.0, and 1.0 % 1.0 is 0.0 -
    # so passing the endpoint straight through would put a completed ramp at
    # its MINIMUM, which is the exact opposite of landing on the downbeat.
    MOD_ONCE_END = 0.999999

    @staticmethod
    def mod_once_pos(phase0, elapsed_beats, rate_bars, beats_per_bar=4):
        """A ONE-SHOT position: 0.0 to 1.0, then held there forever.

        The only difference from mod_pos is the clamp, and the clamp is the
        whole feature. mod_pos returns an UNWRAPPED cycle count because
        sample-and-hold needs the integer part; a riser must instead arrive
        and STAY, or it snaps back to the bottom on the downbeat it was built
        to land on.

        `phase0` is normally NEGATIVE here - _arm_once stores minus the
        elapsed position at the moment of arming, so the sweep starts when the
        player asked for it rather than when the driver booted.

        Do not feed the return value straight to mod_wave at the endpoint:
        see MOD_ONCE_END."""

        span = float(rate_bars) * float(beats_per_bar)
        if span <= 0.0:
            return 1.0
        pos = float(phase0) + float(elapsed_beats) / span
        return max(0.0, min(1.0, pos))

    @staticmethod
    def mod_wave(shape, pos, seed=0):
        """The modulator's output at `pos`, bipolar -1.0..1.0."""
        p = float(pos) % 1.0
        if shape == "tri":
            return 4.0 * p - 1.0 if p < 0.5 else 3.0 - 4.0 * p
        if shape == "ramp":
            return 2.0 * p - 1.0
        if shape == "squ":
            return 1.0 if p < 0.5 else -1.0
        if shape == "s&h":
            return techno_lib.mod_sh(seed, int(float(pos) // 1))
        return 0.0

    @staticmethod
    def mod_value(base, wave, depth, lo, hi):
        """`base` displaced by `wave` at `depth`, clamped to the verb's range.

        The BASE is the driver's own truth and is never read back from the
        plugin: an LFO caught mid-sweep would otherwise write its own position
        into the snapshot and the knob would have nothing to return to."""
        half = (float(hi) - float(lo)) / 2.0
        out = float(base) + float(wave) * (float(depth) / 100.0) * half
        return max(float(lo), min(float(hi), out))

    @staticmethod
    def mod_depth_scale(depth, mult):
        """`depth` scaled by the global multiplier, sign preserved.

        THIS IS A VIEW, NOT AN EDIT. The multiplier is stored separately and
        the stored depths are never multiplied in place: 0 x anything = 0
        would strand every modulator at zero with no way back, which is the
        base/offset lesson wearing a new hat.

        The multiplier floors at zero. A negative one would invert every
        modulator at once - a gesture nobody asked for, reachable by turning
        one knob too far."""
        return float(depth) * max(0.0, float(mult))

    @staticmethod
    def mod_span(base, depth, lo, hi):
        """(low, high) as bar fractions 0..1 - the dashed span the indicator
        bar draws to say a value is moving on its own."""
        half = (float(hi) - float(lo)) / 2.0
        reach = abs(float(depth) / 100.0) * half
        a = max(float(lo), min(float(hi), float(base) - reach))
        b = max(float(lo), min(float(hi), float(base) + reach))
        width = float(hi) - float(lo)
        if width <= 0.0:
            return (0.0, 0.0)
        return ((a - float(lo)) / width, (b - float(lo)) / width)

    @staticmethod
    def mod_base_or(mods, key, value):
        """`value`, unless `key` has a live entry in `mods`, in which case
        that entry's base instead.

        Pure, so the substitution rule is unit tested here rather than only
        through the driver's untestable state_view()/_generated_view(). The
        driver's job is only to build `key` (its own (channel, verb) shape,
        via _mod_key) and hand over its own self.mod - never to decide the
        substitution itself. This is what keeps a modulated verb's display
        reading the base the knob is set to, never the live value the LFO
        just swept it to; _mod_write() still writes the swept value to the
        engine untouched."""
        entry = mods.get(key)
        return value if entry is None else entry["base"]

    @staticmethod
    def mod_steer(mods, key, current, delta, lo, hi):
        """Where an encoder turn on a possibly-modulated verb lands.

        Returns (value, to_base). `to_base` True means the number belongs in
        the modulator's own `base` field and must NOT be written to the engine
        here - the modulator's own tick writes base+offset on its own.

        This is the whole of the rule, and it lives here because the driver
        cannot be imported off the Pi. Without it the knob is dead: _mod_write
        stores base+offset into self.state / the mixer, so reading `current`
        back from there hands the encoder the LFO's own output, and the turn
        is overwritten inside 200 ms.

        Returns (None, False) when there is nothing to steer, so the caller's
        existing "no readable source" path is unchanged."""
        entry = mods.get(key)
        base = current if entry is None else entry.get("base")
        if base is None:
            return (None, False)
        value = min(hi, max(lo, base + delta))
        return (value, entry is not None)

    @staticmethod
    def mark_modulated(col, span):
        """Stamp an already-built column as modulated.

        Applied after columns() rather than threaded through it: columns()
        fans out to three builders, and none of them should have to know what
        a modulator is. Returns the column unchanged when span is None, so the
        caller can apply it blindly."""
        if span is None or col.get("grey"):
            # A dead column stays dead - law L4 outranks a modulator that
            # should not have been bindable there in the first place.
            return col
        out = dict(col)
        out["name"] = col["name"][:techno_lib.NAME_CHARS - 1] + "~"
        out["mod"] = span
        return out

    # Generated pages address a plugin port directly, so their verb names carry
    # a prefix the driver's _verb() dispatches on:
    #   lv2:<symbol>          - the selected channel's synth processor
    #   fx:<which>:<symbol>   - ganged across every channel's <which> insert
    VERB_LV2 = "lv2:"
    VERB_FX = "fx:"

    # The insert families an `fx:` verb can name, and whether one knob moves
    # ONE object or eight. reverb and delay sit on all eight chains, so a knob
    # there writes eight times; MAIN is a single processor on chain 0, so it
    # writes once.
    #
    # A predicate rather than an `if which == "main"` at each call site: there
    # are seven `fx:`-keyed sites and the eighth would forget.
    FX_GANGED = frozenset(("reverb", "delay"))
    FX_MAIN = "main"

    @staticmethod
    def fx_is_ganged(which):
        """Does one turn of this knob write to all eight chains?"""
        return which in techno_lib.FX_GANGED

    PORT_LABEL_CHARS = 8

    NAME_CHARS = 8           # what fits in a column's 5x8 name row

    # Note duration is gate/100, measured in STEPS. The old cap of 100 meant a
    # note could never outlast one step, so at the slowest division no note in
    # this instrument could exceed an eighth note - which is why pads played
    # stabs. The library never had this limit; only this driver's range did.
    GATE_MAX = 800

    @staticmethod
    def port_label(symbol):
        """LV2 symbols are not written for a 64 px column. Upper-case, drop a
        leading underscore, truncate."""
        return str(symbol).lstrip("_").upper()[:techno_lib.PORT_LABEL_CHARS]

    # Ports the host publishes that no player can use. Found on hardware
    # 2026-08-11: Obxd exposes lv2_freewheel (drawn as LV2_FREE), lv2_port_1
    # and unused_1; JC303 exposes latency, freeWheeling and enabled. Each one
    # took a column and did nothing.
    #
    # Matched exactly and case-insensitively, plus two prefixes. Exact matching
    # is the whole trick: it drops JC303's "enabled" while keeping padthv1's
    # DCF1_ENABLED and LFO1_ENABLED, which are genuine section switches.
    PORT_DENY = frozenset({
        "latency", "enabled", "bypass", "freewheel", "freewheeling"})
    PORT_DENY_PREFIXES = ("lv2_", "unused")

    # Below this span, one percent of a port's range is less than one unit.
    PORT_PERCENT_FLOOR = 100.0

    @staticmethod
    def port_is_discrete(lo, hi, is_integer):
        """True when a port must be stepped in whole units, not percentages.

        Two conditions, and BOTH are needed. zynthian_controller._set_value()
        truncates INTEGER controls, so a fractional step on one is a knob that
        never moves; and the step is fractional only when one percent of the
        range is smaller than one unit. TAP Reverberator's combs_en (integer,
        0-1) was dead for exactly this reason, while a 0.0-1.0 float volume is
        perfectly drivable as a percentage - which is why range width alone is
        the wrong question."""
        if not is_integer:
            return False
        return (hi - lo) < techno_lib.PORT_PERCENT_FLOOR

    @staticmethod
    def step_port_value(value, lo, hi, delta):
        """Move a discrete port by whole units, clamped to its own range."""
        return max(lo, min(hi, value + delta))

    # --- generated page labels -------------------------------------------
    #
    # A plugin port's name does not fit one row. PITCH_BEND_RANGE and
    # PITCH_BEND_STEP both truncate to "PITCH_BE", and MOD_WHEEL_RANGE and
    # MOD_WHEEL_ASSIGN both to "MOD_WHEE" - two adjacent columns drawing the
    # same word, which is no name at all. Owner, 2026-08-19, at the rig.
    #
    # The tab row above the columns carries the channel names, and on a
    # GENERATED page nobody needs them there: the page is one channel's own
    # plugin, the selected channel is on the group buttons, and the pages that
    # explain silence are the ones this is not. So the tab row and the name
    # row are used as ONE field two lines deep, and the name is wrapped over
    # both - sixteen characters instead of eight.

    TAB_LABEL_CHARS = 8      # matches maschine_mk2_lib.TAB_CHARS

    @staticmethod
    def wrap_label(text, width=None):
        """(line 1, line 2) for a parameter name spread over the tab row and
        the name row.

        Breaks on spaces and underscores first, because "MOD_WHEEL / ASSIGN"
        reads and "MOD_WHEE / L_ASSIGN" does not. A single word longer than
        the row is hard-split - there is nothing better to do with
        OSCILLATORSYNC, and half a word is still more than none.

        Anything past two rows is dropped: the third line has nowhere to go."""
        width = techno_lib.TAB_LABEL_CHARS if width is None else width
        text = "" if text is None else str(text).strip()
        if not text or width <= 0:
            return ("", "")
        if len(text) <= width:
            return (text, "")
        # Underscores are word breaks that also take up a character; spaces
        # are word breaks that do not survive the wrap.
        words, current = [], ""
        for ch in text:
            current += ch
            if ch in " _":
                words.append(current)
                current = ""
        if current:
            words.append(current)
        lines, line = [], ""
        for word in words:
            candidate = line + word
            if len(candidate.rstrip()) <= width:
                line = candidate
                continue
            if line:
                lines.append(line.rstrip())
                line = ""
            while len(word.rstrip()) > width:
                lines.append(word[:width])
                word = word[width:]
            line = word
        if line:
            lines.append(line.rstrip())
        lines = [text[:width], text[width:width * 2]] if not lines else lines
        return (lines[0][:width], (lines[1][:width] if len(lines) > 1 else ""))

    @staticmethod
    def generated_tabs(labels):
        """Four tab tuples for one screen of a generated page.

        Same shape screen_packets already takes - (letter, name, selected,
        muted, armed) - with no letter and every flag off: a parameter name is
        not a channel, so none of the channel styles apply to it. Plain
        outlined boxes with a word in them."""
        out = []
        for label in labels:
            out.append(("", label, False, False, False))
        return tuple(out)

    # --- switches -------------------------------------------------------
    #
    # A plugin publishes three kinds of control and Zynthian has parsed all
    # three before the driver sees them: continuous, ENUMERATED (scale_points
    # become labels + ticks) and TOGGLE (is_toggled becomes labels
    # ['off','on']). This driver read none of it until 2026-08-19, so a filter
    # type drew as 0040 where the plugin had the word LP24, and a two-state
    # port was a knob you turned between two values.
    #
    # A switch is drawn with the vocabulary the surface already has: the word
    # in the small font, and a "seg" bar at (index, count) - two positions
    # fill it empty or full, more positions fill it left to right.

    SWITCH_LABEL_CHARS = SMALL_VALUE_CHARS      # a switch value is a word

    # What the F row means, as a table rather than as a condition spread
    # through the driver. Three answers, and the driver's _switch_row() is the
    # only caller - so the LED painter and the button handler ask one question
    # once.
    F_ROW_MUTE = "mute"        # mute, or solo while SOLO is held or latched
    F_ROW_SWITCH = "switch"    # the CONTROL page's switches, one per column
    F_ROW_INERT = "inert"      # dark and doing nothing

    @staticmethod
    def f_row_kind(mode, shift, soloing, mod):
        """Whether F1-F8 are mutes, switches, or nothing at all.

        Only CONTROL gives the row away, and only unmodified: SHIFT + Fn hands
        mute back inside CONTROL, and SOLO + Fn is solo there exactly as it is
        in every other mode. Mute is a control a player reaches for without
        looking, so it stays one modifier away rather than being unreachable.

        MOD makes the row INERT rather than leaving it as switches: MOD makes
        the pads inert and repurposes every encoder, and a parameter switch
        firing inside a bind gesture would be a surprise from a gesture that
        is supposed to change nothing."""
        if mode != "CONTROL" or shift or soloing:
            return techno_lib.F_ROW_MUTE
        if mod:
            return techno_lib.F_ROW_INERT
        return techno_lib.F_ROW_SWITCH

    @staticmethod
    def switch_spec(labels, ticks):
        """(labels, ticks) as parallel tuples when a port is a SWITCH, else None.

        A switch is a port carrying at least two labels with a tick each -
        exactly what zynthian_controller._configure() builds for an enumerated
        or toggled port. One label is a TRIGGER, not a switch: firing a
        one-shot off a mute button is a different feature and is refused here
        rather than half-supported.

        Truncates to the shorter of the two rather than trusting them to be
        parallel. Upstream always builds them together, but a column that
        indexes past the end of one of them would take the whole render down,
        and the render runs on the poll thread."""
        if not labels or not ticks:
            return None
        count = min(len(labels), len(ticks))
        if count < 2:
            return None
        return (tuple(labels[:count]), tuple(ticks[:count]))

    @staticmethod
    def switch_index(value, ticks, labels=()):
        """Which position `value` is at: the NEAREST tick.

        Ticks are not necessarily evenly spaced and not necessarily ascending
        (zynthian_controller sets range_reversed for a descending scale), so
        this scans all of them instead of assuming an order. A tie goes to the
        lower index.

        `value` may be a LABEL: zynthian_controller accepts a string and
        converts it, and jalv seeds a toggle with 'off' / 'on', so the very
        first read of a port can be a word."""
        if isinstance(value, str):
            for index, label in enumerate(labels):
                if str(label) == value:
                    return index
            return 0
        best, best_dist = 0, None
        for index, tick in enumerate(ticks):
            try:
                dist = abs(float(tick) - float(value))
            except (TypeError, ValueError):
                continue
            if best_dist is None or dist < best_dist:
                best, best_dist = index, dist
        return best

    @staticmethod
    def switch_next(index, count, delta=1):
        """Where a BUTTON press lands: wrapping. One button has to reach every
        position, and a switch that stops at the end is a button that does
        nothing on its last press."""
        if count <= 0:
            return 0
        return (index + delta) % count

    @staticmethod
    def switch_step(index, count, delta):
        """Where an ENCODER turn lands: clamped. The knob and the button
        deliberately differ - a knob that wrapped would jump from the last
        position to the first on a single detent, which no hardware knob on
        this surface does."""
        if count <= 0:
            return 0
        return max(0, min(count - 1, index + delta))

    @staticmethod
    def switch_label(label):
        """The plugin's own word, in the budget the small font gives.

        Case is left as the plugin wrote it: 'LP24' and 'saw' are how the
        reader will see them in every other editor, and upper-casing them
        loses a distinction some plugins make."""
        return techno_lib.short_label(
            "" if label is None else str(label),
            techno_lib.SWITCH_LABEL_CHARS)

    @staticmethod
    def usable_ports(ports, exclude=()):
        """Numeric ports with a real range, minus the ones that already have a
        home on a hand-written page and the ones the host publishes for itself.
        Order is the plugin's own."""
        out = []
        for symbol, lo, hi in ports:
            if symbol in exclude:
                continue
            name = str(symbol).lower()
            if name in techno_lib.PORT_DENY:
                continue
            if name.startswith(techno_lib.PORT_DENY_PREFIXES):
                continue
            if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
                continue
            if hi <= lo:
                continue
            out.append((symbol, float(lo), float(hi)))
        return out

    @staticmethod
    def generated_pages(ports, exclude, shape, verb_prefix, title):
        """Chunk a plugin's remaining ports into pages of eight.

        Generated rather than tabulated because the requirement is 'as much
        parameter control as possible' and no table here can know what JC303,
        Obxd, padthv1 or TAP Reverberator publish. A generated ring also
        survives an engine change."""
        usable = techno_lib.usable_ports(ports, exclude)
        if not usable:
            return ()
        chunks = [usable[i:i + 8] for i in range(0, len(usable), 8)]
        pages = []
        for index, chunk in enumerate(chunks):
            verbs = [verb_prefix + symbol for symbol, _, _ in chunk]
            verbs += [None] * (8 - len(verbs))
            name = title if len(chunks) == 1 else f"{title}{index + 1}"
            desc = techno_lib.page_desc(shape, name, verbs=verbs)
            desc["generated"] = True
            pages.append(desc)
        return tuple(pages)

    # What the PENDING page calls a macro. Kept apart from ARM_MACROS on
    # purpose: that tuple is append-only because a snapshot stores its
    # indices, while these are display words and may be reworded freely.
    PENDING_NAMES = {
        "drop": "DROP",
        "drop_end": "UNDROP",
        "chance": "THIN",
        "break": "BREAK",
        "break_end": "UNBREAK",
        "half": "HALF",
        "double": "DOUBLE",
        "timescale_end": "RETURN",
        "ratchet": "ROLL",
        "ratchet_end": "UNROLL",
    }

    @staticmethod
    def pending_sort(entries):
        """Armed macros, soonest first, ties broken by name.

        A page whose columns reorder as the countdown runs is unreadable at a
        glance. This key only changes when something actually overtakes
        something else, which is a real event worth seeing."""
        return sorted(entries, key=lambda e: (int(e[1]), str(e[0])))

    @staticmethod
    def pending_columns(entries):
        """The eight columns of the PENDING page.

        `entries` is (macro, bars_left, armed_bars) per armed macro. Eight
        columns because the surface has eight; a ninth armed macro is not
        drawn, and nothing in this instrument can arm nine.

        WITH NOTHING ARMED THE PAGE SAYS `NONE`. Eight blank columns admit
        nothing, and law L4 is about controls that do nothing and do not say
        so - a page is the same object as a knob in that respect. It is the
        whole reason this page exists: package 1 shipped four armable things
        and no way to see or cancel any one of them."""

        rows = techno_lib.pending_sort(entries)[:8]
        out = []
        for macro, left, armed in rows:
            name = techno_lib.PENDING_NAMES.get(macro, str(macro).upper()[:4])
            armed = max(1, int(armed))
            left = max(0, min(armed, int(left)))
            # A seg bar counting DOWN, so the ink on the glass shrinks as the
            # bars run out. The same direction as ARM's pad ruler, because two
            # countdowns that ran opposite ways would be worse than one.
            # A PLAIN fraction, not a "seg" bar. seg divides by (count - 1),
            # so a full ruler - left == armed - gives a fraction ABOVE 1.0 and
            # draws past its own box. The countdown is a continuous quantity
            # anyway; seg is for a switch with named positions.
            out.append(techno_lib._col(
                name, f"{int(left):04d}", "uni",
                max(0.0, min(1.0, left / float(armed)))))
        if not out:
            out.append(techno_lib._col("NONE", "----", None, 0.0, grey=True))
        while len(out) < 8:
            out.append(techno_lib._col("", "", None, 0.0))
        return out

    @staticmethod
    def generated_columns(desc, state):
        """Columns for a generated page. The surface value is 0-100; the driver
        scales it onto each port's own range, as _set_ganged() already does for
        the hand-written FX roles.

        A port that is a SWITCH is the exception: state["switch"] carries
        (index, count, label) for it, and the column draws the plugin's own
        word over a "seg" bar instead of a number over a fill. The driver
        builds that entry because only it can see a live zynthian_controller;
        which columns it changes is decided here, where it is tested."""
        switches = state.get("switch") or {}
        names = state.get("names") or {}
        out = []
        for verb in desc["verbs"]:
            if verb is None:
                out.append(techno_lib._col("", "", None, 0.0))
                continue
            symbol = verb.split(":")[-1]
            # The name row is the SECOND line of the wrapped parameter name;
            # the first line is in the tab box above it. With no name to wrap
            # - a chain that answered nothing - it falls back to the symbol
            # abbreviation this page drew before names existed.
            label = techno_lib.port_label(symbol)
            if verb in names:
                label = techno_lib.wrap_label(names[verb])[1]
            value = state.get(verb)
            if value is None:
                out.append(techno_lib._dead(
                    (label or techno_lib.port_label(symbol)).lower()))
                continue
            switch = switches.get(verb)
            if switch is not None:
                index, count, word = switch
                out.append(techno_lib._col(
                    label, techno_lib.switch_label(word), "seg",
                    (index, count), small=True))
                continue
            out.append(techno_lib._col(label, techno_lib._num(value), "uni",
                                       value / 100.0))
        return out

    @staticmethod
    def spread_columns(desc, views):
        """One verb across eight channels. `views` is eight
        (letter, name, view) tuples in channel order."""
        verb = desc["verb"]
        kind, to_frac = techno_lib.SPREAD_SPECS[verb]
        out = []
        for letter, name, view in views:
            label = f"{letter} {name}"[:8]
            value = view.get(verb)
            if value is None:
                # Law L4 again: a column whose source does not exist draws
                # dead rather than drawing a lie.
                out.append(techno_lib._dead(label.lower()))
                continue
            out.append(techno_lib._col(label, techno_lib._num(value), kind,
                                       to_frac(value)))
        return out

    @staticmethod
    def columns(desc, kind, state, mod=False, owned=False, frozen=False):
        """The 8 columns for a page, with MOD's refusals drawn.

        `mod` is whether MOD is down. While it is, a column whose verb cannot
        take a modulator LOSES ITS BAR and keeps everything else, so the rule
        under MOD reads: a bar means you can bind here.

        This is why binding "sometimes worked and sometimes did not".
        _mod_encoder's docstring claimed a refused verb draws dead; only the
        "does nothing" half was ever implemented, so under MOD the HITS column
        looked exactly like the LEVEL column and one of them worked. The
        refusal now comes from ONE predicate rather than two lists someone
        keeps in sync: _column_dead() reads the same `grey` flag this sets,
        through the same _page_columns(), so the painter and the bind's gate 2
        agree by construction. Adding an eighth modulatable verb later touches
        one frozenset."""

        return techno_lib._freeze_grey(
            techno_lib._mod_grey(
                techno_lib._columns_inner(desc, kind, state), desc, mod, owned),
            desc, frozen)

    # The verbs a FREEZE makes inert. Only the two that DRIVE generation -
    # everything else on a page is a value the player may still want to move
    # while the machine is held, and greying them would say the instrument had
    # stopped rather than that it was holding still.
    FREEZE_VERBS = frozenset(("random", "rhythm"))

    @staticmethod
    def _freeze_grey(cols, desc, frozen):
        """Strip the bar off the generative columns while FREEZE is on.

        The same grammar MOD already established for "this control cannot act
        right now", reused rather than invented - a second look for the same
        idea is a second thing to learn. The VALUE stays, because it is still
        the value that will resume the moment the machine thaws.

        An already-dead column is left alone: FREEZE must not invent a second
        appearance for "no source at all"."""

        if not frozen:
            return cols
        verbs = desc.get("verbs") or ()
        out = []
        for index, col in enumerate(cols):
            verb = verbs[index] if index < len(verbs) else None
            if verb in techno_lib.FREEZE_VERBS and not col.get("grey"):
                col = dict(col)
                col["bar"] = None
            out.append(col)
        return out

    @staticmethod
    def _mod_grey(cols, desc, mod, owned=False):
        """Strip the bar off every column MOD would refuse.

        The value stays: it is a live parameter that simply cannot be
        modulated, and blanking it would put ---- across most of a latched
        page. An already-dead column is left exactly as it is - MOD must not
        invent a second look for "no source at all", which is visible with MOD
        released anyway."""

        if not mod:
            return cols
        spread = desc.get("shape") == techno_lib.SHAPE_SPREAD
        verbs = desc.get("verbs") or ()
        out = []
        for index, col in enumerate(cols):
            verb = desc.get("verb") if spread else (
                verbs[index] if index < len(verbs) else None)
            if col.get("grey") or techno_lib.mod_allowed(verb, owned):
                out.append(col)
                continue
            refused = dict(col)
            refused["bar"] = None
            refused["frac"] = 0.0
            refused["grey"] = True
            out.append(refused)
        return out

    @staticmethod
    def _columns_inner(desc, kind, state):
        """The 8 columns for a page. Reads state, never writes it. This is the
        single place where the greyed columns and the pending brackets are
        decided, so both are unit tested rather than eyeballed on hardware.

        `desc` is a page descriptor. For SHAPE_SPREAD, `state` is eight
        (letter, name, view) tuples; for the other two shapes it is one view
        dict, as it has always been."""
        if desc["shape"] == techno_lib.SHAPE_SPREAD:
            return techno_lib.spread_columns(desc, state)
        if desc["shape"] == techno_lib.SHAPE_PENDING:
            return techno_lib.pending_columns(state)
        if desc.get("generated"):
            return techno_lib.generated_columns(desc, state)

        page = desc["title"]
        p = state.get("pending", set())
        n, c, dead = techno_lib._num, techno_lib._col, techno_lib._dead

        if desc["shape"] == techno_lib.SHAPE_GLOBAL:
            return [
                c("ROOT", techno_lib.NOTE_NAMES[state["root"]], "seg",
                  (state["root"], 12), pending="root" in p),
                c("SCALE", techno_lib.SCALES[state["scale"]][0], "seg",
                  (state["scale"], len(techno_lib.SCALES)), pending="scale" in p),
                c("BPM", n(state["bpm"]), "uni", (state["bpm"] - 60) / 140.0),
                c("MASTER", n(state["master"]), "uni", state["master"] / 100.0),
                c("REVSIZE", n(state["revsize"]), "uni", state["revsize"] / 100.0),
                c("REVTYPE", n(state["revtype"]), "seg", (state["revtype"], 43)),
                c("DLYTIME", techno_lib.DELAY_DIVISIONS[state["dlytime"]][0], "seg",
                  (state["dlytime"], len(techno_lib.DELAY_DIVISIONS))),
                c("DLYFBK", n(state["dlyfbk"]), "uni", state["dlyfbk"] / 100.0),
            ]

        if page == "CTRL":
            tail = [
                c("LEVEL", n(state["level"]), "uni", state["level"] / 100.0),
                c("REVERB", n(state["reverb"]), "uni", state["reverb"] / 100.0),
                c("DELAY", n(state["delay"]), "uni", state["delay"] / 100.0),
            ]
            if kind == "drum":
                return [
                    c("KIT", state["kit"], "seg", (0, 1), pending="kit" in p,
                      small=True),
                    c("SAMPLE", state["sample"], "seg", (0, 1),
                      pending="sample" in p, small=True),
                    dead("tune"), dead("decay"), dead("filtr"),
                ] + tail
            # A column is live only where the running plugin publishes a
            # symbol for that role. Per column, not per channel: a sampler
            # behaving as a voice has none of the four (SP4), and a synth the
            # measured table has never seen may publish three of them.
            # Law L4 - draw dead, never a number the knob cannot move.
            live = techno_lib.synth_ctrl_flags(state)
            return [
                c("PRESET", state["preset"], "seg", (0, 1),
                  pending="preset" in p, small=True),
            ] + [
                c(label, n(state[key]), "uni", state[key] / 127.0)
                if live[index] else dead(key)
                for index, (label, key) in enumerate((
                    ("CUTOFF", "cutoff"), ("RESO", "reso"),
                    ("ENV", "env"), ("DECAY", "decay")))
            ] + tail

        # STEP
        if kind == "drum":
            return [
                c("HITS", n(state["hits"]), "uni", state["hits"] / max(1, state["length"])),
                c("ROTATE", n(state["rotate"]), "seg",
                  (state["rotate"], max(1, state["length"]))),
                c("DIVIDE", techno_lib.DIVISION_LABELS[state["div"]], "seg",
                  (state["div"], len(techno_lib.DIVISION_LABELS)), pending="div" in p),
                c("LENGTH", n(state["length"]), "uni", state["length"] / 16.0,
                  pending="length" in p),
                c("VELO", n(state["velo"]), "uni", state["velo"] / 127.0),
                c("CHANCE", n(state["chance"]), "uni", state["chance"] / 100.0),
                c("SWING", n(state["swing"]), "uni", (state["swing"] - 50) / 25.0),
                # SP10 step 3: the page's dead eighth column, filled. OFF at 1
                # rather than "1", because one hit is not a ratchet and reading
                # "1" invites turning it down looking for off.
                c("RATCH", "OFF" if state.get("ratchet", 1) <= 1
                  else "x%d" % state["ratchet"], "seg",
                  (max(0, state.get("ratchet", 1) - 1), 4)),
            ]
        # THIS LIST'S ORDER MUST MATCH PAGE_RINGS[("STEP", "voice")][0]["verbs"]
        # position for position - the verbs tuple decides which encoder writes
        # what, this decides what each encoder DRAWS, and nothing checks that
        # they agree at runtime. Reorder one and you reorder the other.
        #
        # Owner's layout, 2026-08-16, chosen at the rig: pattern time first
        # (DIVIDE, GATE), then THE TWO GENERATORS SIDE BY SIDE (MELODY,
        # RHYTHM) because they are one idea and the hand should find them
        # together, then pitch (LENGTH, OCTAVE, RANGE) and VELO.
        return [
            c("DIVIDE", techno_lib.DIVISION_LABELS[state["div"]], "seg",
              (state["div"], len(techno_lib.DIVISION_LABELS)), pending="div" in p),
            c("GATE", n(state["gate"]), "uni", state["gate"] / techno_lib.GATE_MAX),
            # LOCK is a word, not a number that could be a coincidence.
            # MELODY, not RANDOM: there are two generators now and "random"
            # never said random WHAT. The state key stays `random` - renaming
            # it would move the data in every saved snapshot for a cosmetic
            # gain.
            c("MELODY", "LOCK" if state["random"] <= 0 else n(state["random"]), "uni",
              state["random"] / 100.0),
            # The rhythm generator, reading LOCK at zero exactly as MELODY
            # does - one grammar for both, because they are one idea.
            c("RHYTHM", "LOCK" if state["rhythm"] <= 0 else n(state["rhythm"]), "uni",
              state["rhythm"] / 100.0),
            c("LENGTH", n(state["length"]), "uni", state["length"] / 16.0,
              pending="length" in p),
            c("OCTAVE", f"{state['octave']:+03d}", "bi", (state["octave"] + 2) / 4.0),
            c("RANGE", str(state["range"]), "seg", (state["range"] - 1, 4)),
            c("VELO", n(state["velo"]), "uni", state["velo"] / 127.0),
        ]

    class PendingQueue:
        """Macros waiting for a bar boundary.

        A bar index in, a list of macro names out. No zynseq, no driver, no
        clock of its own - which is what makes it testable on WSL, where the
        driver cannot even be imported.

        NESTED in techno_lib on purpose. The driver does `from
        ...techno_lib import techno_lib as tlib`, so `tlib` is the CLASS,
        not the module: a module-level class here would be unreachable
        through it and `tlib.PendingQueue` would raise AttributeError on the
        rig, where nothing catches it early.

        Keyed by MACRO NAME rather than by an arming id, so arming a macro
        that is already pending REPLACES it. Two DROPs can then never land
        on different bars and fight over the same restore state."""

        def __init__(self):
            self._due = {}

        def arm(self, macro, bars, at_bar):
            """Schedule `macro` for `bars` bars after `at_bar`.

            A zero-bar arm lands on the NEXT bar, never the current one:
            firing inside the bar the player is already in would be
            indistinguishable from firing immediately, and the countdown
            would never be seen."""
            self._due[macro] = int(at_bar) + max(1, int(bars))

        def due(self, bar_index):
            """Every macro whose landing bar has arrived or passed, removed.

            Uses >= rather than == so a missed poll cannot strand a macro
            pending forever - a 30 Hz poll against a two-second bar has
            margin, but a blocked thread does not."""
            firing = [m for m, bar in self._due.items() if int(bar_index) >= bar]
            for macro in firing:
                del self._due[macro]
            return firing

        def remaining(self, macro, bar_index):
            """Bars left before `macro` lands, or None if it is not pending."""
            bar = self._due.get(macro)
            if bar is None:
                return None
            return max(0, bar - int(bar_index))

        def pending(self):
            return list(self._due)

        def cancel(self, macro):
            """Drop ONE armed macro. Returns True if it was armed.

            Added for the PENDING page, and added HERE rather than rebuilt at
            the caller: re-arming the survivors through arm() would push every
            one of them by at least a bar, because arm() takes a LENGTH and
            floors it at one. A cancel must not move what it did not cancel."""
            return self._due.pop(macro, None) is not None

        def clear(self):
            self._due.clear()


# Rings are built after the class body so page_desc() is callable. Keeping them
# out of the class body is the only reason they are down here; they are read as
# techno_lib.PAGE_RINGS like everything else.
_d = techno_lib.page_desc
techno_lib.PAGE_RINGS = {
    ("CONTROL", "drum"): (
        _d(techno_lib.SHAPE_CHANNEL, "CTRL",
           verbs=("kit", "sample", None, None, None, "level", "reverb", "delay")),
    ),
    ("CONTROL", "voice"): (
        _d(techno_lib.SHAPE_CHANNEL, "CTRL",
           verbs=("preset", "cutoff", "reso", "env", "decay",
                  "level", "reverb", "delay")),
    ),
    ("STEP", "drum"): (
        _d(techno_lib.SHAPE_CHANNEL, "STEP",
           verbs=("hits", "rotate", "div", "length", "velo", "chance",
                  "swing", "ratchet")),
        _d(techno_lib.SHAPE_SPREAD, "SWING", verb="swing"),
        _d(techno_lib.SHAPE_SPREAD, "CHANCE", verb="chance"),
    ),
    # Encoder 7 carries DENSITY rather than SWING: it is the only slot on a
    # full page whose verb has a second home, and swing is on the spread page
    # below for every channel at once, which is where it is wanted in a jam.
    ("STEP", "voice"): (
        _d(techno_lib.SHAPE_CHANNEL, "STEP",
           verbs=("div", "gate", "random", "rhythm", "length", "octave",
                  "range", "velo")),
        _d(techno_lib.SHAPE_SPREAD, "SWING", verb="swing"),
        _d(techno_lib.SHAPE_SPREAD, "CHANCE", verb="chance"),
        _d(techno_lib.SHAPE_SPREAD, "RHYTHM", verb="rhythm"),
    ),
    ("ALL", None): (
        _d(techno_lib.SHAPE_GLOBAL, "GLOBAL",
           verbs=("root", "scale", "bpm", "master", "revsize", "revtype",
                  "dlytime", "dlyfbk")),
        # The ALL ring held exactly ONE page until 2026-08-20, which meant the
        # big encoder - the page ring since 2026-08-19 - did nothing at all on
        # this mode. PENDING is its second stop and the encoder's first job
        # here.
        _d(techno_lib.SHAPE_PENDING, "PENDING"),
    ),
    ("MIXER", None): (
        _d(techno_lib.SHAPE_SPREAD, "LEVEL", verb="level"),
        _d(techno_lib.SHAPE_SPREAD, "REVERB", verb="reverb"),
        _d(techno_lib.SHAPE_SPREAD, "DELAY", verb="delay"),
    ),
    ("FILTER", None): (
        _d(techno_lib.SHAPE_SPREAD, "CUTOFF", verb="cutoff"),
        _d(techno_lib.SHAPE_SPREAD, "RESO", verb="reso"),
    ),
}
del _d
