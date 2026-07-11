"""AST -> synthesizable Verilog monitor.

Every construction here is a classic of runtime/formal monitoring, implemented
from first principles (annotated below); the emitted module contains only
registers and boolean logic, so it flows through open Yosys, btor2, btormc,
Icarus, Verilator, and cocotb alike. One artifact, simulation and formal both.
"""

from .ast import (Node, Expr, Past, Stable, Rose, Fell, And, Or, Not, Delay,
                  Implies, Within, Prop, Project)


class Ctx:
    """Allocates history registers and collects emitted lines per property."""

    def __init__(self, pid: str):
        self.pid = pid
        self.decls: list[str] = []
        self.seq: list[str] = []    # statements inside always @(posedge clock)
        self.n = 0

    def fresh(self, tag: str) -> str:
        self.n += 1
        return f"{self.pid}_{tag}{self.n}"

    def past_chain(self, sv: str, n: int, width: int = 1) -> str:
        """RegNext chain: the `past()` idiom — history operators are just flops."""
        cur = f"({sv})"
        for i in range(n):
            r = self.fresh("p")
            w = f"[{width-1}:0] " if width > 1 else ""
            self.decls.append(f"  reg {w}{r};")
            self.seq.append(f"      {r} <= {cur};")
            cur = r
        return cur


def emit_bool(node: Node, ctx: Ctx) -> str:
    """Lower a boolean-valued node to a Verilog expression, allocating flops."""
    if isinstance(node, Expr):
        return f"({node.sv})"
    if isinstance(node, Past):
        return ctx.past_chain(node.sv, node.n)
    if isinstance(node, Stable):
        prev = ctx.past_chain(node.sv, 1, node.width)
        return f"(({node.sv}) == {prev})"
    if isinstance(node, Rose):
        prev = ctx.past_chain(node.sv, 1)
        return f"(({node.sv}) && !{prev})"
    if isinstance(node, Fell):
        prev = ctx.past_chain(node.sv, 1)
        return f"(!({node.sv}) && {prev})"
    if isinstance(node, And):
        return "(" + " && ".join(emit_bool(p, ctx) for p in node.parts) + ")"
    if isinstance(node, Or):
        return "(" + " || ".join(emit_bool(p, ctx) for p in node.parts) + ")"
    if isinstance(node, Not):
        return f"(!{emit_bool(node.p, ctx)})"
    if isinstance(node, Delay):
        inner = emit_bool(node.p, ctx)
        return ctx.past_chain(inner, node.n)
    raise TypeError(f"not a boolean node: {node!r}")


def compile_prop(p: Prop, dis: str) -> tuple[list[str], str, int]:
    """-> (verilog lines, ok_expr_name, warmup_cycles).

    `ok` is a wire that must hold every enabled cycle; kind decides whether the
    harness asserts it (DUT obligation) or assumes it (environment constraint) —
    assume–guarantee reasoning, mechanized.
    """
    ctx = Ctx(p.id)
    warmup = 0
    f = p.formal

    if isinstance(f, Implies) and isinstance(f.c, Within):
        # Bounded response: a |-> ##[m:n] c, with |=> shifting the window by one.
        # Pending-obligation shift register: bit i == "antecedent fired i cycles
        # ago, not yet satisfied". A response clears every in-window obligation;
        # an obligation shifting past age n unsatisfied is the violation. This is
        # the finite-automaton view of safety: the monitor accepts exactly the
        # traces with no bad prefix, and overlapping activations each get a bit
        # (where a single-counter monitor would be wrong).
        m, n = f.c.m, f.c.n
        if not f.overlap:
            m, n = m + 1, n + 1
        a = emit_bool(f.a, ctx)
        c = emit_bool(f.c.c, ctx)
        pnd = f"{p.id}_pnd"
        mask = sum(1 << i for i in range(m, n + 1))
        ctx.decls.append(f"  reg [{n}:0] {pnd};")
        ctx.decls.append(f"  wire [{n}:0] {pnd}_cur = {pnd} | {{{{{n}{{1'b0}}}}, {a}}};")
        ctx.decls.append(f"  wire [{n}:0] {pnd}_rem = {c} ? ({pnd}_cur & ~{n+1}'h{mask:x})"
                         f" : {pnd}_cur;")
        ctx.seq.append(f"      {pnd} <= {dis} ? {n+1}'h0 : ({pnd}_rem << 1);")
        ok = f"(!{pnd}_rem[{n}])"
        warmup = 1
    elif isinstance(f, Implies):
        a = emit_bool(f.a, ctx)
        c = emit_bool(f.c, ctx)
        if f.overlap:
            ok = f"(!{a} || {c})"                      # |->: same-cycle implication
        else:
            a_p = ctx.past_chain(a, 1)                 # |=>: one flop is the whole story
            ok = f"(!{a_p} || {c})"
            warmup = 1
    else:
        ok = emit_bool(f, ctx)

    warmup = max(warmup, _history_depth(f))
    okw = f"{p.id}_ok"
    lines = list(ctx.decls)
    lines.append(f"  wire {okw} = {ok};")
    if ctx.seq:
        lines.append("  always @(posedge clock) begin")
        lines += ctx.seq
        lines.append("  end")
    return lines, okw, warmup


