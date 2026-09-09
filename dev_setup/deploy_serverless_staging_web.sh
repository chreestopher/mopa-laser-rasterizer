#!/usr/bin/env bash
# Deploy the authenticated Lambda API and private CloudFront staging frontend.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
FOUNDATION_STACK="${SERVERLESS_STAGING_FOUNDATION_STACK:-mopa-rasterizer-serverless-staging}"
WEB_STACK="${SERVERLESS_STAGING_WEB_STACK:-mopa-rasterizer-serverless-staging-web}"

for name in COGNITO_POOL_ID COGNITO_DOMAIN; do
  [ -n "${!name:-}" ] || { echo "$name is required." >&2; exit 2; }
done
ADMIN_EMAIL="${SERVERLESS_STAGING_ADMIN_EMAIL:-${IDENTITY_CENTER_ADMIN_EMAIL:-}}"
[ -n "$ADMIN_EMAIL" ] || { echo "SERVERLESS_STAGING_ADMIN_EMAIL or IDENTITY_CENTER_ADMIN_EMAIL is required." >&2; exit 2; }

output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

BUCKET="$(output "$FOUNDATION_STACK" ArtifactBucketName)"
TABLE="$(output "$FOUNDATION_STACK" RuntimeTableName)"
QUEUE_URL="$(output "$FOUNDATION_STACK" JobQueueUrl)"
QUEUE_ARN="$(output "$FOUNDATION_STACK" JobQueueArn)"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf -- "$BUILD_DIR"' EXIT
cp "$REPO_ROOT/serverless_api/handler.py" "$BUILD_DIR/handler.py"
python3 "$SCRIPT_DIR/build_serverless_depthmap.py" \
  "$REPO_ROOT/templates/depthmap_generator.html" "$BUILD_DIR/depthmap.html"
python3 "$SCRIPT_DIR/build_serverless_community.py" "$BUILD_DIR/community-set"
python3 "$SCRIPT_DIR/build_serverless_experimental.py" \
  "$REPO_ROOT/templates/experimental_laboratories.html" "$BUILD_DIR/experimental-laboratories"
BUILD_DIR="$BUILD_DIR" python3 -c 'import os,zipfile
root=os.environ["BUILD_DIR"]
with zipfile.ZipFile(os.path.join(root,"function.zip"),"w",zipfile.ZIP_DEFLATED) as archive:
    info=zipfile.ZipInfo("handler.py",(1980,1,1,0,0,0)); info.external_attr=0o644<<16
    archive.writestr(info,open(os.path.join(root,"handler.py"),"rb").read())'
CODE_DIGEST="$(sha256sum "$BUILD_DIR/function.zip" | cut -d' ' -f1)"
CODE_KEY="web-deploy/api-${CODE_DIGEST}.zip"
aws s3 cp "$BUILD_DIR/function.zip" "s3://$BUCKET/$CODE_KEY" --region "$REGION" --only-show-errors

DOMAIN_PARAMETERS=()
if [ -n "${SERVERLESS_STAGING_HOSTNAME:-}" ]; then
  CERTIFICATE_ARN="${SERVERLESS_STAGING_CERTIFICATE_ARN:-$(aws acm list-certificates --region us-east-1 \
    --certificate-statuses ISSUED --query "CertificateSummaryList[?DomainName=='${SERVERLESS_STAGING_HOSTNAME}'].CertificateArn | [0]" --output text)}"
  if [ -z "$CERTIFICATE_ARN" ] || [ "$CERTIFICATE_ARN" = "None" ]; then
    echo "No issued us-east-1 certificate exists for $SERVERLESS_STAGING_HOSTNAME." >&2
    echo "Run: bash dev_setup/ensure_serverless_staging_domain.sh" >&2
    exit 2
  fi
  DOMAIN_PARAMETERS+=("StagingHostname=$SERVERLESS_STAGING_HOSTNAME" "CloudFrontCertificateArn=$CERTIFICATE_ARN")
fi

aws cloudformation deploy --region "$REGION" --stack-name "$WEB_STACK" \
  --template-file "$REPO_ROOT/ecs/serverless-staging-web.yaml" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    "ArtifactBucketName=$BUCKET" "RuntimeTableName=$TABLE" \
    "QueueUrl=$QUEUE_URL" "QueueArn=$QUEUE_ARN" \
    "LambdaCodeBucket=$BUCKET" "LambdaCodeKey=$CODE_KEY" \
    "CognitoUserPoolId=$COGNITO_POOL_ID" "CognitoDomain=$COGNITO_DOMAIN" \
    "AdminEmail=$ADMIN_EMAIL" \
    "${DOMAIN_PARAMETERS[@]}" \
  --no-fail-on-empty-changeset

API_URL="$(output "$WEB_STACK" ApiUrl)"
WEB_URL="$(output "$WEB_STACK" PublicUrl)"
PUBLIC_BASE_URL="${SERVERLESS_STAGING_PUBLIC_URL:-$WEB_URL}"
python3 "$SCRIPT_DIR/build_serverless_docs.py" "$BUILD_DIR/docs" "$PUBLIC_BASE_URL"
python3 "$SCRIPT_DIR/build_serverless_seo.py" "$BUILD_DIR/seo" "$PUBLIC_BASE_URL"
CLIENT_ID="$(output "$WEB_STACK" CognitoClientId)"
DISTRIBUTION_ID="$(output "$WEB_STACK" DistributionId)"
bash "$SCRIPT_DIR/apply_cognito_managed_branding.sh" "$CLIENT_ID"
CALLBACK_URL="$WEB_URL"
API_URL="$API_URL" CALLBACK_URL="$CALLBACK_URL" CLIENT_ID="$CLIENT_ID" COGNITO_DOMAIN="$COGNITO_DOMAIN" \
python3 -c 'import json,os; print(json.dumps({
 "api_url":os.environ["API_URL"], "callback_url":os.environ["CALLBACK_URL"],
 "client_id":os.environ["CLIENT_ID"], "cognito_domain":os.environ["COGNITO_DOMAIN"]
},separators=(",",":")))' \
  > "$BUILD_DIR/config.json"
