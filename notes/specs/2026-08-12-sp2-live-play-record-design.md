# Techno Machine — SP2: Live Pad Play and REC Recording

**Date:** 2026-08-12
**Status:** design agreed, build gated on G5
**Extends** `2026-08-11-techno-machine-pass-two-design.md` (§2 names SP2) and
`2026-08-11-sp5-pattern-time-design.md` (§8 records the decisions taken before
this spec existed). It revises two of those decisions — see §2 and §6.1.

---

## 1. Context

The techno machine ships five euclidean drum channels and three Turing voices,
played from the Maschine MK2. Every note it makes is written by a generator.
The pads are a step editor and nothing else: `_midi_event` maps a pad NoteOn to
`_toggle_step` in every mode, and discards NoteOff entirely.

SP2 makes the pads an instrument. You play them, and with REC held you capture
what you played into the same pattern the generator writes. That is the first
time a human is a writer of a pattern in this rig, which is why most of this
spec is about **ownership** rather than about notes.

SP1 shipped and was hardware-verified 2026-08-11; SP5 shipped with it. SP2 was
always sequenced after them because pads that can hold notes are worthless
until patterns can hold long notes, which is what SP5 built.

---

## 2. Decisions taken before this spec, and two revisions

§8 of the SP5 spec recorded four agreed decisions. Two stand as written:

- REC is **held**, and it **overdubs**. Release ends the take. Erase-then-record
  is the replace path.
- **ERASE + Group clears the pattern outright** on a player-owned channel,
  where today it only silences via chance/hits.

A third stands in substance but not in mechanism: recording does claim the
channel and does force a voice to **LOCK**, but it cannot do so through
`writer_token` — see §6.1.

**Revised here: "pads play the drum kit's own notes on a drum channel."**

It does not survive contact with the recording rule. A drum channel is one
sound — `_group_note()` returns a single note per group, and the pad LEDs,
`_toggle_step` and `_erase_step` all derive from it. A pattern that held
several kit notes would need `_group_note` to fall, would make the euclid
writer's "which note do I write?" undecidable, and would make ML/MR's "the
sound of this channel" ambiguous. So a recorded hit stores the **channel's own
note** (§4.2).

But then playing the kit live while recording the channel note means you hear
Clap and record Kick. What you play is not what you get — the same class of
failure as the silent channel that cost a jam, in a new costume. So:

> **On a drum channel all sixteen pads play that channel's own note**,
> differing only in velocity and timing. Kit and sample selection stay where
> they already live, on ML/MR.

Finger-drumming the whole kit is a real wish and is not abandoned; it belongs
to a multi-sound channel type, which is SP4's business. It is not smuggled into
SP2.

---

## 3. Surface

| Gesture | Effect |
|---|---|
| **REC held** | Record on the **selected** channel. Release ends the take |
| **Pads, mode STEP** | Unchanged: toggle a step, velocity from the strike |
| **Pads, every other mode** (CONTROL · ALL · MIXER · FILTER) | The instrument: play live, capture with REC |
| **ERASE + Pad** | Unchanged, STEP only |
| **ERASE + Group**, generator-owned | Unchanged: `_silence_channel` |
| **ERASE + Group**, player-owned | Clear the pattern **and** hand the channel back to its generator, which rewrites immediately |
| **Drum: HITS / ROT / DIV turned**, player-owned | The generator takes the channel back and rewrites. The take is gone — this is the shipped law ("enc 1-3 own the steps") extended, not a new one |
| **Drum: LENGTH turned** | Always allowed, under either owner: `_set_length` is non-destructive and recounts hits from what survives |
| **Voice: LENGTH / DIV turned, or RANDOM moved off LOCK**, player-owned | Same handback. On a voice these three are the content knobs: all of them route to `_write_voice_pattern`, which clears and rewrites from the register |

**The handback set is per kind, and it is exactly "the knobs that rewrite the
pattern".** On a drum that is HITS, ROT and DIV; LENGTH is outside it because
`_set_length` preserves the steps that fit. On a voice it is LENGTH, DIV and
RANDOM — a voice's LENGTH is the shift register, not the pattern's beats, and it
regenerates the line. Nothing else on either kind touches note content.

The mode decides what a pad is. STEP stays the editor; everything else becomes
the instrument. That is the only new concept the player has to learn.

### Why both handback routes exist

