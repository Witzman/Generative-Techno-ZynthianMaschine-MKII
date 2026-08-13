# The Techno Machine — Product Owner position

**Author:** the player. Written as the person who will stand behind this thing for
ninety minutes with no laptop and no second chance.
**Date:** 2026-08-09
**Status:** position paper. Ambition, not plan. Feasibility is the developer's argument
to make; arbitration is the PM's.

**Prior art:** `docs/superpowers/2026-08-09-techno-machine-mapping.md`. It is good work
and I keep most of its skeleton. Where I disagree I say so by name, in §2.7.

---

## 0. What this instrument is, in one paragraph

It is a **generative groovebox you play, not a sequencer you program**. Eight channels —
five euclidean drums, three Turing-machine voices — every one of them producing music
the moment it is switched on, every one of them with reverb and delay. There is no song
mode, no arrangement timeline, no browser, no file dialogue. The whole musical act is
*steering eight generators and riding a mixer*, and the only thing the surface has to be
good at is letting me change my mind fast without ever stopping the sound. The
touchscreen exists to save snapshots and for nothing else. If I have to look at it
during a set, the design has failed.

The thing I am chasing is the feeling Maschine gets right and almost nothing else does:
**every button does one thing, that thing is written on the button, and the machine
never asks me a question.** That is the entire brief. "Clean interface, clean workflow"
means *no dialogues, no confirmations, no modes I can get stuck in* — not "few
features".

---

## 1. The workflow, told with hands

### 1.1 From empty machine to a track that plays

I do not build a machine from nothing. **The snapshot is the machine.** Eight chains,
eight sequences, eight colours, eight names, all present at power-on. Building starts at
"press Play", never at "create a chain". Anything that has to be constructed at run time
is a defect.

**Bar 0 — power on.** Group buttons A–H come up in their colours. Left screen: `A KICK
B SNAR C CLAP D CHAT`. Right screen: `E OHAT F BASS G LEAD H PADS`. `CONTROL` is lit
because it is home. Nothing plays.

**The kick.** Left hand hits **A**. The tab inverts. Right hand hits **STEP**. Four
knobs under the left screen now read `HITS ROTATE DIVIDE LENGTH`. I turn knob 1 to 4.
The sixteen pads light four steps. I hit **Play**. Two seconds have passed and there is
a kick.

**The hats.** **D**, knob 1 to 11, knob 2 (ROTATE) until the hats sit off the kick, knob
3 (DIVIDE) to 1/32 for a hurry. **CONTROL**, knob 1 sweeps kits until the machine is
right, knob 2 sweeps the sample inside it. This is four knob moves and one button. It
must stay four knob moves and one button — the drums are the part I want to stop
thinking about, so I can spend attention on the voices.

**Clap, snare, perc.** Same two pages, same six knobs. Channels 2–5 cost seconds because
they cost *nothing new to learn*.

**The bass.** **F**. **STEP** — same button, but the eight columns are now a Turing
machine, because F is a voice. `LENGTH` 8, `DIVIDE` 1/16, `GATE` 40. Now the move that
this whole instrument exists for: **I hold my fingers on the RANDOM knob and turn it
up.** The line starts mutating, once per step. I listen. Two bars later a phrase goes
past that I want and I **snap RANDOM back to zero on that beat** and it locks, exactly
as it was, forever. That gesture — *fish for a line, catch it in flight* — is the
instrument. Everything else is support.

**Voicing it.** **CONTROL** on F: `CUTOFF RESO ENV DECAY DRIVE`, and knobs 7 and 8 are
`REVERB` and `DELAY`, as they are on every channel of every type on this machine.

**Lead and pads.** Same again. G, H. On the pads channel I turn `GATE` to 95 and `DIVIDE`
to 1/4 and it breathes instead of stabbing.

