"""Run 2: the same obligations plus the environment assumptions the first run's
triage demanded. The ledger records why each assumption exists — these ARE the
interface contract, discovered by counterexample rather than by folklore.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from experiments.tempo.tempo.ast import Project, Prop, expr, implies, within
from project import OBLIGATIONS, SIGNALS, HERE

ASSUMPTIONS = [
    Prop("m_w_follows_aw",
         intent="ENV: the master presents write data within 2 cycles of an accepted "
                "write address (discovered: without this, a master can send AW and "
                "starve W forever, so no response is ever owed)",
         formal=implies(expr("S_AXI_awvalid && S_AXI_awready"),
                        within(0, 2, expr("S_AXI_wvalid"))),
         kind="assume", provenance="human",
         note="added after write_resp_after_aw CEX: hostile master withheld W"),
    Prop("m_w_held",
         intent="ENV: the master holds WVALID (and stable payload is implied by the "
                "DUT capturing on the fire cycle) until WREADY accepts",
         formal=implies(expr("S_AXI_wvalid && !S_AXI_wready"),
                        within(1, 1, expr("S_AXI_wvalid"))),
         kind="assume", provenance="human"),
    Prop("m_b_accepted",
         intent="ENV: the master accepts a write response within 4 cycles (a stalled "
                "BREADY otherwise blocks the next transaction's response window)",
         formal=implies(expr("S_AXI_bvalid"), within(0, 4, expr("S_AXI_bready"))),
         kind="assume", provenance="human"),
]

PROJECT = Project(
    name="axi4litemac_assumed",
    dut_files=[str(HERE / "rtl" / "Axi4LiteMac.sv"), str(HERE / "rtl" / "Mac.sv")],
    dut_top="Axi4LiteMac",
    clock="clock", reset="reset",
    signals=SIGNALS,
    props=OBLIGATIONS + ASSUMPTIONS,
    kmax=14,
    engine="btormc-kind",
)
