# Research Directions — Summer 2026

*Written 2026-07-10 on branch `experiment/fable`. This doc formalizes two candidate directions
for the remaining ~9 weeks (through 9/11), picks one to build, and records the reasoning so the
choice can be re-litigated later with full context.*

## Ground rules (fixed constraints)

- **Deliverable**: a working open-source tool + writeup. Publication optional, community
  usability mandatory. Start unambitious; layer extensions only if the core lands.
- **Toolchain**: fully open (Yosys/sby/eqy, btormc/rIC3/pono/bitwuzla, Verilator, cocotb,
  firtool). LLM is pragmatic (API models fine) — the reproducibility claim is about the EDA stack.
- **Evaluation substrate**: [openhwfp-eval](https://github.com/hwspec/openhwfp-eval)
  (berkeley-hardfloat, OpenFloat, rial) + this repo's Chisel/cocotb harness. Real FP RTL, not
  benchmark suites.
- **Center the human hardware designer.** The flow must map onto something an engineer
  actually does, not a leaderboard.

## Where the field is (July 2026), in five sentences

LLM→SVA generation is saturated (AssertLLM/2, AssertionForge, ChIRAAG, FLAG, ChatSVA,
QiMeng-CodeV-SVA, …), and [Are LLMs Ready for Practical Adoption for Assertion
Generation?](https://arxiv.org/abs/2502.20633) (Pal et al.) shows COTS LLMs still emit a large
fraction of syntactically/semantically wrong assertions. Agentic design has gone hands-free and
benchmark-complete — NVIDIA's [HORIZON](https://arxiv.org/abs/2606.28279) hits 100% across
ChipBench/RTLLM/VerilogEval — which mostly proves the benchmarks are exhausted, and HORIZON's own
§5 admits agents overfit their evaluators and that *independent* acceptance signals (reference
models, formal equivalence, held-out oracles) are the missing safeguard. [Formal that "Floats"
High](https://arxiv.org/abs/2512.06850) (Dec 2025) verifies a combinational FP32 adder by
RTL-to-RTL model checking against a golden reference with LLM-drafted, human-refined helper
lemmas — **entirely on Cadence Jasper**, and only for one adder. [FLAG](https://arxiv.org/abs/2504.17226)
shows generate-then-filter (grammar templates → SAT filter → LLM filter) works for protocol
properties. Nobody has published any of this on an open toolchain, and nobody has characterized
where the open FP libraries actually deviate from IEEE-754.

## The one technical fact everything below rests on

Yesterday's investigation established that both open formal routes for Chisel/LTL die at
temporal operators: open Yosys can't *parse* SVA temporal syntax (no Verific), and firtool's
btor2 backend can't *lower* `!ltl.property` (unimplemented pass, firtool 1.152). The surviving
intersection is **boolean safety properties on arbitrary sequential circuits** — btor2 BMC/k-induction
handles sequential *state* fine; it's temporal *property syntax* that's walled off. Fixed-delay
temporal safety can always be hand-compiled into helper registers (the riscv-formal/chiseltest
`past()` trick). Liveness is genuinely out of reach.

**Equivalence checking of FP datapaths is boolean safety.** A miter (two designs, shared
inputs, assert outputs equal) needs zero temporal operators for combinational units
(hardfloat's AddRecFN/MulRecFN) and only helper-register plumbing for iterative ones
(DivSqrtRecFN_small). The expressiveness ceiling that killed yesterday's pivot does not apply
to the strongest known methodology for FP verification. That is the opening.

---

## Direction 1 (BUILD THIS): `fpdiff` — formal divergence triage for open FP hardware

**One-liner:** `git diff` for floating-point RTL semantics: an open-toolchain workbench that
formally diffs an FP implementation against a reference, decodes every divergence into
IEEE-754 terms a human can adjudicate, and turns human verdicts into formal assumptions —
iterating until the diff is empty or every divergence is signed off.

### The workflow (what the engineer experiences)

1. **Point** `fpdiff` at a DUT and a reference with an IEEE-format interface (hardfloat's
   FN wrappers are the golden model; OpenFloat/rial/your-accelerator's-FPU are DUTs).
   Tool auto-builds the miter and picks an engine: `sby` prove for combinational,
   btormc/rIC3 BMC with helper registers for iterative units.
2. **Run.** Either `PROVED EQUIVALENT` (exhaustive — something 24 random vectors in a
   ChiselSim test can never say), or a counterexample.
3. **Triage.** The counterexample is decoded — not `a=0x0080, b=0x8001` but *"a = smallest
   normal, b = negative subnormal; DUT flushes subnormal inputs to zero, reference rounds
   RNE; outputs differ by 1 ulp"* — and clustered with other CEXes by input class
   (subnormal/inf/NaN/zero/normal × sign × rounding mode). The human issues a verdict per
   cluster: **bug**, or **accepted deviation** (e.g. "OpenFloat documents flush-to-zero;
   waive subnormal inputs").
4. **Waive = assume.** An accepted deviation becomes a machine-generated, human-reviewed
   `assume` on the miter inputs. Re-run. New divergences surface from behind the waived
   ones. Repeat until clean.
5. **Report.** The output artifact is a *human-signed compatibility profile*: "OpenFloat
   FP32 add ≡ IEEE-754 RNE **except**: subnormal inputs (FTZ, waived by rhuang 8/02),
   NaN payload propagation (nonstandard, waived), overflow-to-inf boundary (BUG #3, open)."
   Plus the proof logs that make each line machine-checked.

### Why this is the right shape

- **Human-centered for real.** The human's job is *adjudication* — the one thing neither the
  LLM nor the solver can do, because "is FTZ acceptable?" is a requirements question, not a
  math question. This mirrors the waiver workflows engineers already run for lint/CDC signoff;
  it is a flow, not a benchmark. The saturated literature has the LLM generate properties and
  hopes they're right; here **the LLM is never the oracle** — solvers adjudicate facts, humans
  adjudicate intent.
- **It answers HORIZON §5 concretely.** Independent reference model + formal equivalence as
  the acceptance signal, with a human holding the waiver pen — exactly the safeguard the
  agentic camp says it lacks. (This is the honest version of the old "HITL as
  anti-reward-hacking" framing: now attached to an oracle that can't be gamed.)
- **Open-source novelty, not capability novelty.** Formal-that-Floats-High proved the
  methodology on Jasper for one adder. First public replication on a fully open stack, plus
  the waiver-refinement loop (which they don't have — their HITL edits properties, ours
  refines assumptions), plus application across three real libraries. Nothing here fights
  Verific/Jasper on their turf.
- **Immediately useful to the group.** This *is* openhwfp-eval's mission with a stronger
  instrument: it upgrades "20 random floats match Scala's `+`" to "formally characterized
  against IEEE-754 with a signed deviation ledger." OpenFloat's own testbench needs
  `relTol=1e-5` to pass — meaning real divergences are sitting there waiting to be
  characterized. Day-one findings are nearly guaranteed.
- **Unambitious core, honest stretch.** Week-one demo is a miter + sby on FP16 add. The f32
  multiplier will likely choke SAT solvers — *where* each open engine gives up
  (per precision × op × engine) is itself a deliverable table nobody has published.

### Where the LLM helps (all optional, all human-gated)

- Drafting the decoded natural-language explanation of a CEX cluster.
- Translating a human's informal waiver ("subnormals don't count") into the `assume`
  expression, which the human reviews and the solver then treats as ground truth. A wrong
  assumption can mask bugs, so each waiver gets a vacuity check (assumption must not make the
  miter's input space empty / must leave the covered classes reachable).
- Proposing case-split lemmas when a proof diverges (sign/exponent-class decomposition à la
  Formal-that-Floats), each dispatched to the solver as its own obligation.

### Evaluation plan (no benchmarks, all measurable)

1. **Mutant recall**: inject known bug classes into hardfloat wrappers (rounding-bit drop,
   sticky-bit error, sign flip on zero, exponent off-by-one); measure found/proved-absent.
2. **Real findings**: OpenFloat and rial FP16/BF16/FP32 add/mul vs hardfloat golden —
   publish the divergence profiles. These are new facts about libraries people use.
3. **Engine capability table**: {sby+smt, btormc, rIC3, pono+bitwuzla} × {f16, bf16, f32}
   × {add, mul, div} — prove time / timeout / CEX time. The documented open-tool boundary.
4. **Triage-loop usability**: can a non-author (Kaz, Connor) drive a full waive-rerun-signoff
   cycle on OpenFloat? Qualitative but real HITL evidence.

### 9-week sketch

| Weeks | Milestone |
|---|---|
| 1–2 | Miter generator + engine driver CLI; FP16 add proved/CEX'd end-to-end |
| 3 | CEX decoder (bits → IEEE semantics) + clustering; first OpenFloat findings |
| 4 | Waiver → assumption loop with vacuity check; compatibility-profile emitter |
| 5–6 | Evaluation: mutants, cross-library sweep, engine table; sequential (div/sqrt) BMC attempt |
| 7 | LLM assists (CEX explanation, waiver translation); minimal web/TUI front end if time |
| 8–9 | Writeup, README-grade docs, repo cleanup, handoff |

### Feasibility spike (ran 7/10, before committing to this direction)

Using openhwfp-eval's own generated SV (`FPADD_8_24`, `FPMUL_8_24` — hardfloat FP32 wrappers),
a Yosys miter exported to btor2 and dispatched to btormc:

| Experiment | Result | Time |
|---|---|---|
| FP32 add, golden vs self | proved equivalent (depth-0 BMC = complete for comb.) | **0.02 s** |
| FP32 add, golden vs rounding mutant (`\|`→`&` in underflow term) | CEX found | **0.05 s** |
| CEX validated in iverilog on both designs | outputs differ by exactly 1 ulp | — |
| CEX decoded | golden == Python RNE reference; mutant 1 ulp off at a rounding boundary | — |
| FP32 **mul**, golden vs self | proved | 0.01 s |
| FP32 mul, golden vs rounding mutant | CEX found — on a *subnormal* operand | 0.03 s |

(For contrast: the same add miter through yosys' built-in minisat `sat -prove` took 4 minutes.
Engine choice is the whole game; that's why the engine capability table is a deliverable.)

Two honest caveats. (1) Mutant miters share circuit structure with the golden, which SAT
solvers exploit; a cross-*implementation* multiplier miter (OpenFloat vs hardfloat) will be
much harder — that's a planned boundary experiment, not an assumed win. (2) Yosys' btor2
export models don't-care shift bits as masked free inputs; verified benign here, and the
sim-validation step catches any modeling artifact by construction.

### PoC outcome (built same day — see `fpdiff/`)

The PoC exists and the full loop runs: miter generation (combinational and pipelined
with latency alignment), btormc checking, iverilog cross-validation of every CEX,
IEEE-semantic decoding, class-pair exploration, signed waiver ledger with input assumes
and output relaxations (NaN-canonical, N-ulp, subnormal-flush), coverage check for
assumed-away classes, compatibility-profile emitter, optional LLM narration. First
session against OpenFloat's FP32 adder produced real findings in seconds: `0+0 = 2.35e-38`,
`x+(−x) = 3.17e29`, unbounded ulp error under near-cancellation (no guard/sticky bits),
no gradual underflow, no NaN/inf semantics — none of which openhwfp-eval's random
`relTol` testbench can see. The `fpdiff/README.md` has the details.

### Risks and their honest disposition

- **f32 mul won't prove** — expected; falls to BMC-with-depth-1 (combinational ⇒ BMC *is*
  complete here, actually: depth-1 BMC of a combinational miter is full equivalence; the
  risk is solver time on multiplier SAT instances, mitigated by case-split lemmas and by
  reporting the boundary honestly).
- **Yosys chokes on firtool SV** — low risk: openhwfp-eval already generates
  "Yosys-friendly" SV (Kaz's own firtool flags) for OpenROAD area flow.
- **OpenFloat diverges *everywhere*, drowning triage** — then clustering/waivers are the
  product demo, and the profile says "not IEEE, here is its actual contract," which is a
  publishable finding about a library that advertises FP correctness.

---

## Direction 2 (documented for handoff): `spec-mirror` — IEEE-754 obligation audit of existing testbenches

**One-liner:** a sim-first tool that reads the testbench a human already wrote, diffs it
against a machine-readable checklist of IEEE-754 verification obligations, reports what the
tests *don't* exercise, and generates targeted cocotb cases (softfloat oracle) for the gaps —
with human triage of failures building the same signed compatibility profile as Direction 1.

### Mechanics

1. A curated obligation checklist per FP op, each entry keyed to an IEEE-754 §: subnormal
   in/out, ±0 identities, ±inf arithmetic, qNaN/sNaN propagation and payloads, all five
   rounding modes, exception flags, exponent-boundary cases, catastrophic cancellation.
   (Seeded from TestFloat's level-1/2 case enumeration, so it's grounded, not vibes.)
2. Instrument the existing ChiselSim/cocotb run (VCD or poke-log) and map which obligations
   the current vectors actually hit. openhwfp-eval's own suites — 24 values in
   (−10⁴, 10⁴), RNE only, flags ignored — would score strikingly low, which is the demo.
3. Emit gap report; generate targeted cocotb tests per unmet obligation with
   softfloat (`sfpy`/TestFloat vectors) as oracle.
4. Failures go through the same triage: bug / tolerance / documented-unsupported → the
   library's compliance profile.

### Why it's credible

- Grounded in an observed real gap (this repo's and openhwfp-eval's actual tests).
- "Audit what the human wrote" inverts the saturated "generate from scratch" framing and is
  intrinsically HITL — the starting point is the engineer's own artifact.
- No solver-scaling risk; Verilator + softfloat handles f64 as easily as f16. Exhaustive
  f16 (2³² input pairs) is even brute-forceable overnight.
- TestFloat exists but doesn't audit *your* tests, doesn't integrate cocotb, and doesn't
  produce a deviation ledger; positioning is clean but thinner than Direction 1.

### Why it's second

Closer to the saturated test-generation space; the checklist is curation work rather than
research; and it forfeits the "exhaustive" claim that makes Direction 1's reports
qualitatively stronger than what openhwfp-eval already does. But it composes with
Direction 1 (same triage core, same profile schema, simulation oracle instead of formal) —
if Direction 1's solvers disappoint, this is the soft landing, and the shared code
(FP decode, clustering, profile emitter, cocotb harness) is deliberately reusable.

---

## The unifying thesis (for the writeup, whichever direction survives)

> The deliverable of verification is not a pass/fail bit; it is a **human-signed deviation
> ledger** backed by oracles that cannot be gamed. LLMs translate between human intent and
> formal artifacts; solvers and reference models adjudicate facts; humans adjudicate intent.
> All of it runs on tools anyone can download.

## Explicitly rejected

- **Another LLM→SVA generator** (saturated; Pal et al. show correctness rates too low to
  trust without an oracle anyway).
- **Agentic hands-free loops** (HORIZON owns it, benchmarks saturated, reward-hacking
  unresolved — we build the safeguard instead).
- **Chisel LTL / temporal properties through open tools** (dead-ends mapped yesterday at
  both ends of the toolchain; revisit only if CIRCT lands LTL→btor2 lowering).
- **Information-theoretic property ranking** (rigor theater on miscalibrated priors; dropped
  previously, stays dropped).
- **AXI/protocol verification as the centerpiece** (needs the temporal subset that's walled
  off; FLAG covers the generate-then-filter angle with commercial-adjacent assumptions).
