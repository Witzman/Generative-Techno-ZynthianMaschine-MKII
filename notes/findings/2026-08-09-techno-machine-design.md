# The Techno Machine — arbitrated design

**Date:** 2026-08-09
**Status:** ruled. This is the document the project builds from.
**Supersedes:** `docs/superpowers/2026-08-09-techno-machine-mapping.md` (solo prior art).
**Arbitrates:** `techno-machine/po-position.md` (Product Owner) and
`techno-machine/dev-position.md` (Developer), plus one round of cross-examination
of each. Where either paper disagrees with this one, this one wins.

**Governing principle, from the project owner:** *prototype first, then extend
further and further.* A prototype that plays is worth more than a complete design
that does not exist — but the prototype must not paint the extensions into a
corner. Section 6 is where that second half is cashed in, and it is the section
most likely to be skipped and most expensive to skip.

**What this machine is, in one paragraph.** A generative groovebox played from a
single Maschine MK2 on a Raspberry Pi 4 running Zynthian. Eight channels, all
alive from power-on, never constructed at run time: five euclidean drum channels
(A–E) and three Turing-machine voices (F–H). Every channel has reverb and delay
on encoders 7 and 8. Three latched page buttons decide what the eight encoders
mean. There is no song mode, no browser, no dialogue and no confirmation. The
touchscreen exists to save snapshots.

---

## 1. Decision log

The most valuable section in this document. Each row is a real disagreement, not
a summary of agreement. Where one side lost, it says so and says what they get
back later.

### D1 — Instant lock vs loop-boundary rewrite

| | |
|---|---|
| **PO** | Turning RANDOM to 0 must lock the Turing line *at that instant*, bit-identical forever. "If turning the knob to zero sometimes gives me the bar I heard and sometimes the one after, the gesture is gambling instead of playing, and the voice concept is dead." Non-negotiable §4.3. |
| **DEV** | The Turing register is written into a zynseq pattern on a playhead wrap, from the existing 30 Hz poll thread, under `self.lock`. Notes are never emitted by the driver directly — the pattern is the source of truth, because that is what buys persistence, the touchscreen editor and pad editing. |

**RULING: they were never in conflict, and both sides missed it. PO's requirement
is satisfied for free by DEV's mechanism. No compromise is needed and none is
made.**

Because the pattern is rewritten *only* on a wrap, the audible line is
bit-constant for the whole cycle by construction. "RANDOM → 0" therefore means
exactly "skip the next rewrite" — the loop being heard is the loop kept, forever,
because nothing rewrites it. DEV confirmed this on cross-examination and conceded
he had not spelled it out. The model that breaks §4.3 is per-*step* mutation
applied to a live pattern, and nobody is proposing it.

Two conditions are attached, both binding:

1. **Mutation is incremental on a persistent register, never a fresh line per
   wrap.** PO's condition, and it is correct: low RANDOM must mean "one note
   drifted this bar". A machine that regenerates the whole line each cycle is a
   random-line generator, not a Turing machine, and the slow drift *is* the
   musical value. The register persists across cycles; RANDOM is the per-step
   bit-flip probability applied as the register is clocked forward through the
   cycle.
2. **A 4-deep register ring per voice, in the prototype.** The one residual
   gambling window is human reaction time — the wrap fires and replaces the phrase
   before the hand lands on the knob. DEV: the register is one integer of ≤16
   bits, so a 4-deep `deque` costs nothing and covers two wraps of reaction
   (~1.8 s per cycle at 132 BPM). ~2 h. PO promoted it to the prototype and it is
   granted.

**Cost of the ruling:** mutation granularity is per cycle, not mid-bar. Drift
lands on the bar line. PO accepted this explicitly, and it is the same trade as
D8 — structure lands on the bar.

**Rejected:** zynseq's native `undoPattern` / `savePatternSnapshot` /
`restoreSnapshot` stack. It operates on the note list, not the register, and it
would fight the touchscreen editor's own undo. The driver's register ring is the
right owner.

### D2 — Sends

| | |
|---|---|
| **PO** | Does not care about the mechanism. Cares, non-negotiably (§4.2), that encoders 7 and 8 are REVERB and DELAY on every channel of every type, forever, with no exception. |
| **DEV** | True sends are impossible below tier 4. `rebuild_audio_graph` feeds every destination the identical source at unity (no per-destination gain), and the native send-tap topology needs 26 mixer strips against `MAX_CHANNELS 17` in `zynlibs/zynmixer/mixer.c:48` (16 usable, strip 16 is main). Refuses to raise it. Proposes a post-fader insert reverb and delay per channel, ~4–7 % of one core, behind a measurement gate. |

**RULING: DEV wins the mechanism, PO wins the contract. Post-fader inserts, per
channel, both knobs live on all eight channels of both types. A true shared bus
is not built and is not promised.**

The insert satisfies §4.2 *literally*, and for a non-obvious reason worth
recording: the wet parameter is a **plugin** zctrl, not an engine zctrl, so
LinuxSampler's empty `_ctrls` — the thing that killed volume and pan on the drum
chains — cannot bite here. Both knobs are live on drums and on voices with no
exception, which is precisely what the shipped rig could not do for any other
parameter.

**PO's condition, granted: the eight inserts are GANGED by default.** One set of
reverb and delay parameters on the ALL page drives all eight instances, so the
channels share decay, size, damping and delay division. Identical character in
eight boxes is most of the way to a coherent space. Per-channel divergence is a
later opt-in and is not built.

