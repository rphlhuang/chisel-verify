// SPDX-License-Identifier: Apache-2.0
package arithmetic

import chisel3._
import chisel3.ltl._
import chisel3.ltl.Sequence._
import circt.stage.ChiselStage

class Adder(width: Int) extends Module {
    val io = IO(new Bundle {
        val a = Input(UInt(width.W))
        val b = Input(UInt(width.W))
        val s = Output(UInt((width + 1).W))
    })

    io.s := io.a +& io.b

    AssertProperty(io.s >= io.a)
    AssertProperty(io.s >= io.b)
    AssertProperty((io.a === io.b) |-> (io.s(0) === 0.U)) // equal operands give even sum

    AssumeProperty(io.a <= 100.U && io.b <= 100.U)
    AssertProperty(io.s <= 200.U)
}

object AdderFormalMain extends App {
  ChiselStage.emitSystemVerilogFile(
    new Adder(8),
    args = Array("--target-dir", "generated/arithmetic/formal"),
    firtoolOpts = Array(
      "--disable-all-randomization",
      "--strip-debug-info",
      "--lowering-options=disallowLocalVariables,disallowPackedArrays",
      "--enable-layers=Verification,Verification.Assert,Verification.Assume,Verification.Cover",
    ),
  )
}

object AdderChirrtlMain extends App {
  ChiselStage.emitCHIRRTLFile(
    new Adder(8),
    args = Array("--target-dir", "generated/arithmetic/chirrtl")
  )
}