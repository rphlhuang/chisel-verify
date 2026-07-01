"""The formal execution harness: SVA testbench generation, sby invocation,
and counterexample extraction.

This is the part of the system that is allowed to say "true" or "false".
Everything upstream (llm.py, loop.py) only ever *proposes* a property; this
module is where SymbiYosys actually decides whether it holds on the RTL.
See README.md section "Three-role design" for why that separation matters.

Property format: rather than asking the LLM to emit raw SVA text (which
open-source Yosys only supports a narrow, easy-to-get-wrong subset of), we
ask it for a structured (name, kind, antecedent, consequent) tuple and the
harness renders that into plain immediate assertions inside a clocked
always-block. This keeps every property inside the SVA subset Yosys can
actually elaborate, and keeps LLM generation errors distinguishable from
real BMC failures.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel
from vcdvcd import VCDVCD

DUT_MODULE_NAME = "AdderVariant"
DUT_CLOCK_PORT = "clock"
DUT_RESET_PORT = "reset"
DUT_PORT_A = "io_a"
DUT_PORT_B = "io_b"
DUT_PORT_S = "io_s"

BMC_DEPTH = 12


class PropertySpec(BaseModel):
    name: str
    intent: str
    kind: Literal["assert", "assume"]
    antecedent: Optional[str] = None
    consequent: str


@dataclass
class CounterExample:
    a: int
    b: int
    observed_s: int
    expected_s: int
    fail_step: int
    timeline: list[dict] = field(default_factory=list)  # [{time, clk, reset, a, b, s}, ...]
    wavedrom: dict = field(default_factory=dict)


@dataclass
class PropertyResult:
    name: str
    verdict: Literal["PROVEN", "FAILED", "ERROR"]
    log_tail: str
    sby_dir: Path
    cex: Optional[CounterExample] = None


def _find_sby_binary() -> str:
    path = shutil.which("sby")
    if path is None:
        raise RuntimeError(
            "sby (SymbiYosys) not found on PATH. Run formal-hitl/check_env.py "
            "for install instructions."
        )
    return path


def _render_condition_block(name: str, kind: str, antecedent: Optional[str], consequent: str) -> str:
    stmt = f"{name}: assert ({consequent});" if kind == "assert" else f"{name}: assume ({consequent});"
    if antecedent:
        return f"      if ({antecedent}) begin\n        {stmt}\n      end"
    return f"      {stmt}"


def render_formal_tb(width: int, assumptions: list[PropertySpec], target: PropertySpec) -> str:
    """Harness owns all boilerplate: clock, reset pulse, free (undriven)
    input registers so BMC explores the input space each cycle, and the DUT
    instantiation. The LLM only ever supplies condition bodies via
    `PropertySpec`.
    """
    assume_blocks = "\n".join(
        _render_condition_block(p.name, "assume", p.antecedent, p.consequent) for p in assumptions
    )
    assert_block = _render_condition_block(target.name, "assert", target.antecedent, target.consequent)

    return f"""\
module formal_tb (
  input clk
);
  localparam WIDTH = {width};

  reg reset_r;
  initial reset_r = 1;
  always @(posedge clk) reset_r <= 0;

  // Undriven regs are free per BMC step -- this is what makes each cycle
  // explore a fresh (a, b) rather than replaying a fixed stimulus.
  reg [WIDTH-1:0] a;
  reg [WIDTH-1:0] b;
  wire [WIDTH:0] s;

  {DUT_MODULE_NAME} dut (
    .{DUT_CLOCK_PORT}(clk),
    .{DUT_RESET_PORT}(reset_r),
    .{DUT_PORT_A}(a),
    .{DUT_PORT_B}(b),
    .{DUT_PORT_S}(s)
  );

`ifdef FORMAL
  always @(posedge clk) begin
    if (!reset_r) begin
{assume_blocks}
{assert_block}
    end
  end
`endif
endmodule
"""


def _write_sby_file(sby_dir: Path, depth: int) -> Path:
    sby_path = sby_dir / "prove.sby"
    sby_path.write_text(
        f"""\
[options]
mode bmc
depth {depth}

[engines]
smtbmc bitwuzla

[script]
read -formal -DFORMAL -DSYNTHESIS formal_tb.sv dut.sv
prep -top formal_tb

