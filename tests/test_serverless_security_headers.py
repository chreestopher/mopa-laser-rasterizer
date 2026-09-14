from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "ecs" / "serverless-staging-web.yaml"


def test_static_distribution_uses_security_response_headers_policy():
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "StaticSecurityHeadersPolicy:" in template
    assert "Type: AWS::CloudFront::ResponseHeadersPolicy" in template
    assert "ResponseHeadersPolicyId: !Ref StaticSecurityHeadersPolicy" in template
    assert "AccessControlMaxAgeSec: 31536000" in template
    assert "FrameOption: DENY" in template
    assert "ReferrerPolicy: strict-origin-when-cross-origin" in template
    assert "ContentTypeOptions:" in template
    assert "Header: Permissions-Policy" in template


def test_csp_starts_in_report_only_mode_and_covers_guest_dependencies():
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "Header: Content-Security-Policy-Report-Only" in template
    assert "ContentSecurityPolicy:" not in template
    assert "https://cdn.jsdelivr.net" in template
    assert "https://*.execute-api.us-east-2.amazonaws.com" in template
    assert "https://*.amazonaws.com" in template
    assert "https://*.amazoncognito.com" in template
    assert "https://huggingface.co" in template
    assert "https://*.huggingface.co" in template
    assert "https://*.hf.co" in template
