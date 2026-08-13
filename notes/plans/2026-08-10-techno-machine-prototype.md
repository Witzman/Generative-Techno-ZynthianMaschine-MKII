# Techno Machine Prototype — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the shipped eight-channel Maschine drum rig into the techno machine — five euclidean drum channels, three Turing-machine synth voices, per-channel insert reverb and delay, three latched pages, all played from the Maschine MK2 and all persisted in one prepared snapshot.

**Architecture:** The generative and presentation logic goes into a new pure-function module `techno_lib.py` that is unit-tested on WSL with no Pi and no hardware. The shipped ctrldev driver `zynthian_ctrldev_maschine_mk2.py` grows a page dimension, a channel-role table, a single state dict with one `apply()` path, and a Turing writer that runs on the existing 30 Hz poll thread. Sequencing stays in zynseq; FX are post-fader insert processors placed once by a snapshot-builder script. No Rust, no daemon change.

**Tech stack:** Python 3.11 (Zynthian's UI process), `unittest` (the existing convention in `zyngine/ctrldev/tests/`), `libzynseq` via ctypes, `zynmixer`, `zynthian_chain_manager`, LV2 via jalv.

---

## Global Constraints

Copied from `docs/superpowers/specs/2026-08-10-techno-machine-prototype-design.md` and from the gate results in `docs/superpowers/techno-machine/2026-08-10-gates-g1-g2-g3-results.md`. Every task's requirements implicitly include this section.

**Threading and zynseq — violating any of these has already killed the whole UI with SIGSEGV, exit 139, ~95 s into a jam:**

- Every zynseq / `libseq.*` call holds `self.lock`.
- **One lock acquisition per note burst**, never one per note.
- `selectPattern()` exactly once per burst, and **never** in the playhead poll hot path.
- Clocks-per-step is cached; the hot path never calls into zynseq for it.
- **Never hold the lock across a preset load** (kit or engine preset) — that path runs on its own timer thread.
- Never drive anything step-rate-sensitive from `SS_SEQ_PROGRESS`; it is 5 Hz and aliases against the step rate.
- Transport is `setPlayState` on every sequence. **Never `TOGGLE_PLAY`** — it resolves to `cuia_toggle_audio_play()`.

**Snapshot and LED discipline:**

- Re-force LOOP play mode **after every snapshot restore**, not once at init — a restore rewrites play mode from the `.zss` and a LOOPALL sequence shorter than the bar falls silent until the next bar sync.
- Clear `led_cache` on `SS_LOAD_SNAPSHOT` or the post-load repaint is suppressed as unchanged.
- Every LED write is diff-based against `led_cache`; the USB bus has been flooded once already.
- One diffed repaint per **100 ms** display tick. Redrawing per input report trips the hidraw watchdog.
- `"external_pad_leds": true` must stay in the daemon's `maschine.json`. It is **not in git on the Pi** — re-set it after any deploy that touches the daemon.

**MIDI map:**

- **Do not bind CC 47/48** (Page ◀▶) — the daemon swallows them and never emits them.
- **Do not consume CC 49, 50 or 51** — reserved for SHIFT, SWING and VOLUME in pass two.
- Arrows beside the display are **CC 5 / 6**. Dump `a2j:...Pads MIDI` with `jack_midi_dump` before binding any button.
- Encoders are **relative**: the daemon holds `roller_value` as device state and moves it by the hardware delta. Real movement is 0-4 units per report, counter wraps are −38 to −40, wrap guard is 8, and **a rejected wrap must still resync `roller_status`** or the encoder goes dead.
- `zynthian_controller._set_value()` **truncates** integer controls — chain controls step in whole controller units with the remainder carried, never in fractions of the range.

**Platform:**

- The Pi's installed Zynthian is **older** than `~/zynth/zynthian-ui`. Audit every new `libseq.*` symbol with
  `ssh root@192.168.2.123 'nm -D --defined-only /zynthian/zynthian-ui/zynlibs/zynseq/build/libzynseq.so | awk "\$2==\"T\"{print \$3}" | sort'`
  before writing the call. **Already audited and present:** `addNote`, `clear`, `selectPattern`, `getPattern`, `setStepsPerBeat`, `setBeatsInPattern`, `setPlayState`, `setPlayChance`, `getPlayChance`, `setSwingAmount`, `getSwingAmount`, `setSwingDiv`, `getSwingDiv`, `setScale`, `setTonic`, `setTempo`, `getTempo`, `setStutterCount`.
- The Pi **cannot fetch from GitHub**. Move commits with `git bundle create` on WSL, then `git fetch /tmp/x.bundle main:refs/remotes/origin/main` on the Pi, and **check the fetch exit status** before any reset.
- Deploy the driver by copying `~/zynth/zynthian-ui/zyngine/ctrldev/*.py` to the Pi's `/zynthian/zynthian-ui/zyngine/ctrldev/`.
- Re-run `~/zynth-docs/tools/patch-autoconnect-maschine.py` after any Zynthian update or the driver is "Found" but never "Loaded".

**FX, settled by gate G3 and G1 (owner ratified option (a), 2026-08-10):**

- Reverb: **`JV/TAP Reverberator`** — wet `wetlevel` (−70…+10 dB), dry `drylevel`, size `decay` (0…10000 ms), **`mode` = reverb type, 43 entries, which takes the ALL page's R2 column as `REVTYPE`** because TAP Reverberator has no damping control.
- Delay: **`JV/TAP Stereo Echo`** — wet `lecholevel` + `recholevel` (ganged, −70…+10 dB), dry `dryLevel`, time `ldelay` (0…2000 ms, computed from `getTempo()`), feedback `lfeedback` (0…100).
- **Both engines are `ENABLED = False`** in `/zynthian/config/engine_config.json` and must be enabled before the snapshot can be built.
- **Dry level must be set explicitly** in the prepared snapshot on both inserts. Defaults are not the useful value.
- Encoders 7/8 address the wet **through a per-channel FX handle**, never a hard-coded plugin symbol.

**Voice engines, settled by gate G2 — all three expose all four columns:**

```
BASS  JV/JC303     _cutoff       _resonance   _envmod          _decay
LEAD  JV/Obxd      cutoff        resonance    filterenvamount  decay
PADS  JV/padthv1   DCF1_CUTOFF   DCF1_RESO    DCF1_ENVELOPE    DCA1_ATTACK
```

**Laws the UI must obey:**

- **L1** tap latches, hold (>250 ms) is momentary — F1-F8 and SOLO only, never the page buttons.
- **L2** timbre lands instantly; ROOT, SCALE, DIVIDE, LENGTH, KIT and preset land on the next bar, shown as `>value<` while pending.
- **L3** nothing destructive on a single press. ERASE is hold-and-target only. "Clear a channel" means HITS → 0 (drum) or CHANCE → 0 (voice), never wiping the note list.
- **L4** a column whose source does not exist draws lower-case, `----`, no bar, and its encoder does nothing.
- **L5** one channel, one cursor; the inverted tab is authoritative.
- **L6** RANDOM → 0 keeps the loop bit-identical forever, by skipping the rewrite.

---

## File Structure

| File | Responsibility |
|---|---|
| `zyngine/ctrldev/techno_lib.py` — **new** | Pure functions only: the Turing shift register and its 4-deep ring, register → pitch quantisation, the scale table, the channel-role table, the FX role → symbol maps, the delay-time-from-BPM conversion, and the page/column model for all three pages on both channel types. No imports from Zynthian, no I/O. |
| `zyngine/ctrldev/tests/test_techno_lib.py` — **new** | `unittest` cases for everything in `techno_lib.py`. Runs on WSL. |
| `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py` — modify | The driver: page state, channel table, the one state dict and `apply()`, the Turing writer on the poll thread, FX handles, LED and screen rendering per page, button grammar. |
| `zyngine/ctrldev/maschine_mk2_lib.py` — modify | Only where the display helpers need a new bar kind or a wider value cell. Existing `screen_packets(screen, tabs, cols)` already takes the columns, so it stays page-agnostic. |
| `~/zynth-docs/tools/build-techno-snapshot.py` — **new** | Builds prepared snapshot `022-techno-machine` on the Pi from `021`: eight chains with the right engines, sixteen post-fader inserts, per-pattern swing div and play chance, dry levels, LOOP mode. Run once, by hand, on the Pi. |

`021-maschine-drum-rig-sfz` is never modified. It stays the working fallback exactly as `020` was kept when `021` was built.

---

## Task 1: Turing shift register and the 4-deep ring

**Files:**
- Create: `zyngine/ctrldev/techno_lib.py`
- Test: `zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Produces: `techno_lib.mutate(register, length, chance, rng=random.random) -> int`, `techno_lib.rotations(register, length, steps) -> list[int]`, `techno_lib.ring_push(ring, register) -> None`, `techno_lib.ring_pop(ring) -> int | None`. `ring` is a `collections.deque(maxlen=4)`.

The register is one integer of `length` bits (2-16). `mutate` clocks it **`length` times**, one full rotation, flipping the fed-back bit with probability `chance`. A full rotation is the identity when `chance == 0`, which is what makes lock exact. `rotations` reads the line for the pattern without advancing the persistent register.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest tests.test_techno_lib -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'techno_lib'`

- [ ] **Step 3: Write the minimal implementation**

**`dev_ids = []` is mandatory, not decoration.** `zynthian_ctrldev_manager`
globs every `*.py` in `zyngine/ctrldev/`, takes `getattr(module, module_name)`
as a driver class and reads `.dev_ids` off it. A new module in that directory
without the attribute **crash-loops the entire Zynthian UI on startup** —
`AttributeError: type object 'techno_lib' has no attribute 'dev_ids'`, every
14 seconds, forever. `maschine_mk2_lib` already carries the same guard.

```python
# zyngine/ctrldev/techno_lib.py
"""Pure functions for the techno machine. No Zynthian imports, no I/O, no state.

Everything here is unit tested on WSL with no Pi and no hardware, the same way
euclid() and the screen layout already are.
"""

import random


class techno_lib:

    dev_ids = []      # see above - the ctrldev manager reads this off every module

    # ---------------------------------------------------------------- Turing

    @staticmethod
    def mutate(register, length, chance, rng=random.random):
        """Clock the register one full rotation, flipping the fed-back bit with
        probability `chance`. A full rotation is the identity at chance 0, which
        is what makes LOCK exact rather than approximate."""
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
    def ring_push(ring, register):
        ring.append(register)

    @staticmethod
    def ring_pop(ring):
        return ring.pop() if ring else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest tests.test_techno_lib -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(techno): Turing shift register with a 4-deep undo ring"
```

---

## Task 2: Register → pitch, with ROOT, SCALE, OCTAVE and RANGE

**Files:**
- Modify: `zyngine/ctrldev/techno_lib.py`
- Test: `zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: `techno_lib.rotations` from Task 1.
- Produces: `techno_lib.SCALES` (an ordered tuple of `(label, intervals)`), `techno_lib.pitch(value, length, root, scale_idx, octave, range_octaves) -> int` returning a MIDI note number, and `techno_lib.line(register, length, steps, root, scale_idx, octave, range_octaves) -> list[int]`.

`root` is the tonic as a pitch class 0-11. Notes are generated around MIDI 36 (C2), which puts BASS in range without transposition and lets OCTAVE −2…+2 cover the useful span.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest tests.test_techno_lib -v`
Expected: FAIL with `AttributeError: type object 'techno_lib' has no attribute 'SCALES'`

- [ ] **Step 3: Write the minimal implementation**

Append to `techno_lib.py`, inside the class:

```python
    # ---------------------------------------------------------------- pitch

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
        """Scale the register value across `range_octaves`, quantise to the
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest tests.test_techno_lib -v`
Expected: PASS, 17 tests

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(techno): register to pitch with root, scale, octave and range"
```

---

## Task 3: Channel table, FX role maps, and delay time from BPM

**Files:**
- Modify: `zyngine/ctrldev/techno_lib.py`
- Test: `zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Produces: `techno_lib.CHANNELS` (8 entries of `(letter, name, kind, colour, engine_code, midi_chan)`), `techno_lib.VOICE_SYMBOLS` (engine code → the four CONTROL column symbols), `techno_lib.FX_REVERB` / `techno_lib.FX_DELAY` (role → `(symbol, lo, hi)`), `techno_lib.DELAY_DIVISIONS`, and `techno_lib.delay_ms(bpm, div_idx) -> float`.

Channel roles stay a table so 5+3, 4+4 and G1's degrade to six channels are config lines.

- [ ] **Step 1: Write the failing tests**

```python
class TestChannelTable(unittest.TestCase):

    def test_eight_channels_five_drums_three_voices(self):
        self.assertEqual(len(tl.CHANNELS), 8)
        kinds = [c[2] for c in tl.CHANNELS]
        self.assertEqual(kinds.count("drum"), 5)
        self.assertEqual(kinds.count("voice"), 3)

    def test_channel_names_fit_the_four_character_cell(self):
        for c in tl.CHANNELS:
            self.assertLessEqual(len(c[1]), 4)

    def test_midi_channels_are_one_to_eight(self):
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
        # gate G3: dB level ports, dry is separate
        self.assertEqual(tl.FX_REVERB["WET"][0], "wetlevel")
        self.assertEqual(tl.FX_REVERB["DRY"][0], "drylevel")


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest tests.test_techno_lib -v`
Expected: FAIL with `AttributeError: ... has no attribute 'CHANNELS'`

- [ ] **Step 3: Write the minimal implementation**

Append inside the class:

```python
    # ------------------------------------------------------------- channels

    # letter, 4-char name, kind, colour, engine code, midi channel (0-based)
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

    # engine code -> (CUTOFF, RESO, ENV, DECAY/ATTACK) - measured at gate G2
    VOICE_SYMBOLS = {
        "JV/JC303":   ("_cutoff", "_resonance", "_envmod", "_decay"),
        "JV/Obxd":    ("cutoff", "resonance", "filterenvamount", "decay"),
        "JV/padthv1": ("DCF1_CUTOFF", "DCF1_RESO", "DCF1_ENVELOPE", "DCA1_ATTACK"),
    }

    # ------------------------------------------------------------------- FX

    # role -> (plugin symbol, lo, hi).  Measured at gates G1 and G3:
    # TAP Reverberator and TAP Stereo Echo are the only stereo-in plugins with a
    # true wet level that this Pi can afford eight of.
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
        beat_ms = 60000.0 / max(1e-6, bpm)
        ms = beat_ms * techno_lib.DELAY_DIVISIONS[div_idx][1]
        return min(ms, techno_lib.FX_DELAY["DLYTIME"][2])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest tests.test_techno_lib -v`
Expected: PASS, 28 tests

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(techno): channel table, FX role maps, tempo-locked delay time"
```

---

## Task 4: The page/column model

**Files:**
- Modify: `zyngine/ctrldev/techno_lib.py`
- Test: `zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: `techno_lib.CHANNELS`, `techno_lib.DELAY_DIVISIONS`, `techno_lib.SCALES`.
- Produces: `techno_lib.PAGES = ("CONTROL", "STEP", "ALL")` and
  `techno_lib.columns(page, kind, state) -> list[dict]` returning exactly 8 dicts with keys
  `name` (str), `value` (str, ≤4 chars), `bar` (`"uni"` / `"bi"` / `"seg"` / `None`),
  `frac` (float 0..1 or a `(index, count)` tuple for `"seg"`), `grey` (bool), `pending` (bool).

`state` is the driver's per-channel dict plus the globals; the model reads it and never writes. This is the single place where L4's greyed columns and L2's pending brackets are decided, so both are unit tested rather than eyeballed on hardware.

- [ ] **Step 1: Write the failing tests**

```python
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
                 octave=-1, range=2, swing=58, velo=100, pending=set())
        s.update(over)
        return s

    def test_every_page_returns_eight_columns(self):
        for page in tl.PAGES:
            for kind, st in (("drum", self.drum_state()), ("voice", self.voice_state())):
                self.assertEqual(len(tl.columns(page, kind, st)), 8, f"{page}/{kind}")

    def test_right_hand_trio_is_level_reverb_delay_on_control(self):
        for kind, st in (("drum", self.drum_state()), ("voice", self.voice_state())):
            cols = tl.columns("CONTROL", kind, st)
            self.assertEqual([c["name"] for c in cols[5:]], ["LEVEL", "REVERB", "DELAY"])

    def test_swing_is_column_seven_on_step_for_both_kinds(self):
        for kind, st in (("drum", self.drum_state()), ("voice", self.voice_state())):
            self.assertEqual(tl.columns("STEP", kind, st)[6]["name"], "SWING")

    def test_drum_control_has_three_greyed_columns(self):
        cols = tl.columns("CONTROL", "drum", self.drum_state())
        grey = [c for c in cols if c["grey"]]
        self.assertEqual([c["name"] for c in grey], ["tune", "decay", "filtr"])
        for c in grey:
            self.assertEqual(c["value"], "----")
            self.assertIsNone(c["bar"])

    def test_voice_control_has_no_greyed_column(self):
        cols = tl.columns("CONTROL", "voice", self.voice_state())
        self.assertEqual([c["name"] for c in cols if c["grey"]], [])

    def test_ratchet_is_drawn_greyed_on_the_drum_step_page(self):
        col = tl.columns("STEP", "drum", self.drum_state())[7]
        self.assertEqual(col["name"], "ratchet")
        self.assertTrue(col["grey"])
        self.assertEqual(col["value"], "----")

    def test_random_zero_reads_lock_not_a_number(self):
        col = tl.columns("STEP", "voice", self.voice_state(random=0))[2]
        self.assertEqual(col["value"], "LOCK")
        self.assertEqual(len(col["value"]), 4)

    def test_pending_value_is_wrapped_in_angle_brackets(self):
        st = self.drum_state(div=2, pending={"div"})
        col = tl.columns("STEP", "drum", st)[2]
        self.assertTrue(col["pending"])
        self.assertTrue(col["value"].startswith(">") and col["value"].endswith("<"))

    def test_all_page_is_the_same_for_both_kinds(self):
        gl = dict(root=9, scale=0, bpm=132, master=88,
                  revsize=72, revtype=3, dlytime=2, dlyfbk=58, pending=set())
        a = [c["name"] for c in tl.columns("ALL", "drum", gl)]
        b = [c["name"] for c in tl.columns("ALL", "voice", gl)]
        self.assertEqual(a, b)
        self.assertEqual(a, ["ROOT", "SCALE", "BPM", "MASTER",
                             "REVSIZE", "REVTYPE", "DLYTIME", "DLYFBK"])

    def test_every_value_fits_the_cell(self):
        for page, kind, st in (("CONTROL", "drum", self.drum_state()),
                               ("STEP", "voice", self.voice_state())):
            for c in tl.columns(page, kind, st):
                self.assertLessEqual(len(c["value"].strip("><")), 4, c["name"])

    def test_octave_draws_a_bipolar_bar(self):
        col = tl.columns("STEP", "voice", self.voice_state())[4]
        self.assertEqual(col["name"], "OCTAVE")
        self.assertEqual(col["bar"], "bi")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest tests.test_techno_lib -v`
Expected: FAIL with `AttributeError: ... has no attribute 'PAGES'`

- [ ] **Step 3: Write the minimal implementation**

Append inside the class:

```python
    # ---------------------------------------------------------------- pages

    PAGES = ("CONTROL", "STEP", "ALL")

    DIVISION_LABELS = ("1/32", "1/16", "1/8", "1/16T", "1/8T")

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
        return techno_lib._col(name, "----", None, 0.0, grey=True)

    @staticmethod
    def columns(page, kind, state):
        p = state.get("pending", set())
        n, c, dead = techno_lib._num, techno_lib._col, techno_lib._dead

        if page == "ALL":
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

        if page == "CONTROL":
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
            return [
                c("PRESET", state["preset"], "seg", (0, 1), pending="preset" in p),
                c("CUTOFF", n(state["cutoff"]), "uni", state["cutoff"] / 127.0),
                c("RESO", n(state["reso"]), "uni", state["reso"] / 127.0),
                c("ENV", n(state["env"]), "uni", state["env"] / 127.0),
                c("DECAY", n(state["decay"]), "uni", state["decay"] / 127.0),
            ] + tail

        # STEP
        if kind == "drum":
            return [
                c("HITS", n(state["hits"]), "uni", state["hits"] / max(1, state["length"])),
                c("ROTATE", n(state["rotate"]), "seg", (state["rotate"], max(1, state["length"]))),
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
            c("RANDOM", "LOCK" if state["random"] <= 0 else n(state["random"]), "uni",
              state["random"] / 100.0),
            c("GATE", n(state["gate"]), "uni", state["gate"] / 100.0),
            c("OCTAVE", f"{state['octave']:+04d}"[:4], "bi", (state["octave"] + 2) / 4.0),
            c("RANGE", str(state["range"]), "seg", (state["range"] - 1, 4)),
            c("SWING", n(state["swing"]), "uni", (state["swing"] - 50) / 25.0),
            c("VELO", n(state["velo"]), "uni", state["velo"] / 127.0),
        ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest tests.test_techno_lib -v`
Expected: PASS, 39 tests

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(techno): page and column model for all three pages, both channel types"
```

---

## Task 5: The prepared snapshot `022-techno-machine`

**Files:**
- Create: `~/zynth-docs/tools/build-techno-snapshot.py`
- Runs on: the Pi, against a running Zynthian

**Interfaces:**
- Consumes: `techno_lib.CHANNELS`, `techno_lib.FX_REVERB`, `techno_lib.FX_DELAY`.
- Produces: `/zynthian/zynthian-my-data/snapshots/000/022-techno-machine.zss` — eight chains on MIDI channels 1-8, five LinuxSampler kits and three synth voices, sixteen post-fader inserts with dry set explicitly, eight sequences in LOOP with swing div 1/16 and play chance set.

This is the "snapshot, then measurement, then driver" order the spec insists on. It is built programmatically from `021` the same way `021` was built from `020`, so the drum patterns stay byte-identical.

- [ ] **Step 1: Enable the two FX engines**

In webconf, go to **Library → LV2 plugins**, find **TAP Reverberator** and **TAP Stereo Echo**, tick both, save.

Verify over SSH:

```bash
ssh root@192.168.2.123 'python3 -c "
import json
d=json.load(open(\"/zynthian/config/engine_config.json\"))
for k in (\"JV/TAP Reverberator\",\"JV/TAP Stereo Echo\"):
    print(k, d[k][\"ENABLED\"])"'
```

Expected: `JV/TAP Reverberator True` and `JV/TAP Stereo Echo True`. If webconf cannot do it, edit that JSON directly and restart Zynthian — the file is the source of truth the engine list is built from.

**How the snapshot is built, and why not the obvious way.** There is **no CUIA
that executes code**, so a builder script cannot reach the live `state_manager`
from outside the UI process — `cuia_thread_task` is the internal event loop, not
an exec hook. Building the whole `.zss` offline is equally wrong: it would mean
hand-maintaining `fader_pos`, and the spec forbids exactly that bookkeeping.

The path that is both safe and cheap: **build one channel by hand on the
touchscreen, then clone it.** Two manual operations instead of thirty-two, with
Zynthian itself producing the ground truth for `slots`, `fader_pos` and the
processor state; the script then replicates that structure across the other
seven chains with fresh processor ids. The `.zss` is JSON with this shape:

```
chains[<id>]  = {title, midi_chan, mixer_chan, slots: [{<proc_id>: "<eng_code>"}],
                 fader_pos, zctrls}
zs3["zs3-0"]["processors"][<proc_id>] = {bank_info, preset_info, controllers, ...}
```

- [ ] **Step 2: Build channel A's inserts by hand, and save**

Load `021-maschine-drum-rig-sfz`. On the touchscreen open the **Kick** chain,
add **TAP Reverberator**, then **TAP Stereo Echo**, and move the fader position
so both sit **after** the fader. Set on the reverb: `drylevel` 0 dB,
`wetlevel` −70 dB, `decay` 2500, `mode` 3. On the echo: `dryLevel` 0 dB,
`lecholevel` and `recholevel` −70 dB, `ldelay` 227 (1/8 at 132 BPM),
`lfeedback` 35.

Save as a new snapshot named `022-techno-machine` — inside bank `000`, the first
entry is **"Save as new snapshot"**. **Do not use the webconf Snapshots page Name
field and checkmark: that renames the selected bank**, and it has destroyed bank
`000` once already.

- [ ] **Step 3: Clone the insert pair onto the other seven chains**

```python
#!/usr/bin/env python3
"""Clones channel A's insert pair onto the other seven chains of
022-techno-machine, offline, on the .zss JSON.

Channel A's pair must already exist, built by hand on the touchscreen, so that
Zynthian - not this script - decided slots, fader_pos and processor state.

    scp tools/build-techno-snapshot.py root@192.168.2.123:/root/
    ssh root@192.168.2.123 'python3 /root/build-techno-snapshot.py'
"""

import copy
import json
import shutil
import sys

SNAP = "/zynthian/zynthian-my-data/snapshots/000/022-techno-machine.zss"
REVERB = "JV/TAP Reverberator"
DELAY = "JV/TAP Stereo Echo"


def main():
    shutil.copy(SNAP, SNAP + ".bak")
    d = json.load(open(SNAP))
    chains = d["chains"]
    procs = d["zs3"]["zs3-0"]["processors"]

    # find the template: the chain that already carries both inserts
    template_id = None
    for cid, chain in chains.items():
        codes = [code for slot in chain["slots"] for code in slot.values()]
        if REVERB in codes and DELAY in codes:
            template_id = cid
            break
    if template_id is None:
        sys.exit("no chain carries both inserts - build channel A by hand first")
    template = chains[template_id]
    print(f"template chain {template_id}: {template['title']}, "
          f"fader_pos {template['fader_pos']}, {len(template['slots'])} slots")

    fx_slots = [s for s in template["slots"]
                if any(c in (REVERB, DELAY) for c in s.values())]
    next_id = max(int(p) for p in procs) + 1

    for cid, chain in chains.items():
        if cid == template_id or chain.get("midi_chan") is None:
            continue
        codes = [code for slot in chain["slots"] for code in slot.values()]
        if REVERB in codes:
            print(f"chain {cid}: already has inserts, skipped")
            continue
        for slot in fx_slots:
            (old_id, code), = slot.items()
            chain["slots"].append({str(next_id): code})
            procs[str(next_id)] = copy.deepcopy(procs[str(old_id)])
            next_id += 1
        chain["fader_pos"] = template["fader_pos"]
        print(f"chain {cid} ({chain['title']}): inserts cloned, "
              f"fader_pos {chain['fader_pos']}")

    json.dump(d, open(SNAP, "w"), indent=2)
    print(f"written. backup at {SNAP}.bak")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Load the cloned snapshot and let Zynthian rewrite it**

Load `022-techno-machine` on the touchscreen. Zynthian instantiates the sixteen
inserts and re-derives its own bookkeeping; **save the snapshot again from the
touchscreen** so what is on disk is Zynthian's own output rather than the
script's. Watch it come up:

```bash
ssh root@192.168.2.123 'journalctl -u zynthian --since -3min | grep -iE "error|traceback|processor"'
ssh root@192.168.2.123 'jack_lsp | grep -c TAP'
```

Expected: 64 TAP audio ports (16 instances × 4) and no traceback.

- [ ] **Step 4b: Set the gain staging, and measure it — this is not optional**

Both inserts pass dry at **unity**, as an insert must. The TAP defaults were
−4 dB each, so before this change every channel was quietly losing ~8 dB, and
that attenuation was hiding how hot the mix already was. Measured on the shipped
kits: **a single sampler channel peaks at 1.24 before the mixer**, and eight of
them summed to **2.92** on the main bus — nearly three times full scale.

The LinuxSampler `volume` controller in the snapshot is **not** the fix: taking
it from 96 to 40 moved the bus peak only from 1.88 to 1.59, about 1.5 dB. Use
the **mixer strips**, which is where this rig keeps volume anyway, over the OSC
mixer API — `/MIXER/FADER<n> f`, strip 16 being main:

```bash
ssh root@192.168.2.123 'python3 -c "
import liblo, time
t = liblo.Address(\"localhost\", 1370, liblo.UDP)
for ch in range(8):
    liblo.send(t, \"/MIXER/FADER%d\" % ch, 0.19)
    time.sleep(0.05)
liblo.send(t, \"/MIXER/FADER16\", 0.8)"'
```

The faders are **linear in amplitude** — 0.6 → 0.38 produced exactly a 0.633×
change in peak — so gain can be moved between strips and master freely. Put the
attenuation on the strips and leave **master at 0.8**, so the player's MASTER
knob has travel in both directions.

**Verify:** main bus peak lands near **0.69**, roughly 3 dB of headroom, and it
must stay under 1.0 with the wets still at −70 dB — opening reverb and delay adds
level on top. Measure it, do not eyeball a meter:

```bash
scp <scratchpad>/peak.py root@192.168.2.123:/root/ && ssh root@192.168.2.123 'python3 /root/peak.py'
```

Then save from the touchscreen. The mixer state only appears in the `.zss` once
it differs from the default, as `zs3/zs3-0/mixer/chan_NN/level`; a snapshot with
no such block is one whose faders were never touched.

- [ ] **Step 5: Add the three voice chains**

Still on the touchscreen: add three chains on MIDI channels 6, 7 and 8 with
**JC303**, **Obxd** and **padthv1**, give each the same insert pair, and save
again. Voices are three chains, so this is the same hand-plus-clone cycle: build
one, run the script, reload, save.

- [ ] **Step 4: Verify the snapshot on hardware**

```bash
ssh root@192.168.2.123 'ls -la /zynthian/zynthian-my-data/snapshots/000/022-techno-machine.zss'
ssh root@192.168.2.123 'jack_lsp | grep -cE "TAP"'
```

Expected: the `.zss` exists, and 64 TAP audio ports (16 instances × 4).

On the touchscreen: load `022-techno-machine`, confirm the mixer shows **eight strips plus main**, play a note into each of MIDI channels 6, 7 and 8 from the Xboard and hear BASS, LEAD and PADS. Tap pads on groups A-E and hear the five drum kits.

**Verify:** all eight channels sound; the touchscreen mixer shows eight strips; the pattern editor shows the same steps you tapped; `getSwingDiv()` reads 4 on every pattern.

- [ ] **Step 5: Measure the load time, which is the number at risk**

```bash
ssh root@192.168.2.123 'journalctl -u zynthian --since -5min | grep -iE "loading snapshot|snapshot loaded"'
```

Expected: under 15 s cold. Gate G1 measured 10.8 s for the sixteen inserts alone, so if the total crosses 15 s the degrade is the spec's own — eight channels down to six, by editing `techno_lib.CHANNELS`, which is one table.

- [ ] **Step 6: Commit**

```bash
cd ~/zynth-docs
git add tools/build-techno-snapshot.py
git commit -m "feat(techno): snapshot builder for 022-techno-machine"
```

---

## Task 6: Driver state dict, channel table and the single apply path

**Files:**
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`
- Test: `zyngine/ctrldev/tests/test_techno_lib.py` (the pure parts), plus a hardware check

**Interfaces:**
- Consumes: `techno_lib.CHANNELS`, `techno_lib.columns`.
- Produces: `self.state` — `{channel_index: {param: value}}` plus `self.globals`; `self.apply(channel, param, value)`; `self.fx_handle(channel, which)` returning the processor for `"reverb"` or `"delay"`; `self.page` holding one of `techno_lib.PAGES`; `self.writer_token` — a per-channel token guarding pattern writes.

**Non-negotiable, and the reason Lock snapshots could be deferred without fear:** every write — encoder, snapshot restore, Duplicate, and later Lock recall — goes through `apply()`, which also updates the screen model and the LED cache. Nothing writes zynseq or a zctrl directly.

- [ ] **Step 1: Add the state structure and the apply path**

In `zynthian_ctrldev_maschine_mk2.py`, add near the top:

```python
from techno_lib import techno_lib as tlib
```

In `__init__`, after the existing attributes:

```python
        # one state dict, one apply path - see the spec's "State model"
        self.page = "CONTROL"
        self.globals = dict(root=9, scale=0, bpm=132, master=88,
                            revsize=72, revtype=3, dlytime=1, dlyfbk=35,
                            pending=set())
        self.state = {}
        for idx, (letter, name, kind, colour, engine, chan) in enumerate(tlib.CHANNELS):
            common = dict(level=80, reverb=0, delay=0, div=DEFAULT_DIV, length=16,
                          swing=50, velo=110, pending=set())
            if kind == "drum":
                common.update(kit="----", sample="----", hits=4, rotate=0, chance=100)
            else:
                common.update(preset="----", cutoff=64, reso=32, env=64, decay=40,
                              random=0, gate=40, octave=0, range=2,
                              register=0b10110011, ring=deque(maxlen=4))
            self.state[idx] = common
        # generator parameters are separable from mix parameters, even though
        # nothing in the prototype uses the distinction yet (spec, pass three)
        self.GENERATOR_PARAMS = {"hits", "rotate", "div", "length", "chance", "velo",
                                 "swing", "random", "gate", "octave", "range", "register"}
        self.MIX_PARAMS = {"level", "reverb", "delay"}
        self.writer_token = {i: None for i in range(len(tlib.CHANNELS))}
```

Add `from collections import deque` to the imports.

- [ ] **Step 2: Write `apply()` — the only writer**

```python
    def apply(self, channel, param, value):
        """The single write path. Every encoder, every restore, every undo goes
        through here so that pass two's Lock snapshots are a copy of self.state
        and a morph is a lerp over it."""
        st = self.state[channel]
        if st.get(param) == value:
            return
        st[param] = value

        if param in self.MIX_PARAMS:
            self._apply_mix(channel, param, value)
        elif param in ("kit", "sample", "preset"):
            self._apply_preset(channel, param, value)
        elif param in self.GENERATOR_PARAMS:
            self._apply_generator(channel, param, value)

        self._render_all()
```

`_apply_mix` routes `level` to `zynmixer.set_level`, and `reverb` / `delay` to the FX handle's wet symbol. `_apply_generator` marks the channel dirty for the next pattern write; structure parameters (`div`, `length`) go into `st["pending"]` and are applied at the next bar by the poll thread, per law L2.

- [ ] **Step 3: Add the FX handle**

```python
    def fx_handle(self, channel, which):
        """Encoders 7 and 8 address 'this channel's reverb wet' through here,
        never through a hard-coded plugin symbol. Swapping the plugin under G1's
        headroom then changes one function."""
        chain_ids = self.chain_manager.midi_chan_2_chain_ids[tlib.CHANNELS[channel][5]]
        if not chain_ids:
            return None
        chain = self.chain_manager.chains.get(chain_ids[0])
        if chain is None:
            return None
        want = "TAP Reverberator" if which == "reverb" else "TAP Stereo Echo"
        for proc in chain.get_processors():
            if proc.engine is not None and want in str(proc.engine.name):
                return proc
        return None
```

Note `chain_manager.get_chain_ids_by_midi_chan()` **does not exist** on the Pi — `midi_chan_2_chain_ids[chan]` is the pattern the pattern editor itself uses.

- [ ] **Step 3b: Do NOT add MIDI channel translation — and know why the test that suggested it lied**

An injected note reached only PADS while BASS and LEAD stayed silent, which
looked like JC303 and Obxd being channel-1-only. **They are not: all three voice
engines are omni.** Two measurement faults produced the false reading — a probe
that was not reset between channel rounds, so the previous channel's tail was
counted; and the fact that **Zynthian routes an unconfigured `ZynMidiRouter:devN_in`
to the active chain, not per channel.** Tracing all three `chN_out` ports at once
showed all eighteen events, from three channels, arriving at one zmop.

`zmop_set_midi_chan_trans` exists and works — a translated zmop emits
`902d64`, channel 1 — but using it here narrows the zmop to a single channel to
solve a problem that does not exist. **Do not add it.**

When a voice appears silent, check in this order: is the note reaching the
chain's zmop at all (trace `chN_out` with your own JACK MIDI input port —
`jack_midi_dump` shows nothing on these ports); is the mixer strip up; is the
insert's dry level unity.

- [ ] **Step 4: Deploy and verify the plumbing without any UI change**

```bash
scp ~/zynth/zynthian-ui/zyngine/ctrldev/techno_lib.py \
    ~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py \
    root@192.168.2.123:/zynthian/zynthian-ui/zyngine/ctrldev/
ssh root@192.168.2.123 'systemctl restart zynthian'
ssh root@192.168.2.123 'journalctl -u zynthian --since -2min | grep -iE "ctrldev|maschine|traceback|error"'
```

**Verify:** the driver still loads ("Loaded" in the journal, not just "Found"), the shipped rig still plays from snapshot `021`, and no traceback appears. This task changes no behaviour on purpose — it is the scaffold everything else hangs from.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(techno): one state dict, one apply path, per-channel FX handles"
```

---

## Task 7: Pages, group select, and the three screens

**Files:**
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `self.page`, `self.state`, `techno_lib.columns`.
- Produces: `self._set_page(name)`, and `_columns(screen)` rewritten to read `techno_lib.columns(self.page, kind, state)` instead of the shipped hard-coded list.

CC map for the three page buttons, all of which emit today: **CONTROL = 11, STEP = 32, ALL = 38.** Pressing the lit page returns to CONTROL, except CONTROL itself which does nothing.

- [ ] **Step 1: Confirm the three CCs on the wire before binding them**

```bash
ssh root@192.168.2.123 'timeout 25 jack_midi_dump "a2j:Maschine Controller MK2 [24] (capture): Maschine Controller MK2 Pads MIDI" | grep -E "b0"'
```

Press CONTROL, STEP and ALL while it runs. Expected: `b0 0b`, `b0 20`, `b0 26`. **If a CC differs, use what the wire says** — the reference has been wrong before, which is what cost the project the CC 48/47 detour.

- [ ] **Step 2: Add the page handler**

In `_midi_event`, alongside the existing CC handling:

```python
CC_PAGE_CONTROL = 11
CC_PAGE_STEP = 32
CC_PAGE_ALL = 38
```

```python
    def _set_page(self, name):
        if name == self.page and name != "CONTROL":
            name = "CONTROL"
        self.page = name
        self._recentre_encoders()      # the encoders now mean something else
        self._render_all()
```

Page LEDs are derived from `self.page` on the existing 100 ms display tick, **never written at the point of the press**, so the LED and the screen can never disagree.

- [ ] **Step 3: Point the column builder at the model**

Replace the body of `_columns(screen)` with:

```python
    def _columns(self, screen):
        idx = self.selected
        kind = tlib.CHANNELS[idx][2]
        state = self.globals if self.page == "ALL" else self.state[idx]
        cols = tlib.columns(self.page, kind, state)
        return cols[:4] if screen == 0 else cols[4:]
```

- [ ] **Step 4: Deploy and verify on hardware**

**Verify:** exactly one page LED is lit at any time; the tab row follows group selection on both panels; all three pages render; pressing STEP twice returns to CONTROL; pressing CONTROL while lit does nothing. Photograph the ALL page with the worst-case values (`REVTYPE` at 42, `BPM` at 200) and confirm the four-character cell reads at a glance — risk R10.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(techno): three latched pages driving both screens"
```

---

## Task 8: Drum STEP page — seven live columns

**Files:**
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `apply()`, the existing `maschine_mk2_lib.euclid` and `build_pattern`.
- Produces: encoder handling for HITS, ROTATE, DIVIDE, LENGTH, VELO, CHANCE, SWING on the STEP page; `ratchet` stays inert.

CHANCE is `libseq.setPlayChance` and SWING is `libseq.setSwingAmount` — both per pattern, both persisted in the `.zss`, both costing **zero pattern writes**, which is what keeps risk R1 small.

- [ ] **Step 1: Route the four new columns through apply()**

In `_encoder`, when `self.page == "STEP"` and the channel is a drum, map encoder 5-7 to `velo`, `chance`, `swing`; encoders 1-4 keep the shipped hits / rotate / div / length behaviour but now go through `apply()`. Encoder 8 returns immediately — the column is inert by L4.

```python
        if self.page == "STEP" and kind == "drum":
            if cc_num == ENCODER_CCS[7]:
                return                      # ratchet: drawn, greyed, dead
            if cc_num == ENCODER_CCS[5]:
                steps = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
                self.apply(idx, "chance", max(0, min(100, st["chance"] + steps)))
                return
```

- [ ] **Step 2: Write the zynseq side, one lock acquisition per burst**

```python
    def _apply_chance(self, channel, value):
        with self.lock:
            self._select_pattern(channel)
            self.zynseq.libseq.setPlayChance(value / 100.0)

    def _apply_swing(self, channel, value):
        with self.lock:
            self._select_pattern(channel)
            self.zynseq.libseq.setSwingAmount((value - 50) / 25.0)
```

`setSwingDiv` is **not** called here — it is per pattern and was set once in the prepared snapshot, because trusting its default is what the spec's open item warns about.

- [ ] **Step 3: Make a pad tap set the step's velocity**

The hardware already reads pad velocity, so accents are free. In `_toggle_step`,
when the tap turns a step **on**, write the incoming note-on velocity as that
step's velocity instead of the channel's `VELO`:

```python
    def _toggle_step(self, step, velocity=None):
        ...
        vel = velocity if velocity else self.state[self.selected]["velo"]
        with self.lock:
            self._select_pattern(self.selected)
            self.zynseq.libseq.addNote(step, note, vel, duration, 0.0)
```

The generator still owns the pattern: the next generator move wipes hand-edited
steps, and there is no hidden per-step override state and no third LED colour.
Steps beyond `LENGTH` stay dark and inert, as they already are in the shipped rig.

- [ ] **Step 4: Deploy and verify on hardware**

**Verify:** density, rotation, division and length all audible on channels A-E;
a hard pad tap is audibly louder than a soft one and the pad LED is brighter; CHANCE at 60 opens holes in a four-on-the-floor kick without changing which steps are lit; SWING at 62 shuffles audibly against a straight kick on another channel; the `ratchet` column is drawn, lower-case, `----`, and its encoder does nothing at all.

- [ ] **Step 4: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(techno): drum STEP page with chance and swing"
```

---

## Task 9: Voice STEP page and the Turing writer

**Files:**
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `techno_lib.mutate`, `techno_lib.line`, `techno_lib.ring_push`, `techno_lib.ring_pop`.
- Produces: `self._rewrite_voice(channel)` called from the existing 30 Hz playhead poll thread at a wrap, and the encoder handling for LENGTH, DIVIDE, RANDOM, GATE, OCTAVE, RANGE, SWING, VELO.

**This is the instrument's central idea.** The register is persistent, mutation is incremental, and the pattern is rewritten only on a playhead wrap — which is what makes the audible line bit-constant for a whole cycle by construction, and what makes `RANDOM → 0` an exact lock rather than an approximate one.

- [ ] **Step 1: Write the rewrite, on the poll thread, one lock per burst**

```python
    def _rewrite_voice(self, channel):
        """Called from the playhead poll thread at a wrap. RANDOM at 0 skips the
        rewrite entirely, which is precisely why the loop being heard is the loop
        kept, bit-identical, forever (law L6)."""
        st = self.state[channel]
        if st["random"] <= 0:
            return
        if self.writer_token[channel] not in (None, "turing"):
            return                          # someone else owns this pattern
        self.writer_token[channel] = "turing"

        tlib.ring_push(st["ring"], st["register"])
        st["register"] = tlib.mutate(st["register"], st["length"], st["random"] / 100.0)

        steps = lib.step_count(st["div"])
        notes = tlib.line(st["register"], st["length"], steps,
                          self.globals["root"], self.globals["scale"],
                          st["octave"], st["range"])
        duration = max(0.05, st["gate"] / 100.0)

        with self.lock:                     # ONE acquisition for the whole burst
            self._select_pattern(channel)   # exactly once per burst
            self.zynseq.libseq.clear()
            for step, note in enumerate(notes):
                self.zynseq.libseq.addNote(step, note, st["velo"], duration, 0.0)
        self.writer_token[channel] = None
```

- [ ] **Step 2: Hook it to the wrap, not to a signal**

In `_playhead_loop`, where the cached head position wraps from high to low for a voice channel, call `_rewrite_voice(channel)`. **Never from `SS_SEQ_PROGRESS`** — it is 5 Hz and aliases against the step rate.

- [ ] **Step 3: Wire Duplicate to the ring**

```python
CC_DUPLICATE = 29
```

```python
    def _duplicate(self):
        idx = self.selected
        st = self.state[idx]
        if tlib.CHANNELS[idx][2] != "voice":
            return
        prev = tlib.ring_pop(st["ring"])
        if prev is None:
            return
        st["register"] = prev
        self.apply(idx, "random", 0)        # force LOCK, per the ratified decision
        self._write_voice_pattern(idx)      # rewrite now, ignoring the random gate
```

`_rewrite_voice` is the wrap-time gate; the write itself lives in
`_write_voice_pattern(channel)`, which both call. Split them so Duplicate can
write without mutating:

```python
    def _write_voice_pattern(self, channel):
        """Writes the current register to the pattern. Mutates nothing."""
        st = self.state[channel]
        if self.writer_token[channel] not in (None, "turing"):
            return
        self.writer_token[channel] = "turing"
        steps = lib.step_count(st["div"])
        notes = tlib.line(st["register"], st["length"], steps,
                          self.globals["root"], self.globals["scale"],
                          st["octave"], st["range"])
        duration = max(0.05, st["gate"] / 100.0)
        with self.lock:                     # ONE acquisition for the whole burst
            self._select_pattern(channel)   # exactly once per burst
            self.zynseq.libseq.clear()
            for step, note in enumerate(notes):
                self.zynseq.libseq.addNote(step, note, st["velo"], duration, 0.0)
        self.writer_token[channel] = None
```

and `_rewrite_voice` becomes: return early if `random <= 0`, push the ring,
mutate the register, then call `_write_voice_pattern(channel)`.

- [ ] **Step 4: Deploy and verify on hardware — this is the acceptance test of the whole design**

**Verify:**
- RANDOM at 20 drifts **one note per bar**, not a new line per bar. Listen for four bars.
- **Snap RANDOM to 0 and the line repeats bit-identically for five minutes.** Set a phone timer; this is law L6 and it is the one thing that must not be approximately true.
- Duplicate walks back four registers and no further.
- OCTAVE, RANGE, GATE and VELO all audible; GATE at 5 is a stab, at 100 legato.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(techno): Turing voices - incremental mutation, exact lock, 4-deep undo"
```

---

## Task 10: CONTROL pages and the wet knobs

**Files:**
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `fx_handle`, `techno_lib.VOICE_SYMBOLS`, `techno_lib.FX_REVERB`, `techno_lib.FX_DELAY`.
- Produces: encoders 6/7/8 as LEVEL / REVERB / DELAY on **every channel of every type**, and encoders 2-5 as the voice engine's four zctrls.

The wet parameter is a **plugin** zctrl, not an engine zctrl, which is why LinuxSampler's empty `_ctrls` cannot bite here. Both knobs are live on drums and voices with no exception.

- [ ] **Step 1: Map 0-100 onto the plugin's dB range**

```python
    def _set_wet(self, channel, which, percent):
        proc = self.fx_handle(channel, which)
        if proc is None:
            return
        table = tlib.FX_REVERB if which == "reverb" else tlib.FX_DELAY
        syms = [table["WET"][0]] + ([table["WET_R"][0]] if "WET_R" in table else [])
        lo, hi = table["WET"][1], table["WET"][2]
        # -70 dB reads as off; the useful travel is the top of the range
        value = lo + (hi - lo) * (percent / 100.0)
        for sym in syms:
            zctrl = proc.controllers_dict.get(sym)
            if zctrl is not None:
                zctrl.set_value(value, True)
```

- [ ] **Step 2: Map the voice CONTROL columns to the G2 symbols**

```python
    def _set_voice_ctrl(self, channel, column, value):
        engine = tlib.CHANNELS[channel][4]
        symbol = tlib.VOICE_SYMBOLS[engine][column]      # 0=CUTOFF 1=RESO 2=ENV 3=DECAY
        proc = self._voice_processor(channel)
        zctrl = proc.controllers_dict.get(symbol) if proc else None
        if zctrl is None:
            return                                        # L4: draws greyed, does nothing
        span = zctrl.value_max - zctrl.value_min
        zctrl.set_value(zctrl.value_min + span * (value / 127.0), True)
```

- [ ] **Step 3: Deploy and verify on hardware**

**Verify:** encoder 7 opens reverb on all eight channels and encoder 8 opens delay on all eight; **the dry signal survives a full sweep of both** on every channel — this is gate G3's finding proven on hardware rather than in an offline render; CUTOFF, RESO, ENV and DECAY all audible on BASS, LEAD and PADS.

- [ ] **Step 4: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(techno): CONTROL pages with per-channel wet sends"
```

---

## Task 11: ALL page — key, tempo, master, and the ganged space

**Files:**
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `techno_lib.delay_ms`, `techno_lib.SCALES`, `fx_handle`.
- Produces: ROOT, SCALE (both land on the bar), BPM, MASTER, and the four ganged FX columns broadcast to all eight instances.

- [ ] **Step 1: Broadcast a ganged parameter to eight instances**

```python
    def _set_ganged(self, which, role, value):
        table = tlib.FX_REVERB if which == "reverb" else tlib.FX_DELAY
        symbol, lo, hi = table[role]
        target = lo + (hi - lo) * (value / 100.0) if role != "DLYTIME" else value
        for channel in range(len(tlib.CHANNELS)):
            proc = self.fx_handle(channel, which)
            if proc is None:
                continue
            zctrl = proc.controllers_dict.get(symbol)
            if zctrl is not None:
                zctrl.set_value(target, True)
```

- [ ] **Step 2: Recompute delay time on the display tick, never per encoder event**

In the 100 ms tick:

```python
        bpm = self.zynseq.libseq.getTempo()
        ms = tlib.delay_ms(bpm, self.globals["dlytime"])
        if abs(ms - self._last_delay_ms) > 0.5:
            self._last_delay_ms = ms
            self._set_ganged("delay", "DLYTIME", ms)
```

- [ ] **Step 3: Land ROOT and SCALE on the bar**

Both go into `self.globals["pending"]` when turned and are applied at the next bar boundary by the poll thread, which then forces a rewrite of every voice so the new key is heard immediately at the bar line. Also call `setScale` / `setTonic` on each pattern so the touchscreen editor draws the right keyboard — free, persisted, cosmetic, and it does **not** quantise incoming notes.

- [ ] **Step 4: Deploy and verify on hardware**

**Verify:** all three voices follow a ROOT change and they land together on the bar, with `>A<` shown until they do; DLYTIME tracks a BPM change from 128 to 140 without a click; one turn of REVSIZE moves all eight reverb instances; MASTER moves the main strip and the touchscreen fader follows.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(techno): ALL page with ganged FX and bar-synced key changes"
```

---

## Task 12: Mute, solo, transport and a safe ERASE

**Files:**
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Produces: L1's tap-latches / hold-is-momentary on F1-F8 (CC 39-46) and SOLO (CC 31); Play (CC 1), Restart (CC 7); ERASE (CC 2) as **hold-only**.

F1-F8 are mute, not solo, because mute is used perhaps sixty times a set and solo perhaps four — and because it is what the shipped rig already does, which is what removed SHIFT and therefore all daemon work from the prototype.

- [ ] **Step 1: Implement the 250 ms latch/momentary split**

```python
HOLD_MS = 250

    def _button_down(self, key):
        self._down_at[key] = time.monotonic()

    def _button_up(self, key, action_latch, action_release):
        held = (time.monotonic() - self._down_at.pop(key, 0)) * 1000.0
        if held >= HOLD_MS:
            action_release()        # momentary: undo what the press did
        else:
            action_latch()          # tap: leave it latched
```

- [ ] **Step 2: Make ERASE safe**

A bare ERASE press does nothing at all. Hold ERASE + pad clears that step; hold ERASE + Group sets that channel's generator to silence — HITS → 0 on a drum, CHANCE → 0 on a voice — **never** wiping the note list, because a wiped list is overwritten by the next generator move and the erase would appear not to have worked. This is an accepted regression against the shipped rig, where a bare press cleared the selected group.

- [ ] **Step 3: Deploy and verify on hardware**

**Verify:** tap F3 and CLAP stays muted; hold F3 and it returns on release; hold SOLO + F1 and only the kick sounds, release and everything returns; tap SOLO and the F row becomes solos until tapped again; a bare ERASE press does nothing; Play starts and stops all eight via `setPlayState`; Restart puts every channel on step 0.

- [ ] **Step 4: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(techno): mute, momentary solo, safe erase"
```

---

## Task 13: Snapshot round trip, including the Turing registers

**Files:**
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Produces: `get_state()` / `set_state()` overrides on `zynthian_ctrldev_base` carrying ROOT, SCALE, the page, the selected channel, and **every voice's register plus its 4-deep ring**.

**Persist driver state from day one.** Adding it later means every existing snapshot is missing it.

- [ ] **Step 1: Serialise the driver state**

```python
    def get_state(self):
        return {
            "globals": {k: v for k, v in self.globals.items() if k != "pending"},
            "voices": {
                str(i): {"register": self.state[i]["register"],
                         "ring": list(self.state[i]["ring"])}
                for i, ch in enumerate(tlib.CHANNELS) if ch[2] == "voice"
            },
        }

    def set_state(self, state):
        self.globals.update(state.get("globals", {}))
        for key, v in state.get("voices", {}).items():
            i = int(key)
            self.state[i]["register"] = v["register"]
            self.state[i]["ring"] = deque(v["ring"], maxlen=4)
```

- [ ] **Step 2: Re-force LOOP and clear the LED cache on restore**

In the existing `_on_snapshot` handler: re-force LOOP play mode on every sequence (a restore rewrites play mode from the `.zss`, and a LOOPALL sequence shorter than the bar goes RESTARTING then STARTING and falls silent until the next bar sync), re-derive the cached parameters, and **clear `led_cache`** or the repaint is suppressed as unchanged.

- [ ] **Step 3: Verify on hardware, mid-transport**

**Verify:** with the rig playing, save a snapshot, change everything, reload — patterns, divisions, chance, swing, mutes, presets, insert wets **and every Turing register plus its ring** all return; the locked voice still repeats the exact line it had; every LED repaints; nothing falls silent at the reload.

- [ ] **Step 4: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(techno): persist driver state including Turing registers and ring"
```

---

## Task 14: The twenty-minute jam

**Files:** none — this is the acceptance gate.

**Part 9 is not optional and it is not a two-minute demo. The last bug of this shape took 95 seconds to appear.**

- [ ] **Step 1: Start the monitor**

```bash
ssh root@192.168.2.123 'python3 /root/jam_mon.py > /root/jam-techno.csv 2>&1 &'
```

- [ ] **Step 2: Play for twenty minutes**

All three voices at RANDOM > 0, all eight channels playing, pages and channels switched throughout, kits changed mid-jam, mutes and solos used, ROOT changed at least twice.

- [ ] **Step 3: Check the three things that have bitten before**

```bash
ssh root@192.168.2.123 'journalctl -u zynthian --since -25min | grep -ciE "segfault|traceback|exit code 139"'
ssh root@192.168.2.123 'journalctl --since -25min | grep -c "watchdog: input stalled, reopened"'
ssh root@192.168.2.123 'journalctl --since -25min | grep -ci xrun'
```

**Verify:** zero SIGSEGV, zero UI stall, `watchdog: input stalled, reopened` no more often than the healthy ~8 s baseline (roughly 150 lines in 20 minutes), and the xrun count is what the pre-jam baseline was.

- [ ] **Step 4: Write it up and close the gates**

Update `MD/todo.md` and `MD/inwork.md`, and record the measured numbers in `docs/superpowers/techno-machine/2026-08-10-gates-g1-g2-g3-results.md` under a "hardware verification" heading.

---

## Deferred, and where

**Pass two, in order:** Lock snapshots on SCENE (8 slots, pads 1-8, hold to store, tap to recall on the bar, encoder 1 = morph time in bars) · the verb layer (one daemon patch emitting SHIFT 49, SWING 50, VOLUME 51) · RATCHET via `setStutterCount` · Note Repeat and choke groups · big-encoder triage · PAD MODE play layer · a second Turing layer generating velocity · voice CHANCE back on the surface once RATCHET frees the drum page's column 8.

**Pass three:** a PERFORM page of eight freely assigned macros · a continuous morph-toward-a-slot knob · scoped Lock layers · sidechain ducking from channel A · per-drum tone controls as LV2s · a true shared reverb and delay bus · `setNotePlayChance` and per-step `addControl` automation.
