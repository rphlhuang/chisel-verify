"""The HITL verification loop, staged to mirror the papers this reimplements
(plan / generate / execute / present / adjudicate / refine). See
README.md for the three-role design principle these stages exist to
protect: the formal engine (harness.py) is the only stage allowed to decide
truth; the LLM (llm.py) only ever proposes; the human only ever adjudicates
faithfulness-to-intent.

No agent framework here on purpose -- these are plain functions so the
mapping back to the papers' stage names stays legible.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError

import llm
from harness import PropertyResult, PropertySpec, run_property

REPO_ROOT = Path(__file__).parent.parent
GENERATED_ROOT = Path(__file__).parent / "generated"
RUNS_ROOT = Path(__file__).parent / "runs"

MAX_REFINE_CYCLES = 3

ADDER_SPEC = (
    "An N-bit unsigned adder. Inputs `a` and `b` are WIDTH-bit unsigned "
    "values. Output `s` is (WIDTH+1) bits so a carry out of the top bit is "
    "never lost. `s` must equal the true arithmetic sum of `a` and `b` for "
    "every possible input, every cycle."
)

DUT_INTERFACE_NOTE = (
    "The formal testbench exposes exactly these signals to write properties "
    "over: `a` (WIDTH-bit input), `b` (WIDTH-bit input), `s` ((WIDTH+1)-bit "
    "output), and the localparam `WIDTH`. Do not reference clock or reset; "
    "the harness handles those. Properties are checked every cycle after an "
    "initial one-cycle reset."
)


class Intent(BaseModel):
    name: str
    description: str


def _new_run_dir() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_ROOT / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _repair_mismatched_brackets(text: str) -> str:
    """Groq's llama-3.3-70b has a recurring habit of closing a JSON array
    one brace early, e.g. `..."foo"]\\n]` instead of `..."foo"}]\\n]`. Walk
    the text tracking the bracket stack (skipping string contents) and
    splice in the missing closer wherever a close bracket doesn't match the
    open one on top of the stack."""
    out = []
    stack: list[str] = []
    pairs = {"{": "}", "[": "]"}
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
        elif ch in pairs:
            stack.append(ch)
            out.append(ch)
        elif ch in ("}", "]"):
            if stack and pairs[stack[-1]] != ch:
                # Wrong closer for the innermost opener: synthesize the
                # correct one first, then let this char close its parent.
                out.append(pairs[stack.pop()])
            if stack and pairs[stack[-1]] == ch:
                stack.pop()
                out.append(ch)
            # else: a stray closer with nothing left on the stack to close
            # (e.g. a duplicated trailing ']') -- drop it rather than
            # emitting unbalanced output.
        else:
            out.append(ch)
    return "".join(out)


def _extract_json(text: str):
    """LLMs love to wrap JSON in prose or markdown fences. Pull out the
    first top-level JSON array or object we can find, repairing common
    small bracket mistakes along the way."""
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fence.group(1) if fence else text
    candidate = candidate.strip()

    attempts = [candidate]
    for open_ch, close_ch in [("[", "]"), ("{", "}")]:
        start = candidate.find(open_ch)
        end = candidate.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            attempts.append(candidate[start : end + 1])

    for attempt in list(attempts):
        attempts.append(_repair_mismatched_brackets(attempt))

    for attempt in attempts:
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"Could not parse JSON from LLM output: {text[:300]!r}")


def _complete_json(system: str, user: str, run_dir: Path, tag: str, retries: int = 2):
    """LLM completions occasionally come back as malformed or truncated
    JSON. This is a generation error, not a formal-engine verdict, so it's
    handled here with a bounded retry-with-correction loop rather than
    surfacing a crash to the human."""
    last_error: Optional[Exception] = None
    prompt = user
    for attempt in range(retries + 1):
        completion = llm.complete(system, prompt, run_dir=run_dir, tag=f"{tag}_{attempt}")
        try:
            return _extract_json(completion)
        except ValueError as exc:
            last_error = exc
            prompt = (
                user
                + f"\n\nYour previous response could not be parsed as JSON "
                f"({exc}). Return ONLY a single valid, complete JSON value -- "
                "no markdown fences, no trailing commentary, no truncation."
            )
    raise ValueError(f"LLM did not return valid JSON for '{tag}' after {retries + 1} attempts") from last_error


def _append_transcript(run_dir: Path, event: dict):
    event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
    with open(run_dir / "transcript.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")


# --------------------------------------------------------------------------
# Stage 1: Plan
# --------------------------------------------------------------------------


def plan(run_dir: Path, spec: str = ADDER_SPEC) -> list[Intent]:
    """NL spec -> a small vPlan: a list of property intents in plain
    language. This is the LLM's first and broadest hypothesis-generation
    pass; nothing here is checked yet."""
    system = (
        "You are a hardware verification assistant helping plan a formal "
        "verification effort for a small RTL block. You propose CANDIDATE "
        "property intents in plain English. You do not write SVA yet, and "
        "you are not the judge of correctness -- a formal engine will "
        "decide that later. Propose intents that are meaningful, varied, "
        "and non-redundant: correctness, structural/width properties, and "
        "at least one property that might catch a subtle bug a human might "
        "not think to check."
    )
    user = (
        f"Design under test:\n{spec}\n\n"
        "Return a JSON array of 3 to 6 objects, each with a short snake_case "
        "\"name\" and a one-sentence plain-English \"description\" of the "
        "property intent. Return ONLY the JSON array, no prose."
    )
    raw = _complete_json(system, user, run_dir, "plan")
    intents = [Intent(**item) for item in raw]
    _append_transcript(run_dir, {"stage": "plan", "intents": [i.model_dump() for i in intents]})
    return intents


# --------------------------------------------------------------------------
# Stage 2: Generate
# --------------------------------------------------------------------------


def generate(run_dir: Path, intents: list[Intent], width: int) -> list[PropertySpec]:
    """Each intent -> an SVA body (as a structured PropertySpec), referencing
    the DUT's real port names. Constrained to the boolean/implication subset
    Yosys's open-source frontend can actually elaborate."""
    system = (
        "You translate plain-English property intents into SystemVerilog "
        "Assertion bodies for an open-source Yosys/SymbiYosys BMC flow, "
        "which only supports a SIMPLE subset of SVA: a boolean expression, "
        "optionally guarded by an antecedent (if antecedent then check "
        "consequent). No sequence operators, no $past unless trivial, no "
        "multi-clause sequences. Implication (\"if X then Y\") MUST be "
        "expressed using the separate antecedent/consequent fields, never "
        "with -> or |-> inside a single expression string -- plain Verilog "
        "expressions do not support those operators.\n\n" + DUT_INTERFACE_NOTE
    )
    user = (
        "Property intents:\n"
        + json.dumps([i.model_dump() for i in intents], indent=2)
        + "\n\nReturn a JSON array with one object per intent, each with: "
        '"name" (snake_case, matching the intent name), "intent" (copy of '
        'the description), "kind" (always "assert" for these), '
        '"antecedent" (a boolean SV expression string, or null if '
        'unconditional), and "consequent" (a boolean SV expression string '
        "using only a, b, s, WIDTH). Return ONLY the JSON array."
    )
    raw = _complete_json(system, user, run_dir, "generate")
    properties = [PropertySpec(**item) for item in raw]
    _append_transcript(
        run_dir, {"stage": "generate", "properties": [p.model_dump() for p in properties]}
    )
    return properties


