# tempo — NL-annotated temporal properties, compiled for the open toolchain

Write a hardware property once, as one object holding its **natural-language intent**
and its **formal meaning**. tempo compiles the temporal structure into plain
registers + a boolean assert — the bounded-temporal-safety fragment — so the same
property runs through open Yosys → btor2 → btormc (BMC *and* k-induction) **and**
through Icarus/Verilator/cocotb simulation, with the NL intent riding along into
every failure message. No Verific, no SVA parsing, no unimplemented LTL lowering:
the walls mapped on 7/9 are bypassed by doing the monitor compilation ourselves
(see `DESIGN.md` for the constructions and the formal-methods curriculum they embody).

Protocols and datapaths alike; the human's job is triage — every counterexample is
one of **bug / wrong property / missing environment assumption**, and the third
verdict is assume-guarantee reasoning made tangible.

## Requirements

Same as fpdiff: `yosys` ≥ 0.36, `btormc` + `iverilog` (oss-cad-suite), Python ≥ 3.10,
stdlib only. `TEMPO_TOOLS=<dir>` if not on PATH.

## The demo: this repo's own AXI4-Lite MAC (`examples/axi4litemac/`)

Six protocol obligations (response held until accepted, payload stability under stall,
bounded read/write response), authored in the eDSL with intents. Three runs, run from
`tempo/`:

```
python3 -m tempo run examples/axi4litemac/project.py
```
**Violation in 0.03s.** The solver-controlled master accepts a write address, then
starves WVALID forever — no data, no response owed. The replayed trace (printed
per-cycle, iverilog-confirmed) shows a *hostile environment*, not a broken DUT.
Verdict: **add assumption**.

```
python3 -m tempo run examples/axi4litemac/project_assumed.py
```
Same obligations + 3 signed environment assumptions (W follows AW within 2; WVALID
held; BREADY within 4). **PROVED in 0.51s — k-induction (`btormc --kind`) converges**,
so this is an unbounded proof, not a bounded sweep. The assumptions' intent strings
are the discovered interface contract.

```
python3 -m tempo run examples/axi4litemac/project_mutant.py
```
Same full spec against a mutant that drops BVALID after one cycle. **`b_held` fails**
with a *compliant* master in the trace. Verdict: **bug**. The failure message carries
the property's own English: *"Once BVALID asserts it stays asserted until BREADY
accepts it (AXI4-Lite: response may not be withdrawn)"*.

That's the whole triage triangle on real Chisel-generated RTL, in under a second each.

## Authoring

```python
Prop("b_held",
     intent="Once BVALID asserts it stays asserted until BREADY accepts it",
     formal=implies_next(expr("S_AXI_bvalid && !S_AXI_bready"),
                         expr("S_AXI_bvalid"))),          # |=>

Prop("write_resp_after_aw",
     intent="Every accepted write address gets BVALID within 8 cycles",
     formal=implies(expr("S_AXI_awvalid && S_AXI_awready"),
                    within(1, 8, expr("S_AXI_bvalid")))),  # |-> ##[1:8]

Prop("m_w_follows_aw", intent="ENV: ...", formal=..., kind="assume")  # same compiler
```

Node set: `expr` (raw Verilog boolean leaf), `past/stable/rose/fell`, `delay`,
`implies` (`|->`), `implies_next` (`|=>`), `within(m,n,·)` (bounded response — a
pending-obligation shift register that handles overlapping activations correctly),
`And/Or/Not`, per-property `disable`. `kind`: assert / assume / cover.
`provenance`: human / template / llm — LLM-proposed properties are labeled and never
load-bearing without a human's hand (same stance as fpdiff).

## Honest limits (PoC)

- Bounded-safety fragment only: no unbounded liveness (bound your "eventually" — you
  were going to anyway). No sequence concatenation/repetition yet (`##[*]`, throughout).
- Monitored signals must be DUT ports (internal-signal tapping: future).
- k-induction is whatever `btormc --kind` gives; no invariant strengthening loop yet.
  `b4`-style output interpretation should be double-checked against btormc docs before
  any writeup claims.
- Verdicts live in the project file by hand-editing; interactive triage + findings
  ledger like fpdiff's is a straightforward port (deliberately deferred).
- Next targets: hardfloat `FPDIV_8_24` divReady/outValid handshake (protocol-on-FP, the
  bridge to fpdiff's world); property templates for valid/ready ports (`propose`);
  the Chisel-native embedding over `chisel3.ltl` (see DESIGN.md — the community-shaped
  endgame).
