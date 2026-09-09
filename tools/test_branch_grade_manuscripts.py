"""Grade parser safety and conservative source-preservation regression checks."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import warnings
from zipfile import ZipFile

import branch_grade_manuscripts as grade
from test_branch_manuscripts import manuscript


def raw(locality='가경동'):
    return manuscript(locality).replace('영어학원', '고2 영어학원').encode('utf-8-sig')


def record():
    result = grade._parse(raw(), '고2 영어학원/가경동 고2 영어학원.txt', '고2 영어', 'archive')
    result.update(subject='영어', grade='고2')
    return result


def source_path(school_grade, subject):
    name = f'{school_grade} {subject}학원.zip'
    candidates = [Path(__file__).resolve().parent / 'data' / 'branch-grades' / 'sources' / name,
                  Path('C:/Users/1992k/Desktop/프로그램 원고') / name,
                  Path('C:/Users/1992k/Desktop/프로그램 원고/한 거') / name]
    return next((p for p in candidates if p.is_file()), candidates[0])


class GradeManuscriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '고2 영어학원.zip'

    def archive(self, entries):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with ZipFile(self.path, 'w') as archive:
                for name, content in entries:
                    archive.writestr(name, content)
        return self.path

    def test_normalized_sorted_sources_and_crcrlf(self):
        other = raw('나성동').replace(b'\n', b'\r\r\n')
        self.archive([('고2 영어학원/나성동 고2 영어학원.txt', other),
                      ('고2 영어학원/가경동 고2 영어학원.txt', raw())])
        original = self.path.read_bytes()
        with patch.object(grade, 'EXPECTED_MANUSCRIPTS', 2):
            rows = grade.load_grade_archive(self.path, '고2 영어')
        self.assertEqual([r['locality'] for r in rows], ['가경동', '나성동'])
        self.assertEqual(rows[1]['sourceSha256'], hashlib.sha256(other).hexdigest())
        self.assertEqual(rows[0]['sourceArchiveSha256'], hashlib.sha256(original).hexdigest())
        self.assertTrue(all(r['subject'] == '영어' and r['grade'] == '고2' for r in rows))
        self.assertEqual(self.path.read_bytes(), original)

    def test_count_path_encoding_title_and_size_fail_closed(self):
        valid = '고2 영어학원/가경동 고2 영어학원.txt'
        for member, content in [(valid, raw()), ('../가경동 고2 영어학원.txt', raw()),
                                (valid, raw().decode('utf-8-sig').encode('cp949')),
                                (valid, raw('다른동'))]:
            self.archive([(member, content)])
            with self.subTest(member=member), self.assertRaises(grade.ManuscriptFormatError):
                grade.load_grade_archive(self.path, '영어')
        self.archive([(valid, raw())])
        for limit in ['MAX_ARCHIVE_BYTES', 'MAX_MEMBER_BYTES', 'MAX_UNCOMPRESSED_BYTES', 'MAX_MEMBERS']:
            with patch.object(grade, limit, 0), self.assertRaises(grade.ManuscriptFormatError):
                grade.load_grade_archive(self.path, '영어')

    def test_duplicate_member_and_invalid_grade(self):
        valid = '고2 영어학원/가경동 고2 영어학원.txt'
        self.archive([(valid, raw()), (valid, raw())])
        with self.assertRaises(grade.ManuscriptFormatError):
            grade.load_grade_archive(self.path, '영어')
        with self.assertRaises(grade.ManuscriptFormatError):
            grade.load_grade_archive(self.path, '영어', '고3')

    def test_mixed_list_keeps_original_high_school_spellings(self):
        before = '제공된 학교 정보에는 서현초, 서경초, 서현중, 경덕중, 사대부고, 서원고, 청주외고가 포함되어 있습니다.'
        self.assertEqual(grade._school_lists(before),
                         '제공된 학교 정보에는 사대부고, 서원고, 청주외고가 포함되어 있습니다.')
        self.assertEqual(grade._school_lists('학교명이 여수초, 야탑중, 아람고로 제공되어 있다면 확인해 주세요.'),
                         '학교명이 아람고로 제공되어 있다면 확인해 주세요.')

    def test_no_high_school_no_invention_and_history_retained(self):
        self.assertEqual(grade._school_lists('제공된 학교 정보에는 강선초가 포함되어 있습니다.'),
                         grade._SCHOOL_FALLBACK)
        for text in [
            '학교명은 양진중이나 광장중에서 진학한 학생인지처럼 배경을 설명하는 참고 정보로만 전달합니다.',
            '참고 학교 정보에 버드내중과 태평중이 포함되어 있으므로, 중학교 때의 수학 시험지를 가져갈 수 있습니다.',
            '제공된 학교명인 성리초·성리중 자료 상담이 필요한 가족이라면 고2 상담과 범위를 분리해 주세요.',
            '제공된 학교명인 염경초는 고2 학생의 현재 시험 범위를 판단할 자료가 아니므로 연결하지 않습니다.',
            '이 행에 학교 정보로 제시된 경상고와 성광고를 상담 대상으로 고려한다면, 서술형 문항의 비중을 확인하세요.',
        ]:
            with self.subTest(text=text):
                self.assertEqual(grade._school_lists(text), text)

    def test_deepcopy_metadata_cases_learning_input_preserved(self):
        row = record()
        row['cases'] = ['함수에 수를 입력하고 2, 0, 3을 비교합니다.', '두 번째 상황 예시입니다.']
        row['sections'][0]['paragraphs'] = ['G에 제시된 영어 수학을 함께 고려할 수 있습니다.']
        before = deepcopy(row)
        after, changes = grade.prepare_grade_manuscript(row)
        self.assertEqual(row, before)
        self.assertEqual(after['cases'], row['cases'])
        for key in ['title', 'meta', 'schemaSummary', 'sourceSha256', 'sourceArchiveSha256', 'sourceMember']:
            self.assertEqual(after[key], row[key])
        self.assertEqual(after['sections'][0]['heading'], row['sections'][0]['heading'])
        self.assertTrue(any(c['rule'] == 'grade-source-column-context' for c in changes))
        self.assertEqual(grade.prepare_grade_manuscript(after), (after, []))

    def test_gyoha_exact_override_does_not_touch_other_topics(self):
        row = record()
        row['locality'] = '교하'
        row['intro'] = '모르는 척 넘기는 습관을 확인합니다.'
        row['sections'][0]['heading'] = '모르는 척하는 순간을 먼저 구분해 보기'
        row['faq'][0]['question'] = '모르는 척하는 학생은 수업을 따라가기 어려운 학생으로 봐야 하나요?'
        after, changes = grade.prepare_grade_manuscript(row)
        self.assertIn('모르는 부분을 숨기고 넘기는 습관', after['intro'])
        self.assertIn('모르는 부분을 숨기는 학생', after['faq'][0]['question'])
        self.assertEqual(len([c for c in changes if c['rule'] == 'gyoha-concealed-understanding']), 3)
        row['subject'] = '수학'
        self.assertEqual(grade.prepare_grade_manuscript(row)[0]['intro'], row['intro'])

    def test_long_learning_intro_is_not_mechanically_truncated(self):
        row = record()
        row['intro'] = '부분 부정은 모든 항이 양수인 것은 아니라는 조건을 읽는 일입니다. ' * 7
        self.assertGreater(len(row['intro']), 230)
        self.assertEqual(grade._short_intro(row), row['intro'])

    def test_source_copy_phrase_becomes_reader_facing(self):
        row = record()
        row['sections'][0]['paragraphs'] = ['수업 내용은 이 원고의 제공 사실에 포함되어 있지 않으므로 상담에서 확인해 주세요.']
        result, changes = grade.prepare_grade_manuscript(row)
        self.assertEqual(result['sections'][0]['paragraphs'][0], '수업 내용은 이 안내에서 확인되지 않았으므로 상담에서 확인해 주세요.')
        self.assertEqual([c['rule'] for c in changes], ['grade-source-copy-context'])
        self.assertEqual(grade.prepare_grade_manuscript(result), (result, []))

    def test_high1_grade_parser_fallback_and_gyoha_isolation(self):
        content = raw().decode('utf-8-sig').replace('고2', '고1').encode('utf-8-sig')
        self.archive([('고1 영어학원/가경동 고1 영어학원.txt', content)])
        with patch.object(grade, 'EXPECTED_MANUSCRIPTS', 1):
            row = grade.load_grade_archive(self.path, '고1 영어', '고1')[0]
        self.assertEqual((row['subject'], row['grade'], row['title']), ('영어', '고1', '가경동 고1 영어학원'))
        row['locality'] = '교하'
        row['intro'] = '모르는 척 넘기는 습관을 확인합니다.'
        row['sections'][0]['heading'] = '모르는 척하는 순간을 먼저 구분해 보기'
        row['sections'][0]['paragraphs'] = ['제공된 학교 정보에는 강선초가 포함되어 있습니다.']
        after, changes = grade.prepare_grade_manuscript(row)
        self.assertEqual(after['intro'], row['intro'])
        self.assertEqual(after['sections'][0]['heading'], row['sections'][0]['heading'])
        self.assertTrue(after['sections'][0]['paragraphs'][0].startswith('고1 상담에서는'))
        self.assertFalse(any(c['rule'] == 'gyoha-concealed-understanding' for c in changes))

    def test_high1_context_cleanup_preserves_learning_input_and_speech(self):
        examples = [
            '함수 f(x)=x²에서 입력값이 -2 이상 1 이하인 조건을 생각해 볼 수 있습니다.',
            '최근 발표 원고와 녹음 파일을 함께 준비하고, 원고를 읽을 때의 차이를 살펴봅니다.',
            '상담에서는 원고 사용 가능 여부를 물어보세요.',
            '발표를 준비한다고 해서 매번 긴 원고를 작성할 필요는 없습니다.',
            'A와 B에 해당하는 성분의 형태와 기능을 확인해 주세요.',
        ]
        for text in examples:
            self.assertEqual(grade._high1_reader_context(text), text)
        self.assertEqual(grade._high1_reader_context('D열에 제공된 학교 정보입니다.'), '안내된 학교 정보입니다.')
        self.assertEqual(grade._high1_reader_context('원고를 준비할 때 영어 수학을 함께 고려합니다.'),
                         '상담을 준비할 때 영어 수학을 함께 고려합니다.')
        source = '상담 때는 ‘영어 수학’이라는 검색 의도만으로 두 과목의 운영을 추측하기보다, 학생의 시간을 확인하세요.'
        self.assertEqual(grade._high1_reader_context(source),
                         '상담 때는 영어·수학을 함께 찾고 있더라도 두 과목의 운영을 추측하기보다, 학생의 시간을 확인하세요.')

    def test_high2_display_and_logs_exact_regression_digest(self):
        if not all(source_path('고2', s).is_file() for s in ['영어', '수학']):
            self.skipTest('Original high2 archives are not available')
        display = []
        for subject in ['영어', '수학']:
            display += [grade.prepare_grade_manuscript(r)
                        for r in grade.load_grade_archive(source_path('고2', subject), subject)]
        actual = hashlib.sha256(json.dumps(display, ensure_ascii=False, sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(actual, 'f74b851050c41f8a4572c0f31d4109dc4c15da0999327478f5874c7573a42f7d')

    def test_high1_display_and_logs_exact_regression_digest(self):
        if not all(source_path('고1', s).is_file() for s in ['영어', '수학']):
            self.skipTest('Original high1 archives are not available')
        display = []
        for subject in ['영어', '수학']:
            display += [grade.prepare_grade_manuscript(r)
                        for r in grade.load_grade_archive(source_path('고1', subject), subject, '고1')]
        actual = hashlib.sha256(json.dumps(display, ensure_ascii=False, sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(actual, 'c07f5489480db767a3965ea56b6737af8a351a643aa791bddcb599ef2bdc030e')

    def test_middle_scope_preserves_progression_and_falls_back_to_middle(self):
        source = '제공된 학교 정보에는 청석초, 교하중, 두일중, 심학중, 교하고, 심학고가 포함되어 있습니다.'
        expected = '제공된 학교 정보에는 교하중, 두일중, 심학중이 포함되어 있습니다.'
        for school_grade in ['중1', '중2', '중3']:
            self.assertEqual(grade._middle_school_lists(source, school_grade), expected)
            self.assertEqual(grade._middle_school_lists('제공된 학교 정보에는 강선초가 포함되어 있습니다.', school_grade),
                             f'{school_grade} 상담에서는 재학 중인 중학교의 수업 자료와 현재 평가 범위를 준비해 주세요.')
        history = '제공된 학교 정보에는 교하중과 교하고가 포함되어 있으며, 고등학교 진학을 준비한다면 범위를 구분해 주세요.'
        self.assertEqual(grade._middle_school_lists(history, '중3'), history)
        earlier = '제공된 학교 정보에는 청석초가 포함되어 있으며, 초등 시절의 학습 이력을 확인할 수 있습니다.'
        self.assertEqual(grade._middle_school_lists(earlier, '중1'), earlier)

    def test_middle_authored_phrases_keep_learning_examples_and_headings(self):
        for school_grade in ['중1', '중2', '중3']:
            text = raw().decode('utf-8-sig').replace('고2', school_grade)
            self.archive([(f'{school_grade} 영어학원/가경동 {school_grade} 영어학원.txt', text.encode('utf-8-sig'))])
            with patch.object(grade, 'EXPECTED_MANUSCRIPTS', 1):
                row = grade.load_grade_archive(self.path, '영어', school_grade)[0]
            row['sections'][0]['paragraphs'] = ['D열에 학교명이 제공된 경우에도 확인해야 합니다.',
                                                '함수에 입력한 0.4와 0.04를 비교합니다. 원고 첨삭 범위를 확인합니다.']
            out, changes = grade.prepare_grade_manuscript(row)
            self.assertEqual(out['sections'][0]['paragraphs'][1], row['sections'][0]['paragraphs'][1])
            self.assertEqual(out['sections'][0]['heading'], row['sections'][0]['heading'])
            self.assertTrue(any(c['rule'] == 'middle-reader-context' for c in changes))
            self.assertEqual(grade.prepare_grade_manuscript(out), (out, []))

    def test_middle_2226_sources_structure_examples_and_repeat_preparation(self):
        grades = ['중1', '중2', '중3']
        if not all(source_path(g, s).is_file() for g in grades for s in ['영어', '수학']):
            self.skipTest('Original middle-grade archives are not available')
        sets = []
        for school_grade in grades:
            for subject in ['영어', '수학']:
                rows = grade.load_grade_archive(source_path(school_grade, subject), subject, school_grade)
                self.assertEqual(len(rows), 371)
                sets.append({r['locality'] for r in rows})
                for before in rows:
                    with self.subTest(grade=school_grade, locality=before['locality'], subject=subject):
                        original = deepcopy(before)
                        after, changes = grade.prepare_grade_manuscript(before)
                        self.assertEqual(before, original)
                        for key in ['title', 'meta', 'schemaSummary', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256']:
                            self.assertEqual(after[key], before[key])
                        self.assertEqual([s['heading'] for s in after['sections']],
                                         [s['heading'] for s in before['sections']])
                        self.assertEqual([len(s['paragraphs']) for s in after['sections']],
                                         [len(s['paragraphs']) for s in before['sections']])
                        self.assertEqual(len(after['faq']), 4)
                        self.assertEqual(len(after['cases']), len(before['cases']))
                        body = lambda r: ' '.join(p for s in r['sections'] for p in s['paragraphs']).replace(school_grade, '')
                        tokens = lambda r: Counter(re.findall(r'\d+(?:\.\d+)?|[A-Za-z_]+|[×÷=]', body(r)))
                        a, b = tokens(before), tokens(after)
                        for marker in ['D', 'E', 'G', 'ROW_DATA']:
                            a.pop(marker, None); b.pop(marker, None)
                        self.assertEqual(a, b)
                        self.assertEqual(grade.prepare_grade_manuscript(after), (after, []))
        self.assertTrue(all(s == sets[0] for s in sets))

    def test_middle_prior_display_and_logs_exact_regression_digests(self):
        expected = {
            '중1': '382ce077005b5be7431affe8ac4ffb4c3908c588f2fa8b5967a6fe7ccb605440',
            '중2': 'df8d0975be5f7ac3bee03a4f6723b4ea2a1785cb2a0a77c8b199a62530d306aa',
            '중3': 'bf7f1b6f8bc819364d570c4e6bf428be1b4e39c0c51b0cb7210c01d55289856d',
        }
        if not all(source_path(g, s).is_file() for g in expected for s in ['영어', '수학']):
            self.skipTest('Original middle-grade archives are not available')
        for school_grade, digest in expected.items():
            display = []
            for subject in ['영어', '수학']:
                display += [grade.prepare_grade_manuscript(r) for r in grade.load_grade_archive(
                    source_path(school_grade, subject), subject, school_grade)]
            actual = hashlib.sha256(json.dumps(display, ensure_ascii=False, sort_keys=True,
                                              separators=(',', ':')).encode()).hexdigest()
            self.assertEqual(actual, digest)

    def test_elementary_parser_scope_and_progression_preservation(self):
        for school_grade in ['초5', '초6']:
            content = raw().decode('utf-8-sig').replace('고2', school_grade).encode('utf-8-sig')
            self.archive([(f'{school_grade} 영어학원/가경동 {school_grade} 영어학원.txt', content)])
            with patch.object(grade, 'EXPECTED_MANUSCRIPTS', 1):
                row = grade.load_grade_archive(self.path, school_grade + ' 영어', school_grade)[0]
            self.assertEqual((row['grade'], row['subject']), (school_grade, '영어'))
            source = '제공된 학교 정보에는 청석초, 석곶초, 교하중, 두일중, 교하고가 포함되어 있습니다.'
            self.assertEqual(grade._elementary_school_lists(source, school_grade),
                             '제공된 학교 정보에는 청석초, 석곶초가 포함되어 있습니다.')
            self.assertEqual(grade._elementary_school_lists('제공된 학교 정보에는 동중이 포함되어 있습니다.', school_grade),
                             f'{school_grade} 상담에서는 재학 중인 초등학교의 수업 자료와 현재 학습 범위를 준비해 주세요.')
            for context in ['중학교 진학 이후의 자료는 별도로 구분해야 합니다.',
                            '중등 과정을 준비할 때는 현재 자료와 구분해 주세요.',
                            '과거 학습 이력에 관련된 자료입니다.']:
                self.assertEqual(grade._elementary_school_lists(source + ' ' + context, school_grade),
                                 source + ' ' + context)

    def test_elementary_reader_preserves_real_speech_and_function_input(self):
        for text in ['원고 한 문장이나 화면 일부를 골라 검토 전후를 남겨 보세요.',
                     '원고를 보았는지와 도움받았는지를 함께 표시하세요.',
                     '함수는 입력에 따라 값을 살펴보는 관점으로 설명할 수 있습니다.',
                     '오답노트 어플은 사진이나 입력 자료를 모아 보기 쉽습니다.']:
            self.assertEqual(grade._elementary_reader_context(text), text)
        self.assertEqual(grade._elementary_reader_context('입력에 제시된 상담 참고 항목는 영어와 수학입니다.'),
                         '상담 참고 항목은 영어와 수학입니다.')
        self.assertEqual(grade._elementary_reader_context('G에 제공된 영어 수학을 상담 질문으로 연결합니다.'),
                         '상담 참고 항목인 영어와 수학을 상담 질문으로 연결합니다.')

    def test_elementary_1484_sources_structure_examples_and_repeat_preparation(self):
        grades = ['초5', '초6']
        if not all(source_path(g, s).is_file() for g in grades for s in ['영어', '수학']):
            self.skipTest('Original elementary archives are not available')
        sets = []
        for school_grade in grades:
            for subject in ['영어', '수학']:
                rows = grade.load_grade_archive(source_path(school_grade, subject), subject, school_grade)
                self.assertEqual(len(rows), 371)
                sets.append({r['locality'] for r in rows})
                for before in rows:
                    with self.subTest(grade=school_grade, locality=before['locality'], subject=subject):
                        original = deepcopy(before)
                        after, changes = grade.prepare_grade_manuscript(before)
                        self.assertEqual(before, original)
                        for key in ['title', 'meta', 'schemaSummary', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256']:
                            self.assertEqual(after[key], before[key])
                        self.assertEqual([s['heading'] for s in after['sections']],
                                         [s['heading'] for s in before['sections']])
                        self.assertEqual([len(s['paragraphs']) for s in after['sections']],
                                         [len(s['paragraphs']) for s in before['sections']])
                        self.assertEqual(len(after['faq']), 4)
                        self.assertEqual(len(after['cases']), len(before['cases']))
                        body = lambda r: ' '.join(p for s in r['sections'] for p in s['paragraphs']).replace(school_grade, '')
                        tokens = lambda r: Counter(re.findall(r'\d+(?:\.\d+)?|[A-Za-z_]+|[×÷=]', body(r)))
                        a, b = tokens(before), tokens(after)
                        for marker in ['D', 'E', 'G', 'ROW_DATA']:
                            a.pop(marker, None); b.pop(marker, None)
                        self.assertEqual(a, b)
                        self.assertEqual(grade.prepare_grade_manuscript(after), (after, []))
        self.assertTrue(all(s == sets[0] for s in sets))

    def test_supplied_742_source_structure_and_examples(self):
        if not all(source_path('고2', s).is_file() for s in ['영어', '수학']):
            self.skipTest('User archives are not available on this machine')
        sets = []
        for subject in ['영어', '수학']:
            rows = grade.load_grade_archive(source_path('고2', subject), subject)
            sets.append({r['locality'] for r in rows})
            self.assertEqual(len(rows), 371)
            for before in rows:
                with self.subTest(locality=before['locality'], subject=subject):
                    after, changes = grade.prepare_grade_manuscript(before)
                    for key in ['title', 'meta', 'schemaSummary', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256']:
                        self.assertEqual(after[key], before[key])
                    self.assertEqual(len(after['faq']), 4)
                    self.assertEqual(len(after['cases']), len(before['cases']))
                    self.assertEqual([len(s['paragraphs']) for s in after['sections']],
                                     [len(s['paragraphs']) for s in before['sections']])
                    heading_changes = [c for c in changes if c['field'].endswith('.heading')]
                    self.assertTrue(not heading_changes or (subject == '영어' and before['locality'] == '교하'))
                    # Concrete numbers/equations in learning sections cannot be removed.
                    body = lambda r: ' '.join(p for s in r['sections'] for p in s['paragraphs']).replace('고2', '')
                    tokens = lambda r: Counter(re.findall(r'\d+(?:\.\d+)?|[A-Za-z]+|[×÷=]', body(r)))
                    source_tokens, display_tokens = tokens(before), tokens(after)
                    # Reviewed column markers G and D are writing context, not examples.
                    for marker in ['G', 'D']:
                        source_tokens.pop(marker, None); display_tokens.pop(marker, None)
                    self.assertEqual(source_tokens, display_tokens)
                    second, extra = grade.prepare_grade_manuscript(after)
                    self.assertEqual(second, after)
                    self.assertEqual(extra, [])
        self.assertEqual(sets[0], sets[1])

    def test_high1_742_sources_examples_and_repeat_preparation(self):
        if not all(source_path('고1', s).is_file() for s in ['영어', '수학']):
            self.skipTest('Original high1 archives are not available')
        sets = []
        for subject in ['영어', '수학']:
            rows = grade.load_grade_archive(source_path('고1', subject), subject, '고1')
            self.assertEqual(len(rows), 371)
            sets.append({r['locality'] for r in rows})
            for before in rows:
                with self.subTest(locality=before['locality'], subject=subject):
                    original = deepcopy(before)
                    after, changes = grade.prepare_grade_manuscript(before)
                    self.assertEqual(before, original)
                    for key in ['title', 'meta', 'schemaSummary', 'sourceMember', 'sourceSha256', 'sourceArchiveSha256']:
                        self.assertEqual(after[key], before[key])
                    self.assertEqual([s['heading'] for s in after['sections']],
                                     [s['heading'] for s in before['sections']])
                    self.assertEqual([len(s['paragraphs']) for s in after['sections']],
                                     [len(s['paragraphs']) for s in before['sections']])
                    self.assertEqual(len(after['faq']), 4)
                    self.assertEqual(len(after['cases']), len(before['cases']))
                    body = lambda r: ' '.join(p for s in r['sections'] for p in s['paragraphs']).replace('고1', '')
                    tokens = lambda r: Counter(re.findall(r'\d+(?:\.\d+)?|[A-Za-z_]+|[×÷=]', body(r)))
                    a, b = tokens(before), tokens(after)
                    for marker in ['D', 'E', 'G', 'ROW_DATA']:
                        a.pop(marker, None); b.pop(marker, None)
                    self.assertEqual(a, b)
                    self.assertEqual(grade.prepare_grade_manuscript(after), (after, []))
        self.assertEqual(sets[0], sets[1])


if __name__ == '__main__':
    unittest.main()
