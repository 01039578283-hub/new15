"""Independent regression checks for the approved branch-directory update.

Read-only for the checkout. Snapshot/report files must be outside the checkout.
Run with the existing BeautifulSoup dependency used by audit_branch_pages.py.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
REMOVED_ROUTE = '/지점안내/경기/주엽2호점/'
GALMAE_ROUTE = '/지점안내/경기/갈매점/'
GOJAN_ROUTE = '/지점안내/경기/고잔점/'
GALMAE_LOCATION = '경기 구리시 갈매중앙로 79 에스엠타워 602호로 방문해 주세요.'
GOJAN_DIAGNOSIS = '현재 이해도와 풀이 습관을 함께 살핍니다. 진단할 과목과 진행 방식은 상담에서 확인해 주세요.'
DEFAULT_BASELINE = Path('C:/Users/1992k/Desktop/CodexData/tmp/site15-directory-update-2026-09-09/before-update.json.gz')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text(node) -> str:
    return ' '.join(node.get_text(' ', strip=True).split()) if node else ''


def external_destination(path: Path) -> Path:
    path = path.resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError('Snapshot/report output must be outside the checkout')
    return path


def write_json(path: Path, data: dict) -> None:
    path = external_destination(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    path.write_bytes(gzip.compress(content, mtime=0) if path.suffix == '.gz' else content)


def load_json(path: Path) -> dict:
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def local_target(ref: str) -> str | None:
    value = urlsplit(ref)
    if value.scheme or value.netloc:
        if value.hostname not in {'xn--9p4bn5e3wjn0a.com', '영수코칭.com'}:
            return None
    return unquote(value.path)


def capture_page(route: str, asset_hashes: dict) -> dict:
    file = ROOT / route.strip('/') / 'index.html'
    raw = file.read_bytes()
    soup = BeautifulSoup(raw.decode('utf-8'), 'html.parser')
    graph = []
    for script in soup.select('script[type="application/ld+json"]'):
        data = json.loads(script.string or script.get_text())
        graph.extend(data.get('@graph', [data]))
    images = []
    for image in soup.find_all('img'):
        images.append(dict(image.attrs))
        src = local_target(image.get('src', ''))
        if src and src.startswith('/') and src not in asset_hashes:
            image_file = ROOT / src.lstrip('/')
            asset_hashes[src] = digest(image_file.read_bytes()) if image_file.is_file() else None
    center_info = soup.select_one('#center-info')
    definitions = {}
    if center_info:
        for dt in center_info.find_all('dt'):
            dd = dt.find_next_sibling('dd')
            if dd:
                definitions[text(dt)] = text(dd)
    faq = []
    for detail in soup.select('.branch-faq details'):
        faq.append({'question': text(detail.find('summary')), 'answer': ' '.join(text(p) for p in detail.find_all('p'))})
    blocks = {section['id']: str(section) for section in soup.select('section.branch-panel[id]')}
    return {
        'route': route, 'fileSha256': digest(raw), 'title': text(soup.title), 'h1': text(soup.find('h1')),
        'meta': [dict(meta.attrs) for meta in soup.select('head meta')],
        'canonical': soup.find('link', rel='canonical').get('href'),
        'images': images, 'blocks': blocks, 'blockIds': list(blocks),
        'hero': str(soup.select_one('.branch-hero')), 'centerDefinitions': definitions, 'faq': faq,
        'organization': next((node for node in graph if node.get('@type') == 'EducationalOrganization'), None),
        'graph': graph,
        'processSteps': [{'title': text(li.find('strong')), 'text': text(li.find('p'))} for li in soup.select('.branch-process > li')],
    }


def snapshot() -> dict:
    generation_file = ROOT / 'reports/branches/generation.json'
    generation_bytes = generation_file.read_bytes()
    generation = json.loads(generation_bytes)
    assets = {}
    pages = {route: capture_page(route, assets) for route in generation['paths']}
    after = generation_file.read_bytes()
    if generation_bytes != after:
        raise RuntimeError('Generation report changed during snapshot; snapshot not saved')
    return {
        'schemaVersion': 1, 'capturedAtUtc': datetime.now(timezone.utc).isoformat(), 'repo': str(ROOT),
        'generationSha256': digest(generation_bytes), 'generation': generation, 'pages': pages,
        'imageAssetHashes': assets,
    }


def audit(baseline: dict) -> dict:
    """Implemented independently of the generator and existing audit."""
    current = snapshot()
    errors = []
    checks = 0

    def check(condition: bool, code: str, **details) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            errors.append({'code': code, **details})

    before = baseline['pages']
    now = current['pages']
    generation = current['generation']
    data = ROOT / 'tools/data/branches'
    reference = load_json(data/'reference-content.json')
    source_records = load_json(data/'centers.json')['centers'] + reference.get('additionalCenters', [])
    records_by_route = {'/지점안내/'+c['region']['province']+'/'+c['routeSlug']+'/': c for c in source_records}
    school_matches = {m['centerId']: m for m in load_json(data/'school-match-audit.json')['matches']}
    school_matches.update(reference.get('schoolMatches', {}))
    check(generation['centerCount'] == 193, 'center-count', actual=generation['centerCount'])
    check(generation['regionCount'] == 16 and generation['pageCount'] == 210, 'page-count', actual=generation['pageCount'])
    check(set(now) == set(before) - {REMOVED_ROUTE}, 'retained-route-set', removed=sorted(set(before)-set(now)), added=sorted(set(now)-set(before)))
    check(not (ROOT / REMOVED_ROUTE.strip('/') / 'index.html').exists(), 'removed-center-html-still-exists')

    protected_center_count = 0
    image_count = 0
    changed_process_routes = []
    for route, page in now.items():
        old = before.get(route)
        if old is None:
            continue
        source = (ROOT / route.strip('/') / 'index.html').read_text(encoding='utf-8')
        soup = BeautifulSoup(source, 'html.parser')
        check(page['title'] == old['title'], 'title-changed', route=route)
        check(page['h1'] == old['h1'], 'h1-changed', route=route)
        check(page['canonical'] == old['canonical'], 'canonical-changed', route=route)
        check(page['meta'] == old['meta'], 'metadata-changed', route=route)
        check(page['images'] == old['images'], 'image-markup-changed', route=route)
        image_count += len(page['images'])
        for anchor in soup.find_all('a', href=True):
            check(local_target(anchor['href']) != REMOVED_ROUTE, 'removed-center-link', route=route, href=anchor['href'])
        for node in page['graph']:
            check(REMOVED_ROUTE not in unquote(json.dumps(node, ensure_ascii=False)), 'removed-center-schema-reference', route=route)
        if page['organization']:
            protected_center_count += 1
            check(page['organization'] == old['organization'], 'business-identity-changed', route=route)
            check(page['blocks'].get('tuition') == old['blocks'].get('tuition'), 'tuition-changed', route=route)
            for label in ['주소', '안내 위치', '등록 학원명', '학원 등록번호']:
                check(page['centerDefinitions'].get(label) == old['centerDefinitions'].get(label), 'registered-fact-changed', route=route, label=label)
            allowed = {'consultation-guide', 'other-centers'}
            if route == GALMAE_ROUTE:
                allowed |= {'directions', 'questions'}
            for key in set(old['blocks']) | set(page['blocks']):
                if key not in allowed:
                    check(page['blocks'].get(key) == old['blocks'].get(key), 'unapproved-block-change', route=route, block=key)
            check(page['hero'] == old['hero'], 'hero-changed', route=route)
            expected_process = BeautifulSoup(old['blocks'].get('consultation-guide', ''), 'html.parser')
            for li in expected_process.select('.branch-process > li'):
                paragraph = li.find('p')
                if paragraph and '이 페이지 신청서나 카톡으로' in text(paragraph):
                    paragraph.string = ('이 페이지의 전화·문자·상담 버튼으로 '+records_by_route[route]['sourceCenterName']+
                                        ' 상담을 신청해 주세요. 학년·희망 과목·현재 고민을 알려주시면 됩니다.')
                if route == GOJAN_ROUTE and text(li.find('strong')) == '레벨 테스트' and paragraph:
                    paragraph.string = GOJAN_DIAGNOSIS
            check(str(expected_process) == page['blocks'].get('consultation-guide', ''), 'unapproved-process-change', route=route)
            if page['blocks'].get('consultation-guide') != old['blocks'].get('consultation-guide'):
                changed_process_routes.append(route)
            if route == GALMAE_ROUTE:
                old_guide = records_by_route[route]['locationGuide']
                for key in ['directions', 'questions']:
                    expected = old['blocks'][key].replace(escape(old_guide, quote=True), escape(GALMAE_LOCATION, quote=True))
                    check(page['blocks'][key] == expected, 'unexpected-galmae-location-change', route=route, block=key)
            check(not re.search(r'카톡|카카오|이\s*페이지\s*신청서', text(soup.find('main'))), 'nonexistent-contact-instructions', route=route)
            schema_faq = [{'question': ' '.join(text_value['name'].split()), 'answer': ' '.join(text_value['acceptedAnswer']['text'].split())}
                          for n in page['graph'] if n.get('@type') == 'FAQPage' for text_value in n.get('mainEntity', [])]
            check(schema_faq == page['faq'], 'faq-schema-visible-mismatch', route=route)
            for step in page['processSteps']:
                if re.search(r'문의|상담', step['title']):
                    check(not re.search(r'카톡|신청서', step['text']), 'uncorrected-consultation-step', route=route)
        else:
            search_roots = soup.select('[data-branch-search-root]')
            check(len(search_roots) == 1, 'search-root-count', route=route, actual=len(search_roots))
            if len(search_roots) == 1:
                search = search_roots[0]
                mode = 'directory' if route == '/지점안내/' else 'region'
                check(search.get('data-search-mode') == mode, 'search-mode', route=route)
                inputs = search.select('[data-branch-search-input]')
                check(len(inputs) == 1 and inputs[0].get('type') == 'search', 'search-input', route=route)
                if inputs:
                    control_id = inputs[0].get('id')
                    check(bool(control_id and soup.find('label', attrs={'for': control_id})), 'search-label', route=route)
                reset = search.select('[data-branch-search-reset]')
                check(len(reset) == 1 and reset[0].name == 'button' and reset[0].get('type') == 'button', 'search-reset', route=route)
                status = search.select('[data-branch-search-status]')
                check(len(status) == 1 and status[0].get('role') == 'status' and status[0].get('aria-live') == 'polite', 'search-live-status', route=route)
                empty = search.select('[data-branch-search-empty]')
                check(len(empty) == 1 and empty[0].has_attr('hidden'), 'search-empty-initial-state', route=route)
                cards = search.select('a.branch-center-card[data-branch-search]')
                expected = [p for p in now if now[p]['organization'] and (mode == 'directory' or p.startswith(route))]
                check({local_target(card.get('href','')) for card in cards} == set(expected), 'search-card-route-set', route=route, actual=len(cards), expected=len(expected))
                check(len(cards) == len(expected), 'search-card-count', route=route, actual=len(cards), expected=len(expected))
                for card in cards:
                    check(bool(card.get('data-branch-search','').strip()), 'empty-search-text', route=route, href=card.get('href'))
                    target = local_target(card.get('href', ''))
                    record = records_by_route.get(target)
                    if record:
                        search_text = ' '.join(card['data-branch-search'].split())
                        values = [record['sourceCenterName'], record['brandName'], record['address'], record['region']['province'], record['region']['administrativeAreaText']]
                        values += school_matches.get(record['id'], {}).get('neighborhoods', [])
                        for value in values:
                            check(' '.join(value.split()) in search_text, 'missing-search-source-value', route=route, target=target, value=value)
                if mode == 'directory':
                    results = search.select('[data-branch-search-results]')
                    check(len(results) == 1 and results[0].has_attr('hidden'), 'directory-empty-query-results-hidden', route=route)
                else:
                    check(bool(search.select('section[data-branch-search-group]')), 'region-search-groups', route=route)
                    check(bool(search.select('a[data-branch-search-jump]')), 'region-search-jumps', route=route)
            check(any((script.get('src') or '') == '/assets/branch-search.js' for script in soup.find_all('script')), 'search-script-missing', route=route)

    for src, expected in baseline['imageAssetHashes'].items():
        # Includes the removed page's assets: removing the route must not destroy reusable media.
        file = ROOT / src.lstrip('/')
        got = digest(file.read_bytes()) if file.is_file() else None
        check(got == expected and expected is not None, 'source-image-bytes-changed', src=src)

    check(len(changed_process_routes) == 95, 'approved-process-update-count', actual=len(changed_process_routes))
    scanned_public_html = 0
    ignored = {'.git', '.vercel', 'node_modules', 'tools', 'reports', 'test-results', 'playwright-report', 'tmp', '__pycache__'}
    for directory, directories, files in os.walk(ROOT):
        directories[:] = [name for name in directories if name not in ignored]
        for name in files:
            if not name.endswith('.html'):
                continue
            file = Path(directory)/name
            scanned_public_html += 1
            check(REMOVED_ROUTE not in unquote(file.read_text(encoding='utf-8')), 'removed-route-reference-in-public-html', file=str(file.relative_to(ROOT)))

    sitemap = ET.parse(ROOT / 'sitemap.xml')
    locations = [local_target(n.text or '') for n in sitemap.iter() if n.tag.rsplit('}', 1)[-1] == 'loc']
    check(REMOVED_ROUTE not in locations, 'removed-center-in-sitemap')
    for route in now:
        check(locations.count(route) == 1, 'retained-route-sitemap-count', route=route, count=locations.count(route))
    search_js = ROOT / 'assets/branch-search.js'
    check(search_js.is_file(), 'search-js-absent')
    if search_js.exists():
        js = search_js.read_text(encoding='utf-8')
        check(not re.search(r'\bfetch\s*\(|XMLHttpRequest|https?://', js), 'search-has-network-dependency')
    return {'schemaVersion': 1, 'completedAtUtc': datetime.now(timezone.utc).isoformat(),
            'scope': 'Independent read-only approved-change regression. No deployment or external calls.',
            'baselineGenerationSha256': baseline['generationSha256'], 'currentGenerationSha256': current['generationSha256'],
            'counts': {'checks': checks, 'retainedCenters': protected_center_count, 'pages': len(now), 'images': image_count,
                       'protectedImageFiles': len(baseline['imageAssetHashes']), 'changedProcessPages': len(changed_process_routes),
                       'scannedPublicHtmlFiles': scanned_public_html, 'failures': len(errors)},
            'changedProcessRoutes': changed_process_routes, 'errors': errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, help='Capture baseline once; refuses to overwrite an existing snapshot')
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE)
    parser.add_argument('--report', type=Path, default=DEFAULT_BASELINE.parent/'regression-report.json')
    args = parser.parse_args()
    if args.snapshot:
        target = external_destination(args.snapshot)
        if target.exists():
            parser.error('Baseline already exists; refusing to overwrite it')
        captured = snapshot()
        write_json(target, captured)
        print(json.dumps({'baseline': str(target), 'pages': len(captured['pages']), 'centers': captured['generation']['centerCount'],
                          'imageFiles': len(captured['imageAssetHashes']), 'generationSha256': captured['generationSha256']}, ensure_ascii=False))
        return 0
    result = audit(load_json(args.baseline))
    write_json(args.report, result)
    print(json.dumps({'report': str(args.report), 'counts': result['counts'], 'errors': result['errors']}, ensure_ascii=False))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
