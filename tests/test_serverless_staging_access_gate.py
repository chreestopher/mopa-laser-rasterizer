from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_cloudfront_gate_is_optional_and_attached_at_viewer_request():
    template = read("ecs/serverless-staging-web.yaml")

    assert "AccessGateAuthorization:" in template
    assert "NoEcho: true" in template
    assert "HasAccessGate:" in template
    assert "Type: AWS::CloudFront::Function" in template
    assert "authorization.value === 'Basic ${AccessGateAuthorization}'" in template
    assert "statusCode: 401" in template
    assert "EventType: viewer-request" in template
    assert "FunctionARN: !GetAtt StagingAccessFunction.FunctionMetadata.FunctionARN" in template


def test_staging_api_can_disable_guests_and_allow_only_one_subject():
    template = read("ecs/serverless-staging-web.yaml")
    handler = read("serverless_api/handler.py")

    assert "GUEST_ACCESS_ENABLED: !Ref GuestAccessEnabled" in template
    assert "ALLOWED_USER_SUB: !Ref AllowedUserSub" in template
    assert 'GUEST_ACCESS_ENABLED = os.environ.get("GUEST_ACCESS_ENABLED", "true")' in handler
    assert 'ALLOWED_USER_SUB = os.environ.get("ALLOWED_USER_SUB", "").strip()' in handler
    assert 'if path == "/guest" or path.startswith("/guest/"):' in handler
    assert "Guest access is disabled in this environment" in handler
    assert "secrets.compare_digest(subject, ALLOWED_USER_SUB)" in handler


def test_production_explicitly_disables_the_staging_gate():
    production = read("dev_setup/deploy_serverless_production_web.sh")
    shared_deployment = read("dev_setup/deploy_serverless_staging_web.sh")

    assert 'export SERVERLESS_ACCESS_GATE_AUTHORIZATION=""' in production
    assert 'export SERVERLESS_GUEST_ACCESS_ENABLED="true"' in production
    assert 'export SERVERLESS_ALLOWED_USER_SUB=""' in production
    assert 'SERVERLESS_ACCESS_GATE_AUTHORIZATION+x' in shared_deployment
    assert 'ACCESS_GATE_AUTHORIZATION="$SERVERLESS_ACCESS_GATE_AUTHORIZATION"' in shared_deployment
    assert 'SERVERLESS_ALLOWED_USER_SUB+x' in shared_deployment
    assert 'ALLOWED_USER_SUB="$SERVERLESS_ALLOWED_USER_SUB"' in shared_deployment
