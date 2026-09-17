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

## 2026-09-15 -- LLM response cache: flat files, not SQLite

Decision: Cache LLM responses as individual JSON files on disk, keyed by a SHA-256 hash of the full request, rather than a SQLite table.

Context/reasoning: SPN-04 (the SQLite schema) hasn't been built yet and SPN-02 has no dependency on it. Flat files keep the gateway self-contained and testable in isolation now; this can be revisited once the schema exists if a table turns out to be preferable (e.g. for querying cache stats).

Alternatives considered: Waiting to build the cache until after SPN-04 -- rejected, since SPN-02 is on the critical path and gains nothing by blocking on schema work it doesn't need.

## 2026-09-15 -- Scripts bootstrap sys.path manually

Decision: Each script in scripts/ inserts src/ onto sys.path at the top before importing p1, rather than relying on the editable install's .pth resolution.

Context/reasoning: `uv run python scripts/seed.py` failed with ModuleNotFoundError for p1 even though pip list shows it installed -- traced to unreliable .pth processing in this environment (see the earlier pytest pythonpath fix). This keeps scripts working regardless of that, and regardless of the shell's PYTHONPATH state.

Alternatives considered: Fixing the editable install directly (uv sync --reinstall-package p1) -- already tried, did not resolve it; not worth further time given a working, portable alternative exists.

## 2026-09-15 -- Scripts bootstrap sys.path manually

Decision: Each script in scripts/ inserts src/ onto sys.path at the top before importing p1, rather than relying on the editable install's .pth resolution.

Context/reasoning: `uv run python scripts/seed.py` failed with ModuleNotFoundError for p1 even though pip list shows it installed -- traced to unreliable .pth processing in this environment (see the earlier pytest pythonpath fix). This keeps scripts working regardless of that, and regardless of the shell's PYTHONPATH state.

Alternatives considered: Fixing the editable install directly (uv sync --reinstall-package p1) -- already tried, did not resolve it; not worth further time given a working, portable alternative exists.

## 2026-09-15 -- Scripts bootstrap sys.path manually

Decision: Each script in scripts/ inserts src/ onto sys.path at the top before importing p1, rather than relying on the editable install's .pth resolution.

Context/reasoning: `uv run python scripts/seed.py` failed with ModuleNotFoundError for p1 even though pip list shows it installed -- traced to unreliable .pth processing in this environment (see the earlier pytest pythonpath fix). This keeps scripts working regardless of that, and regardless of the shell's PYTHONPATH state.

Alternatives considered: Fixing the editable install directly (uv sync --reinstall-package p1) -- already tried, did not resolve it; not worth further time given a working, portable alternative exists.

## 2026-09-17 -- CHN-07: sheet 06's 15 planted difficulties are authoritative, not "twenty"

Decision: Rebuild CHN-07's planted-difficulty fixtures to match source sheet
06 (Seed Data and Planted Difficulties) exactly -- 15 named P1 categories --
rather than the 20 categories originally built.

Context/reasoning: Sheet 06 is the only source sheet that itemizes the P1
planted difficulties in enough detail to build and grade against. Three
other sheets (the sheet guide, the schedule, and the eval plan) reference
"twenty planted difficulties" with no supporting list -- an unreconciled
approximation, not a second specification. The original CHN-07 build had
20 categories that did not cleanly correspond to sheet 06's 15: 4 matched
correctly, 2 needed timing verification, 4 were built as the wrong test
(exact-boundary post instead of one-minute-late; a 3-person thread instead
of one member's reply-only update; emoji-text messages instead of true
silence for a reactions-only member; and the departed-tenant-member case
had its roster/membership direction backwards), 4 were missing entirely
(posting on behalf of another, an @mention that's actually a question, a
labelled channel-silent-day, and a configured non-working day distinct
from a calendar weekend), and 3 were extras not in sheet 06 at all
(duplicate double-post, cross-channel identity, mismatched timezone --
the last of these isn't a "difficulty" at all, since the timezone
difference is already normal CHN-06 config diversity).

Actions taken:
- Rewrote scripts/generate_seed_fixtures.py's planted-difficulty section
  to implement exactly sheet 06's 15 categories (20 label rows total,
  since bot_post/edited_message/deleted_message each carry 2-3 instances
  so the eval harness's precision/recall numbers are meaningful rather
  than a coin flip on a single example).
