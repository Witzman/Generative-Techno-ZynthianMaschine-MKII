# Techno Machine — Pass Two Design

**Date:** 2026-08-11
**Status:** design agreed, implementation gated on G4
**Supersedes nothing.** Extends `2026-08-10-techno-machine-prototype-design.md`,
which describes the shipped prototype this builds on.

---

## 1. Context

The techno machine shipped 2026-08-11: five euclidean drum channels, three
Turing voices, sixteen post-fader inserts, three latched pages, played entirely
from the Maschine MK2. It survived a twenty-minute jam at 21.1% mean DSP load,
zero xruns, zero segfaults.

Pass two is the owner's own feature list, captured 2026-08-11 in one sitting and
then decomposed. This document specifies **SP1 only**. SP2–SP4 are named here so
the boundaries are explicit, and each gets its own spec cycle.

### Button naming — fixed for this project

The panel silkscreen, the daemon's token names and the driver's constants
disagree with each other. The owner's names are authoritative in all prose from
here on, and **the CCs below are measured** — gate G4, 2026-08-11, one press per
button. Two of them were wrong in this document as first written, because the
daemon's token names are attached to the **opposite** physical buttons from
what they suggest:

| Name | Panel location | Daemon token | CC |
|---|---|---|---|
| **DL / DR** | arrows beside the display | `page_left` / `page_right` | **47 / 48** |
| **ML / MR** | master section, beside the big encoder | `nav_left` / `nav_right` | 13 / 14 |
| **TL / TR** | transport, ◀STEP / STEP▶ | `step_left` / `step_right` | **5 / 6** |

Rule for all future docs: never name an arrow button without its section
prefix, and any table naming a button carries panel label, daemon token and CC,
because the three do not agree.

---

## 2. Decomposition

| Sub-project | Contents | Status |
|---|---|---|
| **SP1 — mode & page framework** | Daemon patch; five peer modes; DL/DR paging with per-(mode,kind) memory; preset stepping moved to ML/MR; the three encoder shapes; display columns, meters and page indicator; mixer, filter (voices), STEP swing/chance, ALL reverb/delay, CONTROL generated pages | **this spec** |
| **SP2 — live play and record** | Pads play live in every mode but STEP; scale run from root/scale; REC-held capture; nearest-step quantise; recording claims `writer_token` | own spec, next |
| **SP3 — drum filter** | One LV2 filter insert per drum chain, plugin chosen by G1-style load test, fall back to a shared drum bus | own spec; **blocked on the Pi being connected** |
| **SP4 — channel type switching** | SHIFT+GRID tells a group it is now a drum or a voice; per-kind state init; pattern ownership handoff between three writers | own spec |

Build order: **SP1 → SP2 → SP4**, with SP3 whenever the hardware returns. SP1
first because everything draws on it and it is mostly transposes of code that
already works; SP2 second because its target modes do not exist until SP1
ships; SP4 last because its three-writer ownership rule is defined by SP2.

---

## 3. The page model

### 3.1 Current state

`self.page` is a string in `{CONTROL, STEP, ALL}`. `tlib.columns(page, kind,
state)` turns it into eight columns and is the single tested place where column
names, values, greyed columns and pending brackets are decided.
`_encoder_column` looks up `COLUMN_VERBS[(self.page, kind)]` and resolves
`channel = self.group`.

### 3.2 Target state

Replace the string with a pair:

- **`self.mode`** — one of `CONTROL`, `STEP`, `ALL`, `MIXER`, `FILTER`
- **`self.page_idx[(mode, kind)]`** — the current index into that ring

A ring is a tuple of page descriptors:

```
PAGE_RINGS[(mode, kind)] = (descriptor, descriptor, …)
```

Each descriptor declares a **shape**:

| Shape | Meaning | Encoder *n* resolves to |
|---|---|---|
| `channel` | 8 verbs, one selected channel | `(verbs[n], self.group)` |
| `spread` | 1 verb, all 8 channels | `(verb, n)` |
| `global` | 8 verbs, no channel | `(verbs[n], None)` |

`channel` is today's CONTROL and STEP. `global` is today's ALL. `spread` is
new: it is what mixer mode, filter mode and STEP's swing/probability pages are.

