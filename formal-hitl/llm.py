"""The single seam between this pipeline and whatever LLM is answering it.

Everything else in this codebase treats the LLM strictly as a *proposer of
hypotheses* (see README.md's three-role design principle: engine decides
truth, LLM proposes, human judges intent). This module is intentionally the
only place that knows an HTTP request is involved -- swapping providers
(Groq free tier -> a local JLSE/Ollama/vLLM endpoint -> ALCF) means editing
three env vars, not this file.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import APIStatusError, OpenAI

load_dotenv(Path(__file__).parent / ".env")

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"

MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2.0


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
            model=os.environ.get("LLM_MODEL", DEFAULT_MODEL),
            api_key=os.environ.get("LLM_API_KEY", ""),
        )


class LLMNotConfiguredError(RuntimeError):
    pass


def _client(config: LLMConfig) -> OpenAI:
    if not config.api_key:
        raise LLMNotConfiguredError(
            "LLM_API_KEY is not set. Copy formal-hitl/.env.example to "
            "formal-hitl/.env and add a free Groq key from "
            "https://console.groq.com/keys (or point LLM_BASE_URL/LLM_MODEL "
            "at another OpenAI-compatible endpoint)."
        )
    return OpenAI(base_url=config.base_url, api_key=config.api_key)


def _log_dir(run_dir: Optional[Path]) -> Optional[Path]:
    if run_dir is None:
        return None
    log_dir = run_dir / "llm"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def complete(
    system_prompt: str,
    user_prompt: str,
    *,
    run_dir: Optional[Path] = None,
    tag: str = "call",
    config: Optional[LLMConfig] = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> str:
    """Single entry point for every LLM call in the pipeline.

    Logs the exact prompt and raw completion to
    `<run_dir>/llm/<timestamp>_<tag>.json` when `run_dir` is given, so the
    whole loop stays auditable end to end.
    """
    cfg = config or LLMConfig.from_env()
    client = _client(cfg)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    backoff = INITIAL_BACKOFF_SECONDS
    last_error: Optional[Exception] = None
    raw_response = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw_response = client.chat.completions.create(
                model=cfg.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            break
        except APIStatusError as exc:
            last_error = exc
            if exc.status_code == 429 and attempt < MAX_RETRIES:
                print(
                    f"[llm] rate limited (429) on '{tag}', "
                    f"retrying in {backoff:.1f}s (attempt {attempt}/{MAX_RETRIES})"
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            raise
    else:
        assert last_error is not None
        raise last_error

    content = raw_response.choices[0].message.content or ""

    log_dir = _log_dir(run_dir)
    if log_dir is not None:
        record = {
            "tag": tag,
            "model": cfg.model,
            "base_url": cfg.base_url,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "completion": content,
            "raw_response": raw_response.model_dump(),
        }
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_path = log_dir / f"{stamp}_{tag}.json"
        # avoid clobbering same-second calls
        n = 1
        while out_path.exists():
            out_path = log_dir / f"{stamp}_{tag}_{n}.json"
            n += 1
        out_path.write_text(json.dumps(record, indent=2))

    return content
