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

The AWS role trust policy must restrict the GitHub OIDC subject to:

```text
repo:chreestopher/mopa-laser-rasterizer:environment:serverless-staging
```

and require the audience `sts.amazonaws.com`.

## Running a deployment

Open **Actions → Deploy serverless staging → Run workflow**, select the Git revision and one target:

- `web-api`: Lambda API, static frontend, documentation, and media.
- `worker`: worker image and orchestration task reference.
- `release`: existing worker/orchestration resources followed by the API and frontend.

Only one staging deployment runs at a time. A queued run will not cancel an active deployment. Every run validates shell syntax and passes the regression suite before AWS credentials are requested.

The GitHub path deliberately does not create foundational infrastructure, mutate application IAM policies, delete staging objects, modify the shared ECR repository or lifecycle policy, update Cognito, or apply managed-login branding. It publishes worker images to a staging-only ECR repository. Structural infrastructure changes, cleanup operations, identity changes, and account-level maintenance remain available from the workstation path.

## Workstation fallback

Continue deploying locally after refreshing SSO:

```bash
aws sso login --profile mopa-admin --use-device-code
bash dev_setup/deploy_serverless_staging_application.sh
```

To use another local profile, set `DEPLOY_AWS_PROFILE`. If temporary AWS credentials are already present in the environment, the scripts use those credentials instead of a profile.
