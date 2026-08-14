#!/usr/bin/env bash
# Run from AWS CloudShell. Creates repeatable account-level app resources.
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET_NAME="${S3_BUCKET_NAME:-mopa-laser-rasterizer-artifacts-${ACCOUNT_ID}}"
TABLE_NAME="${DYNAMODB_TABLE_NAME:-mopa-laser-rasterizer-users}"
ROLE_NAME="${EC2_ROLE_NAME:-mopa-laser-rasterizer-ec2}"
PROFILE_NAME="${EC2_PROFILE_NAME:-mopa-laser-rasterizer-ec2}"

# Optional edge/authentication setup. Keep these empty in Git and provide
# them at runtime, for example: CONFIGURE_EDGE=1 VPC_ID=vpc-... ./script.sh
CONFIGURE_EDGE="${CONFIGURE_EDGE:-0}"
CREATE_COGNITO="${CREATE_COGNITO:-0}"
APP_DOMAIN="${APP_DOMAIN:-mopa-laser-rasterizer.com}"
VPC_ID="${VPC_ID:-}"
ALB_SUBNET_IDS="${ALB_SUBNET_IDS:-}"              # Two or more subnet IDs, space separated.
ALB_SECURITY_GROUP_ID="${ALB_SECURITY_GROUP_ID:-}"
EC2_INSTANCE_ID="${EC2_INSTANCE_ID:-}"
ROUTE53_HOSTED_ZONE_ID="${ROUTE53_HOSTED_ZONE_ID:-}"
CERTIFICATE_ARN="${CERTIFICATE_ARN:-}"
COGNITO_POOL_ID="${COGNITO_POOL_ID:-}"
COGNITO_CLIENT_ID="${COGNITO_CLIENT_ID:-}"
COGNITO_CLIENT_SECRET="${COGNITO_CLIENT_SECRET:-}" # Secret: runtime only.
COGNITO_USER_POOL_DOMAIN_PREFIX="${COGNITO_USER_POOL_DOMAIN_PREFIX:-}"
COGNITO_POOL_NAME="${COGNITO_POOL_NAME:-mopa-laser-rasterizer}"
COGNITO_CLIENT_NAME="${COGNITO_CLIENT_NAME:-alb}"
ALB_NAME="${ALB_NAME:-mopa-laser-rasterizer}"
TARGET_GROUP_NAME="${TARGET_GROUP_NAME:-mopa-laser-rasterizer}"

echo "Configuring bucket: $BUCKET_NAME"
if ! aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
  aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION" \
    --create-bucket-configuration "LocationConstraint=${REGION}"
fi
aws s3api put-public-access-block --bucket "$BUCKET_NAME" --public-access-block-configuration \
  'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'
aws s3api put-bucket-encryption --bucket "$BUCKET_NAME" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET_NAME" --lifecycle-configuration \
  '{"Rules":[{"ID":"expire-guest-job-artifacts-after-7-days","Status":"Enabled","Filter":{"Prefix":"jobs/"},"Expiration":{"Days":7}},{"ID":"expire-account-job-artifacts-after-7-days","Status":"Enabled","Filter":{"Tag":{"Key":"mopa-retention","Value":"job"}},"Expiration":{"Days":7}},{"ID":"abort-incomplete-uploads-after-1-day","Status":"Enabled","Filter":{"Prefix":""},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}]}'

echo "Configuring DynamoDB table: $TABLE_NAME"
if ! aws dynamodb describe-table --table-name "$TABLE_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws dynamodb create-table --table-name "$TABLE_NAME" --region "$REGION" \
    --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S \
    --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST >/dev/null
  aws dynamodb wait table-exists --table-name "$TABLE_NAME" --region "$REGION"
fi

