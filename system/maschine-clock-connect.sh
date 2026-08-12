#!/bin/bash
# Connect maschine-clock ALSA port to maschine MIDI Control
for i in $(seq 1 30); do
    CLOCK=$(aconnect -l 2>/dev/null | grep -m1 'RtMidiOut' | grep -oP 'client \K[0-9]+')
    MASCHINE=$(aconnect -l 2>/dev/null | grep -m1 'maschine.rs' | grep -oP 'client \K[0-9]+')
    if [ -n "$CLOCK" ] && [ -n "$MASCHINE" ]; then
        aconnect "$CLOCK:0" "$MASCHINE:1" 2>/dev/null && echo "Clock connected: $CLOCK:0 -> $MASCHINE:1" && exit 0
    fi
    sleep 1
done
echo 'maschine-clock or maschine.rs port not found after 30s'
exit 0