**Key and tempo.** **ALL**. `ROOT`, `SCALE`, `BPM`, `SWING`. One place, once. All three
voices follow the root; three voices in three keys is not a feature, it is a bug you can
opt into.

**Balance.** I hold **SHIFT** and the eight encoders become eight faders under their own
eight tabs. I ride all eight at once with both hands for ten seconds and let go, and I
am back on exactly the page I was on. The mix is not a place I go to. It is a thing I
grab.

**Store it.** I take a **Lock snapshot** onto a pad. That pad now holds the entire
machine — every generator parameter, every level, every mute, every filter position.
That is my "intro". I build a second one with the bass in and the hats open and store it
on the next pad. That is my "main". By the time I have five pads filled I have a set.

### 1.2 Mid-set, improvising

This is the part that decides whether the machine is any good, and it is characterised
by one fact: **both my hands are busy and I am not looking down for more than half a
second at a time.**

- **Left hand lives on the F row.** F1–F8 are the eight channels and they mute. Building
  a track live is muting and unmuting, dozens of times a minute. I tap F3 out for a bar
  and back in on the downbeat. I *hold* F1 for two beats to drop the kick and it comes
  back the instant I let go — hold is momentary, tap is latched, and the difference is
  the difference between a fill and a mistake.
- **Right hand lives on the encoders.** Almost always on the CONTROL page of whichever
  channel is selected, riding cutoff and the two sends. The delay send on the lead going
  from 0 to 90 over four bars and back is half of what I do all night.
- **Group buttons are where I steer.** Tap a group, the whole right hand's meaning
  changes to that channel, no confirmation, no delay, no screen redraw I have to wait
  for.
- **The big encoder is the emergency handle.** Master level and, with a Group button
  held, *that group's* level — from any page, without leaving the page.
- **Lock pads are the arrangement.** Sixteen pads, sixteen whole-machine states, and I
  recall them **morphed over four bars, synced to the bar line**. That is a breakdown and
  a build with one finger, and it is musically far better than anything I could do by
  hand in the same four bars, because I set it up when I was calm.
- **The fill.** Hold **NOTE REPEAT**, hold a pad, and that drum rolls at the rate on knob
  1 for as long as I hold it. Release and it is gone. No recording, no undo needed.
- **The drop.** Hold **SOLO + F1**. Kick alone. Release. Everything back.
- **Rescue.** If I have talked myself into a corner — twelve knobs off, three channels
  muted, wrong key — I hit the Lock pad for "main" and in four bars the machine walks
  itself back to a state I know works, while still playing. **There is no other way to
  recover in front of an audience**, and this is the single strongest argument in this
  paper.

Note what does not appear anywhere above: loading, saving, browsing, naming, confirming,
scrolling, or waiting.

---

## 2. The interaction grammar, argued

NI's grammar is thirty years of groovebox ergonomics and I want to spend it, not
reinvent it. But this machine is a fifth of Maschine's size, and half of NI's grammar
exists to manage complexity we deliberately do not have. Here is my keep/drop, and the
argument for each.

### 2.1 KEEP — one lit button per page, always exactly one lit

**CONTROL** = what the selected channel *sounds like*. **STEP** = what it *plays*.
**ALL** = the machine's globals. Latched, mutually exclusive, one LED lit at all times,
CONTROL is home.

Why it earns its place: in a dark room the only reliable state indicator on this device
is *a lit LED next to a printed word*. The screens are two thin strips fully committed
to columns and tabs; they have no room for a page header and I do not want one. NI
solves this with the Page ◀▶ buttons and a page-dots indicator on the display; that
works because their display is big enough to show it. Ours is not. So the page must be
a lit legend.

The legends we have are unusually lucky: CONTROL, STEP and ALL happen to be exactly the
three words I would have chosen. That is not a small thing — a page whose button says
SAMPLING is a page I will press wrong forever.

**Prior art agrees and I am ratifying it, not inventing it.** I go further on one point:
**pressing the lit page button returns to CONTROL.** Home must always be one press away
from everywhere, including from itself.

