#!/usr/bin/env bash
# Shared fail-closed checks for production serverless deployment entry points.

serverless_production_guard() {
  local repo_root expected_commit actual_commit dirty untracked
  repo_root="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"

  [ -n "${SERVERLESS_PRODUCTION_RELEASE_COMMIT:-}" ] || {
    echo "SERVERLESS_PRODUCTION_RELEASE_COMMIT is required." >&2
    return 2
  }
  actual_commit="$(git -C "$repo_root" rev-parse HEAD)"
  expected_commit="$SERVERLESS_PRODUCTION_RELEASE_COMMIT"
  if [ "$actual_commit" != "$expected_commit" ]; then
    echo "Release commit mismatch: checkout $expected_commit before deploying production." >&2
    return 2
  fi
  dirty="$(git -C "$repo_root" status --porcelain --untracked-files=all)"
  untracked="$(git -C "$repo_root" ls-files --others --exclude-standard)"
  # A Windows checkout inspected by WSL can report every CRLF file as changed.
  # Keep the guard fail-closed for staged, untracked, and semantic changes while
  # allowing line-ending-only noise that `--ignore-space-at-eol` proves harmless.
  if [ -n "$untracked" ] || \
     ! git -C "$repo_root" diff --cached --quiet || \
     ! git -C "$repo_root" diff --ignore-space-at-eol --quiet; then
    echo "Refusing production deployment from a dirty worktree." >&2
    echo "$dirty" >&2
    return 2
  fi

  for value in \
    "${SERVERLESS_PRODUCTION_FOUNDATION_STACK:-mopa-rasterizer-serverless-production}" \
    "${SERVERLESS_PRODUCTION_WORKER_STACK:-mopa-rasterizer-serverless-production-worker}" \
    "${SERVERLESS_PRODUCTION_ORCHESTRATION_STACK:-mopa-rasterizer-serverless-production-orchestration}" \
    "${SERVERLESS_PRODUCTION_WEB_STACK:-mopa-rasterizer-serverless-production-web}"; do
    case "$value" in
      *staging*) echo "Refusing staging-named production resource: $value" >&2; return 2 ;;
    esac
  done
}
