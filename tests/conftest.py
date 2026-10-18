from pathlib import Path

import pytest
from pydantic import BaseModel

from prospect.llm import LLMResult
from prospect.seller import load_seller

ROOT = Path(__file__).resolve().parent.parent


class FakeRunner:
    """Stands in for ClaudeRunner: hands out queued answers per step, records prompts.

    An Exception in the queue is raised instead of returned. The last queued answer repeats.
    """

    def __init__(self, responses: dict[str, list[BaseModel | Exception]]):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.prompts: dict[str, list[str]] = {}

    def __call__(self, prompt: str, schema, *, step: str) -> LLMResult:
        self.prompts.setdefault(step, []).append(prompt)
        queue = self.responses[step]
        answer = queue.pop(0) if len(queue) > 1 else queue[0]  # the last answer repeats
        if isinstance(answer, Exception):
            raise answer
        return LLMResult(schema.model_validate(answer.model_dump()), 0.0, 0.0, False)


class ScriptedDecider:
    """Answers questions from a list, in order; records what was asked."""

    def __init__(self, answers: list[str | None]):
        self.answers = list(answers)
        self.questions: list[str] = []

    def decide(self, question: str, options: list[str]) -> str | None:
        self.questions.append(question)
        return self.answers.pop(0)


@pytest.fixture
def seller():
    return load_seller(ROOT / "seller.yaml")
