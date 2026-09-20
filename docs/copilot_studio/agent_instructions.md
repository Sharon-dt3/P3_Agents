# Copilot Studio agent instructions (CHN-25, closing the gap)

This is the piece `DECISION_LOG.md`'s 2026-09-18 "solution-aware and
wired into the live agent" entry names as **not done, on purpose**: the
5 Tools (Health, List Pending Approvals, Approve, Reject, Update
Channel Config) are attached to the live "P1 Channel Intelligence"
agent and confirmed reachable, but the agent was never taught *when* or
*how* to call them, and the per-channel config surface's Dataverse
question was left open. Both are closed below -- as text to paste into
the Copilot Studio maker portal, since neither is reachable as
importable Python (see `connector_contract.md`'s own note on this).

## 0. The Dataverse table: not needed, and building one would be a regression

`connector_contract.md`'s own "Dataverse table mapping" section already
answered this: *"Dataverse is presented to the channel owner as the
editable surface; `update_channel_config()` remains the single write
path regardless... `channel_config` (SQLite) plays its role here."*
That decision is still correct, and confirmed live: the "Update Channel
Config" Tool already calls the real, live `ChannelConfigStore`
(SQLite-backed `channel_config` table) through `copilot_studio_api.py`,
which is already attached to the agent and already proven reachable
(`health_health_get` returned 200 in the last verified session).

A literal Dataverse table would not add a capability -- it would add a
**second copy** of the same roster/window/exceptions data that
`channel_config` already holds, which is exactly what
`config/loader.py`'s own docstring and this row's design rule forbid
("reconciled, not duplicated"). Any sync job written to keep a
Dataverse table in step with `channel_config` would itself have to call
`update_channel_config()` to write anything back -- so it would sit
*beside* the real write path, never replace it, purely so a channel
owner could see a grid view outside chat.

**Recommendation:** treat CHN-25's config surface as closed via the
existing Tool, not a new Dataverse table. The one new thing below (the
"peek" pattern in step 2) is what actually closes the "how does a
channel owner even see their current config" question without adding a
duplicate store. If a visual grid (rather than a conversational
answer) is wanted later, that's a genuinely separate, optional
follow-on -- not a blocker to calling the Copilot Studio surface done.

## 1. General instructions (paste into the agent's "Instructions" field)

```
You are the P1 Channel Intelligence assistant. You help a Teams channel
owner review pending approvals (nudges, escalations, and first
publishes) and maintain their channel's roster, update window, and
exceptions list -- all through your 5 connected tools, never by
inventing an answer.

Hard rules, never relaxed:

1. Never fabricate a proposal_id, channel_id, or approver identity.
   A proposal_id may only be one that came back from your own
   "List Pending Approvals" call earlier in this conversation. If you
   don't have one, call "List Pending Approvals" first.
2. For approver_id (Approve, Reject) and updated_by (Update Channel
   Config), always use the current Teams user's own identity, supplied
   to you as a system value -- never a name or ID the user typed in
   chat, and never a placeholder.
3. Never claim an approval, rejection, or config change succeeded
   unless the tool's own response says so. Every one of these tools
   returns either a "detail" field or the changed values themselves --
   read it back to the user, in plain language, instead of assuming
   success from the fact that the call didn't error.
4. If a tool call fails or comes back "refused", tell the user exactly
   what it said (e.g. "this is this person's first-ever nudge, so it
   needs a human approval before it can send" or "that proposal was
   already applied") rather than retrying silently or guessing why.
5. You never draft the *content* of a nudge, escalation, or digest --
   that text is already fixed by the time it reaches you. Your job is
   only to surface it for a decision (approve/reject) or to answer
   config questions, never to rewrite or summarize it differently than
   the tool returned it.

Typical flow:

- "What's waiting for my approval?" / "Anything pending?" -> call
  List Pending Approvals. For each item, tell the user its type
  (nudge / escalation / first publish), which channel, when it was
  created, and its summary, and ask whether to approve or reject it.
- "Approve it" / "Reject it" (after the above) -> call Approve or
  Reject with that item's proposal_id and the current user's identity.
  Report back the outcome and detail exactly as returned.
- "What's my current roster / update window / exceptions list?" ->
  call Update Channel Config with ONLY channel_id and updated_by set
  (leave roster, update_window_start, update_window_end, and
  exceptions blank). This returns the channel's current config and
  changes nothing -- it is the way to answer a read-only question with
  this tool, since there is no separate "read config" tool.
- "Add X to the roster" / "Change the update window to..." /
  "Add an exception for..." -> gather exactly the field(s) the user
  wants changed, then call Update Channel Config with only those
  fields set (channel_id and updated_by always included; leave every
  other field blank so it stays unchanged). Confirm back using the
  response's own values, not what the user asked for verbatim, since
  the response is what was actually saved after validation.
- "Is the system working?" / troubleshooting a stuck request -> call
  Health. Do not surface this to the user proactively; it is a
  diagnostic, not a normal part of the conversation.

Roster and exceptions are entered as comma-separated text (there is no
list input in Teams), for example:
roster: "alice@contoso.com, bob@contoso.com"
exceptions: "alice@contoso.com:on leave through Oct 3, bob@contoso.com:parental leave"
Pass these through as roster_csv / exceptions_csv exactly as the user
gave them, comma-separated -- do not try to reformat them into a JSON
array yourself.
```

## 2. Per-tool descriptions (paste into each Tool's own description field)

Copilot Studio's generative orchestration leans on each Tool's own
description -- separate from the general instructions above -- to
decide *which* tool to call for a given utterance. Set these exactly:

**Health**
> Checks whether the P1 Channel Intelligence backend is reachable and
> configured. Use only for a system-status / connectivity check, never
> to answer a question about channel content, approvals, or config.

**List Pending Approvals**
> Returns every proposal (nudge, escalation, or first channel publish)
> currently awaiting human approval, across all channels: each item's
> proposal_id, type, channel_id, created_at, and a plain-language
> summary. Call this whenever the user asks what's pending, what needs
> review, or wants to approve or reject something -- always before
> Approve or Reject, since proposal_id must come from here.

**Approve**
> Approves one specific pending proposal (identified by proposal_id)
> and sends it immediately. Requires a proposal_id that came from a
> prior List Pending Approvals call in this conversation, and the
> current user's own identity as approver_id. Returns outcome (sent /
> refused / send_failed) and a detail string explaining it -- always
> relay both to the user.

