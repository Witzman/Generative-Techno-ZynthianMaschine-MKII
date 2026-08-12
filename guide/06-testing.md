# 6 · Testing

Two halves, and the split is the point: what a machine can check, and what only
your ears can.

Every command below was run on the rig this guide was written from, and the
outputs shown are the real ones.

---

## Machine-checkable

### The unit tests

Run these anywhere — a laptop, no Pi, no Maschine attached.

```bash
cd ctrldev && python3 -m unittest discover -s tests -q
```

```
Ran 271 tests in 0.012s

OK
```

**These are the only automated proof this project has, and it is worth knowing
why.** The driver itself cannot be imported off the Pi: it needs `zynlibs.zynseq`,
which exists only there. So everything generative and everything presentational
was pushed down into `techno_lib.py`, which has no Zynthian imports at all — the
Turing register and its mutation, the undo ring, register-to-pitch quantisation,
the euclidean placement, the gate mask, the page and column model, the
four-character value cells. That module is tested. The driver's plumbing around
it is verified by hand, on hardware.

The tests include the invariant the whole instrument rests on: that `RANDOM` at 0
produces a byte-identical register forever, checked over 500 iterations rather
than asserted in a comment.

### The preflight

On the Pi:

```bash
bash tools/check-prereqs.sh; echo "exit=$?"
```

```
exit=0
```

After the snapshot is loaded this must exit **0**. Before it, two MISSING lines
are expected — see [section 4](04-prepare-zynthian.md).

### The rig

All on the Pi, with the snapshot loaded and playing.

```bash
jack_lsp | grep -c TAP
```
```
64
```

Sixteen insert instances, four ports each. Fewer means plugin hosts failed to
start.

```bash
jack_lsp -c | awk '/\(capture\): Pads MIDI/{f=1;next} /^[^ ]/{f=0} f&&/ZynMidiRouter/{print "  route: " $1; c++} END{print "count=" c+0}'
```
```
  route: ZynMidiRouter:dev2_in
count=1
```

**Count exactly one. Do not check for a particular slot number.** The helper
script asks for `dev3_in`, but Zynthian assigns the slot itself once the
`zynautoconnect` patch is in place, and the number differs between rigs and
across reboots. What matters is that there is *one*: two routes make every pad
tap fire twice, and that is a stale connection left by an earlier session, since
`zynautoconnect` only tears down connections it made itself and `jackd` outlives
a Zynthian restart.

Do not use `grep -A3 "Pads MIDI"` for this. The daemon exposes several ports and
`jack_lsp -c` interleaves their connection blocks, so a fixed-window `grep`
over-counts — it reported four routes on a rig that has one.

```bash
journalctl -u zynthian --since -5min | grep -icE "traceback|error|segfault"
```
```
0
```

```bash
journalctl --since -20min | grep -c "watchdog: input stalled, reopened"
```
```
26
```

**The watchdog line is healthy.** The MK2's input dies every few seconds under a
kernel hidraw fault, and the daemon closes and reopens the device to recover. One
reopen every 8 seconds or so is the normal baseline; 26 in twenty minutes is
about one per 46 seconds, which is comfortably better. A sudden jump to many per
second is a regression worth reporting.

---

## By ear

Nothing in this repository can hear. This half is yours, and the factory snapshot
is not signed off until it passes.

### The beat

- **A KICK** — four on the floor, steps 0, 4, 8, 12.
- **B SNAR** — backbeat, steps 4 and 12.
- **C CLAP** — syncopated, steps 3, 8, 13.
- **D CHAT** — offbeat sixteenths, the odd steps.
- Select each channel with its **Group** button and watch the pads: bright pads
  are active steps, the white pad is the playhead, dark pads are beyond the
  pattern's length.

### The three kinds of authorship

- **F BASS** repeats *exactly* the same line, bar after bar. This is `LOCK` —
  `RANDOM` at 0 means the driver skips the rewrite entirely, so the loop cannot
  drift. Listen for a full minute; any change at all is a defect.
- **G LEAD** plays a different phrase roughly every bar, but a *related* one —
  the register mutates one bit at a time rather than being replaced.
- **H PADS** sounds one long note per loop, and its pattern is 8 steps where
  everything else is 16, so it lands twice as often as a bar.
- **E OHAT** is a drum kit walked by a Turing register: the *sound* changes as the
  register moves through the kit's note list, not the pitch.

### The surface

- **F1-F8** mute channels A-H regardless of which channel is selected. A tap
  latches; a hold over 250 ms is momentary and releases when you let go.
- **SOLO held** plus an F button is momentary solo. **SOLO tapped** latches, and
  the whole F row means solo until you tap it again. Solo is additive, not
  exclusive.
- **ERASE alone does nothing.** ERASE plus a pad clears that step; ERASE plus a
  Group silences that channel — HITS to 0 on a drum, play chance to 0 on a voice.
- **Restart** jumps every channel to step 0 without stopping.
- A **dashed tab** means that channel is not sounding. It is the instrument's only
  way of explaining silence, so read it before assuming a fault.

### The send contract

This one is worth doing deliberately, because it is the property the whole
encoder layout depends on.

1. Select any channel, press **CONTROL**.
2. Sweep **encoder 7 (REVERB)** from 0 to 100.
3. **The dry signal must still be there, at the same level, at the top.**

If the dry fades as the wet comes up, the insert is a dry/wet crossfade rather
than a true wet level, and encoders 7 and 8 have stopped being sends. Every
cheaper reverb and delay tested for this rig failed exactly that way.

Expect the knob to feel back-heavy: 0-100 maps onto −70 dB … +10 dB, so 25 is
inaudible, 50 is barely there, 88 equals dry, and the musically useful travel is
roughly **60 to 100**.

### Two things to set after loading

- **MASTER**, on the ALL page, near 80 — this snapshot does not store a main-strip
  level, so the main fader stays wherever it was.
- Watch the main meter if you open several wets at once. Both inserts pass dry at
  unity and add wet on top of it.

---

**Next:** [7 · Playing](07-playing.md)
