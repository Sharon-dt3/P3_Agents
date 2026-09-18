# P1 — Teams Channel Intelligence

Reads allowlisted Microsoft Teams channels, tracks who has and hasn't posted an update against a per-channel roster, and publishes daily and weekly digests. Part of the Incubation Pod Three-Agent Delivery Plan (P1 of P1/P2/P3).

**Status:** P1's core build (CHN-01 through CHN-29) is complete against the mock Teams adapter, all 34 committed golden-case metrics passing (see Eval results below). The one open item is external, not code: CHN-01's live Graph credential is still awaiting tenant admin consent, so every capability below runs against `MockTeamsReader` today (see Status and Key decisions).

## Prerequisites

- uv (Python package/project manager): https://docs.astral.sh/uv/
- Python 3.10+ (uv manages this automatically)
- Git

## Quick start

    git clone https://github.com/Sharon-dt3/P3_Agents.git
    cd P3_Agents
    cp .env.example .env   # fill in real values before running against live services
    make install            # uv sync -- installs all dependencies
    make seed                # builds a fresh SQLite DB from the committed migrations
    make run                  # runs the real full flow (mock adapter) end to end -- see below

Run tests and lint:

    make test
    make lint

`make seed` only runs the SQLite migrations (SPN-04) -- it does not regenerate the seed fixture data. That data (3 channels, 10 working days, 15 planted difficulties from source sheet 06 plus 3 more added by CHN-28) is deterministic (seed=42) and already committed under `seed/fixtures/`; it was produced once by `uv run python scripts/generate_seed_fixtures.py` and never needs to be regenerated unless the fixture generator itself changes.

