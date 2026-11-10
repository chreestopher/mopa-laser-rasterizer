#!/usr/bin/env python3
"""Classify a revision range into the serverless components it can affect.

The classifier is deliberately fail-safe: paths that are not explicitly known
to be deployment-neutral select both components.  This lets documentation,
tests, and standalone infrastructure changes avoid an application deployment
without allowing a newly added runtime file to be silently ignored.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath


ZERO_REVISION = "0" * 40

WEB_PREFIXES = (
    "serverless_api/",
    "serverless_web/",
    "static/",
    "templates/",
)
WORKER_PREFIXES = ("lib/",)
BOTH_PREFIXES = ("routes/",)

WEB_EXACT = {
    "docs/changelog.json",
    "ecs/serverless-staging-web.yaml",
    "dev_setup/apply_cognito_managed_branding.sh",
    "dev_setup/deploy_serverless_production_web.sh",
    "dev_setup/deploy_serverless_staging_web.sh",
}
WORKER_EXACT = {
    ".dockerignore",
    "Dockerfile",
    "app.py",
    "job_runtime.py",
    "requirements.txt",
    "services.py",
    "worker.py",
    "ecs/rasterizer-orchestration.yaml",
    "ecs/rasterizer-worker.yaml",
    "dev_setup/deploy_serverless_production.sh",
    "dev_setup/deploy_serverless_staging.sh",
    "dev_setup/deploy_serverless_staging_worker_only.sh",
    "dev_setup/ensure-s3-fargate-dispatch.sh",
    "dev_setup/remove-s3-fargate-dispatch.sh",
}
BOTH_EXACT = {
    ".github/workflows/deploy-serverless-production.yml",
    ".github/workflows/deploy-serverless-staging.yml",
    "dev_setup/deploy_serverless_production_release.sh",
    "dev_setup/deploy_serverless_staging_release.sh",
    "dev_setup/load-aws-env.sh",
}

NEUTRAL_PREFIXES = (
    ".agents/",
    ".github/",
    ".vscode/",
    "docs/",
    "ecs/",
    "experiments/",
    "outputs/",
    "scratch/",
    "serverless_backup/",
    "serverless_cost_guard/",
    "test-assets/",
    "tests/",
    "uploads/",
)
NEUTRAL_EXACT = {
    ".env.aws.example",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "README.md",
    "mopa-laser-rasterizer-release-post-rewrite-draft.md",
    "requirements-dev.txt",
    "run-cli.sh",
    "run-sample.sh",
    "test-input.png",
}


@dataclass(frozen=True)
class DeploymentSelection:
    worker: bool
    web: bool
    fallback_paths: tuple[str, ...] = ()

    @property
    def any(self) -> bool:
        return self.worker or self.web


def _normalize(path: str) -> str:
    normalized = PurePosixPath(path.replace("\\", "/")).as_posix()
    return normalized[2:] if normalized.startswith("./") else normalized


def classify(paths: list[str] | tuple[str, ...]) -> DeploymentSelection:
    worker = False
    web = False
    fallback_paths: list[str] = []

    for raw_path in paths:
        path = _normalize(raw_path.strip())
        if not path:
            continue
        if path in BOTH_EXACT or path.startswith(BOTH_PREFIXES):
            worker = True
            web = True
            continue
        if path in WEB_EXACT or path.startswith(WEB_PREFIXES) or path.startswith("dev_setup/build_serverless_"):
            web = True
            continue
        if path in WORKER_EXACT or path.startswith(WORKER_PREFIXES):
            worker = True
            continue
        if path in NEUTRAL_EXACT or path.startswith(NEUTRAL_PREFIXES):
            continue

        # A new or unfamiliar path may be runtime-sensitive.  Deploy both until
        # it is deliberately assigned above.
        worker = True
        web = True
        fallback_paths.append(path)

    return DeploymentSelection(worker, web, tuple(fallback_paths))


def changed_paths(base: str, head: str) -> list[str]:
    if not base or base == ZERO_REVISION:
        try:
            base = subprocess.check_output(
                ["git", "rev-parse", f"{head}^"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except subprocess.CalledProcessError:
            return subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    return subprocess.check_output(
        ["git", "diff", "--name-only", f"{base}..{head}"], text=True
    ).splitlines()


def emit(selection: DeploymentSelection, paths: list[str]) -> None:
    print(f"worker={'true' if selection.worker else 'false'}")
    print(f"web={'true' if selection.web else 'false'}")
    print(f"any={'true' if selection.any else 'false'}")
    print(f"changed_count={len(paths)}")
    if selection.fallback_paths:
        print("classification=fail-safe-full")
        print(
            "Unclassified paths selected a fail-safe full deployment: "
            + ", ".join(selection.fallback_paths),
            file=sys.stderr,
        )
    elif selection.any:
        print("classification=targeted")
    else:
        print("classification=no-application-deploy")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--target", choices=("web-api", "worker", "release"))
    arguments = parser.parse_args()

    if arguments.target:
        paths = [f"manual:{arguments.target}"]
        selection = DeploymentSelection(
            worker=arguments.target in {"worker", "release"},
            web=arguments.target in {"web-api", "release"},
        )
    else:
        if not arguments.base:
            parser.error("--base is required unless --target is supplied")
        paths = changed_paths(arguments.base, arguments.head)
        selection = classify(paths)

    emit(selection, paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
