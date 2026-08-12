# 5 · Import the Snapshot

Everything the instrument *is* lives in one file: eight chains on MIDI channels
1-8, sixteen post-fader inserts with their dry and wet levels, the patterns, the
mixer levels, and the driver's own state including every voice's Turing register.

Nothing is constructed at run time. You copy one file and load it.

---

## Step 1 — Copy the snapshot into a bank

```bash
scp snapshot/017-generative-techno.zss \
    root@192.168.2.123:/zynthian/zynthian-my-data/snapshots/000/
```

**The bank subdirectory is not optional.** A snapshot saved or copied to the root
of `/zynthian/zynthian-my-data/snapshots/` is **invisible** in the Zynthian UI's
snapshot list. Bank `000` is the default.

**Verify:**

```bash
ssh root@192.168.2.123 'ls -la /zynthian/zynthian-my-data/snapshots/000/017-generative-techno.zss'
```

---

## Step 2 — Load it from the touchscreen

On the Zynthian **touchscreen**: open Snapshots, go **into** bank `000`, and tap
`017-generative-techno`.

> **Never use webconf's Snapshots page to save.** Its **Name:** field plus the
> checkmark icon **renames the selected bank**. It does not save a snapshot. It
> has destroyed bank `000` on this rig once already. Loading from webconf is safe;
> saving from it is not.

Loading takes about 15 seconds — eight engines start, sixteen plugin hosts come
up, and the driver re-reads its parameters out of the sequencer.

---

## Step 3 — Confirm what you should see

| Where | What |
|---|---|
| Touchscreen mixer | **eight strips plus main** |
| MK2 left display | tab row `A KICK`, `B SNAR`, `C CLAP`, `D CHAT` and four encoder columns |
| MK2 right display | tab row `E OHAT`, `F BASS`, `G LEAD`, `H PADS` and four encoder columns |
| MK2 Group buttons | lit in channel colours; brightness tracks each channel's level |
| MK2 mode buttons | exactly one lit — **CONTROL** |

A **dashed** tab means that channel is not sounding: muted at the mixer, or
silenced by its own generator. That is the instrument's one mechanism for
explaining silence, so read the tab row before assuming a fault.

---

## Step 4 — Press Play once

```
Press PLAY on the MK2.
```

Do this even if something already seems to be running. Restoring a snapshot
rewrites every sequence's play mode from the file, and a loop-all sequence
shorter than the bar goes RESTARTING at its own end — which the next non-sync
clock turns into STARTING, and STARTING does not clock its tracks. The channel
falls silent until the next bar sync.

The driver re-forces LOOP on every transport start, so one press of Play settles
it.

**Verify:** the Play button lights, and a **white pad** sweeps across the selected
channel's step grid.

---

## What the factory snapshot plays

124 BPM. Sixteen steps at `1/16` unless stated.

| Ch | Name | What it does | Steps that fire |
|---|---|---|---|
| A | KICK | four-on-the-floor | 0, 4, 8, 12 |
| B | SNAR | backbeat | 4, 12 |
| C | CLAP | syncopation | 3, 8, 13 |
| D | CHAT | offbeat sixteenths | 1, 3, 5, 7, 9, 11, 13, 15 |
| E | OHAT | a **drum kit driven by a Turing register** — the register walks the kit's own note list, so the sound changes rather than the pitch | varies, DENSITY 40 |
| F | BASS | Turing machine at `LOCK` — a frozen line that repeats bit-identically | fixed |
| G | LEAD | Turing machine at RANDOM 100 — a new phrase roughly every bar | varies |
| H | PADS | an **8-step** pattern with one long note, frozen | one note per loop |

Those three voices are deliberately three different kinds of authorship: **frozen**
(BASS), **fully generative** (LEAD), and **frozen with a single sustained note**
(PADS). Channel E exists to show that the Turing generator is not tied to
melodic engines — a drum kit walked by a register is a texture generator.

Mixer: strips at **0.19**, main at **0.80**. Both inserts pass dry at unity and
their wets start at −70 dB, so the rig arrives dry, with headroom, and you add
space by hand.

---

## When a channel is silent

Work down this list in order. It is ordered by how often each cause is the real
one.

| Check | How |
|---|---|
| Is the transport running? | Play button lit? Press **Play**. |
| Does the tab read dashed? | Then the channel is muted, or its generator is silent — HITS 0 on a drum, play chance 0 on a voice. |
| Is the channel muted? | Its Group button is dark. Tap its F button. |
| Is something soloed? | Every non-soloed Group button goes dark. Tap SOLO to leave solo mode. |
| Are the dependencies actually there? | `bash tools/check-prereqs.sh` — this catches a missing plugin or missing drum kits, which look exactly like a broken snapshot |
| Did the engines start? | `jack_lsp \| grep -c TAP` → **64**. Fewer means plugin instances failed to start. |
| Anything in the log? | `journalctl -u zynthian --since -3min \| grep -iE "traceback\|error"` |

---

**Next:** [6 · Testing](06-testing.md)
