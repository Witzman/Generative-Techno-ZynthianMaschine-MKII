# Snapshots

Three things live here: the **factory snapshot** — `018`, the instrument's own
configuration with a master filter on the Main chain, with `017` beside it as
the same instrument without one; the **genre pack**, fifty-one fixed
arrangements built from it; and
the **drone and ambient pack**, twenty slow pieces that are the opposite
instrument — almost no pattern, and everything moving.

---

## Every snapshot names itself — check it after any build

`last_snapshot_fpath` inside a `.zss` is what Zynthian shows and what it stamps
into audio-capture filenames **when the snapshot is restored as
`last_state.zss`** — the boot path. Loading from the touchscreen uses the real
path instead, which is why a wrong value here hides for months.

Every snapshot built from another one inherits it. On 2026-08-22 that meant
**72 of the 73 files here claimed to be `017-generative-techno`**, including the
factory snapshot `018` and all of `101`, the genre pack and the drone pack. The
rig booted playing one snapshot and naming another, and captures were filed
under the wrong name.

```bash
tools/fix-snapshot-identity.py --check snapshot/*.zss snapshot/*/*.zss
```

**Must print `73 of 73 name themselves`.** Both generators stamp it now
(`build-genre-snapshots.py`, `add-main-insert.py`), so this is a guard against
the next path that copies a snapshot, not a chore.
`notes/findings/2026-08-22-every-snapshot-claimed-to-be-017.md`

---

# The factory snapshot

**File:** [`017-generative-techno.zss`](017-generative-techno.zss) · 27,015 bytes ·
md5 `d10545344a988b8e9b0700ce4dc7f5be` (measured 2026-08-22; the byte count did
not change when the tempo moved to 125, so the old md5 `0becfb52…` looked
plausible beside it for a day)

This one file *is* the instrument's configuration: eight chains on MIDI channels
1-8, sixteen post-fader insert plugins with their dry and wet levels, the
patterns, the mixer levels, and the driver's own state — including every voice's
Turing register, which is why a frozen line comes back frozen and playing the
same notes.

Install it with [section 4](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/04-manual-installation.html):

```bash
scp snapshot/017-generative-techno.zss \
    root@<your-pi>:/zynthian/zynthian-my-data/snapshots/000/
```

Then load it from the **touchscreen**, inside bank `000`. A snapshot at the
snapshots root rather than inside a bank is invisible in the UI, and webconf's
Snapshots **Name:** field renames the selected *bank* instead of saving.

---

## What it contains

**125 BPM is a deliberate choice, not a round number.** zynseq truncates the
length of one sequencer clock to a whole audio frame with no accumulator, so at
48 kHz the tempo error is the fractional part of `30000 / tempo` — **zero only
when the tempo divides 30000.** The factory snapshot shipped at 124 until
2026-08-21, which is 3,882 ppm fast: a bar clear of nominal every 8.3 minutes,
and a MIDI clock out to match. 125 is one BPM away and exact. Changed with
`tools/set-snapshot-tempo.py`, which writes **both** places a `.zss` holds the
tempo — the riff's `vers` block and the driver's own `ctrldev_state/globals/bpm`
— and refuses if a round trip does not reproduce the original byte for byte.
**The pack took the middle path on 2026-08-22.** Fifteen snapshots whose
nearest exact tempo was within **one BPM** were moved there — four 124s and
three 126s to 125, four 121s and two 119s to 120, and two 76s to 75. One BPM
does not change what any of them is: a 124 house track and a 125 house track are
the same track. Everything further away was left alone on purpose, because at
that distance the tempo IS the identity — `057-trance-acid` stays at 137 and
4,487 ppm, the worst in the pack, since its exact neighbours are 125 and 150 and
neither is acid trance. Exact snapshots went from 13 to 28 of 73; the remaining
45 are inexact by design and the reason is written here rather than rediscovered.

Read directly out of the file, not from intent. 125 BPM, sixteen steps at `1/16`
unless stated.

