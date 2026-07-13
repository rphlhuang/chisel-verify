"""The deliverable: a human-signed compatibility profile in markdown."""

from .fmt import FpFormat
from .jobs import Job
from .runner import RunResult, Finding
from .waivers import Waiver


def describe_finding(f: Finding, fmt: FpFormat) -> str:
    lines = [
        f"a    = {fmt.describe(f.a_bits)}",
        f"b    = {fmt.describe(f.b_bits)}",
        f"gold = {fmt.describe(f.gold_bits)}",
        f"gate = {fmt.describe(f.gate_bits)}",
    ]
    if f.ulp is not None:
        lines.append(f"ulp distance: {f.ulp}")
    if not f.validated:
        lines.append("WARNING: not reproduced in simulation (modeling artifact?)")
    return "\n".join(lines)


def render_profile(job: Job, rr: RunResult, waivers: list[Waiver]) -> str:
    fmt = job.fmt
    L = [f"# fpdiff compatibility profile: `{job.name}`", ""]
    L.append(f"- format: exp={fmt.exp} sig={fmt.sig} (width {fmt.width})")
    L.append(f"- golden: `{job.gold.top}` ({', '.join(job.gold.files)}), latency {job.gold.latency}")
    L.append(f"- gate:   `{job.gate.top}` ({', '.join(job.gate.files)}), latency {job.gate.latency}")
    L.append(f"- engine: {job.engine}, kmax {rr.kmax}, total solver time {rr.engine_time}s")
    L.append("")

    verdict = {
        "proved": "**PROVED EQUIVALENT** (complete for combinational designs)",
        "safe_bounded": f"**NO DIVERGENCE up to k={rr.kmax}** (bounded; not a full proof)",
        "diverges": "**DIVERGES** — see findings",
    }[rr.status]
    L.append(f"## Verdict: {verdict}")
    if rr.residual:
        L.append(f"\n_Residual: {rr.residual}_")
    L.append("")

    if waivers:
        L.append("## Waivers in force (human-signed)")
        L.append("")
        L.append("| id | kind | detail | reason | signed off |")
        L.append("|---|---|---|---|---|")
        for w in waivers:
            detail = {"input_class": f"exclude {w.cls} on {'/'.join(w.operands)}",
                      "input_class_pair": f"exclude ({w.cls_a}, {w.cls_b})",
                      "input_expr": f"`{w.expr}`",
                      "output_nan_canonical": "NaN payloads not compared",
                      "output_ulp_tolerance": f"outputs equal within {w.ulp} ulp",
                      }.get(w.kind, w.kind)
            L.append(f"| {w.id} | {w.kind} | {detail} | {w.reason} | {w.signed_off_by} {w.date} |")
        L.append("")

    if rr.findings:
        L.append("## Findings (one exemplar per divergent input-class pair)")
        L.append("")
        for f in rr.findings:
            tag = {"bug": "🐞 BUG", "waived": "waived", "": "UNTRIAGED"}[f.verdict]
            L.append(f"### #{f.id} ({f.cls_a}, {f.cls_b}) — {tag}")
            L.append("```")
            L.append(describe_finding(f, fmt))
            L.append("```")
            if f.note:
                L.append(f"note: {f.note}")
            L.append("")

    L.append("---")
    L.append("_Every finding above was produced by btormc on a Yosys-built miter and"
             " independently re-simulated with Icarus Verilog before being reported._")
    return "\n".join(L) + "\n"


def coverage_section(cov: dict[str, bool]) -> str:
    L = ["## Input-space coverage after waivers", ""]
    L.append("| operand:class | still checked? |")
    L.append("|---|---|")
    for k, v in cov.items():
        L.append(f"| {k} | {'yes' if v else '**NO — assumed away**'} |")
    return "\n".join(L) + "\n"
