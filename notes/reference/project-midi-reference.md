# MIDI Reference

**Purpose:** Complete MIDI map for this hardware rig — device capabilities, active assignments, conflicts, and Zynthian feature triggers. Update this page whenever a tutorial is verified or configuration changes deliberately.

**Hardware:** Maschine MK2 (via MaschineMK2_linux daemon) · E-MU Xboard 25 · SMC-PAD (**NiFox Koala preset — pads on ch 10, see Conflict 11**)
**Access:** SSH · Webconf

---

## Section 1 — Device Capabilities

### Maschine MK2 (MaschineMK2_linux daemon)

The Maschine MK2's native USB MIDI port sends no pad data without NI software. All pad MIDI comes from the `MaschineMK2_linux` daemon, which reads HID and outputs ALSA MIDI via the `Pads MIDI` port on **channel 1** (normal mode) and **channel 2** (sequencer mode).

| Control | MIDI message | Ch | Range / values |
|---|---|---|---|
| 16 pads — normal mode | Note On / Note Off | 1 | base + offset (see layout below), velocity from pressure |
| 16 pads — sequencer mode | Note On / Note Off | 2 | stored per step |
| 8 encoders | **CC** | 1 | CC 16–23 (configurable via `maschine.json` or web editor), absolute 0–127 |
| ~30 transport / function buttons | **CC** | 1 | CC 1–14 and 24–48 (see table below), value 127 = press, 0 = release |
| Group buttons A–H — pad mode | *(none — internal state only)* | — | sets note base: A=24 B=36 C=48 D=60 E=72 F=84 G=96 H=108 |
| Group buttons A–H — sequencer mode | *(none — internal state only)* | — | switches active sequencer page (1–8) |
| `MIDI Control` ALSA input port | accepts NoteOn/Off 0–15, Clock, Start, Stop | — | NoteOn 0–15 → pad LED color/brightness; Clock/Start/Stop → forwarded to `Pads MIDI` output |


**Pad note layout** — offsets added to current note base. Pad rows top → bottom, left → right:

```
Row 0 (top): +12  +13  +14  +15
Row 1:        +8   +9  +10  +11
Row 2:        +4   +5   +6   +7
Row 3 (bot):  +0   +1   +2   +3
```

With Group D active (base 60 = C4):

```
Row 0: C4  C#4  D4  D#4   (MIDI 60–63)
Row 1: G#3  A3  A#3  B3   (MIDI 56–59)
Row 2: E3   F3  F#3  G3   (MIDI 52–55)
Row 3: C3  C#3  D3  D#3   (MIDI 48–51)
```

**Transport / function button CC map (Ch 1, value 127 = press, 0 = release):**

| Button | CC | Button | CC |
|---|---|---|---|
| Play | 1 | Main | 24 |
| Stop (Erase) | 2 | Scene | 25 |
| Rec | 3 | Pattern | 26 |
| Grid | 4 | Pad Mode | 27 |
| Step Left | 5 | View | 28 |
| Step Right | 6 | Duplicate | 29 |
| Restart | 7 | Select | 30 |
| Browse | 8 | Solo | 31 |
| Sampling | 9 | Step | 32 |
| Note Repeat | 10 | Mute | 33 |
| Control | 11 | Navigate | 34 |
| Nav | 12 | Tempo | 35 |
| Nav Left | 13 | Enter | 36 |
| Nav Right | 14 | Auto | 37 |
| — | — | All | 38 |
| — | — | F1–F8 | 39–46 |
| — | — | Page Right | 47 |
| — | — | Page Left | 48 |

**OSC interface:** daemon listens on `127.0.0.1:42434`, sends to `42435`. Supports remote LED control (`/maschine/button/<name>`, `/maschine/pad`) and setting MIDI note base (`/maschine/midi_note_base`).

**MIDI IN (`MIDI Control` ALSA input port):** Connect any MIDI source to drive pad LEDs and sync the sequencer. NoteOn note 0 = bottom-left pad (offset 0), note 15 = top-right pad (offset 15). Velocity maps to LED brightness. Clock/Start/Stop messages are forwarded to `Pads MIDI` output and can lock the built-in step sequencer. Connect with `aconnect <source>:<port> <maschine-client>:1`.

---

### Maschine MK2 — control surface and UI grammar

The full physical inventory, and what the device is *capable* of — established from
the Controller Editor layout and from how NI's own Windows software drives it.
Useful when deciding what a Zynthian driver could do, as opposed to what it does
today.

**Controls**

| Group | Controls |
|---|---|
| Pads | 16, velocity + aftertouch, with pad **pages** |
| Encoders | 8 small, **smooth and endless** (no detents), with **knob pages** |
| Big encoder | 1, **detented** (one click = one step) **and pushable** |
| Above the screens | F1–F8, each with a white LED |
| Screens | 2 × 255x64 monochrome |
| Groups | A–H, full RGB LEDs |
| Transport | Restart, ◀, ▶, Grid, Play, Rec, Erase, Shift |
| Master | Volume, Swing, Tempo, ◀, ▶, Enter, Note Repeat |
| Pads section | Scene, Pattern, Pad Mode, Navigate, Duplicate, Select, Solo, Mute |
| Left column | Control, Step, Browse, Sampling, All, Auto Write |

Roughly 20 of those buttons carry white LEDs and are unused by our rig.

**Naming used in this project** — the MK2 has three separate ◀ ▶ pairs, so they
need distinct names:

| Name | Where |
|---|---|
| **TL / TR** | the transport section's arrows |
| **ML / MR** | the master section's arrows |
| **EL / ER** | SHIFT+Browse / SHIFT+Sampling — "encoder page left/right" in NI's software |

> **[low] Which physical pair maps to the daemon's `step_left`/`step_right`
> (CC 5/6) versus `nav_left`/`nav_right` (CC 13/14) is not confirmed.** The rig
> binds CC 5/6 for sample switching and they are described as "the arrows beside
> the display". Dump the port and press each pair before binding another.

**The UI grammar NI's Windows software uses.** None of this is done by the
device — it is dumb hardware with buttons, LEDs and two screens, and the host
draws everything. So it is all reproducible by a Zynthian driver given the same
primitives. Shift is emitted to the host (our daemon already tracks it as a
modifier), so even Shift combinations are ours to use.

