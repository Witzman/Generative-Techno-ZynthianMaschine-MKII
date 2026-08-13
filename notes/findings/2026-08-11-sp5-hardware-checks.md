# SP5 Hardware Checks — Pattern Time at the Panel

**Date:** 2026-08-11
**Status:** deployed to the Pi, code side unit-tested (203 tests, OK), **nothing below has been run on hardware yet**
**Run this:** at the instrument, in the order given. Nothing in this document has
been verified — it is the checklist for doing that, not a report that it happened.

---

## 0. Before you start

Load the techno machine snapshot as usual. Pick any voice channel (not a drum
channel — this feature is voices only). You'll use its DIVIDE, GATE, RANDOM and
SWING controls.

---

## 1. The stuck-note gate — do this first, before anything enjoyable

**This is the gate. Do not skip to the fun checks before this one passes.**

Why it matters: a probe proved the sequencer can *store* a note-off scheduled
later than the pattern that holds it, but nothing has proven the pattern engine
actually *sends* that note-off across a pattern boundary. If it doesn't, the
note drones forever — the worst failure this instrument can produce, and the
kind you can't fix by looking at a screen, only by pulling a cable.

**Do:** select a voice, step DIVIDE round to `1/4`, set GATE to maximum, and let
it loop for one minute. Just listen.

**Expect:** every note stops. No pitch rings on into the next note, into
silence, or forever.

**If a note doesn't stop:** stop the transport immediately, note which voice
and which step it started on, and do not continue to the checks below. Report
it as a stuck note, not a maybe — this is exactly the failure mode the clamp
exists to prevent, and if you hear it, the clamp isn't holding.

---

## 2. Remove-the-clamp evidence

**Do:** with GATE still at maximum on the same voice, listen specifically to the
note on the *last* step of the pattern compared to the others.

**Expect:** the last-step note sounds audibly shorter than the rest, even
though GATE is maxed. That shortening is the safety clamp doing its job — it's
deliberately cutting the note off before it could run past the pattern
boundary.

**If all notes sound the same length, including the last one:** the clamp may
not be engaging. Note it — this needs to be understood before anyone considers
removing the clamp later, so don't discard the observation even though it
sounds like a "pass."

---

## 3. The Turing interaction (spec risk T4)

**Do:** same voice, turn RANDOM up above 0 with GATE still at maximum, and let
it mutate for one minute. The pattern rewrites itself roughly every bar.

**Expect:** notes keep starting and stopping cleanly through every rewrite. No
note left ringing because the pattern under it changed while it was sounding.

**If you hear a note stranded — going on past where its step's neighbours
would suggest, or not stopping when the pattern visibly changes:** stop and
note the voice, the RANDOM setting, and roughly when in the minute it happened.

---

## 4. Swing at spb=1 (spec risk T3)

**Do:** on the same voice, still on `1/4`, sweep SWING across its full range
while it plays.

**Expect:** the pattern stays in time throughout — no doubled hits, no notes
landing on top of each other, no audible stall as SWING crosses its middle or
either end.

**If the timing breaks anywhere in the sweep:** note the approximate SWING
value where it happened.

---

## 5. The musical check

**Do:** put a pad-type sound on the voice, `1/4` division, a long gate, and let
it run over four bars.

**Expect:** it sounds like a pad — sustained notes that breathe with the
pattern, not a rapid retrigger or a machine-gun of short notes.

**If it sounds choppy or retriggered instead of sustained:** note it — the
whole point of this feature is that `1/4` should be able to hold a note across
more than one bar.

---

## 6. Snapshot round trip

**Do:** with the voice still set to `1/4` and whatever GATE value you left it
at, save a snapshot. Reload it (or reload the instrument and load the
snapshot).

**Expect:** the voice comes back on `1/4` and the same GATE value — nothing
silently reset to a default.

**If either value comes back different:** note the voice, what you set, and
what came back. This is the append-only guarantee under test — a snapshot
should never quietly narrow what you saved.

---

## Recording results

For each of the six checks above, write down: pass / fail, and for a fail, the
exact voice, control values, and what you heard. If check 1 fails, stop there
— the remaining five are not meaningful until the stuck-note gate is closed.

---

## 7. Two things the final code review added

**A tapped step now respects GATE.** The final whole-branch review found that a
step toggled by hand on a pad wrote a fixed one-step note, while generated
steps used GATE — so on a voice at `1/4` with GATE high, your own taps would
have come out as stabs among two-bar notes. Fixed before deploy
(`78c0659a`). Worth confirming by ear: on a voice, tap a step by hand and check
it holds as long as the generated ones around it. Drums are deliberately
unchanged — their samples are one-shots.

**GATE's knob is coarser than it was.** Widening the range from 5-100 to 5-800
spreads eight times as much range across the same encoder sweep, so gate now
moves in jumps of roughly 6-24 per report and the old 5-100 region is a small
part of the travel. This is a deliberate cost of the design, not a fault. If it
proves annoying in practice, say so — the fix would be a coarse/fine split, not
a narrower range.