| Ch | Name | Engine | Generator state |
|---|---|---|---|
| A | KICK | LinuxSampler | euclidean, four-on-the-floor |
| B | SNAR | LinuxSampler | euclidean, backbeat |
| C | CLAP | LinuxSampler | euclidean, syncopated |
| D | CHAT | LinuxSampler | euclidean, offbeat sixteenths |
| E | OHAT | LinuxSampler | **`kinds: {"4": "voice"}`** — a drum kit driven by a Turing register: random 25, density 40, register 179 |
| F | BASS | JC303 | random **0** (`LOCK`), gate 40, octave −1, 16-bit register 61260 |
| G | LEAD | Obxd | random **100**, gate 40, range 2, register 179 |
| H | PADS | padthv1 | random **0** (`LOCK`), gate **800** (8 steps), density **12** (one step sounds), 8-bit register 179 |

Globals: BPM 125, scale index 0 (natural minor), root index 7, master 80,
revsize 25, revtype 3, dlytime index 1 (`1/8`), dlyfbk 35.

Ownership: all eight channels are `gen` — the generator owns every pattern, so
nothing is player-owned and no take can be lost by turning a knob.

Mixer: channel strips `chan_00` … `chan_07` all at **0.19**, and the main strip
`chan_16` at **0.774**. That staging is measured, not cautious: one sampler channel
peaks at 1.24 before the mixer, and eight of them summed to 2.92 on the main bus —
nearly three times full scale. The attenuation lives on the strips, and main just
under 0.80 leaves the MASTER knob travel in both directions.

---

## How this was verified

Two independent passes, because neither alone is sufficient.

**The driver state was read back out of the file** — the table above is what the
`.zss` actually contains, not what was intended: the `kinds` override on channel
E, all eight channels `gen`-owned, the four voice states, the mixer levels.