- **Paged controls.** EL/ER page the 8 encoders **and** the 8 F buttons together,
  so one page is 16 controls, with the screens labelling both.
- **Held-button modal screens.** Holding a button turns the screens into a
  temporary context: hold Mute and the screens show instrument names under the F
  buttons while F1–F8 become channel mutes. Momentary — releasing restores the
  previous view.
- **Select → dial → confirm.** A button opens a screen of fields; ML/MR move the
  selection; the big detented encoder changes the selected value; its push
  confirms. Whether a value applies live while dialling or only on confirm is a
  design choice, not a device constraint — both are possible.
- **Control as escape** out of any menu.
- **Capacitive touch on the encoder row.** The device senses a finger resting on
  the encoders *before* anything is turned. It is a single global signal, not per
  knob, and its only job is contextual display: touching the row snaps the screens
  back to showing what the encoders and F buttons currently do. It exists so you
  can leave a menu without nudging a value.

#### Input report 0x01 decoded against cabl — 2026-08-10

`shaduzlabs/cabl` (`src/devices/ni/MaschineMK2.cpp`) is a known-working MK2 driver and
settles the layout of the button/encoder report. cabl indexes the RAW report (ID at byte
0); our daemon strips the ID, so **our index = cabl's raw index - 1**.

| raw byte | our row | Contents (cabl's own enum order) |
|---|---|---|
| 1 | 0 | DisplayButton1-8 → F1-F8 |
| 2 | 1 | Control · Step · Browse · Sampling · **BrowseLeft · BrowseRight** · All · AutoWrite |
| 3 | 2 | Volume · Swing · Tempo · **MasterLeft · MasterRight** · Enter · NoteRepeat · **Main** |
| 4 | 3 | Group A-H |
| 5 | 4 | Restart · **TransportLeft · TransportRight** · Grid · Play · Rec · Erase · Shift |
| 6 | 5 | Scene · Pattern · PadMode · Navigate · Duplicate · Select · Solo · Mute |
| 7 | 6 | **NotUsed1-4** — our `R1-R8` are phantom names for unused bits |
| 8 | 7 | **THE BIG ENCODER'S VALUE** — our `A1-A8` are phantom names for a counter |
| 9-24 | 8-23 | the 8 small encoders, 16-bit little-endian pairs (low byte first) |

This resolves the three-arrow-pairs question definitively:

| Project name | cabl name | our daemon | CC |
|---|---|---|---|
| **TL / TR** (transport) | TransportLeft/Right | `step_left`/`step_right` | **5 / 6** |
| **ML / MR** (master) | MasterLeft/Right | `nav_left`/`nav_right` | **13 / 14** |
| **EL / ER** (left column) | BrowseLeft/Right | `page_left`/`page_right` | **47 / 48 — swallowed by the daemon** |

So the rig's sample-switch arrows are the TRANSPORT pair, and the left-column pair exists
and is reachable as soon as the daemon stops consuming it for its own page indicators.

**The big encoder is in the stream and always has been.** Raw byte 8 is a 4-bit wrapping
counter (0x00-0x0F, hence detented with 16 positions). Our `read_buttons` treats that byte
as eight button bits named `A1-A8`, so **turning the big encoder currently fires spurious
button events** — harmless only because nothing binds them. Emitting it is a small change
to `read_buttons`, not a reverse-engineering exercise.

**Our small-encoder parsing agrees with cabl:** value = low | high<<8, which is what
`normalize_encoder`'s `raw/4 + state*64` approximates.

**The big encoder's PUSH is unresolved.** It is not a separate entry in cabl's 48-button
enum; `Main` (raw byte 3, bit 7 — our `Nav`) is the likeliest candidate. Test by pushing
the encoder and watching that bit.

**Encoder capacitive touch: UNRESOLVED, with a strong hypothesis and a named test.**
cabl implements no touch for the MK2 and declares `kMASMK2_nEncoders = 9` (8 small + 1
big), but that is weak evidence — cabl's MK2 support is admittedly partial (its
`processPads` is a bare `//!\todo`). The owner is confident the hardware has it and that
NI's Windows driver uses it, which is the better evidence.

The hypothesis: **raw byte 7** — the byte cabl calls `NotUsed1-4` and our daemon calls
`R1-R8` — carries eight bits for eight encoders. Those bits already reach our button
decoder, so touch would be arriving today and being silently dropped, exactly as the big
encoder's counter was.

The test: print raw byte 7 on change only, touch each encoder without turning it, and see
which bit sets. **Print on change only** — at ~750 reports/s an unthrottled print starves
the input reader and trips the hidraw watchdog, which looks precisely like "the encoder
killed the daemon".

Local clone for reference: `~/zynth/cabl`.

**What our daemon exposes today**

| Capability | State |
|---|---|
| Buttons, pads, 8 encoders, LEDs, both screens | working |
| Shift | received, tracked as a modifier |
| Encoder **touch** | **not implemented.** `read_buttons` consumes 24 bytes — 8 of button bits, the rest encoder counters. Touch is either in a byte we ignore or in a report ID we drop unparsed. Unknown whether it is in the stream at all |
| Big encoder | **unverified.** `roller_state` is sized 9, so it is plausibly roller index 8 |
| Big encoder push | **unverified.** The button enum has an `Encoder` entry that is probably it |
| Page ◀▶ (CC 47/48) | **swallowed by the daemon** for its own page indicators — never emitted |

---

### Maschine MK2 — factory MIDI mode (Native Instruments Controller Editor)

**This map is not what the Pi sees.** It documents what the MK2 firmware emits in NI's stand-alone MIDI mode, configured by Controller Editor on Windows/macOS. The `MaschineMK2_linux` daemon bypasses MIDI mode entirely and reads raw USB HID, so the daemon's own map (above) is what applies on Zynthian. This section exists as a compatibility reference — matching it would make the daemon drop-in compatible with DAW templates written for a stock MK2.

Source: `~/zynth/CE/` — Controller Editor 2.7.6 Windows install. `base.ncc` and `Configuration.ncc` are **plain XML** (`<ni-controller-midi-map version="3">`), readable and editable on Linux without running the app. Extract the MK2 block by slicing between `<controller type="Maschine Controller MK2">` and the next `<controller type=`.

