"""Locate open EDA tools. Everything here is downloadable for free:
yosys (or oss-cad-suite), btormc + iverilog (oss-cad-suite)."""

import os
import shutil

_EXTRA_DIRS = [
    os.environ.get("FPDIFF_TOOLS", ""),
    os.path.expanduser("~/Documents/utils/oss-cad-suite/bin"),
]


def tool(name: str) -> str:
    p = shutil.which(name)
    if p:
        return p
    for d in _EXTRA_DIRS:
        if d:
            cand = os.path.join(d, name)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    raise FileNotFoundError(
        f"required tool '{name}' not found on PATH; install oss-cad-suite "
        f"and/or set FPDIFF_TOOLS=<dir containing it>")
