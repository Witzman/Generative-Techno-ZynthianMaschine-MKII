# Techno Machine Pass Two — SP1 Mode & Page Framework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Maschine MK2's three latched pages into five latched modes, each carrying a ring of parameter pages stepped with the DL/DR arrows, so the eight encoders can address one channel's eight parameters, one parameter across eight channels, or eight global parameters.

**Architecture:** All page structure moves into `techno_lib` as pure data and pure functions — page descriptors carrying a *shape*, rings keyed on `(mode, kind)`, a generated-ring builder that reads a plugin's ports, and the column model that renders any shape. The driver keeps `self.mode` and `self.page_idx`, dispatches encoder movement on the descriptor's shape into the existing `_verb(verb, channel, …)` path, and gains three new verb prefixes for generated plugin ports. No verb implementation changes.

**Tech Stack:** Python 3.11+ (Zynthian UI, `zyngine/ctrldev/`), `unittest`, Rust (the `MaschineMK2_linux` HID daemon), OSC to the daemon over UDP.

## Global Constraints

- **Spec:** `~/zynth-docs/docs/superpowers/specs/2026-08-11-techno-machine-pass-two-design.md`. Read it before Task 1.
- **The driver cannot be imported on WSL.** `zynthian_ctrldev_maschine_mk2.py` imports `zynlibs.zynseq`, which exists only on the Pi. Driver changes are verified with `python3 -m py_compile` plus hardware gates. **Push every piece of logic that can be pure into `techno_lib.py`, where it is unit tested.** This is why the task order is tlib-first.
- **Test command:** `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`. Baseline before any change: **118 tests, OK**.
- **Every zynseq call the driver makes must hold `self.lock`.** `libzynseq` is not thread-safe and the driver reaches it from three threads. Without the lock the whole Zynthian UI died with SIGSEGV, exit 139.
- **Never load a preset, a preset list, or an engine on the MIDI thread.** `midi_event` holds `self.lock` for the whole event and an engine load blocks on a socket for seconds. It froze the entire instrument and needed a restart. Defer to the poll thread.
- **`zynthian_controller._set_value()` truncates integer controls.** Encoder paths must step in whole controller units with the remainder carried, via the existing `_enc_steps`.
- **Any new module in `zyngine/ctrldev/` needs `dev_ids = []`.** The manager globs every `*.py` and reads `.dev_ids` off `getattr(module, module_name)`; without it the whole UI crash-loops every 14 seconds. This plan adds no new module, but do not remove the existing guards.
- **G4 (spec §7) blocks hardware deployment**, not local development. Tasks 1–9 are WSL work. Task 10 is the daemon patch. Task 11 is the G4 runbook. Nothing ships to the Pi until G4 passes.
- **Commit after every task.** The repos are `~/zynth/zynthian-ui` (branch `vangelis`) and `~/zynth/MaschineMK2_linux` (branch `main`).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `zyngine/ctrldev/techno_lib.py` | Pure page model: shapes, descriptors, rings, generated rings, column rendering, meter quantisation | Modify — the bulk of this plan |
| `zyngine/ctrldev/tests/test_techno_lib.py` | Unit tests for the above | Modify |
| `zyngine/ctrldev/maschine_mk2_lib.py` | Screen geometry and OSC packet building | Modify — add the page-label row |
| `zyngine/ctrldev/tests/test_maschine_mk2_lib.py` | Unit tests for packet building | Modify |
| `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py` | Driver: mode/page state, encoder dispatch, display wiring, LEDs, ring cache | Modify |
| `MaschineMK2_linux/src/main.rs` | Daemon: emit SHIFT/SWING/VOLUME | Modify — ~10 lines |
| `~/zynth-docs/docs/superpowers/techno-machine/2026-08-11-gate-g4-runbook.md` | The G4 surface audit, step by step | Create |

`techno_lib.py` is 253 lines today and will roughly double. That is still a focused file — it is the page model and nothing else — so it is not split. The driver is 2484 lines and grows by perhaps 120; splitting it is out of scope for this plan and would collide with SP2.

---

### Task 1: Page shapes, descriptors and rings

**Files:**
- Modify: `zyngine/ctrldev/techno_lib.py:158-162` (the `# ---- pages` section header and `PAGES`)
- Test: `zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `techno_lib.SHAPE_CHANNEL: str = "channel"`, `SHAPE_SPREAD = "spread"`, `SHAPE_GLOBAL = "global"`
  - `techno_lib.MODES: tuple[str, ...]` — `("CONTROL", "STEP", "ALL", "MIXER", "FILTER")`
  - `techno_lib.KEYED_BY_KIND: frozenset[str]` — `{"CONTROL", "STEP"}`
  - `techno_lib.page_desc(shape, title, verbs=None, verb=None) -> dict` with keys `shape`, `title`, `verbs`, `verb`
  - `techno_lib.PAGE_RINGS: dict[tuple[str, str | None], tuple[dict, ...]]`
  - `techno_lib.ring_key(mode, kind) -> tuple[str, str | None]`
  - `techno_lib.clamp_index(index, count) -> int`
  - `techno_lib.step_index(index, delta, count) -> int` — wrapping

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_techno_lib.py`:

```python
class TestPageRings(unittest.TestCase):

    def test_ring_key_drops_kind_for_modes_not_keyed_by_kind(self):
        self.assertEqual(tl.ring_key("MIXER", "drum"), ("MIXER", None))
        self.assertEqual(tl.ring_key("FILTER", "voice"), ("FILTER", None))
        self.assertEqual(tl.ring_key("ALL", "drum"), ("ALL", None))

    def test_ring_key_keeps_kind_for_control_and_step(self):
        self.assertEqual(tl.ring_key("CONTROL", "drum"), ("CONTROL", "drum"))
        self.assertEqual(tl.ring_key("STEP", "voice"), ("STEP", "voice"))

    def test_every_mode_has_a_ring_for_every_kind(self):
        for mode in tl.MODES:
            for kind in ("drum", "voice"):
                key = tl.ring_key(mode, kind)
                self.assertIn(key, tl.PAGE_RINGS, f"no ring for {key}")
                self.assertGreater(len(tl.PAGE_RINGS[key]), 0)

    def test_channel_and_global_pages_carry_eight_verb_slots(self):
        for key, ring in tl.PAGE_RINGS.items():
            for desc in ring:
                if desc["shape"] in (tl.SHAPE_CHANNEL, tl.SHAPE_GLOBAL):
                    self.assertEqual(len(desc["verbs"]), 8, f"{key} {desc['title']}")
                    self.assertIsNone(desc["verb"])

    def test_spread_pages_carry_one_verb_and_no_verb_list(self):
        for key, ring in tl.PAGE_RINGS.items():
            for desc in ring:
                if desc["shape"] == tl.SHAPE_SPREAD:
                    self.assertIsInstance(desc["verb"], str)
                    self.assertIsNone(desc["verbs"])

    def test_mixer_ring_is_level_reverb_delay(self):
        ring = tl.PAGE_RINGS[("MIXER", None)]
        self.assertEqual([d["verb"] for d in ring], ["level", "reverb", "delay"])

    def test_filter_ring_is_cutoff_reso(self):
        ring = tl.PAGE_RINGS[("FILTER", None)]
        self.assertEqual([d["verb"] for d in ring], ["cutoff", "reso"])

    def test_step_ring_keeps_its_channel_page_first(self):
        for kind in ("drum", "voice"):
            ring = tl.PAGE_RINGS[("STEP", kind)]
            self.assertEqual(ring[0]["shape"], tl.SHAPE_CHANNEL)
            self.assertEqual([d["verb"] for d in ring[1:]], ["swing", "chance"])

    def test_step_channel_page_verbs_match_the_shipped_layout(self):
        self.assertEqual(
            tl.PAGE_RINGS[("STEP", "drum")][0]["verbs"],
            ("hits", "rotate", "div", "length", "velo", "chance", "swing", None))
        self.assertEqual(
            tl.PAGE_RINGS[("STEP", "voice")][0]["verbs"],
            ("length", "div", "random", "gate", "octave", "range", "swing", "velo"))

    def test_control_channel_page_verbs_match_the_shipped_layout(self):
        self.assertEqual(
            tl.PAGE_RINGS[("CONTROL", "drum")][0]["verbs"],
            ("kit", "sample", None, None, None, "level", "reverb", "delay"))
        self.assertEqual(
            tl.PAGE_RINGS[("CONTROL", "voice")][0]["verbs"],
            ("preset", "cutoff", "reso", "env", "decay", "level", "reverb", "delay"))

    def test_all_page_one_keeps_every_shipped_global(self):
        # The four FX globals stay here. dlytime is a musical division resolved
        # against live tempo and revtype is a room index - neither is a raw
        # plugin port, so neither can move to a generated page.
        self.assertEqual(
            tl.PAGE_RINGS[("ALL", None)][0]["verbs"],
            ("root", "scale", "bpm", "master", "revsize", "revtype",
             "dlytime", "dlyfbk"))


class TestPageIndexArithmetic(unittest.TestCase):

    def test_step_index_wraps_forward(self):
        self.assertEqual(tl.step_index(2, 1, 3), 0)

    def test_step_index_wraps_backward(self):
        self.assertEqual(tl.step_index(0, -1, 3), 2)

    def test_step_index_on_a_single_page_ring_stays_put(self):
        self.assertEqual(tl.step_index(0, 1, 1), 0)
        self.assertEqual(tl.step_index(0, -1, 1), 0)

    def test_clamp_index_pulls_an_out_of_range_index_into_the_ring(self):
        self.assertEqual(tl.clamp_index(7, 3), 2)
        self.assertEqual(tl.clamp_index(-4, 3), 0)

    def test_clamp_index_of_an_empty_ring_is_zero(self):
        self.assertEqual(tl.clamp_index(3, 0), 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest tests.test_techno_lib -q`
