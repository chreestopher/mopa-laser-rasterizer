# AWS disaster-recovery runbook

This documents the production shape of MOPA Laser Rasterizer and the order to rebuild it. It deliberately contains no secrets. Keep the repository, Route 53/domain access, the Flask session secret, and Cognito client secret in a password manager or another secure store.

Production-specific, non-secret identifiers live in the ignored `.env.aws` on
the operator workstation. Restore it from the secured operator backup or copy
`.env.aws.example` and populate it before running any deployment helper. The
scripts load it automatically. Credentials, private keys, passwords, and
application secrets do not belong in this file.

## Production topology

| Area | Configuration |
| --- | --- |
| Region | `us-east-2` |
| Public domain | `mopa-laser-rasterizer.com` and `www.mopa-laser-rasterizer.com` |
| Compute | One Ubuntu EC2 K3s control-plane node runs two web pods, Redis, and K3s system pods; raster work runs in one-shot Fargate tasks |
| Private AWS access | S3 and DynamoDB Gateway VPC Endpoints are associated with every cluster-node subnet route table |
| App networking | NodePort `30080` to container port `8000` |
| Public edge | Internet-facing Application Load Balancer with ACM TLS termination |
| Artifacts | Private S3 bucket `mopa-laser-rasterizer-artifacts-<account-id>`; jobs expire after 7 days, saved Material Libraries persist |
| Account data | DynamoDB `mopa-laser-rasterizer-users`, on-demand; string keys `pk` and `sk` |
| Container images | Private ECR repository `mopa-laser-rasterizer` in `us-east-2`; immutable tags and scan-on-push; production and staging images are retained in separate lifecycle pools |
| Raster task queue | Encrypted standard SQS queue `mopa-laser-raster-jobs`; 7-day retention, 2-hour visibility, three receives before redrive |
| Failed raster tasks | Encrypted SQS DLQ `mopa-laser-raster-jobs-dlq`; 14-day retention and restricted to the raster task queue |
| Sign-in | Cognito Hosted UI, authenticated at the ALB |

The application runs entirely from an immutable image in ECR. `/tmp/uploads` is pod-local scratch space; job inputs and outputs move through S3. A deployment must build and push a new image even for source-only changes.

## Parallel serverless staging

The AWS-native job backend is deliberately deployed beside production. It
uses separate retained S3 and DynamoDB resources, a separate SQS queue/DLQ,
and separate ECS/Step Functions/EventBridge Pipe names. Production continues
to use `JOB_BACKEND=redis` until cutover; staging uses `JOB_BACKEND=aws`.

Create or reconcile the isolated staging data plane and worker:

```bash
bash dev_setup/deploy_serverless_staging.sh
```

Serverless staging defaults each Fargate job to 2 vCPU, 4 GiB of memory, and
two deterministic CPU workers. Raster color-layer geometry and Holographic
Palette color assignment can run concurrently, while results are restored to
their original layer and row order before export. Override staging independently
with `SERVERLESS_STAGING_FARGATE_CPU`, `SERVERLESS_STAGING_FARGATE_MEMORY`, and
`SERVERLESS_STAGING_WORKER_PROCESSES`. The normal cost-focused values are
`2048`, `4096`, and `2`; a 4-vCPU benchmark uses `4096`, `8192`, and `4`.
The production deployment defaults to one CPU worker until the staging
output-equivalence and performance checks are explicitly promoted.

Serverless staging also defaults `SERVERLESS_STAGING_SOURCE_BLACK_COMPONENTS`
to `true`. This enables the isolated source-derived Black experiment: actual
Black raster pixels are coalesced into deterministic, hole-free run rectangles,
their independent components are processed concurrently, and only intersecting
non-Black geometry is removed. The established synthetic Black canvas remains
the default in production. The experimental path validates that its Black
geometry has no positive-area overlap with any non-Black layer; a validation
or topology failure automatically falls back to the established canvas path
for that job.

To disable the experiment cleanly without reverting code or changing
production, set the following in `.env.aws` and redeploy staging:

```bash
SERVERLESS_STAGING_SOURCE_BLACK_COMPONENTS=false
bash dev_setup/deploy_serverless_staging.sh
```

Set it back to `true` and repeat the same idempotent deployment to resume the
experiment. Abstract-filter and transparent workflows that already have
special Black semantics continue to use their established paths even while
the staging flag is enabled.

For an application release that changes both worker code and the staging API
or browser, deploy the complete retained staging environment with:

```bash
bash dev_setup/deploy_serverless_staging_application.sh
```

This wrapper is idempotent. It builds and registers the staging worker first,
updates the SQS-to-Fargate orchestration to that task definition, then deploys
the Lambda API and static CloudFront site. Use it for staging acceptance tests
before promoting the same source revision to production.

