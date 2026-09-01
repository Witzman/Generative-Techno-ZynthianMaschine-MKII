#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Controller driver for Maschine MK2 via the MaschineMK2_linux daemon.
#
# 8 groups x 16 steps: five euclidean drum channels and three Turing-machine
# voices, all eight always alive. All sequencing lives in zynseq, so patterns
# persist in snapshots and the touchscreen pattern editor mirrors them.
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
#   DL / DR   CC 47/48 - the arrows beside the display: page back / forward
#             within the current mode's ring
#   ML / MR   CC 13/14 - previous / next sound: a sample within the kit on a
#             drum, an engine preset on a voice
#   F1-F8     CC 39-46 (mute, or solo while SOLO is held or latched)
#   SHIFT 49 - MOD 50 (SWING, latches; see the modulation section below)
#   Solo 31 - Duplicate 29 - Play 1 - Erase 2 (hold only) - Restart 7
#
# THE CC NUMBERS ABOVE ARE MEASURED, gate G4 2026-08-11 with aseqdump, and the
# daemon's token names are attached to the OPPOSITE physical buttons from what
# they suggest. Do not "correct" DL/DR to 5/6 from the token names - that was
# the wrong belief this header carried until 2026-08-16, while the constants
# below had been right since G4.
#
# Emitted, measured and deliberately unbound: CC 5/6 (TL/TR - the transport
# STEP pair) and CC 12 (big encoder press) / CC 15 (big encoder turn, 8 units
# per detent, wraps 120 -> 0). Free surface for the next feature.
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

import ctypes
import logging
import os
import random
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

# The play-session event log. A file, NOT the journal: roughly six log lines a
# second through journald was enough to make the daemon's reader run late and
# wedge the controller off the USB bus on 2026-08-20 - debugging load is load.
# A line appended to tmpfs is a fraction of that, and every call site is EVENT
# driven, so a busy bar costs a handful of lines and a quiet one costs none.
#
# OFF BY DEFAULT, and it stays off. It earned its place on 2026-08-21 - a
# session nobody could diagnose became four measured checks - but a log that
# writes by default is a cost every player pays for a problem they do not have.
#
# TURNED ON FROM THE ENVIRONMENT since 2026-08-31, not by editing this line.
# Editing it on the rig left the deployed file one line different from every
# commit, and finding that out cost a checksum hunt against five commits the
# same day. A drop-in leaves the source byte-identical to what was shipped:
#
#   systemctl edit zynthian
#   [Service]
#   Environment=MASCHINE_SESSION_LOG=/tmp/maschine-session.log
#
# /tmp is a 100 M tmpfs, which is the intent - a line appended to tmpfs, never
# the journal. Relative paths, directories and the journal's own device
# aliases are refused rather than resolved; tlib.session_log_path says why.
SESSION_LOG_PATH = tlib.session_log_path(os.environ)

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

# How much of the measured phase error the phrase clock takes back each bar.
# A FRACTION, not the whole error: this clock is also the countdown a player is
# reading, and a count that jumps is worse than one that is slightly late.
# Measured drift is ~1.5 clocks a bar, so a quarter converges within a few bars
# and still moves far faster than the drift it is chasing.
PHRASE_REANCHOR_GAIN = 0.25
# The most the anchor may move in one bar, in beats. A guard rather than a
# tuning knob: it bounds what a misread position can do to a running countdown,
# and it sits far above anything the real drift needs.
PHRASE_REANCHOR_MAX_BEATS = 0.25
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
CC_BIG_TURN = 15         # big encoder turn: the page ring, owner 2026-08-19
# "Free" means MEASURED AND UNCLAIMED, and the two halves are not the same
# claim. A CC nobody has captured is UNKNOWN, not free - TEMPO sat outside the
# G4 capture for months because nobody pressed it that day. The authority is
# lib.CCS_MEASURED / lib.CCS_KNOWN / lib.CCS_MEASURED_AND_UNCLAIMED, which a
# test checks against every binding; do not maintain a second list here.
CC_BIG_PRESS = 12        # measured at G4, unclaimed
CC_TL = 5                # measured at G4, unclaimed
CC_TR = 6                # measured at G4 and BOUND since 2026-08-20 - beat
                         # repeat. Was still called "free" here and in the
                         # audit until 2026-08-21.

# Mode buttons, all measured at G4 alongside the arrows. Unlike the arrows,
# every one of these matched what the daemon's source said.
CC_SOLO = 31             # measured
CC_ARM = 30              # SELECT. Measured at G4; LED index 22, measured.
CC_NAVIGATE = 34         # NAVIGATE. Measured at G4; LED index 20, measured.
CC_FREEZE = 27           # PAD MODE. Measured at G4; LED index 19, measured.
LED_ARM = "select"       # the daemon's own name for index 22, corrected in
                         # c141d70 - light a button by ITS OWN name now.
# PAD MODE, index 19. THE NAME IS "pad_mode" WITH THE UNDERSCORE, and it
# was "padmode" from the day FREEZE shipped until 2026-09-01. The daemon's
# osc_button_to_btn_map (main.rs:444) accepts "pad_mode" alone, returns None
# for anything else and drops the message at main.rs:739 - so the FREEZE
# indicator had NEVER lit, silently, while docs/the-surface.html told the
# reader a frozen instrument says so three times. It said so twice.
# A name is not a measurement: grep the daemon's own map before writing one.
LED_FREEZE = "pad_mode"  # index 19

# REC's LED, one row per state tlib.rec_led_state can return. RED means a file
# is being written and nothing else on this panel is red for any other reason -
# the player should never have to work out whether they are recording.
REC_LED_COLOURS = {
    "off": 0xFFFFFF,
    "ready": 0xFFFFFF,
    "overdub": 0xFFFFFF,
    "recording": 0xFF2000,
    "both": 0xFF2000,
}
# CORRECTED 2026-09-01. `both` asked for 2.0 and set_button_light CLAMPS AT
# 1.0 (daemon mikro.rs:960), so "capture running AND overdub held" has always
# looked exactly like "capture running" - a distinction that existed in this
# table and nowhere on the hardware.
#
# The colour already carries the fact that matters. RED means a file is being
# written, and nothing else on this panel is red for any other reason; the
# overdub on top of it is the lesser fact and does not need a level the panel
# cannot draw. The values are the light alphabet's own: dim available, bright
# acting.
REC_LED_BRIGHT = {
    "off": tlib.LIGHT_OFF,
    "ready": tlib.LIGHT_DIM,
    "overdub": tlib.LIGHT_ON,
    "recording": tlib.LIGHT_ON,
    "both": tlib.LIGHT_ON,
}
CC_DUPLICATE = 29        # measured
CC_MODE_CONTROL = 11
CC_MODE_STEP = 32
CC_MODE_ALL = 38
CC_MODE_MIXER = 51       # VOLUME - the pass-two daemon patch, measured live
CC_MODE_FILTER = 37      # AUTO
# Measured at G4. This block is HISTORY, not the current free list - GRID,
# SCENE, PATTERN, PAD MODE, NAVIGATE and MUTE have all been spent since it was
# written. The live answer is lib.CCS_MEASURED_AND_UNCLAIMED, which is 5, 12
# and 29 and is enforced by a test:
#   GRID 4 · SCENE 25 · PATTERN 26 · PAD MODE 27 · NAVIGATE 34 · MUTE 33
#   big encoder: turn CC 15 (8 units per detent, wraps 120 -> 0), press CC 12
# TEMPO is CC 35, measured 2026-08-16 and NOT part of G4 - it was never
# pressed that day, so it was unknown rather than free. It carries COARSE:
# every encoder is half as sensitive as it was, and TEMPO held gives the
# old feel back. See lib.STEP_FACTOR for why two and not ten.
# The big encoder's CC 15 is emitted from the daemon's "A8" branch
# (main.rs:911) as a 16-position counter times 8, so it never passes
# send_encoder_cc and never meets is_encoder_jump. An exact signed delta is
# ((new - old + 64) % 128) - 64; no threshold is involved. Nothing binds it.
# There is no VIEW button on the MK2 panel. The daemon defines a "view" token,
# but the 8-button block is scene, pattern, pad mode, navigate, duplicate,
# select, solo, mute - confirmed against the hardware by the owner.
# FOUR MODES, 2026-09-01. ALL left this table for tlib.BUTTONS_STATEFUL: it
# is the LENS now - held or latched, the eight encoders spread one verb across
# all eight channels - and MIXER and FILTER went with it, because their five
# pages were exactly that and nothing else.
#
# AUTO carries the generator. The button is printed for automation and that is
# what the page is: which generator draws, how fast it evolves, how far it may
# stray, how often it may act at all, and how the phrase is built.
MODE_BUTTONS = {
    CC_MODE_CONTROL: "CONTROL",
    CC_MODE_STEP: "STEP",
    CC_MODE_FILTER: "AUTO",       # the AUTO button, CC 37
    CC_MODE_MIXER: "VOLUME",      # the VOLUME button, CC 51
}
MODE_LED_NAMES = {"CONTROL": "control", "STEP": "step",
                  "AUTO": "auto", "VOLUME": "volume"}
# The lens's own light, on the button it lives on. Not in MODE_LED_NAMES: a
# mode LED is one-of-four and exclusive, and this one is neither.
LED_LENS = "all"
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

# How often the animated MOD legend repaints, in poll ticks. 3 gives ~10 Hz.
#
# NOT a style choice and not a performance tweak: at every tick this overlay
# writes all sixteen pads, and 480 HID writes a second on the fd the input
# arrives on starves the daemon's reader and wedges the controller until it is
# physically unplugged. Measured on the rig 2026-08-20, three times.
MOD_LEGEND_TICKS = 3

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
# How many poll ticks between two unprompted note-base assertions - about a
# second. See the poll loop: this is the backstop for a base the driver never
# learned it had lost.
NOTE_BASE_HEARTBEAT_TICKS = 30
# A pad LED write that the daemon never applied used to stay wrong forever:
# the cache had recorded it as sent, so nothing resent it. Measured on the rig
# 2026-08-22 - a pad reading dark for minutes while the driver's own picture
# said lit. Two halves fix it: the cache lets a pad's value go out again once
# this many seconds have passed, and the poll thread repaints the grid on the
# tick count below so there is something to carry it.
#
# Worst case is sixteen writes in one tick every three seconds - about five a
# second averaged, and the same size burst an ordinary pad tap already causes
# through _render_pads. That is three orders below the ~480/s that wedged the
# controller off the USB bus on 2026-08-20; what killed it was a SUSTAINED
# 30 Hz full-grid repaint, not a burst.
PAD_LED_REFRESH_S = 3.0
PAD_RESYNC_TICKS = 90

# The node udev recreates on every plug. It is the only thing the driver can
# see that moves when the controller is replaced: the udev rule restarts the
# DAEMON on plug and deliberately leaves the UI alone, so nothing signals the
# driver that the surface it painted has been wiped. Stat'ed on the same
# once-a-second tick as the note-base heartbeat - see _check_device().
DEVICE_NODE = "/dev/maschine"
DEVICE_POLL_TICKS = 30

