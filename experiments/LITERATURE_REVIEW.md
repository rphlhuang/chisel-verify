# Literature Review — the neighborhood as of July 2026

*Written 2026-07-10 (Fable), for direction-setting and handoff. Companion to
`RESEARCH_DIRECTIONS.md` (which predates this and covers FLAG / HORIZON / AssertionBench /
Formal-that-Floats in depth) and `tempo/DESIGN.md` (which builds on this review).*

## 1. ICLAD 2026 accepted papers ([iclad.ai/accepted-papers](https://iclad.ai/accepted-papers))

Scanned all 22 long + 12 short papers. The distribution tells the story:

- **~90% is LLM-agents-for-EDA**: RTL/analog/CAD generation, multi-agent frameworks (MACO,
  CircuitLM, HeaRT, CHICO-Agent, RF-Agent), physical design assistants (MapTuner, AutoTimer,
  STELLAR-3D), and a heavy benchmark culture (Pluto, GenBen, VHDL-REPOBENCH, WaveformQA,
  SpecAssess).
- **Verification-adjacent papers, all agentic/dynamic**: *VeriTrace: Human-Like Temporal
  Exploration Completes Agentic Action Space* (Cunxi Yu — same author as HORIZON);
  *Inference-Time Scaling in Agentic Hardware Verification Workflows* (characterizes
  agent strategies across protocol complexity); *WaveformQA* (LLM temporal reasoning on
  waveforms — evidence LLMs are *bad* at exactly the temporal reasoning solvers are good at).
- **Zero papers on**: formal methods as the oracle, human-in-the-loop verification flows,
  Chisel/CIRCT/open-EDA, floating point, assertion/property compilation.

**Read**: the agentic wave is cresting exactly where HORIZON pointed, benchmarks are the
currency, and the formal+HITL+open-tooling corner is *empty at this venue*. A flow whose
thesis is "solvers adjudicate facts, humans adjudicate intent, everything runs on free
tools" is differentiated at ICLAD rather than crowded out — and WaveformQA inadvertently
supplies the motivation slide (LLMs can't reliably read waveforms; monitors and model
checkers can).

## 2. The Chisel/CIRCT formal community (small, active, and exactly adjacent)

- **Amelia Dobis** (Princeton PhD; ETH MSc thesis *Formal Verification of Hardware using
  MLIR*, 2024) wrote CIRCT's btor2 emission — the very backend whose missing LTL lowering
  we hit on 7/9 — and maintains [btor2-opt](https://github.com/dobios/btor2-opt): a Python
  btor2 parser + pass infrastructure + **circuit miter tool** (`btormiter`: two `.fir`
  files → firtool → merged miter btor2), plus "modular BTOR2 extensions enabling structural
  composition and contracts" (v0.3, June 2025). Her talk *Exploiting Wasted Hardware
  Abstractions for Efficient Model Checking* (LLVM dev mtg 2024, w/ Healy & Cicolini)
  argues for verification-aware lowering in MLIR.
  - **Overlap check vs `fpdiff`**: btormiter miters two FIRRTL designs at btor2 level —
    same core trick as fpdiff, upstream of Verilog. fpdiff differs in the parts that face
    the human (IEEE decoding, class exploration, waiver ledger, sim cross-validation) and
    in taking Verilog from any source; a future fpdiff could *use* btor2-opt as its miter
    backend for Chisel-native DUTs. These are complementary, and worth a conversation with
    her at some point — she is the person reviewing any CIRCT-adjacent contribution.
- **chiseltest.formal** (Laeufer, UCB): archived Aug 2024, no successor. **ChiselFV**
  (2023) and **ChiselVerify** (DTU, Schoeberl et al.): ChiselVerify is dynamic-verification
  (coverage, CRV, BFMs); its formal story deferred to chiseltest — i.e., also orphaned.
- **chisel3.ltl + FormalContract** exist in Chisel 7 as *frontends* with no open backend
  path (7/9 findings: Verific wall at the SVA route, unimplemented `!ltl.property` lowering
  at the btor2 route).

**Read**: the Chisel community has an authoring layer (chisel3.ltl) and a solver layer
(btor2 → btormc/rIC3/pono, plus btor2-opt tooling) with a **missing middle**: nothing
compiles temporal properties down to what the solver layer accepts. Whoever fills that
gap — even for a pragmatic subset — fills a hole the community has had since chiseltest
died.

## 3. Property-to-monitor compilation (the prior art for filling that middle)

The idea of compiling temporal assertions into synthesizable monitor circuits is old and
respectable, which is good — it means the technique is sound and the *gap is tooling,
not theory*:

- **MBAC** (Boulé & Zilic, ~2005–2008): the canonical PSL/SVA → automata → RTL monitor
  compiler. Academic, effectively unavailable as maintained open tooling.
- **A Survey on Assertion-Based Hardware Monitor Synthesis** (Chips, 2025): confirms most
  tools support only operator subsets, and none of the surveyed ones are maintained
  open-source infrastructure.
- **Yosys' own `verificsva.cc`** builds NFA→DFA monitor FSMs from SVA — *inside the
  proprietary Verific frontend*. The open Yosys parser never got this. (This is the
  precise technical location of the "Verific wall.")
- **GHDL** supports PSL for VHDL — an existence proof that open temporal-property checking
  works when someone implements the lowering; the Verilog/Chisel world just never got its
  equivalent.
- **riscv-formal** (Wolf): the workaround-in-practice — all temporal obligations
  hand-written as helper-register monitor state machines in plain Verilog. Proves the
  target (boolean-safety + helper regs through open solvers) is fully sufficient for real
  verification at scale; what's missing is the *compiler* so humans don't hand-write
  monitors.
- **PyCaliper** (Godbole, UCB, 2024–25): Python-embedded RTL specification with solver
  dispatch — closest in spirit to a Python property eDSL; oriented toward refinement/
  equivalence specs rather than NL-annotated temporal safety monitors + HITL triage.
  Worth a deeper read before any writeup claims novelty.

## 4. Where the two PoCs sit in this map

- **fpdiff** (built 7/10): open replication of the Formal-that-Floats *equivalence* core,
  plus the human-facing layer (decode/triage/waivers). Its honest weakness — conceded
  after the user's critique of the paper — is that golden-model equivalence is mechanical:
  no NL, no intent, deterministic; and it needs a golden model, which most designers don't
  have. It is a *strong instrument*, not a *creative workflow*.
- **tempo** (next, see `tempo/DESIGN.md`): fills the missing middle of §2 with the §3
  technique — a bounded-temporal-**safety** property layer (NL-annotated AST, FLAG's
  sentiment) compiled to plain boolean monitor registers, so the 7/9 walls never apply,
  running on the same open solver stack, with the human adjudicating counterexamples into
  bugs / property fixes / environment assumptions. Protocols and datapaths alike.

## 5. Standing corrections to earlier framings

- "Temporal properties cannot be checked on the open Chisel stack" (7/9 conclusion) is
  true only of *emitting LTL as LTL*. The bounded-safety fragment — which covers nearly
  every practical protocol obligation (stability under stall, bounded response, no
  spurious response) — compiles to helper registers + boolean asserts, which the whole
  open stack handles. Genuine liveness ("eventually, unboundedly") remains out; in
  practice engineers bound it anyway.
- RTL-to-RTL equivalence does **not** require matching hierarchy for black-box miters
  (fpdiff proves this — hardfloat vs OpenFloat share nothing internally). What needs
  structural alignment is *lemma decomposition* for scaling (the paper's Jasper helper
  assertions). The user's workflow critique survives this correction: you still need a
  golden, and intent still enters nowhere.
