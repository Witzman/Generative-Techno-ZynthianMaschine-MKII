# SP4 — Channel Type Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let SHIFT + GRID switch the selected channel between drum and voice behaviour, so a drum kit can be played by the Turing register and a synth pulsed by the euclid generator.

**Architecture:** A per-channel `kind_override` that is `None` until the player switches, consulted ahead of the existing chain-derived kind so there is never a stored copy of the chain to go stale. Each channel keeps a sleeping state set for the kind it is not, restored on switching back. All mapping arithmetic — the register onto a kit's note list, the resolution precedence, the labels, the default state sets — lives in `techno_lib.py` where it is unit tested.

**Tech Stack:** Python 3 (stdlib `unittest`), `zynlibs.zynseq` C bindings, OSC to the `MaschineMK2_linux` Rust daemon.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-12-sp4-channel-type-design.md`. Every decision in it is agreed with the owner — do not re-litigate.
- **Every `libzynseq` call the driver makes must hold `self.lock`.** The library is not thread-safe and the driver reaches it from three threads. Unsynchronised access segfaulted the whole UI (exit 139). `self.lock` is an `RLock`, so re-entering it is safe.
- **Never do slow work on the MIDI thread.** `midi_event` holds `self.lock` for the whole event.
- **The driver cannot be imported on WSL** (`zynlibs.zynseq` is Pi-only). Driver changes verify with `python3 -m py_compile` only. Push logic into `techno_lib.py`.
- **Test command, from `~/zynth/zynthian-ui/zyngine/ctrldev/`:** `python3 -m unittest discover -s tests -q`. Baseline is **248 passing**; every task must leave it green.
- **Law L4:** a column whose source does not exist draws dead rather than drawing a lie.
- **Deploy by copying files, never with git.** The Pi's `zynthian-ui` runs upstream branch `oram-2601.1` with the three Maschine files as untracked drop-ins.
- **Pi access:** `ssh root@192.168.2.123` (mDNS `.local` does not resolve from WSL2).
- **Commit trailer:** `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `zyngine/ctrldev/techno_lib.py` | Pure arithmetic and tables: kit-note mapping, kind resolution, the type label, the per-kind default state sets | Modify |
| `zyngine/ctrldev/tests/test_techno_lib.py` | Unit tests for all of the above | Modify |
| `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py` | Gesture, override, stash, generator branching, display, persistence | Modify |
| `docs/superpowers/techno-machine/2026-08-12-sp4-test-findings.md` | Hardware test record | Create (Task 8) |

Tasks 1–4 are library-only and independently reviewable. Tasks 5–7 each change one driver behaviour and end with a `py_compile` plus the full unit suite. Task 8 deploys and tests on hardware.

---

### Task 1: Map the Turing register onto a kit's note list

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/techno_lib.py`
- Test: `~/zynth/zynthian-ui/zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: `techno_lib.rotations(register, length, steps)` (already exists)
- Produces: `techno_lib.kit_line(register, length, steps, kit_notes) -> list[int]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_techno_lib.py`, before the `if __name__` block:

```python
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
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest tests.test_techno_lib.TestKitLine -v
```

Expected: FAIL, `AttributeError: type object 'techno_lib' has no attribute 'kit_line'`

- [ ] **Step 3: Implement it**

In `techno_lib.py`, directly after `line()`:

```python
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
```

- [ ] **Step 4: Run the full suite**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest discover -s tests -q
```

Expected: OK, 254 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(sp4): walk the Turing register across a drum kit

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Kind resolution and the type label

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/techno_lib.py`
- Test: `~/zynth/zynthian-ui/zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `techno_lib.resolve_kind(override, chain_kind) -> str`
  - `techno_lib.next_kind(current) -> str`
  - `techno_lib.type_label(label, override) -> str`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest tests.test_techno_lib.TestKindResolution tests.test_techno_lib.TestTypeLabel -v
```

Expected: FAIL, `AttributeError: type object 'techno_lib' has no attribute 'resolve_kind'`

- [ ] **Step 3: Implement them**

