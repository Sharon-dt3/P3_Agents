# Incubation Pod — Master Implementation Plan (Reconciled)

Single builder, six weeks, three agents, ten days each — P1 Teams Channel Intelligence (W1–2) → P2 PM Delivery Steward (W3–4) → P3 PO Backlog Architect (W5–6). This document reconciles all nine source sheets (Master WBS, Schedule & Gates, Tool Split, Traceability, Eval Plan, Seed Data, Adapters, Risks, Deliverables) into one sequential build plan, records what is actually done in the repo as of this writing, and flags every place the source sheets disagreed with each other so a decision doesn't get silently guessed.

Status as of 2026-09-17. Repo: `p1-teams-intelligence` at `github.com/Sharon-dt3/P3_Agents`.

---

## 0. Open decision — read this before touching CHN-07 again

Three sheets say P1's seed data has **twenty** planted difficulties (Sheet guide, Schedule & Gates W1/D3, Risk Register R8). Two sheets say **fifteen** (Master WBS's CHN-07 cell text, and — critically — sheet 06 Seed Data, which is the only sheet that actually *names* each one). Sheet 06 names exactly 15 specific cases; no sheet anywhere names 20. The working assumption in this plan is **sheet 06's 15 is the real spec and "twenty" is a stale figure left over from an earlier draft** — but this has not been confirmed by the user, and CHN-07 has not yet been reworked to match it. Until it is, treat CHN-07 as **built but wrong** (20 categories of my own design, committed, but not verified against sheet 06's actual list).

The 15 from sheet 06, and how the current build compares:

| # | Sheet 06's exact spec | Current state | Fix needed |
|---|---|---|---|
| 1 | Posts only reactions/emoji → counts as no update | Built as short emoji **messages** (state b) | Rebuild as **zero messages at all** (state a) — a reaction isn't a message under Graph |
| 2 | Chatter every day, never an update → state (b) | fatima.hassan — matches | None |
| 3 | On exceptions list for leave → never silent/nudged | liam.oconnor — matches | None |
| 4 | Update is a thread reply, never a root message | Not built as a distinct case | Add |
| 5 | Posts one minute after window closes | Built at exactly window-end, not +1min | Fix timing |
| 6 | A bot/connector post | ci-bot ×2 (spec implies 1) | Trim to 1 |
| 7 | System message (member joined) | Matches | None |
| 8 | Message edited after the window closed | 4 edits, none verified to cross the window boundary | Rebuild as 1 case, verified |
| 9 | Deleted message that was that member's only update that day | 3 deletions, not verified as sole message of the day | Rebuild as 1 case, verified |
| 10 | Two similar display names | olivia.dupont / olivia.dupree — matches | None |
| 11 | Posting on behalf of another ("posting for Priya...") | Not built | Add |
| 12 | A day with no messages in one channel | Exists (proj-beta silent day) but filed under CHN-06, not labeled as a CHN-07 row | Add a labels.csv row for it |
| 13 | A weekend and one configured non-working day (holiday) | Weekends only; no separate configured non-working weekday | Add |
| 14 | An @mention that reads like an assignment but is actually a question | Not built | Add |
| 15 | A roster member who has since left the tenant | Built backwards — dropped from config roster but still visible to Graph | Flip: **stays on config roster**, Graph no longer shows them as a member, zero messages ever |

Also currently in the fixture but **not in sheet 06's list at all**: a duplicate rapid double-post, and wei.chen's cross-channel identity reuse (a natural side-effect of the roster-overlap requirement, not itself a planted case). The timezone mismatch is correctly a CHN-06 config-fixture feature per sheet 06/07, not a CHN-07 difficulty — it was mislabeled as one.

**Action when resumed:** rebuild `scripts/generate_seed_fixtures.py`'s CHN-07 section and `labels.csv` against exactly these 15 (with the corrections above), drop the 2 extras or keep them as clearly-marked bonus cases outside the 15, and re-verify the message/allowlisted counts still sit in the 150–250 target. This is the very first thing to do before D4.

Other stale-artifact notes from the source sheets (none block anything, just flagged for honesty): the Traceability sheet's header says "four COULD rows" but lists five (C13, C14, P10, P11, O12); the Deliverables sheet still references pre-rescoping task IDs (`MTG-26` etc. instead of `CHN-`) from before P1 was re-scoped off the original meeting-transcript brief.

---

## 1. What's actually done right now

