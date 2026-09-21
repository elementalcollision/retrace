"""PRD S1: layout overlays (tools/viz). The puzzle figure needs the puzzle files; the
TEMPO module map needs a TEMPO checkout (see test/test_tempo.py)."""

import collections
import os

import pytest

HAVE_PUZZLE = os.path.exists("upstream/puzzle.gds") and os.path.isdir("pdk/sky130_fd_sc_hd")


@pytest.mark.skipif(not HAVE_PUZZLE, reason="puzzle files or sky130 PDK subset not present")
def test_puzzle_panels_cover_every_logic_cell():
    """Seven panels (six recovered blocks and the clock tree) that between them hold all
    728 logic cells; 14 gates are shared, 13 by two cones and one by five."""
    from tools.viz import puzzle

    cells, flops = puzzle.block_cells()
    assert set(cells) == set(puzzle.ORDER) | {"clock tree"}
    assert sum(flops.values()) == 92
    union = set().union(*cells.values())
    assert len(union) == 728
    shared = collections.Counter(c for k in puzzle.ORDER for c in cells[k])
    assert collections.Counter(n for n in shared.values() if n > 1) == {2: 13, 5: 1}
    svg, panels = puzzle.figure()
    assert len(panels) == 7 and svg.count("<use ") == 7


def test_small_multiples_svg_follows_the_page_theme():
    """The inline SVG is coloured through the page's CSS variables, with fallbacks."""
    from tools.viz.layout import Die, svg_panels

    die = Die(10, 20, {"a": (1, 1, 3, 3), "b": (5, 5, 7, 9)})
    svg = svg_panels(die, [("one", "1 cell", ["a"]), ("two", "1 cell", ["b"])], cols=2)
    for var in ("--accent", "--rule", "--surface", "--ink", "--muted"):
        assert f"var({var}," in svg
    assert svg.count('<path d="') == 2


def test_png_panel_blends_the_macro_tint(tmp_path):
    """Pillow replaces RGBA pixels instead of blending, so a translucent tint must be
    composited by hand (layout._over); a flagged macro must not come out solid."""
    from PIL import Image

    from tools.viz.layout import LIGHT, Die, _over, png_panel

    assert _over((208, 59, 59, 255), (0, 0, 0, 255)) == (208, 59, 59, 255)
    assert _over((0, 0, 0, 0), (10, 20, 30, 255)) == (10, 20, 30, 255)
    die = Die(100, 100, {"m": (10, 10, 90, 90)}, macros=[("M", (10, 10, 90, 90))])
    out = png_panel(die, {"m"}, str(tmp_path / "p.png"), width_px=100, colours={**LIGHT, "hi": LIGHT["flag"]})
    px = Image.open(out).convert("RGBA").getpixel((50, 50))[:3]
    assert px != LIGHT["flag"][:3] and px[0] > px[1]  # tinted red, not solid


def test_tempo_module_labels_recover_held_out_seeds():
    """Labels spread from the register seeds must give most held-out seeds their own
    module back (93% on the v0.2-signoff DEF; the floor here leaves room for a new one)."""
    from tools.tempo import lvs

    if not os.path.isdir(lvs.TEMPO_ROOT):
        pytest.skip(f"{lvs.TEMPO_ROOT} not present")
    from tools.viz import tempo

    die, groups, seeds, adj, cells, unassigned = tempo.modules()
    score = tempo.holdout(seeds, adj, cells)
    right = sum(r for r, _h in score.values())
    hidden = sum(h for _r, h in score.values())
    assert right / hidden >= 0.85, score
    assert len(unassigned) < 0.01 * len(cells)
    assert {"u_core", "u_ser", "u_tio", "u_crc", "u_sys", "u_host"} <= set(groups)
