# Techno Machine prototype — Gate results G1 / G2 / G3

**Date:** 2026-08-10
**Ran on:** the Pi, `ssh root@192.168.2.123`, jackd `-d alsa -d hw:Headphones -r 48000 -p 512 -n 3`
**Spec:** `docs/superpowers/specs/2026-08-10-techno-machine-prototype-design.md`
**Scripts (kept on the Pi):** `/root/g3_wet.py`, `/root/g3_scan.py`, `/root/g3_round2.py`,
`/root/g1_fxcost.py`, `/root/g2_engines.py`

> **Precondition waived by the owner, 2026-08-10.** The spec makes "move jackd to
> `hw:S2` at 44.1 kHz" mandatory before G1. The Sound Blaster is not connected;
> the owner ruled to stay on the internal card and adjust later. **Every absolute
> CPU number below is therefore taken on `hw:Headphones` at 48 kHz and must be
> re-measured before it is trusted for final headroom.** The *relative* costs —
> plugin against plugin, and the per-process floor — are properties of the plugins
> and of jalv, not of the card, and they are what the plugin choice rests on.

---

## G3 — wet parameter · **COMPLETE**

**Question:** does the wet control add wet, or crossfade the dry away?

**Method:** offline, no audio hardware. `lv2apply` renders a full-scale impulse
through the plugin. A wet path always runs through a delay line, so the first
output sample can only be the dry path: `dry_gain = |out[0]| / |in[0]|`. Sweep
the wet port min → max and watch `dry_gain` against the tail RMS (20–400 ms).
A true wet level holds `dry_gain` flat while the tail grows; a crossfade drops it
to zero.

