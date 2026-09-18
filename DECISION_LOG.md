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


- SPN-07: eval results file (`eval/results.jsonl`) is append-only. A run
  never edits or replaces a past run's line -- it only adds one. This
  matches DECISION_LOG.md's own convention and keeps every run's numbers
  comparable across prompt versions and model IDs over the project's
  history, instead of only ever showing the latest run.

- SPN-07: GoldenCaseRegistry is instantiated per run, not a module-level
  singleton. Each call site (a real run, or a test) builds its own
  registry and registers into it, so tests never leak cases into each
  other and two future callers (e.g. P2 and P3 running their own evals)
  never share mutable state by accident.


  - CHN-11: GC1's positive class is "excluded" (rule-detected), not
  "update" -- and only precision is gated, not recall. A false positive
  (a rule wrongly excluding a genuine update) is the failure that names
  an innocent person as silent; a false negative (a bot/system/deleted/
  late post slipping through to the classifier) is a nuisance, since
  CHN-09 still has to judge it as chatter/noise downstream. This matches
  section 6 of docs/MASTER_IMPLEMENTATION_PLAN.md exactly: "Recall
  matters less than precision... a false 'no update' names an innocent
  person." Recall is still computed and printed (target 0.0, so it can
  never itself fail the harness), so a real recall regression is still
  visible in the committed numbers even though it isn't gated.

- CHN-11: GC2's three channel/day combinations were chosen after
  actually running the real pipeline against the fixtures, not assumed
  from what "ordinary" organic traffic should look like. This surfaced
  that proj-alpha's organic messages on 2025-06-05 happen to land
  outside the update window -- a real, previously-unverified fact,
  since CHN-10's own fixture test only ever spot-checked 3 of the 6
  roster members. It also surfaced a latent bug in
  test_participation_against_fixtures.py's ScriptedGateway: it matches
  by `if snippet in prompt`, and the classifier prompt's own worked
  examples contain the literal phrase "Sounds good." (DIFF-CHATTER-01's
  real message text), so that pattern silently matches every message's
  prompt, not just fatima's -- harmless there only because none of that
  test's 3 assertions depend on the messages it affects. GC2 uses a
  corrected gateway that matches only the interpolated message body.
  Alternatives considered: spot-checking only the pre-identified
  difficulty members, as CHN-10's test does -- rejected for GC2
  specifically, since "exact set match" requires knowing every roster
  member's true state, not just the ones already known to be special.
- CHN-12: GC5 runs the real production factory
  (`p1.adapters.factory.get_teams_reader()`) end-to-end against the real
  fixtures and the real `config/channels/*.yaml` allowlist, rather than
  hand-building a `ScopedTeamsReader` from scratch -- the point of this
  golden case is to protect the actual wiring CHN-03's ingestion uses in
  production, not just the `ScopedTeamsReader` class in isolation
  (`test_scope_gate.py` already covers that in full). Doing this
  surfaced a real gap: `get_teams_reader()` constructs its
  `ScopedTeamsReader` without ever passing a `db_path`, so the reader it
  returns always records refusals against the module-level default
  (`data/p1.db`, relative to the caller's cwd) no matter which database
  the rest of the caller's code is actually using. Harmless in
  production, where there is exactly one real db and it already has
  migrations applied -- but it means the factory's return value can't
  safely be used to prove refusal behaviour inside an isolated eval or
  test without either polluting a real `data/p1.db` sitting in the repo
  root or hitting "no such table: audit" against one that was never
  initialised. GC5 works around this rather than depending on it: its
  hard-zero ingest count runs `get_teams_reader()` for real (that half
  never triggers a refusal at all, since `sync_all_allowlisted_channels`
  only ever iterates the already-filtered channel list), and its three
  direct-refusal proofs build their own `ScopedTeamsReader` from the
  same real ingredients (`MockTeamsReader.from_fixtures()`,
  `ChannelConfigStore().list_allowlisted_channels()`) pointed at this
  case's own temp db. Recommended fix, not applied here (pre-existing
  factory.py code, outside this WBS row's own scope, same posture CHN-11
  took with the `ScriptedGateway` bug): let `get_teams_reader()` accept
  an optional `db_path` and pass it through to `ScopedTeamsReader`.

