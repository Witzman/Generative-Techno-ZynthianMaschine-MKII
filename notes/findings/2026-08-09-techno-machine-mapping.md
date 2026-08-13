# The Techno Machine — Maschine MK2 control mapping

**Date:** 2026-08-09
**Status:** design proposal. Not implemented, not planned.
**Scope:** the complete surface mapping for an 8-channel live techno instrument —
5 euclidean drum channels, 3 Turing-machine synth voices, reverb and delay for
every channel — driven from one Maschine MK2 on a Raspberry Pi 4 Zynthian.

**Builds on:** `specs/2026-08-06-maschine-drum-rig-design.md` (the rig that
exists), `specs/2026-08-09-maschine-sfz-kits-design.md` (per-group SFZ kits),
`htmldoku/project-midi-reference.md` §1 and §5 (hardware inventory and what is
bound today).

---

## 0. The one-paragraph summary

Three latched page buttons — **CONTROL**, **STEP**, **ALL** — decide what the
eight encoders mean. CONTROL is the selected channel's sound, STEP is how that
channel generates its notes, ALL is the machine's globals. Group A–H select the
channel and the screen tab inverts to prove it. SHIFT held is the mixer: the
eight encoders become eight faders and the group buttons become eight mutes.
F1–F8 are always the eight channels and always mean solo. The pads are always
the selected channel's sixteen steps, unless PAD MODE is lit, in which case they
play it. Nothing else is mapped, on purpose.

---

## 1. What a player actually does

The workflow the mapping has to make fast, in the order it happens.

1. **Load the snapshot.** Eight chains exist, eight sequences exist, the group
   LEDs come up in their channel colours, the tabs come up with their names.
   Nothing is created at run time.
2. **Build a kick.** Press **A**. Press **STEP**. `HITS` 4, `LENGTH` 16,
   `DIVIDE` 1/16. Press **Play**.
3. **Build a hat.** Press **D**. `HITS` 11, `ROTATE` 2. Press **CONTROL**, sweep
   `KIT` until the machine is right, `SAMPLE` until the sound is right.
4. **Repeat for the other drums.** Every drum is the same two pages and the same
   six knobs, so channels 2–5 cost seconds, not minutes.
5. **Build a bass line.** Press **F**. Press **STEP** — the same button, but the
   columns are now a Turing machine because F is a voice. `LENGTH` 8, `DIVIDE`
   1/16, `GATE` 40. Turn `RANDOM` up and let it mutate until a line arrives that
   you want; turn `RANDOM` back to 0 to lock it. Turn `DENSITY` down to open
   holes in it.
6. **Voice it.** **CONTROL** → `CUTOFF`, `RESO`, `ENV`, `DECAY`, then `REVERB`
   and `DELAY` on the last two knobs, which are the last two knobs on every
   channel in the machine.
7. **Set the key once.** **ALL** → `ROOT` and `SCALE`. All three voices follow.
   Set `BPM` and `SWING` while you are there.
8. **Balance.** Hold **SHIFT**. The eight encoders are eight faders, the eight
   group buttons are eight mutes, the screens are a mixer. Release SHIFT and you
   are back exactly where you were.
9. **Perform.** F-row solos for drops. SHIFT+Group mutes for arrangement.
   **ALL** for delay-feedback throws and reverb size swells. **PAD MODE** to
   finger-play a fill over the running sequence, **REC** to keep it.
10. **Save** from the touchscreen. Everything above is in the snapshot, because
    everything above is either zynseq, the mixer, or a chain's processor state.

Two facts fall out of that list and they are the design's spine:

- **The player alternates between two questions per channel** — *what does it
  sound like* and *what does it play*. Two buttons, always the same two,
  regardless of whether the channel is a drum or a voice.
- **The mix is not a place you go.** It is a modifier you hold, because you
  always want it and you never want to lose your place to get it.

---

## 2. Options considered

### 2.1 Interaction model — how the encoders get re-purposed

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Latched page buttons** — one lit button per page, mutually exclusive, press the lit one to return home | Costs no hand. Page identity is a lit legend the player can read in the dark. Direct access: any page from any page in one press. Scales to exactly as many pages as there are good legends | Consumes a dedicated button per page. Two-state truth (lit LED + screen contents) can disagree if the driver drops a press | **Chosen.** Explicitly what the owner asked for, and the only model where "which page am I on" has a permanent physical answer |
| **B. EL/ER cycling** (SHIFT+Browse / SHIFT+Sampling) — NI's own encoder-page paging | Native grammar. Costs two buttons for unlimited pages. Pages the F buttons together with the encoders, 16 controls per page | Order-dependent: reaching page 3 from page 1 is two presses and you must know the order. **No LED anywhere says which page you are on** — the screens are the only feedback, and they are 64 px tall with no room for a header. Both buttons are SHIFT combinations, which costs a hand anyway | Rejected. It trades the one thing the machine is short of — unambiguous state feedback — for page count we do not need |
| **C. Held modal buttons** — hold STEP to see sequence params | Zero risk of being on the wrong page; release and you are home | Costs a hand permanently, so you cannot two-hand a knob sweep. Rules out any move that needs both hands, which is most live moves | Rejected for pages. **Kept for exactly one thing** — the mixer — because the mixer is inherently the "grab the faders" gesture and SHIFT is already held there for mutes |
| **D. No pages at all** — 8 encoders, 8 fixed functions | The cleanest possible thing to remember | 8 knobs cannot cover sound + sequence + sends + mix for 8 channels. Would force per-channel sends off the surface entirely | Rejected as insufficient |

