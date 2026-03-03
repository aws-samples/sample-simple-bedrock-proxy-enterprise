"""Custom Lambda Authorizer — validates Cognito JWT from x-auth-token header."""

import json
import logging
import os
import time
import urllib.request

import jwt

logger = logging.getLogger("authorizer")
logger.setLevel(logging.INFO)

USER_POOL_ID = os.environ["USER_POOL_ID"]
REGION = os.environ.get("AWS_REGION", "us-east-1")
JWKS_URL = (
    f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"
    "/.well-known/jwks.json"
)
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"

# Cache JWKS keys across invocations (Lambda container reuse)
_jwks_cache: dict = {}
_jwks_cache_time: float = 0
JWKS_CACHE_TTL = 3600  # 1 hour


def _get_jwks() -> dict:
    """Fetch and cache Cognito JWKS."""
    global _jwks_cache, _jwks_cache_time
    if _jwks_cache and (time.time() - _jwks_cache_time) < JWKS_CACHE_TTL:
        return _jwks_cache

    with urllib.request.urlopen(JWKS_URL) as resp:
        _jwks_cache = json.loads(resp.read())
    _jwks_cache_time = time.time()
    return _jwks_cache


def _get_signing_key(token: str) -> jwt.algorithms.RSAAlgorithm:
    """Find the signing key for the token's kid."""
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header["kid"]
    jwks = _get_jwks()
    for key in jwks["keys"]:
        if key["kid"] == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key)
    raise ValueError(f"Key {kid} not found in JWKS")


def handler(event, context):
    """API Gateway TOKEN authorizer handler."""
    token = event.get("authorizationToken", "")
    method_arn = event["methodArn"]

    try:
        signing_key = _get_signing_key(token)
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=ISSUER,
            options={"verify_aud": False},  # client_credentials tokens have no aud
        )

        client_id = claims.get("client_id", "unknown")
        scope = claims.get("scope", "")

        logger.info(json.dumps({
            "event": "auth_success",
            "client_id": client_id,
            "scope": scope,
        }))

        return _build_policy(
            principal_id=client_id,
            effect="Allow",
            resource=method_arn,
            context={"clientId": client_id, "scope": scope},
        )

    except Exception as e:
        logger.warning(json.dumps({"event": "auth_failure", "error": str(e)}))
        return _build_policy(
            principal_id="unauthorized",
            effect="Deny",
            resource=method_arn,
        )


def _build_policy(
    principal_id: str,
    effect: str,
    resource: str,
    context: dict | None = None,
) -> dict:
    """Build IAM policy document for API Gateway authorizer response."""
    # Use wildcard resource so the policy is cacheable across paths
    arn_parts = resource.split(":")
    api_gw_arn = ":".join(arn_parts[:5])
    wildcard_resource = f"{api_gw_arn}:*"

    policy = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": wildcard_resource,
                }
            ],
        },
    }
    if context:
        policy["context"] = context
    return policy
