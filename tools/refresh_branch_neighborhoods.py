"""Rebuild reviewed neighborhood pages locally; never commit, push or deploy."""
from pathlib import Path
import argparse
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', action='store_true', help='Run the current independent improvement audit after generation.')
    args = parser.parse_args()
    if (ROOT / 'tools/data/branch-grades/pages.json').exists():
        parameters = ['--audit'] if args.audit else []
        subprocess.run([sys.executable, str(ROOT / 'tools/refresh_branch_hierarchy.py'), *parameters], cwd=ROOT, check=True)
        return
    commands = [
        ['reconcile_branch_legacy_scope.py', '--apply'],
        ['generate_branch_neighborhood_pages.py'],
        ['generate_discovery_files.py'],
    ]
    if args.audit:
        commands.append(['audit_branch_improvements.py'])
    for script, *parameters in commands:
        subprocess.run([sys.executable, str(ROOT / 'tools' / script), *parameters], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
