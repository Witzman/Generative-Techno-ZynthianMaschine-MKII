# Per-Group SFZ Drum Kits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each of the eight Maschine MK2 drum groups its own SFZ drum-machine kit, selected on encoder 7, with the sound inside that kit on encoder 6.

**Architecture:** All eight group chains run LinuxSampler instead of FluidSynth, from a new prepared snapshot. Changing a kit is a preset change on the chain's existing processor — never an engine swap. Kit contents are read by parsing the `.sfz` files, because Zynthian's `keymaps.json` note-name lookup cannot match them. Volume and pan move from engine controllers to the mixer strip, because LinuxSampler exposes no controllers at all.

**Tech Stack:** Python 3 (Zynthian ctrldev driver), LinuxSampler via Zynthian's processor/preset API, `zynmixer` for level and balance, plain `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-09-maschine-sfz-kits-design.md`

## Global Constraints

- Target device is a Raspberry Pi 4 at `ssh root@192.168.2.123`. Zynthian lives at `/zynthian/zynthian-ui`.
- **The Pi's Zynthian is older than the `~/zynth/zynthian-ui` checkout.** Never call an API taken from local sources without confirming it on the Pi first. APIs used by this plan were audited on 2026-08-09 and are listed in Task 0.
- **Every zynseq call the driver makes must hold `self.lock`.** libzynseq is not thread-safe and the driver reaches it from three threads. Unsynchronised access segfaulted the whole UI (exit 139).
- **Never hold `self.lock` across a preset load.** Loading talks to LinuxSampler over a socket and can block.
- **Never do slow work on the MIDI handler thread.** It is the thread the daemon's input depends on.
- Driver files: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py` (device), `zyngine/ctrldev/maschine_mk2_lib.py` (pure logic, no Zynthian imports), `zyngine/ctrldev/tests/test_maschine_mk2_lib.py` (tests).
- Run tests with `python3 zyngine/ctrldev/tests/test_maschine_mk2_lib.py` from `~/zynth/zynthian-ui`. There is no pytest on this machine.
- Deploy with `scp <files> root@192.168.2.123:/zynthian/zynthian-ui/zyngine/ctrldev/` then `ssh root@192.168.2.123 'systemctl restart zynthian'`. Wait ~22 s before testing.
- **Restarting `maschine-mk2.service` requires restarting `zynthian` afterwards**, or the driver never re-binds to the daemon's recreated ALSA port and the whole rig goes dead.
- Kit files: `/zynthian/zynthian-data/soundfonts/sfz/Drum Machines/` — 41 `.sfz` files plus a `Samples/` directory.
- Commit to `~/zynth/zynthian-ui` on branch `vangelis`. Do not commit `zyngine/zynthian_state_manager.py` or `zyngine/ctrldev/zynthian_ctrldev_sinco_smc_pad.py` — they carry unrelated pre-existing changes.

---

### Task 0: Verify a live preset change through Zynthian

This is a **risk gate, not a feature**. The cost spike drove LinuxSampler directly over LSCP; it never exercised Zynthian's processor layer. If a preset change stalls the UI or glitches audio while a pattern plays, the design changes (kit changes become stopped-transport only) and the rest of this plan must be revised before it is built.

**Files:**
- Modify, temporarily and reverted in Step 6: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a go/no-go answer recorded in `MD/todo.md`. No code that later tasks depend on.

**Audited API (confirmed on the Pi 2026-08-09) — later tasks rely on these:**
- `chain_manager.get_synth_processor(midi_chan)` → processor, or `None`
- `processor.set_bank_by_name(name)` → bool
- `processor.preset_list` → list of entries; `entry[0]` is the `.sfz` path (optionally `path#index`), `entry[2]` is the display name
- `processor.set_preset_by_name(name)` → bool
- `processor.load_preset_list()` populates `preset_list` from the current bank
- `zynmixer.set_level(chan, 0.0..1.0)` / `get_level(chan)`
- `zynmixer.set_balance(chan, -1.0..1.0)` / `get_balance(chan)`
- `zynmixer.set_mute(chan, bool)` / `get_mute(chan)`

- [ ] **Step 1: Load the rig snapshot and start it playing**

On the touchscreen, load `020-maschine-drum-rig` and press Play on the MK2 so a pattern is audibly running. Kit swapping matters most under load, so measuring it on a silent machine proves nothing.

- [ ] **Step 2: Write the probe script**

The probe needs live Python objects — the chain manager and a processor — so it cannot run as a standalone script against the running UI. It goes into the driver temporarily and is triggered from a button.

Add this method to `/zynthian/zynthian-ui/zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`, temporarily, just above `def refresh(self):`

```python
    def _probe_kit_swap(self):
        """TEMPORARY probe - remove after Task 0. Times a preset change on a
        live chain while a pattern plays."""
        import time
        proc = self.chain_manager.get_synth_processor(self.group)
        logging.warning(f"PROBE: processor={proc} engine={proc.engine.nickname if proc else None}")
        if proc is None:
            return
        proc.set_bank_by_name("Drum Machines")
        proc.load_preset_list()
        names = [p[2] for p in proc.preset_list]
        logging.warning(f"PROBE: {len(names)} kits, first five {names[:5]}")
        for name in names[:5]:
            t0 = time.time()
            ok = proc.set_preset_by_name(name)
            logging.warning(f"PROBE: {name} -> {ok} in {time.time() - t0:.3f}s")
            time.sleep(1.0)
```

