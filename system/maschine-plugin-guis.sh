#!/bin/bash
# Engine plugin GUIs: off, on, or what is the state right now.
#
# WHY THIS EXISTS. A plugin Zynthian hosts in jalv.gtk3 - because it ships an
# LV2 UI - and that a modulator writes to spins its GTK idle loop at ~70-80 %
# of a core, doing no audio work: ~140 ms of CPU per parameter write, 99.9 %
# userspace. Measured on the rig 2026-09-07: 031-house-classic went from
# 189.3 % of a core to 97.2 % with the GUIs off, and the modulated instance
# fell from 80.1 % to its siblings' 10 %. Eight of the twelve effects the
# packs use carry a UI, and 50 of the 71 presets carry at least one modulator
# aimed at one.
#
# THE LEVER IS ZYNTHIAN'S OWN CONFIG, NOT A PATCH.
# zynthian_engine.config_remote_display() picks jalv.gtk3 over plain jalv when
# `systemctl is-active vncserver1` succeeds, and ZYNTHIAN_VNCSERVER_ENABLED
# decides whether Zynthian starts that server at boot.
#
# vncserver1 / novnc1  : 5901, :6081  engine plugin GUIs   <- this is the cost
# vncserver0 / novnc0  : 5900, :6080  the Zynthian UI      <- kept, always
#
# Only vncserver1 takes part in the host choice, so the screen you actually
# use is not the price. maschine-vnc-ui.service is what keeps :6080 up.
set -u

ENVARS=/zynthian/config/zynthian_envars.sh
BACKUP=/zynthian/config/zynthian_envars.sh.pre-maschine

usage() {
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
    echo
    echo "usage: $(basename "$0") off|on|status [--restart]"
    echo
    echo "  off       plugin GUIs off. Frees ~0.7 of a core per modulated"
    echo "            GUI-hosted plugin. Takes full effect when the chains are"
    echo "            next rebuilt - use --restart to do that now."
    echo "  on        plugin GUIs back. COSTS ~0.7 of a core per modulated"
    echo "            GUI-hosted plugin; 50 of the 71 presets carry one."
    echo "  status    the envar, the four units, both ports, and the host"
    echo "            binaries actually running. A measurement, not a memory."
    echo "  --restart restart zynthian so the chains rebuild immediately."
}

set_envar() {
    # Idempotent, and it keeps ONE backup of the file as it was before this
    # instrument ever touched it - a second run must not overwrite that with
    # a value this script itself wrote.
    [ -f "$BACKUP" ] || cp -a "$ENVARS" "$BACKUP"
    if grep -q '^export ZYNTHIAN_VNCSERVER_ENABLED=' "$ENVARS"; then
        sed -i "s/^export ZYNTHIAN_VNCSERVER_ENABLED=.*/export ZYNTHIAN_VNCSERVER_ENABLED=\"$1\"/" "$ENVARS"
    else
        echo "export ZYNTHIAN_VNCSERVER_ENABLED=\"$1\"" >> "$ENVARS"
    fi
}

port_code() {
    # NO `|| echo 000` HERE. curl already prints 000 when the connection is
    # refused AND exits non-zero, so the fallback appended a second one and
    # status printed ":6081=000000".
    curl -sk -o /dev/null -w '%{http_code}' --max-time 10 \
         "https://127.0.0.1:$1/vnc.html" 2>/dev/null
}

rfb() {
    # A greeting, not an open port: noVNC answering proves only the proxy.
    timeout 5 bash -c "exec 3<>/dev/tcp/127.0.0.1/$1 && head -c 12 <&3" 2>/dev/null || echo "no answer"
}

hosts_by_binary() {
    for d in /proc/[0-9]*; do
        [ -r "$d/cmdline" ] || continue
        b=$(tr '\0' '\n' < "$d/cmdline" 2>/dev/null | head -1)
        case "$(basename "${b:-x}")" in jalv*) basename "$b" ;; esac
    done | sort | uniq -c
}

case "${1:-status}" in
off)
    set_envar 0
    systemctl stop novnc1 vncserver1 2>/dev/null
    # Leave nothing in `failed`: a stopped Requires= dependency puts novnc1
    # there, and a unit sitting in failed reads like a broken rig.
    systemctl reset-failed novnc1 vncserver1 2>/dev/null
    systemctl reset-failed vncserver0 novnc0 2>/dev/null
    systemctl start vncserver0 novnc0 2>/dev/null
    echo "plugin GUIs OFF. The Zynthian UI stays on :6080."
    # MEASURED 2026-09-07: starting vncserver0 HERE is not enough. With the
    # envar at 0 the UI's own startup calls stop_vncserver() and takes it down
    # again - so on this rig the switch left vncserver0 `failed`, 5900 silent,
    # and :6080 answering only because novnc0 (the proxy) was still up. The
    # keeper is what re-asserts it after the UI has finished starting, and it
    # has to be kicked after the restart below rather than before it.
    ;;
on)
    set_envar 1
    systemctl reset-failed novnc1 vncserver1 2>/dev/null
    systemctl start novnc1 2>/dev/null || systemctl start vncserver1 novnc1
    echo "plugin GUIs ON, at ~0.7 of a core per modulated GUI-hosted plugin."
    ;;
status)
    echo "envar:   $(grep '^export ZYNTHIAN_VNCSERVER_ENABLED=' "$ENVARS" 2>/dev/null || echo '(not set)')"
    printf 'units:   vncserver0=%s novnc0=%s vncserver1=%s novnc1=%s\n' \
        "$(systemctl is-active vncserver0)" "$(systemctl is-active novnc0)" \
        "$(systemctl is-active vncserver1)" "$(systemctl is-active novnc1)"
    printf 'ports:   :6080=%s (UI)  :6081=%s (plugin GUIs)\n' \
        "$(port_code 6080)" "$(port_code 6081)"
    printf 'rfb:     5900=%q  5901=%q\n' "$(rfb 5900)" "$(rfb 5901)"
    echo "hosts:"
    hosts_by_binary | sed 's/^/         /'
    echo "         jalv.gtk3 present means plugin GUIs are ON for those chains."
    exit 0
    ;;
-h|--help|help)
    usage; exit 0 ;;
*)
    usage; exit 2 ;;
esac

case "${2:-}" in
--restart)
    echo "restarting zynthian so the chains rebuild..."
    systemctl restart zynthian
    # --no-block: the keeper watches for a couple of minutes by design, and
    # nothing here should wait for it.
    systemctl start --no-block maschine-vnc-ui 2>/dev/null
    echo "maschine-vnc-ui kicked; :6080 comes back within ~30 s."
    ;;
*)
    echo "Chains keep their current hosts until zynthian next restarts."
    echo "Pass --restart to rebuild them now."
    ;;
esac
