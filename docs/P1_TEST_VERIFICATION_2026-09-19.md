# P1 Full-Capability Test Verification — 2026-09-19

Independent verification pass over P1 (Teams Channel Intelligence), run against the working copy at `/Users/andreasharonsilva/Desktop/P3_Agents` and against the actual public GitHub repo. Scope was deliberately limited to what can be checked safely from a cloud sandbox: the automated test suite, the eval harness's committed output, the seed data, the code for every MUST/SHOULD capability, today's `DECISION_LOG.md` entries, and the real git history. Nothing here touched Microsoft Graph, Power Automate, Teams, Bedrock, or Copilot Studio — those all carry real credentials and can message real colleagues, so every live-service check in this pass is a *read* of evidence you already produced today, not a new live call I made myself.

## 1. Automated test suite

Your machine's own shell couldn't run `uv sync` for this (its network is too slow/restricted to pull packages — the same limitation `DECISION_LOG.md` already noted). I moved a copy of the repo into the sandbox instead (tarball, excluding `.venv`/`.git`) and ran it there with full package access.

Working tree (with today's uncommitted fixes): **462 passed, 2 skipped, ruff clean** — three repeated runs, all identical, no flakes. The two skips are `tests/live/test_chn09_live_classification.py`'s pair, which correctly require a real `ANTHROPIC_API_KEY` and skip without one.

Worth calling out: the order-dependent flake `DECISION_LOG.md` flagged repeatedly through the day (`test_dashboard_lists_and_approves_a_pending_nudge`, failing depending on test run order) did **not** reproduce in any of my three runs. That's consistent with the `load_dotenv()` fix — pinning `TEAMS_PUBLISHER_MODE=mock` via `monkeypatch` in both dashboard tests removes the ambient-environment dependency that caused the order-sensitivity in the first place. Worth one more confirmation on your own machine, but this looks genuinely fixed, not just quiet.

## 2. Eval harness — the 12 golden cases

I didn't re-run `scripts/run_eval.py` myself: this sandbox has no reachable model backend (no `ANTHROPIC_API_KEY` in `.env`, and `LLM_PROVIDER=ollama` needs your local Ollama, which isn't running here). Instead I read the actual committed history in `eval/results.jsonl`.

There's a run more recent than the one the README cites: **2026-09-19T09:13:31Z, model `claude-sonnet-4-20250514`, 34/34 metrics passing across all of GC1–GC12** (the README still cites the 2026-09-18T05:51:27Z run — a one-line doc update, not a real problem). None of GC1–GC12's own assertions exercise the specific bug you found and fixed later that day (a human-approved publish never marking its digest published) — GC6/CHN-18 tests same-day reruns with a scripted approval, not the cross-day "approve once via the dashboard, then check the next due day" path the real bug was in. That's a genuine, narrow gap in golden-case coverage, not a wrong result — recommend re-running `scripts/run_eval.py` once more after committing today's fixes, mainly to keep the committed numbers current, since I don't expect any of the 34 metrics to actually change.

## 3. Seed data and planted difficulties

Cross-checked `seed/fixtures/labels.csv` line by line against sheet 06's 15 named planted difficulties. All 15 are present and correctly labelled (reaction-only member, chatter-only member, the on-leave exception, the thread-reply-only update, the one-minute-late post, both bot posts, the system message, all three edited-message cases, all three deleted-message cases, the similar-name pair, posting-on-behalf-of-another, the silent day, the configured non-working day, and the ambiguous @mention). Three more categories were added later for real eval-harness gaps (`not_on_roster`, `thread_reply_when_not_counted`, `below_length_floor`) — 18 categories, 23 rows total, matching `DECISION_LOG.md`'s own count exactly.

One thing worth knowing about your own workbook: the "00 Read Me" sheet says "twenty planted difficulties for P1 alone" (row 35), but the "06 Seed Data" sheet only ever names 15. `DECISION_LOG.md` already caught and resolved this exact inconsistency in the code (built to the actual named 15, not the unreconciled "twenty"), so nothing to fix in the repo — just flagging that the source workbook itself still carries the stale figure, in case you tidy it later.

