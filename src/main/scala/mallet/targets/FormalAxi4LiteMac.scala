// SPDX-License-Identifier: Apache-2.0
package mallet.targets

import chisel3._
import _root_.circt.stage.ChiselStage

import mallet._
import mallet.contract.AxiLite32Contract
import axi_wrapped.{Axi4LiteMac, MacModuleParams}

/** Phase 1 target: hand-written properties for `Axi4LiteMac`.
  *
  * This is a SUBCLASS, so `Axi4LiteMac` itself is never edited and every one of
  * its internal signals is directly referenceable (subclass bodies run after
  * the parent body). See `MalletProperties` for why a trait mixed into the DUT
  * would not work.
  *
  * The properties are split into two deliberately-separated tiers, because they
  * are different KINDS of claim and (crucially) a different phase of mallet is
  * responsible for each:
  *
  *   TIER 1 -- BLACK-BOX AXI-Lite CONTRACT.  References only the `S.AXI.*` port
  *     signals and wires derived purely from them. These properties follow from
  *     the single fact "this module is an AxiLite32 slave" -- they need NO
  *     knowledge of what the module does, and NO per-design annotation. This is
  *     the tier the Phase 3 generator should produce first and for free on every
  *     AXI design. A human writing by hand routinely forgets cases here.
  *
  *   TIER 2 -- WHITE-BOX / DESIGN-SPECIFIC.  Reaches below the AXI boundary --
  *     into the wrapper's own registers, or into the submodule's IO (`dut.io.*`).
  *     These are the properties that DO require understanding the design. Note
  *     that `dut.io.out` is an internal boundary, not the black-box interface, so
  *     asserting on it is a white-box choice -- a legitimate and standard formal
  *     technique (auxiliary internal invariants), but NOT what a memory-map role
  *     annotation could ever generate. See the note on `result_not_dropped`.
  *
  * Scope for BOTH tiers: protocol / structural correctness only. Nothing here
  * says the MAC computes a correct dot product; datapath correctness is a
  * separate differential-testing concern and is deliberately out of scope.
  */
class FormalAxi4LiteMac(p: MacModuleParams) extends Axi4LiteMac(p) with MalletProperties {

  // Black-box handles: the actual AXI ports.
  private val bvalid  = B(S.AXI.bvalid, "bvalid")
  private val awready = B(S.AXI.awready, "awready")
  private val wready  = B(S.AXI.wready, "wready")

  // Formal-only saturating counter for the reachability canary below: counts to
  // 4 and stops, so its value is never 7. `reachCtr === 7` is thus a genuinely
  // UNREACHABLE antecedent -- but not a constant, so the compiler cannot fold it.
  private val reachCtr = RegInit(0.U(3.W))
  when(reachCtr < 4.U) { reachCtr := reachCtr + 1.U }

  // White-box handles: below the AXI interface.
  private val dutValid   = B(dutValidReg, "dutValidReg")
  private val pushPend   = B(pushPendingReg, "pushPendingReg")
  private val srPulse    = B(softResetPulseReg, "softResetPulseReg")
  private val macOutFire = B(dut.io.out.valid && dut.io.out.ready, "macOutFire")
  private val macInReady = B(dut.io.in.ready, "macInReady")

  // =======================================================================
  // TIER 1 -- AXI4-Lite contract, from the reusable library. ZERO annotation:
  // these follow from `S.AXI` being an AxiLite32 bundle and nothing else. This
  // one line replaces the hand-written bresp_legal / rresp_legal / b_stable /
  // r_stable, and adds the three master-channel VALID-stability assumptions
  // (aw / w / ar) that were never hand-written. See AxiLite32Contract.
  // =======================================================================
  contract(AxiLite32Contract, S.AXI)