**Three pages, not four or five.** Every page is a button that must be
memorised, so each one has to earn its LED. The three that earn it are
CONTROL (sound), STEP (sequence), ALL (globals). A fourth "mixer" page was
designed and then deleted — see 2.4.

### 2.2 Do drums and voices share a page scheme?

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Same buttons, type-dependent contents** — STEP shows euclid on a drum and a Turing machine on a voice | One mental model. The player learns "STEP is where notes come from" once and it is true of all eight channels. Group select and page select stay orthogonal — 8 channels × 3 pages with no exceptions | The eight knobs under STEP mean different things depending on which channel is selected, so muscle memory is per-type, not absolute | **Chosen.** The *button* grammar is uniform; only the labels under it change, and the screens print those labels an inch from the knob |
| **Separate page buttons per type** — e.g. STEP for drums, GRID for voices | Absolute knob memory | Half the buttons are dead on any given channel. Doubles the page count for no new capability. Invites the error of pressing the drum page on a voice and finding nothing | Rejected |
| **Separate machines** — drums on groups A–E behave one way, voices F–H are a different instrument with different transport | Maximum freedom per type | Two instruments in one box is the opposite of the brief | Rejected |

One rule holds this together and it is worth stating as a rule:
**left screen = the shape of the pattern, right screen = how it is played.**
True on the drum STEP page (HITS/ROTATE/DIVIDE/LENGTH | VELO/ACCENT/…) and on
the voice STEP page (LENGTH/DIVIDE/RANDOM/GATE | OCTAVE/RANGE/DENSITY/VELO).

### 2.3 Where the per-channel FX sends live

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Encoders 7 and 8 of the CONTROL page, on every channel** | The last two knobs are REVERB and DELAY on all eight channels, drums and voices alike — one piece of absolute muscle memory that survives every channel change. Costs no page, no button, no modifier | You must select the channel to change its send. Cannot sweep all eight sends at once | **Chosen** |
| **B. Two dedicated send pages** — 8 encoders = 8 channels' reverb send, another page for delay | Sweep all eight at once. Column *n* = channel *n* lines up with the tabs and the F buttons | Two more page buttons, and there is **no legend on this device that reads as "reverb"** — you would be labelling a send page SAMPLING or BROWSE. A wrong legend is worse than no button, because the legend is the only permanent label the player has | Rejected |
| **C. Sends on the SHIFT layer** — SHIFT+enc *n* = channel *n*'s reverb send | Free, always available | SHIFT is already the mixer. Two meanings on one modifier, and the mixer is the more valuable of the two | Rejected |
| **D. No per-channel sends; one global wet control** | Simplest | Directly contradicts the brief | Rejected |

**The mechanism behind the send is the least-solved part of this design** and it
is called out again in §8. The mapping is deliberately built so that it does not
care which mechanism wins:

- If a true **send** into a shared reverb/delay chain is achievable, encoders 7/8
  are send levels and the ALL page holds the two shared units' parameters.
- If it is not, each channel gets its own **insert** reverb and delay, encoders
  7/8 become wet amounts, and the ALL page's four FX columns become the selected
  channel's own FX parameters instead of the shared ones.

Same knobs, same page, same legends, same screens. Only the wiring changes.
That robustness is the reason to put the sends on the per-channel page rather
than on an all-channel one.

### 2.4 Where the mixer lives

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. SHIFT held = mixer** — encoders are faders, group buttons are mutes, screens show levels | Available from every page without losing your place. Costs no button and no legend. SHIFT is **already** the mute modifier by prior decision, so the SHIFT layer is already "the mix layer" — this makes it consistent rather than adding a second meaning. Column *n* sits directly under tab *n*, so the mixer screen needs no new labels | Costs a hand while held. Cannot latch a fader move and walk away | **Chosen** |
| **B. A fourth latched page (VOLUME or ALL)** | Two-handed. All eight faders visible without holding anything | A fourth page to remember, and it steals the ALL legend from the globals page. Worse: you are *on* the mixer, so a mute-and-tweak-the-sound move becomes two page presses | Rejected |
| **C. Encoder 8 = volume of the selected channel** (what the rig does today) | Zero cost | One channel at a time. Balancing a mix one channel at a time with a page change between each is the slowest thing on the machine | Rejected — this is a deliberate regression from the shipped rig, accepted because riding eight faders at once is worth far more than riding one |

**Pan is not on the surface at all.** See §7.

