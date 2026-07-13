"""The waiver ledger: human verdicts persisted as formal constraints.

Kinds:
  input_class          — exclude an input class on chosen operands (assume)
  input_class_pair     — exclude a specific (class(a), class(b)) combination (assume)
  input_expr           — raw SV predicate over inputs `a`,`b` that must hold (assume)
  output_nan_canonical — outputs compare equal if both are NaN (payload waived)
  output_ulp_tolerance — outputs compare equal if within N ulp (and neither NaN)
  output_subnormal_flush — where gold underflows gradually (subnormal/zero result),
                           gate may return zero or min-normal of the same sign

Every entry carries who signed it off and why; the ledger IS the deliverable.
"""

import datetime
import getpass
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .fmt import (FpFormat, sv_class_predicate, sv_is_nan, sv_is_subnormal,
                  sv_is_zero, sv_ordered_key)

INPUT_CLASSES = ["zero", "subnormal", "normal", "inf", "nan"]


@dataclass
class Waiver:
    id: str
    kind: str
    reason: str = ""
    signed_off_by: str = ""
    date: str = ""
    # kind-specific:
    cls: str = ""                     # input_class
    operands: list[str] = field(default_factory=lambda: ["a", "b"])
    cls_a: str = ""                   # input_class_pair
    cls_b: str = ""
    expr: str = ""                    # input_expr
    ulp: int = 0                      # output_ulp_tolerance


def new_waiver(kind: str, wid: str, reason: str, **kw) -> Waiver:
    return Waiver(
        id=wid, kind=kind, reason=reason,
        signed_off_by=getpass.getuser(),
        date=datetime.date.today().isoformat(),
        **kw,
    )


def load_waivers(path: Path) -> list[Waiver]:
    if not path.exists():
        return []
    with open(path) as f:
        raw = json.load(f)
    return [Waiver(**w) for w in raw]


def save_waivers(path: Path, waivers: list[Waiver]) -> None:
    with open(path, "w") as f:
        json.dump([asdict(w) for w in waivers], f, indent=2)
        f.write("\n")


# ---- lowering to SV -----------------------------------------------------------

def input_assume_exprs(waivers: list[Waiver], f: FpFormat) -> list[tuple[str, str]]:
    """-> [(waiver_id, sv_expr_that_must_hold)] over wrapper inputs a, b."""
    out = []
    for w in waivers:
        if w.kind == "input_class":
            terms = [f"!{sv_class_predicate(f, w.cls, op)}" for op in w.operands]
            out.append((w.id, "(" + " && ".join(terms) + ")"))
        elif w.kind == "input_class_pair":
            pa = sv_class_predicate(f, w.cls_a, "a")
            pb = sv_class_predicate(f, w.cls_b, "b")
            out.append((w.id, f"!({pa} && {pb})"))
        elif w.kind == "input_expr":
            out.append((w.id, f"({w.expr})"))
    return out


def output_compare_expr(waivers: list[Waiver], f: FpFormat,
                        gold: str = "out_gold", gate: str = "out_gate") -> str:
    """Equality expression relaxed per output waivers."""
    terms = [f"({gold} == {gate})"]
    nan_g, nan_d = sv_is_nan(f, gold), sv_is_nan(f, gate)
    for w in waivers:
        if w.kind == "output_nan_canonical":
            terms.append(f"({nan_g} && {nan_d})")
        elif w.kind == "output_ulp_tolerance":
            kg, kd = sv_ordered_key(f, gold), sv_ordered_key(f, gate)
            dist = f"(({kg}) > ({kd}) ? ({kg}) - ({kd}) : ({kd}) - ({kg}))"
            terms.append(f"(!{nan_g} && !{nan_d} && ({dist}) <= {f.width}'d{w.ulp})")
        elif w.kind == "output_subnormal_flush":
            w1 = f.width - 1
            min_normal = 1 << f.frac_bits
            gold_tiny = f"({sv_is_subnormal(f, gold)} || {sv_is_zero(f, gold)})"
            gate_flushed = (f"(({gate}[{w1-1}:0] == {w1}'h0) || "
                            f"({gate}[{w1-1}:0] == {w1}'h{min_normal:x}))")
            same_sign = f"({gold}[{w1}] == {gate}[{w1}])"
            terms.append(f"({gold_tiny} && {gate_flushed} && {same_sign})")
    return " || ".join(terms)


# ---- reference-side compare (python), must mirror output_compare_expr ----------

def outputs_equivalent(waivers: list[Waiver], f: FpFormat, gold_bits: int, gate_bits: int) -> bool:
    if gold_bits == gate_bits:
        return True
    g_nan = f.classify(gold_bits) in ("qnan", "snan")
    d_nan = f.classify(gate_bits) in ("qnan", "snan")
    for w in waivers:
        if w.kind == "output_nan_canonical" and g_nan and d_nan:
            return True
        if w.kind == "output_ulp_tolerance" and not g_nan and not d_nan:
            d = f.ulp_distance(gold_bits, gate_bits)
            if d is not None and d <= w.ulp:
                return True
        if w.kind == "output_subnormal_flush":
            w1 = f.width - 1
            mag_mask = (1 << w1) - 1
            min_normal = 1 << f.frac_bits
            gold_tiny = f.classify(gold_bits) in ("subnormal", "zero")
            gate_flushed = (gate_bits & mag_mask) in (0, min_normal)
            same_sign = (gold_bits >> w1) == (gate_bits >> w1)
            if gold_tiny and gate_flushed and same_sign:
                return True
    return False


def inputs_admitted(waivers: list[Waiver], f: FpFormat, a: int, b: int) -> bool:
    """Python mirror of input assumes (class-based kinds only; input_expr not evaluated)."""
    def cls5(bits: int) -> str:
        c = f.classify(bits)
        return "nan" if c in ("qnan", "snan") else c
    ca, cb = cls5(a), cls5(b)
    for w in waivers:
        if w.kind == "input_class":
            if ("a" in w.operands and ca == w.cls) or ("b" in w.operands and cb == w.cls):
                return False
        elif w.kind == "input_class_pair":
            if ca == w.cls_a and cb == w.cls_b:
                return False
    return True
