# Documentation restructure — audience tracks, sources out of the repo

**Date:** 2026-08-13
**Status:** design, agreed with the owner in brainstorming
**Supersedes:** decision D2 of `2026-08-13-generative-techno-repo-design.md`
("documentation is Markdown source **and** generated HTML"), and the seven-section
plus two-appendix structure that spec set out

---

## 1. Goal

Two problems, one restructure.

**The repository carries source it does not need to publish.** `guide/*.md` and
`tools/generate-html.py` exist only to produce `docs/`. A reader gets nothing from
them and every guide edit costs two committed trees.

**The guide addresses the wrong reader.** 8,818 words written as one continuous
build narrative, aimed at someone who will read all of it in order. That reader is
rare. Three real ones exist, and the guide serves none of them well:

| # | Reader | Wants | Gets today |
|---|---|---|---|
| 1 | **The machine owner.** Owns a Maschine MK2, maybe a Pi. Has never configured or developed anything | It running, fast | Seven sections of rationale before the first sound |
| 2 | **The tech-affine user** doing a manual install | Small, fast, step-by-step: what, why, how | Correct steps buried in ~170 words of prose each |
| 3 | **The tech-interested reader** | What is inside the driver, the router, the snapshot | Scattered across section 1, appendix A1 and nothing else |

After the restructure: sources live outside the repo, the repo publishes HTML only,
and the site is organised by reader rather than by build order.

---

## 2. Decisions taken

| # | Decision | Rationale |
|---|---|---|
| D1 | Markdown sources and the generator move to `~/technomaschine/guide-src/`, **outside every repository** | The repo publishes the artefact, not the means of producing it |
| D2 | The repo keeps `README.md` and `docs/` and nothing else documentation-wise | One place to look; nothing to keep in sync |
| D3 | `docs/` stays **multi-page with search**, generated exactly as it is today | The generator already builds nav, prev/next and a search index. Hand-edited HTML would lose search and drift the sidebar across pages |
| D4 | Five sections, ordered by audience, not by build order | See §4 |
| D5 | Prose cut from 8,818 to ~2,900 words (150 + 350 + 550 + 850 + 1,000, `§3` unchanged); reference tables carry what sentences carried | Cut depth is the author's call, taken per section in §4 |
| D6 | `§3 Playing` stays a placeholder until the surface stops moving | The gestures still change; a manual written now would be wrong on publication, exactly as the 2026-08-10 prototype manual already is |
| D7 | New `bootstrap.sh` — one `curl \| bash` line on the Pi | Audience 1 cannot be asked to clone, read and sequence ten steps |
| D8 | No prebuilt daemon binary and no SD image | Both were considered and rejected: a release process and a redistribution question for a project that has neither yet |
| D9 | Guide sources are **not version-controlled**, by explicit owner decision | See §8, risk R1. Raised, weighed, accepted |

---

## 3. Layout

```
~/technomaschine/
    CLAUDE.md · project_status.md · todo.md
    guide-src/                     ← NEW. Sources. Outside every repo, unversioned
        00-start.md
        01-fast-installation.md
        02-features.md
        03-playing.md
        04-manual-installation.md
        05-internals.md
        a1-touchscreen-patch.md
        generate-html.py           ← moved from the repo's tools/
    legacy/                        ← untouched: the 2026-08-13 fork bundle, smc_pad
    Generative-Techno-ZynthianMaschine-MKII/
        README.md                  ← links to the Pages site
        bootstrap.sh               ← NEW, beside install.sh
        docs/                      ← GENERATED ONLY. Committed. Pages serves it
        …                          ← guide/ gone, tools/generate-html.py gone
```

### The workflow, which becomes a rule

```
edit ~/technomaschine/guide-src/*.md
python3 ~/technomaschine/guide-src/generate-html.py
commit and push docs/ in the repo
```

**`docs/*.html` is never hand-edited.** The generator overwrites every page on
every run, so a hand edit is lost silently at the next publish. **`guide/` is never
re-added to the repo.**

### Generator changes — three edits, no rewrite

```python
SRC_DIR = Path(__file__).parent
OUT_DIR = Path(__file__).parent.parent / "Generative-Techno-ZynthianMaschine-MKII" / "docs"

SIDEBAR = [
    ("Get started",  [("1 · Fast installation",    "01-fast-installation.html"),
                      ("2 · Features",             "02-features.html"),
                      ("3 · Playing",              "03-playing.html")]),
    ("Going deeper", [("4 · Manual installation",  "04-manual-installation.html"),
                      ("5 · Internals",            "05-internals.html")]),
    ("Appendix",     [("Touchscreen patch",        "a1-touchscreen-patch.html")]),
]
```

