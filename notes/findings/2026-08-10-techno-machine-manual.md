# The Techno Machine — User Manual

**Instrument:** eight-channel generative groovebox
**Brain:** Zynthian on a Raspberry Pi 4
**Surface:** Native Instruments Maschine MK2
**Snapshot:** `016-techno_maschine.zss`
**Date:** 2026-08-10 · prototype (pass one)

This manual documents **what the instrument actually does**, traced to the
driver source (`zynthian_ctrldev_maschine_mk2.py`, `techno_lib.py`,
`maschine_mk2_lib.py`). Where the design documents describe something the code
does not do, it is either omitted or marked in **§11 Not in this version** and
**§13 Known divergences**. Nothing here is aspirational.

---

## Contents

1. [What the instrument is](#1-what-the-instrument-is)
2. [Before you play](#2-before-you-play)
3. [The surface at a glance](#3-the-surface-at-a-glance)
4. [Playing the drums](#4-playing-the-drums)
5. [Playing the voices](#5-playing-the-voices)
6. [Sound and space](#6-sound-and-space)
7. [The ALL page](#7-the-all-page)
8. [Performing](#8-performing)
9. [Saving and recalling](#9-saving-and-recalling)
10. [When something goes wrong](#10-when-something-goes-wrong)
11. [Not in this version](#11-not-in-this-version)
12. [What had to be added to Zynthian to make this work](#12-what-had-to-be-added-to-zynthian-to-make-this-work)
13. [Known divergences between the design and the shipped code](#13-known-divergences-between-the-design-and-the-shipped-code)

---

## 1. What the instrument is

Three sentences hold the whole mental model.

**Eight channels are always alive.** They exist from the moment the snapshot
loads. Nothing is created, added, browsed for or torn down while you play. Five
are drum channels, three are melodic voices:

| Group | Name | Kind | Engine | MIDI ch | Colour |
|---|---|---|---|---|---|
| A | KICK | drum | LinuxSampler (SFZ drum machine) | 1 | red |
| B | SNAR | drum | LinuxSampler | 2 | orange |
| C | CLAP | drum | LinuxSampler | 3 | amber |
| D | CHAT | drum | LinuxSampler | 4 | yellow-green |
| E | OHAT | drum | LinuxSampler | 5 | green |
| F | BASS | voice | JC303 | 6 | blue |
| G | LEAD | voice | Obxd | 7 | violet |
| H | PADS | voice | padthv1 | 8 | cyan |

Drums are warm colours, voices cool, so the seam between the halves is visible
on the panel without reading anything.

**Three pages decide what the eight encoders mean.** CONTROL is what the
selected channel *sounds like*. STEP is what it *plays*. ALL is the machine's
globals — key, tempo, master and the shared space. Exactly one page is lit at
any moment, and CONTROL is home.

**The generator owns the pattern.** You do not draw a beat and then decorate it.
You set generator parameters — hits, rotation, randomness — and the driver
writes the notes into Zynthian's sequencer. Pad taps edit on top of that, and
the next generator move overwrites them. This is deliberate: there is no hidden
per-step override state and no third pad colour to explain.

Everything is sequenced by zynseq, Zynthian's own step sequencer, so patterns
persist in snapshots and the touchscreen pattern editor mirrors exactly what the
pads show.

---

## 2. Before you play

### Power up

1. Power the Pi. Power/connect the Maschine MK2 over USB.
2. Wait for the Zynthian UI on the touchscreen.
3. The MK2 daemon (`maschine-mk2.service`) must be running. If the MK2's
   displays are blank and its buttons are dark, the daemon is not up.

### Load the snapshot

On the **touchscreen**, open Snapshots, bank `000`, and load
**`016-techno_maschine`**.

Do **not** use the webconf Snapshots page's Name field and checkmark. That
renames the selected *bank*; it has destroyed bank `000` once already.

You should see, within about 15 seconds:

- the touchscreen mixer showing **eight strips plus main**
- the MK2's two displays drawing the tab row (`A KICK`, `B SNAR`, …) and four
  encoder columns each
- the eight Group buttons lit in their channel colours

### What "playing" looks like

Press **Play**. The Play button lights, all eight sequences start together, and
a **white pad** sweeps across the selected channel's step grid.

- Group buttons glow in their colour; brightness tracks that channel's level.
- Pads: dim = empty step, bright = active step, white = playhead, dark = beyond
  the pattern's length.
- The left display shows channels A-D and encoder columns 1-4; the right shows
  E-H and columns 5-8.

### If it is silent

Work down this list in order.

| Check | How |
|---|---|
| Is the transport running? | Play button lit? Press **Play**. |
| Is the channel muted? | Its Group button is **dark**. Its tab on the display is **dashed**. Tap its F button to unmute. |
| Is something soloed? | Every non-soloed Group button goes dark. Tap the soloed F button again, or tap SOLO to leave solo mode. |
| Does the channel have any hits? | STEP page, encoder 1 (HITS on a drum). Zero hits is silence. |
| Did you hold ERASE and press a Group? | That sets the channel's generator to silence — see §8. On a **voice** this is not recoverable from the surface; reload the snapshot. |
| Are the mixer strips down? | The snapshot ships strips at **0.19** and main at **0.80**. If MASTER or a LEVEL knob has been swept to zero, bring it back. |
| Is the driver actually loaded? | See §10 — "Found" but not "Loaded" is a known failure. |

---

## 3. The surface at a glance

### Every control the instrument binds

| Control | CC | What it does |
|---|---|---|
| **Pads 1-16** | NoteOn | Toggle a step of the selected channel. Tap velocity becomes the step's velocity. Step 0 is **top-left**. |
| **Group A-H** | 80-87 | Select the channel. Pads, tabs and all eight encoders follow immediately. |
| **CONTROL** | 11 | Page: what the channel sounds like. Home. Pressing it while lit does nothing. |
| **STEP** | 32 | Page: what the channel plays. Pressing it while lit returns to CONTROL. |
| **ALL** | 38 | Page: the machine's globals. Pressing it while lit returns to CONTROL. |
| **Encoders 1-8** | 16-23 | Meaning depends on page and channel kind. See §4-§7. |
| **F1-F8** | 39-46 | **Mute** channel A-H, regardless of which is selected. Solo while SOLO is held or latched. |
| **SOLO** | 31 | Held: the F row is momentary solo. Tapped: latches solo mode — the F row *is* solo until tapped again. |
| **Play** | 1 | Start / stop all eight sequences together. |
| **Restart** | 7 | Every channel jumps to step 0, without stopping. |
| **Erase** | 2 | **Hold only.** Hold + pad clears that step. Hold + Group silences that channel. A bare press does nothing. |
| **Duplicate** | 29 | Undo for a voice: restore the previous Turing register, force RANDOM to 0, rewrite now. Up to 4 deep. Does nothing on a drum. |
| **Arrows ◀ ▶ beside the display** | 5 / 6 | Previous / next **sound** for the selected channel: a sample within the kit on a drum, an engine preset on a voice. |
| Everything else | — | **Dark, deliberately.** A dark button is a promise that nothing surprising is behind it. |

The **Page ◀▶** pair (CC 47/48) is deliberately unbound: the daemon consumes
those buttons for its own page indicators and never emits them.

### The five laws

**L1 — Tap latches, hold is momentary.** Threshold **250 ms**. Applies to F1-F8
and SOLO. The press always acts; the release undoes it only if you held past the
threshold. It does **not** apply to the three page buttons, which are latch-only
and mutually exclusive — a momentary page is a page you cannot two-hand.

**L2 — Timbre lands instantly, structure lands on the bar.** Level, wet, cutoff,
resonance, envelope, decay, gate, velocity, RANDOM, CHANCE and SWING land the
instant you turn them. **ROOT and SCALE** wait, on both channel kinds, and so do
**DIVIDE and LENGTH on a drum**: the value shows in angle brackets (`>1/8<`)
until the channel's own next wrap takes it, so a structure change can never trip
the groove mid-bar. KIT and PRESET land immediately, and so do DIVIDE and LENGTH
**on a voice** — those rewrite the line from the register the voice already
holds rather than regenerating it from euclid, so there is no groove to trip.

**L3 — Nothing destructive happens on a single press.** ERASE is hold-and-target
only. "Clear that channel" means *set the generator to silence*, not wipe the
note list — a wiped list would be written straight back by the next generator
move and the erase would look broken.

**L4 — A knob with no source is greyed and dead.** Greyed reads as a lower-case
name, `----` in the value cell, and no indicator bar. The encoder under it does
nothing at all. Three greyed columns on the drum CONTROL page and one on the
drum STEP page are thin and honest; a knob that lies is not.

**L5 — One channel, one cursor. The inverted tab is authoritative.** The Group
LED carries identity (hue), level (brightness) and silence (dark). Selection is
not on the LED; it is the inverted tab on the display. A **dashed** tab means
the channel is not sounding — muted at the mixer, or silenced by its own
generator (play chance 0 on a voice, HITS 0 on a drum).

**L6 — RANDOM → 0 keeps the loop you are hearing, bit-identical, forever.** Not
approximately. RANDOM at 0 means *skip the next rewrite*, so nothing rewrites the
pattern and nothing can change it.

### Reading the display

Each panel is 255x64 pixels, four 64-pixel columns lining up with the four
encoders below and four buttons above.

```
+--------+--------+--------+--------+   tab row: 8 chars, "A KICK"
|#A KICK#| B SNAR | C CLAP |:D CHAT:|   #..# inverted = selected
+--------+--------+--------+--------+   :..: dashed   = muted
 · · · · · · · · · · · · · · · · · ·    dotted rule
 KIT      SAMPLE   tune     decay       column name, 5x8
 T808     KICK     ----     ----        value, double height, 4 chars
 [# . . ] [# . . ]                      indicator bar (none when greyed)
```

Bar kinds: `[==== ]` unipolar, fills from the left · `[--|--]` bipolar, fills
from the centre · `[# # . ]` segmented, eight discrete blocks.

The value cell is exactly **four characters** and is hard-truncated. Both
displays are repainted only when their contents change, at roughly 5 Hz.

### Encoder feel

All eight encoders are **endless** and have no detents. The driver reads
movement, not position, and parks each encoder back at mid-travel whenever you
select a different channel or change page. Fine parameters (0-100, 0-127) sweep
their whole range across roughly one turn; coarse ones (division, octave, range,
root, scale, reverb type, delay time, swing) move one step per fixed increment
so they do not feel sticky.

Because the encoders are relative, **a parameter's value belongs to the channel,
not to the knob**. Switching channels does not move anything.

---

## 4. Playing the drums

Select A-E. The five drum channels are pure **euclidean** generators.

### The euclidean model

Given a step count and a hit count, hits are spread as evenly as the grid allows
(Bresenham placement — hit *i* lands on `floor(i × steps / hits)`), then rotated.
Hit 0 always lands on step 0 before rotation.

- 4 hits in 16 steps = four-on-the-floor.
- 5 hits in 16 = the classic 5/16 clave.
- 3 hits in 8 = tresillo.

The pattern is regenerated from scratch every time HITS, ROTATE or DIVIDE moves.
Any pad edits you made are wiped at that moment. That is the deal: the generator
owns the pattern.

### Drum STEP page

```
+--------+--------+--------+--------+      +--------+--------+--------+--------+
|#A KICK#| B SNAR | C CLAP | D CHAT |      | E OHAT | F BASS | G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 HITS     ROTATE   DIVIDE   LENGTH          VELO     CHANCE   SWING    ratchet
 0004     0000     1/16     0016            0110     0100     0050     ----
 [=     ] [# . . ] [ . # . ] [======]      [======] [======] [      ]
```

| Enc | Name | Range | Notes |
|---|---|---|---|
| 1 | `HITS` | 0 … step count | Number of euclidean onsets. 0 = silence. |
| 2 | `ROTATE` | 0 … step count−1 | Rotates the pattern forward in time, wrapping. |
| 3 | `DIVIDE` | `1/32 1/16 1/8 1/16T 1/8T` | Step grid. **Regenerates the pattern.** |
| 4 | `LENGTH` | see table below | **Moves in whole beats.** The number on screen is *steps*. |
| 5 | `VELO` | 1-127 | Velocity written into generated hits. Changing it rewrites the pattern. |
| 6 | `CHANCE` | 0-100 | Per-step play probability. |
| 7 | `SWING` | 50-75 | Shuffle. See the warning below. |
| 8 | `ratchet` | — | **Greyed and dead.** Reserved for a later version. |

### LENGTH is measured in beats, displayed in steps

The sequencer can only express a pattern length as a whole number of **beats**
(`length = beats × PPQN`). There is no way to set an arbitrary step count. One
detent of encoder 4 therefore moves the pattern by one beat, and the number on
screen jumps by the division's steps-per-beat — by 2 on 1/8, by 8 on 1/32.

Reachable step counts, exhaustively:

| DIVIDE | steps/beat | Reachable step counts | Default |
|---|---|---|---|
| 1/32 | 8 | 8, 16 | 16 |
| 1/16 | 4 | 4, 8, 12, 16 | 16 |
| 1/8 | 2 | 2, 4, 6, 8, 10, 12, 14, 16 | 16 |
| 1/16T | 6 | 6, 12 | 12 |
| 1/8T | 3 | 3, 6, 9, 12, 15 | 12 |

Lengths of 1, 5, 7, 11 and 13 steps are unreachable. This is a property of the
sequencer, not a bug, and it will not change.

Shortening a pattern keeps the steps inside the new length exactly where they
are and drops only the notes past the new end. Growing it back leaves the new
steps **empty** — it does not restore what a previous shrink discarded. HITS is
re-counted from what actually remains, so encoder 1 resumes from reality.

### Why triplet divisions light only 12 pads

1/16T runs 6 steps per beat over 2 beats = 12 steps. Pads 13-16 go dark and
inert. 1/8T runs 3 per beat over 4 beats = 12 steps by default, and can be
stretched to 15.

Channels at different lengths phase against each other. **That is the
polyrhythm** — a 12-step channel against a 16-step channel is 3:4 and takes four
bars to come back around. Each channel keeps its own length and wraps on it.

### CHANCE, musically

`CHANCE` is the sequencer's per-pattern play probability. At 100 every lit step
plays. At 60 roughly six in ten do, chosen fresh each pass.

This is what you want for hats and claps: **the lit pads do not move**, so the
pattern still reads as itself, but holes open and close and the loop stops
sounding like a loop. It costs zero pattern writes — the driver just sets a
number on the pattern — which is why it is safe to sweep live.

CHANCE at 0 is silence with the pattern intact. That is what ERASE + Group does
to a voice.

### SWING, musically

`SWING` reads **50-75** on the surface: 50 is straight, and higher values push
every second sixteenth later. Swing division is asserted as **1/16** on all eight
patterns at startup and after every snapshot load, rather than trusted to a
default.

> **Read this if you care about exact swing amounts.** The surface number is a
> classic swing percentage, but what reaches the sequencer is `(value − 50) / 50`
> — so the surface's 50-75 spans only **0.0 to 0.5** of the sequencer's 0-1 swing
> range. The indicator bar is drawn as if the range were 0.0-1.0, so **the bar
> reads full at SWING 75 while the sequencer is at half swing**. Use your ears,
> not the bar. Sensible techno shuffle lives around 56-62.

### Pad editing and velocity accents

Tap a pad to toggle that step. The **velocity of your tap becomes the step's
velocity**, so a hard tap is an accent — the hardware already reads it, so it
costs nothing. A soft tap is a ghost note. The pad LED brightness does not
currently scale with velocity; active is active.

Taps are heard immediately: the driver previews the note as you tap.

Steps past the pattern's length are inert — tapping them does nothing.

Hand edits survive until the next generator move on that channel. Turning HITS,
ROTATE, DIVIDE or VELO wipes them. Changing LENGTH does not. Changing the kit or
the sample does not — the driver moves the existing steps onto the new note
rather than regenerating, though it rewrites them all at velocity 100, so kit
changes flatten your accents.

### KIT and SAMPLE

Those are on the CONTROL page — see §6.

---

## 5. Playing the voices

Select F, G or H. These are **Turing machines**: the instrument's central idea.

### The Turing machine, explained

Each voice owns one **shift register** — a ring of bits, 8 bits by default. On
every pass of the playhead the register is clocked one full rotation. As each bit
comes round, it is fed back into the other end; with probability `RANDOM` it is
**flipped** on the way.

The pattern's notes come from reading that register at each step: the register's
value is scaled across `RANGE` octaves, quantised to the global `ROOT` and
`SCALE`, and transposed by `OCTAVE`.

Three consequences, and they are the whole musical point:

**The register is persistent.** It is not a fresh random line each bar. It is the
*same* line, slightly changed. That is why the music has memory.

**Mutation is incremental.** At RANDOM 5-20 you hear roughly one note move per
cycle. The phrase evolves rather than being replaced. A machine that regenerated
the whole line each cycle would be a random-line generator, not a Turing machine,
and the slow drift is the entire value.

**The line is rewritten only at a playhead wrap.** Inside a cycle the line is
bit-constant by construction. Nothing smears mid-bar.

And therefore:

**RANDOM at 0 is an exact lock.** At 0 the driver skips the rewrite entirely. Not
"nearly no change" — *no rewrite happens*, so the loop you are hearing is the
loop you keep, bit for bit, for as long as you leave the knob down. Snap RANDOM
to 0 the instant you hear a phrase you want. The value cell reads **`LOCK`**, a
word rather than a number that could be a coincidence.

### Voice STEP page

```
+--------+--------+--------+--------+      +--------+--------+--------+--------+
| A KICK | B SNAR | C CLAP | D CHAT |      | E OHAT |#F BASS#| G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 LENGTH   DIVIDE   RANDOM   GATE            OCTAVE   RANGE    SWING    VELO
 0008     1/16     0035     0040            -01      2        0058     0100
 [===   ] [ . # . ] [==    ] [===   ]      [--|   ] [# # . ] [==    ] [===== ]
```

Locked, the RANDOM cell reads:

```
 LENGTH   DIVIDE   RANDOM   GATE
 0008     1/16     LOCK     0040
 [===   ] [ . # . ] [      ] [===   ]
```

| Enc | Name | Range | What it does |
|---|---|---|---|
| 1 | `LENGTH` | 2-16 | The **shift register's** length in bits, not the pattern's. See below. |
| 2 | `DIVIDE` | `1/32 1/16 1/8 1/16T 1/8T` | The voice's step rate. The phrase survives the change of speed. See below. |
| 3 | `RANDOM` | 0-100, `LOCK` at 0 | Per-bit flip probability per cycle. **The main knob on this page.** |
| 4 | `GATE` | 5-100 | Note length as a percentage of one step. 5 = stab, 100 = full step. |
| 5 | `OCTAVE` | −2 … +2 | Transpose in octaves. Bipolar bar. |
| 6 | `RANGE` | 1-4 | How many octaves the register's value is spread across. |
| 7 | `SWING` | 50-75 | Same as on a drum, same caveat. |
| 8 | `VELO` | 1-127 | Velocity written into generated notes. |

Every column on this page rewrites the line **from the unchanged register**, so
all eight change how the phrase sounds without changing which phrase it is. That
is what makes the whole page safe at `LOCK`.

**LENGTH (encoder 1)** is the shift register's length in bits, 2 to 16 — not the
pattern's length. A short register repeats sooner and drifts faster at a given
RANDOM; a long one takes many cycles to come round. It is the single most
musical control on the page after RANDOM.

**DIVIDE (encoder 2)** changes the voice's step rate and rewrites the line from
the unchanged register, so the phrase survives the change of speed.

Both **land immediately**, unlike their drum namesakes. Law L2 makes a drum's
DIVIDE and LENGTH wait for the bar because they regenerate the pattern from
euclid and a mid-bar regeneration trips the groove; a voice regenerates from the
register it already has, so the same knob is not disruptive and does not need the
wait. ROOT and SCALE do still wait — on a voice as on a drum.

### LOCK, in performance

The workflow the instrument is built around:

1. Set RANDOM to 20-40 and let the voice fish for a phrase.
2. The moment you hear one you want, snap RANDOM to 0. The cell reads `LOCK`.
3. It repeats exactly, forever, through page changes, channel changes, mutes and
   solos. Only a snapshot reload or an explicit rewrite can move it.

A locked voice still follows a **ROOT or SCALE change** — the line keeps its
shape and changes key, which is the point of a global root.

### Duplicate — "give it back"

The one residual gamble is human reaction time: the wrap fires and replaces the
phrase before your hand lands on the knob.

**Duplicate** (the button legend does not read as *undo*; no legend on this
device does) pops the voice's register ring: it restores the previous register,
forces RANDOM to 0, and rewrites the line immediately. Press it repeatedly to
walk back up to **four registers** — roughly two wraps of reaction time, about
1.8 seconds per cycle at 132 BPM.

Duplicate does nothing on a drum channel, and nothing on a voice whose ring is
empty (one that has never mutated).

### Pad editing a voice

A pad tap on a voice toggles whether that step **sounds**, keeping the pitch the
Turing machine put there. That is exactly the rest-editing you want: punch holes
in the line without touching the melody. The next rewrite restores the full line.

### Rests and density on a voice

There is no CHANCE column on the voice STEP page in this version — the ratified
layout spends column 6 on RANGE. Voice play chance is set in the snapshot. Live
rests come from pad edits.

---

## 6. Sound and space

Press **CONTROL**. This page is what the selected channel sounds like.

> **The right-hand trio never moves.** Encoders **6, 7 and 8 are LEVEL, REVERB
> and DELAY** on every channel of every type. That is the one absolute muscle
> memory in the machine.

### Drum CONTROL page

```
 KIT      SAMPLE   tune     decay           filtr    LEVEL    REVERB   DELAY
 T808     KICK     ----     ----            ----     0019     0000     0000
 [# . . ] [# . . ]                                   [=     ] [      ] [      ]

 lower case + ---- + no bar = the knob is dead, and says so
```

| Enc | Name | What it does |
|---|---|---|
| 1 | `KIT` | Steps through the SFZ drum machines in the **Drum Machines** bank (Roland TR808/909/727/606, LinnDrum, SP-1200, DDD1, XR10, HR16, Simmons …). |
| 2 | `SAMPLE` | Steps the channel's note through the loaded kit's own sound list. |
| 3-5 | `tune` `decay` `filtr` | **Greyed and dead.** LinuxSampler publishes no controllers at all, so there is nothing behind them. |
| 6 | `LEVEL` | 0-100 → the channel's mixer strip fader. |
| 7 | `REVERB` | 0-100 → this channel's insert reverb wet. |
| 8 | `DELAY` | 0-100 → this channel's insert delay wet. |

**KIT is deferred by 150 ms.** The name on screen changes as you turn, and the
kit is loaded only once you stop. Sweeping the whole list therefore costs one
load, not forty-one. On a kit change the channel lands on the **nearest available
note** to the one it had, so it never falls silent, and the new sound is
previewed once so the choice is audible. Kit names are abbreviated to four
characters (`T808`, `1200`, `HR16`); note that the two SP-1200 banks read `1200`
and `1201`, which do not distinguish at a glance.

**SAMPLE stops at both ends** rather than wrapping, so the extremes are findable
by feel. The names come from the `.sfz` file itself — Zynthian's `keymaps.json`
resolves on a synth's preset path and cannot match an SFZ kit, so every tab would
otherwise read "note 36".

The **arrows beside the display** (◀ ▶) do the same job as encoder 2. They follow
the selected channel's kind: on a voice the same two buttons step the engine
preset instead, exactly as encoder 1 does there.

### Voice CONTROL page

```
 PRESET   CUTOFF   RESO     ENV             DECAY    LEVEL    REVERB   DELAY
 SUBB     0044     0071     0096            0030     0019     0000     0000
 [# . . ] [==    ] [===== ] [======]       [==    ] [=     ] [      ] [      ]
```

| Enc | Name | Range | JC303 (BASS) | Obxd (LEAD) | padthv1 (PADS) |
|---|---|---|---|---|---|
| 1 | `PRESET` | — | steps the engine's preset list | | |
| 2 | `CUTOFF` | 0-127 | `_cutoff` | `cutoff` | `DCF1_CUTOFF` |
| 3 | `RESO` | 0-127 | `_resonance` | `resonance` | `DCF1_RESO` |
| 4 | `ENV` | 0-127 | `_envmod` | `filterenvamount` | `DCF1_ENVELOPE` |
| 5 | `DECAY` | 0-127 | `_decay` | `decay` | `DCA1_ATTACK` |
| 6-8 | `LEVEL` `REVERB` `DELAY` | 0-100 | as above | | |

The 0-127 on the surface is mapped linearly onto whatever range each engine's
control actually has. Note that column 5 is **attack** on PADS, not decay — a
pad wants its front edge shaped, not its tail.

These symbols were measured off the live chains, not read from a config flag. No
column on the voice CONTROL page is greyed: all three engines publish all four.

**PRESET is deferred by 200 ms**, and the ◀ ▶ arrows beside the display drive the
same stepper on a voice. Both only move a number and arm a deadline; the load
itself happens on the playhead thread. This is not a nicety — a preset load talks
to the engine over a socket and can block for seconds, and doing it on the MIDI
thread, which holds the driver's lock for the whole event, **froze the entire
instrument** and needed a restart. The name on screen changes as you step, and
only the value you stop on is loaded.

### The sends, and why the dry survives

Each of the eight channels carries two **post-fader insert processors**:

```
   sampler / synth  →  mixer strip (fader, pan, mute)  →  TAP Reverberator  →  TAP Stereo Echo  →  main
```

Post-fader means the inserts are fed from the mixer strip's output, so they
already follow the channel's fader **and its mute**. Muting a channel kills its
reverb and delay with it.

Both plugins were chosen for one measured property: their wet control is a **true
wet level**, not a dry/wet crossfade. The dry path passes at unity and is set
explicitly in the snapshot. Sweep REVERB from 0 to 100 and the dry signal is
still there at exactly the same level at the top — you are adding wet, not
trading dry away. This is why encoders 7 and 8 behave like sends even though they
are technically inserts, and the contract holds on every channel of both types.

**The wet knobs are linear in decibels.** 0-100 on the surface maps onto
−70 dB … +10 dB:

| Knob | Wet level | Reads as |
|---|---|---|
| 0 | −70 dB | off |
| 25 | −50 dB | inaudible |
| 50 | −30 dB | barely there |
| 75 | −10 dB | present |
| 88 | 0 dB | equal to dry |
| 100 | +10 dB | drowning |

Plan your sweeps accordingly: the musically useful travel is roughly **60 to
100**, and the bottom half of the knob is a fade-out tail. The classic gesture —
delay wet on the lead going 0 to 90 over four bars and back — works, but the
first two bars of it are nearly silent.

The delay's two channels are ganged, so encoder 8 moves the left and right echo
levels together.

Both knobs are live on drums as well as voices, with no exception. The wet is a
*plugin* control, not an *engine* control, so LinuxSampler's empty controller
list — the thing that killed tune, decay and filter on the drum page — cannot
reach it.

### Gain staging

The snapshot ships channel strips at **0.19** and main at **0.80**. That is not
arbitrary. Both inserts pass dry at unity, as an insert must, and a single
sampler channel peaks at 1.24 before the mixer; eight of them summed to 2.92 on
the main bus — nearly three times full scale. The attenuation lives on the
strips, and main sits at 0.80 so the MASTER knob has travel in both directions.

Opening reverb and delay adds level on top of that, so if you sweep several wets
up at once, watch the main meter.

---

## 7. The ALL page

Press **ALL**. Left half = time and key. Right half = space, ganged across all
eight channels. That split is why the page needs no header.

```
+--------+--------+--------+--------+      +--------+--------+--------+--------+
|#A KICK#| B SNAR | C CLAP | D CHAT |      | E OHAT | F BASS | G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 ROOT     SCALE    BPM      MASTER          REVSIZE  REVTYPE  DLYTIME  DLYFBK
 A        MIN      0132     0080            0025     0003     1/8      0035
 [# . . ] [# # . ] [===   ] [===== ]       [==    ] [# . . ] [ . # . ] [==    ]
```

| Enc | Name | Range | What it does |
|---|---|---|---|
| 1 | `ROOT` | `C` … `B` | Tonic for all three voices. **Lands on the bar.** |
| 2 | `SCALE` | `MIN MAJ DOR PHR HMIN PENT` | Scale for all three voices. **Lands on the bar.** |
| 3 | `BPM` | 60-200 | Sequencer tempo. |
| 4 | `MASTER` | 0-100 | Main mixer strip level. |
| 5 | `REVSIZE` | 0-100 | Reverb decay, 0-10000 ms — **ganged to all eight reverbs.** |
| 6 | `REVTYPE` | 0-42 | Reverb **room index**, not a percentage — ganged. |
| 7 | `DLYTIME` | `1/16 1/8 3/16 1/4 3/8 1/2` | Musical delay division — ganged. |
| 8 | `DLYFBK` | 0-100 | Delay feedback, 0-100 — ganged. |

### ROOT and SCALE land on the bar

Turn either and the value shows in angle brackets — `>A<`, `>MIN` — while it is
pending. Each voice takes the new key at its **own next playhead wrap**, and the
brackets clear when the last of the three has taken it, so you know it landed.

Locked voices follow too: the line keeps its shape and changes key.

Voices in three different keys is not a feature, which is why these are global
and not on the voice STEP page.

Scales available: `MIN` natural minor, `MAJ` major, `DOR` dorian, `PHR` phrygian,
`HMIN` harmonic minor, `PENT` minor pentatonic. Notes are generated around MIDI
36 (C2) before OCTAVE is applied.

### REVSIZE is a decay time

0-100 maps linearly onto **0 to 10000 milliseconds** of reverb decay. The
shipped value is 25 = 2500 ms. Small moves at the bottom of the knob are large
musical changes; the top of the knob is cathedral territory.

### REVTYPE is an index into 43 rooms, not a percentage

This is the one column that does not behave like a level. TAP Reverberator has no
damping control, so this column addresses its **reverb type** — 43 distinct room
models. The value written is the raw index, unscaled. `0003` means room number 3,
not 3%. Rooms adjacent in the list can sound wildly different, and there is no
way to preview one from the surface. Find the two or three you like and note
their numbers.

### DLYTIME tracks the tempo

The delay plugin takes milliseconds, so the driver converts your musical division
against the live tempo. It is recomputed on the display tick and pushed only when
it actually moves — never per encoder event and never per audio callback. Change
BPM and every delay follows within about 200 ms, without a click.

Delay time is clamped at the plugin's 2000 ms ceiling, so `1/2` at very slow
tempos stops tracking.

### Why space is ganged

One set of reverb and delay parameters drives all eight instances. Identical
character in eight boxes is most of the way to a coherent space. Only the
per-channel **wet** amounts differ, on encoders 7 and 8. Per-channel divergence
is a later opt-in and is not built.

### Encoders read the live value

`BPM`, `MASTER` and `LEVEL` display values read from the sequencer and the
mixer, and they increment that same live value. Move a fader on the touchscreen
and the next encoder turn continues from where the fader actually is, without
jumping.

---

## 8. Performing

### Mute — F1-F8

F1-F8 mute channels A-H **regardless of which channel is selected**. F3 always
mutes CLAP. This is the gesture you use sixty times a set, so it gets the eight
easiest buttons.

- **Tap** (under 250 ms) — latches. The channel stays muted until you tap again.
- **Hold** (over 250 ms) — momentary. Muted while held, back on release.

Both from the same button inside the same bar: momentary is how you play a
gesture, latched is how you make a decision.

The mute is on the **mixer strip**, not the sequencer track. That means it is
saved in the snapshot, it shows on the touchscreen mixer, and — because the FX
inserts are post-fader — **it cuts the channel's reverb and delay tail too**
rather than letting it ring out.

An F button is **lit when its channel is muted**.

### Solo — SOLO + F

- **Hold SOLO** and press an F button: momentary solo, exactly as long as you
  hold the F button.
- **Tap SOLO**: latches solo mode. The whole F row now means solo until you tap
  SOLO again. The SOLO button is lit while the mode is latched.

Solo is **additive**, not exclusive: soloing a second channel adds it to the solo
group rather than replacing the first. Every non-soloed Group button goes dark.

To get out: unsolo each soloed channel, or tap SOLO to leave solo mode (the F row
returns to showing mutes; the solos themselves stay until cleared).

### Erase — hold only

A bare press of ERASE **does nothing at all**. In front of people, a
single-press channel-clear is a landmine.

- **Hold ERASE + pad** — clears that step. A pad that is already empty is left
  alone rather than toggled on.
- **Hold ERASE + Group** — silences that channel. On a **drum** that means HITS
  → 0 and an immediate rewrite. On a **voice** that means play chance → 0.

Both set the *generator* to silence rather than wiping the note list, because a
wiped list is written straight back by the next generator move and the erase
would appear not to have worked.

On a **voice** the gesture toggles: ERASE + Group silences it, and ERASE + the
same Group brings it back to full play chance. The voice STEP page has no CHANCE
column, so a one-way silence would have needed the touchscreen to undo — not
something you reach for mid-set. On a **drum** it is reversible the obvious way:
turn HITS back up.

Holding ERASE and pressing a Group button does **not** select that group.

### Transport

**Play** starts or stops all eight sequences together. The target state is
decided once from whether anything is running, then applied to all eight, so they
can never drift into opposite states. LOOP play mode is re-forced on every start.
The Play button is lit while anything runs.

**Restart** jumps every channel's playhead to step 0 without stopping. Use it to
re-align channels that have phased apart, or to drop back on the one.

### What the LEDs tell you at a glance

| Surface | Meaning |
|---|---|
| **Group A-H** | Hue = channel identity, fixed. Brightness = that channel's mixer level. **Dark = not sounding** — muted directly, or excluded by someone else's solo. A channel with no chain sits at a flat mid brightness. |
| **CONTROL / STEP / ALL** | Exactly one is lit, always. Derived from the page variable on the render tick, never written at the press, so the LED and the display can never disagree. |
| **F1-F8** | Lit = that channel is muted. While SOLO is held or latched: lit = that channel is soloed. |
| **SOLO** | Lit = solo mode is latched and the F row means solo. |
| **Play** | Lit while anything is running. |
| **Pads** | Dim = empty step · bright = active step · **white = playhead** · dark = beyond the pattern's length. |
| Everything else | Dark, deliberately. |

Selection is **not** on the Group LEDs — they already carry three independent
facts on three independent dimensions. The inverted tab on the display is
authoritative.

Every LED write is diffed against a cache, so only actual changes go on the USB
bus. The device has been flooded off the bus once already by unthrottled writes.

---

## 9. Saving and recalling

Save from the **touchscreen**: inside a bank, the first entry is
**"Save as new snapshot"**. Do not use webconf's Snapshots page Name field — it
renames the bank.

### What a snapshot carries

| Data | Where it lives | Restored? |
|---|---|---|
| Steps, division, pattern length per channel | zynseq pattern | yes |
| Play chance and swing per channel | zynseq pattern | yes |
| Mixer level, pan, mute, solo | zynmixer strip | yes |
| Insert reverb and delay wet, and all ganged FX parameters | plugin controls | yes |
| Kit / sample / preset per channel | chain preset | yes |
| **Every voice's Turing register** | driver state | yes |
| **Every voice's 4-deep undo ring** | driver state | yes |
| Voice LENGTH, RANDOM, GATE, OCTAVE, RANGE, VELO | driver state | yes |
| ROOT, SCALE, BPM, MASTER, REVSIZE, REVTYPE, DLYTIME, DLYFBK | driver state | yes |
| Current page and selected channel | driver state | yes |

The driver's own state rides in the snapshot under the MIDI device's
`ctrldev_state`. This was built in from day one deliberately: adding it later
would leave every existing snapshot silently missing it.

**The registers matter.** A snapshot without them restores a machine that plays
*different music*. With them, a locked voice comes back playing the exact line it
had — the driver rewrites every voice's pattern from its restored register the
moment the state is applied, because a locked voice will never write it on its
own.

### What it does not carry

- **Euclidean rotation.** Rotation cannot be recovered from a pattern, so it
  resumes at whatever the driver last set. HITS, DIVIDE and LENGTH are re-derived
  from the pattern itself and are correct.
- **Which kit index each drum channel was on.** The *preset* is restored
  correctly by the chain; the driver re-derives the index from the processor's
  loaded preset name.
- **Solo/mute momentary state.** Nothing held survives a reload, by definition.

### What happens on a reload

The driver drops every cache, re-reads the parameters back out of the sequencer,
re-asserts swing division 1/16 on all eight patterns, clears the LED cache and
repaints everything. Clearing the LED cache is required, not an optimisation:
without it the post-load repaint would be suppressed as "unchanged" and the
device would keep showing the previous snapshot's picture.

LOOP play mode is re-forced on the next transport start and on every pattern
write. Press **Play** once after a load to be certain.

---

## 10. When something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| Buttons do nothing, displays blank, but Zynthian is up | The driver is **"Found" but never "Loaded"** — Zynthian gave the daemon's virtual port no zmip slot. Happens after any Zynthian system update. | Re-run `~/zynth-docs/tools/patch-autoconnect-maschine.py`, then restart Zynthian. Confirm with `journalctl -u zynthian \| grep -i ctrldev` — you want **Loaded**, not just Found. |
| A voice goes quiet and looks broken; the engine is fine | Three causes, in the order to check them. **Play chance 0** — set by ERASE + Group, which on a voice is a toggle; its tab draws **dashed**. **GATE too short for the division** — at 1/32 a 5% gate is a few milliseconds, and a pad patch never gets loud. **A preset with no output** — some padthv1 bank entries are silent. | Press ERASE + that Group again. Raise GATE and slow DIVIDE. Step the preset with encoder 1. To tell them apart: hold a note into the engine's own MIDI input and watch its output — if it sounds there, the engine is not the problem. |
| First pad touch destroys the per-channel colours; pads go dark red | The daemon's `"external_pad_leds": true` flag is missing, so the daemon repaints pads itself on press and release. | Restore it in the daemon's `maschine.json` and restart the daemon. **It is not in git on the Pi** — a `git reset --hard` there wipes it, so re-set it after every deploy that touches the daemon. |
| A channel is silent after a snapshot load, then comes back on the next bar | LOOP play mode was rewritten from the `.zss`. A LOOPALL sequence shorter than the bar goes RESTARTING at its own end, then STARTING — and STARTING does not clock its tracks. | Press **Play** — the driver re-forces LOOP on every transport start. If it recurs, check the snapshot's stored play modes. |
| Phantom drum sounds when you tap pads, on top of the real ones | A **stale JACK route** left by an earlier debugging session. `zynautoconnect` only tears down connections it made itself, and jackd outlives a Zynthian restart. | `jack_lsp -c \| grep -A3 "Pads MIDI"` — it must show exactly **one** `devN_in`. Disconnect the extra. |
| Input dies after a few seconds, then recovers | Kernel hidraw fault. The daemon has a close-then-reopen watchdog for exactly this. | Nothing to do. `watchdog: input stalled, reopened …` in the journal every ~8 s is **healthy**. Much more often than that is a regression. |
| Encoders feel dead or pinned at one end | An encoder ran into the daemon's 0-127 clamp. | Select a different channel and come back, or change page — both re-park every encoder at mid-travel. |
| A voice suddenly plays one repeated note | **A regression.** Two paths used to do this — the voice's DIVIDE knob regenerating a euclidean drum pattern over the line, and the ◀ ▶ arrows resolving a GM percussion fallback — and both were fixed on 2026-08-11: `_verb` branches on channel kind, and the arrows step the preset on a voice. If it happens now, something reintroduced a drum write on a melodic channel. | Nudge OCTAVE, GATE, RANGE or VELO by one step to rewrite the line from the register, or turn RANDOM up and wait a cycle. Then report it — the surface should no longer be able to cause this. |
| The whole Zynthian UI dies (SIGSEGV, exit 139) | Unsynchronised access to the sequencer library from multiple threads. Every path in this driver holds a lock; if this appears, something has regressed. | Restart Zynthian, and report it — this took 95 seconds to appear last time, so a short test will not reproduce it. |
| Screens stutter, input feels laggy | Repaints starving the input reader. | Both displays are supposed to be one diffed repaint per tick. Watch the watchdog frequency in the journal. |
| Mix is distorting with several wets open | Both inserts pass dry at unity and the wets add on top. | Pull MASTER down, or the channel strips. Design headroom is main at 0.80 with strips at 0.19. |

### Health check commands

```bash
ssh root@192.168.2.123 'journalctl -u zynthian --since -3min | grep -iE "ctrldev|maschine|traceback|error"'
ssh root@192.168.2.123 'jack_lsp | grep -c TAP'          # expect 64 (16 instances x 4 ports)
ssh root@192.168.2.123 'jack_lsp -c | grep -A3 "Pads MIDI"'
ssh root@192.168.2.123 'journalctl --since -20min | grep -c "watchdog: input stalled, reopened"'
```

---

## 11. Not in this version

Deliberately deferred. Each is cheap now and expensive later, and each is
designed for rather than designed around.

| Feature | Status |
|---|---|
| **Lock snapshots** — 8 slots on SCENE, hold to store, tap to recall on the bar, with a morph time | Pass two, first item. The driver already routes every write through one state dict specifically so a Lock is a copy of that dict and a morph is a lerp over it. |
| **RATCHET** | Drawn on the drum STEP page as a greyed `ratchet` column so the page's shape does not move when it lights up. Pass two. |
| **The verb layer** — hold VOLUME for eight faders, hold SWING for eight swings | Needs one small daemon patch to emit SHIFT/SWING/VOLUME. Pass two. CC 49, 50 and 51 are reserved for it. |
| **Voice CHANCE on the surface** | Column 6 is spent on RANGE. Returns in pass two when RATCHET frees the drum page's column 8. Set per voice in the snapshot; live rests come from pad edits. |
| **Exclusive solo** | Solo is additive. Exclusive solo needs SHIFT, which does not emit yet. |
| **Per-channel FX character** | Reverb and delay parameters are ganged across all eight. Only the wets differ. |
| **A true shared reverb/delay bus** | Refused for this version — see §12. No shared tail, and no duckable return, so sidechaining the reverb against the kick is unavailable. |
| **Drum tune / decay / filter** | Greyed and honest. LinuxSampler publishes no controllers; FluidSynth's CC 74/71 is a proven dead end. KIT and SAMPLE deliver more character than a filter would. |
| **Pan on the surface** | Set once, never touched in techno. One tap away on the touchscreen mixer, where it is also visible. |
| **Note Repeat, choke groups, pad pages, PAD MODE play layer** | Pass two. |
| **Song mode, scenes, the arranger, pattern chaining** | Replaced wholesale by Lock snapshots in pass two — one mechanism on a machine whose patterns are parameters. |
| **The big encoder** | Not decoded at all in the daemon. Nothing musical rests on it. |

---

## 12. What had to be added to Zynthian to make this work

Zynthian is a synth and effects host with a step sequencer bolted on. It is not a
groovebox. This section is the honest account of what was added, what was chosen,
and what Zynthian refused to allow.

### A ctrldev driver

A **ctrldev driver** is Zynthian's plug-in point for a control surface. It is a
Python class in `zyngine/ctrldev/` that Zynthian loads when it sees a matching
MIDI device. The driver receives that device's raw MIDI events before anything
else touches them, and it can reach directly into the running instrument — the
chain manager, the mixer, the sequencer library, the signal bus. The manager
globs every `*.py` in that directory and reads a `dev_ids` attribute off each
one, so *every* module in the folder, helper or not, must carry the attribute or
the whole UI crash-loops on startup.

The Techno Machine is one such driver:
`zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`. It claims the Maschine's pad
port exclusively (`unroute_from_chains = True`) so that pads never reach a chain
by themselves — pad previews are played explicitly through the sequencer's own
`playNote`, which is what the touchscreen pattern editor uses.

Inside the driver:

- **One state dict, one apply path.** Every write — encoder, snapshot restore,
  Duplicate — goes through a single `apply(channel, param, value)` function,
  which also updates the screen model and the LED cache. This is why Lock
  snapshots could be deferred without fear: a Lock is a copy of that dict.
- **A page dimension from day one.** The column model is a table keyed by
  `(page, channel kind)`, so adding a fourth page is a dict entry, not a rewrite.
- **The encoder dispatcher takes a verb.** Internally an encoder move becomes
  `(verb, channel, value)`, even though the prototype only ever passes the
  current page's column, so pass two's verb layer is a dispatch change.
- **Per-channel FX handles.** Encoders 7 and 8 address "this channel's reverb
  wet" by walking the chain for the right processor, never by a hard-coded plugin
  symbol. Swapping the plugin changes one function.
- **A 30 Hz poll thread.** The playhead, the Turing wraps, the deferred kit
  loads and the tempo-tracked delay time all run here.

### `techno_lib.py` — pure, testable logic

Everything generative and everything presentational lives in a second module
with **no Zynthian imports, no I/O and no state**: the Turing shift register and
its mutation, the undo ring, register-to-pitch quantisation, the scale table,
the channel role table, the FX role maps, the tempo-to-milliseconds conversion,
and the page/column model for all three pages on both channel types.

That module is unit-tested on a laptop with no Pi and no hardware. The greyed
columns, the `LOCK` word, the pending brackets, the four-character value cells
and the invariant that *RANDOM at 0 produces a byte-identical register forever*
are all tested there rather than eyeballed on stage.

Channel roles are a table (`CHANNELS`), so 5 drums + 3 voices, 4+4, or a degrade
to six channels is a config line rather than a redesign.

### The prepared snapshot, with sixteen post-fader inserts

Nothing is constructed at run time. The snapshot ships eight chains on MIDI
channels 1-8, and **each one carries two post-fader insert processors** — a TAP
Reverberator followed by a TAP Stereo Echo. Sixteen plugin instances in total.

Post-fader placement matters: the insert is fed from the mixer strip's output, so
it inherits the channel's fader and its mute automatically, and every assumption
the shipped drum rig made about the mixer strip survives untouched.

Both inserts have their **dry level set explicitly** in the snapshot. Their
defaults are not the useful value — the TAP plugins ship at −4 dB dry, which was
quietly costing every channel about 8 dB, and one candidate reverb defaults its
dry port to near zero. A default that happens to work is still a default.

Swing division is asserted as 1/16 on all eight patterns by the driver at
startup and after every load, because swing division is a per-pattern property
and trusting its default is exactly the kind of assumption that bites.

### Why TAP Reverberator and TAP Stereo Echo, and why the cheap candidates lost

The whole design rests on one contract: **encoders 7 and 8 are sends on every
channel, forever.** A knob that turns the dry signal down as it turns the wet up
is not a send; it is a dry/wet morph, and it breaks the muscle memory the machine
is built on.

Every candidate was measured, not assumed. A full-scale impulse was rendered
through each plugin; because a wet path always runs through a delay line, the
first output sample can only be the dry path, so the dry gain is measurable
directly while the wet is swept from minimum to maximum.

| Plugin | Wet port | Dry at wet MAX | Verdict |
|---|---|---|---|
| **TAP Reverberator** | `wetlevel` (dB) | 100% | **true wet level** |
| **TAP Stereo Echo** | `lecholevel` / `recholevel` (dB) | 100% | **true wet level** |
| TAL Reverb 2 / 3 | `wet` | 100% | true wet level, but ~9-10% of a core each |
| **MDA Ambience** | `mix` | **0%** | **crossfade — rejected** |
| **MDA DubDelay** | `fx_mix` | **0%** | **crossfade — rejected** |
| **CAPS PlateX2** | `blend` | **0%** | **crossfade — rejected** |
| MDA Delay, swh `lcrDelay`, `bolliedelay` | various | 0% | crossfade — rejected |
| swh `gverb`, DISTRHO MaGigaverb | — | — | true sends and cheap, but **mono in** — rejected |

The two plugins the design originally picked as the cheap starting point — MDA
Ambience and MDA DubDelay — turned out to be crossfades, so the "start cheap,
upgrade into headroom" plan had to start somewhere else entirely.

The mono-in reverbs are worth spelling out: `gverb` was the cheapest true send on
the list at about 2% of a core, and `MaGigaverb` next at 3.7%. Both are one audio
input. Because the insert sits **after** the mixer strip's pan, a mono input
would collapse every channel's pan to centre. That removed the two cheapest
options and left TAP Reverberator, at about 6.4% of a core, as the only
affordable stereo reverb with a genuine wet level.

A further finding worth keeping: **the structural marker to look for is a
separate `dry` port, not the word "wet".** Several true sends do not use the word
at all.

### The measured cost

| | |
|---|---|
| JACK DSP load, five minutes, eight channels playing, all sixteen inserts fed | **mean 17.5%, p95 18.0%, max 18.6%** |
| The sixteen FX processes | 28.2% of one core = 7.1% of the four-core budget |
| Memory actually consumed by the sixteen inserts | 177 MB |
| **xruns** | **zero**, in every run |
| Startup, sixteen instances | 3.8 s warm, 10.8 s cold |

One structural fact reshaped the budget: **sixteen plugin-host processes cost
16.5% of a core doing literally nothing.** That is the per-process floor of the
LV2 host plus its JACK client, about 1% per process before any DSP at all. The
original pass/fail threshold — "no more than 10% of a core for the sixteen
inserts" — was unreachable by architecture and had to be re-baselined onto JACK
DSP load plus zero xruns.

A second fact is worth remembering when anyone re-measures: **with real signal
the inserts cost 2.4× less than with their inputs unconnected.** A reverb
integrating silence is more expensive than one integrating music — almost
certainly denormals. Measure under load, never idle.

> **Caveat.** Every absolute figure above was taken with JACK on the Pi's
> built-in headphone output at 48 kHz, not on the Sound Blaster at 44.1 kHz.
> Relative plugin costs are card-independent and the plugin choice stands; the
> headroom figure must be re-measured once the interface is connected.

### No Rust, no daemon change — at all

The Maschine MK2 is driven by a separate Rust HID daemon, and touching it means a
cross-compile, a manual bundle-based deploy to a Pi with no GitHub access, and
re-setting an untracked config flag afterwards. **None of that was needed.**

Every control the Techno Machine binds already emitted CC before this project
started. That fell out of two design decisions: putting mute on F1-F8 (which the
drum rig already did) and putting solo on the SOLO button — which together took
SHIFT off the critical path. It is the single largest risk reduction in the
design, and it reordered the whole build: snapshot first, then measurement, then
driver.

The daemon does gain one responsibility it already had: it exposes a small OSC
drawing API, so the screen layout lives in the Python driver rather than in Rust.

### Gain staging on the mixer strips

Both inserts pass dry at unity, as an insert must. That exposed how hot the mix
already was: one sampler channel peaks at 1.24 before the mixer, and eight of
them summed to 2.92 on the main bus — nearly three times full scale.

The sampler's own volume control is not the fix — taking it from 96 to 40 moved
the bus peak by about 1.5 dB. The **mixer strips** are, which is where this rig
keeps volume anyway. The faders are linear in amplitude, so gain moves freely
between strips and master. Strips sit at **0.19**, main at **0.80**, which lands
the bus peak near 0.69 — about 3 dB of headroom — and leaves the MASTER knob
travel in both directions.

### The constraints Zynthian imposed, and how they shaped the instrument

These are not complaints. Each one visibly changed the design.

**Sixteen mixer strips, hard.** Zynthian's mixer has `MAX_CHANNELS 17` with strip
16 reserved for main, so sixteen are usable and the limit is compiled in. A
correct send-tap topology would need 8 channels + 16 taps + 2 returns = **26
strips**. Raising the ceiling means realtime C in the routing core that every
Zynthian chain uses, 64 more JACK ports, and both the snapshot format and the
touchscreen mixer assume 16. **True sends were therefore impossible**, and the
answer was sixteen post-fader inserts instead. A shared FX bus fed by
per-channel routing on/off was proposed as a fallback and withdrawn: chain
routing is on/off only with no per-destination gain, so knob 7 would have become
a toggle wearing a knob's clothes.

The insert satisfies the contract literally, and for a non-obvious reason: **the
wet parameter is a plugin control, not an engine control**, so the next
constraint cannot reach it.

**LinuxSampler exposes no controllers at all.** The sampler engine inherits an
empty controller list — it is "enabled", it works, it makes sound, and it
publishes nothing. That is why volume and pan on the drum channels come from the
mixer strip rather than the engine, why the drum CONTROL page has three greyed
columns instead of tune/decay/filter, and why the greyed-column convention exists
in the first place. It is also the standing proof that a config flag saying
"enabled" tells you nothing about what a chain exposes — which is why all three
voice engines' control symbols were enumerated off live chains before the voice
CONTROL page was designed. All three publish all four; no column is greyed there.

**Pattern length is quantised to whole beats.** The sequencer computes a
pattern's length as `beats × PPQN`, and there is no function in the installed
library to set a length in steps. Beats is the only length knob there is. That is
why LENGTH moves in beats while the display shows steps, and why 1, 5, 7, 11 and
13 steps are unreachable. It is a hard property of the sequencer, so the design
went with the grain: reachable lengths per division are documented, and the pads
themselves show the length by going dark past the end.

**The sequencer library is not thread-safe.** The driver reaches it from four
places — the MIDI handler, the queued signal handler, the 30 Hz playhead poll,
and the Turing writer. Unsynchronised access has already killed the entire
Zynthian UI with a segfault, 95 seconds into a jam. Everything that touches the
library holds one lock, and the Turing writer follows strict discipline: one lock
acquisition per note burst rather than one per note; pattern selection exactly
once per burst and never in the poll hot path (it writes the sequencer's single
global pattern selection and would fight the touchscreen editor for it);
clocks-per-step cached so the hot path never calls in; and the lock never held
across a preset load, which talks to the sampler over a socket and can block.

**The playhead cannot come from a signal.** Zynthian's sequence-progress signal
fires at 5 Hz, which aliases against the step rate and skipped pads
unpredictably. The driver polls at 30 Hz in its own thread instead. Nothing
step-rate-sensitive may ever be driven from that signal.

**Transport is not what it looks like.** Zynthian's play-toggle action resolves
to the audio *file player*, or to a single pattern when the pattern editor is on
screen. The driver sets each sequence's play state directly instead, which also
starts JACK transport by itself.

**Loop mode must be re-forced, not set once.** Restoring a snapshot rewrites every
sequence's play mode from the file, and a loop-all sequence shorter than the bar
goes RESTARTING at its own end, which the next non-sync clock turns into
STARTING — and STARTING does not clock its tracks. The channel falls silent until
the next bar sync. LOOP is therefore re-asserted on every pattern write and every
transport start.

**The sequencer cannot persist a mute.** Its track record stores type, chain id,
channel, output, map and the pattern list, and stops there. A sequencer-level
mute was silently lost by every snapshot save. Mutes live on the mixer strip
instead, which is in the snapshot and visible on the touchscreen.

**Nothing signals a control change.** Moving a fader on the touchscreen emits no
signal the driver can subscribe to, so levels are re-read on a slow poll. This is
also why the driver's own copies of LEVEL, MASTER and BPM can drift from reality
(see §7) — the display reads the truth, the encoder increments the copy.

**The Pi's installed Zynthian is older than the development checkout**, and every
new library call has to be audited against the installed shared object before it
is written. That has already broken this project three times, on call arity and
on two functions that exist upstream but not on the Pi.

---

## 13. Known divergences between the design and the shipped code

Recorded because they matter on stage. The code is the truth; the design
documents are not.

Writing this manual was itself a review: reading the driver against the design
surfaced three defects that would have shown up in front of people, and they
were fixed rather than documented. They are listed at the end for the record.

| # | Design says | Code does | Impact |
|---|---|---|---|
| 1 | SWING writes `(value − 50) / 25` to the sequencer | Writes `(value − 50) / 50`, so the surface's 50-75 spans 0.0-0.5 of the sequencer's swing range. The on-screen bar reads full at 75 because it draws the **surface** position. | Deliberate: 0.5 of a step is already a hard shuffle. Use your ears, not the number. |
| 2 | Swing division 1/16 corresponds to `setSwingDiv(4)` | The driver asserts **1**. The sequencer delays a step when `(step + div) % (2 × div) == 0`, so div 1 delays every second step — which at 1/16 steps is 1/16 swing. | Code is right, the plan was wrong. |
| 3 | ALL page column 6 is `REVDAMP`, 0-100 | `REVTYPE` — a raw index into TAP Reverberator's 43 rooms. | Ratified at the gates; the older design text is stale. TAP Reverberator has no damping control. |
| 4 | Snapshot is `022-techno-machine` | In use is **`016-techno_maschine.zss`**. | Naming only. |
| 5 | Globals default to master 88, revsize 72, dlytime 1/4 | Code initialises master 80, revsize **25**, dlytime **1/8**, dlyfbk 35, bpm 132, root 9 (A), scale 0 (MIN). | Cosmetic — the snapshot's own values are what you hear. |
| 6 | Pad LEDs are "bright, scaled by step velocity" | Active steps draw at full brightness; velocity is not reflected in the LED. | Cosmetic. |
| 7 | KIT and PRESET land on the bar | They land immediately (debounced 150 ms and 200 ms, but not bar-synced). ROOT and SCALE do wait for the wrap on both kinds; DIVIDE and LENGTH wait **only on a drum** — on a voice they rewrite from the existing register and land at once. | A kit change mid-bar is audible but not disruptive. |

### Fixed during this review, listed so nobody re-derives them

| What was wrong | Why it mattered |
|---|---|
| Voice `LENGTH` changed the pattern's beats instead of the shift register, and the change was silently undone at the next rewrite | The register was unreachable from the surface and the knob looked dead |
| Voice `DIVIDE` regenerated a euclidean single-note drum pattern over the melodic line | Destroyed the phrase; permanent while the voice was at `LOCK`, which is exactly when a player least expects the line to move |
| The ◀ ▶ arrows always stepped the drum sample | On a voice they resolved a GM percussion fallback and collapsed the whole line onto one note |
| `DIVIDE` and `LENGTH` landed instantly, so law L2 was only half true | A division change mid-bar trips the groove |
| `ERASE` + Group on a voice latched silence with no way back from the surface | Only the touchscreen could undo it |
| `LEVEL`, `MASTER` and `BPM` incremented a stored copy while displaying the live value | The first turn after a touchscreen move jumped |
| A kit or sample change rewrote every step at velocity 100 | Flattened the accents pad velocity exists to capture |
| Dead mixer-encoder code and a module header describing the superseded layout | Misleads the next reader |

---

## Summary card

```
GROUP A-H     select channel            F1-F8     MUTE  (tap=latch, hold=momentary)
SOLO + Fn     momentary solo            SOLO tap  latched solo mode (additive)
CONTROL       what it sounds like       enc 6/7/8 always LEVEL, REVERB, DELAY
STEP          what it plays             enc 7     always SWING, both channel types
ALL           key, tempo, master, space left = time+key, right = ganged space
PADS          the 16 steps              velocity on the tap = step accent
PLAY all on/off   RESTART all to step 0   ERASE hold + pad/group only
DUPLICATE     give the last line back   <  >  next sound: sample on a drum,
                                                  engine preset on a voice

LAW  timbre lands instantly · ROOT and SCALE land on the bar
     drum DIVIDE and LENGTH land on the bar too · on a voice they land at once
LAW  tap = latch · hold = momentary · 250 ms
LAW  nothing destructive on one press
LAW  a knob with no source is greyed, shows ---- and does nothing
LAW  one channel one cursor · the inverted tab is authoritative
     a dashed tab means the channel is not sounding
LAW  RANDOM -> 0 keeps the loop you are hearing, bit-identical, forever

VOICE STEP    enc 1 = register bits (2-16) · enc 2 = step rate
              every column rewrites from the unchanged register, so the whole
              page is safe at LOCK
```