Expected: FAIL — `AttributeError: type object 'techno_lib' has no attribute 'ring_key'`

- [ ] **Step 3: Write the implementation**

In `techno_lib.py`, replace the `PAGES = ("CONTROL", "STEP", "ALL")` line with:

```python
    # PAGES is the pass-one name and is kept so an older snapshot's saved page
    # string still validates in set_state(). MODES is what the surface uses.
    PAGES = ("CONTROL", "STEP", "ALL")

    MODES = ("CONTROL", "STEP", "ALL", "MIXER", "FILTER")

    # A page's shape decides what encoder n means. This is the whole trick:
    # three layouts, one dispatch.
    #   channel - 8 verbs, one selected channel      (today's CONTROL and STEP)
    #   spread  - 1 verb, all 8 channels             (mixer, filter, swing, chance)
    #   global  - 8 verbs, no channel                (today's ALL)
    SHAPE_CHANNEL = "channel"
    SHAPE_SPREAD = "spread"
    SHAPE_GLOBAL = "global"

    # Keying is a property of the RING, not of the shapes inside it. A ring is
    # keyed on kind when its content differs by kind. STEP is keyed on kind
    # even though its pages 2 and 3 are spread, because its page 1 is
    # channel-shaped and differs by kind: a mixed ring takes the keying its
    # page 1 requires.
    KEYED_BY_KIND = frozenset({"CONTROL", "STEP"})

    @staticmethod
    def ring_key(mode, kind):
        return (mode, kind if mode in techno_lib.KEYED_BY_KIND else None)

    @staticmethod
    def page_desc(shape, title, verbs=None, verb=None):
        """One page. `verbs` for channel and global shapes, `verb` for spread.
        `title` is what the page indicator draws."""
        return {"shape": shape, "title": title,
                "verbs": tuple(verbs) if verbs is not None else None,
                "verb": verb}

    @staticmethod
    def step_index(index, delta, count):
        """DL/DR move here. Wrapping, because a ring you cannot cycle is a
        list with a dead end at each side."""
        if count <= 0:
            return 0
        return (index + delta) % count

    @staticmethod
    def clamp_index(index, count):
        """A saved or remembered index landing in a shorter ring."""
        if count <= 0:
            return 0
        return max(0, min(count - 1, index))
```

Then, below `page_desc`, add the rings (a module-level assignment after the class body is required because `page_desc` is a staticmethod of the class being defined — put this at the very end of `techno_lib.py`, outside the class):

```python
# Rings are built after the class body so page_desc() is callable. Keeping them
# out of the class body is the only reason they are down here; they are read as
# techno_lib.PAGE_RINGS like everything else.
_d = techno_lib.page_desc
techno_lib.PAGE_RINGS = {
    ("CONTROL", "drum"): (
        _d(techno_lib.SHAPE_CHANNEL, "CTRL",
           verbs=("kit", "sample", None, None, None, "level", "reverb", "delay")),
    ),
    ("CONTROL", "voice"): (
        _d(techno_lib.SHAPE_CHANNEL, "CTRL",
           verbs=("preset", "cutoff", "reso", "env", "decay",
                  "level", "reverb", "delay")),
    ),
    ("STEP", "drum"): (
        _d(techno_lib.SHAPE_CHANNEL, "STEP",
           verbs=("hits", "rotate", "div", "length", "velo", "chance",
                  "swing", None)),
        _d(techno_lib.SHAPE_SPREAD, "SWING", verb="swing"),
        _d(techno_lib.SHAPE_SPREAD, "CHANCE", verb="chance"),
    ),
    ("STEP", "voice"): (
        _d(techno_lib.SHAPE_CHANNEL, "STEP",
           verbs=("length", "div", "random", "gate", "octave", "range",
                  "swing", "velo")),
        _d(techno_lib.SHAPE_SPREAD, "SWING", verb="swing"),
        _d(techno_lib.SHAPE_SPREAD, "CHANCE", verb="chance"),
    ),
    ("ALL", None): (
        _d(techno_lib.SHAPE_GLOBAL, "GLOBAL",
           verbs=("root", "scale", "bpm", "master", "revsize", "revtype",
                  "dlytime", "dlyfbk")),
    ),
    ("MIXER", None): (
        _d(techno_lib.SHAPE_SPREAD, "LEVEL", verb="level"),
        _d(techno_lib.SHAPE_SPREAD, "REVERB", verb="reverb"),
        _d(techno_lib.SHAPE_SPREAD, "DELAY", verb="delay"),
    ),
    ("FILTER", None): (
        _d(techno_lib.SHAPE_SPREAD, "CUTOFF", verb="cutoff"),
        _d(techno_lib.SHAPE_SPREAD, "RESO", verb="reso"),
    ),
}
del _d
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: PASS, 118 + 14 = **132 tests, OK**

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(maschine): page shapes, descriptors and rings

Three shapes - channel, spread, global - so one dispatch covers eight
parameters of one channel, one parameter across eight channels, and eight
globals. Rings keyed on (mode, kind), with mixed rings taking the keying
their page 1 requires.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Column rendering for all three shapes, page label, meter quantisation

**Files:**
- Modify: `zyngine/ctrldev/techno_lib.py:182-253` (`columns`)
- Test: `zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: `SHAPE_*`, `page_desc`, `PAGE_RINGS` from Task 1.
- Produces:
  - `techno_lib.SPREAD_SPECS: dict[str, tuple[str, callable]]` — verb → (bar kind, value→fraction)
  - `techno_lib.columns(desc, kind, state) -> list[dict]` — **signature change**: first argument is now a page descriptor, not a page-name string. For `spread`, `state` is a list of 8 `(letter, name, view)` tuples; for the other two it is a single view dict, exactly as today.
  - `techno_lib.page_label(title, index, count) -> str`
  - `techno_lib.quantise_frac(frac, steps) -> float`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_techno_lib.py`:

```python
def _drum_view(**over):
    view = dict(hits=4, rotate=0, div=1, length=16, velo=110, chance=100,
                swing=50, level=19, reverb=0, delay=0, kit="909", sample="BD",
                pending=set())
    view.update(over)
    return view


def _voice_view(**over):
    view = dict(length=8, div=1, random=0, gate=40, octave=0, range=2,
                swing=50, velo=110, level=19, reverb=0, delay=0, chance=100,
                preset="SAW", cutoff=64, reso=32, env=64, decay=40,
                pending=set())
    view.update(over)
    return view


