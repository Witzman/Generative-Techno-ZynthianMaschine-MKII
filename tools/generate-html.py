#!/usr/bin/env python3
"""Convert htmldoku/*.md to zynthian-Doku/*.html — stdlib only, no external dependencies."""

import json
import re
import os
import shutil
import html as _html
from pathlib import Path
from datetime import date

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
SRC_DIR   = REPO_ROOT / "guide"
OUT_DIR   = REPO_ROOT / "docs"

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

MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"

# ---------------------------------------------------------------------------
# Step 1 — Extract Mermaid blocks BEFORE any other processing
# ---------------------------------------------------------------------------

MERMAID_FENCE_RE = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)


def extract_mermaid(text):
    blocks = []

    def _replace(m):
        idx = len(blocks)
        blocks.append(m.group(1))
        return f"\n%%MERMAID_{idx}%%\n"

    return MERMAID_FENCE_RE.sub(_replace, text), blocks


def restore_mermaid(html, blocks):
    for i, block in enumerate(blocks):
        token = f"%%MERMAID_{i}%%"
        inner = block.rstrip()
        div = f'<div class="mermaid">\n{inner}\n</div>'
        html = html.replace(f"<p>{token}</p>", div)
        html = html.replace(token, div)
    return html


# ---------------------------------------------------------------------------
# Step 2 — Minimal Markdown → HTML converter (stdlib only)
# ---------------------------------------------------------------------------

def md_escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def apply_inline(text):
    text = re.sub(r"`([^`]+)`", lambda m: f"<code>{md_escape(m.group(1))}</code>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)",
        lambda m: f'<img src="{m.group(2)}" alt="{m.group(1)}">',
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
        text,
    )
    return text


def convert_md(text):
    lines = text.split("\n")
    html_parts = []
    i = 0

    def flush_paragraph(buf):
        if buf:
            content = apply_inline(" ".join(buf))
            html_parts.append(f"<p>{content}</p>")
            buf.clear()

    para_buf = []

    while i < len(lines):
        line = lines[i]

        if re.match(r"^%%MERMAID_\d+%%$", line.strip()):
            flush_paragraph(para_buf)
            html_parts.append(line.strip())
            i += 1
            continue

        if line.startswith("```"):
            flush_paragraph(para_buf)
            lang = line[3:].strip()
            cls = f' class="language-{lang}"' if lang else ""
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(md_escape(lines[i]))
                i += 1
            i += 1
            html_parts.append(f"<pre><code{cls}>" + "\n".join(code_lines) + "</code></pre>")
            continue

        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            flush_paragraph(para_buf)
            level = len(m.group(1))
            content = apply_inline(m.group(2))
            anchor = re.sub(r"[^\w\s-]", "", m.group(2).lower()).strip().replace(" ", "-")
            html_parts.append(f'<h{level} id="{anchor}">{content}</h{level}>')
            i += 1
            continue

        if re.match(r"^-{3,}$", line.strip()) or re.match(r"^\*{3,}$", line.strip()):
            flush_paragraph(para_buf)
            html_parts.append("<hr>")
            i += 1
            continue

        if "|" in line and i + 1 < len(lines) and re.match(r"^\|?[-:| ]+\|?$", lines[i + 1]):
            flush_paragraph(para_buf)
            header_cells = [c.strip() for c in line.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i]:
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            th_html = "".join(f"<th>{apply_inline(c)}</th>" for c in header_cells)
            table = f"<table><thead><tr>{th_html}</tr></thead><tbody>"
            for row in rows:
                td_html = "".join(f"<td>{apply_inline(c)}</td>" for c in row)
                table += f"<tr>{td_html}</tr>"
            table += "</tbody></table>"
            html_parts.append(table)
            continue

        if re.match(r"^[-*]\s+", line):
            flush_paragraph(para_buf)
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i]):
                items.append(apply_inline(lines[i][2:].strip()))
                i += 1
            html_parts.append("<ul>" + "".join(f"<li>{it}</li>" for it in items) + "</ul>")
            continue

        if re.match(r"^\d+\.\s+", line):
            flush_paragraph(para_buf)
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i]):
                items.append(apply_inline(re.sub(r"^\d+\.\s+", "", lines[i])))
                i += 1
            html_parts.append("<ol>" + "".join(f"<li>{it}</li>" for it in items) + "</ol>")
            continue

        if line.startswith(">"):
            flush_paragraph(para_buf)
            bq_lines = []
            while i < len(lines) and lines[i].startswith(">"):
                bq_lines.append(lines[i][1:].strip())
                i += 1
            inner = apply_inline(" ".join(bq_lines))
            html_parts.append(f"<blockquote><p>{inner}</p></blockquote>")
            continue

        if line.strip() == "":
            flush_paragraph(para_buf)
            i += 1
            continue

        para_buf.append(md_escape(line).strip())
        i += 1

    flush_paragraph(para_buf)
    return "\n".join(html_parts)


