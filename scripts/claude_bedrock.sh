#!/usr/bin/env bash
# Launch Claude Code billed to the event AWS account (Bedrock) instead of a personal plan.
#
#   ./scripts/claude_bedrock.sh
#
# Override the model with:  CLAUDE_MODEL=us.anthropic.claude-sonnet-5-5 ./scripts/claude_bedrock.sh
set -uo pipefail

export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION="${AWS_REGION:-us-west-2}"
export ANTHROPIC_MODEL="${CLAUDE_MODEL:-us.anthropic.claude-opus-5-5}"
export ANTHROPIC_SMALL_FAST_MODEL="${CLAUDE_SMALL_MODEL:-us.anthropic.claude-haiku-5-5}"

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  echo "AWS credentials are missing or expired."
  echo "Refresh them first:  ./scripts/aws_creds.sh"
  exit 1
fi

echo "Claude Code -> Bedrock"
echo "  region $AWS_REGION"
echo "  model  $ANTHROPIC_MODEL"
echo
echo "Note: event rules cap Bedrock at ~1 request/second. Claude Code is bursty,"
echo "so expect throttling on heavy turns. Credentials also expire every few hours."
echo

exec claude "$@"
