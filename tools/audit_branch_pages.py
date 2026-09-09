"""Local-only structural and preservation checks for the branch directory."""
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from generate_branch_pages import ROOT, DATA, REPORTS, DOMAIN, FEES, EXCLUDED_CENTER_IDS, EXCLUDED_GLORID_IDS, EXCLUDED_WPLUS_IDS, branch_path, grade_ranges, url, load_branch_data, subject_summary, branch_summary, course_answer, weekend_detail, reader_text
from reconcile_branch_legacy_scope import target_pages, transform_html


def check(ok, message):
    if not ok:
        errors.append(message)


errors = []
bundle, centers, reference = load_branch_data()
center_by_path = {branch_path(c): c for c in centers}
matches = json.loads((DATA / 'school-match-audit.json').read_text(encoding='utf-8'))
match_by_id = {m['centerId']: m for m in matches['matches']}
match_by_id.update(reference.get('schoolMatches', {}))
subject_soup = BeautifulSoup((ROOT / '과목별학원' / 'index.html').read_text(encoding='utf-8'), 'html.parser')
expected_controls = str(subject_soup.select_one('.floating-actions'))
neighborhood_introductions = 0
missing_neighborhood_centers = []
primary_body_images = 0
primary_map_images = 0
verified_assets = set()
check('overflow: clip' in (ROOT / 'assets/branches.css').read_text(encoding='utf-8'), 'Combined map viewport must not scroll into another map panel')
# Child pages have a separate manuscript/media/parent preservation audit.
paths = sorted(p for p in (ROOT / '지점안내').rglob('index.html') if len(p.relative_to(ROOT).parts) <= 4)
alltitles = []
alldescriptions = []
for path in paths:
    route = '/' + path.relative_to(ROOT).parent.as_posix() + '/'
    soup = BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')
    expected = url(route)
    check(len(soup.select('h1')) == 1, f'{route}: H1 count')
    check(soup.select_one('link[rel="canonical"]')['href'] == expected, f'{route}: canonical')
    check(soup.select_one('meta[property="og:url"]')['content'] == expected, f'{route}: og:url')
    check(bool(soup.select_one('meta[name="description"]')['content']), f'{route}: description')
    check(soup.select_one('.nav a[aria-current="page"]')['href'] == '/지점안내/', f'{route}: active menu')
    alltitles.append(soup.title.text)
    alldescriptions.append(soup.select_one('meta[name="description"]')['content'])
    ids = [e['id'] for e in soup.select('[id]')]
    check(len(ids) == len(set(ids)), f'{route}: duplicate IDs')
    for a in soup.select('a[href], link[href], script[src], img[src]'):
        ref = a.get('href') or a.get('src')
        parsed = urlsplit(ref)
        if parsed.scheme or parsed.netloc:
            continue
        if parsed.path:
            dest = ROOT / unquote(parsed.path).lstrip('/') if parsed.path.startswith('/') else path.parent / unquote(parsed.path)
            if ref.endswith('/'):
                dest /= 'index.html'
            check(dest.exists(), f'{route}: missing local link {ref}')
        elif parsed.fragment:
            check(unquote(parsed.fragment) in ids, f'{route}: anchor {ref}')
    graph = json.loads(soup.select_one('script[type="application/ld+json"]').string)['@graph']
    check(len(soup.select('.floating-actions')) == 1 and str(soup.select_one('.floating-actions')) == expected_controls, f'{route}: subject-page floating controls mismatch')
    check(not soup.select('.branch-contact-bar'), f'{route}: obsolete branch contact bar')
    check('글로리드' not in str(soup), f'{route}: removed Glorid branch still referenced')
    check(all(name not in unquote(str(soup)) for name in ('(W+)', '대구역점2호관', '주엽2호점')), f'{route}: removed branch still referenced')
    check(not re.search(r'010[\s-]*6839[\s-]*8283', soup.get_text(' ', strip=True)), f'{route}: visible phone digits')
    for element in soup.select('[aria-label], [title], img[alt]'):
        check(not re.search(r'010[\s-]*6839[\s-]*8283', ' '.join(element.get(attr, '') for attr in ('aria-label', 'title', 'alt'))), f'{route}: phone digits in accessible label')
    galleries = soup.select('.branch-gallery')
    if galleries:
        check(len(galleries) == 1, f'{route}: gallery count')
        section = galleries[0].find_parent('section', class_='branch-panel')
        disclosure = section.select_one('details.branch-space-disclosure') if section else None
        shell = soup.select_one('main > .shell')
        check(disclosure is not None and not disclosure.has_attr('open'), f'{route}: gallery must default closed')
        check(galleries[0].find_parent('details') == disclosure, f'{route}: gallery outside disclosure')
        check(section is not None and section.parent == shell and shell.find_all(recursive=False)[-1] == section, f'{route}: gallery must be final main block')
        check(disclosure is not None and disclosure.select_one('summary > h2') is not None, f'{route}: gallery accessible summary heading')
        check(section is not None and expected + '#' + section['id'] in [p['@id'] for p in graph[1].get('hasPart', [])], f'{route}: gallery schema relation')
        if route in center_by_path:
            check(soup.select('.branch-toc a')[-1]['href'] == '#learning-space', f'{route}: gallery TOC order')
    check(not re.search(r'직통번호|학습 공간 참고 이미지|참고 사진입니다|자료상 |시간·과목 칸|원문:|운영 비고를 함께 반영', str(soup)), f'{route}: removed/editorial-only phrase leaked')
    check('010-9220-0653' not in str(soup), f'{route}: reference phone leaked')
    check(not soup.select('form, [onclick], iframe'), f'{route}: reference interactive HTML leaked')
    check('wa-wacenter.com' not in str(soup), f'{route}: foreign canonical/link/contact leaked')
    for img in soup.select('.branch-gallery img'):
        check(bool(img.get('alt','')) and '참고 이미지' not in img['alt'], f'{route}: image alternative text')
        check(not img.find_parent('figure').find('figcaption'), f'{route}: removed image caption restored')
        check(img.get('loading') == 'lazy' and img.get('width') and img.get('height'), f'{route}: gallery layout/loading')
    for faq in [x for x in graph if x['@type'] == 'FAQPage']:
        visible_faq = soup.select('.branch-faq details')
        check(len(visible_faq) == len(faq['mainEntity']), f'{route}: FAQ count')
        for el, data in zip(visible_faq, faq['mainEntity']):
            check(el.summary.get_text() == data['name'] and el.p.get_text() == data['acceptedAnswer']['text'], f'{route}: FAQ parity')
    graphids = [x['@id'] for x in graph]
    check(len(graphids) == len(set(graphids)), f'{route}: repeated schema IDs')
    web = graph[1]
    for part in web.get('hasPart', []):
        check(part['@id'] in graphids, f'{route}: unresolved section schema')
        fragment = unquote(urlsplit(part['@id']).fragment)
        check(fragment in ids, f'{route}: schema section anchor missing')
        element = soup.find(id=fragment)
        entity = next(x for x in graph if x['@id'] == part['@id'])
        check(entity.get('name') == element.h2.get_text(), f'{route}: schema section name parity')
    crumb = next(x for x in graph if x['@type'] == 'BreadcrumbList')
    check(len(crumb['itemListElement']) == len(route.strip('/').split('/')) + 1, f'{route}: breadcrumb depth')
    check(crumb['itemListElement'][-1]['item'] == expected, f'{route}: breadcrumb URL')
    if route in center_by_path:
        c = center_by_path[route]
        neighborhoods = list(dict.fromkeys(match_by_id.get(c['id'], {}).get('neighborhoods', [])))
        neighborhood_intro = soup.select_one('.branch-detail-hero .branch-hero-neighborhoods')
        if neighborhoods:
            neighborhood_introductions += 1
            check(neighborhood_intro is not None and neighborhood_intro.get_text().startswith('·'.join(neighborhoods) + '에서 학원을 찾는 학생이라면, '), f'{route}: supplied neighborhood introduction')
            check(soup.select_one('#schools .branch-neighborhoods') is not None, f'{route}: original neighborhood list missing')
        else:
            missing_neighborhood_centers.append(c['displayName'])
            check(neighborhood_intro is None, f'{route}: unsupported neighborhood introduction')
        check(' '.join(soup.h1.stripped_strings) == c['displayName'] == soup.title.text, f'{route}: title / H1')
        check(c['address'] in soup.get_text(), f'{route}: source address')
        organization = next(x for x in graph if x['@type'] == 'EducationalOrganization')
        if c.get('addressPrecision') == 'neighborhood':
            check('streetAddress' not in organization['address'], f'{route}: approximate location exposed as street address')
            check('정확한 도로명 주소' in soup.get_text(), f'{route}: missing address limitation')
        else:
            check(organization['address']['streetAddress'] == c['address'], f'{route}: schema address')
        check('telephone' not in organization, f'{route}: common phone misattributed')
        policy = '서울' if c['region']['province'] == '서울' else '서울 외'
        check(soup.select_one('[data-fee-region]')['data-fee-region'] == policy, f'{route}: fee region')
        fees = [e.get_text(strip=True) for e in soup.select('.branch-fee-card dd')]
        check(fees == [f'{n:,}원' for amounts in FEES[policy].values() for n in amounts], f'{route}: fee values')
        actual_grades = [e.get_text(strip=True) for e in soup.select('.branch-grade-range')]
        ref = reference.get('centers', {}).get(c['id'], {})
        media = ref.get('primaryMedia')
        check(media is not None, f'{route}: missing primary media record')
        if media:
            figures = soup.select('.branch-primary-media figure')
            expected_kinds = ['body'] + (['map'] if media.get('map') else [])
            check(len(figures) == len(expected_kinds), f'{route}: primary image count')
            for figure, kind in zip(figures, expected_kinds):
                asset = media[kind]
                img = figure.find('img')
                label = '본문' if kind == 'body' else '지도'
                check('branch-' + kind + '-image' in figure.get('class', []), f'{route}: body/map image order')
                check(img is not None and img.get('src') == asset['src'] and img.get('alt') == c['displayName'] + ' ' + label, f'{route}: page-specific primary image alt/source')
                if img:
                    check(img.get('width') == str(asset['width']) and img.get('height') == str(asset['height']), f'{route}: primary image dimensions')
                    check(img.get('loading') == 'lazy' and not img.has_attr('hidden') and 'display:none' not in img.get('style', '').replace(' ', ''), f'{route}: primary image visibility/loading')
                    panel = asset.get('displayPanel')
                    if panel:
                        frame = img.find_parent(class_='branch-map-panel')
                        check(frame is not None and frame.get('style') == f"aspect-ratio:{asset['width']}/{panel['bottom'] - panel['top']}", f'{route}: map panel aspect ratio')
                        check(img.get('style') == f"transform:translateY(-{panel['top'] / asset['height'] * 100:.8f}%)", f'{route}: wrong combined-map panel')
                    else:
                        check(img.find_parent(class_='branch-map-panel') is None, f'{route}: unintended map clipping')
                if asset['src'] not in verified_assets:
                    image_path = ROOT / asset['src'].lstrip('/')
                    check(image_path.is_file() and hashlib.sha256(image_path.read_bytes()).hexdigest() == asset['sha256'], f'{route}: original image integrity')
                    verified_assets.add(asset['src'])
            policy = 'seoul6839.webp' if c['region']['province'] == '서울' else 'local6839.webp'
            check(media['body']['src'].endswith('/' + policy), f'{route}: body image regional fees')
            container = soup.select_one('.branch-primary-media')
            previous = container.find_previous_sibling() if container else None
            if previous is not None and previous.get('id') == 'neighborhood-pages':
                check({a['href'] for a in previous.select('a[href]')} == {p['path'] for p in c.get('_neighborhoodPages', [])}, f'{route}: child links match manifest')
                previous = previous.find_previous_sibling()
            following = container.find_next_sibling() if container else None
            check(previous is not None and previous.get('class') == ['branch-hero', 'branch-detail-hero'] and following is not None and following.get('class') == ['branch-toc'], f'{route}: primary media before TOC')
            primary_body_images += 1
            primary_map_images += bool(media.get('map'))
        check(actual_grades == [subject_summary(c, name, d, ref) for name, d in c['subjects'].items()], f'{route}: grade coverage')
        if ref.get('sourceUrl'):
            check(soup.select_one('.branch-editorial-intro').get_text() == branch_summary(c, ref), f'{route}: introduction parity')
            check(web.get('abstract') == branch_summary(c, ref), f'{route}: answer summary schema parity')
            check(web.get('about') == web.get('mainEntity') == {'@id': url(route) + '#center'}, f'{route}: center identity relationship')
            check(not re.search(r'전 학년|전학년|전체 학년|모든 학년|많은 학부모|완벽하게|걸어서|국·영·수|1:1', branch_summary(c, ref)), f'{route}: unchecked universal introduction claim')
            check(bool(soup.select('#learning .branch-learning-cards article')), f'{route}: missing learning explanation')
            check(len(soup.select('#learning-space img')) == len(ref['images']), f'{route}: missing source gallery')
            check(bool(soup.select('#consultation-guide .branch-process li')), f'{route}: missing consultation steps')
        faqs = next(x for x in graph if x['@type'] == 'FAQPage')['mainEntity']
        visible = soup.select('.branch-faq details')
        check(len(visible) == len(faqs), f'{route}: FAQ count')
        for el, data in zip(visible, faqs):
            check(el.summary.get_text() == data['name'] and el.p.get_text() == data['acceptedAnswer']['text'], f'{route}: FAQ parity')
        answers = {f['name']:f['acceptedAnswer']['text'] for f in faqs}
        check(course_answer(c, ref) in answers['어떤 과목과 학년을 상담할 수 있나요?'], f'{route}: FAQ course restrictions missing')
        if weekend_detail(c, ref):
            check(weekend_detail(c, ref) in answers['평일과 주말 수업은 어떻게 확인하나요?'], f'{route}: FAQ weekend detail missing')
        if ref.get('editorial'):
            ed = ref['editorial']
            check(soup.select_one('.branch-focus-copy').get_text() == ed['focusText'], f'{route}: editorial copy parity')
            check(answers.get(ed['consultationQuestion']) == ed['consultationAnswer'], f'{route}: tailored consultation FAQ parity')
        check(all('[' not in e.text and '모든' not in e.text for e in soup.select('.branch-school-list li')), f'{route}: unverified school mixed in')
    else:
        itemlist = next(x for x in graph if x['@type'] == 'ItemList')
        primary_links = soup.select('.branch-region-link') if route == '/지점안내/' else soup.select('.branch-center-card')
        check(itemlist['numberOfItems'] == len(primary_links), f'{route}: list count')