In `techno_lib.py`, beside `hands_back` and `owner_label`:

```python
    KINDS = ("drum", "voice")

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
```

- [ ] **Step 4: Run the full suite**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest discover -s tests -q
```

Expected: OK, 261 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(sp4): kind resolution precedence and the type label

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Move the per-kind default state into the library

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/techno_lib.py`
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`
- Test: `~/zynth/zynthian-ui/zyngine/ctrldev/tests/test_techno_lib.py`

The driver builds a channel's starting state inline in `__init__`. Task 5 needs
to build the *other* kind's set on the first switch, and R2 in the spec is that
a half-built set crashes `columns()`, which reads `state["cutoff"]` directly.
One tested builder, used by both, is the fix.

**Interfaces:**
- Consumes: nothing
- Produces: `techno_lib.default_channel_state(kind) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
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
                    "gate", "octave", "range", "density", "length",
                    "register", "ring"):
            self.assertIn(key, st, f"voice is missing {key}")

    def test_pending_is_a_fresh_set_each_call(self):
        a = tl.default_channel_state("drum")
        b = tl.default_channel_state("drum")
        a["pending"].add("div")
        self.assertEqual(b["pending"], set())

    def test_a_voice_starts_locked_and_at_full_density(self):
        st = tl.default_channel_state("voice")
        self.assertEqual(st["random"], 0)
        self.assertEqual(st["density"], 100)
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest tests.test_techno_lib.TestDefaultChannelState -v
```

Expected: FAIL, `AttributeError: type object 'techno_lib' has no attribute 'default_channel_state'`

- [ ] **Step 3: Implement it**

In `techno_lib.py`, beside `resolve_kind`:

```python
    @staticmethod
    def default_channel_state(kind):
        """A complete starting state set for one kind.

        Complete is the point: columns() indexes state["cutoff"] and friends
        directly, so a half-built voice set is a KeyError on the render path.
        The driver's __init__ and SP4's first switch both build through here
        so the two can never drift apart."""
        state = dict(level=19, reverb=0, delay=0, swing=50, velo=110,
                     chance=100, pending=set())
        if kind == "drum":
            state.update(kit="----", sample="----")
        else:
            state.update(preset="----", cutoff=64, reso=32, env=64,
                         decay=40, random=0, gate=40, octave=0, range=2,
                         density=100, length=8, register=0,
                         ring=deque(maxlen=4))
        return state
```

`techno_lib.py` imports only `random` today. Add `from collections import deque`
beside it — verified absent, so this import is required, not conditional. The
module's header says "no Zynthian imports, no I/O, no state"; a stdlib container
does not break that, and returning a real `deque` here means neither call site
has to remember to wrap a list.

- [ ] **Step 4: Point the driver's `__init__` at it**

In `zynthian_ctrldev_maschine_mk2.py`, replace the per-channel state build in
`__init__` — the `common = dict(...)` block and its `if ch[2] == "drum": / else:`
branches — with:

```python
        for idx, ch in enumerate(tlib.CHANNELS):
            common = tlib.default_channel_state(ch[2])
```

Keep every line that follows the branch unchanged, including whatever the
existing code does with `register`, `ring` and `length` for voices: if the
driver seeds a voice's register from a table or a random value, that seeding
stays in the driver and simply overwrites the library's `0`.

- [ ] **Step 5: Verify**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo COMPILED
python3 -m unittest discover -s tests -q
```

Expected: `COMPILED`, then OK, 266 tests.

- [ ] **Step 6: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py \
        zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "refactor(sp4): one tested builder for a channel's default state

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Split the chain-derived kind from the resolved kind

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `techno_lib.resolve_kind`
- Produces: `self.kind_override` (dict `channel -> "drum" | "voice" | None`), `self._chain_kind(channel)`, `self._is_sampler(channel)`

No behaviour changes in this task: with every override `None`, `channel_kind`
returns exactly what it returns today. That is the point — the untouched path
stays the tested one.

- [ ] **Step 1: Add the override state**

In `__init__`, beside `self.owner`:

```python
        # Which kind a channel behaves as, when the player has said so.
        # None means "ask the chain" - never a stored copy of it.
        self.kind_override = {i: None for i in range(len(tlib.CHANNELS))}
```

- [ ] **Step 2: Rename the existing derivation and add the resolver**

Rename the current `channel_kind` to `_chain_kind` — keep its whole body and
docstring — and add above it:

```python
    def channel_kind(self, channel):
        """The kind a channel behaves as: the player's override if set,
        otherwise whatever its chain says."""

        return tlib.resolve_kind(self.kind_override[channel],
                                 self._chain_kind(channel))

    def _is_sampler(self, channel):
        """Does this channel's CHAIN run a sampler, regardless of how the
        channel is behaving? SP4 lets a kit be driven by the Turing register,
        so 'behaves as a voice' and 'is a synth' stop being the same question."""

        return self._chain_kind(channel) == "drum"
```

- [ ] **Step 3: Verify nothing moved**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo COMPILED
python3 -m unittest discover -s tests -q
grep -c "_chain_kind" zynthian_ctrldev_maschine_mk2.py
```

Expected: `COMPILED`, OK 266 tests, and the grep finds **3** occurrences —
the definition plus the two calls in `channel_kind` and `_is_sampler`. More than
three means a call site was renamed that should have kept using the resolved
`channel_kind`.

- [ ] **Step 4: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "refactor(sp4): separate the chain's kind from the resolved kind

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The gesture, the stash, and the switch

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `techno_lib.next_kind`, `techno_lib.default_channel_state`, `self.kind_override`, `self._chain_kind`, `self._handback` and `self._release_all` (both from SP2)
- Produces: `CC_SHIFT`, `CC_GRID`, `self.shift_down`, `self.stash`, `self._toggle_kind()`

- [ ] **Step 1: Add the constants**

Beside `CC_REC`:

```python
# SHIFT has emitted since SP1's daemon patch with no consumer; GRID was
# measured at gate G4 and left unbound. SP4 is the first user of both.
CC_SHIFT = 49
CC_GRID = 4
```

- [ ] **Step 2: Add the state**

In `__init__`, beside `self.kind_override`:

```python
        self.shift_down = False
        # The sleeping state set per channel and kind: channel -> kind -> dict.
        # Pure driver state - nothing in zynseq mirrors it, so there is nothing
        # to read back and nothing that can drift behind us.
        self.stash = {i: {} for i in range(len(tlib.CHANNELS))}
```

- [ ] **Step 3: Handle both buttons**

In `_midi_event`, in the state-carrying block beside `CC_REC`:

```python
            if cc_num == CC_SHIFT:
                self.shift_down = down
                return True
```

And in the press-only section, beside `CC_DUPLICATE`:

```python
            if cc_num == CC_GRID:
                if self.shift_down:
                    self._toggle_kind()
                return True
```

A bare GRID press is swallowed and does nothing. That is deliberate: it stays
free for a later feature and cannot fall through to something that reacts to it.

- [ ] **Step 4: Write the switch**

Beside `_handback`:

```python
    def _toggle_kind(self):
        """SHIFT + GRID: the selected channel changes what it behaves as.

        Switching back to the chain's own kind clears the override rather than
        pinning it to the same value - otherwise one press would freeze a
        channel to a kind it merely happens to have today, and a later snapshot
        putting a different engine on that chain would be overruled by a stale
        choice nobody remembers making.

        The switch rewrites the pattern, so on a player-owned channel SP2's
        rule applies unchanged: hand back, and the take is gone. A second
        contradictory rule for the same situation would be worse than the
        loss."""

        channel = self.group
        old = self.channel_kind(channel)
        new = tlib.next_kind(old)

        self._release_all()
        if self.owner[channel] == "player":
            self._handback(channel)

        # Stash the set we are leaving, restore or build the one we arrive at.
        self.stash[channel][old] = self.state[channel]
        self.stash[channel][old + ":hits"] = self.hits[channel]
        self.stash[channel][old + ":rot"] = self.rot[channel]
        self.state[channel] = self.stash[channel].get(
            new, tlib.default_channel_state(new))
        self.hits[channel] = self.stash[channel].get(new + ":hits",
                                                     self.hits[channel])
        self.rot[channel] = self.stash[channel].get(new + ":rot",
                                                    self.rot[channel])

        # div and beats are pattern TIME, not kind: they mean the same to both
        # and moving them would make the groove jump on a switch.
        self.kind_override[channel] = None if new == self._chain_kind(channel) else new

        if new == "voice":
            self._write_voice_pattern(channel)
        else:
            self._write_pattern(channel)
        self._recentre_encoders()
        self._render_all()
