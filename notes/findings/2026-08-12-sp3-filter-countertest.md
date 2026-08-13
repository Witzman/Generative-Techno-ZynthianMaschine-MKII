# SP3 Filter — Counter-Test, and Why SP3 Was Shelved

**Date:** 2026-08-12
**Status:** **SP3 shelved by the owner.** No spec, no plan, nothing built.
The owner has a different idea for the drum filter and will return to it later.
**Extends** `2026-08-11-sp3-filter-gate-results.md`, which chose MDA RezFilter.

This document exists so the measurements are not lost and the next attempt does
not re-run them.

---

## 1. Decisions taken before the shelving

Four questions were answered with the owner and stand if SP3 resumes in a
similar shape:

| Question | Answer |
|---|---|
| Per-channel filters or one on a shared drum bus | **Per channel**, all five |
| Where in the chain | **Last** — after the reverb and delay inserts, so a sweep closes the tails with the drums rather than leaving a bright reverb over dull drums |
| Surface scale | **0-127, like the voices.** CUTOFF is already an abstract 0-127 on voices, mapped per engine; drums get the same treatment with a different target. One scale across the FILTER spread page, where comparing eight channels is the whole point |
| Snapshot migration | **New snapshot `017`, built programmatically from `016`**, with `016` kept untouched as the fallback — the same method that produced `021` from `020` |

**Never decided:** how far resonance may go (see §3).

The owner also proposed, and it was deliberately split out as **SP6**: the big
rotary encoder as the current page's master. It is not filter-specific and
serves every existing spread page, so it is its own sub-project.

---

## 2. MDA RezFilter's defaults are hostile

Read from `lv2info`, not assumed:

| Port | Default | Why it matters |
|---|---|---|
| `freq` | **33** | **Below the silence cliff.** A freshly inserted RezFilter mutes the channel before anyone touches a knob |
| `env_vcf` | **70** | The envelope sweeps the filter on its own |
| `lfo_vcf` | **40** | The LFO wobbles it as well — the encoder would look broken |
| `max_freq` | **75** | Caps the opening; even at `freq` 100 the filter stays partly closed |
| `res` | **70** | Already strongly resonant |

Any build must force `env_vcf` 0, `lfo_vcf` 0, `max_freq` 100 and a sensible
`freq` before the plugin is heard.

## 3. The measurements the gate did not take

Method: the gate's own harness — white noise at RMS 0.2, seed 7, through
`lv2apply`, band energies compared. Script left at `/root/sp3_probe2.py`.

### `max_freq` barely matters

At `freq` 80 and below, `max_freq` 75 and 100 give **identical** numbers. Only
at full open does 100 gain anything: RMS 0.18967 → 0.19533, >8 kHz 36.04 →
37.62. Set it to 100 anyway; it costs nothing.

**The gate's whole sweep therefore ran at `max_freq` 75** and never measured a
fully open filter.

### The silence cliff is lower than the gate reported

| `freq` | 39 | 37 | 36 | 35 | 34 | 33 | 32 | 30 |
|---|---|---|---|---|---|---|---|---|
| RMS | 0.02941 | 0.02461 | 0.02198 | 0.01915 | 0.01603 | 0.01225 | 0.00573 | **0.00000** |

Exact digital silence arrives between 32 and 30, not at 35. **The gate's
recommended floor of 35 still stands** — at 33 the channel is already 24 dB
below open, so the difference is academic — but the cliff's real location is
recorded here rather than guessed.

### Resonance clips at the top

Peak sample value, `max_freq` 100:

| `res` | 0 | 40 | 70 | 90 | 100 |
|---|---|---|---|---|---|
| peak at `freq` 50 | 0.202 | 0.370 | 0.584 | 0.914 | **1.000, clipping** |
| peak at `freq` 60 | 0.291 | 0.622 | 0.853 | 0.994 | **1.000, clipping** |

