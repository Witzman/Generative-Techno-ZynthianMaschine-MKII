# Appendix A1 · How `017` Was Built

Read this when the snapshot fails to load, when you want a channel layout of your
own, or when you need to rebuild the whole thing from nothing.

---

## The eight chains

| Chain | Title in the snapshot | Engine code | MIDI channel (0-based in the file) |
|---|---|---|---|
| A | `Kick` | `LS/LinuxSampler` | 0 |
| B | `Snare` | `LS/LinuxSampler` | 1 |
| C | `Clap` | `LS/LinuxSampler` | 2 |
| D | `Closed Hat` | `LS/LinuxSampler` | 3 |
| E | `Open Hat` | `LS/LinuxSampler` | 4 |
| F | `BASS` | `JV/JC303` | 5 |
| G | `LEAD` | `JV/Obxd` | 6 |
| H | `PADS` | `JV/padthv1` | 7 |

**The MIDI channel is the contract**, not the title and not the order. The driver
resolves a channel to a chain through `chain_manager.midi_chan_2_chain_ids`, so
the titles are free and the channel numbers are not.

All five drum chains share one LinuxSampler process — Zynthian's sampler engine
runs a single 32-channel JACK client — so eight SFZ kits cost about 250 MB in
total rather than per channel.

---

## The insert pair, as measured on the wire

```
zynmixer:output_NNa/b  →  TAP_Stereo_Echo-NN  →  TAP_Reverberator-NN  →  zynmixer:input_17
```

Echo first, reverb second, so the reverb hears the echo's repeats.

> **This contradicts the 2026-08-10 prototype manual**, whose diagram shows the
> reverb first. The order above was read out of `jack_lsp -c` on the running rig.
> The wire is the truth.

The inserts are fed from the mixer strip's **output**, which is what makes them
post-fader: they inherit the channel's fader and its mute, so muting a channel
takes its reverb and delay tail with it.

### Values that must be forced

| Plugin | Port | Value | Why |
|---|---|---|---|
| TAP Stereo Echo | `dryLevel` | **0.0 dB** | Ships at −4 dB. Across the insert pair that quietly costs every channel about 8 dB |
| TAP Stereo Echo | `lecholevel`, `recholevel` | **−70.0 dB** | Wet starts off; encoder 8 opens it. The two are ganged by the driver |
| TAP Reverberator | `drylevel` | **0.0 dB** | Same reason |
| TAP Reverberator | `wetlevel` | **−70.0 dB** | Wet starts off; encoder 7 opens it |

A default that happens to work is still a default. One candidate reverb defaults
its dry port to near zero, which is why every one of these is set explicitly.

---

## Gain staging

Channel strips **0.19**, main **0.80**.

That is measurement, not caution. One sampler channel peaks at **1.24** before the
mixer, and eight of them summed to **2.92** on the main bus — nearly three times
full scale. The sampler's own volume control is not the lever: taking it from 96
to 40 moved the bus peak by about 1.5 dB. The mixer strips are, and main at 0.80
leaves the MASTER knob travel in both directions.

`017` stores all nine: `chan_00` … `chan_07` at 0.19 and `chan_16` at **0.774**.

Note that the main strip only lands in a snapshot if it is saved *after* MASTER is
set — the first build of `017` had no `chan_16` entry at all, so it loaded leaving
the main fader wherever it happened to be.

---

## Building the sixteen inserts without placing sixteen processors

Do one channel by hand, then let the script replicate it.

1. On the touchscreen, on the Kick chain: **Chain Options** → **Add Audio-FX
   processor** → **LV2 Plugin** → **TAP Stereo Echo**. Repeat for **TAP
   Reverberator**.
2. Set the four values in the table above on that one channel.
3. Save the snapshot from the touchscreen.
4. Run the cloner:

```bash
scp tools/build-techno-snapshot.py root@<pi>:/root/
ssh root@<pi> 'python3 /root/build-techno-snapshot.py \
  /zynthian/zynthian-my-data/snapshots/000/017-generative-techno.zss'
```

It finds the chain carrying both inserts, appends the same two processors to every
other chain that has a MIDI channel, gives each a fresh processor id, copies the
template's `fader_pos`, and backs the file up to `….zss.bak` first.

5. **Load the snapshot on the touchscreen and save it again**, so what is on disk
   is Zynthian's own output rather than the script's.

The script deliberately does not build the whole snapshot. There is no CUIA that
executes code, so nothing outside the UI process can reach Zynthian's live state
manager — and hand-maintaining `fader_pos` in JSON is exactly the kind of guess
this project avoids. One channel is built by hand so that Zynthian, not a script,
decides slots and processor state.

---

## The musical state, and the three constraints that shaped it

124 BPM. Sixteen steps at `1/16` unless stated.

