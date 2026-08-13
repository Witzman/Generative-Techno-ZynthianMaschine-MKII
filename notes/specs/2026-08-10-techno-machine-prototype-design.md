# The Techno Machine, prototype — Design

**Date:** 2026-08-10
**Status:** ratified by the project owner, ready for an implementation plan
**Scope:** the **prototype only**. Five euclidean drum channels (A-E), three
Turing voices (F-H), all eight in one prepared snapshot, per-channel reverb and
delay, played entirely from the Maschine MK2.
**Source:** `docs/superpowers/techno-machine/2026-08-09-techno-machine-design.md`
(the arbitrated design artefact) plus the owner's ratification of its six
contested decisions, 2026-08-10. Where this spec and the artefact differ, this
spec wins and says why.
**Builds on:** `2026-08-06-maschine-drum-rig-design.md` and
`2026-08-09-maschine-sfz-kits-design.md` — the shipped, hardware-verified rig
this extends.

> **The prototype requires no Maschine daemon work at all.** No Rust, no
> `git bundle` deploy dance, no re-setting `"external_pad_leds": true`, no second
> firmware-side risk. Every control it binds already emits CC today. This falls
> out of the owner's ruling that F1-F8 are MUTE (already shipped) and that solo
> lives on SOLO (CC 31, already emitting), which together removed SHIFT from the
> critical path. It is the single largest risk reduction in the design and it
> reorders the build: **snapshot, then measurement, then driver.**

---

## Problem

The shipped rig is eight euclidean drum channels and nothing else. Three things
it cannot do are the three things a live techno set is made of:

1. **No melodic material.** Every channel is a drum kit note. There is no bass,
   no lead, no pad, and no generative pitch source of any kind.
2. **No space.** There is no reverb and no delay anywhere in the signal path.
   The one gesture that carries a techno track — the delay wet on the lead going
   0 to 90 over four bars and back — is unavailable.
3. **No sound-shaping per channel.** LinuxSampler exposes no controllers at all
   (`zynthian_engine_linuxsampler` inherits `_ctrls = []`), which is why the
   shipped rig drives volume and pan from the mixer strip. Two encoders on the
   surface currently do nothing that changes character.

The prototype fixes all three without changing the parts that already work.
Sequencing stays in zynseq, so patterns persist in snapshots and the touchscreen
editor keeps mirroring them. The daemon stays a dumb control surface.

**What it is, in one paragraph.** A generative groovebox. Eight channels, all
alive from power-on, never constructed at run time. Three latched page buttons
decide what the eight encoders mean; the eight Group buttons decide which channel
they point at. There is no song mode, no browser, no dialogue and no
confirmation. The touchscreen exists to save snapshots and to hold the master
fader.

---

## Cost, measured

What is already known, from the shipped rig and from the developer's audit of the
**installed** Zynthian on the Pi (not the local checkout):

| Measure | Result | Source |
|---|---|---|
| Eight SFZ kits, live, 180 s jam | 6.2% system CPU, peak 15% of 400%, 249.5 MB sampler RSS, 3.0 GB free, **zero xruns** | SFZ kit spec, hardware-verified 2026-08-09 |
| Kit load / live swap | 0.06 s mean load, five consecutive live swaps at 0.005-0.043 s, no glitch | same |
| JACK headroom | `-p 512 -n 3` at 48 k = **10.7 ms of wall clock per callback** | `ps aux \| grep jackd` |
| Zynthian UI cost | ~37% of one core, load avg 0.68 of 4.00 | `top -bn1`, `uptime` |
| Mixer strip budget | `MAX_CHANNELS 17`, strip 16 is main → **16 usable, hard** | `mixer.c:48`, `getMaxChannels()` = 17 |
| Chain routing | every destination gets the identical source at unity — **on/off only, no per-destination gain** | `zynthian_chain.rebuild_audio_graph` |
| A route out of a chain | **post-fader**, `sources = ["zynmixer:output_NN"]` | same, line 361 |
| `setSequenceLength` | **absent** from the installed `.so`. Whole-beat quantisation stands | `nm -D --defined-only libzynseq.so` |

What is **not** measured, and therefore gated below: the cost of sixteen new
plugin instances, the controller lists of the three voice engines, and whether
the chosen reverb and delay have a wet control that does not eat the dry signal.

---

## Gates — three tasks, before any driver code

These are first-class tasks, not caveats. Each is cheap, each can kill or reshape
a page of this design, and each must complete and be written up before the driver
is touched. The SFZ kit work's Task 0 caught a design-breaking issue in an hour
by exactly this method — LinuxSampler's empty `_ctrls`, which moved volume and
pan to the mixer and saved a rewrite.

### Gate G1 — FX cost

**Question:** can this Pi carry 8 chains x (reverb + delay) on top of 8 sampler
kits?

**Precondition, mandatory:** **move jackd to `hw:S2` at 44.1 kHz first.** Every
CPU and xrun number this project has ever taken — including the ~6% for the
shipped rig — was on `-d hw:Headphones -r 48000`, which is not the interface the
instrument plays through. Any measurement taken before the move is worthless.

**Method:** build the prepared snapshot with all sixteen inserts in place, then
run five minutes with all eight channels playing at 16ths and record:

- CPU (system and per-process), RSS total and per `jalv` process
- xruns over the run
- **snapshot load time**, cold
- pad hit → sound (must be under ~10 ms) and knob turn → audible change
  (under ~30 ms)
- audio glitch on a live kit change with a pattern running

**Fail thresholds:** more than ~10% of one core for the sixteen inserts, or
snapshot load past ~15 s.

**Degrade path, in this order, and no other:**

1. **Cheaper plugins.** The prototype already starts at the cheap end — see
   Topology — so the next step is cheaper still, or dropping the reverb to one
   shared character setting written to eight instances.
2. **Cut the channel count from 8 to 6.** Both knobs stay live on every channel
   that exists.

**Never a shared bus.** A shared FX chain fed by per-channel routing on/off turns
knob 7 into a toggle wearing a knob's clothes. It breaks the one absolute muscle
memory in the machine and it is off the table as a degrade, permanently.

### Gate G2 — Engines

**Question:** do the three voice engines exist on the Pi, and what does each one
actually expose?

The artefact proposes **JC303** (bass), **Obxd** or **Surge XT** (lead),
**padthv1** or **ZynAddSubFX** (pads). What has been checked so far is
`engine_config.json` — an `ENABLED == true` flag, which is a config assertion,
**not** proof that the LV2 is installed or that it publishes any controllers.