**Pads** — channel 1, Note On/Off, `gate` behaviour, velocity curve 3. Eight pad pages, selected on the device:

| Page | Notes | Page | Notes |
|---|---|---|---|
| A | 12–27 | E | 60–75 |
| B | 24–39 | F | 72–87 |
| C | 36–51 | G | 84–99 |
| D | 48–63 | H | 96–111 |

Page stride is 12 semitones but each page spans 16 notes — **adjacent pages overlap by 4 notes**. This is NI's factory default, not an error in transcription. The Linux daemon uses a 12-semitone base per group button (A=24 … H=108) with the same consequence.

Each pad additionally exposes a `Pressure1..16` control (subtype `pressure`) — assignable independently of the trigger.

**Encoders and display buttons** — channel 1, two switchable pages:

| Control | Page 1 | Page 2 |
|---|---|---|
| Knob 1–8 | CC 14–21 | CC 22–29 |
| Button F1–F8 | CC 46–53 | CC 54–61 |

**Transport / mode buttons** — channel 1, CC, toggle, fires on press:

| Button | CC | Button | CC | Button | CC |
|---|---|---|---|---|---|
| Tempo | 3 | Sampling | 88 | StepR | 106 |
| Volume | 7 | All | 89 | Grid | 107 |
| Swing | 9 | AutoWrite | 90 | Play | 108 |
| Group A–D | 80–83 | Group E–H | 91–94 | Rec | 109 |
| Control | 85 | MasterL | 98 | Erase | 110 |
| Step | 86 | MasterR | 99 | NoteRep | 111 |
| Browse | 87 | Enter | 100 | Scene | 112 |
| | | Dial (wheel turn) | 101 | Pattern | 113 |
| | | Push (wheel click) | 102 | PadMode | 114 |
| | | Restart | 104 | Navigate | 115 |
| | | StepL | 105 | Duplicate | 116 |
| | | | | Select | 117 |
| | | | | Solo | 118 |
| | | | | Mute | 119 |

37 buttons plus the wheel. Controller Editor exposes no **Shift** — the firmware consumes it as the page/template modifier — and no **Main** or **View**. It exposes no display access at all, confirming the LCD is USB-only with no MIDI path.

**LED colour model — HSB across three channels.** Every RGB LED is addressed as three separate targets that share one note (pads) or CC (group buttons) and differ only by channel:

| Suffix | Channel | Component |
|---|---|---|
| `…H` | 0 | Hue |
| `…S` | 1 | Saturation |
| `…B` | 2 | Brightness |

Pad 1's LED is `Pad1H` note 12 ch 0, `Pad1S` note 12 ch 1, `Pad1B` note 12 ch 2. Group button A is `GroupAH/AS/AB` on CC 80, channels 0/1/2.

NI's own RGB→HSB conversion is readable in `CE/Template Support Files/Ableton Live 9/Maschine_Mk2/MIDI_Map.py` (`toHSB`, plaintext). It returns a pair of 7-bit HSB triplets — lit and unlit state:

```python
hue = <0..255 from standard RGB hexcone>
on  = (hue/2, min(sat/2 + 20, 127), bright/2)
off = (hue/2, min(sat/2 + 15, 127), max(bright/2 - 90, 5))
```

The Linux daemon writes raw RGB bytes over USB instead (`src/devices/mk2/mikro.rs:453`), which is correct for the HID path. Relevant only if the daemon's `MIDI Control` input is ever extended to accept NI-style colour: it would need HSB triplets on channels 1/2/3, not a single RGB value.

---

### E-MU Xboard 25

| Control | MIDI message | Ch | Range | Notes |
|---|---|---|---|---|
| 25 keys | Note On / Note Off | patch ch | full range ± 4 oct transpose | velocity-sensitive |
| Channel aftertouch | Channel Pressure | patch ch | 0–127 | configurable on/off |
| Pitch wheel | Pitch Bend | patch ch | ±8192 | springs to center |
| Mod wheel | CC 1 | patch ch | 0–127 | CC number reassignable |
| 16 CC knobs | CC | per-knob ch | 0–127 | **any CC 0–127, any channel, per patch** |
| Footswitch | CC 64 (sustain) | patch ch | 0 / 127 | or continuous pedal mode |
| Data slider | Universal Real Time SysEx | all | master volume | not standard CC |
| Snapshot button | bulk CC send | — | stored knob positions | sends all 16 knobs + wheels at once |
| Program Change | PC + Bank Select (CC 0 + CC 32) | per ch | 0–127 | per patch, per channel |
| Panic (Oct↑ + Oct↓ simultaneously) | All Notes Off + All Sounds Off + CC 64=0 | ch 1–16 | — | clears stuck notes |
| 4 Zones | keys split across 4 MIDI channels | 4 ch | key + velocity range per zone | requires Xboard Control software |

> **[low] Factory CC defaults for the 16 knobs are not documented in the text manual.** Verify with `amidi -d -p hw:X,0,0` (replace X with Xboard card number from `aconnect -l`) before assigning any knob. Until verified, treat CC 1, 7, 10, 11, 16–19, 30, 64, 71, 74 as potentially occupied.

---

### SMC-PAD (Preset 1 — Performance preset) — SUPERSEDED 2026-08-06

> **The NiFox Koala preset pack is now flashed to the device.** Pads send on **channel 10**, not channel 6. The table below describes the factory preset and no longer matches the hardware. It is kept because every current tutorial and the live `default.sh` still assume it. See "NiFox preset pack" below for the active map and Conflict 11 for the fix.

Select Preset 1: **Shift + Pad 1**.

All data below verified from tutorial testing, ctrldev driver source code, and live MIDI capture on Pi (2026-06-05). **Pad channel is 6, not 7** — confirmed from raw MIDI debug (`status 0x95` = Note-On ch6 1-indexed).

