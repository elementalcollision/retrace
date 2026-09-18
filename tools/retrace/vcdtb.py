"""Turn a recorded VCD into a self-checking Verilog testbench (V6 behavioural oracle).

Inputs are driven at the recorded times. Outputs are compared with the recorded values
1 ps after every recorded clock edge and at every mid-cycle point, so both the
post-edge value and the settled value must match. Unknown recorded values (x) are
not checked.

    python -m tools.retrace.vcdtb VCD --top puzzle --inputs clk,rst_n,enable,I \\
        --outputs O,success --clock clk -o out/tb_puzzle.v
"""

import argparse
import bisect
import re
import sys

_VAR = re.compile(r"\$var\s+\w+\s+(\d+)\s+(\S+)\s+(\S+)")


def read_vcd(path):
    """Return (widths {name: w}, events {name: [(t, value_str)]}) with values as bit strings."""
    ids, widths, events = {}, {}, {}
    t = 0
    with open(path) as f:
        text = f.read()
    for m in _VAR.finditer(text):
        ids[m.group(2)] = m.group(3)
        widths[m.group(3)] = int(m.group(1))
        events.setdefault(m.group(3), [])
    body = text[text.index("$enddefinitions"):]
    for tok in body.split():
        if tok.startswith("#"):
            t = int(tok[1:])
        elif tok.startswith(("b", "B")):
            pending = tok[1:]
        elif tok in ids and "pending" in locals() and pending is not None:
            events[ids[tok]].append((t, pending))
            pending = None
        elif tok[0] in "01xzXZ" and tok[1:] in ids:
            events[ids[tok[1:]]].append((t, tok[0].lower()))
    return widths, events


def value_at(evs, t):
    times = [e[0] for e in evs]
    i = bisect.bisect_right(times, t) - 1
    return evs[i][1] if i >= 0 else "x"


def testbench(widths, events, top, inputs, outputs, clock):
    edges = [t for t, v in events[clock] if v == "1"]
    period = edges[1] - edges[0]
    end = max(t for evs in events.values() for t, _v in evs) + period
    checks = sorted({t + 1 for t in edges} | {t + period // 2 for t in edges})
    checks = [c for c in checks if c < end]
    lines = ["`timescale 1ps/1ps", "module tb;"]
    for n in inputs:
        w = widths[n]
        lines.append(f"  reg {'[%d:0] ' % (w - 1) if w > 1 else ''}{n};")
    for n in outputs:
        w = widths[n]
        lines.append(f"  wire {'[%d:0] ' % (w - 1) if w > 1 else ''}{n};")
    lines.append(f"  {top} dut (" + ", ".join(f".{n}({n})" for n in inputs + outputs) + ");")
    lines.append("  integer errors = 0, checked = 0;")
    # stimulus
    stim = sorted((t, n, v) for n in inputs for t, v in events[n])
    lines.append("  initial begin")
    now = 0
    for t, n, v in stim:
        if t > now:
            lines.append(f"    #{t - now};")
            now = t
        lines.append(f"    {n} = {widths[n]}'b{v.zfill(widths[n]) if v not in 'xz' else v * widths[n]};")
    lines.append("  end")
    # checks
    lines.append("  initial begin")
    now = 0
    for c in checks:
        lines.append(f"    #{c - now};")
        now = c
        for n in outputs:
            v = value_at(events[n], c)
            if "x" in v or "z" in v:
                continue
            exp = f"{widths[n]}'b{v.zfill(widths[n])}"
            lines.append(
                f"    checked = checked + 1; if ({n} !== {exp}) begin errors = errors + 1; "
                f"if (errors <= 20) $display(\"MISMATCH t=%0d {n} got=%b exp=%b\", $time, {n}, {exp}); end"
            )
    lines.append(f"    #{period};")
    lines.append('    $display("VCD-REPLAY checked=%0d errors=%0d", checked, errors);')
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("vcd")
    ap.add_argument("--top", required=True)
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--outputs", required=True)
    ap.add_argument("--clock", default="clk")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args(argv)
    widths, events = read_vcd(args.vcd)
    tb = testbench(widths, events, args.top, args.inputs.split(","), args.outputs.split(","), args.clock)
    with open(args.output, "w") as f:
        f.write(tb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
