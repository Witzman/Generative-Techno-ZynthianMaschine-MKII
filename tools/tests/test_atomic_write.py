"""The write that cannot leave half a snapshot behind."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atomic_write


class AtomicWriteCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "snapshot.zss")

    def leftovers(self):
        return [n for n in os.listdir(self.dir) if n != "snapshot.zss"]

    def test_it_writes_the_content(self):
        atomic_write.write_text(self.path, "hello")
        with open(self.path) as fh:
            self.assertEqual(fh.read(), "hello")

    def test_json_matches_what_json_dump_produced(self):
        # The byte-for-byte round-trip guards in set-snapshot-tempo and
        # fix-snapshot-identity compare against `json.dump(..., indent=2)`, so
        # this has to be the same bytes and not merely the same document.
        doc = {"b": 1, "a": [1, 2, {"c": None}]}
        atomic_write.write_json(self.path, doc)
        with open(self.path) as fh:
            self.assertEqual(fh.read(), json.dumps(doc, indent=2))

    def test_it_leaves_no_temp_file_behind(self):
        atomic_write.write_json(self.path, {"a": 1})
        self.assertEqual(self.leftovers(), [])

    def interrupt_mid_write(self, content="the new one"):
        """Raise KeyboardInterrupt after the bytes are written and before the
        file is put in place - the moment a Ctrl-C is most likely to land."""

        real = atomic_write.os.fsync

        def boom(fd):
            raise KeyboardInterrupt

        atomic_write.os.fsync = boom
        try:
            atomic_write.write_text(self.path, content)
        finally:
            atomic_write.os.fsync = real

    def test_an_interrupted_write_leaves_the_ORIGINAL_intact(self):
        # THIS IS THE WHOLE POINT. `open(path, "w")` truncates first, so the
        # same interruption used to leave an empty or half-written snapshot -
        # and on the rig that file is the only copy.
        atomic_write.write_text(self.path, "the original")
        with self.assertRaises(KeyboardInterrupt):
            self.interrupt_mid_write()
        with open(self.path) as fh:
            self.assertEqual(fh.read(), "the original")

    def test_an_interrupted_write_cleans_up_its_temp_file(self):
        atomic_write.write_text(self.path, "the original")
        with self.assertRaises(KeyboardInterrupt):
            self.interrupt_mid_write()
        self.assertEqual(self.leftovers(), [])

    def test_an_existing_file_keeps_its_permissions(self):
        # mkstemp makes 0600 and os.replace keeps the temp file's mode, so the
        # first version of this helper silently turned every 0644 snapshot into
        # a root-only one. Zynthian runs as root, so nothing would have
        # complained until something else had to read the file.
        atomic_write.write_text(self.path, "before")
        os.chmod(self.path, 0o644)
        atomic_write.write_text(self.path, "after")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o644)

    def test_an_odd_mode_is_preserved_too(self):
        atomic_write.write_text(self.path, "before")
        os.chmod(self.path, 0o640)
        atomic_write.write_json(self.path, {"a": 1})
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o640)

    def test_a_new_file_is_readable(self):
        fresh = os.path.join(self.dir, "new.zss")
        atomic_write.write_text(fresh, "x")
        mode = os.stat(fresh).st_mode & 0o777
        self.assertTrue(mode & 0o044, f"a new snapshot must be readable, got {oct(mode)}")

    def test_bytes_round_trip(self):
        atomic_write.write_bytes(self.path, b"\x00\x01MThd")
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), b"\x00\x01MThd")

    def test_the_temp_file_is_in_the_target_directory(self):
        # Not /tmp: os.replace is only atomic within one filesystem, and the
        # rig's snapshots and /tmp are on different ones (/tmp is a tmpfs).
        seen = []
        real = atomic_write.tempfile.mkstemp

        def spy(**kwargs):
            seen.append(kwargs["dir"])
            return real(**kwargs)

        atomic_write.tempfile.mkstemp = spy
        try:
            atomic_write.write_text(self.path, "x")
        finally:
            atomic_write.tempfile.mkstemp = real
        self.assertEqual(seen, [os.path.abspath(self.dir)])


if __name__ == "__main__":
    unittest.main()