This lands on an existing seam. `_verb(verb, channel, cc_num, cc_val)` already
takes the channel as an argument, and its docstring already anticipates the
spread shape ("VOLUME held is eight faders"). `_encoder_column` becomes a
three-way dispatch on shape. **No verb implementation changes.**

### 3.3 Page memory

`page_idx` is keyed on `(mode, kind)`, not on mode alone. Selecting a drum while
on a voice's CONTROL page 4 does not clamp and lose the voice's position; coming
back to the voice returns to page 4.

Keying is a property of the **ring**, not of the shapes inside it. A ring is
keyed on kind when its content differs by kind — CONTROL and STEP — and on mode
alone (`kind = None`) when it does not — MIXER, FILTER, ALL. STEP is keyed on
kind even though its pages 2 and 3 are `spread`, because its page 1 is
`channel`-shaped and differs by kind; a mixed ring takes the keying its page 1
requires. A ring keyed on kind therefore has one page index per kind, so the
drum ring and the voice ring remember their positions separately.

### 3.4 Page changes recentre the encoders

Every mode change and every page change runs `_recentre_encoders()` and clears
`enc_carry`. `_set_page` already does this for mode changes; omitting it on page
changes would leak a knob's accumulated fraction into a different parameter.

### 3.5 Snapshot state

`get_state` / `set_state` store `mode` plus the `page_idx` dict instead of the
`page` string, with the same guard as today: an unrecognised mode falls back to
`CONTROL`, an out-of-range page index clamps into its ring.

---

## 4. Ring contents

### 4.1 Fixed rings

**MIXER** — shape `spread`, no kind:

1. `level`
2. `reverb`
3. `delay`

All three verbs exist and work per channel today. This is purely a transpose.
Note that `reverb` and `delay` are per-channel insert wet levels, not bus sends;
`fx_handle(channel, which)` addresses them through the chain, and the driver's
own comment records that moving insert → bus later "changes one function". The
surface calls them sends; the topology is inserts. That is a deliberate,
recorded mismatch, not an oversight.

**FILTER** — shape `spread`, no kind:

1. `cutoff`
2. `reso`

Both exist for voices via `VOICE_CTRL_COLUMNS`. The five drum columns render
**greyed** — the same treatment drum cutoff already receives, for the same
measured reason (CC 74/71 are unipolar SoundFont modulators, kits ship wide open
at 13500 cents, LinuxSampler publishes no controllers at all). SP3 fills them.

**STEP**:

1. today's `channel`-shape row, unchanged
2. `swing` — shape `spread`
3. `chance` — shape `spread`

Both verbs already exist per channel. Page 3 is what puts **voice CHANCE back on
the surface**, which was already on the pass-two list. The dashed-tab indication
for a chance-0 channel keeps working unchanged: it reads the value, not the
page.

**ALL** — shape `global`, page 1:

`root`, `scale`, `bpm`, `master`, `revsize`, `revtype`, `dlytime`, `dlyfbk` —
all eight shipped globals, unchanged.

An earlier draft of this section moved the four FX globals onto the generated
pages and left four free slots here. That would be a regression: `dlytime` is a
musical division resolved against live tempo by `_push_delay_time`, and
`revtype` is an index into the plugin's 43 rooms with its own no-scaling
special case in `_set_ganged`. Neither is a raw plugin port and neither
survives being generated. The generated pages expose the ports that have **no**
hand-written home, which is why the ring builder takes an `exclude` set.

### 4.2 Generated rings

Three rings are built at runtime from the chain's own plugins rather than
tabulated here:

- **CONTROL pages 2+** — read the voice processor's `controllers_dict`, drop the
  symbols already on page 1, chunk the remainder eight at a time.
- **ALL page 2** — chunk `fx_handle(channel, "reverb").controllers_dict`, pushed
  through the existing `_set_ganged`, which already writes one value to all
  sixteen inserts.
- **ALL page 3** — the same for `delay`.

A drum channel running LinuxSampler yields no controllers, so its CONTROL ring
stays length 1 and DL/DR do nothing there. That is honest rather than a bug.

