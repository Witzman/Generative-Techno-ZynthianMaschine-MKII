#!/bin/bash
for i in $(seq 1 30); do
    PORT=$(jack_lsp 2>/dev/null | grep -m1 'a2j:maschine rs.*Pads MIDI')
    if [ -n "$PORT" ]; then
        if jack_connect "$PORT" ZynMidiRouter:dev3_in 2>/dev/null; then
            echo "Connected: $PORT"
            /zynthian/venv/bin/python3 - "$PORT" <<'PYEOF'
import sys
import jack

# Zynthian derives a control-device id from the part of a JACK port alias
# after the first '/'. a2j gives user-client ports no alias at all, so the
# ctrldev driver could never bind without this.
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
    fi
    sleep 1
done
echo 'Maschine a2j port not found after 30s'
exit 0
