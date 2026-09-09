"""Bounded unit tests for source-faithful grade reading aids; no generation."""
from copy import deepcopy
import unittest

from branch_grade_reading import improve_grade_reading, _sentences


def fixture(**kwargs):
    record = {'grade': '고1', 'subject': '수학', 'locality': '명일동',
              'title': '명일동 고1 수학학원', 'meta': '수학 풀이 기록의 조건과 개념 설명을 확인합니다.',
              'intro': '수학 풀이를 자기 말로 설명하고 조건을 기록하는 연습이 필요합니다.',
              'sourceSha256': 'source-hash', 'path': '/unchanged/',
              'sections': [{'heading': '풀이를 자기 말로 바꾸는 학생 기록', 'paragraphs': [
                  '틀린 수학 문제를 다시 풀 때는 사용한 개념과 빠뜨린 조건을 나누어 적고, 풀이 순서를 자기 말로 설명하는 기록을 남겨 보세요.',
                  '이 기록을 보면서 다시 설명하는 것은 중요합니다.']}],
              'faq': [{'question': '풀이를 모두 적어야 하나요?', 'answer': '모든 문제를 적을 필요는 없습니다. 틀린 문제부터 고릅니다.'}],
              'cases': ['보호자가 풀이 기록을 준비하는 상황을 가정합니다.']}
    record.update(kwargs)
    return record