### 2.2 KEEP — verb + object + value on the big encoder

This is the cleverest idea in the whole Maschine manual and prior art threw it away.
NI's shortcut grammar is:

> Press **VOLUME** (it lights). Turn the 4-D encoder → master level. **Hold a Group
> button** and turn → *that group's* level. Hold a **pad** and turn → that sound's level.
> Same for **SWING** and **TEMPO/TUNE**.

That is *verb (which parameter) + object (whose) + value (the wheel)*, and it costs zero
pages, zero screen space and zero page changes. It works from anywhere. It gives me
per-group swing and per-group tune as a **free by-product of a grammar I already know
from the master volume**.

I want this, and I want it specifically for **per-channel swing**. Prior art declares
per-channel swing out of scope. I am overruling that: shuffled hats against a straight
kick is not a nicety, it is a defining sound of the genre, and a machine where swing is
global-only will always sound like a machine. If it is expensive, say how expensive and
I will rank it — but do not delete it on my behalf.

Three verbs is all I want: **VOLUME**, **SWING**, **TEMPO** (= TUNE when an object is
held). Those three buttons exist, are labelled correctly, and are dark today.

### 2.3 KEEP — pinning, but only in one direction

NI splits modes into *temporary* (held) and *permanent* (latched) and lets you pin a
temporary one with a modifier. That generality is complexity we don't need. But the
underlying insight is exactly right and I want it applied as a **universal law**:

> **Tap = latch. Hold = momentary.** On every mode-ish button on this machine, without
> exception.

Tap SOLO → latched solo mode. Hold SOLO → solo only while held. Tap F3 → muted until I
tap again. Hold F3 → muted for as long as I hold. Tap NOTE REPEAT → rolls stay armed.
Hold NOTE REPEAT → rolls while held.

Why this is worth insisting on: momentary is how you play a *gesture*, latched is how
you make a *decision*, and live techno needs both from the same button within the same
bar. Making me choose one at design time costs me half my vocabulary. And unlike NI's
version, there is nothing to configure and nothing to remember — the rule is the same
everywhere, and your hand already knows the difference between a tap and a hold.

The threshold should be ~250 ms and should be the same everywhere.

### 2.4 KEEP — Lock snapshots with tempo-synced morphing. This is my #1 want.

NI's Lock takes a snapshot of *every modulatable parameter plus mutes and solos*, puts
64 of them on the pads, and can **morph between them synced to the bar**, with either
TRAVEL (start now, take N bars) or TARGET (start on the downbeat, land on the grid).

On a generative machine this is worth more than it is on Maschine, and here is why:
**our patterns are not data, they are parameters.** A euclidean drum channel *is* four
numbers. A Turing voice *is* six numbers plus a register. So a snapshot of the parameter
space is not a mixer scene — **it is a pattern bank, a mixer scene, a filter sweep and an
arrangement, all in one mechanism.** One feature buys everything prior art deleted when
it banned pattern chaining and song mode.

And the morph is not a garnish. Recalling a state instantly is a cut; recalling it over
four bars is a *transition*, and transitions are what a live techno set is made of. A
four-bar morph from "intro" to "main" moves eight filter positions, eight levels, three
randomness amounts and four euclid densities simultaneously, in time, while I stand
still with my hands free to do something else. I cannot do that with two hands. Nothing
else on this machine multiplies my hands.

Where it lives: **pads, when a LOCK page is active.** 16 slots is plenty; four banks is
Maschine's problem, not mine. Morph time is a knob on that page. Snapshots persist in the
Zynthian snapshot.

I know this is expensive. It is the single most expensive thing in this paper. It is also
the thing I would trade the drum filters, the drum tune, the ALL page's FX parameters,
pad velocity accents and the entire kit browser to get.

### 2.5 KEEP — Note Repeat, and Choke groups

