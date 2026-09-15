import pytest
from pydantic import BaseModel

from p1.llm.gateway import LLMResponse
from p1.llm.structured import StructuredOutputError, generate_structured


class ExampleSchema(BaseModel):
    name: str
    count: int


class FakeGateway:
    """Stand-in for LLMGateway: returns canned responses in order."""

    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        text = self._texts.pop(0)
        return LLMResponse(
            text=text, provider="anthropic", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


def test_retries_on_invalid_then_succeeds():
    gateway = FakeGateway([
        "not json at all",
        '{"name": "x"}',
        '{"name": "x", "count": 3}',
    ])

    result = generate_structured(gateway, "describe x", ExampleSchema, max_attempts=3)

    assert result == ExampleSchema(name="x", count=3)
    assert gateway.calls == 3


def test_raises_after_exhausting_attempts_never_defaults():
    gateway = FakeGateway(["still not json", "{}"])

    with pytest.raises(StructuredOutputError):
        generate_structured(gateway, "describe x", ExampleSchema, max_attempts=2)

    assert gateway.calls == 2
