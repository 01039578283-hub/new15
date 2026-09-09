"""Independent edition-2 audit. Reads site/source files; writes only its report.

No renderer, editorial transformer or legacy postprocessor is imported. Raw ZIP
parsing is shared with the earlier independent audit, not with the generator.
Every approved field change is replayed from the private exact-change log;
unlogged edits, changed metadata/images and out-of-scope legacy changes fail.
"""
from __future__ import annotations

import argparse
import ast
import copy
import gzip
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from bs4 import BeautifulSoup
from audit_branch_neighborhood_pages import independent_manuscripts

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports/branch-neighborhoods'
BASELINE = REPORTS / 'improvement-baseline-2026-09-10.json.gz'
JSON_LD = re.compile(r'(<script\b[^>]*type="application/ld\+json"[^>]*>)(.*?)(</script>)', re.S)
PHRASES = {
    ('원고 참고 키워드', '상담 참고 항목'), ('원고를 찾는 과정에서', '학습 정보를 찾는 과정에서'),
    ('원고를 준비하는 과정에서', '상담을 준비하는 과정에서'), ('원고를 읽는 가정', '이 안내를 읽는 가정'),
    ('이 원고에서 확인되지 않은', '이 안내에서 확인되지 않은'), ('이 원고에 제공되지 않은', '이 안내에 제공되지 않은'),
    ('이 원고에서 판단할 수 없으므로', '이 안내에서 판단할 수 없으므로'), ('입력된 학교 정보', '참고 학교 정보'),
    ('입력 정보만으로', '이 안내만으로'), ('입력만으로', '이 안내만으로'), ('D열에 제시된 학교 중', '안내된 학교 중'),
}
EDITORIAL_FIELDS = {
    'topic-focused-summary': r'intro',
    'retain-topic-trim-combined-repetition': r'sections\[\d+\]\.paragraphs',
    'reviewed-faq-meaning': r'faq\[\d+\]\.answer',
    'faq-direct-answer': r'faq\[\d+\]\.answer',
    'scope-before-course-choice': r'faq\[\d+\]\.answer',
    'scenario-without-repeated-combined-checklist': r'cases\[\d+\]',
    'reviewed-scenario-meaning': r'cases\[\d+\]',
}
REVIEWED_READER_TABLE_SHA256 = '308a089dc9ee6eaa0db4f3d98e7988ec5c23be6242eabb5384abba1647697a2f'
REVIEWED_PARENT_NAVIGATION_CSS_SHA256 = '31b620a33028bc232027918aebf59b9cc71592b6170beba51dc4f545e56e567e'
PARENT_NAVIGATION_JUMP = ('<a class="branch-button branch-neighborhood-jump" href="#neighborhood-pages">'
                          '동네별 학원 페이지 보기<span aria-hidden="true">↓</span></a>')
GENERAL_SCHOOLS = {
    '지역내모든고등학교가능': '고등학교별 상담 대상과 희망 과목·학년은 상담에서 확인해 주세요.',
    '모든고등학교가능': '고등학교별 상담 대상과 희망 과목·학년은 상담에서 확인해 주세요.',
    '기타사립초': '사립초등학교 관련 상담은 학교명·학년·희망 과목을 알려 주세요.',
    '특성화고': '특성화고등학교 관련 상담은 학년·희망 과목·교과 범위를 알려 주세요.',
}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def normalize(text):
    return re.sub(r'\s+', ' ', text).strip()


def fold(text):
    return re.sub(r'\s+', '', str(text or ''))


def graph(soup):
    result = []
    for script in soup.select('script[type="application/ld+json"]'):
        value = json.loads(script.string or script.get_text())
        result.extend(value.get('@graph', [value]))
    return result


def parent_navigation_markup(children):
    """Independent, closed approved markup contract; not imported from renderer."""
    ordered = sorted(children, key=lambda p: (p['locality'], p['subject']))
    groups = defaultdict(list)
    for child in ordered:
        groups[child['locality']].append(child)
    cards = []
    for locality, entries in groups.items():
        links = ''.join('<a class="branch-neighborhood-link" href="' + escape(p['path'], quote=True)
                        + '"><span>' + escape(p['title'], quote=True)
                        + '</span><span aria-hidden="true">→</span></a>' for p in entries)
        cards.append('<div class="branch-neighborhood-card"><h3>' + escape(locality, quote=True)
                     + '</h3><div class="branch-neighborhood-buttons">' + links + '</div></div>')
    current = ('<section class="branch-panel branch-neighborhood-navigation" id="neighborhood-pages" '
               'aria-labelledby="neighborhood-pages-title"><p class="branch-kicker">동네별 페이지 바로가기</p>'
               '<h2 id="neighborhood-pages-title">동네별 영어·수학 학습 안내</h2>'
               '<p class="">동네와 과목을 선택하면 학습 내용과 상담 준비사항을 자세히 볼 수 있습니다.</p>'
               '<div class="branch-neighborhood-grid">' + ''.join(cards) + '</div></section>')
    previous = ('<section class="branch-panel" id="neighborhood-pages"><h2>동네별 영어·수학 학습 안내</h2>'
                '<div class="branch-city-links">' + ''.join('<a href="' + escape(p['path'], quote=True)
                + '">' + escape(p['title'], quote=True) + '</a>' for p in ordered) + '</div></section>')
    return current, previous


