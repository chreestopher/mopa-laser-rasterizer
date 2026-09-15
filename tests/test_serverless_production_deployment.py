from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_production_deployment_requires_explicit_apply_and_clean_release():
    guard = read("dev_setup/serverless-production-guard.sh")
    worker = read("dev_setup/deploy_serverless_production.sh")
    web = read("dev_setup/deploy_serverless_production_web.sh")

    assert '"${1:-}" != "--apply"' in worker
    assert '"${1:-}" != "--apply"' in web
    assert "SERVERLESS_PRODUCTION_RELEASE_COMMIT" in guard
    assert '"${GITHUB_REF:-}" = "refs/heads/main"' in guard
    assert '"$current_branch" = "main"' in guard
    assert "Refusing production deployment from a local branch other than main" in guard
    assert "git -C \"$repo_root\" status --porcelain --untracked-files=all" in guard
    assert "git -C \"$repo_root\" ls-files --others --exclude-standard" in guard
    assert "git -C \"$repo_root\" diff --cached --quiet" in guard
    assert "git -C \"$repo_root\" diff --ignore-space-at-eol --quiet" in guard
    assert "Refusing production deployment from a dirty worktree" in guard


def test_production_reuses_staging_image_without_local_docker_build():
    production = read("dev_setup/deploy_serverless_production.sh")

    assert "SERVERLESS_PRODUCTION_IMAGE_URI" in production
    assert "@sha256:" in production
    assert "SERVERLESS_ALLOW_LOCAL_IMAGE_BUILD=false" in production
    assert "docker build" not in production


def test_production_enables_selective_job_ttl_with_durable_asset_guard():
    production = read("dev_setup/deploy_serverless_production.sh")
    ttl = read("dev_setup/ensure_dynamodb_job_ttl.sh")

    assert 'ensure_dynamodb_job_ttl.sh" --apply "$DYNAMODB_TABLE_NAME"' in production
    assert 'TTL_ATTRIBUTE="expires_at"' in ttl
    assert "begins_with(#sk,:material)" in ttl
    assert "begins_with(#sk,:depth)" in ttl
    assert "begins_with(#sk,:holo)" in ttl
    assert "begins_with(#pk,:community)" in ttl
    assert "Refusing to enable TTL" in ttl


def test_production_application_deploys_components_sequentially():
    application = read("dev_setup/deploy_serverless_production_application.sh")

    worker = application.index('bash "$SCRIPT_DIR/deploy_serverless_production.sh"')
    web = application.index('bash "$SCRIPT_DIR/deploy_serverless_production_web.sh"')
    cost_guard = application.index('bash "$SCRIPT_DIR/deploy_serverless_cost_guard.sh"')
    assert worker < web < cost_guard
    assert "&" not in "\n".join(
        line for line in application.splitlines() if line.lstrip().startswith("bash ")
    )


def test_production_foundation_isolates_queue_and_static_bucket_only():
    foundation = read("ecs/serverless-production-foundation.yaml")

    assert "AWS::SQS::Queue" in foundation
    assert "mopa-rasterizer-serverless-production-jobs" in foundation
    assert "StaticBucket:" in foundation
    assert "DeletionPolicy: Retain" in foundation
    assert "AWS::DynamoDB::Table" not in foundation
    assert "ArtifactBucketName: {Value: !Ref ArtifactBucketName}" in foundation
    assert "RuntimeTableName: {Value: !Ref RuntimeTableName}" in foundation


def test_web_stack_keeps_static_policy_off_the_artifact_bucket():
    template = read("ecs/serverless-staging-web.yaml")

    policy = template[template.index("  StaticBucketPolicy:") : template.index("  StagingAppClient:")]
    assert "Bucket: !Ref StaticBucketName" in policy
    assert "${StaticBucketName}/web/*" in policy
    assert "Bucket: !Ref ArtifactBucketName" not in policy


def test_web_stack_supports_preview_and_both_production_hostnames():
    template = read("ecs/serverless-staging-web.yaml")

    assert "AlternateHostname:" in template
    assert 'https://${Distribution.DomainName}/' in template
    assert 'https://${StagingHostname}/' in template
    assert 'https://${AlternateHostname}/' in template
    assert "DeploymentName:" in template
    assert "ApiFunctionName:" in template

    production_script = read("dev_setup/deploy_serverless_production_web.sh")
    assert 'CERTIFICATE_ARN="${SERVERLESS_PRODUCTION_CERTIFICATE_ARN:-}"' in production_script
    assert 'export SERVERLESS_PRIMARY_HOSTNAME=""' in production_script
    assert "SERVERLESS_CONFIGURE_ARTIFACT_CORS=true" in production_script


def test_production_web_configures_post_only_artifact_cors():
    script = read("dev_setup/deploy_serverless_staging_web.sh")

    assert "put-bucket-cors" in script
    assert '\"AllowedMethods\":[\"POST\"]' in script
    assert '\"AllowedOrigins\":origins' in script
    assert '"${CLOUDFRONT_URL%/}"' in script


def test_production_path_contains_no_dns_mutation():
    combined = "\n".join(
        read(path)
        for path in (
            "dev_setup/deploy_serverless_production.sh",
            "dev_setup/deploy_serverless_production_web.sh",
            "dev_setup/deploy_serverless_production_application.sh",
        )
    )

    assert "route53" not in combined.lower()
    assert "change-resource-record-sets" not in combined


def test_shell_labels_staging_and_production_from_hostname():
    shell = read("serverless_web/staging-shell.js")

    assert 'location.hostname.includes("serverless-staging")' in shell
    assert 'isStagingEnvironment ? "Staging" : "Production"' in shell
    assert 'isStagingEnvironment ? "TEST" : "PRODUCTION"' in shell
