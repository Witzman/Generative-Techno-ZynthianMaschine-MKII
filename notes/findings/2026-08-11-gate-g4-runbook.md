# Gate G4 — Maschine MK2 Surface Audit Runbook

**Why this exists:** every CC in the SP1 plan
(`docs/superpowers/plans/2026-08-11-techno-machine-pass-two-sp1.md`) is read out
of the daemon's source, not observed on the wire. G4 converts them from claims
into measurements. **G4 blocks deployment of pass two**, not local development.

**Access:** SSH to the Pi (`ssh root@192.168.2.123`) plus physical access to the
Maschine MK2 — steps 1, 2, 3 and 5 need someone pressing buttons.

**Status:** steps 0 and 4 ran 2026-08-11 and are recorded below. Steps 1, 2, 3
and 5 are pending — they cannot run without hands on the panel.

---

## Step 0 — Pre-flight, before any measurement

Run all four. Each has already cost this project a session.

```bash
# a. Exactly ONE devN_in on the pads port, or every pad tap doubles
ssh root@192.168.2.123 'jack_lsp -c | grep -A3 "Pads MIDI"'

# b. external_pad_leds must be true, or the first pad touch wipes group colours
ssh root@192.168.2.123 'grep -o "external_pad_leds.*" /root/zynth/MaschineMK2_linux/maschine.json'

# c. The daemon is running and its watchdog cadence is sane (~8-40 s per reopen)
ssh root@192.168.2.123 'systemctl is-active maschine-mk2; journalctl --since "-10min" | grep -c "watchdog: input stalled"'

# d. Driver load lines visible while auditing
ssh root@192.168.2.123 'systemctl set-environment ZYNTHIAN_LOG_LEVEL=20; systemctl restart zynthian'
```

### Results — 2026-08-11

| Check | Result |
|---|---|
| a. Pads MIDI routing | **FAIL, then FIXED.** `Pads MIDI` fed both `dev3_in` and `dev2_in`. **Cause: a daemon restart re-registers the a2j port and zynthian assigns it a new zmip slot, leaving the old route behind.** A `systemctl restart zynthian` reconciles it — one route, `dev2_in`, driver reloaded. Check this after *every* daemon restart, not once |
| b. `external_pad_leds` | PASS — `"external_pad_leds": true` present in `/root/zynth/MaschineMK2_linux/maschine.json` |
| c. Daemon + watchdog | PASS — `maschine-mk2` active, reopens roughly one per 30-60 s against the ~8 s healthy baseline |
| d. Log level | `ZYNTHIAN_LOG_LEVEL` is **unset** — it did not survive the reboot. Re-set it before auditing, and unset it afterwards |

---

## Step 1 — Button audit `[DONE 2026-08-11]`

Ran with `aseqdump -p 129:0` under a systemd transient unit, one press per
button, timestamped. Raw log kept at `/root/g4-capture.log` on the Pi.

**Two of the numbers this project has carried since 2026-08-08 were wrong.**

| Button | Panel location | Previously believed | **Measured** | Verdict |
|---|---|---|---|---|
| **DL / DR** | arrows beside the display | 5 / 6 | **47 / 48** | **WRONG before** |
| **TL / TR** | transport ◀STEP / STEP▶ | 48 / 47, *swallowed by the daemon* | **5 / 6, fully emitted** | **WRONG before** |
| **ML / MR** | master, beside the big encoder | 13 / 14 | 13 / 14 | correct |
| CONTROL | | 11 | 11 | correct |
| STEP | | 32 | 32 | correct |
| ALL | | 38 | 38 | correct |
| AUTO | | 37 | 37 | correct |
| SHIFT | | 49 | **49** | patch verified |
| SWING | | 50 | **50** | patch verified |
| VOLUME | | 51 | **51** | patch verified |
| GRID | | — | 4 | new |
| SCENE | 8-block | — | 25 | new |
| PATTERN | 8-block | — | 26 | new |
| PAD MODE | 8-block | — | 27 | new |
| NAVIGATE | 8-block | — | 34 | new |
| DUPLICATE | 8-block | — | 29 | new |
| SELECT | 8-block | — | 30 | new |
| SOLO | 8-block | — | 31 | new |
| MUTE | 8-block | — | 33 | new |
| **Big encoder, turn** | master | — | **15**, 8 units per detent, wraps 120 → 0 | new |
| **Big encoder, press** | master | — | **12** | new |

Every button emits a clean press (127) and release (0) pair. Nothing is
swallowed by the daemon — including TL/TR, which this project had written off
as unusable.

### Why source-reading could never have caught this