- CHN-12: GC10 is a synthetic two-delta-run scenario, not real fixture
  data -- the committed fixtures have no distinct before/after snapshot
  for the same message id, and an edit/delete/bot/system regression test
  needs one. Built the same way `test_ingestion_sync.py`'s own tests
  already build one: a second `MockTeamsReader` constructed from "run 1's
  messages plus more appended at the end," sharing one
  `SyncStateStore`/`MessageStore`/persisted delta token across both
  `sync_channel()` calls. The resent edit and delete messages carry a
  deliberately different `posted_at` than their run-1 originals, the
  same point `test_ingestion_sync.py::test_edited_message_keeps_its_
  original_post_time` already makes by calling `MessageStore.
  upsert_messages()` directly twice -- GC10 makes the identical claim
  but through two real delta-sync runs instead, so the guarantee is
  proven at the level the WBS actually cares about ("across two delta
  runs"), not just against the repo store in isolation. The exact-count
  assertion (7, not 9) is the one place this case would have caught a
  real regression an earlier version of this design missed: if the
  resent edit/delete were ever treated as brand-new rows instead of
  updates to their existing ones, the count would silently drift to 9
  with no other assertion here catching it.

- CHN-13: the four content sections (what moved, blockers raised,
  decisions taken, questions still awaiting an answer) are each their
  own independent model call, not one combined call and not one call
  per fact. This is what makes "a channel with no traffic produces an
  honest empty summary" actually true rather than aspirational: a
  section with zero facts returns immediately with an empty
  GroundingResult, never building a prompt or touching the gateway at
  all, so a silent channel (or one where every message was chatter/
  noise) costs zero model calls, not four calls that each have to be
  told "there is nothing here." Per-section calls also keep each
  prompt's facts_block small and focused on one kind of fact, rather
  than asking one call to juggle four different framings at once.

- CHN-13: the message_lookup handed to SPN-06's grounding kernel for
  each section's model call is a small in-memory dict built only from
  that section's own facts (`{fact.message_id: fact.body_raw}`), not
  the general sqlite-backed `grounding/message_lookup.py` lookup every
  other caller uses. Plain reference-or-drop grounding can only tell
  whether a message_id resolves to *some* real message somewhere in the
  store -- it has no way to tell whether that message is one of the
  facts actually handed to *this* call. A model that (incorrectly)
  claims a real message id belonging to a different section, a
  different day, or a different channel entirely would otherwise ground
  successfully on content it was never given, which is exactly the kind
  of fabrication this capability's own acceptance criteria exist to
  catch. Scoping the lookup to exactly the facts handed to that one
  call closes that hole; see
  test_a_line_claiming_a_real_but_unrelated_message_id_is_dropped_not_kept
  in tests/unit/test_daily_summary.py, which seeds a real blocker
  message and proves a what_moved line claiming that same (real, but
  unrelated) id is dropped across every retry attempt, never kept.

- CHN-13: "questions still awaiting an answer" treats a question as
  addressed the moment at least one non-deleted thread reply exists
  against it (`messages.thread_root_id` pointing at the question's own
  id) -- it does not try to judge whether that reply substantively
  answers the question. This is a deliberate simplification, not an
  oversight: CHN-09's six classification labels (update, question,
  blocker, decision, chatter, noise) include no "answer" label, so
  "was this question substantively answered" is not a fact this
  codebase can honestly compute today. Any reply at all is treated as
  the channel having addressed it. A deleted reply does not count
  (test_a_question_answered_only_by_a_deleted_reply_is_still_awaiting_an_answer),
  since a deleted reply is not evidence the channel currently
  considers the question addressed.

- CHN-13: the participation section adopts CHN-14's exact three-state
  wording ("no message posted" / "posted, but no update" /
  "excluded - on the exceptions list") now, directly from
  docs/MASTER_IMPLEMENTATION_PLAN.md's own phrasing for that future WBS
  row, rather than shipping a placeholder for CHN-14 to come back and
  rewrite. CHN-14's own acceptance test ("a chatter-only member is
  never reported as posted no message, an on-leave member is never
  reported as silent") is already structurally guaranteed here, since
  it is just CHN-10's `build_ledger` state distinctions
  (NO_MESSAGE / POSTED_NO_UPDATE / EXCLUDED) rendered verbatim, not a
  new judgment this module makes on its own.

- CHN-13: the fact-gathering half of this capability lives in its own
  module, `p1.reporting.facts` (pure DB reads, zero import of `p1.llm`
  or `p1.prompts`), separate from `p1.reporting.daily_summary` (the
  model-calling half). This is the same "facts in code, prose from the
  model" boundary the WBS row itself names, just enforced at the module
  level too: `tests/unit/test_no_inline_prompts.py` (SPN-05) treats any
  module that imports `p1.llm`/`p1.prompts` as a "model-calling module"
  and additionally scans it for long (>=200 char, >=30 word) string
  literals as suspected inline prompts. The original single-file draft
  of this capability imported both (to call the model) and separately
  contained a long, wordy multi-line SQL literal for the fact query --
  the combination tripped that lint test even though the literal was
  plainly SQL, not a prompt. The test's own docstring names
  `storage/messages_repo.py` as the precedent for how a SQL-heavy
  module stays correctly out of scope: by never importing `p1.llm`/
  `p1.prompts` in the first place. `p1.reporting.facts` follows that
  same precedent rather than working around the heuristic (e.g. by
  reformatting the SQL to dodge the length/word-count check).

- CHN-13: `DigestStore.record()` upserts on `idempotency_key`
  (`"{channel_id}:{date}:daily"`), matching the same
  upsert-on-reprocess convention every other store in this codebase
  already follows (MessageStore, ClassificationStore,
  ParticipationStore) -- regenerating a day's digest before it has been
  published replaces its content in place instead of duplicating a row.
  `published_at` is deliberately never touched by this module: whether
  a digest has been published, and enforcing that it is only ever
  published once, is CHN-17/CHN-18's concern, not this one's.

- CHN-14: the participation-rendering code CHN-13 originally inlined
  into daily_summary.py (the wording map plus the line-rendering
  function) moved into its own module,
  `p1.reporting.participation_rendering`. The WBS row's own framing --
  "this section is read by managers about named colleagues, the
  wording is a design decision, not a formatting detail" -- is what
  justifies giving it a single, dedicated home: every digest surface
  that ever needs to render a roster's participation (today, the daily
  digest; a future weekly one) reuses the exact same three phrases
  rather than each call site risking its own slightly different
  rephrasing over time.

