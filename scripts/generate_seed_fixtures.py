"""
Generate seed/fixtures/{channels,members,messages}.json (CHN-06) and
seed/fixtures/labels.csv (CHN-07).

Deterministic (fixed random seed) -- re-running this always produces
byte-identical output. Run once and commit the resulting files;
scripts/seed.py loads them, it does not regenerate them.

Two layers of content:
  1. Organic messages: randomly generated update/question/blocker/chatter
     traffic across 3 channels + 2 chats, 10 working days. A handful of
     roster members have a fixed behavioural override (on-leave, chatter-
     only, reaction-only) that shapes the organic stream itself, because
     those cases have to hold for the *entire* window, not just one
     message. SKIP_ORGANIC_AUTHOR_ON_DAY additionally excludes specific
     (channel, date, author) combinations from the random draw wherever a
     planted difficulty below depends on being that member's *only*
     activity that day -- decided up front, not discovered by luck of the
     seed.
  2. Planted difficulties (CHN-07): exactly the 15 named cases specified
     in source sheet 06 (Seed Data and Planted Difficulties) -- no more,
     no fewer. Each has a fixed, human-readable message id so
     seed/fixtures/labels.csv can reference them by id forever,
     independent of the random stream. This script is the single source
     of truth for both the fixtures and their hand labels -- they cannot
     drift apart because the same loop that creates a planted message
     also appends its label row.

     Three earlier categories (duplicate double-post, cross-channel
     identity, mismatched timezone) were dropped in this rework: none of
     the three appears in sheet 06's list, and the first two are already
     covered structurally by ordinary CHN-06 base requirements (a shared
     roster member across channels; nothing here specifically calls for
     a double-post case). Keeping them alongside the real 15 only
     invited the same "does this count or not" confusion this rework
     exists to resolve.
"""
import csv
import json
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

random.seed(42)

FIXTURES_DIR = Path("seed/fixtures")

ALPHA = "19:proj-alpha@thread.tacv2"
BETA = "19:proj-beta@thread.tacv2"
GAMMA = "19:proj-gamma@thread.tacv2"
GROUP_CHAT_ID = "19:groupchat_9f2a1c@unq.gbl.spaces"
ONE_TO_ONE_CHAT_ID = "19:oneonone_7b3e44@unq.gbl.spaces"

CHANNELS = [
    {"id": ALPHA, "display_name": "Project Alpha"},
    {"id": BETA, "display_name": "Project Beta"},
    {"id": GAMMA, "display_name": "Project Gamma"},
]

# Config-side roster (system of record, CHN-02) -- what each channel's
# non-responder arithmetic is computed over. This must mirror
# config/channels/*.yaml exactly, with one deliberate exception: BETA's
# YAML roster also includes "sofia.almeida" (DIFF-DEPART-01, see below),
# who is intentionally left OUT of this dict so she never enters the
# organic author pool or the Teams-membership list built from it.
ROSTERS = {
    ALPHA: [
        "priya.sharma", "james.okafor", "wei.chen",
        "fatima.hassan", "liam.oconnor", "sara.johansson",
    ],
    BETA: [
        "james.okafor", "wei.chen", "diego.martinez",
        "amara.okonkwo", "kenji.tanaka", "elena.rossi",
    ],
    GAMMA: [
        "noah.becker", "aisha.rahman", "wei.chen",
        "olivia.dupont", "mateo.silva", "olivia.dupree",
    ],
}

# Teams-side membership (what list_channel_members returns) -- deliberately
# NOT identical to the config roster for two reasons:
#   - "ci-bot" is a Teams member of proj-alpha (bots show up as channel
#     members in Graph) but was never on the roster -- bots are never
#     asked for an update.
#   - "sofia.almeida" is on proj-beta's *config* roster (config/channels/
#     proj-beta.yaml) -- she is still an expected contributor as far as
#     the system of record is concerned -- but is deliberately absent
#     from both this dict and ROSTERS[BETA] above, so she never appears
#     in list_channel_members. That is DIFF-DEPART-01: a roster member
#     who has since left the tenant. She has real posting history (see
#     the plant() calls below) from before she left.
TEAMS_MEMBERSHIP_EXTRA = {
    ALPHA: ["ci-bot"],
    BETA: [],
    GAMMA: [],
}

