# SP1 + SP5 Hardware Test — Findings

**Date:** 2026-08-11
**Tested by:** the owner, at the panel, with the driver and daemon deployed
**Build under test:** `zynthian-ui` vangelis `78c0659a`, `MaschineMK2_linux` main `39c4503`

---

## Passed

| Check | Result |
|---|---|
| Five modes latch, exactly one LED lit | PASS |
| VOLUME (MIXER) and AUTO (FILTER) as modes | PASS — both buttons did nothing before today |
| Pressing a lit mode returns to CONTROL | PASS |
| **DL/DR paging** — `LEVEL 1/3 → REVERB 2/3 → DELAY 3/3` | **PASS — the CC 47/48 correction is confirmed on hardware** |
| Ring wraps forward and backward | PASS |
| TL/TR do nothing (deliberately unbound) | PASS |
| Spread page addresses eight channels — encoder 3 moves C, encoder 6 moves F | PASS |
| FILTER greys the five drum columns; a greyed knob is silently dead | PASS |
| Page memory per (mode, kind) — leaving a voice and returning keeps its page | PASS |
| `1/4` division reachable, appended last | PASS |
| **SP5 stuck-note gate** — long note on the last step, four-bar loop | **PASS — no stuck note** |
| Long notes audible — GATE min → stabs, GATE max → sustained | PASS |
| **T4** — RANDOM > 0 with long notes, pattern rewriting every bar | **PASS — no stranded notes** |
| Voice DENSITY thins the pattern, rests stay in place | PASS |
| DENSITY 0 silences the channel **and draws its tab dashed** | PASS |
| Peak meters move with audio; a silent channel's bar does not flicker | PASS — confirms the mixer-API fix and the meter quantisation |
| Drum sample stepping on ML/MR | PASS |
| **SOLO, both gestures** | **PASS — fully characterised for the first time, see below** |
| Generated CONTROL pages built from a plugin's own ports | PASS — page appears, continuous parameters change the sound |
| Generated ALL pages (`REV`, `DLY`) | PARTIAL — delay works, reverb page is all toggles (defect 7) |
| Snapshot round trip of DENSITY | PASS — 0060 saved, restored 0060 |
| Snapshot round trip of GATE | PASS |

**Note on the stuck-note gate:** it proves the *clamp* works. It does not prove
a note may safely cross the loop point, because with the clamp in place none
ever does. Removing the clamp still requires a deliberate experiment with an
unclamped build.

---

## Defects found

**Four were fixed and re-verified on hardware the same session** — `212d886b`
and `31b4f7a`-class follow-up, both deployed. Defect numbers 1, 6, 7 and 8
below carry their verification. Defect 2 is snapshot data, 3 and 4 are recorded
by the owner's ruling, and 5 is still open.

### 1. Play chance is invisible and unrecoverable after a snapshot load — **the silent-channel law, violated by a stale-state path**

**Symptom:** channels G (LEAD) and H (PADS) were completely silent after loading
snapshot `016-techno_maschine`, while the pads showed 14 lit steps, the playhead
ran across them, the mixer showed level 100, the tab drew **solid**, and a pad
tap previewed the note correctly through the engine.

**Cause:** `setPlayChance` is a zynseq **pattern** property and is saved inside
the snapshot's `zynseq_riff_b64`. The driver does **not** persist chance in its
own state (`get_state` saves `register`, `ring`, `length`, `random`, `gate`,
`octave`, `range`, `velo`, `density` — not `chance`) and does not read it back
from zynseq on load. So after a snapshot written with chance 0, zynseq holds 0
while the driver's state dict holds its default of 100.

**Why it matters more than the silence:** the dashed-tab indicator reads the
driver's state dict, so it reports the channel as healthy. The one mechanism
this instrument has for explaining silence was itself lying, which is exactly
the failure the dashed tab exists to prevent.

**Workaround used during the test:** turn the channel's CHANCE to any *different*
value and back — `apply()` early-returns when the value is unchanged, so only a
real change writes through to zynseq.

**FIXED and VERIFIED.** `_derive_params` now reads `getPlayChance()` and
`getSwingAmount()` back from zynseq into the state dict, guarded the same way
the mixer's DPM is. Re-verified by loading `016` again: the G column now reads
`0000` and the tab draws **dashed**. The channel is still silent — correctly,
it really is at chance 0 — but the surface now says so instead of claiming
health.

