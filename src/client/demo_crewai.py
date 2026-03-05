"""
Simple Amazon Bedrock Proxy — CrewAI Demo
==========================================

Demonstrates a CrewAI crew working through the Bedrock proxy.
CrewAI does not accept a custom boto3 client — it creates its own
internally. We use a monkey-patch on boto3.Session.client so that
ANY bedrock-runtime client created by any framework gets the proxy
endpoint and custom headers injected automatically.

This is the universal fallback for frameworks with no client= parameter.

Usage:
    source scripts/setup-env.sh
    cd src/client && pip install crewai && python demo_crewai.py
"""

import os
import uuid

os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"

import boto3
import requests
from botocore import UNSIGNED
from botocore.config import Config
from crewai import LLM, Agent, Crew, Task

API_GATEWAY_URL = os.environ["API_GATEWAY_URL"]
TOKEN_URL = os.environ["TOKEN_URL"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

MODEL_ID = "global.anthropic.claude-sonnet-4-6"
WORKLOAD_ID = "demo-crewai-workload"


def get_cognito_token() -> str:
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials", "scope": "bedrock/invoke"},
        auth=(CLIENT_ID, CLIENT_SECRET),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def setup_proxy(token: str):
    """Patch boto3 so ANY bedrock-runtime client gets proxy config.

    CrewAI creates its own boto3.Session() internally, so setting
    DEFAULT_SESSION or env vars alone is not enough — the custom headers
    wouldn't be registered on CrewAI's session.

    This patches Session.client to intercept bedrock-runtime client creation
    and inject endpoint_url + event handlers on every client.
    """
    _original_client = boto3.Session.client

    def _patched_client(self, service_name, *args, **kwargs):
        if service_name == "bedrock-runtime":
            if "endpoint_url" not in kwargs:
                kwargs["endpoint_url"] = API_GATEWAY_URL
            # Merge UNSIGNED config to skip SigV4 (proxy owns the real creds)
            unsigned_config = Config(signature_version=UNSIGNED)
            if "config" in kwargs and kwargs["config"]:
                kwargs["config"] = kwargs["config"].merge(unsigned_config)
            else:
                kwargs["config"] = unsigned_config

        client = _original_client(self, service_name, *args, **kwargs)

        if service_name == "bedrock-runtime":

            def add_headers(params, **_kwargs):
                params["headers"]["Authorization"] = f"Bearer {token}"
                params["headers"]["X-Client-Workload-Id"] = WORKLOAD_ID
                params["headers"]["X-Request-Tracker"] = str(uuid.uuid4())

            client.meta.events.register(
                "before-call.bedrock-runtime.*", add_headers
            )

        return client

    boto3.Session.client = _patched_client


def teardown_proxy():
    """Restore original boto3.Session.client."""
    # Not strictly needed for a script, but good practice
    if hasattr(boto3.Session.client, "__wrapped__"):
        boto3.Session.client = boto3.Session.client.__wrapped__


def main():
    print("CrewAI Crew via Bedrock Proxy")
    print("=" * 50)

    token = get_cognito_token()
    setup_proxy(token)

    # Create CrewAI LLM using Bedrock provider
    llm = LLM(
        model=f"bedrock/{MODEL_ID}",
        region_name="us-west-2",
    )

    # Define an agent
    researcher = Agent(
        role="Geography Expert",
        goal="Answer geography questions accurately and concisely",
        backstory="You are a geography expert who gives brief, factual answers.",
        llm=llm,
        verbose=False,
    )

    # Define a task
    task = Task(
        description="What is the capital of France? Answer in one sentence.",
        expected_output="A single sentence stating the capital of France.",
        agent=researcher,
    )

    # Run the crew
    print("\nQuery: What is the capital of France?\n")
    crew = Crew(agents=[researcher], tasks=[task], verbose=False)
    result = crew.kickoff()

    print(f"Crew result: {result.raw}")
    print("\nPASS — CrewAI crew worked through the proxy")


if __name__ == "__main__":
    main()
