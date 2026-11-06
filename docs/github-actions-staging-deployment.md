# GitHub Actions staging deployment

The `Deploy serverless staging` workflow provides a second deployment path for serverless staging. It does not replace workstation deployment.

## Authentication paths

- GitHub Actions uses OpenID Connect (OIDC) to assume a staging deployment role. AWS issues short-lived credentials for each run; no AWS access key is stored in GitHub.
- Workstation scripts continue to load `.env.aws` and use `DEPLOY_AWS_PROFILE`, defaulting to the `mopa-admin` AWS SSO profile when no ambient AWS credentials exist.

The shared `configure_aws_deployment_credentials` helper automatically selects the correct path. Never add `.env.aws`, AWS keys, the staging access-gate value, or SSO cache files to the repository.

## GitHub environment

Create a GitHub environment named `serverless-staging`. Require a reviewer when the repository plan supports it, then configure these environment values.

The initial AWS identity can be created by an administrator using `ecs/github-actions-staging-deployer.yaml`. The template creates the account-level GitHub OIDC provider and an update-only role whose trust policy accepts only this repository's `serverless-staging` GitHub environment. Its permissions name the existing staging stacks and resources explicitly. It cannot create a stack, delete a stack, manage production stacks, or create and delete application IAM roles. Do not deploy a second copy of the template in the same AWS account.

Variables:

- `AWS_STAGING_DEPLOY_ROLE_ARN`
- `AWS_REGION` (normally `us-east-2`)
- `COGNITO_POOL_ID`
- `COGNITO_DOMAIN`
- `IDENTITY_CENTER_ADMIN_EMAIL`
- `SERVERLESS_STAGING_ALLOWED_USER_SUB`
- `SERVERLESS_STAGING_GUEST_ACCESS_ENABLED` (normally `false`)
- `SERVERLESS_STAGING_HOSTNAME`
- `SERVERLESS_STAGING_CERTIFICATE_ARN`

Secret:

- `SERVERLESS_STAGING_ACCESS_GATE_AUTHORIZATION`

Store only the Base64-encoded `username:password` payload in this secret. Do not include the `Basic ` authentication-scheme prefix; the deployment template and endpoint verification add that prefix where required.

This repository uses GitHub's immutable owner and repository IDs in its customized OIDC subject. The AWS role trust policy must restrict the subject to:

```text
repo:chreestopher@6197770/mopa-laser-rasterizer@1325278435:environment:serverless-staging
```

and require the audience `sts.amazonaws.com`.

## Running a deployment

Merging a pull request into the protected `staging` branch runs tests and deploys components changed since their last successful deployment, including changes left pending by a failed earlier run. For a targeted or repeat deployment, open **Actions → Deploy serverless staging → Run workflow**, select the `staging` branch and one target:

- `web-api`: Lambda API, static frontend, documentation, and media.
- `worker`: worker image and orchestration task reference.
- `release`: existing worker/orchestration resources followed by the API and frontend.

Only one staging deployment runs at a time. A queued run will not cancel an active deployment. Every run validates shell syntax and passes the regression suite before AWS credentials are requested.

## Successful deployment baselines

The staging job uses two mutable lightweight Git tags as deployment records:

- `staging-deployed-web`: the last successfully deployed and endpoint-verified web/API revision.
- `staging-deployed-worker`: the last revision whose worker/orchestration deployment script completed successfully (CloudFormation updates included; this is not an engraving/job smoke test).

Each component is classified against its own recorded revision. Test-only or
documentation-only merges skip deployment only when no runtime changes remain
since those baselines. Manual targets still force only the requested components
and advance only their corresponding records. Skipped or failed components never
advance. A worker success is recorded before starting web deployment, so a later
web failure does not discard the worker result.

Missing markers cause a conservative deployment of the missing component. The
first run after enabling this mechanism therefore deploys both components. Tags
are updated with compare-and-swap leases; write failures fail the run and retain
the prior baseline for a later retry. The job needs `contents: write` for these
two tags using its existing GitHub token; no new AWS permission or personal token
is needed. Repository tag rules must allow this workflow to update these names.
Production workflow permissions and baseline logic are unchanged.

The job only runs on `staging` and checks that its revision is still the branch
tip after tests, before requesting AWS credentials. An obsolete queued run fails
rather than deploying an old revision; the latest staging run should be used.
Marker rewinds or divergent-history updates are rejected. A rewritten staging
history requires operator reconciliation of deployment records before proceeding.
Read/authentication errors are not treated as missing markers.

Workstation deployments do not automatically update these records. After an
out-of-band deployment, use the staging workflow for the affected component to
establish a verified record. Do not advance tags just because tests passed.

## Production promotion policy

All production changes must pass through staging. Develop on a feature branch, open a pull request into the protected `staging` branch, and complete staging acceptance after the automatic deployment succeeds. Production promotion is a pull request from `staging` to the protected `main` branch.

The `Require staging promotion` workflow rejects a pull request into `main` when its source is anything other than this repository's `staging` branch. Configure the `main` ruleset to require its **Production changes came through staging** status check, require a pull request, block force pushes and deletions, and disallow bypass for normal development. Configure the `staging` ruleset to require pull requests and staging test checks while blocking force pushes and deletions.

If an emergency production correction is ever merged to `main`, immediately merge `main` back into `staging` before accepting more feature work. This keeps the environments from drifting.

The workstation production scripts remain available for AWS SSO deployment, but their fail-closed guard permits production deployment only from a clean local checkout of `main` at the explicitly supplied release commit. A GitHub-hosted production workflow is restricted to `refs/heads/main` and the protected `serverless-production` environment. See [GitHub Actions production deployment](github-actions-production-deployment.md). Because the protected `main` ruleset accepts changes only through the required staging-promotion check, both deployment paths consume code that followed the same promotion route.

The staging GitHub path deliberately does not create foundational infrastructure, create or delete application IAM roles, delete staging objects, modify repository lifecycle policy, update Cognito, or apply managed-login branding. It can update only the existing staging workflow role's inline policy because each immutable worker task-definition revision changes that policy's `ecs:RunTask` resource. It publishes worker images to a staging-only ECR repository. Structural infrastructure changes, cleanup operations, identity changes, and account-level maintenance remain available from the workstation path.

## Workstation fallback

Continue deploying locally after refreshing SSO:

```bash
aws sso login --profile mopa-admin --use-device-code
bash dev_setup/deploy_serverless_staging_application.sh
```

To use another local profile, set `DEPLOY_AWS_PROFILE`. If temporary AWS credentials are already present in the environment, the scripts use those credentials instead of a profile.