- [ ] **Step 3: Trigger the probe from the Erase button, temporarily**

In `_midi_event`, inside the `if cc_num == CC_ERASE:` branch, replace `self._clear_group()` with `self._probe_kit_swap()`.

- [ ] **Step 4: Deploy and run**

```bash
cd ~/zynth/zynthian-ui
scp zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py root@192.168.2.123:/zynthian/zynthian-ui/zyngine/ctrldev/
ssh root@192.168.2.123 'systemctl restart zynthian'
sleep 25
```

Load the rig snapshot, start playback, press **Erase** on the MK2, then read the log:

```bash
ssh root@192.168.2.123 'journalctl -u zynthian --since "-2min" --no-pager | grep PROBE'
```

- [ ] **Step 5: Record the answer**

Expected if the design holds: five `-> True in 0.0xx s` lines, audio keeps playing, no xruns, the UI stays responsive.

Note in `MD/todo.md` under the SFZ kit item: the per-swap time, whether audio glitched, and whether the touchscreen stalled.

**If a swap takes longer than ~0.3 s, glitches audio, or freezes the UI: STOP.** Report it and revise the spec before continuing — the fallback design is committing kit changes only while the transport is stopped.

- [ ] **Step 6: Revert the probe**

```bash
cd ~/zynth/zynthian-ui
git checkout -- zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
scp zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py root@192.168.2.123:/zynthian/zynthian-ui/zyngine/ctrldev/
ssh root@192.168.2.123 'systemctl restart zynthian'
```

Nothing is committed from this task.

---

### Task 1: Parse an SFZ kit into its note list

