import httpx
import pytest

from p1.adapters.teams_reader import DeltaTokenExpiredError
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
