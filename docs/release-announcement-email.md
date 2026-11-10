# Release announcement email

The maintained message is `docs/releases/current-announcement.json`. Preview it locally with:

```bash
python3 dev_setup/release_announcement_email.py
```

This writes HTML and plain text under `outputs/release-email-preview/` without creating AWS clients or sending email.

## Deployment and manual sending

Deployment packages the announcement and adds its admin button; it never sends email and does not require the draft to be approved. Changes to the announcement JSON alone do not trigger an application deployment. Preview edits locally, then explicitly deploy the web/API component when the desired content should appear in the admin page.

Sending is a separate authenticated admin action. The button requires approved content, `test_email_approved: true`, configured delivery settings, and live sending enabled. Staging defaults to live delivery disabled. Run `python3 dev_setup/validate_release_announcement.py` manually before approving a send to check release metadata and placeholders.

After a failed campaign, **Retry Failed Recipients** attempts currently eligible recipients with confirmed failures and any not previously attempted. Successful sends and uncertain in-flight attempts are skipped. Recipient claims are atomic, so concurrent workers cannot claim the same recipient. Refresh the admin page to see the completed result. Background-job recovery is outside this change.

Required production deployment settings are:

- `SERVERLESS_PRODUCTION_RELEASE_EMAIL_SOURCE`
- `SERVERLESS_PRODUCTION_RELEASE_EMAIL_CONTACT_LIST`
- `SERVERLESS_PRODUCTION_RELEASE_EMAIL_TOPIC`
- `SERVERLESS_PRODUCTION_RELEASE_EMAIL_CONFIGURATION_SET`

## Consent boundary

A Cognito account alone is not marketing consent. Recipients are the deduplicated intersection of enabled, confirmed Cognito users with verified email addresses and SES contacts explicitly opted into the configured release topic. Every live message uses SES list management and includes the managed unsubscribe URL. The admin UI shows counts and delivery state but never exposes the recipient list.

Before a live send, verify the source identity, contact-list consent provenance, physical postal address, privacy and legal requirements, SES production access and quotas, and bounce/complaint event publishing.

## Send one formatting test

The test path sends exactly one message, omits SES list management, prefixes the subject with `[TEST]`, and explains that the unsubscribe area is intentionally inactive. It requires an explicit environment sentinel:

```bash
export RELEASE_EMAIL_TEST_SEND_ENABLED=I_UNDERSTAND_THIS_SENDS_ONE_TEST_EMAIL
python3 dev_setup/release_announcement_email.py \
  --send-test-to YOUR_ADMIN_EMAIL \
  --profile APPROVED_PROFILE \
  --region us-east-2 \
  --expected-account-id EXPECTED_12_DIGIT_ACCOUNT \
  --user-pool-id REVIEWED_PRODUCTION_POOL_ID \
  --source-email VERIFIED_SOURCE
```

After the owner confirms the received HTML and plain-text formatting, set `test_email_approved` to `true`, replace any remaining placeholder, and set `status` to `approved` in a reviewed commit.

The older CLI bulk-send mode remains available for controlled recovery, but the normal release workflow uses the one-time admin action. It requires multiple independent confirmations, a durable HMAC audit ledger, and at-most-once recipient handling.