**Note Repeat** — hold, hold a pad, roll at the rate on a knob. Prior art calls it "the
one genuinely tempting leftover" and defers it. I want it in tier 2, not tier 3. The
roll is the fill; a techno machine without a roll makes me build fills by hand out of
step edits, which takes eight seconds and I have one.

**Choke groups** — one pad silences another. Closed hat chokes open hat. This is two
lines of behaviour and it is the difference between a hat pattern that sounds programmed
and one that sounds played. Cheap, high value, tier 2.

### 2.6 KEEP — pad modes, but only two of them

Maschine has Group / Keyboard / 16 Velocities / Fixed Velocity. I want **two**:

- **PAD MODE dark** — the 16 pads are the 16 steps of the selected channel. Toggle them.
  Pad velocity when toggling on sets that step's velocity, so a hard tap is an accent and
  it costs nothing because the hardware already reads it.
- **PAD MODE lit** — the pads *play* the selected channel. On a drum: the 16 sounds of its
  kit. On a voice: 16 notes of the current root and scale.

And one borrowed extra, tier 3: **SHIFT + PAD MODE → 16 velocities** of the selected
drum sound. Sixteen pads, one sound, sixteen dynamics. For hi-hats that is an instant
humanised fill and it costs one flag.

Fixed Velocity: drop it. On a machine where the generator sets velocity and the pads
accent it, a fixed-velocity switch solves a problem I do not have.

### 2.7 DROP — and here is exactly what and why

| NI concept | Verdict | Why |
|---|---|---|
| **Master / Group / Sound three-level hierarchy** | **Drop.** One level only: the channel. | Maschine's three levels exist because a Group holds sixteen Sounds. Ours holds one. A hierarchy with a single child at every node is a hierarchy that only generates navigation. Master-level parameters live on the ALL page and nowhere else. |
| **Focus vs selection as separate cursors** | **Drop — fuse them.** | NI can have the screens showing one thing while edits land on another. That is a *studio* affordance. Live, a machine with two cursors is a machine where you turn a knob and the wrong thing changes. One channel is selected; it is what the screens show and what every knob edits. No exceptions, ever. |
| **Parameter pages within a plug-in (Page ◀▶)** | **Drop.** | Unbounded paging with no LED to say which page you are on. Our three latched pages are a *bounded, labelled* substitute. Depth here is a trap: eight knobs I can find beat forty knobs I have to hunt. |
| **Navigate mode / Page Nav / Browse** | **Drop entirely.** | There is nothing to browse. Kits are a knob. Presets are a knob. A browser on a live machine is a hole you fall into. |
| **Scenes, Sections, Patterns, the Arranger** | **Drop.** | Replaced wholesale by Lock snapshots (§2.4), which do the same job with one mechanism instead of four and are better suited to a parametric machine. |
| **Macro Controls** | **Drop the mechanism, keep the idea for tier 3.** | NI's macros need a mouse to assign, which disqualifies them from a hardware-only machine. But the *idea* — one page of eight knobs I chose myself, reaching anywhere in the machine — is exactly what a performer wants once the machine stops being new. See PERFORM page, tier 3. |
| **Scale / Chord / Arp engines** | **Drop Chord and Arp. Keep scale as a global quantiser.** | The Turing machine is our note generator; an arpeggiator on top of it is two generators fighting. `ROOT` + `SCALE` on the ALL page, quantising everything, is all the harmony logic this machine needs. |
| **Sampling, Auto Write, Duplicate, Select, Scene, Pattern, Navigate, Main, View, Grid-as-quantise** | **Drop. Dark buttons.** | Dark buttons are not a wart. A dark button is a promise that nothing surprising is behind it. |

### 2.8 Where I disagree with the prior-art mapping

Six points, in order of how strongly I hold them.