CHAT_ROSTERS = {
    GROUP_CHAT_ID: ["priya.sharma", "diego.martinez", "noah.becker"],
    ONE_TO_ONE_CHAT_ID: ["priya.sharma", "james.okafor"],
}

CHANNEL_TZ = {
    ALPHA: ZoneInfo("Asia/Colombo"),
    BETA: ZoneInfo("America/New_York"),
    GAMMA: ZoneInfo("Asia/Colombo"),
}

UPDATE_WINDOW = {
    ALPHA: (time(9, 0), time(11, 0)),
    BETA: (time(8, 0), time(10, 0)),
    GAMMA: (time(9, 0), time(11, 0)),
}

# Members with a fixed behavioural override for the whole window.
ON_LEAVE = {ALPHA: "liam.oconnor"}          # DIFF-LEAVE-01 (state c: excluded)
CHATTER_ONLY = {ALPHA: "fatima.hassan"}     # DIFF-CHATTER-01 (state b: posted, no update)
REACTION_ONLY = {GAMMA: "aisha.rahman"}     # DIFF-REACTION-01 (state a: no message at all)

# Specific (channel_id, date, member_id) combinations excluded from the
# random organic draw, decided up front, because a planted difficulty
# below depends on that exact combination being the member's *only*
# activity that day. Without this, the random stream could -- by luck of
# the seed -- hand the same (channel, day, author) an extra organic
# message and quietly invalidate the "only update that day" premise of
# the deleted-message, thread-reply-only and late-post cases.
SKIP_ORGANIC_AUTHOR_ON_DAY = {
    (ALPHA, date(2025, 6, 3), "sara.johansson"),    # DIFF-DEL-01
    (ALPHA, date(2025, 6, 9), "wei.chen"),           # DIFF-DEL-02
    (GAMMA, date(2025, 6, 12), "mateo.silva"),       # DIFF-DEL-03
    (ALPHA, date(2025, 6, 12), "james.okafor"),      # DIFF-THREAD-01 (reply-only)
    (BETA, date(2025, 6, 10), "amara.okonkwo"),      # DIFF-LATE-01
}


def display_name(member_id: str) -> str:
    parts = member_id.split(".")
    return " ".join(p.capitalize() for p in parts)


WORKING_DAYS = [
    date(2025, 6, 2), date(2025, 6, 3), date(2025, 6, 4),
    date(2025, 6, 5), date(2025, 6, 6),
    # weekend: 2025-06-07 (Sat), 2025-06-08 (Sun) -- deliberately no messages
    date(2025, 6, 9), date(2025, 6, 10), date(2025, 6, 11),
    date(2025, 6, 12), date(2025, 6, 13),
]

SILENT_CHANNEL = BETA
SILENT_DAY = date(2025, 6, 11)   # DIFF-SILENT-01: whole-channel silent day

# DIFF-NONWORKING-01: a weekday that is NOT a calendar weekend but is
# excluded via config/channels/proj-alpha.yaml's non_working_dates. Must
# mirror that file exactly.
NON_WORKING_DATES = {ALPHA: [date(2025, 6, 13)]}

FEATURES = ["the auth flow", "the export job", "the search index",
            "the notification service", "the billing sync",
            "the onboarding wizard", "the reporting dashboard",
            "the retry queue", "the audit log", "the caching layer"]

UPDATE_TEMPLATES = [
    "Finished {feature}, running the test suite now.",
    "Deployed {feature} to staging, looks stable so far.",
    "Merged the PR for {feature}, moving on to the next item.",
    "Wrapped up code review on {feature}, no major issues found.",
    "{feature} is passing all integration tests locally.",
    "Pushed the fix for {feature}, should resolve the flaky test.",
    "Started work on {feature} today, will have an update tomorrow.",
]

