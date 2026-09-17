"""
CHN-10's own acceptance test, run against the real CHN-06/07 fixtures:
THIN END-TO-END SLICE -- ingest real fixture messages, run them through
the real CHN-08 rules and CHN-09 classifier (a scripted gateway stands
in for the model itself; everything upstream of it -- ingestion, rule
evaluation, the classify/persist write path -- is the genuine pipeline),
then confirm the ledger reports the reaction-only, chatter-only and
on-leave members in the correct state, per DIFF-REACTION-01,
DIFF-CHATTER-01 and DIFF-LEAVE-01 in seed/fixtures/labels.csv.
"""

from datetime import date

from p1.adapters.fixtures import load_teams_fixtures
from p1.config.loader import ChannelConfigStore
from p1.detection.pipeline import classify_and_persist
from p1.llm.gateway import LLMResponse
from p1.participation.ledger import EXCLUDED, NO_MESSAGE, POSTED_NO_UPDATE, build_ledger
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore

ALPHA = "19:proj-alpha@thread.tacv2"
GAMMA = "19:proj-gamma@thread.tacv2"

# A Thursday within the seeded window; an ordinary working day for both
# channels, and the day fatima.hassan's DIFF-CHATTER-01 message
# ("Sounds good.") happens to land on.
TEST_DAY = date(2025, 6, 5)


class ScriptedGateway:
    """Responds by matching known message content, not call order or
    count: CHN-08's rules decide how many messages even reach the model
    and in what order, so the test cannot know that in advance.
    Anything not specifically scripted defaults to "update" -- safe here
    because the fixture generator's ordinary organic traffic really is
    update/question/blocker-shaped text, and all three of those labels
    count as a contributor exactly like "update" does for CHN-10's
    purposes, so which specific one of the three a default guess lands
    on never affects this test's assertions."""

    def __init__(self, canned: dict[str, str], default: str = '{"label": "update", "confidence": 0.9}'):
        self._canned = canned
        self._default = default
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        for snippet, response in self._canned.items():
            if snippet in prompt:
                text = response
                break
        else:
            text = self._default
        return LLMResponse(
            text=text, provider="anthropic", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


def _seed_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    ChannelConfigStore().sync_to_db(db_path)

    _, _, messages_by_channel = load_teams_fixtures()
    all_messages = [m for channel_id in (ALPHA, GAMMA) for m in messages_by_channel.get(channel_id, [])]

    # members table needs a row for every author FK the messages table
    # will reference. This deliberately does not rely on the fixtures'
    # own list_channel_members() data (members.json), since sofia.almeida
    # (DIFF-DEPART-01, on proj-beta not proj-alpha, but the same
    # principle applies) has real posting history despite being absent
    # from Teams-side membership -- the messages table's FK only cares
    # who actually authored a message, not who is currently a member.
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
    return db_path, all_messages


def test_reaction_only_chatter_only_and_on_leave_members_each_land_correctly(tmp_path):
    db_path, all_messages = _seed_db(tmp_path)

    config_store = ChannelConfigStore()
    alpha_config = config_store.get_channel_config(ALPHA)
    gamma_config = config_store.get_channel_config(GAMMA)

    gateway = ScriptedGateway({"Sounds good.": '{"label": "chatter", "confidence": 0.9}'})

    alpha_messages = [m for m in all_messages if m.channel_id == ALPHA]
    gamma_messages = [m for m in all_messages if m.channel_id == GAMMA]

    classify_and_persist(alpha_messages, alpha_config, gateway, db_path=db_path)
    # proj-gamma is not allowlisted (config/channels/proj-gamma.yaml) --
    # in the real pipeline CHN-04's scope gate means it never reaches
    # this point at all. Classified directly here anyway: neither the
    # rule engine nor the classifier has any opinion on scope (see
    # test_update_detection_against_fixtures.py's identical treatment of
    # DIFF-DEL-03), and aisha.rahman's *absence* of any message needs
    # gamma's real message set present to be a meaningful check at all.
    classify_and_persist(gamma_messages, gamma_config, gateway, db_path=db_path)

    alpha_ledger = {r.member_id: r for r in build_ledger(ALPHA, TEST_DAY, alpha_config, db_path=db_path)}
    gamma_ledger = {r.member_id: r for r in build_ledger(GAMMA, TEST_DAY, gamma_config, db_path=db_path)}

    # DIFF-CHATTER-01: fatima.hassan posts, but every message of hers is
    # chatter -- never credited as a real update.
    assert alpha_ledger["fatima.hassan"].state == POSTED_NO_UPDATE

    # DIFF-LEAVE-01: liam.oconnor must appear as excluded, never as a
    # plain non-responder -- he is on proj-alpha's exceptions list for
    # the entire seeded window and organically posts nothing.
    assert alpha_ledger["liam.oconnor"].state == EXCLUDED

    # DIFF-REACTION-01: aisha.rahman generates zero messages for the
    # entire window and is not on any exceptions list -- a genuine
    # non-responder, never excused.
    assert gamma_ledger["aisha.rahman"].state == NO_MESSAGE