1. **F1–F8 must be MUTE, not solo.** Prior art assigns solo to the F row and mute to
   SHIFT+Group. Wrong way round. I mute perhaps sixty times in a set and solo perhaps
   four. The most-used gesture on the machine gets the eight easiest buttons with the
   eight LEDs above the eight tabs, unmodified, one hand. Solo goes to **SHIFT + Fn**,
   or better to the **SOLO button held + Fn**, using the legend that already says SOLO.
2. **The big encoder is not "optional master volume".** It is the object-and-value half
   of §2.2 and it is where per-channel level, swing and tune come from. Prior art treats
   it as a nice-to-have because it is unverified in the daemon. Verifying it is one
   afternoon and it unlocks three parameters per channel with no page cost. Do the
   afternoon.
3. **ERASE must be hold-and-target, never a bare press.** Prior art has ERASE clear the
   selected channel on a press. In front of people that is a landmine. NI's grammar is
   right: **hold ERASE + tap a pad** deletes that step; **hold ERASE + tap a Group**
   clears that channel. Nothing destructive happens on a single press, anywhere on this
   machine.
4. **I want CHANCE on the drum STEP page**, and I will trade `ACCENT` for it. Per-channel
   probability — each generated hit fires with probability *p* — is the highest-value
   generative control after euclid itself, because it turns a loop into something that
   never quite repeats. Two knobs of the drum step page are currently blank in prior art;
   this is what one of them is for.
5. **Per-channel swing.** Covered in §2.2. Prior art rules it out on implementation
   grounds. That is not a product decision.
6. **ROOT changes must land on the bar.** Prior art does not say. A live root change that
   takes effect mid-phrase is a glitch, not a modulation. Which leads to the law below.

### 2.9 The one law I want written into the design

> **Timbre changes land instantly. Structure changes land on the bar.**

Filter, level, sends, drive, gate, velocity, randomness → immediate, continuous, no
quantisation, no smoothing I can hear.

Root, scale, division, pattern length, Lock recall, kit change → **quantised to the next
bar**, with the screen showing the pending value so I know it took.

Every groovebox that feels good obeys some version of this and every one that feels
cheap does not. It is also the thing that makes the machine forgiving: I can press the
next Lock pad any time in the bar and it lands right.

---

## 3. Ranked features

### TIER 1 — PROTOTYPE: the smallest thing I would actually play

If I got only this, I would still take it to a rehearsal room.

1. **Eight channels that always exist.** 5 euclidean drums (A–E) + 3 Turing voices
   (F–H), from a snapshot, never constructed at run time. Group A–H selects; the tab
   inverts; the group LED carries the channel colour and its level as brightness.
2. **Two generator pages that make music.** Drum STEP = `HITS ROTATE DIVIDE LENGTH` +
   `VELO`. Voice STEP = `LENGTH DIVIDE RANDOM GATE` + `OCTAVE RANGE DENSITY VELO`.
   RANDOM is continuous and instant: turn up to mutate, snap to zero to lock the line
   as it stands.
3. **CONTROL page per channel, with encoders 7 and 8 as REVERB and DELAY on every
   channel of both types.** Insert FX is an acceptable prototype mechanism; a shared
   send is better and can come later without changing a single knob.
4. **F1–F8 mute, tap-to-latch and hold-for-momentary. Play, Restart, hold-ERASE.**
   Pads are the sixteen steps of the selected channel with a white playhead; pad
   velocity sets step velocity.
5. **ALL page: `ROOT SCALE BPM SWING` + the screens as prior art draws them** — tabs,
   dotted rule, name over a double-height value over an indicator bar. Everything saved
   in one Zynthian snapshot.

That is a playable instrument. It is roughly the shipped drum rig plus three Turing
voices, sends, and a second page.

### TIER 2 — THEN: the first extensions, in the order I want them

1. **Lock snapshots with bar-synced morphing.** The biggest single jump in musical value
   on this list. It converts a jam machine into a set machine. *If the developer tells me
   tier 2 can hold exactly one item, it is this one.*