check(len(paths) == 1 + len({c['region']['province'] for c in centers}) + len(centers), 'Directory page count does not match sources')
check(len(alltitles) == len(set(alltitles)), 'Duplicate page titles')
check(len(alldescriptions) == len(set(alldescriptions)), 'Duplicate page descriptions')
check(not any(len(p.relative_to(ROOT).parts) > 4 for p in paths), 'Unexpected subject/grade descendant')
for removed in bundle['centers'] + reference.get('additionalCenters', []):
    if removed['id'] in EXCLUDED_CENTER_IDS:
        check(not (ROOT / branch_path(removed).strip('/') / 'index.html').exists(), 'Removed branch page regenerated')
nav_only = 0
# Keep the historical Git baseline intact. The later, explicitly reviewed
# 54-page scope reconciliation is replayed on the old text, never applied to
# the actual text to hide discrepancies. The independent edition-2 audit also
# checks these exact changes without importing this postprocessor.
scope_targets = {t['path'].strip('/') + '/index.html': t for t in target_pages()}
scope_reconciled = 0
tracked = subprocess.check_output(['git', 'ls-files', '-z', '--', '*.html'], cwd=ROOT).decode('utf-8').split('\0')
proc = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
addition = '<a href="/지점안내/">지점안내</a>'
for rel in filter(None, tracked):
    proc.stdin.write(('HEAD:' + rel + '\n').encode('utf-8'))
    proc.stdin.flush()
    header = proc.stdout.readline().decode('utf-8').strip()
    size = int(header.rsplit(' ', 1)[-1])
    before = proc.stdout.read(size).decode('utf-8').replace('\r\n', '\n')
    proc.stdout.read(1)
    after = (ROOT / rel).read_text(encoding='utf-8')
    expected_before = before
    if rel in scope_targets:
        expected_before, _ = transform_html(before, scope_targets[rel])
        scope_reconciled += 1
    if before != after or rel in scope_targets:
        nav_only += int(rel not in scope_targets)
        check(after.replace(addition, '') == expected_before,
              f'{rel}: change outside requested navigation and reviewed scope reconciliation')
