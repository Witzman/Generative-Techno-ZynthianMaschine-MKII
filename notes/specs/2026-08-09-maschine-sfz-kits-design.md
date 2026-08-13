# Per-Group SFZ Drum Kits — Design

**Date:** 2026-08-09
**Status:** implemented and hardware-verified 2026-08-09 — see
`docs/superpowers/plans/2026-08-09-maschine-sfz-kits.md` and the results below
**Builds on:** `2026-08-06-maschine-drum-rig-design.md` (the rig this extends)

---

## Problem

Every group in the Maschine MK2 drum rig plays a note from one shared GM kit —
`FluidDrums.sf2` on FluidSynth, one chain per group on MIDI ch 1-8. The eight
groups differ only in *which note* they sound. There is no way to change the
character of a sound, and every remaining avenue for doing so is closed:

- Filter (CC 74/71) is inaudible — they are unipolar SoundFont modulators that
  can only *add* to `initialFilterFc`, and `FluidDrums.sf2` ships wide open at
  13500 cents. A real filter needs an LV2 per chain.
- Envelope release is inaudible for the same reason, tested on an open hihat.
- There is no pitch or tune controller.

Zynthian ships 41 drum-machine kits as SFZ in
`/zynthian/zynthian-data/soundfonts/sfz/Drum Machines/` (40 `.sfz` files plus
`DYNOSAUR-808.sfz`, which is a directory holding its own `.sfz` — Zynthian
resolves that to the file inside) — TR808, TR909,
LINN9000, SP1200, Simmons, CR78, HR16, RX11 and more. Letting each group choose
its own kit changes the character of the sound rather than tweaking it, and it
is the largest sonic gain available to this rig.

## Cost, measured

A spike on the Pi (2026-08-09, `/root/sfz_spike.py`, standalone `linuxsampler`
over LSCP, touching no Zynthian state) settled the two questions that could have
killed the idea:

| Measure | Result |
|---|---|
| RSS, 8 different kits in one sampler | 248 MB total (~1.5 MB per extra kit) |
| Kit load time | 0.06 s mean |
| Live kit swap on a running channel | ~0 s |
| CPU, 8 kits triggered at 16th notes | 14% of one core (the Pi 4 has 4) |
| RAM free afterwards | 3.0 GB |

Zynthian's LinuxSampler engine runs **one shared process**
(`zynthian_engine_linuxsampler.py`: `jackname = "LinuxSampler"`, a single
32-channel JACK audio device, processors addressed as `LinuxSampler:outN_`), so
that 248 MB covers all eight groups rather than being a per-group cost.

Resources are not a constraint. The remaining work is mapping, not performance.

---

## Design

### Topology

A new prepared snapshot, `021-maschine-drum-rig-sfz`, with eight **LinuxSampler**
chains on MIDI ch 1-8. `020-maschine-drum-rig.zss` is left untouched as a working
fallback.

A group becomes **a kit plus a note within that kit**. Changing a kit is a preset
change on that chain's existing processor — the ~0 s path measured above. The
driver never adds, removes or swaps a processor, and no group is ever in a mixed
state.

### Controls

Pads, group buttons, F1-F8 mutes, transport and the arrow buttons are unchanged.
Only the encoders move:

| Encoder | Today | After |
|---|---|---|
| 1-4 | hits · rotation · division · length | unchanged |
| 5 | pan — engine zctrl | pan — **mixer strip balance** |
| 6 | expression — engine zctrl | **sample within the kit** |
| 7 | *nothing* | **kit** |
| 8 | volume — engine zctrl | volume — **mixer strip level** |

**Volume and pan must move to the mixer.** `zynthian_engine_linuxsampler`
defines no controllers at all — it inherits `_ctrls = []` from `zynthian_engine`
— so `_zctrl(group, "volume")` returns `None` on an SFZ chain and encoders 5 and
8 would silently do nothing, taking the group-button volume brightness with them.
`zynmixer.set_level` / `set_balance`
(`zynthian_engine_audio_mixer.py:198-237`) is engine-independent, is already
where this driver puts mutes, shows on the touchscreen mixer, and is saved in
snapshots.

**Expression is dropped.** It is a FluidSynth-specific SoundFont modulator with
no mixer equivalent and no meaning for a sampler.

Encoder 6 takes over sample selection *within* a kit. The two arrow buttons
beside the display keep doing this as well; the encoder is faster for hunting
through a kit's 15-30 sounds.

### Kit and sample model

