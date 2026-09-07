#!/bin/bash
# Keep the Zynthian UI's own VNC (:6080) up while plugin GUIs stay off.
#
# WHY A LOOP AND NOT A DEPENDENCY. With ZYNTHIAN_VNCSERVER_ENABLED=0 the UI
# calls stop_vncserver() from its own startup (zynthian_state_manager:2409),
# which stops BOTH VNC servers - the plugin-GUI one on 5901, which is what we
# want, and the UI's own on 5900, which we do not. Measured on the rig
# 2026-09-07: that happens well AFTER zynthian.service reports active, and it
# leaves vncserver0 in `failed`. So After=zynthian.service loses the race, and
# so would an ExecStartPost on the existing drop-in.
#
# This re-asserts vncserver0 over a bounded window instead. Idempotent, and it
# resets `failed` first so nothing is left looking broken. It never touches
# vncserver1: that one is meant to be down - see maschine-plugin-guis.sh.
set -u

WINDOW=${MASCHINE_VNC_UI_WINDOW:-120}   # seconds to keep watching
TICK=${MASCHINE_VNC_UI_TICK:-5}
deadline=$(( $(date +%s) + WINDOW ))
acted=0

log() { echo "maschine-vnc-ui: $*"; }

greets() {
    timeout 3 bash -c 'exec 3<>/dev/tcp/127.0.0.1/5900 && head -c 4 <&3' \
        2>/dev/null | grep -q RFB
}

while [ "$(date +%s)" -lt "$deadline" ]; do
    if ! greets; then
        systemctl reset-failed vncserver0 novnc0 2>/dev/null
        if systemctl start vncserver0 novnc0 2>/dev/null; then
            acted=$((acted + 1))
            log "started vncserver0 + novnc0 (assertion $acted)"
        else
            log "could not start vncserver0/novnc0 - will retry"
        fi
    fi
    sleep "$TICK"
done

if greets; then
    log "done: 5900 greets, :6080 is up after $acted assertion(s)"
    exit 0
fi
# A failure here is the owner losing their only screen on a headless rig, so it
# is loud in the journal rather than a silent exit 0.
log "FAILED: 5900 does not greet after ${WINDOW}s and $acted attempt(s)"
exit 1