```

- [ ] **Step 5: Verify**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo COMPILED
python3 -m unittest discover -s tests -q
```

Expected: `COMPILED`, then OK, 266 tests.

- [ ] **Step 6: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(sp4): SHIFT+GRID switches a channel's kind, with per-kind memory

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: The generators on foreign ground

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `techno_lib.kit_line`, `techno_lib.line`, `techno_lib.pad_note`, `self._is_sampler`, `self._keymap(channel)` (returns a list of `(note_number, name)`)
- Produces: `self._voice_notes(channel, steps)`

- [ ] **Step 1: Add the one place that decides what a voice line is**

Beside `_step_notes`:

```python
    def _voice_notes(self, channel, steps):
        """The notes a voice-behaving channel's line uses.

        On a synth this is the scale-quantised Turing line as always. On a
        SAMPLER chain the register walks the kit's own note list instead,
        because a note number there selects which drum sounds, not a pitch -
        quantising to a scale would land most steps on empty keys, and an
        empty key is silence with nothing to explain it.

        The single place both the writer and the pad renderer ask, so they
        can never disagree about what is on a step."""

        st = self.state[channel]
        if self._is_sampler(channel):
            kit = [num for num, _ in self._keymap(channel)]
            notes = tlib.kit_line(st["register"], st["length"], steps, kit)
            # An unreadable or empty kit degrades to the channel's own drum,
            # never to silence.
            return notes or [self._group_note(channel)] * steps
        return tlib.line(st["register"], st["length"], steps,
                         self.globals["root"], self.globals["scale"],
                         st["octave"], st["range"])
```

- [ ] **Step 2: Use it in the writer**

In `_write_voice_pattern`, replace the `notes = tlib.line(...)` call with:

```python
            notes = self._voice_notes(channel, steps)
```

- [ ] **Step 3: Use it in both pad renderers**

In `_step_notes`, replace the `tlib.line(...)` call with
`self._voice_notes(channel, max(1, steps))`, and in `_step_note` replace its
`tlib.line(...)` call with `self._voice_notes(channel, steps)`. Both keep their
existing fallbacks to `self._group_note(channel)` untouched.

- [ ] **Step 4: Give euclid a pitch on a synth**

In `_write_pattern`, replace `note = self._group_note(group)` with:

```python
        if self._is_sampler(group):
            note = self._group_note(group)
        else:
            # Euclid on a synth is a root pulse: ROOT transposes it, OCTAVE
            # places it. Reusing whatever pitch _group_note discovers would
            # leave the voice stuck on an arbitrary note no control can reach.
            note = tlib.pad_note(0, self.globals["root"], self.globals["scale"],
                                 self.state[group].get("octave", 0))
```

- [ ] **Step 5: Verify**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo COMPILED
python3 -m unittest discover -s tests -q
grep -c "tlib.line(" zynthian_ctrldev_maschine_mk2.py
```

Expected: `COMPILED`, OK 266 tests, and the grep finds **1** — only the call
inside `_voice_notes`. More than one means a call site was missed and the pads
will disagree with the writer about what is on a step.

- [ ] **Step 6: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(sp4): Turing walks a kit, euclid pulses a synth's root

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Dead synth columns, the label, and persistence

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/techno_lib.py`
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`
- Test: `~/zynth/zynthian-ui/zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: `techno_lib.type_label`, `self.kind_override`, `self.stash`
- Produces: the `has_synth_ctrl` key in a channel's view

