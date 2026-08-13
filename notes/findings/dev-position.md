# The Techno Machine — developer position paper

**Date:** 2026-08-09
**Author role:** Zynthian developer (feasibility counterweight to the product owner's wish list)
**Responds to:** `docs/superpowers/2026-08-09-techno-machine-mapping.md`
**Builds on:** `specs/2026-08-06-maschine-drum-rig-design.md`, `specs/2026-08-09-maschine-sfz-kits-design.md`,
`htmldoku/project-midi-reference.md` §1 and §5

---

## 0. The position in one paragraph

The machine described in the mapping is about **85 % buildable at tiers 1 and 2** — configuration
and the existing ctrldev driver — and the parts that are not buildable are not the parts anyone
expected. Turing sequencing, scale quantisation, tempo sync, mutes, solos, screens, LEDs and
snapshot recall are all reachable from the driver, and zynseq turns out to hold **five capabilities
nobody in this project has noticed** that are worth more than half the wish list. The one genuine
wall is **per-channel sends**: they cannot be built at any tier below 4, because `MAX_CHANNELS` is
17 in `zynlibs/zynmixer/mixer.c:48` and the send topology needs 26 strips. I would not raise it.
I would build inserts instead, gated on one measurement. The second wall is **the big encoder**,
which is not merely unverified — it is **not decoded anywhere in the daemon at all**, and I refuse
to hang any musical function on it. SHIFT, by contrast, is a five-line patch and I would ship it.

---

## 1. What I actually verified on the Pi

Everything in this paper that touches an API was checked against the **installed** Zynthian on
`192.168.2.123`, not the local checkout. Commands and results:

| # | Claim | Command | Result |
|---|---|---|---|
| 1 | zynmixer has no send | `grep -n "    def " zyngine/zynthian_engine_audio_mixer.py` | level · balance · mute · solo · phase · mono · ms · normalise · dpm. **No send. Confirmed.** |
| 2 | Mixer strip budget | `python3 -c "CDLL(libzynmixer.so).getMaxChannels()"` → **17**; `grep MAX_CHANNELS zynlibs/zynmixer/mixer.c` → `#define MAX_CHANNELS 17` at line 48; `jack_lsp \| grep -c zynmixer` → **68** ports (17 × 4) | Strip 16 is the main bus (`mixer.c:164,178,217,258`). **16 usable chain strips, hard.** |
| 3 | Chain routing has no per-destination gain | `sed -n 294,375p zyngine/zynthian_chain.py` | `for output in self.get_audio_out(): self.audio_routes[output] = sources.copy()` — **every destination gets the identical source at unity.** Confirmed: on/off only. |
| 4 | A route out of a chain is **post-fader** | same, line 361 | `sources = ["zynmixer:output_NN"]` — a send tap follows the channel's fader **and its mute**. Musically correct, and it preserves everything the shipped rig already does on the strip. |
| 5 | Post-fader processor slots exist | `grep -n fader_pos zyngine/zynthian_chain.py` (lines 64, 306-363, 672-741) + `add_processor(..., post_fader=...)` in `zynthian_chain_manager.py:768` | An audio effect can sit **after** the mixer strip, fed from `zynmixer:output_NN`. This is what makes inserts behave like sends. |
| 6 | JACK config | `ps aux \| grep jackd` | `jackd -P 70 -s -S -d alsa -d hw:Headphones -r 48000 -p 512 -n 3` — **512 frames × 3 periods at 48 k = 32 ms latency, 10.7 ms of wall clock per callback.** Enormous headroom. This single fact is why I am willing to add 16 plugin nodes. |
| 7 | Headroom now | `top -bn1`, `uptime` | zynthian `python3` 36.8 % of one core, load avg 0.68 of 4.00, 2.1 GB free. The UI, not the audio, is the biggest consumer. |
| 8 | zctrl write path | `grep -n "def set_value" zyngine/zynthian_controller.py` | `set_value(self, val, send=True)` at **line 459**. Present. This is how the driver drives any plugin parameter. |
| 9 | `setSequenceLength` still absent | `nm -D --defined-only libzynseq.so` | `getSequenceLength` present, **no setter**. The whole-beat quantisation stands. |
| 10 | SHIFT is a five-line patch | `sed -n 840,1010p MaschineMK2_linux/src/main.rs` | `send_osc_button_msg` sets `maschine.set_mod()` at **line 850** and then falls into a `match button` (line 918) with **no `"shift"` arm**. Adding one is identical in shape to the existing `"grid" => RPN7(Ch1, 4, …)`. |
| 11 | The big encoder is not decoded | `grep -n "MaschineButton::Encoder" src/devices/mk2/mikro.rs` → **no hits**; `sed -n 34,145p` shows all 24 rows of `BUTTON_REPORT_TO_MIKROBUTTONS_MAP`; `read_buttons` consumes `buf[0..24]` — bytes 0-7 button bits, 8-23 the eight small encoders' counters | `MaschineButton::Encoder` exists only in `base/maschine.rs:79` and the OSC name map (`main.rs:332,399`). It is **never produced**. `roller_state[8]` is never written from HID. |
| 12 | Synth engines available | `engine_config.json`, `ENABLED == true`, `TYPE` contains "Synth" | JC303 · Obxd · Surge XT · Helm · synthv1 · padthv1 · amsynth · Monique · Nekobi · Odin2 · MiMi-d · Dexed · ZY (ZynAddSubFX). More than enough for bass/lead/pads. |
| 13 | FX engines enabled | same | `JV/MDA Ambience` · `JV/Dragonfly Plate Reverb` · `JV/Gxdigital_delay_st` · `JV/MDA DubDelay` · `JV/Tal-Reverb-II/III` · `JV/GxEcho-Stereo`. |
| 14 | The best insert reverb is present but **not enabled** | `lv2ls \| grep -i plate` → `http://moddevices.com/plugins/caps/PlateX2`; `lv2info` → params `bandwidth · tail · damping · **blend** · inl/inr/outl/outr` | CAPS PlateX2 is stereo, has a 0-1 `blend` (dry/wet) and is a cheap Dattorro plate. Enabling it is one tick in webconf — **tier 1**. |
| 15 | ZamDelay is unsuitable | `lv2info urn:zamaudio:ZamDelay` | **Mono in, mono out** (`lv2_audio_in_1` only). Has `sync`/`div`/`drywet`/`feedb`/`lpf`, but mono means two instances per channel. Rejected in favour of `Gxdigital_delay_st`. |

### 1.1 Five zynseq capabilities this project has not noticed

From `nm -D` on the Pi's `libzynseq.so` and `zynlibs/zynseq/zynseq.py` (argtype declarations at
lines 95-124). These change what the STEP page should contain:

