# The factory snapshot

**File:** [`017-generative-techno.zss`](017-generative-techno.zss) · 27,015 bytes ·
md5 `0becfb52db2c195143956a6389b9f4dd`

This one file *is* the instrument's configuration: eight chains on MIDI channels
1-8, sixteen post-fader insert plugins with their dry and wet levels, the
patterns, the mixer levels, and the driver's own state — including every voice's
Turing register, which is why a frozen line comes back frozen and playing the
same notes.

Install it with [section 5](../guide/05-import-snapshot.md):

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
[section 6's checklist](../guide/06-testing.md). This pass is not optional and
cannot be automated: patterns, tempo, swing and play chance live inside
`zynseq_riff_b64`, a 2,544-byte base64 RIFF blob, and nothing in this repository
decodes it. A snapshot that loads without error is not a snapshot that plays the
right notes — the previous snapshot in this project shipped with two channels at
play chance 0 for its entire existence, reading as perfectly healthy on the
surface.

---

## Rebuilding it

[Appendix A1](../guide/a1-how-017-was-built.md) documents how the snapshot was
made: the chain table, the insert order as measured on the wire, the dry/wet
values, the gain staging, and `tools/build-techno-snapshot.py`, which clones one
channel's insert pair onto the other seven so sixteen instances are not placed by
hand.
