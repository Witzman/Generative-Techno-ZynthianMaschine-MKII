#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Controller driver for Maschine MK2 via the MaschineMK2_linux daemon.
#
# 8 groups x 16 steps euclidean drum sequencer. All sequencing lives in
# zynseq, so patterns persist in snapshots and the touchscreen pattern
# editor mirrors them.
#
# MIDI in (ch 1, from the daemon):
#   Pads      NoteOn, note = group note base + pad index. Velocity becomes the
#             step's velocity, so a hard tap is an accent
#   Group A-H CC 80-87 (select; ERASE held = silence that channel)
#   Encoders  CC 16-23. What they mean depends on the mode, the page within
#             that mode and the channel type - the one table is
#             techno_lib.PAGE_RINGS, and a page's SHAPE decides whether a
#             column is a parameter of the selected channel, one parameter
#             across all eight channels, or a global
#   Modes     CONTROL 11, STEP 32, ALL 38, MIXER (VOLUME) 51, FILTER (AUTO) 37 -
#             latched and mutually exclusive
#   DL / DR   CC 5/6 - page back / forward within the current mode's ring
#   ML / MR   CC 13/14 - previous / next sound: a sample within the kit on a
#             drum, an engine preset on a voice
#   F1-F8     CC 39-46 (mute, or solo while SOLO is held or latched)
#   Solo 31 - Duplicate 29 - Play 1 - Erase 2 (hold only) - Restart 7
#
# Reserved and deliberately unused: CC 47/48 (TL/TR - the daemon swallows the
# transport pair for its own indicators) and CC 49/50 (SHIFT and SWING, which
# the pass-two daemon patch emits but nothing binds yet).
#
# LED out: OSC to the daemon on 127.0.0.1:42434 (main.rs:609-665)
#
# REQUIRES "external_pad_leds": true in the daemon's maschine.json. Without
# it the daemon paints pads itself - bright on press, PAD_RELEASED_BRIGHTNESS
# in its single global colour on release - so the first touch wipes this
# driver's per-group colours and the pad shows the daemon's red at ~1/255
# forever after. Nothing here can win that race; the daemon has to stand down.
#
# Transport: Play (CC 1) starts or stops all 8 sequences together by setting
# their zynseq play state directly. The CUIA TOGGLE_PLAY is NOT usable here -
# it resolves to cuia_toggle_audio_play(), which either toggles the audio file
# player or, when the pattern editor happens to be on screen, toggles that one
# pattern. Hardware test confirmed it started group A alone. setPlayState()
# also starts JACK transport for the first sequence to run (zynseq.cpp:2126),
# so no separate transport call is needed. Restart (CC 7) jumps every group's
# pattern back to step 0 without stopping. A white playhead overlays the
# selected group's pads while it plays.

import logging
import socket
import time
from collections import deque
from threading import Event, RLock, Thread

from zynlibs.zynseq import zynseq as zynseq_lib
from zyngine.ctrldev.zynthian_ctrldev_base import zynthian_ctrldev_base
from zyngine.ctrldev.maschine_mk2_lib import maschine_mk2_lib as lib
from zyngine.ctrldev.techno_lib import techno_lib as tlib
from zyngine.zynthian_signal_manager import zynsigman

OSC_ADDR = ("127.0.0.1", 42434)

GROUP_CC_FIRST = 80                 # Group A..H = CC 80..87
GROUP_NOTE_BASE = (24, 36, 48, 60, 72, 84, 96, 108)

# The daemon maps physical pads to note offsets with this table, indexed by
# physical pad (0 = bottom-left). Decoding a NoteOn to a step number
# (step = note - GROUP_NOTE_BASE[group]) yields step 0 at the TOP-LEFT pad.
# Lighting a step's LED must therefore go through the same table to find
# which physical pad displays it - PAD_OFFSETS[step] is the pad index, not
# the step index. The table is its own inverse (verified on the wire:
# bottom-left pad / note base 48 -> note 60, i.e. offset 12; top-right ->
# note 51, i.e. offset 3), so the same table converts both directions.
PAD_OFFSETS = [12, 13, 14, 15, 8, 9, 10, 11, 4, 5, 6, 7, 0, 1, 2, 3]

# Prepared snapshot's group -> drum note mapping (A..H), used only when a
# group's pattern is empty and nothing can be discovered from it.
FALLBACK_NOTES = (36, 38, 39, 42, 46, 45, 47, 51)

# Per-group pad colour (A..H), user-specified palette.
# Channel identity colours come from the channel table, so drums stay warm and
# voices cool: the seam between the two halves is visible on the panel without
# reading anything. Pads inherit the same colour as their group button.
GROUP_COLORS = tuple(ch[3] for ch in tlib.CHANNELS)

# The daemon's set_rgb_light halves whatever brightness we pass
# (src/devices/mk2/mikro.rs:455-461) before writing the LED report, so a
# literal 1.0 only reaches half intensity - that is why active steps showed
# up dark instead of full colour. Passing 2.0 here nets 2.0 * 0.5 = 1.0,
# i.e. the full 255 per channel; every other pad brightness below is scaled
# by the same factor so their relative levels stay correct. Do not "fix"
# this in the daemon - it is deliberately compensated for from here.
PAD_BRIGHTNESS_SCALE = 2.0
BRIGHT_STEP_ON = 1.0 * PAD_BRIGHTNESS_SCALE      # active step, full colour
BRIGHT_STEP_OFF = 0.05 * PAD_BRIGHTNESS_SCALE    # empty step, dim
BRIGHT_PLAYHEAD = 1.0 * PAD_BRIGHTNESS_SCALE     # white playhead sweep, full

COLOR_PLAYHEAD = 0xFFFFFF
# Amber marks a step a human played in. The daemon uses it for its own
# selected step; this driver used it nowhere.
COLOR_PLAYER = 0xFF8800

# Group buttons carry their group's own colour, so the button matches the
# pads it selects. They are full RGB - three contiguous bytes each in report
# 0x81, mapped on the hardware 2026-08-07 - and the daemon writes the triplet
# without set_rgb_light's halving, so these levels mean what they say.
#
# The earlier "byte 128 looks the same as byte 255" reading was measuring a
# single colour channel, not brightness, which is why a lit channel saturates
# visually well before full.
#
# Group button BRIGHTNESS shows that group's volume, so the eight buttons read
# as a mix level meter. The colour already says which group a button is, and
# the pads say which one is selected, so brightness was free to carry
# something. The floor keeps a silent group faintly visible instead of making
# it look absent.
BRIGHT_GROUP_MIN = 0.10
BRIGHT_GROUP_MAX = 1.0
BRIGHT_GROUP_NO_CHAIN = 0.25       # group has no chain to read a volume from

# Play button: lit while any group is running, dark when everything is
# stopped. Same single-byte LED path as the group buttons.
COLOR_PLAY = 0xFFFFFF
BRIGHT_PLAY_ON = 1.0
BRIGHT_PLAY_OFF = 0.0

CC_PLAY = 1
HOLD_MS = 250            # law L1: tap latches, hold is momentary
CC_ERASE = 2      # hold only: a bare press does nothing (law L3)
CC_RESTART = 7
# MEASURED at gate G5, 2026-08-12, with aseqdump: both edges, and free -
# GROUP_CC_FIRST is 80, so it does not collide with the group buttons.
CC_REC = 3
# SHIFT has emitted since SP1's daemon patch with no consumer; GRID was
# measured at gate G4 and left unbound. SP4 is the first user of both.
CC_SHIFT = 49
CC_GRID = 4

# Euclid encoders. The daemon reports a position, not a movement, so the
# driver reads the difference between successive values - see _enc_steps. A
# position cannot serve eight groups: mapping it straight onto a parameter
# tied all of them to one knob position, so selecting a different group and
# turning made its value jump to the previous group's.

# All eight encoders in daemon index order, and where their reported position
# is parked when it drifts too near the daemon's 0-127 clamp. Without this a
# knob runs out of travel and its parameter refuses to move any further.
ENCODER_CCS = tuple(range(16, 24))
ENC_CENTRE = 64
ENC_RECENTRE_MARGIN = 24

# Division and length have very few settings, so spreading them over the
# whole sweep the way the absolute mapping did cost 26 and 32 units of
# movement per step - four times what hits costs, which read as sticky. They
# take the same movement per step as hits at a full 16-step pattern instead,
# so every pattern encoder feels the same in the hand.
ENC_UNITS_DISCRETE = 8

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

# The owner's button names, and the CCs are MEASURED - gate G4, 2026-08-11,
# one press per button captured off the ALSA port with aseqdump. Every earlier
# number in this project was read out of the daemon's source and two of them
# were wrong, in a way no amount of source-reading could catch: the daemon's
# step_* and page_* tokens are attached to the opposite physical buttons from
# what their names suggest.
#   DL / DR - arrows beside the display. **CC 47 / 48**, not 5/6. They page
#             through the current mode's ring.
#   ML / MR - master section, beside the big encoder. CC 13/14, as assumed.
#             They carry sound stepping, which used to live on DL/DR.
#   TL / TR - transport ◀STEP / STEP▶. **CC 5 / 6, and fully emitted.** The
#             claim that the daemon swallowed this pair was false; it was
#             derived from the mixed-up naming above. Free surface, unbound.
CC_DL = 47
CC_DR = 48
CC_ML = 13
CC_MR = 14
CC_TL = 5                # unbound, free
CC_TR = 6                # unbound, free

# Mode buttons, all measured at G4 alongside the arrows. Unlike the arrows,
# every one of these matched what the daemon's source said.
CC_SOLO = 31             # measured
CC_DUPLICATE = 29        # measured
CC_MODE_CONTROL = 11
CC_MODE_STEP = 32
CC_MODE_ALL = 38
CC_MODE_MIXER = 51       # VOLUME - the pass-two daemon patch, measured live
CC_MODE_FILTER = 37      # AUTO
# Measured at G4 and not bound to anything yet - recorded so the next feature
# does not have to re-run the audit:
#   GRID 4 · SCENE 25 · PATTERN 26 · PAD MODE 27 · NAVIGATE 34 · MUTE 33
#   big encoder: turn CC 15 (8 units per detent, wraps 120 -> 0), press CC 12
# There is no VIEW button on the MK2 panel. The daemon defines a "view" token,
# but the 8-button block is scene, pattern, pad mode, navigate, duplicate,
# select, solo, mute - confirmed against the hardware by the owner.
MODE_BUTTONS = {
    CC_MODE_CONTROL: "CONTROL",
    CC_MODE_STEP: "STEP",
    CC_MODE_ALL: "ALL",
    CC_MODE_MIXER: "MIXER",
    CC_MODE_FILTER: "FILTER",
}
MODE_LED_NAMES = {"CONTROL": "control", "STEP": "step", "ALL": "all",
                  "MIXER": "volume", "FILTER": "auto"}
COLOR_PAGE = 0xFFFFFF
BRIGHT_PAGE_ON = 1.0
BRIGHT_PAGE_OFF = 0.0
BAR_KINDS = {"uni": "u", "bi": "b", "seg": "s", None: ""}

# Used only when a group has no kit notes at all (e.g. no SFZ kit loaded
# yet, or the kit file failed to parse).
FALLBACK_KEYMAP_NOTES = range(35, 82)      # GM percussion range

# The SFZ drum machines. The bank name is the directory under System SFZ as
# Zynthian lists it, and the kits are that bank's presets.
KIT_BANK = "Drum Machines"
# How long after the last encoder movement a kit is actually loaded. Sweeping
# the list then costs one load instead of one per step.
KIT_LOAD_DELAY_S = 0.15
PRESET_LOAD_DELAY_S = 0.20   # a voice preset load is slower than a kit's
KIT_RETRY_S = 2.0            # floor between kit-list retries on a bare chain

# Pattern length is per group, which is what makes polyrhythm possible: each
# zynseq Sequence keeps its own length and wraps on it (sequence.cpp:149,
# "case LOOP: m_nPosition = 0"), and setBeatsInPattern() calls
# updateAllSequenceLengths(). 12 steps against 16 is 3:4.
#
# Length is quantised to whole BEATS, not steps - Pattern::getSteps() is
# beats * stepsPerBeat and getLength() is beats * PPQN, so beats is the only
# length knob there is. At a 1/16 grid that means 4, 8, 12 or 16 steps; a
# 7-step pattern of sixteenths cannot be expressed. Reading the length off
# the pads is the intended feedback - steps past the end are unlit.
MIN_BEATS = 1
PADS = 16              # a pattern longer than the pad grid is not displayable

# What each encoder does now depends on the mode, the page and the channel
# type - see techno_lib.PAGE_RINGS. LEVEL drives the group's MIXER STRIP
# rather than an engine
# controller, because LinuxSampler publishes no controllers at all.
#
# Do not retry filter/resonance on the drum channels: in the SoundFont spec
# CC 74/71 are unipolar modulators that only ADD to initialFilterFc, and the
# kits ship with the filter wide open at 13500 cents, so there is no headroom
# to act in and no way to subtract. Those columns are greyed for that reason.

CC_F1 = 39             # F1..F8 = CC 39..46, one mute per group
F_BUTTON_NAMES = ("f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8")

PREVIEW_VELOCITY = 100
PREVIEW_MS = 200       # playNote spawns its own note-off after this

DEFAULT_DIV = 1        # index into lib.DIVISIONS: 1/16, 16 steps

# Division was pulled off the encoders once, on the theory that taking a
# pattern to 12 steps (1/16T) destabilised zynseq: the playhead dwelled and
# skipped. That diagnosis was wrong - the same dwell-and-skip then showed up
# on straight 1/16, and the real cause was sampling the playhead off the 5 Hz
# SS_SEQ_PROGRESS signal (see PLAYHEAD_POLL_S). With the 30 Hz poll in place
# the reason no longer holds, so division is back on encoder 3.
#
# Still unresolved from that session, and not explained by the aliasing: the
# touchscreen pattern editor flickered through note rows while the division
# changed. Watch for it - it is a display concern, not a timing one.
#
# Endless encoders cannot show which of five divisions is selected. That
# remains a real usability gap until the MK2 display is usable.

# The playhead cannot be driven by SS_SEQ_PROGRESS. That signal comes from
# zynseq.update_state(), which runs in the state manager's slow_thread_task
# on a 0.2s sleep - 5 Hz. A 16-step 1/16 pattern at 120 BPM advances 8
# steps/s, so the LED sampling aliased against the step rate: pads were
# skipped in no discernible pattern, and it got worse as tempo rose. The
# touchscreen editor stays smooth because it polls on the GUI refresh loop.
# This thread polls fast enough to catch every step instead.
PLAYHEAD_POLL_S = 0.033        # ~30 Hz, 4x oversampled at 120 BPM

# The same thread re-reads the group volumes every Nth tick, because nothing
# signals a zctrl change: zynthian_controller emits no zynsigman signal, so a
# volume moved on the touchscreen is invisible until something asks. Only the
# led_cache diff reaches the wire, so a quiet poll costs nothing.
VOLUME_POLL_TICKS = 6          # every ~200ms

# Set by the daemon's alias helper: uid "virtual:maschine.rs/Maschine MK2 Pads",
# and Zynthian's device id is everything after the first '/'.
DEV_ID = "Maschine MK2 Pads"


