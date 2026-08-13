# SP5 — Pattern Time: quarter-note steps and multi-step notes

**Date:** 2026-08-11
**Status:** design agreed, not implemented
**Extends:** `2026-08-11-techno-machine-pass-two-design.md`
**Build order:** **before SP2.** Recording a pad performance into eighth-note
stabs is not worth building, so this comes first.

---

## 1. The problem, in the owner's words

> "For synths with long release like pads, a 16-step maximum sequence is too
> short — even in the slowest division. Especially for pads I need longer
> patterns with longer notes. I will mostly never use 1/32 for pads. Even for
> other synths this is extremely fast and I don't have real slow options."

Two separate limits are hiding behind one complaint, and the second is the one
that actually prevents pads.

### Limit 1 — the pattern spans at most two bars

Every division yields 16 steps (12 for triplets). What differs is the time they
cover:

| Division | `steps_per_beat` | beats | steps | span |
|---|---|---|---|---|
| 1/32 | 8 | 2 | 16 | ½ bar |
| 1/16 | 4 | 4 | 16 | 1 bar |
| **1/8** | 2 | 8 | 16 | **2 bars — today's maximum** |
| 1/16T | 6 | 2 | 12 | ½ bar |
| 1/8T | 3 | 4 | 12 | 1 bar |

### Limit 2 — a note can never be longer than one step

`_write_voice_pattern` computes `duration = max(0.05, gate / 100.0)` and
`VERB_RANGES["gate"]` is `(5, 100)`. Duration is measured in **steps**, so the
cap is exactly **one step**. At the slowest division a step is an eighth note,
so **no note in this instrument can currently exceed an eighth note**. A pad
plays stabs, whatever the pattern length.

### The hard constraint both changes live inside

Pattern length is quantised to whole beats and always will be:
`getLength() = beats * PPQN`, and there is no `setSequenceLength` in the
installed C API. Reachable step counts are `steps_per_beat × beats` with both
integers. `steps_per_beat ≥ 1` therefore makes **a quarter note the longest
possible step**. Anything slower needs more steps, not slower steps.

---

## 2. Probe results — measured 2026-08-11

Run headless on the Pi in its own process, so it loaded its own `libzynseq`
instance and could not touch the running rig. Script: `/root/probe_gate.py`.

**Quarter-note steps work.**

| `spb` | beats | steps | clocks/step |
|---|---|---|---|
| **1** | **16** | **16** | **96** |
| 1 | 8 | 8 | 96 |
| 2 | 8 | 16 | 48 |
| 4 | 4 | 16 | 24 |

PPQN is 96, so at `spb=1` one step is exactly one beat. Sixteen of them is
**four bars**.

**Long notes are fully supported.** Durations of 0.5, 1, 2, 4, 8 and **16**
steps were each stored back exactly. Nothing clamps them. **The one-step cap
was never a library limit — it is this driver's own `VERB_RANGES` entry.**

**Overlapping notes coexist.** Two notes of different pitch, each 8 steps long,
starting 4 steps apart, both persisted with their velocities. Pads can hold
chords and legato.

**Notes past the pattern end are accepted** — 32 steps of duration on a
16-step pattern stored as `32.00`, no error. **This proves storage only.** See
§5.

---

## 3. Design

### Change 1 — a `1/4` division

Append to `maschine_mk2_lib.DIVISIONS` and to `techno_lib.DIVISION_LABELS`:

```python
("1/4", 1, 16)      # 16 quarter-note steps = 4 bars
```

**Appended, never inserted.** Snapshots persist the division as an **index**
into this tuple. Inserting `1/4` in musical order would silently re-point every
saved pattern at a different division — a data corruption with no error
message. Musical order is not worth that.

(An earlier draft of this section claimed the division knob wraps, so ordering
cost nothing. It does not wrap — `_verb` clamps the division index with
`min(len(DIVISIONS) - 1, max(0, ...))` at both call sites. Caught by the Task 1
review before the false claim reached a code comment.)

The 8-step `spb=1, beats=8` variant the probe found is **not** added. It was
considered and declined: it is the same resolution over half the time, and one
more entry on a knob the player steps through by feel.

### Change 2 — GATE spans multiple steps

| | Now | After |
|---|---|---|
| `VERB_RANGES["gate"]` | `(5, 100, None)` | `(5, 800, None)` |
| Duration reached | 0.05 – 1 step | 0.05 – **8 steps** |
| Column bar fraction | `gate / 100` | `gate / 800` |

At the new `1/4` division, 8 steps is a **two-bar note**. Combined with the
four-bar pattern, that is a real pad.

