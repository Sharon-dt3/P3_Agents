# Copilot Studio custom connector contract (CHN-25)

This is the backend contract a Copilot Studio custom connector would
bind its actions to, once this programme has a live Microsoft tenant to
deploy into. It is not deployed anywhere -- there is no live Copilot
Studio bot or Dataverse table behind this repo. What exists instead,
and is real and tested, is the connector's actual backend
implementation: `src/p1/adapters/copilot_studio_connector.py`. Each
action below is one function in that module, taking and returning a
plain JSON-shaped dict, calling straight into `p1.approval.service` or
`p1.config.loader.ChannelConfigStore` -- the exact same functions the
Streamlit fallback (`app/approval_dashboard.py`) calls directly.
`tests/unit/test_copilot_studio_connector.py` proves the two produce
identical audit records; there is nothing about how a connector would
call these functions that this repo cannot already exercise.

In production, `approver_id`/`updated_by` on every action below would
be supplied by Copilot Studio from the Teams user's own identity (its
built-in `User.Id`/`User.DisplayName` context variables), never a value
an adaptive card's own submitted JSON could set -- there is no live
Teams/Entra identity here to bind that to, so every test instead passes
it explicitly, the same way every other test in this repo does.

## Actions

### `list_pending_approvals`
Handler: `handle_list_pending_approvals(request)`
Request: `{}`
Response: `{"approvals": [{"proposal_id", "type", "channel_id", "created_at", "summary"}, ...]}`

### `approve`
Handler: `handle_approve(request)`
Request: `{"proposal_id": str, "approver_id": str}`
Response: `{"proposal_id": str, "outcome": "sent" | "refused" | "send_failed", "detail": str}`
Card: `cards/pending_nudge_card.json`, `cards/pending_escalation_card.json`, `cards/pending_publish_card.json` (the "Approve" action)

### `reject`
Handler: `handle_reject(request)`
Request: `{"proposal_id": str, "approver_id": str}`
Response: `{"proposal_id": str, "outcome": "rejected" | "refused", "detail": str}`
Card: same three cards (the "Reject" action)

### `update_channel_config`
Handler: `handle_update_channel_config(request)`
Request: `{"channel_id": str, "updated_by": str}`, plus any of:
- `"roster"` (`list[str]`) or `"roster_csv"` (`str`, comma-separated member IDs -- what an Adaptive Card's `Input.Text` can actually submit, since Adaptive Cards has no list-input control)
- `"update_window_start"` / `"update_window_end"` (`"HH:MM:SS"`)
- `"exceptions"` (`list[{"member_id", "reason"}]`) or `"exceptions_csv"` (`str`, `"member_id:reason,member_id:reason"`)

A field left out of the request is left unchanged. Response:
`{"channel_id", "roster", "update_window_start", "update_window_end", "exceptions", "version"}`
(the channel's full config for these fields, after the write).
Card: `cards/channel_config_form_card.json`

## Dataverse table mapping

One row per channel, mirroring `channel_config`'s own columns exactly
(`roster`, `update_window_start`, `update_window_end`, `exceptions`,
`version`, `updated_at`, plus every other `ChannelConfig` field for
read visibility in the Copilot Studio canvas). Dataverse is presented
to the channel owner as the editable surface; `update_channel_config()`
remains the single write path regardless -- a production sync between
Dataverse and `channel_config` would call it exactly the way this
connector's own handler does, never write to SQLite directly, for the
same reason there is no second, independent validation path anywhere
else in this row's design.

## What is real vs. represented here

| Piece | Status |
|---|---|
| `copilot_studio_connector.py` handlers | Real code, tested directly (never through a live connector) |
| Adaptive card JSON templates | Real, valid Adaptive Card 1.5 documents; their `Action.Submit` data is checked against each handler's actual request shape in `test_copilot_studio_connector.py`, so this table cannot silently drift from the code |
| The Copilot Studio bot itself (topics, canvas, publish) | Not built -- requires a Microsoft tenant this repo does not have |
| The Dataverse table itself | Not built -- same reason; `channel_config` (SQLite) plays its role here |
| `app/approval_dashboard.py` (Streamlit) | Real, tested, runnable fallback -- the actually-exercised surface for the demo |
