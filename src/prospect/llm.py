"""The agent's brain: Claude Code in headless mode (`claude -p`), one task per call, JSON-schema answer.

Runs on whoever launches it: a logged-in Claude Code (subscription) or ANTHROPIC_API_KEY.
"""

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from prospect.config import CALL_TIMEOUT_S, RETRY_PAUSES_S, STEPS

T = TypeVar("T", bound=BaseModel)

SYSTEM = """You are a research assistant preparing outreach for a B2B sales rep.
- Use only public information. Never open linkedin.com pages with WebFetch: use what search results show about them.
- Every fact you return must carry the URL of the public page it came from, and the page date if the page shows one.
- If you cannot find or confirm something, say so (empty list, null or "not found"). Never guess a person, title or fact.
- Answer only in the requested JSON format."""

# LinkedIn forbids bots; the system prompt asks, these rules enforce.
BLOCKED_FETCH = ["WebFetch(domain:linkedin.com)", "WebFetch(domain:*.linkedin.com)"]  # covers de., uk., www. etc.

INSTALL_HELP = """Claude Code is required to run this agent.
Install: https://docs.claude.com/en/docs/claude-code/setup , then either run `claude` once and log in
with a Claude account, or set ANTHROPIC_API_KEY (calls are then billed to that key)."""


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    data: BaseModel
    cost_usd: float
    duration_s: float
    cached: bool
    searches: int = 0


class Runner(Protocol):
    def __call__(self, prompt: str, schema: type[T], *, step: str) -> LLMResult: ...


def _argv(prompt: str, schema: type[BaseModel], step: str) -> list[str]:
    cfg = STEPS[step]
    argv = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--json-schema", json.dumps(schema.model_json_schema()),
        "--model", cfg.model,
        "--system-prompt", SYSTEM,
        "--setting-sources", "project",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--max-turns", str(cfg.max_turns),
        "--tools", ",".join(cfg.tools),
    ]  # fmt: skip
    if cfg.tools:
        argv += ["--allowedTools", *cfg.tools, "--disallowedTools", *BLOCKED_FETCH]
    if os.environ.get("ANTHROPIC_API_KEY"):
        argv.append("--bare")
    return argv


def _searches(envelope: dict) -> int:
    return sum(m.get("webSearchRequests", 0) for m in (envelope.get("modelUsage") or {}).values())


class ClaudeRunner:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir / "llm"
        self.total_cost_usd = 0.0
        self.total_duration_s = 0.0
        self.total_searches = 0
        self._lock = threading.Lock()  # companies may run in parallel threads

    def __call__(self, prompt: str, schema: type[T], *, step: str) -> LLMResult:
        argv = _argv(prompt, schema, step)
        key = hashlib.sha256(json.dumps([a for a in argv if a != "--bare"]).encode()).hexdigest()
        cached = self.cache_dir / f"{key}.json"
        if cached.exists():
            env = json.loads(cached.read_text())
            return LLMResult(schema.model_validate(env["structured_output"]), 0.0, 0.0, True)

        env = self._call(argv, schema)
        data = schema.model_validate(env["structured_output"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(env))
        res = LLMResult(data, env.get("total_cost_usd", 0.0), env.get("duration_ms", 0) / 1000, False, _searches(env))
        with self._lock:
            self.total_cost_usd += res.cost_usd
            self.total_duration_s += res.duration_s
            self.total_searches += res.searches
        return res

    def _call(self, argv: list[str], schema: type[BaseModel]) -> dict:
        error = ""
        for attempt, pause in enumerate((*RETRY_PAUSES_S, None)):
            try:
                p = subprocess.run(
                    argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=CALL_TIMEOUT_S
                )
                env = json.loads(p.stdout)
                if p.returncode == 0 and not env.get("is_error") and env.get("subtype") == "success":
                    schema.model_validate(env.get("structured_output"))
                    return env
                error = f"{env.get('subtype')}: {str(env.get('result'))[:300]}"
            except (subprocess.TimeoutExpired, json.JSONDecodeError, ValidationError) as e:
                error = f"{type(e).__name__}: {str(e)[:300]}"
            if pause is not None:
                time.sleep(pause)
        raise LLMError(f"claude -p failed after {attempt + 1} attempts: {error}")


def preflight() -> None:
    """Fail once, clearly, before the run if Claude Code cannot answer."""
    if not shutil.which("claude"):
        raise SystemExit(INSTALL_HELP)
    argv = ["claude", "-p", "Reply with OK.", "--output-format", "json", "--model", "haiku",
            "--setting-sources", "project", "--strict-mcp-config", "--no-session-persistence", "--tools", ""]  # fmt: skip
    if os.environ.get("ANTHROPIC_API_KEY"):
        argv.append("--bare")
    try:
        p = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        env = json.loads(p.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        raise SystemExit(f"Claude Code did not answer.\n\n{INSTALL_HELP}")
    if env.get("is_error"):
        raise SystemExit(f"Claude Code returned an error: {env.get('result')}\n\n{INSTALL_HELP}")