[files]
formal_tb.sv
dut.sv
"""
    )
    return sby_path


def run_property(
    run_dir: Path,
    width: int,
    dut_sv_path: Path,
    assumptions: list[PropertySpec],
    target: PropertySpec,
    depth: int = BMC_DEPTH,
) -> PropertyResult:
    """Compiles + proves a single property against the DUT and returns its
    verdict. A parse/elaboration failure (bad LLM-generated Verilog) comes
    back as verdict=ERROR -- route those to the repair/refine step, not to
    the human (they are generation errors, not RTL findings).
    """
    sby_root = run_dir / "sby"
    sby_dir = sby_root / target.name
    sby_dir.mkdir(parents=True, exist_ok=True)

    (sby_dir / "formal_tb.sv").write_text(render_formal_tb(width, assumptions, target))
    shutil.copy(dut_sv_path, sby_dir / "dut.sv")
    _write_sby_file(sby_dir, depth)

    sby_bin = _find_sby_binary()
    workdir = sby_dir / "work"
    proc = subprocess.run(
        [sby_bin, "-f", "-d", str(workdir), "prove.sby"],
        cwd=sby_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )
    log_tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-30:])

    status_file = workdir / "status"
    verdict: Literal["PROVEN", "FAILED", "ERROR"] = "ERROR"
    if status_file.exists():
        token = status_file.read_text().split()[0]
        verdict = {"PASS": "PROVEN", "FAIL": "FAILED", "ERROR": "ERROR", "UNKNOWN": "ERROR"}.get(
            token, "ERROR"
        )

    result = PropertyResult(name=target.name, verdict=verdict, log_tail=log_tail, sby_dir=sby_dir)

    if verdict == "FAILED":
        vcd_path = workdir / "engine_0" / "trace.vcd"
        if vcd_path.exists():
            fail_step = _parse_fail_step(proc.stdout + proc.stderr)
            result.cex = extract_counterexample(vcd_path, width, fail_step)

    return result


def _parse_fail_step(sby_output: str) -> Optional[int]:
    match = re.search(r"failed assertion .* in step (\d+)", sby_output)
    return int(match.group(1)) if match else None


def extract_counterexample(
    vcd_path: Path, width: int, fail_step: Optional[int] = None
) -> Optional[CounterExample]:
    """Parses the sby-produced VCD into a compact, human-legible CEX:
    concrete a/b, observed vs. expected sum, and the full signal timeline
    (needed for RegisteredBuggy, where the bug only appears a cycle later).

    # SEAM: cocotb-replay -- this is where a concrete CEX would be turned
    # into a re-runnable cocotb stimulus (drive `a`/`b` with these exact
    # values each cycle and check `s` against the same reference model).
    """
    vcd = VCDVCD(str(vcd_path))

    def find_signal(suffix: str) -> Optional[str]:
        for name in vcd.signals:
            if name.endswith(suffix):
                return name
        return None

    sig_clk = find_signal(".clk")
    sig_reset = find_signal(".reset_r")
    sig_a = find_signal(".a")
    sig_b = find_signal(".b")
    sig_s = find_signal(".s")
    if not all([sig_clk, sig_a, sig_b, sig_s]):
        return None

    def values(signal: str) -> list[tuple[int, str]]:
        tv = vcd[signal].tv
        return [(int(t), v) for t, v in tv]

    def value_at(signal: str, time: int) -> int:
        tv = values(signal)
        current = "0"
        for t, v in tv:
            if t > time:
                break
            current = v
        try:
            return int(current, 2)
        except ValueError:
            return 0

    all_times = sorted({t for t, _ in values(sig_clk)})
    posedge_times = []
    prev = "0"
    for t, v in values(sig_clk):
        if prev == "0" and v == "1":
            posedge_times.append(t)
        prev = v

    timeline = []
    for t in posedge_times:
        timeline.append(
            {
                "time": t,
                "reset": value_at(sig_reset, t) if sig_reset else 0,
                "a": value_at(sig_a, t),
                "b": value_at(sig_b, t),
                "s": value_at(sig_s, t),
            }
        )

    if not timeline:
        return None

    # smtbmc's step numbering counts the unclocked initial state as step 0,
    # so posedge #1 (our timeline index 0) is its step 1 -- shift by one.
    adjusted = (fail_step - 1) if fail_step is not None else None
    index = adjusted if adjusted is not None and 0 <= adjusted < len(timeline) else len(timeline) - 1
    failing_row = timeline[index]
    a_val, b_val, observed_s = failing_row["a"], failing_row["b"], failing_row["s"]
    # Reference model for THIS domain (the adder): sum is expected to equal
    # a + b with the carry preserved. This is a deliberate, adder-specific
    # shortcut for v0 -- a general system would need a symbolic evaluator
    # of the property's consequent, which is out of scope here.
    expected_s = a_val + b_val

    return CounterExample(
        a=a_val,
        b=b_val,
        observed_s=observed_s,
        expected_s=expected_s,
        fail_step=index,
        timeline=timeline,
        wavedrom=_timeline_to_wavedrom(timeline, width),
    )


def _bits(value: int, width: int) -> str:
    return format(value & ((1 << width) - 1), f"0{width}b")


def _wave_signal(name: str, values: list[int], width: int) -> dict:
    wave_chars = []
    data = []
    prev = None
    for v in values:
        if v != prev:
            wave_chars.append("=")
            data.append(str(v))
        else:
            wave_chars.append(".")
        prev = v
    return {"name": name, "wave": "".join(wave_chars), "data": data}


def _timeline_to_wavedrom(timeline: list[dict], width: int) -> dict:
    clk_wave = "P" + "." * (len(timeline) - 1)
    signals = [
        {"name": "clk", "wave": clk_wave},
        _wave_signal("reset", [row["reset"] for row in timeline], 1),
        _wave_signal("a", [row["a"] for row in timeline], width),
        _wave_signal("b", [row["b"] for row in timeline], width),
        _wave_signal("s", [row["s"] for row in timeline], width + 1),
    ]
    return {"signal": signals}
