# Generative-Techno ZynthianMaschine MKII — repository and documentation design

**Date:** 2026-08-13
**Status:** design, agreed with the owner in brainstorming
**Supersedes:** `zynth-docs/htmldoku/project-techno-machine.md` (to be deleted)

---

## 1. Goal

Publish the Techno Machine as a self-contained, public, buildable project under one
name: **Generative-Techno ZynthianMaschine MKII**.

A reader who owns a Raspberry Pi 4 and a Maschine MK2 must be able to check out
**one repository**, follow seven sections, and end up with the instrument running
and making the same music the author's rig makes.

The existing `zynth-docs` site is left as it is. Its git history is the backup of
everything written so far; no separate archive is taken.

---

## 2. Decisions taken

| # | Decision | Rationale |
|---|---|---|
| D1 | New repo `Witzman/Generative-Techno-ZynthianMaschine-MKII`, public | GitHub slugs take no spaces; the display name lives in the README |
| D2 | Documentation is Markdown source **and** generated HTML on GitHub Pages | Markdown is read on GitHub while copying commands; Pages gives the same reading experience as the zynth-docs site |
| D3 | The Rust HID daemon is **vendored** into the repo | One checkout must be enough. The new repo becomes the daemon's development home; `Witzman/MaschineMK2_linux` gets a pointer and goes read-only |
| D4 | Guide is authoritative, `install.sh` is an optional wrapper | Manual steps are debuggable; the script exists for the impatient and enforces ordering traps |
| D5 | Pinned to **ZynthianOS Oram 2601 stable** | It is what the author's rig runs *and* the current default download. Vangelis 2606/2607 are betas |
| D6 | A clean factory snapshot **`017-generative-techno`** ships, not `016` | `016` carries the last jam's mixer levels and driver state |
| D7 | Licence **GPL-3.0** | Forced: `zynthian-ui` is GPL-3.0 and so is the daemon (fork of `wrl/maschine.rs`) |
| D8 | `zynth-docs/htmldoku/project-techno-machine.md` is **deleted**, sidebar entry removed | One canonical build document. The page was published 2026-08-12 and overlaps the new guide by ~70% |
| D9 | Snapshot import is the only build step; an **appendix** documents how `017` was built | Short main path without a black box. The appendix is the repair manual |
| D10 | `017` is built by **driving the live rig** over MIDI CC | Patterns, tempo, swing and chance live in `zynseq_riff_b64`, a base64 RIFF blob. Writing it offline means implementing zynseq's format, and a format bug produces a snapshot that loads *silently wrong* — the exact failure that hid `016`'s chance-0 channels for its whole existence |
| D11 | The `multitouch.py` coordinate fix ships as an **optional** appendix patch | Not part of the instrument, but it is the difference between working and unusable touch on a mismatched panel |
| D12 | No spare SD card: sections 2-5 are **not** verified from a fresh flash | Stated in the guide rather than implied |

---

## 3. Repository layout

```
README.md                       short: what it is in one screen, contents, credits, licence.
                                Links into guide/01, which is canonical — the README
                                never grows a second copy of the same prose
LICENSE                         GPL-3.0
guide/
  01-what-it-is.md              the site's landing page
  02-install-zynthianos.md
  03-install-driver.md
  04-prepare-zynthian.md
  05-import-snapshot.md
  06-testing.md
  07-playing.md                 placeholder
  a1-how-017-was-built.md       appendix — chain table, insert order, CC sequence
  a2-touchscreen-patch.md       appendix — optional multitouch.py fix
docs/                           generated HTML; GitHub Pages serves main branch /docs
daemon/                         vendored Rust HID daemon (GPL-3.0, credits wrl/maschine.rs)
ctrldev/                        zynthian_ctrldev_maschine_mk2.py · techno_lib.py · maschine_mk2_lib.py
tests/                          test_techno_lib.py · test_maschine_mk2_lib.py (271 tests)
system/                         99-maschine.rules · maschine-mk2.service · maschine-web.service ·
                                maschine-clock.service · maschine-jack-connect.sh · maschine.json
tools/
  generate-html.py              ported from zynth-docs, page list trimmed to this project
  patch-autoconnect-maschine.py
  build-techno-snapshot.py
  check-prereqs.sh              preflight: one line per dependency, non-zero exit on any miss
  sync-from-dev.sh              copies ctrldev + tests from ~/zynth/zynthian-ui; git diff is the drift report
install.sh                      optional wrapper over section 3
snapshot/017-generative-techno.zss
```