# --------------------------------------------------------------------------
# Stage 3: Execute
# --------------------------------------------------------------------------


def execute(
    run_dir: Path, variant: str, width: int, properties: list[PropertySpec]
) -> list[PropertyResult]:
    """Runs the formal harness (the sound arbiter) on every asserted
    property, holding all assume-kind properties as global assumptions."""
    dut_sv = GENERATED_ROOT / variant / f"w{width}" / "AdderVariant.sv"
    if not dut_sv.exists():
        raise FileNotFoundError(
            f"No generated SystemVerilog for variant '{variant}' at width {width} "
            f"(expected {dut_sv}). Run: sbt \"runMain arithmetic.AdderVariantsMain {width}\""
        )

    assumptions = [p for p in properties if p.kind == "assume"]
    asserts = [p for p in properties if p.kind == "assert"]

    results = []
    for target in asserts:
        result = run_property(run_dir, width, dut_sv, assumptions, target)
        results.append(result)
        _append_transcript(
            run_dir,
            {
                "stage": "execute",
                "variant": variant,
                "width": width,
                "property": target.model_dump(),
                "verdict": result.verdict,
                "cex": result.cex.__dict__ if result.cex else None,
            },
        )

    # SEAM: coverage -- per-property coverage (paper Table II) would be
    # collected here, right after each property's execute() call, by
    # inspecting the BMC engine's cell/line coverage for the DUT.
    # SEAM: vacuity-rank -- before results are handed to the human, a
    # vacuity check (does the property's antecedent/assumptions ever hold?)
    # and an information-theoretic ranking of surviving properties would
    # run here, so the human sees the most informative results first.

    return results


