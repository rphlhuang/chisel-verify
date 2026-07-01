// SPDX-License-Identifier: Apache-2.0
package arithmetic

import chisel3.simulator.scalatest.ChiselSim
import chisel3.simulator.PeekPokeAPI._
import org.scalatest.flatspec.AnyFlatSpec

class AdderSpec extends AnyFlatSpec with ChiselSim {
  val width = 8

  "Adder" should "produce correct sum for typical values" in {
    simulate(new Adder(width)) { dut =>
      // TODO
    }
  }

  it should "handle zero inputs" in {
    simulate(new Adder(width)) { dut =>
      // TODO
    }
  }

  it should "not overflow on max inputs (output is width+1 bits)" in {
    simulate(new Adder(width)) { dut =>
      // TODO
    }
  }
}
