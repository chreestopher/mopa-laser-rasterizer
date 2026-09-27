#!/usr/bin/env python3
"""Preview and, only with several explicit gates, send a release announcement.

This utility is intentionally not invoked by either deployment workflow.  Its default
mode only renders the maintained announcement and never creates an AWS client.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Iterable, Iterator, NamedTuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANNOUNCEMENT = ROOT / "docs" / "releases" / "current-announcement.json"
UNSUBSCRIBE_URL = "{{amazonSESUnsubscribeUrl}}"
SEND_ENABLE_VALUE = "I_UNDERSTAND_THIS_SENDS_LIVE_EMAIL"
MAX_SES_RETRIES = 5
EMAIL_PATTERN = re.compile(r"^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$")
RETRYABLE_CODES = {
    "InternalServiceError",
    "ServiceUnavailableException",
    "Throttling",
    "ThrottlingException",
    "TooManyRequestsException",
}
FATAL_CODES = {
    "AccountSuspendedException",
    "BadRequestException",
    "MailFromDomainNotVerifiedException",
    "NotFoundException",
    "SendingPausedException",
}


class ReleaseEmailError(RuntimeError):
    """A validation or safe-operation failure."""


class RenderedAnnouncement(NamedTuple):
    campaign_id: str
    subject: str
    text: str
    html: str


def load_announcement(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required_strings = (
        "release_id", "status", "subject", "preheader", "heading", "intro",
        "cta_label", "cta_url", "product_url", "postal_address",
    )
    missing = [key for key in required_strings if not isinstance(data.get(key), str) or not data[key].strip()]
    if missing:
        raise ReleaseEmailError(f"announcement has missing/empty fields: {', '.join(missing)}")
    if data["status"] not in {"draft", "approved"}:
        raise ReleaseEmailError("announcement status must be 'draft' or 'approved'")
    if "\r" in data["subject"] or "\n" in data["subject"]:
        raise ReleaseEmailError("announcement subject must be a single line")
    if not isinstance(data.get("highlights"), list) or not data["highlights"]:
        raise ReleaseEmailError("announcement highlights must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in data["highlights"]):
        raise ReleaseEmailError("every announcement highlight must be non-empty text")
    for key in ("cta_url", "product_url"):
        if not data[key].startswith("https://"):
            raise ReleaseEmailError(f"{key} must use https")
    return data


def campaign_id_for(announcement: dict[str, Any]) -> str:
    canonical = json.dumps(announcement, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9-]+", "-", announcement["release_id"].lower()).strip("-")
    if not slug:
        raise ReleaseEmailError("release_id must contain a letter or number")
    return f"{slug}-{digest}"


def render_announcement(announcement: dict[str, Any]) -> RenderedAnnouncement:
    campaign_id = campaign_id_for(announcement)
    bullets_text = "\n".join(f"- {item}" for item in announcement["highlights"])
    text_body = (
        f"{announcement['heading']}\n\n{announcement['intro']}\n\n"
        f"What's new\n{bullets_text}\n\n"
        f"{announcement['cta_label']}: {announcement['cta_url']}\n\n"
        f"You are receiving this because you opted in to MOPA Laser Rasterizer release updates.\n"
        f"Unsubscribe or update preferences: {UNSUBSCRIBE_URL}\n\n"
        f"{announcement['postal_address']}\n{announcement['product_url']}"
    )
    bullet_html = "".join(f"<li>{html.escape(item)}</li>" for item in announcement["highlights"])
    html_body = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(announcement['subject'])}</title></head>
<body style="margin:0;background:#11150f;color:#e8eddf;font-family:Arial,sans-serif">
<div style="display:none;max-height:0;overflow:hidden">{html.escape(announcement['preheader'])}</div>
<main style="max-width:640px;margin:auto;padding:32px 20px">
<h1 style="color:#9bed7f">{html.escape(announcement['heading'])}</h1>
<p style="line-height:1.6">{html.escape(announcement['intro'])}</p>
<h2>What's new</h2><ul style="line-height:1.7">{bullet_html}</ul>
<p style="margin:30px 0"><a href="{html.escape(announcement['cta_url'], quote=True)}" style="background:#78c95e;color:#10140f;padding:13px 20px;text-decoration:none;font-weight:bold">{html.escape(announcement['cta_label'])}</a></p>
<hr style="border:0;border-top:1px solid #465142">
<p style="color:#b8bdaF;font-size:12px;line-height:1.5">You are receiving this because you opted in to MOPA Laser Rasterizer release updates.<br>
<a href="{UNSUBSCRIBE_URL}" style="color:#9bed7f">Unsubscribe or update preferences</a><br>
{html.escape(announcement['postal_address'])}<br>
<a href="{html.escape(announcement['product_url'], quote=True)}" style="color:#9bed7f">{html.escape(announcement['product_url'])}</a></p>
</main></body></html>"""
    if text_body.count(UNSUBSCRIBE_URL) != 1 or html_body.count(UNSUBSCRIBE_URL) != 1:
        raise ReleaseEmailError("rendered content must contain one unsubscribe placeholder per format")
    return RenderedAnnouncement(campaign_id, announcement["subject"], text_body, html_body)


