# Techno Machine — SP4: Channel Type Switching

**Date:** 2026-08-12
**Status:** design agreed, ready for a plan
**Extends** `2026-08-11-techno-machine-pass-two-design.md` (§2 names SP4) and
`2026-08-12-sp2-live-play-record-design.md`, whose `owner` flag defines the
ownership rule SP4 obeys.

---

## 1. Context

The techno machine ships five euclidean drum channels and three Turing voices.
Which is which is fixed at design time — or rather, it is **derived**:
`channel_kind()` reads the chain and returns `"drum"` for anything running
LinuxSampler or FluidSynth, whatever `tlib.CHANNELS` says. Its own comment puts
it plainly: *"the table is the intent, but the loaded snapshot is the truth"*.

SP4 lets the player override that from the panel: **SHIFT + GRID** tells the
selected channel it is now a drum or a voice.

**It does not swap engines.** That was considered and deferred (§8). What
switches is which generator writes the pattern and which surface the channel
presents — so a drum kit can be played by the Turing register, and a synth can
be pulsed by the euclid generator.

---

## 2. The gesture

**Hold SHIFT, press GRID.** Toggles the selected channel between `drum` and
`voice`. Two states, no third.

| Button | CC | Status |
|---|---|---|
| SHIFT | 49 | Emitted since SP1's daemon patch, no consumer until now |
| GRID | 4 | Measured at gate G4, unbound |

No three-key chord and no separate addressing mode: you select a group the way
you already do for everything else, then switch it. One hand.

**Switching back to the chain's own kind clears the override to `None`** rather
than pinning it to the same value. Otherwise one press would permanently freeze
a channel to a kind it merely happens to have today, and a later snapshot that
puts a different engine on that chain would be overruled by a stale choice
nobody remembers making. A channel is only overridden while it actually differs
from its chain.

**Switching rewrites the pattern, so it is destructive.** On a player-owned
channel SP2's rule therefore applies unchanged: the switch hands the pattern
back to the generator and the take is gone. A second, contradictory rule for
the same situation would be worse than the loss.

---

## 3. What the type controls

`kind_override[channel]` is `None` until the player switches. `channel_kind()`
consults it first and otherwise behaves exactly as it does today.

**One source of truth per channel at all times** — either the chain or an
explicit choice, never a stored copy of the chain that can go stale. This is
deliberate: storing a derived value, then watching the source move underneath
it, is precisely the CHANCE/SWING defect of 2026-08-11, where the driver and
zynseq agreed on the wrong answer and a silent channel reported itself healthy.

Eight behaviours already follow from `channel_kind()` and now follow the
override with no further work:

- which generator writes the pattern — euclid or Turing
- which page ring and which verbs sit on the encoders
- how `_step_note` derives a step's note
- what the pads play live (SP2)
- what ML/MR steps through — a sample within the kit, or an engine preset
- what LENGTH means — pattern beats, or shift-register bits
- how the tab decides a channel is silent — `hits == 0`, or `chance`/`density`
- which state set is visible

### What it does not control: the engine

The chain is untouched. A drum channel in voice mode is still LinuxSampler; a
voice in drum mode is still JC303.

One consequence must be handled rather than left: **CUTOFF, RESO, ENV and DECAY
on a sampler channel in voice mode.** `VOICE_SYMBOLS` is keyed by engine code
and has no entry for `LS/LinuxSampler`, so `_set_voice_ctrl` already bails out
and the knob moves nothing. But the columns would still **draw numbers** out of
the state dict — a lie on the glass. Law L4: a column whose source does not
exist draws dead. Those four columns now check whether the channel's engine
publishes their symbols at all.

---

## 4. What each generator does on foreign ground

### Turing on a drum kit — a random walk across the kit

The register does **not** select pitches here. On the shipped SFZ kits a note
number selects **which sample sounds** — `key=` / `lokey=` maps notes to
different drums — so quantising to ROOT and SCALE would land most steps on
empty keys. An empty key is silence with nothing to explain it, which is the
one thing this instrument must never do.

Instead the register selects **positions in the kit's own note list**, which the
driver already parses from the `.sfz` for the sample names. Every step hits a
real drum. Same register rotations as `techno_lib.line()`, different mapping —
a sibling function beside it.