QUESTION_TEMPLATES = [
    "Does anyone know why {feature} is timing out in staging?",
    "Should {feature} handle the null case, or is that out of scope?",
    "Can someone review my PR for {feature} when they get a chance?",
    "Is {feature} supposed to run nightly or on every deploy?",
]

BLOCKER_TEMPLATES = [
    "Blocked on {feature} -- waiting on the API credentials from IT.",
    "{feature} is blocked, the staging DB migration hasn't run yet.",
    "Can't proceed on {feature} until the design doc is signed off.",
]

CHATTER_TEMPLATES = [
    "Thanks!", "Sounds good.", "Will do.", "Sure, on it.",
    "Got it, thanks for the heads up.", "Nice work on that.",
    "Sure thing.", "Ack.", "Perfect, thank you.",
]

REPLY_TEMPLATES = [
    "Sounds good, thanks for the update.",
    "Nice, let me know if you need a second reviewer.",
    "Got it -- I'll follow up on my end.",
    "Thanks for flagging this.",
    "Can you share the PR link?",
]


def random_body(kind: str) -> str:
    feature = random.choice(FEATURES)
    if kind == "update":
        return random.choice(UPDATE_TEMPLATES).format(feature=feature)
    if kind == "question":
        return random.choice(QUESTION_TEMPLATES).format(feature=feature)
    if kind == "blocker":
        return random.choice(BLOCKER_TEMPLATES).format(feature=feature)
    return random.choice(CHATTER_TEMPLATES)


message_counter = 0


def new_id(prefix: str) -> str:
    global message_counter
    message_counter += 1
    return f"{prefix}-{message_counter:04d}"


def base_message(msg_id, channel_id, author_id, posted, body, **overrides):
    msg = {
        "id": msg_id, "channel_id": channel_id, "author_id": author_id,
        "thread_root_id": None, "posted_at": posted.isoformat(),
        "edited_at": None, "deleted_at": None, "is_deleted": False,
        "is_bot": False, "is_system": False, "body": body,
        "permalink": f"https://teams.microsoft.com/l/message/{channel_id}/{msg_id}",
    }
    msg.update(overrides)
    return msg


def gen_messages_for_channel(channel_id, roster, days, msgs_per_day_range=(4, 10)):
    tz = CHANNEL_TZ.get(channel_id, ZoneInfo("UTC"))
    on_leave = ON_LEAVE.get(channel_id)
    chatter_only = CHATTER_ONLY.get(channel_id)
    reaction_only = REACTION_ONLY.get(channel_id)
    excluded_always = {m for m in (on_leave, reaction_only) if m}
    non_working = set(NON_WORKING_DATES.get(channel_id, []))
    out = []
    for day in days:
        if channel_id == SILENT_CHANNEL and day == SILENT_DAY:
            continue  # deliberate channel-silent day (DIFF-SILENT-01)
        if day in non_working:
            continue  # configured non-working day (DIFF-NONWORKING-01)
        skip_today = {
            member for (ch, d, member) in SKIP_ORGANIC_AUTHOR_ON_DAY
            if ch == channel_id and d == day
        }
        author_pool = [m for m in roster if m not in excluded_always and m not in skip_today]
        if not author_pool:
            continue
        n = random.randint(*msgs_per_day_range)
        for _ in range(n):
            author = random.choice(author_pool)
            hour = random.randint(8, 16)
            minute = random.randint(0, 59)
            posted = datetime.combine(day, time(hour, minute), tzinfo=tz)
            kind = "chatter" if author == chatter_only else random.choices(
                ["update", "question", "blocker", "chatter"],
                weights=[0.55, 0.15, 0.10, 0.20],
            )[0]
            msg_id = new_id(channel_id.split(":")[1].split("@")[0])
            msg = base_message(msg_id, channel_id, author, posted, random_body(kind))
            out.append(msg)
            if random.random() < 0.25:
                reply_pool = [m for m in author_pool]
                replier = random.choice(reply_pool)
                reply_posted = posted + timedelta(minutes=random.randint(5, 90))
                reply_id = new_id(channel_id.split(":")[1].split("@")[0])
                out.append(base_message(
                    reply_id, channel_id, replier, reply_posted,
                    random.choice(REPLY_TEMPLATES), thread_root_id=msg_id,
                ))
    return out


