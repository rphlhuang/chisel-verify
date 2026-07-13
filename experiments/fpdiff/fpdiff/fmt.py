"""IEEE-754 binary interchange format utilities, parameterized by (exp, sig) widths.

sig includes the hidden bit, matching hardfloat convention: FP32 = (8, 24).
All values travel as plain ints of width 1 + exp + (sig - 1).
"""

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class FpFormat:
    exp: int
    sig: int  # includes hidden bit

    @property
    def width(self) -> int:
        return 1 + self.exp + self.sig - 1

    @property
    def frac_bits(self) -> int:
        return self.sig - 1

    @property
    def bias(self) -> int:
        return (1 << (self.exp - 1)) - 1

    @property
    def exp_mask(self) -> int:
        return (1 << self.exp) - 1

    @property
    def frac_mask(self) -> int:
        return (1 << self.frac_bits) - 1

    def fields(self, bits: int) -> tuple[int, int, int]:
        """-> (sign, biased_exp, frac)"""
        frac = bits & self.frac_mask
        e = (bits >> self.frac_bits) & self.exp_mask
        s = (bits >> (self.frac_bits + self.exp)) & 1
        return s, e, frac

    def classify(self, bits: int) -> str:
        s, e, frac = self.fields(bits)
        if e == self.exp_mask:
            if frac == 0:
                return "inf"
            # MSB of frac set = quiet NaN (IEEE 754-2008 convention)
            return "qnan" if frac >> (self.frac_bits - 1) else "snan"
        if e == 0:
            return "zero" if frac == 0 else "subnormal"
        return "normal"

    def to_fraction(self, bits: int) -> Fraction | None:
        """Exact rational value; None for NaN. Infinities raise OverflowError."""
        s, e, frac = self.fields(bits)
        sign = -1 if s else 1
        if e == self.exp_mask:
            if frac:
                return None
            raise OverflowError("inf")
        if e == 0:
            return sign * Fraction(frac, 1 << self.frac_bits) * Fraction(2) ** (1 - self.bias)
        return sign * Fraction((1 << self.frac_bits) + frac, 1 << self.frac_bits) * Fraction(2) ** (e - self.bias)

    def to_float(self, bits: int) -> float:
        cls = self.classify(bits)
        s, e, frac = self.fields(bits)
        if cls in ("qnan", "snan"):
            return float("nan")
        if cls == "inf":
            return float("-inf") if s else float("inf")
        return float(self.to_fraction(bits))

    def ordered_key(self, bits: int) -> int:
        """Monotone int mapping (sign-magnitude -> offset), so ulp distance = key diff.

        Not meaningful for NaN.
        """
        s = bits >> (self.width - 1)
        mag = bits & ((1 << (self.width - 1)) - 1)
        return -mag if s else mag

    def ulp_distance(self, a: int, b: int) -> int | None:
        """Distance in representable steps; None if either is NaN.

        +0/-0 are adjacent (distance 0 would require special-casing; we report 0)."""
        if self.classify(a) in ("qnan", "snan") or self.classify(b) in ("qnan", "snan"):
            return None
        ka, kb = self.ordered_key(a), self.ordered_key(b)
        d = abs(ka - kb)
        # treat +0 / -0 as equal
        if d == 0 or {ka, kb} == {0}:
            return 0
        return d

    def describe(self, bits: int) -> str:
        s, e, frac = self.fields(bits)
        cls = self.classify(bits)
        val = self.to_float(bits)
        hexw = (self.width + 3) // 4
        base = f"0x{bits:0{hexw}x} [s={s} e={e:#x} f={frac:#x}] {cls}"
        if cls in ("normal", "subnormal", "zero"):
            base += f" ≈ {val!r}"
        elif cls == "inf":
            base += f" ({'-' if s else '+'}inf)"
        return base


FP16 = FpFormat(5, 11)
BF16 = FpFormat(8, 8)
FP32 = FpFormat(8, 24)
FP64 = FpFormat(11, 53)

# SystemVerilog predicate snippets for a signal `x` of this format --------------

def sv_is_subnormal(f: FpFormat, x: str) -> str:
    return (f"(({x}[{f.width-2}:{f.frac_bits}] == {f.exp}'h0) && "
            f"({x}[{f.frac_bits-1}:0] != {f.frac_bits}'h0))")


def sv_is_nan(f: FpFormat, x: str) -> str:
    return (f"(({x}[{f.width-2}:{f.frac_bits}] == {f.exp}'h{f.exp_mask:x}) && "
            f"({x}[{f.frac_bits-1}:0] != {f.frac_bits}'h0))")


def sv_is_inf(f: FpFormat, x: str) -> str:
    return (f"(({x}[{f.width-2}:{f.frac_bits}] == {f.exp}'h{f.exp_mask:x}) && "
            f"({x}[{f.frac_bits-1}:0] == {f.frac_bits}'h0))")


def sv_is_zero(f: FpFormat, x: str) -> str:
    return f"({x}[{f.width-2}:0] == {f.width-1}'h0)"


def sv_class_predicate(f: FpFormat, cls: str, x: str) -> str:
    if cls == "subnormal":
        return sv_is_subnormal(f, x)
    if cls == "nan":
        return sv_is_nan(f, x)
    if cls == "inf":
        return sv_is_inf(f, x)
    if cls == "zero":
        return sv_is_zero(f, x)
    if cls == "normal":
        return (f"(!{sv_is_subnormal(f, x)} && !{sv_is_nan(f, x)} && "
                f"!{sv_is_inf(f, x)} && !{sv_is_zero(f, x)})")
    raise ValueError(f"unknown input class {cls!r}")


def sv_ordered_key(f: FpFormat, x: str) -> str:
    """Monotone key as an SV expression (width w), for ulp-bounded comparison."""
    w = f.width
    # if sign: ~x  else: x | (1 << w-1)  -- classic total-order trick, offset variant
    return f"({x}[{w-1}] ? ~{x} : ({x} | {w}'h{1 << (w-1):x}))"
