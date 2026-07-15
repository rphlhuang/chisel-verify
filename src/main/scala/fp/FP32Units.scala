// SPDX-License-Identifier: Apache-2.0
package fp

import chisel3._
import chisel3.util._
import hardfloat._
import _root_.circt.stage.ChiselStage

object FPOpMode {
  trait Mode
  case object ADD extends Mode
  case object SUB extends Mode
  case object MUL extends Mode
}

class FPCombUnit(val expW: Int = 8, val sigW: Int = 24, val mode: FPOpMode.Mode = FPOpMode.ADD) extends Module {
  val bw = expW + sigW
  val io = IO(new Bundle {
    val in_a  = Input(UInt(bw.W))
    val in_b  = Input(UInt(bw.W))
    val out = Output(UInt(bw.W))
    val exceptionFlags = Output(UInt(5.W))
  })

  require(mode == FPOpMode.MUL ||
          mode == FPOpMode.ADD ||
          mode == FPOpMode.SUB, 
          "mode must be MUL, ADD, or SUB for FPCombUnit"
         )

  override def desiredName = s"FP${mode}_${expW}_$sigW"
  if (mode == FPOpMode.MUL) {
    val opRecFN = Module(new MulRecFN(expW, sigW))
    opRecFN.io.a := recFNFromFN(expW, sigW, io.in_a)
    opRecFN.io.b := recFNFromFN(expW, sigW, io.in_b)
    opRecFN.io.roundingMode := 0.U
    opRecFN.io.detectTininess := 1.U
    io.exceptionFlags := opRecFN.io.exceptionFlags 
    io.out := fNFromRecFN(expW, sigW, opRecFN.io.out)
  } else if (mode == FPOpMode.ADD || mode == FPOpMode.SUB) {
    val opRecFN = Module(new AddRecFN(expW, sigW))
    opRecFN.io.subOp := (mode == FPOpMode.SUB).B
    opRecFN.io.a := recFNFromFN(expW, sigW, io.in_a)
    opRecFN.io.b := recFNFromFN(expW, sigW, io.in_b)
    opRecFN.io.roundingMode := 0.U
    opRecFN.io.detectTininess := 1.U
    io.exceptionFlags := opRecFN.io.exceptionFlags 
    io.out := fNFromRecFN(expW, sigW, opRecFN.io.out)
  }
}


object FPAddMain extends App {
  ChiselStage.emitSystemVerilogFile(
    new FPCombUnit(8, 24, FPOpMode.ADD), // 8 exp, (23 + 1 implcit leading bit) significand = single-precision
    args = Array("--target-dir", "generated/fp"),
    firtoolOpts = Array(
      "--disable-all-randomization",
      "--strip-debug-info",
      "--lowering-options=disallowLocalVariables,disallowPackedArrays",
    ),
  )
}

object FPSubMain extends App {
  ChiselStage.emitSystemVerilogFile(
    new FPCombUnit(8, 24, FPOpMode.SUB),
    args = Array("--target-dir", "generated/fp"),
    firtoolOpts = Array(
      "--disable-all-randomization",
      "--strip-debug-info",
      "--lowering-options=disallowLocalVariables,disallowPackedArrays",
    ),
  )
}

object FPMulMain extends App {
  ChiselStage.emitSystemVerilogFile(
    new FPCombUnit(8, 24, FPOpMode.MUL),
    args = Array("--target-dir", "generated/fp"),
    firtoolOpts = Array(
      "--disable-all-randomization",
      "--strip-debug-info",
      "--lowering-options=disallowLocalVariables,disallowPackedArrays",
    ),
  )
}