aws s3 cp "$BUILD_DIR/seo/index.html" "s3://$BUCKET/web/index.html" \
  --region "$REGION" --content-type text/html --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/holographic.html" "s3://$BUCKET/web/holographic.html" \
  --region "$REGION" --content-type text/html --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/holographic.js" "s3://$BUCKET/web/holographic.js" \
  --region "$REGION" --content-type application/javascript --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/color-lab.html" "s3://$BUCKET/web/color-lab.html" \
  --region "$REGION" --content-type text/html --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/color-lab.js" "s3://$BUCKET/web/color-lab.js" \
  --region "$REGION" --content-type application/javascript --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/staging-shell.css" "s3://$BUCKET/web/staging-shell.css" \
  --region "$REGION" --content-type text/css --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/static/machine_chrome.css" "s3://$BUCKET/web/machine_chrome.css" \
  --region "$REGION" --content-type text/css --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/staging-pages.css" "s3://$BUCKET/web/staging-pages.css" \
  --region "$REGION" --content-type text/css --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/staging-shell.js" "s3://$BUCKET/web/staging-shell.js" \
  --region "$REGION" --content-type application/javascript --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/blank-palette.js" "s3://$BUCKET/web/blank-palette.js" \
  --region "$REGION" --content-type application/javascript --cache-control no-cache --only-show-errors
aws s3 cp "$BUILD_DIR/depthmap.html" "s3://$BUCKET/web/depthmap.html" \
  --region "$REGION" --content-type text/html --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/static/depthmap_generator.js" "s3://$BUCKET/web/depthmap_generator.js" \
  --region "$REGION" --content-type application/javascript --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/static/depthmap_parallax.js" "s3://$BUCKET/web/depthmap_parallax.js" \
  --region "$REGION" --content-type application/javascript --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/static/depthmap_parallax_svg.js" "s3://$BUCKET/web/depthmap_parallax_svg.js" \
  --region "$REGION" --content-type application/javascript --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/depthmap_bootstrap.js" "s3://$BUCKET/web/depthmap_bootstrap.js" \
  --region "$REGION" --content-type application/javascript --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/history.html" "s3://$BUCKET/web/history.html" \
  --region "$REGION" --content-type text/html --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/history.js" "s3://$BUCKET/web/history.js" \
  --region "$REGION" --content-type application/javascript --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/admin.html" "s3://$BUCKET/web/admin.html" \
  --region "$REGION" --content-type text/html --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/admin.js" "s3://$BUCKET/web/admin.js" \
  --region "$REGION" --content-type application/javascript --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/admin.css" "s3://$BUCKET/web/admin.css" \
  --region "$REGION" --content-type text/css --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/vault.html" "s3://$BUCKET/web/vault.html" \
  --region "$REGION" --content-type text/html --cache-control no-cache --only-show-errors
aws s3 cp "$REPO_ROOT/serverless_web/vault.js" "s3://$BUCKET/web/vault.js" \
  --region "$REGION" --content-type application/javascript --cache-control no-cache --only-show-errors
aws s3 cp "$BUILD_DIR/community-set" "s3://$BUCKET/web/community-set" \
  --region "$REGION" --content-type text/html --cache-control no-cache --only-show-errors
aws s3 cp "$BUILD_DIR/experimental-laboratories" "s3://$BUCKET/web/experimental-laboratories" \
  --region "$REGION" --content-type text/html --cache-control no-cache --only-show-errors
for route in laser-engraving-tool color-laser-engraving-tool depthmap-relief-engraving-tool; do
  aws s3 cp "$BUILD_DIR/seo/$route" "s3://$BUCKET/web/$route" \
    --region "$REGION" --content-type text/html --cache-control no-cache --only-show-errors
done
aws s3 cp "$BUILD_DIR/seo/sitemap.xml" "s3://$BUCKET/web/sitemap.xml" \
  --region "$REGION" --content-type application/xml --cache-control no-cache --only-show-errors
aws s3 cp "$BUILD_DIR/seo/robots.txt" "s3://$BUCKET/web/robots.txt" \
  --region "$REGION" --content-type text/plain --cache-control no-cache --only-show-errors
aws s3 cp "$BUILD_DIR/docs/index.html" "s3://$BUCKET/web/docs" \
  --region "$REGION" --content-type text/html --cache-control no-cache --only-show-errors
aws s3 cp "$BUILD_DIR/docs/" "s3://$BUCKET/web/docs/" --recursive --exclude index.html \
  --region "$REGION" --content-type text/html --cache-control no-cache --only-show-errors
# Explicitly remove retired documentation routes. Recursive copy does not delete
# objects that are no longer present in the generated documentation catalog.
aws s3 rm "s3://$BUCKET/web/docs/glyph-mosaic-filter" \
  --region "$REGION" --only-show-errors
aws s3 cp "$REPO_ROOT/static/docs/" "s3://$BUCKET/web/static/docs/" --recursive \
  --region "$REGION" --cache-control no-cache --only-show-errors
aws s3 cp "$BUILD_DIR/config.json" "s3://$BUCKET/web/config.json" \
  --region "$REGION" --content-type application/json --cache-control no-store --only-show-errors
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION_ID" --paths '/*' >/dev/null

echo "Authenticated serverless staging web deployed: $WEB_URL"
echo "API: $API_URL"
echo "A Route 53 subdomain can be attached after an us-east-1 ACM certificate is issued."
