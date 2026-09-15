#!/usr/bin/env bash
# Enable selective DynamoDB expiry for runtime and job-history records.
# Durable Material Libraries and palettes do not carry the expires_at attribute.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"

if [ "${1:-}" != "--apply" ]; then
  echo "Refusing to enable DynamoDB TTL without the explicit --apply argument." >&2
  exit 2
fi

REGION="${AWS_REGION:-us-east-2}"
configure_aws_deployment_credentials
TABLE_NAME="${2:-${DYNAMODB_TABLE_NAME:-}}"
TTL_ATTRIBUTE="expires_at"

[ -n "$TABLE_NAME" ] || { echo "A DynamoDB table name is required." >&2; exit 2; }
aws dynamodb describe-table --region "$REGION" --table-name "$TABLE_NAME" >/dev/null

# TTL is configured at table level but applies only to items containing the
# selected numeric attribute. Refuse the change if any durable asset row has
# accidentally acquired that attribute.
durable_ttl_count="$(aws dynamodb scan \
  --region "$REGION" \
  --table-name "$TABLE_NAME" \
  --select COUNT \
  --filter-expression 'attribute_exists(#ttl) AND (begins_with(#sk,:material) OR begins_with(#sk,:depth) OR begins_with(#sk,:holo) OR begins_with(#pk,:community))' \
  --expression-attribute-names '{"#pk":"pk","#sk":"sk","#ttl":"expires_at"}' \
  --expression-attribute-values '{":material":{"S":"MATERIAL#"},":depth":{"S":"DEPTHPALETTE#"},":holo":{"S":"HOLORECIPE#"},":community":{"S":"LASER_COMMUNITY"}}' \
  --query Count --output text | awk '{count += $1} END {print count + 0}')"
if [ "$durable_ttl_count" != "0" ]; then
  echo "Refusing to enable TTL: $durable_ttl_count durable Material Library/palette record(s) contain $TTL_ATTRIBUTE." >&2
  exit 1
fi

ttl_status="$(aws dynamodb describe-time-to-live \
  --region "$REGION" --table-name "$TABLE_NAME" \
  --query 'TimeToLiveDescription.TimeToLiveStatus' --output text)"
ttl_name="$(aws dynamodb describe-time-to-live \
  --region "$REGION" --table-name "$TABLE_NAME" \
  --query 'TimeToLiveDescription.AttributeName' --output text)"

case "$ttl_status" in
  ENABLED|ENABLING)
    if [ "$ttl_name" != "$TTL_ATTRIBUTE" ]; then
      echo "TTL is already $ttl_status with unexpected attribute '$ttl_name'." >&2
      exit 1
    fi
    echo "DynamoDB TTL is already $ttl_status on $TABLE_NAME.$TTL_ATTRIBUTE"
    ;;
  DISABLED|None)
    aws dynamodb update-time-to-live \
      --region "$REGION" \
      --table-name "$TABLE_NAME" \
      --time-to-live-specification "Enabled=true,AttributeName=$TTL_ATTRIBUTE" >/dev/null
    echo "Enabled DynamoDB TTL on $TABLE_NAME.$TTL_ATTRIBUTE"
    ;;
  *)
    echo "DynamoDB TTL is currently $ttl_status; wait for that transition to finish." >&2
    exit 1
    ;;
esac