## 4. Capability-by-capability (C1–C12)

Read the actual implementation (not just the README's claims) for the highest-risk modules — `participation/ledger.py` (the three-honest-states logic), `approval/write_guard.py` (the fail-closed approval gate), and `grounding/kernel.py` — and cross-checked every other capability against its test file. None are stubs; the write guard in particular is written defensively exactly as the plan demands (any lookup failure, not just a narrow exception, refuses the send — never a silent pass-through). Combined with the passing test suite, I'm confident in the README's Done claims for C1–C12.

| Cap | Capability | Verified |
|---|---|---|
| C1 | Channel registry & per-channel config | Done — GC12 passing |
| C2 | Teams ingestion via Graph, delta tracking | Done — GC10 passing; **also live-verified against the real tenant today** |
| C3 | Scope gate (allowlist only) | Done — GC5 passing |
| C4 | Update detection (rules + classifier) | Done — GC1 passing |
| C5 | Participation ledger / non-responder detection | Done — GC2 passing (all 3 states exact-match) |
| C6 | Daily summary with grounding | Done — GC3/GC4/GC9 passing |
| C7 | Scheduled publishing, idempotent | Done — GC6 passing; no standalone always-on scheduler process yet (one-shot script only) |
| C8 | Approval gate & audit | Done — GC8 passing |
| C9 | Weekly roll-up with trend | Done — GC11 passing |
| C10 | Nudges (opt-in, capped) | Done — GC7 passing |
| C11 | Escalation to channel owner | Done — GC7 passing |
| C12 | Versioned outcome record | Done — schema round-trip tested |

## 5. Real, independent proof: what a clean clone gets *right now*

This is the most important finding. I cloned the actual public repo fresh (`git clone https://github.com/Sharon-dt3/P3_Agents.git`) rather than trusting my copy of your working tree, and ran the full suite with no `.env` at all — the genuine Gate-G1 "clean clone, no tenant credentials" scenario. Result: **454 passed, 2 skipped, ruff clean.** Installs and runs cleanly, exactly as the README promises.

But that's 8 tests fewer than your working tree's 462. Your working tree currently has **18 modified, uncommitted files** — and they're not incidental ones. They include every one of today's real fixes: `src/p1/approval/service.py` (the mark-published bug), `src/p1/storage/participation_repo.py` (the FK bug), `src/p1/llm/gateway.py` (the swallowed-error-message bug), `src/p1/publishing/daily_job.py` and `src/p1/approval/proposals.py` (the stale-payload bug), `app/approval_dashboard.py` (the missing `load_dotenv()`), plus their tests, `README.md`, `DECISION_LOG.md`, and `eval/results.jsonl`. A clean clone taken right now would silently ship every one of the bugs you found and fixed today. Since the Deliverables sheet's own rule is "commit incrementally, one large commit at the end is a red flag," I'd treat committing these — in a few logical commits rather than one — as the single highest-priority remaining item before calling today's live testing done.

## 6. Still open (from today's own `DECISION_LOG.md`, not new findings)

Everything below is already disclosed in your decision log; I'm collecting it in one place because it's the actual "what's left" list for calling P1's live workflow fully tested, as opposed to its mock-adapter behaviour (which is fully tested and passing):

The Teams markdown citation link (`[source](url)`) has never been independently confirmed to render as a clickable hyperlink inside real Teams — the one message posted so far was pasted back with raw markdown syntax, which could be a copy artifact or could mean the Power Automate "Post message" action needs to be told its body is Markdown/HTML. This is worth a direct, deliberate check, since a clickable permalink is explicitly named as the demo's best ten seconds.

The Streamlit dashboard's message-preview expander still calls `st.text(content)` rather than `st.markdown(content)` (confirmed still present at `app/approval_dashboard.py:105`), so a real approver sees raw `[source](url)` text rather than a clickable link in the one surface they actually use to review a digest before approving it.

`CURRENT_USER_ID` still defaults to the placeholder `"priya"` (`app/approval_dashboard.py:53`) unless `P1_APPROVER_ID` is set — every approval made without that env var set is attributed to a name that isn't the real approver. Low risk for a single-operator pilot, real risk the moment a second person approves anything.

`nudge_job.py` and `escalation_job.py` were explicitly flagged as not yet audited for the same stale-payload class of bug `daily_job.py` had (they build proposals differently — no idempotency-key lookup against an existing pending proposal — so they may or may not share the exposure, but it hasn't been checked either way).

`proj-alpha`/`proj-beta` are still mock-fixture channel IDs, not real Teams channels — a deliberate, tracked, still-undecided choice, not a bug.

CHN-33 (extracting the shared spine into its own installable package, one of Gate G1's own named exit criteria) hasn't been done yet — everything so far lives inside `src/p1/` rather than a separate, independently-tested spine package P2/P3 would import.

No standalone always-on scheduler process exists yet — `make run` / `scripts/run_daily.py` is a one-shot script that every test and the real live pipeline already exercise; wiring `p1.publishing.scheduler.build_scheduler`'s clock into a long-running process is still real, undone work.

## 7. Repo hygiene — one worth acting on

`.env.bak` (a real credential backup from the earlier Ollama switch) is untracked but **not** listed in `.gitignore` — only `.env` itself is. It currently has no commit history (confirmed via `git log --all -- .env.bak`), but it's one careless `git add -A` away from landing real AWS/Graph/Power-Automate secrets in your public GitHub repo. Recommend adding `.env.bak` (or a `.env*` pattern that still allows `.env.example`) to `.gitignore`, then deleting the file. I checked `try_self_grant_bedrock.py`, `bedrock_diagnose.py`, and the two `_tmp_decision_log_entry_*.md` files sitting untracked in the repo root too — no hardcoded secrets in any of them (they read credentials from the environment), just loose ends worth sweeping up before your next commit pass.

One more: I created `_cloud_test_tmp/p1_repo.tar.gz` in your project folder to get a copy of the repo into the sandbox (your machine's own shell couldn't run `uv sync` — too little network bandwidth to fetch packages). It's an 800KB tarball with no secrets in it, but I don't have delete permission on this folder, so please remove `_cloud_test_tmp/` yourself.

## 8. Gate G1 scorecard (sheet "02 Schedule & Gates")

| Requirement | Verdict |
|---|---|
| All 8 MUST capabilities run end to end on the fixture | Yes — confirmed via passing tests today |
| 12 golden cases print committed numbers | Yes — 34/34, `eval/results.jsonl`, 2026-09-19T09:13:31Z |
| Clean clone verified with no tenant credentials | Yes, **as of the last commit** (`d60a313`) — but that predates today's fixes; re-verify after committing them |
| Walkthrough recorded | Not independently checked this pass (no video artifact to inspect from here) |
| Spine extracted as an installable package | **Not yet done** — CHN-33 still outstanding per `DECISION_LOG.md` |

## Bottom line

The mock-adapter build is genuinely solid: 462 tests, 34/34 golden cases, no stub code in the parts that matter most, and a real clean-clone run against the actual public repo confirms it installs and runs from nothing. Today's live-Teams work found and fixed six real bugs the mock-only path could never have surfaced (fractional-second timestamps from real Graph data, the GUID-vs-email identity mismatch, the swallowed Bedrock error, the stale proposal payload, the FK gap, the missing `load_dotenv()`) — that's exactly what live testing is for, and none of it is a bad sign about the build. The actual remaining work is narrow and known: commit today's 18 changed files, get an honest look at whether a Teams citation link is really clickable, fix the dashboard's raw-markdown preview and the `priya` placeholder, decide proj-alpha/proj-beta's fate, and audit the nudge/escalation jobs for the same payload-staleness class of bug the daily job had.
