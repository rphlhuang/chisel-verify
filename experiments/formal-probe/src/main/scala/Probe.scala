// SPDX-License-Identifier: Apache-2.0
package probe

import chisel3._
import chisel3.util.log2Ceil
import chisel3.ltl._
import chisel3.ltl.Sequence._
import circt.stage.ChiselStage

/** Capability probe for the open Chisel -> CHIRRTL -> BTOR2 -> btormc formal
  * path. One tiny module per LTL construct, each carrying exactly ONE property
  * so a `bad` index in the emitted BTOR2 maps unambiguously to one construct.
  *
  * `run.sh` emits these to generated/chirrtl/ and runs formal_check.sh, which
  * classifies each module into an outcome (checked / residual / vacuous) and
  * prints a version-stamped table. The lowerable LTL fragment shifts between
  * CIRCT releases, so the table -- not the code -- is the artifact.
  *
  * This lives outside the main source tree on purpose: it's a rarely-run
  * characterization tool, not part of any design.
  */
object Probe {
  /** Reset-aligned warm-up mask (local copy of the main tree's
    * formal.FormalUtils.warmedUp, kept here so the probe is standalone).
    * False for the first `n` cycles after reset, true after -- guards
    * past(n) properties whose shift register samples across the reset
    * boundary. Relies on RegInit's reset mux for soundness. */
  def warmedUp(n: Int): Bool = {
    require(n >= 0)
    if (n == 0) true.B
    else {
      val c = RegInit(0.U(log2Ceil(n + 1).W))
      when(c =/= n.U) { c := c + 1.U }
      c === n.U
    }
  }
}

import Probe.warmedUp

/** Overlapping implication `|->`: same-cycle, lowers to `implies`. -> PASS. */
class ProbeOverlap extends Module {
  val a = IO(Input(Bool()))
  val b = IO(Input(Bool()))
  AssertProperty((a & b) |-> a) // (a AND b) implies a -- provable
}

/** Bounded past `past(n)` under `|->`, guarded: lowers via `seq.shiftreg`,
  * warm-up mask suppresses the reset-boundary sample. -> PASS. */
class ProbePastGuarded extends Module {
  val a    = IO(Input(Bool()))
  val seen = RegNext(a, false.B) // a delayed one cycle, reset-initialized
  AssertProperty(warmedUp(1).and(a.past(1)) |-> seen)
}

/** Same property WITHOUT the warm-up guard. NOTE: this PASSES for this simple
  * design -- inspect the emitted btor2 and you'll see CIRCT gave past()'s
  * shift register a reset mux (`_sh1' = reset ? 0 : a`), so no contaminated
  * sample crosses the boundary. The reset-boundary hazard is therefore
  * DESIGN-DEPENDENT: in arithmetic.Mac the same construct lowers to an
  * UNRESET shiftreg (`_sh1' = io.in.fire`) and the unguarded form FAILs at
  * step 1. warmedUp(n) is the guard that makes the property sound regardless
  * of which way the shiftreg reset falls. Exact trigger is still open (a
  * good question for the toolchain authors). */
class ProbePastUnguarded extends Module {
  val a    = IO(Input(Bool()))
  val seen = RegNext(a, false.B)
  AssertProperty(a.past(1) |-> seen)
}

/** Non-overlapping implication `|=>`: builds `ltl.delay` + `ltl.concat`, which
  * upstream LowerLTLToCore has no pattern for. -> RESIDUAL (sentinel id). */
class ProbeNonOverlap extends Module {
  val a = IO(Input(Bool()))
  val b = IO(Input(Bool()))
  AssertProperty(a |=> b)
}

/** Explicit forward sequence delay `.delay(n)`: no lowering pattern.
  * -> RESIDUAL (sentinel id). */
class ProbeDelay extends Module {
  val a = IO(Input(Bool()))
  val b = IO(Input(Bool()))
  AssertProperty(a.delay(1) |-> b)
}

/** Structural tautology `a === a`: folds to constant true before the HW stage,
  * so no assertion is emitted. -> VACUOUS (hw=0, no bad). */
class ProbeFold extends Module {
  val a = IO(Input(Bool()))
  AssertProperty(a === a)
}

object ProbeChirrtlMain extends App {
  private val dir = "generated/chirrtl"
  ChiselStage.emitCHIRRTLFile(new ProbeOverlap,        args = Array("--target-dir", dir))
  ChiselStage.emitCHIRRTLFile(new ProbePastGuarded,    args = Array("--target-dir", dir))
  ChiselStage.emitCHIRRTLFile(new ProbePastUnguarded,  args = Array("--target-dir", dir))
  ChiselStage.emitCHIRRTLFile(new ProbeNonOverlap,     args = Array("--target-dir", dir))
  ChiselStage.emitCHIRRTLFile(new ProbeDelay,          args = Array("--target-dir", dir))
  ChiselStage.emitCHIRRTLFile(new ProbeFold,           args = Array("--target-dir", dir))
}