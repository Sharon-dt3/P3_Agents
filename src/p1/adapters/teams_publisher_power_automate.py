"""
PowerAutomateTeamsPublisher (CHN-22): the real implementation behind
the identical TeamsPublisher interface, posting via an HTTP-triggered
Power Automate flow acting as the flow bot.

NOT YET EXERCISED AGAINST A LIVE FLOW -- no Power Automate flow has
been provisioned yet (see DECISION_LOG.md, same status GraphTeamsReader
already carries for CHN-01/CHN-03's read side). Written against the
documented shape of an HTTP-triggered flow (one POST URL, one JSON
body, distinguished by an action_type field) so it's ready to wire in
by setting POWER_AUTOMATE_FLOW_URL and switching TEAMS_PUBLISHER_MODE;
the scored path (harness, CI, demo) never depends on this class --
LogPublisher is what every test, eval and demo actually uses.

Graph application permission to SEND channel messages is restricted
(this row's own rationale), so the flow itself -- not this Python
process -- holds whatever credential actually posts as the flow bot;
this class only knows the flow's one trigger URL, never a Graph token,
which is what keeps read and write permissions cleanly separated at
the code level too, not just at the Azure AD app-registration level.
"""

from __future__ import annotations

import httpx

from p1.adapters.teams_publisher import TeamsPublisher

CHANNEL_POST = "channel_post"
DIRECT_MESSAGE = "direct_message"


class PowerAutomatePublishError(Exception):
    """Raised whenever the flow could not be reached, or responded with
    a non-2xx status -- a transport-level concern specific to calling a
    real HTTP-triggered flow, not part of the TeamsPublisher interface
    contract. Never raised for a refused send (SPN-09's guarded_send()
    is what decides whether this class is ever called at all)."""


class PowerAutomateTeamsPublisher(TeamsPublisher):
    def __init__(self, flow_url: str, *, timeout: float = 10.0, client: httpx.Client | None = None) -> None:
        self._flow_url = flow_url
        self._client = client or httpx.Client(timeout=timeout)

    def post_channel_message(self, channel_id: str, content: str) -> dict:
        return self._post(action_type=CHANNEL_POST, target=channel_id, content=content)

    def post_direct_message(self, member_id: str, content: str) -> dict:
        return self._post(action_type=DIRECT_MESSAGE, target=member_id, content=content)

    def _post(self, *, action_type: str, target: str, content: str) -> dict:
        try:
            resp = self._client.post(
                self._flow_url,
                json={"action_type": action_type, "target": target, "content": content},
            )
        except httpx.RequestError as exc:
            raise PowerAutomatePublishError(
                f"could not reach the Power Automate flow at {self._flow_url!r}: {type(exc).__name__}: {exc}"
            ) from exc

        if resp.status_code >= 400:
            raise PowerAutomatePublishError(
                f"Power Automate flow at {self._flow_url!r} returned HTTP {resp.status_code}: {resp.text}"
            )

        try:
            return resp.json()
        except ValueError:
            return {"ok": True, "status_code": resp.status_code}
