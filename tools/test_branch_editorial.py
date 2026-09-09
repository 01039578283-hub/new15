"""Independent contracts for selective manuscript display editing."""
from copy import deepcopy
from pathlib import Path
import re
import unittest

from branch_editorial import prepare_editorial, _intro, _sentences
from branch_manuscripts import load_manuscript_archive


class EditorialTests(unittest.TestCase):
    def record(self):
        return {'locality': '테스트동', 'subject': '수학', 'title': '테스트동 수학학원',
                'meta': '원본 메타', 'intro': '자리값과 계산을 나누어 살펴보는 안내입니다.',
                'sections': [{'heading': '자리값의 구조를 설명하기', 'paragraphs': [
                    '472를 400+70+2로 나누어 보세요. 각 숫자의 뜻을 말로 설명합니다. 영어와 수학은 따로 확인하세요.',
                    '학생이 설명한 내용을 기록합니다. 며칠 뒤 다시 풀어 보세요.']}],
                'faq': [{'question': '무엇을 확인하나요?', 'answer': '숫자의 자리를 설명하는지 확인하세요. 304를 분해해 설명하면 됩니다. 상담에서는 복습 계획을 물어보세요.'}],
                'cases': ['보호자라면 최근 문제를 준비할 수 있습니다. 472를 분해한 기록도 준비합니다. 영어와 수학은 따로 확인하려 합니다.'],
                'schemaSummary': '원본 요약', 'sourceMember': '수학학원/테스트동 수학학원.txt',
                'sourceSha256': 'source-hash', 'sourceArchiveSha256': 'archive-hash'}

    def test_deepcopy_source_contract_and_complete_change_log(self):
        record = self.record(); frozen = deepcopy(record)
        result, changes = prepare_editorial(record)
        self.assertEqual(record, frozen)
        for key in ('title', 'meta', 'locality', 'subject', 'schemaSummary', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256'):
            self.assertEqual(result[key], record[key])
        self.assertEqual([s['heading'] for s in result['sections']], [s['heading'] for s in record['sections']])
        for change in changes:
            self.assertEqual(set(change) - {'stage'}, {'field', 'rule', 'count', 'before', 'after'})
        self.assertTrue(any(c.get('stage') == 'editorial' for c in changes))
        self.assertEqual(prepare_editorial(result), (result, []))

    def test_concrete_body_examples_and_case_examples_are_preserved(self):
        record = self.record()
        record['sections'].append({'heading': '영어와 수학을 함께 비교하기', 'paragraphs': [
            '영어와 수학의 자료를 나누어 보세요. 영어는 어휘를, 수학은 자리값을 확인합니다.',
            '472를 400+70+2로 나눕니다. 영어의 move와 walk를 비교합니다. 과목별 계획을 물어보세요.']})
        result, _ = prepare_editorial(record)
        visible = ' '.join(p for s in result['sections'] for p in s['paragraphs'])
        for phrase in ('472를 400+70+2로 나누어 보세요.', '472를 400+70+2로 나눕니다.', '영어의 move와 walk를 비교합니다.'):
            self.assertIn(phrase, visible)
        self.assertIn('472를 분해한 기록도 준비합니다.', result['cases'][0])

    def test_faq_keeps_direct_answer_and_concrete_detail(self):
        result, _ = prepare_editorial(self.record())
        self.assertEqual(result['faq'][0]['answer'], '숫자의 자리를 설명하는지 확인하세요. 304를 분해해 설명하면 됩니다.')

    def test_faq_keeps_reason_and_final_qualification(self):
        record = self.record()
        record['faq'][0]['answer'] = '학생의 기록을 기준으로 판단하세요. 상담에서 계획을 물어보세요. 다만 개설 여부는 별도 확인이 필요합니다.'
        result, _ = prepare_editorial(record)
        self.assertEqual(result['faq'][0]['answer'], record['faq'][0]['answer'])

    def test_unconfirmed_scope_comes_before_course_choice_and_is_idempotent(self):
        record = self.record()
        record['faq'][0]['question'] = '영어와 수학을 함께 선택할 때 무엇을 확인하나요?'
        result, _ = prepare_editorial(record, scope_confirmed=False)
        self.assertTrue(result['faq'][0]['answer'].startswith('수업 개설 여부와 대상 학년을 먼저 확인해 주세요.'))
        self.assertIn('304를 분해해 설명하면 됩니다.', result['faq'][0]['answer'])
        self.assertLessEqual(len(_sentences(result['faq'][0]['answer'])), 3)
        self.assertEqual(prepare_editorial(result, scope_confirmed=False), (result, []))

    def test_unconfirmed_scope_does_not_replace_a_learning_answer(self):
        record = self.record()
        result, _ = prepare_editorial(record, scope_confirmed=False)
        self.assertTrue(result['faq'][0]['answer'].startswith('숫자의 자리를 설명하는지'))

    def test_third_sentence_example_and_qualification_are_preserved(self):
        record = self.record()
        record['faq'][0]['answer'] = '자리값의 뜻을 먼저 설명해 보세요. 모형으로 각 자리의 양을 구분합니다. 예를 들어 304를 300+4로 나타낼 수 있습니다.'
        result, _ = prepare_editorial(record)
        self.assertIn('304를 300+4', result['faq'][0]['answer'])

    def test_three_reviewed_faq_meaning_corrections(self):
        for locality, subject, question in [
            ('광명동', '수학', '영어 수학을 함께 알아볼 때 무엇을 비교해야 하나요?'),
            ('교하', '수학', '영어 수학을 함께 공부할 때 어떤 점을 상담해야 하나요?'),
            ('교하', '영어', '영어 수학을 함께 학습할 때 상담에서 확인할 점은 무엇인가요?')]:
            record = self.record();record.update(locality=locality, subject=subject)
            record['faq'] = [{'question': question, 'answer': '두 과목의 수업 여부보다 주간 학습량을 먼저 확인하세요.'}]
            result, changes = prepare_editorial(record)
            self.assertNotIn('수업 여부보다', result['faq'][0]['answer'])
            self.assertNotIn('영어 문제 문장', result['faq'][0]['answer'])
            self.assertTrue(any(c['rule'] == 'reviewed-faq-meaning' for c in changes))

    def test_summary_uses_topic_beyond_generic_first_sentence(self):
        record = self.record()
        record['intro'] = ('테스트동에서 수학학원을 찾는 가정이라면 학생의 현재 상태와 학습 기록을 먼저 살펴보는 것이 좋습니다. '
                           '자리값을 헷갈리는 학생은 472를 400+70+2로 나타낸 뒤 각 숫자의 위치와 0의 역할을 설명해 보며, 자릿수 정렬이 계산에 어떻게 이어지는지 확인할 수 있습니다. '
                           '영어와 수학을 함께 알아본다면 과목별 상담 질문도 준비해 보세요.')
        summary = _intro(record)
        self.assertIn('472', summary)
        self.assertNotEqual(summary, _sentences(record['intro'])[0])
        self.assertTrue(summary.endswith('.'))
        self.assertLessEqual(len(summary), 180)

    def test_source_zip_hashes_and_all_numeric_body_sentences_survive(self):
        root = Path(__file__).resolve().parents[1]
        total = 0
        for subject in ('영어', '수학'):
            records = load_manuscript_archive(root / 'tools/data/branch-neighborhoods/sources' / (subject + '학원.zip'), subject)
            for record in records:
                frozen = deepcopy(record)
                result, _ = prepare_editorial(record)
                self.assertEqual(record, frozen)
                for key in ('title', 'meta', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256', 'schemaSummary'):
                    self.assertEqual(result[key], record[key], (record['title'], key))
                self.assertEqual([s['heading'] for s in result['sections']], [s['heading'] for s in record['sections']])
                before = [v for s in record['sections'] for p in s['paragraphs'] for v in _sentences(p) if re.search(r'\d|[A-Za-z]|[×÷=]', v)]
                after = ' '.join(p for s in result['sections'] for p in s['paragraphs'])
                for sentence in before:
                    # Source-description B/D/G columns and address wording are
                    # logged copy corrections, not deleted learning examples.
                    if re.search(r'B열|D열|G에는|입력|원고 참고|원고를 찾는|검색어', sentence):
                        continue
                    self.assertIn(sentence, after, record['title'])
                self.assertEqual(prepare_editorial(result), (result, []), record['title'])
                total += 1
        self.assertEqual(total, 742)


if __name__ == '__main__':
    unittest.main()