def normalize_parent_navigation(html, children):
    """Reverse only the exact approved panel and one first-position hero link.

    The caller still compares every remaining UTF-8 byte with the old baseline,
    including all JSON-LD, metadata, media, tuition and manuscript content.
    """
    if 'branch-neighborhood-navigation' not in html:
        if 'branch-neighborhood-jump' in html:
            raise ValueError('Hero jump exists without the approved navigation panel')
        return html, False
    if not children:
        raise ValueError('Navigation is forbidden for a center without actual children')
    matches = list(re.finditer(r'<section\b[^>]*\bid="neighborhood-pages"[^>]*>.*?</section>', html, re.S))
    expected, previous = parent_navigation_markup(children)
    if len(matches) != 1 or matches[0].group(0) != expected:
        raise ValueError('Navigation panel differs from the exact approved manifest-based markup')
    action = '<div class="branch-actions">' + PARENT_NAVIGATION_JUMP
    if html.count(PARENT_NAVIGATION_JUMP) != 1 or html.count('branch-neighborhood-jump') != 1 or html.count(action) != 1:
        raise ValueError('Expected exactly one first-position hero navigation link')
    normalized = html[:matches[0].start()] + previous + html[matches[0].end():]
    return normalized.replace(action, '<div class="branch-actions">', 1), True


def normalize_parent_navigation_css(raw):
    """Remove only the reviewed 2,074-byte insertion; caller checks old SHA."""
    pattern = rb'(?m)^\.branch-neighborhood-navigation \{.*?(?=^\.branch-info \{)'
    matches = list(re.finditer(pattern, raw, re.S))
    if not matches:
        return raw, False
    if len(matches) != 1 or sha(matches[0].group(0)) != REVIEWED_PARENT_NAVIGATION_CSS_SHA256:
        raise ValueError('Parent navigation CSS insertion differs from its reviewed fingerprint')
    match = matches[0]
    return raw[:match.start()] + raw[match.end():], True


def paragraph_sentences(value):
    return [s for s in re.split(r'(?<=[.!?])\s+', value.strip()) if s]