messages_out = {
    ALPHA: gen_messages_for_channel(ALPHA, ROSTERS[ALPHA], WORKING_DAYS),
    BETA: gen_messages_for_channel(BETA, ROSTERS[BETA], WORKING_DAYS),
    GAMMA: gen_messages_for_channel(GAMMA, ROSTERS[GAMMA], WORKING_DAYS, msgs_per_day_range=(1, 3)),
    GROUP_CHAT_ID: gen_messages_for_channel(GROUP_CHAT_ID, CHAT_ROSTERS[GROUP_CHAT_ID], WORKING_DAYS, msgs_per_day_range=(0, 2)),
    ONE_TO_ONE_CHAT_ID: gen_messages_for_channel(ONE_TO_ONE_CHAT_ID, CHAT_ROSTERS[ONE_TO_ONE_CHAT_ID], WORKING_DAYS, msgs_per_day_range=(0, 2)),
}

# ---------------------------------------------------------------------------
# CHN-07: the 15 planted difficulties named in source sheet 06, fixed ids,
# appended after organic generation. LABELS accumulates the ground-truth
# row for each one. A category may have more than one instance (bot post,
# edited message, deleted message) where a single example would make the
# eval harness's precision/recall numbers meaningless; the assertion below
# checks the 15 DISTINCT categories, not the row count.
# ---------------------------------------------------------------------------
LABELS = []


def plant(channel_id, msg_id, author_id, posted, body, **overrides):
    msg = base_message(msg_id, channel_id, author_id, posted, body, **overrides)
    messages_out.setdefault(channel_id, []).append(msg)
    return msg


def label(difficulty_id, category, channel_id, member_id, message_ids, day, description, expected_ground_truth):
    LABELS.append({
        "difficulty_id": difficulty_id,
        "category": category,
        "channel_id": channel_id or "",
        "member_id": member_id or "",
        "message_ids": ";".join(message_ids) if message_ids else "",
        "date": day,
        "description": description,
        "expected_ground_truth": expected_ground_truth,
    })


TZ_ALPHA = CHANNEL_TZ[ALPHA]
TZ_BETA = CHANNEL_TZ[BETA]
TZ_GAMMA = CHANNEL_TZ[GAMMA]

# --- 1. Edited message, attributed to original post time (sheet 06) ------
# All three edits happen AFTER the channel's update window has closed for
# that day; posted_at (the ORIGINAL post, on time) must remain the record
# of when the update happened, never overwritten by edited_at.
edit_specs = [
    (ALPHA, "priya.sharma", datetime(2025, 6, 2, 9, 30, tzinfo=TZ_ALPHA), 110,
     "Finished the auth flow, running the tests now.",
     "Finished the auth flow, running the test suite now -- fixed a typo."),
    (ALPHA, "james.okafor", datetime(2025, 6, 4, 10, 50, tzinfo=TZ_ALPHA), 20,
     "Deployed the export job to staging.",
     "Deployed the export job to staging -- added the missing rollback step."),
    (BETA, "diego.martinez", datetime(2025, 6, 5, 8, 10, tzinfo=TZ_BETA), 125,
     "Blocked on the billing sync, waiting on IT.",
     "Blocked on the billing sync -- waiting on the API credentials from IT."),
]
for i, (ch, author, posted, delay_min, orig_body, new_body) in enumerate(edit_specs, start=1):
    msg_id = f"diff-edit-{i:02d}"
    window_end = UPDATE_WINDOW[ch][1]
    edited_at = posted + timedelta(minutes=delay_min)
    assert edited_at.time() > window_end, f"{msg_id}: edit must land after the update window closes"
    plant(ch, msg_id, author, posted, new_body, edited_at=edited_at.isoformat())
    label(f"DIFF-EDIT-{i:02d}", "edited_message", ch, author, [msg_id],
          posted.date().isoformat(),
          f"Posted on time at {posted.time()}; edited {delay_min} min later at {edited_at.time()} "
          f"({window_end} window close already passed); original text was: {orig_body!r}",
          "posted_at must remain the original, on-time post time; a post-window edit must not "
          "invalidate an on-time update or be treated as a second, late one")