### What is deliberately *not* vendored

- `obxd-lv2`, `padthv1-lv2`, `tap-lv2` — Debian packages, `apt install`ed by section 4.
- JC303 — comes from Zynthian's own plugin set at `/zynthian/zynthian-plugins/lv2`.
- The 42 SFZ drum machines — 43 MB, ride in the OS image (`sfz/**` is gitignored in
  `zynthian-data`), so section 4 **checks** for them instead of claiming they are stock.
- Any Zynthian core file. Measured 2026-08-13: the whole driver project touches exactly
  five files, all under `zyngine/ctrldev/`. Zynthian core is untouched.

### The one core change, and why it is a patcher

`zynautoconnect/zynthian_autoconnect.py` must gain two things or the driver is
listed *Found* and never *Loaded*: the daemon's port on the hardware-source
whitelist, and a pinned uid (`virtual:maschine.rs/Maschine MK2 Pads`) because the
ALSA client number in the port name changes across boots.

This ships as `tools/patch-autoconnect-maschine.py`, which edits the reader's own
file and is idempotent — never as a copy of the author's file, which would
overwrite their Zynthian version with a different one.

Two other modified core files on the author's Pi are **excluded** as unrelated:
`zyngine/zynthian_state_manager.py` (a 50 ms master-CUIA debounce belonging to the
SMC-PAD project) and `zyngui/multitouch.py` (touchscreen scaling, which returns as
the optional appendix patch D11).

---

## 4. Documentation structure

### Section 1 — What it is

Eight always-alive channels, five drums and three Turing voices, played from an MK2
whose displays and LEDs the driver owns. The channel table. A text block diagram.
What it is not: not a DAW, not a Zynthian fork, no pattern chaining. Hardware bill.
Scope statement naming the exact verified versions.

### Section 2 — Install ZynthianOS

Pinned to `Oram-2601-1`. Download `zynthianos-last-stable.img.xz` (currently the
same build as `2026-01-27-zynthianos-oram-2601-stable.img.xz`), verify the `.md5`,
flash, first boot, enable SSH, reach webconf. Flashing detail links to
zynthian.org's own documentation rather than being copied. Confirmation table:
`/zynthian/build_info.txt` reads `Oram-2601-1`, `zynthian-ui` on branch
`oram-2601.1`, SSH answers, webconf loads. Vangelis betas named and out of scope.

Carries the D12 note: not walked from a fresh flash.

### Section 3 — Install the driver and daemon

The trap-dense section. In order: Rust toolchain · build the vendored daemon · udev
rule (`/dev/maschine` symlink plus hotplug restart) · the three systemd units ·
`maschine.json` with `external_pad_leds: true` · `a2jmidid` exporting software
clients · `maschine-jack-connect.sh` · the `zynautoconnect` patch · the three
ctrldev files · restart order **daemon first, UI second** · the *Loaded, not Found*
check · exactly one `devN_in` route.

Every trap gets one line stating what breaks when it is skipped. `install.sh` is
offered at the end, not the start.

### Section 4 — Prepare Zynthian

`apt install obxd-lv2 padthv1-lv2 tap-lv2` · confirm JC303 · enable the plugins on
webconf's Engines page · **Regenerate LV2 Cache** · confirm the SFZ drum machines
at `/zynthian/zynthian-data/soundfonts/sfz/Drum Machines`. Ends by running
`tools/check-prereqs.sh`, so a failed import in section 5 becomes a list rather
than a mystery.

### Section 5 — Import the snapshot