def replay_log(raw_records, log, check):
    # Read only a reviewed literal table, never execute the editor. Its pinned
    # fingerprint means adding/changing a rule requires a new explicit review.
    module = ast.parse((ROOT / 'tools/polish_branch_manuscripts.py').read_text(encoding='utf-8'))
    reader_rules = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == '_READER_RULES' for t in n.targets))
    check(sha(json.dumps(reader_rules, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) == REVIEWED_READER_TABLE_SHA256,
          'reviewed-reader-rule-table-fingerprint')
    records = copy.deepcopy(raw_records)
    old_edition = copy.deepcopy(raw_records)
    editorial_started = set()
    stats = Counter()
    for change in log:
        key = (change['locality'], change['subject'])
        field = change['field']
        check(key in records, 'log-known-manuscript', str(key))
        tokens = re.findall(r'([A-Za-z]+)|\[(\d+)\]', field)
        keys = [name if name else int(index) for name, index in tokens]
        container = records[key]
        for item in keys[:-1]:
            container = container[item]
        current = container[keys[-1]]
        if change.get('stage') == 'editorial':
            if key not in editorial_started:
                old_edition[key] = copy.deepcopy(records[key])
                editorial_started.add(key)
            pattern = EDITORIAL_FIELDS.get(change['rule'])
            check(pattern is not None and re.fullmatch(pattern, field) is not None, 'log-approved-editorial-rule-field', str(key), change['rule'] + ':' + field)
            check(change['count'] == 1 and current == change['before'], 'log-editorial-exact-before', str(key), field)
            check(type(current) is type(change['after']), 'log-editorial-type', str(key), field)
            container[keys[-1]] = copy.deepcopy(change['after'])
            stats['editorialOperations'] += 1
        else:
            check(key not in editorial_started, 'log-phrase-stage-order', str(key))
            if change['rule'].startswith('reader-'):
                allowed = [(name, expression, after) for name, expression, after in reader_rules
                           if name == change['rule'] and after == change['after']]
                matches = next((list(re.finditer(expression, current)) for _, expression, _ in allowed
                                if any(m.group(0) == change['before'] for m in re.finditer(expression, current))), [])
                selected = [m for m in matches if m.group(0) == change['before']]
                check(bool(selected) and field not in ('title', 'meta') and not field.endswith('.heading'), 'log-approved-reader-phrase-context', str(key), field)
                updated = current
                for match in reversed(selected):
                    updated = updated[:match.start()] + change['after'] + updated[match.end():]
                count = len(selected)
            else:
                check((change['before'], change['after']) in PHRASES and isinstance(current, str), 'log-approved-phrase', str(key), field)
                updated, count = re.subn(r'(?<![가-힣A-Za-z0-9_])' + re.escape(change['before']), change['after'], current)
            check(count == change['count'], 'log-phrase-count', str(key), field)
            container[keys[-1]] = updated
            old_edition[key] = copy.deepcopy(records[key])
            stats['polishedPhrases'] += count
    for key, raw in raw_records.items():
        display = records[key]
        for field in ('title', 'meta', 'locality', 'subject', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256'):
            check(display[field] == raw[field], 'editorial-immutable-' + field, str(key))
        check([s['heading'] for s in display['sections']] == [s['heading'] for s in raw['sections']], 'editorial-heading-preservation', str(key))
        check([f['question'] for f in display['faq']] == [f['question'] for f in old_edition[key]['faq']], 'editorial-faq-question-preservation-after-exact-reader-corrections', str(key))
        check(sum(len(paragraph_sentences(c)) for c in display['cases']) == sum(len(paragraph_sentences(c)) for c in old_edition[key]['cases']), 'no-automatic-case-sentence-deletion', str(key))
        new_body = ' '.join(p for s in display['sections'] for p in s['paragraphs'])
        for section in old_edition[key]['sections']:
            for paragraph in section['paragraphs']:
                for sentence in paragraph_sentences(paragraph):
                    protected = re.search(r'\d|[A-Za-z]|[×÷=]|[‘“「]', sentence) or re.search(r'^(?:다만|단,|하지만|그러나)|보장|단정|운영 여부|개설 여부|확인되지', sentence)
                    if protected:
                        check(sentence in new_body, 'protected-body-example-or-qualification', str(key), sentence)
    return records, dict(stats)


def legacy_mask(html):
    """A narrow byte-comparison mask, not a whole-page serialization exception."""
    html = JSON_LD.sub(lambda m: m.group(1) + 'JSON-LD' + m.group(3), html)
    html = re.sub(r'<p class="academy-scope-confirmation">.*?</p>', '', html, flags=re.S)
    html = re.sub(r'(<strong>수업 가능 학년</strong><span>).*?(</span>)', r'\1GRADE\2', html, flags=re.S)
    faq = re.compile(r'(<section\b[^>]*class="[^"]*academy-faq[^"]*"[^>]*>)(.*?)(</section>)', re.S)

    def mask(match):
        content = re.sub(r'(<details\b[^>]*><summary>).*?(</summary><p>).*?(</p></details>)', r'\1QUESTION\2ANSWER\3', match.group(2), flags=re.S)
        return match.group(1) + content + match.group(3)

    return faq.sub(mask, html)


def expected_scope_sentence(center, subject, scope):
    name = center['sourceCenterName']
    if scope.get('status') == 'note_only_scope':
        return f'{name} {subject}는 기초 보완이 필요한 학생의 수업 가능 여부와 세부 학년을 상담에서 확인해야 합니다.'
    return f'{name}의 {subject} 수업 개설 여부와 대상 학년은 상담에서 확인해야 합니다.'


def confirmed_grades(center, ref, subject):
    grades = center.get('subjects', {}).get(subject, {}).get('grades', [])
    if not grades or any(not re.fullmatch(r'(?:초[1-6]|중[1-3]|고[1-3])', g) for g in grades):
        return []
    summaries = ref.get('operations', {}).get('subjectDisplay', {})
    if summaries:
        row = summaries.get(subject, {})
        if row.get('status') not in {'recorded', 'recorded_with_conditions'} or row.get('includeInUnqualifiedAvailableSubjects') is not True:
            return []
        if 'sourceGrades' in row and set(row['sourceGrades']) != set(grades):
            return []
    elif subject not in center.get('availableSubjects', []):
        return []
    return list(dict.fromkeys(grades))


def run(args):
    with gzip.open(args.baseline, 'rt', encoding='utf-8') as stream:
        baseline = json.load(stream)
    errors = []
    warnings = []
    stats = Counter()

    def check(ok, kind, location='', detail=None):
        stats['assertions'] += 1
        if not ok:
            errors.append({'check': kind, 'location': location, **({'detail': detail} if detail is not None else {})})

    generation = read_json(REPORTS / 'generation.json')
    check(generation.get('editorialEdition') == 2, 'edition-2-required')
    page_manifest = read_json(ROOT / 'tools/data/branch-neighborhoods/pages.json')
    pages = page_manifest['pages']
    reference = read_json(ROOT / 'tools/data/branches/reference-content.json')
    centers = {c['id']: c for c in read_json(ROOT / 'tools/data/branches/centers.json')['centers'] + reference.get('additionalCenters', [])}
    mapping = read_json(ROOT / 'tools/data/branch-neighborhoods/mapping.json')
    check(page_manifest['mappingSha256'] == sha((ROOT / 'tools/data/branch-neighborhoods/mapping.json').read_bytes()), 'generated-manifest-current-mapping-sha')
    check(len(pages) == 742 and len({p['path'] for p in pages}) == 742, 'generated-manifest-exact-page-count')
    mapping_rows = {r['locality']: r for r in mapping['rows']}
    children_by_parent = defaultdict(list)
    for record in pages:
        children_by_parent[record['parentPath'].strip('/') + '/index.html'].append(record)
    check(len(children_by_parent) == 188, 'parent-child-owner-count-188')
    targets = {}
    for page in pages:
        row = reference['centers'][page['centerId']].get('operations', {}).get('subjectDisplay', {}).get(page['subject'], {})
        if row and row.get('includeInUnqualifiedAvailableSubjects') is False:
            for level in ('초등학생', '중학생', '고등학생'):
                relative = f"과목별학원/{level}{page['subject']}학원/{page['locality']}/index.html"
                targets[relative] = (page, row, level)
    check(len(targets) == 54, 'legacy-target-exact-54')
    current_paths = {p.relative_to(ROOT).as_posix() for top in ('지점안내', '과목별학원') for p in (ROOT / top).rglob('index.html')}
    check(current_paths == set(baseline['pages']), 'all-existing-page-paths-preserved')
    for relative, old in baseline['pages'].items():
        parts = Path(relative).parts
        if relative.startswith('지점안내/') and len(parts) > 4:
            continue
        raw = (ROOT / relative).read_bytes()
        if relative not in targets:
            if relative.startswith('지점안내/'):
                children = children_by_parent.get(relative, [])
                try:
                    normalized, has_navigation = normalize_parent_navigation(raw.decode('utf-8'), children)
                    check(sha(normalized.encode('utf-8')) == old['sha256'], 'parent-exact-reversible-navigation-diff', relative)
                    stats['approvedNavigationParents' if has_navigation else 'unchangedParents'] += 1
                    if has_navigation:
                        soup = BeautifulSoup(raw.decode('utf-8'), 'html.parser')
                        panel = soup.select_one('#neighborhood-pages')
                        ordered = sorted(children, key=lambda p: (p['locality'], p['subject']))
                        check([a['href'] for a in panel.select('a')] == [p['path'] for p in ordered], 'parent-exact-child-links', relative)
                        check(panel.find_previous_sibling() == soup.select_one('.branch-detail-hero')
                              and 'branch-primary-media' in panel.find_next_sibling().get('class', []), 'parent-navigation-hero-before-media', relative)
                        check(graph(soup) == graph(BeautifulSoup(old['html'], 'html.parser')), 'parent-all-jsonld-unchanged', relative)
                        listing = [n for n in graph(soup) if n.get('@type') == 'ItemList' and n.get('@id', '').endswith('#neighborhood-pages')]
                        expected_items = [{'@type': 'ListItem', 'position': i + 1, 'name': p['title'],
                                           'url': 'https://xn--9p4bn5e3wjn0a.com' + quote(p['path'], safe='/')} for i, p in enumerate(ordered)]
                        check(len(listing) == 1 and listing[0].get('numberOfItems') == len(ordered)
                              and listing[0].get('itemListElement') == expected_items, 'parent-itemlist-matches-buttons', relative)
                        for child in ordered:
                            check(child['parentPath'].strip('/') + '/index.html' == relative
                                  and (ROOT / child['path'].strip('/') / 'index.html').is_file(), 'parent-existing-child-target', child['path'])
                        stats['parentNavigationLinks'] += len(ordered)
                    elif len(parts) == 4 and not children:
                        check('id="neighborhood-pages"' not in raw.decode('utf-8'), 'no-invented-navigation-without-children', relative)
                        stats['centersWithoutChildren'] += 1
                except (ValueError, AttributeError, TypeError) as exc:
                    check(False, 'parent-navigation-boundary', relative, str(exc))
            else:
                check(sha(raw) == old['sha256'], 'out-of-scope-html-byte-preservation', relative)
                stats['unchangedLegacyPages' if len(parts) == 4 else 'unchangedSubjectHubs'] += 1
            continue
        record, scope, level = targets[relative]
        current_html = raw.decode('utf-8')
        before = BeautifulSoup(old['html'], 'html.parser')
        after = BeautifulSoup(current_html, 'html.parser')
        check(legacy_mask(old['html']) == legacy_mask(current_html), 'legacy-exact-allowed-html-diff', relative)
        sentence = expected_scope_sentence(centers[record['centerId']], record['subject'], scope)
        notices = after.select('.academy-scope-confirmation')
        check(len(notices) == 1 and notices[0].get_text() == sentence + ' 희망 학년과 현재 교재를 함께 알려 주세요.', 'legacy-notice-exact', relative)
        grade = next(n.span.get_text() for n in after.select('.academy-fact-card') if n.strong.get_text() == '수업 가능 학년')
        check(grade == scope['summary'], 'legacy-current-scope', relative)
        expected_faq = []
        for item in before.select('.academy-faq details'):
            question, answer = item.summary.get_text(), item.p.get_text()
            if record['subject'] == '영어' and level == '고등학생' and question == record['locality'] + ' 고1·고2·고3 수업은 모두 같나요?':
                question = record['locality'] + ' 고등학생 영어 상담에서는 학생별 학습 차이를 어떻게 확인하나요?'
                answer = sentence + ' ' + answer.removeprefix(record['locality'] + ' 고등학생 영어학원에서는 ')
                stats['legacyFaqEntriesChanged'] += 1
            elif record['subject'] == '수학' and level == '중학생' and answer.startswith('가능합니다. 다만 '):
                answer = sentence + ' ' + answer.removeprefix('가능합니다. 다만 ')
                stats['legacyFaqEntriesChanged'] += 1
            expected_faq.append((question, answer))
        check([(n.summary.get_text(), n.p.get_text()) for n in after.select('.academy-faq details')] == expected_faq, 'legacy-faq-closed-diff', relative)
        expected_nodes = copy.deepcopy(graph(before))
        canonical = before.select_one('link[rel="canonical"]')['href']
        expected_nodes = [n for n in expected_nodes if n.get('@type') != 'Service']
        for node in expected_nodes:
            if node.get('@type') == 'EducationalOrganization':
                node.pop('educationalLevel', None)
            if isinstance(node.get('about'), list):
                node['about'] = [n for n in node['about'] if n.get('@id') != canonical + '#service']
            if node.get('@type') == 'WebPage':
                node['mainEntity'] = {'@id': canonical + '#article'}
            if node.get('@type') == 'FAQPage':
                node['mainEntity'] = [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in expected_faq]
        check(graph(after) == expected_nodes, 'legacy-exact-allowed-schema-diff', relative)
        stats['reconciledLegacyPages'] += 1
    for relative, old in baseline['assets'].items():
        if relative == 'assets/branch-neighborhoods.css':
            continue
        if relative == 'assets/branches.css':
            try:
                normalized, changed = normalize_parent_navigation_css((ROOT / relative).read_bytes())
                check(sha(normalized) == old['sha256'], 'parent-css-exact-approved-insertion-only', relative)
                stats['approvedParentNavigationStylesheets' if changed else 'preservedAssets'] += 1
            except ValueError as exc:
                check(False, 'parent-css-boundary', relative, str(exc))
            continue
        check((ROOT / relative).is_file() and sha((ROOT / relative).read_bytes()) == old['sha256'], 'original-asset-sha', relative)
        stats['preservedAssets'] += 1
    for relative, old in baseline['sourceFiles'].items():
        if relative == 'tools/data/branch-neighborhoods/pages.json':
            # This generated manifest can change its mapping provenance hash;
            # all row identities/source hashes are verified below against ZIPs.
            stats['generatedManifestsCheckedSemantically'] += 1
            continue
        check((ROOT / relative).is_file() and sha((ROOT / relative).read_bytes()) == old['sha256'], 'original-source-file-sha', relative)
        stats['preservedSourceFiles'] += 1

    original_archives = {Path(n['path']).name: Path(n['path']) for n in mapping['sources'] if n['path'].endswith('.zip')}

    def source_check(ok, kind, location='', detail=None):
        if kind == 'source-archive-original-sha' and not ok and not original_archives[location].exists():
            warnings.append({'check': kind, 'location': str(original_archives[location]),
                             'detail': 'Old external path unavailable. Repository source ZIP is verified against the pre-improvement SHA and original mapping SHA.'})
            return
        check(ok, kind, location, detail)

    raw_records, archive_facts = independent_manuscripts(ROOT / 'tools/data/branch-neighborhoods', mapping, source_check)
    log = read_json(REPORTS / 'manuscript-polish.json')['changes']
    displays, log_stats = replay_log(raw_records, log, check)
    check(log_stats.get('editorialOperations', 0) == generation.get('editorialOperations'), 'editorial-operation-report')
    check(log_stats.get('polishedPhrases', 0) == generation.get('polishedPhrases'), 'phrase-operation-report')
    school_rows = {r['neighborhood']: r for r in read_json(ROOT / 'tools/data/branches/target-schools.json')}
    html_cache = {}

    def soup_at(route):
        if route not in html_cache:
            html_cache[route] = BeautifulSoup((ROOT / route.strip('/') / 'index.html').read_text(encoding='utf-8'), 'html.parser')
        return html_cache[route]

    sample_statistics = []
    for record in pages:
        route = record['path']
        relative = route.strip('/') + '/index.html'
        try:
            old = BeautifulSoup(baseline['pages'][relative]['html'], 'html.parser')
            soup = soup_at(route)
            canonical = old.select_one('link[rel="canonical"]')['href']
            parent_canonical = canonical.rsplit('/', 2)[0] + '/'
            display = displays[(record['locality'], record['subject'])]
            source_record = raw_records[(record['locality'], record['subject'])]
            for key in ('locality', 'subject', 'title', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256'):
                check(record[key] == source_record[key], 'manifest-row-source-' + key, route)
            mapping_row = mapping_rows[record['locality']]
            check(record['centerId'] == mapping_row['centerId'] and record['parentPath'] == mapping_row['branchPath'] and route == mapping_row['childPaths'][record['subject']], 'manifest-mapping-center-parent-route', route)
            center, ref = centers[record['centerId']], reference['centers'][record['centerId']]
            grades = confirmed_grades(center, ref, record['subject'])
            check([n.attrs for n in soup.select('head meta,head link')] == [n.attrs for n in old.select('head meta,head link')], 'new-meta-canonical-og-preservation', route)
            check(str(soup.title) == str(old.title) and str(soup.h1) == str(old.h1), 'new-title-h1-preservation', route)
            check([n.attrs for n in soup.select('img')] == [n.attrs for n in old.select('img')], 'new-all-images-order-attributes', route)
            check(str(soup.select_one('.branch-primary-media')) == str(old.select_one('.branch-primary-media')), 'new-original-media-panel-dom', route)
            check(str(soup.select_one('#related-pages')) == str(old.select_one('#related-pages')) and str(soup.select_one('#contact')) == str(old.select_one('#contact')), 'existing-related-contact-preservation', route)
            check(str(soup.select_one('.branch-child-quick')) == str(old.select_one('.branch-child-quick')), 'original-center-quick-facts', route)
            check(str(soup.select_one('.floating-actions')) == str(old.select_one('.floating-actions')), 'contact-controls-preservation', route)
            check(soup.select_one('.branch-manuscript-intro').get_text() == display['intro'], 'intro-exact-approved-display', route)
            actions = soup.select('.branch-reading-shortcuts a')
            check([(a.get('href'), a.get_text()) for a in actions] == [('#section-1', '본문 바로 읽기'), ('#article-toc', '글 목차'), ('#center-info', '지점·교육비 안내')], 'reading-shortcuts', route)
            check(bool(soup.select('.branch-child-hero .branch-scope-notice')) == (not bool(grades)), 'uncertain-scope-visible-notice', route)
            for index, section in enumerate(display['sections'], 1):
                current = soup.find(id='section-' + str(index))
                check(current is not None and current.h2.get_text() == section['heading'], 'new-heading-preservation', route, index)
                units = current.select('.branch-manuscript-unit')
                check(len(units) == len(section['paragraphs']), 'logical-paragraph-count', route, index)
                for p_index, (unit, expected) in enumerate(zip(units, section['paragraphs'])):
                    check(unit.get('data-paragraph') == str(p_index), 'logical-paragraph-index', route)
                    chunks = unit.select('p.branch-manuscript-paragraph')
                    check(normalize(' '.join(n.get_text() for n in chunks)) == normalize(expected), 'lossless-reading-chunks', route, [index, p_index])
                    check(all(re.search(r'[.!?][”’\")）」]*$', n.get_text()) for n in chunks[:-1]), 'complete-sentence-chunk-boundary', route, [index, p_index])
                    check(not unit.select('span') and len(chunks) > 0, 'reading-chunks-real-paragraphs', route)
                    stats['logicalParagraphs'] += 1
                    stats['displayParagraphs'] += len(chunks)
                stats['manuscriptSections'] += 1
            check([n.get_text() for n in soup.select('#consultation-example p')] == display['cases'], 'cases-exact-approved-display', route)
            examples = soup.select('#consultation-example details.branch-reading-example')
            check(len(examples) == 1 and not examples[0].has_attr('open') and examples[0].summary.get_text() == '준비할 자료와 질문 살펴보기', 'cases-default-closed-accessible-summary', route)
            check(soup.select_one('#consultation-example h2').get_text() == old.select_one('#consultation-example h2').get_text(), 'case-heading-preservation', route)
            faqs = [(n.summary.get_text(), n.p.get_text()) for n in soup.select('#questions details')]
            expected_faq = [(n['question'], n['answer']) for n in display['faq']]
            check(faqs == expected_faq and len(faqs) == 4, 'new-faq-exact-approved-display', route)
            public_text = soup.get_text(' ', strip=True)
            check(not re.search(r'자료상|원문:|D열|원고 참고 키워드|항목로|\[(?:[^\]]*(?:후보|확인\s*필요|미확인|\d{4}\s*통계))[^\]]*\]', public_text), 'no-public-editorial-leaks', route)

            # Independently project only the four approved generic school labels
            # and explicit bracket review notes; preserve all actual names/levels.
            expected_schools, expected_notes = [], []
            for level in ('elementary', 'middle', 'high'):
                names = []
                for original in school_rows[record['locality']].get('targetSchools', {}).get(level, []):
                    name = re.sub(r'\[([^\[\]]*)\]', lambda m: '' if re.search(r'후보|확인\s*필요|미확인|\d{4}\s*통계.*(?:휴|폐)교', m.group(1)) else m.group(0), original).strip()
                    note = GENERAL_SCHOOLS.get(fold(name))
                    if note:
                        if note not in expected_notes:
                            expected_notes.append(note)
                    elif name and name not in names:
                        names.append(name)
                expected_schools.extend(names)
            check([n.get_text() for n in soup.select('#schools .branch-school-list li')] == expected_schools, 'school-name-level-projection', route)
            for note in expected_notes:
                check(note in soup.select_one('#schools').get_text(), 'school-general-note', route)
            if center.get('addressPrecision') == 'neighborhood':
                check('안내 위치' in soup.select_one('#center-info').get_text() and '정확한 도로명 주소·건물·층수' in soup.select_one('#center-info').get_text(), 'approximate-address-notice', route)

            nodes = graph(soup)
            old_nodes = {n['@id']: n for n in graph(old)}
            by_id = {n['@id']: n for n in nodes}
            check(len(by_id) == len(nodes), 'unique-schema-ids', route)
            services = [n for n in nodes if n.get('@type') == 'Service']
            check(len(services) == int(bool(grades)), 'service-confirmed-scope-only', route)
            stats['servicePages'] += bool(services)
            check(not grades or not soup.select('.branch-child-hero .branch-scope-notice'), 'confirmed-scope-not-mislabelled', route)
            actual_section_ids = [n['id'] for n in soup.select('section.branch-panel[id]')]
            old_section_ids = [n['id'] for n in old.select('section.branch-panel[id]')]
            expected_ids = list(old_section_ids)
            grade_links = soup.select('#grade-guides a')
            if grade_links:
                expected_ids.insert(expected_ids.index('contact'), 'grade-guides')
            check(actual_section_ids == expected_ids, 'new-exact-section-inventory-order', route)
            for node in nodes:
                node_id = node['@id']
                if node_id == canonical + '#grade-guides':
                    check(node == {'@type': 'WebPageElement', '@id': node_id, 'url': node_id,
                                   'name': '학년별 ' + record['subject'] + ' 학습 안내', 'isPartOf': {'@id': canonical + '#webpage'}}, 'new-grade-schema-exact', route)
                    continue
                check(node_id in old_nodes, 'no-unapproved-new-schema-entity', route, node_id)
                expected = copy.deepcopy(old_nodes[node_id])
                if node.get('@type') in ('Article', 'WebPage'):
                    expected['dateModified'] = '2026-09-10'
                if node.get('@type') == 'FAQPage':
                    expected['mainEntity'] = [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in expected_faq]
                if node.get('@type') == 'WebPage':
                    expected['hasPart'] = [{'@id': canonical + '#' + key} for key in actual_section_ids]
                if node.get('@type') == 'Article' and not grades:
                    expected['about'] = [n for n in expected['about'] if n.get('@id') != canonical + '#service']
                check(node == expected, 'new-schema-exact-allowed-field-diff', route, node_id)
            expected_node_ids = set(old_nodes) - ({canonical + '#service'} if not grades else set())
            if grade_links:
                expected_node_ids.add(canonical + '#grade-guides')
            check(set(by_id) == expected_node_ids, 'new-exact-schema-entity-set', route)

            # Grade links must match current scope and the existing registered
            # branch identity. No fallback link is accepted for missing facts.
            for link in grade_links:
                target = link.get('href', '')
                check(bool(grades) and target.startswith('/과목별학원/') and target.endswith('/' + record['locality'] + '/'), 'grade-link-scope-locality', route, target)
                prefix = next((p for label, p in [('초등학생', '초'), ('중학생', '중'), ('고등학생', '고')] if target.split('/')[2] == label + record['subject'] + '학원'), None)
                available = [g for g in grades if g.startswith(prefix or '?')]
                check(bool(available), 'grade-link-current-grade-subset', route, target)
                legacy = soup_at(target)
                orgs = [n for n in graph(legacy) if n.get('@type') == 'EducationalOrganization']
                check(len(orgs) == 1, 'grade-link-one-organization', route, target)
                org = orgs[0]
                address = org.get('address', {})
                csv = mapping_rows[record['locality']]['evidence']['csv']
                reviewed = [e for e in mapping_rows[record['locality']]['evidence'].get('registeredIdentityComparison', [])
                            if e.get('centerId') == center['id'] and e.get('active') is True and e.get('strongIdentityEvidence') is True]
                region_matches = fold(address.get('addressRegion')) == fold(center['region']['province'])
                if not region_matches:
                    region_matches = (fold(address.get('addressRegion')) == fold(mapping_rows[record['locality']].get('sourceNeighborhoodRegion'))
                                      and any(e.get('compatibleSourceRegion') is True for e in reviewed))
                check(fold(address.get('streetAddress')) == fold(center.get('address')) and region_matches, 'grade-link-exact-address-reviewed-region', route, target)
                check(fold(org.get('name')) == fold(csv.get('centerName')) and fold(csv.get('registeredName')) == fold(center.get('registeredAcademyName')) and fold(org.get('identifier')) == fold(csv.get('registrationNumber')), 'grade-link-registered-identity', route, target)
                check(set(available).issubset(org.get('educationalLevel', [])), 'grade-link-legacy-grade-coverage', route, target)
                expected_note = '현재 안내 학년: ' + '·'.join(available)
                detail = ref.get('operations', {}).get('subjectDisplay', {}).get(record['subject'], {}).get('detail', '')
                if detail:
                    expected_note += '. ' + detail
                check(link.small is not None and link.small.get_text() == expected_note, 'grade-link-exact-conditions', route, target)
                stats['verifiedGradeLinks'] += 1
            check(not grade_links or bool(soup.select('#article-toc a[href="#grade-guides"]')), 'grade-link-toc', route)
            stats['pagesWithoutGradeLinks'] += not bool(grade_links)
            ids = [n['id'] for n in soup.select('[id]')]
            check(len(ids) == len(set(ids)), 'unique-html-ids', route)
            for anchor in soup.select('a[href]'):
                parsed = urlsplit(anchor['href'])
                if parsed.scheme or parsed.netloc:
                    continue
                target = unquote(parsed.path)
                if not target:
                    check(not parsed.fragment or unquote(parsed.fragment) in ids, 'working-self-anchor', route, anchor['href'])
                else:
                    file = ROOT / target.lstrip('/')
                    if target.endswith('/'):
                        file /= 'index.html'
                    check(file.is_file(), 'working-local-link', route, anchor['href'])
            if record['locality'] in {'명일동', '교하', '화곡동', '위례', '광명동', '화성태안'}:
                sample_statistics.append({'path': route, 'introCharacters': len(display['intro']),
                                          'logicalParagraphs': len(soup.select('.branch-manuscript-unit')),
                                          'displayParagraphs': len(soup.select('.branch-manuscript-paragraph')),
                                          'gradeLinks': len(grade_links), 'service': bool(services)})
            stats['newPages'] += 1
        except Exception as exc:
            check(False, 'page-audit-exception', route, type(exc).__name__ + ': ' + str(exc))
    check(stats['newPages'] == 742, 'new-pages-complete')
    check(stats['unchangedLegacyPages'] == 2172 and stats['unchangedParents'] + stats['approvedNavigationParents'] == 210, 'preserved-page-coverage')
    check(stats['approvedNavigationParents'] in (0, 188)
          and stats['parentNavigationLinks'] == (742 if stats['approvedNavigationParents'] else 0)
          and stats['centersWithoutChildren'] == 5, 'parent-navigation-closed-coverage-188-742-5')
    check(stats['reconciledLegacyPages'] == 54 and stats['legacyFaqEntriesChanged'] == 18, 'legacy-reconciliation-coverage')
    check(stats['servicePages'] == 724, 'confirmed-service-724-uncertain-18')
    check(stats['pagesWithoutGradeLinks'] == 39 and stats['verifiedGradeLinks'] == 2097, 'grade-link-703-pages-2097-links')
    sitemap = [n.text for n in ET.parse(ROOT / 'sitemap.xml').getroot().iter() if n.tag.rsplit('}', 1)[-1] == 'loc']
    for record in pages:
        check(sitemap.count('https://xn--9p4bn5e3wjn0a.com' + quote(record['path'], safe='/')) == 1, 'sitemap-exactly-once', record['path'])
    result = {'version': 1, 'edition': 2, 'createdAt': datetime.now(timezone.utc).isoformat(),
              'status': 'PASS' if not errors else 'FAIL', 'counts': dict(stats), 'sourceArchives': archive_facts,
              'logCounts': log_stats, 'samples': sample_statistics, 'errors': errors, 'warnings': warnings,
              'visualRender': 'Not claimed by this structural audit; root performs current browser samples separately.'}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=BASELINE)
    parser.add_argument('--report', type=Path, default=REPORTS / 'improvements-audit.json')
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({'status': result['status'], 'report': str(args.report), 'counts': result['counts'],
                      'errorCount': len(result['errors']), 'firstErrors': result['errors'][:15]}, ensure_ascii=False, indent=2))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