### 2.5 What F1–F8 mean

The screens settle this before taste does. The F buttons sit **above** the
screens, adjacent to the tab row, and the tab row is the eight channels. The
encoders sit **below** the screens, adjacent to the parameter columns. So the
geometry already assigns the metaphors:

> **F buttons belong to the tab row and therefore to channels. Encoders belong
> to the parameter columns and therefore to parameters.**

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. F1–F8 = solo, always, on every page** | One row whose meaning never changes. LED feedback is direct: lit = soloed. Pairs with SHIFT+Group mute to give both live gestures, both non-modal, both with LEDs. Positionally correct | Uses eight LED buttons for one function | **Chosen** |
| **B. F1–F8 paged with the encoders**, 16 controls per page as in NI's software | Native grammar. 24 controls across three pages | 24 meanings to memorise instead of 8. Breaks the tab-row geometry: Fn would mean "the parameter above column n" while the tab above it says "channel n". Directly opposed to "clean interface" | Rejected |
| **C. F1–F8 = channel select**, duplicating Group A–H | Nothing gained | Two ways to do one thing is a source of confusion, not speed | Rejected |

`SHIFT + Fn` = **exclusive solo**: solos channel *n* and clears every other solo.
Pressing a lit `Fn` clears its solo. Clearing the last solo returns everything to
sounding.

### 2.6 How the player sees where they are

Three facts must be legible at a glance in the dark, from about twenty LEDs and
two 255×64 monochrome panels.

| Fact | Primary indicator | Confirmation |
|---|---|---|
| **Which page** | Exactly one of CONTROL / STEP / ALL is lit, always. Home is CONTROL and it is lit when nothing else is | The eight column names. `HITS ROTATE DIVIDE LENGTH` can only be STEP; `KIT SAMPLE` can only be CONTROL. The parameter names are self-identifying and cost nothing |
| **Which channel** | The **inverted tab** on the screen — one of eight boxes drawn in reverse video | The eight column values change when you change channel |
| **What each channel is** | Group LED **hue** = channel identity, fixed | The tab text: `A KICK`, `F BASS` |
| **How loud** | Group LED **brightness** | The mixer screen while SHIFT is held |
| **Muted or silenced** | Group LED **dark** | Tab drawn with a dashed border |

The group LED carries three independent facts on three independent dimensions —
**hue = identity, brightness = level, dark = silent** — which is why selection
cannot also live there. A fourth dimension exists (**saturation**) and the
proposal is to use it: draw the selected channel at full saturation and every
other channel desaturated ~30 % toward white. That is a free extra cue.

> **Caveat, stated up front:** a quiet channel is a dim LED, and saturation
> differences are hard to read at low brightness. The inverted tab remains
> authoritative for selection; the saturation cue is a bonus and must be
> dropped if it reads badly on the panel.

There is **no room on the screens for a page header.** The layout is fully
committed: tabs 0–12 px, dotted rule at 15, parameter name at 19, double-height
value at 30, indicator bar at 52–62, on a 64 px panel. This is why the page LED
has to be the page indicator, and why option 2.1B (EL/ER cycling, no LED) fails.

### 2.7 Channel allocation

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **5 drums + 3 voices** (A–E drums, F–H voices) | Kick, snare, clap, closed hat, open hat/perc is the minimum honest techno kit. Fills all eight groups | The drum/voice seam falls one tab *inside* the right screen, so neither panel is purely one type | **Chosen default** |
| **4 drums + 3 voices + 1 spare** (A–D drums, E–G voices, H free) | Left screen is entirely drums, right screen entirely voices — a perfect panel split and a very memorable machine | Four drums is thin. A lit group button that does nothing is worse than a seam | Available as a one-line change |

Make the role of each group a **table in the driver**, not a structural
assumption:

```
CHANNELS = [
    ("A", "KICK", DRUM),  ("B", "SNAR", DRUM),  ("C", "CLAP", DRUM),
    ("D", "CHAT", DRUM),  ("E", "OHAT", DRUM),  ("F", "BASS", VOICE),
    ("G", "LEAD", VOICE), ("H", "PADS", VOICE),
]
```

Then 5+3, 4+3+spare, or 4+4 is a config line and never a redesign. Everything
below is written against 5+3.

Suggested hues, chosen so the seam is visible on the panel — **drums warm,
voices cool**: A red · B orange · C amber · D yellow-green · E green · F blue ·
G violet · H cyan.

---

## 3. The recommended mapping

### 3.1 Global controls — the same on every page