| Control | MIDI message | Ch | Value |
|---|---|---|---|
| Pad 1 (bottom-left) | Note 36 On/Off | **6** | velocity-sensitive + aftertouch |
| Pad 2 | Note 37 | **6** | — |
| Pad 3 | Note 38 | **6** | — |
| Pad 4 | Note 39 | **6** | — |
| Pad 5 | Note 40 | **6** | — |
| Pad 6 | Note 41 | **6** | — |
| Pad 7 | Note 42 | **6** | — |
| Pad 8 | Note 43 | **6** | — |
| Pad 9 | Note 44 | **6** | — |
| Pad 10 | Note 45 | **6** | — |
| Pad 11 | Note 46 | **6** | — |
| Pad 12 | Note 47 | **6** | — |
| Pad 13 | Note 48 | **6** | — |
| Pad 14 | Note 49 | **6** | — |
| Pad 15 | Note 50 | **6** | — |
| Pad 16 (top-right) | Note 51 | **6** | — |
| Knob 7 (top-left col) | CC 16 | ? | 0–127 absolute |
| Knob 5 | CC 17 | ? | 0–127 absolute |
| Knob 3 | CC 18 | ? | 0–127 absolute |
| Knob 1 (bottom-left col) | CC 30 | ? | 0–127 absolute |
| Knob 8 (top-right col) | CC 80 | ? | 0–127 absolute |
| Knob 6 | CC 81 | ? | 0–127 absolute |
| Knob 4 | CC 82 | ? | 0–127 absolute |
| Knob 2 (bottom-right col) | CC 31 | ? | 0–127 absolute |
| Transport Left | CC 25 | 1 | 127 on press, 0 on release |
| Transport Right | CC 26 | 1 | 127 on press, 0 on release |
| PLAY button | CC 27 | 1 | 127 on press, 0 on release — verified 2026-06-07 |
| STOP button | CC 28 | 1 | 127 on press, 0 on release — verified 2026-06-07 |
| REC button | CC 29 | 1 | 127 on press, 0 on release — verified 2026-06-07 |

> **[low] Encoder MIDI channel (marked ?) — verify with `amidi -d` capture.**

**ctrldev driver (`zynthian_ctrldev_sinco_smc_pad.py`) — active when SINCO IN 2 port has driver assigned:**

| Incoming | Action | Notes |
|---|---|---|
| CC 16 → | ZYNPOT_ABS 0 (top screen knob) | absolute position |
| CC 17 → | ZYNPOT_ABS 1 | — |
| CC 18 → | ZYNPOT_ABS 2 | — |
| CC 30 → | ZYNPOT_ABS 3 (bottom screen knob) | — |
| CC 25 (press=127) → | PROGRAM_CHANGE − on drum chain | drum chain = MIDI ch 6 (0-indexed=5) |
| CC 26 (press=127) → | PROGRAM_CHANGE + on drum chain | drum chain = MIDI ch 6 (0-indexed=5) |
| CC 27 (press=127) → | TOGGLE_MIDI_PLAY | Zynthian transport play/pause |
| CC 28 (press=127) → | STOP_MIDI_PLAY | Zynthian transport stop |
| CC 29 (press=127) → | TOGGLE_MIDI_RECORD | Zynthian transport record toggle |
| Pad notes 36–51 ch **6** | pass through to chains | no CUIA mapping — pure drum hits |

PAD BANK and KNOB BANK buttons switch to bank 2 assignments — not yet mapped.
Preset 2 (DAW): **Shift + Pad 2** — transport buttons send Mackie Control; use in DAW mode only.

---

### SMC-PAD — NiFox preset pack for Koala Sampler

`~/zynth/SMC Pad/` holds a third-party preset pack (NiFox) that reflashes the SMC-PAD for **Koala Sampler on iPad**. It is not a Zynthian configuration. **It is currently installed on the device** (confirmed 2026-08-06), so this — not the factory table above — is what the Pi receives.

| File | Role |
|---|---|
| `*.spc` × 5 | Device presets, flashed with `MidiSuite/MidiSuite.exe` (Windows) |
| `MIDI Map for Koala.json` | Koala-side import — **Settings → Extras → MIDI Map → Import** |
| `Tutorial + Cheat Sheet/` | Cheat sheets, bank layout images, demo video |

Presets: `1. NiFox Color+` · `1.2 Extra Color+` (banks C/D) · `2. NiFox FX+Control` · `3. DAW Control` · `EXTRA - YARG`.

#### Pad LEDs cannot be driven over MIDI — tested 2026-08-09

The SMC-PAD exposes two ALSA sequencer ports that accept input (`32:0 SINCO
SMC-PAD-Private`, `32:1 SINCO SMC-PAD-Master`), but **nothing sent to either of
them changes a pad's colour**. Tested on the hardware with the NiFox pack
installed:

| Sent | Result |
|---|---|
| NoteOn notes 36-51, velocity 127, **all 16 channels**, both ports | no response |
| Program Change 1-5 (would switch device preset), both ports | no response |
| Every CC 0-127 at value 127, channels 1 and 10, both ports | no response |

So pad colours are baked into the flashed `.spc` preset and are static at run
time. A Zynthian-side driver can read the pads but cannot light them, and
cannot switch the device's preset either.

**Note the trap:** `amidi -p hw:4,0,N` fails with "Device or resource busy"
because Zynthian holds the rawmidi device. It also fails *silently* if stderr
is discarded, which looks exactly like "the device ignored it". Send through
the sequencer instead — `aplaymidi -p 32:N file.mid`.

The only untested path is vendor SysEx, which is what `MidiSuite.exe` uses to
flash presets. Finding it needs a USB capture of that tool under Windows.

Map in `1. NiFox Color+`, from the Koala JSON:

| Control | MIDI message | Ch |
|---|---|---|
| 32 pads (banks A+B) | Notes 36–67 | **10** |
| 8 encoders, bank A | CC 30–37 — eq gain/freq, sampleStart, sampleLength, VOL, PITCH | 1 |
| 8 encoders, bank B | CC 38–48 — mixer vols, fx STUTTER/CUTTER/CRUSH/TALKBOX/FILTER/RING/COMB | 1 |
| Transport buttons | CC 25–29 — mute, solo, play, fxHold, rec | 1 |
| Seq / mixer buttons | Notes 111–126 | 1 |

Pad-to-note order is row-reversed relative to Zynthian's expectation: note 36 → Koala pad index 12.

