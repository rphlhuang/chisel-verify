// SPDX-License-Identifier: Apache-2.0
// See LICENSE file for details.
package axi_wrapped

import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.flatspec.AnyFlatSpec
import axi._
import axi.AxiModuleParamsHelper._
import axi.AxiLiteResp._

class Axi4LiteMacSpec extends AnyFlatSpec with ChiselSim {
  val p = MacModuleParams.default(width_p = 8, accWidth_p = 32)

  "Axi4LiteMac" should "handle a single multiply" in {
    simulate(new Axi4LiteMac(p, debugprint = true)) { dut =>
      val bfm = new Axi4Lite32BFM[Axi4LiteMac](dut)
      bfm.initMaster()
      bfm.reset()

      val a = 3
      val b = 4

      assert(bfm.writeVal(p.a_w, a) == 0, f"\nWrite $a to a_w failed")
      assert(bfm.writeVal(p.b_w, b) == 0, f"\nWrite $b to b_w failed")
      assert(bfm.writeVal(p.push_w, 1) == 0, "\nWrite last (1) to push_w failed")

      // wait for dut by querying status_r
      var data = 0
      var polls = 0
      val maxPolls = 100
      do {
        val (d, resp) = bfm.read(p.status_r)
        assert(resp != SLVERR.toInt, "\nGot SLVERR while waiting for status_r")
        data = d.toInt
        polls += 1
        assert(polls <= maxPolls, f"\nstatus_r never went high after $maxPolls%d polls")
      } while (data != 1)

      bfm.expectVal(p.result_r, a * b)
    }
  }
}