TRUST_FILE="$(mktemp)"; POLICY_FILE="$(mktemp)"
trap 'rm -f "$TRUST_FILE" "$POLICY_FILE"' EXIT
printf '%s' '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' > "$TRUST_FILE"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "file://${TRUST_FILE}" >/dev/null
fi
cat > "$POLICY_FILE" <<JSON
{"Version":"2012-10-17","Statement":[
{"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::${BUCKET_NAME}"},
{"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:PutObjectTagging","s3:DeleteObject"],"Resource":"arn:aws:s3:::${BUCKET_NAME}/*"},
{"Effect":"Allow","Action":["dynamodb:BatchGetItem","dynamodb:BatchWriteItem","dynamodb:DeleteItem","dynamodb:DescribeTable","dynamodb:GetItem","dynamodb:PutItem","dynamodb:Query","dynamodb:UpdateItem"],"Resource":"arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"}]}
JSON
aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name MopaRasterizerAccountData --policy-document "file://${POLICY_FILE}"
if ! aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null
fi
if ! aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" --query "InstanceProfile.Roles[?RoleName=='${ROLE_NAME}'].RoleName" --output text | grep -q "$ROLE_NAME"; then
  aws iam add-role-to-instance-profile --instance-profile-name "$PROFILE_NAME" --role-name "$ROLE_NAME"
fi

if [ "$CREATE_COGNITO" = "1" ]; then
  if [ -z "$COGNITO_USER_POOL_DOMAIN_PREFIX" ]; then
    echo "CREATE_COGNITO=1 requires COGNITO_USER_POOL_DOMAIN_PREFIX." >&2
    exit 2
  fi
  if [ -z "$COGNITO_POOL_ID" ]; then
    echo "Creating Cognito user pool: $COGNITO_POOL_NAME"
    COGNITO_POOL_ID="$(aws cognito-idp create-user-pool --region "$REGION" --pool-name "$COGNITO_POOL_NAME" --username-attributes email --auto-verified-attributes email --query 'UserPool.Id' --output text)"
    aws cognito-idp create-user-pool-domain --region "$REGION" --user-pool-id "$COGNITO_POOL_ID" --domain "$COGNITO_USER_POOL_DOMAIN_PREFIX"
  fi
  if [ -z "$COGNITO_CLIENT_ID" ] || [ -z "$COGNITO_CLIENT_SECRET" ]; then
    CLIENT_JSON="$(aws cognito-idp create-user-pool-client --region "$REGION" --user-pool-id "$COGNITO_POOL_ID" --client-name "$COGNITO_CLIENT_NAME" --generate-secret --allowed-oauth-flows-user-pool-client --allowed-oauth-flows code --allowed-oauth-scopes openid email profile --supported-identity-providers COGNITO --callback-urls "https://${APP_DOMAIN}/oauth2/idpresponse" --logout-urls "https://${APP_DOMAIN}/")"
    COGNITO_CLIENT_ID="$(printf '%s' "$CLIENT_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["UserPoolClient"]["ClientId"])')"
    COGNITO_CLIENT_SECRET="$(printf '%s' "$CLIENT_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["UserPoolClient"]["ClientSecret"])')"
    echo "A new Cognito client secret was generated. Save it securely now: $COGNITO_CLIENT_SECRET" >&2
  fi
  printf 'COGNITO_POOL_ID=%s\nCOGNITO_CLIENT_ID=%s\nCOGNITO_DOMAIN=%s.auth.%s.amazoncognito.com\n' "$COGNITO_POOL_ID" "$COGNITO_CLIENT_ID" "$COGNITO_USER_POOL_DOMAIN_PREFIX" "$REGION"
fi