Copy `017-generative-techno.zss` into `/zynthian/zynthian-my-data/snapshots/000/`,
load from the touchscreen, with the warning that webconf's Snapshots **Name:**
field renames the selected *bank* and has destroyed bank `000` once. What to see
within ~15 s: eight strips plus main, the tab row on both MK2 displays, Group
buttons in channel colours. Press **Play** once after loading, because LOOP play
mode is re-forced on transport start.

### Section 6 — Testing

Machine-checkable first: `python3 -m unittest discover -s tests -q` (271 tests, no
Pi, no hardware — and the guide states plainly that the driver itself cannot be
imported off-Pi because `zynlibs.zynseq` is Pi-only, so these tests are the only
automated proof). Then on the Pi: `jack_lsp | grep -c TAP` → 64, exactly one
`devN_in`, no tracebacks, watchdog cadence sane, `check-prereqs.sh` green.

Then the by-ear checklist, explicitly the reader's to run: kick on the four, the
frozen bass repeating exactly, LEAD changing every wrap, PADS one hit per 8-step
loop, E walking its kit, mute/solo/erase, and the dry-survives-a-full-wet-sweep
test.

### Section 7 — Playing

Placeholder. Lists what will go here — the euclidean model, LOCK as the central
gesture, REC and ownership, SHIFT + GRID — and points at the existing manual
meanwhile.

### Appendix A1 — How `017` was built

Chain table with MIDI channels, insert order as measured on the wire, dry/wet
values, `build-techno-snapshot.py`, the mixer staging numbers with the
2.92-bus-peak reasoning, and the CC sequence that produced the factory state, so
the snapshot can be rebuilt from nothing.

### Appendix A2 — Touchscreen patch

The optional `multitouch.py` coordinate scaling, labelled for readers whose panel
resolution differs from Zynthian's configured display size.

---

## 5. The factory snapshot `017-generative-techno`

Built by driving the live rig (D10). 124 BPM. All channels 16 steps at `1/16`
unless stated.

| Ch | Name | Kind | State | Steps that fire |
|---|---|---|---|---|
| A | KICK | drum | HITS 4, ROTATE 0 | 0, 4, 8, 12 |
| B | SNAR | drum | HITS 2, ROTATE 4 | 4, 12 |
| C | CLAP | drum | HITS 3, ROTATE 3 | 3, 8, 13 |
| D | CHAT | drum | HITS 8, ROTATE 1 | 1, 3, 5, 7, 9, 11, 13, 15 |
| E | OHAT | **drum chain, voice behaviour** (SHIFT + GRID) | RANDOM 25, DENSITY 40 | register walks the kit's own note list |
| F | BASS | voice, JC303 | RANDOM 0 (`LOCK`), GATE 40, OCTAVE −1 | frozen line |
| G | LEAD | voice, Obxd | RANDOM 100, GATE 40, RANGE 2 | new phrase every wrap |
| H | PADS | voice, padthv1 | pattern **8 steps**, RANDOM 0 (`LOCK`), DENSITY 12, GATE 800 | one note, target step 0 |

Which step PADS sounds on is a property of the register, which is not settable from
the surface. Target is step 0, reached by mutating the register (RANDOM up for one
wrap, back to 0) and re-checking with `techno_lib.gate_mask()`. If it will not land
on step 0 within a few attempts, a later step is accepted and **recorded in the
appendix as such**, because `note_duration()` then clamps the note to
`steps - step` and it is shorter than the loop. The riff is never hand-edited to
force it.

Mixer: strips **0.19**, main **0.80**. Insert dry **0.0 dB**, insert wets
**−70 dB**. No channel muted, soloed, or player-owned.

Three constraints the content is built around, all read from the code rather than
assumed:

- **A voice's pattern length is not on the surface.** Encoder 1 `LENGTH` on a voice
  is the shift register's bits. PADS reaches 8 steps by switching to drum behaviour,
  setting LENGTH there (2 beats at `1/16`), and switching back — SP4 deliberately
  does not move `div` or `beats` on a kind switch.
