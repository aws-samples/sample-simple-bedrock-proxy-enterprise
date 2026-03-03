"""Raw byte proxy to Bedrock using httpx + SigV4 signing."""

import logging
from dataclasses import dataclass, field
from typing import AsyncGenerator

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

logger = logging.getLogger("bedrock-proxy")


@dataclass
class ProxyResponse:
    """Holds the streaming generator and upstream response metadata."""

    stream: AsyncGenerator[bytes, None]
    status_code: int = 502
    content_type: str = "application/json"
    _client: httpx.AsyncClient = field(default=None, repr=False)
    _response: httpx.Response = field(default=None, repr=False)


async def proxy_to_bedrock(
    method: str,
    path: str,
    body: bytes,
    region: str,
) -> ProxyResponse:
    """
    Open a streaming connection to Bedrock and return a ProxyResponse.

    The caller gets status_code and content_type immediately (after the
    upstream response headers arrive), then iterates `stream` for raw bytes.
    """
    bedrock_url = f"https://bedrock-runtime.{region}.amazonaws.com{path}"
    logger.info("Proxying %s %s", method, bedrock_url)

    # Sign with the Lambda's IAM credentials
    session = boto3.Session()
    credentials = session.get_credentials().get_frozen_credentials()

    aws_request = AWSRequest(
        method=method,
        url=bedrock_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(credentials, "bedrock", region).add_auth(aws_request)

    signed_headers = dict(aws_request.headers)

    # Open client with proper timeout
    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))
    try:
        response = await client.send(
            httpx.Request(method, bedrock_url, headers=signed_headers, content=body),
            stream=True,
        )
    except Exception:
        await client.aclose()
        logger.exception("Failed to connect to Bedrock at %s", bedrock_url)
        raise

    logger.info(
        "Bedrock responded: status=%d content_type=%s",
        response.status_code,
        response.headers.get("content-type"),
    )

    async def stream_bytes() -> AsyncGenerator[bytes, None]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return ProxyResponse(
        stream=stream_bytes(),
        status_code=response.status_code,
        content_type=response.headers.get("content-type", "application/json"),
        _client=client,
        _response=response,
    )
