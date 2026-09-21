import httpx
import pytest

from p1.adapters.teams_reader import DeltaLinkRejectedError, DeltaTokenExpiredError
from p1.adapters.teams_reader_graph import GraphTeamsReader, GraphThrottledError


def _reader_with_transport(handler) -> GraphTeamsReader:
    reader = GraphTeamsReader(access_token="fake-token", team_id="team-1")
    reader._client = httpx.Client(
        base_url="https://graph.microsoft.com/v1.0",
        transport=httpx.MockTransport(handler),
    )
    return reader


def test_list_messages_sets_has_more_when_nextlink_present():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "value": [],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/teams/team-1/channels/c1/messages/delta?$skiptoken=abc",
            },
        )

    reader = _reader_with_transport(handler)
    page = reader.list_messages("c1")
    assert page.has_more is True
    assert "skiptoken" in page.delta_token


def test_list_messages_has_more_false_when_deltalink_present():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "value": [],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/teams/team-1/channels/c1/messages/delta?$deltatoken=xyz",
            },
        )

    reader = _reader_with_transport(handler)
    page = reader.list_messages("c1")
    assert page.has_more is False
    assert "deltatoken" in page.delta_token


def test_list_messages_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("p1.adapters.teams_reader_graph.time.sleep", lambda s: None)
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json={"value": [], "@odata.deltaLink": "https://x/delta?token=1"})

    reader = _reader_with_transport(handler)
    page = reader.list_messages("c1")
    assert calls["count"] == 2
    assert page.has_more is False


def test_list_messages_raises_after_exhausting_throttle_retries(monkeypatch):
    monkeypatch.setattr("p1.adapters.teams_reader_graph.time.sleep", lambda s: None)

    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "0"}, json={})

    reader = _reader_with_transport(handler)
    with pytest.raises(GraphThrottledError):
        reader.list_messages("c1")


def test_list_messages_raises_on_expired_delta_token():
    def handler(request):
        return httpx.Response(410, json={})

    reader = _reader_with_transport(handler)
    with pytest.raises(DeltaTokenExpiredError):
        reader.list_messages("c1", delta_token="https://x/delta?token=expired")


def test_list_messages_raises_delta_link_rejected_on_known_graph_bug():
    # Reproduces 2026-09-20's real Teams-agent-test failure verbatim:
    # Graph accepts the nextLink it just handed back as a *request*
    # (200 would follow the value/nextLink shape below), but here it
    # comes back 400 with this exact error text -- a known, open Graph
    # bug (see DeltaLinkRejectedError's docstring), not a malformed
    # request on our side.
    def handler(request):
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "BadRequest",
                    "message": "Parameter 'DeltaToken' not supported for this request.",
                }
            },
        )

    reader = _reader_with_transport(handler)
    with pytest.raises(DeltaLinkRejectedError):
        reader.list_messages("c1", delta_token="https://x/delta?$skiptoken=abc")


def test_list_messages_unrelated_400_still_raises_http_status_error():
    # A real, unrelated 400 (not this specific Graph bug's error text)
    # must still surface normally -- this fix is narrowly matched on the
    # actual error text, not "any 400 while following a token".
    def handler(request):
        return httpx.Response(400, json={"error": {"code": "BadRequest", "message": "Something else entirely."}})

    reader = _reader_with_transport(handler)
    with pytest.raises(httpx.HTTPStatusError):
        reader.list_messages("c1", delta_token="https://x/delta?$skiptoken=abc")


def test_list_replies_raises_key_error_for_a_message_never_seen_by_this_instance():
    # The exact failure this class's own _resolve_channel_id has always
    # raised for -- reproduced here directly, without ScopeGate, to
    # isolate that this reader's cache really is independent of any
    # caller. See note_known_message()'s own docstring for why a fresh
    # instance (e.g. a new process tick) starts with this cache empty
    # even for a message_id it "should" already know.
    reader = _reader_with_transport(lambda request: httpx.Response(200, json={"value": []}))
    with pytest.raises(KeyError):
        reader.list_replies("m1")


def test_note_known_message_lets_list_replies_resolve_without_calling_list_messages_first():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"value": []})

    reader = _reader_with_transport(handler)
    reader.note_known_message("m1", "c1")

    reader.list_replies("m1")  # does not raise

    assert calls == ["https://graph.microsoft.com/v1.0/teams/team-1/channels/c1/messages/m1/replies"]


def test_parse_message_flags_system_message():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "m1",
                        "createdDateTime": "2026-09-01T09:00:00Z",
                        "messageType": "systemEventMessage",
                        "body": {"content": "X joined the channel"},
                    }
                ],
                "@odata.deltaLink": "https://x/delta?token=1",
            },
        )

    reader = _reader_with_transport(handler)
    page = reader.list_messages("c1")
    assert page.messages[0].is_system is True