Each `.sfz` is parsed once and cached. The format in these kits is:

```
<region> sample=Samples\Roland TR808\808 Kick_short.wav
lokey=36
hikey=36
```

From that, a kit yields its own `[(note, name)]` list:

- one entry per distinct `lokey`, deduped across velocity layers (several
  `<region>` blocks share a key with `lovel`/`hivel` splits). Match the key
  opcode EXACTLY: `hikey=` contains `key=` as a substring, and 13 of the kits
  have a region where `hikey != lokey`, so a substring test fabricates notes
- the name is the sample's filename without directory or extension, with
  underscores turned to spaces and uppercased: `808 Kick_short` →
  `808 KICK SHORT`

This replaces the `keymaps.json` / `.midnam` lookup, which resolves on the
synth's preset path and cannot match any SFZ kit — without it every group tab
would read `note 36`. The kit's own names are also truer than the GM ones.

Kits use arbitrary note numbers (TR808 starts at 36, 38, 40 …), so a group's
current note usually does not exist in a newly chosen kit. **On a kit change the
group lands on the nearest available note to the one it had**, so it never falls
silent.

### Loading

Encoder 7 updates the displayed kit name immediately. A timer thread commits the
load ~150 ms after movement stops, then previews the group's note once so the
choice is audible. Sweeping the whole list therefore costs one load, not 41.

The load never runs on the MIDI handler thread, and `self.lock` is never held
across the preset call.

### Screen

The layout is unchanged; only the right screen's content moves. Its four columns
become **PAN · SMPL · KIT · VOL**, so the blank column that encoder 7 leaves
today disappears. Group tabs keep showing the group's sample name, now sourced
from the kit rather than from `keymaps.json`.

The double-height value cell fits 4 characters, so kits need a short form:
`TR808`, `LN90`, `1200`. Kit names are abbreviated by a pure function with a
hand-checked table for the machines whose names do not abbreviate mechanically.
The table must keep every label distinct: `SP 12` and `SP1200 1` both reduce to
`SP12` mechanically, so the SP-1200 banks are labelled `1200` and `1201`.

### Testing

Kit parsing, note landing, name derivation and kit-name abbreviation are pure
functions in `maschine_mk2_lib.py` with unit tests, matching how the euclid and
screen-layout code is already tested. Parsing is tested against real kit files.

The preset-change path is verified on hardware: a kit change **while a pattern
is playing**, checked for audio glitches and for xruns.

---

## Risks and open questions

- ~~**`set_preset` on a live chain is untested.**~~ **RESOLVED.** Measured
  through Zynthian's own processor layer with a pattern playing: five
  consecutive kit changes at 0.005-0.043 s, no audio glitch, no UI stall. The
  stopped-transport fallback was not needed. Kit switching while jamming was
  later confirmed by the owner in normal use.
- **The 4-character kit cell is tight.** If the abbreviations read badly on the
  panel, the fix is a wider KIT column at the expense of its neighbour, or a
  name that scrolls while the encoder moves.
- ~~**LinuxSampler streams samples from disk.**~~ **Largely resolved.** A 180 s
  jam on the finished rig: 6.2% system CPU (peak 15% of 400%), 249.5 MB sampler
  RSS — within 1.5 MB of the spike's prediction — 3.0 GB RAM free and **zero
  xruns**. Eight kits cost about 6% of this Pi.

## Rejected alternatives

- **One kit shared by all eight groups.** Simpler to operate and to show, but it
  rules out hybrid kits (808 kick against an SP1200 hat), which is the main
  reason to want this. Per-group covers the shared case anyway — set all eight
  to the same kit.
- **Swapping the engine per group on demand,** keeping FluidSynth as the
  default. Needs runtime processor add/remove instead of a preset change, and
  leaves groups in mixed states that every other code path must then handle.
- **FluidSynth GM as kit 0 in the list.** Carries all of the above complexity
  plus a special case at one end of the list, to keep the least interesting kit
  of the lot.
- **Loading on every detent.** A fast sweep would fire dozens of loads back to
  back against a running sampler, a pattern the spike never tested.
- **Scroll to choose, press to commit.** Safest, but costs an action per change
  and needs the encoder push to be readable, which is not verified on this
  daemon.
- **Tuning on encoder 6.** SFZ can pitch regions, and tune is the one drum
  control genuinely missing — but sample selection is the more useful of the two
  and pitch-per-channel over LSCP is unverified. Worth revisiting once encoder 6
  has proven itself.
