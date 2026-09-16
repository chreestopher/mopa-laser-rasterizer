import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "dev_setup" / "verify_production_auth.py"
SPEC = importlib.util.spec_from_file_location("verify_production_auth", SCRIPT)
auth = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auth)


class ProductionAuthContractTests(unittest.TestCase):
    def setUp(self):
        auth.POOL_ID = "pool-123"
        auth.COGNITO_DOMAIN = "example.auth.us-east-2.amazoncognito.com"
        self.stack = {
            "Parameters": [
                {"ParameterKey": "StagingHostname", "ParameterValue": "mopa-laser-rasterizer.com"},
                {"ParameterKey": "AlternateHostname", "ParameterValue": "www.mopa-laser-rasterizer.com"},
                {"ParameterKey": "CloudFrontCertificateArn", "ParameterValue": "arn:aws:acm:certificate"},
                {"ParameterKey": "CognitoUserPoolId", "ParameterValue": auth.POOL_ID},
            ],
            "Outputs": [
                {"OutputKey": "PublicUrl", "OutputValue": auth.ORIGINS[0]},
                {"OutputKey": "ApiUrl", "OutputValue": "https://api.example"},
                {"OutputKey": "CognitoClientId", "OutputValue": "client-123"},
            ],
        }
        self.client = {
            "ClientId": "client-123",
            "AllowedOAuthFlowsUserPoolClient": True,
            "AllowedOAuthFlows": ["code"],
            "SupportedIdentityProviders": ["COGNITO"],
            "CallbackURLs": ["https://preview.example/", *auth.ORIGINS],
            "LogoutURLs": ["https://preview.example/", *auth.ORIGINS],
        }

    def test_matching_stack_client_and_public_config(self):
        outputs, errors = auth.verify_stack_and_client(self.stack, self.client)
        self.assertEqual(errors, [])
        self.assertEqual(auth.verify_public_config({
            "client_id": "client-123",
            "callback_url": auth.ORIGINS[0],
            "cognito_domain": auth.COGNITO_DOMAIN,
            "api_url": "https://api.example",
        }, outputs), [])

    def test_missing_www_callback_fails(self):
        self.client["CallbackURLs"].remove(auth.ORIGINS[1])
        _, errors = auth.verify_stack_and_client(self.stack, self.client)
        self.assertTrue(any("CallbackURLs" in error for error in errors))

    def test_preview_only_stack_fails(self):
        self.stack["Parameters"][2]["ParameterValue"] = ""
        self.stack["Outputs"][0]["OutputValue"] = "https://preview.example/"
        _, errors = auth.verify_stack_and_client(self.stack, self.client)
        self.assertTrue(any("certificate" in error for error in errors))
        self.assertTrue(any("public URL" in error for error in errors))

    def test_stale_published_client_fails(self):
        outputs, _ = auth.verify_stack_and_client(self.stack, self.client)
        errors = auth.verify_public_config({
            "client_id": "old-client",
            "callback_url": "https://preview.example/",
            "cognito_domain": auth.COGNITO_DOMAIN,
            "api_url": "https://api.example",
        }, outputs)
        self.assertTrue(any("client ID" in error for error in errors))
        self.assertTrue(any("callback URL" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
