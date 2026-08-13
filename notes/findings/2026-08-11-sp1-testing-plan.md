# SP1 + Density — Testing Plan

**Date:** 2026-08-11
**For:** the owner, at the panel, in one sitting
**State of the rig right now:** everything below is **already deployed**. The
pass-two driver, the patched daemon and snapshot 016 are live on the Pi. You do
not need to install anything.

**What was verified without you, and needs no retesting:** every button CC
(gate G4), the daemon emitting SHIFT 49 / SWING 50 / VOLUME 51, the JACK
routing, and 187 unit tests covering the page model, the column shapes and the
density mask.

**What only you can verify:** that the surface *behaves* — LEDs, screens,
encoders under the hand, and sound.

---

## How to run this

Work top to bottom. Each check is one action and one observation. Report
`ok` or `failed: <what you saw>`. A failure does not stop the run unless it
says so — skip to the next check and keep going, because a second symptom is
usually what identifies the first.

Nothing here needs SSH. If something looks wrong I will read the logs myself.

---

## Part 1 — The five modes latch `[15 checks]`

The single biggest behavioural change: three pages became five modes, and the
mode buttons are **latched and mutually exclusive**.

| # | Do | Expect |
|---|---|---|
| 1.1 | Press **CONTROL** | Its LED lights, the other four are dim |
| 1.2 | Press **STEP** | STEP lit, CONTROL dim |
| 1.3 | Press **ALL** | ALL lit, STEP dim |
| 1.4 | Press **AUTO** | AUTO lit — this is **FILTER** mode |
| 1.5 | Press **VOLUME** | VOLUME lit — this is **MIXER** mode. This button never did anything before today |
| 1.6 | Press **VOLUME** again, while lit | Returns to **CONTROL**. Pressing a lit mode is "go home" |
| 1.7 | Press **CONTROL** while it is lit | Nothing happens. CONTROL is home and has nowhere to go |

**Verify overall:** exactly one mode LED is lit at all times, and the screens
change content with each press.

---

## Part 2 — Paging with DL/DR `[the fix that G4 forced]`

**This is the check most likely to fail, and the one I most want the result
of.** Until this afternoon the driver bound paging to CC 5/6, which G4 proved
are the *transport* arrows. It now binds 47/48, the arrows beside the display.

| # | Do | Expect |
|---|---|---|
| 2.1 | Go to **MIXER** (VOLUME). Press **DR** — right arrow **beside the display** | Page indicator reads `REVERB 2/3` |
| 2.2 | Press **DR** again | `DELAY 3/3` |
| 2.3 | Press **DR** again | Wraps to `LEVEL 1/3` |
| 2.4 | Press **DL** | Wraps backwards to `DELAY 3/3` |
| 2.5 | Press **TL** or **TR** — the transport ◀STEP / STEP▶ arrows | **Nothing.** They are deliberately unbound |
| 2.6 | Go to **CONTROL**, select a **voice** (group F, G or H), press **DR** | A generated page of that synth's own ports, e.g. `EXTRA` or `EXTRA1` |
| 2.7 | Select a **drum** (A-E) in CONTROL, press **DR** | Nothing — a drum's CONTROL ring is one page long. A LinuxSampler chain publishes no ports, so there is nothing to generate |

**If 2.1 does nothing but the transport arrows page instead**, say so exactly —
it means the swap is still inverted somewhere and I have the pair backwards.

---

## Part 3 — Page memory `[3 checks]`

| # | Do | Expect |
|---|---|---|
| 3.1 | In **STEP**, select a voice, page to `CHANCE` | Indicator shows the chance spread |
| 3.2 | Select a **drum**, then select the **voice** again | You land back on `CHANCE`, not on page 1 |
| 3.3 | In **MIXER**, page to `DELAY`, switch to **FILTER**, switch back to **MIXER** | Still on `DELAY` |

---

## Part 4 — The three column shapes `[6 checks]`

| # | Do | Expect |
|---|---|---|
| 4.1 | **MIXER**, page `LEVEL` | Eight columns, one per channel, each labelled with its letter and name — `A KICK`, `F BASS` … |
| 4.2 | Turn **encoder 3** on that page | Channel **C**'s level moves, whichever channel is selected |
| 4.3 | Page to `REVERB`, turn encoder 6 | Channel F's reverb moves |
| 4.4 | Go to **FILTER** (AUTO) | The five **drum** columns read `----` and are greyed; the three voice columns show numbers |
| 4.5 | Turn an encoder over a greyed drum column | Nothing happens, silently. It is an honest dead knob, not a bug |
| 4.6 | Go to **ALL** | Eight globals as before — ROOT, SCALE, BPM, MASTER, REVSIZE, REVTYPE, DLYTIME, DLYFBK |

