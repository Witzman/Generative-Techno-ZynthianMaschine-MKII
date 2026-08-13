# Generative-Techno ZynthianMaschine MKII

An eight-channel generative groovebox: **five euclidean drum channels and three
Turing-machine voices**, running on Zynthian on a Raspberry Pi 4, played entirely
from a Native Instruments Maschine MK2 — its pads, its encoders, its two displays
and its LEDs.

### 📖 &nbsp;[**Read the Build Guide →**](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/)

**<https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/>**

From a blank SD card to a rig that plays. Start with **Fast installation** — one
command on the Pi — or work through **Manual installation** if you would rather
run each step yourself.

![GPL-3.0](https://img.shields.io/badge/licence-GPL--3.0-b4b4bc)
![ZynthianOS Oram-2601-1](https://img.shields.io/badge/ZynthianOS-Oram--2601--1-b4b4bc)
![271 tests](https://img.shields.io/badge/tests-271%20passing-b4b4bc)

---

## The guide

| | Section | What it covers |
|---|---|---|
| | [Start here](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/) | What it is, the hardware bill, and which section to read |
| 1 | [Fast installation](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/01-fast-installation.html) | Six actions, one command, about forty minutes |
| 2 | [Features](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/02-features.html) | The eight channels, both generators, the five modes and every encoder |
| 3 | [Playing](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/03-playing.html) | Placeholder — playing technique is not written yet |
| 4 | [Manual installation](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/04-manual-installation.html) | Sixteen steps, each with what it does, why, and how to confirm it |
| 5 | [Internals](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/05-internals.html) | The control path, the `zynautoconnect` patch, the driver, the snapshot |
| A | [Touchscreen patch](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/a1-touchscreen-patch.html) | Optional coordinate-scaling fix for mismatched panels |

## What the instrument does

Eight channels are **always alive** — nothing is created or torn down while you
play. A mode decides what the eight encoders mean: CONTROL is what the selected
channel sounds like, STEP is what it plays, ALL is the machine's globals, and
MIXER and FILTER spread one parameter across all eight channels at once.

**The generator owns the pattern.** You do not draw a beat and decorate it. You
set hits, rotation and randomness, and the driver writes notes into Zynthian's own
sequencer — so patterns persist in snapshots and the touchscreen pattern editor
mirrors exactly what the pads show.

The three voices are Turing machines: a shift register clocked once per pass and
mutated one bit at a time, read as pitch. Set `RANDOM` to 0 and the loop you are
hearing is frozen **bit-identically**, for as long as you leave it there.

The factory snapshot arrives playing 124 BPM techno: four-on-the-floor across
A-D, a drum kit walked by a Turing register on E, a frozen bass line on F, a lead
at full random on G, and one long sustained note per 8-step loop on H — three
different kinds of authorship, one per voice.

## What is in here

| Directory | Contents |
|---|---|
| [`docs/`](docs/) | The build guide as published — GitHub Pages serves it |
| [`daemon/`](daemon/) | The Maschine MK2 HID daemon, Rust. Built on the Pi |
| [`ctrldev/`](ctrldev/) | The Zynthian control-surface driver, plus 271 unit tests that need no Pi |
| [`system/`](system/) | udev rule, systemd units, JACK connect and clock helpers, daemon config |
| [`tools/`](tools/) | Preflight check, the `zynautoconnect` patcher, the snapshot builder |
| [`snapshot/`](snapshot/) | The factory snapshot, `017-generative-techno.zss` |
| [`bootstrap.sh`](bootstrap.sh) | One-command install for a fresh Pi |
| [`install.sh`](install.sh) | The installer `bootstrap.sh` calls; runs standalone too |

## What you need

- **Raspberry Pi 4** running ZynthianOS `Oram-2601-1` (section 1 installs it)
- **Native Instruments Maschine MK2**, over USB
- An audio interface Zynthian supports, and a display for Zynthian's own UI —
  snapshots are loaded there, so it is not optional
- An SD card of 16 GB or more

Third-party plugins and samples are **not** vendored here: Obxd, padthv1 and the
TAP effects come from Debian packages, JC303 from Zynthian's own plugin set, and
the SFZ drum kits ride in the OS image. `tools/check-prereqs.sh` tells you which
of them are missing rather than letting a snapshot fail mysteriously.

## Quick start

On a Pi that already runs Zynthian:

```bash
git clone https://github.com/Witzman/Generative-Techno-ZynthianMaschine-MKII.git
cd Generative-Techno-ZynthianMaschine-MKII
bash tools/check-prereqs.sh     # what is missing, if anything
./install.sh --dry-run          # what the installer would do, changing nothing
```

Read [section 4](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/04-manual-installation.html)
before running the installer for real. It documents the failures that are silent —
a driver that never binds and says so nowhere, a daemon restarted in the wrong
order, a missing config flag that destroys the pad LEDs on first touch. The guide
is authoritative; `install.sh` is only a wrapper over it.

The unit tests need no Pi and no hardware:

```bash
cd ctrldev && python3 -m unittest discover -s tests -q
# → Ran 271 tests ... OK
```

## Scope, stated plainly

Verified on **one rig**: ZynthianOS `Oram-2601-1`, `zynthian-ui` on branch
`oram-2601.1`, one Maschine MK2, audio on the Pi's built-in headphone output at
48 kHz.

The factory snapshot is **confirmed by ear** on that rig: its driver state was
read back out of the file, and its patterns were checked at the panel against
[section 4's verification](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/04-manual-installation.html).

One honest limit, also stated in the guide where it matters:

- **The installation sections were written from a running instrument, not walked
  from a fresh flash** — there was no spare SD card. Where a clean install could
  differ, the guide gives a check rather than a promise.

## Credits

- [Zynthian](https://zynthian.org) — the synth platform this extends. GPL-3.0.
- [wrl/maschine.rs](https://github.com/wrl/maschine.rs) — the original Maschine
  HID daemon, by William Light. The daemon in `daemon/` descends from it via
  [Witzman/MaschineMK2_linux](https://github.com/Witzman/MaschineMK2_linux).

## Licence

GPL-3.0. See [`LICENSE`](LICENSE).
