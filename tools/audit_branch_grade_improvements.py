"""Independent exact-log and pre-improvement preservation checks; no rendering."""
from __future__ import annotations

import argparse
from collections import Counter
import ast
import copy
from datetime import datetime, timezone
from functools import lru_cache
import gzip
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from audit_branch_elementary_pages import graph, read, scoped_grades, sha, url

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path('C:/Users/1992k/Desktop/CodexData/tmp/site15-grade-improvement-2026-09-10/before.json.gz')
REPORTS = ROOT / 'reports/branch-grades'
REVISION = '2026-09-10-reader-v1'
EDITORIAL_MANIFEST = ROOT / 'tools/data/branch-grades/editorial-revision-2026-09-10.json'
FINGERPRINTS = {
    'tools/branch_grade_editorial.py': '9b1bd5ea6494b08616ec8452bddf7b1ae15b743519fcc4f8f967ad29ed65f27e',
    'tools/branch_grade_reading.py': 'a7802270f3b791f1c9e1dd030d52b58b1d957782a7073135742a88967756af26',
    'tools/data/branch-grades/editorial-revision-2026-09-10.json': '45f05d4ca61ed20335eb5f070e82e739be590027a1f86627d3e4c3fa483d0059',
    'assets/branch-grades.css': 'e297bfb9d500452f13ebe92e27bba6c2a2ba031b8548f41c5080f8a44df4b7d2',
}
FIELD = re.compile(r'meta|intro|sections\[\d+\]\.(?:heading|paragraphs\[\d+\])|faq\[\d+\]\.(?:question|answer)|cases\[\d+\]')


def identity(record):
    return (record['locality'], record['subject'], record['grade'])


def content(soup):
    return {
        'title': soup.h1.get_text(),
        'meta': soup.select_one('meta[name="description"]')['content'],
        'intro': soup.select_one('.branch-manuscript-intro').get_text(),
        'sections': [{'heading': node.h2.get_text(),
                      'paragraphs': [' '.join(p.get_text() for p in u.select('p.branch-manuscript-paragraph'))
                                     for u in node.select('.branch-manuscript-unit')]}
                     for node in soup.select('section[id^="section-"]')],
        'faq': [{'question': n.summary.get_text(), 'answer': n.p.get_text()}
                for n in soup.select('#questions details')],
        'cases': [n.get_text() for n in soup.select('#consultation-example details.branch-reading-example p')],
    }


def field_container(record, field):
    if FIELD.fullmatch(field) is None:
        raise ValueError('Unapproved editable field: ' + field)
    tokens = [name if name else int(index) for name, index in re.findall(r'([A-Za-z]+)|\[(\d+)\]', field)]
    target = record
    for token in tokens[:-1]:
        target = target[token]
    return target, tokens[-1]


def replay_reviewed(original, edits):
    result = copy.deepcopy(original)
    seen = set()
    for edit in edits:
        field = edit['field']
        if field in seen:
            raise ValueError('Duplicate reviewed field: ' + field)
        seen.add(field)
        target, key = field_container(result, field)
        if target[key] != edit['before'] or not isinstance(edit['after'], str) or not edit['after'].strip():
            raise ValueError('Reviewed full-field before mismatch: ' + field)
        target[key] = edit['after']
    return result


def validate_points(points, prepared):
    """Quoted key points must be exact substrings of the named body paragraph."""
    for point in points:
        i, j = point['sectionIndex'], point['paragraphIndex']
        if type(i) is not int or type(j) is not int or i < 1 or j < 1:
            raise ValueError('Invalid point source coordinates')
        source = prepared['sections'][i - 1]['paragraphs'][j - 1]
        if not point['text'] or point['text'] not in source:
            raise ValueError('Reading point is not a literal excerpt of its named source')
    if len({p['text'] for p in points}) != len(points):
        raise ValueError('Duplicate reading points')
    return True


