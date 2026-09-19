"""Render docs/WRITEUP.md into the published HTML page.

The Markdown is the source of truth; this adds the page design, draws the solved grid
(regions coloured, stars placed) in place of the ASCII grid, and draws the region map
in place of its ASCII block.

    python -m tools.writeup.render OUT.html            # Claude artifact (body only, web fonts)
    python -m tools.writeup.render --site OUT.html     # theelementalcodices.com/artifacts/: a full
                                                       # document, system fonts, no external requests
"""

import html
import re
import sys

import markdown

SRC = "docs/WRITEUP.md"
TITLE = "Retracing Two Stars"

CSS = """
:root {
  --ground: #f3f4f1; --surface: #fbfbf9; --ink: #15181c; --muted: #5b6168; --rule: #d5d8d2;
  --accent: #0e6f69; --accent-soft: #dcebe8; --warn: #b4441a; --code-bg: #e9ebe6;
  --star: #15181c;
  --r0: #e7d9c4; --r1: #cfe0d6; --r2: #e4cfd6; --r3: #d3d9ea; --r4: #eadfb8; --r5: #d8e7c3;
  --r6: #ddd4e8; --r7: #c9e2e4; --r8: #ecd3c3; --r9: #e2e4d0; --r10: #d6ccc0;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground: #0e1113; --surface: #14181b; --ink: #e4e7e2; --muted: #9aa1a7; --rule: #2a3034;
    --accent: #4fc1b7; --accent-soft: #16302e; --warn: #f08a55; --code-bg: #1a1f22; --star: #f4f1e6;
    --r0: #4a3f2e; --r1: #2c4438; --r2: #4a3139; --r3: #313a54; --r4: #4d4426; --r5: #3a4a2a;
    --r6: #3f3552; --r7: #26464a; --r8: #533a2c; --r9: #43452f; --r10: #463c33;
  }
}
:root[data-theme="dark"] {
  --ground: #0e1113; --surface: #14181b; --ink: #e4e7e2; --muted: #9aa1a7; --rule: #2a3034;
  --accent: #4fc1b7; --accent-soft: #16302e; --warn: #f08a55; --code-bg: #1a1f22; --star: #f4f1e6;
  --r0: #4a3f2e; --r1: #2c4438; --r2: #4a3139; --r3: #313a54; --r4: #4d4426; --r5: #3a4a2a;
  --r6: #3f3552; --r7: #26464a; --r8: #533a2c; --r9: #43452f; --r10: #463c33;
}
body { background: var(--ground); color: var(--ink); font-family: "Source Serif 4", Georgia, "Times New Roman", serif;
  font-size: 17px; line-height: 1.6; }
.wrap { max-width: 1080px; margin: 0 auto; padding-inline: 20px; padding-block: 40px 72px; }
.eyebrow { font-family: "JetBrains Mono", ui-monospace, Menlo, monospace; font-size: 12px; letter-spacing: .08em;
  text-transform: uppercase; color: var(--muted); }
h1, h2, h3 { font-family: "Archivo Narrow", "Arial Narrow", "Helvetica Neue", sans-serif; font-weight: 600;
  text-wrap: balance; line-height: 1.15; }
h1 { font-size: clamp(34px, 5.2vw, 56px); margin: 10px 0 0; letter-spacing: -.01em; }
.hero { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 40px; align-items: center;
  padding-block: 8px 36px; border-bottom: 1px solid var(--rule); }
.answer { font-family: "JetBrains Mono", ui-monospace, Menlo, monospace; font-size: clamp(22px, 3.2vw, 32px);
  color: var(--accent); margin: 22px 0 12px; }
.lede { max-width: 58ch; color: var(--muted); margin: 0; }
.facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 28px; margin: 26px 0 0;
  max-width: 520px; }
.facts div { border-top: 1px solid var(--rule); padding-top: 8px; }
.facts b { display: block; font-family: "Archivo Narrow", "Arial Narrow", sans-serif; font-size: 26px; font-weight: 600;
  font-variant-numeric: tabular-nums; }
.facts span { font-size: 13px; color: var(--muted); }
.board { --cell: min(30px, 6.4vw); display: grid; grid-template-columns: repeat(11, var(--cell)); gap: 0;
  border: 2px solid var(--ink); }
.board i { width: var(--cell); height: var(--cell); display: grid; place-items: center; font-style: normal;
  font-size: calc(var(--cell) * .62); line-height: 1; color: var(--star); box-sizing: border-box; }
.board i.bt { border-top: 2px solid var(--ink); } .board i.bl { border-left: 2px solid var(--ink); }
.board-cap { font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 12px; color: var(--muted);
  margin-top: 8px; text-align: center; }
.region-map { margin: 18px 0 8px; display: flex; flex-direction: column; align-items: flex-start; }
.region-map .board i { font-family: "JetBrains Mono", ui-monospace, monospace; font-size: calc(var(--cell) * .42);
  color: var(--ink); }
article { max-width: 68ch; margin: 40px auto 0; }
article h2 { font-size: 30px; margin: 56px 0 12px; padding-top: 14px; border-top: 1px solid var(--rule); }
article h1 { display: none; }
article p, article li { hyphens: auto; }
article a { color: var(--accent); text-underline-offset: 3px; }
article strong { font-weight: 650; }
article code { font-family: "JetBrains Mono", ui-monospace, Menlo, monospace; font-size: .84em; background: var(--code-bg);
  padding: .08em .32em; border-radius: 3px; }
article pre { background: var(--surface); border: 1px solid var(--rule); border-radius: 4px; padding: 14px 16px;
  overflow-x: auto; line-height: 1.45; }
article pre code { background: none; padding: 0; font-size: 13.5px; }
.table { overflow-x: auto; margin: 18px 0; }
article table { border-collapse: collapse; font-size: 15px; width: 100%; font-variant-numeric: tabular-nums; }
article th, article td { text-align: left; vertical-align: top; padding: 7px 12px 7px 0; border-bottom: 1px solid var(--rule); }
article th { font-family: "Archivo Narrow", "Arial Narrow", sans-serif; font-weight: 600; font-size: 14px;
  letter-spacing: .03em; text-transform: uppercase; color: var(--muted); }
article em { color: var(--muted); }
article p:first-of-type em { display: block; }
footer { max-width: 68ch; margin: 64px auto 0; color: var(--muted); font-size: 14px; border-top: 1px solid var(--rule);
  padding-top: 14px; }
@media (max-width: 760px) {
  .hero { grid-template-columns: minmax(0, 1fr); gap: 24px; }
  .hero .board-wrap { justify-self: start; }
  body { font-size: 16px; }
}
@media (prefers-reduced-motion: no-preference) {
  .board i.star { animation: glint .6s ease-out both; }
  @keyframes glint { from { transform: scale(.4); } to { transform: scale(1); } }
}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo+Narrow:wght@500;600'
         '&family=JetBrains+Mono:wght@400;500&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,650;1,8..60,400'
         '&display=swap">')


STAR_SVG = ('<svg viewBox="0 0 24 24" width="72%" height="72%" aria-hidden="true">'
            '<path fill="currentColor" d="M12 2.2l2.95 6.6 7.2.7-5.45 4.8 1.6 7.05L12 17.6l-6.3 3.75 1.6-7.05'
            'L1.85 9.5l7.2-.7z"/></svg>')


def _blocks(md):
    return re.findall(r"```\n(.*?)\n```", md, re.S)


def board(regions, stars=None, label_regions=False):
    """11x11 grid: fill by region, thick borders between regions, optional stars."""
    letters = sorted({c for row in regions for c in row})
    idx = {c: i for i, c in enumerate(letters)}
    cells = []
    for r in range(11):
        for c in range(11):
            reg = regions[r][c]
            cls = []
            if r == 0 or regions[r - 1][c] != reg:
                cls.append("bt")
            if c == 0 or regions[r][c - 1] != reg:
                cls.append("bl")
            star = stars is not None and stars[r][c] == "*"
            if star:
                cls.append("star")
            text = STAR_SVG if star else (reg if label_regions else "")
            aria = f"row {r} column {c}, region {reg}" + (", star" if star else "")
            cells.append(f'<i class="{" ".join(cls)}" style="background:var(--r{idx[reg]})" '
                         f'role="img" aria-label="{aria}">{text}</i>')
    return f'<div class="board" role="group" aria-label="11 by 11 grid">{"".join(cells)}</div>'


SYSTEM_FONTS = {
    '"Source Serif 4", Georgia, "Times New Roman", serif':
        'ui-serif, "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, "Times New Roman", serif',
    '"Archivo Narrow", "Arial Narrow", "Helvetica Neue", sans-serif':
        '"Avenir Next Condensed", "Arial Narrow", ui-sans-serif, -apple-system, "Segoe UI", sans-serif',
    '"Archivo Narrow", "Arial Narrow", sans-serif':
        '"Avenir Next Condensed", "Arial Narrow", ui-sans-serif, -apple-system, "Segoe UI", sans-serif',
    '"JetBrains Mono", ui-monospace, Menlo, monospace': 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
    '"JetBrains Mono", ui-monospace, monospace': 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
}
DESCRIPTION = ("How RETRACE reverse-engineered Jane Street's ASIC puzzle from a name-stripped GDS to a proven, "
               "unique solution, and what the method developed along the way.")


def render(site=False):
    with open(SRC) as f:
        md = f.read()
    blocks = _blocks(md)
    grid_block = next(b for b in blocks if set(b.replace(" ", "").replace("\n", "")) <= {".", "*"})
    region_block = next(b for b in blocks if re.fullmatch(r"([A-K] ){10}[A-K](\n([A-K] ){10}[A-K]){10}", b.strip()))
    stars = [row.split() for row in grid_block.strip().split("\n")]
    regions = [row.split() for row in region_block.strip().split("\n")]

    # drop the ASCII grid (the hero draws it) and replace the region map with a drawn one
    md = md.replace(f"```\n{grid_block}\n```\n", "", 1)
    md = md.replace(f"```\n{region_block}\n```", "REGION_MAP_PLACEHOLDER", 1)
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "toc"])
    body = body.replace("<p>REGION_MAP_PLACEHOLDER</p>",
                        f'<div class="region-map">{board(regions, label_regions=True)}'
                        f'<div class="board-cap">regions A-K, as decoded from the array block</div></div>')
    body = re.sub(r"<table>", '<div class="table"><table>', body)
    body = re.sub(r"</table>", "</table></div>", body)

    hero = f"""
