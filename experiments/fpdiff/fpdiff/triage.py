"""Interactive triage: the human adjudicates each divergence class, and accepted
deviations become signed waivers that constrain the next formal run."""

from .fmt import FpFormat
from .jobs import Job
from .report import describe_finding
from .runner import RunResult, explore, save_findings, job_waivers
from .waivers import Waiver, new_waiver, save_waivers

MENU = """  verdict?
    [b] bug                — keep as an open bug
    [1] waive this (class_a, class_b) pair
    [2] waive class '{ca}' on either operand
    [3] waive class '{cb}' on either operand
    [n] waive NaN payload differences (output relaxation)
    [u] waive up to N ulp difference (output relaxation)
    [s] skip for now
    [q] quit triage
"""


def triage_loop(job: Job, rr: RunResult, log=print) -> None:
    fmt: FpFormat = job.fmt
    waivers = job_waivers(job)
    wpath = job.resolve(job.waivers_file)
    dirty = False

    for f in rr.findings:
        if f.verdict:
            continue
        log(f"\n─── finding #{f.id}: input classes ({f.cls_a}, {f.cls_b}) " + "─" * 20)
        log(describe_finding(f, fmt))
        log(MENU.format(ca=f.cls_a, cb=f.cls_b))
        choice = input("  > ").strip().lower()

        if choice == "q":
            break
        if choice == "s":
            continue
        if choice == "b":
            f.verdict = "bug"
            f.note = input("  short bug note: ").strip()
            dirty = True
            continue

        reason = input("  reason for waiver (goes in the signed ledger): ").strip()
        if choice == "1":
            w = new_waiver("input_class_pair", f"waive-{f.cls_a}-{f.cls_b}", reason,
                           cls_a=f.cls_a, cls_b=f.cls_b)
        elif choice == "2":
            w = new_waiver("input_class", f"waive-{f.cls_a}", reason, cls=f.cls_a)
        elif choice == "3":
            w = new_waiver("input_class", f"waive-{f.cls_b}", reason, cls=f.cls_b)
        elif choice == "n":
            w = new_waiver("output_nan_canonical", "nan-canonical", reason)
        elif choice == "u":
            n = int(input("  max ulp: ").strip())
            w = new_waiver("output_ulp_tolerance", f"ulp-{n}", reason, ulp=n)
        else:
            log("  unrecognized, skipping")
            continue
        waivers.append(w)
        save_waivers(wpath, waivers)
        f.verdict = "waived"
        f.note = f"waiver {w.id}"
        dirty = True
        log(f"  signed: {w.id} by {w.signed_off_by} ({w.date})")

    if dirty:
        save_findings(job, rr)
        log("\nre-running formal check under updated waivers...")
        rr2 = explore(job, job_waivers(job), log=log)
        log(f"→ {rr2.status}  ({len(rr2.findings)} divergence classes remain)")