# ---------------------------------------------------------------------------
# Link rewriting
# ---------------------------------------------------------------------------

def rewrite_md_links(html):
    return re.sub(r'href="([^"]+)\.md([#"][^"]*)??"',
                  lambda m: f'href="{m.group(1)}.html{m.group(2) or ""}"', html)


# ---------------------------------------------------------------------------
# Search index
# ---------------------------------------------------------------------------

def _strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def build_search_index(out_dir):
    index = []
    for html_file in sorted(out_dir.glob("*.html")):
        if html_file.name == "index.html":
            continue
        raw = html_file.read_text(encoding="utf-8")
        art = re.search(r"<article>(.*?)</article>", raw, re.DOTALL)
        if not art:
            continue
        art_html = art.group(1)
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", art_html, re.IGNORECASE | re.DOTALL)
        title = _strip_tags(h1.group(1)) if h1 else html_file.stem
        headings = [
            {"text": _strip_tags(m.group(2)), "id": m.group(1)}
            for m in re.finditer(r'<h[23][^>]* id="([^"]+)"[^>]*>(.*?)</h[23]>',
                                 art_html, re.IGNORECASE | re.DOTALL)
        ]
        body = _strip_tags(art_html)
        index.append({"title": title, "url": html_file.name,
                      "headings": headings, "body": body})
    out = out_dir / "search-index.json"
    out.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"  search-index.json  ({len(index)} pages)")


# ---------------------------------------------------------------------------
# Sidebar and HTML template
# ---------------------------------------------------------------------------

def build_sidebar(active_file):
    lines = ['<nav id="sidebar" aria-label="Navigation">']
    lines.append('<input id="nav-search" type="search" placeholder="Search…" aria-label="Search documentation" autocomplete="off">')
    lines.append('<div id="search-results" style="display:none">')
    lines.append('<p id="search-no-results" style="display:none">No results found.</p>')
    lines.append('<ul id="search-results-list"></ul>')
    lines.append('</div>')
    for track_name, pages in SIDEBAR:
        has_active = any(filename == active_file for _, filename in pages)
        collapsed_attr = '' if has_active else ' data-collapsed="true"'
        lines.append(f'<div class="track"{collapsed_attr}>')
        lines.append(
            f'<button class="track-header" aria-expanded="{"true" if has_active else "false"}">'
            f'<span class="track-label">{track_name}</span>'
            f'<span class="track-arrow" aria-hidden="true">&#9660;</span>'
            f'</button>'
        )
        display = '' if has_active else ' style="display:none"'
        lines.append(f'<ul class="track-list"{display}>')
        for label, filename in pages:
            if filename == active_file:
                lines.append(
                    f'<li><a href="{filename}" aria-current="page"><strong>{label}</strong></a></li>'
                )
            else:
                lines.append(f'<li><a href="{filename}">{label}</a></li>')
        lines.append("</ul></div>")
    lines.append("</nav>")
    return "\n".join(lines)


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Zynthian Docs</title>
<link rel="stylesheet" href="style.css">
<script src="{mermaid_cdn}"></script>
<script>mermaid.initialize({{ startOnLoad: true, theme: 'base', themeVariables: {{
  primaryColor: '#0d2233', primaryTextColor: '#e0f0e0',
  primaryBorderColor: '#3db87a', lineColor: '#3db87a',
  secondaryColor: '#1a3a2a', tertiaryColor: '#0a2a1a',
  actorBkg: '#0d2233', actorTextColor: '#e0f0e0',
  actorBorder: '#3db87a', actorLineColor: '#3db87a',
  activationBkgColor: '#1a4a3a', activationBorderColor: '#3db87a',
  signalColor: '#3db87a', signalTextColor: '#0d2233',
  labelBoxBkgColor: '#0d2233', labelBoxBorderColor: '#3db87a', labelTextColor: '#e0f0e0',
  noteBkgColor: '#1a3a2a', noteTextColor: '#e0f0e0', noteBorderColor: '#3db87a',
  titleColor: '#e0f0e0',
  clusterBkg: '#1a3a2a', clusterBorder: '#3db87a', clusterTextColor: '#e0f0e0',
  fillType0: '#0d2233', fillType1: '#1a3a2a', fillType2: '#0a2a1a'
}} }});</script>
</head>
<body>
<header id="site-header">
  <a href="index.html">Zynthian</a> &mdash; User Documentation
</header>
<div id="layout">
{sidebar}
<main>
<article>
{content}
</article>
</main>
<div id="toc-column"></div>
</div>
<script src="search.js"></script>
<script src="ui.js"></script>
</body>
</html>
"""


def extract_title(html):
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    return "Zynthian"


# ---------------------------------------------------------------------------
# CSS — dark synth theme
# ---------------------------------------------------------------------------

CSS = """\
/* ============================================================
   Zynthian Documentation — Dark Synth Theme
   Deep navy · Terminal green · Dark slate
   ============================================================ */

*, *::before, *::after { box-sizing: border-box; }

