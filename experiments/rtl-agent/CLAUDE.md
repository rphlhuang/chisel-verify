# rtl-agent — shared context for the RTL → Verify → Synthesize pipeline

This file is the **authoritative workflow** for every agent in this experiment. The
orchestrator and (in Phase 2) every subagent inherit it. **Agents call the repo's
existing Makefiles and sbt targets — they never reimplement build logic** and never
report a step as passing without the tool artifact on disk to prove it.

Written in Phase 0 by reading the real repo. If a target or convention here is ever
contradicted by the code, the code wins and this file is fixed — stop and flag it.

Repo root: `/Users/rhuang/Documents/chisel-verify` (referred to below as `REPO_ROOT`).
This experiment lives at `REPO_ROOT/experiments/rtl-agent`, beside `tempo` and `fpdiff`.

---

## 0. Confirmed decisions (Phase 0 interview, 2026-07-20)

1. **Phase 1 target = re-derive `Axi4LiteMac` against its golden.** The module already
   exists by hand (Chisel + ChiselSim + cocotb + generated SV + a done Vivado run). The
   agent regenerates it from a spec; the existing hand-written sources and passing tests
   are the **golden reference** the harness is validated against — we know the right answer,
   so this tests the *harness*, not the model's luck.
2. **Vivado / Gate 2 = handoff bundle, human runs it.** The Synth-runner produces the
   self-contained `generated/<Top>/` plus a `run_on_jlse.sh` cheat-sheet and stops. The
   human runs the Duo-gated JLSE flow and pastes `timing_summary.txt` / `utilization_report.txt`
   back for the agent to parse. The agent does **not** attempt to SSH through Duo.
3. **Yosys open gate = in from Phase 1**, reusing the oss-cad-suite the siblings assume
   (`~/Documents/utils/oss-cad-suite/bin`, override `TEMPO_TOOLS`/`FPDIFF_TOOLS`). It is an
   **elaboration + area sanity** rung — open `synth_xilinx` targets xc7/UltraScale, **not**
   the V80/Versal, so it never claims V80 accuracy. That is Vivado's job.
4. **Build unit = per-DUT Makefile.** The agent works one module at a time via
   `tests/<pkg>/<Module>/Makefile` (auto-elaborates just that SV, then runs cocotb) and
   scoped `sbt "testOnly *<Module>*"`. Root `make gen/chiselsim/cocotb` are whole-tree runs,
   used only for full-suite sweeps.

---

## 1. Repo conventions (read the code, match it — do not invent)

Canonical exemplar for everything below: **`Axi4LiteMac`**. Read these before generating:
- `src/main/scala/axi_wrapped/Axi4LiteMac.scala` — the AXI-Lite wrapper + `MacModuleParams`.
- `src/main/scala/arithmetic/Mac.scala` — the leaf DUT (`Decoupled` in/out, FSM).
- `src/test/scala/axi_wrapped/Axi4LiteMacSpec.scala` — ChiselSim unit tests + BFM usage.
- `tests/axi_wrapped/Axi4LiteMac/{Makefile,Axi4LiteMacSim.py}` — cocotb integration TB.
- `chisel-axi-utils/src/main/scala/axi/` — the helper library (below). **Do not fork it.**

### Interface & params
- The wrapper `extends chisel3.Module with axi.HasAxiLite32IO` and does
  `override val S = IO(new AxiLite32IO())`. Standard AXI4-Lite 32-bit, `wstrb` word-writes
  only (partial writes → `SLVERR`).
- Ports named `S.AXI.{aw,w,b,ar,r}*`. Reset is active-high `reset`; the plain-Verilog
  `user_accel_bd_wrapper.v` inverts an active-low `s_axi_aresetn` for the outside world.
- The memory map is a **`case class … extends AxiModuleParams with AxiModuleDefParams`**,
  with a companion `object … { implicit val rw: ReadWriter = macroRW; def default(...) }`.
  Address fields are `Long`, suffixed `_r` (read), `_w` (write), `_rw` (read/write);
  `soft_reset_rw` is the DefParams reset register. `moduleName` names the params JSON
  (`<moduleName>_params.json`). **Never hard-code an address in a test** — drive from params.
- 4-byte alignment + no duplicate addresses are enforced by `AxiAddrMapBase.checkaddr`.

### Emitting SystemVerilog — always via `EmitVerilog.generate`
The `Main` App calls:
```scala
val p = checkParamEnv(MacModuleParams.default(), "CMD_MODULE_PARAMS")
EmitVerilog.generate(new Axi4LiteMac(p, debugprint=true), p)
```
`checkParamEnv` lets a run override params via the `CMD_MODULE_PARAMS` env var (JSON);
default is the `.default()` map. `EmitVerilog.generate` writes the **self-contained**
`generated/<Top>/`:
- `<Top>.sv`, plus each leaf `.sv` (e.g. `Mac.sv`), via firtool with
  `--disable-all-randomization --strip-debug-info --lowering-options=disallowLocalVariables,disallowPackedArrays --verilog`.
