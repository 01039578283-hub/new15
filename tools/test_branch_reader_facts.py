"""Unit and current-data tests. Generates only temporary fixtures; no site writes."""
from copy import deepcopy
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import branch_reader_facts as facts


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReaderUnitTests(unittest.TestCase):
    def test_school_names_and_review_annotations(self):
        source = {'targetSchools': {'elementary': ['성남은행초등학교 [후보·지역 확인 필요; 후보 지역: 경기 성남시]', '시흥은행초등학교 [후보 지역: 경기 시흥시]', '성남은행초등학교'],
                                    'middle': ['청솔중학교 [2025 통계 휴·폐교]'], 'high': ['단대부고', '사대부고']}}
        before = deepcopy(source)
        result = facts.public_school_groups(source)
        self.assertEqual(result['groups']['elementary'], ['성남은행초등학교', '시흥은행초등학교'])
        self.assertEqual(result['groups']['middle'], ['청솔중학교'])
        self.assertEqual(result['groups']['high'], ['단대부고', '사대부고'])
        self.assertEqual(len(result['reviewNotes']), 3)
        self.assertEqual(result['notes'], [])
        self.assertEqual(source, before)

    def test_general_labels_are_not_school_names_or_offering_claims(self):
        row = {'targetSchools': {'elementary': ['기타사립초 [기존 안내·대상 미확인]'], 'high': ['지역내 모든 고등학교 가능 [기존 안내·대상 미확인]', '특성화고 [기존 안내·대상 미확인]']}}
        result = facts.public_school_groups(row)
        self.assertTrue(all(not group for group in result['groups'].values()))
        self.assertEqual(len(result['notes']), 3)
        self.assertNotIn('모든', ' '.join(result['notes']))
        self.assertNotIn('가능', ' '.join(result['notes']))
        self.assertEqual({r['kind'] for r in result['reviewNotes']}, {'general'})

    def test_unknown_school_brackets_and_spelling_preserved(self):
        row = {'targetSchools': {'elementary': ['작은초등학교 [분교]', '단  대초등학교']}}
        self.assertEqual(facts.public_school_groups(row)['groups']['elementary'], row['targetSchools']['elementary'])

    def test_uncertainty_is_not_offering(self):
        center = {'subjects': {'영어': {'grades': ['초3', '중1']}}, 'availableSubjects': ['영어']}
        for status in ('unrecorded', 'scope_confirmation_needed', 'note_only_scope', 'not_offered'):
            ref = {'operations': {'subjectDisplay': {'영어': {'status': status, 'includeInUnqualifiedAvailableSubjects': True}}}}
            self.assertFalse(facts.subject_scope_confirmed(center, ref, '영어'))

    def test_conditions_allowed_but_conflicting_grades_not(self):
        center = {'subjects': {'영어': {'grades': ['초3']}}, 'availableSubjects': ['영어']}
        ref = {'operations': {'subjectDisplay': {'영어': {'status': 'recorded_with_conditions', 'includeInUnqualifiedAvailableSubjects': True, 'sourceGrades': ['초3']}}}}
        self.assertTrue(facts.subject_scope_confirmed(center, ref, '영어'))
        ref['operations']['subjectDisplay']['영어']['sourceGrades'] = ['고3']
        self.assertFalse(facts.subject_scope_confirmed(center, ref, '영어'))
        self.assertFalse(facts.subject_scope_confirmed(center, {}, '수학'))

    def test_partial_address_notice(self):
        partial = {'addressPrecision': 'neighborhood'}
        self.assertEqual(facts.address_label(partial), '안내 위치')
        self.assertIn('정확한 도로명 주소·건물·층수', facts.address_notice(partial))
        self.assertEqual(facts.address_label({}), '주소')
        self.assertEqual(facts.address_notice({}), '')

    def link_fixture(self, root, *, change_org=None, change_mapping=None):
        center = {'id': 'test-center', 'registeredAcademyName': '확정학원', 'registrationNumber': '서울 등록 제 123호',
                  'address': '서울 구로구 확인로 10 2층', 'region': {'province': '서울'},
                  'subjects': {'영어': {'grades': ['초3', '초4']}}, 'availableSubjects': ['영어']}
        mapping = {'locality': '확인동', 'status': 'confirmed', 'centerId': 'test-center', 'centerProvince': '서울',
                   'evidence': {'csv': {'centerName': '확정센터', 'registeredName': '확정학원', 'registrationNumber': '서울 등록 제 123호'}}}
        if change_mapping:
            change_mapping(mapping)
        mapping_file = root / 'tools/data/branch-neighborhoods/mapping.json'
        mapping_file.parent.mkdir(parents=True)
        mapping_file.write_text(json.dumps({'rows': [mapping]}, ensure_ascii=False), encoding='utf-8')
        path = '/과목별학원/초등학생영어학원/확인동/'
        org = {'@type': 'EducationalOrganization', '@id': '#org', 'name': '확정센터', 'identifier': '서울 등록 제 123호',
               'address': {'addressRegion': '서울', 'streetAddress': center['address']}, 'educationalLevel': ['초3', '초4']}
        if change_org:
            change_org(org)
        graph = [org, {'@type': 'Service', 'serviceType': '초등학생 영어학원', 'provider': {'@id': '#org'}}]
        file = root / path.strip('/') / 'index.html'
        file.parent.mkdir(parents=True)
        file.write_text('<link rel="canonical" href="https://example.test' + path + '"><h1>확인동 초등학생 영어학원</h1><script type="application/ld+json">' + json.dumps({'@graph': graph}, ensure_ascii=False) + '</script>', encoding='utf-8')
        return center, path, file

    def test_existing_same_center_same_level_links_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            center, path, _ = self.link_fixture(root)
            before = deepcopy(center)
            links = facts.related_grade_links(center, {}, '확인동', '영어', root=root)
            self.assertEqual([r['path'] for r in links], [path])
            self.assertEqual(links[0]['grades'], ['초3', '초4'])
            self.assertIn('초3·초4', links[0]['scopeNote'])
            self.assertEqual(center, before)
            self.assertEqual(facts.related_grade_links(center, {}, '../확인동', '영어', root=root), [])

    def test_stale_identity_or_address_rejected(self):
        alterations = [lambda o: o.update(identifier='서울 등록 제 999호'),
                       lambda o: o['address'].update(addressRegion='경기'),
                       lambda o: o['address'].update(streetAddress='서울 구로구 옛주소 90'),
                       lambda o: o.update(name='다른센터'),
                       lambda o: o.update(educationalLevel=['초1'])]
        for alteration in alterations:
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                center, _, _ = self.link_fixture(root, change_org=alteration)
                self.assertEqual(facts.related_grade_links(center, {}, '확인동', '영어', root=root), [])

    def test_missing_file_wrong_mapping_and_uncertain_subject_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            center, _, file = self.link_fixture(root, change_mapping=lambda m: m.update(centerId='different'))
            self.assertEqual(facts.related_grade_links(center, {}, '확인동', '영어', root=root), [])
            file.unlink()
            self.assertEqual(facts.related_grade_links(center, {}, '확인동', '영어', root=root), [])

    def test_only_explicit_reviewed_macroregion_is_accepted(self):
        def mapping_update(m):
            m['sourceNeighborhoodRegion'] = '광역집계명'
            m['evidence']['registeredIdentityComparison'] = [{'centerId': 'test-center', 'active': True,
                'strongIdentityEvidence': True, 'compatibleSourceRegion': True}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            center, path, _ = self.link_fixture(root, change_org=lambda o: o['address'].update(addressRegion='광역집계명'),
                                                change_mapping=mapping_update)
            self.assertEqual([r['path'] for r in facts.related_grade_links(center, {}, '확인동', '영어', root=root)], [path])


class CurrentDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from generate_branch_pages import load_branch_data
        cls.raw_paths = list((facts.ROOT / 'tools/data/branches').glob('*.json')) + list((facts.ROOT / 'tools/data/branch-neighborhoods').rglob('*'))
        cls.raw_paths = [p for p in cls.raw_paths if p.is_file()]
        cls.raw_paths.append(facts.ROOT.parent / '참고자료/공통자료/센터정보 정리.csv')
        cls.before_hashes = {str(p): digest(p) for p in cls.raw_paths}
        _, centers, reference = load_branch_data()
        cls.centers = {c['id']: c for c in centers}
        cls.reference = reference['centers']
        cls.mapping = json.loads((facts.ROOT / 'tools/data/branch-neighborhoods/mapping.json').read_text(encoding='utf-8'))['rows']

    @classmethod
    def tearDownClass(cls):
        after = {str(p): digest(p) for p in cls.raw_paths}
        if after != cls.before_hashes:
            raise AssertionError('Original source files changed during reader tests')

    def test_all_371_school_rows_keep_owner_confirmed_names(self):
        rows = json.loads((facts.ROOT / 'tools/data/branches/target-schools.json').read_text(encoding='utf-8'))
        annotated = 0
        notes = Counter()
        for row in rows:
            before = deepcopy(row)
            result = facts.public_school_groups(row)
            annotated += bool(result['reviewNotes'])
            for note in result['notes']:
                notes[note] += 1
            review_by_original = {r['original']: r for r in result['reviewNotes']}
            for level, originals in row.get('targetSchools', {}).items():
                for original in originals:
                    review = review_by_original.get(original)
                    if review and review['kind'] == 'general':
                        continue
                    expected = review['schoolName'] if review else original
                    self.assertIn(expected, result['groups'][level])
            self.assertEqual(row, before)
            self.assertNotRegex(' '.join(n for group in result['groups'].values() for n in group), r'\[(?:후보|기존 안내|2025 통계)')
        self.assertEqual(len(rows), 371)
        self.assertEqual(annotated, 22)
        print(json.dumps({'publicSchoolRows': len(rows), 'reviewAnnotationRows': annotated, 'generalNoteRows': dict(notes)}, ensure_ascii=False))

    def test_current_742_scopes_and_existing_grade_links(self):
        unconfirmed, link_total, linked_pages = [], 0, 0
        no_links = []
        for mapping in self.mapping:
            center = self.centers[mapping['centerId']]
            ref = self.reference[center['id']]
            for subject in ('영어', '수학'):
                confirmed = facts.subject_scope_confirmed(center, ref, subject)
                links = facts.related_grade_links(center, ref, mapping['locality'], subject)
                if not confirmed:
                    unconfirmed.append([mapping['locality'], subject])
                    self.assertEqual(links, [])
                if links:
                    linked_pages += 1
                else:
                    no_links.append([mapping['locality'], subject, 'uncertain_scope' if not confirmed else 'existing_page_identity_or_grade_unverified'])
                link_total += len(links)
                for link in links:
                    self.assertTrue((facts.ROOT / link['path'].strip('/') / 'index.html').is_file())
                    self.assertTrue(set(link['grades']).issubset(center['subjects'][subject]['grades']))
        self.assertEqual(len(self.mapping), 371)
        self.assertEqual(len(unconfirmed), 18)
        self.assertGreater(link_total, 1500)
        print(json.dumps({'localities': len(self.mapping), 'unconfirmedPages': len(unconfirmed), 'gradeLinks': link_total,
                          'pagesWithGradeLinks': linked_pages, 'pagesWithoutGradeLinks': len(no_links),
                          'noLinkReasons': dict(Counter(row[2] for row in no_links)), 'firstNoLinkExamples': no_links[:12]}, ensure_ascii=False))


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    unittest.main(verbosity=2)
