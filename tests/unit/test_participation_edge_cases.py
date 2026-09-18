"""
CHN-29: edge-case and failure pass, against the real pipeline and the
real committed CHN-07 fixtures wherever a scenario has one -- never a
hand-simulated shortcut, matching the discipline every prior golden
case in this project already holds itself to.

This module covers the five of the WBS row's eight named scenarios that
had no dedicated end-to-end test anywhere yet. The other three already
have one, and are named here rather than duplicated (see DECISION_LOG.md
for the full investigation):

  - "A day with no messages in a channel" -- DIFF-SILENT-01, proved by
    CHN-11's own GC2-proj-beta-2025-06-11
    (p1.eval.chn11_cases._measure_gc2 / test_gc2_measure_matches_hand_verified_expected_sets).
  - "Graph throttling and delta-token expiry" -- proved by
    tests/unit/test_teams_reader_graph.py
    (test_list_messages_retries_on_429_then_succeeds,
    test_list_messages_raises_after_exhausting_throttle_retries,
    test_list_messages_raises_on_expired_delta_token) and
    tests/unit/test_ingestion_sync.py
    (test_expired_delta_token_triggers_a_clean_resync).
  - "Malformed model output" -- proved by
    tests/unit/test_structured_output.py
    (test_retries_on_invalid_then_succeeds,
    test_raises_after_exhausting_attempts_never_defaults) and
    tests/unit/test_classifier.py (test_invalid_label_retries_then_succeeds),
    the one shared p1.llm.structured.generate_structured() path both
    CHN-13's daily summary and CHN-19's weekly narrative already go
    through too (see those modules' own docstrings).

The five scenarios below are new. Each seeds the real committed
CHN-07 fixture messages for one channel through the real
detection.pipeline.classify_and_persist(), then calls the real
participation.ledger.build_ledger() and asserts on the specific
member(s) each planted difficulty names -- never a synthetic
in-memory shortcut.
"""

from __future__ import annotations

from datetime import date

from p1.adapters.fixtures import load_teams_fixtures
from p1.config.loader import ChannelConfigStore
from p1.detection.pipeline import classify_and_persist
from p1.llm.gateway import LLMResponse
from p1.participation.ledger import (
    NO_MESSAGE,
    POSTED_NO_UPDATE,
    NonWorkingDayError,
    build_ledger,
)
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore

ALPHA = "19:proj-alpha@thread.tacv2"
BETA = "19:proj-beta@thread.tacv2"
GAMMA = "19:proj-gamma@thread.tacv2"