Today's lesson is concrete and expensive: LinuxSampler is "enabled", works, makes
sound, and exposes **no controllers at all**. Designing a CONTROL page against an
assumed controller list is how you get four dead knobs on stage.

**Method,** on the Pi (`ssh root@192.168.2.123`), per candidate engine:

1. Confirm the plugin is installed and instantiable — `lv2ls`, `lv2info`.
2. Load one chain on it and **enumerate `processor.controllers_dict`** — every
   symbol, its range, and whether it is a real continuous parameter.
3. Record which of `CUTOFF`, `RESO`, `ENV`, `DECAY`/`ATTACK` each engine can
   supply, and by which symbol.
4. Measure load time and RSS per instance — three synth engines are three more
   processes on top of G1's sixteen.

**Output:** a table of engine → symbol per CONTROL column. The voice CONTROL page
is designed **against that table**, not against the artefact's guesses. Any
column with no symbol draws greyed and inert, by the law below. If an engine is
missing or bare, substitute from the enabled list (Surge XT, Helm, synthv1,
amsynth, Monique, Nekobi, Odin2, MiMi-d, Dexed, ZY) — the channel role is a table
entry, so this is a config line, never a redesign.

### Gate G3 — Wet parameter

**Question:** do the chosen reverb and delay each have a **usable wet control
that does not crossfade the dry signal away?**

This is not hypothetical. CAPS PlateX2's `blend` is a **crossfade, not an
additive wet** — knob 7 at maximum kills the dry. A crossfade fails the owner's
rule that encoders 7 and 8 are REVERB and DELAY on every channel forever, because
what the player gets is a dry/wet morph, not a send.

**Method:** for each candidate, `lv2info` the port list, then on one channel sweep
the wet parameter 0 → 100 with a steady source and **measure the dry level at
both ends**. Also confirm each is **stereo in, stereo out** — ZamDelay is mono in
and was rejected for exactly this, and a mono insert doubles the process count.

**Rule:** prefer a plugin with a genuine separate wet level. If the best
available candidate only offers a crossfade, cap the knob at ~0.45 of plugin
range and record that the column is a blend, not a send — but exhaust the
enabled list first (`JV/MDA Ambience`, `JV/MDA DubDelay`, `JV/GxEcho-Stereo`,
`JV/Tal-Reverb-II/III`, `JV/Gxdigital_delay_st`) before accepting it.

**Also settled at this gate:** which plugin parameter each of the four ganged FX
columns on the ALL page addresses (`REVSIZE`, `REVDAMP`, `DLYTIME`, `DLYFBK`),
and whether the delay's time parameter can be driven in milliseconds from
`getTempo()` or needs a normalised mapping.

---

## Design

### Topology

One new prepared snapshot. `021-maschine-drum-rig-sfz` is left untouched as a
working fallback, exactly as `020` was kept when `021` was built.

| Group | Name | Type | Hue | Engine | MIDI ch |
|---|---|---|---|---|---|
| A | KICK | drum | red | LinuxSampler, SFZ drum machine | 1 |
| B | SNAR | drum | orange | LinuxSampler | 2 |
| C | CLAP | drum | amber | LinuxSampler | 3 |
| D | CHAT | drum | yellow-green | LinuxSampler | 4 |
| E | OHAT | drum | green | LinuxSampler | 5 |
| F | BASS | voice | blue | per gate G2 (JC303 proposed) | 6 |
| G | LEAD | voice | violet | per gate G2 (Obxd / Surge XT proposed) | 7 |
| H | PADS | voice | cyan | per gate G2 (padthv1 / ZY proposed) | 8 |

Drums warm, voices cool, so the seam between the two halves is visible on the
panel without reading anything. **The roles are a table in the driver**
(`CHANNELS = [...]`), so 5+3, 4+3+spare or 4+4 stays a config line.

Each chain carries a **post-fader insert reverb and insert delay**, placed once
in the prepared snapshot via
`chain_manager.add_processor(chain_id, ..., post_fader=True)`. Post-fader means
the insert is fed from `zynmixer:output_NN` and therefore already follows the
channel's fader **and its mute** — every assumption the shipped rig makes about
the mixer strip survives untouched.

**Start with the cheapest plugins.** `JV/MDA Ambience` and `JV/MDA DubDelay`
class, not PlateX2 and `Gxdigital_delay_st`. Two reasons, both the owner's: it
turns G1 from a critical-path gate into a cheap one, and both MDA plugins are
already **enabled** in `engine_config.json` whereas PlateX2 is installed but not
enabled. Upgrade only if G1 leaves headroom, and only to a plugin that passes G3.

**Not built: true sends.** A correct send-tap topology needs 8 channels + 16 taps
+ 2 returns = **26 mixer strips against a hard 16**. Raising `MAX_CHANNELS` is
realtime C in the routing core every Zynthian chain uses, +64 JACK ports, and
both the snapshot format and the touchscreen mixer assume 16. Refused. The insert
satisfies the contract literally, and for a non-obvious reason worth recording:
**the wet parameter is a plugin zctrl, not an engine zctrl**, so LinuxSampler's
empty `_ctrls` — the thing that killed volume and pan on the drum chains — cannot
bite here. Both knobs are live on drums and on voices with no exception.

**What is honestly lost:** no shared tail, so eight small rooms never glue into
one big room; and no duckable, EQ-able return, so sidechaining the reverb against
the kick is unavailable. Both are pass three, and both are blocked on core work
that is currently refused.

**The eight inserts are ganged by default.** One set of reverb and delay
parameters on the ALL page drives all eight instances, so the channels share
size, damping, delay division and feedback. Identical character in eight boxes is
most of the way to a coherent space. Per-channel divergence is a later opt-in and
is not built. Only the per-channel **wet** amounts differ, on encoders 7 and 8.

### Controls — global, identical on every page

Every control below emits today. Nothing here needs a daemon change.

