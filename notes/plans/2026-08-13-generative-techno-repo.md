# Generative-Techno ZynthianMaschine MKII — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish one self-contained public repository that turns a running Zynthian plus a Maschine MK2 into the Generative-Techno ZynthianMaschine MKII, with a seven-section build guide on GitHub Pages.

**Architecture:** A new git repo at `~/zynth/Generative-Techno-ZynthianMaschine-MKII` carrying four payload trees (`daemon/`, `ctrldev/`, `system/`, `tools/`), one snapshot, and a documentation pair — Markdown in `guide/`, generated HTML in `docs/` served by GitHub Pages. Files are copied in from the existing repos and the Pi; nothing is moved, and no Zynthian core file is shipped as a copy. The single required core change ships as an idempotent patcher.

**Tech Stack:** Python 3 (stdlib only) for the site generator, the patcher and the snapshot tooling · Rust (cargo, edition 2021) for the vendored HID daemon · bash for install and preflight · `gh` CLI for repo and Pages · systemd and udev on the Pi.

**Spec:** `docs/superpowers/specs/2026-08-13-generative-techno-repo-design.md`

## Global Constraints

- Repo slug is `Generative-Techno-ZynthianMaschine-MKII`; the display name "Generative-Techno ZynthianMaschine MKII" appears only in prose. Owner is `Witzman`, repo is public.
- Licence is **GPL-3.0**, forced by `zynthian-ui` (GPL-3.0) and the daemon (fork of `wrl/maschine.rs`, GPL-3.0). Upstream notices stay intact; credits name both.
- Pinned target: **ZynthianOS `Oram-2601-1`**, image `2026-01-27-zynthianos-oram-2601-stable.img.xz` (currently also `zynthianos-last-stable.img.xz`), `zynthian-ui` branch `oram-2601.1`. Vangelis 2606/2607 are betas and out of scope.
- The Pi is `ssh root@192.168.2.123`. mDNS `.local` does not resolve from WSL — always the IP.
- **Never run git on the Pi** in `/zynthian/zynthian-ui` or `/root/zynth/MaschineMK2_linux`. The live code there is untracked drop-ins and uncommitted worktree changes; git destroys it. Deploy and read by file copy.
- Service restart order is **daemon first, UI second**. Restarting `maschine-mk2` alone makes `a2j` re-register the port on a new zmip slot while the driver stays bound to the dead one — silent failure.
- Any edit to `guide/*.md` requires re-running the generator and committing `docs/` in the same commit. The generator rewrites every page's sidebar, so a partial commit leaves stale navigation everywhere.
- Third-party plugin binaries and samples are **never vendored**: `obxd-lv2`, `padthv1-lv2`, `tap-lv2` come from Debian, JC303 from Zynthian's plugin set, the 42 SFZ drum machines from the OS image. The preflight checks for them.
- The unit tests must stay at **271 passing**. Command: `cd ctrldev && python3 -m unittest discover -s tests -q`.
- The rig is the owner's working instrument. Nothing in this plan restarts Zynthian, loads a snapshot, or writes to `/zynthian/zynthian-my-data` except where a step says so explicitly.

---

## File Structure

| Path | Responsibility |
|---|---|
| `README.md` | One screen: what it is, contents, credits, licence. Links into `guide/01`, never a second copy of that prose |
| `LICENSE` | GPL-3.0 text |
| `.gitignore` | `target/`, `__pycache__/`, `*.pyc`, `*.zss.bak` |
| `guide/01-what-it-is.md` … `07-playing.md` | The seven sections; Markdown is the edit target |
| `guide/a1-how-017-was-built.md` | Appendix: chain table, insert order, dry/wet values, CC sequence |
| `guide/a2-touchscreen-patch.md` | Appendix: optional `multitouch.py` coordinate fix |
| `docs/` | Generated HTML + CSS/JS/search index. GitHub Pages serves main `/docs` |
| `tools/generate-html.py` | Site generator, ported from zynth-docs, sidebar trimmed to nine pages |
| `daemon/` | Vendored Rust HID daemon: `src/`, `alsa-seq/`, `web/`, `Cargo.toml`, `Cargo.lock`, `build.sh`, `run.sh`, `picturetest.png`, `LICENSE`, `CREDITS.md` |
| `ctrldev/` | `zynthian_ctrldev_maschine_mk2.py`, `techno_lib.py`, `maschine_mk2_lib.py` |
| `ctrldev/tests/` | `test_techno_lib.py`, `test_maschine_mk2_lib.py` — **must sit one level below the modules**, because both files do `sys.path.insert(0, dirname(__file__) + "/..")` |
| `system/` | `99-maschine.rules`, `maschine-mk2.service`, `maschine-web.service`, `maschine-clock.service`, `maschine-jack-connect.sh`, `maschine-clock-bridge.py`, `maschine-clock-connect.sh`, `maschine.json` |
| `tools/patch-autoconnect-maschine.py` | Idempotent patcher for the reader's `zynthian_autoconnect.py` |
| `tools/build-techno-snapshot.py` | Clones one channel's insert pair onto the other seven, offline on the `.zss` |
| `tools/check-prereqs.sh` | Preflight: one line per dependency, non-zero exit on any miss |
| `tools/sync-from-dev.sh` | Copies ctrldev + tests from `~/zynth/zynthian-ui`; `git diff` afterwards is the drift report |
| `install.sh` | Optional wrapper over section 3, with `--dry-run` |
| `snapshot/017-generative-techno.zss` | The factory snapshot |

**Deviation from the spec, deliberate:** the spec's layout put tests at `tests/`. They go to `ctrldev/tests/` instead, because the existing test files locate their modules one directory up. Moving them to the root would require editing the tests, which are the only automated proof this project has.

---

# Phase P1 — the repo exists and installs

### Task 1: Repo skeleton, licence, first push

**Files:**
- Create: `~/zynth/Generative-Techno-ZynthianMaschine-MKII/LICENSE`
- Create: `~/zynth/Generative-Techno-ZynthianMaschine-MKII/README.md`
- Create: `~/zynth/Generative-Techno-ZynthianMaschine-MKII/.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: `$REPO` = `/home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII`, a git repo on branch `main` with remote `origin` at `git@github.com:Witzman/Generative-Techno-ZynthianMaschine-MKII.git`. Every later task commits into it.

- [ ] **Step 1: Create the directory and initialise git**

```bash
mkdir -p /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git init -b main
```

- [ ] **Step 2: Copy in the GPL-3.0 licence text**

```bash
cp /home/witzman/zynth/zynthian-ui/LICENSE.txt \
   /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/LICENSE
head -3 /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/LICENSE
```

Expected: `GNU GENERAL PUBLIC LICENSE` / `Version 3, 29 June 2007`.

- [ ] **Step 3: Write `.gitignore`**

```
target/
__pycache__/
*.pyc
*.zss.bak
```

- [ ] **Step 4: Write the README stub**

Content — exactly this shape, prose filled in Task 8:

```markdown
# Generative-Techno ZynthianMaschine MKII

An eight-channel generative groovebox: five euclidean drum channels and three
Turing-machine voices, running on Zynthian on a Raspberry Pi 4, played entirely
from a Native Instruments Maschine MK2.

**Build guide:** [`guide/01-what-it-is.md`](guide/01-what-it-is.md) · rendered at
the project's GitHub Pages site.

**Status:** verified on ZynthianOS `Oram-2601-1`.

## Credits