# The same thread re-reads the group volumes every Nth tick, because nothing
# signals a zctrl change: zynthian_controller emits no zynsigman signal, so a
# volume moved on the touchscreen is invisible until something asks. Only the
# led_cache diff reaches the wire, so a quiet poll costs nothing.
VOLUME_POLL_TICKS = 6          # every ~200ms
POLL_ERROR_S = 30.0            # between repeats of one poll error

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
        # The bank this driver addresses, held rather than followed. Pinned in
        # init() once zynseq is up, re-pinned by a snapshot, and checked once a
        # second against what zynseq actually has. See tlib.BankPin.
        self.bankpin = tlib.BankPin()
        self.group = 0                       # selected group, 0 = A
        self.note_cache = [None] * 8         # per-group drum note, discovered lazily
        self.hits = [0] * 8                  # euclid hit count per group
        self.div = [DEFAULT_DIV] * 8         # index into lib.DIVISIONS
        self.rot = [0] * 8                   # euclid rotation per group
        self.beats = [lib.DIVISIONS[DEFAULT_DIV][2]] * 8   # pattern length
        self.keymap_cache = [None] * 8       # per-group [(note, name)], lazy
        self.kit_index = [0] * 8             # which kit each group uses
        # PAD PRESSURE. `_press_raw` is the last aftertouch value the MIDI
        # thread saw, `_press_off` the offset the poll thread is applying, and
        # `_press_base` the value the knob was on when the squeeze started -
        # None when nothing is owed. The base is held HERE and never read back
        # from the engine: that is the same law the LFO obeys, and reading it
        # back mid-squeeze would write the swept value into the snapshot.
        self._press_raw = [0] * 8
        self._press_off = [0.0] * 8
        self._press_base = [None] * 8
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
        # Identity of the device node, so a replug can be noticed. Seeded here
        # rather than left None: the surface is painted at startup anyway, and
        # an unseeded token makes the first poll tick claim a reconnect and
        # repaint it a second time for nothing.
        self.device_token = self._device_token()
        # Per encoder: the last position the daemon reported, and movement
        # not yet worth a whole parameter step. See _enc_steps.
        self.enc_last = {}
        self.enc_carry = {}
        self.osc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.stopping = Event()
        self._log_seen = {}
        # Rate limiting for every error logged on the poll thread. Nothing
        # there dies on a raised exception any more, so a persistent fault
        # would otherwise write 30 journal lines a second. Keyed, so one
        # failing channel cannot silence the report for another.
        self.playhead_thread = None
        self.watchdog_thread = None
        # THE GENERATOR'S HEARTBEAT. Stamped at the top of every poll tick,
        # read by the watchdog thread. None until the first tick: reporting a
        # stall before the loop has ever run would cry wolf on every boot.
        self._beat_at = None
        self._stalled = False
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
        # STEP is the home state: the one page that is always true, showing
        # what the selected channel plays with the playhead over it.
        self.mode = "STEP"
        # One page index per ring, so selecting a drum and coming back to a
        # voice returns to the page you left rather than to whatever the drum's
        # shorter ring could hold.
        self.page_idx = {}
        # Generated rings, keyed (mode, kind, channel). Built once and held:
        # _ring() runs on the MIDI thread, where reaching an engine load would
        # freeze the instrument - midi_event holds self.lock for the whole
        # event and a load blocks on a socket for seconds.
        self.gen_cache = {}
        # Page-1 synth symbols, keyed by engine code. What a plugin publishes
        # depends on the plugin and nothing else, so this needs no
        # invalidation - a different engine is a different key.
        self.sym_cache = {}
        # THE CHORD WALKER'S OWN STATE. `walk` is bars between moves, 0 =
        # LOCK; `wspan` is how far it may stray from the hand-set root, in
        # SCALE DEGREES. `walk_degree` is where it currently is and `walk_base`
        # is the root the player dialled in - kept apart because the base is
        # the player's and the degree is the machine's, which is the same
        # base/offset law MOD already obeys everywhere else.
        self.walk_degree = 0
        self.walk_base = None
        self.globals = dict(root=9, scale=0, bpm=132, master=80, walk=0,
                            wspan=2,
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
                                 "range", "kit_range", "register", "rhythm",
                                 "rhythm_reg", "ratchet", "lane",
                                 # P1, 2026-08-31. Membership here is what
                                 # makes apply() the write path for them: a
                                 # verb missing from this set is stored and
                                 # displayed and never reaches the pattern -
                                 # which is exactly the apply() hole that hid
                                 # HITS and ROTATE for months.
                                 "model", "walk_span", "walk_stride",
                                 "feed", "amount"}
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
        # SP10: modulators, keyed by (channel, verb).
        #
        # KEYED BY VERB, never by (mode, page, encoder position). A future SP9
        # layout switch would otherwise orphan every modulator, or worse,
        # re-point it at whatever verb now sits in that slot.
        #
        # Each value: {"depth", "rate", "shape", "phase0", "base", "seed"}.
        # `base` is the driver's own truth for the parameter - the LFO writes
        # base+offset and never reads its own output back.
        self.mod = {}
        # THE SIX MODIFIERS, one object each, 2026-09-01. Every one of them
        # obeys the same duration rule now - a tap latches, a hold is
        # momentary - where there used to be five different grammars for
        # "enter a state". tlib.latch holds the rule and is unit tested;
        # nothing here decides it.
        #
        # `mod` keeps its own names below as properties, because MOD is read
        # in ten places and by three threads and a rename would touch every
        # one of them for no behavioural gain.
        # CCs whose PRESS was taken by a chord. Their release must be taken
        # too, or it reaches the latch and is measured against an unrelated
        # earlier press.
        self._chord_swallowed = set()
        self.latches = {name: tlib.latch() for name in
                        ("shift", "mod", "lens", "arm", "bank", "mute",
                         "navigate")}
        # THE LENS, 2026-09-01. ALL held or latched: the eight encoders stop
        # being eight verbs of one channel and become one verb across all
        # eight. It replaced the MIXER and FILTER modes and five spread pages.
        # The last CHANNEL verb a hand moved. It is what the lens spreads, and
        # it is set by the ordinary encoder path rather than by the lens - so
        # opening the lens shows you the knob you were just on, without a
        # second gesture to say which one you meant.
        self._lens_verb = None
        self.mod_last = None          # the key MOD+pad edits
        self.mod_seed = 0             # bumped per bind, so two S&H differ
        self._t0 = time.monotonic()   # the modulator clock's origin
        # (channel, verb, base) restores owed by _mod_clear_all, drained on
        # the poll thread. The MIDI thread must not write parameters.
        self._mod_restore_due = []
        # Which kind a channel behaves as, when the player has said so.
        # None means "ask the chain" - never a stored copy of it.
        self.kind_override = {i: None for i in range(len(tlib.CHANNELS))}
        # Big encoder: last CC 15 value, and the sub-detent remainder. It
        # is a counter, so a delta needs the previous value; None means
        # 'no reference yet' and the first report only establishes one.
        self._big_last = None
        self._big_carry = 0
        # REROLL: channels waiting for their own wrap, and the one-deep undo.
        # Pending is per CHANNEL rather than per button so a reroll lands on
        # each channel's OWN bar - the whole point of per-group pattern
        # lengths is polyrhythm, and a single global bar would fight it.
        self._reroll_pending = set()
        self._reroll_undo = {}
        # PHRASE: bars since the transport was started or RESTARTed. None
        # while stopped - there is no bar to be on, and a stale number reads
        # as a clock that has stuck.
        #
        # Anchored to the TRANSPORT, never to a channel's own wrap: each
        # channel owns its length, so a polymetric rig has eight different
        # bars and any one of them would be a lie on the other seven.
        self._phrase_anchor = None
        # (channel, position, pattern length, clocks per beat) - what the
        # phrase clock corrects itself against. Re-seeded rather than nudged
        # whenever the reference stops being comparable: a different channel,
        # a different length, or an error too large to be drift.
        self._phrase_ref = None
        self._phrase_bar = None
        self._pending_macros = tlib.PendingQueue()
        # Lengths armed while the transport was stopped. The absolute landing
        # bar cannot be known until there is a bar zero, so only the length is
        # kept and the queue is filled at transport start. Without this a
        # macro armed on a stopped rig either fires the instant it is armed -
        # the way _wrap_channel takes a pending structure change - or is
        # silently lost.
        self._armed_while_stopped = {}
        self._arm_picked = None
        self._arm_bars = {}
        # Who survives a DROP. Nominated on the Group buttons while ARM is
        # held; empty means the drop takes everything, which is a real and
        # useful setting rather than an unconfigured one.
        self._drop_survivors = set()
        # Countdowns held still while the macro queue is frozen. Empty
        # whenever it is not - see tlib.freeze_memo, and the defect it exists
        # for: a countdown that reads zero for as long as you hold FREEZE.
        self._freeze_memo = {}
        # The bar a transient note expires on. A macro that REFUSES has no
        # restore leg to clear its note the way a macro that ran does, so the
        # note is given the window the macro itself would have occupied.
        self._note_expires = None
        # The mute picture as it was the instant the drop fired, restored
        # verbatim afterwards. Never "all on".
        self._drop_restore = {}
        # A running CHANCE ramp, or None. One dict rather than four
        # attributes so "is a ramp running" is one truth, not four that can
        # disagree.
        self._chance_ramp = None
        # Channels closing or opening through their filter and level, keyed by
        # channel. One dict per channel rather than four parallel maps, for the
        # reason the chance ramp above gives: "is a ramp running" must be one
        # truth, not four that can disagree.
        self._exit_ramps = {}
        # A running HALF/DOUBLE-time move: channel -> the (div, beats, hits,
        # rot) tuple captured before it, plus what the macro managed. The
        # CAPTURE is restored, never the computed inverse - drift, reroll and
        # the encoders all move those values, so the inverse is only
        # arithmetically identical while nothing else touches them.
        self._timescale_restore = {}
        self._timescale_note = None
        # Bars for a BREAK the player just armed, drained by the poll thread.
        self._break_due = None
        # A running RATCHET ramp, or None: the same dict shape as the CHANCE
        # ramp, and for the same reason - one truth about whether a ramp is
        # running rather than three attributes that can disagree.
        self._ratchet_ramp = None
        # A running GATE collapse, or None. Same dict shape as the two ramps
        # above, with one field they do not have: `notes`, the captured events
        # every rewrite is rebuilt FROM. There is no setNoteDuration in the
        # installed API, so a restore is remove-and-re-add and it starts from
        # nothing - the capture is what makes the macro reversible at all.
        self._gate_ramp = None
        # BANKS AS SCENES, 2026-09-01. The overlay, the page the big encoder
        # is showing while it is held, and the bank waiting for the bar.
        self._bank_page = 0
        self._bank_pending = None
        # Everything PYTHON owns about a channel, per bank. zynseq carries the
        # patterns; the registers, the rotation, the ownership and the
        # generator settings live here and are keyed by CHANNEL only - so
        # without this a bank switch would swap the patterns and leave all
        # three voices playing the same line over a different pattern set,
        # which is not a scene.
        self._bank_state = {}
        # Which channels are writing their fill bar right now. Set at the
        # phrase boundary and read by the writers - a flag rather than an
        # argument, because both writers are reached from several places and
        # threading one more parameter through every caller is how a default
        # ends up meaning "no fill" in a path nobody checked.
        self._fill_now = set()
        # Queued mute changes: channel -> the mute state to take at that
        # channel's next wrap. DELIBERATELY NOT state[ch]["pending"] - that
        # set holds only "div" and "length", and _wrap_channel treats any
        # non-"div" member as a length change and calls _set_length(), so a
        # "mute" member there would rewrite the pattern on every queued mute.
        self._mute_pending = {}
        # Beat repeat. `_repeat_due` is the edge the MIDI thread hands to the
        # poll thread; `_repeat_restore` is channel -> (beats, hits, rot)
        # captured before the collapse.
        self._repeat_due = None
        self._repeat_restore = {}
        # The daemon re-bases the pads on BOTH edges of a Group press, so a
        # correction sent when we intercept the press is overwritten by the
        # release we never see - Group buttons are press-only here. Re-asserted
        # from the poll thread instead, for as long as an intercepting modifier
        # is held plus one tick after it is let go.
        self._note_base_due = False
        # Global modulator depth, driven by the big encoder while MOD is
        # latched. Stored SEPARATELY from every entry's own depth - see
        # techno_lib.mod_depth_scale for why that is not a style choice:
        # multiplying the stored depths in place would strand every modulator
        # at zero the first time this reached 0.
        self.mod_depth_mult = 1.0
        # Whether this libzynseq exposes per-step play chance, decided by
        # _probe_step_chance() rather than assumed - see its docstring.
        self.has_step_chance = False
        self.has_stutter = False
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
        # Audio capture to disk. Separate from rec_down, which is overdub.
        self._recording = False
        # Set on the MIDI thread, drained on the poll thread: start_recording
        # spawns jack_capture and can block, and midi_event holds the lock for
        # the whole event. The same law that keeps a preset load off the MIDI
        # thread.
        self._record_due = False
        # The play-session event log's file handle, or None. Opened once and
        # line buffered: an event must be on disk before the thing it
        # describes can wedge the rig, or the last line - the interesting one
        # - is the one that is lost.
        self._slog_fh = None
        # Last master-filter line's timestamp. An encoder sweep is the one
        # gesture that arrives at a rate; everything else in this log is an
        # event and needs no throttle.
        self._slog_fx_at = 0.0
        if SESSION_LOG_PATH:
            try:
                self._slog_fh = open(SESSION_LOG_PATH, "a", buffering=1)
            except OSError as e:
                logging.warning("Maschine: no session log: %s", e)
        # FREEZE. Two stages on one button, law L1: `frozen` is the LATCH a
        # tap toggles, `freeze_deep` is the MOMENTARY hold that parks the LFOs
        # as well.
        self.frozen = False
        self.freeze_deep = False
        self.solo_down = False
        self.solo_mode = False           # latched: the F row means solo
        # TEMPO held: every encoder returns to the pre-2026-08-16 feel, three
        # twice the default sensitivity. Hold only, no latch - COARSE + an
        # encoder is one finger and one hand, so the latch MOD needs (MOD + a
        # Group button is a two-handed stretch) buys nothing here, and a
        # latched sensitivity change is a surface that lies about its feel.
        self.coarse_down = False
        self._down_at = {}

    # THE SIX MODIFIERS, read through their latches. Properties rather than
    # flags since 2026-09-01: the duration rule lives in tlib.latch, where it
    # is unit tested, and the eighty-odd read sites below are unchanged.
    #
    # Each name means "on, by either route". `_held` and `_latched` are for
    # the light alone - that is the ONE place the two routes must be told
    # apart, because a steady light means your finger is on it and a blink
    # means it has left.
    @property
    def mod_down(self):
        """MOD is active either way round: held, or tapped on."""
        return self.latches["mod"].down

    @property
    def mod_held(self):
        return self.latches["mod"].held

    @property
    def mod_latched(self):
        return self.latches["mod"].latched

    @property
    def shift_down(self):
        return self.latches["shift"].down

    @property
    def lens_down(self):
        return self.latches["lens"].down

    def _lens_now(self):
        """The verb the lens is actually holding, or None.

        VALIDATED AGAINST THE SELECTED CHANNEL, every time. `_lens_verb` is
        whatever the hand last moved, and the hand may have moved it on a
        channel of the other kind - turn a drum's HITS, select a voice, and
        the lens would otherwise be holding a verb that channel does not have
        and its own pages cannot reach.

        That was not merely untidy: the euclid path took the column index as
        its channel, so a stale HITS aimed at a voice would have rewritten a
        Turing melody as a drum line. The refusal is at the door in _encoder
        too - two gates, because this one keeps the PICTURE honest and that
        one keeps the SOUND honest, and this surface's expensive bugs are all
        the cases where those two disagreed.

        Falls back to LENS_DEFAULT rather than closing the lens: an empty
        page under a held button reads as a fault, and LEVEL is live on all
        eight of anything."""

        verb = tlib.lens_verb(self._lens_verb)
        if verb is None:
            return None
        if verb in self._lens_ring():
            return verb
        return tlib.lens_verb(tlib.LENS_DEFAULT)

    @property
    def arm_down(self):
        return self.latches["arm"].down

    @property
    def bank_down(self):
        return self.latches["bank"].down

    @property
    def mute_down(self):
        return self.latches["mute"].down

    @property
    def navigate_down(self):
        return self.latches["navigate"].down

    def _modifier_edge(self, name, down):
        """One button edge for one modifier. True when the state changed.

        EVERY modifier goes through here, which is the whole reform: a tap
        latches, a hold is momentary, and the two routes reach the same state.
        The handlers below decide only what to REPAINT."""

        return self.latches[name].edge(down, time.monotonic(),
                                       HOLD_MS / 1000.0)

    # --- plumbing ------------------------------------------------------

    def _send_osc(self, packet):
        try:
            self.osc.sendto(packet, OSC_ADDR)
        except OSError as e:
            logging.error(f"Maschine OSC send failed: {e}")

    @property
    def bank(self):
        """The zynseq bank this driver addresses.

        Read this, never `self.zynseq.bank`. Ten sites used to read zynseq
        directly and nothing ever asserted a bank, so an external change
        repointed every call while every cache still described the old bank -
        no log, no symptom, until something sounded wrong."""

        return self.bankpin.bank

    def _pin_bank(self):
        """Take zynseq's current bank deliberately. Init, and any restore that
        resyncs the caches anyway. Silent: this is not a drift."""

        said = self.bankpin.pin(self.zynseq.bank)
        if said is not None:
            logging.warning(f"Maschine: {said}")

    def _check_bank(self):
        """Once a second, from the poll thread. A bank that moved from outside
        this driver is adopted, said out loud, and everything cached against
        the old one is re-read - which is the whole point: the caches are what
        made this silent."""

        said = self.bankpin.observe(self.zynseq.bank)
        if said is None:
            return
        logging.warning(f"Maschine: {said}")
        self._slog("bank", event="drift", bank=self.bankpin.bank,
                   drifts=self.bankpin.drifts)
        with self.lock:
            self._resync_all()
            self._render_all()

    # RULE is deliberately NOT in GENERATOR_PARAMS and has no apply() branch.
    # It is not a pattern write: it chooses which generator runs at the next
    # wrap, and the register it evolves does not move until then. Putting it in
    # that set without a branch in _apply_generator would be the exact shape of
    # the hole that hid HITS and ROTATE for months - a verb the set promises
    # reaches the pattern and that nothing writes.
    # The switch columns and their value sets. RULE is on both kinds - both
    # have a rhythm register - and LEAN is drums only, because placement on a
    # voice is the rhythm register's own job.
    SWITCH_VERBS = {"rule": tlib.RULES, "lean": tlib.LEANS}

    def _evolve(self, channel, register, steps, rhythm):
        """Evolve a rhythm register one generation, by whichever generator the
        channel is on. ONE PLACE, so the drum path and the voice path can never
        end up on different rules.

        RANDOM/RHYTHM means the same thing either way: on the shift register it
        is the probability the fed-back bit flips, on an automaton it is the
        probability the rule is applied to each bit. LOCK is exact on both, and
        that is what let the knob keep one meaning."""

        rule = self.param_get(channel, "rule")
        if rule in tlib.CA_RULES:
            return tlib.ca_step(register, steps, rule, rhythm / 100.0)
        return tlib.mutate(register, steps, rhythm / 100.0)

    def _exit_bars(self, channel):
        """This channel's EXIT length in bars, through param_get."""

        return int(self.param_get(channel, "exit") or 0)

    def _exit_ticks_per_bar(self):
        """How many 200 ms writes fit in a bar at the current tempo.

        Measured rather than assumed: at 125 BPM a bar is 1920 ms and the
        shipped sub-rate is ~198 ms, so a one-bar close is nine or ten steps.
        zynmixer interpolates every level change across the JACK period, so
        that is click-free - it steps, it does not zipper."""

        bpm = float(self.globals.get("bpm", 125) or 125)
        bar_s = 4.0 * 60.0 / max(1.0, bpm)
        tick_s = PLAYHEAD_POLL_S * VOLUME_POLL_TICKS
        return max(1, int(round(bar_s / tick_s)))

    def _exit_start(self, channel, muting):
        """Begin a close or an open. False means "not this channel" and the
        caller mutes hard, which is the 0-bar default.

        CAPTURE AND RESTORE, the same bookkeeping _drop_fire uses: what is put
        back is what was there, never a nominal full level. A channel the
        player had at 40 comes back at 40."""

        bars = self._exit_bars(channel)
        if bars <= 0:
            return False
        chan = self._mixer_chan(channel)
        if chan is None:
            return False
        level = int(self.param_get(channel, "level"))
        cutoff = (int(self.param_get(channel, "cutoff"))
                  if self.channel_kind(channel) == "voice" else None)
        running = self._exit_ramps.get(channel)
        if running:
            # A reversal mid-flight keeps the ORIGINAL captured values. Reading
            # them again here would capture the half-closed ones and the
            # channel would never come back to where it started.
            level = running["level"]
            cutoff = running["cutoff"]
        self._exit_ramps[channel] = {
            "steps": bars * self._exit_ticks_per_bar(),
            "step": 0,
            "closing": bool(muting),
            "level": level,
            "cutoff": cutoff,
        }
        if not muting:
            # An OPEN unmutes first and comes up from silence. Unmuting at the
            # end instead would put the whole rise behind a muted strip and the
            # gesture would be inaudible.
            self._set_muted(channel, False)
        return True

    def _exit_write(self):
        """Advance every running exit one step. Poll thread, ~200 ms, beside
        the modulators - the same writer, the same rate, the same reason."""

        if not self._exit_ramps:
            return
        for channel in list(self._exit_ramps):
            ramp = self._exit_ramps[channel]
            ramp["step"] += 1
            factor = tlib.exit_factor(ramp["step"], ramp["steps"],
                                      closing=ramp["closing"])
            self._apply_mix(channel, "level",
                            int(round(ramp["level"] * factor)))
            if ramp["cutoff"] is not None:
                self._set_voice_ctrl(
                    channel, self.VOICE_CTRL_COLUMNS["cutoff"],
                    int(round(ramp["cutoff"] * tlib.exit_cutoff(factor))))
            if ramp["step"] < ramp["steps"]:
                continue
            del self._exit_ramps[channel]
            # LANDED. Put the captured values back on the strip BEFORE muting,
            # so the channel that comes back later is the channel that left -
            # and mute last, so nothing is heard between the two writes.
            self._apply_mix(channel, "level", ramp["level"])
            if ramp["cutoff"] is not None:
                self._set_voice_ctrl(channel,
                                     self.VOICE_CTRL_COLUMNS["cutoff"],
                                     ramp["cutoff"])
            if ramp["closing"]:
                self._set_muted(channel, True)
            with self.lock:
                self._render_mutes()

    def _move_of(self, channel):
        """This channel's MOVE, for the gate. Read through param_get, never
        out of self.state: a verb whose storage moves is a verb that reads
        right, displays right and does the wrong thing - five times in one
        evening on 2026-08-31."""

        return self.param_get(channel, "move")

    def _move_roll(self):
        """One 0..99 draw for one gate question. The library stays pure and
        deterministic; the randomness is here."""

        return random.randrange(100)

    def _moves(self):
        """Every channel's MOVE, for the macro walkers that ask about all
        eight at once."""

        return {ch: self._move_of(ch) for ch in range(len(tlib.CHANNELS))}

    def _seq_addr(self, group):
        """Sequence address for a group, as the installed libzynseq expects:
        (bank, sequence, track). Every zynseq call routes through here."""

        return (self.bank, group, 0)

    def _pattern_of(self, group):
        """Pattern id backing a group, read from zynseq (not cached).
        Installed signature: getPattern(bank, sequence, track, position)"""

        return self.libseq.getPattern(self.bank, group, 0, 0)

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

        if param == "range" and self._is_sampler(channel):
            # SP8's alias applies to READS as well as writes. It did not at
            # first, and the symptom was precise: the encoder read `range` (a
            # voice's octave spread, 2) and wrote `kit_range`, so every turn
            # started from 2 again and only ever produced 1 or 3. An alias
            # that covers one direction is a value that disagrees with itself.
            return self.state[channel].get("kit_range", 4)

        attr = self._legacy_attr(channel, param)
        if attr is not None:
            value = getattr(self, attr)[channel]
            # LENGTH is beats in zynseq and steps on the surface:
            # DIVISIONS entries are (label, steps_per_beat, beats).
            if param == "length":
                return value * lib.DIVISIONS[self.div[channel]][1]
            return value
        return self.state[channel].get(param)

    def _mod_key(self, channel, verb):
        """Modulators on a global verb carry channel None; everything else is
        per channel. Same shape as the (channel, verb) pair _verb() already
        takes, so nothing has to translate.

        An `fx:` verb IS a global verb, whatever channel the gesture arrived
        on. _verb_fx and _mod_zctrl both resolve it through fx_handle(0, which)
        - one insert, ganged across every channel - so keying it by the
        selected group meant binding on group A and then switching to group C
        hid the tilde and the span, and let a second modulator be bound to the
        same port to fight the first. `lv2:` verbs stay per channel: they
        address the selected channel's own synth processor.

        Channel None is a real input here, not only a real output: set_state
        feeds this the channel it parsed back out of a saved key, and a saved
        `fx:` key carries an empty channel field."""
        if tlib.mod_is_global(verb):
            return (None, verb)
        return (None if channel is None else int(channel), verb)

    def _mod_range(self, channel, verb):
        """(lo, hi) in SURFACE units for a verb, or None when this driver has
        no range for it.

        Generated plugin ports report (0, 100): _verb_lv2 (line 649) already
        drives them as a percentage scaled onto the port's own range, and a
        modulator must speak the same units as the knob beside it or the two
        would disagree about what depth 50 means."""
        if verb in ("hits", "rotate") and channel is not None:
            # Not in VERB_RANGES because their range is the PATTERN's, not a
            # constant: how many steps this channel has right now.
            steps = lib.step_count(self.div[channel])
            return (0, steps) if verb == "hits" else (0, max(0, steps - 1))
        span = self.VERB_RANGES.get(verb)
        if span is not None:
            return (span[0], span[1])
        if verb.startswith(tlib.VERB_LV2) or verb.startswith(tlib.VERB_FX):
            return (0.0, 100.0)
        return None

    def _mod_column_span(self, channel, verb):
        """This column's dashed modulation span as bar fractions (lo, hi), or
        None when nothing is bound to this (channel, verb) - the caller
        passes None straight to mark_modulated(), which leaves the column
        alone."""
        if verb is None:
            return None
        entry = self.mod.get(self._mod_key(channel, verb))
        if entry is None:
            return None
        lo_hi = self._mod_range(channel, verb)
        if lo_hi is None:
            return None
        # IMPORTANT: This narrows the span via mod_span(), but the live tick
        # (_mod_write) is normalised against the raw lo_hi width, not this
        # narrowed span. If either normalisation changes without the other,
        # the tick will no longer land visually inside this envelope.
        return tlib.mod_span(entry["base"],
                             tlib.mod_depth_scale(entry["depth"],
                                                  self.mod_depth_mult),
                             lo_hi[0], lo_hi[1])

    def _mod_tick_frac(self, channel, verb):
        """Where the modulator's wave currently sits, as a bar fraction, or
        None when nothing is bound to (channel, verb) or the poll thread has
        not sampled it yet (entry has no "live" the instant after bind).

        mod_span is symmetric about the base, so its midpoint never moves -
        drawing the tick there would show a static point forever. This reads
        the fraction _mod_write() stashed at its own ~200 ms rate instead, so
        the tick is the one thing on screen that actually sweeps."""
        entry = self.mod.get(self._mod_key(channel, verb))
        if entry is None:
            return None
        return entry.get("live")

    def _mod_override(self, channel, verb, value):
        """The verb's BASE when a modulator is bound to (channel, verb), else
        `value` unchanged. Thin plumbing over tlib.mod_base_or, which carries
        the actual (and unit tested) substitution rule - this method's only
        job is building the key and handing over self.mod.

        Substitutes only in the VIEW layer that columns() reads - state_view()
        and _generated_view() call this after computing their normal value, so
        the display always shows what the knob is set to, never where the LFO
        has swept it to at this instant. _mod_write() is untouched by this:
        the engine still gets the swept value: only what the display reads
        back changes here."""
        return tlib.mod_base_or(self.mod, self._mod_key(channel, verb), value)

    def _mod_zctrl(self, channel, verb):
        """The zynthian_controller behind a generated verb, or None.

        Resolved the same way _verb_lv2 and _verb_fx resolve it - through
        `proc.controllers_dict[symbol]`. Do NOT reach for
        zynthian_lv2.get_plugin_ports(): it returns a dict keyed by port
        INDEX, not by symbol, so a membership test against symbols silently
        returns nothing and looks exactly like an absent plugin."""
        if verb.startswith(tlib.VERB_LV2):
            proc = self._voice_processor(channel)
            symbol = verb[len(tlib.VERB_LV2):]
        elif verb.startswith(tlib.VERB_FX):
            which, _, symbol = verb[len(tlib.VERB_FX):].partition(":")
            proc = self.fx_handle(0, which)
        else:
            return None
        if proc is None:
            return None
        return proc.controllers_dict.get(symbol)

    def _mod_percent_get(self, channel, verb):
        """A generated port's current value as the 0-100 the surface uses."""
        zctrl = self._mod_zctrl(channel, verb)
        if zctrl is None:
            return None
        span = zctrl.value_max - zctrl.value_min
        if span <= 0:
            return None
        return (zctrl.value - zctrl.value_min) / span * 100.0

    def _elapsed_beats(self):
        """Beats since the driver started.

        Derived from BPM rather than from seconds so every modulator is
        bar-synced and follows a tempo change without being told about it.

        Defined HERE rather than with the poll-thread writer because Task 4
        binds a modulator's phase from it - a definition in Task 6 would leave
        Task 4 calling a method that does not exist, and py_compile cannot see
        that on WSL.

        THE TEMPO READ HOLDS THE LOCK, and nothing else here does. This used
        to go through globals_view(), which calls libseq.getTempo() - an
        unlocked zynseq call, reached from _mod_write on the poll thread and
        from get_state on whichever thread saves. libzynseq is not thread-safe
        and an unlocked reach into it once took the whole UI down with SIGSEGV
        mid-jam.

        The lock is taken for the tempo read ALONE rather than around
        _mod_write's parameter writes, which is why the read is not simply
        moved into the caller's locked section: a parameter write can block on
        a socket for seconds and must never hold this lock. self.lock is an
        RLock, so the MIDI thread - which already holds it for the whole event
        - can call this without deadlocking. A cached tempo was the
        alternative and was rejected: it needs a refresh site of its own and
        goes stale exactly when the tempo moves, which is the one thing this
        clock exists to follow."""
        with self.lock:
            bpm = self.libseq.getTempo()
        return (time.monotonic() - self._t0) * (float(bpm or 120) / 60.0)

    def _mod_percent_set(self, channel, verb, percent):
        """Write a generated port from a 0-100 surface value, using the same
        scaling _verb_lv2 uses so a modulated port and a turned knob land on
        identical numbers."""
        zctrl = self._mod_zctrl(channel, verb)
        if zctrl is None:
            return
        span = zctrl.value_max - zctrl.value_min
        if span <= 0:
            return
        percent = min(100.0, max(0.0, float(percent)))
        target = zctrl.value_min + span * (percent / 100.0)
        if tlib.port_is_discrete(zctrl.value_min, zctrl.value_max,
                                 getattr(zctrl, "is_integer", True)):
            target = round(target)
        zctrl.set_value(target, True)

    def state_view(self, channel):
        """The state techno_lib.columns() reads: the dict, the four parameters
        that live in the legacy arrays, and the values owned by the mixer and
        the chain. Read-only - nothing may write through this."""

        view = dict(self.state[channel])
        # The kind travels WITH the view since the lens shipped, 2026-09-01.
        # A spread page draws eight channels of two kinds at once, so it
        # cannot take one kind as an argument the way a channel page does -
        # and law L4's contextual half (SPAN off the walk model, a synth role
        # the plugin does not publish) has to be answered per column.
        view["kind"] = self.channel_kind(channel)
        for param in self._LEGACY:
            if self._legacy_attr(channel, param) is not None:
                view[param] = self.param_get(channel, param)

        # SP8: on a SAMPLER the RANGE column is the kit-walk window, not the
        # voice's octave spread - octave spread means nothing when a note picks
        # a drum rather than a pitch. Same column, different value, chosen by
        # the engine. The two are stored separately so an existing snapshot's
        # `range` cannot silently narrow a kit walk.
        if self._is_sampler(channel):
            view["range"] = self.state[channel].get("kit_range", 4)

        chan = self._mixer_chan(channel)
        if chan is not None:
            view["level"] = int(round(self.state_manager.zynmixer.get_level(chan) * 100))

        # A LIVE SQUEEZE SHOWS THE KNOB, NOT THE SWEEP. Pressure writes the
        # displaced value through apply(), so without this the column tracked
        # the finger and both screens repainted about thirty times a second -
        # measured at the rig 2026-08-31 as 110 OSC messages/s, 104 of them
        # display, which is inside the band that wedges the controller.
        #
        # The same mistake, and the same fix, as the MOD tick that was removed
        # for rebuilding both screens six times a second. tlib.pressure_display
        # carries the reasoning.
        view = tlib.pressure_display(view, tlib.PRESSURE_VERB,
                                     self._press_base[channel])

        # The ENGINE decides, not the behaviour: a sampler played by the
        # Turing register still has a kit and a sample, and the CONTROL page
        # it is given now shows both. Matches _page_kind().
        if self._is_sampler(channel):
            kits = self._kit_list()
            pending = self.kit_pending
            shown = pending[1] if pending and pending[0] == channel \
                else self._current_kit_index(channel, kits)
            name = kits[shown][0] if 0 <= shown < len(kits) else ""
            # Full names from here down: columns() shortens them with
            # short_label(), which keeps the trailing digits that tell two
            # neighbours apart. Truncating here as well would throw those
            # away before the rule that protects them ever runs.
            view["kit"] = name or "----"
            view["sample"] = self._sample_name(channel) or "----"
        else:
            view["preset"] = self._preset_name(channel) or "----"
        # Per column, because the four page-1 symbols come from the plugin that
        # is actually loaded: a sampler behaving as a voice (SP4) publishes
        # none of them, and a synth swapped in from the touchscreen may publish
        # only some. Whatever _set_voice_ctrl cannot reach draws dead.
        symbols = self._voice_symbols(channel)
        view["synth_ctrl"] = tuple(bool(sym) for sym in symbols) \
            if symbols else (False,) * 4
        # A modulated verb reads back as its BASE here, never the live swept
        # value _mod_write() just wrote into self.state / the mixer - the
        # value cell shows what the knob is set to, not where the LFO is.
        for verb in tlib.MOD_TIMBRE:
            if verb in view:
                view[verb] = self._mod_override(channel, verb, view[verb])
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

        if param == "range" and self._is_sampler(channel):
            # SP8: the RANGE column edits the KIT WINDOW on a sampler. Aliased
            # here rather than at each call site so the encoder, the snapshot
            # and any future caller all land on the same value as the view.
            param = "kit_range"

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
        # The chord walker. 0 is LOCK; 16 bars is the longest phrase this
        # instrument counts, so a walk slower than that would never be seen to
        # move. SPAN is in SCALE DEGREES, and 7 is a full octave of any scale
        # here except PENT, which reaches its own octave sooner.
        "walk": (0, 16, ENC_UNITS_DISCRETE),
        "wspan": (0, 7, ENC_UNITS_DISCRETE),
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

        if param == "root":
            # A HAND TURN SETS THE WALKER'S BASE AND DOES NOT CANCEL IT.
            # `new_features.md` claimed a standing precedent that a hand turn
            # cancels the machine's claim; there is NO CODE behind that
            # sentence anywhere in this driver - mod_steer leaves its modulator
            # running, and four bar-rate macros overwrite every channel with no
            # such check. So the rule had to be chosen rather than inherited,
            # and this is MOD's base/offset law: the player owns the base, the
            # machine owns the offset, and moving the base moves the whole walk
            # rather than ending it.
            self.walk_base = value
            self.walk_degree = 0

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
        elif param == "walk":
            # Nothing to push: the walker is read by the phrase tick. Turning
            # it back to LOCK leaves the root exactly where the walk left it,
            # which is deliberate - snapping home would make LOCK a transport
            # control rather than an off switch.
            pass
        elif param == "wspan":
            # Narrowing the span must pull the walk inside it now, not at some
            # later bar when it happens to step: a degree outside its own span
            # is a number the page would be drawing as legal.
            self.walk_degree = max(-value, min(value, self.walk_degree))
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
        # An enumerated or toggled port moves between its OWN ticks, which
        # are not necessarily one unit apart: stepping in whole units lands
        # between two scale points on any plugin whose values are sparse, and
        # the port then reads as a number nobody named. Clamped, not wrapped -
        # F1-F8 wrap, a knob does not.
        spec = tlib.switch_spec(getattr(zctrl, "labels", None),
                                getattr(zctrl, "ticks", None))
        if spec is not None:
            labels, ticks = spec
            delta = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if delta == 0:
                return
            index = tlib.switch_index(zctrl.value, ticks, labels)
            target = ticks[tlib.switch_step(index, len(ticks), delta)]
        elif tlib.port_is_discrete(zctrl.value_min, zctrl.value_max,
                                 getattr(zctrl, "is_integer", True)):
            # A handful of positions with no labels on them: one percent of it
            # rounds to nothing and _set_value() truncates integer controls,
            # so drive it in whole units instead. Measured dead on TAP
            # Reverberator.
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
            # Logged unthrottled: these are the three ways a knob on a
            # generated page is DEAD rather than slow, they happen once per
            # gesture at most, and each one looks identical from the surface.
            self._slog("fx", which=which, symbol=symbol, wrote=False,
                       why="no processor")
            return
        zctrl = proc.controllers_dict.get(symbol)
        if zctrl is None:
            self._slog("fx", which=which, symbol=symbol, wrote=False,
                       why="no port")
            return
        span = zctrl.value_max - zctrl.value_min
        if span <= 0:
            self._slog("fx", which=which, symbol=symbol, wrote=False,
                       why="zero span")
            return
        # An enumerated or toggled port moves between its OWN ticks, which
        # are not necessarily one unit apart: stepping in whole units lands
        # between two scale points on any plugin whose values are sparse, and
        # the port then reads as a number nobody named. Clamped, not wrapped -
        # F1-F8 wrap, a knob does not.
        spec = tlib.switch_spec(getattr(zctrl, "labels", None),
                                getattr(zctrl, "ticks", None))
        if spec is not None:
            labels, ticks = spec
            delta = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if delta == 0:
                return
            index = tlib.switch_index(zctrl.value, ticks, labels)
            target = ticks[tlib.switch_step(index, len(ticks), delta)]
        elif tlib.port_is_discrete(zctrl.value_min, zctrl.value_max,
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
        if tlib.fx_is_ganged(which):
            for channel in range(len(tlib.CHANNELS)):
                other = self.fx_handle(channel, which)
                if other is None:
                    continue
                zc = other.controllers_dict.get(symbol)
                if zc is not None:
                    zc.set_value(target, True)
        else:
            # ONE instance, one write. A master insert costs a single jalv
            # host, which is the whole reason it is affordable at all: the
            # per-chain insert pair sits on eight chains, so an effect there
            # costs eight times what it looks like.
            zctrl.set_value(target, True)
        if which == tlib.FX_MAIN:
            # THROTTLED, and only the master insert. An encoder sweep is the
            # one gesture in this instrument that arrives at a rate rather
            # than as an event, and the log's whole premise is that it never
            # writes at a rate - two animations had to be cut to get the
            # controller's write budget back.
            #
            # The master filter is the one control that can silence all eight
            # channels at once - MDA RezFilter goes silent below about a third
            # of its range - so its VALUE is what a "the rig went quiet"
            # report needs to be read against.
            now = time.monotonic()
            if now - self._slog_fx_at >= 0.5:
                self._slog_fx_at = now
                self._slog("fx", which=which, symbol=symbol, wrote=True,
                           value=round(float(target), 3),
                           lo=zctrl.value_min, hi=zctrl.value_max)
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

    def _write_voice_pattern(self, channel, by_hand=False):
        """Write the current register into the channel's pattern. Mutates
        nothing - Duplicate needs to write without advancing.

        `by_hand` is a PAD TAP, and it overrides the ownership refusal below.
        Owner's rule, 2026-08-31: "everything is generated first always. If I
        tap in steps, they should be kept." A tap is the player asking for this
        exact step, so refusing it because the player had already played the
        channel refused them twice for the same reason. The generator's own
        writes are still refused on an owned channel - that is what ownership
        is for, and it is unchanged.

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
            if self.owner[channel] == "player" and not by_hand:
                # The take stays. The token cannot express this: it is the
                # mutex between threads and clears itself after every write,
                # so it cannot carry an ownership that survives a snapshot.
                return
            if self.writer_token[channel] not in (None, "turing"):
                return                    # someone else owns this pattern
            self.writer_token[channel] = "turing"
        try:
            steps = lib.step_count(self.div[channel])
            notes, mask = self._voice_line(channel, steps)
            # Which steps sound. A masked step skips addNote entirely, so the
            # write burst - the largest risk in this design - gets smaller at
            # every step masked off, never larger.
            # One bit per step from the channel's OWN rhythm register, not a
            # tap off the pitch register. That separation is the whole point:
            # the melody can evolve while the steps stay exactly where the
            # player put them.
            # .get, not [], deliberately: this runs on the poll thread,
            # whose handler catches Exception and RETURNS - one KeyError
            # from a state dict built by an older path would kill the
            # playhead loop for the rest of the session.
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

    def _drift_channel(self, channel):
        """Apply this channel's drift modulators. Called ONCE PER WRAP.

        Held still by FREEZE: drift rewrites the pattern, which is exactly
        what a player freezes the machine to stop.

        Drift is the half of MOD that rewrites the PATTERN - hits gained and
        lost, the bar rotating under itself, a channel thinning out and coming
        back. It runs here and never in _mod_write(): a pattern verb written on
        the 200 ms tick is clear() plus an addNote loop under the lock five
        times a second, which is precisely the velo defect that destroyed a
        recorded take unattended.

        OWNERSHIP IS RE-CHECKED EVERY WRAP, not only at bind time. A player can
        record onto a channel that is already drifting, and the bind-time gate
        cannot see the future; re-checking here means the take is safe the
        moment it exists. The entry is deliberately NOT deleted, so handing the
        channel back with ERASE + Group restores the drift the player set up.

        Writes through apply(), the single write path, so drift is not a second
        writer with rules of its own - which the SP10 design rejected by name."""
        if self._frozen("drift"):
            # FREEZE holds the pattern still, and drift is the half of MOD
            # that rewrites it - which is most of what a player freezes the
            # machine to stop. The modulator entry is left in place, so
            # thawing resumes rather than needing a re-bind.
            return

        if self.owner.get(channel) == "player":
            return
        beats = self._mod_beats()
        moved = False
        for (chan, verb), entry in list(self.mod.items()):
            if chan != channel or not tlib.is_drift(verb):
                continue
            span = self._mod_range(channel, verb)
            if span is None:
                continue
            pos = tlib.mod_pos(entry["phase0"], beats, tlib.MOD_RATES[entry["rate"]])
            wave = tlib.mod_wave(entry["shape"], pos, entry["seed"])
            value = tlib.mod_value(entry["base"], wave,
                                   tlib.mod_depth_scale(entry["depth"],
                                                        self.mod_depth_mult),
                                   span[0], span[1])
            # Integer verbs: a pattern cannot have 3.4 hits.
            before = self.param_get(channel, verb)
            self.apply(channel, verb, int(round(value)))
            if self.param_get(channel, verb) == before:
                continue
            moved = True
        if moved and channel == self.group:
            # REPAINT, or the pads lie. apply() rewrites the pattern but the
            # 30 Hz poll only moves the two playhead pads - a full repaint
            # otherwise waits for a user event, so the steps on the panel would
            # show a pattern that is no longer playing. Only when something
            # actually moved, and only for the channel being looked at: an
            # unconditional repaint here would be sixteen getNoteVelocity calls
            # per wrap per channel for nothing.
            with self.lock:
                self._render_pads()

    def _rewrite_drum(self, channel):
        """Called at a playhead wrap: evolve a DRUM's rhythm register.

        The voice generator applied to drums - reading (b) of the owner's soft
        randomiser. Reading (a), per-step probability, shipped 2026-08-19 and
        is a different control on a different gesture.

        RHYTHM at 0 skips everything, which is why a channel that has never
        been turned up is bit for bit what it was before this existed. The
        register is SUBTRACTIVE against euclid - see _write_pattern - so what
        the knob does is thin the line the euclid encoders drew, never add to
        it.

        Guarded by the SAME predicate as every other pattern-rewriting
        generator. This one needs it most: it rewrites at every wrap, which is
        the path that destroyed a recorded take through the velo defect, and
        it is the reason this feature sat blocked on the list for months."""

        if self.channel_kind(channel) != "drum":
            return
        st = self.state[channel]
        rhythm = int(st.get("rhythm", 0))
        if rhythm <= 0:
            return
        if not tlib.generator_may_write("rhythm", self.frozen, self.freeze_deep,
                                        self.owner.get(channel),
                                        move=self._move_of(channel),
                                        roll=self._move_roll()):
            return
        steps = self._steps(channel)
        st["rhythm_reg"] = self._evolve(channel, int(st.get("rhythm_reg",
                                                           0xFFFF)),
                                        steps, rhythm)
        with self.lock:
            self._write_pattern(channel)

    def _rewrite_voice(self, channel):
        """Called at a playhead wrap.

        RANDOM at 0 skips the rewrite entirely, which is precisely why the
        line being heard is the line kept, bit for bit, for as long as the
        knob stays down. Law L6 is not an approximation here - nothing
        rewrites the pattern, so nothing can change it."""
        # ONE GUARD FOR EVERY PATTERN-REWRITING GENERATOR, 2026-08-31. It was
        # `if self._frozen("melody"): return` and nothing else - the ownership
        # half was enforced further down, inside _write_voice_pattern, which
        # meant the register still walked under a player-owned channel and only
        # the WRITE was refused. Asking here refuses the mutation too, so a
        # recorded take comes back to the line it was recorded over.
        if not tlib.generator_may_write("melody", self.frozen, self.freeze_deep,
                                        self.owner.get(channel),
                                        move=self._move_of(channel),
                                        roll=self._move_roll()):
            return

        st = self.state[channel]
        melody, rhythm = st["random"], st["rhythm"]
        if melody <= 0 and rhythm <= 0:
            return
        steps = lib.step_count(self.div[channel])
        # Both registers are pushed as a pair, so the undo cannot give back a
        # melody while keeping a rhythm that moved at the same wrap.
        tlib.ring_push(st["ring"], (st["register"], st["rhythm_reg"]))
        if melody > 0:
            feed, amount = st.get("feed"), st.get("amount", 0)
            if feed is None or amount <= 0 or feed == channel:
                st["register"] = tlib.mutate(st["register"], st["length"],
                                             melody / 100.0)
            else:
                # CROSS-COUPLING. The source register is read as it stands at
                # the START of this tick and is never written, which is what
                # bounds a cycle: A feeds B feeds A is a real request, and both
                # sides see the pre-tick values, so the pair cannot run away
                # inside one wrap.
                #
                # A channel feeding itself is refused above rather than
                # allowed to be a slow no-op - a control that appears to do
                # nothing is worse than one that refuses.
                src = self.state[feed]
                st["register"] = tlib.mutate_coupled(
                    st["register"], st["length"], melody / 100.0,
                    src.get("register", 0), src.get("length", 8),
                    amount / 100.0)
        if rhythm > 0:
            # Positions survive a full rotation, so this reads as steps
            # appearing and disappearing - never as the pattern sliding
            # sideways. Rotating the melody is a separate request and this
            # must not quietly consume it.
            st["rhythm_reg"] = self._evolve(channel, st["rhythm_reg"],
                                            steps, rhythm)
        if melody > 0 and st.get("model") == tlib.MODEL_WALK:
            # THE WALK EVOLVES HERE AND NOWHERE ELSE. Its line is a pure
            # function of this seed, so this is the one place the walked
            # melody is allowed to change - the same place, and on the same
            # condition, that the register mutates. RANDOM at 0 therefore
            # holds a walked line exactly as it holds a register line, which
            # is the LOCK grammar this instrument already has.
            st["walk_seed"] = (int(st.get("walk_seed", 0)) + 1) & 0xFFFFFFFF
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
        # A pair since 2026-08-16, one register per generator. A bare int is a
        # ring entry from an older snapshot: pitch only, rhythm unchanged.
        if isinstance(previous, (tuple, list)):
            st["register"], st["rhythm_reg"] = previous[0], previous[1]
        else:
            st["register"] = previous
        # Both knobs go to LOCK, not just MELODY: undoing while the rhythm is
        # still evolving would hand back a line whose steps move out from
        # under it on the next wrap, which is not an undo.
        self.apply(channel, "random", 0)
        self.apply(channel, "rhythm", 0)
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
        elif param == "rhythm" and self.channel_kind(channel) == "voice":
            # Setting the evolve RATE writes nothing new by itself - the
            # register is untouched - but the pattern is rewritten so a move
            # off LOCK takes effect on this wrap rather than the next.
            self._write_voice_pattern(channel)
        elif param in ("gate", "octave", "range", "kit_range") and \
                self.channel_kind(channel) == "voice":
            # Timbre-ish, but they only exist in the written notes, so the
            # line has to be rewritten from the unchanged register. Law L2
            # still holds: nothing about the register or the structure moved.
            self._write_voice_pattern(channel)
        elif param == "velo" and self.channel_kind(channel) == "voice":
            self._write_voice_pattern(channel)
        elif param == "lane" and self.channel_kind(channel) == "drum":
            # A constraint that took a bar to be heard would read as a knob
            # that did not work. HITS and the lean rewrite immediately for the
            # same reason.
            with self.lock:
                self._write_pattern(channel)
        elif param == "ratchet" and self.channel_kind(channel) == "drum":
            # The stutter is written into the notes, so it only becomes audible
            # once the pattern is rewritten - exactly like drum VELO below.
            #
            # THE KIND CHECK IS NOT DECORATION. Without it this branch called
            # _write_pattern on a VOICE, and _write_pattern regenerates from
            # euclid hits and rotation - the DRUM generator - so it overwrote
            # the Turing melody with a drum pattern. Latent since RATCHET
            # shipped, because RATCHET only ever lived on the drum STEP page;
            # the ratchet ramp reached all eight channels and woke it up.
            # Heard by the owner on 2026-08-20 as "some melody changed after
            # the roll", and it was.
            #
            # Every neighbouring branch here checks the kind. This one was the
            # exception, and that is exactly the shape of the apply() hole
            # fixed on 2026-08-19: a dispatcher where one arm forgot the
            # question all the others ask.
            with self.lock:
                self._restyle_pattern(channel)
        elif param == "velo" and self.channel_kind(channel) == "drum":
            # Velocity is written into the notes, so it only becomes audible
            # once they are rewritten - but WHICH steps sound does not change,
            # so this restyles in place rather than regenerating from euclid.
            # Turning VELO used to discard every hand-placed step.
            with self.lock:
                self._restyle_pattern(channel)
        elif param in ("rotate", "model", "walk_span", "walk_stride", "feed",
                       "amount") and self.channel_kind(channel) == "voice":
            # THE KIND CHECK IS LOAD-BEARING AND IT IS WHY THIS ARM SITS ABOVE
            # THE hits/rotate ONE. `rotate` is a verb on BOTH kinds, and the
            # arm below regenerates from euclid - the DRUM generator. Reaching
            # it with a voice would overwrite the Turing melody with a drum
            # pattern, which is exactly the latent RATCHET defect documented a
            # few lines up, heard by the owner on 2026-08-20 as "some melody
            # changed after the roll".
            #
            # None of the six touches the register: rotation moves the rendered
            # line, the model chooses which generator renders it, and the
            # coupling pair only takes effect at the next wrap. So a rewrite
            # from the UNCHANGED register is all that is needed, and the line
            # being heard keeps its shape.
            self._write_voice_pattern(channel)
        elif param == "rhythm" and self.channel_kind(channel) == "drum":
            # The drum rhythm register's evolve RATE. Like its voice twin,
            # setting the rate writes nothing by itself - the register is
            # untouched - but the pattern is rewritten so a move off LOCK is
            # audible on this wrap rather than the next.
            with self.lock:
                self._write_pattern(channel)
        elif param in ("hits", "rotate"):
            # THE HOLE THIS FILLED, 2026-08-19. There was no branch here for
            # these two, because the euclid ENCODER path sets self.hits/self.rot
            # directly and calls _write_pattern() itself - so apply() was never
            # the write path for them and nobody noticed, since nothing else
            # moved them. Then drift did, and so did clearing a drift
            # (_mod_clear -> _mod_base_set -> apply), and both showed the value
            # changing on the display while the pattern kept playing the old
            # one. Fixed here rather than at each caller: one place, and the
            # next non-encoder caller inherits it.
            #
            # No double write: _act_euclid does NOT go through apply().
            with self.lock:
                self._write_pattern(channel)

    def channel_kind(self, channel):
        """The kind a channel behaves as: the player's override if set,
        otherwise whatever its chain says."""

        return tlib.resolve_kind(self.kind_override[channel],
                                 self._chain_kind(channel))

    def _page_kind(self, channel, mode=None):
        """The kind that decides which PAGE RING a mode shows.

        CONTROL follows the ENGINE, every other mode follows the BEHAVIOUR.
        They are different questions and conflating them put four dead knobs
        on the screen: SP4 lets a sampler be played by the Turing register,
        and a sampler behaving as a voice was handed the voice CONTROL page -
        a PRESET column plus cutoff, reso, env and decay, none of which
        LinuxSampler publishes. A sampler always has kits and samples however
        it is being played, and that is what CONTROL should show.

        Same principle as 3685f1d, one level up: that made page 1's four synth
        columns resolve from the loaded processor's eng_code rather than the
        CHANNELS table, because the table records what the snapshot loaded.
        This decides WHICH PAGE the same way.

        STEP keeps the behaviour kind - a kit walked by the register wants the
        voice step parameters, which is the whole point of the override."""

        mode = self.mode if mode is None else mode
        if mode == "CONTROL":
            return self._chain_kind(channel)
        return self.channel_kind(channel)

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

    def _gen_engines(self, mode):
        """The engine codes a generated ring is built from.

        Part of the cache key, because the ring describes a plugin: swap the
        synth on a chain from the touchscreen and nothing in the driver's own
        signal path notices, so a ring keyed on (mode, kind, channel) alone
        keeps serving the old plugin's ports until a preset, kit or snapshot
        load happens to clear it. Reading eng_code is two attribute lookups
        and reaches no engine, so it is safe on the MIDI thread."""

        if mode == "CONTROL":
            return getattr(self._voice_processor(self.group), "eng_code", None)
        if mode == "VOLUME":
            # The ganged inserts. This was the ALL ring until 2026-09-01;
            # ALL is the lens now and the globals moved onto VOLUME with them.
            return tuple(getattr(self.fx_handle(0, which), "eng_code", None)
                         for which in ("reverb", "delay"))
        return None

    def _gen_pages(self, mode, kind):
        """Extra pages built from whatever the chain actually publishes.

        CONTROL extras come from the channel's synth processor; ALL extras come
        from the reverb and the delay, ganged. Symbols that already have a
        hand-written home are excluded so no parameter appears twice."""

        channel = self.group if mode == "CONTROL" else -1
        key = (mode, kind, channel, self._gen_engines(mode))
        if key in self.gen_cache:
            return self.gen_cache[key]

        pages = ()
        if mode == "CONTROL" and kind == "voice":
            proc = self._voice_processor(self.group)
            # Whatever page 1 already reaches, resolved the same way page 1
            # resolves it, so no port shows up twice on a swapped-in engine.
            exclude = {sym for sym in (self._voice_symbols(self.group) or ())
                       if sym}
            pages = tlib.generated_pages(self._ports(proc), exclude,
                                         tlib.SHAPE_CHANNEL, tlib.VERB_LV2,
                                         "EXTRA")
        elif mode == "VOLUME":
            for which, table, title in (
                    ("reverb", tlib.FX_REVERB, "REV"),
                    ("delay", tlib.FX_DELAY, "DLY"),
                    # The master insert. No hand-written table to exclude -
                    # nothing else on the surface reaches it, so every port it
                    # publishes is fair game and the pages are built whole
                    # from the plugin.
                    (tlib.FX_MAIN, {}, "MAIN")):
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
            kind = self._page_kind(self.group, mode)
        key = tlib.ring_key(mode, kind)
        return tlib.PAGE_RINGS[key] + self._gen_pages(mode, kind)

    def _page(self):
        """The descriptor showing right now.

        THE ONE PLACE the lens intervenes. Every painter, the encoder
        dispatch, the F row and the label all ask this - so making the lens a
        descriptor here gives it to all of them at once, and none of them has
        to know it exists. That is the whole reason it is a descriptor and not
        a shape of its own: SHAPE_SPREAD already means "one verb over eight
        channels", and a second branch in every reader would be six copies of
        the same question."""

        if self.lens_down:
            verb = self._lens_now()
            if verb is not None:
                return tlib.lens_desc(verb)
        ring = self._ring()
        key = tlib.ring_key(self.mode, self._page_kind(self.group))
        index = tlib.clamp_index(self.page_idx.get(key, 0), len(ring))
        self.page_idx[key] = index
        return ring[index]

    # The state the instrument returns to. STEP because it is the one page
    # that is always true - what the selected channel is playing, with the
    # playhead over it - and page 1 of it because that is where every mode
    # button already lands you.
    HOME_MODE = "STEP"

    # Where a snapshot's retired mode name lands. See _on_snapshot.
    RETIRED_MODES = {"ALL": "VOLUME", "MIXER": "CONTROL", "FILTER": "CONTROL"}

    def _act_home(self):
        """The big encoder's press. Back to the default performance state.

        NAVIGATION, NOT A DELETION. The selected channel stays, every armed
        macro keeps counting, every modulator keeps sweeping, every mute holds
        - law G4 says ERASE is the only word for taking something away, and
        this button does not take anything. It puts the surface back.

        Every latch is dropped - all seven modifiers and both depths of
        FREEZE - because every one of them can hide the step picture, and the
        step picture is what this button is for. The HELD halves are
        deliberately NOT touched: a finger on SHIFT while the other hand hits
        HOME is still a finger on SHIFT, and clearing it here would leave the
        driver's picture disagreeing with the player's hand until they let
        go.

        It also re-anchors the big encoder. That control is absolute with no
        wrap handling in the daemon (main.rs:911), so it yanks its target once
        per revolution; taking the current raw value as the new origin on the
        way past costs nothing and shortens the worst case to one press."""

        self.mode = self.HOME_MODE
        for key in list(self.page_idx):
            self.page_idx[key] = 0
        # THE LATCHES, THROUGH THEIR OWN CLEAR. `lens_latched` and
        # `mod_latched` are read-only properties now, so assigning to them
        # raises AttributeError on the MIDI thread - which py_compile cannot
        # see and which would take the whole surface down on the first press
        # of this button. tlib.latch.clear() drops the latch and DELIBERATELY
        # leaves the hold: a finger still on the button is a fact about the
        # world, and clearing it here would leave the driver's picture
        # disagreeing with the hand until it let go.
        # EVERY LATCH, not the two that latched when this was written. MUTE,
        # DUPLICATE and NAVIGATE all latch since the duration rule went in,
        # and each of them owns the sixteen pads - a latched NAVIGATE makes
        # every pad inert on top of that. So the button whose whole job is to
        # put the surface back was leaving a player in the three states that
        # hide the step picture most completely.
        #
        # The HOLDS are deliberately left alone. A finger still on a button is
        # a fact about the world, and clearing it here would leave the
        # driver's picture disagreeing with the hand until it let go.
        for latch in self.latches.values():
            latch.clear()
        self.frozen = False
        self.freeze_deep = False
        # Re-anchor: the next turn is measured from where the knob is now.
        self._big_last = None
        self._big_carry = 0
        self._invalidate_gen_cache()
        self._recentre_encoders()
        self.enc_carry.clear()
        self._release_all()
        with self.lock:
            self._render_all()
            self._render_display()

    def _act_lens(self, down):
        """ALL. Held is a glance across the eight, latched is a decision to
        work there for a while.

        The same tap/hold measurement every other stateful button on this
        panel uses. A tap toggles the latch; a hold opens it for exactly as
        long as the finger is on it, and the release closes it whatever the
        latch says - so a player who latched it earlier and then holds it is
        making the short decision now, which is what the steady light says.

        It never CHANGES the verb. Which verb the lens spreads is decided by
        the last knob the hand moved, and opening the lens is not moving a
        knob - a lens that reset itself on the way in would need a second
        gesture to get back to what you were just looking at."""

        self._modifier_edge("lens", down)
        # The encoders now address eight channels instead of eight verbs, so
        # the carries belong to the parameter that was under the knob a moment
        # ago - exactly as on a page change.
        self._recentre_encoders()
        self.enc_carry.clear()
        self._render_overlay_leds()
        with self.lock:
            self._render_all()
            self._render_display()

    def _reroll_which(self):
        """Which half of the instrument a reroll would touch.

        THE SELECTED CHANNEL DECIDES, since 2026-09-01. There were two buttons
        and the word came from whichever you pressed; there is one now, and
        the channel under the cursor names its own engine type. `_is_sampler`
        rather than channel_kind on purpose - a drum sampler driven by the
        Turing register is still a sampler, so it answers with the drums."""

        return "pattern" if self._is_sampler(self.group) else "scene"

    def _reroll_targets(self):
        """The channels a reroll would touch right now, live.

        Asked by the handler AND by the light, so the button cannot say one
        thing and do another - the same reason _pad_owner and _column_dead
        each exist exactly once."""

        samplers = {ch: self._is_sampler(ch) for ch in range(8)}
        return tlib.reroll_scope(self._reroll_which(), samplers, self.owner,
                                 self.group, self.shift_down)

    def _act_reroll(self):
        """PATTERN. One button, both kinds - the selected channel decides."""
        self._reroll_press(self._reroll_which())

    def _reroll_press(self, which):
        """One press regenerates, and the SELECTED CHANNEL decides which half.

        ONE BUTTON, both kinds, 2026-09-01. There were two - SCENE for the
        synths and PATTERN for the samplers - and reading reroll_scope made
        the case for merging them stronger than the argument had been: **a
        bare press already ignored which one you pressed.** It takes the
        selected channel either way. The two differed in exactly one
        situation, SHIFT, where the word chose samplers or synths; now the
        selected channel names its own type and SCENE is free surface again.

        A PRESS FIRES IT, since the same day. It used to fire on a RELEASE
        past 250 ms - the fifth grammar for "do a thing" on a panel that
        already had four, and the only one of its kind here. The comment that
        justified it called hold-to-fire "already this instrument's law";
        there was no code behind that sentence, and no other button on the
        surface did it.

        What the hold bought - a window to change your mind - the BAR buys
        instead, and buys better: the label reads REROLL> the instant you
        press, the reroll lands at the wrap, and a SECOND PRESS before the
        wrap takes it back. That is law G3, the same second-press-cancels the
        bank grid and the mute queue already use, so there is nothing new to
        learn and the window is longer than a finger could hold.

        ERASE + the same button is the one-deep UNDO of a reroll that already
        landed. SHIFT widens the scope to every channel of that engine type.
        DUPLICATE's four-deep ring holds registers only, per channel, so it
        neither undoes a reroll nor is flushed by one."""

        if self.erase_down:
            # UNDO moved here from SHIFT, 2026-08-19: SHIFT now means "every
            # channel of this engine type". ERASE is already this
            # instrument's take-it-back modifier - ERASE + Group hands a
            # pattern back, MOD + ERASE clears a modulator - so undo on
            # ERASE + button is the grammar the player already knows.
            self._reroll_undo_apply(which)
            return
        if self._reroll_pending:
            # THE CANCEL WINDOW, and it is the whole reason the hold could go.
            # A second press before the wrap takes the reroll back - law G3,
            # the same gesture the bank grid and the mute queue already use.
            # It cancels everything pending rather than this button's share:
            # the scopes overlap, and a half-cancelled reroll is harder to
            # reason about mid-bar than none.
            self._reroll_pending.clear()
            with self.lock:
                self._render_all()
            return
        targets = self._reroll_targets()
        if not targets:
            # Everything this button owns is player-owned. Say nothing rather
            # than arm an empty gesture; the tabs already show why.
            return
        self._reroll_pending |= set(targets)
        with self.lock:
            self._render_all()

    def _reroll_undo_apply(self, which):
        """Put back what the last reroll on these channels overwrote."""
        restored = False
        for channel in list(self._reroll_undo):
            saved = self._reroll_undo.pop(channel, None)
            if saved is None:
                continue
            for param, value in saved.items():
                self.apply(channel, param, value)
            restored = True
        if restored:
            with self.lock:
                self._render_all()

    def _reroll_channel(self, channel):
        """Fire the pending reroll for one channel, at its own wrap."""
        if self._frozen("reroll"):
            # A pending reroll is HELD, not dropped: the flag stays in
            # _reroll_pending and the tab stays dotted, so thawing fires it at
            # the next wrap. Discarding it would silently eat a gesture the
            # player already made and the surface still shows as coming.
            return

        if channel not in self._reroll_pending:
            return
        self._reroll_pending.discard(channel)
        if self.owner.get(channel) == "player":
            # Re-checked at fire time as well as at arm time: the player can
            # record onto a channel in the bar between the two, and drums have
            # no undo.
            return
        if self.channel_kind(channel) == "voice":
            new = tlib.reroll_voice()
            self._reroll_undo[channel] = {
                "chance": self.param_get(channel, "chance"),
                "rhythm_reg": self.state[channel].get("rhythm_reg", 0xFFFF),
                "random": self.param_get(channel, "random"),
            }
            self.state[channel]["rhythm_reg"] = new["rhythm_reg"]
            self.apply(channel, "chance", new["chance"])
            self.apply(channel, "random", new["random"])
            self._write_voice_pattern(channel)
        else:
            steps = lib.step_count(self.div[channel])
            new = tlib.reroll_drum(steps)
            self._reroll_undo[channel] = {
                "hits": self.param_get(channel, "hits"),
                "rotate": self.param_get(channel, "rotate"),
            }
            self.apply(channel, "hits", new["hits"])
            self.apply(channel, "rotate", new["rotate"])
        if channel == self.group:
            with self.lock:
                self._render_all()

    def _big_encoder(self, cc_val):
        """The big encoder steps the page ring of the mode you are in.

        One job, everywhere, no modifier and no press - owner, 2026-08-19,
        which also withdrew the spread-page additive aggregate that had claimed
        this knob since 2026-08-14. A knob that does one thing everywhere beats
        one that does the right thing in two places and needs a rule to explain
        which.

        _step_page() is already mode-scoped: page_idx is keyed by
        (mode, kind), so "affects the current mode" is what it already did."""

        if self._big_last is None:
            # First report only establishes a reference. Acting on it would
            # step a page from wherever the counter happened to be sitting.
            self._big_last = cc_val
            return
        units = tlib.big_delta(self._big_last, cc_val)
        self._big_last = cc_val
        if not units:
            return
        steps, self._big_carry = tlib.big_detents(self._big_carry + units)
        if not steps:
            return
        if self.lens_down and not self.bank_down and not self.mod_down:
            # THE LENS IS ONE PAGE by construction, so there is no ring to
            # walk and the arrows beside the display are dark for the same
            # reason. Turning the big encoder here used to move the page index
            # of the level UNDERNEATH the lens - invisible while you turned,
            # and a different page waiting when you let go. Law G5 wearing a
            # knob: a control that would do nothing you can see does nothing.
            return
        if self.bank_down:
            # WHILE THE BANK OVERLAY IS HELD the big encoder walks the four
            # pages of sixteen banks - which is the job it does everywhere
            # else on this surface, so nothing new is learned. Clamped, not
            # wrapped: the same law the switch columns follow.
            page = tlib.switch_step(self._bank_page, tlib.BANK_PAGES, steps)
            if page != self._bank_page:
                self._bank_page = page
                with self.lock:
                    self._render_pads()
                    self._render_display()
            return
        if self.mod_down:
            # WHILE MOD IS LATCHED THE BIG ENCODER IS NOT THE PAGE RING. It
            # scales every live modulator's depth at once instead. This is an
            # exception on the most prominent control, so the guide has to
            # state it plainly - MOD's own label already announces MOD is on,
            # so the surface is not silent about it.
            self.mod_depth_mult = max(0.0, min(
                2.0, self.mod_depth_mult + steps * 0.05))
            with self.lock:
                self._render_display()
            return
        for _ in range(abs(steps)):
            self._step_page(1 if steps > 0 else -1)

    def _lens_ring(self):
        """Every verb the lens can hold, for this channel, in panel order.

        All three channel-shaped levels, not just the one showing: the lens
        is answered from a page you have left as often as from the one you
        are on, and an arrow that could only reach the current level would
        make the walk depend on where you happened to be standing."""

        kind = self._page_kind(self.group)
        ring = ()
        for mode in ("CONTROL", "STEP", "AUTO"):
            ring = ring + tuple(self._ring(mode, kind))
        return tlib.lens_verbs(ring)

    def _step_page(self, delta):
        """DL / DR. Wrapping, and it recentres the encoders for the same reason
        a mode change does: the accumulated fraction belongs to the parameter
        that was under the knob a moment ago.

        WHILE THE LENS IS OPEN they step the VERB instead. The lens is one
        page and has no ring, so the arrows would otherwise be dark there -
        this costs no button and no new gesture, and it is what makes "the
        verb your hand last moved" safe: that rule is perfect for the knob you
        were just on and arbitrary for the one you want next."""

        if self.lens_down:
            verbs = self._lens_ring()
            self._lens_verb = tlib.lens_step(self._lens_now(), verbs, delta)
            self._recentre_encoders()
            self.enc_carry.clear()
            with self.lock:
                self._render_all()
                self._render_display()
            return

        ring = self._ring()
        key = tlib.ring_key(self.mode, self._page_kind(self.group))
        index = tlib.clamp_index(self.page_idx.get(key, 0), len(ring))
        self.page_idx[key] = tlib.step_index(index, delta, len(ring))
        self._recentre_encoders()
        self.enc_carry.clear()
        with self.lock:
            self._render_all()

    def _set_mode(self, name):
        """Latched, mutually exclusive, five of them. Pressing the mode that is
        already lit takes you HOME - back to page 1 of that same mode - rather
        than switching you anywhere.

        It used to bounce you to CONTROL instead, which meant a mode button did
        two different things depending on state, and losing your place was the
        price of a mis-hit. Now every mode button means the same thing twice
        over: 'this mode, from the top'.

        The mode buttons are deliberately NOT subject to the tap/hold law - a
        momentary mode is a mode you cannot two-hand."""

        # A MODE PRESS DROPS THE LATCHED LENS, whichever branch it takes.
        # Without this the lens outranks the mode - _page() returns it
        # whatever self.mode says - so pressing a mode button while the lens
        # was latched moved the mode LED and changed nothing else. A lit
        # button that does nothing is the worst object this surface can
        # produce, and the most ordinary gesture on the panel produced it.
        #
        # BEFORE the same-mode test, so "press the mode you are in" gets you
        # out of the lens too. That press means "this mode, from the top",
        # and the top is not somebody else's page.
        #
        # Only the LATCH: a finger physically on ALL is a fact about the
        # world, and that hold ends when the finger leaves.
        lens_was_open = self.latches["lens"].latched
        self.latches["lens"].clear()

        if name == self.mode and not lens_was_open:
            # Home: page 1 of the ring this mode shows for this channel kind.
            # Keyed through tlib.ring_key, exactly as _page and _step_page do -
            # a hand-rolled tuple would miss the entry they actually use and
            # this would silently do nothing.
            key = tlib.ring_key(name, self._page_kind(self.group, name))
            if self.page_idx.get(key, 0) != 0:
                self.page_idx[key] = 0
                self._invalidate_gen_cache()
                self._recentre_encoders()
                self.enc_carry.clear()
                with self.lock:
                    self._render_all()
            return
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
            self.state[channel]["preset"] = str(presets[index][2])
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
        self.state[channel]["preset"] = str(presets[index][2])
        self._invalidate_gen_cache()
        with self.lock:
            self._render_display()

    def _voice_symbols(self, channel):
        """The four page-1 symbols (CUTOFF, RESO, ENV, DECAY) for whatever this
        channel is actually running, or None when it runs nothing.

        Resolved from the processor's own eng_code, not from CHANNELS[channel],
        because the table records what the snapshot loaded: swap a chain's
        synth on the touchscreen and the table still names the old plugin, so
        the four knobs address symbols nothing publishes and page 1 goes dead
        with no explanation. Gate G2's measured table still wins for the three
        engines it covers; anything else is matched against the ports the
        plugin publishes.

        Cached by engine code - the ports of a plugin are a property of the
        plugin - so the port scan costs nothing at render rate."""

        proc = self._voice_processor(channel)
        if proc is None:
            return None
        eng_code = getattr(proc, "eng_code", None)
        if eng_code is None:
            return tlib.voice_symbols(None, self._ports(proc))
        if eng_code not in self.sym_cache:
            self.sym_cache[eng_code] = tlib.voice_symbols(
                eng_code, self._ports(proc))
        return self.sym_cache[eng_code]

    def _set_voice_ctrl(self, channel, column, value):
        """0-127 on the surface onto whatever range the engine's control has.

        A role the loaded plugin has no symbol for leaves the knob dead rather
        than silently moving something else - law L4."""

        symbols = self._voice_symbols(channel)
        if not symbols or symbols[column] is None:
            return
        proc = self._voice_processor(channel)
        if proc is None:
            return
        zctrl = proc.controllers_dict.get(symbols[column])
        if zctrl is None:
            logging.debug(f"Maschine: {getattr(proc, 'eng_code', '?')} has no "
                          f"'{symbols[column]}'")
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

        if which == tlib.FX_MAIN:
            # THE MAIN CHAIN IS NOT REACHABLE THE ORDINARY WAY. Everything
            # below resolves through midi_chan_2_chain_ids, and Main's
            # midi_chan is None - so chain 0 is invisible to every existing
            # fx resolver and needs this branch rather than a second function.
            # The KEYING needed nothing: _mod_key already returns (None, verb)
            # for a global verb.
            chain = self.chain_manager.chains.get(0)
            if chain is None:
                return None
            for proc in chain.get_processors():
                name = getattr(proc.engine, "name", "") if proc.engine else ""
                if "RezFilter" in str(name):
                    return proc
            return None
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
        self._slog("session", event="init", path=SESSION_LOG_PATH)
        super().init()
        # Before any zynseq call: take the bank rather than follow it.
        self._pin_bank()
        self._slog("bank", event="pin", bank=self.bank)
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
        # Decided once, on the machine that will run the call. Not in __init__:
        # libseq is only reliably usable once the driver is bound.
        self.has_step_chance = self._probe_step_chance()
        self.has_stutter = self._probe_stutter()
        self.stopping.clear()
        self.playhead_thread = Thread(
            target=self._playhead_loop, name="maschine_mk2_playhead", daemon=True)
        self.playhead_thread.start()
        # A SECOND THREAD, and it has to be one: the fault it watches for is
        # the poll thread BLOCKING, so nothing the poll thread runs could ever
        # notice it. It does no zynseq work and takes no lock - the blocked
        # thread may be holding one - so it cannot itself become the fault.
        self.watchdog_thread = Thread(
            target=self._watchdog_loop, name="maschine_mk2_watchdog",
            daemon=True)
        self.watchdog_thread.start()

    def end(self):
        self.stopping.set()
        if self.playhead_thread:
            self.playhead_thread.join(timeout=1.0)
            self.playhead_thread = None
        if self.watchdog_thread:
            self.watchdog_thread.join(timeout=1.0)
            self.watchdog_thread = None
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
            if self.libseq.getPlayMode(self.bank, grp) != zynseq_lib.SEQ_LOOP:
                self.libseq.setPlayMode(self.bank, grp, zynseq_lib.SEQ_LOOP)

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

    def _saved_param(self, channel, verb, live):
        """What the snapshot should record for a parameter.

        A modulated parameter's live value is wherever the LFO happened to be
        when the snapshot was taken. The base is what the player set, and it
        is the only value worth restoring - the modulator is saved separately
        and will start sweeping from it again.

        INERT TODAY, kept on purpose. Its only callers are gate and velo, and
        neither is modulatable any more: both are written by regenerating the
        whole pattern, so an LFO on either rewrote the pattern every 200 ms
        and erased a player-owned take. If either verb ever becomes
        modulatable again this is the guard that stops a saved snapshot
        recording a sweep position instead of the value the player dialled
        in - and it costs one dict lookup per save."""

        entry = self.mod.get(self._mod_key(channel, verb))
        return live if entry is None else entry["base"]

    def get_state(self):
        """What the snapshot must carry that nothing else owns.

        Patterns, chance, swing, mixer levels, mutes and the insert wets all
        live in objects that are already saved. The Turing registers and their
        undo rings do not - they exist only here, and a snapshot without them
        restores a machine that plays different music. Persisted from day one
        deliberately: adding it later leaves every existing snapshot missing
        it, with no way to tell."""
        # Instrumented for the persistence check: what the driver hands the
        # snapshot on the way out, against what it is handed on the way back
        # in. A value that is right here and wrong in set_state is a LOAD
        # bug, and from the surface the two are the same symptom.
        self._slog("snapshot", dir="save")

        # Once, outside the comprehension below: it takes the lock for a
        # tempo read, and asking eight modulators for it eight times would
        # take the lock eight times for one answer.
        beats = self._mod_beats()
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
            # SP10: modulators. Their own key, and saved from the first
            # version deliberately - adding it later leaves every existing
            # snapshot missing it with no way to tell.
            #
            # PHASE IS SAVED. Spread pages give eight independent LFOs whose
            # phase comes from bind time; without the phase they all come back
            # in lockstep and a saved jam does not sound like the saved jam.
            #
            # BASE IS SAVED. It is the driver's own truth: the chain holds
            # wherever the LFO happened to be at save time, which is not the
            # value the player dialled in.
            # The GLOBAL depth multiplier, saved beside the modulators it
            # scales rather than inside them - the stored depths stay the
            # player's own numbers, so a snapshot saved at multiplier 0 still
            # carries every depth it had.
            "mod_depth_mult": self.mod_depth_mult,
            "mods": {
                f"{'' if ch is None else ch}|{verb}": {
                    "depth": e["depth"], "rate": e["rate"],
                    "shape": e["shape"],
                    # The phase saved is the phase RIGHT NOW, not the phase0
                    # the modulator was bound with.
                    #
                    # WHAT ACTUALLY HAPPENS ON LOAD: the beat clock does NOT
                    # restart. self._t0 is set once, at construction, and
                    # set_state never touches it - so a restored phase0 is
                    # immediately advanced by however many beats have elapsed
                    # since the driver started, and no modulator resumes at
                    # the exact phase it was saved at. What survives is the
                    # RELATIVE scatter between modulators running at the same
                    # rate, because they all advance by the same amount, and
                    # that scatter is the thing worth keeping: it is why eight
                    # spread-page LFOs chase each other rather than breathing
                    # together. Saving the bind-time offset instead would lose
                    # even that.
                    "phase0": tlib.mod_pos(
                        e["phase0"], beats,
                        tlib.MOD_RATES[e["rate"]]) % 1.0,
                    "base": e["base"], "seed": e["seed"],
                }
                # list() because this iterates on whichever thread is saving
                # while the MIDI thread can bind or clear a modulator: a bare
                # .items() raises RuntimeError: dictionary changed size during
                # iteration, and takes the whole snapshot save with it.
                for (ch, verb), e in list(self.mod.items())
            },
            # The seed counter itself. Without it a load restarts it at 0 and
            # the next bind collides with a restored entry's seed - two
            # sample-and-holds on the same rate would then step in lockstep,
            # which is the one thing the seed exists to prevent.
            "mod_seed": self.mod_seed,
            "voices": {
                str(i): {
                    "register": self.state[i]["register"],
                    "ring": list(self.state[i]["ring"]),
                    "length": self.state[i]["length"],
                    "random": self.state[i]["random"],
                    # SP10: gate and velo are NOT modulatable - both are
                    # written by regenerating the pattern, so an LFO on
                    # either rewrote the whole pattern every 200 ms.
                    # _saved_param is therefore inert here and simply returns
                    # the live value; it stays as the guard that would keep a
                    # snapshot honest if either verb ever became modulatable
                    # again. See its docstring.
                    "gate": self._saved_param(i, "gate", self.state[i]["gate"]),
                    "octave": self.state[i]["octave"],
                    "range": self.state[i]["range"],
                    # SP8's kit window. .get with a default so a channel whose
                    # state predates SP8 saves the compatible value rather than
                    # raising on the save path.
                    "kit_range": self.state[i].get("kit_range", 4),
                    "velo": self._saved_param(i, "velo", self.state[i]["velo"]),
                    "rhythm": self.state[i]["rhythm"],
                    "rhythm_reg": self.state[i]["rhythm_reg"],
                    # P1, 2026-08-31. .get with a default on every one, for
                    # the reason the kit window already gives above: a channel
                    # whose state predates these must SAVE the compatible
                    # value rather than raise on the save path.
                    "model": self.state[i].get("model",
                                               tlib.MODEL_REGISTER),
                    # RULE, 2026-09-01. Same .get-with-a-default rule: a
                    # channel whose state predates the verb saves `rand`,
                    # which is what it was doing anyway.
                    "rule": self.state[i].get("rule", tlib.RULE_RANDOM),
                    # MOVE and EXIT, 2026-09-01. Both are the player's
                    # arrangement decisions about this channel - how much the
                    # machine may touch it, and how it leaves - and a snapshot
                    # that lost them would come back with the machine free to
                    # move a channel that had been locked.
                    "move": self.state[i].get("move", 100),
                    "exit": self.state[i].get("exit", 0),
                    "walk_span": self.state[i].get("walk_span", 32),
                    "walk_stride": self.state[i].get("walk_stride", 4),
                    # The walked line IS this number - it is the walk's
                    # register. Without it a snapshot restores the span and
                    # the stride and still comes back playing a different
                    # melody.
                    "walk_seed": self.state[i].get("walk_seed", 0),
                    # THROUGH param_get, NOT the state dict. `rotate` lives in
                    # the legacy array self.rot, so reading self.state here
                    # saved 0 for every channel on every snapshot ever written
                    # - found 2026-08-31 while fixing the same shape in the
                    # encoder and the renderer.
                    "rotate": self.param_get(i, "rotate"),
                    "feed": self.state[i].get("feed"),
                    "amount": self.state[i].get("amount", 0),
                }
                # SP4: keyed on how the channel BEHAVES, not on the table. A
                # drum chain switched to voice holds register, gate and octave
                # that exist nowhere else - the table would have dropped them
                # on save and the take would come back as a drum.
                for i, ch in enumerate(tlib.CHANNELS)
                if self.channel_kind(i) == "voice" and "register" in self.state[i]
            },
            # THE DRUM RHYTHM REGISTER HAS TO BE SAVED, and nothing like this
            # block existed before - "voices" is voice-only by design. Without
            # it an evolved drum comes back at 0xFFFF, which is the FULL euclid
            # line: the pattern in the snapshot is the thinned one, so the
            # channel would come back thicker than it was saved, and the
            # surface would read RHYTHM at whatever the knob said. That is the
            # CHANCE/SWING law exactly - a mirrored property defaulted instead
            # of read back, and a channel that sounds different from the one
            # that was saved with nothing to explain it.
            "drums": {
                str(i): {
                    "rhythm": self.state[i].get("rhythm", 0),
                    "rhythm_reg": self.state[i].get("rhythm_reg", 0xFFFF),
                    # HITS TRAVELS WITH THE REGISTER. Once the register thins
                    # the line, _recount_hits refuses to read HITS back out of
                    # the pattern - so the snapshot has to carry the number the
                    # euclid generator was actually given, or a load would
                    # resume from whatever the driver happened to hold.
                    "hits": self.hits[i],
                    # LEAN, 2026-09-01. .get with a default for the reason
                    # every field above has one: a channel whose state
                    # predates the verb saves euclid, which is what it was
                    # doing anyway.
                    "lean": self.state[i].get("lean", tlib.LEAN_OFF),
                    "lane": self.state[i].get("lane", 0),
                    "move": self.state[i].get("move", 100),
                    "exit": self.state[i].get("exit", 0),
                    "rule": self.state[i].get("rule", tlib.RULE_RANDOM),
                    "phrase": self.state[i].get("phrase", 1),
                    "fill": self.state[i].get("fill", 0),
                }
                for i, ch in enumerate(tlib.CHANNELS)
                if self.channel_kind(i) == "drum"
            },
        }

    def set_state(self, state):
        self._slog("snapshot", dir="load",
                   keys=sorted(state) if isinstance(state, dict) else None)
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
        # A snapshot written before 2026-09-01 names a mode that no longer
        # exists. Map it to where its pages went rather than dropping the
        # player somewhere arbitrary: ALL held the globals and they are on
        # VOLUME, while MIXER and FILTER were spreads of LEVEL and CUTOFF and
        # both of those verbs live on the CONTROL page now - one lens press
        # from the eight-channel view they used to be.
        self.mode = self.RETIRED_MODES.get(self.mode, self.mode)
        if self.mode not in tlib.MODES:
            self.mode = self.HOME_MODE
        self.page_idx = {}
        for key, index in (state.get("pages") or {}).items():
            mode, _, kind = str(key).partition("|")
            if mode in tlib.MODES and isinstance(index, int):
                self.page_idx[(mode, kind or None)] = index
        selected = state.get("selected", self.group)
        if isinstance(selected, int) and 0 <= selected < 8:
            self.group = selected
            # Same trap as _select_group, and this is the route that actually
            # bit: a snapshot restoring group H while the daemon sat at the
            # base it booted with. The poll thread sends it - set_state runs
            # on the manager's thread and must not touch the socket.
            self._note_base_due = True

        for key, who in (state.get("owners") or {}).items():
            try:
                channel = int(key)
            except (TypeError, ValueError):
                continue
            if channel in self.owner and who in ("gen", "player"):
                self.owner[channel] = who

        # SP10: modulators. Validated rather than trusted - the lesson of
        # 2026-08-11, when CHANCE and SWING were assumed on load and a channel
        # saved at chance 0 came back silent while the surface read 100. A
        # verb that is no longer modulatable, an unknown shape, an
        # out-of-range rate, a non-dict entry, a zero depth or an unparseable
        # channel is dropped here, never held.
        self.mod = {}
        # Any restore still owed belongs to the OUTGOING snapshot. Applying it
        # after this load would write a stale base over a value the snapshot
        # just restored.
        self._mod_restore_due = []
        # Read with a DEFAULT rather than through an upgrade path: a snapshot
        # written before this key existed simply restores at 1.0, which is the
        # unity multiplier and exactly what those snapshots meant. Validated
        # rather than trusted, for the reason CHANCE and SWING were - a
        # hand-edited value must not reach the poll thread unchecked.
        mult = state.get("mod_depth_mult", 1.0)
        self.mod_depth_mult = (float(mult) if isinstance(mult, (int, float))
                               and 0.0 <= mult <= 2.0 else 1.0)

        for key, entry in (state.get("mods") or {}).items():
            chan_s, _, verb = str(key).partition("|")
            if not verb or not tlib.mod_allowed(verb):
                # A verb that is no longer modulatable is dropped, not held.
                # Never hold a binding that cannot be resolved.
                continue
            try:
                channel = None if chan_s == "" else int(chan_s)
            except (TypeError, ValueError):
                continue
            if not isinstance(entry, dict):
                continue
            shape = entry.get("shape")
            rate = entry.get("rate")
            if shape not in tlib.MOD_SHAPES:
                continue
            if not isinstance(rate, int) or not 0 <= rate < len(tlib.MOD_RATES):
                continue
            depth = entry.get("depth", 0)
            if not isinstance(depth, int) or depth == 0:
                continue
            base = entry.get("base")
            # The base is arithmetic on every single tick. A None or a string
            # out of a hand-edited snapshot raises inside _mod_write, and
            # _playhead_loop's except-and-return then kills the playhead, the
            # kit and preset commits, the volume poll, the display refresh AND
            # all modulation for the rest of the session - one bad character
            # in a JSON file taking the whole instrument silent.
            if isinstance(base, bool) or not isinstance(base, (int, float)):
                continue
            if base != base or base in (float("inf"), float("-inf")):
                continue
            # _mod_key, not the parsed pair: a snapshot written before `fx:`
            # verbs were keyed globally carries a real channel on one, and it
            # has to normalise to None here or it comes back invisible.
            self.mod[self._mod_key(channel, verb)] = {
                "depth": max(-tlib.MOD_DEPTH_MAX,
                             min(tlib.MOD_DEPTH_MAX, depth)),
                "rate": rate,
                "shape": shape,
                "phase0": float(entry.get("phase0", 0.0)),
                "base": base,
                "seed": int(entry.get("seed", 0)),
            }
        # The seed counter. Restored, and floored at the highest seed actually
        # in use - _mod_encoder increments before it reads, so the next bind
        # lands one past every restored entry. The floor is what makes a
        # snapshot written before this key existed safe too: without it the
        # counter restarted at 0 and the next bind handed out a seed a
        # restored modulator already held, and two sample-and-holds on the
        # same rate then step as one, which is what the seed exists to stop.
        saved_seed = state.get("mod_seed")
        self.mod_seed = saved_seed if isinstance(saved_seed, int) else 0
        for entry in self.mod.values():
            self.mod_seed = max(self.mod_seed, entry["seed"])
        # A pointer into a dict that was just rebuilt from scratch is
        # meaningless - MOD+pad has nothing held down across a snapshot load.
        self.mod_last = None

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
                if isinstance(value, dict) and name in tlib.KINDS:
                    # NOT a verbatim copy. A stash written before the rhythm
                    # generator is short `rhythm` and `rhythm_reg`, and
                    # _toggle_kind pulls it straight into self.state, where
                    # columns() indexes both directly. The KeyError lands on
                    # the playhead poll thread and used to end it - every
                    # generator stopped for the rest of the session with
                    # nothing on the surface saying so, measured 2026-08-18.
                    #
                    # The `voices` block below has always upgraded its dicts.
                    # This one restored them as they were saved, so the
                    # ALTERNATE kind kept whatever key set the snapshot was
                    # written with until a SHIFT+GRID pulled it into service.
                    #
                    # self.div is the outgoing snapshot's division here -
                    # _derive_params runs further down - which is the same
                    # approximation the `voices` block makes for the same
                    # seed. It decides a stashed rhythm register for a kind
                    # nobody is playing; _toggle_kind rewrites the pattern the
                    # moment it becomes real.
                    value = tlib.upgrade_state(
                        name, value, lib.step_count(self.div[channel]))
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
                          "range", "kit_range", "velo", "rhythm", "rhythm_reg",
                          "model", "rule", "walk_span", "walk_stride",
                          "walk_seed", "feed", "amount", "move", "exit",
                          "phrase", "fill"):
                if field in saved:
                    st[field] = saved[field]
            if "rotate" in saved:
                # INTO THE LEGACY ARRAY. `rotate` was in the list above until
                # 2026-08-31, which put it in self.state where param_get never
                # looks - so a restored rotation was dead data and the driver
                # kept whatever rotation was last on the panel.
                #
                # It cannot be derived instead: _derive_params says so in its
                # own docstring - "Rotation is not recoverable from a pattern -
                # it stays at whatever the driver last set." The notes come
                # back rotated because they were WRITTEN rotated, so without
                # this the surface and the pattern disagree until the next
                # regeneration, which then jumps the pattern to the stale
                # value.
                #
                # Clamped here rather than trusted: a snapshot saved at a
                # longer division carries a rotation this pattern has no room
                # for.
                self.rot[channel] = max(
                    0, min(max(0, self._steps(channel) - 1),
                           int(saved["rotate"])))
            if "rhythm_reg" not in saved:
                # A snapshot from before the rhythm generator. Seed its
                # register from the mask its DENSITY would have produced, so
                # it sounds IDENTICAL - same function, same inputs, not an
                # approximation. `rhythm` stays 0: a snapshot made before
                # rhythm evolution existed was not evolving its rhythm.
                #
                # This is the CHANCE/SWING law applied BEFORE it bites. Those
                # two were defaulted rather than read back, and a channel
                # saved at chance 0 came back silent while the surface read
                # 100 - silence with nothing to explain it.
                st["rhythm_reg"] = tlib.rhythm_seed(
                    st["register"], st["length"],
                    lib.step_count(self.div[channel]),
                    saved.get("density", 100))
            st["ring"] = deque(saved.get("ring", []), maxlen=4)

        for key, saved in (state.get("drums") or {}).items():
            try:
                channel = int(key)
            except (TypeError, ValueError):
                continue
            if channel not in self.state:
                continue
            # ABSENT IS NOT ZERO. A snapshot from before the drum rhythm
            # register carries no "drums" block at all, and the default it
            # falls back to is 0xFFFF - every step of the euclid line
            # sounding, which is what that snapshot was written with. Reading
            # a missing key as 0 would silence every drum channel in every
            # existing snapshot on load.
            self.state[channel]["rhythm"] = saved.get("rhythm", 0)
            self.state[channel]["rhythm_reg"] = saved.get("rhythm_reg", 0xFFFF)
            # ABSENT IS EUCLID, and absent is the shift register - the same
            # argument as the line above. A snapshot written before these
            # generators existed was played by the ones they default to.
            self.state[channel]["lean"] = saved.get("lean", tlib.LEAN_OFF)
            # ABSENT IS THE RAW FIELD - a snapshot written before the lane
            # existed was played without one.
            self.state[channel]["lane"] = saved.get("lane", 0)
            # ABSENT IS THE OLD BEHAVIOUR on both: the machine could move any
            # channel, and a queued mute landed hard.
            self.state[channel]["move"] = saved.get("move", 100)
            self.state[channel]["exit"] = saved.get("exit", 0)
            self.state[channel]["phrase"] = saved.get("phrase", 1)
            self.state[channel]["fill"] = saved.get("fill", 0)
            self.state[channel]["rule"] = saved.get("rule", tlib.RULE_RANDOM)
            if "hits" in saved:
                self.hits[channel] = int(saved["hits"])

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

        if evtype == 0xA:                        # PolyphonicPressure
            # STORE AND RETURN. Nothing else may happen here: this is the MIDI
            # thread, midi_event holds the lock for the whole event, and the
            # daemon can deliver one of these per held pad every 25 ms. The
            # poll thread does the writing, exactly as it does for the LFO.
            return self._pad_pressure(ev[2])

        if evtype in (0x8, 0x9):                 # NoteOff and NoteOn
            step = ev[1] - GROUP_NOTE_BASE[self.group]
            if not 0 <= step < 16:
                # A pad that decodes out of range is the Group-rebase desync:
                # the daemon re-bases the pads on every Group press and the
                # driver's idea of the base drifts, so presses vanish with no
                # sound and no log. Never gated - it is rare and it is the
                # single most misleading failure this surface has.
                self._slog("pad", result="out of range", note=ev[1],
                           group=self.group, base=GROUP_NOTE_BASE[self.group])
                return False
            if evtype == 0x8 or ev[2] == 0:
                # A release. In STEP mode nothing is ever held, so the pop
                # inside _pad_up finds nothing and this is a no-op.
                self._pad_up(step)
                return True
            if self.shift_down:
                # Ahead of MOD and of the STEP branch, in that order, for the
                # same reason MOD is ahead of STEP: in STEP mode a bare pad hit
                # toggles the step, so intercepting any lower would let
                # SHIFT + pad silently edit the pattern instead of setting a
                # probability. SHIFT outranks MOD because MOD LATCHES - a
                # momentary gesture takes the pads from a latched state and
                # hands them back on release (owner, 2026-08-19).
                self._shift_pad(step)
                return True
            if self._pad_owner() == "bank":
                # Above MUTE, which is OVERLAY_PRIORITY's order: launching a
                # whole arrangement outranks muting one channel.
                self._bank_pad(step)
                return True
            if self._pad_owner() == "mute":
                self._mute_pad(step)
                return True
            if self._pad_owner() == "arm":
                # Between SHIFT and MOD, which is OVERLAY_PRIORITY's order and
                # not a coincidence: SHIFT is the oldest and most-used binding
                # and must not move, and a player holding ARM has committed to
                # scheduling, so it outranks MOD. Ahead of the STEP branch for
                # the same reason MOD is - a pad under a modifier must never
                # fall through and silently edit the pattern.
                #
                # Asked through _pad_owner, not through self.arm_down, so the
                # MOD+ARM chord goes to the MOD legend instead of here.
                self._arm_pad(step)
                return True
            if self.mod_down:
                # Ahead of the STEP branch deliberately. In STEP mode a pad
                # hit goes to _toggle_step, so intercepting further down in
                # _pad_down would let MOD+pad silently edit the pattern
                # instead of setting a rate - a destructive surprise from a
                # gesture that is supposed to be inert.
                self._mod_pad(step)
                return True
            if self._pad_owner() == "navigate":
                # AN OVERLAY TAKES THE PADS WHOLE, 2026-09-01. NAVIGATE was
                # the one that did not: it painted the phrase over the sixteen
                # pads and then let a press fall through to _toggle_step or
                # _pad_down, so a pad showing bar 11 of a phrase silently
                # edited step 11 of a pattern. Five overlays taught "a
                # modifier changes what a pad DOES" and this one taught "a
                # modifier changes what a pad SHOWS", which is not a rule a
                # player can hold two of.
                #
                # It is a page to READ, so its pads are inert - the same
                # answer ARM's countdown ruler already gives, for the same
                # reason: reading something must not also change it.
                self._slog("pad", result="inert", overlay="navigate",
                           step=step)
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
            if cc_num == CC_BIG_TURN:
                # Ahead of the press-only filter for the same reason the eight
                # encoders are: this carries a POSITION, and `down = cc_val ==
                # 127` would throw every value away. CC 15 could never satisfy
                # that test anyway - it maxes at 120, which is why the knob has
                # been inert rather than broken.
                self._big_encoder(cc_val)
                return True
            self._slog("cc", num=cc_num, val=cc_val,
                       name=tlib.BUTTONS_STATEFUL.get(cc_num),
                       owner=self._pad_owner(),
                       frozen=self._frozen("macro"))
            down = cc_val == 127
            # Buttons that carry state across press and release come first:
            # the press-only filter below throws releases away, and for a
            # momentary gesture the release IS the event.
            action = tlib.BUTTONS_STATEFUL.get(cc_num)
            # ERASE + SELECT: cancel everything armed. Caught HERE rather than
            # inside _act_arm so the modifier never opens - the ARM overlay
            # taking the pads for the length of a panic gesture is exactly the
            # wrong answer, and law G4 wants the cancellation to look like
            # every other cancellation on the panel.
            if (action == "arm" and down and self.erase_down):
                self._cancel_all_pending()
                self._chord_swallowed.add(cc_num)
                return True
            # MOD + ERASE + ALL drops every modulator. Three keys and two of
            # them modifiers, because it is destructive and nothing
            # destructive happens on a single press.
            #
            # CAUGHT HERE, NOT BELOW, since ALL became the lens on
            # 2026-09-01. It used to sit under the press-only filter and
            # therefore AFTER the mode dispatch that also owned CC 38: the
            # chord cleared the modulators and then fell through, so the
            # player also landed in a mode they had not asked for.
            # button_conflicts() could not see it - it compares tables, and
            # this was a special case above them.
            if (action == "lens" and down and self.mod_down
                    and self.erase_down):
                self._mod_clear_all()
                self._chord_swallowed.add(cc_num)
                return True
            # THE RELEASE OF A SWALLOWED PRESS IS SWALLOWED TOO. Without this
            # the chord ate the press and the release still reached
            # latch.edge(), which measured it against the timestamp of some
            # EARLIER, unrelated press - and if that was under the threshold,
            # flipped the latch. A panic gesture that occasionally leaves an
            # overlay latched behind it is worse than no panic gesture.
            if not down and cc_num in self._chord_swallowed:
                self._chord_swallowed.discard(cc_num)
                return True
            if action is not None:
                getattr(self, "_act_" + action)(down)
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
            action = tlib.BUTTONS_PRESS.get(cc_num)
            if action is not None:
                getattr(self, "_act_" + action)()
                return True
            group = cc_num - GROUP_CC_FIRST
            if 0 <= group < 8:
                if self.arm_down:
                    # SURVIVORS, not mutes. The Group buttons are free while
                    # ARM is held because ARM claims only the PADS - different
                    # controls under the same modifier, no conflict.
                    #
                    # Ahead of the ERASE branch: ARM+ERASE+Group is not a
                    # gesture, and if a player finds it the nomination is the
                    # safer of the two to win, since silencing a channel from
                    # inside a scheduling gesture is a surprise.
                    if group in self._drop_survivors:
                        self._drop_survivors.discard(group)
                    else:
                        self._drop_survivors.add(group)
                    # PUT THE PAD BASE BACK - but from the POLL THREAD, not
                    # here. The daemon re-bases the pads on every Group press
                    # unconditionally and on BOTH EDGES, whatever we do with
                    # the button, and Group buttons reach this driver on the
                    # press only - so a correction sent here is overwritten by
                    # a release we never see. Left unfixed, its idea of the
                    # pads and ours point at different octaves and every later
                    # pad press decodes out of range and is dropped WITHOUT A
                    # SOUND OR A LOG. Found by the owner on 2026-08-20:
                    # nominating drop survivors killed the ARM grid itself.
                    self._note_base_due = True
                    with self.lock:
                        self._render_groups()
                    return True
                if self.erase_down:
                    # Same trap as the ARM branch above, and this one has been
                    # here since ERASE + Group shipped.
                    self._note_base_due = True
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

    # --- button actions -------------------------------------------------
    #
    # One method per entry in techno_lib.BUTTONS_*. Stateful actions take
    # `down`; press-only actions take none. Keeping them as methods rather
    # than inline lambdas is what makes the table swappable later (SP9).

    def _act_arm(self, down):
        """ARM composes a macro and a length and lands it on a bar.

        HELD OR LATCHED, like every other modifier - the duration rule. A tap
        used to CANCEL everything pending, which meant the only way to read
        the countdown ruler was to hold down the button that destroyed what
        you were reading. Two fixes were made to that before the right one:
        first any release cancelled, then only a release under 250 ms did.

        The right one is that cancelling is not this button's job. It is
        ERASE + SELECT now, on the modifier that means taking away everywhere
        else on the panel, and it rhymes with the surgical version that
        already existed on the PENDING page.

        The pick is cleared on press rather than on release so a second hold
        starts from nothing. Leaving it set would let a bare length tap re-arm
        a macro the player composed a minute ago."""

        self._modifier_edge("arm", down)
        if down:
            self._arm_picked = None
            self._render_overlay_leds()
            with self.lock:
                self._render_pads()
                self._render_display()
            return
        # A TAP NOW LATCHES, like every other modifier on this panel. The
        # cancel-everything gesture that used to live on it moved to
        # ERASE + SELECT - which is where it belonged all along, because ERASE
        # is this surface's one word for taking something away, and because it
        # now rhymes with the surgical version on the PENDING page:
        # ERASE + SELECT kills all of them, ERASE + the encoder under a column
        # kills that one.
        self._arm_picked = None
        self._render_overlay_leds()
        with self.lock:
            self._render_all()

    def _cancel_all_pending(self):
        """ERASE + SELECT: everything armed, gone. Returns True if it did.

        CANCEL-ALL rather than cancel-one, and that is deliberate rather than
        lazy: a half-cancelled gesture is harder to reason about mid-bar than
        none at all, and the surgical version already exists on the PENDING
        page for when the player wants it."""

        if not (self._pending_macros.pending() or self._armed_while_stopped):
            return False
        self._pending_macros.clear()
        self._armed_while_stopped.clear()
        self._arm_bars.clear()
        self._slog("arm", result="cancel_all")
        with self.lock:
            self._render_all()
        return True

    def _arm_pad(self, step):
        """A pad while ARM is held: 0-1 pick the macro, 8-15 the length.

        Pads 2-7 are DARK and do nothing - a lit pad that does nothing is the
        fault this surface must never commit, so they are not lit either.
        They are where the later payloads land.

        While something is pending the grid is the COUNTDOWN RULER, not a
        picker. Reading it must not also change it, so every pad is inert."""

        if self._pending_macros.pending() or self._armed_while_stopped:
            self._slog("arm", result="inert", step=step,
                       pending=self._pending_macros.pending(),
                       stopped=list(self._armed_while_stopped))
            return
        if step < len(tlib.ARM_MACROS):
            self._arm_picked = tlib.ARM_MACROS[step]
            self._slog("arm", result="picked", step=step,
                       macro=self._arm_picked)
        elif step >= 8:
            if self._arm_picked is None:
                # A length with nothing to arm. Deliberately silent rather
                # than guessing a macro: guessing would fire something the
                # player never named.
                return
            bars = tlib.ARM_LENGTHS[step - 8]
            if self._phrase_anchor is None:
                # Stopped: the clock does not advance, so an absolute target
                # bar would be a lie. Keep the LENGTH only; _act_play computes
                # the landing bar at transport start. Nothing fires the
                # instant it is armed and nothing is lost.
                self._armed_while_stopped[self._arm_picked] = bars
            else:
                self._pending_macros.arm(self._arm_picked, bars,
                                         self._phrase_bar or 0)
            self._slog("arm", result="armed", macro=self._arm_picked,
                       bars=bars, at_bar=self._phrase_bar,
                       anchored=self._phrase_anchor is not None,
                       survivors=self._drop_survivors,
                       frozen=self._frozen("macro"))
            # The queue stores only the LANDING BAR, which is all it needs to
            # fire. The ruler needs the length as well, or it cannot know how
            # many pads to extinguish - so the length is kept here rather than
            # widening the queue's contract for a display.
            self._arm_bars[self._arm_picked] = bars
            if self._arm_picked in tlib.MUTEPATH_MACROS:
                # One capture of the mute picture, so only one of DROP and
                # BREAK may be live. Arming either drops the other and its
                # return leg - replace-not-stack, extended from the queue's
                # own rule to the pair, with no refcount and no second
                # lifetime rule to get wrong.
                for other in tlib.MUTEPATH_MACROS:
                    if other != self._arm_picked:
                        self._pending_macros.cancel(other)
                        self._armed_while_stopped.pop(other, None)
                        self._arm_bars.pop(other, None)
            if self._arm_picked == "break":
                # BREAK fires NOW and resolves in N bars, so the length is
                # only the SECOND number. There is no "fires in N" for a macro
                # whose whole point is that it happens immediately - which is
                # why its own queue entry is taken straight back out again:
                # the generic arm above put it there, and leaving it would
                # give the countdown ruler a landing that never lands.
                #
                # Drained by the poll thread within a tick rather than written
                # here: this runs on the MIDI thread under the lock, and eight
                # set_mute(update=True) calls dispatch eight zynsigman signals
                # into the touchscreen mixer. DROP already does its muting on
                # the poll thread; BREAK has no reason to be the exception.
                self._pending_macros.cancel("break")
                self._armed_while_stopped.pop("break", None)
                self._arm_bars.pop("break", None)
                self._break_due = bars
        else:
            return
        with self.lock:
            self._render_pads()
            self._render_display()

    def _arm_state(self):
        """(picked, armed_bars, remaining) - what the ARM grid and LED show.

        armed_bars and remaining are both None when nothing is pending, which
        is how the legend and the LED tell the PICKER apart from the RULER
        without either of them re-deriving the rule.

        The SOONEST pending macro owns the ruler. Two macros can be pending at
        once and only one grid exists; showing the nearest is the only choice
        that cannot mislead, because the nearest is the one about to change
        what the player hears."""

        if self._armed_while_stopped:
            # Armed while stopped: no bar has passed, so nothing is
            # extinguished. Full ruler, and the LED goes steady rather than
            # flashing - see _render_transport.
            bars = min(self._armed_while_stopped.values())
            return (self._arm_picked, bars, bars)

        pending = self._pending_macros.pending()
        if not pending:
            self._freeze_memo = {}
            return (self._arm_picked, None, None)

        bar = self._phrase_bar or 0
        # Held still while the queue is. Maintained HERE, at the one place the
        # countdown is derived, so the ruler, the LED and the PENDING page
        # cannot disagree about what bar it is - and so a macro armed during a
        # freeze is memoised on its first sighting rather than from zero.
        live = {macro: self._pending_macros.remaining(macro, bar)
                for macro in pending
                if self._pending_macros.remaining(macro, bar) is not None}
        self._freeze_memo = tlib.freeze_memo(self._freeze_memo, live,
                                             self._frozen("macro"))
        soonest, left = None, None
        for macro in pending:
            rem = self._freeze_memo.get(
                macro, self._pending_macros.remaining(macro, bar))
            if rem is None:
                continue
            if left is None or rem < left:
                soonest, left = macro, rem
        if soonest is None:
            return (self._arm_picked, None, None)
        return (self._arm_picked, self._arm_bars.get(soonest, left), left)

    def _paint_arm_legend(self):
        """The sixteen pads as ARM's grid. Caller holds the lock."""

        picked, bars, left = self._arm_state()
        for pad in range(16):
            self._paint_pad(pad, tlib.arm_legend_pad(
                pad, picked=picked, armed_bars=bars, remaining=left))

    def _act_repeat(self, down):
        """STEP > held: every generated channel collapses to its first beat.

        The write itself is handed to the poll thread. It clears and rewrites
        a pattern per channel under the lock, and midi_event holds that lock
        for the whole event - the same law that keeps a preset load off this
        thread. The release has to survive a press whose collapse is still in
        flight, which is why both edges go through one attribute rather than
        two flags that can cross."""

        self._repeat_due = bool(down)
        self._render_repeat()
        with self.lock:
            self._render_display()

    def _repeat_apply(self, collapse):
        """Collapse to one beat, or put back what was captured.

        THE CAPTURE IS THE WHOLE DESIGN. _set_length recounts hits from the
        notes that survive the shrink - correct for its own purpose, since
        encoder 1 must resume from what is really there - which makes
        collapse-and-restore LOSSY: a 4-beat 16-step channel collapsed to one
        beat comes back with however many hits fell in that beat, permanently
        thinned, with the surface showing the smaller number as if the player
        had set it. The feature entry only warned about recorded takes.

        So the restore writes back the captured (beats, hits, rot) and
        regenerates through _write_pattern. Growing the length back would not
        do it: zynseq's resize() DELETED the notes past the end, and the
        captured euclid parameters are the only place they still exist.

        Player-owned channels are skipped, which the same fact forces: their
        notes are a take, and there is nothing to regenerate them from."""

        if collapse:
            if self._repeat_restore:
                return                      # already collapsed
            channels = tlib.generated_channels(self.owner, len(tlib.CHANNELS),
                                       moves=self._moves(),
                                       roll=self._move_roll)
            with self.lock:
                for channel in channels:
                    self._repeat_restore[channel] = (
                        self.beats[channel], self.hits[channel],
                        self.rot[channel])
                    try:
                        self._set_length(channel, tlib.REPEAT_BEATS)
                    except Exception as e:
                        self._log_poll_error(f"beat repeat ch{channel}", e)
            with self.lock:
                self._render_display()
            return

        if not self._repeat_restore:
            return
        with self.lock:
            for channel, (beats, hits, rot) in \
                    list(self._repeat_restore.items()):
                self.beats[channel] = beats
                self.hits[channel] = hits
                self.rot[channel] = rot
                try:
                    self._write_pattern(channel)
                except Exception as e:
                    self._log_poll_error(f"beat repeat restore ch{channel}", e)
        self._repeat_restore = {}
        with self.lock:
            self._render_all()

    def _act_bank(self, down):
        """DUPLICATE holds the sixteen-bank arrangement picker on the pads."""

        self._modifier_edge("bank", down)
        self._render_overlay_leds()
        if down:
            # Always open on the page the live bank is on, so the pad under
            # the finger is the arrangement being heard.
            self._bank_page = max(0, (self.bank - 1) // tlib.BANKS_PER_PAGE)
        with self.lock:
            self._render_pads()
            self._render_display()

    def _stocked_banks(self):
        """Which banks actually exist, read WITHOUT allocating one.

        getSequence creates on any index it is handed, silently and
        permanently into the riff - so drawing a grid of 64 pads with the
        wrong reader would grow the snapshot by 64 banks. getSequencesInBank
        only counts."""

        out = []
        for bank in range(1, tlib.BANKS_PER_PAGE * tlib.BANK_PAGES + 1):
            try:
                if self.libseq.getSequencesInBank(bank) > 0:
                    out.append(bank)
            except Exception:
                break
        return tuple(out)

    def _paint_bank_grid(self):
        """Sixteen banks, one page of four. Static: it repaints when the live
        or queued bank changes, which is at most once a bar."""

        stocked = self._stocked_banks()
        for pad in range(16):
            bank = tlib.bank_of_pad(pad, self._bank_page)
            look = tlib.bank_pad_look(bank, self.bank, self._bank_pending,
                                      stocked)
            self._paint_pad(pad, look)

    def _bank_pad(self, pad):
        """A pad while DUPLICATE is held: queue that bank for the next bar.

        LANDS ON THE BAR, never under the finger. A whole arrangement
        arriving mid-bar is the one gesture on this instrument that could not
        possibly be in time, and the phrase machinery that lands everything
        else already ships.

        Pressing the queued bank again CANCELS, which is what the second press
        of a gesture means everywhere else on this surface."""

        bank = tlib.bank_of_pad(pad, self._bank_page)
        if bank is None or bank == self.bank:
            return
        if bank == self._bank_pending:
            self._bank_pending = None
        else:
            self._bank_pending = bank
        with self.lock:
            self._render_pads()
            self._render_display()

    def _author_bank(self, bank):
        """Lay down THIS instrument's eight channels in an empty bank.

        zynseq builds a missing bank ITSELF on select_bank, as sixteen
        sequences in a 4x4 grid on MIDI channels 0-3 - somebody else's
        default, written into the riff. So an empty bank is authored here
        first, in the layout the driver's eight channels actually use, and
        select_bank then finds a bank that already exists and leaves it alone.

        Called only from a deliberate press on a dark pad. The GRID never
        authors anything: a picture that allocated what it drew would grow the
        snapshot by 64 banks the first time the overlay was held."""

        self.libseq.setSequencesInBank(bank, 0)
        self.libseq.setSequencesInBank(bank, len(tlib.CHANNELS))
        for group, ch in enumerate(tlib.CHANNELS):
            midi = ch[5]
            self.libseq.setGroup(bank, group, group)
            self.libseq.setChannel(bank, group, 0, midi)

    def _bank_switch(self, bank):
        """Take a bank. Poll thread, on the bar, under the lock.

        STASH THEN RESTORE. What Python owns about a channel is keyed by
        channel and not by bank, so the outgoing bank's registers are put away
        and the incoming bank's are brought back - or built fresh, which is
        what makes a never-used bank a blank scene rather than a copy of the
        one it was launched from."""

        old = self.bank
        self._bank_state[old] = {ch: dict(self.state[ch])
                                 for ch in range(len(tlib.CHANNELS))}
        if self.libseq.getSequencesInBank(bank) == 0:
            self._author_bank(bank)
        self.zynseq.select_bank(bank, force=True)
        self.bankpin.pin(self.zynseq.bank)
        saved = self._bank_state.get(bank)
        for ch in range(len(tlib.CHANNELS)):
            kind = tlib.CHANNELS[ch][2]
            if saved is not None and ch in saved:
                self.state[ch] = tlib.upgrade_state(kind, saved[ch],
                                                    self._steps(ch))
            else:
                self.state[ch] = tlib.default_channel_state(kind)
        # A bank switch is snapshot-shaped: it rewrites every play mode and
        # every cached value the driver holds. Both of those already have a
        # single answer each, and this reuses them rather than inventing a
        # third.
        self._resync_all()
        self._force_loop_mode()
        self._render_all()
        self._slog("bank", event="switch", bank=bank, was=old)

    def _act_mute(self, down):
        """MUTE holds the eight-channel mute grid on the pads."""

        self._modifier_edge("mute", down)
        self._render_overlay_leds()
        with self.lock:
            self._render_pads()
            self._render_mutes()

    def _is_muted(self, group):
        """Is this channel silent right now? Read live from zynmixer, which is
        the only store - the driver caches no mute state anywhere, and a
        wrapper that did would be a second truth."""

        chan = self._mixer_chan(group)
        if chan is None:
            return False
        return bool(self.state_manager.zynmixer.get_mute(chan))

    def _set_muted(self, group, muted):
        chan = self._mixer_chan(group)
        if chan is None:
            return False
        self.state_manager.zynmixer.set_mute(chan, bool(muted), update=True)
        return True

    def _mute_pad(self, step):
        """A pad while MUTE is held: top half acts now, bottom half queues it.

        A queued change is stored against the channel and taken at that
        channel's OWN wrap. The phrase bar would land all eight together and
        is musically the better answer for an arrangement gesture - but this
        package is deliberately buildable without the clock, and the channel
        wrap already ships. If the two are ever unified, this is the line that
        moves.

        Tapping a queued pad twice CANCELS the queue rather than queueing the
        opposite: the second press of a gesture is its undo everywhere else on
        this surface."""

        picked = tlib.mute_pad_channel(step, len(tlib.CHANNELS))
        if picked is None:
            return
        group, queued = picked
        if queued:
            if group in self._mute_pending:
                del self._mute_pending[group]
            else:
                self._mute_pending[group] = not self._is_muted(group)
        else:
            self._set_muted(group, not self._is_muted(group))
            # An instant press also clears a queued one for that channel. Two
            # answers pending for one strip is how a mute ends up fighting
            # itself a bar later.
            self._mute_pending.pop(group, None)
        with self.lock:
            self._render_pads()
            self._render_mutes()
            self._render_groups()

    def _paint_mute_grid(self):
        """The sixteen pads as the eight channels, twice. Caller holds lock."""

        for pad in range(16):
            picked = tlib.mute_pad_channel(pad, len(tlib.CHANNELS))
            if picked is None:
                self._paint_pad(pad, (0x000000, 0.0))
                continue
            group, queued = picked
            self._paint_pad(pad, tlib.mute_pad_state(
                tlib.CHANNELS[group][3], self._is_muted(group),
                self._mute_pending.get(group), is_queue_row=queued))

    def _act_navigate(self, down):
        """NAVIGATE holds the phrase page on the pads."""

        self._modifier_edge("navigate", down)
        self._render_overlay_leds()
        with self.lock:
            self._render_pads()

    def _paint_phrase_pads(self):
        """Sixteen pads, one per bar of the phrase. Caller holds the lock."""

        for pad in range(16):
            self._paint_pad(pad, tlib.phrase_pad(pad, self._phrase_bar))

    def _act_erase(self, down):
        """ERASE. A bare press does nothing at all - law L3 - so there is no
        state for a tap to flip and this is the one modifier that cannot
        latch. A latched ERASE would be a surface where the next thing you
        touch disappears.

        It lights now: dim while it waits, bright while it is held. It was lit
        at full brightness whenever the instrument was running, which said
        nothing about the only thing it does."""

        self.erase_down = down
        self._render_erase()
        # The Group row becomes the warning while ERASE is held - which
        # channels would LOSE a take - so it has to follow both edges of it.
        with self.lock:
            self._render_groups()

    def _act_freeze(self, down):
        """FREEZE: tap latches pattern generation, hold parks the LFOs too.

        Law L1 exactly, which is the reason this is one button and not two -
        nothing new has to be learned. The 250 ms rule is _act_mod's and
        _solo_button's, unchanged.

        NEVER a SHIFT chord: the daemon eats SHIFT + PAD MODE for its own
        sequencer mode and it never reaches the driver."""

        if down:
            self._down_at["freeze"] = (time.monotonic(), False)
            self.freeze_deep = True
            self._slog("freeze", edge="down", latch=self.frozen, deep=True,
                       pending=self._pending_macros.pending())
            with self.lock:
                self._render_freeze()
                self._render_display()
            return
        went_down, _ = self._down_at.pop("freeze", (None, False))
        self.freeze_deep = False
        if went_down is not None and \
                (time.monotonic() - went_down) * 1000.0 < HOLD_MS:
            self.frozen = not self.frozen
        self._slog("freeze", edge="up", latch=self.frozen, deep=False,
                   blocks_macro=self._frozen("macro"),
                   pending=self._pending_macros.pending())
        with self.lock:
            self._render_freeze()
            self._render_display()

    def _slog(self, tag, **fields):
        """One event into the play-session log. Never raises, never blocks.

        A log that can kill the instrument is worse than no log: this is
        wrapped because it runs on the MIDI thread, the poll thread and the
        signal thread, and a full tmpfs must cost a dropped line rather than a
        dead driver."""

        if self._slog_fh is None:
            return
        try:
            self._slog_fh.write(tlib.session_line(time.time(), tag, fields))
        except (OSError, ValueError):
            pass

    def _frozen(self, what):
        """Is `what` held still right now? One predicate, five call sites."""
        return tlib.freeze_blocks(what, self.frozen, self.freeze_deep)

    def _render_freeze(self):
        """PAD MODE lights while anything is frozen.

        A frozen instrument must never read as a broken one. The 2026-08-18
        poll-thread death is the precedent: generation stopped, nothing on the
        surface said so, and it went unexplained for three hours. Between this
        LED, the FRZ label and the columns losing their bars, there are three
        independent things saying the machine is being held."""

        # THE MODIFIER ALPHABET, and it had to change to be readable at all.
        # This asked for 2.0 on the deep hold and 1.0 on the latch, and
        # set_button_light CLAMPS AT 1.0 (daemon mikro.rs:960) - so the two
        # depths of freeze have been the same brightness since the day the
        # feature shipped, and neither was visible at all until the LED name
        # was fixed earlier today. Two invisible states, and the guide told
        # the reader a frozen instrument says so three times over.
        #
        # Now: bright while HELD (the deep freeze, your finger is on it),
        # blinking while LATCHED (the shallow one, your hand has left), dim
        # while it is merely available. The same three signals every other
        # modifier on this panel uses, and the panel's own word for "latched"
        # is exactly the state the tap produces.
        state = (tlib.COLOR_FREEZE,
                 tlib.state_light(self.freeze_deep, self.frozen,
                                  time.monotonic()))
        if self.leds.changed("freeze", state):
            self._send_osc(lib.button_osc(LED_FREEZE, state[0], state[1]))

    def _toggle_capture(self):
        """Start or stop the audio recorder. POLL THREAD ONLY.

        Explicit start/stop, NEVER cuia_toggle_audio_record: upstream that
        branches on `current_screen == 'control' and is_shown_audio_player()`
        (zynthian_gui.py:1187), and this rig runs headless much of the time,
        so the toggle's behaviour is not predictable from here. Explicit calls
        also mean the driver always knows which state it put the recorder in
        rather than inferring it.

        Reached through state_manager directly rather than through send_cuia,
        which this driver has never called once - a new thread-safety story to
        establish for no gain.

        MEASURED 2026-08-20: start_recording() shells out to jack_capture
        against zynmixer:output_17a/b and touches no screen state, so it works
        on a headless boot. The probe recorded four seconds and the file was
        the right size for the elapsed time."""

        recorder = getattr(self.state_manager, "audio_recorder", None)
        if recorder is None:
            # Not a crash: an older or stripped state manager simply has no
            # recorder, and a poll thread that raised here would take the
            # whole instrument down with it.
            logging.warning("Maschine: no audio_recorder on the state manager")
            return
        try:
            if self._recording:
                recorder.stop_recording()
                self._recording = False
            else:
                self._recording = bool(recorder.start_recording())
            self._slog("capture", recording=self._recording)
        except Exception as e:
            self._log_poll_error("audio capture", e)
            return
        logging.info("Maschine: audio capture %s",
                     "started" if self._recording else "stopped")
        with self.lock:
            self._render_transport()

    def _act_rec(self, down):
        # Held, and it overdubs: release ends the take. Held notes are NOT
        # released here - letting go of REC stops capturing, it does not stop
        # the instrument sounding.
        if down and self.shift_down:
            # SHIFT + REC is AUDIO CAPTURE, and it cannot collide with overdub
            # because overdub is bare-REC-HELD. That is also why the feature
            # entry's "long-press REC" was impossible: a long press IS that
            # hold.
            #
            # Deliberately does not set rec_down, so releasing SHIFT+REC
            # cannot end an overdub the player never started.
            self._record_due = True
            self._slog("rec", meaning="capture", shift=True)
            return
        self.rec_down = down
        self._slog("rec", meaning="overdub", down=down, shift=self.shift_down)
        self._render_display()

    def _act_shift(self, down):
        """SHIFT owns the pads while it is held: they stop showing the step
        picture and show each step's play chance instead.

        Both edges repaint. Without that the overlay would appear only when
        something else happened to trigger a render, which is how MOD's two
        _render_display() calls were literal no-ops before the cache tuple
        carried `mod`."""

        self._modifier_edge("shift", down)
        self._render_shift()
        with self.lock:
            self._render_pads()
            # SHIFT is also what hands the F row back to mute inside CONTROL,
            # so the row's lights have to follow both edges of it.
            self._render_mutes()

    def _mod_legend_state(self):
        """(bound, rate index, shape) for the legend.

        `bound` is False when _mod_pad would return without doing anything, so
        the pads can say so by standing still instead of dancing under an inert
        gesture."""

        entry = self.mod.get(self.mod_last) if self.mod_last else None
        if entry is None:
            return (False, 0, tlib.MOD_SHAPES[0])
        return (True, entry["rate"], entry["shape"])

    def _paint_mod_legend(self):
        """The sixteen pads as the modulation menu. Caller holds the lock.

        Driven by wall time, not beats, and deliberately so: this shows what a
        rate FEELS like on a compressed legibility band, not what the modulator
        is doing. tlib.MOD_LEGEND_PERIODS carries that caveat at length."""

        bound, rate, shape = self._mod_legend_state()
        # STATIC. `elapsed` is fixed rather than read from the clock: the
        # legend is painted on events now, so a moving time base would make
        # two repaints of an unchanged grid differ and put sixteen pad writes
        # on the wire for nothing. Zero is a phase like any other.
        for pad in range(16):
            self._paint_pad(pad, tlib.mod_legend_pad(pad, 0.0, rate, shape,
                                                     bound=bound))

    def _probe_step_chance(self):
        """Register argtypes for the per-step chance calls, and report whether
        they are usable.

        THE SYMBOLS EXIST ON THE PI BUT ZYNSEQ.PY REGISTERS NOTHING FOR THEM -
        it sets argtypes only for the per-PATTERN pair (`:114-115` there). An
        unregistered call is silently wrong rather than an error: ctypes passes
        a Python float as a C double, so `chance` arrives as garbage, and a
        getter without `restype` is read back as an int. That is the same shape
        as the two API-drift faults this project already survived, which is why
        this is a probe and not a hasattr guard - a bare hasattr would degrade
        silently on the only machine that runs it."""

        try:
            # uint8 CHANCE, 0-100 - NOT the float 0.0-1.0 the per-PATTERN
            # setPlayChance() takes, and NOT what our checkout's header says.
            # The Pi's own zynseq.h is the authority:
            #     uint8_t getNotePlayChance(uint32_t step, uint8_t note);
            #     void setNotePlayChance(uint32_t step, uint8_t note, uint8_t chance);
            # while the newer checkout declares the third argument as a float.
            # Registered as float first time round, which made every write pass
            # garbage and every read return garbage, and BOTH FAILED SILENTLY -
            # Pattern::setPlayChance simply returns when no event matches, and
            # the getter reports the "no match" default. The pads drew, nothing
            # moved, and nothing was logged.
            self.libseq.setNotePlayChance.argtypes = [
                ctypes.c_uint32, ctypes.c_uint8, ctypes.c_uint8]
            self.libseq.getNotePlayChance.argtypes = [ctypes.c_uint32, ctypes.c_uint8]
            self.libseq.getNotePlayChance.restype = ctypes.c_uint8
        except AttributeError:
            logging.warning("Maschine: libzynseq has no per-step play chance - "
                            "SHIFT + pad probability is unavailable on this build")
            return False
        return True

    def _probe_stutter(self):
        """Register argtypes for the stutter calls, and report usability.

        Same shape as _probe_step_chance, and for the same reason: the symbols
        are exported by the Pi's .so and `zynseq.py` registers argtypes for
        NEITHER. These are all uint8 rather than float, so an unregistered call
        would happen to work today - which is exactly why it is worth pinning
        now, before someone changes a type upstream and it fails silently."""

        try:
            self.libseq.setStutterCount.argtypes = [
                ctypes.c_uint32, ctypes.c_uint8, ctypes.c_uint8]
            self.libseq.setStutterDur.argtypes = [
                ctypes.c_uint32, ctypes.c_uint8, ctypes.c_uint8]
            self.libseq.getStutterCount.argtypes = [ctypes.c_uint32, ctypes.c_uint8]
            self.libseq.getStutterCount.restype = ctypes.c_uint8
        except AttributeError:
            logging.warning("Maschine: libzynseq has no stutter - RATCHET is "
                            "unavailable on this build")
            return False
        return True

    def _step_chance(self, step, note):
        """One step's play chance, 0-100, or None if unreadable.

        NO conversion: the per-step call speaks the surface's own 0-100 already.
        Only the per-PATTERN setPlayChance() takes a 0.0-1.0 float, which is the
        asymmetry that made this wrong the first time."""

        if not self.has_step_chance or note is None:
            return None
        try:
            return int(self.libseq.getNotePlayChance(step, note))
        except Exception:
            return None

    def _shift_pad(self, step):
        """SHIFT + pad steps that step's play chance down one rung.

        Costs NO pattern rewrite - no clear(), no addNote loop, no write burst
        under the lock. That is what makes this safe on a player-owned channel:
        it cannot destroy a take, so it needs none of drift's ownership rules."""

        if not self.has_step_chance:
            return
        with self.lock:
            self._select_pattern(self.group)
            note = self._step_note(self.group, step)
            if note is None:
                return                      # an empty step has nothing to roll for
            current = self._step_chance(step, note)
            if current is None:
                return
            nxt = tlib.chance_ladder(current)
            self.libseq.setNotePlayChance(step, note, nxt)
            self._render_pads()

    def _act_coarse(self, down):
        """TEMPO held: every encoder returns to its old, faster feel.

        The carries are dropped on BOTH edges. encoder_steps() bounds a carry
        by the units-per-step in force when it was written, so a carry banked
        at the fine default can be twice a coarse step - and the first
        turn after the press would divide it by the coarse units and take the
        whole lot at once. Crossing the edge costs a fraction of one step;
        not crossing it cleanly costs a jump."""

        self.coarse_down = down
        self.enc_carry.clear()
        self._render_coarse()

    def _act_solo(self, down):
        self._solo_button(down)

    def _act_mod(self, down):
        """SWING. Held or latched, the eight encoders set modulation DEPTH and
        the pads become the rate-and-shape menu.

        The duration rule is tlib.latch's now and no longer written out here -
        it was the FIRST button on this panel to have it and is now one of
        seven. Repaint on both edges: without it the legend would appear only
        when something else happened to trigger a render, and the pads would
        keep lying in whichever direction the last paint left them."""

        self._modifier_edge("mod", down)
        self._render_mod()
        # RESTART becomes the pump while MOD is on, and says so.
        self._render_restart()
        self._render_rec()
        self._render_display()
        with self.lock:
            self._render_pads()

    def _act_play(self):
        self._toggle_transport()

    def _act_grid(self):
        # A bare GRID press is swallowed and does nothing. Deliberate: it stays
        # free for a later feature and cannot fall through to something else
        # that reacts to it - which is exactly what an unbound CC 3 was doing
        # before SP2 claimed it.
        if self.shift_down:
            self._toggle_kind()

    def _act_register_undo(self):
        self._duplicate()

    def _act_restart(self):
        if self.mod_down:
            # MOD + RESTART: every modulator back to the start of its cycle,
            # together. THE SIDECHAIN PUMP IS THIS GESTURE, not a new LFO - a
            # negative-depth ramp on LEVEL across the MIXER page already pumps
            # each strip, and the only thing wrong with it is that eight binds
            # made one after another run in eight phases.
            #
            # BARE RESTART DELIBERATELY DOES NOT DO THIS, although the case for
            # it is real: this method already re-zeros the phrase clock with
            # the playheads, and its own comment says the count must not keep
            # running while every pattern jumps to its start. An LFO is the one
            # thing it leaves running. It stays that way because a sixteen-bar
            # filter sweep would SNAP mid-move, and a player reaching for
            # RESTART is asking about the pattern, not about a sweep they set
            # up four bars ago. Under MOD they are asking about modulation, and
            # that is exactly when the answer changes.
            self._rephase_all()
            return
        for group in range(8):
            # Installed signature: setPlayPosition(bank, sequence, clock)
            self.libseq.setPlayPosition(self.bank, group, 0)
        # RESTART re-zeros the phrase with the playheads. Without this the
        # count keeps running while every pattern jumps to its start, which is
        # precisely the disagreement this clock exists to prevent.
        if self._phrase_anchor is not None:
            self._phrase_anchor = self._elapsed_beats()
            self._phrase_bar = 0

    def _rephase_all(self):
        """Put every modulator at the start of its cycle, now, together.

        Same-rate modulators end up in lockstep, which is what turns eight
        scattered per-strip pumps into one mix pump. Different rates start
        together and diverge as their rates say they should - that is the
        honest behaviour, not a special case: two-bar and one-bar modulators
        agreeing forever would mean one of them is not running at its rate.

        The BASE is untouched. Re-phasing moves where in its cycle a modulator
        is, never the value the player dialled in - the base/offset law, which
        every other modulation path here already obeys."""

        if not self.mod:
            return
        elapsed = self._elapsed_beats()
        for entry in self.mod.values():
            entry["phase0"] = tlib.phase_reset(
                elapsed, tlib.MOD_RATES[entry["rate"]])
        self._slog("rephase", count=len(self.mod), beats=round(elapsed, 3))
        with self.lock:
            self._render_display()

    def _act_page_prev(self):
        self._step_page(-1)

    def _act_page_next(self):
        self._step_page(1)

    def _act_sound_prev(self):
        self._sound_step(-1)

    def _act_sound_next(self):
        self._sound_step(1)

    def _sound_step(self, delta):
        # Previous / next SOUND for the selected channel, and SHIFT makes it
        # the KIT. Both ask the ENGINE, never the behaviour: a drum engine has
        # kits and samples whichever way the channel is being played, and a
        # synth engine has presets. Unconditionally cycling the sample once
        # resolved a GM percussion fallback on a voice and collapsed its whole
        # line onto one note.
        drum_engine = self._is_sampler(self.group)
        if self.shift_down:
            # SHIFT + ML/MR walks the kit, and only a drum engine has one. On
            # a synth engine this does nothing and says nothing - a button
            # cannot be drawn dead the way a column can.
            if drum_engine:
                self._nudge_kit(delta)
            return
        if drum_engine:
            self._cycle_sample(delta)
        else:
            self._nudge_preset(self.group, delta)

    def _select_group(self, group):
        self._release_all()          # the pads are about to mean another sound
        self.group = group
        # The daemon re-bases the pads on a Group PRESS it sees itself, and on
        # nothing else. Every other route into this method - a snapshot load,
        # a chain change, any future binding - leaves its base pointing at the
        # group we just left, and then EVERY pad press decodes out of range
        # and is dropped without a sound or a log. Measured on the rig
        # 2026-08-22: driver on group H at base 108, daemon still sending
        # base 48, the whole step grid dead.
        self._note_base_due = True
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
            # RATCHET is stutter, and stutter is SAVED IN THE RIFF - so a
            # snapshot comes back with the pattern still stuttering. Read it
            # back rather than defaulting to 1, or the surface would say OFF
            # over a pattern that is plainly ratcheting: the CHANCE/SWING
            # defect of 2026-08-11 with a new cause.
            if self.has_stutter:
                try:
                    note = self._group_note(group)
                    steps = self.libseq.getSteps()
                    for step in range(steps):
                        if self.libseq.getNoteVelocity(step, note):
                            found = int(self.libseq.getStutterCount(step, note))
                            state["ratchet"] = max(1, found)
                            break
                except Exception:
                    logging.debug("Maschine: no readable stutter on this libzynseq")
        note = self._group_note(group)
        steps = self.libseq.getSteps()
        self._recount_hits(group, note, steps)

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
        steps, carry = lib.encoder_steps(
            self.enc_carry.get(cc_num, 0), delta,
            lib.step_units(units, self.coarse_down))
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
            self.enc_carry.get(cc_num, 0), delta,
            lib.step_units(lib.units_per_step(values), self.coarse_down))
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
        if shape == tlib.SHAPE_PENDING:
            # The audit page has no verbs and no values to turn. Its ONE
            # gesture is ERASE + the encoder under a column, which kills that
            # entry; a bare turn does nothing, deliberately, because a page
            # you read mid-performance must not change under a knock.
            if self.erase_down and self._enc_delta(cc_num, cc_val):
                if self._cancel_pending(column):
                    with self.lock:
                        self._render_all()
            return
        if shape == tlib.SHAPE_SPREAD:
            verb, channel = desc["verb"], column
        else:
            verb = desc["verbs"][column]
            # REMEMBER IT, so ALL can spread it. Only here: a turn inside the
            # lens is already spreading, and letting it write back would pin
            # the lens to itself and make the gesture one-way. A verb the lens
            # refuses (a global, a name) leaves it where it was - lens_verb()
            # decides that, not this line, so the rule lives in one tested
            # place rather than in the dispatch.
            if verb is not None and tlib.lens_verb(verb) is not None:
                self._lens_verb = verb
            # A global page still passes the selected channel, exactly as the
            # shipped ALL page did. _verb() resolves a global by verb name and
            # ignores the channel, but its first line asks the channel for its
            # kind - so None would raise before the global branch is reached.
            channel = self.group
        if verb is None:
            return                        # greyed column, dead knob, honestly
        # A COLUMN WITH A VERB CAN STILL BE DRAWN DEAD, and the encoder has to
        # agree with the glass whatever else is going on. This used to be
        # asked only under MOD, which was safe while every spread page carried
        # a verb all eight channels had; the LENS spreads ANY verb, so CUTOFF
        # over the five drums and LANE over the three voices are now ordinary
        # pictures - four dead columns beside four live ones, on one page.
        # Turning a dead one must do nothing, or the surface says `----` while
        # the sound moves, which is this project's whole catalogue of quiet
        # bugs in one gesture.
        if self._column_dead(column):
            return
        if self.mod_down:
            self._mod_encoder(verb, channel, cc_num, cc_val)
            return
        self._verb(verb, channel, cc_num, cc_val)

    def _mod_encoder(self, verb, channel, cc_num, cc_val):
        """MOD held: the encoder sets modulation DEPTH on this verb, not its
        value. Bipolar, centre is off.

        A refused verb LOSES ITS BAR while MOD is down and does nothing - it
        never silently sets a depth that will not be honoured. Both halves are
        real now: this docstring claimed the drawing half for a while when
        only the doing-nothing half existed, so under MOD the HITS column
        looked exactly like the LEVEL column and one of them worked. The
        drawing comes from techno_lib.columns(), through the same `grey` flag
        _column_dead() reads, so the two cannot drift apart again."""
        if not tlib.mod_allowed(verb, self.owner.get(channel) == "player"):
            # Drift refuses on a player-owned channel and is drawn dead there -
            # owner's confirmed rule, 2026-08-19. Rewriting a pattern with no
            # hands on the panel is exactly how the velo defect erased a take.
            return
        if self.erase_down:
            # MOD + ERASE + encoder clears. Destructive, so it is two-key and
            # it obeys law L3: no single press destroys anything.
            self._mod_clear(self._mod_key(channel, verb))
            self._render_display()
            return
        key = self._mod_key(channel, verb)
        # Everything below addresses the modulator by the KEY's channel, not
        # by the channel the gesture arrived on: an `fx:` verb is global and
        # its key channel is None whichever group is selected.
        channel = key[0]
        span = self._mod_range(channel, verb)
        if span is None:
            return
        entry = self.mod.get(key)
        # 200 units of travel across -100..+100, so a full sweep of the
        # encoder covers the whole bipolar range once.
        delta = self._enc_steps(cc_num, cc_val, 2 * tlib.MOD_DEPTH_MAX + 1)
        if delta == 0:
            return
        if entry is None:
            self.mod_seed += 1
            rate_idx = tlib.MOD_RATES.index(1.0)
            # PHASE COMES FROM BIND TIME. phase0 is chosen so the modulator is
            # at position 0 the instant it is bound - which is what makes eight
            # LFOs bound one after another on a spread page run scattered
            # rather than in lockstep. Setting phase0 to a flat 0.0 would put
            # every same-rate modulator in phase no matter when it was bound.
            elapsed = self._elapsed_beats()
            entry = {
                "depth": 0,
                "rate": rate_idx,
                "shape": "tri",
                "phase0": tlib.phase_reset(elapsed,
                                           tlib.MOD_RATES[rate_idx]),
                # The base is captured ONCE, at bind, from the value the
                # player has dialled in. Re-reading it later would read the
                # LFO's own output back and the parameter would walk away.
                "base": self._mod_base_get(channel, verb),
                "seed": self.mod_seed,
            }
            if entry["base"] is None:
                return                    # no readable source: bind nothing
            self.mod[key] = entry
        entry["depth"] = max(-tlib.MOD_DEPTH_MAX,
                             min(tlib.MOD_DEPTH_MAX, entry["depth"] + delta))
        self.mod_last = key
        if entry["depth"] == 0:
            # Centre is off, and off means gone: leaving a zero-depth entry
            # behind would keep writing base over the top of the touchscreen.
            self._mod_clear(key)
        self._render_display()

    def _mod_pad(self, pad):
        """MOD + pad: rate and shape for the MOST RECENTLY BOUND modulator.

        Not the same pointer as the big encoder's 'last-touched parameter'
        (SP10 step 2) - keep the two names apart or they will be conflated.

        Pads 0-11 (the top three rows) pick a rate from techno_lib.MOD_RATES
        (twelve entries, slowest first, so the rate speeds up left to right
        and top to bottom). Pads 12-15 - the bottom row alone - are the four
        techno_lib.MOD_SHAPES in order, one shape per pad."""
        if self.mod_last is None:
            return
        entry = self.mod.get(self.mod_last)
        if entry is None:
            self.mod_last = None
            return
        if pad < len(tlib.MOD_RATES):
            entry["rate"] = pad
            if entry.get("once"):
                # Re-arm. A new length must restart the sweep from here rather
                # than leave a finished one clamped at its old span, which
                # would look like a dead pad.
                self._arm_once(entry)
        else:
            entry["shape"] = tlib.MOD_SHAPES[pad - len(tlib.MOD_RATES)]
            if self.arm_down:
                # MOD + ARM on a shape pad: that shape now runs ONCE. The rate
                # pads need no branch at all - they already write
                # entry["rate"], and under a one-shot that number is read as a
                # sweep LENGTH instead of a cycle time. Same table, new
                # meaning, no second table to drift.
                self._arm_once(entry)
        # BOTH, and the pads are not optional. The legend used to be repainted
        # by its own 30 Hz animation, so the "selected" highlight followed a
        # tap as a side effect. With the animation gone - it wedged the
        # controller - nothing else repaints the grid, and picking a rate
        # moved the highlight nowhere. Found by the owner asking whether rate
        # selection still worked, 2026-08-20: it did, and it had stopped
        # SAYING so, which on this surface is the same fault.
        self._render_pads()
        self._render_display()

    def _arm_once(self, entry):
        """Make this modulator a one-shot whose sweep starts NOW.

        phase0 is stored NEGATIVE - minus the position already elapsed - so
        mod_once_pos reaches 1.0 one span from this moment rather than one
        span from driver start-up. That is what "lands on the downbeat" means,
        and it also makes the sweep slightly shorter than the nominal rate.

        RISE adds no new permission surface: it goes through mod_allowed()
        unchanged, so gate and velo stay refused and the drift verbs still
        refuse on a player-owned channel. The deny list stays absolute by
        construction rather than by a second copy that can drift."""

        span = tlib.MOD_RATES[entry["rate"]] * 4.0
        entry["once"] = True
        entry["phase0"] = -self._elapsed_beats() / span if span else 0.0

    def _pad_owner(self):
        """What the pads mean right now. One predicate, every caller."""
        return tlib.pad_owner(shift=self.shift_down, mod=self.mod_down,
                              arm=self.arm_down,
                              navigate=self.navigate_down,
                              mute=self.mute_down,
                              bank=self.bank_down)

    def _mod_clear(self, key):
        """Drop a modulator and restore its base, so the parameter is left
        where the player put it rather than wherever the LFO stopped."""
        entry = self.mod.pop(key, None)
        if entry is None:
            return
        # Dropped from self.mod, so `once` goes with it. Kept explicit because
        # set_state rebuilds entries from a saved dict and a stale `once` there
        # would come back clamped, with no pad to un-clamp it.
        entry.pop("once", None)
        channel, verb = key
        self._mod_base_set(channel, verb, entry["base"])
        if self.mod_last == key:
            self.mod_last = None

    def _mod_clear_all(self):
        """MOD + ERASE + ALL: drop every modulator at once.

        The bases are NOT restored here. _mod_clear writes the parameter, and
        for a generated lv2:/fx: verb that reaches the plugin - this runs on
        the MIDI thread with self.lock held, where a write can block on a
        socket for seconds. One such write is what the single-modulator clear
        already costs; doing twenty in one event is the shape of the freeze
        that this instrument has already suffered once.

        So the dict work happens here, which is cheap, and the restores are
        queued for the poll thread - the same deferral _commit_kit,
        _commit_preset and the note-map rebuilds all use."""
        if not self.mod:
            return
        for (channel, verb), entry in list(self.mod.items()):
            self._mod_restore_due.append((channel, verb, entry["base"]))
        self.mod.clear()
        self.mod_last = None
        self._render_display()

    def _mod_base_get(self, channel, verb):
        """The verb's current surface value, or None when it has no source.

        One accessor for both kinds of verb, so nothing downstream has to ask
        which kind it is holding.

        LEVEL is read LIVE from the mixer, for exactly the reason _verb() reads
        it live: the touchscreen and a snapshot both move the fader behind the
        driver's back, so self.state's copy is routinely stale. Capturing that
        stale copy as a modulator's base made the first tick after a bind on
        the MIXER LEVEL spread page yank the fader back to wherever the driver
        last thought it was."""
        if verb.startswith(tlib.VERB_LV2) or verb.startswith(tlib.VERB_FX):
            return self._mod_percent_get(channel, verb)
        if verb == "level":
            level = self._live_level(channel)
            if level is not None:
                return level
        return self.param_get(channel, verb)

    def _live_level(self, channel):
        """This channel's fader as the 0-100 the surface shows, straight from
        the mixer, or None when it has no strip."""
        chan = self._mixer_chan(channel)
        if chan is None:
            return None
        return int(round(self.state_manager.zynmixer.get_level(chan) * 100))

    def _mod_base_set(self, channel, verb, value):
        if verb.startswith(tlib.VERB_LV2) or verb.startswith(tlib.VERB_FX):
            self._mod_percent_set(channel, verb, value)
            return
        self.apply(channel, verb, value)

    def _snapshot_busy(self):
        """True while the state manager is inside a snapshot load or save.

        Read from the state manager's own busy set rather than a flag of our
        own. A flag would need a signal at the START of a load and there is
        none - SS_LOAD_SNAPSHOT is sent after everything, including
        set_state_drivers - so the flag could only be raised on the wrong edge
        and would risk suppressing modulation for the rest of the session.
        This set is emptied by end_busy() whatever happens, including on a
        load that fails, so it cannot latch on.

        The clid is 'load snapshot' on the main path and 'load_snapshot' on
        another, so the test is a substring; 'save snapshot' matches too,
        which is harmless and mildly useful."""

        try:
            busy = getattr(self.state_manager, "busy", None) or ()
            return any("snapshot" in str(clid) for clid in busy)
        except Exception:
            return False

    def _pending_view(self):
        """(macro, bars left, armed bars) for everything armed right now.

        Reads the queue, never a second copy of it. The page is an AUDIT
        surface and an audit that keeps its own tally is not an audit."""

        bar = self._phrase_bar or 0
        out = []
        for macro, bars in self._armed_while_stopped.items():
            # Armed while stopped: nothing is counting down yet, so the whole
            # length is still to come. Drawn rather than hidden - a macro the
            # player armed and cannot see is exactly what this page is for.
            out.append((macro, bars, bars))
        for macro in self._pending_macros.pending():
            left = self._pending_macros.remaining(macro, bar)
            if left is None:
                continue
            out.append((macro, left, self._arm_bars.get(macro, left)))
        return out

    def _cancel_pending(self, column):
        """ERASE + the encoder under a column kills that one armed macro.

        ERASE is already this instrument's take-it-back modifier, and
        encoder-under-column is already how every page on the ring is edited -
        so per-entry cancel costs no new control and no new capture.

        A bare ARM tap still cancels EVERYTHING. This is the addition, not the
        replacement: cancel-all is the panic gesture and has to stay one
        press."""

        rows = tlib.pending_sort(self._pending_view())
        if not 0 <= column < len(rows):
            return False
        macro = rows[column][0]
        self._armed_while_stopped.pop(macro, None)
        self._arm_bars.pop(macro, None)
        self._pending_macros.cancel(macro)
        logging.debug("Maschine: cancelled pending macro %s", macro)
        return True

    def _mod_beats(self):
        """The beat count every modulator is measured against.

        THE PHRASE, not the driver's uptime. `_elapsed_beats()` is
        time.monotonic() scaled by BPM and free-running from construction, so
        an 8-bar sweep used to be an 8-bar sweep at an arbitrary offset -
        never THE 8 bars. Anchoring it to the phrase makes a sweep start where
        the player hears the phrase start, and re-zeros the whole modulation
        system at transport start and at RESTART.

        This does NOT remove the .0573 drift measured over an hour at the SP10
        gate: the phrase clock has the same time base, and the sequencer runs
        on the audio clock. It BOUNDS it - to one performance instead of one
        uptime, because both anchor sites re-zero it. **Do not build a second
        correction here.** If the owed 5-minute measurement says the drift is
        real inside a single performance, the fix is the phrase clock's own
        soft re-anchor and this inherits it for free.

        Falls back to the raw clock before the transport has ever run, so
        modulators still sweep on a stopped rig rather than freezing at zero
        with nothing saying why."""

        if self._phrase_anchor is None:
            return self._elapsed_beats()
        return self._elapsed_beats() - self._phrase_anchor

    def _pad_pressure(self, value):
        """Record pad pressure for the selected channel. MIDI thread.

        The value lands on the SELECTED channel rather than on the pad's own,
        because a pad is a STEP of the selected channel on this instrument
        (`_midi_event` decodes it against GROUP_NOTE_BASE), not a channel of its
        own. Two pads held at once therefore share one offset and the later
        report wins - which is what a filter under one hand should do anyway.

        Drum channels are ignored: their one-shots run to the end regardless
        and the drum filter is shelved, so there is no verb to move."""
        if self.channel_kind(self.group) != "voice":
            return True
        self._press_raw[self.group] = int(value)
        return True

    def _press_release(self, channel):
        """Put the knob back and forget the squeeze."""
        base = self._press_base[channel]
        if base is not None:
            self.apply(channel, tlib.PRESSURE_VERB, base)
        self._press_raw[channel] = 0
        self._press_off[channel] = 0.0
        self._press_base[channel] = None

    def _pressure_write(self):
        """Apply pad pressure as an offset over the knob. Poll thread.

        Deliberately NOT folded into _mod_write: that returns early when no
        modulator exists, and pressure has to work on a channel nobody has
        bound MOD to. It IS called from the same ~200 ms tick, and it is not
        gated by FREEZE - parking the LFOs is a decision about the machine
        evolving on its own, and a hand on a pad is not that."""
        if self._snapshot_busy():
            return
        verb = tlib.PRESSURE_VERB
        for channel in range(8):
            if (self._press_raw[channel] <= 0
                    and self._press_off[channel] <= 0.0
                    and self._press_base[channel] is None):
                continue
            if self.channel_kind(channel) != "voice":
                # SP4 lets a channel change kind under a live squeeze.
                self._press_release(channel)
                continue
            span = self._mod_range(channel, verb)
            if span is None:
                continue
            target = tlib.pressure_offset(self._press_raw[channel],
                                          span[0], span[1])
            # Instant up, decayed down. A squeeze has to feel immediate, and a
            # release has to sound like a filter closing rather than a fault.
            off = self._press_off[channel]
            off = target if target >= off else tlib.pressure_decay(off)
            self._press_off[channel] = off
            if (channel, verb) in self.mod:
                # A modulator already owns this verb, and TWO writers on one
                # parameter is the base/offset bug in a new costume. _mod_write
                # folds our offset into its swept value; we own nothing here,
                # so any base we were holding is not ours to restore.
                self._press_base[channel] = None
                continue
            if off <= 0.0:
                base = self._press_base[channel]
                if base is not None:
                    # The restore write. pressure_value returns the base
                    # EXACTLY at a zero offset, so the knob lands where the
                    # player left it and not half a unit away.
                    self.apply(channel, verb, base)
                    self._press_base[channel] = None
                continue
            if self._press_base[channel] is None:
                self._press_base[channel] = self.state[channel].get(verb, 64)
            self.apply(channel, verb,
                       tlib.pressure_value(self._press_base[channel], off,
                                           span[0], span[1]))

    def _mod_write(self):
        """Advance every modulator and write base+offset.

        Runs on the poll thread and NEVER on the MIDI thread: midi_event holds
        the lock for the whole event, and a parameter write can block."""
        if not self.mod and not self._mod_restore_due:
            return
        if self._frozen("lfo"):
            # THE HELD FLAG ONLY - a FREEZE tap deliberately leaves the LFOs
            # sweeping, so the notes stop changing under you while the sound
            # keeps breathing. Parking them takes the deeper gesture.
            #
            # Returning before the restore drain is deliberate too: a base
            # owed to MOD + ERASE while everything is parked can wait one
            # let-go, and writing it here would move a parameter during a
            # gesture whose whole promise is that nothing moves.
            return
        if self._snapshot_busy():
            # A load rewrites every chain and every mixer strip, and set_state
            # - which is what replaces self.mod - runs at the END of it.
            # Without this the poll thread gets a ~200 ms tick in the middle
            # and writes a modulator belonging to the OUTGOING snapshot over a
            # value that was just restored.
            return
        # Bases owed by MOD + ERASE + ALL. Drained before the sweep so a
        # cleared parameter lands on the value the player set and is not
        # overwritten in the same tick by a modulator still in the dict.
        while self._mod_restore_due:
            channel, verb, base = self._mod_restore_due.pop(0)
            self._mod_base_set(channel, verb, base)
        beats = self._mod_beats()
        for key, entry in list(self.mod.items()):
            channel, verb = key
            span = self._mod_range(channel, verb)
            if span is None:
                continue
            if tlib.is_drift(verb):
                # Applied at the WRAP by _wrap_channel, never here. A pattern
                # verb written every 200 ms is clear() plus an addNote loop
                # under the lock, five times a second, forever - the velo
                # defect exactly.
                continue
            if entry.get("once"):
                pos = tlib.mod_once_pos(entry["phase0"], beats,
                                        tlib.MOD_RATES[entry["rate"]])
                # HOLD at the end. mod_wave takes pos % 1.0 and 1.0 % 1.0 is
                # 0.0, which would drop a finished ramp back to its minimum -
                # the exact opposite of landing on the downbeat.
                wave = tlib.mod_wave(
                    entry["shape"],
                    tlib.MOD_ONCE_END if pos >= 1.0 else pos,
                    entry["seed"])
            else:
                pos = tlib.mod_pos(entry["phase0"], beats,
                                   tlib.MOD_RATES[entry["rate"]])
                wave = tlib.mod_wave(entry["shape"], pos, entry["seed"])
            # THE MULTIPLIER BELONGS HERE TOO. Without it the big encoder
            # scaled drift and the drawn span while the LFO writes went out at
            # their raw depth - so the knob moved the picture and changed
            # nothing anyone could hear. Found on the rig 2026-08-20: "encoder
            # does nothing". _drift_channel had it from the start; this, the
            # main writer, did not.
            value = tlib.mod_value(entry["base"], wave,
                                   tlib.mod_depth_scale(entry["depth"],
                                                        self.mod_depth_mult),
                                   span[0], span[1])
            if verb == tlib.PRESSURE_VERB and self._press_off[channel] > 0.0:
                # ONE writer per parameter. When MOD and a squeezed pad both
                # want cutoff they SUM here and clamp - the LFO wobbles and the
                # hand pushes the whole thing up - rather than taking turns and
                # fighting every tick.
                value = tlib.pressure_value(value, self._press_off[channel],
                                            span[0], span[1])
            # set_value() already returns early on an unchanged value and
            # integer controls dedupe for free, so a slow or parked modulator
            # costs a function call and nothing else.
            self._mod_base_set(channel, verb, value)
            # The display's tick needs where the wave IS, sampled at this
            # ~200 ms write rate - mod_span (the dashed envelope) is static
            # given an unchanged base/depth and would put the tick dead on
            # the span's midpoint forever, showing no motion at all.
            width = span[1] - span[0]
            # IMPORTANT: live is normalised against the raw span width from
            # _mod_range, NOT the narrowed span from mod_span(). If either
            # normalisation changes without the other, the tick will no longer
            # land visually inside the dashed span envelope it is drawn in.
            entry["live"] = (value - span[0]) / width if width else 0.0

    # Range and step size per verb: (lo, hi, units per step).
    # Fine controls sweep across the encoder's 128 units; coarse ones use a
    # flat 8 units per detent, because spreading a handful of settings over
    # the whole sweep reads as sticky.
    VERB_RANGES = {
        "velo": (1, 127, None),
        "chance": (0, 100, None),
        "rhythm": (0, 100, None),
        "swing": (50, 75, ENC_UNITS_DISCRETE),
        "level": (0, 100, None),
        "reverb": (0, 100, None),
        "delay": (0, 100, None),
        "cutoff": (0, 127, None),
        "reso": (0, 127, None),
        "env": (0, 127, None),
        "decay": (0, 127, None),
        "random": (0, 100, None),
        # MOVE, 2026-09-01. 0 is LOCK - the machine may not touch the channel -
        # and 100 is what shipped before the verb existed.
        "move": (0, 100, None),
        # LANE, 2026-09-01. 0 is the raw field, 100 keeps only what lands on
        # the beat.
        "lane": (0, 100, None),
        # A PHRASE, NOT A BAR, 2026-09-01. 1 is off - every bar is its own
        # phrase, which is what shipped before this existed.
        "phrase": (1, 4, ENC_UNITS_DISCRETE),
        "fill": (0, 100, None),
        # EXIT, 2026-09-01. In BARS, and four is the longest close this
        # instrument has a use for - past that the part has left before the
        # gesture finishes. Discrete, or a nudge would change a bar count.
        "exit": (0, 4, ENC_UNITS_DISCRETE),
        # 5-800, widened from 5-100 for the 8-step note length. The old
        # 5-100 range is now a sliver of the sweep, so gate moves in jumps
        # of roughly 6-24 per encoder report - a deliberate resolution
        # trade-off, not a bug to smooth out.
        "gate": (5, tlib.GATE_MAX, None),
        "octave": (-2, 2, ENC_UNITS_DISCRETE),
        "range": (1, 4, ENC_UNITS_DISCRETE),
        # 1 is OFF; 2-4 are the ratchet counts.
        "ratchet": (1, 4, ENC_UNITS_DISCRETE),
        # THE GEN PAGE, 2026-08-31. `rotate` is deliberately absent: it is a
        # verb on BOTH kinds and _verb dispatches it by kind before ever
        # reaching this table - see the branch there.
        "walk_span": (1, 128, None),
        "walk_stride": (1, 32, None),
        "amount": (0, 100, None),
    }

    def _mod_steer(self, key, cc_num, cc_val):
        """A hand turn on a verb that already carries a modulator steers the
        modulator's BASE, and writes nothing to the engine.

        Without this the knob is dead. _mod_write() writes base+offset through
        _mod_base_set() -> apply(), which stores into self.state and the mixer
        - the driver's own parameter store - and the ordinary path below then
        reads that swept number back as `current`. Every turn started from
        wherever the LFO happened to be and was overwritten inside 200 ms, so
        the encoder read as erratic and then dead.

        Nothing is written to the engine here on purpose: _mod_write() is the
        only writer of a modulated parameter, and it picks the new base up on
        its own next tick. The display already substitutes the base through
        mod_base_or(), so the value cell follows the knob immediately.

        Encoder feel matches the ordinary path exactly - the same range, the
        same units per step - or the same verb would move at two different
        speeds depending on whether a modulator happened to be bound."""

        channel, verb = key
        span = self._mod_range(channel, verb)
        if span is None:
            return
        lo, hi = span
        if verb.startswith(tlib.VERB_LV2) or verb.startswith(tlib.VERB_FX):
            # Generated verbs are steered as a percentage, the same 0-100 the
            # column shows and _mod_percent_set() scales onto the port.
            delta = self._enc_steps(cc_num, cc_val, 101)
        else:
            units = self.VERB_RANGES[verb][2]
            delta = (self._enc_steps_fixed(cc_num, cc_val, units) if units
                     else self._enc_steps(cc_num, cc_val, hi - lo + 1))
        if delta == 0:
            return
        value, to_base = tlib.mod_steer(self.mod, key, None, delta, lo, hi)
        if value is None or not to_base:
            return
        self.mod[key]["base"] = value
        with self.lock:
            self._render_display()

    def _verb(self, verb, channel, cc_num, cc_val):
        # A modulated verb is steered at its base and never at the engine.
        # First, before every other dispatch below, because a generated port
        # carries a modulator exactly as a memorable verb does.
        key = self._mod_key(channel, verb)
        if key in self.mod:
            self._mod_steer(key, cc_num, cc_val)
            return
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

        if verb == "lane" and voice:
            # The LANE column draws dead on a voice (law L4) and the knob must
            # agree with the picture. A voice's placement IS its rhythm
            # register, and a pad tap writes into that register - pruning it
            # here would silently undo a hand-tapped step.
            return

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

        if verb == "rotate" and voice:
            # THE SAME TRAP AS `length` AND `div` ABOVE, and it is the third
            # time this shape has appeared: `rotate` is a verb on BOTH kinds,
            # and the arm below runs the DRUM euclid path, which would rewrite
            # a Turing melody as a drum pattern. ROTATE on a voice moves the
            # rendered LINE instead - owner's decision, 2026-08-31.
            delta = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if delta:
                steps = max(1, self._steps(channel))
                # READ IT WHERE IT LIVES. `rotate` is in the LEGACY per-group
                # array self.rot, not in self.state - _LEGACY says so and
                # apply() writes it there. Reading self.state[channel] gave 0
                # every time, so every turn started from zero and the value
                # could only ever be +1 or -1: the owner saw it jump between
                # 1 and 15 on the first turn of this knob at the rig,
                # 2026-08-31.
                #
                # THIS IS THE THIRD TIME THIS EXACT SHAPE HAS SHIPPED, and
                # param_get's own docstring describes the second: SP8's
                # `range` alias read `range` and wrote `kit_range`, "so every
                # turn started from 2 again and only ever produced 1 or 3".
                # The rule the three of them share: a verb whose storage is
                # not self.state must be read through param_get, never through
                # the state dict directly.
                current = int(self.param_get(channel, "rotate") or 0)
                # CLAMPED, NOT WRAPPED - owner, 2026-08-31, at the rig, and it
                # is this surface's existing law rather than a new decision.
                # switch_step says it: "Where an ENCODER turn lands: clamped.
                # The knob and the button deliberately differ - a knob that
                # wrapped would jump from the last position to the first on a
                # single detent, which no hardware knob on this surface does."
                # Buttons wrap (switch_next); the PAGE RING wraps under the big
                # encoder (step_index); every parameter encoder clamps. The
                # drum ROTATE three thousand lines down already did.
                #
                # This wrap was inherited from the code as first written and
                # carried through two fixes in this same gate before anyone
                # turned the knob far enough to see it.
                self.apply(channel, "rotate",
                           max(0, min(steps - 1, current + delta)))
                with self.lock:
                    self._render_display()
            return

        if verb in self.SWITCH_VERBS:
            # RULE and LEAN. Clamped, never cyclic: the owner's law of
            # 2026-08-31, "it should reach upper and then stop or lower and
            # then stop - only the big one should cycle". One arm rather than
            # one each, so a third generator selector cannot arrive with a
            # different feel under the same hand.
            values = self.SWITCH_VERBS[verb]
            delta = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if delta:
                have = self.param_get(channel, verb)
                index = values.index(have) if have in values else 0
                want = values[tlib.switch_step(index, len(values), delta)]
                if want == have:
                    return
                self.apply(channel, verb, want)
                with self.lock:
                    # A placement change rewrites the line NOW rather than at
                    # the next wrap: HITS and ROTATE do the same, and a
                    # generator switch that took a bar to be heard would read
                    # as a knob that did not work.
                    if verb == "lean" and self.channel_kind(channel) == "drum":
                        self._write_pattern(channel)
                    self._render_display()
            return

        if verb == "model" and voice:
            # A two-way switch that takes its DIRECTION from the knob: right is
            # the walk, left is the register. It used to flip on any movement,
            # so it cycled - and the owner named the rule at the rig on
            # 2026-08-31: "it should reach upper and then stop or lower and
            # then stop - this should be default for all encoders - only the
            # big one should cycle through pages." That is switch_step's law,
            # which this arm was not going through.
            #
            # Discrete units still, or a nudge would change the generator under
            # the player's hand mid-bar.
            delta = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if delta:
                want = (tlib.MODEL_WALK if delta > 0
                        else tlib.MODEL_REGISTER)
                if want == self.state[channel].get("model",
                                                   tlib.MODEL_REGISTER):
                    return
                self.apply(channel, "model", want)
                with self.lock:
                    self._render_display()
            return

        if verb == "feed" and voice:
            # -1 is OFF and it is stored as None, because "no source" is not a
            # channel index and a sentinel integer in the state dict would be
            # one more thing every reader has to know. The wheel walks
            # -1..7 and skips this channel itself: a voice feeding itself is a
            # no-op, and a control that appears to do nothing is worse than one
            # that refuses.
            delta = self._enc_steps_fixed(cc_num, cc_val, ENC_UNITS_DISCRETE)
            if delta:
                st = self.state[channel]
                now = -1 if st.get("feed") is None else int(st["feed"])
                nxt = min(7, max(-1, now + delta))
                if nxt == channel:
                    nxt = min(7, max(-1, nxt + (1 if delta > 0 else -1)))
                self.apply(channel, "feed", None if nxt < 0 else nxt)
                with self.lock:
                    self._render_display()
            return

        if verb in ("hits", "rotate", "div", "length"):
            # THE CHANNEL IS PASSED, since 2026-09-01. _encoder used to read
            # self.group and ignore its caller's channel, which was safe while
            # these four only ever appeared on a channel-shaped page - there,
            # the caller's channel IS the selected one.
            #
            # The lens broke that. It spreads any channel verb across all
            # eight, so turning column F under the lens has to write channel
            # F; before this it wrote whichever channel happened to be
            # selected, while column F drew live and moved. Worse with a stale
            # lens verb: hold HITS from a drum, select a voice, turn a live
            # column, and the drum euclid path rewrites a Turing melody -
            # exactly what the kind guards further down exist to prevent,
            # re-entered through a different door.
            self._encoder(cc_num, cc_val, verb, channel)
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

        if self.mode == "VOLUME":
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

    def _reset_rhythm_mask(self, group):
        """Put every step back into the rhythm register.

        HITS, DIV and LENGTH are the START-AGAIN knobs. Owner's rule,
        2026-08-31: taps survive ROTATE and RHYTHM, and turning HITS overwrites
        them. DIV and LENGTH go with it because they change how many steps
        exist, so a mask meaning "steps 0, 5, 6 and 15" means something else
        the moment the grid is a different size.

        Without this there was no way back to a plain euclid line except
        tapping every removed step in by hand, because the mask persisted
        through everything once taps started living in it.
        """

        state = self.state.get(group)
        if state is not None:
            state["rhythm_reg"] = 0xFFFF

    def _encoder(self, cc_num, cc_val, verb, channel=None):
        """The four euclid parameters. They keep their own handler because
        each one has to re-clamp the others and rewrite the pattern, which the
        generic verb path deliberately does not do.

        `channel` defaults to the selected one so every existing caller keeps
        its meaning; the LENS passes a column index instead, because there the
        knob under your finger belongs to a channel you have not selected.

        THE KIND IS CHECKED HERE, not only at the callers. This is the drum
        euclid path - it rewrites the whole pattern from hits and rotation -
        and a voice's pattern comes from its shift register. The guards below
        for `div`, `length` and `rotate` on a voice were written when the only
        way in was a drum page; the lens can hand this any channel, so the
        refusal belongs at the door."""

        group = self.group if channel is None else int(channel)
        if verb in ("hits", "rotate") and self.channel_kind(group) != "drum":
            # A voice has no euclid field to turn. Its own ROTATE is a
            # different verb on a different page and goes through apply().
            return

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
            self._reset_rhythm_mask(group)
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
                self._reset_rhythm_mask(group)
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
                self._reset_rhythm_mask(group)
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
        self._recount_hits(group, note, steps)
        self.rot[group] = min(max(0, steps - 1), self.rot[group])
        logging.debug(f"Maschine group {group}: length beats={beats} steps={steps} "
                      f"hits={self.hits[group]}")
        self._render_pads()

    def _recount_hits(self, group, note, steps):
        """Re-read HITS from the notes actually in the pattern - but ONLY when
        the drum rhythm register is not thinning it.

        ONE PREDICATE, EVERY CALLER, because getting it wrong is a silent and
        COMPOUNDING fault rather than a visible one. The register is
        subtractive: the notes present are the euclid line minus whatever it
        masked off, so counting them sets HITS to the thinned total, and the
        next _write_pattern generates euclid at that lower number and masks it
        AGAIN. A channel would thin itself a little more at every wrap while
        encoder 1 read the shrinking number back as though a hand had turned
        it.

        Skipped exactly when it would lie, leaving HITS where the driver last
        put it - the same treatment ROTATION already gets, and for the same
        reason: _derive_params' own docstring says rotation is not recoverable
        from a pattern. Now neither is HITS, once the register is in play."""

        if steps <= 0:
            return
        full = (1 << steps) - 1
        mask = int(self.state.get(group, {}).get("rhythm_reg", 0xFFFF))
        if mask & full != full:
            return
        self.hits[group] = sum(
            1 for step in range(steps) if self.libseq.getNoteVelocity(step, note))

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

    def _pattern_note(self, group):
        """The pitch a generated drum pattern is written at.

        Extracted 2026-08-31 so the full rewrite and the in-place restyle
        below cannot drift about which note they are addressing - a restyle
        that guessed a different pitch would silently find no notes and do
        nothing, which is the quietest possible failure."""

        if self._is_sampler(group):
            return self._group_note(group)
        # Euclid on a synth is a root pulse: ROOT transposes it, OCTAVE
        # places it. Reusing whatever pitch _group_note discovers would
        # leave the voice stuck on an arbitrary note no control can reach.
        return tlib.pad_note(0, self.globals["root"], self.globals["scale"],
                             self.state[group].get("octave", 0))

    def _restyle_pattern(self, group):
        """Rewrite VELOCITY and STUTTER on the notes already there, without
        touching which steps sound.

        WHY THIS EXISTS. VELO and RATCHET change how a step sounds, not which
        steps sound - but the only write path was _write_pattern, which
        regenerates positions from euclid. So turning either one discarded any
        hand-placed step. The owner hit it at the rig on 2026-08-31: a hit
        tapped onto step 12 of group C vanished when RATCHET was turned up and
        euclid's own hit reappeared at step 1.

        The contract that documented the destruction named encoders 1-3, and by
        then SEVEN of the eight on a drum's STEP page were destructive. Owner's
        decision the same evening: fix VELO and RATCHET, leave RHYTHM.

        RHYTHM KEEPS THE FULL REWRITE, deliberately. It is a subtractive mask -
        it genuinely changes which steps sound - so regenerating is honest
        there, and pretending otherwise would need a second mechanism for a
        difference that is real.

        Addressed by the same note as the writer, through _pattern_note.
        """

        steps = self._steps(group)
        self._select_pattern(group)
        note = self._pattern_note(group)
        velocity = int(self.state[group].get("velo", 110))
        ratchet = int(self.state[group].get("ratchet", 1))
        stutter, stut_dur = tlib.ratchet_stutter(
            ratchet, self.libseq.getClocksPerStep())
        for step in range(steps):
            if not self.libseq.getNoteVelocity(step, note):
                continue
            self.libseq.setNoteVelocity(step, note, velocity)
            if self.has_stutter:
                # Assigned rather than nudged: changeStutterCountAll is a
                # RELATIVE change, so it cannot put a ratchet back to none.
                # Writing 0 here is what makes turning RATCHET down work.
                self.libseq.setStutterCount(step, note, stutter)
                self.libseq.setStutterDur(step, note, stut_dur)
        self.libseq.updateSequenceInfo()
        self._render_pads()

    def _write_pattern(self, group):
        """Regenerate a group's whole pattern from its euclid parameters.

        DESTRUCTIVE BY DESIGN: a pad tap is an edit that the next turn of a
        step-owning encoder wipes. That contract used to say "enc 1-3", which
        was true before LENGTH, VELO, RHYTHM and RATCHET existed and was wrong
        by four of them by 2026-08-31. The step-owning verbs are HITS, ROTATE,
        DIV, LENGTH and RHYTHM - the last because its mask genuinely decides
        which steps sound. VELO and RATCHET go through _restyle_pattern
        instead: they change how a step sounds, not which, and wiping the
        pattern was a side effect nobody asked for.

        setStepsPerBeat rescales the notes already in the pattern
        (pattern.cpp:665-681), which is why this clears and rewrites rather
        than editing in place."""

        label, spb, _ = lib.DIVISIONS[self.div[group]]
        beats = self.beats[group]
        steps = self._steps(group)
        self._select_pattern(group)
        note = self._pattern_note(group)

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
        # RATCHET: how many times a step fires inside its own slot, as zynseq's
        # native stutter. 1 writes nothing at all, so a pattern with the feature
        # unused is identical to one written before it existed.
        ratchet = int(self.state[group].get("ratchet", 1))
        stutter, stut_dur = tlib.ratchet_stutter(
            ratchet, self.libseq.getClocksPerStep())
        # THE DRUM RHYTHM REGISTER, and it is SUBTRACTIVE. Euclid has already
        # drawn the line; the register may take a hit away and may never invent
        # one, which is what keeps HITS meaning the number of hits. 0xFFFF -
        # every existing channel and every existing snapshot - removes nothing,
        # so a pattern written before this existed is written the same way now.
        # THE MASK ROTATES WITH THE LINE. Owner at the rig, 2026-08-31: with
        # two hits tapped out of five, rotating gave 5, 5, 3, 5, 5, 3 sounding
        # steps as the euclid line slid under a stationary mask. You do not
        # remove a POSITION, you remove a HIT, and it should stay removed
        # wherever the line is turned to.
        #
        # The voices have always done this - rotate_line turns "notes and rests
        # together" - so drums were the odd one out. Both rotations move the
        # same way: euclid at rot 1 lights steps 1, 3, 6 and tlib.rotate lights
        # the same three, verified before this was written.
        # THE PLACEMENT GENERATOR, 2026-09-01. `off` returns None and euclid
        # draws the line exactly as it always has, which is what makes every
        # existing channel and every existing snapshot bit for bit unchanged.
        # A lean is rotated by the same call euclid is, so ROTATE keeps doing
        # what it says on a leaning channel - see tlib.lean's docstring for why
        # anchoring it was refused.
        leaned = tlib.lean(steps, self.hits[group],
                           self.state[group].get("lean", tlib.LEAN_OFF))
        line = (lib.rotate(list(leaned), self.rot[group]) if leaned is not None
                else lib.build_pattern_steps(steps, self.hits[group],
                                             self.rot[group]))
        # THE LANE, 2026-09-01. It prunes the GENERATED line and never the
        # hand register: drum_steps below is subtractive, so a step the player
        # tapped OUT stays out, and a constraint that ran after it could not
        # put one back. On a voice this verb does not exist at all - a voice's
        # placement IS its rhythm register, which is where a tap lands.
        line = tlib.lane_filter(line, self.state[group].get("lane", 0))
        # THE FILL BAR, 2026-09-01. After the lane deliberately: the lane says
        # how far the GENERATOR may stray, and a fill is not the generator
        # straying - it is the phrase answering itself, and it is allowed to
        # be busier than the lane would let a bar be on its own. Before the
        # hand register, like everything else, so a step tapped out stays out.
        if group in self._fill_now:
            line = tlib.fill_line(line, self.state[group].get("fill", 0))
        pattern = tlib.drum_steps(
            line,
            tlib.rotate(int(self.state[group].get("rhythm_reg", 0xFFFF)),
                        steps, self.rot[group]))
        for step, on in enumerate(pattern):
            if on:
                self.libseq.addNote(step, note, velocity, 1.0, 0.0)
                if stutter and self.has_stutter:
                    # Written per note rather than pattern-wide: the installed
                    # API is setStutterCount(step, note, count), and there is a
                    # changeStutterCountAll() but it is a RELATIVE change, not
                    # an assignment.
                    self.libseq.setStutterCount(step, note, stutter)
                    self.libseq.setStutterDur(step, note, stut_dur)
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

        ONE MEANING IN EVERY MODE since 2026-09-01. CONTROL used to take the
        row for the page's parameter switches, which needed an exception
        (SHIFT + Fn handed mute back) and then an exception to the exception
        (MOD made the row inert) - and the second of those shipped as a bug:
        F_ROW_INERT returns (None,) * 8, which is not None, so under MOD the
        row was painted dark and advanced the switch anyway. Measured on the
        rig 2026-08-21.

        Nothing was lost giving the row back. A switch column's ENCODER
        already steps that switch through its own ticks - _verb_lv2 walks
        switch_spec/switch_step and draws the plugin's own word - so the
        button was a second route to a thing the knob above it already did,
        bought at the price of the row's only meaning.

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
        if self.erase_down:
            # WHILE ERASE IS HELD the row answers the question that gesture is
            # about to ask: which of these would LOSE something. ERASE + Group
            # is the one irreversible action on this panel - on a channel you
            # have played, it throws your take away and lets the machine
            # refill - and it had no warning at all, because a take on a
            # channel you are not looking at is invisible.
            #
            # Full for a channel that owns a take, the floor for one where the
            # gesture only silences (hits to 0, chance to 0 - both of which
            # you can simply turn back). Same shape as ARM's nomination row
            # above, and for the same reason: while a modifier is down this
            # LED answers exactly one question.
            return (BRIGHT_GROUP_MAX
                    if self.owner.get(group) == tlib.OWNER_PLAYER
                    else BRIGHT_GROUP_MIN)
        if self.arm_down:
            # While ARM is held the Group row stops reporting the mix and
            # starts reporting the NOMINATION - who survives the drop. It is
            # the only feedback the gesture has, and without it a player is
            # tapping buttons in the dark and finding out four bars later.
            #
            # Deliberately overriding mute and solo rather than blending with
            # them: three meanings on one LED is how "solo mode lit VOLUME"
            # went unnoticed for months. While the modifier is down the LED
            # answers exactly one question.
            return (BRIGHT_GROUP_MAX if group in self._drop_survivors
                    else BRIGHT_GROUP_MIN)
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

        # SP8's remembered kit centre names a note in the kit being REPLACED.
        # Carrying it across would centre the walk on whatever happens to sit
        # at that number in the new kit - or on nothing at all.
        self.state[group].pop("kit_centre", None)
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
        pos = self.libseq.getPlayPosition(self.bank, channel)
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
        if self.rec_down:
            self._slog("pad", result="down", pad=pad, note=note,
                       channel=channel, vel=velocity,
                       clock=self._play_clock(channel))

    def _pad_up(self, pad):
        """Release. Ends the note; the capture hangs off the same edge."""

        entry = self.held.pop(pad, None)
        if entry is None:
            if self.rec_down:
                # Released with nothing held: the press went somewhere else -
                # STEP mode's step toggle, or an overlay owner - and no note
                # can ever be captured from it.
                self._slog("pad", result="up with nothing held", pad=pad,
                           owner=self._pad_owner(), mode=self.mode)
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
            self._slog("capture_note", channel=channel, note=note,
                       written=False, why="no start")
            return
        cps = self.cps[channel]
        if cps <= 0:
            self._slog("capture_note", channel=channel, note=note,
                       written=False, why="cps", cps=cps)
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
        # Claimed BEFORE the note is written, not after. _claim wipes the
        # generator's line on a voice, so claiming afterwards would wipe the
        # very note that did the claiming - and claiming after the write is
        # what let a take sound ON TOP of the Turing line until 2026-08-22.
        self._claim(channel)
        # Overdub replaces rather than stacks: a second strike on the same step
        # and note updates its velocity and length.
        if self.libseq.getNoteVelocity(step, note):
            self.libseq.removeNote(step, note)
        vel = max(1, min(127, velocity))
        self.libseq.addNote(step, note, vel, duration, 0.0)
        self._slog("capture_note", channel=channel, note=note, written=True,
                   step=step, vel=vel, dur=duration)
        self.libseq.updateSequenceInfo()
        self.notes[channel][step] = (note, vel, duration)
        self._render_pads()

    def _claim(self, channel):
        """The first captured note makes the channel the player's.

        The owner flag is what enforces; forcing a voice to LOCK is what makes
        it visible on the surface."""

        if self.owner[channel] == "player":
            return
        self.owner[channel] = "player"
        kind = self.channel_kind(channel)
        if tlib.claim_clears(kind):
            # The take REPLACES the generated line rather than landing on top
            # of it. Owner, 2026-08-22, after hearing both at once on the rig.
            # Safe to lose: the line is reproducible from the register, and
            # ERASE + Group brings it straight back.
            #
            # After owner is set, never before - clearing first and claiming
            # second leaves a window in which the poll thread's wrap sees an
            # unowned empty pattern and refills it.
            self._select_pattern(channel)
            self.libseq.clear()
            self.libseq.updateSequenceInfo()
        if kind == "voice":
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
        # The remembered kit centre belongs to the kind being left.
        self.state[channel].pop("kit_centre", None)
        self.stash[channel][old] = self.state[channel]
        self.stash[channel][old + ":hits"] = self.hits[channel]
        self.stash[channel][old + ":rot"] = self.rot[channel]
        # CARRY WHAT BELONGS TO THE CHANNEL. A stashed set already holds it;
        # a freshly built one does not, and that was a real defect found at
        # the rig - a first switch to a kind rebuilt the state from defaults,
        # which put CHANCE back to 100 in the driver's mirror while the
        # SEQUENCER kept the pattern's real value. The display read 100 and
        # the channel played thinner than that, which is the one lie this
        # surface may not tell: the number a player checks when something goes
        # quiet was the number that was wrong.
        #
        # Carried either way, not only on a fresh build: a stash taken before
        # this fix can hold the same stale mirror, and a channel switched back
        # and forth twice would otherwise restore it.
        previous = self.state[channel]
        arriving = self.stash[channel].get(new)
        if arriving is None:
            arriving = tlib.default_channel_state(new)
        self.state[channel] = tlib.carry_channel_scoped(previous, arriving)
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

        return self.libseq.getPlayState(self.bank, group) & 0xFF

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
            self._phrase_anchor = self._elapsed_beats()
            self._phrase_bar = 0
            # Anything armed with the transport stopped gets its landing bar
            # now, counted from this bar zero.
            for macro, bars in self._armed_while_stopped.items():
                self._pending_macros.arm(macro, bars, at_bar=0)
            self._armed_while_stopped.clear()
        else:
            # Stopping the rig must not leave a held pad droning over silence.
            self._release_all()
            self._phrase_anchor = None
            self._phrase_bar = None
        self._slog("transport",
                   state="start" if target == zynseq_lib.SEQ_STARTING
                   else "stop",
                   anchor=self._phrase_anchor, bar=self._phrase_bar,
                   pending=self._pending_macros.pending())
        for group in range(8):
            self.libseq.setPlayState(self.bank, group, target)
        self._render_pads()
        self._render_transport()

    def _toggle_rhythm_step(self, step):
        """A pad tap on EITHER KIND: flip that step in the rhythm register.

        Drums joined voices here on 2026-08-31, when they got a rhythm
        register of their own. Before that a drum tap edited the pattern
        directly and the next encoder turn wiped it.

        The rewrite goes through _write_voice_pattern, which returns early on
        a player-owned channel - so a REC take is not disturbed by tapping,
        the same protection both evolve knobs already get.

        The tap is refused past the end of the pattern: a 12-step triplet
        division must not set bit 13 and have it reappear when the division
        changes back."""

        channel = self.group
        st = self.state[channel]
        voice = self.channel_kind(channel) == "voice"
        # A VOICE's register spans the division's own step count; a DRUM's
        # pattern is as long as LENGTH makes it, and a bit set past the end
        # would reappear when the length changed back.
        steps = lib.step_count(self.div[channel]) if voice \
            else self._steps(channel)
        if not 0 <= step < steps:
            return
        # The register is stored UNROTATED and rotated onto the grid when the
        # pattern is written, so a tap on grid step `step` has to come back the
        # other way to reach the bit behind it. A drum only: a voice's rotation
        # is applied to the rendered line rather than to the mask.
        bit = step if voice else (step - self.rot[channel]) % steps
        st["rhythm_reg"] = tlib.rhythm_toggle(st["rhythm_reg"], bit)
        if voice:
            # BY HAND: a tap is honoured even on a channel the player owns.
            # It used to be silently refused, which is the same fault as a dead
            # knob - the player asked for a step and nothing happened and
            # nothing said why.
            self._write_voice_pattern(channel, by_hand=True)
        else:
            # The drum's own writer. It reads rhythm_reg as a subtractive mask
            # over the euclid line, so the flipped bit takes effect on this
            # rewrite exactly as a turn of RHYTHM would.
            with self.lock:
                self._write_pattern(channel)
            # A DRUM TAP HAS ALWAYS MADE A SOUND, and it must keep doing so.
            # The old drum path previewed the note it had just written; this
            # one writes no note, so the preview has to be explicit or tapping
            # a pad in STEP mode goes silent - a feel regression that would
            # read as the tap being ignored.
            self._preview(self._group_note(channel))
        with self.lock:
            self._render_pads()

    def _toggle_step(self, step, velocity=None):
        """A pad tap toggles a step. The tap's own velocity becomes the step's
        velocity, so a hard tap is an accent - free, because the hardware
        already reads it.

        On a VOICE this flips a bit in the channel's rhythm register and lets
        the generator rewrite, rather than editing the pattern directly. The
        steps become the generator's own state, so nothing wipes them and they
        persist in the snapshot for free - which is what makes "tap steps 1
        and 9, then evolve only the notes on them" possible at all. Until
        2026-08-16 this docstring warned that the next encoder turn would wipe
        a hand edit; on a voice that is no longer true.

        A DRUM DOES THE SAME SINCE 2026-08-31, and the reason it did not is
        the reason it now can. The old docstring said "a drum is euclidean, its
        rhythm is HITS and ROTATE, and the generator owns the pattern" - true
        until the drum rhythm register shipped the same day. Drums have the
        mask now, so a drum tap flips a bit in it exactly as a voice tap does,
        and a hand-chosen step survives HITS, ROTATE, DIV, LENGTH and RHYTHM
        instead of being wiped by whichever of them moved next. The owner asked
        for it after watching a tapped step disappear twice in one evening.

        WHAT IT COSTS, and it is a real trade rather than a free win. The mask
        is SUBTRACTIVE: a tap can now silence a step euclid placed, or restore
        one the register had removed, but it cannot invent a hit where euclid
        put none. It also loses the per-step accent - the tap's velocity used
        to become that note's velocity - because a mask bit has no room for a
        number. That accent never survived a regeneration anyway, so what is
        lost is a transient the next encoder turn erased."""

        self._toggle_rhythm_step(step)

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

    def _kit_centre(self, channel):
        """The note SP8's kit window centres on: the drum this channel plays.

        REMEMBERED, NEVER REDISCOVERED, and that is the whole point.
        _group_note() reads the note back out of the PATTERN, so using it as
        the centre made a feedback loop: the walk wrote a higher note, home was
        rediscovered there, the next walk centred on that, and the channel
        marched up the kit until it was in keys with nothing mapped. Measured
        on the rig 2026-08-19 - group A had drifted from note 36 to 64 and gone
        silent, which reads as a dead channel rather than a wandering one.

        Captured once, on the first walk, and cleared whenever the kit or the
        kind changes - the two events after which the old centre means nothing.
        """

        st = self.state[channel]
        centre = st.get("kit_centre")
        if centre is None:
            centre = self._group_note(channel)
            st["kit_centre"] = centre
        return centre

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
            # SP8: RANGE narrows the walk to part of the kit, centred on the
            # channel's own drum. It reads `kit_range`, NOT `range`, and the
            # difference is a compatibility rule rather than a style choice:
            # `range` is the VOICE's octave spread and defaults to 2, so a
            # sampler channel switched to Turing would have narrowed to half
            # its kit the day SP8 landed - including channel E of the factory
            # snapshot, which ships switched. `kit_range` defaults to 4, the
            # whole kit, so every existing snapshot walks exactly as before.
            #
            # The RANGE COLUMN edits this on a sampler channel, because octave
            # spread means nothing there - the kit walk ignores pitch entirely.
            # Same column, different value, chosen by the ENGINE: the pattern
            # CONTROL already follows.
            notes = tlib.kit_line(st["register"], st["length"], steps, kit,
                                  kit_range=st.get("kit_range", 1),
                                  centre=self._kit_centre(channel))
            # An unreadable or empty kit degrades to the channel's own drum,
            # never to silence.
            return notes or [self._group_note(channel)] * steps
        if st.get("model") == tlib.MODEL_WALK:
            # A bounded random walk instead of the shift register. Same root,
            # same scale, same octave and range - only where the VALUES come
            # from changes, which is why this is a model and not a kind.
            #
            # The register is the walk's starting point, so switching models
            # back and forth does not teleport the line somewhere unrelated.
            # SEEDED, so this is a pure function of stored state. _voice_line
            # is called by the writer AND by both pad renderers; unseeded, each
            # call invented a different melody, the pads never showed the line
            # that was playing, and the repaint rate reached 109 OSC messages a
            # second against 6.6 idle - inside the band that wedges the
            # controller. Owner found it at the rig, 2026-08-31.
            #
            # The seed advances at the WRAP, where the register would have
            # mutated, so the walk evolves once a bar instead of five times a
            # second - and RANDOM at 0 holds it, which is this instrument's
            # existing grammar for LOCK.
            return tlib.walk_line(st["register"], st["length"], steps,
                                  self.globals["root"], self.globals["scale"],
                                  st["octave"], st["range"],
                                  st.get("walk_span", 32),
                                  st.get("walk_stride", 4),
                                  rng=tlib.walk_rng(st.get("walk_seed", 0)))
        return tlib.line(st["register"], st["length"], steps,
                         self.globals["root"], self.globals["scale"],
                         st["octave"], st["range"])

    def _voice_line(self, channel, steps):
        """(notes, mask) for a voice: what each step plays and whether it
        sounds, ROTATED. The single place ROTATE is applied.

        It has to be single. _step_notes and _step_note derive the pitch a
        step carries so the pads can query it, and _write_voice_pattern writes
        it - and _step_note's own docstring says that if the two disagree the
        pads query a note that is not there and every step reads as empty.
        Rotation applied in the writer alone did exactly that: the pattern
        moved and the renderer kept asking about the unrotated line.

        Notes and mask go through rotate_line together, in one call, because
        rotating them apart gives a melody that slides while its rhythm stands
        still."""

        st = self.state[channel]
        notes = self._voice_notes(channel, steps)
        mask = tlib.rhythm_mask(st.get("rhythm_reg", 0xFFFF), steps)
        # ROTATE IS NOT IN self.state. It is in the legacy per-group array
        # self.rot - _LEGACY says so, apply() writes it there, and param_get
        # is the accessor that knows. Reading the state dict here returned 0
        # forever, so the line was rotated by nothing: the owner turned ROTATE
        # on a voice at the rig on 2026-08-31, watched the value count
        # correctly, and heard the sound never change.
        #
        # The value read correctly on the display because the display goes
        # through param_get. Two readers of one verb disagreeing about where
        # it lives is what makes this shape so quiet - and this is its FOURTH
        # appearance. See the note at the ROTATE encoder path.
        notes, mask = tlib.rotate_line(
            notes, mask, int(self.param_get(channel, "rotate") or 0))
        # THE FILL BAR, after the rotation: the fill answers the bar as it is
        # actually heard, not as it was before it was turned. The pads read
        # this same function, so the picture shows the fill too - which is the
        # point. A voice's rests ARE its rhythm register, so filling the mask
        # is filling the line.
        if channel in self._fill_now:
            mask = tlib.fill_line(mask, self.state[channel].get("fill", 0))
        return notes, mask

    def _step_notes(self, channel, steps):
        """The note each step carries, as a list. Computed once per repaint:
        deriving it per pad meant recomputing the whole line sixteen times,
        five times a second, for one answer."""

        if self.channel_kind(channel) != "voice":
            return [self._group_note(channel)] * steps
        notes, _mask = self._voice_line(channel, max(1, steps))
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
        notes, _mask = self._voice_line(channel, steps)
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
        playpos = self.libseq.getPlayPosition(self.bank, group)
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

        for channel in range(len(tlib.CHANNELS)):
            try:
                self._wrap_channel(channel)
            except Exception as e:
                # PER CHANNEL, deliberately. A single raise used to abort the
                # whole sweep, so every channel after the bad one missed its
                # wrap - and since the channels are walked in a fixed order,
                # the same ones lost it every time. The bad channel is the
                # one that stops evolving; the others must not pay for it.
                self._log_poll_error(f"voice wrap on channel {channel}", e)

    def _reanchor_phrase(self):
        """Take back a fraction of the phrase clock's drift, once a bar.

        MEASURED BEFORE IT WAS CORRECTED, 2026-08-21: `_elapsed_beats()`
        integrates getTempo() against the MONOTONIC clock while the sequencer
        advances on the AUDIO clock, and the two slip **3,896 ppm** - a whole
        bar every 8.3 minutes, linear to within one poll tick over 350 bars.
        `notes/findings/2026-08-21-phrase-clock-drift.md` has the series.

        Linear is what makes this safe. The error is taken back a QUARTER at a
        time rather than snapped out, because this clock is also the countdown
        a player is reading: a count that jumps backward mid-drop is worse
        than one that is a poll tick late, and the drift needs a fraction of
        the correction rate available here.

        The reference is the SELECTED channel's own play position, held as a
        phase rather than a count. Re-seeded rather than nudged whenever it
        stops being comparable - a different channel, a different pattern
        length, or an error too large to be drift, which is what a RESTART
        looks like from in here.

        Costs one locked read a bar. Silently does nothing if the pattern
        geometry is unusable: no correction is always better than a wrong one
        on the clock every timed gesture in the instrument resolves against."""

        channel = self.group
        cps = self.cps[channel]
        spb = lib.DIVISIONS[self.div[channel]][1]
        cpb = float(cps or 0) * float(spb or 0)
        length = cpb * float(self.beats[channel] or 0)
        if cpb <= 0.0 or length <= 0.0:
            return
        with self.lock:
            pos = self._play_clock(channel)
        if pos is None:
            self._phrase_ref = None
            return

        ref = self._phrase_ref
        if ref is None or ref[0] != channel or ref[2] != length:
            self._phrase_ref = (channel, pos, length, cpb)
            return

        err = tlib.phase_error(pos, ref[1], length)
        if err is None:
            return
        if abs(err) > length / 4.0:
            # Not drift. A RESTART, a length change, or a reading taken while
            # the pattern moved under us - re-seed rather than haul the clock
            # a quarter of a bar toward a number that means something else.
            self._phrase_ref = (channel, pos, length, cpb)
            return

        move = (err / cpb) * PHRASE_REANCHOR_GAIN
        move = max(-PHRASE_REANCHOR_MAX_BEATS,
                   min(PHRASE_REANCHOR_MAX_BEATS, move))
        # MINUS. The anchor is subtracted from elapsed beats, so a sequencer
        # running AHEAD - a positive error - has to make the next bar arrive
        # SOONER, which means a smaller anchor.
        self._phrase_anchor -= move
        if self._slog_fh is not None:
            self._slog("reanchor", bar=self._phrase_bar, pos=pos, ref=ref[1],
                       err=round(err, 2), move=round(move, 5))

    def _fill_tick(self, bar):
        """Turn each channel's fill bar on and off at the boundary.

        ONLY FOR CHANNELS WHOSE ANSWER CHANGED. Rewriting eight patterns every
        bar would be the write burst this design has avoided everywhere else; a
        channel on a one-bar phrase, or with the fill at zero, is never touched
        at all.

        Gated through generator_may_write like every other generator, so FREEZE
        holds the fill, a player-owned channel never has one written over its
        take, and MOVE at LOCK means what it says. "fill" joined
        FREEZE_GENERATIVE in the same commit as this caller - the standing
        lesson from `rhythm`, which sat in that set for months with nothing
        asking and was correct only by the accident of an early return."""

        for channel in range(len(tlib.CHANNELS)):
            phrase = int(self.param_get(channel, "phrase") or 1)
            fill = int(self.param_get(channel, "fill") or 0)
            want = fill > 0 and tlib.is_fill_bar(bar, phrase)
            if want == (channel in self._fill_now):
                continue
            if not tlib.generator_may_write("fill", self.frozen,
                                            self.freeze_deep,
                                            self.owner.get(channel),
                                            move=self._move_of(channel),
                                            roll=self._move_roll()):
                continue
            if want:
                self._fill_now.add(channel)
            else:
                self._fill_now.discard(channel)
            try:
                with self.lock:
                    if self.channel_kind(channel) == "voice":
                        self._write_voice_pattern(channel)
                    else:
                        self._write_pattern(channel)
            except Exception as e:
                # The flag is set either way, so the next bar puts the channel
                # back rather than leaving it stuck inside a fill.
                self._log_poll_error(f"fill bar ch{channel}", e)

    def _phrase_tick(self):
        """Advance the phrase clock and fire anything the bar has reached.

        Runs at 30 Hz, so a boundary is caught within ~33 ms - about 1.7% of a
        bar at 125 BPM. Adequate for mutes and levels. NOTHING that needs step
        accuracy may ride this clock.

        Deliberately NOT in _wrap_channel: a wrap is per channel, and eight
        channels have eight different bars the moment anyone uses an odd
        length. One transport-anchored count is the only one that stays true
        for all of them."""

        if self._phrase_anchor is None:
            return
        bar, _frac = tlib.phrase_pos(self._elapsed_beats(), self._phrase_anchor)
        if bar == self._phrase_bar:
            return
        self._phrase_bar = bar
        self._reanchor_phrase()
        if self._slog_fh is not None:
            # DRIFT PROBE. _elapsed_beats() integrates getTempo() against the
            # MONOTONIC clock; the sequencer advances on the AUDIO clock. Same
            # tempo number, two time bases, and the spec declined to correct a
            # drift nobody had measured.
            #
            # Phase slip, not absolute counting: sample the sequencer's OWN
            # play position at each phrase-bar tick. If the two clocks agree
            # the number sits still, jittering by up to one poll tick. If they
            # drift it WALKS, monotonically, and the rate is the answer. No
            # wrap accumulation and no second counter to get wrong.
            # ONE locked section for BOTH zynseq reads. libzynseq is not
            # thread-safe and this runs on the poll thread; an unlocked reach
            # into it once took the whole UI down with SIGSEGV mid-jam.
            # _elapsed_beats takes the lock itself and self.lock is an RLock,
            # so calling it in here is safe and keeps the tempo read and the
            # position read on the same side of one acquire - which they must
            # be, or the two numbers describe different instants and the drift
            # they are measuring is the thing that separates them.
            with self.lock:
                bpm = self.libseq.getTempo()
                pos = self._play_clock(self.group)
                beats = self._elapsed_beats()
            self._slog("drift", bar=bar, beats=round(beats, 4), pos=pos,
                       group=self.group, bpm=bpm,
                       mono=round(time.monotonic() - self._t0, 4))
        if self._pending_macros.pending() or self._frozen("macro"):
            # GATED on purpose: a bar with nothing armed and nothing frozen
            # writes no line at all, so an idle jam costs the log nothing and
            # the write budget stays where the animations left it.
            self._slog("bar", bar=bar, frozen=self._frozen("macro"),
                       latch=self.frozen, deep=self.freeze_deep,
                       pending=self._pending_macros.pending(),
                       due={m: self._pending_macros.remaining(m, bar)
                            for m in self._pending_macros.pending()})
        if self._frozen("macro"):
            # HELD, NOT DROPPED. The queue is not drained at all while frozen,
            # so everything armed keeps its place and lands on the first bar
            # after the thaw. Draining and discarding would eat a gesture the
            # player made and the countdown is still advertising.
            #
            # Found by playing it, 2026-08-20: an armed DROP fired while
            # frozen and, with no survivors nominated, muted all eight
            # channels. FREEZE promises that nothing changes under you, and a
            # macro landing is the largest change this instrument makes.
            with self.lock:
                self._render_display()
                self._render_transport()
            return
        self._fill_tick(bar)
        if self._bank_pending is not None:
            # THE BANK LANDS ON THE BAR, and after the freeze gate above: a
            # whole arrangement is the largest change this instrument makes,
            # and FREEZE promises nothing changes under you.
            #
            # Popped before it is taken, so a raise cannot leave a bank queued
            # forever with a green pad advertising a switch that will never
            # happen.
            want, self._bank_pending = self._bank_pending, None
            try:
                with self.lock:
                    self._bank_switch(want)
            except Exception as e:
                self._log_poll_error(f"bank switch to {want}", e)
        if self._note_expires is not None and bar >= self._note_expires:
            # A refusal note lives exactly as long as the macro would have.
            self._note_expires = None
            self._timescale_note = None
            with self.lock:
                self._render_display()
        for macro in self._pending_macros.due(bar):
            self._slog("due", macro=macro, bar=bar)
            try:
                self._fire_macro(macro, bar)
            except Exception as e:
                # PER MACRO, the same reason _voice_wraps catches per channel:
                # a single raise would abort the rest of the drain, and in a
                # fixed order the same macros would lose it every time.
                self._log_poll_error(f"macro {macro}", e)
        self._chance_tick(bar)
        self._ratchet_tick(bar)
        self._gate_tick(bar)
        self._walk_tick(bar)
        with self.lock:
            self._render_display()
            self._render_transport()
            # ASK WHO OWNS THE PADS. Both of these used to paint on the bare
            # held flag, so with MOD latched and SELECT held - which is the
            # RISE gesture - the ARM legend overwrote the MOD menu once a bar
            # and something else painted it back: amber pads flashing over a
            # grid that belonged to MOD. Seen by the owner, 2026-08-20.
            #
            # _pad_owner is the single predicate for exactly this question and
            # these two were the only writers not asking it.
            owner = self._pad_owner()
            if owner == "navigate":
                # One pad per bar, so the lit pad has to advance here.
                self._paint_phrase_pads()
            if owner == "arm":
                # The ruler loses a pad per bar, so it has to be repainted
                # here. Only while ARM is actually held: the grid is the step
                # picture the rest of the time and repainting it every bar
                # would fight the playhead.
                self._paint_arm_legend()

    def _ratchet_tick(self, bar):
        """Walk a running RATCHET ramp one bar. ONCE PER BAR.

        Written through apply(ch, "ratchet", n) - the SHIPPED path, which
        reaches _write_pattern and computes the stutter count AND its duration
        from ratchet_stutter(). That pairing is the whole reason this route
        was taken over the in-place changeStutterCountAll:

        - Both stutter-all calls are RELATIVE and clamped, not assignments
          (pattern.cpp:485-509), and _write_pattern already carries a comment
          saying so.
        - A fresh StepEvent defaults its duration to ONE CLOCK. Bumping the
          count without moving the duration emits events that fall outside the
          note, and on a LinuxSampler one-shot that is inaudible - the exact
          mistake that made x2 sound identical to OFF, twice, by ear.
        - The in-place route also assumes every NOTE_ON in the pattern carries
          the same stutter values, which the touchscreen pattern editor can
          break behind us.

        Its cost is that _write_pattern regenerates from euclid, so this is
        confined to generated_channels() and a recorded take never ratchets.
        That is the trade, written down rather than discovered later."""

        if not self._ratchet_ramp:
            return
        ramp = self._ratchet_ramp
        step = bar - ramp["start"]
        if step >= ramp["bars"]:
            for channel, base in ramp["base"].items():
                self.apply(channel, "ratchet", base)
            self._ratchet_ramp = None
            return
        value = tlib.ratchet_rung(step, ramp["bars"])
        for channel in ramp["base"]:
            self.apply(channel, "ratchet", value)

    def _break_fire(self, bars):
        """The nominated channels fall out NOW and come back on the landing.

        DROP with its two ends swapped, sharing every piece of its
        bookkeeping: the same survivors, the same capture, the same restore.
        The survivors are the ones that KEEP PLAYING in both - so a player who
        has learnt the nomination for one already knows it for the other.

        Poll thread, drained from _break_due. See _arm_pad for why."""

        mixer = self.state_manager.zynmixer
        self._drop_restore = {}
        for group in range(8):
            chan = self._mixer_chan(group)
            if chan is None:
                continue
            self._drop_restore[group] = bool(mixer.get_mute(chan))
            if group not in self._drop_survivors:
                mixer.set_mute(chan, True, update=True)
        bar = self._phrase_bar
        if bar is None:
            # Stopped. Nothing is counting, so hold the length and let the
            # transport start arm the return - the same rule _arm_pad already
            # applies to everything else armed while stopped.
            self._armed_while_stopped["break_end"] = bars
        else:
            self._pending_macros.arm("break_end", bars, bar)
        self._arm_bars["break_end"] = bars
        with self.lock:
            self._render_mutes()
            self._render_groups()
            self._render_display()

    def _timescale_fire(self, macro, bar):
        """Take every generated channel to half or double speed.

        THE TRANSFORM IS NOT A DIV MOVE. tlib.time_scale halves the steps per
        beat AND doubles the beat count, which keeps beats * spb - the step
        count the sixteen pads draw - invariant. That is what makes it the
        same rhythm slower rather than a coarser rhythm at the same speed, and
        it is also why _clamp_params never fires: the new length always fits
        the grid exactly.

        Structure lands at the channel's own wrap, through the pending set
        that already ships. THE LIMIT THAT CREATES, on the record: the macro
        fires on the PHRASE bar and pending is taken at each channel's wrap,
        which are the same moment only when every channel's length divides the
        bar. Under polymeter - which already ships - a 3-beat channel takes it
        up to three beats late. Accepted deliberately: writing immediately
        would rewrite mid-bar and trip the groove, which is what law L2 exists
        to stop, and firing per channel would turn one musical event into
        eight."""

        factor = 0.5 if macro == "half" else 2.0
        channels = tlib.generated_channels(self.owner, len(tlib.CHANNELS),
                                       moves=self._moves(),
                                       roll=self._move_roll)
        moved = 0
        with self.lock:
            for channel in channels:
                got = tlib.time_scale(self.div[channel], self.beats[channel],
                                      factor)
                if got is None:
                    # This channel's division has nowhere to go - four of the
                    # six do not, in one direction or the other. Skipped, and
                    # counted, so the label can say so.
                    continue
                self._timescale_restore[channel] = (
                    self.div[channel], self.beats[channel],
                    self.hits[channel], self.rot[channel])
                self.div[channel], self.beats[channel] = got
                self.state[channel]["pending"].add("div")
                self.state[channel]["pending"].add("length")
                moved += 1
        self._timescale_note = (macro.upper(), moved, len(channels))
        # A macro that RUNS must not inherit a refusal's expiry - its own
        # restore leg owns the clearing.
        self._note_expires = None
        bars = self._arm_bars.get(macro, 4)
        self._pending_macros.arm("timescale_end", bars, bar)
        self._arm_bars["timescale_end"] = bars
        logging.info("Maschine: %s took %d of %d channels",
                     macro, moved, len(channels))
        with self.lock:
            self._render_display()

    def _timescale_restore_apply(self):
        """Put back the captured tuple, and regenerate from it.

        Restoring through the pending set rather than writing now, for the
        same reason the move itself lands there: structure belongs on the bar.

        A channel the player has since turned DIV on by hand is left alone.
        A macro must not overwrite a deliberate move made after it was armed -
        the take-back rule points the other way."""

        with self.lock:
            for channel, (div, beats, hits, rot) in \
                    list(self._timescale_restore.items()):
                self.div[channel] = div
                self.beats[channel] = beats
                self.hits[channel] = hits
                self.rot[channel] = rot
                self.state[channel]["pending"].add("div")
                self.state[channel]["pending"].add("length")
        self._timescale_restore = {}
        self._timescale_note = None
        with self.lock:
            self._render_display()

    def _chance_tick(self, bar):
        """Walk a running CHANCE ramp one bar. ONCE PER BAR, never on the
        200 ms modulator tick.

        setPlayChance is read live in Track::getEvent(), so this costs no
        pattern rewrite at all - the whole breakdown is one shipped verb
        called eight times a bar. That is also why it is safe on a
        player-owned channel: nothing is regenerated and no take is touched.

        At chance 0 a tab still draws dashed. The silent-channel law does not
        pause for a performance macro."""

        if not self._chance_ramp:
            return
        ramp = self._chance_ramp
        step = bar - ramp["start"]
        floor = tlib.CHANCE_RUNGS[-1]
        for channel, base in ramp["base"].items():
            self.apply(channel, "chance",
                       tlib.chance_ramp(base, floor, step, ramp["bars"]))
        if step >= ramp["bars"]:
            self._chance_ramp = None

    def _gate_fire(self, bar):
        """Arm a gate collapse: capture every note that will be shortened.

        VOICES ONLY, and that is a measurement rather than a scope decision.
        The five drum channels play LinuxSampler one-shots, which run to the
        end of the sample whether or not the note is shortened - the same
        measurement that killed choke groups. Collapsing a drum channel would
        change the pattern, cost eight rewrites and produce no sound anybody
        could hear, so it is refused and the note says how many channels took
        it. A macro that appears to fire on eight channels and is audible on
        three is worse than one that says three.

        THE CAPTURE IS THE FEATURE. There is no setNoteDuration in the
        installed API, so a restore is remove-and-re-add - which drops the
        note's ratchet and stutter unless they were captured too. And the
        obvious shortcut, changeDurationAll, was measured and is asymmetric: it
        returns out of its whole loop the moment any event would reach <= 0, so
        a decrement leaves the pattern half changed, and it clamps at 0.1, so
        the inverse does not restore what was there. Nothing here computes an
        inverse; it rebuilds from what was read."""

        channels = [ch for ch in tlib.generated_channels(self.owner,
                                                         len(tlib.CHANNELS),
                                                         moves=self._moves(),
                                                         roll=self._move_roll)
                    if self.channel_kind(ch) == "voice"]
        captured = {}
        with self.lock:
            for channel in channels:
                captured[channel] = self._capture_notes(channel)
        if not captured:
            self._timescale_note = ("TIGHT", 0, len(tlib.CHANNELS))
            self._note_expires = None
            return
        self._gate_ramp = {
            "bars": self._arm_bars.get("gate", 4),
            "start": bar,
            "notes": captured,
        }
        self._timescale_note = ("TIGHT", len(captured), len(tlib.CHANNELS))
        self._note_expires = None

    def _capture_notes(self, channel):
        """Every note in a channel's pattern, with everything a rewrite needs.

        Duration, velocity AND the stutter pair, because remove-and-re-add is
        the only way back and it starts from nothing. Called under the lock;
        selectPattern exactly once, like every other burst here."""

        self._select_pattern(channel)
        steps = self.libseq.getSteps()
        # ASK THE ONE SOURCE which note a step carries rather than scanning all
        # 128. A blind scan is 2048 getNoteVelocity calls per channel under the
        # lock, and libzynseq is not thread-safe - the poll thread, the MIDI
        # handler and the queued handler all reach it, and a burst that size on
        # a macro landing is the shape of the SIGSEGV this driver survived once.
        line = self._step_notes(channel, steps)
        out = []
        for step in range(steps):
            for note in {line[step]}:
                velocity = self.libseq.getNoteVelocity(step, note)
                if not velocity:
                    continue
                duration = float(self.libseq.getNoteDuration(step, note))
                stutter = (0, 0)
                if self.has_stutter:
                    try:
                        stutter = (int(self.libseq.getStutterCount(step, note)),
                                   int(self.libseq.getStutterDur(step, note)))
                    except Exception:
                        pass
                out.append((step, note, int(velocity), duration, stutter))
        return out

    def _gate_tick(self, bar):
        """Walk a running gate collapse one bar. ONCE PER BAR.

        Rewrites the pattern, so it obeys the same law drift does - and unlike
        the CHANCE ramp, which costs no pattern write at all and is therefore
        safe anywhere, this one has to re-ask ownership EVERY BAR. A player can
        start recording onto a channel four bars into a build, and the capture
        taken at fire time cannot see that coming.

        A channel that leaves the set keeps its captured notes: dropping them
        would mean the restore had nothing to put back, and the channel would
        stay collapsed for as long as the pattern lived."""

        if not self._gate_ramp:
            return
        ramp = self._gate_ramp
        step = bar - ramp["start"]
        factor = tlib.gate_ramp(step, ramp["bars"])
        for channel, events in ramp["notes"].items():
            if not tlib.generator_may_write("macro", self.frozen,
                                            self.freeze_deep,
                                            self.owner.get(channel),
                                            move=self._move_of(channel),
                                            roll=self._move_roll()):
                continue
            self._write_captured(channel, events, factor)
        if step >= ramp["bars"]:
            # Landed: the last write above already restored full length,
            # because gate_ramp returns 1.0 at and past the end.
            self._gate_ramp = None

    def _write_captured(self, channel, events, factor):
        """Rewrite one channel's notes at `factor` of their captured length.

        Always from the CAPTURE, never from what is currently in the pattern:
        scaling what is already scaled compounds, and the floor would make it
        irreversible after two bars."""

        with self.lock:
            self._select_pattern(channel)
            for step, note, velocity, duration, (count, dur) in events:
                self.libseq.removeNote(step, note)
                self.libseq.addNote(step, note, velocity,
                                    tlib.collapse_duration(duration, factor),
                                    0.0)
                if count and self.has_stutter:
                    # Re-applied because remove-and-re-add starts from nothing.
                    # Without this a build would quietly strip the ratchet off
                    # every note it touched, and the ROLL macro would come back
                    # to a pattern that had lost it.
                    self.libseq.setStutterCount(step, note, count)
                    self.libseq.setStutterDur(step, note, dur)
            self.libseq.updateSequenceInfo()

    def _walk_tick(self, bar):
        """The chord walker: move the shared root every N bars.

        THE GLOBAL-SCALE HALF OF THIS ALREADY SHIPPED and the internal list
        said otherwise for months - ROOT and SCALE have been global verbs
        driving all three voices, landing on the bar through _key_dirty, since
        long before this. Only the walk was missing, which is why this is one
        short method rather than a feature.

        Held by FREEZE like every other bar-rate machine: a key change is one
        of the largest things that can happen under a player who has asked for
        nothing to change. It goes through apply_global(), the single write
        path, so the display, the pending brackets and the voices cannot
        disagree about what key the instrument is in."""

        every = int(self.globals.get("walk", 0))
        if not tlib.walk_due(bar, every):
            return
        if self._frozen("walk"):
            return
        if self.walk_base is None:
            # First move of the session: the root the player left on the knob
            # is the base, and every degree is measured from it.
            self.walk_base = self.globals["root"]
        span = int(self.globals.get("wspan", 2))
        base = self.walk_base
        degree = tlib.walk_next(self.walk_degree, span)
        root = tlib.walk_root(base, degree, self.globals["scale"]) % 12
        self.apply_global("root", root)
        # BOTH HALVES GO BACK, and the degree is the one that matters.
        # apply_global re-bases the walker on every hand turn of ROOT and
        # cannot tell a hand from this method, so it has just set base = root
        # and degree = 0. Restoring only the base would leave the walk starting
        # from home at every step - it would oscillate one degree either side
        # of the root forever and never use its span, which looks like a walk
        # and is not one.
        self.walk_base = base
        self.walk_degree = degree
        self._slog("walk", bar=bar, degree=degree, root=root)

    def _drop_fire(self, bar):
        """Everything that is not a survivor falls silent for the drop.

        WITH NOBODY NOMINATED IT REFUSES, and says so on the page indicator.
        Owner decision, 2026-08-21 - see the comment on the guard below.

        The MIXER STRIP is muted, never the zynseq track. zynseq's file format
        has no mute field at all, so a zynseq mute is lost by every snapshot
        save; the mixer's is in the zs3 state and shows on the touchscreen
        mixer. And a sequencer-level stop would be worse than useless here -
        Sequence::setPlayState turns STOPPING into STOPPED immediately under
        LOOP and then resets the position to 0, so the channel would come back
        out of sync with the other seven.

        THE STATE IS CAPTURED HERE AND RESTORED VERBATIM. Restoring "all on"
        would un-mute a channel the player had killed by hand, and they would
        blame the drop for it."""

        if not self._drop_survivors:
            # OWNER DECISION, 2026-08-21: a DROP with nobody nominated does
            # NOT mute all eight. It used to, which is literally what
            # nominating nobody means - and is how the rig went silent on
            # 2026-08-20 while the owner held FREEZE.
            #
            # AND IT SAYS SO. A macro that lands and does nothing in silence
            # is the unexplained-silence law wearing a different hat, so the
            # refusal borrows the note HALF and DOUBLE already use for a
            # partial result: `DROP 0/8` reads as "took none of eight", in a
            # grammar the player has already met on this same indicator.
            #
            # The note is given the window the drop itself would have
            # occupied. A macro that RAN clears its note on its restore leg;
            # a macro that refused has no restore leg to clear it.
            self._timescale_note = ("DROP", 0, len(tlib.CHANNELS))
            self._note_expires = bar + self._arm_bars.get("drop", 4)
            self._slog("drop", bar=bar, survivors=self._drop_survivors,
                       fired=False, why="no survivors nominated")
            logging.info("Maschine: DROP refused - no survivors nominated")
            with self.lock:
                self._render_display()
            return
        self._drop_restore = {}
        mixer = self.state_manager.zynmixer
        muted = []
        nochain = []
        for group in range(8):
            chan = self._mixer_chan(group)
            if chan is None:
                # Every group landing here is a DROP that fires and is
                # inaudible: the macro lands, the log says so, and not one
                # strip moves. That is the shape the log exists to tell apart
                # from "it never fired".
                nochain.append(group)
                continue
            self._drop_restore[group] = bool(mixer.get_mute(chan))
            if group not in self._drop_survivors:
                mixer.set_mute(chan, True, update=True)
                muted.append(group)
        self._slog("drop", bar=bar, survivors=self._drop_survivors,
                   muted=muted, nochain=nochain,
                   captured=sorted(self._drop_restore))
        # Symmetric by design: the ARM length is BOTH when it fires and how
        # long it lasts. A second gesture for the duration was rejected - the
        # queue already carries a per-macro length, so adding one later is
        # additive rather than a rewrite.
        bars = self._arm_bars.get("drop", 4)
        self._pending_macros.arm("drop_end", bars, bar)
        self._arm_bars["drop_end"] = bars
        with self.lock:
            self._render_mutes()
            self._render_groups()

    def _drop_restore_apply(self):
        """Put back exactly what _drop_fire captured, then forget it."""

        self._slog("drop_end", restoring=sorted(self._drop_restore))
        mixer = self.state_manager.zynmixer
        for group, muted in self._drop_restore.items():
            chan = self._mixer_chan(group)
            if chan is None:
                continue
            mixer.set_mute(chan, muted, update=True)
        self._drop_restore = {}
        with self.lock:
            self._render_mutes()
            self._render_groups()

    def _fire_macro(self, macro, bar):
        """Dispatch one landed macro.

        A stub with one arm per payload, extended by the DROP and CHANCE-ramp
        tasks. Unknown macros are logged rather than raised: an unrecognised
        name in a restored snapshot must not kill the poll thread, which is
        the 2026-08-18 failure."""

        logging.debug(f"Maschine: macro {macro} landed on bar {bar}")
        self._slog("fire", macro=macro, bar=bar)
        if macro == "drop":
            self._drop_fire(bar)
        elif macro == "drop_end":
            self._drop_restore_apply()
        elif macro == "ratchet":
            # Capture each channel's OWN ratchet, walk away from it, land back
            # on it. Never assume 1: a channel the player left ratcheting must
            # come back ratcheting.
            # DRUMS ONLY. RATCHET is a drum-page verb: it is written into the
            # notes as zynseq stutter, and a voice's pattern is rewritten by a
            # different generator entirely. Taking the voices too is what
            # overwrote their melodies.
            channels = [ch for ch
                        in tlib.generated_channels(self.owner,
                                                   len(tlib.CHANNELS),
                                                   moves=self._moves(),
                                                   roll=self._move_roll)
                        if self.channel_kind(ch) == "drum"]
            self._ratchet_ramp = {
                "bars": self._arm_bars.get("ratchet", 4),
                "start": bar,
                "base": {ch: int(self.state[ch].get("ratchet", 1))
                         for ch in channels},
            }
            self._timescale_note = ("ROLL", len(channels), len(tlib.CHANNELS))
            self._note_expires = None
        elif macro == "break_end":
            # The same restore DROP uses. BREAK is DROP's second entry point,
            # not a parallel implementation - one capture, one restore, and
            # therefore one place where the "put back what was captured, never
            # all-on" rule lives.
            self._drop_restore_apply()
        elif macro in ("half", "double"):
            self._timescale_fire(macro, bar)
        elif macro == "timescale_end":
            self._timescale_restore_apply()
        elif macro == "gate":
            self._gate_fire(bar)
        elif macro == "chance":
            # Capture every channel's OWN value at fire time. The ramp walks
            # away from it and lands back on it; nothing here assumes 100.
            self._chance_ramp = {
                "bars": self._arm_bars.get("chance", 8),
                "start": bar,
                # Ownership is deliberately NOT asked here - setPlayChance
                # regenerates nothing, so a recorded take is safe, and that
                # exception is in _chance_tick's docstring. MOVE is a
                # different question and IS asked: a channel the player has
                # locked must not have its odds walked out from under it.
                "base": {ch: int(self.state[ch].get("chance", 100))
                         for ch in range(len(tlib.CHANNELS))
                         if tlib.move_allows(self._move_of(ch),
                                             self._move_roll())},
            }

    def _wrap_channel(self, channel):

        """One channel's share of _voice_wraps.

        Split out so the caller can catch per channel. Everything that can
        raise in here is that channel's own: its state dict, its pattern, its
        registers."""

        voice = self.channel_kind(channel) == "voice"
        with self.lock:
            if self._play_state(channel) == zynseq_lib.SEQ_STOPPED:
                self._voice_pos[channel] = None
                # Stopped: a pending structure change has no bar to wait
                # for, so take it now rather than leaving it in brackets.
                if self.state[channel]["pending"]:
                    pending = set(self.state[channel]["pending"])
                    self.state[channel]["pending"].clear()
                    try:
                        if not voice:
                            if "div" in pending:
                                self._write_pattern(channel)
                            else:
                                self._set_length(channel, self.beats[channel])
                    except Exception:
                        # The write did not land, so the change is still
                        # pending. Putting it back keeps the brackets on the
                        # surface, which is the truth, and the next wrap
                        # tries again. Clearing it and failing would drop a
                        # structure change silently - the exact shape of
                        # fault this whole round exists to stop.
                        self.state[channel]["pending"] |= pending
                        raise
                return
            position = self.libseq.getPlayPosition(self.bank, channel)
        previous = self._voice_pos.get(channel)
        self._voice_pos[channel] = position
        wrapped = previous is not None and position < previous

        if wrapped and self.state[channel]["pending"]:
            pending = set(self.state[channel]["pending"])
            self.state[channel]["pending"].clear()
            try:
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
            except Exception:
                self.state[channel]["pending"] |= pending
                raise

        if wrapped and channel in self._mute_pending:
            # A queued mute lands on this channel's own wrap. Popped before it
            # is applied so a raise cannot leave it queued forever, drawing a
            # half-lit pad for a change that will never happen.
            want = self._mute_pending.pop(channel)
            # EXIT, 2026-09-01. THE QUEUED ROW IS THE MUSICAL ONE and the
            # instant row stays hard, so the two halves of the MUTE grid
            # finally mean different things and no new gesture was invented.
            # At 0 bars this is exactly what it always did.
            if not self._exit_start(channel, want):
                self._set_muted(channel, want)
            with self.lock:
                self._render_mutes()
                self._render_groups()
                if self.mute_down:
                    self._paint_mute_grid()

        if wrapped:
            # A reroll lands on the bar - a phrase-level gesture, so it obeys
            # the structure rule rather than the timbre rule, even though HITS
            # and ROTATE land instantly when turned by hand.
            self._reroll_channel(channel)

        if wrapped:
            # Drift, for drums and voices alike - it is the pattern that drifts,
            # not the line. Outside the lock, like _rewrite_voice below: apply()
            # reaches _write_pattern, which takes the lock itself.
            self._drift_channel(channel)
            self._rewrite_drum(channel)

        if not voice:
            return
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

    def _log_poll_error(self, key, exc):
        """Report an exception raised on the poll thread, rate limited.

        Two callers now - the loop itself and each channel of _voice_wraps -
        which is what earns the helper: the throttle's bookkeeping is easy to
        get subtly different in two places, and a limiter that is wrong in one
        of them either floods the journal or hides the fault."""

        message = f"{type(exc).__name__}: {exc}"
        emit, suppressed, fresh = tlib.throttle(
            self._log_seen, key, message, time.monotonic(), POLL_ERROR_S)
        if not emit:
            return
        # The traceback goes out once per distinct message. A repeat carries
        # the count instead - the stack is identical and printing it again
        # buries everything else in the journal.
        logging.error("Maschine %s failed, %d since last report: %s",
                      key, suppressed, message, exc_info=fresh)

    def _device_token(self):
        """Identity of the controller's device node, or None when it is not
        there. udev recreates /dev/maschine on every plug, so the symlink
        target and the inode behind it move exactly when the hardware has
        been through a power cycle and lost every LED."""

        try:
            st = os.stat(DEVICE_NODE)
        except OSError:
            return None
        try:
            target = os.readlink(DEVICE_NODE)
        except OSError:
            # Not a symlink on this install. The stat alone still moves.
            target = None
        return (target, st.st_ino, st.st_rdev)

    def _check_device(self):
        """Repaint the whole surface once, if the controller has been
        replaced since the last look.

        The LED cache suppresses a write whose value has not changed, which
        after a replug is a correct statement about the driver and a false one
        about the hardware: the device came back blank and every write is then
        judged redundant. Only the pads healed on their own, because the pads
        are the one cache site with a ttl - buttons, the static LEDs and both
        screens stayed dark until something happened to change their state,
        and the static LEDs never do. Measured on the rig 2026-08-30, after a
        wedge that needed a physical replug to clear.

        This is the same cure _on_snapshot already applies for the same
        reason, and it costs nothing while the device stays put: one stat a
        second, and no writes at all unless the token moved.

        Called with the lock held - _render_all() reaches the pattern."""

        token = self._device_token()
        reconnected = tlib.device_reconnected(self.device_token, token)
        self.device_token = token
        if not reconnected:
            return
        logging.info("Maschine: device node is new, repainting the surface")
        self.leds.clear()
        self.head_shown = None
        self._render_all()

    WATCHDOG_POLL_S = 1.0

    def _watchdog_loop(self):
        """Notice that the generator has stopped, say so, and keep the pads
        alive while it is stopped.

        WHAT "REDUCED MODE" IS HERE. While the poll thread is stuck, the
        note-base heartbeat it normally sends every second stops with it - and
        the daemon re-bases the pads on every Group press whatever the driver
        thinks, so the base drifts and every pad press decodes out of range,
        silently. So this thread keeps sending it. The generator is stopped
        either way; the difference is whether the instrument can still be
        PLAYED while it is.

        NO LOCK IS TAKEN ANYWHERE IN HERE. The thread this watches may be
        blocked while holding one, and a watchdog that can deadlock on the
        fault it reports is worse than none. One UDP packet a second is the
        whole cost.

        The banner itself is composed on the render path (tlib.stall_label) so
        it appears the moment anything repaints. It is not painted from this
        thread: writing text over a row with no clear primitive would leave
        the old label underneath it, and inventing one from here - untested,
        on the write path that is the prime suspect for every controller wedge
        this project has had - is not a trade worth making for a message the
        journal already carries."""

        while not self.stopping.wait(self.WATCHDOG_POLL_S):
            try:
                now = time.monotonic()
                stalled = tlib.stalled(now, self._beat_at)
                if stalled:
                    # Reduced mode: the pads keep decoding.
                    self._send_osc(lib.note_base_osc(
                        GROUP_NOTE_BASE[self.group]))
                if stalled and not self._stalled:
                    self._stalled = True
                    logging.warning(
                        "Maschine: generation has stopped - no poll tick for "
                        f"{now - (self._beat_at or now):.1f}s. The pads are "
                        "still being re-based; nothing else is running.")
                    self._slog("watchdog", event="stall",
                               since=round(now - (self._beat_at or now), 1))
                elif self._stalled and not stalled:
                    self._stalled = False
                    logging.warning("Maschine: generation resumed.")
                    self._slog("watchdog", event="resumed")
            except Exception as e:
                # A watchdog that can die is not a watchdog.
                logging.error(f"Maschine watchdog: {e}")

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
                # THE HEARTBEAT, stamped before the two calls that can block.
                # Anything below this line failing to return is exactly what
                # the watchdog exists to notice.
                self._beat_at = time.monotonic()
                # Outside the lock on purpose: loading a kit talks to
                # LinuxSampler over a socket and can block.
                self._commit_kit()
                self._commit_preset()
                if self._record_due:
                    self._record_due = False
                    self._toggle_capture()
                if self.arm_down or self.erase_down:
                    # Held: the daemon may re-base under us at any moment, so
                    # keep asserting. The LED-style cache does not apply here -
                    # it is one small OSC message on a tick that already sends
                    # several.
                    self._send_osc(lib.note_base_osc(
                        GROUP_NOTE_BASE[self.group]))
                    self._note_base_due = True
                elif self._note_base_due:
                    # One more after the modifier is released, to land after
                    # the daemon's own release-edge write.
                    self._note_base_due = False
                    self._send_osc(lib.note_base_osc(
                        GROUP_NOTE_BASE[self.group]))
                elif tick % NOTE_BASE_HEARTBEAT_TICKS == 0:
                    # Once a second, unconditionally. The driver decides what
                    # a pad MEANS, so it is the authority on the base, and the
                    # failure it prevents is the worst one this surface has:
                    # every press dropped, no sound, no log. One small UDP
                    # packet a second is nothing next to the LED traffic on
                    # the same tick - and unlike the pad grid, it is not a
                    # rate that can starve the daemon's reader.
                    self._send_osc(lib.note_base_osc(
                        GROUP_NOTE_BASE[self.group]))
                if self._repeat_due is not None:
                    want, self._repeat_due = self._repeat_due, None
                    self._repeat_apply(want)
                if self._break_due is not None:
                    bars, self._break_due = self._break_due, None
                    self._break_fire(bars)
                # Drain queued note-map rebuilds here, never on the MIDI
                # thread: the scan takes the lock for a whole pattern.
                while self._rebuild_due:
                    self._rebuild_notes(self._rebuild_due.pop())
                if tick % NOTE_BASE_HEARTBEAT_TICKS == 0:
                    # Once a second: has the bank moved under us? Cheap - an
                    # attribute compare - and it does real work only on a
                    # drift, which nothing in this instrument produces today.
                    self._check_bank()
                self._voice_wraps()
                self._phrase_tick()
                if tick % VOLUME_POLL_TICKS == 0:
                    # Tempo can move from the touchscreen or from a snapshot,
                    # and the delay's musical division has to follow it.
                    self._push_delay_time()
                if tick % VOLUME_POLL_TICKS == 0:
                    # ~200ms. Deliberately the existing sub-rate: an unthrottled
                    # 30 Hz modulator is 30 writes/s per moving target, each
                    # reaching engine.send_controller_value(). Raise this only
                    # for a target that proves it needs more.
                    self._mod_write()
                    # After _mod_write, so a channel whose verb a modulator
                    # owns has already had this tick's swept value folded in.
                    self._pressure_write()
                    # And after both: a channel on its way out overrides
                    # whatever a modulator was doing to its level, because it
                    # is leaving.
                    self._exit_write()
                with self.lock:
                    # Before anything else this tick: if the controller has
                    # been replugged, everything below would be written into
                    # a cache that describes a surface which no longer exists.
                    if tick % DEVICE_POLL_TICKS == 0:
                        self._check_device()
                    owner = self._pad_owner()
                    # THE MOD LEGEND IS NO LONGER ANIMATED FROM HERE, and
                    # it is not a throttling question any more. Repainting
                    # sixteen pads on a timer - at 30 Hz, and then at 10 Hz -
                    # starved the daemon's reader and wedged the controller
                    # three times in one session, each within seconds of a
                    # modulator being bound. It does not recover from a daemon
                    # restart or from USB re-enumeration; only a physical
                    # replug brings it back.
                    #
                    # The legend is now painted from _render_pads on the
                    # EVENTS that change it - MOD pressed, a rate or shape
                    # picked, the selection moved - so a still grid costs
                    # nothing at all. What is lost is the fade that showed
                    # what a rate FEELS like. That was a genuine nicety and it
                    # is written up in new_features.md; a controller that dies
                    # when you bind a modulator is not a trade worth making.
                    if tlib.overlay_is_stepwise(owner):
                        head = self._playhead()
                        if head != self.head_shown:
                            self._move_playhead(head)
                    # A non-stepwise overlay that is NOT animated - ARM - is
                    # left alone. Asked by the predicate rather than by name so
                    # the next such overlay inherits it: moving a playhead
                    # across pads that no longer stand for steps would paint
                    # white over whatever they DO stand for, once per tick.
                    if tick % PAD_RESYNC_TICKS == 0:
                        # The pads are the one surface with no periodic
                        # writer - deliberately, because a full repaint at the
                        # poll rate is what wedged the controller. This is the
                        # same repaint at 1/90th of that rate, and it exists
                        # so PAD_LED_REFRESH_S has something to ride on: a
                        # single lost write heals within three seconds instead
                        # of never. It goes through _render_pads rather than a
                        # pad loop of its own so that whatever owns the pads -
                        # the step grid, MUTE, MOD, ARM, NAVIGATE - is redrawn
                        # as itself and not painted over.
                        self._render_pads()
                    if tick % VOLUME_POLL_TICKS == 0:
                        self._render_groups()
                        # GRID blinks while the selected channel is on an
                        # overridden kind, so it needs a periodic writer
                        # rather than an event-driven one. Same sub-rate as
                        # everything else here; the LED cache still swallows
                        # every repeat, so a steady GRID costs nothing.
                        self._render_grid()
                        # SCENE / PATTERN follow the selected channel's kind.
                        self._render_reroll()
                        # SWING blinks while MOD is LATCHED, so it needs the
                        # same periodic writer GRID does. The LED cache
                        # swallows every unchanged repeat, so a steady or dark
                        # SWING still puts nothing on the wire.
                        self._render_mod()
                        # The modifier lights BLINK while latched, so they
                        # need a periodic writer for the same reason GRID
                        # does. The LED cache swallows every unchanged
                        # repeat, so a panel with nothing latched puts
                        # nothing on the wire.
                        self._render_overlay_leds()
                        self._render_freeze()
                        # The display arrows go dark on a one-page ring, and
                        # the ring changes with the selected channel's kind
                        # and with the lens.
                        self._render_page_arrows()
                        # The F row follows the page in CONTROL, and a switch
                        # can also move from the touchscreen - so it needs a
                        # periodic writer for the same reason GRID does. Eight
                        # dict lookups against the LED cache when nothing has
                        # changed.
                        self._render_mutes()
                        # Volume, pan and the mutes can all move on the
                        # touchscreen with nothing signalling it, so the
                        # screens are polled on the same tick.
                        self._render_display()
            except Exception as e:
                # NEVER return. Everything that makes the instrument evolve
                # lives in this loop - the Turing rewrite at every wrap, the
                # modulators, the pending structure changes, the kit and
                # preset commits - so ending it stops the generator dead while
                # the pads, the encoders and the display all keep working off
                # the MIDI and zynsigman threads. Nothing on the surface says
                # the instrument has stopped generating. On 2026-08-18 one
                # KeyError out of a stale snapshot dict did exactly that, and
                # it went unexplained for three hours of playing.
                #
                # Rate limited because this is a 30 Hz loop: an unguarded
                # logging.error on a persistent fault writes 30 lines a second
                # for as long as the fault lasts. The traceback goes out once
                # per distinct message, the repeat carries the count instead.
                self._log_poll_error("playhead poll", e)

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
        if self.leds.changed(f"pad{pad}", state, ttl=PAD_LED_REFRESH_S):
            self._send_osc(lib.pad_osc(pad, state[0], state[1]))

    # --- LEDs ----------------------------------------------------------

    def _step_lit(self, step, gen_note):
        """Does this step sound - by EITHER route?

        `gen_note` is the pitch the generator put on this step. Asking zynseq
        for only that pitch is what hid every played-in note on a voice: a
        voice pad plays a KEYBOARD pitch chosen by which pad was hit
        (_pad_note -> tlib.pad_note), not the pitch the Turing register wrote
        there, so the query missed the note, the step read as empty, and
        _step_state returned dim one line ABOVE the amber test it never
        reached. The note was in the pattern and sounding the whole time.

        Drums never showed it because a drum channel's played and generated
        notes are the same pitch - the same identity that costs drums their
        amber across a reload. One cause, two opposite symptoms.

        The played pitch is read back from zynseq rather than trusted from
        self.notes, which is a cache: any mirrored state is verified against
        the pattern, the CHANCE/SWING law. The extra query only happens on a
        step that actually has a player entry."""

        if self.libseq.getNoteVelocity(step, gen_note):
            return True
        entry = self.notes[self.group].get(step)
        return bool(entry and self.libseq.getNoteVelocity(step, entry[0]))

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
            self._step_lit(step, notes[step]) if step < steps else None
            for step in range(16)]
        head = self._playhead()
        self.head_shown = head
        # While a modifier owns the pads they stop being the step picture. The
        # playhead is still drawn over the top, in white, unchanged - the
        # overlay does not have to suppress or special-case it, which is the
        # whole reason white is reserved for it.
        owner = self._pad_owner()
        if owner == "bank":
            self._paint_bank_grid()
            return
        if owner == "mute":
            self._paint_mute_grid()
            return
        if owner == "navigate":
            self._paint_phrase_pads()
            return
        if owner == "arm":
            # Ahead of MOD only because the priority table says so; neither
            # can be true at once here.
            self._paint_arm_legend()
            return
        if owner == "mod":
            # The pads stop standing for steps entirely, so there is no step
            # loop and no playhead - see tlib.overlay_is_stepwise().
            self._paint_mod_legend()
            return
        stepwise = tlib.overlay_is_stepwise(owner)
        for step in range(16):
            if step == head and stepwise:
                state = (COLOR_PLAYHEAD, BRIGHT_PLAYHEAD)
            elif owner == "shift":
                state = tlib.probability_pad(
                    bool(self.step_on[step]),
                    self._step_chance(step, notes[step]) or 100)
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
            # THE HUE ANSWERS THE SAME QUESTION THE BRIGHTNESS DOES. While
            # ERASE is held the row is about what would be lost, so a channel
            # holding a take wears the colour a played step already wears
            # everywhere on this surface - amber - rather than its own
            # identity. Hue is identity every other moment; here it would be
            # the one fact nobody needs.
            colour = GROUP_COLORS[group]
            if (self.erase_down
                    and self.owner.get(group) == tlib.OWNER_PLAYER):
                colour = COLOR_PLAYER
            state = (colour, bright)
            key = f"group{group}"
            if self.leds.changed(key, state):
                self._send_osc(lib.button_osc(
                    f"group_{chr(ord('a') + group)}", state[0], state[1]))

    def _render_transport(self):
        # Bright while anything runs, DIM while stopped. Dark would say the
        # button does nothing, and a stopped instrument is exactly when PLAY
        # matters most - in a dark room it is the button you are looking for.
        state = (COLOR_PLAY, tlib.toggle_light(self._any_playing()))
        if self.leds.changed("play", state):
            self._send_osc(lib.button_osc("play", state[0], state[1]))
        self._render_arm()
        self._render_modes()

    def _render_arm(self):
        """SELECT flashes once per bar while something is pending, and goes
        STEADY through the landing bar.

        Once ARM is released this LED is the only thing on the panel that says
        a macro is coming, so it is not decoration. The BAR NUMBER drives the
        flash rather than a timer - the flash IS the countdown, not an
        animation running alongside one, and a timer would drift away from the
        bars it claims to be counting.

        Steady rather than flashing when the transport is stopped: nothing is
        counting down yet, and a flash would say it was.

        LED index 22, MEASURED. Lit by the daemon's own name for that index,
        which has been correct since c141d70 - before that the names were
        attached to the wrong buttons and two shipped features lit the wrong
        LED for months."""

        pending = bool(self._pending_macros.pending()
                       or self._armed_while_stopped)
        if not pending:
            bright = BRIGHT_PAGE_OFF
        elif self._phrase_bar is None or self._armed_while_stopped:
            bright = BRIGHT_PAGE_ON
        else:
            _picked, _bars, left = self._arm_state()
            bright = (BRIGHT_PAGE_ON if left == 0
                      else (BRIGHT_PAGE_ON if self._phrase_bar % 2
                            else BRIGHT_PAGE_OFF))
        state = (tlib.COLOR_ARM_COUNT, bright)
        if self.leds.changed("arm", state):
            self._send_osc(lib.button_osc(LED_ARM, state[0], state[1]))

    def _render_reroll(self):
        """SCENE and PATTERN light when the SELECTED group is theirs to reroll.

        Owner, 2026-08-19. The two buttons act on different halves of the
        instrument, and nothing on the panel said which half you were in - so
        the answer was "hold one and watch the tabs", which is a disclosure
        that arrives after the gesture rather than before it.

        Driven from the render tick like every other LED here, never at the
        point of a press, so the light and the behaviour cannot disagree. The
        LED cache swallows every unchanged repeat, so a steady button costs
        nothing on the wire.

        The button LED NAMES go to the daemon, which owns the measured index
        table - SCENE is index 17 and PATTERN 18, both measured 2026-08-15
        after nine of thirteen guessed indices turned out wrong."""

        # ENGINE, not kind - the same rule the reroll itself follows. A drum
        # sampler in Turing mode is still a sampler, so PATTERN stays lit on it.
        # ONE BUTTON since 2026-09-01, and its light answers the only question
        # left: WOULD A PRESS DO ANYTHING RIGHT NOW.
        #
        # That is not decoration. A reroll refuses on a channel you have
        # played - it would throw your take away - and the refusal was
        # SILENT. The owner hit it at the rig, pressed PATTERN, watched
        # nothing happen and had to be told why. This surface's one law is
        # that a silent channel says why; a refused gesture that says nothing
        # is the same failure wearing different clothes.
        #
        # Asked through the same predicate the handler uses, so the light and
        # the button cannot disagree - and it follows SHIFT live, because
        # SHIFT widens the scope and can make a dark button lit.
        #
        # SCENE is dark: free surface, bound to nothing, and a lit button that
        # does nothing is the object law G5 forbids.
        acts = bool(self._reroll_targets())
        for led, lit in (("pattern", acts), ("scene", False)):
            state = (COLOR_PAGE, tlib.action_light(lit))
            if self.leds.changed(f"reroll_{led}", state):
                self._send_osc(lib.button_osc(led, state[0], state[1]))

    def _render_modes(self):
        """Exactly one mode LED lit, always. Derived from self.mode on the
        render tick and never written at the point of the press, so the LED and
        the screens cannot disagree about which mode is showing.

        The daemon accepts a button LED name over OSC whether or not it emits
        that button's CC, so volume and auto light without the daemon patch."""

        for mode, led in MODE_LED_NAMES.items():
            # Bright for the one you are in, DIM for the other three. Dark
            # would say the button does nothing, and every one of them does
            # the same thing from anywhere: take you to page 1 of itself.
            state = (COLOR_PAGE, tlib.toggle_light(mode == self.mode))
            # The cache key changed from page_ to mode_ deliberately: a stale
            # page_control entry would suppress the first repaint.
            if self.leds.changed(f"mode_{led}", state):
                self._send_osc(lib.button_osc(led, state[0], state[1]))

    def _render_mutes(self):
        """F1-F8 light what they do: bright = muted, or bright = soloed while
        the row means solo. Dim = audible and reachable. Dark = there is no
        channel behind that button at all.

        ONE MEANING IN EVERY MODE since 2026-09-01. CONTROL used to take the
        row for the page's switches and this method had a second reading for
        that; the row never leaves now, so both the branch and the predicate
        behind it went with it. SOLO blinks while its mode is latched, which is the panel's
        word for latched and the one thing telling you what these eight
        buttons currently mean."""

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
            # A TOGGLE: bright when true, DIM when reachable, dark when there
            # is nothing behind it. The dark used to cover both "audible" and
            # "no chain", so a channel that was not there looked exactly like
            # one that was playing.
            state = (COLOR_PAGE, tlib.toggle_light(on, chan is not None))
            if self.leds.changed(f"mute{group}", state):
                self._send_osc(lib.button_osc(F_BUTTON_NAMES[group], state[0], state[1]))
        # SOLO latches, so it wears the latch blink like every other latch on
        # this panel - and it is the one light that says what the eight
        # buttons under your hand currently mean.
        solo_state = (COLOR_PAGE, tlib.state_light(
            self.solo_down, self.solo_mode, time.monotonic()))
        if self.leds.changed("solo", solo_state):
            self._send_osc(lib.button_osc("solo", solo_state[0], solo_state[1]))

    # Buttons that are lit whenever the instrument is running, because they
    # always do the same thing and a dark button reads as a dead one. The
    # daemon token names are on the LEFT; the physical button each one lights
    # was MEASURED 2026-08-15, one index at a time, because this project has
    # twice shipped an LED table that was inferred and wrong.
    #
    #   page_left / page_right  -> the two arrows beside the display
    #   nav_left  / nav_right   -> the two below the big encoder (preset step)
    #   step_left / step_right  -> the two transport STEP arrows
    #   stop                    -> ERASE   (the daemon calls Erase "stop")
    #   shift                   -> SHIFT
    # ACTION buttons: dim while they would do something, dark while they
    # would not. There is no third level - bright means "acting now" on this
    # panel and an action is never acting; it happened and it is over.
    #
    # This tuple used to be called STATIC_LEDS and every one of them was lit
    # at full brightness whenever the instrument was running. Four buttons
    # saying yes forever, which is a light that means nothing - and, worse,
    # the same brightness a HELD modifier now uses. `shift` and `stop`
    # (the daemon's measured name for ERASE) left for the modifier alphabet,
    # and the display arrows learned to go dark on a ring with one page.
    ACTION_LEDS = ("nav_left", "nav_right")
    BRIGHT_STATIC = 1.0

    # Which LED each modifier lights. NAVIGATE, DUPLICATE and MUTE had no
    # writer at all before 2026-09-01 - three buttons that took the sixteen
    # pads and said nothing while they did it, which is the largest single
    # inconsistency this panel had.
    #
    # SHIFT is here rather than in STATIC_LEDS for the same reason: it was lit
    # permanently, so its light carried no information about the one thing it
    # does.
    OVERLAY_LEDS = {
        "shift": "shift",
        "arm": LED_ARM,
        "bank": "duplicate",
        "mute": "mute",
        "navigate": "navigate",
        "lens": LED_LENS,
        # `mod` is DELIBERATELY ABSENT and so is `freeze`. Both wear the same
        # alphabet through tlib.state_light, but each has a renderer of its
        # own that is called from edges this one is not - _act_mod repaints on
        # both halves of its press so the legend takes the pads without a
        # tick's delay, and _render_freeze is reached from the freeze handler.
        # Two writers on one LED is a light that flickers between two
        # opinions, so they own theirs and this owns the rest.
    }

    def _render_overlay_leds(self):
        """Every modifier, one alphabet: dim available, bright held, blink
        latched.

        ARM is the exception and it is a documented one: while something is
        armed its light is the COUNTDOWN, driven by the bar rather than by a
        timer, and _render_arm owns it. A modifier light and a countdown on
        one LED cannot both be right, and the countdown is the one a player
        needs from across a room."""

        now = time.monotonic()
        for name, led in self.OVERLAY_LEDS.items():
            if name == "arm" and (self._pending_macros.pending()
                                  or self._armed_while_stopped):
                # _render_arm owns the LED while a macro counts down. ITS
                # CACHE KEY IS DROPPED ON THE WAY PAST, and that is the whole
                # point of this line: two writers on one LED with two keys
                # meant the handover only worked in one direction. While
                # pending, this writer's key froze at whatever it last wrote;
                # when pending cleared, _render_arm wrote DARK and then this
                # one recomputed the identical value it had cached, found no
                # change, and sent nothing. SELECT stayed dark - reading, on a
                # panel where dark now means "does nothing", as a dead button
                # - until the next press of it.
                self.leds.forget(f"overlay_{name}")
                continue
            latch = self.latches[name]
            bright = tlib.state_light(latch.held, latch.latched, now)
            state = (COLOR_PAGE, bright)
            if self.leds.changed(f"overlay_{name}", state):
                self._send_osc(lib.button_osc(led, state[0], state[1]))

    def _render_shift(self):
        """SHIFT alone, for the handler that has to repaint on its own edge."""
        self._render_overlay_leds()

    def _render_static_leds(self):
        """The action buttons, plus the ones that answer to their own state.

        Diffed through self.leds like every other LED write, so a steady panel
        puts nothing on the wire. The device has been flooded off the USB bus
        once by unthrottled writes, and it is the DISPLAY path that does it -
        LED writes are three reports on a 16 ms timer however many change.

        ERASE is a modifier and lights like one; the display arrows go dark
        when the ring they walk has a single page, which is law G5 wearing a
        button - a lit control that cannot do anything is the lie this surface
        exists not to tell."""

        state = (COLOR_PAGE, tlib.action_light(True))
        for name in self.ACTION_LEDS:
            if self.leds.changed(f"action_{name}", state):
                self._send_osc(lib.button_osc(name, state[0], state[1]))
        # STEP-left is measured, unbound and therefore dark. It is the last
        # free control on the panel and the light says so honestly.
        dark = (COLOR_PAGE, tlib.action_light(False))
        if self.leds.changed("action_step_left", dark):
            self._send_osc(lib.button_osc("step_left", dark[0], dark[1]))
        self._render_page_arrows()
        self._render_erase()
        self._render_repeat()
        self._render_restart()
        self._render_overlay_leds()
        self._render_register_undo()
        self._render_rec()
        self._render_grid()

    def _render_page_arrows(self):
        """The two arrows beside the display, dark on a one-page ring.

        The lens has no ring of its own - it is one page by construction - so
        the arrows go dark while it is open too. That is not a special case:
        it is the same question, asked of whatever _page() is showing."""

        # In the lens they step the VERB rather than a page, so they are lit -
        # they were dark here while they did nothing, which was correct then
        # and would be a lie now.
        pages = len(self._lens_ring()) if self.lens_down else len(self._ring())
        state = (COLOR_PAGE, tlib.action_light(pages > 1))
        for name in ("page_left", "page_right"):
            if self.leds.changed(f"arrow_{name}", state):
                self._send_osc(lib.button_osc(name, state[0], state[1]))

    def _render_repeat(self):
        """STEP-right, the beat repeat. A modifier that cannot latch: bright
        while held, dim while it waits.

        It had no light at all. A gesture that collapses the whole machine to
        one beat and comes back on release is the last one that should be
        invisible while it is happening - and this is the button a player
        holds while looking somewhere else entirely."""

        state = (COLOR_PAGE, tlib.state_light(bool(self._repeat_due), False))
        if self.leds.changed("repeat", state):
            self._send_osc(lib.button_osc("step_right", state[0], state[1]))

    def _render_restart(self):
        """RESTART. Dim, and BRIGHT while MOD is on, because there it is the
        pump - MOD + RESTART snaps every modulator into phase together.

        It had no light either, and it is the one button whose meaning changes
        under a modifier without the modifier being visible on it."""

        state = (COLOR_PAGE,
                 tlib.state_light(self.mod_down, False))
        if self.leds.changed("restart", state):
            self._send_osc(lib.button_osc("restart", state[0], state[1]))

    def _render_erase(self):
        """ERASE, on the LED the daemon measured as `stop`.

        A modifier, so it follows the modifier alphabet - dim available,
        bright held. It cannot latch: a bare press does nothing at all (law
        L3), which means a tap has no state to flip, and a latched ERASE would
        be a surface where the next thing you touch disappears."""

        state = (COLOR_PAGE,
                 tlib.state_light(self.erase_down, False))
        if self.leds.changed("erase", state):
            self._send_osc(lib.button_osc("stop", state[0], state[1]))

    def _render_register_undo(self):
        """NOTE REPEAT lights only while the selected channel behaves as a
        voice, because that is the only kind the register undo can act on.

        _duplicate returns immediately on a drum channel - it restores a Turing
        shift register, and a euclidean channel has none. An always-lit button
        that silently does nothing on five of the eight channels is the same
        lie as a knob showing a number it cannot move, which law L4 already
        forbids elsewhere on this surface.

        NOTE REPEAT is index 31, MEASURED 2026-08-15. It had no working LED at
        all before: the daemon had it at 17, which belongs to SCENE.

        Repainted from _render_all, which both _select_group and _toggle_kind
        end with - so it follows a change of channel and a change of kind
        without either of them knowing about this button."""

        lit = self.channel_kind(self.group) == "voice"
        # An ACTION: dim where it would act, dark where it would not. On a
        # euclidean channel there is no shift register to give back.
        state = (COLOR_PAGE, tlib.action_light(lit))
        if self.leds.changed("register_undo", state):
            self._send_osc(lib.button_osc("note_repeat", state[0], state[1]))

    def _render_grid(self):
        """GRID is lit whenever it does something - which is always, since
        SHIFT + GRID switches the selected channel's kind on any channel.

        It BLINKS while that channel is on an overridden kind, because a
        channel behaving as something its engine is not is the surface's most
        surprising state, and the page indicator's DRM/VOX marker is easy to
        miss mid-jam. The blink stops the moment the override clears - which
        switching back does by itself, since _toggle_kind sets the override to
        None rather than pinning it.

        The phase comes from the clock, not from a counter, so any caller
        computes the same state and no phase has to be carried around. Driven
        from the poll thread's sub-rate tick; the LED cache swallows every
        unchanged repeat, so a steady GRID puts nothing on the wire.

        GRID is index 52, measured 2026-08-15."""

        # An overridden kind IS a latched state - the player put this channel
        # somewhere its engine is not - so it wears the panel's word for
        # latched: a 1 Hz blink. Otherwise DIM: GRID does nothing on its own
        # and only acts under SHIFT, so full brightness was the level a held
        # modifier now uses, promising more than the button does.
        overridden = self.kind_override[self.group] is not None
        state = (COLOR_PAGE,
                 tlib.state_light(False, overridden, time.monotonic()))
        if self.leds.changed("grid", state):
            self._send_osc(lib.button_osc("grid", state[0], state[1]))

    def _render_rec(self):
        """REC lights while holding it would actually capture something.

        Recording hangs off _pad_down, and a pad reaches it only when the mode
        is not STEP - where the pads are the step editor - and MOD is not
        active, where they pick a modulator's rate and shape. In either case
        holding REC does nothing at all, and a lit REC would be promising a
        take it cannot make.

        REC is index 54, measured 2026-08-15. Repainted from _render_all, so
        it follows a mode change, and from both edges of _act_mod, so it
        follows MOD being held or latched."""

        possible = self.mode != "STEP" and not self.mod_down
        # ONE predicate, every fact. Capture is a second meaning on this LED
        # and a second writer would fight the first, so there is no second
        # writer - this is the only place REC's LED is written.
        meaning = tlib.rec_led_state(possible, self.rec_down, self._recording)
        state = (REC_LED_COLOURS[meaning], REC_LED_BRIGHT[meaning])
        if self.leds.changed("rec_possible", state):
            self._send_osc(lib.button_osc("rec", state[0], state[1]))

    def _render_mod(self):
        """SWING lights while MOD is active: STEADY while held, BLINKING while
        latched.

        Same precedent as SOLO above: a latched modifier that is not lit is a
        modifier nobody can find. MOD makes every pad inert and turns all
        eight encoders into depth controls, and mod_latched survives the
        finger leaving the button - so unlit it is an invisible mode that
        looks exactly like a broken surface.

        Diffed through self.leds like every other LED write: the device has
        been flooded off the USB bus once."""

        # THE ALPHABET, and MOD was the button it was derived from: steady
        # while held, blinking while latched, dim while it waits. Only the
        # third is new - an unlit MOD looked exactly like an unlit anything.
        state = (COLOR_PAGE, tlib.state_light(
            self.mod_held, self.mod_latched, time.monotonic()))
        if self.leds.changed("mod", state):
            self._send_osc(lib.button_osc("swing", state[0], state[1]))

    def _render_coarse(self):
        """TEMPO lights while COARSE is held.

        Steady only, never blinking: COARSE does not latch, so there is no
        second state to tell apart. Blinking is the panel's word for LATCHED
        (GRID on an overridden kind, SWING on a latched MOD) and using it
        here would invent a meaning that cannot occur.

        LED index 27, measured 2026-08-16 alongside 17-20. Called from both
        edges of _act_coarse and from nowhere else - there is no periodic
        writer because there is nothing to animate. Diffed through self.leds
        like every other LED write."""

        # A modifier that cannot latch, exactly like ERASE: bright while held,
        # dim while it waits. It does not latch on purpose - a latched
        # sensitivity change is a surface that lies about its own feel.
        state = (COLOR_PAGE, tlib.state_light(self.coarse_down, False))
        if self.leds.changed("coarse", state):
            self._send_osc(lib.button_osc("tempo", state[0], state[1]))

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

        # A GENERATED page is the exception, owner 2026-08-19 at the rig: it
        # is one channel's own plugin, the parameter names do not fit one row
        # (PITCH_BEND_RANGE and PITCH_BEND_STEP both truncate to "PITCH_BE"),
        # and the channel names are not what a player is reading there. So the
        # tab row carries the FIRST line of each column's name and the name
        # row carries the second. The channel tabs are still on every other
        # page, which is where the silence signal is read.
        desc = self._page()
        if desc.get("generated"):
            labels = []
            for verb in desc["verbs"][screen * 4:screen * 4 + 4]:
                labels.append(tlib.wrap_label(self._port_name(verb))[0])
            return tlib.generated_tabs(labels)

        out = []
        for group in range(screen * 4, screen * 4 + 4):
            chan = self._mixer_chan(group)
            silent = chan is not None and bool(self.state_manager.zynmixer.get_mute(chan))
            if not silent:
                st = self.state[group]
                if self.channel_kind(group) == "voice":
                    # Density 0 writes no notes at all, which is the same
                    # unexplained silence chance 0 produced by another route.
                    # No bits set in the rhythm register is the new "no
                    # steps at all" - the same unexplained silence density 0
                    # produced by another route. A silent channel must say why.
                    silent = (st.get("chance", 100) == 0
                              or st.get("rhythm_reg", 0xFFFF) == 0)
                else:
                    silent = self.hits[group] == 0
            out.append((chr(ord("A") + group), tlib.CHANNELS[group][1],
                        group == self.group, silent,
                        group in self._reroll_pending))
        return tuple(out)

    def _page_columns(self, desc):
        """The eight column dicts techno_lib.columns() builds for a page.

        Split out of _columns() so _encoder_column can ask the RENDERER's own
        question - is this column drawn dead? - instead of a second
        approximation of it that would drift from what is on the glass."""

        # MOD strips the bar off every column it would refuse, and the same
        # flag reaches _column_dead through this one method - so the painter
        # and the bind's refusal cannot disagree about which columns are live.
        mod = self.mod_down
        # FREEZE strips the bar off the generative columns through the SAME
        # method, for the same reason MOD does: the painter and the encoder's
        # refusal must not hold two opinions about which columns are live.
        frozen = self.frozen or self.freeze_deep
        shape = desc["shape"]
        if shape == tlib.SHAPE_PENDING:
            return tlib.columns(desc, None, self._pending_view(), mod,
                                frozen=frozen)
        if desc.get("generated"):
            return tlib.columns(desc, None, self._generated_view(desc), mod,
                                frozen=frozen)
        if shape == tlib.SHAPE_SPREAD:
            views = [(chr(ord("A") + i), tlib.CHANNELS[i][1], self.state_view(i))
                     for i in range(len(tlib.CHANNELS))]
            return tlib.columns(desc, None, views, mod, frozen=frozen)
        if shape == tlib.SHAPE_GLOBAL:
            return tlib.columns(desc, None, self.globals_view(), mod,
                                frozen=frozen)
        channel = self.group
        owned = self.owner.get(channel) == "player"
        return tlib.columns(desc, self._page_kind(channel),
                            self.state_view(channel), mod, owned,
                            frozen=frozen)

    def _column_dead(self, column):
        """True when this column is drawn dead (law L4): greyed, showing ----,
        with an encoder that does nothing.

        A verb name is not enough to tell. A voice CONTROL column whose synth
        publishes no such port carries a perfectly good verb and only
        synth_ctrl says it is dead - so MOD bound a modulator there happily,
        mark_modulated() then correctly refused to mark a grey column, and the
        result was a modulator that swept an absent port, drew no tilde and no
        span, was persisted into the snapshot and had mod_last pointing at it.

        A SPREAD ASKS ABOUT ONE CHANNEL, not eight. This runs on the MIDI
        thread for every encoder report, and it used to run only under MOD;
        since 2026-09-01 it gates EVERY turn, because the lens puts live and
        dead columns side by side as an ordinary picture. Building all eight
        columns to read one of them would mean eight state_view() copies -
        each a dict copy plus four param_get calls - per encoder report, under
        the lock. The single-column path asks techno_lib the same question
        through the same two predicates, so the painter and this cannot
        disagree; it is the same answer arrived at without the other seven."""

        desc = self._page()
        if desc["shape"] == tlib.SHAPE_SPREAD:
            if not 0 <= column < len(tlib.CHANNELS):
                return False
            verb = desc["verb"]
            view = self.state_view(column)
            col = tlib.verb_col(verb, view, view.get("kind"))
            return (col is None or bool(col.get("grey"))
                    or tlib.verb_is_dead(verb, view.get("kind"), view))
        cols = self._page_columns(desc)
        if not 0 <= column < len(cols):
            return False
        return bool(cols[column].get("grey"))

    def _columns(self, screen):
        """Four columns for one screen, taken from the page model.

        techno_lib.columns() decides names, values, greyed columns and the
        pending brackets in one tested place; this only translates its dicts
        into the (name, value, bar kind, fraction, mod span, tick) tuples
        screen_packets() draws, converts a segmented bar's (index, count)
        into a fraction, and stamps a modulated column via mark_modulated()
        after the fact - columns() itself never learns what a modulator is.
        `tick` is None on an unmodulated column and the live wave position
        (distinct from `frac`, which stays the base) on a modulated one."""

        desc = self._page()
        shape = desc["shape"]
        cols = self._page_columns(desc)

        meter_page = shape == tlib.SHAPE_SPREAD and desc["verb"] == "level"
        out = []
        for offset, col in enumerate(cols[screen * 4:screen * 4 + 4]):
            col_idx = screen * 4 + offset
            # Same verb/channel resolution as _encoder_column, so MOD marks
            # exactly the column the encoder would have bound.
            if shape == tlib.SHAPE_SPREAD:
                verb, channel = desc["verb"], col_idx
            else:
                # `verbs` is None on a page whose columns are not verbs at all
                # - PENDING is the first. Subscripting it raised on EVERY
                # render tick, which took the whole UI down the moment the
                # page was reached. Asked with .get so the next such page
                # inherits the guard rather than repeating the crash.
                verbs = desc.get("verbs")
                verb = verbs[col_idx] if verbs else None
                channel = self.group
            col = tlib.mark_modulated(col, self._mod_column_span(channel, verb))
            bar = BAR_KINDS[col["bar"]]
            frac = col["frac"]
            if bar == "s":
                index, count = frac
                frac = (index / (count - 1)) if count > 1 else 0.0
            if meter_page:
                level = self._meter_frac(col_idx)
                if level is not None:
                    frac = level
            mod = col["mod"]
            tick = None
            if mod is not None:
                # Quantised against the bar's own pixel width BEFORE the
                # change comparison below (self.leds.changed in
                # _render_display) - see quantise_frac's docstring. Without
                # this a steady modulator's span reports a new value every
                # frame and floods the device at 5 Hz.
                frac = tlib.quantise_frac(frac, self.METER_PIXELS)
                mod = (tlib.quantise_frac(mod[0], self.METER_PIXELS),
                       tlib.quantise_frac(mod[1], self.METER_PIXELS))
                # The tick is a DIFFERENT quantity from frac (frac is the
                # base; mod_span's midpoint never moves) - it is where
                # _mod_write() last sampled the wave, sourced separately and
                # quantised the same way so it repaints only on a real pixel
                # move. Nothing sampled yet (just bound) falls back to the
                # base's own position rather than drawing at 0.
                # NO LIVE TICK. It used to be sampled here and drawn inside
                # the span, and redrawing it in real time is what rebuilt both
                # screens six times a second and wedged the controller.
                #
                # It is not merely un-triggered now, it is GONE - because a
                # marker that is drawn from a live quantity but only refreshed
                # when something else happens to repaint is a marker that
                # LIES. It would sit still while the wave moved and jump when
                # you pressed an unrelated button. This surface does not ship
                # indicators that mean nothing.
                #
                # What it said - how fast is this moving - is now a word on
                # MOD's own label: MOD 8B, MOD 1/4. Owner's suggestion,
                # 2026-08-20. The dashed span stays: it is static, and it says
                # the thing the tick never did, which is HOW FAR the value
                # will travel.
                tick = None
            # THE SHAPE, 2026-09-01. The pads say how FAST a modulator moves;
            # this says what shape it is, as a small static picture in the name
            # row. Read from the modulator itself rather than from the column,
            # because the column has never needed to know what a modulator is -
            # mark_modulated stamps it from outside for the same reason.
            #
            # STATIC. It changes when the shape changes and at no other time:
            # the law out of two accidental experiments in one evening is never
            # animate a value on the screens.
            # NOT `shape` - that name is the PAGE's shape a few lines above,
            # and shadowing it here would make every column after the first
            # resolve its verb as though the page were not a spread.
            mod_shape = None
            if mod is not None:
                entry = self.mod.get(self._mod_key(channel, verb))
                if entry is not None:
                    mod_shape = entry.get("shape")
            out.append((col["name"], col["value"], bar, round(float(frac), 3),
                       mod, tick, bool(col.get("small")), mod_shape))
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
            percent = int(round((zctrl.value - zctrl.value_min) / span * 100.0))
            # Same substitution as state_view(): a modulated port shows its
            # base, not the live value _mod_write() just swept it to.
            view[verb] = self._mod_override(self.group, verb, percent)
            # An enumerated or toggled port draws the plugin's own word over a
            # segmented bar instead of a number over a fill. The percent above
            # is still set: the modulator speaks in percent and mark_modulated
            # stamps the same column.
            switch = self._switch_view(verb)
            if switch is not None:
                view.setdefault("switch", {})[verb] = switch
            # The plugin's own name, wrapped across the tab row and the name
            # row by generated_columns and _tabs between them.
            name = getattr(zctrl, "name", None)
            if name:
                view.setdefault("names", {})[verb] = str(name)
        return view

    # --- switches -------------------------------------------------------
    #
    # An enumerated or toggled plugin port is a SWITCH: it has labels and
    # ticks, and turning a knob between two of them was the surface flattening
    # a distinction the engine had already made. The F row carries them in
    # CONTROL mode, one button directly above the encoder that owns the same
    # column.
    #
    # Everything decidable without a live controller is in techno_lib, where
    # it is unit tested - this half exists only because a zynthian_controller
    # cannot be imported off the Pi.

    def _port_name(self, verb):
        """The plugin's own name for a generated verb's port - "Pitch Bend
        Range", not the LV2 symbol - or the symbol abbreviation when the
        chain answers nothing.

        A name is what the tab row and the name row spell out between them.
        The symbol is the fallback rather than the source: symbols are written
        for a host, and two of them sharing their first eight characters is
        exactly the collision this fixes."""

        if verb is None:
            return ""
        zctrl = self._mod_zctrl(self.group, verb)
        name = getattr(zctrl, "name", None) if zctrl is not None else None
        if name:
            return str(name)
        return tlib.port_label(verb.split(":")[-1])

    def _switch_spec(self, verb):
        """(labels, ticks) for a generated verb whose port is a switch, else
        None. Resolved through _mod_zctrl, so it reaches the port exactly the
        way _verb_lv2 and the modulator do - never through
        zynthian_lv2.get_plugin_ports(), which is keyed by port INDEX."""

        if verb is None or not (verb.startswith(tlib.VERB_LV2)
                                or verb.startswith(tlib.VERB_FX)):
            return None
        zctrl = self._mod_zctrl(self.group, verb)
        if zctrl is None:
            return None
        return tlib.switch_spec(getattr(zctrl, "labels", None),
                                getattr(zctrl, "ticks", None))

    def _switch_view(self, verb):
        """(index, count, label) for a switch port, or None when this verb is
        not one.

        A MODULATED switch reads its BASE, not the sweep - the same
        substitution _generated_view() applies to every other generated
        column. Showing the LFO's current position here would put the word and
        the bar somewhere the button did not leave them."""

        spec = self._switch_spec(verb)
        if spec is None:
            return None
        labels, ticks = spec
        zctrl = self._mod_zctrl(self.group, verb)
        value = zctrl.value
        entry = self.mod.get(self._mod_key(self.group, verb))
        if entry is not None:
            span = zctrl.value_max - zctrl.value_min
            if span > 0:
                value = zctrl.value_min + span * (float(entry["base"]) / 100.0)
        index = tlib.switch_index(value, ticks, labels)
        return (index, len(ticks), labels[index])

    # RESTORED 2026-09-01. These two were deleted by accident in the same hunk
    # that removed _switch_press - they sat between it and _meter_frac - and
    # nothing caught it, because both remaining readers hide the failure:
    # _meter_frac's own try/except swallowed the AttributeError and returned
    # None for every channel forever, so the level meter would simply never
    # have worked again and the bar would have gone on showing fader position
    # with nothing to say it had stopped measuring. The other reader, in
    # _columns, is NOT guarded and raises the moment any visible column
    # carries a modulator - which is the first thing MOD does.
    #
    # A deletion that removes a constant a hundred lines from its readers is
    # exactly the kind of edit py_compile cannot see, and it is why the AST
    # guard in tests/test_maschine_mk2_lib.py now checks that every `self.X`
    # the driver reads is one the driver also sets.
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
        if self.lens_down:
            # THE LENS IS ONE PAGE and its arrows step the VERB, not a page.
            # Reading page_idx here counted the ring UNDERNEATH it, so the
            # indicator showed a position in a ring nothing could move -
            # `ALL RULE 2/2` while the arrows walked twenty verbs. Its own
            # title already names the verb, which is the only position that
            # means anything here.
            label = desc["title"]
        else:
            ring = self._ring()
            key = tlib.ring_key(self.mode, self._page_kind(self.group))
            label = tlib.page_label(desc["title"],
                                    self.page_idx.get(key, 0), len(ring))
        # THE STALL BANNER REPLACES EVERYTHING BELOW IT. Composed first and
        # returned early, because every suffix in the chain that follows makes
        # the line longer and the indicator truncates silently at 42
        # characters - the one message that must never be the one cut is the
        # one saying the instrument has stopped.
        stall = tlib.stall_label(time.monotonic(), self._beat_at, label)
        # The page indicator also carries who owns the channel and whether a
        # take is being captured. The tab row is left alone: dashed there means
        # "this channel is not sounding", and that meaning is not diluted.
        label = tlib.owner_label(
            label, self.owner[self.group], self.rec_down,
            self._play_state(self.group) != zynseq_lib.SEQ_STOPPED)
        label = tlib.type_label(label, self.kind_override[self.group])
        # MOD repurposes every encoder on whatever page is showing, so the
        # page indicator has to say it is on.
        mod = self.mod_down
        # The rate of the LAST-BOUND modulator, as a word. This is what
        # replaced the moving tick: a number that changes when you change it,
        # rather than an animation that rebuilt both screens six times a
        # second and killed the controller.
        rate_bars = None
        if mod and self.mod_last is not None:
            entry = self.mod.get(self.mod_last)
            if entry is not None:
                rate_bars = tlib.MOD_RATES[entry["rate"]]
        label = tlib.mod_rate_label(label, mod, rate_bars)
        # A pending reroll says so, and the tabs say which channels.
        label = tlib.reroll_label(label, bool(self._reroll_pending))
        # The bar of the phrase, so every timed gesture has something to
        # resolve against that the player can see.
        label = tlib.phrase_label(label, self._phrase_bar)
        # And FREEZE says the machine is being held, which is the difference
        # between held and broken.
        if self.bank_down:
            label = tlib.bank_label(self._bank_page, self.bank)
        label = tlib.arm_label(label, self.arm_down, self._arm_picked)
        # WHICH OVERLAY OWNS THE PADS, while it is latched. Six of them
        # compete for the same sixteen pads and the colours cannot tell them
        # apart - the eight channel hues leave two gaps wider than fifty
        # degrees and both are spent, measured rather than assumed. Since the
        # duration rule an overlay can be latched, which means the hand that
        # set it has left the button, so the one surface that can say which is
        # this row.
        #
        # Asked through _pad_owner(), the same predicate the pads and the pad
        # dispatcher use, so the word and the behaviour cannot disagree - and
        # it therefore respects the MOD+ARM chord for free.
        owner = self._pad_owner()
        label = tlib.overlay_label(
            label, owner,
            bool(owner) and self.latches[owner].latched)
        label = tlib.freeze_label(label, self.frozen, self.freeze_deep)
        label = tlib.repeat_label(label, bool(self._repeat_restore),
                                  len(self._repeat_restore))
        if self._timescale_note is not None:
            name, moved, asked = self._timescale_note
            label = tlib.scope_label(label, name, moved, asked)
        if stall != label and tlib.stalled(time.monotonic(), self._beat_at):
            label = stall
        for screen in (0, 1):
            # The label joins the cached tuple deliberately: paging with no
            # other change must still repaint.
            #
            # So does mod: without it both _render_display() calls in
            # _act_mod() were literal no-ops, because nothing else in the
            # tuple moves when MOD goes down, and a latched MOD made the pads
            # inert and the encoders mean something else with no indication.
            cols = self._columns(screen)
            # THE LIVE TICK IS DRAWN BUT DOES NOT TRIGGER A REDRAW. It is the
            # marker showing where a modulator's wave is RIGHT NOW, and it was
            # quantised only to the bar's pixel width - so every pixel of
            # movement rebuilt BOTH SCREENS. Measured on the rig 2026-08-20:
            # ~190 messages a second, essentially all of them display, about
            # six full rebuilds per second, and the controller was dead within
            # seconds of a modulator being bound. Four physical replugs.
            #
            # Quantising it more coarsely does not fix it: a fast rate crosses
            # any threshold many times a second. The only reliable answer is
            # that a continuously moving value must not be in the
            # change-detection key at all.
            #
            # So the tick redraws when something ELSE does. What is lost is
            # its animation; what is kept is a controller that answers.
            key = tuple(c[:5] + (None,) + c[6:] for c in cols)
            state = (self._tabs(screen), key, label, mod,
                     frozenset(self._reroll_pending), self._phrase_bar)
            if not self.leds.changed(f"disp{screen}", state):
                continue
            # Drawn from `cols`, which still carries the live tick - only the
            # comparison above ignores it.
            for packet in lib.screen_packets(screen, state[0], cols, state[2]):
                self._send_osc(packet)

    def _render_all(self):
        self._render_groups()
        self._render_transport()
        self._render_mutes()
        self._render_mod()
        self._render_coarse()
        # The modifier lights and FREEZE follow the same alphabet and have to
        # be repainted whenever anything else is: a latch survives the gesture
        # that set it, so an event-driven paint alone would leave a blink
        # frozen on whichever half the last paint caught.
        self._render_overlay_leds()
        self._render_freeze()
        self._render_static_leds()
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
        # A snapshot brings its own bank. Take it deliberately, here, where
        # every cache is about to be re-read anyway - so the once-a-second
        # check does not then report a restore as a drift.
        self._pin_bank()
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
