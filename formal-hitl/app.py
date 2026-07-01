"""Local HITL frontend. Run with: uvicorn app:app --reload

This is where the human role in the three-role design actually happens:
the engine (harness.py) has already decided PROVEN/FAILED/ERROR by the time
anything reaches this file, and the LLM (llm.py, loop.py) has already
proposed everything in the property table. All this app does is present
that clearly -- especially counterexample waveforms, which are the whole
point -- and collect the human's faithfulness-to-intent judgment.
"""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import loop
from harness import PropertyResult, PropertySpec

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="formal-hitl")


class RunState:
    def __init__(self, run_id: str, variant: str, width: int):
        self.run_id = run_id
        self.variant = variant
        self.width = width
        self.run_dir = loop.RUNS_ROOT / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.stage: str = "queued"
        self.cycle: int = 0
        self.properties: dict[str, PropertySpec] = {}
        self.results: dict[str, PropertyResult] = {}
        self.adjudications: dict[str, dict] = {}
        self._assumptions: list[PropertySpec] = []
        self.error: Optional[str] = None
        self.lock = threading.Lock()

    def to_json(self) -> dict:
        with self.lock:
            return {
                "run_id": self.run_id,
                "variant": self.variant,
                "width": self.width,
                "stage": self.stage,
                "cycle": self.cycle,
                "error": self.error,
                "properties": [
                    self._property_row(name) for name in self.properties
                ],
            }

    def _property_row(self, name: str) -> dict:
        prop = self.properties[name]
        result = self.results.get(name)
        adj = self.adjudications.get(name)
        row = {
            "name": prop.name,
            "intent": prop.intent,
            "kind": prop.kind,
            "antecedent": prop.antecedent,
            "consequent": prop.consequent,
            "verdict": result.verdict if result else "PENDING",
            "adjudication": adj,
        }
        if result and result.cex:
            c = result.cex
            row["cex"] = {
                "a": c.a,
                "b": c.b,
                "observed_s": c.observed_s,
                "expected_s": c.expected_s,
                "fail_step": c.fail_step,
                "wavedrom": c.wavedrom,
            }
        else:
            row["cex"] = None
        return row


RUNS: dict[str, RunState] = {}


class StartRunRequest(BaseModel):
    variant: str
    width: int = 8


class AdjudicationIn(BaseModel):
    property_name: str
    decision: Literal["real_bug", "vacuous", "missing_assumption", "edge_case_forgot"]
    note: Optional[str] = None


class AdjudicateRequest(BaseModel):
    adjudications: list[AdjudicationIn]


def _run_cycle_worker(state: RunState, spec: str = loop.ADDER_SPEC):
    try:
        with state.lock:
            state.stage = "plan"
        intents = loop.plan(state.run_dir, spec)

        with state.lock:
            state.stage = "generate"
        properties = loop.generate(state.run_dir, intents, state.width)
        with state.lock:
            state.properties = {p.name: p for p in properties if p.kind == "assert"}
            # assumptions aren't rows in the table but are needed by execute()
            state._assumptions = [p for p in properties if p.kind == "assume"]
            state.stage = "execute"

        results = loop.execute(state.run_dir, state.variant, state.width, properties)
        with state.lock:
            state.results = {r.name: r for r in results}
            state.stage = "done"
    except Exception as exc:  # noqa: BLE001
        with state.lock:
            state.stage = "error"
            state.error = f"{exc}\n{traceback.format_exc()}"


def _refine_cycle_worker(state: RunState, adjudications: list[AdjudicationIn]):
    try:
        with state.lock:
            state.stage = "refine"
            adj_objs = [loop.Adjudication(**a.model_dump()) for a in adjudications]
            for a in adjudications:
                state.adjudications[a.property_name] = a.model_dump()
            all_properties = list(state.properties.values()) + getattr(state, "_assumptions", [])
            all_results = list(state.results.values())
            cycle = state.cycle + 1

        loop.record_adjudications(state.run_dir, adj_objs)

        if cycle > loop.MAX_REFINE_CYCLES:
            with state.lock:
                state.stage = "done"
                state.error = (
                    f"Reached MAX_REFINE_CYCLES ({loop.MAX_REFINE_CYCLES}) without full "
                    "convergence. Surfacing current state for further human review."
                )
            return

        refined = loop.refine(state.run_dir, all_properties, all_results, adj_objs, state.width)

        # refine() only returns the properties covered by this batch of
        # feedback (vacuous ones dropped, missing_assumption ones paired
        # with a new assume). Merge that back into the untouched rest of
        # the table rather than replacing it wholesale, so properties the
        # human hasn't looked at yet don't disappear from the UI.
        touched_names = {a.property_name for a in adjudications}
        refined_asserts = {p.name: p for p in refined if p.kind == "assert"}
        refined_assumes = {p.name: p for p in refined if p.kind == "assume"}

        with state.lock:
            state.stage = "execute"
            state.cycle = cycle
            for name in touched_names:
                state.properties.pop(name, None)
                state.results.pop(name, None)
            state.properties.update(refined_asserts)
            assumptions_by_name = {p.name: p for p in state._assumptions}
            assumptions_by_name.update(refined_assumes)
            state._assumptions = list(assumptions_by_name.values())
            state.adjudications = {
                k: v for k, v in state.adjudications.items() if k in state.properties
            }

        results = loop.execute(
            state.run_dir, state.variant, state.width, list(refined_asserts.values()) + state._assumptions
        )
        with state.lock:
            for r in results:
                state.results[r.name] = r
            state.stage = "done"
    except Exception as exc:  # noqa: BLE001
        with state.lock:
            state.stage = "error"
            state.error = f"{exc}\n{traceback.format_exc()}"


@app.get("/api/variants")
def list_variants():
    return {"variants": _discover_variants()}


def _discover_variants() -> list[str]:
    if not loop.GENERATED_ROOT.exists():
        return []
    return sorted(p.name for p in loop.GENERATED_ROOT.iterdir() if p.is_dir())


@app.post("/api/runs")
def start_run(req: StartRunRequest):
    dut_sv = loop.GENERATED_ROOT / req.variant / f"w{req.width}" / "AdderVariant.sv"
    if not dut_sv.exists():
        raise HTTPException(
            400,
            f"No generated SystemVerilog for variant '{req.variant}' at width "
            f"{req.width}. Run: sbt \"runMain arithmetic.AdderVariantsMain {req.width}\"",
        )
    run_id = time.strftime("%Y%m%d-%H%M%S")
    state = RunState(run_id, req.variant, req.width)
    RUNS[run_id] = state
    thread = threading.Thread(target=_run_cycle_worker, args=(state,), daemon=True)
    thread.start()
    return {"run_id": run_id}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(404, "unknown run_id")
    return state.to_json()


@app.post("/api/runs/{run_id}/adjudicate")
def adjudicate(run_id: str, req: AdjudicateRequest):
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(404, "unknown run_id")
    with state.lock:
        if state.stage not in ("done", "error"):
            raise HTTPException(409, f"run is still in stage '{state.stage}'")
    thread = threading.Thread(target=_refine_cycle_worker, args=(state, req.adjudications), daemon=True)
    thread.start()
    return {"ok": True}


@app.get("/api/runs/{run_id}/transcript")
def get_transcript(run_id: str):
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(404, "unknown run_id")
    transcript_path = state.run_dir / "transcript.jsonl"
    if not transcript_path.exists():
        return {"events": []}
    events = []
    for line in transcript_path.read_text().splitlines():
        if line.strip():
            import json

            events.append(json.loads(line))
    return {"events": events}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
