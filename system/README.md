# System files

Deployed configuration, taken off a working rig and verified by checksum.

| File | Installs to | Why it matters |
|---|---|---|
| `99-maschine.rules` | `/etc/udev/rules.d/` | Gives the MK2 a stable `/dev/maschine` symlink, mode `0664`, group `audio`, and restarts the daemon on plug / stops it on unplug. Vendor `17cc`, product `1140`. |
| `maschine-mk2.service` | `/etc/systemd/system/` | The HID daemon. `ExecStartPost` runs `maschine-jack-connect.sh`. **`ExecStart` and `WorkingDirectory` are rewritten by `install.sh`** to wherever this repository was cloned. |
| `maschine-clock.service` | `/etc/systemd/system/` | JACK transport → MIDI clock bridge. |
| `maschine-jack-connect.sh` | `/usr/local/bin/` | Waits for the daemon's `a2j` port and sets the alias `virtual:maschine.rs/Maschine MK2 Pads` on it. **It deliberately does not connect the port** — patched `zynautoconnect` whitelists it and assigns its own zmip slot, and a second connection from here was the cause of the duplicate-route fault that made every pad tap fire twice. |
| `maschine-clock-bridge.py` | `/usr/local/bin/` | The clock bridge itself. |
| `maschine-clock-connect.sh` | `/usr/local/bin/` | Wires the bridge's ports. |
| `zynthian-maschine-order.conf` | `/etc/systemd/system/zynthian.service.d/10-maschine-order.conf` | Makes the boot order **structural**: `After=` plus `Wants=maschine-mk2.service` on Zynthian's own unit, as a drop-in rather than an edit, so a ZynthianOS update leaves it alone and nothing has to be re-run. `Wants=`, never `Requires=` — the udev rule stops the daemon on unplug, and `Requires=` would take the UI down with it. `PartOf=` was rejected from both ends for the same reason. **It does not cover a hand restart**: `systemctl restart maschine-mk2` on its own still needs the UI restarted after it, which is why the prose below and `tools/deploy-to-pi.sh` still matter. |
| `maschine.json` | the daemon's working directory | Pad note offsets and encoder CC numbers, **`"external_pad_leds": true`** — without it the daemon repaints pads on press and release in its own colour, and the first touch destroys the per-channel picture — and the panel's `screen_brightness` / `screen_contrast`, described below. |

`tests/test-system-files.sh` is the automated check for everything in this
table — 55 assertions (measured 2026-09-01), WSL only, no Pi and no hardware:

    bash system/tests/test-system-files.sh

`tests/test-dry-run.sh` is the other half — 76 assertions (measured 2026-08-22)
on what `install.sh --dry-run`, `bootstrap.sh --dry-run` and
`tools/deploy-to-pi.sh --dry-run` **print**. Ten of them are `bootstrap.sh`'s,
added 2026-08-22 when `018` became the factory snapshot: that `018` goes into
bank `000` **and** over `default.zss`, that `017` goes into the bank and
**never** over it, and that no genre snapshot is ever the default:

    bash system/tests/test-dry-run.sh

`ssh`, `scp`, `systemctl`, `udevadm`, `apt-get`, `cargo`, `install` and `rsync`
are shadowed by stubs that exit 99 if called, so a dry run that actually
executes something fails there rather than on a rig. It pins the daemon-first
restart order in both scripts by line number, and that the deploy path never
names `maschine.json`, a unit or the udev rule.

`test-system-files.sh` parses the helpers, pins the udev rule and
`maschine.json` field by field,
checks the unit ordering, confirms `install.sh` still enables exactly these
three units, that it installs the ordering drop-in, and that its path rewrites leave no `/root` path behind, and runs
`systemd-analyze verify` on all three units inside a `mktemp -d` fake root with
every `Exec*=` binary stubbed. Where `systemd-analyze` is absent that group
**skips** rather than passing.

**`maschine.json` here is the TEMPLATE, and the live copy is deliberately
untracked.** `config.rs` reads `maschine.json` relative to its working
directory, and `maschine-mk2.service` sets that to `daemon/`, so the file the
daemon actually reads is `daemon/maschine.json`. `install.sh` copies this
template there **only if it is absent** — a rig whose config has been edited by
hand must survive a reinstall — and `deploy-to-pi.sh` never sends it at all.
The live copy is in `.gitignore`. **Do not track it.** Committing it publishes
one machine's settings, and tracking the path would make a pull on any rig fail
on the untracked file sitting there; the obvious unblock is deleting it, which
silently drops `external_pad_leds`.

## Screen brightness and contrast — and how to recover a dark panel

```json
"screen_brightness": 72,
"screen_contrast": 50
```

**These two are the factory values, measured off this hardware on 2026-08-31,
and they are here so that recovery is a file you already have rather than a
number in somebody's notes.** Both screens read 72 and 50 from the factory.

Range is 0-100, taken from the device's own report descriptor. The daemon
clamps to **1-100**: it will not write 0.

### Why this is more careful than a normal setting

The two values live in HID **feature** reports `0xF8` (left screen) and `0xF9`
(right screen) — a different mechanism from every other write the daemon makes,
and the device declares every field in them **Non-volatile**. A written value
therefore survives a power cycle. **A bad write does not clear itself by
unplugging the controller**, on a device whose one known failure mode already
needs a physical replug, and a dark panel cannot explain why it is dark.

So the daemon:

- does **nothing at all** unless *both* keys are present — a rig whose
  `maschine.json` predates them is untouched, reads included;
- **reads the report first** and checks that its constant bytes decode as this
  panel's own geometry (256 x 64) before believing it is the right report;
- **echoes every byte it did not author** — the report id, the seven bytes the
  device declares constant, and the eight flag bits in byte 10 that nobody has
  identified;
- **skips the write entirely** when the device already holds the requested
  pair, so a rig on the shipped defaults issues no feature write at all;
- applies them **once, at start-up**, and from nowhere else. There is no live
  control on purpose: a control that dims a screen can dim the screen you need
  in order to see the control.

Every branch of that prints a line to the journal, including the report it read
and the report it wrote.

### Recovering a screen you cannot read

1. `ssh root@<pi>` and edit `daemon/maschine.json` — **not** `system/maschine.json`,
   which is only the template.
2. Set `"screen_brightness": 72` and `"screen_contrast": 50`.
3. Restart **daemon first, UI second** (below), or run `tools/deploy-to-pi.sh`.
4. `journalctl -u maschine-mk2 -b | grep '^screen '` shows what was read and
   what was written.

Which of the two device bytes is really brightness and which is contrast is
still unproven — the descriptor lists the two usages out of order and only a
write settles it. It does not matter for recovery: both are restored the same
way.

Restart order is always **daemon first, UI second**. Restarting the daemon alone
makes `a2j` re-register its port on a new zmip slot while the ctrldev driver
stays bound to the dead one: the rig goes silent with no error in any log.