def check_manifest(current, baseline):
    original = json.loads(baseline['sourceFiles']['tools/data/branch-grades/pages.json']['text'])
    restored = copy.deepcopy(current)
    if restored.pop('editorialRevision', None) != REVISION:
        raise ValueError('Missing/wrong complete-manifest editorialRevision')
    for record in restored['pages']:
        if record.pop('editorialRevision', None) != REVISION:
            raise ValueError('Missing/wrong per-page editorialRevision')
    # Per-subject generation may reorder the unchanged archive records only.
    restored['archives'] = sorted(restored['archives'], key=lambda r: (r['grade'], r['subject']))
    original['archives'] = sorted(original['archives'], key=lambda r: (r['grade'], r['subject']))
    if restored != original:
        raise ValueError('Grade manifest changed beyond the revision marker')
    return True


def assert_immutable_inventory(baseline, manifest, check, counts):
    paths = {r['path'].strip('/') + '/index.html' for r in manifest['pages']}
    check(len(paths) == 5194, 'exact-improved-grade-inventory')
    for relative, old in baseline['pages'].items():
        if relative in paths:
            continue
        path = ROOT / relative
        check(path.is_file() and sha(path.read_bytes()) == old['sha256'], 'all-other-public-html-byte-preservation', relative)
        counts['unchangedOtherPublicHtml'] += 1
    check(counts['unchangedOtherPublicHtml'] == 3188, '3188-other-public-pages-including-742-parents')
    for relative, old in baseline['assets'].items():
        path = ROOT / relative
        check(path.is_file() and sha(path.read_bytes()) == old['sha256'], 'original-asset-byte-preservation', relative)
        counts['preservedOriginalAssets'] += 1
    for relative, old in baseline['sourceFiles'].items():
        if relative == 'tools/data/branch-grades/pages.json':
            continue
        path = ROOT / relative
        check(path.is_file() and sha(path.read_bytes()) == old['sha256'], 'original-data-or-zip-byte-preservation', relative)
        counts['preservedSourceFiles'] += 1
        counts['preservedGradeSourceZips'] += int(relative.startswith('tools/data/branch-grades/sources/') and relative.endswith('.zip'))
    check(counts['preservedGradeSourceZips'] == 14, 'all-fourteen-original-grade-zips-preserved')
    for name in ('branch_grade_manuscripts.py', 'polish_branch_manuscripts.py', 'branch_manuscripts.py', 'branch_reader_facts.py', 'branch_readability.py'):
        relative = 'tools/' + name
        check(sha((ROOT / relative).read_bytes()) == baseline['sourceCode'][relative]['sha256'], 'unchanged-legacy-preparation-or-facts-code', relative)


@lru_cache(maxsize=None)
def literal_regex(name):
    tree = ast.parse((ROOT / 'tools/branch_grade_reading.py').read_text(encoding='utf-8'))
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
    return re.compile(ast.literal_eval(assignment.value.args[0]))


def replay_reading(prepared, changes):
    result = copy.deepcopy(prepared)
    if len(changes) > 1:
        raise ValueError('At most one narrow introduction reading edit is allowed')
    for change in changes:
        before, after = change['before'], change['after']
        if change['field'] != 'intro' or result['intro'] != before or not before.startswith(after + ' '):
            raise ValueError('Reading edit must retain the exact introduction prefix')
        removed = before[len(after):].strip()
        if not 100 <= len(after) <= 260 or not after.endswith('.') or not literal_regex('_REDUNDANT_TAIL').fullmatch(removed):
            raise ValueError('Only the reviewed generic third consultation sentence may be removed')
        if literal_regex('_TAIL_PROTECTED').search(removed):
            raise ValueError('A concrete fact/example/condition was removed from the introduction')
        result['intro'] = after
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def markup_is(node, expected):
    return str(node) == str(BeautifulSoup(expected, 'html.parser').find())