- CHN-14: "no inferred reasons" is enforced structurally, not just by
  convention. `render_participation_lines` takes only
  `ParticipationRecord` (channel_id, member_id, date, state,
  evidence_message_ids) -- CHN-10's `build_ledger` never copies a
  channel's configured exception reason
  (`ChannelConfig.exceptions[*].reason`, e.g. "On leave") onto the
  record in the first place, so there is no reason text this function
  could reach for even if a future edit tried to add it in. Proved
  directly: `test_a_different_exception_reason_produces_byte_
  identical_wording` builds the same excluded member under two
  different configured reasons and asserts the rendered output is
  identical either way -- not just that today's fixture's reason
  string happens not to appear.

- CHN-14: "no ranking of people" is enforced by this module never
  reordering what it's given. `render_participation_lines` renders
  records in exactly the order `build_ledger` returns them (already
  sorted by member_id -- CHN-10's own
  `test_ledger_is_sorted_by_member_id`), never resorted by state, by
  how long someone's been silent, or by any other measure of severity.
  `test_rendering_preserves_the_ledgers_own_order_never_resorting_
  by_state` proves this directly by feeding a deliberately
  out-of-member-id-order, mixed-state batch straight through and
  asserting the output order is untouched.

- CHN-14: the acceptance test itself ("the chatter-only member is
  never reported as having posted no message, and the on-leave member
  is never reported as silent") is re-proved directly against
  `p1.reporting.participation_rendering` in its own test file, not
  only implicitly through the full daily-digest test suite CHN-13
  already has. CHN-13's tests still cover the same guarantee
  end-to-end; this is a second, narrower, faster net around the exact
  rendering contract, so a future refactor of digest assembly can't
  quietly break this specific promise without a focused test catching
  it immediately.

- CHN-14: `PARTICIPATION_WORDING` is pinned by its own snapshot test
  (`test_wording_map_is_exactly_the_three_specified_phrases_and_
  nothing_else`) asserting the dict equals the three exact strings the
  WBS row specifies, character for character. This is the practical
  enforcement of "no adjectives" for a property that is otherwise a
  judgment call, not a mechanically checkable one: a future edit that
  quietly adds an adjective, a count, or a qualifier to any of the
  three phrases fails this test immediately, rather than only showing
  up as an unnoticed diff in a generated digest months later.

- CHN-15: GC3 (citation rate) and GC4 (fabrication probe) are measured
  as two separate scenarios, not one combined run, because they audit
  different populations and would distort each other if mixed: GC3
  needs a batch large enough that one invented id is a meaningful,
  boundary-sitting fraction (19 real facts + 1 invented id = 19/20 =
  0.95, exactly the target -- deliberately not a comfortably-clear
  number, since the WBS's own rationale is making a point about how
  tight this boundary is); GC4 needs a small, realistic end-to-end
  digest run where a single deliberate fabrication attempt is easy to
  trace to a specific, named cause. Folding both into one scenario
  would have forced a choice between diluting GC3's ratio with GC4's
  necessarily-adversarial input, or diluting GC4's clarity with GC3's
  bulk of uneventful facts.

- CHN-15: GC3 measures the model's *first, unaided* attempt at citing
  a fact -- before SPN-06's retry-and-drop safety net gets a chance to
  correct anything -- rather than the fully-grounded output that
  eventually reaches a digest. The fully-grounded output is
  guaranteed by construction to resolve 100% of the time (that is what
  `verify_lines` inside `ground_with_retry` enforces before anything is
  returned), so measuring citation rate against it would be a trivial,
  always-1.0 metric that proves nothing. Measuring the raw first draft
  instead makes ">=0.95" a real, falsifiable claim about how often the
  model gets a mechanical, exact-copy task right unaided -- which is
  also why the target is higher than GC1's 0.80: there is no judgment
  call involved in copying an id verbatim, so the bar for "acceptable"
  is much closer to perfect.

- CHN-15: GC3 calls `p1.grounding.kernel.verify_lines` directly rather
  than reimplementing "does this id resolve" as its own comparison.
  Golden cases exist to protect real production code paths (the same
  posture GC1 takes by scoring `p1.detection.rules.evaluate_message`
  directly, and GC5 by calling the real
  `p1.adapters.factory.get_teams_reader()`), not to duplicate their
  logic and risk the duplicate silently drifting out of sync with the
  real implementation.

- CHN-15: GC4 does not trust SPN-06's own bookkeeping
  (`GroundingResult.dropped`/`.failures`) to prove fabrication never
  survives -- it re-derives the check independently, straight against
  the database, for every line in the FINAL rendered
  `DailySummaryResult.section_lines`: the message_id must exist in this
  channel's `messages` table, that message's own
  `classifications.label` must actually match the section the line was
  placed under (a line under "decisions taken" citing a message the
  store says is chatter is exactly as dishonest as citing a message
  that doesn't exist at all -- both count as fabrication here, not
  just the first), and the message must carry a real author. This is a
  black-box probe on purpose: it would still catch a bug in the
  grounding kernel itself, which trusting `result.dropped` never could.

- CHN-15: GC4's scenario deliberately makes its own scripted gateway
  attempt one real fabrication (citing a real message that belongs to
  a *different* section) before correcting on retry, rather than
  scripting an entirely clean run with nothing to catch. A "hard zero"
  metric that never actually exercises the failure path it claims to
  guard against would trivially pass without proving anything; this
  golden case's own test
  (`test_gc4_probe_is_not_vacuous_a_fabrication_was_really_attempted`)
  pins that the fabrication attempt genuinely happened by asserting
  the gateway was called exactly 5 times (4 sections, plus one retry),
  not 4.

## 2026-09-17 -- CHN-16: GC9 compares production's own fact-set, not a third re-derivation

Decision: _fact_set() reads contributor lists, per-section counts and the participation set directly off the real DailySummaryResult and ParticipationRecord objects that generate_daily_summary() actually returned, rather than independently re-querying the database for a third answer to compare both sides against.

Context/reasoning: GC9 is a determinism check, not a correctness check -- it asks whether two independent generations against the identical seeded window agree with each other, not whether either one is right (that is already GC1/GC3/GC4/GC5/GC10's job). Re-deriving a third answer straight from the database for each side would only prove the database matches itself twice, which is trivially true and would catch nothing. Comparing production's two actual outputs directly is what would catch a real regression -- for instance a change that made section assembly order-sensitive, or that let the grounding retry path silently drop a fact on one run and not the other.

Alternatives considered: recomputing gather_daily_facts() and build_ledger() fresh for each side and asserting those two independent calls agree -- rejected, since both are already pure, deterministic functions over the same immutable seeded window and would trivially agree with themselves regardless of whether generate_daily_summary() reliably plumbs their output through to the final result end to end.

## 2026-09-17 -- SPN-08: proposals table already existed; no new migration needed

Decision: ProposalStore is built entirely against the `proposals` table already defined in 0001_initial.sql -- no new migration file for this row.

Context/reasoning: The initial schema spike already scaffolded `proposals`, `write_log` and `audit` alongside the tables CHN-06 through CHN-15 needed, anticipating SPN-08/09's shape. Its columns match this row's own listed fields exactly (id, type, status, payload, original_model_output, source_refs, approver_id, created_at, decided_at, idempotency_key), so this row is purely the Python state machine on top of an already-correct table. One gap worth naming: original_model_output has no NOT NULL constraint at the schema level, unlike payload -- ProposalStore.create() requires it as a mandatory keyword argument regardless, so the guarantee is enforced at the application layer even though the column itself would technically permit a null.

Alternatives considered: adding a NOT NULL migration for original_model_output -- deferred rather than rejected outright; SQLite's ALTER TABLE can't add a NOT NULL column without a default to an existing table with rows already using looser rules elsewhere in this schema (e.g. digests.published_at), so tightening it would mean a table rebuild for a guarantee the application layer already enforces just as reliably for every row this store itself ever writes.

## 2026-09-17 -- SPN-08: create() refuses to reset an already-decided proposal on retry

Decision: create()'s idempotency is ON CONFLICT(idempotency_key) DO NOTHING followed by a read-back of whatever row now exists, rather than DigestStore's own ON CONFLICT ... DO UPDATE pattern.

Context/reasoning: A digest can be safely regenerated any time before it's published -- overwriting its content in place on a retried create() is exactly the right behavior (CHN-13). A proposal is different: by the time a caller retries the same idempotency_key, a human may already have approved or rejected it, and an overwrite-on-conflict create() would silently wipe that decision back to a fresh pending row -- the opposite of what an idempotency key is supposed to guarantee. DO NOTHING plus read-back means a retried create() is always a no-op against an already-decided proposal, and only ever inserts when the key is genuinely new.

Alternatives considered: matching DigestStore's overwrite pattern verbatim for consistency -- rejected once the concrete failure mode (a retried digest job silently un-approving yesterday's already-approved digest) was worked through; consistency with a different store isn't worth reintroducing the exact bug idempotency keys exist to prevent.

## 2026-09-18 -- SPN-09: the approval lookup catches Exception broadly, on purpose

Decision: guarded_send()'s try/except around store.get(proposal_id) catches bare Exception, not just ProposalNotFoundError.

Context/reasoning: normal advice is to catch narrow, specific exception types so a real bug doesn't get silently swallowed. Here that advice is inverted deliberately: this row's own acceptance test names "documented timeout behaviour defaulting to not sending" as a requirement, and the failure modes that could show up in that lookup -- an unknown proposal id, a database error, a future networked store's connection timeout -- are all, from this function's point of view, the same case: a failure to positively confirm status == 'approved'. The one thing worse than refusing a send because of a transient bug in the lookup is sending because of one. Catching broadly and refusing is the fail-closed choice; catching narrowly would mean an unanticipated exception type falls through uncaught, past the refusal, with unclear consequences for whatever called guarded_send().

Alternatives considered: catching only ProposalNotFoundError and letting any other exception propagate uncaught -- rejected, since an uncaught exception is not the same guarantee as a raised WriteRefusedError refusal, and a caller written to only check for WriteRefusedError would not reliably stop the send on a different exception type.

## 2026-09-18 -- SPN-09: guarded_send() also marks the proposal applied and logs the attempt

Decision: on a successful send, guarded_send() calls proposal.apply() (SPN-08) and writes a row to write_log itself, rather than leaving both to the caller.

Context/reasoning: CHN-17, CHN-21 and CHN-23 will each have their own send_fn, but none of them should need to remember, separately, "and now mark this applied" and "and now log the attempt" -- those two things are true of every successful send through this gate, not particular to any one capability. Colocating them in the guard itself means a future capability that forgets to call apply() after its own send simply can't happen, because it never had to.

Alternatives considered: leaving apply()/write_log entirely to each capability's own publish code -- rejected, since it would mean the exact same three lines get duplicated (or, worse, inconsistently omitted) across CHN-17, CHN-21 and CHN-23.

## 2026-09-18 -- CHN-17: no summary-channel config field; publishes into the channel itself

Decision: run_daily_digest_job publishes every channel's digest into that channel itself (payload["target_channel"] = channel_id), since ChannelConfig has no field naming a separate "designated summary channel" to publish into instead.

Context/reasoning: the WBS row's own text says "Publishes into the channel, or a designated summary channel," but no such field exists anywhere in p1.config.schema.ChannelConfig -- adding one would mean a new field plus a migration for config data that doesn't exist yet, which is a real scope decision, not a one-line implementation detail to guess at silently. Publishing into the channel itself is the only option available without inventing new config shape, and it's also the simpler, safer default: a channel's own digest going back into that same channel is unsurprising, where a misconfigured summary-channel field could route a digest somewhere unexpected.

Alternatives considered: adding a summary_channel_id: str | None field to ChannelConfig now and wiring it through -- deferred rather than rejected outright; that's a real config-schema change with its own migration and validation questions (does an empty summary channel need its own allowlist entry? what if it's set but wrong?) that belongs to its own row, not a decision to make silently inside this one's implementation.

