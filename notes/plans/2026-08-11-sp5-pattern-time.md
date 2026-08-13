# SP5 Pattern Time Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the techno machine four-bar patterns and notes that can hold for two bars, so a pad sounds like a pad instead of a stab.

**Architecture:** Three small changes, all inside existing structures. A sixth entry appended to the division table gives quarter-note steps (16 steps × 1 beat = 4 bars). The GATE verb's range rises from 100 to 800, which lifts note duration from one step to eight — the one-step cap was never a library limit, only this driver's own range entry. The voice write path clamps a note's duration to the steps remaining in its pattern, conservatively, until hardware proves a note may safely cross the loop point.

**Tech Stack:** Python 3.11+ (Zynthian UI, `zyngine/ctrldev/`), `unittest`. No Rust, no daemon change, no new dependency.

## Global Constraints

- **Spec:** `~/zynth-docs/docs/superpowers/specs/2026-08-11-sp5-pattern-time-design.md`. Read it before Task 1.
- **Test command:** `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`. Baseline before any change: **187 tests, OK**.
- **The `1/4` division is APPENDED to `DIVISIONS`, never inserted.** Snapshots persist the division as an **index** into that tuple. Inserting in musical order silently re-points every saved pattern at a different division, with no error message. This is the single most important constraint in this plan.
- **Pattern length is quantised to whole beats and always will be.** `getLength() = beats * PPQN`, and there is no `setSequenceLength` in the installed C API. Step counts are `steps_per_beat × beats`, both integers.
- **The driver cannot be imported on WSL.** `zynthian_ctrldev_maschine_mk2.py` imports `zynlibs.zynseq`, which exists only on the Pi. Driver changes are verified with `python3 -m py_compile` plus hardware. **Push logic into `techno_lib.py` / `maschine_mk2_lib.py`, where it is unit tested.**
- **Every zynseq call the driver makes must hold `self.lock`.** `libzynseq` is not thread-safe and the driver reaches it from three threads. Without the lock the whole Zynthian UI died with SIGSEGV, exit 139.
- **Deployment to the Pi is a file copy, never a git operation.** The Pi runs upstream branch `oram-2601.1` and the three Maschine files are untracked drop-ins. Backups live at `/root/ctrldev-backup-20260811/`.
- **Commit after every task.** Repo: `~/zynth/zynthian-ui`, branch `vangelis`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `zyngine/ctrldev/maschine_mk2_lib.py` | The division table and `step_count` | Modify — append one row |
| `zyngine/ctrldev/techno_lib.py` | Division labels, the GATE column, duration clamping | Modify — one label, one fraction, one new pure function |
| `zyngine/ctrldev/tests/test_maschine_mk2_lib.py` | Division tests | Modify — existing tests assert the old table and must be updated |
| `zyngine/ctrldev/tests/test_techno_lib.py` | Label, column and clamp tests | Modify |
| `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py` | GATE range; the write path that applies the clamp | Modify — two small edits |

No new file. No file grows meaningfully. `techno_lib.py` gains one pure function of four lines.

---

### Task 1: The `1/4` division

**Files:**
- Modify: `zyngine/ctrldev/maschine_mk2_lib.py:18-25` (`DIVISIONS`)
- Modify: `zyngine/ctrldev/techno_lib.py:249` (`DIVISION_LABELS`)
- Test: `zyngine/ctrldev/tests/test_maschine_mk2_lib.py`, `zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `maschine_mk2_lib.DIVISIONS` gains index **5**, the tuple `("1/4", 1, 16)`. `maschine_mk2_lib.step_count(5)` returns `16`. `techno_lib.DIVISION_LABELS` gains `"1/4"` at index 5.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_maschine_mk2_lib.py`:

```python
class TestQuarterNoteDivision(unittest.TestCase):

    def test_quarter_division_is_appended_last(self):
        # Appended, never inserted: snapshots persist the division as an INDEX
        # into this tuple, so inserting in musical order would silently
        # re-point every saved pattern at a different division.
        self.assertEqual(lib.DIVISIONS[5], ("1/4", 1, 16))

    def test_the_first_five_indices_are_unchanged(self):
        self.assertEqual([d[0] for d in lib.DIVISIONS[:5]],
                         ["1/32", "1/16", "1/8", "1/16T", "1/8T"])

    def test_quarter_division_has_16_steps(self):
        self.assertEqual(lib.step_count(5), 16)

    def test_quarter_division_steps_are_one_beat_each(self):
        # steps_per_beat 1 means one step IS one beat. 16 of them is 4 bars,
        # and it is the slowest step this API can express: steps_per_beat is
        # an integer >= 1.
        self.assertEqual(lib.DIVISIONS[5][1], 1)
        self.assertEqual(lib.DIVISIONS[5][2], 16)
```

Append to `tests/test_techno_lib.py`:

```python
class TestQuarterDivisionLabel(unittest.TestCase):

    def test_label_table_gains_the_quarter_division_last(self):
        self.assertEqual(tl.DIVISION_LABELS[5], "1/4")

    def test_label_table_matches_the_division_table_in_length(self):
        import maschine_mk2_lib as mlib
        self.assertEqual(len(tl.DIVISION_LABELS),
                         len(mlib.maschine_mk2_lib.DIVISIONS))

    def test_the_first_five_labels_are_unchanged(self):
        self.assertEqual(list(tl.DIVISION_LABELS[:5]),
                         ["1/32", "1/16", "1/8", "1/16T", "1/8T"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: FAIL — `IndexError: tuple index out of range` on `DIVISIONS[5]`.

- [ ] **Step 3: Write the implementation**

In `maschine_mk2_lib.py`, replace the `DIVISIONS` tuple with:

```python
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
```

In `techno_lib.py`, replace the `DIVISION_LABELS` line with:

```python
    # Mirrors maschine_mk2_lib.DIVISIONS and is append-only for the same
    # reason: a snapshot stores the index, not the label.
    DIVISION_LABELS = ("1/32", "1/16", "1/8", "1/16T", "1/8T", "1/4")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: PASS, **187 + 7 = 194 tests, OK**.

**One existing test will fail, and it is meant to.** `test_five_divisions_in_order` in `tests/test_maschine_mk2_lib.py:10` asserts the label list is exactly the five old entries. It is a correct assertion about a table that has changed. Update it:

```python
    def test_divisions_in_order(self):
        labels = [d[0] for d in lib.DIVISIONS]
        self.assertEqual(labels, ["1/32", "1/16", "1/8", "1/16T", "1/8T", "1/4"])
```

Rename the method too — "five" is now wrong. `test_beats_times_spb_equals_step_count` iterates the whole table and keeps passing on its own, because `1 * 16 == 16`.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/maschine_mk2_lib.py zyngine/ctrldev/techno_lib.py \
        zyngine/ctrldev/tests/test_maschine_mk2_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(maschine): a 1/4 division - 16 quarter-note steps, four bars

Appended, never inserted: a snapshot stores the division as an index into
DIVISIONS, so inserting in musical order would silently re-point every saved
pattern at a different division.

steps_per_beat 1 is the slowest step the installed API can express, so 16
steps over 16 beats is the longest pattern reachable without paging the pads.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: GATE spans multiple steps

**Files:**
- Modify: `zyngine/ctrldev/techno_lib.py:466` (the `GATE` column in `columns`)
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py:1543` (`VERB_RANGES["gate"]`)
- Test: `zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `techno_lib.GATE_MAX = 800`, an int. The `GATE` column's bar fraction becomes `gate / GATE_MAX`. `VERB_RANGES["gate"]` becomes `(5, 800, None)`.