# --------------------------------------------------------------------------
# Stage 5 (human happens in app.py): persist adjudications
# --------------------------------------------------------------------------

Decision = Literal["real_bug", "vacuous", "missing_assumption", "edge_case_forgot"]


class Adjudication(BaseModel):
    property_name: str
    decision: Decision
    note: Optional[str] = None


def record_adjudications(run_dir: Path, adjudications: list[Adjudication]):
    for adj in adjudications:
        _append_transcript(run_dir, {"stage": "adjudicate", **adj.model_dump()})


# --------------------------------------------------------------------------
# Stage 6: Refine
# --------------------------------------------------------------------------


def refine(
    run_dir: Path,
    properties: list[PropertySpec],
    results: list[PropertyResult],
    adjudications: list[Adjudication],
    width: int,
) -> list[PropertySpec]:
    """Feeds human decisions + concrete CEXs back to the LLM to
    regenerate/repair the relevant properties. This is the explicit version
    of the paper's "convergence not reached -> HITL" step: the human's
    adjudication IS the signal that tells the LLM what to fix, and if this
    doesn't converge within MAX_REFINE_CYCLES the loop stops and surfaces
    state rather than looping forever.
    """
    results_by_name = {r.name: r for r in results}
    props_by_name = {p.name: p for p in properties}

    feedback_items = []
    for adj in adjudications:
        result = results_by_name.get(adj.property_name)
        prop = props_by_name.get(adj.property_name)
        if not prop:
            continue
        feedback_items.append(
            {
                "property": prop.model_dump(),
                "verdict": result.verdict if result else None,
                "cex": result.cex.__dict__ if result and result.cex else None,
                "human_decision": adj.decision,
                "human_note": adj.note,
            }
        )

    system = (
        "You repair or refine SystemVerilog Assertion properties for an "
        "open-source Yosys/SymbiYosys BMC flow (same simple boolean/"
        "implication subset as before) based on human adjudication of prior "
        "results. Human decisions mean:\n"
        "- real_bug: the failure is a genuine RTL defect; keep the property "
        "as-is (it is doing its job).\n"
        "- vacuous: the property is meaningless; DROP it (omit from output).\n"
        "- missing_assumption: the failure is a false positive caused by an "
        "unconstrained input; ADD an \"assume\"-kind PropertySpec that "
        "constrains the input space, and keep the original assert.\n"
        "- edge_case_forgot: a legitimate property the human hadn't thought "
        "of; keep it as-is.\n\n" + DUT_INTERFACE_NOTE
    )
    user = (
        "Adjudicated results:\n"
        + json.dumps(feedback_items, indent=2)
        + "\n\nReturn a JSON array of the FULL updated property set (only "
        "the properties covered by this feedback; vacuous ones omitted, "
        "missing_assumption ones paired with a new assume). Same object "
        "shape as before: name, intent, kind, antecedent, consequent. "
        "Return ONLY the JSON array."
    )
    raw = _complete_json(system, user, run_dir, "refine")
    refined = [PropertySpec(**item) for item in raw]

    _append_transcript(
        run_dir,
        {
            "stage": "refine",
            "input_feedback": feedback_items,
            "refined_properties": [p.model_dump() for p in refined],
        },
    )
    return refined


# --------------------------------------------------------------------------
# End to end (used by app.py and for CLI smoke-testing)
# --------------------------------------------------------------------------


def run_cycle(
    run_dir: Path, variant: str, width: int, spec: str = ADDER_SPEC
) -> tuple[list[PropertySpec], list[PropertyResult]]:
    intents = plan(run_dir, spec)
    properties = generate(run_dir, intents, width)
    results = execute(run_dir, variant, width, properties)
    return properties, results


if __name__ == "__main__":
    import sys

    variant = sys.argv[1] if len(sys.argv) > 1 else "Golden"
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    run_dir = _new_run_dir()
    print(f"run_dir: {run_dir}")
    properties, results = run_cycle(run_dir, variant, width)
    for r in results:
        print(f"{r.name}: {r.verdict}")
        if r.cex:
            print(f"  a={r.cex.a} b={r.cex.b} observed_s={r.cex.observed_s} expected_s={r.cex.expected_s}")
