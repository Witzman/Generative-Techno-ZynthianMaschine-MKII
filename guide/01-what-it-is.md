# 1 · What It Is

The Generative-Techno ZynthianMaschine MKII is an **eight-channel generative
groovebox**. Zynthian on a Raspberry Pi 4 is the brain; a Native Instruments
Maschine MK2 is the entire surface.

Three sentences hold the whole idea.

**Eight channels are always alive.** They exist the moment the snapshot loads.
Nothing is created, added, browsed for or torn down while you play.

**A mode decides what the eight encoders mean.** CONTROL is what the selected
channel *sounds like*, STEP is what it *plays*, ALL is the machine's globals,
and MIXER and FILTER spread one parameter across all eight channels at once.

**The generator owns the pattern.** You do not draw a beat and decorate it. You
set generator parameters — hits, rotation, randomness — and the driver writes
notes into Zynthian's own sequencer. Because it is Zynthian's sequencer,
patterns persist in snapshots and the touchscreen pattern editor mirrors exactly
what the pads show.

---

## The eight channels

| Group | Name | Kind | Engine | MIDI ch | Colour |
|---|---|---|---|---|---|
| A | KICK | drum | LinuxSampler, an SFZ drum machine | 1 | red |
| B | SNAR | drum | LinuxSampler | 2 | orange |
| C | CLAP | drum | LinuxSampler | 3 | amber |
| D | CHAT | drum | LinuxSampler | 4 | yellow-green |
| E | OHAT | drum | LinuxSampler | 5 | green |
| F | BASS | voice | JC303 | 6 | blue |
| G | LEAD | voice | Obxd | 7 | violet |
| H | PADS | voice | padthv1 | 8 | cyan |

Drums are warm colours and voices cool, so the seam between the halves is
visible on the panel without reading anything.

The five drum channels are **euclidean** generators: given a step count and a
hit count, hits are spread as evenly as the grid allows, then rotated. The three
voices are **Turing machines** — each owns a shift register that is clocked once
per pass and mutated with probability `RANDOM`, and the register's value becomes
pitch. Set `RANDOM` to zero and the loop you are hearing is frozen bit for bit,
for as long as you leave it there.

**The MIDI channel is the contract.** The driver finds a channel's chain by MIDI
channel, not by chain order or title, so channels 1-8 must be exactly as above.

---

## The signal path

Measured on the wire, not assumed:

```
LinuxSampler / synth
    │
    ▼
zynmixer strip  (fader, pan, mute)
    │
    ▼
TAP Stereo Echo      ─┐
    │                 │  two post-fader inserts per channel,
    ▼                 │  sixteen plugin instances in total
TAP Reverberator     ─┘
    │
    ▼
main
```

Two properties of that path are the reason the instrument feels the way it does.

**The inserts are post-fader.** They are fed from the mixer strip's *output*, so
they inherit the channel's fader and its mute automatically. Muting a channel
kills its reverb and delay tail with it instead of letting it ring out.

**Both plugins have a true wet level, not a dry/wet crossfade.** Sweep the wet
to maximum and the dry is still there at exactly the same level. That is what
lets encoders 7 and 8 behave like sends on every channel of both kinds, forever.
Every cheaper candidate — MDA Ambience, MDA DubDelay, CAPS PlateX2, MDA Delay,
`lcrDelay`, `bolliedelay` — turned out to be a crossfade. The two cheapest true
sends, `gverb` and MaGigaverb, are **mono in**, and an insert sitting after the
strip's pan would collapse every channel to centre.

---

## What it is not

- **Not a DAW.** No arranger, no song mode, no pattern chaining, no undo history
  beyond a voice's four-deep register ring.
- **Not a Zynthian fork.** One control-surface driver in `zyngine/ctrldev/`, plus
  one idempotent patch to `zynautoconnect`. Zynthian core is untouched.
- **Not a shared effects bus.** Zynthian's mixer has sixteen usable strips
  compiled in, and a correct send-tap topology needs twenty-six. Sixteen
  post-fader inserts is the answer to that constraint, not a preference — so
  there is no shared tail and no duckable return.
- **Not a general MIDI controller mapping.** The driver claims the Maschine's pad
  port exclusively, so pads never reach a chain by themselves.

---

## What you need

| | |
|---|---|
| Computer | Raspberry Pi 4 (this is what the rig was built and measured on) |
| Surface | Native Instruments Maschine MK2, over USB |
| Audio | Any interface Zynthian supports. Every figure in this project was measured on the Pi's built-in headphone output at 48 kHz |
| Storage | SD card, 16 GB or more — the ZynthianOS image is about 7.5 GB compressed |
| Display | A screen for Zynthian's own UI. Snapshots are saved and loaded there, so it is not optional |

---

## Scope, stated plainly

Verified on **ZynthianOS `Oram-2601-1`** with `zynthian-ui` on branch
`oram-2601.1`, on one rig, with one Maschine MK2.

Sections 2 to 5 were written from a running instrument, **not** walked from a
fresh flash — there was no spare SD card. Where a step could differ on a clean
install, the guide gives you a check rather than a promise, and
`tools/check-prereqs.sh` turns any gap into a list of missing dependencies
instead of a mystery.

---

This guide is published at
<https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/> and its
source lives in the repository's `guide/` directory.

**Next:** [2 · Install ZynthianOS](02-install-zynthianos.md)

The appendix [How 017 Was Built](a1-how-017-was-built.md) documents the factory
snapshot's contents and how it was made, which is what you need if an import
goes wrong or you want a channel layout of your own.
