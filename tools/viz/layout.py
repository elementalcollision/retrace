"""Layout overlays (PRD S1): a die drawn as small multiples, one panel per group of cells.

A panel shows every cell of the design in a recessive tone and one group (a recovered
block, an RTL module, the cells an LVS check flagged) in a single highlight colour, so
identity comes from the panel title, never from telling hues apart. Coordinates are in
um, GDS convention (y up); both renderers flip to image convention (y down).

  svg_panels(...)   inline SVG, coloured through CSS variables with fallbacks, so the
                    same markup follows the writeup's light and dark themes and still
                    renders on its own (GitHub, a browser)
  png_panel(...)    one panel as a PNG (Pillow), for designs too large for inline SVG
  png_sheet(...)    several PNG panels on one sheet with titles, for standalone use
"""

import html
import math

# PNG colours: a light sheet (standalone use) and a transparent, theme-neutral panel
# (embedded in a page that has its own light and dark backgrounds)
LIGHT = {"sheet": (251, 251, 249, 255), "die": (243, 244, 241, 255), "edge": (160, 166, 160, 255),
         "cell": (201, 205, 199, 255), "hi": (14, 111, 105, 255), "macro": (226, 228, 223, 255),
         "ink": (21, 24, 28, 255), "muted": (91, 97, 104, 255), "flag": (208, 59, 59, 255),
         "halo": (255, 255, 255, 230)}
NEUTRAL = {"sheet": (0, 0, 0, 0), "die": (128, 134, 138, 28), "edge": (128, 134, 138, 150),
           "cell": (128, 134, 138, 110), "hi": (26, 145, 135, 255), "macro": (128, 134, 138, 45),
           "ink": (128, 134, 138, 255), "muted": (128, 134, 138, 255), "flag": (208, 59, 59, 255)}


class Die:
    """The die outline, every cell rectangle (um) by name, and any macros to outline."""

    def __init__(self, width, height, cells, macros=()):
        self.width, self.height = width, height
        self.cells = cells  # {name: (x0, y0, x1, y1)}
        self.macros = list(macros)  # [(label, (x0, y0, x1, y1))]


def _path(rects, height, scale=1.0, nd=2):
    """One SVG path for many rectangles (y flipped); far smaller than one <rect> each."""
    out = []
    for x0, y0, x1, y1 in rects:
        out.append(f"M{x0 * scale:.{nd}f} {(height - y1) * scale:.{nd}f}h{(x1 - x0) * scale:.{nd}f}"
                   f"v{(y1 - y0) * scale:.{nd}f}h{-(x1 - x0) * scale:.{nd}f}z")
    return "".join(out)


def svg_panels(die, panels, cols=4, panel_w=180, gap=18, title_h=34, label="layout panels", min_px=1.2):
    """Small multiples as one inline SVG. `panels` is [(title, subtitle, [cell names])].
    Cells smaller than `min_px` on screen are grown to it, so a lone cell stays visible."""
    s = panel_w / die.width
    ph = die.height * s
    rows = math.ceil(len(panels) / cols)
    w = cols * panel_w + (cols - 1) * gap
    h = rows * (ph + title_h) + (rows - 1) * gap

    def grow(r):
        x0, y0, x1, y1 = r
        dx = max(0.0, min_px / s - (x1 - x0)) / 2
        dy = max(0.0, min_px / s - (y1 - y0)) / 2
        return x0 - dx, y0 - dy, x1 + dx, y1 + dy

    base = _path((grow(r) for r in die.cells.values()), die.height, s)
    parts = [f'<svg class="lo" viewBox="0 0 {w:.0f} {h:.0f}" role="img" aria-label="{html.escape(label)}" '
             f'xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;max-width:{w:.0f}px">',
             f'<defs><path id="lo-cells" d="{base}"/></defs>']
    for k, (title, sub, names) in enumerate(panels):
        r, c = divmod(k, cols)
        ox, oy = c * (panel_w + gap), r * (ph + title_h + gap)
        parts.append(f'<g transform="translate({ox:.1f} {oy:.1f})">')
        parts.append(f'<text x="0" y="13" style="fill:var(--ink,#15181c);font:600 13px ui-monospace,Menlo,monospace">'
                     f'{html.escape(title)}</text>')
        parts.append(f'<text x="0" y="28" style="fill:var(--muted,#5b6168);font:12px ui-monospace,Menlo,monospace">'
                     f'{html.escape(sub)}</text>')
        parts.append(f'<g transform="translate(0 {title_h})">')
        parts.append(f'<rect width="{panel_w:.1f}" height="{ph:.1f}" style="fill:var(--surface,#fbfbf9);'
                     f'stroke:var(--rule,#d5d8d2);stroke-width:1"/>')
        for _lbl, (x0, y0, x1, y1) in die.macros:
            parts.append(f'<rect x="{x0 * s:.1f}" y="{(die.height - y1) * s:.1f}" width="{(x1 - x0) * s:.1f}" '
                         f'height="{(y1 - y0) * s:.1f}" style="fill:none;stroke:var(--muted,#5b6168);'
                         f'stroke-dasharray:3 2;stroke-width:1"/>')
        parts.append('<use href="#lo-cells" style="fill:var(--rule,#d5d8d2)"/>')
        hi = _path((grow(die.cells[n]) for n in names if n in die.cells), die.height, s)
        parts.append(f'<path d="{hi}" style="fill:var(--accent,#0e6f69)"/>')
        parts.append("</g></g>")
    parts.append("</svg>")
    return "".join(parts)