- [ ] **Step 1: Write the failing test**

```python
class TestDeadSynthColumns(unittest.TestCase):

    def _voice_state(self, has_synth_ctrl):
        st = tl.default_channel_state("voice")
        st["has_synth_ctrl"] = has_synth_ctrl
        return st

    def test_a_synth_draws_its_four_control_columns(self):
        desc = tl.PAGE_RINGS[("CONTROL", "voice")][0]
        cols = tl.columns(desc, "voice", self._voice_state(True))
        names = [c["name"] for c in cols]
        for want in ("CUTOFF", "RESO", "ENV", "DECAY"):
            self.assertIn(want, names)
        for col in cols:
            if col["name"] in ("CUTOFF", "RESO", "ENV", "DECAY"):
                self.assertFalse(col["grey"], f"{col['name']} should be live")

    def test_a_sampler_in_voice_mode_draws_them_dead(self):
        # Law L4: a column whose source does not exist draws dead rather than
        # drawing a lie. LinuxSampler publishes no filter controls at all.
        desc = tl.PAGE_RINGS[("CONTROL", "voice")][0]
        cols = tl.columns(desc, "voice", self._voice_state(False))
        for col in cols:
            if col["name"].upper() in ("CUTOFF", "RESO", "ENV", "DECAY"):
                self.assertTrue(col["grey"], f"{col['name']} should be dead")

    def test_a_missing_flag_is_treated_as_present(self):
        # Every caller before SP4 omits the key; omitting it must not grey a
        # working synth.
        desc = tl.PAGE_RINGS[("CONTROL", "voice")][0]
        st = tl.default_channel_state("voice")
        cols = tl.columns(desc, "voice", st)
        names = [c["name"] for c in cols if not c["grey"]]
        self.assertIn("CUTOFF", names)
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest tests.test_techno_lib.TestDeadSynthColumns -v
```

Expected: FAIL — `test_a_sampler_in_voice_mode_draws_them_dead` asserts a grey
column that is currently drawn live.

- [ ] **Step 3: Implement it**

In `techno_lib.columns()`, in the voice CONTROL branch, replace the four
hand-written columns with:

```python
                c("PRESET", state["preset"], "seg", (0, 1), pending="preset" in p),
            ] + ([
                c("CUTOFF", n(state["cutoff"]), "uni", state["cutoff"] / 127.0),
                c("RESO", n(state["reso"]), "uni", state["reso"] / 127.0),
                c("ENV", n(state["env"]), "uni", state["env"] / 127.0),
                c("DECAY", n(state["decay"]), "uni", state["decay"] / 127.0),
            ] if state.get("has_synth_ctrl", True) else [
                # SP4: a sampler chain behaving as a voice has no filter
                # controls to reach. Law L4 - draw dead, never a number the
                # knob cannot move.
                dead("cutoff"), dead("reso"), dead("env"), dead("decay"),
            ]) + tail
```

Keep the list opened before `PRESET` exactly as it is; only the four columns
after it become conditional.

- [ ] **Step 4: Publish the flag from the driver**

In `state_view`, in the `else:` branch that already sets `view["preset"]`:

```python
        else:
            view["preset"] = (self._preset_name(channel) or "----")[:4]
        # SP4: a channel can behave as a voice while its chain runs a sampler.
        # VOICE_SYMBOLS is keyed by engine code and has no LinuxSampler entry,
        # so _set_voice_ctrl already bails out - the columns must say so.
        view["has_synth_ctrl"] = bool(
            tlib.VOICE_SYMBOLS.get(tlib.CHANNELS[channel][4]))
```

Place the `has_synth_ctrl` line outside the `if/else` so it is set for both
kinds.

- [ ] **Step 5: Add the label**

In `_render_display`, after the existing `owner_label` call:

```python
        label = tlib.type_label(label, self.kind_override[self.group])
```

- [ ] **Step 6: Persist the overrides and the stash**

First add a serialiser beside `get_state`, because a state set carries two
things a snapshot cannot hold: `pending` is a `set` and `ring` is a `deque`.