| Control | CC | Function |
|---|---|---|
| **Group A-H** | 80-87 | Select the channel. Pads, both screens' columns, CONTROL and STEP all follow. Takes effect before the finger leaves the button |
| **CONTROL** | 11 | Page: what the channel *sounds like*. **Home.** Pressing it while lit does nothing |
| **STEP** | 32 | Page: what the channel *plays*. Pressing it while lit returns to CONTROL |
| **ALL** | 38 | Page: the machine's globals. Pressing it while lit returns to CONTROL |
| **F1-F8** | 39-46 | **Mute** channel A-H regardless of selection, on the mixer strip. Tap = latched, hold (>250 ms) = momentary |
| **SOLO** | 31 | Hold + Fn = momentary solo of channel *n*. Tap = latched solo mode, the F row becomes solos until tapped again |
| **Play** | 1 | Start / stop all eight sequences via `setPlayState` on each — **never `TOGGLE_PLAY`** |
| **Restart** | 7 | Every channel to step 0 |
| **Erase** | 2 | **Hold only.** A bare press does nothing. Hold + pad clears that step; hold + Group silences that channel |
| **Duplicate** | 29 | "Give it back." On a voice: restore the previous Turing register, force RANDOM to 0, rewrite now; repeated presses walk back up to 4 deep. On a drum: restore the previous generator parameter set |
| **Arrows beside the display** | **5 / 6** | Previous / next **sound** for the selected channel — sample within the kit on a drum, engine preset on a voice |
| Everything else | — | **Dark, deliberately.** A dark button is a promise that nothing surprising is behind it |

**Do not bind the Page ◀▶ pair (CC 47/48).** The daemon swallows them for its own
page indicators and never emits them. And **dump `a2j:...Pads MIDI` with
`jack_midi_dump` before binding any button** — the CC 5/6 versus CC 13/14
physical pairing is unconfirmed in the reference and has bitten this project
before.

**F1-F8 are mute, not solo**, because the owner mutes perhaps sixty times in a
set and solos perhaps four, and the most-used gesture gets the eight easiest
buttons. It is also what the shipped rig already does, so it is zero work and
zero regression risk.

**Legend wart, accepted and recorded:** *Duplicate* does not read as *undo*. No
legend on this device does. It is the least-wrong available and it does exactly
one thing on every channel type.

**Solo is on SOLO because the F row is spoken for.** `zynmixer.toggle_solo` is
additive and has a special case at `MAX_NUM_CHANNELS - 1` (main strip clears
all). Exclusive solo (SHIFT + Fn) is pass two, when SHIFT emits.

### Laws

These are laws, not preferences. Every page obeys them.

**L1 — Tap latches, hold is momentary.** Threshold ~250 ms. Applies to F1-F8 and
to SOLO. Momentary is how you play a gesture, latched is how you make a decision,
and live techno needs both from the same button inside the same bar. It does
**not** apply to the three page buttons, which are latch-only and mutually
exclusive — a momentary page is a page you cannot two-hand.

**L2 — Timbre lands instantly, structure lands on the bar.**

| Instant, continuous, no smoothing | Quantised to the next bar, pending value shown |
|---|---|
| level, wet/sends, cutoff, reso, env, decay, gate, velocity, RANDOM, CHANCE, SWING | ROOT, SCALE, DIVIDE, LENGTH, KIT, preset |

DIVIDE and LENGTH are already whole-beat quantised by zynseq
(`getLength() = beats × PPQN`, no `setSequenceLength` in the installed C API), so
this is with the grain, not against it.

**L3 — Nothing destructive happens on a single press, anywhere.** ERASE is
hold-and-target only. "Clear that channel" on a generator-owned pattern means
**set the generator to silence** (drum: HITS → 0; voice: CHANCE → 0), not wipe
the note list — a wiped note list is overwritten by the next generator move and
the erase would appear not to have worked.

**L4 — A column whose source does not exist draws greyed and its encoder is
inert.** Greyed reads as a lower-case name, `----` in the value cell, and no
indicator bar. A knob that does nothing and does not admit it is the worst object
on a control surface. Three greyed columns on the drum CONTROL page is thin and
honest; a lie is not.

**L5 — One channel, one cursor. The inverted tab is authoritative.**

**L6 — RANDOM → 0 keeps the loop you are hearing, bit-identical, forever.**

### Pads

| State | Behaviour | LED |
|---|---|---|
| **Default, and the only state in the prototype** | Toggle step *n* of the selected channel's zynseq pattern. Pad velocity sets that step's velocity when toggling it on, so a hard tap is an accent — free, the hardware already reads it | dim = empty · bright = active, scaled by step velocity · **white = playhead** |
| Steps beyond `LENGTH` | dark and inert | dark |
| Hold ERASE + pad | clear that step | — |

**Pattern authority: the generator owns the pattern.** Pad taps edit on top of
it; the next generator move wipes them. No hidden per-step override state, no
third LED colour. On a voice, a pad tap toggles whether a step *sounds*, keeping
the pitch the Turing machine put there — which is exactly the rest-editing you
want.

**Pattern length is quantised to whole beats** and always will be. Reachable
lengths are `beats × steps_per_beat`; 1, 5, 7, 11 and 13 are unreachable with the
current divisions. Known and accepted.

Step 0 is the **top-left** pad. LED index for a step is `PAD_OFFSETS[step]` with
`PAD_OFFSETS = [12,13,14,15,8,9,10,11,4,5,6,7,0,1,2,3]` (its own inverse).

### The drum model — euclidean

Unchanged from the shipped rig. `euclid(hits, length, rotate)` is an existing,
unit-tested pure function in `maschine_mk2_lib.py`. Notes are written with
`addNote(step, note, velocity, duration, offset)` at the channel's `VELO`.
`DIVIDE` is `setStepsPerBeat` 8/4/2/6/3 for 1/32, 1/16, 1/8, 1/16T, 1/8T. A
division change always regenerates from euclid, because `setStepsPerBeat`
rescales existing notes.

Triplet divisions give 12 steps, not 16, so pads 13-16 go dark on those channels.
Channels phase against each other by design — that is the polyrhythm.

### The voice model — Turing machine

The instrument's central idea. Get this wrong and there is no reason to build
anything else.

**The register is persistent and mutation is incremental.** Each voice owns one
shift register of `LENGTH` bits (2-16). `RANDOM` is the **per-step bit-flip
probability applied as the register is clocked forward through a cycle** — never
a fresh line generated per wrap. Low RANDOM must mean "one note drifted this
bar"; a machine that regenerates the whole line each cycle is a random-line
generator, not a Turing machine, and the slow drift *is* the musical value.

