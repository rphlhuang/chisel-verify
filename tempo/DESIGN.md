# tempo — design document

*2026-07-10, branch `experiment/fable`. Read `LITERATURE_REVIEW.md` first.*

## The gut feeling this is built from

Restating what I understood from the user (so it can be corrected if wrong):

> fpdiff is a good instrument, but it's a *checker*, not a *workflow I'd inhabit*. The
> creative act in verification is **authoring intent** — deciding what should be true of a
> design and saying it precisely — not diffing two implementations (which needs a golden
> model nobody has, and where a deterministic script beats an LLM anyway, per the
> Formal-that-Floats critique). I want the FLAG sentiment — natural language and formal
> meaning tied together in one artifact — applied broadly (protocols *and* datapaths, since
> I don't particularly care about FP), fully open, HITL at the point where human judgment
> is genuinely needed. And I want to *learn formal methods* by building it, not just wire
> up solvers.

**tempo** is that: a property layer where every property is one object carrying its
natural-language intent and its formal meaning, compiled to plain synthesizable monitor
registers so it runs on the entire open stack (the 7/9 temporal walls never apply), with a
triage loop where human verdicts become part of the specification.

## Why this is technically possible despite "LTL is doomed on open tools"

The 7/9 investigation showed: open Yosys can't parse SVA temporal syntax (Verific wall),
and firtool can't lower `!ltl.property` to btor2 (unimplemented pass). Both walls are about
*shipping temporal operators to the backend*. tempo never does that. It compiles the
**bounded temporal safety fragment** — delays, implication, stability, bounded response
windows — into helper registers + a single boolean `assert` per property, *before* any
backend sees it. This is exactly how riscv-formal verifies real RISC-V cores and how
Yosys' own Verific frontend works internally (NFA→DFA monitor FSMs in `verificsva.cc`);
tempo is that lowering, liberated from the proprietary frontend, with an authorable AST
on top. What's genuinely excluded is unbounded liveness — and practicing engineers bound
their liveness anyway ("a response within 64 cycles", not "eventually").

## The formal-methods curriculum embedded in this project

This is a first-class goal: each component *is* a classic formal-verification concept,
learned by implementing or operating it. The map:

| tempo component | Formal method you learn hands-on |
|---|---|
| Monitor compilation (`compiler.py`) | Safety vs. liveness; temporal operators as automata; why "bad prefix detectable by finite monitor" *defines* safety; the `past()`/helper-register idiom every formal engineer knows |
| `within(m,n)` obligation shift-register | Pending-obligation tracking = the NFA powerset trick specialized to bounded windows; overlapping activations and why naive "one counter" monitors are wrong |
| `disable iff` handling | Resets in formal; why obligations must be *cancelled*, not just gated |
| Environment assumptions (`assume` monitors) | **Assume–guarantee reasoning**: verifying an open system means constraining its environment; a slave can't be correct against a hostile master |
| Triage verdict "add assumption" | The most common real-world formal outcome: the property was right, the *universe* was underspecified. Learning to tell this apart from a bug is the core skill of an FV engineer |
| BMC (`btormc --kmax N`) vs k-induction (`--kind`) | Bounded proof vs unbounded proof; why BMC-pass isn't a proof, why induction fails without strengthening invariants, what "k-inductive" means — surfaced in the tool's own verdict language |
| Vacuity / cover checks | A property that can't fire proves nothing; `cover` as the dual of `assert` |
| CEX replay in a second simulator | Witness formats; the difference between a model of the design (btor2) and the design (RTL); why cross-validation catches modeling artifacts |
| (fpdiff, already built) | Equivalence checking, miters, input-space case-splitting, formally-backed waivers |

A deliberate consequence: the writeup can honestly say "the tool's author implemented the
safety-monitor construction from first principles" — which is worth more, as learning and
as credibility, than calling Jasper.

## Architecture (PoC scope)

```
tempo/
  DESIGN.md            this file
  README.md            usage + demo results
  tempo/
    ast.py             Property AST: NL intent + formal structure, one object
    compiler.py        AST -> synthesizable Verilog monitor (regs + boolean assert)
    harness.py         DUT + monitors top-level; yosys -> btor2 (chformal -lower!)
    engines.py         btormc BMC / k-induction driver + witness parser (from fpdiff)
    replay.py          iverilog CEX replay -> per-cycle trace table (from fpdiff)
    triage.py          findings ledger: bug | fix-property | add-assumption verdicts
    cli.py             tempo run/report <project.py>
  examples/
    axi4litemac/       the repo's own AXI-Lite MAC: protocol properties + env assumptions
    fpdiv_handshake/   hardfloat DivSqrt valid/ready timing (protocol-on-FP bridge)
```

### The AST (FLAG's sentiment, minus the parsing)

A property is *one object* holding NL and formal meaning:

```python
Prop("write_resp_held",
     intent="Once BVALID asserts, it must stay asserted (with stable BRESP) until BREADY",
     formal=implies(expr("bvalid && !bready"),
                    next_(expr("bvalid") & stable("bresp"))),
     kind="assert", provenance="human")
```

Boolean leaves are raw Verilog expressions (strings) — the AST owns the *temporal*
structure only. This is a deliberate scope cut: no boolean-expression parser to write, and
leaves stay readable to any RTL engineer. Node set (bounded-safety fragment):

- `expr(sv)` — boolean leaf
- `past(x,n)`, `stable(x)`, `rose(x)`, `fell(x)` — history operators (RegNext chains)
- `delay(p, n)` — `##n` shift
- `implies(a, c)` / `implies_next(a, c)` — `|->` / `|=>`
- `within(a, m, n, c)` — `a |-> ##[m:n] c`, the bounded-eventually workhorse
- top-level: implicit `always`, plus `disable_iff(rst)` per property
- `kind`: `assert` (obligation on DUT) or `assume` (constraint on environment) — the
  **same compiler** emits both; an assumption is just a monitor whose verdict binds the
  universe instead of the design. `cover` for vacuity.

Provenance field: `human | template | llm` — LLM-proposed properties are first-class but
*labeled*, and never become load-bearing without a human moving them to the ledger
(same LLM-is-never-the-oracle stance as fpdiff).

### Monitor construction sketches (the teaching core, implemented in compiler.py)

- `past/stable/rose/fell`: `reg x_p; always @(posedge clk) x_p <= x;`
- `implies_next(a,c)`: `reg a_p; assert(!a_p || c)` — one flop, the whole `|=>`.
- `within(a,m,n,c)`: pending shift register `p[0..n]`; each cycle `p` shifts and `p[0]`
  loads `a`; when `c` holds, bits `m..n` clear (a response satisfies every in-window
  request); **fail** = a bit shifting past `n` unsatisfied. Handles overlapping
  activations correctly — the case naive counter monitors get wrong.
- `disable_iff(rst)`: `rst` clears all pending/history regs and gates the assert — an
  aborted transaction owes nothing.
- Every emitted monitor also gets, under `` `ifdef TEMPO_SIM ``, a `$error` with the
  property id + **NL intent string**, so the same file is the formal property and the
  simulation checker (cocotb/Verilator/Icarus). One artifact, both worlds — the
  sim↔formal boundary erased at the property level.

### Flow

`tempo run project.py` → compile monitors → generate harness top (DUT + monitors, reset
sequencing as in fpdiff) → yosys (`read_verilog -formal`, `prep`, `chformal -lower`,
`write_btor`) → btormc BMC (and `--kind` when asked) → on CEX: iverilog replay, per-cycle
table of the signals the failing property mentions, annotated with the property's NL
intent → human verdict: **bug** (file it) / **fix property** (edit the AST — the property
was wrong) / **add assumption** (the environment was underconstrained; the new `assume`
is a signed ledger entry, and its NL intent documents the interface contract you just
discovered). Verdicts + assumptions persist as the project's specification ledger — the
tempo analog of fpdiff's waiver ledger, and the artifact that makes the flow HITL rather
than push-button.

### What stays out of the PoC (documented, not forgotten)

- Unbounded liveness (out of the fragment, honestly); `s_until` etc. — later.
- Interactive TTY triage & LLM proposal (`propose` = port-pattern templates for
  valid/ready handshakes — deterministic where a script belongs — with optional LLM
  drafting of NL intents; fpdiff already demonstrates both patterns, reuse later).
- Chisel-native embedding: the honest end-state is this compiler as a Scala library over
  `chisel3.ltl.AssertProperty` (monitors materialized as Chisel `RegNext` logic before
  firtool, making `--btor2` Just Work). That is the community-shaped contribution and a
  candidate headline for the writeup; the Python PoC de-risks the construction first.
- Deeper PyCaliper comparison before any novelty claim in a writeup.
