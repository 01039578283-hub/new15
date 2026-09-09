"""Generate directory -> province -> center pages from reviewed source data.

Approved neighborhood children are generated separately and linked by manifest.
No deploy, API calls, or source manuscript rewrites.
Import snapshots with --import-from PATH once; ordinary reruns use tools/data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from html import escape, unescape
from pathlib import Path
from urllib.parse import quote

from generate_subject_pages import DOMAIN, ROOT, SHARE_IMAGE_URL, page_head, site_header, site_footer
from branch_copy_corrections import apply_branch_copy_corrections

DATA = ROOT / 'tools' / 'data' / 'branches'
REPORTS = ROOT / 'reports' / 'branches'
REGIONS = ['서울', '경기', '인천', '부산', '대구', '광주', '대전', '울산', '세종', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']
LEVELS = {'elementary': '초등학교', 'middle': '중학교', 'high': '고등학교'}
FEES = {
    '서울': {'초등': [179000, 249000, 389000], '중등': [191000, 266000, 416000], '고등': [214000, 299000, 469000]},
    '서울 외': {'초등': [159000, 219000, 339000], '중등': [171000, 236000, 366000], '고등': [194000, 269000, 419000]},
}
HUB = '/지점안내/'
# Removed at the owner's request; keep the original workbook snapshot untouched.
EXCLUDED_GLORID_IDS = {'center-row-113', 'center-row-152'}
EXCLUDED_WPLUS_IDS = {'center-row-026', 'center-row-048', 'center-row-104', 'center-row-114',
                     'center-row-153', 'center-row-169', 'center-row-200', 'center-row-202'}
EXCLUDED_CENTER_IDS = EXCLUDED_GLORID_IDS | EXCLUDED_WPLUS_IDS | {'center-row-034', 'reference-경기-주엽2호점'}
IGNORED = {'.git', '.vercel', 'tools', 'reports', 'node_modules', 'test-results', 'playwright-report', 'tmp'}


def load_branch_data():
    """Keep the original workbook snapshot immutable; layer reviewed website data."""
    bundle = json.loads((DATA / 'centers.json').read_text(encoding='utf-8'))
    reference_path = DATA / 'reference-content.json'
    reference = json.loads(reference_path.read_text(encoding='utf-8')) if reference_path.exists() else {}
    editorial_path = DATA / 'editorial-content.json'
    if editorial_path.exists():
        editorial = json.loads(editorial_path.read_text(encoding='utf-8'))['centers']
        assert set(editorial) == set(reference['centers']), 'Incomplete editorial dataset'
        for cid, content in editorial.items():
            reference['centers'][cid]['editorial'] = content
    media_path = DATA / 'branch-media.json'
    if media_path.exists():
        media = json.loads(media_path.read_text(encoding='utf-8'))['centers']
        for cid, content in media.items():
            reference['centers'][cid]['primaryMedia'] = content
    centers = bundle['centers'] + reference.get('additionalCenters', [])
    child_manifest = ROOT / 'tools/data/branch-neighborhoods/pages.json'
    children = json.loads(child_manifest.read_text(encoding='utf-8'))['pages'] if child_manifest.exists() else []
    for c in centers:
        c['_neighborhoodPages'] = [p for p in children if p['centerId'] == c['id']]
        for child in c['_neighborhoodPages']:
            assert child['path'].startswith(branch_path(c)) and len(child['path'].strip('/').split('/')) == 4, 'Invalid child-parent relationship'
        apply_branch_copy_corrections(c, reference.get('centers', {}).get(c['id'], {}))
        operations = reference.get('centers', {}).get(c['id'], {}).get('operations', {})
        summaries = operations.get('subjectDisplay', {})
        if summaries:
            names = []
            for name in c['subjects']:
                detail = summaries.get(name, {})
                if detail.get('includeInUnqualifiedAvailableSubjects'):
                    names.append(name)
                elif detail.get('status') == 'note_only_scope':
                    names.append(name + '(학년 확인)')
            c['_displaySubjects'] = names
    assert len({c['id'] for c in centers}) == len(centers)
    assert len({branch_path(c) for c in centers}) == len(centers)
    return bundle, [c for c in centers if c['id'] not in EXCLUDED_CENTER_IDS], reference


def subject_summary(c, name, data, reference):
    override = reference.get('operations', {}).get('subjectDisplay', {}).get(name)
    return reader_text(override['summary'] if override else grade_ranges(data['grades']))


def weekend_summary(c, reference):
    override = reference.get('operations', {}).get('weekend', {})
    return reader_text(override.get('summary') or op(c, 'weekendAvailability') or '상담 시 확인')


def weekend_detail(c, reference):
    data = reference.get('operations', {}).get('weekend', {})
    if data.get('status') == 'subject_notes_not_schedule':
        return ''
    if data.get('status') == 'time_confirmation_needed':
        return '토요일 수업의 과목별 시작·종료 시간은 상담에서 확인해 주세요.'
    if data.get('status') == 'schedule_scope_unrecorded':
        return '주말 수업의 진행 여부와 대상 과목, 시간표를 상담에서 확인해 주세요.'
    return reader_text(data.get('detail') or op(c, 'weekendScheduleAndSubjects'))


def course_answer(c, reference):
    sentences = []
    for name, data in c['subjects'].items():
        row = reference.get('operations', {}).get('subjectDisplay', {}).get(name, {})
        if not data['grades'] and not row:
            continue
        detail = reader_text(row.get('detail', ''))
        text = name + ' ' + subject_summary(c, name, data, reference)
        if detail:
            text += ' (' + detail.rstrip('.') + ')'
        sentences.append(text)
    return '; '.join(sentences) or '희망 과목과 현재 학년을 알려주시면 가능한 수업을 확인할 수 있습니다'


def location_copy(reference):
    result = []
    for value in reference.get('locationParagraphs', []):
        if re.search(r'걸어서|부담이|꾸준히 다니|안전하게|편리하게', value):
            continue
        value = re.sub(r'\s*(?:도보\s*\d+(?:~\d+)?분|\d+(?:\.\d+)?\s*(?:km|m)(?![a-zA-Z]))', '', value)
        result.append(value.replace('주변 위치 참고:', '주변 위치:'))
    return result


def reader_text(value):
    value = value.replace('자료상 ', '').replace('자료에 기재된 ', '')
    value = value.replace('과목별 학년 범위와 운영 안내가 서로 달라 확정 안내가 어렵습니다. ', '')
    value = value.replace('주말 정규수업·보강 일정의 안내가 서로 달라 현재 시간표를 확인해야 합니다.', '주말 정규수업과 보강의 가능 시간은 상담에서 확인해 주세요.')
    value = value.replace('현재 수업 미운영 안내', '수업 미운영 안내')
    return value


def confirmed_courses(c, reference):
    operations = reference.get('operations', {}).get('subjectDisplay', {})
    return [(name, subject_summary(c, name, data, reference)) for name, data in c['subjects'].items()
            if data['grades'] and (not operations or operations.get(name, {}).get('includeInUnqualifiedAvailableSubjects'))]


def branch_summary(c, reference):
    place = ' '.join(dict.fromkeys([c['region']['province'], c['region']['administrativeAreaText']])).strip()
    courses = confirmed_courses(c, reference)
    first = f'{place}에 있는 {c["displayName"]}입니다.'
    if c.get('addressPrecision') == 'neighborhood':
        first = f'{c["displayName"]}의 안내 위치는 {c["address"]}입니다. 상세 도로명 주소와 건물·층수는 방문 전에 확인해 주세요.'
    if courses:
        ordered = sorted(courses, key=lambda row: ['영어', '수학', '국어', '과학', '사회'].index(row[0]))
        primary = ordered[:2]
        other = ordered[2:]
        text = first + ' ' + '; '.join(f'{name} {grades}' for name, grades in primary) + ' 수업을 안내합니다.'
        if other:
            text += ' ' + '·'.join(name for name, _ in other) + '의 학년 범위와 세부 조건은 과목표에서 확인해 주세요.'
        else:
            text += ' 세부 과정과 요일별 시간표는 상담에서 확인할 수 있습니다.'
        return text
    return first + ' 희망 과목과 학년을 알려주시면 가능한 과정과 학습 계획을 함께 확인할 수 있습니다.'


def branch_description(c, reference):
    courses = confirmed_courses(c, reference)
    labels = '·'.join(name for name, _ in courses)
    first = f'{c["displayName"]}. {c["address"]}. '
    return first + (labels + ' 수업의 가능 학년, ' if labels else '수업 과정과 ') + '교육비·학교별 상담 준비·학습관리 방법을 안내합니다.'


CURRICULUM_COPY = {
    '수학': {'초등': '계산 과정과 개념 이해를 나누어 살핍니다. 문장제는 조건을 식으로 옮기는 과정부터 확인합니다.', '중등': '방정식·함수·도형에서 막히는 개념을 구분합니다. 틀린 문제는 풀이 근거를 설명하고 조건이 다른 문제에 다시 적용해 봅니다.', '고등': '학교 시험 범위와 선택 과목에 맞춰 개념·계산·문제 해석을 점검합니다. 풀이가 막힌 단계와 시간 사용을 기록해 복습 순서를 정합니다.'},
    '영어': {'초등': '소리와 철자의 연결, 어휘 이해, 짧은 문장 읽기를 구분해 살핍니다. 읽을 수 있는 단어와 뜻을 설명할 수 있는 단어의 차이를 확인합니다.', '중등': '교과서 본문과 문법을 연결해 읽고, 서술형 답안에서 어순·시제·문장 성분을 확인합니다. 정답뿐 아니라 선택 근거를 설명하는 연습이 중요합니다.', '고등': '긴 문장의 구조, 문장 사이의 논리, 어법 판단 근거를 나누어 점검합니다. 학교 시험 범위와 모의고사에서 어려웠던 유형을 구분해 준비합니다.'},
    '국어': {'초등': '문단의 중심 내용을 찾고 자신의 말로 요약해 봅니다. 낯선 어휘의 뜻을 문맥에서 짐작한 뒤 정확한 뜻을 확인합니다.', '중등': '문학·독서·문법에서 어려운 영역을 구분합니다. 지문 속 근거를 찾고 질문에 맞는 답안을 쓰는 과정을 살펴봅니다.', '고등': '지문의 구조와 선지의 판단 근거를 연결합니다. 학교 시험과 수능형 문제의 요구를 나누어 읽기와 답안 작성 전략을 점검합니다.'},
    '과학': {'초등': '생활 속 현상을 관찰하고 원인을 설명해 봅니다. 과학 용어를 외우는 것과 개념을 예로 설명하는 것을 구분합니다.', '중등': '단원별 핵심 개념과 자료 해석을 연결합니다. 실험 조건·결과·결론을 구분하고 틀린 문제의 개념으로 돌아가 확인합니다.', '고등': '현재 배우는 과목과 시험 범위를 먼저 확인합니다. 개념 설명, 그래프 해석, 계산 중 보완할 부분을 나누어 학습 계획을 세웁니다.'},
    '사회': {'초등': '지역과 생활 속 사례로 핵심 개념을 이해합니다. 용어의 뜻을 설명하고 지도·사진·표에서 근거를 찾는 연습을 합니다.', '중등': '역사적 흐름과 사회 개념의 관계를 함께 살핍니다. 지도·그래프·사료를 읽고 질문에 맞는 근거를 고르는 과정을 확인합니다.', '고등': '현재 배우는 과목의 개념과 자료 분석을 구분해 점검합니다. 비슷한 개념의 차이를 설명하고 제시문에서 판단 근거를 찾습니다.'},
}


def esc(value):
    return escape(str(value), quote=True)


def url(path):
    return DOMAIN + quote(path, safe='/')


def write_changed(path, value):
    data = value.encode('utf-8')
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def branch_path(center):
    return HUB + center['region']['province'] + '/' + center['routeSlug'] + '/'


def breadcrumb(items):
    return '<nav aria-label="현재 위치"><ol class="branch-breadcrumb">' + ''.join(
        f'<li><a href="{esc(path)}">{esc(name)}</a></li>' if i < len(items) - 1 else f'<li><span aria-current="page">{esc(name)}</span></li>'
        for i, (name, path) in enumerate(items)
    ) + '</ol></nav>'


def button(path, text, secondary=False, external=False):
    attrs = ' target="_blank" rel="noopener noreferrer"' if external else ''
    return f'<a class="branch-button{" secondary" if secondary else ""}" href="{esc(path)}"{attrs}>{esc(text)}</a>'


def paragraph(value, css=''):
    return f'<p class="{css}">{esc(value)}</p>'


def base_graph(title, desc, path, crumbs, kind='WebPage'):
    return [
        {'@type': 'WebSite', '@id': DOMAIN + '/#website', 'name': '영수코칭', 'url': DOMAIN + '/', 'inLanguage': 'ko-KR'},
        {'@type': kind, '@id': url(path) + '#webpage', 'url': url(path), 'name': title, 'description': desc, 'inLanguage': 'ko-KR',
         'isPartOf': {'@id': DOMAIN + '/#website'}, 'breadcrumb': {'@id': url(path) + '#breadcrumb'}},
        {'@type': 'BreadcrumbList', '@id': url(path) + '#breadcrumb', 'itemListElement': [
            {'@type': 'ListItem', 'position': i + 1, 'name': name, 'item': url(href)} for i, (name, href) in enumerate(crumbs)
        ]},
    ]


def itemlist(path, items):
    return {'@type': 'ItemList', '@id': url(path) + '#list', 'numberOfItems': len(items), 'itemListElement': [
        {'@type': 'ListItem', 'position': i + 1, 'name': name, 'url': url(href)} for i, (name, href) in enumerate(items)
    ]}


def page(title, desc, path, crumbs, body, graph, detail=False):
    parts = []
    for section_id, heading in re.findall(r'<section class="branch-panel(?: [^"]+)?" id="([^"]+)"[^>]*>(?:<p[^>]*>.*?</p>)?(?:<details class="branch-space-disclosure"><summary>)?<h2(?: [^>]*)?>(.*?)</h2>', body):
        part_id = url(path) + '#' + section_id
        parts.append({'@type': 'WebPageElement', '@id': part_id, 'url': part_id, 'name': unescape(re.sub('<[^>]+>', '', heading)), 'isPartOf': {'@id': url(path) + '#webpage'}})
    if parts:
        graph[1]['hasPart'] = [{'@id': p['@id']} for p in parts]
        # FAQPage already owns the questions anchor; merge its page-element relation.
        for part in parts:
            existing = next((x for x in graph if x.get('@id') == part['@id']), None)
            if existing:
                existing['isPartOf'] = part['isPartOf']
                existing['name'] = part['name']
            else:
                graph.append(part)
    head = page_head(title=title, description=desc, canonical=url(path), asset_prefix='/', image_url=SHARE_IMAGE_URL, graph=graph, page_type='website')
    head = head.replace('</head>', '<link rel="stylesheet" href="/assets/branches.css">\n</head>')
    # Share the exact phone / message / consultation controls used by subject pages.
    footer = site_footer()
    search_script = '<script src="/assets/branch-search.js" defer></script>' if not detail else ''
    return '<!DOCTYPE html>\n<html lang="ko">\n' + head + '\n<body class="branch-page' + (' branch-detail-page' if detail else '') + '">\n' + site_header('branches') + '<main id="main"><div class="shell">' + breadcrumb(crumbs) + body + '</div></main>' + footer + '<script src="/assets/site.js" defer></script>' + search_script + '\n</body></html>\n'


def search_controls(region='전국'):
    return ('<div class="branch-search-controls" data-branch-search-controls hidden>'
            '<label for="branch-search-input">' + esc(region) + ' 지점 검색</label>'
            '<p id="branch-search-help">지점명·지역명·동네명으로 찾아보세요. 예: 명일, 성남, 위례</p>'
            '<div class="branch-search-field"><input id="branch-search-input" data-branch-search-input '
            'type="search" placeholder="지점명 또는 지역명 입력" autocomplete="off" maxlength="100" '
            'aria-describedby="branch-search-help branch-search-status" aria-controls="branch-search-results">'
            '<button type="button" data-branch-search-reset disabled>초기화</button></div>'
            '<p id="branch-search-status" class="branch-search-status" data-branch-search-status role="status" aria-live="polite" aria-atomic="true"></p>'
            '<p class="branch-search-empty" data-branch-search-empty hidden>일치하는 지점이 없습니다. 검색어를 줄이거나 다른 지역명으로 검색해 주세요.</p>'
            '</div><noscript><p>지역별 링크를 선택해 지점을 찾아보세요. 검색은 JavaScript를 켜면 사용할 수 있습니다.</p></noscript>')


def directory_page(centers):
    regions = [r for r in REGIONS if any(c['region']['province'] == r for c in centers)]
    crumbs = [('홈', '/'), ('지점안내', HUB)]
    title = '전국 지점안내 | 영수코칭'
    desc = '가까운 지역의 와와학습코칭학원과 모두오름학원코칭학원을 찾아보세요. 지점별 주소, 수업 과목·학년, 교육비와 학교 목록을 안내합니다.'
    graph = base_graph(title, desc, HUB, crumbs, 'CollectionPage')
    graph.append(itemlist(HUB, [(r + ' 지점안내', HUB + r + '/') for r in regions]))
    graph[1]['mainEntity'] = {'@id': url(HUB) + '#list'}
    body = '''<section class="branch-hero"><p class="branch-eyebrow">FIND YOUR LEARNING CENTER</p>
<h1>전국 지점안내</h1>
<p class="branch-intro">와와학습코칭학원 · 모두오름학원코칭학원<br>지역을 선택하고, 지점별 수업과 방문 정보를 살펴보세요.</p>
<div class="branch-actions">''' + button('#regions', '지역별 지점 찾기') + button('/상담문의/', '상담 전 준비사항', True) + '</div></section>'
    body += '<section class="branch-search-section" data-branch-search-root data-search-mode="directory" aria-label="전국 지점 검색">' + search_controls()
    body += '<div id="branch-search-results" class="branch-center-grid" data-branch-search-results hidden>' + ''.join(center_card(c, searchable=True) for c in sorted(centers, key=lambda c: (c['sourceCenterName'], c['region']['province']))) + '</div></section>'
    body += '<section class="branch-section" id="regions"><div class="branch-section-heading"><h2>어느 지역을 찾으세요?</h2><p>지역 → 지점 순서로 찾아보세요.</p></div><div class="branch-region-grid">'
    body += ''.join(f'<a class="branch-region-link" href="{HUB}{r}/"><strong>{r}</strong><span aria-hidden="true">↗</span></a>' for r in regions)
    body += '</div></section><section class="branch-guide" aria-label="지점 안내 활용 방법">'
    for title_, text_ in [('01  지역과 위치', '주소와 지점명을 함께 확인하면 이름이 비슷한 지점을 구분하기 쉽습니다.'), ('02  과목과 학년', '센터마다 수업 가능한 과목과 학년이 다릅니다. 상세 안내에서 먼저 확인해 주세요.'), ('03  교육비와 상담', '서울과 서울 외 교육비를 구분해 안내합니다. 학생의 학년과 희망 과목을 준비해 주세요.')]:
        body += '<div><strong>' + esc(title_) + '</strong>' + paragraph(text_) + '</div>'
    body += '</section>'
    return HUB, page(title, desc, HUB, crumbs, body, graph)


def center_card(c, searchable=False):
    subjects = ' · '.join(c.get('_displaySubjects', c['availableSubjects'])) or '과목 상담 필요'
    search_attr = ''
    if searchable:
        terms = [c['sourceCenterName'], c['displayName'], c['brandName'], c['address'],
                 c['region']['province'], c['region']['administrativeAreaText'],
                 c['region']['province'] + c['sourceCenterName'], *c.get('_searchNeighborhoods', [])]
        search_attr = ' data-branch-search="' + esc(' '.join(terms)) + '"'
    return f'<a class="branch-center-card" href="{esc(branch_path(c))}"{search_attr}><div><span class="branch-card-brand">{esc(c["brandName"])}</span><h3>{esc(c["sourceCenterName"])}</h3></div><p>{esc(c["address"])}</p><div class="branch-card-end"><span>{esc(subjects)}</span><strong>지점 안내 →</strong></div></a>'


def region_page(region, centers, reference=None):
    reference = reference or {}
    gallery = ''
    path = HUB + region + '/'
    crumbs = [('홈', '/'), ('지점안내', HUB), (region, path)]
    title = region + ' 지점안내 | 영수코칭'
    cities = list(dict.fromkeys(c['region']['administrativeAreaText'] for c in centers if c['region']['administrativeAreaText']))
    citytext = ', '.join(cities[:3]) + (' 등' if len(cities) > 3 else '')
    desc = region + ' ' + citytext + '의 학원 지점을 찾아보세요. 주소, 과목별 가능 학년과 교육비를 비교하고 학교·시간표에 맞춰 상담을 준비할 수 있습니다.'
    graph = base_graph(title, desc, path, crumbs, 'CollectionPage')
    ordered = sorted(centers, key=lambda c: (c['region']['administrativeAreaText'], c['sourceCenterName']))
    graph.append(itemlist(path, [(c['displayName'], branch_path(c)) for c in ordered]))
    graph[1]['mainEntity'] = {'@id': url(path) + '#list'}
    body = '<section class="branch-hero"><p class="branch-eyebrow">LOCAL CENTERS</p><h1>' + region + ' 지점안내</h1>' + paragraph(citytext + '에서 방문할 지점을 찾아보세요. 주소와 과목별 학년 범위를 확인한 뒤 학생의 하교 시간에 맞는 시간표를 상담할 수 있습니다.', 'branch-intro') + '</section>'
    groups = defaultdict(list)
    for c in ordered:
        groups[c['region']['administrativeAreaText'] or region].append(c)
    body += '<div data-branch-search-root data-search-mode="region">' + search_controls(region)
    body += '<nav class="branch-city-links" aria-label="시군구 바로가기">' + ''.join(f'<a href="#district-{i}" data-branch-search-jump>{esc(city)}</a>' for i, city in enumerate(groups, 1)) + '</nav><div id="branch-search-results" data-branch-search-results>'
    for i, (city, items) in enumerate(groups.items(), 1):
        body += f'<section class="branch-city-section" id="district-{i}" data-branch-search-group><h2>{esc(city)}</h2><div class="branch-center-grid">' + ''.join(center_card(c, searchable=True) for c in items) + '</div></section>'
    body += '</div></div>'
    if reference:
        body += '<div class="branch-section">'
        subjects = list(dict.fromkeys(name.replace('(학년 확인)', '') for c in centers for name in c.get('_displaySubjects', c['availableSubjects'])))
        guide = paragraph(region + ' 지역 지점에서 안내하는 과목을 한눈에 살펴보세요. 모든 지점에서 아래 과목이 동일하게 개설되는 것은 아니며, 지점별 가능 학년과 조건은 상세 페이지에서 확인할 수 있습니다.')
        guide += '<div class="branch-neighborhoods">' + ''.join('<span>' + esc(name) + '</span>' for name in subjects) + '</div>'
        body += panel('region-subjects', region + ' 지역 과목 안내', guide)
        level_cards = reference.get('schoolLevelCards', [])
        if level_cards:
            level_texts = ['기초 개념을 이해하는지, 배운 내용을 혼자 설명할 수 있는지부터 살핍니다. 숙제 양보다 매일 실천할 수 있는 공부 시간을 정하는 것이 우선입니다.', '학교 시험 범위와 평소 수업 내용을 연결합니다. 틀린 문제를 개념 부족·문제 해석·풀이 실수로 나누어 복습할 부분을 찾습니다.', '선택 과목과 학교 평가 방식, 모의고사에서 어려운 유형을 구분합니다. 시험 일정에 맞춰 개념 보완과 문제 적용의 우선순위를 정합니다.']
            body += panel('region-levels', '학교급에 따라 달라지는 학습 준비', '<div class="branch-learning-cards">' + ''.join('<article><h3>' + esc(card['title']) + '</h3>' + paragraph(level_texts[i]) + '</article>' for i, card in enumerate(level_cards[:3])) + '</div>')
        learning = learning_section({'sourceCenterName': region}, reference)
        if learning:
            body += panel('region-learning', '계획·학습·소통을 연결하는 학습관리', learning)
        policy = '서울' if region == '서울' else '서울 외'
        duration = '80~100분' if region == '서울' else '90~100분'
        fees = paragraph(policy + ' 지점 기준 월 수업비입니다. 1회 수업은 ' + duration + ' 기준이며, 실제 개설 과정과 적용 조건은 지점 상담에서 확인해 주세요.')
        fees += '<div class="branch-fee-grid" data-fee-region="' + policy + '">'
        for level, amounts in FEES[policy].items():
            fees += '<section class="branch-fee-card"><h3>' + level + '</h3><dl>' + ''.join(f'<div><dt>주 {n}회</dt><dd>{amount:,}원</dd></div>' for n, amount in zip((2,3,5), amounts)) + '</dl></section>'
        fees += '</div>' + paragraph('등록번호·운영 일정은 지점마다 다르므로 개별 지점 안내를 확인해 주세요. 교재 등 별도 비용의 포함 여부는 상담에서 확인할 수 있습니다.', 'branch-small')
        body += panel('region-tuition', region + ' 지역 교육비 안내', fees)
        gallery = reference_gallery({'displayName': region + ' 지역 영수코칭'}, reference)
        faqs = [(region + '의 모든 지점이 같은 과목을 운영하나요?', '아니요. 지점마다 수업 가능한 과목·학년·시간표가 다릅니다. 지점 카드를 눌러 과목별 안내와 운영 조건을 확인해 주세요.'), ('가까운 지점은 어떻게 찾나요?', '위의 시·군·구 바로가기를 선택하고 지점 주소를 비교해 보세요. 같은 이름의 지점도 별도 운영 정보가 있을 수 있으므로 등록 학원명과 주소를 함께 확인해 주세요.'), ('상담을 준비할 때 무엇을 알려드리면 되나요?', '상담을 원하는 지점명과 재학 학교·학년, 희망 과목, 가능한 요일을 준비해 주세요. 페이지의 전화·문자·상담 버튼으로 문의하실 수 있습니다.')]
        body += panel('region-questions', region + ' 지점 선택 시 자주 묻는 질문', '<div class="branch-faq">' + ''.join('<details><summary>' + esc(q) + '</summary>' + paragraph(a) + '</details>' for q, a in faqs) + '</div>')
        graph.append({'@type': 'FAQPage', '@id': url(path) + '#region-questions', 'mainEntity': [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in faqs]})
        body += '</div>'
    body += '<a class="branch-back" href="/지점안내/">← 전체 지역 다시 선택하기</a>'
    if gallery:
        body += collapsed_gallery_panel('region-space', '학습 공간', gallery)
    return path, page(title, desc, path, crumbs, body, graph)


def grade_ranges(grades):
    # Preserve missing grades; never turn 초4,초6 into 초4~초6.
    if not grades:
        return '상담 시 확인'
    segments = []
    for prefix in ('초', '중', '고'):
        nums = sorted({int(x[1:]) for x in grades if re.fullmatch(prefix + r'\d+', x)})
        runs = []
        for n in nums:
            if runs and n == runs[-1][-1] + 1:
                runs[-1].append(n)
            else:
                runs.append([n])
        segments.extend(prefix + str(r[0]) + ('~' + prefix + str(r[-1]) if len(r) > 1 else '') for r in runs)
    segments.extend(g for g in grades if not re.fullmatch(r'[초중고]\d+', g))
    return ' · '.join(segments)


def op(c, key):
    return ' / '.join(c['publicOperations'][key]['values'])


def info_row(label, value):
    return f'<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>' if value else ''


def panel(id_, title, body, kicker=''):
    return f'<section class="branch-panel" id="{id_}">' + (f'<p class="branch-kicker">{esc(kicker)}</p>' if kicker else '') + f'<h2>{esc(title)}</h2>' + body + '</section>'


def neighborhood_navigation(children):
    """Visible, grouped links to existing children; never infer missing courses."""
    if not children:
        return ''
    groups = defaultdict(list)
    for child in children:
        groups[child['locality']].append(child)
    cards = []
    for locality, entries in groups.items():
        links = ''.join(
            '<a class="branch-neighborhood-link" href="' + esc(child['path']) + '">'
            '<span>' + esc(child['title']) + '</span><span aria-hidden="true">→</span></a>'
            for child in entries
        )
        cards.append('<div class="branch-neighborhood-card"><h3>' + esc(locality) + '</h3>'
                     '<div class="branch-neighborhood-buttons">' + links + '</div></div>')
    return ('<section class="branch-panel branch-neighborhood-navigation" id="neighborhood-pages" '
            'aria-labelledby="neighborhood-pages-title">'
            '<p class="branch-kicker">동네별 페이지 바로가기</p>'
            '<h2 id="neighborhood-pages-title">동네별 영어·수학 학습 안내</h2>'
            + paragraph('동네와 과목을 선택하면 학습 내용과 상담 준비사항을 자세히 볼 수 있습니다.')
            + '<div class="branch-neighborhood-grid">' + ''.join(cards) + '</div></section>')


def collapsed_gallery_panel(id_, title, gallery, kicker=''):
    # Native details stays closed on initial load and supports keyboard/touch without JavaScript.
    return f'<section class="branch-panel" id="{id_}">' + (f'<p class="branch-kicker">{esc(kicker)}</p>' if kicker else '') + '<details class="branch-space-disclosure"><summary><h2>' + esc(title) + '</h2></summary>' + gallery + '</details></section>'


def learning_section(c, reference):
    cards = reference.get('learningCards', [])
    if not cards:
        return ''
    editorial = reference.get('editorial', {})
    body = ''
    if editorial.get('focusText'):
        body += '<h3 class="branch-subheading">' + esc(editorial['focusHeading']) + '</h3>' + paragraph(editorial['focusText'], 'branch-focus-copy')
    else:
        body += paragraph('학생의 현재 이해도와 학습 습관을 살피고, 계획·수업·복습 기록을 연결합니다.')
    body += '<div class="branch-learning-cards">'
    for i, card in enumerate(cards, 1):
        body += '<article><span class="branch-step-number">' + str(i).zfill(2) + '</span><h3>' + esc(card['title']) + '</h3>' + paragraph(card['text']) + '</article>'
    body += '</div>'
    strengths = reference.get('strengths', [])
    if strengths and not editorial.get('focusText'):
        body += '<h3 class="branch-subheading">' + esc(c['sourceCenterName']) + '에서 살펴볼 학습 환경</h3><ul class="branch-editorial-list">' + ''.join('<li>' + esc(x) + '</li>' for x in strengths) + '</ul>'
    return body


def curriculum_section(c, reference):
    rows = reference.get('curriculum', [])
    if not rows:
        return ''
    body = paragraph('현재 배우는 단원과 어려운 문제를 함께 준비하면 부족한 개념과 연습할 내용을 구분하기 쉽습니다. 아래의 학교급별 점검 기준을 상담 준비에 활용해 보세요.')
    body += '<div class="branch-curriculum">'
    for row in rows:
        body += '<article><h3>' + esc(row['subject']) + '</h3><dl>'
        for level, text in row['levels'].items():
            body += info_row(level, CURRICULUM_COPY.get(row['subject'], {}).get(level, text))
        body += '</dl></article>'
    body += '</div>' + paragraph('희망 과정은 위 과목·학년표에서 확인하고, 현재 사용하는 교재와 진도에 맞춰 상담해 주세요.', 'branch-small')
    return body


def reference_gallery(c, reference):
    images = reference.get('images', [])
    if not images:
        return ''
    body = '<div class="branch-gallery">'
    for i, img in enumerate(images, 1):
        body += f'<figure><img src="{esc(img["localSrc"])}" width="{img["width"]}" height="{img["height"]}" loading="lazy" decoding="async" alt="학습코칭 교실"></figure>'
    body += '</div>'
    return body


def primary_media(c, reference):
    media = reference.get('primaryMedia')
    if not media:
        return ''
    body = '<div class="branch-primary-media" aria-label="학원 수업 및 위치 안내">'
    for kind, label in [('body', '본문'), ('map', '지도')]:
        asset = media.get(kind)
        if not asset:
            continue
        panel = asset.get('displayPanel')
        image_style = ''
        frame_start = frame_end = ''
        if panel:
            assert kind == 'map' and 0 <= panel['top'] < panel['bottom'] <= asset['height']
            # Clip only the displayed area of an owner-supplied combined image.
            # Keep the actual image bytes, including GIF animation, untouched.
            ratio = str(asset['width']) + '/' + str(panel['bottom'] - panel['top'])
            frame_start = '<div class="branch-map-panel" style="aspect-ratio:' + ratio + '">'
            frame_end = '</div>'
            image_style = ' style="transform:translateY(-' + f"{panel['top'] / asset['height'] * 100:.8f}" + '%)"'
        body += '<figure class="branch-' + kind + '-image">' + frame_start + '<img src="' + esc(asset['src']) + '" width="' + str(asset['width']) + '" height="' + str(asset['height']) + '" alt="' + esc(c['displayName'] + ' ' + label) + '" loading="lazy" decoding="async"' + image_style + '>' + frame_end + '</figure>'
    return body + '</div>'


def consultation_section(c, reference):
    steps = reference.get('consultationSteps', [])
    if not steps:
        return ''
    body = '<ol class="branch-process">'
    for step in steps:
        text = step['text']
        if step['title'] == '문의':
            text = c['sourceCenterName'] + ' 상담을 원한다고 말씀해 주세요. 재학 학교와 학년, 희망 과목, 하교 후 가능한 시간을 알려주시면 됩니다.'
        elif step['title'] == '설계':
            text = '현재 이해도와 공부 습관을 바탕으로 필요한 수업 횟수와 복습량을 조율합니다. 다른 일정과 겹치지 않는 시간표를 함께 확인합니다.'
        body += '<li><strong>' + esc(step['title']) + '</strong>' + paragraph(text) + '</li>'
    body += '</ol><h3 class="branch-subheading">방문 전 함께 확인할 내용</h3><ul class="branch-editorial-list">'
    for text in reference.get('checklist', []):
        body += '<li>' + esc(text) + '</li>'
    body += '</ul><div class="branch-actions">' + button('tel:01068398283', '공통 상담 전화') + button('/상담문의/', '상담 준비사항', True) + '</div>'
    return body


def schools_section(c, match):
    if not match:
        return paragraph('재학 학교와 희망 과목을 알려주시면 수업 가능 학년과 교재·진도를 함께 상담할 수 있습니다.')
    neighborhoods = match.get('neighborhoods', [])
    locality = '·'.join(neighborhoods[:3]) + (' 등' if len(neighborhoods) > 3 else '')
    body = paragraph((locality + '에서 ' if locality else '') + c['sourceCenterName'] + ' 상담을 준비한다면 재학 학교와 사용하는 교재, 시험 범위를 함께 알려주세요. 같은 학년이라도 학교의 진도와 평가 방식에 따라 준비할 내용이 달라집니다.')
    if neighborhoods:
        body += '<div class="branch-neighborhoods" aria-label="상담 지역">' + ''.join('<span>' + esc(n) + '</span>' for n in neighborhoods) + '</div>'
    uncertain = []
    for key, label in LEVELS.items():
        values = match['targetSchools'][key]
        schools = sorted({s for s in values if '[' not in s and '모든' not in s})
        uncertain += [(label, s) for s in values if '[' in s or '모든' in s]
        body += f'<details class="branch-school-group" open><summary>{label}</summary>'
        if schools:
            body += '<ul class="branch-school-list">' + ''.join('<li>' + esc(s) + '</li>' for s in schools) + '</ul>'
        else:
            body += paragraph('재학 학교를 알려주시면 교재·진도와 수업 가능 범위를 확인해 드립니다.', 'branch-small')
        body += '</details>'
    if uncertain:
        body += '<details class="branch-school-group"><summary>학교별 추가 확인사항</summary>' + paragraph('학교 명칭·지역과 재학 상태를 함께 확인할 항목입니다.', 'branch-small') + '<ul class="branch-school-notes">'
        body += ''.join('<li>' + esc(level + ' · ' + text) + '</li>' for level, text in sorted(set(uncertain))) + '</ul></details>'
    extra = match.get('referenceSchools', {})
    if any(extra.values()):
        body += '<details class="branch-school-group branch-reference-schools"><summary>주변 학교 추가 안내</summary>'
        body += paragraph('주변 학교에서 상담을 준비할 때 살펴볼 목록입니다. 해당 학교·학년의 실제 수업 가능 여부는 희망 과목과 함께 확인해 주세요.', 'branch-small')
        for key, label in LEVELS.items():
            if extra.get(key):
                body += '<h3 class="branch-subheading">' + label + '</h3><ul class="branch-school-list">'
                body += ''.join('<li>' + esc(item['name']) + '</li>' for item in extra[key]) + '</ul>'
        body += '</details>'
    body += paragraph('학교별 시험 일정과 과목별 가능 학년을 함께 확인한 뒤 수업 계획을 정해 주세요.', 'branch-small')
    return body


def center_page(c, match, centers, reference=None):
    reference = reference or {}
    region = c['region']['province']
    path = branch_path(c)
    regionpath = HUB + region + '/'
    crumbs = [('홈', '/'), ('지점안내', HUB), (region, regionpath), (c['sourceCenterName'], path)]
    title = c['displayName']
    subject_names = ' · '.join(c.get('_displaySubjects', c['availableSubjects']))
    desc = branch_description(c, reference)
    graph = base_graph(title, desc, path, crumbs)
    centerid = url(path) + '#center'
    graph[1]['mainEntity'] = {'@id': centerid}
    graph[1]['about'] = {'@id': centerid}
    graph[1]['abstract'] = branch_summary(c, reference)
    graph.append({'@type': 'EducationalOrganization', '@id': centerid, 'name': title, 'url': url(path),
                  'address': {'@type': 'PostalAddress', 'addressCountry': 'KR', 'addressRegion': region,
                              'addressLocality': c['region']['administrativeAreaText'], 'streetAddress': c['address']}})
    if c['registeredAcademyName']:
        graph[-1]['legalName'] = c['registeredAcademyName']
    graph[-1]['mainEntityOfPage'] = {'@id': url(path) + '#webpage'}
    if c['registrationNumber']:
        graph[-1]['identifier'] = c['registrationNumber']
    if c.get('addressPrecision') == 'neighborhood':
        graph[-1]['address'].pop('streetAddress', None)
    # Do not attach the site's common contact number, unconfirmed hours, school affiliations,
    # reviews, or estimates as facts about the individual business in structured data.
    policy = '서울' if region == '서울' else '서울 외'
    duration = '80~100분' if region == '서울' else '90~100분'
    children = sorted(c.get('_neighborhoodPages', []), key=lambda child: (child['locality'], child['subject']))
    heading = '<span class="branch-brand-name">' + esc(c['brandName']) + '</span> ' + esc(c['sourceCenterName'])
    body = '<section class="branch-hero branch-detail-hero"><div><p class="branch-eyebrow">' + esc(region + ' · ' + (c['region']['administrativeAreaText'] or '지점안내')) + '</p><h1>' + heading + '</h1>'
    body += paragraph(branch_summary(c, reference), 'branch-intro branch-editorial-intro')
    body += paragraph(c['address'], 'branch-intro branch-hero-address')
    neighborhoods = list(dict.fromkeys((match or {}).get('neighborhoods', [])))
    if neighborhoods:
        body += paragraph('·'.join(neighborhoods) + '에서 학원을 찾는 학생이라면, ' + c['sourceCenterName'] + '에서 희망 과목의 수업을 상담해 보세요. 재학 학교와 학년에 맞는 수업 범위·시간표를 함께 확인합니다.', 'branch-hero-neighborhoods')
    child_jump = ('<a class="branch-button branch-neighborhood-jump" href="#neighborhood-pages">'
                  '동네별 학원 페이지 보기<span aria-hidden="true">↓</span></a>') if children else ''
    body += '<div class="branch-actions">' + child_jump + button('tel:01068398283', '공통 상담 전화') + button('#directions', '위치 확인하기', True) + '</div></div>'
    body += '<dl class="branch-at-a-glance">' + info_row('안내 과목', subject_names or '상담 시 확인') + info_row('평일 시작 안내', op(c, 'averageWeekdayOpening') or '상담 시 확인') + info_row('교육비 기준', policy + ' · 월 수업비 / 1회 ' + duration) + '</dl></section>'
    body += primary_media(c, reference)
    anchors = [('center-info', '지점 정보'), ('programs', '과목·학년'), ('tuition', '교육비'), ('schools', '대상 학교'), ('directions', '오시는 길'), ('questions', '자주 묻는 질문')]
    additions = [('learning', '학습코칭', learning_section(c, reference)), ('curriculum', '학습 방향', curriculum_section(c, reference)), ('learning-space', '학습 공간', reference_gallery(c, reference)), ('consultation-guide', '상담 절차', consultation_section(c, reference))]
    available_additions = {id_: (label, content) for id_, label, content in additions if content}
    order = ['center-info', 'learning', 'programs', 'curriculum', 'tuition', 'schools', 'directions', 'consultation-guide', 'questions', 'neighborhood-pages', 'learning-space']
    labels = dict(anchors) | {id_: label for id_, (label, _) in available_additions.items()}
    if children:
        labels['neighborhood-pages'] = '동네별 학습 안내'
    anchors = [(id_, labels[id_]) for id_ in order if id_ in labels]
    body += '<nav class="branch-toc" aria-label="지점 상세 목차">' + ''.join(f'<a href="#{id_}">{label}</a>' for id_, label in anchors) + '</nav><div class="branch-detail-grid"><div class="branch-detail-content">'
    info = ''.join(paragraph(p) for p in location_copy(reference))
    info += '<dl class="branch-info">' + info_row('안내 위치' if c.get('addressPrecision') == 'neighborhood' else '주소', c['address']) + info_row('등록 학원명', c['registeredAcademyName']) + info_row('학원 등록번호', c['registrationNumber']) + info_row('평일 시작 안내', op(c, 'averageWeekdayOpening')) + info_row('주말 수업', weekend_summary(c, reference))
    weekend = reference.get('operations', {}).get('weekend', {})
    info += info_row('주말 추가 안내', weekend_detail(c, reference)) + '</dl>'
    if c.get('addressPrecision') == 'neighborhood':
        info += paragraph('현재 안내는 동네와 주변 위치 기준입니다. 정확한 도로명 주소·건물·층수와 운영 상태는 방문 전 상담으로 확인해 주세요.', 'branch-small')
    info += paragraph('방문 전 희망 과목·학년과 가능한 요일을 알려주시면 현재 시간표를 확인할 수 있습니다.', 'branch-small')
    body += panel('center-info', '방문 전, 지점 정보부터', info, '01  CENTER INFORMATION')
    if additions[0][2]:
        body += panel('learning', c['sourceCenterName'] + '의 학습코칭', additions[0][2], 'LEARNING & CARE')
    subjects = paragraph('같은 지점에서도 과목마다 시작 학년과 수업 가능한 범위가 다릅니다. 희망 과목의 학년을 먼저 살펴보세요.') + '<div class="branch-subject-list">'
    for name, data in c['subjects'].items():
        detail = reader_text(reference.get('operations', {}).get('subjectDisplay', {}).get(name, {}).get('detail', ''))
        subjects += '<div class="branch-subject-row"><strong>' + esc(name) + '</strong><div><span class="branch-grade-range">' + esc(subject_summary(c, name, data, reference)) + '</span>' + (paragraph(detail, 'branch-status-note') if detail else '') + '</div></div>'
    subjects += '</div>'
    conditions = c['publicOperations']['subjectConditions']['values']
    if conditions and not reference.get('operations', {}).get('subjectDisplay'):
        subjects += '<ul class="branch-conditions">' + ''.join('<li>' + esc(x) + '</li>' for x in conditions) + '</ul>'
    subjects += paragraph('가능 학년과 세부 과정은 과목마다 다릅니다. 표에서 확인이 필요한 과목은 희망 학년과 현재 진도를 말씀해 주세요.', 'branch-small')
    body += panel('programs', '수업 과목과 가능 학년', subjects, '02  SUBJECTS & GRADES')
    if additions[1][2]:
        body += panel('curriculum', '과목별로 살펴보는 학습 방향', additions[1][2], 'SUBJECT LEARNING GUIDE')
    fees = paragraph(policy + ' 지점 기준의 월 수업비입니다. 1회 수업은 ' + duration + ' 기준으로 안내합니다.')
    fees += '<div class="branch-fee-grid" data-fee-region="' + policy + '">'
    for level, amounts in FEES[policy].items():
        fees += '<section class="branch-fee-card"><h3>' + level + '</h3><dl>' + ''.join(f'<div><dt>주 {n}회</dt><dd>{amount:,}원</dd></div>' for n, amount in zip((2,3,5), amounts)) + '</dl></section>'
    fees += '</div>' + paragraph('수강 신청 전 희망 과목·학년의 개설 여부와 적용 교육비를 확인해 주세요. 교재 등 별도 항목의 포함 여부는 상담에서 안내받으실 수 있습니다.', 'branch-small')
    body += panel('tuition', policy + ' 지점 교육비 안내', fees, '03  TUITION')
    body += panel('schools', '지역별 대상 학교', schools_section(c, match), '04  LOCAL SCHOOLS')
    directions = '<div class="branch-map-box"><address>' + esc(c['address']) + '</address></div>'
    if c['locationGuide']:
        directions += paragraph(c['locationGuide'])
    apartments = reference.get('apartments', [])
    if apartments:
        directions += '<h3 class="branch-subheading">주변 생활권에서 방문하기</h3>' + paragraph('아래 단지는 지점 주변 생활권을 확인할 때 참고할 수 있습니다. 출발하는 동·출입구와 이동 수단에 따라 실제 경로가 달라지므로 지도에서 길을 확인해 주세요.')
        directions += '<details class="branch-school-group"><summary>주변 단지 목록 보기</summary><ul class="branch-school-list">' + ''.join('<li>' + esc(x) + '</li>' for x in apartments) + '</ul></details>'
    if reference.get('commuteParagraphs'):
        directions += ''.join(paragraph(p) for p in reference['commuteParagraphs'])
    directions += button('https://map.naver.com/p/search/' + quote(c['address'], safe=''), '네이버 지도에서 주소 찾기 ↗', True, True)
    directions += paragraph('지도 검색은 새 창으로 열립니다. 지점명과 건물·층수를 함께 확인하고 방문해 주세요.', 'branch-small')
    body += panel('directions', c['sourceCenterName'] + ' 오시는 길', directions, '05  LOCATION')
    if additions[3][2]:
        body += panel('consultation-guide', '상담부터 첫 수업까지', additions[3][2], 'CONSULTATION GUIDE')
    gradeanswer = course_answer(c, reference)
    location_answer = c['address'] + ('. ' + c['locationGuide'] if c['locationGuide'] else '')
    if c.get('addressPrecision') == 'neighborhood':
        location_answer += '. 상세 도로명 주소와 건물·층수는 방문 전에 확인해 주세요.'
    faqs = [(c['sourceCenterName'] + '은 어디에 있나요?', location_answer), ('어떤 과목과 학년을 상담할 수 있나요?', gradeanswer + '. 세부 단원과 시간표는 상담 시 확인해 주세요.'), ('상담은 어떻게 신청하나요?', '페이지의 전화·문자·상담 버튼으로 문의하실 수 있습니다. ' + c['sourceCenterName'] + ' 상담을 원한다고 말씀해 주세요. 재학 학교와 학년, 희망 과목과 가능한 요일을 알려주시면 상담을 준비할 수 있습니다.')]
    if reference.get('sourceUrl'):
        amounts = FEES[policy]
        faqs[2:2] = [
            ('교육비는 얼마인가요?', f'{policy} 지점 기준 월 수업비입니다. 주 2회는 초등 {amounts["초등"][0]:,}원, 중등 {amounts["중등"][0]:,}원, 고등 {amounts["고등"][0]:,}원이며 1회 {duration} 기준입니다. 주 3회·5회 금액은 본문 교육비 안내를 확인해 주세요.'),
            ('평일과 주말 수업은 어떻게 확인하나요?', '평일 시작 안내: ' + (op(c, 'averageWeekdayOpening') or '상담 시 확인') + '. 주말 안내: ' + weekend_summary(c, reference) + '. ' + weekend_detail(c, reference) + ' 희망 요일·과목과 재학 학년을 알려주시면 구체적인 시간표를 확인할 수 있습니다.'),
            ('재학 학교에 맞춰 상담하려면 무엇을 준비하나요?', '재학 학교, 현재 학년, 사용 중인 교재와 최근 시험지 또는 어려웠던 문제를 준비해 주세요. 해당 과목의 개설 학년과 학습 진도를 함께 확인할 수 있습니다.'),
            ('첫 상담에서는 무엇을 확인하나요?', '현재 학습 상태와 공부 습관, 어려운 단원, 가능한 요일을 함께 확인합니다. 학생에게 필요한 과목과 횟수, 복습 계획을 상담하고 교육비와 교재 조건을 확인한 뒤 수업 일정을 정합니다.'),
        ]
    editorial = reference.get('editorial', {})
    if editorial.get('consultationQuestion') and editorial.get('consultationAnswer'):
        faqs = [(editorial['consultationQuestion'], editorial['consultationAnswer']) if q == '첫 상담에서는 무엇을 확인하나요?' else (q, a) for q, a in faqs]
    faqhtml = '<div class="branch-faq">' + ''.join('<details><summary>' + esc(q) + '</summary>' + paragraph(a) + '</details>' for q, a in faqs) + '</div>'
    body += panel('questions', '자주 묻는 질문', faqhtml)
    graph.append({'@type': 'FAQPage', '@id': url(path) + '#questions', 'mainEntity': [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in faqs]})
    if children:
        body += neighborhood_navigation(children)
        graph.append({'@type': 'ItemList', '@id': url(path) + '#neighborhood-pages', 'numberOfItems': len(children),
                      'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': child['title'], 'url': url(child['path'])} for i, child in enumerate(children)]})
    related = sorted([x for x in centers if x['id'] != c['id'] and x['region']['province'] == region and x['region']['district'] == c['region']['district']], key=lambda x: x['sourceCenterName'])[:4]
    if related:
        body += panel('other-centers', '같은 지역의 다른 지점', '<div class="branch-center-grid">' + ''.join(center_card(x) for x in related) + '</div>')
    body += '</div><aside class="branch-aside"><p class="branch-kicker">BEFORE YOUR VISIT</p><h2>상담은 이렇게 준비하세요</h2><p>' + esc(c['sourceCenterName']) + ' 상담을 원한다고 말씀해 주세요.</p><ol><li>재학 학교와 현재 학년</li><li>희망 과목과 어려운 단원</li><li>가능한 요일과 시간대</li></ol>' + button('tel:01068398283', '공통 상담 전화') + button('/상담문의/', '상담 준비사항 보기', True) + '</aside></div><a class="branch-back" href="' + esc(regionpath) + '">← ' + region + ' 지점 목록으로</a>'
    if additions[2][2]:
        body += collapsed_gallery_panel('learning-space', '학습 공간 살펴보기', additions[2][2], 'LEARNING SPACE')
    return path, page(title, desc, path, crumbs, body, graph, detail=True)


def sync_navigation():
    updates = []
    for path in ROOT.rglob('*.html'):
        if any(part in IGNORED for part in path.relative_to(ROOT).parts) or '지점안내' in path.relative_to(ROOT).parts:
            continue
        old = path.read_bytes().decode('utf-8')
        def patch_nav(m):
            value = m.group(0)
            if 'href="/지점안내/"' in value:
                return value
            return value.replace('</nav>', '<a href="/지점안내/">지점안내</a></nav>')
        new = re.sub(r'<nav class="nav"[^>]*>.*?</nav>', patch_nav, old, flags=re.S)
        def patch_footer(m):
            value = m.group(0)
            if 'href="/지점안내/"' in value:
                return value
            return value.replace('<a href="/sitemap.xml">', '<a href="/지점안내/">지점안내</a><a href="/sitemap.xml">')
        new = re.sub(r'<div class="footer-links">.*?</div>', patch_footer, new, flags=re.S)
        if write_changed(path, new):
            updates.append(str(path.relative_to(ROOT)))
    return updates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--import-from', type=Path)
    args = parser.parse_args()
    if args.import_from:
        for name in ('centers.json', 'target-schools.json', 'school-match-audit.json'):
            source = args.import_from / name
            value = json.loads(source.read_text(encoding='utf-8'))
            write_changed(DATA / name, json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    bundle, centers, reference = load_branch_data()
    matches = json.loads((DATA / 'school-match-audit.json').read_text(encoding='utf-8'))
    match_by_id = {m['centerId']: m for m in matches['matches']}
    match_by_id.update(reference.get('schoolMatches', {}))
    match_by_id = {c['id']: match_by_id[c['id']] for c in centers if c['id'] in match_by_id}
    for c in centers:
        c['_searchNeighborhoods'] = match_by_id.get(c['id'], {}).get('neighborhoods', [])
    pages = [directory_page(centers)]
    for region in REGIONS:
        group = [c for c in centers if c['region']['province'] == region]
        if group:
            pages.append(region_page(region, group, reference.get('regions', {}).get(region)))
    pages += [center_page(c, match_by_id.get(c['id']), centers, reference.get('centers', {}).get(c['id'])) for c in centers]
    changed = 0
    for path, content in pages:
        changed += write_changed(ROOT / path.strip('/') / 'index.html', content)
    nav_updates = sync_navigation()
    effective_school_summary = {
        'centerRecords': len(match_by_id),
        'targetSchoolEntries': sum(len(names) for m in match_by_id.values() for names in m.get('targetSchools', {}).values()),
        'referenceCandidateEntries': sum(len(names) for m in match_by_id.values() for names in m.get('referenceSchools', {}).values()),
        'centersWithReferenceCandidates': sum(any(m.get('referenceSchools', {}).values()) for m in match_by_id.values()),
    }
    report = {'centerCount': len(centers), 'regionCount': len(pages) - len(centers) - 1, 'pageCount': len(pages), 'changedBranchPages': changed,
              'navigationUpdates': nav_updates, 'schoolMatchSummary': matches['summary'], 'paths': [p for p, _ in pages],
              'effectiveSchoolSummary': effective_school_summary,
              'sourceWorkbookSha256': bundle['source']['sha256'], 'deployment': 'NOT DEPLOYED - local only'}
    write_changed(REPORTS / 'generation.json', json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k not in {'paths','navigationUpdates'}}, ensure_ascii=False))
    print(f'Updated navigation only on {len(nav_updates)} existing HTML pages')


if __name__ == '__main__':
    main()