The worker image tag is derived from the built Docker image ID. Repeating a
deployment with unchanged inputs reuses the existing immutable ECR image and
does not manufacture a timestamp-only release. The deploy output prints the
exact image URI. To roll the worker back, set that previously validated URI
explicitly and reconcile the staging stacks:

```bash
SERVERLESS_STAGING_IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/mopa-laser-rasterizer:serverless-staging-IMAGE_ID" \
  bash dev_setup/deploy_serverless_staging.sh
```

This changes only the staging worker task definition and orchestration. To roll
back the API and static frontend together, check out the previously validated
source revision in a separate worktree and run
`bash dev_setup/deploy_serverless_staging_web.sh` there. CloudFormation retains
the existing stack if template validation or change-set creation fails; never
use production DNS as the rollback mechanism.

Deployment idempotency and worker rollback were acceptance-tested on
2026-08-24. Two unchanged deploys selected the same content-addressed ECR tag;
the second reported no changes for the foundation, worker, and orchestration
stacks. Staging was then moved to previously validated task revision 5 and
restored to content-addressed task revision 8 without launching a job. The live
state machine was verified to reference revision 8 and its expected immutable
image after restoration.

Final post-rollback smoke validation passed on 2026-08-24 as task
`b66b5020-7073-4359-bca5-322ce843c728`. Revision 8 traversed DynamoDB, SQS,
Step Functions, and Fargate Spot, completed in approximately 46 seconds, and
wrote both SVG and LightBurn outputs to the staging bucket. This closes the
serverless staging functional-acceptance phase; deferred browser presentation
work can proceed without changing the validated backend contract.

The helper discovers the proven VPC/subnets from the production worker stack
when they are not duplicated in `.env.aws`. It does not modify production DNS.
Run the real DynamoDB-to-SQS-to-Fargate-to-S3 test with:

```bash
bash dev_setup/test_serverless_staging_job.sh
```

The test uploads the one artwork and Material Library under
`scratch/videos/Color-Guided-Material-Library-Backed`, creates a disposable
seven-day runtime record, sends a direct JSON task-ID message, follows status,
and fails unless durable output objects are present.

To seed staging with one real account for acceptance testing without changing
production, copy its newest jobs and all Swatch Palette Vault data with:

```bash
bash dev_setup/copy-user-data-to-serverless-staging.sh USERNAME 10
```

The copy is idempotent and owner-scoped. It resolves the Cognito `sub`, copies
the requested number of newest job history/owner records and their S3 artifact
prefixes, and copies every color or hatch Material Library, depth palette, and
Holographic Palette owned by that account. It also reconciles the anonymous
`LASER_COMMUNITY` partition into the isolated staging table so Community Set
searches use staging data rather than reading production at runtime. Each
Holographic Palette retains its referenced S3 object. The command refuses to run
when the source and destination table or bucket are the same and never deletes
or updates production data. Staging is a retained pre-production environment,
but it is not a backup authority; repeat this command when its explicitly
seeded acceptance-test data needs to be refreshed from production.

The staging web deployment statically renders the production documentation
catalog and publishes `/docs` plus each `/docs/<slug>` page and diagram. It also
publishes `/community-set` and provisions the JWT-protected
`GET /community-set/settings` API route. Re-run the normal web deployment after
documentation, shared navigation, or Community Set presentation changes:

```bash
bash dev_setup/deploy_serverless_staging_web.sh
```

The staging bucket mirrors production retention: objects below `jobs/` and
objects tagged `mopa-retention=job` expire after seven days, while saved
Material Libraries and Holographic Palettes remain durable. Incomplete
multipart uploads are aborted after one day.

Keep the staging stacks and `serverless-staging` DNS name available after the
production migration. Normal releases should deploy and pass authenticated
browser, worker, retry, and download smoke tests in staging before the same
immutable application revision is promoted to production. Never make staging
share production queues or runtime tables, and never route production DNS to
staging as part of an ordinary test deployment.

Deferred staging UX work after functional acceptance testing: replace the
indeterminate submit state with visible artwork and Material Library upload
progress, clearly label the transition from upload to job submission, and make
the task-status view visible as soon as a task ID has been allocated. This is a
presentation improvement only; complete functional validation before adding it.
Also compare every staging swatch name and hexadecimal color against the
production palette source of truth, correct any discrepancies, and visually
verify the rendered swatches on both pages before production cutover.
When the user selects a saved Hatch Palette as the raster Material Library,
replace the ordinary color-only selector presentation with that library's hatch
swatches and pattern previews. Preserve each selected hatch entry's identity in
the submitted settings so the worker receives the same selections the browser
displayed.

The shared Cognito prefix domain uses managed login version 2 on the user pool's
Essentials tier. Production and serverless staging have separate app-client
branding records, but both receive the same reproducible machine-facade theme
from `ecs/cognito-managed-login-settings.json`. Every
`deploy_serverless_staging_web.sh` reconciliation reapplies both records
idempotently with:

```bash
bash dev_setup/apply_cognito_managed_branding.sh "$SERVERLESS_STAGING_COGNITO_CLIENT_ID"
```

The script preserves each app client's OAuth, callback, and secret settings; it
only reconciles the shared domain's login version and the two visual-branding
records. The previous classic CSS remains in
`ecs/cognito-staging-classic.css` for rollback. To restore classic login without
deleting either app client, run:

```bash
source dev_setup/load-aws-env.sh
COGNITO_DOMAIN_PREFIX="${COGNITO_DOMAIN%%.*}"
aws cognito-idp update-user-pool-domain \
  --profile "$DEPLOY_AWS_PROFILE" \
  --region "$AWS_REGION" \
  --user-pool-id "$COGNITO_POOL_ID" \
  --domain "$COGNITO_DOMAIN_PREFIX" \
  --managed-login-version 1
```

The staging retry path was acceptance-tested on 2026-08-24 with an isolated,
nonexistent task ID. The deployed workflow traversed `RunSpotWorker` twice,
then `RunOnDemandWorker`, `SendToDlq`, and `JobFailed`. The exact synthetic task
ID was observed in the staging DLQ and removed afterward. This confirms the
two-Spot-attempt/on-demand-fallback/dead-letter sequence without touching a
production queue or job.

Account isolation was acceptance-tested on 2026-08-24 without creating a
second real user. A direct staging Lambda invocation using the real job owner
could read a completed job, while the same request with a synthetic different
Cognito `sub` returned `404`. The synthetic identity's account-resource lists
contained no saved libraries, palettes, holographic swatches, or jobs. An HTTP request to
the public API without a JWT returned `401`. These checks validate both the API
Gateway authentication boundary and the Lambda/DynamoDB ownership boundary.

Upload security was acceptance-tested on 2026-08-24. The staging API rejected
an artwork key from a different task with `400`, rejected an expired upload
capability with `403`, and returned `404` when a synthetic second Cognito
identity referenced the real owner's saved Material Library. Presigned S3 POST
policies enforce a 100 MiB artwork limit and 10 MiB Material Library limit, and
submission performs a second size and capability-metadata check. Upload grants
and their submit capabilities share the same ten-minute expiration; a
successful conditional submission removes the capability to prevent reuse.

Duplicate submission was acceptance-tested on 2026-08-24 by racing two
conditional claims against one isolated synthetic staging task. Exactly one
claim succeeded and the other received `ConditionalCheckFailed`; the test
record was removed afterward. Both raster and holographic submit handlers map
that losing claim to HTTP `409`, so only the winning request can proceed to
SQS. If SQS submission itself fails, the handler restores the still-unexpired
capability so the browser can safely retry.

A subdomain such as `serverless-staging.mopa-laser-rasterizer.com` is the
intended browser endpoint. Do not create or switch its Route 53 alias until
the API/static frontend stack exists and its Cognito callback URL, presigned
large-file upload flow, ownership checks, and rollback tests pass. API Gateway
and Lambda cannot safely lift-and-shift the existing large multipart `/upload`
request because of their request payload limits; browser uploads must go to S3
using short-lived presigned URLs first.

Deploy the authenticated staging API and browser UI after the worker smoke
test passes:

```bash
bash dev_setup/deploy_serverless_staging_web.sh
```

This creates a separate Cognito app client in the existing user pool, a JWT-
protected HTTP API, an ARM Lambda function, and a private CloudFront/S3 static
site. It never changes the production Cognito client. Presigned POST policies
expire after ten minutes, bind each input to its task-specific key and upload
capability, and enforce 100 MiB artwork and 10 MiB Material Library limits.
Downloads use private presigned GET URLs that expire after fifteen minutes.

The static browser bundle includes production's shared `machine_chrome.css`
alongside `staging-shell.css`, `staging-pages.css`, and `staging-shell.js`,
which provide the shared staging machine header and navigation across the
Rasterizer, Holographic Lab, Depthmap Lab, the staged Color Lab port, Job
History, and Swatch Palette Vault.
`deploy_serverless_staging_web.sh` uploads these assets and invalidates
CloudFront on every reconciliation. The Depthmap build helper injects the same
versioned assets into its generated page, while Vault loads the shell from its
existing JavaScript module. This keeps disaster recovery idempotent and avoids
a separate frontend framework or build toolchain. The shared shell stylesheet is
the single owner of the metal page enclosure, header geometry, and navigation
on every staging route; page styles may format tool content but must not define
a second facade or route-specific shell dimensions. The staging markup uses
the production machine-chrome class contract directly, and its Dark/Light
switch persists the same `mopa-machine-theme` preference across every tool.
It also owns the Depthmap-style page hero (eyebrow, Impact title, description,
and environment badge) for all serverless routes so title typography and
colors cannot diverge in individual page templates.

