# SP2 — Hardware Test Findings

**Date:** 2026-08-12
**Build:** `zynthian-ui` vangelis, SP2 commits `ad9093b3`…`d3eb853b`
**Snapshot:** `016-techno_maschine`
**Verdict: PASSED.** Eight checks, no defects. One design limit confirmed as
real rather than theoretical, and one open question from gate G5 closed.

---

## 1. What was tested

| # | Check | Result |
|---|---|---|
| 1a | Held note released on group change | **pass** |
| 1b | Held note released on mode change | **pass** |
| 1c | Held note released on transport stop | **pass** |
| 2a | Drum: all sixteen pads play the channel's own sound, velocity follows the strike | **pass** |
| 2b | Voice: pitch rises through the scale across the sixteen pads | **pass** |
| 3 | Drum recording: hits loop, pads amber, label `PLAY` | **pass** |
| 4 | Voice recording with a held note | **pass** |
| 5 | REC with the transport stopped: pads sound, nothing captured, label `REC-STOP` | **pass** |
| 6a | Handback via ERASE + Group | **pass** |
| 6b | Handback via a content encoder (HITS) | **pass** |
| 7 | Snapshot round trip: take returns, steps amber again, label `PLAY` | **pass** |
| 8 | G5 follow-up: the REC encoder burst is gone | **pass** |

Risk R1 — the stuck note, this instrument's worst failure — is retired.

## 2. The drum stuck-note test was invalid, and the voice test replaced it

The first attempt at check 1a ran on a drum channel and produced "the tone
fades out slowly after the switch". **That proves nothing.** A LinuxSampler
one-shot plays its sample to the end whether or not a note-off arrives, so on a
drum channel the test cannot distinguish a released note from a stuck one.

Re-run on **group H (PADS, padthv1)**, where the answer is unambiguous:

- Held with the group unchanged, the tone **stands indefinitely** — so the note
  really was open.
- On the group change it **decays exactly as it does when the pad is released**
  — so the note-off arrived. A missing note-off would have left it standing,
  not fading.

**Rule for any future note-off test in this rig: use a voice, never a drum.**

## 3. Recording adds, it does not overwrite

The owner's first reading of check 4 was that "the recording overwrites the
running pattern at the point where I record". It does not. What happens:

- The first captured note claims the channel, so the Turing generator stops
  rewriting and the line **freezes as it stood**.
- The played note is written **on top**. At the recorded step the pattern holds
  two notes: the generated one and the played one.

**The pads prove it without opening the sequencer.** The driver decides a step
is occupied by querying that step's *generated* note. If the generated note had
been removed, the step would read as empty and the pad would be dark — the
amber branch is only reached after the occupied check passes. So:

| Pad | Meaning |
|---|---|
| **amber** | generated note still present **and** a played note on top |
| **dark, but your note sounds** | the generated note was destroyed — a defect |

Observed: **amber**. Nothing was overwritten.

## 4. Confirmed limit: amber cannot survive a reload on a drum channel

Predicted before check 7 and confirmed by design inspection: on a drum channel
a played note carries **the same pitch as the generated one**, because a drum
channel is one sound. `_rebuild_notes` skips any note equal to the step's
generated note, so after a snapshot load the driver cannot tell the two apart.

**On drums the amber marking is lost across a reload. The notes themselves are
not** — they live in the pattern and in the `.zss`. Only the provenance goes.

The spec called this a "known and accepted limit". On voices it genuinely is an
edge case; **on drums it is not an edge case, it is always**. Check 7 was
therefore run on a voice, where the pitches differ and the reconstruction is
observable — and it passed.

This is worth revisiting: unlike CHANCE and SWING, provenance has **no truth in
zynseq to read back**. Refusing to persist it does not protect against a stale
mirror; it simply discards information nothing else holds. A future change could
persist the played-step indices and validate them against the pattern on load —
persisted *and* checked, which is not the mistake of 2026-08-11.

## 5. Closed: the G5 encoder burst

Gate G5 recorded that pressing REC emitted `controller 15, value 120` followed
by controllers 16–23 at `value 64` — `ENC_CENTRE`, i.e. a full encoder
re-centre. The hypothesis was that CC 3 fell through unhandled and something in
Zynthian reacted.

Re-measured with the SP2 driver loaded, two presses, nothing else touched:

```
129:0   Control change          1, controller 3, value 127
129:0   Control change          1, controller 3, value 0
129:0   Control change          1, controller 3, value 127
```

**No burst.** The hypothesis holds: the driver now consumes CC 3 and returns
`True`, so nothing downstream sees it.

## 6. Defect caught before hardware, recorded so it is not reintroduced

During self-review of Task 10, the drum handback was found to run **before** the
encoder delta was computed. An encoder report below the step threshold yields
delta 0, so brushing HITS without moving it by a single unit would have
destroyed a take with no value changing anywhere. Fixed in `d3eb853b`: the
handback runs only once a real movement is known.

## 7. Deviations from the plan, and why

- **Ownership is persisted under its own `owners` key**, not inside the
  per-channel fields. The plan assumed `get_state`'s `voices` covered every
  channel; it holds only the three voices, and a drum channel can be
  player-owned too.
- **`_pad_up` gained its REC branch in Task 7, not Task 6**, so no commit
  referenced a method that did not yet exist.
