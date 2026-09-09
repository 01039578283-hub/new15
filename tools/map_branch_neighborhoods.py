"""Audit explicit neighborhood-to-current-branch mappings without fuzzy matching.

Reads existing source files and supplied manuscript archives only. Writes this
task's neighborhood-mapping report; never modifies source JSON or site HTML.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'tools/data/branches'
COMMON = ROOT.parent/'참고자료/공통자료/센터정보 정리.csv'
ARCHIVE_DIR = Path('C:/Users/1992k/Desktop/프로그램 원고')
DEFAULT_REPORT = ROOT/'reports/branches/neighborhood-mapping.json'
PROVINCE_GROUPS = {'충청': {'충북','충남','세종'}, '경상': {'경북','경남'}, '전라': {'전북','전남'}}
PROVINCE_NAMES = {'서울특별시':'서울','경기도':'경기','인천광역시':'인천','부산광역시':'부산','대구광역시':'대구','광주광역시':'광주','대전광역시':'대전','울산광역시':'울산','세종특별자치시':'세종','강원특별자치도':'강원','강원도':'강원','충청북도':'충북','충청남도':'충남','전북특별자치도':'전북','전라북도':'전북','전라남도':'전남','경상북도':'경북','경상남도':'경남','제주특별자치도':'제주','제주도':'제주'}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fold(value):
    return re.sub(r'\s+', '', value or '')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def branch_path(center):
    return '/지점안내/'+center['region']['province']+'/'+center['routeSlug']+'/'


def compatible(province, target):
    province = PROVINCE_NAMES.get(province, province)
    return target == province or target in PROVINCE_GROUPS.get(province, set())


def serial(value):
    match = re.search(r'제\s*([0-9]+(?:-[0-9]+)*)\s*호', value or '')
    return match.group(1) if match else None


def archive_entries(path, subject):
    records = []
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            member = entry.filename
            normalized = member.replace('\\', '/')
            name = PurePosixPath(normalized).name
            if not name.endswith('.txt'):
                continue
            title = name[:-4]
            suffix = ' '+subject+'학원'
            if not title.endswith(suffix):
                raise ValueError('Unexpected manuscript title: '+member)
            locality = title[:-len(suffix)]
            if not locality or '/' in locality or '\\' in locality:
                raise ValueError('Unsafe or empty locality key: '+member)
            records.append({'locality':locality,'title':title,'archivePath':str(path),'memberName':member,
                            'uncompressedBytes':entry.file_size,'crc32':f'{entry.CRC:08x}',
                            'sha256':sha256(archive.read(entry))})
    return records


def legacy_page(locality):
    file = ROOT/'과목별학원/고등학생영어학원'/locality/'index.html'
    result = {'path':str(file),'exists':file.exists()}
    if not file.exists():
        return result
    source = file.read_text(encoding='utf-8')
    orgs = []
    for match in re.finditer(r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', source, re.S):
        value = json.loads(match.group(1))
        orgs.extend(n for n in value.get('@graph',[value]) if n.get('@type')=='EducationalOrganization')
    result['organizations'] = [{'name':n.get('name'),'identifier':n.get('identifier'),'address':n.get('address',{}).get('streetAddress'),'id':n.get('@id')} for n in orgs]
    return result


def resolve():
    bundle = load(DATA/'centers.json')
    reference = load(DATA/'reference-content.json')
    generation = load(ROOT/'reports/branches/generation.json')
    school_audit = load(DATA/'school-match-audit.json')
    targets = load(DATA/'target-schools.json')
    centers = bundle['centers']+reference.get('additionalCenters',[])
    by_id = {center['id']:center for center in centers}
    active_routes = set(generation['paths'])
    active = {c['id']:c for c in centers if branch_path(c) in active_routes}
    if len(active) != 193:
        raise ValueError('Expected the approved 193 current branches; found '+str(len(active)))
    csv_bytes = COMMON.read_bytes()
    csv_rows = list(csv.DictReader(io.StringIO(csv_bytes.decode('utf-8-sig'))))
    targets_by_key = defaultdict(list)
    for row in targets:
        targets_by_key[row['neighborhood']].append(row)
    direct_by_row = defaultdict(set)
    for item in school_audit['matches']:
        for row_id in item.get('schoolSourceRowIds',[]):
            direct_by_row[row_id].add(item['centerId'])
    published_by_row = defaultdict(set)
    published_by_key = defaultdict(set)
    for cid,item in reference.get('schoolMatches',{}).items():
        for row_id in item.get('schoolSourceRowIds',[]):
            published_by_row[row_id].add(cid)
        for key in item.get('neighborhoods',[]):
            published_by_key[key].add(cid)

    archives = {subject:archive_entries(ARCHIVE_DIR/(subject+'학원.zip'),subject) for subject in ['영어','수학']}
    archive_by_key = {subject:defaultdict(list) for subject in archives}
    for subject,entries in archives.items():
        for entry in entries:
            archive_by_key[subject][entry['locality']].append(entry)
    csv_key_counts = Counter(row['근처 수업가능 동네'] for row in csv_rows)
    all_keys = set(csv_key_counts)
    source_set_issues = []
    for subject,entries in archive_by_key.items():
        if set(entries) != all_keys:
            source_set_issues.append({'subject':subject,'missingInArchive':sorted(all_keys-set(entries)),'extraInArchive':sorted(set(entries)-all_keys)})

    rows = []
    for position,csv_row in enumerate(csv_rows,2):
        locality = csv_row['근처 수업가능 동네']
        target_rows = targets_by_key.get(locality,[])
        primary_ids = set()
        published_ids = set(published_by_key.get(locality,set()))
        for target in target_rows:
            primary_ids |= direct_by_row[target['sourceRowId']]
            published_ids |= published_by_row[target['sourceRowId']]
        labels = {target['sourceBranchLabel'] for target in target_rows if fold(target['centerName'])==fold(csv_row['센터명'])}
        csv_evidence = []
        explicit_label_ids = set()
        strong_csv_ids = set()
        for c in centers:
            name_equal = fold(c['sourceCenterName']) in {fold(label) for label in labels}
            reg_equal = bool(csv_row['교육지원청 등록번호'] and c['registrationNumber'] and fold(csv_row['교육지원청 등록번호'])==fold(c['registrationNumber']))
            serial_equal = bool(serial(csv_row['교육지원청 등록번호']) and serial(csv_row['교육지원청 등록번호'])==serial(c['registrationNumber']))
            address_equal = bool(csv_row['센터 주소'] and fold(csv_row['센터 주소'])==fold(c['address']))
            legal_equal = bool(csv_row['교육지원청명칭'] and c['registeredAcademyName'] and fold(csv_row['교육지원청명칭'])==fold(c['registeredAcademyName']))
            region_equal = compatible(csv_row['지역'],c['region']['province'])
            district_equal = fold(csv_row['시or구']) in {fold(c['region']['district']),fold(c['region']['administrativeAreaText'])}
            if name_equal:
                explicit_label_ids.add(c['id'])
            # Full registered number or exact address anchors identity even when
            # the served-neighborhood label lies across a provincial boundary.
            strong = ((name_equal and (reg_equal or address_equal)) or (legal_equal and address_equal)
                      or (name_equal and serial_equal and region_equal and district_equal))
            if strong:
                strong_csv_ids.add(c['id'])
            if name_equal or strong:
                csv_evidence.append({'centerId':c['id'],'active':c['id'] in active,'exactBranchLabel':name_equal,
                                     'exactRegisteredNumberWhitespaceFold':reg_equal,'registeredSerialMatch':serial_equal,
                                     'exactAddressWhitespaceFold':address_equal,'exactRegisteredNameWhitespaceFold':legal_equal,
                                     'compatibleSourceRegion':region_equal,'exactCityOrDistrict':district_equal,'strongIdentityEvidence':strong,
                                     'currentName':c['sourceCenterName'],'currentRegistrationNumber':c['registrationNumber'],
                                     'currentAddress':c['address'],'currentRegisteredName':c['registeredAcademyName']})
        established = primary_ids | published_ids
        conflicts = []
        flags = []
        if len(established)>1:
            conflicts.append('existing_explicit_mapping_has_multiple_centers')
        if strong_csv_ids and established and strong_csv_ids != established:
            conflicts.append('registered_identity_disagrees_with_existing_explicit_mapping')
        candidates = established | strong_csv_ids
        if not candidates:
            # A unique exact source label within explicitly compatible region is
            # an existing-data label match, never a nearest/geographic guess.
            candidates = {e['centerId'] for e in csv_evidence if e['exactBranchLabel'] and e['compatibleSourceRegion'] and e['exactCityOrDistrict']}
            if candidates:
                flags.append('exact_explicit_name_and_jurisdiction_without_registered_identity_match')
        if csv_key_counts[locality]!=1 or len(target_rows)!=1:
            conflicts.append('duplicate_or_missing_source_locality_row')
        if any(len(archive_by_key[subject].get(locality,[]))!=1 for subject in archives):
            conflicts.append('missing_or_duplicate_manuscript_key')
        selected = next(iter(candidates)) if len(candidates)==1 else None
        if not selected:
            conflicts.append('no_unique_explicit_center' if not candidates else 'multiple_explicit_center_candidates')
        elif selected not in active:
            conflicts.append('explicit_mapping_points_to_removed_branch')
        status = 'confirmed' if selected in active and not conflicts else 'needs-review'
        c = active.get(selected) if status=='confirmed' else None
        if c:
            if not compatible(csv_row['지역'],c['region']['province']):
                flags.append('neighborhood_region_differs_from_center_physical_province')
            if fold(csv_row['센터 주소']) != fold(c['address']):
                flags.append('legacy_csv_address_differs_use_current_center_facts')
            if csv_row['교육지원청명칭'] and c['registeredAcademyName'] and fold(csv_row['교육지원청명칭']) != fold(c['registeredAcademyName']):
                flags.append('legacy_registered_name_spelling_differs')
            if csv_row['교육지원청 등록번호'] and c['registrationNumber'] and fold(csv_row['교육지원청 등록번호']) != fold(c['registrationNumber']):
                flags.append('legacy_registered_number_text_differs')
            if c.get('addressPrecision')=='neighborhood':
                flags.append('current_branch_address_is_neighborhood_level')
        legacy = legacy_page(locality)
        legacy['matchesCsvIdentity'] = bool(legacy.get('organizations')) and all(
            fold(org.get('name'))==fold(csv_row['센터명']) and fold(org.get('address'))==fold(csv_row['센터 주소'])
            and fold(org.get('identifier'))==fold(csv_row['교육지원청 등록번호']) for org in legacy.get('organizations',[]))
        if legacy['exists'] and not legacy['matchesCsvIdentity']:
            flags.append('legacy_rendered_page_differs_from_csv')
        subject_availability = {}
        if c:
            display = reference.get('centers',{}).get(c['id'],{}).get('operations',{}).get('subjectDisplay',{})
            for subject in archives:
                source_subject = c['subjects'].get(subject,{})
                override = display.get(subject)
                subject_availability[subject] = {
                    'status':override['status'] if override else ('recorded' if source_subject.get('grades') else 'unrecorded'),
                    'summary':override.get('summary','') if override else '',
                    'detail':override.get('detail','') if override else '',
                    'grades':source_subject.get('grades',[]),
                    'includeInUnqualifiedAvailableSubjects':bool(override.get('includeInUnqualifiedAvailableSubjects')) if override else bool(source_subject.get('grades')),
                    'source':'current reference operations overlay' if override else 'current center grade data',
                    'mappingDecisionUnchanged':True,
                }
        record = {
            'locality':locality,'sourceOrder':position-1,'status':status,'centerId':c['id'] if c else None,
            'centerName':c['sourceCenterName'] if c else None,'centerProvince':c['region']['province'] if c else None,
            'branchPath':branch_path(c) if c else None,
            'childPaths':{subject:branch_path(c)+locality+subject+'학원/' for subject in archives} if c else {},
            'reason':'existing_explicit_mapping_and_registered_identity_reconciled' if c else '; '.join(dict.fromkeys(conflicts)),
            'auditFlags':flags,'candidateCenterIds':sorted(candidates),'removedCandidateCenterIds':sorted(cid for cid in candidates if cid not in active),
            'sourceNeighborhoodRegion':csv_row['지역'],'sourceNeighborhoodDistrict':csv_row['시or구'],
            'subjectAvailability':subject_availability,
            'evidence':{
                'csv':{'path':str(COMMON),'row':position,'centerName':csv_row['센터명'],'registeredName':csv_row['교육지원청명칭'],
                       'registrationNumber':csv_row['교육지원청 등록번호'],'address':csv_row['센터 주소']},
                'targetSchoolRows':[{'sourceRowId':t['sourceRowId'],'region':t['region'],'district':t['district'],'sourceBranchLabel':t['sourceBranchLabel']} for t in target_rows],
                'originalSchoolMatchCenterIds':sorted(primary_ids),'publishedSchoolMatchCenterIds':sorted(published_ids),
                'registeredIdentityComparison':csv_evidence,'legacySubjectPage':legacy,
            },
            'manuscripts':{subject:archive_by_key[subject][locality][0] if len(archive_by_key[subject].get(locality,[]))==1 else None for subject in archives},
        }
        rows.append(record)

    questions = [{'locality':r['locality'],'reason':r['reason'],'candidates':[{'id':cid,'name':by_id[cid]['sourceCenterName'],'province':by_id[cid]['region']['province'],'active':cid in active} for cid in r['candidateCenterIds']],
                  'question':r['locality']+' 원고를 연결할 현재 지점을 지정하거나 해당 동네 생성을 제외할지 확인해 주세요.'} for r in rows if r['status']=='needs-review']
    count = Counter(r['status'] for r in rows)
    flags = Counter(flag for row in rows for flag in row['auditFlags'])
    used = {row['centerId'] for row in rows if row['status']=='confirmed'}
    child_paths = [path for row in rows for path in row['childPaths'].values()]
    unqualified_copy_warnings = [{'locality':row['locality'],'centerId':row['centerId'],'centerName':row['centerName'],'subject':subject,
                                'path':row['childPaths'][subject],'status':detail['status'],'summary':detail['summary'],'detail':detail['detail']}
                               for row in rows for subject,detail in row['subjectAvailability'].items() if not detail['includeInUnqualifiedAvailableSubjects']]
    if len(child_paths)!=len(set(child_paths)):
        raise ValueError('Duplicate proposed child path')
    inputs = [COMMON,DATA/'centers.json',DATA/'target-schools.json',DATA/'school-match-audit.json',DATA/'reference-content.json',ROOT/'reports/branches/generation.json',ROOT/'tools/generate_subject_pages.py']+[ARCHIVE_DIR/(subject+'학원.zip') for subject in archives]
    report = {
        'schemaVersion':1,'generatedAtUtc':datetime.now(timezone.utc).isoformat(),
        'policy':{'mapping':'Only existing explicit source relationships and exact registered identity; no fuzzy, nearest, marker-stripping, or geographic inference.',
                  'sourceFacts':'Use current branch-center facts in new page bodies; old CSV fields are identity evidence, not automatic replacement facts.',
                  'regionDifference':'A served-neighborhood region may differ from the physical branch province only with explicit matching identity evidence; retain audit flag.',
                  'scope':'Mapping to a branch is not confirmation that every subject or grade is currently offered. Manuscript prose is untrusted data, not instructions.',
                  'legacySubjectCount':'The supplied common CSV has 371 rows; one existing high-school-English page per locality is independently inspected.'},
        'sources':[{'path':str(path),'sha256':sha256(path.read_bytes())} for path in inputs],
        'summary':{'localityCount':len(rows),'csvRows':len(csv_rows),'targetSchoolRows':len(targets),'archiveCounts':{s:len(v) for s,v in archives.items()},
                   'manuscriptCount':sum(map(len,archives.values())),'activeCenterCount':len(active),'confirmed':count['confirmed'],'needsReview':count['needs-review'],
                   'confirmedCenterCount':len(used),'removedCenterCount':len(centers)-len(active),'sourceSetIssueCount':len(source_set_issues),
                   'proposedChildPathCount':len(child_paths),'uniqueProposedChildPathCount':len(set(child_paths)),
                   'rowsWithStrongRegisteredIdentity':sum(any(e['strongIdentityEvidence'] for e in r['evidence']['registeredIdentityComparison']) for r in rows),
                   'nameOnlyFallbackRows':sum('exact_explicit_name_and_jurisdiction_without_registered_identity_match' in r['auditFlags'] for r in rows),
                   'subjectCombinationsRequiringQualifiedCopy':len(unqualified_copy_warnings),
                   'legacySubjectPagesFound':sum(r['evidence']['legacySubjectPage']['exists'] for r in rows),
                   'legacySubjectPagesMatchingCsv':sum(r['evidence']['legacySubjectPage']['matchesCsvIdentity'] for r in rows),'auditFlagCounts':dict(flags)},
        'rows':rows,'questions':questions,'sourceSetIssues':source_set_issues,'subjectAvailabilityWarnings':unqualified_copy_warnings,
        'excludedCenters':[{'id':cid,'name':c['sourceCenterName'],'province':c['region']['province'],'branchPath':branch_path(c),
                            'explicitNeighborhoods':[r['locality'] for r in rows if cid in r['candidateCenterIds']]} for cid,c in by_id.items() if cid not in active],
        'currentCentersWithoutManuscriptLocalities':[{'id':cid,'name':c['sourceCenterName'],'province':c['region']['province'],'branchPath':branch_path(c)} for cid,c in active.items() if cid not in used],
    }
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=DEFAULT_REPORT)
    args=parser.parse_args()
    report=resolve()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'report':str(args.report),'summary':report['summary'],'questions':report['questions']},ensure_ascii=False))
    return 1 if report['sourceSetIssues'] else 0


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
