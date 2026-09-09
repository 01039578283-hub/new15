"""Independent high-school-year-1 source, navigation and preservation audit.

No generator, source parser, editorial transformer or navigation renderer is
imported. Reads raw ZIPs and the pre-task snapshot; writes only the JSON report.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import copy
from datetime import datetime, timezone
import gzip
import hashlib
from html import escape
import json
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata
from urllib.parse import quote, unquote, urlsplit
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'tools/data/branch-grades'
REPORTS = ROOT / 'reports/branch-grades'
BASELINE = Path('C:/Users/1992k/Desktop/CodexData/tmp/site15-high1-2026-09-10/before.json.gz')
DOMAIN = 'https://xn--9p4bn5e3wjn0a.com'
ARCHIVE_SHAS = {'영어': '778e39b4d4461deafb8ddd543d87e4fd49088d1b176f5f182ee0134a5540cd1a',
                '수학': 'e767085ffa04c4084244ff22158b91947ddfa170d33505afb4dd1aa6910dc713'}
POLISHER_SHA256 = '6cf96be3eef5d91e97110468a2e3aeba8f443aeec90dc50c4d17b2c0a1597d2c'
GRADE_EDITOR_SHA256 = 'aa8fef2acfe1c6577c7461662a1a6855a7279eb41d58f325d049fec9ef0fb093'
JSON_LD = re.compile(r'(<script\b[^>]*type="application/ld\+json"[^>]*>)(.*?)(</script>)', re.S)
FIELDS = re.compile(r'intro|sections\[\d+\]\.(?:heading|paragraphs\[\d+\])|faq\[\d+\]\.(?:question|answer)|cases\[\d+\]')
GYOHA = (
    ('모르는 척 넘기는 습관', '모르는 부분을 숨기고 넘기는 습관'),
    ('모르는 척하는 순간을 먼저 구분해 보기', '모르는 부분을 숨기는 순간을 먼저 구분해 보기'),
    ('학생이 모르는 척 넘긴 문항', '학생이 모르는 부분을 숨기고 넘긴 문항'),
    ('모르는 척한다고 판단하는 기준', '모르는 부분을 숨긴다고 판단하는 기준'),
    ('모르는 척하는 학생은 수업을 따라가기 어려운 학생으로 봐야 하나요?',
     '모르는 부분을 숨기는 학생은 수업을 따라가기 어려운 학생으로 봐야 하나요?'),
)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(value):
    return hashlib.sha256(value).hexdigest()


def normalized(value):
    return re.sub(r'\s+', ' ', value).strip()


def url(path):
    return DOMAIN + quote(path, safe='/')


def graph(soup):
    result = []
    for script in soup.select('script[type="application/ld+json"]'):
        value = json.loads(script.string or script.get_text())
        result.extend(value.get('@graph', [value]))
    return result


def scoped_grades(center, ref, subject):
    grades = center.get('subjects', {}).get(subject, {}).get('grades', [])
    if not grades or any(re.fullmatch(r'초[1-6]|중[1-3]|고[1-3]', g) is None for g in grades):
        return []
    overrides = ref.get('operations', {}).get('subjectDisplay', {})
    if overrides:
        scope = overrides.get(subject, {})
        if scope.get('status') not in ('recorded', 'recorded_with_conditions') or scope.get('includeInUnqualifiedAvailableSubjects') is not True:
            return []
        if 'sourceGrades' in scope and set(scope['sourceGrades']) != set(grades):
            return []
    elif subject not in center.get('availableSubjects', []):
        return []
    return list(dict.fromkeys(grades))


def complete_sentence_selection(before, after):
    old = re.split(r'(?<=[.!?])\s+', before.strip())
    new = re.split(r'(?<=[.!?])\s+', after.strip())
    if not new or old[0] != new[0] or not 100 <= len(after) <= 230 or len(after) >= len(before):
        return False
    remaining, selected = list(enumerate(old)), set()
    for sentence in new:
        match = next(((i, text) for i, text in remaining if text == sentence), None)
        if match is None:
            return False
        selected.add(match[0])
        remaining = [(i, text) for i, text in remaining if i > match[0]]
    for i, sentence in enumerate(old):
        if i in selected:
            continue
        if re.search(r'\d|[A-Za-z]|[×÷=]|[‘“「]|다만|단정|보장|개설|운영 여부', sentence.replace('고1', '')):
            return False
        if not re.search(r'상담|영어.{0,8}수학|수학.{0,8}영어|비교|질문', sentence):
            return False
    return True


def literal_table(path, name):
    module = ast.parse(path.read_text(encoding='utf-8'))
    return next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))


def reviewed_school_lists(value):
    """Independent implementation of the narrow, reviewed list-only contract."""
    school = re.compile(r'(?<![가-힣A-Za-z0-9])([가-힣0-9]{1,16}?(?:초등학교|중학교|고등학교|여중|여고|초|중|고))'
                        r'(?=(?:이나|처럼|에서|은|는|이|가|을|를|와|과|로|의|,|·|/|\s|$))')
    ignored = {'참고', '그리고', '말고', '않고', '보고', '집중', '그중', '이중', '도중', '고등', '중고', '초중',
               '과정중', '수업중', '학습중', '재학중', '비중'}
    fallback = '고1 상담에서는 재학 중인 고등학교의 수업 자료와 현재 평가 범위를 준비해 주세요.'

    def sentence_update(sentence):
        if (sentence.endswith('?') or not re.search(r'(?:제공된|제시된|안내된|참고|입력된).{0,12}학교|학교.{0,30}(?:제공|제시|포함)|학교명이 상담 대상|학교 가운데', sentence)
                or re.search(r'진학한|진학하기 전|학습 이력|학습한 경험|중학교 때|보조 자료|범위를 분리|상담과 범위|이전에|출신|자료가 아니|확대해석|연결해 판단할 근거', sentence)):
            return sentence
        names = [m for m in school.finditer(sentence) if m[1] not in ignored]
        groups = []
        for match in names:
            if groups and re.fullmatch(r'(?:\s|,|·|/|와|과|및|또는|이나|나)*', sentence[groups[-1][-1].end():match.start()]):
                groups[-1].append(match)
            else:
                groups.append([match])
        for group in reversed(groups):
            if not any(m[1].endswith(('초', '중', '초등학교', '중학교')) for m in group):
                continue
            high = [m[1] for m in group if m[1].endswith(('고', '고등학교'))]
            if high:
                tail = sentence[group[-1].end():]
                for old, new in [('이 ', '가 '), ('은 ', '는 '), ('과 ', '와 '), ('을 ', '를 ')]:
                    if tail.startswith(old):
                        tail = new + tail[len(old):]
                        break
                sentence = sentence[:group[0].start()] + ', '.join(high) + tail
            else:
                if (not re.search(r'학교.{0,8}(?:정보|명|목록)|학교명', sentence)
                        or not re.search(r'포함|적혀|제시|제공', sentence)
                        or any(m[1].endswith(('고', '고등학교')) for m in names)
                        or '제공된 지역 정보' in sentence
                        or re.search(r'\d|[A-Za-z]|[×÷=]', sentence.replace('고1', ''))):
                    continue
                caution = re.search(r'(?:하지만|있지만|으며|으므로|이므로|이며|이고),\s+(.+)', sentence)
                if caution and re.search(r'단정|추정|판단|별도로 확인', caution[1]):
                    return fallback + ' ' + re.sub(r'^(?:이 정보만으로|이 명칭만으로|학교명만으로)\s*', '학교 이름만으로 ', caution[1])
                return fallback
        return sentence

    result = re.sub(r'[^.!?]+[.!?](?:[”’])?|[^.!?]+$', lambda m: m[0][:len(m[0]) - len(m[0].lstrip())] + sentence_update(m[0].lstrip()), value)
    if fallback in result and fallback not in value and re.search(r'이 학교들|이 이름들|그 학교|이것만으로', value):
        return value
    return result


def replay_changes(raw_records, changes, check):
    """Closed display changes, replayed on independent ZIP-derived fields."""
    path = ROOT / 'tools/polish_branch_manuscripts.py'
    check(sha(path.read_bytes()) == POLISHER_SHA256, 'reviewed-generic-polisher-fingerprint')
    check(sha((ROOT / 'tools/branch_grade_manuscripts.py').read_bytes()) == GRADE_EDITOR_SHA256, 'reviewed-grade-editor-fingerprint')
    phrases, readers = literal_table(path, '_RULES'), literal_table(path, '_READER_RULES')
    grade_path = ROOT / 'tools/branch_grade_manuscripts.py'
    high1_phrases = literal_table(grade_path, '_HIGH1_READER_PHRASES')
    grade_ast = ast.parse(grade_path.read_text(encoding='utf-8'))
    high1_function = next(n for n in grade_ast.body if isinstance(n, ast.FunctionDef) and n.name == '_high1_reader_context')
    high1_starts = next(ast.literal_eval(n.value) for n in high1_function.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'starts' for t in n.targets))
    records, counts = copy.deepcopy(raw_records), Counter()
    for change in changes:
        key = (change['locality'], change['subject'])
        field = change['field']
        if key not in records or FIELDS.fullmatch(field) is None:
            check(False, 'closed-editorial-record-field', str(key), field)
            continue
        source = raw_records[key]
        check(change.get('grade') == '고1' and change.get('sourceMember') == source['sourceMember'], 'editorial-grade-source-identity', str(key))
        tokens = re.findall(r'([A-Za-z]+)|\[(\d+)\]', field)
        tokens = [name if name else int(index) for name, index in tokens]
        container = records[key]
        for token in tokens[:-1]:
            container = container[token]
        current = container[tokens[-1]]
        rule = change['rule']
        if change.get('stage') == 'grade-editorial':
            check(current == change['before'] and change['count'] == 1, 'grade-exact-before-field', str(key), field)
            permitted = False
            if rule == 'grade-complete-sentence-intro' and field == 'intro':
                permitted = complete_sentence_selection(current, change['after'])
            elif rule == 'grade-source-column-context' and not field.endswith('.heading'):
                permitted = current.replace('G에 제시된', '안내된').replace('D에 제공된 학교', '안내된 학교') == change['after']
            elif rule == 'grade-source-copy-context' and key == ('다산신도시', '수학') and re.fullmatch(r'sections\[\d+\]\.paragraphs\[\d+\]', field):
                permitted = current.replace('이 원고의 제공 사실에 포함되어 있지 않으므로', '이 안내에서 확인되지 않았으므로') == change['after']
            elif rule == 'grade-school-list-scope' and not field.endswith('.heading'):
                permitted = reviewed_school_lists(current) == change['after']
            elif rule == 'high1-reader-context' and not field.endswith('.heading'):
                expected = current
                for old, new in high1_phrases:
                    expected = expected.replace(old, new)
                for old, new in high1_starts:
                    expected = re.sub(r'(\A|(?<=[.!?])\s+)' + re.escape(old), lambda m: m[1] + new, expected)
                permitted = expected == change['after']
            check(permitted, 'closed-reviewed-grade-rule', str(key), rule + ':' + field)
            container[tokens[-1]] = change['after']
            counts['gradeEditorialFields'] += 1
        else:
            check(not field.endswith('.heading'), 'generic-polisher-cannot-edit-headings', str(key), field)
            if rule.startswith('reader-'):
                candidates = [(name, expression, after) for name, expression, after in readers if name == rule and after == change['after']]
                matches = next(([m for m in re.finditer(expression, current) if m[0] == change['before']]
                                for _, expression, _ in candidates if any(m[0] == change['before'] for m in re.finditer(expression, current))), [])
                check(bool(matches), 'reviewed-reader-exact-context', str(key), field)
                updated = current
                for match in reversed(matches):
                    updated = updated[:match.start()] + change['after'] + updated[match.end():]
                count = len(matches)
            else:
                check((rule, change['before'], change['after']) in phrases, 'reviewed-phrase-pair', str(key), field)
                updated, count = re.subn(r'(?<![가-힣A-Za-z0-9_])' + re.escape(change['before']), change['after'], current)
            check(count == change['count'], 'exact-editorial-phrase-count', str(key), field)
            container[tokens[-1]] = updated
            counts['polishedPhrases'] += count
    for key, original in raw_records.items():
        display = records[key]
        check(len(display['sections']) == len(original['sections']) and len(display['faq']) == 4
              and len(display['cases']) == len(original['cases']), 'original-section-faq-case-count-preservation', str(key))
        check([len(s['paragraphs']) for s in display['sections']] == [len(s['paragraphs']) for s in original['sections']], 'no-unapproved-paragraph-deletion', str(key))
        check([s['heading'] for s in display['sections']] == [s['heading'] for s in original['sections']], 'all-high1-source-headings-unchanged', str(key))
        for field in ('title', 'meta', 'locality', 'subject', 'grade', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256'):
            check(display[field] == original[field], 'immutable-source-display-' + field, str(key))
    return records, dict(counts)


def source_records(check, source_dir=None):
    """Independent strict parser of the six known blocks, with ZIP CRC checks."""
    records, facts = {}, []
    for subject in ('영어', '수학'):
        path = (Path(source_dir) if source_dir else DATA / 'sources') / ('고1 ' + subject + '학원.zip')
        archive_sha = sha(path.read_bytes())
        check(archive_sha == ARCHIVE_SHAS[subject], 'original-preflight-archive-sha256', path.name)
        original = Path('C:/Users/1992k/Desktop/프로그램 원고') / path.name
        if original.exists():
            check(sha(original.read_bytes()) == archive_sha, 'owner-archive-copy-byte-identical', path.name)
        with ZipFile(path) as archive:
            members = archive.infolist()
            check(len(members) == 371 and sum(i.file_size for i in members) < 100_000_000, 'archive-exact-count-bounded-size', path.name)
            seen = set()
            for info in members:
                name = info.filename
                member = PurePosixPath(name)
                key_name = unicodedata.normalize('NFC', name).casefold()
                safe = (not member.is_absolute() and len(member.parts) == 2 and '..' not in member.parts
                        and member.parts[0] == '고1 ' + subject + '학원' and member.suffix == '.txt'
                        and not any(c in name for c in ('\\', ':', '\0')) and key_name not in seen
                        and not info.flag_bits & 1 and not stat.S_ISLNK(info.external_attr >> 16)
                        and not info.is_dir() and 0 < info.file_size < 2_000_000)
                check(safe, 'safe-source-member', name)
                if not safe:
                    continue
                seen.add(key_name)
                raw = archive.read(info)
                text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
                markers = list(re.finditer(r'^\[([^\]\n]+)\]\s*$', text, re.M))
                check([m[1] for m in markers] == ['페이지타이틀', '메타설명', '본문', 'FAQ', '학부모후기', 'JSON-LD 요약'], 'source-blocks', name)
                blocks = {m[1]: text[m.end():markers[i + 1].start() if i + 1 < len(markers) else len(text)].strip() for i, m in enumerate(markers)}
                title = normalized(blocks['페이지타이틀'])
                suffix = ' 고1 ' + subject + '학원'
                locality = title.removesuffix(suffix)
                check(title == locality + suffix and member.stem == title, 'source-filename-title-grade', name)
                body = blocks['본문']
                headings = list(re.finditer(r'^##[ \t]+(.+)$', body, re.M))
                sections = []
                for i, heading in enumerate(headings):
                    end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
                    sections.append({'heading': normalized(heading[1]), 'paragraphs': [normalized(p) for p in re.split(r'\n\s*\n', body[heading.end():end]) if p.strip()]})
                faq = []
                for match in re.finditer(r'^Q(\d+)\.[ \t]*([^\n]+)\n\s*A(\d*)\.[ \t]*(.*?)(?=^Q\d+\.|\Z)', blocks['FAQ'], re.M | re.S):
                    check(int(match[1]) == len(faq) + 1 and match[3] in ('', match[1]), 'source-faq-numbering', name)
                    faq.append({'question': normalized(match[2]), 'answer': normalized(match[4])})
                check(len(faq) == 4, 'source-four-faqs', name)
                cases = re.sub(r'^※[^\n]*학부모 관점의 상황 예시입니다\.[ \t]*(?:\n|$)', '', blocks['학부모후기'], count=1).strip()
                key = (locality, subject)
                check(key not in records, 'source-unique-key', name)
                records[key] = {'title': title, 'locality': locality, 'subject': subject, 'grade': '고1',
                                'meta': normalized(blocks['메타설명']), 'intro': normalized(body[:headings[0].start()]),
                                'sections': sections, 'faq': faq, 'cases': [normalized(p) for p in re.split(r'\n\s*\n', cases) if p.strip()],
                                'sourceMember': name, 'sourceSha256': sha(raw), 'sourceArchiveSha256': archive_sha}
            facts.append({'path': path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path), 'sha256': archive_sha, 'members': len(members)})
    return records, facts


def exact_child_panel(child):
    return ('<section class="branch-panel branch-child-navigation" id="child-pages" aria-labelledby="child-pages-title">'
            '<h2 id="child-pages-title">학년별 학습 안내</h2><nav class="branch-child-links" aria-label="학년별 학습 안내">'
            '<a class="branch-child-link" href="' + escape(child['path'], quote=True) + '">' + escape(child['title'])
            + '</a></nav></section>')


def section_match(html, id_):
    matches = list(re.finditer(r'<section\b[^>]*\bid="' + re.escape(id_) + r'"[^>]*>.*?</section>', html, re.S))
    if len(matches) != 1:
        raise ValueError('Expected exactly one section#' + id_)
    return matches[0]


def restore_existing_html(before, after, kind, child=None):
    """Reverse only prepending the one exact high1 button to an existing high2 panel."""
    if kind != 'neighborhood' or child is None:
        raise ValueError('Only existing neighborhood parent navigation may change')
    old_soup, soup = BeautifulSoup(before, 'html.parser'), BeautifulSoup(after, 'html.parser')
    old_panel, new_panel = section_match(before, 'child-pages'), section_match(after, 'child-pages')
    old_links = old_soup.select('#child-pages a')
    if len(old_links) != 1 or not old_links[0]['href'].endswith('/고2/'):
        raise ValueError('Baseline must contain exactly one original high2 link')
    link = '<a class="branch-child-link" href="' + escape(child['path'], quote=True) + '">' + escape(child['title']) + '</a>'
    opening = '<nav class="branch-child-links" aria-label="학년별 학습 안내">'
    expected_panel = old_panel[0].replace(opening, opening + link, 1)
    if new_panel[0] != expected_panel:
        raise ValueError('Only the exact high1-before-high2 button addition is allowed')
    if soup.select_one('#child-pages').find_previous_sibling() != soup.select_one('#questions'):
        raise ValueError('Grade buttons must immediately follow the existing FAQ')
    expected_graph = copy.deepcopy(graph(old_soup))
    canonical = old_soup.select_one('link[rel="canonical"]')['href']
    listing = [n for n in expected_graph if n.get('@id') == canonical + '#child-pages']
    if len(listing) != 1 or listing[0].get('@type') != 'ItemList' or listing[0].get('numberOfItems') != 1:
        raise ValueError('Expected original one-child ItemList')
    listing[0]['numberOfItems'] = 2
    listing[0]['itemListElement'][0]['position'] = 2
    listing[0]['itemListElement'].insert(0, {'@type': 'ListItem', 'position': 1, 'name': child['title'], 'url': url(child['path'])})
    if sorted(graph(soup), key=lambda n: n['@id']) != sorted(expected_graph, key=lambda n: n['@id']):
        raise ValueError('Schema changed outside the exact high1 ItemList addition')
    restored = after[:new_panel.start()] + old_panel[0] + after[new_panel.end():]
    masked = lambda html: JSON_LD.sub(lambda m: m[1] + 'VERIFIED-JSON-LD' + m[3], html)
    if masked(before) != masked(restored):
        raise ValueError('Non-navigation HTML bytes changed')
    return True


def high_school_names(row):
    names = []
    for raw in row.get('targetSchools', {}).get('high', []):
        value = re.sub(r'\[([^\]]*(?:후보|확인\s*필요|미확인|\d{4}\s*통계)[^\]]*)\]', '', raw).strip()
        if re.sub(r'\s+', '', value) in ('지역내모든고등학교가능', '모든고등학교가능', '특성화고'):
            continue
        if value and value not in names:
            names.append(value)
    return names


def validate_new_page(record, source, display, parent, baseline, centers, reference, school_row, all_pages, check, counts, cache):
    path = record['path']
    soup = BeautifulSoup((ROOT / path.strip('/') / 'index.html').read_text(encoding='utf-8'), 'html.parser')
    old_parent = BeautifulSoup(baseline['pages'][parent['path'].strip('/') + '/index.html']['html'], 'html.parser')
    center = centers[record['centerId']]
    ref = reference['centers'].get(center['id'], {})
    canonical, parent_canonical = url(path), url(parent['path'])
    center_canonical = url(parent['parentPath'])
    scope_confirmed = '고1' in scoped_grades(center, ref, record['subject'])
    check(record['scopeConfirmed'] is scope_confirmed, 'manifest-current-high1-scope', path)
    for field in ('title', 'grade', 'locality', 'subject', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256'):
        check(record[field] == source[field], 'manifest-source-' + field, path)
    check(record['path'] == parent['path'] + '고1/' and record['parentPath'] == parent['path']
          and record['parentTitle'] == parent['title'] and record['centerPath'] == parent['parentPath']
          and record['centerId'] == parent['centerId'], 'exact-manifest-grade-parent-center-path', path)
    check(record['representative'] == parent['representative'], 'same-parent-representative-record', path)
    check(record['sectionCount'] == len(display['sections']) and record['faqCount'] == 4, 'manifest-section-faq-counts', path)
    full_title = source['title'] + old_parent.title.get_text()[len(parent['title']):]
    check(soup.title.get_text() == full_title and [h.get_text() for h in soup.select('h1')] == [source['title']], 'source-title-and-single-h1', path)
    for selector, attr, expected in (
        ('link[rel="canonical"]', 'href', canonical), ('meta[name="description"]', 'content', source['meta']),
        ('meta[property="og:url"]', 'content', canonical), ('meta[property="og:title"]', 'content', full_title),
        ('meta[property="og:description"]', 'content', source['meta']), ('meta[property="og:type"]', 'content', 'article')):
        nodes = soup.select(selector)
        check(len(nodes) == 1 and nodes[0].get(attr) == expected, 'new-head-' + selector, path)
    check('branch-neighborhood-page' in soup.body.get('class', []), 'shared-reader-body-class', path)
    check(soup.select_one('.branch-manuscript-intro').get_text() == display['intro'], 'approved-intro-copy', path)
    quick = soup.select_one('.branch-child-quick')
    check(any(p.strong and p.strong.get_text() == '학습 대상' and p.get_text(' ', strip=True) == '학습 대상 고1 ' + record['subject'] for p in quick.select('p')), 'visible-exact-high1-learning-audience', path)
    notice = soup.select('.branch-child-hero .branch-scope-notice')
    check(bool(notice) is (not scope_confirmed), 'scope-notice-present-iff-unconfirmed', path)
    if not scope_confirmed:
        expected_notice = '고1 ' + record['subject'] + ' 수업의 개설 여부와 상담 가능 학년을 먼저 확인해 주세요. 아래 글은 학습 준비를 위한 안내이며 해당 학년의 수업 개설을 뜻하지 않습니다.'
        check(len(notice) == 1 and notice[0].get_text() == expected_notice, 'unconfirmed-guide-not-offered-service-copy', path)
    images, old_images = soup.select('img'), old_parent.select('img')
    check(len(images) == len(old_images) == 3, 'exactly-three-primary-images', path)
    expected_images = copy.deepcopy([n.attrs for n in old_images])
    for attrs, suffix in zip(expected_images, (' 영수코칭 대표', ' 본문', ' 지도')):
        attrs['alt'] = source['title'] + suffix
    check([n.attrs for n in images] == expected_images, 'image-order-original-attributes-only-title-alt-change', path)
    check(images[0].get('style') == 'display:none;' and all('display:none' not in n.get('style', '') for n in images[1:]), 'original-representative-hidden-body-map-visible-policy', path)
    expected_media = copy.deepcopy(old_parent.select_one('.branch-primary-media'))
    for node, attrs in zip(expected_media.select('img'), expected_images):
        node.attrs = attrs
    check(str(soup.select_one('.branch-primary-media')) == str(expected_media), 'original-body-map-media-and-panel-dom', path)
    for attrs in expected_images:
        relative = unquote(urlsplit(attrs['src']).path).lstrip('/')
        check(relative in baseline['assets'] and sha((ROOT / relative).read_bytes()) == baseline['assets'][relative]['sha256'], 'original-image-file-sha', path)
    for i, section in enumerate(display['sections'], 1):
        node = soup.select_one('#section-' + str(i))
        check(node is not None and node.h2.get_text() == section['heading'], 'approved-section-heading', path)
        units = node.select('.branch-manuscript-unit')
        check([u.get('data-paragraph') for u in units] == [str(j) for j in range(len(section['paragraphs']))], 'logical-paragraph-order-count', path)
        check([' '.join(p.get_text() for p in u.select('p.branch-manuscript-paragraph')) for u in units] == section['paragraphs'], 'lossless-source-logical-paragraphs', path)
        counts['logicalParagraphs'] += len(units)
    groups = soup.select('#schools .branch-school-group')
    check(all(g.summary.get_text() == '고등학교' for g in groups), 'high-school-level-only', path)
    check([n.get_text() for n in soup.select('#schools .branch-school-list li')] == high_school_names(school_row), 'actual-reviewed-high-school-names', path)
    faq = [{'question': n.summary.get_text(), 'answer': n.p.get_text()} for n in soup.select('#questions details')]
    check(faq == display['faq'] and len(faq) == 4, 'source-approved-faq-four', path)
    cases = soup.select_one('#consultation-example details.branch-reading-example')
    check(cases is not None and not cases.has_attr('open') and cases.summary.get_text() == '준비할 자료와 질문 살펴보기', 'consultation-example-collapsed-label', path)
    check([p.get_text() for p in cases.select('p')] == display['cases'], 'source-case-paragraphs-preserved', path)
    check(soup.select_one('#child-pages') is None and soup.select_one('#grade-guides') is None, 'no-fabricated-further-grade-or-legacy-grade-links', path)
    expected_related = sorted([r for r in all_pages if r['centerId'] == record['centerId'] and r['path'] != path],
                              key=lambda r: (r['locality'] != record['locality'], r['locality'], r['subject']))[:6]
    check([a['href'] for a in soup.select('#related-pages a')] == [record['centerPath'], record['parentPath']] + [r['path'] for r in expected_related], 'related-links-same-center-and-grade', path)
    check([a['href'] for a in soup.select('#center-info .branch-actions a')] == [record['centerPath'] + '#tuition', record['centerPath'] + '#directions'], 'unchanged-center-fee-location-targets', path)
    check(str(soup.select_one('.floating-actions')) == str(old_parent.select_one('.floating-actions')), 'common-phone-cta-preservation', path)
    nodes = graph(soup)
    by_type = defaultdict(list)
    for n in nodes:
        by_type[n.get('@type')].append(n)
    check(len(by_type['Article']) == len(by_type['WebPage']) == len(by_type['FAQPage']) == len(by_type['EducationalOrganization']) == 1, 'required-schema-node-counts', path)
    article, webpage = by_type['Article'][0], by_type['WebPage'][0]
    check(article.get('@id') == canonical + '#article' and article.get('url') == canonical
          and article.get('mainEntityOfPage') == {'@id': canonical + '#webpage'} and article.get('headline') == source['title']
          and article.get('description') == source['meta'] and article.get('educationalLevel') == '고1', 'exact-high1-article-identity', path)
    check(article.get('isPartOf') == webpage.get('isPartOf') == {'@id': parent_canonical + '#webpage'}
          and webpage.get('mainEntity') == {'@id': canonical + '#article'}, 'article-page-parent-relationship', path)
    check(article.get('articleSection') == [s['heading'] for s in display['sections']], 'schema-source-heading-parity', path)
    old_org = next(n for n in graph(old_parent) if n.get('@type') == 'EducationalOrganization')
    check(by_type['EducationalOrganization'][0] == old_org and old_org['@id'] == center_canonical + '#center', 'same-real-center-organization-not-new-branch', path)
    services = by_type['Service']
    check(len(services) == int(scope_confirmed), 'service-only-exact-high1-confirmed', path)
    if services:
        service = services[0]
        check(service.get('@id') == canonical + '#service' and service.get('provider') == {'@id': center_canonical + '#center'}
              and service.get('serviceType') == '고1 ' + record['subject'] + ' 학습코칭'
              and service.get('mainEntityOfPage') == {'@id': canonical + '#webpage'}, 'grade-service-provider-identity', path)
    else:
        check('#service' not in json.dumps(nodes, ensure_ascii=False), 'no-dangling-unconfirmed-service-reference', path)
    check(by_type['FAQPage'][0]['mainEntity'] == [{'@type': 'Question', 'name': f['question'], 'acceptedAnswer': {'@type': 'Answer', 'text': f['answer']}} for f in faq], 'visible-schema-faq-exact-parity', path)
    crumbs = soup.select('.branch-breadcrumb li')
    check(len(crumbs) == 6 and crumbs[-1].get_text() == source['title']
          and crumbs[-2].a['href'] == record['parentPath'] and crumbs[-3].a['href'] == record['centerPath'], 'six-level-visible-breadcrumb', path)
    crumb_nodes = by_type['BreadcrumbList'][0]['itemListElement']
    check(len(crumb_nodes) == 6 and [n['position'] for n in crumb_nodes] == list(range(1, 7))
          and [n['item'] for n in crumb_nodes] == [url('/'), url('/지점안내/'), url('/지점안내/' + center['region']['province'] + '/'), center_canonical, parent_canonical, canonical], 'six-level-schema-breadcrumb', path)
    ids = [n['id'] for n in soup.select('[id]')]
    check(len(ids) == len(set(ids)), 'unique-html-ids', path)
    visible = soup.body.get_text(' ', strip=True)
    check(re.search(r'원고\s*참고\s*키워드|[FG]\s*(?:열)?에\s*제시된|입력된\s*학교\s*정보|이\s*원고|상담 참고 항목로', visible) is None,
          'no-known-internal-writing-notes', path)
    for anchor in soup.select('a[href]'):
        parsed = urlsplit(anchor['href'])
        if parsed.scheme in ('tel', 'sms', 'mailto') or parsed.netloc and parsed.netloc != urlsplit(DOMAIN).netloc:
            continue
        route = unquote(parsed.path) or path
        target = ROOT / route.strip('/')
        if not target.suffix:
            target /= 'index.html'
        check(target.is_file(), 'existing-local-href', anchor['href'])
        if parsed.fragment and target.is_file():
            key = str(target)
            if key not in cache:
                cache[key] = {n['id'] for n in BeautifulSoup(target.read_text(encoding='utf-8'), 'html.parser').select('[id]')}
            check(unquote(parsed.fragment) in cache[key], 'existing-href-fragment', anchor['href'])
    counts['servicePages' if scope_confirmed else 'learningGuideOnlyPages'] += 1
    counts['newPages'] += 1


def run(args):
    with gzip.open(args.baseline, 'rt', encoding='utf-8') as stream:
        baseline = json.load(stream)
    counts, errors = Counter(), []

    def check(ok, kind, location='', detail=None):
        counts['assertions'] += 1
        if not ok:
            errors.append({'check': kind, 'location': location, **({'detail': detail} if detail is not None else {})})

    manifest = read(DATA / 'pages.json')
    extras = read(args.baseline.parent / 'public-extra-before.json')
    for relative, old in extras['pages'].items():
        check(sha((ROOT / relative).read_bytes()) == old['sha256'], 'remaining-public-entry-page-byte-preservation', relative)
        counts['preservedExtraPublicPages'] += 1
    check(len(baseline['pages']) + len(extras['pages']) == len(extras['sitemapUrls']) == 3930,
          'pre-high1-checkpoint-covers-all-3930-public-pages')
    pages = [r for r in manifest['pages'] if r['grade'] == '고1']
    parents = read(ROOT / 'tools/data/branch-neighborhoods/pages.json')['pages']
    parent_by_key = {(p['locality'], p['subject']): p for p in parents}
    children_by_parent = {r['parentPath'].strip('/') + '/index.html': r for r in pages}
    centers_with_children = set()  # Center and all high2 HTML must remain byte-identical.
    check(len(pages) == len(children_by_parent) == 742, '742-grade-pages-and-parents')
    check(manifest['parentManifestSha256'] == sha((ROOT / 'tools/data/branch-neighborhoods/pages.json').read_bytes()), 'parent-manifest-sha')
    prior_manifest = copy.deepcopy(manifest)
    prior_manifest['archives'] = [r for r in manifest['archives'] if r['grade'] != '고1']
    prior_manifest['pages'] = [r for r in manifest['pages'] if r['grade'] != '고1']
    prior_manifest_bytes = (json.dumps(prior_manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    check(sha(prior_manifest_bytes) == baseline['sourceFiles']['tools/data/branch-grades/pages.json']['sha256'],
          'merged-manifest-reverses-to-exact-original-high2-manifest')
    check(len(manifest['pages']) == 1484 and {r['grade'] for r in manifest['pages']} == {'고1', '고2'},
          'manifest-only-existing-high2-and-new-high1')
    expected = set(baseline['pages']) | {r['path'].strip('/') + '/index.html' for r in pages}
    actual = {p.relative_to(ROOT).as_posix() for top in ('지점안내', '과목별학원') for p in (ROOT / top).rglob('index.html')}
    check(actual == expected, 'complete-path-set-exactly-742-additions')
    for relative, old in baseline['pages'].items():
        raw = (ROOT / relative).read_bytes()
        if relative in centers_with_children or relative in children_by_parent:
            kind = 'center' if relative in centers_with_children else 'neighborhood'
            try:
                restore_existing_html(old['html'], raw.decode('utf-8'), kind, children_by_parent.get(relative))
                counts['preservedCentersWithRelocatedNavigation' if kind == 'center' else 'preservedNeighborhoodParentsWithGradeLink'] += 1
            except (ValueError, KeyError, AttributeError) as exc:
                check(False, 'existing-exact-navigation-only', relative, str(exc))
        else:
            check(sha(raw) == old['sha256'], 'untouched-existing-page-byte-preservation', relative)
            counts['untouchedExistingPages'] += 1
            if relative.endswith('/고2/index.html'):
                counts['preservedHigh2Pages'] += 1
    for category in ('assets', 'sourceFiles'):
        for relative, old in baseline[category].items():
            if relative == 'tools/data/branch-grades/pages.json':
                continue  # Checked by exact reversal of only the high1 rows below.
            path = ROOT / relative
            check(path.is_file() and sha(path.read_bytes()) == old['sha256'], 'existing-' + category + '-sha256', relative)
            counts['preservedAssets' if category == 'assets' else 'preservedSourceFiles'] += 1
    expected_sources = set(baseline['sourceFiles']) | {'tools/data/branch-grades/pages.json',
                        'tools/data/branch-grades/sources/고1 영어학원.zip', 'tools/data/branch-grades/sources/고1 수학학원.zip'}
    actual_sources = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'tools/data').rglob('*') if p.is_file()}
    check(actual_sources == expected_sources, 'only-two-approved-new-archive-artifacts')
    raw_records, archives = source_records(check)
    check({(r['grade'], r['subject'], r['sha256'], r['count']) for r in manifest['archives'] if r['grade'] == '고1'}
          == {('고1', subject, digest, 371) for subject, digest in ARCHIVE_SHAS.items()}, 'manifest-original-archive-records')
    changes = read(REPORTS / '고1-editorial.json')['changes']
    displays, editorial_counts = replay_changes(raw_records, changes, check)
    reference = read(ROOT / 'tools/data/branches/reference-content.json')
    centers = {c['id']: c for c in read(ROOT / 'tools/data/branches/centers.json')['centers'] + reference.get('additionalCenters', [])}
    schools = {r['neighborhood']: r for r in read(ROOT / 'tools/data/branches/target-schools.json')}
    check(set(raw_records) == set(parent_by_key) == {(p['locality'], p['subject']) for p in pages}, 'exact-742-source-parent-child-key-coverage')
    cache = {}
    for record in pages:
        try:
            key = (record['locality'], record['subject'])
            validate_new_page(record, raw_records[key], displays[key], parent_by_key[key], baseline, centers,
                              reference, schools.get(record['locality'], {}), pages, check, counts, cache)
        except (ValueError, KeyError, AttributeError, TypeError, IndexError) as exc:
            check(False, 'new-page-audit-exception', record['path'], str(exc))
    check(counts['preservedCentersWithRelocatedNavigation'] == 0 and counts['preservedNeighborhoodParentsWithGradeLink'] == 742
          and counts['untouchedExistingPages'] == 3185, 'existing-page-scope-coverage')
    check(counts['newPages'] == 742 and counts['servicePages'] == 719 and counts['learningGuideOnlyPages'] == 23, 'grade-page-service-719-guide-23-coverage')
    generation = read(REPORTS / '고1-generation.json')
    check(generation['generatedPages'] == 742 and generation['scopeConfirmed'] == 719
          and set(generation['scopeConfirmationNeeded']) == {p['path'] for p in pages if not p['scopeConfirmed']}, 'generation-report-matches-audited-scope')
    check(counts['preservedHigh2Pages'] == 742, 'every-existing-high2-html-byte-preserved')
    actual_assets = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'assets').rglob('*') if p.is_file()}
    check(actual_assets == set(baseline['assets']), 'no-added-or-deleted-image-assets')
    locs = [n.text for n in ET.parse(ROOT / 'sitemap.xml').getroot().iter() if n.tag.rsplit('}', 1)[-1] == 'loc']
    check(len(locs) == len(set(locs)), 'sitemap-unique')
    check(set(locs) == set(extras['sitemapUrls']) | {url(r['path']) for r in pages} and len(locs) == 4672,
          'sitemap-all-original-3930-plus-only-new-742')
    counts['publicSitemapPages'] = len(locs)
    check(len(ET.parse(ROOT / 'rss.xml').findall('.//item')) == 9, 'rss-valid-nine-items')
    for record in pages:
        check(locs.count(url(record['path'])) == 1, 'grade-sitemap-exactly-once', record['path'])
    result = {'status': 'FAIL' if errors else 'PASS', 'grade': '고1', 'createdAt': datetime.now(timezone.utc).isoformat(),
              'baseline': str(args.baseline), 'counts': dict(counts), 'archives': archives, 'editorialCounts': editorial_counts, 'errors': errors,
              'visualRender': 'Not claimed; browser interaction checks are performed separately by root.'}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=BASELINE)
    parser.add_argument('--report', type=Path, default=REPORTS / '고1-audit.json')
    result = run(parser.parse_args())
    print(json.dumps({'status': result['status'], 'counts': result['counts'], 'errorCount': len(result['errors']),
                      'firstErrors': result['errors'][:12]}, ensure_ascii=False, indent=2))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
