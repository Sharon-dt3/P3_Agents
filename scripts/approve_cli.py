"""Command-line approve/reject/list for pending P1 proposals.

This calls the exact same p1.approval.service functions the Streamlit
dashboard (app/approval_dashboard.py) and the Copilot Studio connector
call -- list_pending_approvals(), approve_and_send(), reject() -- so a
decision made here produces the identical audit row, write_log entry,
and (for daily_digest_publish) mark_published() call as clicking the
button in either surface. There is no separate code path here: this is
a thin argparse wrapper around service.py, nothing more.

Usage:
    uv run python scripts/approve_cli.py list
    uv run python scripts/approve_cli.py approve <proposal_id>
    uv run python scripts/approve_cli.py reject  <proposal_id>

DB path and approver identity follow the same environment variables as
the dashboard: P1_DB_PATH (default data/p1.db) and P1_APPROVER_ID
(default "priya"). Override either per-invocation with --db-path /
--approver-id if you need to.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure `src/` is importable regardless of how this script is invoked --
# same workaround every other scripts/*.py entry point already uses (see
# DECISION_LOG.md): the editable p1 install isn't reliably picked up by a
# plain `uv run python scripts/x.py` on this machine, so every script adds
# src/ to sys.path itself rather than depending on it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.approval import service as approval_service
from p1.approval.proposals import ProposalNotFoundError
from p1.storage.db import DEFAULT_DB_PATH

DB_PATH_DEFAULT = os.environ.get("P1_DB_PATH", str(DEFAULT_DB_PATH))
APPROVER_DEFAULT = os.environ.get("P1_APPROVER_ID", "priya")


def cmd_list(args: argparse.Namespace) -> int:
    pending = approval_service.list_pending_approvals(db_path=args.db_path)
    if not pending:
        print(f"Nothing awaiting approval. (db: {args.db_path})")
        return 0
    for p in pending:
        print(f"{p.proposal_id}  [{p.type}]  {p.channel_id}  created {p.created_at}")
        print(f"    {p.summary}")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    try:
        result = approval_service.approve_and_send(
            args.proposal_id, approver_id=args.approver_id, db_path=args.db_path,
        )
    except ProposalNotFoundError as exc:
        print(f"{args.proposal_id}: not_found -- {exc}")
        return 1
    print(f"{result.proposal_id}: {result.outcome} -- {result.detail}")
    return 0 if result.outcome == "sent" else 1


def cmd_reject(args: argparse.Namespace) -> int:
    try:
        result = approval_service.reject(
            args.proposal_id, approver_id=args.approver_id, db_path=args.db_path,
        )
    except ProposalNotFoundError as exc:
        print(f"{args.proposal_id}: not_found -- {exc}")
        return 1
    print(f"{result.proposal_id}: {result.outcome} -- {result.detail}")
    return 0 if result.outcome == "rejected" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", default=DB_PATH_DEFAULT, help=f"default: {DB_PATH_DEFAULT}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List every proposal currently awaiting a human decision").set_defaults(func=cmd_list)

    p_approve = sub.add_parser("approve", help="Approve a proposal and attempt to send it immediately")
    p_approve.add_argument("proposal_id")
    p_approve.add_argument("--approver-id", default=APPROVER_DEFAULT, help=f"default: {APPROVER_DEFAULT!r}")
    p_approve.set_defaults(func=cmd_approve)

    p_reject = sub.add_parser("reject", help="Reject a proposal")
    p_reject.add_argument("proposal_id")
    p_reject.add_argument("--approver-id", default=APPROVER_DEFAULT, help=f"default: {APPROVER_DEFAULT!r}")
    p_reject.set_defaults(func=cmd_reject)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