The serverless Color Lab is stored in `serverless_web/color-lab.html` and
`serverless_web/color-lab.js`. Its authenticated API supports durable grid
creation, 29-cell LightBurn grids, stored short grid IDs, photograph alignment,
optional white-background correction, measured-swatch review, repeatable
refinement grids with editable bounds, and saving qualified swatches as Color
Palettes. The same idempotent web deployment publishes the page and points the
staging Experimental Laboratories card to `/color-lab.html`; production remains
unchanged until the serverless site is explicitly promoted.

The authenticated staging API also exposes `GET /account/resources`. It
returns only records under the caller's Cognito `USER#<sub>` partition:
recent live jobs, color and hatch Material Libraries, depth palettes, and
Holographic Palettes. A raster submission may reference a saved Material
Library instead of uploading it again. The API resolves the library ID from
that owner partition, verifies its S3 key remains below the same user's
`materials/` prefix, and rejects arbitrary or cross-account object keys.
The same selector offers an explicit SVG-Only option. In that mode the upload
grant contains only an artwork target, the API rejects Material Library and
Holographic Palette keys, the retained input list contains only the artwork,
and the existing worker skips its Material Library download and `.lbrn2`
export. The mode is bound to the upload record so it cannot be changed between
upload authorization and job submission.
Rasterizer submissions may also select a self-contained schema-v2 Holographic
Palette. Lambda reconstructs a temporary `.clb` below the task's private
`jobs/<task-id>/inputs/` prefix from the palette's embedded LightBurn settings,
then records the selected palette and routes the completed submission through
the holographic artwork worker path. The worker uses the palette's measured
swatch colors, intervals, angles, optional Black setting, cut-mode selection,
and Preserve Black Outlines choice. This does not modify the saved palette and
does not require its original calibration library. Legacy schema-v1 palettes
are excluded from the Rasterizer selector.

New serverless jobs write the same durable user-history and direct-owner records
used by the existing application so the worker can update them on completion.

The staging browser preserves production's separate-tool structure:
`/` publishes the Rasterizer and `/holographic.html` publishes the
Holographic Etching Lab. Each has a dedicated static form and browser module;
the staging deployment publishes both explicitly. Cognito returns to the
registered root callback and then restores the originating tool route.

The staging raster form renders the canonical 30 raster swatches, supports
including/excluding each swatch, and submits both canonical names and hexes.
Saved library summaries expose the owner-authenticated LightBurn settings
needed by the Swatch Palette Vault inline editors, plus color chips or hatch-angle
patterns. Raw library objects remain private in S3 and are never returned by
the account-resource response.
The browser stores Cognito tokens only in per-tab `sessionStorage`. It uses the
OAuth refresh token to replace an expired ID token and retries one unauthorized
API request; if refresh is unavailable or rejected, it clears the stale session
and returns to the sign-in state instead of presenting an authorization error
as a configuration failure.
The staging Holographic Lab implements the calibration and palette-building
portion of the calibration-first loop.
`POST /holographic/calibrations` resolves an exact setting from an owned
Material Library and creates durable `.lbrn2`, SVG, and JSON grid artifacts
below `users/<sub>/holographic-calibrations/<calibration-id>/`. The Lambda role
is intentionally limited to that owner-namespaced prefix. After engraving,
the operator loads the grid photograph into a browser Canvas and aligns its
four corners. Cell colors are sampled locally; the source photograph is never
uploaded. `POST /account/holographic-recipes/measured` validates submitted
cell indices against the caller's durable calibration metadata and stores the
resulting Holographic Palette below the caller's legacy internal
`holographic-recipes/` prefix with a matching DynamoDB `HOLORECIPE` index
record. The final lab card links to Rasterizer with the newly saved palette
preselected. Artwork uploads directly to private S3 from Rasterizer, and the
API submits the holographic artwork job through the existing SQS-to-Fargate
orchestration. Worker status and logs use the DynamoDB runtime and do not
require Redis.
Newly measured Holographic Palettes use schema version 2. Each approved
calibration cell contains a snapshot of its effective LightBurn cut setting
after interval, angle, cut-mode, and sweep overrides are applied. When the
selected material contains an entry explicitly named `Black`, that cut setting
is also embedded as the palette's optional `black_setting`. These palettes are
therefore self-contained snapshots; legacy schema-version-1 data remains valid
and continues to depend on its original Material Library until migrated.
The staging Swatch Palette Vault lazy-loads a palette's private JSON through
the compatibility route `GET /account/holographic-recipes/<recipe-id>` only
when its card is opened.
Version-2 measured swatches can be edited as accordion rows and are persisted
together with the profile name through `PUT` on the same owner-checked route.
The update operation validates observed colors, interval, angle, unique names,
and every embedded LightBurn setting before replacing the durable S3 object.
Version-2 holographic swatches also participate in the Swatch Palette Vault's shared
Selected Actions workflow. The API resolves selections by owner and holographic
swatch index, reconstructs LightBurn Material Library entries from the embedded
CutSettings, and assigns each entry to the nearest official LightBurn layer
color based on its observed swatch. Holographic swatch selections support `.clb` export,
copying into new or existing owned libraries, and labeled LightBurn coupon
generation subject to the shared 29-setting coupon limit.
Depth palettes remain listed while the specialized, entirely browser-side
Depthmap/Relief editor is deployed as `/depthmap.html`. The staging deployment
renders that static page reproducibly from the production template, publishes
the shared browser module, and adds a Cognito-token bootstrap that loads only
the signed-in owner's palettes through `GET /account/resources`. Source images,
depth inference, color guidance, painting, previews, and 8-bit or 16-bit PNG
exports remain local to the browser and do not create a Fargate task or upload
the user's image. The raster and holographic Fargate paths do not consume Depth
Palettes.