| Task | Status | Detail |
|---|---|---|
| SPN-01 Repo scaffold | **Done** | uv-managed package, Makefile, CI, `.env.example`, `.gitignore`, README/decision-log skeletons |
| SPN-02 LLM gateway | **Done** | `LLMGateway.generate()` — single call site, provider swap via `LLM_PROVIDER`, on-disk cache by request hash, tenacity backoff + degrade-to-Ollama, JSONL call log (test for this was written but uncommitted until this session — now fixed, see below) |
| SPN-03 Structured-output layer | **Done** | `generate_structured()` — forced-schema tool call, Pydantic validation, re-prompt-with-error retry (capped), raises `StructuredOutputError` rather than defaulting |
| SPN-04 SQLite schema and migrations | **Done** | 10 tables + FTS5 virtual table, migration runner, `make seed` builds a fresh DB from migrations alone |
| CHN-02 Channel registry / config | **Done** | `ChannelConfig` (Pydantic) + `ChannelConfigStore`, versioned YAML in `config/channels/`, synced to SQLite. Three channels now: proj-alpha, proj-beta (both allowlisted), proj-gamma (deliberately not allowlisted) |
| CHN-03 Teams read adapter | **Done** | `TeamsReader` interface + `MockTeamsReader` + `GraphTeamsReader`, factory-selected. Two real bugs caught and fixed (missing `list_channel_members` on the interface; a `self._client_get` typo in the Graph reader) |
| CHN-04 Scope gate | **Done** | `ScopedTeamsReader` enforces the allowlist at the adapter boundary; chats can never pass; every refusal logged to `audit` |
| CHN-05 Ingestion hardening | **Done** | Two-part build: reader-level (paging flag, 429 retry, delta-expiry signal, `is_system` flagging, `sync_state` table) and ingestion-layer (`MessageStore.upsert_messages` edit-safe, `sync_channel`/`sync_all_allowlisted_channels`) |
| CHN-06 Seed fixture | **Done** | `scripts/generate_seed_fixtures.py` (seed=42, deterministic), 3 channels + 2 chats, 10 working days, 231 organic messages (179 allowlisted). Committed separately from CHN-07 so it's independently reviewable |
| CHN-07 Plant difficulties + labels | **Done but flagged for rework** — see §0. Currently 20 categories, not verified against sheet 06's 15 |
| Loose ends | **Done** | Missing SPN-02 test (JSONL call log) committed; `.gitignore` updated for local caches and the scratch plan-doc folder |
| CHN-01 Graph access spike | **Blocked, in progress** | Azure app registered, delegated `ChannelMessage.Read.All` requested, admin consent needs a role this account doesn't hold. Escalated to Alfred 2026-09-15. Per Gate G0b, work proceeds against the mock adapter regardless |

Git state: 4 local commits beyond CHN-05 (`CHN-06`, `CHN-07`, the SPN-02 test fixup, the `.gitignore` cleanup), **not yet pushed to origin** — held locally at the user's request. 37 tests passing, ruff clean.

Not started: everything from SPN-05 onward (prompt registry) through the rest of P1, and all of P2 and P3.

---

## 2. Full day-by-day plan, P1 (W1–2, D1–D10)

Reconciled from the Schedule & Gates sheet and the Master WBS. Each day names its WBS task IDs and its end-of-day definition of done.

**D1 — Spine foundations + Graph access spike ◆ Gate G0b.** SPN-01, SPN-02, SPN-03, CHN-01. *Done* (CHN-01 blocked per G0b's own cut rule: proceed on the mock regardless, escalate the consent request, don't wait on it).

**D2 — Config, Graph adapter, scope gate.** SPN-04, CHN-02, CHN-03, CHN-04. *Done.*

**D3 — Ingestion hardening + seed data.** CHN-05, CHN-06, CHN-07. *Done, CHN-07 flagged for rework (§0).* DoD: two consecutive delta runs produce a correct incremental set; an edited message keeps its original post time; the fixture reproduces byte-identical.

