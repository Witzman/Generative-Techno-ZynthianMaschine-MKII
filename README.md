# Generative-Techno ZynthianMaschine MKII

An eight-channel generative groovebox: five euclidean drum channels and three
Turing-machine voices, running on Zynthian on a Raspberry Pi 4, played entirely
from a Native Instruments Maschine MK2.

**Build guide:** [`guide/01-what-it-is.md`](guide/01-what-it-is.md) · rendered at
the project's GitHub Pages site.

**Status:** verified on ZynthianOS `Oram-2601-1`.

## Credits

- [Zynthian](https://zynthian.org) — the synth platform this extends. GPL-3.0.
- [wrl/maschine.rs](https://github.com/wrl/maschine.rs) — the original Maschine
  HID daemon, by William Light. The daemon in `daemon/` descends from it via
  [Witzman/MaschineMK2_linux](https://github.com/Witzman/MaschineMK2_linux).

## Licence

GPL-3.0. See `LICENSE`.
