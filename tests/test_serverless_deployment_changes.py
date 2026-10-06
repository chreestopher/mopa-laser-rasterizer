import unittest

from dev_setup.classify_serverless_deployment_changes import classify


class ServerlessDeploymentChangeTests(unittest.TestCase):
    def test_standalone_infrastructure_and_docs_do_not_deploy_the_application(self):
        selection = classify([
            "ecs/serverless-production-signup-alert.yaml",
            "docs/production-signup-alert.md",
            "tests/test_serverless_signup_alert.py",
        ])

        self.assertFalse(selection.any)
        self.assertFalse(selection.fallback_paths)

    def test_frontend_and_api_changes_select_only_web(self):
        selection = classify([
            "serverless_web/rasterizer/jobs-v1.js",
            "serverless_api/handler.py",
            "templates/changelog.html",
        ])

        self.assertTrue(selection.web)
        self.assertFalse(selection.worker)

    def test_worker_runtime_changes_select_only_worker(self):
        selection = classify(["worker.py", "lib/custom_shape.py", "Dockerfile"])

        self.assertTrue(selection.worker)
        self.assertFalse(selection.web)

    def test_shared_routes_and_release_scripts_select_both_components(self):
        selection = classify([
            "routes/holographic.py",
            "dev_setup/deploy_serverless_staging_release.sh",
        ])

        self.assertTrue(selection.worker)
        self.assertTrue(selection.web)

    def test_deployment_workflow_paths_keep_their_leading_dot(self):
        selection = classify([".github/workflows/deploy-serverless-staging.yml"])

        self.assertTrue(selection.worker)
        self.assertTrue(selection.web)
        self.assertFalse(selection.fallback_paths)

    def test_unknown_paths_fail_safe_to_full_deployment(self):
        selection = classify(["new_runtime/component.py"])

        self.assertTrue(selection.worker)
        self.assertTrue(selection.web)
        self.assertEqual(selection.fallback_paths, ("new_runtime/component.py",))


if __name__ == "__main__":
    unittest.main()