2. **Verb+object+value on the big encoder** — VOLUME / SWING / TEMPO lit, hold a Group,
   turn. Delivers per-channel level, **per-channel swing** and per-channel tune with no
   page cost.
3. **SHIFT held = the mixer** — eight encoders as eight faders under their own tabs, from
   any page, released back to where I was.
4. **Note Repeat** (hold + pad + rate knob) and **Choke groups** (closed hat kills open
   hat).
5. **CHANCE per drum channel** and a **PAD MODE play layer** with live record onto the
   running pattern.
6. **SOLO held + Fn**, momentary, for drops.
7. **A real shared reverb bus and a shared delay bus**, so encoders 7/8 become sends and
   the whole mix sits in one space. Musically this is the difference between eight dry
   channels with effects on them and a record.

### TIER 3 — DREAM: where it ends up

1. **A PERFORM page** — eight encoders I assign myself, each pointing at any parameter
   anywhere in the machine, assigned *from the hardware* (hold a PERFORM slot, turn the
   target knob, done). This is NI's Macro Control idea with the mouse removed. Once the
   machine stops being new, this is the page I would actually stand on all night, because
   my set has eight moves in it and they are never all on one channel.
2. **Morph targets as a performance axis, not just a recall** — a knob that morphs
   continuously between the current state and a chosen Lock slot, so I can ride halfway
   into the breakdown and back out. This is the single most expressive control I can
   imagine on this instrument.
3. **Per-channel pattern variation as a *second* Lock layer**, so a Lock pad can carry
   only the generator parameters and leave the mix alone, or vice versa. Scoped recall.
4. **Sidechain ducking from channel A**, with an amount knob per channel. Techno is
   pumping; a machine that cannot pump needs an external compressor and then it is not a
   self-contained instrument.
5. **Per-drum kit switching across all 42 SFZ drum machines from the surface**, already
   half-built, plus per-channel `TUNE` / `DECAY` / `FILTER` / `DRIVE` that actually exist
   as parameters rather than as blank columns.
6. **16-velocity pad mode** for hat fills, and pad aftertouch mapped to filter on the
   selected voice.
7. **A second Turing layer per voice generating velocity rather than pitch**, so the
   voices accent themselves.
8. **Tape-stop / gate / reverse as three momentary buttons on the master.** Pure garnish,
   pure fun, last.

### What I sacrifice first, honestly

In order, the things I would give up without much pain:

1. **PAN.** Set once, never touched. Not on the surface at all — prior art is right.
2. **Drum `TUNE` / `FILTER` / `DRIVE` / `DECAY`.** I want them, but if they need an LV2
   per drum chain and that costs the Pi its headroom, I will take four blank columns and
   pick better samples instead. Choosing the right kit is 80 % of the sound anyway.
3. **The ALL page's four FX-parameter columns.** Fix the reverb and delay to a good
   setting and give me the sends. I tune reverb size perhaps once a night.
4. **Pad-velocity accents.** Nice; the generator's `VELO` and `ACCENT` cover most of it.
5. **The kit browser on a knob.** If it turns out to be slow or glitchy mid-set, freeze
   the kits per snapshot and I will pick them at home.
6. **16 velocities, aftertouch, tape-stop, everything in tier 3 items 6–8.**

What I will *not* trade away is in §4.

---

## 4. Non-negotiable

Four things. If any of these is missing the machine is a toy and I will not take it out
of the house.

### 4.1 The machine never stops making sound, and never asks me anything

No dialogue. No confirmation. No "are you sure". No page that mutes anything on entry.
No mode I can enter and not know how to leave — **CONTROL is always one press from
anywhere, including from CONTROL.** No load, save, or snapshot recall that drops a bar or
introduces a click. No knob that is silently dead: if a parameter does not exist on this
channel, the screen greys the column and says so, because a knob that does nothing and
does not admit it is the worst object on a control surface.

