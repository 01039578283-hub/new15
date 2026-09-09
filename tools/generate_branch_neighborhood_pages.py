"""Local branch -> neighborhood/subject pages from supplied manuscript archives.

Source archives and original center records remain immutable. No deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path

from PIL import Image
from branch_manuscripts import load_manuscript_archive
from branch_editorial import prepare_editorial
from branch_reader_facts import (public_school_groups, subject_scope_confirmed,
    related_grade_links, address_notice, address_label, _confirmed_grades)
from branch_child_navigation import load_child_pages, child_navigation_html, child_item_list
from branch_readability import reading_chunks
from generate_branch_pages import (ROOT, DATA as BRANCH_DATA, HUB, DOMAIN, LEVELS,
    load_branch_data, branch_path, subject_summary, reader_text, base_graph, url,
    page, panel, paragraph, button, esc, primary_media, info_row, write_changed)

DATA = ROOT / 'tools/data/branch-neighborhoods'
REPORTS = ROOT / 'reports/branch-neighborhoods'
SOURCE = Path('C:/Users/1992k/Desktop/프로그램 원고')
MAPPING = ROOT / 'reports/branches/neighborhood-mapping.json'
REPRESENTATIVES = ROOT / 'assets/representative/manifest.json'
EDITORIAL_REVIEW_DATE = '2026-09-10'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_archive(source):
    destination = DATA / 'sources' / source.name
    if destination.exists():
        if source.exists() and sha(destination) != sha(source):
            raise ValueError(f'Source archive changed: {source.name}; review before replacing snapshot')
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return destination


def representative_pool():
    pool = json.loads(REPRESENTATIVES.read_text(encoding='utf-8'))['images']
    if len(pool) != 371:
        raise ValueError('Expected the existing 371-image representative pool')
    for record in pool:
        asset = ROOT / 'assets/representative' / record['asset_name']
        source = ROOT.parent / '참고자료/공통자료/대표이미지' / record['source_name']
        if sha(asset) != record['sha256'] or sha(source) != record['sha256']:
            raise ValueError(f'Representative source mismatch: {asset.name}')
        with Image.open(asset) as image:
            record['width'], record['height'] = image.size
        record['src'] = '/assets/representative/' + asset.name
    return pool


def child_path(center, manuscript):
    slug = manuscript['locality'] + manuscript['subject'] + '학원'
    if not slug or re.search(r'[/\\?#\x00-\x1f]', slug):
        raise ValueError(f'Invalid child slug: {slug!r}')
    return branch_path(center) + slug + '/'


def media_html(center, reference, title, representative):
    # Existing map panels (including owner-selected multi-map images) stay intact.
    view = dict(center, displayName=title)
    media = primary_media(view, reference)
    image = ('<figure class="branch-representative-image"><img style="display:none;" '
             'src="' + esc(representative['src']) + '" width="' + str(representative['width']) +
             '" height="' + str(representative['height']) + '" alt="' + esc(title + ' 영수코칭 대표') +
             '" loading="lazy" decoding="async"></figure>')
    opening = '<div class="branch-primary-media" aria-label="학원 수업 및 위치 안내">'
    if not media.startswith(opening):
        raise ValueError('Primary media wrapper changed; review the image order')
    return media.replace(opening, opening + image, 1)


def school_html(row):
    result = paragraph('재학 학교와 학년에 맞는 상담을 준비할 때 참고할 학교 목록입니다. 학교별 과정은 위의 과목·학년 안내와 함께 확인해 주세요.')
    public = public_school_groups(row)
    groups = public['groups']
    for key, label in LEVELS.items():
        names = list(dict.fromkeys(groups.get(key, [])))
        if names:
            result += '<details class="branch-school-group"><summary>' + esc(label) + '</summary><ul class="branch-school-list">' + ''.join('<li>' + esc(name) + '</li>' for name in names) + '</ul></details>'
    for note in public['notes']:
        result += paragraph(note, 'branch-small')
    return result


def manuscript_paragraphs(paragraphs, *, limit=210):
    result = ''
    for index, text in enumerate(paragraphs):
        result += '<div class="branch-manuscript-unit" data-paragraph="' + str(index) + '">'
        result += ''.join(paragraph(chunk, 'branch-manuscript-paragraph') for chunk in reading_chunks(text, limit=limit))
        result += '</div>'
    return result


def render(center, ref, manuscript, representative, school_row, siblings, *, page_context=None):
    title, subject = manuscript['title'], manuscript['subject']
    parent, path = branch_path(center), child_path(center, manuscript)
    grade = page_context.get('grade') if page_context else None
    revised_grade = bool(grade and page_context.get('editorialRevision') == '2026-09-10-reader-v1')
    page_parent = page_context['parentPath'] if page_context else parent
    if page_context:
        path = page_context['path']
    children = load_child_pages(path) if not grade else []
    region = center['region']['province']
    full_title = title + ' | ' + center['sourceCenterName'] + ' · 영수코칭'
    meta = manuscript['meta']
    crumbs = [('홈', '/'), ('지점안내', HUB), (region, HUB + region + '/'),
              (center['sourceCenterName'], parent)]
    if grade:
        crumbs.append((page_context['parentTitle'], page_parent))
    crumbs.append((title, path))
    graph = base_graph(full_title, meta, path, crumbs)
    center_id = url(parent) + '#center'
    article_id = url(path) + '#article'
    graph[1]['isPartOf'] = {'@id': url(page_parent) + '#webpage'}
    graph[1]['mainEntity'] = {'@id': article_id}
    graph[1]['about'] = {'@id': center_id}
    graph[1]['dateModified'] = EDITORIAL_REVIEW_DATE
    organization = {'@type': 'EducationalOrganization', '@id': center_id,
                    'name': center['displayName'], 'url': url(parent),
                    'address': {'@type': 'PostalAddress', 'addressCountry': 'KR',
                                'addressRegion': region,
                                'addressLocality': center['region']['administrativeAreaText'],
                                'streetAddress': center['address']},
                    'mainEntityOfPage': {'@id': url(parent) + '#webpage'}}
    if center.get('addressPrecision') == 'neighborhood':
        organization['address'].pop('streetAddress', None)
    if center['registeredAcademyName']:
        organization['legalName'] = center['registeredAcademyName']
    if center['registrationNumber']:
        organization['identifier'] = center['registrationNumber']
    graph.append(organization)
    scope = subject_summary(center, subject, center['subjects'].get(subject, {'grades': []}), ref)
    detail = reader_text(ref.get('operations', {}).get('subjectDisplay', {}).get(subject, {}).get('detail', ''))
    article = {'@type': 'Article', '@id': article_id, 'url': url(path), 'headline': title,
               'description': meta, 'inLanguage': 'ko-KR', 'mainEntityOfPage': {'@id': url(path) + '#webpage'},
               'isPartOf': {'@id': url(page_parent) + '#webpage'}, 'about': [{'@id': center_id}, {'@type': 'Thing', 'name': subject + ' 학습'}],
               'articleSection': [section['heading'] for section in manuscript['sections']],
               'dateModified': EDITORIAL_REVIEW_DATE}
    # Do not imply an offered course if the verified branch scope is absent.
    confirmed = grade in _confirmed_grades(center, ref, subject) if grade else subject_scope_confirmed(center, ref, subject)
    if grade:
        article['educationalLevel'] = grade
        article['about'].append({'@type': 'Thing', 'name': grade + ' ' + subject + ' 학습'})
    if confirmed:
        service_id = url(path) + '#service'
        service_topic = grade + ' ' + subject if grade else subject
        graph.append({'@type': 'Service', '@id': service_id, 'name': center['displayName'] + ' ' + service_topic + ' 수업 안내',
                      'serviceType': service_topic + ' 학습코칭', 'provider': {'@id': center_id},
                      'description': (grade + ' ' + subject + ' 수업의 구체적인 시간표와 학습 범위는 상담 시 확인해 주세요.') if grade else subject + ' ' + scope + ('. ' + detail if detail else ''),
                      'areaServed': {'@type': 'Place', 'name': manuscript['locality']},
                      'mainEntityOfPage': {'@id': url(path) + '#webpage'}})
        article['about'].append({'@id': service_id})
    graph.append(article)

    body = '<section class="branch-hero branch-child-hero"><p class="branch-eyebrow">' + esc(center['sourceCenterName'] + ' · ' + (grade + ' ' if grade else '') + subject + ' 학습 안내') + '</p><h1>' + esc(title) + '</h1>'
    shortcuts = '<div class="branch-actions branch-reading-shortcuts">' + button('#section-1', '본문 바로 읽기') + button('#article-toc', '글 목차', True) + button('#center-info', '지점·교육비 안내', True) + '</div>'
    if revised_grade:
        if not confirmed:
            body += '<p class="branch-grade-scope-badge">학습 준비 안내 · 수업 개설 확인 필요</p>'
        body += shortcuts
    body += paragraph(manuscript['intro'], 'branch-intro branch-manuscript-intro')
    if revised_grade and page_context.get('readingPoints'):
        body += '<aside class="branch-grade-takeaways" aria-label="본문 핵심"><p class="branch-grade-takeaways-label">본문 핵심</p><ul>'
        for point in page_context['readingPoints']:
            section_index, paragraph_index = point['sectionIndex'], point['paragraphIndex']
            if type(section_index) is not int or type(paragraph_index) is not int or section_index < 1 or paragraph_index < 1:
                raise ValueError('Invalid reading-point source indexes')
            source_text = manuscript['sections'][section_index - 1]['paragraphs'][paragraph_index - 1]
            if not point['text'] or point['text'] not in source_text:
                raise ValueError('Reading point must be an exact excerpt of its source paragraph')
            body += '<li data-source-section="' + str(section_index) + '" data-source-paragraph="' + str(paragraph_index) + '">' + esc(point['text']) + '</li>'
        body += '</ul></aside>'
    body += '<div class="branch-child-quick"><p><strong>상담 지점</strong> <a href="' + esc(parent) + '">' + esc(center['displayName']) + '</a></p>'
    if grade:
        body += '<p><strong>' + ('학습 안내 대상' if revised_grade else '학습 대상') + '</strong> ' + esc(grade + ' ' + subject) + '</p>'
        body += '<p><strong>동네별 안내</strong> <a href="' + esc(page_parent) + '">' + esc(page_context['parentTitle']) + '</a></p>'
    body += '<p><strong>' + esc(subject) + ' 학년 안내</strong> ' + esc(scope) + '</p></div>'
    if not confirmed:
        notice = (grade + ' ' + subject + ' 수업의 개설 여부와 상담 가능 학년을 먼저 확인해 주세요. 아래 글은 학습 준비를 위한 안내이며 해당 학년의 수업 개설을 뜻하지 않습니다.') if grade else '희망 과목과 학년의 개설 여부를 먼저 확인해 주세요. 아래 내용은 학습 점검을 위한 안내이며 개설 확정을 뜻하지 않습니다.'
        body += paragraph(notice, 'branch-scope-notice')
    if not revised_grade:
        body += shortcuts
    body += '</section>'
    body += media_html(center, ref, title, representative)
    sections = manuscript['sections']
    grade_links = [] if grade else related_grade_links(center, ref, manuscript['locality'], subject)
    anchors = [('center-info', '지점·수업 정보')] + [('section-' + str(i), s['heading']) for i, s in enumerate(sections, 1)]
    if school_row.get('targetSchools'):
        anchors += [('schools', '학교별 상담 준비')]
    anchors += [('questions', '자주 묻는 질문')]
    if revised_grade:
        anchors += [('other-grades', '같은 동네의 다른 학년')]
    if children:
        anchors += [('child-pages', '학년별 학습 안내')]
    if manuscript.get('cases'):
        anchors += [('consultation-example', '상담 준비 예시')]
    anchors += [('related-pages', '관련 동네·과목 안내')]
    if grade_links:
        anchors += [('grade-guides', '학년별 ' + subject + ' 학습 안내')]
    body += '<nav class="branch-toc branch-child-toc" id="article-toc" aria-label="글 목차">' + ''.join('<a href="#' + esc(key) + '">' + esc(label) + '</a>' for key, label in anchors) + '</nav>'
    body += '<div class="branch-child-content">'
    info = '<dl class="branch-info">' + info_row('상담 지점', center['displayName']) + info_row(address_label(center), center['address']) + info_row(subject + ' 가능 학년', scope)
    if detail:
        info += info_row('수업 범위 안내', detail)
    info += '</dl>' + paragraph('아래 글은 ' + subject + ' 학습과 상담을 준비하는 안내입니다. 글에 나오는 수업 방식·교재·시간표의 실제 운영 여부는 ' + center['sourceCenterName'] + '에서 확인해 주세요.', 'branch-small')
    if address_notice(center):
        info += paragraph(address_notice(center), 'branch-scope-notice')
    info += '<div class="branch-actions">' + button(parent + '#tuition', '교육비 확인', True) + button(parent + '#directions', '지점 위치 확인', True) + '</div>'
    body += panel('center-info', center['sourceCenterName'] + '에서 상담하기', info)
    for i, section in enumerate(sections, 1):
        body += panel('section-' + str(i), section['heading'], manuscript_paragraphs(section['paragraphs'], limit=150 if revised_grade else 210))
    if school_row.get('targetSchools'):
        body += panel('schools', manuscript['locality'] + ' 학교별 상담 준비', school_html(school_row))
    faq_html = '<div class="branch-faq">' + ''.join('<details><summary>' + esc(f['question']) + '</summary>' + paragraph(f['answer']) + '</details>' for f in manuscript['faq']) + '</div>'
    body += panel('questions', '자주 묻는 질문', faq_html)
    graph.append({'@type': 'FAQPage', '@id': url(path) + '#questions', 'mainEntity': [
        {'@type': 'Question', 'name': f['question'], 'acceptedAnswer': {'@type': 'Answer', 'text': f['answer']}}
        for f in manuscript['faq']]})
    if revised_grade:
        body += panel('other-grades', '같은 동네의 다른 학년 안내',
                      paragraph(manuscript['locality'] + ' ' + subject + '의 다른 학년 안내를 찾고 계신가요?') +
                      '<div class="branch-actions">' + button(page_parent + '#child-pages', '다른 학년 보기', True) + '</div>')
    if children:
        body += child_navigation_html(children)
        graph.append(child_item_list(children))
    if manuscript.get('cases'):
        example = '<details class="branch-reading-example"><summary>준비할 자료와 질문 살펴보기</summary>' + ''.join(paragraph(p) for p in manuscript['cases']) + '</details>'
        body += panel('consultation-example', '학부모 관점의 상담 준비 예시', example)
    # Show the other subject first, then nearby pages owned by this same center.
    related = sorted([s for s in siblings if s['path'] != path], key=lambda s: (s['locality'] != manuscript['locality'], s['locality'], s['subject']))[:6]
    links = '<a class="branch-child-link" href="' + esc(parent) + '">' + esc(center['displayName'] + ' 전체 안내') + '</a>'
    if grade:
        links += '<a class="branch-child-link" href="' + esc(page_parent) + '">' + esc(page_context['parentTitle'] + ' 전체 안내') + '</a>'
    links += ''.join('<a class="branch-child-link" href="' + esc(s['path']) + '">' + esc(s['title']) + '</a>' for s in related)
    body += panel('related-pages', '같은 지점의 ' + (grade + ' ' if grade else '') + '동네·과목 안내', '<div class="branch-child-links">' + links + '</div>')
    if grade_links:
        grade_html = paragraph('학년별 학습 고민을 더 살펴볼 수 있는 안내입니다. 실제 상담 가능한 학년은 이 페이지의 지점 안내를 기준으로 확인해 주세요.')
        grade_html += '<div class="branch-child-links">' + ''.join('<a class="branch-child-link" href="' + esc(link['path']) + '"><span>' + esc(link['label']) + '<small>' + esc(link['scopeNote']) + '</small></span></a>' for link in grade_links) + '</div>'
        body += panel('grade-guides', '학년별 ' + subject + ' 학습 안내', grade_html)
    body += panel('contact', '상담을 준비하고 계신가요?', paragraph(center['sourceCenterName'] + '에서 ' + title + ' 안내를 보고 문의했다고 말씀해 주세요. 재학 학교·학년, 희망 과목, 가능한 요일을 함께 알려주시면 됩니다.') + '<div class="branch-actions">' + button('tel:01068398283', '전화 상담') + button('/상담문의/', '상담 준비사항', True) + '</div>')
    body += '</div>'
    html = page(full_title, meta, path, crumbs, body, graph, detail=True)
    html = html.replace('class="branch-page branch-detail-page"', 'class="branch-page branch-detail-page branch-neighborhood-page"')
    html = html.replace('</head>', '<link rel="stylesheet" href="/assets/branch-neighborhoods.css">\n</head>')
    if revised_grade:
        html = html.replace('class="branch-page branch-detail-page branch-neighborhood-page"', 'class="branch-page branch-detail-page branch-neighborhood-page branch-grade-page"')
        html = html.replace('</head>', '<link rel="stylesheet" href="/assets/branch-grades.css">\n</head>')
    html = html.replace('<meta property="og:type" content="website">', '<meta property="og:type" content="article">')
    return path, html


def main():
    parser = argparse.ArgumentParser()
    saved_mapping = DATA / 'mapping.json'
    parser.add_argument('--mapping', type=Path, default=saved_mapping if saved_mapping.exists() else MAPPING)
    parser.add_argument('--allow-partial', action='store_true', help='Generate only confirmed mappings, report all pending rows')
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text(encoding='utf-8'))
    rows = mapping['rows']
    pending = [r for r in rows if r['status'] != 'confirmed']
    if pending and not args.allow_partial:
        raise ValueError(f'{len(pending)} neighborhoods need a reviewed parent mapping')
    mapped = {r['locality']: r for r in rows if r['status'] == 'confirmed'}
    _, centers, reference = load_branch_data()
    by_id = {c['id']: c for c in centers}
    pool = representative_pool()
    raw_schools = json.loads((BRANCH_DATA / 'target-schools.json').read_text(encoding='utf-8'))
    schools = {row['neighborhood']: row for row in raw_schools}
    manuscript_sets = [load_manuscript_archive(copy_archive(SOURCE / (subject + '학원.zip')), subject) for subject in ('영어', '수학')]
    polish_changes = []
    for group in manuscript_sets:
        for i, manuscript in enumerate(group):
            if manuscript['locality'] not in mapped:
                continue
            c = by_id[mapped[manuscript['locality']]['centerId']]
            ref = reference['centers'][c['id']]
            group[i], changes = prepare_editorial(manuscript, scope_confirmed=subject_scope_confirmed(c, ref, manuscript['subject']))
            for key in ('title', 'meta', 'locality', 'subject', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256'):
                if group[i][key] != manuscript[key]:
                    raise ValueError(f'Editorial overlay changed protected field: {manuscript["title"]} {key}')
            if [s['heading'] for s in group[i]['sections']] != [s['heading'] for s in manuscript['sections']]:
                raise ValueError('Editorial overlay changed stable section headings')
            if any(not s['paragraphs'] or any(not p.strip() for p in s['paragraphs']) for s in group[i]['sections']):
                raise ValueError('Editorial overlay produced an empty section')
            polish_changes.extend({'locality': manuscript['locality'], 'subject': manuscript['subject'], **change} for change in changes)
    if set(m['locality'] for m in manuscript_sets[0]) != set(m['locality'] for m in manuscript_sets[1]):
        raise ValueError('The two archives have different neighborhood sets')
    if set(r['locality'] for r in rows) != set(m['locality'] for m in manuscript_sets[0]):
        raise ValueError('Mapping does not cover the manuscript inventory exactly')
    plan = []
    for category_index, manuscripts in enumerate(manuscript_sets):
        for locality_index, manuscript in enumerate(manuscripts):
            mapping_row = mapped.get(manuscript['locality'])
            if mapping_row is None:
                continue
            c = by_id[mapping_row['centerId']]
            ref = reference['centers'][c['id']]
            if not ref.get('primaryMedia', {}).get('map') or not ref['primaryMedia'].get('body'):
                raise ValueError(f'Missing approved map/body for {c["sourceCenterName"]}')
            representative = pool[(locality_index + category_index * 97) % len(pool)]
            path = child_path(c, manuscript)
            record = {key: manuscript[key] for key in ('locality', 'subject', 'title', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256')}
            record.update({'path': path, 'centerId': c['id'], 'parentPath': branch_path(c), 'representative': representative,
                           'sectionCount': len(manuscript['sections']), 'faqCount': len(manuscript['faq'])})
            plan.append((record, manuscript, c, ref))
    if len({r['path'] for r, *_ in plan}) != len(plan):
        raise ValueError('Duplicate child URLs')
    manifest_path = DATA / 'pages.json'
    previous = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {'pages': []}
    owned_paths = {r['path'] for r in previous['pages']}
    planned_paths = {r['path'] for r, *_ in plan}
    if owned_paths - planned_paths:
        raise ValueError('Previous child pages would be orphaned; review them before changing scope')
    rendered = []
    for record, manuscript, center, ref in plan:
        destination = (ROOT / record['path'].strip('/') / 'index.html').resolve()
        if not destination.is_relative_to((ROOT / branch_path(center).strip('/')).resolve()):
            raise ValueError('Destination outside selected parent')
        siblings = [r for r, *_ in plan if r['centerId'] == center['id']]
        path, html = render(center, ref, manuscript, record['representative'], schools.get(manuscript['locality'], {}), siblings)
        if destination.exists() and path not in owned_paths:
            raise ValueError(f'Refusing to overwrite unrelated page: {destination}')
        rendered.append((destination, html))
    changed = sum(write_changed(path, html) for path, html in rendered)
    write_changed(saved_mapping, args.mapping.read_text(encoding='utf-8'))
    records = [r for r, *_ in plan]
    write_changed(manifest_path, json.dumps({'version': 1, 'mappingSha256': sha(args.mapping), 'pages': records}, ensure_ascii=False, indent=2) + '\n')
    report = {'status': 'PARTIAL' if pending else 'COMPLETE', 'sourceManuscripts': sum(map(len, manuscript_sets)),
              'generatedPages': len(records), 'changedPages': changed, 'bySubject': dict(Counter(r['subject'] for r in records)),
              'parentCenters': len({r['centerId'] for r in records}), 'pendingNeighborhoods': pending,
              'pendingPages': len(pending) * 2, 'deployment': 'NOT DEPLOYED - local only'}
    report.update({'manuscriptPolishApplied': True, 'editorialEdition': 2,
                   'editorialReviewDate': EDITORIAL_REVIEW_DATE,
                   'polishedPages': len({(c['locality'], c['subject']) for c in polish_changes}),
                   'polishedFields': len({(c['locality'], c['subject'], c['field']) for c in polish_changes}),
                   'polishedPhrases': sum(c['count'] for c in polish_changes if c.get('stage') != 'editorial'),
                   'editorialOperations': sum(c['count'] for c in polish_changes if c.get('stage') == 'editorial')})
    write_changed(REPORTS / 'manuscript-polish.json', json.dumps({'changes': polish_changes}, ensure_ascii=False, indent=2) + '\n')
    school_reviews = []
    for locality, school_row in schools.items():
        public = public_school_groups(school_row)
        if public['reviewNotes']:
            school_reviews.append({'locality': locality, 'reviewNotes': public['reviewNotes']})
    write_changed(REPORTS / 'school-reader-notes.json', json.dumps({'reviews': school_reviews}, ensure_ascii=False, indent=2) + '\n')
    write_changed(REPORTS / 'generation.json', json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'pendingNeighborhoods'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
