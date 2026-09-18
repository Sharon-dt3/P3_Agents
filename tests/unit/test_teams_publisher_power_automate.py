"""
PowerAutomateTeamsPublisher tests -- same httpx.MockTransport posture
test_teams_reader_graph.py already uses for the read-side real
adapter: no real network egress in this test file, but the actual
request-building/response-handling code is exercised for real.
"""

from __future__ import annotations

import json

import httpx
import pytest

from p1.adapters.teams_publisher_power_automate import (
    CHANNEL_POST,
    DIRECT_MESSAGE,
    PowerAutomatePublishError,
    PowerAutomateTeamsPublisher,
)

FLOW_URL = "https://prod-00.westus.logic.azure.com/workflows/fake/triggers/manual/paths/invoke"


def _publisher_with_transport(handler) -> PowerAutomateTeamsPublisher:
    publisher = PowerAutomateTeamsPublisher(flow_url=FLOW_URL)
    publisher._client = httpx.Client(transport=httpx.MockTransport(handler))
    return publisher


def test_post_channel_message_posts_the_expected_body_to_the_flow_url():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    publisher = _publisher_with_transport(handler)
    result = publisher.post_channel_message("c1", "hello channel")

    assert captured["url"] == FLOW_URL
    assert captured["body"] == {"action_type": CHANNEL_POST, "target": "c1", "content": "hello channel"}
    assert result == {"ok": True}


def test_post_direct_message_posts_the_expected_body_to_the_flow_url():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    publisher = _publisher_with_transport(handler)
    publisher.post_direct_message("bob", "hi bob")

    assert captured["body"] == {"action_type": DIRECT_MESSAGE, "target": "bob", "content": "hi bob"}


def test_a_non_2xx_response_raises_power_automate_publish_error():
    def handler(request):
        return httpx.Response(500, text="flow failed")

    publisher = _publisher_with_transport(handler)

    with pytest.raises(PowerAutomatePublishError, match="HTTP 500"):
        publisher.post_channel_message("c1", "hello")


def test_a_transport_failure_is_wrapped_in_power_automate_publish_error():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    publisher = _publisher_with_transport(handler)

    with pytest.raises(PowerAutomatePublishError, match="could not reach"):
        publisher.post_channel_message("c1", "hello")


def test_a_non_json_response_body_still_returns_a_dict():
    def handler(request):
        return httpx.Response(200, text="OK")

    publisher = _publisher_with_transport(handler)

    result = publisher.post_channel_message("c1", "hello")

    assert result == {"ok": True, "status_code": 200}
