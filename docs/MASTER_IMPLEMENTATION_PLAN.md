# Incubation Pod — Master Implementation Plan (Complete Reference)

Single builder, six weeks, three agents, ten days each — P1 Teams Channel Intelligence (W1–2) → P2 PM Delivery Steward (W3–4) → P3 PO Backlog Architect (W5–6). This is the complete, non-lossy reconciliation of all nine source sheets (Master WBS, Schedule & Gates, Tool Split, Traceability, Eval Plan, Seed Data, Adapters, Risks, Deliverables): a readable day-by-day build plan up front (§§2–4), every reference table in full (§§5–13) rather than condensed, and the nine source sheets reproduced verbatim in the appendix so nothing from the original material is lost.

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
| SPN-02 LLM gateway | **Done** | `LLMGateway.generate()` — single call site, provider swap via `LLM_PROVIDER`, on-disk cache by request hash, tenacity backoff + degrade-to-Ollama, JSONL call log (test for this was written but uncommitted until this session — now fixed) |
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

Git state: 5 local commits beyond CHN-05 (`CHN-06`, `CHN-07`, the SPN-02 test fixup, the `.gitignore` cleanup, this master plan doc), **not yet pushed to origin** — held locally at the user's request. 37 tests passing, ruff clean.

Not started: everything from SPN-05 onward (prompt registry) through the rest of P1, and all of P2 and P3.


---

## 2. Full day-by-day plan, P1 (W1–2, D1–D10)

Reconciled from the Schedule & Gates sheet and the Master WBS. Each day names its WBS task IDs and its end-of-day definition of done. Full per-task detail (hours, dependencies, tool rationale, acceptance test wording) is in Appendix A (Master WBS, verbatim).

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

## 5. Decision gates — full detail (8 gates)

| Gate | When | Gate question | Evidence required to pass | Cut rule if it does not pass |
|---|---|---|---|---|
| G0b | W1 D1 | Graph access resolved | One real Teams channel message read in this tenant, or the blocker documented with the fallback selected and a consent request dated and outstanding | Proceed against the mock adapter regardless — it is the scored path. Escalate the consent request; do not wait on it |
| G0 | W1 D4 | Thin end-to-end slice — P1 participation ledger | A seeded day of channel messages produces a non-responder set matching hand labels, with the reaction-only, chatter-only and on-leave members each in the correct state | STOP AND FIX. Do not build the daily summary, publishing or nudges until the ledger is right. Everything else in P1 is a renderer over this |
| G1 | W2 D10 | P1 complete and demoable | All 8 MUST capabilities run end to end on the fixture; 12 golden cases print committed numbers; clean clone verified with no tenant credentials; walkthrough recorded; spine extracted as a package | Cut C9 weekly trend, then C11 escalation, before degrading C1–C8. Record the cut |
| G1b | W3 D13 | Thin end-to-end slice — P2 | A scheduled morning brief generates from a real snapshot with every factual line carrying a resolvable reference and the zero-activity assignee reported honestly | STOP AND FIX. Do not begin the risk log until reference-or-drop holds |
| G2 | W4 D20 | P2 complete and demoable | All 5 MUST capabilities run end to end; 9 golden cases print committed numbers; rejection path recorded on camera; clean clone verified; spine hardened | Cut P9 before degrading P3. Deltas are the differentiator |
| G2b | W5 D23 | Thin end-to-end slice — P3 | Acceptance criteria draft from a story with every citation resolving and all three planted gaps surfacing as open questions rather than invented rules | STOP AND FIX. Open-question recall is the headline metric and cannot be retrofitted |
| G3 | W6 D29 | P3 complete and demoable | All 7 MUST capabilities run end to end; 10 golden cases print committed numbers; live citation click-through works; clean clone verified | Cut O10 and O11 before degrading O1–O9 |
| G4 | W6 D30 | Programme close | Consolidated eval report across three agents; shared spine published internally; cross-agent demo showing a P1 channel outcome record consumed by both P2 and P3 through the published schema, with the shared nudge cap holding | If the cross-agent demo will not hold, ship the three agents separately and record why |

## 6. Golden cases — full detail (31 total: 12 + 9 + 10)

### P1 Channel (12)

| Case | Name | What is measured | Target | Built on | Note |
|---|---|---|---|---|---|
| GC1 | Update-detection precision and recall | Precision and recall of update-vs-not against hand labels, per class | ≥0.80 precision | D5 | Recall matters less than precision: a missed update is a nuisance, a false "no update" names an innocent person |
| GC2 | Non-responder accuracy | Exact set match across all three participation states | Exact match | D5 | THE headline number. Reaction-only, chatter-only and on-leave members must each land in the right state |
| GC3 | Citation rate | Proportion of factual summary lines carrying a resolvable message ID | ≥0.95 | D6 | Higher than the typical 0.90 because message IDs are exact — no excuse for an unresolvable reference |
| GC4 | Fabrication probe | Lines claiming a message, author, decision or blocker absent from the store | 0 | D6 | A fluent channel summary nobody can verify is worse than no summary, because it will be believed |
| GC5 | Scope gate | Messages in the store from non-allowlisted channels or any chat | 0 | D5 | Hard zero. The one failure that ends the agent's life in the organisation |
| GC6 | Publish idempotency | Digests per channel per day after running the job three times | Exactly 1 | D7 | The write log must also show the two suppressed attempts |
| GC7 | Nudge cap, exclusions, escalation order | Nudges per person per day; excluded members nudged; nudge before escalation | ≤cap / 0 / correct | D9 | Nudging someone on annual leave is the fastest way to have the agent switched off |
| GC8 | Approval enforcement | Nudge, escalation, first publish attempted for pending/rejected proposals | All fail | D9 | Tested directly against the service layer, not through the interface |
| GC9 | Determinism of facts | Factual divergence across two summary generations from the same window | 0 | D6 | Wording may differ; the participation set, contributors and counts must not |
| GC10 | Ingest correctness | Edited, deleted, bot and system messages handled correctly across two delta runs | All correct | D5 | The deleted-only-update case is the one that most easily produces a false accusation |
| GC11 | Weekly arithmetic reproducibility | Every figure in the weekly roll-up recomputable from stored messages | All | D8 | Includes the week containing a non-working day |
| GC12 | Configuration is really configuration | Non-responder set for the same day under two different rosters/windows | Moves correctly | D9 | Proves the roster and window are not hard-coded — the specific thing the request asked for |

### P2 PM (9)

| Case | Name | What is measured | Target | Built on | Note |
|---|---|---|---|---|---|
| GC1 | Citation rate | Proportion of factual brief/summary lines with a resolvable reference | ≥0.90 | D13 | A reference that does not resolve to a real seeded item counts as a failure, not a citation |
| GC2 | Fabrication probe | Lines claiming a transition, commit or message absent from the snapshot | 0 | D13 | THE headline number. Includes the zero-activity assignee and the empty day |
| GC3 | Delta correctness | Precision/recall on the hand-labelled changed set, including the twice-moved item | 1.0 / 1.0 | D12 | Deltas are what make this agent more than a dashboard |
| GC4 | Gap-detection precision | Precision/recall on blockers missing from the risk log; duplicates after rejection | 1.0 / 1.0 / 0 | D15 | The reject-and-rerun assertion is the part most candidates miss |
| GC5 | Promotion threshold | Proposed set at a 2-day vs a 4-day threshold | Shrinks correctly | D15 | Proves the threshold is really configuration, not a literal |
| GC6 | Approval enforcement | Direct service-layer writes for pending/rejected proposals; audit completeness | Both fail / complete | D14 | Audit must answer who approved, when, and what was originally proposed |
| GC7 | Shared nudge cap and escalation order | Nudges per person per day counting P1's nudges too; nudge before escalation | ≤shared cap / correct | D17 | One person chased twice in a day by two different agents is the estate-level failure this catches |
| GC8 | Scope and consent refusal | Proposals from an outcome record lacking the flag; logged refusals | 0 / 1 | D17 | The scope flag carried forward from P1 stops out-of-scope content reaching the tracker |
| GC9 | Determinism of facts | Factual divergence across two generations from the same snapshot | 0 | D16 | Wording may differ; items, owners, counts and statuses must not |

### P3 PO (10)

| Case | Name | What is measured | Target | Built on | Note |
|---|---|---|---|---|---|
| GC1 | Citation resolution | Citations not resolving to a real specific section | 0 | D22 | A citation pointing at the whole document counts as unresolvable |
| GC2 | Open-question recall (fabrication probe) | Planted gaps surfaced as open questions; criteria asserting a value for them | 3 of 3 / 0 | D23 | THE single most important number in the P3 submission |
| GC3 | Generic-story rate | Hand-labelled generic rate, before and after the anti-generic guard | <0.10 after | D25 | The before-and-after measurement is worth more than the guard itself |
| GC4 | Decomposition coverage | Coverage of expected capabilities AND redundancy among generated stories | High / low, both reported | D24 | High coverage from twenty overlapping stories is not a pass |
| GC5 | Readiness gate accuracy | Agreement with four hand labels; specificity of each block reason | 4 of 4 / all specific | D25 | A general complaint does not count as a reason |
| GC6 | Prioritisation reproducibility | Hand-recomputed scores; rank direction under perturbation; dependency order | 3 of 3 / correct / held | D26 | Compute the score in code; use the model only for the rationale sentence |
| GC7 | Overlap detection | Precision/recall with the correct relationship type on the labelled set | 1.0 / 1.0 | D27 | Four genuinely distinct stories must NOT be flagged |
| GC8 | Thin-epic behaviour | Open-question count vs story count; invented product behaviour | Questions > stories / 0 | D26 | A confident, complete-looking backlog here is a failure, not a pass |
| GC9 | Approval and status floor | Writes from pending/rejected drafts; tag and status on written records | Both fail / AI-drafted, not-ready | D27 | The floor must be enforced in the write path, not the prompt |
| GC10 | Glossary consistency | Glossary term used over the planted variant; the inconsistency raised | Both pass | D28 | Using the right term while staying silent about the conflict is a partial pass only |

A harness that reveals a weakness you then explain scores higher than one reporting everything passing. Each agent's hardening day: run the full harness, fix the single worst finding, re-run, commit both numbers with a written explanation.


---

## 7. Risk register — full detail (14 risks)

| ID | Category | Risk | Likelihood | Impact | Mitigation | Trigger |
|---|---|---|---|---|---|---|
| R1 | Access | Microsoft gates bulk application-permission reads behind admin consent and protected-API approval, may meter them | High | High | CHN-01 day-1 spike; fallback chosen in advance (delegated ChannelMessage.Read.All via a service account); mock adapter means harness/CI/demo run with no tenant access at all | Day 1 DoD |
| R2 | People | Naming colleagues who haven't posted is management-visible; wrong once and the agent is switched off permanently | High | High | Three honest states, exceptions list honoured everywhere including nudges, nudges off by default, first nudge/escalation behind approval, neutral wording, GC2 as exact-match, written policy sign-off before switch-on | GC2, GC7, CHN-14 |
| R3 | Tooling | Copilot Studio work displaces the scored Python path, leaving a repo that can't run from a clean clone | High | High | Streamlit/CLI built first; Copilot Studio added on top in a capped 2h slot; harness never needs tenant access | Clean-clone check each Friday |
| R4 | Quality | Grounding kernel built late, weeks of digests ship unverified | High | Medium | SPN-06 lands W1 D5; every downstream capability wires into it; nothing ships without passing through it | W1 D5 DoD |
| R5 | Quality | Eval harness deferred to the last days of each agent | High | Medium | First golden cases land D5/D13/D22, before half the capabilities exist; harness framework built once in week 1 | Weekly metric commit |
| R6 | Schedule | D10 carries harden + document + demo in one day, because Graph access/ingestion hardening took a day the original scope didn't need | High | Medium | Accept the tight day, protect it: no feature work after D9. If G0 slips, cut C9 (weekly trend) first, then C11 (escalation). Alternatively borrow a day from P2 (under capacity) | Gate G0 on W1 D4 |
| R7 | Data | Teams streams are messier than a chat export: delta expiry, throttling, edits, deletes, bot/system posts all corrupt the ledger silently if mishandled | Medium | High | CHN-05 is a dedicated 3h task; GC10 is a hard assertion across two delta runs, not a proportion | GC10 |
| R8 | Schedule | Seed data underestimated; hand-planting difficulties and labelling takes longer than expected | Medium | High | A full day budgeted for the P1 fixture and labels, a day per agent thereafter; Claude drafts prose, difficulties placed by hand; P2 reuses P1's fixture rather than re-seeding | D3, D11, D21 DoD |
| R9 | Model | Free-tier rate limits stall an eval run, or daily classification cost grows with channel volume | Medium | Medium | Rules settle clear cases so the model sees only the residue; disk cache from day 1; Ollama fallback proven in week 1; token cost logged per run | W1 D1 (SPN-02) |
| R10 | Honesty | README drifts ahead of the code as weeks compress | Medium | High | README written LAST from the code, Done/Partial/Not-built table; overstating is an automatic failure | D10, D19, D29 |
| R11 | Continuity | Spine copy-pasted between agents instead of reused, tripling maintenance | Medium | Medium | Extracted into an installable internal package at G1 with its own tests, hardened again at G2; P2 inherits two of its five adapters from P1 | CHN-33, PM-40 |
| R12 | Estate | Two agents each politely chasing the same person the same day, making the estate a nuisance | Medium | Medium | One shared per-person daily nudge cap across P1 and P2, tested by GC7 in both | GC7 in P1 and P2 |
| R13 | Single point of failure | One individual across six consecutive weeks; illness or leave stops the programme | Medium | High | Commit daily so state is recoverable; keep the decision log current; each agent independently demoable at its own gate | Daily commits |
| R14 | Demo | Recording left to the final afternoon and something breaks | Low | High | Clean-clone verification is a separate task before recording; recording runs against the mock adapter, immune to tenant/network problems | D10, D20, D30 |

R1 (Graph access) and R2 (people-sensitivity) are the two that decide whether P1 ever goes live.

## 8. Rubric — the 9 weighted criteria (sum to 100)

Functional coverage — 28 · Grounding — 12 · Eval harness — 12 · HITL gating — 10 · Architecture — 10 · Robustness — 8 · Repo hygiene — 8 · Demo quality — 8 · Judgement — 4.

The eval harness and its 31 golden cases are weighted above the user interface (12 points), which is why golden cases land on the day named in the WBS rather than at the end. Functional coverage is by far the largest single weight (28), which is why MUST-priority capabilities are never degraded ahead of SHOULD/COULD ones under a gate's cut rule.


---

## 9. Adapter interfaces and mocks — full detail (8 interfaces)

Test applied to each: could a real integration be dropped in by writing one class and changing one wiring line? Empty adapter files are worse than missing ones — an empty file implies a capability that doesn't exist and is an automatic-failure condition. Mock writes must always be persisted and inspectable (a table, a JSONL log, a diff).

| Interface | Operations | Mock implementation | Used by | Built | Mock messiness required |
|---|---|---|---|---|---|
| Teams reader (READ) | `list_channels()`, `list_channel_members(channel_id)`, `list_messages(channel_id, since\|delta_token)`, `list_replies(message_id)`, `get_permalink(message_id)` | `MockTeamsReader` over the committed fixture; `GraphTeamsReader` behind the identical interface | P1 (C2,C3,C4,C5), P2 (P1 chat source) | W1 D2 (CHN-03) | Edited/deleted messages, bot/connector posts, system messages, thread replies, similar display names, a member who has left the tenant |
| Teams publisher (WRITE) | `post_channel_message(channel_id, card)`, `post_direct_message(user_id, text)` | `LogPublisher` — JSONL log, no network egress; real impl posts via an HTTP-triggered Power Automate flow | P1 (C7,C10,C11), P2 (P2,P3,P7) | W2 D8 (CHN-22) | Read and write are deliberately separate adapters — a read credential must never post as anyone |
| Channel config store | `get_channel_config(channel_id)`, `list_configured_channels()`, `version()` | Committed YAML as system of record; Dataverse table as the owner-editable surface, reconciled not duplicated | P1 (C1), P2 (P6 thresholds), P3 (O4 checklist) | W1 D2 (CHN-02) | A roster containing a departed member; a channel with no exceptions list; two channels in different timezones |
| Tracker | `list_items(filter)`, `get_item(id)`, `add_comment(id, body, tags)`, `create_item(payload)`, `transition(id, status)` | `MockTracker` over a seeded SQLite table; every write appended to an inspectable write log. No real implementation in these six weeks | P2 (P1,P4,P5,P8), P3 (O1,O9) | W3 D11 (PM-04) | Missing assignee, stale timestamp, duplicate item, free-text status, no due date |
| Code host | `list_commits(since)`, `get_commit(sha)`, `get_branch_state(ref)` | `MockCodeHost` over a seeded commit fixture, some commits referencing no item | P2 (P1,P3) | W3 D11 (PM-04) | Commits with no item reference; one item referenced by a commit but never transitioned |
| Risk log store | `list_risks()`, `get_risk(id)`, `create_risk(payload)`, `update_risk(id, payload)` | Dataverse table for the human-facing view plus a committed JSON mirror as system of record | P2 (P4,P6,P8) | W3 D14 (PM-15) | Three pre-existing entries, two of which match current blockers |
| Document store | `get_document(id)`, `list_sections(doc_id)`, `get_section(ref)` | `MockDocStore` over the committed product brief and glossary, addressable to paragraph level | P3 (O1,O3,O6) | W5 D22 (PO-08) | One term inconsistent with the glossary; three deliberate silences |
| Outcome record store | `write_outcome(channel_id, date, record)`, `read_outcome(channel_id, date)`, `schema_version()` | Versioned JSON files with a published JSON Schema — **the cross-agent contract** | P1 (C12) produces; P2 (P8) and P3 (O10) consume | W2 D9 (CHN-26) | Carries the scope/consent flags forward; approved and classified items only |

Do not wire Copilot Studio connectors to a real Jira, SharePoint or Teams data source during these six weeks — a real SaaS integration earns no extra marks; a clean, swappable mock earns full marks. Teams is the one real integration in the programme.

## 10. Capability traceability — full detail (48 rows)

Every capability, its golden case, metric, target, the WBS tasks that build it, and the rubric criterion it feeds.

