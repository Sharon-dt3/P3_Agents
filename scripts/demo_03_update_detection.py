"""
Recording beat 3 (CHN-32): update detection -- one message settled by a
deterministic RULE (no model involved) and one settled by the CLASSIFIER,
both real messages from the real p1-agent-test channel.

For each example it re-runs the real decision code live and prints the
outcome: the rule engine (p1.detection.rules.evaluate_message) first; only
if no rule fires does the real model classifier run
(p1.detection.classifier.classify_message, through the real LLMGateway).
It also prints the split for the channel, computed live against today's
config: how many messages rules settle without ever calling a model versus
how many are left for the model.

Read-only: nothing is written to the database or sent anywhere. The single
model call is the one live classifier demonstration.

Usage:
    uv run python scripts/demo_03_update_detection.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv()

from p1.config.calendar import to_local
from p1.config.loader import ChannelConfigStore
from p1.detection.classifier import classify_message
from p1.detection.rules import evaluate_message
from p1.llm.gateway import LLMGateway
from p1.storage.db import get_connection
from p1.storage.members_repo import resolve_display_name
from run_live_pipeline_p1_agent_test import CHANNEL_ID, LIVE_DB_PATH, _load_channel_messages

PROMPT_PATH = Path("prompts/chn09_classify_message/v1.md")
CONTENT_LABELS = ("update", "question", "blocker", "decision")


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _label_definition(label: str) -> str:
    """The classifier prompt's own definition of this label, so the demo
    shows the criteria the model was actually given."""
    text = PROMPT_PATH.read_text()
    match = re.search(rf"^- {label}:(.*?)(?=^- |\n\nAlongside)", text, re.S | re.M)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _pick(conn, *, method: str, prefer_rules=(), prefer_labels=()):
    rows = conn.execute(
        """
        SELECT m.id, m.posted_at, m.body_raw, c.label, c.rule_name
        FROM classifications c JOIN messages m ON m.id = c.message_id
        WHERE m.channel_id = ? AND c.method = ?
        ORDER BY m.posted_at DESC
        """,
        (CHANNEL_ID, method),
    ).fetchall()
    if method == "model":
        # A demo example should be unambiguous: substantive text, a real
        # content label, and not an @-mention aside that reads like chatter.
        rows = [r for r in rows if len(_plain(r["body_raw"])) >= 40 and "<at " not in (r["body_raw"] or "")] or rows
    for wanted in (prefer_rules if method == "rule" else prefer_labels):
        for r in rows:
            if (r["rule_name"] if method == "rule" else r["label"]) == wanted:
                return r
    return next((r for r in rows if r["rule_name"] != "system_message"), rows[0] if rows else None)


def _describe(message, config) -> None:
    who = resolve_display_name(message.author_id, db_path=LIVE_DB_PATH) if message.author_id else "(no author)"
    local = to_local(message.posted_at, config.timezone).strftime("%a %d %b %H:%M")
    print(f'   from {who}, posted {local} {config.timezone}')
    print(f'   "{_plain(message.body)[:110]}"')


def main() -> int:
    config = ChannelConfigStore().get_channel_config(CHANNEL_ID)
    conn = get_connection(LIVE_DB_PATH)
    try:
        rule_row = _pick(conn, method="rule", prefer_rules=("outside_update_window", "below_length_floor", "not_on_roster"))
        model_row = _pick(conn, method="model", prefer_labels=CONTENT_LABELS)
    finally:
        conn.close()

    messages = {m.id: m for m in _load_channel_messages(LIVE_DB_PATH, CHANNEL_ID)}

    print("=" * 78)
    print("UPDATE DETECTION -- rules first, model only for what rules cannot settle")
    print("=" * 78)

    print("\nA. A message settled by a RULE (deterministic, no model call)")
    msg = messages[rule_row["id"]]
    _describe(msg, config)
    decision = evaluate_message(msg, config)
    print(f"   rule engine ran live -> settled={decision.settled}, rule: {decision.rule_name}")
    print(f"   reason: {decision.reason}")
    print(f"   label: {decision.label}   model called: NO")

    print("\nB. A message settled by the CLASSIFIER (no rule could decide it)")
    msg = messages[model_row["id"]]
    _describe(msg, config)
    decision = evaluate_message(msg, config)
    print(f"   rule engine ran live -> settled={decision.settled} ({decision.reason})")
    gateway = LLMGateway()
    print(f"   so it goes to the model ({gateway.ollama_model}) -- calling it live now ...")
    result = classify_message(msg, gateway)
    print(f"   model says: label={result.label}, confidence={result.confidence}")
    print(f"   stored label for this message: {model_row['label']}")
    definition = _label_definition(result.label)
    if definition:
        print(f"   the prompt defines '{result.label}' as: {definition}")

    # Computed live over every message, not read from stored rows: a stored
    # rule row can go stale after a config change, and a model verdict of
    # 'noise' is deliberately never stored, so stored counts can drift.
    rules_n = sum(1 for m in messages.values() if evaluate_message(m, config).settled)
    model_n = len(messages) - rules_n
    print(f"\nC. The split across all {len(messages)} messages in this channel, computed live against today's config")
    print(f"   settled by rules, zero model calls: {rules_n}")
    print(f"   left for the model to judge:        {model_n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
