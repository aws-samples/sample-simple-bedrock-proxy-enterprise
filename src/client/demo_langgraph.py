"""
Simple Amazon Bedrock Proxy — LangGraph Demo
=============================================

Demonstrates a LangGraph ReAct agent working through the Bedrock proxy.
LangGraph uses ChatBedrockConverse which accepts a custom boto3 client directly.

Usage:
    source scripts/setup-env.sh
    cd src/client && pip install langchain langchain-aws langgraph && python demo_langgraph.py
"""

import os
import uuid

import boto3
import requests
from langchain.agents import create_agent
from langchain_aws import ChatBedrockConverse
from langchain_core.tools import tool

API_GATEWAY_URL = os.environ["API_GATEWAY_URL"]
TOKEN_URL = os.environ["TOKEN_URL"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

MODEL_ID = "global.anthropic.claude-sonnet-4-6"
WORKLOAD_ID = "demo-langgraph-workload"


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
        params["headers"]["Authorization"] = f"Bearer {token}"
        params["headers"]["X-Client-Workload-Id"] = WORKLOAD_ID
        params["headers"]["X-Request-Tracker"] = str(uuid.uuid4())

    client.meta.events.register("before-call.bedrock-runtime.*", add_headers)
    return client


# -- Define a simple tool for the agent --
@tool
def get_population(country: str) -> str:
    """Get the approximate population of a country."""
    populations = {
        "france": "68 million",
        "germany": "84 million",
        "japan": "125 million",
        "brazil": "215 million",
    }
    return populations.get(country.lower(), f"Unknown population for {country}")


def main():
    print("LangGraph ReAct Agent via Bedrock Proxy")
    print("=" * 50)

    token = get_cognito_token()
    client = create_bedrock_client(token)

    # Create LLM with custom boto3 client → goes through proxy
    llm = ChatBedrockConverse(model=MODEL_ID, client=client)

    # Create a ReAct agent with tools
    agent = create_agent(llm, tools=[get_population])

    # Run the agent
    print("\nQuery: What is the population of France and its capital?\n")
    result = agent.invoke(
        {"messages": [("user", "What is the population of France and its capital?")]}
    )

    # Print the final response
    final = result["messages"][-1]
    print(f"Agent response:\n{final.content}\n")
    print("PASS — LangGraph agent worked through the proxy")


if __name__ == "__main__":
    main()