### P1 Channel

| Cap | Priority | Capability | Golden case | Metric | Target | WBS tasks | Rubric |
|---|---|---|---|---|---|---|---|
| C1 | MUST | Channel registry and per-channel configuration | GC12 | Non-responder set under two different configs | Moves correctly | CHN-02, CHN-24 | Functional coverage |
| C2 | MUST | Teams ingestion via Graph with delta tracking | GC10 | Edits/deletes/bot/system across two delta runs | All correct | CHN-01, CHN-03, CHN-05, CHN-12 | Functional coverage |
| C3 | MUST | Scope gate — allowlist only, chats never read | GC5 | Out-of-scope messages in the store | 0 | CHN-04, CHN-12 | HITL gating |
| C4 | MUST | Update detection — rules then classifier | GC1 | Precision/recall vs hand labels | ≥0.80 / reported | CHN-08, CHN-09, CHN-11 | Functional coverage |
| C5 | MUST | Participation ledger and non-responder detection | GC2 | Exact set match, three states | Exact | CHN-10, CHN-11, CHN-14 | Functional coverage |
| C6 | MUST | Per-channel daily summary with grounding | GC3 | Factual lines with resolvable message ID | ≥0.95 | SPN-06, CHN-13, CHN-15 | Grounding |
| C6 | MUST | (same) | GC4 | Lines claiming absent message/author/decision | 0 | CHN-14, CHN-15 | Grounding |
| C6 | MUST | (same) | GC9 | Factual divergence across two generations | 0 | CHN-16 | Eval harness |
| C7 | MUST | Scheduled daily and weekly publishing | GC6 | Digests per channel per day across three runs | Exactly 1 | CHN-17, CHN-18 | Functional coverage |
| C8 | MUST | Approval gate and audit for outbound actions | GC8 | Nudge/escalation/publish from pending-rejected | All fail | SPN-08, SPN-09, CHN-24 | HITL gating |
| C9 | SHOULD | Weekly roll-up with participation trend | GC11 | Figures recomputable from stored messages | All | CHN-19, CHN-20 | Grounding |
| C10 | SHOULD | Nudge non-responders, opt-in and capped | GC7 | Nudges/person/day; excluded members nudged | ≤cap / 0 | CHN-21, CHN-22, CHN-24 | Functional coverage |
| C11 | SHOULD | Escalate to the channel owner | GC7 | Nudge precedes escalation; threshold respected | Correct | CHN-23, CHN-24 | Functional coverage |
| C12 | SHOULD | Emit versioned outcome record | Schema round-trip | Day reconstructed without the message store | Pass | CHN-26 | Architecture |
| C13 | COULD | Cross-channel question answering | Not planned | — | Not built | — | Judgement |
| C14 | COULD | Per-person digest | Not planned | — | Not built | — | Judgement |

### P2 PM

| Cap | Priority | Capability | Golden case | Metric | Target | WBS tasks | Rubric |
|---|---|---|---|---|---|---|---|
| P1 | MUST | Read project state through adapters | GC3 (input) | Two snapshots diffable | Pass | PM-04, PM-05 | Functional coverage |
| P2 | MUST | Morning brief | GC1 | Factual lines with a resolvable reference | ≥0.90 | PM-08, PM-09, PM-12 | Grounding |
| P2 | MUST | (same) | GC2 | Fabricated-claim count | 0 | PM-10, PM-12 | Grounding |
| P2 | MUST | (same) | GC9 | Factual divergence across two runs | 0 | PM-23 | Eval harness |
| P3 | MUST | End-of-day summary | GC3 | Precision/recall on the delta set | 1.0 / 1.0 | PM-06, PM-07, PM-22 | Functional coverage |
| P4 | MUST | Risk-log gap detection | GC4 | Precision/recall/duplicates after reject | 1.0 / 1.0 / 0 | PM-15, PM-16, PM-17, PM-18 | Functional coverage |
| P5 | MUST | Approval gate for all writes | GC6 | Writes from pending/rejected proposals | Both fail | SPN-08, SPN-09, PM-13, PM-14 | HITL gating |
| P6 | SHOULD | Blocker-to-risk promotion | GC5 | Proposed set at 2-day vs 4-day threshold | Shrinks correctly | PM-19, PM-20 | Functional coverage |
| P7 | SHOULD | Commitments, nudges, escalation | GC7 | Nudges/person/day across BOTH agents | ≤shared cap | PM-24, PM-25 | Functional coverage |
| P8 | SHOULD | Consume a channel outcome record | GC8 | Proposals from a flagless record / refusals | 0 / 1 | PM-26, PM-27 | HITL gating |
| P9 | SHOULD | Weekly status report | Quant. reproducibility | Figures recomputable from snapshots | All | PM-29, PM-30 | Grounding |
| P10 | COULD | Sprint planning pack | Not planned | — | Not built | — | Judgement |
| P11 | COULD | Delivery narrative | Not planned | — | Not built | — | Judgement |

### P3 PO

| Cap | Priority | Capability | Golden case | Metric | Target | WBS tasks | Rubric |
|---|---|---|---|---|---|---|---|
| O1 | MUST | Load and index product context | GC1 (input) | Section refs hand-checkable | Pass | PO-06, PO-08 | Grounding |
| O2 | MUST | Decompose an epic into stories | GC4 | Coverage/redundancy | High/low, both reported | PO-13, PO-14 | Functional coverage |
| O2 | MUST | (same) | GC8 | Open questions vs stories | Questions > stories | PO-23 | Functional coverage |
| O3 | MUST | Draft acceptance criteria | GC2 | Planted gaps surfaced / invented specifics | 3 of 3 / 0 | PO-10, PO-12 | Grounding |
| O3 | MUST | (same) | GC10 | Glossary term used / inconsistency raised | Both pass | PO-29 | Grounding |
| O4 | MUST | Definition of Ready gate | GC5 | Agreement with 4 labels / specific reasons | 4 of 4 / all specific | PO-17, PO-18 | Functional coverage |
| O5 | MUST | Prioritise the backlog | GC6 | Hand-recompute/perturbation/dependency | 3 of 3 / correct / held | PO-20, PO-21, PO-22 | Functional coverage |
| O6 | MUST | Grounding and citation enforcement | GC1 | Unresolvable-citation count | 0 | PO-07, PO-09, PO-11 | Grounding |
| O7 | SHOULD | Duplicate and overlap detection | GC7 | Precision/recall, correct relationship type | 1.0 / 1.0 | PO-24, PO-25 | Functional coverage |
| O8 | SHOULD | Anti-generic guard | GC3 | Rate before/after the guard | <0.10 after | PO-15, PO-16 | Functional coverage |
| O9 | MUST | Draft back to the tracker | GC9 | Records after 2 approvals+2 re-runs / tag / status | 2 / AI-drafted / not-ready | PO-26, PO-27 | HITL gating |
| O10 | SHOULD | Synthesise stakeholder input | Consent refusal test | Items from a consentless record | 0 | PO-28 | HITL gating |
| O11 | COULD | Batch criteria drafting | Flagged-only test | Stories drafted vs flagged | Exact match | PO-31 | Functional coverage |
| O12 | COULD | Release notes draft | Not planned | — | Not built | — | Judgement |

