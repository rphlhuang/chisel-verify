// SPDX-License-Identifier: Apache-2.0
package arithmetic

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage

class MacIn(w: Int) extends Bundle {
  val a    = UInt(w.W)
  val b    = UInt(w.W)
  val last = Bool()
}

/** 
  * AI GENERATED [Claude Opus 4.7]
  *
  * Consumes a stream of (a, b, last) beats over a Decoupled input.
  * Each beat takes 2 cycles: one to capture operands, one to add a*b
  * into the accumulator. On a beat with `last` asserted, the current
  * accumulator value is presented on the Decoupled output and held
  * until the consumer accepts it. Accepting the output resets the
  * accumulator, and the MAC is ready for a new dot-product.
  */

class Mac(val width: Int, val accWidth: Int) extends Module {
  require(accWidth >= 2 * width, "accWidth must hold at least one full product")

  val io = IO(new Bundle {
    val in  = Flipped(Decoupled(new MacIn(width)))
    val out = Decoupled(UInt(accWidth.W))
  })

  val sIdle :: sCompute :: sDone :: Nil = Enum(3)
  val state = RegInit(sIdle)

  val aReg    = Reg(UInt(width.W))
  val bReg    = Reg(UInt(width.W))
  val lastReg = RegInit(false.B)
  val accReg  = RegInit(0.U(accWidth.W))

  io.in.ready  := state === sIdle
  io.out.valid := state === sDone
  io.out.bits  := accReg

  switch(state) {
    is(sIdle) {
      when(io.in.fire) {
        aReg    := io.in.bits.a
        bReg    := io.in.bits.b
        lastReg := io.in.bits.last
        state   := sCompute
      }
    }
    is(sCompute) {
      accReg := accReg + (aReg * bReg)
      state  := Mux(lastReg, sDone, sIdle)
    }
    is(sDone) {
      when(io.out.fire) {
        accReg := 0.U
        state  := sIdle
      }
    }
  }
}

object MacMain extends App {
  ChiselStage.emitSystemVerilogFile(
    new Mac(width = 8, accWidth = 32),
    args = Array("--target-dir", "generated/arithmetic"),
    firtoolOpts = Array(
      "--disable-all-randomization",
      "--strip-debug-info",
      "--lowering-options=disallowLocalVariables,disallowPackedArrays",
    ),
  )
}