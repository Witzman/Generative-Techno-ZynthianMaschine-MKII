"""The zynseq RIFF inside a `.zss`, read and written in ONE place.

WHY THIS EXISTS, and the entry that asked for it named the trigger exactly:
*"two decoders of one binary format drift... if a third tool needs the riff,
that is the moment to lift these out rather than the moment after."*

**The moment was passed twice without anyone noticing, and they HAD drifted.**
On 2026-09-02 there were THREE independent copies across four consumers:

| tool | had | notes |
|---|---|---|
| `build-genre-snapshots.py` | `parse_blocks`, `build_blocks` | the original |
| `build-factory-snapshot.py` | imports the above by FILENAME | `spec_from_file_location` on a sibling script |
| `export-patterns-midi.py` | its own `parse_blocks` | a straight copy |
| `set-snapshot-tempo.py` | its own `parse_blocks` AND `build_blocks` | **different in three ways** |

`set-snapshot-tempo`'s copy decoded block ids as **ascii** where the others
used **latin1**, returned **tuples** instead of lists, raised on a truncated
header where the others stopped silently, and did **not** check for trailing
bytes. Two behaviours, three copies, one binary format - which is the whole
argument the original entry made in advance.

**This module is the union of what each copy got right**: latin1, because it
is what two of the three did and it cannot raise on a block id the file
actually contains; LISTS, because the builders mutate a block body in place;
the truncated-header raise, because a header that runs off the end is a
corrupt file and saying so beats returning a short list; and the trailing-byte
check, for the same reason.

The format itself: a flat sequence of blocks, each a **4-byte id** then a
**big-endian u32 length** then that many bytes. No nesting, no padding.
"""

import struct


def parse_blocks(raw):
    """`[[id, bytearray], ...]` for a whole riff.

    Lists rather than tuples so a caller can replace a body in place - that is
    what every builder does, and it is why `set-snapshot-tempo`'s tuple
    version could never have been the shared one.
    """
    blocks, off = [], 0
    while off < len(raw):
        if off + 8 > len(raw):
            raise ValueError("riff has a truncated block header")
        bid = raw[off:off + 4].decode("latin1")
        size = struct.unpack(">I", raw[off + 4:off + 8])[0]
        if off + 8 + size > len(raw):
            raise ValueError(f"riff block {bid!r} runs past the end")
        blocks.append([bid, bytearray(raw[off + 8:off + 8 + size])])
        off += 8 + size
    if off != len(raw):
        raise ValueError(f"riff has {len(raw) - off} trailing bytes")
    return blocks


def build_blocks(blocks):
    """The inverse. Accepts anything iterable of `(id, body)`, so a caller
    holding tuples is not broken by the switch to lists."""
    out = bytearray()
    for bid, body in blocks:
        out += bid.encode("latin1") + struct.pack(">I", len(body)) + body
    return bytes(out)