def normalize_email(value: str) -> str | None:
    if not isinstance(value, str) or "\r" in value or "\n" in value:
        return None
    display, parsed = parseaddr(value.strip())
    if display or parsed != value.strip() or not EMAIL_PATTERN.fullmatch(parsed):
        return None
    local, domain = parsed.rsplit("@", 1)
    try:
        domain = domain.encode("idna").decode("ascii")
        normalized = f"{local.lower()}@{domain.lower()}"
        normalized.encode("ascii")
    except (UnicodeError, UnicodeEncodeError):
        return None
    return normalized if len(normalized) <= 254 else None


def _attributes(user: dict[str, Any]) -> dict[str, str]:
    return {item.get("Name", ""): item.get("Value", "") for item in user.get("Attributes", [])}


def cognito_member_emails(client: Any, user_pool_id: str) -> Iterator[str]:
    """Yield validated, confirmed, enabled, verified member emails across all pages."""
    token = None
    while True:
        request: dict[str, Any] = {"UserPoolId": user_pool_id, "Limit": 60}
        if token:
            request["PaginationToken"] = token
        response = client.list_users(**request)
        for user in response.get("Users", []):
            attrs = _attributes(user)
            email = normalize_email(attrs.get("email", ""))
            if (
                email
                and user.get("Enabled", True) is True
                and user.get("UserStatus") == "CONFIRMED"
                and attrs.get("email_verified", "").lower() == "true"
            ):
                yield email
        token = response.get("PaginationToken")
        if not token:
            return


def opted_in_contact_emails(client: Any, contact_list: str, topic: str) -> Iterator[str]:
    """Yield only explicit topic opt-ins; topic defaults never establish consent."""
    token = None
    while True:
        request: dict[str, Any] = {
            "ContactListName": contact_list,
            "Filter": {
                "FilteredStatus": "OPT_IN",
                "TopicFilter": {"TopicName": topic, "UseDefaultIfPreferenceUnavailable": False},
            },
            "PageSize": 100,
        }
        if token:
            request["NextToken"] = token
        response = client.list_contacts(**request)
        for contact in response.get("Contacts", []):
            preferences = {
                item.get("TopicName"): item.get("SubscriptionStatus")
                for item in contact.get("TopicPreferences", [])
            }
            email = normalize_email(contact.get("EmailAddress", ""))
            if email and not contact.get("UnsubscribeAll", False) and preferences.get(topic) == "OPT_IN":
                yield email
        token = response.get("NextToken")
        if not token:
            return


def select_recipients(
    cognito_emails: Iterable[str], opted_in_emails: Iterable[str], suppressed: Iterable[str] = (),
) -> list[str]:
    members = {email for value in cognito_emails if (email := normalize_email(value))}
    opted_in = {email for value in opted_in_emails if (email := normalize_email(value))}
    exclusions = {email for value in suppressed if (email := normalize_email(value))}
    return sorted((members & opted_in) - exclusions)


def load_suppressions(path: Path | None) -> list[str]:
    if path is None:
        return []
    values = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = raw.strip()
        if value and not value.startswith("#"):
            if not normalize_email(value):
                raise ReleaseEmailError(f"invalid address in suppression file at line {line_number}")
            values.append(value)
    return values


def recipient_key(email: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), email.encode("utf-8"), hashlib.sha256).hexdigest()


