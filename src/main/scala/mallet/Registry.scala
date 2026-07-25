// SPDX-License-Identifier: Apache-2.0
package mallet

import chisel3._
import scala.collection.mutable
import java.security.MessageDigest

/** Collects the properties elaborated across a run and writes the sidecar that
  * lets the shell-side report attribute a BTOR2 verdict back to an English
  * sentence.
  *
  * Process-global because Chisel elaboration is single-threaded. `clear()` must
  * be called at the top of each emitting `App`, since `make formal-gen` runs
  * several mains in one sbt invocation and they would otherwise bleed together.
  */
object MalletRegistry {

  final case class Entry(
    module: String,
    label:  String,
    name:   String,
    prop:   Prop,
    note:   String,
    idx:    Int,
    maxPast: Int,
    kind:   PropKind,
    coverLabel: Option[String]   // reachability cover for this property, if any
  )

  private val entries = mutable.ArrayBuffer.empty[Entry]

  /** When true, `mallet(...)` also emits the reachability-cover hardware. Set
    * for the dedicated reach elaboration only, so the main model stays cover-free
    * (covers would otherwise be seen by `make formal` and, fatally, by rIC3 --
    * covers are meant to be violated, so an unbounded prover would always report
    * SAT). See FormalAxi4LiteMacChirrtlMain for the two-emission pattern.
    */
  var coversEnabled: Boolean = false

  def clear(): Unit = entries.clear()

  def all: Seq[Entry] = entries.toSeq

  def forModule(m: String): Seq[Entry] = entries.filter(_.module == m).toSeq

  /** Stable machine identity for a property.
    *
    * `MT_<NN>_<name>_<hash8>`:
    *   - `NN`     preserves readable source order in the report
    *   - `name`   makes the emitted IR self-describing when debugging by grep
    *   - `hash8`  is sha1 of the canonical AST, so identity survives reordering
    *              and changes detectably when the property itself is edited
    *
    * Restricted to `[A-Za-z0-9_]` so the shell-side `grep -oE` stays trivially
    * safe.
    */
  def labelFor(idx: Int, name: String, prop: Prop): String = {
    val sha = MessageDigest.getInstance("SHA-1").digest(prop.canon.getBytes("UTF-8"))
    val hash8 = sha.take(4).map(b => f"${b & 0xff}%02x").mkString
    f"MT_$idx%02d_${sanitize(name)}_$hash8"
  }

  private def sanitize(s: String): String =
    s.map(c => if (c.isLetterOrDigit || c == '_') c else '_')

  private[mallet] def register(
    module: String,
    label:  String,
    name:   String,
    prop:   Prop,
    note:   String,
    idx:    Int,
    kind:   PropKind,
    coverLabel: Option[String]
  ): Unit = entries += Entry(module, label, name, prop, note, idx, prop.maxPast, kind, coverLabel)

  /** Write the per-module sidecar.
    *
    * MUST be called AFTER `emitCHIRRTLFile` returns. The English rendering reads
    * `instanceName`, which is only stable once the module is closed.
    */
  def writeSidecar(dir: String, chiselVersion: String = "7.13.0"): Unit = {
    if (entries.isEmpty) return
    val d = os.Path(dir, os.pwd)
    os.makeDir.all(d)

    entries.groupBy(_.module).foreach { case (module, es) =>
      val props = es.sortBy(_.idx).map { e =>
        ujson.Obj(
          "label"   -> e.label,
          "name"    -> e.name,
          "idx"     -> e.idx,
          "maxPast" -> e.maxPast,
          "kind"    -> (e.kind match { case AssertK => "assert"; case AssumeK => "assume" }),
          "shape"   -> (e.prop match {
                          case _: Implies => "implies"
                          case _: Always  => "always"
                        }),
          "nl"      -> Render.toNL(e.prop),
          "canon"   -> e.prop.canon,
          "coverLabel" -> (e.coverLabel match { case Some(c) => ujson.Str(c); case None => ujson.Null }),
          "note"    -> e.note
        )
      }
      val obj = ujson.Obj(
        "module" -> module,
        "chisel" -> chiselVersion,
        "props"  -> ujson.Arr.from(props)
      )
      os.write.over(d / s"$module.props.json", ujson.write(obj, indent = 2))
      println(s"[mallet] wrote ${d / s"$module.props.json"} (${props.length} properties)")
    }
  }
}

/** Mixed into a `Module` to give it property-elaboration machinery.
  *
  * Carries machinery only, never properties -- the properties live in the
  * concrete design subclass.
  *
  * Attachment note: this must be mixed into a SUBCLASS of the design under test,
  * not into the design itself. Scala linearization runs trait bodies BEFORE the
  * subclass body, so a trait mixed directly into the DUT would try to reference
  * registers that do not exist yet. Subclass bodies run after the parent body,
  * so every `val` in the DUT is initialized and directly referenceable -- no
  * `BoringUtils`, no wrapper ports, and zero edits to the design.
  */
trait MalletProperties { this: chisel3.Module =>

  /** Override to switch `past` realisation. See `PastBackend`. */
  def pastBackend: PastBackend = LtlPast

  // Per-INSTANCE. A global cache would hand back a Bool belonging to a
  // different module and produce a cross-module-reference error.
  private val warmCache = mutable.Map.empty[Int, Bool]

  private def warm(n: Int): Bool =
    if (n == 0) true.B else warmCache.getOrElseUpdate(n, formal.FormalUtils.warmedUp(n))

  /** Elaborate the given properties.
    *
    * Call ONCE, as the LAST statement of the module body. Chisel exposes no
    * public end-of-body hook that can still add hardware (`afterModuleBuilt`
    * runs after the module is closed), hence the explicit call. The emitting
    * `App` checks the registry is non-empty afterwards so forgetting it fails
    * loudly rather than silently producing an unverified design.
    *
    * Must be at top module scope, never inside a `when` -- `warmedUp(n)` builds
    * a `RegInit` and a `when`.
    */
  // Running index across every mallet(...) / contract(...) call on this module,
  // so a contract set and hand-written properties never collide on idx.
  private var propIdx = 0

  protected def mallet(ps: NamedProp*): Unit = {
    val module = this.desiredName
    ps.foreach { np =>
      propIdx += 1
      val label = MalletRegistry.labelFor(propIdx, np.name, np.prop)
      Render.toChisel(label, np.prop, warm, np.kind, pastBackend)
      // Reachability cover, only for assert-kind implications (an assumption is a
      // constraint, and a bare Always has no antecedent to be unreachable). The
      // label is recorded always (metadata); the hardware is emitted only in the
      // cover-enabled reach elaboration.
      val coverLabel =
        if (np.kind == AssertK) Render.coverLabelFor(label, np.prop) else None
      if (MalletRegistry.coversEnabled) coverLabel.foreach(cl => Render.emitCover(cl, np.prop, warm))
      MalletRegistry.register(module, label, np.name, np.prop, np.note, propIdx, np.kind, coverLabel)
    }
  }

  /** Attach a whole protocol contract set to this module. The set produces both
    * assertions (the design's obligations) and assumptions (constraints on its
    * environment) from the protocol bundle alone -- no per-design annotation.
    */
  protected def contract[B](set: _root_.mallet.contract.ContractSet[B], bundle: B): Unit =
    mallet(set.properties(bundle): _*)
}