- Added SKIP_ORGANIC_AUTHOR_ON_DAY to the generator so the deleted-
  message, thread-reply-only, and late-post cases are deterministically
  guaranteed to be each subject's sole activity that day, rather than
  relying on the random seed to avoid a collision.
- Added a new ChannelConfig field, non_working_dates (list[date], default
  empty), plus migration 0003_channel_config_non_working_dates.sql and
  the matching loader.py sync, to represent a one-off configured holiday
  on an otherwise-working weekday -- something working_days (a recurring
  Mon-Fri pattern) cannot express on its own. Applied to proj-alpha.yaml
  (2025-06-13).
- Corrected the departed-tenant-member case's direction: sofia.almeida is
  now on config/channels/proj-beta.yaml's roster (still an expected
  contributor per the system of record) but deliberately absent from
  list_channel_members, rather than the reverse.
- Dropped the 3 out-of-spec categories entirely rather than keeping them
  as an unlabelled "bonus" tier, to avoid recreating the same "does this
  count or not" ambiguity this rework exists to resolve.

Alternatives considered: Keeping 20 and treating the extra 5 as
legitimately specified -- rejected, since no sheet actually specifies what
those 5 would be, and inventing them ourselves would just be a different
unbacked guess. Keeping the 3 out-of-spec categories as clearly-marked
"bonus" cases -- rejected in favour of a clean 15-for-15 match against the
one document that actually specifies this.

## 2026-09-17 -- CHN-08: the update window is inclusive at both ends

Context: CHN-08's deterministic rules need to decide whether a message
posted exactly at update_window_start or update_window_end counts as
"inside" the window. The CHN-07 rework deliberately dropped the one
fixture case that tested this exact boundary (in favour of an
unambiguous one-minute-late case) specifically so this decision could be
made deliberately here, in the module that actually owns it, rather than
being silently baked into a fixture's expected label.

Decision: the window is inclusive of both ends --
update_window_start <= posted_time <= update_window_end, evaluated in
the channel's own configured timezone (never UTC, never the timestamp's
original offset). A message posted at exactly 09:00:00 when the window
opens at 09:00:00, or at exactly 11:00:00 when it closes at 11:00:00, is
inside the window.

Rationale: the alternative (exclusive on one or both ends) would silently
penalise someone for posting at the exact minute a channel's config says
updates are due, which is the opposite of what update_window_start and
update_window_end are meant to communicate to a human reading the config.
Inclusive-both-ends is also the reading that requires no asymmetry to
justify -- excluding only the end (open interval on the right) is the
usual convention for machine-generated ranges (like Python slicing), but
there is no equivalent convention for a time-of-day window a person
configures and reads back, and picking one end to exclude would need its
own justification this decision doesn't have a reason to supply.

This is implemented in src/p1/detection/rules.py's
_within_update_window and covered directly by
test_window_boundaries_are_inclusive in
tests/unit/test_update_detection_rules.py.

Alternatives considered: exclusive of the end only (start <= t < end),
matching typical range-slicing convention -- rejected, since there is no
equivalent "slicing" mental model for a human-configured time-of-day
window, and it would exclude a message posted at the exact closing
instant for no reason a channel owner reading the config would expect.
Exclusive of both ends -- rejected outright, since it would also exclude
the exact opening instant, an even harder case to justify to a user who
configured update_window_start=09:00:00 and then had their 09:00:00 post
disqualified.

## 2026-09-17 -- CHN-09: low-confidence threshold is 0.6, not a fraction of chance rate

Context: CHN-09's forced schema means the model always returns exactly
one of the six labels -- it never gets to abstain or say "not sure."
"Uncertain" therefore has to be a property this system computes from the
model's own stated confidence number, and that requires picking a cutoff
below which a classification is surfaced for review rather than acted on
as settled.

Decision: LOW_CONFIDENCE_THRESHOLD = 0.6 in src/p1/detection/classifier.py.
A classification is flagged uncertain when confidence < 0.6.

