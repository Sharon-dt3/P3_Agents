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

## 2026-09-18 -- CHN-22: TeamsPublisher is a separate interface from TeamsReader

**Decision**: The write path (`TeamsPublisher`, with `post_channel_message`
and `post_direct_message`) is its own ABC in its own module, not a method
added to `TeamsReader` (CHN-03).

**Context/reasoning**: `teams_reader.py`'s own docstring already said "a
read credential behind this interface must never be able to post" before
this row existed. That guarantee has to be visible in the code shape
itself, not just in whichever Graph application permission happens to be
granted at deploy time -- a single merged interface would make it trivial
for a future capability to call `reader.post_message(...)` by accident,
because nothing in the type signature would stop it.

**Alternatives considered**: adding `post_channel_message`/
`post_direct_message` directly to `TeamsReader` and leaving it to callers
to only use them with a publish-scoped credential -- rejected because it
puts the permissions boundary entirely on programmer discipline rather
than on the interface.

## 2026-09-18 -- CHN-22: the mock is named LogPublisher, not MockTeamsPublisher

**Decision**: The mock implementation of `TeamsPublisher` is named
`LogPublisher`.

**Context/reasoning**: `docs/MASTER_IMPLEMENTATION_PLAN.md` (Section 9's
adapter table and Appendix H, both) already name this class `LogPublisher`,
ahead of it actually being built. Matching the plan's own naming keeps the
codebase and the documentation in sync, rather than introducing a
differently-named class (`MockTeamsPublisher`, matching `MockTeamsReader`'s
naming pattern) that a reader of the plan would then have to reconcile by
hand.

**Alternatives considered**: `MockTeamsPublisher`, for symmetry with
`MockTeamsReader` -- rejected once the master plan's own naming was found,
since the plan is the authoritative source for cross-cutting names like
this one.

## 2026-09-18 -- CHN-22: get_teams_publisher() has no scope-gate wrapper

**Decision**: `factory.get_teams_publisher()` returns a bare `TeamsPublisher`
implementation, with no equivalent of `get_teams_reader()`'s
`ScopedTeamsReader` wrapper.

**Context/reasoning**: `ScopedTeamsReader` exists to restrict WHICH channels
a reader may even see -- a read-side concern with no natural write-side
analogue. Every write this programme ever makes already goes through
SPN-09's `guarded_send()` first, at the call site, which refuses anything
whose proposal isn't `APPROVED`. An adapter-level gate here would duplicate
that check, not add a new guarantee, and would create two places a future
capability's write path would need to satisfy instead of one.

**Alternatives considered**: a `ScopedTeamsPublisher` wrapper restricting
which channels/members a given publisher instance may target -- rejected
as redundant with `guarded_send()`'s own target-aware logging and refusal,
and as a second source of truth that could drift from it.

## 2026-09-18 -- CHN-22: post_direct_message rename (correction to CHN-21)

**Decision**: `nudge_job.py`'s `send_fn()` and `_RecordingPublisher` in
`test_nudge_job.py` (both from CHN-21) call/implement `post_direct_message`,
not `send_direct_message`.

**Context/reasoning**: CHN-21 was built before CHN-22's interface existed,
using an ad-hoc method name (`send_direct_message`) since there was no
canonical `TeamsPublisher` to conform to yet. Researching CHN-22 against
`docs/MASTER_IMPLEMENTATION_PLAN.md` surfaced `post_direct_message` as the
plan's own canonical name. Rather than let CHN-21's call site and CHN-22's
interface disagree, CHN-21's two affected files were corrected in place as
part of this row's delivery -- a rename only, no behavior change, and all
of CHN-21's own tests were re-verified passing unchanged under the new
name.

**Alternatives considered**: giving `TeamsPublisher` a `send_direct_message`
method instead, to avoid touching already-committed CHN-21 files --
rejected because `post_direct_message` is what the master plan itself
names, and the WBS row for CHN-22 states it explicitly.

## 2026-09-18 -- CHN-22: PowerAutomateTeamsPublisher is not yet exercised against a live flow

**Decision**: `PowerAutomateTeamsPublisher` is written and unit-tested
against a mocked HTTP transport, but has never been run against a real
Power Automate flow.

**Context/reasoning**: No Power Automate flow has been provisioned yet --
the same status `GraphTeamsReader` already carries for CHN-01/CHN-03's read
side. The class is written against the documented shape of an
HTTP-triggered flow (one POST URL, one JSON body distinguished by
`action_type`) so it is ready to wire in once a flow exists, by setting
`POWER_AUTOMATE_FLOW_URL` and `TEAMS_PUBLISHER_MODE=power_automate`. Nothing
in the scored path (tests, eval, demo) depends on this class --
`LogPublisher` is what every test, eval and demo in this repo actually
exercises.

**Alternatives considered**: none -- provisioning a real flow is out of
scope for this row.

## 2026-09-18 -- CHN-23: escalation has no separate enable flag; it is gated by nudge history

**Decision**: `run_escalation_job` never escalates a member unless
`NudgeStore.has_ever_been_nudged(channel_id, member_id)` is already True
for them. There is no `escalation_enabled` field in `ChannelConfig`.

