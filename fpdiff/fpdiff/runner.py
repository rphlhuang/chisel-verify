"""Orchestration: build -> check -> validate -> decode -> (block class, repeat).

`explore` enumerates divergence *classes*: each counterexample's (class(a), class(b))
pair is auto-blocked and the check re-run, so one pass yields at most one exemplar
finding per input-class pair (≤25 iterations) plus the residual verdict for
everything not yet waived or blocked.
"""

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

from .engines import run_btormc
from .fmt import FpFormat
from .jobs import Job
from .miter import build_miter, build_cover
from .fmt import sv_class_predicate
from .validate import replay_side, extract_stimulus
from .waivers import (Waiver, load_waivers, outputs_equivalent, INPUT_CLASSES)


@dataclass
class Finding:
    id: int
    cls_a: str
    cls_b: str
    a_bits: int
    b_bits: int
    gold_bits: int
    gate_bits: int
    ulp: int | None
    frame: int
    validated: bool
    verdict: str = ""       # "", "bug", "waived"
    note: str = ""


@dataclass
class RunResult:
    status: str             # "proved" | "safe_bounded" | "diverges"
    kmax: int
    engine_time: float
    findings: list[Finding] = field(default_factory=list)
    residual: str = ""      # status of the space left after auto-blocks


def _cls5(f: FpFormat, bits: int) -> str:
    c = f.classify(bits)
    return "nan" if c in ("qnan", "snan") else c


def _block_waiver(cls_a: str, cls_b: str) -> Waiver:
    return Waiver(id=f"block-{cls_a}-{cls_b}", kind="input_class_pair",
                  cls_a=cls_a, cls_b=cls_b, reason="auto-block during explore")


def check_once(job: Job, waivers: list[Waiver], blocks: list[Waiver]):
    btor = build_miter(job, waivers, blocks)
    return run_btormc(btor, job.effective_kmax)


def _decode_cex(job: Job, waivers: list[Waiver], frames, fid: int) -> Finding:
    f = job.fmt
    stim = extract_stimulus(job, frames)
    gold_outs = replay_side(job, "gold", stim)
    gate_outs = replay_side(job, "gate", stim)
    lmax = job.max_latency
    cmp_start = 0 if lmax == 0 else lmax + 1
    for t in range(cmp_start, len(stim)):
        g, _ = gold_outs[t]
        d, _ = gate_outs[t]
        if g is None or d is None:
            continue
        if not outputs_equivalent(waivers, f, g, d):
            a_bits, b_bits = stim[t - lmax]
            return Finding(
                id=fid,
                cls_a=_cls5(f, a_bits), cls_b=_cls5(f, b_bits),
                a_bits=a_bits, b_bits=b_bits,
                gold_bits=g, gate_bits=d,
                ulp=f.ulp_distance(g, d),
                frame=t, validated=True)
    # solver said cex but simulation disagrees -> modeling artifact; report unvalidated
    a_bits, b_bits = stim[max(0, len(stim) - 1 - lmax)]
    g = gold_outs[-1][0] or 0
    d = gate_outs[-1][0] or 0
    return Finding(id=fid, cls_a=_cls5(f, a_bits), cls_b=_cls5(f, b_bits),
                   a_bits=a_bits, b_bits=b_bits, gold_bits=g, gate_bits=d,
                   ulp=None, frame=len(stim) - 1, validated=False,
                   note="btormc cex NOT reproduced in iverilog — investigate")


def explore(job: Job, waivers: list[Waiver], max_cex: int = 25,
            log=print) -> RunResult:
    blocks: list[Waiver] = []
    findings: list[Finding] = []
    total_time = 0.0
    complete = job.max_latency == 0  # depth-0 BMC of a comb. miter is a full proof

    while True:
        res = check_once(job, waivers, blocks)
        total_time += res.elapsed
        if res.status == "safe":
            break
        fid = len(findings) + 1
        finding = _decode_cex(job, waivers, res.frames, fid)
        findings.append(finding)
        log(f"  divergence #{fid}: class ({finding.cls_a}, {finding.cls_b})"
            f"{'' if finding.validated else '  [UNVALIDATED]'}")
        if len(findings) >= max_cex:
            break
        blocks.append(_block_waiver(finding.cls_a, finding.cls_b))

    if findings:
        status = "diverges"
        if len(findings) < max_cex:
            residual = ("all other input-class pairs proved equivalent"
                        if complete else
                        f"all other input-class pairs safe up to k={job.effective_kmax}")
        else:
            residual = "exploration stopped at max-cex; residual space unchecked"
    else:
        status = "proved" if complete else "safe_bounded"
        residual = ""

    rr = RunResult(status=status, kmax=job.effective_kmax,
                   engine_time=round(total_time, 3),
                   findings=findings, residual=residual)
    save_findings(job, rr)
    return rr


def coverage_check(job: Job, waivers: list[Waiver]) -> dict[str, bool]:
    """After waivers, which input classes remain reachable on each operand?
    Guards against a waiver that quietly assumes away the whole space."""
    out = {}
    for op in ("a", "b"):
        for cls in INPUT_CLASSES:
            pred = sv_class_predicate(job.fmt, cls, op)
            btor = build_cover(job, waivers, pred, f"{cls}_{op}")
            res = run_btormc(btor, 0)
            out[f"{op}:{cls}"] = (res.status == "cex")  # reachable == sat
    return out


# ---- persistence ---------------------------------------------------------------

def findings_path(job: Job) -> Path:
    return job.out_dir / "findings.json"


def save_findings(job: Job, rr: RunResult) -> None:
    data = {"status": rr.status, "kmax": rr.kmax, "engine_time": rr.engine_time,
            "residual": rr.residual, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "findings": [asdict(x) for x in rr.findings]}
    job.out_dir.mkdir(parents=True, exist_ok=True)
    findings_path(job).write_text(json.dumps(data, indent=2) + "\n")


def load_findings(job: Job) -> RunResult | None:
    p = findings_path(job)
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    return RunResult(status=data["status"], kmax=data["kmax"],
                     engine_time=data["engine_time"], residual=data.get("residual", ""),
                     findings=[Finding(**x) for x in data["findings"]])


def job_waivers(job: Job) -> list[Waiver]:
    return load_waivers(job.resolve(job.waivers_file))