| Symbol | Wrapper | What it gives us |
|---|---|---|
| `setPlayChance(float)` / `getPlayChance()` | **declared**, `zynseq.py:114-115` | Per-pattern **play probability**. This is the Turing machine's `DENSITY` knob, native, persisted in the snapshot, **costing zero pattern writes**. |
| `setNotePlayChance(step, note, chance)` / `getNotePlayChance` | in the `.so`, **not declared** in the wrapper | Per-**step** probability. Default ctypes int marshalling will work (uint32/uint8/uint8) but must be confirmed before use. |
| `setSwingAmount(float)` / `setSwingDiv(uint32)` | **declared**, `zynseq.py:108-109` | **Per-pattern swing.** The mapping doc §7 states per-channel swing "is not representable in zynseq patterns". **That is wrong** — it is one call, and it is in the snapshot. |
| `setStutterCount(step, note, n)` / `setStutterDur` | in the `.so` | **Per-step ratchets.** This is note-repeat, per step, for free, and it is the most techno-useful thing in the entire API. The mapping doc defers Note Repeat as "the best candidate for the next thing added" — it is already here. |
| `addControl` / `setControlValue` / `setControlOffset` | **declared**, `zynseq.py:102-107` | **Per-step CC automation inside the pattern.** Filter sweeps and send throws can be sequenced, persisted and edited on the touchscreen, with no driver thread involved. |

Also present and useful: `transpose(int)` (pattern transpose — the `ROOT` knob, free),
`setScale`/`setTonic` (pattern-level, stored in the snapshot; drives the touchscreen editor's
keyboard, does **not** quantise incoming notes), `setNoteOffset(step, note, float)` (per-note
micro-timing), `setHumanTime`/`setHumanVelo`.

---

## 2. Capability ledger

