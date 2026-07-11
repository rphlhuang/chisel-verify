"""tempo — NL-annotated temporal-safety properties on the open toolchain.

  python -m tempo run <project.py>   compile monitors, model-check, replay CEX

The project file is a Python module defining PROJECT: tempo.ast.Project.
On a counterexample, the failing properties are reported with their NL intents
and a per-cycle signal table; the human's move is one of:
  bug            -> fix the DUT
  fix property   -> the formal half didn't say what the intent meant; edit it
  add assumption -> the environment was underconstrained; add an assume Prop
                    (this is assume-guarantee reasoning — see DESIGN.md)
then re-run. Verdicts live in the project file itself: it IS the spec ledger.
"""

import importlib.util
import json
import sys
from pathlib import Path

from .engines import run_btormc
from .harness import build
from .replay import replay


def load_project(path: str):
    spec = importlib.util.spec_from_file_location("tempo_project", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PROJECT


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 2 or argv[0] != "run":
        print(__doc__, file=sys.stderr)
        return 2
    proj = load_project(argv[1])
    out_dir = Path(argv[1]).resolve().parent / f"{proj.name}.out"

    n_assert = sum(p.kind == "assert" for p in proj.props)
    n_assume = sum(p.kind == "assume" for p in proj.props)
    print(f"[tempo] {proj.name}: {n_assert} obligations, {n_assume} environment "
          f"assumptions, kmax={proj.kmax}")
    btor = build(proj, out_dir)
    kind = proj.engine.endswith("kind")
    res = run_btormc(btor, proj.kmax, kind=kind)

    if res.status == "safe":
        verdict = ("PROVED (k-induction converged)" if kind
                   else f"NO VIOLATION up to k={proj.kmax} (bounded — not a proof)")
        print(f"[tempo] {verdict}  ({res.elapsed:.2f}s)")
        (out_dir / "findings.json").write_text(json.dumps(
            {"status": "safe", "kmax": proj.kmax, "kind": kind}, indent=2))
        return 0

    print(f"[tempo] VIOLATION found at k={len(res.frames)-1}  ({res.elapsed:.2f}s); "
          f"replaying in iverilog...")
    rep = replay(proj, out_dir, res.frames)
    intents = {p.id: p for p in proj.props}
    failing = []
    for f in rep["fails"]:
        pid = f.split()[2].rstrip(":")
        failing.append(pid)
    print()
    for line in rep["table"]:
        print("   ", line)
    print()
    if failing:
        for pid in sorted(set(failing)):
            p = intents.get(pid)
            print(f"[tempo] FAILED {pid}: {p.intent if p else '?'}")
        print("[tempo] triage: bug in DUT / fix the property / add an environment "
              "assumption — then re-run.")
    else:
        print("[tempo] WARNING: btormc violation not reproduced by iverilog "
              "(modeling artifact?) — inspect replay_tb.v")
    (out_dir / "findings.json").write_text(json.dumps(
        {"status": "cex", "k": len(res.frames) - 1, "failing": sorted(set(failing)),
         "trace": rep["table"]}, indent=2))
    return 1


if __name__ == "__main__":
    sys.exit(main())