Deliberate scope decision: C13, C14, P10, P11 and O12 are COULD rows, not planned inside the six weeks (the Traceability sheet's own header says "four" but lists these five — a stale-artifact note, not a build decision). Each must be recorded in the relevant README's Not-built column with one sentence on how it would be approached. O11 is attempted on D28 only if every MUST is genuinely complete.


---

## 11. Tool split — full detail (13 decisions)

Governing principle: Copilot Studio owns the human surface, Claude owns language, plain Python owns every correctness guarantee.

| Concern | Tool | Why | Constraint |
|---|---|---|---|
| Build engine — all code, tests, harness, docs | Claude Code | Writes/refactors Python, generates the eval harness, drafts README and architecture notes from the actual repo | Declare AI-assistant use in the README; be able to explain every file |
| Reading Teams messages | Microsoft Graph behind an adapter interface | Only Graph gives message IDs, permalinks, thread replies, edit history, delta tracking | Permission model is a day-1 spike (CHN-01); nothing downstream validates until it's settled |
| Writing into Teams | Power Automate flow bot behind a publish adapter | Graph app permission to send is restricted; an HTTP-triggered flow bot is straightforward | Read and write are separate adapters on purpose — a read credential must never post |
| Update-vs-chatter classification | Deterministic rules first, Claude API for the remainder | Rules settle clear cases free and auditably; the model only handles judgement calls | Every rule-settled case is a token not spent and a decision no reviewer can dispute |
| Roster, windows, thresholds, exceptions | Python config schema + Dataverse surface | A non-responder claim is only as defensible as the roster behind it; the channel owner maintains it without a deploy | The committed YAML mirror stays the system of record so the harness runs reproducibly offline |
| Non-responder arithmetic, participation states, nudge caps, escalation triggers | Python only — no model, no low-code | Naming a colleague silent must be set arithmetic over an explicit roster and window | MANDATORY, whatever the adoption pressure |
| Quote verification, citation resolution, delta arithmetic, prioritisation scoring, DoR evaluation, idempotency, scope gating | Python only — no model, no low-code | Every one of these is a correctness guarantee | MANDATORY, same rule |
| Prose expression of computed facts | Claude API | The model writes the sentence; facts/ledgers/deltas/scores are computed in code and passed in | This split lets a digest regenerate without factual drift |
| Evaluation harness, golden cases | Python script, committed results | Weighted 12/100 in every rubric, above the UI; must run from one command against mocks | Must never need tenant access, or CI becomes impossible |
| Human review / approval — primary | Copilot Studio + Power Automate + Teams adaptive cards | Approving a nudge to a named colleague belongs where that colleague works | Enforcement stays in the Python service layer — Copilot Studio is one of two heads on the same API |
| Human review / approval — scored fallback | Streamlit or CLI | Keeps the repo runnable from a clean clone, zero licensed software, no tenant | Build this first. Copilot Studio is added on top, never instead |
| Scheduling | APScheduler in code + Power Automate recurrence | A real scheduler must exist in code with a clock override for demos | Power Automate is the organisational trigger; it calls the same job the code exposes, never replaces it |
| Tracker, code host, document store | Python adapter interface + mock only | A real SaaS integration earns no extra marks; a clean swappable mock earns full marks | Teams is the one real integration in this programme — do not add a second |

## 12. Submission checklist — full detail (9 required + 3 optional, per agent, ×3)

| Required? | Deliverable | What must be there | When | WBS task (P1 / P2 / P3) |
|---|---|---|---|---|
| Required | Public git repository | Full source committed incrementally. History is part of the assessment — one large commit at the end is a red flag | Daily | All |
| Required | README with an honest status table | One row per capability, Done/Partial/Not built, one-line note. Written LAST, from the code | D10/D19/D29 | CHN-30, PM-36, PO-35 |
| Required | Setup verified from a clean clone | One install command, one seed command, one run command, `.env.example`, exact model/version stated | D10/D20/D30 | CHN-31, PM-38, PO-36 |
| Required | Architecture note | One page/diagram: components, data flow, approval gate, adapters and what they mock | D10/D19/D29 | CHN-30, PM-37, PO-35 |
| Required | Adapter interfaces plus mocks | One interface per external system, each with a mock returning realistically messy data | Ongoing | See §9 |
| Required | Evaluation harness plus committed results | Script running golden cases, printing per-metric scores, plus the final results file | D9/D19/D29 | CHN-27, PM-34, PO-32 |
| Required | Decision and assumption log | Scope cuts, ambiguous-requirement assumptions, known limitations. Bullets fine, brevity fine | Daily | All gate tasks |
| Required | Recorded walkthrough, 5–10 min | A genuine end-to-end run including one edge case or failure handled. No slides | D10/D20/D30 | CHN-32, PM-39, PO-37 |
| Required | Sample data used | The seed data in the repo so the run is exactly reproducible | D2/D11/D21 | See §0/sheet 06 |
| Optional | Deployed public URL | Not scored | — | — |
| Optional | Container/compose setup | Helpful, not required | D1 | SPN-01 |
| Optional | Stretch work | Only after every MUST is genuinely done; noted separately | D28 | PO-31, PGM-01 |

The README status table is the item most often skipped and the one that most changes how a submission is read: a capability honestly marked Partial is assessed as partial; the same capability implied complete is assessed as misrepresentation — which ends the evaluation regardless of build quality. It costs fifteen minutes.

## 13. Effort and capacity

30 working days × 8 hours = 240 hours capacity; no day exceeds 9. Total planned: 239.0 hours.

Hours by agent — P1 Channel Intelligence: 63.5 · P2 PM Delivery Steward: 76.0 · P3 PO Backlog Architect: 76.0 · Shared spine: 23.5.

Hours by priority — MUST: 186.5 · SHOULD: 50.5 · COULD: 2.0.

Weeks 1–2 run at full capacity (84 hours) because the shared spine is built there; weeks 3–4 and 5–6 sit under capacity because they reuse it — that front-loading is the point of the sequence, and it's why P2 has slack to absorb a borrowed day if P1's Gate G0 slips (R6).


---

## 14. Immediate next step

1. **Resolve §0** — confirm sheet 06's 15 planted difficulties are authoritative, then rebuild CHN-07's difficulty section and `labels.csv` against that exact list (including the corrections: reaction-only = zero messages, departed-member direction flipped, thread-reply-only update, posting-on-behalf-of-another, configured holiday, ambiguous @mention, and verified edit/delete timing). Re-run the full test suite and re-verify message counts stay in the 150–250 range.
2. Push the current local commits to origin whenever ready (currently held back at the user's request).
3. Start D4: CHN-08 (deterministic rules) → CHN-09 (classifier) → CHN-10 (participation ledger) → SPN-05 (prompt registry). This is Gate G0 — the most important correctness gate in P1, and it depends directly on CHN-07's hand labels being right.
4. CHN-01 (Graph admin consent) stays a background item — check in on Alfred periodically, but per G0b's own cut rule, nothing on the build path waits for it.

---

# Appendix — Source sheets, verbatim

Everything below is reproduced exactly as originally provided, sheet by sheet, so nothing from the source material is lost even where §§0–14 above condensed or reorganised it. Each is wrapped in a code block to preserve the original text precisely.

## Appendix A — Sheet guide overview (front matter)

```
Incubation Pod — Three-Agent Delivery Plan
P1 Teams Channel Intelligence · P2 PM Delivery Steward · P3 PO Backlog Architect. Single builder, two weeks per agent, six weeks end to end. Toolset: Claude (Code + API) and Microsoft Copilot Studio.

Topic | Decision | Why / what it means in practice
What P1 is
P1 Teams Channel Intelligence | Reads allowlisted Teams channels; summarises each one; tracks who has and has not posted an update; publishes daily and weekly | Re-scoped from the original meeting-transcript brief. Audio and transcript ingestion is gone entirely. The agent now reads channel messages through Microsoft Graph, decides which messages count as updates, keeps a participation ledger against a per-channel roster, publishes a daily digest and a weekly roll-up back into the channel, and optionally nudges non-responders and escalates to the channel owner.
Per-channel configuration | Roster, update window, timezone, working days, what counts as an update, digest times, nudge on/off, nudge cap, escalation threshold, channel owner, exceptions list | Held as versioned configuration with a Dataverse surface so the channel owner maintains their own roster in Teams. Every non-responder claim is only as defensible as the roster behind it, so the config is a first-class capability (C1), not a settings file.
The three participation states | Posted no message · posted but no update · excluded by the exceptions list | Never collapsed into one 'silent' list. This is the single most important design decision in P1: the output names colleagues to their manager, so the difference between 'said nothing' and 'chatted but did not report' and 'on annual leave' has to survive all the way to the page.

How this plan is shaped
Sequence | P1 Channel (W1–2) → P2 PM (W3–4) → P3 PO (W5–6) | P1's daily channel outcome record (C12) is the input P2 consumes (P8) and P3 reuses for stakeholder synthesis (O10). P1 also builds two adapters P2 inherits outright — the Teams reader and the publisher — and forces the hardest shared machinery into week 1: scope gating, reference-or-drop grounding, an approval queue, idempotent publishing and a shared nudge cap.
Shared spine | Ten components built once in weeks 1–2, reused by all three agents | LLM gateway, structured-output layer with retry, SQLite schema, adapter framework, proposal record, service-layer write guard, grounding kernel, prompt registry, eval harness framework, approval surface. Extracted into an installable internal package at gate G1 and hardened at G2. This is what makes agent three cost less than agent one.
Effort basis | 30 working days × 8 hours = 240 hours; no day exceeds 9 hours | Each agent gets 10 days. P1 carries the spine, so weeks 1–2 run at full capacity while weeks 3–4 and 5–6 sit under it.
Cadence per agent | Seed data → thin end-to-end slice → capabilities → harden → measure → demo | A thin end-to-end slice by day 3–4 of each agent, and evaluation started well before the hardening day. Gates G0, G1b and G2b enforce it and each names its cut rule.

Tool doctrine
Claude Code | The build engine for all six weeks | Writes the Python, the tests, the eval harness, and drafts the README and architecture note from the actual repository. Declare assistant use in the README and be able to explain every file.
Claude API | Classification, drafting and prose expression of computed facts | Always through one wrapper, always with a forced tool-use schema and a validate-and-retry loop. In P1 the model only sees messages the deterministic rules could not settle — that keeps a daily scheduled job cheap and keeps the audit defensible.
Microsoft Graph | Reading Teams channel messages | Only Graph gives message IDs, permalinks, thread replies, edit history and delta change tracking — and all four are what the grounding and the participation ledger depend on. The permission model is a day-1 spike (CHN-01) because it can block the agent.
Power Automate | Writing into Teams — digests, nudges, escalations | Graph application permission to SEND channel messages is restricted, while an HTTP-triggered flow posting as the flow bot is straightforward. Read and write are separate adapters on purpose: a read credential must never post as anyone.
Copilot Studio + Dataverse | The human surface: approval cards, per-channel config, brief and digest delivery | Approving a nudge to a named colleague, or a first digest into a live channel, belongs where that colleague works. The channel owner who knows the roster edits it in Teams, not in a YAML file — that is how the roster stays current and the non-responder list stays right.
Python, no model, no low-code | Every correctness guarantee | Non-responder set arithmetic, participation states, nudge caps, escalation triggers, scope gating, quote verification, citation resolution, snapshot deltas, prioritisation scoring, Definition-of-Ready evaluation, idempotency, and all metric computation. A guarantee that depends on a model or a low-code expression is not a guarantee.

Three constraints worth reading twice
Graph access can block P1, so it is settled on day 1 | CHN-01 — resolve the permission model before anything depends on it | Bulk application-permission reads of channel messages need admin consent AND Microsoft's protected-API approval, and may be metered. The fallback is chosen in advance: delegated ChannelMessage.Read.All via a dedicated service account that is a member of each allowlisted channel. Because the harness and the demo run entirely against the mock adapter, a consent delay slows go-live without stopping the build.
Naming people is the real risk, not the engineering | Three honest states · exceptions list · nudges off by default · first nudge and first escalation behind approval | This agent produces a management-visible list of named colleagues who did not post. Wrong once and it gets switched off permanently. So GC2 is an exact-set assertion rather than a proportion, the on-leave member is never nudged under any path, the wording carries no inferred reasons and no ranking of people, and a written policy sign-off precedes switch-on in any real channel.
The scored path must run without Copilot Studio or a tenant | Build the Streamlit or CLI surface first; the harness never needs Graph | A clean clone must install and run against the mock adapter with zero licensed software and no credentials. Copilot Studio is added on top in a capped 2 h slot per agent. Teams is the one real integration in this programme — tracker, code host and document store stay adapter-plus-mock, because a real SaaS integration there earns nothing.

Sheet guide
01 Master WBS | 119 tasks across 30 days | Each with a capability ID, workstream, tool assignment and the reason for it, dependency, estimate, acceptance test and the rubric criterion it feeds. Filter by Agent, Week or Priority; status dropdown and live hour rollups at the foot.
02 Schedule & Gates | Day-by-day focus and the eight decision gates | Each gate names its evidence and its cut rule.
03 Tool Split | Thirteen decisions on Graph vs Power Automate vs Copilot Studio vs Claude vs plain Python | Read this before starting any capability.
04 Traceability | Every capability → golden case → metric → target → tasks → rubric row | The coverage map. Five COULD rows are deliberately marked Not built.
05 Eval Plan | All 31 golden cases across the three agents | Built into the harness on the days named in the WBS, not at the end. All run against the mock adapter.
06 Seed Data | Seed artefacts and all planted difficulties | Twenty planted difficulties for P1 alone. Hand-place these — they are the ground truth for every metric.
07 Adapters | Eight interfaces, their operations and their mocks | Teams reader and publisher are deliberately separate. Includes the cross-agent outcome-record contract.
08 Risks | Fourteen risks with mitigations and the trigger that catches each | R1 Graph access and R2 people-sensitivity are the two that decide whether P1 ever goes live.
09 Deliverables | The submission checklist, per agent | Nine required items each; three optional items that are not scored.
```


## Appendix B — Master Work Breakdown (119 tasks), verbatim, part 1 of 3 (SPN + CHN)

```
Master Work Breakdown — 30 days, 3 agents
One row per task. 'Cap ID' maps to the capability IDs in the source briefs (M1–M13 Meeting, P1–P11 PM, O1–O12 PO). SPN rows are shared-spine components built once and reused by all three agents.

Task ID | Week | Day | Agent | Cap ID | Workstream | Task | What to build / what done means | Primary tool | Why this tool | Depends on | Est hrs | Acceptance test | Rubric criterion (weight) | Priority

SPN-01 | W1 | D1 | Shared | — | Platform | Repo scaffold and reproducible run | Git repo, uv or docker-compose, one install command, one seed command, one run command, .env.example, CI lint+test, empty decision log and README skeleton. | Claude Code | Claude Code writes the scaffold, Makefile and CI in one pass; nothing here benefits from a low-code surface. | — | 1.5 | Clean clone in a fresh directory installs and starts in under 5 documented steps. | 7 Repo hygiene (8) | MUST

SPN-02 | W1 | D1 | Shared | — | Platform | LLM gateway (single wrapper) | One call site for every model invocation. Provider swap by config: Claude API primary, local Ollama 3B-8B fallback. On-disk response cache keyed by prompt hash. Exponential backoff and an explicit rate-limit degradation path. Token and latency log per call. | Claude Code + Claude API | A single swappable call site is a rubric-5 architecture requirement and the only way to cap token spend on a daily scheduled job. | SPN-01 | 2.0 | Flip one config value and the same capability runs against the local model. Cache hit avoids a second API call. | 5 Architecture (10) | MUST

SPN-03 | W1 | D1 | Shared | — | Platform | Structured-output layer with retry-on-invalid | Pydantic models per capability. Schema-constrained decoding via Claude tool-use forced schema. Validate every response; on failure re-prompt with the validation error fed back, max N attempts, then surface as an exception - never a silent default. | Claude Code + Claude API | Hard requirement in the brief. Regex or string-split parsing loses marks in several rubric rows at once. | SPN-02 | 2.0 | Inject a deliberately malformed model response: it is caught, retried with the error fed back, and never silently defaulted. | 6 Robustness (8) | MUST

CHN-01 | W1 | D1 | P1 Channel | C2 | Access | GRAPH ACCESS SPIKE - resolve the permission model | CRITICAL PATH. Determine what the DigitalT3 tenant can actually grant for bulk channel message reads. Option A: delegated ChannelMessage.Read.All via a dedicated service account that is a member of each channel - no protected-API approval needed, but needs a token-refresh story. Option B: application permission ChannelMessage.Read.All - needs admin consent AND Microsoft's protected-API approval for Teams export, and may be metered. Register the app, request consent, and prove one real channel message can be read. Document the decision and the chosen fallback. | Azure app registration + Microsoft Graph | This can block the entire agent and nothing else on the critical path can be validated without it. It goes on day 1 for that reason alone, not because it is interesting. | — | 2.5 | One real Teams channel message is read through Graph in this tenant - or the blocker is documented with the fallback selected and a dated consent request outstanding. | 9 Judgement (4) | MUST

SPN-04 | W1 | D2 | Shared | — | Platform | SQLite schema and migrations | Visible schema file (not ad hoc at runtime) for channels, channel_config, members, messages, classifications, participation, digests, proposals, write_log, audit. FTS5 virtual table over message text. | Python + SQLite | Zero-setup and the schema stays readable in the repo. Dataverse is added later as a human-facing config surface, not the system of record. | SPN-01 | 1.5 | Schema exists as a committed migration; a fresh DB is built by the seed command alone. | 5 Architecture (10) | MUST

CHN-02 | W1 | D2 | P1 Channel | C1 | Config | Channel registry and per-channel configuration | Per channel: channel ID and display name, EXPECTED-CONTRIBUTOR ROSTER, update window (local time and working days), timezone, what counts as an update (length floor, whether thread replies count, whether bot posts are ignored), daily digest time, weekly digest day and time, nudge on/off, nudge cap per person per day, escalation threshold in consecutive missed days, channel owner for escalation, and an exceptions list for leave. Held as versioned configuration, never literals in code. | Python (YAML schema) + Dataverse surface | The roster and window ARE the product - every non-responder claim is only as defensible as the config behind it. Dataverse lets a channel owner maintain their own roster in Teams without a deploy. | SPN-04 | 2.5 | Two channels configured with different rosters, windows and timezones; changing one roster changes the non-responder set with no code change. | 1 Functional coverage (28) | MUST

CHN-03 | W1 | D2 | P1 Channel | C2 | Adapters | Teams read adapter - interface, mock and real Graph implementation | Narrow interface: list_channels, list_channel_members, list_messages(channel, since or delta), list_replies(message_id), get_permalink(message_id). MockTeamsReader over the seeded fixture for CI and the eval harness; GraphTeamsReader as the real implementation behind the identical interface. Factory chooses from config. | Python + Microsoft Graph | Mock keeps the harness reproducible and offline; the real implementation is what makes the agent go live. Same interface, one wiring line apart. | CHN-01, SPN-04 | 3.0 | The same capability code runs against the mock and against a real channel with only a config change. No Graph type appears in agent logic. | 5 Architecture (10) | MUST

CHN-04 | W1 | D2 | P1 Channel | C3 | Governance | Scope gate - allowlisted channels only, chats never read | Only channels on the explicit allowlist are read. One-to-one and group chats are excluded AT THE ADAPTER BOUNDARY, not filtered downstream. Any out-of-scope request produces a refusal record stating what was refused and why. Permission scope and admin consent documented in the repo. | Python (service layer) | Reading a colleague's chat is the one failure this agent must make structurally impossible, not merely unlikely. A downstream filter is not a gate. | CHN-03 | 1.0 | Zero messages from non-allowlisted channels or from any chat exist in the store after a full ingest; each refusal is logged. | 3 HITL gating (10) | MUST

CHN-05 | W1 | D3 | P1 Channel | C2 | Ingest | Ingestion hardening - delta, paging, throttling, edits and system noise | Delta-query change tracking with token persistence and expiry recovery. Pagination. Throttling: honour 429 and Retry-After with backoff. Handle edited messages (attributed to original post time), deleted messages, bot and connector posts, and system messages such as member joined or left. Store raw plus normalised with stable message IDs and permalinks. | Python + Microsoft Graph | Everything downstream is wrong if ingestion is wrong, and Teams message streams are far messier than a chat export. This is the least glamorous and most load-bearing task of week 1. | CHN-04 | 3.0 | Two consecutive delta runs produce a correct incremental set. An edited message keeps its original post time. A bot post counts as nobody's update. | 1 Functional coverage (28) | MUST

CHN-06 | W1 | D3 | P1 Channel | — | Seed data | Seed fixture - 3 channels, rosters, 10 working days of traffic | Two allowlisted project channels plus one channel deliberately NOT on the allowlist. One group chat and one one-to-one chat that must never be read. 150-250 messages over 10 working days including thread replies. Rosters of 6-8 members per channel with two members on both. | Claude (generation) + Python (fixture) | Claude drafts realistic standup chatter fast; the fixture is committed so every metric is reproducible. | CHN-05 | 2.5 | Seed command reproduces byte-identical state; the fixture covers weekends and one channel-silent day. | 1 Functional coverage (28) | MUST

CHN-07 | W1 | D3 | P1 Channel | — | Seed data | Plant the fifteen deliberate difficulties and write the labels file | See sheet 06 for the full list. Every planted case recorded in a committed labels file naming the message ID, the member and the expected outcome. | Human (Claude assists formatting) | These fifteen are the entire P1 golden set. A model that places its own difficulties measures nothing. | CHN-06 | 2.5 | Labels file committed with one row per planted difficulty and its expected classification or participation state. | 4 Eval harness (12) | MUST

CHN-08 | W1 | D4 | P1 Channel | C4 | Detection | Update detection - deterministic rules first | Auditable rules settle the clear cases: posted by a roster member, inside the configured window on a working day, above the length floor, not a reaction, not a bot or connector post, not a system message, thread replies counted per config. | Python (no model) | Rules are inspectable and free to run. Every case a rule can settle is a case no token is spent on and no reviewer can dispute. | CHN-07 | 2.0 | Each rule decision is traceable to the named rule and the message ID it fired on. | 1 Functional coverage (28) | MUST

CHN-09 | W1 | D4 | P1 Channel | C4 | Detection | Update detection - classifier for the remainder | Schema-constrained classification of the messages rules cannot settle: update / question / blocker / decision / chatter / noise, with a confidence and the message ID. Noise is discarded, not stored. Low-confidence items are surfaced as uncertain rather than forced. | Claude API (forced schema) | Judgement calls only. The model never sees a message a rule has already decided. | CHN-08 | 2.5 | A status-shaped message is labelled an update; a 'thanks, will look' reply is not. Uncertain cases are flagged, not guessed. | 1 Functional coverage (28) | MUST

CHN-10 | W1 | D4 | P1 Channel | C5 | Participation | Participation ledger and non-responder detection | Per channel per day: roster minus contributors within the window. THREE HONEST STATES, never collapsed into one: (a) posted no message at all, (b) posted but nothing that counts as an update, (c) excluded by the exceptions list. Never infers a reason for absence. | Python (set arithmetic) | This is the answer the user actually asked for, and it must be arithmetic over the roster and the window - not a model's impression of who was quiet. | CHN-09 | 2.5 | THIN END-TO-END SLICE: a seeded day yields a non-responder set matching hand labels, with the reaction-only, chatter-only and on-leave members each in the correct state. | 1 Functional coverage (28) | MUST

SPN-05 | W1 | D4 | Shared | — | Platform | Prompt registry | One prompt per capability in its own versioned file, loaded at runtime, tagged with a version string the eval harness records alongside every result. | Python + Claude Code | Inline prompt literals are a named anti-pattern and make prompt regression impossible. | SPN-03 | 1.0 | No prompt string literal exists outside the prompts directory (enforced by a lint test). | 5 Architecture (10) | MUST

SPN-06 | W1 | D5 | Shared | C6 | Grounding | Grounding kernel - reference-or-drop and verbatim quote verifier | Every factual line must carry a resolvable message ID; lines without one are removed or explicitly marked unsupported. Every quoted fragment must be a literal substring of the stored message. On failure, re-prompt with the failure fed back, then drop and log. Same module later enforces citation resolution for P2 and P3. | Python | The single highest-leverage artefact of the programme, reused by all three agents. A fluent summary nobody can verify is worse than no summary, because it will be believed. | SPN-05 | 2.0 | A hand-forged summary line with no message ID is dropped and logged; a near-miss quote is rejected and retried. | 2 Grounding (12) | MUST

SPN-07 | W1 | D5 | Shared | — | Eval | Eval harness framework | Golden-case loader, metric registry, per-metric line printer (measured value vs target), results written to a committed file, tagged with prompt version and model ID. Reused by P2 and P3 with new cases only. | Python + Claude Code | Weighted at 12 in every rubric, above the user interface. Most candidates skip it. | SPN-06 | 2.5 | Harness runs from one command and writes a results file naming metric, measured, target and pass/fail. | 4 Eval harness (12) | MUST

CHN-11 | W1 | D5 | P1 Channel | C4 | Eval | Golden cases 1 and 2 - detection and non-responder accuracy | GC1 update-detection precision and recall against hand labels (precision target >=0.80). GC2 non-responder set EXACT MATCH including the three participation states. | Python + human labels | GC2 is the headline number for this agent. Naming the wrong person as silent is the failure that gets the agent switched off. | SPN-07, CHN-10 | 2.5 | Both metrics printed and committed; GC2 is an exact-set assertion, not a proportion. | 4 Eval harness (12) | MUST

CHN-12 | W1 | D5 | P1 Channel | C3 | Eval | Golden cases 5 and 10 - scope gate and ingest correctness | GC5 zero out-of-scope messages in the store after a full ingest, target 0. GC10 edited, deleted, bot and system messages handled correctly across two delta runs. | Python | Both are hard-zero assertions rather than proportions. | CHN-11 | 1.0 | Both assertions pass; the non-allowlisted channel and both chats contribute nothing. | 3 HITL gating (10) | MUST

CHN-13 | W2 | D6 | P1 Channel | C6 | Reporting | Per-channel daily summary | Per channel: what moved, blockers raised, decisions taken, questions still awaiting an answer, then the participation section. Facts come from the ledger and the classifications; the model writes the prose only. Every factual line carries a message permalink. | Python (facts) + Claude API (expression) | Facts in code, prose from the model. This split is what lets the digest be regenerated without factual drift. | CHN-12 | 3.5 | A seeded day produces a summary in which every factual line resolves to a real message, and a channel with no traffic produces an honest empty summary. | 1 Functional coverage (28) | MUST

CHN-14 | W2 | D6 | P1 Channel | C5 | Grounding | Honest participation rendering | The three states rendered distinctly and without editorialising: 'no message posted', 'posted, but no update', 'excluded - on the exceptions list'. No inferred reasons, no adjectives, no ranking of people. | Python + prompt design | This section is read by managers about named colleagues. The wording is a design decision, not a formatting detail. | CHN-13 | 1.5 | The chatter-only member is never reported as having posted no message, and the on-leave member is never reported as silent. | 2 Grounding (12) | MUST

CHN-15 | W2 | D6 | P1 Channel | C6 | Eval | Golden cases 3 and 4 - citation rate and fabrication probe | GC3 proportion of factual summary lines carrying a resolvable message ID, target >=0.95. GC4 count of lines claiming a message, author, decision or blocker absent from the store, target 0. | Python | The citation target is higher than a typical 0.90 because message IDs are exact - there is no excuse for an unresolvable reference here. | CHN-14 | 2.0 | Both metrics printed and committed. | 2 Grounding (12) | MUST

CHN-16 | W2 | D6 | P1 Channel | C6 | Eval | Golden case 9 - determinism of facts | Generate a daily summary twice from the same message window. Wording may differ; the participation set, contributor list and counts must not. | Python | — | CHN-15 | 1.0 | Fact-set comparison across two generations prints zero divergences. | 4 Eval harness (12) | MUST

SPN-08 | W2 | D7 | Shared | C8 | Approval | Proposal record and status machine | First-class row: id, type, status (pending / approved / rejected / applied), payload, original_model_output retained separately from any human edit, source_refs, approver identity, created_at, decided_at, idempotency_key. Reused verbatim by P2 and P3. | Python + SQLite | The core abstraction of all three agents. Build once, well. | CHN-16 | 2.0 | An edited-then-approved proposal retains both the original model output and the applied payload. | 3 HITL gating (10) | MUST

SPN-09 | W2 | D7 | Shared | C8 | Approval | Service-layer write guard | Every outbound path - channel post, nudge, escalation - refuses any proposal not in status=approved, raising at the service layer regardless of caller. Documented timeout behaviour defaulting to not sending. | Python | Approval that is bypassable via the API is an automatic-failure condition in the rubric, and here it also means messaging real colleagues. | SPN-08 | 1.5 | An automated test calling each outbound path directly for a pending and a rejected proposal fails every time. | 3 HITL gating (10) | MUST

CHN-17 | W2 | D7 | P1 Channel | C7 | Publishing | Scheduled publishing, idempotent, per-channel local time | Real scheduler (APScheduler) with a clock override for demos, firing per channel at its own configured local time on working days only. Publishes into the channel, or a designated summary channel, via the publish adapter. Exactly one digest per channel per day, enforced by an idempotency key. FIRST PUBLISH PER CHANNEL REQUIRES APPROVAL; subsequent days run unattended. | Python (APScheduler) + Power Automate publish | A button labelled 'run the digest' is a test harness, not a scheduler. First-publish approval means no channel ever receives an unexpected bot post. | SPN-09 | 3.0 | A clock-override run at three different channel-local times produces three correctly timed digests and no duplicates. | 1 Functional coverage (28) | MUST

CHN-18 | W2 | D7 | P1 Channel | C7 | Eval | Golden case 6 - publish idempotency | Run the daily job three times over the same day. Assert exactly one digest exists per channel, and that the write log shows the two suppressed attempts. | Python | — | CHN-17 | 1.5 | Assertion passes and the suppressed attempts are visible. | 1 Functional coverage (28) | MUST

CHN-19 | W2 | D8 | P1 Channel | C9 | Reporting | Weekly roll-up with participation trend | Per channel per week: participation rate per member, trend against the prior week, recurring blockers, the week's decisions, and questions that went unanswered all week. Every quantitative claim recomputable from stored messages. | Python (arithmetic) + Claude API (narrative) | Rates and trends are computed, never estimated by a model. The narrative sentence is the only generated part. | CHN-18 | 3.0 | Every figure in the weekly roll-up recomputes by hand from the stored message set. | 1 Functional coverage (28) | SHOULD

CHN-20 | W2 | D8 | P1 Channel | C9 | Eval | Golden case 11 - weekly arithmetic reproducibility | Automated check that every number in the weekly roll-up can be recomputed from the stored messages, including the week containing a non-working day. | Python | — | CHN-19 | 1.0 | Recomputation test passes for every figure. | 2 Grounding (12) | SHOULD

CHN-21 | W2 | D8 | P1 Channel | C10 | Nudges | Nudge non-responders - opt-in, capped, never the excluded | OFF BY DEFAULT, enabled per channel. Polite reminder to a non-responder via the publish adapter. Hard per-person per-day cap. Members on the exceptions list are never nudged. The first nudge to any given person requires approval; thereafter within cap it runs unattended. | Python (cap and eligibility) + Power Automate (delivery) | Eligibility and the cap are correctness guarantees and stay in code. Delivery is a Teams concern. | CHN-20 | 2.5 | The on-leave member is never nudged under any path; the cap holds across repeated runs in one day. | 1 Functional coverage (28) | SHOULD

CHN-22 | W2 | D8 | P1 Channel | C10 | Adapters | Teams publish adapter - mock log and real flow | Narrow interface: post_channel_message, post_direct_message. Mock writes every outbound message to an inspectable JSONL log and performs no network egress. Real implementation posts via an HTTP-triggered Power Automate flow as the flow bot. | Python + Power Automate | Graph application permission to SEND channel messages is restricted; a Power Automate flow bot is the pragmatic write path and keeps read and write permissions cleanly separated. | CHN-21 | 1.5 | Every nudge, escalation and digest is a row you can show on camera before anything is ever sent. | 5 Architecture (10) | SHOULD

CHN-23 | W2 | D9 | P1 Channel | C11 | Escalation | Escalate to the channel owner | After N consecutive missed update days (N from config), escalate to the configured channel owner with the evidence: the dates, the window applied, and what was and was not posted. The first escalation for any person requires approval. Escalation is a private message to the owner, never a channel post. | Python (trigger and evidence) + Power Automate (delivery) | The evidence bundle is the point - an escalation without dates and message IDs is an accusation. | CHN-22 | 2.0 | With the threshold at three days, exactly the seeded members missing three consecutive days are escalated, each with a dated evidence bundle. | 1 Functional coverage (28) | SHOULD

CHN-24 | W2 | D9 | P1 Channel | C1 | Eval | Golden cases 7, 8 and 12 | GC7 nudge cap, never-nudge-excluded, and nudge-before-escalation ordering. GC8 approval enforcement: nudge, escalation and first publish for pending and rejected proposals all fail at the service layer. GC12 configuration is really configuration - change the roster and the window and assert the non-responder set moves correctly. | Python | GC12 is the one that proves the roster and window are not hard-coded, which is what the user asked for. | CHN-23 | 2.0 | All three cases pass; GC12 runs the same day's data against two different configs. | 4 Eval harness (12) | MUST

CHN-25 | W2 | D9 | P1 Channel | C1 | UI | Copilot Studio - approvals and per-channel config in Teams | Copilot Studio agent over the same service API: adaptive cards for pending nudges, escalations and first publishes; a per-channel config surface backed by Dataverse so a channel owner maintains their own roster, window and exceptions list without a deploy. A Streamlit or CLI surface over the same API remains the scored fallback. | Copilot Studio + Dataverse | BEST FIT. The channel owner who knows the roster lives in Teams. Asking them to edit a YAML file is how the config goes stale and the non-responder list becomes wrong. | CHN-24 | 2.0 | Approving from Teams and from the fallback surface produce identical audit records - proving the gate lives in the service, not the UI. | 3 HITL gating (10) | SHOULD

CHN-26 | W2 | D9 | P1 Channel | C12 | Contract | Emit versioned outcome record | One versioned record per channel per day with a published JSON schema and a version field: classified updates, blockers, decisions, questions, and the participation ledger. THIS IS THE CONTRACT THE P2 PM AGENT CONSUMES. | Python + JSON Schema | Cross-agent contract. Design it now and week 4 becomes assembly. A daily channel record feeding the PM morning brief is the natural composition. | CHN-25 | 2.0 | A second process reconstructs the day's updates and participation from the record with no access to the message store. | 5 Architecture (10) | SHOULD

CHN-27 | W2 | D10 | P1 Channel | — | Eval | Full harness run and record numbers | Run all twelve golden cases; commit the results file; quote headline numbers in the README. | Python | — | CHN-26 | 1.0 | Results file committed with timestamp, model ID and prompt versions. | 4 Eval harness (12) | MUST

CHN-28 | W2 | D10 | P1 Channel | — | Eval | Fix the worst finding and document it | Pick the weakest metric, fix it, re-run, record both numbers and write up what changed and why in the decision log. | Claude Code + Claude API | A harness that reveals a weakness you then explain scores higher than one reporting all green. | CHN-27 | 1.5 | Before and after numbers both committed with a written explanation. | 4 Eval harness (12) | MUST

CHN-29 | W2 | D10 | P1 Channel | — | Robustness | Edge-case and failure pass | A day with no messages in a channel. A non-working day. A member whose only update was later deleted. A message edited after the window closed. Two similar display names. Graph throttling and delta-token expiry. Malformed model output. A roster member who has left the tenant. | Python | Ambiguity surfaced as ambiguity, never resolved by guessing. The deleted-only-update case is the one that most easily produces a false accusation. | CHN-28 | 2.0 | Each scenario has a test and a graceful, non-fabricating outcome. | 6 Robustness (8) | MUST

CHN-30 | W2 | D10 | P1 Channel | — | Docs | README status table, architecture note, decision log | Status table written FROM the code with one row per capability marked Done / Partial / Not built. One-page architecture note showing the read path, the write path, where the approval gate sits, and the Graph permission model actually used. Decision log including the CHN-01 permission decision and every scope cut. | Claude Code (drafted from the repo) | Write it last, from the code. A README that outruns the code is an automatic failure. | CHN-29 | 1.5 | Every row in the status table is verifiable by opening the named file. | 7 Repo hygiene (8) | MUST

CHN-31 | W2 | D10 | P1 Channel | — | Demo | Clean-clone verification | Clone into a fresh directory, follow only the README, run the full flow against the mock adapter. | Human | The mock path must run with no tenant access at all - that is what makes the repo reproducible. | CHN-30 | 0.5 | Works with zero undocumented steps and no Graph credentials. | 7 Repo hygiene (8) | MUST

CHN-32 | W2 | D10 | P1 Channel | — | Demo | Record the walkthrough | 5-10 minutes: ingest two channels and refuse the third, a chat refused at the boundary, update detection with a rule decision and a classifier decision shown, the participation ledger with all three states, the daily summary with a permalink clicked live, the weekly roll-up, a nudge held at approval and one rejected, an escalation evidence bundle, and the eval output. Close with your own view of the weakest part. | Human + screen recorder | Clicking a permalink live, from a summary line to the actual Teams message, is the most convincing ten seconds of the demo. | CHN-31 | 1.0 | Recording shows a genuine end-to-end run including the refusal and rejection paths. | 8 Demo quality (8) | MUST

CHN-33 | W2 | D10 | Shared | — | Platform | Gate G1 review and spine extraction | Self-score against the rubric. Extract the reusable spine (gateway, schema layer, proposals, write guard, grounding kernel, harness, scheduler, prompt registry, config pattern) into an installable internal package with its own tests. | Claude Code | The whole six-week economy depends on the spine being reused rather than copy-pasted. | CHN-32 | 1.0 | Spine package installs into a fresh project and its tests pass independently of P1. | 9 Judgement (4) | MUST
```


## Appendix B — Master Work Breakdown (119 tasks), verbatim, part 2 of 3 (PM)

```
Master Work Breakdown — 30 days, 3 agents
One row per task. 'Cap ID' maps to the capability IDs in the source briefs (M1–M13 Meeting, P1–P11 PM, O1–O12 PO). SPN rows are shared-spine components built once and reused by all three agents.

Task ID | Week | Day | Agent | Cap ID | Workstream | Task | What to build / what done means | Primary tool | Why this tool | Depends on | Est hrs | Acceptance test | Rubric criterion (weight) | Priority

PM-01 | W3 | D11 | P2 PM | — | Seed data | Seed the project: items and history | 25-40 work items across two sprints, 5-7 assignees, full transition history with real timestamps. | Claude (generation) + Python (fixture) | Generation is fast; the fixture must be committed so runs are reproducible. | CHN-33 | 3.0 | Committed as files or a migration; a fresh seed reproduces byte-identical state. | 1 Functional coverage (28) | MUST

PM-02 | W3 | D11 | P2 PM | — | Seed data | Seed commits, risks, commitments and outcome records | 30-60 commits referencing some but not all items. A risk log with three entries. Six to ten commitments, some overdue. Two channel outcome records from P1, one missing a consent or scope flag. Channel message data is reused from the P1 fixture rather than re-seeded. | Claude (generation) + Python (fixture) | Reusing P1's channel fixture is the first concrete dividend of building the agents in this order. | PM-01 | 2.0 | All stores seeded and committed; the chat source is the P1 fixture, not a copy. | 1 Functional coverage (28) | MUST

PM-03 | W3 | D11 | P2 PM | — | Seed data | Plant the ten deliberate difficulties | Blocker open 4 days with no risk entry, and another open 1 day. An item moved to done then back to in-progress the same day. An assignee with zero activity for two days. An unassigned item. Two items added mid-sprint. Commits with no item reference and one item referenced but never transitioned. A free-text status that does not map to the enum. A commitment with a relative due date only. Two people with similar names. | Human (Claude assists) | These ten are the entire P2 golden set. Place them by hand and record where. | PM-02 | 2.0 | A committed difficulties file naming each planted case and the entity it lives on. | 4 Eval harness (12) | MUST

PM-04 | W3 | D11 | P2 PM | P1 | Adapters | Tracker, code-host and risk-log adapters | Three narrow interfaces with mocks over the seeded fixtures. The chat adapter is inherited from P1's Teams reader rather than rebuilt, and the notifier from P1's publish adapter. | Python | Two of the five adapters this agent needs already exist. Do not rebuild them. | PM-03 | 1.0 | Mocks return messy data; P1's Teams reader satisfies the chat dependency with no new code. | 5 Architecture (10) | MUST

PM-05 | W3 | D12 | P2 PM | P1 | State | Project-state snapshot with persistence | Normalise tracker, code-host and channel reads into one snapshot, persisted with a timestamp so later runs can diff against it. Free-text status values that do not map are carried as UNMAPPED, never coerced. | Python | Deterministic normalisation; no model involved. | PM-04 | 3.0 | Two consecutive snapshots persist and are independently readable. | 1 Functional coverage (28) | MUST

PM-06 | W3 | D12 | P2 PM | P3 | State | Snapshot diff engine computed in code | Delta between two snapshots computed arithmetically, not by asking a model to compare two blobs. Correctly collapses the item that moved forward and then back into a single accurate description. | Python | The brief names this as the decision separating a strong submission from an average one. | PM-05 | 3.0 | The twice-moved item appears once, described accurately, in the computed delta. | 1 Functional coverage (28) | MUST

PM-07 | W3 | D12 | P2 PM | P3 | Eval | Golden case 3 - delta correctness | Hand-label what actually changed between the morning and end-of-day snapshots. Assert the delta set matches exactly. Report precision and recall. | Python + human labels | — | PM-06 | 2.0 | Precision and recall printed against hand labels. | 4 Eval harness (12) | MUST

PM-08 | W3 | D13 | P2 PM | P2 | Reporting | Morning brief | Sprint day and scope, then per person committed / delivered / pending / blocked, then blockers ranked by impact. Schema-constrained. The model expresses the facts; the facts come from the snapshot. | Claude API (expression) + Python (facts) | Same split proven in P1. Facts in code, prose from the model. | PM-07 | 3.0 | Regenerating on the same snapshot yields identical facts; wording may differ. | 1 Functional coverage (28) | MUST

PM-09 | W3 | D13 | P2 PM | P2 | Grounding | Reference-or-drop on every brief line | Apply the grounding kernel: any factual line without a resolvable source reference (item ID, transition, commit hash, message ID) is removed or explicitly marked unsupported. | Python (spine SPN-06) | Already built in week 1. This is wiring, and it is the heart of the agent. | PM-08 | 1.5 | A hand-forged unreferenced line is dropped and logged. | 2 Grounding (12) | MUST

PM-10 | W3 | D13 | P2 PM | P2 | Grounding | Absence reported as absence | A person with no activity is reported as having no activity - not omitted, not embellished. An empty day produces an honest empty brief. | Python + prompt design | The same discipline as P1's participation ledger, applied to tracker and commit activity. | PM-09 | 1.0 | The zero-activity assignee appears with an explicit no-update line. | 2 Grounding (12) | MUST

PM-11 | W3 | D13 | P2 PM | P2 | Scheduler | Morning and end-of-day scheduling | Reuse P1's scheduler with a clock override. Jobs at configured local times, working days only. | Python (spine) + Power Automate | Scheduler already exists. This is configuration, not construction. | PM-10 | 1.0 | A clock-override run produces the brief at the simulated time. | 1 Functional coverage (28) | MUST

PM-12 | W3 | D13 | P2 PM | P2 | Eval | Golden cases 1 and 2 - citation rate and fabrication | GC1 proportion of factual lines with a valid resolvable reference, target >=0.90. GC2 fabricated-claim count across brief and summary including the zero-activity assignee and the empty day, target 0. | Python | GC2 is the most important number in the P2 submission. | PM-11 | 1.5 | Both metrics printed and committed. | 4 Eval harness (12) | MUST

PM-13 | W3 | D14 | P2 PM | P5 | Approval | Approval gate wired to the proposal spine | Approve / reject / edit-then-approve, recording approver, timestamp, the original proposal and the final applied payload. Approved proposals execute through the adapter and are logged. | Python (spine SPN-08/09) + Copilot Studio cards | Reused from week 2. Teams cards are the human surface; enforcement stays in the service. | PM-12 | 2.5 | The audit trail answers: who approved this entry, when, and what did the agent originally propose? | 3 HITL gating (10) | MUST

PM-14 | W3 | D14 | P2 PM | P5 | Eval | Golden case 6 - approval enforcement | Direct service-layer write attempts for pending and rejected proposals must both fail. Assert the audit record captures approver, timestamp, original and applied payload. | Python | — | PM-13 | 1.0 | Both assertions pass. | 3 HITL gating (10) | MUST

PM-15 | W3 | D14 | P2 PM | P4 | Storage | Risk-log store, human-readable | Risk log in a format a human can open and read. Dataverse table as the delivery-lead-facing store, with a committed JSON or CSV mirror as the repo system of record. | Dataverse + Python mirror | A risk log the lead can open is what makes the demo persuasive. The mirror keeps runs reproducible offline. | PM-14 | 2.0 | The same three seeded risks are visible in both stores and stay in sync. | 1 Functional coverage (28) | MUST

PM-16 | W3 | D14 | P2 PM | P4 | Proposals | Risk-log gap detection | For each current blocker absent from the risk log, one proposal containing description, impact, suggested owner only where evidenced, and the blocker reference that grounds it. | Python (gap set) + Claude API (wording) | Set arithmetic in code, prose from the model. | PM-15 | 2.5 | The two missing blockers are proposed; the three already present are not. | 1 Functional coverage (28) | MUST

PM-17 | W3 | D15 | P2 PM | P4 | Proposals | Rejection memory - no identical re-proposal | A rejected proposal is fingerprinted so the next run does not re-propose it identically. A material change to the underlying blocker allows a new proposal, with the change stated. | Python | Named explicitly in the brief. Most candidates miss it. | PM-16 | 1.5 | Reject one proposal, re-run, assert no duplicate appears. | 1 Functional coverage (28) | MUST

PM-18 | W3 | D15 | P2 PM | P4 | Eval | Golden case 4 - gap precision and no-duplicate | Precision and recall on the gap set, then the reject-and-rerun assertion. | Python | — | PM-17 | 1.5 | Both printed and committed. | 4 Eval harness (12) | MUST

PM-19 | W3 | D15 | P2 PM | P6 | Proposals | Blocker-to-risk promotion | Blocker age computed from transitions. Promotion threshold read from configuration. Proposal carries drafted mitigation wording and the evidence of how long the blocker has been open. | Python (age, threshold) + Claude API (mitigation) | Threshold must be configuration, not a literal - the golden case tests exactly this. | PM-18 | 2.5 | With the threshold at two days, exactly the blockers older than two days are proposed. | 1 Functional coverage (28) | SHOULD

PM-20 | W3 | D15 | P2 PM | P6 | Eval | Golden case 5 - promotion threshold reconfiguration | Run at a two-day threshold, then at four days, and assert the proposed set shrinks correctly. | Python | Proves the threshold is really configuration. | PM-19 | 1.5 | Both runs printed; set difference asserted. | 4 Eval harness (12) | SHOULD

PM-21 | W3 | D15 | P2 PM | — | Platform | Prompt files for brief, summary and mitigation | Versioned prompts in the registry, recorded in eval output. | Claude Code | — | PM-20 | 1.0 | Three prompt files with versions in the results file. | 5 Architecture (10) | MUST

PM-22 | W4 | D16 | P2 PM | P3 | Reporting | End-of-day summary as genuine deltas | What shipped, what is still pending, what is newly blocked, what changed since morning - built from the stored diff, never a restatement of the morning brief. | Python (delta) + Claude API (expression) | If short on time, cut P9 rather than degrading this. Deltas are what make this agent more than a dashboard. | PM-21 | 3.0 | The summary names exactly the hand-labelled changed set; the twice-moved item appears once. | 1 Functional coverage (28) | MUST

PM-23 | W4 | D16 | P2 PM | P2 | Eval | Golden case 9 - determinism of facts | Generate the morning brief twice from the same snapshot. Wording may differ; the set of items, owners, counts and statuses must not. | Python | — | PM-22 | 1.5 | Fact-set comparison across two generations prints zero divergences. | 4 Eval harness (12) | MUST

PM-24 | W4 | D16 | P2 PM | P7 | Commitments | Commitment tracking, nudges and escalation | Commitment store seeded and fed by channel outcome records. Nudge before a due date, overdue record after, escalation to the lead beyond the configured threshold. Hard per-person per-day cap shared with P1's cap so one person is never chased by two agents on the same day. Ageing view of all open commitments. | Python + P1 publish adapter | THE SHARED NUDGE CAP IS THE REUSE THAT MATTERS MOST. Two agents each politely chasing the same person is how an agent estate becomes a nuisance. | PM-23 | 3.0 | Seeded overdue commitments produce nudge then escalation in that order; the cap holds across both agents on the same day. | 1 Functional coverage (28) | SHOULD

PM-25 | W4 | D17 | P2 PM | P7 | Eval | Golden case 7 - nudge cap and escalation order | Assert nudges never exceed the per-person daily cap - counting P1's nudges too - and that nudge precedes escalation without repeating beyond the cap. | Python | — | PM-24 | 1.5 | Ordering and the shared cap both asserted. | 4 Eval harness (12) | SHOULD

PM-26 | W4 | D17 | P2 PM | P8 | Contract | Consume the channel outcome record | Read the versioned outcome record emitted by P1 (CHN-26). Produce two batched proposal sets - tracker updates or creations, and risk-log entries - each item carrying the channel and message reference that justifies it. | Python + JSON Schema | CROSS-AGENT PROOF POINT. Two independently built agents composing through a published versioned contract is the strongest thing in the programme demo. | PM-25 | 2.5 | P1's record file is consumed with no shared code beyond the schema. | 5 Architecture (10) | SHOULD

PM-27 | W4 | D17 | P2 PM | P8 | Governance | Scope and consent refusal, golden case 8 | Outcome records whose scope or consent flag is not explicitly true are refused outright with a logged reason and produce zero proposals. | Python | The scope flag carried forward from P1 is what stops out-of-scope channel content leaking into the tracker. | PM-26 | 2.0 | The record lacking the flag yields zero proposals and one logged refusal. | 3 HITL gating (10) | SHOULD

PM-28 | W4 | D17 | P2 PM | P2 | UI | Copilot Studio brief delivery and approvals in Teams | Morning brief and end-of-day digest posted into a Teams channel through P1's publish adapter. Proposal approvals as adaptive cards. Dataverse risk log surfaced conversationally. | Copilot Studio + Power Automate | The primary user reads the brief on a phone before standup. Teams is that surface, and the publish path already exists. | PM-27 | 2.0 | Approving from Teams writes the same audit record as the fallback surface. | 3 HITL gating (10) | SHOULD

PM-29 | W4 | D18 | P2 PM | P9 | Reporting | Weekly status report | Progress against sprint scope, scope change, top risks ranked, decisions needed from the client, and a plain-language explanation of any velocity change. Grounded throughout. The agent never sends. | Python (quantities) + Claude API (narrative) | Reuses P1's weekly roll-up arithmetic pattern. | PM-28 | 3.0 | The scope-change section correctly identifies the two items added mid-sprint. | 1 Functional coverage (28) | SHOULD

PM-30 | W4 | D18 | P2 PM | P9 | Grounding | Quantitative reproducibility assertion | Automated check that every number in the weekly report can be recomputed from the stored snapshots. | Python | — | PM-29 | 1.5 | Recomputation test passes for every figure in the report. | 2 Grounding (12) | SHOULD

PM-31 | W4 | D18 | P2 PM | P1 | Robustness | Free-text status mapping | Unmappable status values are surfaced as UNMAPPED with the raw value shown, never coerced into the nearest enum member. | Python | Silent coercion is guessing with extra steps. | PM-30 | 1.5 | The planted free-text status appears as UNMAPPED in the brief with its raw value. | 6 Robustness (8) | MUST

PM-32 | W4 | D18 | P2 PM | P2 | Robustness | Similar-name disambiguation guard | Two people with similar names are never merged. Ambiguous attribution is surfaced as ambiguous. Shares the resolution rule with P1. | Python | — | PM-31 | 1.5 | Both similar-named assignees keep distinct per-person sections. | 6 Robustness (8) | MUST

PM-33 | W4 | D19 | P2 PM | — | Eval | Full harness run and record numbers | All nine golden cases; commit the results file; quote headline numbers in the README. | Python | — | PM-32 | 1.5 | Results committed with model ID and prompt versions. | 4 Eval harness (12) | MUST

PM-34 | W4 | D19 | P2 PM | — | Eval | Fix the worst finding and document it | Fix, re-run, record both numbers, write up the change. | Claude Code + Claude API | — | PM-33 | 2.0 | Before and after numbers committed with an explanation. | 4 Eval harness (12) | MUST

PM-35 | W4 | D19 | P2 PM | — | Robustness | Edge-case and failure pass | Empty day, person with no activity, item that moved twice, malformed model output, rate-limit path, unassigned item, commit with no item reference. | Python | The fabrication probe matters most: verify no progress is reported that the snapshots do not support. | PM-34 | 2.5 | Each scenario tested; none fabricates. | 6 Robustness (8) | MUST

PM-36 | W4 | D19 | P2 PM | — | Docs | README status table, architecture note, decision log | Written from the code, one row per capability, Done / Partial / Not built. | Claude Code (from the repo) | — | PM-35 | 2.0 | Every claim verifiable against a named file. | 7 Repo hygiene (8) | MUST

PM-37 | W4 | D20 | P2 PM | — | Demo | Clean-clone verification | Fresh directory, README only, mock adapters throughout. | Human | — | PM-36 | 1.0 | Runs with zero undocumented steps. | 7 Repo hygiene (8) | MUST

PM-38 | W4 | D20 | P2 PM | — | Demo | Record the walkthrough | Scheduled morning brief with references, a person with no activity handled honestly, end-of-day deltas, gap detection, approve one and REJECT ONE with the audit trail shown, a promotion proposal, a nudge and an escalation, an outcome record refused for a missing scope flag, the eval output. | Human + screen recorder | Show the rejection path on camera - most candidates only show approval. | PM-37 | 2.0 | Recording shows a genuine run including the rejection path. | 8 Demo quality (8) | MUST

PM-39 | W4 | D20 | P2 PM | — | Governance | Gate G2 review | Self-score against the rubric. Record scope cuts and what it would take to add them. | Human | — | PM-38 | 2.0 | Self-score sheet completed with evidence per criterion. | 9 Judgement (4) | MUST

PM-40 | W4 | D20 | Shared | — | Platform | Spine hardening for P3 | Fold P1 and P2 learnings back into the shared package: citation resolver generalisation, config-threshold pattern, proposal fingerprinting, shared nudge cap, eval metric helpers. | Claude Code | The third agent should be assembly, not construction. | PM-39 | 3.0 | Spine tests still pass; P3 starts from the hardened package. | 5 Architecture (10) | MUST
```


## Appendix B — Master Work Breakdown (119 tasks), verbatim, part 3 of 3 (PO + PGM + totals)

```
Master Work Breakdown — 30 days, 3 agents
One row per task. 'Cap ID' maps to the capability IDs in the source briefs (M1–M13 Meeting, P1–P11 PM, O1–O12 PO). SPN rows are shared-spine components built once and reused by all three agents.

Task ID | Week | Day | Agent | Cap ID | Workstream | Task | What to build / what done means | Primary tool | Why this tool | Depends on | Est hrs | Acceptance test | Rubric criterion (weight) | Priority

PO-01 | W5 | D21 | P3 PO | — | Seed data | Write the sample product brief | 1,500-3,000 words for a plausible internal product, structured into numbered, addressable sections down to paragraph level. | Claude (drafting) + human edit | Declare model assistance in the README - the brief says that is expected and fine. | PM-40 | 3.0 | Committed brief with a stable section numbering scheme. | 1 Functional coverage (28) | MUST

PO-02 | W5 | D21 | P3 PO | — | Seed data | Glossary with a planted inconsistency | 15-25 domain terms. One term is used inconsistently between the brief and the glossary. | Claude + human edit | — | PO-01 | 1.5 | Glossary committed; the inconsistent term recorded in the golden-labels file. | 1 Functional coverage (28) | MUST

PO-03 | W5 | D21 | P3 PO | — | Seed data | Seed the existing backlog | 15-25 items of mixed quality: some with good criteria, some with none, one that overlaps with a story the epic will produce, one that contradicts a requirement in the brief. Four items labelled ready / not ready with reasons for the gate test. | Claude + human labels | — | PO-02 | 2.0 | Backlog committed with a labels file for the readiness and overlap cases. | 1 Functional coverage (28) | MUST

PO-04 | W5 | D21 | P3 PO | — | Seed data | Two epics and two feedback records | One reasonably detailed epic, one deliberately thin. One stakeholder feedback record, and one lacking a consent flag. | Claude + human edit | The thin epic is the revealing test - a good agent asks questions, a weak one invents a product. | PO-03 | 1.5 | All four artefacts committed. | 1 Functional coverage (28) | MUST

PO-05 | W5 | D22 | P3 PO | — | Seed data | Plant the three deliberate gaps | A stated limit with no number ('large files are rejected' - how large?). A role referenced but never defined ('approvers can override' - who is an approver?). A state transition with an undefined path ('rejected submissions are returned' - to which state, and can they be resubmitted?). | Human | These three drive the headline metric of the whole P3 submission. Place them yourself. | PO-04 | 1.0 | Each gap recorded with its exact section reference in the golden-labels file. | 4 Eval harness (12) | MUST

PO-06 | W5 | D22 | P3 PO | O1 | Grounding | Context index with hand-checkable section refs | Chunk and index the brief, glossary and backlog so every chunk is addressable by a stable, specific reference of the form section.subsection, paragraph N. A reference to the whole document is invalid by construction. | Python + FTS5 or local embeddings | Design the reference scheme on day one with the reviewer's hand-check in mind. Everything downstream is worthless if references are not checkable. | PO-05 | 3.0 | Ask for context supporting a topic and get back specific citable sections a human can open and verify. | 2 Grounding (12) | MUST

PO-07 | W5 | D22 | P3 PO | O6 | Grounding | Citation resolver | Resolve every emitted citation against the index. Whole-document references count as unresolvable. Unresolvable claims are removed and reported as unsupported, never quietly dropped. | Python (spine SPN-06 generalised) | Reuses the grounding kernel built in week 1. Unresolvable-citation count must be zero. | PO-06 | 2.0 | A hand-forged citation to a non-existent section is rejected and surfaced as a gap. | 2 Grounding (12) | MUST

PO-08 | W5 | D22 | P3 PO | O1 | Adapters | Doc-store adapter | Narrow interface plus mock over the seeded brief, glossary and backlog, addressable to paragraph level. The tracker adapter is inherited from P2. | Python | One new adapter. The other two already exist. | PO-07 | 1.0 | Agent logic imports only interfaces. | 5 Architecture (10) | MUST

PO-09 | W5 | D22 | P3 PO | O6 | Eval | Golden case 1 - citation resolution | Assert every citation in every generated artefact resolves to a real specific section. Metric: unresolvable-citation count, target zero. | Python | — | PO-08 | 1.0 | Metric printed; target is a hard zero. | 4 Eval harness (12) | MUST

PO-10 | W5 | D23 | P3 PO | O3 | Drafting | Acceptance criteria with open questions as a required field | Given/When/Then for happy path and stated alternatives; separately edge cases; separately non-functional considerations only where the source states them; separately OPEN QUESTIONS as a required schema field the model cannot omit. Everything tagged AI-drafted. | Claude API (forced schema) + Python (validation) | Making open questions a required field is the design decision that produces the headline metric. Enforce it in the schema, not the prompt. | PO-09 | 3.5 | A story yields GWT criteria where every citation resolves, and the planted gaps surface as open questions rather than invented rules. | 1 Functional coverage (28) | MUST

PO-11 | W5 | D23 | P3 PO | O6 | Grounding | Grounding enforcement on criteria | Hard validation step removing any criterion that states a threshold, limit, role or field name absent from the source. Removed items reported to the human as unsupported. | Python | Removal must be a code step, not a hopeful sentence in the prompt. | PO-10 | 2.0 | A criterion inventing a numeric limit is removed and reported. | 2 Grounding (12) | MUST

PO-12 | W5 | D23 | P3 PO | O3 | Eval | Golden case 2 - open-question recall and invented-specific count | For each of the three planted gaps, assert a corresponding open question is raised and no criterion asserts a specific value for it. Targets: recall 3 of 3, invented-specific count 0. | Python | THE MOST IMPORTANT NUMBER IN THE P3 SUBMISSION. | PO-11 | 2.5 | Both metrics printed and committed. | 4 Eval harness (12) | MUST

PO-13 | W5 | D24 | P3 PO | O2 | Drafting | Epic decomposition with citations | Independent, testable stories in a consistent format, each citing the source section that justifies it, plus a note on dependencies between them and an explicit list of what the epic does not say. Stories that cannot be grounded are omitted and reported as gaps. | Claude API (forced schema) + Python (validation) | Reuses the citation validation built on day 22. | PO-12 | 3.0 | The detailed epic decomposes into grounded, product-specific stories; ungroundable ones are reported, not invented. | 1 Functional coverage (28) | MUST

PO-14 | W5 | D24 | P3 PO | O2 | Eval | Golden case 4 - decomposition coverage and redundancy | Hand-write the capabilities a reviewer would expect from the detailed epic. Measure coverage AND redundancy. High coverage achieved by generating twenty overlapping stories is not a pass. | Python + human labels | Reporting both numbers is the point. | PO-13 | 2.0 | Coverage and redundancy both printed. | 4 Eval harness (12) | MUST

PO-15 | W5 | D24 | P3 PO | O8 | Guardrails | Anti-generic guard | Configurable forbidden-pattern list plus a glossary-density check. Generic output is rejected and regenerated with the specific failure fed back. Persistent failures are surfaced to the human rather than shipped. | Python (detection) + Claude API (regeneration) | Runs before the human ever sees the draft. | PO-14 | 2.5 | A story that would read identically for an unrelated product is rejected. | 1 Functional coverage (28) | SHOULD

PO-16 | W5 | D25 | P3 PO | O8 | Eval | Golden case 3 - generic-story rate before and after | Hand-label generated stories as product-specific or generic. Report the rate BEFORE and AFTER the guard. Target under 0.1 after. | Python + human labels | The before-and-after measurement is worth more than the guard itself. | PO-15 | 2.0 | Two numbers printed and committed with the labels file. | 4 Eval harness (12) | SHOULD

PO-17 | W5 | D25 | P3 PO | O4 | Gating | Definition of Ready gate | Checklist held as configuration, not literals in code. Pass or block verdict per story with a SPECIFIC failing reason per unmet criterion and a note on what would resolve it. Overrides recorded with who overrode and why. | Python (rule engine) + Claude API (resolution note) | Reuses P1's rules-as-config pattern. Checklist-as-config is directly tested by the golden case. | PO-16 | 3.0 | The two deficient seeded stories are blocked for the right reasons; the two adequate ones pass. | 1 Functional coverage (28) | MUST

PO-18 | W5 | D25 | P3 PO | O4 | Eval | Golden case 5 - readiness gate accuracy | Assert the gate agrees with all four labels and that each block names a specific unmet criterion rather than a general complaint. | Python | — | PO-17 | 1.5 | Four-for-four with specific reasons. | 4 Eval harness (12) | MUST

PO-19 | W5 | D25 | P3 PO | — | Platform | Prompt files for criteria, decomposition and rationale | Versioned prompts in the registry, recorded in eval output. | Claude Code | — | PO-18 | 1.5 | Prompt versions appear in the results file. | 5 Architecture (10) | MUST

PO-20 | W6 | D26 | P3 PO | O5 | Prioritisation | Transparent prioritisation - arithmetic in code | Score computed in code from stated inputs (value, effort, risk, dependency state, readiness). Component inputs, the arithmetic and the final score all displayed. The model writes the one-line rationale ONLY. | Python (arithmetic) + Claude API (rationale) | A model asked to score a backlog produces numbers nobody can reproduce or defend - the opposite of the point. | PO-19 | 3.0 | The arithmetic is reproducible by hand from the displayed inputs. | 1 Functional coverage (28) | MUST

PO-21 | W6 | D26 | P3 PO | O5 | Prioritisation | Dependency-respecting next-sprint slice | Proposed slice never places an item ahead of an unmet dependency and respects readiness state. | Python | — | PO-20 | 1.5 | No item is proposed ahead of something it depends on. | 1 Functional coverage (28) | MUST

PO-22 | W6 | D26 | P3 PO | O5 | Eval | Golden case 6 - prioritisation reproducibility | Recompute three items' scores by hand and assert they match. Perturb one input and assert the rank moves in the predicted direction. Assert dependency ordering holds. | Python + human recomputation | — | PO-21 | 2.5 | All three assertions pass. | 4 Eval harness (12) | MUST

PO-23 | W6 | D26 | P3 PO | O2 | Eval | Golden case 8 - thin-epic negative test | Run the deliberately thin epic. Assert the agent produces MORE open questions than stories and does not invent product behaviour. | Python | The revealing test of the whole agent. A confident, complete-looking backlog here is a failure. | PO-22 | 1.0 | Open-question count exceeds story count; zero invented specifics. | 4 Eval harness (12) | MUST

PO-24 | W6 | D27 | P3 PO | O7 | Detection | Duplicate and overlap detection | Overlap warnings naming the existing item, the relationship type (duplicate / subset / superset / adjacent), and a recommendation to merge, split or proceed. The agent never merges or closes anything. | Python (retrieval) + Claude API (relationship) | Retrieval narrows; the model classifies the relationship; the human decides. | PO-23 | 3.0 | The deliberately overlapping story is flagged with the correct relationship; the four distinct stories are not flagged. | 1 Functional coverage (28) | SHOULD

PO-25 | W6 | D27 | P3 PO | O7 | Eval | Golden case 7 - overlap precision and recall | Report precision and recall against the labelled overlap set. | Python | — | PO-24 | 1.5 | Both printed. | 4 Eval harness (12) | SHOULD

PO-26 | W6 | D27 | P3 PO | O9 | Approval | Draft back to tracker with the not-ready status floor | Approved drafts become a tracker comment or draft item through the adapter, tagged AI-drafted, carrying citations, FLOORED AT A NOT-READY STATUS ENFORCED IN THE WRITE PATH. Idempotent: re-approval does not duplicate. Persisted write log. | Python (spine SPN-08/09) | The status floor is a design constraint, not a label. It must be structurally impossible for the agent to mark its own work ready. | PO-25 | 2.5 | Approve two drafts and re-run twice: exactly two records, both tagged, both not-ready. Pending and rejected drafts fail at the service layer. | 3 HITL gating (10) | MUST

PO-27 | W6 | D27 | P3 PO | O9 | Eval | Golden case 9 - approval and status floor | Automated test attempting writes for pending and rejected drafts (both must fail) plus an assertion that every written record is tagged AI-drafted and sits at the not-ready status. | Python | — | PO-26 | 1.0 | All assertions pass. | 3 HITL gating (10) | MUST

PO-28 | W6 | D28 | P3 PO | O10 | Drafting | Synthesise stakeholder input | Candidate backlog items and a discovery log from the supplied feedback record and from P1 channel outcome records, each citing the originating input, with duplicates against the existing backlog already flagged. Records without consent or scope set true are refused. | Claude API (forced schema) + Python (consent, dedupe) | Reusing P1's outcome record here means product feedback raised in a Teams channel reaches the backlog with its citation intact. | PO-27 | 2.5 | Candidate items carry correct citations; the record lacking consent is refused with a logged reason; nothing is created without approval. | 1 Functional coverage (28) | SHOULD

PO-29 | W6 | D28 | P3 PO | O3 | Eval | Golden case 10 - glossary consistency | Assert generated output uses the glossary term rather than the inconsistent variant planted in the brief, AND that the inconsistency itself is raised as an open question. | Python | Both halves must pass - using the right term while staying silent about the conflict is a partial pass only. | PO-28 | 1.5 | Both assertions pass. | 4 Eval harness (12) | MUST

PO-30 | W6 | D28 | P3 PO | O4 | UI | Copilot Studio backlog review in Teams | Draft stories and criteria surfaced as adaptive cards for refinement and approval. Dataverse table holds AI-drafted items at not-ready status, visible to the whole product team. A conversational 'why does this story exist?' topic returns the citation. | Copilot Studio + Dataverse | Backlog refinement is a group activity in Teams, and a Dataverse table at not-ready status makes the floor visible to everyone rather than only provable in a test. | PO-29 | 2.0 | Approving in Teams writes the same audit record and the same not-ready floor as the fallback surface. | 3 HITL gating (10) | SHOULD

PO-31 | W6 | D28 | P3 PO | O11 | Drafting | Batch criteria drafting (stretch - only if green) | Scheduled run over stories flagged as lacking criteria. Draft criteria attached as comments, tagged AI-drafted, one per story, with a summary of what was skipped and why. Nothing modifies the story body. | Python (scheduler) + Claude API | COULD row. Attempt only when every MUST is genuinely complete. | PO-30 | 2.0 | Drafts criteria for exactly the flagged stories and skips the rest, with skip reasons logged. | 1 Functional coverage (28) | COULD

PO-32 | W6 | D29 | P3 PO | — | Eval | Full harness run across all ten golden cases | Run, commit the results file, quote headline numbers in the README. | Python | — | PO-31 | 1.5 | Results committed with model ID and prompt versions. | 4 Eval harness (12) | MUST

PO-33 | W6 | D29 | P3 PO | — | Eval | Fix the worst finding and document it | Fix, re-run, record both numbers, write up the change. | Claude Code + Claude API | — | PO-32 | 2.0 | Before and after numbers committed with an explanation. | 4 Eval harness (12) | MUST

PO-34 | W6 | D29 | P3 PO | — | Robustness | Edge-case and failure pass | The near-empty epic, a story already perfectly specified, the inconsistent glossary term, malformed model output, the rate-limit path, and a requirement contradicting an existing backlog item. | Python | The near-empty epic is the revealing test: a good agent asks questions, a weak one invents a product. | PO-33 | 2.5 | Each scenario tested; none invents product behaviour. | 6 Robustness (8) | MUST

PO-35 | W6 | D29 | P3 PO | — | Docs | README status table, architecture note, decision log | Written from the code, one row per capability, Done / Partial / Not built. | Claude Code (from the repo) | — | PO-34 | 2.0 | Every claim verifiable against a named file. | 7 Repo hygiene (8) | MUST

PO-36 | W6 | D30 | P3 PO | — | Demo | Clean-clone verification | Fresh directory, README only. | Human | — | PO-35 | 1.0 | Runs with zero undocumented steps. | 7 Repo hygiene (8) | MUST

PO-37 | W6 | D30 | P3 PO | — | Demo | Record the walkthrough with a live citation click-through | Context loading, decomposition with citations RESOLVING LIVE, criteria with open questions for the planted gaps, a generic story rejected by the guard, a readiness block with reasons, prioritisation arithmetic shown, an overlap flag, approve and reject with tracker records shown, the eval output. | Human + screen recorder | Clicking one citation live, from generated criterion to the exact section of the brief, is the most convincing ten seconds of the demo. | PO-36 | 2.0 | Recording shows a genuine run with a live citation click-through. | 8 Demo quality (8) | MUST

PO-38 | W6 | D30 | P3 PO | — | Governance | Gate G3 review | Self-score against the rubric. Record scope cuts and what it would take to add them. | Human | — | PO-37 | 1.5 | Self-score sheet completed with evidence per criterion. | 9 Judgement (4) | MUST

PGM-01 | W6 | D30 | Shared | — | Governance | Programme close and cross-agent demo | Consolidated eval report across all three agents. Shared-spine package published internally with its own README. Live cross-agent demo: a P1 channel outcome record consumed by P2 producing approved risk-log entries and by P3 producing candidate backlog items, with no shared code beyond the published schema, and the shared nudge cap holding across both agents. | Claude Code + human | The composition demo is the thing none of the three briefs asks for and the thing that best shows the pod can build an agent estate rather than three apps. | PO-38 | 3.5 | One command runs P1 end to end and both P2 and P3 consume its output with no manual intervention. | 9 Judgement (4) | SHOULD

Effort and capacity summary
TOTAL HOURS | 239.0 | Capacity: 30 working days x 8 hours = 240 hours, and no day exceeds 9 hours. Weeks 1-2 carry 84 hours because the shared spine is built there; weeks 3-4 and 5-6 sit under capacity because they reuse it. That front-loading is the point of the sequence.

Hours by agent
P1 Channel Intelligence | 63.5
P2 PM Delivery Steward | 76.0
P3 PO Backlog Architect | 76.0
Shared spine | 23.5

Hours by priority
MUST | 186.5
SHOULD | 50.5
COULD | 2.0
```


## Appendix C — Six-Week Schedule and Decision Gates, verbatim

```
Six-Week Schedule and Decision Gates
Day-by-day focus with the end-of-day definition of done. Gates are stop-and-decide points, not status meetings — each one names its evidence and its cut rule.

Week | Day | Focus | What gets built | End-of-day definition of done
W1 | D1 | Spine foundations + GRAPH ACCESS SPIKE  ◆ GATE G0b | Repo scaffold · LLM gateway with provider swap and cache · structured-output layer with retry · CHN-01 resolve the Teams permission model | A model responds through one wrapper and a malformed response is caught and retried. One real Teams channel message is read in this tenant, or the blocker is documented with the fallback selected and a dated consent request outstanding.
W1 | D2 | P1 — config, Graph adapter, scope gate | SQLite schema · per-channel configuration (roster, window, timezone, thresholds, exceptions) · Teams reader interface with mock and real Graph implementation · scope gate | Allowlisted channels ingest. The non-allowlisted channel and both chats are refused at the adapter boundary, each refusal logged.
W1 | D3 | P1 — ingestion hardening and seed data | Delta tracking, pagination, throttling, edits and deletes, bot and system messages · 3-channel fixture with rosters and 10 working days of traffic · plant twenty difficulties and write the labels file | Two consecutive delta runs produce a correct incremental set. An edited message keeps its original post time. The fixture reproduces byte-identical.
W1 | D4 | P1 — THIN END-TO-END SLICE  ◆ GATE G0 | Update detection: deterministic rules · classifier for the remainder · participation ledger and non-responder detection with three honest states · prompt registry | A seeded day yields a non-responder set matching hand labels, with the reaction-only, chatter-only and on-leave members each in the correct state.
W1 | D5 | P1 — grounding and first numbers | Grounding kernel (reference-or-drop + verbatim quote verifier) · eval harness framework · golden cases 1, 2, 5 and 10 | First detection precision and an exact-match non-responder number, committed. Zero out-of-scope messages in the store.
W2 | D6 | P1 — daily summary | Per-channel daily summary with a permalink on every factual line · honest participation rendering · golden cases 3, 4 and 9 | Every factual line resolves to a real message; a channel with no traffic produces an honest empty summary; two generations agree on the facts.
W2 | D7 | P1 — approval spine and publishing | Proposal record and status machine · service-layer write guard · scheduled publishing at per-channel local times, idempotent, first publish per channel behind approval · golden case 6 | A clock-override run at three channel-local times produces three correctly timed digests and no duplicates. A pending proposal cannot post.
W2 | D8 | P1 — weekly roll-up and nudges | Weekly roll-up with participation rate and week-on-week trend · golden case 11 · nudge non-responders (opt-in, capped, never the excluded) · publish adapter with mock log and real flow | Every weekly figure recomputes by hand from stored messages. The on-leave member is never nudged under any path and the cap holds across repeated runs.
W2 | D9 | P1 — escalation, config proof, Teams surface, contract | Escalate to the channel owner with a dated evidence bundle · golden cases 7, 8 and 12 · Copilot Studio approval cards and per-channel config · versioned outcome record | With the threshold at three days, exactly the right members escalate. The same day's data under two different rosters produces two different non-responder sets.
W2 | D10 | P1 — harden, measure, demo  ◆ GATE G1 | Full harness across twelve cases · fix the worst finding · edge-case pass · README from the code · clean clone · record the walkthrough · spine extraction | Committed eval results with a documented fix. A clean clone runs with no Graph credentials. Recording shows the refusal and rejection paths. Spine package installs standalone.
W3 | D11 | P2 — seed data and adapters | 25–40 items with transition history · commits, risks, commitments, two P1 outcome records · ten planted difficulties · tracker, code-host and risk-log adapters | Seed committed and reproducible. The chat source is P1's fixture, not a copy, and P1's Teams reader satisfies the chat dependency with no new code.
W3 | D12 | P2 — state and deltas | Project-state snapshot with persistence · snapshot diff engine computed in code · golden case 3 | The item that moved to done and back appears once in the computed delta, described accurately.
W3 | D13 | P2 — THIN END-TO-END SLICE  ◆ GATE G1b | Morning brief · reference-or-drop on every line · absence as absence · scheduler reuse · golden cases 1 and 2 | Every factual line carries a resolvable reference; the zero-activity assignee is reported as having no activity; fabricated-claim count is zero.
W3 | D14 | P2 — approval gate and risk log | Approval gate on the proposal spine · golden case 6 · risk-log store in Dataverse with a committed mirror · gap detection | The two blockers missing from the risk log are proposed; the three already present are not. The audit trail answers who approved what and when.
W3 | D15 | P2 — promotion and rejection memory | Rejection fingerprinting · golden case 4 · blocker-to-risk promotion with a config threshold · golden case 5 · prompt files | Reject one proposal and re-run: no duplicate. Threshold at two days versus four days changes the proposed set correctly.
W4 | D16 | P2 — deltas and commitments | End-of-day summary as genuine deltas · golden case 9 determinism · commitment tracking with nudges, escalation and the SHARED per-person cap | The summary names exactly the hand-labelled changed set. The nudge cap holds across P1 and P2 on the same day.
W4 | D17 | P2 — the cross-agent contract and Teams surface | Golden case 7 · consume P1's channel outcome record · scope and consent refusal · Copilot Studio brief delivery and approvals | P1's record is consumed with no shared code beyond the schema. The record lacking its flag yields zero proposals and one logged refusal.
W4 | D18 | P2 — weekly report and robustness | Weekly status with scope-change detection · quantitative reproducibility · free-text status mapping · similar-name guard | Every figure in the report recomputes from stored snapshots. The unmappable status appears as UNMAPPED with its raw value.
W4 | D19 | P2 — harden and measure | Full harness · fix the worst finding · edge-case pass · README from the code | Committed eval results, a documented fix, and a README that survives being read against the code.
W4 | D20 | P2 — demo  ◆ GATE G2 | Clean clone · recorded walkthrough including the rejection path · gate review · spine hardening for P3 | The rejection path is on camera. Spine tests still pass and P3 starts from the hardened package.
W5 | D21 | P3 — seed data | Product brief of 1,500–3,000 words in numbered sections · glossary with a planted inconsistency · seeded backlog · two epics and two feedback records | All seed artefacts committed with a labels file for the readiness and overlap cases.
W5 | D22 | P3 — citable context | Three planted gaps placed by hand · context index with hand-checkable section references · citation resolver · doc-store adapter · golden case 1 | Ask for context on a topic and get back specific citable sections a human can open. A whole-document reference is invalid by construction.
W5 | D23 | P3 — THIN END-TO-END SLICE  ◆ GATE G2b | Criteria with open questions as a required schema field · grounding enforcement · golden case 2 | All three planted gaps surface as open questions; invented-specific count is zero. This is the headline metric of the P3 submission.
W5 | D24 | P3 — decomposition and the generic guard | Epic decomposition with citations · golden case 4 coverage and redundancy · anti-generic guard with regenerate-on-failure | The detailed epic decomposes into grounded, product-specific stories; ungroundable ones are reported as gaps rather than invented.
W5 | D25 | P3 — readiness gate | Golden case 3 generic rate before and after · Definition of Ready with the checklist as configuration · golden case 5 · prompt files | Two deficient stories blocked for the right reasons, two adequate ones pass, and each block names a specific unmet criterion.
W6 | D26 | P3 — prioritisation | Scoring arithmetic in code with visible inputs · dependency-respecting slice · golden case 6 · golden case 8 thin-epic test | Three scores recompute by hand; a perturbed input moves the rank as predicted; the thin epic yields more open questions than stories.
W6 | D27 | P3 — overlap and the status floor | Overlap detection with relationship types · golden case 7 · draft-back with the not-ready floor enforced in the write path · golden case 9 | Two approvals plus two re-runs produce exactly two records, both tagged AI-drafted, both at not-ready.
W6 | D28 | P3 — stakeholder input and Teams surface | Synthesis from the feedback record and P1 channel outcomes · golden case 10 glossary consistency · Copilot Studio backlog review · batch drafting if green | Product feedback raised in a Teams channel reaches the backlog with its citation intact. The glossary term is used AND the inconsistency is raised.
W6 | D29 | P3 — harden and measure  ◆ GATE G3 | Full harness across ten cases · fix the worst finding · edge-case pass including the near-empty epic · README from the code | The near-empty epic produces questions, not an invented product. All ten metrics committed.
W6 | D30 | P3 demo and programme close  ◆ GATES G3/G4 | Clean clone · walkthrough with a live citation click-through · gate review · consolidated eval report · cross-agent demo | One command runs P1 end to end and both P2 and P3 consume its output through the published schema, with the shared nudge cap holding.

DECISION GATES
Gate | When | Gate question | Evidence required to pass | Cut rule if it does not pass
G0 | W1 D4 | Thin end-to-end slice - P1 participation ledger | A seeded day of channel messages produces a non-responder set matching hand labels, with the reaction-only, chatter-only and on-leave members each in the correct state. | STOP AND FIX. Do not build the daily summary, publishing or nudges until the ledger is right. Everything else in P1 is a renderer over this.
G0b | W1 D1 | Graph access resolved | One real Teams channel message read in this tenant, or the blocker documented with the fallback selected and a consent request dated and outstanding. | Proceed against the mock adapter regardless - it is the scored path. Escalate the consent request; do not wait on it.
G1 | W2 D10 | P1 complete and demoable | All 8 MUST capabilities run end to end on the fixture; 12 golden cases print committed numbers; clean clone verified with no tenant credentials; walkthrough recorded; spine extracted as a package. | Cut C9 weekly trend, then C11 escalation, before degrading C1-C8. Record the cut.
G1b | W3 D13 | Thin end-to-end slice - P2 | A scheduled morning brief generates from a real snapshot with every factual line carrying a resolvable reference and the zero-activity assignee reported honestly. | STOP AND FIX. Do not begin the risk log until reference-or-drop holds.
G2 | W4 D20 | P2 complete and demoable | All 5 MUST capabilities run end to end; 9 golden cases print committed numbers; rejection path recorded on camera; clean clone verified; spine hardened. | Cut P9 before degrading P3. Deltas are the differentiator.
G2b | W5 D23 | Thin end-to-end slice - P3 | Acceptance criteria draft from a story with every citation resolving and all three planted gaps surfacing as open questions rather than invented rules. | STOP AND FIX. Open-question recall is the headline metric and cannot be retrofitted.
G3 | W6 D29 | P3 complete and demoable | All 7 MUST capabilities run end to end; 10 golden cases print committed numbers; live citation click-through works; clean clone verified. | Cut O10 and O11 before degrading O1-O9.
G4 | W6 D30 | Programme close | Consolidated eval report across three agents; shared spine published internally; cross-agent demo showing a P1 channel outcome record consumed by both P2 and P3 through the published schema, with the shared nudge cap holding. | If the cross-agent demo will not hold, ship the three agents separately and record why.
```


## Appendix D — Tool Split — Copilot Studio, Claude, or plain Python, verbatim

```
Tool Split — Copilot Studio, Claude, or plain Python
Thirteen decisions. The governing principle: Copilot Studio owns the human surface, Claude owns language, and plain Python owns every correctness guarantee. Teams is the one real integration in this programme — everything else stays an adapter with a mock.

Concern | Tool | Applies to | Why this tool | Constraint / warning
Build engine - all code, tests, harness, docs | Claude Code | Whole programme | Writes and refactors the Python, generates the eval harness, drafts README and architecture notes from the actual repo. | Copilot Studio has no equivalent. Declare AI-assistant use in the README as the briefs require, and be able to explain every file.
Reading Teams channel messages | Microsoft Graph behind an adapter interface | P1 C2 | Only Graph gives message-level IDs, permalinks, thread replies, edit history and delta change tracking - all four of which the grounding and non-responder logic depend on. | PERMISSION MODEL IS A DAY-1 SPIKE (CHN-01). Bulk application-permission reads are gated by Microsoft; the delegated service-account route is the likely fallback. Nothing downstream is validated until this is settled.
Writing into Teams - digests, nudges, escalations | Power Automate flow bot behind a publish adapter | P1 C7 C10 C11 / P2 P2 P7 | Graph application permission to SEND channel messages is restricted, while an HTTP-triggered flow posting as the flow bot is straightforward and keeps read and write permissions cleanly separated. | Read and write are separate adapters on purpose. A read credential should never be able to post as anyone.
Update-vs-chatter classification | Deterministic rules first, Claude API for the remainder | P1 C4 | Rules settle the clear cases for free and auditably - roster member, inside window, above length floor, not a bot or reaction. The model only handles genuine judgement calls. | Every case a rule settles is a token not spent on a daily job and a decision no reviewer can dispute. Keep the rule set visible in config.
Roster, window, thresholds and exceptions | Python config schema + Dataverse surface | P1 C1 / P2 P6 / P3 O4 | Every non-responder claim is only as defensible as the roster behind it. The channel owner who knows the roster needs to maintain it without a deploy. | The YAML mirror in the repo stays the system of record so the eval harness is reproducible offline.
Non-responder arithmetic, participation states, nudge caps, escalation triggers | Python (no model, no low-code) | P1 C5 C10 C11 | Naming a colleague as silent must be set arithmetic over an explicit roster and window, never a model's impression of who was quiet. | MANDATORY. This must never move into Copilot Studio, whatever the adoption pressure.
Quote verification, citation resolution, delta arithmetic, prioritisation scoring, DoR evaluation, idempotency, scope gating | Python (no model, no low-code) | SPN-06 / P2 P3 P5 / P3 O4 O5 O6 O9 | Every one of these is a correctness guarantee. A guarantee that depends on a model or a low-code expression is not a guarantee. | MANDATORY. Same rule as above.
Prose expression of computed facts | Claude API | P1 C6 C9 / P2 P2 P3 P9 / P3 O5 rationale | The model writes the sentence; the facts, ledgers, deltas and scores are computed in code and passed in. | This split is what lets a digest be regenerated without factual drift.
Evaluation harness and golden cases | Python script, committed results | All 31 golden cases | Weighted at 12 in every rubric, above the user interface. Must run from one command against the MOCK adapters and produce a committed file. | The harness must never need tenant access. If it does, it stops being reproducible and CI stops being possible.
Human review and approval surface - primary | Copilot Studio + Power Automate + Teams adaptive cards | P1 C8 / P2 P5 / P3 O4 O9 | Approving a nudge to a named colleague, or a first digest into a live channel, belongs where that colleague works. | BEST FIT. Enforcement stays in the Python service layer - Copilot Studio is one of two heads on the same API.
Human review and approval surface - scored fallback | Streamlit or CLI | P1 C8 / P2 P5 / P3 O4 O9 | Keeps the repository runnable from a clean clone with zero licensed software and no tenant, which the briefs require and the rubric scores. | Build this FIRST. Copilot Studio is added on top, never instead.
Scheduling | APScheduler in code + Power Automate recurrence | P1 C7 / P2 P2 P3 P6 P7 P9 / P3 O11 | A real scheduler must exist and be visible in the code with a clock override for demos, and P1 needs per-channel local times on working days only. | Power Automate is the organisational trigger. It calls the same scheduled job the code exposes - it does not replace it.
Tracker, code host, document store | Python adapter interface + mock ONLY | P2 P1 P4 / P3 O1 O9 | The briefs cap external writes at L2 and state that a real SaaS integration earns no extra marks while a clean swappable mock earns full marks. | Teams is the one real integration in this programme, because the user asked for a live channel agent. Do not add a second.
```


## Appendix E — Capability Traceability — brief → build → measurement → score, verbatim

```
Capability Traceability — brief → build → measurement → score
Every capability in the three source task catalogs, the golden case that proves it, the metric and target, the WBS tasks that build it, and the rubric criterion it feeds. Four COULD rows are deliberately Not built.

Agent | Cap ID | Priority | Capability | Golden case | Metric | Target | WBS tasks | Rubric criterion
P1 Channel | C1 | MUST | Channel registry and per-channel configuration | GC12 configuration is really configuration | Non-responder set under two different configs | Moves correctly | CHN-02, CHN-24 | 1 Functional coverage
P1 Channel | C2 | MUST | Teams ingestion via Graph with delta tracking | GC10 ingest correctness | Edits, deletes, bot and system messages across two delta runs | All correct | CHN-01, CHN-03, CHN-05, CHN-12 | 1 Functional coverage
P1 Channel | C3 | MUST | Scope gate - allowlist only, chats never read | GC5 scope gate | Out-of-scope messages in the store | 0 | CHN-04, CHN-12 | 3 HITL gating
P1 Channel | C4 | MUST | Update detection - rules then classifier | GC1 update-detection precision and recall | Precision / recall vs hand labels | >= 0.80 / reported | CHN-08, CHN-09, CHN-11 | 1 Functional coverage
P1 Channel | C5 | MUST | Participation ledger and non-responder detection | GC2 non-responder accuracy | Exact set match across the three participation states | Exact | CHN-10, CHN-11, CHN-14 | 1 Functional coverage
P1 Channel | C6 | MUST | Per-channel daily summary with grounding | GC3 citation rate | Factual lines carrying a resolvable message ID | >= 0.95 | SPN-06, CHN-13, CHN-15 | 2 Grounding
P1 Channel | C6 | MUST | Per-channel daily summary with grounding | GC4 fabrication probe | Lines claiming a message, author or decision not in the store | 0 | CHN-14, CHN-15 | 2 Grounding
P1 Channel | C6 | MUST | Per-channel daily summary with grounding | GC9 determinism of facts | Factual divergence across two generations | 0 | CHN-16 | 4 Eval harness
P1 Channel | C7 | MUST | Scheduled daily and weekly publishing | GC6 publish idempotency | Digests per channel per day across three runs | Exactly 1 | CHN-17, CHN-18 | 1 Functional coverage
P1 Channel | C8 | MUST | Approval gate and audit for outbound actions | GC8 approval enforcement | Nudge, escalation and first publish from pending/rejected proposals | All fail | SPN-08, SPN-09, CHN-24 | 3 HITL gating
P1 Channel | C9 | SHOULD | Weekly roll-up with participation trend | GC11 weekly arithmetic reproducibility | Figures recomputable from stored messages | All | CHN-19, CHN-20 | 2 Grounding
P1 Channel | C10 | SHOULD | Nudge non-responders, opt-in and capped | GC7 nudge cap and order | Nudges per person per day / excluded members nudged | <= cap / 0 | CHN-21, CHN-22, CHN-24 | 1 Functional coverage
P1 Channel | C11 | SHOULD | Escalate to the channel owner | GC7 escalation order | Nudge precedes escalation; threshold respected | Correct | CHN-23, CHN-24 | 1 Functional coverage
P1 Channel | C12 | SHOULD | Emit versioned outcome record | Schema round-trip | Day reconstructed without the message store | Pass | CHN-26 | 5 Architecture
P1 Channel | C13 | COULD | Cross-channel question answering | Not planned in the six weeks | — | Not built | — | 9 Judgement
P1 Channel | C14 | COULD | Per-person digest | Not planned in the six weeks | — | Not built | — | 9 Judgement
P2 PM | P1 | MUST | Read project state through adapters | GC3 delta correctness (input) | Two snapshots diffable | Pass | PM-04, PM-05 | 1 Functional coverage
P2 PM | P2 | MUST | Morning brief | GC1 citation rate | Factual lines with a resolvable reference | >= 0.90 | PM-08, PM-09, PM-12 | 2 Grounding
P2 PM | P2 | MUST | Morning brief | GC2 fabrication probe | Fabricated-claim count | 0 | PM-10, PM-12 | 2 Grounding
P2 PM | P2 | MUST | Morning brief | GC9 determinism of facts | Factual divergence across two runs | 0 | PM-23 | 4 Eval harness
P2 PM | P3 | MUST | End-of-day summary | GC3 delta correctness | Precision / recall on the delta set | 1.0 / 1.0 | PM-06, PM-07, PM-22 | 1 Functional coverage
P2 PM | P4 | MUST | Risk-log gap detection | GC4 gap precision and no-duplicate | Precision / recall / duplicates after reject | 1.0 / 1.0 / 0 | PM-15, PM-16, PM-17, PM-18 | 1 Functional coverage
P2 PM | P5 | MUST | Approval gate for all writes | GC6 approval enforcement | Writes from pending/rejected proposals | Both fail | SPN-08, SPN-09, PM-13, PM-14 | 3 HITL gating
P2 PM | P6 | SHOULD | Blocker-to-risk promotion | GC5 promotion threshold | Proposed set at 2-day vs 4-day threshold | Shrinks correctly | PM-19, PM-20 | 1 Functional coverage
P2 PM | P7 | SHOULD | Commitments, nudges, escalation | GC7 nudge cap and order | Nudges per person per day across BOTH agents | <= shared cap | PM-24, PM-25 | 1 Functional coverage
P2 PM | P8 | SHOULD | Consume a channel outcome record | GC8 scope and consent refusal | Proposals from a record lacking the flag / refusals | 0 / 1 | PM-26, PM-27 | 3 HITL gating
P2 PM | P9 | SHOULD | Weekly status report | Quantitative reproducibility | Figures recomputable from snapshots | All | PM-29, PM-30 | 2 Grounding
P2 PM | P10 | COULD | Sprint planning pack | Not planned in the six weeks | — | Not built | — | 9 Judgement
P2 PM | P11 | COULD | Delivery narrative | Not planned in the six weeks | — | Not built | — | 9 Judgement
P3 PO | O1 | MUST | Load and index product context | GC1 citation resolution (input) | Section refs hand-checkable | Pass | PO-06, PO-08 | 2 Grounding
P3 PO | O2 | MUST | Decompose an epic into stories | GC4 coverage and redundancy | Coverage / redundancy | High / low, both reported | PO-13, PO-14 | 1 Functional coverage
P3 PO | O2 | MUST | Decompose an epic into stories | GC8 thin-epic behaviour | Open questions vs stories | Questions > stories | PO-23 | 1 Functional coverage
P3 PO | O3 | MUST | Draft acceptance criteria | GC2 open-question recall | Planted gaps surfaced / invented specifics | 3 of 3 / 0 | PO-10, PO-12 | 2 Grounding
P3 PO | O3 | MUST | Draft acceptance criteria | GC10 glossary consistency | Glossary term used / inconsistency raised | Both pass | PO-29 | 2 Grounding
P3 PO | O4 | MUST | Definition of Ready gate | GC5 readiness gate accuracy | Agreement with 4 labels / specific reasons | 4 of 4 / all specific | PO-17, PO-18 | 1 Functional coverage
P3 PO | O5 | MUST | Prioritise the backlog | GC6 prioritisation reproducibility | Hand-recompute / perturbation / dependency | 3 of 3 / correct / held | PO-20, PO-21, PO-22 | 1 Functional coverage
P3 PO | O6 | MUST | Grounding and citation enforcement | GC1 citation resolution | Unresolvable-citation count | 0 | PO-07, PO-09, PO-11 | 2 Grounding
P3 PO | O7 | SHOULD | Duplicate and overlap detection | GC7 overlap detection | Precision / recall with correct relationship type | 1.0 / 1.0 | PO-24, PO-25 | 1 Functional coverage
P3 PO | O8 | SHOULD | Anti-generic guard | GC3 generic-story rate | Rate before and after the guard | < 0.10 after | PO-15, PO-16 | 1 Functional coverage
P3 PO | O9 | MUST | Draft back to the tracker | GC9 approval and status floor | Records after 2 approvals + 2 re-runs / tag / status | 2 / AI-drafted / not-ready | PO-26, PO-27 | 3 HITL gating
P3 PO | O10 | SHOULD | Synthesise stakeholder input | Consent refusal test | Items from a record lacking consent | 0 | PO-28 | 3 HITL gating
P3 PO | O11 | COULD | Batch criteria drafting | Flagged-only test | Stories drafted vs flagged | Exact match | PO-31 | 1 Functional coverage
P3 PO | O12 | COULD | Release notes draft | Not planned in the six weeks | — | Not built | — | 9 Judgement

Deliberate scope decision: C13, C14, P10, P11 and O12 are COULD rows and are not planned inside the six weeks. Each must be recorded in the relevant README's Not built column with one sentence on how it would be approached. O11 is attempted on D28 only if every MUST is genuinely complete. C13 cross-channel question answering was not requested and is the natural first stretch item once P1 is live.
```


## Appendix F — Evaluation Harness — 31 golden cases, verbatim

```
Evaluation Harness — 31 golden cases
Weighted at 12 points in every rubric, above the user interface. Built into the harness on the day named, never at the end. The harness prints one line per metric with measured value and target, and writes a committed file.

Agent | Case | Name | What is measured | Target | Built on | Note
P1 Channel | GC1 | Update-detection precision and recall | Precision and recall of update-vs-not against hand labels, reported per class | >= 0.80 precision | D5 | Recall matters less than precision here: a missed update is a nuisance, a false 'no update' names an innocent person
P1 Channel | GC2 | Non-responder accuracy | EXACT set match against hand labels across all three participation states | Exact match | D5 | THE headline number for this agent. The reaction-only, chatter-only and on-leave members must each land in the right state
P1 Channel | GC3 | Citation rate | Proportion of factual summary lines carrying a resolvable message ID | >= 0.95 | D6 | Higher than a typical 0.90 because message IDs are exact - there is no excuse for an unresolvable reference
P1 Channel | GC4 | Fabrication probe | Lines claiming a message, author, decision or blocker absent from the store | 0 | D6 | A fluent channel summary nobody can verify is worse than no summary, because it will be believed
P1 Channel | GC5 | Scope gate | Messages in the store from non-allowlisted channels or from any chat | 0 | D5 | Hard zero. This is the one failure that ends the agent's life in the organisation
P1 Channel | GC6 | Publish idempotency | Digests per channel per day after running the job three times | Exactly 1 | D7 | The write log must also show the two suppressed attempts
P1 Channel | GC7 | Nudge cap, exclusions and escalation order | Nudges per person per day; excluded members nudged; nudge before escalation | <= cap / 0 / correct | D9 | Nudging someone on annual leave is the fastest way to have the agent switched off
P1 Channel | GC8 | Approval enforcement | Nudge, escalation and first publish attempted for pending and rejected proposals | All fail | D9 | Tested directly against the service layer, not through the interface
P1 Channel | GC9 | Determinism of facts | Factual divergence across two summary generations from the same window | 0 | D6 | Wording may differ; the participation set, contributors and counts must not
P1 Channel | GC10 | Ingest correctness | Edited, deleted, bot and system messages handled correctly across two delta runs | All correct | D5 | The deleted-only-update case is the one that most easily produces a false accusation
P1 Channel | GC11 | Weekly arithmetic reproducibility | Every figure in the weekly roll-up recomputable from stored messages | All | D8 | Includes the week containing a non-working day
P1 Channel | GC12 | Configuration is really configuration | Non-responder set for the same day under two different rosters and windows | Moves correctly | D9 | Proves the roster and window are not hard-coded - the specific thing the request asked for
P2 PM | GC1 | Citation rate | Proportion of factual brief and summary lines carrying a resolvable reference | >= 0.90 | D13 | A reference that does not resolve to a real seeded item counts as a failure, not a citation
P2 PM | GC2 | Fabrication probe | Lines claiming a transition, commit or message absent from the snapshot | 0 | D13 | THE headline number for this agent. Includes the zero-activity assignee and the empty day
P2 PM | GC3 | Delta correctness | Precision and recall on the hand-labelled changed set, including the twice-moved item | 1.0 / 1.0 | D12 | Deltas are what make this agent more than a dashboard
P2 PM | GC4 | Gap-detection precision | Precision and recall on blockers missing from the risk log; duplicates after rejection | 1.0 / 1.0 / 0 | D15 | The reject-and-rerun assertion is the part most candidates miss
P2 PM | GC5 | Promotion threshold | Proposed set at a two-day threshold versus a four-day threshold | Shrinks correctly | D15 | Proves the threshold is really configuration and not a literal
P2 PM | GC6 | Approval enforcement | Direct service-layer writes for pending and rejected proposals; audit completeness | Both fail / complete | D14 | Audit must answer who approved, when, and what was originally proposed
P2 PM | GC7 | Shared nudge cap and escalation order | Nudges per person per day counting P1's nudges too; nudge before escalation | <= shared cap / correct | D17 | One person chased twice in a day by two different agents is the estate-level failure this catches
P2 PM | GC8 | Scope and consent refusal | Proposals from a channel outcome record lacking the flag; logged refusals | 0 / 1 | D17 | The scope flag carried forward from P1 is what stops out-of-scope content reaching the tracker
P2 PM | GC9 | Determinism of facts | Factual divergence across two generations from the same snapshot | 0 | D16 | Wording may differ; items, owners, counts and statuses must not
P3 PO | GC1 | Citation resolution | Citations not resolving to a real specific section | 0 | D22 | A citation pointing at the whole document counts as unresolvable
P3 PO | GC2 | Open-question recall (fabrication probe) | Planted gaps surfaced as open questions; criteria asserting a value for them | 3 of 3 / 0 | D23 | THE single most important number in the P3 submission
P3 PO | GC3 | Generic-story rate | Hand-labelled generic rate, reported before and after the anti-generic guard | < 0.10 after | D25 | The before-and-after measurement is worth more than the guard itself
P3 PO | GC4 | Decomposition coverage | Coverage of expected capabilities AND redundancy among generated stories | High / low, both reported | D24 | High coverage achieved by generating twenty overlapping stories is not a pass
P3 PO | GC5 | Readiness gate accuracy | Agreement with four hand labels; specificity of each block reason | 4 of 4 / all specific | D25 | A general complaint does not count as a reason
P3 PO | GC6 | Prioritisation reproducibility | Hand-recomputed scores; rank direction under perturbation; dependency order | 3 of 3 / correct / held | D26 | Compute the score in code; use the model only for the rationale sentence
P3 PO | GC7 | Overlap detection | Precision and recall with the correct relationship type on the labelled set | 1.0 / 1.0 | D27 | Four genuinely distinct stories must NOT be flagged
P3 PO | GC8 | Thin-epic behaviour | Open-question count versus story count; invented product behaviour | Questions > stories / 0 | D26 | A confident, complete-looking backlog here is a failure, not a pass
P3 PO | GC9 | Approval and status floor | Writes from pending and rejected drafts; tag and status on written records | Both fail / AI-drafted, not-ready | D27 | The floor must be enforced in the write path, not the prompt
P3 PO | GC10 | Glossary consistency | Glossary term used over the planted variant; the inconsistency raised | Both pass | D28 | Using the right term while staying silent about the conflict is a partial pass only

A harness that reveals a weakness you then explain scores higher than one reporting everything passing. Each agent's hardening day includes: run the full harness, fix the single worst finding, re-run, and commit both numbers with a written explanation.
```


## Appendix G — Seed Data and Planted Difficulties, verbatim

```
Seed Data and Planted Difficulties
The ground truth for every metric in the plan. Claude drafts the prose; the difficulties are placed by hand and recorded in a labels file. A full day per agent is budgeted for this — it is the most commonly underestimated task.

Agent | Artefact | Specification | Day | WBS task
P1 Channel | Teams channels | 2 allowlisted project channels plus 1 channel deliberately NOT on the allowlist | D3 | CHN-06
P1 Channel | Chats | 1 group chat and 1 one-to-one chat that must never be read under any path | D3 | CHN-06
P1 Channel | Messages | 150-250 messages over 10 working days across the allowlisted channels, including thread replies | D3 | CHN-06
P1 Channel | Rosters | 6-8 expected contributors per channel, with 2 members belonging to both channels | D3 | CHN-06
P1 Channel | Config fixtures | Two channel configs with different rosters, update windows, timezones and thresholds | D3 | CHN-06
P1 Channel | Planted difficulty | A member who posts only reactions and emoji - counts as no update | D3 | CHN-07
P1 Channel | Planted difficulty | A member who posts chatter every day but never an update - state (b), not state (a) | D3 | CHN-07
P1 Channel | Planted difficulty | A member on the exceptions list for leave - must never be reported silent or nudged | D3 | CHN-07
P1 Channel | Planted difficulty | A member whose update is a thread reply, not a root message | D3 | CHN-07
P1 Channel | Planted difficulty | A member who posts one minute after the window closes | D3 | CHN-07
P1 Channel | Planted difficulty | A bot or connector post (build notification) that must count as nobody's update | D3 | CHN-07
P1 Channel | Planted difficulty | A system message (member joined the channel) that must not count | D3 | CHN-07
P1 Channel | Planted difficulty | A message edited after the window closed - attributed to its original post time | D3 | CHN-07
P1 Channel | Planted difficulty | A deleted message that was a member's only update that day | D3 | CHN-07
P1 Channel | Planted difficulty | Two members with very similar display names | D3 | CHN-07
P1 Channel | Planted difficulty | A member posting on behalf of another ('posting for Priya - she is blocked on the migration') | D3 | CHN-07
P1 Channel | Planted difficulty | A day with no messages at all in one channel | D3 | CHN-07
P1 Channel | Planted difficulty | A weekend and one configured non-working day | D3 | CHN-07
P1 Channel | Planted difficulty | An @mention that reads like an assignment but is actually a question | D3 | CHN-07
P1 Channel | Planted difficulty | A roster member who has since left the tenant | D3 | CHN-07
P2 PM | Work items | 25-40 items across 2 sprints, 5-7 assignees, transition history with real timestamps | D11 | PM-01
P2 PM | Commits | 30-60 commits referencing some but not all items | D11 | PM-02
P2 PM | Channel messages | Reused from the P1 fixture rather than re-seeded | D11 | PM-02
P2 PM | Risk log | 3 existing entries | D11 | PM-02
P2 PM | Commitments | 6-10, some with due dates, some already overdue | D11 | PM-02
P2 PM | Outcome records | 2 channel outcome records from P1, one missing its scope or consent flag | D11 | PM-02
P2 PM | Planted difficulty | 1 item blocked 4 days with no risk-log entry; another blocked 1 day | D11 | PM-03
P2 PM | Planted difficulty | 1 item moved to done and back to in-progress on the same day | D11 | PM-03
P2 PM | Planted difficulty | 1 assignee with zero activity for two days | D11 | PM-03
P2 PM | Planted difficulty | 1 unassigned item | D11 | PM-03
P2 PM | Planted difficulty | 2 items added mid-sprint after planning | D11 | PM-03
P2 PM | Planted difficulty | Commits with no item reference; 1 item referenced but never transitioned | D11 | PM-03
P2 PM | Planted difficulty | 1 free-text status value that does not map cleanly to the enum | D11 | PM-03
P2 PM | Planted difficulty | 1 commitment with a relative due date only | D11 | PM-03
P2 PM | Planted difficulty | 2 people with similar names | D11 | PM-03
P3 PO | Product brief | 1,500-3,000 words, numbered addressable sections down to paragraph level | D21 | PO-01
P3 PO | Glossary | 15-25 domain terms | D21 | PO-02
P3 PO | Existing backlog | 15-25 items of mixed quality; some with good criteria, some with none | D21 | PO-03
P3 PO | Epics | 1 reasonably detailed, 1 deliberately thin | D21 | PO-04
P3 PO | Feedback records | 1 stakeholder feedback record, and 1 lacking a consent flag | D21 | PO-04
P3 PO | Planted gap | A stated limit with no number ('large files are rejected' - how large?) | D22 | PO-05
P3 PO | Planted gap | A role referenced but never defined ('approvers can override' - who is an approver?) | D22 | PO-05
P3 PO | Planted gap | A state transition with an undefined path ('rejected submissions are returned' - to which state? resubmittable?) | D22 | PO-05
P3 PO | Planted difficulty | 1 term used inconsistently between the brief and the glossary | D21 | PO-02
P3 PO | Planted difficulty | 1 backlog item that overlaps a story the epic will produce | D21 | PO-03
P3 PO | Planted difficulty | 1 requirement that contradicts an existing backlog item | D21 | PO-03
P3 PO | Labelled set | 4 seeded stories labelled ready / not ready with reasons | D21 | PO-03
```


## Appendix H — Adapter Interfaces and Mocks, verbatim

```
Adapter Interfaces and Mocks
One narrow interface per external system, listing only the operations the agents actually use, each backed by a mock over local files or tables. Agent logic imports the interface type and never the mock. The test applied: could a real integration be dropped in by writing one class and changing one wiring line?

Interface | Operations | Mock implementation | Used by | Built | Mock messiness required
Teams reader (READ) | list_channels(), list_channel_members(channel_id), list_messages(channel_id, since | delta_token), list_replies(message_id), get_permalink(message_id) | MockTeamsReader over the committed fixture for CI and the eval harness. GraphTeamsReader as the REAL implementation behind the identical interface. | P1 (C2, C3, C4, C5), P2 (P1 chat source) | W1 D2 (CHN-03) | Edited and deleted messages, bot and connector posts, system messages, thread replies, similar display names, a member who has left the tenant
Teams publisher (WRITE) | post_channel_message(channel_id, card), post_direct_message(user_id, text) | LogPublisher writing every outbound message to an inspectable JSONL log with no network egress. Real implementation posts via an HTTP-triggered Power Automate flow as the flow bot. | P1 (C7, C10, C11), P2 (P2, P3, P7) | W2 D8 (CHN-22) | Read and write are deliberately separate adapters: a read credential must never be able to post as anyone
Channel config store | get_channel_config(channel_id), list_configured_channels(), version() | Committed YAML as the system of record; Dataverse table as the owner-editable surface in Teams. The two are reconciled, not duplicated. | P1 (C1), P2 (P6 thresholds), P3 (O4 checklist) | W1 D2 (CHN-02) | A roster containing a departed member; a channel with no exceptions list; two channels in different timezones
Tracker | list_items(filter), get_item(id), add_comment(id, body, tags), create_item(payload), transition(id, status) | MockTracker over a seeded SQLite table; every write appended to an inspectable write log. No real implementation in these six weeks. | P2 (P1, P4, P5, P8), P3 (O1, O9) | W3 D11 (PM-04) | Missing assignee, stale timestamp, duplicate item, free-text status, no due date
Code host | list_commits(since), get_commit(sha), get_branch_state(ref) | MockCodeHost over a seeded commit fixture, some commits referencing no item. | P2 (P1, P3) | W3 D11 (PM-04) | Commits with no item reference; one item referenced by a commit but never transitioned
Risk log store | list_risks(), get_risk(id), create_risk(payload), update_risk(id, payload) | Dataverse table for the human-facing view plus a committed JSON mirror as system of record. | P2 (P4, P6, P8) | W3 D14 (PM-15) | Three pre-existing entries, two of which match current blockers
Document store | get_document(id), list_sections(doc_id), get_section(ref) | MockDocStore over the committed product brief and glossary, addressable to paragraph level. | P3 (O1, O3, O6) | W5 D22 (PO-08) | One term inconsistent with the glossary; three deliberate silences
Outcome record store | write_outcome(channel_id, date, record), read_outcome(channel_id, date), schema_version() | Versioned JSON files with a published JSON Schema. THE CROSS-AGENT CONTRACT. | P1 (C12) produces; P2 (P8) and P3 (O10) consume | W2 D9 (CHN-26) | Carries the scope and consent flags forward; approved and classified items only

Empty files are worse than missing files. Do not commit a placeholder named after an integration that was not built — an empty adapter file implies a capability that does not exist and is an automatic-failure condition.
Mock writes must be persisted and inspectable (a table, a JSONL log, a file diff) so the demo can show exactly what the agent would have written to the real system, and prove nothing was written without approval.
Do not wire Copilot Studio connectors to a real Jira, SharePoint or Teams data source during these six weeks. All three briefs state that a real SaaS integration earns no extra marks while a clean, swappable mock earns full marks.
```


## Appendix I — Risk Register, verbatim

```
Risk Register
Twelve risks with the mitigation built into the plan and the trigger that catches each one.

ID | Category | Risk | Likelihood | Impact | Mitigation (built into the plan) | Trigger that catches it
R1 | Access | Microsoft gates bulk application-permission reads of channel messages behind admin consent and a protected-API approval, and may meter them. Without a usable permission model P1 cannot read a real channel at all. | High | High | CHN-01 is a day-1 spike, before any dependent work. Fallback selected in advance: delegated ChannelMessage.Read.All via a dedicated service account that is a member of each allowlisted channel. The mock adapter means the harness, CI and the whole demo run with no tenant access whatsoever, so a consent delay slows go-live without stopping the build. | Day 1 DoD
R2 | People | Naming colleagues who have not posted is a management-visible output about named individuals. Wrong once and the agent is switched off permanently. | High | High | Three honest participation states, never collapsed. An exceptions list for leave, honoured everywhere including nudges. Nudges off by default and opt-in per channel. First nudge and first escalation per person behind an approval gate. Neutral wording with no inferred reasons and no ranking of people. GC2 is an exact-match assertion, not a proportion. A written policy sign-off before switch-on in any real channel. | GC2, GC7, CHN-14
R3 | Tooling | Copilot Studio work displacing the scored Python path, leaving a repo that cannot run from a clean clone. | High | High | Build the Streamlit or CLI approval surface FIRST. Copilot Studio is added on top in a capped 2h slot per agent, never instead. The eval harness must never need tenant access. | Clean-clone check each Friday
R4 | Quality | Grounding kernel built late, so weeks of digests ship unverified. | High | Medium | SPN-06 lands on W1 D5 and every downstream capability wires into it. No summary line, brief line or criterion ships without passing through it. | W1 D5 DoD
R5 | Quality | Eval harness deferred to the last days of each agent. | High | Medium | First golden cases land on D5, D13 and D22 - before half the capabilities exist. The harness framework itself is built once in week 1. | Weekly metric commit
R6 | Schedule | Week 2 D10 carries harden, document and demo in one day, because the Graph access and ingestion-hardening work took a day that the original meeting-based scope did not need. | High | Medium | Accept the tight day and protect it: no feature work after D9. If G0 slips, the first cut is C9 weekly trend analysis (keep the weekly totals, drop the week-on-week comparison), then C11 escalation. Alternatively borrow one day from P2, which sits under capacity. | Gate G0 on W1 D4
R7 | Data | Teams message streams are far messier than a chat export: delta-token expiry, throttling, edits, deletes, bot posts and system messages all corrupt the ledger silently if mishandled. | Medium | High | CHN-05 is a dedicated 3h task, and GC10 tests edits, deletes, bot and system messages across two delta runs as a hard assertion rather than a proportion. | GC10
R8 | Schedule | Seed data underestimated; hand-planting twenty difficulties and labelling them takes longer than expected. | Medium | High | A full day is budgeted for the P1 fixture and its labels, and a day per agent thereafter. Claude drafts the message prose; the difficulties are placed by hand. P2 reuses the P1 channel fixture rather than re-seeding. | D3, D11, D21 DoD
R9 | Model | Free-tier rate limits stall an eval run, or a daily classification job costs more than expected as channel volume grows. | Medium | Medium | Rules settle the clear cases so the model sees only the residue. Disk cache keyed by prompt hash from day 1. Local Ollama fallback proven in week 1, not discovered in week 6. Token cost logged per scheduled run. | W1 D1 (SPN-02)
R10 | Honesty | README drifting ahead of the code as the weeks compress. | Medium | High | README written LAST from the code on the final day of each agent, with a Done / Partial / Not built table. Overstating is an automatic failure in the rubric. | D10, D19, D29
R11 | Continuity | Spine copy-pasted between agents instead of reused, tripling maintenance. | Medium | Medium | Spine extracted into an installable internal package at gate G1 with its own tests, hardened again at G2 before P3 starts. P2 inherits two of its five adapters from P1. | CHN-33, PM-40
R12 | Estate | Two agents each politely chasing the same person on the same day, making the estate a nuisance. | Medium | Medium | One shared per-person daily nudge cap enforced across P1 and P2, tested by GC7 in both agents. | GC7 in P1 and P2
R13 | Single point of failure | One individual across six consecutive weeks; illness or leave stops the programme. | Medium | High | Commit daily so state is always recoverable. Keep the decision log current. Each agent is independently demoable at its own gate, so a stop after week 2 or week 4 still leaves shipped, usable work. | Daily commits
R14 | Demo | Recording left to the final afternoon and something breaks. | Low | High | Clean-clone verification is a separate task before the recording, and the recording runs against the mock adapter so it cannot be broken by a tenant or network problem. | D10, D20, D30
```


## Appendix J — Submission Checklist — per agent (Deliverables), verbatim

```
Submission Checklist — per agent
Nine required items per agent, produced three times. Required items are scored; optional items are not, and skipping them costs nothing.

Required? | Deliverable | What must be there | When | WBS task
Required | Public git repository | Full source committed incrementally across the two weeks. History is part of the assessment — one large commit at the end is a red flag. | Daily | All
Required | README with an honest status table | One row per capability from the task catalog marked Done / Partial / Not built with a one-line note. Written LAST, from the code. | D10 / D19 / D29 | MTG-26, PM-37, PO-35
Required | Setup verified from a clean clone | One command to install, one to seed, one to run, plus a .env.example. State the exact model and version used. | D10 / D20 / D30 | MTG-27, PM-38, PO-36
Required | Architecture note | One page or one diagram: components, data flow, where the human approval gate sits, which adapters exist and what they mock. | D10 / D19 / D29 | MTG-26, PM-37, PO-35
Required | Adapter interfaces plus mocks | One interface per external system, each with a mock backed by local data returning realistically messy records. | Ongoing | See sheet 07
Required | Evaluation harness plus committed results | A script running the golden cases and printing per-metric scores, plus the output file from the final run. | D9 / D19 / D29 | MTG-21, PM-34, PO-32
Required | Decision and assumption log | Scope cuts, assumptions about ambiguous requirements, known limitations. Bullet points are fine; brevity is fine. | Daily | All gate tasks
Required | Recorded walkthrough, 5–10 minutes | A genuine end-to-end run on sample data including one edge case or failure being handled. No slides. | D10 / D20 / D30 | MTG-28, PM-39, PO-37
Required | Sample data used | The seed data in the repo so the run is exactly reproducible. | D2 / D11 / D21 | See sheet 06
Optional | Deployed public URL | Not scored. Local plus a recording scores identically. | — | —
Optional | Container / compose setup | Helpful for reproducibility, not required. | D1 | SPN-01
Optional | Stretch work | Only after every MUST capability is genuinely done. Note separately so it is scored as stretch. | D28 | PO-31, PGM-01

The README status table is the item most often skipped and the one that most changes how a submission is read. It costs fifteen minutes and it protects the work: a capability honestly marked Partial is assessed as partial, whereas the same capability implied complete is assessed as misrepresentation — which ends the evaluation regardless of build quality.
```
