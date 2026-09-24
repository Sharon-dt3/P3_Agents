"""
Detection pipeline (CHN-08 + CHN-09 unified): the single write path from
"here is a batch of messages" to "every one of them has a row in
classifications, except the ones the model called noise."

Ordering is the whole point and is not negotiable per-call: every
message goes through detection.rules.evaluate_message FIRST. Only a
message left settled=False there is ever passed to
detection.classifier.classify_message -- the model never sees a message
a rule has already decided.

Persistence asymmetry, both deliberate (see rules.py and classifier.py
for the two decisions this combines):
- A rule-settled message is always persisted: label="noise",
  method="rule", rule_name=<the rule>, confidence=None (a rule's verdict
  is exact by construction; there is no confidence to record). A named,
  inspectable exclusion is CHN-08's acceptance test.
- A model-settled message is persisted only when its label is NOT
  "noise" -- CHN-09's "noise is discarded, not stored" note. A model
  noise call is a real judgement (unlike a rule exclusion, it required
  reading the content) but still carries no signal worth keeping in the
  classifications table, so it is reported in the returned outcome list
  for visibility/testing and left out of the database.

Every outcome, persisted or not, also carries `uncertain` -- computed
from the model's own confidence for model-settled rows, always False for
rule-settled rows (a rule has no confidence to be uncertain about).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from spine.config.calendar import parse_instant

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig
from p1.detection.classifier import (
    CLASSIFIER_NOISE_LABEL,
    classify_message,
    is_uncertain,
)
from p1.detection.rules import evaluate_message
from p1.prompts import PromptRegistry
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import DEFAULT_DB_PATH


@dataclass(frozen=True)
class ClassificationOutcome:
    """What happened to one message after the full CHN-08 -> CHN-09
    pipeline ran on it."""

    message_id: str
    label: str
    method: str  # "rule" | "model"
    confidence: float | None
    rule_name: str | None
    persisted: bool
    uncertain: bool


def _edited_since(message: TeamsMessage, classified_at: str) -> bool:
    """True iff Teams reports this message edited AFTER its stored model
    verdict was written -- classified_at is SQLite's UTC 'YYYY-MM-DD
    HH:MM:SS'. A message never edited is never "edited since"."""
    if not message.edited_at:
        return False
    written = datetime.strptime(classified_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return parse_instant(message.edited_at) > written


def classify_and_persist(
    messages: list[TeamsMessage],
    config: ChannelConfig,
    gateway,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    prompt_registry: PromptRegistry | None = None,
    reuse_model_verdicts: bool = False,
) -> list[ClassificationOutcome]:
    """reuse_model_verdicts=True is for a caller that re-runs this over the
    same growing message list on a timer (the live runners' 5-minute tick):
    a message the MODEL has already judged, and that has not been edited
    since, keeps its stored verdict instead of being sent to the model
    again. Rules are still re-evaluated for every message every time (they
    are free, and a config change can newly settle a message), and an
    edited message is always re-judged. Off by default, so every one-shot
    script, the eval harness and any prompt-version comparison still
    re-judge everything.

    Found 2026-09-24: without this, each tick sent every unsettled message
    (31 for one channel, ~3.6 minutes of a 5-minute cycle) to a local model
    that answers one request at a time, so anything else needing the model
    -- including the real 17:30 digest -- queued behind it and timed out."""
    store = ClassificationStore(db_path)
    outcomes: list[ClassificationOutcome] = []
    stored_verdicts = store.model_verdicts() if reuse_model_verdicts else {}

    for message in messages:
        rule_decision = evaluate_message(message, config)

        if rule_decision.settled:
            store.record(
                message_id=message.id,
                label=rule_decision.label,
                method="rule",
                confidence=None,
                rule_name=rule_decision.rule_name,
            )
            outcomes.append(
                ClassificationOutcome(
                    message_id=message.id,
                    label=rule_decision.label,
                    method="rule",
                    confidence=None,
                    rule_name=rule_decision.rule_name,
                    persisted=True,
                    uncertain=False,
                )
            )
            continue

        prior = stored_verdicts.get(message.id)
        if prior is not None and not _edited_since(message, prior[2]):
            label, confidence, _ = prior
            outcomes.append(
                ClassificationOutcome(
                    message_id=message.id, label=label, method="model", confidence=confidence,
                    rule_name=None, persisted=True, uncertain=is_uncertain(confidence),
                )
            )
            continue

        result = classify_message(message, gateway, prompt_registry=prompt_registry)
        uncertain = is_uncertain(result.confidence)

        if result.label == CLASSIFIER_NOISE_LABEL:
            outcomes.append(
                ClassificationOutcome(
                    message_id=message.id,
                    label=result.label,
                    method="model",
                    confidence=result.confidence,
                    rule_name=None,
                    persisted=False,
                    uncertain=uncertain,
                )
            )
            continue

        store.record(
            message_id=message.id,
            label=result.label,
            method="model",
            confidence=result.confidence,
            rule_name=None,
        )
        outcomes.append(
            ClassificationOutcome(
                message_id=message.id,
                label=result.label,
                method="model",
                confidence=result.confidence,
                rule_name=None,
                persisted=True,
                uncertain=uncertain,
            )
        )

    return outcomes
