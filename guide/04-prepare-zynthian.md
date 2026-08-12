# 4 · Prepare Zynthian

The snapshot in section 5 names five engines and two effect plugins. If any of
them is missing, the snapshot loads with silent channels and no clear
explanation. This section makes sure everything it names exists first.

---

## Step 1 — Install the packaged plugins

Three of the five engines are Debian packages on ZynthianOS:

```bash
apt install -y obxd-lv2 padthv1-lv2 tap-lv2
```

| Package | Provides | Used by |
|---|---|---|
| `obxd-lv2` | `/usr/lib/lv2/Obxd.lv2` | channel **G LEAD** |
| `padthv1-lv2` | `/usr/lib/lv2/padthv1.lv2` | channel **H PADS** |
| `tap-lv2` | `/usr/lib/lv2/tap-reverb.lv2` and `/usr/lib/lv2/tap-echo.lv2` | **all sixteen inserts** — TAP Reverberator and TAP Stereo Echo |

**Verify:**

```bash
dpkg -s obxd-lv2 padthv1-lv2 tap-lv2 | grep ^Status
# → Status: install ok installed   (three times)
```

---

## Step 2 — Confirm JC303

The bass engine is **not** a Debian package. It comes from Zynthian's own plugin
set:

```bash
ls -d /zynthian/zynthian-plugins/lv2/JC303.lv2
```

If it is missing, install it through webconf's LV2 plugin management rather than
by hand, so Zynthian's plugin cache learns about it.

**Verify:** the directory exists.

---

## Step 3 — Enable the plugins and regenerate the LV2 cache

**A plugin that is installed but not enabled is invisible to a snapshot.**
Zynthian keeps its own list of which LV2 plugins may be used as engines, and
loading a snapshot that names a disabled plugin gives you a chain with no engine.

In webconf:

1. Go to **Engines**.
2. Find and enable **Obxd**, **padthv1**, **JC303**, **TAP Reverberator** and
   **TAP Stereo Echo**.
3. Press **Regenerate LV2 Cache**.

The cache scan walks every bundle in the LV2 search path and takes a while. Let
it finish before loading anything.

**Verify:** all five appear as available engines in webconf's Engines list.

---

## Step 4 — Confirm the SFZ drum kits

The five drum channels run LinuxSampler on SFZ drum-machine kits:

```bash
find "/zynthian/zynthian-data/soundfonts/sfz/Drum Machines" -maxdepth 1 -type f -name '*.sfz' | wc -l
# → 40   (on the rig this was written from)
```

On the author's rig that directory holds **40 kit files** — Roland TR-808, TR-909,
TR-727, TR-606, LinnDrum, SP-1200, Akai XR10, Alesis HR16, Simmons and more —
plus a `Samples/` directory holding the actual audio.

Two details worth knowing before you count them yourself:

- **Use `find -type f`, not `ls`.** One entry, `DYNOSAUR-808.sfz`, is a
  *directory*, so `ls` on a `*.sfz` glob lists its contents and reports far more
  kits than exist. That is a counting trap, not a broken kit.
- **These kits are not in any git repository.** `soundfonts/sfz/**` is gitignored
  in `zynthian-data`, so they arrive with the 7.5 GB OS image. They are believed
  to be stock, but that could not be proved without a fresh flash — hence a check
  here instead of a claim.

If the directory is missing or empty, the five drum channels will load and be
silent. The fix is to put SFZ drum kits there; any kit with a `.sfz` file and its
samples will do, and the driver reads note names out of the `.sfz` itself.

**Verify:** the count is greater than zero, and `ls` shows kit names you
recognise.

---

## Step 5 — Run the preflight

```bash
bash tools/check-prereqs.sh; echo "exit=$?"
```

It prints one line per dependency and exits with the number of misses. Expected
output at this point in the guide:

```
ZynthianOS
  PRESENT  ZynthianOS Oram-2601-1
LV2 plugins
  PRESENT  obxd-lv2
  PRESENT  padthv1-lv2
  PRESENT  tap-lv2
  PRESENT  /usr/lib/lv2/Obxd.lv2
  PRESENT  /usr/lib/lv2/padthv1.lv2
  PRESENT  /usr/lib/lv2/tap-reverb.lv2
  PRESENT  /usr/lib/lv2/tap-echo.lv2
  PRESENT  /zynthian/zynthian-plugins/lv2/JC303.lv2
Drum kits
  PRESENT  40 SFZ kits in /zynthian/zynthian-data/soundfonts/sfz/Drum Machines
Driver
  PRESENT  zynthian_ctrldev_maschine_mk2.py
  PRESENT  techno_lib.py
  PRESENT  maschine_mk2_lib.py
  PRESENT  zynautoconnect patched
Services
  PRESENT  maschine-mk2 active
  PRESENT  maschine-web active
  PRESENT  maschine-clock active
  PRESENT  /dev/maschine
JACK routing
  PRESENT  daemon MIDI port visible in JACK
  MISSING  0 TAP ports, expected 64 - is the snapshot loaded?
Snapshot
  MISSING  /zynthian/zynthian-my-data/snapshots/000/017-generative-techno.zss
```

**Two MISSING lines are correct here**: the snapshot has not been copied yet, and
with no snapshot loaded there are no TAP plugin instances running. Everything
else must read PRESENT before you go on. Section 6 runs this same script again
after the import, where it must exit `0`.

---

**Next:** [5 · Import the snapshot](05-import-snapshot.md)