| Control | MIDI in | Function |
|---|---|---|
| **Group A–H** | CC 80–87 | Select channel. Pads, both screens' column values, CONTROL and STEP all follow selection |
| **SHIFT + Group A–H** | SHIFT + CC 80–87 | Toggle mute of that channel (mixer strip mute — see §8, zynseq cannot persist a mute). LED goes dark |
| **F1–F8** | CC 39–46 | Solo channel A–H. Additive. LED lit = soloed. Non-soloed channels' group LEDs go dark |
| **SHIFT + F1–F8** | SHIFT + CC 39–46 | Exclusive solo — solos that channel and clears all others |
| **CONTROL** | CC 11 | Page: sound of the selected channel. **Home.** Lit when no other page is |
| **STEP** | CC 32 | Page: sequence of the selected channel. Press again → CONTROL |
| **ALL** | CC 38 | Page: machine globals. Press again → CONTROL |
| **PAD MODE** | CC 27 | Latched. Dark = pads are steps. Lit = pads play the selected channel |
| **REC** | CC 3 | Latched. Lit = pad hits in PAD MODE are written into the pattern |
| **GRID** | CC 4 | Latched. Lit = live record quantises to the nearest step. Dark = nearest clock |
| **Play** | CC 1 | Start / stop all eight sequences (`setPlayState` on each — never `TOGGLE_PLAY`, see §8) |
| **Restart** | CC 7 | Every channel to step 0 |
| **Erase** | CC 2 | Clear the selected channel's pattern |
| **SHIFT + Erase** | SHIFT + CC 2 | Clear all eight patterns |
| **Arrows beside the display** | CC 5/6 | Previous / next **sound** for the selected channel — the sample within the kit on a drum, the engine preset on a voice. Same meaning on both types |
| **Master arrows** | CC 13/14 *(pair identity unconfirmed)* | BPM −1 / +1 |
| **Big encoder** | *(unverified)* | Master output level |
| **Big encoder push** | *(unverified)* | Return to the CONTROL page — an escape that works from anywhere |
| **SHIFT held** | *(needs daemon patch)* | Mixer layer — see 3.5 |

Nothing in this table except master volume depends on the big encoder, and the
push is a convenience duplicate of the CONTROL button. **If the big encoder
turns out to be unreadable, the mapping loses master volume from the surface and
nothing else** — set it on the touchscreen. That is the whole cost, and it is
why BPM was deliberately put on the ALL page rather than under the TEMPO button.

### 3.2 Pads

| State | Pad behaviour | Pad LED |
|---|---|---|
| **PAD MODE dark** (default) | Toggle step *n* of the selected channel's zynseq pattern. **Pad velocity sets the step's velocity when toggling it on**, so a hard tap is an accent — free, and it uses hardware the rig already reads | dim = empty · bright = active, brightness scaled by step velocity · white = playhead |
| **PAD MODE lit, drum channel** | Play the 16 sounds of that channel's SFZ kit, so you can audition and choose without the encoder | channel hue on pads that exist in the kit, dark on the rest |
| **PAD MODE lit, voice channel** | Play 16 notes of the current `ROOT`+`SCALE`, ascending from the channel's octave | channel hue; root notes brighter |
| **PAD MODE lit + REC lit** | As above, and each hit is written into the pattern, quantised per GRID | as above; the written step flashes |

Steps beyond the pattern's `LENGTH` are dark and inert. **Pattern length is
quantised to whole beats** (`getLength() = beats × PPQN`, no `setSequenceLength`
in the installed C API), so reachable lengths are `beats × steps_per_beat` —
1, 5, 7, 11 and 13 are not reachable with the current divisions. Known and
accepted.

**Pattern authority is unchanged from the shipped rig:** the generator (euclid or
Turing) owns the pattern. Pad taps edit on top of it. The next generator move
wipes those taps. No hidden per-step override state, no third LED colour. For a
voice this means a pad tap toggles whether a step *sounds*, keeping the pitch the
Turing machine put there — which is exactly the rest-editing you want.

**No pad pages.** Eight groups × sixteen pads is enough, and a pad page has no
LED to show which page you are on.

### 3.3 CONTROL page — the selected channel's sound

Encoders 7 and 8 are **REVERB and DELAY on every channel of every type.** That
is the one absolute piece of muscle memory in the machine and it is worth
protecting.

**Drum channel**

| Enc | Screen | Name | Value | Bar | Source |
|---|---|---|---|---|---|
| 1 | L1 | `KIT` | 4-char kit abbrev | segmented | LinuxSampler preset — 41 SFZ drum machines |
| 2 | L2 | `SAMPLE` | sample name, 4 char | segmented | note within the kit |
| 3 | L3 | `TUNE` | ±24 | bipolar | **needs new work — see §8** |
| 4 | L4 | `DECAY` | 0–100 | unipolar | **needs new work** |
| 5 | R1 | `FILTER` | 0–100 | unipolar | **needs an LV2 per drum chain** |
| 6 | R2 | `DRIVE` | 0–100 | unipolar | **needs an LV2 per drum chain** |
| 7 | R3 | `REVERB` | 0–100 | unipolar | send / wet |
| 8 | R4 | `DELAY` | 0–100 | unipolar | send / wet |

**Voice channel**