# --- 2. Deleted message that was a member's only update that day ---------
# SKIP_ORGANIC_AUTHOR_ON_DAY guarantees each of these is genuinely the
# member's only message that day, so its deletion leaves them with zero
# visible activity for the day.
del_specs = [
    (ALPHA, "sara.johansson", datetime(2025, 6, 3, 9, 15, tzinfo=TZ_ALPHA),
     "Started work on the search index today, will have an update tomorrow."),
    (ALPHA, "wei.chen", datetime(2025, 6, 9, 10, 40, tzinfo=TZ_ALPHA),
     "Pushed the fix for the caching layer, should resolve the flaky test."),
    (GAMMA, "mateo.silva", datetime(2025, 6, 12, 9, 20, tzinfo=TZ_GAMMA),
     "Blocked on the audit log, design doc isn't signed off yet."),
]
for i, (ch, author, posted, orig_body) in enumerate(del_specs, start=1):
    msg_id = f"diff-del-{i:02d}"
    assert (ch, posted.date(), author) in SKIP_ORGANIC_AUTHOR_ON_DAY
    plant(ch, msg_id, author, posted, "",
          deleted_at=(posted + timedelta(minutes=25)).isoformat(), is_deleted=True)
    label(f"DIFF-DEL-{i:02d}", "deleted_message", ch, author, [msg_id],
          posted.date().isoformat(),
          f"Message deleted ~25 min after posting; this was the member's only message that day; "
          f"original text was: {orig_body!r}",
          "must never count as an update for participation; the day reverts to a genuine "
          "no-message day for this member, not a fabricated one")

# --- 3. Bot / connector post -----------------------------------------------
bot_specs = [
    (datetime(2025, 6, 4, 7, 0, tzinfo=TZ_ALPHA), "Nightly build for proj-alpha: PASSED (142/142 tests)."),
    (datetime(2025, 6, 11, 7, 0, tzinfo=TZ_ALPHA), "Nightly build for proj-alpha: FAILED -- 2 tests, see CI run #4821."),
]
for i, (posted, body) in enumerate(bot_specs, start=1):
    msg_id = f"diff-bot-{i:02d}"
    plant(ALPHA, msg_id, "ci-bot", posted, body, is_bot=True)
    label(f"DIFF-BOT-{i:02d}", "bot_post", ALPHA, "ci-bot", [msg_id],
          posted.date().isoformat(),
          "Automated CI bot post; ci-bot is a Teams channel member but is not on the config roster",
          "ignore_bots=true for proj-alpha: must never be attributed to a person or counted as anyone's update")

# --- 4. System message: a member joined the channel -----------------------
sys_posted = datetime(2025, 6, 9, 8, 0, tzinfo=TZ_BETA)
plant(BETA, "diff-sys-01", None, sys_posted, "Kenji Tanaka was added to the channel.", is_system=True)
label("DIFF-SYS-01", "system_post", BETA, None, ["diff-sys-01"], sys_posted.date().isoformat(),
      "Teams-generated 'member joined the channel' notice; author_id is null",
      "must never be attributed to a person or counted as anyone's update")

