"""Decode the non-electrical easter eggs in the puzzle GDS.

* The INTERNAL_3 / INTERNAL_7 rectangles below the die (layer 200/0) are Morse code:
  widths 1.38 and 4.14 um are dot and dash (1:3); gaps of 1, 3 and 7 units separate
  marks, letters and words.
* The 0.3 um met2 squares (69/20, top-level polygons) are a 57 x 57 pixel drawing.

    python -m tools.analysis.eastereggs [GDS]
"""

import sys

import gdstk

MORSE = {".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F", "--.": "G", "....": "H",
         "..": "I", ".---": "J", "-.-": "K", ".-..": "L", "--": "M", "-.": "N", "---": "O", ".--.": "P",
         "--.-": "Q", ".-.": "R", "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X",
         "-.--": "Y", "--..": "Z"}
DOT, DASH = "INTERNAL_3", "INTERNAL_7"


def morse(top):
    marks = sorted((r.origin[0], r.cell.name) for r in top.references if r.cell.name in (DOT, DASH))
    unit = next(c.bounding_box()[1][0] for c in (r.cell for r in top.references) if c.name == DOT)
    width = {DOT: unit, DASH: 3 * unit}
    words, letter, word = [], "", []
    for i, (x, name) in enumerate(marks):
        letter += "." if name == DOT else "-"
        if i + 1 == len(marks):
            break
        gap = round((marks[i + 1][0] - (x + width[name])) / unit)
        if gap >= 3:
            word.append(MORSE[letter])
            letter = ""
        if gap >= 7:
            words.append("".join(word))
            word = []
    word.append(MORSE[letter])
    words.append("".join(word))
    return " ".join(words)


def pixel_art(top, layer=(69, 20)):
    sq = {(round(p.bounding_box()[0][0], 2), round(p.bounding_box()[0][1], 2))
          for p in top.polygons if (p.layer, p.datatype) == layer}
    xs = sorted({x for x, _ in sq})
    ys = sorted({y for _, y in sq}, reverse=True)
    return ["".join("#" if (x, y) in sq else " " for x in xs) for y in ys]


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    top = gdstk.read_gds(argv[0] if argv else "upstream/puzzle.gds").top_level()[0]
    print("Morse strip:", morse(top))
    print("\n".join(pixel_art(top)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