| Plugin | wet port | dry at wet MAX | Verdict |
|---|---|---|---|
| **TAP Reverb** `tap/reverb` | `wetlevel` (dB) | 100% | **true wet level** |
| **TAP Echo** `tap/echo` | `lecholevel` / `recholevel` (dB) | 100% | **true wet level** |
| **TAL Reverb 2** `urn:juce:TalReverb2` | `wet` | 100% | **true wet level** |
| **TAL Reverb 3** `urn:juce:TalReverb3` | `wet` | 100% | **true wet level** |
| LSP `slap_delay_stereo` | `wet` | 100% | true wet level (taps need configuring) |
| MDA Ambience | `mix` | 0% | **crossfade** |
| MDA DubDelay | `fx_mix` | 0% | **crossfade** |
| MDA Delay | `fx_mix` | 0% | **crossfade** |
| CAPS PlateX2 | `blend` | 0% | **crossfade** (spec's assumption confirmed) |
| swh `lcrDelay` | `wet` | 0% | **crossfade** |
| `bolliedelay` | `mix` | 0% | **crossfade** |
| Calf VintageDelay | `amount` (+ separate `dry`) | — | **inconclusive offline** — under `lv2apply` it produces no tail and ignores `dry`; Calf needs host features `lv2apply` does not provide. Re-test under jalv if it is ever wanted |
| DISTRHO MVerb | `mix` | — | `lv2apply`: "Options feature missing" |

**Findings that change the design:**

1. **Both plugins the spec picked as the cheap starting point are crossfades.**
   MDA Ambience and MDA DubDelay fail the encoders-7/8-are-sends contract
   outright. They are out, and the "start cheap, upgrade into headroom" plan has
   to start somewhere else.
2. **TAL Reverb's `dry` port defaults to ~0.** Measured 0.0031 at default, 0.0641
   with `dry = 1.0` — it responds, but the prepared snapshot must set dry
   explicitly or the channel loses its dry signal on insert. Same class of trap as
   LinuxSampler's empty `_ctrls`: the default is not the useful value.
3. **A separate `dry` port is the structural marker to look for**, not the word
   "wet". `gverb`'s `drylevel`/`taillevel` pair and Calf's `dry`/`amount` pair are
   both true sends whose names do not contain "wet".

---

## G1 — FX cost · **COMPLETE for the plugin choice, one hardware step outstanding**

**Question:** can this Pi carry 8 channels × (reverb + delay)?

**Method:** `/root/g1_fxcost.py` launches 16 `jalv -n <name> <uri>` hosts — exactly
how `zynthian_engine_jalv` starts an LV2 — waits for all 16 to register their JACK
ports, then samples `/proc/<pid>/stat` over a window. Touches no Zynthian state.

### The finding that reshapes the gate: the per-process floor

**16 instances of a no-op plugin (`gareus nodelay`) cost 16.5% of one core.**
That is pure jalv + JACK client overhead at 512/3 — about **1.03% of a core per
process, before any DSP at all**.

**The spec's fail threshold — "more than ~10% of one core for the sixteen
inserts" — is therefore unreachable by architecture.** No plugin choice can meet
it; sixteen jalv processes cost 16.5% if they do literally nothing. The threshold
was written without this number. **It needs re-baselining, and that is an owner
decision** (see "Decisions needed" below).

### Measured cost, 16 instances each

| Plugin | 16 instances | per instance | net DSP (floor removed) |
|---|---|---|---|
| jalv floor (`nodelay`) | 16.5% | 1.03% | — |
| **TAP Echo** | 17.0% | 1.06% | **~0.03%** — effectively free |
| Calf VintageDelay | 45.4% | 2.84% | ~1.8% |
| swh `gverb` | 48.4% | 3.02% | ~2.0% |
| DISTRHO MaGigaverb | 75.8% | 4.74% | ~3.7% |
| **TAP Reverb** | 118.2% | 7.39% | **~6.4%** |
| TAL Reverb 2 | ~158%¹ | ~9.9% | ~8.9% |
| TAL Reverb 3 | 175.3% | 10.95% | ~9.9% |

¹ derived from the mixed run: 8 × TalReverb2 + 8 × TAP Echo = 87.4%.

Cross-check: 8 × TAP Reverb + 8 × TAP Echo measured **67.8%**, against 59.1 + 8.5
predicted. The per-plugin numbers are additive.

**Reverb is the whole cost.** Delay is free at TAP Echo's price.

### Mono-in reverbs are out, and it costs the cheapest option

`gverb` (2.0% DSP) and `MaGigaverb` (3.7%) are both **1 audio in / 2 out**. The
insert is **post-fader**, so it sits *after* the mixer strip's pan — a mono input
collapses the channel's pan to centre. This is the same reason the spec rejected
ZamDelay, and it removes the cheapest reverb on the list.

Stereo-in reverbs with a true wet level: **TAP Reverb (6.4%)**, TAL Reverb 2/3
(~9-10%).

### The proposed pair, and what it costs

**TAP Reverb + TAP Echo**, 8 of each:

| | |
|---|---|
| DSP | 8 × 6.4% + 8 × 0.03% ≈ **52% of one core** |
| jalv floor | 16 × 1.03% ≈ **16.5%** |
| **Total for 16 inserts** | **≈ 68% of one core = 17% of the 4-core budget** |
| jackd | 6.9% of one core |
| RSS | summed RSS reads 1.9 GB but that is shared pages counted 16 times — **MemAvailable fell by 174 MB**, which is the real cost |
| Startup, all 16 | **10.8 s**, cold — against the spec's ~15 s snapshot-load ceiling this is the number to watch |
| xruns | **0** in every run |

**Startup is the risk, not CPU.** 10.8 s for the inserts alone, before eight
LinuxSampler kits and three synth engines load, puts the prepared snapshot close
to the spec's 15 s fail threshold.

### The realistic run — **G1 PASSES**

Snapshot `021` loaded, all eight channels sounding, the sixteen inserts fed from
`zynmixer:output_01…08` in the prototype's own topology (mixer → reverb → delay,
outputs left dangling so nothing is rerouted), sampled for five minutes:

| | |
|---|---|
| **JACK DSP load** | **mean 17.5%, p95 18.0%, max 18.6%** |
| 16 FX processes | **28.24% of one core** = 7.06% of the 4-core budget |
| jackd | 2.89% of one core |
| System total | 15.34% of all four cores |
| MemAvailable delta | **177 MB** |
| **xruns** | **0** |
| Startup, 16 instances | 3.77 s warm (10.8 s cold, first load of the day) |
| Proof the rig was sounding | peak 0.2231 on `zynmixer:output_01a` |

**With real signal the sixteen inserts cost 28% of one core, not the 68% measured
with their inputs unconnected — a factor of 2.4 cheaper.** The likely cause is
denormals: a reverb integrating silence is more expensive than one integrating
music. That is a hypothesis and is not needed for the decision; the measured
figure under real conditions is the one that counts, and it is comfortable.

The threshold discussion below stands — 16 jalv processes still cost 16.5% before
any DSP — but the question it was guarding is now answered: **DSP load sits at
17.5% of the callback budget with zero xruns over five minutes.**

### Earlier, unconnected measurements

The per-plugin table above was taken with the inserts **unconnected**, processing
silence. It is still the right basis for *comparing* plugins — every candidate
was measured the same way — but its absolute numbers are 2.4× pessimistic, as the
realistic run above shows. Use it to rank, not to budget.

**Note for whoever measures next:** there is no CUIA that loads a snapshot
(`cuia_screen_snapshot` only opens the screen) and none that executes code, so
the rig has to be brought up by hand before any measurement of this kind. Confirm
it is actually sounding by measuring peak level on the sampler or mixer outputs —
`ps -o pcpu` reports the average since process start and will read ~1% on a
sampler that is playing, which is how a silent rig can look like a busy one.

---

## G2 — engines · **PASS**

**Question:** do the voice engines exist, and what do they actually expose?

**Method:** `zynthian_lv2.get_plugin_ports(url)` — the same call
`zynthian_engine_jalv.get_lv2_controllers_dict()` makes. This is what the chain
really publishes, not an `ENABLED` flag.

| Engine | Controllers | CUTOFF | RESO | ENV | DECAY / ATTACK |
|---|---|---|---|---|---|
| **JC303** (bass) | 17 | `_cutoff` | `_resonance` | `_envmod` | `_decay`, `_softAttack` |
| **Obxd** (lead) | 81 | `cutoff` | `resonance` | `filterenvamount` | `decay`, `attack` |
| **padthv1** (pads) | 95 | `DCF1_CUTOFF` | `DCF1_RESO` | `DCF1_ENVELOPE` | `DCA1_DECAY`, `DCA1_ATTACK` |
| Surge XT | 777 | `surge_xt_a_filter1_cutoff` | `…_filter1_resonance` | `…_filter1_envmod` | `…_env2_decay/attack` |
| OB-Xf | 104 | `…_FilterCutoff` | `…_FilterResonance` | `…_FilterEnvAmount` | `…_AmpEnvDecay/Attack` |
| synthv1 | 150 | `DCF1_CUTOFF` | `DCF1_RESO` | `DCF1_ENVELOPE` | `DCA1_DECAY/ATTACK` |
| Nekobi | 8 | `cutoff` | `resonance` | `env_mod` | `decay` only |

**All three proposed voice engines fill all four CONTROL-page columns.** No greyed
column is needed on the voice page, and R3 is retired. The engine → symbol table
the spec asked for:

```
BASS  JC303     _cutoff  _resonance  _envmod      _decay
LEAD  Obxd      cutoff   resonance   filterenvamount  decay
PADS  padthv1   DCF1_CUTOFF  DCF1_RESO  DCF1_ENVELOPE  DCA1_ATTACK
```

Surge XT's 777 controllers make it the fallback of last resort — the symbol names
are long enough to be a liability in a 4-character value cell.

**Not yet measured:** load time and RSS per voice engine instance. Three synth
processes land on top of G1's sixteen, and startup time is already the tight
number.