## 2026-09-18 -- CHN-17: two distinct idempotency keys for two distinct resources

Decision: digest CONTENT keeps CHN-13's own key (f"{channel_id}:{date}:daily"); the decision to SEND that content gets a separate key (f"{channel_id}:{date}:daily_publish") on its own SPN-08 Proposal.

Context/reasoning: these are genuinely different resources with different mutability rules. Content can be regenerated any number of times right up until it's sent (CHN-13's own upsert-on-reprocess pattern, unchanged by this row). The decision to publish, once made, must never be silently redone -- "exactly one digest per channel per day" is a promise about the SEND, not the content, so it needs its own idempotency key on its own record, one that SPN-08's status machine (and SPN-09's write guard) can govern independently of however many times the content underneath it gets regenerated.

Alternatives considered: a single idempotency key shared between DigestStore.record() and the publish Proposal -- rejected; it would either block legitimate content regeneration before a proposal is decided, or (worse) let a proposal's identity depend on content that's still changing.

## 2026-09-18 -- CHN-17: first-publish-requires-approval is answered per channel, across all dates

Decision: "is this the first publish for this channel" is answered by DigestStore.has_ever_published(channel_id) -- true iff ANY date's digest for this channel has ever been marked published -- computed once, at the moment a channel's first publish proposal is created, not re-checked on every rerun.

