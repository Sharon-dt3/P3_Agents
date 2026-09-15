from p1.llm.gateway import LLMGateway


def test_cache_hit_avoids_second_provider_call(tmp_path, monkeypatch):
    calls = []

    def fake_call_provider(self, provider, prompt, system, max_tokens, temperature, tools, tool_choice):
        calls.append(provider)
        return "fake response", "fake-model", 10, 5

    monkeypatch.setattr(LLMGateway, "_call_provider", fake_call_provider)

    gateway = LLMGateway(
        provider="anthropic",
        anthropic_api_key="test-key",
        cache_dir=tmp_path / "cache",
        call_log_path=tmp_path / "calls.jsonl",
    )

    first = gateway.generate("What is the status of channel X?")
    second = gateway.generate("What is the status of channel X?")

    assert len(calls) == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.text == first.text


def test_provider_swap_by_config(tmp_path, monkeypatch):
    seen = []

    def fake_call_provider(self, provider, prompt, system, max_tokens, temperature, tools, tool_choice):
        seen.append(provider)
        return f"response from {provider}", f"{provider}-model", 1, 1

    monkeypatch.setattr(LLMGateway, "_call_provider", fake_call_provider)

    LLMGateway(
        provider="anthropic", anthropic_api_key="test-key",
        cache_dir=tmp_path / "cache_a", call_log_path=tmp_path / "calls_a.jsonl",
    ).generate("same prompt")

    LLMGateway(
        provider="ollama",
        cache_dir=tmp_path / "cache_b", call_log_path=tmp_path / "calls_b.jsonl",
    ).generate("same prompt")

    assert seen == ["anthropic", "ollama"]
