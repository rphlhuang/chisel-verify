"""btormc driver + btor2 witness parsing (shared design with fpdiff/engines.py).

BMC ("no violation up to k") is not a proof; `--kind` asks btormc for
k-induction, which — when it converges — is an unbounded proof. tempo surfaces
the difference in its verdicts on purpose: knowing which one you have is the
formal-methods lesson.
"""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .tools import tool


@dataclass
class EngineResult:
    status: str                    # "safe" | "cex"
    frames: list[dict[str, str]]
    elapsed: float
    raw: str = ""


def _parse_witness(text: str) -> list[dict[str, str]]:
    frames, cur, in_states = [], None, False
    for line in text.splitlines():
        line = line.strip()
        if not line or line in ("sat", "unsat") or line.startswith("b"):
            continue
        if line == ".":
            break
        if line.startswith("#"):
            in_states = True
            continue
        if line.startswith("@"):
            in_states = False
            frames.append({})
            cur = frames[-1]
            continue
        if in_states or cur is None:
            continue
        parts = line.split()
        if len(parts) >= 3:
            name = parts[2].split("@")[0]
            if name.startswith("in_"):
                name = name[3:]
            cur[name] = parts[1]
    return frames


def run_btormc(btor: Path, kmax: int, kind: bool = False,
               timeout: int = 600) -> EngineResult:
    cmd = [tool("btormc"), "--kmax", str(kmax)]
    if kind:
        cmd.append("--kind")
    t0 = time.monotonic()
    r = subprocess.run(cmd + [str(btor)], capture_output=True, text=True,
                       timeout=timeout)
    elapsed = time.monotonic() - t0
    if "sat" in r.stdout.splitlines()[0:2]:
        return EngineResult("cex", _parse_witness(r.stdout), elapsed, r.stdout)
    return EngineResult("safe", [], elapsed, r.stdout)


def frame_input(frames: list[dict[str, str]], t: int, name: str) -> int:
    val = 0
    for i in range(min(t, len(frames) - 1) + 1):
        if name in frames[i]:
            val = int(frames[i][name], 2)
    return val
