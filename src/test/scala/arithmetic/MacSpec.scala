// SPDX-License-Identifier: Apache-2.0
package arithmetic

import scala.util.Random

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.flatspec.AnyFlatSpec

class MacSpec extends AnyFlatSpec with ChiselSim {
  val DEFAULT_WIDTH = 8
  val DEFAULT_ACCWIDTH = 16
  val NUM_RANDOM_TESTS = 100
  val TIMEOUT = 100

  val max = (1 << DEFAULT_WIDTH) - 1
  val rng = new Random(42L)

  def enqueue(dut: Mac, a: Int, b: Int, last: Boolean): Unit = {
    dut.io.in.bits.a.poke(a.U)
    dut.io.in.bits.b.poke(b.U)
    dut.io.in.bits.last.poke(last.B)
    dut.io.in.valid.poke(true.B)
    while (!dut.io.in.ready.peek().litToBoolean) {
      dut.clock.step()
    }
    dut.clock.step()
    dut.io.in.valid.poke(false.B)
  }

  def dequeue(dut: Mac, expected: Int): Unit = {
    dut.io.out.ready.poke(true.B)
    var cycle_count = 0
    while (!dut.io.out.valid.peek().litToBoolean) {
      dut.clock.step()
      cycle_count += 1
      assert(cycle_count <= TIMEOUT, s"dequeue timed out after $TIMEOUT cycles")
    }
    dut.io.out.bits.expect(expected.U)
    dut.clock.step()
    dut.io.out.ready.poke(false.B)
  }

  "Mac" should "not produce outputs without handshake" in {
    simulate(new Mac(width=8, accWidth=16)) { dut =>
      dut.io.in.valid.poke(false.B)
      dut.io.out.ready.poke(false.B)
      dut.clock.step(5)
      dut.io.out.valid.expect(false.B)
    }
  }

  it should "not produce outputs when not finished" in {
    simulate(new Mac(width=8, accWidth=16)) { dut =>
      dut.io.in.valid.poke(false.B)
      dut.io.out.ready.poke(false.B)
      dut.clock.step()
      dut.io.in.valid.poke(true.B)
      dut.io.in.bits.a.poke(2.U)
      dut.io.in.bits.b.poke(4.U)
      dut.io.in.bits.last.poke(false.B)
      dut.clock.step(3)
      dut.io.out.valid.expect(false.B)
    }
  }

  it should "accumulate a simple multiplication once" in {
    simulate(new Mac(width=8, accWidth=16)) { dut =>
      enqueue(dut, 2, 2, false)
      dequeue(dut, 4)
    }
  }
  

  // it should "handle a single transfer" in {
  //   simulate(new Mac(width=8, accWidth=16)) { dut =>

  //   }
  // }
}
