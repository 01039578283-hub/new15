"""Reader-safe projections of reviewed facts; never edits sources or HTML.

The school names are owner-confirmed. Review annotations are retained separately,
not interpreted as authority to replace a name or as current school-status facts.
Related links fail closed when existing page identity does not match current data.
"""
from __future__ import annotations

from functools import lru_cache
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LEVELS = (('elementary', '초', '초등학생'), ('middle', '중', '중학생'), ('high', '고', '고등학생'))
CONFIRMED_STATUSES = {'recorded', 'recorded_with_conditions'}
REVIEW_ANNOTATION = re.compile(r'후보|확인\s*필요|미확인|\d{4}\s*통계.*(?:휴|폐)교')
GENERAL_NOTES = {
    '지역내모든고등학교가능': '고등학교별 상담 대상과 희망 과목·학년은 상담에서 확인해 주세요.',
    '모든고등학교가능': '고등학교별 상담 대상과 희망 과목·학년은 상담에서 확인해 주세요.',
    '기타사립초': '사립초등학교 관련 상담은 학교명·학년·희망 과목을 알려 주세요.',
    '특성화고': '특성화고등학교 관련 상담은 학년·희망 과목·교과 범위를 알려 주세요.',
}


def _fold(value):
    return re.sub(r'\s+', '', str(value or ''))


def public_school_groups(row):
    """Return groups, public notes and non-public reviewNotes without mutation.

    groups keeps the original school level and spelling, removing only explicit
    review brackets. Exact duplicate cleaned names are shown once, in input order.
    reviewNotes must be saved as management data, never rendered in public HTML.
    """
    groups = {level: [] for level, _, _ in LEVELS}
    notes, review = [], []
    for level, _, _ in LEVELS:
        for original in row.get('targetSchools', {}).get(level, []):
            annotations = []

            def remove_review(match):
                if REVIEW_ANNOTATION.search(match.group(1)):
                    annotations.append(match.group(1))
                    return ''
                return match.group(0)

            name = re.sub(r'\[([^\[\]]*)\]', remove_review, original).strip()
            note = GENERAL_NOTES.get(_fold(name))
            kind = 'general' if note else 'school'
            if annotations or note:
                review.append({'level': level, 'original': original, 'schoolName': None if note else name,
                               'annotations': annotations, 'kind': kind})
            if note:
                if note not in notes:
                    notes.append(note)
            elif name and name not in groups[level]:
                groups[level].append(name)
    return {'groups': groups, 'notes': notes, 'reviewNotes': review}


def _confirmed_grades(center, ref, subject):
    if subject not in {'영어', '수학'}:
        return []
    grades = center.get('subjects', {}).get(subject, {}).get('grades', [])
    if not grades or any(not re.fullmatch(r'(?:초[1-6]|중[1-3]|고[1-3])', g) for g in grades):
        return []
    overrides = ref.get('operations', {}).get('subjectDisplay', {})
    if overrides:
        detail = overrides.get(subject, {})
        if detail.get('status') not in CONFIRMED_STATUSES or detail.get('includeInUnqualifiedAvailableSubjects') is not True:
            return []
        # A contradictory source-grade set is not repaired by this reader layer.
        if 'sourceGrades' in detail and set(detail['sourceGrades']) != set(grades):
            return []
    elif subject not in center.get('availableSubjects', []):
        return []
    return list(dict.fromkeys(grades))


def subject_scope_confirmed(center, ref, subject):
    """True only for a recorded current subject scope; false is not 'not offered'."""
    return bool(_confirmed_grades(center, ref, subject))


def address_label(center):
    return '안내 위치' if center.get('addressPrecision') == 'neighborhood' else '주소'


def address_notice(center):
    if center.get('addressPrecision') == 'neighborhood':
        return '현재 안내는 동네와 주변 위치 기준입니다. 정확한 도로명 주소·건물·층수와 운영 상태는 방문 전 상담으로 확인해 주세요.'
    return ''


class _PageFacts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.graph, self.canonical, self.h1 = [], '', ''
        self._script, self._buffer, self._h1 = False, [], False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self._script, self._buffer = True, []
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs.get('href', '')
        if tag == 'h1':
            self._h1 = True

    def handle_data(self, data):
        if self._script:
            self._buffer.append(data)
        if self._h1:
            self.h1 += data

    def handle_endtag(self, tag):
        if tag == 'script' and self._script:
            value = json.loads(''.join(self._buffer))
            self.graph.extend(value.get('@graph', [value]))
            self._script = False
        if tag == 'h1':
            self._h1 = False


@lru_cache(maxsize=8)
def _mapping_cached(path, mtime_ns, size):
    rows = json.loads(Path(path).read_text(encoding='utf-8'))['rows']
    # Duplicated locality keys are not an implicit choice of the last row.
    result = {}
    for row in rows:
        key = row['locality']
        result[key] = None if key in result else row
    return result


