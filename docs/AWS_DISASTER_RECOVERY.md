# Serverless disaster recovery

Last verified against the repository and production AWS checks: 2026-09-16. This is an operational runbook; an isolated data restore was tested, but a complete application cutover has not been demonstrated. The old EC2/K3s/ALB environment is retired; do not rebuild it as the normal recovery path.

## Recovery priorities

1. Preserve evidence and stop new job dispatch if ongoing writes could worsen data loss. The cost guard's environment-specific pause is a dispatch control, not a backup or a general maintenance lock.
2. Establish whether the incident is application code, authentication, infrastructure, or durable data. Do not overwrite a surviving table or bucket during diagnosis.
3. Recover durable production data first: DynamoDB account/palette/library metadata and corresponding private S3 objects. Seven-day job history and artifacts are intentionally ephemeral.
4. Restore the production worker, orchestration, API, and browser from the approved `main` revision, then test sign-in, vault assets, one job, and downloads before reopening dispatch.

No recovery-point objective (RPO) or recovery-time objective (RTO) has been demonstrated. Record both only after a successful restore exercise.

## Current topology and source of truth

The live site is `https://mopa-laser-rasterizer.com/` (`www` is also supported). In `us-east-2`, CloudFront serves a private S3 static site; API Gateway routes to Lambda; Cognito supplies browser sign-in; DynamoDB stores account, vault, and job state; S3 stores uploads and generated artifacts; SQS, EventBridge Pipes, Step Functions, and one-shot ECS Fargate workers process jobs. Worker logs are in CloudWatch. Route 53 and the CloudFront certificate are separate from the application release. There is no required production EC2 or K3s cluster.

| Component | Production identifier or stack | Recovery significance |
| --- | --- | --- |
| Durable/runtime DynamoDB | `mopa-laser-rasterizer-users` | Existing table, passed into the production foundation; **not** created by it. Job records use selective `expires_at` TTL; durable material and palette records must not. |
| Private artifact S3 | `mopa-laser-rasterizer-artifacts-401716294893` | Existing retained bucket, passed into the foundation. `jobs/` and job-tagged account artifacts expire after seven days; durable `users/<sub>/...` vault assets are not on that lifecycle. |
| Static site S3, SQS queue/DLQ | `mopa-rasterizer-serverless-production` | Foundation stack; static files are rebuilt from the approved repository revision. |
| Fargate worker and log group | `mopa-rasterizer-serverless-production-worker` | Worker task/image and `/ecs/mopa-rasterizer-serverless-production-worker` logs. |
| Pipe and state machine | `mopa-rasterizer-serverless-production-orchestration` | Production-only dispatch path. |
| API, CloudFront, Cognito app client | `mopa-rasterizer-serverless-production-web` | Browser/API release and login callback configuration. The production user pool itself is an existing resource, not something to replace during routine recovery. |
| Cost guard | `mopa-rasterizer-serverless-production-cost-guard` | Separate, workstation-admin-managed budget/dispatch controls; the ordinary GitHub production release does not reconcile it. |
| Durable-asset backup | `mopa-rasterizer-serverless-production-backups` | Separate versioned S3 bucket, daily copy function, EventBridge schedule, and failure alarm. Managed outside the normal application release. |

Staging has separate artifact storage, DynamoDB, SQS, worker/orchestration, web stack, and an invite-only Cognito pool (`mopa-rasterizer-serverless-staging-identity`). It is for acceptance testing, **not** an authoritative production backup. Its copied user data can be incomplete or stale. Keep staging and production dispatch, identity, and data resources isolated.

Infrastructure templates are under `ecs/`; release scripts are under `dev_setup/`. Use current CloudFormation outputs rather than remembered physical IDs during recovery. The [staging](github-actions-staging-deployment.md) and [production](github-actions-production-deployment.md) release guides describe deployment permissions and gates.

## Actual protection state as checked on 2026-09-16

| Resource | Observed protection | Gap |
| --- | --- | --- |
| Production DynamoDB | Encryption at rest and selective `expires_at` TTL enabled; about 598 KB reported table size. **35-day PITR enabled on 2026-09-16.** An isolated PITR restore returned 2,170 records, matching a live count at the test time; its temporary table was deleted. | The window starts when PITR was enabled; it cannot restore earlier data. A restored table had TTL **disabled**, so a real cutover must re-enable `expires_at` only after checking the data. No full application cutover drill yet. |
| Production artifact bucket | Private, encrypted, with seven-day job lifecycle; about 112 live objects / 186 MB at check time. | Source bucket versioning is **not enabled**. Recovery of durable assets depends on the separate backup copy, not source versions. |
| Separate durable S3 backup | Private SSE-S3 bucket `mopa-rasterizer-durable-backups-401716294893-us-east-2`, versioning enabled; 30-day expiry of noncurrent versions. First manual run copied 19 objects / 3,537,879 bytes; second run copied zero unchanged objects. A sample material-library object retrieved from the backup matched its source SHA-256. Daily schedule: 05:00 UTC. | Only `materials`, `holographic-recipes`, and `holographic-calibrations` are included. At most daily granularity; no full application restore drill yet. The failure alarm reached the existing operator-notification topic in a labeled test. |
| AWS Backup service | No AWS Backup plan, vault, or protected resource found in the account/region. | This implementation uses DynamoDB-native PITR and a scheduled scoped S3 copy, **not** AWS Backup. |
| Staging DynamoDB | Separate table with PITR and selective `expires_at` TTL enabled by its foundation template. | Not a substitute for production recovery. |
| GitHub/repository deployment source | Protected `staging` → `main` promotion and immutable release images. | Rebuilds code/infrastructure, **not** missing user data or necessarily external DNS/identity settings. |

