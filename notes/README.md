# notes/ — how this instrument was designed and measured

Working documents, not user documentation. The user documentation is
[`guide/`](../guide/), published at
<https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/>.

These files were written while building the instrument, between 2026-08-09 and
2026-08-13, and moved here when the project became its own repository. **They are
dated records, not living documents.** Where a note and the code disagree, the
code is right — the code shipped after most of these were written.

They are kept because several of them cost a full measurement round to produce,
and because they record decisions that would otherwise be re-litigated.

## specs/

What was decided before building, and why. The prototype design, the pass-two
design and its four sub-projects (SP1 modes and pages, SP2 live play and record,
SP4 channel-type switching, SP5 pattern time), the SFZ drum-kit design, and the
design for this repository itself.

## plans/

The task breakdowns those specs were built from.

## findings/

What the hardware actually did.

| File | Why it matters |
|---|---|
| `2026-08-10-gates-g1-g2-g3-results.md` | Two gates changed the design: the FX plugins in the spec turned out to be dry/wet crossfades, and the CPU threshold was unreachable by architecture |
| `2026-08-11-g4-capture.log` + runbook | The **measured** button CC map. Two entries had been wrong for four days because they were read out of the daemon's token names |
| `2026-08-11-sp1-sp5-test-findings.md` | 23 hardware checks, five defects |
| `2026-08-12-sp2-test-findings.md`, `2026-08-12-sp2-g5-results.md` | 8 checks, zero defects. Pad velocity is `pressure^0.4 * 127`, so the usable range is ~66-127 |
| `2026-08-12-sp4-test-findings.md` | 6 checks, zero defects |
| `2026-08-12-sp3-filter-countertest.md` | **Read this before restarting the drum filter.** It saves a full measurement round and names two plugins that pass a "does it run" check while doing nothing |
| `2026-08-11-sp3-filter-gate-results.md` | Why MDA RezFilter was chosen, and the silence cliff below `freq` 32 |
| `2026-08-10-techno-machine-manual.md` | The prototype manual. **Describes the 2026-08-10 surface** — three pages, pads that only toggle steps. Superseded by the shipped five-mode surface; kept as source material for guide section 7 |
| `po-position.md`, `dev-position.md` | The product-owner and developer positions from the design debate |
| `2026-08-09-maschine-sfz-kits-ledger.md` | Why volume and pan live on the mixer strip: `zynthian_engine_linuxsampler` defines no controllers at all |

## reference/

| File | What |
|---|---|
| `project-midi-reference.md` | The Maschine MK2 factory MIDI mode, the pad LED HSB model, and the accumulated hardware conflicts. The raw `.ncc` source it was distilled from is gone; this is what remains |
| `display-investigation.md` | How the 255×64 display protocol was worked out. The upstream source of truth is `src/devices/ni/MaschineMK2.cpp` in [shaduzlabs/cabl](https://github.com/shaduzlabs/cabl) |
| `2026-08-12-pre-move-claude-context.md` | The full working context from before the repository split, including the drum-rig era this instrument grew out of |
