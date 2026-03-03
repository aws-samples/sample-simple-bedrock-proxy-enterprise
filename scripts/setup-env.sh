#!/usr/bin/env bash
# Retrieves CDK stack outputs and Cognito client secret, then exports them.
#
# Usage:
#   source scripts/setup-env.sh            # uses default region
#   source scripts/setup-env.sh us-west-2  # explicit region
#
# After sourcing, these env vars are set:
#   API_GATEWAY_URL, TOKEN_URL, CLIENT_ID, CLIENT_SECRET

# NOTE: no "set -e" — this script is meant to be sourced, not executed.

REGION="${1:-us-west-2}"
STACK_NAME="BedrockProxyStack"

echo "Fetching stack outputs from $STACK_NAME in $REGION..."

# Get all outputs in one call
OUTPUTS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs' \
  --output json)

get_output() {
  echo "$OUTPUTS" | python3 -c "
import json, sys
outputs = json.load(sys.stdin)
for o in outputs:
    if o['OutputKey'] == '$1':
        print(o['OutputValue'])
        break
"
}

export API_GATEWAY_URL=$(get_output "ApiUrl")
export TOKEN_URL=$(get_output "TokenUrl")
export CLIENT_ID=$(get_output "ClientId")
export INFERENCE_PROFILE_ARN=$(get_output "InferenceProfileArn")

echo "  API_GATEWAY_URL=$API_GATEWAY_URL"
echo "  TOKEN_URL=$TOKEN_URL"
echo "  CLIENT_ID=$CLIENT_ID"
echo "  INFERENCE_PROFILE_ARN=$INFERENCE_PROFILE_ARN"

# Client secret is not in stack outputs — retrieve from Cognito
echo "Fetching Cognito client secret..."

USER_POOL_ID=$(aws cognito-idp list-user-pools \
  --max-results 10 \
  --region "$REGION" \
  --query "UserPools[?Name=='bedrock-proxy-sample'].Id | [0]" \
  --output text)

export CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client \
  --user-pool-id "$USER_POOL_ID" \
  --client-id "$CLIENT_ID" \
  --region "$REGION" \
  --query 'UserPoolClient.ClientSecret' \
  --output text)

echo "  CLIENT_SECRET=****${CLIENT_SECRET: -4}"
echo ""
echo "Environment ready. Run a demo:"
echo "  cd src/client && python demo_boto3.py"