proc.stdin.close()
proc.wait()
check(scope_reconciled == 54, 'Reviewed legacy scope coverage must be exactly 54 existing pages')
sitemap = ET.parse(ROOT / 'sitemap.xml')
locs = [el.text for el in sitemap.findall('.//{*}loc')]
check(len(locs) == len(set(locs)), 'Duplicate sitemap URLs')
check(not any('글로리드' in unquote(loc) for loc in locs), 'Removed Glorid page in sitemap')
check(not any(any(name in unquote(loc) for name in ('(W+)', '대구역점2호관', '주엽2호점')) for loc in locs), 'Removed branch in sitemap')
for p in paths:
    check(url('/' + p.relative_to(ROOT).parent.as_posix() + '/') in locs, f'{p}: missing sitemap entry')
ET.parse(ROOT / 'rss.xml')
report = {'status': 'PASS' if not errors else 'FAIL', 'directoryPages': len(paths), 'centerPages': len(centers),
          'uniqueTitles': len(set(alltitles)), 'uniqueDescriptions': len(set(alldescriptions)), 'existingPagesNavigationOnly': nav_only, 'sitemapUrls': len(locs),
          'existingPagesScopeReconciled': scope_reconciled,
          'existingBaseline': 'Git HEAD retained; only original navigation and reviewed 54-page scope reconciliation replayed on expected text.',
          'neighborhoodIntroductions': neighborhood_introductions, 'centersWithoutNeighborhoodData': missing_neighborhood_centers, 'errors': errors}
report.update({'primaryBodyImages': primary_body_images, 'primaryMapImages': primary_map_images, 'verifiedPrimaryImageFiles': len(verified_assets), 'excludedGloridCenters': len(EXCLUDED_GLORID_IDS), 'excludedWplusCenters': len(EXCLUDED_WPLUS_IDS), 'excludedCentersTotal': len(EXCLUDED_CENTER_IDS)})
REPORTS.mkdir(parents=True, exist_ok=True)
(REPORTS / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(bool(errors))
