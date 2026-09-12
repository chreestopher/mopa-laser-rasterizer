from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_monthly_budget_has_warning_and_overspend_notifications():
    template = read("ecs/serverless-cost-guard.yaml")

    assert "AWS::Budgets::Budget" in template
    assert "TimeUnit: MONTHLY" in template
    assert "BudgetType: COST" in template
    assert "MonthlyLimitUsd" in template
    assert "WarningThresholdPercent" in template
    assert "Threshold: 100" in template
    assert template.count("NotificationType: ACTUAL") == 2
    assert "budgets.amazonaws.com" in template
    assert "Protocol: email" in template


def test_cost_guard_email_contains_authenticated_operator_actions():
    handler = read("serverless_cost_guard/handler.py")

    assert "days_left" in handler
    assert "Pause:" in handler
    assert "Continue / leave running:" in handler
    assert "Start / re-enable if paused:" in handler
    assert "admin.html?" in handler
    assert "Each link opens an authenticated administrator confirmation" in handler
    assert "No action will be taken automatically" in handler


def test_cost_guard_controls_production_and_staging_independently():
    handler = read("serverless_cost_guard/handler.py")
    template = read("ecs/serverless-cost-guard.yaml")
    deployment = read("dev_setup/deploy_serverless_cost_guard.sh")

    assert '"production": {' in handler
    assert '"staging": {' in handler
    assert "environment_actions('production')" in handler
    assert "environment_actions('staging')" in handler
    assert "changing one does not change the other" in handler
    assert "Ignore this email to leave both environments running" in handler

    for parameter in (
        "ProductionPublicUrl",
        "ProductionRuntimeTableName",
        "ProductionPipeName",
        "StagingPublicUrl",
        "StagingRuntimeTableName",
        "StagingPipeName",
    ):
        assert parameter in template
        assert parameter in deployment

    assert "tables[environment]" in handler
    assert 'ENVIRONMENTS[environment]["pipe_name"]' in handler


def test_pause_blocks_api_and_fargate_launches_independently():
    api = read("serverless_api/handler.py")
    orchestration = read("ecs/rasterizer-orchestration.yaml")

    assert "SERVICE_PAUSED_FOR_COST" in api
    assert api.count("paused = service_paused_response()") == 2
    assert "pipes.stop_pipe(Name=PIPE_NAME)" in api
    assert "pipes.start_pipe(Name=PIPE_NAME)" in api
    assert "CheckServiceAvailability:" in orchestration
    assert "WaitForServiceResume:" in orchestration
    assert orchestration.index("CheckServiceAvailability:") < orchestration.index("RunSpotWorker:")
    assert 'StringEquals: paused' in orchestration


def test_pause_control_is_publicly_visible_but_admin_only_to_change():
    template = read("ecs/serverless-staging-web.yaml")
    api = read("serverless_api/handler.py")
    shell = read("serverless_web/staging-shell.js")
    admin = read("serverless_web/admin.js")

    assert "GET /service-status" in template
    assert "AuthorizationType: NONE" in template[template.index("  ServiceStatusRoute:"):template.index("  GuestUploadRoute:")]
    assert 'RouteKey: "POST /admin/service-control"' in template
    assert "AuthorizerId: !Ref JwtAuthorizer" in template[template.index("  AdminServiceControlPostRoute:"):]
    assert "require_admin(event)" in api
    assert "/service-status" in shell
    assert "service-pause-banner" in shell
    assert 'api("/admin/service-control"' in admin


def test_cost_pause_expires_at_next_month_without_ttl_on_durable_control():
    api = read("serverless_api/handler.py")
    guard = read("serverless_cost_guard/handler.py")

    assert "next_billing_cycle_start" in api
    assert "automatic-monthly-reset" in api
    assert "resume_if_due" in guard
    control_section = api[api.index("def admin_service_control"):api.index("def safe_name")]
    assert "expires_at" not in control_section


def test_cost_guard_deployment_defaults_to_requested_limits():
    deployment = read("dev_setup/deploy_serverless_cost_guard.sh")
    example = read(".env.aws.example")

    assert 'SERVERLESS_MONTHLY_BUDGET_USD:-100' in deployment
    assert 'SERVERLESS_BUDGET_WARNING_PERCENT:-75' in deployment
    assert "SERVERLESS_MONTHLY_BUDGET_USD=100" in example
    assert "SERVERLESS_BUDGET_WARNING_PERCENT=75" in example
    assert "StaticBucketName" in deployment


def test_cost_guard_resolves_public_urls_from_deployed_web_stacks():
    deployment = read("dev_setup/deploy_serverless_cost_guard.sh")

    assert 'PRODUCTION_WEB_STACK="${SERVERLESS_PRODUCTION_WEB_STACK:-mopa-rasterizer-serverless-production-web}"' in deployment
    assert 'STAGING_WEB_STACK="${SERVERLESS_STAGING_WEB_STACK:-mopa-rasterizer-serverless-staging-web}"' in deployment
    assert 'PRODUCTION_PUBLIC_URL="$(output "$PRODUCTION_WEB_STACK" PublicUrl)"' in deployment
    assert 'STAGING_PUBLIC_URL="$(output "$STAGING_WEB_STACK" PublicUrl)"' in deployment
    assert 'https://${SERVERLESS_PRODUCTION_HOSTNAME:-}' not in deployment
    assert 'https://${SERVERLESS_STAGING_HOSTNAME:-}' not in deployment


def test_staging_pause_acceptance_refuses_busy_service_and_always_recovers():
    acceptance = read("dev_setup/test_serverless_cost_pause.sh")

    assert "Refusing to pause a non-empty staging queue" in acceptance
    assert "Refusing to pause while a staging worker is running" in acceptance
    assert "trap resume EXIT" in acceptance
    assert "aws pipes stop-pipe" in acceptance
    assert "aws pipes start-pipe" in acceptance
    assert '"status":"paused"' in acceptance
    assert '"status":"active"' in acceptance
