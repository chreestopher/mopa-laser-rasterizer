# Production sign-up email alert

This optional, production-only alert sends an email to the existing AWS budget-alert recipient when a user confirms a new account through Cognito managed login. It filters CloudTrail events by the production user-pool and app-client IDs. It does not modify the Cognito pool or run code in the sign-up path, so an alert failure cannot prevent a user from registering.

Deploy from a trusted workstation with the `mopa-admin` AWS SSO profile and an active session:

```bash
bash dev_setup/deploy_serverless_production_signup_alert.sh --apply
```

The script reads the recipient from the production cost-guard stack and the Cognito identifiers from the production web stack. It validates the template before deploying a separate CloudFormation stack. That stack creates a single-Region, write-management-events-only CloudTrail trail, a private S3 log bucket with 30-day expiration, an EventBridge rule, and an SNS topic. The account currently has no trail, so the rule alone would never receive events. The first copy of management events has no CloudTrail event-delivery charge, but S3 storage and requests still cost money. The recipient must confirm the new SNS subscription email before alerts will arrive. Ordinary application releases do not deploy this stack.

This is a best-effort operational alert, not a guaranteed audit log. AWS delivers Cognito service events to CloudTrail on a best-effort basis. Cognito masks identifying information in these hosted-signup events; the email contains a timestamp, CloudTrail event ID, and link to the admin directory rather than the new user's address. Confirm trail logging, the rule, and the SNS subscription with a controlled production sign-up after deployment. No production resources are created merely by merging the code to staging.
