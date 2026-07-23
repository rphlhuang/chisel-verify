# formal-probe

A **standalone, rarely-run** capability probe for the open Chisel formal path:

```
Chisel --emitCHIRRTLFile--> .fir --firtool --btor2--> .btor2 --btormc--> SAT/UNSAT
```

It answers one question: *which LTL/SVA constructs actually lower to a checkable
BTOR2 model in the current toolchain?* The lowerable fragment shifts between CIRCT
releases, so the **version-stamped table this prints is the artifact**, not the code.

This folder is intentionally decoupled from the root sbt build — it has its own
`build.sbt` and compiles nothing from the main tree, so it never slows the main
build and can be deleted or gitignored freely.

## Run

```bash
./run.sh
```

Needs `firtool` and `btormc` on `PATH` (same as the root `make formal` flow).
First run resolves Chisel from the coursier cache and takes a few seconds.

## What it emits

One tiny module per construct, each with exactly **one** `AssertProperty` so a
`bad` index in the BTOR2 maps to a single construct. The table classifies each:

| column | meaning |
|--------|---------|
| `hw`   | `verif.clocked_assert` ops in `firtool --ir-hw` — survived Chisel + FIRRTL folding (the robust denominator) |
| `bad`  | `bad` instructions in the emitted `.btor2` — reached the model checker |
| `res`  | residual: a dangling `18446744073709551615` (2^64−1) operand id ⇒ an unlowered LTL op leaked |
| `verdict` | `PASS` (UNSAT) / `FAIL` (SAT + witness) / `ERROR` / `SKIP` |

The five outcome buckets: **didn't elaborate** (sbt emit failed) · **rewritten**
(`|=>` → `warmedUp(n) && past(n) |-> b`) · **folded/vacuous** (`hw>bad`, no `bad`)
· **residual LTL op** (`res=yes`) · **checked** (btormc verdict).

## Constructs probed

- `ProbeOverlap` — overlapping `|->` → **PASS** (lowers to `implies`)
- `ProbePastGuarded` — `past(1)` under `|->`, guarded by `warmedUp(1)` → **PASS**
- `ProbePastUnguarded` — same without the guard → **PASS here**, but see the note:
  the reset-boundary hazard is design-dependent (in `arithmetic.Mac` the same
  construct FAILs). The guarded form is sound regardless.
- `ProbeNonOverlap` — `|=>` → **ERROR/residual** (builds `ltl.delay` + `ltl.concat`,
  which upstream `LowerLTLToCore` has no pattern for)
- `ProbeDelay` — `.delay(1)` → **ERROR/residual**
- `ProbeFold` — `a === a` → **SKIP/vacuous** (folds to `true` before the HW stage)

## Provenance

`|=>` never lowered upstream (the thesis NOI/concat pattern lowering stayed on
Amelia Dobis's branch); the supported temporal primitive is now `ltl.past`
(`seq.shiftreg`), wired into the btor2 pipeline by CIRCT PR #9892 (Mar 2026).
The `warmedUp(n)` mask here is a local copy of the main tree's
`formal.FormalUtils.warmedUp` — the reset guard the upstream `past` lowering omits.