**Context/reasoning**: The row's own acceptance criterion is "nudge
precedes escalation" (GC7, landing in CHN-24). Rather than adding a
second config flag that a channel owner would have to remember to also
turn on, escalation is made strictly downstream of nudging: a channel
that never sets `nudge_enabled=True` (CHN-21's own default) can never
produce an escalation either, for anyone, because nobody in it can ever
satisfy `has_ever_been_nudged`. This makes the ordering guarantee
mechanical rather than a matter of running jobs in the right sequence
and hoping nobody reorders them later.

**Alternatives considered**: an `escalation_enabled` boolean alongside
`nudge_enabled` -- rejected as a second switch that could drift out of
sync with the first (enabled escalation with nudging off would let
someone be escalated without ever having been nudged, violating the
row's own acceptance test) and as unnecessary config surface for a
guarantee the nudge-history check already gives for free.

## 2026-09-18 -- CHN-23: never the excluded, checked twice independently -- built correctly from the start

**Decision**: `run_escalation_job`'s `_eligible_candidates()` filters
only the ledger's own `EXCLUDED` state (mirroring `_eligible_non_responders()`
in CHN-21's `nudge_job.py`), and the real, always-executed exceptions
check lives separately in the per-member loop, checking
`config.exceptions` directly before a streak is ever walked for that
person.

**Context/reasoning**: CHN-21 originally folded both checks into one
filter function, which made the loop's own "second layer" check
unreachable dead code -- caught only by a test that handed the job a
deliberately mislabelled ledger record. CHN-23 reproduces CHN-21's
final, corrected structure directly rather than repeating the same
mistake and needing the same fix a second time. The test file makes
the same distinction CHN-21's own tests do: the real-ledger test
(`test_excluded_member_is_never_escalated_via_the_real_ledger`) asserts
the excepted member produces no result at all (she's filtered before
the loop runs), while the defensive test
(`test_..._even_if_the_ledger_mislabels_them`) is the only one that
exercises the loop's own independent check and gets an explicit
`EXCLUDED_STATUS` result back.

**Alternatives considered**: none -- this is a direct application of
CHN-21's own documented lesson, not a new design question.

## 2026-09-18 -- CHN-23: the escalation idempotency key is the streak's own start date, not the day evaluated

**Decision**: an escalation's idempotency key is
`f"{channel_id}:{member_id}:{streak_start_date}"`, where
`streak_start_date` comes from walking the participation ledger
backward from the day being evaluated until it hits a day the member
contributed or was excluded -- not `f"{channel_id}:{member_id}:{date}"`
(the day the job happens to run on).

**Context/reasoning**: A missed-day streak keeps growing every working
day a person stays silent past the threshold. Keying on the evaluated
day would either re-escalate that same continuing streak every single
day past the threshold (spam, and the opposite of the "wrong once and
the agent is switched off" risk this whole programme is built around),
or require a second piece of bookkeeping to suppress repeats. Keying on
the streak's own start date means the key is stable for exactly as
long as the streak stays unbroken, and only changes once the person
actually breaks it (a real contribution) and then misses the threshold
again -- so `guarded_send()`'s own `ALREADY_SENT` branch is what
suppresses repeats, the same mechanism CHN-17/18's daily-digest
idempotency check already relies on, with no new bookkeeping required.

**Alternatives considered**: a per-day cap counter analogous to
`nudge_cap_per_day` -- rejected because there is no natural "per-day"
unit for an escalation the way there is for a nudge (a nudge is capped
at N *sends*/day; an escalation's natural cap is "at most one per
*streak*", which a counter doesn't express directly and a date-derived
key does.

## 2026-09-18 -- CHN-23: guarded_send's target is the owner, not the escalated member

**Decision**: `run_escalation_job` calls `guarded_send(..., action_type="escalation",
target=config.channel_owner_id, ...)` -- the write_log's `target`
column holds the owner's member_id, not the escalated person's.

**Context/reasoning**: SPN-09's own `write_guard.py` docstring already
documented this exact call shape (`action_type="escalation"/
target=owner_id`) before this row was built, alongside nudge's
`action_type="nudge"/target=member_id`. In both cases `target` means
"who received the Teams message" -- consistent across the two
capabilities -- rather than "who the action is about." The escalated
person's identity is still fully present and queryable: it's the
`member_id` inside the proposal's own payload, and the escalation's own
storage row (`escalations.member_id`) is keyed on them directly.

**Alternatives considered**: `target=member_id` (the escalated person),
for symmetry with "the subject of the action" -- rejected because it
would contradict `write_guard.py`'s own pre-existing documented
convention, and because `target`'s established meaning in this
codebase is already "message recipient," not "message subject."

## 2026-09-18 -- CHN-24: GC7 runs the real jobs end-to-end, with deliberate reruns, and recomputes every fact from the raw tables

**Decision**: GC7's fixture calls `run_nudge_job()` and `run_escalation_job()`
directly -- the real production functions, never a hand-simulated
shortcut -- and calls each one 3 times per day (simulating a scheduler
that reruns), approving proposals in between exactly as a human would.
`_measure_gc7()` then queries the `nudges` and `escalations` tables
directly with raw SQL rather than trusting either job function's own
return value.

**Context/reasoning**: calling the cap check and the cap-holds metric
the same number of times a real scheduler rerun would is what makes
"the cap holds" a claim about the *system*, not about a single
in-memory call -- a job that happened to be cap-safe on one call but
not on a rerun would pass a single-call test and still be broken in
production. Likewise, recomputing bob's per-day sent counts, carol's
nudge-row count, and the nudge/escalation ordering directly from
`nudges`/`escalations` rather than from `NudgeResult`/`EscalationResult`
objects means a bug that corrupted the job's own return value but not
its writes (or vice versa) can't hide behind a metric that only ever
asked the job to grade its own homework -- the same "independent
recomputation" posture GC9 and GC11 already established for the
narrative/weekly-rollup golden cases.

**Alternatives considered**: hand-building the nudge/escalation rows a
scenario would produce, without calling the real jobs -- rejected
because it would protect a model of the jobs' behaviour rather than the
jobs themselves, and would not have caught the fixture-completeness bug
this row's own build surfaced (see the entry below).

## 2026-09-18 -- CHN-24: a fixture with no message history before the test window corrupts a streak's computed start date

**Decision**: every GC7/escalation fixture that relies on a specific
`streak_start_date` seeds a real "anchor" contribution for the relevant
member on the last working day immediately before the test window,
not just on the days the scenario is actually about.

**Context/reasoning**: `_streak_dates_ending_at()`'s backward walk is
deliberately unbounded except for a generous safety cap
(`_MAX_STREAK_LOOKBACK_CALENDAR_DAYS`), so it is *correct* to keep
walking backward through any day with no ledger record for that
member. An empty fixture has no ledger record for any day before the
seeded window, so that walk finds "missed days" stretching back to the
safety cap instead of stopping at a real contribution -- corrupting the
computed streak start and, with it, every idempotency key derived from
it. This bit CHN-23's own tests first (fixed by anchoring dave and
bob), and recurred while building GC7 here: the fixture anchored
alice's history but not bob's, so bob -- who never posts at all in this
scenario -- got a phantom streak start far earlier than `GC7_MON`,
and `proposal_store.get_by_idempotency_key(f"...:bob:{GC7_MON...}")`
came back `None`. Fixed the same way: an anchor contribution for bob on
`GC7_FRI_PREV`.

**Alternatives considered**: bounding the walk to a short, fixed
lookback instead of a real backward search -- rejected in CHN-23
already, since it would either miscount a streak longer than the bound
or require a second mechanism to detect "streak longer than we can
see"; the anchor-fixture discipline is the cheaper fix and now applies
project-wide to any fixture exercising this code path.

## 2026-09-18 -- CHN-24: GC7-excluded-never-nudged proves the real-ledger outcome; the mislabelled-ledger unit test proves the defensive layer

**Decision**: GC7-excluded-never-nudged runs carol (permanently on the
exceptions list) through the real, non-mislabelled ledger and asserts
she has zero nudge rows of any kind across all three days. It does not
attempt to prove, by itself, that `run_nudge_job`'s own second,
independent `config.exceptions` check (the per-member loop's
"checked twice, independently" guarantee, see `nudge_job.py`'s module
docstring) is load-bearing.

**Context/reasoning**: confirmed by deliberate bug injection -- disabling
that second check in a sandboxed copy of `nudge_job.py` and rerunning
the eval left this metric passing unchanged, because
`_eligible_non_responders()`'s first-layer filter already removes
carol's EXCLUDED-state record before the per-member loop ever runs for
her in a real (non-mislabelled) ledger. This is not a flaw in GC7: it is
the same structural fact CHN-23 already documented for its own
excluded-member escalation test, and `nudge_job.py`'s own docstring
already anticipates it -- the second layer is "exercised by a test that
hands this job a deliberately mislabelled record to prove it, not a
copy of the first filter that would just agree with it every time,"
which is exactly what CHN-21/22's existing unit test
`test_on_leave_member_is_never_nudged_even_if_the_ledger_mislabels_them`
does. Golden cases and unit tests are doing two different jobs here:
GC7 protects the production-path acceptance criterion ("excluded
members are never nudged, full stop"), and the mislabelled-ledger unit
test protects the specific defensive code path that criterion doesn't
otherwise exercise.

**Alternatives considered**: extending GC7 to also hand the escalation
job a deliberately mislabelled ledger record, so one golden case proves
both layers -- rejected as redundant with the existing unit test, and
because mislabelling the ledger inside a golden case fixture would mean
GC7 no longer runs the real, trustworthy production path end-to-end for
its other two assertions (cap-holds, nudge-precedes-escalation).

## 2026-09-18 -- CHN-24: GC8 calls guarded_send() directly, and its send_fn raises rather than returning a sentinel

**Decision**: GC8's six checks create each proposal directly via
`ProposalStore.create()` and call `guarded_send()` directly -- never
through `run_nudge_job`/`run_escalation_job`/`run_daily_digest_job` --
with a `send_fn` that raises `AssertionError` if it is ever actually
invoked, rather than returning a value GC8 would then have to notice
was wrong.

**Context/reasoning**: calling `guarded_send()` directly, against the
service layer, is what this row's own text asks for -- proving refusal is
enforced at the one seam every write path shares, rather than
re-proving it separately inside each job's own tests. Making the
`send_fn` raise on invocation means a regression that let a pending or
rejected proposal's send through would not quietly show up as a
metric reading `False` next to a `True` target -- it would blow up the
eval run itself with an uncaught `AssertionError`, which is a strictly
louder and harder-to-miss failure mode than a silently wrong PASS/FAIL
line.

**Alternatives considered**: a `send_fn` that records whether it was
called and returns normally, with GC8 asserting the flag stayed
`False` -- rejected because it depends on GC8's own assertion being
correct to catch a regression, the same single point of failure the
raise-on-call approach removes entirely.

## 2026-09-18 -- CHN-24: GC12 changes both the roster and the window in one before/after comparison

**Decision**: GC12 reclassifies the exact same day's messages under
two different `ChannelConfig`s that differ in both `roster` (adds
carol) and `update_window_end` (narrows from 11:00 to 10:00) in a
single before/after comparison, rather than isolating one variable at
a time across two separate cases.

**Context/reasoning**: this row's own acceptance text asks to "change
the roster and the window" together, and the point of GC12 is to prove
the non-responder set is genuinely config-driven rather than
hard-coded anywhere -- a single combined comparison demonstrates both
facts move independently in one measurement (bob's state changes
because of the window; carol's presence changes because of the
roster) without doubling the number of golden cases. This only works
because `ClassificationStore.record()` upserts on `message_id`: the
same `TeamsMessage` objects can be reclassified under config B without
needing a second message fixture, so "same day's data, two configs" is
a literal re-run against the same rows, not two parallel fixtures that
could quietly drift apart.

**Alternatives considered**: two separate golden cases, one isolating
the roster change and one isolating the window change -- considered
more diagnostic if either ever regresses alone, but rejected for now
as more eval surface than this row asks for; can be split out later if
a regression in only one of the two ever needs isolating.

## 2026-09-18 -- CHN-25: Copilot Studio and Dataverse are a documented, tested connector contract, not a live integration

**Decision**: `src/p1/adapters/copilot_studio_connector.py` implements
the real backend contract a Copilot Studio custom connector's actions
would call (list/approve/reject/update_channel_config), and
`src/p1/adapters/copilot_studio_cards/*.json` are real Adaptive Card
1.5 documents whose `Action.Submit` data is checked against each
handler's request shape by a test -- but no Copilot Studio bot, no
Dataverse table, and no live Teams/Entra identity exist anywhere in
this repo. `docs/copilot_studio/connector_contract.md` states this
plainly rather than leaving it implied.

**Context/reasoning**: this is CHN-22's own precedent (a real
`PowerAutomateTeamsPublisher` class, implementing the real HTTP
contract, never exercised against a live flow) applied to a second
low-code Microsoft surface, for the same reason: this repo has no
Microsoft tenant to build or deploy either one into, so the honest and
useful thing to build is the seam a real integration would bind to,
proven correct on its own terms, rather than either skipping the row
or faking a tenant that doesn't exist. Cross-checking each card's
submitted keys against its handler's actual accepted keys
(`test_copilot_studio_connector.py`) means this doc/template pair
cannot silently drift from the code the way a hand-written contract
doc could -- the same "docs cannot outrun the code" discipline D10
asks for at the whole-repo level, applied here at the row that
introduces it.

**Alternatives considered**: skipping the Copilot Studio side entirely
and building only the Streamlit fallback -- rejected because the row's
own text asks for the connector contract specifically ("BEST FIT... the
channel owner who knows the roster lives in Teams"), and because the
equivalence proof this row's acceptance test asks for is strongest when
there are genuinely two independent call shapes (a JSON request dict
vs. Streamlit's own widget values) converging on the same service
calls, not one surface pretending to be two.

## 2026-09-18 -- CHN-25: approve_and_send()/reject() are the one seam; neither surface is allowed to touch ProposalStore or write_guard directly

**Decision**: `p1.approval.service.approve_and_send()`/`reject()` are
the only functions either surface (the Copilot Studio connector's
handlers, or `app/approval_dashboard.py`'s own button callbacks) is
allowed to call for a HITL decision. Neither surface imports
`ProposalStore`, `guarded_send`, or `write_guard` itself.

**Context/reasoning**: this is the actual mechanism behind "proving the
gate lives in the service, not the UI" -- not an assertion about
design intent, but a structural fact a reviewer can check by grep: if
neither surface ever imports the lower-level machinery, neither one
can special-case its own path through it, and the two calling into the
literal same function is what makes their resulting write_log/audit
rows the same shape by construction rather than by careful parallel
maintenance of two copies of the same logic.
`approve_and_send()` deliberately carries no `surface`/`caller`
parameter of any kind, for the same reason: a parameter that let a
caller identify itself would be exactly the seam a future special case
could be hung off of, even unintentionally.

**Alternatives considered**: a `surface` tag threaded through to the
audit row, for observability (so a demo could show "approved via
Teams" vs. "approved via Streamlit") -- rejected because it would make
the two surfaces' audit rows differ by construction, undermining the
one thing this row's acceptance test asks to prove; if that
observability is ever wanted, it belongs in a log line the calling
surface writes on its own, outside the audited call, never inside it.

## 2026-09-18 -- CHN-25: the config surface only writes roster, the update window, and exceptions -- everything else is still YAML-only

**Decision**: `ChannelConfigStore.update_channel_config()` accepts only
`roster`, `update_window_start`/`update_window_end`, and `exceptions`.
Every other `ChannelConfig` field (timezone, digest times,
`nudge_cap_per_day`, `escalation_threshold_days`, ...) has no write
path through this function at all, and stays committed-YAML-only,
changed only by a deploy.

**Context/reasoning**: this row's own text names exactly these three
fields as what "a channel owner maintains... without a deploy" --
scoping the write surface to match that list precisely means a channel
owner cannot accidentally (or via a compromised Copilot Studio card)
change something like `escalation_threshold_days` or the digest
schedule from a Teams adaptive card, fields whose blast radius and
review expectations are different from a roster or a leave list.
`get_effective_config()` still reads every field from the live DB
mirror (so a job always sees a consistent whole config), but the write
side is deliberately the narrower of the two.

**Alternatives considered**: exposing the whole `ChannelConfig` for
editing -- rejected as broader than this row asks for and a bigger
surface for an unreviewed change to do damage; can be widened field by
field later if a specific field earns it, same as any other scope cut
in this programme.

## 2026-09-18 -- CHN-25: get_effective_config() reads the DB mirror, not the committed YAML, so a live edit needs no deploy

**Decision**: `get_effective_config()` -- the read path
`approve_and_send()`'s escalation resend and both surfaces' config
forms use -- queries the `channel_config` table SQLite already
mirrors YAML into (CHN-02's own `sync_to_db()`), never the YAML files
`get_channel_config()`/`list_configured_channels()` read.

**Context/reasoning**: CHN-02's own `loader.py` docstring already
anticipated this split before CHN-25 was built ("Dataverse is added
later (CHN-25) purely as a human-editable surface on top of this --
never the source of truth"). Reading the DB, not the files, for the
live path is what makes "without a deploy" literally true: a process
that loaded its config from files at start-up would never see a
Teams-side edit until it restarted. A live-edited channel owner's
escalation target, specifically, is looked up this way rather than
from whatever the escalation's own payload snapshot said at creation
time -- an owner who changes AFTER a streak was flagged but BEFORE a
human approves it is escalated to the CURRENT owner, not a stale one,
the same "configuration is really configuration" principle GC12
already established for the non-responder set.

**Alternatives considered**: baking `channel_owner_id` into the
escalation's own payload at creation time (as nudge already does with
`member_id`) and resending to whichever owner that snapshot names --
rejected once the config surface existed, since it would mean an
approved-late escalation could go to someone who is no longer the
channel owner by the time a human approves it.

## 2026-09-18 -- CHN-26: the outcome record reuses CHN-13's own grounded facts, never a second independent read of the classification pipeline

**Decision**: `build_outcome_record()` takes the exact
`DailySummaryResult` `generate_daily_summary()` already produces --
the same grounded, retry-verified lines the Teams digest itself is
rendered from -- and serializes it into the published contract shape.
It does not call `gather_daily_facts()`, `build_ledger()`, or anything
else in the classification/participation pipeline a second time.

**Context/reasoning**: the master plan's own note on this row says the
record should carry "approved and classified items only." In this
codebase, the bar a fact must clear to be trustworthy enough to show a
human is SPN-06's grounding kernel (a resolvable `message_id`, and a
verbatim quote when one is claimed) -- a line that failed that check
never reaches `DailySummaryResult.section_lines` at all, it lands in
`dropped` instead. Reusing that same, already-verified result means the
outcome record can never be MORE permissive than what the digest itself
would show; a second, independent re-classification pass would risk
drifting from that bar, or duplicating the same model calls for no
reason.

**Alternatives considered**: computing the record straight from
`gather_daily_facts()` (skipping grounding entirely, since the record
carries `message_id`+`quote` provenance a human could check
independently anyway) -- rejected because it would mean a fact that a
human reviewing the digest would never see (because grounding dropped
it) could still reach P2 through this second channel, which is
precisely the kind of two-tier trust gap this whole codebase's
"grounding kernel as a load-bearing layer" design otherwise avoids
everywhere else.

## 2026-09-18 -- CHN-26: the record is not gated on the day's digest publish approval

**Decision**: `build_outcome_record()`/`write_outcome()` have no
dependency on CHN-17's own digest publish proposal or its approval
status. A channel's first-ever digest sitting `AWAITING_APPROVAL`, or a
digest a human actively rejected, does not block or skip that day's
outcome record.

**Context/reasoning**: the master plan's "approved... items only" note
is read here as being about which FACTS are trustworthy enough to
include (see the entry above), not as "only emit a record for a day
whose Teams post a human happened to approve." Coupling P2's entire
data feed to a decision about whether THIS channel gets a Teams
announcement today conflates two unrelated approvals -- "should this go
out as a Teams message" and "did anything happen in this channel
today" -- and would leave P2's morning brief blind on exactly the
channels a human is most likely to review carefully before approving
(new channels, on their first-ever publish). This is a judgment call
made without an explicit answer from the WBS row itself; flagged here
so it is easy to revisit if the intent was actually the stricter
reading.

**Alternatives considered**: gating `write_outcome()` on
`ProposalStore` showing that day's `daily_digest_publish` proposal as
`applied` -- rejected for the reason above; can be added later as an
opt-in flag if P2's own design ends up wanting it.

## 2026-09-18 -- CHN-26: the published schema is generated from the pydantic model, checked for drift by a test

**Decision**: `schema/outcome_record.v1.schema.json` is produced by
`scripts/generate_outcome_schema.py` from
`p1.contracts.outcome_record.OutcomeRecord.model_json_schema()`, never
hand-written, and `tests/unit/test_outcome_record_schema.py` fails if
regenerating it right now would produce something different from the
checked-in file.

**Context/reasoning**: the same "docs cannot outrun the code"
discipline CHN-25 applied to its adaptive card templates, applied here
to what this row calls out explicitly as "a published JSON schema" --
a hand-maintained schema doc could silently drift the moment a field
is added to `OutcomeRecord` without the schema file being regenerated;
a test that diffs the two makes that impossible to miss in review.

**Alternatives considered**: writing the JSON Schema by hand for
tighter control over its wording -- rejected, since pydantic's own
generation is both correct and automatically current, and the
row's emphasis ("published JSON schema") is about consumers having a
schema to validate against, not about hand-crafted prose in the schema
itself (the human-readable explanation lives in
`docs/outcome_record_contract.md` instead).

## 2026-09-18 -- CHN-26: emitting a record is a plain file overwrite, not a proposal -- nothing here goes through SPN-08/09

**Decision**: `write_outcome()` writes (or overwrites) a JSON file
directly. It creates no `Proposal`, calls no `guarded_send()`, and
writes no `write_log`/`audit` row.

**Context/reasoning**: SPN-08/09's proposal-and-write-guard machinery
exists for actions that SEND something to a person -- a channel post, a
DM. Writing a data file to this repo's own `outcomes/` directory sends
nothing to anyone; there is no send to gate, no human decision to
record, and no failure mode ("sent to the wrong person," "sent twice")
that machinery protects against here. Regenerating a day's record is
exactly as safe to call repeatedly as regenerating that day's digest
CONTENT already is (CHN-13's own idempotency key, `{channel_id}:
{date}:daily`) -- the analogy is to that content-generation step, never
to the separate publish-approval step layered on top of it.

**Alternatives considered**: routing `write_outcome()` through a
`Proposal` anyway, for a uniform "everything this system produces is
an approvable proposal" story -- rejected as adding approval-gate
ceremony around an action that has no recipient and nothing to refuse,
and because it would blur SPN-08's own scope (outbound actions) with a
plain internal data artifact.

## 2026-09-18 -- CHN-27: a flag-less eval run is tagged with a real model id and every prompt capability's real version, by default

**Decision**: `scripts/run_eval.py`'s `resolve_model_id()`/
`resolve_prompt_versions()` mean `uv run python scripts/run_eval.py`,
with no flags at all, now tags its committed run with
`p1.llm.gateway.DEFAULT_ANTHROPIC_MODEL` (a new constant, extracted
from `LLMGateway`'s own existing default parameter value rather than a
second copy of the same string) and with every prompt capability under
`prompts/` at its own current checked-in version --
`PromptRegistry.list_capabilities()` plus `.get(capability).version`
for each, not a hand-maintained list. `--model-id`/`--prompt-version`
still override these per-run, for reproducing a past run against an
older prompt or model deliberately.

**Context/reasoning**: before this row, `run_eval.py` defaulted both to
nothing (`model_id=None`, `prompt_versions={}`), so a committed run's
own timestamp/model/prompt-version story was only as complete as
whoever ran it remembered to make it with the right flags -- exactly
the kind of thing this row's own DoD ("results file committed with
timestamp, model ID and prompt versions") should not depend on a human
getting right by hand every time. Deriving both defaults from the same
single sources of truth the rest of the system already uses
(`LLMGateway`'s own default, `PromptRegistry`'s own file listing) means
the recorded metadata can't drift from what the system would actually
run with -- the same "docs/metadata cannot outrun the code" discipline
CHN-25/CHN-26 already applied to their own published artifacts.

**Alternatives considered**: leaving the CLI flags optional with no
defaults, and relying on a documented convention ("always pass
--model-id") -- rejected as exactly the kind of convention that erodes
the first time someone runs the script in a hurry; a default that is
always correct removes the failure mode entirely rather than
documenting around it.

## 2026-09-18 -- CHN-27: the README gets a headline eval-results section; the full status table stays CHN-30's job

**Decision**: this row adds a "## Eval results" section to README.md
quoting the latest committed run's headline numbers (34/34 metrics,
12/12 golden cases, timestamp, model id, prompt versions) and pointing
at `eval/results.jsonl` for the full history. It does not touch the
existing "## Status" capability table or the stale "Week 1, Day 1"
status line above it.

**Context/reasoning**: this row's own text asks only to "quote headline
numbers in the README"; the capability-by-capability status table is
explicitly CHN-30's own row ("Status table written FROM the code...
Written LAST, from the code"), and the README itself already says so
in a comment next to that table. Touching that table now, ahead of
CHN-29's edge-case pass, would mean writing status claims before D10's
own hardening work is done -- precisely the "README outruns the code"
failure mode D10's own risk register calls out.

**Alternatives considered**: updating the whole README's status
picture now, since the numbers are genuinely better than what it
currently claims -- rejected as scope creep into CHN-30's own row, and
because a status table written before CHN-28/29 (fix the worst
finding, edge-case pass) would already be stale by the time CHN-30
actually runs.

## 2026-09-18 -- CHN-28: the weakest metric wasn't the one closest to its threshold

**Decision**: the metric picked to fix is GC1-precision/recall
(`p1.eval.chn11_cases`), not GC3-citation-rate even though GC3 sits
exactly on its own boundary (0.95 measured against a 0.95 target, zero
margin). The real weakness found and fixed: of CHN-08's 8 deterministic
rules (`deleted_message`, `system_message`, `bot_post`, `not_on_roster`,
`thread_reply_not_counted`, `non_working_day`, `outside_update_window`,
`below_length_floor`), GC1's own hand-labelled ground truth
(`seed/fixtures/labels.csv`) only ever exercised 4 of them
(`deleted_message`, `system_message`, `bot_post`,
`outside_update_window`). The other 4 rules had zero representation --
not one example anywhere in the fixture set that they were supposed to
fire on -- so a regression in any of them (a flipped comparison in
`_rule_below_length_floor`, a deleted branch in `_rule_not_on_roster`,
`_rule_thread_reply_not_counted` always returning `None`) could never
show up in either GC1-precision or GC1-recall, no matter how badly the
rule engine broke, while both numbers kept reporting a perfect 1.0.

**Context/reasoning**: before settling on this, GC3 was investigated
first, since it's the only metric in the entire 34-metric harness
sitting with literally zero margin. Two things ruled it out. First,
`tests/unit/test_chn15_golden_cases.py::test_gc3_citation_rate_is_exactly_nineteen_of_twenty`
pins that exact arithmetic (19 real facts + 1 invented id = 0.95) with
its own docstring explaining this is deliberate -- "landing this metric
directly on the boundary it targets... the arithmetic the WBS's own
'>=0.95, not a typical 0.90' rationale is making a point about." Moving
that number would reverse a previous, deliberate, already-reasoned
design choice, not fix a defect. Second, and more fundamentally, GC3's
"drafted" lines are hand-authored in `_measure_gc3` itself (Method:
Python, no live model call) -- there is no production code path a real
fix could touch that would ever move this number at all; the only way
to change it is to edit the fixture, which is exactly what the pinning
test forbids without a real reason. GC1-recall's own "never gates"
design (target 0.0, `at_least`, mathematically always true) looked like
an even more obviously "weak" tautological check next -- but
`docs/MASTER_IMPLEMENTATION_PLAN.md`'s own C4 row says the target is
"reported" for recall, not a number, and CHN-11's own
`test_gc1_recall_target_never_gates_the_case_recall_is_reported_only`
already asserts this is deliberate ("a missed update is a nuisance, a
false 'no update' names an innocent person"). Gating recall with a real
numeric floor would override that explicit, authoritative spec, not fix
a bug in it.

What both investigations turned up instead: GC1's reported numbers,
gated or not, were resting on a ground truth that only ever tested half
of the rule engine they claim to certify. That is the actual weakest
thing in this harness -- not a number sitting near a line, but a
"PASS" that was structurally incapable of catching a regression in 4 of
8 rules.

**The fix**: added one new hand-authored example per previously-untested
rule, to the real committed fixtures (`seed/fixtures/messages.json`,
`seed/fixtures/labels.csv`), all dated 2025-06-12 to avoid every date
GC2 or `test_participation_against_fixtures.py` actually checks
(proj-alpha/2025-06-05, proj-beta/2025-06-11):
  - DIFF-ROSTER-01 (`not_on_roster`): james.okafor -- on proj-alpha's and
    proj-beta's rosters -- posts in proj-gamma, where he is not
    configured, exercising the "on this channel" half of roster
    membership that the existing `on_leave`/`departed` planted
    difficulties never touch.
  - DIFF-THREADOFF-01 (`thread_reply_not_counted`): elena.rossi replies
    in-thread to DIFF-LATE-01 in proj-beta, where
    `count_thread_replies=false` -- the mirror image of DIFF-THREAD-01,
    which proves the same rule's *other* branch (proj-alpha,
    `count_thread_replies=true`, reply stays eligible).
  - DIFF-SHORT-01 (`below_length_floor`): wei.chen posts "Done." (5
    characters) inside proj-alpha's window on an ordinary working day --
    on-roster, on-time, undeleted, non-bot/system, and excluded purely
    on length.
`chn11_cases._EXCLUDED_CATEGORIES` now includes all three new category
names; `_load_rule_ground_truth()` itself needed no other change, since
it already generically maps any listed category to `expected=True`.
`non_working_day` was deliberately left uncovered -- CHN-29's own
edge-case list already names "non-working day" as its scope, and
proj-alpha's already-configured but unused `non_working_dates` field is
exactly the hook that row will use; covering it here would be doing
CHN-29's job early with no coordination.

**Numbers, before and after** (`GC1-precision`/`GC1-recall`,
`_measure_gc1()`): before -- n=16, tp=7 fp=0 fn=0 tn=9, precision=1.0,
recall=1.0, but only 4 of 8 rules ever contributing a true positive.
After -- n=19, tp=10 fp=0 fn=0 tn=9, precision=1.0, recall=1.0, now with
7 of 8 rules contributing at least one true positive. The headline
numbers didn't move (the rule engine was already correct on every
category it was asked about) -- what changed is how much those
identical-looking "1.0"s actually vouch for. Precision itself never
moves from adding more *excluded*-class examples (a missed exclusion is
a false negative, not a false positive -- precision was already covered
by the 9 existing eligible/true-negative examples, each of which
implicitly proves no rule wrongly fires on it); what these three
examples strengthen is recall's own honesty, which is reported and
committed to `eval/results.jsonl` and now quoted in the README, even
though it isn't gated.

**Non-vacuousness proof**: backup-mutate-test-restore against
`src/p1/detection/rules.py`, one rule at a time -- disabling
`_rule_not_on_roster`, then (after restoring) `_rule_thread_reply_not_counted`,
then (after restoring) `_rule_below_length_floor`, each in turn, by
making the function unconditionally `return None`. Every single
injection dropped `GC1-recall` from 1.0 to 0.9 (fn: 0 -> 1) and left
`GC1-precision` at 1.0 unchanged, exactly matching the "a missed
exclusion costs recall, not precision" design this module's own
docstring already states. All three restores confirmed byte-identical
to the pre-injection file before moving to the next.

**Alternatives considered**: reversing GC3's deliberate boundary
arithmetic -- rejected, see above, this would erase a previous decision
rather than fix a defect, and there is no production code path GC3
exercises that a real fix could move anyway. Gating GC1-recall with a
real numeric floor -- rejected, contradicts
`docs/MASTER_IMPLEMENTATION_PLAN.md`'s own explicit "reported" spec and
CHN-11's own test asserting that's deliberate. Also covering
`non_working_day` in this same pass -- rejected, reserved for CHN-29
which already names it, to avoid two rows racing to plant the same
scenario.

**Also added**: `tests/unit/test_update_detection_against_fixtures.py`
gets three new dedicated assertions
(`test_message_not_on_roster_is_excluded_as_not_on_roster`,
`test_thread_reply_is_excluded_when_channel_does_not_count_them`,
`test_short_message_is_excluded_as_below_length_floor`), matching this
file's existing one-assertion-per-planted-difficulty style, so these
three rules have a permanent, individually-named regression test
outside the aggregate GC1 metric too.

## 2026-09-18 -- CHN-29: three of the eight scenarios were already proven; five weren't

**Decision**: before writing anything, each of the row's eight named
scenarios was checked against the existing test suite for a real,
dedicated proof -- not assumed missing, and not assumed covered just
because a fixture with the right shape existed somewhere. Three already
had one:
  - "A day with no messages in a channel" -- DIFF-SILENT-01 (proj-beta,
    2025-06-11) is exactly CHN-11's own `GC2-proj-beta-2025-06-11`
    (`test_gc2_measure_matches_hand_verified_expected_sets`): the full
    7-member roster lands as `no_message`, asserted as an exact-set
    match, not a proportion.
  - "Graph throttling and delta-token expiry" -- both already have
    dedicated, passing tests from earlier rows:
    `test_list_messages_retries_on_429_then_succeeds`,
    `test_list_messages_raises_after_exhausting_throttle_retries`,
    `test_list_messages_raises_on_expired_delta_token`
    (`tests/unit/test_teams_reader_graph.py`), and
    `test_expired_delta_token_triggers_a_clean_resync`
    (`tests/unit/test_ingestion_sync.py`, which also proves
    `sync_channel()`'s own clear-and-full-resync recovery, not just the
    reader raising).
  - "Malformed model output" -- `p1.llm.structured.generate_structured()`
    is the one shared validate-and-retry path every capability that
    needs typed output already goes through (CHN-09's classifier, CHN-13's
    daily summary, CHN-19's weekly narrative -- confirmed by reading all
    three, not assumed from the module's own docstring claim alone), and
    it is already covered by `test_retries_on_invalid_then_succeeds`,
    `test_raises_after_exhausting_attempts_never_defaults`
    (`tests/unit/test_structured_output.py`), and
    `test_invalid_label_retries_then_succeeds`
    (`tests/unit/test_classifier.py`). No new test was added for any of
    these three -- doing so would duplicate real, already-load-bearing
    coverage rather than close an actual gap, the same reasoning CHN-24
    already applied to GC7 vs. the pre-existing mislabelled-ledger test.

The other five had a *rule-level* or *ingestion-level* test each
(mostly from CHN-08/CHN-24's `test_update_detection_against_fixtures.py`
and CHN-05/06's `test_ingestion_sync.py`) but no *participation-ledger*
test at all -- nothing proving `p1.participation.ledger.build_ledger()`
itself handles them correctly end-to-end, which is what this row's own
"graceful, non-fabricating outcome" language is actually about. New
module: `tests/unit/test_participation_edge_cases.py`, five tests, all
against the real committed CHN-07 fixtures and the real
`detection.pipeline.classify_and_persist()` -> `build_ledger()` path,
never a hand-simulated ledger:

  1. **Non-working day** (DIFF-NONWORKING-01, proj-alpha, 2025-06-13,
     a Friday, not a weekend): `build_ledger` raises `NonWorkingDayError`
     rather than computing a fabricated non-responder set for a day
     nobody was asked to respond on -- the existing
     `test_non_working_day_raises` in `test_participation_ledger.py`
     only ever exercised a calendar Saturday, never the "configured,
     not a weekend" distinction the WBS text itself calls out. Also
     asserts the adjacent 2025-06-12 (an ordinary Thursday) does NOT
     raise, as a contrast.
  2. **Deleted-only-update** (DIFF-DEL-01, sara.johansson, proj-alpha,
     2025-06-03) -- the row's own text names this the scenario "that
     most easily produces a false accusation." Asserts her day reverts
     to a genuine `no_message`, never `posted_no_update`.
  3. **Edited after window close** (DIFF-EDIT-01, priya.sharma,
     proj-alpha, 2025-06-02) -- asserts she is a contributor (absent
     from the ledger entirely), proving the edit never disqualifies her
     on-time post.
  4. **Similar display names** (DIFF-NAME-01, proj-gamma, 2025-06-10) --
     olivia.dupree's 09:30 post is in-window and update-shaped
     (contributor); olivia.dupont, unrelatedly, also posts that day
     (proj-gamma-0189) but at 11:41, outside the 09:00-11:00 window
     (`posted_no_update`). Two almost-identically-named people landing
     in two different, individually correct states on the same day is
     the concrete proof against fuzzy/display-name-keyed attribution.
  5. **Departed tenant member** (DIFF-DEPART-01, sofia.almeida,
     proj-beta) -- posts through 2025-06-04, then nothing; Graph's own
     `members.json` no longer lists her at all. Asserts 2025-06-09 (a
     working day she's silent on) still carries a real `no_message`
     record for her, and asserts the scenario's own precondition (she's
     on `config.roster` but absent from live membership) directly rather
     than taking it on faith.

**Non-vacuousness proofs**, one per new test, each backup-mutate-verify-restore:
  - Non-working day: cleared `proj-alpha.yaml`'s `non_working_dates` ->
    the test's own precondition assertion failed immediately (it reads
    the real file, not a hardcoded date).
  - Deleted-only-update: disabled `ledger.py`'s `is_deleted` guard ->
    her state flipped from `no_message` to `posted_no_update`, proving
    this ledger-level check is a second, independent layer behind the
    rule engine's own `deleted_message` exclusion, not a redundant copy
    of it -- the same "checked twice, independently" shape CHN-21's
    nudge-exceptions check already has.
  - Edited after window: changed `calendar.local_datetime()` to prefer
    `edited_at` over `posted_at` -> priya.sharma's message then read as
    posted at 11:20 (past the 11:00 window close), which the shared
    `local_datetime()` also feeds to `detection.rules.evaluate_message`,
    so she flipped straight from contributor to a wrongly rule-excluded
    non-responder -- exactly the regression this planted difficulty
    exists to catch, and proof the shared calendar module (not two
    independent copies) is what keeps CHN-08 and CHN-10 agreeing.
  - Similar names: swapped which of the two olivias the test expects in
    which state -> the swapped assertion failed, proving the original
    assertion is sensitive to which specific person posted, not
    order-independent or accidentally always-true.
  - Departed tenant member: removed her from `proj-beta.yaml`'s roster
    (simulating the exact wrong fix -- "sync the roster to live
    membership") -> she vanished from the ledger's own precondition
    check entirely, the silent-drop failure mode this test exists to
    prevent.
  All five restores confirmed byte-identical to the pre-injection file
  before moving to the next.

**Alternatives considered**: writing all eight as brand-new tests
regardless of existing coverage -- rejected, since three would have
been pure duplication of already-load-bearing tests from CHN-05/06/08/09/
11/24, adding maintenance surface without adding any new protection.
Testing the five new scenarios via a hand-built in-memory `ChannelConfig`
and synthetic messages instead of the real CHN-07 fixtures -- rejected,
matching this project's standing discipline (see CHN-11, CHN-24, CHN-28):
a synthetic shortcut proves a model of the pipeline's behaviour, not the
pipeline itself, and these five planted difficulties already exist,
hand-verified, in the real fixture set for exactly this purpose.

## 2026-09-18 -- CHN-30: the status table is one row per traceability-table capability, verified by opening the file

**Decision**: README.md's new "## Status" table has exactly one row per
`docs/MASTER_IMPLEMENTATION_PLAN.md`'s own C1-C14 capability list (its
"Cap" traceability table), not one row per WBS task -- a WBS task
(CHN-17, CHN-22, ...) is an increment of *work*; a capability is the
unit the row's own DoD asks to verify ("every row in the status table
is verifiable by opening the named file"), and it's also the unit P2
and P3's own traceability tables will eventually reference back into
this one. Two supporting surfaces (the Copilot Studio UI, the eval
harness itself) don't map to any single numbered capability and are
called out in a short paragraph under the table instead of forced into
a row of their own.

**Context/reasoning**: every "Verify" cell was checked by actually
opening the named file on this machine before being written down, not
assumed from memory of having built it -- the same discipline CHN-28
already applied to "is this rule actually exercised" and CHN-29 applied
to "does this scenario already have a real test." One correction came
out of that check: the Graph-mode config flip is `TEAMS_READER_MODE=graph`
(`src/p1/adapters/factory.py`), not the `P1_TEAMS_READER` name first
drafted from memory -- caught and fixed before committing.

Three real, honest caveats came out of the same file-by-file check,
each recorded as a caveat rather than silently rounded up to "Done":
  - **C2** (Graph ingestion) and the write-side equivalent
    (`PowerAutomateTeamsPublisher`, under CHN-22 in Key decisions) are
    both fully written and unit-tested against a mocked transport, but
    neither has ever run against a real Microsoft endpoint -- CHN-01's
    admin consent is still pending, and no Power Automate flow has been
    provisioned. Marked **Partial** (C2) and called out explicitly
    (CHN-22), not folded into a blanket "Done."
  - **C4**'s GC1 still has zero rule-level ground truth for
    `non_working_day` specifically -- CHN-28 closed 3 of the 4
    previously-uncovered rules and deliberately left this one for
    CHN-29, and CHN-29 then proved the *ledger-level* refusal
    (`NonWorkingDayError`) rather than the *rule-level* classification.
    Both are real and correct, but they're not the same proof, and the
    Status table says exactly that rather than letting "Done" imply
    GC1 itself now covers all 8 rules.
  - **C7** (scheduled publishing) is fully built and tested
    (`run_daily_digest_job`, `build_scheduler`, GC6) but `make run` still
    prints a placeholder -- nobody has wired a standalone long-running
    process. This is real, undone work, not a documentation gap, so it's
    named as such rather than the Makefile being quietly left to imply
    otherwise.

`scripts/seed.py` and `scripts/run_daily.py` had their own docstrings and
print statements corrected to match reality (`seed.py` claimed "Fixture
data not yet implemented" when `seed/fixtures/` has held real, committed
fixture data since CHN-06/07; `run_daily.py` claimed "No daily job yet"
when CHN-17/18 built and proved one). Actually wiring `make run` into a
real standalone scheduler process was considered and rejected for this
row -- that's new capability-building work, not documentation, and this
row's own Method column ("Claude Code (drafted from the repo)") and
"Repo hygiene" bucket are about writing docs from the code that already
exists, not writing more code to make the docs true.

The **CHN-07 rework** flagged as still-open in
`docs/MASTER_IMPLEMENTATION_PLAN.md`'s §0 (written 2026-09-17, before
CHN-08 onward existed) was checked against the actual commit history and
found already resolved: the 2026-09-17 DECISION_LOG entry
"CHN-07: sheet 06's 15 planted difficulties are authoritative, not
'twenty'" shows the rebuild to source sheet 06's 15 categories already
happened. The master plan file itself is treated as a frozen, dated
planning snapshot (per its own header, "Status as of 2026-09-17") and
was not edited -- README.md's Status section is the current,
code-verified picture instead, and now says so explicitly rather than
silently repeating the master plan's stale flag.

**Scope cuts, collected**: the "Key decisions and scope cuts" section
in README.md is a synthesis, not new reasoning -- every item there
(CHN-01, CHN-07, CHN-17, CHN-22, CHN-25, C13/C14, GC1 recall) already
had its own full decision recorded earlier in this file; CHN-30's job
was to find all of them (checked every `## ` heading in this file
against the WBS row list, not just the ones remembered) and put a
one-line pointer to each in one place a reader doesn't have to search
1600+ lines for.

**Alternatives considered**: a WBS-task-level status table (CHN-01
through CHN-29, one row each) matching section 1's own style in
`docs/MASTER_IMPLEMENTATION_PLAN.md` -- rejected as the primary table,
since the row's own DoD frames verification in terms of capabilities,
and a 29-row task table would mostly restate what DECISION_LOG.md's own
per-row entries already say in more detail; kept the WBS framing out of
the *table* but folded task IDs into the Verify column and the scope-cuts
section instead, so both views are still recoverable from this one
document.

## 2026-09-18 -- CHN-31: `make run` didn't run anything -- a clean clone couldn't have passed this row as written

**The finding**: this row's own DoD is "clone into a fresh directory,
follow only the README, run the full flow against the mock adapter" /
"works with zero undocumented steps and no Graph credentials." Reading
`scripts/run_daily.py` and the README's own Quick start section before
touching anything showed `make run` printed a placeholder string
("[run] The daily-digest job itself is implemented ... this entry point
just doesn't call it yet") and did nothing else. A clean clone following
only the README would never see a real digest, a real ledger, or a real
outbound message -- the "run the full flow" half of this row's DoD was
false as of CHN-30, not merely underdocumented. This is exactly the
"real, undone work" CHN-30 explicitly deferred ("Wiring a
`scripts/run_daily.py` that actually starts the scheduler is real,
undone work -- it just isn't part of this row"), and CHN-31 is that
deferred row, not a reason to defer again.

**What was built**: `scripts/run_daily.py` now has a real,
dependency-injectable `run_full_flow()` that, for both allowlisted
channels (`proj-alpha`, `proj-beta` -- `proj-gamma` is not allowlisted
and is correctly never touched), on a fixed demo day inside the
committed fixture window (`2025-06-11`, an ordinary mid-window working
Wednesday for both channels, not the first or last day): ingests the
committed mock fixtures, runs CHN-08/09 detection, builds CHN-10's
ledger, and generates and publishes CHN-13/17's daily digest through
the exact same `p1.publishing.daily_job.run_daily_digest_job` every
unit test, GC6, and CHN-24/27's own "real runs" already exercise --
never a second, separately maintained demo path. `main()` is a thin
wrapper calling `run_full_flow()` with production defaults (the real
`LLMGateway`, the real `get_teams_publisher()`).

**Two judgment calls, both flagged rather than silently made**:

1. **Member rows.** `run_full_flow()` inserts `members` rows straight
   from the fixture data before ingesting messages -- the identical
   pattern already used, independently, in seven different
   `p1.eval.chn*_cases.py` modules (`chn11`, `chn12`, `chn15`, `chn16`,
   `chn20`, `chn24`). Investigating why surfaced a real, pre-existing
   gap: `p1.ingestion.sync.sync_all_allowlisted_channels` (CHN-05) syncs
   *messages* from a `TeamsReader` but has never had any member-sync
   capability at all, mock or Graph -- every eval module already works
   around this the same way, which is why the pattern was safe to
   reuse rather than a shortcut invented for this row. Building a real
   member-sync ingestion path (wiring `TeamsReader.list_channel_members`
   into `sync.py`) is real, new capability work and is deferred to its
   own future row, not built here -- named in README.md's Key decisions
   section so it isn't silently repeated as solved.
2. **Scope of "full flow."** `run_full_flow()` calls the real
   `run_daily_digest_job` (not a stub), which means a real digest
   genuinely requires one real Anthropic API call (the model turns
   already-computed facts into prose -- see `daily_summary.py`'s own
   docstring); this is normal product behaviour on the mock *Teams*
   path, not a Graph/tenant dependency, and was deliberately not
   papered over with a second, fake "demo-only" LLM gateway -- a demo
   that doesn't really call the model isn't proof the real flow works.
   `.env.example` already documents `ANTHROPIC_API_KEY` under "LLM
   Gateway," so this needs no new documentation, only the README's
   `make run` line being honest that this is what it now does.

**Non-vacuousness (bug injection)**: temporarily removed the
member-insertion block from `scripts/run_daily.py`, reran
`tests/unit/test_run_daily_full_flow.py` -- both tests failed with a
real `sqlite3.IntegrityError: FOREIGN KEY constraint failed` (never a
silent pass), restored the file byte-identical (`diff` confirmed) and
reran green. This is the same discipline every prior row's own
non-vacuousness check has used.

**Two tests, not one**, because a single "it ran" assertion would have
missed CHN-17's own idempotent-approval behaviour, which is exactly the
kind of "this looks done but silently sends unapproved" bug this row's
"no undocumented steps" DoD exists to catch:
  - a fresh DB's first run for both channels is `awaiting_approval`,
    with the mock publisher's log file never even created (proof
    nothing was silently sent);
  - approving both proposals and re-running the SAME day publishes
    (2 log rows); running a LATER day after that auto-approves and
    publishes with no second human step (2 more log rows, 4 total) --
    proving `has_ever_published()` is what actually gates this, not
    `approve()` alone, which the first draft of this test got wrong
    (see below).

**Errors and fixes while building this row**: the first version of the
"later day auto-approves" test asserted a later day was `published`
right after approving the first day's proposal, without re-running the
first day -- it failed, still `awaiting_approval`, because
`run_daily_digest_job` only calls `digest_store.mark_published()` on an
actual successful send, and `has_ever_published()` (the flag that
decides "does this channel get auto-approved") reads that, not the
proposal's `approve()` state. Fixed by re-running the approved first
day (which then genuinely publishes) before asserting anything about
the second day -- the corrected test is the one now committed. The
first attempt at the `ScriptedGateway` also failed once, returning the
classifier's `{"label", "confidence"}` shape for every call including
the daily-summary-section request, which needs `{"lines": [...]}`
(`DailySummarySectionDraft`) -- fixed by branching on
`tool_choice["name"]` (`"classification"` vs. anything else,
`generate_structured`'s own `tool_name` parameter), returning an empty,
schema-valid `{"lines": []}` for the summary case (no minimum length on
`DailySummarySectionDraft.lines`, and an honest empty section is this
module's own documented legitimate output, not a shortcut).

**What was NOT done by me, and why (this row's own Owner column says
"Human")**: I did not set a real `ANTHROPIC_API_KEY` and personally run
`make run` against my own live model call -- this project's standing
verification rule is that a live Anthropic call is never part of my own
verification, and I have no key of my own to use anyway. What I
verified instead, directly on this machine: `make install` / `make
seed` / `make run` reach the classifier/summary's model-call boundary
cleanly with zero `GRAPH_*` variable ever read anywhere on the path
(confirmed by reading `p1.adapters.factory.get_teams_reader` /
`get_teams_publisher`, both defaulting to mock with no Graph import
touched); and the full pipeline genuinely runs to completion, digest
and all, under the two committed tests above using a scripted (never
live) gateway. The one thing only a human can actually witness --
`make run` producing a real, model-written digest end to end with a
real key -- is exactly what CHN-31's own Owner column assigns to you: a
clean `git clone` into any fresh directory, `cp .env.example .env` with
your real `ANTHROPIC_API_KEY` filled in (nothing else), then `make
install && make seed && make run`.

**Alternatives considered**: building a genuinely fake, no-external-call
demo gateway (so `make run` needed zero credentials of any kind,
matching "reproducible" in the most literal possible sense) --
rejected, because a demo that fakes its own core capability isn't proof
the real flow works, and the row's own guidance names *Graph* tenant
access specifically, not the LLM call this product's actual value comes
from. Wiring `p1.publishing.scheduler` into a real standalone
long-running process so `make run` became indistinguishable from
production -- rejected as materially larger, unrelated new work; C7's
Status table caveat already names this honestly as separate, undone
work.

## 2026-09-18 -- Hotfix (found during CHN-31, filed separately): anthropic 1.5.0 dropped `temperature` from `Messages.create()`

**Not a WBS row** -- surfaced while doing CHN-31's own clean-clone
verification (`make run`'s first real, uncached LLM call), and kept out
of that row's commit on purpose: this touches `p1.llm.gateway`
(SPN-02), a shared foundation every capability from CHN-09 onward
depends on, and it changes a real behavioural guarantee (explicit
temperature pinning), not just documentation or a demo entry point. Filed
here as its own fix, per an explicit choice offered and taken: fix
`gateway.py` now, as its own commit, rather than folding it into CHN-31
or pausing for a longer investigation first.

**The finding**: `_call_anthropic` unconditionally sent
`"temperature": temperature` to `self._anthropic_client.messages.create(**kwargs)`.
The currently locked `anthropic` package (`uv.lock` pins `1.5.0`,
`pyproject.toml` says `anthropic>=1.5.0`) has removed `temperature` --
and `top_p`/`top_k` with it -- from `Messages.create()` entirely: not
renamed, not moved to `extra_body`, just gone. Confirmed three ways,
never by trial and error alone: `inspect.signature(anthropic.resources.messages.Messages.create)`
lists no such parameter; a repo-wide `grep -rn "temperature"` inside the
installed `anthropic` package returns nothing at all; and
`anthropic/types/message_create_params.py` (the SDK's own source of
truth for the request shape) has no `temperature`/`top_p`/`top_k` field
in its `TypedDict`. This is identical in a brand-new clone and in the
existing repo's own `.venv` right now -- not a clean-clone-specific
drift.

**The fix**: `_call_anthropic` no longer includes `temperature` in the
kwargs it builds. The parameter stays on `LLMGateway.generate()`'s own
signature (still folded into the cache key, still forwarded to
`_call_ollama`, which is unaffected -- Ollama's own API still accepts
it) so every caller and every existing test keeps working unchanged;
only what actually reaches the Anthropic client changed. **Honest
caveat**: this SDK version offers no replacement sampling-control
parameter at all, so explicit `temperature=0.0` determinism is no
longer enforceable on the Anthropic path -- the model now runs at
whatever its own default sampling behaviour is. This is disclosed here
rather than silently absorbed; if reproducible, low-variance model
output turns out to matter enough to chase further, that's a separate,
future investigation (an `extra_body` passthrough was considered --
see Alternatives below).

**New regression test**, `tests/unit/test_llm_gateway_anthropic_call_shape.py`
-- the reason this was invisible until a real call crashed is that
every existing gateway test (`test_llm_gateway.py`,
`test_llm_gateway_call_log.py`) monkeypatches `_call_provider` itself,
so none of them ever touched `_call_anthropic`'s real kwargs. The new
test substitutes a fake `_anthropic_client` (no real `Anthropic()`
construction, no network call, ever) and asserts every kwarg
`_call_anthropic` actually builds is a name the REAL, currently
installed SDK's own `Messages.create` signature accepts (read via
`inspect.signature`, plus the SDK's own generic escape hatches --
`extra_headers`/`extra_query`/`extra_body`/`timeout`) -- so a future SDK
upgrade that drops or renames another parameter fails this test at test
time, not at the next real demo.

**Non-vacuousness (bug injection)**: reintroduced `"temperature": temperature`
into `_call_anthropic`'s kwargs, reran the two new tests -- both failed,
one on the "sent an unsupported kwarg" assertion, the other on the
explicit "temperature is never forwarded" assertion. Restored
byte-identical (`diff` confirmed), reran green. Full suite: 396 passed
(394 + these 2 new tests), 2 skipped; ruff clean.

**Re-verified against the actual symptom**: reran `make run` (no `.env`,
no key in the shell) after the fix. It no longer raises
`TypeError: Messages.create() got an unexpected keyword argument 'temperature'`.
It now fails cleanly at `LLMGatewayError: ANTHROPIC_API_KEY is not set`,
which -- per `LLMGateway.generate()`'s own designed degrade-to-Ollama
fallback (SPN-02) -- retries against a local Ollama endpoint and fails
there instead with a plain `Connection refused`. That is existing,
documented gateway behaviour surfaced by CHN-31, not introduced by this
fix; a real `ANTHROPIC_API_KEY` now reaches a real classification/digest
call instead of crashing before ever sending one.

**Open thread, disclosed rather than resolved**: `eval/results.jsonl`'s
most recent entries (today, `run_at` 05:25:16 / 05:29:40 / 05:51:27
UTC) show `all_passed: true` with real-looking `model_id`s and
per-metric detail strings, which on their face means `scripts/run_eval.py`
made real, live, successful Anthropic calls through this exact
(previously broken) code path only 1-2 hours before this fix. `uv.lock`
was not touched today (last touched in the CHN-02/CHN-25 era) and
`data/cache/llm/` is empty and gitignored, so neither "the lockfile
changed" nor "a stale cache masked it" explains the discrepancy -- and I
was not able to resolve it further within this fix's own scope. Flagging
it plainly rather than asserting a cause I haven't confirmed: those
three results.jsonl entries' legitimacy is now an open question, and a
fresh `uv run python scripts/run_eval.py` run (with a real key, by a
human -- this project's standing rule is that I never make a live model
call as part of my own verification) would settle it either way.

**Alternatives considered**: passing `temperature` via `extra_body={"temperature": temperature}`
instead of dropping it -- rejected without evidence that the server-side
API still honours it there; the SDK's own request-shape source
(`message_create_params.py`) lists no such field anywhere, so this would
have been a guess, not a confirmed fix, exactly the kind of unverified
platform-behaviour assumption this project's own standing rule (use
AskUserQuestion / flag rather than guess) exists to avoid. Pinning
`anthropic` to an older, compatible version instead of changing
`gateway.py` -- not pursued without first knowing whether an older
version is even compatible with everything else pinned in `uv.lock`
(cache format, retry classes, etc.), and changing a locked dependency
version is a larger, riskier surface than removing one now-unsupported
kwarg from one call site.

## 2026-09-18 -- CHN-32: recording needs a real script, not a checklist of separate commands

**The finding, before building anything**: this row's own Method column
says "Human + screen recorder" -- the recording itself is not mine to
make (no screen capture, no live Teams tenant either way). What IS
mine is making sure every beat the WBS row lists is something a real,
already-existing production function can actually produce on demand.
Checking turned up the same class of gap CHN-31 found for the daily
digest: `run_nudge_job`, `run_escalation_job`, and
`generate_and_persist_weekly_rollup` are all real, tested functions,
but none had a standalone entry point -- only eval-case modules ever
called them, several (GC7/GC8/GC12) against entirely synthetic
channels built for clean, controlled test conditions, not the real
`proj-alpha`/`proj-beta` data a "genuine end-to-end run" implies.

**Two decisions asked and answered before writing code** (both stayed
with the recommended option): the live-permalink beat is narrated
honestly on camera as a well-formed, non-live URL (Graph consent still
pending, same disclosed status the README already carries) rather than
skipped or faked; and the nudge/escalation/weekly-rollup gap is closed
with one consolidated script, `scripts/run_walkthrough.py`, rather than
a checklist of separate `pytest -k` invocations.

**Finding real data for the nudge/escalation beats, not synthetic
data**: rather than reusing GC7's own purpose-built synthetic channel
(`gc7-channel`, fabricated alice/bob/carol), I queried `build_ledger()`
directly across proj-beta's entire real fixture window
(2025-06-02 through 2025-06-13) before writing any walkthrough code.
`sofia.almeida` (the same person CHN-29's "departed tenant member" test
already uses) turned out to have a genuine, naturally-occurring
7-consecutive-working-day silence starting 2025-06-05 -- nothing added
or adjusted, already sitting in the committed fixtures, and it clears
proj-beta's own `escalation_threshold_days` (2) on the second day on
its own. `kenji.tanaka`'s real, near-total "posted, but nothing
counted" pattern across the same window is what shows the OTHER nudge
wording. Using the real system's own real data for beats 7 and 8, not
a fabricated one, keeps the whole recording inside the same two real
channels beat 1 ingests -- no jarring third "channel" appearing mid-take.

**What `scripts/run_walkthrough.py` actually does**, in the WBS row's
own order: real production ingestion (`p1.adapters.factory.get_teams_reader()`
+ `p1.ingestion.sync.sync_all_allowlisted_channels()` -- the same
wiring GC5 proves, not CHN-31's own fixture-loading shortcut) for
proj-alpha/proj-beta, then explicit direct reads of proj-gamma and two
synthetic chat ids to show `ScopeViolationError` raised at the
boundary; a real rule-settled and a real model-settled classification
outcome printed side by side (2025-06-06, proj-alpha's busiest real
day); proj-alpha's ledger on 2025-06-05 (excluded/no_message/posted_no_update
all genuinely present that day); proj-alpha's daily summary with a
permalink line and the honest live-vs-mock narration cue; proj-beta's
weekly roll-up (week ending its own configured Thursday, 2025-06-12);
a first nudge pass on proj-beta (everyone's first-ever nudge held
pending), one member (`amara.okonkwo`) rejected by hand, sofia's
approved and resent, then her second consecutive day auto-approving;
and a real escalation run producing sofia's actual evidence-bundle
text (both real dates, both `no_message`, the real update window).

**Non-vacuousness (bug injection)**: removed the `proposal_store.reject()`
call for `amara.okonkwo`'s nudge in the new test's target script,
reran `tests/unit/test_run_walkthrough.py` -- failed exactly where
expected (`amara.okonkwo: rejected` never appears), restored
byte-identical (`diff` confirmed), reran green. Full suite: 397 passed
(396 + this one new test), 2 skipped; ruff clean.

**Errors and fixes while building the test**: the first `ScriptedGateway`
draft handled only the classifier's `"classification"` tool name
(CHN-31's own pattern) and returned empty `{"lines": []}` for
everything else, which made the weekly roll-up crash --
`WeeklyNarrativeDraft` requires a `narrative` field, not `lines`;
fixed by branching on `"weekly_narrative"` too. Once that was fixed,
the daily-summary permalink assertion still failed, because an empty
`{"lines": []}` response (valid, but contentless) never produces a
permalink line to check at all -- fixed by having the fake, for a
`"daily_summary_section"` request specifically, parse the real
`message_id` `p1.reporting.facts.render_facts_block` put in the prompt
and echo it back in a properly grounded line, so the permalink
rendering path is genuinely exercised rather than silently skipped.

**Not done, on purpose**: the eval-output beat is not called from
inside `run_walkthrough.py` -- it is `scripts/run_eval.py`, an already
real, already working command, meant to run as its own step in the
same recording rather than being wrapped a second time. And a `make`
target (`make walkthrough`) was added rather than leaving this as a
bare `uv run` invocation, matching `make run`/`make seed`'s own
convention.

**Alternatives considered**: reusing GC7/GC8's synthetic channel for
the nudge/escalation beats -- rejected once querying the real fixture
window showed a genuine, unforced streak already existed; a synthetic
channel would have been an easier build but a less honest "genuine
end-to-end run" than the row's own verify criterion asks for. A
checklist of separate `pytest -k` commands instead of one script --
asked about directly and declined in favor of the consolidated script,
for the same reason CHN-31 built a real entry point instead of leaving
`make run` a placeholder: a recording is a worse take with more cuts
and more chances to fumble a command live.

## 2026-09-18 -- CHN-32 CI fix: the walkthrough test only passed locally by accident

**Finding.** CI's `lint-and-test` run failed on a clean checkout:
`tests/unit/test_run_walkthrough.py::test_walkthrough_runs_every_beat_end_to_end`
-- `sqlite3.OperationalError: no such table: audit`, raised from
`ScopedTeamsReader._record_refusal()` while refusing proj-gamma in
beat 1. The test had passed locally (397 passed) every time it was
run before committing. Root cause: the test builds its own
`tmp_path/"test.db"` and passes it as `db_path=` to
`run_walkthrough()`, which correctly ran `init_db(db_path)` against
that path -- but the test does **not** pass a `reader=`, so
`run_walkthrough()` fell back to its default,
`reader = reader or get_teams_reader()`. `get_teams_reader()` had no
`db_path` parameter at all: it always built `ScopedTeamsReader(reader,
allowlisted_channel_ids)`, which itself defaults its own `db_path` to
`p1.storage.db.DEFAULT_DB_PATH` (`data/p1.db`) -- a completely
different file than the one `init_db()` had just migrated. Locally
this never surfaced, because `data/` is gitignored and every developer
machine that has ever run `make run` or `make walkthrough` already has
a real, migrated `data/p1.db` sitting in the repo root with an `audit`
table in it, so the reader's audit-write silently succeeded against
the *real* database instead of the test's isolated one -- the test was
never actually isolated, it was borrowing house state and reporting a
false pass. A clean CI checkout has no `data/` directory at all, so
`get_connection()` opened a brand-new, empty SQLite file with no
`audit` table, and the refusal write failed. This is the exact class
of bug CHN-31 exists to catch (a clean clone can't reproduce a result
that depends on leftover local state) -- CHN-31 just didn't happen to
cover this particular script.

**Fix.** `src/p1/adapters/factory.py`'s `get_teams_reader()` now takes
an optional `db_path: str = DEFAULT_DB_PATH` and threads it into the
`ScopedTeamsReader` it constructs, instead of relying on that class's
own default. Every existing caller that passes nothing is unaffected
(same default, same behaviour). `scripts/run_walkthrough.py`'s
`run_walkthrough()` now calls `get_teams_reader(db_path=db_path)`
instead of `get_teams_reader()`, so a caller (a test, or a future
script) that supplies its own `db_path` gets a reader whose audit
writes actually land in that same database.

**Non-vacuousness (bug injection).** Moved `data/` aside entirely (a
true clean-clone simulation, not just deleting one file) and ran the
full suite: 397 passed, 2 skipped -- confirms the fix holds with no
leftover local state to hide behind. Then reverted only
`run_walkthrough.py`'s one-line change (kept the `factory.py` fix) and
reran `test_run_walkthrough.py`: failed with the identical
`sqlite3.OperationalError: no such table: audit` CI had reported,
proving that line is the load-bearing half of the fix, not the
`factory.py` signature change alone. Restored the fix (byte-identical
to the working version via a kept backup), reran: 397 passed, 2
skipped again. Ruff clean throughout. Finally moved the real `data/`
directory back into place and ran the full suite once more to confirm
normal (non-clean-clone) local behaviour is unchanged.

**Not done, on purpose.** `tests/unit/test_run_walkthrough.py` itself
was not changed -- it doesn't need to pass an explicit `reader=` now
that the default one it gets is correctly bound to its own `db_path`.
Left `get_teams_reader()`'s other two call sites
(`tests/unit/test_teams_reader_mock.py`,
`src/p1/eval/chn12_cases.py`) untouched -- both already call it with
no arguments and rely on its default, which is unchanged.

**Alternatives considered.** Making the test pass its own
`ScopedTeamsReader(MockTeamsReader.from_fixtures(), [...], db_path=db_path)`
directly, bypassing `get_teams_reader()` entirely -- rejected, because
CHN-32's own script docstring makes a point of exercising
`p1.adapters.factory.get_teams_reader()` specifically, the same
production wiring GC5 proves, "not a second, demo-only code path" --
patching the test around the bug would have undermined that claim
instead of fixing it.

## 2026-09-18 -- CHN-01's own "next step," finally built: the device-code sign-in script

**Finding.** CHN-01's entry above already named this exact next step
("run a device-code-flow script to fetch one real Teams channel
message via Graph") -- but no such script existed anywhere in the
repo: no `msal` dependency, no file. One test docstring
(`tests/live/test_chn09_live_classification.py`) even referenced this
step as though it were already handled. It wasn't. Surfaced while
answering the user's question about what's actually left before a
live demo is possible, not discovered by building toward a row.

**What was built.** `scripts/graph_login.py`: runs Microsoft's own
device-code sign-in flow via `msal.PublicClientApplication` (added as
a new dependency, `msal>=1.39.0`), using `AZURE_TENANT_ID` /
`AZURE_CLIENT_ID` from `.env`, and writes the resulting access token
into `.env`'s `GRAPH_ACCESS_TOKEN` line in place (every other line
untouched). `scripts/graph_smoke_test.py`: a deliberately tiny,
read-only next step -- lists the real channels a token/team can see,
then previews (author + timestamp only, never message text) one page
of real messages, but only for a channel_id already on this repo's own
allowlist, enforcing the same allow-by-default-refuse discipline
CHN-04's scope gate enforces everywhere else, even though this script
talks to Graph directly and doesn't go through `ScopedTeamsReader`.
Neither script touches ingestion, detection, digests, nudges, or
anything that sends. Both are unit-tested (`tests/unit/test_graph_login.py`,
`tests/unit/test_graph_smoke_test.py`) against a fake MSAL app / fake
`GraphTeamsReader` respectively -- no real network call, no real
interactive login, ever happens under pytest, the same "written,
tested against a fake, never run live" discipline as `GraphTeamsReader`
and `PowerAutomateTeamsPublisher` themselves.

**Judgment calls, flagged.** (1) No `AZURE_CLIENT_SECRET` is used or
requested anywhere in this path -- a device-code flow is Microsoft's
public-client (secret-less) login mechanism by design, so the
`.env.example` field of that name is for a different, not-yet-built
flow, not this one; this needs the app registration's "Allow public
client flows" setting turned on, which is an Azure-portal action nobody
has confirmed yet. (2) `graph_login.py` mints a short-lived (~1 hour)
token and stops there -- it does not attempt silent token refresh,
token caching, or any unattended renewal; re-running the script by
hand is the whole story for now. A real always-connected setup would
want MSAL's token cache and a refresh strategy, deliberately deferred
rather than guessed at here. (3) The user chose (via direct question)
to point the very first live test at a real project channel rather
than a dedicated sandbox channel -- `graph_smoke_test.py`'s
allowlist-gated, read-only, no-message-text design is shaped
specifically around that choice, to keep the actual first live touch
as low-risk as it can be regardless.

**Non-vacuousness (bug injection).** `write_token_to_env`'s in-place
`.env` rewrite: first draft of `main()` called it without passing
`env_path`, so it silently used the real module-level default instead
of a test's monkeypatched path -- caught immediately by
`test_main_happy_path_writes_env_and_reports_expiry` failing exactly
that way (asserting the token landed in a tmp file, finding the tmp
file untouched). Fixed by having `main()` pass `env_path=ENV_PATH`
explicitly. Bug-injected the revert afterward to confirm: reverting
that one line reproduces the identical failure, restoring it passes
again. Ran the full suite with `data/` moved aside entirely (a true
clean-clone simulation, learned from the CHN-32 CI fix immediately
above this entry) -- 413 passed, 2 skipped, before restoring the real
`data/` directory and confirming normal behaviour is unchanged. Ruff
clean throughout.

**Not done, on purpose.** Wiring a real Team/channel into
`config/channels/*.yaml`, flipping `TEAMS_READER_MODE=graph` for the
actual pipeline, and building real member-sync into
`sync_all_allowlisted_channels` (the pre-existing, separately disclosed
gap noted in CHN-31/CHN-32's own entries) are all still explicitly
deferred to their own next steps, gated on admin consent actually
landing first -- building further on top of an unconfirmed permission
would be guessing, not building.

**Alternatives considered.** A client-credentials (app-only secret)
flow instead of device-code -- rejected, since CHN-01 explicitly chose
delegated permissions via a real signed-in identity ("Option A"), and
a secret-based flow would silently reintroduce the tenant-wide,
higher-consent-bar shape ("Option B") that decision deliberately
avoided.

## 2026-09-18 -- CHN-25 taken further: a real, internet-hostable HTTP API

**Finding.** A tool-doctrine audit (the user checking every row's
assigned tool against what was actually built) surfaced this as the
sharpest gap in the whole repo: the doctrine names Copilot Studio +
Dataverse as the "BEST FIT" for approvals/config, and neither was ever
built or provisioned -- only a documented, tested connector contract
existed, callable only in-process from a test or from Streamlit. There
was no real HTTP surface anywhere in this repo at all, so even with
tenant access and licensing, there was nothing yet for a Power Platform
custom connector to actually point at.

**What was built.** `src/p1/api/copilot_studio_api.py`: a FastAPI app
wrapping `p1.adapters.copilot_studio_connector`'s four existing
handlers as real HTTP endpoints (`/list_pending_approvals`, `/approve`,
`/reject`, `/update_channel_config`), plus `/health`. Every endpoint is
a thin adapter -- request JSON in, the same handler call, response JSON
out -- no business logic duplicated or reimplemented. `fastapi` and
`uvicorn` added as dependencies. `tests/unit/test_copilot_studio_api.py`
drives the whole thing via FastAPI's own `TestClient` (in-process, no
real socket) -- auth enforcement (fail closed when unconfigured, 401 on
a wrong/missing key), HTTP status translation for the two real error
modes the handlers can raise (`ProposalNotFoundError` / unknown
channel_id -> 404, a bad exceptions payload -> 400), and full
happy-path round trips through `/approve`, `/reject`, and
`/update_channel_config` against an isolated (tmp_path, chdir'd)
database and a fixture channel config, ending in a real
`publisher.post_direct_message()` call recorded and asserted on.

**Judgment calls, flagged.** (1) Auth is a single shared `X-API-Key`
secret, not a per-user identity check -- `connector_contract.md`
already disclosed there is no live Teams/Entra identity for
`approver_id`/`updated_by` to come from yet, so a shared secret is what
stands between "anyone with the URL" and "only something holding the
key" until real identity binding exists; this is a real, named scope
cut, not represented as more than it is. (2) The app fails CLOSED
(500, refuses every action) if `COPILOT_STUDIO_API_KEY` is unset,
rather than failing open -- chosen deliberately over a default/dev key,
since an approval-granting endpoint with no secret at all would be a
worse failure mode than one that simply refuses to start serving
actions. (3) `db_path`/`config_store`/`publisher` are never part of
this API's wire contract, matching the connector module's own
documented seam philosophy -- a real caller (Copilot Studio, or a
test) only ever supplies what `connector_contract.md` documents, never
implementation details like which database file to use.

**Non-vacuousness (bug injection).** Reverted the fail-closed check to
fail open (auth only rejected a WRONG key, not a missing configuration)
and reran the test suite -- `test_action_endpoint_fails_closed_when_no_api_key_is_configured_at_all`
failed exactly as expected, for the right reason (the request no
longer stopped at the auth layer at all). Restored (byte-identical via
a kept backup), reran: passing again. Full suite run with `data/`
moved aside entirely (a true clean-clone simulation): 422 passed, 2
skipped. Ruff clean throughout.

**Not done, on purpose.** No Copilot Studio agent, no Dataverse table,
and no hosting of this API anywhere Microsoft's cloud could actually
reach it -- all three still require a human with real Power Platform
access in the tenant's maker portal, and a separate hosting decision
this row doesn't make (Azure App Service vs. a tunnel vs. something
else). This row's whole job was removing the "there's no real HTTP
surface at all" blocker, not completing the remaining, genuinely
external steps.

**Alternatives considered.** A Flask app instead of FastAPI -- rejected,
since FastAPI generates a real OpenAPI/Swagger document for free
(`/openapi.json`), which is exactly the artifact a Power Platform
custom connector imports to define its actions; hand-writing that
document for Flask would be redundant, error-prone effort for no
benefit. Embedding the API directly into the existing Streamlit process
-- rejected, since Streamlit is not an HTTP API framework and conflating
the two surfaces would undo the "no surface-specific parameter" design
this row's own acceptance test already proves.

## 2026-09-18 -- SPN-02 extended: AWS Bedrock as a third LLM provider

**Finding.** The user was provisioned real Claude model access, but via
AWS Bedrock rather than a direct Anthropic API key -- AWS-style
credentials (access key ID, secret access key, region, and a Bedrock
inference-profile ARN identifying the model) rather than a single
`ANTHROPIC_API_KEY` string. `p1.llm.gateway.LLMGateway` had no branch
for this at all: `LLM_PROVIDER` only ever recognized `anthropic` and
`ollama` (see `_call_provider`'s dispatch, pre-existing). Note: the
credential email the user received had its actual
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` values still as unfilled
template placeholders (`<new access key ID>` etc.) -- flagged to the
user directly, not something this row's code can route around; only
`AWS_REGION` and `BEDROCK_MODEL_ID` from that email were real, usable
values, and both are now in `.env`.

**Build.** Added `_call_bedrock` alongside the existing `_call_anthropic`,
both now backed by one shared `_call_messages_api` (previously
`_call_anthropic`'s own body) -- confirmed via `inspect.signature` that
`anthropic.AnthropicBedrock` exposes the exact same
`anthropic.resources.messages.Messages` class as the direct `Anthropic`
client (same signature, byte for byte), so this is a genuine auth-layer
swap in the same SDK, not a second API shape to maintain. `LLMGateway`
gained four new constructor params /  env vars:
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_REGION`/`BEDROCK_MODEL_ID`
(explicit config in, matching every other adapter in this repo -- never
AWS's ambient default credential chain). `pyproject.toml`'s
`anthropic>=1.5.0` became `anthropic[bedrock]>=1.5.0`, which pulled in
`boto3`/`botocore` (required for AWS SigV4 request signing) -- without
this extra, a real Bedrock call fails at import time with
`ModuleNotFoundError: No module named 'botocore'` (confirmed directly:
this is exactly the error the bug-injection pass below surfaced when
the missing-config guard was removed and a real `AnthropicBedrock()`
client got far enough to try signing a request).

**Judgment calls.** (1) `generate()`'s degrade-to-Ollama-on-exhaustion
path previously only triggered for `provider == "anthropic"`; widened to
`provider in ("anthropic", "bedrock")` so either cloud provider falls
back to the same local Ollama path on failure. This is a real behavior
change, not just new code alongside old -- both a real bug-injection
target and now covered by `tests/unit/test_llm_gateway_degrade.py`,
which previously didn't exist for *either* provider (the anthropic
degrade path had no direct test before this row; adding it once, for
both, closes a real pre-existing gap rather than leaving it
half-covered). (2) A consequence of that same widening, deliberately
kept rather than special-cased: a misconfigured Bedrock provider
(missing AWS config) raises `LLMGatewayError` from `_call_bedrock`,
which `generate()`'s degrade path then catches the same way it catches
an exhausted real call -- it silently degrades to Ollama instead of
surfacing the AWS config problem loudly. This mirrors the exact,
already-documented behavior CHN-31 found for a missing
`ANTHROPIC_API_KEY` (see that entry and the README's CHN-31 bullet) --
kept consistent across both providers rather than giving Bedrock a
different, special-cased failure mode. `test_missing_aws_config_raises_before_touching_the_network`
therefore calls `_call_bedrock` directly, not `generate()`, to test the
guard in isolation from the degrade path that would otherwise mask it.

**Non-vacuousness (bug injection).** Two separate injections, both
reverted from the same before/after backup file: (a) removed the
missing-AWS-config guard entirely -- `test_missing_aws_config_raises_before_touching_the_network`
failed as expected, and failed with the real, literal
`ModuleNotFoundError: No module named 'botocore'` before the
`anthropic[bedrock]` extra was added (confirming the guard's absence
really would have let a broken client construction through, not just
skipped a check that never mattered); (b) reverted the degrade
condition back to `!= "anthropic"` -- `test_bedrock_degrades_to_ollama_on_exhaustion`
failed as expected. Restored byte-identical, reran: both pass. Full
suite: 431 passed, 2 skipped, ruff clean. Clean-clone simulation
(`data/` moved aside entirely, then restored): 431 passed both times,
identical to the repo's normal state.

**Not done, on purpose.** No real Bedrock call has ever been made --
same "written, tested against a fake, never a real network call under
test" status as every other adapter in this repo. The user's actual
AWS access key ID and secret access key are still placeholders in the
credential email she received; nothing here can be exercised against a
real AWS account until she obtains the real values (flagged to her
directly) and pastes them into `.env`'s `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`.

**Alternatives considered.** Hand-rolling AWS SigV4 request signing
directly (e.g. with `httpx` + a manual signer, matching `_call_ollama`'s
own plain-`httpx` style) -- rejected, since `anthropic`'s own
`AnthropicBedrock` client already does this correctly, is the
officially supported path, and sharing `_call_messages_api` with the
direct-Anthropic path means the request-building/retry/parsing logic
genuinely only has to be correct once, not maintained twice.

## 2026-09-18 -- CHN-01's real test channel added; a real regression found and fixed along the way

**Finding.** Added `config/channels/p1-agent-test.yaml` -- a genuine
third allowlisted channel (the user's own real Teams channel, created
specifically to test this project against), alongside the existing two
fixture-style channels (`proj-alpha`, `proj-beta`). Roster is real (one
person: the channel creator), timezone `Asia/Colombo`, update window
08:00-17:00 -- all user-supplied. Digest timing, working days, and
`nudge_enabled: false` are defaults matching the other test channels,
not yet confirmed by the user; flagged to her as adjustable.

Doing this surfaced a real, previously-latent bug, found the honest
way -- by breaking the test suite, not by hunting for it. Earlier in
this same session, `TEAMS_READER_MODE=graph` was written into `.env`
(intended to prepare for a real Graph connection once the user's
sign-in and admin consent land). That single `.env` change alone,
independent of this channel addition, made the full test suite attempt
a REAL network call to Microsoft Graph: `scripts/run_daily.py`,
`scripts/run_walkthrough.py`, and the tests that exercise them all
build their reader via `p1.adapters.factory.get_teams_reader()`, which
reads `TEAMS_READER_MODE` straight from `os.environ` with no test-time
override -- so with that var set to `graph` in `.env`, every one of
those tests tried to construct a real `GraphTeamsReader` against the
placeholder `GRAPH_ACCESS_TOKEN=live-token` and hit this environment's
egress proxy (`httpx.ProxyError: 403 Forbidden`) instead of a mocked
reader. This is exactly the class of thing this project's own standing
rule exists to prevent (a live external call sneaking into
verification) -- caught here only because the sandboxed proxy refused
the request; against a real, permissive network it would have
attempted a genuine unauthenticated call to Microsoft's servers from
inside a test run.

**Fix, this session.** Removed `TEAMS_READER_MODE` from `.env` again
(reverted to unset, which defaults to `mock` -- see `factory.py`).
Confirmed this alone fixed 5 of the 7 failures the full suite showed.

**The remaining 2 failures were real, and about this row's own change.**
`tests/unit/test_run_daily_full_flow.py` hardcodes an assertion that
the real, full-flow demo touches exactly `{proj-alpha, proj-beta}` and
never gamma -- by design, proving the demo respects the real
allowlist. Adding a genuine third allowlisted channel made that
assertion stale, correctly: the demo now (correctly) also touches
`p1-agent-test`. Updated both tests in that file: renamed
`test_run_full_flow_runs_both_allowlisted_channels_end_to_end` to
`test_run_full_flow_runs_all_allowlisted_channels_end_to_end` (the name
`...both...` was no longer true), widened the expected channel set to
include the new channel, and updated the second test's approval loop
and published-count assertions (2 -> 3 per day) to match. This is not a
production bug -- production code is working exactly as designed; the
test's own hardcoded expectation was what fell out of date.

**Judgment calls.** (1) Renamed the first test rather than leaving a
now-inaccurate name in place -- checked first that nothing in
README.md or DECISION_LOG.md references that test by name. (2) Did NOT
harden `get_teams_reader()`/the test suite against `TEAMS_READER_MODE`
being read from the real, live `.env` -- that's a real, still-open gap
(any future real `.env` change to this var will silently affect the
test suite again), but fixing it (e.g. tests explicitly forcing mode to
`mock` regardless of `.env`, or the test suite loading a separate,
test-only env file) is a genuine design decision of its own, not
something to fold silently into this row. Flagged to the user directly
rather than built unasked.

**Non-vacuousness.** This one didn't need synthetic bug injection --
the regression was real, observed directly (7 real failures, not a
staged one), diagnosed to its true root cause (confirmed by removing
just the `.env` line and rerunning), and the remaining 2 failures were
independently confirmed to be caused specifically by the new channel
config (by reading their assertions, not guessing). Full suite: 431
passed, 2 skipped, ruff clean, both with and without a clean-clone
simulation (`data/` moved aside and restored).

**Not done, on purpose.** `TEAMS_READER_MODE` stays unset (mock) in
`.env` for now -- it should only be set to `graph` right before an
actual intended live run against Teams (e.g. once the user has a real
`GRAPH_ACCESS_TOKEN` and wants to run `scripts/graph_smoke_test.py` or
`make run` for real), not left set permanently, until the test-isolation
gap above is separately fixed.

## 2026-09-18 -- CHN-05's real member-registration gap, closed

**Finding.** README.md's CHN-31 entry already named this honestly as a
real, pre-existing gap: `sync_all_allowlisted_channels` (the real
ingestion path, used by a live Graph sync) had no member-sync
capability of its own. What that gap actually meant in practice, found
while preparing `p1-agent-test` for a genuine live run: `messages.author_id`
is a foreign key into `members(id)` with `PRAGMA foreign_keys = ON`
(see `p1.storage.db`) -- so ingesting a real message from anyone not
already known to the database would crash the entire sync outright
with `sqlite3.IntegrityError: FOREIGN KEY constraint failed`, not just
display a blank name. The only things that ever populated `members`
were `scripts/run_daily.py`, `scripts/run_walkthrough.py`, and
`p1.eval.chn12_cases`, each separately pre-inserting rows from their
own committed fixture authors before calling into ingestion -- none of
which helps a real Graph sync, where the authors aren't known ahead of
time.

**Build.** Moved member-registration into `MessageStore.upsert_messages()`
itself (`p1.storage.messages_repo`) -- the one place every reader's
messages actually pass through, mock, Graph, or fixtures alike.
`_ensure_member_exists()` does `INSERT OR IGNORE INTO members (id,
display_name) VALUES (author_id, author_id)` before the message insert,
for any non-null `author_id` -- the exact same fallback pattern all
three existing call sites already used, generalized rather than
reinvented. A `None` author_id (a bot/system message with no sender,
already a real, tested case) is left alone entirely, matching the
column's existing nullable FK.

**Judgment calls.** (1) Used the author_id itself as a placeholder
display name, since `GraphTeamsReader._parse_message` only reliably
extracts a sender's `id` from Graph's delta message payload, not a
display name -- `list_channel_members()` (already written, never
wired into ingestion) could fill in a real one later without this path
needing to change at all, since `INSERT OR IGNORE` never overwrites an
existing row (proven directly by
`test_an_already_known_member_is_never_overwritten`). Wiring
`list_channel_members()` into ingestion for real display names is a
deliberate non-goal of this row: it needs a different Graph permission
scope (`ChannelMember.Read.All` or similar) than `ChannelMessage.Read.All`
already requested, which would mean a second, separate admin-consent
round-trip -- not worth it for what is, for `p1-agent-test`, a
single-person roster already known and named in its config. (2) Left
the three existing call sites' own manual member-seeding in place
rather than removing them -- harmless now (`INSERT OR IGNORE` makes
them pure no-ops once this row's fix runs first), and removing them
was out of scope for closing this specific gap.

**Non-vacuousness (bug injection).** Removed the one line calling
`_ensure_member_exists` and reran the new tests:
`test_ingesting_a_never_before_seen_author_no_longer_crashes` failed
with the exact real error a live run would have hit --
`sqlite3.IntegrityError: FOREIGN KEY constraint failed`. Restored
byte-identical, reran: passing again. Full suite: 434 passed, 2
skipped, ruff clean, both with and without a clean-clone simulation
(`data/` moved aside and restored).

**What this actually unblocks.** Previously, even with a perfect,
working `GRAPH_ACCESS_TOKEN` and a correctly allowlisted channel, the
very first real message `scripts/run_walkthrough.py` (or any future
live-run entry point built on `sync_all_allowlisted_channels`) tried to
ingest from `p1-agent-test` would have crashed the whole run. That
class of failure is now impossible -- any author, known or not, ahead
of time or not, can be ingested cleanly.

**Not done, on purpose.** `scripts/run_daily.py` (the `make run` demo
entry point) still loads its messages from committed fixtures, not a
real Teams connection -- deliberately: the master plan's own submission
checklist requires the scored path run from a clean clone with zero
credentials and no tenant (see docs/MASTER_IMPLEMENTATION_PLAN.md
Appendix J and R3's risk mitigation), so `make run` staying
fixture-based is required, not a shortfall. `scripts/run_walkthrough.py`
is the one that already goes through the real path
(`get_teams_reader()` + `sync_all_allowlisted_channels()`) and is what
an actual live run against `p1-agent-test` will use, once a real token
exists.

## 2026-09-18 -- CHN-25's Copilot Studio backend, made to actually work end to end

**Finding.** Standing up the real Copilot Studio custom connector against
the live `copilot_studio_api` app (via ngrok) surfaced two real gaps that
no existing test caught, because every test in
`tests/unit/test_copilot_studio_api.py` called `init_db()` (directly or
via `_seed()`) before ever touching the app -- something no real
deployment path did for it automatically:

1. **Every action endpoint 500'd against the real, on-disk `data/p1.db`**
   with `sqlite3.OperationalError: no such table: proposals`. That file
   existed (auto-created empty by `get_connection()`'s
   `sqlite3.connect()` the first time anything touched it) but had never
   had a single migration applied -- nothing before this row ever called
   `run_migrations()`/`init_db()` as part of actually starting the
   server, only as part of test fixtures, `scripts/seed.py`, or the two
   fixture-driven walkthrough/demo scripts.
2. Testing the connector for real from Power Platform's own "Test
   operation" panel (not just via `curl` with a hand-added header) hit
   ngrok's free-tier interstitial warning page even on POST requests
   with a real API key -- confirmed directly: `Content-Type: text/html`,
   a literal `<!DOCTYPE html>` body, on every action call.

**Build.**
1. `src/p1/api/copilot_studio_api.py`: replaced the FastAPI app's plain
   construction with a `lifespan` context manager (the modern
   replacement for the deprecated `@app.on_event("startup")`, which
   ruff/FastAPI both flagged) that calls `init_db()` before the app ever
   serves a request. `run_migrations()` is idempotent (tracked via its
   own `schema_migrations` table), so this is always safe to run on
   every single startup, not just a fresh deploy's first one.
   `tests/unit/test_copilot_studio_api.py::_client()` was updated to
   actually enter the `TestClient`'s own context manager (a bare
   `TestClient(app)` silently never runs ASGI lifespan at all, which is
   exactly how every existing test masked this gap without meaning to);
   the three tests that didn't already `monkeypatch.chdir(tmp_path)`
   picked up one, so the lifespan's `init_db()` never touches the real
   repo's `data/p1.db` during a test run.
2. Her actual, already-running `data/p1.db` was one-time-fixed directly
   by running `uv run python scripts/seed.py` against it (all 5
   migrations applied, `[seed] Database initialised` confirmed) -- the
   code fix above means this manual step is never required again for
   any future deployment, including a from-scratch one.
3. The ngrok interstitial is Power-Platform-connector-side, not
   FastAPI-app-side: added a "Set HTTP header" policy template
   (`ngrok-skip-browser-warning: true`, applied to every request) on the
   custom connector itself, in the Power Platform maker portal --
   nothing in this repo needed to change for this half, since it's
   entirely about what ngrok's free tier does to *any* request lacking
   that header, regardless of caller.

**Judgment calls.** (1) Used `lifespan` over keeping
`@app.on_event("startup")` -- both work identically for this purpose,
but `on_event` is deprecated in the FastAPI version this repo pins, and
"complete everything, real" is a bad time to leave a deprecation warning
sitting in a file freshly touched for exactly this. (2) Fixed the three
tests that didn't isolate their cwd via `tmp_path`/`chdir`, rather than
leaving them and accepting that the app's own tests would mutate the
real repo's `data/p1.db` on every test run -- once `_client()` started
actually entering the lifespan, this stopped being a hypothetical risk.

**Non-vacuousness (bug injection).** Replaced the lifespan's `init_db()`
call with a bare `yield` (schema-init removed, nothing else touched) and
reran: `test_starting_the_app_against_a_brand_new_database_does_not_500`
failed with the exact real error a live, never-initialised deployment
hits -- `sqlite3.OperationalError: no such table: proposals`. Restored
byte-identical, reran: passing again, 10/10 in this file, 435 passed / 2
skipped across the full suite, ruff clean.

**Verified live, not just in tests.** After both fixes: the Power
Platform connector's own "Test operation" panel round-tripped
`health_health_get` (200, real `application/json` body, not the ngrok
interstitial) and `list_pending_approvals_list_pending_approvals_post`
(200, `{"approvals": []}` -- correctly empty, since no real Teams
ingestion or digest cycle has produced a live proposal yet, not an
error).

**Not done, on purpose.** The connector's remaining 3 operations
(`approve`, `reject`, `update_channel_config`) were not individually
re-tested from the Power Platform Test panel after this fix, since they
share the exact same auth/db-init code path already proven by
`list_pending_approvals` and by their own existing
`test_copilot_studio_api.py` coverage -- there is no proposal to
approve/reject yet with zero real ingested data, and manufacturing a
fake one through the live connector (rather than through a real digest
cycle) would test nothing this row's fix is actually about.

## 2026-09-18 -- CHN-25's Copilot Studio connector, made solution-aware and wired into the live agent

**Finding.** After the schema-init and ngrok-header fixes (previous entry,
same day), restarting `make copilot-api` with the `--reload-dir src`
Makefile fix (also this entry) confirmed the reload-storm class of hang
can't recur, and both `health_health_get` and
`list_pending_approvals_list_pending_approvals_post` re-verified live at
200 through the Power Platform Test panel. The next real step -- wiring
the "P1 Channel Approvals" custom connector into the "P1 Channel
Intelligence" Copilot Studio agent as a Tool -- immediately hit a genuine
blocker: Copilot Studio's "Add a tool" dialog rejected every one of the
connector's 5 operations with a raw, unlocalized error string
(`agentContent.addToolCustomConnectorNotSolutionAware`), not a cosmetic
glitch -- the connector had been created directly in the environment's
default Dataverse context rather than inside a solution, and Copilot
Studio's tool-attachment flow requires a custom connector to be
solution-aware before it can be attached as a tool (confirmed against
Microsoft's own custom-connector-in-solutions documentation).

**Build.**
1. Root-caused the `uvicorn --reload` hang from the terminal log she
   pasted: `uv run` had silently rebuilt her `.venv` (stale interpreter
   symlink), and the unscoped `--reload` watcher treated the ~79-package
   rebuild as source changes, causing an endless restart loop that
   looked like a hung server. Fixed permanently in the `Makefile`'s
   `copilot-api` target by adding `--reload-dir src`.
2. Created a new unmanaged Dataverse solution, "P1 Channel Intelligence"
   (publisher: DT3 Cloud Integrations, matching the publisher already
   used for her other Copilot Studio agent solutions in this
   environment), and added the existing "P1 Channel Approvals" custom
   connector into it via Power Apps' "Add existing" > Automation >
   Custom connector flow. This made the connector solution-aware without
   touching its definition, its host, or anything in this repo.
3. Re-opened "Add a tool" on the "P1 Channel Intelligence" agent (after a
   hard page reload, since the stale error banner persisted client-side
   until then) and added all 5 connector operations as Tools: Health,
   List Pending Approvals, Approve, Reject, Update Channel Config.
   Verified via a second full reload (agents list -> reopen) that all 5
   persisted server-side, not just in client state.

**Judgment calls.** (1) Created a dedicated new solution rather than
adding the connector to one of the pre-existing unrelated solutions in
this environment ("Meeting Agent", "AWS Integration for Copilot") --
those belong to different projects, and mixing an unrelated custom
connector into them would make future solution exports/imports for
either project pull in components that don't belong. (2) Added all 5
operations as Tools, including `Health` -- asked the user directly
(AskUserQuestion) whether to include the connectivity-probe operation
alongside the 4 real action operations, since this determines what
capabilities the live production agent gets exposed to; she chose all 5.

**Non-vacuousness.** N/A for the solution/tool-wiring change itself (no
code path to bug-inject -- this is Power Platform/Dataverse
configuration, not application code). The reload-storm fix was already
bug-injection-verified in the prior entry; this entry only confirms it
held on a real restart.

**Verified live.** `health_health_get` (200, `{"status": "ok",
"api_key_configured": true}`) and
`list_pending_approvals_list_pending_approvals_post` (200,
`{"approvals": []}`) both re-tested from the Power Platform Test panel
after the Makefile fix and server restart -- schema validation succeeded
on both, confirming the restart picked up every fix from the same day's
earlier entry. All 5 Tools confirmed attached to the live "P1 Channel
Intelligence" agent after a hard reload (agents list -> reopen), not
just visible in an unsaved client-side state.

**Not done, on purpose.** The agent's own instructions/prompt were not
updated to describe when to call these new tools -- that's a separate,
later step (teaching the agent when/how to use the approval tools in
conversation), not part of making the connector reachable at all. The
Dataverse table for channel config (the other half of CHN-25) is still
not built.

## 2026-09-19 -- CHN-01 follow-up: GraphTeamsReader's real permission surface, and a second Alfred escalation

**Finding.** The first live `graph_smoke_test.py` run (after CHN-01's
`ChannelMessage.Read.All` consent landed and "Allow public client
flows" was enabled) failed with a genuine, non-network `403 Forbidden`
on `GET /teams/{id}/channels` -- not a token problem. Checked
Microsoft's own Graph API docs: `list_channels()` (called by both
`src/p1/ingestion/sync.py` and the scope-gate's own `list_channels()`
filtering) needs `Channel.ReadBasic.All` at minimum;
`ChannelMessage.Read.All` only ever covered `list_messages()`. A
further check of `list_channel_members()` (used by the scope-gate's
per-channel membership enforcement) found it needs
`ChannelMember.Read.All` -- but also found, via
`storage/messages_repo.py`'s own comment, that `list_channel_members()`
is written and unit-tested against the mock but not actually called by
any live code path yet.

**Build.** Added `Channel.ReadBasic.All` and `ChannelMember.Read.All`
as delegated Graph permissions on the `p1-teams-intelligence` app
registration (user's own action, Azure Portal). Updated
`scripts/graph_login.py`'s `GRAPH_SCOPES` and its docstring twice in
the same session: first to request all three scopes, then -- once it
became clear `ChannelMember.Read.All` is both blocked on admin consent
(only Alfred can grant it) and unused by any live path -- reverted to
requesting only `ChannelMessage.Read.All` and `Channel.ReadBasic.All`,
leaving `ChannelMember.Read.All` configured-but-unrequested with a
comment explaining why. Updated `tests/unit/test_graph_login.py`'s
scope-list assertion to match, twice, for the same reason.

**Second blocker found.** Re-running `graph_login.py` with the
two-scope set still failed at Microsoft's sign-in screen with "Need
admin approval" -- even though `Channel.ReadBasic.All`'s own row in
Azure's API permissions table shows "Admin consent required: No". This
means the DigitalT3 tenant has a consent policy requiring admin
approval for any new permission grant to this app, overriding the
per-permission flag (a tenant-wide "user consent disabled" style
setting, not visible or changeable from this app registration's own
blade). This is the same class of blocker as CHN-01's original one,
now recurring for the two additional scopes: only Alfred can unblock
it, by clicking "Grant admin consent for DigitalT3 Software Services
Pvt Ltd" once on this app's API permissions page -- a single click
that consents everything currently configured (`Channel.ReadBasic.All`,
`ChannelMember.Read.All`, `ChannelMessage.Read.All`, `User.Read`).

**Judgment calls.** (1) Chose to request only the two scopes actually
needed by a live code path today, rather than blocking further work on
all three landing at once -- reversible in one line once
`ChannelMember.Read.All` is both consented and wired into a real
feature. (2) Did not attempt any workaround for the tenant consent
policy (a different flow, a different account, etc.) -- per this
project's standing rule against bypassing access controls, the only
correct path is asking the actual tenant admin.

**Non-vacuousness.** N/A -- this is a live Azure AD/tenant
configuration blocker, not application code; nothing here was
testable by bug injection. The `403` and the "Need admin approval"
screen are both real, observed failures against the live tenant, not
simulated.

**Verified.** Full test suite (435 passed, 2 skipped) and ruff clean
after both `graph_login.py` scope-list changes.

**Not done, on purpose.** A live Graph read is still not proven
end-to-end -- blocked entirely on Alfred granting admin consent for
`Channel.ReadBasic.All` (and, whenever it's actually wired in,
`ChannelMember.Read.All`). No code change can substitute for that.

## 2026-09-19 -- CHN-01/CHN-05: ingestion no longer needs Channel.ReadBasic.All at all

**Finding.** Asked directly whether `Channel.ReadBasic.All` (the
permission the previous entry escalated to Alfred) is really needed.
It genuinely was, as the code stood: `sync_all_allowlisted_channels()`
discovered which channels to sync by calling `reader.list_channels()`
against Graph. But `config/channels/*.yaml` already names every
allowlisted channel_id by hand -- the same source `ScopedTeamsReader`
itself builds its allowlist from -- so Graph's enumeration was never
telling the ingestion path anything it didn't already know from its
own config. `list_messages()` only ever needs `ChannelMessage.Read.All`
(already granted), and only needs a channel_id, which config already
provides.

**Build.** Changed `sync_all_allowlisted_channels()`
(`src/p1/ingestion/sync.py`) to take an explicit `channel_ids`
argument instead of calling `reader.list_channels()` -- callers now
pass `ChannelConfigStore().list_allowlisted_channels()` directly.
Updated both callers: `src/p1/eval/chn12_cases.py`'s GC5 (which
already computed that exact list for its own assertions) and
`scripts/run_walkthrough.py`'s beat 1 (now takes `(ALPHA, BETA)`
explicitly; kept its own narration line calling `reader.list_channels()`
directly, since that's illustrative-only against the mock reader and
costs nothing -- only the *production* sync loop needed to stop
depending on Graph's version of that call).

Also updated `scripts/graph_smoke_test.py` to match: it no longer
calls Graph's `list_channels()` to discover the team's channels either.
It now reads the allowlist straight from `config/channels/*.yaml` and
attempts `list_messages()` on each entry directly, reporting per
channel_id whether Graph accepted or rejected it. Added a
`config_store` seam to `run_smoke_test()` (same pattern as its existing
`reader_factory` seam) so tests never touch this repo's real committed
configs. Rewrote `tests/unit/test_graph_smoke_test.py` around the new
behavior (temp-dir configs via `ChannelConfigStore`, a fake reader that
can raise `httpx.HTTPStatusError` per channel_id) -- 6 tests, including
one proving a rejected channel_id doesn't stop the others in the list
from being tried.

Net effect: neither the real ingestion path nor its own acceptance
test needs `Channel.ReadBasic.All` at all now. The permission stays
configured on the app registration (added last entry, never consented)
in case a future feature genuinely needs live channel enumeration --
nothing currently does.

**Judgment calls.** (1) Kept `TeamsReader.list_channels()` in the
interface itself (still used by `MockTeamsReader`/tests/the demo
narration) -- only stopped the *production sync path* and the smoke
test from calling it against Graph. (2) The smoke test trades away
something real: it can no longer show every channel Graph can see on
the team, so discovering a new real channel_id now means reading it
by hand from Teams' own "Get link to channel" URL (the same way
`GRAPH_TEAM_ID` was obtained) rather than from this script's own
output. Flagged directly in the script's docstring and in-terminal
messaging rather than silently dropped.

**Non-vacuousness.** Real bug injection, not synthetic: temporarily
changed GC5's call to pass `list(allowlisted) + ["19:proj-gamma@thread.tacv2"]`
as `channel_ids` (simulating a config-reading bug that let an
out-of-scope channel through) and re-ran
`test_gc5_zero_out_of_scope_messages_after_a_full_ingest` --  it failed
immediately with a real `ScopeViolationError` raised by the scope gate
at the reader boundary, proving GC5's hard-zero assertion still
depends on a genuine, independent safety check (the scope gate), not
merely on trusting whatever list the caller happens to pass in.
Reverted immediately after confirming the failure; re-ran clean.

**Verified.** Full suite 436 passed, 2 skipped (was 435 before this
entry -- one new test added), ruff clean, all 34 golden-case metrics
still PASS via `scripts/run_eval.py` (including both GC5 checks), and
`scripts/run_walkthrough.py` re-run end to end to confirm beat 1's
ingest-and-refuse behavior is unchanged.

**Not done, on purpose.** `ChannelMember.Read.All` is untouched by
this entry -- still configured-but-unconsented, still blocked on
Alfred, still unused by any live path (see the immediately preceding
entry). A live Graph read is still not proven end-to-end; this entry
only removes one of the two permissions blocking it. The other,
`ChannelMessage.Read.All`, was already granted -- so once
`config/channels/p1-agent-test.yaml`'s real channel_id
(`19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2`, added
in an earlier session) is the only thing the next `graph_smoke_test.py`
run needs to succeed against.

## 2026-09-19 -- graph_login.py's scope list was never actually updated after the ingestion refactor

**Finding.** The smoke test's next real run still hit two separate,
unrelated problems, both self-inflicted oversights from earlier the
same day. First: `graph_login.py`'s `GRAPH_SCOPES` still requested
`Channel.ReadBasic.All` -- the immediately preceding entry removed
every *caller's* dependency on that permission, but never touched the
one place that actually requests it at sign-in, so re-running
`graph_login.py` would still have hit the same tenant-wide "Need admin
approval" wall as before, for a permission nothing needs anymore.
Second, and what actually surfaced first in practice: the smoke test
returned `401 Unauthorized` for every channel_id, including the real
one -- not a permission problem at all. The `.env` token in place was
still the very first one from earlier in this session (device-code
`HG49KVTCM`, ~72-minute validity), because every later `graph_login.py`
attempt had requested a scope set the tenant refused before ever
producing a fresh token -- so `GRAPH_ACCESS_TOKEN` was simply stale.

**Fix.** Reverted `GRAPH_SCOPES` to `["ChannelMessage.Read.All"]` only
-- the sole permission anything in this codebase actually calls live,
confirmed by this same day's ingestion refactor. Updated
`scripts/graph_login.py`'s docstring to state this plainly, and
`tests/unit/test_graph_login.py`'s scope assertion to match (renamed
the test accordingly). This scope was already tenant-consented from
CHN-01's original grant, so the next `graph_login.py` run should
neither need Alfred nor hit the admin-approval screen -- and should
produce a fresh, valid token, fixing the `401` as a side effect.

**Judgment calls.** None beyond the immediately preceding entry's --
this is a direct, mechanical follow-through of that decision (the
scope this script requests should always match what live code
actually calls), not a new tradeoff.

**Non-vacuousness.** N/A -- straightforward scope-list correction and
docstring update, covered by the existing scope-assertion test
(`test_acquire_token_requests_only_channel_message_read_all`), not new
application logic.

**Verified.** `tests/unit/test_graph_login.py`: 10 passed. Full suite:
436 passed, 2 skipped. Ruff clean.

**Not done, on purpose.** Still not proven end-to-end -- the user needs
to actually re-run `graph_login.py` (fresh token) and
`graph_smoke_test.py` (real read) for this to be confirmed live, not
just theorized from the code.

## 2026-09-19 -- CHN-01's first real live Graph read, confirmed -- and a smoke-test crash fixed along the way

**The milestone.** After this session's earlier permission/scope work
landed (a fresh token via `scripts/graph_login.py`,
`ChannelMessage.Read.All` already consented, `Channel.ReadBasic.All`
no longer needed by anything), `scripts/graph_smoke_test.py` read one
real page of real Teams messages from `config/channels/p1-agent-test.yaml`'s
real channel_id
(`19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2`) against
the real DigitalT3 tenant. This is CHN-01's own acceptance test finally
satisfied for real, not against `MockTeamsReader` -- the first
genuine, live Microsoft Graph read this project has ever made.
`GraphTeamsReader`, written and unit-tested against a mock since
CHN-03, has now round-tripped against the real API it was written for.

**A real bug found immediately after, the honest way.** The very next
channel in the allowlist, `config/channels/proj-alpha.yaml`'s
mock-fixture id (`19:proj-alpha@thread.tacv2`, never a real Graph id),
crashed the whole script with an unhandled `DeltaTokenExpiredError`
traceback instead of being reported and skipped. Root cause:
`GraphTeamsReader.list_messages()` raises `DeltaTokenExpiredError` for
*any* bare `410` Graph returns -- which happens for a channel_id Graph
can't resolve at all, not only for a genuinely expired delta token --
and this script's own `except` clause only caught
`httpx.HTTPStatusError`, an oversight from when the two-scope
`Channel.ReadBasic.All`-dependent version of this script was rewritten
earlier the same day.

**Fix.** Widened `graph_smoke_test.py`'s per-channel `except` clause to
catch `(httpx.HTTPStatusError, DeltaTokenExpiredError)` together --
both mean the same thing here (Graph didn't accept this channel_id),
so both are reported and the loop continues to the next allowlisted
channel rather than crashing. Added
`test_run_smoke_test_treats_delta_token_expired_the_same_as_a_rejection_and_keeps_going`
to `tests/unit/test_graph_smoke_test.py`, extending `_FakeGraphReader`
with a `delta_expired_for` seam so this exact failure mode is now
covered without ever needing a real Graph connection.

**Judgment calls.** None beyond the fix itself -- this was a
straightforward gap in exception handling, found by a real run against
the real tenant (not hunted for), not a design tradeoff.

**Non-vacuousness.** N/A in the injected-bug sense -- this bug was
real and already observed (a genuine unhandled traceback from a live
run), not something that needed to be synthetically introduced to
prove the test would catch it. The new test does directly reproduce
the exact failure (a `DeltaTokenExpiredError` from a mid-list
channel_id) and asserts the script both reports it and keeps going to
the next channel, which is what was missing before this fix.

**Verified.** `tests/unit/test_graph_smoke_test.py`: 8 passed (was 6).
Full suite: 437 passed, 2 skipped. Ruff clean.

**Not done, on purpose.** The two remaining mock-fixture channel_ids
(`proj-alpha`, `proj-beta`) are still in the allowlist pointed at
non-Graph ids -- they will keep reporting "Graph rejected this
channel_id" on every future smoke-test run, which is expected and
harmless (this script is designed to report a rejection per channel_id
rather than treat one bad id as fatal), but worth deciding on
purpose at some point: either replace them with real channel_ids if
those projects go live on Teams, or drop them from the allowlist if
they're staying mock-only, so the tenant admin (`Alfred`, or whoever
eventually audits this app's Graph footprint) doesn't have to wonder
why real Graph calls are being made against ids that were never real
in the first place. Flagged, not decided or built here.

## 2026-09-19 -- CHN-05: a scoped, one-off live ingestion script -- and why the config allowlist wasn't touched

**Finding.** The natural next step after CHN-01's live smoke test was
to actually run production ingestion (`sync_all_allowlisted_channels()`)
against the real tenant. Tried the seemingly-obvious quick fix first --
temporarily set `allowlisted: false` on `config/channels/proj-alpha.yaml`
and `proj-beta.yaml` so a real run wouldn't crash on their mock
channel_ids -- and tested it directly before committing to it. It
broke 3 real tests immediately (`test_run_daily_full_flow.py` x2,
`test_run_walkthrough.py`): those scripts' own demo/full-flow tests
read the exact same `config/channels/*.yaml` directory and hardcode
`proj-alpha`/`proj-beta` as allowlisted by name. There is no separate
"live allowlist" vs. "demo allowlist" in this codebase -- one shared
directory serves both, so a change made for today's live run would
have silently broken unrelated, already-passing tests. Reverted
immediately; confirmed clean (437 passed) before doing anything else.

**Build.** Added `scripts/run_live_ingest_p1_agent_test.py`: a
deliberately narrow, one-off script that syncs exactly one real
channel_id (`p1-agent-test`'s, already verified live via
`graph_smoke_test.py`) through the real production path
(`p1.ingestion.sync.sync_channel()`, wrapped in CHN-04's
`ScopedTeamsReader` with an allowlist of just that one id -- built
fresh in code, not read from `config/channels/*.yaml`'s shared
allowlist at all). Writes to a dedicated `data/p1_live.db`, never the
shared `data/p1.db` the mock-fixture demo/eval scripts read and write,
so real Teams message content never mixes into the store golden-case
eval scores against. Discovered along the way that
`sync_state.channel_id` is a foreign key into a `channels` table only
`ChannelConfigStore().sync_to_db()` populates -- added that call
(registers every configured channel's config into the dedicated db,
never attempts a Graph read for any but the one scoped channel_id).

**Judgment calls.** (1) Did not touch `config/channels/*.yaml` at all
for this run -- proj-alpha/proj-beta's real-vs-drop decision (raised
last entry) stays open and fully decoupled from getting a real
ingestion run working today. (2) New dedicated db
(`data/p1_live.db`) rather than reusing `data/p1.db` -- a real
person's real message content and a mock mock fixture demo/eval store
are different enough in kind that mixing them felt like the wrong
default, not something to do silently.

**Non-vacuousness.** Real bug injection, twice. First: bypassed the
scope gate entirely in `run_live_ingest()` (`reader = raw_reader`
instead of wrapping it) and re-ran this script's own test file --
both tests still passed, which is a real problem: it meant
`test_run_live_ingest_only_ever_scopes_to_the_one_channel_id` was
vacuous, testing a second, hand-rolled `ScopedTeamsReader` built
inside the test itself rather than the one `run_live_ingest()` actually
constructs. Fixed by extracting `build_scoped_reader()` -- the exact
construction `run_live_ingest()` uses -- so the test calls that same
function directly. Re-injected the identical bug and confirmed the
rewritten test now genuinely fails (an `IndexError` on the fake
reader's page list, because it never got refused, proving the
previous version of this test would never have caught a real scope-gate
regression here). Reverted, re-ran clean: 2 passed. Full suite: 439
passed, 2 skipped (was 437 -- two new tests), ruff clean.

**Not done, on purpose.** Deliberately stops at ingestion -- classify_and_persist,
digests, nudges, and escalations against real data are all separate,
larger steps not attempted here. proj-alpha/proj-beta's real-vs-drop
decision (previous entry) is still open. `data/p1_live.db` is a new,
uncommitted (gitignored, same as `data/p1.db`) runtime artifact --
nothing about its schema or location is meant to be permanent
infrastructure yet; if live ingestion becomes a regular thing rather
than a one-off proof, this script and its db path deserve a proper
production home, not this scaffolding.

## 2026-09-19 -- CHN-01/CHN-05 confirmed live end to end; README updated to match

**The confirmation.** `scripts/run_live_ingest_p1_agent_test.py` ran
successfully against the real DigitalT3 tenant: "Ingested 1 message(s)
from 19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2" and
persisted it into `data/p1_live.db`. This is the first time any code
in this repo has both read a real message from a real Microsoft Teams
channel and stored it through the real production ingestion path
(`sync_channel`, scope-gated). Everything upstream of this point this
session -- the scope investigation, the two `Channel.ReadBasic.All`
round-trips, the ingestion refactor, the smoke-test crash fix -- was in
service of getting to this one line of real output.

**Build.** Updated `README.md` to stop describing this as pending:
- C2's Status row: `**Partial** -- code done, live credential pending`
  -> `**Done** -- live-verified 2026-09-19`, `Verify` column now
  includes `scripts/run_live_ingest_p1_agent_test.py`.
- The Architecture section's `TeamsReader` description now says
  `GraphTeamsReader` is live-verified rather than "once CHN-01's
  credential lands".
- CHN-01's Key decisions paragraph rewritten from "admin consent is
  still pending... has never read a real message" to what actually
  happened, including the `Channel.ReadBasic.All` request-then-remove
  round trip and a pointer to today's DECISION_LOG entries, plus an
  explicit note that `proj-alpha`/`proj-beta` are still mock-fixture
  ids (that decision stays open, undecided, tracked separately).
- "Connecting to a real Microsoft Team" section: added
  `run_live_ingest_p1_agent_test.py` as a third script, corrected
  `graph_smoke_test.py`'s own description (it no longer enumerates
  channels via Graph's `list_channels()` -- it reads the allowlist
  from config, per the earlier refactor).
- The walkthrough's live-permalink caveat corrected: permalinks in
  that script don't resolve because `proj-alpha`/`proj-beta` are mock
  ids, not because Graph consent is pending (consent landed; a
  walkthrough-style run against `p1-agent-test` would resolve).

**Judgment calls.** None beyond accurately describing what already
happened -- this entry is documentation catching up to reality, not a
new decision.

**Non-vacuousness.** N/A -- documentation update, no application code
changed.

**Verified.** Full suite re-run after the README edit (docs-only, but
confirmed nothing else drifted): 439 passed, 2 skipped, ruff clean.

**Not done, on purpose.** Still open, unchanged by this entry:
proj-alpha/proj-beta's real-vs-drop decision; the Copilot Studio
Dataverse config table and agent instructions; a real Power Automate
flow for the write side; a standalone always-on scheduler process;
CHN-33 (spine extraction for P2/P3). The live ingestion proven today
covers CHN-01/CHN-05 specifically -- classification, digests, nudges
and escalations against this real data are separate, larger,
not-yet-attempted steps.

## 2026-09-19 -- CHN-22: the real Power Automate flow provisioned; write side wired, not yet proven live

**What was built.** A real, saved Power Automate flow ("P1 Teams
Publisher") in the DigitalT3 Software Services Pvt Ltd environment,
built by driving `make.powerautomate.com` directly in the browser (the
user's explicit choice, same pattern as the earlier Copilot Studio
agent setup): an HTTP trigger with the exact JSON schema
`PowerAutomateTeamsPublisher._post()` already sends
(`action_type`/`target`/`content`, all required), a `Condition` on
`action_type == "channel_post"`, and one Teams "Post message in a chat
or channel" action per branch -- `Post in: Channel` (Team hardcoded to
the real DigitalT3 team id from `.env`'s `GRAPH_TEAM_ID`, Channel bound
to the trigger's `target`) on the true branch, `Post in: Chat with Flow
bot` (Recipient bound to `target`) on the false branch -- both with
Message bound to the trigger's `content`. `.env` now has
`TEAMS_PUBLISHER_MODE=power_automate` and the flow's real
`POWER_AUTOMATE_FLOW_URL` (the anonymous, SAS-signed trigger URL),
matching `.env.example`'s documented shape.

**Judgment calls.**
- **"Who can trigger the flow?" switched from the default "Any user in
  my tenant" to "Anyone."** The tenant-restricted default requires an
  Azure AD bearer token on every call; `PowerAutomateTeamsPublisher`
  does a plain, unauthenticated JSON POST (by design -- see that
  file's own docstring: it never holds a Graph token, only the flow's
  URL). "Anyone" produces the classic SAS-signed URL
  (`?...&sp=...&sv=...&sig=...`) that a bare POST can call, which is
  what the existing, already-written publisher code requires. This
  makes the flow's URL itself the credential -- consistent with how
  `.env.example` already documented `POWER_AUTOMATE_FLOW_URL` as a
  secret-shaped value, not a new posture. No alternative was viable
  without rewriting `PowerAutomateTeamsPublisher` to acquire and
  attach an AAD token, which is a materially different design than
  what CHN-22 already committed to.
- **Team id hardcoded, Channel id left dynamic.** The publisher's
  contract only ever sends one identifier (`target`) per call --
  channel_id for a channel post, member_id for a direct message --
  never a team_id. Since Power Automate's Teams connector needs both a
  Team and a Channel to resolve a channel post, the flow hardcodes the
  one Team this pilot lives in (`GRAPH_TEAM_ID`'s value, confirmed
  correct by cross-checking that `p1-agent-test` appears in that
  Team's channel list once entered) and leaves Channel bound to
  `target`, so the flow works for any channel in that Team, not only
  `p1-agent-test`, matching the reader side's existing single-tenant
  assumption.

**Build.** `scripts/power_automate_smoke_test.py` (new): posts one
obvious, timestamped, clearly-labelled test message to the real
`p1-agent-test` channel_id through the real
`PowerAutomateTeamsPublisher`, calling it directly rather than through
`SPN-09`'s `guarded_send()` -- this script is the guard here, the same
role `graph_smoke_test.py` plays on the read side. Not yet run for
real: that is the next step, deliberately left for the user to trigger
and confirm against the actual Teams channel, consistent with never
having this session assert a live result it did not itself observe
being pasted back.

**Non-vacuousness.** `tests/unit/test_power_automate_smoke_test.py`'s
channel-id assertion was proven to actually exercise the real
`CHANNEL_ID` constant, not just echo back whatever a fake happened to
receive: temporarily changed the script's `post_channel_message` call
to a wrong, hardcoded channel id, re-ran the test, confirmed it failed
with the expected diff, then reverted and re-confirmed green.

**Verified.** `uv run pytest tests/unit/test_power_automate_smoke_test.py`:
4 passed. Full suite: 442 passed, 2 skipped, 1 pre-existing failure
(`test_approval_dashboard_app.py::test_dashboard_lists_and_approves_a_pending_nudge`,
confirmed unrelated -- it fails identically with these two new files
removed entirely, and passes in isolation; a pre-existing test-order
dependency, not something this entry introduced or attempts to fix).
`ruff check` clean on both new files (one auto-fixed unused-import and
import-order issue).

**Not done, on purpose.** The flow has never actually been triggered --
no real message has landed in the real `p1-agent-test` channel yet.
That requires running `scripts/power_automate_smoke_test.py` for real
and checking Teams, which is next. Beyond that: the full "ingest ->
classify -> summarize -> post" pipeline against real `p1-agent-test`
data has not been attempted (classification and summary generation
both need a real LLM call that hasn't been exercised against this
channel's real content yet); `proj-alpha`/`proj-beta`'s real-vs-drop
decision remains open; the standalone always-on scheduler, the
Copilot Studio Dataverse config table, and CHN-33 (spine extraction
for P2/P3) are all still outstanding, unchanged by this entry.

## 2026-09-19 -- SPN-02: real AWS Bedrock credentials wired in; a real, previously-latent test bug found and fixed as a direct consequence

**What was added.** `.env` now has `LLM_PROVIDER=bedrock`,
`AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY` (the user's own IAM
credentials, provided directly, not fabricated or derived from any
sign-in flow -- an API key pair is a static credential the user
generates herself, unlike the Graph device-code token, so there was no
interactive-login step to gate this on). `AWS_REGION` and
`BEDROCK_MODEL_ID` were already present from an earlier session.
`LLM_PROVIDER` was previously unset (defaulting to `anthropic`, which
would have failed anyway with no `ANTHROPIC_API_KEY` present); the
user chose Bedrock explicitly when asked, matching the AWS values
already sitting unused in `.env`.

**A real bug this surfaced, immediately, not hunted for.** The very
next full-suite run failed:
`test_llm_gateway_bedrock_call_shape.py::test_missing_aws_config_raises_before_touching_the_network`
went from passing to raising a genuine `anthropic.APIConnectionError`
instead of the `LLMGatewayError` it asserts on. Root cause: `gateway.py`
calls `load_dotenv()` at module import time, and `LLMGateway.__init__`
resolves every Bedrock config field as `constructor_arg or
os.environ.get(...)`. The test simulated "AWS config missing" by
passing `bedrock_aws_access_key=None, bedrock_aws_secret_key=None` to
the constructor -- which worked only because `.env` had never had real
values for those two names. The moment real values landed in `.env`,
`None or os.environ.get("AWS_ACCESS_KEY_ID")` silently resolved to the
real key, the test's "missing config" scenario stopped being missing,
and `_call_bedrock` sailed past its own validation check into a real
`AnthropicBedrock()` client construction and a real (failing, but
real) network call -- from inside a unit test, which is exactly the
class of thing SPN-02's other Bedrock tests go out of their way to
prevent (see this file's own module docstring: "no AWS credentials,
network access, or real Bedrock account are ever touched under
pytest"). This test alone hadn't been living up to that.

**Fix.** Added `monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)`
and the same for `AWS_SECRET_ACCESS_KEY` at the top of that one test,
so it no longer depends on the ambient environment (real or `.env`-
sourced) lacking these two names -- it now actively removes them for
its own duration, regardless of what `.env` holds. No other test in
this file makes the same assumption (the other three all supply a
fake `_bedrock_client` directly and never reach the config-validation
branch at all).

**Judgment calls.** Fixed this in place rather than only disclosing it:
it's a one-line, clearly-scoped isolation fix to a test whose entire
purpose is guarding against exactly this kind of accidental live call,
not a design question needing a decision.

**Non-vacuousness.** Directly observed, not injected: this was a real
failure from a real change (adding real credentials to `.env`), caught
by running the full suite immediately afterward rather than assuming
the credential addition was inert. Re-ran the fixed test alone (4
passed) and the full suite again to confirm the fix holds.

**Verified.** `uv run pytest tests/unit/test_llm_gateway_bedrock_call_shape.py`:
4 passed. Full suite: 442 passed, 2 skipped, ruff clean, plus the one
pre-existing, already-documented, unrelated
`test_approval_dashboard_app.py` order-dependent flake (unchanged by
this entry).

**Not done, on purpose.** No real Bedrock call has been made yet --
these credentials are wired and config-validated, not yet exercised
against a real classification or summary prompt. That is the next
step, building the real "ingest -> classify -> summarize -> post"
pipeline script against `p1-agent-test`.

## 2026-09-19 -- CHN-23: the real ingest -> classify -> digest -> publish pipeline, wired for `p1-agent-test` and proven against a fake reader/scripted model

**What was built.** `scripts/run_live_pipeline_p1_agent_test.py`: the
first script this session to exercise CHN-08/09 classification, the
CHN-10 participation ledger, and CHN-13 digest generation against real
`p1-agent-test` data, by calling the exact same production functions
every mock-fixture test and `scripts/run_daily.py` already use
(`sync_channel`, `classify_and_persist`, `run_daily_digest_job`) --
pointed at the real `channel_id`, a real `LLMGateway` (Bedrock, per
SPN-02), and whatever `get_teams_publisher()` resolves to from
`TEAMS_PUBLISHER_MODE` (Power Automate, per CHN-22) -- instead of
fixtures and a mock. It builds on the read side
(`scripts/run_live_ingest_p1_agent_test.py`) and write side
(`scripts/power_automate_smoke_test.py`) this session already proved
live on their own; this script is the first thing to connect ingest,
classification, and publish into one real run. It never pre-seeds a
`members` row from fixture data the way `scripts/run_daily.py` does --
`MessageStore._ensure_member_exists` already covers that for any real
`author_id` ingestion encounters (see CHN-31), so nothing here needs to
duplicate it.

**Three real findings, disclosed in the script's own docstring before
being asked, not assumed away:**

1. `config/channels/p1-agent-test.yaml` sets `ignore_bots: true`, and
   the one real message in this channel as of this writing (the Power
   Automate smoke test's own post) is bot-authored -- it will be
   classified as noise and contribute nothing to a digest. This script
   will not look "useful" on a real run until a real, human-authored
   message exists in the actual Teams channel.
2. The channel's `working_days` is Mon-Fri in `Asia/Colombo`;
   `run_daily_digest_job` returns `SKIPPED_NON_WORKING_DAY` outright
   for any other day. A `--day YYYY-MM-DD` flag lets a specific past
   working day be targeted instead of only ever trying "today."
3. `run_daily_digest_job` requires human approval before its very
   first publish for any channel ever
   (`DigestStore.has_ever_published()` is `False` for
   `p1-agent-test`) -- so the very first real run of this script is
   expected to end `status="awaiting_approval"`, not an actual Teams
   post. That is designed behaviour ("no channel ever receives an
   unexpected bot post"), not a failure; approving it is a separate,
   deliberate step.

**A real bug this surfaced while writing the test, caught before it
ever ran for real, not hunted for.** The first draft of
`tests/unit/test_run_live_pipeline_p1_agent_test.py` used
`author_id="sharons@digitalt3.com"` (lowercase) for its synthetic
human-authored fixture message. The very first run classified it as
noise, not signal:
`detection.rules._rule_not_on_roster` does an exact, case-sensitive
string match against `config/channels/p1-agent-test.yaml`'s real
roster entry, which is `"SharonS@digitalt3.com"` (capital S). The
fixture's casing didn't match, so the message fell through to that
rule and was excluded before ever reaching the model -- exactly the
kind of silent misclassification this pipeline's own docstring warns
about for bot-authored content, just triggered by a test-fixture typo
instead. Fixed by changing the fixture's `author_id` to match the real
roster's exact casing, with a comment on `_human_message()` explaining
why the casing matters (rules.py's roster check is not
case-insensitive, and there is no plan to make it one -- Teams/Graph
author identifiers are case-sensitive strings, and normalizing them
implicitly here would risk silently admitting a genuinely different
account).

**A second, unrelated test bug found and fixed in the same file.**
`test_run_live_pipeline_only_ever_scopes_to_the_one_channel_id` called
`build_scoped_reader()` directly without first calling
`run_live_pipeline()` (which calls `init_db()`), so `sync_state` didn't
exist yet and the test failed with
`sqlite3.OperationalError: no such table: sync_state`. Fixed by adding
an initial `run_live_pipeline()` call (fake reader, empty page) before
the direct `build_scoped_reader()`/`sync_channel()` scope-violation
check -- mirroring the exact pattern already established in
`tests/unit/test_run_live_ingest_p1_agent_test.py`'s own
`test_run_live_ingest_only_ever_scopes_to_the_one_channel_id`.

**Judgment calls.** Both test fixes were applied in place rather than
only disclosed: the roster-casing fix corrects a wrong test fixture
against a real, unambiguous config value (not a design question), and
the missing-`init_db()` fix reproduces an already-established,
already-reviewed pattern from a sibling test file rather than
introducing a new one.

**Non-vacuousness.** Directly injected and confirmed, not assumed: with
the fix reverted (`author_id="sharons@digitalt3.com"` restored),
`test_first_run_ingests_classifies_and_awaits_approval` failed with the
exact original symptom (`Classified 1 message(s): 0 signal, 1 noise.`,
expected `"1 signal, 0 noise"`); reverted back and re-confirmed all 4
tests green. The scope-gate test's non-vacuousness is inherited from
the identical, already-proven pattern in
`test_run_live_ingest_p1_agent_test.py` (that file's own comment
documents its own bug-injection proof for the same
`build_scoped_reader()` construction path this script reuses).

**Verified.** `uv run pytest tests/unit/test_run_live_pipeline_p1_agent_test.py`:
4 passed. Full suite: 446 passed, 2 skipped, ruff clean, plus the same
one pre-existing, already-documented, unrelated
`test_approval_dashboard_app.py::test_dashboard_lists_and_approves_a_pending_nudge`
order-dependent flake (unchanged by this entry; still fails identically
in isolation from these changes).

**Not done, on purpose.** This script has not yet been run for real
against the actual Teams channel, real Bedrock, or the real Power
Automate flow -- only against a fake Graph reader and a scripted
gateway. The real first run is expected to report `awaiting_approval`
and, per finding (1) above, will not surface a useful digest until a
real, human-authored message exists in `p1-agent-test` -- that requires
a person (Sharon) actually posting there. `proj-alpha`/`proj-beta`'s
real-vs-drop decision remains open; the standalone always-on scheduler,
the Copilot Studio Dataverse config table, a real public host for
`copilot_studio_api.py`, and CHN-33 (spine extraction for P2/P3) are
all still outstanding, unchanged by this entry.

## 2026-09-19 -- CHN-24: a real crash on the first live run of the full pipeline -- `parse_instant` couldn't handle real-world fractional-second lengths

**What happened.** The very first real run of
`scripts/run_live_pipeline_p1_agent_test.py` against the actual
`p1-agent-test` channel (after refreshing the Graph token via
`scripts/graph_login.py`) crashed inside digest generation:

```
ValueError: Invalid isoformat string: '2026-09-16T10:49:31.35+00:00'
```

**Root cause.** `p1.config.calendar.parse_instant` already tolerated a
trailing `Z` (Python 3.10's `datetime.fromisoformat` doesn't accept it
directly), but had no equivalent tolerance for fractional-seconds
length: 3.10's `fromisoformat` only accepts a fractional component of
*exactly* 3 or 6 digits, not any other count. The one real message
already stored in `data/p1_live.db` --
`scripts/power_automate_smoke_test.py`'s own earlier test post --
carries `posted_at="2026-09-16T10:49:31.35Z"`, a 2-digit fraction, and
crashed immediately. This wasn't a one-off oddity to special-case
around either: Microsoft Graph's own `dateTimeOffset` format uses 7
digits (.NET's 100ns ticks, e.g. `"2019-07-12T15:00:00.0000000Z"`),
which 3.10's `fromisoformat` rejects just as hard. Every real message
this pipeline will ever ingest from Graph was going to hit this same
crash the moment a human message actually reached the digest step --
the bot-only content just meant it hadn't been triggered until this
run. This is confirmed, not hypothetical: verified directly against
this repo's own Python 3.10.12 interpreter (`datetime.fromisoformat`
rejects both `'...31.35+00:00'` and `'...31.3500000+00:00'`, accepts
only `'...31.350+00:00'`/`'...31+00:00'`).

**Fix.** `parse_instant` now normalizes any fractional-seconds length
to exactly 6 digits (microseconds) before calling `fromisoformat`:
padding a short fraction with trailing zeros, truncating a long one.
Truncating Graph's sub-microsecond tick digits loses nothing Python's
own `datetime` could have kept anyway (it only stores microsecond
precision). The trailing-`Z` handling is unchanged.

**Judgment calls.** Fixed in place rather than only disclosed -- this
is a parsing-correctness bug in a shared, already-tested utility
function, not a design question. Truncating (rather than rejecting)
sub-microsecond digits was chosen over raising on "too many digits":
`datetime` cannot represent finer-than-microsecond precision at all,
so refusing to parse a real, valid Graph timestamp over precision
Python could never have used anyway would only trade one crash for
another, more confusing one.

**Non-vacuousness.** Directly observed, not injected, for the original
crash (a real production run failed with this exact error). For the
fix itself: temporarily restored `parse_instant`'s pre-fix body,
re-ran `tests/unit/test_calendar.py`, and confirmed the two new tests
(`test_parse_instant_handles_a_short_fractional_second`,
`test_parse_instant_handles_microsoft_graphs_own_seven_digit_fraction`)
failed with the identical `ValueError` this entry describes; reverted
and re-confirmed all 9 tests in that file green.

**Verified.** `uv run pytest tests/unit/test_calendar.py`: 9 passed.
Full suite: 449 passed, 2 skipped, ruff clean, plus the same one
pre-existing, already-documented, unrelated
`test_approval_dashboard_app.py::test_dashboard_lists_and_approves_a_pending_nudge`
order-dependent flake (unchanged by this entry).

**Not done, on purpose.** The live pipeline has not yet been re-run
against the real channel since this fix -- that's the immediate next
step, and it should now get past digest generation (though it will
still report 0 signal for 2026-09-16 specifically, since that channel's
only real message that day is the bot-authored smoke-test post,
excluded by `ignore_bots: true` per CHN-23's own finding). A real,
human-authored message posted into the actual channel is still needed
for this pipeline to produce a non-empty digest.

## 2026-09-19 -- CHN-25: a second, more serious identity bug found before it could waste a real Teams post -- author_id from Graph is a GUID, roster is written as an email

**Finding.** While preparing to seed `p1-agent-test` with real, human
test content, re-read `GraphTeamsReader._parse_message()`
(`src/p1/adapters/teams_reader_graph.py`) to confirm what a real human
message would actually look like once ingested. It sets
`author_id = (item.get("from") or {}).get("user", {}).get("id")` --
Microsoft Graph's Azure AD **object ID** (a GUID) -- never an
email/UPN string. Every channel config's roster
(`config/channels/p1-agent-test.yaml`'s `["SharonS@digitalt3.com"]`
included) was written as an email, matching the mock reader's fixture
convention that every prior test and demo has used. `_rule_not_on_roster`
does an exact string match. Put together: a genuine, human-typed
message from the right person, in the right channel, would still have
been silently classified as noise -- not because of anything about the
message's content, but because the identifier format the real reader
produces has never matched the identifier format every channel config's
roster was written in. `GraphTeamsReader` had never been exercised
against a live tenant before this week (its own module docstring said
so), so nothing had ever exposed this until now.

Caught before any real content was posted to test it -- the user had
asked to seed the real `p1-agent-test` channel with many test messages
to compensate for having no real conversational history there, and
this was found while checking whether that would actually work, not
after wasting a batch of real Teams posts on a broken roster match.

**A related, already-understood dead end also confirmed while
investigating.** Messages posted through the Power Automate flow
arrive at Graph with `from.application` set (not `from.user`), which
`_parse_message` maps to `is_bot=True`; with `ignore_bots: true`, any
volume of Power-Automate-posted content will always be classified
noise. This isn't new -- CHN-23's own docstring already predicted the
one existing bot-authored message would be excluded -- but it means
posting *more* test content through the write path this session
already built would not have helped either. Real signal can only ever
come from a message a human actually typed directly into Teams.

**What was built.** `scripts/graph_whoami.py`: a small, read-only
diagnostic that calls Graph's `/me` with the existing
`GRAPH_ACCESS_TOKEN` and prints the account's real AAD object id
alongside its `userPrincipalName`/`displayName`/`mail` -- so the actual
GUID a real message will carry can be read directly, rather than
guessed at, before deciding how to fix the roster mismatch.
`tests/unit/test_graph_whoami.py` (4 tests, same fake-`http_get`-seam
discipline as `test_graph_smoke_test.py`'s `reader_factory` seam) --
never opens a real Graph connection.

**Judgment calls.** Did not attempt to fix the roster-format mismatch
itself in this entry -- how to resolve it is genuinely ambiguous and
affects every channel config going forward, not just this test
channel:
- storing the real AAD object GUID directly in each channel's roster
  (works today, no new Graph permission needed, but roster entries
  stop being human-readable);
- resolving GUID -> UPN/email at classification time via an extra
  Graph call (`GET /users/{id}`, needs a scope like `User.ReadBasic.All`)
  -- keeps roster human-readable, but CHN-01's DECISION_LOG entries
  already document that this tenant requires admin consent for any new
  permission grant beyond the one already approved
  (`ChannelMessage.Read.All`), and that admin consent has been a real,
  ongoing blocker for other permissions this session never got past;
  this option may hit the identical wall.
This needs the user's own decision (which format the roster should
hold, and whether pursuing the second admin-consent grant is worth
attempting again), not a unilateral pick -- flagged to her directly
rather than silently choosing one.

**Non-vacuousness.** Injected the real bug this test suite guards
against (renamed the `id` field being read to a nonexistent key) and
confirmed `test_run_whoami_prints_the_real_identity_fields` failed with
the expected missing value; reverted and re-confirmed all 4 tests
green.

**Verified.** `uv run pytest tests/unit/test_graph_whoami.py`: 4
passed. Full suite: 453 passed, 2 skipped, ruff clean, plus the same
one pre-existing, already-documented, unrelated
`test_approval_dashboard_app.py` order-dependent flake (unchanged by
this entry).

**Not done, on purpose.** The roster-format mismatch itself is not yet
fixed -- `scripts/graph_whoami.py` is a diagnostic, not a fix. No real
message has been posted into `p1-agent-test` by a human yet. The next
step is running `scripts/graph_whoami.py` for real to get the actual
GUID, deciding with the user which of the two options above to take,
then updating `config/channels/p1-agent-test.yaml`'s roster (and,
eventually, the roster-format story for every other channel config)
accordingly -- only after that should real human test messages be
posted, so they're not wasted against a roster that still can't match
them.

## 2026-09-19 -- CHN-25 (resolved): roster switched from email to the real Azure AD object id, per the user's own choice

**Decision.** CHN-25 flagged two ways to fix the roster/author_id
format mismatch and left the choice to the user rather than picking
unilaterally: store the real AAD object GUID directly in each
channel's roster (works today, no new permission), or resolve
GUID -> email automatically via an extra Graph call (keeps roster
human-readable, but likely needs a new tenant admin-consent grant this
project has already been blocked on twice). Asked directly; the user
chose the GUID approach, with an annotation so the file stays
human-readable despite the value itself being opaque.

**What changed.** Ran `scripts/graph_whoami.py` for real against the
user's own signed-in account: her Azure AD object id is
`a52e61e5-16c6-4f6c-af67-f41f85e7a00a` (userPrincipalName/mail both
confirm it's `SharonS@digitalt3.com`). Updated
`config/channels/p1-agent-test.yaml`'s `roster` entry from the email
string to that GUID, with an inline YAML comment naming her and
pointing at this entry so a future editor doesn't have to go looking
up whose id it is:

```yaml
roster:
  - "a52e61e5-16c6-4f6c-af67-f41f85e7a00a"  # Sharon Silva (SharonS@digitalt3.com) -- Graph reports author_id as the AAD object id, not the email; see DECISION_LOG.md CHN-25
```

`channel_owner_id` (used only as the escalation job's direct-message
`target`, a separate write-path concern from roster matching) was
deliberately left as the email -- untouched, since nothing has shown
that field is actually broken the same way, and changing it without
evidence would be guessing rather than fixing a confirmed bug.

**Test fix required as a direct consequence.**
`tests/unit/test_run_live_pipeline_p1_agent_test.py`'s `_human_message()`
fixture used the email as `author_id` to match the (now-changed) real
roster -- this is the third distinct value that fixture has needed
since it was written this session (first a case-mismatched email,
then the correctly-cased email, now the real GUID), each one exposing
a different real gap between the mock-fixture convention and the real
Graph-sourced identity format. Updated to the same GUID, with a
comment explaining why.

**A real device-bridge flake hit while applying this fix, worth
recording.** The first `device_commit_files` call for the updated test
file reported success but silently left the file unchanged on disk
(confirmed by `grep`ing the file immediately after and finding the old
value still there) -- a second `device_commit_files` call with
`force=true` for the identical content did apply correctly. No data
was lost and the discrepancy was caught immediately by verifying the
file's actual content after every commit rather than trusting the
tool's reported success, which is why this session checks with `grep`
after every `device_commit_files` call for a file a test's correctness
depends on.

**Non-vacuousness.** Reverted `_human_message()`'s `author_id` back to
the email, re-ran the file, and confirmed the exact same failure CHN-25
predicted (`Classified 1 message(s): 0 signal, 1 noise.`, expected "1
signal, 0 noise"); reverted back and re-confirmed all 4 tests green.

**Verified.** `uv run pytest tests/unit/test_run_live_pipeline_p1_agent_test.py`:
4 passed. Full suite: 453 passed, 2 skipped, ruff clean, plus the same
one pre-existing, already-documented, unrelated
`test_approval_dashboard_app.py` order-dependent flake (unchanged by
this entry).

**Not done, on purpose.** No real human message has been posted into
`p1-agent-test` yet -- that's now unblocked and is the actual next
step. `channel_owner_id`'s own identity-format correctness (the
escalation/DM path) remains unverified against a real Graph-sourced
value and is a separate, still-open question if that path is ever
exercised for real. This same email-vs-GUID roster format question
will recur for every future real channel config -- CHN-25/this entry's
resolution is the pattern to follow (GUID + comment), not a one-off
special case for `p1-agent-test` alone.

## 2026-09-19 -- CHN-26: the first real Bedrock call failed, and the gateway's own fallback logging hid why

**What happened.** The first real run of
`scripts/run_live_pipeline_p1_agent_test.py` to reach classification
against a genuine ingested message (a real human message, correctly
matched to the fixed roster from CHN-25) failed to get a usable
response from either configured provider:

```
Primary provider exhausted; degrading to local Ollama fallback
...
httpx.ConnectError: [Errno 61] Connection refused
p1.llm.gateway.LLMGatewayError: Ollama request failed: [Errno 61] Connection refused
```

Bedrock (the primary, configured via `LLM_PROVIDER=bedrock`) failed
first; the gateway's designed degrade-to-local-Ollama fallback then
also failed, because there is no local Ollama server running on the
user's machine. That second failure is expected and not a bug -- the
fallback is a last resort, not a guarantee. The real problem is what
happened to the *first* failure.

**A real bug found while trying to diagnose it.**
`LLMGateway.generate()`'s degrade path was `except LLMGatewayError:`
-- no bound exception name -- so the actual reason Bedrock rejected
the call (an `APIStatusError`, wrapped by `_call_messages_api` into an
`LLMGatewayError` carrying the real HTTP status/message) was silently
discarded. Only `logger.warning("Primary provider exhausted; degrading
to local Ollama fallback")` was ever logged -- a fixed string with no
information about *why*. The user's terminal only ever showed the
unrelated Ollama connection-refused error, with no way to tell whether
Bedrock failed on bad credentials, a disabled model, a wrong region, a
malformed inference-profile ARN, or something else entirely. This
would have made every future real provider failure equally
undiagnosable, not just this one.

**Fix.** `except LLMGatewayError:` -> `except LLMGatewayError as exc:`,
and the warning now includes `self.provider` and `exc` itself:
`"Primary provider (%s) exhausted: %s; degrading to local Ollama
fallback"`. The original exception's message (already a clear string
built by `_call_bedrock`/`_call_anthropic`/`_call_messages_api`) now
always reaches the log, whichever provider is primary.

**Judgment calls.** Fixed in place rather than only disclosed -- this
is a pure logging-completeness bug (information already computed and
then thrown away), not a design question.

**Non-vacuousness.** Reverted the fix, re-ran the new test
(`test_degrading_logs_the_primary_providers_real_failure_reason`), and
confirmed it failed showing exactly the same generic, uninformative
message this entry describes (`'Primary provider exhausted; degrading
to local Ollama fallback'`, missing the injected `"bedrock exhausted
(simulated)"` reason); reverted back and re-confirmed all 5 tests in
`test_llm_gateway_degrade.py` green.

**Verified.** `uv run pytest tests/unit/test_llm_gateway_degrade.py`:
5 passed. Full suite: 454 passed, 2 skipped, ruff clean, plus the same
one pre-existing, already-documented, unrelated
`test_approval_dashboard_app.py` order-dependent flake (unchanged by
this entry).

**Not done, on purpose.** The actual reason the real Bedrock call
failed is still unknown -- this entry only fixes the gateway's ability
to report it. The next live run will surface the real message (AWS
auth, model-access, region, or ARN issue are all still live
possibilities) and that specific cause still needs diagnosing and
fixing once seen. Separately, `p1-agent-test`'s config currently has a
temporary, uncommitted `working_days` override (adding "Sat") to allow
testing on a non-working day -- deliberately left uncommitted, to be
reverted once the model-call issue is resolved and a real digest has
actually been produced end to end.

## 2026-09-19 -- CHN-26 (follow-up): real Bedrock call blocked on an IAM permission the demo credentials cannot self-grant

**Finding.** With CHN-26's logging fix in place, the real Bedrock call
now reports its actual failure clearly:

```
Bedrock API error: Error code: 403 - {'Message': 'User:
arn:aws:iam::619042036275:user/p1-agent-bedrock-demo is not authorized
to perform: bedrock:InvokeModel on resource:
arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0
because no identity-based policy allows the bedrock:InvokeModel action'}
```

The AWS credentials in `.env` (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`,
provided by the user's lead, per SPN-02's original entry) belong to IAM
user `p1-agent-bedrock-demo`, which has no policy granting
`bedrock:InvokeModel` at all. This is an AWS account permissions gap,
not a bug in this codebase -- `LLMGateway._call_bedrock`'s config
validation, client construction, and request shape are all already
confirmed correct (SPN-02, CHN-26); the request reaches AWS and is
rejected by IAM before Bedrock itself ever runs the model.

**A resource-ARN wrinkle worth recording.** The 403 named
`arn:aws:bedrock:us-east-1::foundation-model/...`, not the
`us-east-2` inference-profile ARN configured in `.env`'s
`BEDROCK_MODEL_ID`. This is expected, not a second bug: `us.` prefixed
Bedrock inference profiles are cross-region and route to whichever
underlying regional foundation-model endpoint serves the request, so
IAM needs permission on both the inference-profile resource and the
foundation-model resource(s) it can land on -- not just the profile
ARN itself. Passed along to the user as the two-resource IAM policy
recommendation below.

**Confirmed the demo credential cannot self-remediate.** At the user's
own request, a one-off diagnostic (`try_self_grant_bedrock.py`, run
directly by her, deleted after use, never committed) attempted
`iam:PutUserPolicy` against the same `p1-agent-bedrock-demo` user using
its own credentials -- cleanly rejected with a second, unrelated
AccessDenied (`iam:PutUserPolicy` is itself not granted). This is the
expected and correct behaviour for a properly scoped-down demo
credential (a key that could grant itself more permissions would be a
real security gap on the provisioning side), not something to work
around.

**Judgment calls.** Did not attempt any further workaround (e.g.
suggesting a different model ID, silently switching providers, or
retrying with elevated assumptions) -- this is squarely the AWS
account owner's action to take, not a code or architecture decision.
Gave the user exact, copy-pasteable guidance (an IAM policy JSON
covering both required resource ARNs, plus a reminder to check
Bedrock's separate per-region "Model access" grant) to relay to her
lead, and suggested a plain Anthropic API key as a lower-friction
alternative if IAM changes are slow to get approved on his end.

**Verified.** No code change in this entry -- confirmed via the user's
own real terminal output that the gateway's error reporting (CHN-26)
now surfaces enough detail to diagnose a real infrastructure problem
precisely, which was the entire point of that fix.

**Not done, on purpose, and blocked on an external party.** The full
pipeline still cannot produce a real digest until either: the user's
lead attaches the `bedrock:InvokeModel`/`InvokeModelWithResponseStream`
policy to `p1-agent-bedrock-demo` (covering both resource ARNs above)
and confirms Bedrock model access is granted for Claude Sonnet 4 in the
relevant region(s); or the user obtains a plain `ANTHROPIC_API_KEY` and
switches `LLM_PROVIDER=anthropic` instead. Everything else in the
pipeline -- real Graph ingestion, roster matching against the real AAD
object id (CHN-25), the working-day gate, and error surfacing -- is
confirmed working correctly up to this exact point. `p1-agent-test`'s
`working_days` still carries the temporary, uncommitted Saturday
override (CHN-25/CHN-26); still deliberately left in place and
unreverted until a real digest actually completes end to end.

## 2026-09-19 -- CHN-27: found and fixed before it could waste an Ollama install -- structured-output requests silently dropped their schema on the Ollama path

**Context.** With the real Bedrock call blocked on an external AWS IAM
permission gap (CHN-26) that the user cannot resolve herself, and a
second identical "still not fixed" round-trip with her lead, she chose
to unblock herself with a fully local alternative: install Ollama and
run a model on her own machine, sidestepping AWS entirely. Investigated
whether `LLM_PROVIDER=ollama` would actually work for this codebase's
real capabilities before recommending she spend the time downloading a
multi-GB local model.

**Finding.** It would not have worked. Every real capability in this
codebase (classification, daily-summary generation) calls
`generate_structured()`, which always sends `tools`/`tool_choice` and
expects the response text to already be schema-valid JSON. Anthropic
and Bedrock satisfy this via native tool-calling (the model returns a
structured `tool_use` block, dumped straight to JSON). `_call_ollama`,
however, didn't even accept `tools`/`tool_choice` as parameters --
`_call_provider`'s dispatch called it as `self._call_ollama(prompt,
system, max_tokens, temperature)`, silently dropping both. Ollama's
`/api/generate` has no native tool-calling API, and nothing in this
codebase's prompts (see `prompts/chn09_classify_message/v1.md`) states
the expected JSON shape in plain text -- that information only ever
lived in the `tools` parameter. So a real Ollama call for
classification would have received a prompt with zero indication of
what shape to answer in, `generate_structured()`'s `json.loads()` would
have failed on every one of its 3 retry attempts, and the whole call
would have ended in `StructuredOutputError` -- discovered here, before
the user spent time on an install and download that would have failed
at the very last step, not after.

**Fix.** `_call_ollama` now accepts `tools`/`tool_choice` and, when
present, appends the tool's JSON schema to the prompt as an explicit
instruction (the closest equivalent Ollama's plain-completion API
supports to native tool-calling). Also added
`_strip_markdown_json_fence()`, applied to every Ollama response:
local/open models often wrap JSON in a ` ```json ... ``` ` fence
despite being told not to, which would otherwise burn one of
`generate_structured()`'s three retry attempts on a purely cosmetic
wrapper. Added a `_make_ollama_client()` seam (mirroring this repo's
existing `reader_factory`/`publisher_factory` testability pattern) so
tests can inject an `httpx.MockTransport` instead of the previous
inline `httpx.Client(...)` construction, which had no way to be
intercepted at all.

**Judgment calls.** Embedding the schema as a plain-text instruction
(rather than, say, requiring a tool-calling-capable local model or
refusing structured requests on the ollama provider) was chosen because
it's the same shape of fix Ollama's own ecosystem generally recommends
for models without native function-calling, and it degrades gracefully
-- a capable instruction-following local model (e.g. llama3:8b or
better) should follow it reliably; a weaker one will still fail
`generate_structured()`'s validation cleanly (an explicit
`StructuredOutputError`) rather than silently miscounting like the
prior, untested state would have.

**Non-vacuousness.** Reverted the fix (old `_call_ollama` signature and
body, no seam) and re-ran the four new tests in
`test_llm_gateway_ollama_structured.py`: all four failed, three with a
real `ConnectionRefused` from the pre-fix code trying to open an actual
TCP connection to `localhost:11434` -- proving these tests weren't
already accidentally passing against unrelated mocking. Reverted back
and re-confirmed all four green.

**Verified.** `uv run pytest tests/unit/test_llm_gateway_ollama_structured.py`:
4 passed. Full suite: 458 passed, 2 skipped, ruff clean (one
auto-fixable import-order nit in the new test file, fixed), plus the
same one pre-existing, already-documented, unrelated
`test_approval_dashboard_app.py` order-dependent flake (unchanged by
this entry).

**A repo-hygiene note, unrelated to the fix itself.** This session's
device-bridge shell and the user's own terminal share the same
`.venv` (the connected folder is the same physical files on both
sides), so each side's `uv run` had been silently rebuilding the
other's virtual environment out from under it every time either one
ran a command -- explaining the repeated "Removed virtual
environment... Creating virtual environment..." churn seen in both
this session's tool output and the user's own terminal output all
session. Worked around from this side by pointing `uv` at a separate,
throwaway environment (`UV_PROJECT_ENVIRONMENT=/tmp/...`) for the rest
of this session, so verification here no longer disturbs whatever
state the user's own terminal has. Not a code bug, and not something
this entry attempts to fix in the repo itself.

**Not done, on purpose.** Ollama has still never been exercised against
a real, running local server -- this entry fixes a structural gap
found by inspection and proven with a fully mocked test suite, not by
a real end-to-end local run. The user still needs to actually install
Ollama, pull a model, and set `LLM_PROVIDER=ollama` (plus optionally
`OLLAMA_MODEL` if not using the default `llama3:8b`) before this can be
proven live. The AWS Bedrock permission gap (CHN-26) remains open and
unresolved on her lead's end; `p1-agent-test`'s `working_days` still
carries its temporary, uncommitted Saturday override, unreverted until
a real digest completes end to end via whichever provider ends up
working.

## 2026-09-19 -- CHN-32: persisting the participation ledger for real-world visibility surfaced a real, previously-latent FK bug in its own write path

**Context.** `build_and_persist_ledger()`/`ParticipationStore` have
existed since CHN-10 but were never actually called by any production
job -- `daily_summary.py`, `nudge_job.py`, and `escalation_job.py` all
deliberately read the ledger fresh via `build_ledger()` instead, "so a
digest never reports a stale ledger" (daily_summary.py's own
docstring). That's a correct, deliberate design choice for those
callers, but it also meant the `participation` table itself had never
been exercised end to end against real data -- it stayed empty even
after real messages, a real digest, and a real pending proposal already
existed for `p1-agent-test`. Wanted a real, human-visible row in that
table (via sqlite_web / the Supabase mirror set up this session) rather
than only ever seeing participation state as prose inside a digest, so
added one call to `build_and_persist_ledger()` at the end of
`scripts/run_live_pipeline_p1_agent_test.py`, clearly commented as
visibility-only and never a dependency of the digest or any downstream
job.

**Finding.** That one addition immediately failed two existing tests
with `sqlite3.IntegrityError: FOREIGN KEY constraint failed` inside
`ParticipationStore.record()`. Root cause: `participation.member_id` is
a foreign key into `members(id)`, and the only thing that ever inserts
a `members` row is `MessageStore._ensure_member_exists()` -- which
fires per message, for whoever authored it. A roster member who has
*never* posted a single message -- the exact, ordinary case this table
exists to record as `no_message` -- has no row in `members` at all, so
persisting their non-responder state crashed outright. This was a real,
previously-latent bug in `ParticipationStore`, not something the new
call introduced: it had simply never been exercised against a roster
member with zero messages before, because nothing in production ever
called it.

**Fix.** `ParticipationStore.record()` now does
`INSERT OR IGNORE INTO members (id, display_name) VALUES (?, ?)` for
each record's `member_id` immediately before the participation upsert
-- the identical, already-proven pattern `MessageStore._ensure_member_exists`
uses (the id standing in as its own placeholder display name until a
richer sync fills one in), just applied at the one other write path
that shares the same foreign key.

**Judgment calls.** Fixed centrally in `ParticipationStore` rather than
in the calling script, so any future caller of `build_and_persist_ledger()`
gets the same protection automatically, matching the precedent
`MessageStore._ensure_member_exists`'s own docstring sets ("fixing it
here, centrally, in the one place... means no caller needs to pre-seed
anything, ever again"). Kept `build_ledger()` itself, and every
production job's use of it, completely untouched -- this is additive,
opt-in persistence for visibility, not a change to detection, nudging,
or escalation behaviour.

**Non-vacuousness.** Reverted the fix (removed the `INSERT OR IGNORE`
call) and re-ran `tests/unit/test_run_live_pipeline_p1_agent_test.py`:
the same two tests failed with the identical `IntegrityError` this
entry describes. Restored the fix and re-confirmed all 4 tests in that
file, plus `test_participation_edge_cases.py` and
`test_participation_against_fixtures.py`, green (10 passed).

**Verified.** Full suite: 458 passed, 2 skipped, ruff clean, plus the
same one pre-existing, already-documented, unrelated
`test_approval_dashboard_app.py` order-dependent flake (unchanged by
this entry).

**Not done, on purpose.** `build_ledger()` and every real production
caller remain exactly as they were -- this entry only makes the
already-computed ledger additionally visible in the database for a
human looking at it directly, and fixes the one bug that surfaced the
moment that visibility was actually attempted.

## 2026-09-19 -- CHN-17/SPN-08: a pending publish proposal never refreshed its payload after creation, even though its own digest kept regenerating

**Context.** Testing the real write path against `p1-agent-test` for
the first time (CHN-22's Power Automate publisher, wired to a real
flow URL, via the CHN-25 Streamlit approval dashboard) surfaced that
the channel's first-ever `daily_digest_publish` proposal, created
06:37:33 UTC on 2026-09-19 before that day had any real Teams activity,
still showed "no updates were posted today" hours later -- after two
real messages had actually been posted and correctly classified. Every
rerun of `scripts/run_live_pipeline_p1_agent_test.py` in between
regenerated the `digests` table's own row with the right, up-to-date
content (confirmed directly against the database), so the regeneration
itself was working. The proposal shown to the human approver, and the
one `guarded_send()` would actually post from, was a different story.

**Finding.** `run_daily_digest_job()` (`src/p1/publishing/daily_job.py`)
only ever builds `publish_payload` (the dict containing `content`)
inside the `if proposal is None:` branch -- the one-time creation path.
Once a proposal already exists for that channel/day (found via its
idempotency key), every subsequent call skips straight past that block
and reuses the existing proposal object untouched, payload included.
The module's own docstring claims "content can be regenerated any
number of times right up until it is approved" -- true of the
`digests` table row, never true of the proposal's own payload, which is
what a human actually reviews and what `send_fn()` actually posts. A
proposal created early in the day (or during quiet mock/demo testing)
and left pending for any length of time while real messages arrive
would be approved and sent with stale, incorrect content -- not a
display bug, a real correctness bug in the one thing this whole HITL
gate exists to protect.

**Fix.** Added `ProposalStore.refresh_payload(proposal_id, *, payload,
source_refs=None)` (`src/p1/approval/proposals.py`): updates a
proposal's `payload` (and `source_refs`, kept in sync with it) in
place, but only when the proposal's current status is still `PENDING`
-- raising `IllegalTransitionError` otherwise, the same exception
family `approve()`/`reject()`/`apply()` already raise for an illegal
move. `original_model_output` is never touched, preserving SPN-08's own
guarantee that "what the model originally said" stays readable no
matter how many times payload is refreshed before a decision is made.
`run_daily_digest_job()` now computes `source_refs`/`publish_payload`
unconditionally on every call (not just inside the creation branch),
and added an `elif proposal.status == PENDING:` branch that calls
`refresh_payload()` with the freshly regenerated content whenever an
existing proposal is still awaiting a decision. `send_fn()` already
re-fetched the proposal fresh from the store immediately before
posting, so no change was needed there -- it now simply reads the
refreshed row.

**Judgment calls.** Restricted the refresh to `PENDING` only, on
purpose: an `approved`, `rejected`, or `applied` proposal is a real
record of a decision someone actually made, and must never be
silently rewritten out from under that decision by a later rerun --
matching SPN-08's own load-bearing guarantee (see `proposals.py`'s
module docstring) more than it extends it. Refreshed `source_refs`
alongside `payload` rather than leaving it stale, since both are
computed from the same `digest_result` in the same block and a
grounding audit trail that no longer matches the content it is meant
to back would just be a smaller, quieter version of the same bug.

**Non-vacuousness.** Temporarily disabled the new `elif` branch
(`elif False:`) and re-ran
`test_a_rerun_before_approval_refreshes_the_pending_proposals_payload`:
it failed exactly as the real bug behaved -- the proposal's payload
stayed at the first draft ("draft one") instead of picking up the
second ("draft two"). Restored the real branch and reconfirmed all 29
tests in `test_daily_job.py` + `test_proposals.py` green, including
`test_after_approval_a_rerun_never_touches_the_proposals_payload_again`
(the safety half: an already-approved proposal's payload must never be
touched by a later rerun, even one whose digest regeneration would
produce different content).

**Verified.** Full suite: 461 passed, 2 skipped (same pre-existing
skips as before), ruff clean.

**Not done, on purpose.** `DigestStore`/the `digests` table's own
regeneration behaviour is untouched -- this entry only makes the
*proposal's* payload track what that table already does correctly.
Nudge and escalation proposals (`nudge_job.py`, `escalation_job.py`)
build their proposals differently (no idempotency-key lookup against
an existing pending proposal before creating one) and were not audited
for the same class of bug in this pass -- flagged for a follow-up look,
not assumed safe by association.

## 2026-09-19 -- CHN-25: the approval dashboard never loaded `.env`, so every real approval silently posted through the mock publisher instead of Teams

**Context.** Two digest proposals were approved for real through
`app/approval_dashboard.py` against the real `p1-agent-test` channel,
and nothing appeared in the actual Teams channel. `.env` was confirmed
correct (`TEAMS_PUBLISHER_MODE=power_automate`, a `POWER_AUTOMATE_FLOW_URL`
whose signature matches the live "P1 Teams Publisher" flow's real
trigger URL byte-for-byte, a `GRAPH_TEAM_ID` matching the flow's own
Post-message action), and the flow itself was confirmed correctly
built by direct inspection in the Power Automate maker portal. Its
28-day run history contained no run at all for either approval-time
send.

**Finding.** `app/approval_dashboard.py` was the one script in the
entire project that never called `load_dotenv()` -- every other entry
point (`scripts/*.py`, `src/p1/llm/gateway.py`,
`src/p1/api/copilot_studio_api.py`) does, immediately after its own
`sys.path.insert(...)` (confirmed via
`grep -rn "load_dotenv" --include=*.py .`, excluding `.venv`). Streamlit
runs the dashboard as a long-lived process, so without that call it
only ever saw whatever was already in the OS environment at launch --
never `.env`'s contents. `src/p1/adapters/factory.py`'s
`get_teams_publisher()` reads `TEAMS_PUBLISHER_MODE` fresh on every
call with no caching, and defaults to `"mock"` (`LogPublisher`,
writing to `data/outbound_log.jsonl`) whenever that variable is unset.
Confirmed root cause, not just correlation: both real approval-time
send timestamps in `data/outbound_log.jsonl`
(`2026-09-19T15:24:20.458432+00:00`,
`2026-09-19T15:27:28.354993+00:00`) match `write_log`'s two `"sent"`
rows to the millisecond -- proving the send genuinely happened, just
through the mock adapter instead of `PowerAutomateTeamsPublisher`.

**Fix.** Added `from dotenv import load_dotenv` + a `load_dotenv()`
call near the top of `app/approval_dashboard.py`, mirroring the same
convention every other entry point already follows.

**Judgment calls.** This fix alone would have created a new, more
dangerous problem: `tests/unit/test_approval_dashboard_app.py` drives
the real `app/approval_dashboard.py` script headlessly via
`streamlit.testing.v1.AppTest.from_file(...)`, and
`test_dashboard_lists_and_approves_a_pending_nudge` clicks the real
Approve button, which falls through to `approval_service.approve_and_send()`
-> `get_teams_publisher()` with no publisher override. Neither test in
that file previously set `TEAMS_PUBLISHER_MODE`. Once
`app/approval_dashboard.py` calls `load_dotenv()`, running that test
under `pytest` on the real project checkout would, without this
correction, have read the developer's own `.env` (`load_dotenv()`
walks up from the calling file's own directory looking for `.env`,
regardless of pytest's working directory, and would find the repo
root's `.env` from `app/`) and set `TEAMS_PUBLISHER_MODE=power_automate`
for the whole test process -- meaning an ordinary `pytest` run could
have fired a real POST at the live Power Automate flow. Fixed by
adding `monkeypatch.setenv("TEAMS_PUBLISHER_MODE", "mock")` to both
tests in that file, before `AppTest.from_file(...).run()` is ever
called. This is safe specifically because `python-dotenv`'s
`load_dotenv()` defaults to `override=False` (confirmed via
`inspect.signature`) -- it never overwrites a variable
`monkeypatch.setenv` already set, so pinning the mode first guarantees
the dashboard's own `load_dotenv()` call is a no-op for this one
variable during the test.

**Non-vacuousness.** Root cause confirmed by the millisecond-level
timestamp match described above (an independent, pre-existing piece
of evidence, not something manufactured for this fix) rather than by
disabling and re-enabling the fix itself, since the dashboard is a
long-lived interactive process outside the automated test suite and
not something this pass could safely bounce live against the real
Power Automate flow again just to reproduce the bug.

**Verified.** `python3 -m py_compile` clean on both changed files.
Full test suite + ruff still pending a run by the project owner
(cloud-side `device_bash` cannot execute against the real project
venv -- see earlier entries), which is also the only way to prove
`test_dashboard_lists_and_approves_a_pending_nudge` still passes and
does not attempt any real network call.

**Not done, on purpose.** The Streamlit process already running on the
project owner's machine will not pick up this fix until it is
restarted. `st.text(content)` in the message-preview expander still
renders citation markdown as raw text instead of clickable links
(`st.markdown`) -- flagged, not yet fixed. `CURRENT_USER_ID`'s
placeholder default of `"priya"`, the flow's hardcoded direct-message
template body, and the stray `.env.bak` left over from the earlier
Ollama switch are all still open from prior entries.

## 2026-09-19 -- CHN-17/SPN-08: a human-approved publish never marked its digest published, so "auto-approve after the first publish" never actually engaged

**Context.** Found while proving the `load_dotenv()` fix live: after
`p1-agent-test` already had two applied (approved and sent) daily
digests -- 2026-09-17 and 2026-09-19 -- running the live pipeline for a
third day (2026-09-21) still came back `awaiting_approval` instead of
publishing unattended, contradicting this module's own documented
design ("first-publish approval means no channel ever receives an
unexpected bot post" -- meant to apply once per channel, not every day
after; see the CHN-17 entries above).

**Finding.** `run_daily_digest_job()` (`daily_job.py`) only calls
`digest_store.mark_published()` from its own success path -- the tail
end of the exact same function call that both creates a proposal and
(on every day after the channel's first) auto-approves and sends it in
one go. A proposal a *person* approves -- through the Streamlit
dashboard or the Copilot Studio connector, the only two real surfaces
that ever call `approval_service.approve_and_send()` -- never runs back
through `run_daily_digest_job()` at all. Confirmed by reading
`approve_and_send()`'s full body: it calls `ProposalStore.approve()`,
writes an audit row, and sends via `guarded_send()` -- no reference to
`DigestStore` anywhere. So `has_ever_published(channel_id)` stayed
False forever for any channel whose publishes are only ever approved by
a human, which in practice is every real channel this project has ever
run against -- the "auto-approve every day after the first" behavior
had never actually been reachable in real use, only in the
`run_daily_digest_job()`-reruns-itself-same-day case golden case
CHN-18/GC6 exercises with a scripted approval, not a real dashboard
click.

**Fix.** `approve_and_send()` (`src/p1/approval/service.py`) now takes
an optional `digest_store: DigestStore | None = None` parameter
(defaulting to `DigestStore(db_path)`, matching `proposal_store`'s and
`config_store`'s own pattern), and after a `daily_digest_publish`
proposal sends successfully, calls
`digest_store.mark_published(idempotency_key=f"{channel_id}:{date}:daily",
published_at=<now, UTC>)` -- reconstructing the digest's own
idempotency key (`...:daily`, CHN-13's key) from the proposal's payload,
deliberately distinct from the proposal's own `...:daily_publish` key.
Nudge and escalation approvals are untouched -- gated on
`proposal.type == "daily_digest_publish"` specifically, since
`has_ever_published()` is a concept CHN-17's daily-digest rule alone is
built on.

**Judgment calls.** `DigestStore.mark_published()` is a plain
`UPDATE ... WHERE idempotency_key = ?` with no existence check, so this
call is a safe no-op if no matching `digests` row exists yet -- not a
concern in real use, since `generate_and_persist_daily_summary()`
(CHN-13) always writes that row before `run_daily_digest_job()` ever
creates the proposal this function is approving. Placed the call after
`guarded_send()` succeeds, not before, so a `send_failed`/`refused`
outcome never marks a digest published that was never actually sent.

**Non-vacuousness.** Temporarily disabled the new block
(`if False and proposal.type == ...`) and re-ran
`test_approve_and_send_a_channel_post_marks_the_digest_published`: it
failed exactly as the real bug behaved --
`has_ever_published(CHANNEL_ID)` stayed `False` after a successful
`"sent"` approval. Restored the real code and reconfirmed all 7 tests
in `test_approval_service.py` green.

**Verified.** Full suite: 462 passed, 2 skipped (same pre-existing
skips), ruff clean.

**Not done, on purpose.** This only fixes the gap for
`daily_digest_publish` proposals specifically -- weekly digests
(`weekly_summary.py`/`run_weekly_digest_job`, if one exists analogous to
the daily job) were not audited for the same class of bug in this pass.
The real, live proof that `p1-agent-test`'s pending 2026-09-21 proposal
now both sends through the real Power Automate flow AND correctly
marks the channel as having published (so its *next* due day skips
approval) is still pending the project owner clicking Approve in the
now-restarted dashboard and a follow-up live run to confirm the
auto-approve behavior actually engages this time.

## 2026-09-19 -- CHN-25: the dashboard's P1_DB_PATH pointer to the live database was never actually persisted

**Context.** Immediately after fixing `load_dotenv()` and
`mark_published()`, restarted `app/approval_dashboard.py` and a real,
freshly-created pending proposal for `p1-agent-test` (2026-09-21) did
not appear -- the dashboard reported "Nothing awaiting approval." This
was despite two earlier real approvals (2026-09-17, 2026-09-19) having
worked correctly through this same dashboard, in an earlier terminal
session, before this segment's restart.

**Finding.** `app/approval_dashboard.py` resolves its database with
`DB_PATH = os.environ.get("P1_DB_PATH", DEFAULT_DB_PATH)`, and
`DEFAULT_DB_PATH` (`src/p1/storage/db.py`) is `data/p1.db` -- the
shared mock/fixture store every eval/demo/golden-case test reads and
writes, deliberately kept separate from `data/p1_live.db` (the
dedicated live database `run_live_ingest_p1_agent_test.py` and
`run_live_pipeline_p1_agent_test.py` both use, per the README's own
CHN-05 section). Confirmed via
`grep -rn "P1_DB_PATH" --include=*.py --include=*.md .` that this
variable is set in exactly zero persistent places in the repo -- not
`.env`, not any script, not README.md -- only inside
`tests/unit/test_approval_dashboard_app.py`'s own
`monkeypatch.setenv(...)` calls. The only way the two earlier real
approvals could have worked is an ephemeral `export P1_DB_PATH=...` set
directly in whatever terminal was running the dashboard at the time --
never written anywhere durable, so it evaporated the moment that
terminal was closed and a fresh one (`source .venv/bin/activate` +
`uv run streamlit run app/approval_dashboard.py`) started the process
over, silently falling back to the wrong database.

**Fix.** Added `P1_DB_PATH=data/p1_live.db` to `.env` itself, so the
dashboard resolves the same live database every launch, from a
committed source, the same way `TEAMS_PUBLISHER_MODE` and everything
else already does. Also added a paragraph to README.md (next to the
existing `data/p1_live.db` explanation) documenting this requirement
explicitly, so a `.env` recreated from scratch on another machine does
not silently reintroduce the same gap.

**Judgment calls.** Did not change `DEFAULT_DB_PATH` itself, and did
not make the dashboard default to `data/p1_live.db` in code -- the
dashboard's whole point (per its own module docstring, CHN-25) is
being one generic fallback surface usable against whichever database a
deployment points it at via `P1_DB_PATH`; hardcoding the live path
into the dashboard itself would quietly break every existing
mock-fixture test and demo flow that deliberately runs it against
`data/p1.db`. Fixing the *pointer* in `.env` (a per-deployment config
concern) rather than the *code* (a shared, tested default) keeps that
separation intact.

**Non-vacuousness.** Not applicable in the usual disable/reproduce
sense -- this is a plain, already-reproduced configuration gap (the
dashboard visibly showed "Nothing awaiting approval" against a
database confirmed via direct sqlite query to actually have a pending
row), not a code branch to toggle. Confirmed the exact env var name and
its complete absence from every persistent source via the grep above
before writing the fix, rather than guessing.

**Verified.** `.env` now contains `P1_DB_PATH=data/p1_live.db` (checked
directly). Full proof is the project owner restarting the dashboard
once more and confirming the 2026-09-21 proposal now appears -- pending
at time of writing.

**Not done, on purpose.** Did not audit whether any *other* script or
surface relies on an env var that was similarly only ever set
ephemerally in a shell rather than persisted -- this entry only closes
the one instance actually hit.

## 2026-09-19 -- CHN-22/CHN-25: the real write path proven live end to end, for the first time, with real content

**Context.** Closing entry for this day's investigation: after fixing
the missing `load_dotenv()` call, the unreachable `mark_published()`
call, and the unpersisted `P1_DB_PATH` pointer (all three entries
above), the real 2026-09-19 digest -- containing the two genuine
roster updates, previously stuck in `data/outbound_log.jsonl` instead
of Teams -- was reposted via a dedicated, disclosed one-off script
(`scripts/repost_stuck_digest.py`, modelled on
`scripts/power_automate_smoke_test.py`) that reads the real, already-
`applied` proposal's content straight out of `data/p1_live.db` and
posts it directly through `PowerAutomateTeamsPublisher`, bypassing the
guarded approval path entirely (deliberately -- `applied` is a
permanent terminal state by design, and this is a manual, disclosed,
one-time recovery of content that was already legitimately approved,
not a second automated send).

**Finding.** The flow's HTTP trigger returned `202 Accepted` (as always
-- a 202 only proves the trigger queued the request, not that the
Teams post itself succeeded, per this session's earlier finding on
Power Automate trigger semantics). This time, unlike every earlier
attempt, the message was independently confirmed to have actually
landed in the real `p1-agent-test` Teams channel -- the project owner
pasted back the exact message as it appears in Teams, disclosure line
and all, matching what the script sent verbatim.

**Verified.** The full write path -- real digest content, generated by
the real pipeline, approved once for real, reaching the real Teams
channel through the real Power Automate flow -- is now proven live,
for the first time this engagement, with an independent human
confirmation (not just an HTTP status code or a database row).

**Not done, on purpose / still open.** Whether the `[source](url)`
markdown links actually render as clickable hyperlinks inside Teams
itself (rather than literal bracket/parenthesis text) has not yet been
independently confirmed -- the pasted confirmation shows raw markdown
syntax, which may just be an artifact of how the text was copied out of
Teams, or may mean the "Post message in a chat or channel" action needs
to be told its body is Markdown/HTML rather than plain text. This is
directly relevant to CHN-13's own grounding/citation requirement ("a
permalink clicked live" per the implementation plan's demo checklist)
and needs a direct check: click a `[source](...)` link inside the real
Teams channel and confirm it navigates to the real message, rather than
displaying as inert text.

## 2026-09-20 -- CHN-17/21/23: nothing ever ran on a schedule -- build_scheduler() was wired but never started, and ingestion/nudges/escalations were never scheduled at all

**Context.** While live-testing the approval flow on p1-agent-test, a
real message posted mid-morning never showed up in that same day's
approved digest, and the person testing it correctly asked why
ingestion appeared to be "ignored" and how nudges could ever be trusted
if they might be checking stale data.

**Finding.** Two separate gaps, not one: (1)
`p1.publishing.scheduler.build_scheduler()` correctly builds a real
APScheduler `BackgroundScheduler` with one `CronTrigger` per channel at
`daily_digest_time` -- but grepping the entire codebase for `.start()`
found nothing anywhere that ever calls it. It was built, tested, and
never deployed. (2) Even started, `build_scheduler()` only ever
schedules the daily digest job. Ingestion (`sync_channel()`) has never
been called by anything except a person running
`run_live_ingest_p1_agent_test.py` / `run_live_pipeline_p1_agent_test.py`
by hand, and `nudge_job.py`/`escalation_job.py` have never been wired
into any scheduler either, also only ever run manually. Every real
run on this channel to date -- ingest, digest, nudge -- has been a
one-off manual script invocation, never a running process.

**Fix.** `scripts/live_runner_p1_agent_test.py`: one long-running
process that (a) polls Graph ingestion on a real interval
(`INGEST_POLL_MINUTES`, default 5) instead of only on a keypress, (b)
calls `build_scheduler().start()` for the first time anywhere in this
codebase, and (c) adds a second `CronTrigger`, not previously
existing anywhere, that runs `run_nudge_job()` then
`run_escalation_job()` once per working day at the channel's own
`update_window_end` -- nudge before escalation because
`escalation_job.py`'s own guarantee 3 requires a person to have already
been nudged before they can ever be escalated.

**A second, blocking problem found in the course of building this.**
`scripts/graph_login.py`'s own docstring already flags it: Graph access
tokens are short-lived (~1hr) and "turning this into something that
refreshes itself automatically without a human in the loop is a
separate future step, deliberately not attempted here." An ingestion
poll running all day cannot work at all under that constraint -- it
would die silently after about an hour. `p1.adapters.graph_auth` is
that future step, taken now: a persisted MSAL `SerializableTokenCache`
(`data/graph_token_cache.bin`, already covered by `.gitignore`'s
wholesale `data/` rule) seeded by one interactive device-code sign-in
(`scripts/graph_seed_token_cache.py`, or the live runner's own first
startup), after which every ingestion poll calls
`acquire_token_silent()` against the cached refresh token -- no
browser, no human, no code, until that refresh token itself expires or
is revoked (Azure AD default ~90 days of inactivity).

**Judgment calls.** Unattended callers (the poll loop itself) always
pass `allow_interactive=False`: if silent refresh ever fails,
`get_access_token()` raises `GraphAuthError` and the poll tick logs it
and skips, rather than ever blocking a background thread on a
device-code prompt nobody may be watching. Only the live runner's own
`main()`, running in the foreground at startup with a person at the
terminal, ever passes `allow_interactive=True`. Both `_poll_ingest()`
and `_run_nudges_and_escalations()` catch every exception and log
rather than raise, matching `run_daily_digest_job()`'s own idempotent,
safe-to-call-repeatedly posture -- one bad tick (a transient Graph
error, a rate limit) must never take down the whole process.

**Not done, on purpose / still open.** This is a foreground process
(`Ctrl+C` to stop); running it under a real supervisor (systemd,
launchd, a container) for actual unattended production use is a
separate, deliberate future step, not attempted here. Config
(`daily_digest_time`, `update_window_end`, `working_days`, etc.) is
read once at startup, same restart-to-pick-up-a-change caveat this log
already notes for the Streamlit dashboard. `build_scheduler()` itself
is untouched -- this script only calls it and adds jobs to the
scheduler it returns, so every existing test of `build_scheduler()`'s
own wiring still holds unmodified.

## 2026-09-20 -- CHN-03/CHN-05: two gaps found while re-verifying the scope gate and schema against the original delivery plan rows, both fixed and tested

**Context.** Re-checked two delivery-plan rows against the actual code
rather than the docstrings alone: "Scope gate - allowlisted channels
only, chats never read" and "SQLite schema and migrations." Both mostly
held up; two real gaps were found underneath the surface-level claims.

**Gap 1 -- `messages_fts` was declared, never populated.** `0001_initial.sql`
declares `messages_fts` as an external-content FTS5 table
(`content='messages', content_rowid='rowid'`). SQLite does not sync an
external-content table automatically -- nothing anywhere in the
codebase ever inserted into it, and no query anywhere ever ran a MATCH
against it. Confirmed live: `SELECT * FROM messages_fts` and
`count(*)` both read through to the content table and looked populated,
but `SELECT ... WHERE messages_fts MATCH '...'` -- the only kind of
query full-text search actually means -- returned nothing at all,
proving the index itself was empty regardless of what a plain SELECT
suggested.

**Fix.** `0006_messages_fts_sync.sql`: `AFTER INSERT/UPDATE/DELETE`
triggers on `messages` keep the FTS index in sync going forward, plus a
one-time `INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')` to
backfill every message ingested before this migration existed
(p1-agent-test's real messages included). Verified directly: seeded a
db with only migrations 0001-0005 (the "before" state), confirmed a
MATCH query against a real inserted row found nothing, then applied
0006 alone and confirmed the same MATCH query found it. Insert, update,
and delete triggers were each verified independently (search finds new
content, an edited body re-indexes, a deleted row's content stops
matching).

**Gap 2 -- `list_replies()`/`get_permalink()` had no independent allowlist
check.** `ScopedTeamsReader` enforced the allowlist on
`list_messages()`/`list_channel_members()`, but these two methods take
only a `message_id`, and the previous version delegated them straight
to the wrapped reader with no check at all here -- relying entirely on
`GraphTeamsReader`'s own internal `message_id -> channel_id` cache to
make an out-of-scope call impossible in practice. That is true only as
long as every `TeamsReader` implementation happens to enforce that
invariant itself; `MockTeamsReader.list_replies()`/`get_permalink()`
do not (they scan every channel's messages, not just allowlisted ones)
-- exactly the "merely unlikely, not structurally impossible" gap this
module's own docstring says is the one failure mode that must not
exist.

**Fix.** `ScopedTeamsReader` now keeps its own
`_channel_id_by_message_id` record, populated only from messages it has
itself returned through a gated `list_messages()`/`list_replies()`
call -- never borrowed from the wrapped reader. `list_replies()`/
`get_permalink()` now resolve the channel from that record and enforce
the allowlist against it exactly like `list_messages()` does; a
message_id this gate has never itself seen is refused outright, audited
the same way (`entity_type="message"` instead of `"channel"`).
`tests/unit/test_scope_gate.py`'s old
`test_list_replies_and_get_permalink_pass_through_without_a_channel_check`
(a test that named and asserted the bug) was replaced with tests
proving: an unseen message_id is refused; a legitimately-seen one
succeeds; and -- the sharpest proof -- `MockTeamsReader`'s own willingness
to answer an out-of-scope message_id doesn't help, because this gate
refuses it before ever asking the wrapped reader.

**A third, related bug found and fixed while testing `live_runner_p1_agent_test.py` live (same day).**
Its first version called `sync_channel()` on every poll tick but never
`classify_and_persist()` -- a message would land in `messages` but
never in `classifications`, so it stayed permanently invisible to
`gather_daily_facts()` (which reads `classifications`, never
`messages`, directly), no matter how fresh ingestion was. Confirmed
live: the person's own real 9:55am update was ingested (visible in
`messages`) but never classified, so it could never have appeared in
any digest. Fixed by adding the same read-back-and-classify step
`run_live_pipeline_p1_agent_test.py` already does
(`_load_channel_messages()` + `classify_and_persist()`) to every
ingest tick -- safe to re-run against the channel's full known message
set each time since `ClassificationStore.record()` is an
upsert-on-message_id, not an append.

**Verified.** Full suite (466 passed, 2 skipped) after all three fixes,
plus a live functional check of the fixed `_poll_ingest()` against a
seeded db with a rule-settled (bot) message, confirming the tick now
logs both an ingest count and a classify count and writes a real
`classifications` row.

**Not done, on purpose.** `messages_fts` is now populated but nothing
yet queries it -- no capability in this codebase does full-text search
today; this fix makes that possible, not exercised. The live runner
(this same day's earlier entry) still needs restarting to pick up the
classification fix -- a config/code change made while it's running is
never picked up live, same restart caveat already noted for it and for
the Streamlit dashboard.

## 2026-09-20 -- CHN-25's two "not done, on purpose" items closed: agent instructions written, Dataverse table found unnecessary

**Finding.** The 2026-09-18 "solution-aware and wired into the live
agent" entry left two items open: the agent's own conversational
instructions were never written, and "the Dataverse table for channel
config... is still not built." Revisiting the second one against this
repo's own already-documented design (`connector_contract.md`'s
"Dataverse table mapping" section, and `config/loader.py`'s own
docstring) found that a literal Dataverse table was never actually
required for the config surface to work end to end -- `channel_config`
(SQLite), reached live through the already-attached "Update Channel
Config" Tool, already plays that role. Building a separate Dataverse
table now would create a second copy of the same roster/window/
exceptions data, which is exactly what this row's own "reconciled, not
duplicated" design rule already rules out. Also found, by reading
`copilot_studio_api.py`'s `UpdateChannelConfigRequest` and its
`body.model_dump(exclude_none=True)` call into
`handle_update_channel_config()`: calling that same Tool with only
`channel_id`/`updated_by` set (every optional field omitted) already
returns the channel's current config with no write and no audit row --
`ChannelConfigStore.update_channel_config()`'s own `if not changes:
return current` short-circuit makes this a real, already-tested,
zero-code-change "read current config" path through the one Tool that
exists, so no sixth Tool was needed either.

**Build.** `docs/copilot_studio/agent_instructions.md`: the agent's
general instructions (persona, hard rules on never fabricating a
proposal_id/identity, always relaying a tool's own outcome/detail
rather than assuming success), a description for each of the 5 Tools
matched to what Copilot Studio's own orchestration uses to pick a
tool, the identity-binding note for `approver_id`/`updated_by` (map to
the agent's built-in current-user value in the Tool input-mapping step,
never left for the model to fill from conversation text), the
"call Update Channel Config with only channel_id/updated_by to read,
not write" pattern documented as the intended usage, and a live test
checklist (real Teams utterances against the real agent, cross-checked
against `proposals`/`audit` rows in `data/p1_live.db`) -- since no unit
test can prove which utterance triggers which tool, that only exists as
portal state.

**Judgment call.** Recommended against building the Dataverse table
rather than building one anyway to literally match the row's original
wording, since building it would regress the single-write-path
guarantee `update_channel_config()` exists to provide (see
`connector_contract.md`, already-decided). This is a scope correction
to a design question the row's original text left ambiguous
("Dataverse-backed... surface"), not a reversal of anything already
verified live -- the 5 Tools, the live API, and the solution-aware
connector wiring from 2026-09-18 are all unchanged and still confirmed
reachable.

**Not done, on purpose.** Pasting `agent_instructions.md`'s text into
the actual "P1 Channel Intelligence" agent's Instructions field and
each Tool's description field is Power Platform maker-portal
configuration -- it has to be done by hand in that portal, the same as
every other Copilot Studio step in this programme; this repo can
document exactly what to paste but cannot paste it. Confirming the
`approver_id`/`updated_by` identity-binding step is also left to the
maker portal, since the exact system-variable name Copilot Studio
exposes for "current Teams user" was not something this repo could
verify without tenant access. The optional Dataverse-backed grid view
(a visual alternative to the conversational config answer, not
required for this row's own acceptance test) remains unbuilt, and is
not planned unless specifically asked for.

## 2026-09-20 -- copilot-api: PYTHONPATH=src added to the Makefile target, since `p1`'s editable install is unreliable for a dotted-module import

**Finding.** Restarting `make copilot-api` tonight (after the earlier
ngrok tunnel had gone offline) hit `ModuleNotFoundError: No module
named 'p1'` -- reproduced identically with and without `--reload`,
ruling out the reload-subprocess theory. This is the same
`.pth`-processing unreliability already diagnosed for `scripts/*.py`
entry points (see this file's own earlier entry, "Each script in
scripts/ inserts src/ onto sys.path..."), just hitting a case that
workaround cannot cover: every `scripts/*.py` file adds `src/` to
`sys.path` at the top of its own file, before it imports `p1` -- but
`uvicorn p1.api.copilot_studio_api:app` has to resolve `p1` as a
dotted import target before any of that file's own code ever runs, so
a fix written inside the file (including this same module's own
`sys.path.insert` line, added for a different reason -- see its
docstring) cannot rescue this particular invocation shape.

**Build.** `Makefile`'s `copilot-api` target now runs with
`PYTHONPATH=src` set: `PYTHONPATH=src uv run uvicorn
p1.api.copilot_studio_api:app --reload --reload-dir src`. Unlike the
editable install's own `.pth` file (confirmed present and pointing at
the right absolute path, so this is not a missing-file problem, just
an unreliable one), `PYTHONPATH` is read directly by the interpreter's
own `site` initialization independent of `.pth` processing, so it is
not subject to the same flakiness.

**Not done, on purpose.** The underlying `.pth`-unreliability itself is
still not root-caused -- same as the earlier entry's own conclusion,
fixing the symptom at each call site has been more worthwhile than
chasing why `uv sync`'s editable install intermittently doesn't take
in this environment. If it recurs somewhere PYTHONPATH can't reach
(another dotted-module entry point added later), the same one-line fix
applies there too.

## 2026-09-20 -- CHN-25 live end-to-end test blocked: Copilot Studio environment is out of Credits

**Finding.** With the agent's instructions and tool descriptions in
place (this file's earlier entry today) and the API + tunnel confirmed
live (`{"status":"ok","api_key_configured":true}` from the real
`copilot_studio_api.py` through the current ngrok forwarding URL), the
first real test message sent to the agent (via Copilot Studio's own
Preview/test chat, not yet Teams -- see below) failed with:
`EnforcementUsageCredits` -- "You need credits to continue. Credits
power building and running your agents and workflows. This
environment is out of credits." This is a tenant-level Power Platform
billing/capacity limit, not a code, config, or connector defect --
nothing in this repo can work around it.

**Also found, separately.** The agent's "Channels" section is still
empty (no Microsoft Teams channel has been added/published) -- so even
once credits are restored, a genuine "test it in Teams" pass still
needs a Channels > Microsoft Teams > Publish step in the maker portal
first. Today's test was run (and blocked) via Copilot Studio's own
Preview pane, which talks to the same draft agent and the same 5 live
tools without requiring that publish step -- the right way to verify
wiring before spending the extra step of publishing to Teams.

**Not done, on purpose.** Adding credits or checking the reset date is
an admin/billing action in the Power Platform admin center, outside
what this repo or its own maker-portal access can do. Publishing the
agent to a Microsoft Teams channel is also still outstanding, deferred
until a Preview-pane pass succeeds end to end (no reason to publish an
agent that cannot yet complete a single turn).

## 2026-09-20 -- copilot_studio_api.py was silently reading the wrong database (data/p1.db, not data/p1_live.db)

**Finding.** Proving the CHN-25 wiring directly against the live API
(bypassing Copilot Studio's own Credits block -- see this file's
own entry on that) surfaced a real bug, not a Credits-side effect:
`POST /list_pending_approvals` returned `{"approvals":[]}` and
`POST /update_channel_config` for `channel_id=p1-agent-test` 404'd
with "No configuration found ... in PosixPath('data/p1.db')" -- on a
channel that genuinely has a synced config and, at the time, genuinely
had live data. Both were symptoms of the same cause: every
`handle_*` call in `copilot_studio_api.py` ran with no `db_path`
argument at all, so each one silently fell back to
`copilot_studio_connector.py`'s own default parameter,
`DEFAULT_DB_PATH = "data/p1.db"` -- a fresh, essentially-empty
database, completely separate from `data/p1_live.db`, the one
`scripts/live_runner_p1_agent_test.py` actually ingests into,
`sync_to_db()`s config into, and publishes from. The two database
files existed side by side in `data/` the whole time; the API was
just pointed at the wrong one. `.env` already had `P1_DB_PATH=
data/p1_live.db` set (from earlier in this programme, anticipating
exactly this), but nothing in `copilot_studio_api.py` ever read that
variable -- the module's own docstring even says "any DB_PATH a real
deployer points this at", naming the seam without ever wiring it up.

This means every one of tonight's earlier live-wiring claims for
CHN-25 (5 Tools attached, instructions pasted, API+tunnel healthy)
was accurate on its own terms, but the Copilot Studio agent -- once
Credits allow it to complete a turn at all -- would have been talking
to an empty, disconnected database indefinitely, silently, with no
error surfaced anywhere a maker-portal test would have shown it
(an empty "what's pending" answer looks identical to a correct one).

**Build.** `copilot_studio_api.py`: added `DB_PATH_ENV_VAR =
"P1_DB_PATH"` and `DB_PATH = Path(os.environ.get(DB_PATH_ENV_VAR,
str(DEFAULT_DB_PATH)))`, computed once at import time from the
already-configured `.env` value. `_lifespan()` now calls
`init_db(DB_PATH)` instead of `init_db()`; all four action endpoints
now pass `db_path=DB_PATH` into their `handle_*` call instead of
relying on the handler's own default. `/health` now also reports
`db_path` in its response, so a future mismatch like this one would
be visible from the very first reachability check, not just from a
suspiciously-empty answer three calls later. No test-suite behavior
changes: `tests/unit/test_copilot_studio_api.py` never sets
`P1_DB_PATH`, so `DB_PATH` still resolves to the same relative
`DEFAULT_DB_PATH` those tests already `monkeypatch.chdir()` around --
verified by inspection of every call site, not just assumed.

**Not done, on purpose.** The live API process already running in the
user's terminal from earlier tonight is still running the pre-fix
code (Python doesn't hot-reload an already-imported module-level
constant, and even `--reload` only re-execs on a file save it watches
after the fact) -- it needs to be restarted for this fix to take
effect. Re-running the same three curl commands from this file's
"live end-to-end test blocked" entry (list_pending_approvals, and a
peek update_channel_config for p1-agent-test) after that restart is
what actually proves this fix, not just the code diff.

## 2026-09-20 -- correction: tonight's "Anthropic API" classification/digest/weekly claims were wrong -- the live system has been running on local Ollama the whole time

**Finding.** Investigating why `scripts/test_weekly_today_adhoc.py` failed with
byte-identical `StructuredOutputError` output on two independent runs led to
checking `data/logs/llm_calls.jsonl` (every `LLMGateway.generate()` call is
logged there with `provider`, `model`, `cache_hit`, `degraded`). The full log
(561 entries, going back to 2026-09-19 13:02 -- before this entire live-testing
programme started) shows **100% `provider: "ollama"`, `model:
"qwen2.5:7b-instruct"`, zero `provider: "anthropic"` entries, and `degraded:
false` on every single one.** `degraded=false` on every row rules out the
"fallback after an Anthropic failure" theory -- degrade-to-Ollama only fires
when a direct Anthropic/Bedrock call raises `LLMGatewayError`; here, no
Anthropic call was ever attempted to fail. Root cause, confirmed directly:
`.env` (mtime 2026-09-19 17:21, so already in place before tonight's session)
has `LLM_PROVIDER=ollama` explicitly set, and has **no `ANTHROPIC_API_KEY` at
all** -- `grep -c "^ANTHROPIC_API_KEY=" .env` returns 0. `LLMGateway.__init__`
reads `self.provider = provider or os.environ.get("LLM_PROVIDER", "anthropic")`
-- with `LLM_PROVIDER=ollama` set, this resolves to `"ollama"` on every
instantiation, unconditionally. My own earlier doc,
`docs/P1_TEST_VERIFICATION_2026-09-19.md`, already said this in writing
("`LLM_PROVIDER=ollama` needs your local Ollama") -- I had the evidence
committed to this repo and repeated the wrong claim anyway tonight.

This means every claim made tonight that "the Anthropic API is genuinely
working" for CHN-09 classification (question/blocker/decision labels),
CHN-13 daily digest generation, or CHN-19 weekly narrative generation was
**wrong**. The rules-first split (deterministic rules, then a model call for
the remainder) is real and live-tested as described; the model on the other
end of that remaining call has been the local `qwen2.5:7b-instruct` running
on the user's own Mac via Ollama, not Claude. This also plausibly explains
the weekly-narrative `StructuredOutputError`: a small local 7B model failing
to keep tool-call output flat to a JSON schema (returning
`{"properties": {"narrative": ...}}` instead of `{"narrative": ...}`) is a
well-known weak-model tool-use failure mode, not a Claude Sonnet 4 quirk --
the byte-identical repeat across two runs is consistent with a
deterministic/near-deterministic local model producing the same malformed
shape given the same prompt, rather than a fresh Claude sampling failure.

**Not done, on purpose.** Not switching `LLM_PROVIDER` or adding a real
`ANTHROPIC_API_KEY` without the user's go-ahead -- that changes what model
tonight's already-recorded classifications and digests would be regenerated
against, and the user has not said whether they have a key to use for this
environment. Flagging this here as the authoritative record instead of
letting the earlier (wrong) claims stand uncorrected in this file.

## 2026-09-20 -- Bedrock smoke test: real 403 from AWS, not a code or config bug -- IAM policy is missing the required second statement for cross-region inference profiles

**Finding.** After setting `LLM_PROVIDER=bedrock` and the new
`p1-agent-bedrock-demo` AWS keys the user supplied, running the new
`scripts/test_llm_gateway_smoke.py` in the user's own terminal (real venv,
`skip_cache=True`, so a genuinely fresh call) produced a real AWS response,
not a local error:

`Bedrock API error: Error code: 403 - {'Message': 'User:
arn:aws:iam::619042036275:user/p1-agent-bedrock-demo is not authorized to
perform: bedrock:InvokeModel on resource:
arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0
because no identity-based policy allows the bedrock:InvokeModel action'}`

`LLMGateway.generate()`'s existing degrade-to-Ollama path (see the CHN-31/
CHN-26 decision-log entries) caught this correctly and transparently --
`degraded: True` was reported, the underlying AWS error text was preserved
and printed, not swallowed, and the log entry for this call (`data/logs/
llm_calls.jsonl`) will show `provider: ollama, degraded: true` for exactly
this call, distinguishable from the 561 pre-existing `degraded: false`
entries this session already found (see this file's own prior entry on
that). This is the gateway working as designed, not a new bug.

**Root cause (confirmed against AWS's own documentation, not assumed).**
`BEDROCK_MODEL_ID` in `.env` is a **cross-region inference profile** ARN
(`arn:aws:bedrock:us-east-2:619042036275:inference-profile/
us.anthropic.claude-sonnet-4-20250514-v1:0`, the `us.` prefix marking it as
one). Per AWS's own "Prerequisites for inference profiles" documentation,
an IAM policy authorizing a cross-region inference profile needs **two**
statements: `bedrock:InvokeModel*` on the inference-profile ARN itself
(present here -- the grant the user's admin issued was scoped to
`bedrock:InvokeModel`/`InvokeModelWithResponseStream` in `us-east-2` only),
**and a second statement** granting `bedrock:InvokeModel*` on the
underlying `foundation-model` ARN(s) in each Region the profile can route
requests to, scoped back down via a
`"Condition": {"StringLike": {"bedrock:InferenceProfileArn": "<the profile
ARN>"}}` clause -- AWS's own documented example for a Claude Sonnet 4
profile is exactly this shape. `p1-agent-bedrock-demo`'s policy has only
the first statement, not the second, so any request the profile happens to
route to a region without an explicit foundation-model grant (this call
landed in `us-east-1`) is denied even though the caller does hold
`InvokeModel` on the profile ARN and even though `AWS_REGION=us-east-2`
matches where the client itself connects. This is a real, external
AWS-account permissions gap, not anything wrong in this repo's code,
`.env`, or `BEDROCK_MODEL_ID` value.

**Not done, on purpose.** Widening the `p1-agent-bedrock-demo` IAM policy is
outside this repo's or this session's control -- it requires whoever issued
these keys (the same person/team who sent the credential email) to add a
second statement to that user's policy. `LLM_PROVIDER` is left at
`bedrock` rather than reverted to `ollama`, since the failure mode is
already safe (transparent degrade, not a silent wrong answer) and reverting
would erase the evidence trail this test just produced.

## 2026-09-20 -- fix: Ollama's structured-output prompt was showing the model the JSON Schema wrapper itself, not an example of the answer -- root cause of the weekly narrative StructuredOutputError

**Finding.** `_call_ollama()` (Ollama has no native Anthropic-style tool-calling API -- see its own docstring, CHN-27) hands a weak local model its only shape hint by dumping the raw `tool["input_schema"]` (i.e. `schema.model_json_schema()`) into the prompt behind the words "Respond with ONLY a single JSON object matching this schema exactly." For `WeeklyNarrativeDraft` (one real field: `narrative: str`), that raw schema is `{"properties": {"narrative": {"title": "Narrative", "type": "string"}}, "required": ["narrative"], "title": "WeeklyNarrativeDraft", "type": "object"}`. The two live failures pasted tonight show `qwen2.5:7b-instruct` echoing that wrapper back verbatim with only the leaf value replaced --
`{"properties": {"narrative": "<the real narrative text>"}}` -- instead of producing a flat instance (`{"narrative": "..."}`). This is a known weak-model tool-use failure mode (pattern-completing the literal structure it was shown, rather than treating it as a schema to instantiate), not a Claude-side issue and not caused by the `_no_digits` validator (which was retried against, not the cause of the shape being wrong in the first place). `ClassificationResult` and `DailySummarySectionDraft` happen not to have hit this tonight, but their raw schemas have the identical `"properties"` wrapper shape -- the same failure was always latent for them too, just not yet triggered.

**Build.** Added `_example_instance(schema, defs=None)` to `src/p1/llm/gateway.py` (module-level, right after `_strip_markdown_json_fence`): walks a JSON Schema dict (`$ref`/`$defs`, `enum`, `anyOf`/`oneOf`, `object`/`properties`, `array`/`items`, and the scalar types) and returns a placeholder **instance** of it -- e.g. `{"narrative": "<value>"}` for `WeeklyNarrativeDraft`, `{"label": "update", "confidence": 0.0}` for `ClassificationResult`, `{"lines": [{"message_id": "<value>", "text": "<value>", "quote": "<value>"}]}` for `DailySummarySectionDraft` -- verified directly against all three of this repo's real schemas before touching the live prompt path. `_call_ollama()`'s prompt now leads with this concrete flat example, followed by an explicit "do NOT nest your answer under a `properties` key, and do NOT include `type`/`title`/`required` keys" instruction, and only then the full schema "for reference." The full schema is kept, not removed -- this adds a disambiguating example in front of it rather than replacing information the model had before.

**Not done, on purpose.** Not yet proven against a live Ollama server -- `python3 -m py_compile` passed and `_example_instance` was unit-checked in isolation against this repo's three real schemas, but the actual fix for the reported failure (does `qwen2.5:7b-instruct` now return a flat `{"narrative": ...}` instead of the `{"properties": {...}}` wrapper) can only be confirmed by re-running `scripts/test_weekly_today_adhoc.py` live, which needs the user's own terminal/venv exactly as the two prior failing runs did. Also not done: touching `ClassificationResult`'s or `DailySummarySectionDraft`'s prompts or call sites -- this fix is entirely inside `_call_ollama()`'s own prompt construction, so every existing caller benefits without any change to `structured.py`, `classifier.py`, `daily_summary.py`, or `weekly_summary.py`.

## 2026-09-20 -- second fix: unwrap a schema-echoed payload once, deterministically, instead of relying on a retry to fix it

**Finding.** The prompt fix above (leading with a flat example instance) was tested live: `scripts/test_weekly_today_adhoc.py` now succeeds, where it failed completely (3/3 attempts, twice) before. But the pasted output shows attempt 1 *still* returned the schema-echoed shape --
`error=1 validation error for WeeklyNarrativeDraft \n narrative \n Field required [... input_value={'properties': {'narrativ... throughout the week.'}}]` -- and only a later retry produced a flat, valid instance. So the prompt fix reduced the failure rate but did not eliminate the underlying echo behaviour; production correctness was riding on `generate_structured()`'s 3-attempt retry budget catching what attempt 1 still gets wrong, which costs an extra full model round-trip every time and is not a guarantee for a schema/message combination unlucky enough to echo on every attempt.

**Build.** Added `_unwrap_schema_echo(payload, schema)` to `src/p1/llm/structured.py`, called on the parsed payload immediately before `schema.model_validate(payload)`, inside `generate_structured()`'s existing try block. Logic: if any of the schema's own field names already appear as top-level keys, the payload is left untouched (covers every correctly-shaped response, from any provider); otherwise, if `payload["properties"]` exists and is a dict containing the schema's field names, that inner dict is used instead. `"properties"` is never itself a real field name in this codebase's schemas (`narrative`, `label`/`confidence`, `lines`), so the unwrap cannot misfire against a legitimately-named field. Unit-verified in isolation (payload variations: already-flat, schema-echoed, and genuinely-unrelated-garbage) against fake schemas standing in for `WeeklyNarrativeDraft` and `ClassificationResult` -- all five cases behaved as intended, including garbage input still failing validation loudly rather than being silently guessed at. Read the two existing tests that exercise this exact path
(`tests/unit/test_llm_gateway_ollama_structured.py`,
`tests/unit/test_structured_output.py`) line by line against both patches
before committing to them: neither asserts on the literal prompt text this
change doesn't touch, and every payload shape they already exercise
contains at least one real field name at the top level or is empty/invalid
JSON, so `_unwrap_schema_echo` leaves their expected behaviour unchanged --
not run here, since this sandbox's own Python environment lacks
pydantic/pytest entirely (separate from the user's real project venv), so
this is reasoned from the source, not machine-verified.

**Not done, on purpose.** Have not re-run `scripts/test_weekly_today_adhoc.py`
against this second fix yet -- that needs the user's real terminal/venv, same
as every other live check tonight. Have not run the real `pytest` suite
either, for the same environment reason -- asking the user to run
`uv run pytest tests/unit/test_llm_gateway_ollama_structured.py
tests/unit/test_structured_output.py -v` themselves is the next step, not
a rubber-stamped "should be fine."

## 2026-09-20 -- confirmed live: CHN-19 weekly narrative now succeeds cleanly, no retry needed

**Finding.** User ran both checks in their real venv:
`uv run pytest tests/unit/test_llm_gateway_ollama_structured.py
tests/unit/test_structured_output.py -v` -- all 6 existing tests still pass,
confirming neither of tonight's two fixes (the Ollama example-instance prompt
in `gateway.py`, the `_unwrap_schema_echo` repair in `structured.py`) broke
anything already relied on. Then `scripts/test_weekly_today_adhoc.py` --
this run produced a real, valid `WeeklyNarrativeDraft` with **no
`structured_output_retry` warning line at all**, unlike both prior failing
runs and even unlike the immediately-preceding run (which needed a retry
after attempt 1 echoed the schema). This is the strongest evidence yet:
either the improved prompt got it right on the very first attempt this
time, or `_unwrap_schema_echo` silently repaired an attempt-1 echo before
validation ever saw it -- either way, one clean model call produced a
valid, grounded, digit-free narrative sentence for a real live week
("The team made progress with a significant increase in rate, achieved one
decision, and faced a single unanswered question throughout the week."),
persisted through the same `generate_and_persist_weekly_rollup()` path the
real weekly scheduler would use (once one exists -- see the still-open
"no weekly-publish scheduling job exists" gap from earlier tonight).

CHN-19 is now live-tested with genuine evidence, matching CHN-09 and
CHN-13's status from earlier tonight -- not just code-reviewed.

**Not done, on purpose.** One clean run is evidence, not a guarantee -- the
underlying model can still echo the schema shape on some future call
(the fix makes that survivable via the deterministic unwrap, not
impossible). Nothing further changed; this is a confirmation entry, not a
new build.

## 2026-09-20 -- P1 C1/P2 P6/P3 O4 ("Roster, window, thresholds and exceptions -- Python config schema + Dataverse surface"): the live-edit half of this row was never actually wired into the running system

**Finding.** Traced every real caller of `ChannelConfigStore.get_effective_config()` -- the CHN-25 live-read path this row's own reasoning ("the channel owner ... needs to maintain it without a deploy") was built for -- across the whole codebase. There are exactly two: `src/p1/approval/service.py` (only to look up `channel_owner_id` when resending an approved escalation) and `app/approval_dashboard.py` (the Streamlit page's own display). **Nothing in the real ingest/classify/digest/nudge/escalation pipeline ever calls it.** `scripts/live_runner_p1_agent_test.py`'s `main()` loads config exactly once at startup with `get_channel_config()` (the plain committed-YAML read, not the DB-backed live one), holds that single object, and passes it by reference into every scheduled job (`_poll_ingest`, `_run_nudges_and_escalations`, `build_scheduler`'s per-channel cron jobs) for the rest of the process's life -- confirmed by reading each of those functions, none of which re-fetch config.

Proved live tonight: used `scripts/test_live_config_update_adhoc.py` (calling the exact same `update_channel_config()` Copilot Studio's tool and Streamlit call) to write `update_window_end` from `17:30:00` to `12:00:00` in the live DB (version 1 -> 2), confirmed the write and the version bump, then reverted (version 2 -> 3) -- both writes succeeded cleanly, so the write/validate/audit side of this feature works exactly as built. The revert happened before an ingest poll tick fired in between (5-minute interval), so the specific live-witnessed "the running process's classify counts didn't move" observation was not captured this session -- the finding rests on exhaustive call-site tracing (every `get_effective_config()` call site read, every scheduled-job function read), not on watching a tick happen mid-divergence. Flagging this distinction explicitly rather than overstating it as fully live-witnessed.

Three compounding gaps, not one:
1. The running process never re-reads live config at all (above).
2. Even a restart doesn't help: `main()` calls `sync_to_db()` unconditionally on every startup, which resyncs the DB from committed YAML -- so a live edit sitting in the DB gets silently overwritten back to the YAML value on the next deploy/restart, rather than surviving it. (This part is actually documented as intentional in `loader.py`'s own module docstring -- "a live edit is a running override, not a fork of the source of truth" -- but combined with gap 1, it means a live edit currently has NO path to ever taking effect on the real system: not while running, not after a restart.)
3. `update_channel_config()` only accepts three fields -- roster, update_window_start/end, exceptions. "Thresholds" (`length_floor`, `count_thread_replies`), named explicitly in this spec row's own first column, was never exposed as a live-editable field at all -- it is YAML-only/deploy-only by design, per the same docstring, so even fixing gaps 1-2 would not cover thresholds without further work.

The row's second column, "Dataverse surface", is separately already known-blocked by a real Power Apps permissions wall (this file's earlier entry today) -- so neither half of "Python config schema + Dataverse surface" currently delivers the row's own stated reason for existing (a channel owner maintaining roster/window/thresholds/exceptions without a deploy).

**Not done, on purpose.** Not wiring `_poll_ingest`/`_run_nudges_and_escalations`/`build_scheduler`'s jobs to call `get_effective_config()` per tick instead of using the frozen startup snapshot -- that is a real, buildable fix (unlike the Dataverse permissions wall) but is a design/behavior change to the live pipeline the user has not yet asked for and hasn't reviewed the tradeoff on (e.g. re-fetching config every 5-minute tick vs. caching with a TTL, and what "the channel owner changed the window mid-tick" should mean for a message ingested in that same tick).

## 2026-09-20 -- fix: live_runner's ingest and nudge/escalation ticks now fetch config fresh from the live DB, closing the "channel owner can't actually reach the running system" gap

**Finding this fixes.** This file's own earlier entry today ("the live-edit half of this row was never actually wired into the running system") traced every real caller of `get_effective_config()` and found none of them in the live pipeline -- `_poll_ingest()` and `_run_nudges_and_escalations()` both received `config` as a frozen argument, captured once in `main()` at process startup, never refreshed.

**Build.** `scripts/live_runner_p1_agent_test.py`:
- `_poll_ingest()`: dropped the `config` parameter; now calls
  `ChannelConfigStore().get_effective_config(CHANNEL_ID, db_path=db_path)`
  at the top of its existing try block, every tick (every
  `INGEST_POLL_MINUTES`, default 5) -- so a channel owner's roster,
  window, or exceptions edit (via Copilot Studio's tool or the
  Streamlit dashboard, both calling `update_channel_config()`) is
  live within one poll interval, not never.
- `_run_nudges_and_escalations()`: same treatment -- fetches config
  once per tick, before nudge and escalation both run (they must use
  the same config instance for one tick, not two independently-fetched
  ones). A config-fetch failure now logs once and skips both nudge and
  escalation for that tick, rather than raising or running one against
  a value it never received.
- `main()`: removed `"config": config` from both jobs' `kwargs` in
  `scheduler.add_job(...)`, since neither function accepts it anymore.

**Deliberately unchanged / out of scope**, per the tradeoff already
discussed with the user before writing this: `working_days` and
`daily_digest_time` still come from the frozen startup config, because
they set the APScheduler `CronTrigger`'s own fire time at job
registration -- changing them live would require rescheduling the job
itself, not just refreshing a value read inside it, and neither field
is even live-editable via `update_channel_config()` today (roster,
window, exceptions only -- see this file's own earlier "thresholds
were never exposed as live-editable" note). The race this introduces
(a config edit landing mid-tick is now visible to that same tick,
where before every tick was internally consistent against one frozen
snapshot) was flagged to the user beforehand as a real, low-stakes
behavior change, not discovered after the fact.

**Not done, on purpose.** `python3 -m py_compile` passed and every
altered call site was re-read after patching to confirm no leftover
reference to the removed `config` kwarg remains, but this has NOT yet
been proven live -- no unit test exists for this script (it requires
real Graph auth, consistent with every other live-runner-shaped script
in this repo), so the only real proof is restarting the running
process and re-running tonight's earlier live-config-write test
(`scripts/test_live_config_update_adhoc.py`) against it, this time
actually waiting out a poll tick before reverting. That restart and
re-test have not happened yet -- next step, not yet done.

## 2026-09-20 -- second channel configured for the SPN-04 multi-channel isolation test

**Build.** Added `config/channels/teams-agent-test.yaml`: a second real
Teams channel (`19:ID3C8qqqxb40IRhNJ3xvts2BWAgRac3SxYwm9XyBEGM1@thread.tacv2`,
display name "Teams-agent-test", same team/tenant as `p1-agent-test`),
deliberately configured with a different window (`09:00-13:00` vs.
`08:00-17:30`) and a different timezone (`America/New_York` vs.
`Asia/Colombo`) than the first channel, per the SPN-04 acceptance criteria
this row's own wording names ("Two channels configured with different
rosters, windows and timezones"). Roster deliberately reuses Sharon
Silva's AAD id (`a52e61e5-...`) -- confirmed with the user this is fine
for an isolation test, since the point is whether editing one channel's
config leaves the other alone, not that the person differs.
`nudge_enabled` left at its real default (`false`), unlike
`p1-agent-test`'s still-active TEMPORARY override.

Added `scripts/live_runner_teams_agent_test.py`: a copy of
`live_runner_p1_agent_test.py` with `CHANNEL_ID` swapped to the new
channel and every `_log()` line tagged `[Teams-agent-test]` so two
terminals running side by side are unambiguous at a glance -- no other
behavior change from the original, which is left untouched (already
proven live tonight, including today's frozen-config fix).

Both scripts point at the same `LIVE_DB_PATH = "data/p1_live.db"` --
channels are rows in one shared database, not separate files, which is
by design (`ChannelConfigStore.sync_to_db()` upserts every configured
channel's YAML into that one DB on every startup, regardless of which
channel a given runner process actively polls). `ScopedTeamsReader`
still scopes each process to ingesting only its own `CHANNEL_ID`, so
the two processes cannot cross-ingest each other's messages even though
they share a database file.

**Not done, on purpose.** SQLite concurrency: `get_connection()`
(`src/p1/storage/db.py`) calls `sqlite3.connect(db_path)` with no
explicit `timeout=`, so it gets Python's own 5-second default busy
timeout, no WAL mode. Two independent processes writing to the same
file should be fine for this test's write volume (one short write per
5-minute tick each), but a `sqlite3.OperationalError: database is
locked` under sustained overlap is a real, if unlikely, possibility
worth knowing about -- not fixed here, since it wasn't asked for and
isn't yet a proven problem.

Not yet run: this is config + a second runner script only. The actual
isolation test (edit one channel's roster/window live, confirm the
other channel's classify counts do not move) has not happened yet --
next step, once the user starts `live_runner_teams_agent_test.py` in a
new terminal alongside the already-running `live_runner_p1_agent_test.py`
(after that one's already-planned restart to pick up today's config-
freshness fix).

## 2026-09-20 -- fix: Graph's own nextLink can be rejected on an empty/new channel (DeltaLinkRejectedError); plus three unrelated full-suite regressions found and fixed along the way

**Finding.** `scripts/live_runner_teams_agent_test.py`'s very first ingest
tick against the brand-new Teams-agent-test channel failed with
`HTTPStatusError: Client error '400 Bad Request'` on an absolute Graph
delta URL containing `$skiptoken`. A one-off diagnostic
(`scripts/diagnose_second_channel_delta_400.py`, real Graph calls,
read-only) reproduced it directly: page 1 (relative URL) returns 200
with `"value": []` and an `@odata.nextLink`; following that exact
nextLink for page 2 returns 400 `{"error": {"code": "BadRequest",
"message": "Parameter 'DeltaToken' not supported for this request."}}`.
Confirmed via web search this is a known, open Microsoft Graph bug
(Microsoft Q&A #1184831; tracked upstream in
microsoftgraph/microsoft-graph-docs#7382), reproducible on an
empty/newly-created channel -- not a bug in this codebase's pagination
code, and not fixed by clearing the token and resyncing from scratch
(retracing the code showed that would reproduce the identical
rejection immediately, within the same sync attempt).

**Build.**
- `src/p1/adapters/teams_reader.py`: added `DeltaLinkRejectedError`,
  documented as distinct from `DeltaTokenExpiredError` (a
  previously-valid token going stale over time, HTTP 410, fixed by a
  full resync) -- this is the backend handing back a broken
  continuation link within the same sync attempt, where resyncing
  doesn't help.
- `src/p1/adapters/teams_reader_graph.py`: `list_messages()` now
  raises `DeltaLinkRejectedError` when a 400 response's body contains
  both "DeltaToken" and "not supported" -- narrowly matched on the
  actual Graph error text (not "any 400 while following a token") so
  an unrelated real 400 still surfaces normally via `raise_for_status()`.
- `src/p1/ingestion/sync.py`: `_drain_pages()` now catches it, stops
  paging for that sync attempt, and persists the last delta position
  that actually worked (`last_good_token`, possibly `None`) instead of
  the rejected link -- so the next tick starts clean from the plain
  relative URL rather than retrying a dead link forever.
- Test coverage: two new cases in `tests/unit/test_teams_reader_graph.py`
  (the exact Graph error triggers `DeltaLinkRejectedError`; an
  unrelated 400 still raises `HTTPStatusError` normally) and one in
  `tests/unit/test_ingestion_sync.py` reproducing the exact repro shape
  end-to-end (empty page + nextLink, then rejection) asserting the sync
  doesn't blow up and doesn't persist the broken link.

**Not done, on purpose.** No general fix exists for Graph's own bug --
this only makes the client side of it safe (stop, don't loop, don't
persist garbage). The moment a real message lands in a previously-empty
channel, whether page 1 then returns a working `deltaLink` or the same
broken-nextLink shape is still Graph's to decide, not something this
fix controls; if it recurs against a channel with real messages later,
that's new evidence, not a sign this fix is wrong.

---

**Along the way**: running the first full (`uv run pytest -q`) suite of
the night turned up 8 failures, none caused by the fix above (confirmed
via `git diff --stat` on exactly the 5 files that change touched) --
three separate, real, pre-existing issues, all fixed on request:

1. **`tests/unit/test_run_daily_full_flow.py` (2 failures)** -- caused
   by tonight's own second-channel work: `run_daily.run_full_flow()`
   enumerates the real `config/channels/*.yaml` directory unmocked, and
   these tests asserted an exact 3-channel set. Added a
   `TEAMS_AGENT_TEST` constant and folded it into both assertions and
   the outbound-log line counts (3->4, 6->8).

2. **`tests/unit/test_copilot_studio_api.py` (4 failures)** --
   pre-existing, from an earlier fix today to `copilot_studio_api.py`
   (making it read `P1_DB_PATH` from `.env` instead of an empty
   default). That value was a module-level constant computed once at
   import time; `.env`'s real `P1_DB_PATH=data/p1_live.db` gets loaded
   into the whole pytest process via `load_dotenv()` and never unset,
   so every test silently pointed the API at a different file than the
   one each test's own `_seed()` populated (which assumes
   `DEFAULT_DB_PATH`) -- hence the empty approvals list and the 404s.
   Fixed by replacing the frozen `DB_PATH` constant with a `_db_path()`
   function read fresh at every request/startup, and having the test's
   `_client()` helper `monkeypatch.delenv(P1_DB_PATH)` per test to
   restore `_seed()`'s own stated isolation design. Confirmed this was
   never a real-data-safety issue -- each test's `monkeypatch.chdir`
   keeps both the wrong and right paths scoped inside that test's own
   tmp directory, never the real repo's `data/p1_live.db`. Also updated
   `test_health_needs_no_api_key_and_reports_whether_one_is_configured`
   for the new `db_path` field in the health response.

3. **`tests/unit/test_no_inline_prompts.py` (1 failure)** --
   pre-existing, from tonight's earlier Ollama schema-echo fix. This
   repo's own SPN-05 lint rule forbids hand-written prompt-shaped
   string literals outside `prompts/`. Moved the two flagged literals
   into versioned prompt files, loaded via `PromptRegistry`:
   `prompts/ollama_schema_instructions/v1.md` (the wrapper instruction
   text `LLMGateway._call_ollama()` builds for any structured-output
   request against Ollama -- not tied to one capability, documented as
   such in `prompts/README.md`) and
   `prompts/ops_llm_gateway_smoke_test/v1.md` (the ad-hoc
   `scripts/test_llm_gateway_smoke.py` diagnostic's prompt/system text,
   combined into one prompt since the split made no difference to what
   that script actually checks).

Full suite after all four fixes: `469 passed, 2 skipped, 0 failed`
(same 2 pre-existing skips as before any of tonight's work).

## 2026-09-20 -- SPN-04 acceptance test, fully live-verified: "Two channels configured with different rosters, windows and timezones; changing one roster changes the non-responder set with no code change"

**What this closes.** Two real, currently-running channels
(p1-agent-test, Teams-agent-test) with genuinely different rosters*,
windows (08:00-17:30 Asia/Colombo vs. 09:00-13:00 America/New_York) and
timezones, both live and polling on their own schedule. This entry
records the two live tests that together prove the row's full claim.

(*at the time of these tests both channels' roster happened to be the
single reused id `a52e61e5-...`, a deliberate choice for the earlier
isolation test -- see this file's 2026-09-20 "second channel configured"
entry. Neither test below depends on the rosters actually differing;
both prove editing one channel's roster never reaches the other,
regardless of whether the two happen to overlap.)

**Test 1 -- config/window isolation** (`scripts/test_spn04_isolation.py`):
live-edited only Teams-agent-test's update window (09:00-13:00 ->
10:00-11:00 -> reverted) via the real `update_channel_config()` write
path, snapshotted both channels' effective config and full
message/classification state before the edit, waited for a real
scheduled poll tick on both already-running `live_runner_*.py`
processes (no restart), then re-snapshotted. Verdict: p1-agent-test's
config and all 18 messages' classifications were byte-for-byte
identical across the edit and the tick; Teams-agent-test's config
version genuinely bumped, proving the edit really took effect rather
than silently no-opping.

**Test 2 -- roster changes the non-responder set**
(`scripts/test_spn04_roster_changes_non_responders.py`): calls
`p1.participation.ledger.build_ledger()` directly -- the exact, pure
function both `run_nudge_job()` and `run_escalation_job()` use in
production to compute non-responders, pure read-only set arithmetic,
no nudge/escalation actually run, no real Teams message ever sent.
Added one clearly-synthetic, never-a-real-person member id to
p1-agent-test's live roster via `update_channel_config()`, recomputed
the ledger for 2026-09-20, and reverted. Verdict, all three true: the
synthetic member appeared as a brand-new `no_message` non-responder
immediately; the real existing roster member's own state was
unaffected; Teams-agent-test's config was completely untouched
throughout (checked via a full `model_dump()` equality, not just the
roster field).

**Together**, these two tests cover the row's full acceptance wording:
different rosters/windows/timezones can coexist on two real channels,
a live edit to either field reaches the running system within one poll
interval with zero deploy (closing this file's own earlier "the
live-edit half of this row was never actually wired into the running
system" finding), and a change to one channel's roster or window never
touches the other channel's own non-responder set or config.

**Not done, on purpose.** Both tests used a single scenario (one
synthetic addition, one window change) rather than exhaustively testing
every field `update_channel_config()` can touch (exceptions is the one
CHN-25 field not exercised by either test here) -- exceptions already
has its own direct unit test coverage elsewhere in this repo, and nothing
about the frozen-config fix or the isolation mechanism treats exceptions
differently from roster, so this wasn't considered separately
load-bearing enough to justify a third live test tonight.

## 2026-09-20 -- Dataverse-as-config-surface (CHN-25/SPN-04): confirmed real Power Platform permissions blocker, Option A put on hold

**Context.** After SPN-04's roster/window claim was proven live by two
tests (see this file's entry immediately above), the question came up of
whether Dataverse actually plays any role in that claim as literally
written in the spec ("Dataverse lets a channel owner maintain their own
roster in Teams without a deploy"). It doesn't yet -- `ChannelConfigStore`
reads/writes SQLite only, and the earlier CHN-25 decision to treat a
Dataverse table as "unnecessary" was a unilateral call that didn't follow
the literal spec wording. Re-opened it and chose the more invasive of two
designs: Option A, where Dataverse's Web API becomes the live source of
truth `ChannelConfigStore` reads/writes on every poll tick (as opposed to
Option B, a synced mirror behind SQLite).

**What was tested, live, before writing any code.** Rather than build an
integration against an architecture that might be blocked, tested whether
this account can even create a Dataverse table in this environment.
Navigated to the real "P1 Channel Intelligence" solution in the Power Apps
maker portal (`make.powerapps.com`, environment `DigitalT3 Software
Services`, solution id `de03e8c9-6eb3-f111-b374-000d3af06e75`) and opened
its `+ New` menu.

**Result: Table is greyed out.** Every other option in that menu --
Agent, App, Automation, Dashboard, Report, Security -- is clickable.
Table alone is disabled. This is on top of the page-level banner already
seen twice before ("One or more commands are unavailable due to your
current privileges for this environment"). Together these confirm what
was previously only suspected: this account lacks the Dataverse
customization privilege (something like System Customizer or System
Administrator) needed to create a table in this environment at all --
this is a real, external, admin-side permissions wall, not a code
problem, and not something workable around from the client side.

**Decision: hold Option A, request admin access.** No `ChannelConfigStore`
migration code will be written against Dataverse until this is resolved --
building a Web API integration against a table that can't yet exist would
be pure waste, and doing so under a differently-privileged account later
would mean redoing the design work anyway. The concrete ask for whoever
administers this Power Platform tenant: grant the signed-in account
(shown in the portal as "SS") the System Customizer role (or equivalent)
scoped to the `DigitalT3 Software Services` environment, specifically so
it can create a new Dataverse table inside the existing "P1 Channel
Intelligence" solution. Once granted, the next step is designing the
actual table schema (open question: how to represent `roster`, currently
a flat list, in Dataverse's relational model -- a related child table,
most likely, rather than a single-column list) before touching any
`ChannelConfigStore` code, and re-running `test_spn04_isolation.py` /
`test_spn04_roster_changes_non_responders.py` against the Dataverse-backed
implementation without disrupting the two currently-running live channels.

**Not blocked by this.** SPN-04's own acceptance wording (two channels,
different rosters/windows/timezones, changing one roster changes only
that channel's non-responder set with no code change) is already fully
proven against the current SQLite-backed `ChannelConfigStore` -- see the
entry directly above. This blocker is specific to the separate,
higher-bar claim that a channel owner can maintain their roster from
inside Teams/Dataverse without any deploy; that claim stays open until
the admin-access ask above is resolved.

## 2026-09-20 -- CHN-02's "Dataverse surface" wording re-read carefully; switched from Option A back to Option B

**What triggered this.** Re-examined CHN-02's exact spec text, which was
being paraphrased loosely until now: implementation column reads "Python
(YAML schema) + Dataverse surface" -- a compound, additive pairing, not
two alternatives. "Python (YAML schema)" names the config's schema,
validation and versioning layer -- exactly what's already built
(`ChannelConfig` Pydantic model, versioned, persisted via YAML + mirrored
into SQLite through `ChannelConfigStore`). "Dataverse surface" is the
added piece, and "surface" is Microsoft's own Power Platform term for an
interaction/UI layer (a "Teams surface", an "Outlook surface"), not a
storage-engine or backend-of-record term. The row's own rationale --
"Dataverse lets a channel owner maintain their own roster in Teams
without a deploy" -- is a claim about who edits what, from where, not a
claim that the live poll loop must read Dataverse's Web API on every
tick.

**Decision.** Reading it literally, this row asks for Option B, not
Option A: the Python/YAML-schema config engine stays authoritative for
the running system (already built, already proven live via
`test_spn04_isolation.py` and
`test_spn04_roster_changes_non_responders.py`); Dataverse's job is
specifically to be the editable surface a channel owner opens inside
Teams. Something still needs to carry an edit made on that surface into
the operational store, but introducing a live network dependency into
every 5-minute poll tick (what Option A would have required) goes further
than the spec text actually asks for. Reversing yesterday's Option A
choice; Option B is now the design target once Dataverse table creation
is unblocked.

**Still blocked, unchanged.** This doesn't touch the permissions wall
from the entry above -- table creation for this account in this
environment is still disabled (confirmed live: "Table" greyed out in the
P1 Channel Intelligence solution's `+ New` menu). The admin-access ask
stands as written: grant the signed-in account ("SS") System Customizer
(or equivalent) on the `DigitalT3 Software Services` environment. No
Dataverse code -- for either option -- gets written until that's granted.
Once it is, the concrete shape of Option B to design: a Dataverse table
mirroring the same config fields (roster, window, timezone, etc.), a
sync direction from that table into `ChannelConfigStore`'s SQLite/YAML
store (poll-interval or event-driven, still to be decided), and the same
live isolation/roster tests re-run against the new write path without
disrupting the two channels already running.

## 2026-09-20 -- Correction: a Dataverse table was never actually required for CHN-02's "surface" outcome; reconciling with the 2026-09-20 CHN-25 finding this session missed

**What went wrong.** Earlier today, pushback on the original CHN-25
decision ("Dataverse table found unnecessary") led to exploring Option A
(Dataverse as live source of truth), then Option B (Dataverse as a
synced mirror) -- both of which assume a new Dataverse table has to get
built once the permissions wall clears. That exploration never
re-checked this repo's own already-recorded finding, earlier the same
day, that a literal Dataverse table was investigated and explicitly
rejected -- see this file's "CHN-25's two 'not done, on purpose' items
closed" entry. That earlier entry's reasoning still holds and was
missed: building a separate Dataverse table would create a second copy
of the exact same roster/window/exceptions data already held in
`channel_config` (SQLite), which the row's own "reconciled, not
duplicated" design rule rules out, and would regress the
single-write-path guarantee `ChannelConfigStore.update_channel_config()`
exists to provide (every write auditable through the one path,
GC8-proven). Option A and Option B were both solving a problem that
was already correctly solved a different way.

**What actually already satisfies the row's outcome.** CHN-02's
rationale is "the channel owner who knows the roster needs to maintain
it without a deploy." That's already live, wired, and does not touch
Dataverse at all: Copilot Studio's "Update Channel Config" Tool (one of
the connector's 5 Tools, already attached to the "P1 Channel
Intelligence" agent per the 2026-09-18 solution-aware entry) calls
`copilot_studio_api.py`'s `/update_channel_config` endpoint, which calls
`copilot_studio_connector.py::handle_update_channel_config()`, which
calls `ChannelConfigStore.update_channel_config()` directly --
`src/p1/adapters/copilot_studio_connector.py` lines ~116-141, confirmed
by direct re-read this entry. A channel owner typing into the agent in
Teams ("update my roster to add X") reaches the exact same write path
`app/approval_dashboard.py`'s Streamlit form already reaches live today
-- zero Dataverse tables, zero sync job, zero duplicated data.

**Decision, corrected again.** No Dataverse table gets built for CHN-02,
full stop -- not Option A, not Option B. The 2026-09-20 CHN-25 finding
was right the first time. What's actually still open is getting that
already-built path reachable from a real Teams conversation: the
Copilot Studio tenant is out of credits, and the agent has never been
published to a Microsoft Teams channel (both already logged, both
unrelated to the Dataverse permissions wall from earlier today). A
lighter fallback that sidesteps Copilot Studio entirely also exists on
paper and was not tried: a Power Apps Canvas app -- "App" creation is
NOT blocked for this account, unlike "Table" -- bound directly to the
same "P1 Channel Approvals" custom connector, embedded as a Teams tab.
Neither path needs a Dataverse table or the System Customizer role this
file's admin-access ask was written for.

**Not done, on purpose.** The admin-access ask from earlier today is
left standing rather than withdrawn, since Dataverse customization
privilege may still matter for something else in this programme later
-- but it is no longer blocking CHN-02, and framing it as blocking
CHN-02 (as this file's two most recent prior entries did) was the
mistake this entry corrects.

## 2026-09-20 -- CHN-02's Dataverse question, closed: no table built, decision confirmed by the user

**Decision.** No Dataverse table gets built for CHN-02. Confirmed
explicitly by the user after the correction above (Dataverse was never
architecturally required for P1's own outcome; the "P1 C1 / P2 P6 /
P3 O4" grouping in the master plan's Appendix D is a shared tool-choice
convention across three structurally similar config capabilities, not a
claim that P2/P3 read P1's own roster data).

**Precise statement of what's actually true today, so this doesn't get
overstated on re-read later.** "The channel owner maintains their roster
without a deploy" is real and live-proven -- through
`app/approval_dashboard.py` (Streamlit), which calls
`ChannelConfigStore.update_channel_config()` directly, no code change or
restart required for an edit to take effect. It is NOT yet proven
through an actual Teams conversation. Copilot Studio's "Update Channel
Config" Tool wraps the identical function
(`copilot_studio_connector.py::handle_update_channel_config()`,
equivalence-proven against the Streamlit path by
`tests/unit/test_copilot_studio_connector.py`) and two of its sibling
operations (health, list_pending_approvals) were confirmed live through
the Power Platform Test panel on 2026-09-18 -- but
`update_channel_config` itself was not individually re-verified there
(see that day's entry, "not done, on purpose"), and no real Teams
conversation with the published agent has ever successfully invoked any
tool, because the one live test attempt hit `EnforcementUsageCredits`
before reaching that point. So: the mechanism is code-complete and does
not need Dataverse: the two things actually gating the "edit it from
inside Teams" experience are the Copilot Studio tenant being out of
credits and the agent never having been published to a Microsoft Teams
channel -- both already logged, neither related to Dataverse or the
permissions wall from earlier today.

**Status of the admin-access ask.** Left standing, not withdrawn, per
the earlier correction entry -- Dataverse customization privilege may
still matter later (P2/P3's own analogous config capabilities, per
Appendix D's grouping, once those agents actually get built -- CHN-33's
spine extraction is still outstanding and unstarted). Not urgent, not
blocking anything today.

**This closes the Dataverse thread for CHN-02.** Three prior entries
today (Option A, the "surface" reading/Option B switch, and the
correction back to "no table needed") are superseded by this one as the
final state; they're left in place rather than edited, since each one
documents real reasoning that was actually acted on at the time -- this
entry is the one that reflects where things actually landed.


## 2026-09-20 -- Blocker 2 resolved live: "P1 Channel Intelligence" published with a Teams + Microsoft 365 channel

**What was done, live, in the real Copilot Studio environment, with the user's
explicit go-ahead ("then lets try to do blocker 2").** Clicked Publish on the
"P1 Channel Intelligence" agent (Build view, no channel attached yet) --
confirmed via the Publish dialog's own state: "Last published Sep 20, 2026,
8:09 PM" with a green check, immediately after the first publish resolved.
Then Add a channel -> Teams + Microsoft 365 -> Availability kept at its
default, "Microsoft 365 Copilot and Microsoft Teams" (the user was asked
first, since the dialog itself states this setting can't be changed after
publishing, and chose to keep the default rather than narrow it to Teams
only) -> Add channel -> Publish agent again. Second publish took noticeably
longer than the channel-less one (~30s+) but resolved with an explicit
in-app confirmation: "Your agent published successfully -- Your agent is now
available on the configured channels," listing "Teams + Microsoft 365."
Re-verified a third time afterward via the Publish dialog's own state:
"Last published Sep 20, 2026, 8:15 PM."

**Direct Teams install link, captured for real (not guessed).** Opened Share
-> "Copy link (Microsoft Teams)." The app writes this to the OS clipboard
with no on-screen text, so it was captured by hooking
`navigator.clipboard.writeText` in the page's own JS context immediately
before clicking copy:
`https://teams.microsoft.com/l/app/?titleId=T_7426ed15-b8c6-44c5-83bd-701c1d4034e6`.
This is the real, live titleId for this agent's Teams app registration --
not a placeholder. The Share dialog's own "Share" action (which grants
individuals/org access) was deliberately NOT clicked -- only "Copy link" was
used, so no new people or org-wide access were granted this session. Currently
only Sharon Silva (SS, owner) can use the agent; "Everyone in your
organization" still shows "No permissions, unless specified."

**What this actually resolves.** Blocker 2 (agent never published to a Teams
channel) is closed: the agent is published, has a live Teams + Microsoft 365
channel, and has a real install link. Blocker 1 (Copilot Studio tenant out of
Copilot Credits) is UNCHANGED and still open -- publishing and adding a
channel are build/config actions and did not touch the credits blocker.
Installing the link and actually chatting with the agent in Teams will still
hit `EnforcementUsageCredits` until an admin adds credits or capacity in the
Power Platform admin center (confirmed out of reach for this account -- see
the Sep 20 entry on the Teams-admin and Power-Platform-admin-center access
denials). The link itself was not yet installed/tested end-to-end in a real
Teams client this session.

**Not done, on purpose.** Did not click "Share" to grant the user's own
account or the organization access, since that is a standing-permission /
account-setting change outside what was asked ("try to do blocker 2" was
read as publish + channel + link, not as granting broad access). If the user
wants specific people able to use the agent, that is a separate, explicit
ask.


## 2026-09-20 -- Full day-by-day delivery plan re-verified against real evidence (all 10 rows of the WBS table)

**What triggered this.** The user pasted the master plan's whole
day-by-day WBS table (Focus / What gets built / End-of-day definition of
done, spine foundations through Gate G1) and asked to check through all
of it -- not trust the table's own wording, verify each "definition of
done" cell against real code, real tests, and real logged runs.

**Method.** `pytest` cannot run from this sandboxed device_bash shell --
confirmed again this session: `.venv`'s python symlinks point at
`/opt/homebrew/...` (the real Mac), not reachable from this Linux VM,
and `.venv/lib/python3.10/site-packages` itself is empty (uv installed
via hardlinks into a Mac-side cache, not copied into the venv folder).
So verification here means: read the actual test files' own docstrings
and assertions, read `eval/results.jsonl`'s real recorded run, read
`README.md`'s own status claims, and cross-check `DECISION_LOG.md`'s
dated entries -- not re-running anything myself.

**Result, row by row (WBS row -> verdict -> evidence):**

1. Spine foundations + G0b -- CONFIRMED. `src/p1/llm/gateway.py` wraps
   every model call through one path with `tenacity.Retrying`;
   `structured.py`'s `generate_structured()` docstring: "validate-and-
   retry," logs `structured_output_retry attempt=%d`. CHN-01: not just
   documented-with-fallback -- actually live. README: "as of 2026-09-19
   GraphTeamsReader has read and persisted a real message from a real
   Teams channel (p1-agent-test) against the real DigitalT3 tenant."
   Stronger than the row's own bar.

2. Config/Graph adapter/scope gate -- CONFIRMED. README states it
   directly: "ScopedTeamsReader ... enforces the channel allowlist at
   the adapter boundary -- a chat or a non-allowlisted channel is
   refused before any capability code ever sees it, and every refusal
   is logged to audit." Live eval proof: GC5-gamma-channel-refused,
   GC5-one-to-one-chat-refused, GC5-group-chat-refused all `passed:
   true` in `eval/results.jsonl`'s latest run. A real gap was found and
   fixed here too (`list_replies()`/`get_permalink()` had no
   independent allowlist check) -- see the 2026-09-20 CHN-03/CHN-05
   entry above.

3. Ingestion hardening + seed data -- CONFIRMED for the delta-run half:
   GC10's six metrics (message-count, edit-posted-at-preserved, edit-
   content-updated, delete-handled, bot-flags-correct, system-flags-
   correct) all `passed: true`. Fixture byte-identical claim is a
   documented design property (`scripts/generate_seed_fixtures.py`:
   "Deterministic (fixed random seed) -- re-running this always
   produces byte-identical output"; `scripts/seed.py`: "deterministic
   (seed=42)") but NOT independently re-verified this session (no test
   found that regenerates and diffs) -- weaker evidence than the rest
   of this row.

4. Thin end-to-end slice G0 -- CONFIRMED, verbatim.
   `tests/unit/test_participation_against_fixtures.py` has
   `test_reaction_only_chatter_only_and_on_leave_members_each_land_correctly`
   -- the exact three states the row names.

5. Grounding + first numbers (GC1/2/5/10) -- CONFIRMED. GC1-precision
   (1.0 vs target 0.8), GC2's three exact-match non-responder sets
   (proj-alpha/gamma/beta), GC5-out-of-scope-message-count (0) all
   `passed: true`.

6. Daily summary (GC3/4/9) -- CONFIRMED. GC3-citation-rate 0.95/0.95,
   GC4-fabrication-count 0/0, GC9-fact-divergence-count 0/0, all
   passed. `test_daily_summary.py` has its own "honest empty summary"
   section by name.

7. Approval spine + publishing -- CONFIRMED, verbatim.
   `tests/unit/test_daily_job.py`'s own docstring: "CHN-17's own
   acceptance test: 'A clock-override run at three different channel-
   local times produces three correctly timed digests and no
   duplicates.'" GC6-suppressed-attempts (sent=1, refused=2) and GC8's
   six pending/rejected-proposal-refused metrics all passed.

8. Weekly roll-up + nudges (GC11) -- CONFIRMED. GC11-arithmetic-
   mismatch-count (0/0) and GC11-non-working-day-scenario-check both
   passed. GC7-nudge-cap-holds (1/1) and GC7-excluded-never-nudged (0/0
for carol) cover the cap/never-nudged half live.

9. Escalation + config proof (GC7/8/12) -- CONFIRMED, verbatim.
   `tests/unit/test_escalation_job.py`'s own docstring: "CHN-23's own
   acceptance test: 'With the threshold at three days, exactly...'"
   GC12-set-moves-with-config (`measured: true`) plus config A/B
   producing different non-responder sets on identical data -- this is
   also independently confirmed live the same day (2026-09-20)  via
   the separate SPN-04 acceptance-test entry above.

10. Harden/measure/demo G1 -- PARTIALLY CONFIRMED. `eval/results.jsonl`'s
    latest run (2026-09-19T09:13 UTC): `all_passed: true` across all 34
    metrics, all 12 golden cases (GC1-GC12) represented -- committed,
    real. A real finding-and-fix during hardening is documented (CHN-05's
    ingestion orchestrator had no member-sync capability; closed, see
    README's CHN-31 bullet and the matching DECISION_LOG entry). README
    confirms clean-clone-no-Graph-credentials directly: "it needs no
    Graph/tenant credential at all, since TEAMS_READER_MODE and
    TEAMS_PUBLISHER_MODE both default to mock ... a fresh clean-clone run
    reports awaiting_approval for both channels -- that is the correct,
    honest first result." BUT two sub-items are NOT done: (a) the actual
    recording -- `scripts/run_walkthrough.py`'s own docstring says "Run
    this once, ON CAMERA" -- the backing script and its test
    (`test_run_walkthrough.py`) exist and pass, but no video/cast file is
    committed anywhere in the repo, and nothing in DECISION_LOG.md says
    the recording itself has been made; (b) spine extraction (CHN-33) --
    confirmed still outstanding and unstarted, per this file's own
    2026-09-20 closing entry above ("CHN-33's spine extraction is still
    outstanding and unstarted"), and no `spine` package/directory exists
    anywhere in the repo.

**Bottom line.** 8 of 10 rows fully confirmed with direct evidence (test
docstrings quoting the row's own acceptance language, or passing
eval/results.jsonl metrics, or explicit README claims). Row 3's fixture-
determinism half is asserted in code comments but not independently
re-verified. Row 10 (Gate G1) has its hardest, most code-verifiable
parts done (eval harness, documented fix, clean-clone-no-credentials)
but its two human-action deliverables -- the actual recording and the
spine package extraction -- are not done.


## 2026-09-20 -- CHN-32's open question, resolved live: [source](url) markdown links DO render as clickable hyperlinks in real Teams, and DO navigate correctly

**What was open.** The 2026-09-19 SPN-08 entry left this explicitly
unconfirmed: whether digest citation links posted through the real
Power Automate flow render as clickable hyperlinks inside Teams itself,
or as literal bracket/parenthesis text -- flagged as needing "a direct
check: click a [source](...) link inside the real Teams channel and
confirm it navigates to the real message."

**What was checked, live, in the real Teams web client (teams.cloud.microsoft),
signed in as Sharon Silva.** Opened the real p1-agent-test channel and
found a real, already-posted digest from the live pipeline: "# p1-agent-test
-- Daily Summary (2026-09-20)", posted by Workflows at 5:37 PM, with
multiple "What moved" bullets each ending in a (source) citation.
These render as ordinary blue, underlined hyperlinks -- not raw
markdown syntax. Clicked one ("Finished wiring the daily digest
pipeline end-to-end for p1-agent-test (source)"): it navigated into a
thread view and landed precisely on the real 9:55 AM source message
with that exact text, highlighted -- confirmed by screenshot, not
assumed from the click succeeding without an error.

**Resolution.** SPN-08's open question is closed: yes, on both halves
-- the links render as genuinely clickable, and clicking one navigates
to the correct source message. This directly de-risks CHN-32's own
"most convincing ten seconds" beat (a permalink clicked live) for a
supplementary p1-agent-test recording: the mechanism is proven to
work end-to-end against the real tenant today, not just designed to.

**Still true, unchanged.** p1-agent-test has only one real roster
member (Sharon Silva) and none of the planted-difficulty data the mock
fixtures carry, so it still cannot carry CHN-32's full 8-beat narrative
on its own -- this resolves the live-permalink risk specifically, not
the separate dataset-richness gap. The two-clip plan (mock-channel
walkthrough for the full narrative + a short live p1-agent-test clip
for the permalink beat) is unblocked by this finding, not replaced by
it.

## 2026-09-20 -- scripts/run_walkthrough.py actually executed for real, end to end, all 8 beats -- first time ever outside its unit test

**What was actually run, for real, per the user's explicit "can we do this first" request.** Built a
throwaway lightweight venv (system python3.10 + only the packages the script's import chain needs --
not the project's own broken `.venv`, which is unusable from this sandbox because it symlinks to a
macOS-only interpreter). Ran `run_walkthrough.run_walkthrough()` directly against a fresh, disposable
db (`data/p1_scripted_verify.db`, deleted afterward) -- not the unit test's throwaway `tmp_path`, and
not the shared demo `data/p1.db`.

**Beats 1-2, first pass: real LLM gateway, real fixtures, no overrides at all.**
Deleted `data/p1.db` for a genuinely clean state first (an earlier attempt against a stale db printed a
misleading "0 message(s)" -- traced to leftover state from an incomplete prior cleanup, not a bug; the
`_drain_pages()` counting logic itself is correct). The clean run printed real, first-ever-observed
terminal output: `ingested 19:proj-alpha@thread.tacv2: 90 message(s)`, `ingested
19:proj-beta@thread.tacv2: 103 message(s)`, and both the ingest-side and chat-side refusals firing
exactly as documented. This confirms beats 1-2 work against the real production code paths with no
substitutions at all.

**Beats 3-8: real production code, LLM calls only substituted.** This sandboxed Linux VM cannot reach
this project's actually-configured LLM provider (`.env` has `LLM_PROVIDER=ollama`, which normally runs
on the user's own Mac and isn't reachable from here -- confirmed via direct `.env` grep, correcting an
earlier wrong guess on my part that this was the separately-documented Bedrock IAM issue; it isn't --
that issue only matters if `LLM_PROVIDER=bedrock`, which it isn't here). Since a real model call isn't
possible from this sandbox, ran the identical entry point with the project's own `ScriptedGateway` (the
exact stand-in `tests/unit/test_run_walkthrough.py` already uses for its passing unit test) passed via
`run_walkthrough(gateway=...)` -- everything else (rule engine, classifier wiring, ledger, digest
generation, weekly rollup, nudge job, approval/rejection, escalation bundle assembly) is the real,
unmodified production code. Result: all 8 beats produced genuine, real terminal output for the first
time ever outside a unit test -- rule decision on message `proj-alpha-0033` (`outside_update_window`),
classifier decision on `proj-alpha-0036` (`update`, confidence 0.9), the ledger's three real states,
a real rendered daily summary with a well-formed permalink, a real rendered weekly roll-up with real
percentage deltas, a real nudge run showing awaiting_approval -> one rejected by hand -> one approved
by hand -> that approval auto-sending on the rerun -> a second consecutive miss auto-approving on day
2, and a real escalation evidence bundle with real bundled text. `run_walkthrough()` returned normally,
no exception, end to end.

**One genuine new finding, not previously known: beat 7 will try a real network call if run with the
project's actual `.env` as-is.** `.env` has `TEAMS_PUBLISHER_MODE=power_automate` (the real, live
publisher), not mock. First attempt (no override) hit `PowerAutomatePublishError: ... ProxyError: 403
Forbidden` -- this sandbox's network egress allowlist blocks that specific Power Automate host, so this
is an environment limitation on my end here, not a code defect. Re-ran with `TEAMS_PUBLISHER_MODE=mock`
forced via env var (the same one-line-swap the adapter factory is designed for) and beats 7-8 completed
identically in logic, just logging instead of sending. Separately confirmed the beta-channel roster
(`amara.okonkwo`, `diego.martinez`, etc.) are fixture/demo identities, not real Azure AD member IDs, so
even on the user's own Mac with real network access this call would not reach a real person -- but
nobody has actually run beat 7 against the real Power Automate flow to confirm what it does with a
fixture ID, so that specific claim (that it's harmless on a real run) is inference, not something
observed.

**What this settles for CHN-32.** The script itself, watched running for real: works, beats 1-8, no
code defects found. Two things worth knowing before the actual recording take, both new from this run:
(1) `data/p1.db` needs a fresh delete immediately before the real take -- confirmed firsthand that a
stale db produces a misleading zero-count line; (2) if recording against the real `.env` as committed,
beat 7 onward will attempt a real Power Automate call and, on this sandbox, that call is blocked by
network egress -- unconfirmed whether it succeeds, fails cleanly, or does something unexpected on the
user's own Mac where the network path is different. Worth a quick real check on the user's own machine
before the take, not assumed either way.

## 2026-09-20 -- scripts/run_walkthrough.py rebuilt into an 11-beat full tour covering all 9 W1/W2 DoD lines, both channels -- two real findings surfaced along the way

**Why.** The user asked for every demo scenario built so far to actually run, live, on camera, covering
both `proj-alpha` and `proj-beta`, mapped exactly to the 9 "end-of-day definition of done" lines in
`docs/MASTER_IMPLEMENTATION_PLAN.md`'s W1 D1-W2 D9 table (which together cover GC1-GC12). The original
8-beat script (see the entry directly above this one) proved beats 1-8 work, but a gap analysis against
those 9 lines found 4 missing live moments -- the LLM retry demo (W1 D1), delta-sync + fixture
reproducibility (W1 D3), per-channel-local-time scheduled publishing via the real
`run_daily_digest_job()` (the original script bypassed it entirely, calling
`generate_and_persist_daily_summary` directly), and the eval harness's own numbers on screen (W1 D5) --
plus every beat only ever showed one channel at a time instead of both. User picked "Full build" to
close every gap rather than ship a partial tour.

**What changed.** `scripts/run_walkthrough.py` went from 8 beats to 11, every one of them calling real,
unmodified production code (no second demo-only path anywhere):
1. LLM retry -- a local throwaway schema/gateway proves `generate_structured()`'s own retry loop.
2. Ingest + refuse (unchanged logic, renumbered).
3. Chat refused at the boundary (unchanged logic, renumbered).
4. NEW -- two consecutive delta syncs (0 new messages second time), `diff-edit-01`'s `posted_at`
   preserved across its edit, and a live fixture-regeneration diff (see finding #1 below).
5. Rule + classifier decision, now on BOTH channels.
6. Ledger, now on BOTH channels.
7. NEW -- `run_daily_digest_job()` (the real scheduled-publish entry point, previously unused by this
   script) run 3x per channel: awaiting_approval -> still pending -> approved by hand -> published
   exactly once, `write_log` proving the two earlier attempts were refused, not silently dropped. Both
   channels' own configured local time/timezone.
8. Weekly roll-up, now on BOTH channels.
9. Nudges -- proj-beta's original approve/reject/auto-approve flow, PLUS a new proj-alpha section (see
   below).
10. Escalation evidence bundle, now on BOTH channels.
11. NEW -- `scripts/run_eval.py`'s real harness run inline, printing all 34 golden-case metrics
    (GC1-GC12), ending in `ALL PASS`.

**proj-alpha's new nudge/escalation story: fatima.hassan.** Found by directly querying
`build_ledger()` day-by-day across the whole fixture window (not assumed): fatima is
`DIFF-CHATTER-01` -- she posts a message almost every day, but every organic message is chatter
("Thanks!", "Sounds good."), never an update, so the ledger counts her like genuine silence. Her real
silence run is 2025-06-09 through 2025-06-12 (Mon-Thu, 4 consecutive working days -- she genuinely
contributes real updates on 06-05 and 06-06, which is what makes 06-09 a clean streak start). Since
proj-alpha's committed `nudge_enabled` is `false` (its real, intentional value), the script turns it on
for this run only via `ChannelConfig.model_copy(update={"nudge_enabled": True})` -- the same
in-memory-only override pattern this project already uses for clock overrides -- never touching
`config/channels/proj-alpha.yaml`. The escalation evidence bundle that comes out the other end is a
genuinely nice demo beat: it names 4 real message IDs she posted on the third day and says outright
"posted, but nothing counted as an update" -- proving the escalation path is driven by the ledger's
counted updates, not by whether someone was around.

**Finding #1 (real, in the codebase, not fixed here): the seed fixture generator has silently drifted
from the committed fixtures since CHN-28.** Beat 4 regenerates `seed/fixtures/*` into a disposable
temp dir and diffs it against the committed files -- something nobody had actually done end-to-end
before. Result: `channels.json` and `members.json` are byte-identical; `messages.json` and
`labels.csv` are each missing exactly 3 entries relative to the regenerated output --
`DIFF-SHORT-01`, `DIFF-THREADOFF-01`, `DIFF-ROSTER-01`. Root-caused via `git log`/`git show`: commit
`3920f95` ("CHN-28: fix the harness's real weakest spot -- half of CHN-08's rules had zero coverage",
2026-09-18) added these 3 rows straight into the committed JSON/CSV by hand to close a real rule-
coverage gap, without also updating `scripts/generate_seed_fixtures.py` to produce them. The
generator's own docstring claims "deterministic... re-running this always produces the same output"
and calls itself the fixture "single source of truth" -- both true for everything the generator itself
plants, but that invariant has been silently false for these 3 rows since CHN-28. Not fixed in this
session (would mean editing the generator's random-draw sequencing without a chance to re-verify
against the other 20 planted categories under time pressure before the recording); beat 4 now reports
the true diff honestly instead of claiming full byte-identical reproduction, explicitly calling out
that this specific 3-row gap is the one known, tested, intentional exception. Worth a real ticket:
either fold DIFF-SHORT-01/THREADOFF-01/ROSTER-01 into the generator properly, or update its docstring
to stop claiming full reproduction.

**Finding #2 (real latent bug, in `src/p1/escalations/escalation_job.py`, not fixed here): the streak
walker has no lower bound at a channel's actual data start date.** First attempt at proj-alpha's
escalation picked 2025-06-03/04/05 as fatima's streak (a reasonable-looking guess from her longest
silence run spanning the whole window) and got a real, reproducible surprise: the escalation's own
idempotency key came back keyed on `streak_start_date=2025-02-05` -- four months before the fixture
window even starts. Root cause: 2025-06-02 is the very first day either channel has any data at all,
and the walker's job is to walk backward from the escalation day until it hits a day the person
actually contributed (per its own docstring, point 1) -- but `build_ledger()` has no concept of "before
the channel existed," so for a member whose silence appears to start on the fixture's first day, the
walker just keeps finding `no_message` indefinitely into a data desert with nothing to make it stop,
until some incidental boundary condition (not fully traced) finally halts it on a date that means
nothing. This is a real gap worth a ticket in a system whose channels have genuine multi-year history,
even though it can never surface in THIS fixture (every channel's data starts 2025-06-02). Worked
around for the demo, not patched in code: picked 2025-06-09 instead, immediately preceded by a real
contribution on 06-06, so the walker correctly stops there and reports a sane `streak_start_date`.
Confirmed with a direct script (`build_ledger()` called for every day 06-02 through 06-16) before
committing to the date.

**Also caught and fixed before it became a real problem: I nearly overwrote this repo's actual
committed `seed/fixtures/messages.json` and `labels.csv` on disk.** While investigating finding #1
above, ran `generate_seed_fixtures.py` once with its cwd pointed at this repo's root instead of a
scratch temp dir (a plain mistake, not something the script itself did) -- it writes to the relative
path `seed/fixtures/` from wherever it's invoked, so this genuinely overwrote the real working-tree
files in place. Caught it immediately via `git status`/`git diff`, and restored both files with `git
checkout -- seed/fixtures/messages.json seed/fixtures/labels.csv` before doing anything else. Verified
clean afterward (`git status --short seed/fixtures/` empty). No commit was ever made with the bad
content, and the real fixtures are confirmed back to their exact committed state.

**Verification.** Ran the real, final `scripts/run_walkthrough.py` (imported by its real module name,
not a test copy) end to end in this sandbox's throwaway venv, `ScriptedGateway` standing in for the
unreachable local Ollama and `TEAMS_PUBLISHER_MODE=mock` standing in for the unreachable Power
Automate host -- exit 0, all 11 beats printed real output, all 34 eval-harness metrics PASS, zero
FAILs. `git status` confirmed no unintended files changed in the real repo afterward (only the
intended `scripts/run_walkthrough.py` replacement). All scratch test files and throwaway `data/*.db`
files created during this investigation were deleted afterward.

**What's still true from the entry above this one, unchanged:** `data/p1.db` should still get a fresh
delete immediately before the actual recording take (it does not currently exist on disk, so this is
already satisfied as of right now, but will exist again the moment anyone runs the script against the
real `.env`); and beat 7 onward will still attempt a real Power Automate call if run against the
committed `.env` (`TEAMS_PUBLISHER_MODE=power_automate`) -- unconfirmed on the user's own Mac, where
the network path differs from this sandbox's blocked egress.

## 2026-09-21 -- CHN-33: spine package extracted and committed; two "Shared spine" items deferred to G2, on purpose

Executed CHN-33's own WBS row literally: "Extract the reusable spine (gateway, schema layer,
proposals, write guard, grounding kernel, harness, scheduler, prompt registry, config pattern) into
an installable internal package with its own tests." All nine named components now live at
`packages/spine/` as a `uv` workspace member (`spine` on PyPI-style import), wired into root
`pyproject.toml` via `[tool.uv.workspace]`/`[tool.uv.sources]`. Two of the nine (scheduler, config
pattern) needed genuine generalization rather than a file copy, since both were hard-coupled to P1's
concrete `ChannelConfig` type: `spine.scheduling.scheduler` now takes a caller-supplied `to_spec()`/
`job_kwargs()` pair instead of assuming P1's field names, and `spine.config.store.ConfigStore[T]` is a
generic committed-YAML-plus-live-DB-override pattern using JSON-blob storage in two new tables
(`spine_config_store`/`spine_config_audit`), deliberately NOT a rewrite of P1's own live
`ChannelConfigStore` (see the 2026-09-20 CHN-25 entries above -- that schema stays exactly as-is,
still the only thing either running `live_runner` process talks to). The other seven moved as literal
copies with internal `p1.xxx` imports rewritten to `spine.xxx`: LLM gateway, structured-output/retry,
the SQLite migration engine, proposal record, write guard, grounding kernel, prompt registry, and the
eval harness framework. Also moved, beyond CHN-33's literal list but named by the plan's own doctrine
line ("P1 also builds two adapters P2 inherits outright"): the `TeamsReader`/`TeamsPublisher` ABC
interfaces only, not their concrete mock/Graph/PowerAutomate implementations, which stay in P1.

Real proof, not a claim: a fresh venv, `pip install -e .`, a genuine 25-test pytest suite written
against deliberately alien toy configs (`ProjectConfig`, `MorningBriefConfig` -- names with nothing to
do with P1) to prove actual reusability rather than replaying P1's own shapes, all 25 passing; then a
real wheel built and installed into a second, unrelated `/tmp/fresh_project` directory with a
standalone smoke test exercising `ConfigStore`, the scheduler, `ProposalStore`, and the grounding
kernel -- all passed. This directly satisfies CHN-33's acceptance test ("Spine package installs into a
fresh project and its tests pass independently of P1"). One real bug found and fixed in the process:
`ConfigStore.get_effective()` raised a raw `sqlite3.OperationalError` instead of `ConfigNotFoundError`
when called before any `sync_to_db()` had run for that `db_path` -- fixed by having it call
`self.ensure_schema()` first; caught by the test suite itself, not by inspection.

P1 confirmed untouched: the only changes committed to the real repo are the 33 new files under
`packages/spine/` and one additive edit to root `pyproject.toml` (the workspace member, the sources
entry, and `spine` added to the dependency list with a comment noting nothing imports it yet). No file
under `src/p1/` or `scripts/` was touched. Both `live_runner_p1_agent_test.py` and
`live_runner_teams_agent_test.py` are running the exact same code they were before this task started.

**Gap found and deliberately deferred, not missed.** The master plan's own "Shared spine" summary line
(section 13, "How this plan is shaped") names ten components, not nine, and its wording differs from
CHN-33's WBS row: it says "adapter framework" and "approval surface" where CHN-33's row instead says
"scheduler" and "config pattern." Both of the ten-item list's two extra names are real, existing P1
code that is NOT in `packages/spine/`: `p1.adapters.factory` (`get_teams_reader()`/
`get_teams_publisher()` -- env-var-driven mock/real selection, plus always wrapping the reader in
`ScopedTeamsReader`) and `p1.approval.service` (`list_pending_approvals()`/`approve_and_send()`/
`reject()` -- the one seam CHN-25's own acceptance test rests on, that both the Copilot Studio
connector and `scripts/approve_cli.py`'s Streamlit/CLI fallback call through so neither surface can
produce a different audit outcome than the other; see the 2026-09-18 CHN-25 entry on this same seam).
Deliberately not generalized this session: `approve_and_send()`'s `_resend_plan()` is keyed to P1's
exact three proposal types (`daily_digest_publish`/`nudge`/`escalation`) and does a
`ChannelConfigStore.get_effective_config(...).channel_owner_id` lookup for escalation's target --
genuinely P1-specific business logic, not a thin coupling like the scheduler's field names were. Given
the user's own read of the plan's phrasing -- "Extracted into an installable internal package at gate
G1 and hardened at G2" -- the decision made here was to treat CHN-33 as satisfied against its own
literal WBS text now, and treat these two components as G2 hardening work, not a gap to close before
moving to P2. Recorded here so it is not silently lost: if G1 is scored strictly against the ten-item
"Shared spine" line rather than CHN-33's own nine-item WBS row, this is a real, known, two-item
shortfall against that broader list, with a stated reason and a stated remediation point (G2).

**Also not yet done, tracked separately, not a CHN-33 gap:** converting P1's eight clean origin files
into thin re-export shims pointing at `spine` (so no P1 call site needs to change), and rewiring
`publishing/scheduler.py`/`config/calendar.py` onto the new generic spine code. Deliberately held for
after the user runs `uv sync` and confirms `packages/spine`'s own test suite passes on their own Mac,
specifically to protect the two live_runner processes currently running tonight's nudge/escalation
test.

## 2026-09-21 -- CHN-33 (continued): P1's 14 origin call sites converted to spine shims, real end-to-end verified

Following the user's own `uv sync` + `uv run pytest -v` confirmation (25/25 passing on their Mac, not
just this sandbox), converted P1's side of the extraction: the eight clean components named in CHN-33's
WBS row (gateway, schema layer, proposals, write guard, grounding kernel, harness, prompt registry) plus
the Teams reader/publisher ABC interfaces -- twelve files total -- into thin re-export shims at their
original `src/p1/...` paths, pointing at `spine`. Two more files (`publishing/scheduler.py`,
`config/calendar.py`) became thin P1-facing wrappers rather than pure re-exports, since both needed the
ChannelConfig-specific glue spine's generalized versions deliberately don't own. All 14 changes are
edits to existing files at their existing paths -- no P1 call site anywhere needed to change, and this
was verified directly (see below), not assumed.

**Real bug caught before it reached the live repo, not after.** `p1/storage/db.py`'s `run_migrations()`
takes `migrations_dir: Path = MIGRATIONS_DIR` as a default argument -- and that default binds at
function-DEFINITION time to whichever module defines the function. spine's copy of `run_migrations()`
was moved verbatim, so its own `MIGRATIONS_DIR` resolves to `packages/spine/src/spine/storage/migrations`
-- a directory that doesn't exist. A naive `from spine.storage.db import *` shim would have made
`init_db()` (which nearly every live script and both `live_runner_*.py` processes call with no
`migrations_dir` argument) silently glob an empty/nonexistent directory and apply ZERO of P1's six real
migrations -- `channels`, `channel_config`, `messages`, `proposals`, `write_log`, `nudges`,
`escalations`, all of it. Not an error, not a crash -- just silently absent tables the next time
anything called `init_db()` against a fresh path. Caught by reading the actual code path (not by
running the test suite blind, which uses `tmp_path` fixtures for every DB test and so would have masked
nothing about the bug's actual production trigger), before any shim was written. Fixed by redefining
`run_migrations()`/`init_db()` in the p1 shim as thin wrappers that always pass P1's own `MIGRATIONS_DIR`
through explicitly to spine's real engine; `get_connection()`/`DEFAULT_DB_PATH` (genuinely
location-independent) are re-exported directly.

**Verification, in order:**
1. Grepped the entire `src/p1` tree, `scripts/`, AND `tests/unit/` (not just the two trees checked
   during extraction) for every `from p1.<one of the 14 modules> import ...` site -- about 90 call
   sites across ~40 files -- to build the exact, complete public-API surface each shim must re-export,
   rather than guessing from memory or re-exporting `*`.
2. Built a throwaway `p1` package skeleton in the cloud sandbox around the real, just-written shim
   files, installed against the real, already-pip-installed `spine` package, and ran genuine assertions
   lifted verbatim from this repo's own `tests/unit/test_scheduler.py` and `tests/unit/test_calendar.py`
   -- CronTrigger field values, `is_due()` timezone-conversion cases, `parse_instant()`'s three
   fractional-second-length cases, `local_datetime()`/`is_working_day()` -- all reproduced exactly.
3. Specifically reproduced `tests/unit/test_storage_db.py`'s own migration test against a fake
   P1-specific migration file (distinct from spine's own migrations, which don't exist) to prove
   `init_db()` really does still apply P1's own schema through the shim -- this is what caught and then
   confirmed the fix for the MIGRATIONS_DIR bug above.
4. Grepped `tests/unit/` for `mock.patch(...)`/`monkeypatch.setattr(...)` targeting any of the 14
   modules' dotted paths -- none found beyond one unrelated patch on `teams_reader_graph.time.sleep`,
   so no test's mocking strategy is broken by the re-export indirection.
5. Checked `tests/unit/test_no_inline_prompts.py` (an AST-based lint test scanning `src/`+`scripts/`
   for hand-written prompt literals) against the new shim files specifically: their only string content
   is a module docstring, which that test's own logic already excludes -- confirmed not a false
   positive, not just assumed.
6. `py_compile` on every new/changed file; syntax-clean.

**Not yet done, and this is the real remaining ask of the user:** run the actual `uv run pytest` (full
suite, repo root, not just `packages/spine`'s own 25) on their Mac. Everything above is real,
executed verification against the actual shim files and the actual installed spine package -- but it
is still a sandbox reconstruction of the relevant slice of P1, not the real 100+-file `tests/unit/`
suite running against the real repo with the real `.venv`. That is the one confirmation this session
cannot produce itself (`device_bash` has been wedged the entire session), and it is what actually
closes CHN-33 out. Also unchanged by this session, by design: `config/loader.py`'s `ChannelConfigStore`
stays exactly as it is, and the "adapter framework"/"approval surface" gap against the master plan's
broader ten-item list (see the entry above this one) remains deferred to G2.

## 2026-09-21 -- CHN-33 (continued): root pyproject.toml's workspace wiring silently failed to write, twice, despite the write tool reporting success both times

Real ops finding, not a code bug: after committing all 14 P1-side shims and asking the user to run
`uv sync` + `uv run pytest tests/unit -q` on their Mac, every test failed to collect with
`ModuleNotFoundError: No module named 'spine'`. Root cause, found by re-staging and reading
`pyproject.toml` directly off the user's Mac rather than trusting the earlier write confirmation: the
file on disk was still the original 821-byte version with none of the `[tool.uv.workspace]`/
`[tool.uv.sources]`/`"spine"` dependency wiring -- even though the write that added it, days earlier in
this same session, had reported `{"written": [...], "rejected": []}` with no error. The file's mtime had
in fact changed (consistent with a write happening), but the bytes that landed were the pre-edit
content, same size as the original. A second attempt at the same write, using a freshly re-staged mtime
as the guard, was verified this time by an independent re-stage-and-read afterward (not by trusting the
"written" response alone) -- confirmed correct, all 1302 bytes, workspace section present.

**Takeaway recorded here on purpose:** a `device_commit_files`-style "written, no rejection" result is
not sufficient confirmation that content actually landed correctly for a file this critical to the
build -- an independent read-back after the write is what actually confirms it, and that is now this
session's standing practice for `pyproject.toml`-class changes specifically. `uv lock`/`uv sync` on the
user's Mac silently doing nothing ("Resolved 87 packages... Checked 78 packages", no install line) was
the first correct signal something was wrong -- it should have shown `spine` being added.

## 2026-09-21 -- CHN-33 (continued): all 469 real unit tests pass; root cause of the "spine not importable" saga was a corrupted root .venv, unrelated to the extraction itself

After the workspace wiring fix (previous entry), `uv sync`/`uv lock` reported installing spine correctly, but `python -c "import spine"` and `uv run pytest tests/unit -q` kept failing with `ModuleNotFoundError: No module named 'spine'` (59 collection errors), reproducing identically across multiple `uv sync` runs.

Diagnosis (all done by independently inspecting the real files on disk via the device bridge's list/stage tools, since `device_bash` stayed wedged for the entire session -- `uv run`/shell commands were run by the user and pasted back):

- `spine.pth` and `p1.pth` were both present in `.venv/lib/python3.10/site-packages`, byte-correct, pointing at the right `src` directories. `uv pip show spine` confirmed uv's own package DB considered it correctly, editably installed.
- Manually prepending `packages/spine/src` to `sys.path` and importing worked instantly -- proving the spine package content itself was always fine.
- `uv run python -c "import sys; print(sys.path)"` showed NEITHER `p1.pth`'s nor `spine.pth`'s target directory ever landing in `sys.path`, even though `.venv/lib/.../site-packages` itself (where those `.pth` files live) was present. So `.pth`-file processing was silently failing for BOTH workspace members' editable installs in this one venv -- not something introduced by CHN-33.
- Ruled out a `PYTHONPATH` env var (found exported, duplicated, in `~/.zshrc` line 17, pointing at an unrelated old project) as the cause: unsetting it and retrying still failed the same way.
- `.venv/lib/python3.10/site-packages/_virtualenv.pth` (`import _virtualenv`, the `virtualenv` tool's system-site-isolation seed hook, alphabetically first) was present, suggesting this particular `.venv` had accumulated some non-standard state across the several different `uv sync` invocations earlier in this session (including the one accidentally run from inside `packages/spine` that first created a stray standalone venv there).

Rather than keep reverse-engineering exactly why this one venv's `.pth` processing broke, rebuilt it clean: `rm -rf .venv && uv sync`. This did not touch source, the lockfile, or the two live `live_runner_*.py` processes (a deleted-and-recreated `.venv` directory doesn't affect a process that already has its interpreter loaded in memory). Confirmed fresh:

```
uv sync            -> Installed 79 packages, including "+ p1==0.1.0" and "+ spine==0.1.0 (from file:///.../packages/spine)"
python -c "import spine; print(spine.__file__)"   -> spine OK: .../packages/spine/src/spine/__init__.py
uv run pytest tests/unit -q                        -> 469 passed, 1 warning in 16.74s
```

**CHN-33 acceptance is now genuinely, independently verified end-to-end on the real repo**: the spine package extraction, all 14 P1-side shim/wrapper files (including the `run_migrations`/`MIGRATIONS_DIR` binding fix), and the root `pyproject.toml` workspace wiring are all correct. The entire "spine not importable" saga across this session was a red herring caused by a corrupted local `.venv`, not by anything in the extraction itself -- worth remembering if a similar "package installed but not importable" symptom shows up again on this machine: check for a broken/accumulated venv before re-auditing the package or its `pyproject.toml` wiring.

Deferred (unchanged from the earlier entry, still deferred to G2 on the user's explicit decision): `p1/adapters/factory.py` (adapter framework) and `p1/approval/service.py` (approval surface) were not extracted into spine this gate.

## 2026-09-21 -- CHN-33 (continued): systemic sys.path gap across 31 scripts + app/approval_dashboard.py, all fixed

Streamlit's approval_dashboard.py hit `ModuleNotFoundError: No module named 'spine'` even though `uv run pytest`/`uv run python -c` had already proven spine importable in this exact venv. Root cause: `app/approval_dashboard.py` has a hardcoded `sys.path.insert(0, .../  "src")` (predating CHN-33), so `p1` always imports regardless of `.pth` processing -- but there was no equivalent insert for `packages/spine/src`, so anything reaching `p1.adapters.teams_publisher` (which does `from spine.adapters.teams_publisher import TeamsPublisher`) depended entirely on `spine.pth`'s site-packages redirect activating, which does not reliably happen under Streamlit's own script-execution model (still not fully root-caused). Fixed by adding a second `sys.path.insert` for `packages/spine/src`, mirroring the existing pattern.

While recovering a stalled Graph token (`scripts/graph_seed_token_cache.py`), the exact same crash reproduced for a second, unrelated script -- confirming this isn't a Streamlit-only problem but a systemic gap: `grep` found the same `sys.path.insert(0, .../ "src")` pattern, with no spine equivalent, in 31 more files under `scripts/`. All 31 were fixed the same way, in one batch, mechanically (only the sys.path section touched, nothing else): graph_seed_token_cache.py, live_runner_p1_agent_test.py, live_runner_teams_agent_test.py, test_weekly_today_adhoc.py, test_spn04_roster_changes_non_responders.py, test_spn04_isolation.py, test_publish_idempotency_p1_agent_test.py, test_llm_gateway_smoke.py, test_live_config_update_adhoc.py, test_digest_today_adhoc.py, sync_to_supabase.py, sync_from_dataverse.py, sync_channel_config_to_db.py, seed.py, search_messages_p1_agent_test.py, run_live_pipeline_teams_agent_test.py, run_live_pipeline_p1_agent_test.py, run_live_nudge_p1_agent_test.py, run_live_ingest_p1_agent_test.py, run_eval.py, run_daily.py, reset_daily_digest_days.py, repost_stuck_digest.py, preview_daily_summary_teams_agent_test.py, power_automate_smoke_test.py, live_scope_gate_test_p1_agent_test.py, graph_smoke_test.py, graph_replies_smoke_test.py, graph_login.py, diagnose_second_channel_delta_400.py, approve_cli.py.

Notably this includes `live_runner_p1_agent_test.py` and `live_runner_teams_agent_test.py` themselves -- both currently-running live processes were started before today's `.venv` rebuild and so never actually hit this bug, but had it been present, restarting either one after today's venv rebuild would very likely have failed to start with this identical error. Fixed proactively, not because either process is broken right now.

Every edited file was syntax-checked (`py_compile`) before committing, and every commit was independently re-staged and byte-count-verified afterward, per the standing practice from this session's earlier pyproject.toml incident.

The underlying question of *why* `spine.pth` doesn't reliably activate in some execution contexts (Streamlit, a freshly-launched `uv run python scripts/*.py`) but does in others (`pytest`, `python -c`) remains open and unexplained. The sys.path.insert fix works around it reliably everywhere it's applied, but if a *new* script is added later that imports anything under `p1.adapters`/`p1.approval`/`p1.llm`/etc. without this same two-line sys.path pattern, it can hit this identical error. Worth fixing at the source (or at minimum documenting the required pattern for new scripts) rather than continuing to patch reactively.

## 2026-09-21 -- Thread replies were never ingested by the live pipeline (fixed)

**Finding.** Adding two members to `p1-agent-test` and having them reply in
a thread under an existing message never showed up in the database, even
after the sys.path fix restored silent Graph token refresh and ingest ticks
went from `[ingest] SKIPPED` to genuinely running. Root cause: Microsoft
Graph's `/teams/{team}/channels/{channel}/messages/delta` endpoint -- the
only thing `GraphTeamsReader.list_messages()` calls, and therefore the only
thing `ingestion.sync.sync_channel()`/`_drain_pages()` ever call -- returns
top-level root messages only. A thread reply only ever surfaces via a
separate, per-root `GET .../messages/{id}/replies` call
(`TeamsReader.list_replies()`). That method has existed on every
`TeamsReader` implementation (mock, Graph, scope-gated) since CHN-03/04 and
is unit-tested in isolation, but was never called anywhere in the live
ingestion path -- only from standalone smoke-test scripts. This meant no
thread reply from any member, old or new, could ever reach `messages`,
`classifications`, the daily digest, or nudge/escalation tracking, despite
`config/channels/*.yaml`'s own `count_thread_replies: true` implying
replies were meant to count. Not an auth or scheduling bug -- a missing
feature in the ingestion path itself.

**Fix.** Three small, reader-agnostic pieces, wired together only in the
live_runner scripts that actually use them, per Liskov substitution (every
`TeamsReader` -- mock, Graph, scope-gated -- must keep working identically
through `sync_channel()`/`sync_channel_replies()`):

1. `MessageStore.list_root_message_ids(channel_id, since=None)`
   (`src/p1/storage/messages_repo.py`) -- returns every non-deleted root
   message id (`thread_root_id IS NULL`) this channel has, the set a
   caller needs before it can ask for each root's replies.
2. `ingestion.sync.sync_channel_replies(reader, channel_id,
   root_message_ids, message_store)` (`src/p1/ingestion/sync.py`) -- loops
   `reader.list_replies(root_id)` for each given root and upserts the
   results. Reader-agnostic; contains nothing `ScopedTeamsReader`-specific.
   Safe to rerun every tick -- `MessageStore.upsert_messages()` is an
   idempotent `INSERT ... ON CONFLICT DO UPDATE`.
3. `ScopedTeamsReader.note_known_message(message_id, channel_id)`
   (`src/p1/governance/scope_gate.py`) -- lets a caller re-establish a root
   message id as known-good to a *fresh* gate instance. Necessary because
   `_poll_ingest()` builds a brand-new `ScopedTeamsReader` every tick, and
   `_channel_id_by_message_id` lives only in that instance's memory (see
   2026-09-20's hardening entry above) -- so a root ingested in an earlier
   tick would otherwise be permanently refused with `ScopeViolationError`
   the moment this tick tried `list_replies()` on it, even though it is
   already committed, on-allowlist, known-good data. Still runs through
   `_enforce()` first, so it cannot be used to assert an out-of-scope
   channel_id -- only to re-assert something already in scope. Covered by
   new tests in `tests/unit/test_scope_gate.py` (success on an allowlisted
   channel, `ScopeViolationError` + audit record on a non-allowlisted one).

`_poll_ingest()` in both `scripts/live_runner_p1_agent_test.py` and
`scripts/live_runner_teams_agent_test.py` now runs this between the
existing `sync_channel()` call and the classify/persist step: read back
every known root via `list_root_message_ids()`, re-assert each one via
`note_known_message()`, call `sync_channel_replies()`, log the count, then
classify as before -- so a reply ingested this tick is classified in the
same tick, not the next one.

New tests: `test_scope_gate.py` (`note_known_message` success/refusal/audit),
`test_ingestion_sync.py` (`sync_channel_replies` fetch, idempotent rerun,
zero-replies case), `test_messages_repo_member_registration.py`
(`list_root_message_ids` excludes replies and deleted roots, is scoped per
channel, honours `since`).

**Caveat.** The two running live_runner processes read their own source at
startup and do not hot-reload -- this fix only takes effect once each is
restarted. Restarting also means the immediate next ingest tick will, for
the first time, walk every existing root message's replies (bounded by
this channel's current small history; `list_root_message_ids()` accepts an
optional `since` lower bound for when that no longer holds).

**Not yet done.** The two new members' replies will only actually reach
`members`/`messages` once a live_runner process with this fix has run and
polled. Adding their AAD object ids to `config/channels/p1-agent-test.yaml`'s
`roster:` -- the original ask that led to this finding -- still needs that
data first.

## 2026-09-21 -- Thread-replies fix (continued): note_known_message() also had to seed GraphTeamsReader's own cache

**Finding, from the first live restart with the fix above.** Both
live_runner processes restarted cleanly and got past the sys.path/token
issues, but the very first ingest tick on each failed:

```
[ingest] FAILED -- KeyError: "Unknown channel for message_id='...' --
list_messages() must be called for its channel before
list_replies/get_permalink."
```

Root cause: `ScopedTeamsReader.note_known_message()` (added above) only
ever seeded the *gate's own* `_channel_id_by_message_id` cache. But
`ScopedTeamsReader.list_replies()` still delegates to
`self._reader.list_replies(message_id)` -- the wrapped `GraphTeamsReader`
-- which resolves `channel_id` from its *own*, entirely separate
`_channel_id_by_message_id` cache (see `teams_reader_graph.py`'s own
docstring; this separation was already known and documented, just not
accounted for in the first version of this fix). Seeding only the gate's
cache let the gate's own check pass, but the call was then still refused
one layer down, inside the wrapped `GraphTeamsReader`, which had never
itself seen that message_id in this process's lifetime.

**Fix.** `GraphTeamsReader` gained its own `note_known_message(message_id,
channel_id)` (`src/p1/adapters/teams_reader_graph.py`), seeding its own
cache directly. `ScopedTeamsReader.note_known_message()`
(`src/p1/governance/scope_gate.py`) now forwards to the wrapped reader's
`note_known_message`, duck-typed via `getattr`/`callable` rather than an
`isinstance` check against `GraphTeamsReader` specifically -- so this
keeps working for any `TeamsReader` implementation that needs the same
seeding, and is a no-op for one that doesn't (`MockTeamsReader` has no such
method and needs none, since its own `list_replies()` scans every
channel's messages directly with no cache to resolve).

New tests: `test_teams_reader_graph.py` (`list_replies` still raises
`KeyError` for an unseen message on a fresh instance; `note_known_message`
lets it resolve without a prior `list_messages()` call), `test_scope_gate.py`
(`note_known_message` forwards to a wrapped reader that exposes the same
method; does not forward -- and does not raise -- when the wrapped reader
doesn't have one).

**Status.** Not yet re-verified live -- both live_runner processes need a
second restart to pick this up. `uv run pytest tests/unit -q` still
pending from the user to confirm both this and the original thread-replies
fix pass against the real repo.

## 2026-09-21 -- Thread-replies fix (continued): pytest's own pythonpath was missing packages/spine/src

**Finding.** `uv run pytest tests/unit -q` failed at collection with
`ModuleNotFoundError: No module named 'spine'` across 19 test modules --
none of them touched by the thread-replies fix itself (`test_calendar.py`,
`test_classifier.py`, `test_channel_config.py`, etc.), so this was a
pre-existing environment gap surfacing the first time pytest was actually
run in this session, not a regression from the fix above.

Root cause: `pyproject.toml`'s `[tool.pytest.ini_options]` had
`pythonpath = ["src"]` only. That option is pytest's own path-injection
mechanism -- independent of Python's `site.py` `.pth` processing -- which
is exactly why every `p1.*` import kept resolving fine (the errors were
always "no module named spine", never "no module named p1"). CHN-33's
spine extraction added `packages/spine/src` as a second path every
`p1/*.py` module now needs, wired only through the venv's `spine.pth`
(site-packages) redirect -- and a live diagnostic this session confirmed
that redirect does not reliably activate even for a bare
`uv run python -c "import spine"` (`sys.path` printed with no `src` or
`packages/spine/src` entry at all, despite `spine.pth` existing with the
correct absolute path and the real `packages/spine/src/spine/` package
being fully intact on disk) -- consistent with, and now directly
confirming, this session's earlier "some execution contexts don't process
.pth reliably" finding. `uv sync` reported "Checked 79 packages" with no
changes, ruling out a lock/install-state problem.

**Fix.** One line in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["src", "packages/spine/src"]
```

Same fix, in spirit, as the 32-file `sys.path.insert` batch fix earlier
this session -- `packages/spine/src` was omitted from an explicit path
list that already existed for exactly this reason, in yet another context
(pytest's own config, this time, not a hand-written script). The root
cause of *why* `.pth` processing itself is unreliable across contexts
remains unexplained and undocumented beyond "confirmed, not yet
root-caused" -- every fix so far (scripts, pytest) has been to stop
depending on it, not to repair it.

**Verified.** `uv run pytest tests/unit -q` -- 482 passed (469 previously
+ 13 new tests from this fix: 5 in `test_scope_gate.py`, 3 in
`test_ingestion_sync.py`, 3 in `test_messages_repo_member_registration.py`,
2 in `test_teams_reader_graph.py`). Both live_runner processes already
confirmed live and clean (`[ingest] N reply message(s) synced across M
thread(s)`, no `FAILED`) on both `p1-agent-test` and `Teams-agent-test`.
`p1-agent-test`'s roster now includes Himanshu Ranjan
(`230d27f7-dd11-407c-8822-8947f0068611`) and Esandu Obadaarachchi
(`442e9b43-e50a-446c-9c4b-e612e9036bd8`) alongside Sharon Silva. The
thread-replies ingestion gap (this entry's original 2026-09-21 finding
above) is now fully fixed, live-verified, and test-covered end to end.

## 2026-09-21 -- Escalation messages now use the member's real display name

**Finding.** After manually correcting `members.display_name` for Sharon
Silva, Himanshu Ranjan, and Esandu Obadaarachchi in the live DB (the
auto-registered placeholder is the AAD id itself, per
`messages_repo.py`'s own `_ensure_member_exists` docstring), a check of
the actual rendering code showed the fix had no visible effect anywhere:
`daily_job.py`, `facts.py`, and `ledger.py` never reference
`display_name` at all, and `escalation_job.py`'s own
`_render_escalation_message()` interpolated `member_id` directly into
the message sent to the channel owner -- the one place in this pipeline
that actually names a specific person for someone else to read.
`nudge_job.py`'s own message never names the recipient at all (it's a
direct message *to* them), so it needed no change.

**Fix.** Added `_resolve_display_name(member_id, db_path=...)` to
`escalation_job.py` -- a plain `members` table lookup, falling back to
the bare `member_id` if no row exists (defensive; every real author is
auto-registered on ingest, and `nudges.member_id`/`messages.author_id`
both carry a real `REFERENCES members(id)` foreign key, so a candidate
reaching this code path -- which requires a prior nudge, itself FK-bound
to `members` -- is guaranteed to already have a row; this fallback is
belt-and-suspenders, not a reachable production path). `_evaluate_member()`
now resolves the display name once per escalation and passes it into
`_render_escalation_message()` (renamed parameter, same rendering logic).

New test: `test_escalation_message_uses_the_members_display_name_not_the_raw_member_id`
in `test_escalation_job.py`, seeding a member with a display_name
deliberately different from their member_id (this file's own `db_path`
fixture otherwise seeds `display_name == member_id` for every member,
which made the original bug invisible to every existing test in this
file). A second, "missing member row" defensive-fallback test was
attempted and dropped -- constructing it through `run_escalation_job()`'s
public API is not actually possible without violating the same
`REFERENCES members(id)` foreign key this fix relies on, since escalation
requires a prior nudge and nudging itself requires a `members` row to
exist first.

**Verified.** `py_compile` clean on both files; `uv run pytest tests/unit -q`
still pending re-run from the user to confirm 483 passed (482 previous +
this one new test).
