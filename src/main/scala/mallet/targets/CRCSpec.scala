// SPDX-License-Identifier: Apache-2.0
package mallet.targets

import chisel3._
import _root_.circt.stage.ChiselStage

import mallet._
import axi_wrapped.{Axi4LiteCRC, CRCModuleParams}


class CRCSpec(p: CRCModuleParams) extends Axi4LiteCRC(p) with MalletSpec {

  // ── memory-map roles ─────────────────────────────────────────────
  p.x_w           is Operand at xReg
  p.ri_w          is Commit  at riReg
  p.ro_r          is Result  at dutDataReg // valid always?
  p.soft_reset_rw is RW

  // ── protocol contract ────────────────────────────────────────────
  S.AXI conformsTo AxiLite32Slave

  // ── raw escape hatch ─────────────────────────────────────────────
  private val srPulse = B(softResetPulseReg, "softResetPulseReg")
  property("soft_reset_is_pulse") { srPulse |=> !srPulse }
  property("result_not_dropped")  { dut.io.out.fire |=> dutValidReg }

  done()
}

object CRCSpecChirrtlMain extends App {
  val p = CRCModuleParams.default()

  MalletRegistry.clear()
  MalletRegistry.coversEnabled = false
  ChiselStage.emitCHIRRTLFile(
    new CRCSpec(p),
    args = Array("--target-dir", "generated/mallet/chirrtl")
  )
  MalletRegistry.writeSidecar("generated/mallet/props")

  MalletRegistry.clear()
  MalletRegistry.coversEnabled = true
  ChiselStage.emitCHIRRTLFile(
    new CRCSpec(p),
    args = Array("--target-dir", "generated/mallet/reach")
  )
  MalletRegistry.coversEnabled = false
}