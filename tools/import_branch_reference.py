"""Reconcile the requested public branch reference with immutable owner workbooks.

Network collection is separate. This importer consumes the reviewed crawl and
matching manifests, never copies scripts/forms, and never publishes the site.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

from generate_branch_pages import DATA, ROOT, REPORTS, write_changed


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, data):
    write_changed(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def clean(value):
    text = re.sub(r'[\U0001f000-\U0001ffff\u2600-\u27ff\ufe0f]', '', value or '')
    return re.sub(r'\s+', ' ', text).strip()


def sections(ref, kind):
    return [s for s in ref['sections'] if s['kind'] == kind]


def public_operations(operations):
    result = deepcopy(operations)
    for name, row in result.get('subjectDisplay', {}).items():
        status = row.get('status')
        if status == 'unrecorded':
            row['detail'] = ''
        elif status == 'note_only_scope':
            row['detail'] = '구체적인 시작 학년과 가능한 과정은 상담 시 확인해 주세요.'
        elif status == 'not_offered_in_source':
            row['summary'], row['detail'] = '현재 수업 미운영 안내', ''
        elif status in {'conflicting_source', 'scope_confirmation_needed'}:
            row['summary'] = '개설 범위 확인 필요'
            row['detail'] = '과목별 학년 범위와 운영 안내가 서로 달라 확정 안내가 어렵습니다. 희망 학년과 과정을 말씀해 주시면 현재 수업 가능 여부를 확인할 수 있습니다.'
        else:
            row['detail'] = re.sub(r'^' + re.escape(name) + r'\s+', '', row.get('detail', ''))
            row['detail'] = re.sub(r'^' + re.escape(name) + r'\s+', '', row['detail'])
    weekend = result.get('weekend', {})
    status = weekend.get('status')
    if status == 'conflicting_source':
        weekend['summary'] = '주말 수업 여부 확인 필요'
        weekend['detail'] = '주말 정규수업·보강 일정의 안내가 서로 달라 현재 시간표를 확인해야 합니다. 희망 요일과 과목을 상담 시 알려주세요.'
    elif status in {'exception_only', 'exception_scope_confirmation_needed'}:
        weekend['summary'] = '주말 정규수업과 별도 프로그램 구분 확인'
        weekend['detail'] = '주말 보강·특강·자율학습은 정규수업과 별도로 운영될 수 있습니다. 진행 여부와 대상 과목, 날짜를 방문 전에 확인해 주세요.'
    return result


def parse_grades(text):
    sequence = [f'{p}{n}' for p, count in [('초', 6), ('중', 3), ('고', 3)] for n in range(1, count + 1)]
    parts = re.findall(r'[초중고][1-6]', text)
    if len(parts) == 2 and re.search(r'[~～–-]', text) and all(p in sequence for p in parts):
        return sequence[sequence.index(parts[0]):sequence.index(parts[1]) + 1]
    return [x for x in sequence if x in parts]


def additional_center(ref):
    """A public neighborhood location must not become an invented street address."""
    name = ref['branchName']
    district = ref['district'] or ''
    source_subjects = {}
    for sec in sections(ref, 'subject-grades'):
        for table in sec['tables']:
            for row in table['rows']:
                if len(row) > 1 and row[0] in ('국어', '영어', '수학', '과학', '사회'):
                    source_subjects[row[0]] = parse_grades(row[1])
    subjects = {name: {'grades': source_subjects.get(name, []), 'schoolLevels': [label for prefix, label in [('초', '초등'), ('중', '중등'), ('고', '고등')] if any(g.startswith(prefix) for g in source_subjects.get(name, []))], 'sourceCell': None, 'emptyMeaning': 'reference-unrecorded'} for name in ('국어', '영어', '수학', '과학', '사회')}
    start = ref.get('basicInfo', {}).get('수업 시작', '')
    parts = start.split('·')
    weekday = clean(parts[0]) if parts else ''
    weekend = clean(' · '.join(parts[1:])) if len(parts) > 1 else ''
    ops = {'averageWeekdayOpening': {'values': [weekday] if weekday else []}, 'weekendAvailability': {'values': [weekend] if weekend else []}, 'weekendScheduleAndSubjects': {'values': []}, 'subjectConditions': {'values': []}}
    return {'id': 'reference-' + ref['region'] + '-' + ref['sourceSlug'], 'source': {'website': ref['sourceUrl'], 'sourceSnapshotSha256': ref['sourceMeta']['sha256']},
            'sourceCenterName': name, 'branchName': name, 'branchSlug': ref['sourceSlug'], 'routeSlug': ref['sourceSlug'], 'sourceMarkers': [],
            'brandName': '와와학습코칭학원', 'displayName': '와와학습코칭학원 ' + name, 'registeredAcademyName': ref.get('legalName') or '',
            'registrationNumber': ref.get('registrationNumber') or '', 'registeredOpeningDateText': '',
            'address': ref.get('address') or ref['region'] + ' ' + district, 'addressPrecision': 'neighborhood',
            'region': {'province': ref['region'], 'district': district.split()[0] if district else '', 'subdistrict': ' '.join(district.split()[1:]), 'administrativeAreaText': district},
            'locationGuide': '', 'publicTelephone': None, 'subjects': subjects, 'availableSubjects': [name for name, d in subjects.items() if d['grades']],
            'schoolLevels': list(dict.fromkeys(level for d in subjects.values() for level in d['schoolLevels'])), 'publicOperations': ops}


def project_reference(c, ref, operations, assets, decisions):
    operations = public_operations(operations)
    source_name = ref.get('branchName') or c['sourceCenterName']
    result = {'sourceUrl': ref['sourceUrl'], 'sourceSnapshotSha256': ref['sourceMeta']['sha256'], 'operations': operations,
              'intro': '', 'locationParagraphs': [], 'learningCards': [], 'strengths': [], 'images': [], 'curriculum': [], 'apartments': [], 'commuteParagraphs': [], 'consultationSteps': [], 'checklist': [], 'referenceGeo': ref.get('geo')}
    if ref.get('intro'):
        result['intro'] = clean(ref['intro'][-1]).replace(source_name, c['sourceCenterName'])
        result['intro'] = result['intro'].replace('찾아요 무리한', '찾아요. 무리한')
    if not result['intro']:
        result['intro'] = c['sourceCenterName'] + '의 학습코칭과 수업·방문 정보를 함께 살펴보세요.'
    for sec in sections(ref, 'location-intro'):
        for value in sec['paragraphs']:
            text = clean(value).replace(source_name, c['sourceCenterName'])
            if '가까이에 있어서' in text:
                text = text.split('가까이에 있어서')[0].strip() + '에 있습니다.'
                text = text.replace('인근에 있습니다.', '인근에 있습니다.')
            if text:
                if not re.search(r'[.!?]$', text):
                    text = '주변 위치 참고: ' + text + '.'
                result['locationParagraphs'].append(text)
    for sec in sections(ref, 'learning-management'):
        for card in sec['cards']:
            if card['title']:
                text = clean(' '.join(card.get('paragraphs', [])))
                title = clean(card['title'])
                # Share the source's coaching approach without unsupported daily guarantees.
                if '계획' in title:
                    title, text = '현재 수준에 맞춘 계획', '학년과 과목, 현재 이해도를 함께 살피고 학생이 실행할 수 있는 학습 계획을 세웁니다.'
                elif '이해' in title:
                    title, text = '개념부터 적용까지', '설명을 듣는 데서 멈추지 않고 개념을 이해했는지, 문제에 적용할 수 있는지 단계별로 확인합니다.'
                elif '알려' in title or '공유' in title:
                    title, text = '학습 기록으로 소통', '진도와 이해도, 수업 참여와 과제 상태를 함께 기록하며 다음 학습 계획을 조정합니다.'
                result['learningCards'].append({'title': title, 'text': text})
    risky_claim = re.compile(r'성적|등급|합격|[0-9]+\s*년|다수|최고|상위|보장|경력|학벌|만족도|이직|매출|재등록|전공|졸업|출신|경시|입상|[0-9]+\s*명|직접 꼽|확실한|입증|재원|높은 신뢰|압도|우수')
    for sec in sections(ref, 'source-claims'):
        for li in sec['lists']:
            for value in li['items']:
                text = clean(value)
                if risky_claim.search(text):
                    decisions.append({'centerId': c['id'], 'sourceUrl': ref['sourceUrl'], 'field': 'strengths', 'sourceText': text, 'decision': 'held-unverified-results-or-dated-claims'})
                elif text:
                    result['strengths'].append(text)
    for sec in sections(ref, 'gallery'):
        for img in sec['images']:
            asset = assets.get(img['url'])
            if not asset:
                raise ValueError('Missing observed gallery asset: ' + img['url'])
            result['images'].append({k: asset[k] for k in ('sourceUrl', 'localSrc', 'width', 'height', 'sha256')})
    for sec in sections(ref, 'schools'):
        for table in sec['tables']:
            if table['headers'][:4] != ['과목', '초등', '중등', '고등']:
                continue
            for row in table['rows']:
                if len(row) < 4 or row[0] not in c['subjects']:
                    continue
                subject = row[0]
                status = operations.get('subjectDisplay', {}).get(subject, {}).get('status')
                if status in {'conflicting_source', 'not_offered_in_source', 'scope_confirmation_needed'}:
                    continue
                grades = c['subjects'][subject]['grades']
                levels = {level: clean(text) for prefix, level, text in zip(('초','중','고'), ('초등','중등','고등'), row[1:4]) if any(g.startswith(prefix) for g in grades)}
                if levels:
                    result['curriculum'].append({'subject': subject, 'levels': levels})
    apartments = []
    for sec in sections(ref, 'apartments'):
        for link in sec['links']:
            if '/apt/' not in link.get('url', ''):
                continue
            text = re.sub(r'\s*학원(?:\s*[·|].*)?$', '', clean(link['text']))
            if not text or any(t in text for t in ('주거단지', '신축단지', '기존단지', 'LH단지')) or text in {'주공', '아파트', '주변 단지', '대단지', '주택가'}:
                decisions.append({'centerId': c['id'], 'field': 'apartments', 'sourceText': text, 'decision': 'held-nonspecific-place-name'})
                continue
            apartments.append(text)
    result['apartments'] = list(dict.fromkeys(apartments))
    for sec in sections(ref, 'consultation-process'):
        for table in sec['tables']:
            if table['headers'] != ['단계', '내용']:
                continue
            for row in table['rows']:
                if len(row) < 2:
                    continue
                title, separator, text = row[1].partition('—')
                text = clean(text)
                if not separator:
                    continue
                if '진단' in title:
                    text = '과목별 이해도와 공부 습관을 살피고, 이미 알고 있는 내용과 보완할 내용을 나눕니다. 진단 방식과 소요 시간은 상담 시 안내받으세요.'
                elif '시작' in title:
                    text = '학습 기록과 수업 적응 상황을 바탕으로 계획을 조정합니다. 기록 공유 방식과 주기도 함께 확인해 주세요.'
                result['consultationSteps'].append({'title': clean(title), 'text': text})
    if result['consultationSteps']:
        result['checklist'] = ['집·학교에서 지점까지 실제 등하원 경로가 안전한지 확인해 주세요.', '학교 시험 범위와 사용하는 교재, 어려운 단원을 상담에서 함께 살펴보세요.', '학습 기록을 공유하는 방식과 주기를 확인해 주세요.', '희망 과목·횟수에 적용되는 교육비와 교재 등 별도 비용을 확인해 주세요.', '하교 시간과 평일·주말의 실제 가능 시간표가 맞는지 확인해 주세요.']
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-dir', required=True, type=Path)
    parser.add_argument('--mapping', required=True, type=Path)
    args = parser.parse_args()
    work = args.source_dir
    index = read(work / 'details-index.json')
    assert index['completed'] == index['expected'] == 205, 'Refuse a partial crawl'
    refs = {x['sourceUrl']: read(x['jsonPath']) for x in index['branches']}
    assert len(refs) == 205 and all(x['isVerifiedCenter'] for x in refs.values())
    original = read(DATA / 'centers.json')['centers']
    center_by_id = {c['id']: c for c in original}
    operations = read(work / 'display-overrides.json')['displayOverrides']
    mapping = read(args.mapping)
    media = read(work / 'asset-manifest.json')
    assets = {}
    for asset in media['assets']:
        source = Path(asset['localFile'])
        target = ROOT / 'assets' / 'branches' / 'reference' / (asset['sha256'][:20] + source.suffix.lower())
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == asset['sha256']
        assets[asset['sourceUrl']] = {**asset, 'localSrc': '/' + target.relative_to(ROOT).as_posix()}
    result = {'schemaVersion': 1, 'sourceRoot': 'https://wa-wacenter.com/branches/', 'policy': {'fees': 'owner-supplied-Seoul-and-non-Seoul', 'contact': '010-6839-8283', 'deployment': 'local-only', 'maximumDepth': 'center'}, 'centers': {}, 'regions': {}, 'additionalCenters': [], 'schoolMatches': {}}
    decisions = []
    for item in mapping['matches']:
        c = center_by_id[item['centerId']]
        ref = refs[item['sourceUrl']]
        result['centers'][c['id']] = project_reference(c, ref, operations.get(c['id'], {}), assets, decisions)
    for item in mapping.get('contentOnlyMatches', []):
        c = center_by_id[item['centerId']]
        projected = project_reference(c, refs[item['sourceUrl']], operations.get(c['id'], {}), assets, decisions)
        for key in ('locationParagraphs', 'apartments', 'commuteParagraphs', 'curriculum', 'strengths'):
            projected[key] = []
        projected['referenceGeo'] = None
        projected['importStatus'] = 'editorial-only-registration-conflict'
        result['centers'][c['id']] = projected
    for item in mapping['additional']:
        source_url = item if isinstance(item, str) else item['sourceUrl']
        ref = refs[source_url]
        c = additional_center(ref)
        result['additionalCenters'].append(c)
        result['centers'][c['id']] = project_reference(c, ref, {}, assets, decisions)
    # Preserve workbook records even if a future source removes a branch.
    for c in original:
        if c['id'] not in result['centers']:
            result['centers'][c['id']] = {'operations': operations.get(c['id'], {}), 'importStatus': 'no-safe-reference-match'}
    schoolfile = work / 'reference-school-merge.json'
    if schoolfile.exists():
        result['schoolMatches'] = read(schoolfile)['schoolMatches']
    editorial = work / 'curated-strengths.json'
    if editorial.exists():
        curated = read(editorial)['centers']
        assert set(result['centers']) == set(curated), 'Incomplete branch editorial review'
        for cid, item in curated.items():
            result['centers'][cid]['strengths'] = item['strengths']
            decisions.extend({'centerId': cid, 'field': 'strengths-editorial', 'decision': 'held-or-rephrased', 'detail': held} for held in item.get('held', []))
    intros_file = work / 'curated-intros.json'
    if intros_file.exists():
        intros = read(intros_file)['centers']
        assert set(result['centers']) == set(intros), 'Incomplete branch introduction review'
        for cid, item in intros.items():
            assert item['intro'].strip(), f'Empty branch introduction: {cid}'
            result['centers'][cid]['intro'] = item['intro']
            decisions.append({'centerId': cid, 'field': 'intro-editorial', 'decision': 'source-theme-with-owner-fact-boundaries', 'detail': item})
    full_reference = read(work / 'reference-content.json')
    for ref in full_reference['regions']:
        region = ref['region'] or ref['sourceSlug']
        stub = {'id': 'region-' + region, 'sourceCenterName': region, 'subjects': {}}
        result['regions'][region] = project_reference(stub, ref, {}, assets, decisions)
        result['regions'][region]['schoolLevelCards'] = [{'title': clean(card['title']), 'text': clean(' '.join(card['paragraphs']))} for sec in ref['sections'] if '초·중·고' in sec['heading'] for card in sec['cards'] if card['title']]
    save(DATA / 'reference-content.json', result)
    save(DATA / 'reference-import-decisions.json', {'mapping': mapping, 'decisions': decisions, 'policy': result['policy']})
    save(DATA / 'reference-asset-manifest.json', {'assets': list(assets.values())})
    # Keep a reproducible text snapshot; executable HTML and source form endpoints stay out.
    keep = ['sourceUrl', 'sourceMeta', 'region', 'branchName', 'sourceSlug', 'district', 'title', 'intro', 'address', 'addressPrecision', 'registrationNumber', 'basicInfo', 'geo']
    snapshot = []
    for ref in refs.values():
        row = {k: ref.get(k) for k in keep}
        row['sections'] = [{k: s.get(k) for k in ('kind','heading','paragraphs','subheadings','cards','lists','tables','faq','images','links')} for s in ref['sections']]
        snapshot.append(row)
    snapshot_bytes = json.dumps({'sources': snapshot, 'regions': read(work / 'branch-index.json')['regions']}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    packed_snapshot = DATA / 'reference-source-snapshot.json.gz'
    compressed = gzip.compress(snapshot_bytes, compresslevel=9, mtime=0)
    if not packed_snapshot.exists() or packed_snapshot.read_bytes() != compressed:
        packed_snapshot.write_bytes(compressed)
    report = {'sourceCenterPages': len(refs), 'matchedExistingCenters': len(mapping['matches']), 'editorialOnlyCenters': len(mapping.get('contentOnlyMatches', [])), 'addedCenters': len(result['additionalCenters']),
              'localCenterPages': len(original) + len(result['additionalCenters']), 'galleryAssets': len(assets), 'heldClaimsAndPlaceNames': len(decisions),
              'moduleCounts': {key: sum(bool(r.get(key)) for r in result['centers'].values()) for key in ('sourceUrl','images','learningCards','strengths','curriculum','apartments','consultationSteps')},
              'unresolved': mapping.get('unresolved', []), 'feesUnchanged': True, 'sourceFormsScriptsTrackersCopied': False, 'deployment': 'NOT DEPLOYED'}
    save(REPORTS / 'reference-import.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
