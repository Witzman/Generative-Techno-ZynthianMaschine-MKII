"""Tests for the pattern -> MIDI file exporter.

Pure: every test builds its own riff bytes and reads back the MIDI it
produces. Nothing here touches a snapshot on disk, a rig, or a sequencer.
"""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importlib
exporter = importlib.import_module("export-patterns-midi")


def riff(tempo=125, patterns=None):
    """A minimal v10 riff: a vers block and eight patn blocks.

    `patterns` is eight lists of (step, note, velocity).
    """
    patterns = patterns or [[] for _ in range(8)]
    out = bytearray()
    vers = bytearray(16)
    vers[4:6] = struct.pack(">H", tempo)
    out += b"vers" + struct.pack(">I", len(vers)) + vers
    for events in patterns:
        body = bytearray(exporter.PATN_HEADER)
        for step, note, velo in events:
            ev = bytearray(exporter.PATN_EVENT)
            ev[0:4] = struct.pack(">I", step)
            ev[12] = 0x90
            ev[13] = note
            ev[14] = velo
            body += ev
        out += b"patn" + struct.pack(">I", len(body)) + bytes(body)
    return bytes(out)


class ReadingTheRiff(unittest.TestCase):

    def test_the_tempo_comes_from_the_vers_block(self):
        self.assertEqual(exporter.riff_tempo(exporter.parse_blocks(riff(137))), 137)

    def test_events_decode_to_step_note_and_velocity(self):
        pats = [[] for _ in range(8)]
        pats[0] = [(0, 36, 100), (4, 36, 90), (8, 36, 100), (12, 36, 90)]
        got = exporter.read_patterns(exporter.parse_blocks(riff(patterns=pats)))
        self.assertEqual(got[0], [(0, 36, 100), (4, 36, 90), (8, 36, 100), (12, 36, 90)])

    def test_a_four_on_the_floor_kick_is_recognisable(self):
        # The finding that decoded this format checked itself the same way:
        # pattern 10 decodes to steps 0, 4, 8, 12.
        pats = [[(s, 36, 100) for s in (0, 4, 8, 12)]] + [[] for _ in range(7)]
        got = exporter.read_patterns(exporter.parse_blocks(riff(patterns=pats)))
        self.assertEqual([e[0] for e in got[0]], [0, 4, 8, 12])

    def test_eight_channels_come_back_even_when_empty(self):
        # An empty channel must be an empty track, not a missing one: the
        # track number is how a reader knows which channel they are looking at.
        got = exporter.read_patterns(exporter.parse_blocks(riff()))
        self.assertEqual(len(got), 8)
        self.assertEqual(got, [[]] * 8)

    def test_a_non_note_event_is_skipped(self):
        # Only 0x90 is a note on. Anything else in that byte is not ours to
        # guess at, and inventing a note from it would be worse than dropping.
        raw = bytearray(riff(patterns=[[(0, 36, 100)]] + [[] for _ in range(7)]))
        i = raw.index(b"patn") + 8 + exporter.PATN_HEADER
        raw[i + 12] = 0x80
        self.assertEqual(exporter.read_patterns(exporter.parse_blocks(bytes(raw)))[0], [])

    def test_a_step_outside_the_pattern_is_refused(self):
        pats = [[(99, 36, 100)]] + [[] for _ in range(7)]
        with self.assertRaises(ValueError):
            exporter.read_patterns(exporter.parse_blocks(riff(patterns=pats)))


class WritingTheMidi(unittest.TestCase):

    def _mid(self, pats, tempo=125):
        return exporter.build_midi(pats, tempo)

    def test_it_is_a_type_1_file_with_a_track_per_channel_plus_the_tempo_map(self):
        data = self._mid([[] for _ in range(8)])
        self.assertTrue(data.startswith(b"MThd"))
        fmt, ntrks, div = struct.unpack(">HHH", data[8:14])
        self.assertEqual(fmt, 1)
        self.assertEqual(ntrks, 9)          # eight channels and a tempo track
        self.assertEqual(div, exporter.PPQ)

    def test_the_tempo_is_carried_as_microseconds_per_beat(self):
        data = self._mid([[] for _ in range(8)], tempo=120)
        self.assertIn(b"\xff\x51\x03" + (500000).to_bytes(3, "big"), data)

    def test_a_note_lands_on_the_right_tick(self):
        # Step 4 at four steps to the beat is one beat in.
        pats = [[(4, 36, 100)]] + [[] for _ in range(7)]
        events = exporter.track_events(pats[0], channel=0)
        self.assertEqual(events[0], (4 * exporter.TICKS_PER_STEP, b"\x90\x24\x64"))

    def test_every_note_gets_an_off_exactly_one_step_later(self):
        # The duration encoding in the riff was never cracked - deliberately,
        # because it is inconsistent across channels and the drums are
        # one-shots that ignore it. A uniform one-step gate is declared rather
        # than invented; a made-up duration would be worse than an honest one.
        pats = [[(0, 36, 100)]] + [[] for _ in range(7)]
        events = exporter.track_events(pats[0], channel=0)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1], (exporter.TICKS_PER_STEP, b"\x80\x24\x00"))

    def test_each_channel_writes_to_its_own_midi_channel(self):
        events = exporter.track_events([(0, 36, 100)], channel=5)
        self.assertEqual(events[0][1][0], 0x95)

    def test_simultaneous_notes_both_survive(self):
        # Two events on one step is legal and the exporter must not collapse
        # them - a closed hat and a kick on the same sixteenth is normal.
        events = exporter.track_events([(0, 36, 100), (0, 42, 80)], channel=0)
        self.assertEqual(len([e for e in events if e[1][0] == 0x90]), 2)

    def test_events_come_out_in_tick_order(self):
        events = exporter.track_events([(8, 36, 100), (0, 38, 90)], channel=0)
        self.assertEqual(events, sorted(events, key=lambda e: e[0]))

    def test_a_variable_length_quantity_round_trips(self):
        for n in (0, 1, 127, 128, 8192, 0x0FFFFFFF):
            self.assertEqual(exporter.read_vlq(exporter.vlq(n)), n)

    def test_a_track_ends_with_end_of_track(self):
        self.assertTrue(exporter.build_track([], "x").endswith(b"\xff\x2f\x00"))


if __name__ == "__main__":
    unittest.main()
