"""Model-checker drivers + btor2 witness parsing.

btormc only for now; the interface is deliberately trivial to extend
(rIC3 / pono / avy all consume the same miter.btor).
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .tools import tool


@dataclass
class EngineResult:
    status: str                     # "safe" (no bad state up to kmax) | "cex"
    frames: list[dict[str, str]]    # per-frame input assignments: symbol -> bitstring
    kmax: int
    elapsed: float
    raw: str = ""


def _parse_witness(text: str) -> list[dict[str, str]]:
    """Parse a btor2 witness: `@t` frames of `<id> <bits> <symbol>@t` lines.

    `#t` (state init) sections are skipped; only inputs matter for replay."""
    frames: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    in_states = False
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
            _, bits, sym = parts[0], parts[1], parts[2]
            name = sym.split("@")[0]
            if name.startswith("in_"):
                name = name[3:]
            cur[name] = bits
    return frames


def run_btormc(btor: Path, kmax: int, timeout: int = 600) -> EngineResult:
    import time
    t0 = time.monotonic()
    r = subprocess.run([tool("btormc"), "--kmax", str(kmax), str(btor)],
                       capture_output=True, text=True, timeout=timeout)
    elapsed = time.monotonic() - t0
    out = r.stdout
    if "sat" in out.splitlines()[0:2]:
        return EngineResult("cex", _parse_witness(out), kmax, elapsed, out)
    return EngineResult("safe", [], kmax, elapsed, out)


def frame_input(frames: list[dict[str, str]], t: int, name: str) -> int:
    """Input value at frame t, carrying the last assignment forward (btor witnesses
    may omit unchanged inputs) and defaulting to 0."""
    val = 0
    for i in range(min(t, len(frames) - 1) + 1):
        if name in frames[i]:
            val = int(frames[i][name], 2)
    return val
