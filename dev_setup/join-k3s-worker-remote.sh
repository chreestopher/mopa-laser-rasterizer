#!/usr/bin/env bash
# Runs on a new Linux EC2 instance. The k3s token is read from stdin so it is
# not exposed in the remote command line or written to the repository.
set -euo pipefail
trap 'status=$?; echo "k3s worker bootstrap failed at line ${LINENO} (exit ${status})." >&2' ERR

if [ "$#" -ne 2 ]; then
  echo "Usage: join-k3s-worker-remote.sh <https://server-private-ip:6443> <node-name>" >&2
  exit 2
fi

K3S_URL="$1"
NODE_NAME="$2"
IFS= read -r K3S_TOKEN

if [ -z "$K3S_TOKEN" ]; then
  echo "No k3s join token was supplied on stdin." >&2
  exit 2
fi

export K3S_URL K3S_TOKEN
export INSTALL_K3S_EXEC="agent --node-name ${NODE_NAME}"

if command -v k3s >/dev/null 2>&1 && systemctl is-active --quiet k3s-agent; then
  echo "k3s agent is already running on ${NODE_NAME}."
else
  echo "Installing k3s agent for ${NODE_NAME} and joining ${K3S_URL}"
  if [ -s /tmp/k3s ] && [ -s /tmp/install-k3s.sh ]; then
    install -m 0755 /tmp/k3s /usr/local/bin/k3s
    INSTALL_K3S_SKIP_DOWNLOAD=true sh /tmp/install-k3s.sh
  else
    echo "Offline k3s installer files were not provided." >&2
    exit 2
  fi
fi

unset K3S_TOKEN
systemctl enable k3s-agent >/dev/null
systemctl restart k3s-agent
rm -f /tmp/k3s /tmp/install-k3s.sh
echo "k3s agent started; showing service status"
systemctl --no-pager --full status k3s-agent | sed -n '1,12p'
