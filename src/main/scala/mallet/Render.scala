// SPDX-License-Identifier: Apache-2.0
package mallet

import chisel3._
import chisel3.util.ShiftRegister
import chisel3.ltl._
import chisel3.ltl.Sequence._

/** How `past(n)` is realised in hardware. */
sealed trait PastBackend

/** Emit `ltl.past` (a `seq.shiftreg`). This is what `arithmetic.Mac` and
  * `formal.FormalUtils` already assume, and it is confirmed to lower.
  */
case object LtlPast extends PastBackend

/** Emit an explicit `ShiftRegister` with a known reset value, so the only LTL
  * construct the tool ever emits is the top-level `|->`.
  *
  * This is the escape hatch if `ltl.or` / `ltl.not` turn out not to lower (only
  * `ltl.and` is confirmed today, via `Mac.scala`). It also removes the
  * design-dependent shiftreg-reset lottery documented in the formal-probe README:
  * with `ltl.past`, whether CIRCT gives the shiftreg a reset mux varies by design,
  * whereas here the init value is chosen explicitly.
  *
  * Cost: it creates registers unconditionally, so elaborate under a Verification
  * layer if the design is also being synthesized.
  */
case object ShiftRegPast extends PastBackend

/** Renders one AST value to Chisel and to English.
  *
  * Both renderers are exhaustive pattern matches over the sealed traits, so
  * adding an AST node without teaching both renderers about it is a compile
  * error rather than a silent divergence. That is the whole point of the
  * one-object-three-renderings design.
  */
object Render {

  // -------------------------------------------------------------------------
  // Chisel
  // -------------------------------------------------------------------------

  /** Emit `AssertProperty` / `AssumeProperty` for one property.
    *
    * @param label   the stable machine identity, carried into the emitted IR so
    *                the report can attribute verdicts by name rather than by
    *                position (see MalletRegistry.labelFor)
    * @param prop    the property
    * @param warm    per-module memoized `warmedUp(n)` provider
    * @param kind    obligation (assert) vs environment assumption (assume)
    * @param backend how `past` is realised
    */
  def toChisel(
    label:   String,
    prop:    Prop,
    warm:    Int => Bool,
    kind:    PropKind = AssertK,
    backend: PastBackend = LtlPast
  ): Unit = {
    val p = Normalize(prop)
    val n = p.maxPast

    val body: Property = p match {
      // Guard goes into the antecedent, with N computed over BOTH sides.
      // `warm(N) && A |-> C` is the same boolean formula as
      // `warm(N) |-> (A |-> C)`: every connective here is same-cycle and `past`
      // is a sampling function, not a temporal quantifier. The `.and` form is
      // used because it matches Mac.scala's existing style and emits one fewer
      // `ltl.implication`.
      case Implies(a, c) if n > 0 =>
        seq(warmSeq(warm, n), a, backend) |-> seqOf(c, backend)

      case Implies(a, c) =>
        seqOf(a, backend) |-> seqOf(c, backend)

      // A bare property with a `past` in it has no antecedent to guard, so
      // SYNTHESIZE one. It must NOT become `warm(N) && e` -- that would assert
      // the warm-up counter has reached N, which is a different (and false)
      // property.
      case Always(e) if n > 0 =>
        warmSeq(warm, n) |-> seqOf(e, backend)

      case Always(e) =>
        seqOf(e, backend)
    }

    kind match {
      case AssertK =>
        AssertProperty(body, label = Some(label))
      case AssumeK =>
        // MEASURED: `verif.clocked_assume` with an `ltl.implication` body does
        // NOT lower to BTOR2 -- the pass whitelists only `clocked_assert` as a
        // user of the clock, and the leftover `ltl.implication` leaks a dangling
        // operand id that corrupts the whole file. So assumes are rendered as a
        // single plain Bool (boolean implication, shift-register past). A btor2
        // `constraint` only needs a boolean anyway.
        AssumeProperty(toBoolBody(p, warm), label = Some(label))
    }
  }