Tiers: **1 CONFIG** · **2 DRIVER** (`zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py` +
`maschine_mk2_lib.py`) · **3 DAEMON** (`MaschineMK2_linux`, Rust) · **4 CORE** (last resort).

| Capability | Tier | What specifically has to be built |
|---|---|---|
| **Euclidean drum sequencing** | **done** | Shipped. `maschine_mk2_lib.euclid()` / `build_pattern()` → `libseq.addNote`. No work. |
| **Turing sequencing (pitch register)** | **2** | New pure function in `maschine_mk2_lib.py` beside `euclid()`: an *n*-bit shift register with a mutation probability, unit-tested the same way. Output written to zynseq via the driver's existing `_write_pattern`/`_select_pattern`/`_pattern_of`. Regeneration triggered from the driver's **existing** 30 Hz thread (`PLAYHEAD_POLL_S = 0.033`) on a playhead wrap, **under `self.lock`**, never from `SS_SEQ_PROGRESS`. |
| **Turing `DENSITY` / `RANDOM` gating** | **1-2** | Do **not** implement by rewriting the pattern. `libseq.setPlayChance(float)` is native and persisted (verified, `zynseq.py:114`). Only the *pitch* register needs writes. |
| **Turing `GATE` (note length)** | **2** | `addNote(step, note, velocity, duration, offset)` — `duration` is a `c_float` already declared (`zynseq.py:95`). Free parameter on a call the driver already makes. |
| **Tempo-synced clock division** | **done** | `setStepsPerBeat` / `setBeatsInPattern`, already driven by encoder 3. Whole-beat quantisation stands (item 9). |
| **Scale / root quantisation** | **2** | Second pure function in the lib, applied to register output before `addNote`. Additionally call `setScale`/`setTonic` on the pattern so the touchscreen editor draws the right keyboard — free, persisted, cosmetic. |
| **Per-channel reverb + delay** | **1 (+2 to drive it)** | **Post-fader insert per channel**, placed once in a prepared snapshot via `chain_manager.add_processor(chain_id, "JV/C* PlateX2", post_fader=True)` and the same for `JV/Gxdigital_delay_st`. Driver writes `blend` / dry-wet with `zctrl.set_value()` (verified, line 459). **Enable PlateX2 in webconf first.** See §3.1 — a true send is tier 4 and I refuse it. |
| **Delay time follows BPM** | **2** | Driver computes ms from `libseq.getTempo()` (returns `c_double`, declared) × the chosen division and writes the delay's time zctrl. Works with any delay plugin; needs no plugin-side sync. Recompute on the 100 ms display tick, not per encoder event. |
| **Per-channel synth parameter control (voices)** | **2** | `processor.controllers_dict[symbol].set_value(v)`. Choose voices for the zctrls they expose: **JC303** (bass — cutoff/reso/env/decay/accent are its whole point), **Obxd** or **Surge XT** (lead), **padthv1** or **ZY** (pads). A column whose zctrl is missing draws greyed and its encoder is inert — the convention the SFZ work already established. |
| **Per-channel drum parameter control** | **refused for v1** | See §3.3. `zynthian_engine_linuxsampler` inherits `_ctrls = []`; FluidSynth CC 74/71 is a proven dead end. KIT and SAMPLE (shipped, hardware-verified) already deliver more character than a filter would. |
| **Volume / pan per channel** | **done** | `zynmixer.set_level` / `set_balance`, engine-independent, in the snapshot. Shipped. |
| **Mutes** | **done** | `zynmixer.toggle_mute` on the strip, currently on F1-F8. Shipped and hardware-verified. |
| **Solos** | **1-2** | `zynmixer.toggle_solo(chan)` — verified present, additive, with a special case at `MAX_NUM_CHANNELS - 1` (main strip = clear all). **I disagree with the mapping on where it goes — see §4.** |
| **Screens** | **2** | `maschine_mk2_lib.screen_packets()` already renders tabs + four columns per panel. Adding a page dimension is a dict lookup. **Blocked** until the untested 128×32 + both-row-bands tile is confirmed (`MD/display-investigation.md`). |
| **LEDs** | **2** | `led_cache` in the lib, diff-based. Must be **cleared** on `SS_LOAD_SNAPSHOT` or the repaint is suppressed as unchanged — already paid for once. |
| **SHIFT as a modifier** | **3** | ~5 lines. See §3.2. |
| **Big encoder / its push** | **refused** | Not decoded at all (item 11). Would need a `usbmon` capture and new HID parsing — research, not a patch. |
| **Snapshots / recall** | **1 + 2** | Mixer, zynseq patterns, chain presets and insert-FX zctrls are all already in the `.zss`. The **Turing register state is driver state** and belongs in `zynthian_ctrldev_base.get_state`/`set_state` (verified present on the Pi at lines 183/188). LOOP play mode must be **re-forced** after every restore, and the LED cache cleared. |
| **Tempo sync / transport** | **1-2** | zynseq owns JACK transport (`transportRequestTimebase`, `setTempo(c_double)`). BPM knob = `libseq.setTempo`. `setPlayState` per sequence — **never `TOGGLE_PLAY`**. Shipped. |
| **Swing** | **1** | `libseq.setSwingAmount(float)` — per pattern, therefore **per channel**, contradicting the mapping's §7. One call. |
| **Ratchets / note repeat** | **2** | `setStutterCount` / `setStutterDur` per step. Free. |
| **Per-step parameter automation** | **2** | `addControl` / `setControlValue`. Free, persisted, editable on the touchscreen. Not in the brief; noted as the cheapest future win. |

