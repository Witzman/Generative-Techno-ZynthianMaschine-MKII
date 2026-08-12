# 3 · Install the Driver and Daemon

This is the section where things fail silently if a step is skipped, so every
step says what breaks without it.

Two pieces of software are involved:

- **The daemon** (`daemon/`, Rust) talks HID to the Maschine MK2 and exposes its
  pads, buttons, encoders and displays as ALSA MIDI plus an OSC drawing API.
- **The driver** (`ctrldev/`, Python) is a Zynthian *ctrldev* driver — Zynthian's
  plug-in point for a control surface. It receives the Maschine's MIDI before
  anything else touches it and reaches into the running instrument: the chain
  manager, the mixer, the sequencer library.

At the end of this section the Maschine draws its own screens and lights its own
buttons **with no chains and no snapshot loaded at all**. That is the point of
doing it before any sound exists: it separates "the surface works" from "the
instrument is configured".

Clone the repository on the Pi first. Anywhere is fine — `install.sh` adapts the
systemd units to wherever it sits.

```bash
ssh root@192.168.2.123
git clone https://github.com/Witzman/Generative-Techno-ZynthianMaschine-MKII.git
cd Generative-Techno-ZynthianMaschine-MKII
```

---

## Step 1 — Build the daemon

```bash
apt install -y rustc cargo
cd daemon && cargo build --release && cp picturetest.png target/release/
```

This takes **minutes** on a Pi 4. Do not interrupt it.

**Verify:** `ls -la daemon/target/release/maschine` exists and is executable.

---

## Step 2 — Put the daemon config in place

```bash
cp system/maschine.json daemon/maschine.json
grep external_pad_leds daemon/maschine.json
# → "external_pad_leds": true
```

`maschine.json` carries the pad note offsets, the encoder CC numbers, and one
flag that matters more than it looks:

**Without `"external_pad_leds": true` the daemon repaints the pads itself** on
every press and release, in its own global colour. The driver owns the pad
colours — dim for an empty step, bright for an active one, white for the
playhead, amber for a played-in step — and the first pad you touch destroys that
picture.

The flag is not in the upstream daemon's git history, so a `git reset --hard` in
a daemon checkout wipes it. Re-set it after any deploy that touches the daemon.

**Verify:** the `grep` prints the line above.

---

## Step 3 — Install the udev rule

```bash
install -m 0644 system/99-maschine.rules /etc/udev/rules.d/99-maschine.rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw
ls -la /dev/maschine
```

The rule matches vendor `17cc`, product `1140` and does three things: gives the
device mode `0664` and group `audio` so the daemon need not own the raw node,
creates the stable `/dev/maschine` symlink, and restarts the daemon on plug and
stops it on unplug.

Without the symlink the daemon has to be pointed at a `/dev/hidrawN` number
that moves between boots.

**Verify:** `/dev/maschine` exists and points at a `hidraw` node.

---

## Step 4 — Install the helper scripts

```bash
install -m 0755 system/maschine-jack-connect.sh /usr/local/bin/
install -m 0755 system/maschine-clock-bridge.py /usr/local/bin/
install -m 0755 system/maschine-clock-connect.sh /usr/local/bin/
```

`maschine-jack-connect.sh` is the important one. It waits for the daemon's `a2j`
port to appear in JACK, connects it to `ZynMidiRouter:dev3_in`, and then sets a
port alias:

```
virtual:maschine.rs/Maschine MK2 Pads
```

**Zynthian derives a control-device id from the part of a JACK port alias after
the first `/`, and `a2j` gives user-client ports no alias at all.** Without this
alias the ctrldev driver has no device id to bind to, and it will never load no
matter what else is correct.

**Verify:** all three files exist in `/usr/local/bin` and are executable.

---

## Step 5 — Install and enable the systemd units

```bash
./install.sh --dry-run     # see exactly what the next commands will do
```

Then, doing it by hand rather than with the installer:

```bash
install -m 0644 system/maschine-mk2.service   /etc/systemd/system/
install -m 0644 system/maschine-web.service   /etc/systemd/system/
install -m 0644 system/maschine-clock.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now maschine-mk2 maschine-web maschine-clock
```

> **If you cloned anywhere other than `/root/Generative-Techno-ZynthianMaschine-MKII`,
> edit `ExecStart` and `WorkingDirectory` in `maschine-mk2.service` to match, and
> `--directory` in `maschine-web.service`.** `install.sh` does this rewrite for
> you; by hand, it is on you.

The three units are: the daemon itself (with
`ExecStartPost=/usr/local/bin/maschine-jack-connect.sh`), the LED and config web
editor on port 9000, and the JACK-transport-to-MIDI-clock bridge.

**Verify:** `systemctl is-active maschine-mk2` prints `active`, and the MK2's
displays light up.

---

## Step 6 — Let `a2jmidid` export software clients

The daemon's MIDI port is an ALSA sequencer port, and it only appears in JACK if
`a2jmidid` is running with software-client export enabled. On ZynthianOS this is
a webconf setting; confirm it from the shell:

```bash
jack_lsp | grep "Pads MIDI"
# → a2j:maschine rs [N] (playback): Maschine MK2 Pads MIDI
```

Without this there is no JACK port, so step 4's script has nothing to connect and
nothing to alias.

**Verify:** the `grep` finds a `Pads MIDI` port.

---

## Step 7 — Patch `zynautoconnect`

```bash
python3 tools/patch-autoconnect-maschine.py
# → zynautoconnect patched: whitelist + stable uid
```

