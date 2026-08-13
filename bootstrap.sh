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
SNAP_DIR=/zynthian/zynthian-my-data/snapshots/000
SNAP=017-generative-techno.zss

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
    # The bank subdirectory is not optional: a snapshot at the snapshots root
    # is invisible in the Zynthian UI.
    echo "== Place the factory snapshot in bank 000"
    if [ "$DRY" = 1 ]; then
        echo "  [dry-run] mkdir -p $SNAP_DIR"
        echo "  [dry-run] install -m 0644 $REPO_DIR/snapshot/$SNAP $SNAP_DIR/"
    else
        mkdir -p "$SNAP_DIR"
        install -m 0644 "$REPO_DIR/snapshot/$SNAP" "$SNAP_DIR/"
    fi

    # --- 4. verify -----------------------------------------------------------
    echo "== Verify"
    if [ "$DRY" = 1 ]; then
        echo "  [dry-run] bash tools/check-prereqs.sh"
        echo "  [dry-run] journalctl -u zynthian --since -3min | grep -i ctrldev"
        echo "  [dry-run] jack_lsp -c | grep -A3 'Pads MIDI'"
    else
        ( cd "$REPO_DIR" && bash tools/check-prereqs.sh ) || true
        journalctl -u zynthian --since -3min | grep -i ctrldev || true
        jack_lsp -c | grep -A3 "Pads MIDI" || true
    fi

    cat <<'EOF'

== Two things left, both on the touchscreen
  1. Load the snapshot: Snapshots > into bank 000 > 017-generative-techno
  2. Press Play.

If something is wrong, section 4 of the guide gives every step its own check:
https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/04-manual-installation.html
EOF
}

main "$@"
