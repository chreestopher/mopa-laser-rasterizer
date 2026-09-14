#!/usr/bin/env bash
# Give an EC2 subnet private access to the regional S3 and DynamoDB APIs
# without requiring a public IPv4 address or NAT gateway.
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
INSTANCE_ID="${1:-${K3S_WORKER_INSTANCE_ID:-}}"

if [ -z "$INSTANCE_ID" ]; then
  echo "Usage: $0 <ec2-instance-id>" >&2
  exit 2
fi
command -v aws >/dev/null || { echo "Missing command: aws" >&2; exit 2; }

instance_value() {
  aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
    --query "Reservations[0].Instances[0].$1" --output text
}

VPC_ID="$(instance_value VpcId)"
SUBNET_ID="$(instance_value SubnetId)"
if [ -z "$VPC_ID" ] || [ "$VPC_ID" = "None" ] || \
   [ -z "$SUBNET_ID" ] || [ "$SUBNET_ID" = "None" ]; then
  echo "Could not resolve the VPC and subnet for $INSTANCE_ID." >&2
  exit 1
fi

ROUTE_TABLE_ID="$(aws ec2 describe-route-tables --region "$REGION" \
  --filters "Name=association.subnet-id,Values=$SUBNET_ID" \
  --query 'RouteTables[0].RouteTableId' --output text)"
if [ -z "$ROUTE_TABLE_ID" ] || [ "$ROUTE_TABLE_ID" = "None" ]; then
  ROUTE_TABLE_ID="$(aws ec2 describe-route-tables --region "$REGION" \
    --filters "Name=vpc-id,Values=$VPC_ID" \
    --query 'RouteTables[?Associations[?Main]].RouteTableId | [0]' --output text)"
fi
if [ -z "$ROUTE_TABLE_ID" ] || [ "$ROUTE_TABLE_ID" = "None" ]; then
  echo "Could not resolve the route table used by subnet $SUBNET_ID." >&2
  exit 1
fi

ensure_gateway_endpoint() {
  local service="$1" label="$2" service_name endpoint_id associated
  service_name="com.amazonaws.${REGION}.${service}"
  endpoint_id="$(aws ec2 describe-vpc-endpoints --region "$REGION" \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=service-name,Values=$service_name" \
    --query 'VpcEndpoints[?State!=`deleted` && State!=`deleting`].VpcEndpointId | [0]' \
    --output text)"
  if [ -z "$endpoint_id" ] || [ "$endpoint_id" = "None" ]; then
    echo "Creating a $label Gateway endpoint for $VPC_ID on $ROUTE_TABLE_ID"
    endpoint_id="$(aws ec2 create-vpc-endpoint --region "$REGION" \
      --vpc-id "$VPC_ID" --service-name "$service_name" \
      --vpc-endpoint-type Gateway --route-table-ids "$ROUTE_TABLE_ID" \
      --query 'VpcEndpoint.VpcEndpointId' --output text)"
  else
    associated="$(aws ec2 describe-vpc-endpoints --region "$REGION" \
      --vpc-endpoint-ids "$endpoint_id" \
      --query "contains(VpcEndpoints[0].RouteTableIds, '$ROUTE_TABLE_ID')" \
      --output text)"
    if [ "$associated" != "True" ]; then
      echo "Associating $label endpoint $endpoint_id with $ROUTE_TABLE_ID"
      aws ec2 modify-vpc-endpoint --region "$REGION" \
        --vpc-endpoint-id "$endpoint_id" \
        --add-route-table-ids "$ROUTE_TABLE_ID" >/dev/null
    fi
  fi
  aws ec2 create-tags --region "$REGION" --resources "$endpoint_id" \
    --tags "Key=Name,Value=mopa-rasterizer-${service}"
  echo "$label Gateway endpoint ready: $endpoint_id ($ROUTE_TABLE_ID)"
}

ensure_gateway_endpoint s3 S3
ensure_gateway_endpoint dynamodb DynamoDB
