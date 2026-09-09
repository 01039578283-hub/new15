"""Scoped legacy course-scope reconciliation; never deploy or rewrite manuscripts.

Run this postprocessor after the existing subject-page generator. The source
generator remains unchanged, so a later generation must be followed by this
postprocessor again. Only the 54 reviewed legacy pages may be changed; no
reverse links are added. --snapshot records the current pre-improvement files.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from html import escape
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports/branch-neighborhoods'
BASELINE = REPORTS / 'improvement-baseline-2026-09-10.json.gz'
JSON_LD = re.compile(r'(<script\b[^>]*type="application/ld\+json"[^>]*>)(.*?)(</script>)', re.S)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def target_pages(root=ROOT):
    records = read_json(root / 'tools/data/branch-neighborhoods/pages.json')['pages']
    ref = read_json(root / 'tools/data/branches/reference-content.json')
    centers = read_json(root / 'tools/data/branches/centers.json')['centers'] + ref.get('additionalCenters', [])
    centers = {c['id']: c for c in centers}
    targets = []
    combinations = set()
    for record in records:
        scope = ref['centers'][record['centerId']].get('operations', {}).get('subjectDisplay', {}).get(record['subject'], {})
        if not scope or scope.get('includeInUnqualifiedAvailableSubjects') is not False:
            continue
        combinations.add((record['locality'], record['subject']))
        for level in ('초등학생', '중학생', '고등학생'):
            route = '/과목별학원/' + level + record['subject'] + '학원/' + record['locality'] + '/'
            targets.append({'path': route, 'centerId': record['centerId'], 'locality': record['locality'],
                            'subject': record['subject'], 'level': level, 'scope': scope,
                            'centerName': centers[record['centerId']]['sourceCenterName']})
    if len(combinations) != 18 or len(targets) != 54 or len({t['path'] for t in targets}) != 54:
        raise RuntimeError('Reviewed 18-combination / 54-page scope changed; review before proceeding')
    return targets


def public_scope(target):
    name, subject = target['centerName'], target['subject']
    if target['scope'].get('status') == 'note_only_scope':
        sentence = f'{name} {subject}는 기초 보완이 필요한 학생의 수업 가능 여부와 세부 학년을 상담에서 확인해야 합니다.'
    else:
        sentence = f'{name}의 {subject} 수업 개설 여부와 대상 학년은 상담에서 확인해야 합니다.'
    return target['scope']['summary'], sentence


def section_pattern(class_name):
    return re.compile(r'(<section\b[^>]*class="[^\"]*\b' + re.escape(class_name) + r'\b[^\"]*"[^>]*>)(.*?)(</section>)', re.S)


def transform_html(html, target):
    """Change only the agreed grade card, added notice, selected FAQ and schema."""
    from bs4 import BeautifulSoup

    scope_label, sentence = public_scope(target)
    changes = {'gradeCard': False, 'summaryNotice': False, 'faq': [], 'removedServices': 0,
               'removedEducationalLevel': False}
    grade_re = re.compile(r'(<div class="academy-fact-card"><strong>수업 가능 학년</strong><span>)(.*?)(</span></div>)', re.S)
    found = list(grade_re.finditer(html))
    if len(found) != 1:
        raise RuntimeError(target['path'] + ': expected exactly one grade card')
    changes['gradeCard'] = found[0].group(2) != escape(scope_label)
    html = grade_re.sub(lambda m: m.group(1) + escape(scope_label) + m.group(3), html)
    summary_re = section_pattern('academy-summary')
    if len(list(summary_re.finditer(html))) != 1:
        raise RuntimeError(target['path'] + ': summary block changed')
    notice = '<p class="academy-scope-confirmation">' + escape(sentence + ' 희망 학년과 현재 교재를 함께 알려 주세요.') + '</p>'

    def summary_update(match):
        inside = match.group(2)
        existing = re.search(r'<p class="academy-scope-confirmation">.*?</p>', inside, re.S)
        changes['summaryNotice'] = not existing or existing.group(0) != notice
        inside = (inside[:existing.start()] + notice + inside[existing.end():]) if existing else inside + notice
        return match.group(1) + inside + match.group(3)

    html = summary_re.sub(summary_update, html)
    faq_re = section_pattern('academy-faq')
    if len(list(faq_re.finditer(html))) != 1:
        raise RuntimeError(target['path'] + ': FAQ block changed')

    def faq_update(section):
        index = 0

        def detail_update(match):
            nonlocal index
            position = index
            index += 1
            soup = BeautifulSoup(match.group(0), 'html.parser')
            question, answer = soup.summary.get_text(), soup.p.get_text()
            new_question, new_answer = question, answer
            if target['subject'] == '영어' and target['level'] == '고등학생' and question == target['locality'] + ' 고1·고2·고3 수업은 모두 같나요?':
                new_question = target['locality'] + ' 고등학생 영어 상담에서는 학생별 학습 차이를 어떻게 확인하나요?'
                old_prefix = target['locality'] + ' 고등학생 영어학원에서는 '
                if not answer.startswith(old_prefix):
                    raise RuntimeError('High-school English FAQ wording changed; review before replacing')
                new_answer = sentence + ' ' + answer.removeprefix(old_prefix)
            elif target['subject'] == '수학' and target['level'] == '중학생' and answer.startswith('가능합니다. 다만 '):
                new_answer = sentence + ' ' + answer.removeprefix('가능합니다. 다만 ')
            if (new_question, new_answer) == (question, answer):
                return match.group(0)
            changes['faq'].append({'index': position, 'beforeQuestion': question, 'question': new_question,
                                   'beforeAnswer': answer, 'answer': new_answer})
            updated = re.sub(r'(<summary\b[^>]*>).*?(</summary>)', lambda m: m.group(1) + escape(new_question) + m.group(2), match.group(0), count=1, flags=re.S)
            return re.sub(r'(<p\b[^>]*>).*?(</p>)', lambda m: m.group(1) + escape(new_answer) + m.group(2), updated, count=1, flags=re.S)

        inside = re.sub(r'<details\b[^>]*>.*?</details>', detail_update, section.group(2), flags=re.S)
        if index != 4:
            raise RuntimeError(target['path'] + ': expected four existing FAQ entries')
        return section.group(1) + inside + section.group(3)

    html = faq_re.sub(faq_update, html)
    soup = BeautifulSoup(html, 'html.parser')
    visible_faq = [(node.summary.get_text(), node.p.get_text()) for node in soup.select('.academy-faq details')]
    matches = list(JSON_LD.finditer(html))
    if len(matches) != 1:
        raise RuntimeError(target['path'] + ': expected one JSON-LD graph')
    data = json.loads(matches[0].group(2))
    graph = data['@graph']
    removed_ids = {node['@id'] for node in graph if node.get('@type') == 'Service'}
    changes['removedServices'] = len(removed_ids)
    # The suffix is also rejected on reruns, so no dangling old reference survives.
    canonical = soup.select_one('link[rel="canonical"]')['href']
    removed_ids.add(canonical + '#service')
    graph = [node for node in graph if node.get('@type') != 'Service']
    for node in graph:
        if node.get('@type') == 'EducationalOrganization':
            changes['removedEducationalLevel'] = 'educationalLevel' in node
            node.pop('educationalLevel', None)
        if isinstance(node.get('about'), list):
            node['about'] = [item for item in node['about'] if item.get('@id') not in removed_ids]
        if node.get('@type') == 'WebPage':
            node['mainEntity'] = {'@id': canonical + '#article'}
        if node.get('@type') == 'FAQPage':
            node['mainEntity'] = [{'@type': 'Question', 'name': question,
                                  'acceptedAnswer': {'@type': 'Answer', 'text': answer}}
                                 for question, answer in visible_faq]
    data['@graph'] = graph
    serialized = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    if any(service_id in serialized for service_id in removed_ids):
        raise RuntimeError(target['path'] + ': an unexpected Service reference remains')
    html = JSON_LD.sub(lambda m: m.group(1) + serialized + m.group(3), html)
    return html, changes


def reconcile(apply=False, root=ROOT):
    targets = target_pages(root)
    result = {'mode': 'APPLY' if apply else 'DRY_RUN', 'targetPages': len(targets), 'changedPages': 0,
              'faqEntriesChanged': 0, 'reverseLinksAdded': 0, 'pages': []}
    planned = []
    for target in targets:
        path = root / target['path'].strip('/') / 'index.html'
        raw = path.read_bytes()
        before = raw.decode('utf-8')
        after, changes = transform_html(before, target)
        repeat, _ = transform_html(after, target)
        if repeat != after:
            raise RuntimeError(target['path'] + ': reconciliation is not idempotent')
        changed = before != after
        result['changedPages'] += changed
        result['faqEntriesChanged'] += len(changes['faq'])
        result['pages'].append({'path': target['path'], 'centerId': target['centerId'],
                                'scopeStatus': target['scope']['status'], 'beforeSha256': sha256(raw),
                                'afterSha256': sha256(after.encode('utf-8')), 'changed': changed, 'changes': changes})
        planned.append((path, after.encode('utf-8'), changed))
    # Plan and validate every target before the first site write.
    if apply:
        if not BASELINE.is_file():
            raise RuntimeError('Required pre-improvement baseline is missing')
        for path, raw, changed in planned:
            if changed:
                path.write_bytes(raw)
        output = root / 'reports/branch-neighborhoods/legacy-scope-reconciliation.json'
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def capture_baseline(destination=BASELINE):
    if destination.exists():
        raise RuntimeError('Refusing to overwrite an existing improvement baseline')
    pages = {}
    for top in ('지점안내', '과목별학원'):
        for path in sorted((ROOT / top).rglob('index.html')):
            raw = path.read_bytes()
            pages[path.relative_to(ROOT).as_posix()] = {
                'sha256': sha256(raw), 'bytes': len(raw), 'html': raw.decode('utf-8-sig')}
    sources = {}
    for path in sorted((ROOT / 'tools/data').rglob('*')):
        if path.is_file():
            raw = path.read_bytes()
            sources[path.relative_to(ROOT).as_posix()] = {'bytes': len(raw), 'sha256': sha256(raw)}
    assets = {}
    for path in sorted((ROOT / 'assets').rglob('*')):
        if path.is_file():
            raw = path.read_bytes()
            assets[path.relative_to(ROOT).as_posix()] = {'bytes': len(raw), 'sha256': sha256(raw)}
    payload = {'version': 1, 'createdAt': datetime.now(timezone.utc).isoformat(),
               'root': str(ROOT), 'pages': pages, 'sourceFiles': sources, 'assets': assets}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(destination, 'wt', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(',', ':'))
    return {'baseline': str(destination), 'pages': len(pages), 'sourceFiles': len(sources),
            'assets': len(assets), 'compressedBytes': destination.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', action='store_true')
    parser.add_argument('--apply', action='store_true', help='Apply the reviewed 54-page reconciliation after subject-page generation.')
    args = parser.parse_args()
    result = capture_baseline() if args.snapshot else reconcile(apply=args.apply)
    print(json.dumps({key: value for key, value in result.items() if key != 'pages'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
