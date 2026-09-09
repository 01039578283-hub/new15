"""Bounded regression tests for the approved text-only display overlay."""
from copy import deepcopy
import unittest

from polish_branch_manuscripts import polish_manuscript


class PolishManuscriptTests(unittest.TestCase):
    def record(self):
        return {
            'locality':'명일동', 'subject':'수학', 'title':'명일동 수학학원',
            'meta':'학교 자료를 준비합니다.', 'intro':'입력된 학교 정보에는 명일중이 있습니다.',
            'sections':[{'heading':'상담 전 준비', 'paragraphs':[
                '원고 참고 키워드에 영어 수학이 함께 제시되어 있습니다.',
                '학생이 원고를 읽고 첫 원고와 수정 원고를 비교합니다.',
            ]}],
            'faq':[{'question':'무엇을 확인하나요?', 'answer':'입력만으로 판단하지 마세요.'}],
            'cases':['보호자라면 상담을 준비할 수 있습니다.'],
            'schemaSummary':'입력된 학교 정보는 원본 요약으로 보존합니다.',
            'sourceMember':'수학학원/명일동 수학학원.txt',
            'sourceSha256':'raw-hash', 'sourceArchiveSha256':'archive-hash',
        }

    def test_changes_are_exact_and_source_is_independent(self):
        original = self.record()
        snapshot = deepcopy(original)
        result, changes = polish_manuscript(original)
        self.assertEqual(original, snapshot)
        self.assertIsNot(result, original)
        self.assertIsNot(result['sections'], original['sections'])
        self.assertEqual(result['intro'], '참고 학교 정보에는 명일중이 있습니다.')
        self.assertEqual(result['sections'][0]['paragraphs'][0], '상담 참고 항목에 영어 수학이 함께 제시되어 있습니다.')
        self.assertEqual(result['faq'][0]['answer'], '이 안내만으로 판단하지 마세요.')
        self.assertEqual(sum(c['count'] for c in changes), 3)
        self.assertEqual(changes[0], {'field':'intro','rule':'input-school-info','count':1,'before':'입력된 학교 정보','after':'참고 학교 정보'})
        for field in ('locality','subject','schemaSummary','sourceMember','sourceSha256','sourceArchiveSha256'):
            self.assertEqual(result[field], original[field])

    def test_all_reviewed_phrases_and_visible_field_types(self):
        record = {
            'title':'원고를 읽는 가정',
            'meta':'원고를 찾는 과정에서 비교합니다.',
            'intro':'원고를 준비하는 과정에서 확인합니다.',
            'sections':[{'heading':'D열에 제시된 학교 중', 'paragraphs':[
                '이 원고에서 확인되지 않은 운영 정보입니다.',
                '이 원고에 제공되지 않은 조건입니다.',
                '이 원고에서 판단할 수 없으므로 확인합니다.',
            ]}],
            'faq':[{'question':'입력 정보만으로 판단하나요?', 'answer':'아니요.'}],
            'cases':['입력된 학교 정보에는 학교명이 있습니다.'],
        }
        result, changes = polish_manuscript(record)
        self.assertEqual(result['title'],'이 안내를 읽는 가정')
        self.assertEqual(result['meta'],'학습 정보를 찾는 과정에서 비교합니다.')
        self.assertEqual(result['intro'],'상담을 준비하는 과정에서 확인합니다.')
        self.assertEqual(result['sections'][0]['heading'],'안내된 학교 중')
        self.assertEqual(result['faq'][0]['question'],'이 안내만으로 판단하나요?')
        self.assertTrue(all(p.startswith('이 안내') for p in result['sections'][0]['paragraphs']))
        self.assertEqual(sum(c['count'] for c in changes),9)

    def test_student_writing_and_other_input_are_preserved(self):
        text = (
            '학생이 원고를 읽습니다. 발표 원고와 수정 전 원고를 비교합니다. '
            '첫 원고와 수정 원고의 차이를 살핍니다. 원고에만 시선이 머뭅니다. '
            '원고를 보지 않고 말합니다. 이 원고의 주장을 요약합니다. '
            '단어 입력 연습과 개념 입력을 진행합니다. 학생이 입력한 답을 살핍니다. '
            '입력된 범위를 확인합니다. D열을 입력합니다.'
        )
        original = {'intro':text}
        result, changes = polish_manuscript(original)
        self.assertEqual(result,original)
        self.assertEqual(changes,[])

    def test_cases_remain_hypothetical_without_invented_results(self):
        original = {'cases':['상담을 앞둔 보호자라면 원고를 찾는 과정에서 질문을 준비할 수 있습니다.']}
        result, _ = polish_manuscript(original)
        self.assertEqual(result['cases'], ['상담을 앞둔 보호자라면 학습 정보를 찾는 과정에서 질문을 준비할 수 있습니다.'])
        self.assertIn('보호자라면',result['cases'][0])

    def test_reapplication_is_noop_and_occurrences_are_counted(self):
        result, changes = polish_manuscript({'intro':'입력만으로 알 수 없고, 입력만으로 판단하지 않습니다.'})
        self.assertEqual(changes[0]['count'],2)
        twice, repeated = polish_manuscript(result)
        self.assertEqual(twice,result)
        self.assertEqual(repeated,[])

    def test_reviewed_particle_school_and_search_contexts(self):
        original = {'intro': '원고 참고 키워드로 비교합니다. 입력에 제시된 학교를 확인합니다. 입력된 학교명만으로 판단하지 않습니다. 입력된 검색어에 영어 수학이 함께 포함되어 있다면 과목을 나눠 보세요.'}
        result, changes = polish_manuscript(original)
        self.assertEqual(result['intro'], '상담 참고 항목으로 비교합니다. 안내된 학교를 확인합니다. 안내된 학교명만으로 판단하지 않습니다. 영어와 수학을 함께 고려한다면 과목을 나눠 보세요.')
        self.assertTrue(any(c['rule'] == 'reader-noun-particle' for c in changes))
        self.assertEqual(polish_manuscript(result), (result, []))

    def test_learning_input_search_and_keywords_are_not_blanket_changed(self):
        original = {'intro': '함수의 입력값과 출력을 비교합니다. 학생이 입력한 답, 입력 조건과 결과를 기록합니다. 검색어, 확인한 개념, 키워드 메모를 정리합니다. 입력과 출력이 섞여 있습니다.'}
        self.assertEqual(polish_manuscript(original), (original, []))

    def test_new_review_rules_preserve_source_titles_metadata_and_headings(self):
        original = {'title': '입력된 학교 안내', 'meta': '입력에 없는 운영 정보',
                    'intro': '입력에 없는 운영 정보는 확인하세요.',
                    'sections': [{'heading': '입력된 학교', 'paragraphs': []}]}
        result, _ = polish_manuscript(original)
        self.assertEqual(result['title'], original['title'])
        self.assertEqual(result['meta'], original['meta'])
        self.assertEqual(result['sections'], original['sections'])
        self.assertEqual(result['intro'], '이 안내에 없는 운영 정보는 확인하세요.')


if __name__ == '__main__':
    unittest.main()
