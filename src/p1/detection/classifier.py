"""
Update detection -- classifier for the remainder (CHN-09).

Schema-constrained judgement calls only. Every message this module ever
sees has already been through detection.rules.evaluate_message and left
settled=False there -- the model never sees a message a rule has already
decided (see detection/rules.py and detection/pipeline.py, which is the
only caller of classify_message and is what enforces that ordering).

Design decision made here, not silently assumed:

- LOW_CONFIDENCE_THRESHOLD is the cutoff below which a classification is
  surfaced as uncertain rather than acted on as settled fact. The forced
  schema means the model always returns exactly one of the six labels --
  it never gets to abstain -- so "uncertain" has to be a property this
  module computes from the model's own stated confidence, not a seventh
  label it can choose. 0.6 is chosen as a plain reading of the model's
  own number: confidence here means "how sure am I THIS label is right",
  not "better than the ~0.17 chance rate of picking among six labels",
  so anything below the point where the model itself is more unsure than
  sure is exactly the case this task's acceptance test means by
  "flagged, not guessed." See DECISION_LOG.md.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from p1.adapters.teams_reader import TeamsMessage
from p1.llm.structured import generate_structured
from p1.prompts import PromptRegistry

CLASSIFIER_CAPABILITY = "chn09_classify_message"
CLASSIFIER_NOISE_LABEL = "noise"

# Below this, the model's own stated confidence says it isn't sure.
LOW_CONFIDENCE_THRESHOLD = 0.6


class LabeledPoint(BaseModel):
    """One distinct point within a message's own text, labeled on its
    own -- a bulky message is often several of these at once (see
    classify_message's own docstring). point_text must be an exact,
    verbatim substring of the message it came from; the grounding
    kernel verifies this the same way it verifies a digest line's own
    quote, so a fabricated point_text is dropped, never rendered."""

    label: Literal["update", "question", "blocker", "decision"]
    point_text: str
    confidence: float = Field(ge=0.0, le=1.0)


class ClassificationResult(BaseModel):
    """The model's forced-schema verdict on one message. label is one of
    the six CHN-09 labels; confidence is the model's own stated
    certainty in THIS label, not an importance or urgency score. This
    top-level (label, confidence) pair is the one and only thing
    detection/pipeline.py persists to the classifications table, and
    the one and only thing rules.py, the participation ledger, and
    every existing golden-case eval depend on -- unchanged by points
    below, which is purely additive.

    points is a finer-grained, optional breakdown of that same message
    into its distinct sub-points, each with its OWN label -- empty for
    the overwhelming majority of real messages (a short, single-point
    update has nothing to break down), populated only when the message
    genuinely contains more than one distinct thing. This is what lets
    digest rendering route a bulky message's embedded blocker or
    question to its own correct section, instead of every point in a
    message landing under its single dominant label (see
    DECISION_LOG.md, 2026-10-01)."""

    label: Literal["update", "question", "blocker", "decision", "chatter", "noise"]
    confidence: float = Field(ge=0.0, le=1.0)
    points: list[LabeledPoint] = Field(default_factory=list)


def is_uncertain(confidence: float) -> bool:
    """True when a classification's confidence falls below the threshold
    below which it must be surfaced for a person to review rather than
    treated as a settled label."""
    return confidence < LOW_CONFIDENCE_THRESHOLD


def classify_message(
    message: TeamsMessage,
    gateway,
    *,
    prompt_registry: PromptRegistry | None = None,
) -> ClassificationResult:
    """Judge one message CHN-08's rules could not settle -- a bulky
    message (several distinct accomplishments, a blocker, a question,
    all in one post) is judged for both its one dominant label AND,
    where it genuinely contains more than one distinct thing, a
    per-point breakdown (see ClassificationResult.points' own
    docstring). Raises StructuredOutputError (never returns a guessed
    default) if the model cannot produce a schema-valid result within
    the configured retries.

    max_tokens is raised above generate_structured's own 1024 default --
    a bulky message's point breakdown, each point carrying its own
    verbatim text, needs real room; 1024 was tuned for a single
    label+confidence response, not this."""
    registry = prompt_registry or PromptRegistry()
    prompt = registry.get(CLASSIFIER_CAPABILITY)
    rendered = prompt.render(message_body=message.body)
    return generate_structured(
        gateway, rendered, ClassificationResult, tool_name="classification", max_tokens=2048,
    )