### 2. Snapshot `016-techno_maschine` ships with LEAD and PADS muted

`chan_06` and `chan_07` both carry `mute: 1` in the snapshot's `zs3-0` mixer
state; every other channel has `mute: None`. It also carried **chance 0** on
both, so they were silenced twice over. Unrelated to this build — those two
channels have been silent on every load of that snapshot, however long it has
been in use.

**REPAIRED and VERIFIED 2026-08-11.** `016` re-saved with both channels unmuted
and at chance 100; loading it fresh now brings LEAD and PADS in with no
intervention.

### 3. Long notes plus repeated pitches cut each other off; swing exposes it

**Symptom:** on a voice at `1/4` with GATE at maximum, raising SWING silenced the
sequence entirely. Returning SWING to minimum restored it.

**Discriminating test:** with GATE low, swing at `1/4` plays fine. So **swing is
not the defect.**

**Cause:** with GATE 800 a note is eight steps long on a sixteen-step pattern, so
each pitch is still sounding when it comes round again. `track.cpp:186-192` adds
swing as a fraction of a step to the event offset, and the note-off is scheduled
at `(offset + duration) × clocksPerStep`. The shift is enough for a previous
instance's note-off to land after the new note-on and cut it.

**Owner's ruling:** the swing behaviour at `1/4` is musically interesting and
stays as it is. The interaction is recorded rather than fixed.

**If it is ever fixed**, the shape would be clamping a note's duration to the
gap before the next note of the same pitch — legato rather than overlap — which
is a second clamp alongside SP5's loop-point one.

### 4. A very short GATE on a slow-attack patch is inaudible

LEAD appeared to have "only a few notes" until GATE was raised. At the bottom of
its range a note is 0.05 steps, which on a patch with any attack at all never
develops. Combined with the coarser encoder resolution the widened range
introduced, the bottom of GATE is now easier to land on by accident. Not a bug;
worth knowing, and an argument for a coarse/fine split on that knob if it
annoys in practice.

### 5. Voice preset stepping on MR — unresolved

Stepping presets on channel F appeared to do nothing audible. The journal shows
`set_preset: Preset selected: BA 002 ng (9)` → `BA 003 ng (10)` → `BA 002 ng (9)`,
so the mechanism fired.

**RESOLVED — not a defect.** Re-run on LEAD from the CONTROL page: the preset
name changes and the sound changes with it. Both original suspicions were
right at once — JC303's bass patches sound near-identical, and the `PRESET`
column is not drawn on the STEP page where the first test was run.

---

### SOLO — specified by observation, 2026-08-11

The oldest unverified behaviour in this project. Both gestures work:

| Gesture | Behaviour |
|---|---|
| **Hold SOLO + Fn** | Momentary. Solos that channel; further Fn presses **accumulate** (LEAD, then LEAD+PADS); releasing SOLO restores everything |
| **Tap SOLO** | Latches — the F row becomes solos instead of mutes |
| **Tap SOLO again** | Exits; the F row returns to muting |

`zynmixer`'s solo is additive, and the surface's momentary layer sits on top of
it cleanly. No change needed. **This item is closed.**

---

### 6. Generated pages include ports no musician can use

`usable_ports` filters on "numeric with a real range", which is not the same
question as "a parameter a player can use". Host and infrastructure ports pass
it and occupy columns:

| Engine | Junk ports that take columns |
|---|---|
| Obxd | `lv2_freewheel` (drawn as `LV2_FREE`), `lv2_port_1`, `unused_1` |
| JC303 | `latency`, `freeWheeling`, `enabled` |
| padthv1 | none — its `DCF1_ENABLED` / `LFO1_ENABLED` are **genuine musical toggles and must be kept** |

**FIXED and VERIFIED.** Deny-list in `usable_ports`: symbols starting with
`lv2_` or `unused`, plus exact case-insensitive matches for `latency`,
`enabled`, `bypass`, `freewheel`, `freewheeling`. Exact matching keeps
padthv1's `DCF1_ENABLED` alive. `LV2_FREE` confirmed gone from the Obxd EXTRA
page.