And no crash. The shipped rig has already killed the whole UI once, ninety-five seconds
into a jam, over a threading bug. That must never happen again, and I would rather have
tier 1 only and rock-solid than tier 2 and a segfault.

### 4.2 Encoders 7 and 8 are REVERB and DELAY, on every channel, on every type, forever

This is the one piece of absolute muscle memory in the machine. It survives every channel
change and every page change. It is the thing my right hand reaches for without looking,
in the dark, mid-phrase, on a channel I selected half a second ago and have not read the
screen for. The moment there is an exception — one channel where knob 8 is something
else — the memory is worthless and I am reading screens again.

The mechanism behind it (true send, insert, or hybrid) is the developer's to choose and I
genuinely do not care, as long as the knobs never move.

### 4.3 RANDOM must lock the line *in the moment I turn it to zero*

The Turing voice is the reason this instrument exists. The gesture is: turn RANDOM up,
listen for two bars, hear a phrase you want, snap the knob to zero and keep that phrase.

That requires three things and all three are non-negotiable. The knob must be continuous
and instantly audible — no ramp, no smoothing, no "applies next cycle". Zero must mean
*absolutely locked*: the register repeats forever, bit-identical, with no drift. And the
lock must capture **the register as it stands at that instant**, not as it was at the last
cycle boundary and not as it will be at the next one. If turning the knob to zero
sometimes gives me the bar I heard and sometimes gives me the one after, the gesture is
gambling instead of playing, and the voice concept is dead.

### 4.4 One channel, one cursor, no ambiguity

At every instant exactly one channel is selected, every encoder edits that channel, the
screens show that channel, and the selection is visible in two independent ways at once
(the inverted tab and the group LED). Selecting is one tap with no confirmation and takes
effect before my finger leaves the button. There is never a state where the screen shows
one channel and a knob edits another.

---

## 5. Open musical questions for the developer

Ordered by how much of the design moves depending on the answer.

1. **Can a Lock snapshot morph?** Not "can you store and recall parameters" — recall is
   easy and half the value. Can you interpolate every stored continuous parameter from
   current to target over N bars, on the bar line, without zipper noise and without
   fighting whatever else is writing those parameters? If interpolation is impossible but
   instant recall is cheap, tell me — I will take instant recall in tier 2 and put morph
   in tier 3, and it changes nothing else in this paper. If *neither* is possible, we need
   to reopen arrangement entirely and I will want pattern variation instead.

2. **Is per-channel swing reachable at all?** Prior art says the step grid forbids it. Is
   that a zynseq constraint or a "we'd have to generate the notes off-grid" constraint? If
   I can get swing by having the generator place notes at non-quantised clock positions
   rather than by asking the sequencer to shuffle, say so — I do not care how it is done,
   only that hats can shuffle against a straight kick.

3. **Shared FX bus or sixteen inserts — and what does each cost in CPU on this Pi?** I
   want the number, because I would trade two drum channels for a shared reverb. A shared
   tail is what makes eight sources sound like one record. If the answer is "inserts fit,
   sends don't", tell me and I will accept inserts — but tell me rather than deciding it
   quietly.

4. **How fast is a kit change, honestly?** If sweeping the KIT knob reloads a sampler and
   costs 200 ms of silence, it is not a live control and it should be moved off the
   performance page and into "set up at home". Measure it before we design around it.

5. **How much latency is there from pad hit to sound, and from knob turn to audible
   change?** Give me a number. Anything above ~10 ms on the pads and I am not playing
   fills on this thing; anything above ~30 ms on the knobs and filter sweeps feel like
   they are happening to someone else.

6. **When I lock a Turing register and save the snapshot, does the exact line come back?**
   The register state must be *in* the snapshot, not regenerated from a seed. If it is
   regenerated, every reload gives me a different bassline and my set does not exist.

