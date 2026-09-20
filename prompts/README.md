# Prompt registry (SPN-05)

Every prompt sent to a model anywhere in this repository lives here, never
as a string literal in Python. This is what makes prompt regression
detectable: `p1.prompts.PromptRegistry` records the exact version string
returned for a prompt alongside every eval-harness result, so a prompt
change shows up as a line in the eval history instead of an invisible
diff in model behaviour.

`tests/unit/test_no_inline_prompts.py` is the lint test that enforces
this (SPN-05's acceptance test): no prompt-shaped string literal is
allowed to exist outside this directory.

## Layout

    prompts/
      <capability>/
        v1.md
        v2.md
        ...

One directory per capability (named after the WBS task that uses it,
e.g. `chn09_classify_message`), containing one file per version. Files
are plain text with `{placeholder}` slots filled by
`Prompt.render(**values)`. `PromptRegistry.get(capability)` returns the
highest version by default; pass `version=` to pin an older one
deliberately (e.g. to reproduce a past eval run byte-for-byte).

A version is never edited in place once an eval run has referenced it --
a changed prompt gets a new version file, so old results stay
reproducible against the version they actually used.

## Capabilities

- `chn09_classify_message` (CHN-09) -- classifies a single message that
  CHN-08's deterministic rules left unsettled into one of six labels
  (update, question, blocker, decision, chatter, noise) plus a
  confidence. Current version: v1.

- `chn13_daily_summary` (CHN-13) -- turns one content section's worth
  of already-gathered facts (what moved / blockers raised / decisions
  taken / questions still awaiting an answer) into one line of grounded
  prose per fact, never deciding what counts as a fact itself. Current
  version: v1.

- `ollama_schema_instructions` (2026-09-20, alongside CHN-27's ollama
  tool-schema fix) -- not tied to one capability: this is the wrapper
  instruction text `LLMGateway._call_ollama()` appends to ANY
  structured-output request when the active provider is `ollama`,
  telling a model with no native tool-calling API to answer with a
  flat JSON object matching the given schema instead of echoing the
  schema itself back. Rendered with `{example}` (a placeholder
  instance built by `_example_instance()`) and `{schema}` (the raw
  JSON Schema). Current version: v1.

- `ops_llm_gateway_smoke_test` (2026-09-20) -- the fixed prompt text
  `scripts/test_llm_gateway_smoke.py` sends when a person runs it by
  hand to check whether LLM_PROVIDER is actually reaching the
  configured provider (Bedrock, Ollama, etc.) -- not a real capability,
  just an ad-hoc diagnostic that still has to follow this repo's own
  rule. Current version: v1.