---

## 3. The three open problems

### 3.1 Per-channel sends — verdict: **build inserts, not sends**

The mechanism does not exist and cannot be made to exist below tier 4. Two independent code
facts kill it:

1. **`zynthian_chain.rebuild_audio_graph` gives every destination the identical source at unity**
   (item 3). There is no per-destination gain, and a post-fader processor attenuates *all* outputs
   equally, so it cannot be turned into one.
2. **The native workaround does not fit in 16 strips.** A "send tap" chain per (channel, FX) pair —
   `audio_thru`, no processors, its mixer strip level *being* the send level, un-normalised so it does
   not double-feed main, output routed to a shared FX chain — is a genuinely correct design and uses
   only shipped mechanisms. It needs **8 channels + 16 taps + 2 returns = 26 strips.** There are 16
   (item 2). Even the degenerate one-tap-per-channel-into-one-combined-FX-chain variant needs
   **8 + 8 + 1 = 17** — one over — and it collapses reverb and delay onto a single knob, which
   fails the brief anyway.

Evaluating the four options honestly:

| Option | Verdict |
|---|---|
| **(a) True send bus** | **Refused.** Needs `MAX_CHANNELS` raised in `zynlibs/zynmixer/mixer.c:48` — realtime C, +64 JACK ports, and the snapshot format and touchscreen mixer both assume 16. Tier 4, permanent upstream divergence, for a feature the player cannot hear the difference of once inserts are in place. |
| **(b) Per-channel insert FX, wet driven by the driver** | **Chosen.** Zero extra strips. No new mechanism at any tier. Post-fader (item 5) so it is fed from `zynmixer:output_NN` and therefore already follows the channel's fader and its mute — every assumption in the shipped rig survives untouched. The mapping doc already designed for this fallback: same knobs, same legends, same screens, and the ALL page's four FX columns become the selected channel's own. **Per-channel delay time is a better performance control than a shared one**, which the mapping itself concedes. |
| **(c) Shared FX chain, per-channel routing on/off** | **Kept as the degrade path.** 2 strips, 2 plugins, and "throw the delay on" is a real techno gesture. If (b) fails its measurement gate, this is where reverb goes and per-channel delay inserts stay. |
| **(d) MIDI-controlled send levels** | **Dead.** There is no send to control. |

**Expected cost of (b) on this Pi, and why I am confident.** The DSP is not the issue. CAPS Plate
is a Dattorro 8-delay-line plate, on the order of 0.3-0.6 % of one core per stereo instance at 48 k;
`Gxdigital_delay_st` is a circular buffer plus a one-pole, under 0.2 %. Eight of each is roughly
**4-7 % of one core**, against ~6 % for the eight samplers and 36 % for the UI, on a four-core box.
I would **not** use Dragonfly Plate (freeverb3 with oversampling, several percent per instance —
eight of those is 16-32 % of a core).

The real costs, in the order they will bite:

1. **RAM and process count.** 16 more `jalv` processes at ~25-40 MB RSS ≈ **480 MB**. With 3.0 GB
   free that fits, but it is the largest single line item in the whole design.