**The pattern is rewritten only on a playhead wrap**, from the driver's existing
30 Hz poll thread, under `self.lock`. The audible line is therefore bit-constant
for the whole cycle **by construction**. This is why "RANDOM → 0" gives an
instant, exact lock for free: it means precisely "skip the next rewrite", so the
loop being heard is the loop kept, forever, because nothing rewrites it. There is
no compromise here and none is needed — the two requirements were never in
conflict.

**Cost of the model, accepted:** mutation granularity is per cycle, not mid-bar.
Drift lands on the bar line. This is the same trade as L2.

**A 4-deep register ring per voice, in the prototype.** The one residual gambling
window is human reaction time — the wrap fires and replaces the phrase before the
hand lands on the knob. The register is one integer of ≤16 bits, so a 4-deep
`deque` costs nothing and covers roughly two wraps of reaction (~1.8 s per cycle
at 132 BPM). **Duplicate** pops it: restore the previous register, force RANDOM
to 0, rewrite now. Repeated presses walk back up to four deep.

**Pitch derivation.** The register's bits are read as an unsigned value, scaled
across `RANGE` octaves, quantised to the global `ROOT` and `SCALE`, and
transposed by `OCTAVE`. The quantiser is a second pure function in the lib, unit
tested. Additionally call `setScale` / `setTonic` on each pattern so the
touchscreen editor draws the right keyboard — free, persisted, cosmetic; it does
**not** quantise incoming notes.

**Rests come from `setPlayChance`, never from rewriting the pattern.** This is
load-bearing, not a nicety: it removes the need to rewrite the pattern for
density at all, which directly cuts the largest risk in the design.

**`GATE` is the `duration` argument of `addNote`** — a `c_float` already declared
in the wrapper. Free parameter on a call the driver already makes.

**Lock discipline, non-negotiable.** `libzynseq` is not thread-safe and the
driver reaches it from three threads. Unsynchronised access has already killed
the entire Zynthian UI with SIGSEGV, exit 139, about 95 seconds into a jam. The
Turing machine adds a fourth access pattern — a `clear` plus 8-16 `addNote` burst
at each cycle boundary, three voices over, roughly every 0.6 s at 132 BPM.

- **Every** zynseq / libseq call holds `self.lock`.
- **One lock acquisition per burst**, not per note.
- `selectPattern()` exactly once per burst and **never** in the poll hot path —
  it writes zynseq's single global pattern selection and fights the touchscreen
  pattern editor for it.
- Clocks-per-step is cached so the hot path never calls into zynseq for it.
- **Never hold the lock across a preset load** (kit or engine preset). That path
  runs on its own timer thread, as the SFZ work established.
- Never drive anything step-rate-sensitive from `SS_SEQ_PROGRESS` — it is 5 Hz
  and aliases against the step rate.

### CONTROL page — what the selected channel sounds like

> **The right-hand trio: encoders 6, 7 and 8 are LEVEL, REVERB and DELAY on every
> channel of every type.**

**Drum channel**

| Enc | Panel | Name | Value | Bar | Source |
|---|---|---|---|---|---|
| 1 | L1 | `KIT` | 4-char abbrev | segmented | LinuxSampler preset — the 41 SFZ drum machines |
| 2 | L2 | `SAMPLE` | 4-char name | segmented | note within the kit |
| 3 | L3 | `tune` | `----` | — | **greyed, inert.** No source exists |
| 4 | L4 | `decay` | `----` | — | **greyed, inert** |
| 5 | R1 | `filtr` | `----` | — | **greyed, inert** |
| 6 | R2 | `LEVEL` | 0-100 | unipolar | `zynmixer.set_level`, engine-independent |
| 7 | R3 | `REVERB` | 0-100 | unipolar | insert reverb wet |
| 8 | R4 | `DELAY` | 0-100 | unipolar | insert delay wet |

KIT and SAMPLE deliver more character than a filter would, and both are shipped
and hardware-verified. KIT commits ~150 ms after movement stops, then previews
the channel's note once so the choice is audible; sweeping the whole list costs
one load, not 41. On a kit change the channel lands on the nearest available note
to the one it had, so it never falls silent.

**Voice channel** — column names are **provisional until gate G2**. The four
left-hand columns are filled from that gate's engine → symbol table; anything the
engine does not expose draws greyed by L4.

| Enc | Panel | Name | Value | Bar | Source |
|---|---|---|---|---|---|
| 1 | L1 | `PRESET` | 4-char name | segmented | chain preset |
| 2 | L2 | `CUTOFF` | 0-127 | unipolar | engine zctrl (G2) |
| 3 | L3 | `RESO` | 0-127 | unipolar | engine zctrl (G2) |
| 4 | L4 | `ENV` | 0-127 | unipolar | filter envelope amount (G2) |
| 5 | R1 | `DECAY` | 0-127 | unipolar | amp decay — **`ATTACK` on PADS** (G2) |
| 6 | R2 | `LEVEL` | 0-100 | unipolar | `zynmixer.set_level` |
| 7 | R3 | `REVERB` | 0-100 | unipolar | insert reverb wet |
| 8 | R4 | `DELAY` | 0-100 | unipolar | insert delay wet |

### STEP page — how the selected channel generates notes

> **SWING is column 7 on both channel types.** Column 8 is the type's own extra.
> Within a page, a column never changes meaning.

**Drum channel — euclidean**

| Enc | Panel | Name | Value | Bar | Source |
|---|---|---|---|---|---|
| 1 | L1 | `HITS` | 0-*len* | unipolar | euclid onsets |
| 2 | L2 | `ROTATE` | 0-*len*−1 | segmented | euclid rotation |
| 3 | L3 | `DIVIDE` | `1/32 1/16 1/8 1/16T 1/8T` | segmented | `setStepsPerBeat` 8/4/2/6/3 — **lands on the bar** |
| 4 | L4 | `LENGTH` | steps | unipolar | `beats × steps_per_beat` — **lands on the bar** |
| 5 | R1 | `VELO` | 1-127 | unipolar | velocity of generated hits |
| 6 | R2 | `CHANCE` | 0-100 | unipolar | `setPlayChance` |
| 7 | R3 | `SWING` | 50-75 | unipolar | `setSwingAmount`, div fixed at 1/16 |
| 8 | R4 | `ratchet` | `----` | — | **greyed and inert in the prototype.** Reads exactly like the drum CONTROL page's dead columns — lower-case name, `----`, no bar, the encoder does nothing. Becomes `RATCHET` (`setStutterCount`) in pass two |

The RATCHET column is drawn now, greyed, rather than left blank, so the page's
shape does not move when pass two fills it. Under L4 the player is told the truth:
the knob is dead and looks dead.