Duration is measured in **steps** and is computed as `gate / 100.0`, so 800 is
eight steps. At the new `1/4` division that is a two-bar note.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_techno_lib.py`:

```python
class TestGateRange(unittest.TestCase):

    def test_gate_max_is_eight_steps_worth(self):
        # duration = gate / 100, measured in steps. 800 is eight steps, which
        # at the 1/4 division is a two-bar note.
        self.assertEqual(tl.GATE_MAX, 800)

    def test_gate_column_renders_the_new_maximum(self):
        state = _voice_view(gate=800)
        cols = tl.columns(tl.PAGE_RINGS[("STEP", "voice")][0], "voice", state)
        gate_col = next(c for c in cols if c["name"] == "GATE")
        self.assertEqual(gate_col["value"], "0800")
        self.assertAlmostEqual(gate_col["frac"], 1.0)

    def test_gate_column_bar_is_scaled_to_the_new_maximum(self):
        # A gate of 100 used to fill the bar. It is now one eighth of it, and
        # that is the point: the bar shows note length, not knob travel.
        state = _voice_view(gate=100)
        cols = tl.columns(tl.PAGE_RINGS[("STEP", "voice")][0], "voice", state)
        gate_col = next(c for c in cols if c["name"] == "GATE")
        self.assertAlmostEqual(gate_col["frac"], 0.125)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: FAIL — `AttributeError: type object 'techno_lib' has no attribute 'GATE_MAX'`.

- [ ] **Step 3: Write the implementation**

In `techno_lib.py`, add next to the other module constants (beside `PORT_LABEL_CHARS` is fine):

```python
    # Note duration is gate/100, measured in STEPS. The old cap of 100 meant a
    # note could never outlast one step, so at the slowest division no note in
    # this instrument could exceed an eighth note - which is why pads played
    # stabs. The library never had this limit; only this driver's range did.
    GATE_MAX = 800
```

Replace the `GATE` column line:

```python
            c("GATE", n(state["gate"]), "uni", state["gate"] / techno_lib.GATE_MAX),
```

In `zynthian_ctrldev_maschine_mk2.py`, replace the `gate` entry in `VERB_RANGES`:

```python
        "gate": (5, tlib.GATE_MAX, None),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: PASS, **194 + 3 = 197 tests, OK**.

Then confirm the driver still compiles:

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo OK`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py \
        zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(maschine): GATE spans up to eight steps

Duration is gate/100 measured in steps, so the old cap of 100 meant no note
could outlast one step - at the slowest division, no note in this instrument
could exceed an eighth note. Probed on the Pi: libzynseq stores durations of
16 steps exactly. The cap was never a library limit, only this range entry.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Clamp a note at the loop point

**Files:**
- Modify: `zyngine/ctrldev/techno_lib.py` (new pure function, next to `gate_mask`)
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py:754-766` (`_write_voice_pattern`)
- Test: `zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: `techno_lib.GATE_MAX` from Task 2.
- Produces: `techno_lib.note_duration(gate, step, steps) -> float` — the duration in steps for a note starting at `step` in a pattern of `steps` steps, clamped so it never crosses the loop point. Never returns less than `0.05`.

**Why this exists, and why it is temporary:** the Pi probe proved that
`libzynseq` *stores* a duration longer than the pattern; it did not prove the
player emits the note-off after the loop wraps. A stuck pad drone is this
instrument's worst failure. The clamp makes the failure unreachable while the
question is open. It is removed, or replaced by a wrap, once hardware answers —
see the spec's §6 test order.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_techno_lib.py`:

