# 7 · Playing

**This section is a placeholder.** The instrument is built and installed by the
six sections before it; how to *play* it is not written yet.

Until it is, the material exists in a manual written for the prototype:
`docs/superpowers/techno-machine/2026-08-10-techno-machine-manual.md` in the
[zynth-docs](https://github.com/Witzman/zynth-docs) repository.

> **Read that manual with a date in mind.** It describes the surface as of
> 2026-08-10: three pages (CONTROL, STEP, ALL) and pads that only toggle steps.
> The shipped surface has **five modes** with page rings, pads that play as an
> instrument outside STEP, REC overdubbing with pattern ownership, and SHIFT+GRID
> channel-kind switching. Where the two disagree, the code is right and the manual
> is old.

---

## What will go here

**The euclidean model.** Hits spread as evenly as the grid allows, then rotated.
Why 4 in 16 is four-on-the-floor, 5 in 16 is the clave, 3 in 8 is tresillo. Why
pattern length moves in whole *beats* while the display counts *steps*, and why
1, 5, 7, 11 and 13 steps are unreachable.

**The Turing machine, and `LOCK` as the central gesture.** A register clocked once
per pass, mutated one bit at a time, read as pitch. The workflow the instrument is
built around: set `RANDOM` to 20-40, let the voice fish for a phrase, and snap it
to 0 the moment you hear one worth keeping — the cell reads `LOCK`, a word rather
than a number that could be a coincidence. Then `DUPLICATE` as the undo for the
phrase the wrap took before your hand arrived, four registers deep.

**The five modes and the page rings.** What CONTROL, STEP, ALL, MIXER and FILTER
each make the eight encoders mean, why encoders 6, 7 and 8 are LEVEL, REVERB and
DELAY on every channel of both kinds, and why a knob with no source is greyed and
dead rather than quietly doing nothing.

**REC and ownership.** Holding REC overdubs into the same pattern the generator
writes; the note's length is how long the pad was held. A captured note makes the
player the owner of that channel's pattern and the generator stops writing it.
Two gestures hand it back, both destructive, and knowing which knobs those are is
the difference between keeping a take and losing it.

**SHIFT + GRID.** Switching a channel between drum and voice behaviour without
swapping its engine: a drum kit gets the Turing generator, a synth gets euclid as
a root pulse. Why the register walks a *kit's own note list* on a sampler instead
of quantising to a scale.

**Performing.** Mute and solo, tap versus hold, ERASE as a hold-only gesture, what
each LED colour means, and reading the display's tab row — including the dashed
tab, which is the only thing that ever explains silence.

---

**Back to:** [1 · What It Is](01-what-it-is.md) · [6 · Testing](06-testing.md)