class GradeReadingTests(unittest.TestCase):
    def test_exact_source_and_coordinates(self):
        original = fixture()
        result, edits, points = improve_grade_reading(original)
        self.assertEqual(len(points), 1)
        p = points[0]
        self.assertIn(p['text'], original['sections'][p['sectionIndex']-1]['paragraphs'][p['paragraphIndex']-1])
        self.assertEqual((p['sectionIndex'], p['paragraphIndex']), (1, 1))
        self.assertEqual(edits, [])
        self.assertEqual(result, original)

    def test_input_and_every_non_intro_field_immutable(self):
        original = fixture()
        saved = deepcopy(original)
        result, _, points = improve_grade_reading(original)
        result['sections'][0]['paragraphs'][0] = 'caller mutation'
        self.assertEqual(original, saved)
        self.assertEqual(points[0]['text'], saved['sections'][0]['paragraphs'][0])

    def test_all_seven_grades_and_both_subjects(self):
        for grade in ('초5', '초6', '중1', '중2', '중3', '고1', '고2'):
            for subject in ('영어', '수학'):
                with self.subTest(grade=grade, subject=subject):
                    original = fixture(grade=grade, subject=subject)
                    result, edits, points = improve_grade_reading(original)
                    self.assertEqual(result, original)
                    self.assertEqual(edits, [])
                    self.assertLessEqual(len(points), 2)

    def test_other_subject_advice_not_promoted(self):
        original = fixture(subject='영어')
        self.assertEqual(improve_grade_reading(original)[2], [])

    def test_not_applied_to_parent_or_unsupported_grade(self):
        for grade in ('', '고3', None):
            self.assertEqual(improve_grade_reading(fixture(grade=grade))[1:], ([], []))

    def test_quote_decimal_and_formula_boundaries(self):
        text = '계산값 1.5를 확인합니다. 예를 들어 ‘x = 2. y = 3.’을 적습니다. 이어 읽습니다.'
        self.assertEqual(_sentences(text), ['계산값 1.5를 확인합니다.', '예를 들어 ‘x = 2. y = 3.’을 적습니다.', '이어 읽습니다.'])
        original = fixture(sections=[{'heading': '조건과 계산 기록', 'paragraphs': [
            '예를 들어 조건을 x = 2로 바꾸면 계산 결과가 달라지므로 식을 다시 쓰고 그래프의 위치를 확인하는 연습을 합니다.',
            '이때 풀이 조건을 적고 다시 확인하면 개념을 바르게 구분할 수 있으므로 기록을 남기는 것이 도움이 됩니다.']}])
        self.assertEqual(improve_grade_reading(original)[2], [])

    def test_institution_and_question_not_points(self):
        original = fixture(sections=[{'heading': '개념과 풀이', 'paragraphs': [
            '학원에서는 학생마다 틀린 문제의 조건과 풀이를 기록하고 개념을 다시 설명하는 방법으로 체계적인 수업을 운영합니다.',
            '상담에서는 학생의 풀이 조건과 개념을 어떤 방식으로 기록하는지 질문하고 최근 틀린 문제를 함께 확인해 보세요.']}])
        self.assertEqual(improve_grade_reading(original)[2], [])

    def test_unrelated_generic_and_short_material_can_return_empty(self):
        original = fixture(sections=[{'heading': '안내', 'paragraphs': [
            '짧은 설명입니다.', '학생에게 맞는 환경과 방법을 살펴보고 누구에게나 같은 방식이 적절하지 않을 수 있다는 점을 생각해 보세요.']}])
        self.assertEqual(improve_grade_reading(original)[2], [])

    def test_unresolved_step_and_reason_not_detached(self):
        for text in ('두 문제를 해결하면 표시를 바꾸고, 여전히 막히면 개념 설명으로 돌아가는 식으로 오답노트를 복습 순서와 연결해야 합니다.',
                     '이후 원문을 다시 보면서 바르게 고친 조건이 실제 계산과 결론에 끝까지 반영됐는지 학생이 표시하도록 해 보세요.',
                     '숫자가 나열된 표와 그래프의 관계를 해석한 뒤 풀이와 조건의 차이를 자기 말로 설명해야 하는 경우가 있기 때문입니다.'):
            record = fixture(sections=[{'heading': '조건과 풀이 기록', 'paragraphs': [text]}])
            self.assertEqual(improve_grade_reading(record)[2], [])

    def test_two_sentence_intro_and_faq_exactly_preserved(self):
        original = fixture(intro='수학 풀이 조건을 설명해 봅니다. 영어와 수학을 함께 살펴볼 때도 개념을 기록해 보세요.')
        result, edits, _ = improve_grade_reading(original)
        self.assertEqual(result, original)
        self.assertEqual(edits, [])

    def test_only_generic_third_intro_sentence_can_be_removed(self):
        first = '신월성에서 고2 수학학원을 고를 때는 진도 속도보다 학생이 증감표를 어느 단계에서 틀리는지 설명하고, 그 결과를 복습 계획으로 연결하는지 먼저 확인하는 것이 좋습니다.'
        second = '최근 풀이를 가져가 식 정리, 변화 판단, 표 완성, 그래프 해석을 차례로 점검해 달라고 요청하면 수업 적합성을 구체적으로 비교할 수 있습니다.'
        tail = '영어 수학을 함께 관리하는지가 궁금한 경우에도 막연한 통합 관리 여부보다 과목마다 진단과 피드백이 어떻게 구분되는지 질문해야 합니다.'
        original = fixture(intro=' '.join((first, second, tail)))
        result, edits, _ = improve_grade_reading(original)
        self.assertEqual(result['intro'], first + ' ' + second)
        self.assertEqual(edits[0]['field'], 'intro')
        for key in original:
            if key != 'intro':
                self.assertEqual(result[key], original[key])
        self.assertEqual(improve_grade_reading(result)[1], [])

    def test_unique_detail_or_scope_in_intro_is_preserved(self):
        beginning = '풀이 기록에서 학생이 계산 과정과 조건을 함께 설명할 수 있는지 살펴보면 개념을 적용하는 과정의 빈틈을 찾을 수 있습니다. 틀린 문제를 다시 풀고 풀이를 기록하는 습관은 학생이 막힌 지점을 스스로 확인하는 데 도움이 될 수 있습니다. '
        for tail in ('영어와 수학을 함께 비교할 때 수업 개설 여부를 확인해 보세요.',
                     '영어 수학을 함께 비교할 때 증감표와 문장 구조의 차이를 확인해 보세요.'):
            original = fixture(intro=beginning+tail)
            self.assertEqual(improve_grade_reading(original)[0]['intro'], original['intro'])

    def test_point_count_and_total_bound(self):
        sentence = fixture()['sections'][0]['paragraphs'][0]
        original = fixture(sections=[{'heading': heading, 'paragraphs': [sentence.replace('틀린 수학 문제', topic)]}
                                     for heading, topic in [('풀이의 조건', '복잡한 수학 문제'), ('개념의 연결', '다시 보는 수학 문제'), ('기록의 방법', '처음 보는 수학 문제')]])
        points = improve_grade_reading(original)[2]
        self.assertLessEqual(len(points), 2)
        self.assertLessEqual(sum(len(p['text']) for p in points), 320)

    def test_same_error_classification_action_not_two_points(self):
        original = fixture(sections=[
            {'heading': '풀이의 오류', 'paragraphs': ['계산 과정의 오류와 놓친 문제 조건을 서로 구분하여 표시하고 개념을 다시 설명할 수 있는지 점검해 보세요.']},
            {'heading': '풀이 기록', 'paragraphs': ['수학 풀이를 단원 이름으로만 모으지 말고 조건 누락과 계산 실수로 나누어 기록하면 다시 풀 때 확인할 내용을 정하기 쉽습니다.']}])
        self.assertEqual(len(improve_grade_reading(original)[2]), 1)