| Enc | Screen | Name | Value | Bar | Source |
|---|---|---|---|---|---|
| 1 | L1 | `PRESET` | preset name, 4 char | segmented | chain preset |
| 2 | L2 | `CUTOFF` | 0–127 | unipolar | engine zctrl |
| 3 | L3 | `RESO` | 0–127 | unipolar | engine zctrl |
| 4 | L4 | `ENV` | 0–127 | unipolar | filter envelope amount |
| 5 | R1 | `DECAY` | 0–127 | unipolar | amp decay — **`ATTACK` on the PADS channel**, per the role table |
| 6 | R2 | `DRIVE` | 0–127 | unipolar | drive / shape |
| 7 | R3 | `REVERB` | 0–100 | unipolar | send / wet |
| 8 | R4 | `DELAY` | 0–100 | unipolar | send / wet |

A column whose zctrl does not exist on that chain draws its name greyed, no
value and no bar, and its encoder does nothing. Silently-dead knobs are the
failure mode the SFZ work already hit with LinuxSampler; make the screen say so.

### 3.4 STEP page — how the selected channel generates notes

**Drum channel — euclidean**

| Enc | Screen | Name | Value | Bar | Range |
|---|---|---|---|---|---|
| 1 | L1 | `HITS` | 0–*len* | unipolar | euclid onsets |
| 2 | L2 | `ROTATE` | 0–*len*−1 | segmented | euclid rotation |
| 3 | L3 | `DIVIDE` | `1/32 1/16 1/8 1/16T 1/8T` | segmented | `setStepsPerBeat` 8/4/2/6/3 |
| 4 | L4 | `LENGTH` | steps | unipolar | `beats × steps_per_beat`, quantised |
| 5 | R1 | `VELO` | 1–127 | unipolar | velocity of generated hits |
| 6 | R2 | `ACCENT` | 0–100 | unipolar | how much louder every *n*-th hit is |
| 7 | R3 | — | — | — | **deliberately blank** |
| 8 | R4 | — | — | — | **deliberately blank** |

`GHOST` — a second, quieter euclidean layer placed in the gaps — is the obvious
candidate for column 7 and is genuinely techno-useful, but it is an invention
beyond the brief. Leave the columns blank until it is wanted. Two blank columns
are cheaper than two knobs whose function nobody can name.

**Voice channel — Turing machine**

| Enc | Screen | Name | Value | Bar | Range |
|---|---|---|---|---|---|
| 1 | L1 | `LENGTH` | 2–16 | unipolar | shift-register length |
| 2 | L2 | `DIVIDE` | `1/32 1/16 1/8 1/4 1/16T 1/8T` | segmented | clock division, tempo-synced |
| 3 | L3 | `RANDOM` | 0–100 | unipolar | **0 = locked loop, 100 = new every step.** The single most-touched knob on the machine |
| 4 | L4 | `GATE` | 5–100 | unipolar | note length as % of a step |
| 5 | R1 | `OCTAVE` | −2…+2 | bipolar | transpose |
| 6 | R2 | `RANGE` | 1–4 | segmented | spread in octaves |
| 7 | R3 | `DENSITY` | 0–100 | unipolar | how many steps sound rather than rest |
| 8 | R4 | `VELO` | 1–127 | unipolar | velocity, matching the drum page's column 5 |

`ROOT` and `SCALE` are **not here** — they are global, on the ALL page. Three
voices in three different keys is not a feature, and moving them out buys two
columns.

The Turing machine's output is **written into the channel's zynseq pattern**, so
it persists in snapshots, appears in the touchscreen pattern editor, and is
edited by the pads like any other pattern. Consequences in §8.

### 3.5 SHIFT held — the mixer

Momentary. Release and everything returns to the page you were on.

| Control | Function |
|---|---|
| Encoder 1–8 | Level of channels A–H — `zynmixer.set_level` on the strip, engine-independent, in the snapshot |
| Group A–H | Toggle mute of channel A–H |
| F1–F8 | Exclusive solo of channel A–H |
| Erase | Clear all patterns |
| Big encoder | Global swing |
| Screens | Mixer view — see 4.5 |

Column *n* on the mixer screen sits directly under tab *n*, which sits directly
under F button *n*, which sits above encoder *n*. On this one screen every
metaphor on the machine agrees. That alignment is the argument for the SHIFT
mixer more than any feature is.

### 3.6 ALL page — the machine's globals

| Enc | Screen | Name | Value | Bar |
|---|---|---|---|---|
| 1 | L1 | `ROOT` | `C` … `B` | segmented |
| 2 | L2 | `SCALE` | `MIN MAJ DOR PHR HMIN PENT` | segmented |
| 3 | L3 | `BPM` | 60–200 | unipolar |
| 4 | L4 | `SWING` | 50–75 | unipolar |
| 5 | R1 | `REV SIZE` | 0–100 | unipolar |
| 6 | R2 | `REV DAMP` | 0–100 | unipolar |
| 7 | R3 | `DLY TIME` | `1/16 1/8 3/16 1/4 3/8 1/2` | segmented |
| 8 | R4 | `DLY FBK` | 0–100 | unipolar |