**D4 — Thin end-to-end slice ◆ Gate G0 (not started, next up).** CHN-08 (deterministic rules), CHN-09 (classifier for the remainder), CHN-10 (participation ledger, three honest states), SPN-05 (prompt registry). This is the most important correctness gate in P1: a seeded day must yield a non-responder set matching hand labels, with the reaction-only, chatter-only and on-leave members each in the correct state. **Depends on CHN-07 being correct first** — the hand labels this gate checks against come from `labels.csv`.
  - CHN-08: rules settle the clear cases (roster member, inside window, above length floor, not bot/reaction/system) — Python only, no model, traceable to a named rule and message ID.
  - CHN-09: Claude API (forced schema) classifies only what rules couldn't settle — update/question/blocker/decision/chatter/noise, with confidence; low-confidence surfaced as uncertain, never guessed.
  - CHN-10: pure set arithmetic — roster minus contributors within the window, three states never collapsed, no inferred reasons.
  - Cut rule if G0 slips: this is a STOP AND FIX gate — no daily summary, publishing, or nudges until the ledger is right.

**D5 — Grounding and first numbers.** SPN-06 (grounding kernel: reference-or-drop + verbatim quote verifier), SPN-07 (eval harness framework), CHN-11 (GC1 detection precision/recall, GC2 non-responder exact match), CHN-12 (GC5 scope-gate hard zero, GC10 ingest correctness). DoD: first detection precision and an exact-match non-responder number, committed; zero out-of-scope messages in the store.

**D6 — Daily summary.** CHN-13 (per-channel daily summary, facts-in-code/prose-from-model, permalink per line), CHN-14 (honest participation rendering — no inferred reasons, no ranking), CHN-15 (GC3 citation rate ≥0.95, GC4 fabrication probe = 0), CHN-16 (GC9 determinism of facts). DoD: every factual line resolves to a real message; a channel with no traffic produces an honest empty summary; two generations agree on the facts.

**D7 — Approval spine and publishing.** SPN-08 (proposal record + status machine), SPN-09 (service-layer write guard), CHN-17 (scheduled publishing, idempotent, per-channel local time, first publish behind approval), CHN-18 (GC6 publish idempotency). DoD: a clock-override run at three channel-local times produces three correctly timed digests and no duplicates; a pending proposal cannot post.

**D8 — Weekly roll-up and nudges.** CHN-19 (weekly roll-up with trend), CHN-20 (GC11 weekly arithmetic reproducibility), CHN-21 (nudges — opt-in, capped, never the excluded), CHN-22 (Teams publish adapter — mock log + real flow). DoD: every weekly figure recomputes by hand; the on-leave member is never nudged under any path; the cap holds across repeated runs.

**D9 — Escalation, config proof, Teams surface, contract.** CHN-23 (escalate to channel owner with dated evidence), CHN-24 (GC7 nudge cap/order, GC8 approval enforcement, GC12 config-is-really-config), CHN-25 (Copilot Studio approval cards + Dataverse config), CHN-26 (versioned outcome record — **the P2 contract**). DoD: with the threshold at three days, exactly the right members escalate; the same day's data under two different rosters produces two different non-responder sets.

**D10 — Harden, measure, demo ◆ Gate G1.** CHN-27 (full 12-case harness run), CHN-28 (fix the worst finding, document it), CHN-29 (edge-case pass — no messages in a channel, non-working day, deleted-only-update, edit-after-window, similar names, throttling/delta-expiry, malformed output, member who left the tenant), CHN-30 (README/architecture note/decision log from the code), CHN-31 (clean-clone verification), CHN-32 (record the walkthrough), CHN-33 (spine extraction into an installable package). Cut rule: cut C9 (weekly trend) first, then C11 (escalation), before degrading C1–C8.

**Gate G1 evidence (end of P1):** all 8 MUST capabilities run end to end; 12 golden cases print committed numbers; clean clone verified with no tenant credentials; walkthrough recorded; spine extracted as a package.


---

## 3. Full day-by-day plan, P2 (W3–4, D11–D20)

P2 lives in its own repo, importing the spine package extracted at G1 and inheriting two of its five adapters (Teams reader, publisher) from P1 outright.

