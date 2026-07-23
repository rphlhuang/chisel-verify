// SPDX-License-Identifier: Apache-2.0
package formal

import chisel3._
import chisel3.util.log2Ceil

object FormalUtils {

  /** Reset-aligned warm-up mask for guarding past(n).
    * Returns false for first n cycles after reset deasserts and true thereafter.
    *
    * This is needed because CIRCT lowers ltl.past to a seq.shiftreg with NO reset, 
    * so the shift register keeps sampling while the circuit is held in reset. 
    * The first post-reset cycle therefore sees a past-value
    * from a cycle that never legitimately happened, and "past(a) |-> b"
    * fires a spurious counterexample at that boundary.
    * 
    * Example: AssertProperty( warmedUp(1).and(io.in.fire.past(1)) |-> (state === sCompute) )
    */
  def warmedUp(n: Int): Bool = {
    require(n >= 0, "warm-up depth must be non-negative")
    if (n == 0) true.B
    else {
      val c = RegInit(0.U(log2Ceil(n + 1).W))
      when(c =/= n.U) { c := c + 1.U }
      c === n.U
    }
  }
}