The live S3 total is dominated by job data: `jobs/` and `users/jobs/` together were about 181 MB. Durable user assets under `users/materials/`, `users/holographic-recipes/`, and `users/holographic-calibrations/` were about 3.5 MB. `users/color-discovery/` held about 1.3 MB, but its DynamoDB grid records have a seven-day TTL; do not silently treat those grids as permanent. A small `migration-backups/` prefix existed, but it is not a scheduled, tested backup policy. These are snapshots of size, not a growth forecast.

Read-only verification commands (AWS SSO administrator profile; use the intended account and `us-east-2`):

```bash
aws sts get-caller-identity --profile mopa-admin
aws dynamodb describe-continuous-backups --table-name mopa-laser-rasterizer-users --region us-east-2 --profile mopa-admin
aws dynamodb describe-time-to-live --table-name mopa-laser-rasterizer-users --region us-east-2 --profile mopa-admin
aws dynamodb list-backups --table-name mopa-laser-rasterizer-users --region us-east-2 --profile mopa-admin
aws s3api get-bucket-versioning --bucket mopa-laser-rasterizer-artifacts-401716294893 --region us-east-2 --profile mopa-admin
aws s3api get-bucket-lifecycle-configuration --bucket mopa-laser-rasterizer-artifacts-401716294893 --region us-east-2 --profile mopa-admin
aws backup list-backup-plans --region us-east-2 --profile mopa-admin
aws cloudformation describe-stacks --stack-name mopa-rasterizer-serverless-production-backups --region us-east-2 --profile mopa-admin
aws s3api get-bucket-versioning --bucket mopa-rasterizer-durable-backups-401716294893-us-east-2 --region us-east-2 --profile mopa-admin
aws s3api list-object-versions --bucket mopa-rasterizer-durable-backups-401716294893-us-east-2 --region us-east-2 --profile mopa-admin
```

## Current low-cost protection and remaining work

1. Production DynamoDB now has **35-day PITR**. Its retention length does not change the PITR storage rate. Job-only items still use `expires_at`; durable material/palette items must not. A PITR restore creates a **new table**. Rehearse switching the application only after comparing ownership, records, TTL, and encryption.
2. The production backup stack copies changed objects under `users/<sub>/materials/`, `users/<sub>/holographic-recipes/`, and `users/<sub>/holographic-calibrations/` into its separate, versioned bucket every day. It compares the source ETag and modification time, and skips unchanged files. If a source asset disappears, the backup function creates a destination delete marker; the prior version remains recoverable for 30 days. It refuses an empty source listing or unusually large deletion wave. Restore an earlier version rather than assuming a deleted asset is visible as the current version. The function does not back up job files, account exports, or seven-day Color Discovery grids.
3. The stack's CloudWatch failure alarm targets the existing budget-alert operator SNS topic. Check the alarm and a **recent successful Lambda log entry** periodically: an error alarm does not detect a schedule that was disabled or never invoked. Re-run the function manually with `{"dry_run":true}` before changing its scope. The normal GitHub application release does not manage this separate stack; administrator SSO deployment is `bash dev_setup/deploy_serverless_production_backups.sh --apply`.
4. Keep the production bucket's existing seven-day job lifecycle. Do **not** turn on full-bucket AWS Backup with 30-day retention without reviewing it: AWS Backup for S3 requires versioning and can retain job artifacts and old versions beyond the intended seven-day lifecycle. It also prices small objects at a 128 KiB minimum.
5. The first isolated checks succeeded: the DynamoDB PITR table restored and a backup object was readable with matching bytes. Still required before claiming an RTO/RPO: test an end-to-end application cutover using **both** compatible data recovery points, verify owner `sub` and object references, login, import, and one job, and document rollback. Do not copy staging identities into production. Recheck backup coverage after every new durable storage prefix.

This is a same-account, same-region first step. A separate account or region would protect against a wider compromise/outage but adds copy, transfer, IAM, and operational cost; scope that separately after the basic restore has been demonstrated.

### Cost planning, not a bill forecast