class zynthian_ctrldev_maschine_mk2(zynthian_ctrldev_base):

    dev_ids = [DEV_ID]
    driver_name = "Maschine MK2 Drum Rig"
    driver_description = "8 groups x 16 steps euclidean drum sequencer on zynseq"
    unroute_from_chains = True      # pads must not reach chains directly

    def __init__(self, state_manager, idev_in, idev_out=None):
        super().__init__(state_manager, idev_in, idev_out)
        # The installed base class sets self.zynseq only in its zynpad
        # subclass, so this driver wires it up itself.
        self.zynseq = state_manager.zynseq
        self.libseq = self.zynseq.libseq
        self.group = 0                       # selected group, 0 = A
        self.note_cache = [None] * 8         # per-group drum note, discovered lazily
        self.hits = [0] * 8                  # euclid hit count per group
        self.div = [DEFAULT_DIV] * 8         # index into lib.DIVISIONS
        self.rot = [0] * 8                   # euclid rotation per group
        self.beats = [lib.DIVISIONS[DEFAULT_DIV][2]] * 8   # pattern length
        self.keymap_cache = [None] * 8       # per-group [(note, name)], lazy
        self.kit_index = [0] * 8             # which kit each group uses
        self.kit_cache = {}                  # sfz path -> [(note, name)]
        self.kits = None                     # [(display name, sfz path)], lazy
        self.kit_pending = None              # (group, index, due) waiting to load,
                                              # due = time.monotonic() deadline; a
                                              # single attribute so _nudge_kit's
                                              # writer and _commit_kit's reader on
                                              # the other thread can never see it
                                              # half-written
        # Last reason _kit_list() had nothing to offer, or None. _kit_list()
        # is now retried on every call while a chain has no kits, which is
        # every screen render (~5 Hz); without this it would log at that
        # rate instead of once per distinct condition.
        self._kit_warned = None
        # Groups already warned about an empty keymap (see _cycle_sample), so
        # a stuck encoder doesn't log on every detent.
        self._empty_keymap_warned = set()
        # Clocks per step, cached per group by _render_pads. The playhead
        # poll must not call selectPattern(): that writes zynseq's single
        # global pattern selection, and doing it 30 times a second from this
        # thread would fight the pattern editor screen for it.
        self.cps = [0] * 8
        self.step_on = [False] * 16          # selected group's steps, for repaint
        self.head_shown = None               # step the white pad is currently on
        self.leds = lib.led_cache()
        # Per encoder: the last position the daemon reported, and movement
        # not yet worth a whole parameter step. See _enc_steps.
        self.enc_last = {}
        self.enc_carry = {}
        self.osc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.stopping = Event()
        self.playhead_thread = None
        # libzynseq is not thread-safe and this driver touches it from three
        # threads: the MIDI handler, the zynsigman queued signal handler and
        # the playhead poll. Zynthian's UI died with SIGSEGV (exit 139) inside
        # zynthian_main.py about 95s into a jam before this lock existed -
        # getPlayPosition() dereferences whatever getSequence() returns, with
        # no guard against the sequence manager being mutated underneath it by
        # clear() / addNote() / setStepsPerBeat() on another thread. Every
        # entry point that reaches libseq takes this lock.
        self.lock = RLock()

        # --- techno machine state -------------------------------------
        # One state dict and one apply() path. Every write - encoder,
        # snapshot restore, Duplicate, and later Lock recall and morph - goes
        # through apply(), so pass two's Lock snapshots are a copy of this
        # dict and a morph is a lerp over it. Writing zynseq and zctrls
        # directly from the encoder handlers is what would turn that feature
        # into a driver rewrite.
        #
        # hits / rotate / div / length deliberately do NOT live here: they
        # already live in self.hits, self.rot, self.div and self.beats, and
        # two copies of one value diverge. param_get() and apply() read and
        # write those arrays, so the dict stays the only home for everything
        # else and there is still exactly one home per parameter.
        self.mode = "CONTROL"
        # One page index per ring, so selecting a drum and coming back to a
        # voice returns to the page you left rather than to whatever the drum's
        # shorter ring could hold.
        self.page_idx = {}
        # Generated rings, keyed (mode, kind, channel). Built once and held:
        # _ring() runs on the MIDI thread, where reaching an engine load would
        # freeze the instrument - midi_event holds self.lock for the whole
        # event and a load blocks on a socket for seconds.
        self.gen_cache = {}
        self.globals = dict(root=9, scale=0, bpm=132, master=80,
                            revsize=25, revtype=3, dlytime=1, dlyfbk=35,
                            pending=set())
        self.state = {}
        for idx, ch in enumerate(tlib.CHANNELS):
            # One tested builder, shared with SP4's first switch to the other
            # kind, so a freshly built set can never be half a set.
            self.state[idx] = tlib.default_channel_state(ch[2])
        # Two named groups, even though nothing in the prototype uses the
        # distinction: scoped Lock layers in pass three are impossible later
        # without re-tagging every field.
        self.GENERATOR_PARAMS = {"hits", "rotate", "div", "length", "chance",
                                 "velo", "swing", "random", "gate", "octave",
                                 "range", "register", "density"}
        self.MIX_PARAMS = {"level", "reverb", "delay"}
        # Built now, while the Turing mutation is the only writer, so a morph
        # can take it later. Two writers to one pattern is the SIGSEGV by a
        # different door.
        self.writer_token = {i: None for i in range(len(tlib.CHANNELS))}
        # Pads currently held down: pad -> (note, midi_chan, channel,
        # start_clock, velocity). A held note that never gets its note-off is
        # the worst failure this instrument can produce, so every path that
        # changes what the pads mean goes through _release_all().
        self.held = {}
        self.rec_down = False
        # Who writes a channel's pattern: "gen" or "player". NOT writer_token -
        # that is the short-lived mutex between threads and clears itself after
        # every write, so it cannot carry an ownership that survives a snapshot.
        self.owner = {i: "gen" for i in range(len(tlib.CHANNELS))}
        # Which kind a channel behaves as, when the player has said so.
        # None means "ask the chain" - never a stored copy of it.
        self.kind_override = {i: None for i in range(len(tlib.CHANNELS))}
        self.shift_down = False
        # The sleeping state set per channel and kind: channel -> kind -> dict,
        # plus "<kind>:hits" and "<kind>:rot" from the legacy arrays. Pure
        # driver state - nothing in zynseq mirrors it, so there is nothing to
        # read back and nothing that can drift behind us.
        self.stash = {i: {} for i in range(len(tlib.CHANNELS))}
        # step -> (note, velocity, duration) for player-owned channels. A
        # cache, never the truth: rebuilt from the pattern, never assumed.
        self.notes = {i: {} for i in range(len(tlib.CHANNELS))}
        # Channels whose note map needs rebuilding. Drained by the poll
        # thread: the scan takes the lock and must never run on the MIDI
        # thread, for the same reason _commit_kit and _commit_preset do not.
        self._rebuild_due = set()
        self._last_delay_ms = None
        # last raw play position per voice, for wrap detection
        self._voice_pos = {}
        # (channel, index, due) waiting to load - one attribute, so the
        # encoder's writer and the poll thread's reader can never see it
        # half-written
        self.preset_pending = None
        self.preset_cache = {}
        self._kit_retry_at = 0.0
        # voices that still owe a rewrite for a key change
        self._key_dirty = set()
        # Law L1 bookkeeping: when each held button went down, and whether it
        # changed anything, so the release knows what to undo.
        self.erase_down = False
        self.solo_down = False
        self.solo_mode = False           # latched: the F row means solo
        self._down_at = {}

    # --- plumbing ------------------------------------------------------

    def _send_osc(self, packet):
        try:
            self.osc.sendto(packet, OSC_ADDR)
        except OSError as e:
            logging.error(f"Maschine OSC send failed: {e}")

    def _seq_addr(self, group):
        """Sequence address for a group, as the installed libzynseq expects:
        (bank, sequence, track). Every zynseq call routes through here."""

        return (self.zynseq.bank, group, 0)

    def _pattern_of(self, group):
        """Pattern id backing a group, read from zynseq (not cached).
        Installed signature: getPattern(bank, sequence, track, position)"""

        return self.libseq.getPattern(self.zynseq.bank, group, 0, 0)

    def _select_pattern(self, group):
        """Select a group's pattern and return its id. The installed API is
        selection-based - getSteps(), setStepsPerBeat(), setBeatsInPattern()
        and clear() all act on the selected pattern and take no pattern
        argument, so every read or write is preceded by this call."""

        pattern = self._pattern_of(group)
        self.libseq.selectPattern(pattern)
        return pattern

    # --- techno machine: one state dict, one apply path -----------------

    # Parameters that live in the legacy per-group arrays rather than in
    # self.state, mapped to the attribute holding them.
    _LEGACY = {"hits": "hits", "rotate": "rot", "div": "div", "length": "beats"}

    def _legacy_attr(self, channel, param):
        """The per-group array holding a parameter, or None when the state
        dict owns it. LENGTH is the one word with two meanings: pattern beats
        on a drum, shift-register bits on a voice."""

        if param == "length" and self.channel_kind(channel) == "voice":
            return None
        return self._LEGACY.get(param)

    def param_get(self, channel, param):
        """Read a parameter wherever it actually lives."""

        attr = self._legacy_attr(channel, param)
        if attr is not None:
            value = getattr(self, attr)[channel]
            # LENGTH is beats in zynseq and steps on the surface:
            # DIVISIONS entries are (label, steps_per_beat, beats).
            if param == "length":
                return value * lib.DIVISIONS[self.div[channel]][1]
            return value
        return self.state[channel].get(param)

    def state_view(self, channel):
        """The state techno_lib.columns() reads: the dict, the four parameters
        that live in the legacy arrays, and the values owned by the mixer and
        the chain. Read-only - nothing may write through this."""

        view = dict(self.state[channel])
        for param in self._LEGACY:
            if self._legacy_attr(channel, param) is not None:
                view[param] = self.param_get(channel, param)

        chan = self._mixer_chan(channel)
        if chan is not None:
            view["level"] = int(round(self.state_manager.zynmixer.get_level(chan) * 100))

        if self.channel_kind(channel) == "drum":
            kits = self._kit_list()
            pending = self.kit_pending
            shown = pending[1] if pending and pending[0] == channel \
                else self._current_kit_index(channel, kits)
            name = kits[shown][0] if 0 <= shown < len(kits) else ""
            view["kit"] = lib.kit_short_name(name) or "----"
            view["sample"] = (self._sample_name(channel) or "----")[:4]
        else:
            view["preset"] = (self._preset_name(channel) or "----")[:4]
        # SP4: a channel can behave as a voice while its chain runs a sampler.
        # VOICE_SYMBOLS is keyed by engine code and has no LinuxSampler entry,
        # so _set_voice_ctrl already bails out - the columns must say so.
        view["has_synth_ctrl"] = bool(
            tlib.VOICE_SYMBOLS.get(tlib.CHANNELS[channel][4]))
        return view

    def globals_view(self):
        """The ALL page's state, with tempo and master read from the objects
        that own them rather than from the driver's copy - a displayed value
        that disagrees with the mixer is worse than no value."""

        view = dict(self.globals)
        view["bpm"] = int(round(self.libseq.getTempo()))
        mixer = self.state_manager.zynmixer
        main = getattr(mixer, "MAX_NUM_CHANNELS", 17) - 1
        try:
            view["master"] = int(round(mixer.get_level(main) * 100))
        except Exception:
            pass
        return view

    def _preset_name(self, channel):
        """The voice chain's current preset, for the CONTROL page's first
        column. Returns None when the chain has no synth processor."""

        chain_ids = self.chain_manager.midi_chan_2_chain_ids[tlib.CHANNELS[channel][5]]
        if not chain_ids:
            return None
        chain = self.chain_manager.chains.get(chain_ids[0])
        if chain is None:
            return None
        for proc in chain.get_processors():
            info = getattr(proc, "preset_info", None)
            if info:
                return str(info[2])
        return None

    def apply(self, channel, param, value):
        """The single write path.

        Everything that changes a channel comes through here so that the
        screen model, the LED cache and the engine can never disagree, and so
        that Lock snapshots stay a copy of one dict rather than a scrape of
        four subsystems."""

        if self.param_get(channel, param) == value:
            return

        attr = self._legacy_attr(channel, param)
        if attr is not None:
            getattr(self, attr)[channel] = value
        else:
            self.state[channel][param] = value

        if param in self.MIX_PARAMS:
            self._apply_mix(channel, param, value)
        elif param in self.GENERATOR_PARAMS:
            self._apply_generator(channel, param, value)
        elif param in self.VOICE_CTRL_COLUMNS:
            self._set_voice_ctrl(channel, self.VOICE_CTRL_COLUMNS[param], value)

    def _apply_mix(self, channel, param, value):
        if param == "level":
            chan = self._mixer_chan(channel)
            if chan is not None:
                self.state_manager.zynmixer.set_level(chan, value / 100.0)
        else:
            self._set_wet(channel, param, value)

    # --- the ALL page: globals ------------------------------------------

    GLOBAL_RANGES = {
        "root": (0, 11, ENC_UNITS_DISCRETE),
        "scale": (0, len(tlib.SCALES) - 1, ENC_UNITS_DISCRETE),
        "bpm": (60, 200, None),
        "master": (0, 100, None),
        "revsize": (0, 100, None),
        "revtype": (0, 42, ENC_UNITS_DISCRETE),
        "dlytime": (0, len(tlib.DELAY_DIVISIONS) - 1, ENC_UNITS_DISCRETE),
        "dlyfbk": (0, 100, None),
    }

    def apply_global(self, param, value):
        """The globals' write path. Same rule as apply(): one place, so the
        screens, the LEDs and the engines cannot disagree."""

        if self.globals.get(param) == value:
            return
        self.globals[param] = value

        if param in ("root", "scale"):
            # Structure, so it lands on the bar (law L2). Every voice picks it
            # up at its own next wrap; until then the value shows in brackets.
            #
            # The pending marker is cleared by the LAST voice to take it, not
            # on the next poll: clearing it eagerly meant a key change only
            # ever landed if a wrap happened to fall inside the same 33 ms
            # tick, which is why it appeared to work exactly once.
            self.globals["pending"].add(param)
            self._key_dirty = {i for i, ch in enumerate(tlib.CHANNELS)
                               if self.channel_kind(i) == "voice"}
        elif param == "bpm":
            with self.lock:
                self.libseq.setTempo(float(value))
        elif param == "master":
            mixer = self.state_manager.zynmixer
            main = getattr(mixer, "MAX_NUM_CHANNELS", 17) - 1
            mixer.set_level(main, value / 100.0)
        elif param in ("revsize", "revtype"):
            self._set_ganged("reverb", param.upper(), value)
        elif param == "dlyfbk":
            self._set_ganged("delay", "DLYFBK", value)
        elif param == "dlytime":
            self._push_delay_time(force=True)

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
        span = zctrl.value_max - zctrl.value_min
        if span <= 0:
            return
        if tlib.port_is_discrete(zctrl.value_min, zctrl.value_max,
                              getattr(zctrl, "is_integer", True)):
            # A toggle or a handful of positions: one percent of it rounds to
            # nothing and _set_value() truncates integer controls, so drive it
            # in whole units instead. Measured dead on TAP Reverberator.
            delta = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if delta == 0:
                return
            target = tlib.step_port_value(zctrl.value, zctrl.value_min,
                                          zctrl.value_max, delta)
        else:
            # Whole percent with the remainder carried, for the same reason.
            delta = self._enc_steps(cc_num, cc_val, 101)
            if delta == 0:
                return
            percent = (zctrl.value - zctrl.value_min) / span * 100.0
            percent = min(100.0, max(0.0, percent + delta))
            target = zctrl.value_min + span * (percent / 100.0)
        zctrl.set_value(target, True)
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
        span = zctrl.value_max - zctrl.value_min
        if span <= 0:
            return
        if tlib.port_is_discrete(zctrl.value_min, zctrl.value_max,
                              getattr(zctrl, "is_integer", True)):
            # The whole REV page is toggles - combs_en, allps_en, bandpass,
            # stereo_E - and every one of them was dead until this branch.
            delta = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if delta == 0:
                return
            target = tlib.step_port_value(zctrl.value, zctrl.value_min,
                                          zctrl.value_max, delta)
        else:
            delta = self._enc_steps(cc_num, cc_val, 101)
            if delta == 0:
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

    def _set_ganged(self, which, role, value):
        """One knob, eight instances. Identical character in eight boxes is
        most of the way to a coherent space, and per-channel divergence is a
        later opt-in that nothing here forecloses."""

        table = tlib.FX_REVERB if which == "reverb" else tlib.FX_DELAY
        symbol, lo, hi = table[role]
        if role == "REVTYPE":
            # A reverb type is an index into the plugin's 43 rooms, not a
            # percentage - scaling it would silently pick the wrong room.
            target = max(lo, min(hi, float(value)))
        else:
            target = lo + (hi - lo) * (value / 100.0)
        for channel in range(len(tlib.CHANNELS)):
            proc = self.fx_handle(channel, which)
            if proc is None:
                continue
            zctrl = proc.controllers_dict.get(symbol)
            if zctrl is not None:
                zctrl.set_value(target, True)

    def _push_delay_time(self, force=False):
        """The delay takes milliseconds, so the musical division is resolved
        against the live tempo. Recomputed on the render tick and pushed only
        when it actually moved - never per encoder event, and never per
        callback."""

        with self.lock:
            bpm = self.libseq.getTempo()
        ms = tlib.delay_ms(bpm, self.globals["dlytime"])
        if not force and self._last_delay_ms is not None and \
                abs(ms - self._last_delay_ms) < 0.5:
            return
        self._last_delay_ms = ms
        symbol = tlib.FX_DELAY["DLYTIME"][0]
        for channel in range(len(tlib.CHANNELS)):
            proc = self.fx_handle(channel, "delay")
            if proc is None:
                continue
            for sym in (symbol, "rhaasdelay"):
                zctrl = proc.controllers_dict.get(sym)
                if zctrl is not None:
                    zctrl.set_value(ms, True)

    # --- the Turing voices ---------------------------------------------

    def _write_voice_pattern(self, channel):
        """Write the current register into the channel's pattern. Mutates
        nothing - Duplicate needs to write without advancing.

        Lock discipline: one acquisition for the whole burst, selectPattern
        exactly once inside it, and the note loop never touches anything else.
        libzynseq is not thread-safe and this runs on the poll thread."""

        st = self.state[channel]
        # Claim the pattern under the lock. Checking the token and then setting
        # it as two separate steps leaves a window where two threads both see
        # it free - set_state() runs on the manager's thread while the poll
        # thread is mutating, so the window is real, and two writers to one
        # pattern is the SIGSEGV this driver already survived once.
        with self.lock:
            if self.owner[channel] == "player":
                # The take stays. The token cannot express this: it is the
                # mutex between threads and clears itself after every write,
                # so it cannot carry an ownership that survives a snapshot.
                return
            if self.writer_token[channel] not in (None, "turing"):
                return                    # someone else owns this pattern
            self.writer_token[channel] = "turing"
        try:
            steps = lib.step_count(self.div[channel])
            notes = self._voice_notes(channel, steps)
            # Which steps sound. A masked step skips addNote entirely, so the
            # write burst - the largest risk in this design - gets smaller at
            # every density below 100, never larger.
            mask = tlib.gate_mask(st["register"], st["length"], steps,
                                  st.get("density", 100) / 100.0)
            velocity = max(1, min(127, int(st["velo"])))
            played = []
            with self.lock:
                self._select_pattern(channel)
                self._force_loop_mode(channel)
                self.libseq.setStepsPerBeat(lib.DIVISIONS[self.div[channel]][1])
                self.libseq.setBeatsInPattern(lib.DIVISIONS[self.div[channel]][2])
                self.libseq.clear()
                for step, note in enumerate(notes):
                    if not mask[step]:
                        continue
                    # Per step, not once per pattern: a long gate near the end
                    # of the pattern is clamped so the note cannot outlive it.
                    duration = tlib.note_duration(st["gate"], step, steps)
                    self.libseq.addNote(step, note, velocity, duration, 0.0)
                    played.append(note)
                self.libseq.updateSequenceInfo()
            # The range must come from what was written, not from the line:
            # reporting pitches that were masked out would make this log lie.
            note_range = (min(played), max(played)) if played else None
            logging.debug(f"Maschine voice {channel}: {len(played)}/{steps} notes, "
                          f"register {st['register']:0{st['length']}b}, range {note_range}")
        finally:
            self.writer_token[channel] = None

    def _rewrite_voice(self, channel):
        """Called at a playhead wrap.

        RANDOM at 0 skips the rewrite entirely, which is precisely why the
        line being heard is the line kept, bit for bit, for as long as the
        knob stays down. Law L6 is not an approximation here - nothing
        rewrites the pattern, so nothing can change it."""

        st = self.state[channel]
        if st["random"] <= 0:
            return
        tlib.ring_push(st["ring"], st["register"])
        st["register"] = tlib.mutate(st["register"], st["length"],
                                     st["random"] / 100.0)
        self._write_voice_pattern(channel)

    def _duplicate(self):
        """Give the last line back. Restores the previous register, forces
        RANDOM to 0 so the restored line is held, and rewrites now. Walks back
        up to four registers - roughly two wraps of human reaction time, which
        is the window the wrap can steal a phrase in."""

        channel = self.group
        if self.channel_kind(channel) != "voice":
            return
        st = self.state[channel]
        previous = tlib.ring_pop(st["ring"])
        if previous is None:
            return
        st["register"] = previous
        self.apply(channel, "random", 0)
        self._write_voice_pattern(channel)
        with self.lock:
            self._render_display()

    def _apply_generator(self, channel, param, value):
        """Generator writes reach zynseq from here.

        CHANCE and SWING are native per-pattern properties, persisted in the
        .zss and costing zero pattern writes, which is what keeps the write
        burst - the largest risk in this design - as small as it is."""

        if param == "chance":
            with self.lock:
                self._select_pattern(channel)
                self.libseq.setPlayChance(value / 100.0)
        elif param == "swing":
            # The surface reads the classic 50-75 swing percentage; libseq
            # takes 0..1, the same units the touchscreen pattern editor uses.
            with self.lock:
                self._select_pattern(channel)
                self.libseq.setSwingAmount((value - 50) / 50.0)
        elif param == "density" and self.channel_kind(channel) == "voice":
            # The mask is a function of the register, so nothing about the
            # register moves here - only which of its steps get written.
            self._write_voice_pattern(channel)
        elif param in ("gate", "octave", "range") and \
                self.channel_kind(channel) == "voice":
            # Timbre-ish, but they only exist in the written notes, so the
            # line has to be rewritten from the unchanged register. Law L2
            # still holds: nothing about the register or the structure moved.
            self._write_voice_pattern(channel)
        elif param == "velo" and self.channel_kind(channel) == "voice":
            self._write_voice_pattern(channel)
        elif param == "velo" and self.channel_kind(channel) == "drum":
            # Velocity is written into the notes, so it only becomes audible
            # once the pattern is rewritten.
            with self.lock:
                self._write_pattern(channel)

    def channel_kind(self, channel):
        """The kind a channel behaves as: the player's override if set,
        otherwise whatever its chain says."""

        return tlib.resolve_kind(self.kind_override[channel],
                                 self._chain_kind(channel))

    def _is_sampler(self, channel):
        """Does this channel's CHAIN run a sampler, regardless of how the
        channel is behaving? SP4 lets a kit be driven by the Turing register,
        so 'behaves as a voice' and 'is a synth' stop being the same
        question."""

        return self._chain_kind(channel) == "drum"

    def _chain_kind(self, channel):
        """'drum' or 'voice' for a channel.

        The table is the intent, but the loaded snapshot is the truth: the
        shipped drum rig (021) puts LinuxSampler on all eight, and rendering a
        voice page against a sampler chain would show four columns backed by
        nothing. A chain running LinuxSampler is a drum channel whatever the
        table says."""

        kind = tlib.CHANNELS[channel][2]
        if kind != "voice":
            return kind
        chain_ids = self.chain_manager.midi_chan_2_chain_ids[tlib.CHANNELS[channel][5]]
        if not chain_ids:
            return kind
        chain = self.chain_manager.chains.get(chain_ids[0])
        if chain is None:
            return kind
        for proc in chain.get_processors():
            name = getattr(proc.engine, "name", "") if proc.engine else ""
            if "LinuxSampler" in str(name) or "FluidSynth" in str(name):
                return "drum"
        return kind

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

    def _set_mode(self, name):
        """Latched, mutually exclusive, five of them. Pressing the lit mode
        returns to CONTROL, which is home; pressing CONTROL while lit does
        nothing. The mode buttons are deliberately NOT subject to the tap/hold
        law - a momentary mode is a mode you cannot two-hand."""

        if name == self.mode:
            if name == "CONTROL":
                return
            name = "CONTROL"
        # A pad held across a mode change stops being an instrument mid-note.
        self._release_all()
        self.mode = name
        # The encoders now mean something else, so their accumulated fractions
        # belong to the previous mode and must not leak into this one.
        self._recentre_encoders()
        self.enc_carry.clear()
        with self.lock:
            self._render_all()

    # CONTROL page column -> index into the engine's symbol tuple from gate G2
    VOICE_CTRL_COLUMNS = {"cutoff": 0, "reso": 1, "env": 2, "decay": 3}

    def _voice_processor(self, channel):
        """The chain's synth processor - the one that is neither of the two
        inserts."""

        chain_ids = self.chain_manager.midi_chan_2_chain_ids[tlib.CHANNELS[channel][5]]
        if not chain_ids:
            return None
        chain = self.chain_manager.chains.get(chain_ids[0])
        if chain is None:
            return None
        for proc in chain.get_processors():
            name = str(getattr(proc.engine, "name", "") if proc.engine else "")
            if "TAP Reverberator" in name or "TAP Stereo Echo" in name:
                continue
            return proc
        return None

    def _nudge_preset(self, channel, delta):
        """Step a voice through its engine's preset list - deferred, never
        loaded here.

        Loading a preset talks to the engine over a socket and can block for
        seconds. Doing it inline hung the whole instrument: this runs on the
        MIDI handler thread, which holds self.lock for the length of the
        event, so a blocking load stalls the poll thread, the renderers and
        eventually the UI. Hardware-confirmed - the machine froze on the
        arrow buttons and had to be restarted.

        So the encoder only moves a number and arms a deadline. _commit_preset
        does the loading on the playhead thread, outside the lock, exactly as
        _commit_kit has always done for drum kits."""

        proc = self._voice_processor(channel)
        if proc is None:
            return
        # Only a list already in hand is used here. Loading one can be slow,
        # and slow on this thread is what froze the instrument - _commit_preset
        # resolves and clamps the index on the poll thread instead.
        presets = self.preset_cache.get(channel) or getattr(proc, "preset_list", None)
        pending = self.preset_pending
        current = pending[1] if pending and pending[0] == channel \
            else int(getattr(proc, "preset_index", 0))
        index = max(0, current + delta)
        if presets:
            index = min(len(presets) - 1, index)
            self.state[channel]["preset"] = str(presets[index][2])[:4]
        self.preset_pending = (channel, index, time.monotonic() + PRESET_LOAD_DELAY_S)
        with self.lock:
            self._render_display()

    def _preset_list(self, channel):
        """The voice's preset list, loaded once and cached. load_preset_list()
        itself can be slow, so it is never called from the MIDI thread."""

        cached = self.preset_cache.get(channel)
        if cached is not None:
            return cached
        proc = self._voice_processor(channel)
        if proc is None:
            return []
        presets = getattr(proc, "preset_list", None)
        if not presets:
            try:
                proc.load_preset_list()
            except Exception as e:
                logging.error(f"Maschine: preset list failed on {tlib.CHANNELS[channel][1]}: {e}")
                return []
            presets = getattr(proc, "preset_list", None) or []
        self.preset_cache[channel] = presets
        return presets

    def _commit_preset(self):
        """Load a preset whose delay has elapsed. Runs on the playhead thread,
        outside self.lock, because the load can block.

        Same identity check as _commit_kit: if the encoder replaced the
        pending tuple while this was deciding, back off rather than discard
        the player's newer turn."""

        pending = self.preset_pending
        if pending is None or time.monotonic() < pending[2]:
            return
        if self.preset_pending is pending:
            self.preset_pending = None
        else:
            return
        channel, index, _ = pending
        presets = self._preset_list(channel)
        proc = self._voice_processor(channel)
        if not presets or proc is None:
            return
        index = max(0, min(len(presets) - 1, index))
        try:
            proc.set_preset(index)            # NOT under the lock
        except Exception as e:
            logging.error(f"Maschine: preset load failed on {tlib.CHANNELS[channel][1]}: {e}")
            return
        self.state[channel]["preset"] = str(presets[index][2])[:4]
        self._invalidate_gen_cache()
        with self.lock:
            self._render_display()

    def _set_voice_ctrl(self, channel, column, value):
        """0-127 on the surface onto whatever range the engine's control has.

        The symbol comes from gate G2's measured table, never from a guess,
        and a symbol the engine does not publish leaves the knob dead rather
        than silently moving something else - law L4."""

        engine = tlib.CHANNELS[channel][4]
        symbols = tlib.VOICE_SYMBOLS.get(engine)
        if not symbols:
            return
        proc = self._voice_processor(channel)
        if proc is None:
            return
        zctrl = proc.controllers_dict.get(symbols[column])
        if zctrl is None:
            logging.debug(f"Maschine: {engine} has no '{symbols[column]}'")
            return
        span = zctrl.value_max - zctrl.value_min
        zctrl.set_value(zctrl.value_min + span * (value / 127.0), True)

    def fx_handle(self, channel, which):
        """'This channel's reverb', addressed through the chain rather than a
        hard-coded plugin symbol, so swapping the plugin - into G1's headroom,
        or from insert to bus in pass three - changes one function.

        Note the wet is a PLUGIN zctrl, not an engine zctrl, which is why
        LinuxSampler's empty _ctrls cannot reach it: both knobs are live on
        drums and on voices with no exception."""

        chain_ids = self.chain_manager.midi_chan_2_chain_ids[tlib.CHANNELS[channel][5]]
        if not chain_ids:
            return None
        chain = self.chain_manager.chains.get(chain_ids[0])
        if chain is None:
            return None
        want = "TAP Reverberator" if which == "reverb" else "TAP Stereo Echo"
        for proc in chain.get_processors():
            name = getattr(proc.engine, "name", "") if proc.engine else ""
            if want in str(name):
                return proc
        return None

    def _set_wet(self, channel, which, percent):
        """0-100 on the surface onto the plugin's dB range. Gate G3 measured
        these as true wet levels: the dry survives a full sweep, which is the
        contract encoders 7 and 8 rest on."""

        proc = self.fx_handle(channel, which)
        if proc is None:
            return
        table = tlib.FX_REVERB if which == "reverb" else tlib.FX_DELAY
        symbols = [table["WET"][0]]
        if "WET_R" in table:                  # the echo's two sides are ganged
            symbols.append(table["WET_R"][0])
        lo, hi = table["WET"][1], table["WET"][2]
        value = lo + (hi - lo) * (percent / 100.0)
        for symbol in symbols:
            zctrl = proc.controllers_dict.get(symbol)
            if zctrl is not None:
                zctrl.set_value(value, True)

    # --- lifecycle -----------------------------------------------------

    def init(self):
        super().init()
        zynsigman.register_queued(
            zynsigman.S_STEPSEQ, self.zynseq.SS_SEQ_PROGRESS, self._on_progress)
        # Progress signals stop arriving the moment a sequence stops, so the
        # last playhead pad would stay white forever without a play-state
        # signal to trigger the clearing render.
        zynsigman.register_queued(
            zynsigman.S_STEPSEQ, self.zynseq.SS_SEQ_PLAY_STATE, self._on_progress)
        # A snapshot load replaces the patterns, the chains and the mixer
        # state underneath the driver, so every LED on the device is stale
        # afterwards. The state manager sends this once the whole restore is
        # finished (zynthian_state_manager.py:1273), which is exactly when a
        # full re-render is safe.
        zynsigman.register_queued(
            zynsigman.S_STATE_MAN, self.state_manager.SS_LOAD_SNAPSHOT,
            self._on_snapshot)
        # Peak metering is off by default and costs nothing until a mixer page
        # asks for it. Two signatures exist and the Pi runs the older one:
        # enable_dpm(enable) here, enable_dpm(start, end, enable) there.
        mixer = self.state_manager.zynmixer
        if hasattr(mixer, "enable_dpm"):
            try:
                mixer.enable_dpm(True)
            except TypeError:
                try:
                    mixer.enable_dpm(0, mixer.MAX_NUM_CHANNELS - 1, True)
                except Exception:
                    logging.debug("Maschine: mixer has no usable DPM")
            except Exception:
                logging.debug("Maschine: mixer has no usable DPM")
        with self.lock:
            self._force_loop_mode()
            self._recentre_encoders()
            self._render_all()
        self._force_swing_div()
        if self.playhead_thread and self.playhead_thread.is_alive():
            # init() twice without end() would stack poll threads, each one
            # hammering libseq at 30 Hz.
            logging.warning("Maschine: playhead thread already running")
            return
        self.stopping.clear()
        self.playhead_thread = Thread(
            target=self._playhead_loop, name="maschine_mk2_playhead", daemon=True)
        self.playhead_thread.start()

    def end(self):
        self.stopping.set()
        if self.playhead_thread:
            self.playhead_thread.join(timeout=1.0)
            self.playhead_thread = None
        zynsigman.unregister(
            zynsigman.S_STEPSEQ, self.zynseq.SS_SEQ_PROGRESS, self._on_progress)
        zynsigman.unregister(
            zynsigman.S_STEPSEQ, self.zynseq.SS_SEQ_PLAY_STATE, self._on_progress)
        zynsigman.unregister(
            zynsigman.S_STATE_MAN, self.state_manager.SS_LOAD_SNAPSHOT,
            self._on_snapshot)
        self.light_off()
        super().end()

    def _force_swing_div(self):
        """Swing division is per pattern, so it is asserted rather than
        trusted - the spec's open item.

        The value is 1, not 4: track.cpp delays a step when
        (step + div) % (2 * div) == 0, so div 1 delays every second step,
        regardless of what a step represents. This assertion is the same for
        every channel and every note division - it does not know or care
        whether a step is a 1/16 or a 1/4. At 1/16 steps that delay is 1/16
        swing; the musical result at any other division follows from the
        same rule, but nothing about that has been confirmed - in particular,
        the behaviour with 1/4 (one step per beat) is untested on hardware.
        It is also the default, but a default that agrees with the intent by
        accident is still a default."""

        with self.lock:
            for group in range(8):
                self._select_pattern(group)
                if self.libseq.getSwingDiv() != 1:
                    self.libseq.setSwingDiv(1)

    def _force_loop_mode(self, group=None):
        """Per-group pattern lengths only produce polyrhythm in LOOP mode.
        LOOPSYNC and LOOPALL reset m_nPosition to 0 on the sync signal
        (sequence.cpp:137), which would drag every group back into alignment
        and defeat the whole point.

        Worse than mere alignment: a LOOPALL sequence shorter than the bar
        goes RESTARTING at its own end, which the next non-sync clock turns
        into STARTING, and STARTING does not clock its tracks
        (sequence.cpp:142). A 12-step group therefore played 12 steps and then
        sat silent until the next bar sync - the polyrhythm was inaudible.

        Doing this once in init() is not enough: restoring a snapshot rewrites
        every sequence's play mode from the .zss, and the prepared snapshot
        carries LOOPALL. Hence the re-force on every pattern write and every
        transport start, which is where a wrong mode would be heard."""

        for grp in (range(8) if group is None else (group,)):
            if self.libseq.getPlayMode(self.zynseq.bank, grp) != zynseq_lib.SEQ_LOOP:
                self.libseq.setPlayMode(self.zynseq.bank, grp, zynseq_lib.SEQ_LOOP)

    def light_off(self):
        self._release_all()
        self.leds.clear()
        self.head_shown = None
        for pad in range(16):
            self._send_osc(lib.pad_osc(pad, 0x000000, 0.0))
        for group in range(8):
            self._send_osc(lib.button_osc(f"group_{chr(ord('a') + group)}", 0x000000, 0.0))
        self._send_osc(lib.button_osc("play", COLOR_PLAY, 0.0))
        for screen in (0, 1):
            self._send_osc(lib.display_clear_osc(screen))

    # --- persistence ----------------------------------------------------

    @staticmethod
    def _stash_out(value):
        """One stashed entry on its way into a snapshot. Ints pass through; a
        state dict loses its `pending` set and hands over its ring as a plain
        list, because neither a set nor a deque survives JSON."""

        if not isinstance(value, dict):
            return value
        out = {k: v for k, v in value.items() if k != "pending"}
        if "ring" in out:
            out["ring"] = list(out["ring"])
        return out

    def get_state(self):
        """What the snapshot must carry that nothing else owns.

        Patterns, chance, swing, mixer levels, mutes and the insert wets all
        live in objects that are already saved. The Turing registers and their
        undo rings do not - they exist only here, and a snapshot without them
        restores a machine that plays different music. Persisted from day one
        deliberately: adding it later leaves every existing snapshot missing
        it, with no way to tell."""

        return {
            "globals": {k: v for k, v in self.globals.items() if k != "pending"},
            "mode": self.mode,
            "pages": {f"{mode}|{kind or ''}": index
                      for (mode, kind), index in self.page_idx.items()},
            "selected": self.group,
            # SP4: the player's explicit kind choices, and the sleeping state
            # set for the kind each channel is not. Only channels that were
            # actually switched appear - an absent entry means "ask the chain".
            "kinds": {str(i): self.kind_override[i]
                      for i in range(len(tlib.CHANNELS))
                      if self.kind_override[i] is not None},
            "stash": {str(i): {k: self._stash_out(v) for k, v in sets.items()}
                      for i, sets in self.stash.items() if sets},
            # Who writes each pattern. Its own key rather than a field inside
            # "voices", because a DRUM channel can be player-owned too and
            # "voices" holds only the three voices. Only the flag is saved:
            # the notes themselves are already in the .zss, and the note map
            # is rebuilt from the pattern rather than trusted.
            "owners": {str(i): self.owner[i]
                       for i in range(len(tlib.CHANNELS))},
            "voices": {
                str(i): {
                    "register": self.state[i]["register"],
                    "ring": list(self.state[i]["ring"]),
                    "length": self.state[i]["length"],
                    "random": self.state[i]["random"],
                    "gate": self.state[i]["gate"],
                    "octave": self.state[i]["octave"],
                    "range": self.state[i]["range"],
                    "velo": self.state[i]["velo"],
                    "density": self.state[i]["density"],
                }
                # SP4: keyed on how the channel BEHAVES, not on the table. A
                # drum chain switched to voice holds register, gate and octave
                # that exist nowhere else - the table would have dropped them
                # on save and the take would come back as a drum.
                for i, ch in enumerate(tlib.CHANNELS)
                if self.channel_kind(i) == "voice" and "register" in self.state[i]
            },
        }

    def set_state(self, state):
        if not isinstance(state, dict):
            return
        globals_in = state.get("globals") or {}
        for key, value in globals_in.items():
            if key in self.globals:
                self.globals[key] = value
        # Reading "page" as a fallback is deliberate: a snapshot written by the
        # shipped prototype carries "page": "STEP", and those three names are
        # also mode names, so an old snapshot restores to the right mode
        # instead of silently landing on CONTROL.
        self.mode = state.get("mode", state.get("page", self.mode))
        if self.mode not in tlib.MODES:
            self.mode = "CONTROL"
        self.page_idx = {}
        for key, index in (state.get("pages") or {}).items():
            mode, _, kind = str(key).partition("|")
            if mode in tlib.MODES and isinstance(index, int):
                self.page_idx[(mode, kind or None)] = index
        selected = state.get("selected", self.group)
        if isinstance(selected, int) and 0 <= selected < 8:
            self.group = selected

        for key, who in (state.get("owners") or {}).items():
            try:
                channel = int(key)
            except (TypeError, ValueError):
                continue
            if channel in self.owner and who in ("gen", "player"):
                self.owner[channel] = who

        for key, kind in (state.get("kinds") or {}).items():
            try:
                channel = int(key)
            except (TypeError, ValueError):
                continue
            if channel in self.kind_override and kind in tlib.KINDS:
                self.kind_override[channel] = kind

        for key, sets in (state.get("stash") or {}).items():
            try:
                channel = int(key)
            except (TypeError, ValueError):
                continue
            if channel not in self.stash:
                continue
            restored = {}
            for name, value in sets.items():
                if isinstance(value, dict):
                    value = dict(value)
                    # pending is rebuilt empty rather than restored: it holds
                    # parameters waiting for the next bar, and a snapshot load
                    # has no bar to wait for.
                    value["pending"] = set()
                    if "ring" in value:
                        value["ring"] = deque(value["ring"], maxlen=4)
                restored[name] = value
            self.stash[channel] = restored

        # SP4: a restored override says a channel behaves as the other kind,
        # but its ACTIVE state dict is still the one __init__ built for the
        # table's kind. Align them before anything reads them: columns()
        # indexes state["cutoff"] directly, so a drum dict on a voice-behaving
        # channel is a KeyError on the first repaint.
        for channel in range(len(tlib.CHANNELS)):
            kind = self.channel_kind(channel)
            shaped = "register" if kind == "voice" else "kit"
            if shaped in self.state[channel]:
                continue
            other = "drum" if kind == "voice" else "voice"
            self.stash[channel][other] = self.state[channel]
            self.state[channel] = self.stash[channel].get(
                kind, tlib.default_channel_state(kind))

        for key, saved in (state.get("voices") or {}).items():
            try:
                channel = int(key)
            except (TypeError, ValueError):
                continue
            if channel not in self.state or "register" not in self.state[channel]:
                continue
            st = self.state[channel]
            for field in ("register", "length", "random", "gate", "octave",
                          "range", "velo", "density"):
                if field in saved:
                    st[field] = saved[field]
            st["ring"] = deque(saved.get("ring", []), maxlen=4)

        # Take each voice's division from what the snapshot actually restored,
        # BEFORE rewriting its pattern. _write_voice_pattern writes
        # setStepsPerBeat/setBeatsInPattern from self.div, so without this it
        # stamps whatever division was last on the panel over the one just
        # loaded - and _derive_params afterwards reads the stamped value back,
        # leaving the driver and zynseq agreeing on the wrong answer. A voice's
        # DIVIDE had never survived a snapshot load.
        with self.lock:
            for channel, ch in enumerate(tlib.CHANNELS):
                if ch[2] == "voice" and self.channel_kind(channel) == "voice":
                    self._derive_params(channel)

        # The restored registers describe lines nobody has written yet, and a
        # locked voice will never write them on its own - that is what the
        # lock means. Write them once, now.
        for channel, ch in enumerate(tlib.CHANNELS):
            if ch[2] == "voice" and self.channel_kind(channel) == "voice":
                self._write_voice_pattern(channel)
        with self.lock:
            self._render_all()

    # --- MIDI ----------------------------------------------------------

    def midi_event(self, ev):
        with self.lock:
            return self._midi_event(ev)

    def _midi_event(self, ev):
        evtype = (ev[0] >> 4) & 0x0F

        if evtype in (0x8, 0x9):                 # NoteOff and NoteOn
            step = ev[1] - GROUP_NOTE_BASE[self.group]
            if not 0 <= step < 16:
                return False
            if evtype == 0x8 or ev[2] == 0:
                # A release. In STEP mode nothing is ever held, so the pop
                # inside _pad_up finds nothing and this is a no-op.
                self._pad_up(step)
                return True
            if self.mode == "STEP":
                # The step editor stays bound to NoteOn only, so dropping the
                # note-off filter cannot make it toggle twice per strike.
                if self.erase_down:
                    self._erase_step(step)
                else:
                    self._toggle_step(step, ev[2] & 0x7F)
                return True
            self._pad_down(step, ev[2] & 0x7F)
            return True

        if evtype == 0xB:
            cc_num, cc_val = ev[1] & 0x7F, ev[2] & 0x7F
            if cc_num in ENCODER_CCS:
                # Encoders carry a position in cc_val, so they must be handled
                # before the press-only filter below throws every value away.
                self._encoder_column(cc_num - ENCODER_CCS[0], cc_num, cc_val)
                return True
            down = cc_val == 127
            # Buttons that carry state across press and release come first:
            # the press-only filter below throws releases away, and for a
            # momentary gesture the release IS the event.
            if cc_num == CC_ERASE:
                self.erase_down = down
                return True
            if cc_num == CC_REC:
                # Held, and it overdubs: release ends the take. Held notes are
                # NOT released here - letting go of REC stops capturing, it
                # does not stop the instrument sounding.
                self.rec_down = down
                self._render_display()
                return True
            if cc_num == CC_SHIFT:
                self.shift_down = down
                return True
            if cc_num == CC_SOLO:
                self._solo_button(down)
                return True
            fbtn = cc_num - CC_F1
            if 0 <= fbtn < 8:
                self._f_button(fbtn, down)
                return True

            if not down:                         # everything else: press only
                return False
            if cc_num in MODE_BUTTONS:
                self._set_mode(MODE_BUTTONS[cc_num])
                return True
            if cc_num == CC_GRID:
                # A bare GRID press is swallowed and does nothing. Deliberate:
                # it stays free for a later feature and cannot fall through to
                # something else that reacts to it - which is exactly what an
                # unbound CC 3 was doing before SP2 claimed it.
                if self.shift_down:
                    self._toggle_kind()
                return True
            if cc_num == CC_DUPLICATE:
                self._duplicate()
                return True
            if cc_num == CC_PLAY:
                self._toggle_transport()
                return True
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
            if cc_num == CC_RESTART:
                for group in range(8):
                    # Installed signature: setPlayPosition(bank, sequence, clock)
                    self.libseq.setPlayPosition(self.zynseq.bank, group, 0)
                return True
            group = cc_num - GROUP_CC_FIRST
            if 0 <= group < 8:
                if self.erase_down:
                    if self.owner[group] == "player":
                        # On a player-owned channel this is an undo, not a
                        # silencing: drop the take and let the machine refill.
                        self._handback(group)
                        return True
                    # Hold ERASE + Group silences that channel. It never wipes
                    # the note list: the generator owns the pattern and would
                    # write it straight back, so the erase would look broken.
                    self._silence_channel(group)
                    return True
                self._select_group(group)
                return True

        return False

    # --- actions -------------------------------------------------------

    def _select_group(self, group):
        self._release_all()          # the pads are about to mean another sound
        self.group = group
        self._kit_retry_at = 0.0          # a new chain deserves an immediate look
        self._derive_params(group)
        self._recentre_encoders()
        self._render_all()

    def _derive_params(self, group):
        """Read back what zynseq actually holds so the encoders resume from
        real values after a snapshot load or a run of pad edits. Rotation is
        not recoverable from a pattern - it stays at whatever the driver last
        set."""

        self._select_pattern(group)
        spb = self.libseq.getStepsPerBeat()
        for idx, (_, div_spb, _) in enumerate(lib.DIVISIONS):
            if div_spb == spb:
                self.div[group] = idx
                break
        self.beats[group] = max(MIN_BEATS, self.libseq.getBeatsInPattern())
        # CHANCE and SWING are per-pattern zynseq properties, saved inside the
        # snapshot's own riff. The driver used to keep only its own copy and
        # default it to 100 on load, so a channel saved at chance 0 came back
        # silent while the surface said 100 and the tab drew solid - the one
        # mechanism this instrument has for explaining silence, reporting the
        # channel healthy. Read the real values back instead of assuming them.
        state = self.state.get(group)
        if state is not None:
            # Guarded for the same reason the mixer's DPM is: the Pi's
            # libzynseq is older than this checkout and has surprised this
            # project three times. A resync that throws would leave every
            # channel unsynced, which is worse than the values it recovers.
            try:
                state["chance"] = int(round(self.libseq.getPlayChance() * 100))
                state["swing"] = int(round(self.libseq.getSwingAmount() * 50 + 50))
            except Exception:
                logging.debug("Maschine: no readable chance/swing on this libzynseq")
        note = self._group_note(group)
        steps = self.libseq.getSteps()
        self.hits[group] = sum(
            1 for step in range(steps) if self.libseq.getNoteVelocity(step, note))

    def _recentre_encoders(self):
        """Park every encoder mid-range in the daemon, so none of them starts
        driving a new group from against an end stop."""

        for idx, cc_num in enumerate(ENCODER_CCS):
            self._send_osc(lib.encoder_osc(idx, ENC_CENTRE))
            self.enc_last[cc_num] = ENC_CENTRE
            self.enc_carry[cc_num] = 0

    def _enc_delta(self, cc_num, cc_val):
        """Raw encoder movement since its last message, re-centring the knob
        before it reaches the daemon's 0-127 clamp.

        The next value may already have been in flight when the re-centre was
        sent, so the baseline is dropped rather than assumed: the following
        message re-establishes it, and only that message's own movement is
        lost - a fraction of one step."""

        delta = lib.encoder_delta(self.enc_last.get(cc_num), cc_val)
        self.enc_last[cc_num] = cc_val
        if not ENC_RECENTRE_MARGIN <= cc_val <= 127 - ENC_RECENTRE_MARGIN:
            self._send_osc(lib.encoder_osc(cc_num - ENCODER_CCS[0], ENC_CENTRE))
            self.enc_last[cc_num] = None
        return delta

    def _enc_steps_fixed(self, cc_num, cc_val, units):
        """Encoder movement in whole steps at an explicit units-per-step,
        for parameters with too few settings for the sweep to divide well."""

        delta = self._enc_delta(cc_num, cc_val)
        if delta == 0:
            return 0
        steps, carry = lib.encoder_steps(self.enc_carry.get(cc_num, 0), delta, units)
        self.enc_carry[cc_num] = carry
        return steps

    def _enc_steps(self, cc_num, cc_val, values):
        """Encoder movement in whole steps of a parameter that has `values`
        distinct settings, with the remainder carried.

        `values` is what sets the feel: the absolute mapping this replaces
        spread a parameter's whole range across the encoder's 128-unit sweep,
        so dividing the sweep by the number of settings reproduces exactly
        that sensitivity while the value itself stays per group."""

        delta = self._enc_delta(cc_num, cc_val)
        if delta == 0:
            return 0
        steps, carry = lib.encoder_steps(
            self.enc_carry.get(cc_num, 0), delta, lib.units_per_step(values))
        self.enc_carry[cc_num] = carry
        return steps

    def _encoder_column(self, column, cc_num, cc_val):
        """Turn an encoder movement into (verb, channel, value).

        Three shapes, one dispatch. `channel` resolves to the selected channel,
        to the column's own channel, or to None for a global - and _verb() has
        always taken the channel as an argument, so nothing below this changes.

        Which verb each column carries now lives in techno_lib.PAGE_RINGS,
        where it is unit tested. None is a column with no source: law L4 draws
        it greyed and the encoder does nothing at all."""

        desc = self._page()
        shape = desc["shape"]
        if shape == tlib.SHAPE_SPREAD:
            verb, channel = desc["verb"], column
        else:
            verb = desc["verbs"][column]
            # A global page still passes the selected channel, exactly as the
            # shipped ALL page did. _verb() resolves a global by verb name and
            # ignores the channel, but its first line asks the channel for its
            # kind - so None would raise before the global branch is reached.
            channel = self.group
        if verb is None:
            return                        # greyed column, dead knob, honestly
        self._verb(verb, channel, cc_num, cc_val)

    # Range and step size per verb: (lo, hi, units per step).
    # Fine controls sweep across the encoder's 128 units; coarse ones use a
    # flat 8 units per detent, because spreading a handful of settings over
    # the whole sweep reads as sticky.
    VERB_RANGES = {
        "velo": (1, 127, None),
        "chance": (0, 100, None),
        "density": (0, 100, None),
        "swing": (50, 75, ENC_UNITS_DISCRETE),
        "level": (0, 100, None),
        "reverb": (0, 100, None),
        "delay": (0, 100, None),
        "cutoff": (0, 127, None),
        "reso": (0, 127, None),
        "env": (0, 127, None),
        "decay": (0, 127, None),
        "random": (0, 100, None),
        # 5-800, widened from 5-100 for the 8-step note length. The old
        # 5-100 range is now a sliver of the sweep, so gate moves in jumps
        # of roughly 6-24 per encoder report - a deliberate resolution
        # trade-off, not a bug to smooth out.
        "gate": (5, tlib.GATE_MAX, None),
        "octave": (-2, 2, ENC_UNITS_DISCRETE),
        "range": (1, 4, ENC_UNITS_DISCRETE),
    }

    def _verb(self, verb, channel, cc_num, cc_val):
        # Generated pages address a plugin port directly and have no entry in
        # any of the tables below, so they are resolved first.
        if verb.startswith(tlib.VERB_LV2):
            self._verb_lv2(verb[len(tlib.VERB_LV2):], channel, cc_num, cc_val)
            return
        if verb.startswith(tlib.VERB_FX):
            which, _, symbol = verb[len(tlib.VERB_FX):].partition(":")
            self._verb_fx(which, symbol, cc_num, cc_val)
            return

        voice = self.channel_kind(channel) == "voice"

        if verb == "length" and voice:
            # LENGTH on a voice is the shift register, not the pattern. Sent
            # to the drum handler it changed the pattern's beats instead,
            # which the next rewrite silently reset - the knob looked dead and
            # the register was unreachable from the surface.
            delta = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if delta:
                if self.owner[channel] == "player":
                    self._handback(channel)
                st = self.state[channel]
                self.apply(channel, "length", min(16, max(2, st["length"] + delta)))
                self._write_voice_pattern(channel)
                with self.lock:
                    self._render_display()
            return

        if verb == "div" and voice:
            # The drum handler would rewrite the pattern from euclid, turning
            # a melodic line into a single repeated drum note. At LOCK nothing
            # would ever repair it.
            delta = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if delta:
                new_div = min(len(lib.DIVISIONS) - 1, max(0, self.div[channel] + delta))
                if new_div != self.div[channel]:
                    if self.owner[channel] == "player":
                        self._handback(channel)
                    self.div[channel] = new_div
                    self._write_voice_pattern(channel)
                    with self.lock:
                        self._render_pads()
            return

        if verb in ("hits", "rotate", "div", "length"):
            self._encoder(cc_num, cc_val, verb)
            return
        if verb == "kit":
            steps = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if steps:
                self._nudge_kit(steps)
            return
        if verb == "sample":
            steps = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if steps:
                self._cycle_sample(steps)
            return
        if verb == "preset":
            steps = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if steps:
                self._nudge_preset(channel, steps)
            return

        if self.mode == "ALL":
            span = self.GLOBAL_RANGES.get(verb)
            if span is None:
                return
            lo, hi, units = span
            delta = (self._enc_steps_fixed(cc_num, cc_val, units) if units
                     else self._enc_steps(cc_num, cc_val, hi - lo + 1))
            if delta == 0:
                return
            current = self.globals[verb]
            if verb in ("bpm", "master"):
                current = self.globals_view()[verb]      # live, for the same reason
            self.apply_global(verb, min(hi, max(lo, current + delta)))
            with self.lock:
                self._render_display()
            return

        span = self.VERB_RANGES.get(verb)
        if span is None:
            return
        lo, hi, units = span
        if units:
            delta = self._enc_steps_fixed(cc_num, cc_val, units)
        else:
            delta = self._enc_steps(cc_num, cc_val, hi - lo + 1)
        if delta == 0:
            return
        current = self.param_get(channel, verb)
        if verb == "level":
            # Read the live value, not the stored copy: the touchscreen and
            # the snapshot both move the fader behind the driver's back, and
            # incrementing a stale number makes the first turn jump.
            chan = self._mixer_chan(channel)
            if chan is not None:
                current = int(round(self.state_manager.zynmixer.get_level(chan) * 100))
        if current is None:
            return
        new_value = min(hi, max(lo, current + delta))
        # RANDOM only hands back when it moves OFF lock. Turning it down to 0
        # is what _claim itself does, and that must not undo the recording it
        # has just made.
        if self.owner[channel] == "player" and tlib.hands_back(
                self.channel_kind(channel), verb, new_value):
            self._handback(channel)
        self.apply(channel, verb, new_value)
        with self.lock:
            self._render_display()

    def _encoder(self, cc_num, cc_val, verb):
        """The four euclid parameters. They keep their own handler because
        each one has to re-clamp the others and rewrite the pattern, which the
        generic verb path deliberately does not do."""

        group = self.group

        def take_back():
            """The generator takes back what you turn. A dead knob would be
            the unexplained-silence law in another form.

            Called only once a real movement is known: an encoder report below
            the step threshold yields delta 0, and that must not destroy a
            take the player never asked to lose."""

            if self.owner[group] == "player" and tlib.hands_back("drum", verb):
                self._handback(group)

        if verb == "div":
            delta = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if delta == 0:
                return
            take_back()
            self.div[group] = min(len(lib.DIVISIONS) - 1, max(0, self.div[group] + delta))
            self._clamp_params(group)
            # Law L2: structure lands on the bar. The value shows in brackets
            # until the pattern's own next wrap takes it, so a division change
            # mid-bar cannot trip the groove.
            self.state[group]["pending"].add("div")
            self.state[group]["pending"].add("length")
            with self.lock:
                self._render_display()
            return
        elif verb == "length":
            top = self._max_beats(group)
            delta = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if delta == 0:
                return
            beats = min(top, max(MIN_BEATS, self.beats[group] + delta))
            if beats != self.beats[group]:
                self.beats[group] = beats
                self._clamp_params(group)
                self.state[group]["pending"].add("length")
                with self.lock:
                    self._render_display()
            return
        else:
            steps = self._steps(group)
            delta = self._enc_steps(cc_num, cc_val, steps + 1)
            if delta == 0:
                return
            take_back()
            if verb == "hits":
                self.hits[group] = min(steps, max(0, self.hits[group] + delta))
            else:
                self.rot[group] = min(max(0, steps - 1), max(0, self.rot[group] + delta))
        self._write_pattern(group)

    def _set_length(self, group, beats):
        """Change a group's length without touching which steps are on.

        Encoders 1-3 own the steps and regenerate them, but length is a
        different kind of edit: shortening a pattern to hear a polyrhythm
        should not throw away the beat that is playing. zynseq drops only the
        notes past the new end (pattern.cpp:391-400) and keeps the rest where
        they are, so the steps inside the new length survive untouched;
        growing back leaves the new steps empty rather than restoring what a
        previous shrink discarded.

        hits is re-counted from the notes that remain so encoder 1 resumes
        from what is really there instead of from a stale figure."""

        self.beats[group] = beats
        self._select_pattern(group)
        self._force_loop_mode(group)
        self.libseq.setBeatsInPattern(beats)
        self.libseq.updateSequenceInfo()
        note = self._group_note(group)
        steps = self.libseq.getSteps()
        self.hits[group] = sum(
            1 for step in range(steps) if self.libseq.getNoteVelocity(step, note))
        self.rot[group] = min(max(0, steps - 1), self.rot[group])
        logging.debug(f"Maschine group {group}: length beats={beats} steps={steps} "
                      f"hits={self.hits[group]}")
        self._render_pads()

    def _steps(self, group):
        return lib.DIVISIONS[self.div[group]][1] * self.beats[group]

    def _max_beats(self, group):
        """Longest length still displayable on the 16 pads."""

        return max(MIN_BEATS, PADS // lib.DIVISIONS[self.div[group]][1])

    def _clamp_params(self, group):
        """Division and length both change the step count, so hits and
        rotation have to be pulled back inside the new range."""

        self.beats[group] = min(self._max_beats(group),
                                max(MIN_BEATS, self.beats[group]))
        steps = self._steps(group)
        self.hits[group] = min(steps, self.hits[group])
        self.rot[group] = min(max(0, steps - 1), self.rot[group])

    def _write_pattern(self, group):
        """Regenerate a group's whole pattern from its euclid parameters.
        Destructive by design: enc 1-3 own the steps, so a pad tap is an edit
        that the next encoder turn wipes.

        setStepsPerBeat rescales the notes already in the pattern
        (pattern.cpp:665-681), which is why this clears and rewrites rather
        than editing in place."""

        label, spb, _ = lib.DIVISIONS[self.div[group]]
        beats = self.beats[group]
        steps = self._steps(group)
        self._select_pattern(group)
        if self._is_sampler(group):
            note = self._group_note(group)
        else:
            # Euclid on a synth is a root pulse: ROOT transposes it, OCTAVE
            # places it. Reusing whatever pitch _group_note discovers would
            # leave the voice stuck on an arbitrary note no control can reach.
            note = tlib.pad_note(0, self.globals["root"], self.globals["scale"],
                                 self.state[group].get("octave", 0))

        # All three act on the selected pattern and take no pattern argument.
        # There is no clearPattern(index) in the installed API - clear() is it.
        # setStepsPerBeat first: it rescales existing note positions, and
        # setBeatsInPattern drops notes past the new end, so ordering matters
        # less once clear() follows, but the length must be set before the
        # rewrite so getSteps() agrees with what is written.
        velocity = int(self.state[group].get("velo", 110))
        self._force_loop_mode(group)
        self.libseq.setStepsPerBeat(spb)
        self.libseq.setBeatsInPattern(beats)
        self.libseq.clear()
        for step, on in enumerate(
                lib.build_pattern_steps(steps, self.hits[group], self.rot[group])):
            if on:
                self.libseq.addNote(step, note, velocity, 1.0, 0.0)
        self.libseq.updateSequenceInfo()
        logging.debug(f"Maschine group {group}: {label} beats={beats} steps={steps} "
                      f"hits={self.hits[group]} rot={self.rot[group]}")
        self._render_pads()

    def _mixer_chan(self, group):
        """The mixer strip behind a group, or None if it has no chain."""

        chain_ids = self.chain_manager.midi_chan_2_chain_ids[group]
        if not chain_ids:
            return None
        return self.chain_manager.chains[chain_ids[0]].mixer_chan

    def _f_button(self, index, down):
        """F1-F8. Mute by default, solo while SOLO is held or latched.

        Law L1: a tap latches, a hold is momentary. Both are needed from the
        same button inside the same bar - momentary is how you play a gesture,
        latched is how you make a decision - so the press always acts and the
        release undoes it only if the button was held past the threshold."""

        key = ("f", index)
        soloing = self.solo_down or self.solo_mode
        if down:
            self._down_at[key] = (time.monotonic(), soloing)
            self._toggle_solo(index) if soloing else self._toggle_mute(index)
            return
        went_down, was_soloing = self._down_at.pop(key, (None, soloing))
        if went_down is None:
            return
        if (time.monotonic() - went_down) * 1000.0 >= HOLD_MS:
            self._toggle_solo(index) if was_soloing else self._toggle_mute(index)

    def _solo_button(self, down):
        """Tap latches solo mode, so the F row becomes solos until tapped
        again. Held, it is a modifier: SOLO + Fn is a momentary solo."""

        if down:
            self._down_at["solo"] = (time.monotonic(), False)
            self.solo_down = True
            return
        went_down, _ = self._down_at.pop("solo", (None, False))
        self.solo_down = False
        if went_down is not None and (time.monotonic() - went_down) * 1000.0 < HOLD_MS:
            self.solo_mode = not self.solo_mode
        with self.lock:
            self._render_mutes()

    def _toggle_solo(self, group):
        chan = self._mixer_chan(group)
        if chan is None:
            return
        self.state_manager.zynmixer.toggle_solo(chan, update=True)
        with self.lock:
            self._render_mutes()
            self._render_groups()

    def _silence_channel(self, channel):
        """ERASE + Group. Sets the generator to silence rather than wiping the
        note list: a wiped list is written straight back by the next generator
        move, so the erase would appear not to have worked."""

        if self.channel_kind(channel) == "drum":
            self.apply(channel, "hits", 0)
            with self.lock:
                self._write_pattern(channel)
        else:
            # A voice is silenced with play chance, but the voice STEP page
            # has no CHANCE column - so this toggles. Without that, the only
            # way back would be the touchscreen, which is not a thing you
            # reach for mid-set.
            current = self.state[channel].get("chance", 100)
            self.apply(channel, "chance", 100 if current == 0 else 0)
        with self.lock:
            self._render_display()

    def _toggle_mute(self, group):
        """Mute is per group, not per selection: F3 always mutes group C
        whichever group the pads are showing.

        This mutes the MIXER STRIP, not the zynseq track. zynseq's file format
        has no mute field at all - its track record stores type, chain id,
        channel, output, map and the pattern list and stops there
        (zynseq.cpp:1321-1329) - so a zynseq mute was silently lost by every
        snapshot save. The mixer's mute is part of the snapshot's zs3 state
        (zynthian_state_manager.py:1434), shows up on the touchscreen mixer,
        and is the same object encoder 8 already drives for volume.

        The one behavioural difference: this silences the chain's audio, so a
        long tail is cut rather than left to ring out."""

        chan = self._mixer_chan(group)
        if chan is None:
            logging.debug(f"Maschine: group {group} has no chain to mute")
            return
        self.state_manager.zynmixer.toggle_mute(chan, update=True)
        self._render_mutes()
        self._render_groups()

    def _mixer_level(self, group):
        chan = self._mixer_chan(group)
        return 0.0 if chan is None else self.state_manager.zynmixer.get_level(chan)

    def _mixer_balance(self, group):
        chan = self._mixer_chan(group)
        return 0.0 if chan is None else self.state_manager.zynmixer.get_balance(chan)

    def _group_brightness(self, group):
        """Three independent facts on three independent dimensions: hue is
        identity, brightness is level, and dark means not sounding - muted
        directly, or excluded by somebody else's solo.

        Selection is deliberately not in here. The inverted tab on the screen
        is authoritative for that; a fourth meaning on one LED would make all
        four unreadable."""

        chan = self._mixer_chan(group)
        if chan is None:
            return BRIGHT_GROUP_NO_CHAIN
        mixer = self.state_manager.zynmixer
        if mixer.get_mute(chan):
            return 0.0
        if self._any_soloed() and not mixer.get_solo(chan):
            return 0.0
        level = min(1.0, max(0.0, mixer.get_level(chan)))
        return BRIGHT_GROUP_MIN + (BRIGHT_GROUP_MAX - BRIGHT_GROUP_MIN) * level

    def _any_soloed(self):
        mixer = self.state_manager.zynmixer
        for group in range(8):
            chan = self._mixer_chan(group)
            if chan is not None and mixer.get_solo(chan):
                return True
        return False

    def _kit_list(self):
        """The available SFZ kits as [(display name, sfz path)], read once
        from the selected group's processor. Zynthian's own preset list is
        the source rather than a directory listing, so the names match what
        set_preset_by_name expects.

        Returns [], uncached, whenever this chain has no such bank (or no
        processor at all, or the lookup blew up) - so a later call, once the
        selected group has a LinuxSampler chain, can still succeed instead of
        being stuck with whatever the FIRST call happened to see."""

        if self.kits is not None:
            return self.kits
        # The retry is deliberate - kits appear once a LinuxSampler chain is
        # selected - but it must not run at render rate. set_bank_by_name and
        # load_preset_list both talk to the engine and both would then be
        # called five times a second, under the lock, on a chain that has no
        # kits at all. That is the shape of blocking call that froze this
        # instrument once already.
        now = time.monotonic()
        if now < self._kit_retry_at:
            return []
        self._kit_retry_at = now + KIT_RETRY_S
        proc = self.chain_manager.get_synth_processor(self.group)
        if proc is None:
            self._warn_no_kits("no synth processor")
            return []
        # Note this moves that processor's selected BANK, which the preset
        # browser on the touchscreen also uses. Harmless here because every
        # kit this driver sets lives in that same bank, but do not widen it
        # to other banks without rechecking that.
        try:
            if not proc.set_bank_by_name(KIT_BANK):
                # set_bank_by_name returns False, with no exception and no
                # side effect, when the engine has no bank by that name -
                # true of every FluidSynth chain. Falling through to
                # load_preset_list() here would silently reload whatever
                # bank IS selected and report ITS presets as "kits in Drum
                # Machines", then cache that wrong list for the process's
                # life. Bail out uncached instead.
                self._warn_no_kits(f"no '{KIT_BANK}' bank on this chain")
                return []
            proc.load_preset_list()
            # preset_list entries are [path, ?, name, ...] and the path may
            # carry an instrument index after a '#' (engine set_preset splits
            # on it), which is not part of the file name.
            self.kits = [(entry[2], entry[0].split("#")[0])
                         for entry in proc.preset_list]
            logging.info(f"Maschine: {len(self.kits)} kits in '{KIT_BANK}'")
            self._kit_warned = None
        except Exception as e:
            self._warn_no_kits(f"kit list failed: {e}")
            return []
        return self.kits

    def _warn_no_kits(self, reason):
        """Log once per distinct reason, not once per call - _kit_list() now
        retries on every screen render (~5 Hz) while a chain has no kits."""

        if reason != self._kit_warned:
            logging.warning(f"Maschine: no kits ({reason})")
            self._kit_warned = reason

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

    def _current_kit_index(self, group, kits):
        """Which of `kits` is actually loaded on `group` right now.

        self.kit_index[group] is only a remembered position, and
        _reset_kit_cache() deliberately snaps it back to 0 on every snapshot
        load or chain change (see its docstring) - the chain itself keeps
        whatever preset it was saved or left with, which is very rarely kit
        0. Trusting kit_index here would make the first turn of encoder 7
        after such a reset jump from the group's real kit straight to
        whatever sits one step from index 0, with no load in between to
        make that visible ahead of time.

        `kits` is the SAME list _kit_list() built for this group (the
        caller is always the currently selected group), so the processor's
        own loaded preset name can be matched against it directly. Falls
        back to kit_index only when there is no processor, no preset name,
        or the name matches nothing in `kits` - e.g. a chain that has never
        had a kit from this bank applied yet."""

        proc = self.chain_manager.get_synth_processor(group)
        name = getattr(proc, "preset_name", None) if proc is not None else None
        if name:
            # set_preset_by_name strips this same heart-favourite prefix
            # before comparing names; match the same way in both directions
            # since a favourited kit's preset_list entry carries it too.
            if name[0] == '❤':
                name = name[2:]
            for i, (kit_name, _) in enumerate(kits):
                if kit_name[:1] == '❤':
                    kit_name = kit_name[2:]
                if kit_name == name:
                    return i
        return self.kit_index[group]

    def _nudge_kit(self, delta):
        """Move the selected group's kit choice. The load itself is deferred:
        the name on screen changes at once, and the kit is loaded once the
        knob stops, so sweeping the list costs one load rather than 41."""

        kits = self._kit_list()
        if not kits:
            return
        group = self.group
        # One local read: self.kit_pending is also written by _commit_kit on
        # the playhead thread, so re-reading the attribute between the check
        # and the use below could see it cleared out from under us.
        pending = self.kit_pending
        if pending and pending[0] == group:
            current = pending[1]
        else:
            current = self._current_kit_index(group, kits)
        index = max(0, min(len(kits) - 1, current + delta))
        if index == current:
            return
        # The whole intent - group, index and deadline - lives in one tuple
        # behind one attribute assignment, so _commit_kit on the other thread
        # can never observe a new index paired with a stale due time (or vice
        # versa): it always sees either the old tuple whole or the new one.
        self.kit_pending = (group, index, time.monotonic() + KIT_LOAD_DELAY_S)
        with self.lock:
            self._render_display()

    def _commit_kit(self):
        """Load a kit whose delay has elapsed. Runs on the playhead thread,
        outside self.lock, because the preset change can block.

        Decides entirely from a local snapshot of self.kit_pending, and only
        clears the attribute if it still holds that exact tuple - if
        _nudge_kit replaced it (on the MIDI thread) while this function was
        deciding, that identity check fails and this call backs off instead
        of discarding the newer nudge. Without it, an elapsed-but-just-
        superseded pending could be read here, decided on, and then blown
        away by `self.kit_pending = None` after _nudge_kit had already
        written its replacement - silently losing the player's last turn of
        the encoder."""

        pending = self.kit_pending
        if pending is None or time.monotonic() < pending[2]:
            return
        if self.kit_pending is pending:
            self.kit_pending = None
        else:
            return                            # a newer nudge won; let it run
        self._apply_kit(pending[0], pending[1])
        self._invalidate_gen_cache()

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
            # _preview plays on the SELECTED group's channel, so only preview
            # a kit change the player can actually hear. playNote() reaches
            # libseq, so it must stay inside this lock like every other
            # libseq call here - it was previously called after the lock had
            # already been released, which ran it unlocked from the playhead
            # poll thread on every kit commit.
            if landed is not None and group == self.group:
                self._preview(landed)

    def _keymap(self, group):
        notes = self.keymap_cache[group]
        if notes is None:
            notes = self._load_keymap(group)
            self.keymap_cache[group] = notes
        return notes

    def _load_keymap(self, group):
        """The notes available to a group: its kit's own list.

        Zynthian's keymaps.json resolves on the synth's preset path and
        matches only the FluidSynth soundfonts, so an SFZ kit would leave
        every group tab reading "note 36". The kit file has the real names."""

        kits = self._kit_list()
        if kits:
            index = self._current_kit_index(group, kits)
            _, path = kits[max(0, min(len(kits) - 1, index))]
            notes = self._kit_notes(path)
            if notes:
                return notes
        logging.info(f"Maschine group {group}: no kit notes, using the GM "
                     f"percussion range (names unavailable)")
        return [(note, f"note {note}") for note in FALLBACK_KEYMAP_NOTES]

    def _cycle_sample(self, delta):
        """Step the selected group's drum note through its keymap. Stops at
        both ends rather than wrapping, so the extremes are findable by feel."""

        group = self.group
        notes = self._keymap(group)
        if not notes:
            # Reachable: _apply_kit installs [] when a kit file is unreadable
            # or parses to nothing (_kit_notes returns [] on OSError), and
            # nothing ever reloads it since [] is not None. notes[-1] below
            # would raise IndexError, which escapes into
            # zynthian_state_manager's zynmidi_read catch-all and discards
            # the REST of that MIDI batch - including notes from a keyboard
            # playing at the same time - repeating on every encoder detent.
            if group not in self._empty_keymap_warned:
                logging.warning(
                    f"Maschine group {group}: kit has no notes, sample "
                    f"encoder/arrows have nothing to select")
                self._empty_keymap_warned.add(group)
            return
        current = self._group_note(group)
        idx = next((i for i, (note, _) in enumerate(notes) if note == current), 0)
        idx = min(len(notes) - 1, max(0, idx + delta))
        note, name = notes[idx]
        if note == current:
            return
        self._swap_note(group, current, note)
        self.note_cache[group] = note
        logging.info(f"Maschine group {group}: sample {note} {name}")
        self._render_pads()
        self._preview(note)

    def _swap_note(self, group, old, new):
        """Move a group's steps onto a different drum note, keeping which
        steps are on. Rewriting from the euclid parameters instead would throw
        away any hand edits made with the pads."""

        self._select_pattern(group)
        steps = self.libseq.getSteps()
        # Keep each step's own velocity: rewriting them all at a fixed value
        # would silently flatten the accents a player tapped in, which is the
        # one thing pad velocity is for.
        on = []
        for step in range(steps):
            velocity = self.libseq.getNoteVelocity(step, old)
            if velocity:
                on.append((step, velocity))
        for step, _ in on:
            self.libseq.removeNote(step, old)
        for step, velocity in on:
            self.libseq.addNote(step, new, velocity, 1.0, 0.0)
        self.libseq.updateSequenceInfo()

    def _preview(self, note):
        """Audible feedback for a pad tap. The driver claims the port
        exclusively (unroute_from_chains), so pads reach no chain by
        themselves. playNote is what the touchscreen pattern editor uses for
        its own preview (zynthian_gui_patterneditor.py:308); it spawns the
        note-off itself after the duration. Signature: playNote(note,
        velocity, channel, duration_ms). Group N sits on MIDI channel N."""

        self.libseq.playNote(note, PREVIEW_VELOCITY, self.group, PREVIEW_MS)

    def _pad_note(self, channel, pad):
        """The note a pad plays on this channel.

        A drum channel is one sound: all sixteen pads trigger it, differing
        only in velocity and timing. Playing the kit's other notes here would
        mean hearing Clap while recording Kick, because a recorded hit stores
        the channel's own note - what you play would not be what you get."""

        if self.channel_kind(channel) != "voice":
            return self._group_note(channel)
        return tlib.pad_note(pad, self.globals["root"], self.globals["scale"],
                             self.state[channel]["octave"])

    def _play_clock(self, channel):
        """The sequence's play position in clocks, or None when stopped.

        None is not an error: it is the answer to "where would a strike land?"
        on a stopped sequence, and the recorder treats it as "capture
        nothing"."""

        if self._play_state(channel) == zynseq_lib.SEQ_STOPPED:
            return None
        pos = self.libseq.getPlayPosition(self.zynseq.bank, channel)
        return None if pos < 0 else pos

    def _pad_down(self, pad, velocity):
        """A pad struck outside STEP mode. Sounds immediately; the capture
        happens on release, when the hold length is known."""

        channel = self.group
        note = self._pad_note(channel, pad)
        midi_chan = tlib.CHANNELS[channel][5]
        # duration 0 means no auto note-off (zynseq.cpp:1742) - this note is
        # ours to end, unlike _preview's fire-and-forget audition.
        self.libseq.playNote(note, max(1, min(127, velocity)), midi_chan, 0)
        self.held[pad] = (note, midi_chan, channel, self._play_clock(channel),
                          velocity)

    def _pad_up(self, pad):
        """Release. Ends the note; the capture hangs off the same edge."""

        entry = self.held.pop(pad, None)
        if entry is None:
            return
        note, midi_chan, channel, start, velocity = entry
        # A NoteOn at velocity 0 is a note-off.
        self.libseq.playNote(note, 0, midi_chan, 0)
        if self.rec_down:
            self._capture(channel, note, velocity, start,
                          self._play_clock(channel))

    def _capture(self, channel, note, velocity, start, end):
        """Write a played note into the pattern, quantised to the nearest step
        with its held length.

        Captured on release rather than on press because the length is not
        known until then. Nothing is captured on a stopped sequence: with no
        playhead there is no step, and the display says REC-STOP so the player
        is not left guessing.

        Reached from _pad_up inside _midi_event, which already holds the lock."""

        if start is None:
            return
        cps = self.cps[channel]
        if cps <= 0:
            return
        self._select_pattern(channel)
        steps = self.libseq.getSteps()
        if steps <= 0:
            return
        step = tlib.record_step(start, cps, steps)
        length = steps * cps
        # Modulo handles a hold that crossed the loop point, where end < start.
        held = ((end - start) % length) if (end is not None and length) else cps
        duration = tlib.record_duration(held or cps, cps, step, steps)
        # Overdub replaces rather than stacks: a second strike on the same step
        # and note updates its velocity and length.
        if self.libseq.getNoteVelocity(step, note):
            self.libseq.removeNote(step, note)
        vel = max(1, min(127, velocity))
        self.libseq.addNote(step, note, vel, duration, 0.0)
        self.libseq.updateSequenceInfo()
        self.notes[channel][step] = (note, vel, duration)
        self._claim(channel)
        self._render_pads()

    def _claim(self, channel):
        """The first captured note makes the channel the player's.

        The owner flag is what enforces; forcing a voice to LOCK is what makes
        it visible on the surface."""

        if self.owner[channel] == "player":
            return
        self.owner[channel] = "player"
        if self.channel_kind(channel) == "voice":
            self.apply(channel, "random", 0)

    def _handback(self, channel):
        """Give a pattern back to its generator, which rewrites it from its own
        parameters. Destructive by design - the take is gone.

        Both routes land here: ERASE + Group, which is the deliberate "undo my
        take", and turning any knob that rewrites the pattern, which is the
        shipped law that enc 1-3 own the steps.

        Both writers clear() before rewriting, so no separate wipe is needed."""

        self._release_all()
        self.owner[channel] = "gen"
        self.notes[channel].clear()
        if self.channel_kind(channel) == "voice":
            self._write_voice_pattern(channel)
        else:
            self._write_pattern(channel)

    def _toggle_kind(self):
        """SHIFT + GRID: the selected channel changes what it behaves as.

        Switching back to the chain's own kind CLEARS the override rather than
        pinning it to the same value - otherwise one press would freeze a
        channel to a kind it merely happens to have today, and a later snapshot
        putting a different engine on that chain would be overruled by a stale
        choice nobody remembers making.

        The switch rewrites the pattern, so on a player-owned channel SP2's
        rule applies unchanged: hand back, and the take is gone. A second
        contradictory rule for the same situation would be worse than the
        loss."""

        channel = self.group
        old = self.channel_kind(channel)
        new = tlib.next_kind(old)

        self._release_all()
        if self.owner[channel] == "player":
            self._handback(channel)

        # Stash the set we are leaving, restore or build the one we arrive at.
        self.stash[channel][old] = self.state[channel]
        self.stash[channel][old + ":hits"] = self.hits[channel]
        self.stash[channel][old + ":rot"] = self.rot[channel]
        self.state[channel] = self.stash[channel].get(
            new, tlib.default_channel_state(new))
        self.hits[channel] = self.stash[channel].get(new + ":hits",
                                                     self.hits[channel])
        self.rot[channel] = self.stash[channel].get(new + ":rot",
                                                    self.rot[channel])

        # div and beats are pattern TIME, not kind: they mean the same to both
        # and moving them would make the groove jump on a switch.
        self.kind_override[channel] = (
            None if new == self._chain_kind(channel) else new)

        if new == "voice":
            self._write_voice_pattern(channel)
        else:
            self._write_pattern(channel)
        self._recentre_encoders()
        self._render_all()

    def _release_all(self):
        """End every held note, unconditionally.

        Called wherever the meaning of the pads changes underneath a finger:
        group change, mode change, transport stop, ownership change, end() and
        light_off(). A stuck pad drone is the silent channel's twin and it is
        louder.

        Capture is deliberately skipped here: a take is ended by letting go of
        the pad, not by the rig deciding to tidy up."""

        if not self.held:
            return
        for pad in list(self.held):
            note, midi_chan, _, _, _ = self.held.pop(pad)
            self.libseq.playNote(note, 0, midi_chan, 0)

    def _play_state(self, group):
        """Play state of a group's sequence. No argtypes are registered for
        getPlayState() in zynseq.py, so ctypes hands back a full int for a
        uint8_t return - mask it."""

        return self.libseq.getPlayState(self.zynseq.bank, group) & 0xFF

    def _any_playing(self):
        return any(self._play_state(g) != zynseq_lib.SEQ_STOPPED for g in range(8))

    def _toggle_transport(self):
        """Start or stop all 8 groups together. The target state is decided
        once from whether anything is currently running, then applied to every
        group, so the eight sequences can never drift into opposite states the
        way eight independent togglePlayState() calls would."""

        target = zynseq_lib.SEQ_STOPPED if self._any_playing() else zynseq_lib.SEQ_STARTING
        if target == zynseq_lib.SEQ_STARTING:
            self._force_loop_mode()
        else:
            # Stopping the rig must not leave a held pad droning over silence.
            self._release_all()
        for group in range(8):
            self.libseq.setPlayState(self.zynseq.bank, group, target)
        self._render_pads()
        self._render_transport()

    def _toggle_step(self, step, velocity=None):
        """A pad tap toggles a step. The tap's own velocity becomes the step's
        velocity, so a hard tap is an accent - free, because the hardware
        already reads it.

        The generator still owns the pattern: the next encoder turn rewrites
        it and wipes hand-edited steps. That is deliberate - no hidden
        per-step override state, and no third LED colour to explain."""

        self._select_pattern(self.group)
        steps = self.libseq.getSteps()
        if step >= steps:
            return
        note = self._step_note(self.group, step)
        if self.libseq.getNoteVelocity(step, note):
            self.libseq.removeNote(step, note)
        else:
            vel = velocity if velocity else int(self.state[self.group].get("velo", 110))
            if self.channel_kind(self.group) == "voice":
                # Match the generator (_write_pattern): a hand-tapped step must
                # obey GATE the same as a written one, or the two disagree by
                # up to 8x at long gates. Drums keep a fixed one-shot duration -
                # their gate is not a meaningful parameter.
                duration = tlib.note_duration(self.state[self.group]["gate"], step, steps)
            else:
                duration = 1.0
            self.libseq.addNote(step, note, max(1, min(127, vel)), duration, 0.0)
        self.libseq.updateSequenceInfo()
        self._preview(note)
        self._render_pads()

    def _erase_step(self, step):
        """ERASE + pad. Removes that step's note if it has one; a pad that is
        already empty is left alone rather than toggled on."""

        self._select_pattern(self.group)
        if step >= self.libseq.getSteps():
            return
        note = self._step_note(self.group, step)
        if self.libseq.getNoteVelocity(step, note):
            self.libseq.removeNote(step, note)
            self.libseq.updateSequenceInfo()
            self._render_pads()

    def _voice_notes(self, channel, steps):
        """The notes a voice-behaving channel's line uses.

        On a synth this is the scale-quantised Turing line as always. On a
        SAMPLER chain the register walks the kit's own note list instead,
        because a note number there selects which drum sounds, not a pitch -
        quantising to a scale would land most steps on empty keys, and an
        empty key is silence with nothing to explain it.

        The single place both the writer and the pad renderer ask, so they can
        never disagree about what is on a step."""

        st = self.state[channel]
        if self._is_sampler(channel):
            kit = [num for num, _ in self._keymap(channel)]
            notes = tlib.kit_line(st["register"], st["length"], steps, kit)
            # An unreadable or empty kit degrades to the channel's own drum,
            # never to silence.
            return notes or [self._group_note(channel)] * steps
        return tlib.line(st["register"], st["length"], steps,
                         self.globals["root"], self.globals["scale"],
                         st["octave"], st["range"])

    def _step_notes(self, channel, steps):
        """The note each step carries, as a list. Computed once per repaint:
        deriving it per pad meant recomputing the whole line sixteen times,
        five times a second, for one answer."""

        if self.channel_kind(channel) != "voice":
            return [self._group_note(channel)] * steps
        notes = self._voice_notes(channel, max(1, steps))
        return [notes[i % len(notes)] for i in range(steps)] if notes \
            else [self._group_note(channel)] * steps

    def _step_note(self, channel, step):
        """Which note a step carries on this channel.

        A drum channel plays one note, discovered from its kit. A voice plays
        whatever the Turing register put on that step, so the pitch has to be
        derived the same way the writer derived it - otherwise the pads would
        query a note that is not there and every step would read as empty."""

        if self.channel_kind(channel) != "voice":
            return self._group_note(channel)
        steps = lib.step_count(self.div[channel])
        if steps <= 0:
            return self._group_note(channel)
        notes = self._voice_notes(channel, steps)
        return notes[step % len(notes)] if notes else self._group_note(channel)

    def _note_duration(self, step, note):
        """A stored note's length, if the installed libzynseq can tell us.

        Measured present at gate G5 (`_ZN7Pattern15getNoteDurationEjh`). The
        guard stays as cheap insurance: the Pi's build is older than this
        checkout and has already been caught missing getNoteAtIndex(), and the
        failure mode of assuming is a driver that will not load at all."""

        getter = getattr(self.libseq, "getNoteDuration", None)
        if getter is None:
            return 1.0
        try:
            return float(getter(step, note))
        except Exception:
            return 1.0

    def _rebuild_notes(self, channel):
        """Reconstruct which steps a human played, by reading the pattern.

        The map is a cache, never the truth. The notes live in the pattern and
        therefore in the .zss, and this is the CHANCE/SWING lesson applied
        before it bites: any mirrored zynseq state is read back on load, never
        assumed.

        Cheap because the candidate set is small - one note on a drum, the
        keyboard plus the generated line on a voice. Not 128 per step.

        Known and accepted limit: a played note that lands on the same step
        with the same pitch the generator would have written there is
        indistinguishable, and shows in the group colour rather than amber."""

        kind = self.channel_kind(channel)
        with self.lock:
            self._select_pattern(channel)
            steps = self.libseq.getSteps()
            if steps <= 0:
                self.notes[channel] = {}
                return
            generated = self._step_notes(channel, steps)
            if kind == "voice":
                cands = tlib.candidate_notes(
                    kind, self._group_note(channel),
                    pads=tlib.pad_notes(self.globals["root"],
                                        self.globals["scale"],
                                        self.state[channel]["octave"]),
                    line=generated)
            else:
                cands = tlib.candidate_notes(kind, self._group_note(channel))
            out = {}
            for step in range(steps):
                for note in cands:
                    if note == generated[step]:
                        continue
                    vel = self.libseq.getNoteVelocity(step, note)
                    if vel:
                        out[step] = (note, vel, self._note_duration(step, note))
                        break
            self.notes[channel] = out

    def _group_note(self, group):
        """The single note a group's pattern uses, cached per group so LED
        rendering doesn't rescan the pattern on every call. The installed
        libzynseq has no getNoteAtIndex() (only in a newer header than what's
        built on the Pi - confirmed via `nm -D` against the installed .so),
        so discovery works only with symbols that exist: getRefNote() and
        getNoteVelocity()."""

        note = self.note_cache[group]
        if note is None:
            note = self._discover_group_note(group)
            self.note_cache[group] = note
        return note

    def _discover_group_note(self, group):
        """Find a group's drum note without getNoteAtIndex(): try the
        pattern's ref note first, then scan step 0, then every step, then
        fall back to the prepared snapshot's known mapping."""

        self._select_pattern(group)

        ref_note = self.libseq.getRefNote()
        if self.libseq.getNoteVelocity(0, ref_note):
            return ref_note

        for note in range(128):
            if self.libseq.getNoteVelocity(0, note):
                return note

        steps = self.libseq.getSteps()
        for step in range(steps):
            for note in range(128):
                if self.libseq.getNoteVelocity(step, note):
                    return note

        return FALLBACK_NOTES[group]

    def _playhead(self):
        """Current step of the selected group's pattern, or None when
        stopped. getPatternPlayhead() is unreliable from a ctrldev driver
        (see the note at zynthian_ctrldev_akai_apc_key25_mk2.py:2182 - "NOTE:
        libseq.getPatternPlayhead() does not work here!"), so derive it from
        clocks instead. Installed signature: getPlayPosition(bank, sequence).

        Clocks per step comes from the self.cps cache rather than
        getClocksPerStep(), which would need a selectPattern() first - see
        the cache's comment in __init__ for why this path must not touch the
        global pattern selection.

        The play-state check is load-bearing, not defensive: a stopped
        sequence reports play position 0, which painted step 0 white at full
        brightness forever. That both stuck a white pad on screen after Stop
        and made step 0 look like it ignored being deselected - the snapshot
        puts every group's note on step 0, so it was the first pad anyone
        tried to switch off."""

        group = self.group
        if self._play_state(group) == zynseq_lib.SEQ_STOPPED:
            return None
        cps = self.cps[group]
        if cps <= 0:
            return None
        playpos = self.libseq.getPlayPosition(self.zynseq.bank, group)
        if playpos < 0:
            return None
        return playpos // cps

    def _voice_wraps(self):
        """Detect a playhead wrap on each voice, independently of which
        channel is selected - all three voices mutate whether or not anyone is
        looking at them.

        Uses the raw play position rather than a step number: the step is
        quantised by clocks-per-step and can repeat across a poll, while the
        position only ever runs forward until it wraps. Reads only, and the
        rewrite it triggers takes the lock itself."""

        for channel, ch in enumerate(tlib.CHANNELS):
            voice = self.channel_kind(channel) == "voice"
            with self.lock:
                if self._play_state(channel) == zynseq_lib.SEQ_STOPPED:
                    self._voice_pos[channel] = None
                    # Stopped: a pending structure change has no bar to wait
                    # for, so take it now rather than leaving it in brackets.
                    if self.state[channel]["pending"]:
                        pending = set(self.state[channel]["pending"])
                        self.state[channel]["pending"].clear()
                        if not voice:
                            if "div" in pending:
                                self._write_pattern(channel)
                            else:
                                self._set_length(channel, self.beats[channel])
                    continue
                position = self.libseq.getPlayPosition(self.zynseq.bank, channel)
            previous = self._voice_pos.get(channel)
            self._voice_pos[channel] = position
            wrapped = previous is not None and position < previous

            if wrapped and self.state[channel]["pending"]:
                pending = set(self.state[channel]["pending"])
                self.state[channel]["pending"].clear()
                with self.lock:
                    if voice:
                        self._write_voice_pattern(channel)
                    elif "div" in pending:
                        # A division change rescales note positions, so the
                        # pattern has to be regenerated from euclid.
                        self._write_pattern(channel)
                    else:
                        # Length alone keeps the steps that fit: shortening a
                        # pattern to hear a polyrhythm must not throw away the
                        # beat that is playing.
                        self._set_length(channel, self.beats[channel])

            if not voice:
                continue
            if wrapped:
                if channel in self._key_dirty:
                    # A key change lands on the bar, and it must be heard even
                    # on a voice that is locked - the line keeps its shape and
                    # changes key, which is the point of a global root.
                    self._key_dirty.discard(channel)
                    self._write_voice_pattern(channel)
                    if not self._key_dirty:
                        self.globals["pending"].clear()
                self._rewrite_voice(channel)

    def _playhead_loop(self):
        """Repaint just the two pads the playhead moves between. A full
        _render_pads() at this rate would mean 16 getNoteVelocity() calls
        every 33ms for no gain - the only thing changing is which pad is
        white.

        Also re-reads the group volumes at a slower rate, so the group button
        brightness follows the touchscreen faders as well as encoder 8."""

        tick = 0
        while not self.stopping.wait(PLAYHEAD_POLL_S):
            try:
                tick += 1
                # Outside the lock on purpose: loading a kit talks to
                # LinuxSampler over a socket and can block.
                self._commit_kit()
                self._commit_preset()
                # Drain queued note-map rebuilds here, never on the MIDI
                # thread: the scan takes the lock for a whole pattern.
                while self._rebuild_due:
                    self._rebuild_notes(self._rebuild_due.pop())
                self._voice_wraps()
                if tick % VOLUME_POLL_TICKS == 0:
                    # Tempo can move from the touchscreen or from a snapshot,
                    # and the delay's musical division has to follow it.
                    self._push_delay_time()
                with self.lock:
                    head = self._playhead()
                    if head != self.head_shown:
                        self._move_playhead(head)
                    if tick % VOLUME_POLL_TICKS == 0:
                        self._render_groups()
                        # Volume, pan and the mutes can all move on the
                        # touchscreen with nothing signalling it, so the
                        # screens are polled on the same tick.
                        self._render_display()
            except Exception as e:
                logging.error(f"Maschine playhead poll failed: {e}")
                return

    def _move_playhead(self, head):
        group_color = GROUP_COLORS[self.group]
        old = self.head_shown
        self.head_shown = head
        if old is not None and 0 <= old < 16:
            self._paint_pad(old, self._step_state(old, group_color))
        if head is not None and 0 <= head < 16:
            self._paint_pad(head, (COLOR_PLAYHEAD, BRIGHT_PLAYHEAD))

    def _step_state(self, step, group_color):
        """LED state a step shows when the playhead is not on it.

        A played-in step is amber. This overrides _toggle_step's standing "no
        third LED colour to explain" comment, which predates per-step override
        state that now survives a snapshot: the handback is destructive, so a
        player-owned channel that looks like a generated one invites nudging
        HITS and silently eats the take."""

        if self.step_on[step] is None:          # beyond the pattern's length
            return (group_color, 0.0)
        if not self.step_on[step]:
            return (group_color, BRIGHT_STEP_OFF)
        if step in self.notes[self.group]:
            return (COLOR_PLAYER, BRIGHT_STEP_ON)
        return (group_color, BRIGHT_STEP_ON)

    def _paint_pad(self, step, state):
        # See PAD_OFFSETS above: the pad that displays a step is not the
        # step's own index, it's PAD_OFFSETS[step].
        pad = PAD_OFFSETS[step]
        if self.leds.changed(f"pad{pad}", state):
            self._send_osc(lib.pad_osc(pad, state[0], state[1]))

    # --- LEDs ----------------------------------------------------------

    def _render_pads(self):
        """Full repaint. Also refreshes the two caches the playhead poll
        reads - step_on and cps - so that poll never has to touch the
        pattern selection."""

        self._select_pattern(self.group)
        steps = self.libseq.getSteps()
        color = GROUP_COLORS[self.group]
        self.cps[self.group] = self.libseq.getClocksPerStep()
        # None means "past the end of the pattern", which is not the same as
        # an empty step: it is unlit rather than dim.
        notes = self._step_notes(self.group, 16)
        self.step_on = [
            bool(self.libseq.getNoteVelocity(step, notes[step])) if step < steps else None
            for step in range(16)]
        head = self._playhead()
        self.head_shown = head
        for step in range(16):
            if step == head:
                state = (COLOR_PLAYHEAD, BRIGHT_PLAYHEAD)
            else:
                state = self._step_state(step, color)
            self._paint_pad(step, state)
        # Every path that changes a pattern parameter or the selected group
        # ends here, so this is where the screens follow the encoders without
        # each handler having to remember to repaint them.
        self._render_display()

    def _render_groups(self):
        for group in range(8):
            # Rounded so tiny zctrl wobbles don't push a fresh OSC write past
            # the LED cache on every render.
            bright = round(self._group_brightness(group), 2)
            state = (GROUP_COLORS[group], bright)
            key = f"group{group}"
            if self.leds.changed(key, state):
                self._send_osc(lib.button_osc(
                    f"group_{chr(ord('a') + group)}", state[0], state[1]))

    def _render_transport(self):
        bright = BRIGHT_PLAY_ON if self._any_playing() else BRIGHT_PLAY_OFF
        state = (COLOR_PLAY, bright)
        if self.leds.changed("play", state):
            self._send_osc(lib.button_osc("play", state[0], state[1]))
        self._render_modes()

    def _render_modes(self):
        """Exactly one mode LED lit, always. Derived from self.mode on the
        render tick and never written at the point of the press, so the LED and
        the screens cannot disagree about which mode is showing.

        The daemon accepts a button LED name over OSC whether or not it emits
        that button's CC, so volume and auto light without the daemon patch."""

        for mode, led in MODE_LED_NAMES.items():
            bright = BRIGHT_PAGE_ON if mode == self.mode else BRIGHT_PAGE_OFF
            state = (COLOR_PAGE, bright)
            # The cache key changed from page_ to mode_ deliberately: a stale
            # page_control entry would suppress the first repaint.
            if self.leds.changed(f"mode_{led}", state):
                self._send_osc(lib.button_osc(led, state[0], state[1]))

    def _render_mutes(self):
        """F1-F8 light what they did: lit = muted, or lit = soloed while the
        F row means solo. SOLO itself is lit only while its mode is latched,
        so the row's meaning is always readable from the panel."""

        mixer = self.state_manager.zynmixer
        soloing = self.solo_down or self.solo_mode
        for group in range(8):
            chan = self._mixer_chan(group)
            if chan is None:
                on = False
            elif soloing:
                on = bool(mixer.get_solo(chan))
            else:
                on = bool(mixer.get_mute(chan))
            state = (0xFFFFFF, 1.0 if on else 0.0)
            if self.leds.changed(f"mute{group}", state):
                self._send_osc(lib.button_osc(F_BUTTON_NAMES[group], state[0], state[1]))
        solo_state = (0xFFFFFF, 1.0 if self.solo_mode else 0.0)
        if self.leds.changed("solo", solo_state):
            self._send_osc(lib.button_osc("solo", solo_state[0], solo_state[1]))

    # --- screens -------------------------------------------------------
    #
    # The two screens show what the LEDs cannot: which sample each group
    # plays, and what the endless encoders are actually set to. Left screen =
    # groups A-D and the pattern encoders, right = E-H and the sound
    # encoders, matching the four buttons above and four encoders below each
    # panel. Geometry and layout live in the lib; this only supplies values.

    def _sample_name(self, group):
        """The drum note's name from the chain's keymap, for the group tab."""

        note = self._group_note(group)
        for num, name in self._keymap(group):
            if num == note:
                return name.upper()
        return str(note)

    def _tabs(self, screen):
        """Tab row. A dashed tab means "this channel is not sounding" - and
        that has to include a channel silenced by its generator, not just one
        muted at the mixer.

        A voice whose play chance is 0 emits nothing at all, and the voice STEP
        page has no CHANCE column to show it. That combination cost a jam:
        the channel looked broken, the engine was healthy, and nothing on the
        surface said why. Silence with no explanation is the one thing this
        instrument must never do."""

        out = []
        for group in range(screen * 4, screen * 4 + 4):
            chan = self._mixer_chan(group)
            silent = chan is not None and bool(self.state_manager.zynmixer.get_mute(chan))
            if not silent:
                st = self.state[group]
                if self.channel_kind(group) == "voice":
                    # Density 0 writes no notes at all, which is the same
                    # unexplained silence chance 0 produced by another route.
                    silent = (st.get("chance", 100) == 0
                              or st.get("density", 100) == 0)
                else:
                    silent = self.hits[group] == 0
            out.append((chr(ord("A") + group), tlib.CHANNELS[group][1],
                        group == self.group, silent))
        return tuple(out)

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
        for offset, col in enumerate(cols[screen * 4:screen * 4 + 4]):
            bar = BAR_KINDS[col["bar"]]
            frac = col["frac"]
            if bar == "s":
                index, count = frac
                frac = (index / (count - 1)) if count > 1 else 0.0
            if meter_page:
                level = self._meter_frac(screen * 4 + offset)
                if level is not None:
                    frac = level
            out.append((col["name"], col["value"], bar, round(float(frac), 3)))
        return tuple(out)

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

    # Peak metering. Two mixer APIs exist and the Pi runs the older one -
    # measured 2026-08-11, G4 step 4:
    #   new (this checkout): update_dpm_states() fills mixer.dpm, a DPM array of
    #                        (a, b, a_hold, b_hold, mono); enable_dpm(enable)
    #   old (on the Pi):     get_dpm_states(start, end) -> [[a, b, ha, hb, mono]]
    #                        per channel; enable_dpm(start, end, enable)
    # Both report dBFS (mixer.c convertToDBFS). Neither present means the bar
    # keeps showing fader position, which is what it showed before this feature.
    METER_PIXELS = lib.SCREEN_COL - 12      # the bar's inner width in pixels
    METER_FLOOR = 40.0                      # dB below 0 that fills the bar

    def _meter_frac(self, channel):
        """This channel's peak level as a 0-1 fraction, quantised to the bar's
        real pixel resolution so a steady signal stops repainting."""

        mixer = self.state_manager.zynmixer
        chan = self._mixer_chan(channel)
        if chan is None:
            return None
        try:
            if hasattr(mixer, "update_dpm_states"):
                mixer.update_dpm_states()
                # The bar is one column per channel, so it shows the louder side.
                dpm = mixer.dpm[chan]
                level = max(float(dpm.a), float(dpm.b))
            elif hasattr(mixer, "get_dpm_states"):
                state = mixer.get_dpm_states(chan, chan)[0]
                level = max(float(state[0]), float(state[1]))
            else:
                return None
            frac = (level + self.METER_FLOOR) / self.METER_FLOOR
        except Exception:
            return None
        return tlib.quantise_frac(frac, self.METER_PIXELS)

    def _render_display(self):
        """Repaint both screens, but only put a screen on the wire when its
        contents actually changed - this runs at the same rate as the pad
        repaint, and a full screen is ~50 OSC packets."""

        desc = self._page()
        ring = self._ring()
        key = tlib.ring_key(self.mode, self.channel_kind(self.group))
        label = tlib.page_label(desc["title"], self.page_idx.get(key, 0), len(ring))
        # The page indicator also carries who owns the channel and whether a
        # take is being captured. The tab row is left alone: dashed there means
        # "this channel is not sounding", and that meaning is not diluted.
        label = tlib.owner_label(
            label, self.owner[self.group], self.rec_down,
            self._play_state(self.group) != zynseq_lib.SEQ_STOPPED)
        label = tlib.type_label(label, self.kind_override[self.group])
        for screen in (0, 1):
            # The label joins the cached tuple deliberately: paging with no
            # other change must still repaint.
            state = (self._tabs(screen), self._columns(screen), label)
            if not self.leds.changed(f"disp{screen}", state):
                continue
            for packet in lib.screen_packets(screen, state[0], state[1], state[2]):
                self._send_osc(packet)

    def _render_all(self):
        self._render_groups()
        self._render_transport()
        self._render_mutes()
        self._render_pads()

    def _on_progress(self, *args, **kwargs):
        """zynsigman callback for SS_SEQ_PROGRESS and SS_SEQ_PLAY_STATE -
        called with each signal's own arguments, which neither the playhead
        nor the transport LED needs."""

        with self.lock:
            self._render_pads()
            self._render_transport()

    def _on_snapshot(self, *args, **kwargs):
        """A restored snapshot brings its own patterns, chains and mixer
        state. Every cached value the driver holds - group notes, keymaps,
        lengths, hit counts - describes the old one, so re-read all of it and
        repaint. Without this the F1-F8 mute LEDs kept showing the mutes from
        before the load, while the mixer had already moved on."""

        self._invalidate_gen_cache()
        with self.lock:
            self._resync_all()
            self._render_all()
        # The restored patterns may hold played-in notes. Queue the rebuild
        # rather than run it here: the scan takes the lock, and this handler
        # runs on the signal thread.
        self._rebuild_due.update(range(len(tlib.CHANNELS)))
        self._force_swing_div()
        # A restore rebuilds the chains, so the zmop channel translation the
        # voices need is gone with them. Outside the lock: it touches zyncore
        # and the chain manager, never libzynseq.

    def _resync_all(self):
        """Drop every cache and read the encoder state back from zynseq."""

        self.note_cache = [None] * 8
        self.keymap_cache = [None] * 8
        self._reset_kit_cache()
        # The LED cache suppresses writes whose value has not changed. After a
        # snapshot load its idea of "unchanged" is about the previous state,
        # so it has to be emptied or the repaint below is a no-op.
        self.leds.clear()
        for group in range(8):
            self._derive_params(group)

    def _reset_kit_cache(self):
        """Drop everything _kit_list()/_apply_kit() cached. Used wherever the
        chains underneath the driver may have changed: a restored snapshot,
        or a chain added/removed/moved (refresh() below).

        kit_index resets to 0 as well, not just kits/kit_cache. A restored
        snapshot's chains carry whatever preset THEY were saved with, chosen
        outside this driver - the old kit_index described a position in the
        OLD self.kits list, against the OLD chain, and has no reason to still
        name the right entry in a freshly rebuilt list. _kit_list() only
        reads the SELECTED group's bank (see its docstring), so there is no
        cheap, reliable way to reverse-match every group's actual preset back
        to an index here. Landing on 0 is a deliberate, visible default
        rather than a stale value that happens to look plausible - and it is
        now safe to land on precisely because every reader of kit_index
        (_load_keymap, _columns, _nudge_kit) goes through
        _current_kit_index() first, which re-derives the real index from the
        processor's own loaded preset name and only falls back to this 0 when
        that name matches nothing in `kits` (a chain that has never had a kit
        from this bank applied).

        That resolver did not always sit in front of _load_keymap: it used to
        read self.kit_index[group] directly, so this reset gave every group
        kit 0's note list until encoder 6/7 happened to touch it - wrong tab
        and SMPL names, and worse, encoder 6 (_cycle_sample) would then move
        that group's pattern onto a note that plain does not exist in its
        real kit (e.g. Akai XE8's 77-96 range vs. kit 0's), taking the group
        silent rather than just mislabelled. With _load_keymap routed through
        _current_kit_index(), this reset no longer affects which preset is
        actually loaded, which notes a group's keymap resolves to, or which
        note a pad plays - the last of those is note_cache/_group_note,
        reset separately above."""

        self.kit_index = [0] * 8
        self.kits = None
        self.kit_cache = {}
        self.kit_pending = None
        self._kit_warned = None
        self._empty_keymap_warned = set()

    def refresh(self):
        super().refresh()
        with self.lock:
            self.note_cache = [None] * 8
            self.keymap_cache = [None] * 8
            self._reset_kit_cache()
            self._render_all()