- [Zynthian](https://zynthian.org) — the synth platform this extends. GPL-3.0.
- [wrl/maschine.rs](https://github.com/wrl/maschine.rs) — the original Maschine
  HID daemon, by William Light. The daemon in `daemon/` descends from it via
  [Witzman/MaschineMK2_linux](https://github.com/Witzman/MaschineMK2_linux).

## Licence

GPL-3.0. See `LICENSE`.
```

- [ ] **Step 5: Commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add LICENSE README.md .gitignore
git commit -m "chore: repo skeleton, GPL-3.0, credits

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Create the GitHub repo and push**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
gh repo create Generative-Techno-ZynthianMaschine-MKII \
  --public --source=. --push \
  --description "Eight-channel generative groovebox: Zynthian on a Raspberry Pi 4, played from a Maschine MK2"
```

- [ ] **Step 7: Verify the repo is public and on GitHub**

```bash
gh repo view Witzman/Generative-Techno-ZynthianMaschine-MKII --json name,visibility,defaultBranchRef
```

Expected: `"name":"Generative-Techno-ZynthianMaschine-MKII"`, `"visibility":"PUBLIC"`, default branch `main`.

---

### Task 2: Vendor the Rust daemon

**Files:**
- Create: `$REPO/daemon/` — copied tree
- Create: `$REPO/daemon/CREDITS.md`

**Interfaces:**
- Consumes: Task 1's repo.
- Produces: `daemon/Cargo.toml` buildable with `cargo build --release` on the Pi, producing `daemon/target/release/maschine`. `install.sh` (Task 6) and `guide/03` (Task 10) both reference that exact path.

- [ ] **Step 1: Copy the daemon tree, excluding build output**

```bash
SRC=/home/witzman/zynth/MaschineMK2_linux
DST=/home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/daemon
mkdir -p "$DST"
rsync -a --exclude target --exclude .git \
  "$SRC/src" "$SRC/alsa-seq" "$SRC/web" "$SRC/doc" \
  "$SRC/Cargo.toml" "$SRC/Cargo.lock" "$SRC/build.sh" "$SRC/run.sh" \
  "$SRC/insert_colors.sh" "$SRC/picturetest.png" "$SRC/LICENSE" "$DST/"
cp "$SRC/README.md" "$DST/README.upstream.md"
```

`alsa-seq/` is not optional: `Cargo.toml` declares it as `[dependencies.alsa-seq] path = "alsa-seq"`, so without it the build cannot resolve.

- [ ] **Step 2: Verify the copy is complete and identical**

```bash
diff -r --exclude target --exclude .git --exclude README.md \
  /home/witzman/zynth/MaschineMK2_linux \
  /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/daemon \
  | grep -v "^Only in /home/witzman/zynth/Generative" || echo "IDENTICAL"
```

Expected: `IDENTICAL`, or `Only in` lines naming just `maschine.json` (which goes to `system/` in Task 4) and `README.upstream.md`.

- [ ] **Step 3: Verify the manifest parses**

```bash
cargo metadata --no-deps --format-version 1 \
  --manifest-path /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/daemon/Cargo.toml \
  >/dev/null && echo "MANIFEST OK"
```

Expected: `MANIFEST OK`. Do **not** attempt a full `cargo build` on WSL — the crate needs ALSA and hidraw headers, and the Pi is where it is built and already known to build.

- [ ] **Step 4: Write `daemon/CREDITS.md`**

```markdown
# Lineage

    wrl/maschine.rs  (William Light, GPL-3.0)
        └── Witzman/MaschineMK2_linux  (fork: MK2 support, display, OSC, web editor)
                └── this repository  (development home as of 2026-08-13)

The upstream `LICENSE` and source notices are preserved unchanged. Changes made
in this lineage: MK2 HID report maps, the 255x64 display protocol, the OSC
drawing API, the hidraw close-then-reopen watchdog, the WebSocket LED editor,
and the `external_pad_leds` config flag.
```

- [ ] **Step 5: Commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add daemon
git commit -m "feat: vendor the Maschine MK2 HID daemon

This repo becomes the daemon's development home. alsa-seq is vendored too
because Cargo.toml declares it as a local path dependency.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Copy the ctrldev driver and its tests

**Files:**
- Create: `$REPO/ctrldev/zynthian_ctrldev_maschine_mk2.py`, `techno_lib.py`, `maschine_mk2_lib.py`
- Create: `$REPO/ctrldev/tests/test_techno_lib.py`, `test_maschine_mk2_lib.py`

**Interfaces:**
- Consumes: Task 1's repo.
- Produces: the three files that `install.sh` copies to `/zynthian/zynthian-ui/zyngine/ctrldev/`, and a test suite runnable as `cd ctrldev && python3 -m unittest discover -s tests -q`.

- [ ] **Step 1: Copy the five files, preserving the relative layout**

```bash
SRC=/home/witzman/zynth/zynthian-ui/zyngine/ctrldev
DST=/home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/ctrldev
mkdir -p "$DST/tests"
cp "$SRC/zynthian_ctrldev_maschine_mk2.py" "$SRC/techno_lib.py" "$SRC/maschine_mk2_lib.py" "$DST/"
cp "$SRC/tests/test_techno_lib.py" "$SRC/tests/test_maschine_mk2_lib.py" "$DST/tests/"
```

The layout matters: both test files run `sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))`, so the modules must sit exactly one directory above `tests/`.

- [ ] **Step 2: Run the suite in the new repo**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/ctrldev
python3 -m unittest discover -s tests -q 2>&1 | tail -4
```

Expected: `Ran 271 tests`, `OK`.

- [ ] **Step 3: Confirm `dev_ids` is present on every module**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/ctrldev
grep -l "dev_ids" *.py
```

Expected: all three files listed. Zynthian's driver manager globs every `*.py` in `zyngine/ctrldev/` and reads `dev_ids` off each one; a helper module without it crash-loops the whole UI every 14 seconds.

- [ ] **Step 4: Commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add ctrldev
git commit -m "feat: the ctrldev driver and its 271 unit tests

Tests sit at ctrldev/tests/ because both files locate their modules one
directory up. techno_lib.py has no Zynthian imports, so the suite runs on any
machine with no Pi and no hardware.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Collect the system files from the Pi

**Files:**
- Create: `$REPO/system/99-maschine.rules`, `maschine-mk2.service`, `maschine-web.service`, `maschine-clock.service`, `maschine-jack-connect.sh`, `maschine-clock-bridge.py`, `maschine-clock-connect.sh`, `maschine.json`

**Interfaces:**
- Consumes: Task 1's repo.
- Produces: the files `install.sh` (Task 6) installs to `/etc/udev/rules.d/`, `/etc/systemd/system/`, `/usr/local/bin/` and the daemon's working directory.

- [ ] **Step 1: Copy the eight files off the Pi**

```bash
DST=/home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/system
mkdir -p "$DST"
scp root@192.168.2.123:/etc/udev/rules.d/99-maschine.rules "$DST/"
scp root@192.168.2.123:/etc/systemd/system/maschine-mk2.service "$DST/"
scp root@192.168.2.123:/etc/systemd/system/maschine-web.service "$DST/"
scp root@192.168.2.123:/etc/systemd/system/maschine-clock.service "$DST/"
scp root@192.168.2.123:/usr/local/bin/maschine-jack-connect.sh "$DST/"
scp root@192.168.2.123:/usr/local/bin/maschine-clock-bridge.py "$DST/"
scp root@192.168.2.123:/usr/local/bin/maschine-clock-connect.sh "$DST/"
scp root@192.168.2.123:/root/zynth/MaschineMK2_linux/maschine.json "$DST/"
```

- [ ] **Step 2: Verify each file matches the Pi byte for byte**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/system
for f in 99-maschine.rules maschine-mk2.service maschine-web.service \
         maschine-clock.service maschine-jack-connect.sh \
         maschine-clock-bridge.py maschine-clock-connect.sh maschine.json; do
  printf "%-28s %s\n" "$f" "$(md5sum "$f" | cut -c1-32)"
done
ssh root@192.168.2.123 'md5sum /etc/udev/rules.d/99-maschine.rules \
  /etc/systemd/system/maschine-mk2.service /etc/systemd/system/maschine-web.service \
  /etc/systemd/system/maschine-clock.service /usr/local/bin/maschine-jack-connect.sh \
  /usr/local/bin/maschine-clock-bridge.py /usr/local/bin/maschine-clock-connect.sh \
  /root/zynth/MaschineMK2_linux/maschine.json'
```

Expected: the eight checksums match pairwise.

- [ ] **Step 3: Confirm `maschine.json` carries the pad-LED flag**

```bash
grep external_pad_leds \
  /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/system/maschine.json
```

Expected: `"external_pad_leds": true`. Without it the daemon repaints pads itself and the first touch destroys the per-channel colours.

- [ ] **Step 4: Rewrite the two absolute paths in `maschine-mk2.service`**

The Pi's unit hard-codes `/root/zynth/MaschineMK2_linux`. The repo's copy must reference the install location the guide uses. Replace both lines:

```
ExecStart=/root/Generative-Techno-ZynthianMaschine-MKII/daemon/target/release/maschine /dev/maschine any
WorkingDirectory=/root/Generative-Techno-ZynthianMaschine-MKII/daemon
```

Leave `ExecStartPost`, `After`, `Requires`, `Restart` and `RestartSec` untouched.

- [ ] **Step 5: Verify the unit still parses**

```bash
systemd-analyze verify \
  /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/system/maschine-mk2.service 2>&1 | head -5
```

Expected: no output, or only warnings about units not installed on this machine (`jack2.service`, `a2jmidid.service`). Errors about syntax are failures.

- [ ] **Step 6: Commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add system
git commit -m "feat: udev rule, systemd units, JACK connect and clock bridge

Taken off the running Pi and verified by checksum. maschine-mk2.service now
points at the repo's own daemon path instead of /root/zynth. maschine.json
keeps external_pad_leds true, without which the first pad touch destroys the
per-channel LED colours.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Tools — the patcher, the snapshot builder, and the preflight

**Files:**
- Create: `$REPO/tools/patch-autoconnect-maschine.py` (copy)
- Create: `$REPO/tools/build-techno-snapshot.py` (copy)
- Create: `$REPO/tools/check-prereqs.sh` (new)
- Create: `$REPO/tools/sync-from-dev.sh` (new)

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: `tools/check-prereqs.sh`, called by `guide/04` and `guide/06` and by `install.sh --dry-run`; exit code 0 means every dependency is present. `tools/sync-from-dev.sh` re-copies the five ctrldev files from `~/zynth/zynthian-ui`.

- [ ] **Step 1: Copy the two existing tools**

```bash
DST=/home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/tools
mkdir -p "$DST"
cp /home/witzman/zynth-docs/tools/patch-autoconnect-maschine.py "$DST/"
cp /home/witzman/zynth-docs/tools/build-techno-snapshot.py "$DST/"
```

- [ ] **Step 2: Point the snapshot builder at the factory snapshot**

`build-techno-snapshot.py` line 24 hard-codes `016-techno_maschine.zss`. Change it so the target is an argument with the factory snapshot as default:

```python
SNAP = sys.argv[1] if len(sys.argv) > 1 else \
    "/zynthian/zynthian-my-data/snapshots/000/017-generative-techno.zss"
```

Also update its module docstring's example invocation to the same filename.

- [ ] **Step 3: Write `tools/check-prereqs.sh`**

```bash
#!/usr/bin/env bash
# Preflight for the Generative-Techno ZynthianMaschine MKII.
# Run ON THE PI. Prints one line per dependency; exits non-zero on any miss.
set -u

miss=0
ok()   { printf "  PRESENT  %s\n" "$1"; }
bad()  { printf "  MISSING  %s\n" "$1"; miss=$((miss+1)); }

echo "ZynthianOS"
if [ -f /zynthian/build_info.txt ]; then
    ok "$(head -1 /zynthian/build_info.txt)"
else
    bad "/zynthian/build_info.txt - is this a ZynthianOS install?"
fi

echo "LV2 plugins"
for pkg in obxd-lv2 padthv1-lv2 tap-lv2; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then ok "$pkg"; else bad "$pkg (apt install $pkg)"; fi
done
for b in /usr/lib/lv2/Obxd.lv2 /usr/lib/lv2/padthv1.lv2 \
         /usr/lib/lv2/tap-reverb.lv2 /usr/lib/lv2/tap-echo.lv2 \
         /zynthian/zynthian-plugins/lv2/JC303.lv2; do
    if [ -d "$b" ]; then ok "$b"; else bad "$b"; fi
done

echo "Drum kits"
KITS="/zynthian/zynthian-data/soundfonts/sfz/Drum Machines"
if [ -d "$KITS" ]; then
    n=$(ls "$KITS"/*.sfz 2>/dev/null | wc -l)
    if [ "$n" -gt 0 ]; then ok "$n SFZ kits in $KITS"; else bad "no .sfz files in $KITS"; fi
else
    bad "$KITS"
fi

echo "Driver"
for f in zynthian_ctrldev_maschine_mk2.py techno_lib.py maschine_mk2_lib.py; do
    if [ -f "/zynthian/zynthian-ui/zyngine/ctrldev/$f" ]; then ok "$f"; else bad "$f"; fi
done
if grep -q "maschine rs.*Pads MIDI" /zynthian/zynthian-ui/zynautoconnect/zynthian_autoconnect.py 2>/dev/null
then ok "zynautoconnect patched"
else bad "zynautoconnect NOT patched (run tools/patch-autoconnect-maschine.py)"
fi

echo "Services"
for u in maschine-mk2 maschine-web maschine-clock; do
    if systemctl is-active --quiet "$u"; then ok "$u active"; else bad "$u not active"; fi
done
if [ -e /dev/maschine ]; then ok "/dev/maschine"; else bad "/dev/maschine (udev rule, or the MK2 is unplugged)"; fi

echo "JACK routing"
pads=$(jack_lsp 2>/dev/null | grep -c "Pads MIDI")
if [ "$pads" -gt 0 ]; then ok "daemon MIDI port visible in JACK"; else bad "no 'Pads MIDI' port in JACK"; fi
taps=$(jack_lsp 2>/dev/null | grep -c TAP)
if [ "$taps" -eq 64 ]; then ok "64 TAP ports (16 inserts)"; else bad "$taps TAP ports, expected 64 - is the snapshot loaded?"; fi

echo "Snapshot"
SNAP=/zynthian/zynthian-my-data/snapshots/000/017-generative-techno.zss
if [ -f "$SNAP" ]; then ok "$SNAP"; else bad "$SNAP (section 5 copies it)"; fi

echo
if [ "$miss" -eq 0 ]; then echo "All dependencies present."; else echo "$miss missing."; fi
exit "$miss"
```

- [ ] **Step 4: Write `tools/sync-from-dev.sh`**

```bash
#!/usr/bin/env bash
# Re-copy the ctrldev driver and its tests from the development checkout.
# Development happens in ~/zynth/zynthian-ui on branch vangelis; this repo is a
# release target. Run this, then `git diff` - that diff IS the drift report.
set -eu

SRC="${1:-/home/witzman/zynth/zynthian-ui/zyngine/ctrldev}"
DST="$(cd "$(dirname "$0")/.." && pwd)/ctrldev"

[ -d "$SRC" ] || { echo "no such source: $SRC" >&2; exit 1; }

for f in zynthian_ctrldev_maschine_mk2.py techno_lib.py maschine_mk2_lib.py; do
    cp "$SRC/$f" "$DST/$f"
    echo "synced $f"
done
for f in test_techno_lib.py test_maschine_mk2_lib.py; do
    cp "$SRC/tests/$f" "$DST/tests/$f"
    echo "synced tests/$f"
done

echo
echo "Now run the suite and read the diff:"
echo "  (cd '$DST' && python3 -m unittest discover -s tests -q)"
echo "  git -C '$(dirname "$DST")' diff --stat ctrldev"
```

- [ ] **Step 5: Make both scripts executable and prove the sync is a no-op**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
chmod +x tools/check-prereqs.sh tools/sync-from-dev.sh
bash tools/sync-from-dev.sh
git status --porcelain ctrldev
```

Expected: the sync prints five `synced` lines and `git status --porcelain ctrldev` prints **nothing** — the repo already matches the development checkout, so the drift report is empty.

- [ ] **Step 6: Run the preflight on the Pi**

```bash
scp /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/tools/check-prereqs.sh \
    root@192.168.2.123:/tmp/
ssh root@192.168.2.123 'bash /tmp/check-prereqs.sh; echo "exit=$?"'
```

Expected: `PRESENT` for ZynthianOS, all three apt packages, the five plugin bundles, the SFZ kits, the three driver files, the patched autoconnect, the three services, `/dev/maschine`, the JACK port and 64 TAP ports. **`017-generative-techno.zss` will report MISSING** until Task 16 — that is correct, and `exit=1` here is the expected result today. Every other line must be PRESENT; anything else is a real finding, so stop and report it.

- [ ] **Step 7: Commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add tools
git commit -m "feat: preflight, dev sync, autoconnect patcher, snapshot builder

check-prereqs.sh turns a failed snapshot import into a dependency list rather
than a mystery. sync-from-dev.sh keeps zynthian-ui as the development home and
makes drift visible as a git diff.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: `install.sh`

**Files:**
- Create: `$REPO/install.sh`

**Interfaces:**
- Consumes: `daemon/`, `ctrldev/`, `system/`, `tools/` from Tasks 2-5.
- Produces: `./install.sh [--dry-run]`. `guide/03` (Task 10) references it by that exact invocation.

- [ ] **Step 1: Write `install.sh`**

```bash
#!/usr/bin/env bash
# Generative-Techno ZynthianMaschine MKII - installer.
# Runs exactly what guide/03-install-driver.md documents, in the same order.
# The guide is authoritative; this is a wrapper. --dry-run prints and changes
# nothing.
set -eu

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

REPO="$(cd "$(dirname "$0")" && pwd)"
CTRLDEV=/zynthian/zynthian-ui/zyngine/ctrldev
AUTOCONNECT=/zynthian/zynthian-ui/zynautoconnect/zynthian_autoconnect.py

say() { printf "\n== %s\n" "$1"; }
run() {
    if [ "$DRY" = 1 ]; then printf "  [dry-run] %s\n" "$*"; else printf "  %s\n" "$*"; eval "$@"; fi
}
backup() {
    [ -f "$1" ] || return 0
    [ -f "$1.bak" ] && return 0
    run "cp '$1' '$1.bak'"
}

# --- refuse to run anywhere but a ZynthianOS Pi --------------------------------
if [ ! -f /zynthian/build_info.txt ]; then
    echo "This is not a ZynthianOS install (/zynthian/build_info.txt missing)." >&2
    echo "Run this on the Pi, not on your laptop." >&2
    exit 1
fi
echo "ZynthianOS: $(head -1 /zynthian/build_info.txt)"
[ "$DRY" = 1 ] && echo "DRY RUN - nothing will be changed."

# --- 1. packaged LV2 plugins ---------------------------------------------------
say "LV2 plugins from Debian"
for pkg in obxd-lv2 padthv1-lv2 tap-lv2; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then
        echo "  already installed: $pkg"
    else
        run "apt-get install -y $pkg"
    fi
done

# --- 2. build the daemon -------------------------------------------------------
say "Build the HID daemon (minutes - do not interrupt)"
if [ -x "$REPO/daemon/target/release/maschine" ]; then
    echo "  already built: daemon/target/release/maschine"
else
    run "cd '$REPO/daemon' && cargo build --release"
    run "cp '$REPO/daemon/picturetest.png' '$REPO/daemon/target/release/'"
fi

# --- 3. daemon config ----------------------------------------------------------
say "Daemon config (external_pad_leds must be true)"
if [ -f "$REPO/daemon/maschine.json" ]; then
    echo "  already present: daemon/maschine.json"
else
    run "cp '$REPO/system/maschine.json' '$REPO/daemon/maschine.json'"
fi

# --- 4. udev ------------------------------------------------------------------
say "udev rule: /dev/maschine plus hotplug restart"
run "install -m 0644 '$REPO/system/99-maschine.rules' /etc/udev/rules.d/99-maschine.rules"
run "udevadm control --reload-rules"
run "udevadm trigger --subsystem-match=hidraw"

# --- 5. helper scripts ---------------------------------------------------------
say "Helper scripts in /usr/local/bin"
for f in maschine-jack-connect.sh maschine-clock-bridge.py maschine-clock-connect.sh; do
    run "install -m 0755 '$REPO/system/$f' /usr/local/bin/$f"
done

# --- 6. systemd units ---------------------------------------------------------
say "systemd units"
for f in maschine-mk2.service maschine-web.service maschine-clock.service; do
    run "install -m 0644 '$REPO/system/$f' /etc/systemd/system/$f"
done
run "systemctl daemon-reload"
run "systemctl enable maschine-mk2 maschine-web maschine-clock"

# --- 7. the ctrldev driver ----------------------------------------------------
say "ctrldev driver files"
for f in zynthian_ctrldev_maschine_mk2.py techno_lib.py maschine_mk2_lib.py; do
    backup "$CTRLDEV/$f"
    run "install -m 0644 '$REPO/ctrldev/$f' '$CTRLDEV/$f'"
done

# --- 8. the one core patch ----------------------------------------------------
say "Patch zynautoconnect (idempotent)"
backup "$AUTOCONNECT"
run "python3 '$REPO/tools/patch-autoconnect-maschine.py' '$AUTOCONNECT'"

# --- 9. restart, daemon FIRST -------------------------------------------------
say "Restart: daemon first, UI second"
echo "  Order matters. Restarting the daemon alone makes a2j re-register its"
echo "  port on a new zmip slot while the driver stays bound to the dead one,"
echo "  and the rig goes silent with no error."
run "systemctl restart maschine-mk2"
run "sleep 8"
run "systemctl restart zynthian"

# --- 10. hand back to the guide ----------------------------------------------
say "Verify (this script does not verify anything itself)"
cat <<'EOF'
  bash tools/check-prereqs.sh
  journalctl -u zynthian --since -3min | grep -i ctrldev     # want "Loaded", not just "Found"
  jack_lsp -c | grep -A3 "Pads MIDI"                          # exactly one devN_in
EOF
```

- [ ] **Step 2: Make it executable and check the syntax**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
chmod +x install.sh
bash -n install.sh && echo "SYNTAX OK"
```

Expected: `SYNTAX OK`.

- [ ] **Step 3: Verify it refuses to run off-Pi**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
./install.sh; echo "exit=$?"
```

Expected: `This is not a ZynthianOS install`, `exit=1`. The WSL box has no `/zynthian/build_info.txt`.

- [ ] **Step 4: Dry-run it on the Pi**

```bash
ssh root@192.168.2.123 'rm -rf /tmp/gtzm && mkdir -p /tmp/gtzm'
rsync -a --exclude .git --exclude docs \
  /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/ \
  root@192.168.2.123:/tmp/gtzm/
ssh root@192.168.2.123 'cd /tmp/gtzm && ./install.sh --dry-run'
```

Expected: prints the ZynthianOS line, `DRY RUN - nothing will be changed`, `already installed` for the three packages, and `[dry-run]` lines for every install/patch/restart action. **Nothing on the rig changes.** Confirm afterwards that the services were untouched:

```bash
ssh root@192.168.2.123 'systemctl is-active maschine-mk2 zynthian'
```

Expected: `active` twice.

- [ ] **Step 5: Commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add install.sh
git commit -m "feat: optional installer with --dry-run

Refuses to run anywhere but ZynthianOS, backs up every file it overwrites,
enforces the daemon-then-UI restart order, and verifies nothing itself - it
prints the verification commands and hands back to the guide.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Push phase P1**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git push -u origin main
```

---

# Phase P2 — the guide and GitHub Pages

### Task 7: Port the site generator

**Files:**
- Create: `$REPO/tools/generate-html.py` (ported from `~/zynth-docs/htmldoku/generate-html.py`, 1273 lines)
- Create: `$REPO/guide/01-what-it-is.md` (one-line placeholder, replaced in Task 8)

**Interfaces:**
- Consumes: Task 1's repo.
- Produces: `python3 tools/generate-html.py` reads `guide/*.md` and writes `docs/*.html` plus `style.css`, `search.js`, `ui.js`, `search-index.json`, and copies `readme.html`→`index.html`. Tasks 8-14 each end by running it.

- [ ] **Step 1: Copy the generator**

```bash
cp /home/witzman/zynth-docs/htmldoku/generate-html.py \
   /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/tools/generate-html.py
```

- [ ] **Step 2: Repoint the source and output directories**

In the Configuration block near the top, replace:

```python
REPO_ROOT = Path(__file__).parent.parent
SRC_DIR   = Path(__file__).parent
OUT_DIR   = REPO_ROOT / "docs" / "zynthian-Doku"
```

with:

```python
REPO_ROOT = Path(__file__).parent.parent
SRC_DIR   = REPO_ROOT / "guide"
OUT_DIR   = REPO_ROOT / "docs"
```

- [ ] **Step 3: Replace the sidebar with this project's nine pages**

Replace the whole `SIDEBAR = [...]` list with:

```python
SIDEBAR = [
    ("Build", [
        ("1 · What It Is",          "01-what-it-is.html"),
        ("2 · Install ZynthianOS",  "02-install-zynthianos.html"),
        ("3 · Driver & Daemon",     "03-install-driver.html"),
        ("4 · Prepare Zynthian",    "04-prepare-zynthian.html"),
        ("5 · Import Snapshot",     "05-import-snapshot.html"),
        ("6 · Testing",             "06-testing.html"),
        ("7 · Playing",             "07-playing.html"),
    ]),
    ("Appendices", [
        ("How 017 Was Built",       "a1-how-017-was-built.html"),
        ("Touchscreen Patch",       "a2-touchscreen-patch.html"),
    ]),
]
```

- [ ] **Step 4: Neutralise the sprint-board generator**

`build_status_html()` reads `MD/inwork.md`, `todo.md` and `done.md`, which exist only in zynth-docs. In `main()`, replace the bare call `build_status_html()` with:

```python
    if (REPO_ROOT / "MD").is_dir():
        build_status_html()
```

Leave the function itself in place — deleting it means also unpicking `_parse_md_items` and the status CSS, which is churn for no gain.

- [ ] **Step 5: Point `index.html` at section 1**

`main()` copies `readme.html` to `index.html`. There is no `readme.md` in `guide/`, so change that block to use section 1:

```python
    landing = OUT_DIR / "01-what-it-is.html"
    if landing.exists():
        shutil.copy(landing, OUT_DIR / "index.html")
        print("  01-what-it-is.html → index.html (copy)")
```

- [ ] **Step 6: Create a placeholder page and run the generator**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
mkdir -p guide
printf '# What It Is\n\nPlaceholder.\n' > guide/01-what-it-is.md
python3 tools/generate-html.py
ls docs/
```

Expected: `01-what-it-is.html`, `index.html`, `style.css`, `search.js`, `ui.js`, `search-index.json`. No traceback, and no `status.html`.

- [ ] **Step 7: Verify the sidebar rendered**

```bash
grep -c "02-install-zynthianos.html" \
  /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/docs/01-what-it-is.html
```

Expected: at least `1` — the sidebar is written into every page, including pages whose targets do not exist yet.

- [ ] **Step 8: Commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add tools/generate-html.py guide docs
git commit -m "build: port the site generator, guide/ to docs/

Sidebar trimmed to this project's seven sections and two appendices. The
sprint-board generator is guarded on an MD/ directory that only zynth-docs
has, and index.html now mirrors section 1.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Section 1 and the README

**Files:**
- Modify: `$REPO/guide/01-what-it-is.md`
- Modify: `$REPO/README.md`

**Interfaces:**
- Consumes: Task 7's generator.
- Produces: the guide's landing page and the repo's front door. Later sections link back to it as `01-what-it-is.md`.

- [ ] **Step 1: Write `guide/01-what-it-is.md`**

Required content, all values exact:

- The instrument in three sentences: eight always-alive channels; three pages of meaning for eight encoders; the generator owns the pattern.
- The channel table: A KICK / B SNAR / C CLAP / D CHAT / E OHAT are drums on LinuxSampler SFZ kits, MIDI 1-5, warm colours; F BASS is JC303, G LEAD is Obxd, H PADS is padthv1, MIDI 6-8, cool colours.
- A text signal diagram: `LinuxSampler / synth → zynmixer strip (fader, pan, mute) → TAP Stereo Echo → TAP Reverberator → main`. State that this order is measured on the wire, and that the inserts are **post-fader**, so muting a channel kills its FX tail.
- What it is not: not a DAW, not a Zynthian fork, no song mode, no pattern chaining, no shared FX bus (Zynthian's mixer has sixteen usable strips compiled in; a send-tap topology would need twenty-six).
- Hardware bill: Raspberry Pi 4, Maschine MK2, a USB audio interface, an SD card of 16 GB or more, a display for Zynthian's own UI.
- Scope statement: verified on ZynthianOS `Oram-2601-1` with `zynthian-ui` on branch `oram-2601.1`, on one rig; sections 2-5 have not been walked from a fresh flash.
- Links: section 2 as the next step, and the appendix for how the snapshot was built.

- [ ] **Step 2: Fill in the README's opening**

Keep the README to one screen. It states what the instrument is in two sentences, links to `guide/01-what-it-is.md` and the Pages URL, lists the repo's directories in a five-row table (`daemon/`, `ctrldev/`, `system/`, `tools/`, `snapshot/`), and keeps the Credits and Licence sections from Task 1 unchanged. It must not repeat section 1's prose.

- [ ] **Step 3: Regenerate and check both**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
python3 tools/generate-html.py >/dev/null
grep -c "TAP Stereo Echo" docs/01-what-it-is.html
grep -c "Oram-2601-1" docs/01-what-it-is.html
```

Expected: both counts at least `1`.

- [ ] **Step 4: Commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add README.md guide/01-what-it-is.md docs
git commit -m "docs: section 1 - what the instrument is

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Section 2 — install ZynthianOS

**Files:**
- Create: `$REPO/guide/02-install-zynthianos.md`

**Interfaces:**
- Consumes: Task 7's generator.
- Produces: the pinned-version contract every later section depends on.

- [ ] **Step 1: Write the page**

Required content, all values exact:

- Download `https://os.zynthian.org/zynthianos-last-stable.img.xz`, or the dated equivalent `2026-01-27-zynthianos-oram-2601-stable.img.xz`, and verify the matching `.md5`. State that as of 2026-08-13 those are the same 7.5 GB build.
- Flashing and first boot link to zynthian.org's own documentation rather than being re-copied, with one sentence saying why: upstream docs are maintained, a copy here would rot.
- Enable SSH and reach webconf at `http://zynthian.local`, noting that mDNS may not resolve from WSL, in which case use the IP.
- A confirmation table with four rows: `cat /zynthian/build_info.txt` contains `Oram-2601-1`; `git -C /zynthian/zynthian-ui branch --show-current` prints `oram-2601.1`; `ssh root@<pi>` answers; webconf loads.
- A note that newer images exist — `2026-07-30-zynthianos-vangelis-2607-beta.img.xz` and `2026-06-18-zynthianos-vangelis-2606-test.img.xz` — that they are **beta**, and that this guide is not tested on them.
- The D12 honesty note: this section was written from a running rig, not from a fresh flash.

- [ ] **Step 2: Regenerate and verify**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
python3 tools/generate-html.py >/dev/null
grep -c "zynthianos-last-stable" docs/02-install-zynthianos.html
grep -c "oram-2601.1" docs/02-install-zynthianos.html
```

Expected: both at least `1`.

- [ ] **Step 3: Commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add guide/02-install-zynthianos.md docs
git commit -m "docs: section 2 - install ZynthianOS, pinned to Oram 2601 stable

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Section 3 — driver and daemon

**Files:**
- Create: `$REPO/guide/03-install-driver.md`

**Interfaces:**
- Consumes: Tasks 2-6. References `install.sh`, `system/`, `ctrldev/`, `tools/patch-autoconnect-maschine.py` by exact path.
- Produces: the installed rig the later sections assume.

- [ ] **Step 1: Write the page as an ordered step list**

Required steps, in this order, each with the command and the consequence of skipping it:

1. `apt install rustc cargo` (or rustup), then `cd daemon && cargo build --release` and `cp picturetest.png target/release/`. Warn it takes minutes on a Pi 4 and must not be interrupted.
2. `cp system/maschine.json daemon/maschine.json`. **`"external_pad_leds": true`** — without it the daemon repaints pads on press and the first touch destroys the per-channel colours. Note it is not in git upstream, so a `git reset --hard` in a daemon checkout wipes it.
3. `install -m 0644 system/99-maschine.rules /etc/udev/rules.d/`, then `udevadm control --reload-rules && udevadm trigger --subsystem-match=hidraw`. Explain the rule: vendor `17cc`, product `1140`, mode `0664`, group `audio`, `SYMLINK+="maschine"`, plus restart-on-add and stop-on-remove.
4. `install -m 0755 system/maschine-jack-connect.sh system/maschine-clock-bridge.py system/maschine-clock-connect.sh /usr/local/bin/`.
5. `install -m 0644 system/maschine-*.service /etc/systemd/system/`, `systemctl daemon-reload`, `systemctl enable --now maschine-mk2 maschine-web maschine-clock`. Note `maschine-mk2.service` runs `ExecStartPost=/usr/local/bin/maschine-jack-connect.sh`, which connects the a2j port to `ZynMidiRouter:dev3_in` and sets the port alias `virtual:maschine.rs/Maschine MK2 Pads` — Zynthian derives a control-device id from the alias, and a2j gives user-client ports none.
6. `a2jmidid` must export software clients, or the daemon's port never appears in JACK.
7. `python3 tools/patch-autoconnect-maschine.py` — the whitelist entry plus the pinned uid. Without it the driver is listed **Found** and never **Loaded**, and the rig does nothing with no error. State that it must be re-run after every Zynthian system update, and that it is idempotent.
8. Copy the three `ctrldev/*.py` files to `/zynthian/zynthian-ui/zyngine/ctrldev/`. Warn: copy files, never git — the Pi's `zynthian-ui` carries them as untracked drop-ins and a hard reset deletes them. Warn that every module in that directory needs a `dev_ids` attribute or the UI crash-loops every 14 seconds.
9. Restart **daemon first, then the UI**, with the a2j/zmip explanation.
10. Verify: `journalctl -u zynthian --since -3min | grep -i ctrldev` shows **Loaded**; `jack_lsp -c | grep -A3 "Pads MIDI"` shows exactly one `devN_in`; the MK2 draws the tab row `A KICK` … `H PADS` and lights its Group buttons **with no snapshot loaded at all**.

Then offer `./install.sh` as the scripted equivalent, and `./install.sh --dry-run` to see what it would do. State plainly that the guide is authoritative and the script is a convenience.

- [ ] **Step 2: Regenerate and verify the traps survived into HTML**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
python3 tools/generate-html.py >/dev/null
for s in external_pad_leds dev_ids "daemon first" Loaded 99-maschine.rules; do
  printf "%-20s %s\n" "$s" "$(grep -c "$s" docs/03-install-driver.html)"
done
```

Expected: every count at least `1`.

- [ ] **Step 3: Commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add guide/03-install-driver.md docs
git commit -m "docs: section 3 - driver, daemon and the seven traps

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Section 4 — prepare Zynthian

**Files:**
- Create: `$REPO/guide/04-prepare-zynthian.md`

**Interfaces:**
- Consumes: `tools/check-prereqs.sh` from Task 5.
- Produces: a Zynthian able to load the snapshot in section 5.

- [ ] **Step 1: Write the page**

Required content:

- `apt install obxd-lv2 padthv1-lv2 tap-lv2`, naming what each provides: Obxd (LEAD), padthv1 (PADS), and TAP Reverberator plus TAP Stereo Echo (the sixteen inserts). Give the bundle paths `/usr/lib/lv2/Obxd.lv2`, `padthv1.lv2`, `tap-reverb.lv2`, `tap-echo.lv2`.
- JC303 (BASS) comes from Zynthian's own plugin set at `/zynthian/zynthian-plugins/lv2/JC303.lv2` and is not a Debian package.
- In webconf, enable the plugins on the **Engines** page, then **Regenerate LV2 Cache**. State that a plugin installed but not enabled is invisible to a snapshot.
- Confirm the SFZ drum machines at `/zynthian/zynthian-data/soundfonts/sfz/Drum Machines` — 42 kits, about 43 MB, on the author's rig. State honestly that they are **not** in any git repo (`sfz/**` is gitignored in `zynthian-data`), so they are believed to ship in the OS image but that is unproven; if the directory is missing or empty, the five drum channels will load with no sound and the fix is to supply SFZ kits there.
- Run `bash tools/check-prereqs.sh` and read the output. Explain that `017-generative-techno.zss` and the 64 TAP ports will report MISSING until section 5, and that everything else must be PRESENT.

- [ ] **Step 2: Regenerate and verify**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
python3 tools/generate-html.py >/dev/null
for s in obxd-lv2 padthv1-lv2 tap-lv2 "Regenerate LV2 Cache" "Drum Machines"; do
  printf "%-24s %s\n" "$s" "$(grep -c "$s" docs/04-prepare-zynthian.html)"
done
```

Expected: every count at least `1`.

- [ ] **Step 3: Commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add guide/04-prepare-zynthian.md docs
git commit -m "docs: section 4 - plugins, LV2 cache, drum kits, preflight

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: Section 5 — import the snapshot

**Files:**
- Create: `$REPO/guide/05-import-snapshot.md`

**Interfaces:**
- Consumes: Task 11's prepared Zynthian; `snapshot/017-generative-techno.zss` (committed in Task 16).
- Produces: a rig that makes the factory music.

- [ ] **Step 1: Write the page**

Required content:

- `scp snapshot/017-generative-techno.zss root@<pi>:/zynthian/zynthian-my-data/snapshots/000/`. State that a snapshot at the snapshots root rather than inside a bank is **invisible** in the UI.
- Load it from the touchscreen: Snapshots → bank `000` → the snapshot's name.
- The warning, in a block: webconf's Snapshots page **Name:** field with the checkmark **renames the selected bank**. It has destroyed bank `000` once. Never save or load from there.
- What to see within about 15 seconds: eight mixer strips plus main on the touchscreen; both MK2 displays drawing the tab row and four encoder columns each; the eight Group buttons in their channel colours.
- Press **Play** once after loading. Restoring a snapshot rewrites every sequence's play mode from the file, and a loop-all sequence shorter than the bar goes silent until the next bar sync; the driver re-forces LOOP on every transport start.
- What the factory state is, as a table matching the appendix: 124 BPM; A-D the four-on-the-floor beat; E a drum kit walking a Turing register; F a frozen bass line at `LOCK`; G a lead at full random; H one 8-step note per 8-step loop.
- Fault routing: if channels are silent, run `tools/check-prereqs.sh` before anything else, then section 6's checks.

- [ ] **Step 2: Regenerate and verify**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
python3 tools/generate-html.py >/dev/null
for s in "017-generative-techno" "renames the selected bank" "Play"; do
  printf "%-30s %s\n" "$s" "$(grep -c "$s" docs/05-import-snapshot.html)"
done
```

Expected: every count at least `1`.

- [ ] **Step 3: Commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add guide/05-import-snapshot.md docs
git commit -m "docs: section 5 - import and load the factory snapshot

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: Section 6 — testing

**Files:**
- Create: `$REPO/guide/06-testing.md`

**Interfaces:**
- Consumes: `ctrldev/tests/` (Task 3), `tools/check-prereqs.sh` (Task 5).
- Produces: the acceptance procedure the owner runs before signing off `017`.

- [ ] **Step 1: Write the page in two halves**

Machine-checkable half, with expected output for each:

```bash
cd ctrldev && python3 -m unittest discover -s tests -q     # Ran 271 tests ... OK
bash tools/check-prereqs.sh; echo "exit=$?"                # exit=0
jack_lsp | grep -c TAP                                     # 64
jack_lsp -c | grep -A3 "Pads MIDI"                         # exactly one devN_in
journalctl -u zynthian --since -5min | grep -iE "traceback|error|segfault"   # nothing
journalctl --since -20min | grep -c "watchdog: input stalled, reopened"      # ~1 per 8s is HEALTHY
```

State plainly why the unit tests are the only automated proof: the driver itself cannot be imported off-Pi because `zynlibs.zynseq` is Pi-only, so `techno_lib.py` carries the logic and is tested, and the driver is verified by hand.

By-ear half, a checklist the reader runs:

- Kick on the four; snare on steps 4 and 12; clap on 3, 8, 13; closed hat on the odd steps.
- BASS repeats the same line exactly, every bar — the `LOCK` proof.
- LEAD changes phrase roughly every bar.
- PADS sounds one note per 8-step loop.
- E OHAT changes sample as its register walks the kit.
- F1-F8 mute the matching channel from any selection; tap latches, hold is momentary.
- SOLO held plus an F button is momentary solo; SOLO tapped latches the row.
- ERASE alone does nothing; ERASE plus a pad clears that step; ERASE plus a Group silences the channel.
- Sweep encoder 7 (REVERB) 0 → 100 on any channel: the dry signal must still be there, at the same level, at the top. If it fades, the insert is a crossfade and the send contract is broken.
- The wet knobs are back-heavy: 0-100 maps to −70 dB … +10 dB, so 25 is inaudible, 88 equals dry, and the useful travel is roughly 60-100.

Close with the note that no agent can verify audio, so this half is the reader's, and `017` is not signed off until it passes.

- [ ] **Step 2: Run every machine-checkable command in the page and paste real output**

Run them, and correct the page wherever reality differs from what you wrote. The `017`-dependent checks (64 TAP ports, `exit=0`) only pass after Task 16 — note in the page that they are part of the post-import check, not the pre-import one.

- [ ] **Step 3: Regenerate, verify, commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
python3 tools/generate-html.py >/dev/null
grep -c "271" docs/06-testing.html
git add guide/06-testing.md docs
git commit -m "docs: section 6 - automated checks and the by-ear checklist

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 14: Section 7 placeholder and both appendices

**Files:**
- Create: `$REPO/guide/07-playing.md`
- Create: `$REPO/guide/a1-how-017-was-built.md`
- Create: `$REPO/guide/a2-touchscreen-patch.md`

**Interfaces:**
- Consumes: Tasks 7-13. A1 consumes the CC sequence produced by the snapshot build.
- Produces: the last three pages the sidebar already links to.

- [ ] **Step 1: Write `07-playing.md` as an honest placeholder**

One paragraph saying what will go here — the euclidean model, the Turing machine and `LOCK` as the central gesture, REC and pattern ownership, SHIFT + GRID kind switching, the performance gestures — and a link to the existing manual at
`zynth-docs/docs/superpowers/techno-machine/2026-08-10-techno-machine-manual.md`, with the warning that the manual is dated 2026-08-10 and describes three pages where the shipped surface has five modes.

- [ ] **Step 2: Write `a1-how-017-was-built.md`**

Required content, all values exact:

- The chain table: eight chains, MIDI channels 1-8, engines `LS/LinuxSampler` ×5, `JV/JC303`, `JV/Obxd`, `JV/padthv1`; chain titles `Kick`, `Snare`, `Clap`, `Closed Hat`, `Open Hat`, `BASS`, `LEAD`, `PADS`.
- Insert order **as measured on the wire**: `zynmixer:output_NNa/b → TAP_Stereo_Echo-NN → TAP_Reverberator-NN → zynmixer:input_17`. Note that this contradicts the 2026-08-10 manual's diagram, which shows the reverb first.
- Insert values: `dryLevel` and `drylevel` at **0.0 dB** (TAP ships −4 dB, which costs about 8 dB across the pair), `lecholevel`, `recholevel` and `wetlevel` at **−70.0 dB**.
- Gain staging: strips **0.19**, main **0.80**, with the measurement behind it — one sampler channel peaks at 1.24 before the mixer and eight summed to 2.92 on the main bus, nearly three times full scale; the sampler's own volume is not the fix (96 → 40 moved the bus peak about 1.5 dB), the strips are.
- `tools/build-techno-snapshot.py`: build one channel's insert pair by hand, run the script to clone it onto the other seven with fresh processor ids, then load and re-save from the touchscreen so what is on disk is Zynthian's own output.
- The factory musical state table from section 5, plus the three constraints that shaped it: a voice's pattern length is not on the surface (encoder 1 is the register's bits) and PADS reaches 8 steps via a kind switch, because `div` and `beats` deliberately do not move on a switch; `GATE_MAX = 800` is 8 steps and `note_duration()` clamps to `steps - step`; `DENSITY` is deterministic — `gate_mask()` sounds the N lowest gate values, `N = round(density × steps)`.
- The CC sequence that produced the state, taken from the snapshot build's report, with the note that encoders are **relative** and the driver rejects apparent jumps of 8 units or more as counter wraps.
- Which step PADS actually landed on, and if it is not step 0, that the note is correspondingly shorter than the loop.

- [ ] **Step 3: Write `a2-touchscreen-patch.md`**

State who needs it: readers whose panel's touch resolution differs from Zynthian's configured display size, which makes touches land in the wrong place. Give the diff against `zyngui/multitouch.py` — the `ABS_MT_POSITION_X` and `ABS_MT_POSITION_Y` handlers scale the raw value by `zynthian_gui_config.display_width / self.max_x` and `display_height / self.max_y`, guarding against a zero maximum. Say it is optional, not part of the instrument, and that it edits a Zynthian core file, so back it up first.

- [ ] **Step 4: Regenerate, verify all nine pages exist, commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
python3 tools/generate-html.py >/dev/null
ls docs/*.html | wc -l
git add guide docs
git commit -m "docs: section 7 placeholder, plus both appendices

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

Expected: `10` — nine pages plus `index.html`.

---

### Task 15: Enable GitHub Pages

**Files:** none — repository settings only.

**Interfaces:**
- Consumes: Task 7's `docs/` output.
- Produces: the public URL used in the README and in section 1.

- [ ] **Step 1: Push everything, then enable Pages on main `/docs`**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git push
gh api -X POST repos/Witzman/Generative-Techno-ZynthianMaschine-MKII/pages \
  -f 'source[branch]=main' -f 'source[path]=/docs'
```

If the API answers `409 Conflict`, Pages is already enabled; move on.

- [ ] **Step 2: Read back the URL and confirm it builds**

```bash
gh api repos/Witzman/Generative-Techno-ZynthianMaschine-MKII/pages -q '.html_url, .status'
```

Expected: a `https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/` URL and a status that reaches `built`. A build takes a minute or two; re-run until it is not `building`.

- [ ] **Step 3: Fetch the live landing page**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://witzman.github.io/Generative-Techno-ZynthianMaschine-MKII/
```

Expected: `200`.

- [ ] **Step 4: Put the URL in the README and section 1, then commit**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
python3 tools/generate-html.py >/dev/null
git add README.md guide/01-what-it-is.md docs
git commit -m "docs: link the published Pages site"
git push
```

---

# Phase P3 — cutover

### Task 16: Commit the factory snapshot after the owner signs it off

**Files:**
- Create: `$REPO/snapshot/017-generative-techno.zss`

**Interfaces:**
- Consumes: the snapshot built on the Pi by the parallel snapshot task.
- Produces: the file section 5 tells the reader to `scp`.

- [ ] **Step 1: Confirm the snapshot exists on the Pi and copy it out**

```bash
ssh root@192.168.2.123 'ls -la /zynthian/zynthian-my-data/snapshots/000/017-generative-techno.zss'
mkdir -p /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/snapshot
scp root@192.168.2.123:/zynthian/zynthian-my-data/snapshots/000/017-generative-techno.zss \
    /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/snapshot/
```

- [ ] **Step 2: Verify the file's contents against the spec**

```bash
python3 - <<'EOF'
import json
p="/home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII/snapshot/017-generative-techno.zss"
d=json.load(open(p))
mix=d["zs3"]["zs3-0"]["mixer"]
print("mixer:", {k:round(v["level"],3) for k,v in mix.items() if isinstance(v,dict) and "level" in v})
print("chains:", [(c.get("midi_chan"), c.get("title")) for _,c in sorted(d["chains"].items(), key=lambda kv:int(kv[0]))])
print("riff bytes:", len(d.get("zynseq_riff_b64","")))
EOF
```

Expected: eight strips at `0.19` and the main strip at `0.8`; MIDI channels 0-7 present with the eight titles; a non-empty riff.

- [ ] **Step 3: Owner gate — sign-off by ear**

The owner loads the snapshot on the rig and walks section 6's by-ear checklist. **Do not commit until they confirm.** No agent can verify audio; a snapshot that loads is not a snapshot that plays.

- [ ] **Step 4: Commit the snapshot**

```bash
cd /home/witzman/zynth/Generative-Techno-ZynthianMaschine-MKII
git add snapshot/017-generative-techno.zss
git commit -m "feat: factory snapshot 017-generative-techno

124 BPM, four-on-the-floor across A-D, E a drum kit walking a Turing register,
F a frozen bass at LOCK, G a lead at full random, H one 8-step note per loop.
Strips 0.19, main 0.80, inserts dry at unity and wet off. Verified by ear on
the author's rig.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
```

---

### Task 17: Retire the superseded zynth-docs page

**Files:**
- Delete: `~/zynth-docs/htmldoku/project-techno-machine.md`
- Delete: `~/zynth-docs/docs/zynthian-Doku/project-techno-machine.html`
- Modify: `~/zynth-docs/htmldoku/generate-html.py` (remove the sidebar entry)
- Modify: `~/zynth-docs/MD/inwork.md`, `~/zynth-docs/MD/todo.md`

**Interfaces:**
- Consumes: the published Pages URL from Task 15.
- Produces: a zynth-docs site with one canonical pointer instead of a competing build document.

- [ ] **Step 1: Remove the page, its HTML and its sidebar entry**

```bash
cd /home/witzman/zynth-docs
git rm htmldoku/project-techno-machine.md docs/zynthian-Doku/project-techno-machine.html
```

Then delete this line from `htmldoku/generate-html.py`:

```python
        ("Techno Machine — Build the Rig", "project-techno-machine.html"),
```

- [ ] **Step 2: Point the tracking files at the new repo**

In `MD/inwork.md`, replace the `Techno Machine — Build the Rig` tutorial item with one line stating the build guide now lives in `Generative-Techno-ZynthianMaschine-MKII`, with the Pages URL. In `MD/todo.md`, replace the four hardware-walk checkboxes with a single item pointing at the new repo's own tasks.

- [ ] **Step 3: Regenerate the whole site and verify the page is gone everywhere**

```bash
cd /home/witzman/zynth-docs
python3 htmldoku/generate-html.py >/dev/null
grep -rl "project-techno-machine" docs/zynthian-Doku/ | head
ls docs/zynthian-Doku/project-techno-machine.html 2>&1
```

Expected: the `grep` prints nothing, and the `ls` reports no such file. The generator rewrites every page's sidebar, so all 41 remaining pages change.

- [ ] **Step 4: Commit and push**

```bash
cd /home/witzman/zynth-docs
git add -A htmldoku docs/zynthian-Doku MD/inwork.md MD/todo.md
git commit -m "docs: retire the techno machine tutorial, superseded by its own repo

The build guide now lives in Generative-Techno-ZynthianMaschine-MKII, which
also carries the driver, the daemon, the system files and the factory
snapshot. Two build documents would have drifted from the first edit.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
```

---

### Task 18: Point the old daemon fork at the new home

**Files:**
- Modify: `~/zynth/MaschineMK2_linux/README.md`

**Interfaces:**
- Consumes: Task 2's vendored daemon.
- Produces: one truth about where the daemon is developed.

- [ ] **Step 1: Add a notice at the top of the fork's README**

```markdown
> **Development moved.** This daemon is now developed inside
> [Generative-Techno-ZynthianMaschine-MKII](https://github.com/Witzman/Generative-Techno-ZynthianMaschine-MKII),
> under `daemon/`, together with the Zynthian-side driver it is built for.
> This repository is kept for history and is no longer updated.
```

- [ ] **Step 2: Commit and push the fork**

```bash
cd /home/witzman/zynth/MaschineMK2_linux
git add README.md
git commit -m "docs: development moved to Generative-Techno-ZynthianMaschine-MKII

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push
```

- [ ] **Step 3: Archive the repository on GitHub**

```bash
gh repo archive Witzman/MaschineMK2_linux --yes
gh repo view Witzman/MaschineMK2_linux --json isArchived
```

Expected: `{"isArchived":true}`.

**Do not touch the Pi's copy at `/root/zynth/MaschineMK2_linux`.** Its git HEAD is an old display experiment and the running code exists only as uncommitted working-tree changes; the running daemon binary lives there and the systemd unit points at it until the reader re-installs from the new repo.

---

## Verification summary

| Success criterion (spec §10) | Proven by |
|---|---|
| 1 · repo public, GPL-3.0 | Task 1 Step 7 |
| 2 · a clone installs the instrument | Task 6 Step 4 dry-run on the Pi |
| 3 · 271 tests pass in the clone, no Pi | Task 3 Step 2 |
| 4 · Pages renders nine pages with an intact sidebar | Task 14 Step 4, Task 15 Step 3 |
| 5 · preflight exits zero on the Pi | Task 5 Step 6 (exit 1 until Task 16), re-run after Task 16 |
| 6 · `017` loads and plays the factory state | Task 16 Steps 2-3, owner gate |
| 7 · zynth-docs no longer carries the tutorial | Task 17 Step 3 |