**Reject**
> Rejects one specific pending proposal (identified by proposal_id)
> without sending it. Same proposal_id/approver_id requirements as
> Approve.

**Update Channel Config**
> Reads or changes one channel's roster, update window, or exceptions
> list. Called with only channel_id and updated_by, it returns the
> CURRENT config unchanged -- use this to answer "what's my roster /
> window / exceptions" questions. Called with roster_csv,
> update_window_start, update_window_end, and/or exceptions_csv, it
> changes only the fields given, effective immediately with no deploy,
> and returns the full saved config. updated_by must be the current
> user's own identity.

## 3. Binding approver_id / updated_by to the real Teams identity

`connector_contract.md` already flags this as the one thing that
cannot be tested from this repo: in production, `approver_id` and
`updated_by` must come from Copilot Studio's own knowledge of who is
chatting, never from a value the model fills in from conversation
text (which a user could talk it into spoofing).

In the Copilot Studio maker portal, when mapping each Tool's inputs
(the step after "Add a tool"), set `approver_id` (Approve, Reject) and
`updated_by` (Update Channel Config) to the agent's built-in
current-user value -- listed under the System/User category in the
input-mapping picker (exposed as the user's Entra object id or UPN,
depending on what your tenant's picker offers) -- rather than "Ask the
user" or leaving it for the model to fill in. The exact label varies by
Copilot Studio release, so confirm which one resolves to the real
signed-in Teams user in your environment before relying on it; if
none is available, this stays a disclosed scope cut exactly as
`connector_contract.md` already states, and every approval in the
meantime should be double-checked against the Teams thread it came
from.

## 4. Before testing: the API has to actually be running and reachable

The agent's Tools call `copilot_studio_api.py` over HTTP -- this is a
separate process from `live_runner_p1_agent_test.py` and is **not**
started automatically. Before any live Copilot Studio test:

```
make copilot-api   # uv run uvicorn p1.api.copilot_studio_api:app --reload
```

and whatever tunnel (ngrok or similar) makes that local port reachable
from Microsoft's cloud must also be up, matching the URL the "P1
Channel Approvals" custom connector already points at. If that tunnel
was only started for a prior working session, it has almost certainly
expired (ngrok's free-tier URLs are ephemeral per run) -- check the
connector's configured host against whatever tunnel URL is live right
now before testing, and re-import/update the connector's host if it
has drifted.

## 5. Live test checklist (real Teams conversation with the agent)

Run these against the actual "P1 Channel Intelligence" agent in Teams,
not the API directly, once steps 1-4 are done:

1. Type "is the system working?" -> expect the agent to call Health
   and report back reachable + configured, without volunteering this
   information unprompted on other questions.
2. Type "what's pending for approval?" -> expect a plain-language list
   (possibly zero items, which is itself a correct, honest answer) --
   compare against `SELECT status, type, channel_id FROM proposals
   WHERE status='pending'` on the real `data/p1_live.db` to confirm it
   isn't inventing or omitting anything.
3. If anything is pending, type "approve the first one" -> expect the
   agent to call Approve with that exact proposal_id and report back
   the real outcome/detail, and expect the same proposal to now show
   `status='applied'` in the DB (or `pending` again with a `refused`
   detail, if it was a first-ever send needing this same approval).
4. Type "what's my current roster for p1-agent-test?" -> expect the
   agent to call Update Channel Config with no optional fields and
   read back the real roster -- confirm it exactly matches
   `get_effective_config("p1-agent-test").roster` and that no `audit`
   row was written for this call (it's a read, not a write).
5. Type "add <a real test member id> to the exceptions list for
   p1-agent-test, reason: testing" -> expect a confirmation using the
   tool's own returned values, and confirm one new `audit` row exists
   with `action='channel_config.updated'` and the expected before/after
   in its `details` JSON.
6. Type "remove that exception" (or otherwise revert) to leave the
   channel's real config as it was before this test, since step 5's
   change is a genuine live write to `p1-agent-test`'s config, the same
   channel tonight's digest test is using.

Each of these is something no unit test can prove, since orchestration
(which utterance triggers which tool, and how the model narrates the
result) lives entirely in Copilot Studio's own portal state -- this
checklist is what actually proves "wired and runs as expected" for
this row, the same way the FTS5/scope-gate live checks already proved
the ingestion side.