<header class="hero">
  <div>
    <div class="eyebrow">RETRACE &middot; Jane Street ASIC puzzle &middot; writeup</div>
    <h1>{html.escape(TITLE)}</h1>
    <p class="answer">(* TWO STARS *)</p>
    <p class="lede">A 728-cell SKY130 layout with its names stripped, turned back into a netlist, readable RTL and
    an 11&times;11 Star Battle checker, then solved two independent ways. Every stage has its own oracle.</p>
    <div class="facts">
      <div><b>728</b><span>logic cells, 92 flops, recovered from geometry</span></div>
      <div><b>719/719</b><span>nets identical in two independent extractors</span></div>
      <div><b>130</b><span>layout mutants: 90 killed, 39 equivalent, 1 explained</span></div>
      <div><b>1</b><span>solution, unique over every input sequence</span></div>
    </div>
  </div>
  <div class="board-wrap">{board(regions, stars)}<div class="board-cap">the only accepted grid</div></div>
</header>"""
    footer = "Generated from <code>docs/WRITEUP.md</code> by <code>tools/writeup/render.py</code>."
    desc = html.escape(DESCRIPTION)
    if not site:
        return f"""<title>{html.escape(TITLE)}</title>
<meta name="description" content="{desc}">
{FONTS}
<style>{CSS}</style>
<div class="wrap">
{hero}
<article>
{body}
</article>
<footer>{footer}</footer>
</div>
"""
    css = CSS
    for web, system in SYSTEM_FONTS.items():
        css = css.replace(web, system)
    css += (".back { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; letter-spacing: .08em;\n"
            "  text-transform: uppercase; color: var(--muted); text-decoration: none; }\n"
            ".back:hover { color: var(--accent); }\n")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="description" content="{desc}">
<meta property="og:title" content="{html.escape(TITLE)}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<title>{html.escape(TITLE)}</title>
<!-- No external requests: system font stacks, inline SVG, no scripts. -->
<style>{css}</style>
</head>
<body>
<div class="wrap">
<a class="back" href="/artifacts/">&larr; The Elemental Codices &middot; Artifacts</a>
{hero}
<article>
{body}
</article>
<footer>{footer}</footer>
</div>
</body>
</html>
"""


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    site = "--site" in argv
    argv = [a for a in argv if a != "--site"]
    out = argv[0] if argv else "out/writeup/index.html"
    with open(out, "w") as f:
        f.write(render(site))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