Rationale: the model is asked for its confidence in THIS SPECIFIC label
being correct, not for how much better than random guessing it did. A
six-way classification has a ~0.17 chance floor, but that is not what
the confidence field measures, so anchoring the threshold to it would
conflate two different questions. 0.6 reads the number the way it was
asked for: below the point where the model itself is more unsure than
sure about its own answer, which is exactly what "flagged, not guessed"
in CHN-09's acceptance test means.

Alternatives considered: a threshold derived from the six-label chance
rate (e.g. ~0.3, twice chance) -- rejected, since it answers "did better
than guessing," a different and less honest question than "is the model
itself confident." A stricter threshold such as 0.8 -- rejected as a
default, since it would route a large share of genuinely fine
classifications to manual review for no reason beyond caution; 0.6 can
be revisited once real eval data shows how the model's stated confidence
actually correlates with correctness, but there is no such data yet to
justify a stricter number today.

## 2026-09-17 -- CHN-10: an exception-list entry is not date-scoped

Context: config/channels/*.yaml's `exceptions` list (e.g. proj-alpha's
liam.oconnor, "Annual leave through 2025-06-13") gives ChannelConfig a
member_id and a free-text reason, with no structured start/end date.
CHN-10's participation ledger needs to decide, for one specific
(channel, member, day), whether that member counts as "excluded" --
and the WBS is explicit that the system must "never infer a reason for
absence."

Decision: an exceptions-list entry excuses its member_id for as long as
the entry exists in the config file, full stop -- not for a date range
parsed out of `reason`. build_ledger checks only set membership
(member_id in {e.member_id for e in config.exceptions}), nothing else.

Rationale: `reason` is free text for a human reading the config, not a
machine-readable field, and there is no structured start/end date
anywhere in ExceptionEntry to check instead. Parsing "through
2025-06-13" out of a prose string to compute an effective date range
would itself be exactly the inference this task's acceptance test
forbids -- it would mean the system deciding, from unstructured text,
why and for how long someone gets excused, rather than reading an
explicit fact. Treating list membership itself as the fact respects
that boundary: whoever edits the YAML (adding or removing an entry) is
the one making the date judgement, not the code.

This does mean an exception is "on" until a person removes it from the
config -- there is no automatic expiry. That is consistent with every
other config field in this system (roster, working_days, and so on all
take effect only when the committed file changes) and with CHN-02's own
governing principle that the config file is the system of record.

Alternatives considered: adding start_date/end_date fields to
ExceptionEntry and computing membership per day -- rejected for this
task, not because it's a bad idea, but because doing it now would mean
inventing dates for the one exception the current fixtures actually
have (liam.oconnor's, whose real bound is only ever given as prose) --
exactly the fabrication this decision exists to avoid. If a real,
per-channel leave calendar becomes a requirement, that is a schema
change to make deliberately, with real structured dates behind it, not
a guess made here to fill a gap.

## 2026-09-17 -- SPN-06: an ungroundable line is dropped, not rendered as "unsupported"

Context: SPN-06's own WBS row gives two options for a factual line that
never resolves to a real message -- "removed or explicitly marked
unsupported." Both keep a false claim out of a final summary; they
differ only in whether the gap itself is made visible to the reader.

Decision: the grounding kernel drops an ungroundable line entirely from
GroundingResult.grounded_lines. It is never rendered as a placeholder
("[unsupported claim]" or similar) in a caller's final output. It IS
logged (logger "p1.grounding.kernel", event "grounding_dropped"), with
its reason and original text, exactly as the WBS's acceptance test
names this outcome ("dropped and logged").

Rationale: the summaries this kernel exists to protect (CHN-13/CHN-14,
and their P2/P3 equivalents later) are read by managers about named
colleagues. An awkward "[unsupported]" line would draw attention to a
gap in a way that reads as a missing person or a missing event -- its
own kind of misleading signal, arguably worse than the line simply not
existing. Dropping keeps the rendered output honest by omission rather
than by a visible asterisk; the log is where the gap is actually
inspectable, by whoever is checking the pipeline's own health, not by
the summary's end reader.

Alternatives considered: rendering an explicit "unsupported" marker
inline by default -- rejected for the reason above, though nothing here
prevents a specific future caller from choosing to render
GroundingResult.failures itself, deliberately, if a capability genuinely
wants that visibility -- the kernel returns failures separately from
grounded_lines precisely so a caller can do this without changing the
kernel.