def _over(top, bottom):
    """`top` composited over `bottom` (RGBA tuples). Pillow draws on an RGBA image by
    replacing pixels, alpha included, so any blending has to be done here."""
    ta, ba = top[3] / 255, bottom[3] / 255
    a = ta + ba * (1 - ta)
    if a == 0:
        return (0, 0, 0, 0)
    rgb = tuple(round((t * ta + b * ba * (1 - ta)) / a) for t, b in zip(top[:3], bottom[:3]))
    return rgb + (round(a * 255),)


def _font(size):
    from PIL import ImageFont

    return ImageFont.load_default(size=size)


def png_panel(die, names, out, width_px=900, colours=NEUTRAL, supersample=3, marks=(), min_px=1.0):
    """One panel as a PNG: every cell recessive, `names` highlighted, `marks` (a list of
    (label, (x0, y0, x1, y1)) in um) drawn as flag-coloured rings with a label. Drawn at
    `supersample` times the size and reduced, so sub-pixel cells blend into density, and
    quantised to a small palette to keep the file light."""
    from PIL import Image, ImageDraw

    s = width_px * supersample / die.width
    W, H = round(die.width * s), round(die.height * s)
    img = Image.new("RGBA", (W, H), colours["sheet"])
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], fill=colours["die"], outline=colours["edge"], width=supersample)
    grow = min_px * supersample

    def box(r):
        x0, y0, x1, y1 = r
        a, b = x0 * s, (die.height - y1) * s
        c, e = max(x1 * s, a + grow), max((die.height - y0) * s, b + grow)
        return [a, b, c, e]

    macro_rects = {tuple(r) for _lbl, r in die.macros}
    for _lbl, r in die.macros:
        d.rectangle(box(r), fill=colours["macro"], outline=colours["edge"], width=supersample)
    for r in die.cells.values():
        if tuple(r) not in macro_rects:
            d.rectangle(box(r), fill=colours["cell"])
    for n in names:
        if n not in die.cells:
            continue
        if tuple(die.cells[n]) in macro_rects:  # a macro: tint it, keep its outline visible
            tint = _over(colours["hi"][:3] + (70,), colours["macro"])
            d.rectangle(box(die.cells[n]), fill=tint, outline=colours["hi"], width=supersample * 2)
        else:
            d.rectangle(box(die.cells[n]), fill=colours["hi"])
    font = _font(15 * supersample)
    placed = []  # label boxes already drawn, so later labels step clear of them
    for label, r in marks:
        x0, y0, x1, y1 = box(r)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rad = max(9 * supersample, (x1 - x0) / 2 + 4 * supersample, (y1 - y0) / 2 + 4 * supersample)
        if rad > 60 * supersample:  # a long feature (a rail): outline it instead of ringing it
            d.rectangle([x0 - 3 * supersample, y0 - 3 * supersample, x1 + 3 * supersample, y1 + 3 * supersample],
                        outline=colours["flag"], width=2 * supersample)
            tx, ty = x0, y0 - 22 * supersample
        else:
            d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=colours["flag"], width=2 * supersample)
            tx, ty = cx + rad + 3 * supersample, cy - 10 * supersample
        if label:
            bb = d.textbbox((tx, ty), label, font=font, stroke_width=supersample * 2 if colours.get("halo") else 0)
            step = bb[3] - bb[1] + 2 * supersample
            ty0 = ty
            while any(bb[0] < q[2] and q[0] < bb[2] and bb[1] < q[3] and q[1] < bb[3] for q in placed):
                ty += step
                bb = (bb[0], bb[1] + step, bb[2], bb[3] + step)
            placed.append(bb)
            if ty != ty0:  # moved clear of another label: a leader line back to its mark
                d.line([(tx - 3 * supersample, (bb[1] + bb[3]) / 2), (tx - 3 * supersample, cy)],
                       fill=colours["flag"], width=supersample)
            halo = colours.get("halo")
            d.text((tx, ty), label, fill=colours["flag"], font=font, stroke_width=supersample * 2 if halo else 0,
                   stroke_fill=halo)
    img = img.resize((round(W / supersample), round(H / supersample)), Image.LANCZOS)
    img.quantize(colors=48, method=Image.Quantize.FASTOCTREE).save(out, optimize=True)
    return out


def png_sheet(die, panels, out, cols=2, panel_w=760, gap=28, title_h=46, pad=28, colours=LIGHT, heading=None):
    """Several panels on one light sheet with titles: [(title, subtitle, names, marks)]."""
    import os
    import tempfile

    from PIL import Image, ImageDraw

    rows = math.ceil(len(panels) / cols)
    ph = round(die.height * panel_w / die.width)
    head_h = 44 if heading else 0
    W = pad * 2 + cols * panel_w + (cols - 1) * gap
    H = pad * 2 + head_h + rows * (title_h + ph) + (rows - 1) * gap
    sheet = Image.new("RGBA", (W, H), colours["sheet"])
    d = ImageDraw.Draw(sheet)
    if heading:
        d.text((pad, pad), heading, fill=colours["ink"], font=_font(24))
    with tempfile.TemporaryDirectory() as tmp:
        for k, (title, sub, names, marks) in enumerate(panels):
            r, c = divmod(k, cols)
            x, y = pad + c * (panel_w + gap), pad + head_h + r * (title_h + ph + gap)
            d.text((x, y), title, fill=colours["ink"], font=_font(18))
            d.text((x, y + 22), sub, fill=colours["muted"], font=_font(14))
            p = os.path.join(tmp, f"{k}.png")
            png_panel(die, names, p, width_px=panel_w, colours=colours, marks=marks)
            sheet.paste(Image.open(p).convert("RGBA"), (x, y + title_h))
    sheet.convert("RGB").quantize(colors=64, method=Image.Quantize.MEDIANCUT).save(out, optimize=True)
    return out
