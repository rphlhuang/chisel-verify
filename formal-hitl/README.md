# formal-hitl

An early, experimental **LLM-driven, human-in-the-loop (HITL) formal verification**
pipeline, exercised here against a small variable-width Chisel adder as a
proof-of-concept.

It's a from-scratch, open-source reimplementation of the workflow described in:

- Mohanty, Naduvodi Viswambharan, Gadde, *"Formal that 'Floats' High: Formal
  Verification of Floating Point Arithmetic"* (arXiv:2512.06850, 2025)
- Gadde et al., *"Hey AI, Generate Me a Hardware Code! Agentic AI-based Hardware
  Design & Verification"* (arXiv:2507.02660, 2025)

Both papers use LLM-generated SVA, a generate→critique→correct→execute loop, and
**Cadence JasperGold** as the formal engine. This project targets the fully
open-source stack instead: **Chisel → SystemVerilog → Yosys/SymbiYosys (`sby`)**.

## The three-role design (read this before extending anything)

The whole point of this system is to keep three roles cleanly separated, because
each one can soundly answer a different question and *only* that question:

1. **The formal engine (`harness.py` + `sby`) decides truth-of-RTL.** "Does
   property φ hold on this RTL?" is decidable (modulo solver power) and the
   engine answers it soundly. It is never asked whether a property is "the
   right property" — only whether it holds.
2. **The LLM (`llm.py`, `loop.py`) supplies an external prior.** It proposes
   candidate properties — cheap, broad, informed by everything it has seen
   about designs like this one. It is a *generator of hypotheses*, never a
   judge of correctness.
3. **The human (the web UI) decides faithfulness-to-intent.** "Is this
   property what I actually meant? Is this failure a real bug or a missing
   assumption?" is not a formal question and cannot be delegated. The system's
   whole job is to make that judgment as cheap as possible, by handing the
   human a concrete counterexample trace instead of an abstract SVA to audit
   in their head.

**The counterexample presentation is the product.** The most valuable output of
a run is a property the LLM's prior expected to hold but that the RTL actually
*fails* — a corner case nobody thought to check by hand. Everything about the
CEX/waveform panel exists to make that legible in one glance.

Do not let future work drift into "LLM writes assertions, we measure pass rate."
The engine adjudicates; the human judges faithfulness; the LLM only proposes.

## Honest caveat

The adder under test is trivial (essentially one assignment). This PoC validates
the *pipeline* — plan → generate → prove/disprove → present → adjudicate →
refine, fully audited end to end — not any research claim about adders. The
injected bugs in `dut/AdderVariants.scala` exist purely to give the CEX/HITL
path something real to exercise; a correct trivial adder alone would produce a
table of green rows and demonstrate nothing.

## Pipeline

```
NL intent  --(LLM: plan)-->  vPlan (property intents)
           --(LLM: generate)-->  structured SVA properties (PropertySpec)
           --(harness.py: execute)-->  sby BMC per property --> PROVEN / FAILED / ERROR
           --(app.py: present)-->  property table + rendered waveform for failures
           --(human: adjudicate)-->  real_bug / vacuous / missing_assumption / edge_case_forgot
           --(LLM: refine)-->  regenerated properties, bounded to 3 cycles
```

Properties are not raw SVA text from the LLM. To stay inside the subset of SVA
that open-source Yosys can actually elaborate (no `assert property (@(posedge
clk) ...)` concurrent-assertion syntax — that requires the proprietary Verific
frontend), the LLM instead returns a structured `{name, kind, antecedent,
consequent}` tuple, and `harness.py` renders that into a plain immediate
assertion inside a clocked `always` block. This also makes a bad LLM-generated
expression fail to *elaborate* (routed to `ERROR`, then to refine) cleanly
separable from a property that elaborates fine but the RTL genuinely violates
(routed to the human as `FAILED`).

Every property is proven independently: one `sby` invocation per assertion
(all currently-active `assume`-kind properties are included as constraints in
every run). This keeps each counterexample attributable to exactly one
property instead of getting lost behind whichever assertion `smtbmc` happens
to hit first.

## Setup

```bash
cd formal-hitl
python3 -m venv .venv   # use a 3.12/3.13 interpreter -- some deps don't yet
source .venv/bin/activate  # have 3.14 wheels
pip install -r requirements.txt

cp .env.example .env
# edit .env: set LLM_API_KEY to a free Groq key from https://console.groq.com/keys
# (Groq's free tier needs no credit card; llama-3.3-70b-versatile is one of
# the models the papers used. Since llm.py only speaks the OpenAI-compatible
# chat-completions API, pointing this at a local Ollama/vLLM endpoint or an
# ALCF-hosted model later is a matter of changing LLM_BASE_URL/LLM_MODEL only.)

python check_env.py   # confirms yosys, sby, a solver, and the Python deps
```

