"""
CHN-11 golden cases: GC1 (update-detection precision/recall) and GC2
(non-responder exact match) -- the first two real cases registered into
SPN-07's harness. Both are measured against the real CHN-07 fixtures
and seed/fixtures/labels.csv, the same hand-labelled ground truth
test_update_detection_against_fixtures.py and
test_participation_against_fixtures.py already exercise as individual
assertions. This module aggregates that same ground truth into the two
named metrics capability C4's row in docs/MASTER_IMPLEMENTATION_PLAN.md
requires, so they print and get committed by the eval harness instead of
only ever being pass/fail inside CI.

GC1 -- update-detection precision and recall (target: precision >=0.80,
recall reported only), scored purely against p1.detection.rules --
CHN-08's deterministic engine, with no model call involved at all. The
positive class is "this message is correctly excluded by a rule" (never
"update"): a false positive there means a rule wrongly excluded a
genuine update, which is the failure that makes an innocent person look
silent -- precision is what guards against that, so precision is the
one gated number; a false negative (a bot/system/deleted/late post that
slips through unexcluded) just means it reaches CHN-09's classifier
instead, which is a nuisance, not a false accusation -- see
DECISION_LOG.md and section 6 of docs/MASTER_IMPLEMENTATION_PLAN.md
("Recall matters less than precision: a missed [exclusion] is a
nuisance, a false 'no update' names an innocent person").

CHN-28 update: until this row, this ground truth only ever scored 4 of
CHN-08's 8 deterministic rules (bot_post, system_message,
deleted_message, outside_update_window) -- the other 4
(not_on_roster, thread_reply_not_counted, non_working_day,
below_length_floor) had zero representation here, so a regression in
any of them could never show up in either printed number, however
perfect precision/recall looked. Three of the four now have a real,
hand-authored positive example each (DIFF-ROSTER-01, DIFF-THREADOFF-01,
DIFF-SHORT-01 in labels.csv) -- non_working_day is deliberately left for
CHN-29's own edge-case pass, which already names it. See DECISION_LOG.md
for the full reasoning and the bug-injection proof that each new example
is load-bearing.

GC2 -- non-responder set exact match, including all three participation
states (excluded / posted_no_update / no_message), across three
independently hand-verifiable channel/day combinations:
  - proj-alpha, 2025-06-05: the full 6-member roster lands as
    non-responders -- liam.oconnor excluded (DIFF-LEAVE-01), and every
    other member's actual organic message that day is either rule-
    excluded (outside the update window) or classified chatter
    (DIFF-CHATTER-01), so nobody contributes. Confirmed empirically
    against the real fixtures, not assumed -- see DECISION_LOG.md.
  - proj-gamma, 2025-06-05: 5 of 6 roster members have zero messages
    that day (DIFF-REACTION-01's aisha.rahman among them); wei.chen
    does post a genuine update and is correctly a contributor, absent
    from the set entirely.
  - proj-beta, 2025-06-11: DIFF-SILENT-01 -- zero messages anywhere in
    the channel that day, so the full 7-member roster (no exceptions
    configured) lands as no_message, the one scenario knowable without
    running any pipeline at all.
This is an "equals" (exact dict) comparison per channel/day, never a
proportion -- a single spurious or missing member fails the case
outright, per this task's own acceptance test.
"""

from __future__ import annotations

import csv
import re
import shutil
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from p1.adapters.fixtures import load_teams_fixtures
from p1.config.loader import ChannelConfigStore
from p1.detection.pipeline import classify_and_persist
from p1.detection.rules import evaluate_message
from p1.eval.cases import GoldenCase, GoldenCaseRegistry, MetricResult, at_least, equals
from p1.llm.gateway import LLMResponse
from p1.participation.ledger import build_ledger
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore

LABELS_PATH = Path("seed/fixtures/labels.csv")

ALPHA = "19:proj-alpha@thread.tacv2"
BETA = "19:proj-beta@thread.tacv2"
GAMMA = "19:proj-gamma@thread.tacv2"

# --- GC1: update-detection precision/recall -------------------------------