2. **Snapshot load time.** Sixteen processes to spawn. The shipped rig's load already takes seconds.
   This is the user-visible cost and nobody has measured it.
3. **JACK graph nodes.** 16 more per-period wakeups. At 512 frames × 3 periods (item 6) there is
   10.7 ms of wall clock per callback and this is comfortable. **At 128 × 2 I would not do it** — so
   if the buffer is ever shortened, this design has to be revisited.

**Therefore: (b) ships behind a measurement gate, not a promise.** Build the snapshot, measure
CPU / RSS / xruns / load time *before writing a line of driver code*, and if 16 instances cost more
than ~10 % of a core or push snapshot load past ~15 s, degrade to (c) for reverb and keep the
eight delay inserts.

### 3.2 SHIFT not being emitted — verdict: **build it, it is five lines**

`send_osc_button_msg` in `MaschineMK2_linux/src/main.rs` already resolves `button == "shift"` and
sets the internal modifier at **line 850**, then falls into a `match button` at line 918 that simply
has no arm for it. The patch is one arm, structurally identical to its neighbours:

```
"shift" => { RPN7(Ch1, 49, cc_math::button_cc_value(is_down)) }
```

CC 49 is free (the map is 1-14 and 24-48). The `set_mod()` block runs *before* the match and is
untouched, so the daemon's own SHIFT behaviour cannot regress. Two cautions:

- `if button.contains("shift")` at line 850 is a **substring** test. Confirm no other name in
  `btn_to_osc_button_map` contains it before assuming the modifier logic is unaffected.
- **The stuck-modifier fear is smaller than it looks, and I can say why.** `read_buttons`
  (`mikro.rs:411`) decodes buttons as an XOR diff against a cached byte, and the hidraw watchdog
  reopens the file descriptor without resetting that cache. So if a SHIFT *release* is lost inside a
  reopen window, the very next report differs from the cache and the release is emitted late — within
  roughly the reopen window, ~50 ms. **This is a hypothesis derived from the code, not a measurement.**
  The acceptance test is: hold SHIFT across a reopen (`watchdog: input stalled, reopened` in the
  journal), release it during the dead window, and watch `jack_midi_dump` for the CC 49 = 0.

Belt and braces regardless: any latched page press should clear the driver's shift flag, so a lost
release can never strand the player in the mixer layer.

### 3.3 Drum sound parameters — verdict: **drop them, and fill the columns with things that exist**

`TUNE`, `DECAY`, `FILTER`, `DRIVE` have no source and every remaining avenue is closed:
LinuxSampler inherits `_ctrls = []`, FluidSynth's CC 74/71 is proven dead, and SFZ-side pitch over
LSCP is unverified against a sampler Zynthian owns the lifecycle of. The obvious fix — an LV2
filter and drive per drum chain — would mean **8-16 more `jalv` processes on top of the 16 the
sends already cost**, i.e. up to 32. I refuse that on resource grounds before it is even designed.

My position is that this is the wrong problem. The drum CONTROL page already has the two most
powerful controls on the machine: **KIT (41 SFZ drum machines) and SAMPLE**, both shipped, both
hardware-verified, both delivering an 808-kick-against-an-SP1200-hat move that no filter sweep can
match. Four greyed columns beside them is honest, and the greyed-column convention was invented for
exactly this.

But two of those four columns should not be blank, because zynseq hands us real controls for free
(§1.1):

- **`SWING`** — `libseq.setSwingAmount(float)`, per pattern, per channel, in the snapshot. One call.
- **`CHANCE`** — `libseq.setPlayChance(float)`, per pattern. Drums that drop hits probabilistically
  is a first-class techno control and it costs nothing.
- and behind those, **`RATCHET`** via `setStutterCount` when a third is wanted.

That converts the weakest page in the design into a page with six live controls, without adding a
single process. It is the best answer I have to §8.2 and it is strictly better than the LV2 route.

---

## 4. What I refuse to build, and what I would defer

### Refuse

1. **Raising `MAX_CHANNELS` in `zynlibs/zynmixer/mixer.c:48`** to make true sends fit. Tier 4,
   realtime C, +64 JACK ports, and both the snapshot format and the touchscreen mixer assume 16
   strips. Permanent upstream divergence for an inaudible gain over inserts.