The staging site also publishes `/history.html`. `GET /account/jobs` queries
only the authenticated owner's ordered DynamoDB history partition, while
`GET /account/jobs/{task_id}` verifies the direct owner record before returning
parameters, retained DynamoDB logs, and fresh fifteen-minute S3 download URLs.
This history remains usable after the short-lived runtime record disappears;
downloads naturally become unavailable when the staging bucket's seven-day job
lifecycle removes their objects.

`/vault.html` provides the first serverless Swatch Palette Vault management boundary:
Depth Palettes can be created, edited, and deleted; existing Material Libraries
can be renamed or reclassified as color/hatch palettes; and existing Material
Libraries or Holographic Palettes can be deleted. Each mutation resolves a key
below `USER#<sub>`, and object deletion additionally verifies the expected
owner-specific S3 prefix. API IAM includes only object/item deletion needed for
these explicit actions. New `.clb`, `.lbmat`, `.lbrn`, and Holographic Palette
JSON imports use a two-phase flow: the API creates a short-lived owner-bound
import record and presigned S3 POST, then a finalize request verifies capability
metadata, size, extension, and contents before copying the object into its
durable owner prefix and creating the Vault index. Material Library XML must
contain 1-500 settings with non-empty unique descriptions; Holographic Palette
JSON must be a calibration profile with at least one saved holographic swatch. Temporary objects and
import records are removed after finalization, including validation failures.
Unfinalized objects use the isolated `imports/` prefix and expire automatically
after one day, so an abandoned browser upload cannot become permanent storage.
Material setting rows can also be selected across libraries. The authenticated
`POST /account/material-libraries/selected-settings` route reconstructs every
selection from the caller's durable S3 objects rather than trusting settings
sent by the browser. It supports the four production Swatch Palette Vault actions:
download a composed `.clb`, download a labeled `.lbrn2` test coupon (1-29
settings), copy into an existing owned library, or create a new owned library.
Copy operations update both the S3 XML and DynamoDB summary; duplicate swatch
descriptions are rejected before an existing library is changed. The route and
its API Gateway JWT authorization are declared in
`ecs/serverless-staging-web.yaml`, so the normal idempotent staging deployment
and DR restoration recreate the feature.
The staging HTTP API CORS policy explicitly permits `DELETE`, `GET`, `OPTIONS`,
`PATCH`, `POST`, and `PUT`; adding a mutation route without its method in this
list causes browsers to reject the preflight before Lambda is invoked.

The CloudFront hostname works immediately. A friendly Route 53 alias requires
an ACM certificate issued in `us-east-1` (CloudFront's required certificate
region); create that as a separate final staging-domain step after the default
CloudFront URL passes the complete signed-in browser test.

## 1. Restore account-level resources

Open AWS CloudShell in Ohio, copy in [aws_bootstrap_cloudshell.sh](../dev_setup/aws_bootstrap_cloudshell.sh), then run:

```bash
chmod +x aws_bootstrap_cloudshell.sh
./aws_bootstrap_cloudshell.sh
```

The script safely repeats and configures:

- A private, AES-256 encrypted S3 bucket.
- Seven-day lifecycle rules for guest and signed-in job artifacts, including incomplete-multipart abort after one day.
- DynamoDB in `PAY_PER_REQUEST` mode, primary key `pk` plus sort key `sk`.
- A private, AES-256 encrypted ECR repository with immutable tags and scan-on-push. Separate lifecycle pools retain the newest 20 `deploy-*` production images, 10 `spinner-*` production images, and 20 `serverless-staging-*` images, so staging deployments cannot expire a production image. Untagged images expire after seven days.
- SQS standard queues `mopa-laser-raster-jobs` and
  `mopa-laser-raster-jobs-dlq`, encrypted with SQS-managed keys. The source
  queue uses long polling, a two-hour visibility timeout, seven-day retention,
  and retains its native redrive policy as a transport-level fallback.