**ROOT and SCALE have no meaning on such a channel.** They are global and go on
governing the real voices; on this channel's own pages the pitch-related columns
draw dead, because there is no pitch.

If a kit's note list is empty or unreadable, the walk falls back to the
channel's own note. It degrades to a plain repeated drum, never to silence.

### Euclid on a synth — a root pulse

`_write_pattern` writes one note repeatedly. On a drum that note is the
channel's drum; on a synth it is **ROOT plus the channel's OCTAVE**.

Both controls therefore keep meaning: turning ROOT transposes the pulse,
OCTAVE places it. It comes free from SP2's `pad_note(0, root, scale, octave)`,
which returns exactly the root.

The alternative — reusing whatever pitch `_group_note()` discovers in the
pattern — was rejected: it leaves the voice stuck on an arbitrary note that no
control can reach.

---

## 5. Per-kind state memory

`self.state[channel]` stays "the active state", so nothing that reads it today
changes. On a switch the current set is **stashed** and the opposite set is
restored, or built fresh from the same defaults `__init__` uses the first time.

**Stashed:** the state dict, plus `hits` and `rot` from the legacy arrays.

**Not stashed: `div` and `beats`.** Those are pattern *time*, not channel kind —
they mean the same thing to both, and if they moved on a switch the groove would
jump. Switching changes what a channel sounds like, never its grid.

Without this memory the switch is a one-way door nobody uses for fear of losing
their settings. The driver already carries this pattern one level up: the page
rings remember their position per `(mode, kind)`.

---

## 6. Persistence

Two new top-level snapshot keys, following SP2's `owners` precedent:

- **`kinds`** — the explicit overrides
- **`stash`** — the sleeping state sets

Both are pure driver state with no counterpart in zynseq. There is nothing to
read back and nothing that can drift behind the driver's back, which is exactly
why persisting them is right here and was wrong for CHANCE and SWING.

---

## 7. Display

A channel called **KICK** that behaves like a voice is a trap without a marker.

The page-indicator row, which already carries `PLAY`, `REC` and `REC-STOP` from
SP2, gains **`DRM`** or **`VOX`** — **for the selected channel, and only while
its override is set**. An unused feature costs no space, and a switched channel
says so where the player is already reading. Since the override clears itself
when it matches the chain (§2), the marker is present exactly when the channel
is behaving differently from what its engine suggests.

The tab row is not touched. Dashed there means "this channel is not sounding",
and that meaning is not diluted a second time.

---

## 8. Out of scope, and recorded

- **Engine swapping.** The owner's own idea: spare chains in the snapshot, each
  channel carrying both a sampler and a synth with one muted, so a switch is
  instant and real. Costs roughly 5% of a core idle for five more jalv hosts,
  plus RAM and a new snapshot. Deferred by the owner, who has an idea for it.
- **A range-limited kit walk.** Confining the random walk to part of the kit —
  only the hats, say — with the voice's RANGE column taking that role. Worth
  having once the full walk has been heard for a few minutes; not before.
- **The big encoder as the current page's master** remains SP6.

---

## 9. Testing

**Unit tests, in `techno_lib`:**

- the register-to-kit-note mapping, including an empty kit list
- the root pitch for euclid on a voice, across root and octave
- kind resolution precedence: override before chain before table
- the page label with and without an override
- stash and restore as a round trip

**Hardware checks, in order:**

1. Drum to voice: a random walk across the kit is audible, **no silence**, every
   step hits a drum.
2. Switch back: HITS and ROTATE stand **exactly** as they were.
3. Voice to drum: a root pulse, and turning ROOT transposes it audibly.
4. On a sampler in voice mode, CUTOFF, RESO, ENV and DECAY draw **dead** rather
   than showing numbers.
5. Snapshot round trip: the types and both state sets come back.
6. Switching a player-owned channel hands back, exactly as turning HITS does.

---

## 10. Risks

| | Risk | Mitigation |
|---|---|---|
| R1 | A kit with very few notes degenerates the walk, or the list is empty | Falls back to the channel's own note — never to silence |
| R2 | `state_view` on a channel missing the opposite kind's keys | The fresh set is built complete on the first switch, never half |
| R3 | Switching with a pad held | `_release_all`, exactly as on a mode change |
| R4 | A switch lands while the Turing thread is writing | Runs under the same lock and the same `owner` check as every other write |
