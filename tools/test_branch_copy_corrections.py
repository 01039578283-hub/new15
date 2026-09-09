"""Independent unit checks; no generator execution, files or network writes."""
import copy
import unittest

from branch_copy_corrections import apply_branch_copy_corrections


class BranchCopyCorrectionsTests(unittest.TestCase):
    def center(self, center_id='center-row-003', name='가좌점'):
        return {
            'id': center_id,
            'sourceCenterName': name,
            'address': '서울 서대문구 가재울로 52  승우빌딩 301호',
            'locationGuide': '',
            'subjects': {'영어': {'grades': ['초3', '중1']}},
            'registrationNumber': 'test-registration',
        }

    def application(self, name='가좌점'):
        return {
            'consultationSteps': [{
                'title': '상담 신청',
                'text': f'이 페이지 신청서나 카톡으로 {name}에 학년·과목·지금 고민을 남겨주세요.',
            }],
            'primaryMedia': {'map': {'src': '/original-map.gif'}},
            'operations': {'subjectDisplay': {'영어': {'summary': '초3 · 중1'}}},
        }

    def test_legacy_application_uses_actual_channels(self):
        center, reference = self.center(), self.application()
        changes = apply_branch_copy_corrections(center, reference)
        self.assertEqual(changes, ['consultation-actual-channels'])
        text = reference['consultationSteps'][0]['text']
        self.assertIn('전화·문자·상담 버튼', text)
        self.assertIn('가좌점 상담', text)
        self.assertNotIn('카톡', text)
        self.assertNotIn('이 페이지 신청서', text)

    def test_marked_center_name_is_preserved(self):
        center = self.center('center-row-056', '목감점(모두)')
        reference = self.application('목감점')
        apply_branch_copy_corrections(center, reference)
        self.assertIn('목감점(모두) 상담', reference['consultationSteps'][0]['text'])

    def test_existing_inquiry_and_design_are_left_to_generator(self):
        center = self.center('center-row-054', '명일점')
        reference = {'consultationSteps': [
            {'title': '문의', 'text': '기존 문의 원문'},
            {'title': '설계', 'text': '기존 설계 원문'},
        ]}
        before = copy.deepcopy(reference)
        self.assertEqual(apply_branch_copy_corrections(center, reference), [])
        self.assertEqual(reference, before)

    def test_other_application_copy_is_not_rewritten(self):
        center = self.center()
        reference = {'consultationSteps': [{'title': '상담 신청', 'text': '현재 확인된 상담 안내'}]}
        before = copy.deepcopy(reference)
        self.assertEqual(apply_branch_copy_corrections(center, reference), [])
        self.assertEqual(reference, before)

    def test_galmae_uses_canonical_address_for_shared_guide(self):
        center = self.center('center-row-004', '갈매점')
        center['address'] = '경기 구리시 갈매중앙로 79  에스엠타워 602호'
        center['locationGuide'] = '안녕하세요, OO학생 학부모님~갈매점. 구리시 갈매동79입니다.'
        original_address = center['address']
        changes = apply_branch_copy_corrections(center, {})
        self.assertEqual(changes, ['galmae-public-location-guide'])
        self.assertEqual(center['address'], original_address)
        self.assertEqual(center['locationGuide'], '경기 구리시 갈매중앙로 79 에스엠타워 602호로 방문해 주세요.')
        self.assertNotIn('OO학생', center['locationGuide'])
        self.assertNotIn('갈매동79', center['locationGuide'])

    def test_galmae_without_canonical_address_is_not_guessed(self):
        center = self.center('center-row-004', '갈매점')
        center.update(address='', locationGuide='OO학생 학부모님')
        before = copy.deepcopy(center)
        self.assertEqual(apply_branch_copy_corrections(center, {}), [])
        self.assertEqual(center, before)

    def test_other_center_identity_does_not_receive_galmae_fix(self):
        center = self.center('another-center', '갈매점')
        center['locationGuide'] = 'OO학생 학부모님'
        before = copy.deepcopy(center)
        self.assertEqual(apply_branch_copy_corrections(center, {}), [])
        self.assertEqual(center, before)

    def test_gojan_does_not_invent_the_missing_subject(self):
        center = self.center('center-row-009', '고잔점')
        reference = {'consultationSteps': [
            {'title': '레벨 테스트', 'text': '위주로 개념 구멍과 풀이 습관을 봐요.'},
        ]}
        changes = apply_branch_copy_corrections(center, reference)
        self.assertEqual(changes, ['gojan-incomplete-diagnosis'])
        text = reference['consultationSteps'][0]['text']
        self.assertEqual(text, '현재 이해도와 풀이 습관을 함께 살핍니다. 진단할 과목과 진행 방식은 상담에서 확인해 주세요.')
        for subject in ('영어', '수학', '국어', '과학', '사회'):
            self.assertNotIn(subject, text)

    def test_other_center_diagnosis_and_corrected_gojan_copy_are_unchanged(self):
        for center, text in [
            (self.center(), '위주로 개념 구멍과 풀이 습관을 봐요.'),
            (self.center('center-row-009', '고잔점'), '수학·영어 위주로 개념 구멍과 풀이 습관을 봐요.'),
        ]:
            with self.subTest(center=center['id'], text=text):
                reference = {'consultationSteps': [{'title': '레벨 테스트', 'text': text}]}
                before = copy.deepcopy(reference)
                self.assertEqual(apply_branch_copy_corrections(center, reference), [])
                self.assertEqual(reference, before)

    def test_unrelated_fields_are_preserved(self):
        center, reference = self.center(), self.application()
        original_center = copy.deepcopy(center)
        expected_reference = copy.deepcopy(reference)
        apply_branch_copy_corrections(center, reference)
        expected_reference['consultationSteps'][0]['text'] = reference['consultationSteps'][0]['text']
        self.assertEqual(center, original_center)
        self.assertEqual(reference, expected_reference)

    def test_idempotent_and_empty_reference_safe(self):
        center, reference = self.center(), self.application()
        apply_branch_copy_corrections(center, reference)
        once = copy.deepcopy(reference)
        self.assertEqual(apply_branch_copy_corrections(center, reference), [])
        self.assertEqual(reference, once)
        self.assertEqual(apply_branch_copy_corrections(center, {}), [])


if __name__ == '__main__':
    unittest.main()