**Left screen = time and key. Right screen = space.** That split is why this
page needs no header to be understood, and why BPM and SWING live here rather
than under the TEMPO and SWING buttons — which is fortunate, because neither of
those buttons emits a CC today (see §8).

FX return levels are fixed at unity; the per-channel sends do all the balancing.
If the insert fallback (§2.3) is taken instead, these four FX columns become the
**selected channel's own** reverb and delay parameters — same knobs, same
labels, and per-channel delay time is if anything a better performance control
than a shared one.

---

## 4. Screen layouts

Geometry as built: two panels, 255×64, four 64 px columns each. Tab row 0–12,
dotted rule at 15, parameter name at 19 (5×8), value at 30 (double height,
**4 characters**), indicator bar 52–62. Tabs hold 8 characters. Selected tab is
drawn inverted; muted tabs get a dashed border. The tab row is present on every
page, always, because channel selection and mute state are always wanted.

Bar kinds: `[====  ]` unipolar fill · `[--|--]` bipolar from centre ·
`[# # . .]` segmented.

### 4.1 CONTROL page, drum channel A selected

```
LEFT SCREEN  (255x64)                     RIGHT SCREEN  (255x64)
+--------+--------+--------+--------+     +--------+--------+--------+--------+
|#A KICK#| B SNAR | C CLAP | D CHAT |     | E OHAT | F BASS |:G LEAD:| H PADS |
+--------+--------+--------+--------+     +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·       · · · · · · · · · · · · · · · · · ·
 KIT      SAMPLE   TUNE     DECAY          FILTER   DRIVE    REVERB   DELAY
 T808     KICK     +00      068            082      014      024      036
 [# # . ] [# . . ] [--|--]  [====  ]       [===== ] [=     ] [==    ] [===   ]

  #..#  selected channel        :..:  muted channel (dashed border)
```

### 4.2 CONTROL page, voice channel F selected

```
+--------+--------+--------+--------+     +--------+--------+--------+--------+
| A KICK | B SNAR | C CLAP | D CHAT |     | E OHAT |#F BASS#| G LEAD | H PADS |
+--------+--------+--------+--------+     +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·       · · · · · · · · · · · · · · · · · ·
 PRESET   CUTOFF   RESO     ENV             DECAY    DRIVE    REVERB   DELAY
 SUBB     044      071      096             030      058      012      064
 [# . . ] [==    ] [===== ] [======]       [==    ] [====  ] [=     ] [===== ]
```

### 4.3 STEP page, drum channel A selected

```
+--------+--------+--------+--------+     +--------+--------+--------+--------+
|#A KICK#| B SNAR | C CLAP | D CHAT |     | E OHAT | F BASS | G LEAD | H PADS |
+--------+--------+--------+--------+     +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·       · · · · · · · · · · · · · · · · · ·
 HITS     ROTATE   DIVIDE   LENGTH          VELO     ACCENT
 04       00       1/16     16              110      025
 [=     ] [# . . ] [ . # . ] [======]      [======] [==    ]

                                            <-- columns 7 and 8 intentionally
                                                empty: no bar, no value
```

### 4.4 STEP page, voice channel F selected

```
+--------+--------+--------+--------+     +--------+--------+--------+--------+
| A KICK | B SNAR | C CLAP | D CHAT |     | E OHAT |#F BASS#| G LEAD | H PADS |
+--------+--------+--------+--------+     +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·       · · · · · · · · · · · · · · · · · ·
 LENGTH   DIVIDE   RANDOM   GATE            OCTAVE   RANGE    DENSITY  VELO
 08       1/16     000      040             -01      2        075      100
 [===   ] [ . # . ] [      ] [===   ]      [--|   ] [# # . ] [===== ] [======]

 RANDOM 000 = the sequence is locked and will repeat forever.
```

### 4.5 SHIFT held — mixer

```
+--------+--------+--------+--------+     +--------+--------+--------+--------+
|#A KICK#| B SNAR | C CLAP |:D CHAT:|     | E OHAT | F BASS | G LEAD | H PADS |
+--------+--------+--------+--------+     +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·       · · · · · · · · · · · · · · · · · ·
 A KICK   B SNAR   C CLAP   D CHAT          E OHAT   F BASS   G LEAD   H PADS
 100      082      074      000             066      090      058      044
 [######] [===== ] [====  ] [      ]       [====  ] [======] [===   ] [==    ]

 Every column sits under its own tab, its own F button and its own encoder.
 D is muted: dashed tab, level shown but not sounding, group LED dark.
```

### 4.6 ALL page

```
+--------+--------+--------+--------+     +--------+--------+--------+--------+
|#A KICK#| B SNAR | C CLAP | D CHAT |     | E OHAT | F BASS | G LEAD | H PADS |
+--------+--------+--------+--------+     +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·       · · · · · · · · · · · · · · · · · ·
 ROOT     SCALE    BPM      SWING           REV SIZE REV DAMP DLY TIME DLY FBK
 A        MIN      132      056             072      040      3/16     058
 [# . . ] [# # . ] [===   ] [==    ]       [===== ] [===   ] [ . # . ] [==== ]

 Left = time and key.  Right = space.
```

