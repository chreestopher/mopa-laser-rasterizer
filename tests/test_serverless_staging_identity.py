from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_staging_identity_is_invite_only_and_retained():
    template = read("ecs/serverless-staging-identity.yaml")
    assert "AllowAdminCreateUserOnly: true" in template
    assert "UserPoolTier: ESSENTIALS" in template
    assert "DeletionProtection: ACTIVE" in template
    assert "DeletionPolicy: Retain" in template
    assert "mopa-rasterizer-staging-${AWS::AccountId}" in template


def test_staging_deploy_rejects_nonisolated_pool_after_cutover():
    web = read("dev_setup/deploy_serverless_staging_web.sh")
    assert "SERVERLESS_STAGING_REQUIRE_ISOLATED_COGNITO" in web
    assert "SERVERLESS_STAGING_IDENTITY_STACK" in web
    assert '"$COGNITO_POOL_ID" != "$expected_pool"' in web
    assert "AllowAdminCreateUserOnly" in web
    workflow = read(".github/workflows/deploy-serverless-staging.yml")
    assert "SERVERLESS_STAGING_REQUIRE_ISOLATED_COGNITO" in workflow


def test_staging_deployer_cannot_manage_production_cognito_pool():
    role = read("ecs/github-actions-staging-deployer.yaml")
    assert "StagingUserPoolId" in role
    assert "HasIsolatedStagingPool" in role
    assert "cognito-idp:CreateUserPoolClient" in role
    assert "userpool/${StagingUserPoolId}" in role
    assert "userpool/${CognitoUserPoolId}" not in role


def test_migration_copies_only_durable_assets_and_keeps_source():
    migration = read("dev_setup/migrate_staging_identity_assets.py")
    assert 'DURABLE_PREFIXES = ("MATERIAL#", "DEPTHPALETTE#", "HOLOCALIBRATION#", "HOLORECIPE#")' in migration
    assert 'item["sk"] == "PREFERENCES"' in migration
    assert "s3.copy_object" in migration
    assert "table.put_item" in migration
    assert "table.delete_item" not in migration
    assert "s3.delete_object" not in migration