### 7. A small-range port on a generated page cannot be moved at all

The `REV1` page is `combs_en`, `allps_en`, `bandpass`, `stereo_E` — TAP
Reverberator's on/off toggles, range 0-1. All four read `0100` (a toggle that is
on really is 100% of its range) and none of them can be moved.

**Cause:** the generated write path scales a 0-100 surface step back onto the
port's range, giving 0.01 per step, and `zynthian_controller._set_value()`
**truncates integer controls** — the identical trap this project hit with pan.
Continuous ports are unaffected, which is why the delay page works.

**FIXED and VERIFIED, after one wrong cut.** The first attempt classified a
port as discrete by **range width** (span ≤ 8). That caught the toggles and
also caught Obxd's `volume`, a 0.0-1.0 **float**, which then moved only between
0 and 100 — found on hardware within minutes.

The real discriminator is **integer-ness**, because `_set_value()` truncates
only integer controls. A port is discrete when it is integer **and** one percent
of its range is smaller than one unit:

```python
port_is_discrete(lo, hi, is_integer) -> is_integer and (hi - lo) < 100
```

Verified both ways on hardware: the reverb toggles step 0 ↔ 100 (correct — they
have two positions), and Obxd's volume moves smoothly again.

**Worth keeping:** TAP Reverberator publishes exactly `decay drylevel wetlevel
combs_en allps_en bandpass_en stereo_enh mode`. Four have hand-written homes, so
the REV page is *supposed* to be four toggles and nothing else. There is no
`volume` on the reverb — that column was on the Obxd page all along.

### 8. A voice's DIVIDE has never survived a snapshot load

**Symptom:** saved with a voice at `1/8`, changed it to `1/4`, reloaded — the
voice stayed at `1/4`. GATE and DENSITY restored correctly in the same test.

**Cause:** `set_state` restores the voice fields and then writes every voice's
pattern with `_write_voice_pattern`, which calls `setStepsPerBeat` /
`setBeatsInPattern` from **`self.div[channel]` — the division still in
memory**. The snapshot's division loads and is immediately overwritten by
whatever was last on the panel. `_derive_params` afterwards reads back the
*stamped* value, so the driver and zynseq agree on the wrong answer, which is
why this has gone unnoticed.

**Pre-existing**, independent of SP1 and SP5; the new `1/4` division merely made
it visible.

**FIXED and VERIFIED.** `set_state` now derives each voice's division from
zynseq *before* the rewrite. Verified by saving a voice at `1/16`, changing it
to `1/4`, and reloading: it comes back `1/16`. Before the fix it stayed `1/4`.

---

## The stability jam — PASSED 2026-08-11

Nineteen minutes of playing against the full build, exercising modes, paging,
density, gate, presets, mute and solo.

| Measure | Result | Prototype baseline |
|---|---|---|
| xruns | **0** | 0 |
| tracebacks | **0** | 0 |
| segfaults | **0** | 0 |
| driver reloads | **0** | — |
| Maschine errors | **0** | — |
| watchdog reopens | 40, one per **~30 s** | one per ~8 s healthy, 22.6 s in the prototype jam |
| MemAvailable after | 2.64 GB | 2.63 GB |

The watchdog cadence is the notable one: **~30 s between reopens against an
~8 s healthy baseline**, so the hidraw path is behaving better under this build
than it has before.

**No mean DSP load figure was taken.** The window was timestamped but JACK's
load was never sampled during the jam, so this run proves nothing failed
without establishing what it cost. Deferred by the owner to a future
measurement; the prototype's 21.1% mean remains the last real number.

**A measurement trap worth remembering:** `journalctl --since "HH:MM"` reads the
**Pi's local clock** (BST), while a baseline stamped with `date -u` on the
development machine is UTC. Mixing them silently widened the first query by two
hours and swallowed two of this session's own deploys, which then read as
driver reloads during the jam. Stamp the baseline with the Pi's own `date`.

## Still untested
- Whether a note may safely cross the loop point — needs a deliberately
  unclamped build, so it is an experiment rather than a test
- That the last step's note is audibly shorter than its neighbours — the
  clamp's visible cost. Subtle, low value, skipped by agreement: the absence of
  stuck notes already proves the clamp works