Context/reasoning: the row's own acceptance framing is "no channel ever receives an unexpected bot post," which is a statement about the channel's entire history, not about today in isolation. Checking has_ever_published() only at proposal-creation time (rather than every time the job runs) means a channel that's already past its first publish never gets asked again, even if this job is rerun many times a day -- once true, has_ever_published() only ever stays true, since digests.published_at is never unset.

Alternatives considered: a config-level boolean flag (e.g. "first_publish_done") set by the job -- rejected in favor of deriving the answer from data that's already true (published_at) rather than introducing a second, potentially-drifting source of truth for the same fact.

## 2026-09-18 -- CHN-17: is_due() and build_scheduler() are two layers, not one fake clock

Decision: scheduler.py splits into a pure, clock-injectable is_due(config, moment) function and a separate build_scheduler() that wires real APScheduler CronTriggers -- rather than trying to make APScheduler itself accept an overridden clock.

Context/reasoning: "a clock override for demos" could mean monkeypatching datetime.now inside APScheduler's own internals, but that's fighting a real scheduling library's own clock-handling code for no real benefit -- fragile across APScheduler versions, and it still wouldn't give a demo a simple, direct way to ask "would channel X fire right now at instant Y." Splitting the decision (is_due) from the mechanism (build_scheduler) means the override is just an ordinary function argument: a demo (or run_daily_digest_job's own `day` parameter) hands in whatever moment/day it wants to pretend it is, gets the same answer production's real scheduler would give at that real moment, and never touches APScheduler's internals at all. build_scheduler()'s CronTrigger fields are a direct translation of the same ChannelConfig fields is_due() reads, so the two are provably answering the same question, not two independent implementations that could drift apart.

Alternatives considered: monkeypatching or dependency-injecting a clock into APScheduler itself -- rejected as more fragile and no more powerful than a pure function that any caller (test, demo, or a future admin tool) can call directly with whatever moment it likes.

## 2026-09-18 -- CHN-17: rejected/already-applied publishes short-circuit before reaching guarded_send()

Decision: run_daily_digest_job checks proposal.status against REJECTED and APPLIED itself, returning a plain JobResult without calling guarded_send(), rather than always routing every rerun through the guard and catching WriteRefusedError.

Context/reasoning: guarded_send() (SPN-09) still refuses those cases too if it were called -- that's not in question. But routing a routine, expected rerun (a rejected proposal, or a day that's already been sent) through an exception-raising refusal path on every single invocation would mean using exceptions for ordinary control flow, and would write a "refused" write_log row every time a scheduler fires on an already-decided day, which is noise, not a real refused-send event. guarded_send() is still the sole gate for the one case that matters -- an approved proposal actually being sent -- and nothing in this row bypasses it for that case.