The landing copy changes from `01-what-it-is.html` to `00-start.html`. Search index,
prev/next links, mermaid rendering and styling are untouched.

---

## 4. The five sections

```
§1  Fast installation (Recommended)   audience 1    WHAT only        ~350 w + commands
§2  Features                          everyone      WHAT it does     ~550 w + 2 tables
§3  Playing                           everyone      PLACEHOLDER      unchanged
§4  Manual installation               audience 2    WHAT/WHY/HOW     ~850 w + commands
§5  Internals                         audience 3    WHY/HOW deep     ~1,000 w + tables
```

`00-start.md` is a ~150-word landing: what the instrument is in three sentences,
then three links that let a reader self-sort.

### §1 Fast installation (Recommended)

No explanations, no alternatives, no choices. A hardware checklist table, then
numbered actions: confirm the Pi is on the network, flash the image, boot, find the
IP, ssh in, run the one command, load the snapshot on the touchscreen, press Play.
Closes with a three-row *nothing happened?* table.

If a step needs a *why*, the why belongs in §4. Stated plainly in §1: the cargo
build takes about ten minutes on a Pi 4 and looks like a hang, and the last two
steps need the touchscreen because snapshots load nowhere else.

**Source:** today's `02` (condensed to four lines), `03`'s scripted equivalent,
`05` step 1.

### §2 Features

What the instrument does, in capability terms. No gestures, no build detail.

- The eight channels — table: five euclidean drums, three Turing voices, engine and role
- The generator owns the pattern: hits, rotation, chance and swing are set; the
  driver writes real notes into Zynthian's own zynseq, so patterns persist in
  snapshots and the touchscreen pattern editor mirrors the pads
- The Turing machine: a register clocked once per pass, mutated one bit at a time,
  read as pitch; `LOCK` freezes a phrase worth keeping
- Five surface modes — table: CONTROL / STEP / ALL / MIXER / FILTER and what the
  eight encoders mean in each
- Channel kind is switchable: a drum kit can take the Turing generator, a synth can
  take euclid as a root pulse, without swapping engines
- Live capture: REC overdubs into the generator's own pattern, and a captured note
  transfers pattern ownership to the player
- Per-channel sound: level, reverb send and delay send on every channel of both
  kinds; a filter per drum chain
- The surface talks back: both displays, per-group pad LEDs, and a dashed tab that
  marks a channel silenced by chance 0
- What it is not: no song mode, no pattern chaining, no sampling; eight channels,
  always alive, nothing created or torn down while playing

**Every claim is checked against `project_status.md`'s "What shipped" before it is
written.** A features page that promises what the driver does not do is worse than
no features page.

**Source:** today's `01`, plus the capability half of the `07` outline.

### §3 Playing — placeholder, moved unchanged

Keeps the honest "not written yet", the pointer to the 2026-08-10 prototype manual
with its staleness warning, and the "what will go here" outline. **One fix:** the
stub cites `docs/superpowers/techno-machine/2026-08-10-techno-machine-manual.md` in
the `zynth-docs` repository, a path that no longer holds it. It becomes
`notes/findings/2026-08-10-techno-machine-manual.md` in this repo.

### §4 Manual installation

Every step gets exactly three lines before its command:

- **What** it does
- **Why** it is needed — the trap it avoids, where there is one
- **How** to confirm it worked — the expected output

The ten daemon and driver steps stay ten steps; they are irreducible. Each drops
from ~170 words to ~40. Closes with a merged symptom → cause → fix table.

**Source:** today's `02`, `03`, `04`, `05` and the machine-checkable half of `06`;
troubleshooting merged from `03`'s "when it does not work" and `05`'s "when a
channel is silent".

### §5 Internals

- Signal path diagram: HID → daemon → a2j → zmip → ctrldev driver → zynseq
- Why `zynautoconnect` needs patching and what the patcher does
- The driver: the generator-owns-the-pattern model, the five modes, the threading
  rule and why every zynseq call holds the lock
- Snapshot `017`: the chain table, the insert pair, gain staging, and building
  sixteen inserts without placing sixteen processors

**Source:** today's `01` signal path, appendix `A1` condensed. Appendix `A2`
becomes `a1-touchscreen-patch.md`, its own page, unchanged in substance.

---

## 5. `bootstrap.sh`

`install.sh` already performs nine of the ten steps and is idempotent throughout.
The bootstrap is a front end, not a second installer. It adds only what `install.sh`
deliberately omits: getting the repository onto the Pi, placing the snapshot, and
verifying.

```bash
curl -sSL https://raw.githubusercontent.com/Witzman/Generative-Techno-ZynthianMaschine-MKII/main/bootstrap.sh | bash
```

