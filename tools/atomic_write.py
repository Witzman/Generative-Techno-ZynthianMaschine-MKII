"""Write a file so that an interrupted run cannot destroy the old one.

WHY THIS EXISTS. Every tool in here wrote its output with `open(path, "w")`,
which truncates the file before the first byte of the new content is produced.
The content checks in these tools are genuinely good - `set-snapshot-tempo`
refuses unless a round trip reproduces the original byte for byte, and
`fix-snapshot-identity` restores the original when it cannot - but all of that
protects against writing the WRONG thing, and none of it protects against not
finishing. A Ctrl-C, a full tmpfs or a closed laptop lid between the truncate
and the flush leaves a `.zss` that is empty or half a JSON document.

That matters more here than in most places: several of these tools are pointed
at the snapshots the rig actually boots from, where the file being edited is
the only copy.

Temp file in the SAME DIRECTORY, then `os.replace`, which is atomic on POSIX
for a rename within one filesystem: readers see either the old file or the new
one, never a partial one. A crash leaves the temp file behind and the original
untouched.
"""

import json
import os
import tempfile


def _permissions_for(path):
    """The mode the finished file must have.

    `mkstemp` creates 0600 and `os.replace` keeps the temp file's mode, so
    without this every rewrite silently narrowed a 0644 snapshot to root-only.
    That reads as working - Zynthian runs as root - right up to the point
    something else has to read the file.

    An existing file keeps its own mode. A new one gets 0644 minus the umask,
    which is what `open()` would have produced.
    """
    try:
        return os.stat(path).st_mode & 0o7777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o644 & ~umask


def _replace(path, data, mode):
    directory = os.path.dirname(os.path.abspath(path))
    permissions = _permissions_for(path)
    fd, tmp = tempfile.mkstemp(
        dir=directory, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, mode) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, permissions)
        os.replace(tmp, path)
    except BaseException:
        # Includes KeyboardInterrupt, which is the whole point.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_text(path, text):
    """Replace `path` with `text`, atomically."""
    _replace(path, text, "w")


def write_bytes(path, data):
    """Replace `path` with `data`, atomically."""
    _replace(path, data, "wb")


def write_json(path, doc, indent=2):
    """Replace `path` with `doc` as JSON, atomically.

    `indent=2` and no trailing newline, which is what every caller here did
    with `json.dump` - the byte-for-byte round-trip guards in
    `set-snapshot-tempo` and `fix-snapshot-identity` depend on that exact form.
    """
    write_text(path, json.dumps(doc, indent=indent))
