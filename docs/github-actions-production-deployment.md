# GitHub Actions production deployment

Production releases are promoted from the protected `staging` branch into the protected `main` branch. A successful merge to `main` triggers **Deploy serverless production**. The workflow tests the exact promoted commit, assumes a short-lived AWS role through GitHub OIDC, publishes an immutable worker image, and updates the existing production application sequentially.

## What the workflow may change

The production deployer is intentionally update-only. It can update the existing production worker, orchestration, API, CloudFront distribution, and static site. It can publish worker images to the production ECR repository, publish site files to the production static bucket, maintain the runtime table's selective job TTL, and configure upload CORS.

It cannot create or delete CloudFormation stacks, create or delete IAM roles, deploy staging, manage AWS Budgets or the cost guard, change Route 53, change Cognito branding, or rebuild foundational storage and queues. Those account-level and structural operations remain workstation-admin tasks using AWS SSO.

## One-time administrator bootstrap

The AWS account must already contain the GitHub OIDC provider created for staging. From a clean administrator workstation session, review `ecs/github-actions-production-deployer.yaml`, refresh AWS SSO, and run:

```bash
bash dev_setup/deploy_github_actions_production_deployer.sh --apply
```

The script discovers the physical IDs of the existing production resources and creates the narrowly scoped role. It prints the role ARN needed by GitHub.

## GitHub environment

Create a protected GitHub environment named `serverless-production` and restrict deployment branches to `main`. Configure these environment variables:

- `AWS_PRODUCTION_DEPLOY_ROLE_ARN`
- `AWS_REGION` (normally `us-east-2`)
- `COGNITO_POOL_ID`
- `COGNITO_DOMAIN`
- `IDENTITY_CENTER_ADMIN_EMAIL`
- `S3_BUCKET_NAME`
- `DYNAMODB_TABLE_NAME`
- `SERVERLESS_PRODUCTION_CERTIFICATE_ARN`
- `SERVERLESS_PRODUCTION_USE_CLOUDFRONT_CALLBACK` (normally `false` after cutover)

No long-lived AWS key is stored in GitHub. Production currently requires no GitHub environment secret.

The role trust policy accepts only this repository's `serverless-production` environment subject:

```text
repo:chreestopher@6197770/mopa-laser-rasterizer@1325278435:environment:serverless-production
```

## Release flow

1. Merge feature work into `staging` through a pull request.
2. Let the automatic staging deployment complete and perform acceptance testing.
3. Open the promotion pull request from `staging` to `main`.
4. Merge only after the required **Production changes came through staging** check passes.
5. Monitor **Deploy serverless production**. The workflow tests first, builds and pushes an image addressed by SHA-256 digest, deploys worker/orchestration, then API/frontend, and finally checks the public production endpoint.

The workflow uses a concurrency lock and never cancels an active production deployment.

## Workstation fallback

Local production deployment remains available and continues to require a clean checkout of `main` at an explicitly named release commit:

```bash
export SERVERLESS_PRODUCTION_RELEASE_COMMIT="$(git rev-parse HEAD)"
bash dev_setup/deploy_serverless_production_application.sh --apply
```

The local application script also reconciles the account-level cost guard. The GitHub application release intentionally does not.