`sby` (SymbiYosys) and a solver (Bitwuzla/Boolector/Yices/z3) must be on
`PATH` — install the [oss-cad-suite](https://github.com/YosysHQ/oss-cad-suite-build)
bundle and `source /path/to/oss-cad-suite/environment`.

**macOS note:** if `sby --version` fails with a `dyld`/library-load error,
Gatekeeper has quarantined the bundle's own Python. Fix with:
```bash
xattr -dr com.apple.quarantine /path/to/oss-cad-suite
```

### Generating the DUT variants

The adder variant family lives in `dut/AdderVariants.scala` (wired into the
root `build.sbt` as an extra unmanaged source directory) and shares the exact
port interface of the repo's existing `arithmetic.Adder` (`a`, `b`: `width`
bits in; `s`: `width+1` bits out; Chisel's usual `clock`/`reset`). From the
repo root:

```bash
sbt "runMain arithmetic.AdderVariantsMain 8"   # width defaults to 8
```

This emits SystemVerilog for all six variants into
`formal-hitl/generated/<variant>/w<width>/` (width-scoped, so generating a new
width doesn't silently invalidate `.sv` already generated for another width —
running the loop at a given width requires that width to have been generated
first):

| Variant | Bug |
|---|---|
| `Golden` | none — reference behavior (`a +& b`) |
| `TruncatingAdd` | uses `+` instead of `+&`, drops the carry-out |
| `OffByOneWidth` | output wire one bit too narrow, silently truncates |
| `SwappedOperand` | computes `a + a` instead of `a + b` |
| `WidthDependentBug` | correct for `width <= 8`, wrong above it (`sbt "runMain arithmetic.AdderVariantsMain 16"` then run the loop at width 16 to see it fail) |
| `RegisteredBuggy` | pipelined (registers `a`/`b`/`s` across clock edges) + `TruncatingAdd`'s bug — multi-cycle CEX waveforms |

## Running

```bash
cd formal-hitl
source /path/to/oss-cad-suite/environment   # sby/yosys on PATH
source .venv/bin/activate
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`, pick a variant and width, click **Run loop**.
The property table fills in live (poll-based) as plan → generate → execute
progress. Click any red (`FAILED`) row to open the counterexample panel: a
WaveDrom-rendered waveform plus concrete `a` / `b` / observed `s` / expected
`s`. Use the four adjudication buttons to record your judgment; submitting
kicks off a bounded refine cycle (`loop.MAX_REFINE_CYCLES = 3`) that
regenerates the affected properties and re-executes, updating the table in
place.

You can also drive the loop headlessly for smoke-testing:

```bash
python loop.py Golden 8
python loop.py TruncatingAdd 8
python loop.py RegisteredBuggy 8
```

## Audit trail

Every run writes `formal-hitl/runs/<timestamp>/`:

- `llm/*.json` — every prompt and raw completion, one file per call
- `sby/<property_name>/` — the rendered `formal_tb.sv`, the DUT copy, the
  `.sby` file, and the full `sby` work directory (logs, VCD, SMT2)
- `transcript.jsonl` — a running, structured log of every plan/generate/
  execute/adjudicate/refine event, human-readable line by line

## Extension seams (intentionally not built in v0)

Three things this version deliberately leaves as clean, marked seams rather
than half-building them:

- **`# SEAM: coverage`** (`loop.py`, in `execute()`) — where per-property
  coverage collection (the paper's Table II) would run, right after each
  property's `execute()` call.
- **`# SEAM: cocotb-replay`** (`harness.py`, in `extract_counterexample()`) —
  where a concrete CEX (`a`, `b`, and the reference-model expected `s`) would
  be turned into a re-runnable cocotb stimulus for the existing
  `tests/Adder`-style simulation flow.
- **`# SEAM: vacuity-rank`** (`loop.py`, in `execute()`, before results reach
  the human) — where a vacuity check (does the antecedent/assumption set ever
  hold?) and an information-theoretic ranking of surviving properties would
  run, so the human sees the most informative results first.

## Known limitations of this PoC

- The reference "expected `s`" shown in a CEX is a hardcoded `a + b` — a
  domain-specific shortcut for this one design, not a general symbolic
  evaluator of arbitrary property consequents.
- The LLM (llama-3.3-70b-versatile via Groq) occasionally emits mildly
  malformed JSON (most commonly: forgetting one closing `}` before an array's
  closing `]`). `loop._extract_json` includes a bracket-repair pass and a
  bounded retry-with-correction loop for this; genuinely wrong property
  *logic* (e.g. a nonsensical carry-check formula) is left alone and shows up
  as a `FAILED` result for the human to adjudicate as `vacuous` — that's the
  system working as intended, not a bug.
- The frontend uses polling (1s) rather than a push/streaming channel for
  progress updates. Fine for a single local user; would need SSE/WebSockets
  for anything more.