class ScriptedGateway:
    """Identical convention to test_participation_against_fixtures.py's
    own ScriptedGateway: anything not specifically scripted defaults to
    "update", which is safe because the fixture generator's ordinary
    organic traffic really is update/question/blocker-shaped text."""

    def __init__(self, canned: dict[str, str] | None = None, default: str = '{"label": "update", "confidence": 0.9}'):
        self._canned = canned or {}
        self._default = default

    def generate(self, prompt, **kwargs):
        for snippet, response in self._canned.items():
            if snippet in prompt:
                return LLMResponse(
                    text=response, provider="anthropic", model="fake-model",
                    prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
                )
        return LLMResponse(
            text=self._default, provider="anthropic", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


def _seed_and_classify(tmp_path, *, channel_ids: tuple[str, ...]):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    ChannelConfigStore().sync_to_db(db_path)

    _, _, messages_by_channel = load_teams_fixtures()
    all_messages = [m for cid in channel_ids for m in messages_by_channel.get(cid, [])]

    # Members table FK, populated from who actually authored a message --
    # deliberately not from members.json's live membership list. See
    # test_participation_against_fixtures.py's identical note: sofia.almeida
    # (this module's own DIFF-DEPART-01 case) has real posting history
    # despite being absent from Teams-side membership.
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
    gateway = ScriptedGateway()
    for channel_id in channel_ids:
        config = config_store.get_channel_config(channel_id)
        channel_messages = [m for m in all_messages if m.channel_id == channel_id]
        # proj-gamma is not allowlisted -- classified directly here anyway,
        # exactly as every other test in this project touching gamma does:
        # neither the rule engine nor the classifier has any opinion on
        # scope, and this module needs gamma's real message set present.
        classify_and_persist(channel_messages, config, gateway, db_path=db_path)

    return db_path, config_store


# --- 1. A non-working day, configured distinctly from an ordinary weekend --


def test_configured_non_working_day_refuses_rather_than_fabricates(tmp_path):
    """DIFF-NONWORKING-01: 2025-06-13 is a Friday -- not a calendar
    weekend -- but is listed in config/channels/proj-alpha.yaml's
    non_working_dates. build_ledger must refuse to compute a
    non-responder set for it at all (a fabricated result would be worse
    than none), and that refusal must be driven by the channel's own
    config, not by weekday arithmetic alone."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    ChannelConfigStore().sync_to_db(db_path)
    config = ChannelConfigStore().get_channel_config(ALPHA)

    assert date(2025, 6, 13) in config.non_working_dates

    try:
        build_ledger(ALPHA, date(2025, 6, 13), config, db_path=db_path)
        raise AssertionError("expected NonWorkingDayError for the configured non-working Friday")
    except NonWorkingDayError:
        pass

    # Contrast: the ordinary adjacent Thursday is NOT configured as
    # non-working and must not raise -- proving the refusal above is
    # about 2025-06-13 specifically, not a blanket failure.
    records = build_ledger(ALPHA, date(2025, 6, 12), config, db_path=db_path)
    assert isinstance(records, list)


# --- 2. A member whose only update that day was later deleted -------------


def test_deleted_only_update_reverts_to_a_genuine_no_message_day(tmp_path):
    """DIFF-DEL-01: sara.johansson's only message on 2025-06-03 was
    deleted ~25 minutes after posting. The WBS row itself names this the
    case "that most easily produces a false accusation" -- the day must
    revert to an honest no_message day for her, never a fabricated
    posted_no_update (which would at least imply she was present) and
    never silently absent from the ledger altogether (which would mean
    nobody ever follows up)."""
    db_path, config_store = _seed_and_classify(tmp_path, channel_ids=(ALPHA,))
    config = config_store.get_channel_config(ALPHA)

    ledger = {r.member_id: r for r in build_ledger(ALPHA, date(2025, 6, 3), config, db_path=db_path)}
    assert ledger["sara.johansson"].state == NO_MESSAGE


# --- 3. A message edited after the window closed ---------------------------


def test_edited_after_window_close_still_counts_as_an_on_time_contribution(tmp_path):
    """DIFF-EDIT-01: priya.sharma posted on time at 09:30:00 and edited
    110 minutes later, well after proj-alpha's 11:00:00 window close.
    The edit must never disqualify the on-time post or leave her looking
    like a non-responder -- she must not appear in the ledger at all,
    since a contributor is never written to it."""
    db_path, config_store = _seed_and_classify(tmp_path, channel_ids=(ALPHA,))
    config = config_store.get_channel_config(ALPHA)

    ledger = {r.member_id: r for r in build_ledger(ALPHA, date(2025, 6, 2), config, db_path=db_path)}
    assert "priya.sharma" not in ledger, "an on-time (later-edited) update must make her a contributor, not a non-responder"


# --- 4. Two similar display names ------------------------------------------


def test_similar_display_names_are_never_merged_or_confused(tmp_path):
    """DIFF-NAME-01: proj-gamma's roster has both olivia.dupont and
    olivia.dupree -- one letter apart -- and both post real messages on
    2025-06-10. olivia.dupree's 09:30 post is inside gamma's 09:00-11:00
    window and update-shaped, so she must be a contributor. Unrelatedly,
    olivia.dupont also posts that day (proj-gamma-0189) but at 11:41,
    outside the window, so she must remain a non-responder
    (posted_no_update, not no_message -- she did post, just not in time).
    Two members with almost-identical display names ending up in two
    different, individually correct states on the same day is the
    concrete proof that attribution here is keyed by member_id, never by
    display name."""
    db_path, config_store = _seed_and_classify(tmp_path, channel_ids=(GAMMA,))
    config = config_store.get_channel_config(GAMMA)

    ledger = {r.member_id: r for r in build_ledger(GAMMA, date(2025, 6, 10), config, db_path=db_path)}
    assert "olivia.dupree" not in ledger, "her in-window update must make her a contributor, not a non-responder"
    assert ledger["olivia.dupont"].state == POSTED_NO_UPDATE, "her out-of-window post must still count as posted_no_update, not no_message"


# --- 5. A roster member who has left the tenant ----------------------------


def test_departed_tenant_member_is_tracked_from_the_roster_not_live_membership(tmp_path):
    """DIFF-DEPART-01: sofia.almeida is on proj-beta's config roster and
    posted through 2025-06-04, then nothing for the rest of the seeded
    window -- and Graph's own list_channel_members (seed/fixtures/members.json)
    no longer returns her at all. Participation must be computed over
    the config roster, not over live Teams membership: 2025-06-09 (a
    working day on which she posts nothing) must still carry a real
    no_message record for her, not a silent drop just because she is no
    longer a returned member."""
    _, _, members_by_channel = load_teams_fixtures()
    live_beta_member_ids = {m.id for m in members_by_channel.get(BETA, [])}
    assert "sofia.almeida" not in live_beta_member_ids, "the scenario requires her absence from live Graph membership"

    db_path, config_store = _seed_and_classify(tmp_path, channel_ids=(BETA,))
    config = config_store.get_channel_config(BETA)
    assert "sofia.almeida" in config.roster, "she must still be on the config roster despite leaving the tenant"

    ledger = {r.member_id: r for r in build_ledger(BETA, date(2025, 6, 9), config, db_path=db_path)}
    assert ledger["sofia.almeida"].state == NO_MESSAGE
