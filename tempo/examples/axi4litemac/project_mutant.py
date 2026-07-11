"""Run 3: same spec (obligations + signed environment assumptions) against a
buggy DUT: the write-response register drops BVALID after one cycle instead of
holding it until BREADY. Expect `b_held` to fail — and this time the trace shows
a well-behaved master, so the triage verdict is **bug in DUT**, not assumption.

The three runs together are the whole triage triangle:
  project.py          -> violation, hostile master   -> add assumption
  project_assumed.py  -> no violation                -> spec + env contract signed
  project_mutant.py   -> violation, compliant master -> DUT bug
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tempo.ast import Project
from project import OBLIGATIONS, SIGNALS, HERE
from project_assumed import ASSUMPTIONS

PROJECT = Project(
    name="axi4litemac_mutant",
    dut_files=[str(HERE / "rtl" / "Axi4LiteMac_mut.sv"), str(HERE / "rtl" / "Mac.sv")],
    dut_top="Axi4LiteMac",
    clock="clock", reset="reset",
    signals=SIGNALS,
    props=OBLIGATIONS + ASSUMPTIONS,
    kmax=14,
)