```python
class TestNoteDuration(unittest.TestCase):

    def test_a_note_early_in_the_pattern_gets_its_full_length(self):
        self.assertAlmostEqual(tl.note_duration(800, 0, 16), 8.0)

    def test_a_note_is_clamped_to_the_steps_remaining(self):
        # Step 14 of a 16-step pattern has two steps left, so eight is not
        # available. The clamp is conservative on purpose: it makes a note
        # that outlives its pattern unreachable while the note-off behaviour
        # at the loop point is unproven.
        self.assertAlmostEqual(tl.note_duration(800, 14, 16), 2.0)

    def test_a_note_on_the_last_step_gets_one_step(self):
        self.assertAlmostEqual(tl.note_duration(800, 15, 16), 1.0)

    def test_a_short_gate_is_unaffected_by_the_clamp(self):
        self.assertAlmostEqual(tl.note_duration(50, 15, 16), 0.5)

    def test_duration_never_reaches_zero(self):
        # A zero-length note is a note that never sounds, which is silence
        # with no explanation - the failure this instrument has a law about.
        self.assertGreaterEqual(tl.note_duration(0, 15, 16), 0.05)
        self.assertGreaterEqual(tl.note_duration(5, 0, 16), 0.05)

    def test_it_matches_the_old_behaviour_for_every_legacy_gate(self):
        # Gate 5..100 on step 0 behaved as gate/100 before this change and
        # must still, or every existing pattern changes character.
        for gate in range(5, 101):
            self.assertAlmostEqual(tl.note_duration(gate, 0, 16), gate / 100.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: FAIL — `AttributeError: type object 'techno_lib' has no attribute 'note_duration'`.

- [ ] **Step 3: Write the implementation**

In `techno_lib.py`, directly below `gate_mask`:

```python
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
```

In `zynthian_ctrldev_maschine_mk2.py`, in `_write_voice_pattern`, delete the line

```python
            duration = max(0.05, st["gate"] / 100.0)
```

and change the write loop so the duration is computed per step:

```python
            velocity = max(1, min(127, int(st["velo"])))
            played = []
            with self.lock:
                self._select_pattern(channel)
                self._force_loop_mode(channel)
                self.libseq.setStepsPerBeat(lib.DIVISIONS[self.div[channel]][1])
                self.libseq.setBeatsInPattern(lib.DIVISIONS[self.div[channel]][2])
                self.libseq.clear()
                for step, note in enumerate(notes):
                    if not mask[step]:
                        continue
                    # Per step, not once per pattern: a long gate near the end
                    # of the pattern is clamped so the note cannot outlive it.
                    duration = tlib.note_duration(st["gate"], step, steps)
                    self.libseq.addNote(step, note, velocity, duration, 0.0)
                    played.append(note)
                self.libseq.updateSequenceInfo()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: PASS, **197 + 6 = 203 tests, OK**.

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo OK`
Expected: `OK`

Confirm the old duration line is gone:

Run: `grep -n 'st\["gate"\] / 100' zynthian_ctrldev_maschine_mk2.py`
Expected: prints nothing.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py \
        zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(maschine): clamp a note so it cannot outlive its pattern

The Pi probe proved libzynseq stores a duration longer than its pattern; it
did not prove the player emits the note-off after the loop wraps. A stuck pad
drone is the worst failure this instrument has, so the write path clamps to
the steps remaining until hardware answers the question.

Gate 5..100 on step 0 still resolves to exactly gate/100, so no existing
pattern changes character.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Deploy and hand over for hardware verification

**Files:**
- Modify: none. This task ships what Tasks 1-3 built and writes the hardware checklist.
- Create: `~/zynth-docs/docs/superpowers/techno-machine/2026-08-11-sp5-hardware-checks.md`

**Interfaces:**
- Consumes: everything from Tasks 1-3.
- Produces: the deployed files on the Pi, and a checklist the owner runs at the panel.

- [ ] **Step 1: Run the full suite one more time**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: **203 tests, OK**

- [ ] **Step 2: Deploy by copying files, never with git**

The Pi runs upstream branch `oram-2601.1` and the three Maschine files are
untracked drop-ins there. A `git reset --hard` or a bundle checkout on the Pi
destroys the working driver.

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
ssh root@192.168.2.123 'mkdir -p /root/ctrldev-backup-sp5 && cd /zynthian/zynthian-ui/zyngine/ctrldev && cp techno_lib.py maschine_mk2_lib.py zynthian_ctrldev_maschine_mk2.py /root/ctrldev-backup-sp5/'
scp techno_lib.py maschine_mk2_lib.py zynthian_ctrldev_maschine_mk2.py \
    root@192.168.2.123:/zynthian/zynthian-ui/zyngine/ctrldev/
ssh root@192.168.2.123 'cd /zynthian/zynthian-ui/zyngine/ctrldev && python3 -m py_compile techno_lib.py maschine_mk2_lib.py zynthian_ctrldev_maschine_mk2.py && echo PI_COMPILE_OK'
```