def _mapping(root):
    path = root / 'tools/data/branch-neighborhoods/mapping.json'
    stat = path.stat()
    return _mapping_cached(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=2400)
def _page_facts_cached(path, mtime_ns, size):
    parser = _PageFacts()
    parser.feed(Path(path).read_text(encoding='utf-8'))
    return parser


def _page_facts(path):
    stat = path.stat()
    return _page_facts_cached(str(path), stat.st_mtime_ns, stat.st_size)


def _identity_matches(center, mapping, org):
    """Require current location and registered identity, not nearest/name guesses."""
    address = org.get('address', {})
    if not isinstance(address, dict) or center.get('addressPrecision') == 'neighborhood':
        return False
    evidence = mapping.get('evidence', {}).get('registeredIdentityComparison', [])
    reviewed = [e for e in evidence if e.get('centerId') == center['id'] and e.get('active') is True
                and e.get('strongIdentityEvidence') is True]
    if _fold(address.get('addressRegion')) != _fold(center['region']['province']):
        # Old pages may use the supplied macroregion (e.g. 충청), while the
        # current center uses its province. Accept only the explicit reviewed
        # source region, with exact current street address still required below.
        if not (mapping.get('sourceNeighborhoodRegion')
                and _fold(address.get('addressRegion')) == _fold(mapping['sourceNeighborhoodRegion'])
                and any(e.get('compatibleSourceRegion') is True for e in reviewed)):
            return False
    if _fold(address.get('streetAddress')) != _fold(center.get('address')):
        return False
    csv = mapping.get('evidence', {}).get('csv', {})
    if _fold(org.get('name')) != _fold(csv.get('centerName')):
        return False
    if not csv.get('registeredName') or _fold(csv['registeredName']) != _fold(center.get('registeredAcademyName')):
        return False
    identifier = org.get('identifier', '')
    if not isinstance(identifier, str) or not identifier or _fold(identifier) != _fold(csv.get('registrationNumber')):
        return False
    # Accept only exact registration text or an already-reviewed same-serial
    # spelling variation with current legal name, exact address and province.
    if _fold(identifier) == _fold(center.get('registrationNumber')):
        return True
    old_numbers, current_numbers = re.findall(r'\d+', identifier), re.findall(r'\d+', center.get('registrationNumber', ''))
    return bool(old_numbers and old_numbers == current_numbers and any(
        e.get('centerId') == center['id'] and e.get('active') is True and e.get('registeredSerialMatch') is True
        and e.get('exactRegisteredNameWhitespaceFold') is True and e.get('strongIdentityEvidence') is True
        for e in reviewed))


def related_grade_links(center, ref, locality, subject, *, root=None):
    """Return existing same-locality/subject grade links with verified identity.

    Each item has path, label, level, grades, scopeNote. A label identifies an
    editorial grade guide, not availability for every grade within that level.
    scopeNote keeps the actual grade subset/conditions for the caller to display.
    Missing/uncertain/stale facts result in no link, never an inferred substitute.
    """
    root = Path(root) if root is not None else ROOT
    grades = _confirmed_grades(center, ref, subject)
    if not grades or not locality or re.search(r'[/\\?#\x00-\x1f]', locality) or locality in {'.', '..'}:
        return []
    try:
        mapping = _mapping(root).get(locality)
    except (OSError, ValueError, KeyError):
        return []
    if not mapping or mapping.get('status') != 'confirmed' or mapping.get('centerId') != center['id']:
        return []
    if _fold(mapping.get('centerProvince')) != _fold(center['region']['province']):
        return []
    detail = ref.get('operations', {}).get('subjectDisplay', {}).get(subject, {}).get('detail', '')
    links = []
    for level, prefix, label in LEVELS:
        available = [g for g in grades if g.startswith(prefix)]
        if not available:
            continue
        path = f'/과목별학원/{label}{subject}학원/{locality}/'
        file = root / path.strip('/') / 'index.html'
        try:
            facts = _page_facts(file)
            if unquote(urlsplit(facts.canonical).path) != path or _fold(locality) not in _fold(facts.h1):
                continue
            organizations = [n for n in facts.graph if n.get('@type') == 'EducationalOrganization']
            if len(organizations) != 1 or not _identity_matches(center, mapping, organizations[0]):
                continue
            old_grades = organizations[0].get('educationalLevel', [])
            if not set(available).issubset(old_grades):
                continue
            services = [n for n in facts.graph if n.get('@type') == 'Service']
            if not any(n.get('serviceType') == f'{label} {subject}학원'
                       and n.get('provider', {}).get('@id') == organizations[0].get('@id') for n in services):
                continue
        except (OSError, ValueError, KeyError, TypeError):
            continue
        scope_note = '현재 안내 학년: ' + '·'.join(available)
        if detail:
            scope_note += '. ' + detail
        links.append({'path': path, 'label': f'{locality} {label} {subject}학원',
                      'level': level, 'grades': available, 'scopeNote': scope_note})
    return links
