# MaschineMK2_linux

User-space Linux driver for the Native Instruments Maschine MK2 USB controller. Exposes pads, buttons, encoders, and the physical MIDI DIN IN jack as ALSA MIDI, with a browser-based LED/config editor and 128×64 display support.

Forked from [wrl/maschine.rs](https://github.com/wrl/maschine.rs).

---

## Features

### MIDI Output
- **Pads** → ALSA MIDI Note On/Off (velocity-sensitive); note = `note_base + pad_offset`
- **Buttons** → CC messages (mappable in any DAW)
- **Encoders** → CC messages (CC numbers configurable per-encoder, default 16–23)
- **Group buttons A–H** → change MIDI note base (C2–C9)

### MIDI Input
- **ALSA writable port `MIDI Control`** — connect any MIDI source; Note On/Off notes 0–15 control pad RGB LEDs; Clock/Start/Stop forwarded to output
- **Physical DIN MIDI IN jack** — clock and note data forwarded to the `Pads MIDI` output port for sync

### Web Editor
Local browser interface at `web/index.html`. Connect via WebSocket (`ws://127.0.0.1:9001`). Features:
- Set pad LED colors and brightness
- Control button LEDs
- Set MIDI note base
- **Config sidebar**: per-pad note offsets (editable), per-encoder CC numbers (editable), preset layouts (Default / Chromatic / Minor Pentatonic)
- Live event stream: pad presses, encoder movements, button state

### Config Persistence
Settings saved to `maschine.json` in the working directory. Loaded on startup. Editing via web editor writes through immediately.

```json
{
  "pad_notes": [12,13,14,15,8,9,10,11,4,5,6,7,0,1,2,3],
  "encoder_ccs": [16,17,18,19,20,21,22,23]
}
```

`pad_notes` — per-pad offset added to the current note base (0–127 each).  
`encoder_ccs` — CC number sent by each encoder (0–127 each).

### Display
128×64 monochrome OLED. Renders pad note names and encoder CC values using a built-in 5×8 bitmap font.

### Sequencer Mode (experimental)
- Activate: **Shift + Pad Mode** twice
- **Group A–H** — switch between 8 independent 16-step pages; lit button = active page
- Press pads to toggle steps on/off (lit = active); pressing a step also **selects** it (orange LED)
- **Encoder 1** (while step selected) — adjust that step's velocity (0–127)
- **Encoder 2** (while step selected) — adjust that step's note offset (0–127)
- **Shift + Group A–H** — fill current page with Euclidean rhythm (1–8 hits evenly distributed)
- **Shift + tap pad A → tap pad B** — set pad A's step note to pad B's note
- **Play** starts the sequencer on the current page

### MIDI Clock Sync (experimental)
Connect any MIDI host (DAW, Zynthian, hardware sequencer) to the `MIDI Control` input port and send MIDI Clock.

- **External clock** — sequencer steps follow incoming 24ppqn Clock ticks (6 ticks = one 16th-note step); Start resets to step 0 and begins playback; Stop halts playback and preserves position
- **Fallback** — if no Clock tick arrives within 500 ms of the last one, sequencer automatically falls back to internal BPM timer so playback doesn't stall
- **BPM display** — estimated BPM derived from tick interval, emitted as `clock_bpm` event over the WebSocket

Connect from Zynthian or a DAW: `aconnect <zynthian-output-port> <maschine-MIDI-Control-port>`

---

## Requirements

- Rust (install via [rustup](https://www.rust-lang.org/tools/install))
- ALSA development headers (`libasound2-dev` on Debian/Ubuntu, `alsa-lib-devel` on Fedora/RHEL)
- `pkg-config`
- PipeWire, PipeWire-JACK, or JACK

Connect ALSA ports using `aconnect`, Patchance, Qjackctl, or similar.

---

## Building

```sh
git clone https://github.com/Witzman/MaschineMK2_linux.git
cd MaschineMK2_linux
cargo build --release
```

---

## Running

### Find your hidraw device

```sh
for f in /dev/hidraw*; do
  echo "$f: $(cat /sys/class/hidraw/${f##*/}/device/uevent | grep HID_NAME | cut -d= -f2)"
done
```

Or use the interactive helper:

```sh
./run.sh
```

### udev rule (run without sudo)

Create `/etc/udev/rules.d/70-maschine.rules`:

```
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="17cc", ATTRS{idProduct}=="1200", MODE="0666"
```

Then: `sudo udevadm control --reload-rules && sudo udevadm trigger`

### Start the daemon

```sh
./target/release/maschine /dev/hidrawX
```

Replace `X` with the number for your Maschine MK2.

### Open the web editor

Open `web/index.html` in a browser. Connects to `ws://127.0.0.1:9001` automatically and loads current config on connect.

---

## ALSA Ports

After starting, two ALSA sequencer ports appear:

```
client N: 'maschine.rs'
    0 'Pads MIDI   '   ← output: pad notes, button CC, encoder CC, forwarded DIN MIDI IN
    1 'MIDI Control'   ← input:  NoteOn/Off 0-15 → pad LEDs; Clock/Start/Stop → forwarded out
```

Check with `aconnect -l`. Connect with `aconnect <source> N:1` to drive LEDs from a DAW or sequencer.

---

## MIDI Mapping

| Source | Type | Default CC / Note | Notes |
|--------|------|-------------------|-------|
| Pads | Note On/Off | `note_base + pad_notes[i]` | Velocity-sensitive; offsets configurable |
| Group A–H | — | — | Sets note base to C2–C9 (MIDI 24–108) |
| Transport buttons (Play, Stop, Rec, …) | CC 1–14, 24–48 | — | Value 127 = down, 0 = up |
| Encoders 1–8 | CC | 16–23 | Absolute 0–127; CC numbers configurable per-encoder via `maschine.json` or web editor |
| A8 knob | CC 15 | — | Absolute |

### Pad note offsets

Default layout maps pad hardware indices to offsets `[12,13,14,15,8,9,10,11,4,5,6,7,0,1,2,3]` (bottom-left pad = offset 0). With note base 48 (C3), bottom-left fires C3, top-right fires D#4.

Change offsets via the web editor config panel or edit `maschine.json` directly.

---

## OSC (legacy)

OSC listen port: `42434`. Send port: `42435`.

Paths: `/maschine/button/<name>`, `/maschine/pad`, `/maschine/midi_note_base`.

OSC is kept for compatibility; the web editor covers the same functionality.

---

## License

LGPL-3.0. See [LICENSE](LICENSE).
