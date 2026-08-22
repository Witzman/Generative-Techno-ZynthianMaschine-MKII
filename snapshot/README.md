# Snapshots

Three things live here: the **factory snapshot** — `018`, the instrument's own
configuration with a master filter on the Main chain, with `017` beside it as
the same instrument without one; the **genre pack**, fifty-one fixed
arrangements built from it; and
the **drone and ambient pack**, twenty slow pieces that are the opposite
instrument — almost no pattern, and everything moving.

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
· 55,109 bytes · md5 `df1c6ebb86910b670d3190911dfbf7da` (measured 2026-08-22)

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

These are **fixed arrangements, not generative patches.** Every voice is at
`random 0` and `rhythm 0`, so the melody and the rhythm are locked; `mods` is
empty, so nothing is being modulated. Load one and it plays the same bar until
you change it. That is the point of the pack: the rest of the instrument is
about evolution, and these are the starting places.

| Files | What varies | Effects |
|---|---|---|
| `031`–`060` | thirty different instrumentations across five genres | the factory pair: TAP Stereo Echo + TAP Reverberator |
| `061`–`080` | twenty more | a different effect pair on every one, no pair repeated |

Ten each of **house**, **deep house**, **minimal**, **dub** and **trance**, 118
to 140 BPM, plus `101` as an eleventh dub. 21 distinct synth engines, 24
distinct drum kits, 21 distinct effect pairs.

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

**Every one of the fifty-one was checked structurally** — the RIFF re-parses with no
trailing bytes, all eight patterns present, every drum step list matching the
manifest, every drum note matching that kit's scanned map, every voice's steps
matching its `rhythm_reg`, evolution off, `mods` and `stash` empty, the engines
and the effect pair actually applied to all eight chains.

**Three were loaded on the rig**, through the real boot path, and the engines
that came up were confirmed as JACK clients — one from each transform the
builder performs:

| Loaded | Voices that came up | Effects that came up |
|---|---|---|
| `031-house-classic` | JC303, Obxd, padthv1 | 8 × TAP Stereo Echo, 8 × TAP Reverberator |
| `061-fx-tape-chorus` | JC303, Obxd, padthv1 | 8 × CHOWTapeModel, 8 × YK Chorus |
| `080-fx-chorus-plate` | amsynth, Surge XT, String machine | 8 × YK Chorus, 8 × Tal-Reverb-III |

Zero driver errors on all three, and one `LinuxSampler` serving the five drum
chains in each. That covers the untouched-effects case, the swapped-effects
case and the swapped-synths case.

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
| Tempo | **120 BPM — chosen because it is EXACT** (see the tempo note in the factory
snapshot section above). Of the dub entries only this one and `050` sit on a zero-error tempo |
| Key | root 10, scale 5 — B♭ pentatonic, the only dub entry in that pair |
| Drums | TR808 across all five, sparse: kick four-on-floor, snare on 4 and 12, one clap on 12, offbeat hats |
| Voices | sub on the one and the and (`rhythm_reg` 16705), the stab strictly offbeat (17476), one sustained pad per bar (1, gate 800) |
| Effects | **`JV/Tal-Dub-3` → `JV/Tal-Reverb-III`** — the dub delay proper into a plate. A pair used nowhere else: `073` is Tal-Dub-3 into Tal-Reverb-II, `076` is Modulay into Tal-Reverb-III |

**Why those effects.** The insert pair sits on **all eight chains**, so an
effect costs eight times what it looks like — Tal-Reverb-III is the reverb this
project moved to when Roboverb was measured unusable at eight instances, and
Tal-Dub-3 is already proven at eight in `073` and `074`. Neither is on the
banned list.

**Measured on the rig, 2026-08-21**: loads with 8 × Tal-Dub-3 and
8 × Tal-Reverb-III instantiated, **JACK DSP mean 23.9%, p95 24.1%, zero
xruns** over 60 s with the transport running — level with the factory
snapshot's own 23.5-25.4% baseline. `JV/Mutated Instruments` is the zynMI
engine and does **not** appear as a `jalv` process, so do not look for it
there; `053-dub-rimshot` behaves the same way.

---

# The drone and ambient pack

**Twenty snapshots**, `081`–`100`, in [`drone-ambient/`](drone-ambient/), built
by the same tool from [`drone-ambient-manifest.json`](drone-ambient-manifest.json).

Where the genre pack is fixed arrangements with no modulation, this pack is the
inverse: **barely any rhythm, and twelve modulators per preset.** 240 in total.

| Files | Layout | Channels |
|---|---|---|
| `081`–`090` | **drone** | all eight play as voices, each on its own synth engine |
| `091`–`100` | **ambient** | A–D stay drums, E–H are voices |

Tempos 52–90. Every voice is `gate 800` — an eight-step note — with a
`rhythm_reg` of one or two bits, so a drone voice sounds once or twice a bar and
holds.

## SHIFT + GRID is what makes them work

A channel plays as a voice **only** because the snapshot carries a kind
override, which is exactly what SHIFT + GRID sets on the panel. This is not
cosmetic: `_chain_kind()` returns `drum` for channels A–E straight off the
channel table and **never looks at the loaded engine**, so putting a synth on
chain 1 does not make channel A a voice. The override does.

So a drone snapshot carries `kinds` for channels 0–4, and the ambient ones carry
it for channel 4 alone. On the panel, GRID blinks on those channels and the page
indicator reads `VOX` — the instrument telling you the channel is not itself.

Four ambient presets leave channel E on **LinuxSampler with no synth**, so the
Turing register walks the kit's own samples rather than a scale. That is the
factory snapshot's trick, and it is a genuinely different colour from a synth
pad: `092`, `094`, `097`, `099`.

## The modulators

Twelve per preset, bound to `level`, `reverb`, `delay`, `cutoff` and `reso`.
Rates are **bar-synced and slow** — indices 0–5 only, which is 16 bars down to
2 bars per cycle. At 60 BPM, index 0 is a 64-second sweep.

`level`, `reverb` and `delay` carry 180 of the 240 because **they always
resolve**: level is the mixer strip, reverb and delay are the two insert wets
every chain has. `cutoff` and `reso` are placed only on channels running JC303,
Obxd or padthv1, whose ports this project has actually measured. That matters
because a modulator on a port the loaded synth does not publish is **inert, not
an error** — `_mod_write()` treats a missing span as "skip" — so it would be
silent weight in the file rather than a fault you could hear and fix.

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
