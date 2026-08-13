# SP1 Addendum — Voice Density (Turing gate tap)

**Date:** 2026-08-11
**Status:** design agreed, not implemented
**Extends:** `2026-08-11-techno-machine-pass-two-design.md` (SP1). Adds two
tasks to `../plans/2026-08-11-techno-machine-pass-two-sp1.md`, numbered A1 and
A2 so the existing eleven keep their numbers.
**Gated on:** nothing new. This is pure WSL work plus one driver wiring change;
it rides the same G4 that already blocks SP1 deployment.

---

## 1. The requirement, in the owner's words

> "For the voice channels running on Turing — if I set the steps to 16, it will
> always generate 16 random notes. I also want a probability setting: I select
> 16 steps, if prob = 100 it will be 16 notes; if I turn it down there should be
> fewer steps."

A density control for the melodic voices. Rests, not just notes.

### A naming correction the owner's phrasing exposed

On the voice STEP page, **`LENGTH` is the register length** — the Turing
machine's memory in bits, 2 to 16. It is **not** the step count. Step count
comes from `DIV` through `lib.step_count()`: 1/16 gives 16 steps, 1/8T gives 12.
The two have been conflated in conversation and must not be conflated in code or
in the manual.

Two further names are already taken and must not be reused here:

| Existing name | What it actually is |
|---|---|
| `chance` | `libseq.setPlayChance` — one probability for the **whole pattern**, rolled per pass. Encoder 6 on the drum STEP page |
| `hits` | The drum channels' euclidean hit count. That **is** drum density; drums need nothing from this addendum |

The new verb is therefore **`density`**.

---

## 2. What happens today

`_write_voice_pattern` writes one note per step, unconditionally:

```python
notes = tlib.line(st["register"], st["length"], steps, …)
…
for step, note in enumerate(notes):
    self.libseq.addNote(step, note, velocity, duration, 0.0)
```

Sixteen steps, sixteen notes, every time. There is no way to produce a rest in a
voice line at all.

---

## 3. Mechanism — a gate tap off the same register

The register already produces one value per step (`tlib.rotations`). Pitch uses
that value scaled across the scale. Density reads **a second tap of the same
register** and uses it to decide which steps sound.

This is what the hardware Turing Machine's Pulses expander does, and it is the
reason this option was chosen over the two alternatives in §9: the rests come
out of the same memory as the notes, so they mutate together, and **they freeze
exactly when the register freezes**.

### 3.1 The tap

The gate stream is the register rotated by half its length, read as its own
sequence of rotations:

```
gate_reg  = rotate(register, length, length // 2)
gate_vals = rotations(gate_reg, length, steps)
```

Pitch reads value *i*; density reads value *i + length//2*. Both are the same
register, so they are not independent — but they are **offset**, so the melodic
contour and the rhythm do not move in lockstep, which is the whole point. A
purely independent RNG would not survive LOCK.

`length // 2` is at least 1 for every legal register length (minimum 2).

### 3.2 Selection — rank, not threshold

A step sounds if its gate value is among the **N lowest**, where

```
N = round(density / 100 * steps)
```

Ties break by step index ascending, so the result is fully deterministic.

Ranking is chosen over a plain `gate_frac < density` threshold because the owner
asked for a **count**: "if prob = 100 it will be 16 notes". Ranking delivers
exactly that at every setting, not on average.

| Density | Notes on a 16-step pattern |
|---|---|
| 100 | 16 — identical to today's behaviour |
| 75 | 12 |
| 50 | 8 |
| 6 | 1 |
| 0 | **0 — the channel is silent.** See §7 |

Both endpoints are exact by construction, not by luck: `N = steps` selects
every step, `N = 0` selects none.

Monotonicity holds: lowering density can only remove steps, never add or move
one. Turning the knob down thins the line rather than rearranging it.

### 3.3 Degenerate registers

A register whose rotations are all equal — all-zeros, all-ones, or any value
with rotational period 1 — produces a flat gate stream. Ranking then falls
through to the tie-break and selects the **first N steps**, a contiguous block
at the head of the bar.

This is accepted, not worked around. It is rare, it is deterministic, it is
audible as exactly what it is, and the fix is one nudge of RANDOM. Hiding it
behind a shuffle would make the mask stop being a function of the register,
which would break LOCK.

---

## 4. Pure functions — `techno_lib`

All three are pure, take no Zynthian import, and are unit tested on WSL. This
follows the SP1 constraint: **the driver cannot be imported on WSL, so logic
lives in `techno_lib`.**