This is the **only** change to a Zynthian core file, and it ships as a patcher
rather than as a copy of the author's file, so it edits *your* version instead of
overwriting it. It is idempotent — run twice and it says
`already patched, nothing to do`.

It does two things:

1. Adds `maschine rs.*Pads MIDI` to the list of ports Zynthian treats as
   **hardware MIDI sources**, so the port is given a **zmip slot**.
2. Pins the stable uid `virtual:maschine.rs/Maschine MK2 Pads`, because the ALSA
   client number embedded in the port name changes across boots and a ctrldev
   driver binds by device id.

Without it, Zynthian lists the driver as **Found** and never **Loaded**, and the
rig does nothing at all with no error in any log. That is the single most
confusing failure in this project.

**Re-run this after every Zynthian system update.** An update replaces
`zynthian_autoconnect.py` and takes the binding with it.

**Verify:**

```bash
grep -c "maschine rs.*Pads MIDI" /zynthian/zynthian-ui/zynautoconnect/zynthian_autoconnect.py
# → 1 or more
```

---

## Step 8 — Copy the three driver files

```bash
install -m 0644 ctrldev/zynthian_ctrldev_maschine_mk2.py \
                ctrldev/techno_lib.py \
                ctrldev/maschine_mk2_lib.py \
                /zynthian/zynthian-ui/zyngine/ctrldev/
```

Two warnings, both learned the hard way.

**Copy files. Never use git in `/zynthian/zynthian-ui`.** These three files are
untracked drop-ins in a checkout that tracks an upstream branch. A
`git reset --hard` or a bundle checkout there deletes them, along with the
running instrument.

**Every module in that directory needs a `dev_ids` attribute.** Zynthian's driver
manager globs every `*.py` in `zyngine/ctrldev/`, imports it, and reads
`dev_ids` off it. `techno_lib.py` and `maschine_mk2_lib.py` are helpers and
carry `dev_ids = []` for exactly this reason. Remove it from either and the whole
Zynthian UI crash-loops every 14 seconds.

**Verify:** all three files are present, and
`grep -l dev_ids /zynthian/zynthian-ui/zyngine/ctrldev/{zynthian_ctrldev_maschine_mk2,techno_lib,maschine_mk2_lib}.py`
lists all three.

---

## Step 9 — Restart: daemon first, UI second

```bash
systemctl restart maschine-mk2
sleep 8
systemctl restart zynthian
```

**The order is not a style preference.** Restarting the daemon alone makes `a2j`
re-register the Pads port onto a *new* zmip slot while the ctrldev driver stays
bound to the dead one. The rig goes silent, no error appears anywhere, and a
second stale route is left behind that makes every later pad tap fire twice.

Restarting the UI alone is harmless.

**Verify:** Zynthian's UI comes back on the display.

---

## Step 10 — Confirm the surface is alive

Three checks, in this order.

```bash
journalctl -u zynthian --since -3min | grep -i ctrldev
```

You want a line saying the driver was **Loaded**. *Found* alone means step 7 did
not take effect.

```bash
jack_lsp -c | grep -A3 "Pads MIDI"
```

Exactly **one** `ZynMidiRouter:devN_in` connection. Two means a stale route from
an earlier session is still alive — `zynautoconnect` only tears down connections
it made itself, and `jackd` outlives a Zynthian restart. Extra routes make every
pad tap fire twice.

Then look at the hardware. With **no snapshot loaded**, the MK2 should show:

- the left display drawing the tab row `A KICK`, `B SNAR`, `C CLAP`, `D CHAT`,
  the right drawing `E OHAT`, `F BASS`, `G LEAD`, `H PADS`
- a dotted rule under the tabs and four encoder columns on each screen
- the eight Group buttons lit in their channel colours, warm for drums and cool
  for voices
- the **CONTROL** button lit

The channels sit at a flat mid brightness and nothing makes sound, because no
chains exist yet. That is the correct state at the end of this section.

---

## The scripted equivalent

Everything above is what `install.sh` runs, in the same order:

```bash
./install.sh --dry-run     # print every action, change nothing
./install.sh               # do it
```

It refuses to run anywhere but a ZynthianOS Pi, backs up every file it
overwrites with a `.bak` suffix, rewrites the units' paths to wherever the repo
is, and verifies nothing itself — it prints the verification commands and hands
back to this page.

The guide is authoritative. The script is a convenience.

---

## When it does not work

| Symptom | Cause | Fix |
|---|---|---|
| Displays blank, buttons dark, Zynthian fine | daemon not running | `systemctl status maschine-mk2`, then `journalctl -u maschine-mk2 -n 50` |
| Driver **Found** but never **Loaded** | no zmip slot | Step 7, then restart daemon and UI |
| Nothing at all, and `jack_lsp` shows no `Pads MIDI` | `a2jmidid` not exporting software clients | Step 6 |
| Every pad tap fires twice | a stale JACK route | Step 10, disconnect the extra `devN_in` |
| Whole UI restarts every ~14 seconds | a module in `ctrldev/` without `dev_ids` | Step 8 |
| First pad touch destroys the pad colours | `external_pad_leds` missing | Step 2, then restart the daemon **and** the UI |
| Input dies after a few seconds, then recovers | kernel hidraw fault; the daemon closes and reopens the device | Nothing to do. `watchdog: input stalled, reopened …` about once every 8 s in the journal is **healthy** |

---

**Next:** [4 · Prepare Zynthian](04-prepare-zynthian.md)