Alternatives considered: always calling guarded_send() and letting it raise/refuse for every status -- rejected for the reasons above; kept as SPN-09's own defense-in-depth regardless (if this job's short-circuit logic ever had a bug, guarded_send() would still refuse a send that wasn't actually approved).

## 2026-09-18 -- CHN-18: daily_job.py revised to always route through guarded_send()

Decision: run_daily_digest_job() no longer short-circuits around SPN-09's guarded_send() for a rejected or already-applied proposal (reversing the CHN-17 decision logged immediately above this one). Every call now reaches guarded_send() regardless of the proposal's current status; WriteRefusedError is caught only to translate SPN-09's one generic refusal into this job's own more specific JobResult status (awaiting_approval / rejected / already_published).

Context/reasoning: CHN-17's own short-circuit was deliberate at the time -- avoiding a "refused" write_log row on every routine rerun of an already-decided day, reasoning that this was noise rather than a real event worth recording. CHN-18's acceptance test proved that reasoning wrong: "run the daily job three times over the same day... assert... the write log shows the two suppressed attempts" is only satisfiable if every rerun's suppression is actually written to write_log, and guarded_send() is the only function in the codebase that ever writes there. Keeping the short-circuit would have made GC6's second metric (GC6-suppressed-attempts) permanently unsatisfiable without either duplicating guarded_send()'s own logging logic elsewhere or reintroducing exactly the write path this codebase deliberately keeps in one place. Reversing the short-circuit also makes SPN-09's own docstring claim -- "every attempt -- refused, sent, or failed after being sent -- is recorded in the write_log table" -- actually true for this capability, rather than true in principle but bypassed by its first real caller.

Alternatives considered: keeping the short-circuit and having run_daily_digest_job write its own separate "suppressed" row directly to write_log -- rejected, since it would mean two different code paths writing to the same table for what is conceptually the same kind of event (a refused send), which is exactly the duplication SPN-09 was built to prevent in the first place.

## 2026-09-18 -- CHN-18: GC6 pre-seeds an already-published earlier day, not a fresh channel

Decision: GC6's scenario seeds a digest already published on the day before the one it tests, so the very first of its three run_daily_digest_job() calls is the "subsequent days run unattended" case (CHN-17) -- auto-approved and actually sent -- rather than a fresh channel's first-ever publish (which would stay pending across all three calls and never send at all).

Context/reasoning: the row's own acceptance test implies exactly one real send happened ("the write log shows the two suppressed attempts" -- two, not three) alongside one digest. A fresh channel run three times would produce three pending refusals and zero sends, which technically has "the digest exists once" but would not demonstrate publish idempotency around an actual send at all -- the more interesting and more representative case for a channel already past onboarding.

Alternatives considered: pre-approving a fresh channel's first-day proposal directly via ProposalStore before calling the job -- rejected in favor of the already-published-yesterday setup, since it exercises has_ever_published()'s real auto-approval path (the actual mechanism CHN-17 built) rather than bypassing it with a manually-forced approval that isn't how any real proposal reaches APPROVED on a subsequent day.

## 2026-09-18 -- CHN-19: A week is a fixed 7-day window ending on an explicit `week_end` argument

**Decision:** `week_bounds(week_end)` always returns a 7-calendar-day window `[week_end - 6 days, week_end]`. `week_end` is a plain function argument everywhere in `p1.reporting.weekly_facts`/`weekly_summary` -- there is no hidden `date.today()` read anywhere in the module.

**Context/reasoning:** This mirrors CHN-17's `is_due(config, moment)` clock-override pattern exactly, for the same reason: a fact-gathering function that silently reads the wall clock cannot be tested deterministically and cannot be re-run for a past week to backfill or audit. Every test in `test_weekly_facts.py` and `test_weekly_summary.py` passes a fixed `WEEK_END` and gets a fixed answer.

**Alternatives considered:** Deriving `week_start`/`week_end` from a `weekly_digest_day` config field and "now" was rejected -- it would couple fact-gathering to the scheduler's own concern (when the job happens to fire) rather than to what a week means, and would make every test time-dependent.

## 2026-09-18 -- CHN-19: Excepted roster members are absent from `participation`, never given a rate of 0

**Decision:** A member listed in `config.exceptions` does not appear as a key in the dict `member_participation()`/`participation_trend()` return at all. `gather_weekly_facts()` reports them separately, in `excluded_members`, alongside their stated reason.

**Context/reasoning:** A rate of 0% for someone on leave is a false claim about non-participation; the honest fact is "not measured," not "measured at zero." This also matches how the rendered roll-up needs to read: "carol: excluded (On leave)" rather than a misleading "carol: 0%" sitting next to real numbers.

**Alternatives considered:** Giving excepted members `rate=None` inside the same dict (rather than omitting the key) was considered, but rejected because it would require every consumer to remember to check for both "excepted" and "zero working days this week" (a separate, real `None` case) as distinct meanings collapsed into the same sentinel.

## 2026-09-18 -- CHN-19: "Recurring blocker" is a mechanical, code-checkable rule, not a model judgment

**Decision:** A recurring blocker is: the same roster author, raising a blocker-labeled message, on two or more distinct local calendar days within the current week only. No topic clustering, no similarity scoring -- just author + label + distinct day count.

