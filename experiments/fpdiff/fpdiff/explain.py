"""Optional LLM assist. The LLM never adjudicates — it drafts prose for a human.

With ANTHROPIC_API_KEY set, `explain` asks a Claude model to narrate a finding;
without it, it prints the prompt so the user can paste it anywhere (or skip it).
"""

import json
import os
import urllib.request

from .fmt import FpFormat
from .report import describe_finding
from .runner import Finding

MODEL = os.environ.get("FPDIFF_LLM_MODEL", "claude-sonnet-5")


def build_prompt(f: Finding, fmt: FpFormat, op_name: str) -> str:
    return f"""You are helping a hardware engineer triage a formally-discovered divergence
between two floating-point {op_name} implementations (format: exp={fmt.exp}, sig={fmt.sig}).
'gold' is the reference (berkeley-hardfloat, round-to-nearest-even). 'gate' is the design
under audit. The counterexample below was found by a model checker on a miter and
confirmed by independent simulation.

{describe_finding(f, fmt)}

In at most 5 sentences: (1) characterize the input corner in IEEE-754 terms,
(2) hypothesize the likely microarchitectural cause of the difference,
(3) say whether this looks like a bug or a legitimate documented-deviation candidate
(e.g. flush-to-zero, NaN payload policy, truncation rounding). Do not hedge with
boilerplate; commit to the most likely reading."""


def explain(f: Finding, fmt: FpFormat, op_name: str = "operation") -> str:
    prompt = build_prompt(f, fmt, op_name)
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return ("[no ANTHROPIC_API_KEY — showing the prompt instead]\n\n" + prompt)
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return "".join(part.get("text", "") for part in data.get("content", []))