def write_review_samples():
    """Explicit opt-in artifact export: 3 localities x 14 grade/subjects only."""
    import hashlib
    import json
    from pathlib import Path
    from branch_grade_manuscripts import load_grade_archive, prepare_grade_manuscript
    from branch_grade_editorial import apply_reviewed_edits, MANIFEST_PATH

    root = Path(__file__).resolve().parent.parent
    localities = ('광명동', '명일동', '신월성')
    samples = []
    archives = []
    for grade in ('초5', '초6', '중1', '중2', '중3', '고1', '고2'):
        for subject in ('영어', '수학'):
            path = root / 'tools/data/branch-grades/sources' / f'{grade} {subject}학원.zip'
            before_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            records = {r['locality']: r for r in load_grade_archive(path, subject, grade)}
            for locality in localities:
                prepared, _ = prepare_grade_manuscript(records[locality])
                reviewed, prior_changes = apply_reviewed_edits(prepared)
                baseline = deepcopy(reviewed)
                result, changes, points = improve_grade_reading(reviewed)
                assert reviewed == baseline
                assert {k: v for k, v in result.items() if k != 'intro'} == {k: v for k, v in reviewed.items() if k != 'intro'}
                for point in points:
                    paragraph = reviewed['sections'][point['sectionIndex']-1]['paragraphs'][point['paragraphIndex']-1]
                    assert point['text'] in paragraph
                samples.append({'grade': grade, 'subject': subject, 'locality': locality,
                                'sourceSha256': reviewed['sourceSha256'],
                                'beforeIntro': reviewed['intro'], 'afterIntro': result['intro'],
                                'changes': changes, 'reviewedEditorialChanges': len(prior_changes),
                                'readingPoints': points,
                                'pointSourceParagraphs': [reviewed['sections'][p['sectionIndex']-1]['paragraphs'][p['paragraphIndex']-1] for p in points],
                                'faqUnchanged': result['faq'] == reviewed['faq'],
                                'bodyAndOtherFieldsUnchanged': True})
            assert hashlib.sha256(path.read_bytes()).hexdigest() == before_hash
            archives.append({'name': path.name, 'sha256': before_hash, 'unchanged': True})
    target = root / 'reports/branch-grades/2026-09-10-reading-samples.json'
    payload = {'scope': '42 fixed examples, prepared -> reviewed editorial -> reading; no HTML generation',
               'localities': localities, 'sampleCount': len(samples),
               'editorialManifestSha256': hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
               'readingModuleSha256': hashlib.sha256((root/'tools/branch_grade_reading.py').read_bytes()).hexdigest(),
               'introChanged': sum(bool(s['changes']) for s in samples),
               'pagesWithReadingPoints': sum(bool(s['readingPoints']) for s in samples),
               'readingPointCount': sum(len(s['readingPoints']) for s in samples),
               'sourceArchives': archives, 'samples': samples}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines = ['# 학년 원고 읽기 개선 고정 표본 42개', '',
             '적용 순서: 원본 파싱 → 기존 prepare → reviewed-editorial → reading.', '',
             '본문·FAQ·메타·제목·학교·운영·사례는 reading 단계에서 모두 그대로다. 핵심 포인트는 원문 연속 부분문자열이며 1-based 원문 위치를 남긴다. 전후 문맥이 불명확하면 발췌하지 않는다.', '',
             f"- 표본: {len(samples)}개, 첫 요약 변경 {payload['introChanged']}개, 포인트가 있는 페이지 {payload['pagesWithReadingPoints']}개, 포인트 {payload['readingPointCount']}개.",
             '- 14개 입력 ZIP은 읽기 전후 SHA-256 동일. HTML 생성·수정·배포 없음.', '']
    for sample in samples:
        lines.extend([f"## {sample['locality']} {sample['grade']} {sample['subject']}", '',
                      '첫 요약 전: '+sample['beforeIntro'], '',
                      '첫 요약 후: '+sample['afterIntro'], '', '핵심 포인트:', ''])
        for point in sample['readingPoints']:
            lines.append(f"- [{point['sectionIndex']}번 섹션 / {point['paragraphIndex']}번 문단] {point['text']}")
        if not sample['readingPoints']:
            lines.append('- 안전한 독립 문장 후보가 없어 생략.')
        lines.extend(['', 'FAQ·본문 및 다른 필드: reading 단계 무변경.', ''])
    target.with_suffix('.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({k: v for k, v in payload.items() if k not in ('samples', 'sourceArchives')}, ensure_ascii=False))


if __name__ == '__main__':
    import sys
    if '--review-samples' in sys.argv:
        sys.stdout.reconfigure(encoding='utf-8')
        write_review_samples()
    else:
        unittest.main()