- [ ] **Step 3: Restart the UI and confirm the driver loads**

The daemon is untouched by this plan, so only the UI restarts. (If the daemon
ever *is* restarted, the order is daemon first, UI second, or the driver stays
bound to a dead zmip slot and the rig goes silent with no error.)

```bash
ssh root@192.168.2.123 'systemctl restart zynthian'
sleep 45
ssh root@192.168.2.123 'journalctl --since "-2min" --no-pager | grep -cE "Loaded ctrldev driver .Maschine"'
ssh root@192.168.2.123 'journalctl --since "-2min" --no-pager | grep -ciE "traceback"'
```

Expected: exactly `1` load event and `0` tracebacks. Then wait a further 60
seconds and re-check the load count is still `1` — a crash-loop reloads every
~14 seconds.

- [ ] **Step 4: Write the hardware checklist**

Create `~/zynth-docs/docs/superpowers/techno-machine/2026-08-11-sp5-hardware-checks.md` containing, in this order:

1. **The stuck-note gate, first, before anything enjoyable.** Select a voice,
   step DIVIDE round to `1/4`, set GATE to maximum, and let it loop for one
   minute. Listen for a note that never stops. **Expected: no stuck note** —
   the clamp is in place. Record the answer.
2. **Remove-the-clamp evidence.** With GATE at maximum, confirm a note on the
   *last* step is audibly shorter than the others. That is the clamp working,
   and it is also the cost we want to remove later.
3. **The Turing interaction (spec risk T4).** Same voice, RANDOM above 0, GATE
   at maximum, let it mutate for one minute. `_write_voice_pattern` calls
   `clear()` every bar; listen for a stranded note.
4. **Swing at `spb=1` (spec risk T3).** On `1/4`, move SWING across its range
   and confirm the pattern still plays in time.
5. **The musical check.** A pad on `1/4` with a long gate over four bars.
   Confirm it sounds like a pad.
6. **Snapshot round trip.** Save, reload, confirm the division is still `1/4`
   and the gate still what you set — this is the append-only guarantee under
   test.

- [ ] **Step 5: Commit and push**

```bash
cd ~/zynth-docs
git add docs/superpowers/techno-machine/2026-08-11-sp5-hardware-checks.md
git commit -m "docs: SP5 hardware checks, stuck-note gate first

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push origin master

cd ~/zynth/zynthian-ui
git push origin vangelis
```

---

## Post-plan verification

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest discover -s tests -q            # expect 203 tests, OK
python3 -m py_compile zynthian_ctrldev_maschine_mk2.py
grep -n 'st\["gate"\] / 100' zynthian_ctrldev_maschine_mk2.py   # expect nothing
grep -n '"1/4"' maschine_mk2_lib.py techno_lib.py               # expect one hit each, both last
```

## What this plan deliberately does not do

- **32-step patterns and pad paging.** Eight bars needs 32 steps, which do not
  fit 16 pads. Deferred; `1/4` covers four bars without touching any pad code.
- **Anything for drums.** Their samples are one-shots and gain nothing from a
  longer note-off. `_write_pattern` keeps its fixed `1.0`.
- **Removing the clamp.** That needs the hardware answer from Task 4's
  checklist. If crossing the loop point proves safe, removing it is a
  one-line follow-up with its own test.
- **SP2.** Live pad play and recording is the next spec, and it is built on top
  of this. Its agreed decisions are recorded in §8 of the SP5 spec.