`.spc` is a binary of fixed 22-byte records — byte 0 is the control type (`0x02` = CC, `0x09` = note), byte 2 the CC or note number. The CC numbers in the dump match the JSON exactly, so the file is decodable without MidiSuite if a Linux-side editor is ever needed. Pad records carry a `0x96` byte — Note-On status for channel 10 — corroborating the JSON channel.

**What survived the reflash, and what did not:**

| Element | Factory preset 1 | NiFox Color+ | Impact |
|---|---|---|---|
| Pad channel | 6 | **10** | breaks master channel, drum chain routing, `DRUM_CHAN` |
| Pad notes, bank A | 36–51 | **36–51 — unchanged** | all 16 TOGGLE_SEQ note mappings stay valid |
| Pad notes, bank B | — | 52–67 (new) | widens the overlap with Maschine pages C/D |
| Transport CC 25–29 ch 1 | Left/Right/Play/Stop/Rec | mute/solo/play/fxHold/rec | **same CC, same channel** — ctrldev transport unaffected |
| Encoder CCs | 16, 17, 18, 30, 80, 81, 82, 31 | 30–37 (bank A) | ctrldev `ZYNPOT_ABS` on CC 16/17/18 dead; only CC 30 survives |

> **[low] Which of the five presets occupies which device slot is unconfirmed**, as is whether the encoder CC channel really is 1. The table above assumes `1. NiFox Color+`. Verify on the Pi with `amidi -d -p hw:X,0,0`: hit pad 1 (expect `99 24 vv`), then turn each encoder.

The seq/mixer note mappings at notes 111–126 ch 1 in the Koala JSON do not correspond to any control identified on the SMC-PAD so far — possibly a different preset in the pack, possibly Shift-layer output. Unresolved. The JSON also assigns `seq 3` to note 127 on ch 10 while `seq 0–2` are ch 1 — almost certainly an export bug in the pack.

---

## Section 2 — Master MIDI Assignment Matrix

### Global settings (live — `default.sh`)

| Setting | Value | Effect |
|---|---|---|
| Master MIDI channel | **6** | Notes on ch 6 trigger CUIA master key actions |
| Master key actions | *none* | Cleared 2026-06-07 — pads are drums, not launcher triggers |
| MIDI filter rules | *none* | No RPN→CC remapping, no channel redirects |
| SINGLE_ACTIVE_CHANNEL | **OFF** | MIDI routes per channel — each chain responds to its assigned channel only |
| PROG_CHANGE_ZS3 | **ON** | Program Change recalls ZS3 subsnapshots |
| BLE MIDI | enabled | SMC-PAD BLE broken on kernel 6.12 — use USB |

### JACK device routing (live)

| ZynMidiRouter port | Physical device |
|---|---|
| dev0_in | Maschine MK2 native USB MIDI *(no pad data — needs daemon)* |
| dev1_in | E-MU Xboard 25 |
| dev2_in | SINCO SMC-PAD Private port |
| dev3_in | SINCO SMC-PAD Master port (pads + CCs) **and** Maschine daemon `Pads MIDI` (fan-in) |
| dev4_in | SINCO SMC-PAD port 2 |
| dev5_in | ttymidi (DIN-5) |

### Assignment matrix

Status tags: `[verified]` = Pi-tested · `[draft]` = written, not yet tested · `[low]` = not yet verified · `[blocked]` = depends on unresolved issue · `passive` = standard MIDI, no explicit assignment needed

| Device | Control | Ch | Message | Zynthian target | Tutorial | Status |
|---|---|---|---|---|---|---|
| Maschine MK2 | Pads — Group C (default) | 1 | Note = 48 + `pad_notes[pad]` | active chain | Maschine MK2 P1 | `[verified]` |
| Maschine MK2 | Pads — Group D | 1 | Note 60–75 | active chain | Step Seq P2 | `[draft]` |
| Maschine MK2 | Sequencer output | 2 | Note (any) | chain on ch 2 | Step Seq P1 | `[draft]` |
| Maschine MK2 | 8 Encoders | 1 | CC 16–23 (`encoder_ccs` in `maschine.json`) | **unassigned** | Maschine MK2 P2 | `[verified]` |
| Maschine MK2 | Play / Erase / Rec / Grid / Restart | 1 | CC 1 / 2 / 3 / 4 / 7 (127 press, 0 release) | **unassigned** | Drum Rig | `[verified]` |
| Maschine MK2 | F1–F8 (above displays) | 1 | CC 39–46 (127 press, 0 release) | **unassigned** | Drum Rig | `[verified]` |
| Maschine MK2 | Group A–H | — | **nothing** — sets internal note base only | — | Drum Rig | `[verified]` |
| Maschine MK2 | MIDI Control IN → pad LEDs | — | NoteOn 0–15 | pad LED color/brightness | Maschine MK2 P4 | `[draft]` |
| Xboard 25 | Keys | 1 | Note 0–127 | active chain | MIDI Channel Routing | `[draft]` |
| Xboard 25 | 16 CC knobs | 1 | CC [unknown] | **unassigned** | Xboard CC Knob Map | `[draft]` |
| Xboard 25 | Mod wheel | 1 | CC 1 | active chain engine | — | passive |
| Xboard 25 | Pitch wheel | 1 | Pitch Bend | active chain engine | — | passive |
| Xboard 25 | Aftertouch | 1 | Channel Pressure | active chain engine | — | passive |
| SMC-PAD | Pads 1–12 | **6** | Note 36–47 | **unassigned** | SMC-PAD Launcher P3 | `[draft]` |
| SMC-PAD | Pad 13 (note 48) | **6** | Note 48 | TOGGLE_SEQ 0,0 | SMC-PAD Launcher P3 | partial `[low]` |
| SMC-PAD | Pads 14–16 (notes 49–51) | **6** | Note 49–51 | **unassigned** | SMC-PAD Launcher P3 | `[draft]` |
| SMC-PAD | Encoders left col | ? | CC 16/17/18/30 | Screen knobs 1–4 (ZYNPOT_ABS) | SMC-PAD Launcher P4 | `[verified]` |
| SMC-PAD | Encoders right col | ? | CC 80/81/82/31 | **unassigned** | — | — |
| SMC-PAD | Transport Left | 1 | CC 25 | PROGRAM_CHANGE − (drum ch 6) | SMC-PAD Drum Computer | `[low]` |
| SMC-PAD | Transport Right | 1 | CC 26 | PROGRAM_CHANGE + (drum ch 6) | SMC-PAD Drum Computer | `[low]` |
| SMC-PAD | Transport PLAY | 1 | CC 27 | TOGGLE_PLAY (ctrldev) | rig-v1 | `[verified]` |
| SMC-PAD | Transport STOP | 1 | CC 28 | STOP (ctrldev) | rig-v1 | `[verified]` |
| SMC-PAD | Transport REC | 1 | CC 29 | TOGGLE_RECORD (ctrldev) | rig-v1 | `[verified]` |

