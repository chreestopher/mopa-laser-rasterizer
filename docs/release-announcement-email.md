# Release announcement email (review-only)

The repository contains a deliberately un-deployed release-email utility at
`dev_setup/release_announcement_email.py`. It is not called by staging or production
deployment scripts or GitHub Actions. Running it with no flags only renders HTML and
plain text under the ignored `outputs/` directory; it does not initialize an AWS
session, enumerate people, or send email.

The maintained message source is `docs/releases/current-announcement.json`. The file
is committed as a draft with placeholder copy and a placeholder postal address.
Production sending is impossible while its `status` is `draft`.

## Consent boundary

A Cognito account is not evidence that someone consented to marketing email. The
eligible set is therefore the deduplicated intersection of:

1. enabled, `CONFIRMED` Cognito users with `email_verified=true`; and
2. SES contacts with an **explicit** `OPT_IN` preference for the configured release
   topic (`UseDefaultIfPreferenceUnavailable=false`).

SES list management is mandatory on every send. Both message formats contain the
`{{amazonSESUnsubscribeUrl}}` placeholder, and the tool makes one `SendEmail` call per
person because SES applies its managed one-click unsubscribe headers/footer only to a
single-recipient message. An optional local suppression file (one address per line)
is applied after the intersection. The SES account-level suppression list and normal
bounce/complaint controls remain additional delivery safeguards.

Before approval, legal/operations review must confirm the message classification,
recorded opt-in provenance, physical postal address, privacy notice, applicable
CAN-SPAM/CASL/GDPR obligations, sender identity, Easy DKIM, custom MAIL FROM alignment,
configuration-set bounce/complaint events, and SES production access/quotas. Account
signup alone must never be bulk-imported as an opt-in.

## Review flow (safe now)

Use the same Python environment as the project's other development helpers:

```bash
python3 dev_setup/release_announcement_email.py
python3 -m pytest tests/test_release_announcement_email.py
```

Open `outputs/release-email-preview/announcement.html` and compare it with
`announcement.txt`. Review the committed JSON changes. The campaign ID printed by the
preview is content-addressed: changing any maintained source field creates a new ID.

After an operator has separately provisioned and reviewed the SES contact list,
explicit-opt-in topic, verified source identity, and event-publishing configuration
set, a read-only recipient discovery can be performed:

```bash
python3 dev_setup/release_announcement_email.py \
  --discover-recipients \
  --profile APPROVED_PROFILE \
  --region us-east-2 \
  --expected-account-id EXPECTED_12_DIGIT_ACCOUNT \
  --user-pool-id REVIEWED_PRODUCTION_POOL_ID \
  --contact-list REVIEWED_CONTACT_LIST \
  --topic RELEASE_UPDATES \
  --source-email verified-sender@example.com \
  --configuration-set REVIEWED_EVENT_CONFIGURATION_SET \
  --audit-log /secure/operator/path/release-email-audit.jsonl
```

Discovery calls STS, Cognito `ListUsers`, and SES `ListContacts`; it does not call
`SendEmail`. It reports a count, never addresses. Review Cognito and SES pagination,
the count, exclusions, quotas, and the account ID before considering a send.

## Eventual invocation after a separate approval

This section documents a future manual operation; do not run it merely because the
code has merged. First replace all draft content and the postal-address placeholder,
complete staging/production acceptance, obtain legal and release approval, and change
`status` to `approved` in the same reviewed commit. Preview again and record the new
campaign ID and freshly discovered recipient count.

Use a stable, access-restricted audit path on durable operator storage. Set the HMAC
key from an approved secret manager or ephemeral shell input; do not commit it, print
it, or place it in command history. The key must remain stable for resumability.

```bash
export RELEASE_EMAIL_SEND_ENABLED=I_UNDERSTAND_THIS_SENDS_LIVE_EMAIL
export RELEASE_EMAIL_AUDIT_HMAC_KEY='obtain-at-least-32-characters-from-secret-storage'
python3 dev_setup/release_announcement_email.py \
  --send \
  --profile APPROVED_PROFILE \
  --region us-east-2 \
  --expected-account-id EXPECTED_12_DIGIT_ACCOUNT \
  --user-pool-id REVIEWED_PRODUCTION_POOL_ID \
  --contact-list REVIEWED_CONTACT_LIST \
  --topic RELEASE_UPDATES \
  --source-email verified-sender@example.com \
  --configuration-set REVIEWED_EVENT_CONFIGURATION_SET \
  --audit-log /secure/operator/path/release-email-audit.jsonl \
  --confirm-campaign-id ID_FROM_FINAL_PREVIEW \
  --confirm-recipient-count COUNT_FROM_FRESH_DISCOVERY
```

The gates are cumulative: `--send`, approved content, exact environment sentinel,
matching AWS account, exact content-derived campaign ID, exact freshly enumerated
count, SES list/topic, configuration set, and an audit HMAC key are all required. No
secret values belong in repository files.

The audit log stores HMAC recipient identifiers, states, non-sensitive AWS error
codes, and SES message IDs—not email addresses. An `attempted` record is flushed before
each API call. On restart, every previously attempted recipient is skipped. The ledger
also pins a fingerprint of the HMAC key and rejects a different key. This
chooses at-most-once behavior: if a process dies after SES accepts a message but before
the `sent` record, the ambiguous recipient is not automatically retried. Resolve such
entries against SES configuration-set delivery events under an incident/change record;
never delete or hand-edit the ledger to force a retry.

A per-ledger lock prevents concurrent operators from running the same audit path. A
hard process or host failure can leave the `.lock` file behind; verify no sender is
running and preserve the stale file with the change record before clearing it.

Transient throttling/service errors receive bounded exponential backoff. Sending is
paced (default 5 messages/second), with a longer pause after each logical group of 25.
Permanent per-recipient errors are recorded and processing continues, while systemic
account/configuration errors stop the campaign immediately. Tune
`--messages-per-second` only below the reviewed SES send rate. Stop if bounce or
complaint metrics breach the approved operational threshold.

## Least-privilege preparation (not provisioned here)

No IAM or SES resources are added by this change. A future reviewed operator role
needs only `sts:GetCallerIdentity`, `cognito-idp:ListUsers` on the exact production
pool, `ses:ListContacts` on the exact contact list, and `ses:SendEmail` constrained to
the verified identity/configuration set where IAM supports those conditions. It does
not need Cognito mutation, contact import/update, CloudFormation, or broad SES admin
permissions. Keep contact-list provisioning and consent import as a separately
reviewed process.
