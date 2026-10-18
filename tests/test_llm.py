import json
import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel

from prospect import llm
from prospect.llm import ClaudeRunner, LLMError, preflight

ENVELOPE = (Path(__file__).parent / "fixtures" / "claude_envelope.json").read_text()


class DomainOnly(BaseModel):
    domain: str


class Calls(list):
    """argv of every subprocess.run call; `outputs` is what the fake CLI prints (last one repeats)."""

    outputs: list[str]


@pytest.fixture
def fake_cli(monkeypatch):
    calls = Calls()
    calls.outputs = [ENVELOPE]

    def run(argv, **kwargs):
        calls.append(argv)
        out = calls.outputs[min(len(calls), len(calls.outputs)) - 1]
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    monkeypatch.setattr(llm.subprocess, "run", run)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return calls


def test_parses_structured_output(fake_cli, tmp_path):
    r = ClaudeRunner(tmp_path)("q", DomainOnly, step="company")
    assert r.data.domain == "concentrix.com" and r.cost_usd > 0 and not r.cached


def test_second_identical_call_is_cached(fake_cli, tmp_path):
    run = ClaudeRunner(tmp_path)
    run("q", DomainOnly, step="company")
    r = run("q", DomainOnly, step="company")
    assert r.cached and r.cost_usd == 0 and len(fake_cli) == 1


def test_is_error_raises_after_retries(fake_cli, tmp_path):
    bad = json.loads(ENVELOPE) | {"is_error": True, "subtype": "error_during_execution"}
    fake_cli.outputs[0] = json.dumps(bad)
    with pytest.raises(LLMError):
        ClaudeRunner(tmp_path)("q", DomainOnly, step="company")
    assert len(fake_cli) == 3


def test_command_flags(fake_cli, tmp_path, monkeypatch):
    ClaudeRunner(tmp_path)("q", DomainOnly, step="company")
    argv = fake_cli[0]
    assert "--json-schema" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--setting-sources") + 1] == "project"
    i = argv.index("--allowedTools")
    assert argv[i + 1 : i + 3] == ["WebSearch", "WebFetch"]
    assert "--bare" not in argv

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    ClaudeRunner(tmp_path)("other prompt", DomainOnly, step="company")
    assert "--bare" in fake_cli[1]


def test_cost_and_duration_accumulate(fake_cli, tmp_path):
    run = ClaudeRunner(tmp_path)
    run("a", DomainOnly, step="company")
    run("b", DomainOnly, step="company")
    assert run.total_cost_usd == pytest.approx(2 * json.loads(ENVELOPE)["total_cost_usd"])


def test_preflight_missing_binary(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit) as e:
        preflight()
    assert "Claude Code" in str(e.value) and "ANTHROPIC_API_KEY" in str(e.value)


@pytest.mark.live
def test_live_call(tmp_path):
    r = ClaudeRunner(tmp_path)("Return the primary web domain of Concentrix.", DomainOnly, step="judge")
    assert "concentrix" in r.data.domain


def test_linkedin_fetch_blocked_on_every_subdomain(fake_cli, tmp_path):
    ClaudeRunner(tmp_path)("q", DomainOnly, step="company")
    argv = fake_cli[0]
    blocked = argv[argv.index("--disallowedTools") + 1 :]
    assert "WebFetch(domain:linkedin.com)" in blocked and "WebFetch(domain:*.linkedin.com)" in blocked