def append_audit(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, (json.dumps(event, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def audited_recipient_states(path: Path, campaign_id: str, key_id: str) -> dict[str, str]:
    states: dict[str, str] = {}
    if not path.exists():
        return states
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReleaseEmailError(f"invalid audit JSON at line {line_number}") from exc
        if event.get("campaign_id") != campaign_id:
            continue
        if event.get("key_id") != key_id:
            raise ReleaseEmailError("audit HMAC key does not match existing campaign ledger")
        if event.get("recipient_key"):
            states[event["recipient_key"]] = event.get("state", "unknown")
    return states


def _error_code(exc: Exception) -> str:
    response = getattr(exc, "response", {})
    return response.get("Error", {}).get("Code", exc.__class__.__name__)


def send_campaign(
    *, ses: Any, recipients: list[str], rendered: RenderedAnnouncement, source: str,
    contact_list: str, topic: str, configuration_set: str, audit_path: Path,
    audit_secret: str, messages_per_second: float = 5.0, batch_size: int = 25,
    sleep: Any = time.sleep,
) -> dict[str, int]:
    """Send one-recipient SES calls so managed one-click unsubscribe is applied."""
    key_id = hashlib.sha256(audit_secret.encode("utf-8")).hexdigest()[:16]
    lock_path = Path(f"{audit_path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ReleaseEmailError(f"campaign lock already exists: {lock_path}") from exc
    try:
        os.write(lock_descriptor, f"pid={os.getpid()} campaign={rendered.campaign_id}\n".encode("ascii"))
        os.fsync(lock_descriptor)
        prior = audited_recipient_states(audit_path, rendered.campaign_id, key_id)
        summary = {"sent": 0, "failed": 0, "skipped": 0}
        interval = 1.0 / messages_per_second
        for index, email in enumerate(recipients):
            key = recipient_key(email, audit_secret)
            # Any prior event means this address was already attempted. An ambiguous
            # attempted-only delivery is never automatically retried.
            if key in prior:
                summary["skipped"] += 1
                continue
            base = {
                "campaign_id": rendered.campaign_id, "key_id": key_id,
                "recipient_key": key, "ordinal": index + 1,
            }
            append_audit(audit_path, {**base, "state": "attempted"})
            for retry in range(MAX_SES_RETRIES + 1):
                try:
                    response = ses.send_email(
                        FromEmailAddress=source,
                        Destination={"ToAddresses": [email]},
                        Content={"Simple": {
                            "Subject": {"Data": rendered.subject, "Charset": "UTF-8"},
                            "Body": {
                                "Text": {"Data": rendered.text, "Charset": "UTF-8"},
                                "Html": {"Data": rendered.html, "Charset": "UTF-8"},
                            },
                        }},
                        ConfigurationSetName=configuration_set,
                        ListManagementOptions={"ContactListName": contact_list, "TopicName": topic},
                        EmailTags=[{"Name": "campaign", "Value": rendered.campaign_id[:256]}],
                    )
                    append_audit(audit_path, {**base, "state": "sent", "message_id": response.get("MessageId")})
                    summary["sent"] += 1
                    break
                except Exception as exc:  # boto exceptions vary; classify from AWS error response.
                    code = _error_code(exc)
                    retryable = code in RETRYABLE_CODES and retry < MAX_SES_RETRIES
                    append_audit(audit_path, {
                        **base, "state": "retrying" if retryable else "failed",
                        "error_code": code, "retry": retry,
                    })
                    if not retryable:
                        summary["failed"] += 1
                        if code in FATAL_CODES:
                            raise ReleaseEmailError(f"SES stopped the campaign with {code}") from exc
                        break
                    sleep(min(2 ** retry, 16))
            if index + 1 < len(recipients):
                sleep(interval)
            if batch_size > 0 and (index + 1) % batch_size == 0:
                sleep(max(interval, 1.0))
        return summary
    finally:
        os.close(lock_descriptor)
        lock_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--announcement", type=Path, default=DEFAULT_ANNOUNCEMENT)
    parser.add_argument("--preview-dir", type=Path, default=ROOT / "outputs" / "release-email-preview")
    parser.add_argument("--discover-recipients", action="store_true", help="read Cognito and SES; never sends")
    parser.add_argument("--send", action="store_true", help="enable gated live send (disabled by default)")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-2"))
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    parser.add_argument("--user-pool-id")
    parser.add_argument("--contact-list")
    parser.add_argument("--topic")
    parser.add_argument("--source-email")
    parser.add_argument("--configuration-set")
    parser.add_argument("--suppression-file", type=Path)
    parser.add_argument("--audit-log", type=Path)
    parser.add_argument("--expected-account-id")
    parser.add_argument("--confirm-campaign-id")
    parser.add_argument("--confirm-recipient-count", type=int)
    parser.add_argument("--messages-per-second", type=float, default=5.0)
    parser.add_argument("--batch-size", type=int, default=25)
    return parser


def _require_live_options(args: argparse.Namespace) -> None:
    required = ["user_pool_id", "contact_list", "topic", "expected_account_id"]
    if args.send:
        required.extend(("source_email", "configuration_set", "audit_log"))
    missing = [name.replace("_", "-") for name in required if not getattr(args, name)]
    if missing:
        raise ReleaseEmailError(f"live discovery/send requires: {', '.join(missing)}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    announcement = load_announcement(args.announcement)
    rendered = render_announcement(announcement)
    args.preview_dir.mkdir(parents=True, exist_ok=True)
    (args.preview_dir / "announcement.txt").write_text(rendered.text, encoding="utf-8")
    (args.preview_dir / "announcement.html").write_text(rendered.html, encoding="utf-8")
    print(f"Rendered campaign {rendered.campaign_id} ({announcement['status']}) to {args.preview_dir}")
    if not args.discover_recipients and not args.send:
        print("Preview only: no AWS clients were created and no recipient data was read.")
        return 0

    _require_live_options(args)
    if args.messages_per_second <= 0 or args.batch_size <= 0:
        raise ReleaseEmailError("messages-per-second and batch-size must be positive")
    if args.send:
        if announcement["status"] != "approved":
            raise ReleaseEmailError("sending requires announcement status 'approved'")
        if os.environ.get("RELEASE_EMAIL_SEND_ENABLED") != SEND_ENABLE_VALUE:
            raise ReleaseEmailError(f"set RELEASE_EMAIL_SEND_ENABLED={SEND_ENABLE_VALUE} for an approved send")
        if args.confirm_campaign_id != rendered.campaign_id:
            raise ReleaseEmailError("--confirm-campaign-id does not match rendered content")
        if normalize_email(args.source_email) != args.source_email.lower():
            raise ReleaseEmailError("--source-email must be a normalized email address")
        audit_secret = os.environ.get("RELEASE_EMAIL_AUDIT_HMAC_KEY", "")
        if len(audit_secret) < 32:
            raise ReleaseEmailError("RELEASE_EMAIL_AUDIT_HMAC_KEY must contain at least 32 characters")
    import boto3  # Lazy import preserves the no-AWS default and makes tests simple.

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    account_id = session.client("sts").get_caller_identity()["Account"]
    if not hmac.compare_digest(account_id, args.expected_account_id):
        raise ReleaseEmailError("active AWS account does not match --expected-account-id")
    cognito = session.client("cognito-idp")
    ses = session.client("sesv2")
    recipients = select_recipients(
        cognito_member_emails(cognito, args.user_pool_id),
        opted_in_contact_emails(ses, args.contact_list, args.topic),
        load_suppressions(args.suppression_file),
    )
    print(f"Eligible recipients: {len(recipients)} (intersection of confirmed members and explicit opt-ins)")
    if not args.send:
        print("Discovery only: no email was sent.")
        return 0

    if args.confirm_recipient_count != len(recipients):
        raise ReleaseEmailError("--confirm-recipient-count does not match the freshly discovered count")
    summary = send_campaign(
        ses=ses, recipients=recipients, rendered=rendered, source=args.source_email,
        contact_list=args.contact_list, topic=args.topic, configuration_set=args.configuration_set,
        audit_path=args.audit_log, audit_secret=audit_secret,
        messages_per_second=args.messages_per_second, batch_size=args.batch_size,
    )
    print(f"Send complete: {summary}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReleaseEmailError, OSError, json.JSONDecodeError) as exc:
        print(f"Release email stopped: {exc}", file=sys.stderr)
        raise SystemExit(2)
