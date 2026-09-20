"""
Proves LLMGateway._call_ollama actually gives Ollama the JSON schema
generate_structured() needs -- CHN-27 found that tools/tool_choice were
previously silently dropped for the ollama provider (not even accepted
as parameters), so a real Ollama call for ANY structured-output request
(every real capability in this codebase) would never have been told
what schema to produce, and would have reliably failed
generate_structured()'s json.loads() parse. Every test here mocks
httpx.Client so no real Ollama server is ever required -- see
test_teams_reader_graph.py / test_teams_publisher_power_automate.py for
the same httpx.MockTransport posture used elsewhere in this repo.
"""

from __future__ import annotations

import json

import httpx

from p1.llm.gateway import LLMGateway


def _gateway(tmp_path, handler) -> LLMGateway:
    gateway = LLMGateway(
        provider="ollama",
        cache_dir=tmp_path / "cache",
        call_log_path=tmp_path / "calls.jsonl",
    )

    def fake_client(*args, **kwargs):
        return httpx.Client(base_url=kwargs.get("base_url", "http://localhost:11434"), transport=httpx.MockTransport(handler))

    gateway._make_ollama_client = fake_client
    return gateway


CLASSIFICATION_TOOL = {
    "name": "classification",
    "description": "Return a ClassificationResult matching the given schema.",
    "input_schema": {
        "type": "object",
        "properties": {"label": {"type": "string"}, "confidence": {"type": "number"}},
        "required": ["label", "confidence"],
    },
}
CLASSIFICATION_TOOL_CHOICE = {"type": "tool", "name": "classification"}


def test_a_tool_schema_request_embeds_the_schema_in_the_prompt_ollama_actually_sees(tmp_path):
    seen_prompts = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_prompts.append(body["prompt"])
        return httpx.Response(200, json={"response": '{"label": "update", "confidence": 0.9}'})

    gateway = _gateway(tmp_path, handler)

    response = gateway.generate(
        "Classify this message.", tools=[CLASSIFICATION_TOOL], tool_choice=CLASSIFICATION_TOOL_CHOICE, skip_cache=True,
    )

    assert response.text == '{"label": "update", "confidence": 0.9}'
    assert len(seen_prompts) == 1
    # The model was actually told the schema -- not just the bare prompt
    # text, which is what CHN-27 found was happening before this fix.
    assert "input_schema" not in seen_prompts[0]  # the raw tool wrapper key never leaks into the prompt
    assert '"label"' in seen_prompts[0]
    assert '"confidence"' in seen_prompts[0]
    assert "Classify this message." in seen_prompts[0]


def test_a_plain_request_with_no_tool_schema_is_sent_unmodified(tmp_path):
    seen_prompts = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_prompts.append(body["prompt"])
        return httpx.Response(200, json={"response": "plain text answer"})

    gateway = _gateway(tmp_path, handler)

    response = gateway.generate("Just answer plainly.", skip_cache=True)

    assert response.text == "plain text answer"
    assert seen_prompts == ["Just answer plainly."]


def test_a_markdown_json_fence_is_stripped_before_generate_structured_ever_sees_it(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": '```json\n{"label": "chatter", "confidence": 0.8}\n```'})

    gateway = _gateway(tmp_path, handler)

    response = gateway.generate(
        "Classify this message.", tools=[CLASSIFICATION_TOOL], tool_choice=CLASSIFICATION_TOOL_CHOICE, skip_cache=True,
    )

    # Must be valid, fence-free JSON -- generate_structured() calls
    # json.loads() on this directly with no fence-handling of its own.
    parsed = json.loads(response.text)
    assert parsed == {"label": "chatter", "confidence": 0.8}


def test_end_to_end_through_generate_structured_actually_parses(tmp_path):
    # The real acceptance test: this is the exact call shape
    # detection.classifier.classify_message makes, going through
    # generate_structured() itself, not just gateway.generate()
    # directly -- proving the fix actually closes the real gap, not
    # just an internal implementation detail.
    from pydantic import BaseModel

    from p1.llm.structured import generate_structured

    class ClassificationResult(BaseModel):
        label: str
        confidence: float

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": '{"label": "update", "confidence": 0.95}'})

    gateway = _gateway(tmp_path, handler)

    result = generate_structured(gateway, "Classify this message.", ClassificationResult, tool_name="classification")

    assert result.label == "update"
    assert result.confidence == 0.95