# Categories from labels.csv with an unambiguous CHN-08 structural
# verdict, and what that verdict is. Categories not listed here
# (similar_names, channel_silent_day, configured_non_working_day,
# reaction_only_member, chatter_only_member, on_leave_member) are
# CHN-09/CHN-10 territory -- content judgement or participation
# arithmetic, not rule exclusion -- and carry no structural claim for
# this metric to score.
_EXCLUDED_CATEGORIES = frozenset(
    {
        "bot_post",
        "system_post",
        "deleted_message",
        "late_post_after_window",
        # CHN-28: three more of CHN-08's own eight rules, previously
        # scored by nothing in this ground truth at all -- see
        # DECISION_LOG.md for why this was the weakest metric in the
        # harness and how these were chosen.
        "not_on_roster",
        "thread_reply_when_not_counted",
        "below_length_floor",
    }
)
_ELIGIBLE_CATEGORIES = frozenset(
    {
        "edited_message",
        "posting_on_behalf_of_another",
        "ambiguous_mention_as_question",
        "departed_tenant_member",
    }
)
_THREAD_REPLY_CATEGORY = "thread_reply_only_update"


def _load_rule_ground_truth() -> dict[str, bool]:
    """message_id -> expected "should be excluded by a CHN-08 rule"."""
    ground_truth: dict[str, bool] = {}
    with LABELS_PATH.open(newline="") as f:
        for row in csv.DictReader(f):
            category = row["category"]
            ids = [message_id for message_id in row["message_ids"].split(";") if message_id]
            if category in _EXCLUDED_CATEGORIES:
                for message_id in ids:
                    ground_truth[message_id] = True
            elif category in _ELIGIBLE_CATEGORIES:
                for message_id in ids:
                    ground_truth[message_id] = False
            elif category == _THREAD_REPLY_CATEGORY:
                # This row's message_ids mixes priya.sharma's ordinary
                # root question with james.okafor's reply-only update --
                # only the reply is this difficulty's planted claim; the
                # root is context, not something to score here.
                for message_id in ids:
                    if "reply" in message_id:
                        ground_truth[message_id] = False
    return ground_truth


def _measure_gc1() -> list[MetricResult]:
    ground_truth = _load_rule_ground_truth()
    _, _, messages_by_channel = load_teams_fixtures()
    message_index = {m.id: m for msgs in messages_by_channel.values() for m in msgs}
    configs = {c.channel_id: c for c in ChannelConfigStore().list_configured_channels()}

    tp = fp = fn = tn = 0
    for message_id, expected_excluded in ground_truth.items():
        message = message_index[message_id]
        config = configs[message.channel_id]
        actual_excluded = evaluate_message(message, config).settled
        if expected_excluded and actual_excluded:
            tp += 1
        elif not expected_excluded and actual_excluded:
            fp += 1
        elif expected_excluded and not actual_excluded:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    counts = f"tp={tp} fp={fp} fn={fn} tn={tn} n={tp + fp + fn + tn}"

    return [
        MetricResult(
            metric_id="GC1-precision",
            name="update-detection precision (excluded class)",
            measured=round(precision, 4),
            target=0.80,
            comparator_name="at_least",
            passed=at_least(precision, 0.80),
            detail=counts,
        ),
        MetricResult(
            metric_id="GC1-recall",
            name="update-detection recall (excluded class)",
            measured=round(recall, 4),
            target=0.0,
            comparator_name="at_least",
            passed=at_least(recall, 0.0),
            detail="reported per the WBS, not gated -- " + counts,
        ),
    ]


# --- GC2: non-responder exact match ----------------------------------------

_MESSAGE_BODY_RE = re.compile(r'Message to classify:\n"(.*)"\s*\Z', re.DOTALL)


