#!/usr/bin/env python3
"""
JACK transport → Maschine MK2 MIDI clock bridge.
Uses ctypes for JACK transport query (avoids python-jack binding bugs).
Sends 0xF8 at 24 PPQN via rtmidi virtual ALSA port.
maschine-clock-connect.sh wires the ALSA port to maschine MIDI Control.
"""
import ctypes
import rtmidi
import time
import sys

PPQN = 24
DEFAULT_BPM = 120.0
JackTransportRolling = 1
JackPositionBBT = 0x10
JackNullOption = 0x00


class JackPosition(ctypes.Structure):
    _fields_ = [
        ('unique_1',         ctypes.c_uint64),
        ('usecs',            ctypes.c_uint64),
        ('frame_rate',       ctypes.c_uint32),
        ('frame',            ctypes.c_uint32),
        ('valid',            ctypes.c_int),
        ('bar',              ctypes.c_int32),
        ('beat',             ctypes.c_int32),
        ('tick',             ctypes.c_int32),
        ('bar_start_tick',   ctypes.c_double),
        ('beats_per_bar',    ctypes.c_float),
        ('beat_type',        ctypes.c_float),
        ('ticks_per_beat',   ctypes.c_double),
        ('beats_per_minute', ctypes.c_double),
        ('frame_time',       ctypes.c_double),
        ('next_time',        ctypes.c_double),
        ('bbt_offset',       ctypes.c_uint32),
        ('audio_frames_per_video_frame', ctypes.c_float),
        ('video_offset',     ctypes.c_uint32),
        ('padding',          ctypes.c_int32 * 7),
        ('unique_2',         ctypes.c_uint64),
    ]


libjack = ctypes.CDLL('libjack.so.0')
libjack.jack_client_open.restype = ctypes.c_void_p
libjack.jack_client_open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
libjack.jack_transport_query.restype = ctypes.c_int
libjack.jack_transport_query.argtypes = [ctypes.c_void_p, ctypes.POINTER(JackPosition)]
libjack.jack_activate.restype = ctypes.c_int
libjack.jack_activate.argtypes = [ctypes.c_void_p]
libjack.jack_client_close.restype = ctypes.c_int
libjack.jack_client_close.argtypes = [ctypes.c_void_p]

jclient = libjack.jack_client_open(b'maschine-clock-bridge', JackNullOption, None)
if not jclient:
    print('Failed to connect to JACK server', flush=True)
    sys.exit(1)

libjack.jack_activate(jclient)

midiout = rtmidi.MidiOut()
midiout.open_virtual_port('maschine-clock')
print('maschine-clock ALSA port open', flush=True)

last_bpm = DEFAULT_BPM

while True:
    try:
        pos = JackPosition()
        libjack.jack_transport_query(jclient, ctypes.byref(pos))
        bpm = last_bpm
        if pos.valid & JackPositionBBT and pos.beats_per_minute > 0:
            bpm = pos.beats_per_minute
            last_bpm = bpm

        midiout.send_message([0xF8])
        time.sleep(60.0 / (bpm * PPQN))

    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f'error: {e}', flush=True)
        time.sleep(0.1)

libjack.jack_client_close(jclient)
