"""Import matched or explicitly owner-selected original images without editing pixels."""
import argparse
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

from PIL import Image
from generate_branch_pages import ROOT, DATA, REPORTS, EXCLUDED_CENTER_IDS, EXCLUDED_GLORID_IDS, EXCLUDED_WPLUS_IDS, load_branch_data, write_changed

COMMON = ROOT.parent / '참고자료' / '공통자료'
SOURCE_CSV = COMMON / '센터정보 정리.csv'
SOURCE_IMAGES = COMMON / '이미지'
SUPPLEMENT_IMAGES = Path('C:/Users/1992k/Desktop/WAWA 지도 모음 및 주소')
SUPPLEMENT_MANIFEST = DATA / 'supplemental-map-review.json'
OWNER_ATTACHMENTS = DATA / 'map-attachments'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(value):
    return re.sub(r'\s+', '', value)


def asset(source, destination, source_root=SOURCE_IMAGES):
    source = source.resolve(strict=True)
    assert source.is_relative_to(source_root.resolve()), 'Image outside supplied folder'
    destination = destination.resolve()
    assert destination.is_relative_to((ROOT / 'assets').resolve()), 'Asset outside site'
    sha = digest(source)
    if destination.exists():
        assert digest(destination) == sha, 'Do not overwrite a different existing asset'
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    with Image.open(destination) as img:
        width, height = img.size
    return {'src': '/' + destination.relative_to(ROOT).as_posix(), 'width': width,
            'height': height, 'sha256': sha, 'sourcePath': str(source)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mapping', required=True, type=Path)
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text(encoding='utf-8'))
    _, centers, _ = load_branch_data()
    matches = {m['centerId']: m for m in mapping['matches'] if m['centerId'] not in EXCLUDED_CENTER_IDS}
    unresolved = {m['centerId']: m for m in mapping['unresolved'] if m['centerId'] not in EXCLUDED_CENTER_IDS}
    assert not (matches.keys() & unresolved.keys())
    assert matches.keys() | unresolved.keys() == {c['id'] for c in centers}
    supplement = json.loads(SUPPLEMENT_MANIFEST.read_text(encoding='utf-8')) if SUPPLEMENT_MANIFEST.exists() else {'matches': []}
    supplemental = {m['centerId']: m for m in supplement['matches']}
    assert len(supplemental) == len(supplement['matches']), 'Duplicate supplemental center'
    supplemental = {cid: match for cid, match in supplemental.items() if cid not in EXCLUDED_CENTER_IDS}
    assert supplemental.keys() <= unresolved.keys(), 'Do not replace previously confirmed maps'
    with SOURCE_CSV.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    result = {'sourceCsv': str(SOURCE_CSV), 'sourceCsvSha256': digest(SOURCE_CSV),
              'policy': 'Original supplied images; distinguish matched maps from explicit owner selections; preserve page facts',
              'centers': {}}
    bodies = {name: asset(SOURCE_IMAGES / '본문이미지' / name, ROOT / 'assets/centers/common' / name)
              for name in ('seoul6839.webp', 'local6839.webp')}
    for c in centers:
        name = 'seoul6839.webp' if c['region']['province'] == '서울' else 'local6839.webp'
        record = {'body': bodies[name], 'map': None}
        if c['id'] in matches:
            match = matches[c['id']]
            assert compact(c['address']) == compact(match['csvAddress'])
            row = rows[match['csvRow'] - 2]
            assert row['센터명'] == match['csvCenterName'] and row['센터 주소'] == match['csvAddress']
            assert row['교육지원청 등록번호'] == match['csvRegistrationNumber']
            assert match['registrationNumberMatches'] and match['provinceCompatible']
            source = Path(match['sourceMapPath'])
            assert digest(source) == match['sourceMapSha256']
            existing = ROOT / 'assets/maps' / source.name
            destination = existing if existing.exists() and digest(existing) == match['sourceMapSha256'] else ROOT / 'assets/branches/maps' / (match['sourceMapSha256'][:24] + source.suffix.lower())
            record['map'] = asset(source, destination)
            assert (record['map']['width'], record['map']['height']) == (match['width'], match['height'])
            record['mapMatch'] = match
        elif c['id'] in supplemental:
            match = supplemental[c['id']]
            assert match['reviewStatus'] in {'confirmed', 'owner-selected'} and match['evidence']
            if match['reviewStatus'] == 'owner-selected':
                assert match.get('ownerInstruction') and match.get('originalAttachmentPath')
            assert c['sourceCenterName'] == match['centerName']
            assert compact(c['address']) == compact(match['centerAddress']), 'Recheck map after address changes'
            assert c['registrationNumber'] == match['centerRegistrationNumber']
            source_root = OWNER_ATTACHMENTS if match.get('sourceCollection') == 'owner-attachments' else SUPPLEMENT_IMAGES
            source = (source_root / match['sourceRelativePath']).resolve(strict=True)
            assert source.is_relative_to(source_root.resolve()), 'Map outside supplemental folder'
            assert digest(source) == match['sourceMapSha256'], 'Recheck altered source map'
            destination = ROOT / 'assets/branches/maps' / (match['sourceMapSha256'][:24] + source.suffix.lower())
            record['map'] = asset(source, destination, source_root)
            if match.get('displayPanel'):
                panel = match['displayPanel']
                assert 0 <= panel['top'] < panel['bottom'] <= record['map']['height']
                record['map']['displayPanel'] = panel
            record['mapMatch'] = {'sourceType': 'owner-supplied-supplement', **match}
        else:
            record['mapOmission'] = dict(unresolved[c['id']])
            note = supplement.get('remainingReviewNotes', {}).get(c['id'])
            if note:
                record['mapOmission']['supplementalReview'] = note
        result['centers'][c['id']] = record
    if supplemental:
        result['supplementalSource'] = str(SUPPLEMENT_IMAGES)
        result['supplementalReviewSha256'] = digest(SUPPLEMENT_MANIFEST)
    write_changed(DATA / 'branch-media.json', json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    remaining = [r['mapOmission'] for r in result['centers'].values() if not r['map']]
    report = {'centerPages': len(centers), 'bodyImages': len(centers), 'mapImages': len(matches) + len(supplemental),
              'supplementalMapsAdded': len(supplemental),
              'supplementalCenters': [m['centerName'] for m in supplemental.values()],
              'mapsOmittedWithApproval': len(remaining), 'excludedGloridPages': len(EXCLUDED_GLORID_IDS),
              'excludedWplusPages': len(EXCLUDED_WPLUS_IDS), 'excludedCenterPages': len(EXCLUDED_CENTER_IDS),
              'ownerSelectedMaps': [m['centerName'] for m in supplemental.values() if m['reviewStatus'] == 'owner-selected'],
              'sourcePixelsChanged': False, 'deployment': 'NOT DEPLOYED',
              'unresolved': remaining}
    write_changed(REPORTS / 'primary-media.json', json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'unresolved'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
