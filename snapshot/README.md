# Snapshots

Two things live here: the **factory snapshot**, which is the instrument's own
configuration, and the **genre pack**, fifty fixed arrangements built from it.

---

# The factory snapshot

**File:** [`017-generative-techno.zss`](017-generative-techno.zss) · 27,015 bytes ·
md5 `0becfb52db2c195143956a6389b9f4dd`

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

Read directly out of the file, not from intent. 124 BPM, sixteen steps at `1/16`
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

Globals: BPM 124, scale index 0 (natural minor), root index 7, master 80,
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


---

# The genre pack

**Fifty snapshots**, `031`–`080`, in [`genre-pack/`](genre-pack/), built from the
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
to 140 BPM. 21 distinct synth engines, 24 distinct drum kits, 20 distinct effect
pairs.

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

`install.sh` and `bootstrap.sh` place the whole pack in bank `000` beside the
factory snapshot. By hand:

```bash
scp snapshot/genre-pack/*.zss \
    root@<your-pi>:/zynthian/zynthian-my-data/snapshots/000/
```

## How the pack was verified

**Every one of the fifty was checked structurally** — the RIFF re-parses with no
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

**What that does not prove:** that all fifty sound good. Structure is verified,
taste is not. The same caveat as the factory snapshot applies, for the same
reason — loading without error is not playing the right notes.