---

## Part 5 — Voice density `[the new feature, 7 checks]`

Built today. On a voice's **STEP** page, **encoder 7** is now `DENSITY` — it
used to be SWING.

| # | Do | Expect |
|---|---|---|
| 5.1 | Select a voice, **STEP** mode. Look at encoder 7 | Column reads `DENSITY`, value `0100` |
| 5.2 | Set that voice's DIV to 1/16 so it runs 16 steps. Listen | Sixteen notes, exactly as before today |
| 5.3 | Turn **encoder 7** down to about 50 | Roughly half the notes become rests. The line thins; it does not transpose or shift |
| 5.4 | Turn it down further, slowly | Notes keep dropping out one at a time. **Nothing that was silent should come back** |
| 5.5 | Turn it to **0** | The voice goes silent **and its tab draws dashed** — the dashed tab is the check, not the silence |
| 5.6 | Turn it back to 100 | All sixteen notes return |
| 5.7 | Set RANDOM to **LOCK** (0), then set density to 50 | The pattern of rests freezes. Repeated bars are identical |

**Why 5.4 and 5.7 matter more than the rest:** 5.4 proves the mask is ranked
rather than random, and 5.7 proves it is a function of the register — which is
the entire reason this design was chosen over per-note play chance.

---

## Part 6 — Sound stepping moved to ML/MR `[2 checks]`

| # | Do | Expect |
|---|---|---|
| 6.1 | Select a **drum**, press **MR** (master section, beside the big encoder) | Next sample in the kit |
| 6.2 | Select a **voice**, press **MR** | Next engine preset. Give it a moment — preset loads are deferred off the MIDI thread deliberately |

---

## Part 7 — Peak meters `[2 checks, may legitimately do nothing]`

| # | Do | Expect |
|---|---|---|
| 7.1 | Start the sequencer. **MIXER**, page `LEVEL` | The bars move with the audio, not with the fader positions |
| 7.2 | Stop, and watch a silent channel's bar for ten seconds | It sits still. It must not flicker |

**7.1 is allowed to fail softly:** if the bars show fader position instead, the
Pi's mixer did not accept the DPM enable, and the code falls back by design.
Say which you see — it is a real result either way. 7.2 is the check that meter
quantisation stops a repaint storm.

---

## Part 8 — SOLO, the oldest unverified thing here `[4 checks]`

Never verified, on any pass. Known before you start: `zynmixer`'s solo is
**additive, not exclusive**, with a special case on the main strip that clears
every solo.

| # | Do | Expect — **record what actually happens** |
|---|---|---|
| 8.1 | Hold **SOLO**, press **F1**, then **F3**, still holding | Do both channels solo, or only the last? |
| 8.2 | Release SOLO | Do the solos clear, or persist? |
| 8.3 | Tap **SOLO** alone and release | Does the F row become solos (a latched mode)? |
| 8.4 | Clear everything | Does anything actually clear all solos? |

There is no "expected" column on purpose. This behaviour was assumed, never
designed. **Whatever you observe becomes the specification.**

---

## Part 9 — Stability `[the twenty-minute jam, optional today]`

Only if you have the time and the appetite. Same shape as the jam that passed
2026-08-11: play for twenty minutes, using mode switching and paging
throughout, then tell me. I read DSP load, xruns, memory and watchdog cadence
off the logs afterwards — you just play.

Baselines to beat: mean DSP load 21.1%, **zero** xruns, **zero** segfaults,
**zero** tracebacks, memory flat, watchdog reopens no worse than one per ~8 s.

---

## If the rig is dead when you sit down

One command, and it is the fix for the failure mode found today — a daemon
restart moves the Pads port to a new zmip slot and leaves the driver bound to
the dead one:

```bash
ssh root@192.168.2.123 'systemctl restart zynthian'
```

Wait about 40 seconds. If it is still dead, stop and tell me rather than
restarting further — the state at that moment is the diagnostic.

---

## Known-good state to compare against

| Thing | Value |
|---|---|
| Driver | pass-two, deployed 2026-08-11 16:16, loaded clean, zero tracebacks |
| Daemon | patched build, SHIFT 49 / SWING 50 / VOLUME 51 verified on the wire |
| Routing | exactly one route, `Pads MIDI → ZynMidiRouter:dev2_in` |
| Snapshot | `016-techno_maschine` |
| Backups | driver `/root/ctrldev-backup-20260811/`, daemon `/root/main.rs.b567fb0.bak` |