```python
@staticmethod
def rotate(register, length, count):
    """The register rotated left `count` times. rotations() already walks this
    path; this returns just the endpoint."""

@staticmethod
def gate_values(register, length, steps):
    """The density tap: `steps` rotations of the register offset by half its
    length, so rhythm and pitch read the same memory at different points."""

@staticmethod
def gate_mask(register, length, steps, density):
    """Which steps sound. `density` is 0.0-1.0, matching mutate()'s chance
    argument - the driver divides its 0-100 surface value, exactly as
    setPlayChance already does.

    Returns a tuple of `steps` bools with round(density * steps) True."""
```

`gate_mask` is the only one the driver calls; the other two are separated
because they are independently testable and because SP2's recording path may
want `gate_values` later.

---

## 5. Driver wiring

### 5.1 The write

In `_write_voice_pattern`, between building `notes` and the `addNote` loop:

```python
mask = tlib.gate_mask(st["register"], st["length"], steps,
                      st["density"] / 100.0)
…
played = []
for step, note in enumerate(notes):
    if not mask[step]:
        continue
    self.libseq.addNote(step, note, velocity, duration, 0.0)
    played.append(note)
…
note_range = (min(played), max(played)) if played else None
```

`note_range` must come from `played`, not `notes`, or the debug line reports a
range containing pitches that were never written.

**The write burst gets smaller, not larger.** Masked steps skip `addNote`
entirely. Write-burst size is the largest risk in the shipped design; this
addendum reduces it at every density below 100.

### 5.2 State and defaults

- `density=100` joins the voice branch of the state init, beside `chance=100`.
- `100` is the default **because it reproduces today's behaviour exactly**. A
  snapshot written before this addendum restores to 100 and sounds unchanged.
- `"density"` joins the persisted field tuple in `get_state`/`set_state`
  alongside `register`, `length`, `random`, `gate`, `octave`, `range`.
- `"density": (0, 100, None)` joins the encoder range table, the same shape as
  `chance`.
- `"density"` joins `GENERATOR_PARAMS` — changing it must rewrite the pattern.

### 5.3 `_verb`

`density` is a voice-only verb. On a drum channel it is not reachable from any
page, and `_verb` must reject it the way it already branches on channel kind —
sending a voice verb to the drum handler is a mistake this project has made
once, and it wrote a euclidean single-note pattern over a melodic line.

---

## 6. Surface

### 6.1 Voice STEP channel page — encoder 7

| Encoder | Was | Becomes |
|---|---|---|
| 7 | `swing` | **`density`** |

`swing` is not lost: it is already page 2 of the STEP ring as a spread across
all eight channels, added by SP1 Task 1. Encoder 7 is the only slot on a full
page whose verb has a second home, which is what makes it the one to take.

Voice STEP page 1 verbs become:

```python
("length", "div", "random", "gate", "octave", "range", "density", "velo")
```

### 6.2 A DENSITY spread page

The STEP voice ring gains a fourth page:

```python
("STEP", "voice"): (
    channel page,
    _d(SHAPE_SPREAD, "SWING",   verb="swing"),
    _d(SHAPE_SPREAD, "CHANCE",  verb="chance"),
    _d(SHAPE_SPREAD, "DENSITY", verb="density"),
)
```

The drum STEP ring is **unchanged at three pages**. On the DENSITY spread page
the five drum columns grey out and read `----`, which is already the tested
behaviour for a channel lacking a verb — and it is honest: a drum's density is
`HITS`, on its own page, in its own units.

### 6.3 Column rendering

One line in `SPREAD_SPECS`:

```python
"density": ("uni", lambda v: v / 100.0),
```

and a `DENSITY` column on the voice channel page, uni bar, 0-100, the same shape
as `CHANCE`.

---

## 7. Density 0 is silence, and silence must say so

**A silent channel must say why.** A voice at play chance 0 emitted nothing,
had no surface indication, read as a hang and cost a jam. The tab row now draws
such a channel dashed.

`density = 0` produces the identical failure by a different route, so it takes
the identical treatment: extend the existing silent-channel test from

```python
silent = st.get("chance", 100) == 0
```

to also cover `st.get("density", 100) == 0`. This is not optional and is not a
polish item — it is the same defect the jam already found.

---

## 8. Interactions

