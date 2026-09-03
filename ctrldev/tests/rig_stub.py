"""Import the ctrldev driver without a Zynthian, so its 10,000 lines can be
tested at all.

WHY THIS EXISTS
---------------

Until 2026-09-03 the project's standing position was that the driver "cannot be
imported on WSL", and everything followed from that: the only static reach into
the largest file in the repository was twelve AST guards reading its source as
text, and every routing decision in `_midi_event` - which overlay owns a pad,
which press is swallowed, which release is thrown away - had no test of any
kind. That is where nearly every defect the owner has found at the rig lived.

The premise was false. The driver imports four names from Zynthian:

    zynlibs.zynseq.zynseq
    zyngine.ctrldev.zynthian_ctrldev_base.zynthian_ctrldev_base
    zyngine.ctrldev.techno_lib / maschine_mk2_lib      (this repo's own)
    zyngine.zynthian_signal_manager.zynsigman

Three of those are stubbed here in a few dozen lines, the other two are the real
files loaded from this directory, and the class then CONSTRUCTS against a fake
state manager. Nothing about the rig is simulated: libseq is a recorder, the
mixer is a dict, the chains are empty. That is deliberate - what these tests are
for is the part of the driver that decides what a button MEANS, which is pure
routing over its own state and needs none of it.

WHAT IT IS NOT
--------------

Not a rig, and not a substitute for one. Nothing here proves a note sounds, a
pattern is written, or an LED lights - libseq records calls and returns zeros,
so a test asserting musical output would be asserting the fake. The AST guards
stay exactly as they are: they answer questions about the source that no
instance can answer, and they have caught defects this cannot.
"""

import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

CTRLDEV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeLibseq:
    """Records what the driver asks of libzynseq and answers plausibly.

    Every getter returns a number rather than a MagicMock, because the driver
    does arithmetic and comparisons on all of them - a Mock reaches a `<` and
    raises a TypeError that reads like a driver bug.
    """

    def __init__(self):
        self.calls = []
        self.notes = {}                 # step -> [(note, velocity)]
        self.tempo = 125.0
        self.play_state = {}

    def __getattr__(self, name):
        # One recorder for the whole API surface. Anything not named below
        # answers 0, which is what an unloaded sequencer looks like.
        def call(*args):
            self.calls.append((name, args))
            return 0
        return call

    def getTempo(self):
        self.calls.append(("getTempo", ()))
        return self.tempo

    def addNote(self, step, note, velocity, duration, offset):
        self.calls.append(("addNote", (step, note, velocity, duration, offset)))
        self.notes.setdefault(step, []).append((note, velocity))
        return True

    def clear(self):
        self.calls.append(("clear", ()))
        self.notes.clear()

    def getNoteVelocity(self, step, note):
        for n, v in self.notes.get(step, []):
            if n == note:
                return v
        return 0

    def named(self, name):
        """Every call to `name`, in order."""
        return [args for called, args in self.calls if called == name]


class FakeMixer:
    def __init__(self):
        self.levels = {}
        self.mutes = {}
        self.MAX_NUM_CHANNELS = 17

    def get_level(self, chan):
        return self.levels.get(chan, 0.67)

    def set_level(self, chan, value):
        self.levels[chan] = value

    def get_mute(self, chan):
        return self.mutes.get(chan, 0)

    def set_mute(self, chan, value):
        self.mutes[chan] = value

    def enable_dpm(self, *args):
        pass

    def get_dpm(self, *args):
        return -88.0

    def get_dpm_holds(self, *args):
        return -88.0


class FakeChainManager:
    def __init__(self):
        # A LIST of sixteen lists, exactly as zynthian_chain_manager builds it
        # (chain_manager.py:118). A dict here would hide the KeyError a real
        # empty channel cannot raise.
        self.midi_chan_2_chain_ids = [list() for _ in range(16)]
        self.chains = {}

    def get_synth_processor(self, chan):
        """No engine on any channel. The driver's own answer to that is what
        several of these tests are about: an absent chain must draw a dash and
        refuse a knob, not raise."""
        return None

    def get_processors(self, *args, **kwargs):
        return []


