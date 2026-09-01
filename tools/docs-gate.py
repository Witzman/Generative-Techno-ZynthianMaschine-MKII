#!/usr/bin/env python3
"""Rebuild the search index and gate the hand-edited documentation.

    python3 tools/docs-gate.py          # rebuild index, run every gate
    python3 tools/docs-gate.py --check  # gates only, write nothing

`docs/*.html` is the source. There is no Markdown and no site generator: the
HTML is edited directly. That trade buys immediate, readable edits and costs the
three things a generator used to guarantee, which is exactly what these gates
put back:

  G1  every internal link resolves
  G2  the sidebar is identical on every page  (it is now copied in 19 files)
  G3  search-index.json matches what the pages actually say
  G4  no internal-only path is published
  G6  every bound button is named on the surface page, and vice versa

G5 WAS A LENGTH RATCHET AND IS GONE, 2026-09-01. It capped each page against a
dated baseline and each section at 300 words, to stop prose drifting longer
without anybody deciding to. It did its job for a year and then started doing
the opposite: the surface redesign added a light alphabet, a lens and a
duration rule, and the gate's answer to a page that had genuinely more to say
was to make somebody trim it or move a number. A budget that is raised every
time it is hit is not a ratchet, it is a chore.

What replaced it is G6 and G1: the guide has to NAME EVERY BOUND BUTTON and
every link has to resolve. Those bound the documentation to the instrument
rather than to its own past length, which is the thing that was actually worth
enforcing.
"""

import html as _html
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

LANDING = "00-start.html"

# Paths that exist only on the author's machine. None may reach a reader.
INTERNAL = ["/home/witzman", "guide-src", "zynth-docs", "zynth-repos",
            "technomaschine/notes", "/legacy/"]




def strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def article(raw):
    m = re.search(r"<article>(.*?)</article>", raw, re.DOTALL)
    return m.group(1) if m else ""



def build_index(pages, write=True):
    index = []
    for f in pages:
        art_html = article(f.read_text(encoding="utf-8"))
        if not art_html:
            continue
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", art_html, re.I | re.S)
        index.append({
            "title": strip_tags(h1.group(1)) if h1 else f.stem,
            "url": f.name,
            "headings": [{"text": strip_tags(m.group(2)), "id": m.group(1)}
                         for m in re.finditer(
                             r'<h[23][^>]* id="([^"]+)"[^>]*>(.*?)</h[23]>',
                             art_html, re.I | re.S)],
            "body": strip_tags(art_html),
        })
    blob = json.dumps(index, ensure_ascii=False, separators=(",", ":"))
    if write:
        (DOCS / "search-index.json").write_text(blob, encoding="utf-8")
    return blob


# Every CC the driver binds, and the words the guide is allowed to call it by.
# The FIRST is the name printed on the panel, because that is what a player
# reads; the rest are the names this instrument gives the function, which is
# what the prose usually says. Either satisfies the gate - what it refuses is
# a bound button the page mentions by NEITHER name.
#
# Kept here rather than imported from techno_lib because this tool must run
# with no path games and no import of a module that pulls in the driver's
# world. It is a second copy, and that is a real cost - so the count is
# asserted against the live tables by ctrldev/tests, which fails the moment a
# binding is added or removed without this list moving with it.
PANEL_NAMES = {
    1:  ("PLAY",),
    2:  ("ERASE",),
    3:  ("REC",),
    4:  ("GRID",),
    6:  ("STEP", "beat repeat"),
    7:  ("RESTART",),
    10: ("NOTE REPEAT",),
    11: ("CONTROL",),
    12: ("big encoder", "HOME"),
    13: ("beside the big encoder", "master"),
    14: ("beside the big encoder", "master"),
    # 25 (SCENE) left this table on 2026-09-01 when PATTERN took both kinds.
    # It is free surface, and G6 must not ask the guide to document a button
    # that does nothing.
    26: ("PATTERN",),
    27: ("PAD MODE", "FREEZE"),
    29: ("DUPLICATE",),
    30: ("SELECT", "ARM"),
    31: ("SOLO",),
    32: ("STEP",),
    33: ("MUTE",),
    34: ("NAVIGATE",),
    35: ("TEMPO",),
    37: ("AUTO",),
    38: ("ALL", "lens"),
    47: ("arrows beside the display",),
    48: ("arrows beside the display",),
    49: ("SHIFT",),
    50: ("SWING", "MOD"),
    51: ("VOLUME",),
}