def verify_and_restore(old, current, expected, record, points, confirmed):
    """Validate each allowed change then reverse it for a whole-DOM comparison."""
    before = BeautifulSoup(old, 'html.parser')
    after = BeautifulSoup(current, 'html.parser')
    original = content(before)
    require(content(after) == expected, 'Current copy differs from exact reviewed/reading log replay')
    require(after.h1.get_text() == record['title'] == before.h1.get_text(), 'H1/source title changed')
    require([n.attrs for n in after.select('img')] == [n.attrs for n in before.select('img')], 'Image order or attributes changed')
    require(str(after.select_one('.branch-primary-media')) == str(before.select_one('.branch-primary-media')), 'Image panels changed')
    require(after.body.get('class') == before.body.get('class') + ['branch-grade-page'], 'Unexpected grade body classes')
    after.body['class'] = before.body['class']
    css = after.select('link[href="/assets/branch-grades.css"]')
    require(len(css) == 1 and css[0].attrs == {'rel': ['stylesheet'], 'href': '/assets/branch-grades.css'}, 'Expected exactly one grade-only stylesheet')
    css[0].decompose()
    # Removing the injected link also removes exactly its immediately following newline.
    for extra in list(after.head.children):
        if getattr(extra, 'name', None) is None and str(extra) == '\n\n':
            extra.replace_with('\n')
    badge = after.select('.branch-grade-scope-badge')
    require(len(badge) == int(not confirmed), 'Scope badge count disagrees with actual grade scope')
    if badge:
        require(markup_is(badge[0], '<p class="branch-grade-scope-badge">학습 준비 안내 · 수업 개설 확인 필요</p>')
                and badge[0].find_previous_sibling() == after.h1, 'Wrong badge copy/location')
        badge[0].decompose()
    actions_before = before.select_one('.branch-reading-shortcuts')
    actions_after = after.select_one('.branch-reading-shortcuts')
    require(str(actions_before) == str(actions_after), 'Reading shortcut buttons or hrefs changed')
    require(actions_after.find_previous_sibling() == after.h1, 'Reading buttons are not directly after H1/badge')
    actions_before.decompose()
    actions_after.decompose()
    audience = [n for n in after.select('.branch-child-quick strong') if n.get_text() == '학습 안내 대상']
    require(len(audience) == 1 and audience[0].parent.get_text(' ', strip=True) == '학습 안내 대상 ' + record['grade'] + ' ' + record['subject'],
            'Exact grade/subject learning-audience label missing')
    audience[0].string = '학습 대상'
    aside = after.select('.branch-grade-takeaways')
    require(len(aside) == int(bool(points)), 'Point panel presence differs from reading manifest')
    if points:
        require(aside[0].attrs == {'class': ['branch-grade-takeaways'], 'aria-label': '본문 핵심'}
                and aside[0].find_previous_sibling() == after.select_one('.branch-manuscript-intro'), 'Point panel wrapper/location changed')
        require(aside[0].p.get_text() == '본문 핵심', 'Point label changed')
        actual_points = [{'text': n.get_text(), 'sectionIndex': int(n['data-source-section']),
                          'paragraphIndex': int(n['data-source-paragraph'])} for n in aside[0].select('ul li')]
        require(actual_points == points and 1 <= len(points) <= 2 and sum(len(p['text']) for p in points) <= 320,
                'Displayed reading points differ from bounded exact excerpts')
        expected_aside = '<aside class="branch-grade-takeaways" aria-label="본문 핵심"><p class="branch-grade-takeaways-label">본문 핵심</p><ul>'
        expected_aside += ''.join('<li data-source-section="' + str(p['sectionIndex']) + '" data-source-paragraph="'
                                 + str(p['paragraphIndex']) + '">' + escape(p['text']) + '</li>' for p in points)
        require(markup_is(aside[0], expected_aside + '</ul></aside>'), 'Unapproved reading point markup')
        for point in points:
            require(45 <= len(point['text']) <= 170 and point['text'].endswith('.'), 'Reading excerpt is not a bounded complete sentence')
            require(not literal_regex('_UNSAFE_CONTENT').search(point['text'])
                    and not literal_regex('_DEPENDENT').search(point['text'])
                    and not literal_regex('_FORMULA').search(point['text']), 'Unsafe/dependent excerpt was elevated into a summary')
        validate_points(points, expected)
        aside[0].decompose()
    other = after.select('#other-grades')
    require(len(other) == 1 and other[0].find_previous_sibling() == after.select_one('#questions'), 'Other-grade panel must directly follow FAQ')
    require(other[0].h2.get_text() == '같은 동네의 다른 학년 안내'
            and other[0].p.get_text() == record['locality'] + ' ' + record['subject'] + '의 다른 학년 안내를 찾고 계신가요?',
            'Other-grade panel heading/copy changed')
    links = other[0].select('a')
    require(len(links) == 1 and links[0].get('href') == record['parentPath'] + '#child-pages'
            and links[0].get_text() == '다른 학년 보기', 'Other-grade target must be the real parent grade buttons')
    expected_other = '<section class="branch-panel" id="other-grades"><h2>같은 동네의 다른 학년 안내</h2><p class="">'
    expected_other += escape(record['locality'] + ' ' + record['subject'] + '의 다른 학년 안내를 찾고 계신가요?')
    expected_other += '</p><div class="branch-actions"><a class="branch-button secondary" href="' + escape(record['parentPath'] + '#child-pages')
    require(markup_is(other[0], expected_other + '">다른 학년 보기</a></div></section>'), 'Unapproved other-grade panel markup')
    other[0].decompose()
    toc_link = after.select('#article-toc a[href="#other-grades"]')
    require(len(toc_link) == 1 and toc_link[0].get_text() == '같은 동네의 다른 학년'
            and toc_link[0].find_previous_sibling().get('href') == '#questions', 'Other-grade TOC link is not immediately after FAQ')
    require(toc_link[0].attrs == {'href': '#other-grades'}, 'Unexpected other-grade TOC attributes')
    toc_link[0].decompose()
    # Metadata fields may change only through the explicit reviewed meta field.
    for selector in ('meta[name="description"]', 'meta[property="og:description"]', 'meta[name="twitter:description"]'):
        require(after.select_one(selector)['content'] == expected['meta'], 'Reviewed description and social metadata disagree')
        after.select_one(selector)['content'] = before.select_one(selector)['content']
    # Restore each allowed copy field only after checking its complete expected value.
    require(after.select_one('.branch-manuscript-intro').attrs == before.select_one('.branch-manuscript-intro').attrs,
            'Introduction attributes changed')
    after.select_one('.branch-manuscript-intro').replace_with(copy.deepcopy(before.select_one('.branch-manuscript-intro')))
    for i, section in enumerate(original['sections'], 1):
        old_node, new_node = before.select_one('#section-' + str(i)), after.select_one('#section-' + str(i))
        require(old_node.attrs == new_node.attrs and old_node.h2.attrs == new_node.h2.attrs, 'Section attributes changed')
        new_node.h2.replace_with(copy.deepcopy(old_node.h2))
        old_units, new_units = old_node.select('.branch-manuscript-unit'), new_node.select('.branch-manuscript-unit')
        require(len(old_units) == len(new_units), 'Logical paragraph count changed')
        for old_unit, new_unit in zip(old_units, new_units):
            require(new_unit.attrs == old_unit.attrs and all(n.name == 'p' and n.attrs == {'class': ['branch-manuscript-paragraph']}
                    for n in new_unit.children), 'Paragraph chunk structure/attributes changed')
            new_unit.replace_with(copy.deepcopy(old_unit))
        old_toc = before.select_one('#article-toc a[href="#section-' + str(i) + '"]')
        new_toc = after.select_one('#article-toc a[href="#section-' + str(i) + '"]')
        require(new_toc.get_text() == expected['sections'][i - 1]['heading'], 'Reviewed heading and TOC disagree')
        new_toc.replace_with(copy.deepcopy(old_toc))
    for selector in ('#questions details', '#consultation-example details.branch-reading-example p'):
        old_nodes, new_nodes = before.select(selector), after.select(selector)
        require(len(old_nodes) == len(new_nodes), 'FAQ/case count changed')
        for old_node, new_node in zip(old_nodes, new_nodes):
            require(old_node.attrs == new_node.attrs, 'FAQ/case attributes changed')
            if selector == '#questions details':
                require([n.name for n in new_node.children] == ['summary', 'p']
                        and new_node.summary.attrs == old_node.summary.attrs and new_node.p.attrs == old_node.p.attrs
                        and new_node.summary.find() is None and new_node.p.find() is None, 'Unapproved nested FAQ markup')
            new_node.replace_with(copy.deepcopy(old_node))
    old_graph, new_graph = graph(before), graph(after)
    expected_graph = copy.deepcopy(old_graph)
    canonical = url(record['path'])
    for node in expected_graph:
        if node.get('@type') in ('Article', 'WebPage'):
            node['description'] = expected['meta']
        if node.get('@type') == 'Article':
            node['articleSection'] = [s['heading'] for s in expected['sections']]
        if node.get('@type') == 'FAQPage':
            node['mainEntity'] = [{'@type': 'Question', 'name': f['question'], 'acceptedAnswer': {'@type': 'Answer', 'text': f['answer']}}
                                  for f in expected['faq']]
        for i, section in enumerate(expected['sections'], 1):
            if node.get('@id') == canonical + '#section-' + str(i):
                node['name'] = section['heading']
        if node.get('@type') == 'WebPage':
            parts = node['hasPart']
            index = next(i for i, p in enumerate(parts) if p['@id'] == canonical + '#questions')
            parts.insert(index + 1, {'@id': canonical + '#other-grades'})
    expected_graph.append({'@type': 'WebPageElement', '@id': canonical + '#other-grades',
                           'url': canonical + '#other-grades', 'name': '같은 동네의 다른 학년 안내',
                           'isPartOf': {'@id': canonical + '#webpage'}})
    require(sorted(new_graph, key=lambda n: n['@id']) == sorted(expected_graph, key=lambda n: n['@id']),
            'Schema changed outside exact reviewed copy and other-grade page element')
    for left, right in zip(before.select('script[type="application/ld+json"]'), after.select('script[type="application/ld+json"]')):
        right.string = left.string
    compact = lambda soup: re.sub(r'>\s+<', '><', str(soup))
    if compact(before) != compact(after):
        left, right = compact(before), compact(after)
        position = next((i for i, (a, b) in enumerate(zip(left, right)) if a != b), min(len(left), len(right)))
        raise ValueError('Unapproved remaining DOM change: ' + repr(left[max(0, position - 80):position + 140])
                         + ' -> ' + repr(right[max(0, position - 80):position + 140]))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=BASELINE)
    parser.add_argument('--report', type=Path, default=REPORTS / 'improvements-audit.json')
    args = parser.parse_args()
    with gzip.open(args.baseline, 'rt', encoding='utf-8') as stream:
        baseline = json.load(stream)
    counts, errors = Counter(), []

    def check(ok, kind, location='', detail=None):
        counts['assertions'] += 1
        if not ok:
            errors.append({'check': kind, 'location': location, **({'detail': detail} if detail is not None else {})})

    manifest = read(ROOT / 'tools/data/branch-grades/pages.json')
    try:
        check_manifest(manifest, baseline)
    except ValueError as exc:
        check(False, 'only-approved-manifest-revision', detail=str(exc))
    assert_immutable_inventory(baseline, manifest, check, counts)
    current_paths = {p.relative_to(ROOT).as_posix() for top in ('지점안내', '과목별학원') for p in (ROOT / top).rglob('index.html')}
    current_paths |= {'index.html', '상담문의/index.html', '학습가이드/index.html'}
    check(current_paths == set(baseline['pages']), 'exact-public-path-set-unchanged')
    assets = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'assets').rglob('*') if p.is_file()}
    check(assets == set(baseline['assets']) | {'assets/branch-grades.css'}, 'only-one-new-grade-stylesheet')
    sources = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'tools/data').rglob('*') if p.is_file()}
    check(sources == set(baseline['sourceFiles']) | {EDITORIAL_MANIFEST.relative_to(ROOT).as_posix()}, 'only-one-new-reviewed-editorial-manifest')
    check(len(FINGERPRINTS) == 4, 'reviewed-revision-fingerprints-are-frozen')
    for relative, expected_sha in FINGERPRINTS.items():
        check(sha((ROOT / relative).read_bytes()) == expected_sha, 'reviewed-revision-fingerprint', relative)
    reviewed = read(EDITORIAL_MANIFEST)
    require(reviewed.get('version') == 1 and reviewed.get('stage') == 'reviewed-editorial', 'Unknown reviewed manifest contract')
    edit_map = {identity(r): r for r in reviewed['records']}
    check(len(edit_map) == len(reviewed['records']), 'unique-reviewed-record-identities')
    records = {identity(r): r for r in manifest['pages']}
    check(set(edit_map).issubset(records), 'reviewed-edits-only-original-grade-records')
    for key, patch in edit_map.items():
        for field in ('sourceSha256', 'sourceArchiveSha256'):
            check(patch[field] == records[key][field], 'reviewed-patch-original-source-hash', str(key), field)
    changes_by_key, points_by_key, generation = {}, {}, []
    for grade in ('초5', '초6', '중1', '중2', '중3', '고1', '고2'):
        prefixes = [grade + '-전체'] if (REPORTS / 'improvements' / (grade + '-전체-generation.json')).exists() else [grade + '-영어', grade + '-수학']
        for prefix in prefixes:
            base = REPORTS / 'improvements'
            group_report = read(base / (prefix + '-generation.json'))
            group_changes = read(base / (prefix + '-editorial.json'))['changes']
            group_points = read(base / (prefix + '-reading.json'))['pages']
            generation.append((prefix, group_report, group_changes, group_points))
            check(group_report.get('editorialRevision') == REVISION, 'generation-report-revision', prefix)
            for point_record in group_points:
                key = identity(point_record)
                check(key in records and point_record['path'] == records[key]['path'] and key not in points_by_key,
                      'unique-reading-record-source-route', str(key))
                points_by_key[key] = point_record['readingPoints']
            for change in group_changes:
                changes_by_key.setdefault(identity(change), []).append(change)
    check(set(points_by_key) == set(records) and set(changes_by_key).issubset(records), 'full-5194-reading-and-editorial-log-coverage')
    legacy_by_key = {}
    for grade in ('초5', '초6', '중1', '중2', '중3', '고1', '고2'):
        for change in read(REPORTS / (grade + '-editorial.json'))['changes']:
            legacy_by_key.setdefault(identity(change), []).append(change)
    reference = read(ROOT / 'tools/data/branches/reference-content.json')
    centers = {c['id']: c for c in read(ROOT / 'tools/data/branches/centers.json')['centers'] + reference.get('additionalCenters', [])}
    group_scope = Counter()
    for index, (key, record) in enumerate(records.items(), 1):
        relative = record['path'].strip('/') + '/index.html'
        try:
            old_html = baseline['pages'][relative]['html']
            new_html = (ROOT / relative).read_text(encoding='utf-8')
            old_copy = content(BeautifulSoup(old_html, 'html.parser'))
            all_changes = changes_by_key.get(key, [])
            legacy = [c for c in all_changes if c.get('stage') not in ('reviewed-editorial', 'reading-editorial')]
            check(legacy == legacy_by_key.get(key, []), 'original-legacy-preparation-logs-identical', record['path'])
            patches = edit_map.get(key, {}).get('edits', [])
            expected_logs = [dict(stage='reviewed-editorial', field=e['field'], rule='reviewed-exact-field',
                                 rules=e['rules'], count=1, before=e['before'], after=e['after'],
                                 grade=record['grade'], subject=record['subject'], locality=record['locality'],
                                 sourceMember=record['sourceMember']) for e in patches]
            actual_logs = [c for c in all_changes if c.get('stage') == 'reviewed-editorial']
            check(actual_logs == expected_logs, 'exact-approved-reviewed-change-logs', record['path'])
            prepared = replay_reviewed(old_copy, patches)
            reading = [c for c in all_changes if c.get('stage') == 'reading-editorial']
            for change in reading:
                check(change.get('sourceMember') == record['sourceMember'] and identity(change) == key,
                      'reading-change-source-identity', record['path'])
            expected = replay_reading(prepared, reading)
            points = points_by_key[key]
            validate_points(points, expected)
            confirmed = record['grade'] in scoped_grades(centers[record['centerId']],
                reference['centers'].get(record['centerId'], {}), record['subject'])
            check(record['scopeConfirmed'] is confirmed, 'current-exact-grade-scope', record['path'])
            verify_and_restore(old_html, new_html, expected, record, points, confirmed)
            # The sole new URL fragment is independently verified against the preserved parent.
            parent = record['parentPath'].strip('/') + '/index.html'
            check('id="child-pages"' in baseline['pages'][parent]['html'], 'real-parent-grade-anchor', record['path'])
            counts['verifiedGradePages'] += 1
            counts['confirmedServicePages' if confirmed else 'learningGuideOnlyPages'] += 1
            counts['reviewedFields'] += len(patches)
            counts['readingIntroChanges'] += len(reading)
            counts['pagesWithReadingPoints'] += int(bool(points))
            counts['readingPoints'] += len(points)
            counts['logicalParagraphs'] += sum(len(s['paragraphs']) for s in expected['sections'])
            counts['faqQuestions'] += len(expected['faq'])
            group_scope[(record['grade'], record['subject'])] += int(confirmed)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            check(False, 'grade-copy-or-approved-ui-boundary', record['path'], str(exc))
        if index % 1000 == 0:
            print(json.dumps({'checkedGradePages': index, 'errorsSoFar': len(errors)}, ensure_ascii=False), flush=True)
    check(counts['verifiedGradePages'] == 5194 and counts['confirmedServicePages'] == 4992 and counts['learningGuideOnlyPages'] == 202,
          'exact-5194-pages-service4992-guide202')
    for prefix, report, changes, point_records in generation:
        expected_scope = sum(group_scope[(r['grade'], r['subject'])] for r in
                             { (p['grade'], p['subject']): p for p in point_records }.values())
        check(report['generatedPages'] == len(point_records) and report['scopeConfirmed'] == expected_scope
              and report['reviewedChanges'] == sum(c.get('stage') == 'reviewed-editorial' for c in changes)
              and report['readingChanges'] == sum(c.get('stage') == 'reading-editorial' for c in changes)
              and report['pagesWithReadingPoints'] == sum(bool(p['readingPoints']) for p in point_records),
              'generation-report-matches-independent-audit', prefix)
    locations = [n.text for n in ET.parse(ROOT / 'sitemap.xml').getroot().iter() if n.tag.rsplit('}', 1)[-1] == 'loc']
    check(len(locations) == len(set(locations)) == 8382 and set(locations) == set(baseline['sitemapUrls']), 'all-8382-public-sitemap-urls-preserved')
    check(len(ET.parse(ROOT / 'rss.xml').findall('.//item')) == 9, 'rss-nine-items')
    result = {'status': 'FAIL' if errors else 'PASS', 'createdAt': datetime.now(timezone.utc).isoformat(),
              'baseline': str(args.baseline), 'revision': REVISION, 'counts': dict(counts),
              'fingerprints': FINGERPRINTS, 'errors': errors,
              'scope': 'One integrated preservation/exact-copy review; browser checks are separate.'}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'counts': result['counts'], 'errors': errors[:12],
                      'errorCount': len(errors), 'report': str(args.report)}, ensure_ascii=False, indent=2))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
