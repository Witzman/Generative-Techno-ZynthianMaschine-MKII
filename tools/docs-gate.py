#!/usr/bin/env python3
"""Rebuild the search index and gate the hand-edited documentation.

    python3 tools/docs-gate.py          # rebuild index, run every gate
    python3 tools/docs-gate.py --check  # gates only, write nothing

`docs/*.html` is the source. There is no Markdown and no site generator: the
HTML is edited directly. That trade buys immediate, readable edits and costs the
three things a generator used to guarantee, which is exactly what these gates
put back:

  G1  every internal link resolves
  G2  the sidebar is identical on every page  (it is now copied in 7 files)
  G3  search-index.json matches what the pages actually say
  G4  no internal-only path is published
  G5  prose has not drifted past its dated baseline

A budget here is a ratchet against drift, not a claim about ideal length. Going
over is allowed - move the number in BASELINE and its date, deliberately. Never
nudge it to make a run pass.
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

# name: (baseline prose words, date measured). Prose excludes code and tables.
BASELINE = {
    "00-start.html":               (93,   "2026-08-13"),
    "01-fast-installation.html":   (286,  "2026-08-13"),
    "02-features.html":            (676,  "2026-08-13"),
    "04-manual-installation.html": (1539, "2026-08-13"),
    "05-internals.html":           (1011, "2026-08-13"),
    "a1-touchscreen-patch.html":   (325,  "2026-08-13"),
}
SKIP_BUDGET = {"03-playing.html", "index.html"}
HEADROOM = 1.15
UNIT_CAP = 300   # any h2/h3 section; long asides belong in their own section


def strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def article(raw):
    m = re.search(r"<article>(.*?)</article>", raw, re.DOTALL)
    return m.group(1) if m else ""


def prose_words(art_html):
    """Prose only: code blocks and tables carry detail on purpose."""
    t = re.sub(r"<pre>.*?</pre>", " ", art_html, flags=re.S)
    t = re.sub(r"<table>.*?</table>", " ", t, flags=re.S)
    return strip_tags(t).split()


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
    broken = set()
    for f in list(pages) + [DOCS / "index.html"]:
        if not f.exists():
            continue
        for href in re.findall(r'href="([^"#:]+\.html)"', f.read_text(encoding="utf-8")):
            if not (DOCS / href).exists():
                broken.add(f"{f.name} -> {href}")
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

    # --- G5 budgets ----------------------------------------------------------
    print("  G5  prose budgets")
    for f in pages:
        if f.name in SKIP_BUDGET:
            print(f"        {f.name:<30} skipped")
            continue
        art_html = article(f.read_text(encoding="utf-8"))
        words = len(prose_words(art_html))
        if f.name not in BASELINE:
            fail.append(f"G5 {f.name}: no baseline - add one to BASELINE")
            continue
        base, when = BASELINE[f.name]
        budget = int(base * HEADROOM)
        ok = words <= budget
        print(f"        {f.name:<30} {words:>5} / {budget:<5} base {base} @{when} "
              f"{'ok' if ok else 'OVER by ' + str(words - budget)}")
        if not ok:
            fail.append(f"G5 {f.name}: {words} over {budget} - trim or re-baseline")

        for m in re.finditer(r"<h[23][^>]*>.*?(?=<h[23][^>]*>|$)", art_html, re.S):
            unit = m.group(0)
            n = len(prose_words(unit))
            if n > UNIT_CAP:
                head = strip_tags(re.match(r"<h[23][^>]*>(.*?)</h[23]>", unit, re.S).group(1))
                fail.append(f"G5 {f.name}: section over {UNIT_CAP} words ({n}): {head}")

    if fail:
        print("\nFAIL")
        for x in fail:
            print(f"  {x}")
        return 1
    print("\nAll gates passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