| With | Behaviour |
|---|---|
| **LOCK (RANDOM = 0)** | `_rewrite_voice` returns before writing, so the register never changes, so the mask never changes. The rests are frozen bit for bit exactly as the notes are. Law L6 holds unchanged |
| **RANDOM > 0** | Each mutation moves notes *and* rests together, because both read the same register. This is the character being bought |
| **DIV change** | `steps` changes, `N` recomputes, the mask regenerates. Nothing to migrate |
| **LENGTH change** | The tap offset is `length // 2`, so it moves with the register. A different register length is a different line and a different rhythm, which is already true of the pitches |
| **Duplicate** | `_write_voice_pattern` mutates nothing, so a duplicate writes the same mask as the source. Unchanged |
| **`writer_token`** | Unchanged. The mask lives inside the turing writer and is invisible to any other writer |
| **SP2 recording** | Recorded notes are written by the recording path, not by `_write_voice_pattern`, so the mask does not apply to them. This is correct — a note you played is a note you meant. Restated in SP2's spec when it is written |

---

## 9. Rejected alternatives

**Per-note play chance.** `setNotePlayChance` exists in the Pi's installed
`libzynseq.so` — confirmed by the G4 step 4 symbol audit, 2026-08-11. Write all
sixteen notes, give each a chance equal to density. Rejected because playback
re-rolls every pass, so the pattern breathes **even at LOCK**, which breaks the
one guarantee LOCK exists to give. Worth building later as its own, differently
named control; it is not this feature.

**Euclidean mask.** `hits = round(density * steps)`, placed with the existing
`lib.euclid()`. Deterministic, evenly spaced, and the cheapest of the three.
Rejected because it imposes a euclid grid on a melodic line: the voice stops
sounding like a Turing machine and starts sounding like a drum channel that
happens to have pitches. The rhythm would no longer come from the register.

**A downbeat anchor** — forcing step 0 to sound whenever density > 0, the way
`euclid()` guarantees hit 0 at step 0. Considered and rejected: a Turing voice
that always lands on the 1 is no longer a Turing voice. If a line needs an
anchor, that is what the drum channels are for.

---

## 10. Testing

Pure, in `tests/test_techno_lib.py`, all runnable on WSL:

- `gate_mask` at density 1.0 selects every step, for several register values
- `gate_mask` at density 0.0 selects none
- selected count is `round(density * steps)` across the full 0-100 sweep
- lowering density only removes steps — assert each mask is a subset of the mask
  above it, over a sweep, for several registers
- a degenerate all-ones register selects the first N steps and no others
- a degenerate all-zeros register does the same
- `gate_values` is periodic in the register length
- `gate_values` differs from `rotations` for a register whose rotational period
  exceeds 1 — the tap is genuinely offset
- `rotate(reg, length, length)` is the identity
- the voice STEP ring is four pages and the drum STEP ring is still three
- the DENSITY spread page greys a drum column and renders a voice column
- `SPREAD_SPECS["density"]` maps 0→0.0 and 100→1.0

Driver-side, verified with `py_compile` plus hardware:

- density persists across a snapshot round trip
- a pre-addendum snapshot restores to density 100 and sounds unchanged
- a voice at density 0 draws its tab dashed

---

## 11. Risks

| # | Risk | Mitigation |
|---|---|---|
| A1 | A degenerate register makes the mask a contiguous block | Deterministic, documented, audible for what it is, one nudge of RANDOM away from resolving. §3.3 |
| A2 | Density 0 reads as a hang | Dashed tab, same treatment as chance 0. §7. **Non-negotiable** |
| A3 | Encoder 7's swing is now one page away | Swing is on the STEP spread page for every channel at once, which is where it is actually wanted during a jam |
| A4 | Rhythm and pitch are correlated, being the same register | By design, and offset by half the register length. If it ever reads as too locked, the offset is one constant |

---

## 12. Non-goals

- Per-step manual rest editing on the pads. That is STEP-page pad behaviour and
  belongs to SP2's ownership rules.
- Density on drum channels. `HITS` already is that, euclidean and better suited.
- Any change to `mutate`, `pitch`, `line` or `rotations`. The existing Turing
  path is untouched; this reads it a second time at a different offset.

---

## 13. Tasks added to the SP1 plan

**Task A1 — `techno_lib`: `rotate`, `gate_values`, `gate_mask`, plus the ring
and `SPREAD_SPECS` entries.** Pure, TDD, all thirteen tests above. No driver
changes. Committed on its own.

**Task A2 — driver wiring.** `_write_voice_pattern` mask, `density` state field
and default, snapshot persistence, encoder range, `GENERATOR_PARAMS`, `_verb`
branch, the voice STEP page verb swap, and the dashed-tab silence check.
Verified with `py_compile` and the full suite; hardware verification rides G4.

Both are WSL work. Neither needs the Pi.
