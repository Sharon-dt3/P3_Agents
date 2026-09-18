"""
CHN-25: the Streamlit fallback -- pending approvals and per-channel
config, over the exact same p1.approval.service /
p1.config.loader.ChannelConfigStore calls the Copilot Studio connector
uses (see docs/copilot_studio/connector_contract.md). This file is
deliberately thin: every button and form here calls straight into that
shared service, with no business logic of its own, so
tests/unit/test_approval_dashboard_app.py driving these exact widgets
headlessly (via streamlit.testing.v1.AppTest) is proof this surface
behaves identically to the connector, not a separate, hand-verified
claim about it -- "the gate lives in the service, not the UI" applies
to this file too: there is nothing it does that the connector's own
handlers do not also do, calling the same functions.

DB_PATH is read from the P1_DB_PATH environment variable if set (a
test-only seam -- AppTest.from_file() cannot pass constructor arguments
to a script, so an env var is how a test points this app at an
isolated temp database instead of production's default), falling back
to DEFAULT_DB_PATH otherwise, exactly like every job/service function
elsewhere in this codebase takes db_path as a keyword argument.
CURRENT_USER_ID stands in for a real signed-in identity, the same gap
this row's own contract doc notes for the Copilot Studio side -- there
is no live Teams/Entra sign-in for either surface to bind to here.
"""

from __future__ import annotations

import os

import streamlit as st

from p1.approval import service as approval_service
from p1.config.loader import ChannelConfigStore
from p1.storage.db import DEFAULT_DB_PATH, get_connection

DB_PATH = os.environ.get("P1_DB_PATH", DEFAULT_DB_PATH)
CURRENT_USER_ID = os.environ.get("P1_APPROVER_ID", "priya")

st.title("P1 Channel -- approvals & config (fallback surface)")

st.header("Pending approvals")
pending = approval_service.list_pending_approvals(db_path=DB_PATH)
if not pending:
    st.info("Nothing awaiting approval.")
for approval in pending:
    with st.container():
        st.write(f"**{approval.type}** -- {approval.summary}")
        st.caption(
            f"proposal_id={approval.proposal_id} channel={approval.channel_id} created={approval.created_at}"
        )
        col1, col2 = st.columns(2)
        if col1.button("Approve", key=f"approve_{approval.proposal_id}"):
            result = approval_service.approve_and_send(
                approval.proposal_id, approver_id=CURRENT_USER_ID, db_path=DB_PATH,
            )
            st.success(f"{result.outcome}: {result.detail}")
        if col2.button("Reject", key=f"reject_{approval.proposal_id}"):
            result = approval_service.reject(
                approval.proposal_id, approver_id=CURRENT_USER_ID, db_path=DB_PATH,
            )
            st.warning(f"{result.outcome}: {result.detail}")

st.divider()
st.header("Per-channel configuration")

conn = get_connection(DB_PATH)
try:
    channel_ids = [row["id"] for row in conn.execute("SELECT id FROM channels ORDER BY id").fetchall()]
finally:
    conn.close()

if not channel_ids:
    st.info("No channels configured yet.")
else:
    selected_channel = st.selectbox("Channel", channel_ids)
    config_store = ChannelConfigStore()
    try:
        current = config_store.get_effective_config(selected_channel, db_path=DB_PATH)
    except KeyError:
        current = None

    if current is None:
        st.warning("This channel has no synced config yet (sync_to_db() has not run for it).")
    else:
        roster_text = st.text_area("Roster (one member ID per line)", value="\n".join(current.roster))
        window_start = st.time_input("Update window start", value=current.update_window_start)
        window_end = st.time_input("Update window end", value=current.update_window_end)
        exceptions_text = st.text_area(
            "Exceptions (member_id:reason, one per line)",
            value="\n".join(f"{e.member_id}:{e.reason}" for e in current.exceptions),
        )
        if st.button("Save configuration"):
            roster = [line.strip() for line in roster_text.splitlines() if line.strip()]
            exceptions = []
            for line in exceptions_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                member_id, _, reason = line.partition(":")
                exceptions.append({"member_id": member_id.strip(), "reason": reason.strip()})
            try:
                new_config = config_store.update_channel_config(
                    selected_channel,
                    roster=roster,
                    update_window_start=window_start,
                    update_window_end=window_end,
                    exceptions=exceptions,
                    updated_by=CURRENT_USER_ID,
                    db_path=DB_PATH,
                )
                st.success(f"Saved -- version {new_config.version}")
            except Exception as exc:  # noqa: BLE001 -- shown to the channel owner, never a raw traceback
                st.error(f"Could not save: {exc}")
