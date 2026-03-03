# Simple Amazon Bedrock Proxy for Enterprise Integration

> **Disclaimer:** AWS code samples are example code that demonstrates practical implementations of AWS services for specific use cases and scenarios. These application solutions are not supported products in their own right, but educational examples to help our customers use our products for their applications. As our customer, any applications you integrate these examples into should be thoroughly tested, secured, and optimized according to your business's security standards & policies before deploying to production or handling production workloads.

Demonstrates that developers can use popular AI frameworks seamlessly through a Bedrock proxy by leveraging [boto3's event system](https://docs.aws.amazon.com/boto3/latest/guide/events.html) to inject custom headers into a pre-configured client. This pattern enables enterprise platforms to centrally govern, authenticate, and track AI model usage while letting developers use their preferred tools without modification.

![Architecture](docs/generated-diagrams/architecture.png)

## Supported Frameworks

The proxy works transparently with any framework that uses boto3 to call Bedrock. Each demo shows a different integration method:

| Demo | Framework | Integration Method |
|---|---|---|
| `demo_boto3.py` | **boto3** (direct) | All 4 Bedrock APIs: Converse, ConverseStream, InvokeModel, InvokeModelWithResponseStream |
| `demo_langchain.py` | **LangChain** | `ChatBedrockConverse(client=...)` — pass pre-configured boto3 client |
| `demo_langgraph.py` | **LangGraph** | ReAct agent with tools via `ChatBedrockConverse(client=...)` |
| `demo_strands.py` | **Strands Agents** | `BedrockModel(boto_session=...)` — pass session with event handlers + `AWS_ENDPOINT_URL_BEDROCK_RUNTIME` env var |
| `demo_crewai.py` | **CrewAI** | `boto3.Session.client` monkey-patch — universal fallback for frameworks with no client parameter |

## How It Works

1. **Client authenticates** with Cognito (client_credentials grant) and gets an access token
2. **Client configures boto3** to route through the proxy (via `endpoint_url` or env var)
3. **Client injects custom headers** via boto3's `before-call` event:
   - `x-auth-token` — Cognito JWT for authorization
   - `X-Client-Workload-Id` — identifies the calling application
   - `X-Request-Tracker` — unique request correlation ID
4. **AI framework calls Bedrock as usual** — the proxy is invisible to the framework
5. **API Gateway** validates the JWT via a Custom Lambda Authorizer
6. **Proxy Lambda** (FastAPI + Lambda Web Adapter) extracts tracking headers + model ID, logs them, then forwards raw bytes to Bedrock using SigV4-signed requests
7. **Response streaming** — Bedrock's binary event stream flows back through API Gateway (REST, `responseTransferMode: STREAM`) to the client's boto3, which parses it natively

### Application Inference Profile

The stack creates an [Application Inference Profile](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-create.html) that copies from the `us.anthropic.claude-sonnet-4-6` system profile. This demonstrates that the proxy works with inference profile ARNs — not just foundation model IDs.

After `source scripts/setup-env.sh`, the `INFERENCE_PROFILE_ARN` env var is exported. The `demo_boto3.py` demo uses it automatically. To switch back to the default cross-region profile:

```bash
unset INFERENCE_PROFILE_ARN
python demo_boto3.py
```

### What Gets Tracked

The proxy Lambda logs a structured JSON entry for every request:

```json
{
  "workload_id": "demo-langchain-workload",
  "request_tracker": "a1b2c3d4-...",
  "model_id": "global.anthropic.claude-sonnet-4-6",
  "operation": "converse-stream",
  "auth_token_present": true,
  "timestamp": "2026-03-02T14:30:00Z"
}
```

## Prerequisites

- AWS CLI configured with appropriate credentials
- AWS CDK CLI (`npm install -g aws-cdk`)
- Python 3.12+
- Docker (for Lambda bundling)

## Deploy

```bash
cd infra
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk deploy
```

## Run the Demos

```bash
# Set environment variables from stack outputs
source scripts/setup-env.sh

# Install client dependencies
cd src/client
pip install -r requirements.txt

# Run any demo
python demo_boto3.py       # Raw boto3 — all 4 Bedrock APIs
python demo_langchain.py   # LangChain ChatBedrockConverse
python demo_langgraph.py   # LangGraph ReAct agent with tools
python demo_strands.py     # Strands Agents
python demo_crewai.py      # CrewAI crew
```

## Project Structure

```
├── infra/                           # CDK infrastructure (Python)
│   ├── app.py                       # CDK app entry point
│   └── stacks/proxy_stack.py        # Cognito + API GW + Lambdas
├── src/
│   ├── proxy/                       # Proxy Lambda (FastAPI + LWA)
│   │   ├── main.py                  # FastAPI routes, tracking logs
│   │   ├── bedrock_proxy.py         # Raw byte proxy with SigV4
│   │   └── run.sh                   # Lambda Web Adapter startup
│   ├── authorizer/                  # Custom Authorizer Lambda
│   │   └── handler.py               # Cognito JWT validation
│   └── client/                      # Demo clients (run locally)
│       ├── demo_boto3.py            # boto3 — all 4 Bedrock APIs
│       ├── demo_langchain.py        # LangChain streaming
│       ├── demo_langgraph.py        # LangGraph ReAct agent
│       ├── demo_strands.py          # Strands Agents
│       └── demo_crewai.py           # CrewAI crew
├── scripts/
│   └── setup-env.sh                 # Fetch stack outputs → env vars
└── docs/
    └── generated-diagrams/          # Architecture diagram
```

## Key Client Code

```python
import boto3
from langchain_aws import ChatBedrockConverse

# Point boto3 at the proxy instead of real Bedrock
client = boto3.client("bedrock-runtime", endpoint_url=API_GATEWAY_URL)

# Inject custom headers via boto3 event system
def add_headers(params, **kwargs):
    params["headers"]["x-auth-token"] = cognito_token
    params["headers"]["X-Client-Workload-Id"] = "my-app"
    params["headers"]["X-Request-Tracker"] = str(uuid.uuid4())

client.meta.events.register("before-call.bedrock-runtime.*", add_headers)

# Any framework works transparently
chat = ChatBedrockConverse(model="global.anthropic.claude-sonnet-4-6", client=client)
for chunk in chat.stream("Hello!"):
    print(chunk.content)
```

## Production Considerations

This sample is intentionally simplified for demonstration purposes. In an enterprise deployment, consider the following:

- **Private API Gateway** — The API Gateway is deployed as `REGIONAL` (public) so that demo clients can be run directly from a developer laptop. In production, a `PRIVATE` endpoint type restricts access to traffic originating from within a VPC, which requires clients to run inside the VPC (e.g., ECS tasks, EC2 instances, or via VPN/Direct Connect).
- **Secrets management** — The Cognito client secret is retrieved and stored in a local environment variable for convenience. In production, store secrets in AWS Secrets Manager and retrieve them at runtime.
- **Throttling and rate limiting** — Configure API Gateway usage plans, throttling limits, and per-client rate limiting in the CDK stack to prevent abuse and control costs.
- **Bedrock Guardrails** — Apply [Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html) to enforce content filtering, topic restrictions, and sensitive information redaction.
- **TLS enforcement** — API Gateway uses HTTPS by default, but to enforce TLS 1.2+ and use a custom domain, configure a custom domain name with an ACM certificate in the CDK stack.
- **WAF** — For customer-facing applications, attach AWS WAF rules to the API Gateway to protect against common web exploits (SQL injection, XSS, bot traffic, IP-based throttling).

## Cleanup

```bash
cd infra && cdk destroy
```
