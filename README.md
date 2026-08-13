<img src="docs/logo.svg" alt="" width="76" align="left" hspace="14" vspace="2">

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
[![Support this project](https://img.shields.io/badge/support-PayPal-b4b4bc)](https://paypal.me/ChristianWitzel)

---

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

## What you need

- **Raspberry Pi 4** running ZynthianOS `Oram-2601-1` (section 1 installs it)
- **Native Instruments Maschine MK2**, over USB
- A screen for Zynthian's own UI — any HDMI monitor or TV with a USB mouse and
  keyboard will do. A touchscreen is what the instrument was built around, but it
  is not needed to install: the installer loads the factory snapshot itself.
  Saving snapshots does need the screen
- **No audio interface required.** The Pi's built-in headphone output is what
  every measurement here was made on. An external interface Zynthian supports is
  optional and sounds better, but is untested against this build
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

## Credits

- [Zynthian](https://zynthian.org) — the synth platform this extends. GPL-3.0.
- [wrl/maschine.rs](https://github.com/wrl/maschine.rs) — the original Maschine
  HID daemon, by William Light. The daemon in `daemon/` descends from it via
  [Witzman/MaschineMK2_linux](https://github.com/Witzman/MaschineMK2_linux).

## Licence

GPL-3.0. See [`LICENSE`](LICENSE).