**Context/reasoning:** The row's own framing is "every quantitative claim recomputable from stored messages," and a model-based judgment of "is this the same underlying blocker as three days ago" is not recomputable by hand. A mechanical day-count rule is exactly what a person skimming the raw messages table could verify themselves, which is the bar this whole capability is held to.

**Alternatives considered:** Clustering by message similarity or by explicit thread-linking was rejected as both unnecessary (the WBS row asks only for "recurring," not "the same specific issue") and untestable in the same deterministic way.

## 2026-09-18 -- CHN-19: "Unanswered all week" is scoped to the week's own window, deliberately narrower than CHN-13's real-time check

**Decision:** A question counts as "went unanswered all week" if no non-deleted reply exists with `posted_at <= week_end`. A reply that arrives the following week does not retroactively remove the question from this week's list.

**Context/reasoning:** CHN-13's daily "still awaiting an answer" check is a real-time question ("is anyone waiting on an answer right now") and rightly looks at all replies ever, regardless of date. CHN-19's claim is different in kind: "went unanswered all week" is a historical claim about that specific week, and a reply that shows up later does not make that claim false -- it was still true that, during that week, nobody had answered yet. Keeping this distinct from CHN-13 was a deliberate divergence, not an inconsistency, and is exercised directly by `test_a_reply_that_arrives_the_following_week_does_not_count`.

**Alternatives considered:** Reusing CHN-13's real-time check unmodified was rejected because it would make a past week's roll-up mutate its own answer retroactively every time this job re-runs later, which contradicts what "went unanswered all week" is supposed to mean as a permanent historical fact about that week.

## 2026-09-18 -- CHN-19: The no-digits rule on the narrative is a pydantic validator, not just a prompt instruction

**Decision:** `WeeklyNarrativeDraft.narrative` carries a `@field_validator` that raises `ValueError` on any digit character, feeding directly into `generate_structured()`'s existing retry-on-validation-failure loop.

**Context/reasoning:** The row's own acceptance framing is "rates and trends are computed, never estimated by a model" -- if this were only a prompt instruction, a model that ignored it would silently ship a restated (and possibly wrong) figure into the final roll-up, with no mechanical way to catch it. Making it a validator turns a qualitative prompt-engineering hope into something `test_narrative_with_a_digit_is_rejected_and_retried` can actually prove, and costs no new plumbing since `generate_structured` already retries on `ValidationError` for CHN-13's structured drafts.

**Alternatives considered:** Post-processing the model's output to strip digits after the fact was rejected -- silently mangling a sentence the model wrote is worse than asking it again, and would hide a bad instruction-following pattern rather than surfacing it.

## 2026-09-18 -- CHN-20: GC11 is two independent computations compared, not one hand-picked literal expectation

**Decision:** GC11 seeds one scenario as a plain list of `_SeedMessage` records, then computes the weekly roll-up two separate ways: the real production `gather_weekly_facts()` against a real seeded sqlite db, and `_independent_recompute()`, a from-scratch reimplementation of the working-day/participation/blocker/decision/question arithmetic that imports none of `weekly_facts.py`'s functions (only its frozen dataclasses, reused purely as result shapes). The metric is the count of sections where the two disagree, targeted at `equals(0)`.

**Context/reasoning:** The row's own acceptance criterion is "recomputation test passes for every figure," and the risk with a unit test that hand-computes expected numbers by hand (as `test_weekly_facts.py`/`test_weekly_summary.py` already do, deliberately, at smaller scale) is that a hand-computed expectation can itself be wrong in exactly the way the code being tested is wrong, especially once several interacting rules (working days, exceptions, window scoping) are combined in one scenario. Two independently-coded implementations agreeing is a much stronger signal than one implementation matching a human's arithmetic -- the same reasoning CHN-16's GC9 already applied to the daily digest's dual-generation grounding check.

**Alternatives considered:** A single larger unit test with hand-verified literals (extending `test_weekly_summary.py`'s own scenario) was rejected for this specific row, both because CHN-19 already has that coverage and because the row's own category ("2 Grounding") calls for the cross-check style GC3/GC4/GC9 already established, not another functional-coverage unit test.

## 2026-09-18 -- CHN-20: the non-working-day scenario reuses the same message for two different rules, plus a dedicated sanity metric

**Decision:** GC11's scenario has one roster member raise the identical blocker again on a day declared in `config.non_working_dates`, sitting inside the week window. `GC11-non-working-day-scenario-check` independently confirms that day is excluded from `working_days_in_range()` but still present in a `RecurringBlocker.days` tuple, as its own separate metric from the main reproducibility check.

**Context/reasoning:** The row explicitly calls out "including the week containing a non-working day," and `weekly_facts.py`'s own design has two different window rules in play here: participation is working-day-scoped (a holiday reduces the denominator and can't be "contributed to"), while recurring-blocker/decision/question windowing is calendar-week-scoped (a message posted on a holiday still counts toward "did this happen this week"). A golden case that included a non-working day only incidentally -- say, a day nobody posted on -- would pass without ever actually exercising that split. The separate sanity metric makes it impossible for this case to silently regress into checking nothing about non-working days at all.

**Verification note:** Before sending this case, I deliberately broke `weekly_facts.py`'s working-day intersection (`contributed_working_days = len(days_contributed)` instead of `len(days_contributed & working_days_set)`) in the sandbox and reran the eval -- `GC11-arithmetic-mismatch-count` correctly failed (measured=1, mismatched section: participation) -- then reverted and confirmed a clean pass again, to confirm this golden case actually catches a wrong answer rather than tautologically agreeing with whatever the production code currently does.