```python
    @staticmethod
    def _stash_out(value):
        """One stashed entry on its way into a snapshot. Ints pass through;
        a state dict loses its `pending` set and hands over its ring as a
        plain list, because neither survives JSON."""

        if not isinstance(value, dict):
            return value
        out = {k: v for k, v in value.items() if k != "pending"}
        if "ring" in out:
            out["ring"] = list(out["ring"])
        return out
```

Then in `get_state`, beside `"owners"`:

```python
            "kinds": {str(i): self.kind_override[i]
                      for i in range(len(tlib.CHANNELS))
                      if self.kind_override[i] is not None},
            "stash": {str(i): {k: self._stash_out(v) for k, v in sets.items()}
                      for i, sets in self.stash.items() if sets},
```

In `set_state`, beside the `owners` restore:

```python
        for key, kind in (state.get("kinds") or {}).items():
            try:
                channel = int(key)
            except (TypeError, ValueError):
                continue
            if channel in self.kind_override and kind in tlib.KINDS:
                self.kind_override[channel] = kind

        for key, sets in (state.get("stash") or {}).items():
            try:
                channel = int(key)
            except (TypeError, ValueError):
                continue
            if channel not in self.stash:
                continue
            restored = {}
            for name, value in sets.items():
                if isinstance(value, dict):
                    value = dict(value)
                    value["pending"] = set()
                    if "ring" in value:
                        value["ring"] = deque(value["ring"], maxlen=4)
                restored[name] = value
            self.stash[channel] = restored
```

`pending` is rebuilt empty rather than restored: it is a set of parameters
waiting for the next bar, and a snapshot load has no bar to wait for.

- [ ] **Step 7: Verify**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo COMPILED
python3 -m unittest discover -s tests -q
```

Expected: `COMPILED`, then OK, 269 tests.

- [ ] **Step 8: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py \
        zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(sp4): dead synth columns on a sampler, type label, persistence

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Deploy and hardware test

**This task needs the owner at the Maschine.**

**Files:**
- Create: `~/zynth-docs/docs/superpowers/techno-machine/2026-08-12-sp4-test-findings.md`

- [ ] **Step 1: Deploy by file copy**

```bash
ssh root@192.168.2.123 'cd /zynthian/zynthian-ui/zyngine/ctrldev && \
  cp zynthian_ctrldev_maschine_mk2.py /root/maschine_mk2.pre-sp4.bak && \
  cp techno_lib.py /root/techno_lib.pre-sp4.bak'
scp ~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py \
    ~/zynth/zynthian-ui/zyngine/ctrldev/techno_lib.py \
    root@192.168.2.123:/zynthian/zynthian-ui/zyngine/ctrldev/
```

- [ ] **Step 2: Restart daemon first, UI second**

```bash
ssh root@192.168.2.123 'systemctl restart maschine-mk2 && sleep 4 && systemctl restart zynthian'
```

Restarting `maschine-mk2` alone makes a2j re-register the Pads port onto a new
zmip slot while the ctrldev driver stays bound to the dead one — the rig goes
silent with no error.

- [ ] **Step 3: Confirm exactly one route and no traceback**

```bash
ssh root@192.168.2.123 'jack_lsp -c | grep -A3 "Pads MIDI"; \
  journalctl -u zynthian --since "-3 min" --no-pager | grep -i -E "maschine|traceback" | tail'
