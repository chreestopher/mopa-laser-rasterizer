import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class DeploymentRetentionTests(unittest.TestCase):
    def test_ecr_lifecycle_keeps_only_the_newest_ten_images(self):
        policy = json.loads(read("dev_setup/ecr-lifecycle-policy.json"))

        self.assertEqual(
            policy,
            {
                "rules": [
                    {
                        "rulePriority": 1,
                        "description": "Keep only the newest 10 images in this environment repository",
                        "selection": {
                            "tagStatus": "any",
                            "countType": "imageCountMoreThan",
                            "countNumber": 10,
                        },
                        "action": {"type": "expire"},
                    }
                ]
            },
        )

    def test_worker_deployments_prune_task_definition_history(self):
        pruning = read("dev_setup/prune_ecs_task_definitions.sh")
        shared_deployment = read("dev_setup/deploy_serverless_staging.sh")
        staging_worker = read("dev_setup/deploy_serverless_staging_worker_only.sh")

        self.assertIn('ECS_TASK_DEFINITION_RETAIN_COUNT:-10', pruning)
        self.assertIn("aws ecs list-task-definitions", pruning)
        self.assertIn("aws ecs deregister-task-definition", pruning)
        self.assertIn('bash "$SCRIPT_DIR/prune_ecs_task_definitions.sh"', shared_deployment)
        self.assertIn('bash "$SCRIPT_DIR/prune_ecs_task_definitions.sh"', staging_worker)

    def test_deployment_roles_can_apply_retention(self):
        for relative_path in (
            "ecs/github-actions-staging-deployer.yaml",
            "ecs/github-actions-production-deployer.yaml",
        ):
            with self.subTest(template=relative_path):
                template = read(relative_path)
                self.assertIn("ecs:ListTaskDefinitions", template)
                self.assertIn(
                    "- Sid: DeregisterTaskDefinition\n"
                    "                Effect: Allow\n"
                    "                Action: ecs:DeregisterTaskDefinition\n"
                    '                Resource: "*"',
                    template,
                )
                self.assertIn("ecr:PutLifecyclePolicy", template)


if __name__ == "__main__":
    unittest.main()
