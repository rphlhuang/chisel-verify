"""Independent counterexample validation: replay the btor2 witness through
icarus verilog on each design separately and compare outputs in python.

This guards every finding against model-checker/export artifacts — a divergence
is only reported if two unrelated tools (btormc and iverilog) both exhibit it.
"""

import subprocess
from pathlib import Path

from .engines import frame_input
from .jobs import Job, Design
from .tools import tool


def _tb_source(job: Job, d: Design, stim: list[tuple[int, int]], delay: int) -> str:
    f = job.fmt
    w = f.width
    n = len(stim)
    hexw = (w + 3) // 4

    conns = [f".{d.port('a')}(a)", f".{d.port('b')}(b)", f".{d.port('out')}(out)"]
    if d.port("clock"):
        conns.append(f".{d.port('clock')}(clock)")
    if d.port("reset"):
        conns.append(f".{d.port('reset')}(rst)")
    for role in ("valid_in", "en"):
        if d.port(role):
            conns.append(f".{d.port(role)}(1'b1)")
    if d.port("valid_out"):
        conns.append(f".{d.port('valid_out')}(vout)")
    for port, val in d.tie.items():
        conns.append(f".{port}({val})")

    L = ["module fpdiff_tb;"]
    L.append("  reg clock = 1'b0;")
    L.append("  always #5 clock = ~clock;")
    L.append(f"  reg [{w-1}:0] a, b;")
    L.append("  reg rst;")
    L.append(f"  wire [{w-1}:0] out;")
    L.append("  wire vout;" if d.port("valid_out") else "  wire vout = 1'b1;")
    L.append(f"  {d.top} dut({', '.join(conns)});")
    L.append("  integer i;")
    L.append(f"  reg [{w-1}:0] stim_a [0:{n-1}];")
    L.append(f"  reg [{w-1}:0] stim_b [0:{n-1}];")
    L.append("  initial begin")
    for i in range(n):
        # this side sees the stimulus delayed by `delay` frames (latency alignment)
        j = i - delay
        av, bv = stim[j] if j >= 0 else (0, 0)
        L.append(f"    stim_a[{i}] = {w}'h{av:0{hexw}x};")
        L.append(f"    stim_b[{i}] = {w}'h{bv:0{hexw}x};")
    L.append(f"    for (i = 0; i < {n}; i = i + 1) begin")
    L.append("      a = stim_a[i]; b = stim_b[i]; rst = (i == 0);")
    L.append('      #4 $display("FPDIFF %0d %h %b", i, out, vout);')
    L.append("      #6;")
    L.append("    end")
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def replay_side(job: Job, side: str, stim: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """-> per-frame (out_bits, valid) observed on `side` for the raw stimulus."""
    d: Design = getattr(job, side)
    delay = job.max_latency - d.latency
    work = job.out_dir
    tb = work / f"replay_{side}_tb.v"
    tb.write_text(_tb_source(job, d, stim, delay))
    src = sorted(work.glob(f"{side}_*_*"))  # preprocessed sources from build_miter
    exe = work / f"replay_{side}"
    r = subprocess.run([tool("iverilog"), "-g2012", "-o", str(exe), str(tb), *map(str, src)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"iverilog failed for {side}:\n{r.stderr}")
    r = subprocess.run([str(exe)], capture_output=True, text=True)
    outs = []
    for line in r.stdout.splitlines():
        if line.startswith("FPDIFF "):
            _, i, hx, v = line.split()
            # uninitialized pipeline registers read X before the pipe fills;
            # those frames precede the compare window and are skipped upstream
            out_val = None if "x" in hx or "z" in hx else int(hx, 16)
            valid = 0 if v not in ("0", "1") else int(v, 2)
            outs.append((out_val, valid))
    if len(outs) != len(stim):
        raise RuntimeError(f"replay produced {len(outs)} frames, expected {len(stim)}")
    return outs


def extract_stimulus(job: Job, frames: list[dict[str, str]]) -> list[tuple[int, int]]:
    n = len(frames)
    return [(frame_input(frames, t, "a"), frame_input(frames, t, "b")) for t in range(n)]
