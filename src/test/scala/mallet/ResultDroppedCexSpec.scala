// SPDX-License-Identifier: Apache-2.0
package mallet

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.flatspec.AnyFlatSpec

import axi._
import axi_wrapped.{Axi4LiteMac, MacModuleParams}

/** Simulation replay of the `result_not_dropped` counterexample.
  *
  * This exists to answer the only question that matters about a formal FAIL:
  * is it a real bug, or an artifact of how the property was modelled? btormc
  * produced a trace in which a `result_r` read lands on the same cycle the MAC
  * result is accepted; this drives that exact cycle alignment in simulation.
  *
  * The bug (Axi4LiteMac.scala):
  *   :159-162  when (dut.io.out.fire) { dutDataReg := ...; dutValidReg := true.B }
  *   :167-173  when (arFire) { ... when (a === result_r) { dutValidReg := false.B } }
  *
  * Chisel last-connect semantics make the SECOND assignment win. So on a cycle
  * where both happen, the fresh result is written into dutDataReg but
  * dutValidReg is forced low. The result is never marked available, and the MAC
  * has already cleared its accumulator -- so it is lost permanently, not merely
  * delayed.
  */
class ResultDroppedCexSpec extends AnyFlatSpec with ChiselSim {

  val p = MacModuleParams.default(width_p = 8, accWidth_p = 32)

  // IGNORED, and not because the property is in doubt.
  //
  // ChiselSim cannot currently simulate Axi4LiteMac at all: it invokes its
  // bundled firtool 1.149.0, which CRASHES in ExportVerilog
  // (EmittedExpressionStateManager / dispatchSVVisitor) while emitting this
  // design. This is PRE-EXISTING and unrelated to mallet -- verified by
  // stashing every mallet file and running the untouched
  // axi_wrapped.Axi4LiteMacSpec at HEAD, where all 4 of its tests fail the same
  // way. Setting CHISEL_FIRTOOL_PATH to the newer 1.152.0 on PATH does not
  // redirect it.
  //
  // The formal flow is unaffected: it uses `firtool --btor2` from PATH (1.152.0)
  // and never enters the SystemVerilog emitter.
  //
  // Flip `ignore` back to `in` once simulation works, to get an independent
  // confirmation of the counterexample.
  "Axi4LiteMac" should "not drop a MAC result when result_r is read on the completion cycle" ignore {
    simulate(new Axi4LiteMac(p)) { d =>
      val bfm = new Axi4Lite32BFM[Axi4LiteMac](d)
      bfm.initMaster()
      bfm.reset()

      // Stage and commit a single 3*4 multiply.
      assert(bfm.writeVal(p.a_w, 3) == 0)
      assert(bfm.writeVal(p.b_w, 4) == 0)
      assert(bfm.writeVal(p.push_w, 1) == 0)

      // Advance to the cycle on which the MAC presents its result. Because
      // dutValidReg is still low, dut.io.out.ready is high, so this is the
      // cycle the handshake fires.
      var t = 0
      while (!d.dut.io.out.valid.peekBoolean() && t < 50) { bfm.step(1); t += 1 }
      assert(d.dut.io.out.valid.peekBoolean(), "MAC never produced a result")
      assert(!d.dutValidReg.peekBoolean(), "precondition: no result latched yet")

      // Same cycle: issue the read of result_r. arready is high (rvalidReg is
      // low), so arFire and dut.io.out.fire coincide -- the exact alignment
      // btormc found.
      d.S.AXI.araddr.poke(p.result_r.U)
      d.S.AXI.arvalid.poke(true.B)
      d.S.AXI.rready.poke(true.B)
      bfm.step(1)
      d.S.AXI.arvalid.poke(false.B)
      bfm.step(1)
      d.S.AXI.rready.poke(false.B)
      bfm.step(1)

      // The result was accepted from the MAC, so it must still be retrievable.
      // If dutValidReg was clobbered, status_r never goes high and the 3*4=12
      // result is gone for good.
      var polls = 0
      var status = 0
      while (status != 1 && polls < 50) {
        status = bfm.read(p.status_r)._1.toInt
        polls += 1
      }

      assert(
        status == 1,
        "MAC result was silently dropped: the result was accepted from the MAC " +
          "(out.fire) but dutValidReg was cleared by the concurrent result_r read, " +
          "so status_r never goes high and the value is unrecoverable."
      )
      bfm.expectVal(p.result_r, 12)
    }
  }
}