---

## 5. Complete LED language

| Surface | State |
|---|---|
| **Group A–H** | hue = channel identity (fixed) · brightness = mixer level · **dark = not sounding**, whether muted directly or excluded by someone else's solo · full saturation = selected, others desaturated ~30 % |
| **F1–F8** | lit = channel soloed · dark = not |
| **CONTROL / STEP / ALL** | exactly one lit, always. CONTROL is home |
| **PAD MODE** | lit = pads play, dark = pads edit steps |
| **REC** | lit = live record armed |
| **GRID** | lit = live record quantised to step |
| **Play** | lit while transport runs |
| **Pads** | dim = empty step · bright (scaled by velocity) = active step · white = playhead · channel hue in PAD MODE |
| Everything else | **dark, deliberately** |

Every LED write stays diff-based against the cache — the daemon has been flooded
off the USB bus once already (`ffc8f2b`). And the cache must be **cleared** on
`SS_LOAD_SNAPSHOT`, or the post-load repaint is suppressed as unchanged. Both
are lessons already paid for by the shipped rig.

---

## 6. What the daemon has to gain

| Need | State today | Work |
|---|---|---|
| **SHIFT emitted as a CC** | **Not emitted.** The daemon receives Shift and tracks it as an internal modifier; there is no Shift entry in its CC map (1–14, 24–48), and the shipped driver has no shift handling at all | **Required, and load-bearing.** Suggest CC 49 (free), 127 on press / 0 on release. Without it the machine loses the entire mixer layer *and* mute, which is already a taken decision |
| Group A–H → CC 80–87 | already patched and shipped | none |
| Big encoder turn / push | unverified — `roller_state` is sized 9, so probably roller index 8; the button enum has an `Encoder` entry | optional. Costs only master volume and one escape shortcut |
| VOLUME / SWING / TEMPO buttons → CC | **Volume and Swing emit nothing.** Only Tempo (CC 35) is in the map | not needed — the design deliberately routes around them |
| Encoder capacitive touch | not implemented, and it is not known whether it is in the HID stream at all | **not needed.** Nothing in this design depends on it |

Before binding anything, dump `a2j:...Pads MIDI` with `jack_midi_dump` and press
each control. The `step_left`/`step_right` (CC 5/6) versus `nav_left`/`nav_right`
(CC 13/14) physical pairing is still unconfirmed, and the Page ◀▶ pair (CC 47/48)
is swallowed by the daemon and never arrives.

---

## 7. Deliberately not mapped

| Thing | Why |
|---|---|
| **Pan** | Set once per channel and then never touched in techno. It is one tap away on the touchscreen mixer, where it is also visible. Putting it on the surface would cost either a knob on the CONTROL page — where every slot is doing more work — or a second modifier layer |
| **Pad pages** | 8 groups × 16 pads is enough, and no LED can show which page you are on |
| **Knob pages / EL/ER** | Superseded by the three latched page buttons. See 2.1 |
| **Page ◀▶ (CC 47/48)** | Swallowed by the daemon for its own page indicators. Never emitted |
| **Encoder capacitive touch** | Not implemented, possibly not in the stream. Its only job in NI's software is snapping the screens back to the encoder view — and here the screens never leave the encoder view, so there is nothing for it to do. **The design has no fallback to state because it has no dependency** |
| **SOLO and MUTE buttons** | Their functions live on faster controls — the F row and SHIFT+Group. Two dark buttons whose legends describe things the machine does elsewhere is a real wart; it is accepted because the alternative is making solo or mute modal, which is slower in exactly the moment it matters. If it grates, the fallback is SOLO latched → group buttons become solos, freeing F1–F8 |
| **Scene, Pattern, Navigate, Duplicate, Select, Browse, Sampling, Auto Write, Enter, Main, View** | Nothing in a machine with no scenes, no pattern chaining and no browser needs them. Dark |
| **Note Repeat** | The one genuinely tempting leftover — hold NOTE REPEAT + pad for rolls is a real techno move. Out of scope now; the best candidate for the next thing added |
| **Pad aftertouch** | Read by the hardware, used by nothing. No obvious per-step meaning that does not fight the "generator owns the pattern" rule |
| **Pattern chaining / song mode** | This is a live improvising machine. Arrangement is mutes and solos |
| **Per-channel swing** | Global only. Per-channel swing is not representable in zynseq patterns without fighting the step grid |

---

## 8. Open questions and risks

Ordered by how much of the design they can take with them.

### 8.1 How does a per-channel send actually work in Zynthian? *(highest)*

`zynmixer` exposes level, balance, mute and solo per strip and nothing else, and
chain-to-chain audio routing is on/off with no per-target level. So a *variable*
send into a shared reverb chain has no obvious native expression. Three paths,
none verified:

- **(a) True sends** via a per-channel gain stage that duplicates the channel's
  output into the FX chain. Needs a routing mechanism that may not exist.
