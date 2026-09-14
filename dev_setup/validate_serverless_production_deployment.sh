#!/usr/bin/env bash
# Local-only validation. This script makes no AWS calls and performs no deployment.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"

scripts=(
  "$SCRIPT_DIR/deploy_serverless_staging.sh"
  "$SCRIPT_DIR/deploy_serverless_staging_web.sh"
  "$SCRIPT_DIR/serverless-production-guard.sh"
  "$SCRIPT_DIR/deploy_serverless_production.sh"
  "$SCRIPT_DIR/deploy_serverless_production_web.sh"
  "$SCRIPT_DIR/deploy_serverless_production_application.sh"
  "$SCRIPT_DIR/ensure_dynamodb_job_ttl.sh"
  "$SCRIPT_DIR/inspect_serverless_production_readiness.sh"
)
for script in "${scripts[@]}"; do
  bash -n "$script"
done

python3 - "$REPO_ROOT" <<'PY'
from pathlib import Path
import sys
import yaml

root = Path(sys.argv[1])


class CloudFormationLoader(yaml.SafeLoader):
    pass


def construct_intrinsic(loader, _tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


CloudFormationLoader.add_multi_constructor("!", construct_intrinsic)
for template_path in (
    root / "ecs/serverless-production-foundation.yaml",
    root / "ecs/serverless-staging-web.yaml",
    root / "ecs/rasterizer-worker.yaml",
    root / "ecs/rasterizer-orchestration.yaml",
):
    with template_path.open(encoding="utf-8") as stream:
        template = yaml.load(stream, Loader=CloudFormationLoader)
    if not isinstance(template, dict) or "Resources" not in template:
        raise SystemExit(f"Invalid CloudFormation document: {template_path}")
    print(f"PASS: YAML structure {template_path.relative_to(root)}")

foundation = (root / "ecs/serverless-production-foundation.yaml").read_text(encoding="utf-8")
web = (root / "ecs/serverless-staging-web.yaml").read_text(encoding="utf-8")
worker = (root / "dev_setup/deploy_serverless_production.sh").read_text(encoding="utf-8")
application = (root / "dev_setup/deploy_serverless_production_application.sh").read_text(encoding="utf-8")

checks = {
    "production foundation reuses named durable stores": (
        "ArtifactBucketName" in foundation and "RuntimeTableName" in foundation
    ),
    "production foundation creates isolated queues": (
        "mopa-rasterizer-serverless-production-jobs" in foundation
        and "mopa-rasterizer-serverless-production-jobs-dlq" in foundation
    ),
    "web template supports two production aliases": "AlternateHostname" in web,
    "web template parameterizes resource names": (
        "DeploymentName" in web and "ApiFunctionName" in web
    ),
    "production forbids local worker builds": "SERVERLESS_ALLOW_LOCAL_IMAGE_BUILD=false" in worker,
    "production requires immutable image digest": "@sha256:" in worker,
    "application deployment is sequential": (
        application.index("deploy_serverless_production.sh")
        < application.index("deploy_serverless_production_web.sh")
    ),
}
failed = [name for name, passed in checks.items() if not passed]
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}: {name}")
if failed:
    raise SystemExit("Production deployment validation failed: " + ", ".join(failed))
PY

echo "Local production deployment validation passed. No AWS resources were contacted or changed."
