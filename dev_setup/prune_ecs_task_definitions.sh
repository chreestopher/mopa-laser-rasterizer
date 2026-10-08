#!/usr/bin/env bash
# Retain only the newest task-definition revisions for the supplied families.
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
RETAIN="${ECS_TASK_DEFINITION_RETAIN_COUNT:-10}"

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 TASK_DEFINITION_FAMILY [...]" >&2
  exit 2
fi

case "$RETAIN" in
  ''|*[!0-9]*)
    echo "ECS_TASK_DEFINITION_RETAIN_COUNT must be a positive integer." >&2
    exit 2
    ;;
esac
if [ "$RETAIN" -lt 1 ]; then
  echo "ECS_TASK_DEFINITION_RETAIN_COUNT must be at least 1." >&2
  exit 2
fi

for family in "$@"; do
  definition_output="$(aws ecs list-task-definitions \
    --region "$REGION" \
    --family-prefix "$family" \
    --status ACTIVE \
    --sort DESC \
    --query 'taskDefinitionArns' \
    --output text)"
  mapfile -t definitions < <(printf '%s\n' "$definition_output" | tr '\t' '\n' | awk -v expected="$family" '
      $0 ~ ("task-definition/" expected ":[0-9]+$") { print }
    ')

  if [ "${#definitions[@]}" -le "$RETAIN" ]; then
    echo "Retaining all ${#definitions[@]} active revisions for $family."
    continue
  fi

  echo "Retaining the newest $RETAIN active revisions for $family; deregistering $((${#definitions[@]} - RETAIN)) older revisions."
  for definition in "${definitions[@]:RETAIN}"; do
    aws ecs deregister-task-definition \
      --region "$REGION" \
      --task-definition "$definition" >/dev/null
  done
done