```

Expected: exactly **one** `devN_in`, and no traceback.

- [ ] **Step 4: Drum to voice — the kit walk**

Load `016-techno_maschine`. Select group **A (KICK)**, start transport, hold
**SHIFT** and press **GRID**.

Expected: the channel starts playing **different drums from its kit** step by
step, **no silence on any step**, and the page indicator reads **`VOX`**.

- [ ] **Step 5: Switch back — the memory**

Note the HITS and ROTATE values first. Hold SHIFT and press GRID again.

Expected: the euclid pattern returns with HITS and ROTATE **exactly** as they
were, and the `VOX` marker is gone — the override cleared itself because the
channel again agrees with its chain.

- [ ] **Step 6: Voice to drum — the root pulse**

Select group **F (BASS)**, hold SHIFT and press GRID.

Expected: a single repeated pitch in a euclidean rhythm, the indicator reads
**`DRM`**, and turning **ROOT** on the ALL page transposes the pulse audibly.

- [ ] **Step 7: Dead columns**

With group A in voice mode, page to the voice CONTROL page.

Expected: **CUTOFF, RESO, ENV and DECAY draw dead**, not numbers. Turning those
encoders does nothing, and the display says why by being greyed rather than by
showing a value that will not move.

- [ ] **Step 8: Player-owned handback**

Put group A back to drum. Record a take on it with REC. Then hold SHIFT and
press GRID.

Expected: the take is gone and the generator's pattern is back, exactly as
turning HITS does — and the pads return to the group colour from amber.

- [ ] **Step 9: Snapshot round trip**

Switch group A to voice, save a snapshot from the touchscreen ("Save as new
snapshot" inside bank `000` — **never** the webconf name field, which renames
the bank). Load another snapshot, then load this one back.

Expected: group A is still in voice mode with `VOX` showing, the kit walk plays,
and switching back restores the drum settings that were stashed before saving.

- [ ] **Step 10: Write up and commit the findings**

Record every check as pass or fail with what was observed, in
`2026-08-12-sp4-test-findings.md`. Commit it to `zynth-docs`.

- [ ] **Step 11: Update the tracking files**

Mark SP4 done in `MD/todo.md` and update the RESUME HERE block in `CLAUDE.md`.
Commit and push both repos.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §2 the gesture, SHIFT + GRID | 5 |
| §2 switching back clears the override | 5 (`kind_override = None if new == chain`) |
| §2 destructive, hands back on a player-owned channel | 5 |
| §3 override consulted first, one source of truth | 2 (`resolve_kind`), 4 (`channel_kind`) |
| §3 the eight behaviours that follow `channel_kind` | 4 — they already read `channel_kind`, which now resolves |
| §3 dead CUTOFF/RESO/ENV/DECAY on a sampler | 7 |
| §4 Turing walks the kit's note list | 1, 6 |
| §4 empty kit falls back to the channel's note | 1 (returns `[]`), 6 (`notes or [...]`) |
| §4 euclid on a synth is ROOT + OCTAVE | 6 |
| §5 per-kind state memory, `hits`/`rot` stashed | 5 |
| §5 `div` and `beats` not stashed | 5 — the switch never touches them, and the comment says why |
| §6 `kinds` and `stash` persisted | 7 |
| §7 `DRM` / `VOX` on the page indicator | 2 (`type_label`), 7 (wiring) |
| §9 unit tests | 1, 2, 3, 7 |
| §9 hardware checks | 8 |
| §10 R1 empty kit | 1, 6 |
| §10 R2 half-built state set | 3 (`default_channel_state`) |
| §10 R3 pad held during a switch | 5 (`_release_all`) |
| §10 R4 switch during a Turing write | 5 — `_write_voice_pattern` takes the lock and checks `owner` itself |

No gaps.

**Placeholder scan:** none — every code step carries its actual code. The two
`grep -c` checks in Tasks 4 and 6 exist because both are refactors where a
missed call site fails silently rather than loudly.

**Type consistency:** `resolve_kind(override, chain_kind)`, `next_kind(current)`
and `type_label(label, override)` are defined in Task 2 and called with those
signatures in Tasks 4, 5 and 7. `kit_line(register, length, steps, kit_notes)`
is defined in Task 1 and called that way in Task 6. `default_channel_state(kind)`
is defined in Task 3 and called in Tasks 3 and 5. `self.kind_override` is
`channel -> "drum" | "voice" | None` in `__init__`, `channel_kind`,
`_toggle_kind`, `get_state`, `set_state` and `_render_display`. `self.stash` is
`channel -> {kind: dict, kind + ":hits": int, kind + ":rot": int}` in
`__init__`, `_toggle_kind`, `get_state` and `set_state`.
