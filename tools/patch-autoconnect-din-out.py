"""Send every chain's MIDI to the Maschine MK2's DIN OUT socket.

    python3 tools/patch-autoconnect-din-out.py [path/to/zynthian_autoconnect.py]

WHY A PATCH, AND NOT A SETTING. Zynthian already has per-chain MIDI outputs
(`chain.midi_out`, defaulting to MIDI-OUT and NET-OUT), and they do nothing for
this instrument: `zynthian_chain.rebuild_midi_graph` feeds them from the chain's
last MIDI processor, and a synth chain has none, so its list of sources is
EMPTY. A drum or voice chain's notes never leave the box that way.

What does carry them is `ZynMidiRouter:chN_out`, the router's output for chain
N. Everything the chain is about to play arrives there - the notes the
generator wrote into zynseq AND the notes played on the pads - so connecting it
to the DIN port sends exactly what the sound engines hear, on the MIDI channel
the chain owns. Eight chains merge onto one cable as channels 1-8.

WHY IT IS INSIDE AUTOCONNECT. A `jack_connect` made by hand is undone on the
next autoconnect pass: for every destination port it knows, it disconnects
anything not in `required_routes`. The hardware output is such a port, so the
route has to be one of the required ones. Same reason, same mechanism, as
tools/patch-autoconnect-maschine.py.

THE PORT IS FOUND BY ITS ALIAS, never by `system:midi_playback_N` - the
number is the order the kernel enumerated the cards in, and the alias carries
the USB path too (`USB:1.1.2/Maschine Controller MK2 OUT 1`), which moves when
the controller is replugged. Only the stable part is matched.

IT IS IDEMPOTENT and refuses loudly when the anchor is missing, which is what a
Zynthian update that rewrote this function looks like. Re-run it after every
Zynthian system update, like the other one.

DO NOT LOOP A CABLE FROM DIN OUT TO DIN IN. DIN IN is routed into every chain
by default, so the notes would come straight back out - a feedback storm.
"""
import pathlib
import sys

MARKER = "MASCHINE DIN OUT"

ANCHOR = ('            if src_ports:\n'
          '                # Connect to first slot, excluding clippy\n')

# Kept as a constant so the test can run the very text that gets inserted,
# against fake ports, instead of only checking that the text is present.
SNIPPET = '''\
            # MASCHINE DIN OUT: the chain's router output also goes to the
            # Maschine MK2's DIN socket. See tools/patch-autoconnect-din-out.py.
            if src_ports:
                for din_out in devices_out:
                    if din_out is not None and din_out.aliases \\
                            and "Maschine Controller MK2 OUT" in din_out.aliases[0]:
                        required_routes[din_out.name].add(src_ports[0].name)
'''


def patch(source):
    """Return `source` with the DIN-out route added. Raises on a missing or
    ambiguous anchor, and returns it unchanged when already patched."""
    if MARKER in source:
        return source
    if source.count(ANCHOR) != 1:
        raise SystemExit(
            f"anchor found {source.count(ANCHOR)} times, expected once - "
            "zynthian_autoconnect.py has changed shape and this patch must be "
            "re-read against it, not forced")
    return source.replace(ANCHOR, SNIPPET + ANCHOR)


def main(argv):
    path = pathlib.Path(argv[1] if len(argv) > 1 else
                        "/zynthian/zynthian-ui/zynautoconnect/zynthian_autoconnect.py")
    text = path.read_text()
    new = patch(text)
    if new == text:
        print("already patched, nothing to do")
        return 0
    path.write_text(new)
    print("zynautoconnect patched: every chain's MIDI also goes to the MK2 DIN out")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