- IAM role and instance profile `mopa-laser-rasterizer-ec2`.
- Least-privilege S3, DynamoDB, ECR-pull, and SQS producer access used by the
  app and K3s nodes. Queue consumers require a separate launcher role with
  receive/delete/change-visibility access; the web role intentionally does not
  receive or delete messages.

To create or reconcile only the queues without touching the other account
resources, run `dev_setup/ensure-sqs-raster-queues.sh` instead.

Saved Material Libraries are deliberately outside the lifecycle filters, so they persist until explicitly deleted. Signed-in job uploads are tagged `mopa-retention=job`; guest job files remain under the `jobs/` prefix.

Both production image deployment and `deploy_serverless_staging.sh` reconcile
the shared ECR lifecycle policy before publishing an image. Do not replace it
with a repository-wide `tagStatus: any` count rule: that combines staging and
production into one eviction pool and can remove an immutable image that an
active production task definition still references.

The final bootstrap output includes `SQS_QUEUE_NAME`, `SQS_QUEUE_URL`,
`SQS_QUEUE_ARN`, `SQS_DLQ_NAME`, `SQS_DLQ_URL`, and `SQS_DLQ_ARN`. Record these
non-secret identifiers with the recovered environment configuration. Override
the default names with `SQS_QUEUE_NAME` and `SQS_DLQ_NAME`; override the retry
threshold with `SQS_MAX_RECEIVE_COUNT` before running the bootstrap.

Verify the restored redrive relationship:

```bash
aws sqs get-queue-attributes --region us-east-2 \
  --queue-url "$SQS_QUEUE_URL" \
  --attribute-names QueueArn RedrivePolicy VisibilityTimeout MessageRetentionPeriod SqsManagedSseEnabled
aws sqs get-queue-attributes --region us-east-2 \
  --queue-url "$SQS_DLQ_URL" \
  --attribute-names QueueArn RedriveAllowPolicy MessageRetentionPeriod SqsManagedSseEnabled
```

### Restore administrative human access

Use an organization instance of IAM Identity Center for human administration;
reserve the root user for root-only recovery tasks. Organization-instance
activation is completed once in the AWS console because AWS does not expose
that operation through the public `CreateInstance` API:

1. Open IAM Identity Center in `us-east-2` from the Organization management
   account.
2. Enable with AWS Organizations, permission sets enabled, AWS-owned
   encryption, and `us-east-2` as the primary Region.
3. Reconcile the administrator identity and assignment:

```bash
bash dev_setup/configure-identity-center-admin.sh \
  "$IDENTITY_CENTER_ADMIN_EMAIL" "$IDENTITY_CENTER_ADMIN_USERNAME"
```

The script is idempotent. It enables Organizations trusted access for Identity
Center, discovers the instance and identity store, creates or reuses the user,
`Admin team` group, and four-hour `AdministratorAccess` permission set, ensures
group membership, attaches AWS's managed `AdministratorAccess` policy, and
waits for the management-account assignment to complete. Override the profile
name fields with `IDENTITY_CENTER_ADMIN_GIVEN_NAME` and
`IDENTITY_CENTER_ADMIN_FAMILY_NAME` when restoring a different administrator.

Identity Center authentication policy is configured in the console. Under
**Settings → Authentication → Multi-factor authentication → Configure**, keep
MFA enabled, enable authenticator apps and/or security keys, and set **If a
user does not yet have a registered MFA device** to **Require them to register
an MFA device at sign in**. Do not select **Block their sign-in** for a newly
restored directory because API/CLI-created users begin without an MFA device.
Under standard authentication, enable **Send email OTP** so users created by
the API/CLI can establish their initial password through their verified email.

Do not delete root credentials until the administrator has signed in through
the AWS access portal, configured an AWS CLI SSO profile, and successfully run
`aws sts get-caller-identity` through that profile.

Configure the workstation profile once and authenticate it when each SSO
session begins or expires:

```bash
aws configure sso --profile mopa-admin
aws sso login --profile mopa-admin --use-device-code
aws sts get-caller-identity --profile mopa-admin
export AWS_PROFILE=mopa-admin
```

Routine deployment helpers explicitly select `mopa-admin`, even when the
surrounding shell has another `AWS_PROFILE`. Set `DEPLOY_AWS_PROFILE` only when
another deployment identity is intentional. `aws login` is reserved for
IAM/root sign-in workflows and is not the Identity Center deployment command.

## 2. Rebuild EC2 and K3s

Create a small Ubuntu instance in the target VPC and attach the `mopa-laser-rasterizer-ec2` instance profile. Create or use two security groups:

| Security group | Inbound rule |
| --- | --- |
| ALB | Public TCP `80` and `443` |
| EC2 | TCP `30080` from the ALB security group only; SSH `22` from your fixed IP only |

Do not expose NodePort `30080` to the internet.

