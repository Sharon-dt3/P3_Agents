import json

from p1.llm.gateway import LLMGateway


def test_call_log_records_provider_tokens_and_latency(tmp_path, monkeypatch):
    def fake_call_provider(self, provider, prompt, system, max_tokens, temperature, tools, tool_choice):
        return "fake response", "fake-model", 10, 5

    monkeypatch.setattr(LLMGateway, "_call_provider", fake_call_provider)

    call_log_path = tmp_path / "calls.jsonl"
    gateway = LLMGateway(
        provider="anthropic",
        anthropic_api_key="test-key",
        cache_dir=tmp_path / "cache",
        call_log_path=call_log_path,
    )

    gateway.generate("What is the status of channel X?")
    gateway.generate("What is the status of channel X?")  # second call is a cache hit

    lines = call_log_path.read_text().strip().splitlines()
    assert len(lines) == 2

    first_entry = json.loads(lines[0])
    second_entry = json.loads(lines[1])

    for entry in (first_entry, second_entry):
        assert entry["provider"] == "anthropic"
        assert entry["model"] == "fake-model"
        assert entry["prompt_tokens"] == 10
        assert entry["completion_tokens"] == 5
        assert isinstance(entry["latency_ms"], (int, float))
        assert "timestamp" in entry
        assert "cache_key" in entry

    assert first_entry["cache_hit"] is False
    assert second_entry["cache_hit"] is True
