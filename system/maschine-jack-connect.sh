#!/bin/bash
#
# Waits for the daemon's a2j port and pins a stable JACK alias on it.
#
# THIS SCRIPT DELIBERATELY DOES NOT CONNECT THE PORT. It used to run
#
#     jack_connect "$PORT" ZynMidiRouter:dev3_in
#
# and that was the cause of the duplicate-route fault: patched zynautoconnect
# whitelists "maschine rs.*Pads MIDI" as a hardware MIDI source, so Zynthian
# assigns the port a zmip slot and connects it ITSELF - to whichever slot it
# picks, which on this rig is dev2_in. Both connections then persisted, the
# port showed two ZynMidiRouter:devN_in routes, and every pad tap fired twice.
#
# Measured 2026-08-15: the stale route was always dev3_in, this script's own
# hardcoded target, and the journal shows this script connecting a few seconds
# after a2jmidid creates the port. The fault survived a clean boot, which is
# what ruled out a restart-order artefact.
#
# The alias below is kept even though patched zynautoconnect now derives the
# device uid from port.name rather than from an alias. It is harmless, it
# costs one call at startup, and it was not traced to every possible consumer
# before this change - so it stays until something proves it dead.

for i in $(seq 1 30); do
    PORT=$(jack_lsp 2>/dev/null | grep -m1 'a2j:maschine rs.*Pads MIDI')
    if [ -n "$PORT" ]; then
        echo "Found: $PORT"
        /zynthian/venv/bin/python3 - "$PORT" <<'PYEOF'
import sys
import jack

# Zynthian can derive a control-device id from the part of a JACK port alias
# after the first '/'. a2j gives user-client ports no alias at all, so this
# pins one. Patched zynautoconnect also special-cases the port by name, so
# this is belt-and-braces rather than the only route to a stable id.
port_name = sys.argv[1]
client = jack.Client("maschine-alias", no_start_server=True)
try:
    port = client.get_port_by_name(port_name)
    for alias in list(port.aliases):
        port.unset_alias(alias)
    port.set_alias("virtual:maschine.rs/Maschine MK2 Pads")
    print(f"Alias set: {port.aliases}")
finally:
    client.close()
PYEOF
        exit 0
    fi
    sleep 1
done
echo 'Maschine a2j port not found after 30s'
exit 0