  // =======================================================================
  // TIER 2 -- design-specific properties the contract library does not cover.
  // =======================================================================
  mallet(
    // (r_solicited / b_solicited are now Increment-2 contract properties --
    //  axi_r_solicited / axi_b_solicited via outstanding-transaction monitors --
    //  so the hand-written versions were deleted. Subsumption, again.)

    NamedProp.assert(
      "soft_reset_is_pulse",
      srPulse |=> !srPulse,
      "the soft-reset pulse is exactly one cycle wide"
    ),

    // Reaches into dut.io -- the submodule handshake, below the black box.
    NamedProp.assert(
      "push_retires",
      (pushPend && macInReady) |=> !pushPend,
      "a pending push is cleared once the MAC accepts it"
    ),

    // Design-specific serialization property that happens to be vacuous by
    // construction (restates the awready/wready equations). MEASURED: it does
    // NOT fold -- CIRCT catches syntactic identity, not entailment -- so it
    // sails through to NOCEX. The reason Phase 2 needs a reachability check.
    NamedProp.assert(
      "no_write_during_bresp",
      bvalid ==> (!awready && !wready),
      "vacuous by construction, but NOT folded -- see Phase 2 reachability check"
    ),

    // A SYNTACTIC tautology (x === x), which folds pre-HW. Included on purpose
    // to exercise the VACUOUS path: it proves the label-based join reports a
    // MISSING assertion rather than silently shifting its neighbours' verdicts.
    NamedProp.assert(
      "vacuity_canary",
      Always(Cmp(CmpOp.Eq, Sig(dutDataReg, "dutDataReg"), Sig(dutDataReg, "dutDataReg"))),
      "CANARY: x === x, must report VACUOUS or the join is broken"
    ),

    // SEMANTIC vacuity canary: the antecedent (reachCtr === 7) is unreachable
    // (the counter saturates at 4), so this passes trivially -- but it does NOT
    // fold (7 is a valid value, just never reached). Only the reachability pass
    // can catch it: expect VERDICT=VACUOUS with REACH=no. If this ever shows
    // NOCEX/REACH=yes, the cover pass is broken.
    NamedProp.assert(
      "reach_canary",
      Cmp(CmpOp.Eq, Sig(reachCtr, "reachCtr"), Lit(7, "7")) ==> dutValid,
      "CANARY: unreachable antecedent, must report REACH=no / VACUOUS"
    ),

    // The bug. WHITE-BOX BY NECESSITY: it relates an internal submodule
    // handshake (dut.io.out.fire) to an internal validity flag (dutValidReg).
    // No memory-map role could generate this -- neither macOutFire nor
    // dutValidReg has an address -- which is exactly why the role generator
    // (Phase 3b) would MISS this bug, and why white-box invariants remain a
    // human/LLM responsibility (Phase 5).
    //
    // The bug itself: Axi4LiteMac.scala:159-162 sets dutValidReg := true.B on
    // dut.io.out.fire; :167-173 sets dutValidReg := false.B on any result_r read.
    // Chisel last-connect makes the SECOND win, so a result accepted on the same
    // cycle as a result_r read is stored into dutDataReg but never marked valid
    // -- silently dropped, and the MAC has already cleared its accumulator.
    NamedProp.assert(
      "result_not_dropped",
      macOutFire |=> dutValid,
      "a MAC result accepted from the DUT must not be silently dropped"
    )
  )
}

object FormalAxi4LiteMacChirrtlMain extends App {
  val p = MacModuleParams.default()

  // 1. Main model, COVER-FREE: this is what make formal, the per-property
  //    verdicts, and the unbounded rIC3 proof all run on.
  MalletRegistry.clear()
  MalletRegistry.coversEnabled = false
  ChiselStage.emitCHIRRTLFile(
    new FormalAxi4LiteMac(p),
    args = Array("--target-dir", "generated/mallet/chirrtl")
  )
  // AFTER elaboration: instanceName is only stable once the module is closed.
  // The sidecar (incl. each property's coverLabel metadata) comes from here.
  MalletRegistry.writeSidecar("generated/mallet/props")
  require(
    MalletRegistry.forModule("FormalAxi4LiteMac").nonEmpty,
    "no properties registered -- did the module body forget its trailing mallet(...) call?"
  )

  // 2. Reach model, COVERS ENABLED: a second elaboration whose only purpose is
  //    the antecedent-reachability btor2. Emitted to a separate dir so make
  //    formal (which globs .../chirrtl/*.fir) never sees it.
  MalletRegistry.clear()
  MalletRegistry.coversEnabled = true
  ChiselStage.emitCHIRRTLFile(
    new FormalAxi4LiteMac(p),
    args = Array("--target-dir", "generated/mallet/reach")
  )
  MalletRegistry.coversEnabled = false
}
