"""AXI4-Lite slave protocol obligations for this repo's Axi4LiteMac.

Run 1 (this file): obligations only, no environment assumptions -- the solver
plays a maximally hostile master. Expect a violation of `write_resp_after_aw`:
the master sends AW and then simply never sends W, so no response ever comes.
That is not a DUT bug; it is an underconstrained environment. The triage verdict
is "add assumption" -- see project_assumed.py, which is this spec plus the
signed environment assumptions, and passes.

This is assume-guarantee reasoning experienced from the driver's seat.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tempo.ast import (Project, Prop, expr, implies, implies_next, within,
                       stable, And, Expr)

HERE = Path(__file__).parent

SIGNALS = {
    "S_AXI_awaddr": 32, "S_AXI_awvalid": 1, "S_AXI_awready": 1,
    "S_AXI_wdata": 32, "S_AXI_wstrb": 4, "S_AXI_wvalid": 1, "S_AXI_wready": 1,
    "S_AXI_bresp": 2, "S_AXI_bvalid": 1, "S_AXI_bready": 1,
    "S_AXI_araddr": 32, "S_AXI_arvalid": 1, "S_AXI_arready": 1,
    "S_AXI_rdata": 32, "S_AXI_rresp": 2, "S_AXI_rvalid": 1, "S_AXI_rready": 1,
}

OBLIGATIONS = [
    Prop("b_held",
         intent="Once BVALID asserts it stays asserted until BREADY accepts it "
                "(AXI4-Lite: response may not be withdrawn)",
         formal=implies_next(expr("S_AXI_bvalid && !S_AXI_bready"),
                             expr("S_AXI_bvalid"))),
    Prop("b_stable",
         intent="BRESP is stable while BVALID waits for BREADY",
         formal=implies_next(expr("S_AXI_bvalid && !S_AXI_bready"),
                             stable("S_AXI_bresp", 2))),
    Prop("r_held",
         intent="Once RVALID asserts it stays asserted until RREADY accepts it",
         formal=implies_next(expr("S_AXI_rvalid && !S_AXI_rready"),
                             expr("S_AXI_rvalid"))),
    Prop("r_stable",
         intent="RDATA and RRESP are stable while RVALID waits for RREADY",
         formal=implies_next(expr("S_AXI_rvalid && !S_AXI_rready"),
                             And(stable("S_AXI_rdata", 32),
                                 stable("S_AXI_rresp", 2)))),
    Prop("read_resp_bounded",
         intent="Every accepted read address gets RVALID within 4 cycles",
         formal=implies(expr("S_AXI_arvalid && S_AXI_arready"),
                        within(1, 4, expr("S_AXI_rvalid")))),
    Prop("write_resp_after_aw",
         intent="Every accepted write address gets BVALID within 8 cycles",
         formal=implies(expr("S_AXI_awvalid && S_AXI_awready"),
                        within(1, 8, expr("S_AXI_bvalid")))),
]

PROJECT = Project(
    name="axi4litemac",
    dut_files=[str(HERE / "rtl" / "Axi4LiteMac.sv"), str(HERE / "rtl" / "Mac.sv")],
    dut_top="Axi4LiteMac",
    clock="clock", reset="reset",
    signals=SIGNALS,
    props=OBLIGATIONS,
    kmax=14,
)
