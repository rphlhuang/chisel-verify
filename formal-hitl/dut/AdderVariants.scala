// SPDX-License-Identifier: Apache-2.0
package arithmetic

import chisel3._
import circt.stage.ChiselStage

// A family of variable-width adders that all share the exact same port
// interface as the existing `arithmetic.Adder` (a, b: width bits in;
// s: width+1 bits out). Only `Golden` is correct; the rest carry a
// deliberately injected bug so the formal-hitl loop below (see
// formal-hitl/README.md) has something to disprove and produce
// counterexamples for -- a correct trivial adder alone demos nothing.
//
// Selecting the bug via a plain Scala parameter (instead of six separate
// classes) keeps every variant diffable against the same io block.
object AdderVariant {
  // Width threshold used by WidthDependentBug: correct for width <= N,
  // broken for width > N.
  val WidthDependentBugThreshold = 8
}

class AdderVariant(variant: String, width: Int) extends Module {
  val io = IO(new Bundle {
    val a = Input(UInt(width.W))
    val b = Input(UInt(width.W))
    val s = Output(UInt((width + 1).W))
  })

  variant match {
    case "Golden" =>
      // Reference behavior: full-width sum, carry preserved.
      io.s := io.a +& io.b

    case "TruncatingAdd" =>
      // Bug: `+` (not `+&`) drops the carry-out. Wrong whenever a+b
      // overflows `width` bits.
      io.s := io.a + io.b

    case "OffByOneWidth" =>
      // Bug: correct math, but the output wire is declared one bit too
      // narrow, so the wraparound assignment silently truncates the MSB.
      val narrow = Wire(UInt(width.W))
      narrow := io.a +& io.b
      io.s := narrow

    case "SwappedOperand" =>
      // Bug: computes a+a instead of a+b.
      io.s := io.a +& io.a

    case "WidthDependentBug" =>
      // Bug only manifests for width > threshold; correct below it. This
      // exercises "the bug only shows up at a specific parameterization"
      // story -- a single fixed-width testbench can miss it entirely.
      if (width <= AdderVariant.WidthDependentBugThreshold) {
        io.s := io.a +& io.b
      } else {
        io.s := io.a + io.b
      }

    case "RegisteredBuggy" =>
      // Sequential variant: inputs and output are registered across a
      // clock edge, and the combinational core carries the TruncatingAdd
      // bug. Exists so counterexample waveforms span multiple cycles
      // instead of being a single degenerate step.
      val aReg = RegNext(io.a, 0.U)
      val bReg = RegNext(io.b, 0.U)
      val sumReg = RegNext(aReg + bReg, 0.U((width + 1).W))
      io.s := sumReg

    case _ =>
      throw new IllegalArgumentException(s"Unknown AdderVariant: $variant")
  }
}

object AdderVariants {
  val all: Seq[String] = Seq(
    "Golden",
    "TruncatingAdd",
    "OffByOneWidth",
    "SwappedOperand",
    "WidthDependentBug",
    "RegisteredBuggy",
  )
}

// Emits SystemVerilog for every variant into
// formal-hitl/generated/<variant>/w<width>/, so re-generating at a new width
// doesn't silently invalidate .sv already generated for another width.
// Width defaults to 8 but can be overridden: `sbt "runMain arithmetic.AdderVariantsMain 4"`
object AdderVariantsMain extends App {
  val width = if (args.nonEmpty) args(0).toInt else 8
  val outRoot = "formal-hitl/generated"

  for (variant <- AdderVariants.all) {
    val targetDir = s"$outRoot/$variant/w$width"
    ChiselStage.emitSystemVerilogFile(
      new AdderVariant(variant, width),
      args = Array("--target-dir", targetDir),
    )
    println(s"emitted $variant -> $targetDir")
  }
}