Before scheduling application pods on a private node, give its route table
private access to S3. From WSL, with the AWS CLI authenticated, run:

```bash
bash dev_setup/ensure-ec2-aws-gateway-endpoints.sh <ec2-instance-id>
```

The script creates or reuses the regional S3 and DynamoDB Gateway VPC
Endpoints and associates the instance subnet's effective route table. These
Gateway endpoints do not require a NAT gateway or public IPv4 address. The
instance profile must still contain the S3 and DynamoDB permissions created in
section 1.

On the EC2 host:

```bash
curl -sfL https://get.k3s.io | sh -
sudo systemctl enable --now k3s
cd /home/ubuntu
git clone "$GITHUB_REPOSITORY_URL"
cd mopa-laser-rasterizer
```

Generate the new session secret and deploy the workload:

```bash
SESSION_SECRET="$(openssl rand -hex 32)"
sudo kubectl create secret generic mopa-rasterizer-session \
  --from-literal=secret="$SESSION_SECRET" -n default
sudo kubectl apply -f k8s/redis.statefulset.yaml
sudo kubectl apply -f k8s/redis.service.yml
sudo kubectl apply -f k8s/redis.fargate-service.yml
sudo kubectl apply -f k8s/service.aws.yaml
bash dev_setup/start-k3s-tunnel.sh
bash dev_setup/deploy_production.sh
```

`redis.fargate-service.yml` exposes Redis on NodePort `30379` for the one-shot
Fargate workers. Do not add a public CIDR ingress rule for this port. The
Fargate stack creates a worker security group and permits only that group on
the K3s node security group. The Fargate deployment uses a K3s node private IP
as `REDIS_HOST` and `30379` as `REDIS_PORT`.

Deploy or reconcile the Fargate task after the K3s control plane exists:

```bash
aws sso login --profile mopa-admin --use-device-code
K3S_INSTANCE_ID=<replacement-control-plane-id> \
  bash dev_setup/deploy_fargate_worker_production.sh
```

The wrapper discovers non-secret VPC settings from that instance. The verified
2026-08-24 deployment created CloudFormation stacks `mopa-rasterizer-worker`
and `mopa-rasterizer-orchestration`, ECS
cluster `mopa-laser-rasterizer`, task family `mopa-laser-raster-worker`, log
group `/ecs/mopa-laser-raster-worker`, and the worker security group recorded
as `FARGATE_WORKER_SECURITY_GROUP_ID` in the ignored `.env.aws`. The EC2 node
security group permits NodePort `30379`
only from that worker security group; never replace it with a public CIDR rule.
CloudFormation outputs remain authoritative if the stack is recreated.

The orchestration stack creates EventBridge Pipe
`mopa-rasterizer-jobs-to-fargate` and Standard workflow
`mopa-rasterizer-fargate-job`. The web application writes a zero-byte
`jobs/TASK_ID/dispatch.ready` S3 marker; the bucket notification sends the
object-created event to SQS, and the pipe starts one workflow per marker. This
uses the existing free S3 gateway endpoint instead of requiring a paid SQS
interface endpoint for private K3s nodes. The workflow waits for each ECS task
to stop, tries Fargate Spot twice, falls back to one regular Fargate task, and
explicitly sends the task ID to the 14-day DLQ only if all three executions
fail. Override the number of Spot attempts with
`FARGATE_SPOT_WORKER_ATTEMPTS`; the on-demand fallback is always retained.
Set `FARGATE_DISPATCH_VIA_S3=true` on the web deployment only after the bucket
notification and orchestration stack are healthy.

The normal production topology does not require a second EC2 node. To restore
one temporarily for capacity or a Kubernetes-worker rollback after the control plane is available and the
local K3s tunnel is running:

```bash
bash dev_setup/add-ec2-k3s-worker.sh <worker-instance-id>
bash dev_setup/deploy-worker-to-node.sh <worker-instance-id>
```

`add-ec2-k3s-worker.sh` now ensures both Gateway endpoints before joining and
labeling the node. Do not label or uncordon a replacement worker until its S3
and DynamoDB HTTPS connectivity succeeds; workers retrieve inputs from S3 and
persist durable job status in DynamoDB.

`deploy_production.sh` builds and pushes one unique immutable image, updates the
Fargate task and orchestration stacks, preloads private K3s nodes, refreshes the
`ecr-registry` Kubernetes pull secret, renders and applies both workload
manifests, and verifies that the web image matches while the legacy K3s worker
remains at zero replicas. Reusing the same tag resumes a partial rollout from
the existing immutable ECR image.

The pull secret contains a short-lived ECR authorization token and is refreshed by every deployment. For replacement nodes that must start pods without a recent deployment, configure the AWS ECR kubelet credential provider on every K3s node. The EC2 instance profile created by the bootstrap script includes the required read-only ECR actions. Do not store ECR passwords in this repository.