class _PreciseScriptedGateway:
    """Matches the exact interpolated message body -- the text after
    "Message to classify:" -- never a substring anywhere else in the
    rendered prompt. The classifier prompt's own worked examples name
    "Sounds good." as a sample chatter phrase, which is also
    DIFF-CHATTER-01's real organic message text: a naive
    `if snippet in prompt` match (as in
    test_participation_against_fixtures.py's ScriptedGateway) would
    match that instructional text on every single call, not just
    fatima.hassan's message, silently mis-scripting every other
    eligible message in this fixture set to "chatter" too. Anything not
    specifically scripted defaults to "update" -- safe here because the
    fixture generator's ordinary organic traffic really is
    update/question/blocker-shaped text, and all three of those labels
    count as a contributor exactly like "update" does for the ledger's
    purposes."""

    def __init__(self, canned: dict[str, str], default: str = '{"label": "update", "confidence": 0.9}'):
        self._canned = canned
        self._default = default

    def generate(self, prompt, **kwargs):
        match = _MESSAGE_BODY_RE.search(prompt)
        body = match.group(1) if match else prompt
        text = self._canned.get(body, self._default)
        return LLMResponse(
            text=text, provider="anthropic", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


@contextmanager
def _seeded_db():
    tmp_dir = tempfile.mkdtemp(prefix="chn11_gc2_")
    try:
        db_path = str(Path(tmp_dir) / "eval.db")
        init_db(db_path)
        ChannelConfigStore().sync_to_db(db_path)

        _, _, messages_by_channel = load_teams_fixtures()
        all_messages = [m for ch in (ALPHA, BETA, GAMMA) for m in messages_by_channel.get(ch, [])]

        conn = get_connection(db_path)
        try:
            for author_id in sorted({m.author_id for m in all_messages if m.author_id}):
                conn.execute(
                    "INSERT OR IGNORE INTO members (id, display_name) VALUES (?, ?)",
                    (author_id, author_id),
                )
            conn.commit()
        finally:
            conn.close()

        MessageStore(db_path).upsert_messages(all_messages)

        config_store = ChannelConfigStore()
        gateway = _PreciseScriptedGateway({"Sounds good.": '{"label": "chatter", "confidence": 0.9}'})

        for channel_id in (ALPHA, BETA, GAMMA):
            config = config_store.get_channel_config(channel_id)
            # proj-gamma is not allowlisted (config/channels/proj-gamma.yaml)
            # -- in the real pipeline CHN-04's scope gate means it never
            # reaches this point at all. Classified directly here anyway,
            # exactly as the CHN-10 fixture test does: neither the rule
            # engine nor the classifier has any opinion on scope, and
            # aisha.rahman's absence needs gamma's real message set
            # present to be a meaningful check at all.
            channel_messages = [m for m in all_messages if m.channel_id == channel_id]
            classify_and_persist(channel_messages, config, gateway, db_path=db_path)

        yield db_path, config_store
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# Hand-verified expected non-responder sets -- confirmed by running the
# real ingestion -> detection -> classification -> ledger pipeline
# against the committed fixtures (see this module's docstring for how
# each was arrived at); not asserted from a scripted assumption about
# what "ordinary" organic traffic must contain.
_EXPECTED = {
    (ALPHA, date(2025, 6, 5)): {
        "priya.sharma": "posted_no_update",
        "james.okafor": "no_message",
        "wei.chen": "posted_no_update",
        "fatima.hassan": "posted_no_update",
        "liam.oconnor": "excluded",
        "sara.johansson": "posted_no_update",
    },
    (GAMMA, date(2025, 6, 5)): {
        "noah.becker": "no_message",
        "aisha.rahman": "no_message",
        "olivia.dupont": "no_message",
        "mateo.silva": "no_message",
        "olivia.dupree": "no_message",
        # wei.chen deliberately absent: he posts a genuine update this
        # day and is correctly a contributor, never a non-responder.
    },
    (BETA, date(2025, 6, 11)): {
        "james.okafor": "no_message",
        "wei.chen": "no_message",
        "diego.martinez": "no_message",
        "amara.okonkwo": "no_message",
        "kenji.tanaka": "no_message",
        "elena.rossi": "no_message",
        "sofia.almeida": "no_message",
    },
}


def _measure_gc2() -> list[MetricResult]:
    results = []
    with _seeded_db() as (db_path, config_store):
        for (channel_id, day), expected in _EXPECTED.items():
            config = config_store.get_channel_config(channel_id)
            actual = {r.member_id: r.state for r in build_ledger(channel_id, day, config, db_path=db_path)}
            channel_name = channel_id.split(":")[1].split("@")[0]
            results.append(
                MetricResult(
                    metric_id=f"GC2-{channel_name}-{day.isoformat()}",
                    name=f"non-responder exact match ({channel_name}, {day.isoformat()})",
                    measured=actual,
                    target=expected,
                    comparator_name="equals",
                    passed=equals(actual, expected),
                    detail=f"{len(expected)} expected non-responder(s)",
                )
            )
    return results


def register(registry: GoldenCaseRegistry) -> None:
    registry.register(
        GoldenCase(
            case_id="GC1",
            description="Update-detection precision/recall against hand labels (CHN-11)",
            measure_fn=_measure_gc1,
        )
    )
    registry.register(
        GoldenCase(
            case_id="GC2",
            description="Non-responder set exact match, all three participation states (CHN-11)",
            measure_fn=_measure_gc2,
        )
    )