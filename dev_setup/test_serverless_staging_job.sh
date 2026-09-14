#!/usr/bin/env bash
# End-to-end smoke test for DynamoDB -> SQS -> Step Functions -> Fargate -> S3.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
STACK="${SERVERLESS_STAGING_FOUNDATION_STACK:-mopa-rasterizer-serverless-staging}"

output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

BUCKET="$(output ArtifactBucketName)"
TABLE="$(output RuntimeTableName)"
QUEUE_URL="$(output JobQueueUrl)"
TASK_ID="${1:-$(cat /proc/sys/kernel/random/uuid)}"
IMAGE="${SERVERLESS_STAGING_SMOKE_IMAGE:-$REPO_ROOT/test-input.png}"
MATERIAL="${SERVERLESS_STAGING_SMOKE_MATERIAL:-$SCRIPT_DIR/serverless-staging-smoke.clb}"
IMAGE_NAME="$(basename -- "$IMAGE")"
MATERIAL_FILE_NAME="$(basename -- "$MATERIAL")"
SELECTED_MATERIAL="${SERVERLESS_STAGING_SMOKE_SELECTED_MATERIAL:-}"
if [ -z "$SELECTED_MATERIAL" ] && [ -f "$MATERIAL" ]; then
  SELECTED_MATERIAL="$(python3 -c 'import sys, xml.etree.ElementTree as ET; root=ET.parse(sys.argv[1]).getroot(); material=root.find(".//Material"); print(material.get("name", "") if material is not None else "")' "$MATERIAL")"
fi
IMAGE_KEY="jobs/$TASK_ID/inputs/$IMAGE_NAME"
MATERIAL_KEY="jobs/$TASK_ID/inputs/$MATERIAL_FILE_NAME"
NOW="$(date +%s)"
EXPIRES="$((NOW + 604800))"

[ -f "$IMAGE" ] || { echo "Missing artwork: $IMAGE" >&2; exit 2; }
[ -f "$MATERIAL" ] || { echo "Missing Material Library: $MATERIAL" >&2; exit 2; }
[ -n "$SELECTED_MATERIAL" ] || { echo "Could not determine the selected Material Library material." >&2; exit 2; }

aws s3 cp "$IMAGE" "s3://$BUCKET/$IMAGE_KEY" --region "$REGION" --only-show-errors
aws s3 cp "$MATERIAL" "s3://$BUCKET/$MATERIAL_KEY" --region "$REGION" --only-show-errors

export STAGING_TASK_ID="$TASK_ID" STAGING_IMAGE_KEY="$IMAGE_KEY" STAGING_MATERIAL_KEY="$MATERIAL_KEY"
export STAGING_NOW="$NOW" STAGING_EXPIRES="$EXPIRES"
export STAGING_IMAGE_NAME="$IMAGE_NAME" STAGING_MATERIAL_FILE_NAME="$MATERIAL_FILE_NAME"
export STAGING_SELECTED_MATERIAL="$SELECTED_MATERIAL"
ITEM="$(python3 -c '
import json, os
S=lambda value:{"S":str(value)}
task=os.environ["STAGING_TASK_ID"]
data={name:S(value) for name,value in {
 "pixel_square_mm":"0.125","new_width":"400","new_height":"0",
 "material":os.environ["STAGING_SELECTED_MATERIAL"],"colors":"Black,Red","image_preset":"cartoon",
 "abstract_filter":"none","abstract_filter_parameters":"{}","color_name_overrides":"{}","svg_only":"false"
}.items()}
item={"pk":S("JOB#"+task),"sk":S("RUNTIME"),"task_id":S(task),"status":S("pending"),
 "logs":{"L":[S("Serverless staging smoke job accepted.")]},
 "created_at":{"N":os.environ["STAGING_NOW"]},"updated_at":{"N":os.environ["STAGING_NOW"]},
 "expires_at":{"N":os.environ["STAGING_EXPIRES"]},
 "payload":{"M":{"task_id":S(task),"image_key":S(os.environ["STAGING_IMAGE_KEY"]),
 "material_key":S(os.environ["STAGING_MATERIAL_KEY"]),"image_name":S(os.environ["STAGING_IMAGE_NAME"]),
 "material_name":S(os.environ["STAGING_MATERIAL_FILE_NAME"]),"output_name":S("output_"+task+"_"+os.environ["STAGING_IMAGE_NAME"]),
 "data":{"M":data}}}}
print(json.dumps(item,separators=(",",":")))')"

aws dynamodb put-item --region "$REGION" --table-name "$TABLE" --item "$ITEM" \
  --condition-expression 'attribute_not_exists(pk)'
aws sqs send-message --region "$REGION" --queue-url "$QUEUE_URL" \
  --message-body "{\"task_id\":\"$TASK_ID\"}" >/dev/null
echo "Submitted staging task $TASK_ID"

deadline=$((SECONDS + 1200))
while (( SECONDS < deadline )); do
  STATUS="$(aws dynamodb get-item --region "$REGION" --table-name "$TABLE" \
    --key "{\"pk\":{\"S\":\"JOB#$TASK_ID\"},\"sk\":{\"S\":\"RUNTIME\"}}" \
    --consistent-read --query 'Item.status.S' --output text)"
  echo "[$(date -u +%H:%M:%S)] $STATUS"
  case "$STATUS" in
    completed)
      aws s3api list-objects-v2 --region "$REGION" --bucket "$BUCKET" \
        --prefix "jobs/$TASK_ID/outputs/" --query 'Contents[].{Key:Key,Bytes:Size}' --output table
      echo "SERVERLESS_STAGING_SMOKE_PASS task_id=$TASK_ID"
      exit 0
      ;;
    failed)
      aws dynamodb get-item --region "$REGION" --table-name "$TABLE" \
        --key "{\"pk\":{\"S\":\"JOB#$TASK_ID\"},\"sk\":{\"S\":\"RUNTIME\"}}" \
        --consistent-read --output json
      exit 1
      ;;
  esac
  sleep 10
done
echo "Timed out waiting for staging task $TASK_ID" >&2
exit 1
