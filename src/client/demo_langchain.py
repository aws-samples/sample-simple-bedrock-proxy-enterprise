"""
Simple Amazon Bedrock Proxy — LangChain Demo
=======================

Demonstrates that LangChain works seamlessly through a Bedrock proxy by:
1. Authenticating with Cognito (client_credentials grant)
2. Configuring a boto3 client with endpoint_url → API Gateway
3. Injecting Authorization header and tracking headers via boto3 events (before-call)
4. Passing the configured client to LangChain's ChatBedrockConverse

Usage:
    export API_GATEWAY_URL=https://xxx.execute-api.region.amazonaws.com/prod
    export TOKEN_URL=https://xxx.auth.region.amazoncognito.com/oauth2/token
    export CLIENT_ID=xxx
    export CLIENT_SECRET=xxx

    python demo.py
"""

import os
import uuid

import boto3
import requests
from langchain_aws import ChatBedrockConverse

# -- Configuration (from CDK stack outputs) --
API_GATEWAY_URL = os.environ["API_GATEWAY_URL"]
TOKEN_URL = os.environ["TOKEN_URL"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

MODEL_ID = "global.anthropic.claude-sonnet-4-6"
WORKLOAD_ID = "demo-langchain-workload"


def get_cognito_token() -> str:
    """Authenticate with Cognito using client_credentials grant."""
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials", "scope": "bedrock/invoke"},
        auth=(CLIENT_ID, CLIENT_SECRET),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def create_bedrock_client(token: str) -> boto3.client:
    """Create a boto3 bedrock-runtime client with custom endpoint and headers."""
    client = boto3.client(
        "bedrock-runtime",
        endpoint_url=API_GATEWAY_URL,
        region_name="us-east-1",
    )

    def add_tracking_headers(params, **kwargs):
        params["headers"]["Authorization"] = f"Bearer {token}"
        params["headers"]["X-Client-Workload-Id"] = WORKLOAD_ID
        params["headers"]["X-Request-Tracker"] = str(uuid.uuid4())

    client.meta.events.register(
        "before-call.bedrock-runtime.*", add_tracking_headers
    )
    return client


def main():
    print("1. Authenticating with Cognito...")
    token = get_cognito_token()
    print("   Got access token.\n")

    print("2. Creating boto3 client with custom endpoint + headers...")
    client = create_bedrock_client(token)
    print(f"   endpoint_url = {API_GATEWAY_URL}")
    print(f"   workload_id  = {WORKLOAD_ID}\n")

    print("3. Initializing LangChain ChatBedrockConverse...")
    chat = ChatBedrockConverse(
        model=MODEL_ID,
        client=client,
    )
    print(f"   model = {MODEL_ID}\n")

    print("4. Streaming response through proxy:\n")
    print("-" * 50)
    for chunk in chat.stream("What is the capital of France? Answer briefly. Then provide a poem about it"):
        # ChatBedrockConverse yields content as list of blocks or str
        if isinstance(chunk.content, str):
            print(chunk.content, end="", flush=True)
        elif isinstance(chunk.content, list):
            for block in chunk.content:
                if isinstance(block, dict) and "text" in block:
                    print(block["text"], end="", flush=True)
    print("\n" + "-" * 50)

    print("\nDone. Check Lambda CloudWatch logs for tracking entries.")


if __name__ == "__main__":
    main()
