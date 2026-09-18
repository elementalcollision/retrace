"""Minimal DEF reader for the warm-up oracle: COMPONENTS placements and NETS connectivity."""

import re

_COMP = re.compile(r"^\s*-\s+(\S+)\s+(\S+).*?\+\s+(?:PLACED|FIXED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+)")
_CONN = re.compile(r"\(\s*(\S+)\s+(\S+)\s*\)")


def read_def(path):
    """Return {"components": {name: (master, x, y, orient)}, "nets": {net: [(inst|'PIN', pin)]}}."""
    comps, nets = {}, {}
    section = None
    net = None
    with open(path) as f:
        for line in f:
            s = line.strip()
            if s.startswith("COMPONENTS"):
                section = "comp"
                continue
            if s.startswith("NETS"):
                section = "nets"
                continue
            if s.startswith("END COMPONENTS") or s.startswith("END NETS"):
                section = None
                continue
            if section == "comp" and (m := _COMP.match(line)):
                comps[m.group(1)] = (m.group(2), int(m.group(3)), int(m.group(4)), m.group(5))
            elif section == "nets":
                if s.startswith("- "):
                    net = s.split()[1]
                    nets[net] = []
                    s = s[len(net) + 2:]
                if net is not None and not s.startswith(("+", "NEW")):
                    for inst, pin in _CONN.findall(s):
                        if inst == "PIN" or not inst.isdigit():
                            nets[net].append((inst, pin))
                if s.endswith(";"):
                    net = None
    return {"components": comps, "nets": nets}