**What is actually lost, honestly** (DEV's own words, not a reassurance):

- No shared tail. Eight independent small rooms never glue into one big room.
- No duckable, EQ-able return. Sidechaining the reverb return against the kick —
  a defining techno move — is unavailable.
- `blend` on CAPS PlateX2 is a **crossfade, not an additive wet**, so turning
  knob 7 up turns the dry down. Mitigation: cap the knob at ~0.45 of the plugin
  range, and prefer a delay plugin with a separate wet level. Verify per plugin
  at gate G2.

**Degrade path corrected.** DEV's paper offered "shared FX chain, per-channel
routing on/off" as the fallback. On cross-examination he conceded it **breaks
§4.2** — a shared bus fed by on/off routing turns knob 7 into a toggle wearing a
knob's clothes. **It is off the table.** The correct degrades keep the topology
and cut something else, in this order: (1) swap to cheaper plugins — MDA Ambience
and MDA Delay instead of PlateX2 and `Gxdigital_delay_st`; (2) cut channel count
from 8 to 6. Both keep knobs 7 and 8 live on every channel that exists.

**Refused outright, and this stands:** raising `MAX_CHANNELS`, and adding a
per-destination gain to `rebuild_audio_graph`. Realtime C in the routing core
every Zynthian chain uses, +64 JACK ports, and both the snapshot format and the
touchscreen mixer assume 16 strips. Permanent upstream divergence for a gain the
player cannot hear once inserts exist.

### D3 — The big encoder

| | |
|---|---|
| **PO** | Wants NI's verb + object + value grammar: press VOLUME, hold a Group button, turn the big encoder. Calls verification "one afternoon" and says it unlocks three parameters per channel at no page cost. |
| **DEV (paper)** | Not merely unverified — **absent**. `MaschineButton::Encoder` appears nowhere in `BUTTON_REPORT_TO_MIKROBUTTONS_MAP`; `roller_state[8]` is never written from HID. Refuses to hang any musical function on it; calls it a `usbmon` capture, "research, not a patch". |
| **DEV (cross-exam)** | **Corrects his own paper.** `readable()` at `mikro.rs:857` already reads every report into a 512-byte buffer and dispatches on report ID; `read_buttons` discards everything past `buf[23]`, and unrecognised report IDs are dropped unlooked-at. No `usbmon` is needed. Triage is two `println!`s and a knob turn: **~30 min to know**, ~2–4 h to decode and emit if the bytes are in report `0x01`, ~1–2 days if a new parse path is needed. |

**RULING: the grammar is kept and the wheel is dropped. The verb is a held or
latched button; the OBJECT is the eight tabs; the VALUE is the eight small
encoders. Eight channels at once, not one at a time.**

This is strictly better than what NI does and than what the PO asked for: holding
VOLUME gives eight faders under their own eight tabs and you ride them
two-handed; holding SWING gives eight swings the same way. PO accepted and called
it better. DEV confirmed all three verb buttons are **one ~10-line patch and one
deploy** — SWING and VOLUME are already decoded from HID and merely have no arm
in the `match button` at `main.rs:918`; TEMPO already emits CC 35. Free CCs:
49–79 and 88–127. Proposed: **49 = shift, 50 = swing, 51 = volume**.

**One correction to the PO's own grammar, and it is a real override.** PO
insisted "SHIFT-as-level IS the mixer layer; never give SHIFT a second meaning."
But PO's §2.2 also names VOLUME as the volume verb. Both cannot be true without
duplicating the function on two buttons. **Ruling: VOLUME held is the mixer.**
The legend is printed on the button, it is the verb the PO's own grammar names,
and it leaves SHIFT as a clean general modifier (SHIFT+ERASE = clear all,
SHIFT+Fn = exclusive solo). The PO loses "SHIFT is the mixer" and gains a
correctly-labelled button; the prior art's §3.5 is otherwise honoured intact.

**Verb buttons obey the tap/hold law** (D7): tap latches so the player can
two-hand the knobs; hold is momentary. PO's condition, granted.

**Master output level** does not need the wheel either: global SWING vacates the
ALL page (swing is per channel now — D6), so **ALL encoder 4 = MASTER**. PO had
already conceded master volume to the touchscreen; this is better than the
concession and costs nothing.

**Is the wheel worth daemon work later? Yes — as triage, not as a dependency.**
Thirty minutes to know is cheap enough to do in pass 2. Nothing musical may
depend on it until it is emitting. Hard caveat for whoever does it: the device
streams ~750 reports/s and a `println!` per report **will** trip the hidraw
watchdog and will look exactly like "the big encoder killed the daemon". The
print must be one-shot or fire only on a changed byte.

### D4 — F1–F8: mute or solo?

| | |
|---|---|
| **PO** | Mute. "I mute perhaps sixty times in a set and solo perhaps four. The most-used gesture gets the eight easiest buttons." Tap latches, hold is momentary. |
| **Prior art** | Solo, always, on every page; mute on SHIFT+Group. |
| **DEV** | Neutral on taste; notes `zynmixer.toggle_solo` exists and is additive, and that F1–F8 already mute on the shipped, hardware-verified rig. |

**RULING: PO wins, decisively, and it is also the cheapest option on the table.**

F1–F8 are **mute**: tap = latched, hold = momentary. This is what the shipped rig
already does, so it is zero work and zero regression risk.

**Solo moves to the SOLO button, which already emits CC 31 today** (`main.rs:1045`,
DEV-confirmed, zero daemon work):

- **Hold SOLO + tap Fn** → momentary solo of channel *n*. Release and everything
  returns. This is PO's "drop" gesture.
- **Tap SOLO** → latched solo mode; the F row becomes solos until SOLO is tapped
  again. SOLO's own LED lit means "the F row means solo now".
- **SHIFT + Fn** → exclusive solo (clears all others), in pass 2 when SHIFT emits.

**Consequence worth naming, because it changes the build order:** with mute on
the F row, **SHIFT is no longer load-bearing for the prototype.** DEV had SHIFT
as prototype item 2 precisely because mute depended on it. It does not any more.
Combined with SOLO already emitting, **the prototype needs no daemon work at
all** — no Rust, no `git bundle` deploy dance, no re-setting
`"external_pad_leds": true`. That is the single largest risk reduction in this
document and it fell out of a taste argument.

The prior art's SHIFT+Group mute is dropped. Group buttons select and only
select — D9.

### D5 — Lock snapshots

| | |
|---|---|
| **PO** | The #1 want. On a parametric machine a parameter snapshot is a pattern bank, a mixer scene, a filter sweep and an arrangement in one mechanism. Tempo-synced morphing is not a garnish: "recalling a state instantly is a cut; recalling it over four bars is a transition, and transitions are what a live set is made of." Also the only way to recover in front of an audience. |
| **DEV** | Did not scope it at all. |

**RULING: not in the prototype. First item of pass two, ahead of everything
else, exactly as the PO's own tier 2 ranks it. Eight slots, not sixteen.**

DEV costed it on cross-examination: **(a)** instant recall of 16 slots **6–8 h**;
**(b)** bar-synced recall **+2–3 h**; **(c)** N-bar morph **+6–8 h**. So a
morphing 8-slot Lock is roughly two days — real, but not the monster either side
assumed. PO accepted 8 slots to get the morph sooner and confirmed eight
whole-machine states is a full set.

Three findings from the cross-examination that must be in the build spec:

1. **The morph is the risk, not the recall.** A naive re-apply per 100 ms tick is
   10 ticks/s × 8 channels = **80 pattern rewrites per second under `self.lock`** —
   precisely the shape that produced the SIGSEGV at 95 seconds. The guard is one
   rule, not a redesign: **interpolate HITS and ROTATE as floats but write the
   pattern only when the value crosses an integer, and only at a step boundary.**
   HITS 4→11 over 8 bars is then 7 rewrites total. Mixer levels and insert wet
   zctrls interpolate freely on the tick; those are genuinely free.
2. **A morph and a live Turing mutation are two writers to the same pattern.**
   They must be **mutually exclusive per channel** or the race returns by a
   different door. See the arbitration token in §6.
3. **Discrete parameters step at the target bar** and never interpolate: LENGTH,
   DIVIDE, KIT, ROOT, SCALE. Kit changes mean up to 8 LinuxSampler preset loads —
   they need the SFZ work's 150 ms debounce **and** a stagger.

**What a Lock slot contains, agreed explicitly** — PO's demand, and he named the
omission that would kill trust: **mutes and solos**. "Hit 'main' in a breakdown
and nothing comes back in, the recall visibly does nothing and I'm dead in two
seconds." Turing registers are the close second and must also be in. A slot
holds: all generator parameters per channel (drum: hits/rotate/divide/length/velo/
accent/chance/swing; voice: length/divide/random/gate/octave/range/chance/swing),
the Turing register per voice, mixer level and mute per channel, solo state,
insert wet per channel, the ganged FX parameters, root, scale, BPM, and the
selected kit/sample or preset per channel.

**Where it lives:** the **SCENE** button (CC 25, already emitting) is the LOCK
page — semantically the closest legend on the device to "a whole-machine state".
Pads 1–8 are the slots. Hold SCENE + tap a pad = store. Tap a pad = recall,
landing on the bar. Encoder 1 on that page = morph time in bars (0 = cut).

**If interpolation proves expensive, take bar-synced instant recall first.** PO:
"rescue beats transition when exposed."

### D6 — The free zynseq capabilities

DEV found five capabilities nobody had noticed: `setSwingAmount`,
`setPlayChance`, `setNotePlayChance`, `setStutterCount` and per-step `addControl`.
They fill columns the prior art left dead and they contradict the prior art's
claim that per-channel swing "is not representable in zynseq patterns" — that
claim is simply **wrong**.

**RULING on placement — the right-hand pair law, extended:**

> **On the CONTROL page, encoders 7 and 8 are REVERB and DELAY on every channel
> of every type. On the STEP page, encoders 7 and 8 are CHANCE and SWING on every
> channel of every type.**

This is a strictly stronger version of the PO's own §4.2 muscle-memory principle
and it costs nothing: the right hand's two outermost knobs never change meaning
within a page, on any channel, ever.

**This overrides the PO's requested column order**, who asked for drum
`VELO CHANCE SWING RATCHET` and voice `OCTAVE RANGE SWING VELO` with ACCENT
dropped. My scheme drops nothing, puts SWING at the same position on both types
as he asked, and additionally puts CHANCE at the same position on both types. He
loses only the specific ordering, and gains ACCENT back.

**RULING on scope**, following DEV's ranking:

| Capability | Verdict | Cost | Where |
|---|---|---|---|
| `setPlayChance` | **Ship in prototype.** Load-bearing, not a nicety — it is the voice DENSITY knob and it removes the need to rewrite the pattern for density at all, which directly cuts the #1 risk | ~1 h | STEP encoder 7, both types, named `CHANCE` |
| `setSwingAmount` | **Ship in prototype.** Genuinely per pattern therefore per channel (`zynseq.cpp:1683`), and persisted in the `.zss` (`1265-1266`, `1404-1405`, read back `955-956`, `1158-1159`) | ~1 h | STEP encoder 8, both types |
| `setStutterCount` | **Defer to pass 2**, top candidate. Ratchets are the most techno thing in the API but they are per-**step**, so they need a UI decision and a new pad-LED state — design work, not plumbing | ~4–6 h | Pass 2: replaces drum STEP encoder 6 (`ACCENT`) |
| `setNotePlayChance` | **Refuse for the prototype.** Overlaps almost entirely with pattern-level `setPlayChance`, is not declared in the Python wrapper, and inherits the per-step UI problem for near-zero marginal gain | — | Pass 3 at the earliest |
| `addControl` (per-step CC) | **Refuse for the prototype.** Highest ceiling, worst value/hours here: needs an automation-lane UI, a CC-target map per channel, and there is neither screen room nor an LED language for it | — | Pass 3 |

**Swing division:** fix it at 1/16 and give the player one knob — it is the only
swing division anyone wants in techno. But `getSwingDiv` is also per pattern, so
**the prepared snapshot must set it explicitly on every pattern** rather than
trusting the default.

**Lock discipline reminder:** `setSwingAmount` and `setPlayChance` act on the
*currently selected* pattern, so each is "one call" only after a `selectPattern()`
— same lock rules as every other pattern write, and `selectPattern` still never
appears in the poll hot path.

### D7 — Tap = latch, hold = momentary (universal law)

PO asked for it as a universal law with a ~250 ms threshold. DEV did not contest
it. **Granted, and written into the design as a law**, because momentary is how
you play a gesture, latched is how you make a decision, and live techno needs
both from the same button inside the same bar.

Applies to: F1–F8 (mute), SOLO, the verb buttons (pass 2), NOTE REPEAT (pass 2).
**Does not apply to** the three page buttons, which are latch-only and mutually
exclusive — a momentary page is a page you cannot two-hand.

### D8 — Timbre lands instantly, structure lands on the bar

PO's §2.9, uncontested by DEV, and it interlocks with D1 and D5. **Granted as a
law.**

| Instant, continuous, no smoothing | Quantised to the next bar, with the pending value shown |
|---|---|
| Filter, level, sends/wet, drive, gate, velocity, accent, RANDOM, CHANCE, SWING | ROOT, SCALE, DIVIDE, LENGTH, KIT, preset, Lock recall |

DIVIDE and LENGTH are already whole-beat quantised by zynseq
(`getLength() = beats × PPQN`, no `setSequenceLength` in the installed C API), so
this is with the grain, not against it.

### D9 — ERASE

PO: hold-and-target, never a bare press — "in front of people that is a
landmine." Prior art and the shipped rig: bare press clears the selected channel.

**RULING: PO wins.** A bare ERASE press does **nothing**. Hold ERASE + tap a pad
clears that step; hold ERASE + tap a Group clears that channel. Nothing
destructive happens on a single press anywhere on this machine. This is a
deliberate, accepted regression from the shipped rig.

"Clear that channel" on a generator-owned pattern means **set the generator to
silence** (drum: HITS → 0; voice: CHANCE → 0), not just wipe the note list — a
wiped note list is overwritten by the next generator move and the erase would
appear not to have worked.

### D10 — What the prototype needs from the daemon: nothing

Falls out of D3 and D4 and is worth stating as its own decision, because it
reorders DEV's own build plan. **The prototype is driver plus prepared snapshot
only.** Every control it uses already emits today: pages CONTROL 11 / STEP 32 /
ALL 38, Groups A–H 80–87 (already patched), F1–F8 39–46, SOLO 31, Play 1,
Restart 7, Erase 2, Duplicate 29, Scene 25, display arrows 5/6.

DEV's prototype item 2 (emit SHIFT as CC 49) **moves to pass 2** and is folded
into the single ~10-line verb-button patch that also emits SWING and VOLUME. One
Rust deploy instead of two.

---

## 2. The workflow

### 2.1 From power-on to a track that plays

**The snapshot is the machine.** Eight chains, eight sequences, eight colours,
eight names, all present at power-on. Nothing is created at run time; anything
that has to be constructed live is a defect.

| # | Hands | What happens |
|---|---|---|
| 0 | Power on | Group A–H light in their colours. Left screen `A KICK B SNAR C CLAP D CHAT`, right `E OHAT F BASS G LEAD H PADS`. CONTROL is lit — it is home. Nothing plays. |
| 1 | **A**, **STEP**, enc 1 → 4 | Four steps light on the pads. |
| 2 | **Play** | There is a kick. Roughly two seconds have passed. |
| 3 | **D**, enc 1 → 11, enc 2 (ROTATE) until the hats sit off the kick, enc 3 (DIVIDE) → 1/32 | A hurrying hat. |
| 4 | **CONTROL**, enc 1 sweeps KIT, enc 2 sweeps SAMPLE | The drum machine is chosen, not filtered. Four knob moves and one button. |
| 5 | **B**, **C**, **E** — same two pages, same knobs | Channels 2–5 cost seconds because they cost nothing new to learn. |
| 6 | **F**, **STEP** | Same button; the columns are a Turing machine because F is a voice. `LENGTH` 8, `DIVIDE` 1/16, `GATE` 40. |
| 7 | **Turn RANDOM up. Listen. Snap it to zero on the bar you want.** | The line locks, bit-identical, forever. This gesture is the instrument. If the wrap stole the phrase, press **Duplicate** to walk the register back up to four cycles. |
| 8 | **CONTROL** on F | `CUTOFF RESO ENV DECAY` … and encoders 7 and 8 are `REVERB` and `DELAY`, as on every channel of every type. |
| 9 | **G**, **H** | Lead and pads. On PADS, `GATE` 95 and `DIVIDE` 1/4 so it breathes instead of stabbing. |
| 10 | **ALL** | `ROOT`, `SCALE`, `BPM`, `MASTER`, and the four ganged FX columns. One place, once. All three voices follow the root. |
| 11 | **STEP** enc 7/8 per channel | `CHANCE` opens holes in the loop, `SWING` shuffles the hats against a straight kick. |
| 12 | Touchscreen | Save the snapshot. Everything above is in it. **Lock the Turing lines before saving** — a snapshot taken with RANDOM > 0 captures whatever the register happened to hold. |

### 2.2 Mid-set, improvising

Characterised by one fact: both hands are busy and the player is not looking down
for more than half a second at a time.

| Gesture | Hands |
|---|---|
| **Arrangement** | Left hand lives on the F row. Tap F3 out for a bar and back in on the downbeat; *hold* F1 for two beats to drop the kick and it returns the instant you let go. Dozens of times a minute. |
| **Steering** | Tap a group; the whole right hand's meaning changes to that channel. No confirmation, no delay. |
| **Riding** | Right hand on the CONTROL page of the selected channel, on cutoff and the two sends. The delay wet on the lead going 0 → 90 over four bars and back is half the night. |
| **The drop** | Hold **SOLO** + **F1**. Kick alone. Release. Everything back. |
| **Rescue** | Pass 2: hit the "main" Lock pad and the machine walks itself back to a state that works, over four bars, while still playing. |
| **Balance** | Pass 2: hold **VOLUME** and the eight encoders are eight faders under their own eight tabs. Release and you are back on exactly the page you were on. |

Nothing in either list involves loading, saving, browsing, naming, confirming,
scrolling or waiting.

---

## 3. The prototype mapping, in full

Everything below is what gets built first. Nothing here needs a daemon change.

### 3.1 Channels

| Group | Name | Type | Hue | Engine |
|---|---|---|---|---|
| A | KICK | drum | red | LinuxSampler, SFZ drum machine |
| B | SNAR | drum | orange | LinuxSampler |
| C | CLAP | drum | amber | LinuxSampler |
| D | CHAT | drum | yellow-green | LinuxSampler |
| E | OHAT | drum | green | LinuxSampler |
| F | BASS | voice | blue | JC303 |
| G | LEAD | voice | violet | Obxd or Surge XT |
| H | PADS | voice | cyan | padthv1 or ZynAddSubFX |

Drums warm, voices cool, so the seam is visible on the panel. **The roles are a
table in the driver** (`CHANNELS = [...]`), so 5+3, 4+3+spare or 4+4 stays a
config line and never a redesign.

Each chain carries a **post-fader** PlateX2 reverb and a `Gxdigital_delay_st`
delay, placed once in the prepared snapshot. Post-fader means the insert is fed
from `zynmixer:output_NN` and therefore already follows the channel's fader and
its mute — every assumption in the shipped rig survives untouched.

### 3.2 Global controls — identical on every page

| Control | CC | Function | Emits today? |
|---|---|---|---|
| **Group A–H** | 80–87 | Select the channel. Pads, both screens' columns, CONTROL and STEP all follow. Takes effect before the finger leaves the button | yes (patched) |
| **CONTROL** | 11 | Page: what the channel *sounds like*. **Home.** Pressing it while lit does nothing (you are home) | yes |
| **STEP** | 32 | Page: what the channel *plays*. Pressing it while lit → CONTROL | yes |
| **ALL** | 38 | Page: the machine's globals. Pressing it while lit → CONTROL | yes |
| **F1–F8** | 39–46 | **Mute** channel A–H, regardless of selection. Tap = latched, hold (>250 ms) = momentary | yes |
| **SOLO** | 31 | Hold + Fn = momentary solo. Tap = latched solo mode, F row becomes solos until tapped again | yes |
| **Play** | 1 | Start / stop all eight sequences via `setPlayState` on each — **never `TOGGLE_PLAY`** | yes |
| **Restart** | 7 | Every channel to step 0 | yes |
| **Erase** | 2 | **Hold only.** Bare press does nothing. Hold + pad = clear that step. Hold + Group = silence that channel (HITS→0 / CHANCE→0) | yes |
| **Duplicate** | 29 | "Give it back." On a voice: restore the previous Turing register, force RANDOM to 0, rewrite now; repeated presses walk back up to 4 deep. On a drum: restore the previous generator parameter set | yes |
| **Arrows beside the display** | **5 / 6** | Previous / next **sound** for the selected channel — sample within the kit on a drum, engine preset on a voice | yes |
| Everything else | — | **Dark, deliberately.** A dark button is a promise that nothing surprising is behind it | — |

**Do not bind the Page ◀▶ pair (CC 47/48).** The daemon swallows them for its own
page indicators and never emits them. And dump `a2j:...Pads MIDI` with
`jack_midi_dump` before binding any button — the CC 5/6 versus CC 13/14 physical
pairing has bitten this project before.

**Legend wart, accepted and recorded:** *Duplicate* does not read as *undo*. No
legend on this device does. It is the least-wrong available and it does exactly
one thing on every channel type, so it does not violate "every button does one
thing". The alternative — a master arrow (CC 13/14) — was rejected because the
physical pairing is unconfirmed and it would do nothing on a drum channel.

### 3.3 Pads

| State | Behaviour | LED |
|---|---|---|
| **Default (and the only state in the prototype)** | Toggle step *n* of the selected channel's zynseq pattern. Pad velocity sets that step's velocity when toggling it on, so a hard tap is an accent — free, the hardware already reads it | dim = empty · bright = active, brightness scaled by step velocity · **white = playhead** |
| Steps beyond `LENGTH` | dark and inert | dark |
| Hold ERASE + pad | clear that step | — |

**Pattern authority:** the generator owns the pattern. Pad taps edit on top of
it; the next generator move wipes them. No hidden per-step override state, no
third LED colour. On a voice a pad tap toggles whether a step *sounds*, keeping
the pitch the Turing machine put there — which is exactly the rest-editing you
want.

**Pattern length is quantised to whole beats** and always will be. Reachable
lengths are `beats × steps_per_beat`; 1, 5, 7, 11 and 13 are unreachable with the
current divisions. Known and accepted.

Step 0 is the **top-left** pad. LED index for a step is `PAD_OFFSETS[step]` with
`PAD_OFFSETS = [12,13,14,15,8,9,10,11,4,5,6,7,0,1,2,3]`.

### 3.4 CONTROL page — the selected channel's sound

> **The right-hand trio: encoders 6, 7 and 8 are LEVEL, REVERB and DELAY on every
> channel of every type.**

**Drum channel**

| Enc | Panel | Name | Value | Bar | Source |
|---|---|---|---|---|---|
| 1 | L1 | `KIT` | 4-char abbrev | segmented | LinuxSampler preset — 41 SFZ drum machines |
| 2 | L2 | `SAMPLE` | 4-char name | segmented | note within the kit |
| 3 | L3 | `TUNE` | — | — | **greyed, inert.** No source exists |
| 4 | L4 | `DECAY` | — | — | **greyed, inert** |
| 5 | R1 | `FILTR` | — | — | **greyed, inert** |
| 6 | R2 | `LEVEL` | 0–100 | unipolar | `zynmixer.set_level`, engine-independent |
| 7 | R3 | `REVERB` | 0–100 | unipolar | PlateX2 `blend`, capped at ~0.45 of range |
| 8 | R4 | `DELAY` | 0–100 | unipolar | delay wet |

**Voice channel**

| Enc | Panel | Name | Value | Bar | Source |
|---|---|---|---|---|---|
| 1 | L1 | `PRESET` | 4-char name | segmented | chain preset |
| 2 | L2 | `CUTOFF` | 0–127 | unipolar | engine zctrl |
| 3 | L3 | `RESO` | 0–127 | unipolar | engine zctrl |
| 4 | L4 | `ENV` | 0–127 | unipolar | filter envelope amount |
| 5 | R1 | `DECAY` | 0–127 | unipolar | amp decay — **`ATTACK` on the PADS channel** |
| 6 | R2 | `LEVEL` | 0–100 | unipolar | `zynmixer.set_level` |
| 7 | R3 | `REVERB` | 0–100 | unipolar | insert wet |
| 8 | R4 | `DELAY` | 0–100 | unipolar | insert wet |

**Greyed columns are a law, not a wart.** A column whose source does not exist on
that channel draws its name greyed, shows no value and no bar, and its encoder
does nothing. A knob that does nothing and does not admit it is the worst object
on a control surface (PO §4.1). Three greyed columns on the drum CONTROL page is
thin and honest; the fix is pass 3, not a lie now.

### 3.5 STEP page — how the selected channel generates notes

> **The right-hand pair: encoders 7 and 8 are CHANCE and SWING on every channel
> of every type.**

**Drum channel — euclidean**

| Enc | Panel | Name | Value | Bar | Source |
|---|---|---|---|---|---|
| 1 | L1 | `HITS` | 0–*len* | unipolar | euclid onsets |
| 2 | L2 | `ROTATE` | 0–*len*−1 | segmented | euclid rotation |
| 3 | L3 | `DIVIDE` | `1/32 1/16 1/8 1/16T 1/8T` | segmented | `setStepsPerBeat` 8/4/2/6/3 — **lands on the bar** |
| 4 | L4 | `LENGTH` | steps | unipolar | `beats × steps_per_beat` — **lands on the bar** |
| 5 | R1 | `VELO` | 1–127 | unipolar | velocity of generated hits |
| 6 | R2 | `ACCENT` | 0–100 | unipolar | how much louder every *n*-th hit is — driver-side velocity math, free. **Becomes `RATCHET` in pass 2** |
| 7 | R3 | `CHANCE` | 0–100 | unipolar | `setPlayChance` |
| 8 | R4 | `SWING` | 50–75 | unipolar | `setSwingAmount`, div fixed at 1/16 |

**Voice channel — Turing machine**

| Enc | Panel | Name | Value | Bar | Source |
|---|---|---|---|---|---|
| 1 | L1 | `LENGTH` | 2–16 | unipolar | shift-register length — **lands on the bar** |
| 2 | L2 | `DIVIDE` | `1/32 1/16 1/8 1/4 1/16T 1/8T` | segmented | **lands on the bar** |
| 3 | L3 | `RANDOM` | 0–100 | unipolar | per-step bit-flip probability applied **incrementally to the persistent register**, evaluated as the register is clocked through a cycle. **0 = the next rewrite is skipped, so the line you are hearing is locked, bit-identical, forever.** Instant, continuous, no smoothing |
| 4 | L4 | `GATE` | 5–100 | unipolar | note length as % of a step — `addNote` duration |
| 5 | R1 | `OCTAVE` | −2…+2 | bipolar | transpose |
| 6 | R2 | `RANGE` | 1–4 | segmented | spread in octaves |
| 7 | R3 | `CHANCE` | 0–100 | unipolar | `setPlayChance` — the rests. **Never implemented by rewriting the pattern** |
| 8 | R4 | `SWING` | 50–75 | unipolar | `setSwingAmount` |

`ROOT` and `SCALE` are **not** here. They are global, on ALL. Three voices in
three keys is not a feature.

**Voice velocity is fixed at 100 in the prototype** and returns in pass 2 as a
second Turing layer generating velocity — which is strictly better than a knob
(PO tier 3, item 7). This is the one thing the PO asked for on this page and did
not get.

### 3.6 ALL page — the machine's globals

| Enc | Panel | Name | Value | Bar | Notes |
|---|---|---|---|---|---|
| 1 | L1 | `ROOT` | `C` … `B` | segmented | quantises all three voices — **lands on the bar** |
| 2 | L2 | `SCALE` | `MIN MAJ DOR PHR HMIN PENT` | segmented | **lands on the bar** |
| 3 | L3 | `BPM` | 60–200 | unipolar | `libseq.setTempo` |
| 4 | L4 | `MASTER` | 0–100 | unipolar | main mixer strip level |
| 5 | R1 | `REVSIZE` | 0–100 | unipolar | **ganged — broadcast to all 8 plates** |
| 6 | R2 | `REVDAMP` | 0–100 | unipolar | ganged |
| 7 | R3 | `DLYTIME` | `1/16 1/8 3/16 1/4 3/8 1/2` | segmented | ganged; driver computes ms from `getTempo()`, recomputed on the 100 ms tick, never per encoder event |
| 8 | R4 | `DLYFBK` | 0–100 | unipolar | ganged |

**Left = time and key. Right = space.** That split is why the page needs no
header. Global SWING is gone from this page — swing is per channel now (D6).

Also apply `setScale` / `setTonic` to each pattern so the touchscreen editor draws
the right keyboard. Free, persisted, cosmetic — it does **not** quantise incoming
notes; the driver's own quantiser does that.

### 3.7 LED language

| Surface | State |
|---|---|
| **Group A–H** | hue = channel identity (fixed) · brightness = mixer level · **dark = not sounding**, whether muted directly or excluded by someone else's solo · full saturation = selected, others desaturated ~30 % |
| **CONTROL / STEP / ALL** | exactly one lit, always. CONTROL is home |
| **F1–F8** | lit = muted (or soloed while SOLO mode is latched) |
| **SOLO** | lit = latched solo mode; the F row means solo |
| **Play** | lit while transport runs |
| **Pads** | dim = empty step · bright, scaled by velocity = active step · **white = playhead** · dark = beyond LENGTH |
| Everything else | dark, deliberately |

The group LED carries three independent facts on three independent dimensions —
hue = identity, brightness = level, dark = silent — which is why selection cannot
also live there. The **inverted tab is authoritative for selection**; the
saturation cue is a bonus and must be dropped without argument if it reads badly
at low brightness.

**Every LED write is diff-based against `led_cache`** — the daemon has been
flooded off the USB bus once already. The cache must be **cleared** on
`SS_LOAD_SNAPSHOT` or the post-load repaint is suppressed as unchanged. Page LEDs
are derived from the page variable on the existing 100 ms display tick, **never
written at the point of the press**, so the LED and the screen can never disagree.

The daemon's `maschine.json` must keep `"external_pad_leds": true` or it repaints
pads on press/release in its own colour and the first touch destroys the picture.
It is not in git on the Pi — re-set it after every deploy.

---

## 4. Screen sketches

Real geometry, from `maschine_mk2_lib.py` lines 250–259: two panels, **255×64**,
four **64 px** columns each. Tab row 0–12 (**8 characters**), dotted rule at 15,
parameter name at 19 (5×8), value at 30 (**double height, 4 characters**),
indicator bar 52–62. The tab row is on every page, always. Selected tab inverted;
muted tab dashed.

Bars: `[==== ]` unipolar · `[--|--]` bipolar from centre · `[# # . ]` segmented.

### 4.1 CONTROL — drum channel A selected, D muted

```
LEFT SCREEN  (255x64)                      RIGHT SCREEN  (255x64)
+--------+--------+--------+--------+      +--------+--------+--------+--------+
|#A KICK#| B SNAR | C CLAP |:D CHAT:|      | E OHAT | F BASS | G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 KIT      SAMPLE   tune     decay           filtr    LEVEL    REVERB   DELAY
 T808     KICK     ----     ----            ----     0082     0024     0036
 [# . . ] [# . . ]                                   [===== ] [==    ] [===   ]

 #..#  selected      :..:  muted (dashed)      lower case + no bar = greyed, inert
```

### 4.2 CONTROL — voice channel F selected

```
+--------+--------+--------+--------+      +--------+--------+--------+--------+
| A KICK | B SNAR | C CLAP | D CHAT |      | E OHAT |#F BASS#| G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 PRESET   CUTOFF   RESO     ENV             DECAY    LEVEL    REVERB   DELAY
 SUBB     0044     0071     0096            0030     0090     0012     0064
 [# . . ] [==    ] [===== ] [======]       [==    ] [======] [=     ] [===== ]
```

### 4.3 STEP — drum channel A selected

```
+--------+--------+--------+--------+      +--------+--------+--------+--------+
|#A KICK#| B SNAR | C CLAP | D CHAT |      | E OHAT | F BASS | G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 HITS     ROTATE   DIVIDE   LENGTH          VELO     ACCENT   CHANCE   SWING
 0004     0000     1/16     0016            0110     0025     0100     0050
 [=     ] [# . . ] [ . # . ] [======]      [======] [==    ] [======] [      ]

 Every column is live.  No dead knobs on this page.
```

### 4.4 STEP — voice channel F selected, mid-fish

```
+--------+--------+--------+--------+      +--------+--------+--------+--------+
| A KICK | B SNAR | C CLAP | D CHAT |      | E OHAT |#F BASS#| G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 LENGTH   DIVIDE   RANDOM   GATE            OCTAVE   RANGE    CHANCE   SWING
 0008     1/16     0035     0040            -001     2        0075     0058
 [===   ] [ . # . ] [==    ] [===   ]      [--|   ] [# # . ] [===== ] [==    ]

 RANDOM 0035 = the register drifts a little each cycle.
 Snap it to 0000 and the line you are hearing is kept, bit-identical, forever.
```

### 4.5 STEP — voice, locked

```
 LENGTH   DIVIDE   RANDOM   GATE            OCTAVE   RANGE    CHANCE   SWING
 0008     1/16     LOCK     0040            -001     2        0075     0058
 [===   ] [ . # . ] [      ] [===   ]      [--|   ] [# # . ] [===== ] [==    ]

 The value cell reads LOCK, not 0000, so "locked" is a word and not a number
 that could be a coincidence.  4 characters exactly.
```

### 4.6 ALL

```
+--------+--------+--------+--------+      +--------+--------+--------+--------+
|#A KICK#| B SNAR | C CLAP | D CHAT |      | E OHAT | F BASS | G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 ROOT     SCALE    BPM      MASTER          REVSIZE  REVDAMP  DLYTIME  DLYFBK
 A        MIN      0132     0088            0072     0040     3/16     0058
 [# . . ] [# # . ] [===   ] [===== ]       [===== ] [===   ] [ . # . ] [==== ]

 Left = time and key.  Right = space, ganged across all eight inserts.
```

### 4.7 A structure change pending on the bar (D8)

```
 HITS     ROTATE   DIVIDE   LENGTH          VELO     ACCENT   CHANCE   SWING
 0004     0000    >1/8<     0016            0110     0025     0100     0050
 [=     ] [# . . ] [ . . # ] [======]      [======] [==    ] [======] [      ]

 Angle brackets around the value = set, waiting for the bar line.
 They clear the instant it lands, so the player knows it took.
```

### 4.8 Pass 2 only — VOLUME held, the mixer

```
+--------+--------+--------+--------+      +--------+--------+--------+--------+
|#A KICK#| B SNAR | C CLAP |:D CHAT:|      | E OHAT | F BASS | G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 A KICK   B SNAR   C CLAP   D CHAT          E OHAT   F BASS   G LEAD   H PADS
 0100     0082     0074     0000            0066     0090     0058     0044
 [######] [===== ] [====  ] [      ]       [====  ] [======] [===   ] [==    ]

 Every column sits under its own tab, its own F button and its own encoder.
 On this one screen every metaphor on the machine agrees.
```

---

## 5. The extension path

### Pass two — in this order

| # | Item | Cost | Notes |
|---|---|---|---|
| 1 | **Lock snapshots.** SCENE = the LOCK page, pads 1–8 = slots, hold SCENE + pad stores, tap recalls **on the bar**, encoder 1 = morph time in bars | 6–8 h recall · +2–3 h bar-sync · +6–8 h morph | The integer-crossing write guard is mandatory, not an optimisation. Morph and Turing mutation are mutually exclusive per channel. Kit loads debounced 150 ms and staggered |
| 2 | **The verb layer.** One ~10-line daemon patch emitting SHIFT = CC 49, SWING = CC 50, VOLUME = CC 51. **VOLUME held or latched = eight faders. SWING held = eight swings.** SHIFT stays a pure modifier (SHIFT+ERASE clears all, SHIFT+Fn = exclusive solo) | ~2 h patch + ~4 h driver | Deploy by `git bundle` — the Pi has no GitHub auth. Re-set `"external_pad_leds": true` afterwards. Any latched page press must clear the shift flag so a lost release can never strand the player |
| 3 | **RATCHET** via `setStutterCount`, replacing drum STEP encoder 6 (`ACCENT`) | 4–6 h | Needs a per-step gesture and a new pad-LED state. See "must not foreclose" #5 |
| 4 | **Note Repeat** (CC 10, hold + pad + rate knob) and **choke groups** (closed hat kills open hat) | ~1 day | Item 3 partly discharges the Note Repeat ask, so this may shrink |
| 5 | **Big-encoder triage.** Two one-shot `println!`s and a knob turn | 30 min to know | Then 2–4 h if the bytes are in report `0x01`; 1–2 days if a new parse path is needed. **Nothing musical may depend on it until it emits** |
| 6 | **PAD MODE play layer** (CC 27) + **REC** (CC 3) + **GRID** (CC 4) | ~1 week | Also closes the "can I audition a sound with the transport stopped" gap |
| 7 | **Second Turing layer generating velocity**, restoring voice `VELO` as something better than a knob | ~1 day | |

### Pass three — the dream, in order

1. **PERFORM page** — eight encoders assigned from the hardware, each pointing at
   any parameter anywhere. NI's Macro Control idea with the mouse removed. Needs a
   legend decision; no button on the device says "macro".
2. **Continuous morph toward a Lock slot as a knob** — ride halfway into the
   breakdown and back out. The most expressive control imaginable on this machine.
3. **Scoped Lock layers** — a slot that carries only generator parameters, or only
   the mix. Requires "must not foreclose" #2.
4. **Sidechain ducking from channel A.** Blocked by D2 until there is a real bus.
5. **Per-drum tone controls** (`TUNE` / `DECAY` / `FILTER` / `DRIVE`) as LV2s, only
   if gate G2 leaves headroom. Up to 32 `jalv` processes total — probably never.
6. **A true shared reverb bus and delay bus**, only if a measurement finds room.
   Requires core work that is currently refused.
7. `setNotePlayChance`, per-step `addControl` automation, 16-velocity pad mode, pad
   aftertouch → filter, tape-stop / gate / reverse.

### What the prototype must NOT foreclose

This is the price of "prototype first" and it is the part most likely to be
skipped. Every item is cheap now and expensive later.

1. **One state dict, one apply path.** Every mutable parameter lives in a single
   `state[channel][param]` structure, and *every* write — encoder, snapshot
   restore, Lock recall, morph — goes through one `apply(channel, param, value)`
   that also updates the screen model and the LED cache. Lock is then a copy of
   that dict and a morph is a lerp over it. **If encoders write zynseq and zctrls
   directly, pass-2 item 1 becomes a rewrite of the driver rather than a feature.**
   This single constraint is why the decision log ruled Lock out of the prototype
   without fear.
2. **Generator parameters must be separable from mix parameters** inside that
   dict — two named groups, even though nothing uses the distinction yet. Scoped
   Lock layers (pass 3) are otherwise impossible without re-tagging every field.
3. **A per-channel pattern-writer token.** Build the arbitration now, when the
   Turing mutation is the only writer, so that the morph can take it later. Two
   writers to one pattern is the SIGSEGV by a different door.
4. **Encoders 7 and 8 address "the channel's reverb wet" through a per-channel FX
   handle**, never a hard-coded plugin symbol. Swapping insert → shared bus, or
   PlateX2 → MDA Ambience under the degrade path, must then change one function.
5. **The encoder dispatcher must already take (verb, channel, value) internally**,
   even though the prototype only ever passes the current page's column. The verb
   layer is then a dispatch change, not a rewrite. Likewise, leave room for the
   verb's object to be a *step* rather than a channel — PO flagged that once
   per-step chance and ratchets exist, the instinct will be "hold a pad and turn a
   knob", and it should not be designed out.
6. **Channel roles stay a table** (`CHANNELS = [...]`). 5+3, 4+3+spare, 4+4 is a
   config line.
7. **Do not consume CC 49, 50 or 51.** They are reserved for shift, swing and
   volume.
8. **Persist driver state from day one** via `zynthian_ctrldev_base.get_state` /
   `set_state` — including the Turing registers *and* the 4-deep register ring.
   Adding it later means every existing snapshot is missing it.
9. **The screen renderer takes a page dimension from day one**, even with three
   pages. Adding a page must be a dict entry.

---

## 6. Deliberately not built

| Thing | Reason |
|---|---|
| **True FX sends** | 26 mixer strips needed against a hard 16. Raising `MAX_CHANNELS` is realtime C in Zynthian's routing core, +64 JACK ports, and both the snapshot format and the touchscreen mixer assume 16. Permanent upstream divergence for a gain that is inaudible once inserts exist |
| **The shared-bus degrade path** | Turns knob 7 into a toggle wearing a knob's clothes, which breaks the one absolute muscle memory in the machine (D2) |
| **Drum `TUNE` / `DECAY` / `FILTER` / `DRIVE`** | No source. LinuxSampler inherits `_ctrls = []`; FluidSynth CC 74/71 is a proven dead end; an LV2 per drum chain means up to 32 `jalv` processes. KIT and SAMPLE already deliver more character than a filter would. Greyed and honest |
| **Pan on the surface** | Set once, never touched in techno. One tap away on the touchscreen mixer, where it is also visible. PO's own first sacrifice |
| **The big encoder as a dependency** | Not decoded at all today. Triage is cheap (pass 2 item 5) but nothing musical may rest on it until it emits |
| **Encoder capacitive touch** | Not implemented, possibly not in the HID stream. Its only job in NI's software is snapping the screens back to the encoder view, and here the screens never leave it. **The design has no fallback because it has no dependency** |
| **Page ◀▶ (CC 47/48)** | Swallowed by the daemon for its own page indicators. Never emitted |
| **Runtime processor add/remove from the driver** | Everything is a prepared snapshot. `fader_pos` bookkeeping is fiddly enough that the driver must never touch it |
| **Generating notes outside zynseq** | Would lose persistence, the touchscreen editor and pad editing, and would put note timing on a Python thread with no JACK clock |
| **Pattern chaining, song mode, scenes, the arranger** | Replaced wholesale by Lock snapshots, which do the same job with one mechanism on a machine whose patterns are parameters |
| **Navigate / Browse / Sampling / Main / View / Auto Write / Select / Enter** | Nothing in a machine with no scenes, no chaining and no browser needs them. Dark buttons are a promise that nothing surprising is behind them |
| **Chord and arp engines** | The Turing machine is the note generator; an arpeggiator on top is two generators fighting. `ROOT` + `SCALE` quantising everything is all the harmony logic needed |
| **Fixed-velocity pad mode** | Solves a problem this machine does not have — the generator sets velocity and pads accent it |
| **`GHOST`** (a second quieter euclidean layer) | An invention beyond the brief. The columns it would have filled are now live (D6) |
| **Pad pages** | 8 groups × 16 pads is enough, and no LED can show which pad page you are on |
| **A saturation cue for selection** | Kept as a bonus only. The inverted tab is authoritative; drop the cue without argument if it reads badly at low brightness |

---

## 7. Open risks

Ordered by what they can take with them. Each row names the specific measurement
or test that retires it.

| # | Risk | Retire it by |
|---|---|---|
| **G1** | ~~Display tile untested~~ **RETIRED — this was stale information.** The geometry was solved and hardware-verified on 2026-08-09: each screen is **255x64, 1bpp row-major, MSB leftmost, 32 bytes per row**, sent as **8 reports, each a full-width band of 8 rows** (`header = [0xE0|screen, 0, 0, chunk*8, 0, 0x20, 0, 0x08, 0]` + 256 payload bytes). The 128x32-tile-with-both-row-bands model was the WRONG model and is dead. The full rig layout — group tabs, dotted rule, four encoder columns with names, double-height values and indicator bars — renders correctly on the hardware today. Source of truth: `MD/display-investigation.md` FIRST section, and `MaschineMK2_linux` `bbf2a62` | **Nothing to do. Do not spend the hour.** |
| **G2** | **Sixteen new `jalv` processes.** ~480 MB RSS, 16 more JACK graph nodes, and a snapshot load time nobody has measured. The DSP is affordable at 512 × 3; the process count and the load are what will hurt | Build the prepared snapshot, then **measure CPU, RSS, xruns and snapshot load time over a 5-minute run before writing a line of driver code.** Fail thresholds: >10 % of one core, or load past ~15 s → degrade to MDA Ambience / MDA Delay, then to 6 channels. Never to a shared bus (D2) |
| **G3** | **jackd is on the wrong device.** `-d hw:Headphones -r 48000 -p 512 -n 3`. Every CPU and xrun number taken to date — including the ~6 % figure for the shipped rig — is on the Pi's headphone jack, not the Sound Blaster (`hw:S2`, 44.1 kHz) | Move jackd to `hw:S2` **before G2**. Any measurement taken before this is worthless. Also record the numbers the PO asked for: **pad hit → sound** (must be under ~10 ms) and **knob turn → audible change** (under ~30 ms) |
| **R1** | **The lock, and the write burst.** `libzynseq` is not thread-safe and the driver reaches it from three threads; this has already killed the whole Zynthian UI with SIGSEGV, exit 139, ~95 s into a jam. The Turing machine adds a fourth access pattern — a `clear` + 8–16 `addNote` burst at each cycle boundary, three voices over, roughly every 0.6 s at 132 BPM | **A twenty-minute jam with all three voices at RANDOM > 0**, not a two-minute demo — the last bug of this shape took 95 seconds to appear. Design rules, not later fixes: one lock acquisition per burst; `selectPattern()` exactly once per burst and **never** in the poll hot path; clocks-per-step cached so the hot path never calls it |
| **R2** | **`blend` on PlateX2 is a crossfade, not an additive wet** — knob 7 at maximum kills the dry signal | At G2, sweep knob 7 on one channel and measure the dry level. Cap the knob at ~0.45 of plugin range if confirmed. Check the chosen delay plugin has a separate wet level; if not, choose another |
| **R3** | **The kit change may not be a live control.** If sweeping KIT reloads a sampler and costs 200 ms of silence it belongs in "set up at home", not on the performance page | Measure the kit-change time at G2. Above ~200 ms of silence, freeze kits per snapshot and move KIT off the CONTROL page |
| **R4** | **Screen repaints starving the input reader.** Redrawing per input report has already tripped the hidraw watchdog once | Three pages, two panels and a mixer overlay must remain **one diffed repaint per 100 ms tick**. Verify by watching for `watchdog: input stalled, reopened` frequency — every ~8 s is the healthy baseline, more is a regression |
| **R5** | **Snapshot restore rewrites more than expected.** Restoring rewrites every sequence's play mode from the `.zss`, and a LOOPALL sequence shorter than the bar goes RESTARTING then STARTING and falls silent until the next bar sync | **Re-force LOOP play mode after every restore**, not once. **Clear the LED cache on `SS_LOAD_SNAPSHOT`** or the repaint is suppressed as unchanged. Test: load the snapshot mid-transport and confirm all eight channels still loop and all LEDs repaint |
| **R6** | **The Pi's Zynthian is older than the local checkout.** This has broken three times — call arity, `clearPattern`, `getNoteAtIndex` | Audit every new `libseq.*` and zynmixer call against the installed `.so` with `nm -D --defined-only` before writing it. Ten seconds each |
| **R7** | **The big-encoder triage can look like a crash.** ~750 reports/s; a `println!` per report will trip the hidraw watchdog and present exactly as "the encoder killed the daemon" | One-shot prints only, or print only on a changed byte. Budget 30 min, and stop if the daemon destabilises |
| **R8** | **The 4-character value cell.** `T808` reads; `1200` and `1201` for the two SP-1200 banks do not distinguish at a glance | Photograph the CONTROL page with the worst kit names during the first driver deploy. The fix is a wider column at a neighbour's expense, never a smaller font |
| **R9** | **`patch-autoconnect-maschine.py` must be re-run after any Zynthian update**, or the daemon's virtual port never gets a zmip slot and the driver is "Found" but never "Loaded" — the rig then does nothing at all, with no error | Check for the zmip slot after every system update, before blaming the driver |

---

## 8. Summary card

```
GROUP A-H     select channel            F1-F8     MUTE  (tap=latch, hold=momentary)
SOLO + Fn     momentary solo            SOLO tap  latched solo mode
CONTROL       what it sounds like       enc 6/7/8 always LEVEL, REVERB, DELAY
STEP          what it plays             enc 7/8   always CHANCE, SWING
ALL           key, tempo, master, space left = time+key, right = ganged space
PADS          the 16 steps              velocity on the tap = step accent
PLAY all on/off   RESTART all to step 0   ERASE hold + pad/group only
DUPLICATE     give the last line back   <  >  previous / next sound

LAW  timbre lands instantly · structure lands on the bar
LAW  tap = latch · hold = momentary · 250 ms, everywhere
LAW  one channel, one cursor · the inverted tab is the truth
LAW  RANDOM -> 0 keeps the loop you are hearing, bit-identical, forever

PASS 2   LOCK snapshots with bar-synced morph (SCENE + pads)
         verb layer: VOLUME held = 8 faders, SWING held = 8 swings
         RATCHET · Note Repeat · choke · big-encoder triage · PAD MODE

PASS 3   PERFORM page · continuous morph knob · scoped Locks
         sidechain · drum tone controls · a real shared bus
```