class TestColumnsByShape(unittest.TestCase):

    def test_channel_shape_still_renders_the_shipped_step_page(self):
        desc = tl.PAGE_RINGS[("STEP", "drum")][0]
        cols = tl.columns(desc, "drum", _drum_view())
        self.assertEqual([c["name"] for c in cols],
                         ["HITS", "ROTATE", "DIVIDE", "LENGTH", "VELO",
                          "CHANCE", "SWING", "ratchet"])
        self.assertTrue(cols[7]["grey"])

    def test_global_shape_still_renders_the_shipped_all_page(self):
        desc = tl.PAGE_RINGS[("ALL", None)][0]
        state = dict(root=9, scale=0, bpm=132, master=80, revsize=25,
                     revtype=3, dlytime=1, dlyfbk=35, pending=set())
        cols = tl.columns(desc, "drum", state)
        self.assertEqual([c["name"] for c in cols],
                         ["ROOT", "SCALE", "BPM", "MASTER", "REVSIZE",
                          "REVTYPE", "DLYTIME", "DLYFBK"])

    def test_spread_shape_labels_each_column_with_its_channel(self):
        desc = tl.PAGE_RINGS[("MIXER", None)][0]
        views = [(chr(ord("A") + i), name, _drum_view(level=10 * i))
                 for i, name in enumerate(
                     ["KICK", "SNAR", "CLAP", "CHAT", "OHAT", "BASS", "LEAD", "PADS"])]
        cols = tl.columns(desc, None, views)
        self.assertEqual(len(cols), 8)
        self.assertEqual(cols[0]["name"], "A KICK")
        self.assertEqual(cols[5]["name"], "F BASS")
        self.assertEqual(cols[3]["value"], "0030")

    def test_spread_greys_a_channel_that_lacks_the_verb(self):
        # A drum has no cutoff: LinuxSampler publishes no controllers and the
        # SoundFont CC 74 route is a measured dead end. The column says so.
        desc = tl.PAGE_RINGS[("FILTER", None)][0]
        views = [("A", "KICK", _drum_view()), ("F", "BASS", _voice_view())]
        views += [("X", "----", _drum_view())] * 6
        cols = tl.columns(desc, None, views)
        self.assertTrue(cols[0]["grey"])
        self.assertEqual(cols[0]["value"], "----")
        self.assertIsNone(cols[0]["bar"])
        self.assertFalse(cols[1]["grey"])
        self.assertEqual(cols[1]["value"], "0064")

    def test_spread_swing_uses_the_shipped_swing_fraction(self):
        desc = tl.PAGE_RINGS[("STEP", "drum")][1]
        views = [("A", "KICK", _drum_view(swing=75))] * 8
        cols = tl.columns(desc, "drum", views)
        self.assertAlmostEqual(cols[0]["frac"], 1.0)

    def test_spread_chance_reads_a_voice_too(self):
        desc = tl.PAGE_RINGS[("STEP", "voice")][2]
        views = [("F", "BASS", _voice_view(chance=0))] * 8
        cols = tl.columns(desc, "voice", views)
        self.assertEqual(cols[0]["value"], "0000")
        self.assertFalse(cols[0]["grey"])


class TestPageLabel(unittest.TestCase):

    def test_single_page_ring_shows_no_position(self):
        self.assertEqual(tl.page_label("CTRL", 0, 1), "CTRL")

    def test_multi_page_ring_shows_one_based_position(self):
        self.assertEqual(tl.page_label("LEVEL", 0, 3), "LEVEL 1/3")
        self.assertEqual(tl.page_label("DELAY", 2, 3), "DELAY 3/3")


