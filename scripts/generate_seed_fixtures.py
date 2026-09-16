"""
Generate seed/fixtures/{channels,members,messages}.json (CHN-06) and
seed/fixtures/labels.csv (CHN-07).

Deterministic (fixed random seed) -- re-running this always produces
byte-identical output. Run once and commit the resulting files;
scripts/seed.py loads them, it does not regenerate them.

Two layers of content:
  1. Organic messages: randomly generated update/question/blocker/chatter
     traffic across 3 channels + 2 chats, 10 working days. A handful of
     roster members have a fixed behavioural override (on-leave, always
     chatter, emoji-only) that shapes the organic stream itself, because
     those cases have to hold for the *entire* window, not just one message.
  2. Planted difficulties (CHN-07): exactly 20 hand-authored cases, each
     with a fixed, human-readable message id so seed/fixtures/labels.csv
     can reference them by id forever, independent of the random stream.
     This script is the single source of truth for both the fixtures and
     their hand labels -- they cannot drift apart because the same loop
     that creates a planted message also appends its label row.
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
# non-responder arithmetic is computed over.
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
# NOT identical to the config roster above for two members:
#   - "sofia.almeida" is a Teams member of proj-beta (she posted there
#     before leaving the company) but was already dropped from the config
#     roster, which is current. Proves participation math must be computed
#     over the roster, never over "everyone who ever posted."
#   - "ci-bot" is a Teams member of proj-alpha (bots show up as channel
#     members in Graph) but was never on the roster -- bots are never
#     asked for an update.
TEAMS_MEMBERSHIP_EXTRA = {
    ALPHA: ["ci-bot"],
    BETA: ["sofia.almeida"],
    GAMMA: [],
}

CHAT_ROSTERS = {
    GROUP_CHAT_ID: ["priya.sharma", "diego.martinez", "noah.becker"],
    ONE_TO_ONE_CHAT_ID: ["priya.sharma", "james.okafor"],
}

CHANNEL_TZ = {
    ALPHA: ZoneInfo("Asia/Colombo"),
    BETA: ZoneInfo("America/New_York"),   # DIFF-TZ-01: mismatched vs. alpha/gamma
    GAMMA: ZoneInfo("Asia/Colombo"),
}

# Members with a fixed behavioural override for the whole window.
ON_LEAVE = {ALPHA: "liam.oconnor"}          # DIFF-LEAVE-01
CHATTER_ONLY = {ALPHA: "fatima.hassan"}     # DIFF-CHATTER-01
EMOJI_ONLY = {GAMMA: "aisha.rahman"}        # DIFF-EMOJI-01
EMOJI_BODIES = ["\U0001F44D", "\U0001F642", "\U0001F389"]  # thumbs up, smile, party -- all well under length_floor


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
SILENT_DAY = date(2025, 6, 11)   # DIFF-SILENT-01: whole-channel silent day (pre-existing)

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
    emoji_only = EMOJI_ONLY.get(channel_id)
    author_pool = [m for m in roster if m != on_leave]
    out = []
    for day in days:
        if channel_id == SILENT_CHANNEL and day == SILENT_DAY:
            continue  # deliberate channel-silent day (DIFF-SILENT-01)
        n = random.randint(*msgs_per_day_range)
        for _ in range(n):
            author = random.choice(author_pool)
            hour = random.randint(8, 16)
            minute = random.randint(0, 59)
            posted = datetime.combine(day, time(hour, minute), tzinfo=tz)
            if author == chatter_only:
                kind = "chatter"
            elif author == emoji_only:
                kind = "emoji"
            else:
                kind = random.choices(
                    ["update", "question", "blocker", "chatter"],
                    weights=[0.55, 0.15, 0.10, 0.20],
                )[0]
            msg_id = new_id(channel_id.split(":")[1].split("@")[0])
            body = random.choice(EMOJI_BODIES) if kind == "emoji" else random_body(kind)
            msg = base_message(msg_id, channel_id, author, posted, body)
            out.append(msg)
            if random.random() < 0.25:
                replier = random.choice(author_pool)
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
# CHN-07: 20 planted difficulties, fixed ids, appended after organic
# generation. LABELS accumulates the ground-truth row for each one.
# ---------------------------------------------------------------------------
LABELS = []


def plant(channel_id, msg_id, author_id, posted, body, **overrides):
    msg = base_message(msg_id, channel_id, author_id, posted, body, **overrides)
    messages_out.setdefault(channel_id, []).append(msg)
    return msg


def label(difficulty_id, category, channel_id, member_id, message_ids, date, description, expected_ground_truth):
    LABELS.append({
        "difficulty_id": difficulty_id,
        "category": category,
        "channel_id": channel_id,
        "member_id": member_id or "",
        "message_ids": ";".join(message_ids) if message_ids else "",
        "date": date,
        "description": description,
        "expected_ground_truth": expected_ground_truth,
    })


TZ_ALPHA = CHANNEL_TZ[ALPHA]
TZ_BETA = CHANNEL_TZ[BETA]
TZ_GAMMA = CHANNEL_TZ[GAMMA]

# DIFF-EDIT-01..04: edited messages. posted_at must never change; edited_at
# is set; body reflects the post-edit text.
edit_specs = [
    (ALPHA, "priya.sharma", datetime(2025, 6, 2, 9, 30, tzinfo=TZ_ALPHA), 12,
     "Finished the auth flow, running the tests now.",
     "Finished the auth flow, running the test suite now -- fixed a typo."),
    (ALPHA, "james.okafor", datetime(2025, 6, 4, 10, 5, tzinfo=TZ_ALPHA), 40,
     "Deployed the export job to staging.",
     "Deployed the export job to staging -- added the missing rollback step."),
    (BETA, "diego.martinez", datetime(2025, 6, 5, 9, 0, tzinfo=TZ_BETA), 8,
     "Blocked on the billing sync, waiting on IT.",
     "Blocked on the billing sync -- waiting on the API credentials from IT."),
    (BETA, "amara.okonkwo", datetime(2025, 6, 10, 8, 45, tzinfo=TZ_BETA), 20,
     "Merged the PR for the retry queue.",
     "Merged the PR for the retry queue, moving on to the caching layer."),
]
for i, (ch, author, posted, delay_min, orig_body, new_body) in enumerate(edit_specs, start=1):
    msg_id = f"diff-edit-{i:02d}"
    plant(ch, msg_id, author, posted, new_body,
          edited_at=(posted + timedelta(minutes=delay_min)).isoformat())
    label(f"DIFF-EDIT-{i:02d}", "edited_message", ch, author, [msg_id],
          posted.date().isoformat(),
          f"Message edited {delay_min} min after posting; original text was: {orig_body!r}",
          "posted_at must remain the original post time; edit must not be treated as a second update")

# DIFF-DEL-01..03: deleted messages. Real content is gone (Teams-style
# tombstone); the fact that *something* was posted must still be knowable
# from is_deleted/deleted_at, but the deleted body must never be used as
# evidence of an update.
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
    plant(ch, msg_id, author, posted, "",
          deleted_at=(posted + timedelta(minutes=25)).isoformat(), is_deleted=True)
    label(f"DIFF-DEL-{i:02d}", "deleted_message", ch, author, [msg_id],
          posted.date().isoformat(),
          f"Message deleted ~25 min after posting; original text was: {orig_body!r}",
          "must never count as an update for participation; deletion itself is not evidence of anything")

# DIFF-BOT-01..02: bot posts. ci-bot is a Teams member of proj-alpha but
# never on the config roster.
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

# DIFF-SYS-01: system-generated event message, no human author.
sys_posted = datetime(2025, 6, 9, 8, 0, tzinfo=TZ_BETA)
plant(BETA, "diff-sys-01", None, sys_posted, "Kenji Tanaka was added to the channel.", is_system=True)
label("DIFF-SYS-01", "system_post", BETA, None, ["diff-sys-01"], sys_posted.date().isoformat(),
      "Teams-generated membership-change notice; author_id is null",
      "must never be attributed to a person or counted as anyone's update")

# DIFF-DEPART-01: a Teams member with real posting history who was already
# removed from the config roster (she left the company). 3 messages across
# the first 3 working days, then nothing -- her absence for the rest of the
# window must never be flagged, because she isn't on the roster at all.
depart_days = WORKING_DAYS[:3]
depart_msg_ids = []
for i, day in enumerate(depart_days, start=1):
    posted = datetime.combine(day, time(8, 30), tzinfo=TZ_BETA)
    msg_id = f"diff-depart-{i:02d}"
    plant(BETA, msg_id, "sofia.almeida", posted,
          random.choice(UPDATE_TEMPLATES).format(feature=random.choice(FEATURES)))
    depart_msg_ids.append(msg_id)
label("DIFF-DEPART-01", "departed_member", BETA, "sofia.almeida", depart_msg_ids,
      depart_days[0].isoformat(),
      "sofia.almeida posted through 2025-06-04, then left; still returned by list_channel_members "
      "but already removed from channel_config.roster for proj-beta",
      "participation must be computed over the config roster only -- she must never appear as a "
      "non-responder for the days after she left, because she is not on the roster")

# DIFF-NAME-01: similar-name collision within one roster/channel.
name_posted = datetime(2025, 6, 10, 9, 30, tzinfo=TZ_GAMMA)
name_msg_id = "diff-name-01"
plant(GAMMA, name_msg_id, "olivia.dupree", name_posted,
      "Merged the PR for the reporting dashboard, moving on to the next item.")
label("DIFF-NAME-01", "similar_names", GAMMA, "olivia.dupree", [name_msg_id],
      name_posted.date().isoformat(),
      "proj-gamma roster has both olivia.dupont and olivia.dupree -- same first name, one letter apart",
      "must be tracked as two distinct people keyed by member_id, never merged or fuzzy-matched by display name")

# DIFF-BOUND-01: message posted exactly at update_window_end (proj-alpha:
# 11:00:00). Whether the window boundary is inclusive is a CHN-08 design
# decision not yet made -- this case exists to force that decision to be
# explicit rather than accidental.
bound_posted = datetime(2025, 6, 6, 11, 0, 0, tzinfo=TZ_ALPHA)
bound_msg_id = "diff-bound-01"
plant(ALPHA, bound_msg_id, "james.okafor", bound_posted,
      "Wrapped up code review on the onboarding wizard, no major issues found.")
label("DIFF-BOUND-01", "window_boundary", ALPHA, "james.okafor", [bound_msg_id],
      bound_posted.date().isoformat(),
      "Posted at exactly update_window_end (11:00:00 Asia/Colombo) for proj-alpha",
      "NOT YET DECIDED -- flag for CHN-08: whether the update window is inclusive or exclusive of its end instant")

# DIFF-DUP-01: accidental rapid double-post of near-identical text.
dup_posted = datetime(2025, 6, 5, 8, 20, tzinfo=TZ_BETA)
dup_ids = ["diff-dup-01a", "diff-dup-01b"]
plant(BETA, dup_ids[0], "james.okafor", dup_posted,
      "Deployed the notification service to staging, looks stable so far.")
plant(BETA, dup_ids[1], "james.okafor", dup_posted + timedelta(seconds=30),
      "Deployed the notification service to staging, looks stable so far.")
label("DIFF-DUP-01", "duplicate_post", BETA, "james.okafor", dup_ids,
      dup_posted.date().isoformat(),
      "Same author posts near-identical text twice, 30 seconds apart (accidental double-send)",
      "must count as one update for participation purposes, not two")

# DIFF-THREAD-01: a deep reply chain, 3 replies from 3 different members,
# in proj-alpha where count_thread_replies=true (contrast with proj-beta,
# where it's false).
thread_root_posted = datetime(2025, 6, 12, 9, 45, tzinfo=TZ_ALPHA)
thread_root_id = "diff-thread-01-root"
plant(ALPHA, thread_root_id, "priya.sharma", thread_root_posted,
      "Should the reporting dashboard handle the null case, or is that out of scope?")
thread_reply_ids = []
for i, (author, body, delay) in enumerate([
    ("james.okafor", "I'd say out of scope for v1, worth a follow-up ticket though.", 10),
    ("wei.chen", "Agreed -- I'll file the ticket.", 18),
    ("fatima.hassan", "Thanks!", 25),
], start=1):
    reply_id = f"diff-thread-01-reply-{i}"
    plant(ALPHA, reply_id, author, thread_root_posted + timedelta(minutes=delay), body,
          thread_root_id=thread_root_id)
    thread_reply_ids.append(reply_id)
label("DIFF-THREAD-01", "deep_thread", ALPHA, "priya.sharma", [thread_root_id] + thread_reply_ids,
      thread_root_posted.date().isoformat(),
      "Root question with 3 sequential replies from 3 different roster members",
      "count_thread_replies=true for proj-alpha: all 3 repliers get participation credit for this thread")

# Pre-existing / structural difficulties that need no extra planted
# messages of their own -- documented here so labels.csv is the complete,
# authoritative list of all 20.
label("DIFF-LEAVE-01", "on_leave_member", ALPHA, "liam.oconnor", [],
      "2025-06-02..2025-06-13",
      "liam.oconnor is on channel_config.exceptions for proj-alpha (annual leave) and organically "
      "generates zero messages for the entire seeded window",
      "must appear as excluded, never as a non-responder, and must never be nudged under any path (R2)")

label("DIFF-CHATTER-01", "chatter_only_member", ALPHA, "fatima.hassan", [],
      "2025-06-02..2025-06-13",
      "Every organically generated message from fatima.hassan is chatter-kind (e.g. 'Thanks!', 'Sounds good.'), never an update/question/blocker",
      "on days she posts: posted_no_update, not no_message and not credited as a real update")

first_emoji_ids = [m["id"] for m in messages_out[GAMMA] if m["author_id"] == "aisha.rahman" and m["body"] in EMOJI_BODIES]
label("DIFF-EMOJI-01", "emoji_only_member", GAMMA, "aisha.rahman", first_emoji_ids,
      "2025-06-02..2025-06-13",
      "Every organically generated message from aisha.rahman is a single emoji, below proj-gamma's length_floor "
      "(reactions themselves are invisible to this system -- Graph reactions are a separate, unread API -- so an "
      "emoji-only chat message is the closest representable analogue)",
      "posted_no_update on days she posts (fails length_floor); must not be conflated with no_message")

label("DIFF-TZ-01", "mismatched_timezone", BETA, None, [],
      "n/a",
      "proj-beta's update window (08:00-10:00) is America/New_York while proj-alpha and proj-gamma are Asia/Colombo",
      "window membership must be computed in each channel's own configured timezone, never a global one")

label("DIFF-XCHAN-01", "cross_channel_identity", None, "wei.chen", [],
      "n/a",
      "wei.chen is on the roster of all three channels (proj-alpha, proj-beta, proj-gamma) with independent posting history in each",
      "participation must be keyed by (channel_id, member_id), never by member_id alone")

assert len(LABELS) == 20, f"expected exactly 20 planted difficulties, got {len(LABELS)}"

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
print(f"Planted difficulties written: {len(LABELS)}")