if [ "$CONFIGURE_EDGE" = "1" ]; then
  for variable_name in VPC_ID ALB_SUBNET_IDS ALB_SECURITY_GROUP_ID EC2_INSTANCE_ID ROUTE53_HOSTED_ZONE_ID CERTIFICATE_ARN COGNITO_POOL_ID COGNITO_CLIENT_ID COGNITO_CLIENT_SECRET COGNITO_USER_POOL_DOMAIN_PREFIX; do
    if [ -z "${!variable_name}" ]; then
      echo "CONFIGURE_EDGE=1 requires $variable_name to be supplied at runtime." >&2
      exit 2
    fi
  done

  echo "Configuring ALB, target group, Cognito listener actions, and Route 53"
  ALB_ARN="$(aws elbv2 describe-load-balancers --region "$REGION" --names "$ALB_NAME" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || true)"
  if [ "$ALB_ARN" = "None" ] || [ -z "$ALB_ARN" ]; then
    # ALB_SUBNET_IDS is intentionally space-separated AWS CLI arguments.
    # shellcheck disable=SC2086
    ALB_ARN="$(aws elbv2 create-load-balancer --region "$REGION" --name "$ALB_NAME" --type application --scheme internet-facing --ip-address-type ipv4 --subnets $ALB_SUBNET_IDS --security-groups "$ALB_SECURITY_GROUP_ID" --query 'LoadBalancers[0].LoadBalancerArn' --output text)"
    aws elbv2 wait load-balancer-available --region "$REGION" --load-balancer-arns "$ALB_ARN"
  fi
  TARGET_GROUP_ARN="$(aws elbv2 describe-target-groups --region "$REGION" --names "$TARGET_GROUP_NAME" --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || true)"
  if [ "$TARGET_GROUP_ARN" = "None" ] || [ -z "$TARGET_GROUP_ARN" ]; then
    TARGET_GROUP_ARN="$(aws elbv2 create-target-group --region "$REGION" --name "$TARGET_GROUP_NAME" --protocol HTTP --port 30080 --target-type instance --vpc-id "$VPC_ID" --health-check-path /auth-status --matcher HttpCode=200 --query 'TargetGroups[0].TargetGroupArn' --output text)"
  fi
  aws elbv2 register-targets --region "$REGION" --target-group-arn "$TARGET_GROUP_ARN" --targets "Id=${EC2_INSTANCE_ID},Port=30080"

  HTTP_LISTENER_ARN="$(aws elbv2 describe-listeners --region "$REGION" --load-balancer-arn "$ALB_ARN" --query 'Listeners[?Port==`80`].ListenerArn | [0]' --output text)"
  HTTP_ACTIONS='[{"Type":"redirect","RedirectConfig":{"Protocol":"HTTPS","Port":"443","Host":"#{host}","Path":"/#{path}","Query":"#{query}","StatusCode":"HTTP_301"}}]'
  if [ "$HTTP_LISTENER_ARN" = "None" ] || [ -z "$HTTP_LISTENER_ARN" ]; then
    aws elbv2 create-listener --region "$REGION" --load-balancer-arn "$ALB_ARN" --protocol HTTP --port 80 --default-actions "$HTTP_ACTIONS" >/dev/null
  else
    aws elbv2 modify-listener --region "$REGION" --listener-arn "$HTTP_LISTENER_ARN" --default-actions "$HTTP_ACTIONS" >/dev/null
  fi

  ACTION_FILE="$(mktemp)"; LOGOUT_FILE="$(mktemp)"; LOGIN_FILE="$(mktemp)"
  trap 'rm -f "$TRUST_FILE" "$POLICY_FILE" "$ACTION_FILE" "$LOGOUT_FILE" "$LOGIN_FILE"' EXIT
  cat > "$ACTION_FILE" <<JSON
[{"Type":"authenticate-cognito","Order":1,"AuthenticateCognitoConfig":{"UserPoolArn":"arn:aws:cognito-idp:${REGION}:${ACCOUNT_ID}:userpool/${COGNITO_POOL_ID}","UserPoolClientId":"${COGNITO_CLIENT_ID}","UserPoolClientSecret":"${COGNITO_CLIENT_SECRET}","UserPoolDomain":"${COGNITO_USER_POOL_DOMAIN_PREFIX}","OnUnauthenticatedRequest":"allow","Scope":"openid email profile","SessionCookieName":"AWSELBAuthSessionCookie","SessionTimeout":604800}},{"Type":"forward","Order":2,"ForwardConfig":{"TargetGroups":[{"TargetGroupArn":"${TARGET_GROUP_ARN}","Weight":1}]}}]
JSON
  cat > "$LOGOUT_FILE" <<JSON
[{"Type":"forward","TargetGroupArn":"${TARGET_GROUP_ARN}"}]
JSON
  cat > "$LOGIN_FILE" <<JSON