class TestMeterQuantisation(unittest.TestCase):

    def test_quantise_snaps_to_whole_pixels(self):
        self.assertEqual(tl.quantise_frac(0.5, 52), round(0.5 * 52) / 52)

    def test_two_values_inside_one_pixel_quantise_equal(self):
        # This is the whole point: a steady signal must stop repainting, or
        # mixer mode pushes ~50 OSC packets per screen per 100 ms forever.
        a = tl.quantise_frac(0.5000, 52)
        b = tl.quantise_frac(0.5090, 52)
        self.assertEqual(a, b)

    def test_quantise_clamps_out_of_range_input(self):
        self.assertEqual(tl.quantise_frac(-3.0, 52), 0.0)
        self.assertEqual(tl.quantise_frac(9.0, 52), 1.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest tests.test_techno_lib -q`
Expected: FAIL — `TypeError` on `columns()` receiving a dict where it expects a page name, and `AttributeError` for `page_label`.

- [ ] **Step 3: Write the implementation**

In `techno_lib.py`, add above `columns`:

```python
    # verb -> (bar kind, value -> 0..1 fraction). The formulas are lifted
    # verbatim from the shipped channel pages so a parameter looks identical
    # whichever shape shows it.
    SPREAD_SPECS = {
        "level":  ("uni", lambda v: v / 100.0),
        "reverb": ("uni", lambda v: v / 100.0),
        "delay":  ("uni", lambda v: v / 100.0),
        "chance": ("uni", lambda v: v / 100.0),
        "swing":  ("uni", lambda v: (v - 50) / 25.0),
        "cutoff": ("uni", lambda v: v / 127.0),
        "reso":   ("uni", lambda v: v / 127.0),
    }

    @staticmethod
    def page_label(title, index, count):
        """What the indicator row draws. A one-page ring says only its name -
        showing 1/1 on a ring that cannot move is noise."""
        return title if count <= 1 else f"{title} {index + 1}/{count}"

    @staticmethod
    def quantise_frac(frac, steps):
        """Snap a bar fraction to the bar's real pixel resolution BEFORE the
        change comparison in _render_display. Without this a live meter
        reports a new value every frame and mixer mode repaints forever."""
        frac = max(0.0, min(1.0, float(frac)))
        if steps <= 0:
            return frac
        return round(frac * steps) / steps

    @staticmethod
    def spread_columns(desc, views):
        """One verb across eight channels. `views` is eight
        (letter, name, view) tuples in channel order."""
        verb = desc["verb"]
        kind, to_frac = techno_lib.SPREAD_SPECS[verb]
        out = []
        for letter, name, view in views:
            label = f"{letter} {name}"[:8]
            value = view.get(verb)
            if value is None:
                # Law L4 again: a column whose source does not exist draws
                # dead rather than drawing a lie.
                dead = techno_lib._dead(label.lower())
                dead["name"] = label.lower()
                out.append(dead)
                continue
            out.append(techno_lib._col(label, techno_lib._num(value), kind,
                                       to_frac(value)))
        return out
```

Then change `columns`'s signature and head. Replace:

```python
    @staticmethod
    def columns(page, kind, state):
        """The 8 columns for a page. Reads state, never writes it. This is the
        single place where the greyed columns and the pending brackets are
        decided, so both are unit tested rather than eyeballed on hardware."""
        p = state.get("pending", set())
        n, c, dead = techno_lib._num, techno_lib._col, techno_lib._dead

        if page == "ALL":
```

with:

```python
    @staticmethod
    def columns(desc, kind, state):
        """The 8 columns for a page. Reads state, never writes it. This is the
        single place where the greyed columns and the pending brackets are
        decided, so both are unit tested rather than eyeballed on hardware.

        `desc` is a page descriptor. For SHAPE_SPREAD, `state` is eight
        (letter, name, view) tuples; for the other two shapes it is one view
        dict, as it has always been."""
        if desc["shape"] == techno_lib.SHAPE_SPREAD:
            return techno_lib.spread_columns(desc, state)

        page = desc["title"]
        p = state.get("pending", set())
        n, c, dead = techno_lib._num, techno_lib._col, techno_lib._dead

        if desc["shape"] == techno_lib.SHAPE_GLOBAL:
```

and change the two remaining branch tests in the body: `if page == "CONTROL":` becomes `if page == "CTRL":`, and the trailing `# STEP` branch is unchanged (it is the fall-through).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: PASS. Some pre-existing `columns()` tests will now fail because they pass a page-name string. **Update them** to pass `tl.PAGE_RINGS[(mode, kind)][0]` instead — that is the point of the signature change, not a regression. Final count: **132 + 12 = 144 tests, OK**.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(maschine): render columns for all three page shapes

columns() takes a page descriptor instead of a page name and grows a spread
branch: one verb, eight channels, each column labelled with its channel and
greyed where that channel has no such parameter.

Adds page_label() for the indicator row and quantise_frac(), which snaps a
bar fraction to real pixels so a live meter stops repainting a steady signal.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Generated parameter rings from plugin ports

**Files:**
- Modify: `zyngine/ctrldev/techno_lib.py` (append to the pages section)
- Test: `zyngine/ctrldev/tests/test_techno_lib.py`

**Interfaces:**
- Consumes: `page_desc`, `SHAPE_CHANNEL`, `SHAPE_GLOBAL` from Task 1.
- Produces:
  - `techno_lib.VERB_LV2 = "lv2:"` and `techno_lib.VERB_FX = "fx:"` — verb-name prefixes
  - `techno_lib.port_label(symbol) -> str` — 8 chars, upper case
  - `techno_lib.usable_ports(ports, exclude=()) -> list[tuple[str, float, float]]`
  - `techno_lib.generated_pages(ports, exclude, shape, verb_prefix, title) -> tuple[dict, ...]`

A **port** is a `(symbol, value_min, value_max)` tuple. The driver builds these from `proc.controllers_dict`; the pure function never sees a zctrl.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_techno_lib.py`:

```python
class TestPortFilter(unittest.TestCase):

    def test_drops_ports_with_no_range(self):
        ports = [("cutoff", 0.0, 1.0), ("bypass", 1.0, 1.0)]
        self.assertEqual([p[0] for p in tl.usable_ports(ports)], ["cutoff"])

    def test_drops_excluded_symbols(self):
        ports = [("cutoff", 0.0, 1.0), ("resonance", 0.0, 1.0)]
        got = tl.usable_ports(ports, exclude=("cutoff",))
        self.assertEqual([p[0] for p in got], ["resonance"])

    def test_drops_non_numeric_bounds(self):
        ports = [("good", 0.0, 1.0), ("bad", None, 1.0)]
        self.assertEqual([p[0] for p in tl.usable_ports(ports)], ["good"])

    def test_preserves_order(self):
        ports = [("z", 0.0, 1.0), ("a", 0.0, 1.0)]
        self.assertEqual([p[0] for p in tl.usable_ports(ports)], ["z", "a"])


class TestPortLabel(unittest.TestCase):

    def test_uppercases_and_truncates_to_eight(self):
        self.assertEqual(tl.port_label("filterenvamount"), "FILTEREN")

    def test_strips_a_leading_underscore(self):
        # JC303 publishes _cutoff, _resonance, _envmod, _decay.
        self.assertEqual(tl.port_label("_cutoff"), "CUTOFF")

    def test_short_symbol_survives_intact(self):
        self.assertEqual(tl.port_label("decay"), "DECAY")


class TestGeneratedPages(unittest.TestCase):

    def _ports(self, n):
        return [(f"p{i}", 0.0, 1.0) for i in range(n)]

    def test_no_usable_ports_yields_no_pages(self):
        # A LinuxSampler drum chain publishes nothing. Its ring stays length 1
        # and DL/DR do nothing there, which is honest.
        self.assertEqual(
            tl.generated_pages([], (), tl.SHAPE_CHANNEL, tl.VERB_LV2, "EXTRA"),
            ())

    def test_nine_ports_make_two_pages(self):
        pages = tl.generated_pages(self._ports(9), (), tl.SHAPE_CHANNEL,
                                   tl.VERB_LV2, "EXTRA")
        self.assertEqual(len(pages), 2)

    def test_a_short_final_page_is_padded_with_none(self):
        pages = tl.generated_pages(self._ports(9), (), tl.SHAPE_CHANNEL,
                                   tl.VERB_LV2, "EXTRA")
        self.assertEqual(len(pages[1]["verbs"]), 8)
        self.assertEqual(pages[1]["verbs"][1:], (None,) * 7)

    def test_verbs_carry_the_prefix_and_the_symbol(self):
        pages = tl.generated_pages(self._ports(2), (), tl.SHAPE_CHANNEL,
                                   tl.VERB_LV2, "EXTRA")
        self.assertEqual(pages[0]["verbs"][0], "lv2:p0")

    def test_fx_pages_are_global_shaped_and_carry_the_role(self):
        pages = tl.generated_pages(self._ports(2), (), tl.SHAPE_GLOBAL,
                                   tl.VERB_FX + "reverb:", "REVERB")
        self.assertEqual(pages[0]["shape"], tl.SHAPE_GLOBAL)
        self.assertEqual(pages[0]["verbs"][0], "fx:reverb:p0")

    def test_titles_number_only_when_there_is_more_than_one_page(self):
        one = tl.generated_pages(self._ports(3), (), tl.SHAPE_CHANNEL,
                                 tl.VERB_LV2, "EXTRA")
        many = tl.generated_pages(self._ports(20), (), tl.SHAPE_CHANNEL,
                                  tl.VERB_LV2, "EXTRA")
        self.assertEqual(one[0]["title"], "EXTRA")
        self.assertEqual([p["title"] for p in many], ["EXTRA1", "EXTRA2", "EXTRA3"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest tests.test_techno_lib -q`
Expected: FAIL — `AttributeError: type object 'techno_lib' has no attribute 'usable_ports'`

- [ ] **Step 3: Write the implementation**

Append inside the class in `techno_lib.py`:

```python
    # Generated pages address a plugin port directly, so their verb names carry
    # a prefix the driver's _verb() dispatches on:
    #   lv2:<symbol>          - the selected channel's synth processor
    #   fx:<which>:<symbol>   - ganged across every channel's <which> insert
    VERB_LV2 = "lv2:"
    VERB_FX = "fx:"

    PORT_LABEL_CHARS = 8

    @staticmethod
    def port_label(symbol):
        """LV2 symbols are not written for a 64 px column. Upper-case, drop a
        leading underscore, truncate."""
        return str(symbol).lstrip("_").upper()[:techno_lib.PORT_LABEL_CHARS]

    @staticmethod
    def usable_ports(ports, exclude=()):
        """Numeric ports with a real range, minus the ones that already have a
        home on a hand-written page. Order is the plugin's own."""
        out = []
        for symbol, lo, hi in ports:
            if symbol in exclude:
                continue
            if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
                continue
            if hi <= lo:
                continue
            out.append((symbol, float(lo), float(hi)))
        return out

    @staticmethod
    def generated_pages(ports, exclude, shape, verb_prefix, title):
        """Chunk a plugin's remaining ports into pages of eight.

        Generated rather than tabulated because the requirement is 'as much
        parameter control as possible' and no table here can know what JC303,
        Obxd, padthv1 or TAP Reverberator publish. A generated ring also
        survives an engine change."""
        usable = techno_lib.usable_ports(ports, exclude)
        if not usable:
            return ()
        chunks = [usable[i:i + 8] for i in range(0, len(usable), 8)]
        pages = []
        for index, chunk in enumerate(chunks):
            verbs = [verb_prefix + symbol for symbol, _, _ in chunk]
            verbs += [None] * (8 - len(verbs))
            name = title if len(chunks) == 1 else f"{title}{index + 1}"
            pages.append(techno_lib.page_desc(shape, name, verbs=verbs))
        return tuple(pages)
```

`columns()` must render these. In the `SHAPE_CHANNEL`/`SHAPE_GLOBAL` path, a verb starting with `lv2:` or `fx:` has no hand-written column, so add this immediately after the `p = state.get("pending", set())` line in `columns`:

```python
        if desc.get("generated"):
            out = []
            for verb in desc["verbs"]:
                if verb is None:
                    out.append(techno_lib._col("", "", None, 0.0))
                    continue
                symbol = verb.split(":")[-1]
                value = state.get(verb)
                if value is None:
                    out.append(techno_lib._dead(techno_lib.port_label(symbol).lower()))
                    continue
                out.append(techno_lib._col(techno_lib.port_label(symbol),
                                           techno_lib._num(value), "uni",
                                           value / 100.0))
            return out
```

and set the flag in `generated_pages` by replacing its `pages.append(...)` line with:

```python
            desc = techno_lib.page_desc(shape, name, verbs=verbs)
            desc["generated"] = True
            pages.append(desc)
```

Generated columns carry a 0–100 surface value; the driver scales that onto each port's real range, exactly as `_set_ganged` already does for the FX roles.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: PASS, **144 + 14 = 158 tests, OK**

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/techno_lib.py zyngine/ctrldev/tests/test_techno_lib.py
git commit -m "feat(maschine): build parameter pages from a plugin's own ports

CONTROL pages 2+ and ALL pages 2-3 are generated by chunking whatever the
chain publishes, minus the symbols already on a hand-written page. Neither a
table here nor the Pi being reachable is needed to know what JC303, Obxd,
padthv1 or TAP Reverberator expose.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The page-label row on the screens

**Files:**
- Modify: `zyngine/ctrldev/maschine_mk2_lib.py:249-265` (geometry), `:367-399` (`screen_packets`)
- Test: `zyngine/ctrldev/tests/test_maschine_mk2_lib.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `maschine_mk2_lib.screen_packets(screen, tabs, cols, label="")` — new optional fourth argument. New constants `LABEL_Y`, and changed `RULE_Y`, `NAME_Y`, `VALUE_Y`.

The 64 px screen has no spare row, so the layout shifts: tabs `0..12`, rule at `13`, label at `15`, names at `24`, values at `32..48`, bars at `52..62`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_maschine_mk2_lib.py`:

```python
class TestPageLabelRow(unittest.TestCase):

    def _tabs(self):
        return [("A", "KICK", True, False)] * 4

    def _cols(self):
        return [("HITS", "0004", "uni", 0.25)] * 4

    def test_label_is_drawn_when_given(self):
        packets = lib.screen_packets(0, self._tabs(), self._cols(), "LEVEL 1/3")
        self.assertTrue(any("LEVEL 1/3" in str(p) for p in packets))

    def test_no_label_draws_no_extra_text(self):
        with_label = lib.screen_packets(0, self._tabs(), self._cols(), "X")
        without = lib.screen_packets(0, self._tabs(), self._cols(), "")
        self.assertEqual(len(with_label), len(without) + 1)

    def test_label_defaults_to_empty_so_old_calls_still_work(self):
        packets = lib.screen_packets(0, self._tabs(), self._cols())
        self.assertGreater(len(packets), 0)

    def test_rows_do_not_overlap(self):
        cls = lib
        self.assertLess(cls.TAB_H, cls.RULE_Y)
        self.assertLess(cls.RULE_Y, cls.LABEL_Y)
        self.assertLessEqual(cls.LABEL_Y + 8, cls.NAME_Y)
        self.assertLessEqual(cls.NAME_Y + 8, cls.VALUE_Y)
        self.assertLessEqual(cls.VALUE_Y + 16, cls.BAR_Y)
        self.assertLessEqual(cls.BAR_Y + cls.BAR_H, 64)
```

Note: `lib` here is whatever alias the existing test file already binds `maschine_mk2_lib` to — check the file's imports and match it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest tests.test_maschine_mk2_lib -q`
Expected: FAIL — `AttributeError: … has no attribute 'LABEL_Y'`

- [ ] **Step 3: Write the implementation**

In `maschine_mk2_lib.py`, change the geometry constants:

```python
    TAB_H = 12
    RULE_Y = 13
    LABEL_Y = 15             # mode + page position, 5x8
    NAME_Y = 24              # encoder name, 5x8
    VALUE_Y = 32             # encoder value, double height
    BAR_Y = 52
```

In `screen_packets`, change the signature and add the label draw right after the rule:

```python
    def screen_packets(screen, tabs, cols, label=""):
        """Every OSC packet for one screen, in draw order.

        tabs: four (letter, name, selected, muted)
        cols: four (name, value, bar kind, bar fraction)
        label: the page indicator, e.g. "LEVEL 1/3". Empty draws nothing."""
```

and after the existing dotted-rule packet:

```python
        if label:
            out.append(cls.display_text_osc(screen, 3, cls.LABEL_Y, 1, False, label))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: PASS. Any existing test asserting the old `NAME_Y`/`VALUE_Y` numbers must be updated to the new constants — they were correct assertions about a layout that has changed. Final: **158 + 4 = 162 tests, OK**.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/maschine_mk2_lib.py zyngine/ctrldev/tests/test_maschine_mk2_lib.py
git commit -m "feat(maschine): page indicator row on both screens

A ring whose length is invisible is a ring you get lost in. The 64 px screen
had no spare row, so the layout shifts: rule 13, label 15, names 24, values
32, bars unchanged at 52.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Driver mode and page state

**Files:**
- Modify: `zynthian_ctrldev_maschine_mk2.py:330` (`self.page = "CONTROL"`), `:749-766` (`_set_page`), `:1030-1075` (`get_state`/`set_state`), `:339` (voice state init)
- Test: hardware only — see the constraint at the top. Verify with `py_compile`.

**Interfaces:**
- Consumes: `tlib.MODES`, `tlib.ring_key`, `tlib.PAGE_RINGS`, `tlib.step_index`, `tlib.clamp_index`, `tlib.page_desc`.
- Produces:
  - `self.mode: str`
  - `self.page_idx: dict[tuple[str, str | None], int]`
  - `self._ring(mode=None, kind=None) -> tuple[dict, ...]`
  - `self._page() -> dict` — the current descriptor
  - `self._set_mode(name)` — replaces `_set_page`
  - `self._step_page(delta)`

- [ ] **Step 1: Replace the page state**

At line 330, replace `self.page = "CONTROL"` with:

```python
        self.mode = "CONTROL"
        # One page index per ring, so selecting a drum and coming back to a
        # voice returns to the page you left rather than to whatever the drum's
        # shorter ring could hold.
        self.page_idx = {}
```

- [ ] **Step 2: Give voices a chance field**

At line 339, the voice branch of the state init, add `chance=100` to the `common.update(...)` call for voices. STEP page 3 is a spread of `chance` across all eight channels, and `setPlayChance` is a per-pattern property that works for voices already — only the driver's state dict was missing the key. Without this, every voice column on that page draws dead.

- [ ] **Step 3: Add the ring accessors**

Insert just above `_set_page`:

```python
    def _ring(self, mode=None, kind=None):
        """The page ring for a mode and kind, hand-written pages first and
        generated pages appended. Generated pages come from _gen_pages(), which
        caches - this runs on the MIDI thread and must never reach an engine
        load."""

        mode = self.mode if mode is None else mode
        if kind is None:
            kind = self.channel_kind(self.group)
        key = tlib.ring_key(mode, kind)
        return tlib.PAGE_RINGS[key] + self._gen_pages(mode, kind)

    def _page(self):
        """The descriptor showing right now."""

        ring = self._ring()
        key = tlib.ring_key(self.mode, self.channel_kind(self.group))
        index = tlib.clamp_index(self.page_idx.get(key, 0), len(ring))
        self.page_idx[key] = index
        return ring[index]

    def _step_page(self, delta):
        """DL / DR. Wrapping, and it recentres the encoders for the same reason
        a mode change does: the accumulated fraction belongs to the parameter
        that was under the knob a moment ago."""

        ring = self._ring()
        key = tlib.ring_key(self.mode, self.channel_kind(self.group))
        index = tlib.clamp_index(self.page_idx.get(key, 0), len(ring))
        self.page_idx[key] = tlib.step_index(index, delta, len(ring))
        self._recentre_encoders()
        self.enc_carry.clear()
        with self.lock:
            self._render_all()
```

`_gen_pages` is Task 9; until then, add a stub returning `()` so this task compiles and runs:

```python
    def _gen_pages(self, mode, kind):
        return ()
```

- [ ] **Step 4: Replace `_set_page` with `_set_mode`**

```python
    def _set_mode(self, name):
        """Latched, mutually exclusive, five of them. Pressing the lit mode
        returns to CONTROL, which is home; pressing CONTROL while lit does
        nothing. The mode buttons are deliberately NOT subject to the tap/hold
        law - a momentary mode is a mode you cannot two-hand."""

        if name == self.mode:
            if name == "CONTROL":
                return
            name = "CONTROL"
        self.mode = name
        # The encoders now mean something else, so their accumulated fractions
        # belong to the previous mode and must not leak into this one.
        self._recentre_encoders()
        self.enc_carry.clear()
        with self.lock:
            self._render_all()
```

Then update the one caller in `_midi_event` (`self._set_page(PAGE_BUTTONS[cc_num])`) to `self._set_mode(MODE_BUTTONS[cc_num])` — `MODE_BUTTONS` arrives in Task 6.

- [ ] **Step 5: Update persistence**

In `get_state`, replace `"page": self.page,` with:

```python
            "mode": self.mode,
            "pages": {f"{mode}|{kind or ''}": index
                      for (mode, kind), index in self.page_idx.items()},
```

In `set_state`, replace the three `self.page` lines with:

```python
        self.mode = state.get("mode", state.get("page", self.mode))
        if self.mode not in tlib.MODES:
            self.mode = "CONTROL"
        self.page_idx = {}
        for key, index in (state.get("pages") or {}).items():
            mode, _, kind = str(key).partition("|")
            if mode in tlib.MODES and isinstance(index, int):
                self.page_idx[(mode, kind or None)] = index
```

Reading `page` as a fallback is deliberate: a snapshot written by the shipped prototype carries `"page": "STEP"`, and those three names are also mode names, so an old snapshot restores to the right mode instead of silently landing on CONTROL.

- [ ] **Step 6: Verify it compiles**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo OK`
Expected: `OK`

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: **162 tests, OK** — unchanged, this task touches no pure code.

- [ ] **Step 7: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(maschine): five modes and a page index per ring

self.page becomes self.mode plus self.page_idx keyed on (mode, kind), so a
kind change never costs you your place. Snapshots carry both, and a
prototype snapshot's page string still restores its mode.

Voices gain a chance field: setPlayChance is per-pattern and kind-agnostic,
only the state dict was missing the key.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Button bindings — VOLUME, AUTO, DL/DR, ML/MR

**Files:**
- Modify: `zynthian_ctrldev_maschine_mk2.py:154-171` (CC constants), `:1140-1160` (`_midi_event`)
- Test: hardware (G4). Verify with `py_compile`.

**Interfaces:**
- Consumes: `_set_mode`, `_step_page` from Task 5.
- Produces: `CC_DL`, `CC_DR`, `CC_ML`, `CC_MR`, `CC_VOLUME`, `CC_AUTO`, `MODE_BUTTONS`.

- [ ] **Step 1: Rename and add the constants**

Replace the `CC_PAGE_RIGHT = 6` / `CC_PAGE_LEFT = 5` pair with:

```python
# The owner's button names, fixed 2026-08-11. The panel silkscreen, the
# daemon's token names and this driver's old constant names all disagreed with
# each other; these are authoritative.
#   DL / DR - arrows beside the display (daemon page_left/page_right, CC 47/48 - MEASURED at G4)
#   ML / MR - master section, beside the big encoder (daemon nav_*, CC 13/14)
#   TL / TR - transport ◀STEP / STEP▶ (daemon page_*, CC 48/47) - SWALLOWED by
#             the daemon for its own page indicators, never emitted, unbound.
CC_DL = 5
CC_DR = 6
CC_ML = 13
CC_MR = 14
```

and replace `PAGE_BUTTONS` / `CC_PAGE_*` with:

```python
CC_MODE_CONTROL = 11
CC_MODE_STEP = 32
CC_MODE_ALL = 38
CC_MODE_MIXER = 51       # VOLUME - needs the daemon patch, see Task 10
CC_MODE_FILTER = 37      # AUTO - already emitted by the shipped daemon
MODE_BUTTONS = {
    CC_MODE_CONTROL: "CONTROL",
    CC_MODE_STEP: "STEP",
    CC_MODE_ALL: "ALL",
    CC_MODE_MIXER: "MIXER",
    CC_MODE_FILTER: "FILTER",
}
MODE_LED_NAMES = {"CONTROL": "control", "STEP": "step", "ALL": "all",
                  "MIXER": "volume", "FILTER": "auto"}
```

Update every reference to the old names — `PAGE_BUTTONS`, `PAGE_LED_NAMES`, `CC_PAGE_CONTROL/STEP/ALL`, `CC_PAGE_LEFT/RIGHT`. `grep -n "PAGE_" zynthian_ctrldev_maschine_mk2.py` finds them all.

- [ ] **Step 2: Rebind DL/DR to paging and ML/MR to sound stepping**

In `_midi_event`, replace the `if cc_num in (CC_PAGE_LEFT, CC_PAGE_RIGHT):` block with:

```python
            if cc_num in (CC_DL, CC_DR):
                # Page within the current mode's ring, wrapping.
                self._step_page(-1 if cc_num == CC_DL else 1)
                return True
            if cc_num in (CC_ML, CC_MR):
                # Previous / next SOUND for the selected channel: a sample
                # within the kit on a drum, an engine preset on a voice.
                # Unconditionally cycling the sample resolved a GM percussion
                # fallback on a voice and collapsed its whole line onto one
                # note.
                delta = -1 if cc_num == CC_ML else 1
                if self.channel_kind(self.group) == "voice":
                    self._nudge_preset(self.group, delta)
                else:
                    self._cycle_sample(delta)
                return True
```

- [ ] **Step 3: Light one of five**

Replace `_render_pages` with:

```python
    def _render_modes(self):
        """Exactly one mode LED lit, always. Derived from self.mode on the
        render tick and never written at the point of the press, so the LED and
        the screens cannot disagree about which mode is showing.

        The daemon accepts a button LED name over OSC whether or not it emits
        that button's CC, so volume and auto light without the Task 10 patch."""

        for mode, led in MODE_LED_NAMES.items():
            bright = BRIGHT_PAGE_ON if mode == self.mode else BRIGHT_PAGE_OFF
            state = (COLOR_PAGE, bright)
            if self.leds.changed(f"mode_{led}", state):
                self._send_osc(lib.button_osc(led, state[0], state[1]))
```

Update the caller in `_render_all` from `self._render_pages()` to
`self._render_modes()`. The LED cache key changes from `page_*` to `mode_*`
deliberately — a stale `page_control` entry would suppress the first repaint.

- [ ] **Step 4: Verify it compiles and nothing stale remains**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && grep -n "CC_PAGE_\|PAGE_BUTTONS\|PAGE_LED_NAMES\|_set_page\|_render_pages" zynthian_ctrldev_maschine_mk2.py`
Expected: `py_compile` silent, and **grep prints nothing**.

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(maschine): bind VOLUME and AUTO as modes, DL/DR as paging

DL/DR step the current ring; sound stepping moves to ML/MR, which are free
and already emitting. Constants renamed to the owner's button names - the
old CC_PAGE_LEFT was CC 5, which is DL, not the transport pair.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Encoder dispatch on shape

**Files:**
- Modify: `zynthian_ctrldev_maschine_mk2.py:1263-1293` (`COLUMN_VERBS`, `_encoder_column`), `_verb`
- Test: hardware (G4/G5). Verify with `py_compile`.

**Interfaces:**
- Consumes: `_page()` from Task 5; `tlib.VERB_LV2`, `tlib.VERB_FX` from Task 3.
- Produces: `_encoder_column(column, cc_num, cc_val)` dispatching on shape; `_verb` handling the two generated prefixes.

- [ ] **Step 1: Replace COLUMN_VERBS with shape dispatch**

Delete the `COLUMN_VERBS` dict and the `COLUMN_VERBS[("ALL", "voice")] = …` line — `tlib.PAGE_RINGS` now owns that data. Replace `_encoder_column` with:

```python
    def _encoder_column(self, column, cc_num, cc_val):
        """Turn an encoder movement into (verb, channel, value).

        Three shapes, one dispatch. `channel` resolves to the selected channel,
        to the column's own channel, or to None for a global - and _verb() has
        always taken the channel as an argument, so nothing below this changes."""

        desc = self._page()
        shape = desc["shape"]
        if shape == tlib.SHAPE_SPREAD:
            verb, channel = desc["verb"], column
        else:
            verb = desc["verbs"][column]
            channel = None if shape == tlib.SHAPE_GLOBAL else self.group
        if verb is None:
            return                        # greyed column, dead knob, honestly
        self._verb(verb, channel, cc_num, cc_val)
```

For the `SHAPE_GLOBAL` case, `_verb` already resolves globals by verb name and ignores the channel; passing `None` matches what the ALL page does today.

- [ ] **Step 2: Teach `_verb` the two generated prefixes**

At the top of `_verb`, before the existing verb tests:

```python
        if verb.startswith(tlib.VERB_LV2):
            self._verb_lv2(verb[len(tlib.VERB_LV2):], channel, cc_num, cc_val)
            return
        if verb.startswith(tlib.VERB_FX):
            which, _, symbol = verb[len(tlib.VERB_FX):].partition(":")
            self._verb_fx(which, symbol, cc_num, cc_val)
            return
```

and add the two handlers next to `_set_ganged`:

```python
    def _verb_lv2(self, symbol, channel, cc_num, cc_val):
        """A generated CONTROL page column: one port on this channel's synth
        processor. The surface value is 0-100 and is scaled onto the port's own
        range, the same contract _set_ganged() uses for the FX roles."""

        proc = self._voice_processor(channel)
        if proc is None:
            return
        zctrl = proc.controllers_dict.get(symbol)
        if zctrl is None:
            return
        delta = self._enc_steps(cc_num, cc_val, 101)
        if delta == 0:
            return
        span = zctrl.value_max - zctrl.value_min
        if span <= 0:
            return
        percent = (zctrl.value - zctrl.value_min) / span * 100.0
        percent = min(100.0, max(0.0, percent + delta))
        zctrl.set_value(zctrl.value_min + span * (percent / 100.0), True)
        with self.lock:
            self._render_display()

    def _verb_fx(self, which, symbol, cc_num, cc_val):
        """A generated ALL page column: one port on the reverb or the delay,
        ganged across all sixteen inserts, exactly as _set_ganged() does for
        the four hand-written FX roles."""

        proc = self.fx_handle(0, which)
        if proc is None:
            return
        zctrl = proc.controllers_dict.get(symbol)
        if zctrl is None:
            return
        delta = self._enc_steps(cc_num, cc_val, 101)
        if delta == 0:
            return
        span = zctrl.value_max - zctrl.value_min
        if span <= 0:
            return
        percent = (zctrl.value - zctrl.value_min) / span * 100.0
        percent = min(100.0, max(0.0, percent + delta))
        target = zctrl.value_min + span * (percent / 100.0)
        for channel in range(len(tlib.CHANNELS)):
            other = self.fx_handle(channel, which)
            if other is None:
                continue
            zc = other.controllers_dict.get(symbol)
            if zc is not None:
                zc.set_value(target, True)
        with self.lock:
            self._render_display()
```

Both use `_enc_steps(…, 101)` so a knob moves in whole percent with the remainder carried — `zynthian_controller._set_value()` truncates integer controls, and a fractional step on an integer port is a knob that does nothing.

- [ ] **Step 3: Verify it compiles**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && grep -n "COLUMN_VERBS" zynthian_ctrldev_maschine_mk2.py`
Expected: `py_compile` silent, **grep prints nothing**.

- [ ] **Step 4: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(maschine): dispatch encoders on page shape

COLUMN_VERBS retires into techno_lib's rings. _encoder_column resolves
(verb, channel) from the descriptor's shape and hands both to the unchanged
_verb path. Two new verb prefixes reach generated plugin ports directly.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Display wiring — spread columns, page label, meters

**Files:**
- Modify: `zynthian_ctrldev_maschine_mk2.py:2360-2394` (`_columns`, `_render_display`)
- Test: hardware (G5). Verify with `py_compile`.

**Interfaces:**
- Consumes: `tlib.columns` (Task 2), `tlib.page_label`, `tlib.quantise_frac`, `lib.screen_packets(…, label)` (Task 4), `_page()` (Task 5).
- Produces: `_columns(screen)` handling all three shapes; `_meter_frac(channel)`.

- [ ] **Step 1: Rewrite `_columns` for the three shapes**

```python
    def _columns(self, screen):
        """Four columns for one screen, taken from the page model.

        techno_lib.columns() decides names, values, greyed columns and the
        pending brackets in one tested place; this only translates its dicts
        into the (name, value, bar kind, fraction) tuples screen_packets()
        draws, and converts a segmented bar's (index, count) into a fraction."""

        desc = self._page()
        shape = desc["shape"]
        if desc.get("generated"):
            cols = tlib.columns(desc, None, self._generated_view(desc))
        elif shape == tlib.SHAPE_SPREAD:
            views = [(chr(ord("A") + i), tlib.CHANNELS[i][1], self.state_view(i))
                     for i in range(len(tlib.CHANNELS))]
            cols = tlib.columns(desc, None, views)
        elif shape == tlib.SHAPE_GLOBAL:
            cols = tlib.columns(desc, None, self.globals_view())
        else:
            channel = self.group
            cols = tlib.columns(desc, self.channel_kind(channel),
                                self.state_view(channel))

        meter_page = shape == tlib.SHAPE_SPREAD and desc["verb"] == "level"
        out = []
        for index, col in enumerate(cols[screen * 4:screen * 4 + 4]):
            bar = BAR_KINDS[col["bar"]]
            frac = col["frac"]
            if bar == "s":
                count, total = frac
                frac = (count / (total - 1)) if total > 1 else 0.0
            if meter_page:
                channel = screen * 4 + index
                level = self._meter_frac(channel)
                if level is not None:
                    frac = level
            out.append((col["name"], col["value"], bar,
                        round(float(frac), 3)))
        return tuple(out)
```

Note the tuple unpack for segmented bars keeps the shipped names (`index, count`) — rename only if the surrounding code does.

- [ ] **Step 2: Add the generated-page view**

A generated column's value lives on the plugin, not in `self.state`, so
`columns()` needs a view keyed by the same `lv2:`/`fx:` verb names the
descriptor carries:

```python
    def _generated_view(self, desc):
        """Current value of every port on a generated page, as 0-100, keyed by
        the descriptor's own verb names. Reading controllers_dict and a zctrl's
        value is cheap and reaches no engine load."""

        view = {"pending": set()}
        for verb in desc["verbs"]:
            if verb is None:
                continue
            if verb.startswith(tlib.VERB_LV2):
                symbol = verb[len(tlib.VERB_LV2):]
                proc = self._voice_processor(self.group)
            else:
                which, _, symbol = verb[len(tlib.VERB_FX):].partition(":")
                proc = self.fx_handle(0, which)
            if proc is None:
                continue
            zctrl = proc.controllers_dict.get(symbol)
            if zctrl is None:
                continue
            span = zctrl.value_max - zctrl.value_min
            if span <= 0:
                continue
            view[verb] = int(round((zctrl.value - zctrl.value_min) / span * 100.0))
        return view
```

A verb missing from the view draws dead, which is exactly right: a port that
vanished with a preset change should say so rather than show a stale number.

- [ ] **Step 3: Add the meter reader**

```python
    # Peak metering. enable_dpm and update_dpm_states may not exist on the Pi's
    # older libzynmixer - G4 checks. When they are missing the bar keeps showing
    # fader position, which is what it showed before this feature existed.
    METER_PIXELS = lib.SCREEN_COL - 12      # the bar's inner width in pixels

    def _meter_frac(self, channel):
        """This channel's peak level as a 0-1 fraction, quantised to the bar's
        real pixel resolution so a steady signal stops repainting."""

        mixer = self.state_manager.zynmixer
        chan = self._mixer_chan(channel)
        if chan is None or not hasattr(mixer, "update_dpm_states"):
            return None
        try:
            mixer.update_dpm_states()
            dpm = mixer.dpm[chan]
            # DPM is dBFS; -40 dB is the bottom of a useful bar.
            level = getattr(dpm, "peakA", None)
            if level is None:
                return None
            frac = (float(level) + 40.0) / 40.0
        except Exception:
            return None
        return tlib.quantise_frac(frac, self.METER_PIXELS)
```

The `peakA` attribute name and the `dpm` indexing are the one thing here that cannot be confirmed with the Pi offline. **G4 step 4 settles it**; if the shape differs, only this function changes.

- [ ] **Step 4: Pass the label through**

In `_render_display`, replace the body of the loop:

```python
        desc = self._page()
        ring = self._ring()
        key = tlib.ring_key(self.mode, self.channel_kind(self.group))
        label = tlib.page_label(desc["title"], self.page_idx.get(key, 0), len(ring))
        for screen in (0, 1):
            state = (self._tabs(screen), self._columns(screen), label)
            if not self.leds.changed(f"disp{screen}", state):
                continue
            for packet in lib.screen_packets(screen, state[0], state[1], state[2]):
                self._send_osc(packet)
```

The label joins the cached tuple deliberately: paging with no other change must still repaint.

- [ ] **Step 5: Enable DPM once at start**

In the driver's `init` (next to the other one-time setup), add:

```python
        # Peak metering is off by default and costs nothing until a mixer page
        # asks for it. Guarded because the Pi's libzynmixer may not export it.
        mixer = self.state_manager.zynmixer
        if hasattr(mixer, "enable_dpm"):
            try:
                mixer.enable_dpm(True)
            except Exception:
                logging.debug("Maschine: mixer has no usable DPM")
```

- [ ] **Step 6: Verify it compiles**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo OK`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(maschine): draw spread pages, the page indicator and meters

Spread pages label each column with its channel; MIXER's level page swaps the
fader bar for a peak meter, quantised to real pixels so a steady signal does
not repaint. Both degrade to fader position if the Pi's libzynmixer has no
DPM.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Generated ring cache and invalidation

**Files:**
- Modify: `zynthian_ctrldev_maschine_mk2.py` — replace the `_gen_pages` stub from Task 5; hook `_on_snapshot`, `_commit_kit`, `_commit_preset`
- Test: hardware (G5). Verify with `py_compile`.

**Interfaces:**
- Consumes: `tlib.generated_pages`, `tlib.VERB_LV2`, `tlib.VERB_FX`, `tlib.VOICE_SYMBOLS`, `tlib.FX_REVERB`, `tlib.FX_DELAY`.
- Produces: `self.gen_cache: dict`, `self._gen_pages(mode, kind)`, `self._invalidate_gen_cache()`.

- [ ] **Step 1: Add the cache**

Next to the other caches in `init`:

```python
        # Generated rings, keyed (mode, kind, channel). Built once and held:
        # _ring() runs on the MIDI thread, where reaching an engine load would
        # freeze the instrument - midi_event holds self.lock for the whole
        # event and a load blocks on a socket for seconds.
        self.gen_cache = {}
```

- [ ] **Step 2: Replace the stub**

```python
    def _gen_pages(self, mode, kind):
        """Extra pages built from whatever the chain actually publishes.

        CONTROL extras come from the channel's synth processor; ALL extras come
        from the reverb and the delay, ganged. Symbols that already have a
        hand-written home are excluded so no parameter appears twice."""

        channel = self.group if mode == "CONTROL" else -1
        key = (mode, kind, channel)
        if key in self.gen_cache:
            return self.gen_cache[key]

        pages = ()
        if mode == "CONTROL" and kind == "voice":
            proc = self._voice_processor(self.group)
            engine = tlib.CHANNELS[self.group][4]
            exclude = set(tlib.VOICE_SYMBOLS.get(engine, ()))
            pages = tlib.generated_pages(self._ports(proc), exclude,
                                         tlib.SHAPE_CHANNEL, tlib.VERB_LV2,
                                         "EXTRA")
        elif mode == "ALL":
            for which, table, title in (
                    ("reverb", tlib.FX_REVERB, "REV"),
                    ("delay", tlib.FX_DELAY, "DLY")):
                proc = self.fx_handle(0, which)
                exclude = {sym for sym, _, _ in table.values()}
                pages += tlib.generated_pages(
                    self._ports(proc), exclude, tlib.SHAPE_GLOBAL,
                    tlib.VERB_FX + which + ":", title)

        self.gen_cache[key] = pages
        return pages

    @staticmethod
    def _ports(proc):
        """A processor's controllers as techno_lib's (symbol, lo, hi) tuples.
        Reading controllers_dict is cheap and touches no engine load."""

        if proc is None:
            return []
        out = []
        for symbol, zctrl in proc.controllers_dict.items():
            out.append((symbol, getattr(zctrl, "value_min", None),
                        getattr(zctrl, "value_max", None)))
        return out

    def _invalidate_gen_cache(self):
        """A different preset, kit or snapshot means a different plugin, which
        means different ports."""

        self.gen_cache.clear()
```

- [ ] **Step 3: Hook invalidation**

Call `self._invalidate_gen_cache()` at the end of each of: `_on_snapshot` (inside the existing `with self.lock:` block, after `_resync_all()`), `_commit_kit`, and `_commit_preset`. All three already run off the MIDI thread.

- [ ] **Step 4: Verify it compiles**

Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m py_compile zynthian_ctrldev_maschine_mk2.py && echo OK`
Expected: `OK`

Run the full suite once more to confirm nothing pure regressed:
Run: `cd ~/zynth/zynthian-ui/zyngine/ctrldev && python3 -m unittest discover -s tests -q`
Expected: **162 tests, OK**

- [ ] **Step 5: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(maschine): cache generated rings, invalidate on plugin change

_ring() runs on the MIDI thread, so port discovery is cached and never
reaches an engine load. Cleared on snapshot, kit and preset commits, all of
which already run off that thread.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Daemon patch — emit SHIFT, SWING, VOLUME

**Files:**
- Modify: `~/zynth/MaschineMK2_linux/src/main.rs:840-860` (the SHIFT modifier arm) and `:940-1145` (the RPN7 match)
- Test: `cargo build` locally; hardware at G4 step 3.

**Interfaces:**
- Consumes: nothing.
- Produces: CC 49 (SHIFT), 50 (SWING), 51 (VOLUME) on `Ch1`, press and release, matching every other button's `cc_math::button_cc_value(is_down)` contract.

- [ ] **Step 1: Add the three arms**

In the `match button` block, alongside the existing arms:

```rust
                "shift" => {
                    let msg = Message::RPN7(Ch1, 49, cc_math::button_cc_value(is_down));
                    self.seq_port.send_message(&msg).unwrap();
                    self.seq_handle.drain_output();
                }
                "swing" => {
                    let msg = Message::RPN7(Ch1, 50, cc_math::button_cc_value(is_down));
                    self.seq_port.send_message(&msg).unwrap();
                    self.seq_handle.drain_output();
                }
                "volume" => {
                    let msg = Message::RPN7(Ch1, 51, cc_math::button_cc_value(is_down));
                    self.seq_port.send_message(&msg).unwrap();
                    self.seq_handle.drain_output();
                }
```

**Do not touch the `if button.contains("shift")` block above the match.** It sets `maschine.set_mod`, which is live: it gates the daemon's own PAD MODE handling and one encoder. SHIFT must keep working as an internal modifier *and* start emitting. The two are independent — the modifier block runs before the match and does not return.

- [ ] **Step 2: Build**

Run: `cd ~/zynth/MaschineMK2_linux && cargo build --release`
Expected: compiles with no new warnings.

- [ ] **Step 3: Commit**

```bash
cd ~/zynth/MaschineMK2_linux
git add src/main.rs
git commit -m "feat: emit SHIFT 49, SWING 50 and VOLUME 51

VOLUME is the techno machine's mixer-mode button and SHIFT is its channel
type gesture; neither reached the driver because neither had an RPN7 arm.
SHIFT keeps its internal set_mod behaviour - it gates PAD MODE and one
encoder inside the daemon and cannot simply be forwarded.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: The G4 runbook

**Files:**
- Create: `~/zynth-docs/docs/superpowers/techno-machine/2026-08-11-gate-g4-runbook.md`

Every CC in this plan is read out of source, not observed. G4 converts that, and it cannot run until the Pi is connected. Writing the runbook now means the audit is a checklist rather than a re-derivation.

- [ ] **Step 1: Write the runbook**

The document contains, as a numbered checklist with a results table to fill in:

1. **Button audit.** `ssh root@192.168.2.123`, then `jack_midi_dump` on the daemon's port — find it with `jack_lsp | grep -i pads`. Press each of DL, DR, ML, MR, TL, TR, AUTO, MUTE, GRID, SELECT, VIEW, PAD MODE, NAVIGATE, NAV once, alone, and record: CC number, whether a release event arrives, and the physical location. **This settles which physical pair emits 5/6** — the old constant was named `CC_PAGE_LEFT` while CLAUDE.md called that pair the display arrows.
2. **AUTO reachability.** Confirm CC 37 arrives at the driver and is not swallowed the way 47/48 are.
3. **Post-patch check.** After deploying Task 10: confirm CC 49/50/51 emit on press and release, **and** that PAD MODE still behaves — SHIFT is a live modifier inside the daemon.
4. **Symbol audit.**
   ```
   ssh root@192.168.2.123 'nm -D --defined-only /zynthian/zynthian-ui/zynlibs/zynmixer/build/libzynmixer.so | awk "\$2==\"T\"{print \$3}" | sort | grep -i dpm'
   ssh root@192.168.2.123 'nm -D --defined-only /zynthian/zynthian-ui/zynlibs/zynseq/build/libzynseq.so | awk "\$2==\"T\"{print \$3}" | sort | grep -i addnote'
   ```
   Record whether `updateDpmStates` and `enableDpm` exist, and `addNote`'s arity. If DPM is absent, Task 8's `_meter_frac` returns `None` and the bar shows fader position — no code change needed, but record the decision.
5. **SOLO gestures.** The oldest unverified claim in the project. `zynmixer.toggle_solo` is **additive**, not exclusive, with a special case at `MAX_NUM_CHANNELS - 1` that clears every solo. Hold SOLO, press F1, then F3: confirm whether both channels solo or only the last pressed. Record the answer.

Deployment notes the runbook must carry:

- Move commits with `git bundle create` on WSL, `git fetch /tmp/x.bundle main:refs/remotes/origin/main` on the Pi. **Check the fetch exit status** — a bare `git reset --hard origin/main` once rewound the tree because the fetch had silently failed.
- Re-set `"external_pad_leds": true` in the daemon's `maschine.json` after any reset; it is not in git on the Pi and without it the first pad touch wipes the driver's per-group colours.
- Re-run `~/zynth-docs/tools/patch-autoconnect-maschine.py` after any Zynthian update, or the driver is "Found" but never "Loaded" and the rig does nothing with no error.
- `jack_lsp -c | grep -A3 "Pads MIDI"` must show exactly **one** `devN_in`. A stale manual `jack_connect` outlives a zynthian restart and produces phantom drum sounds on pad taps.

- [ ] **Step 2: Commit**

```bash
cd ~/zynth-docs
git add docs/superpowers/techno-machine/2026-08-11-gate-g4-runbook.md
git commit -m "docs: G4 surface audit runbook

Every CC in the SP1 plan is read out of source, not observed. This is the
checklist that converts them, plus the deploy steps that have bitten before.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Deviations from the spec

One, deliberate, found while writing Task 1:

**Spec §4.1 says ALL page 1 keeps `root, scale, bpm, master` and gains four free slots, with the FX globals moving to generated pages 2–3.** That would be a regression. `dlytime` is a musical division resolved against live tempo by `_push_delay_time`, and `revtype` is an index into the plugin's 43 rooms with its own no-scaling special case in `_set_ganged`. Neither is a raw plugin port and neither survives being generated. **ALL page 1 therefore keeps all eight shipped globals unchanged**, and the generated pages expose the ports that have no hand-written home — which is also why `generated_pages` takes an `exclude` set. Update the spec to match.

## Post-plan verification

After Task 9, before any hardware work:

```bash
cd ~/zynth/zynthian-ui/zyngine/ctrldev
python3 -m unittest discover -s tests -q          # expect 162 tests, OK
python3 -m py_compile zynthian_ctrldev_maschine_mk2.py
grep -n "COLUMN_VERBS\|CC_PAGE_\|self\.page\b" zynthian_ctrldev_maschine_mk2.py   # expect nothing
```

G5 (spec §7) runs after deployment: DSP load mean and p95, xrun count, segfault and traceback count, memory over twenty minutes, watchdog reopen cadence against the ~8 s healthy baseline, plus a mixer-mode check that meter quantisation actually stops the repaint storm — watch OSC volume with the page held still on a silent channel.
