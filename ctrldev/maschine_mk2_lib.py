#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Pure helper logic for the Maschine MK2 drum rig ctrldev driver.
#
# Imports nothing from Zynthian on purpose: the unit tests load this module
# directly by path, and importing the zyngine package pulls in every engine.
#
# The class name matches the filename because the ctrldev loader does
# getattr(module, module_name). dev_ids is empty so no device ever matches it.

import struct


class maschine_mk2_lib:

    dev_ids = []

    # (label, steps_per_beat, beats) — steps_per_beat * beats == step count
    #
    # APPEND ONLY. A snapshot stores the division as an INDEX into this tuple,
    # so inserting "1/4" in musical order would silently re-point every saved
    # pattern at a different division, with no error anywhere.
    #
    # "1/4" is the slowest step this API can express: steps_per_beat is an
    # integer >= 1, so a step can never be longer than one beat. Sixteen of
    # them is four bars, which is the longest pattern reachable without
    # paging the pads.
    DIVISIONS = (
        ("1/32", 8, 2),
        ("1/16", 4, 4),
        ("1/8", 2, 8),
        ("1/16T", 6, 2),
        ("1/8T", 3, 4),
        ("1/4", 1, 16),
    )

    @staticmethod
    def step_count(div_idx):
        """Number of steps a division yields: 16 straight, 12 triplet"""

        _, spb, beats = maschine_mk2_lib.DIVISIONS[div_idx]
        return spb * beats

    @staticmethod
    def euclid(steps, hits):
        """Bresenham placement, identical to the daemon's sequencer.rs:
        hit i lands on floor(i * steps / hits), so hit 0 is always step 0"""

        pattern = [False] * steps
        hits = max(0, min(hits, steps))
        for i in range(hits):
            pattern[(i * steps) // hits] = True
        return pattern

    @staticmethod
    def rotate(pattern, offset):
        """Rotate a pattern forward in time, wrapping at the end"""

        n = len(pattern)
        if n == 0:
            return []
        offset %= n
        return pattern[-offset:] + pattern[:-offset] if offset else list(pattern)

    @staticmethod
    def build_pattern_steps(steps, hits, rotation):
        """Full pattern from an explicit step count. Pattern length is set
        independently of division so groups can run different lengths against
        each other, so the step count is not always a division's own."""

        return maschine_mk2_lib.rotate(
            maschine_mk2_lib.euclid(steps, hits), rotation
        )

    @staticmethod
    def build_pattern(div_idx, hits, rotation):
        """Full pattern at a division's natural length"""

        return maschine_mk2_lib.build_pattern_steps(
            maschine_mk2_lib.step_count(div_idx), hits, rotation
        )

    @staticmethod
    def clamp_to_steps(value, div_idx):
        """Clamp a hit count or rotation into a division's step range"""

        return max(0, min(value, maschine_mk2_lib.step_count(div_idx)))

    # --- SFZ kits ------------------------------------------------------
    #
    # A kit's note list cannot come from Zynthian's keymaps.json: that
    # resolves on the synth's preset path and matches only the FluidSynth
    # soundfonts, so an SFZ kit would leave every group tab reading
    # "note 36". The kit files carry the information themselves.

    @staticmethod
    def parse_sfz_notes(text):
        """The playable notes of an SFZ kit, as [(note, NAME)] sorted by note.

        One entry per distinct key: kits split a key into several <region>
        blocks by velocity (lovel/hivel), and those are the same drum sound,
        so the first one wins. The name is the sample's filename without
        directory or extension."""

        notes = {}
        sample = None
        for raw in text.replace("<region>", "\n<region>").splitlines():
            line = raw.strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("<"):
                sample = None                     # a new block, name not seen yet
            if "sample=" in line:
                # Extract sample path: everything after sample= until the next
                # directive (word=) or end of line
                start = line.find("sample=") + 7
                rest = line[start:].strip()
                # Find where the next directive starts (space + word + =)
                end = len(rest)
                for i, char in enumerate(rest):
                    if char == ' ':
                        # Check if what follows is a directive
                        after_space = rest[i+1:]
                        if '=' in after_space:
                            word_before_eq = after_space.split('=')[0].split()[0]
                            if word_before_eq and word_before_eq[0].isalpha():
                                end = i
                                break
                sample = rest[:end].strip()
            # Extract lokey or key (but not hikey). We must check lokey first to
            # avoid substring collision: "hikey=" contains "key=".
            note = None
            if "lokey=" in line:
                value = line.split("lokey=")[1].split()[0]
                try:
                    note = int(value)
                except ValueError:
                    pass
            elif "key=" in line and "hikey=" not in line and "pitch_keycenter=" not in line:
                value = line.split("key=")[1].split()[0]
                try:
                    note = int(value)
                except ValueError:
                    pass
            if note is not None and note not in notes and sample:
                notes[note] = maschine_mk2_lib._sample_label(sample)
        return sorted(notes.items())

    @staticmethod
    def _sample_label(sample):
        """A drum name from a sample path: strip the directories and the
        extension, turn underscores into spaces, uppercase."""

        leaf = sample.replace("\\", "/").rsplit("/", 1)[-1]
        if "." in leaf:
            leaf = leaf.rsplit(".", 1)[0]
        return leaf.replace("_", " ").strip().upper()

    # The double-height value cell fits 4 characters, and a drum machine's
    # familiar name is rarely its first four letters. Machines people name by
    # their number get it; everything else is shortened mechanically.
    KIT_SHORT_NAMES = {
        "Roland TR808": "808", "Roland TR909": "909", "Roland TR727": "727",
        "Roland TR606": "606", "Roland CR78": "CR78", "LINN9000 1": "LN90",
        "LINN9000 2": "LN91", "SP1200 1": "1200", "SP1200 2": "1201",
        "SP 12": "SP12", "DYNOSAUR-808": "DYNO", "Boss DR220": "DR22",
        "Boss DR55": "DR55", "Korg DDD1": "DDD1", "Korg DDM110": "DDM1",
        "Kawai R50": "R50", "Akai XR10": "XR10", "Akai XE8": "XE8",
        "Alesis HR16": "HR16", "Yamaha RX11": "RX11", "MXR 185": "M185",
        "Fricke MSB512": "MSB5", "Simmons": "SIMM", "DrumTraks": "TRAK",
        "Acetone Rhythm Ace": "ACET", "Mattel Synsonic": "MSYN",
        "Drumula 1": "DRU1", "Drumula 2": "DRU2",
        "Tyson 1": "TYS1", "Tyson 2": "TYS2", "Tyson 3": "TYS3",
    }

    @staticmethod
    def kit_short_name(name):
        """At most 4 characters for the KIT cell on the screen."""

        if not name:
            return "-"
        short = maschine_mk2_lib.KIT_SHORT_NAMES.get(name)
        if short:
            return short[:4]
        words = [w for w in name.replace("-", " ").split() if w]
        if len(words) > 1:
            # Initial of each leading word plus as much of the last as fits.
            head = "".join(w[0] for w in words[:-1])
            short = (head + words[-1])[:4]
        else:
            short = words[0][:4] if words else "-"
        return short.upper()

    @staticmethod
    def nearest_note(available, wanted):
        """The note in `available` closest to `wanted`, ties going to the
        lower one. Kits number their sounds differently, so a group's note
        usually does not exist in a kit it has just been given - landing on
        the nearest keeps it audible instead of silent."""

        if not available:
            return None
        return min(sorted(available), key=lambda n: (abs(n - wanted), n))

    @staticmethod
    def _osc_pad(data):
        """Pad a byte string to the next multiple of 4"""

        return data + b"\x00" * ((4 - len(data) % 4) % 4)

    @staticmethod
    def osc_message(path, args):
        """Minimal OSC 1.0 encoder. int (i), float (f) and string (s) are all
        the daemon's handler accepts (main.rs:609-665)"""

        out = maschine_mk2_lib._osc_pad(path.encode("ascii") + b"\x00")
        tags = ","
        body = b""
        for arg in args:
            if isinstance(arg, bool):
                raise TypeError("OSC bool not supported by the daemon")
            if isinstance(arg, int):
                tags += "i"
                body += struct.pack(">i", arg)
            elif isinstance(arg, float):
                tags += "f"
                body += struct.pack(">f", arg)
            elif isinstance(arg, str):
                tags += "s"
                body += maschine_mk2_lib._osc_pad(arg.encode("ascii", "replace") + b"\x00")
            else:
                raise TypeError(f"unsupported OSC argument type: {type(arg)}")
        out += maschine_mk2_lib._osc_pad(tags.encode("ascii") + b"\x00")
        return out + body

    @staticmethod
    def pad_osc(pad, color, brightness):
        """LED write for one pad. Pad 0 is bottom-left (daemon commit a42ff17)"""

        return maschine_mk2_lib.osc_message("/maschine/pad", [int(pad), int(color), float(brightness)])

    @staticmethod
    def button_osc(name, color, brightness):
        """LED write for one named button, e.g. 'f1', 'group_a', 'play'"""

        return maschine_mk2_lib.osc_message(
            f"/maschine/button/{name}", [int(color), float(brightness)])

    # --- screens -------------------------------------------------------
    #
    # Each screen is 255x64, verified on the hardware (MD/display-investigation
    # .md, first section). Screen 0 is the left panel, 1 the right. Four
    # columns of 64 px line the layout up with the four encoders below each
    # screen and the four buttons above it, which is Maschine's own grammar.
    #
    # The daemon draws nothing on its own: this builds the whole screen every
    # time, and the driver only puts it on the wire when something changed.

    SCREEN_W = 255
    SCREEN_COL = 64          # one column per encoder, four per screen
    TAB_H = 12
    RULE_Y = 13
    LABEL_Y = 15             # mode + page position, 5x8
    NAME_Y = 24              # encoder name, 5x8
    VALUE_Y = 32             # encoder value, double height
    BAR_Y = 52
    BAR_H = 10
    TAB_CHARS = 8            # "A KICK " - what fits in a 60 px tab at 6 px
    VALUE_CHARS = 4          # 4 chars of double-height text fit a column
    # A name-valued column (PRESET, KIT, SAMPLE) draws single height instead,
    # because four characters cannot tell one preset from the next: 48 of the
    # 67 patches on group H shared a 4-char label with an alphabetical
    # neighbour, and stepping walks a bank alphabetically. At 6 px per
    # character a 64 px column starting at x+3 holds ten; nine keeps a gutter.
    SMALL_VALUE_CHARS = 9

    # rect styles the daemon understands (main.rs display handler)
    RECT_OUTLINE = 0
    RECT_FILL = 1
    RECT_DASHED = 2
    RECT_DOTTED = 3
    RECT_INVERT = 4

    @staticmethod
    def encoder_osc(idx, value):
        """Force what an encoder reports (daemon main.rs, /maschine/encoder).

        The encoders are endless and the daemon carries their CC position as
        state. A knob left near 127 by one group would otherwise run out of
        travel for the next one, so the position is parked back in the middle
        before it gets to an end."""

        return maschine_mk2_lib.osc_message("/maschine/encoder", [int(idx), int(value)])

    @staticmethod
    def encoder_delta(last, value):
        """How far an encoder moved, given the last value seen from it.
        None means nothing has been seen yet, which is not a movement."""

        return 0 if last is None else int(value) - int(last)

    @staticmethod
    def encoder_steps(carry, delta, units_per_step):
        """Turn encoder movement into whole parameter steps, returning
        (steps, carry).

        The daemon reports a position, not a movement, so the driver reads
        the difference - but a difference of one unit per step would be far
        more sensitive than the absolute mapping this replaces. That mapping
        spread a parameter's whole range over the 128-unit sweep, so the feel
        is preserved by taking a step every 128/range units and carrying the
        remainder, which keeps slow turns from being lost."""

        total = carry + delta
        steps = int(total / units_per_step)     # truncates toward zero, both ways
        return steps, total - steps * units_per_step

    # The sweep the absolute mapping used to cover a parameter's whole range.
    # Dividing it by the number of values a parameter has gives the movement
    # one step of that parameter costs.
    ENC_SWEEP = 128

    @staticmethod
    def units_per_step(values):
        """Encoder movement worth one step of a parameter with `values`
        distinct settings."""

        return maschine_mk2_lib.ENC_SWEEP / max(1, values)

    @staticmethod
    def display_clear_osc(screen):
        return maschine_mk2_lib.osc_message("/maschine/display/fbclear", [int(screen)])

    @staticmethod
    def display_text_osc(screen, x, y, scale, invert, text):
        return maschine_mk2_lib.osc_message(
            "/maschine/display/text",
            [int(screen), int(x), int(y), int(scale), 1 if invert else 0, str(text)])

    @staticmethod
    def display_rect_osc(screen, x, y, w, h, style):
        return maschine_mk2_lib.osc_message(
            "/maschine/display/rect",
            [int(screen), int(x), int(y), int(w), int(h), int(style)])

    @staticmethod
    def bar_packets(screen, x, w, kind, frac, mod=None, tick=None):
        """Indicator bar under one encoder column.

        kind 'u' fills from the left (hits, length, expression, volume),
        'b' fills from the centre (pan, where the middle is the neutral
        position and which way it went matters), 's' lights discrete
        segments (rotation and division, which are counts and not
        continuous). '' draws nothing - encoder 7 carries nothing.

        mod, when not None, is (lo, hi) bar fractions - the range an active
        modulator can reach. Drawn inside the same inner geometry (ix, iy, iw,
        ih) the fill above already uses.

        tick is a SEPARATE bar fraction - where the wave currently sits -
        drawn as a 2 px mark inside the span. It is deliberately not `frac`:
        mod_span is symmetric about the base, so frac would sit dead on the
        span's midpoint every frame and never move. Falls back to `frac` when
        None, so a bare mod with no tick still draws something sane. The
        caller is expected to have quantised frac, mod and tick already; this
        draws whatever it is given.

        BOTH MARKS HAVE TO READ AGAINST FILLED AND UNFILLED BACKGROUND. Every
        modulatable verb draws bar kind 'u', a solid bar from the left out to
        `frac`, and the span is centred on `frac` - so half the span and the
        whole negative half of the tick's travel stand on already-lit pixels.
        A dashed outline there sets pixels that are already set and a filled
        tick there is a filled block inside a filled block: both were
        invisible for half of every cycle. The tick is therefore INVERTED,
        and the span is split at the fill's own edge - inverted where it
        stands on fill, dashed where it stands on empty background."""

        cls = maschine_mk2_lib
        if not kind:
            return []
        frac = min(1.0, max(0.0, float(frac)))
        out = [cls.display_rect_osc(screen, x, cls.BAR_Y, w, cls.BAR_H, cls.RECT_OUTLINE)]
        ix, iw = x + 1, w - 2
        iy, ih = cls.BAR_Y + 2, cls.BAR_H - 4
        if kind == "u":
            out.append(cls.display_rect_osc(
                screen, ix, iy, max(1, int(iw * frac)), ih, cls.RECT_FILL))
        elif kind == "b":
            mid = ix + iw // 2
            half = int(iw // 2 * abs(frac * 2 - 1))
            start = mid if frac >= 0.5 else mid - half
            out.append(cls.display_rect_osc(screen, start, iy, max(1, half), ih, cls.RECT_FILL))
        elif kind == "s":
            segs = 8
            seg_w = iw // segs
            lit = int(round(frac * (segs - 1)))
            for i in range(segs):
                style = cls.RECT_FILL if i <= lit else cls.RECT_OUTLINE
                out.append(cls.display_rect_osc(
                    screen, ix + i * seg_w, iy, seg_w - 1, ih, style))
        else:
            raise ValueError(f"unknown bar kind: {kind}")
        if mod is not None:
            lo, hi = mod
            lo = min(1.0, max(0.0, float(lo)))
            hi = min(1.0, max(0.0, float(hi)))
            if hi < lo:
                lo, hi = hi, lo
            span_x = ix + int(iw * lo)
            span_w = max(1, int(iw * (hi - lo)))
            # Where the solid fill ends. Only kind 'u' fills from the left, so
            # only there is the split meaningful; the others keep the plain
            # dashed span they have always drawn.
            fill_end = ix + max(1, int(iw * frac)) if kind == "u" else ix
            lit = max(0, min(span_x + span_w, fill_end) - span_x)
            if lit > 0:
                out.append(cls.display_rect_osc(
                    screen, span_x, iy, lit, ih, cls.RECT_INVERT))
            if span_w - lit > 0:
                out.append(cls.display_rect_osc(
                    screen, span_x + lit, iy, span_w - lit, ih, cls.RECT_DASHED))
            tick_frac = frac if tick is None else min(1.0, max(0.0, float(tick)))
            tick_x = min(ix + max(0, iw - 2), ix + int(iw * tick_frac))
            out.append(cls.display_rect_osc(screen, tick_x, iy, 2, ih, cls.RECT_INVERT))
        return out

    @staticmethod
    def screen_packets(screen, tabs, cols, label=""):
        """Every OSC packet for one screen, in draw order.

        tabs: four (letter, name, selected, muted)
        cols: four (name, value, bar kind, bar fraction), optionally extended
              with a mod span and a tick: (..., mod span) or
              (..., mod span, tick). Shorter forms still work so every
              existing caller and test is untouched; mod and tick default to
              None.
        label: the page indicator, e.g. "LEVEL 1/3". Empty draws nothing."""

        cls = maschine_mk2_lib
        out = [cls.display_clear_osc(screen)]
        for i, (letter, name, selected, muted) in enumerate(tabs):
            x = i * cls.SCREEN_COL + 1
            w = cls.SCREEN_COL - 4
            out.append(cls.display_rect_osc(
                screen, x, 0, w, cls.TAB_H,
                cls.RECT_DASHED if muted else cls.RECT_OUTLINE))
            tab_label = f"{letter} {name}"[:cls.TAB_CHARS]
            out.append(cls.display_text_osc(screen, x + 3, 2, 1, False, tab_label))
            if selected:
                # One inversion over the finished tab. Filling the box and
                # then drawing inverted text into it cancels out and leaves an
                # unreadable white block.
                out.append(cls.display_rect_osc(screen, x, 0, w, cls.TAB_H, cls.RECT_INVERT))
        out.append(cls.display_rect_osc(
            screen, 0, cls.RULE_Y, cls.SCREEN_W, 1, cls.RECT_DOTTED))
        if label:
            out.append(cls.display_text_osc(screen, 3, cls.LABEL_Y, 1, False, label))
        for i, col in enumerate(cols):
            name, value, kind, frac = col[:4]
            mod = col[4] if len(col) > 4 else None
            tick = col[5] if len(col) > 5 else None
            small = col[6] if len(col) > 6 else False
            x = i * cls.SCREEN_COL + 3
            if name:
                out.append(cls.display_text_osc(screen, x, cls.NAME_Y, 1, False, name))
            if value:
                # A name draws small so more of it fits; a number keeps the
                # double height that reads at a glance while playing.
                size = 1 if small else 2
                budget = cls.SMALL_VALUE_CHARS if small else cls.VALUE_CHARS
                out.append(cls.display_text_osc(
                    screen, x, cls.VALUE_Y, size, False, str(value)[:budget]))
            out.extend(cls.bar_packets(screen, x, cls.SCREEN_COL - 8, kind, frac, mod, tick))
        return out

    led_cache = None  # bound below to avoid a forward reference


class led_cache:
    """Remembers the last value written per LED so only changes go on the wire.
    The daemon has already been flooded off the USB bus once by unthrottled
    writes (commit ffc8f2b), so diffing is required, not an optimisation."""

    def __init__(self):
        self._last = {}

    def changed(self, key, value):
        """True if value differs from the last one stored under key"""

        if self._last.get(key) == value:
            return False
        self._last[key] = value
        return True

    def clear(self):
        self._last = {}


maschine_mk2_lib.led_cache = led_cache
