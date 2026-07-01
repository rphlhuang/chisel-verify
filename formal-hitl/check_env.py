#!/usr/bin/env python3
"""Checks that the tools this pipeline needs are present.

Run this before anything else. It never raises; it always prints a report
and exits 0 (all good) or 1 (something missing), so it's safe to wire into
CI or a pre-flight UI check.
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys

OK = "\033[32mOK\033[0m"
MISSING = "\033[31mMISSING\033[0m"

REQUIRED_PY_PACKAGES = [
    "openai",
    "fastapi",
    "uvicorn",
    "vcdvcd",
    "dotenv",  # python-dotenv's import name
    "pydantic",
]

SOLVER_BINARIES = ["bitwuzla", "boolector", "yices-smt2", "z3"]


def check_binary(name: str) -> bool:
    return shutil.which(name) is not None


def check_sby() -> tuple[bool, str]:
    path = shutil.which("sby")
    if path is None:
        return False, "not found on PATH"
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
        version = (out.stdout or out.stderr).strip()
        return True, version
    except Exception as exc:  # noqa: BLE001 - report, don't crash
        return False, f"found at {path} but failed to run: {exc}"


def check_python_package(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def main() -> int:
    print("formal-hitl environment check")
    print("=" * 40)

    all_ok = True

    print("\n[Yosys / SymbiYosys]")
    yosys_ok = check_binary("yosys")
    print(f"  yosys: {OK if yosys_ok else MISSING}")
    all_ok &= yosys_ok

    sby_ok, sby_info = check_sby()
    print(f"  sby:   {OK if sby_ok else MISSING}  ({sby_info})")
    all_ok &= sby_ok

    print("\n[SMT solvers] (need at least one)")
    solver_hits = {name: check_binary(name) for name in SOLVER_BINARIES}
    for name, present in solver_hits.items():
        print(f"  {name}: {OK if present else MISSING}")
    any_solver = any(solver_hits.values())
    if not any_solver:
        print("  -> no supported solver found")
    all_ok &= any_solver

    print("\n[Python packages]")
    pkg_hits = {name: check_python_package(name) for name in REQUIRED_PY_PACKAGES}
    for name, present in pkg_hits.items():
        print(f"  {name}: {OK if present else MISSING}")
    all_ok &= all(pkg_hits.values())

    print("\n" + "=" * 40)
    if all_ok:
        print("All checks passed.")
        return 0

    print("Some checks failed. To fix:\n")
    if not (yosys_ok and sby_ok and any_solver):
        print(
            "  Install the oss-cad-suite bundle (Yosys + SymbiYosys + solvers):\n"
            "    https://github.com/YosysHQ/oss-cad-suite-build/releases\n"
            "  After extracting, add its bin/ to PATH, e.g.:\n"
            "    source /path/to/oss-cad-suite/environment\n"
            "  On macOS, if 'sby' fails with a dyld/library-load error, the\n"
            "  bundle's own Python was quarantined by Gatekeeper. Clear it with:\n"
            "    xattr -dr com.apple.quarantine /path/to/oss-cad-suite\n"
        )
    if not all(pkg_hits.values()):
        print(
            "  Create a venv and install Python deps:\n"
            "    cd formal-hitl && python3 -m venv .venv\n"
            "    source .venv/bin/activate\n"
            "    pip install -r requirements.txt\n"
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