**Voice channel — Turing machine**

| Enc | Panel | Name | Value | Bar | Source |
|---|---|---|---|---|---|
| 1 | L1 | `LENGTH` | 2-16 | unipolar | shift-register length — **lands on the bar** |
| 2 | L2 | `DIVIDE` | `1/32 1/16 1/8 1/4 1/16T 1/8T` | segmented | **lands on the bar** |
| 3 | L3 | `RANDOM` | 0-100 / `LOCK` | unipolar | per-step bit-flip probability applied **incrementally to the persistent register**. **0 = the next rewrite is skipped, so the line you are hearing is locked, bit-identical, forever.** Instant, continuous, no smoothing |
| 4 | L4 | `GATE` | 5-100 | unipolar | note length as % of a step — `addNote` duration |
| 5 | R1 | `OCTAVE` | −2…+2 | bipolar | transpose |
| 6 | R2 | `RANGE` | 1-4 | segmented | spread in octaves |
| 7 | R3 | `SWING` | 50-75 | unipolar | `setSwingAmount` |
| 8 | R4 | `VELO` | 1-127 | unipolar | velocity of generated notes — `addNote` velocity |

`CHANCE` on a voice is reached the same way as on a drum, and both are one
`setPlayChance` call — but note that on the voice page the owner's ratified layout
spends column 6 on `RANGE`, so **voice CHANCE is not on the surface in the
prototype**. It is set once in the prepared snapshot per voice and returns as a
surface control in pass two when RATCHET frees the drum page's column 8 and the
two types can be re-balanced. Rests on a voice are still available live, by pad
edit.

`ROOT` and `SCALE` are **not** here. They are global, on ALL. Three voices in
three keys is not a feature.

**Swing division is fixed at 1/16** — the only swing division anyone wants in
techno. `getSwingDiv` is per pattern, so the **prepared snapshot must set it
explicitly on every pattern** rather than trusting the default.

### ALL page — the machine's globals

| Enc | Panel | Name | Value | Bar | Notes |
|---|---|---|---|---|---|
| 1 | L1 | `ROOT` | `C` … `B` | segmented | quantises all three voices — **lands on the bar** |
| 2 | L2 | `SCALE` | `MIN MAJ DOR PHR HMIN PENT` | segmented | **lands on the bar** |
| 3 | L3 | `BPM` | 60-200 | unipolar | `libseq.setTempo` |
| 4 | L4 | `MASTER` | 0-100 | unipolar | main mixer strip level |
| 5 | R1 | `REVSIZE` | 0-100 | unipolar | **ganged — broadcast to all 8 reverbs** |
| 6 | R2 | `REVDAMP` | 0-100 | unipolar | ganged |
| 7 | R3 | `DLYTIME` | `1/16 1/8 3/16 1/4 3/8 1/2` | segmented | ganged; the driver computes the plugin value from `getTempo()`, recomputed on the 100 ms tick, **never per encoder event** |
| 8 | R4 | `DLYFBK` | 0-100 | unipolar | ganged |

**Left = time and key. Right = space.** That split is why the page needs no
header.

The four right-hand columns are named by **role**, and each addresses its
parameter through the per-channel FX handle, never a hard-coded plugin symbol.
Gate G3 fills in which symbol each role maps to on the plugin actually chosen.

**On MASTER:** the owner ruled that master volume lives on the touchscreen, in
the context of dropping the big encoder. The touchscreen master fader remains
authoritative and is the guaranteed path. `MASTER` sits on ALL encoder 4 as well
because global SWING vacated that column (swing is per channel now) and it costs
nothing — and it is the first column to give up if a global needs the slot.

### LED language

| Surface | State |
|---|---|
| **Group A-H** | hue = channel identity (fixed) · brightness = mixer level · **dark = not sounding**, whether muted directly or excluded by someone else's solo · full saturation = selected, others desaturated ~30% |
| **CONTROL / STEP / ALL** | exactly one lit, always. CONTROL is home |
| **F1-F8** | lit = muted (or soloed while SOLO mode is latched) |
| **SOLO** | lit = latched solo mode; the F row means solo |
| **Play** | lit while transport runs |
| **Pads** | dim = empty · bright, scaled by velocity = active · **white = playhead** · dark = beyond LENGTH |
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
It is not in git on the Pi — re-set it after any deploy that touches the daemon.

### Screens

**The display geometry is solved and hardware-verified. No work is scheduled to
re-verify it.** Two panels, **255x64**, four 64 px columns each. Tab row 0-12
(8 characters), dotted rule at 15, parameter name at 19 (5x8), value at 30
(**double height, 4 characters**), indicator bar 52-62. Each screen is 1bpp
row-major, MSB leftmost, 32 bytes per row, sent as 8 reports of a full-width
8-row band. Source of truth: `MD/display-investigation.md`, first section.

The tab row is on every page, always. Selected tab inverted; muted tab dashed.
Bars: `[==== ]` unipolar · `[--|--]` bipolar from centre · `[# # . ]` segmented.

The renderer takes a **page dimension from day one**, even with three pages.

#### CONTROL — drum channel A selected, D muted

```
LEFT SCREEN  (255x64)                      RIGHT SCREEN  (255x64)
+--------+--------+--------+--------+      +--------+--------+--------+--------+
|#A KICK#| B SNAR | C CLAP |:D CHAT:|      | E OHAT | F BASS | G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 KIT      SAMPLE   tune     decay           filtr    LEVEL    REVERB   DELAY
 T808     KICK     ----     ----            ----     0082     0024     0036
 [# . . ] [# . . ]                                   [===== ] [==    ] [===   ]

 #..#  selected     :..:  muted (dashed)     lower case + ---- + no bar = inert
```

#### CONTROL — voice channel F selected

```
+--------+--------+--------+--------+      +--------+--------+--------+--------+
| A KICK | B SNAR | C CLAP | D CHAT |      | E OHAT |#F BASS#| G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 PRESET   CUTOFF   RESO     ENV             DECAY    LEVEL    REVERB   DELAY
 SUBB     0044     0071     0096            0030     0090     0012     0064
 [# . . ] [==    ] [===== ] [======]       [==    ] [======] [=     ] [===== ]

 Columns 2-5 are provisional until gate G2 names the engine's symbols.
```

#### STEP — drum channel A selected