**Why generated, not tabulated.** The requirement is "as much parameter control
as possible", and JC303's, Obxd's and TAP Reverberator's port lists cannot be
enumerated with the Pi offline. A generated ring needs no such list, survives an
engine change, and makes the requirement literally true. The cost is that page
count varies by engine and columns carry whatever the plugin calls its ports.

**Port filter.** The ring builder accepts numeric controllers only, skips
symbols already present on page 1, and truncates names to the column width.
Toggles, enums and unnamed ports are excluded. This is a pure function and is
unit tested against a fake `controllers_dict`.

**Cache discipline.** Generated rings are cached per channel and invalidated on
preset change, kit change and snapshot load. Reading `controllers_dict` is
cheap, but nothing in the ring path may trigger a preset or engine load: that
runs on `midi_event`, which holds `self.lock` for the whole event, and an engine
load blocks on a socket for seconds — it froze the entire instrument once and
needed a restart.

---

## 5. Buttons, LEDs, daemon

### 5.1 Daemon patch

`MaschineMK2_linux`, `src/main.rs`: three new arms in the RPN7 match — **SHIFT
49, SWING 50, VOLUME 51**. Roughly ten lines.

SHIFT keeps its existing internal modifier behaviour (`maschine.set_mod`) **and**
emits; the modifier is live and gates the daemon's own PAD MODE and one encoder,
so removing it breaks the daemon.

Deployment: `git bundle` on WSL, `git fetch` on the Pi — the Pi has no GitHub
auth, and a bare `git reset --hard origin/main` there once rewound the tree
because the fetch had silently failed. Check fetch exit status. Afterwards,
re-set `"external_pad_leds": true` in the daemon's `maschine.json`; it is not in
git on the Pi and a reset wipes it.

SWING is patched but unused in SP1. SHIFT is patched in SP1 because the rebuild
is here; its first consumer is SP4. Patching both now means SP4 needs no second
trip to the Pi.

### 5.2 Bindings

| Control | CC | Action | Change |
|---|---|---|---|
| VOLUME | 51 | mode → MIXER | new, needs patch |
| AUTO | 37 | mode → FILTER | new, already emits |
| CONTROL / STEP / ALL | 11 / 32 / 38 | mode | unchanged |
| DL / DR | **47 / 48** | page − / + in the current ring, wrapping | **repurposed** |
| ML / MR | 13 / 14 | previous / next sound | **moved off DL/DR** |

Five modes, mutually exclusive, one variable. The existing `_set_page` rule —
pressing the lit mode returns to CONTROL, pressing CONTROL while lit does
nothing — extends to all five unchanged, which gives VOLUME and AUTO their
"press again to exit" behaviour with no special case.

### 5.3 LEDs

`_render_pages` asserts exactly one of three lit today, derived from
`self.page`. It becomes exactly one of five, with `"volume"` and `"auto"` added
to `PAGE_LED_NAMES`. The daemon accepts button LED names over OSC regardless of
whether it emits that button's CC, so the LED half needs no patch.

### 5.4 Deliberately unbound

TL/TR (**5/6 — free surface, and fully emitted**; the claim that the daemon
swallowed them was retracted at G4), MUTE (33, free and emitting), SWING (50,
patched but unused), SHIFT (49, patched for SP4), and the **big encoder**
(turn 15, press 12), which G4 also measured and nothing uses.

---

## 6. Display

Layout unchanged, parts repurposed. `_columns()` keeps returning `(name, value,
bar kind, fraction)` tuples; `tlib.columns()` stays the single place deciding
content and takes a page descriptor instead of a page string.

Per shape: `channel` and `global` render as today. `spread` labels each column
with the channel letter and its sound name; the value is that channel's value of
the one verb.

Two additions:

- **Page indicator** in the dotted rule — mode name and position, e.g.
  `MIXER 2/3` — so a ring whose length is otherwise invisible becomes legible.
- **Meters** in MIXER's `level` page: the indicator bar shows level from
  `update_dpm_states` instead of fader position, gated on `enable_dpm`. If G4
  finds those symbols absent on the Pi's older `libzynmixer`, the bar falls back
  to fader position and nothing else changes.