7. **Where does note velocity actually come from on each engine?** I have `VELO`,
   `ACCENT` and pad velocity all wanting to write it. Tell me which engines respond to
   velocity at all, so I do not put a knob on a screen that moves nothing.

8. **Can the machine free-run, or does the transport have to be running for the pads to
   sound?** I want to audition sounds and finger-play with the sequencer stopped. This is
   a small thing that turns out to matter every single time you set up.

9. **What happens on the bar where I change DIVIDE or LENGTH?** I have asked for
   structure changes to land on the bar. Is that natural to the sequencer, or does it fight
   it? If it fights, I would rather hear a clean immediate change than a mangled quantised
   one — but I want to know which we are getting.

10. **How many Lock slots can we afford, and what exactly is in one?** My answer is
    sixteen and "everything a knob can move, plus mutes". If storing "everything" is
    unworkable, I want to negotiate the contents explicitly — a Lock that silently omits,
    say, the euclid parameters is worse than no Lock at all, because I will trust it and
    it will lie to me on stage.

---

## 6. PO rulings, 2026-08-09 (in answer to the PM)

Recorded so the trades are not lost. These override the tiering above where they conflict.

1. **Turing mutation may be per-cycle, not per-step — with one condition.** Mutation must
   be applied *incrementally to the existing register*, so low RANDOM means one note drifts
   per bar. If a cycle regenerates a fresh line from scratch, it is a random-line generator
   and not a Turing machine, and I object. **One-cycle undo is PROTOTYPE**, not later — it
   is one array copy and it is the only thing protecting the gesture in §4.3 from human
   reaction time.
2. **Sends: inserts accepted** for prototype and tier 2, shared bus only if a later
   measurement finds room. Condition: the eight instances must be **ganged by default** —
   one set of reverb/delay parameters driving all eight from the ALL page — so the channels
   at least share a room's character. Encoders 7/8 never move either way.
3. **Big encoder dropped.** Held-verb + eight small encoders (SHIFT = level, SWING = swing,
   TEMPO = tune, across all eight channels at once) supersedes §2.2 and is better. Verb
   buttons obey §2.3 — tap latches, hold is momentary. Master volume lives on the
   touchscreen for the prototype.
4. **Lock: 8 slots with morph** beats 16 without. Morph is a superset — time 0 *is* instant
   recall. If the interpolation itself is the cost, take instant-recall-on-the-bar first.
   A Lock slot that silently omitted **mutes and solos** would destroy trust on stage; the
   Turing register is the close second and must also be in.
5. **Drum STEP page columns:** `HITS ROTATE DIVIDE LENGTH | VELO CHANCE SWING RATCHET`.
   **ACCENT is dropped** — it is the only one of the four I can fake by other means.
   **Voice STEP page column 7 = SWING**, matching the drum page position exactly:
   `LENGTH DIVIDE RANDOM GATE | OCTAVE RANGE SWING VELO`.

---

## 7. Summary card — what I am asking for

```
PROTOTYPE   8 channels always alive · euclid drums + Turing voices
            CONTROL / STEP / ALL as three lit pages
            enc 7/8 = REVERB + DELAY, everywhere, forever
            F1-F8 mute, tap=latch hold=momentary
            pads = steps, Play / Restart / hold-ERASE

THEN        LOCK snapshots with bar-synced morph      <- the big one
            VOLUME/SWING/TEMPO + hold Group + big encoder
            SHIFT held = 8 faders
            Note Repeat · Choke · CHANCE · SOLO held
            one shared reverb bus, one shared delay bus

DREAM       PERFORM page — 8 knobs I assign from the hardware
            continuous morph toward a Lock slot as a knob
            sidechain pump · scoped Lock layers · real drum tone controls

NEVER TRADE never stops, never asks       enc 7/8 never move
            RANDOM→0 locks THAT bar       one channel, one cursor
```