Measured with noise at RMS 0.2; louder drum material would clip sooner. Whether
to clamp the surface below 100, allow the clipping as a musical sound, or
compensate with `output` was the open question when SP3 was shelved.

---

## 4. The counter-test: two other filters, both unverifiable

The owner asked for a counter-test before committing to RezFilter. It was worth
running — it found a better plugin on paper and a plugin that lies.

### Calf Filter — the best port design, and unmeasurable

`http://calf.sourceforge.net/plugins/Filter`. Stereo, `freq` **10-20000 Hz**,
`res` as a Q of **0.707-32**, `mode` 0-12 for several filter shapes, `inertia`
5-100 for parameter smoothing, `bypass`, and `level_in`/`level_out` for gain
compensation. **No LFO and no envelope at all**, and the defaults are benign:
2 kHz, Q 0.707, mode 0. A freshly inserted Calf Filter barely changes the sound,
where RezFilter would have muted the channel.

**It aborts `lv2apply` with `corrupted size vs. prev_size`** — heap corruption.

A block-size theory was tested and **disproved**: `lv2apply` processes the whole
file as one call and advertises no `bufsz:maxBlockLength`, so Calf might have
been allocating from a wrong assumption. It crashes identically at 1024, 4096
and 8192 frames. Not block size.

It may still be fine under jalv, which is what Zynthian uses and which supplies
a full host feature set. But it cannot be verified with the tools on this Pi,
and a plugin that corrupts a heap in one host deserves a clean bill of health
before it goes near a rig whose worst historical failure was a SIGSEGV.

### TAL Filter — runs, produces audio, and is completely inert

`urn:juce:TalFilter`. It emits `JUCE Assertion failure in
juce_LV2_Wrapper.cpp:881` and then writes a perfectly normal-looking wav file.

**Every setting produces byte-identical results:**

| cutoff | 1.00 | 0.60 | 0.40 | 0.10 | 0.00 |
|---|---|---|---|---|---|
| RMS | 0.49654 | 0.49654 | 0.49654 | 0.49654 | 0.49654 |
| 2-8 kHz | 101.52 | 101.52 | 101.52 | 101.52 | 101.52 |

Resonance 0 through 1 and filtertype 0 versus 1: identical as well. The control
ports are not reaching the plugin. The output is also amplified about 2.5x from
the RMS 0.2 input and clips throughout.

**This is the trap worth remembering: it produces output, so a check for "does
it run" passes.** Only comparing settings against each other exposes it. Script
left at `/root/sp3_tal.py`.

### TAL Filter 2 — not a filter

`urn:juce:TalFilter2` has **no cutoff port at all**: `speedfactor`,
`filtertype`, `resonance`, `depth`. It is an LFO/sequenced filter effect. The
same naming trap the gate already hit with LSP's `surge_filter_stereo`.

### The rest

`lsFilter`, `svf`, `mooglpf` and `ams vcf` are mono. Invada LPF and mod-devel
LowPassFilter have no resonance. LSP `filter_stereo` is an EQ band. All were
already rejected at the gate for these reasons.

---

## 5. Where this leaves a future attempt

RezFilter is the only candidate that can be **verified** with what is on this
Pi, and every one of its problems is bounded and fixable at build time: force
four ports, clamp the surface to 35-100, decide the resonance ceiling.

Calf Filter is the better instrument if it can be shown to behave. That check
is an in-rig test, not a `lv2apply` run.

The driver is already built for this choice to be cheap: `fx_handle`'s own
comment says an FX processor is addressed **through the chain rather than a
hard-coded plugin symbol, so swapping the plugin changes one function**. A
future swap from RezFilter to Calf is a small change, not a redesign.

**Scripts left on the Pi:** `/root/sp3_filter_probe.py`, `/root/sp3_sweep.py`,
`/root/sp3_cost.py` (from the gate), `/root/sp3_probe2.py`, `/root/sp3_calf.py`,
`/root/sp3_tal.py` (from this counter-test). All operate on scratch files in
`/tmp` and touch no Zynthian state.
