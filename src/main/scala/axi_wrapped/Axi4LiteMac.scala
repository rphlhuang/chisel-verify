package axi_wrapped

import arithmetic.Mac

import axi._
import axi.AxiLiteResp._
import axi.AxiModuleParamsHelper._
import upickle.default._

import chisel3._
import chisel3.util._

case class MacModuleParams( // Note: do not put default value here
                            // params suffixed with _r, _w, or _rw represent addresses
                            // DefParams
                            soft_reset_rw : Long,
                            // module params
                            width_p : Int,
                            accWidth_p : Int,
                            // io
                            a_w : Long,
                            b_w : Long,
                            push_w : Long,
                            result_r : Long,
                            status_r : Long,
                            // constant definition
                            reset_cycles : Int // soft reset cycles
                          ) extends AxiModuleParams with AxiModuleDefParams
{
  val moduleName = "Mac"
}

object MacModuleParams {
  implicit val rw: ReadWriter[MacModuleParams] = macroRW

  def default(width_p: Int = 8, accWidth_p: Int = 32) : MacModuleParams =
    new MacModuleParams(
      soft_reset_rw = 0x0, a_w = 0x10, b_w = 0x14, push_w = 0x20, result_r = 0x24, status_r = 0x28,
      width_p = width_p, accWidth_p = accWidth_p, reset_cycles = 8
    )
}