### G2 addendum — a measurement trap, and the false conclusion it produced

With all three voice chains built and correctly routed, an injected note made
**only PADS sound; BASS and LEAD stayed silent.** Feeding each engine's own MIDI
input directly appeared to explain it: JC303 and Obxd seemed to answer on MIDI
channel 1 only, padthv1 being omni. A driver change was written and deployed to
translate each voice chain's channel with `zmop_set_midi_chan_trans`.

**That conclusion was wrong, and the change has been reverted.** Two faults in
the measurement produced it:

1. **The probe did not reset between channels.** The peak from the channel-1
   round was still ringing when the channel-6 round was measured, so "channel 6
   adds nothing" was read as "channel 6 is ignored". With a peak reset and a
   settle between rounds, **JC303 and Obxd both sound on their own channel and
   on channel 1 — they are omni**, like padthv1.
2. **An unconfigured device input does not route by channel.** Tracing all three
   `chN_out` ports at once showed **all eighteen injected events — from three
   different channels — arriving at one zmop**, the active chain's. Zynthian
   routes an unconfigured `devN_in` to the active chain, not per channel, so the
   test could never have reached BASS or LEAD whatever their channel behaviour.

Sequenced notes are unaffected: zynseq routes per channel, which is exactly what
the eight drum channels demonstrate every time the rig plays.

**The lesson stands even though the finding did not:** a chain that is enabled,
loaded, routed and publishing controllers can still make no sound, so verify with
a note and a level measurement. But the harness needs the same scepticism as the
system under test — reset the meter, settle between runs, and confirm the signal
path carries what you think it carries before drawing a conclusion from silence.

---

## The FX → ALL-page mapping the gates settled

| ALL page column | TAP Reverb / TAP Echo symbol | Note |
|---|---|---|
| enc 7 per channel — REVERB wet | `wetlevel` (−70…+10 dB) | true wet level |
| enc 8 per channel — DELAY wet | `lecholevel` + `recholevel` (−70…+10 dB), ganged | true wet level |
| R1 `REVSIZE` | `decay` (0…10000 ms) | |
| R2 `REVDAMP` | **no source** | TAP Reverb has no damping control. See decision 3 |
| R3 `DLYTIME` | `ldelay` (0…2000 ms) | ms, so the driver computes it from `getTempo()` — the spec anticipated this |
| R4 `DLYFBK` | `lfeedback` (0…100) | |
| dry, both inserts | `drylevel` / `dryLevel` (dB) | set once in the prepared snapshot; **must be set explicitly** |

---

## Decisions — settled 2026-08-10

1. **G1's threshold is re-baselined.** "10% of one core for sixteen inserts"
   cannot be met by any plugin, because sixteen jalv processes cost 16.5% doing
   nothing. It is replaced by **JACK DSP load plus zero xruns over a five-minute
   run**, with snapshot load time as the secondary ceiling. Measured: **17.5% DSP
   load, zero xruns.**
2. **TAP Reverberator + TAP Stereo Echo** are the insert pair. **Owner ratified,
   option (a).**
3. **`REVDAMP` becomes `REVTYPE`** — TAP Reverberator has no damping control, so
   the ALL page's R2 column addresses its `mode` instead: 43 reverb types,
   segmented. **Owner ratified, option (a).** More character than damping, and it
   costs nothing.
4. **Startup time is no longer the risk it looked like.** 3.77 s warm for the
   sixteen inserts, 10.8 s cold. The degrade to six channels stays available as
   one table edit in `techno_lib.CHANNELS` if the full snapshot crosses ~15 s.

## Precondition still outstanding

Every number here was measured on `hw:Headphones` at 48 kHz, with the owner's
explicit ruling to stay on the internal card for now. **Re-measure the realistic
run on `hw:S2` at 44.1 kHz once the Sound Blaster is connected** — the plugin
choice will not change (relative costs are card-independent) but the headroom
figure will.
