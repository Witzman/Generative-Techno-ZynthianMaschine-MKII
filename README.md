<img src="docs/logo.svg" alt="" width="76" align="left" hspace="14" vspace="2">

# Generative-Techno ZynthianMaschine MKII


An eight-channel generative groovebox: **five euclidean drum channels and three
Turing-machine voices**, running on Zynthian on a Raspberry Pi 4, played entirely
from a Native Instruments Maschine MK2 — its pads, its encoders, its two displays
and its LEDs.

### ▶ &nbsp;[**Watch it play →**](https://youtu.be/VJs85sTF880)

No hands: the run was scripted and the panel in the video is that same run
played back, so the pads, both displays and every lamp are what the hardware
actually showed.

### 📖 &nbsp;[**Read the Build Guide →**](https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/)

**<https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/>**

From a blank SD card to a rig that plays. Start with **Fast installation** — one
command on the Pi — or work through **Manual installation** if you would rather
run each step yourself.

Want to know whether it does a particular thing? The guide's **Features** page
is the whole instrument in one list, every entry linked to the page that walks
you through it, and **Changelog** says when each of them arrived.

![GPL-3.0](https://img.shields.io/badge/licence-GPL--3.0-b4b4bc)
![ZynthianOS Oram-2601-1](https://img.shields.io/badge/ZynthianOS-Oram--2601--1-b4b4bc)
![2091 tests](https://img.shields.io/badge/tests-2091%20passing-b4b4bc)
[![Support this project](https://img.shields.io/badge/support-PayPal-b4b4bc)](https://paypal.me/ChristianWitzel)

---

## What the instrument does

Eight channels are **always alive** — nothing is created or torn down while you
play.

**Four buttons decide what the eight encoders mean**, and each one answers one
question about the channel you have selected. **CONTROL** — how does it sound.
**STEP** — what does it play. **AUTO** — what does the machine do to it by
itself. **VOLUME** — what holds for everything.

**The fifth button, ALL, is not a mode. It is a lens.** Hold it, or tap it to
latch it, and the eight encoders stop being eight verbs of one channel and
become **one verb across all eight** — whichever knob your hand last moved. Turn
CHANCE on the kick, hold ALL, and there is CHANCE on all eight under your
fingers. A channel that has no such control draws four dashes rather than
pretending. Let go and you are back where you were, on the same page, without
having navigated anywhere.

That is the whole grammar of the panel, and the rest of it follows one rule
each: **a tap latches and a hold is momentary**, for every modifier there is;
**a light is dark when it does nothing, dim when it is available, bright when it
is acting, and blinks when it is latched**, and nothing else is invented; and
the big encoder's press is **HOME** — back to a known place, without throwing
anything away.

**The generator owns the pattern.** You do not draw a beat and decorate it. You
set hits, rotation and randomness, and the driver writes notes into Zynthian's own
sequencer — so patterns persist in snapshots and the touchscreen pattern editor
mirrors exactly what the pads show.

The three voices are Turing machines: a shift register clocked once per pass and
mutated one bit at a time, read as pitch. Set `MELODY` to 0 and the loop you are
hearing is frozen **bit-identically**, for as long as you leave it there. A voice
can be switched to a **bounded random walk** instead, which strolls where the
register jumps, and one voice can be **fed** another's register so the two drift
toward each other without ever becoming the same line. A slow **chord walker**
moves the root all three share, along the scale rather than chromatically, so
three independent lines become a progression.

The drums have an evolving generator of their own now: **RHYTHM** lets steps
appear and disappear from bar to bar. Tapping a pad writes into that same
register rather than editing the pattern — **a tap takes a step away where there
is one and puts a step in where there is not** — so a hand-chosen rhythm
survives rotation and is saved with the snapshot, and HITS, DIVIDE or LENGTH put
every step back when you want the plain euclidean line again.

**The pads are pressure-sensitive.** Squeeze a held pad on a voice and the filter
opens for as long as you press, easing back when you let go.

**A gesture can land on a bar rather than under your finger.** The instrument
counts bars, so ARM composes a macro with a length — a drop, a thinning of the
odds, half or double time, a break, a ratchet ramp — and it fires on the
boundary and resolves by itself. MOD binds a bar-synced LFO to any knob, FREEZE
parks everything that moves, a held MUTE turns the pads into a mute grid, and
SHIFT + REC captures the master to a WAV on the Pi.

The factory snapshot arrives playing 125 BPM techno: four-on-the-floor across
A-D, a drum kit walked by a Turing register on E, a frozen bass line on F, a lead
at full random on G, and one long sustained note per 8-step loop on H — three
different kinds of authorship, one per voice. It is
`018-generative-techno-main-insert`, which carries a filter on the Main chain, so
one knob sweeps the whole mix; `017-generative-techno` ships beside it as the
same instrument without that insert.

## What you need

- **Raspberry Pi 4** running ZynthianOS `Oram-2601-1` (section 1 installs it)
- **Native Instruments Maschine MK2**, over USB
- A screen for Zynthian's own UI — any HDMI monitor or TV with a USB mouse and
  keyboard will do. A touchscreen is what the instrument was built around, but it
  is not needed to install: the installer loads the factory snapshot itself.
  Saving a snapshot needs the UI — either that screen, or Zynthian's own VNC
  server in a browser, which is the headless answer
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

**The daemon listens on one socket, and it is loopback only** — OSC, which is
how the driver paints the lights and the screens. There used to be a second: a
pad-and-encoder editor on port 9001, on every interface, with no authentication,
in a process running as root, whose commands remapped what the pads send and
saved that to disk. It was **deleted in September 2026** rather than narrowed to
loopback, along with a complete second step-sequencer that lived inside the
daemon — about eight hundred lines of inherited code that nothing in this
instrument had ever used. Pad notes and encoder CCs are edited in
`maschine.json` and take a restart.

Every test in this repository runs without a Pi and without the controller:

```bash
cd ctrldev && python3 -m unittest discover -s tests -q   # the driver
cd daemon  && cargo test                                 # the HID daemon
bash system/tests/test-system-files.sh                   # units, udev, helpers
python3 -m unittest discover -s tools/tests -q           # the offline tools
bash system/tests/test-dry-run.sh                        # what each installer PRINTS
```

**The badge above is the only count written down, and it is a snapshot.** The
per-suite figures used to be in this block and every one of them went stale
within days of being typed; a number nobody re-runs is a claim rather than a
fact. Run the commands. Three kinds of test sit behind them.

**The libraries** are ordinary unit tests, and as much behaviour as possible is
pushed down into `techno_lib.py` so that it can be one.

**The driver is around eleven thousand lines and needs both of the others.** Twelve AST guards
read its *source* and answer questions no instance can — is a name defined
twice, does every LED name it sends exist in the daemon, is every key the
snapshot saves one the load reads back. And since September 2026 it is also
*constructed*: `tests/rig_stub.py` stands in for the four Zynthian imports in a
few dozen lines, so `midi_event` can be driven byte by byte and the thing that
had no test at all — which overlay owns a pad, which press is swallowed — has
one. No CC number is written down in those tests; every one is looked up in the
driver's own tables at run time, because that map is measured hardware fact.

**The installers are tested by what they PRINT.** The dry-run suite shadows
`ssh`, `scp`, `systemctl` and `cargo` with stubs that fail if called, so a dry
run that actually executes something breaks the build rather than someone's
rig.

## Credits

- [Zynthian](https://zynthian.org) — the synth platform this extends. GPL-3.0.
- [wrl/maschine.rs](https://github.com/wrl/maschine.rs) — the original Maschine
  HID daemon, by William Light. The daemon in `daemon/` descends from it via
  [Witzman/MaschineMK2_linux](https://github.com/Witzman/MaschineMK2_linux).

## Licence

GPL-3.0. See [`LICENSE`](LICENSE).