```
+--------+--------+--------+--------+      +--------+--------+--------+--------+
|#A KICK#| B SNAR | C CLAP | D CHAT |      | E OHAT | F BASS | G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 HITS     ROTATE   DIVIDE   LENGTH          VELO     CHANCE   SWING    ratchet
 0004     0000     1/16     0016            0110     0100     0050     ----
 [=     ] [# . . ] [ . # . ] [======]      [======] [======] [      ]

 Seven live columns.  The eighth is drawn, greyed and honest until pass two.
```

#### STEP — voice channel F selected, mid-fish

```
+--------+--------+--------+--------+      +--------+--------+--------+--------+
| A KICK | B SNAR | C CLAP | D CHAT |      | E OHAT |#F BASS#| G LEAD | H PADS |
+--------+--------+--------+--------+      +--------+--------+--------+--------+
 · · · · · · · · · · · · · · · · · ·        · · · · · · · · · · · · · · · · · ·
 LENGTH   DIVIDE   RANDOM   GATE            OCTAVE   RANGE    SWING    VELO
 0008     1/16     0035     0040            -001     2        0058     0100
 [===   ] [ . # . ] [==    ] [===   ]      [--|   ] [# # . ] [==    ] [===== ]

 RANDOM 0035 = the register drifts a little each cycle.
 Snap it to 0000 and the line you are hearing is kept, bit-identical, forever.
```

#### STEP — voice, locked

```
 LENGTH   DIVIDE   RANDOM   GATE            OCTAVE   RANGE    SWING    VELO
 0008     1/16     LOCK     0040            -001     2        0058     0100
 [===   ] [ . # . ] [      ] [===   ]      [--|   ] [# # . ] [==    ] [===== ]

 The value cell reads LOCK, not 0000, so "locked" is a word and not a number
 that could be a coincidence.  4 characters exactly.
```

#### ALL

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

#### A structure change pending on the bar (L2)

```
 HITS     ROTATE   DIVIDE   LENGTH          VELO     CHANCE   SWING    ratchet
 0004     0000    >1/8<     0016            0110     0100     0050     ----
 [=     ] [# . . ] [ . . # ] [======]      [======] [======] [      ]

 Angle brackets around the value = set, waiting for the bar line.
 They clear the instant it lands, so the player knows it took.
```

### State model — one dict, one apply path

Non-negotiable, and the reason Lock snapshots could be ruled out of the prototype
without fear.

Every mutable parameter lives in a single `state[channel][param]` structure, and
**every** write — encoder, snapshot restore, Duplicate, and later Lock recall and
morph — goes through one `apply(channel, param, value)` that also updates the
screen model and the LED cache. Lock is then a copy of that dict and a morph is a
lerp over it. If encoders write zynseq and zctrls directly, pass two's first item
becomes a rewrite of the driver rather than a feature.

Within the dict, **generator parameters are separable from mix parameters** — two
named groups, even though nothing in the prototype uses the distinction.

| Data | Owner | Survives snapshot reload |
|---|---|---|
| Steps, division, length per channel | zynseq pattern | yes |
| Chance, swing per channel | zynseq pattern (`get/setPlayChance`, `get/setSwingAmount`) | yes |
| Mixer level, mute, solo | zynmixer strip | yes |
| Insert wet, ganged FX parameters | plugin zctrls | yes |
| Kit / sample / preset per channel | chain preset | yes |
| ROOT, SCALE, BPM | driver state + `setTempo` | via driver `get_state` |
| **Turing register per voice, and the 4-deep ring** | **driver state** | **via `zynthian_ctrldev_base.get_state` / `set_state` — from day one** |
| Rotation, selected channel, current page | driver RAM | selected channel and page default to A / CONTROL |

**Persist driver state from day one.** Adding it later means every existing
snapshot is missing it.

**Build the per-channel pattern-writer token now**, while the Turing mutation is
the only writer, so a morph can take it later. Two writers to one pattern is the
SIGSEGV by a different door.

---

## Testing

**Pure functions, unit tested with pytest on WSL, no Pi and no hardware.** This
is how `euclid()`, the screen layout and the SFZ kit parsing are already tested,
and the new code is the same shape:

- the shift register — length, clocking, incremental mutation at a given RANDOM,
  and the invariant that RANDOM = 0 produces a byte-identical register forever
- the register ring — 4 deep, correct pop order, correct behaviour when fewer
  than four entries exist
- register → pitch: range scaling, ROOT/SCALE quantisation, OCTAVE transpose
- the screen model for all three pages on both channel types, including greyed
  columns and the pending-value brackets

**Hardware verification on the Pi, one part per sitting.** Every part starts with
the copy step — the driver lives in `~/zynth/zynthian-ui/zyngine/ctrldev/` and
must be copied to the Pi's `/zynthian/zynthian-ui/` each cycle.