**Files:**
- Modify: `zyngine/ctrldev/maschine_mk2_lib.py`
- Test: `zyngine/ctrldev/tests/test_maschine_mk2_lib.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `maschine_mk2_lib.parse_sfz_notes(text) -> list[tuple[int, str]]`, sorted by note ascending, one entry per distinct key, names uppercased.

The real format, from `Roland TR808.sfz`:

```
<region> sample=Samples\Roland TR808\808 Kick_short.wav
lokey=36
hikey=36
pitch_keycenter=60
loop_mode=no_loop
```

Several `<region>` blocks share a key with `lovel`/`hivel` velocity splits; only the first is kept.

- [ ] **Step 1: Write the failing tests**

Add to `test_maschine_mk2_lib.py`, above `if __name__ == "__main__":`

```python
class TestSfzParsing(unittest.TestCase):

    KIT = r"""<group>
pitch_keytrack=0

<region> sample=Samples\Roland TR808\808 Kick_short.wav
lokey=36
hikey=36

<region> sample=Samples\Roland TR808\808 Snare_lo1.wav
lokey=40
hikey=40
lovel=70
hivel=127

<region> sample=Samples\Roland TR808\808 Snare_lo2.wav
lokey=40
hikey=40
lovel=0
hivel=69
"""

    def test_one_entry_per_distinct_key(self):
        self.assertEqual([n for n, _ in lib.parse_sfz_notes(self.KIT)], [36, 40])

    def test_name_comes_from_the_sample_filename(self):
        notes = dict(lib.parse_sfz_notes(self.KIT))
        self.assertEqual(notes[36], "808 KICK SHORT")

    def test_velocity_layers_keep_the_first_sample(self):
        notes = dict(lib.parse_sfz_notes(self.KIT))
        self.assertEqual(notes[40], "808 SNARE LO1")

    def test_notes_are_sorted(self):
        text = "<region> sample=a\\Z.wav\nlokey=50\n<region> sample=a\\A.wav\nlokey=30\n"
        self.assertEqual([n for n, _ in lib.parse_sfz_notes(text)], [30, 50])

    def test_region_without_a_key_is_skipped(self):
        text = "<region> sample=a\\NoKey.wav\n<region> sample=a\\Ok.wav\nlokey=42\n"
        self.assertEqual(lib.parse_sfz_notes(text), [(42, "OK")])

    def test_key_is_accepted_as_well_as_lokey(self):
        self.assertEqual(lib.parse_sfz_notes("<region> sample=a\\B.wav\nkey=44\n"),
                         [(44, "B")])

    def test_empty_text_gives_no_notes(self):
        self.assertEqual(lib.parse_sfz_notes(""), [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 zyngine/ctrldev/tests/test_maschine_mk2_lib.py -v 2>&1 | tail -20`
Expected: FAIL — `AttributeError: type object 'maschine_mk2_lib' has no attribute 'parse_sfz_notes'`

- [ ] **Step 3: Implement the parser**

Add to `maschine_mk2_lib.py` inside the class, just above the `# --- screens ---` comment block:

```python
    # --- SFZ kits ------------------------------------------------------
    #
    # A kit's note list cannot come from Zynthian's keymaps.json: that
    # resolves on the synth's preset path and matches only the FluidSynth
    # soundfonts, so an SFZ kit would leave every group tab reading
    # "note 36". The kit files carry the information themselves.

    @staticmethod
    def parse_sfz_notes(text):
        """The playable notes of an SFZ kit, as [(note, NAME)] sorted by note.

        One entry per distinct key: kits split a key into several <region>
        blocks by velocity (lovel/hivel), and those are the same drum sound,
        so the first one wins. The name is the sample's filename without
        directory or extension."""

        notes = {}
        sample = None
        for raw in text.replace("<region>", "\n<region>").splitlines():
            line = raw.strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("<"):
                sample = None                     # a new block, name not seen yet
            for token in line.split():
                if token.startswith("sample="):
                    sample = token.split("=", 1)[1]
                elif token.startswith(("lokey=", "key=")):
                    value = token.split("=", 1)[1]
                    try:
                        note = int(value)
                    except ValueError:
                        continue
                    if note not in notes and sample:
                        notes[note] = maschine_mk2_lib._sample_label(sample)
        return sorted(notes.items())

    @staticmethod
    def _sample_label(sample):
        """A drum name from a sample path: strip the directories and the
        extension, turn underscores into spaces, uppercase."""

        leaf = sample.replace("\\", "/").rsplit("/", 1)[-1]
        if "." in leaf:
            leaf = leaf.rsplit(".", 1)[0]
        return leaf.replace("_", " ").strip().upper()
```

The `replace("<region>", "\n<region>")` matters: the sample name sits on the same line as the `<region>` tag, so the tag has to be split off before the block is read, or the `sample=` on that line is discarded by the block reset.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 zyngine/ctrldev/tests/test_maschine_mk2_lib.py 2>&1 | tail -4`
Expected: `OK`

- [ ] **Step 5: Check the parser against every real kit**

```bash
ssh root@192.168.2.123 'exit 0'   # confirm the Pi is reachable
cd ~/zynth/zynthian-ui
scp zyngine/ctrldev/maschine_mk2_lib.py root@192.168.2.123:/tmp/mk2lib.py
ssh root@192.168.2.123 'cd /tmp && python3 -c "
import sys, os, glob
sys.path.insert(0, \"/tmp\")
from mk2lib import maschine_mk2_lib as lib
d = \"/zynthian/zynthian-data/soundfonts/sfz/Drum Machines\"
bad = 0
for f in sorted(glob.glob(d + \"/*.sfz\")):
    notes = lib.parse_sfz_notes(open(f, errors=\"replace\").read())
    if not notes:
        print(\"EMPTY:\", os.path.basename(f)); bad += 1
    else:
        print(f\"{os.path.basename(f):<26} {len(notes):3d} notes  {notes[0][1][:18]}\")
print(\"kits with no notes:\", bad)
"'
```

Expected: every kit reports a sensible note count (roughly 10-30) and a readable first name; `kits with no notes: 0`. If any kit parses empty, add its shape to the tests and fix the parser before continuing.

- [ ] **Step 6: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/maschine_mk2_lib.py zyngine/ctrldev/tests/test_maschine_mk2_lib.py
git commit -m "feat(maschine): read an SFZ kit's note list from the kit file"
```

---

### Task 2: Kit name shortening and nearest-note landing

**Files:**
- Modify: `zyngine/ctrldev/maschine_mk2_lib.py`
- Test: `zyngine/ctrldev/tests/test_maschine_mk2_lib.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `maschine_mk2_lib.kit_short_name(name) -> str`, at most 4 characters, for the double-height KIT cell
  - `maschine_mk2_lib.nearest_note(available, wanted) -> int | None` where `available` is a list of ints

- [ ] **Step 1: Write the failing tests**

```python
class TestKitNames(unittest.TestCase):

    def test_known_machines_get_their_familiar_short_names(self):
        self.assertEqual(lib.kit_short_name("Roland TR808"), "808")
        self.assertEqual(lib.kit_short_name("Roland TR909"), "909")
        self.assertEqual(lib.kit_short_name("LINN9000 1"), "LN90")
        self.assertEqual(lib.kit_short_name("SP1200 1"), "SP12")

    def test_unknown_names_fall_back_to_letters_and_digits(self):
        self.assertEqual(lib.kit_short_name("Mattel Synsonic"), "MSYN")

    def test_result_is_never_longer_than_four_characters(self):
        for name in ["Acetone Rhythm Ace", "Tama Tech Star 3", "DYNOSAUR-808",
                     "Fricke MSB512", "Electro Puff", "Boss DR220", "E Ave"]:
            self.assertLessEqual(len(lib.kit_short_name(name)), 4, name)

    def test_empty_name_gives_a_dash(self):
        self.assertEqual(lib.kit_short_name(""), "-")


class TestNearestNote(unittest.TestCase):

    def test_exact_match_is_kept(self):
        self.assertEqual(lib.nearest_note([36, 38, 42], 38), 38)

    def test_missing_note_lands_on_the_closest(self):
        self.assertEqual(lib.nearest_note([36, 38, 42], 39), 38)

    def test_ties_go_to_the_lower_note(self):
        self.assertEqual(lib.nearest_note([36, 40], 38), 36)

    def test_below_the_range_lands_on_the_lowest(self):
        self.assertEqual(lib.nearest_note([36, 40], 20), 36)

    def test_above_the_range_lands_on_the_highest(self):
        self.assertEqual(lib.nearest_note([36, 40], 90), 40)

    def test_empty_kit_gives_none(self):
        self.assertIsNone(lib.nearest_note([], 38))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 zyngine/ctrldev/tests/test_maschine_mk2_lib.py 2>&1 | tail -6`
Expected: FAIL — no attribute `kit_short_name`

- [ ] **Step 3: Implement both**

Add to `maschine_mk2_lib.py` below `_sample_label`:

```python
    # The double-height value cell fits 4 characters, and a drum machine's
    # familiar name is rarely its first four letters. Machines people name by
    # their number get it; everything else is shortened mechanically.
    KIT_SHORT_NAMES = {
        "Roland TR808": "808", "Roland TR909": "909", "Roland TR727": "727",
        "Roland TR606": "606", "Roland CR78": "CR78", "LINN9000 1": "LN90",
        "LINN9000 2": "LN91", "SP1200 1": "SP12", "SP1200 2": "SP13",
        "SP 12": "SP12", "DYNOSAUR-808": "DYNO", "Boss DR220": "DR22",
        "Boss DR55": "DR55", "Korg DDD1": "DDD1", "Korg DDM110": "DDM1",
        "Kawai R50": "R50", "Akai XR10": "XR10", "Akai XE8": "XE8",
        "Alesis HR16": "HR16", "Yamaha RX11": "RX11", "MXR 185": "M185",
        "Fricke MSB512": "MSB5", "Simmons": "SIMM", "DrumTraks": "TRAK",
        "Acetone Rhythm Ace": "ACET", "Mattel Synsonic": "MSYN",
    }

    @staticmethod
    def kit_short_name(name):
        """At most 4 characters for the KIT cell on the screen."""

        if not name:
            return "-"
        short = maschine_mk2_lib.KIT_SHORT_NAMES.get(name)
        if short:
            return short[:4]
        words = [w for w in name.replace("-", " ").split() if w]
        if len(words) > 1:
            # Initial of each leading word plus as much of the last as fits.
            head = "".join(w[0] for w in words[:-1])
            short = (head + words[-1])[:4]
        else:
            short = words[0][:4] if words else "-"
        return short.upper()

    @staticmethod
    def nearest_note(available, wanted):
        """The note in `available` closest to `wanted`, ties going to the
        lower one. Kits number their sounds differently, so a group's note
        usually does not exist in a kit it has just been given - landing on
        the nearest keeps it audible instead of silent."""

        if not available:
            return None
        return min(sorted(available), key=lambda n: (abs(n - wanted), n))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 zyngine/ctrldev/tests/test_maschine_mk2_lib.py 2>&1 | tail -4`
Expected: `OK`

- [ ] **Step 5: Eyeball every real kit's short name**

```bash
ssh root@192.168.2.123 'ls "/zynthian/zynthian-data/soundfonts/sfz/Drum Machines/"*.sfz' \
  | xargs -n1 basename | sed 's/\.sfz$//' > /tmp/kitnames.txt
cd ~/zynth/zynthian-ui
python3 -c "
import sys; sys.path.insert(0, 'zyngine/ctrldev')
from maschine_mk2_lib import maschine_mk2_lib as lib
for n in open('/tmp/kitnames.txt').read().splitlines():
    print(f'{n:<26} {lib.kit_short_name(n)}')
"
```

Expected: every line has a 1-4 character name that is recognisable. Add any that read badly to `KIT_SHORT_NAMES` and re-run.

- [ ] **Step 6: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/maschine_mk2_lib.py zyngine/ctrldev/tests/test_maschine_mk2_lib.py
git commit -m "feat(maschine): short kit names and nearest-note landing"
```

---

### Task 3: Move volume and pan to the mixer strip

LinuxSampler defines no controllers (`_ctrls = []` inherited from `zynthian_engine`), so encoders 5 and 8 would silently do nothing on an SFZ chain, taking the group-button volume brightness with them. This task is a prerequisite for the kits and is worth doing on its own: it works on any engine.

**Files:**
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `lib.encoder_delta`, `lib.ENC_SWEEP` (already present).
- Produces: `_mixer_level(group) -> float 0..1`, `_mixer_balance(group) -> float -1..1`, and a `MIXER_ENCODERS` dict replacing `CHAIN_CTRL_ENCODERS`.

- [ ] **Step 1: Replace the encoder table**

Replace the whole `CHAIN_CTRL_ENCODERS` block (the dict and its comment) with:

```python
# Encoders 5 and 8 drive the group's MIXER STRIP, not a controller on its
# engine. LinuxSampler defines no controllers at all - it inherits
# _ctrls = [] from zynthian_engine - so reading pan and volume off the
# engine stops working the moment a group runs an SFZ kit, and the group
# button's volume brightness stops with it. The mixer works on any engine,
# is where this driver already puts mutes, shows on the touchscreen mixer
# and is saved in snapshots.
#
# Expression is gone: it was a FluidSynth SoundFont modulator with no mixer
# equivalent and no meaning for a sampler.
CC_ENC_SAMPLE = 21     # encoder 6 - which sound of the kit this group plays
CC_ENC_KIT = 22        # encoder 7 - which kit this group uses
MIXER_ENCODERS = {
    20: "balance",      # encoder 5 - pan
    23: "level",        # encoder 8 - volume
}
```

- [ ] **Step 2: Replace `_set_chain_ctrl` with mixer versions**

Delete `_set_chain_ctrl` entirely and put this in its place:

```python
    def _mixer_level(self, group):
        chan = self._mixer_chan(group)
        return 0.0 if chan is None else self.state_manager.zynmixer.get_level(chan)

    def _mixer_balance(self, group):
        chan = self._mixer_chan(group)
        return 0.0 if chan is None else self.state_manager.zynmixer.get_balance(chan)

    def _set_mixer(self, symbol, cc_num, cc_val):
        """Move the selected group's mixer level or balance.

        Level is 0..1 and balance -1..+1 (zynthian_engine_audio_mixer.py:198),
        so one encoder unit is one 128th of the control's own range - the
        resolution the encoders had when they drove engine controllers."""

        chan = self._mixer_chan(self.group)
        if chan is None:
            return
        delta = self._enc_delta(cc_num, cc_val)
        if delta == 0:
            return
        mixer = self.state_manager.zynmixer
        if symbol == "level":
            value = mixer.get_level(chan) + delta / lib.ENC_SWEEP
            mixer.set_level(chan, min(1.0, max(0.0, value)))
            # The group buttons show volume as brightness, so they follow.
            self._render_groups()
        else:
            value = mixer.get_balance(chan) + 2.0 * delta / lib.ENC_SWEEP
            mixer.set_balance(chan, min(1.0, max(-1.0, value)))
```

- [ ] **Step 3: Point the MIDI dispatch at it**

In `_midi_event`, replace the `CHAIN_CTRL_ENCODERS` branch with:

```python
            if cc_num in MIXER_ENCODERS:
                self._set_mixer(MIXER_ENCODERS[cc_num], cc_num, cc_val)
                return True
```

- [ ] **Step 4: Take group brightness off the engine**

Replace the body of `_group_brightness` with:

```python
    def _group_brightness(self, group):
        """Group button brightness = that group's mixer level."""

        chan = self._mixer_chan(group)
        if chan is None:
            return BRIGHT_GROUP_NO_CHAIN
        level = min(1.0, max(0.0, self.state_manager.zynmixer.get_level(chan)))
        return BRIGHT_GROUP_MIN + (BRIGHT_GROUP_MAX - BRIGHT_GROUP_MIN) * level
```

- [ ] **Step 5: Point the screen at the mixer**

In `_columns`, replace the `screen == 1` branch with:

```python
        if screen == 1:
            balance = self._mixer_balance(group)
            level = self._mixer_level(group)
            return (("PAN", str(int(round(balance * 50))), "b", round((balance + 1) / 2, 2)),
                    ("SMPL", "-", "", 0.0),        # filled in by the kit task
                    ("KIT", "-", "", 0.0),         # filled in by the kit task
                    ("VOL", str(int(round(level * 100))), "u", round(level, 2)))
```

Then delete `_ctrl_column`, which nothing calls any more, and delete the now-unused `VOLUME_SYMBOL` constant and the `_zctrl` method **only if** nothing else references them — check with `grep -n "_zctrl\|VOLUME_SYMBOL" zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py` and leave them if anything still does.

- [ ] **Step 6: Check it imports and deploy**

```bash
cd ~/zynth/zynthian-ui
python3 -m py_compile zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py && echo compile-ok
python3 zyngine/ctrldev/tests/test_maschine_mk2_lib.py 2>&1 | tail -3
scp zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py root@192.168.2.123:/zynthian/zynthian-ui/zyngine/ctrldev/
ssh root@192.168.2.123 'systemctl restart zynthian; sleep 25; systemctl is-active zynthian'
```

- [ ] **Step 7: Verify on the hardware**

Load `020-maschine-drum-rig`. Then:
- Encoder 8 changes the selected group's fader on the touchscreen mixer, and the group button's brightness follows.
- Encoder 5 moves that strip's balance; the screen's PAN value goes negative left of centre and positive right.
- Switching group and turning either does **not** jump the new group's value.
- The VOL and PAN columns on the right screen track both.

- [ ] **Step 8: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(maschine): drive volume and pan from the mixer strip

LinuxSampler defines no controllers, so reading them off the engine stops
working the moment a group runs an SFZ kit. The mixer works on any engine,
already holds this driver's mutes, and is saved in snapshots."
```

---

### Task 4: Load kits and hold them per group

The driver gains a per-group kit model, with no control bound to it yet — that lands in Task 5. Splitting it keeps a reviewer able to reject the model without rejecting the control, and the model is the part with the API risk.

**Files:**
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `lib.parse_sfz_notes`, `lib.nearest_note`, `lib.kit_short_name` (Tasks 1-2).
- Produces: `_kit_list() -> list[tuple[str, str]]` of `(display_name, sfz_path)`; `_kit_notes(path) -> list[tuple[int, str]]`; `_apply_kit(group, index)`; `self.kit_index` list of 8 ints; `self.kit_pending` and `self.kit_due` used by Task 5.

- [ ] **Step 1: Add the constants**

Below `FALLBACK_KEYMAP_NOTES`:

```python
# The SFZ drum machines. The bank name is the directory under System SFZ as
# Zynthian lists it, and the kits are that bank's presets.
KIT_BANK = "Drum Machines"
# How long after the last encoder movement a kit is actually loaded. Sweeping
# the list then costs one load instead of one per step.
KIT_LOAD_DELAY_S = 0.15
```

- [ ] **Step 2: Add the per-group state**

In `__init__`, after `self.keymap_cache = [None] * 8`:

```python
        self.kit_index = [0] * 8             # which kit each group uses
        self.kit_cache = {}                  # sfz path -> [(note, name)]
        self.kits = None                     # [(display name, sfz path)], lazy
        self.kit_pending = None              # (group, index) waiting to load
        self.kit_due = 0.0                   # when that load is due, time.time()
```

and add `import time` to the imports at the top of the file, after `import socket`.

- [ ] **Step 3: Add the kit list and note lookup**

Put these just above `def _keymap(self, group):`

```python
    def _kit_list(self):
        """The available SFZ kits as [(display name, sfz path)], read once
        from the selected group's processor. Zynthian's own preset list is
        the source rather than a directory listing, so the names match what
        set_preset_by_name expects."""

        if self.kits is not None:
            return self.kits
        proc = self.chain_manager.get_synth_processor(self.group)
        if proc is None:
            logging.warning("Maschine: no synth processor, no kits")
            return []
        # Note this moves that processor's selected BANK, which the preset
        # browser on the touchscreen also uses. Harmless here because every
        # kit this driver sets lives in that same bank, but do not widen it
        # to other banks without rechecking that.
        try:
            proc.set_bank_by_name(KIT_BANK)
            proc.load_preset_list()
            # preset_list entries are [path, ?, name, ...] and the path may
            # carry an instrument index after a '#' (engine set_preset splits
            # on it), which is not part of the file name.
            self.kits = [(entry[2], entry[0].split("#")[0])
                         for entry in proc.preset_list]
            logging.info(f"Maschine: {len(self.kits)} kits in '{KIT_BANK}'")
        except Exception as e:
            logging.error(f"Maschine: kit list failed: {e}")
            self.kits = []
        return self.kits

    def _kit_notes(self, path):
        """A kit's playable notes, parsed from the .sfz once and cached."""

        notes = self.kit_cache.get(path)
        if notes is None:
            try:
                with open(path, errors="replace") as fh:
                    notes = lib.parse_sfz_notes(fh.read())
            except OSError as e:
                logging.error(f"Maschine: cannot read {path}: {e}")
                notes = []
            self.kit_cache[path] = notes
        return notes

    def _apply_kit(self, group, index):
        """Load a kit onto a group and land its note somewhere audible.

        The preset change itself must NOT hold self.lock - it talks to
        LinuxSampler over a socket and can block - but every zynseq read and
        write around it must. Hence the three phases."""

        kits = self._kit_list()
        if not kits:
            return
        index = max(0, min(len(kits) - 1, index))
        name, path = kits[index]
        proc = self.chain_manager.get_synth_processor(group)
        if proc is None:
            return

        with self.lock:                       # zynseq read
            current = self._group_note(group)

        t0 = time.time()                      # no lock held: this can block
        ok = proc.set_preset_by_name(name)
        logging.info(f"Maschine group {group}: kit '{name}' -> {ok} "
                     f"in {time.time() - t0:.3f}s")
        if not ok:
            return
        self.kit_index[group] = index
        self.keymap_cache[group] = self._kit_notes(path)

        # The old note almost never exists in the new kit, and a group on a
        # note its kit does not define is silent.
        available = [note for note, _ in self.keymap_cache[group]]
        landed = lib.nearest_note(available, current)
        with self.lock:                       # zynseq writes
            if landed is not None and landed != current:
                self._swap_note(group, current, landed)
                self.note_cache[group] = landed
            self._render_pads()
        # _preview plays on the SELECTED group's channel, so only preview a
        # kit change the player can actually hear.
        if landed is not None and group == self.group:
            self._preview(landed)

- [ ] **Step 4: Make the keymap come from the kit**

Replace the body of `_load_keymap` with:

```python
    def _load_keymap(self, group):
        """The notes available to a group: its kit's own list.

        Zynthian's keymaps.json resolves on the synth's preset path and
        matches only the FluidSynth soundfonts, so an SFZ kit would leave
        every group tab reading "note 36". The kit file has the real names."""

        kits = self._kit_list()
        if kits:
            _, path = kits[max(0, min(len(kits) - 1, self.kit_index[group]))]
            notes = self._kit_notes(path)
            if notes:
                return notes
        logging.info(f"Maschine group {group}: no kit notes, using the GM "
                     f"percussion range (names unavailable)")
        return [(note, f"note {note}") for note in FALLBACK_KEYMAP_NOTES]
```

Then delete the now-unused `KEYMAP_ROOT` constant and the `json` and `re` imports **if** nothing else uses them — check with `grep -n "KEYMAP_ROOT\|json\.\|re\." zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py` first and leave them if anything does.

- [ ] **Step 5: Check it compiles and deploy**

```bash
cd ~/zynth/zynthian-ui
python3 -m py_compile zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py && echo compile-ok
scp zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py root@192.168.2.123:/zynthian/zynthian-ui/zyngine/ctrldev/
ssh root@192.168.2.123 'systemctl restart zynthian; sleep 25; systemctl is-active zynthian'
```

- [ ] **Step 6: Verify the kit list is found**

With the rig snapshot loaded, check the log:

```bash
ssh root@192.168.2.123 'journalctl -u zynthian --since "-3min" --no-pager | grep -i "Maschine:.*kit"'
```

Expected: `Maschine: 41 kits in 'Drum Machines'` — but note this only appears once something calls `_kit_list()`, which nothing does until Task 5. If there is no line, that is correct at this point; the real check is that the rig still works exactly as before and nothing in the log errors.

- [ ] **Step 7: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(maschine): per-group kit model, notes read from the .sfz"
```

---

### Task 5: Kit on encoder 7, sample on encoder 6

**Files:**
- Modify: `zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py`

**Interfaces:**
- Consumes: `_apply_kit`, `_kit_list`, `self.kit_pending`, `self.kit_due` (Task 4); `_enc_steps_fixed`, `ENC_UNITS_DISCRETE`, `_cycle_sample` (already present).
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Handle both encoders in the MIDI dispatch**

In `_midi_event`, immediately after the existing pattern-encoder branch (`if cc_num in (CC_ENC_HITS, CC_ENC_ROT, CC_ENC_DIV, CC_ENC_LENGTH):`), add:

```python
            if cc_num == CC_ENC_SAMPLE:
                steps = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
                if steps:
                    self._cycle_sample(steps)
                return True
            if cc_num == CC_ENC_KIT:
                steps = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
                if steps:
                    self._nudge_kit(steps)
                return True
```

`_cycle_sample` already clamps at both ends of the note list and previews the new sound, and it takes a signed step count, so it needs no change.

- [ ] **Step 2: Add the deferred kit change**

Put this just above `def _apply_kit(self, group, index):`

```python
    def _nudge_kit(self, delta):
        """Move the selected group's kit choice. The load itself is deferred:
        the name on screen changes at once, and the kit is loaded once the
        knob stops, so sweeping the list costs one load rather than 41."""

        kits = self._kit_list()
        if not kits:
            return
        group = self.group
        current = self.kit_pending[1] if self.kit_pending and self.kit_pending[0] == group \
            else self.kit_index[group]
        index = max(0, min(len(kits) - 1, current + delta))
        if index == current:
            return
        self.kit_pending = (group, index)
        self.kit_due = time.time() + KIT_LOAD_DELAY_S
        with self.lock:
            self._render_display()

    def _commit_kit(self):
        """Load a kit whose delay has elapsed. Runs on the playhead thread,
        outside self.lock, because the preset change can block."""

        pending = self.kit_pending
        if pending is None or time.time() < self.kit_due:
            return
        self.kit_pending = None
        self._apply_kit(pending[0], pending[1])
```

- [ ] **Step 3: Drive the commit from the existing poll thread**

In `_playhead_loop`, the body currently opens with `with self.lock:`. Put the commit **before** that, so it never runs under the lock:

```python
        tick = 0
        while not self.stopping.wait(PLAYHEAD_POLL_S):
            try:
                tick += 1
                # Outside the lock on purpose: loading a kit talks to
                # LinuxSampler over a socket and can block.
                self._commit_kit()
                with self.lock:
```

The rest of the loop body is unchanged.

- [ ] **Step 4: Show both on screen**

In `_columns`, replace the two placeholder entries in the `screen == 1` branch:

```python
        if screen == 1:
            balance = self._mixer_balance(group)
            level = self._mixer_level(group)
            kits = self._kit_list()
            pending = self.kit_pending
            shown = pending[1] if pending and pending[0] == group else self.kit_index[group]
            kit_name = kits[shown][0] if 0 <= shown < len(kits) else ""
            kit_frac = (shown / (len(kits) - 1)) if len(kits) > 1 else 0.0
            notes = self._keymap(group)
            note = self._group_note(group)
            pos = next((i for i, (n, _) in enumerate(notes) if n == note), 0)
            smpl_frac = (pos / (len(notes) - 1)) if len(notes) > 1 else 0.0
            return (("PAN", str(int(round(balance * 50))), "b", round((balance + 1) / 2, 2)),
                    ("SMPL", str(pos + 1), "u", round(smpl_frac, 2)),
                    ("KIT", lib.kit_short_name(kit_name), "u", round(kit_frac, 2)),
                    ("VOL", str(int(round(level * 100))), "u", round(level, 2)))
```

- [ ] **Step 5: Check it compiles and deploy**

```bash
cd ~/zynth/zynthian-ui
python3 -m py_compile zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py && echo compile-ok
scp zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py root@192.168.2.123:/zynthian/zynthian-ui/zyngine/ctrldev/
ssh root@192.168.2.123 'systemctl restart zynthian; sleep 25; systemctl is-active zynthian'
```

- [ ] **Step 6: Verify on the hardware**

This still runs on the FluidSynth snapshot `020`, where `set_bank_by_name("Drum Machines")` will fail because FluidSynth has no such bank — so expect the KIT column to read `-` and the log to show no kits. **That is the correct result at this stage.** What to check now:

- Encoder 6 steps through the group's sounds and previews each, exactly as the arrow buttons do, and the SMPL number moves.
- Encoder 7 does nothing visible and logs no exception.
- Nothing else regressed: pads, mutes, transport, the pattern encoders.

The kit encoder is verified for real in Task 6, on the SFZ snapshot.

- [ ] **Step 7: Commit**

```bash
cd ~/zynth/zynthian-ui
git add zyngine/ctrldev/zynthian_ctrldev_maschine_mk2.py
git commit -m "feat(maschine): kit on encoder 7, sample on encoder 6"
```

---

### Task 6: The SFZ snapshot, and the whole thing verified

**Files:**
- Create (on the Pi): `/zynthian/zynthian-my-data/snapshots/000/021-maschine-drum-rig-sfz.zss`

**Interfaces:**
- Consumes: everything above.
- Produces: the snapshot the rig loads from now on. `020-maschine-drum-rig.zss` stays untouched as a fallback.

- [ ] **Step 1: Back up before touching snapshots**

```bash
ssh root@192.168.2.123 'D=/zynthian/zynthian-my-data/snapshots/.backup/pre-sfz-build-$(date +%F); mkdir -p "$D"; cp -n /zynthian/zynthian-my-data/snapshots/last_state.zss "$D/"; cp -n "/zynthian/zynthian-my-data/snapshots/000/020-maschine-drum-rig.zss" "$D/"; ls "$D"'
```

`last_state.zss` is the one at real risk — Zynthian rewrites it on every restart.

- [ ] **Step 2: Build the eight chains on the touchscreen**

Load `020-maschine-drum-rig` first, so the zynseq patterns and the mixer strips are already right; only the engines change.

For each group A-H, i.e. MIDI channels 1-8 in the UI: open the chain, change its engine to **LinuxSampler**, then set its preset to a kit from the **Drum Machines** bank. Give each group a different machine to start with, for example A `Roland TR808`, B `Roland TR909`, C `LINN9000 1`, D `SP1200 1`, E `Simmons`, F `Roland CR78`, G `Alesis HR16`, H `Yamaha RX11`.

**Do not use the webconf Snapshots page Name field and checkmark — that renames the selected bank.** It has already destroyed bank `000` once.

- [ ] **Step 3: Save it as a new snapshot**

On the touchscreen, go into bank `000` and choose the first entry, **"Save as new snapshot"**. Name it `maschine-drum-rig-sfz`. Confirm the file exists:

```bash
ssh root@192.168.2.123 'ls -la /zynthian/zynthian-my-data/snapshots/000/ | grep -i sfz'
```

- [ ] **Step 4: Reload it and check the driver picked the kits up**

Load the new snapshot from the touchscreen, then:

```bash
ssh root@192.168.2.123 'journalctl -u zynthian --since "-2min" --no-pager | grep -i "Maschine"'
```

Expected: a line reporting the kit count, e.g. `Maschine: 41 kits in 'Drum Machines'`.

- [ ] **Step 5: Verify the feature on the hardware**

With a pattern running:

- Group tabs show sounds from each group's own kit, not GM names.
- Encoder 7 sweeps kits: the KIT cell changes as you turn, and the kit loads shortly after you stop, previewing the sound.
- A group keeps its own kit — select another group, turn encoder 7, come back: the first group is unchanged.
- Encoder 6 moves through the current kit's sounds.
- Volume, pan and the F1-F8 mutes still work; the group buttons still show volume.
- The pattern keeps playing throughout, with no audible glitch.

- [ ] **Step 6: Verify it survives a save and reload**

Change two groups' kits, save over the snapshot from the touchscreen ("Save as new snapshot" then overwrite, or the existing entry), restart Zynthian, and reload. Both kits must come back, and the tabs must show the right sample names.

```bash
ssh root@192.168.2.123 'systemctl restart zynthian; sleep 25; systemctl is-active zynthian'
```

- [ ] **Step 7: Record the result**

Update `MD/todo.md`: mark the SFZ kit item done, note the snapshot name, and record anything that behaved unexpectedly. Update the deployed-HEADs table in `MD/CLAUDE.md`, and add the new control layout (encoder 6 = sample, 7 = kit, 5/8 = mixer, no expression) to its "Control layout as shipped" line.

- [ ] **Step 8: Commit and push everything**

```bash
cd ~/zynth/zynthian-ui
git push origin vangelis
cd ~/zynth-docs
git add MD/
git commit -m "docs: per-group SFZ kits shipped and verified"
git push origin master
```

---

## Notes for whoever executes this

- **Task 0 can stop the project.** Do not treat it as a formality. If a live preset change is slow or glitches, say so and stop — the spec has a fallback but it changes the design.
- Tasks 1 and 2 are pure functions and need no hardware. Tasks 3-6 all need the Pi.
- After every deploy, wait ~25 s before touching the device: Zynthian takes that long to come up and bind the driver.
- If the rig ever goes completely dead — no pads, no screens — the usual cause is that `maschine-mk2.service` was restarted without restarting `zynthian` afterwards.
- If pad colours die on first touch, `external_pad_leds` has been wiped from the daemon's `maschine.json` on the Pi. It is not in git there; a `git reset --hard` removes it every time.