**D11 — Seed data and adapters.** PM-01/02 (25–40 items across 2 sprints, 5–7 assignees, commits, risk log, commitments, 2 P1 outcome records — one missing its scope/consent flag; channel messages reused from P1's fixture, not re-seeded), PM-03 (ten planted difficulties: a blocker open 4 days with no risk entry and another open 1 day; an item moved to done and back the same day; a zero-activity assignee for two days; an unassigned item; two items added mid-sprint; commits with no item reference and one item never transitioned; a free-text status outside the enum; a commitment with a relative due date only; two similar names), PM-04 (tracker/code-host/risk-log adapters — chat and notifier inherited, not rebuilt). DoD: seed committed and reproducible; P1's Teams reader satisfies the chat dependency with no new code.

**D12 — State and deltas.** PM-05 (project-state snapshot with persistence), PM-06 (snapshot diff engine computed in code — the twice-moved item collapses to one accurate entry), PM-07 (GC3 delta correctness). DoD: the item that moved to done and back appears once, described accurately, in the computed delta.

**D13 — Thin end-to-end slice ◆ Gate G1b.** PM-08 (morning brief, facts-in-code/prose-from-model), PM-09 (reference-or-drop wiring — reuses SPN-06), PM-10 (absence reported as absence), PM-11 (scheduler reuse), PM-12 (GC1 citation rate ≥0.90, GC2 fabrication probe = 0). DoD: every factual line carries a resolvable reference; the zero-activity assignee is reported as having no activity; fabricated-claim count is zero. STOP AND FIX if this doesn't hold — no risk log until reference-or-drop is solid.

**D14 — Approval gate and risk log.** PM-13 (approval gate on the proposal spine), PM-14 (GC6 approval enforcement), PM-15 (risk-log store — Dataverse + committed mirror), PM-16 (gap-detection proposals). DoD: the two blockers missing from the risk log are proposed, the three already present are not; the audit trail answers who approved what and when.

**D15 — Promotion and rejection memory.** PM-17 (rejection fingerprinting — no duplicate re-proposal), PM-18 (GC4 gap precision/no-duplicate), PM-19 (blocker-to-risk promotion with a config threshold), PM-20 (GC5 promotion-threshold reconfiguration), PM-21 (prompt files). DoD: reject one proposal, re-run — no duplicate; threshold at 2 days vs 4 days changes the proposed set correctly.

**D16 — Deltas and commitments.** PM-22 (end-of-day summary as genuine deltas, never a restatement of the morning brief), PM-23 (GC9 determinism), PM-24 (commitment tracking with nudges/escalation and the **shared** per-person nudge cap with P1). DoD: the summary names exactly the hand-labelled changed set; the nudge cap holds across P1 and P2 on the same day.

**D17 — Cross-agent contract and Teams surface.** PM-25 (GC7 shared nudge cap/order), PM-26 (consume P1's outcome record — **the cross-agent proof point**), PM-27 (GC8 scope/consent refusal), PM-28 (Copilot Studio brief delivery and approvals). DoD: P1's record is consumed with no shared code beyond the schema; the record lacking its flag yields zero proposals and one logged refusal.

**D18 — Weekly report and robustness.** PM-29 (weekly status — grounded, never auto-sends), PM-30 (GC-level quantitative reproducibility), PM-31 (free-text status → UNMAPPED, never coerced), PM-32 (similar-name disambiguation guard). DoD: every figure recomputes from stored snapshots; the unmappable status appears as UNMAPPED with its raw value.

**D19 — Harden and measure.** PM-33 (full 9-case harness run), PM-34 (fix the worst finding), PM-35 (edge-case pass — empty day, no-activity assignee, twice-moved item, malformed output, rate-limit path, unassigned item, commit with no item reference), PM-36 (README/architecture/decision log from the code). DoD: committed eval results, a documented fix, a README that survives being read against the code.

**D20 — Demo ◆ Gate G2.** PM-37 (clean-clone verification), PM-38 (record the walkthrough — **show the rejection path on camera**), PM-39 (gate review), PM-40 (spine hardening for P3: citation resolver generalisation, config-threshold pattern, proposal fingerprinting, shared nudge cap, eval metric helpers). Cut rule: cut P9 (weekly status) before degrading P3.

**Gate G2 evidence:** all 5 MUST capabilities end to end; 9 golden cases committed; rejection path recorded on camera; clean clone verified; spine hardened for P3.

---

## 4. Full day-by-day plan, P3 (W5–6, D21–D30)

P3 inherits the tracker adapter from P2 and generalises the grounding kernel into a citation resolver over a document index.

**D21 — Seed data.** PO-01 (product brief, 1,500–3,000 words, numbered addressable sections), PO-02 (glossary with a planted inconsistency), PO-03 (existing backlog: 15–25 items mixed quality, one overlap, one contradiction, 4 items labelled ready/not-ready), PO-04 (two epics — one detailed, one deliberately thin — plus two feedback records, one missing consent). DoD: all seed artefacts committed with a labels file for the readiness and overlap cases.

**D22 — Citable context.** PO-05 (plant the three gaps by hand: an unspecified limit, an undefined role, an undefined state transition), PO-06 (context index with hand-checkable section refs — a whole-document reference is invalid by construction), PO-07 (citation resolver, generalising SPN-06), PO-08 (doc-store adapter), PO-09 (GC1 citation resolution = 0 unresolvable). DoD: ask for context on a topic and get back specific citable sections a human can open.

**D23 — Thin end-to-end slice ◆ Gate G2b.** PO-10 (acceptance criteria with open questions as a **required schema field**), PO-11 (grounding enforcement on criteria), PO-12 (GC2 open-question recall 3/3, invented-specific count 0 — **the single most important number in the P3 submission**). DoD: all three planted gaps surface as open questions rather than invented rules. STOP AND FIX — this cannot be retrofitted later.

**D24 — Decomposition and the generic guard.** PO-13 (epic decomposition with citations), PO-14 (GC4 coverage AND redundancy), PO-15 (anti-generic guard, regenerate-on-failure). DoD: the detailed epic decomposes into grounded, product-specific stories; ungroundable ones are reported as gaps, not invented.

**D25 — Readiness gate.** PO-16 (GC3 generic-story rate before/after the guard, target <0.10 after), PO-17 (Definition-of-Ready gate, checklist as config), PO-18 (GC5 readiness accuracy 4/4 with specific reasons), PO-19 (prompt files). DoD: two deficient stories blocked for the right reasons, two adequate ones pass.

**D26 — Prioritisation.** PO-20 (score computed in code from visible inputs, model writes only the rationale), PO-21 (dependency-respecting slice), PO-22 (GC6 reproducibility/perturbation/dependency), PO-23 (GC8 thin-epic negative test — more questions than stories, zero invented behaviour). DoD: three scores recompute by hand; a perturbed input moves the rank as predicted; the thin epic yields more open questions than stories.

**D27 — Overlap and the status floor.** PO-24 (duplicate/overlap detection with relationship types), PO-25 (GC7 precision/recall), PO-26 (draft-back to tracker with the **not-ready status floor enforced in the write path**), PO-27 (GC9 approval/status floor). DoD: two approvals plus two re-runs produce exactly two records, both tagged AI-drafted, both not-ready.

**D28 — Stakeholder input and Teams surface.** PO-28 (synthesis from the feedback record and P1's channel outcome records), PO-29 (GC10 glossary consistency — both the right term used AND the inconsistency raised), PO-30 (Copilot Studio backlog review), PO-31 (batch criteria drafting — COULD, only if every MUST is genuinely done). DoD: product feedback raised in a Teams channel reaches the backlog with its citation intact.

**D29 — Harden and measure ◆ Gate G3.** PO-32 (full 10-case harness run), PO-33 (fix the worst finding), PO-34 (edge-case pass — **the near-empty epic is the revealing test**), PO-35 (README/architecture/decision log from the code). DoD: the near-empty epic produces questions, not an invented product.

**D30 — Demo and programme close ◆ Gates G3/G4.** PO-36 (clean-clone verification), PO-37 (walkthrough with a live citation click-through), PO-38 (gate review), PGM-01 (consolidated eval report, spine published internally, cross-agent demo: P1's outcome record consumed by both P2 and P3, shared nudge cap holding).

**Gate G3 evidence:** all 7 MUST capabilities end to end; 10 golden cases committed; live citation click-through works; clean clone verified. **Gate G4 evidence:** consolidated eval report across all three agents; spine published internally; cross-agent demo holding, or a documented reason why the three ship separately.


---

## 5. Decision gates — quick reference

| Gate | When | Cut rule if it doesn't pass |
|---|---|---|
| G0b | W1 D1 | Proceed on the mock adapter regardless; escalate consent, don't wait |
| G0 | W1 D4 | STOP AND FIX — no summary/publishing/nudges until the ledger is right |
| G1 | W2 D10 | Cut C9 (weekly trend), then C11 (escalation), before degrading C1–C8 |
| G1b | W3 D13 | STOP AND FIX — no risk log until reference-or-drop holds |
| G2 | W4 D20 | Cut P9 (weekly status) before degrading P3 |
| G2b | W5 D23 | STOP AND FIX — open-question recall can't be retrofitted |
| G3 | W6 D29 | Cut O10/O11 before degrading O1–O9 |
| G4 | W6 D30 | If the cross-agent demo won't hold, ship the three agents separately and record why |

## 6. Golden cases — 31 total (12 + 9 + 10)

P1: GC1 detection precision/recall (≥0.80) · GC2 non-responder exact match (headline) · GC3 citation rate (≥0.95) · GC4 fabrication probe (0) · GC5 scope gate (0, hard zero) · GC6 publish idempotency (exactly 1) · GC7 nudge cap/order · GC8 approval enforcement · GC9 determinism · GC10 ingest correctness · GC11 weekly arithmetic · GC12 config-is-config.

P2: GC1 citation rate (≥0.90) · GC2 fabrication probe (headline, 0) · GC3 delta correctness · GC4 gap precision/no-duplicate · GC5 promotion threshold · GC6 approval enforcement · GC7 shared nudge cap/order · GC8 scope/consent refusal · GC9 determinism.

P3: GC1 citation resolution (0 unresolvable) · GC2 open-question recall (headline, 3/3 + 0 invented) · GC3 generic-story rate (<0.10 after guard) · GC4 decomposition coverage/redundancy · GC5 readiness accuracy (4/4) · GC6 prioritisation reproducibility · GC7 overlap detection · GC8 thin-epic behaviour · GC9 approval/status floor · GC10 glossary consistency.

## 7. Risk register — condensed

The two that decide whether P1 ever goes live: **R1** Graph access gated behind admin consent (mitigated by CHN-01's day-1 spike + mock-adapter fallback — currently live, escalated to Alfred) and **R2** naming colleagues wrongly gets the agent switched off permanently (mitigated by the three honest states, exceptions list, nudges off by default, GC2 as exact-match). Others worth remembering: **R6** D10 carries harden+document+demo in one day (no feature work after D9; borrow a day from P2 if needed, it sits under capacity); **R8** seed data is the most commonly underestimated task (a full day budgeted per agent — already proved out on P1, where D3 alone needed real iteration); **R11** spine copy-pasted between agents (mitigated by extraction at G1, hardening at G2); **R12** two agents chasing the same person the same day (mitigated by the shared nudge cap, tested by GC7 in both P1 and P2).

## 8. Submission checklist — per agent (produced 3×)

Public git repo with daily commits · README with an honest Done/Partial/Not-built status table, written last from the code · setup verified from a clean clone (.env.example, one install/seed/run command, exact model stated) · one-page architecture note (components, data flow, approval gate, adapters/mocks) · adapter interfaces + mocks with realistically messy data · eval harness + committed results · decision/assumption log (daily) · recorded 5–10 min walkthrough with one edge case shown · sample data in the repo, reproducible. Optional and unscored: deployed URL, container/compose setup, stretch work (only after every MUST is done).

The README status table is the item most often skipped and the one that most changes how a submission is read: a capability honestly marked Partial is graded as partial; the same gap marked Done is graded as misrepresentation and ends the evaluation regardless of build quality.

## 9. Tool doctrine — one-line reminders

Claude Code writes everything. Microsoft Graph reads Teams (permission model settled day 1). Power Automate writes into Teams (read and write are separate adapters on purpose). Copilot Studio + Dataverse is the human approval surface in Teams; Streamlit/CLI is the scored fallback and must be built first. Every correctness guarantee (non-responder arithmetic, participation states, nudge caps, scope gating, citation resolution, prioritisation scoring, DoR evaluation, idempotency) is **Python only — no model, no low-code, no exceptions**. Facts are computed in code; the model only writes the sentence expressing them.

---

## 10. Immediate next step

1. **Resolve §0** — confirm sheet 06's 15 planted difficulties are authoritative, then rebuild CHN-07's difficulty section and `labels.csv` against that exact list (including the corrections: reaction-only = zero messages, departed-member direction flipped, thread-reply-only update, posting-on-behalf-of-another, configured holiday, ambiguous @mention, and verified edit/delete timing). Re-run the full test suite and re-verify message counts stay in the 150–250 range.
2. Push the current 4 local commits to origin whenever ready (currently held back at the user's request).
3. Start D4: CHN-08 (deterministic rules) → CHN-09 (classifier) → CHN-10 (participation ledger) → SPN-05 (prompt registry). This is Gate G0 — the most important correctness gate in P1, and it depends directly on CHN-07's hand labels being right.
4. CHN-01 (Graph admin consent) stays a background item — check in on Alfred periodically, but per G0b's own cut rule, nothing on the build path waits for it.