2. **Adding a per-destination gain to `zynthian_chain.rebuild_audio_graph`.** That function is the
   routing core every chain in Zynthian uses, and `zynautoconnect` would have to learn about it too.
   Tier 4, highest blast radius in the codebase.
3. **Per-drum-chain filter/drive LV2s.** Up to 32 `jalv` processes total. Not until §3.1's
   measurement says there is room, and probably not then.
4. **Any musical function that depends on the big encoder or its push.** It is not "unverified" —
   `MaschineButton::Encoder` appears nowhere in `BUTTON_REPORT_TO_MIKROBUTTONS_MAP` and
   `roller_state[8]` is never written from HID (item 11). Making it work is a `usbmon` capture and
   new report parsing. The mapping already put BPM and swing on the ALL page precisely so nothing
   depends on it; hold that line. Master volume goes to the touchscreen.
5. **Encoder capacitive touch.** Not implemented, possibly not in the stream, and the design has no
   dependency on it. Do not investigate.
6. **Runtime processor add/remove from the driver.** Everything is a prepared snapshot, exactly as
   the SFZ design decided. `fader_pos` bookkeeping (`zynthian_chain.py:672-741`) is fiddly enough
   that the driver must never touch it.
7. **Generating Turing notes outside zynseq** — e.g. the driver emitting note-ons itself. It would
   lose persistence, the touchscreen pattern editor and pad editing, and it would put note timing on
   a Python thread with no JACK clock. The pattern is the source of truth.
8. **Pattern chaining, song mode, scenes.** Out of scope for a live improvising machine.

### Defer

- **Drum `TUNE` / `FILTER` / `DRIVE`** — until §3.1's measurement is in and there is known headroom.
- **`PAD MODE` + `REC` live recording.** It is a whole second input mode with a quantiser and a
  distinct LED language. Real value, but it is v2 — the generator-owns-the-pattern rule is what keeps
  v1 comprehensible.
- **`GHOST`** (a second quieter euclidean layer). An invention beyond the brief.
- **Per-channel delay division as a synced fraction.** v1: one global division, driver-computed ms.
- **The saturation cue on the group LEDs.** Flagged in the mapping as likely to read badly at low
  brightness; the inverted tab is authoritative anyway. Try it last, drop it without argument.
- **Per-step CC automation** (`addControl`). The cheapest future win in the whole API, but not asked
  for. Note it and move on.

---

## 5. The prototype I would ship

Five items, ordered. Items 1-3 are all gates: none of them is implementation, and each can kill or
reshape what follows. That is deliberate — this design has three unverified load-bearing assumptions
and they should cost hours, not weeks.

| # | Work item | Effort | Why it is here, and why now |
|---|---|---|---|
| **1** | **Confirm the untested display tile.** Send the three-line test (y=2 small, y=24 double-height, y=48 small) at 128×32 with **both** row bands per tile, photograph both panels. | **~1 h** | `MD/display-investigation.md` says this combination shipped **untested**. Every screen in the mapping — three pages, the mixer overlay, the tab row — sits on it. Nothing else should start first. |
| **2** | **Emit SHIFT as CC 49** — one arm in the `match button` at `main.rs:918`, deploy by `git bundle` (the Pi has no GitHub auth), re-set `"external_pad_leds": true` in `maschine.json` afterwards. Then hold SHIFT across a hidraw reopen and watch `jack_midi_dump` for the release. | **~2 h** | Load-bearing for mute and the entire mixer layer. Cheap, isolated, and the reopen test settles the only real objection to a momentary modifier (§3.2). |
| **3** | **Prepared snapshot v2 + the measurement gate.** Enable `C* PlateX2` in webconf. Build 8 chains on strips 0-7 — 5 LinuxSampler drum kits, JC303 bass, Obxd/Surge lead, padthv1/ZY pads — each with a post-fader PlateX2 and `Gxdigital_delay_st`. **Measure CPU, RSS, xruns and snapshot load time over a 5-minute run before writing any driver code.** Fix jackd onto the Sound Blaster first. | **~4 h** | This is the whole sends decision (§3.1) reduced to one number. If it fails, item 4 changes shape and item 5 does not. Writing driver code before this is how plans die. |
| **4** | **Driver: the page layer.** One `self.page` variable (CONTROL / STEP / ALL), latched, LEDs derived from it on the **existing** 100 ms display tick — never written at the press. SHIFT-held mixer overlay. Encoders 7/8 → the insert wet zctrls via `zctrl.set_value()`. Drum STEP page gains `SWING` and `CHANCE` in the two columns the mapping left blank. | **~1 day** | Extends the shipped driver instead of replacing it. Drums keep working at every commit, so every step is testable on hardware in isolation. |
| **5** | **Driver: the three voices.** Turing register as a pure, unit-tested function in `maschine_mk2_lib.py` beside `euclid()`; scale/root quantisation as a second one. Written into zynseq on a playhead wrap detected by the existing 30 Hz poll thread, **one lock acquisition and one `selectPattern` per burst**. `DENSITY` via `setPlayChance`, not by rewriting. Register state persisted through `get_state`/`set_state`. | **~2 days** | The only genuinely new machinery. Everything before it is configuration or a rearrangement of shipped code. |

