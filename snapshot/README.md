# The factory snapshot

**File:** [`017-generative-techno.zss`](017-generative-techno.zss) · 26,931 bytes ·
md5 `5b8558b7bb7a580e0f4aff5bd6f7240e`

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

Mixer: channel strips `chan_00` … `chan_07` all at **0.19**.

---

## Two honest caveats

**The main strip's level is not stored in this file.** The mixer block carries the
eight channel strips and no `chan_16` entry, so loading this snapshot leaves the
main fader wherever it already was. Set **MASTER** to about 80 on the ALL page, or
the main strip to 0.80 on the touchscreen mixer, after loading. Design headroom is
strips 0.19 with main 0.80: one sampler channel peaks at 1.24 before the mixer and
eight of them summed to 2.92 on the main bus, nearly three times full scale.

**The patterns have not been verified note by note.** Patterns, tempo, swing and
play chance live inside `zynseq_riff_b64`, a 2,544-byte base64 RIFF blob, and that
blob has not been decoded and checked against the intended beat. The driver state
above *was* read back and matches. What remains unconfirmed is which steps
actually fire, the PADS pattern's 8-step length, and which step the single PADS
note sits on — if it is not step 0, `note_duration()` clamps it to
`steps - step`, so it is shorter than the loop.

Both are checked by ear in one pass with
[section 6's checklist](../guide/06-testing.md). No automated check in this
repository can hear.

---

## Rebuilding it

[Appendix A1](../guide/a1-how-017-was-built.md) documents how the snapshot was
made: the chain table, the insert order as measured on the wire, the dry/wet
values, the gain staging, and `tools/build-techno-snapshot.py`, which clones one
channel's insert pair onto the other seven so sixteen instances are not placed by
hand.