  /** Collapse a whole (normalized) property to one plain Bool: boolean
    * implication, `past` realised as a shift register. Used for assumptions,
    * whose `clocked_assume` form cannot carry an `ltl.implication`.
    */
  private def toBoolBody(p: Prop, warm: Int => Bool): Bool = {
    val n = p.maxPast
    p match {
      case Implies(a, c) =>
        val ante = if (n > 0) warm(n) && toBool(a, ShiftRegPast) else toBool(a, ShiftRegPast)
        !ante || toBool(c, ShiftRegPast)
      case Always(e) =>
        if (n > 0) !warm(n) || toBool(e, ShiftRegPast) else toBool(e, ShiftRegPast)
    }
  }

  /** The cover label a property would carry, or `None` if it has no antecedent
    * (a bare `Always` is checked every cycle -- it cannot be vacuous for want of
    * a trigger). This is pure metadata, computed whether or not the cover
    * hardware is actually emitted, so the sidecar always records it.
    */
  def coverLabelFor(parentLabel: String, prop: Prop): Option[String] =
    Normalize(prop) match {
      case _: Implies => Some("COVER_" + parentLabel)
      case _: Always  => None
    }

  /** Emit the reachability-cover hardware for an implication property.
    *
    * The cover is `assert(!(warm(n) && antecedent))`: btormc VIOLATES it exactly
    * when the guarded antecedent is reachable, i.e. when the property is actually
    * exercised. A cover that is NOT violated means the antecedent never holds, so
    * the parent property passes vacuously.
    *
    * It is an ordinary `AssertProperty` (with a `COVER_` label) rather than a
    * `CoverProperty`, because `verif.clocked_cover` does not lower to BTOR2. The
    * covers are emitted into a SEPARATE model (a second elaboration with covers
    * enabled) so they never pollute the real verdicts or the unbounded rIC3
    * proof -- see MalletRegistry.coversEnabled. The antecedent uses the
    * shift-register `past` backend so the whole cover is one plain `Bool`.
    */
  def emitCover(coverLabel: String, prop: Prop, warm: Int => Bool): Unit =
    Normalize(prop) match {
      case Implies(ante, _) =>
        val n    = ante.maxPast
        val mask = if (n > 0) warm(n) else true.B
        val antBool = mask && toBool(ante, ShiftRegPast)
        AssertProperty(!antBool, label = Some(coverLabel))
      case Always(_) => ()
    }

  private def warmSeq(warm: Int => Bool, n: Int): Sequence = Sequence.BoolSequence(warm(n))

  private def seq(w: Sequence, a: Expr, backend: PastBackend): Sequence =
    w.and(seqOf(a, backend))

  /** Render a normalized expression as a `Sequence`.
    *
    * The `maxPast == 0` short-circuit is the important line: any subtree that
    * does not reach back in time becomes plain Chisel `Bool` logic, which is
    * trivially lowerable. Only genuinely temporal subtrees pay for `ltl.and` /
    * `ltl.or`.
    */
  private def seqOf(e: Expr, backend: PastBackend): Sequence =
    if (e.maxPast == 0 || backend == ShiftRegPast) {
      Sequence.BoolSequence(toBool(e, backend))
    } else {
      e match {
        // post-normalization `a` is an atom with maxPast == 0
        case Past(a, n) => Sequence.BoolSequence(toBool(a, backend)).past(n)
        case And(a, b)  => seqOf(a, backend).and(seqOf(b, backend))
        case Or(a, b)   => seqOf(a, backend).or(seqOf(b, backend))
        case Not(_) =>
          // Unreachable: Normalize pushes Not to the leaves precisely because
          // Property.not returns a Property, not a Sequence, and so could not
          // be used as an implication antecedent.
          throw new IllegalStateException(
            s"Not above Past survived normalization in: ${e.canon}"
          )
        case other =>
          throw new IllegalStateException(s"unreachable in seqOf: ${other.canon}")
      }
    }

