"""SP5 probe: can a note be longer than one step, and what happens at the
pattern end?

Runs in its own process, so it loads its own libzynseq instance and cannot
touch the running rig's patterns. Uses a scratch pattern id far above the
snapshot's 10-17.
"""
import ctypes

lib = ctypes.CDLL("/zynthian/zynthian-ui/zynlibs/zynseq/build/libzynseq.so")
lib.getNoteDuration.restype = ctypes.c_float
lib.getNoteDuration.argtypes = [ctypes.c_uint32, ctypes.c_uint8]
lib.getNoteVelocity.argtypes = [ctypes.c_uint32, ctypes.c_uint8]
lib.addNote.argtypes = [ctypes.c_uint32, ctypes.c_uint8, ctypes.c_uint8,
                        ctypes.c_float, ctypes.c_float]
lib.init(b"sp5probe")
PAT = 900

def fresh(spb, beats):
    lib.selectPattern(PAT)
    lib.clear()
    lib.setStepsPerBeat(spb)
    lib.setBeatsInPattern(beats)
    return lib.getSteps()

print("=== 1. does a quarter-note division exist? spb=1 ===")
for spb, beats in ((1, 16), (1, 8), (2, 8), (4, 4)):
    steps = fresh(spb, beats)
    cps = lib.getClocksPerStep()
    print("  spb=%-2d beats=%-3d -> steps=%-3d clocks/step=%-3d spb_readback=%d"
          % (spb, beats, steps, cps, lib.getStepsPerBeat()))

print()
print("=== 2. duration longer than one step ===")
fresh(1, 16)
for dur in (0.5, 1.0, 2.0, 4.0, 8.0, 16.0):
    lib.clear()
    lib.addNote(0, 60, 100, ctypes.c_float(dur), ctypes.c_float(0.0))
    got = lib.getNoteDuration(0, 60)
    vel = lib.getNoteVelocity(0, 60)
    print("  asked %6.2f -> stored %6.2f  velocity %3d  %s"
          % (dur, got, vel, "OK" if abs(got - dur) < 0.01 else "CLAMPED/CHANGED"))

print()
print("=== 3. duration running past the pattern end (16 steps) ===")
fresh(1, 16)
for step, dur in ((14, 4.0), (15, 8.0), (15, 32.0)):
    lib.clear()
    lib.addNote(step, 60, 100, ctypes.c_float(dur), ctypes.c_float(0.0))
    print("  step %2d dur %5.1f -> stored %6.2f" % (step, dur, lib.getNoteDuration(step, 60)))

print()
print("=== 4. do two overlapping notes coexist? ===")
fresh(1, 16)
lib.clear()
lib.addNote(0, 60, 100, ctypes.c_float(8.0), ctypes.c_float(0.0))
lib.addNote(4, 63, 100, ctypes.c_float(8.0), ctypes.c_float(0.0))
print("  step0 note60 dur %.2f vel %d" % (lib.getNoteDuration(0, 60), lib.getNoteVelocity(0, 60)))
print("  step4 note63 dur %.2f vel %d" % (lib.getNoteDuration(4, 63), lib.getNoteVelocity(4, 63)))
