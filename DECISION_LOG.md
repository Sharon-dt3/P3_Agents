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