  /** Render an expression as a plain Chisel `Bool`.
    *
    * Only legal when the expression has `maxPast == 0`, or when the backend
    * realises `past` as an explicit `ShiftRegister` (which yields a `Bool`).
    */
  private def toBool(e: Expr, backend: PastBackend): Bool = e match {
    case B(d, _)       => d
    case TrueE         => true.B
    case FalseE        => false.B
    case Not(a)        => !toBool(a, backend)
    case And(a, b)     => toBool(a, backend) && toBool(b, backend)
    case Or(a, b)      => toBool(a, backend) || toBool(b, backend)
    case Cmp(op, l, r) => op(l.toData, r.toData)
    case Past(a, n) =>
      backend match {
        case ShiftRegPast => ShiftRegister(toBool(a, backend), n, false.B, true.B)
        case LtlPast =>
          throw new IllegalStateException(
            s"Past reached toBool under the LtlPast backend: ${e.canon}"
          )
      }
  }

  // -------------------------------------------------------------------------
  // English
  // -------------------------------------------------------------------------

  /** Render a property as an English sentence.
    *
    * A pure function of the AST -- no Chisel state is touched beyond reading
    * signal names, so this must be called AFTER elaboration closes, when
    * `instanceName` is stable.
    */
  def toNL(p: Prop): String = {
    // Render the ORIGINAL shape, not the normalized one: normalization is a
    // compilation detail and its De Morgan output reads badly in English.
    val core = p match {
      case Implies(a, c) => s"Whenever ${nl(a)}, ${nl(c)}."
      case Always(e)     => s"At all times, ${nl(e)}."
    }
    val n = p.maxPast
    // Be honest that the warm-up mask makes the property vacuously true for the
    // first N cycles -- it can hide a genuine reset-boundary bug, and a report
    // that quietly claims more than it checked is worse than no report.
    if (n > 0) s"$core (Not checked for the first $n cycle(s) after reset.)" else core
  }

  private def name(d: Bool, alias: String): String =
    if (alias.nonEmpty) alias else Term.safeName(d)

  private def nl(e: Expr): String = e match {
    case B(d, alias)          => s"${name(d, alias)} is high"
    case TrueE                => "true"
    case FalseE               => "false"
    case Not(B(d, a))         => s"${name(d, a)} is low"
    // A negated past atom reads better flattened: "x was low N-ago" beats
    // "it is not the case that x was high N-ago".
    case Not(Past(B(d, a), n)) => s"${name(d, a)} was low ${cycleRef(n)}"
    case Not(x)               => s"it is not the case that ${nl(x)}"
    case And(a, b)            => s"${nl(a)} and ${nl(b)}"
    case Or(a, b)             => s"${nl(a)} or ${nl(b)}"
    case Cmp(op, l, r)        => s"${l.nl} ${op.word} ${r.nl}"
    // The cycle reference attaches to the WHOLE sampled subexpression, once at
    // the end: past(a && !b, 1) -> "a was high and b was low on the previous
    // cycle", not "a was high ... and b was low ..." with two markers.
    case Past(a, n)           => s"${nlPast(a)} ${cycleRef(n)}"
  }

  private def cycleRef(n: Int): String =
    if (n == 1) "on the previous cycle" else s"$n cycles ago"

  /** Past-tense rendering of a sampled subexpression, WITHOUT the cycle
    * reference (the caller appends that once). Distributes over the connectives
    * so a compound antecedent reads as one past-tense clause.
    */
  private def nlPast(e: Expr): String = e match {
    case B(d, a)       => s"${name(d, a)} was high"
    case Not(B(d, a))  => s"${name(d, a)} was low"
    case And(a, b)     => s"${nlPast(a)} and ${nlPast(b)}"
    case Or(a, b)      => s"${nlPast(a)} or ${nlPast(b)}"
    case Cmp(op, l, r) => s"${l.nl} ${op.word} ${r.nl}"
    case TrueE         => "true"
    case FalseE        => "false"
    // nested past or a bare Not(compound): fall back to present tense + "held"
    case other         => s"${nl(other)}, which held"
  }
}
