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
        density can only remove a step - never move one."""
        count = int(round(max(0.0, min(1.0, density)) * steps))
        values = techno_lib.gate_values(register, length, steps)
        order = sorted(range(steps), key=lambda i: (values[i], i))
        chosen = set(order[:count])
        return tuple(i in chosen for i in range(steps))

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
    def kit_line(register, length, steps, kit_notes):
        """The Turing walk across a drum kit instead of across a scale.

        On the shipped SFZ kits a note number selects WHICH SAMPLE sounds -
        key=/lokey= maps notes to different drums - so quantising to ROOT and
        SCALE would land most steps on empty keys. An empty key is silence
        with nothing to explain it, which is the one thing this instrument
        must never do.

        Same rotations as line(), mapped onto the kit's own notes. Returns []
        for an empty kit; the caller falls back to the channel's own note
        rather than the library inventing one."""
        if not kit_notes:
            return []
        count = len(kit_notes)
        out = []
        for value in techno_lib.rotations(register, length, steps):
            idx = (value * count) >> length
            out.append(kit_notes[min(count - 1, max(0, idx))])
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
        "voice": frozenset(("length", "div", "random")),
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
        if verb == "random":
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
            state.update(kit="----", sample="----")
        else:
            state.update(
                preset="----", cutoff=64, reso=32, env=64, decay=40,
                random=0, gate=40, octave=0, range=2,
                # 100 is every step, which is what the voices did before
                # density existed - a snapshot without the key restores to it
                # and sounds unchanged.
                density=100,
                # LENGTH on a voice is the shift register's length in bits,
                # not the pattern's length in beats - a different parameter
                # wearing the same word, so it lives in the dict and never in
                # the legacy beats array.
                length=8, register=0b10110011, ring=deque(maxlen=4))
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

    # Buttons whose release is also an event: the driver tracks them across
    # press and release, so they are dispatched before the press-only filter.
    BUTTONS_STATEFUL = {
        2: "erase",
        3: "rec",
        49: "shift",
        31: "solo",
    }

    # Buttons that act on press only.
    BUTTONS_PRESS = {
        1: "play",
        4: "grid",
        7: "restart",
        13: "sound_prev",
        14: "sound_next",
        29: "duplicate",
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

    @staticmethod
    def _num(v):
        return f"{int(round(v)):04d}"

    @staticmethod
    def _col(name, value, bar=None, frac=0.0, grey=False, pending=False):
        if pending:
            value = f">{value}<"
        return {"name": name, "value": value, "bar": bar, "frac": frac,
                "grey": grey, "pending": pending}

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
        "density": ("uni", lambda v: v / 100.0),
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

    # Generated pages address a plugin port directly, so their verb names carry
    # a prefix the driver's _verb() dispatches on:
    #   lv2:<symbol>          - the selected channel's synth processor
    #   fx:<which>:<symbol>   - ganged across every channel's <which> insert
    VERB_LV2 = "lv2:"
    VERB_FX = "fx:"

    PORT_LABEL_CHARS = 8

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

    @staticmethod
    def generated_columns(desc, state):
        """Columns for a generated page. The surface value is 0-100; the driver
        scales it onto each port's own range, as _set_ganged() already does for
        the hand-written FX roles."""
        out = []
        for verb in desc["verbs"]:
            if verb is None:
                out.append(techno_lib._col("", "", None, 0.0))
                continue
            symbol = verb.split(":")[-1]
            value = state.get(verb)
            if value is None:
                out.append(techno_lib._dead(techno_lib.port_label(symbol).lower()))
                continue
            out.append(techno_lib._col(techno_lib.port_label(symbol),
                                       techno_lib._num(value), "uni",
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
    def columns(desc, kind, state):
        """The 8 columns for a page. Reads state, never writes it. This is the
        single place where the greyed columns and the pending brackets are
        decided, so both are unit tested rather than eyeballed on hardware.

        `desc` is a page descriptor. For SHAPE_SPREAD, `state` is eight
        (letter, name, view) tuples; for the other two shapes it is one view
        dict, as it has always been."""
        if desc["shape"] == techno_lib.SHAPE_SPREAD:
            return techno_lib.spread_columns(desc, state)
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
                    c("KIT", state["kit"], "seg", (0, 1), pending="kit" in p),
                    c("SAMPLE", state["sample"], "seg", (0, 1), pending="sample" in p),
                    dead("tune"), dead("decay"), dead("filtr"),
                ] + tail
            # A column is live only where the running plugin publishes a
            # symbol for that role. Per column, not per channel: a sampler
            # behaving as a voice has none of the four (SP4), and a synth the
            # measured table has never seen may publish three of them.
            # Law L4 - draw dead, never a number the knob cannot move.
            live = techno_lib.synth_ctrl_flags(state)
            return [
                c("PRESET", state["preset"], "seg", (0, 1), pending="preset" in p),
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
                dead("ratchet"),
            ]
        return [
            c("LENGTH", n(state["length"]), "uni", state["length"] / 16.0,
              pending="length" in p),
            c("DIVIDE", techno_lib.DIVISION_LABELS[state["div"]], "seg",
              (state["div"], len(techno_lib.DIVISION_LABELS)), pending="div" in p),
            # LOCK is a word, not a number that could be a coincidence
            c("RANDOM", "LOCK" if state["random"] <= 0 else n(state["random"]), "uni",
              state["random"] / 100.0),
            c("GATE", n(state["gate"]), "uni", state["gate"] / techno_lib.GATE_MAX),
            c("OCTAVE", f"{state['octave']:+03d}", "bi", (state["octave"] + 2) / 4.0),
            c("RANGE", str(state["range"]), "seg", (state["range"] - 1, 4)),
            c("DENSITY", n(state["density"]), "uni", state["density"] / 100.0),
            c("VELO", n(state["velo"]), "uni", state["velo"] / 127.0),
        ]


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
                  "swing", None)),
        _d(techno_lib.SHAPE_SPREAD, "SWING", verb="swing"),
        _d(techno_lib.SHAPE_SPREAD, "CHANCE", verb="chance"),
    ),
    # Encoder 7 carries DENSITY rather than SWING: it is the only slot on a
    # full page whose verb has a second home, and swing is on the spread page
    # below for every channel at once, which is where it is wanted in a jam.
    ("STEP", "voice"): (
        _d(techno_lib.SHAPE_CHANNEL, "STEP",
           verbs=("length", "div", "random", "gate", "octave", "range",
                  "density", "velo")),
        _d(techno_lib.SHAPE_SPREAD, "SWING", verb="swing"),
        _d(techno_lib.SHAPE_SPREAD, "CHANCE", verb="chance"),
        _d(techno_lib.SHAPE_SPREAD, "DENSITY", verb="density"),
    ),
    ("ALL", None): (
        _d(techno_lib.SHAPE_GLOBAL, "GLOBAL",
           verbs=("root", "scale", "bpm", "master", "revsize", "revtype",
                  "dlytime", "dlyfbk")),
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