[{"Type":"authenticate-cognito","Order":1,"AuthenticateCognitoConfig":{"UserPoolArn":"arn:aws:cognito-idp:${REGION}:${ACCOUNT_ID}:userpool/${COGNITO_POOL_ID}","UserPoolClientId":"${COGNITO_CLIENT_ID}","UserPoolClientSecret":"${COGNITO_CLIENT_SECRET}","UserPoolDomain":"${COGNITO_USER_POOL_DOMAIN_PREFIX}","OnUnauthenticatedRequest":"authenticate","Scope":"openid email profile","SessionCookieName":"AWSELBAuthSessionCookie","SessionTimeout":604800}},{"Type":"forward","Order":2,"ForwardConfig":{"TargetGroups":[{"TargetGroupArn":"${TARGET_GROUP_ARN}","Weight":1}]}}]
JSON
  HTTPS_LISTENER_ARN="$(aws elbv2 describe-listeners --region "$REGION" --load-balancer-arn "$ALB_ARN" --query 'Listeners[?Port==`443`].ListenerArn | [0]' --output text)"
  if [ "$HTTPS_LISTENER_ARN" = "None" ] || [ -z "$HTTPS_LISTENER_ARN" ]; then
    HTTPS_LISTENER_ARN="$(aws elbv2 create-listener --region "$REGION" --load-balancer-arn "$ALB_ARN" --protocol HTTPS --port 443 --certificates "CertificateArn=${CERTIFICATE_ARN}" --default-actions "file://${ACTION_FILE}" --query 'Listeners[0].ListenerArn' --output text)"
  else
    aws elbv2 modify-listener --region "$REGION" --listener-arn "$HTTPS_LISTENER_ARN" --certificates "CertificateArn=${CERTIFICATE_ARN}" --default-actions "file://${ACTION_FILE}" >/dev/null
  fi
  for rule in logout:10 login:20; do
    name="${rule%%:*}"; priority="${rule##*:}"; file_var="${name^^}_FILE"; action_file="${!file_var}"
    rule_arn="$(aws elbv2 describe-rules --region "$REGION" --listener-arn "$HTTPS_LISTENER_ARN" --query "Rules[?Priority=='${priority}'].RuleArn | [0]" --output text)"
    condition="Field=path-pattern,Values=/${name}*"
    if [ "$rule_arn" = "None" ] || [ -z "$rule_arn" ]; then
      aws elbv2 create-rule --region "$REGION" --listener-arn "$HTTPS_LISTENER_ARN" --priority "$priority" --conditions "$condition" --actions "file://${action_file}" >/dev/null
    else
      aws elbv2 modify-rule --region "$REGION" --rule-arn "$rule_arn" --conditions "$condition" --actions "file://${action_file}" >/dev/null
    fi
  done
  ALB_DNS="$(aws elbv2 describe-load-balancers --region "$REGION" --load-balancer-arns "$ALB_ARN" --query 'LoadBalancers[0].DNSName' --output text)"
  ALB_ZONE="$(aws elbv2 describe-load-balancers --region "$REGION" --load-balancer-arns "$ALB_ARN" --query 'LoadBalancers[0].CanonicalHostedZoneId' --output text)"
  for record in "$APP_DOMAIN" "www.$APP_DOMAIN"; do
    CHANGE_FILE="$(mktemp)"
    printf '{"Changes":[{"Action":"UPSERT","ResourceRecordSet":{"Name":"%s.","Type":"A","AliasTarget":{"HostedZoneId":"%s","DNSName":"%s","EvaluateTargetHealth":false}}}]}' "$record" "$ALB_ZONE" "$ALB_DNS" > "$CHANGE_FILE"
    aws route53 change-resource-record-sets --hosted-zone-id "$ROUTE53_HOSTED_ZONE_ID" --change-batch "file://${CHANGE_FILE}" >/dev/null
    rm -f "$CHANGE_FILE"
  done
fi

echo
echo "Bootstrap complete. Attach instance profile '$PROFILE_NAME' to the replacement EC2 instance."
printf 'AWS_REGION=%s\nS3_BUCKET_NAME=%s\nDYNAMODB_TABLE_NAME=%s\n' "$REGION" "$BUCKET_NAME" "$TABLE_NAME"
