// SPDX-License-Identifier: Apache-2.0
// See LICENSE file for details.
package fp

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.flatspec.AnyFlatSpec

// Golden reference: Java Float arithmetic is IEEE-754 single-precision round-nearest-even,
// canonical NaN result becomes 0x7FC00000 which is what the NaN hardfloat/RISCV produce.

class FP32UnitsSpec extends AnyFlatSpec with ChiselSim {

  // bit <-> float helpers
  private def toF(bits: Int): Float = java.lang.Float.intBitsToFloat(bits)
  private def u32(bits: Int): UInt = (bits.toLong & 0xFFFFFFFFL).U(32.W)
  // floatToIntBits to "canonicalize", which only affects NaN (every NaN -> 0x7FC00000); use for expected results
  private def canon(x: Float): Int = java.lang.Float.floatToIntBits(x)
  // floatToRawIntBits does straight conversion without canonicalizing; use for stimuli
  private def f(x: Float): Int = java.lang.Float.floatToRawIntBits(x)


  // Peek + assert so a failure prints "expected 0x.., got 0x.." in hex.
  private def expectHex(actual: UInt, expected: Int, clue: String): Unit = {
    val got = actual.peek().litValue
    val exp = expected.toLong & 0xFFFFFFFFL
    assert(got == exp, f"$clue: expected 0x$exp%08x, got 0x$got%08x")
  }

  // f32 bit patterns      s/eemmmmmm
  private val PosZero    = 0x00000000
  private val NegZero    = 0x80000000
  private val PosInf     = 0x7f800000 // 0__1111_1111__000_0000_0000_0000_0000_0000
  private val NegInf     = 0xff800000 // 1__1111_1111__000_0000_0000_0000_0000_0000
  private val QNaN       = 0x7fc00000 // quiet (indicated by mantissa MSB set); 0__1111_1111__100_0000_0000_0000_0000_0000
  private val SNaN       = 0x7f800001 // signaling (indicated by mantissa MSB clear); 0__1111_1111__000_0000_0000_0000_0000_0001
  private val MinSubnrm  = 0x00000001 // smallest positive subnormal
  private val MaxSubnrm  = 0x007fffff // largest subnormal
  private val MinNormal  = 0x00800000 // smallest positive normal
  private val TwoToThe24 = f(16777216.0f) // 2^24 --> incs of 2.0 here so 2^24+1 tests testing round to even

  // test vectors
  private val vectors: Seq[(String, Int, Int)] = Seq(
    ("+0 , +0",                     PosZero,    PosZero),
    ("+0 , -0",                     PosZero,    NegZero),
    ("-0 , -0",                     NegZero,    NegZero),
    ("+inf , 1.0",                  PosInf,     f(1.0f)),
    ("+inf , -inf",                 PosInf,     NegInf),
    ("1.0 , qNaN",                  f(1.0f),    QNaN),
    ("1.0 , sNaN",                  f(1.0f),    SNaN),
    ("maxSubnormal , minNormal",    MaxSubnrm,  MinNormal),
    ("minSubnormal , minSubnormal", MinSubnrm,  MinSubnrm),
    ("2^24 , 1.0 (tie-to-even)",    TwoToThe24, f(1.0f)),
    ("-1.0 , -2.0",                 f(-1.0f),   f(-2.0f)),
    ("3.14 , 2.71",                 f(3.14f),   f(2.71f)),
  )

  // goldem model is JVM
  private def ref(mode: FPOpMode.Mode, a: Float, b: Float): Float = mode match {
    case FPOpMode.ADD => a + b
    case FPOpMode.SUB => a - b
    case FPOpMode.MUL => a * b
  }

  private def opName(mode: FPOpMode.Mode): String = mode.toString

  private def runVectors(mode: FPOpMode.Mode): Unit = {
    simulate(new FPCombUnit(8, 24, mode)) { dut =>
      for ((label, aBits, bBits) <- vectors) {
        val expected = canon(ref(mode, toF(aBits), toF(bBits)))
        dut.io.in_a.poke(u32(aBits))
        dut.io.in_b.poke(u32(bBits))
        expectHex(dut.io.out, expected, s"${opName(mode)}($label)")
      }
    }
    info(s"${opName(mode)}: ${vectors.length} vectors passed")
  }

  "FPCombUnit ADD" should "match IEEE-754 round-nearest-even on directed vectors" in {
    runVectors(FPOpMode.ADD)
  }

  "FPCombUnit SUB" should "match IEEE-754 round-nearest-even on directed vectors" in {
    runVectors(FPOpMode.SUB)
  }

  "FPCombUnit MUL" should "match IEEE-754 round-nearest-even on directed vectors" in {
    runVectors(FPOpMode.MUL)
  }
}