| # | Step | Why it is not in `install.sh` |
|---|---|---|
| 1 | Refuse unless `/zynthian/build_info.txt` exists and uid is 0 | Same guard, restated before anything is downloaded |
| 2 | `git clone`, or `git pull` if the directory exists, to `/root/Generative-Techno-ZynthianMaschine-MKII` | `install.sh` presumes the repo is already on the Pi |
| 3 | Run `./install.sh` | Called, never duplicated |
| 4 | Copy `snapshot/017-generative-techno.zss` to `/zynthian/zynthian-my-data/snapshots/000/` | Guide §5 step 1, today a manual `scp` from the laptop. The bank subdirectory is not optional — a snapshot at the snapshots root is invisible in the UI |
| 5 | `bash tools/check-prereqs.sh` and the two grep checks | `install.sh` explicitly verifies nothing |
| 6 | Print the two remaining human actions | Loading a snapshot is touchscreen-only and cannot be automated |

**Anonymous GitHub access from the Pi is verified, not assumed.** Measured
2026-08-13: `curl -sI` on `raw.githubusercontent.com` returns `HTTP/2 200` and
`git clone --depth 1` of the public repo succeeds as root. CLAUDE.md's "the Pi
cannot fetch from GitHub" is about *authenticated* fetches of the owner's forks and
does not apply here.

**Safety:** the whole body sits in `main() { … }` with `main "$@"` as the last line,
so a truncated download executes nothing. `set -eu`. `--dry-run` passes straight
through to `install.sh`. Re-running is safe; every underlying step is idempotent.

---

## 6. Collateral edits

| File | Change |
|---|---|
| `README.md` | The `guide/` row in the contents table and the "Build guide" link point at the Pages site |
| `snapshot/README.md` | Three links into `guide/05`, `guide/06` and `a1` |
| `notes/README.md` | One link into `guide/`. `notes/specs/` and `notes/plans/` are **not** rewritten — they are dated records of what was decided when, and `guide/` was real at the time |
| `install.sh` line 3 | Comment naming `guide/03-install-driver.md` |
| `CLAUDE.md` | Publishing rule replaced by §3's workflow; `guide-src/` added to the layout map with its unversioned warning; `guide/` removed from the repo tree; "site generator" dropped from the `tools/` line; the Pi/GitHub trap gains the measured anonymous-clone fact |
| `project_status.md` | Records the restructure and the five-section site |
| `todo.md` | One entry: write §3 Playing once the surface stops moving |

---

## 7. Verification

Nothing is called done before all five pass.

```bash
python3 ~/technomaschine/guide-src/generate-html.py          # exit 0, seven pages + search index rewritten
grep -rn "guide/" --include='*.md' --include='*.sh' --include='*.py' \
     ~/technomaschine/Generative-Techno-ZynthianMaschine-MKII # only notes/specs/ + notes/plans/
python3 -m http.server -d docs 8080                          # every sidebar link followed, one search run
cd ctrldev && python3 -m unittest discover -s tests -q       # 271 tests, OK, untouched
ssh root@192.168.2.123 'bash bootstrap.sh --dry-run'         # on the real Pi, changes nothing
```

`bootstrap.sh` is **not** run for real on the owner's Pi without asking: it restarts
`maschine-mk2` and `zynthian` on a rig that gets played.

---

## 8. Risks, accepted

| # | Risk | Decision |
|---|---|---|
| R1 | Guide sources are unversioned and single-machine. Lose `guide-src/` and only the HTML survives; no second machine can edit the guide | Accepted by the owner. `git init` with no remote was offered and declined |
| R2 | Nine published URLs die — `03-install-driver.html` and its siblings. No redirect stubs | Accepted. The site is days old and nothing links into it |
| R3 | A hand edit to `docs/*.html` is silently lost at the next generator run | Mitigated by the rule in §3 and by CLAUDE.md carrying it |
| R4 | §2 Features can drift from what the driver actually does | Mitigated by checking every claim against `project_status.md` when written, and by keeping gestures out of §2 entirely |
| R5 | `bootstrap.sh` hides the cargo build; a reader may kill it thinking it hung | Mitigated by §1 and the script both stating the ten-minute expectation before it starts |

---

## 9. Sequencing

Four repository commits, each independently sound. Edits inside `guide-src/` are not
commits — that tree is unversioned by D9.

1. Remove `guide/` and `tools/generate-html.py` from the repo; place both in
   `guide-src/`; repoint `SRC_DIR`, `OUT_DIR` and `SIDEBAR`
2. Rewrite the sources to the five-section plan, regenerate, commit `docs/` wholesale
3. Add `bootstrap.sh` with its `--dry-run` proof from the Pi
4. Collateral edits from §6
