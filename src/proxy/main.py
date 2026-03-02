"""Bedrock proxy Lambda — FastAPI app behind Lambda Web Adapter."""

import json
import os
import re
from datetime import datetime, timezone

from fastapi import Request
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

from bedrock_proxy import proxy_to_bedrock

app = FastAPI()

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")

# Matches model/{modelId}/{operation}
PATH_PATTERN = re.compile(r"^model/(?P<model_id>[^/]+)/(?P<operation>.+)$")


@app.get("/")
@app.get("/health")
async def health():
    """Health/readiness check — LWA probes GET / on cold start."""
    return {"status": "ok", "region": BEDROCK_REGION}


@app.api_route("/{path:path}", methods=["POST", "GET", "PUT", "DELETE"])
async def catch_all(request: Request, path: str):
    """Catch-all route that proxies requests to Bedrock."""
    match = PATH_PATTERN.match(path)
    if not match:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid path: /{path}. Expected /model/{{modelId}}/{{operation}}"},
        )

    model_id = match.group("model_id")
    operation = match.group("operation")

    # Extract custom tracking headers set by the client
    auth_token = request.headers.get("x-auth-token", "")
    workload_id = request.headers.get("x-client-workload-id", "")
    request_tracker = request.headers.get("x-request-tracker", "")

    # print() goes straight to CloudWatch (named loggers don't under LWA)
    print(json.dumps({
        "event": "bedrock_proxy_request",
        "model_id": model_id,
        "operation": operation,
        "workload_id": workload_id,
        "request_tracker": request_tracker,
        "auth_token_present": bool(auth_token),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }))

    try:
        body = await request.body()

        proxy_resp = await proxy_to_bedrock(
            method=request.method,
            path=f"/{path}",
            body=body,
            region=BEDROCK_REGION,
        )

        return StreamingResponse(
            proxy_resp.stream,
            status_code=proxy_resp.status_code,
            media_type=proxy_resp.content_type,
        )
    except Exception as e:
        print(json.dumps({"event": "bedrock_proxy_error", "error": str(e)}))
        return JSONResponse(
            status_code=502,
            content={"error": "Failed to proxy request to Bedrock"},
        )
