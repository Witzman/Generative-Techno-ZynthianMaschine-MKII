# System files

Deployed configuration, taken off a working rig and verified by checksum.

| File | Installs to | Why it matters |
|---|---|---|
| `99-maschine.rules` | `/etc/udev/rules.d/` | Gives the MK2 a stable `/dev/maschine` symlink, mode `0664`, group `audio`, and restarts the daemon on plug / stops it on unplug. Vendor `17cc`, product `1140`. |
| `maschine-mk2.service` | `/etc/systemd/system/` | The HID daemon. `ExecStartPost` runs `maschine-jack-connect.sh`. **`ExecStart` and `WorkingDirectory` are rewritten by `install.sh`** to wherever this repository was cloned. |
| `maschine-web.service` | `/etc/systemd/system/` | Serves the LED/config web editor on port 9000. |
| `maschine-clock.service` | `/etc/systemd/system/` | JACK transport → MIDI clock bridge. |
| `maschine-jack-connect.sh` | `/usr/local/bin/` | Connects the daemon's `a2j` port to `ZynMidiRouter:dev3_in` and sets the port alias `virtual:maschine.rs/Maschine MK2 Pads`. Zynthian derives a control-device id from the part of the alias after the first `/`, and `a2j` gives user-client ports no alias at all — without this the ctrldev driver can never bind. |
| `maschine-clock-bridge.py` | `/usr/local/bin/` | The clock bridge itself. |
| `maschine-clock-connect.sh` | `/usr/local/bin/` | Wires the bridge's ports. |
| `maschine.json` | the daemon's working directory | Pad note offsets and encoder CC numbers, and **`"external_pad_leds": true`** — without it the daemon repaints pads on press and release in its own colour, and the first touch destroys the per-channel picture. |

Restart order is always **daemon first, UI second**. Restarting the daemon alone
makes `a2j` re-register its port on a new zmip slot while the ctrldev driver
stays bound to the dead one: the rig goes silent with no error in any log.
