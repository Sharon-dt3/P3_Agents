"""
One-off, safe-to-try check: attempts to attach an inline IAM policy
granting bedrock:InvokeModel to the IAM user these credentials belong
to. If the credentials don't have permission to manage their own IAM
policies (the normal case for a scoped-down demo user), this fails
cleanly with an AccessDenied error and changes nothing. Never deletes
or overwrites anything -- put_user_policy only adds/replaces the one
named inline policy below, on this one user.

Usage:
    uv run python try_self_grant_bedrock.py
"""

import json
import os

import boto3
from dotenv import load_dotenv

load_dotenv()

IAM_USER = "p1-agent-bedrock-demo"
POLICY_NAME = "p1-bedrock-invoke-self-grant-attempt"
POLICY_DOCUMENT = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            "Resource": [
                "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0",
                "arn:aws:bedrock:*:619042036275:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0",
            ],
        }
    ],
}


def main() -> int:
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    region = os.environ.get("AWS_REGION", "us-east-1")

    if not access_key or not secret_key:
        print("AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY must be set in .env")
        return 1

    iam = boto3.client(
        "iam",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )

    try:
        iam.put_user_policy(
            UserName=IAM_USER,
            PolicyName=POLICY_NAME,
            PolicyDocument=json.dumps(POLICY_DOCUMENT),
        )
    except Exception as exc:  # noqa: BLE001 -- this is a one-off diagnostic, not production code
        print(f"Could not self-grant: {exc}")
        print("\nThis is expected if the demo credentials don't include IAM permissions on themselves.")
        print("You'll need your lead to attach the policy from their end instead.")
        return 1

    print(f"Success: attached inline policy '{POLICY_NAME}' to {IAM_USER}.")
    print("Re-run the pipeline now -- it should reach Bedrock successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