`make run` (CHN-31) calls `scripts/run_daily.py`, which now runs the real full flow, once, end to end: ingest the committed mock fixtures for both allowlisted channels, run CHN-08/09 detection, build CHN-10's participation ledger, and generate and publish CHN-13/17's daily digest -- through the exact same `p1.publishing.daily_job.run_daily_digest_job` every unit test, GC6, and CHN-24/27's own real runs already exercise, never a second, separately maintained demo path. It requires only a real `ANTHROPIC_API_KEY` in `.env` (the model writes the digest's prose from already-computed facts -- see `p1.reporting.daily_summary`'s own docstring); it needs no Graph/tenant credential at all, since `TEAMS_READER_MODE` and `TEAMS_PUBLISHER_MODE` both default to mock. A channel's very first publish is always left pending for a human to approve (CHN-17's own rule), so a fresh clean-clone run reports `awaiting_approval` for both channels -- that is the correct, honest first result, not a failure.

This is a one-shot manual run, not a standalone always-on process: wiring `p1.publishing.scheduler.build_scheduler`'s clock into a long-running per-channel scheduler is still real, undone work -- see the Status table's C7 row. Every test, the eval harness, and CHN-24/27's own real runs all call `run_daily_digest_job` directly, same as this script now does.

## Project structure

    src/p1/             application code (adapters, detection, participation, grounding, approval, publishing, ...)
    tests/unit/         unit tests
    scripts/            entry-point scripts used by the Makefile
    docs/               implementation plan and other project documentation
    .github/workflows/  CI (lint + test on every push)

See docs/P1_IMPLEMENTATION_PLAN.md for P1's architecture and day-by-day build plan.

See docs/MASTER_IMPLEMENTATION_PLAN.md for the full six-week, three-agent programme plan (P1 -> P2 -> P3), reconciled against all nine source sheets. That document is a dated snapshot (as of 2026-09-17, before CHN-08 onward was built) rather than a living status page -- this README's Status section below is the current, code-verified picture.

## Architecture

**Read path:** `TeamsReader` (an interface -- `MockTeamsReader` today, `GraphTeamsReader` once CHN-01's credential lands, chosen by `p1.adapters.factory.get_teams_reader()`) is wrapped by `ScopedTeamsReader` (`p1.governance.scope_gate`), which enforces the channel allowlist *at the adapter boundary* -- a chat or a non-allowlisted channel is refused before any capability code ever sees it, and every refusal is logged to `audit`. `p1.ingestion.sync` drains delta pages (paging, 429 backoff, delta-token-expiry recovery) into `MessageStore`. `p1.detection.rules` (CHN-08, no model call) settles the clear cases; anything left unsettled goes to `p1.detection.classifier` (CHN-09, schema-forced) -- the model never sees a message a rule already decided. `p1.participation.ledger` (CHN-10) turns the roster and the day's classifications into the three honest non-responder states. `p1.reporting.facts` + `p1.reporting.daily_summary` / `weekly_summary` compute every figure in code and ask the model only for prose, verified line-by-line against the message store by `p1.grounding.kernel` before anything is kept.

**Write path:** every outbound action (a digest publish, a nudge, an escalation) first creates a `p1.approval.proposals.Proposal` (state `PENDING`). `p1.approval.write_guard.guarded_send()` is the *one* gate every send goes through, called from `daily_job.py`, `nudge_job.py` and `escalation_job.py` alike (proven never bypassed by GC8) -- it re-confirms `APPROVED` immediately before sending, refuses and logs anything else, and marks the proposal `APPLIED` only after a real send succeeds. A person's or channel's *first-ever* send is left `PENDING` for a human to approve (via `p1.approval.service`, reachable from the Copilot Studio connector or the Streamlit fallback `app/approval_dashboard.py` -- both call the identical service functions, proven by a dedicated equivalence test); afterward it auto-approves within its own cap. The actual send goes through `p1.adapters.teams_publisher` (`LogPublisher` for every test/eval/demo today; `PowerAutomateTeamsPublisher` once a flow is provisioned).

**Graph permission model actually used:** delegated `ChannelMessage.Read.All` via a dedicated service account added as a member of each allowlisted channel (CHN-01's "Option A"), not the tenant-wide application permission -- a lower admin-consent bar and a narrower blast radius (see Key decisions). Read and write are cleanly separated on purpose: outbound messages never go through a Graph *send* permission at all, only through the Power Automate flow bot, so the read credential can never itself post anything.

## Status

One row per capability from `docs/MASTER_IMPLEMENTATION_PLAN.md`'s own traceability table (§ "Cap"). Every "Verify" cell names a real file in this repo -- open it to check the claim yourself.

| Cap | Priority | Capability | Status | Verify |
|---|---|---|---|---|
| C1 | MUST | Channel registry and per-channel configuration | **Done** | `config/channels/*.yaml` (3 real configs); `src/p1/config/loader.py` (`ChannelConfigStore`, `get_effective_config`, `update_channel_config`); GC12 in `src/p1/eval/chn24_cases.py` (changing the roster and window moves the non-responder set) |
| C2 | MUST | Teams ingestion via Graph with delta tracking | **Partial** -- code done, live credential pending | `src/p1/adapters/teams_reader_graph.py`, `src/p1/ingestion/sync.py`; GC10 in `src/p1/eval/chn12_cases.py`. Never run against a real tenant -- see CHN-01 in Key decisions |
| C3 | MUST | Scope gate -- allowlist only, chats never read | **Done** | `src/p1/governance/scope_gate.py`; GC5 in `src/p1/eval/chn12_cases.py` |
| C4 | MUST | Update detection -- rules then classifier | **Done** | `src/p1/detection/rules.py`, `src/p1/detection/classifier.py`; GC1 in `src/p1/eval/chn11_cases.py` (7 of CHN-08's 8 rules have a real ground-truth example as of CHN-28; `non_working_day` is proven instead at the participation-ledger level by `tests/unit/test_participation_edge_cases.py`, CHN-29) |
| C5 | MUST | Participation ledger and non-responder detection | **Done** | `src/p1/participation/ledger.py`; GC2 in `src/p1/eval/chn11_cases.py`; `tests/unit/test_participation_edge_cases.py` (CHN-29's edge-case pass) |
| C6 | MUST | Per-channel daily summary with grounding | **Done** | `src/p1/reporting/daily_summary.py`, `src/p1/grounding/kernel.py`; GC3/GC4 in `src/p1/eval/chn15_cases.py`, GC9 in `src/p1/eval/chn16_cases.py` |
| C7 | MUST | Scheduled daily and weekly publishing | **Done** (code + tests; `make run` (CHN-31) runs the real job once end to end; no standalone always-on process yet -- see Quick start) | `src/p1/publishing/scheduler.py`, `src/p1/publishing/daily_job.py`, `scripts/run_daily.py`; GC6 in `src/p1/eval/chn18_cases.py`; `tests/unit/test_run_daily_full_flow.py` |
| C8 | MUST | Approval gate and audit for outbound actions | **Done** | `src/p1/approval/proposals.py`, `src/p1/approval/write_guard.py`; GC8 in `src/p1/eval/chn24_cases.py` |
| C9 | SHOULD | Weekly roll-up with participation trend | **Done** | `src/p1/reporting/weekly_summary.py`; GC11 in `src/p1/eval/chn20_cases.py` |
| C10 | SHOULD | Nudge non-responders, opt-in and capped | **Done** | `src/p1/nudges/nudge_job.py`; GC7 in `src/p1/eval/chn24_cases.py` |
| C11 | SHOULD | Escalate to the channel owner | **Done** | `src/p1/escalations/escalation_job.py`; GC7 in `src/p1/eval/chn24_cases.py` |
| C12 | SHOULD | Emit versioned outcome record | **Done** | `src/p1/contracts/outcome_record.py`, `schema/outcome_record.v1.schema.json`; `tests/unit/test_outcome_record.py`, `test_outcome_record_schema.py` |
| C13 | COULD | Cross-channel question answering | **Not built** (not planned) | -- |
| C14 | COULD | Per-person digest | **Not built** (not planned) | -- |

Two more surfaces sit alongside C1 and C8 but aren't their own numbered capability: the **Copilot Studio approvals/config UI** (CHN-25) is a documented, tested connector contract over the exact same `p1.approval.service` every other surface calls -- `src/p1/adapters/copilot_studio_connector.py`, `docs/copilot_studio/connector_contract.md`, `tests/unit/test_copilot_studio_connector.py` -- plus a real, internet-hostable HTTP API in front of it (`src/p1/api/copilot_studio_api.py`, `tests/unit/test_copilot_studio_api.py` -- see "Copilot Studio custom connector API" below), but no Copilot Studio agent or Dataverse table has actually been created yet (both need a human in the Power Platform maker portal, plus a decision on where the API is hosted so Microsoft's cloud can reach it); the scored fallback, a real Streamlit app (`app/approval_dashboard.py`, `tests/unit/test_approval_dashboard_app.py`), is what's actually exercised end-to-end today. And the **eval harness itself** (SPN-07) is what every GC reference above runs through: `src/p1/eval/cases.py`, `runner.py`, `registrations.py`, driven by `scripts/run_eval.py` -- see Eval results below.

## Key decisions and scope cuts

**CHN-01 — the Graph permission model.** Delegated `ChannelMessage.Read.All` via a dedicated service account added as a member of each allowlisted channel ("Option A"), not the tenant-wide application permission ("Option B"). Option A needed only tenant admin consent; Option B would also have needed Microsoft's Teams-export protected-API approval and may be metered, for a broader (tenant-wide) grant than this agent actually needs. Full detail, including the Azure app registration and the outstanding consent request, is in `DECISION_LOG.md`'s CHN-01 entry. Status: admin consent is still pending, so `GraphTeamsReader` -- written and unit-tested against a mocked Graph API -- has never read a real message; per Gate G0b's own rule, every capability above was built and proven against `MockTeamsReader` regardless, and needs only a config flip (`TEAMS_READER_MODE=graph`, plus `GRAPH_ACCESS_TOKEN`/`GRAPH_TEAM_ID` -- see `src/p1/adapters/factory.py`) once consent lands, no agent-logic changes. The device-code sign-in script this entry's own "next step" named was, for a while, never actually built -- see "Connecting to a real Microsoft Team" below for where that stands now.

**Every other deliberate scope cut**, in build order (full reasoning for each is in `DECISION_LOG.md`):

- **CHN-07 (seed fixtures).** Originally over-built at 20 planted-difficulty categories against an unreconciled "twenty" figure with no source naming them; rebuilt to match source sheet 06's actual, named 15. CHN-28 and CHN-29 later added 3 more real categories (`not_on_roster`, `thread_reply_when_not_counted`, `below_length_floor` -- `seed/fixtures/labels.csv` now has 18 categories, 23 rows) to close genuine eval-harness coverage gaps found after the fact, not to re-litigate the 15-vs-20 question.
- **CHN-17 (scheduled publishing).** No `summary_channel_id` field exists on `ChannelConfig`, so every digest publishes into the channel it's about, never a separate designated summary channel (the WBS text allowed either). Adding that field is a real config-schema change deferred to its own future row, not guessed at silently here.
- **CHN-22 (Teams publish adapter).** `PowerAutomateTeamsPublisher` is written and unit-tested against a mocked HTTP transport; no Power Automate flow has actually been provisioned, so it has never sent a real message. `LogPublisher` is what every test, eval and demo in this repo actually exercises -- the same "written, mocked, never run live" status as `GraphTeamsReader`, on the write side.
- **CHN-25 (Copilot Studio UI).** Built as a documented, tested connector contract rather than a live Copilot Studio agent, deliberately following CHN-22's Power Automate precedent -- no Copilot Studio environment has been provisioned. The scored fallback (Streamlit) is real and is what's actually exercised end-to-end.
- **C13 / C14 (cross-channel question answering; per-person digest).** COULD-priority in the master plan's own capability table, explicitly "not planned" -- no code exists for either.
- **GC1 recall (update-detection).** Deliberately reported, never gated (target `0.0`), per the master plan's own stated rationale: a missed exclusion is a nuisance, a false "no update" names an innocent person. CHN-28 investigated gating it anyway and rejected that, since it would override this explicit, already-reasoned spec rather than fix a defect in it.
- **CHN-31 (clean-clone verification).** `scripts/run_daily.py`'s full-flow demo inserts `members` rows straight from the committed fixture data before ingesting messages, exactly as every golden-case eval module already does (see e.g. `p1.eval.chn24_cases`). This row originally found that CHN-05's ingestion orchestrator (`sync_all_allowlisted_channels`) had never had a member-sync capability of its own, mock or Graph -- that gap has since been closed (see the "CHN-05's real member-registration gap" DECISION_LOG.md entry): `MessageStore.upsert_messages()` now auto-registers any never-before-seen `author_id` before inserting their message, so a real Graph sync against a live channel no longer crashes on the very first message from someone the database has never seen. Separately: if `ANTHROPIC_API_KEY` is missing, the visible error is an Ollama connection failure, not a plain "no API key" message -- `p1.llm.gateway.LLMGateway`'s own designed degrade-to-Ollama fallback (SPN-02) catches the missing-key error and tries a local Ollama call next, which then fails on its own terms. That is existing, documented gateway behaviour this row surfaced, not changed.
- **SPN-02 (AWS Bedrock as a third LLM provider).** `LLM_PROVIDER=bedrock` reaches the same Claude model through AWS's own hosted infrastructure instead of Anthropic's API directly, for whoever's model access happens to be provisioned that way -- via the `anthropic` SDK's own `AnthropicBedrock` client (`anthropic[bedrock]`, which pulls in `boto3`/`botocore`), not a separately hand-rolled AWS signing path. `_call_anthropic` and the new `_call_bedrock` share one request/retry/parsing implementation (`_call_messages_api`), proven identical in call shape via `inspect.signature` against the real installed SDK (`tests/unit/test_llm_gateway_bedrock_call_shape.py`), the same discipline CHN-31 established for the direct Anthropic path. Authenticates via an explicit `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_REGION`, never AWS's ambient default credential chain. One real, deliberately-kept design consequence worth knowing: a misconfigured Bedrock provider (missing AWS config) raises `LLMGatewayError`, and `generate()`'s existing degrade-to-Ollama path (see the CHN-31 bullet above) catches that the same way it catches an exhausted or misconfigured direct-Anthropic call -- it degrades to Ollama rather than surfacing the AWS config problem loudly. This has never been run against a real AWS account; written and tested entirely against a fake Bedrock client, same "written, tested against a fake, never a real network call under test" status as `GraphTeamsReader` and `PowerAutomateTeamsPublisher`.

## Eval results

    uv run python scripts/run_eval.py

**34/34 golden-case metrics passing, across all 12 golden cases (GC1-GC12).**

Latest committed run: 2026-09-18T05:51:27Z -- model `claude-sonnet-4-20250514`,
prompt versions `chn09_classify_message@v1`, `chn13_daily_summary@v1`,
`chn19_weekly_narrative@v1`. (GC1's ground truth grew from 16 to 19
messages in CHN-28 -- see DECISION_LOG.md.)

Every run appends one full record (timestamp, model id, every prompt
capability's version, and every metric's measured/target/pass-fail) to
`eval/results.jsonl` -- the committed history in full is there, this is
just the headline. See `docs/MASTER_IMPLEMENTATION_PLAN.md`'s own
golden-case table for what each GC actually checks.

## Recorded walkthrough

    make walkthrough   # uv run python scripts/run_walkthrough.py

CHN-32's own real backing script for a 5-10 minute recorded demo:
ingests both allowlisted channels and explicitly refuses proj-gamma and
two synthetic chat ids at the scope-gate boundary, prints one real
rule-settled and one real model-settled update-detection decision,
renders proj-alpha's participation ledger with all three non-responder
states present on a real day, generates proj-alpha's daily summary
(with a real, clickable-shaped permalink -- see the caveat below) and
proj-beta's weekly roll-up, holds one real nudge pending and rejects
another, and produces a real escalation evidence bundle -- all against
the exact same production functions every unit test and golden case
already exercises, never a second demo-only code path. `tests/unit/test_run_walkthrough.py`
proves every beat runs against the real fixtures with a scripted
(never live) gateway. Run `uv run python scripts/run_eval.py` as its
own next step for the eval-output beat, and close by naming your own
view of the weakest part -- that's the recording's job, not this
script's.

**Live-permalink caveat**, same one C2/CHN-22 already name: every
permalink in this walkthrough (e.g.
`https://teams.microsoft.com/l/message/19:proj-alpha@thread.tacv2/proj-alpha-0001`)
is well-formed and traces to a real message in this repo's own store,
but does not resolve against a live Teams tenant -- CHN-01's Graph
consent is still pending (see Status above). The script prints an
explicit on-camera narration cue for this rather than leaving it to be
discovered mid-recording.

## Connecting to a real Microsoft Team

Two scripts exist to move from the mock adapter to a real one, once
CHN-01's tenant admin consent is granted (see Status and Key decisions
above -- neither of these can succeed before that):

    uv run python scripts/graph_login.py        # one-time-per-hour device-code sign-in
    uv run python scripts/graph_smoke_test.py    # read-only: proves the live connection works

`graph_login.py` runs Microsoft's own device-code sign-in flow -- it
prints a short code and a URL, you sign in normally in any browser
with an account that's a member of the target channels, and it writes
the resulting access token straight into `.env`'s `GRAPH_ACCESS_TOKEN`
(every other line left untouched). It needs `AZURE_TENANT_ID` and
`AZURE_CLIENT_ID` set in `.env` first (the client ID is the already-registered
`p1-teams-intelligence` app, `1e9e359c-8cd0-4554-9cfd-552d837bd7a8`), and
the app registration's "Allow public client flows" setting must be on,
since a device-code flow is a secret-less, public-client login by
design -- no `AZURE_CLIENT_SECRET` is used anywhere in this path. The
token is short-lived (about an hour); re-run this script to refresh it.

`graph_smoke_test.py` is deliberately the smallest possible next step:
given `GRAPH_ACCESS_TOKEN` and `GRAPH_TEAM_ID` (the Team's M365 Group
ID -- the `groupId` query parameter in a channel's own "Get link to
channel" URL, no separate lookup needed) in `.env`, it lists the real
channels Graph can see for that team, and -- only for a channel_id
that's also in this repo's own allowlist (`config/channels/*.yaml`,
`allowlisted: true`) -- fetches and previews one real page of messages
(author and timestamp only, never full message text). It never touches
ingestion, detection, digests, nudges, or anything that sends -- its
only job is proving the live read path works in isolation before
anything else is allowed to depend on it. Both scripts are unit-tested
against a fake MSAL app / fake reader (`tests/unit/test_graph_login.py`,
`tests/unit/test_graph_smoke_test.py`) -- neither has ever made a real
network call under test, the same discipline as `GraphTeamsReader`
itself.

## Copilot Studio custom connector API

    make copilot-api   # uv run uvicorn p1.api.copilot_studio_api:app --reload

A real, runnable HTTP API (`src/p1/api/copilot_studio_api.py`) sitting
in front of CHN-25's already-tested connector handlers
(`p1.adapters.copilot_studio_connector`) -- the one piece that was
missing for Copilot Studio to be more than a documented contract: a
custom connector needs a real URL and a real OpenAPI document to
import, and nothing in this repo was reachable over HTTP before this.
Every action endpoint (`/list_pending_approvals`, `/approve`,
`/reject`, `/update_channel_config`) is a thin wrapper -- no business
logic of its own -- over the exact same handler functions
`docs/copilot_studio/connector_contract.md` already documents, so
approving through this API and approving through the Streamlit
fallback still produce identical audit records, the same equivalence
`test_copilot_studio_connector.py` already proves.

Auth is a shared secret: every action endpoint requires the correct
`X-API-Key` header, checked against `COPILOT_STUDIO_API_KEY` (`.env`).
This is a deliberate, disclosed scope cut, not a real per-user identity
check -- there is no live Teams/Entra identity yet for this app to
bind `approver_id`/`updated_by` to (see `connector_contract.md`'s own
note on this). If `COPILOT_STUDIO_API_KEY` is unset, the app refuses
every action request outright (fails closed, never open).

Run it locally, open `http://127.0.0.1:8000/docs` for interactive docs
or `http://127.0.0.1:8000/openapi.json` for the document a Power
Platform custom connector imports directly. What this does NOT do:
create a Copilot Studio agent or a Dataverse table, or expose this API
anywhere Microsoft's cloud can actually reach it -- both still need a
human in the Power Platform maker portal with real tenant access, plus
a hosting decision (this repo runs the API locally; making it
internet-reachable, e.g. via Azure App Service or a tunnel, is a
separate, undone step). See `DECISION_LOG.md`'s CHN-25 API entry.

## AI assistance

Portions of this repository's scaffolding, code, and documentation were written with assistance from Claude (Anthropic), used interactively during development. Every file's purpose is understood and can be explained by the author.