- `user_accel_bd_wrapper.v` — the plain-Verilog AXI top; **this is cocotb's `COCOTB_TOPLEVEL`.**
- `<moduleName>_params.json` — the memory map cocotb's `COCOTB_Bridge` reads via `$PARAMFN`.
- `run.tcl`, `constraints.xdc` (100 MHz / 10 ns clock only), `compile.sh`, `copysrcto.sh`,
  `filelist.f` — the Vivado JLSE bundle. Part is hard-coded to the V80 `xcv80-lsva4737-2MHP-e-S`.

Leaf-only modules (e.g. `arithmetic/Mac`) instead emit directly with
`ChiselStage.emitSystemVerilogFile(..., "--target-dir", "generated/<pkg>")` — no AXI/Vivado
wrapper. Use the wrapper path (`EmitVerilog.generate`) for anything AXI-exposed.

### The reference oracle (correctness backbone — non-negotiable)
Both test layers already do this: compute `expected` in host software and assert equality
against the DUT read back over AXI — never against the agent's expectation.
- ChiselSim: `Axi4Lite32BFM[T]` → `initMaster()`, `reset()`, `writeVal(addr,v)` (returns
  resp; `0` = OKAY), `read(addr)` → `(data, resp)`, `expectVal(addr, ref)`.
- cocotb: `COCOTB_Bridge(cocotb_dut)` → `await dut.setup()`, `await dut.writeWord(dut.p.<field>, v)`,
  `await dut.readWord(dut.p.<field>)`; `dut.p` is the params JSON.
- **Corner cases are mandatory**, not just random vectors: for MAC include 0, max operands,
  accumulation to the overflow boundary (`Axi4LiteMacSpec` has `CYCLES_UNTIL_POSSIBLE_OVERFLOW`).
  For a future FP leaf: NaN / ±inf / subnormal / ±0 / rounding boundaries.

---

## 2. The canonical loop (agents run exactly this order, per-DUT)

For a module at `<pkg>.<Module>` with test dir `tests/<pkg>/<Module>/`:

| # | Step | Command (from `REPO_ROOT`) | Artifact that proves it | Why here |
|---|------|----------------------------|-------------------------|----------|
| 1 | **generate** | `cd tests/<pkg>/<Module> && make gen` (force) — or `make sim`'s auto-gen | `generated/<Top>/<Top>.sv`, `user_accel_bd_wrapper.v`, `<moduleName>_params.json` | SV + params must exist before any sim; regen so RTL edits take effect |
| 2 | **chiselsim (unit)** | `sbt "testOnly *<Module>Spec"` (or `make chiselsim` whole-suite) | scalatest PASS/FAIL lines; sbt exit 0 | fast in-Chisel check with the BFM before spinning Verilator |
| 3 | **cocotb (integration)** | `cd tests/<pkg>/<Module> && make sim` | `results.xml` (`failures="0"`), `output.log`, `dump.vcd` | independent Verilator sim of the real SV through the AXI wrapper + oracle |
| 4 | **yosys (open gate)** | `yosys -p 'read_verilog -sv generated/<Top>/Mac.sv generated/<Top>/<Top>.sv; hierarchy -top <Top>; synth_xilinx -top <Top>; stat'` | `runs/<id>/4_yosys/stat.txt` (elaborates, sane cell/area counts) | cheap medium-fidelity gate: catches elaboration/inference breakage before slow Vivado |
| 5 | **vivado (JLSE, human)** | hand off `generated/<Top>/` + `run_on_jlse.sh`; human runs `compile.sh` remotely | `timing_summary.txt`, `utilization_report.txt` pasted back | the one non-open, slow, real-synth signal; behind Gate 2 |

**Ordering is load-bearing** — never reorder. gen before sim (no SV → no sim). ChiselSim
before cocotb (fail fast in-language before Verilator build). Yosys before Vivado (cheap
before expensive). Vivado only after a human approves at Gate 2.

Root aggregate targets, for reference (whole-tree only):
`make gen` (elaborate every App), `make chiselsim` (`sbt test`, `FORCE=1` → `testOnly *`),
`make cocotb` (every `tests/*/*/`), `make` (both), `make clean` / `make extraclean`.

### Reading artifacts (the guardrail in practice)
- **cocotb pass** = `results.xml` present AND `<testsuite ... failures="0" errors="0">`.
  A missing `results.xml` is a FAIL, never a pass — parse the file, don't trust stdout.
- **chiselsim pass** = sbt exits 0 and scalatest prints no failed tests. `-oF` gives full
  stack traces on failure (set in `build.sbt`).
