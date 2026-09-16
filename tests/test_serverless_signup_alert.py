from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_signup_alert_is_production_client_specific_and_does_not_modify_cognito():
    template = read("ecs/serverless-production-signup-alert.yaml")

    assert "AWS Service Event via CloudTrail" in template
    assert "signup_confirm_POST" in template
    assert "AwsServiceEvent" in template
    assert "userPoolId: [!Ref UserPoolId]" in template
    assert "clientId: [!Ref ProductionClientId]" in template
    assert "status: [204]" in template
    assert "AWS::CloudTrail::Trail" in template
    assert "IsMultiRegionTrail: false" in template
    assert "ReadWriteType: WriteOnly" in template
    assert "ExpirationInDays: 30" in template
    assert "AWS::Cognito::UserPool" not in template
    assert "AWS::Lambda::Function" not in template


def test_signup_alert_deployment_requires_explicit_apply_and_uses_budget_recipient():
    script = read("dev_setup/deploy_serverless_production_signup_alert.sh")

    assert '"${1:-}" != "--apply"' in script
    assert "configure_aws_deployment_credentials" in script
    assert "OperatorEmail" in script
    assert "SERVERLESS_PRODUCTION_COST_GUARD_STACK" in script
    assert "SERVERLESS_PRODUCTION_WEB_STACK" in script
    assert "validate-template" in script
    assert "--no-fail-on-empty-changeset" in script