An explicit route alone (ERASE + Group) leaves HITS, ROT and DIV inert while a
channel is player-owned — a knob that feels dead. This instrument has a law
against unexplained silence, and a dead knob is that law in another form. An
implicit route alone leaves no way to drop a take *and* get the euclid pattern
back without hunting values by hand. Both gestures have to do something
sensible anyway; §3 only writes down what.

---

## 4. Live play

### 4.1 Mechanism

`playNote(note, velocity, channel, 0)` on press, `playNote(note, 0, channel, 0)`
on release. `duration=0` means no auto note-off (`zynseq.cpp:1742`) and a
NoteOn at velocity 0 is a note-off. The existing 200 ms `_preview` stays where
it belongs — auditioning a kit or sample change.

**The driver must handle NoteOff for the first time.** `_midi_event` currently
filters with `ev[2] > 0`. That filter goes. The step toggle stays explicitly
bound to NoteOn so STEP mode cannot start toggling twice per pad.

The daemon already emits pad note-off on release (`main.rs:1411`), conditional
on `padmode != 2`. G5 step 2 confirms both facts on the wire.

### 4.2 What a pad plays

- **Drum:** all sixteen pads trigger the channel's own note, velocity from pad
  pressure. Heard equals recorded.
- **Voice:** pad *n* plays scale degree *n* counting up from ROOT, based at
  `BASE_NOTE + OCTAVE` for that channel, with SCALE taken from the ALL page. A
  seven-note scale spans a little over two octaves across sixteen pads; a
  pentatonic spans a little over three.

The voice keyboard is deliberately **independent of the generator**. It does
not follow RANGE and does not mirror the running line: a keyboard has to lie
still under the hands, and both alternatives move the mapping while you play —
while coupling hand-play to the very generator the recording is about to
switch off.

### 4.3 Stuck notes

A held note that never receives its note-off is the worst failure this
instrument can produce — it is the silent channel's twin, and it is louder.

Every held note is force-released on: group change, mode change, transport
stop, ownership change, `end()`, and `light_off()`. This is not a nicety. It is
the first line of the hardware test plan (§8).

---

## 5. Recording

- **Nothing is captured while the channel's sequence is not playing.** With no
  playhead there is no step. Pads still sound, and the display says that
  nothing is being captured — otherwise it is silence without an explanation.
- **Quantise to the nearest step** from the live playhead. A strike past the
  midpoint of the last step lands on step 0 of the next pass.
- **Overdub only.** Existing notes stay. Replacing goes through ERASE.
- **Duration is hold time in steps**, minimum 1, clamped with
  `min(duration, steps - step)` — SP5's Change 3 clamp, inherited unchanged
  rather than fought.
- **The first captured note claims the channel:** `owner[channel] = "player"`,
  and a voice is forced to **LOCK** (RANDOM 0). The owner flag enforces; LOCK
  makes it visible.
- A second strike on a step that already carries that note **replaces** it
  (velocity and duration updated). It does not stack a duplicate.
- Velocity comes from pad pressure, as `_toggle_step` already does.

---

## 6. State, persistence, display

### 6.1 Ownership

`owner[channel]` ∈ `gen` | `player`, its own durable field, saved in
`get_state`.

**This revises §8 of the SP5 spec, which said recording "claims
`writer_token`".** It cannot: that token is the short-lived mutex between the
MIDI thread, the zynsigman handler and the 30 Hz poll thread, and
`_write_voice_pattern` sets it to `"turing"` and back to `None` around every
single write. A flag that clears itself after each write cannot express an
ownership that has to survive a snapshot.

So the two stay separate. The token remains the mutex, untouched.
`_write_voice_pattern` gains one line: it returns early when
`owner[channel] == "player"`, alongside the token check it already makes. That
is what actually stops the generator, and it is the same guard for a mutation
scheduled by the poll thread as for one triggered by an encoder.

### 6.2 The note map

`notes[channel]`: `step → (note, velocity, duration)`, maintained for
player-owned channels only.

The driver needs it because it never *asks* what a step holds — it **derives**
it. `_step_note` returns `_group_note(channel)` on a drum and recomputes the
Turing line on a voice. Pad LEDs, `_toggle_step` and `_erase_step` all depend
on that derivation. A pattern containing notes no generator derived would read
as empty, and ERASE would grab at nothing.

