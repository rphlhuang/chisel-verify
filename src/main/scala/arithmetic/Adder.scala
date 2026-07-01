// SPDX-License-Identifier: Apache-2.0
package arithmetic

import chisel3._
import circt.stage.ChiselStage

class Adder(width: Int) extends Module {
    val io = IO(new Bundle {
        val a = Input(UInt(width.W))
        val b = Input(UInt(width.W))
        val s = Output(UInt((width + 1).W))
    })

    io.s := io.a +& io.b
}

object AdderMain extends App {
  ChiselStage.emitSystemVerilogFile(
    new Adder(8),
    args = Array("--target-dir", "generated/arithmetic"),
    firtoolOpts = Array(
      "--disable-all-randomization",
      "--strip-debug-info",
      "--lowering-options=disallowLocalVariables,disallowPackedArrays",
    ),
  )
}