#!/usr/bin/env bash
# Ensure an EC2 instance's subnet route table can reach regional S3 without
# requiring a public IPv4 address or NAT gateway.
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

SERVICE_NAME="com.amazonaws.${REGION}.s3"
ENDPOINT_ID="$(aws ec2 describe-vpc-endpoints --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=service-name,Values=$SERVICE_NAME" \
  --query 'VpcEndpoints[?State!=`deleted` && State!=`deleting`].VpcEndpointId | [0]' \
  --output text)"

if [ -z "$ENDPOINT_ID" ] || [ "$ENDPOINT_ID" = "None" ]; then
  echo "Creating an S3 Gateway endpoint for $VPC_ID on $ROUTE_TABLE_ID"
  ENDPOINT_ID="$(aws ec2 create-vpc-endpoint --region "$REGION" \
    --vpc-id "$VPC_ID" --service-name "$SERVICE_NAME" \
    --vpc-endpoint-type Gateway --route-table-ids "$ROUTE_TABLE_ID" \
    --query 'VpcEndpoint.VpcEndpointId' --output text)"
else
  ASSOCIATED="$(aws ec2 describe-vpc-endpoints --region "$REGION" \
    --vpc-endpoint-ids "$ENDPOINT_ID" \
    --query "contains(VpcEndpoints[0].RouteTableIds, '$ROUTE_TABLE_ID')" \
    --output text)"
  if [ "$ASSOCIATED" != "True" ]; then
    echo "Associating S3 endpoint $ENDPOINT_ID with $ROUTE_TABLE_ID"
    aws ec2 modify-vpc-endpoint --region "$REGION" \
      --vpc-endpoint-id "$ENDPOINT_ID" \
      --add-route-table-ids "$ROUTE_TABLE_ID" >/dev/null
  fi
fi

aws ec2 create-tags --region "$REGION" --resources "$ENDPOINT_ID" \
  --tags Key=Name,Value=mopa-rasterizer-s3

echo "S3 Gateway endpoint ready: $ENDPOINT_ID ($ROUTE_TABLE_ID)"
