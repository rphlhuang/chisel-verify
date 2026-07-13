"""Replay a btor2 witness through Icarus Verilog with the monitor in TEMPO_SIM
mode: the $error carries each failing property's id and NL intent, and a
per-cycle table of the monitored signals is printed for human triage.

Same cross-validation stance as fpdiff: a violation is only presented to the
human after two unrelated tools (btormc and iverilog) both exhibit it.
"""

import subprocess
from pathlib import Path

from .ast import Project
from .engines import frame_input
from .harness import parse_ports
from .tools import tool


def replay(proj: Project, out_dir: Path, frames: list[dict[str, str]]) -> dict:
    dut_srcs = [Path(f).resolve() for f in proj.dut_files]
    ports = parse_ports(dut_srcs[0].read_text(), proj.dut_top)
    ins = [(n, w) for n, (d, w) in ports.items()
           if d == "input" and n not in (proj.clock, proj.reset)]
    outs = [(n, w) for n, (d, w) in ports.items() if d == "output"]
    nf = len(frames)

    L = ["module tempo_tb;",
         "  reg clock = 1'b0;",
         "  always #5 clock = ~clock;",
         "  reg rst;",
         "  integer i;"]
    for n, w in ins:
        L.append(f"  reg {f'[{w-1}:0] ' if w>1 else ''}{n};")
        L.append(f"  reg {f'[{w-1}:0] ' if w>1 else ''}stim_{n} [0:{nf-1}];")
    for n, w in outs:
        L.append(f"  wire {f'[{w-1}:0] ' if w>1 else ''}{n};")
    conns = [f".{proj.clock}(clock)"]
    if proj.reset:
        conns.append(f".{proj.reset}(rst)")
    conns += [f".{n}({n})" for n, _ in ins + outs]
    L.append(f"  {proj.dut_top} dut({', '.join(conns)});")
    mconns = [".clock(clock)", ".dis(rst)"] + [f".{s}({s})" for s in proj.signals]
    L.append(f"  tempo_monitor mon({', '.join(mconns)});")
    L.append("  initial begin")
    for t in range(nf):
        for n, w in ins:
            v = frame_input(frames, t, n)
            L.append(f"    stim_{n}[{t}] = {w}'h{v:x};")
    trace = " ".join(f"{n}=%h" for n, _ in list(proj.signals.items()))
    args = ", ".join(n for n in proj.signals)
    L.append(f"    for (i = 0; i < {nf}; i = i + 1) begin")
    for n, _ in ins:
        L.append(f"      {n} = stim_{n}[i];")
    L.append("      rst = (i == 0);")
    L.append(f'      #4 $display("TEMPO_TRACE %0d {trace}", i, {args});')
    L.append("      #6;")
    L.append("    end")
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    tb = out_dir / "replay_tb.v"
    tb.write_text("\n".join(L) + "\n")

    exe = out_dir / "replay"
    r = subprocess.run([tool("iverilog"), "-g2012", "-DTEMPO_SIM", "-o", str(exe),
                        str(tb), str(out_dir / "monitor.v"), *map(str, dut_srcs)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"iverilog failed:\n{r.stderr}")
    r = subprocess.run([str(exe)], capture_output=True, text=True)

    table, fails = [], []
    for line in r.stdout.splitlines():
        if "TEMPO_TRACE" in line:
            table.append(line.split("TEMPO_TRACE ", 1)[1])
        if "TEMPO FAIL" in line:
            fails.append(line[line.index("TEMPO FAIL"):])
    return {"table": table, "fails": sorted(set(fails))}