# --- 5. Roster member who has since left the tenant (direction corrected) -
# sofia.almeida is on config/channels/proj-beta.yaml's roster (still an
# expected contributor as far as the system of record goes) but is
# deliberately absent from ROSTERS[BETA] and TEAMS_MEMBERSHIP_EXTRA above,
# so list_channel_members never returns her. She has real posting history
# from before she left, then nothing.
depart_days = WORKING_DAYS[:3]
depart_msg_ids = []
for i, day in enumerate(depart_days, start=1):
    posted = datetime.combine(day, time(8, 30), tzinfo=TZ_BETA)
    msg_id = f"diff-depart-{i:02d}"
    plant(BETA, msg_id, "sofia.almeida", posted,
          random.choice(UPDATE_TEMPLATES).format(feature=random.choice(FEATURES)))
    depart_msg_ids.append(msg_id)
label("DIFF-DEPART-01", "departed_tenant_member", BETA, "sofia.almeida", depart_msg_ids,
      depart_days[0].isoformat(),
      "sofia.almeida is on channel_config.roster for proj-beta (still expected) but is no longer "
      "returned by list_channel_members -- she left the tenant. She posted through "
      f"{depart_days[-1].isoformat()}, then nothing for the rest of the window.",
      "participation must be computed over the config roster, not over live Graph membership -- she "
      "must still be tracked rather than silently dropped just because Graph no longer lists her as "
      "a member; her post-departure silence is evaluated the same as any roster member's absence, "
      "since tenant-departure detection is not itself a built capability yet")

# --- 6. Two members with very similar display names ------------------------
name_posted = datetime(2025, 6, 10, 9, 30, tzinfo=TZ_GAMMA)
name_msg_id = "diff-name-01"
plant(GAMMA, name_msg_id, "olivia.dupree", name_posted,
      "Merged the PR for the reporting dashboard, moving on to the next item.")
label("DIFF-NAME-01", "similar_names", GAMMA, "olivia.dupree", [name_msg_id],
      name_posted.date().isoformat(),
      "proj-gamma roster has both olivia.dupont and olivia.dupree -- same first name, one letter apart",
      "must be tracked as two distinct people keyed by member_id, never merged or fuzzy-matched by display name")

# --- 7. A member whose update is a thread reply, not a root message -------
# james.okafor's ONLY activity on 2025-06-12 is this reply (guaranteed by
# SKIP_ORGANIC_AUTHOR_ON_DAY); it must still count as his update for the
# day since count_thread_replies=true for proj-alpha.
thread_root_posted = datetime(2025, 6, 12, 9, 45, tzinfo=TZ_ALPHA)
thread_root_id = "diff-thread-01-root"
plant(ALPHA, thread_root_id, "priya.sharma", thread_root_posted,
      "Should the reporting dashboard handle the null case, or is that out of scope?")
thread_reply_id = "diff-thread-01-reply-1"
thread_reply_posted = thread_root_posted + timedelta(minutes=10)
plant(ALPHA, thread_reply_id, "james.okafor", thread_reply_posted,
      "Out of scope for v1 -- I'll file a follow-up ticket and link it here.",
      thread_root_id=thread_root_id)
label("DIFF-THREAD-01", "thread_reply_only_update", ALPHA, "james.okafor",
      [thread_root_id, thread_reply_id], thread_root_posted.date().isoformat(),
      "james.okafor's only message on 2025-06-12 is a reply to priya.sharma's root question, not a "
      "root message of his own",
      "count_thread_replies=true for proj-alpha: the reply alone must count as his update for the day")

# --- 8. A member who posts one minute after the window closes -------------
# amara.okonkwo's ONLY activity on 2025-06-10 is this post (guaranteed by
# SKIP_ORGANIC_AUTHOR_ON_DAY), one minute after proj-beta's window closes.
late_posted = datetime(2025, 6, 10, 10, 1, tzinfo=TZ_BETA)
late_msg_id = "diff-late-01"
plant(BETA, late_msg_id, "amara.okonkwo", late_posted,
      "Merged the PR for the retry queue, moving on to the caching layer.")
label("DIFF-LATE-01", "late_post_after_window", BETA, "amara.okonkwo", [late_msg_id],
      late_posted.date().isoformat(),
      "amara.okonkwo's only message on 2025-06-10, posted at 10:01 America/New_York -- one minute "
      "after proj-beta's update_window_end (10:00:00)",
      "must not satisfy the day's update requirement even though the content would otherwise "
      "qualify -- the window close is a hard boundary, not a suggestion")

