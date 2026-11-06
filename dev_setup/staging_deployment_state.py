#!/usr/bin/env python3
"""Staging-only component deployment markers; production uses its existing flow."""
import argparse
import subprocess
import sys

try:
    from .classify_serverless_deployment_changes import DeploymentSelection, classify, changed_paths, emit
except ImportError:
    from classify_serverless_deployment_changes import DeploymentSelection, classify, changed_paths, emit

REFS = {component: f'refs/tags/staging-deployed-{component}' for component in ('web', 'worker')}


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def remote_marker(component):
    # ls-remote failures are errors, not evidence that a marker is missing.
    output = git('ls-remote', '--refs', 'origin', REFS[component])
    if not output:
        return None
    sha = output.split()[0]
    git('fetch', '--no-tags', 'origin', sha)
    return sha


def baseline_paths(base, head):
    valid = subprocess.run(['git', 'merge-base', '--is-ancestor', base, head], capture_output=True)
    if valid.returncode != 0:
        print(f'Cannot use non-ancestor baseline {base}; selecting conservatively.', file=sys.stderr)
        return ['unknown-deployment-baseline']
    return changed_paths(base, head)


def select_components(baselines, head, diff=baseline_paths):
    selected = {}
    fallback = []
    for component in REFS:
        base = baselines.get(component)
        if not base:
            selected[component] = True
            print(f'No staging {component} deployment marker; deploying it.', file=sys.stderr)
        else:
            classification = classify(diff(base, head))
            selected[component] = getattr(classification, component)
            fallback.extend(classification.fallback_paths)
    return DeploymentSelection(worker=selected['worker'], web=selected['web'], fallback_paths=tuple(sorted(set(fallback))))


def record(component, head):
    head = git('rev-parse', f'{head}^{{commit}}')
    previous = remote_marker(component)
    if previous == head:
        return
    if previous and subprocess.run(['git', 'merge-base', '--is-ancestor', previous, head], capture_output=True).returncode != 0:
        raise RuntimeError(f'Refusing to move staging {component} marker backwards or across rewritten history.')
    ref = REFS[component]
    # Do not overwrite a marker changed by another writer after our read.
    git('push', f'--force-with-lease={ref}:{previous or ""}', 'origin', f'{head}:{ref}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['select', 'record', 'verify-head'])
    parser.add_argument('--head', required=True)
    parser.add_argument('--component', choices=list(REFS))
    args = parser.parse_args()
    if args.action == 'verify-head':
        selected = git('rev-parse', f'{args.head}^{{commit}}')
        current = git('ls-remote', '--refs', 'origin', 'refs/heads/staging').split()
        if not current or current[0] != selected:
            raise RuntimeError('This run is no longer the staging tip; deploy the latest staging revision instead.')
    elif args.action == 'record':
        if not args.component:
            parser.error('--component is required for record')
        record(args.component, args.head)
    else:
        baselines = {component: remote_marker(component) for component in REFS}
        for component, baseline in baselines.items():
            print(f'{component}_baseline={baseline or "missing"}')
        selection = select_components(baselines, args.head)
        paths = set()
        for baseline in baselines.values():
            if baseline:
                paths.update(baseline_paths(baseline, args.head))
        emit(selection, sorted(paths))


if __name__ == '__main__':
    main()
