"""Independent, local-only audit for branch neighborhood child pages.

The snapshot command records existing root/region/center HTML and referenced
asset hashes before generation. It never imports or runs either generator.
Only the new child-list section and its matching ItemList are removable when
comparing an existing parent with that baseline. No website files are written.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from zipfile import ZipFile

from bs4 import BeautifulSoup
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = Path('C:/Users/1992k/Desktop/CodexData/tmp/site15-branch-children-2026-09-09/before.json.gz')
DEFAULT_DATA = ROOT / 'tools/data/branch-neighborhoods/pages.json'
DEFAULT_REPORT = ROOT / 'reports/branch-neighborhoods/audit.json'
ALLOWED_SECTION = 'neighborhood-pages'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def route_for(path):
    return '/' + path.relative_to(ROOT).parent.as_posix() + '/'


def baseline_paths():
    return sorted(p for p in (ROOT / '지점안내').rglob('index.html')
                  if len(p.relative_to(ROOT).parts) <= 4)


def graphs(soup):
    result = []
    for script in soup.select('script[type="application/ld+json"]'):
        data = json.loads(script.string or script.get_text())
        if isinstance(data, list):
            result.extend(data)
        elif isinstance(data, dict):
            result.extend(data.get('@graph', [data]))
    return result


def normalized_parent(html, remove_additions=False):
    """Ignore formatting only; keep original attributes, text and schema values."""
    soup = BeautifulSoup(html, 'html.parser')
    canonical = soup.select_one('link[rel="canonical"]')
    added_id = (canonical.get('href', '') if canonical else '') + '#' + ALLOWED_SECTION
    if remove_additions:
        for section in soup.select('section#' + ALLOWED_SECTION):
            section.decompose()
    for script in soup.select('script[type="application/ld+json"]'):
        data = json.loads(script.string or script.get_text())
        if remove_additions and isinstance(data, dict) and '@graph' in data:
            data['@graph'] = [node for node in data['@graph']
                             if not (node.get('@type') == 'ItemList' and node.get('@id') == added_id)]
            for node in data['@graph']:
                if node.get('@type') == 'WebPage' and isinstance(node.get('hasPart'), list):
                    node['hasPart'] = [part for part in node['hasPart'] if part != {'@id': added_id}]
        script.string = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    # Only drop whitespace-only nodes: meaningful prose whitespace is preserved.
    for node in list(soup.find_all(string=True)):
        if not str(node).strip():
            node.extract()
    return str(soup)


def local_resource(url, page):
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    dest = (ROOT / unquote(parsed.path).lstrip('/') if parsed.path.startswith('/')
            else page.parent / unquote(parsed.path)).resolve()
    try:
        dest.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return dest


def resource_urls(soup):
    result = set()
    for node in soup.select('img[src], script[src], source[src], video[poster], link[href]'):
        if node.name == 'link' and not set(node.get('rel', [])) & {'stylesheet', 'icon', 'preload', 'apple-touch-icon'}:
            continue
        result.add(node.get('src') or node.get('poster') or node.get('href'))
    for node in soup.select('[srcset]'):
        result.update(part.strip().split()[0] for part in node['srcset'].split(',') if part.strip())
    for node in soup.select('[style], style'):
        value = node.get('style', '') + (node.get_text() if node.name == 'style' else '')
        result.update(re.findall(r'url\([\s\'\"]*([^\s\'\")]+)', value))
    return sorted(result)


def page_facts(html):
    soup = BeautifulSoup(html, 'html.parser')
    return {
        'title': soup.title.get_text() if soup.title else None,
        'h1': [node.get_text(' ', strip=True) for node in soup.select('h1')],
        'meta': [dict(node.attrs) for node in soup.select('head meta, head link')],
        'images': [dict(node.attrs) for node in soup.select('img')],
        'primaryMedia': [str(node) for node in soup.select('.branch-primary-media')],
        'fees': [str(node) for node in soup.select('[data-fee-region], .branch-fee-card')],
        'schema': graphs(soup),
        'sectionIds': [node['id'] for node in soup.select('section[id]')],
    }


def snapshot(path):
    if path.exists():
        raise RuntimeError(f'Refusing to overwrite existing baseline: {path}')
    pages = {}
    assets = {}
    for page in baseline_paths():
        raw = page.read_bytes()
        html = raw.decode('utf-8-sig')
        soup = BeautifulSoup(html, 'html.parser')
        if soup.select('section#' + ALLOWED_SECTION):
            raise RuntimeError(f'Baseline already contains new child section: {page}')
        route = route_for(page)
        pages[route] = {'relativePath': page.relative_to(ROOT).as_posix(),
                        'sha256': sha256(raw), 'bytes': len(raw), 'html': html,
                        'normalizedSha256': sha256(normalized_parent(html).encode('utf-8')),
                        'facts': page_facts(html)}
        for url in resource_urls(soup):
            asset = local_resource(url, page)
            if not asset or not asset.is_file():
                continue
            key = asset.relative_to(ROOT).as_posix()
            if key not in assets:
                blob = asset.read_bytes()
                assets[key] = {'bytes': len(blob), 'sha256': sha256(blob)}
    levels = Counter(len(route.strip('/').split('/')) for route in pages)
    payload = {'version': 1, 'createdAt': datetime.now(timezone.utc).isoformat(),
               'root': str(ROOT), 'counts': {'pages': len(pages), 'directory': levels[1],
               'regions': levels[2], 'centers': levels[3], 'assets': len(assets)},
               'allowedParentAdditions': {'sectionId': ALLOWED_SECTION,
                   'itemListId': 'parent canonical + #neighborhood-pages'},
               'pages': pages, 'assets': assets}
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wt', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(',', ':'))
    return {'snapshot': str(path), **payload['counts'], 'compressedBytes': path.stat().st_size}


def preservation_audit(baseline, errors):
    current_paths = {route_for(path) for path in baseline_paths()}
    expected_paths = set(baseline['pages'])
    if current_paths != expected_paths:
        errors.append({'check': 'parent-path-set', 'missing': sorted(expected_paths - current_paths),
                       'unexpected': sorted(current_paths - expected_paths)})
    changed = []
    for route, old in baseline['pages'].items():
        path = ROOT / old['relativePath']
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if sha256(raw) == old['sha256']:
            continue
        changed.append(route)
        html = raw.decode('utf-8-sig')
        if sha256(normalized_parent(html, True).encode('utf-8')) != old['normalizedSha256']:
            errors.append({'check': 'parent-content-preservation', 'route': route,
                           'detail': 'Changes remain after removing the permitted section and ItemList.'})
        new_facts = page_facts(html)
        for key in ('title', 'h1', 'meta', 'images', 'primaryMedia', 'fees'):
            if old['facts'][key] != new_facts[key]:
                errors.append({'check': 'parent-' + key + '-preservation', 'route': route})
    for name, old in baseline['assets'].items():
        asset = ROOT / name
        if not asset.is_file() or sha256(asset.read_bytes()) != old['sha256']:
            errors.append({'check': 'asset-preservation', 'path': name})
    return {'checkedParents': len(expected_paths), 'changedParents': changed,
            'checkedExistingAssets': len(baseline['assets'])}


def normalized_text(value):
    return re.sub(r'\s+', ' ', value).strip()


def independent_manuscripts(data_dir, mapping, check):
    """Re-read raw ZIP bytes; deliberately do not use the generation parser."""
    records = {}
    archive_facts = []
    mapping_sources = {Path(row['path']).name: row for row in mapping['sources']}
    required = ['페이지타이틀', '메타설명', '본문', 'FAQ', '학부모후기', 'JSON-LD 요약']
    for subject in ('영어', '수학'):
        archive_path = data_dir / 'sources' / (subject + '학원.zip')
        archive_sha = sha256(archive_path.read_bytes())
        source = mapping_sources.get(archive_path.name, {})
        check(archive_sha == source.get('sha256'), 'source-archive-mapping-sha', archive_path.name)
        original = Path(source.get('path', ''))
        check(original.is_file() and sha256(original.read_bytes()) == archive_sha,
              'source-archive-original-sha', archive_path.name)
        count = 0
        with ZipFile(archive_path) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            check(len(infos) == 371, 'source-archive-member-count', archive_path.name)
            check(len({info.filename for info in infos}) == len(infos), 'source-archive-duplicate-members', archive_path.name)
            for info in infos:
                check(info.filename.endswith('.txt') and '..' not in Path(info.filename).parts,
                      'source-member-path', info.filename)
                raw = archive.read(info)
                text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
                blocks = list(re.finditer(r'^\[([^\]\n]+)\]\s*$', text, re.MULTILINE))
                check([m.group(1) for m in blocks] == required, 'source-blocks', info.filename)
                values = {m.group(1): text[m.end():blocks[i + 1].start() if i + 1 < len(blocks) else len(text)].strip()
                          for i, m in enumerate(blocks)}
                title = normalized_text(values['페이지타이틀'])
                locality = title.removesuffix(' ' + subject + '학원')
                check(title == locality + ' ' + subject + '학원', 'source-title-subject', info.filename)
                body = values['본문']
                headings = list(re.finditer(r'^##[ \t]+(.+)$', body, re.MULTILINE))
                sections = []
                for i, heading in enumerate(headings):
                    end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
                    paragraphs = [normalized_text(p) for p in re.split(r'\n\s*\n', body[heading.end():end]) if p.strip()]
                    sections.append({'heading': normalized_text(heading.group(1)), 'paragraphs': paragraphs})
                faqs = []
                for match in re.finditer(r'^Q(\d+)\.[ \t]*([^\n]+)\nA(\d*)\.[ \t]*(.*?)(?=^Q\d+\.|\Z)',
                                         values['FAQ'], re.MULTILINE | re.DOTALL):
                    check(int(match.group(1)) == len(faqs) + 1 and match.group(3) in ('', match.group(1)),
                          'source-faq-numbering', info.filename)
                    faqs.append({'question': normalized_text(match.group(2)), 'answer': normalized_text(match.group(4))})
                check(len(faqs) == 4, 'source-faq-four', info.filename)
                case_text = re.sub(r'^※[^\n]*학부모 관점의 상황 예시입니다\.[ \t]*(?:\n|$)', '', values['학부모후기'], count=1).strip()
                key = (locality, subject)
                check(key not in records, 'source-duplicate-locality-subject', info.filename)
                records[key] = {'title': title, 'locality': locality, 'subject': subject,
                    'meta': normalized_text(values['메타설명']),
                    'intro': normalized_text(body[:headings[0].start()]), 'sections': sections, 'faq': faqs,
                    'cases': [normalized_text(p) for p in re.split(r'\n\s*\n', case_text) if p.strip()],
                    'sourceMember': info.filename, 'sourceSha256': sha256(raw),
                    'sourceArchiveSha256': archive_sha}
                count += 1
        archive_facts.append({'path': str(archive_path), 'sha256': archive_sha, 'members': count})
    return records, archive_facts


def approved_display_records(records, generation, check):
    """Allow only the reviewed exact phrase overlay; keep raw ZIP records intact."""
    if generation.get('manuscriptPolishApplied') is not True:
        return records, {'applied': False, 'pages': 0, 'fields': 0, 'phrases': 0}
    from polish_branch_manuscripts import polish_manuscript

    # Independent allowlist: a new overlay rule requires explicit audit review.
    approved_pairs = {
        ('원고 참고 키워드', '상담 참고 항목'),
        ('원고를 찾는 과정에서', '학습 정보를 찾는 과정에서'),
        ('원고를 준비하는 과정에서', '상담을 준비하는 과정에서'),
        ('원고를 읽는 가정', '이 안내를 읽는 가정'),
        ('이 원고에서 확인되지 않은', '이 안내에서 확인되지 않은'),
        ('이 원고에 제공되지 않은', '이 안내에 제공되지 않은'),
        ('이 원고에서 판단할 수 없으므로', '이 안내에서 판단할 수 없으므로'),
        ('입력된 학교 정보', '참고 학교 정보'),
        ('입력 정보만으로', '이 안내만으로'),
        ('입력만으로', '이 안내만으로'),
        ('D열에 제시된 학교 중', '안내된 학교 중'),
    }
    displays = {}
    all_changes = []
    for key, original in records.items():
        before = copy.deepcopy(original)
        polished, changes = polish_manuscript(original)
        check(original == before, 'overlay-does-not-mutate-source', original['sourceMember'])
        replayed = copy.deepcopy(before)
        for change in changes:
            check((change['before'], change['after']) in approved_pairs, 'overlay-approved-phrase-only', original['sourceMember'], change)
            field = change['field']
            allowed_field = re.fullmatch(r'(?:title|meta|intro|sections\[\d+\]\.(?:heading|paragraphs\[\d+\])|faq\[\d+\]\.(?:question|answer)|cases\[\d+\])', field)
            check(allowed_field is not None, 'overlay-public-field-only', original['sourceMember'], field)
            parts = re.findall(r'([A-Za-z]+)|\[(\d+)\]', field)
            keys = [name if name else int(index) for name, index in parts]
            target = replayed
            for item in keys[:-1]:
                target = target[item]
            value, count = re.subn(r'(?<![가-힣A-Za-z0-9_])' + re.escape(change['before']), change['after'], target[keys[-1]])
            target[keys[-1]] = value
            check(count == change['count'], 'overlay-replacement-count', original['sourceMember'], field)
            all_changes.append({'locality': original['locality'], 'subject': original['subject'], **change})
        check(replayed == polished, 'overlay-no-unreported-rewriting', original['sourceMember'])
        for field in ('title', 'locality', 'subject', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256'):
            check(polished[field] == before[field], 'overlay-preserves-' + field, original['sourceMember'])
        displays[key] = polished
    summary = {'applied': True, 'pages': len({(c['locality'], c['subject']) for c in all_changes}),
               'fields': len({(c['locality'], c['subject'], c['field']) for c in all_changes}),
               'phrases': sum(c['count'] for c in all_changes),
               'rules': dict(Counter(c['rule'] for c in all_changes))}
    for key, field in [('polishedPages', 'pages'), ('polishedFields', 'fields'), ('polishedPhrases', 'phrases')]:
        check(generation.get(key) == summary[field], 'overlay-generation-' + key)
    report = read_json(ROOT / 'reports/branch-neighborhoods/manuscript-polish.json')
    stable = lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True)
    check(Counter(map(stable, report['changes'])) == Counter(map(stable, all_changes)), 'overlay-change-report-parity')
    return displays, summary


def child_audit(args, baseline, errors):
    stats = Counter()

    def check(ok, name, location='', detail=None):
        stats['assertions'] += 1
        if not ok:
            error = {'check': name, 'location': location}
            if detail is not None:
                error['detail'] = detail
            errors.append(error)

    manifest = read_json(args.data)
    generation = read_json(ROOT / 'reports/branch-neighborhoods/generation.json')
    pages = manifest['pages']
    mapping_path = ROOT / 'reports/branches/neighborhood-mapping.json'
    mapping = read_json(mapping_path)
    mapping_rows = {row['locality']: row for row in mapping['rows']}
    check(manifest['mappingSha256'] == sha256(mapping_path.read_bytes()), 'mapping-sha')
    check(len(pages) == 742, 'manifest-page-count')
    check(len(mapping_rows) == 371 and all(r['status'] == 'confirmed' for r in mapping_rows.values()), 'mapping-confirmed-coverage')
    check(Counter(p['subject'] for p in pages) == {'영어': 371, '수학': 371}, 'manifest-subject-counts')
    page_by_route = {p['path']: p for p in pages}
    check(len(page_by_route) == len(pages), 'manifest-path-uniqueness')
    records, archive_facts = independent_manuscripts(args.data.parent, mapping, check)
    display_records, polish_summary = approved_display_records(records, generation, check)
    check({(p['locality'], p['subject']) for p in pages} == set(records), 'source-manifest-exact-coverage')
    actual_paths = {route_for(p) for p in (ROOT / '지점안내').rglob('index.html')
                    if len(p.relative_to(ROOT).parts) > 4}
    check(actual_paths == set(page_by_route), 'child-html-exact-path-set',
          detail={'missing': sorted(set(page_by_route) - actual_paths), 'unexpected': sorted(actual_paths - set(page_by_route))})
    by_parent = defaultdict(list)
    for record in pages:
        by_parent[record['parentPath']].append(record)
    check(len(by_parent) == 188, 'parent-center-count')
    parents = {}
    for route, old in baseline['pages'].items():
        soup = BeautifulSoup((ROOT / old['relativePath']).read_text(encoding='utf-8-sig'), 'html.parser')
        parents[route] = soup
        children = sorted(by_parent.get(route, []), key=lambda p: (p['locality'], p['subject']))
        sections = soup.select('section#neighborhood-pages')
        nodes = graphs(soup)
        canonical = soup.select_one('link[rel="canonical"]')['href']
        lists = [n for n in nodes if n.get('@id') == canonical + '#neighborhood-pages']
        check(len(sections) == (1 if children else 0), 'parent-child-section-count', route)
        check(len(lists) == (1 if children else 0), 'parent-child-list-count', route)
        if children and sections and lists:
            section = sections[0]
            hero = soup.select_one('.branch-detail-hero')
            check(hero is not None and hero.find_next_sibling() == section and
                  section.find_next_sibling() == soup.select_one('.branch-primary-media'), 'parent-child-section-position', route)
            check([(a.get('href'), a.get_text()) for a in section.select('a[href]')] ==
                  [(p['path'], p['title']) for p in children], 'parent-child-link-exact-set-order', route)
            expected_list = [{'@type': 'ListItem', 'position': i, 'name': p['title'],
                              'url': urlsplit(canonical).scheme + '://' + urlsplit(canonical).netloc + quote(p['path'], safe='/')}
                             for i, p in enumerate(children, 1)]
            itemlist = lists[0]
            check(itemlist.get('@type') == 'ItemList' and itemlist.get('numberOfItems') == len(children) and
                  itemlist.get('itemListElement') == expected_list, 'parent-itemlist-parity', route)
            webpage = next(n for n in nodes if n.get('@type') == 'WebPage')
            check(webpage.get('hasPart', []).count({'@id': canonical + '#neighborhood-pages'}) == 1,
                  'parent-child-hasPart', route)
    raw_centers = read_json(ROOT / 'tools/data/branches/centers.json')['centers']
    reference = read_json(ROOT / 'tools/data/branches/reference-content.json')
    centers = {c['id']: c for c in raw_centers + reference.get('additionalCenters', [])}
    pool = read_json(ROOT / 'assets/representative/manifest.json')['images']
    pool_by_name = {p['asset_name']: p for p in pool}
    check(len(pool_by_name) == 371, 'representative-pool-count')
    source_image_dir = ROOT.parent / '참고자료/공통자료/대표이미지'
    verified_images = {}
    verified_links = {}
    missing_service = []
    all_titles, all_descriptions = [], []
    school_rows = {r['neighborhood']: r for r in read_json(ROOT / 'tools/data/branches/target-schools.json')}

    def image_check(src, page, expected_sha, expected_size=None, original=None):
        asset = local_resource(src, page)
        check(asset is not None and asset.is_file(), 'image-local-exists', route, src)
        if not asset or not asset.is_file():
            return
        if str(asset) not in verified_images:
            raw = asset.read_bytes()
            with Image.open(asset) as image:
                image.verify()
            with Image.open(asset) as image:
                size = image.size
            verified_images[str(asset)] = {'sha256': sha256(raw), 'size': size}
        observed = verified_images[str(asset)]
        check(observed['sha256'] == expected_sha, 'image-source-bytes', route, src)
        if expected_size:
            check(observed['size'] == expected_size, 'image-dimensions', route, src)
        if original:
            check(original.is_file() and sha256(original.read_bytes()) == expected_sha, 'representative-original-bytes', route, src)

    for record in pages:
        route = record['path']
        page = ROOT / route.strip('/') / 'index.html'
        try:
            manuscript = records[(record['locality'], record['subject'])]
            mapping_row = mapping_rows[record['locality']]
            parent_route = record['parentPath']
            check(record['centerId'] == mapping_row['centerId'] and parent_route == mapping_row['branchPath'] and
                  route == mapping_row['childPaths'][record['subject']], 'mapping-center-parent-child', route)
            check(parent_route in baseline['pages'] and len(parent_route.strip('/').split('/')) == 3,
                  'parent-is-existing-center', route)
            check(route == parent_route + record['locality'] + record['subject'] + '학원/', 'child-route-format', route)
            check(len(route.strip('/').split('/')) == 4 and page.resolve().is_relative_to((ROOT / parent_route.strip('/')).resolve()),
                  'child-route-depth-safety', route)
            for key in ('title', 'locality', 'subject', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256'):
                check(record[key] == manuscript[key], 'manifest-source-' + key, route)
            check(record['sectionCount'] == len(manuscript['sections']) and record['faqCount'] == 4, 'manifest-source-counts', route)
            manuscript = display_records[(record['locality'], record['subject'])]
            html = page.read_text(encoding='utf-8-sig')
            soup = BeautifulSoup(html, 'html.parser')
            parent = parents[parent_route]
            parent_canonical = parent.select_one('link[rel="canonical"]')['href']
            origin = urlsplit(parent_canonical).scheme + '://' + urlsplit(parent_canonical).netloc
            canonical = origin + quote(route, safe='/')
            parent_org = next(n for n in graphs(parent) if n.get('@type') == 'EducationalOrganization')
            center = centers[record['centerId']]
            title = record['title']
            full_title = title + ' | ' + center['sourceCenterName'] + ' · 영수코칭'
            all_titles.append(full_title)
            all_descriptions.append(manuscript['meta'])
            check(soup.body is not None and 'branch-neighborhood-page' in soup.body.get('class', []), 'child-body-class', route)
            check(len(soup.select('h1')) == 1 and soup.h1.get_text() == title, 'child-h1', route)
            check(soup.title.get_text() == full_title, 'child-title', route)
            for selector, attr, expected in [
                ('link[rel="canonical"]', 'href', canonical),
                ('meta[name="description"]', 'content', manuscript['meta']),
                ('meta[property="og:url"]', 'content', canonical),
                ('meta[property="og:type"]', 'content', 'article'),
                ('meta[property="og:title"]', 'content', full_title),
                ('meta[property="og:description"]', 'content', manuscript['meta']),
                ('meta[name="twitter:title"]', 'content', full_title),
                ('meta[name="twitter:description"]', 'content', manuscript['meta'])]:
                nodes = soup.select(selector)
                check(len(nodes) == 1 and nodes[0].get(attr) == expected, 'child-meta-' + selector, route)
            check('noindex' not in str(soup.select_one('meta[name="robots"]')), 'child-indexable', route)
            check(soup.select_one('.branch-manuscript-intro').get_text() == manuscript['intro'], 'source-intro-preservation', route)
            actual_sections = soup.select('section[id^="section-"]')
            check(len(actual_sections) == len(manuscript['sections']), 'source-section-count', route)
            for index, expected in enumerate(manuscript['sections'], 1):
                section = soup.find(id='section-' + str(index))
                check(section is not None and section.h2.get_text() == expected['heading'], 'source-section-heading', route, index)
                check(section is not None and [p.get_text() for p in section.select('p.branch-manuscript-paragraph')] == expected['paragraphs'],
                      'source-section-paragraphs', route, index)
                stats['sourceSections'] += 1
                stats['sourceParagraphs'] += len(expected['paragraphs'])
            faqs = soup.select('#questions .branch-faq details')
            check(len(faqs) == 4, 'visible-faq-four', route)
            for faq, expected in zip(faqs, manuscript['faq']):
                check(faq.summary.get_text() == expected['question'] and faq.p.get_text() == expected['answer'], 'source-faq-preservation', route)
            cases = soup.select('#consultation-example p')
            check([p.get_text() for p in cases] == manuscript['cases'], 'source-case-preservation', route)
            check('상담 준비 예시' in soup.select_one('#consultation-example h2').get_text(), 'case-example-label', route)
            school_groups = school_rows[record['locality']].get('targetSchools', {})
            expected_schools = [name for level in ('elementary', 'middle', 'high') for name in dict.fromkeys(school_groups.get(level, []))]
            check([n.get_text() for n in soup.select('#schools .branch-school-list li')] == expected_schools, 'locality-school-list', route)
            toc_expected = [('center-info', '지점·수업 정보')] + [('section-' + str(i), s['heading']) for i, s in enumerate(manuscript['sections'], 1)]
            if school_groups:
                toc_expected.append(('schools', '학교별 상담 준비'))
            toc_expected += [('questions', '자주 묻는 질문'), ('consultation-example', '상담 준비 예시'), ('related-pages', '관련 동네·과목 안내')]
            check([(a.get('href'), a.get_text()) for a in soup.select('#article-toc a')] == [('#' + anchor, name) for anchor, name in toc_expected],
                  'toc-order-and-headings', route)
            ids = [n['id'] for n in soup.select('[id]')]
            check(len(ids) == len(set(ids)), 'html-unique-ids', route)
            for node in soup.select('a[href], link[href], img[src], script[src]'):
                ref = node.get('href') or node.get('src')
                parsed = urlsplit(ref)
                if parsed.scheme in ('tel', 'mailto') or (parsed.netloc and parsed.netloc != urlsplit(canonical).netloc):
                    continue
                local_ref = parsed.path + ('#' + parsed.fragment if parsed.fragment else '')
                if not parsed.path:
                    check(not parsed.fragment or unquote(parsed.fragment) in ids, 'local-fragment', route, ref)
                    continue
                dest = local_resource(local_ref, page)
                if dest and (parsed.path.endswith('/') or dest.is_dir()):
                    dest /= 'index.html'
                cache_key = (str(dest), parsed.fragment)
                if cache_key not in verified_links:
                    exists = dest is not None and dest.is_file()
                    if exists and parsed.fragment:
                        target = BeautifulSoup(dest.read_text(encoding='utf-8-sig'), 'html.parser')
                        exists = target.find(id=unquote(parsed.fragment)) is not None
                    verified_links[cache_key] = exists
                check(verified_links[cache_key], 'local-link-target', route, ref)
            check(str(soup.select_one('.floating-actions')) == str(parent.select_one('.floating-actions')), 'floating-contact-preservation', route)
            check(len(soup.select('a[href="tel:01068398283"]')) >= 1, 'common-contact-target', route)
            check(not soup.select('form, iframe, [onclick]'), 'no-foreign-interactive-html', route)
            check('wa-wacenter.com' not in html and '010-9220-0653' not in html, 'no-reference-site-contact-leak', route)
            siblings = sorted([p for p in by_parent[parent_route] if p['path'] != route],
                              key=lambda p: (p['locality'] != record['locality'], p['locality'], p['subject']))[:6]
            related = soup.select('#related-pages a')
            check([(a.get('href'), a.get_text()) for a in related] == [(parent_route, center['displayName'] + ' 전체 안내')] +
                  [(p['path'], p['title']) for p in siblings], 'related-parent-and-sibling-links', route)
            check(soup.select_one('.branch-child-quick a')['href'] == parent_route, 'hero-parent-link', route)
            for fragment in ('tuition', 'directions'):
                check(any(a.get('href') == parent_route + '#' + fragment for a in soup.select('#center-info a')), 'parent-' + fragment + '-link', route)

            # Compare cloned parent media DOM with only the page-specific ALT changed.
            containers = soup.select('.branch-primary-media')
            check(len(containers) == 1 and len(containers[0].select('img')) == 3, 'three-primary-images', route)
            media = containers[0]
            representative = media.select_one('.branch-representative-image')
            rep_img = representative.img
            rep = record['representative']
            source_rep = pool_by_name.get(rep['asset_name'])
            check(source_rep is not None and all(rep[k] == source_rep[k] for k in ('asset_name', 'source_name', 'sha256')), 'representative-manifest-source', route)
            check(rep_img.get('style') == 'display:none;' and rep_img.get('alt') == title + ' 영수코칭 대표' and
                  rep_img.get('src') == rep['src'], 'representative-hidden-alt-src', route)
            check(rep_img.get('width') == str(rep['width']) and rep_img.get('height') == str(rep['height']), 'representative-html-dimensions', route)
            image_check(rep['src'], page, rep['sha256'], (rep['width'], rep['height']), source_image_dir / rep['source_name'])
            check(media.find_all('figure', recursive=False)[0] == representative, 'representative-first', route)
            expected_media = BeautifulSoup(baseline['pages'][parent_route]['facts']['primaryMedia'][0], 'html.parser')
            for kind, label in [('body', '본문'), ('map', '지도')]:
                expected_img = expected_media.select_one('.branch-' + kind + '-image img')
                actual_img = media.select_one('.branch-' + kind + '-image img')
                check(expected_img is not None and actual_img is not None, 'parent-' + kind + '-image', route)
                if expected_img is not None and actual_img is not None:
                    expected_img['alt'] = title + ' ' + label
                    check(actual_img.attrs == expected_img.attrs, 'parent-' + kind + '-image-attributes', route)
                    local = local_resource(expected_img['src'], page)
                    baseline_asset = baseline['assets'][local.relative_to(ROOT).as_posix()]
                    image_check(expected_img['src'], page, baseline_asset['sha256'])
            media_copy = BeautifulSoup(str(media), 'html.parser')
            media_copy.select_one('.branch-representative-image').decompose()
            check(str(media_copy) == str(expected_media), 'parent-media-panel-dom-preservation', route)
            check(soup.select_one('.branch-child-hero').find_next_sibling() == media and media.find_next_sibling() == soup.select_one('#article-toc'),
                  'child-primary-media-position', route)
            check(len(soup.select('link[href="/assets/branch-neighborhoods.css"]')) == 1, 'child-stylesheet', route)

            nodes = graphs(soup)
            node_ids = [n.get('@id') for n in nodes]
            check(all(node_ids) and len(node_ids) == len(set(node_ids)), 'schema-unique-ids', route)
            by_id = {n.get('@id'): n for n in nodes}
            articles = [n for n in nodes if n.get('@type') == 'Article']
            check(len(articles) == 1, 'article-count', route)
            article = articles[0]
            check(article.get('@id') == canonical + '#article' and article.get('url') == canonical and
                  article.get('mainEntityOfPage') == {'@id': canonical + '#webpage'} and
                  article.get('isPartOf') == {'@id': parent_canonical + '#webpage'}, 'article-canonical-parent-identity', route)
            check(article.get('headline') == title and article.get('description') == manuscript['meta'] and
                  article.get('articleSection') == [s['heading'] for s in manuscript['sections']], 'article-source-text', route)
            webpage = by_id[canonical + '#webpage']
            check(webpage.get('mainEntity') == {'@id': canonical + '#article'} and webpage.get('about') == {'@id': parent_canonical + '#center'} and
                  webpage.get('isPartOf') == {'@id': parent_canonical + '#webpage'}, 'webpage-article-parent-identity', route)
            organizations = [n for n in nodes if n.get('@type') == 'EducationalOrganization']
            check(len(organizations) == 1 and organizations[0].get('@id') == parent_canonical + '#center', 'parent-organization-id', route)
            for key in ('@id', 'url', 'name', 'address', 'legalName', 'identifier', 'mainEntityOfPage'):
                check(organizations[0].get(key) == parent_org.get(key), 'parent-organization-' + key, route)
            check('telephone' not in organizations[0] and not any(n.get('@type') in ('Review', 'AggregateRating') for n in nodes), 'no-invented-organization-claims', route)
            summary = reference['centers'][record['centerId']].get('operations', {}).get('subjectDisplay', {})
            offers = (bool(summary.get(record['subject'], {}).get('includeInUnqualifiedAvailableSubjects'))
                      if summary else record['subject'] in center.get('availableSubjects', []))
            services = [n for n in nodes if n.get('@type') == 'Service']
            check(len(services) == (1 if offers else 0), 'service-supported-subject-only', route)
            if offers and services:
                service = services[0]
                check(service.get('@id') == canonical + '#service' and service.get('provider') == {'@id': parent_canonical + '#center'} and
                      service.get('mainEntityOfPage') == {'@id': canonical + '#webpage'}, 'service-identity-provider', route)
                check({'@id': canonical + '#service'} in article.get('about', []), 'article-service-relationship', route)
                stats['servicePages'] += 1
            else:
                missing_service.append({'path': route, 'centerId': record['centerId'], 'subject': record['subject']})
                check({'@id': canonical + '#service'} not in article.get('about', []), 'no-unsupported-service-reference', route)
            crumbs = [n for n in nodes if n.get('@type') == 'BreadcrumbList']
            crumb_routes = ['/', '/지점안내/', '/' + '/'.join(route.strip('/').split('/')[:2]) + '/', parent_route, route]
            check(len(crumbs) == 1 and len(crumbs[0]['itemListElement']) == 5, 'breadcrumb-five-levels', route)
            check([(n.get('position'), n.get('item')) for n in crumbs[0]['itemListElement']] ==
                  [(i, origin + quote(r, safe='/')) for i, r in enumerate(crumb_routes, 1)], 'breadcrumb-route-order', route)
            visible_crumb = soup.select_one('main > .shell > nav')
            check(visible_crumb is not None and [a.get('href') for a in visible_crumb.select('a')] == crumb_routes[:-1] and
                  title in visible_crumb.get_text(), 'visible-breadcrumb-route-order', route)
            faq_nodes = [n for n in nodes if n.get('@type') == 'FAQPage']
            check(len(faq_nodes) == 1 and faq_nodes[0].get('@id') == canonical + '#questions', 'faq-schema-identity', route)
            expected_faq = [{'@type': 'Question', 'name': f['question'], 'acceptedAnswer': {'@type': 'Answer', 'text': f['answer']}} for f in manuscript['faq']]
            check(faq_nodes[0].get('mainEntity') == expected_faq, 'faq-schema-source-parity', route)
            for part in webpage.get('hasPart', []):
                part_id = part.get('@id')
                element = soup.find(id=urlsplit(part_id).fragment)
                check(part_id in by_id and element is not None and by_id[part_id].get('name') == element.h2.get_text(),
                      'webpage-section-hasPart', route, part_id)
            stats['pages'] += 1
            stats['articles'] += len(articles)
            stats['faqEntries'] += len(faqs)
            stats['primaryImages'] += len(media.select('img'))
        except Exception as exc:
            check(False, 'page-audit-exception', route, type(exc).__name__ + ': ' + str(exc))
    check(len(missing_service) == 18, 'unsupported-service-omission-count', detail=len(missing_service))
    check(len(all_titles) == len(set(all_titles)), 'unique-page-titles')
    check(len(all_descriptions) == len(set(all_descriptions)), 'unique-meta-descriptions')
    for key, expected in [('status', 'COMPLETE'), ('sourceManuscripts', 742), ('generatedPages', 742),
                          ('parentCenters', 188), ('pendingPages', 0), ('pendingNeighborhoods', []),
                          ('bySubject', {'영어': 371, '수학': 371})]:
        check(generation.get(key) == expected, 'generation-report-' + key)
    sitemap = ET.parse(ROOT / 'sitemap.xml')
    sitemap_urls = [n.text for n in sitemap.getroot().iter() if n.tag.rsplit('}', 1)[-1] == 'loc']
    origin = urlsplit(next(iter(parents.values())).select_one('link[rel="canonical"]')['href'])
    origin_text = origin.scheme + '://' + origin.netloc
    for route in page_by_route:
        check(sitemap_urls.count(origin_text + quote(route, safe='/')) == 1, 'sitemap-child-exactly-once', route)
    return {'counts': dict(stats), 'sourceArchives': archive_facts,
            'approvedDisplayCorrections': polish_summary,
            'parentCentersWithChildren': len(by_parent), 'uniqueVerifiedImageAssets': len(verified_images),
            'omittedUnsupportedServices': missing_service,
            'independentParsing': 'Raw ZIP text parsed locally without importing either generator or branch_manuscripts.'}


def audit(args):
    with gzip.open(args.baseline, 'rt', encoding='utf-8') as handle:
        baseline = json.load(handle)
    errors = []
    checks = preservation_audit(baseline, errors)
    if not args.preservation_only:
        checks['children'] = child_audit(args, baseline, errors)
    result = {'version': 1, 'createdAt': datetime.now(timezone.utc).isoformat(),
              'status': 'PASS' if not errors else 'FAIL',
              'mode': 'preservation-only' if args.preservation_only else 'full',
              'baseline': str(args.baseline), 'dataFile': str(args.data),
              'checks': checks, 'errors': errors}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', action='store_true', help='Create an immutable pre-generation baseline.')
    parser.add_argument('--baseline', type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--report', type=Path, default=DEFAULT_REPORT)
    parser.add_argument('--preservation-only', action='store_true')
    args = parser.parse_args()
    generation_path = ROOT / 'reports/branch-neighborhoods/generation.json'
    if not args.snapshot and not args.preservation_only and generation_path.is_file() and read_json(generation_path).get('editorialEdition') == 2:
        print('Editorial edition 2 detected: delegating to audit_branch_improvements.py; the edition-1 report remains historical.', flush=True)
        return subprocess.call([sys.executable, str(ROOT / 'tools/audit_branch_improvements.py')])
    result = snapshot(args.baseline) if args.snapshot else audit(args)
    console_result = result if args.snapshot else {
        'status': result['status'], 'report': str(args.report), 'mode': result['mode'],
        'checkedParents': result['checks']['checkedParents'],
        'changedParents': len(result['checks']['changedParents']),
        'checkedExistingAssets': result['checks']['checkedExistingAssets'],
        'children': result['checks'].get('children', {}).get('counts'),
        'errorCount': len(result['errors']), 'firstErrors': result['errors'][:20]}
    print(json.dumps(console_result, ensure_ascii=False, indent=2))
    return 0 if args.snapshot or result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
