"""
Simple Amazon Bedrock Proxy — Strands Agents Demo
==================================================

Demonstrates a Strands agent working through the Bedrock proxy.
Strands accepts a boto_session parameter — events registered on the session
propagate to all clients created from it.

The endpoint_url is set via AWS_ENDPOINT_URL_BEDROCK_RUNTIME env var,
which boto3 picks up automatically when creating the client.

Usage:
    source scripts/setup-env.sh
    cd src/client && pip install strands-agents && python demo_strands.py
"""

import os
import uuid

import boto3
import requests
from strands import Agent
from strands.models.bedrock import BedrockModel

API_GATEWAY_URL = os.environ["API_GATEWAY_URL"]
TOKEN_URL = os.environ["TOKEN_URL"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

MODEL_ID = "global.anthropic.claude-sonnet-4-6"
WORKLOAD_ID = "demo-strands-workload"


def get_cognito_token() -> str:
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials", "scope": "bedrock/invoke"},
        auth=(CLIENT_ID, CLIENT_SECRET),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def main():
    print("Strands Agent via Bedrock Proxy")
    print("=" * 50)

    token = get_cognito_token()

    # Redirect boto3 to the proxy via env var (Strands creates its own client)
    os.environ["AWS_ENDPOINT_URL_BEDROCK_RUNTIME"] = API_GATEWAY_URL

    # Create a session with event handlers for custom headers
    session = boto3.Session(region_name="us-west-2")

    def add_headers(params, **kwargs):
        params["headers"]["x-auth-token"] = token
        params["headers"]["X-Client-Workload-Id"] = WORKLOAD_ID
        params["headers"]["X-Request-Tracker"] = str(uuid.uuid4())

    session.events.register("before-call.bedrock-runtime.*", add_headers)

    # Create Strands model with the custom session
    model = BedrockModel(
        model_id=MODEL_ID,
        boto_session=session,
    )

    # Create and run the agent
    agent = Agent(model=model)

    print("\nQuery: What is the capital of France? Answer briefly.\n")
    result = agent("What is the capital of France? Answer briefly.")
    print(f"\nAgent response: {result}")
    print("\nPASS — Strands agent worked through the proxy")

    # Clean up env var
    del os.environ["AWS_ENDPOINT_URL_BEDROCK_RUNTIME"]


if __name__ == "__main__":
    main()
