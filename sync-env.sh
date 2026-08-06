#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"
K8S_DIR="$ROOT_DIR/k8s"

if [[ ! -f "$ROOT_DIR/.env.local" ]]; then
  echo "Error: $ROOT_DIR/.env.local does not exist." >&2
  exit 1
fi

# Generate the deployment manifest from the template using root env vars.
export ROOT_DIR
python3 <<'PY'
from pathlib import Path
import os

root = Path(os.environ['ROOT_DIR'])

env = {}
for line in (root / '.env.local').read_text().splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    if '=' not in line:
        continue
    k, v = line.split('=', 1)
    env[k.strip()] = v.strip()

template_path = root / 'k8s' / 'deployment.yaml.template'
output_path = root / 'k8s' / 'deployment.yaml'
text = template_path.read_text()
for key, value in env.items():
    text = text.replace('${' + key + '}', value)
output_path.write_text(text)
print(f"Generated {output_path}")
PY

echo "Synced root .env.local into k8s/deployment.yaml from template"
