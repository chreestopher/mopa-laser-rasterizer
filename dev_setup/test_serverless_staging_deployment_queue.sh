#!/usr/bin/env bash
# Verify that a real staging job remains queued across a worker/orchestration deployment.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"

REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
FOUNDATION_STACK="${SERVERLESS_STAGING_FOUNDATION_STACK:-mopa-rasterizer-serverless-staging}"
WORKER_STACK="${SERVERLESS_STAGING_WORKER_STACK:-mopa-rasterizer-serverless-staging-worker}"
PIPE_NAME="${SERVERLESS_STAGING_PIPE_NAME:-mopa-rasterizer-serverless-staging-to-fargate}"
SMOKE_IMAGE="${SERVERLESS_STAGING_QUEUE_TEST_IMAGE:-$REPO_ROOT/test-input.png}"
SMOKE_MATERIAL="${SERVERLESS_STAGING_QUEUE_TEST_MATERIAL:-$SCRIPT_DIR/serverless-staging-smoke.clb}"
REQUIRE_REVISION_CHANGE="${SERVERLESS_STAGING_QUEUE_TEST_REQUIRE_REVISION_CHANGE:-true}"
TASK_ID="${1:-$(cat /proc/sys/kernel/random/uuid)}"
SMOKE_LOG="$(mktemp)"

pipe_owned=false
deployment_started=false
deployment_succeeded=false
smoke_pid=""

stack_output() {
  stack="$1"
  key="$2"
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$stack" \
    --query "Stacks[0].Outputs[?OutputKey=='$key'].OutputValue" --output text
}

wait_for_pipe_state() {
  expected="$1"
  attempts=0
  while [ "$attempts" -lt 60 ]; do
    current="$(aws pipes describe-pipe --region "$REGION" --name "$PIPE_NAME" \
      --query CurrentState --output text)"
    [ "$current" = "$expected" ] && return 0
    attempts=$((attempts + 1))
    sleep 2
  done
  echo "Timed out waiting for EventBridge Pipe $PIPE_NAME to reach $expected." >&2
  return 1
}

cleanup() {
  status=$?
  if [ -n "$smoke_pid" ] && kill -0 "$smoke_pid" 2>/dev/null; then
    kill "$smoke_pid" 2>/dev/null || true
    wait "$smoke_pid" 2>/dev/null || true
  fi
  if [ "$pipe_owned" = true ]; then
    if [ "$deployment_started" = false ] || [ "$deployment_succeeded" = true ]; then
      echo "Restoring staging dispatch after interrupted queue test..." >&2
      aws pipes start-pipe --region "$REGION" --name "$PIPE_NAME" >/dev/null || true
      wait_for_pipe_state RUNNING || true
    else
      echo "Deployment did not complete; staging dispatch remains STOPPED so the queued job is preserved." >&2
    fi
  fi
  rm -f -- "$SMOKE_LOG"
  exit "$status"
}
trap cleanup EXIT INT TERM

[ -f "$SMOKE_IMAGE" ] || { echo "Missing queue-test artwork: $SMOKE_IMAGE" >&2; exit 2; }
[ -f "$SMOKE_MATERIAL" ] || { echo "Missing queue-test Material Library: $SMOKE_MATERIAL" >&2; exit 2; }
aws sts get-caller-identity >/dev/null

initial_pipe_state="$(aws pipes describe-pipe --region "$REGION" --name "$PIPE_NAME" \
  --query CurrentState --output text)"
[ "$initial_pipe_state" = "RUNNING" ] || {
  echo "Refusing to start: staging dispatch is $initial_pipe_state, not RUNNING." >&2
  exit 2
}

runtime_table="$(stack_output "$FOUNDATION_STACK" RuntimeTableName)"
before_task_definition="$(stack_output "$WORKER_STACK" TaskDefinitionArn)"

echo "Stopping staging dispatch before queueing task $TASK_ID..."
aws pipes stop-pipe --region "$REGION" --name "$PIPE_NAME" >/dev/null
wait_for_pipe_state STOPPED
pipe_owned=true

SERVERLESS_STAGING_SMOKE_IMAGE="$SMOKE_IMAGE" \
SERVERLESS_STAGING_SMOKE_MATERIAL="$SMOKE_MATERIAL" \
  bash "$SCRIPT_DIR/test_serverless_staging_job.sh" "$TASK_ID" >"$SMOKE_LOG" 2>&1 &
smoke_pid=$!

echo "Waiting for the smoke task to be recorded while dispatch is stopped..."
attempts=0
queued_status=""
while [ "$attempts" -lt 60 ]; do
  queued_status="$(aws dynamodb get-item --region "$REGION" --table-name "$runtime_table" \
    --key "{\"pk\":{\"S\":\"JOB#$TASK_ID\"},\"sk\":{\"S\":\"RUNTIME\"}}" \
    --consistent-read --query 'Item.status.S' --output text 2>/dev/null || true)"
  [ "$queued_status" = "pending" ] && break
  if ! kill -0 "$smoke_pid" 2>/dev/null; then
    cat "$SMOKE_LOG" >&2
    echo "Smoke submission exited before the task reached Pending." >&2
    exit 1
  fi
  attempts=$((attempts + 1))
  sleep 1
done
[ "$queued_status" = "pending" ] || {
  echo "Task did not reach Pending while dispatch was stopped." >&2
  exit 1
}
sleep 5
current_pipe_state="$(aws pipes describe-pipe --region "$REGION" --name "$PIPE_NAME" \
  --query CurrentState --output text)"
[ "$current_pipe_state" = "STOPPED" ] || {
  echo "Dispatch unexpectedly changed to $current_pipe_state." >&2
  exit 1
}
echo "PASS: task $TASK_ID remained Pending while dispatch was STOPPED."

deployment_started=true
echo "Running the normal staging worker/orchestration deployment with the task queued..."
bash "$SCRIPT_DIR/deploy_serverless_staging.sh"
deployment_succeeded=true
after_task_definition="$(stack_output "$WORKER_STACK" TaskDefinitionArn)"

if [ "$before_task_definition" = "$after_task_definition" ]; then
  if [ "$REQUIRE_REVISION_CHANGE" = "true" ]; then
    echo "Deployment was a no-op and did not create a new task-definition revision; the revision-transition test is incomplete." >&2
    exit 1
  fi
  echo "NOTICE: task definition did not change; only queue pause/resume behavior was exercised."
else
  echo "PASS: task definition changed from $before_task_definition to $after_task_definition while dispatch remained stopped."
fi

echo "Restarting dispatch and waiting for the queued task to complete..."
aws pipes start-pipe --region "$REGION" --name "$PIPE_NAME" >/dev/null
wait_for_pipe_state RUNNING
pipe_owned=false

if ! wait "$smoke_pid"; then
  cat "$SMOKE_LOG" >&2
  echo "Queued staging task failed after dispatch resumed." >&2
  exit 1
fi
smoke_pid=""
cat "$SMOKE_LOG"
echo "SERVERLESS_STAGING_DEPLOYMENT_QUEUE_PASS task_id=$TASK_ID"