- **`GATE_MAX = 800`, i.e. 8 steps**, and `note_duration()` clamps to
  `steps - step`. A note across a 16-step bar is therefore not expressible from the
  knob; on an 8-step pattern, GATE 800 at step 0 fills the loop exactly.
- **DENSITY is deterministic**, not probabilistic: `gate_mask()` sounds the N lowest
  gate values, `N = round(density × steps)`, ties by step index. DENSITY 12 on 8
  steps sounds exactly one step, and the mask is a function of the register, so it
  survives `LOCK`.

`017` ships marked **unverified by ear** until the owner signs it off at the panel.
No agent can verify audio.

---

## 6. Drift control

Three copies of the ctrldev driver will exist: the WSL `zynthian-ui` checkout where
it is developed and tested, the Pi where it runs, and this repo where it is
published.

- `~/zynth/zynthian-ui` on branch `vangelis` stays the **development** home. Tests
  run there; edits happen there.
- The new repo is a **release** target. `tools/sync-from-dev.sh` copies the three
  ctrldev files and the two test files in; `git diff` afterwards is the drift
  report. Publishing is deliberate, never automatic.
- The daemon is the exception: it moves *into* the new repo as its development home,
  because nothing else builds it.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| The SFZ drum pack may not be stock | Section 4 checks instead of claiming; section 5 states which channels fall silent without it |
| `017` cannot be verified by ear by any agent | Section 6's by-ear checklist is the owner's; the snapshot ships marked unverified |
| Three copies of the driver drift apart | `sync-from-dev.sh` plus `git diff`; development stays in `zynthian-ui` |
| The reader's Zynthian differs from the pinned version | Version stated in every section; the core change is a patcher against their file |
| GPL compliance on a public repo | GPL-3.0 licence, credits to Zynthian and `wrl/maschine.rs` in the README and in `daemon/`, original notices intact |
| Building Rust on a Pi is slow | Documented in minutes, with a warning not to interrupt it |
| A fresh install has something the author's rig lacks, or vice versa | Cannot be closed without a spare card (D12). `check-prereqs.sh` narrows it to a dependency list |

---

## 8. Out of scope

SP3's drum filter (shelved by the owner 2026-08-12) · SP6, SP7, SP8 · the Vangelis
beta train · playing technique beyond section 7's placeholder · any change to the
`zynth-docs` site other than deleting the superseded tutorial page.

---

## 9. Implementation phasing

This is more than one plan's worth of work, so it splits into three, in order. Each
is independently useful and independently verifiable.

| Phase | Contents | Done when |
|---|---|---|
| **P1 — the repo exists and installs** | Create the repo, vendor the daemon, copy ctrldev + tests + system + tools, `LICENSE`, `README`, `install.sh`, `check-prereqs.sh`, `sync-from-dev.sh` | A clone passes the unit tests; `check-prereqs.sh` runs green on the Pi |
| **P2 — the guide** | Sections 1-7, both appendices, the generator port, Pages enabled | Pages renders all nine pages with an intact sidebar |
| **P3 — cutover** | `017` verified by ear and committed; `zynth-docs` tutorial page, HTML and sidebar entry deleted and the site regenerated; `MaschineMK2_linux` pointed here | Success criteria 1-7 below all hold |

`017` itself is being built in parallel and is not on this critical path.

## 10. Success criteria

1. `gh repo view Witzman/Generative-Techno-ZynthianMaschine-MKII` resolves, public, GPL-3.0.
2. A clone contains everything needed to install the instrument on a running Zynthian, minus third-party plugin binaries and samples, which the preflight checks for.
3. `python3 -m unittest discover -s tests -q` passes in the clone, on a machine with no Pi.
4. GitHub Pages renders the seven sections and both appendices, sidebar intact.
5. `tools/check-prereqs.sh` on the author's Pi exits zero and names every dependency.
6. `017-generative-techno.zss` loads on the author's rig and plays the state in §5, confirmed by ear by the owner.
7. `zynth-docs` no longer contains `project-techno-machine.md`, its HTML, or its sidebar entry, and its regenerated site is committed.