The AWS Price List API for Ohio on 2026-09-16 showed DynamoDB PITR at **$0.20/GB-month**, DynamoDB on-demand backup at **$0.10/GB-month**, S3 Standard at **$0.023/GB-month** (first 50 TB), and AWS Backup warm S3 storage at **$0.05/GB-month**. DynamoDB restore was **$0.15/GB** and AWS Backup S3 restore **$0.02/GB**. These rates exclude requests, events, replication, data transfer, restore testing, and future price changes. Recheck the official [DynamoDB](https://aws.amazon.com/dynamodb/pricing/), [S3](https://aws.amazon.com/s3/pricing/), and [AWS Backup](https://aws.amazon.com/backup/pricing/) pricing before enabling protection.

At the observed sizes, PITR for a roughly 0.6 MB production table and one current copy of roughly 3.5 MB of durable S3 assets amount to **far below one cent per month in raw storage arithmetic**. The separate daily-copy design also incurs S3 LIST/GET/PUT requests, Lambda/EventBridge/CloudWatch usage, and retained changed versions. The one standard-resolution CloudWatch alarm may add roughly **$0.10/month** outside any applicable free tier ([CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)). Budget **roughly $0.10–$0.30/month at today's scale**, then verify in Cost Explorer after a full billing month. This assumes the present low object count, same Region, SSE-S3 encryption, incremental copies, and no large growth; it is not a price guarantee. PITR is charged by table size, so reducing its retention from 35 days does not reduce that line item.

For comparison, backing up the **entire** currently 186 MB artifact bucket in AWS Backup has a rough initial warm-storage baseline of about **$0.01/month**, before object-size minimums, requests/events, source-bucket version storage, and accumulating seven-day job churn. That baseline can become misleading as jobs grow. At 10 GB of protected data, warm backup storage alone is about **$0.50/month per retained 10 GB**; 40 GB of retained current/history data is about **$2/month**, before other charges. Do not include ephemeral jobs in a long-retention policy merely because the present bucket is small.

## Application recovery and validation

**Before changing anything:** identify the last known-good `main` commit and successful production GitHub Action; export the incident timeline, stack events, CloudWatch logs, and current resource identifiers. Check `aws sts get-caller-identity`. Keep production and staging stack names distinct. If durable data may be corrupted, stop writes/dispatch and select a recovery point before replaying jobs.

For a code regression, use the protected `staging` → `main` PR path and the `Deploy serverless production` workflow. A merge to `main` runs tests, builds/pushes an immutable production image, updates worker/orchestration and then API/static site sequentially, verifies production authentication, and checks the public endpoint. It **does not** reuse the exact staging image digest, and it does not reconcile foundational infrastructure, the cost guard, Route 53, or the Cognito pool. GitHub's production role is update-only.

For an administrator-led infrastructure repair, inspect CloudFormation events and the templates first. The production foundation points at the pre-existing table and artifact bucket; never delete/recreate them as a casual stack reset. Use AWS SSO and the appropriate `dev_setup/` script only for the affected stack. The local production application path requires a clean checkout of `main` at an explicitly supplied release commit. Do not run concurrent deploys or switch production DNS to staging to mask an outage.

After recovery, verify:

1. Root and `www` HTTPS, documentation/media, and API health load through the intended CloudFront distribution.
2. Production sign-in and logout work from the home page and a documentation page, returning to the original URL. Verify the Cognito callback origin remains `https://mopa-laser-rasterizer.com/`.
3. The same signed-in owner can see durable material libraries/palettes and preferences; another user cannot access them.
4. A small job moves from pending through Fargate to completed, writes expected SVG/optional `.lbrn2`, streams CloudWatch logs, and downloads through signed URLs.
5. SQS DLQ, state machine failures, CloudWatch errors, budget pause state, job TTL, S3 lifecycle, and newly configured backup alerts are healthy.

Restoring DynamoDB alone will leave S3 references broken if their objects are missing; restoring S3 alone will not restore account metadata. Reconcile both using **compatible recovery points**, checking references against objects, and validate on isolated resources before cutover. A daily S3 copy cannot promise the same precise recovery time as DynamoDB PITR. The service's seven-day job history is not a promise that expired job artifacts can be restored.

For a real DynamoDB recovery, restore PITR to a **new** table and examine records before directing the API to it. DynamoDB did not carry `expires_at` TTL enablement onto the isolated test restore, so confirm and re-enable that attribute on the recovered table only after checking which records should expire. For a durable S3 object, inspect the backup bucket's object versions: a deleted asset may have a current delete marker, with its last good data in a noncurrent version. Retrieve that version into an isolated location and compare it with the table record before any production write. Do not overwrite the production object or table as the first recovery step.

## External dependencies and records to retain securely

Keep the repository and protected-branch history; AWS account/root and SSO recovery access; Route 53 registrar/hosted-zone access; CloudFront ACM certificate ownership and DNS validation; production and staging Cognito pool/domain identifiers; and GitHub environment/OIDC role configuration. Store staging gate credentials and any mail/DNS administration secrets in a secure operator store, never in this runbook or Git. `dev_setup/ensure-proton-mail-dns.sh` can help reconcile documented mail DNS records when explicitly needed, but DNS changes are not part of a routine application redeploy.

If these identity, domain, or account-level resources are lost, restore them deliberately with an administrator; routine GitHub Actions lack permission to recreate them. Preserve existing user identifiers when possible, because account and S3 ownership keys are tied to Cognito `sub` values.
