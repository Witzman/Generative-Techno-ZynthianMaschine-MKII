# 2 · Install ZynthianOS

This guide is pinned to one version: **ZynthianOS `Oram-2601-1`**, built
2026-01-27 from RaspberryPiOS Bookworm (aarch64), with `zynthian-ui` and
`zynthian-sys` on branch `oram-2601.1`.

That is not an arbitrary pin. It is the build the rig was measured on, **and** it
is what zynthian.org currently serves as the latest stable image.

If Zynthian already runs on your Pi, skip to
[section 3](03-install-driver.md) — but check the version first, at the bottom of
this page.

---

## Get the image

| File on `https://os.zynthian.org/` | Notes |
|---|---|
| `zynthianos-last-stable.img.xz` | The "latest stable" pointer. As of 2026-08-13 this is the same 7.5 GB build as the dated file below |
| `2026-01-27-zynthianos-oram-2601-stable.img.xz` | The dated, stable-forever name for exactly this build |

Download one of them and its matching `.md5`, then verify before you flash. A
truncated 7.5 GB download produces a Pi that boots most of the way and then
behaves inexplicably.

```bash
curl -O https://os.zynthian.org/2026-01-27-zynthianos-oram-2601-stable.img.xz
curl -O https://os.zynthian.org/2026-01-27-zynthianos-oram-2601-stable.img.xz.md5
md5sum -c 2026-01-27-zynthianos-oram-2601-stable.img.xz.md5
# → 2026-01-27-zynthianos-oram-2601-stable.img.xz: OK
```

### Newer images exist, and this guide is not tested on them

| Image | Date | Status |
|---|---|---|
| `2026-07-30-zynthianos-vangelis-2607-beta.img.xz` | 2026-07-30 | **beta** |
| `2026-06-18-zynthianos-vangelis-2606-test.img.xz` | 2026-06-18 | test |

Vangelis is Zynthian's active development train — upstream commits land there
daily, while the `oram` branches stopped moving in early 2026. Its release
thread is still titled BETA and carries open bugs, including a system hang when
the audio player is asked to play an MP3.

Nothing in this project has been run on Vangelis. If you install it, expect to
audit every library call the driver makes: this rig has already been broken three
times by a Zynthian version difference, on call arity and on two functions that
exist upstream but not in the installed library.

---

## Flash it and boot

Flashing and first boot are documented upstream and maintained there, so this
guide links rather than copies — a second-hand copy of installation instructions
rots quietly and then costs someone an afternoon.

- **Zynthian wiki:** <https://wiki.zynthian.org>
- **Zynthian install documentation:** <https://zynthian.org> → Wiki → the
  "Getting Started" / SD card sections

Use Raspberry Pi Imager or `dd` to write the decompressed image to a card of
16 GB or more. Boot the Pi with a display attached; ZynthianOS resizes its
filesystem and starts its UI by itself on first boot.

---

## Get to a shell and to webconf

You need both for everything that follows.

**SSH.** ZynthianOS runs `sshd` and the account you use is `root`.

```bash
ssh root@zynthian.local
```

If `.local` does not resolve — it does not, from WSL2 — use the IP address
instead. Find it on the Zynthian UI's admin screen, or from your router.

```bash
ssh root@192.168.2.123      # substitute your own
```

**webconf.** Open `http://zynthian.local` (or `http://<ip>`) in a browser. This
guide uses it for exactly one thing, in section 4: enabling LV2 plugins and
regenerating the plugin cache.

---

## Confirm the version before continuing

Four checks. All four must pass, because every later section assumes them.

| Check | Command | Expected |
|---|---|---|
| OS build | `cat /zynthian/build_info.txt` | first line contains `Oram-2601-1` |
| UI branch | `git -C /zynthian/zynthian-ui branch --show-current` | `oram-2601.1` |
| Shell | `ssh root@<pi> 'echo ok'` | `ok` |
| webconf | open `http://<pi>` | the configuration page loads |

```bash
ssh root@192.168.2.123 'head -1 /zynthian/build_info.txt; \
  git -C /zynthian/zynthian-ui branch --show-current'
# → ZynthianOS Oram-2601-1
# → oram-2601.1
```

If the branch differs, you are on another release train. The rest of the guide
may still work, but it is untested there, and `tools/check-prereqs.sh` in
section 4 is where you will find out what is missing.

> **Honesty note.** This section was written from a rig that was already running,
> not from a fresh flash — there was no spare SD card to test with. The commands
> above are real and their output is real; the flashing steps are upstream's and
> are linked rather than reproduced. If a clean install differs from what you read
> here, that difference is a gap in this page, and section 4's preflight is
> designed to catch its consequences.

---

**Next:** [3 · Install the driver and daemon](03-install-driver.md)