class FakeStateManager:
    def __init__(self):
        self.zynseq = MagicMock()
        self.zynseq.libseq = FakeLibseq()
        self.zynseq.bank = 1
        self.zynmixer = FakeMixer()
        self.chain_manager = FakeChainManager()
        self.busy = set()

        # The signals the driver registers for. SS_LOAD_SNAPSHOT is read off
        # the state manager, so it has to exist.
        self.SS_LOAD_SNAPSHOT = "load_snapshot"


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _install_fake_zynthian():
    """Put the four Zynthian imports on sys.modules. Idempotent."""

    if "zyngine.ctrldev.zynthian_ctrldev_base" in sys.modules:
        return

    zynlibs = _module("zynlibs"); zynlibs.__path__ = []
    zynseq_pkg = _module("zynlibs.zynseq"); zynseq_pkg.__path__ = []
    zynseq = _module(
        "zynlibs.zynseq.zynseq",
        SEQ_STOPPED=0, SEQ_PLAYING=1, SEQ_STOPPING=2,
        SEQ_STARTING=3, SEQ_RESTARTING=4, SEQ_LOOP=5, SEQ_LOOPALL=6,
    )
    zynseq_pkg.zynseq = zynseq

    zyngine = _module("zyngine"); zyngine.__path__ = []
    ctrldev = _module("zyngine.ctrldev"); ctrldev.__path__ = []

    class ZynthianCtrldevBase:
        """What the installed base class provides that the driver uses.

        Only three things: the state manager, the chain manager off it, and the
        device index. Everything else in the real base class is about binding
        to a MIDI port, which is the half these tests deliberately do not have.
        """

        dev_ids = []

        def __init__(self, state_manager, idev_in, idev_out=None):
            self.state_manager = state_manager
            self.chain_manager = state_manager.chain_manager
            self.idev = idev_in
            self.idev_out = idev_out

        def init(self):
            pass

        def end(self):
            pass

    _module("zyngine.ctrldev.zynthian_ctrldev_base",
            zynthian_ctrldev_base=ZynthianCtrldevBase)

    signals = MagicMock()
    signals.S_STEPSEQ = "stepseq"
    signals.S_STATE_MAN = "state_man"
    _module("zyngine.zynthian_signal_manager", zynsigman=signals)

    # The repo's own two libraries, loaded from source under the names the
    # driver imports them by.
    for name, filename in (("zyngine.ctrldev.techno_lib", "techno_lib.py"),
                           ("zyngine.ctrldev.maschine_mk2_lib",
                            "maschine_mk2_lib.py")):
        spec = importlib.util.spec_from_file_location(
            name, os.path.join(CTRLDEV, filename))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)


def load_driver():
    """The driver module, imported once."""

    _install_fake_zynthian()
    if "maschine_driver_under_test" in sys.modules:
        return sys.modules["maschine_driver_under_test"]
    spec = importlib.util.spec_from_file_location(
        "maschine_driver_under_test",
        os.path.join(CTRLDEV, "zynthian_ctrldev_maschine_mk2.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["maschine_driver_under_test"] = module
    spec.loader.exec_module(module)
    return module


def make_driver():
    """A constructed driver, with nothing running.

    `init()` is NOT called: it starts two threads and registers signal
    handlers, and every test here is about a single event reaching a single
    handler. The OSC socket is replaced by a recorder, so nothing leaves the
    process.
    """

    driver_module = load_driver()
    state_manager = FakeStateManager()
    driver = driver_module.zynthian_ctrldev_maschine_mk2(state_manager, 0)
    driver.osc = MagicMock()
    driver.bankpin.pin(state_manager.zynseq.bank)
    return driver


def cc_for(action, driver_module):
    """The CC number bound to a stateful action, read out of the table.

    Never a literal in a test: the CC map is measured hardware fact and it has
    moved, so a test carrying its own copy of a number is a test that will one
    day disagree with the instrument and be believed.
    """

    tlib = driver_module.tlib
    for cc, name in tlib.BUTTONS_STATEFUL.items():
        if name == action:
            return cc
    for cc, name in tlib.BUTTONS_PRESS.items():
        if name == action:
            return cc
    raise AssertionError(f"nothing is bound to {action!r}")
