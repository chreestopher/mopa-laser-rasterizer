#!/usr/bin/env bash
set -euo pipefail

LOCAL_PORT="${K3S_LOCAL_PORT:-16443}"
FORWARD_TARGET="${LOCAL_PORT}:127.0.0.1:6443"

mapfile -t tunnel_pids < <(pgrep -f "^ssh .*[-]L ${FORWARD_TARGET}( |$)" || true)

if [ "${#tunnel_pids[@]}" -eq 0 ]; then
  echo "K3s tunnel is not running on local port ${LOCAL_PORT}."
  exit 0
fi

kill "${tunnel_pids[@]}"

for pid in "${tunnel_pids[@]}"; do
  for _ in 1 2 3 4 5; do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.2
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "Tunnel process ${pid} did not stop normally." >&2
    exit 1
  fi
done

echo "K3s tunnel stopped. The remote cluster and its workloads are still running."