The daemon's token names are attached to the opposite physical buttons from
what they suggest: `step_left`/`step_right` (CC 5/6) are the **transport**
arrows, and `page_left`/`page_right` (CC 47/48) are the arrows **beside the
display**. Every previous conclusion in this project was derived from those
names. The 2026-08-08 note that "sample switching listened on CC 48/47, which
the daemon swallows; the display arrows send CC 5/6" is exactly backwards and
is now retracted.

### There is no VIEW button on the MK2

The daemon defines a `view` token, but the panel's 8-button block is, top to
bottom: **scene, pattern, pad mode, navigate, duplicate, select, solo, mute**.
Confirmed against the hardware by the owner. Do not go looking for it again.

### Fixed in code

`zynthian-ui` `eb26b00c` — `CC_DL = 47`, `CC_DR = 48`, and `CC_TL`/`CC_TR` = 5/6
recorded as free. Without this, paging was bound to buttons that are not where
the driver thought they were.

---

## Step 1 (original procedure, retained for re-runs)

Find the port, then dump it:

```bash
ssh root@192.168.2.123
jack_lsp | grep -i pads
jack_midi_dump "a2j:maschine rs [129] (capture): Pads MIDI"
```

Press each button **once, alone**, and record what arrives. This settles which
physical pair emits CC 5/6 — the driver's old constant was named
`CC_PAGE_LEFT`, while `CLAUDE.md` calls that pair the arrows beside the display.
The owner's names are authoritative; the table below is what the driver now
assumes.

| Button | Owner's name | Assumed CC | Observed CC | Release event? | Notes |
|---|---|---|---|---|---|
| Arrows beside the display, left / right | **DL / DR** | 5 / 6 | | | Bound to page stepping |
| Master section, beside the big encoder | **ML / MR** | 13 / 14 | | | Bound to sound stepping |
| Transport ◀STEP / STEP▶ | **TL / TR** | 48 / 47 | | | Expected **swallowed** by the daemon for its own page indicators — confirm nothing arrives |
| CONTROL | | 11 | | | Mode |
| STEP | | 32 | | | Mode |
| ALL | | 38 | | | Mode |
| AUTO | | 37 | | | Mode — FILTER |
| VOLUME | | 51 | | | Mode — MIXER. **Needs the Task 10 patch deployed** |
| SWING | | 50 | | | Needs Task 10 |
| SHIFT | | 49 | | | Needs Task 10 |
| MUTE | | | | | Record whatever it sends |
| GRID | | | | | SP4 gesture |
| SELECT | | | | | |
| VIEW | | | | | |
| PAD MODE | | | | | Gated by SHIFT inside the daemon |
| NAVIGATE / NAV | | | | | |

Record the **physical location** of every button that emits, not only its label —
the panel silkscreen, the daemon's token names and the driver's constant names
have all disagreed with each other before.

---

## Step 2 — AUTO reachability `[DONE 2026-08-11]`

- [x] CC 37 on press, CC 37 on release, clean single pair. FILTER mode has a
      working button.
- [ ] The FILTER mode LED lights — deferred to the SP1 testing pass, since the
      driver that draws it is not deployed yet.

---

## Step 3 — Post-patch check `[mostly DONE 2026-08-11]`

`MaschineMK2_linux` `39c4503` (Task 10) deployed to the Pi and rebuilt there.

- [x] SHIFT emits CC 49 on press and release
- [x] SWING emits CC 50 on press and release
- [x] VOLUME emits CC 51 on press and release
- [ ] **PAD MODE still behaves.** Its CC (27) was captured, but whether SHIFT
      still gates the daemon's own PAD MODE handling was not exercised. Carry
      into the SP1 testing pass

### Deployment notes learned doing it

**The Pi's `MaschineMK2_linux` git HEAD is `7038f60`, an old display
experiment, and the deployed code exists only as uncommitted working-tree
changes** — byte-identical to WSL's `b567fb0`, verified file by file. A
`git reset --hard` or a bundle fetch-and-checkout there would have destroyed
the working daemon. **Deploy by copying the changed file, not through git**,
until the Pi's repo is reconciled. The pre-patch `src/main.rs` is backed up at
`/root/main.rs.b567fb0.bak`.

**Restart order is daemon first, UI second.** Restarting `maschine-mk2` alone
makes a2j re-register the Pads port, zynthian assigns it a *new* zmip slot, and
the ctrldev driver stays bound to the dead one — the rig goes silent with no
error. `systemctl restart zynthian` afterwards rebinds it. This is also what
cleared the double-route in step 0a.

---

## Step 4 — Symbol audit `[done 2026-08-11]`

```bash
ssh root@192.168.2.123 'nm -D --defined-only /zynthian/zynthian-ui/zynlibs/zynmixer/build/libzynmixer.so | awk "\$2==\"T\"{print \$3}" | sort'
ssh root@192.168.2.123 'nm -D --defined-only /zynthian/zynthian-ui/zynlibs/zynseq/build/libzynseq.so  | awk "\$2==\"T\"{print \$3}" | sort'
```

