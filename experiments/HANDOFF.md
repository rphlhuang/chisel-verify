# Handoff — state of branch `experiment/fable` (2026-07-10, written by Fable for Opus)

## What exists, in reading order

1. **`RESEARCH_DIRECTIONS.md`** — the two directions, field survey, constraints
   (internship ends 9/11; deliverable = open tool + writeup; open EDA stack, pragmatic
   LLM; LLM never the oracle), 9-week plan, rejected alternatives, fpdiff spike results.
2. **`LITERATURE_REVIEW.md`** — ICLAD 2026 scan (agentic wave; formal+HITL+open corner
   empty), Chisel/CIRCT formal community map (Dobis / btor2-opt / the "missing middle"),
   property-to-monitor prior art (MBAC, verificsva, GHDL-PSL, riscv-formal, PyCaliper
   — the last needs a deeper read before novelty claims).
3. **`fpdiff/`** — PoC #1, formal FP divergence triage (equivalence miters vs golden,
   IEEE decoding, class exploration, waiver ledger). Working; real OpenFloat findings
   (README). User's verdict: good instrument, **not the workflow they want to own** —
   mechanical, needs a golden model, no intent-authoring. Keep as evaluation
   infrastructure and as the waiver-ledger pattern donor.
4. **`tempo/`** — PoC #2, the direction that matches the user's gut feeling (DESIGN.md
   §1 states it explicitly; verify with them). NL+formal properties in one AST →
   compiled monitors → open solvers, HITL triage triangle (bug / fix property / add
   assumption). Demo on the repo's own Axi4LiteMac: hostile-master CEX → 3 signed
   assumptions → **k-induction proof, 0.51s** → mutant caught as genuine bug.

## User context that shapes everything

- Master's research aide at Argonne. Wants **formal-methods
  learning** as a first-class outcome — tempo/DESIGN.md has a component↔concept
  curriculum table; keep extending it and keep the human doing the formal reasoning.
- Not attached to FP (fpdiff's substrate); is attached to HITL, open tooling,
  human-centered flows, and the FLAG idea of NL+formal tied together.
- Skeptical of: benchmarks, agentic hands-free loops, LLM-where-a-script-works
  (their Formal-that-Floats critique — internalize it before proposing LLM features).

## Immediate open threads (roughly prioritized)

1. Show Kaz the OpenFloat findings (`fpdiff/README.md` §findings) — directly serves
   openhwfp-eval's mission; likely redirects priorities.
2. tempo: FPDIV handshake example (bridges both PoCs); internal-signal monitoring;
   `propose` templates for valid/ready ports; interactive triage ledger (port from
   fpdiff/triage.py).
3. The community-shaped endgame: reimplement tempo's compiler as a Chisel library over
   `chisel3.ltl.AssertProperty` (monitors as RegNext logic pre-firtool → `--btor2`
   just works). That fills the gap chiseltest.formal left; Amelia Dobis (Princeton,
   btor2-opt) is the natural reviewer/collaborator.
4. Verify btormc `--kind` output semantics (`unsat`/`b4`) before writeup claims;
   consider rIC3/pono as second engines (both consume the same btor2).
5. PyCaliper deep-read for the related-work section.

## Gotchas that cost time (don't rediscover)

- **yosys ≥0.36 parses SV `assert`/`assume` into `$check` cells; `write_btor` silently
  drops them.** Always `chformal -lower` before `write_btor`, or everything "proves".
- firtool's single-file SV output appends `` `include ``-based verification-layer stubs
  after `----- 8< -----` markers; strip before yosys (fpdiff/miter.py does).
- btor2 witnesses: `#0` = states, `@t` = inputs; inputs may be omitted when unchanged
  (carry last value). Uninitialized regs read `x` in iverilog replay before pipes
  fill — gate comparisons/asserts by warm-up counters (both PoCs do).
- Both PoCs re-validate every solver CEX in iverilog before showing it to a human;
  keep that invariant — it has already caught the difference between modeling
  artifacts and real findings.
- Tools: brew yosys + oss-cad-suite (`~/Documents/utils/oss-cad-suite/bin`, via
  `FPDIFF_TOOLS`/`TEMPO_TOOLS` if PATH lacks them); firtool 1.152 at
  `~/Documents/utils/firtool-1.152.0/bin` (not needed by either PoC — they consume SV).
- openhwfp-eval generates Yosys-friendly SV via `sbt "runMain
  Generate.GenerateAllTestModules"` (clone + submodules; ~1 min).

## How to demo everything in 90 seconds

```bash
cd fpdiff && python3 -m fpdiff run examples/01_selfcheck.json   # proved 0.03s
python3 -m fpdiff run examples/03_openfloat.json                # real findings
cd ../tempo && python3 -m tempo run examples/axi4litemac/project.py          # hostile env
python3 -m tempo run examples/axi4litemac/project_assumed.py    # k-induction proof
python3 -m tempo run examples/axi4litemac/project_mutant.py     # real bug caught
```
