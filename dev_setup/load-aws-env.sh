#!/usr/bin/env bash
# Load workstation-specific AWS deployment identifiers without committing them.

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "Source this helper from another script; do not execute it directly." >&2
  exit 2
fi

AWS_ENV_REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_ENV_FILE="${AWS_ENV_FILE:-$AWS_ENV_REPO_ROOT/.env.aws}"

if [ -f "$AWS_ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090 -- this is an explicitly selected local config.
  source "$AWS_ENV_FILE"
  set +a
fi

unset AWS_ENV_REPO_ROOT

# Prefer short-lived credentials supplied by CI, ECS, or another AWS credential
# provider. Fall back to the workstation SSO profile when no ambient credentials
# are present. This keeps the same deployment scripts usable both locally and in
# GitHub Actions without storing long-lived AWS keys in GitHub.
configure_aws_deployment_credentials() {
  if [ -n "${AWS_ACCESS_KEY_ID:-}" ] || [ -n "${AWS_WEB_IDENTITY_TOKEN_FILE:-}" ] || \
      [ -n "${AWS_CONTAINER_CREDENTIALS_RELATIVE_URI:-}" ] || \
      [ -n "${AWS_CONTAINER_CREDENTIALS_FULL_URI:-}" ]; then
    unset AWS_PROFILE AWS_DEFAULT_PROFILE
    return
  fi

  export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-${AWS_PROFILE:-mopa-admin}}"
}
