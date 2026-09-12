#!/usr/bin/env bash
# Safely exercise the staging pause banner, worker gate, and automatic recovery.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
FOUNDATION_STACK="${SERVERLESS_STAGING_FOUNDATION_STACK:-mopa-rasterizer-serverless-staging}"
PIPE_NAME="${SERVERLESS_STAGING_PIPE_NAME:-mopa-rasterizer-serverless-staging-to-fargate}"
API_URL="${SERVERLESS_STAGING_API_URL:-https://9hh3s68rod.execute-api.us-east-2.amazonaws.com}"

output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

TABLE="$(output "$FOUNDATION_STACK" RuntimeTableName)"
QUEUE_URL="$(output "$FOUNDATION_STACK" JobQueueUrl)"
CONTROL_KEY='{"pk":{"S":"SYSTEM#SERVICE"},"sk":{"S":"CONTROL"}}'
ATTRIBUTE_NAMES='{"#status":"status"}'
paused=false

resume() {
  if [ "$paused" != true ]; then return; fi
  local state
  state="$(aws pipes describe-pipe --region "$REGION" --name "$PIPE_NAME" --query CurrentState --output text)"
  if [ "$state" != RUNNING ] && [ "$state" != STARTING ]; then
    aws pipes start-pipe --region "$REGION" --name "$PIPE_NAME" >/dev/null
  fi
  aws dynamodb update-item --region "$REGION" --table-name "$TABLE" \
    --key "$CONTROL_KEY" \
    --update-expression 'SET #status=:active, updated_at=:now, updated_by=:actor REMOVE pause_reason, resumes_at' \
    --expression-attribute-names "$ATTRIBUTE_NAMES" \
    --expression-attribute-values "{\":active\":{\"S\":\"active\"},\":now\":{\"N\":\"$(date +%s)\"},\":actor\":{\"S\":\"acceptance-test-cleanup\"}}" >/dev/null
  paused=false
}
trap resume EXIT

QUEUE_COUNTS="$(aws sqs get-queue-attributes --region "$REGION" --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible ApproximateNumberOfMessagesDelayed \
  --query '[Attributes.ApproximateNumberOfMessages,Attributes.ApproximateNumberOfMessagesNotVisible,Attributes.ApproximateNumberOfMessagesDelayed]' --output text)"
[ "$QUEUE_COUNTS" = $'0\t0\t0' ] || { echo "Refusing to pause a non-empty staging queue: $QUEUE_COUNTS" >&2; exit 2; }
[ "$(aws ecs list-tasks --region "$REGION" --cluster mopa-rasterizer-serverless-staging --desired-status RUNNING --query 'length(taskArns)' --output text)" = 0 ] || {
  echo "Refusing to pause while a staging worker is running." >&2; exit 2;
}

NOW="$(date +%s)"
NEXT_MONTH="$(date -u -d "$(date -u +%Y-%m-01) +1 month" +%s)"
VALUES="{\":paused\":{\"S\":\"paused\"},\":reason\":{\"S\":\"overspending\"},\":resumes\":{\"N\":\"$NEXT_MONTH\"},\":now\":{\"N\":\"$NOW\"},\":actor\":{\"S\":\"acceptance-test\"}}"
aws dynamodb update-item --region "$REGION" --table-name "$TABLE" --key "$CONTROL_KEY" \
  --update-expression 'SET #status=:paused, pause_reason=:reason, resumes_at=:resumes, updated_at=:now, updated_by=:actor' \
  --expression-attribute-names "$ATTRIBUTE_NAMES" --expression-attribute-values "$VALUES" >/dev/null
paused=true
aws pipes stop-pipe --region "$REGION" --name "$PIPE_NAME" >/dev/null

for _ in {1..24}; do
  PIPE_STATE="$(aws pipes describe-pipe --region "$REGION" --name "$PIPE_NAME" --query CurrentState --output text)"
  [ "$PIPE_STATE" = STOPPED ] && break
  sleep 5
done
[ "$PIPE_STATE" = STOPPED ] || { echo "Pipe did not stop; cleanup will restore service." >&2; exit 1; }
STATUS="$(curl -fsS "$API_URL/service-status")"
printf '%s' "$STATUS" | grep -q '"status":"paused"'
printf '%s' "$STATUS" | grep -q '"processing_available":false'

# Make the pause due, then let the public status endpoint exercise the same
# automatic recovery used at the first request of a new billing cycle.
aws dynamodb update-item --region "$REGION" --table-name "$TABLE" --key "$CONTROL_KEY" \
  --update-expression 'SET resumes_at=:due' \
  --expression-attribute-values "{\":due\":{\"N\":\"$((NOW - 1))\"}}" >/dev/null
STATUS="$(curl -fsS "$API_URL/service-status")"
printf '%s' "$STATUS" | grep -q '"status":"active"'
for _ in {1..24}; do
  PIPE_STATE="$(aws pipes describe-pipe --region "$REGION" --name "$PIPE_NAME" --query CurrentState --output text)"
  [ "$PIPE_STATE" = RUNNING ] && break
  sleep 5
done
[ "$PIPE_STATE" = RUNNING ]
paused=false
echo "Staging pause banner, stopped dispatch, and automatic recovery are working."
