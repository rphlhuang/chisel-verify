// SPDX-License-Identifier: Apache-2.0
package arithmetic

import scala.util.Random

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.flatspec.AnyFlatSpec

class AdderSpec extends AnyFlatSpec with ChiselSim {
  val DEFAULT_WIDTH = 8
  val NUM_RANDOM_TESTS = 100

  val max = (1 << DEFAULT_WIDTH) - 1
  val rng = new Random(42L)

  "Adder" should "produce correct sum for typical values" in {
    simulate(new Adder(DEFAULT_WIDTH)) { dut =>
      for (i <- 0 until NUM_RANDOM_TESTS) {
        val a = rng.between(0, max + 1)
        val b = rng.between(0, max + 1)
        dut.io.a.poke(a.U)
        dut.io.b.poke(b.U)
        dut.io.s.expect((a + b).U)
      }
    }
  }

  it should "handle zero inputs" in {
    simulate(new Adder(DEFAULT_WIDTH)) { dut =>
      dut.io.a.poke(0.U)
      dut.io.b.poke(0.U)
      dut.io.s.expect(0.U)
    }
  }

  it should "not overflow on max inputs (output is width+1 bits)" in {
    simulate(new Adder(DEFAULT_WIDTH)) { dut =>
      dut.io.a.poke((max).U)
      dut.io.b.poke((max).U)
      dut.io.s.expect((max + max).U)
    }
  }

  it should "produce correct sum for varying width" in {
    for (width <- Seq(4, 8, 16, 32)) {
      val maxVal = (1 << width) - 1
      simulate(new Adder(width)) { dut =>
        for (i <- 0 until NUM_RANDOM_TESTS) {
          val a = rng.between(0, maxVal + 1)
          val b = rng.between(0, maxVal + 1)
          dut.io.a.poke(a.U)
          dut.io.b.poke(b.U)
          dut.io.s.expect((a + b).U)
        }
      }
      info(s"passed for width $width")
    }
  }
}
