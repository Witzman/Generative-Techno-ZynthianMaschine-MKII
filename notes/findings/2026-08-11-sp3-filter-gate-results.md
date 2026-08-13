# SP3 Gate — The Drum Filter: plugin choice, measured

**Date:** 2026-08-11
**Status:** gate passed, plugin chosen, **SP3 not yet specced or built**
**Unblocked by:** the Pi coming back online. SP3 was recorded as "blocked on the
Pi being connected" since 2026-08-10; this is the measurement that was waiting.

---

## 1. Why a filter plugin at all

Drum channels have no filter today and cannot get one from the engine. That is
a measured dead end, not an omission:

- FluidSynth's CC 74/71 are **unipolar SoundFont modulators** that can only
  *add* to `initialFilterFc`, and `FluidDrums.sf2` ships wide open at 13500
  cents — the knob can never be audible.
- LinuxSampler, which the shipped SFZ kits use, **defines no controllers at
  all** (`_ctrls = []`).

So FILTER mode's five drum columns render greyed. SP3 fills them with a real
LV2 filter insert per drum chain.

---

## 2. Candidates surveyed

Everything filter-shaped installed on the Pi, judged on: stereo in/out, a real
cutoff **and** resonance, and cost.

| Plugin | Cutoff | Resonance | Stereo | Verdict |
|---|---|---|---|---|
| **MDA RezFilter** | `freq` 0-100 | `res` 0-100 | yes | **chosen** |
| Invada LPF (stereo) | `freq` 20-20000 Hz | **none** | yes | no resonance — a techno filter without resonance is a tone control |
| TAL Filter | `cutoff` 0-1 | `resonance` 0-1 | yes | viable second choice; JUCE-hosted, heavier |
| LSP `filter_stereo` | equalizer-shaped | — | yes | an EQ band, plus FFT graph ports that cost CPU for a display nobody sees |
| LSP `surge_filter_stereo` | — | — | yes | **not a filter** — a surge/limiter. The name misleads |
| ams `mooglpf` | `frequency` −6..6 (volts) | `resonance` 0-1 | **mono** | CV-style modular port, mono |
| swh `svf` | `filt_freq` 0-**6000** | `filt_q`, `filt_res` | mono | 6 kHz ceiling, mono |
| mod-devel LowPassFilter | `Freq` 20-20000 | **none** | mono | no resonance |

**MDA RezFilter wins on a detail that matters to this driver:** its `freq` and
`res` are already **0-100**, the exact surface units the encoders and
`techno_lib` use. No scaling table, no range mapping, no truncation trap.

---

## 3. Does it actually filter? Measured

White noise through `lv2apply`, env and LFO zeroed (`env_vcf 0`, `lfo_vcf 0`),
band energy compared. This is the same method that caught the dry/wet trap at
G3, run here because a filter that cannot be swept is the FluidSynth dead end
again.

| freq | res | RMS | 50-200 Hz | 2-8 kHz |
|---|---|---|---|---|
| 100 | 0 | 0.18967 | 39.64 | 38.24 |
| 80 | 0 | 0.14087 | 39.64 | 34.37 |
| 60 | 0 | 0.07226 | 39.59 | 16.13 |
| 50 | 0 | 0.05161 | 39.46 | 6.87 |
| 45 | 0 | 0.04190 | 39.23 | 3.45 |
| 40 | 0 | 0.03164 | 38.40 | 1.22 |
| 35 | 0 | 0.01915 | 32.30 | 0.17 |
| **30** | 0 | **0.00000** | **0.00** | **0.00** |
| 20 | 0 | 0.00000 | 0.00 | 0.00 |
| 0 | 0 | 0.00000 | 0.00 | 0.00 |

A clean, monotonic lowpass sweep from 100 down to 35: the low band holds while
2-8 kHz falls from 38.24 to 0.17.

**Resonance is real and audible**, which is what separates a filter from a tone
control:

| freq | res | 2-8 kHz |
|---|---|---|
| 60 | 0 | 16.13 |
| **60** | **80** | **54.27** |

A resonant peak more than three times the flat response at the same cutoff.

---

## 4. The trap — and it is the one this project has a law about

**Below `freq` 35, MDA RezFilter emits exact digital silence.** Not a steep
roll-off: `RMS 0.00000`, both bands zero.

A knob swept to its bottom would therefore kill the channel outright, with the
engine healthy and nothing on the surface saying why — the identical failure
that play chance 0 produced, which cost a jam and produced the dashed-tab rule.

**SP3 must clamp `freq` to a floor of 35 on the surface**, mapping the
encoder's 0-100 onto the plugin's 35-100. The bottom of the knob is then a very
closed filter, which is musically what "closed" should mean, rather than a mute
wearing a filter's name.

Whether the cliff is a denormal collapse or the plugin's own design was not
investigated: the clamp makes it unreachable either way, and the effort belongs
in SP3's build, not in this gate.

---

## 5. Cost — five more hosts

Five `jalv` RezFilter instances, idle, against the live rig with snapshot 016
loaded:

| Measure | Result |
|---|---|
| CPU, five instances, idle, over 20 s | **4.60% of one core** |
| xruns during the test | **zero** |
| Instances that started and stayed up | 5 / 5 |

This lands exactly where G1 predicted: sixteen jalv hosts cost 16.5% of a core
doing nothing, so five cost about 5% before processing a single sample. **The
host is the cost, not the DSP** — the same conclusion G1 reached, now confirmed
at a different instance count.

**Memory: do not trust a sum of RSS.** The probe reported 587.9 MB across the
five processes, which is wrong as an incremental figure — every jalv maps the
same shared libraries and summing RSS double-counts them. G1's honest method is
the **MemAvailable delta**, which gave −177 MB for sixteen hosts, so five is
roughly **55 MB**. Re-measure with MemAvailable when SP3 is built; never quote
the RSS sum.

---

## 6. What this gate does not settle

- **Where the filter sits in the chain.** Per-drum-chain insert (five hosts,
  5% of a core) versus one filter on a shared drum bus (one host, but the five
  drums stop being independently filterable). The spec's fallback is the bus;
  this gate shows the per-chain option is affordable, so it is a design choice
  and not a cost-forced one.
- **Audibility on real drum material.** Noise proves the filter works; it does
  not prove 35-100 is a *musically* useful sweep on a kick.
- **Interaction with the sixteen existing inserts.** The rig already runs
  sixteen jalv hosts; five more takes it to twenty-one.

---

## 7. Reproducing

Scripts left on the Pi: `/root/sp3_filter_probe.py` (band sweep),
`/root/sp3_sweep.py` (fine sweep plus resonance), `/root/sp3_cost.py` (the five
-host cost test, which cleans up after itself).

`lv2apply` takes its options **before** the plugin URI and uses `-c SYM VAL`,
not `-p`. Both mistakes cost a run here.