def _history_depth(f) -> int:
    """Cycles of history the property references (monitor warm-up requirement)."""
    if isinstance(f, Implies):
        return max(_history_depth(f.a), _history_depth(f.c))
    if isinstance(f, Within):
        return _history_depth(f.c)
    if isinstance(f, (Past, Delay)):
        inner = _history_depth(f.p) if isinstance(f, Delay) else 0
        return f.n + inner
    if isinstance(f, (Stable, Rose, Fell)):
        return 1
    if isinstance(f, (And, Or)):
        return max((_history_depth(p) for p in f.parts), default=0)
    if isinstance(f, Not):
        return _history_depth(f.p)
    return 0


def compile_monitor(proj: Project) -> str:
    """One module: all properties, shared signal ports, per-property assert/assume.

    Under `ifdef TEMPO_SIM the same module reports violations with $error and the
    property's natural-language intent — the NL half of the property rides along
    into simulation."""
    ports = ["input clock", "input dis"]
    for name, width in proj.signals.items():
        w = f"[{width-1}:0] " if width > 1 else ""
        ports.append(f"input {w}{name}")

    L = ["// generated by tempo -- properties compiled to boolean safety monitors"]
    L.append("module tempo_monitor(")
    L.append("  " + ",\n  ".join(ports))
    L.append(");")
    L.append("  // warm-up: history registers hold garbage until filled; asserting")
    L.append("  // before then would report artifacts of the monitor, not the DUT.")
    L.append("  reg [15:0] tempo_t = 16'd0;")
    L.append("  always @(posedge clock) tempo_t <= tempo_t + 16'd1;")
    L.append("")

    checks = []
    for p in proj.props:
        pdis = f"(dis || ({p.disable}))" if p.disable else "dis"
        lines, okw, warmup = compile_prop(p, pdis)
        L.append(f"  // ---- [{p.kind}] {p.id} ({p.provenance})")
        L.append(f"  // intent: {p.intent}")
        L += lines
        en = f"(tempo_t >= 16'd{warmup + 1} && !{pdis})"
        checks.append((p, okw, en))
        L.append("")

    L.append("`ifdef TEMPO_FORMAL")
    for p, okw, en in checks:
        stmt = {"assert": "assert", "assume": "assume", "cover": "cover"}[p.kind]
        cond = okw if p.kind != "cover" else f"({en} && {okw})"
        if p.kind == "cover":
            L.append(f"  always @* cover({cond});")
        else:
            L.append(f"  always @* if ({en}) {stmt}({okw});")
    L.append("`endif")
    L.append("`ifdef TEMPO_SIM")
    L.append("  always @(posedge clock) begin")
    for p, okw, en in checks:
        if p.kind == "assert":
            L.append(f'    if ({en} && !{okw}) $error("TEMPO FAIL {p.id}: {p.intent}");')
        elif p.kind == "assume":
            L.append(f'    if ({en} && !{okw}) $display("TEMPO ENV-VIOLATED {p.id}");')
    L.append("  end")
    L.append("`endif")
    L.append("endmodule")
    return "\n".join(L) + "\n"
