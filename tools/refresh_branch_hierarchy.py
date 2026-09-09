"""Regenerate the registered grade -> neighborhood -> center hierarchy locally."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(name, *args):
    subprocess.run([sys.executable, str(ROOT / 'tools' / name), *args], cwd=ROOT, check=True)


def audit_script(grades, revision=None):
    """Use the approved checkpoint for the entire registered grade inventory."""
    grades = set(grades)
    if revision is not None:
        if revision == '2026-09-10-reader-v1' and grades == {'초5', '초6', '중1', '중2', '중3', '고1', '고2'}:
            return 'audit_branch_grade_improvements.py'
        raise ValueError('No reviewed audit checkpoint for editorial revision and grade inventory')
    if grades == {'초5', '초6', '중1', '중2', '중3', '고1', '고2'}:
        return 'audit_branch_elementary_pages.py'
    if grades == {'중1', '중2', '중3', '고1', '고2'}:
        return 'audit_branch_middle_pages.py'
    if grades == {'고1', '고2'}:
        return 'audit_branch_high1_pages.py'
    if grades == {'고2'}:
        return 'audit_branch_high2_pages.py'
    if not grades:
        return 'audit_branch_pages.py'
    raise ValueError('No reviewed audit checkpoint for grades: ' + ', '.join(sorted(grades)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    manifest = ROOT / 'tools/data/branch-grades/pages.json'
    grades = sorted({r['grade'] for r in json.loads(manifest.read_text(encoding='utf-8')).get('archives', [])}) if manifest.exists() else []
    from generate_branch_grade_pages import EDITORIAL_REVISION
    audit = audit_script(grades, revision=EDITORIAL_REVISION if grades else None) if args.audit else None
    for grade in grades:
        run('generate_branch_grade_pages.py', '--grade', grade)
    run('generate_branch_neighborhood_pages.py')
    run('generate_branch_pages.py')
    run('generate_discovery_files.py')
    if audit:
        run(audit)


if __name__ == '__main__':
    main()