# --- 9. A member posting on behalf of another ------------------------------
onbehalf_posted = datetime(2025, 6, 3, 10, 15, tzinfo=TZ_ALPHA)
onbehalf_msg_id = "diff-onbehalf-01"
plant(ALPHA, onbehalf_msg_id, "james.okafor", onbehalf_posted,
      "Posting for Priya -- she's blocked on the migration and asked me to update the channel.")
label("DIFF-ONBEHALF-01", "posting_on_behalf_of_another", ALPHA, "james.okafor", [onbehalf_msg_id],
      onbehalf_posted.date().isoformat(),
      "james.okafor posts an update on priya.sharma's behalf; the message text names her, but he "
      "is the author",
      "must be attributed to and counted as james.okafor's update; priya.sharma must never be "
      "credited for a message she did not post, however the text reads")

# --- 10. An @mention that reads like an assignment but is actually a ------
#         question
mention_posted = datetime(2025, 6, 10, 10, 0, tzinfo=TZ_ALPHA)
mention_msg_id = "diff-mention-01"
plant(ALPHA, mention_msg_id, "sara.johansson", mention_posted,
      "@james.okafor should this run before the deploy, or after -- trying to get the order right.")
label("DIFF-MENTION-01", "ambiguous_mention_as_question", ALPHA, "sara.johansson", [mention_msg_id],
      mention_posted.date().isoformat(),
      "sara.johansson @-mentions james.okafor in a message that reads like it could be assigning "
      "him a task, but is grammatically a question",
      "must be classified as a question raised by sara.johansson, not as a task assignment to "
      "james.okafor")

# --- 11. A day with no messages at all in one channel ----------------------
# Pre-existing structural mechanic (SILENT_CHANNEL / SILENT_DAY above),
# documented here so labels.csv is the complete, authoritative list of
# all 15 categories.
label("DIFF-SILENT-01", "channel_silent_day", BETA, None, [],
      SILENT_DAY.isoformat(),
      "proj-beta has zero messages -- organic or planted -- on 2025-06-11, an otherwise ordinary "
      "working day",
      "must be reported as an honest empty day for every roster member, never fabricated or silently "
      "skipped")

# --- 12. A weekend and one configured non-working day ----------------------
# The weekend (2025-06-07/08) is structural: WORKING_DAYS simply never
# includes those dates for any channel. This label covers the second,
# distinct half of the sheet-06 case: a weekday that config explicitly
# excludes via non_working_dates, which working_days (a recurring Mon-Fri
# pattern) cannot express on its own.
non_working_day = NON_WORKING_DATES[ALPHA][0]
label("DIFF-NONWORKING-01", "configured_non_working_day", ALPHA, None, [],
      non_working_day.isoformat(),
      f"{non_working_day.isoformat()} is a Friday (not a calendar weekend) but is listed in "
      "config/channels/proj-alpha.yaml's non_working_dates",
      "must never be counted as a missed-update day for any proj-alpha roster member, distinctly "
      "from the ordinary weekend that brackets it")

# --- 13. A member who posts only reactions and emoji -- counts as no ------
#         update
# Teams reactions are a separate, unread Graph API -- invisible to this
# system entirely. The only honest representable form of "reacts a lot,
# never posts a real update" is a member who generates zero messages for
# the whole window, exactly like ON_LEAVE -- with one deliberate
# difference: she is NOT on the exceptions list, so (once built) the
# participation ledger must report her as a genuine non-responder, not as
# excluded. This is the contrast that makes the case worth planting.
label("DIFF-REACTION-01", "reaction_only_member", GAMMA, "aisha.rahman", [],
      "2025-06-02..2025-06-13",
      "aisha.rahman generates zero messages for the entire seeded window (in real Teams she is "
      "assumed to be reacting to others' messages, which Graph does not expose to this system)",
      "must be reported as a genuine non-responder for every day in the window -- unlike "
      "liam.oconnor (DIFF-LEAVE-01), she is not on the exceptions list, so her silence must never "
      "be excused")