### Mixer — the Pi runs an **older API than this checkout**

| Symbol | On the Pi | Note |
|---|---|---|
| `enableDpm` | **yes** | |
| `getDpm`, `getDpmHold`, `getDpmStates` | **yes** | All return **dBFS** (`convertToDBFS` in `mixer.c`) |
| `updateDpmStates` | **no** | This is what the WSL checkout's Python wrapper calls |

The Python side differs too, and this matters more than the C symbols:

| | WSL checkout | The Pi |
|---|---|---|
| Module | `zynlibs/zynmixer/zynmixer.py` | `zyngine/zynthian_engine_audio_mixer.py` |
| Read | `update_dpm_states()` fills `mixer.dpm`, a `DPM` array of `(a, b, a_hold, b_hold, mono)` | `get_dpm_states(start, end)` → `[[a, b, hold_a, hold_b, mono], …]` |
| Enable | `enable_dpm(enable)` | `enable_dpm(start, end, enable)` |

**Consequence, and it was silent:** Task 8's `_meter_frac` guarded on
`hasattr(mixer, "update_dpm_states")`, which is False on the Pi, so the mixer
meter would have degraded to fader position on the only machine that runs it —
with no error anywhere. `enable_dpm(True)` would additionally have raised
`TypeError` into a swallowing `except`. Fixed in `zynthian-ui` `f1c98493`: the
driver now tries the new API, falls back to the old one, and only then gives up.

- [x] Decision recorded: **the meter works on the Pi's API**, no feature is
      dropped. If a future Zynthian update moves to the newer wrapper, the same
      code takes the first branch and keeps working.

### Sequencer — everything pass two and SP2 need is present

`addNote` is `_ZN7Pattern7addNoteEjhhff` — **five arguments** (`step, note,
velocity, duration, offset`). Also present, all of which pass two or SP2 reach
for: `setPlayChance` / `getPlayChance`, `setNotePlayChance` /
`getNotePlayChance`, `setSwingAmount` / `setSwingDiv`, `setStutterCount` /
`setStutterDur`, `changeStutterCountAll` / `changeStutterDurAll`.

**RATCHET is unblocked** — `setStutterCount` exists on the installed library.

---

## Step 5 — SOLO gestures `[pending — needs button presses]`

The oldest unverified claim in the project. Know before pressing: `zynmixer`'s
solo is **additive, not exclusive**, and it has a special case at
`MAX_NUM_CHANNELS - 1` where the main strip clears every solo.

- [ ] Hold SOLO, press F1, then F3. Record: do **both** channels solo, or only
      the last pressed?
- [ ] Release SOLO. Record whether the solos clear (momentary) or persist
      (latched)
- [ ] Tap SOLO alone. Record whether the F row becomes solos
- [ ] Press the main strip's solo. Confirm it clears every solo

Whatever is observed is the specification — the surface behaviour was never
designed, only assumed.

---

## Deployment notes

These have all bitten before. None is optional.

**Moving commits to the Pi.** The Pi cannot fetch from GitHub — root has no
auth. Bundle on WSL, fetch on the Pi:

```bash
# WSL
cd ~/zynth/MaschineMK2_linux && git bundle create /tmp/mk2.bundle main
scp /tmp/mk2.bundle root@192.168.2.123:/tmp/

# Pi
cd /root/zynth/MaschineMK2_linux
git fetch /tmp/mk2.bundle main:refs/remotes/origin/main && echo FETCH_OK
```

**Check the fetch exit status.** A bare `git reset --hard origin/main` once
rewound the tree on the Pi because the fetch had silently failed.

**After any reset on the Pi**, re-set `"external_pad_leds": true` in
`/root/zynth/MaschineMK2_linux/maschine.json`. It is not in git there, and
without it the first pad touch destroys the driver's per-group colours.

**After any Zynthian update**, re-run
`~/zynth-docs/tools/patch-autoconnect-maschine.py`. Without it Zynthian never
gives the daemon's virtual port a zmip slot, the driver is "Found" but never
"Loaded", and the rig does nothing at all with no error.

**Before trusting any measurement**, re-check step 0a. `jack_lsp -c | grep -A3
"Pads MIDI"` must show exactly **one** `devN_in`.

**After the audit**, unset the log level:
`systemctl unset-environment ZYNTHIAN_LOG_LEVEL`.

---

## What G4 does not cover

G5 runs after deployment and is separate: DSP load mean and p95, xrun count,
segfault and traceback count, memory over twenty minutes, watchdog reopen
cadence against the ~8 s healthy baseline, plus a mixer-mode check that meter
quantisation really does stop the repaint storm — hold a page still on a silent
channel and watch the OSC volume.
