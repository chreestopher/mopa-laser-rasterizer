#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$REPO_ROOT/.env.aws" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env.aws"
  set +a
fi

AWS_PROFILE="${AWS_PROFILE:-${DEPLOY_AWS_PROFILE:-mopa-admin}}"
MAIL_DOMAIN="${PROTON_MAIL_DOMAIN:-mopa-laser-rasterizer.com}"
HOSTED_ZONE_ID="${PROTON_MAIL_HOSTED_ZONE_ID:-}"
VERIFICATION="${PROTON_MAIL_VERIFICATION:-}"
DMARC_POLICY="${PROTON_MAIL_DMARC_POLICY:-none}"

aws_cli=(aws --profile "$AWS_PROFILE")

if [[ -z "$HOSTED_ZONE_ID" ]]; then
  HOSTED_ZONE_ID="$(${aws_cli[@]} route53 list-hosted-zones-by-name \
    --dns-name "$MAIL_DOMAIN" \
    --query "HostedZones[?Name=='${MAIL_DOMAIN}.']|[0].Id" \
    --output text)"
  HOSTED_ZONE_ID="${HOSTED_ZONE_ID##*/}"
fi

if [[ -z "$HOSTED_ZONE_ID" || "$HOSTED_ZONE_ID" == "None" ]]; then
  echo "No Route 53 hosted zone found for $MAIL_DOMAIN" >&2
  exit 1
fi

if [[ -z "$VERIFICATION" ]]; then
  echo "Set PROTON_MAIL_VERIFICATION to the protonmail-verification=... TXT value." >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

export PROTON_DNS_DOMAIN="$MAIL_DOMAIN"
export PROTON_DNS_ZONE_ID="$HOSTED_ZONE_ID"
export PROTON_DNS_VERIFICATION="$VERIFICATION"
export PROTON_DNS_DMARC_POLICY="$DMARC_POLICY"
export PROTON_DNS_PROFILE="$AWS_PROFILE"
export PROTON_DNS_CHANGE_FILE="$tmp_dir/change-batch.json"

python3 - <<'PY'
import json
import os
import subprocess

domain = os.environ["PROTON_DNS_DOMAIN"].rstrip(".")
zone_id = os.environ["PROTON_DNS_ZONE_ID"]
verification = os.environ["PROTON_DNS_VERIFICATION"]
profile = os.environ["PROTON_DNS_PROFILE"]
change_file = os.environ["PROTON_DNS_CHANGE_FILE"]
dmarc_policy = os.environ["PROTON_DNS_DMARC_POLICY"]

records = json.loads(subprocess.check_output([
    "aws", "--profile", profile, "route53", "list-resource-record-sets",
    "--hosted-zone-id", zone_id, "--output", "json",
], text=True))["ResourceRecordSets"]

apex_name = domain + "."
apex_txt = next((r for r in records if r["Name"] == apex_name and r["Type"] == "TXT"), None)
txt_values = [r["Value"] for r in (apex_txt or {}).get("ResourceRecords", [])]
quoted_verification = json.dumps(verification)
if quoted_verification not in txt_values:
    txt_values.append(quoted_verification)
quoted_spf = json.dumps("v=spf1 include:_spf.protonmail.ch ~all")
if quoted_spf not in txt_values:
    txt_values.append(quoted_spf)

changes = [
    {
        "Action": "UPSERT",
        "ResourceRecordSet": {
            "Name": apex_name,
            "Type": "TXT",
            "TTL": 300,
            "ResourceRecords": [{"Value": value} for value in txt_values],
        },
    },
    {
        "Action": "UPSERT",
        "ResourceRecordSet": {
            "Name": apex_name,
            "Type": "MX",
            "TTL": 300,
            "ResourceRecords": [
                {"Value": "10 mail.protonmail.ch."},
                {"Value": "20 mailsec.protonmail.ch."},
            ],
        },
    },
    {
        "Action": "UPSERT",
        "ResourceRecordSet": {
            "Name": "_dmarc." + apex_name,
            "Type": "TXT",
            "TTL": 300,
            "ResourceRecords": [{"Value": json.dumps(f"v=DMARC1; p={dmarc_policy}")}],
        },
    },
]

# Clean up the common Route 53 mistake where "@" was entered literally.
# Route 53 represents that label as \100 in its API response. Only remove it
# when it contains exactly this Proton verification value.
legacy_name = r"\100." + apex_name
legacy_txt = next((r for r in records if r["Name"] == legacy_name and r["Type"] == "TXT"), None)
if legacy_txt and legacy_txt.get("ResourceRecords") == [{"Value": quoted_verification}]:
    changes.append({"Action": "DELETE", "ResourceRecordSet": legacy_txt})

for selector in (1, 2, 3):
    target = os.environ.get(f"PROTON_MAIL_DKIM_{selector}", "").strip()
    if target:
        selector_name = "protonmail" if selector == 1 else f"protonmail{selector}"
        changes.append({
            "Action": "UPSERT",
            "ResourceRecordSet": {
                "Name": f"{selector_name}._domainkey.{apex_name}",
                "Type": "CNAME",
                "TTL": 300,
                "ResourceRecords": [{"Value": target.rstrip(".") + "."}],
            },
        })

with open(change_file, "w", encoding="utf-8") as handle:
    json.dump({"Comment": "Configure Proton Mail DNS", "Changes": changes}, handle)
PY

change_id="$(${aws_cli[@]} route53 change-resource-record-sets \
  --hosted-zone-id "$HOSTED_ZONE_ID" \
  --change-batch "file://$PROTON_DNS_CHANGE_FILE" \
  --query 'ChangeInfo.Id' --output text)"

${aws_cli[@]} route53 wait resource-record-sets-changed --id "$change_id"

echo "Proton Mail DNS reconciled for $MAIL_DOMAIN."
echo "Route 53 hosted zone: $HOSTED_ZONE_ID"
if [[ -z "${PROTON_MAIL_DKIM_1:-}" ]]; then
  echo "DKIM was not changed. Add Proton's three account-specific CNAME targets to .env.aws and rerun."
fi