### Currently loaded chains

From `dub-techno-p1` snapshot (bank 000):

| Chain | MIDI ch | Engine |
|---|---|---|
| 1 | 1 | FluidSynth — drums |
| 2 | 2 | ZynAddSubFX — bass |

---

## Section 3 — Conflicts and Design Decisions

### Conflict 1 — Maschine + Xboard both on MIDI ch 1

Both devices send notes on ch 1. With SINGLE_ACTIVE_CHANNEL=ON, both drive whichever chain is currently selected. Can be intentional layering or accidental doubling.

**Resolution:** Set Xboard to ch 3 or ch 4 when used alongside Maschine. Document channel assignment in each tutorial that uses both simultaneously. *(Not yet implemented — pending MIDI Channel Routing tutorial.)*

---

### Conflict 2 — Maschine note range overlaps SMC-PAD pads

| Group | Note base | Notes sent | Overlap with SMC-PAD (36–51) |
|---|---|---|---|
| A | 24 | 24–39 | partial — notes 36–39 (pads 1–4) |
| B | 36 | 36–51 | **full overlap** |
| C | 48 | 48–63 | partial — notes 48–51 (pads 13–16) |
| D | 60 | 60–75 | none |
| E+ | 72+ | 72–87+ | none |

**Resolution:** Use Group D or higher when SMC-PAD launcher is active. Note in each affected tutorial.

---

### Conflict 3 — Master channel 6 = SMC-PAD channel — RESOLVED (2026-06-07)

When master channel = 6, `zynmidirouter.c` intercepts all ch 6 events and routes them to the CUIA queue — bypassing chain routing entirely. The drum chain (also ch 6 in rig-v1) received no note events.

**Resolution:** Master channel is now **disabled** (`ZYNTHIAN_MIDI_MASTER_CHANNEL=0`) in rig-v1. Ch 6 events reach the drum chain directly. TOGGLE_SEQ launcher functionality requires a separate snapshot where master channel = 6 and no instrument chain is on ch 6.

---

### Conflict 4 — Only 1 of 16 TOGGLE_SEQ mappings active

`default.sh` MASTER_NOTE_CUIA contains only `48: TOGGLE_SEQ 0,0`. SMC-PAD Launcher P3 planned:

```
36: TOGGLE_SEQ 0,0   37: TOGGLE_SEQ 0,1   38: TOGGLE_SEQ 0,2   39: TOGGLE_SEQ 0,3
40: TOGGLE_SEQ 1,0   41: TOGGLE_SEQ 1,1   42: TOGGLE_SEQ 1,2   43: TOGGLE_SEQ 1,3
44: TOGGLE_SEQ 2,0   45: TOGGLE_SEQ 2,1   46: TOGGLE_SEQ 2,2   47: TOGGLE_SEQ 2,3
48: TOGGLE_SEQ 3,0   49: TOGGLE_SEQ 3,1   50: TOGGLE_SEQ 3,2   51: TOGGLE_SEQ 3,3
```

**Resolution:** Complete SMC-PAD Launcher P3. Add all 16 lines in webconf → MIDI Options → Master Key Actions.

---

### Conflict 5 — ~~Maschine RPN14/RPN7 invisible to CC Learn~~ RESOLVED (2026-06-06)

Encoders now send standard CC 16–23 (configurable). Transport buttons now send CC 1–14 (value 127 press, 0 release). Both are standard CC 0–119 — Zynthian CC Learn can capture them. Maschine MK2 Part 2 redesign is now unblocked.

**Previous issue:** Encoders sent RPN14, buttons sent RPN7 — neither capturable by CC Learn. MIDI filter rules were planned as a workaround. No longer needed.

---

### Conflict 6 — Xboard CC defaults unknown

Factory CC numbers for the 16 knobs not documented in text manual. Risk of collision with SMC-PAD CCs (16/17/18/30/80/81/82/31) or standard engine parameters.

**Resolution:** Before assigning any Xboard knob, run:

```bash
amidi -d -p hw:X,0,0    # replace X with Xboard card number from aconnect -l
```

Turn each knob and record CC number. Map conflicts before any tutorial uses the knobs.

---

### Conflict 7 — ctrldev DRUM_CHAN hardcoded to ch 6

`zynthian_ctrldev_sinco_smc_pad.py` has `DRUM_CHAN = 5` (0-indexed = ch 6). SMC-PAD transport Left/Right cycle drum kits only if drum chain is on ch 6. Dub Techno snapshot puts drums on ch 1 — transport buttons target wrong chain if loaded with driver active.

**Resolution:** Maintain separate snapshots per use case: SMC-PAD Drum Computer snapshot = drums on ch 6; Dub Techno snapshot = drums on ch 1 (transport Left/Right inactive in that context). Or update `DRUM_CHAN` constant in the driver when switching snapshots.

---

### Conflict 8 — CC 25/26 ch 1 reserved for SMC-PAD transport

If any Xboard knob maps to CC 25 or CC 26 on ch 1, it unintentionally cycles drum kits.

**Resolution:** Reserve CC 25 and CC 26 on ch 1 for SMC-PAD transport buttons only.

---

### Conflict 9 — dev3_in fan-in: SMC-PAD Master + Maschine daemon

