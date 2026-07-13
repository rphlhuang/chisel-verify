"""tempo property AST: natural-language intent and formal meaning in one object.

Boolean leaves are raw Verilog expressions (strings); the AST owns only the
*temporal* structure. This is the bounded-temporal-safety fragment: everything
here is compilable to helper registers + one boolean assert (see compiler.py),
which is precisely why it runs on the whole open toolchain.
"""

from dataclasses import dataclass, field


class Node:
    """A boolean-valued formula over the trace (possibly referencing history)."""


@dataclass(frozen=True)
class Expr(Node):
    """Raw Verilog boolean expression over monitored signals, e.g. "bvalid && !bready"."""
    sv: str


@dataclass(frozen=True)
class Past(Node):
    """Value of `sv` (1-bit expr) n cycles ago."""
    sv: str
    n: int = 1


@dataclass(frozen=True)
class Stable(Node):
    """sv == past(sv): signal (any width) unchanged since previous cycle."""
    sv: str
    width: int = 1


@dataclass(frozen=True)
class Rose(Node):
    sv: str


@dataclass(frozen=True)
class Fell(Node):
    sv: str


@dataclass(frozen=True)
class And(Node):
    parts: tuple

    def __init__(self, *parts):
        object.__setattr__(self, "parts", tuple(parts))


@dataclass(frozen=True)
class Or(Node):
    parts: tuple

    def __init__(self, *parts):
        object.__setattr__(self, "parts", tuple(parts))


@dataclass(frozen=True)
class Not(Node):
    p: Node


@dataclass(frozen=True)
class Delay(Node):
    """`p` delayed by n cycles (##n on a boolean)."""
    p: Node
    n: int


@dataclass(frozen=True)
class Implies:
    """a |-> c (overlap=True) or a |=> c (overlap=False).

    `c` may be a Node (same/next-cycle consequence) or a Within (bounded response).
    """
    a: Node
    c: object
    overlap: bool = True


@dataclass(frozen=True)
class Within:
    """Consequent-only: c must hold at some offset in [m, n] after the antecedent.

    The bounded-eventually workhorse: `a |-> ##[m:n] c`. Compiled as a pending-
    obligation shift register that handles overlapping activations correctly.
    """
    m: int
    n: int
    c: Node


@dataclass
class Prop:
    id: str
    intent: str                    # the natural-language half of the FLAG-style pairing
    formal: object                 # Implies or Node
    kind: str = "assert"           # assert (DUT obligation) | assume (environment) | cover
    provenance: str = "human"      # human | template | llm
    disable: str | None = None     # extra disable-iff expression (reset is implicit)
    note: str = ""


@dataclass
class Project:
    name: str
    dut_files: list[str]
    dut_top: str
    clock: str
    reset: str                     # active-high sync reset port ("" if none)
    signals: dict[str, int]        # monitored signal name -> width (DUT port names)
    props: list[Prop]
    kmax: int = 16
    engine: str = "btormc"         # bmc; "btormc-kind" attempts k-induction


# -- convenience constructors (the eDSL surface) ---------------------------------

def expr(sv: str) -> Expr:
    return Expr(sv)


def implies(a: Node, c, overlap: bool = True) -> Implies:
    return Implies(a, c, overlap)


def implies_next(a: Node, c) -> Implies:
    return Implies(a, c, overlap=False)


def within(m: int, n: int, c: Node) -> Within:
    return Within(m, n, c)


def stable(sv: str, width: int = 1) -> Stable:
    return Stable(sv, width)
