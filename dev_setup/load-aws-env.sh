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
