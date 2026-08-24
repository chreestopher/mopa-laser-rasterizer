#!/usr/bin/env bash
set -euo pipefail

WINDOWS_USER="${WINDOWS_USER:-chree}"
WINDOWS_AWS_DIR="/mnt/c/Users/${WINDOWS_USER}/.aws"

if ! command -v aws >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y curl unzip

  installer_dir="$(mktemp -d)"
  trap 'rm -rf "$installer_dir"' EXIT
  curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip \
    -o "$installer_dir/awscliv2.zip"
  unzip -q "$installer_dir/awscliv2.zip" -d "$installer_dir"
  sudo "$installer_dir/aws/install"
else
  echo "AWS CLI is already installed; leaving it in place."
fi

if [[ ! -d "$WINDOWS_AWS_DIR" ]]; then
  echo "Windows AWS configuration was not found at $WINDOWS_AWS_DIR." >&2
  echo "Run 'aws configure sso --profile mopa-admin' inside WSL." >&2
  exit 1
fi

if [[ -e "$HOME/.aws" && ! -L "$HOME/.aws" ]]; then
  echo "$HOME/.aws already exists and is not a symbolic link; leaving it unchanged." >&2
  echo "Set AWS_CONFIG_FILE and AWS_SHARED_CREDENTIALS_FILE manually if needed." >&2
  exit 1
fi

ln -sfn "$WINDOWS_AWS_DIR" "$HOME/.aws"

echo
aws --version
echo "WSL now uses the AWS configuration at $WINDOWS_AWS_DIR."
echo "Verifying the active AWS identity..."
echo "Authenticate the deployment profile with:"
echo "  aws sso login --profile mopa-admin --use-device-code"
echo "Then verify it with:"
echo "  aws sts get-caller-identity --profile mopa-admin"
