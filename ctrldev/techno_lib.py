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
import time
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

    LEAN_OFF = "off"             # euclid, as it always was
    LEAN_BEAT = "beat"           # the floor: toward the quarter notes
    LEAN_EIGHTH = "8th"          # hats: toward the eighths
    LEAN_OFFBEAT = "offb"        # syncopation: away from the strong positions
    LEANS = (LEAN_OFF, LEAN_BEAT, LEAN_EIGHTH, LEAN_OFFBEAT)
    LEAN_LABELS = {LEAN_OFF: "EUCL", LEAN_BEAT: "BEAT",
                   LEAN_EIGHTH: "8TH", LEAN_OFFBEAT: "OFFB"}

    @staticmethod
    def metric_weight(i, steps):
        """How strong position `i` is, on a bar of `steps`.

        The metric hierarchy, derived rather than tabulated so a 12-step
        triplet division gets its own thirds instead of a 16-step pattern's
        halves: a position scores a point for every subdivision of the bar it
        lands on. Step 0 lands on all of them and is always the strongest.

        Pure arithmetic on `steps`, so nothing here assumes sixteen."""

        i %= max(1, steps)
        weight = 0
        span = steps
        while span >= 2:
            if i % span == 0:
                weight += 1
            if span % 2:
                break
            span //= 2
        return weight

    @staticmethod
    def lean_grid(steps, profile):
        """The positions a profile is aiming AT, as a set of step indices.

        Built by dividing the bar rather than by tabulating sixteen, so a
        12-step triplet division gets its own grid: BEAT is the four quarters,
        8TH the eight eighths, and OFFB the quarters shifted half a beat - the
        "and" of each beat, which is where a syncopating part lives."""

        steps = max(1, int(steps))
        if profile == techno_lib.LEAN_BEAT:
            return {(k * steps) // 4 % steps for k in range(4)}
        if profile == techno_lib.LEAN_EIGHTH:
            return {(k * steps) // 8 % steps for k in range(8)}
        if profile == techno_lib.LEAN_OFFBEAT:
            return {((2 * k + 1) * steps) // 8 % steps for k in range(4)}
        return set()

    @staticmethod
    def lean(steps, hits, profile):
        """Place `hits` by what the part is FOR, instead of evenly.

        A THIRD PLACEMENT GENERATOR BESIDE EUCLID, not a replacement: OFF
        returns None and the caller keeps euclid, which is what makes every
        existing channel and every existing snapshot bit for bit what it was.

        The hits closest to the profile's grid win; ties break on the metric
        hierarchy and then on index. So the first hits land ON the grid, and
        the ones past it crowd the strong positions rather than spreading out -
        which is the difference a listener hears between a part that leans and
        a euclidean part that cannot.

        DETERMINISTIC BY CONSTRUCTION. A weighted random pick would need a seed
        of its own, and a pattern that changed on every rewrite is not a
        pattern.

        ROTATE STILL ROTATES. On a leaning channel that moves the accent off
        the grid it was computed against, which is a real musical consequence -
        and it is the right trade: anchoring the lean would make ROTATE do
        nothing on these channels, and a knob that silently does nothing is the
        worst object on a control surface. The pads show where the hits went."""

        if profile == techno_lib.LEAN_OFF or profile not in techno_lib.LEANS:
            return None
        steps = max(1, int(steps))
        hits = max(0, min(int(hits), steps))
        grid = sorted(techno_lib.lean_grid(steps, profile),
                      key=lambda g: (-techno_lib.metric_weight(g, steps), g))
        chosen = []
        taken = set()
        # ROUND ROBIN over the grid, and it is what makes this a lean rather
        # than a pile. Each pass gives every grid position one hit before any
        # of them gets a second, so eight hits on the floor profile land as a
        # flam on each beat and not as four hits crowded onto beat one. The
        # order within a pass is the metric hierarchy, so if the hits run out
        # mid-pass it is the weak beats that go without.
        offset = 0
        while len(chosen) < hits and offset <= steps:
            for g in grid:
                if len(chosen) >= hits:
                    break
                # FORWARD FIRST: a hit that arrives just after the beat is a
                # push, which is what these parts do. Backward is the pickup
                # and comes second.
                for i in ((g + offset) % steps, (g - offset) % steps):
                    if i not in taken:
                        taken.add(i)
                        chosen.append(i)
                        break
            offset += 1
        return tuple(i in taken for i in range(steps))

    # A close is heard as the part getting DARKER before it gets quieter, so
    # the filter leads the level. Squaring the factor is enough: at half way
    # the level is at 50% and the cutoff at 25%, and both still reach the ends
    # exactly, which is what keeps an opened channel identical to one that
    # never closed.
    EXIT_CUTOFF_CURVE = 2

    @staticmethod
    def exit_factor(step, steps, closing=True):
        """Where a close or an open has got to, 1.0 open and 0.0 shut.

        Linear, and past the end it STAYS landed rather than overshooting: the
        writer runs on a poll tick, so it may be asked one tick after it has
        finished, and a ramp that kept going would drive the level negative.

        A zero-length exit is INSTANT - the landed value, immediately - which
        is what makes 0 bars exactly the behaviour that shipped before this
        existed."""

        steps = max(0, int(steps))
        if steps <= 0:
            return 0.0 if closing else 1.0
        frac = min(1.0, max(0.0, step / float(steps)))
        return (1.0 - frac) if closing else frac

    @staticmethod
    def exit_cutoff(factor):
        """The filter's share of a close, given the level's.

        Both ends are exact - 0 stays 0 and 1 stays 1 - so a channel that has
        opened fully is bit for bit one that never closed, and a channel that
        has closed fully is silent by BOTH routes rather than by a rounding
        error in one."""

        f = min(1.0, max(0.0, float(factor)))
        return f ** techno_lib.EXIT_CUTOFF_CURVE

    # THE WATCHDOG, 2026-09-01. Long enough that a kit change which merely
    # took a while does not cry wolf - the poll tick is 33 ms and the shipped
    # sub-rate is ~200 ms - and short enough that a player notices the banner
    # in the same breath as the silence.
    STALL_AFTER_S = 3.0

    @staticmethod
    def stalled(now, beat, after=None):
        """Has the generator's heartbeat stopped?

        A HEARTBEAT, NOT A try/except, and the distinction is the whole
        feature. The failure this was written from - a poll thread that died by
        raising - cannot recur: that thread has had an exception guard since
        `643659f`. What remains is a thread that stops by BLOCKING, on the
        LinuxSampler socket with no timeout, and no exception handler catches
        that. A watchdog shaped like the entry's description would guard the
        half that is already guarded.

        A beat that has never happened is NOT a stall: before the first tick
        there is nothing to compare against, and reporting one at start-up
        would cry wolf on every boot."""

        if beat is None:
            return False
        after = techno_lib.STALL_AFTER_S if after is None else after
        return (now - beat) > after

    @staticmethod
    def stall_label(now, beat, label=""):
        """The page indicator while the machine is stopped.

        IT REPLACES THE LABEL RATHER THAN APPENDING TO IT. The indicator
        already composes up to eleven suffixes onto a 42-character line and
        truncates silently - a logged defect - and the one message that must
        never be the one truncated is the one saying the instrument has
        stopped.

        WHOLE SECONDS. A tenth ticking on the label is an animation, and it
        would repaint both screens ten times a second, which is how this
        controller has been wedged before."""

        if not techno_lib.stalled(now, beat):
            return label
        return "GEN STOPPED %ds" % int(now - beat)

    PHRASE_LENGTHS = (1, 2, 4)

    @staticmethod
    def is_fill_bar(bar, phrase):
        """Is this the last bar of the phrase?

        A phrase of 1 is OFF and no bar is ever a fill, which is exactly the
        behaviour that shipped before this existed."""

        phrase = int(phrase)
        if phrase <= 1:
            return False
        return int(bar) % phrase == phrase - 1

    @staticmethod
    def fill_line(pattern, amount):
        """The same bar, answered.

        ADDS steps and never removes one: a fill that took hits away would be
        a breakdown, and the player has a knob for that. It reaches for the
        OFFBEATS first - a fill that added on the beats would just be a louder
        version of the bar it is meant to answer - and it is deterministic, so
        the fourth bar is the same fourth bar every time round.

        `amount` is how much of the room left in the bar to use, 0-100, so a
        dense pattern fills less than a sparse one for the same number: what
        the knob controls is how FULL the answer gets, not how many hits are
        added to whatever is there."""

        amount = max(0, min(100, int(amount)))
        if amount <= 0:
            return tuple(pattern)
        steps = len(pattern)
        out = list(pattern)
        free = [i for i in range(steps) if not out[i]]
        if not free:
            return tuple(out)
        grid = techno_lib.beat_grid(steps)

        def distance(i):
            return min(min((i - g) % steps, (g - i) % steps) for g in grid)

        # FURTHEST FROM THE BEAT FIRST - the mirror image of the lane, which
        # drops in exactly this order. The two verbs pull against each other on
        # purpose: one is how far the generator may stray, the other is how far
        # the fill is allowed to.
        free.sort(key=lambda i: (-distance(i), i))
        take = max(1, int(round(len(free) * amount / 100.0)))
        for i in free[:take]:
            out[i] = True
        return tuple(out)

    @staticmethod
    def beat_grid(steps):
        """The quarter-note positions of a bar of `steps`. Derived by dividing
        the bar, so a 12-step triplet division gets 0, 3, 6, 9."""

        steps = max(1, int(steps))
        return {(k * steps) // 4 % steps for k in range(4)}

    @staticmethod
    def syncopation(pattern):
        """What share of a bar's hits are OFF the beat, 0-100.

        A proportion rather than a weighted distance, and that is deliberate:
        the question a constraint has to answer is "how much of this part is
        not on the beat", and a hit is either on one or it is not. The distance
        still matters, but it decides the ORDER hits are dropped in rather than
        the score - see lane_filter.

        An EMPTY bar scores 0 rather than dividing by zero. A bar with nothing
        in it has not strayed anywhere.

        Deliberately crude. It ranks the hits of one bar against each other so
        the weakest can go; it is not a musicological claim."""

        steps = len(pattern)
        on = [i for i, hit in enumerate(pattern) if hit]
        if not on:
            return 0
        grid = techno_lib.beat_grid(steps)
        off = sum(1 for i in on if i not in grid)
        return int(round(100.0 * off / len(on)))

    @staticmethod
    def lane_filter(pattern, lane):
        """Drop the weakest hits until the bar is inside the lane.

        `lane` is how NARROW the lane is: 0 is the raw field - the pattern is
        returned untouched, which is exactly what shipped before this existed -
        and 100 allows only what lands on the beat.

        THE DROP ORDER IS FURTHEST-FROM-THE-BEAT FIRST, then latest in the bar.
        So the stray sixteenth goes before the eighth, and the answer is the
        same every time it is asked for - a constraint that pruned differently
        on each rewrite would be a fourth generator, not a limit.

        It only ever REMOVES. A constraint that added a step would be inventing
        a part, and HITS would stop meaning the number of hits.

        A CHANNEL IS NEVER EMPTIED. The last hit survives whatever the lane
        says: a silence whose explanation lives on another page is the one law
        this surface cannot break."""

        lane = max(0, min(100, int(lane)))
        if lane <= 0:
            return tuple(pattern)
        steps = len(pattern)
        out = list(pattern)
        budget = 100 - lane
        grid = techno_lib.beat_grid(steps)

        def distance(i):
            return min(min((i - g) % steps, (g - i) % steps) for g in grid)

        # Weakest LAST, so pop() takes the next one to go.
        order = sorted((i for i, hit in enumerate(out) if hit),
                       key=lambda i: (distance(i), i))
        while order and techno_lib.syncopation(out) > budget:
            if sum(out) <= 1:
                break
            out[order.pop()] = False
        return tuple(out)

    RULE_RANDOM = "rand"         # the shift register, as it always was
    CA_RULES = ("r30", "r90", "r110")
    RULES = (RULE_RANDOM,) + CA_RULES

    # Wolfram numbering: bit (left<<2 | centre<<1 | right) of the rule number
    # is the cell's next value. Three chosen, and the choice is musical rather
    # than mathematical - 30 scatters, 90 makes travelling diagonals that
    # collide, 110 grows structures that persist for many bars.
    _CA_NUMBERS = {"r30": 30, "r90": 90, "r110": 110}

    @staticmethod
    def ca_step(register, width, rule, chance=1.0, rng=random.random):
        """Evolve a rhythm register one generation by an elementary CA rule.

        THIS REPLACES mutate, NOT the MODEL column. `model` chooses where a
        voice's PITCH values come from; this chooses how the register EVOLVES.
        Folding them together would mean picking R110 silently also decided the
        pitch source - the PM decision of 2026-09-01, and there is a test on it.

        The neighbourhood WRAPS: the pattern is a loop, so a shape that travels
        has to leave one end and arrive at the other. Nothing is ever written
        outside `width` - a 12-step triplet division must not pick up bits
        12-15 left behind by a 16-step one.

        `chance` is the probability the rule is applied to each bit, the rest
        held - the owner decision. LOCK stays EXACT at 0 (mutate's own promise,
        kept), 100 is the pure automaton, and RANDOM keeps one meaning on every
        channel kind. At chance 1.0 the rng is not consulted at all, which is
        what makes the automaton reproducible.

        AN EMPTY REGISTER IS RESEEDED, DETERMINISTICALLY. Every elementary rule
        offered here maps 000 -> 0, so a register that reached empty would stay
        empty forever with the knob reading whatever it read: a silent channel
        with nothing explaining it, and that is the one law this surface cannot
        break. The reseed is one bit at step 0 and never a random one - a CA is
        bought for "some rules never repeat, some grow shapes", and a random
        rescue would make it unreproducible."""

        width = max(1, int(width))
        mask = (1 << width) - 1
        reg = int(register) & mask
        number = techno_lib._CA_NUMBERS.get(rule)
        if number is None:
            # Not an automaton - the shift register, or a name from a newer
            # snapshot. Hold, rather than invent a rule that was not asked for.
            return reg
        if chance <= 0:
            return reg
        out = 0
        for i in range(width):
            bit = (reg >> i) & 1
            if chance < 1.0 and rng() >= chance:
                out |= bit << i
                continue
            left = (reg >> ((i - 1) % width)) & 1
            right = (reg >> ((i + 1) % width)) & 1
            out |= ((number >> ((left << 2) | (bit << 1) | right)) & 1) << i
        if out == 0:
            return 1
        return out

    @staticmethod
    def mutate_coupled(register, length, chance, source, source_length,
                       amount, rng=random.random):
        """mutate(), but the fed-back bit may come from ANOTHER voice.

        WHAT COUPLING MEANS HERE, and two rejected readings. The source's
        outgoing bit is fed into the target's incoming bit, with probability
        `amount`. Rejected: reciprocal XOR, which makes two voices IDENTICAL
        inside a single tick - that is collapse, not drift-together; and making
        the target's mutate chance depend on the source's bit, which is
        statistically indistinguishable from a slightly different MELODY
        setting, so the player cannot hear it and it is not a feature.

        AMOUNT 0 IS BIT-IDENTICAL TO mutate(), AND CONSUMES THE SAME RANDOM
        STREAM. The `amount > 0` short-circuit is what guarantees the second
        half: an unconditional rng() call here would draw one extra number per
        bit and change how every evolving voice on the instrument sounds, the
        day this shipped, with nothing to point at.

        AMOUNT 1 AT LOCK COPIES THE SOURCE - the target becomes it, one bar
        behind. That is the degenerate end of a continuous control and it is
        reachable on purpose; it is named here so it is not reported as a bug.

        THE SOURCE IS A VALUE, NOT A CHANNEL, and it is never written. A feeds
        B feeds A is a musically real request, and passing both registers as
        they were at the START of the tick is what stops the pair running away
        inside one wrap.

        Lengths need not agree. The feed is ONE BIT, so a five-bit source can
        drive a sixteen-bit target; the source is read modulo its own length."""

        mask = (1 << length) - 1
        reg = register & mask
        src_len = max(1, source_length)
        for i in range(length):
            bit = (reg >> (length - 1)) & 1
            if amount > 0 and rng() < amount:
                bit = (source >> ((length - 1 - i) % src_len)) & 1
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
    def rotate_line(notes, mask, count):
        """A voice's rendered line rotated forward in time, notes and rests
        together. Returns (notes, mask).

        ROTATE ON A VOICE - owner's decision, 2026-08-31. Two readings were on
        the table and they are indistinguishable from outside the code, so the
        rejected one is named here rather than left to be re-derived: clocking
        the PITCH REGISTER walks to a related but different melody, the way the
        hardware Turing Machine's rotation does. That was rejected because a
        voice's neighbourhood is already reachable through REROLL, so it would
        have bought a second route to something that exists while leaving the
        requested gesture - the one drums have - still missing.

        SO THE VERB MEANS ONE THING ON BOTH KINDS OF CHANNEL, and the direction
        is deliberately maschine_mk2_lib.rotate's: forward in time, wrapping at
        the end. A test asserts the two agree, because if they ever drift the
        same word moves a drum and a voice opposite ways and nothing on the
        surface would say so.

        Notes and mask rotate in ONE call because the failure worth preventing
        is rotating them apart: a melody that slides while its rhythm stands
        still is not the same melody moved, it is a different one."""

        n = len(notes)
        if n == 0:
            return [], ()
        count %= n
        if not count:
            return list(notes), tuple(mask)
        return (list(notes[-count:]) + list(notes[:-count]),
                tuple(mask[-count:]) + tuple(mask[:-count]))

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
    def drum_steps(pattern, rhythm_reg):
        """A euclidean drum pattern thinned by the drum rhythm register.

        SUBTRACTIVE, and that is the whole design decision. On a voice the
        rhythm register decides which steps sound outright, because nothing
        else has an opinion. On a drum, HITS and ROTATE have already drawn the
        line - so the register may take a hit away and may never invent one. A
        register that could add steps would leave the HITS encoder reporting a
        number that is not the number of hits, with nothing on the surface to
        say so.

        Only the pattern's own bits are read, exactly as rhythm_mask does, so a
        12-step triplet division cannot pick up bits 12-15 left behind by a
        16-step one."""

        return tuple(bool(step) and bool(rhythm_reg >> i & 1)
                     for i, step in enumerate(pattern))

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
    def claim_clears(kind):
        """Does the FIRST captured note wipe what the generator wrote?

        On a VOICE, yes. Measured on the rig 2026-08-22: a REC take landed on
        top of the Turing line and the player heard both at once, so the take
        never sounded like a replacement even though the channel had changed
        hands. The generator's line is reproducible from the register at any
        time - ERASE + Group brings it straight back - so clearing it costs
        nothing that cannot be undone.

        On a DRUM, no. A drum overdub is how a euclidean pattern gets a
        hand-placed accent on top of its own hits, and clearing there would
        silence the whole channel on the first tap. Anything unrecognised
        stacks too: stacking loses nothing, clearing loses a pattern."""

        return kind == "voice"

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

    # ---------------------------------------------------------- chord walker
    #
    # THE GLOBAL-SCALE HALF OF THIS FEATURE ALREADY SHIPPED. `new_features.md`
    # said "the three voices pick pitch independently today" and that was
    # false: ROOT and SCALE have been global verbs driving all three voices for
    # months, and a key change already lands on the bar through the driver's
    # key-dirty set - deliberately, so a LOCKED voice still changes key while
    # keeping its shape. Only the walker was ever missing, which is why this is
    # three small functions and not a feature.

    @staticmethod
    def walk_due(bar, every):
        """Is the walker due to move on this bar? 0 is LOCK.

        Zero reads as LOCK because that is already this instrument's grammar -
        MELODY and RHYTHM at zero hold their registers still - and a fourth
        control that spelled "off" a fourth way would be one more thing to
        remember for nothing."""

        return every > 0 and bar % every == 0

    @staticmethod
    def walk_next(degree, span, rng=random.random):
        """One step of the bounded walk, in scale degrees. Span 0 holds still.

        REFLECTS AT THE EDGE, never clamps. A clamp parks the key against the
        end of its span and sits there - a walker that has stopped walking,
        which reads as a broken feature rather than a bounded one."""

        if span <= 0:
            return 0
        step = 1 if rng() < 0.5 else -1
        nxt = degree + step
        if nxt > span or nxt < -span:
            nxt = degree - step
        return nxt

    @staticmethod
    def walk_root(base_root, degree, scale_idx):
        """The walked root, in semitones, `degree` scale steps from the base.

        ALONG THE SCALE, NOT BY SEMITONES. The three voices are sharing this
        scale; stepping the root chromatically would walk out of the key they
        are sharing, which is the opposite of the request - three unrelated
        lines were supposed to become a progression. Degree 0 is exactly the
        root the player dialled in, so a walk that returns to zero returns to
        the hand-set key rather than near it."""

        intervals = techno_lib.SCALES[scale_idx][1]
        octaves, idx = divmod(degree, len(intervals))
        return base_root + intervals[idx] + 12 * octaves

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
    def walk_line(start, length, steps, root, scale_idx, octave,
                  range_octaves, span, stride, rng=random.random):
        """line()'s counterpart for a voice on MODEL_WALK.

        Deliberately the same shape and the same downstream call, so the writer
        asks one function whichever model a voice is on and the scale, root,
        octave and range mean exactly what they mean everywhere else. The walk
        replaces where the VALUES come from and nothing else."""

        return [techno_lib.pitch(v, length, root, scale_idx, octave,
                                 range_octaves)
                for v in techno_lib.walk_values(start, length, steps, span,
                                                stride, rng)]

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

    # How a voice picks its pitches. A MODEL, not a KIND - see the `model` key
    # in default_channel_state for why that distinction is the whole cost of
    # this feature.
    MODEL_REGISTER = "reg"       # the Turing shift register, as it always was
    MODEL_WALK = "walk"          # a bounded random walk
    MODELS = (MODEL_REGISTER, MODEL_WALK)

    @staticmethod
    def walk_rng(seed):
        """A deterministic random source for the walk, from a stored integer.

        THE WALK MUST BE A PURE FUNCTION OF STATE, exactly as the register is.
        `line()` derives the same notes from the same register every time, so
        the writer and the pad renderers always agree. The walk had no such
        anchor: `_voice_line` is called by `_write_voice_pattern` AND by both
        pad renderers, and each call re-ran the walk against the module rng, so
        every repaint invented a different melody.

        The owner found it at the rig on 2026-08-31 - the pads flashed about
        five times a second and never showed the line that was playing, which
        is the failure `_voice_line`'s own docstring had predicted. It measured
        109 OSC messages a second against 6.6 idle, inside the band the
        write-budget finding says wedges the controller off the USB bus.

        A private Random rather than seeding the module one, because the
        register's own mutation draws from that and a repaint must not consume
        the randomness the generator is about to use.

        The seed is a plain int so it stores in the channel state and survives
        a snapshot like every other value there.
        """

        return random.Random(seed).random

    @staticmethod
    def walk_values(start, length, steps, span, stride, rng=random.random):
        """`steps` values from a bounded random walk, in the REGISTER's own
        domain, so everything downstream of it is untouched.

        That domain matters: pitch() shifts the value right by `length`, so a
        value outside 0..2^length-1 quantises to a scale degree that does not
        exist. The walk is bounded twice - by `span` around its start and by
        the register domain - and the tighter of the two wins.

        REFLECTS AT BOTH BOUNDS, never clamps, for the same reason the chord
        walker does: a walk parked against its own edge has stopped walking,
        and that reads as broken rather than bounded.

        A span or a stride of zero yields one note held for the whole pattern.
        Deliberate, and audible: a silent channel must say why, and this one
        has nothing to explain because it is sounding."""

        top = (1 << length) - 1
        start = max(0, min(top, int(start)))
        lo = max(0, start - span)
        hi = min(top, start + span)
        out, value = [], start
        for _ in range(steps):
            out.append(value)
            if stride <= 0 or hi <= lo:
                continue
            step = stride if rng() < 0.5 else -stride
            nxt = value + step
            if nxt > hi or nxt < lo:
                nxt = value - step
            value = max(lo, min(hi, nxt))
        return out

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
                     chance=100, pending=set(),
                     # A PHRASE, NOT A BAR, 2026-09-01. `phrase` is how many
                     # bars the phrase is and `fill` is how full its last bar
                     # gets. 1 and 0 ARE THE MIGRATION: no bar is ever a fill
                     # and nothing is ever added, which is what every channel
                     # did before these existed.
                     phrase=1, fill=0,
                     # EXIT, 2026-09-01. How long a QUEUED mute takes to close
                     # the channel, in bars. 0 IS THE MIGRATION - hard, the
                     # instant the wrap arrives, exactly as a queued mute has
                     # always landed.
                     exit=0,
                     # RULE, 2026-09-01. How the rhythm register EVOLVES:
                     # the shift register as always, or an elementary cellular
                     # automaton. `rand` IS THE MIGRATION - it is bit for bit
                     # what every channel did before this verb existed.
                     rule=techno_lib.RULE_RANDOM,
                     # MOVE, 2026-09-01. How much the machine's own gestures
                     # may touch this channel. 100 IS LOAD-BEARING: it is
                     # exactly the behaviour that shipped before this verb
                     # existed, and upgrade_state builds from here, so every
                     # existing snapshot comes back playing what it played.
                     move=100)
        if kind == "drum":
            # RANGE on a DRUM is SP8's kit-walk window, and it starts at 4 -
            # the whole kit - so a channel walks exactly as it did before SP8
            # existed. A voice's RANGE is octave spread and keeps its own
            # default of 2; sharing that number here would have narrowed every
            # existing drum channel to half its kit the day this shipped.
            state.update(kit="----", sample="----", range=4, kit_range=1,
                         # 1 = off. A step fires once, as it always has.
                         ratchet=1,
                         # The drum rhythm register. `rhythm` is its evolve
                         # knob, 0 = LOCK, exactly as it is on a voice.
                         #
                         # 0xFFFF IS LOAD-BEARING AND IT IS THE MIGRATION.
                         # The register is subtractive on a drum - euclid has
                         # already decided which steps sound - so an all-ones
                         # register removes nothing and a drum channel is bit
                         # for bit what it was before this existed. Default it
                         # to anything else and every drum channel in every
                         # existing snapshot comes back partly silent, which is
                         # the 2026-08-18 class of bug: upgrade_state builds
                         # from here, so this literal is what an old snapshot
                         # inherits.
                         rhythm=0, rhythm_reg=0xFFFF,
                         # LEAN, 2026-09-01. Which PLACEMENT generator draws
                         # the line. `off` is euclid and IS the migration: a
                         # drum channel out of any existing snapshot is placed
                         # exactly as it was before this generator existed.
                         lean=techno_lib.LEAN_OFF,
                         # LANE, 2026-09-01. How narrow the danceable lane is.
                         # 0 IS THE MIGRATION - the raw field, which is what
                         # every drum channel has always played. Drums only:
                         # a voice's placement IS its rhythm register, and a
                         # pad tap writes into that register, so pruning it
                         # would silently undo a hand-tapped step.
                         lane=0)
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
                kit_range=1,
                # WHICH GENERATOR PICKS THE PITCHES. A per-voice switch, NOT a
                # third channel KIND: there are 42 binary kind tests, and six
                # driver sites written `!= "voice"` would have routed a third
                # kind down the DRUM path silently, with no error and no log.
                # The channel stays a voice, so every one of those tests keeps
                # the answer it has today and none of them needs auditing.
                #
                # MODEL_REGISTER is the default, so an existing voice - and
                # every voice in every saved snapshot - behaves exactly as it
                # did before the walk existed.
                model=techno_lib.MODEL_REGISTER,
                walk_span=32, walk_stride=4,
                # ROTATE on a voice - the LINE, not the register (owner,
                # 2026-08-31). 0 is unrotated, which is every existing voice.
                rotate=0,
                # Cross-coupling. `feed` is the channel whose register feeds
                # this one, or None; `amount` is how often its bit is taken,
                # 0-100. None and 0 are today's behaviour exactly, and
                # mutate_coupled does not even draw a random number at 0.
                feed=None, amount=0)
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
    # BANK sits under ARM and over MUTE, 2026-09-01. Under ARM because ARM's
    # countdown is already running and has to stay readable; over MUTE because
    # launching a whole arrangement is a larger commitment than muting one
    # channel, and the larger commitment should not be the one that loses.
    OVERLAY_PRIORITY = ("shift", "arm", "bank", "mute", "mod", "navigate")

    # Whether an overlay's pads still MEAN steps. The playhead is drawn over
    # the top only where they do: under SHIFT pad 3 is step 3 carrying a
    # probability, so the sweep helps; under MOD pad 3 is a RATE and a playhead
    # marker on it would point at nothing. Under ARM a pad is a macro or a bar
    # count, which is the same story again.
    OVERLAY_STEPWISE = {"shift": True, "arm": False, "bank": False,
                        "mute": False, "mod": False, "navigate": False}

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
                  mute=False, bank=False):
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
                                        navigate=navigate, mute=mute,
                                        bank=bank)

    @staticmethod
    def overlay_owner(shift=False, mod=False, navigate=False, arm=False,
                      mute=False, bank=False):
        """Which modifier owns the pads, or None for the ordinary step picture.

        `arm` defaults False so every existing caller keeps its meaning."""
        held = {"shift": shift, "arm": arm, "bank": bank, "mute": mute,
                "mod": mod, "navigate": navigate}
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

    BANKS_PER_PAGE = 16
    BANK_PAGES = 4
    # The live and stocked banks share ONE hue and differ only in brightness,
    # which is legitimate here for the ARM picker's own reason: exactly one pad
    # is full, so it is a POSITION read and not a magnitude read. The queued
    # bank gets a different hue because "not yet, but soon" already has one on
    # this surface.
    COLOR_BANK = 0xFFE000

    @staticmethod
    def bank_of_pad(pad, page):
        """Which zynseq bank a pad stands for, or None.

        64 banks, sixteen pads, four pages walked by the big encoder while the
        overlay is held - the same job that encoder does everywhere else.
        Banks are 1-based because zynseq's own select_bank refuses anything
        outside 1..64."""

        pad, page = int(pad), int(page)
        if not 0 <= pad < techno_lib.BANKS_PER_PAGE:
            return None
        if not 0 <= page < techno_lib.BANK_PAGES:
            return None
        return page * techno_lib.BANKS_PER_PAGE + pad + 1

    @staticmethod
    def bank_pad_look(bank, live, queued, stocked):
        """(colour, brightness) for one bank pad.

        FOUR STATES AND EACH IS A HUE OR A POSITION, never brightness alone
        across two meanings: the live bank is the one bright pad, the queued
        bank is the one green pad, a stocked bank is the live hue dimmed, and
        an EMPTY bank is dark - a press there claims nothing and, more
        importantly, the picture that says so was built from a read that does
        not allocate. `getSequence` creates on any index it is handed,
        silently and permanently into the riff, so drawing the grid with the
        wrong reader would grow the snapshot by 64 banks."""

        if bank == queued:
            return (techno_lib.COLOR_ARM_LENGTH, techno_lib.PAD_FULL)
        if bank == live:
            return (techno_lib.COLOR_BANK, techno_lib.PAD_FULL)
        if bank in stocked:
            return (techno_lib.COLOR_BANK, techno_lib.ARM_DIM)
        return (techno_lib.COLOR_BANK, 0.0)

    @staticmethod
    def bank_label(page, live):
        """What the indicator row says while the overlay is held."""

        return "BANK %d/%d . %d" % (int(page) + 1, techno_lib.BANK_PAGES,
                                    int(live))

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

    # What a FREEZE tap stops. Everything here changes what you are hearing
    # without you touching anything; the LFOs do not rewrite notes, which is
    # why they are not in the set and need the deeper gesture.
    #
    # "macro" JOINED THE SET 2026-08-20, found by playing it: an armed DROP
    # fired while the machine was frozen and muted every channel. FREEZE
    # promises that nothing changes under you, and a macro landing is the
    # largest change this instrument can make - it is the one thing a player
    # freezes the machine to prevent.
    #
    # "walk" JOINED THE SET 2026-08-31 with the chord walker, on the same
    # argument that put "macro" here: a key change is one of the largest things
    # that can happen under a player who has asked for nothing to change.
    #
    # "rhythm" HAD NO CALLER until the same day - it sat in this set being
    # correct only by accident of an early return elsewhere, which is the
    # NAVIGATE-overlay shape: a library entry with no code behind it reads as
    # covered and is not. The drum rhythm register asks it through
    # generator_may_write, so it means something now.
    # "fill" joined 2026-09-01 WITH its caller, in the same commit - the
    # standing lesson from `rhythm`, which sat in this set for months with
    # nothing asking and was correct only by the accident of an early return.
    FREEZE_GENERATIVE = frozenset(("melody", "rhythm", "drift", "reroll",
                                   "macro", "walk", "fill"))

    # Ice blue, and nothing else on the panel uses it.
    COLOR_FREEZE = 0x60D0FF

    OWNER_PLAYER = "player"

    @staticmethod
    def move_allows(move, roll):
        """MOVE: how much the machine's own gestures may touch this channel.

        A PROBABILITY, not a switch - the owner decision of 2026-09-01. As a
        switch it is per-channel FREEZE renamed, and this instrument already
        has that button; as a probability the machine still surprises you on a
        channel you have half-claimed.

        100 is exactly today's behaviour and is the default everywhere, so an
        existing snapshot plays bit for bit what it played before this existed.
        0 is LOCK and is checked before the roll, so LOCK is exact rather than
        one-in-a-hundred.

        `roll` is 0..99, supplied by the caller - the library stays pure and
        the test stays deterministic. A MISSING roll ALLOWS: a gesture that
        vanished because a caller forgot an argument would be a channel that
        goes quiet with nothing explaining it, which is the one law this
        surface cannot break."""

        if move is None:
            return True
        move = max(0, min(100, move))
        if move >= 100:
            return True
        if move <= 0:
            return False
        if roll is None:
            return True
        return roll < move

    @staticmethod
    def generator_may_write(what, frozen, deep, owner, move=100, roll=None):
        """May a pattern-rewriting generator write this channel right now?

        ONE PREDICATE FOR EVERY GENERATOR THAT REWRITES THE PATTERN, and that
        is the whole point of it existing. Rewriting a pattern with no hands on
        the panel is how the velo defect destroyed a recorded take, unattended,
        every 200 ms. _drift_channel solved it and shipped; leaving each new
        generator to re-derive the same two gates is how the fourth one gets it
        subtly wrong with no runtime symptom.

        Two gates, and they are independent:

            FREEZE   - freeze_blocks decides, so a generator freeze does not
                       name is not held by it. The player froze the machine to
                       stop exactly this.
            OWNER    - a player-owned channel is never rewritten. RE-ASKED
                       EVERY WRAP by the callers, never cached at bind time: a
                       player can record onto a channel that is already
                       generating, and a bind-time answer cannot see that
                       coming.

        The caller does NOT delete the generator's entry on a refusal - handing
        the channel back with ERASE + Group must restore what the player set
        up, which is drift's rule and now everybody's."""

        if techno_lib.freeze_blocks(what, frozen, deep):
            return False
        if owner == techno_lib.OWNER_PLAYER:
            return False
        # MOVE, third and last. Deliberately after the other two: FREEZE and
        # ownership are absolute, and asking a probability first would let a
        # frozen channel's refusal depend on a dice roll.
        return techno_lib.move_allows(move, roll)

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

    # GATE COLLAPSE. The floor is a FRACTION of each note's own length, not an
    # absolute duration: a pattern of long pads and a pattern of stabs must
    # both end up "tight and dry", and a fixed target length would leave one
    # untouched and silence the other.
    GATE_COLLAPSE_FLOOR = 0.15

    # zynseq clamps a note duration at 0.1 and changeDurationAll returns out of
    # its whole loop the moment any event would reach <= 0. Both were measured.
    # Writing below this means the value read back is not the value written,
    # and a restore rebuilt from that reading would be rebuilding from a lie.
    NOTE_DURATION_MIN = 0.1

    @staticmethod
    def gate_ramp(bar, bars):
        """How much of its length a note keeps, `bar` bars into a collapse.

        Monotone DOWN and then a snap back, where chance_ramp is a V. The two
        are different gestures on purpose: the CHANCE ramp thins and refills
        to make a breakdown, this one tightens all the way into the landing and
        releases on it, which is what makes it read as a build rather than a
        dip.

        At and past the end it returns 1.0 - the pattern restored - rather than
        continuing past the floor. A missed poll cannot strand a channel
        collapsed forever, the same reasoning as chance_ramp's clamp and
        PendingQueue.due() using >= rather than ==."""

        if bars <= 0 or bar >= bars:
            return 1.0
        if bars == 1:
            return techno_lib.GATE_COLLAPSE_FLOOR
        pos = max(0, bar) / float(bars - 1)
        return 1.0 - (1.0 - techno_lib.GATE_COLLAPSE_FLOOR) * pos

    @staticmethod
    def collapse_duration(duration, factor):
        """One note's duration under the ramp, never below what zynseq will
        actually store.

        Clamped rather than allowed to reach zero: a note of zero length is not
        a short note, it is a note the sequencer drops - and the pattern is
        rebuilt from a capture, so a dropped note would not come back."""

        return max(techno_lib.NOTE_DURATION_MIN, float(duration) * float(factor))

    # The macros ARM can compose, one per pad from 0. The remaining pads stay
    # dark and unbound, because a lit pad that does nothing is the fault this
    # surface must never commit. APPEND-ONLY - a snapshot may store the name,
    # so an existing entry never moves index. drop and chance shipped with
    # package 1; half and double joined them with package 3.
    ARM_MACROS = ("drop", "chance", "half", "double", "break",
                  "ratchet", "gate")

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
    def phase_error(pos, ref, length):
        """Signed distance from `ref` to `pos` around a pattern of `length`
        clocks, in [-length/2, +length/2). None if the length is unusable.

        The phrase clock integrates getTempo() against the MONOTONIC clock
        while the sequencer advances on the AUDIO clock. Measured 2026-08-21:
        they slip 3,896 ppm - a whole bar every 8.3 minutes - linearly, which
        is what makes a gentle correction possible at all.
        `notes/findings/2026-08-21-phrase-clock-drift.md`.

        SIGNED AND WRAPPED, because both halves matter. Unsigned would not say
        which way to nudge, and unwrapped would read a two-clock error across
        the loop point as `length - 2` and jerk the clock most of a bar in the
        wrong direction - once per pattern, for ever."""

        length = float(length or 0.0)
        if length <= 0.0:
            return None
        delta = (float(pos) - float(ref)) % length
        if delta >= length / 2.0:
            delta -= length
        return delta

    @staticmethod
    def freeze_memo(memo, live, frozen):
        """Countdowns, held still for as long as the machine is.

        `live` is {macro: bars remaining} as the queue reports it. While frozen
        each macro keeps the FIRST value seen; the moment the freeze lifts the
        memo empties and the live numbers take over again.

        The defect this exists for, measured 2026-08-21: the landing bar goes
        by while the queue is held, `remaining()` floors at zero, and the
        countdown then advertises *zero bars left* for as long as the player
        holds FREEZE - nine bars of it in the log - while nothing lands. The
        ruler and the number were saying the drop was about to happen. Only
        `FRZ` said otherwise, and two true-looking readings that disagree are
        worse than one.

        A macro armed DURING a freeze is memoised on its first sighting, so it
        is held from where it started rather than from zero.

        PURE, and the memo is returned rather than mutated: the driver calls
        this from the poll thread and reads it from the render path."""

        if not frozen:
            return {}
        return {macro: memo.get(macro, rem) for macro, rem in live.items()}

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
        at 125 BPM is 480 ms against a ~33 ms tick - but PendingQueue is
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
    # matters enough to say twice. MOD_RATES spans 250:1 - at 125 BPM one bar is
    # 1.92 s, so the twelve rates run from 31 s per cycle down to 0.12 s. The
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
    def device_reconnected(previous, current):
        """Has the controller been replaced since the last look?

        `previous` and `current` are identity tokens for the device node -
        None when it is not there. True means the surface the driver painted
        is gone and the one in front of the player is blank.

        This exists because the LED cache suppresses a write whose value has
        not changed, and after a replug that judgement is right about the
        driver and wrong about the hardware. On 2026-08-30 a wedged controller
        was cleared with a physical replug and came back with dark buttons,
        dark statics and dark screens; only the pads healed, because the pads
        are the one cache site with a ttl. The cure is the one _on_snapshot
        already uses for the same reason - empty the cache and repaint once -
        and this is the trigger it was missing.

        The udev rule restarts the daemon on plug and deliberately leaves the
        UI alone (PartOf= was rejected on measurement), so nothing else tells
        the driver. The node does: udev recreates /dev/maschine on every plug.

        A vanished device is NOT a reconnect - there is nothing to repaint
        while it is unplugged, and the debt is paid when it returns. That
        matters because the poll tick sees several ticks of absence, and a
        repaint per tick is a full surface rewrite once a second - the kind of
        traffic that wedges the controller in the first place.
        """
        return current is not None and current != previous

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
    def rate_word(rate_bars):
        """A rate as a short word: 16B, 4B, 1B, 1/2, 1/16.

        Bars above one read as a count; below one as the fraction, because
        "0.25B" is a number nobody thinks in and "1/4" is the word already
        printed on the DIVIDE column."""
        if rate_bars is None:
            return ""
        if rate_bars >= 1.0:
            return f"{int(round(rate_bars))}B"
        return f"1/{int(round(1.0 / rate_bars))}"

    @staticmethod
    def mod_rate_label(label, active, rate_bars=None):
        """MOD's label carries the LAST-BOUND modulator's rate.

        Owner's idea, 2026-08-20, and it replaces something better than it
        replaces nothing: the moving tick inside the bar showed where the wave
        was in real time, and that animation is what wedged the controller -
        every pixel of movement rebuilt both screens, ~190 messages a second.

        A NUMBER carries the useful half of that - how fast is this thing
        moving - and changes only when the rate does, so it costs one repaint
        per decision instead of six a second forever."""
        if not active:
            return label
        word = techno_lib.rate_word(rate_bars)
        return f"{label} MOD {word}" if word else f"{label} MOD"

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
    # ------------------------------------------------------------------
    # CC PROVENANCE. Working rule 7 in data rather than in prose.
    #
    # The rule these sets exist to enforce: a CC is MEASURED only if a capture
    # log or a probe round records it. Everything else is UNKNOWN - not free.
    # TEMPO taught this the hard way: it is CC 35, it appears NOWHERE in the G4
    # capture because nobody pressed it that day, and for months an unlisted CC
    # read as available surface simply because no list said otherwise.
    #
    # Sources are named per set. Do not add a number here from a daemon token
    # name; the daemon's names have been attached to the wrong physical buttons
    # twice.

    # notes/findings/2026-08-11-g4-capture.log - the raw aseqdump log. Exactly
    # 24 distinct controller numbers, extracted mechanically from the log.
    CCS_MEASURED_G4 = frozenset({
        4, 5, 6, 11, 12, 13, 14, 15, 25, 26, 27, 29,
        30, 31, 32, 33, 34, 37, 38, 47, 48, 49, 50, 51,
    })

    # notes/findings/2026-08-12-g5-capture.log - REC and the eight encoders.
    CCS_MEASURED_G5 = frozenset({3}) | frozenset(range(16, 24))

    # Single-button captures after the two gates.
    #   10 NOTE REPEAT, 2026-08-15 - NO LOG FILE WAS KEPT. Weakest record in
    #      the bound set; treat it as measured but know why it is the weakest.
    #   35 TEMPO, 2026-08-16 -
    #      notes/findings/2026-08-16-tempo-cc-and-encoder-sensitivity.md
    CCS_MEASURED_SINGLE = frozenset({10, 35})

    CCS_MEASURED = CCS_MEASURED_G4 | CCS_MEASURED_G5 | CCS_MEASURED_SINGLE

    # No capture log exists for these, and that is NOT a hazard: a button that
    # visibly does its job every session is verified by use, which is stronger
    # evidence than a log. Listed separately so "it is in a capture log" is
    # never confused with "it is verified".
    #   1 PLAY - 2 ERASE - 7 RESTART - 39..46 F1..F8 - 80..87 Groups A..H
    CCS_VERIFIED_BY_USE = (frozenset({1, 2, 7})
                           | frozenset(range(39, 47))
                           | frozenset(range(80, 88)))

    # Anything a binding may legitimately sit on.
    CCS_KNOWN = CCS_MEASURED | CCS_VERIFIED_BY_USE

    # Measured, and nothing claims them - the only numbers a new feature may
    # take without a fresh capture. 27, 30, 33 and 34 were on this list and are
    # spent: FREEZE, ARM, the mute grid and the NAVIGATE phrase page.
    #
    # CC 6 (STEP >) came off on 2026-08-21, and how it came off is the point.
    # notes/findings/2026-08-20-cc-and-led-audit.md still calls it
    # MEASURED-AND-FREE in its own table, three lines above a note saying beat
    # repeat took it. That contradiction sat in the definitive audit for a day
    # and was caught the moment the list became a test instead of prose.
    # 29 (DUPLICATE) was SPENT on 2026-09-01 by the bank overlay. Two left:
    # 5 (TL, transport left-step) and 12 (the big encoder press). The test on
    # this set is what caught the double-claim the moment the binding landed,
    # which is the reason it is a test and not a comment.
    CCS_MEASURED_AND_UNCLAIMED = frozenset({5, 12})

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
        # DUPLICATE. CC 29 is one of the three in CCS_MEASURED_AND_UNCLAIMED -
        # measured in the G4 capture, and `grep duplicate daemon/src/main.rs`
        # shows a plain CC forward with no side effect. LED index 21 MEASURED
        # 2026-08-15. Both halves of working rule 7 are satisfied and neither
        # was read off a token name.
        #
        # HELD, never latched, exactly like MUTE: a latched arrangement picker
        # is state a player can walk away from, and the pads would stop being
        # the step picture until they noticed.
        #
        # DUPLICATE sits in the same physical row as SELECT (ARM), SOLO and
        # MUTE - the row this surface already spends on pad overlays.
        29: "bank",
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
    def generated_channels(owners, count=8, moves=None, roll=None):
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
        out = []
        for ch in range(count):
            if owners.get(ch, "gen") == "player":
                continue
            if moves is not None:
                # One roll per channel, drawn only for the channels that get
                # this far - so a locked or player-owned channel never costs
                # one, and a test can hand over an exact sequence.
                move = moves.get(ch, 100)
                if not techno_lib.move_allows(
                        move, None if roll is None else roll()):
                    continue
            out.append(ch)
        return tuple(out)

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
    # An optional THIRD element formats the value. Only MOVE has one: 0 there
    # means the machine may not touch the channel, and this instrument already
    # says that with the word LOCK (RANDOM, RHYTHM, WALK). A bare 0 on a page
    # about what the machine may do is exactly the kind of silence law L4
    # exists to forbid.
    SPREAD_SPECS = {
        "level":  ("uni", lambda v: v / 100.0),
        "reverb": ("uni", lambda v: v / 100.0),
        "delay":  ("uni", lambda v: v / 100.0),
        "chance": ("uni", lambda v: v / 100.0),
        "rhythm": ("uni", lambda v: v / 100.0),
        "swing":  ("uni", lambda v: (v - 50) / 25.0),
        "cutoff": ("uni", lambda v: v / 127.0),
        "reso":   ("uni", lambda v: v / 127.0),
        "move":   ("uni", lambda v: v / 100.0,
                   lambda v: "LOCK" if v <= 0 else techno_lib._num(v)),
        "lane":   ("uni", lambda v: v / 100.0,
                   lambda v: "RAW" if v <= 0 else techno_lib._num(v)),
        "exit":   ("seg", lambda v: v / 4.0,
                   lambda v: "HARD" if v <= 0 else "%dbar" % v),
        "phrase": ("seg", lambda v: v / 4.0,
                   lambda v: "BAR" if v <= 1 else "%dbar" % v),
        "fill":   ("uni", lambda v: v / 100.0,
                   lambda v: "OFF" if v <= 0 else techno_lib._num(v)),
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
    def phase_reset(elapsed_beats, rate_bars, beats_per_bar=4):
        """The phase0 that puts a modulator at the START of its cycle at
        `elapsed_beats`.

        THIS IS THE SIDECHAIN PUMP, and the shape was never the missing part.
        A bar-rate gain LFO already ships: `level` is in MOD_TIMBRE, 1.0 bars
        is the default rate a new bind takes, depth is signed, and a
        negative-depth `ramp` is an instant rise on the downbeat falling
        linearly to the bar line. Bind that across the MIXER page's eight
        LEVEL columns and every strip pumps.

        In eight different phases. phase0 is captured at BIND time, on
        purpose - _mod_encoder says so in as many words, because scattered
        LFOs are what you want when eight of them are colouring eight
        different timbres. A pump is the one case where they must agree, and
        agreeing is what this function is for.

        Same expression the bind path already computes inline; extracted so
        the re-phase gesture and the bind cannot drift apart, and so it can be
        tested at all - the driver cannot be imported off a Pi."""

        if float(rate_bars) <= 0.0:
            return 0.0
        return (-techno_lib.mod_pos(0.0, elapsed_beats, rate_bars,
                                    beats_per_bar)) % 1.0

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

    # PAD PRESSURE. The MK2's pads stream 12-bit continuous pressure per pad,
    # and the daemon has always been able to emit it as polyphonic aftertouch -
    # `send_aftertouch` was hardcoded false from its first commit until
    # 2026-08-30, so nothing here is new hardware, only a switch nobody found.
    #
    # WHY IT IS SHAPED LIKE A MODULATOR. Pressure displaces a verb over the
    # value the player set, and the base/offset law applies unchanged: the
    # driver owns the base and writes base + offset, and the swept value is
    # never written back as the base. Squeeze a pad, let go, and the knob is
    # where you left it.
    #
    # WHY CUTOFF. It inherits the modulation law - a modulator may only drive a
    # verb that does NOT rewrite the pattern - so the target must be in
    # MOD_TIMBRE, and there is a test below that says so. GATE and VELO are the
    # cautionary tale: they read as timbre and are written by regenerating the
    # pattern, and an LFO on VELO destroyed a recorded take every 200 ms.
    #
    # VOICES ONLY, and that is a scope decision rather than a limitation: the
    # five drum channels play LinuxSampler one-shots that run to the end
    # regardless, and the drum filter (SP3) is shelved, so on a drum channel
    # there is no verb for pressure to move.
    PRESSURE_VERB = "cutoff"

    # Full pressure reaches the top of the verb's span. Less than 1.0 would
    # make the end stop unreachable by hand, which reads as a broken gesture
    # rather than as a gentle one.
    PRESSURE_DEPTH = 1.0

    # Release decay, as the fraction of the REMAINING offset shed per poll
    # tick (~200 ms). 0.35 lands a full squeeze back on the base in about
    # 1.5 s. A snap to base sounds like a fault; a slow glide sounds like a
    # filter closing, which is the point.
    PRESSURE_DECAY = 0.35

    # Below this the offset snaps to zero. It MUST snap: an asymptote leaves a
    # fraction of a surface unit sitting on the channel forever, the restore
    # write never happens, and the knob never gets its value back.
    PRESSURE_FLOOR = 0.5

    @staticmethod
    def pressure_display(view, verb, base):
        """The display's copy of a channel's state, with a live squeeze hidden.

        PURE, so it is tested on WSL where the driver cannot be imported.

        THE NUMBER ON THE GLASS MUST NOT MOVE WHILE A FINGER PRESSES. Pressure
        writes the swept value into state and the display renders state, so
        with pad pressure on, the screens repainted about thirty times a
        second: measured at the rig on 2026-08-31 as 110 OSC messages a second,
        of which 104 were display traffic against 5.6 for the pads. That is
        inside the band that wedges the controller off the USB bus, and a wedge
        needs a physical replug.

        This surface has already paid for this lesson once. _render_display's
        comment about the MOD tick that was taken out: "a number that changes
        when you change it, rather than an animation that rebuilt both screens
        six times a second and killed the controller." Pressure brought it back
        at five times the rate.

        It is also the modulation law, which was written down and not applied
        here: base and offset are separate, the driver owns the base, and the
        swept value is for the engine rather than for the knob. Pressure kept
        its base so the KNOB survived a squeeze; nothing kept the DISPLAY off
        the sweep.

        `base is None` means no squeeze is live, and the view is returned
        untouched. A base of ZERO is a real base - `if base:` would show the
        swept value at the bottom of the range, which is exactly where a filter
        sweep is most audible.
        """

        if base is None:
            return view
        out = dict(view)
        out[verb] = base
        return out

    @staticmethod
    def pressure_offset(value, lo, hi, depth=None):
        """Surface-unit offset for an aftertouch value 0-127.

        Scaled onto the VERB's span, not onto 0-127: a verb whose range is
        0-100 must not be pushed to 127 because the wire happens to carry
        seven bits."""
        if depth is None:
            depth = techno_lib.PRESSURE_DEPTH
        frac = max(0.0, min(1.0, float(value) / 127.0))
        return frac * max(0.0, float(depth)) * (float(hi) - float(lo))

    @staticmethod
    def pressure_value(base, offset, lo, hi):
        """`base` displaced by `offset`, clamped to the verb's range.

        Separate from mod_value() on purpose: this one takes an offset already
        in surface units, so a zero offset returns the base EXACTLY. That is
        the restore write, and a rounding error there leaves the knob somewhere
        the player never put it."""
        out = float(base) + float(offset)
        return max(float(lo), min(float(hi), out))

    @staticmethod
    def pressure_decay(offset, factor=None):
        """One poll tick of release decay. Snaps to zero under PRESSURE_FLOOR."""
        if factor is None:
            factor = techno_lib.PRESSURE_DECAY
        out = float(offset) * (1.0 - max(0.0, min(1.0, float(factor))))
        if out < techno_lib.PRESSURE_FLOOR:
            return 0.0
        return out

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
        "gate": "TIGHT",
        "gate_end": "UNTIGHT",
    }

    @staticmethod
    def pending_sort(entries):
        """Armed macros, soonest first, ties broken by name.

        A page whose columns reorder as the countdown runs is unreadable at a
        glance. This key only changes when something actually overtakes
        something else, which is a real event worth seeing."""
        return sorted(entries, key=lambda e: (int(e[1]), str(e[0])))

    @staticmethod
    def pending_columns(entries, frozen=False):
        """The eight columns of the PENDING page.

        `entries` is (macro, bars_left, armed_bars) per armed macro. Eight
        columns because the surface has eight; a ninth armed macro is not
        drawn, and nothing in this instrument can arm nine.

        WHILE THE MACRO QUEUE IS FROZEN EVERY COLUMN SAYS `HELD` INSTEAD OF
        A NUMBER. The number would be a countdown that is not counting, and
        once the landing bar has passed it reads `0000` forever - which says
        the drop is about to land at the exact moment it cannot. One word that
        is true beats four digits that are not.

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
                name, "HELD" if frozen else f"{int(left):04d}", "uni",
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
        spec = techno_lib.SPREAD_SPECS[verb]
        kind, to_frac = spec[0], spec[1]
        fmt = spec[2] if len(spec) > 2 else techno_lib._num
        out = []
        for letter, name, view in views:
            label = f"{letter} {name}"[:8]
            value = view.get(verb)
            if value is None:
                # Law L4 again: a column whose source does not exist draws
                # dead rather than drawing a lie.
                out.append(techno_lib._dead(label.lower()))
                continue
            out.append(techno_lib._col(label, fmt(value), kind,
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
                techno_lib._columns_inner(desc, kind, state, frozen),
                desc, mod, owned),
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
    def _columns_inner(desc, kind, state, frozen=False):
        """The 8 columns for a page. Reads state, never writes it. This is the
        single place where the greyed columns and the pending brackets are
        decided, so both are unit tested rather than eyeballed on hardware.

        `desc` is a page descriptor. For SHAPE_SPREAD, `state` is eight
        (letter, name, view) tuples; for the other two shapes it is one view
        dict, as it has always been."""
        if desc["shape"] == techno_lib.SHAPE_SPREAD:
            return techno_lib.spread_columns(desc, state)
        if desc["shape"] == techno_lib.SHAPE_PENDING:
            # The one page whose NUMBERS are wrong while frozen rather than
            # merely inert: a countdown that is not counting. Everything else
            # on a frozen page is a value the player may still move.
            return techno_lib.pending_columns(state, frozen)
        if desc.get("generated"):
            return techno_lib.generated_columns(desc, state)

        page = desc["title"]
        p = state.get("pending", set())
        n, c, dead = techno_lib._num, techno_lib._col, techno_lib._dead

        def rule_col():
            """RULE, on both kinds. RAND is a WORD, not a blank: the shift
            register is a choice the player made, and a column that showed
            nothing for it would read as a control that is not working."""
            rule = state.get("rule", techno_lib.RULE_RANDOM)
            index = (techno_lib.RULES.index(rule)
                     if rule in techno_lib.RULES else 0)
            return c("RULE", rule.upper() if rule != techno_lib.RULE_RANDOM
                     else "RAND", "seg", (index, len(techno_lib.RULES)))

        if page == "GEN" and kind == "drum":
            lean = state.get("lean", techno_lib.LEAN_OFF)
            index = (techno_lib.LEANS.index(lean)
                     if lean in techno_lib.LEANS else 0)
            return [
                rule_col(),
                # EUCL is a word, not a blank: euclid is a choice the player
                # made and the column has to say which generator is drawing.
                c("LEAN", techno_lib.LEAN_LABELS.get(lean, "EUCL"), "seg",
                  (index, len(techno_lib.LEANS))),
            ] + [dead("gen%d" % i) for i in range(3, 9)]


        if desc["shape"] == techno_lib.SHAPE_GLOBAL and page == "WALK":
            walk = state.get("walk", 0)
            return [
                c("ROOT", techno_lib.NOTE_NAMES[state["root"]], "seg",
                  (state["root"], 12), pending="root" in p),
                c("SCALE", techno_lib.SCALES[state["scale"]][0], "seg",
                  (state["scale"], len(techno_lib.SCALES)),
                  pending="scale" in p),
                # LOCK rather than 0000, the same word MELODY and RHYTHM use
                # at zero. A number here invites turning it down looking for
                # off, and there is nothing below zero.
                c("WALK", "LOCK" if walk <= 0 else "%dbar" % walk, "seg",
                  (walk, 17)),
                c("SPAN", n(state.get("wspan", 2)), "uni",
                  state.get("wspan", 2) / 7.0),
                dead("walk5"), dead("walk6"), dead("walk7"), dead("walk8"),
            ]

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
                # The drum rhythm register's evolve knob, 0 = LOCK, exactly
                # as it reads on a voice. SWING moved to the spread page in
                # the same round - see the verbs tuple for why.
                c("RHYTHM", n(state.get("rhythm", 0)), "uni",
                  state.get("rhythm", 0) / 100.0),
                # SP10 step 3: the page's dead eighth column, filled. OFF at 1
                # rather than "1", because one hit is not a ratchet and reading
                # "1" invites turning it down looking for off.
                c("RATCH", "OFF" if state.get("ratchet", 1) <= 1
                  else "x%d" % state["ratchet"], "seg",
                  (max(0, state.get("ratchet", 1) - 1), 4)),
            ]
        if page == "GEN":
            # ORDER MUST MATCH the GEN page's verbs tuple position for
            # position, exactly as the STEP page's list does below.
            model = state.get("model", techno_lib.MODEL_REGISTER)
            walking = model == techno_lib.MODEL_WALK
            feed = state.get("feed")
            length = max(1, state.get("length", 8))
            return [
                c("ROTATE", n(state.get("rotate", 0)), "seg",
                  (state.get("rotate", 0), 16)),
                c("MODEL", "WALK" if walking else "REG", "seg",
                  (1 if walking else 0, len(techno_lib.MODELS))),
                # SPAN and STRIDE belong to the walk and mean nothing to the
                # register - drawn dead on the register model rather than
                # showing a number the knob cannot make audible. Law L4.
                c("SPAN", n(state.get("walk_span", 32)), "uni",
                  state.get("walk_span", 32) / 128.0) if walking
                else dead("span"),
                c("STRIDE", n(state.get("walk_stride", 4)), "uni",
                  state.get("walk_stride", 4) / 32.0) if walking
                else dead("stride"),
                # OFF, not a channel letter, when nothing is feeding this
                # voice. A coupling that is not coupled has to say so.
                c("FEED", "OFF" if feed is None else "ABCDEFGH"[feed % 8],
                  "seg", (0 if feed is None else feed + 1, 9)),
                c("AMT", n(state.get("amount", 0)), "uni",
                  state.get("amount", 0) / 100.0),
                rule_col(), dead("gen8"),
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

    @staticmethod
    def session_log_path(environ):
        """Where the play-session log goes, or None for off.

        PURE, so it is testable on WSL where the driver cannot be imported.

        THE LOG STAYS OFF BY DEFAULT. That is not timidity: it was measured.
        Roughly six log lines a second through journald was enough to make the
        daemon's reader run late and wedge the controller off the USB bus on
        2026-08-20, and a log that writes for every player is a cost paid for a
        problem they do not have.

        What this changes is HOW it is turned on. It used to be a constant to
        edit on the rig, which leaves the deployed file one line different from
        every commit - the hazard that cost a checksum hunt on 2026-08-31, when
        the Pi had to be diffed against five commits to find out what it was
        running. A systemd drop-in setting MASCHINE_SESSION_LOG turns it on and
        leaves the source byte-identical to what was shipped.

        Three things are REFUSED rather than resolved, and each has a failure
        behind it:

        - A RELATIVE path. The driver's working directory is whatever systemd
          gave it, so the file lands somewhere nobody chose and nobody can
          find. Refusing is louder than guessing.
        - A DIRECTORY. `open(dir, "a")` raises, the driver catches it and logs
          one warning, and the rig then reads as "logging is on" while nothing
          is ever written - the exact shape of a silent failure this project
          keeps finding.
        - THE JOURNAL, by any of its device aliases. This log exists because
          journald could not carry it. Letting somebody ask for it by accident
          would rebuild the fault it was built to avoid.
        """

        raw = (environ.get("MASCHINE_SESSION_LOG") or "").strip()
        if not raw:
            return None
        if not raw.startswith("/") or raw.endswith("/"):
            return None
        if raw in ("/dev/stdout", "/dev/stderr", "/dev/fd/1", "/dev/fd/2"):
            return None
        return raw

    @staticmethod
    def session_line(stamp, tag, fields):
        """One line of the play-session event log.

        PURE, so it is testable on WSL where the driver cannot be imported -
        the driver owns the file handle and this owns the grammar.

        `stamp` is seconds since the epoch, printed to the millisecond because
        the questions this log exists to answer are ordering questions: did
        the freeze latch before or after the bar tick that should have fired
        the macro.

        The format is `HH:MM:SS.mmm tag key=value key=value`, deliberately
        greppable by tag and by key: a session is read with grep, never by
        eye. None prints as `-` rather than being dropped, because a field
        that is sometimes absent makes a column that cannot be counted."""

        ms = int((stamp % 1.0) * 1000)
        clock = time.strftime("%H:%M:%S", time.localtime(stamp))
        parts = [f"{clock}.{ms:03d}", str(tag)]
        for key, value in fields.items():
            if value is None:
                value = "-"
            elif isinstance(value, bool):
                value = "1" if value else "0"
            elif isinstance(value, (list, tuple, set, frozenset)):
                value = ",".join(str(v) for v in sorted(value)) or "-"
            parts.append(f"{key}={value}")
        return " ".join(parts) + "\n"

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

    class BankPin:
        """The zynseq bank the driver is working in, HELD rather than followed.

        NESTED for the same reason as PendingQueue: the driver imports the
        CLASS, so a module-level class here would be unreachable through
        `tlib` and would raise AttributeError on the rig, where nothing
        catches it early.

        The defect this closes: ten driver sites READ `zynseq.bank` and
        nothing ever asserted it, so an external bank change - the
        touchscreen, a snapshot, a CUIA - repointed every zynseq call while
        every Python-side cache still described the old bank. No log, no
        symptom, until something sounded wrong. Latent while one bank exists;
        live the moment banks-as-scenes does.

        A drift is ADOPTED, not refused. Refusing looks safer and is worse:
        the driver would keep writing into a bank the sequencer is no longer
        playing, which is silence with nothing explaining it. Adopting and
        SAYING SO leaves the caller a place to resync from.

        No zynseq, no driver, no logging of its own - which is what makes it
        testable on WSL, where the driver cannot be imported."""

        BANKS = (1, 64)          # zynseq.select_bank refuses anything outside

        def __init__(self):
            self.bank = None
            self.drifts = 0
            self._said = None    # the bank a drift was last reported ABOUT

        def pin(self, bank):
            """Take a bank deliberately: init, or a snapshot that has already
            resynced everything. Not a drift, so it never counts as one.

            Returns a message when the bank being pinned is not one zynseq
            could address. It is still taken - refusing would leave the driver
            with no bank at all - but a rig that pins a 0 has something wrong
            upstream and must not find that out later, from the once-a-second
            check, as a drift it is not."""

            self.bank = bank
            self._said = None
            lo, hi = self.BANKS
            if not isinstance(bank, int) or isinstance(bank, bool) \
                    or not lo <= bank <= hi:
                return (f"pinned zynseq bank {bank!r}, outside {lo}-{hi}. "
                        f"Every sequence address this driver builds uses it.")
            return None

        def observe(self, bank):
            """Compare what zynseq says against what is held. Returns a
            message when the caller must act, None when there is nothing to
            say.

            Reported ONCE per drift, not once per tick: this is called about
            once a second forever, and a message per tick would bury the
            journal and teach the next reader to skip it. Drifting back is a
            second drift and is reported again."""

            lo, hi = self.BANKS
            if not isinstance(bank, int) or isinstance(bank, bool) \
                    or not lo <= bank <= hi:
                # Out of range means something upstream is unset. Adopting it
                # would address a bank that cannot exist, so hold what we have
                # and say so - once.
                if self._said == bank:
                    return None
                self._said = bank
                return (f"zynseq bank reads {bank!r}, outside {lo}-{hi}. "
                        f"Holding bank {self.bank}.")
            if self.bank is None:
                # Nothing has been pinned yet - init has not run. The first
                # answer is the answer, not a drift.
                self.bank = bank
                return None
            if bank == self.bank:
                self._said = None
                return None
            was, self.bank = self.bank, bank
            self.drifts += 1
            if self._said == bank:
                return None
            self._said = bank
            return (f"zynseq bank moved {was} -> {bank} from outside this "
                    f"driver; adopting it and resyncing (drift {self.drifts}).")


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
        # Encoder 7 carries RHYTHM rather than SWING, 2026-08-31 - the same
        # trade the owner made on the voice page in 2026-08-16 and for the
        # identical reason, written there as "it is the only slot on a full
        # page whose verb has a second home, and swing is on the spread page
        # below for every channel at once, which is where it is wanted in a
        # jam". The drum page simply never got the same treatment.
        _d(techno_lib.SHAPE_CHANNEL, "STEP",
           verbs=("hits", "rotate", "div", "length", "velo", "chance",
                  "rhythm", "ratchet")),
        _d(techno_lib.SHAPE_SPREAD, "SWING", verb="swing"),
        _d(techno_lib.SHAPE_SPREAD, "CHANCE", verb="chance"),
        # GEN, 2026-09-01. The drum ring has been one page shorter than the
        # voice ring since the GEN page shipped, and a new page in an existing
        # ring costs no button, no capture and no overlay - the cheapest
        # surface on this instrument. Column 1 only for now; the leaning
        # generator has a named home in column 2 when it is built.
        _d(techno_lib.SHAPE_CHANNEL, "GEN",
           verbs=("rule", "lean", None, None, None, None, None, None)),
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
        # P1, 2026-08-31. Three features on one new page, which is the whole
        # reason they were built together: a new page in an existing ring
        # costs no button, no measurement and no pad overlay, and the free
        # button budget for the whole instrument is three CCs.
        _d(techno_lib.SHAPE_CHANNEL, "GEN",
           # THE VERB NAMES ARE THE STATE KEYS. `walk_span`, not `wspan`:
           # _verb looks the verb up in VERB_RANGES and param_get reads it
           # straight out of the state dict, so a page verb that does not
           # name a real key is a knob that silently does nothing. The
           # GLOBAL walk page's `wspan` is a different value in a different
           # table - the walker's span, not this voice's.
           verbs=("rotate", "model", "walk_span", "walk_stride", "feed",
                  # RULE is its own column and NOT a value on MODEL, 2026-09-01.
                  # MODEL chooses where the pitch values come from; RULE
                  # chooses how the rhythm register evolves. One knob showing
                  # one word must not decide two axes.
                  "amount", "rule", None)),
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
        # The chord walker. ROOT and SCALE are repeated from the GLOBAL page
        # deliberately - the walker moves the root, and a page that hid the
        # thing it moves would make the player page back and forth to see the
        # effect of the knob under their hand.
        _d(techno_lib.SHAPE_GLOBAL, "WALK",
           verbs=("root", "scale", "walk", "wspan", None, None, None, None)),
        # MOVE, 2026-09-01. A SPREAD, because the question it answers is about
        # all eight at once - "which of these may the machine touch tonight" -
        # and a per-channel column on a channel page would make the player walk
        # eight pages to read one answer. It is on the ALL ring rather than
        # STEP because it governs every automatic gesture, not the generators
        # alone: the four bar-rate macros and the chord walker are exactly the
        # ones that never asked.
        _d(techno_lib.SHAPE_SPREAD, "MOVE", verb="move"),
        # LANE, 2026-09-01. A spread beside MOVE because it answers the
        # neighbouring question - MOVE is how OFTEN the machine may touch a
        # channel, LANE is how FAR it may go when it does - and both are read
        # for all eight at once. The three voices draw dead here by law L4:
        # the verb does not exist on them, and pretending otherwise would put
        # a knob on the page that quietly undoes hand-tapped steps.
        _d(techno_lib.SHAPE_SPREAD, "LANE", verb="lane"),
        # EXIT, 2026-09-01. How a channel LEAVES. It belongs beside MOVE and
        # LANE because the three are one question asked three ways - how
        # often, how far, and how it goes - and because an arrangement gesture
        # is read for all eight at once or it is not read at all.
        _d(techno_lib.SHAPE_SPREAD, "EXIT", verb="exit"),
        # A PHRASE, NOT A BAR, 2026-09-01. Two spreads rather than one page of
        # pairs: the question "which channels are on a four-bar phrase" and the
        # question "how full is the fill" are asked at different moments, and
        # each is read across all eight at once.
        _d(techno_lib.SHAPE_SPREAD, "PHRASE", verb="phrase"),
        _d(techno_lib.SHAPE_SPREAD, "FILL", verb="fill"),
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
