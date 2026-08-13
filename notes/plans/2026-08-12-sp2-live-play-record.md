# SP2 — Live Pad Play and REC Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Maschine pads an instrument in every mode but STEP, and let REC held capture what is played into the same pattern the generator writes.

**Architecture:** All arithmetic (quantise, duration, pad→note, candidate sets, handback rules) goes into `techno_lib.py`, where it is unit-tested on WSL. The driver keeps only the parts that must touch `libzynseq`, the LEDs and the display — it cannot be imported on WSL and verifies with `py_compile` and nothing more. A new durable `owner[channel]` flag decides who writes a pattern; a rebuilt-not-trusted note map tells the grid which steps a human played.

**Tech Stack:** Python 3 (stdlib `unittest`), `zynlibs.zynseq` C bindings, OSC to the `MaschineMK2_linux` Rust daemon.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-12-sp2-live-play-record-design.md`. Every decision in it is agreed with the owner — do not re-litigate.
- **Every `libzynseq` call the driver makes must hold `self.lock`.** The library is not thread-safe and the driver reaches it from three threads. Unsynchronised access segfaulted the whole UI (exit 139).
- **Never do slow work on the MIDI thread.** `midi_event` holds `self.lock` for the whole event. Preset loads and pattern scans go on the poll thread.
- **The driver cannot be imported on WSL** (`zynlibs.zynseq` is Pi-only). Driver changes verify with `python3 -m py_compile` only. Push logic into `techno_lib.py`.
- **Test command, from `~/zynth/zynthian-ui/zyngine/ctrldev/`:** `python3 -m unittest discover -s tests -q`. Baseline is **217 passing**; every task must leave it green.
- **`_set_value()` truncates INTEGER controls only.** Do not reintroduce range-width heuristics.
- **Deploy by copying files, never with git.** The Pi's `zynthian-ui` runs upstream branch `oram-2601.1` with the three Maschine files as untracked drop-ins; `MaschineMK2_linux`'s Pi HEAD is an old display experiment with the live code uncommitted. A `git reset --hard` there destroys working code.
- **Pi access:** `ssh root@192.168.2.123` (mDNS `.local` does not resolve from WSL2).
- **Commit trailer:** `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `zyngine/ctrldev/techno_lib.py` | Pure arithmetic and tables: quantise, duration, pad→note, candidate sets, handback rules, label text | Modify |
| `zyngine/ctrldev/tests/test_techno_lib.py` | Unit tests for all of the above | Modify |
| `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py` | Event dispatch, `libzynseq` calls, LEDs, display | Modify |
| `docs/superpowers/techno-machine/2026-08-12-g5-capture.log` | Raw `aseqdump` output from Task 1 | Create |
| `docs/superpowers/techno-machine/2026-08-12-sp2-g5-results.md` | What G5 measured and what it changes | Create |

Tasks 2–5 are library-only and independently reviewable. Tasks 6–10 each change one driver behaviour and end with a `py_compile` plus the full unit suite. Task 11 deploys and tests on hardware.

---

### Task 1: Gate G5 — capture at the panel

**This task needs the owner physically at the Maschine.** Nothing else in the
plan can start until it finishes: the G4 lesson is that the daemon's token
names are attached to the wrong physical buttons, and two CCs were wrong in
this project's documentation for three days because they were read out of
source instead of measured.

**Files:**
- Create: `~/zynth-docs/docs/superpowers/techno-machine/2026-08-12-g5-capture.log`
- Create: `~/zynth-docs/docs/superpowers/techno-machine/2026-08-12-sp2-g5-results.md`

**Interfaces:**
- Consumes: nothing
- Produces: the measured value of `CC_REC` (Task 7 hardcodes it), a yes/no on pad NoteOff reaching the ALSA port (Task 6 depends on it), and a yes/no on `getNoteDuration` / `getNoteStart` existing in the installed `.so` (Task 9 branches on it)

- [ ] **Step 1: Find the daemon's ALSA port**

```bash
ssh root@192.168.2.123 'aseqdump -l | grep -i -E "maschine|pads"'
```

Expected: a line naming the daemon's `Pads MIDI` port with a client:port
number, e.g. `129:0`.

- [ ] **Step 2: Start the capture**

```bash
ssh root@192.168.2.123 'timeout 180 aseqdump -p <client:port>' \
  | tee ~/zynth-docs/docs/superpowers/techno-machine/2026-08-12-g5-capture.log
```

Leave it running for the next three steps.

- [ ] **Step 3: Owner presses REC once**

Expected in the log: two `Control change` lines on the same controller number,
value 127 then value 0.

**Record the controller number.** The daemon's source says 3 (`main.rs:938`,
token `rec`). If the capture says anything else, the capture wins — that is the
entire point of this gate.

- [ ] **Step 4: Owner presses and HOLDS pad 1, waits two seconds, releases**