body {
  margin: 0;
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  font-size: 16px;
  line-height: 1.72;
  background: #0a1520;
  color: #c8dcc8;
}

/* --- Header --- */
#site-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: #060f18;
  color: #3db87a;
  padding: 0.55rem 1.5rem;
  font-size: 0.82rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  border-bottom: 1px solid #3db87a;
  box-shadow: 0 2px 0 rgba(61,184,122,0.2);
}
#site-header a { color: #3db87a; text-decoration: none; }
#site-header a:hover { color: #5dda9a; }

/* --- Layout --- */
#layout { display: flex; min-height: calc(100vh - 42px); }

/* --- Sidebar --- */
#sidebar {
  width: 260px;
  flex-shrink: 0;
  background: #0d1e2d;
  border-right: 1px solid rgba(61,184,122,0.3);
  padding: 0.75rem 0 1.5rem;
  overflow-y: auto;
  position: sticky;
  top: 42px;
  height: calc(100vh - 42px);
}
#sidebar .track { margin-bottom: 0.25rem; }
.track-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: calc(100% - 2rem);
  margin: 0.85rem 1rem 0.35rem;
  padding: 0 0 0.3rem;
  background: none;
  border: none;
  border-bottom: 1px solid rgba(61,184,122,0.2);
  cursor: pointer;
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.22em;
  color: #3db87a;
  text-align: left;
}
.track-header:hover { color: #5dda9a; }
.track-arrow {
  font-size: 0.65rem;
  transition: transform 0.18s ease;
  flex-shrink: 0;
  margin-left: 0.3rem;
}
.track-header[aria-expanded="false"] .track-arrow { transform: rotate(-90deg); }
#sidebar ul { list-style: none; margin: 0; padding: 0; }
#sidebar .track-list { margin-bottom: 0.5rem; }
#sidebar li a {
  display: block;
  padding: 0.28rem 1rem;
  text-decoration: none;
  color: #7a9a8a;
  font-size: 0.875rem;
  transition: background 0.12s, color 0.12s;
}
#sidebar li a:hover { background: rgba(61,184,122,0.08); color: #5dda9a; }
#sidebar li a[aria-current="page"] {
  background: rgba(61,184,122,0.12);
  color: #3db87a;
  font-weight: 600;
  border-left: 2px solid #3db87a;
  padding-left: calc(1rem - 2px);
}