# --- 14. A member who posts chatter every day but never an update --------
label("DIFF-CHATTER-01", "chatter_only_member", ALPHA, "fatima.hassan", [],
      "2025-06-02..2025-06-13",
      "Every organically generated message from fatima.hassan is chatter-kind (e.g. 'Thanks!', "
      "'Sounds good.'), never an update/question/blocker",
      "on days she posts: posted_no_update, not no_message and not credited as a real update")

# --- 15. A member on the exceptions list for leave -------------------------
label("DIFF-LEAVE-01", "on_leave_member", ALPHA, "liam.oconnor", [],
      "2025-06-02..2025-06-13",
      "liam.oconnor is on channel_config.exceptions for proj-alpha (annual leave) and organically "
      "generates zero messages for the entire seeded window",
      "must appear as excluded, never as a non-responder, and must never be nudged under any path (R2)")

EXPECTED_CATEGORIES = {
    "edited_message", "deleted_message", "bot_post", "system_post",
    "departed_tenant_member", "similar_names", "thread_reply_only_update",
    "late_post_after_window", "posting_on_behalf_of_another",
    "ambiguous_mention_as_question", "channel_silent_day",
    "configured_non_working_day", "reaction_only_member",
    "chatter_only_member", "on_leave_member",
}
actual_categories = {row["category"] for row in LABELS}
assert actual_categories == EXPECTED_CATEGORIES, (
    f"planted-difficulty categories drifted from sheet 06's 15: "
    f"missing={EXPECTED_CATEGORIES - actual_categories}, "
    f"unexpected={actual_categories - EXPECTED_CATEGORIES}"
)
assert len(EXPECTED_CATEGORIES) == 15, "sheet 06 names exactly 15 planted difficulties for P1"

# ---------------------------------------------------------------------------
# Assemble channels/members and write output
# ---------------------------------------------------------------------------
channels_out = list(CHANNELS)  # chats deliberately excluded -- see CHN-04

members_out = {}
for ch_id, roster in {**ROSTERS, **CHAT_ROSTERS}.items():
    ids = list(roster) + TEAMS_MEMBERSHIP_EXTRA.get(ch_id, [])
    members_out[ch_id] = [{"id": m, "display_name": display_name(m)} for m in ids]

FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
(FIXTURES_DIR / "channels.json").write_text(json.dumps(channels_out, indent=2) + "\n")
(FIXTURES_DIR / "members.json").write_text(json.dumps(members_out, indent=2) + "\n")
(FIXTURES_DIR / "messages.json").write_text(json.dumps(messages_out, indent=2) + "\n")

with open(FIXTURES_DIR / "labels.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "difficulty_id", "category", "channel_id", "member_id",
        "message_ids", "date", "description", "expected_ground_truth",
    ])
    writer.writeheader()
    writer.writerows(LABELS)

alpha_count = len(messages_out[ALPHA])
beta_count = len(messages_out[BETA])
gamma_count = len(messages_out[GAMMA])
group_count = len(messages_out[GROUP_CHAT_ID])
oneonone_count = len(messages_out[ONE_TO_ONE_CHAT_ID])
total = alpha_count + beta_count + gamma_count + group_count + oneonone_count
print(f"proj-alpha messages: {alpha_count}")
print(f"proj-beta messages:  {beta_count}")
print(f"Allowlisted total:   {alpha_count + beta_count}")
print(f"proj-gamma (excluded) messages: {gamma_count}")
print(f"group chat (excluded) messages: {group_count}")
print(f"1:1 chat (excluded) messages:   {oneonone_count}")
print(f"TOTAL messages (all channels+chats): {total}")
print(f"Planted difficulty categories written: {len(EXPECTED_CATEGORIES)} (sheet 06's 15)")
print(f"Planted difficulty label rows written: {len(LABELS)}")
