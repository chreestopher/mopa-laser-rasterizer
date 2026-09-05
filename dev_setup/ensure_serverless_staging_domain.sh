#!/usr/bin/env bash
# Idempotently issue/validate CloudFront TLS and attach the staging subdomain.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
HOSTNAME="${SERVERLESS_STAGING_HOSTNAME:-serverless-staging.mopa-laser-rasterizer.com}"
ROOT_DOMAIN="${HOSTNAME#*.}"
WEB_STACK="${SERVERLESS_STAGING_WEB_STACK:-mopa-rasterizer-serverless-staging-web}"

ZONE_ID="$(aws route53 list-hosted-zones-by-name --dns-name "$ROOT_DOMAIN." \
  --query "HostedZones[?Name=='${ROOT_DOMAIN}.'] | [0].Id" --output text)"
ZONE_ID="${ZONE_ID#/hostedzone/}"
[ -n "$ZONE_ID" ] && [ "$ZONE_ID" != "None" ] || { echo "Route 53 hosted zone for $ROOT_DOMAIN was not found." >&2; exit 2; }

CERTIFICATE_ARN="$(aws acm list-certificates --region us-east-1 \
  --certificate-statuses ISSUED PENDING_VALIDATION \
  --query "CertificateSummaryList[?DomainName=='${HOSTNAME}'].CertificateArn | [0]" --output text)"
if [ -z "$CERTIFICATE_ARN" ] || [ "$CERTIFICATE_ARN" = "None" ]; then
  CERTIFICATE_ARN="$(aws acm request-certificate --region us-east-1 \
    --domain-name "$HOSTNAME" --validation-method DNS \
    --options CertificateTransparencyLoggingPreference=ENABLED \
    --tags Key=application,Value=mopa-laser-rasterizer Key=environment,Value=serverless-staging \
    --query CertificateArn --output text)"
fi

VALIDATION_NAME=""
for _attempt in $(seq 1 30); do
  VALIDATION_NAME="$(aws acm describe-certificate --region us-east-1 --certificate-arn "$CERTIFICATE_ARN" \
    --query 'Certificate.DomainValidationOptions[0].ResourceRecord.Name' --output text)"
  VALIDATION_VALUE="$(aws acm describe-certificate --region us-east-1 --certificate-arn "$CERTIFICATE_ARN" \
    --query 'Certificate.DomainValidationOptions[0].ResourceRecord.Value' --output text)"
  [ "$VALIDATION_NAME" != "None" ] && [ -n "$VALIDATION_NAME" ] && break
  sleep 2
done
[ -n "$VALIDATION_NAME" ] && [ "$VALIDATION_NAME" != "None" ] || { echo "ACM DNS validation record was not generated." >&2; exit 1; }

CHANGE_FILE="$(mktemp)"
trap 'rm -f -- "$CHANGE_FILE"' EXIT
VALIDATION_NAME="$VALIDATION_NAME" VALIDATION_VALUE="$VALIDATION_VALUE" python3 -c 'import json,os
print(json.dumps({"Changes":[{"Action":"UPSERT","ResourceRecordSet":{"Name":os.environ["VALIDATION_NAME"],"Type":"CNAME","TTL":300,"ResourceRecords":[{"Value":os.environ["VALIDATION_VALUE"]}]}}]}))' > "$CHANGE_FILE"
aws route53 change-resource-record-sets --hosted-zone-id "$ZONE_ID" --change-batch "file://$CHANGE_FILE" >/dev/null
echo "Waiting for ACM validation in us-east-1: $HOSTNAME"
aws acm wait certificate-validated --region us-east-1 --certificate-arn "$CERTIFICATE_ARN"

SERVERLESS_STAGING_HOSTNAME="$HOSTNAME" SERVERLESS_STAGING_CERTIFICATE_ARN="$CERTIFICATE_ARN" \
  bash "$SCRIPT_DIR/deploy_serverless_staging_web.sh"

DISTRIBUTION_DOMAIN="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$WEB_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDomainName'].OutputValue" --output text)"
HOSTNAME="$HOSTNAME" DISTRIBUTION_DOMAIN="$DISTRIBUTION_DOMAIN" python3 -c 'import json,os
target={"HostedZoneId":"Z2FDTNDATAQYW2","DNSName":os.environ["DISTRIBUTION_DOMAIN"],"EvaluateTargetHealth":False}
print(json.dumps({"Changes":[
 {"Action":"UPSERT","ResourceRecordSet":{"Name":os.environ["HOSTNAME"],"Type":"A","AliasTarget":target}},
 {"Action":"UPSERT","ResourceRecordSet":{"Name":os.environ["HOSTNAME"],"Type":"AAAA","AliasTarget":target}}
]}))' > "$CHANGE_FILE"
CHANGE_ID="$(aws route53 change-resource-record-sets --hosted-zone-id "$ZONE_ID" \
  --change-batch "file://$CHANGE_FILE" --query ChangeInfo.Id --output text)"
aws route53 wait resource-record-sets-changed --id "$CHANGE_ID"
echo "Serverless staging domain ready: https://$HOSTNAME/"
echo "Certificate: $CERTIFICATE_ARN"