Expected: `Note on` with a velocity, then — two seconds later — `Note off`
(or `Note on` with velocity 0).

If **no note-off appears**, the daemon is in `padmode == 2` and is swallowing
it (`main.rs:1411` makes note-off conditional on `padmode != 2`). Stop and
report: the whole spec's hold-time duration rests on this event existing.

- [ ] **Step 5: Owner presses and holds pad 1 while turning encoder 1**

Expected: the note stays on, encoder CCs interleave. This confirms a held note
survives other traffic and is not cancelled by the daemon.

- [ ] **Step 6: Audit the installed libzynseq symbols**

```bash
ssh root@192.168.2.123 'nm -D --defined-only /zynthian/zynthian-ui/zynlibs/zynseq/build/libzynseq.so | awk "\$2==\"T\"{print \$3}" | sort | grep -i -E "note|play"'
```

Expected to be present: `playNote`, `addNote`, `removeNote`,
`getNoteVelocity`, `getRefNote`.
**Record present/absent for: `getNoteDuration`, `getNoteStart`.**
`getNoteAtIndex` is known absent — its absence confirms the audit ran against
the right file.

- [ ] **Step 7: Write the results document**

Create `2026-08-12-sp2-g5-results.md` with: the measured REC CC, whether pad
note-off appears, whether `getNoteDuration` and `getNoteStart` exist, and the
`playNote` arity. State each as measured, with the log line that shows it.

- [ ] **Step 8: Commit**

