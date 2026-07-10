"""fpdiff — formal divergence triage for floating-point RTL, on open tools only.

  fpdiff run <job.json>       build miter, explore divergence classes, save findings
  fpdiff triage <job.json>    adjudicate findings interactively; waivers re-run formal
  fpdiff report <job.json>    render the compatibility profile (markdown)
  fpdiff coverage <job.json>  check which input classes the waivers leave verified
  fpdiff explain <job.json> <finding-id>   LLM-drafted narration of a finding
"""

import argparse
import sys

from .jobs import load_job
from .runner import explore, load_findings, coverage_check, job_waivers
from .report import render_profile, coverage_section
from .triage import triage_loop


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fpdiff", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["run", "triage", "report", "coverage", "explain"])
    ap.add_argument("job", help="path to job .json")
    ap.add_argument("finding", nargs="?", type=int, help="finding id (explain)")
    ap.add_argument("--max-cex", type=int, default=25)
    args = ap.parse_args(argv)

    job = load_job(args.job)
    waivers = job_waivers(job)

    if args.command == "run":
        print(f"[fpdiff] {job.name}: gold={job.gold.top} gate={job.gate.top} "
              f"kmax={job.effective_kmax} waivers={len(waivers)}")
        rr = explore(job, waivers, max_cex=args.max_cex)
        print(f"[fpdiff] status: {rr.status}  "
              f"({len(rr.findings)} divergence classes, {rr.engine_time}s solver time)")
        if rr.residual:
            print(f"[fpdiff] residual: {rr.residual}")
        if rr.findings:
            print(f"[fpdiff] next: fpdiff triage {args.job}")
        return 0

    rr = load_findings(job)
    if rr is None and args.command != "coverage":
        print("no findings yet — run `fpdiff run` first", file=sys.stderr)
        return 1

    if args.command == "triage":
        triage_loop(job, rr)
    elif args.command == "report":
        out = render_profile(job, rr, waivers)
        path = job.out_dir / "profile.md"
        path.write_text(out)
        print(out)
        print(f"[fpdiff] written to {path}")
    elif args.command == "coverage":
        cov = coverage_check(job, waivers)
        print(coverage_section(cov))
    elif args.command == "explain":
        from .explain import explain as llm_explain
        fid = args.finding or 1
        f = next((x for x in rr.findings if x.id == fid), None)
        if f is None:
            print(f"no finding #{fid}", file=sys.stderr)
            return 1
        print(llm_explain(f, job.fmt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