**The map is a cache, not the truth.** The notes live in the pattern and
therefore in the `.zss`. The map is **rebuilt from the pattern** on
`SS_LOAD_SNAPSHOT` and on every ownership change; only `owner` is persisted.
This is the CHANCE/SWING lesson of 2026-08-11 applied before it bites: any
mirrored zynseq state must be read back on load, never assumed.

The rebuild is cheap because the candidate set is small — the installed API has
no `getNoteAtIndex`, but it does not need one. A drum channel has exactly one
candidate note (16 `getNoteVelocity` calls); a voice has its sixteen scale-run
notes plus its derived line (~256 calls). Not 128 × 16.

**The rebuild runs on the poll thread**, never on the MIDI thread, for the same
reason `_commit_kit` and `_commit_preset` do.

### 6.3 Display

The page-indicator label row (today `LEVEL 1/3`) carries the REC state and the
channel's owner.

The tab row is not touched. A dashed tab means "this channel is not sounding",
and that meaning is not diluted with a second one.

**A played-in step lights amber** (`0xFF8800`), where a generated step keeps the
group colour. The playhead still wins on the pad it is standing on. Amber is
free: the daemon uses it for its own selected step, the driver uses it nowhere.

This overrides `_toggle_step`'s standing comment, "no hidden per-step override
state, and no third LED colour to explain". That comment was written when there
was no such state. Now there is, it survives a snapshot, and **the handback is
destructive**: after a snapshot load, a player-owned channel that looks exactly
like a generated one invites you to nudge HITS to try something, which silently
eats the take. The display carries the ownership in words, but while playing you
are looking at the pads. A colour that costs one line of explanation is cheaper
than a lost take with no warning where you were looking.

This makes the note map (§6.2) load-bearing for the grid, not only for
`_step_note` — which is another reason it is rebuilt from the pattern on load
rather than trusted.

---

## 7. Gate G5

Ten minutes with hands at the panel, **before** any build. The G4 lesson stands:
never bind a button without a capture.

1. `aseqdump`, press REC. **Expect CC 3, both edges** — that is what the
   daemon's `rec` token sends (`main.rs:938`), but the daemon's token names are
   attached to the wrong physical buttons twice already, and REC was not among
   the buttons G4 captured.
2. `aseqdump`, press and hold a pad. Expect NoteOn, then NoteOff on release.
   This also confirms `padmode != 2`, the condition the daemon puts on note-off.
3. `nm -D --defined-only` against the installed `libzynseq.so`:
   **`getNoteDuration`, `getNoteStart`, and `playNote`'s arity.**
   `getNoteAtIndex` is known absent there; nothing in this list is assumed.

---

## 8. Testing

**Unit tests** (in `techno_lib`, on WSL, where the driver itself cannot be
imported):

- playhead clock → nearest step, including the wrap past the last step
- hold time → steps, minimum 1, with the loop-point clamp
- pad index → note, across root, scale and octave
- candidate note set per channel kind
- ownership transitions in both directions

**Hardware checks, worst failure first:**

1. **Stuck note.** Hold a pad, then change group, change mode, and stop
   transport. Silence each time.
2. Record on a drum: four strikes, survives the loop.
3. Record on a voice: held length audible, no hang at the loop point.
4. ERASE + Group: the euclid pattern comes back.
5. Turn HITS: the take is overwritten, as advertised.
6. Snapshot save and load: the take returns, the map is rebuilt, and the
   played-in steps come back **amber** — the map driving the grid is the check
   that it was rebuilt rather than assumed.

---

## 9. Risks

| | Risk | Mitigation |
|---|---|---|
| R1 | **Stuck note** — the worst failure this instrument has | Forced note-off on every ownership, mode, group and transport change; first hardware check |
| R2 | Dropping the NoteOff filter breaks STEP toggling | Step toggle stays explicitly bound to NoteOn; unit test on the dispatcher |
| R3 | `getNoteDuration` absent on the Pi | G5 step 3. Fallback: rebuild assumes one step of duration — audibly poorer, not broken |
| R4 | Rebuild scan on the MIDI thread under the lock | Rebuild runs on the poll thread |

---

## 10. Out of scope

Multi-sound drum channels · finger-drumming the whole kit · channel type
switching. All SP4, whose three-writer ownership rule is now defined by §6.1.