**The patterns were confirmed by ear at the panel**, against
[section 4's verification](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/04-manual-installation.html). This pass is not optional and
cannot be automated for THIS file: patterns, tempo, swing and play chance live
inside `zynseq_riff_b64`, a 2,544-byte base64 RIFF blob. `tools/build-genre-snapshots.py`
now decodes and writes that blob — it is how the genre pack below is built — but
decoding proves the notes are where the file says, not that the file says the
right thing. A snapshot that loads without error is not a snapshot that plays the
right notes — the previous snapshot in this project shipped with two channels at
play chance 0 for its entire existence, reading as perfectly healthy on the
surface.

---

## Rebuilding it

[section 5](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/05-internals.html) documents how the snapshot was
made: the chain table, the insert order as measured on the wire, the dry/wet
values, the gain staging, and `tools/build-techno-snapshot.py`, which clones one
channel's insert pair onto the other seven so sixteen instances are not placed by
hand.



## `018-generative-techno-main-insert` — THE FACTORY SNAPSHOT since 2026-08-22

**File:** [`018-generative-techno-main-insert.zss`](018-generative-techno-main-insert.zss)
· 55,121 bytes · md5 `89020924f3700bdae09ba47e308e9bd0` (measured 2026-08-22,
after the identity fix; the file grew twelve bytes when it stopped claiming to
be `017`, so the pre-fix `df1c6ebb…` is stale rather than wrong about a
different file)

`017` with one thing added: **`JV/MDA RezFilter` in slot 1 of the Main chain**.
Nothing else differs — the two files' only unequal top-level keys are `chains`
and `zs3`, and both differences are that plugin and its saved controls.

**Owner decision, 2026-08-22: this became the factory snapshot.** `bootstrap.sh`
now places `018` as the bank-`000` entry **and** as `default.zss`, so a fresh Pi
boots into the instrument with its MAIN page already there.

**The argument that had kept it out for two days is still true, and is answered
rather than dismissed.** The insert sits between the mixer and the card, so it
hears all eight channels at once and can silence the whole instrument from one
knob. It loads wide open here because the snapshot writes every one of its
controls explicitly; at the plugin's own defaults the cutoff sits below the
point where it passes audio at all. The risk of shipping it was that one bad
control write leaves a dead rig with a healthy-looking surface.

**What makes it acceptable is the way back.** `bootstrap.sh` also places `017`
in bank `000` — never as `default.zss` — so the insert-free instrument is one
snapshot load away rather than a rebuild. Both halves are asserted in
`system/tests/test-dry-run.sh`: `018` in the bank and over `default.zss`, `017`
in the bank and never over it, and no genre snapshot as the default. The
assertions were proved able to fail by pointing the installer back at `017`.

**Loading `017` builds no MAIN page at all** — `ALL`'s ring is one page shorter
rather than showing dead columns — which is what the guide's mixing page says.

---

# The genre pack

**Fifty-one snapshots**, `031`–`080` and `101`, in [`genre-pack/`](genre-pack/), built from the
factory snapshot by `tools/build-genre-snapshots.py` out of
[`genre-pack-manifest.json`](genre-pack-manifest.json). Regenerating them is one
command, so the manifest — not the `.zss` files — is the thing to edit:

```bash
python3 tools/build-genre-snapshots.py \
    --manifest snapshot/genre-pack-manifest.json \
    --out snapshot/genre-pack
```

## What they are

**REBUILT 2026-09-04, and the reason is worth stating: the first version of
this pack was fifty-one files holding about thirty-one arrangements, on a flat
mixing board, and twenty of them could not reach a reverb or a delay at all.**
The scan that found it is `notes/findings/2026-09-04-the-preset-packs-are-one-preset.md`
and the plan is beside it. What changed:

| Was | Is |
|---|---|
| every fader at **0.19** on all eight channels | a staged mix per family — drums forward, voices 8-10 dB down, the way `019` does it |
| every channel a **one-bar loop at 1/16** | the pad runs at 1/8, so it is a two-bar layer over a one-bar groove |
| `chord` **0** everywhere — no preset made a chord | chords on the mid and pad channels: sevenths in house, ninths in deep, a real triad in dub |
| drum grooves as **literal step lists**, with no `drums` block — so HITS and ROT on the panel were whatever it last held, and the first encoder turn wiped the groove | grooves written as **euclid + rotation + mask**, with the `drums` block saved, so the panel and the pattern agree |
| **nineteen** presets had a bass playing the flat seventh or the fifth on **every** step and never the root | 2-4 bass onsets a bar, and the first note of the bar is the root |
| swing and humanisation **zero** everywhere | per-channel swing (house 0.16, deep 0.20, dub 0.08) and humanised clap, snare and hats |
| `061`–`080` were **twenty different effect pairs over eleven duplicated arrangements** | the **SPACE series**: twenty rooms, each with its own key and its own chord register |

| Files | What varies | Effects |
|---|---|---|
| `031`–`060` | thirty arrangements across five genres | TAP Stereo Echo + TAP Reverberator |
| `061`–`080` | **twenty rooms** — plate, chamber, hall, cathedral, tile, cavern, spring, gated, ambience, slapback, canyon, studio, basement, stairwell, glass, tunnel, chapel, hangar, closet, observatory | the same pair, driven to twenty different `revtype`/`revsize`/`dlytime`/`dlyfbk` settings |
| `101` | an eleventh dub, every voice a Mutated Instrument | the same pair |

Six each of **house**, **deep house**, **minimal**, **dub** and **trance** at
120-140 BPM, twenty **space** presets at 120, plus `101`.

**Why one effect pair on all fifty-one now.** Not a narrowing — the opposite.
`revtype` alone is **43 distinct rooms**, and until 2026-09-04 not one of them
was reachable on the twenty-one presets that carried a different pair, because
the driver resolved REVERB and DELAY by plugin NAME. The knobs, both modulator
kinds and all four space globals were dead on those files, in silence. The
driver resolves by ROLE now, so the whole palette works — and the pack takes
the one pair that supplies both roles on every chain, because that is what
makes `revtype`, `revsize`, `dlytime` and `dlyfbk` live on every preset.
See `notes/specs/2026-09-04-role-based-fx-resolution.md`.

**These are still fixed arrangements, not generative patches** — `random` and
`rhythm` are 0 on every genre voice, so the melody and the rhythm are locked.
The drone pack is the opposite instrument; see below.

**The five drum channels keep their roles.** A is always the kick, E always the
open hat; what changes is the kit — TR909 for house, TR808 and CR78 for dub,
TR606 for minimal, SP-1200 and SP 12 for lo-fi. Kits are mixed across channels
where that is normal practice, such as a 909 kick under an 808 clap.

## The drum note map, and why it is generated

The kits **do not share a note map, and none of them is General MIDI.** Roland
TR909 is kick 36 / snare 40 / clap 50 / closed hat 42 / open hat 46. Yamaha RX11
puts its clap at 64. Korg DDD1 calls its kick `bass1`; Alesis HR16 calls it
`kik`; TR808 and Tyson name their open hat `hat_long`.

So the notes are not written by hand. `tools/scan-drum-kits.py` runs on the Pi,
parses all 41 `.sfz` files and writes `tools/drum-kit-notes.json`, which the
builder reads. A wrong note is a **silent channel**, and a silent channel with
the surface reporting it healthy is the one failure this instrument must not
produce.

**Three kits are excluded** because they cannot cover the five roles, and faking
it would have been worse than leaving them out: `DYNOSAUR-808` (every sample is
a bass drum — no snare, no hats), `E Ave` (four samples, no hats) and
`Roland TR727` (Latin percussion only — no kick, snare or hat). Ten of the 38
usable kits borrow one role from a neighbour, most often a clap from the snare or
an open hat from the closed hat; that is a musical substitution and is recorded
in `drum-kit-notes.json` under `borrowed`.

## Installing them

`bootstrap.sh` places the whole pack in bank `000` beside the factory snapshot.
`install.sh` places **no snapshots at all** — it installs the driver, the daemon
and the system files and nothing else. By hand:

```bash
scp snapshot/genre-pack/*.zss \
    root@<your-pi>:/zynthian/zynthian-my-data/snapshots/000/
```

## How the pack was verified

**Every one of the fifty-one now crosses `tools/validate-manifest.py`**, which
is a check on the MUSIC rather than the structure: it renders every channel's
notes and refuses two sustained notes closer than the critical band at their
register, a unison between channels, more channels attacking one instant than
the family's budget, a bass whose first note of the bar is not the root, a flat
mixing board, a kit note two channels share, and a `level` modulator whose base
disagrees with its fader. All 71 entries of both packs pass; all 71 of the
version before the rebuild fail.

**Every one of the fifty-one was checked structurally** — the RIFF re-parses with no
trailing bytes, all eight patterns present, every drum step list matching the
manifest, every drum note matching that kit's scanned map, every voice's steps
matching its `rhythm_reg`, evolution off, `mods` and `stash` empty, the engines
and the effect pair actually applied to all eight chains.

**Three were loaded on the rig** on 2026-08-22, through the real boot path,
and the engines that came up were confirmed as JACK clients — one from each
transform the builder performs. **Two of those three files no longer exist**:
`061-fx-tape-chorus` and `080-fx-chorus-plate` were part of the fx-* series the
2026-09-04 rebuild replaced, and the record is kept because what it proved —
that the builder's engine and effect swaps reach the rig — is still true of the
tool. Zero driver errors on all three, one `LinuxSampler` serving the five drum
chains in each.

**THE REBUILT PACK HAS NOT BEEN LOADED ON THE RIG.** Every entry passes
`tools/validate-manifest.py`, which renders the notes and refuses a collision,
a rootless bass, a flat board or a drone that cannot sustain — but that is a
floor, not a verdict.

**Staging a snapshot to test it must stop the UI first.** Zynthian rewrites
`last_state.zss` on a clean shutdown, so copying a snapshot over it while the UI
is running gets the copy overwritten by the outgoing state — the rig then comes
back on the OLD state and every check passes against the wrong file. Two of
these three initially "passed" that way and proved nothing.

**What that does not prove:** that all fifty-one sound good. Structure is verified,
taste is not. The same caveat as the factory snapshot applies, for the same
reason — loading without error is not playing the right notes.


## `101-dub-mutated` — added 2026-08-21

The one preset in the pack whose three voices are **all the same engine**:
`JV/Mutated Instruments` on chains 6, 7 and 8. Everything else in the pack
mixes three different synths; this one leans on one engine's own character and
separates the voices by register, octave and gate instead.

| | |
|---|---|
| Tempo | **120 BPM — chosen because it is EXACT** (see the tempo note in the factory snapshot section above) |
| Key | root 10, scale 5 — B♭ pentatonic |
| Drums | TR909 across all five, and dub-sparse: kick four-on-floor, one rimshot on the four, a closed hat on 2 and 10, no clap and no open hat |
| Voices | bass on the one and the offbeat (`rhythm_reg` 65) doubled at the octave, the triad stab strictly offbeat, a fifth held above it |
| Effects | TAP Stereo Echo → TAP Reverberator, with `dlytime` 1/2 and `dlyfbk` 35 |

**Its effect pair changed in the 2026-09-04 rebuild, and not for taste.** It
used to carry `JV/Tal-Dub-3` → `JV/Tal-Reverb-III`, which reads like the right
choice for a dub preset and was in fact a preset with **no reachable delay and
no reachable reverb**: the driver resolved both verbs by plugin name, so the
knobs, the modulators and all four space globals were dead. The driver resolves
by role now and Tal-Dub-3 works — but the dub character comes from `dlytime`,
`dlyfbk` and `revtype`, which are live on every preset only when the pair
supplies both roles. See the note in the genre-pack section above.

**Measured on the rig, 2026-08-21, on the version that carried Tal-Dub-3 and
Tal-Reverb-III**: 8 × each instantiated, **JACK DSP mean 23.9%, p95 24.1%,
zero xruns** over 60 s with the transport running — level with the factory
snapshot's own 23.5-25.4% baseline. The rebuilt file carries the TAP pair
instead, which is the cheaper of the two, so that figure is an upper bound
rather than a current reading. `JV/Mutated Instruments` is the zynMI
engine and does **not** appear as a `jalv` process, so do not look for it
there; `053-dub-rimshot` behaves the same way.

---

# The drone and ambient pack

**Twenty snapshots**, `081`–`100`, in [`drone-ambient/`](drone-ambient/), built
by the same tool from [`drone-ambient-manifest.json`](drone-ambient-manifest.json).

**REBUILT 2026-09-04, and this pack was the owner's stated priority:** *"they
just sound like a mess."* It was, and the reasons were measurable.

**All twenty shared ONE arrangement** — identical voice registers `(219, 147,
201)`, identical rhythm registers `(4097, 1, 17)`, identical lengths. Twenty
files, one piece, twenty reverbs.

**All eight channels attacked step 0 together.** `081` rendered as
`D1 D2 D#2 D#2 D3 D3 F3 C5` in G minor: no G anywhere, so the chord had no
root and its lowest note was the fifth; D2 against D#2 is a **minor second at
73 Hz**, which the ear hears as one rough tone beating four times a second, not
as two notes; and two pairs were in **exact unison** — two voices spent on no
extra harmony.

**And they were not drones.** `note_duration` clamps a note to the loop point,
so on the 1/16 grid all twenty used, the longest note the instrument can hold
is **eight of sixteen steps — half a bar**. Every one sat at `gate 800`, the
maximum, which is exactly that. So each "drone" played half a bar of sound,
half a bar of silence, and then all eight re-attacked together: a one-bar
unison chug at 52-90 BPM. The lever nobody had pulled is DIVISION, and it was
not expressible from a manifest until the builder grew it the same day.

## What they are now

**Five sustained layers, none of them attacking at the same instant, over a
four-bar cycle.**

| ch | role | division | holds | chord |
|---|---|---|---|---|
| A | sub anchor | **1/4 — four bars** | two bars per note | — |
| B | bass | **1/4** | two bars | root only |
| C | the chords | **1/8 — two bars** | to the next chord | triad, or a fifth in pentatonic |
| D, E | silent, fader 0.00 | — | — | — |
| F | upper voice | **1/4** | two bars | seventh |
| G | air | **1/8** | to the next | — |
| H | silent | — | — | — |

`gate` is 800 on every layer and it is now **exact rather than maximal**: with
the hits eight steps apart the binding clamp is the gap to the next note, so
every note butts against the one after it. Continuous sound, with the harmony
changing underneath. That is a drone.

Sixteen attacks over the four-bar cycle and **no two channels ever share
one** — the bar line is deliberately impossible to hear. Three layers run four
bars and two run two, so the picture is never the same two bars running.

The interval rule that governs it: an octave or wider is always safe, and below
that, keyed on the lower note — nothing closer than an **octave** below MIDI
36, a **fifth** from 36 to 47, a **minor third** to 59, a **whole tone** to 71,
and anything above that. `tools/validate-manifest.py` enforces it, and every
one of the twenty passes at all twelve roots.

**Pentatonic gets four layers, not five.** PENT has five degrees to the octave
instead of seven, so a triad spans 1.6 octaves and the chord channel reaches
into the one above it. No combination of shape, octave or register fixes it
with five layers — it was searched exhaustively. `088-drone-thaw` and
`093-ambient-solstice` drop the upper voice and take a fifth on the chords, and
that four-layer form is clean in **all seventy-two** root-and-scale
combinations.

| Files | Layout | Channels |
|---|---|---|
| `081`–`090` | **drone** | A, B, C overridden to voices; F, G voices; D, E, H silent |
| `091`–`100` | **ambient** | the same, plus a brushed percussion channel on E |

## SHIFT + GRID is what makes them work

A channel plays as a voice **only** because the snapshot carries a kind
override, which is exactly what SHIFT + GRID sets on the panel. This is not
cosmetic: `_chain_kind()` returns `drum` for channels A–E straight off the
channel table and **never looks at the loaded engine**, so putting a synth on
chain 1 does not make channel A a voice. The override does.

So a rebuilt snapshot carries `kinds` for channels 0, 1 and 2. On the panel,
GRID blinks on those channels and the page indicator reads `VOX` — the
instrument telling you the channel is not itself.

## The modulators — seven, not twelve

**Five of the old twelve were inert.** They were bound to `reverb` and `delay`
on chains whose insert pair was not TAP + TAP, and the driver resolved those
two verbs by plugin NAME — so on all twenty presets the reverb and delay
modulators did nothing, and so did `revsize`, `revtype`, `dlytime` and
`dlyfbk`. What actually moved was four `level` LFOs, one of them a
sample-and-hold at depth 60, and three `cutoff` LFOs. That is why they read as
static but lurching rather than drifting.

Seven per preset now, nine on the ambient ones, and every one resolves:

- **`tri` only.** `s&h` is an event generator and a drone has no events; a
  random filter jump on a sustained pad is the sound of a broken synth.
- **`level` depth 18-30, never more.** Depth 22 on a 0-100 span is about ±3 dB
  — a breath. The old depth 55 was a channel disappearing and returning.
- **Nothing on the anchor.** Channel A never moves; that is what an anchor is.
- **Rates 16, 8, 6, 4 and 3 bars — an LCM of 48 bars**, so at 60 BPM the
  modulation picture takes 192 seconds to repeat. That is where the long form
  comes from, and it has to, because a voice's loop cannot be longer than four
  bars: `_write_voice_pattern` re-stamps the beat count from the division table
  on every rewrite, so coprime polymeter is not available on a sustained layer.
- **Never above rate index 5.** The modulator runs on the poll thread at about
  200 ms, so at 60 BPM index 11 is 1.25 samples per cycle — noise, not a shape.

**A `level` modulator's `base` must equal 100× its channel's fader**, because
it overwrites the strip within 200 ms of load. The old pack had bases of 22-32
against faders of 0.19, with four channels on one system and four on the other;
`validate-manifest.py` refuses that now.

**`random` is 0 on every pitched layer, and that is a proof rather than a
preference.** A bit flip moves the top bits of the pitch register, so an
evolving register walks anywhere in its band and destroys the voicing above
within a minute. Harmonic motion comes from the global key walker instead —
`walk` 8 bars for drone, 4 for ambient — which adds the same offset to every
voice and therefore preserves every interval exactly. `rhythm` is 4-10 on the
upper layers and 0 on the anchor and the bass.

## What the cost measurement changed

**Three effect plugins had to be removed from the design after measuring**, and
one of them was already shipped in the genre pack. The instrument puts the same
insert pair on **all eight chains**, so an effect's cost is multiplied by eight,
and a drone is 24 plugin hosts.

| Removed | Measured | Replaced with |
|---|---|---|
| `Aether` | 61.6% DSP, 5 xruns | `Dragonfly Hall Reverb` |
| `CHOWTapeModel` | 82.4% DSP, 62 xruns | `Calf Vinyl` |
| `ChowPhaserStereo` | 91.6% DSP, **11 of 24 hosts never started** | `YK Chorus` |
| `Roboverb` | 93.8% DSP, **406 xruns** | `Tal-Reverb-III` |
| `SO-kl5 Piano Synthesizer` | the one engine, not an effect — 57.6%, 11 xruns | `RipplerX` |
| two Dragonfly reverbs together | 52.7% DSP, 2 xruns | one of them |

Each was proven by elimination — its partner measured clean in another pair, or
in the engine's case, every other synth in that preset appears in a preset that
passed.

**The synths are not the cost.** One probe carrying all six otherwise-unproven
engines at once measured **16.4%**, barely above the floor. Every problem found
was an insert plugin multiplied by eight. After the replacements, the whole pack
runs **18.9% to 38.6% with zero xruns**.

**Load-testing is not cost-testing.** All four affected genre-pack presets had
already been loaded successfully on the rig, and one of them was glitching at
43.4% with 8 xruns. Loading without error is not running without glitching.

---

# `example-style.json` — a style as odds, and it ships nothing

Every manifest here is a list of **points**: one entry, one snapshot, every
field a single value. `example-style.json` is the same thing written as a
**region** — a field may carry odds instead of a value, and a `rules` block says
what the odds may never break.

```json
"tempo": { "odds": { "choice": [120, 124, 125, 126], "weights": [2, 1, 4, 1] } },
"rules": [ { "path": "drums.steps.0", "require": [0] } ]
```

`tools/style-sampler.py` draws concrete entries from it, seeded, and blends two
existing entries into a third. **Its output is an ordinary manifest**, which
`build-genre-snapshots.py` turns into `.zss` files with no change to that
script:

```bash
python3 tools/style-sampler.py sample --style snapshot/example-style.json \
    --variants 4 --seed 1234 --out /tmp/style-manifest.json
python3 tools/build-genre-snapshots.py --manifest /tmp/style-manifest.json \
    --out /tmp/style-pack
```

**No snapshot in this directory comes from it.** It is a worked example and a
test fixture; the shipped packs are still authored as points, by hand.

Two things about it are load-bearing and are covered by
`tools/tests/test_style_sampler.py`:

- **A plain value still means what it means today.** Odds are marked by a
  wrapper key, `{"odds": {...}}`, and nothing else. Both shipped manifests pass
  through the sampler byte-identical, at every seed.
- **A blend never invents a value it cannot average.** `root`, `scale`,
  `register`, `rhythm_reg`, `steps`, `kits`, `engines` and the insert pair are
  taken **whole from one parent**; only ordered scalars interpolate. The insert
  pair in particular is taken as a PAIR, because it lands on all eight chains
  and a per-slot mix could assemble a banned combination out of two legal
  parents — see the cost table above.