| Part | Adds | Verify |
|---|---|---|
| **G1/G2/G3** | the three gates | Complete and written up **before any driver code**. G1's precondition — jackd on `hw:S2` — first of all |
| 1 | Prepared snapshot, 8 chains, 8 sequences, 16 inserts, driver loads | All eight channels sound; the touchscreen mixer shows eight strips plus main; the pattern editor shows the same steps you tapped |
| 2 | Page buttons, group select, screens on all three pages | Exactly one page LED lit; the tab row follows selection; three pages render on both panels |
| 3 | Drum STEP page, all seven live columns | Density, rotation, division, length audible; CHANCE opens holes; SWING shuffles against a straight kick; the `ratchet` column is visibly inert |
| 4 | Voice STEP page and the Turing machine | RANDOM up drifts one note per bar, not a new line per bar. **Snap RANDOM to 0 and the line repeats bit-identically for five minutes.** Duplicate walks back four registers |
| 5 | CONTROL pages, both types, plus encoders 7/8 | Wet knobs live on all eight channels of both types; the dry signal survives a full sweep (G3's finding, on hardware) |
| 6 | ALL page, ganged FX, ROOT/SCALE/BPM | All three voices follow the root; DLYTIME tracks a BPM change; one knob moves eight instances |
| 7 | F1-F8 mute, SOLO, transport, ERASE | Tap latches, hold is momentary, on both. Hold SOLO + F1 = kick alone, release = everything back. A bare ERASE press does nothing |
| 8 | Snapshot save and reload | Patterns, divisions, chance, swing, mutes, presets, insert wets **and the Turing registers plus the ring** all return. LOOP play mode re-forced; every LED repaints |
| 9 | **The twenty-minute jam** | All three voices at RANDOM > 0, all eight channels playing, pages and channels switched throughout. Zero SIGSEGV, zero UI stall, and `watchdog: input stalled, reopened` no more often than the healthy ~8 s baseline |

Part 9 is not optional and it is not a two-minute demo. **The last bug of this
shape took 95 seconds to appear.**

---

## Risks and open questions

| # | Risk | Retire it by |
|---|---|---|
| **R1** | **The lock, and the write burst.** `libzynseq` is not thread-safe and the driver reaches it from three threads; this has already killed the whole Zynthian UI with SIGSEGV, exit 139, ~95 s into a jam. The Turing machine adds a fourth access pattern — a `clear` plus 8-16 `addNote` burst per cycle boundary, three voices over, roughly every 0.6 s at 132 BPM | Test part 9. Design rules, not later fixes: one lock acquisition per burst; `selectPattern()` once per burst and never in the poll hot path; clocks-per-step cached; the lock never held across a preset load |
| **R2** | **Sixteen new plugin processes.** RSS, JACK graph nodes and a snapshot load time nobody has measured. The DSP is affordable at 512 × 3; the process count and the load time are what will hurt | Gate G1. Degrade to cheaper plugins, then 8 channels to 6. **Never to a shared bus** |
| **R3** | **The voice engines' controller lists are unknown.** LinuxSampler is the standing proof that "enabled" says nothing about what a chain exposes | Gate G2, before the voice CONTROL page is designed |
| **R4** | **A wet control that is really a crossfade.** PlateX2's `blend` turns the dry down as it turns the wet up, which fails the contract that encoders 7 and 8 are sends | Gate G3. Prefer a plugin with a separate wet level; cap at ~0.45 of range only as a last resort |
| **R5** | **jackd is on the wrong device.** `-d hw:Headphones -r 48000`. Every number taken to date, including the ~6% for the shipped rig, is on the Pi's headphone jack, not the Sound Blaster (`hw:S2`, 44.1 kHz) | Move it **before G1**. Any measurement taken before the move is worthless |
| **R6** | **Screen repaints starving the input reader.** Redrawing per input report has already tripped the hidraw watchdog once | Three pages and two panels must remain **one diffed repaint per 100 ms tick**. Watch the `watchdog: input stalled, reopened` frequency; ~8 s is healthy, more is a regression |
| **R7** | **Snapshot restore rewrites more than expected.** Restoring rewrites every sequence's play mode from the `.zss`, and a LOOPALL sequence shorter than the bar goes RESTARTING then STARTING and falls silent until the next bar sync | **Re-force LOOP after every restore**, not once. **Clear the LED cache on `SS_LOAD_SNAPSHOT`**. Test part 8, mid-transport |
| **R8** | **The Pi's Zynthian is older than the local checkout.** This has broken three times — call arity, `clearPattern`, `getNoteAtIndex` | Audit every new `libseq.*` and zynmixer call against the installed `.so` with `nm -D --defined-only` before writing it. Ten seconds each |
| **R9** | **The kit change may not survive being a live control** if a reload costs audible silence | Measured at G1. Above ~200 ms of silence, freeze kits per snapshot and move KIT off the CONTROL page |
| **R10** | **The 4-character value cell.** `T808` reads; `1200` and `1201` for the two SP-1200 banks do not distinguish at a glance | Photograph the CONTROL page with the worst kit names during the first driver deploy. The fix is a wider column at a neighbour's expense, **never** a smaller font |
| **R11** | **`patch-autoconnect-maschine.py` must be re-run after any Zynthian update**, or the daemon's virtual port never gets a zmip slot and the driver is "Found" but never "Loaded" — the rig does nothing at all, with no error | Check for the zmip slot after every system update, before blaming the driver |
| **Open** | **Voice CHANCE is off the surface** in the ratified column layout (column 6 is RANGE). Set per voice in the prepared snapshot; live rests come from pad edits | Revisit in pass two, when RATCHET lands and the two channel types' column 6-8 can be re-balanced |
| **Open** | **`setSwingDiv` is per pattern**, so the prepared snapshot must set 1/16 explicitly on all eight patterns rather than trusting a default | Assert it in the snapshot build, and read it back in test part 1 |

---

## What the prototype must NOT foreclose

The price of "prototype first". Every item is cheap now and expensive later.

1. **One state dict, one apply path** — above. Lock snapshots (pass two, item
   one) are a copy of that dict; a morph is a lerp over it.
2. **Generator parameters separable from mix parameters** inside that dict. Scoped
   Lock layers (pass three) are otherwise impossible without re-tagging every
   field.
3. **A per-channel pattern-writer token**, built now while there is only one
   writer, so the morph can take it later.
4. **Encoders 7 and 8 address "the channel's reverb wet" through a per-channel FX
   handle**, never a hard-coded plugin symbol. Swapping MDA Ambience for something
   better under G1's headroom, or insert for bus in pass three, must then change
   one function.
5. **The encoder dispatcher takes `(verb, channel, value)` internally** from day
   one, even though the prototype only ever passes the current page's column. The
   pass-two verb layer — VOLUME held = eight faders, SWING held = eight swings — is
   then a dispatch change, not a rewrite. Leave room for the verb's object to be a
   **step** rather than a channel: once per-step chance and ratchets exist, the
   instinct will be "hold a pad and turn a knob".
6. **Channel roles stay a table** (`CHANNELS = [...]`). 5+3, 4+3+spare and 4+4 are
   config lines, and G1's degrade to six channels depends on it.
7. **Do not consume CC 49, 50 or 51.** Reserved for SHIFT, SWING and VOLUME in
   pass two's single ~10-line daemon patch.
8. **Persist driver state from day one**, including the Turing registers *and* the
   4-deep ring.
9. **The screen renderer takes a page dimension from day one**, even with three
   pages. Adding a page must be a dict entry.
10. **The greyed-column convention is load-bearing**, not decoration. Pass two
    fills `ratchet`, and pass three may fill the drum `tune`/`decay`/`filtr`
    columns from LV2s. The page shape must not move when they light up.

### Deferred, and where

**Pass two, in order:** Lock snapshots on SCENE (8 slots, pads 1-8, hold to store,
tap to recall on the bar, encoder 1 = morph time in bars) · the verb layer (one
daemon patch emitting SHIFT 49, SWING 50, VOLUME 51) · RATCHET via
`setStutterCount` · Note Repeat and choke groups · big-encoder triage · PAD MODE
play layer · a second Turing layer generating velocity.

**Pass three:** a PERFORM page of eight freely assigned macros · a continuous
morph-toward-a-slot knob · scoped Lock layers · sidechain ducking from channel A ·
per-drum tone controls as LV2s · a true shared reverb and delay bus ·
`setNotePlayChance` and per-step `addControl` automation.

---

## Rejected alternatives

- **True FX sends.** 26 mixer strips needed against a hard 16. Raising
  `MAX_CHANNELS` is realtime C in Zynthian's routing core, +64 JACK ports, and
  both the snapshot format and the touchscreen mixer assume 16. Permanent
  upstream divergence for a gain that is inaudible once inserts exist.
- **A shared FX bus as the degrade path.** It was the developer's own proposal and
  he withdrew it on cross-examination: a shared bus fed by per-channel routing
  on/off turns knob 7 into a toggle wearing a knob's clothes, which breaks the one
  absolute muscle memory in the machine.
- **Starting with PlateX2 and `Gxdigital_delay_st`.** Better-sounding, but PlateX2
  is not enabled in webconf, its `blend` is a crossfade, and starting at the
  expensive end makes G1 a critical-path gate instead of a cheap one. Start cheap,
  measure, upgrade into proven headroom.
- **Dragonfly Plate Reverb.** freeverb3 with oversampling — several percent of a
  core per instance, so eight is 16-32% of a core. Off the table for an
  eight-instance insert.
- **The big encoder as a dependency.** Not decoded at all: `MaschineButton::Encoder`
  is never produced from HID and `roller_state[8]` is never written. Triage is
  cheap (~30 min) and is pass two, but nothing musical may rest on it until it
  emits. The grammar the owner wanted is delivered better without it — verb button
  + the eight small encoders applies a verb across eight channels at once, instead
  of one channel at a time.
- **SHIFT as the mixer layer.** VOLUME held is the mixer: the legend is printed on
  the button, it is the verb the grammar names, and it leaves SHIFT a clean
  general modifier (SHIFT+ERASE = clear all, SHIFT+Fn = exclusive solo).
- **F1-F8 as solo.** The prior art's choice. Mute is used perhaps sixty times a
  set and solo perhaps four; the most-used gesture gets the eight easiest buttons.
  It is also what the shipped rig already does, so it is zero work — and it is what
  removed SHIFT, and therefore all daemon work, from the prototype.
- **A bare ERASE press clearing the selected channel** (the shipped rig's
  behaviour). In front of people that is a landmine. Accepted regression.
- **Regenerating the Turing line each wrap.** That is a random-line generator, not
  a Turing machine. Mutation must be incremental on a persistent register or the
  slow drift — the entire musical value — does not exist.
- **zynseq's native `undoPattern` / `savePatternSnapshot` / `restoreSnapshot`
  stack** for the "give it back" button. It operates on the note list, not the
  register, and it would fight the touchscreen editor's own undo. The driver's own
  4-deep register ring is the right owner.
- **Implementing rests or density by rewriting the pattern.** `setPlayChance` is
  native, per pattern, persisted in the `.zss` and costs zero pattern writes —
  which directly cuts R1, the largest risk in the design.
- **`setNotePlayChance` and per-step `addControl` in the prototype.** The first
  overlaps almost entirely with pattern-level `setPlayChance`, is not declared in
  the Python wrapper, and inherits a per-step UI problem for near-zero marginal
  gain. The second has the highest ceiling and the worst value per hour here: it
  needs an automation-lane UI, a CC-target map per channel, and there is neither
  screen room nor an LED language for it.
- **Lock snapshots in the prototype.** Costed at roughly two days for eight slots
  with a bar-synced morph — real, but it is a feature on top of a machine that
  must first play. Ruled out without fear only because of the one-state-dict
  constraint above.
- **Drum `TUNE` / `DECAY` / `FILTER` / `DRIVE`.** No source: LinuxSampler inherits
  `_ctrls = []`, FluidSynth's CC 74/71 is a proven dead end, and an LV2 per drum
  chain means up to 32 more processes. KIT and SAMPLE already deliver more
  character than a filter would. Greyed and honest.
- **Pan on the surface.** Set once, never touched in techno. One tap away on the
  touchscreen mixer, where it is also visible.
- **Runtime processor add/remove from the driver.** Everything is a prepared
  snapshot. `fader_pos` bookkeeping is fiddly enough that the driver must never
  touch it.
- **Generating notes outside zynseq.** Would lose persistence, the touchscreen
  editor and pad editing, and would put note timing on a Python thread with no
  JACK clock.
- **Pattern chaining, song mode, scenes, the arranger.** Replaced wholesale by
  Lock snapshots in pass two, which do the same job with one mechanism on a
  machine whose patterns are parameters.
- **Chord and arp engines.** The Turing machine is the note generator; an
  arpeggiator on top is two generators fighting. ROOT + SCALE quantising
  everything is all the harmony logic needed.
- **Pad pages, fixed-velocity pad mode, and a `GHOST` second euclidean layer.**
  8 groups × 16 pads is enough and no LED can show which pad page you are on; the
  generator sets velocity and pads accent it; and the columns GHOST would have
  filled are now live.

---

## Summary card

```
GROUP A-H     select channel            F1-F8     MUTE  (tap=latch, hold=momentary)
SOLO + Fn     momentary solo            SOLO tap  latched solo mode
CONTROL       what it sounds like       enc 6/7/8 always LEVEL, REVERB, DELAY
STEP          what it plays             enc 7     always SWING, both channel types
ALL           key, tempo, master, space left = time+key, right = ganged space
PADS          the 16 steps              velocity on the tap = step accent
PLAY all on/off   RESTART all to step 0   ERASE hold + pad/group only
DUPLICATE     give the last line back   <  >  previous / next sound

LAW  timbre lands instantly · structure lands on the bar
LAW  tap = latch · hold = momentary · 250 ms, everywhere
LAW  one channel, one cursor · the inverted tab is the truth
LAW  a knob with no source is greyed, shows ---- and does nothing
LAW  RANDOM -> 0 keeps the loop you are hearing, bit-identical, forever

GATES  G1 FX cost (jackd on hw:S2 first) · G2 engines · G3 wet parameter
       All three complete before a line of driver code.

NO DAEMON WORK IN THE PROTOTYPE.
```