- **yosys pass** = yosys exits 0, `hierarchy`/`synth_xilinx` emit no error, `stat` shows a
  plausible design (nonzero cells, no `$` unmapped blackboxes for the leaf).
- **vivado pass** = human-pasted `timing_summary.txt` shows WNS ≥ 0 and no failing endpoints.

---

## 3. Golden reference for Phase 1 (Axi4LiteMac)

The re-derivation must match the existing golden. Known-good facts to check against:
- Memory map (`MacModuleParams.default`): `soft_reset_rw=0x0`, `a_w=0x10`, `b_w=0x14`,
  `push_w=0x20`, `result_r=0x24`, `status_r=0x28`; `width_p=8`, `accWidth_p=32`,
  `reset_cycles=8`. (The generated `Mac_params.json` shows these in decimal.)
- Behaviour: write `a`,`b`, then `push_w` (bit0 = `last`); poll `status_r` until 1; read
  `result_r` = Σ(a·b) over the accumulated beats. Partial write → `SLVERR`.
- Vivado (V80, from prior run): WNS ≈ +6.99 ns on 10 ns → Fmax ≈ 332 MHz; 192 FF, 173 LUT,
  **0 DSP**, 0 BRAM. A re-run should land in the same ballpark.

A Phase-1 run **passes** iff: regenerated `Axi4LiteMac.sv` elaborates, the ChiselSim +
cocotb suites (matching the golden tests' intent, incl. corner cases) run and pass against
the oracle, the Yosys gate is clean, and — after Gate 2 — the pasted Vivado report meets timing.

---

## 4. Environment / tools (verified present 2026-07-20)

- `sbt` 2.0.1 (Scala 2.13.18, Chisel 7.13.0), `firtool` 1.152.0.
- Python venv: **`REPO_ROOT/venv`** (cocotb 2.0.1 + the RasmusGOlsen `cocotbext-axi` fork).
  Use this venv, not a system/pipx cocotb. `pip install -e chisel-axi-utils/python` provides
  `axi_test_bridge` (`COCOTB_Bridge`).
- Sim: **Verilator 5.051** (default; ≥5.036 required by the cocotb 2.0 fork), Icarus fallback.
- Open synth/formal: **yosys 0.39**, `btormc`, from `~/Documents/utils/oss-cad-suite/bin`.
- Vivado 2025.1 lives on **JLSE only** (remote, Duo). Never assume it locally.

---

## 5. SVA policy (light, optional)
Immediate/simple concurrent assertions only — Verilator-supported, Yosys-readable. **No
temporal SVA** (`##`, `|->` over cycles, `s_eventually`) in the open flow: open Yosys has no
Verific front-end and the FIRRTL→btor2 path doesn't lower temporal LTL. For a genuine
temporal property, use a Chisel `assert` on a hand-built `past()` helper register (see the
`tempo` experiment), not temporal SVA. Primary correctness stays ChiselSim + cocotb + oracle.

---

## 6. Guardrails (non-negotiable, repeated because they matter)
- **Never edit or weaken a test to make it pass.** A failing test is a Designer problem.
- **No artifact on disk → not a pass.** A textual claim of success is unverified.
- **Bound every repair loop.** On exhaustion, stop and surface the failure + real logs to
  the human. Never loop forever or fabricate progress.
- **The human + real tool output is the acceptance signal. The agent is not.**

---

## 7. Run layout (OpenROAD-style numbered steps)
Generated Chisel goes in the sbt source tree the Makefile expects (`src/main/scala/...`);
per-run *artifacts/logs* go under `runs/<id>/`:
```
runs/<id>/
  1_generate/   emitted SV + generated-Chisel snapshot + gen log
  2_chiselsim/  scalatest log + pass/fail
  3_cocotb/     results.xml, output.log, dump.vcd
  4_yosys/      yosys script + stat.txt (+ optional CEC)
  5_vivado/     run_on_jlse.sh, pasted timing_summary.txt / utilization_report.txt
  report.md     cross-step summary, every tool call with its real output, traceable end to end
```

---

## 8. Build order (do not do it all at once)
- **Phase 0 (this file):** workflow captured, confirmed by user. ← current gate.
- **Phase 1:** single orchestrator, `Axi4LiteMac` re-derivation, linear pipeline through the
  Vivado handoff. No subagents, no UI. Prove the spine.
- **Phase 2:** split Designer / Verifier / Synth-runner subagents (`.claude/agents/*.md`,
  each carrying this workflow); bounded repair loop; the Yosys gate as an independent rung.
- **Phase 3:** FastAPI HITL frontend with the three gates; optional SymbiYosys boolean-safety.
- **Phase 4:** second module (HardFloat `AddRecFN` wrapper) to show generality.
