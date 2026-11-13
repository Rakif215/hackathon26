#!/usr/bin/env bash
# Verify AWS access and list which Claude models Bedrock will actually serve us.
# Usage: ./scripts/check_aws.sh [region]
# Workshop Studio allows Oregon (us-west-2) and Ireland (eu-west-1) only.
set -uo pipefail

REGION="${1:-${AWS_REGION:-us-west-2}}"

echo "== Identity =="
if ! aws sts get-caller-identity --output json; then
  cat <<'MSG'

No valid credentials. Workshop Studio credentials are temporary and expire.
To refresh: event dashboard -> "Get AWS CLI credentials" -> copy the
credentials-file block -> paste it into ~/.aws/credentials
MSG
  exit 1
fi

echo
echo "== Bedrock Claude models in $REGION =="
aws bedrock list-foundation-models --region "$REGION" \
  --query "modelSummaries[?contains(modelId,'claude')].[modelId,modelLifecycle.status]" \
  --output table 2>/dev/null \
  || echo "Could not list models — Bedrock may not be enabled, or the role lacks bedrock:ListFoundationModels."

echo
echo "== Inference profiles (cross-region ids, often required for newer models) =="
aws bedrock list-inference-profiles --region "$REGION" \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId,'claude')].inferenceProfileId" \
  --output table 2>/dev/null \
  || echo "No inference profiles listed."

cat <<'MSG'

Reminder (event rules): keep Bedrock under 1 request/second, and do not
request access to more than 5 models.
MSG