## 2026-09-18 -- CHN-21: nudges get their own table, mirroring digests_repo.py, not a query over proposals' JSON payload

**Decision:** A new `nudges` table (channel_id, member_id, date, proposal_id, sent_at, idempotency_key) backs `NudgeStore`, with `has_ever_been_nudged(channel_id, member_id)` and `sent_count_for_day(channel_id, member_id, date)` as its two read methods. Neither is answered by scanning `proposals` for `type='nudge'` rows and parsing their JSON payload.

**Context/reasoning:** `proposals` has no queryable member_id/date columns -- those live inside the JSON `payload` blob -- so answering "has this person ever been nudged" or "how many times today" that way would mean loading and parsing every nudge proposal's payload in Python on every job run. `digests` already solved exactly this shape of problem for CHN-13/17 by giving itself real `channel_id`/`date` columns alongside `proposals` rather than querying through it, and `NudgeStore` follows that same precedent for the same reason, one level narrower (per person, not per channel).

**Alternatives considered:** Adding `member_id`/`date` columns directly to the `proposals` table (nullable, used only by nudge-type rows) was considered and rejected -- `proposals` is a shared abstraction across all three agents (SPN-08's own framing), and adding capability-specific columns to it would start coupling that shared table to each capability's own read patterns, the same reason `digests` stayed a separate table instead of extending `proposals` when CHN-13 was built.

## 2026-09-18 -- CHN-21: "has ever been nudged" is scoped per (channel, member), not globally per person

**Decision:** `NudgeStore.has_ever_been_nudged()` takes both `channel_id` and `member_id`. A person nudged before in one channel still gets their first-ever-in-*this*-channel nudge held for approval in a different channel.

**Context/reasoning:** `config.exceptions`, `config.roster` and every other per-person rule in this codebase are already channel-scoped, not person-scoped globally -- a member can be on-leave in one channel's config and not another's, and CHN-19's own participation rate is computed per channel. Treating "has this person been nudged before" as a global fact about the person, independent of channel, would be the only cross-channel rule in the whole nudge/participation/digest surface, for no requirement that asked for it.

## 2026-09-18 -- CHN-21: the per-person cap is enforced by a sequence-numbered idempotency key, and only counts sends, never attempts

**Decision:** Each nudge attempt for a person on a given day gets its own idempotency key, `f"{channel_id}:{member_id}:{date}:{sequence}"`, where `sequence` is `NudgeStore.sent_count_for_day(...) + 1` at the moment of creation. The cap check (`sent_count_today >= config.nudge_cap_per_day`) runs BEFORE any proposal for this run is looked up or created, and only counts rows with a non-null `sent_at` -- a pending or rejected attempt never counts against the cap.

**Context/reasoning:** `nudge_cap_per_day` is a plain integer field on `ChannelConfig`, not a boolean, so the mechanism has to generalize past 1 without a redesign later. Keying by sequence rather than a single fixed per-day key is what makes a cap of 2 or 3 fall out of the same code path as a cap of 1, exercised directly by `test_a_higher_cap_allows_more_than_one_nudge_the_same_day`. Counting only actual sends (not attempts) toward the cap is the same reasoning `DigestStore.has_ever_published()` already applies to "published" vs. "proposed" -- an unsent proposal is not a nudge the person received, so it must not consume their daily allowance, matching this row's own "hard per-person per-day cap" wording (a cap on nudges received, not proposals created).

## 2026-09-18 -- CHN-21: the exceptions check is deliberately real code in run_nudge_job's own loop, not folded into the eligibility filter

**Decision:** `_eligible_non_responders()` only filters out the ledger's own `EXCLUDED` state. The independent, second check against `config.exceptions` lives in `run_nudge_job`'s per-member loop itself, immediately before a proposal could ever be created.

**Context/reasoning:** An earlier draft put both checks inside `_eligible_non_responders()` (filtering on ledger state AND `config.exceptions` together). That made the "second, independent layer" this row's acceptance test calls for actually unreachable: a record for an excepted member is already dropped by that one function before anything downstream ever sees it, so a test proving the second layer works by handing the job a deliberately mislabelled record found nothing left to check -- the member had already vanished from the list, and the loop's own defensive branch was dead code a coverage tool would have to `pragma: no cover` around. Splitting the two checks into two different places means both are real, both run every time, and `test_on_leave_member_is_never_nudged_even_if_the_ledger_mislabels_them` exercises the second one directly rather than trusting that it would fire if it needed to.

## 2026-09-18 -- CHN-21: the nudge message is a fixed Python template, never a model call

**Decision:** `_render_nudge_message()` returns one of two fixed, deterministic strings (selected by ledger state: `NO_MESSAGE` vs. `POSTED_NO_UPDATE`), with only the channel's display name interpolated. There is no `p1.llm`/`p1.prompts` import anywhere in `p1.nudges`.

**Context/reasoning:** This row's own technology line is explicit: "Python (cap and eligibility) + Power Automate (delivery)" -- no model is named, unlike CHN-13/19's own rows which explicitly call out Claude for prose generation. A nudge is a short, low-stakes, structurally repetitive message where a template already says everything needed; introducing a model call here would add cost, latency and a retry/validation surface for a capability whose whole point is to be quick, polite, and predictable.
