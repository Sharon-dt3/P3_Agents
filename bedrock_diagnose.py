"""
Read-only diagnostics for the Bedrock 403. Changes nothing -- every
call here is a read (GetCallerIdentity, GetFoundationModel,
GetInferenceProfile). Helps pin down exactly what's missing: whether
this is purely an IAM policy gap, or also a Bedrock "Model access" gate
that hasn't been granted for this account in this region.

Usage:
    uv run python bedrock_diagnose.py
"""

import os

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

REGION = os.environ.get("AWS_REGION", "us-east-2")
MODEL_ID = "anthropic.claude-sonnet-4-20250514-v1:0"
INFERENCE_PROFILE_ARN = os.environ.get("BEDROCK_MODEL_ID")


def main() -> int:
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        print("AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY must be set in .env")
        return 1

    sts = boto3.client("sts", aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=REGION)
    try:
        identity = sts.get_caller_identity()
        print(f"Signed in as: {identity['Arn']}")
    except ClientError as exc:
        print(f"sts:GetCallerIdentity failed: {exc}")

    for region in ("us-east-1", "us-east-2"):
        bedrock = boto3.client(
            "bedrock", aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region
        )
        print(f"\n--- region {region} ---")
        try:
            model = bedrock.get_foundation_model(modelIdentifier=MODEL_ID)
            print(f"get_foundation_model: OK -- {model['modelDetails']['modelId']}")
        except ClientError as exc:
            print(f"get_foundation_model failed: {exc.response['Error']['Code']} -- {exc.response['Error']['Message']}")

        if INFERENCE_PROFILE_ARN:
            try:
                profile = bedrock.get_inference_profile(inferenceProfileIdentifier=INFERENCE_PROFILE_ARN)
                print(f"get_inference_profile: OK -- status={profile.get('status')}")
            except ClientError as exc:
                print(f"get_inference_profile failed: {exc.response['Error']['Code']} -- {exc.response['Error']['Message']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
