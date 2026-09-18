"""Minimal LEF reader: macro size and pin direction/use, enough for extraction checks."""

import re

_MACRO = re.compile(r"^MACRO\s+(\S+)")
_PIN = re.compile(r"^\s+PIN\s+(\S+)")
_DIR = re.compile(r"^\s+DIRECTION\s+(\w+)")
_USE = re.compile(r"^\s+USE\s+(\w+)")
_SIZE = re.compile(r"^\s+SIZE\s+([\d.]+)\s+BY\s+([\d.]+)")


def read_lef(path):
    """Return {macro: {"size": (w, h), "pins": {name: {"direction": .., "use": ..}}}}."""
    macros, macro, name, pin = {}, None, None, None
    with open(path) as f:
        for line in f:
            if m := _MACRO.match(line):
                name = m.group(1)
                macro = macros.setdefault(name, {"size": None, "pins": {}})
                pin = None
            elif macro is None:
                continue
            elif m := _PIN.match(line):
                pin = macro["pins"].setdefault(m.group(1), {"direction": None, "use": "SIGNAL"})
            elif pin is not None and (m := _DIR.match(line)):
                pin["direction"] = m.group(1)
            elif pin is not None and (m := _USE.match(line)):
                pin["use"] = m.group(1)
            elif pin is None and (m := _SIZE.match(line)):
                macro["size"] = (float(m.group(1)), float(m.group(2)))
            elif line.strip() == f"END {name}":
                macro, name, pin = None, None, None

    return macros