def main():
    check_only = "--check" in sys.argv
    pages = sorted(p for p in DOCS.glob("*.html") if p.name != "index.html")
    fail = []

    if not pages:
        print("no pages in docs/", file=sys.stderr)
        return 1

    # --- G3 search index -----------------------------------------------------
    blob = build_index(pages, write=not check_only)
    current = (DOCS / "search-index.json")
    if check_only:
        if not current.exists() or current.read_text(encoding="utf-8") != blob:
            fail.append("G3 search-index.json is stale - run without --check")
    print(f"  G3  search index      {len(json.loads(blob))} pages"
          f"{'' if check_only else ' (rebuilt)'}")

    # --- G1 links ------------------------------------------------------------
    # Fragments count. A link to a heading that no longer carries that id lands
    # the reader at the top of the right page and looks like it worked, so it is
    # exactly the kind of rot that survives a read-through.
    ids = {p.name: set(re.findall(r'id="([^"]+)"', p.read_text(encoding="utf-8")))
           for p in DOCS.glob("*.html")}
    broken = set()
    for f in list(pages) + [DOCS / "index.html"]:
        if not f.exists():
            continue
        for href in re.findall(r'href="([^"]+)"', f.read_text(encoding="utf-8")):
            if "://" in href or href.startswith("mailto:"):
                continue
            path, _, frag = href.partition("#")
            target = path or f.name          # a bare #id points at this page
            if not target.endswith(".html"):
                continue                     # style.css, favicon.svg and friends
            if target not in ids:
                broken.add(f"{f.name} -> {href}")
            elif frag and frag not in ids[target]:
                broken.add(f"{f.name} -> {href} (no such id)")
    print(f"  G1  internal links    {'ok' if not broken else sorted(broken)}")
    if broken:
        fail.append(f"G1 broken links: {sorted(broken)}")

    # --- G2 sidebar identical ------------------------------------------------
    # Compare the link structure, not the markup: which group holds which
    # pages, in order. The active page's group is expanded and the others are
    # collapsed, so raw markup legitimately differs from page to page.
    navs = {}
    for f in pages:
        m = re.search(r'<nav id="sidebar".*?</nav>', f.read_text(encoding="utf-8"), re.S)
        if not m:
            fail.append(f"G2 {f.name} has no sidebar")
            continue
        nav = m.group(0)
        shape = []
        for group in re.finditer(
                r'<span class="track-label">(.*?)</span>(.*?)(?=<div class="track"|</nav>)',
                nav, re.S):
            links = re.findall(r'<li><a href="([^"]+)"[^>]*>(?:<strong>)?(.*?)(?:</strong>)?</a></li>',
                               group.group(2), re.S)
            shape.append((strip_tags(group.group(1)),
                          tuple((h, strip_tags(t)) for h, t in links)))
        navs.setdefault(tuple(shape), []).append(f.name)
    if len(navs) > 1:
        groups = [sorted(v) for v in navs.values()]
        fail.append(f"G2 sidebar differs between pages: {groups}")
    print(f"  G2  sidebar identical {'ok' if len(navs) == 1 else 'DRIFT'}")

    # --- G4 no internal paths ------------------------------------------------
    leaks = []
    for f in list(pages) + [DOCS / "index.html"]:
        if not f.exists():
            continue
        raw = f.read_text(encoding="utf-8")
        leaks += [f"{f.name}: {tok}" for tok in INTERNAL if tok in raw]
    print(f"  G4  no internal paths {'ok' if not leaks else leaks}")
    if leaks:
        fail.append(f"G4 internal paths published: {leaks}")

    # --- G6 the button map against the page that documents it ----------------
    #
    # THE GATE THIS PROJECT HAS NEEDED MOST OFTEN. Its recorded failure mode is
    # "a document that describes the code, believed, and wrong" - the guide
    # said a frozen instrument says so three times when its light had never
    # lit, said a shipped LENGTH range did not exist, and ranked sixteen built
    # features as open. Every one of those was prose drifting from a table.
    #
    # This compares the two directly. Every CC in BUTTONS_STATEFUL or
    # BUTTONS_PRESS is a button a player can press, so the-surface.html has to
    # name it; every panel name the page uses has to be one that is bound.
    # Neither direction is decoration: the first catches a binding nobody
    # wrote up, the second catches a paragraph outliving its feature.
    print("  G6  buttons vs the guide")
    surface = DOCS / "the-surface.html"
    if not surface.exists():
        fail.append("G6 docs/the-surface.html is missing")
    else:
        text = strip_tags(surface.read_text(encoding="utf-8")).upper()
        for cc, action in sorted(PANEL_NAMES.items()):
            if not any(name.upper() in text for name in action):
                fail.append(f"G6 CC {cc} is bound and the surface page never "
                            f"names it ({' / '.join(action)})")

    if fail:
        print("\nFAIL")
        for x in fail:
            print(f"  {x}")
        return 1
    print("\nAll gates passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
