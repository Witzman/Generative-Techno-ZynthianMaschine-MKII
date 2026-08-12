import pathlib
import sys

p = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                 else "/zynthian/zynthian-ui/zynautoconnect/zynthian_autoconnect.py")
s = p.read_text()

if "maschine rs.*Pads MIDI" in s:
    print("already patched, nothing to do")
    raise SystemExit(0)

# 1) treat the daemon's output port as a hardware MIDI source, so Zynthian
#    assigns it a zmip slot and a ctrldev driver can attach to it
old = ('    for port_name in ("QmidiNet:out", "jackrtpmidid:rtpmidi_out", '
       '"jacknetumpd:netump_out", "RtMidiOut Client:TouchOSC Bridge", "aubio"):')
new = ('    for port_name in ("QmidiNet:out", "jackrtpmidid:rtpmidi_out", '
       '"jacknetumpd:netump_out", "RtMidiOut Client:TouchOSC Bridge", "aubio", '
       '"maschine rs.*Pads MIDI"):')
assert s.count(old) == 1, "source whitelist anchor not found"
s = s.replace(old, new)

# 2) give that port a stable uid, the same way ttymidi / ZynMaster / zynseq are
#    special-cased, so the derived device id survives reboots
anchor = '    elif port.name.startswith("aubio:midi_out"):\n'
assert s.count(anchor) == 1, "build_midi_port_name anchor not found"
idx = s.index(anchor)
end = s.index("\n", s.index("return", idx)) + 1
addition = (
    '    elif "maschine rs" in port.name and "Pads MIDI" in port.name:\n'
    '        # MaschineMK2_linux daemon. It is a virtual a2j client, so it never\n'
    '        # gets a USB-style uid, and the ALSA client number embedded in the\n'
    '        # port name changes across boots. Pin a stable uid so that ctrldev\n'
    '        # drivers can bind to it by device id.\n'
    '        return "virtual:maschine.rs/Maschine MK2 Pads", "Maschine MK2"\n'
)
s = s[:end] + addition + s[end:]

p.write_text(s)
print("zynautoconnect patched: whitelist + stable uid")