Both SINCO SMC-PAD Master and the Maschine daemon `Pads MIDI` port connect to `ZynMidiRouter:dev3_in` (JACK allows multiple inputs to one port). Both are active simultaneously. No hard conflict as long as channel discipline holds (Maschine on ch 1, SMC-PAD on ch 6). If USB enumeration order changes, SMC-PAD may shift off `system:midi_capture_4` and `dev3_in` would wire Maschine to a different slot.

**Resolution:** Monitor in testing. If enumeration shifts, run `aconnect -l` and `jack_lsp -c` to diagnose.

---

### Conflict 10 — SINCO Private port mirrors all pad MIDI (double CUIA firing)

SINCO SMC-PAD has three ALSA ports. Port 0 (Private = SINCO IN 1 = `system:midi_capture_3`) is supposed to carry internal device messages only — but on this firmware it mirrors all pad notes from Port 1 (Master = SINCO IN 2 = `system:midi_capture_4`). Both ports are connected to ZynMidiRouter by autoconnect. Both fire as master channel events, causing TOGGLE_SEQ (and all other master-channel CUIAs) to fire **twice per pad press** — double-toggle = no net change.

**Confirmed:** live MIDI debug showed `EV izmip=2 head=0x95 chan=5` and `EV izmip=3 head=0x95 chan=5` for a single pad press — identical events from both ports.

**Workaround (applied):** 50ms debounce on `cuia_queue.put_nowait` in `zynthian_state_manager.py` — same note within 50ms fires CUIA only once. Change is on the Pi, not committed to the zynthian-ui git repo.

**Permanent fix options:**
1. Patch `zynautoconnect` to skip ports whose JACK alias starts with `USB:…/SINCO IN 1`
2. Use `lib_zyncore.zmip_set_flags(izmip, flags & ~FLAG_ZMIP_UI)` after identifying the Private port's zmip index at startup — clears UI flag so master-channel events from that port are silently consumed and not sent to Python

**`ZYNTHIAN_MIDI_PORTS DISABLED_IN` does NOT work** — field exists in config but is not enforced by current autoconnect code.

---

### Conflict 11 — SMC-PAD reflashed to Koala preset: pads now on ch 10 (2026-08-06)

The device carries the NiFox Koala preset pack. Pads send on **channel 10**; the whole rig is built around channel 6. Nothing on the Zynthian side has changed, so pads currently reach no drum chain and fire no master-channel CUIA.

Affected, in order of how quietly they fail:

| What | Where | Symptom |
|---|---|---|
| `ZYNTHIAN_MIDI_MASTER_CHANNEL=6` | `/zynthian/config/midi-profiles/default.sh` | no CUIA fires; pads look dead in Launcher |
| Drum chain on ch 6 | rig-v1, Drum Computer, Dub Techno snapshots | pads play nothing |
| `DRUM_CHAN = 5` | `zynthian_ctrldev_sinco_smc_pad.py` | transport Left/Right cycle the wrong chain — see Conflict 7 |
| `ZYNPOT_ABS` on CC 16/17/18 | same driver | three of four screen knobs dead; CC 30 still works |

**Recommended fix — one filter rule, nothing else changes:**

```
MAP CH#9 => CH#5
```

Add in webconf → **Interface → MIDI Options → Midi filter rules**. Channels in filter rules are **0-indexed**, so `CH#9` = channel 10 and `CH#5` = channel 6. Bank A pad notes are still 36–51, so once the channel is translated every existing mapping — master key actions, drum chain, `DRUM_CHAN` — works untouched. Syntax verified against `zynthian-ui/zyngine/zynthian_midi_filter.py` (see `test_map_rules`, e.g. `MAP CH#0:15 CC#45 => CH#15 CC#76`).

Two caveats. The rule is global, not per-port — any other device sending ch 10 is also remapped; nothing in this rig does. And a bare `MAP CH#a => CH#b` covers all event types on that channel, which is what is wanted here since the NiFox CCs sit on ch 1.

**Alternative** — change `ZYNTHIAN_MIDI_MASTER_CHANNEL` to 10 and move every drum chain to ch 10. More edits, more places to forget, and it collides with the GM drum convention. Not recommended.

The dead encoder CCs are a separate matter: the filter rule does not fix them, since NiFox reassigned the CC numbers themselves. Either remap in the ctrldev driver (CC 16/17/18 → the NiFox bank-A numbers) or add `MAP CH#0 CC#31,32,33 => CH#0 CC#16,17,18` once the real encoder CCs are confirmed on the Pi.

**Not yet verified on hardware** — Pi was unreachable when this was written (`No route to host`, 192.168.2.123). Confirm with `amidi -d` before applying.

### Conflict 12 — Maschine HID input dies after seconds: kernel hidraw stops delivering — RESOLVED (2026-08-06)

**Symptom.** Pads, buttons and encoders produce no MIDI 6–37 s after the daemon starts, while pad LEDs still work. A daemon restart brings input back for a few more seconds. This had been latent for weeks: the Step Sequencer Part 5 verification passed on 2026-06-07 only because it was tested within seconds of a restart.

**Cause.** The MK2 streams ~750 HID reports/s unconditionally (endpoint `ep_82`, 125 µs interval) whether or not anything is touched. The kernel's hidraw layer stops delivering those reports to an open file descriptor after a few seconds at that rate: `poll()` goes permanently quiet and `read()` returns `EAGAIN` forever, while `usbmon` shows the URBs still completing with report data. Kernel `6.12.47+rpt-rpi-v8`, `HIDRAW_BUFFER_SIZE = 64` — about 85 ms of buffering at that rate.

**Ruled out by measurement**, so don't re-chase these: the USB hub (the `2109:3431 VIA Labs` device is the Pi 4's internal VL805, not an external hub — the MK2 is direct), USB autosuspend (`power/control = on`), LED writes, display writes, drain rate, periodic keepalive writes, stale file descriptors, and the aftertouch path. `HID SET_IDLE(0)` is accepted and `GET_IDLE` reads back 0, but the device ignores it, so the rate cannot be reduced at the source. `snd-usb-caiaq` has no alias for `17cc:1140`, so there is no in-kernel driver alternative.

**Fix** (in `MaschineMK2_linux`, commit `0b36cd9`): an input watchdog reopens the device when no report arrives for 50 ms. Two details matter:

