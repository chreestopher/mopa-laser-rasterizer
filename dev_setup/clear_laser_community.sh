#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Delete every Comunity Set record from the configured DynamoDB table.

Usage:
  ./dev_setup/clear_laser_community.sh --confirm [--table TABLE] [--region REGION]

The script only deletes items whose partition key begins with LASER_COMMUNITY.
Private user Material Vault records are not selected.
EOF
}

TABLE_NAME="${DYNAMODB_TABLE_NAME:-mopa-laser-rasterizer-users}"
REGION="${AWS_REGION:-us-east-2}"
CONFIRMED=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --confirm) CONFIRMED=true; shift ;;
    --table) TABLE_NAME="${2:?--table requires a value}"; shift 2 ;;
    --region) REGION="${2:?--region requires a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$CONFIRMED" != true ]]; then
  echo "Refusing to delete data without --confirm." >&2
  usage >&2
  exit 2
fi

for command_name in aws jq; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command not found: $command_name" >&2
    exit 1
  fi
done

echo "Scanning DynamoDB table '$TABLE_NAME' in '$REGION' for Comunity Set records..."

scan_output="$(mktemp)"
request_file="$(mktemp)"
response_file="$(mktemp)"
trap 'rm -f "$scan_output" "$request_file" "$response_file"' EXIT

aws dynamodb scan \
  --table-name "$TABLE_NAME" \
  --region "$REGION" \
  --projection-expression "pk, sk" \
  --filter-expression "begins_with(pk, :community_prefix)" \
  --expression-attribute-values '{":community_prefix":{"S":"LASER_COMMUNITY"}}' \
  --output json > "$scan_output"

record_count="$(jq '.Items | length' "$scan_output")"
if [[ "$record_count" -eq 0 ]]; then
  echo "No Comunity Set records found."
  exit 0
fi

echo "Deleting $record_count Comunity Set record(s)..."

offset=0
while [[ "$offset" -lt "$record_count" ]]; do
  jq --arg table "$TABLE_NAME" --argjson offset "$offset" '
    {($table): [.Items[$offset:$offset + 25][] | {
      DeleteRequest: {Key: {pk: .pk, sk: .sk}}
    }]}
  ' "$scan_output" > "$request_file"

  while [[ "$(jq --arg table "$TABLE_NAME" '.[$table] | length' "$request_file")" -gt 0 ]]; do
    aws dynamodb batch-write-item \
      --region "$REGION" \
      --request-items "file://$request_file" \
      --output json > "$response_file"
    jq '.UnprocessedItems' "$response_file" > "$request_file"
    if [[ "$(jq --arg table "$TABLE_NAME" '.[$table] // [] | length' "$request_file")" -gt 0 ]]; then
      sleep 1
    fi
  done

  offset=$((offset + 25))
done

echo "Comunity Set development data removed. Private Material Vault records were not touched."
