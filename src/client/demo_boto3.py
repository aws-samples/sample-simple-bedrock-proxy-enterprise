"""
Simple Amazon Bedrock Proxy — boto3 Four Methods Demo
=====================================================

Demonstrates all four Bedrock invocation methods through the proxy:
1. Converse (non-streaming)
2. ConverseStream (streaming)
3. InvokeModel (non-streaming)
4. InvokeModelWithResponseStream (streaming)

Usage:
    source scripts/setup-env.sh
    cd src/client && python demo_boto3.py
"""

import json
import os
import uuid

import boto3
import requests

# -- Configuration (from CDK stack outputs) --
API_GATEWAY_URL = os.environ["API_GATEWAY_URL"]
TOKEN_URL = os.environ["TOKEN_URL"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

MODEL_ID = "global.anthropic.claude-sonnet-4-6"
WORKLOAD_ID = "demo-boto3-workload"
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
    )

    def add_headers(params, **kwargs):
        params["headers"]["x-auth-token"] = token
        params["headers"]["X-Client-Workload-Id"] = WORKLOAD_ID
        params["headers"]["X-Request-Tracker"] = str(uuid.uuid4())

    client.meta.events.register("before-call.bedrock-runtime.*", add_headers)
    return client


# -- Test 1: Converse --
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


# -- Test 2: ConverseStream --
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


# -- Test 3: InvokeModel --
def test_invoke_model(client):
    print("=" * 60)
    print("TEST 3: InvokeModel (non-streaming)")
    print("=" * 60)
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": PROMPT}],
    })
    response = client.invoke_model(
        modelId=MODEL_ID,
        body=body,
        contentType="application/json",
    )
    result = json.loads(response["body"].read())
    text = result["content"][0]["text"]
    usage = result["usage"]
    print(f"Response: {text}")
    print(f"Tokens:   in={usage['input_tokens']} out={usage['output_tokens']}")
    print("PASS\n")


# -- Test 4: InvokeModelWithResponseStream --
def test_invoke_model_stream(client):
    print("=" * 60)
    print("TEST 4: InvokeModelWithResponseStream (streaming)")
    print("=" * 60)
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": PROMPT}],
    })
    response = client.invoke_model_with_response_stream(
        modelId=MODEL_ID,
        body=body,
        contentType="application/json",
    )
    print("Response: ", end="")
    for event in response["body"]:
        chunk = json.loads(event["chunk"]["bytes"])
        if chunk["type"] == "content_block_delta":
            print(chunk["delta"]["text"], end="", flush=True)
        if chunk["type"] == "message_delta":
            usage = chunk.get("usage", {})
    print(f"\nTokens:   out={usage.get('output_tokens', '?')}")
    print("PASS\n")


def main():
    print("Authenticating with Cognito...\n")
    token = get_cognito_token()

    print(f"Creating boto3 client → {API_GATEWAY_URL}")
    print(f"Model: {MODEL_ID}")
    print(f"Workload: {WORKLOAD_ID}\n")
    client = create_bedrock_client(token)

    test_converse(client)
    test_converse_stream(client)
    test_invoke_model(client)
    test_invoke_model_stream(client)

    print("=" * 60)
    print("ALL 4 TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
