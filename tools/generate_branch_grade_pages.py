"""Generate supplied grade manuscripts under existing neighborhood pages locally.

No guessed parents, source replacement, publication, or deletion of older grades.
The grade manifest is also the source of parent-page child navigation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil

from branch_grade_manuscripts import load_grade_archive, prepare_grade_manuscript
from branch_reader_facts import _confirmed_grades
from generate_branch_neighborhood_pages import render, sha
from generate_branch_pages import ROOT, DATA as BRANCH_DATA, load_branch_data, branch_path, write_changed

DATA = ROOT / 'tools/data/branch-grades'
REPORTS = ROOT / 'reports/branch-grades'
PARENTS = ROOT / 'tools/data/branch-neighborhoods/pages.json'
SOURCE = Path('C:/Users/1992k/Desktop/프로그램 원고')
GRADE_PATTERN = re.compile(r'(?:초[1-6]|중[1-3]|고[1-3])')
EDITORIAL_REVISION = '2026-09-10-reader-v1'


def selected_subjects(subject=None):
    if subject is not None and subject not in ('영어', '수학'):
        raise ValueError('Subject must be 영어 or 수학')
    return (subject,) if subject else ('수학', '영어')


def keep_other_groups(rows, grade, subjects):
    """A subject-only run must never remove its same-grade sibling subject."""
    return [r for r in rows if (r['grade'], r['subject']) not in {(grade, s) for s in subjects}]


def merge_archives(existing, updated):
    """Keep original archive order, identity and snapshots during a revision."""
    replacements = {(r['grade'], r['subject']): r for r in updated}
    if len(replacements) != len(updated):
        raise ValueError('Duplicate archive groups')
    result = [replacements.pop((r['grade'], r['subject']), r) for r in existing]
    return result + list(replacements.values())


def grade_path(parent, grade):
    if not GRADE_PATTERN.fullmatch(grade):
        raise ValueError('Unsupported grade slug')
    path = parent['path']
    parts = path.strip('/').split('/')
    if (not path.startswith('/지점안내/') or not path.endswith('/') or len(parts) != 4
            or parts[-1] != parent['locality'] + parent['subject'] + '학원'
            or any(part in ('', '.', '..') or re.search(r'[\\?#\x00-\x1f]', part) for part in parts)):
        raise ValueError(f'Invalid reviewed parent route: {path}')
    return path + grade + '/'


def source_snapshot(grade, subject):
    name = grade + ' ' + subject + '학원.zip'
    original, saved = SOURCE / name, DATA / 'sources' / name
    if saved.exists():
        if original.exists() and sha(original) != sha(saved):
            raise ValueError(f'Changed source archive requires review: {name}')
    else:
        if not original.is_file():
            raise FileNotFoundError(original)
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, saved)
    return saved


def grade_school_row(row, grade):
    level = {'초': 'elementary', '중': 'middle', '고': 'high'}[grade[0]]
    result = deepcopy(row)
    names = row.get('targetSchools', {}).get(level, [])
    result['targetSchools'] = {level: list(names)} if names else {}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grade', default='고2')
    parser.add_argument('--subject', choices=('영어', '수학'), help='Review one 371-page topic without replacing the other subject')
    args = parser.parse_args()
    grade = args.grade
    subjects = selected_subjects(args.subject)
    if not GRADE_PATTERN.fullmatch(grade):
        raise ValueError('Grade must be 초1~초6, 중1~중3, or 고1~고3')
    parents = json.loads(PARENTS.read_text(encoding='utf-8'))['pages']
    by_key = {(p['locality'], p['subject']): p for p in parents}
    if len(by_key) != len(parents):
        raise ValueError('Ambiguous existing neighborhood parents')
    _, centers, references = load_branch_data()
    centers = {c['id']: c for c in centers}
    schools = {r['neighborhood']: r for r in json.loads((BRANCH_DATA / 'target-schools.json').read_text(encoding='utf-8'))}
    old = json.loads((DATA / 'pages.json').read_text(encoding='utf-8')) if (DATA / 'pages.json').exists() else {'pages': []}
    old_paths = {r['path'] for r in old['pages']}
    from branch_grade_editorial import apply_reviewed_edits
    from branch_grade_reading import improve_grade_reading
    plan, changes, archives, reading_records = [], [], [], []
    for subject in subjects:
        archive = source_snapshot(grade, subject)
        originals = load_grade_archive(archive, subject, grade)
        if len(originals) != 371:
            raise ValueError(f'{grade} {subject}: expected 371 manuscripts, got {len(originals)}')
        expected = {p['locality'] for p in parents if p['subject'] == subject}
        if {r['locality'] for r in originals} != expected:
            raise ValueError(f'{grade} {subject}: manuscripts and reviewed parents differ')
        archives.append({'grade': grade, 'subject': subject, 'path': str(archive.relative_to(ROOT)), 'sha256': sha(archive), 'count': len(originals)})
        for original in originals:
            manuscript, edits = prepare_grade_manuscript(original)
            for field in ('title', 'meta', 'locality', 'subject', 'grade', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256'):
                if manuscript[field] != original[field]:
                    raise ValueError(f'Protected manuscript field changed: {field}')
            manuscript, reviewed_edits = apply_reviewed_edits(manuscript)
            manuscript, reading_edits, reading_points = improve_grade_reading(manuscript)
            for field in ('title', 'locality', 'subject', 'grade', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256'):
                if manuscript[field] != original[field]:
                    raise ValueError(f'Protected identity changed in reviewed revision: {field}')
            edits = edits + reviewed_edits + [dict(edit, stage='reading-editorial') for edit in reading_edits]
            changes.extend(dict(edit, locality=original['locality'], subject=subject, grade=grade,
                                sourceMember=original['sourceMember']) for edit in edits)
            parent = by_key[(original['locality'], subject)]
            center = centers[parent['centerId']]
            reference = references['centers'][center['id']]
            if parent['parentPath'] != branch_path(center) or not (ROOT / parent['path'].strip('/') / 'index.html').is_file():
                raise ValueError(f'Missing or mismatched parent: {parent["path"]}')
            media = reference.get('primaryMedia', {})
            if not media.get('body') or not media.get('map'):
                raise ValueError(f'Missing approved media: {center["sourceCenterName"]}')
            destination = grade_path(parent, grade)
            disk = (ROOT / destination.strip('/') / 'index.html').resolve()
            parent_disk = (ROOT / parent['path'].strip('/')).resolve()
            if not disk.is_relative_to(parent_disk) or not disk.is_relative_to((ROOT / '지점안내').resolve()):
                raise ValueError('Grade destination escaped reviewed parent')
            if disk.exists() and destination not in old_paths:
                raise ValueError(f'Refusing to overwrite unrelated page: {disk}')
            rep = dict(parent['representative'])
            if sha(ROOT / rep['src'].lstrip('/')) != rep['sha256']:
                raise ValueError('Parent representative image hash mismatch')
            record = {key: manuscript[key] for key in ('locality', 'subject', 'grade', 'title', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256')}
            record.update({'path': destination, 'parentPath': parent['path'], 'parentTitle': parent['title'],
                           'centerId': center['id'], 'centerPath': branch_path(center), 'representative': rep,
                           'scopeConfirmed': grade in _confirmed_grades(center, reference, subject),
                           'sectionCount': len(manuscript['sections']), 'faqCount': len(manuscript['faq']),
                           'editorialRevision': EDITORIAL_REVISION})
            reading_records.append({'path': destination, 'grade': grade, 'subject': subject,
                                    'locality': manuscript['locality'], 'readingPoints': reading_points})
            plan.append((record, manuscript, center, reference, disk, reading_points))
    records = [r for r, *_ in plan]
    if len({r['path'] for r in records}) != len(records):
        raise ValueError('Duplicate grade destinations')
    prior_grade = {r['path'] for r in old['pages'] if r['grade'] == grade and r['subject'] in subjects}
    if prior_grade - {r['path'] for r in records}:
        raise ValueError('Existing grade pages would be orphaned')
    other_grades = keep_other_groups(old['pages'], grade, subjects)
    merged = sorted(other_grades + records, key=lambda r: (r['parentPath'], r['grade']))
    rendered = []
    for record, manuscript, center, reference, disk, reading_points in plan:
        siblings = [r for r in merged if r['centerId'] == center['id'] and r['grade'] == grade]
        school = grade_school_row(schools.get(record['locality'], {}), grade)
        context = dict(record, readingPoints=reading_points)
        path, html = render(center, reference, manuscript, record['representative'], school, siblings, page_context=context)
        if path != record['path']:
            raise ValueError('Renderer changed planned route')
        rendered.append((disk, html))
    changed = sum(write_changed(disk, html) for disk, html in rendered)
    manifest = {'version': 1, 'parentManifestSha256': sha(PARENTS),
                'archives': merge_archives(old.get('archives', []), archives), 'pages': merged}
    if all(r.get('editorialRevision') == EDITORIAL_REVISION for r in merged):
        manifest['editorialRevision'] = EDITORIAL_REVISION
    write_changed(DATA / 'pages.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    report = {'status': 'COMPLETE', 'grade': grade, 'generatedPages': len(records), 'changedPages': changed,
              'bySubject': dict(Counter(r['subject'] for r in records)), 'parentPages': len({r['parentPath'] for r in records}),
              'parentCenters': len({r['centerId'] for r in records}),
              'scopeConfirmed': sum(r['scopeConfirmed'] for r in records),
              'scopeConfirmationNeeded': [r['path'] for r in records if not r['scopeConfirmed']],
              'archives': archives, 'editorialChanges': len(changes), 'editorialRevision': EDITORIAL_REVISION,
              'reviewedChanges': len([c for c in changes if c.get('stage') == 'reviewed-editorial']),
              'readingChanges': len([c for c in changes if c.get('stage') == 'reading-editorial']),
              'pagesWithReadingPoints': sum(bool(r['readingPoints']) for r in reading_records),
              'deployment': 'NOT DEPLOYED - local only'}
    # Keep every earlier generation/editorial checkpoint intact.
    report_dir = REPORTS / 'improvements'
    report_name = grade + '-' + (args.subject or '전체')
    write_changed(report_dir / (report_name + '-generation.json'), json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    write_changed(report_dir / (report_name + '-editorial.json'), json.dumps({'changes': changes}, ensure_ascii=False, indent=2) + '\n')
    write_changed(report_dir / (report_name + '-reading.json'), json.dumps({'pages': reading_records}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('scopeConfirmationNeeded', 'archives')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
