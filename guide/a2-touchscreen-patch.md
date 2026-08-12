# Appendix A2 · Touchscreen Coordinate Patch

**Optional.** Not part of the instrument. Apply it only if you have the symptom
below.

---

## Who needs this

Your touchscreen reports touches at the wrong place — usually compressed into one
corner or scaled toward one edge — while the same screen displays correctly.

That happens when the panel's touch controller reports coordinates in its own
native resolution while Zynthian's UI is running at a different configured display
size. Zynthian passes the raw touch value straight through, so a panel reporting
0-4095 on a 800×480 UI puts every touch in the top-left eighth of the screen.

This was the case on the rig this guide was written from: an Elecrow 5" 800×480
panel, HDMI for video and USB for touch.

**If your touch already lands where you press, skip this page.** The patch edits a
Zynthian core file, and there is no reason to carry a change you do not need.

---

## The patch

It scales the raw touch value onto Zynthian's configured display size, guarding
against a zero maximum so an unreported range cannot divide by zero.

File: `/zynthian/zynthian-ui/zyngui/multitouch.py`, in `MultiTouch`'s evdev event
loop.

```diff
@@ class MultiTouch(object):
                  elif evdev_event.code == ecodes.ABS_MT_POSITION_X:
 -                    if self._invert_x:
 -                        self._current_touch.x_root = self.max_x - evdev_event.value
 -                    else:
 -                        self._current_touch.x_root = evdev_event.value
 +                    raw = self.max_x - evdev_event.value if self._invert_x else evdev_event.value
 +                    self._current_touch.x_root = int(raw * zynthian_gui_config.display_width / self.max_x) if self.max_x else raw
                      if self._current_touch not in self.events:
                          self.events.append(self._current_touch)
                  elif evdev_event.code == ecodes.ABS_MT_POSITION_Y:
 -                    if self._invert_y:
 -                        self._current_touch.y_root = self.max_y - evdev_event.value
 -                    else:
 -                        self._current_touch.y_root = evdev_event.value
 +                    raw = self.max_y - evdev_event.value if self._invert_y else evdev_event.value
 +                    self._current_touch.y_root = int(raw * zynthian_gui_config.display_height / self.max_y) if self.max_y else raw
                      if self._current_touch not in self.events:
                          self.events.append(self._current_touch)
```

Both hunks keep the existing `_invert_x` / `_invert_y` handling and only add the
scaling on top of it.

---

## Applying it

Back the file up first — this is a Zynthian core file, not one of ours.

```bash
ssh root@<pi>
cp /zynthian/zynthian-ui/zyngui/multitouch.py \
   /zynthian/zynthian-ui/zyngui/multitouch.py.bak
# edit the two handlers as shown above
systemctl restart zynthian
```

**Verify:** press each corner of the screen and confirm the UI responds at that
corner.

To undo it:

```bash
cp /zynthian/zynthian-ui/zyngui/multitouch.py.bak \
   /zynthian/zynthian-ui/zyngui/multitouch.py
systemctl restart zynthian
```

---

## Two warnings

**A Zynthian update overwrites it.** `multitouch.py` is tracked in the
`zynthian-ui` checkout, so any update replaces your edit. Keep the `.bak`, and
expect to re-apply after upgrading.

**Do not run `git checkout` or `git reset` in `/zynthian/zynthian-ui` to undo
this.** That directory also holds this project's three driver files as *untracked*
drop-ins; a hard reset removes the instrument along with the patch. Restore from
the `.bak` copy instead.

---

**Back to:** [Appendix A1 · How 017 was built](a1-how-017-was-built.md) ·
[1 · What It Is](01-what-it-is.md)