| Ch | State | Read back from the file |
|---|---|---|
| A | euclidean, four-on-the-floor | HITS 4, ROTATE 0 → steps 0, 4, 8, 12 |
| B | euclidean, backbeat | HITS 2, ROTATE 4 → steps 4, 12 |
| C | euclidean, syncopated | HITS 3, ROTATE 3 → steps 3, 8, 13 |
| D | euclidean, offbeat sixteenths | HITS 8, ROTATE 1 → odd steps |
| E | **drum kit driven by a Turing register** | `kinds: {"4": "voice"}`, random 25, density 40, register 179 |
| F | Turing at `LOCK` | random 0, gate 40, octave −1, 16-bit register 61260 |
| G | Turing at full random | random 100, gate 40, range 2, register 179 |
| H | one long note per 8-step loop | random 0, gate 800, density 12, 8-bit register 179 |

Globals: BPM 124, scale index 0 (natural minor), root index 7, master 80, revsize
25, revtype 3, dlytime index 1 (`1/8`), dlyfbk 35. Ownership: all eight channels
`gen`, so no pattern is player-owned.

### Constraint 1 — a voice's pattern length is not on the surface

On a voice, encoder 1 `LENGTH` is the **shift register's** length in bits, not the
pattern's. There is no voice control for pattern beats at all.

PADS reaches 8 steps by a detour: switch it to drum behaviour with **SHIFT +
GRID**, set LENGTH there (it moves in whole beats — 2 beats at `1/16` is 8 steps),
then switch back to voice. SP4 deliberately does **not** move `div` or `beats` on
a kind switch, because those are pattern time rather than kind, so the 8-step
length survives the switch back.

### Constraint 2 — `GATE_MAX` is 800, which is eight steps

`GATE` runs 5-800 %, so the longest note the knob can express is **8 steps**, and
`note_duration()` clamps it further to `steps - step` so a note can never outlive
its pattern. A note spanning a 16-step bar is therefore not expressible from the
knob — which is why PADS' pattern is 8 steps rather than 16. On an 8-step pattern,
GATE 800 starting at step 0 fills the loop exactly.

(A *recorded* note is not bound by `GATE_MAX`: `record_duration()` is
`min(held_steps, steps - step)`. Hold time can produce a 16-step note where the
knob cannot. That route makes the channel player-owned, which the factory snapshot
avoids.)

### Constraint 3 — `DENSITY` is deterministic, not probabilistic

`gate_mask()` sounds the **N lowest gate values**, where
`N = round(density × steps)`, ties broken by step index. On 8 steps, DENSITY 12
gives `round(0.96) = 1` — exactly one sounding step, every pass. And because the
mask is a function of the register, it survives `LOCK` unchanged.

Which step sounds is decided by the register, and the register is not settable
from the surface. Step 0 is the target; a later step is acceptable but then
`note_duration()` clamps the note to `steps - step`, so it is shorter than the
loop.

---

## Driving the surface instead of editing the file

`017` was built by sending MIDI CC into the running instrument, so that the
driver's own code paths wrote everything. That matters: patterns, tempo, swing and
play chance live inside `zynseq_riff_b64`, a base64 RIFF blob, and writing that
blob by hand means reimplementing zynseq's format. A format bug there produces a
snapshot that loads *silently wrong* — which is precisely how the previous
snapshot shipped with two channels at play chance 0 for its entire existence,
reading as healthy on the surface.

The CC map, measured with `aseqdump` one button at a time — never guessed:

| Control | CC |
|---|---|
| Groups A-H (select channel) | **80-87** |
| Encoders 1-8 | **16-23** |
| Modes: CONTROL · STEP · ALL · MIXER (VOLUME) · FILTER (AUTO) | **11 · 32 · 38 · 51 · 37** |
| Page ring within a mode: DL / DR | **47 / 48** |
| Sound stepping: ML / MR | **13 / 14** |
| SHIFT · GRID · REC · SOLO · DUPLICATE | **49 · 4 · 3 · 31 · 29** |
| Play · Erase (hold only) · Restart | **1 · 2 · 7** |
| F1-F8 (mute) | **39-46** |
| Free, emitted, unbound: TL / TR · big encoder press / turn | 5 / 6 · 12 / 15 |

Two traps when driving it this way:

- **The encoders are relative.** The driver computes a delta against its own
  parked baseline and rejects any apparent jump of 8 units or more as a counter
  wrap, because real hardware movement is 0-4 units per report and hardware wraps
  measure −38 to −40. Move values in small increments, and re-read the result
  rather than assuming the burst landed.
- **Selecting a channel or changing mode re-parks every encoder** at mid-travel,
  so a value must be set after the selection that owns it, not before.

> **Not recorded:** the literal CC-value stream used for this particular build.
> The process driving it was interrupted before reporting the sequence, so what is
> documented here is the map and the method rather than a replayable script.
>
> The result, however, is verified twice over: the state table above was **read
> back out of the finished file**, and the patterns were **confirmed by ear** at
> the panel against [section 6's checklist](06-testing.md). Rebuilding from this
> page means re-deriving the CC values from the map — the target state is exact,
> the keystrokes to reach it are not written down.

---

**Back to:** [5 · Import the snapshot](05-import-snapshot.md) ·
[Appendix A2 · Touchscreen patch](a2-touchscreen-patch.md)