- The **close must happen before the reopen**. `usbhid` only tears down and resubmits the interrupt URB when the device user count drops to zero, so opening first keeps a user held and the reopen does nothing at all.
- `readable()` drains until `EAGAIN` rather than taking one report per poll iteration (drain rate ~220/s → ~1400/s), `write_lights()` writes only on change, and the display writes are disabled.

**Result:** sustained input, ~14 transparent reopens per 110 s, roughly 0.6 % dead time.

---

## Section 4 — Zynthian MIDI Feature Map

What Zynthian can receive and respond to. Check here before assigning a device control to avoid collisions.

| Feature | MIDI trigger | Ch scope | Configure via |
|---|---|---|---|
| Play note on chain | Note On | per-chain MIDI ch | Chain Options → MIDI Channel |
| Route all to active chain | Note On (any ch) | any | SINGLE_ACTIVE_CHANNEL=ON (currently ON) |
| CC → synth engine parameter | CC 0–119 | per-chain ch | CC Learn: long-press param knob ~600 ms |
| CC → screen knob (absolute) | CC 16 / 17 / 18 / 30 | any | ctrldev driver active on SINCO IN 2 |
| Volume | CC 7 | any | always active |
| Sustain | CC 64 | any | always active |
| Modulation | CC 1 | any | always active |
| Preset recall | Program Change | active chain ch | standard |
| ZS3 subsnapshot recall | Program Change | active chain ch | PROG_CHANGE_ZS3=ON *(currently ON)* |
| Bank select | CC 0 (MSB) + CC 32 (LSB) + PC | active chain ch | MIDI_BANK_CHANGE setting |
| Launcher slot toggle | Note On on master ch (6) | ch 6 only | webconf → MIDI Options → Master Key Actions |
| Any CUIA action | Note On on master ch (6) | ch 6 only | webconf → MIDI Options → Master Key Actions |
| Drum kit cycle (via ctrldev) | CC 25 / CC 26 press on ch 1 | ch 1 only | ctrldev driver active |
| Channel aftertouch | Channel Pressure | per-chain ch | if engine supports |
| Poly aftertouch | Poly Pressure | per-chain ch | if engine supports |
| Pitch bend | Pitch Bend | per-chain ch | standard |
| Panic | CC 123 (All Notes Off) | any | standard |
| Pitch bend range | RPN 0 | standard | standard |
| Fine tuning | RPN 1 / RPN 2 | standard | standard |

---

## Section 5 — Maschine MK2 drum rig, as built

The rig running today, for reference when extending it. Driver:
`zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py` with pure logic in
`maschine_mk2_lib.py`. Snapshot `021-maschine-drum-rig-sfz`; `020-maschine-drum-rig`
is the FluidSynth predecessor, kept as a fallback.

**Structure.** Eight groups on MIDI channels 1–8, one chain each, all on
LinuxSampler with their own SFZ drum-machine kit. Each group is one sound: a kit
plus a note within it. All sequencing lives in zynseq, so patterns persist in
snapshots and the touchscreen pattern editor mirrors them.

**Bound controls**

| Control | Function |
|---|---|
| 16 pads | toggle steps of the selected group; a white playhead sweeps while playing |
| Group A–H | select group; LED carries the group's colour, brightness shows its volume |
| Encoder 1–4 | hits · rotation · division · length (euclidean pattern) |
| Encoder 5 | pan — **mixer strip balance** |
| Encoder 6 | sample within the kit |
| Encoder 7 | kit — 40 SFZ drum machines |
| Encoder 8 | volume — **mixer strip level** |
| F1–F8 | mute groups A–H, independent of selection (mixer strip mute) |
| Play | start/stop all eight sequences |
| Restart | jump every group to step 0 |
| Erase | clear the selected group |
| Arrows beside the display (CC 5/6) | step the group's sample through its kit |
| Both screens | group tabs with sample names, dotted rule, one column per encoder with name, double-height value and an indicator bar |

**Free for future use:** roughly 20 LED buttons (Scene, Pattern, Pad Mode,
Navigate, Duplicate, Select, Solo, Mute, Step, Control, Browse, Sampling, All,
Auto Write, Grid, Enter, Note Repeat, Tempo, Swing, Volume), the big detented
encoder and its push, both master arrows, pad pages, knob pages, and Shift
combinations.

**Behaviour worth knowing when extending**

- Encoders are **relative**: the daemon holds each encoder's CC value as device
  state and moves it by the hardware delta, so every group keeps its own values.
  Sensitivity is derived from the 128-unit sweep; division and length use a flat
  8 units per step.
- Volume and pan are on the **mixer**, not the engine, because LinuxSampler
  exposes no controllers at all. This is engine-independent and survives in
  snapshots.
- Kit and sample names are parsed from the `.sfz` files; Zynthian's `keymaps.json`
  cannot match an SFZ kit.
- Measured cost of the whole rig, eight kits live: ~6% of the Pi's CPU, ~250 MB,
  zero xruns. **Caveat found 2026-08-09:** this was measured with `jackd` on
  `hw:Headphones` at 48000 (`-P 70 -s -S -d alsa -d hw:Headphones -r 48000 -p 512
  -n 3 -o 2 -X raw`) — the Pi's built-in PWM output — not on the Sound Blaster
  Play! 2 (`hw:S2`, 44.1 kHz) this project's hardware notes describe.
  `/zynthian/config/zynthian_envars.sh` has `SOUNDCARD_NAME="RBPi Headphones"`.
  The number is real but not representative of the documented rig; re-measure
  after switching the soundcard back before trusting it for FX headroom
  decisions.

---

---

## Going Further

- Complete SMC-PAD Launcher P3: add all 16 TOGGLE_SEQ mappings in webconf
- Verify Xboard CC defaults via `amidi -d`, then design Xboard CC Knob Mapping tutorial
- Map Maschine encoder CCs to Zynthian synth parameters via CC Learn (Maschine MK2 Part 2)
- Verify SMC-PAD encoder MIDI channel with `amidi -d`
- Map SMC-PAD bank 2 (PAD BANK / KNOB BANK assignments)
- Update this page after each tutorial is verified — change `[draft]` → `[verified]` in the assignment matrix