class Axi4LiteMac(p : MacModuleParams, debugprint: Boolean = false)
  extends chisel3.Module with axi.HasAxiLite32IO {

  override val S = IO(new AxiLite32IO())

  // -----------------------------
  // AXI-lite regs
  // -----------------------------
  
  val awHoldValidReg = RegInit(false.B)
  val awHoldAddrReg = Reg(UInt(32.W))
  val wHoldValidReg = RegInit(false.B)
  val wHoldDataReg = Reg(UInt(32.W))
  val wHoldStrbReg = Reg(UInt(4.W))

  val bvalidReg = RegInit(false.B)
  val brespReg = RegInit(0.U(2.W))

  val doWrite = awHoldValidReg && wHoldValidReg && !bvalidReg

  // -----------------------------
  // Instantiate Mac DUT and regs
  // -----------------------------  
  
  val softResetPulseReg = RegInit(false.B) // soft reset: when doWrite and write addr
  softResetPulseReg := (doWrite && (awHoldAddrReg === p.soft_reset_rw.U) && (wHoldStrbReg === "b1111".U))
  val combinedReset = (softResetPulseReg || reset.asBool) // reset if whole module reset OR dut-only soft reset
  val dut = withReset(combinedReset) {Module(new Mac(width = p.width_p, accWidth = p.accWidth_p))}

  val aReg = Reg(UInt(p.width_p.W))
  val bReg = Reg(UInt(p.width_p.W))
  val pushPendingReg = RegInit(false.B)
  val lastReg = RegInit(false.B)

  // -----------------------------
  // Write path: AW -> W and B
  // -----------------------------

  S.AXI.awready := !awHoldValidReg && !bvalidReg && !pushPendingReg
  S.AXI.wready := !wHoldValidReg && !bvalidReg && !pushPendingReg
  val awFire = S.AXI.awvalid && S.AXI.awready
  val wFire = S.AXI.wvalid && S.AXI.wready

  when(awFire) {
    awHoldValidReg := true.B;
    awHoldAddrReg := S.AXI.awaddr(19, 0) // in case MMIO range is 1MB
  }

  when(wFire) {
    wHoldValidReg := true.B
    wHoldDataReg := S.AXI.wdata
    wHoldStrbReg := S.AXI.wstrb
  }

  when(doWrite) {

    val fullWrite = (wHoldStrbReg === "b1111".U) // only accept word writes
    val a = awHoldAddrReg
    val bresp = WireDefault(OKAY.U)

    when(!fullWrite) { 
      bresp := SLVERR.U // support full write only for this example
    }.otherwise { 
      // if not strobe or reset, write to internal reg or start calc
      when(a === p.a_w.U) {
        aReg := wHoldDataReg
      }.elsewhen(a === p.b_w.U) {
        bReg := wHoldDataReg
      }.elsewhen(a === p.push_w.U) {
        // if push_w is 1, push and last; else just push
        pushPendingReg := true.B
        lastReg := wHoldDataReg(0).asBool
      }.elsewhen(a === p.soft_reset_rw.U) {
        // pass, handled by softResetPulseReg assign above
      }.otherwise {
        bresp := SLVERR.U
      }
    }
    brespReg := bresp
    bvalidReg := true.B
    awHoldValidReg := false.B
    wHoldValidReg := false.B

  }

  // when downstream ready and we have valid data, fire downstream write
  dut.io.in.valid := pushPendingReg
  dut.io.in.bits.a := aReg
  dut.io.in.bits.b := bReg
  dut.io.in.bits.last := lastReg
  when(pushPendingReg && dut.io.in.fire) {
    pushPendingReg := false.B
  }

  // B resp reset
  when(bvalidReg && S.AXI.bready) {
    bvalidReg := false.B
  }
  S.AXI.bvalid := bvalidReg
  S.AXI.bresp := brespReg

  // -----------------------------
  // Read path: AR -> R
  // -----------------------------

  val rdataReg = Reg(UInt(32.W))
  val rvalidReg = RegInit(false.B)
  val rrespReg = RegInit(0.U(2.W))

  // object RState extends ChiselEnum {
  //   val READY2READ, COMPLETED = Value
  // }

  // val rstateReg = RegInit(RState.READY2READ)

  S.AXI.arready := rstateReg === RState.READY2READ
  S.AXI.rvalid := rstateReg === RState.COMPLETED
  S.AXI.rdata := rdataReg
  S.AXI.rresp := rrespReg

  val arFire = S.AXI.arvalid && S.AXI.arready

  // when(arFire) {
  //   if (debugprint) printf("%d: arFire: %x\n", cycles, S.AXI.araddr)
  //   val araddr = S.AXI.araddr(19, 0) // 1MB range
  //   rrespReg := OKAY.U

  //   val rstate = WireDefault(RState.READY2READ)

  //   when(araddr === p.const1_r.U) {
  //     rdataReg := p.const1.U
  //     rstate := RState.COMPLETED
  //   }.elsewhen(araddr === p.const2_r.U) {
  //     rdataReg := p.const2.U
  //     rstate := RState.COMPLETED
  //   }.elsewhen(araddr === p.soft_reset_rw.U) {
  //     rdataReg := softResetDoneReg
  //     rstate := RState.COMPLETED
  //   }.elsewhen(araddr === p.dut_rw.U) {
  //     rdataReg := dut.out
  //     rstate := RState.COMPLETED
  //   }.otherwise {
  //     if (debugprint) printf("%d: bad read req %d\n", cycles, araddr)
  //     // rrespReg := SLVERR.U // with this, the host can only read 0xffffffff for any addresses on AVED
  //     rdataReg := 0xbad00000L.U | S.AXI.araddr(31, 0)
  //     if (debugprint) printf(cf"arFire otherwise: addr=${S.AXI.araddr}%16x\n")
  //     rstate := RState.COMPLETED
  //   }
  //   rstateReg := rstate
  // }

  // when(rstateReg === RState.COMPLETED && S.AXI.rready) {
  //   rstateReg := RState.READY2READ
  // }
}

object Axi4LiteMac extends App {
  val const1 : Long = 0xdeadbeefL // module id
  val const2 : Long = getGitHash

  val p = checkParamEnv(
    MacModuleParams.default(const1 = const1, const2 = const2),
    "CMD_MODULE_PARAMS")

  EmitVerilog.generate(new Axi4LiteMac(p, debugprint=true), p)
}
