"""
Generate seed/fixtures/{channels,members,messages}.json (CHN-06).

Deterministic (fixed random seed) -- re-running this always produces
byte-identical output. Run once and commit the resulting JSON files;
scripts/seed.py loads them, it does not regenerate them.
"""
import json
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

random.seed(42)

FIXTURES_DIR = Path("seed/fixtures")

CHANNELS = [
    {"id": "19:proj-alpha@thread.tacv2", "display_name": "Project Alpha"},
    {"id": "19:proj-beta@thread.tacv2", "display_name": "Project Beta"},
    {"id": "19:proj-gamma@thread.tacv2", "display_name": "Project Gamma"},
]

GROUP_CHAT_ID = "19:groupchat_9f2a1c@unq.gbl.spaces"
ONE_TO_ONE_CHAT_ID = "19:oneonone_7b3e44@unq.gbl.spaces"

ROSTERS = {
    "19:proj-alpha@thread.tacv2": [
        "priya.sharma", "james.okafor", "wei.chen",
        "fatima.hassan", "liam.oconnor", "sara.johansson",
    ],
    "19:proj-beta@thread.tacv2": [
        "james.okafor", "wei.chen", "diego.martinez",
        "amara.okonkwo", "kenji.tanaka", "elena.rossi",
    ],
    "19:proj-gamma@thread.tacv2": [
        "noah.becker", "aisha.rahman", "wei.chen",
        "olivia.dupont", "mateo.silva",
    ],
}

CHAT_ROSTERS = {
    GROUP_CHAT_ID: ["priya.sharma", "diego.martinez", "noah.becker"],
    ONE_TO_ONE_CHAT_ID: ["priya.sharma", "james.okafor"],
}

CHANNEL_TZ = {
    "19:proj-alpha@thread.tacv2": ZoneInfo("Asia/Colombo"),
    "19:proj-beta@thread.tacv2": ZoneInfo("America/New_York"),
    "19:proj-gamma@thread.tacv2": ZoneInfo("Asia/Colombo"),
}

def display_name(member_id: str) -> str:
    first, last = member_id.split(".")
    return f"{first.capitalize()} {last.capitalize()}"

WORKING_DAYS = [
    date(2025, 6, 2), date(2025, 6, 3), date(2025, 6, 4),
    date(2025, 6, 5), date(2025, 6, 6),
    # weekend: 2025-06-07 (Sat), 2025-06-08 (Sun) -- deliberately no messages
    date(2025, 6, 9), date(2025, 6, 10), date(2025, 6, 11),
    date(2025, 6, 12), date(2025, 6, 13),
]

SILENT_CHANNEL = "19:proj-beta@thread.tacv2"
SILENT_DAY = date(2025, 6, 11)

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

channels_out = list(CHANNELS)  # chats deliberately excluded -- see CHN-04
members_out = {}
messages_out = {}

for ch_id, roster in {**ROSTERS, **CHAT_ROSTERS}.items():
    members_out[ch_id] = [
        {"id": m, "display_name": display_name(m)} for m in roster
    ]

message_counter = 0

def new_id(prefix: str) -> str:
    global message_counter
    message_counter += 1
    return f"{prefix}-{message_counter:04d}"

def gen_messages_for_channel(channel_id, roster, days, msgs_per_day_range=(4, 10)):
    tz = CHANNEL_TZ.get(channel_id, ZoneInfo("UTC"))
    out = []
    for day in days:
        if channel_id == SILENT_CHANNEL and day == SILENT_DAY:
            continue  # deliberate channel-silent day
        n = random.randint(*msgs_per_day_range)
        for _ in range(n):
            author = random.choice(roster)
            hour = random.randint(8, 16)
            minute = random.randint(0, 59)
            posted = datetime.combine(day, time(hour, minute), tzinfo=tz)
            kind = random.choices(
                ["update", "question", "blocker", "chatter"],
                weights=[0.55, 0.15, 0.10, 0.20],
            )[0]
            msg_id = new_id(channel_id.split(":")[1].split("@")[0])
            msg = {
                "id": msg_id, "channel_id": channel_id, "author_id": author,
                "thread_root_id": None, "posted_at": posted.isoformat(),
                "edited_at": None, "deleted_at": None, "is_deleted": False,
                "is_bot": False, "is_system": False, "body": random_body(kind),
                "permalink": f"https://teams.microsoft.com/l/message/{channel_id}/{msg_id}",
            }
            out.append(msg)
            if random.random() < 0.25:
                replier = random.choice(roster)
                reply_posted = posted + timedelta(minutes=random.randint(5, 90))
                reply_id = new_id(channel_id.split(":")[1].split("@")[0])
                out.append({
                    "id": reply_id, "channel_id": channel_id, "author_id": replier,
                    "thread_root_id": msg_id, "posted_at": reply_posted.isoformat(),
                    "edited_at": None, "deleted_at": None, "is_deleted": False,
                    "is_bot": False, "is_system": False,
                    "body": random.choice(REPLY_TEMPLATES),
                    "permalink": f"https://teams.microsoft.com/l/message/{channel_id}/{reply_id}",
                })
    return out

messages_out["19:proj-alpha@thread.tacv2"] = gen_messages_for_channel(
    "19:proj-alpha@thread.tacv2", ROSTERS["19:proj-alpha@thread.tacv2"], WORKING_DAYS)
messages_out["19:proj-beta@thread.tacv2"] = gen_messages_for_channel(
    "19:proj-beta@thread.tacv2", ROSTERS["19:proj-beta@thread.tacv2"], WORKING_DAYS)
messages_out["19:proj-gamma@thread.tacv2"] = gen_messages_for_channel(
    "19:proj-gamma@thread.tacv2", ROSTERS["19:proj-gamma@thread.tacv2"], WORKING_DAYS, msgs_per_day_range=(1, 3))
messages_out[GROUP_CHAT_ID] = gen_messages_for_channel(
    GROUP_CHAT_ID, CHAT_ROSTERS[GROUP_CHAT_ID], WORKING_DAYS, msgs_per_day_range=(0, 2))
messages_out[ONE_TO_ONE_CHAT_ID] = gen_messages_for_channel(
    ONE_TO_ONE_CHAT_ID, CHAT_ROSTERS[ONE_TO_ONE_CHAT_ID], WORKING_DAYS, msgs_per_day_range=(0, 2))

FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
(FIXTURES_DIR / "channels.json").write_text(json.dumps(channels_out, indent=2))
(FIXTURES_DIR / "members.json").write_text(json.dumps(members_out, indent=2))
(FIXTURES_DIR / "messages.json").write_text(json.dumps(messages_out, indent=2))

alpha_count = len(messages_out["19:proj-alpha@thread.tacv2"])
beta_count = len(messages_out["19:proj-beta@thread.tacv2"])
print(f"proj-alpha messages: {alpha_count}")
print(f"proj-beta messages:  {beta_count}")
print(f"Allowlisted total:   {alpha_count + beta_count}")
print(f"proj-gamma (excluded) messages: {len(messages_out['19:proj-gamma@thread.tacv2'])}")
print(f"group chat (excluded) messages: {len(messages_out[GROUP_CHAT_ID])}")
print(f"1:1 chat (excluded) messages:   {len(messages_out[ONE_TO_ONE_CHAT_ID])}")
