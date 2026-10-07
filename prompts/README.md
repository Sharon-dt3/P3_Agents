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
  confidence. Current version: v3 (2026-10-07) -- v2, run five times each on a live bulky message, labelled "yeah same thing happened to me ... I got a new key and it works again" as chatter every time (the update inside it never reached the digest) and listed a hedging trailing sentence ("Haven't switched anything on though.") as an update point of its own every time; v3 says a message that only OPENS with agreement but then reports something new is not chatter, and that a sentence which only qualifies the one before it is folded into it. Measured on the same messages: the first became an update 5/5, the second disappeared 5/5, and four other live messages kept their labels and points. Earlier version: v2 (2026-10-01) -- v1 only ever produced
  that one dominant label per message, so a bulky message mixing real
  content types (some progress, plus a genuine embedded blocker or
  question) could only ever land in one digest section, under
  whichever type was dominant; v2 additionally asks for an optional,
  per-point breakdown (`ClassificationResult.points`) when a message
  genuinely contains more than one distinct thing, each point carrying
  its own label -- empty for the ordinary single-point message, which
  is most of them. The one dominant (label, confidence) pair stays
  exactly as v1 produced it and is still the only thing persisted to
  the `classifications` table -- rules.py, the participation ledger,
  and every existing golden-case eval are unaffected; `points` is
  purely additive, stored separately (`classification_points`,
  migration 0007), consumed only by digest rendering.

- `chn13_daily_summary` (CHN-13) -- turns one content section's worth
  of already-gathered facts (what moved / blockers raised / decisions
  taken / questions still awaiting an answer) into grounded prose, never
  deciding what counts as a fact itself. Current version: v2 -- v1 wrote
  exactly one line per fact regardless of how many distinct points that
  fact's own message actually contained, silently compressing a bulky,
  multi-point update into a single sentence; v2 (2026-10-01) asks for
  one line per distinct point within an item instead, so a long update
  is treated as the several facts it actually is, not one. Current
  version: v3 (2026-10-01) -- v2, live-observed, sometimes over-split a
  single long-but-coherent sentence at its own "and"s into run-on
  fragments that only read correctly as a continuation of the line
  before them; v3 adds an explicit "a distinct point is a separate
  thing, not every clause joined by 'and'" rule, plus a standalone-
  sentence requirement for every line. Current version: v4 (2026-10-07) --
  v3 reversed the meaning of a label the author used: "the source links
  work on the posted but no update lines" came out as "on posted lines but
  not on update lines" in 6 of 6 runs. Current version: v5 (2026-10-07) -- v4 still gave a hedging sentence its own
  line ("not saying we change it, just flagging" came out as its own bullet; 3 such
  lines per run on the live day). v5 adds one sentence inside the "distinct point"
  paragraph: a sentence that only qualifies the point before it goes into that
  point's line as a short clause, or is left out. Measured on the same day: 3 filler
  lines per run became 1, the "posted but no update" label stayed intact 3/3, and
  the digest kept its third-person wording. A first attempt that added a separate
  rule instead made the writer copy first-person sentences ("I'll keep going on...")
  verbatim and was discarded. v4 adds a rule that the author's own
  names, labels and status words stay intact as one unit (and are quoted
  rather than rephrased when unclear); the same message kept the phrase in
  6 of 6 runs.

- `chn13_blocker_followup` (2026-10-07) -- given the day's blockers (labelled B1, B2, ...)
  and the messages posted after them, says which later message, if any, states that the
  same blocker is sorted out, with an exact quote. The answer is checked in code before
  anything is shown (see `p1/reporting/blocker_followup.py`). Current version: v1.

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
