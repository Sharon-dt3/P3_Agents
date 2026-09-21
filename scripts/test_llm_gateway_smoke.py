"""Ad-hoc, safe smoke test for LLMGateway against whatever LLM_PROVIDER
is currently set in .env -- no DB writes, no Teams posts, no proposals.

Run it with the same interpreter/venv the live processes use, e.g.:
    uv run python3 scripts/test_llm_gateway_smoke.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from p1.llm.gateway import LLMGateway  # noqa: E402
from p1.prompts import PromptRegistry  # noqa: E402

def main() -> None:
    gw = LLMGateway()
    print(f"Configured provider : {gw.provider}")
    print(f"Bedrock model id     : {gw.bedrock_model_id}")
    print(f"Bedrock region       : {gw.bedrock_aws_region}")
    print(f"Bedrock key present  : {bool(gw.bedrock_aws_access_key)}")
    print("Calling gateway.generate() with a trivial, uncached prompt...")

    # Prompt text lives in prompts/ (SPN-05's own rule: no hand-written
    # prompt as a Python literal), even for this ad-hoc smoke test --
    # combined into one prompt string here rather than split into a
    # separate system= message, since that split makes no difference to
    # what this script is actually checking (whether a real call reaches
    # the configured provider at all).
    smoke_prompt = PromptRegistry().get("ops_llm_gateway_smoke_test").text

    response = gw.generate(
        prompt=smoke_prompt,
        max_tokens=64,
        temperature=0.0,
        skip_cache=True,  # force a fresh call, not a cache replay
    )

    print("\n--- LLMResponse ---")
    print(f"provider           : {response.provider}")
    print(f"model              : {response.model}")
    print(f"cache_hit          : {response.cache_hit}")
    print(f"degraded           : {response.degraded}")
    print(f"latency_ms         : {response.latency_ms:.1f}")
    print(f"prompt_tokens      : {response.prompt_tokens}")
    print(f"completion_tokens  : {response.completion_tokens}")
    print(f"text               : {response.text!r}")

    if response.provider == "bedrock" and not response.degraded:
        print("\nRESULT: genuine, non-degraded Bedrock (Claude Sonnet 4) call confirmed.")
    elif response.degraded:
        print("\nRESULT: Bedrock call FAILED and degraded to Ollama -- see text above for clues, "
              "and check data/logs/llm_calls.jsonl for the underlying error.")
    else:
        print(f"\nRESULT: unexpected provider '{response.provider}' -- check LLM_PROVIDER in .env.")

if __name__ == "__main__":
    main()
