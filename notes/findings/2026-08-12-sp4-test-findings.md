# SP4 — Hardware Test Findings

**Date:** 2026-08-12
**Build:** `zynthian-ui` vangelis, SP4 commits `c2648c8b`…`f0171f47`
**Snapshot:** `016-techno_maschine`
**Verdict: PASSED.** Six checks, **zero defects found on hardware**. The two
defects SP4 did produce were both caught in self-review before deploying.

---

## 1. What was tested

| # | Check | Result |
|---|---|---|
| 1 | Drum to voice: the register walks the kit, every step hits a real drum, `VOX` shows | **pass** |
| 2 | Switch back and forth: the euclid and Turing settings both survive the round trip, `VOX` clears itself | **pass** |
| 3 | Voice to drum: one repeated pitch, `DRM` shows, ROOT transposes the pulse | **pass** |
| 4 | A sampler in voice mode draws CUTOFF/RESO/ENV/DECAY dead, while a real voice still draws them live | **pass** |
| 5 | Switching a player-owned channel hands back: take gone, amber gone, `PLAY` gone | **pass** |
| 6 | Snapshot round trip: the override, the kit walk and the stashed drum settings all return | **pass** |

Check 4 was run as a **comparison**, not a single look: dead on group A and
live on group H. Dead on both would have meant the flag simply greyed
everything; the difference is what proves the driver is discriminating
correctly — LinuxSampler publishes no filter controls, JC303 and padthv1 do.

## 2. Confirmed by the owner: hand-edited steps do not survive a switch

Observed during check 2, and correct:

> Turing sequences come back exactly, euclid steps too. Only manually set steps
> are not carried over when switching back — but that fits the operating
> concept.

It does. Switching **rewrites the pattern from the generator's parameters**, so
hand-placed steps die with it. That is the law the drum rig has shipped with
since 2026-08-07: encoders 1-3 own the steps, a pad tap is an edit the next
encoder turn wipes. A kind switch is such a turn. The per-kind memory covers
**parameters**, never hand edits — those live only in the pattern, and the
pattern is what gets rewritten.

## 3. Two defects caught in self-review, neither reached hardware

Both were in the snapshot path and neither was anticipated by the plan.

**`get_state` keyed the voice block on the `CHANNELS` table.** A drum chain
switched to voice carries `register`, `gate`, `octave` and the rest — values
that exist nowhere else, because a drum channel's own parameters are re-derived
from zynseq on load while a voice's are not. The table would have dropped them
on save and the channel would have come back as a drum. Now keyed on
`channel_kind(i)` — how the channel *behaves*, not what the table intended.

**`set_state` restored the override without restoring a matching state set.** A
channel would have been marked `voice` while still holding the drum dict
`__init__` built for it. `columns()` indexes `state["cutoff"]` directly, so that
is a `KeyError` on the first repaint — precisely risk R2, at a place §10 had not
looked. `set_state` now aligns each channel's active set with its resolved kind
before anything reads it, pulling from the stash or building a complete fresh
set.

## 4. The two grep checks earned their place

Tasks 4 and 6 are refactors where a missed call site fails **silently** rather
than loudly, so each ended with a count instead of a test:

- `_chain_kind` must appear exactly **3** times — the definition plus the two
  calls in `channel_kind` and `_is_sampler`. A fourth would be a caller that
  bypasses the override entirely.
- `tlib.line(` must appear exactly **1** time — only inside `_voice_notes`. A
  second would let the pad renderer and the pattern writer disagree about what
  is on a step, which reads as "the pads are wrong" rather than as a bug.

Both came out exactly right.

## 5. Worth knowing before testing again

**A voice switched to drum may be silent, and that is not a defect.** `hits`
initialises to 0 and is read back from the pattern by counting notes that match
the channel's discovered reference note — on a Turing line that count can land
anywhere, including zero. A euclid channel with `hits` 0 is legitimately silent,
and the tab draws it dashed to say so. Turn HITS up.

---

## 6. Deviations from the plan

None in structure. The plan's library default for a voice's `register` was
written as `0`; the driver seeded it inline with `0b10110011`, so the real seed
moved into `techno_lib.default_channel_state` unchanged and a test now pins it —
changing it would change what every voice plays on a cold start.