Drums are unchanged. `_write_pattern` keeps its fixed `1.0`, because a sampled
one-shot gains nothing from a longer note-off and every drum kit in the rig is
one-shots.

### Change 3 — clamp at the loop point, then try to earn the clamp away

The write path clamps each note's duration to the steps remaining in the
pattern:

```python
duration = min(duration, steps - step)
```

This is a **deliberately conservative first cut**, not the desired end state:
it makes a note on the last step one step long, which is exactly the pad case
we are fixing. It exists because §5's risk cannot be settled headlessly. The
clamp is removed — or replaced by a wrap — once hardware says what really
happens, and the testing plan below is written to answer that question first.

---

## 4. Surface impact

Small, by design.

- **DIVIDE** gains a sixth setting, `1/4`. It is a segmented column already and
  renders the new label with no layout change.
- **GATE** shows up to `0800`. The column is four digits wide already.
- No new button, no new page, no new mode. The `1/4` division is reached by
  stepping DIVIDE as always.

---

## 5. Risks

| # | Risk | Handling |
|---|---|---|
| **T1** | **A note longer than its remaining pattern may hang.** The probe proved storage, not playback: whether the player still emits the note-off after the loop wraps is unknown. A stuck pad drone is the worst failure this instrument has — it is silent-channel's twin, and the rig has a law about it | Clamp first (Change 3), then test explicitly. **This is the first thing the testing plan checks** |
| T2 | A snapshot written before this restores with a division index that still means what it meant | Guaranteed by appending rather than inserting. A regression test asserts the first five indices are unchanged |
| T3 | Swing at `spb=1`. `_force_swing_div` asserts a per-pattern swing division; quarter-note steps are a case it has never seen | Check `setSwingDiv` behaviour at `spb=1` during implementation; if it misbehaves, swing is disabled for that division rather than left wrong |
| T4 | Long notes plus the Turing rewrite. At RANDOM > 0 a voice's pattern is rewritten every bar, and a rewrite calls `clear()` — a sounding long note could lose its note-off | Test with a long gate and RANDOM > 0 together. If it hangs, the rewrite must emit an all-notes-off for that channel first |

T1 and T4 are the same failure by two routes, and both are why this spec ships
with a clamp rather than without one.

---

## 6. Testing

**Pure, in `tests/test_techno_lib.py` and `tests/test_maschine_mk2_lib.py`:**

- `DIVISIONS[5]` is `("1/4", 1, 16)` and `step_count(5)` is 16
- the first five division indices are **unchanged** — the snapshot-compatibility guard
- `DIVISION_LABELS` and `DIVISIONS` stay the same length and the same order
- the GATE column renders `0800` at maximum and its bar fraction is 1.0
- duration clamping: a note at step 15 of a 16-step pattern clamps to 1, a note
  at step 0 does not clamp

**On hardware, in this order** — T1 is checked before anything enjoyable:

1. Set a voice to `1/4`, GATE to maximum, put a note on the **last** step, and
   let it loop for a minute. **Listen for a stuck note.** This is the gate.
2. With the clamp in place, confirm the note simply ends at the loop point.
3. Set RANDOM > 0 with a long gate and let it mutate for a minute (T4).
4. Then the musical check: a pad on `1/4` with a long gate, four bars, and
   confirm it sounds like a pad rather than a stab.

---

## 7. Non-goals

- **32-step patterns and pad paging.** Eight bars needs 32 steps, which do not
  fit 16 pads, so it needs a pad-page gesture and touches every pad-render
  path. Deferred deliberately; `1/4` at 16 steps covers four bars without it.
- **Steps slower than a quarter note.** Impossible: `steps_per_beat` is an
  integer ≥ 1. Not a deferral — an API fact.
- **Per-note duration editing on the pads.** Belongs with SP2's recording.
- **Anything about drums.** Their one-shots gain nothing here.

---

## 8. Relationship to SP2

SP2 (live pad play and REC recording) is designed and waiting. It is built
**after** this, because its whole value for pads depends on notes that can be
held and patterns that can hold them. SP2's agreed decisions so far:

- Pads play the drum kit's own notes on a drum channel, a scale run from
  ROOT/SCALE on a voice.
- REC held, overdub. Release ends the take. Erase-then-record is the replace
  path.
- Recording claims `writer_token` and forces the voice to LOCK, so the
  generator stops overwriting the take. LOCK is what makes the ownership
  visible; the token is what actually enforces it.
- **ERASE + Group clears the pattern outright on a player-owned channel**,
  where today it only silences via chance/hits — because on a generated channel
  a wipe is written straight back within a bar and looks broken.
