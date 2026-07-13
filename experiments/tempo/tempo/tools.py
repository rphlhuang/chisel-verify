"""Open-tool lookup (same contract as fpdiff/fpdiff/tools.py)."""

import os
import shutil

_EXTRA_DIRS = [
    os.environ.get("TEMPO_TOOLS", ""),
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
        f"required tool '{name}' not found; install oss-cad-suite and/or set "
        f"TEMPO_TOOLS=<dir containing it>")