- **(b) Per-channel insert FX** — a reverb and a delay LV2 on each of the eight
  chains, `REVERB`/`DELAY` becoming wet amounts. Works today with no new
  mechanism. Costs 16 plugin instances on a Pi 4 that currently runs the whole
  eight-kit rig at ~6 % CPU, and gives up the shared reverb tail that glues a
  techno mix. **Must be measured before it is chosen.**
- **(c) A hybrid** — shared reverb via routing at unity, per-channel delay as an
  insert.

**The mapping is identical under all three.** That was designed in, and it is the
reason the sends sit on the per-channel page. Resolve this before writing a plan,
not before writing the mapping.

### 8.2 Do the drum sound parameters exist at all?

`TUNE`, `DECAY`, `FILTER` and `DRIVE` — four of the eight columns on a drum's
CONTROL page — have **no source today.** `zynthian_engine_linuxsampler` defines
no controllers whatsoever (`_ctrls = []`), and the FluidSynth route was already
proven dead (CC 74/71 are unipolar SoundFont modulators against a kit that ships
wide open at 13500 cents). The options are an LV2 filter/drive per drum chain, or
SFZ-side pitch over LSCP, which is unverified. **If neither lands, the drum
CONTROL page is KIT, SAMPLE, REVERB, DELAY and four blanks**, which is a thin
page but not a broken one — and the greyed-column convention makes it honest
rather than mysterious.

### 8.3 A mutating Turing machine rewrites a zynseq pattern every cycle

Putting the Turing output into zynseq is what buys persistence, the touchscreen
editor and pad editing — but it means the driver writes 8–16 notes into a pattern
once per cycle while `RANDOM` > 0. Three specific hazards:

- **Every one of those writes must hold `self.lock`.** `libzynseq` is not
  thread-safe and this driver already reaches it from three threads. The last
  time that rule was broken the whole Zynthian UI died with SIGSEGV about 95 s
  into a jam.
- Never drive the regeneration from `SS_SEQ_PROGRESS` — it is 5 Hz and aliases
  against the step rate. Regenerate on a cycle boundary detected by the driver's
  own poll thread.
- A snapshot saved while `RANDOM` > 0 captures whatever the register happened to
  be holding. Correct, but say so in the tutorial: **lock it before you save it.**

Also: `selectPattern()` writes zynseq's single global pattern selection and
fights the touchscreen pattern editor for it, so the hot path must never call it.

### 8.4 SHIFT is a dependency, not a preference

Mute and the entire mixer layer rest on the driver seeing SHIFT. The daemon does
not emit it. Verify with `jack_midi_dump` before anything else in this design is
planned — if SHIFT cannot be emitted, mute and the mixer both need new homes and
§2.4 has to be reopened.

### 8.5 The big encoder and its push

Unverified. **Cost if absent: master volume moves to the touchscreen, and the
CONTROL-page escape shortcut disappears.** No page, no parameter and no
performance gesture is lost. This was a deliberate design constraint — BPM and
swing were put on the ALL page specifically so that no musical value depends on
an unverified control.

### 8.6 Three lit page buttons, three states, one truth

If a page press is dropped, the LED and the screen contents can disagree. Mitigate
by deriving the LED from the same page variable the screen renderer reads, on the
same 100 ms display tick — never by writing the LED at the point of the press.

### 8.7 The 4-character value cell

Already flagged in the SFZ work and still true. `T808` for the TR-808 is
readable; `1200` and `1201` for the two SP-1200 banks are not obviously
distinguishable at a glance. Scale names (`HMIN`, `PENT`) and delay divisions
(`3/16`) fit exactly. The fix, if it reads badly, is a wider column at a
neighbour's expense — not a smaller font.

### 8.8 Rebuild hazards inherited from the shipped rig

Not new, but they will bite again if forgotten: LOOP play mode must be
**re-forced after every snapshot restore**, not set once. `"external_pad_leds":
true` must stay in `maschine.json` or the first pad touch destroys the LED
picture. `patch-autoconnect-maschine.py` must be re-run after any Zynthian
update. And every `libseq.*` call must be audited against the Pi's installed
`libzynseq.so`, which is older than the local checkout — that has already broken
three times.

---

## 9. One-page summary card

```
GROUP A-H          select channel          SHIFT+GROUP   mute
F1-F8              solo channel            SHIFT+F       exclusive solo
PADS               steps of the channel    PAD MODE      pads play it
                                           REC           record what you play
                                           GRID          quantise the recording
CONTROL   page     what it sounds like     enc 7/8 always REVERB and DELAY
STEP      page     what it plays           euclid on drums, Turing on voices
ALL       page     key, tempo, space       left = time+key, right = FX
SHIFT     held     the mixer               8 faders, 8 mutes, 8 solos

PLAY  all on/off      RESTART  all to step 0      ERASE  clear this channel
<  >  (by display)    previous / next sound for this channel
<  >  (master)        BPM -1 / +1
BIG ENCODER           master volume  ·  push = back to CONTROL
```
