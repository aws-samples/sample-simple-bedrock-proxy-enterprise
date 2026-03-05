"""
Simple Amazon Bedrock Proxy — boto3 Demo (No AWS Credentials)
=============================================================

Proves that **no real AWS credentials** are needed on the client side.
The proxy Lambda owns the IAM role that calls Bedrock; the client only
needs a Cognito token and the API Gateway URL.

We use botocore.UNSIGNED to skip SigV4 signing entirely — no credentials
are needed at all. The proxy re-signs every request with its own IAM role.

Usage:
    source scripts/setup-env.sh
    # Optionally unset any AWS creds to prove they aren't needed:
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE
    cd src/client && python demo_boto3_no_credentials.py
"""

import os
import uuid

import boto3
import requests
from botocore import UNSIGNED
from botocore.config import Config

# -- Configuration (from CDK stack outputs) --
API_GATEWAY_URL = os.environ["API_GATEWAY_URL"]
TOKEN_URL = os.environ["TOKEN_URL"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

MODEL_ID = os.environ.get("INFERENCE_PROFILE_ARN", "global.anthropic.claude-sonnet-4-6")
WORKLOAD_ID = "demo-boto3-no-creds"
PROMPT = "What is the capital of France? Answer in one sentence."


def get_cognito_token() -> str:
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials", "scope": "bedrock/invoke"},
        auth=(CLIENT_ID, CLIENT_SECRET),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def create_bedrock_client(token: str):
    client = boto3.client(
        "bedrock-runtime",
        endpoint_url=API_GATEWAY_URL,
        region_name="us-west-2",
        config=Config(signature_version=UNSIGNED),
    )

    def add_headers(params, **kwargs):
        params["headers"]["Authorization"] = f"Bearer {token}"
        params["headers"]["X-Client-Workload-Id"] = WORKLOAD_ID
        params["headers"]["X-Request-Tracker"] = str(uuid.uuid4())

    client.meta.events.register("before-call.bedrock-runtime.*", add_headers)
    return client


def test_converse(client):
    print("=" * 60)
    print("TEST 1: Converse (non-streaming)")
    print("=" * 60)
    response = client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": PROMPT}]}],
        inferenceConfig={"maxTokens": 100},
    )
    text = response["output"]["message"]["content"][0]["text"]
    tokens = response["usage"]
    print(f"Response: {text}")
    print(f"Tokens:   in={tokens['inputTokens']} out={tokens['outputTokens']}")
    print("PASS\n")


def test_converse_stream(client):
    print("=" * 60)
    print("TEST 2: ConverseStream (streaming)")
    print("=" * 60)
    response = client.converse_stream(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": PROMPT}]}],
        inferenceConfig={"maxTokens": 100},
    )
    print("Response: ", end="")
    for event in response["stream"]:
        if "contentBlockDelta" in event:
            print(event["contentBlockDelta"]["delta"]["text"], end="", flush=True)
        if "metadata" in event:
            tokens = event["metadata"]["usage"]
    print(f"\nTokens:   in={tokens['inputTokens']} out={tokens['outputTokens']}")
    print("PASS\n")


def main():
    print("Authenticating with Cognito...\n")
    token = get_cognito_token()

    print(f"Creating boto3 client → {API_GATEWAY_URL}")
    print(f"Model: {MODEL_ID}")
    print(f"Workload: {WORKLOAD_ID}")
    print("AWS credentials: UNSIGNED (no signing, no credentials needed)\n")
    client = create_bedrock_client(token)

    test_converse(client)
    test_converse_stream(client)

    print("=" * 60)
    print("ALL TESTS PASSED — no real AWS credentials required")
    print("=" * 60)


if __name__ == "__main__":
    main()
