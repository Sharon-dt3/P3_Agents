# Decision Log

Format: date, decision, context/reasoning, alternatives considered.

## 2026-09-15 -- Project tooling: uv over docker-compose

Decision: Use uv for environment/dependency management rather than docker-compose.

Context/reasoning: uv gives a single, fast, reproducible install command (uv sync) with a committed lockfile, satisfying SPN-01's "one install command" requirement without container-orchestration overhead for a single-service Python project.

Alternatives considered: docker-compose -- rejected at this stage as unnecessary overhead; may be reconsidered if the project later needs to bundle non-Python services locally.

---

## 2026-09-15 -- SQLite over a hosted database

Decision: Use SQLite (with FTS5) as the system of record, per SPN-04.

Context/reasoning: Zero setup, reproducible in a clean clone with no external service, and the schema stays readable in the repo as committed migration files.

Alternatives considered: A hosted Postgres/Dataverse-backed store -- rejected as system of record; Dataverse is added later purely as a human-editable config surface (CHN-02/CHN-25), never the source of truth.

---

## 2026-09-15 -- CHN-01: Microsoft Graph access spike

Decision: Pursue Option A -- delegated ChannelMessage.Read.All via a dedicated
service account added as a member of each allowlisted channel, rather than
Option B (application permission).

Context/reasoning: Option A does not require Microsoft's Teams-export
protected-API approval, only tenant admin consent -- a materially lower bar
than Option B, which needs both admin consent and Microsoft's protected-API
approval, and may be metered. Option A also bounds the app's reach to
whichever channels the service account actually joins, rather than granting
tenant-wide read access.

Actions taken:
- Registered Azure AD app p1-teams-intelligence in the DigitalT3 tenant
  (Application (client) ID: 1e9e359c-8cd0-4554-9cfd-552d837bd7a8).
- Added the delegated Microsoft Graph permission ChannelMessage.Read.All.
- Attempted to grant tenant-wide admin consent directly -- blocked: my
  account does not hold an Entra ID role with rights to grant consent
  (confirmed via Entra ID > Roles and administrators; the "Grant admin
  consent" control is disabled for my account).

Status: BLOCKED, pending admin action. Consent request sent to PD on
2026-09-15, asking them to grant admin consent for the above app/permission.

Alternatives considered: Option B (application permission) -- not pursued,
since Option A remains viable pending consent and carries materially lower
approval overhead and narrower scope.

Next step once resolved: run a device-code-flow script to fetch one real
Teams channel message via Graph, satisfying CHN-01's acceptance test.
