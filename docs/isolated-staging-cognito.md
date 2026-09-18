# Isolated staging Cognito cutover

Staging currently shares a Cognito user pool with production. Do **not** turn off self-registration on that shared pool: it would also stop production signups. This migration creates a separate staging pool with `AllowAdminCreateUserOnly: true` from its first moment of use. The production pool and its app client remain unchanged.

The existing staging user has durable records under their old Cognito `sub`: material libraries, depth palettes, fauxlographic calibrations and recipes, and preferences. The one-time migration copies those records and referenced S3 objects to the invited user's new `sub`, leaving the originals intact. Short-lived jobs, upload fingerprints, and color-discovery history are not copied; they retain their existing seven-day lifecycle.

## Sequence

1. Merge this feature PR into `staging`. The automatic deployment still uses the old Cognito environment variables, so this merge alone does **not** cut over authentication.
2. From a workstation with refreshed admin SSO, run `bash dev_setup/deploy_serverless_staging_identity.sh --apply`. Verify its distinct pool ID and invite-only configuration. This creates a new Essentials-tier Cognito pool and prefix domain, not a new production pool.
3. Run `bash dev_setup/invite_isolated_staging_admin.sh --apply`. It sends the existing staging owner a temporary-password invitation; it does not print the password. Record the new `sub` printed by the script.
4. In a Python environment with the repository's `boto3` dependency installed, run `python3 dev_setup/migrate_staging_identity_assets.py --target-sub NEW_SUB` to review the durable record and S3-object counts. Then rerun with `--apply` while no staging jobs or palette edits are in progress. The script refuses to overwrite destination records or objects.
5. Update the existing GitHub staging deploy-role stack from `ecs/github-actions-staging-deployer.yaml`, preserving its current parameter values and setting `StagingUserPoolId` to the new pool ID. The added Cognito permissions apply only to that pool. Do not grant this role access to the shared production pool.
6. Use workstation SSO for the **first** staging web-stack cutover, with `SERVERLESS_STAGING_COGNITO_POOL_ID`, `SERVERLESS_STAGING_COGNITO_DOMAIN`, and `SERVERLESS_STAGING_ALLOWED_USER_SUB_OVERRIDE` exported to the new values, then run `bash dev_setup/deploy_serverless_staging_web.sh`. The explicit overrides take precedence over the workstation's old `.env.aws` values. This first update replaces the old staging app client in the shared pool; the GitHub role intentionally has no permission to delete a client there.
7. After the workstation cutover succeeds, change the GitHub `serverless-staging` environment variables `COGNITO_POOL_ID`, `COGNITO_DOMAIN`, and `SERVERLESS_STAGING_ALLOWED_USER_SUB` to the new pool ID, new domain hostname, and new `sub`. Set `SERVERLESS_STAGING_REQUIRE_ISOLATED_COGNITO` to `true`. Keep the access-gate secret unchanged. Doing this after the initial cutover prevents an automatic GitHub deployment from attempting to delete a client in the production pool.
8. Sign in through the staging gate and Cognito using the invitation's temporary password, complete the password change, and verify the vault's durable assets, job submission, and logout. Then run the staging GitHub workflow once to confirm future deploys work with the isolated pool.

Do not reveal the invitation password or access-gate credentials in logs or PRs. The temporary password can be reset by an administrator if it expires before cutover.

## Rollback

The migration never deletes old pool users, DynamoDB records, or S3 objects. If the new sign-in path fails, restore the previous three GitHub environment values and redeploy the staging web stack from the workstation with the previous Cognito pool/domain/allowed-sub values. Production remains on its original pool throughout. Investigate the isolated pool before trying the cutover again.

Managed login version 2 requires the Essentials tier. Cognito's direct-sign-in free tier is pooled per AWS account, so an isolated pool for one staging administrator should not add MAU charges while the account stays within that tier; Cognito email and other service usage may still incur charges.
