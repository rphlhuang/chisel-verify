"""Job specification: what to diff against what."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from .fmt import FpFormat


@dataclass
class Design:
    files: list[str]
    top: str
    ports: dict[str, str]  # role -> port name; roles: a, b, out, clock, reset, valid_in, en, valid_out
    latency: int = 0
    tie: dict[str, int] = field(default_factory=dict)  # extra ports tied to constants

    def port(self, role: str) -> str | None:
        return self.ports.get(role)


@dataclass
class Job:
    name: str
    fmt: FpFormat
    gold: Design
    gate: Design
    job_dir: Path            # directory the job file lives in; file paths are relative to it
    waivers_file: str = "waivers.json"
    engine: str = "btormc"
    kmax: int | None = None  # default: max latency + 3

    @property
    def max_latency(self) -> int:
        return max(self.gold.latency, self.gate.latency)

    @property
    def effective_kmax(self) -> int:
        return self.kmax if self.kmax is not None else self.max_latency + 3

    @property
    def out_dir(self) -> Path:
        return self.job_dir / f"{self.name}.out"

    def resolve(self, p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() else self.job_dir / q


def _design(d: dict) -> Design:
    return Design(
        files=d["files"],
        top=d["top"],
        ports=d["ports"],
        latency=d.get("latency", 0),
        tie=d.get("tie", {}),
    )


def load_job(path: str | Path) -> Job:
    path = Path(path)
    with open(path) as f:
        spec = json.load(f)
    return Job(
        name=spec.get("name", path.stem),
        fmt=FpFormat(spec["format"]["exp"], spec["format"]["sig"]),
        gold=_design(spec["gold"]),
        gate=_design(spec["gate"]),
        job_dir=path.parent.resolve(),
        waivers_file=spec.get("waivers", "waivers.json"),
        engine=spec.get("engine", "btormc"),
        kmax=spec.get("kmax"),
    )