Repaint stays on the existing 100 ms display timer. Meters will look coarse.
Redrawing faster starves the input reader and trips the hidraw watchdog; this is
not negotiable for a meter.

**Meter quantisation.** `_render_display` sends a screen only when its content
changed. Live meters change every frame, so mixer mode would push ~50 OSC
packets per screen per 100 ms indefinitely. The meter fraction is therefore
quantised to the bar's actual pixel resolution **before** the change
comparison, so a steady signal stops repainting.

---

## 7. Gates

### G4 — surface audit. Blocks SP1 implementation.

Every CC in section 5 currently comes from reading the daemon's Rust and the
driver's constants. That is good evidence, not hardware evidence. With the Pi
connected:

1. `jack_midi_dump` on `a2j:…Pads MIDI` while pressing, one at a time: DL, DR,
   ML, MR, TL, TR, AUTO, MUTE, GRID, SELECT, VIEW, PAD MODE, NAVIGATE, NAV.
   Record the CC for each and confirm each sends on **press and release**. This
   also settles which physical pair emits 5/6 — CLAUDE.md and the driver's
   constant name disagree about whether that pair is DL/DR or TL/TR.
2. Confirm AUTO 37 reaches the driver. (G4 result: it does.)
3. After the daemon patch: confirm SHIFT 49, SWING 50 and VOLUME 51 emit, **and**
   that PAD MODE still behaves — SHIFT is a live internal modifier and the patch
   must not disturb it.
4. `nm -D --defined-only` on the Pi's `libzynmixer.so` for `updateDpmStates` and
   `enableDpm`, and on `libzynseq.so` for `addNote`'s arity. The Pi's build is
   older than the WSL checkout and this has already broken three times.

### G5 — jam test. After implementation.

The same measurements the twenty-minute jam took: JACK DSP load mean and p95,
xrun count, segfault and traceback count, memory over twenty minutes, watchdog
reopen cadence against the ~8 s healthy baseline. Plus a mixer-mode-specific
check that the meter quantisation actually stops the repaint storm.

---

## 8. Testing

Everything that can be pure, is. Unit tested on WSL with no hardware, in the
style of the existing 118 tests:

- `PAGE_RINGS` structure and shape dispatch
- `page_idx` memory across mode and kind changes, and clamping into short rings
- `columns()` for each of the three shapes
- ring generation from a fake `controllers_dict`, including the port filter,
  the page-1 exclusion and name truncation
- meter fraction quantisation — that a steady value produces no repaint

Hardware verification is G4 before and G5 after.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| Generated rings produce junk columns (toggles, enums, unnameable ports) | Port filter, numeric only; name truncation; unit tested against a fake controller dict |
| Ring generation touches the MIDI thread and blocks on an engine load | Rings cached per channel, invalidated on preset/kit/snapshot change; nothing in the ring path may load a preset |
| Integer truncation — `_set_value()` truncates, so fractional steps vanish | Spread pages step in whole controller units with the remainder carried, via the existing `_enc_steps` |
| Display packet storm in MIXER from live meters | Quantise the meter fraction to the bar's pixel resolution before the change comparison |
| DPM symbols missing on the Pi's older `libzynmixer` | G4 checks; degrades to fader position |
| CC numbers wrong — sourced from code, not hardware | G4 blocks implementation until observed |

---

## 10. Non-goals

Explicitly not built in SP1, though the design stays compatible with all of
them:

- SP2's live play and record
- SP3's drum filter
- SP4's channel type switching
- **Channel-based pad behaviour** — pads as a per-channel property (sequenced
  vs played) rather than a per-mode one. Considered and deferred to pass three:
  it is a third flag on a surface about to grow two, and the mode rule should be
  played for a jam or two first to see whether reaching for STEP annoys.
- TL/TR and MUTE bindings
- Converting per-channel FX inserts into real send/return buses

---

## 11. Open item carried from the prototype

The **two SOLO gestures** remain the only shipped surface behaviour never
verified on hardware. `zynmixer.toggle_solo` is **additive**, not exclusive,
with a special case at `MAX_NUM_CHANNELS - 1` that clears every solo. Fold this
into G4 while the Pi is connected — it costs one press and settles the oldest
unverified claim in the project.
