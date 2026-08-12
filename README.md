# Generative-Techno ZynthianMaschine MKII

An eight-channel generative groovebox: five euclidean drum channels and three
Turing-machine voices, running on Zynthian on a Raspberry Pi 4, played entirely
from a Native Instruments Maschine MK2.

**Build guide:** [`guide/01-what-it-is.md`](guide/01-what-it-is.md) — seven
sections, from a blank SD card to a rig that plays. Also rendered as a site from
this repository's `docs/`.

**Status:** verified on ZynthianOS `Oram-2601-1`.

## What is in here

| Directory | Contents |
|---|---|
| `guide/` | The build guide, Markdown source. `docs/` is generated from it |
| `daemon/` | The Maschine MK2 HID daemon, Rust. Build it on the Pi |
| `ctrldev/` | The Zynthian control-surface driver, plus 271 unit tests that need no Pi |
| `system/` | udev rule, systemd units, JACK connect and clock helpers, daemon config |
| `tools/` | Preflight check, the `zynautoconnect` patcher, the snapshot builder, the site generator |
| `snapshot/` | The factory snapshot, `017-generative-techno.zss` |

Quick start, on a Pi that already runs Zynthian:

```bash
git clone https://github.com/Witzman/Generative-Techno-ZynthianMaschine-MKII.git
cd Generative-Techno-ZynthianMaschine-MKII
bash tools/check-prereqs.sh     # what is missing, if anything
./install.sh --dry-run          # what the installer would do
```

Read [section 3](guide/03-install-driver.md) before running the installer for
real. It documents seven traps that produce silent failures, and the guide is
authoritative — `install.sh` is only a wrapper over it.

## Credits

- [Zynthian](https://zynthian.org) — the synth platform this extends. GPL-3.0.
- [wrl/maschine.rs](https://github.com/wrl/maschine.rs) — the original Maschine
  HID daemon, by William Light. The daemon in `daemon/` descends from it via
  [Witzman/MaschineMK2_linux](https://github.com/Witzman/MaschineMK2_linux).

## Licence

GPL-3.0. See `LICENSE`.