Before applying `deployment.aws.yaml`, set its S3 bucket, DynamoDB table, Cognito domain/client ID, and public URL for the recovered environment. These are identifiers, not secret values.

## 3. ACM, Cognito, ALB, and DNS

The bootstrap script can create a replacement Cognito pool and generated-secret app client with `CREATE_COGNITO=1`. It prints the new secret exactly once, so save it immediately in a secure secret store. It can also configure the ALB, target group, listener rules, and root/`www` Route 53 aliases when invoked with `CONFIGURE_EDGE=1`. Edge setup intentionally requires VPC, subnet, security-group, instance, certificate, Route 53, and Cognito values as runtime environment variables; no secret is written to the script or repository.

1. Request an ACM public certificate in `us-east-2` for the root domain and `www`; complete its Route 53 DNS validation.
2. Create a Cognito User Pool using email sign-in and verification. Create an app client with a generated secret, OAuth code flow, scopes `openid email profile`, callback URL `https://mopa-laser-rasterizer.com/oauth2/idpresponse`, and logout URL `https://mopa-laser-rasterizer.com/`. Create a Cognito hosted-UI domain.
3. Create an internet-facing **Application Load Balancer** in two public subnets. Its target group is type `instance`, protocol HTTP, port `30080`, health-check path `/auth-status`, and includes the EC2 instance.
4. Add ALB listener `:80` to redirect permanently to HTTPS while preserving host/path/query.
5. Add HTTPS listener `:443` using the ACM certificate. Configure rules in this order:

   1. `/logout*`: forward directly to the target group.
   2. `/login*`: Cognito authenticate with unauthenticated action `authenticate`, then forward.
   3. Default: Cognito authenticate with unauthenticated action `allow`, then forward.

   Every Cognito action uses the same pool, app-client ID/secret, and hosted-UI domain. The direct logout rule is required so Flask can clear the ALB session and redirect to Cognito logout.

6. In Route 53, create root and `www` A Alias records to the ALB. Verify HTTP redirects and HTTPS presents the ACM certificate.

## 4. Validate the restoration

### Restore Proton Mail DNS

Proton Mail for the custom domain is restored independently of the web
application. Copy the `PROTON_MAIL_*` values from the environment-specific
backup into `.env.aws`, authenticate the deployment profile, and run:

```bash
bash dev_setup/ensure-proton-mail-dns.sh
```

The helper discovers (or uses the recorded) Route 53 hosted zone and
idempotently reconciles Proton's MX, SPF, three account-specific DKIM CNAMEs,
and a monitoring-only (`p=none`) DMARC policy. It merges the Proton ownership
verification and SPF values into the existing apex TXT record set, preserving
unrelated records such as Google site verification. DKIM targets are unique to
the Proton domain configuration; copy all three values from Proton's domain
wizard rather than inventing them. DNS records do not contain a Proton account
password or MFA secret.

After restoring DNS, use Proton's **Refresh status** action and confirm MX,
SPF, DKIM, and DMARC are all green. Custom addresses and catch-all behavior are
Proton account settings and must be recreated in Proton if the account itself
was replaced.

```bash
sudo kubectl get pods -n default
sudo kubectl get svc mopa-laser-rasterizer -n default
curl -I http://mopa-laser-rasterizer.com/
curl -I https://mopa-laser-rasterizer.com/
```

Confirm the ALB target is healthy, guests receive three daily jobs, `/login` reaches Cognito, sign-out works, and a signed-in job writes S3 objects below `users/<cognito-sub>/jobs/<task-id>/`.

Restore the private administrator binding after the K3s API tunnel is available:

```bash
bash dev_setup/configure-k3s-admin.sh you@example.com
```

This recreates the `mopa-rasterizer-admin` Secret without placing the email in
source control, restores the Cognito directory permission, and rolls the web
deployment. Verify that the configured account can open `/admin` and that a
different signed-in account receives a 404 response.

Confirm both workloads use the same ECR image and that each node can pull it:

```bash
sudo kubectl get deployment mopa-laser-rasterizer mopa-laser-raster-worker \
  -n default -o=jsonpath='{range .items[*]}{.metadata.name}{" -> "}{.spec.template.spec.containers[0].image}{"\n"}{end}'
sudo kubectl get pods -n default -o wide
```

Also launch a small SVG-only test job on each worker node. Its console should
show `Downloading the source image from durable storage` followed by `Source
image download complete` before raster processing begins. If it remains at the
download message, cordon that node and verify its S3 endpoint route and IAM
profile before returning it to service.

To inspect the durable job record from a pod:

```bash
python -c 'from services import get_job_record; import json; print(json.dumps(get_job_record("TASK_ID"), indent=2))'
```

Account history is stored in DynamoDB; job inputs and outputs expire from S3 after seven days, at which point the file panel intentionally hides those expired entries. Saved Material Libraries persist independently.