```bash
cd ~/zynth-docs
git add docs/superpowers/techno-machine/2026-08-12-g5-capture.log \
        docs/superpowers/techno-machine/2026-08-12-sp2-g5-results.md
git commit -m "docs: SP2 gate G5 — REC CC, pad note-off and note API measured

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Quantise a strike to the nearest step

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/techno_lib.py`
- Test: `~/zynth/zynthian-ui/zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: nothing
- Produces: `techno_lib.record_step(playpos, cps, steps) -> int` — a step index in `range(steps)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_techno_lib.py`, before the `if __name__` block:

```python
class TestRecordStep(unittest.TestCase):

    def test_the_start_of_a_step_is_that_step(self):
        self.assertEqual(tl.record_step(0, 24, 16), 0)
        self.assertEqual(tl.record_step(48, 24, 16), 2)

    def test_just_before_the_midpoint_stays_on_the_step(self):
        self.assertEqual(tl.record_step(11, 24, 16), 0)

    def test_the_midpoint_rounds_up(self):
        self.assertEqual(tl.record_step(12, 24, 16), 1)

    def test_a_late_strike_wraps_to_step_zero(self):
        # Step 15 of 16, past its midpoint: the loop wraps within a step, so
        # step 0 of the next pass IS the nearest grid line in time.
        self.assertEqual(tl.record_step(15 * 24 + 13, 24, 16), 0)

    def test_a_degenerate_pattern_never_raises(self):
        self.assertEqual(tl.record_step(100, 0, 16), 0)
        self.assertEqual(tl.record_step(100, 24, 0), 0)
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest tests.test_techno_lib.TestRecordStep -v
```

Expected: FAIL, `AttributeError: type object 'techno_lib' has no attribute 'record_step'`

- [ ] **Step 3: Implement it**

In `techno_lib.py`, in the `pitch` section right after `note_duration`:

```python
    @staticmethod
    def record_step(playpos, cps, steps):
        """Which step a live strike belongs to: the nearest grid line, wrapping.

        A strike past the midpoint of the last step lands on step 0 of the next
        pass, and that is not a delay - the loop wraps within one step, so the
        note fires immediately, at the position the player meant."""
        if cps <= 0 or steps <= 0:
            return 0
        return int((playpos + cps // 2) // cps) % steps
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest discover -s tests -q
```

Expected: OK, 222 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(sp2): quantise a live strike to the nearest step

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Hold time to note duration

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/techno_lib.py`
- Test: `~/zynth/zynthian-ui/zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: nothing
- Produces: `techno_lib.record_duration(held_clocks, cps, step, steps) -> float` — a duration in steps, minimum 1.0

- [ ] **Step 1: Write the failing tests**

```python
class TestRecordDuration(unittest.TestCase):

    def test_a_short_tap_is_one_step(self):
        self.assertEqual(tl.record_duration(3, 24, 0, 16), 1.0)

    def test_a_hold_rounds_to_whole_steps(self):
        self.assertEqual(tl.record_duration(24 * 4, 24, 0, 16), 4.0)
        self.assertEqual(tl.record_duration(24 * 4 + 13, 24, 0, 16), 5.0)

    def test_it_never_crosses_the_loop_point(self):
        # SP5's clamp: a note at step 15 of 16 can only be one step long.
        self.assertEqual(tl.record_duration(24 * 8, 24, 15, 16), 1.0)
        self.assertEqual(tl.record_duration(24 * 8, 24, 12, 16), 4.0)

    def test_a_full_length_hold_from_step_zero_fills_the_pattern(self):
        self.assertEqual(tl.record_duration(24 * 16, 24, 0, 16), 16.0)

    def test_a_degenerate_pattern_never_raises(self):
        self.assertEqual(tl.record_duration(100, 0, 0, 16), 1.0)
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest tests.test_techno_lib.TestRecordDuration -v
```

Expected: FAIL, `AttributeError: ... has no attribute 'record_duration'`

- [ ] **Step 3: Implement it**

Directly below `record_step`:

```python
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
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest discover -s tests -q
```

Expected: OK, 227 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(sp2): hold time to note duration, clamped at the loop point

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The pad keyboard and the candidate note set

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/techno_lib.py`
- Test: `~/zynth/zynthian-ui/zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: `techno_lib.SCALES`, `techno_lib.BASE_NOTE` (both already exist)
- Produces:
  - `techno_lib.pad_note(pad, root, scale_idx, octave) -> int`
  - `techno_lib.pad_notes(root, scale_idx, octave, count=16) -> tuple[int, ...]`
  - `techno_lib.candidate_notes(kind, group_note, pads=(), line=()) -> tuple[int, ...]`

- [ ] **Step 1: Write the failing tests**

```python
class TestPadKeyboard(unittest.TestCase):

    def test_pad_zero_is_the_root(self):
        # MIN, root C, octave 0 -> BASE_NOTE itself.
        self.assertEqual(tl.pad_note(0, 0, 0, 0), tl.BASE_NOTE)

    def test_pads_walk_up_the_scale(self):
        # MIN intervals are (0, 2, 3, 5, 7, 8, 10).
        got = [tl.pad_note(p, 0, 0, 0) for p in range(7)]
        self.assertEqual(got, [tl.BASE_NOTE + i for i in (0, 2, 3, 5, 7, 8, 10)])

    def test_the_scale_repeats_an_octave_up(self):
        self.assertEqual(tl.pad_note(7, 0, 0, 0), tl.pad_note(0, 0, 0, 0) + 12)

    def test_root_and_octave_transpose(self):
        self.assertEqual(tl.pad_note(0, 3, 0, 0), tl.BASE_NOTE + 3)
        self.assertEqual(tl.pad_note(0, 0, 0, 1), tl.BASE_NOTE + 12)

    def test_a_pentatonic_spans_more_octaves(self):
        # PENT is index 5, five notes: pad 5 is one octave up.
        self.assertEqual(tl.pad_note(5, 0, 5, 0), tl.pad_note(0, 0, 5, 0) + 12)

    def test_notes_are_clamped_into_midi_range(self):
        self.assertLessEqual(tl.pad_note(15, 11, 0, 2), 127)
        self.assertGreaterEqual(tl.pad_note(0, 0, 0, -2), 0)

    def test_pad_notes_gives_sixteen_ascending(self):
        notes = tl.pad_notes(0, 0, 0)
        self.assertEqual(len(notes), 16)
        self.assertEqual(list(notes), sorted(notes))


class TestCandidateNotes(unittest.TestCase):

    def test_a_drum_has_exactly_one_candidate(self):
        self.assertEqual(tl.candidate_notes("drum", 38), (38,))

    def test_a_voice_covers_its_keyboard_and_its_line(self):
        got = tl.candidate_notes("voice", 36, pads=(36, 38), line=(40, 38))
        self.assertEqual(got, (36, 38, 40))

    def test_the_voice_set_is_deduplicated_and_sorted(self):
        got = tl.candidate_notes("voice", 60, pads=(64, 60), line=(62, 64))
        self.assertEqual(got, (60, 62, 64))
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest tests.test_techno_lib.TestPadKeyboard tests.test_techno_lib.TestCandidateNotes -v
```

Expected: FAIL, `AttributeError: ... has no attribute 'pad_note'`

- [ ] **Step 3: Implement them**

In `techno_lib.py`, directly after `line()`:

```python
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
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest discover -s tests -q
```

Expected: OK, 237 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(sp2): pad keyboard and candidate note sets

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Handback rules and the ownership label

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/techno_lib.py`
- Test: `~/zynth/zynthian-ui/zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `techno_lib.HANDBACK_VERBS` — `dict[str, frozenset[str]]`
  - `techno_lib.hands_back(kind, verb, value=None) -> bool`
  - `techno_lib.owner_label(label, owner, recording, playing) -> str`

- [ ] **Step 1: Write the failing tests**

```python
class TestHandback(unittest.TestCase):

    def test_the_drum_content_knobs_hand_back(self):
        for verb in ("hits", "rotate", "div"):
            self.assertTrue(tl.hands_back("drum", verb))

    def test_drum_length_does_not_hand_back(self):
        # _set_length preserves the steps that fit, so it destroys nothing.
        self.assertFalse(tl.hands_back("drum", "length"))

    def test_the_voice_content_knobs_hand_back(self):
        for verb in ("length", "div"):
            self.assertTrue(tl.hands_back("voice", verb))

    def test_voice_length_is_the_register_not_the_bar_count(self):
        # Same verb name, opposite answer per kind - this is the whole reason
        # the rule is a table and not one list.
        self.assertTrue(tl.hands_back("voice", "length"))
        self.assertFalse(tl.hands_back("drum", "length"))

    def test_random_hands_back_only_when_it_moves_off_lock(self):
        self.assertTrue(tl.hands_back("voice", "random", 40))
        self.assertFalse(tl.hands_back("voice", "random", 0))

    def test_random_does_nothing_on_a_drum(self):
        self.assertFalse(tl.hands_back("drum", "random", 40))

    def test_an_unrelated_verb_never_hands_back(self):
        self.assertFalse(tl.hands_back("drum", "level"))
        self.assertFalse(tl.hands_back("voice", "gate"))


class TestOwnerLabel(unittest.TestCase):

    def test_a_generated_channel_shows_the_page_only(self):
        self.assertEqual(tl.owner_label("LEVEL 1/3", "gen", False, True),
                         "LEVEL 1/3")

    def test_a_player_owned_channel_says_so(self):
        self.assertEqual(tl.owner_label("LEVEL 1/3", "player", False, True),
                         "LEVEL 1/3 PLAY")

    def test_recording_wins_over_ownership(self):
        self.assertEqual(tl.owner_label("LEVEL 1/3", "player", True, True),
                         "LEVEL 1/3 REC")

    def test_rec_held_while_stopped_says_nothing_is_being_captured(self):
        self.assertEqual(tl.owner_label("LEVEL 1/3", "gen", True, False),
                         "LEVEL 1/3 REC-STOP")
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest tests.test_techno_lib.TestHandback tests.test_techno_lib.TestOwnerLabel -v
```

Expected: FAIL, `AttributeError: ... has no attribute 'hands_back'`

- [ ] **Step 3: Implement them**

In `techno_lib.py`, after `candidate_notes`:

```python
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
```

- [ ] **Step 4: Run the tests and watch them pass**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest discover -s tests -q
```

Expected: OK, 248 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(sp2): handback rules per channel kind and the ownership label

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Live pad play

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `techno_lib.pad_note`
- Produces: `self.held` (dict `pad -> (note, midi_chan, channel, start_clock, velocity)`), `self._pad_note(channel, pad)`, `self._pad_down(pad, velocity)`, `self._pad_up(pad)`, `self._release_all()`, `self._play_clock(channel)`

This task adds live play only. Recording arrives in Task 7.

- [ ] **Step 1: Add the state and the note colour**

In the constants block, next to `COLOR_PLAYHEAD`:

```python
# Amber marks a step a human played in. The daemon uses it for its own
# selected step; this driver used it nowhere.
COLOR_PLAYER = 0xFF8800
```

In `__init__`, next to `self.writer_token`:

```python
        # Pads currently held down: pad -> (note, midi_chan, channel,
        # start_clock, velocity). A held note that never gets its note-off is
        # the worst failure this instrument can produce, so every path that
        # changes what the pads mean goes through _release_all().
        self.held = {}
        self.rec_down = False
        self.owner = {i: "gen" for i in range(len(tlib.CHANNELS))}
        self.notes = {i: {} for i in range(len(tlib.CHANNELS))}
```

- [ ] **Step 2: Add the play helpers**

Next to `_preview`:

```python
    def _pad_note(self, channel, pad):
        """The note a pad plays on this channel.

        A drum channel is one sound: all sixteen pads trigger it, differing
        only in velocity and timing. Playing the kit's other notes here would
        mean hearing Clap while recording Kick, because a recorded hit stores
        the channel's own note - what you play would not be what you get."""

        if self.channel_kind(channel) != "voice":
            return self._group_note(channel)
        return tlib.pad_note(pad, self.globals["root"], self.globals["scale"],
                             self.state[channel]["octave"])

    def _play_clock(self, channel):
        """The sequence's play position in clocks, or None when stopped.

        None is not an error: it is the answer to "where would a strike land?"
        on a stopped sequence, and the recorder treats it as "capture nothing"."""

        if self._play_state(channel) == zynseq_lib.SEQ_STOPPED:
            return None
        pos = self.libseq.getPlayPosition(self.zynseq.bank, channel)
        return None if pos < 0 else pos

    def _pad_down(self, pad, velocity):
        """A pad struck outside STEP mode. Sounds immediately; the capture
        happens on release, when the hold length is known."""

        channel = self.group
        note = self._pad_note(channel, pad)
        midi_chan = tlib.CHANNELS[channel][5]
        # duration 0 means no auto note-off (zynseq.cpp:1742) - this note is
        # ours to end, unlike _preview's fire-and-forget audition.
        self.libseq.playNote(note, max(1, min(127, velocity)), midi_chan, 0)
        self.held[pad] = (note, midi_chan, channel, self._play_clock(channel),
                          velocity)

    def _pad_up(self, pad):
        """Release. Ends the note; Task 7 hangs the capture off the same edge."""

        entry = self.held.pop(pad, None)
        if entry is None:
            return
        note, midi_chan, _, _, _ = entry
        # A NoteOn at velocity 0 is a note-off.
        self.libseq.playNote(note, 0, midi_chan, 0)

    def _release_all(self):
        """End every held note, unconditionally.

        Called wherever the meaning of the pads changes underneath a finger:
        group change, mode change, transport stop, ownership change, end() and
        light_off(). A stuck pad drone is the silent channel's twin and it is
        louder."""

        for pad in list(self.held):
            self._pad_up(pad)
```

- [ ] **Step 3: Route pad events by mode**

Replace the NoteOn branch at the top of `_midi_event` with:

```python
        if evtype in (0x8, 0x9):                 # NoteOff and NoteOn
            step = ev[1] - GROUP_NOTE_BASE[self.group]
            if not 0 <= step < 16:
                return False
            if evtype == 0x8 or ev[2] == 0:
                # A release. In STEP mode nothing is ever held, so the pop
                # inside _pad_up finds nothing and this is a no-op.
                self._pad_up(step)
                return True
            if self.mode == "STEP":
                # The step editor stays bound to NoteOn only, so dropping the
                # note-off filter cannot make it toggle twice per strike.
                if self.erase_down:
                    self._erase_step(step)
                else:
                    self._toggle_step(step, ev[2] & 0x7F)
                return True
            self._pad_down(step, ev[2] & 0x7F)
            return True
```

- [ ] **Step 4: Release held notes wherever the pads change meaning**

Add `self._release_all()` as the **first** line of `_select_group`, as the
first line of `_set_mode`, in `_toggle_transport` on the branch that stops
playback, and in both `end()` and `light_off()`.

- [ ] **Step 5: Verify it compiles and the suite is still green**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo COMPILED
python3 -m unittest discover -s tests -q
```

Expected: `COMPILED`, then OK, 248 tests.

- [ ] **Step 6: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(sp2): pads play live outside STEP mode

Handles pad NoteOff for the first time; every path that changes what a
pad means force-releases held notes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: REC and capture

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `techno_lib.record_step`, `techno_lib.record_duration`, `self.held`, `self._play_clock`
- Produces: `CC_REC`, `self._capture(channel, note, velocity, start, end)`, `self._claim(channel)`

- [ ] **Step 1: Add the REC constant**

Next to `CC_RESTART`, using **the CC measured in Task 1** (the daemon's source
says 3; if G5 measured otherwise, G5 wins):

```python
CC_REC = 3               # MEASURED at gate G5, 2026-08-12. Both edges emitted.
```

- [ ] **Step 2: Handle the button**

In `_midi_event`, in the state-carrying block beside `CC_ERASE`:

```python
            if cc_num == CC_REC:
                # Held, and it overdubs: release ends the take. Held notes are
                # NOT released here - letting go of REC stops capturing, it
                # does not stop the instrument sounding.
                self.rec_down = down
                with self.lock:
                    self._render_display()
                return True
```

- [ ] **Step 3: Capture on release**

Extend `_pad_up` (Task 6) so the release edge captures:

```python
    def _pad_up(self, pad):
        entry = self.held.pop(pad, None)
        if entry is None:
            return
        note, midi_chan, channel, start, velocity = entry
        self.libseq.playNote(note, 0, midi_chan, 0)
        if self.rec_down:
            self._capture(channel, note, velocity, start, self._play_clock(channel))
```

- [ ] **Step 4: Write the capture and the claim**

Next to `_pad_up`:

```python
    def _capture(self, channel, note, velocity, start, end):
        """Write a played note into the pattern, quantised to the nearest step
        with its held length.

        Captured on release rather than on press because the length is not
        known until then. Nothing is captured on a stopped sequence: with no
        playhead there is no step, and the display says REC-STOP so the player
        is not left guessing."""

        if start is None:
            return
        cps = self.cps[channel]
        if cps <= 0:
            return
        self._select_pattern(channel)
        steps = self.libseq.getSteps()
        if steps <= 0:
            return
        step = tlib.record_step(start, cps, steps)
        length = steps * cps
        # Modulo handles a hold that crossed the loop point, where end < start.
        held = ((end - start) % length) if (end is not None and length) else cps
        duration = tlib.record_duration(held or cps, cps, step, steps)
        # Overdub replaces rather than stacks: a second strike on the same step
        # and note updates its velocity and length.
        if self.libseq.getNoteVelocity(step, note):
            self.libseq.removeNote(step, note)
        vel = max(1, min(127, velocity))
        self.libseq.addNote(step, note, vel, duration, 0.0)
        self.libseq.updateSequenceInfo()
        self.notes[channel][step] = (note, vel, duration)
        self._claim(channel)
        self._render_pads()

    def _claim(self, channel):
        """The first captured note makes the channel the player's.

        The owner flag is what enforces; forcing a voice to LOCK is what makes
        it visible on the surface."""

        if self.owner[channel] == "player":
            return
        self.owner[channel] = "player"
        if self.channel_kind(channel) == "voice":
            self.apply(channel, "random", 0)
```

`_capture` is reached from `_pad_up`, which runs inside `_midi_event` under
`self.lock` — it must not take the lock again.

- [ ] **Step 5: Persist ownership**

In `get_state`, alongside the per-channel fields, add:

```python
                    "owner": self.owner[i],
```

In `set_state`, where the per-channel fields are restored:

```python
            self.owner[i] = chan_state.get("owner", "gen")
```

Only `owner` is persisted. The notes themselves live in the pattern and
therefore in the `.zss`; the map is rebuilt in Task 9.

- [ ] **Step 6: Verify**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo COMPILED
python3 -m unittest discover -s tests -q
```

Expected: `COMPILED`, then OK, 248 tests.

- [ ] **Step 7: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(sp2): REC held captures played notes into the pattern

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Ownership enforcement and handback

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `techno_lib.hands_back`, `self.owner`
- Produces: `self._handback(channel)`

- [ ] **Step 1: Stop the generator writing a player-owned voice**

At the top of `_write_voice_pattern`, before the existing `writer_token`
check:

```python
        if self.owner[channel] == "player":
            # The token is the mutex between threads and clears itself after
            # every write, so it cannot carry an ownership that has to survive
            # a snapshot. This flag can.
            return
```

- [ ] **Step 2: Write the handback**

Next to `_claim`:

```python
    def _handback(self, channel):
        """Give a pattern back to its generator, which rewrites it from its own
        parameters. Destructive by design - the take is gone.

        Both routes land here: ERASE + Group, which is the deliberate "undo my
        take", and turning any knob that rewrites the pattern, which is the
        shipped law that enc 1-3 own the steps."""

        self._release_all()
        self.owner[channel] = "gen"
        self.notes[channel].clear()
        if self.channel_kind(channel) == "voice":
            self._write_voice_pattern(channel)
        else:
            self._write_pattern(channel)
```

Both writers `clear()` before rewriting, so no separate wipe is needed.

- [ ] **Step 3: Wire ERASE + Group**

In `_midi_event`, in the group-button branch, replace the `erase_down` case:

```python
                if self.erase_down:
                    if self.owner[group] == "player":
                        # On a player-owned channel this is an undo, not a
                        # silencing: clear the take and let the machine refill.
                        self._handback(group)
                    else:
                        self._silence_channel(group)
                    return True
```

- [ ] **Step 4: Wire the drum content knobs**

At the top of `_encoder`, after `group = self.group`:

```python
        if self.owner[group] == "player" and tlib.hands_back("drum", verb):
            self._handback(group)
```

- [ ] **Step 5: Wire the voice content knobs**

In `_verb`, inside the `verb == "length" and voice` branch and the
`verb == "div" and voice` branch, as the first statement of each `if delta:`
body:

```python
                if self.owner[channel] == "player":
                    self._handback(channel)
```

And in the generic verb path, immediately after the clamped new value is
computed and before `self.apply(...)`:

```python
        new_value = min(hi, max(lo, current + delta))
        if self.owner[channel] == "player" and tlib.hands_back(
                self.channel_kind(channel), verb, new_value):
            self._handback(channel)
        self.apply(channel, verb, new_value)
```

This is the RANDOM case: only a move **off** LOCK hands back, so turning
RANDOM down to 0 — which is what `_claim` itself does — cannot undo the
recording it just made.

- [ ] **Step 6: Verify**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo COMPILED
python3 -m unittest discover -s tests -q
```

Expected: `COMPILED`, then OK, 248 tests.

- [ ] **Step 7: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(sp2): ownership enforcement and both handback routes

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Rebuild the note map from the pattern

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `techno_lib.candidate_notes`, `techno_lib.pad_notes`
- Produces: `self._rebuild_notes(channel)`, `self._note_duration(step, note)`, `self._rebuild_due`

- [ ] **Step 1: Add the deferral set**

In `__init__`, beside `self.notes`:

```python
        # Channels whose note map needs rebuilding. Drained by the poll
        # thread: the scan takes the lock and must never run on the MIDI
        # thread, for the same reason _commit_kit and _commit_preset do not.
        self._rebuild_due = set()
```

- [ ] **Step 2: Add the guarded duration read**

Next to `_step_note`:

```python
    def _note_duration(self, step, note):
        """A stored note's length, if the installed libzynseq can tell us.

        The Pi's build is older than this checkout and has already been caught
        missing getNoteAtIndex(). Audited at gate G5; guarded anyway, because
        the failure mode of assuming is a driver that will not load at all."""

        getter = getattr(self.libseq, "getNoteDuration", None)
        if getter is None:
            return 1.0
        try:
            return float(getter(step, note))
        except Exception:
            return 1.0
```

- [ ] **Step 3: Write the rebuild**

```python
    def _rebuild_notes(self, channel):
        """Reconstruct which steps a human played, by reading the pattern.

        The map is a cache, never the truth. The notes live in the pattern and
        therefore in the .zss, and this is the CHANCE/SWING lesson applied
        before it bites: any mirrored zynseq state is read back on load, never
        assumed.

        Cheap because the candidate set is small - one note on a drum, the
        keyboard plus the generated line on a voice. Not 128 per step.

        Known and accepted limit: a played note that lands on the same step
        with the same pitch the generator would have written there is
        indistinguishable, and shows in the group colour rather than amber."""

        kind = self.channel_kind(channel)
        with self.lock:
            self._select_pattern(channel)
            steps = self.libseq.getSteps()
            if steps <= 0:
                self.notes[channel] = {}
                return
            generated = self._step_notes(channel, steps)
            if kind == "voice":
                cands = tlib.candidate_notes(
                    kind, self._group_note(channel),
                    pads=tlib.pad_notes(self.globals["root"],
                                        self.globals["scale"],
                                        self.state[channel]["octave"]),
                    line=generated)
            else:
                cands = tlib.candidate_notes(kind, self._group_note(channel))
            out = {}
            for step in range(steps):
                for note in cands:
                    if note == generated[step]:
                        continue
                    vel = self.libseq.getNoteVelocity(step, note)
                    if vel:
                        out[step] = (note, vel,
                                     self._note_duration(step, note))
                        break
            self.notes[channel] = out
```

- [ ] **Step 4: Queue rebuilds and drain them on the poll thread**

In the `SS_LOAD_SNAPSHOT` handler, after `_derive_params` runs for every
channel:

```python
        self._rebuild_due.update(range(len(tlib.CHANNELS)))
```

In the playhead poll loop, before the playhead work:

```python
            while self._rebuild_due:
                self._rebuild_notes(self._rebuild_due.pop())
```

- [ ] **Step 5: Verify**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo COMPILED
python3 -m unittest discover -s tests -q
```

Expected: `COMPILED`, then OK, 248 tests.

- [ ] **Step 6: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(sp2): rebuild the player note map from the pattern on load

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Amber steps and the ownership label

**Files:**
- Modify: `~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `COLOR_PLAYER`, `self.notes`, `self.owner`, `techno_lib.owner_label`
- Produces: nothing further

- [ ] **Step 1: Colour played-in steps**

Replace `_step_state`:

```python
    def _step_state(self, step, group_color):
        """LED state a step shows when the playhead is not on it.

        A played-in step is amber. This overrides _toggle_step's standing "no
        third LED colour to explain" comment, which predates per-step override
        state that now survives a snapshot: the handback is destructive, so a
        player-owned channel that looks like a generated one invites nudging
        HITS and silently eats the take."""

        if self.step_on[step] is None:          # beyond the pattern's length
            return (group_color, 0.0)
        if not self.step_on[step]:
            return (group_color, BRIGHT_STEP_OFF)
        if step in self.notes[self.group]:
            return (COLOR_PLAYER, BRIGHT_STEP_ON)
        return (group_color, BRIGHT_STEP_ON)
```

- [ ] **Step 2: Put ownership and REC on the page indicator**

In `_render_display`, where the page label is built, wrap it:

```python
        label = tlib.owner_label(
            label, self.owner[self.group], self.rec_down,
            self._play_state(self.group) != zynseq_lib.SEQ_STOPPED)
```

The tab row is not touched: a dashed tab means "this channel is not sounding",
and that meaning is not diluted with a second one.

- [ ] **Step 3: Verify**

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo COMPILED
python3 -m unittest discover -s tests -q
```

Expected: `COMPILED`, then OK, 248 tests.

- [ ] **Step 4: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(sp2): amber played-in steps and the ownership page label

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Deploy and hardware test

**This task needs the owner at the Maschine.**

**Files:**
- Create: `~/zynth-docs/docs/superpowers/techno-machine/2026-08-12-sp2-test-findings.md`

**Interfaces:**
- Consumes: everything above
- Produces: a findings record and a green or red verdict

- [ ] **Step 1: Deploy by file copy**

```bash
scp ~/zynth/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py \
    ~/zynth/zynthian-ui/zyngine/ctrldev/techno_lib.py \
    root@192.168.2.123:/zynthian/zynthian-ui/zyngine/ctrldev/
```

Never `git reset --hard` on the Pi: the Maschine files are untracked drop-ins
on upstream branch `oram-2601.1`.

- [ ] **Step 2: Restart in the right order — daemon first, UI second**

```bash
ssh root@192.168.2.123 'systemctl restart maschine-mk2 && sleep 3 && systemctl restart zynthian'
```

Restarting `maschine-mk2` alone makes a2j re-register the Pads port onto a new
zmip slot while the ctrldev driver stays bound to the dead one — the rig goes
silent with no error.

- [ ] **Step 3: Confirm exactly one route**

```bash
ssh root@192.168.2.123 'jack_lsp -c | grep -A3 "Pads MIDI"'
```

Expected: exactly **one** `devN_in`. More than one is a stale manual
`jack_connect` and causes phantom notes.

- [ ] **Step 4: Stuck note — the worst failure, tested first**

Load snapshot `016-techno_maschine`. In CONTROL mode, hold a pad and, while
still holding it: change group, change mode, press Play to stop.

**Expected: silence after each. Any drone that survives is a stop-the-line
defect** — report it and go no further.

- [ ] **Step 5: Live play on both kinds**

Select a drum channel, strike several pads: every pad sounds the same drum,
harder strikes louder. Select a voice, strike pads left to right: pitch rises
through the scale.

- [ ] **Step 6: Record on a drum**

Start transport. Hold REC, tap four hits, release REC. Expected: the four hits
loop, the pads show them **amber**, and the page label reads `PLAY` once REC is
released.

- [ ] **Step 7: Record on a voice, including a long note**

Hold REC and hold one pad for about four steps. Expected: the note sustains
audibly on playback, and it does **not** hang at the loop point. The channel's
RANDOM column reads `LOCK`.

- [ ] **Step 8: REC while stopped**

Stop transport, hold REC, strike pads. Expected: pads sound, nothing is
captured, and the page label reads `REC-STOP`.

- [ ] **Step 9: Both handback routes**

Hold ERASE and press the recorded channel's Group button. Expected: the take
goes, the euclid or Turing pattern comes back, pads return to the group colour.
Record another take, then turn HITS one detent. Expected: the same, without the
ERASE.

- [ ] **Step 10: Snapshot round trip**

Save a snapshot with a take in it. Load another, then load it back. Expected:
the take is there, the played-in steps are **amber again**, and the page label
reads `PLAY`. Amber returning is the proof the map was rebuilt and not assumed.

- [ ] **Step 11: Write up and commit the findings**

Record every check as pass or fail with what was observed, in
`2026-08-12-sp2-test-findings.md`. Commit it to `zynth-docs`.

- [ ] **Step 12: Update the tracking files**

Mark SP2 done in `MD/todo.md` and update the RESUME HERE block in `CLAUDE.md`
with what shipped, what was measured at G5, and any defect found. Commit and
push all three repos.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §2 revision — drum pads play the channel note | 6 (`_pad_note`) |
| §3 gesture table | 6 (mode routing), 7 (REC), 8 (both handbacks) |
| §3 per-kind handback set | 5 (`HANDBACK_VERBS`), 8 (three wiring points) |
| §4.1 playNote mechanism, NoteOff handling | 6 |
| §4.2 what a pad plays | 4 (`pad_note`), 6 (`_pad_note`) |
| §4.3 stuck notes | 6 (`_release_all`), 11 step 4 |
| §5 not capturing while stopped | 7 (`start is None`), 5 (`REC-STOP`), 11 step 8 |
| §5 nearest-step quantise | 2 |
| §5 overdub, replace not stack | 7 |
| §5 duration and clamp | 3, 7 |
| §5 claim and LOCK | 7 (`_claim`) |
| §6.1 owner flag, not writer_token | 7 (persist), 8 (`_write_voice_pattern` guard) |
| §6.2 note map, rebuilt not trusted | 9 |
| §6.3 amber steps, page label, tabs untouched | 10 |
| §7 gate G5 | 1 |
| §8 unit tests | 2, 3, 4, 5 |
| §8 hardware checks | 11 |
| §9 R1–R4 | 6 (R1), 6 step 3 (R2), 9 step 2 (R3), 9 step 1 (R4) |

No gaps.

**Placeholder scan:** none — every code step carries its actual code, and the
one value that cannot be known before execution (the REC CC) is produced by
Task 1 and consumed by Task 7, with the source's claim and the rule for
resolving a conflict both stated.

**Type consistency:** `record_step` and `record_duration` both take
`(…, cps, step(s), …)` in that order and are called that way in `_capture`.
`candidate_notes` is defined with keyword parameters `pads`/`line` in Task 4
and called with those keywords in Task 9. `owner` is the string `"gen"` or
`"player"` in `__init__`, `get_state`, `set_state`, `_claim`, `_handback`,
`hands_back` and `owner_label`. `self.notes[channel]` is
`step -> (note, velocity, duration)` in `_capture`, `_rebuild_notes` and
`_step_state`.