/* --- Search --- */
#nav-search {
  display: block;
  width: calc(100% - 2rem);
  margin: 0.7rem 1rem 0.8rem;
  padding: 0.32rem 0.6rem;
  border: 1px solid rgba(61,184,122,0.28);
  border-radius: 2px;
  font-size: 0.85rem;
  background: rgba(255,255,255,0.03);
  color: #9abaa0;
}
#nav-search::placeholder { color: rgba(154,186,160,0.35); }
#nav-search:focus { outline: 1px solid #3db87a; border-color: #3db87a; background: rgba(255,255,255,0.05); }
#search-results ul { list-style: none; margin: 0; padding: 0; }
#search-no-results { padding: 0.4rem 1rem; color: #4a6a50; font-size: 0.85rem; margin: 0; }
.search-result a { display: block; padding: 0.5rem 1rem; text-decoration: none; border-bottom: 1px solid rgba(61,184,122,0.1); }
.search-result a:hover, .result-focused a { background: rgba(61,184,122,0.08); }
.result-focused a { outline: 1px solid #3db87a; outline-offset: -1px; }
.result-title { display: block; font-weight: 600; font-size: 0.88rem; color: #5dda9a; }
.result-heading { display: block; font-size: 0.75rem; color: #3db87a; margin-top: 0.1rem; }
.result-excerpt { display: block; font-size: 0.78rem; color: #5a7a60; margin-top: 0.12rem; line-height: 1.4; }
mark { background: rgba(61,184,122,0.25); color: inherit; padding: 0 2px; border-radius: 1px; }

/* --- Main --- */
main {
  flex: 1;
  padding: 2rem 2.5rem;
  background: #101c28;
}

/* --- Article --- */
article {
  max-width: 820px;
  margin: 0 auto;
  padding: 2.5rem 2.75rem;
  background: #142030;
  border: 1px solid rgba(61,184,122,0.18);
  border-radius: 3px;
  box-shadow: 0 6px 32px rgba(0,0,0,0.4);
}

/* --- Headings --- */
h1, h2, h3, h4 { color: #e0f0e0; line-height: 1.3; font-weight: 600; }

h1 {
  font-size: 2rem;
  margin-top: 0;
  margin-bottom: 1.4rem;
}
h1::after {
  content: '';
  display: block;
  margin-top: 0.45rem;
  height: 2px;
  background: linear-gradient(to right, #3db87a 0%, #3db87a 40%, transparent 100%);
}

h2 {
  font-size: 1.35rem;
  margin-top: 2rem;
  margin-bottom: 0.65rem;
}
h2::after {
  content: '';
  display: block;
  margin-top: 0.25rem;
  height: 1px;
  background: linear-gradient(to right, rgba(61,184,122,0.6) 0%, rgba(61,184,122,0.1) 50%, transparent 100%);
}

h3 { font-size: 1.05rem; color: #9adaba; margin-top: 1.6rem; margin-bottom: 0.45rem; }
h4 { font-size: 0.95rem; color: #7abaa0; margin-top: 1.1rem; }

p { margin: 0 0 0.9rem; color: #b8d0b8; }

a { color: #3db87a; text-decoration: underline; text-decoration-color: rgba(61,184,122,0.3); }
a:hover { color: #5dda9a; text-decoration-color: rgba(93,218,154,0.6); }

/* --- HR --- */
hr {
  border: none;
  height: 1px;
  background: linear-gradient(to right, transparent 0%, rgba(61,184,122,0.4) 15%, rgba(61,184,122,0.4) 85%, transparent 100%);
  margin: 1.75rem 0;
}

/* --- Code --- */
pre, code { font-family: 'Fira Code', 'Cascadia Code', 'Consolas', 'Courier New', monospace; }
pre {
  background: #080f18;
  color: #a8e0c0;
  border-left: 2px solid #3db87a;
  border-radius: 0 2px 2px 0;
  padding: 0.9rem 1.1rem;
  overflow-x: auto;
  font-size: 0.84rem;
  line-height: 1.6;
  margin: 1.1rem 0;
}
code {
  background: rgba(61,184,122,0.1);
  color: #7adaaa;
  padding: 0.1em 0.32em;
  border-radius: 2px;
  font-size: 0.86em;
}
pre code { background: none; padding: 0; color: inherit; font-size: inherit; }

/* --- Tables --- */
table { border-collapse: collapse; width: 100%; margin: 1.1rem 0; font-size: 0.9rem; }
th {
  background: #0a1520;
  color: #3db87a;
  text-align: left;
  font-weight: 600;
  letter-spacing: 0.04em;
  font-size: 0.85rem;
}
th, td { padding: 0.42rem 0.8rem; border: 1px solid rgba(61,184,122,0.2); }
td { color: #b8d0b8; }
tr:nth-child(even) td { background: rgba(61,184,122,0.03); }
tr:hover td { background: rgba(61,184,122,0.07); }

/* --- Images --- */
img {
  max-width: 100%;
  border: 1px solid rgba(61,184,122,0.3);
  border-radius: 2px;
  box-shadow: 2px 4px 10px rgba(0,0,0,0.4);
  display: block;
  margin: 0.75rem 0;
}

/* --- Blockquote --- */
blockquote {
  border-left: 2px solid #3db87a;
  margin: 1.1rem 0;
  padding: 0.5rem 1rem;
  background: rgba(61,184,122,0.06);
  color: #7a9a80;
  font-style: italic;
}

/* --- Lists --- */
ul, ol { padding-left: 1.5rem; margin: 0.4rem 0 0.9rem; }
li { margin-bottom: 0.2rem; color: #b8d0b8; }

/* --- Mermaid --- */
.mermaid { margin: 1.4rem 0; }

/* --- Responsive --- */
@media (max-width: 900px) {
  #layout { flex-direction: column; }
  #sidebar { width: 100%; height: auto; position: static; border-right: none; border-bottom: 1px solid rgba(61,184,122,0.3); }
  #toc-column { display: none !important; }
  main { padding: 1rem; }
  article { padding: 1.25rem 1rem; }
}

/* --- Copy buttons --- */
.pre-wrap { position: relative; }
.copy-btn {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  background: rgba(61,184,122,0.08);
  color: #3db87a;
  border: 1px solid rgba(61,184,122,0.25);
  border-radius: 2px;
  padding: 0.16rem 0.5rem;
  font-size: 0.7rem;
  font-family: inherit;
  letter-spacing: 0.05em;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
  line-height: 1.6;
}
.copy-btn:hover { background: rgba(61,184,122,0.18); color: #5dda9a; }
.copy-btn.copied { background: rgba(61,184,122,0.2); color: #5dda9a; }

/* --- Anchor links --- */
.anchor-link {
  margin-left: 0.5em;
  color: rgba(61,184,122,0.35);
  text-decoration: none;
  font-size: 0.8em;
  font-weight: 400;
  vertical-align: middle;
}
.anchor-link:hover, .anchor-link.anchor-copied { color: #3db87a; }

/* --- TOC column (wide screens) --- */
#toc-column {
  width: 220px;
  flex-shrink: 0;
  padding: 1.5rem 0.75rem 1.5rem 0;
  display: none;
}
@media (min-width: 1280px) {
  #toc-column { display: block; }
}

/* --- TOC box --- */
#toc {
  background: #0d1e2d;
  border: 1px solid rgba(61,184,122,0.22);
  border-radius: 3px;
  padding: 0.6rem 0.8rem;
  font-size: 0.8rem;
  overflow-y: auto;
}
/* Sticky when in column */
#toc-column #toc {
  position: sticky;
  top: 58px;
  max-height: calc(100vh - 80px);
}
/* Fixed floating when toggled on narrow screens */
#toc.toc-floating {
  position: fixed;
  right: 1.5rem;
  top: 80px;
  width: 210px;
  max-height: calc(100vh - 120px);
  z-index: 10;
  display: none;
}
#toc.toc-floating.toc-visible { display: block; }
.toc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.toc-header-label {
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 0.62rem;
  color: #3db87a;
}
.toc-collapse-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: #3db87a;
  font-size: 0.75rem;
  padding: 0 0.1rem;
  line-height: 1;
  transition: transform 0.18s ease;
}
.toc-collapse-btn:hover { color: #5dda9a; }
#toc.toc-body-collapsed .toc-collapse-btn { transform: rotate(-90deg); }
#toc.toc-body-collapsed ul { display: none; }
#toc ul { list-style: none; margin: 0; padding: 0; }
#toc li a {
  display: block;
  color: #5a8070;
  text-decoration: none;
  padding: 0.18rem 0;
  line-height: 1.4;
  transition: color 0.1s;
}
#toc li a:hover, #toc li a.toc-active { color: #3db87a; }
#toc li.toc-h3 a { padding-left: 0.8rem; font-size: 0.75rem; }

/* Floating toggle button (narrow screens only) */
#toc-toggle {
  display: none;
  position: fixed;
  bottom: 1.2rem;
  right: 1.2rem;
  width: 40px; height: 40px;
  background: #0d1e2d;
  border: 1px solid #3db87a;
  border-radius: 50%;
  color: #3db87a;
  font-size: 1.1rem;
  cursor: pointer;
  z-index: 11;
  align-items: center;
  justify-content: center;
}
@media (max-width: 1279px) {
  #toc-toggle { display: flex; }
}
"""


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

SEARCH_JS = """\
(function () {
  'use strict';

  var input  = document.getElementById('nav-search');
  if (!input) return;

  var panel  = document.getElementById('search-results');
  var list   = document.getElementById('search-results-list');
  var noRes  = document.getElementById('search-no-results');
  var tracks = document.querySelectorAll('#sidebar .track');

  var index      = null;
  var pending    = null;
  var focusIndex = -1;

  function loadIndex() {
    if (index)   return Promise.resolve();
    if (pending) return pending;
    pending = fetch('search-index.json')
      .then(function (r) { return r.json(); })
      .then(function (data) { index = data; pending = null; });
    return pending;
  }

  function escapeRe(s) {
    return s.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
  }

  function highlight(text, words) {
    if (!words.length) return text;
    var re = new RegExp('(' + words.map(escapeRe).join('|') + ')', 'gi');
    return text.replace(re, '<mark>$1</mark>');
  }

  function excerpt(body, words) {
    var idx = -1;
    for (var i = 0; i < words.length; i++) {
      var p = body.toLowerCase().indexOf(words[i].toLowerCase());
      if (p !== -1) { idx = p; break; }
    }
    var start = Math.max(0, idx === -1 ? 0 : idx - 60);
    var end   = Math.min(body.length, start + 160);
    return (start > 0 ? '\\u2026' : '') +
           highlight(body.slice(start, end), words) +
           (end < body.length ? '\\u2026' : '');
  }

  function scoreItem(item, words) {
    var s  = 0;
    var tl = item.title.toLowerCase();
    var hl = item.headings.map(function (h) { return h.text; }).join(' ').toLowerCase();
    var bl = item.body.toLowerCase();
    words.forEach(function (w) {
      var wl = w.toLowerCase();
      if (tl.includes(wl)) s += 10;
      if (hl.includes(wl)) s +=  5;
      if (bl.includes(wl)) s +=  1;
    });
    return s;
  }

  function setFocus(idx) {
    var items = list.querySelectorAll('.search-result');
    if (focusIndex >= 0 && focusIndex < items.length)
      items[focusIndex].classList.remove('result-focused');
    focusIndex = Math.max(0, Math.min(idx, items.length - 1));
    if (items.length) {
      items[focusIndex].classList.add('result-focused');
      items[focusIndex].scrollIntoView({ block: 'nearest' });
    }
  }

  input.addEventListener('keydown', function (e) {
    var items = list.querySelectorAll('.search-result');
    if (!items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setFocus(focusIndex < 0 ? 0 : focusIndex + 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setFocus(focusIndex <= 0 ? 0 : focusIndex - 1);
    } else if (e.key === 'Enter' && focusIndex >= 0) {
      e.preventDefault();
      var link = items[focusIndex].querySelector('a');
      if (link) window.location.href = link.href;
    } else if (e.key === 'Escape') {
      input.value = '';
      showPanel(false);
    }
  });

  function showPanel(show) {
    panel.style.display = show ? '' : 'none';
    tracks.forEach(function (t) { t.style.display = show ? 'none' : ''; });
    if (!show) focusIndex = -1;
  }

  function renderResults(results, words) {
    list.innerHTML = '';
    focusIndex = -1;
    if (!results.length) { noRes.style.display = ''; return; }
    noRes.style.display = 'none';
    results.forEach(function (item) {
      var matchHeading = null;
      item.headings.forEach(function (h) {
        if (!matchHeading &&
            words.some(function (w) { return h.text.toLowerCase().includes(w.toLowerCase()); })) {
          matchHeading = h;
        }
      });
      var href = matchHeading ? item.url + '#' + matchHeading.id : item.url;
      var li   = document.createElement('li');
      li.className = 'search-result';
      li.innerHTML =
        '<a href="' + href + '">' +
        '<span class="result-title">'   + highlight(item.title, words) + '</span>' +
        (matchHeading
          ? '<span class="result-heading">\\u00a7\\u00a0' + highlight(matchHeading.text, words) + '</span>'
          : '') +
        '<span class="result-excerpt">' + excerpt(item.body, words) + '</span>' +
        '</a>';
      list.appendChild(li);
    });
  }

  input.addEventListener('input', function () {
    var q = input.value.trim();
    if (!q) { showPanel(false); return; }
    var words = q.split(/\\s+/).filter(Boolean);
    loadIndex().then(function () {
      var results = index
        .map(function (item) { return { item: item, s: scoreItem(item, words) }; })
        .filter(function (r) { return r.s > 0; })
        .sort(function (a, b) { return b.s - a.s; })
        .slice(0, 12)
        .map(function (r) { return r.item; });
      renderResults(results, words);
      showPanel(true);
    });
  });
}());
"""


UI_JS = """\
(function () {
  'use strict';

  function headingText(h) {
    return Array.from(h.childNodes)
      .filter(function (n) { return n.nodeType === 3; })
      .map(function (n) { return n.textContent; })
      .join('').trim();
  }

  function flashClass(el, cls, ms) {
    el.classList.add(cls);
    setTimeout(function () { el.classList.remove(cls); }, ms || 1500);
  }

  function copyText(text, onDone) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(onDone).catch(function () {});
    } else {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); onDone(); } catch (e) {}
      document.body.removeChild(ta);
    }
  }

  /* ---- 1. Copy buttons ---- */

  function initCopyButtons() {
    document.querySelectorAll('pre').forEach(function (pre) {
      var wrap = document.createElement('div');
      wrap.className = 'pre-wrap';
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);

      var btn = document.createElement('button');
      btn.className = 'copy-btn';
      btn.setAttribute('aria-label', 'Copy code');
      btn.textContent = 'Copy';
      wrap.appendChild(btn);

      btn.addEventListener('click', function () {
        var code = pre.querySelector('code');
        copyText((code || pre).textContent, function () {
          btn.textContent = 'Copied!';
          flashClass(btn, 'copied', 2000);
          setTimeout(function () { btn.textContent = 'Copy'; }, 2000);
        });
      });
    });
  }

  /* ---- 2. Heading anchor links ---- */

  function initAnchorLinks() {
    var article = document.querySelector('article');
    if (!article) return;
    article.querySelectorAll('h2[id], h3[id], h4[id]').forEach(function (h) {
      var a = document.createElement('a');
      a.className = 'anchor-link';
      a.href = '#' + h.id;
      a.setAttribute('aria-label', 'Link to this section');
      a.textContent = '\\u00a7';
      h.appendChild(a);
      a.addEventListener('click', function (e) {
        e.preventDefault();
        history.pushState(null, '', '#' + h.id);
        copyText(location.href, function () { flashClass(a, 'anchor-copied'); });
      });
    });
  }

  /* ---- 3. TOC ---- */

  function initTOC() {
    var article = document.querySelector('article');
    if (!article) return;
    var headings = Array.from(article.querySelectorAll('h2[id], h3[id]'));
    if (headings.length < 3) return;

    var nav = document.createElement('nav');
    nav.id = 'toc';
    nav.setAttribute('aria-label', 'Page contents');

    /* Header with collapse toggle */
    var hdr = document.createElement('div');
    hdr.className = 'toc-header';
    var lbl = document.createElement('span');
    lbl.className = 'toc-header-label';
    lbl.textContent = 'Contents';
    var collapseBtn = document.createElement('button');
    collapseBtn.className = 'toc-collapse-btn';
    collapseBtn.setAttribute('aria-label', 'Collapse contents');
    collapseBtn.setAttribute('aria-expanded', 'true');
    collapseBtn.textContent = '\\u25be';
    hdr.appendChild(lbl);
    hdr.appendChild(collapseBtn);
    nav.appendChild(hdr);

    collapseBtn.addEventListener('click', function () {
      var collapsed = nav.classList.toggle('toc-body-collapsed');
      collapseBtn.setAttribute('aria-expanded', !collapsed);
    });

    var ul = document.createElement('ul');
    headings.forEach(function (h) {
      var li = document.createElement('li');
      li.className = h.tagName === 'H3' ? 'toc-h3' : 'toc-h2';
      var a = document.createElement('a');
      a.href = '#' + h.id;
      a.textContent = headingText(h);
      a.dataset.id = h.id;
      li.appendChild(a);
      ul.appendChild(li);
    });
    nav.appendChild(ul);

    /* Place in column if available, else floating */
    var col = document.getElementById('toc-column');
    if (col) {
      col.appendChild(nav);
    } else {
      nav.classList.add('toc-floating');
      document.body.appendChild(nav);
    }

    /* Floating toggle button (visible only on narrow via CSS) */
    var btn = document.createElement('button');
    btn.id = 'toc-toggle';
    btn.setAttribute('aria-label', 'Table of contents');
    btn.textContent = '\\u2630';
    document.body.appendChild(btn);
    btn.addEventListener('click', function () {
      if (col && col.offsetParent !== null) return; /* column visible, button inactive */
      nav.classList.add('toc-floating');
      nav.classList.toggle('toc-visible');
    });
    nav.addEventListener('click', function (e) {
      if (e.target.tagName === 'A') nav.classList.remove('toc-visible');
    });

    var active = null;
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          if (active) active.classList.remove('toc-active');
          active = ul.querySelector('a[data-id="' + entry.target.id + '"]');
          if (active) active.classList.add('toc-active');
        }
      });
    }, { rootMargin: '-10% 0px -80% 0px', threshold: 0 });
    headings.forEach(function (h) { observer.observe(h); });
  }

  /* ---- 4. Sidebar collapse ---- */

  function initSidebarCollapse() {
    document.querySelectorAll('.track-header').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var list = btn.nextElementSibling;
        var expanded = btn.getAttribute('aria-expanded') === 'true';
        if (expanded) {
          list.style.display = 'none';
          btn.setAttribute('aria-expanded', 'false');
        } else {
          list.style.display = '';
          btn.setAttribute('aria-expanded', 'true');
        }
      });
    });
  }

  /* ---- init ---- */

  document.addEventListener('DOMContentLoaded', function () {
    initCopyButtons();
    initAnchorLinks();
    initTOC();
    initSidebarCollapse();
  });
}());
"""


# ---------------------------------------------------------------------------
# Status board — generated from MD/inwork.md, todo.md, done.md
# ---------------------------------------------------------------------------

_STATUS_MAP = {
    'x': ('status-done',     'Done'),
    '>': ('status-pr',       'Needs PR'),
    't': ('status-testing',  'Testing'),
    '~': ('status-partial',  'In Progress'),
    '/': ('status-started',  'Started'),
    ' ': ('status-todo',     'Todo'),
}

_STATUS_CSS = """\
.sb-section { margin-bottom: 2rem; }
.sb-section h2 { font-size: 1.15rem; color: #9adaba; margin-bottom: 0.75rem; }
.sb-items { display: flex; flex-direction: column; gap: 0.35rem; }
.sb-item { display: flex; align-items: flex-start; gap: 0.75rem; padding: 0.4rem 0.6rem;
  border: 1px solid rgba(61,184,122,0.14); border-radius: 2px;
  background: rgba(61,184,122,0.03); }
.sb-badge { flex-shrink: 0; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; padding: 0.18rem 0.5rem; border-radius: 2px; margin-top: 0.1rem; }
.status-done     { background: rgba(61,184,122,0.18); color: #5dda9a; }
.status-pr       { background: rgba(255,200,80,0.18); color: #ffc850; }
.status-testing  { background: rgba(80,160,255,0.18); color: #60b0ff; }
.status-partial  { background: rgba(200,120,60,0.18); color: #e8904a; }
.status-started  { background: rgba(180,90,220,0.18); color: #c870e0; }
.status-todo     { background: rgba(140,140,140,0.14); color: #8a9a8a; }
.sb-text { color: #b8d0b8; font-size: 0.9rem; line-height: 1.5; }
.sb-stats { margin-bottom: 1.5rem; padding: 0.75rem 1rem; background: rgba(61,184,122,0.05);
  border: 1px solid rgba(61,184,122,0.18); border-radius: 2px;
  display: flex; gap: 1.5rem; flex-wrap: wrap; font-size: 0.85rem; }
.sb-stat { color: #9adaba; }
.sb-stat span { color: #3db87a; font-weight: 700; font-size: 1rem; }
"""


def _parse_md_items(md_path):
    """Parse a tracking MD file → [(section, status_cls, status_label, text), ...]"""
    if not md_path.exists():
        return []
    items = []
    current_section = "General"
    for line in md_path.read_text(encoding="utf-8").splitlines():
        h = re.match(r'^#{1,3}\s+(.+)', line)
        if h:
            current_section = h.group(1).strip()
            continue
        m = re.match(r'^- \[([x>t~ /])\] (.*)', line)
        if not m:
            continue
        char = m.group(1)
        text = re.sub(r'\*\*\[[^\]]+\]\*\*', '', m.group(2)).strip()
        cls, label = _STATUS_MAP.get(char, ('status-todo', 'Todo'))
        items.append((current_section, cls, label, text))
    return items


def build_status_html():
    """Generate status.html from MD/inwork.md, todo.md, and done.md."""
    md_dir = REPO_ROOT / "MD"

    inwork_items = _parse_md_items(md_dir / "inwork.md")
    todo_items   = _parse_md_items(md_dir / "todo.md")
    done_items   = _parse_md_items(md_dir / "done.md")

    all_items = inwork_items + todo_items + done_items
    n_done    = sum(1 for _, cls, _, _ in all_items if cls == 'status-done')
    n_active  = sum(1 for _, cls, _, _ in all_items if cls in ('status-partial', 'status-testing', 'status-started'))
    n_pr      = sum(1 for _, cls, _, _ in all_items if cls == 'status-pr')
    n_todo    = sum(1 for _, cls, _, _ in all_items if cls == 'status-todo')

    p = []
    p.append('<h1 id="sprint-board">Sprint Board</h1>')
    p.append(f'<div class="sb-stats">'
             f'<div class="sb-stat">Active <span>{n_active}</span></div>'
             f'<div class="sb-stat">Needs PR <span>{n_pr}</span></div>'
             f'<div class="sb-stat">Todo <span>{n_todo}</span></div>'
             f'<div class="sb-stat">Done <span>{n_done}</span></div>'
             f'</div>')

    def _render_section(title, items):
        if not items:
            return
        p.append(f'<div class="sb-section"><h2>{_html.escape(title)}</h2><div class="sb-items">')
        for section, cls, label, text in items:
            p.append(
                f'<div class="sb-item">'
                f'<span class="sb-badge {cls}">{label}</span>'
                f'<span class="sb-text">{_html.escape(text)}</span>'
                f'</div>'
            )
        p.append('</div></div>')

    _render_section("In Work", inwork_items)
    _render_section("Backlog", todo_items)
    _render_section("Done", done_items)

    if not any([inwork_items, todo_items, done_items]):
        p.append('<p>No tracking files found in MD/. Add items to <code>MD/inwork.md</code> to populate this board.</p>')

    content = '\n'.join(p)
    sidebar_html = build_sidebar('status.html')
    extra_css = f'<style>\n{_STATUS_CSS}\n</style>'

    full_html = HTML_TEMPLATE.format(
        title='Sprint Board',
        mermaid_cdn=MERMAID_CDN,
        sidebar=sidebar_html,
        content=extra_css + '\n' + content,
    )
    (OUT_DIR / 'status.html').write_text(full_html, encoding='utf-8')
    print(f"  status.html  ({len(inwork_items)} active · {len(todo_items)} todo · {len(done_items)} done)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def convert_file(md_path, out_dir):
    raw = md_path.read_text(encoding="utf-8")
    tokenised, mermaid_blocks = extract_mermaid(raw)
    body_html = convert_md(tokenised)
    body_html = rewrite_md_links(body_html)
    body_html = restore_mermaid(body_html, mermaid_blocks)

    out_filename = md_path.stem + ".html"
    title = extract_title(body_html)
    sidebar_html = build_sidebar(out_filename)

    full_html = HTML_TEMPLATE.format(
        title=title,
        mermaid_cdn=MERMAID_CDN,
        sidebar=sidebar_html,
        content=body_html,
    )

    (out_dir / out_filename).write_text(full_html, encoding="utf-8")
    print(f"  {md_path.name} → {out_filename}")
    return out_filename


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "style.css").write_text(CSS, encoding="utf-8")

    converted = []
    for md_file in sorted(SRC_DIR.glob("*.md")):
        converted.append(convert_file(md_file, OUT_DIR))

    landing = OUT_DIR / "01-what-it-is.html"
    if landing.exists():
        shutil.copy(landing, OUT_DIR / "index.html")
        print("  01-what-it-is.html → index.html (copy)")

    for img in SRC_DIR.glob("*.png"):
        shutil.copy(img, OUT_DIR / img.name)

    images_src = SRC_DIR / "images"
    if images_src.is_dir():
        images_dst = OUT_DIR / "images"
        if images_dst.exists():
            shutil.rmtree(images_dst)
        shutil.copytree(images_src, images_dst)

    (OUT_DIR / "search.js").write_text(SEARCH_JS, encoding="utf-8")
    (OUT_DIR / "ui.js").write_text(UI_JS, encoding="utf-8")
    # The sprint board reads MD/inwork.md, todo.md and done.md, which exist only
    # in the zynth-docs repository this generator came from.
    if (REPO_ROOT / "MD").is_dir():
        build_status_html()
    build_search_index(OUT_DIR)

    print(f"\nDone. {len(converted)} pages → {OUT_DIR}/index.html")


if __name__ == "__main__":
    main()
