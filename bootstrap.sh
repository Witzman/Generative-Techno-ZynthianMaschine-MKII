#!/usr/bin/env bash
# Generative-Techno ZynthianMaschine MKII - one-command install for a fresh Pi.
# Fetches the repository, runs install.sh, places the factory snapshot, verifies.
# Everything it does is documented step by step in section 4 of the guide:
# https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/04-manual-installation.html
#
# The whole body sits in main(), called on the last line, so a truncated
# download executes nothing.
set -eu

REPO_URL=https://github.com/Witzman/Generative-Techno-ZynthianMaschine-MKII
REPO_DIR=/root/Generative-Techno-ZynthianMaschine-MKII
SNAP_ROOT=/zynthian/zynthian-my-data/snapshots
SNAP_DIR="$SNAP_ROOT/000"
SNAP=017-generative-techno.zss
PACK_DIR="$REPO_DIR/snapshot/genre-pack"   # the fifty genre snapshots, 031-080

main() {
    DRY=0
    [ "${1:-}" = "--dry-run" ] && DRY=1

    # --- refuse to run anywhere but a ZynthianOS Pi ---------------------------
    if [ ! -f /zynthian/build_info.txt ]; then
        echo "This is not a ZynthianOS install (/zynthian/build_info.txt missing)." >&2
        echo "Run this on the Pi, not on your laptop." >&2
        exit 1
    fi
    [ "$(id -u)" = "0" ] || { echo "Run as root." >&2; exit 1; }

    echo "== ZynthianOS: $(head -1 /zynthian/build_info.txt)"
    [ "$DRY" = 1 ] && echo "DRY RUN - nothing will be changed."

    # --- 1. the repository ---------------------------------------------------
    echo "== Fetch the repository into $REPO_DIR"
    if [ -d "$REPO_DIR/.git" ]; then
        if [ "$DRY" = 1 ]; then
            echo "  [dry-run] git -C $REPO_DIR pull --ff-only"
        else
            git -C "$REPO_DIR" pull --ff-only
        fi
    else
        if [ "$DRY" = 1 ]; then
            echo "  [dry-run] git clone $REPO_URL $REPO_DIR"
        else
            git clone "$REPO_URL" "$REPO_DIR"
        fi
    fi

    # --- 2. the installer ----------------------------------------------------
    echo "== Install (this compiles the daemon: about ten minutes, do not interrupt)"
    if [ "$DRY" = 1 ]; then
        if [ -x "$REPO_DIR/install.sh" ]; then
            "$REPO_DIR/install.sh" --dry-run
        else
            echo "  [dry-run] $REPO_DIR/install.sh   (not present until the clone runs)"
        fi
    else
        "$REPO_DIR/install.sh"
    fi

    # --- 3. the factory snapshot ---------------------------------------------
    # Two copies, for two different jobs.
    #
    # In bank 000 so it appears in the UI's snapshot list. The bank
    # subdirectory is not optional: a snapshot at the snapshots root is
    # invisible in the list.
    #
    # As default.zss so a fresh Pi boots straight into it. zynthian_gui.py
    # restores last_state.zss first and falls back to default.zss when there is
    # none - which is exactly the fresh-install case. default.zss is otherwise
    # only written by an explicit "save as default", so seeding it destroys
    # nothing, and a Pi that already has a last state keeps its own session.
    #
    # This install is unconditional by design: it overwrites any existing
    # default.zss rather than skipping when the file is present. A fresh flash
    # has no default.zss, so creating it and overwriting it are the same act,
    # and re-running the installer after an upgrade must land the new factory
    # snapshot rather than silently keeping an old one. Verified by dry-run on
    # a rig that already had a last state; the fresh-flash path is identical
    # because the file content is the same either way.
    echo "== Place the factory snapshot (bank 000, and as the default)"
    if [ "$DRY" = 1 ]; then
        echo "  [dry-run] mkdir -p $SNAP_DIR"
        echo "  [dry-run] install -m 0644 $REPO_DIR/snapshot/$SNAP $SNAP_DIR/"
        echo "  [dry-run] install -m 0644 $REPO_DIR/snapshot/$SNAP $SNAP_ROOT/default.zss"
    else
        mkdir -p "$SNAP_DIR"
        install -m 0644 "$REPO_DIR/snapshot/$SNAP" "$SNAP_DIR/"
        install -m 0644 "$REPO_DIR/snapshot/$SNAP" "$SNAP_ROOT/default.zss"
    fi

    # --- 3b. the genre pack ---------------------------------------------------
    # Fifty fixed arrangements, 031-080, beside the factory snapshot in bank
    # 000. NOT copied over default.zss: the factory snapshot is what a fresh
    # Pi should boot into, and these are places to go from there.
    #
    # Copied rather than installed one by one so the count is visible in the
    # output - fifty silent successes look identical to fifty silent failures.
    # A pack that is absent from the checkout is not an error: an older clone
    # predates it, and the instrument is complete without it.
    if [ -d "$PACK_DIR" ]; then
        PACK_N=$(find "$PACK_DIR" -name '*.zss' | wc -l)
        echo "== Place the genre pack ($PACK_N snapshots, bank 000)"
        if [ "$DRY" = 1 ]; then
            echo "  [dry-run] install -m 0644 $PACK_DIR/*.zss $SNAP_DIR/"
        else
            install -m 0644 "$PACK_DIR"/*.zss "$SNAP_DIR/"
            # Counted by name against the pack itself, not by a 03x-08x glob:
            # the reader may have their own snapshots in that number range and
            # a count that includes them reports a success that did not happen.
            PLACED=0
            for f in "$PACK_DIR"/*.zss; do
                [ -f "$SNAP_DIR/$(basename "$f")" ] && PLACED=$((PLACED + 1))
            done
            echo "  placed $PLACED of $PACK_N"
        fi
    else
        echo "== No genre pack in this checkout - skipping (the instrument is complete without it)"
    fi

    # --- 4. restart the UI so it picks the snapshot up ------------------------
    # install.sh already restarted, but that was before default.zss existed.
    echo "== Restart the UI so it comes up in the instrument"
    if [ "$DRY" = 1 ]; then
        echo "  [dry-run] systemctl restart zynthian"
    else
        systemctl restart zynthian
        sleep 20
    fi

    # --- 4. verify -----------------------------------------------------------
    echo "== Verify"
    if [ "$DRY" = 1 ]; then
        echo "  [dry-run] bash tools/check-prereqs.sh"
        echo "  [dry-run] jack_lsp -c | awk '/Pads MIDI/...' (route count)"
    else
        ( cd "$REPO_DIR" && bash tools/check-prereqs.sh ) || true
        # Exactly one ZynMidiRouter:devN_in under the Pads port. Do not look for
        # a "Loaded" line: Zynthian logs it at INFO and ZYNTHIAN_LOG_LEVEL
        # defaults to WARNING, so it is never written on a stock rig.
        #
        # NOT `grep -A3 "Pads MIDI"`. That form reports a HEALTHY rig as a
        # broken one: it matches the Pads port twice - once as a port, once as
        # another port's connection - and then prints unrelated ports that sit
        # at the left margin, so a working rig shows four devN_in lines under a
        # header saying "want exactly one". Indentation is the whole
        # distinction: a route is indented under its port, a port is not.
        # Measured on the rig 2026-08-15.
        echo "-- Pads MIDI routing (want exactly one devN_in):"
        jack_lsp -c | awk '/\(capture\): Pads MIDI/{f=1;next} /^[^ \t]/{f=0} f{print}' || true
        echo "   two or more means a stale route - restart the daemon, then the UI"
    fi

    cat <<'EOF'

== Done. Press Play.
The instrument should already be loaded: eight mixer strips on screen, both MK2
displays drawing their tab rows, the Group buttons lit in channel colours.

If instead you get an empty Zynthian, this Pi had a previous session, which
takes priority over the factory snapshot. Load it by hand from the screen:
  Snapshots > into bank 000 > 017-generative-techno

If something is wrong, section 4 of the guide gives every step its own check:
https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/04-manual-installation.html
EOF
}

main "$@"