**Room to extend, by construction:** swing, chance, ratchets, per-step automation, note repeat and
per-note micro-timing are all already in zynseq and all land in the STEP page's spare columns with no
new mechanism, no new process and no new tier. Channel roles stay a table in the driver
(`CHANNELS = [...]`), so 5+3, 4+3+spare or 4+4 stays a config line.

---

## 6. The risks that actually worry me

Ordered by what they can take with them.

1. **The lock, and the Turing write burst.** *(highest — this has already happened once)*
   `libzynseq` is not thread-safe and this driver reaches it from three threads. Unsynchronised
   access has already killed the whole Zynthian UI with SIGSEGV, exit 139, ~95 s into a jam. The
   Turing machine adds a *fourth* pattern of access: a burst of `clear` + 8-16 `addNote` calls at a
   cycle boundary, on the same 30 Hz thread that drives the playhead LEDs, three times over for three
   voices. At 132 BPM a 16-step 1/16 pattern wraps every 1.8 s, so a burst lands roughly every 0.6 s.
   **Mitigations that must be in the design, not added later:** one lock acquisition per burst;
   `selectPattern()` exactly once per burst and **never** in the poll hot path (it writes zynseq's
   single global pattern selection and fights the touchscreen editor for it); and the acceptance test
   is a **twenty-minute** jam with all three voices at `RANDOM` > 0, not a two-minute demo. The last
   bug of this shape took 95 seconds to appear.

2. **Sixteen new `jalv` processes.** ~480 MB RSS, 16 more JACK graph nodes, and a snapshot load
   time nobody has measured. The DSP is affordable at 512 × 3; the process count and the load are
   what will actually hurt. This is why item 3 is a gate and not a step.

3. **jackd is currently on the wrong device.** `jackd … -d hw:Headphones -r 48000 -p 512 -n 3`.
   Every CPU and xrun number taken today is on the Pi's headphone jack, not the Sound Blaster
   (`hw:S2`, 44.1 kHz). The USB interface has a different period profile and its own xrun behaviour.
   **Any measurement taken before this is fixed is worthless**, and that includes the ~6 % figure the
   SFZ work recorded if it was taken the same way.

4. **A momentary modifier over a link that reopens ~14 times per 110 s.** The XOR-diff decode in
   `read_buttons` should re-sync a lost SHIFT release on the next report (§3.2), but that is read off
   the source, not observed. Test it explicitly. Any latched page press must also clear the flag.

5. **Screen repaints starving the input reader.** Redrawing per input report has already tripped the
   hidraw watchdog once. Three pages, two panels and a mixer overlay must still be **one diffed
   repaint per 100 ms tick**, and every LED write stays diff-based against `led_cache` — the daemon
   has been flooded off the USB bus once already.

6. **Snapshot restore rewrites more than you expect.** LOOP play mode must be **re-forced** after
   every restore, not set once; the LED cache must be **cleared** on `SS_LOAD_SNAPSHOT` or the
   repaint is suppressed as unchanged; and a snapshot saved while `RANDOM` > 0 captures whatever the
   register happened to hold. All three are already-paid-for lessons that will be re-learned by
   anyone who writes this driver fresh.

7. **The Pi's Zynthian is older than the local checkout.** Every `libseq.*` and every zynmixer call
   in this paper was audited against the installed `.so` — that is what §1 is for. This has broken
   three times. Audit anything added later the same way; `nm -D --defined-only` costs ten seconds.
