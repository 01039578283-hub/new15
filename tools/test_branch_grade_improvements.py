"""Small regression suite for the exact reviewed-copy/preservation boundary."""
import copy
import json
import unittest

from audit_branch_grade_improvements import (REVISION, check_manifest, field_container,
    replay_reading, replay_reviewed, validate_points)


class GradeImprovementAuditTests(unittest.TestCase):
    def test_reviewed_edits_require_exact_full_before_and_preserve_input(self):
        original = {'intro': '기존 안내문입니다.', 'sections': [{'heading': '제목', 'paragraphs': ['기존 본문입니다.']}]}
        edit = {'field': 'sections[0].paragraphs[0]', 'before': '기존 본문입니다.', 'after': '검토한 본문입니다.'}
        result = replay_reviewed(original, [edit])
        self.assertEqual(result['sections'][0]['paragraphs'][0], '검토한 본문입니다.')
        self.assertEqual(original['sections'][0]['paragraphs'][0], '기존 본문입니다.')
        with self.assertRaises(ValueError):
            replay_reviewed(original, [dict(edit, before='다른 문장')])
        with self.assertRaises(ValueError):
            replay_reviewed(original, [edit, edit])

    def test_identity_and_source_fields_cannot_be_edited(self):
        for field in ('title', 'grade', 'path', 'sourceSha256', 'sections[0].paragraphs'):
            with self.assertRaises(ValueError):
                field_container({}, field)

    def test_excerpt_must_reference_the_exact_named_paragraph(self):
        record = {'sections': [{'paragraphs': ['분수를 비교할 때는 분모를 맞추고 수의 크기를 확인합니다.', '다른 문단입니다.']}]}
        point = {'text': '분모를 맞추고 수의 크기를 확인합니다.', 'sectionIndex': 1, 'paragraphIndex': 1}
        self.assertTrue(validate_points([point], record))
        for bad in (dict(point, text='분모를 바꾸면 성적이 향상됩니다.'), dict(point, paragraphIndex=2),
                    dict(point, sectionIndex=True), dict(point, paragraphIndex=0)):
            with self.assertRaises(ValueError):
                validate_points([bad], record)

    def test_manifest_only_revision_marker_and_archive_order_can_change(self):
        original = {'version': 1, 'archives': [{'grade': '고2', 'subject': '영어', 'sha256': 'original'}],
                    'pages': [{'title': '시험동 고2 영어학원', 'sourceSha256': 'source', 'path': '/same/'}]}
        baseline = {'sourceFiles': {'tools/data/branch-grades/pages.json': {'text': json.dumps(original)}}}
        current = copy.deepcopy(original)
        current['editorialRevision'] = REVISION
        current['pages'][0]['editorialRevision'] = REVISION
        self.assertTrue(check_manifest(current, baseline))
        for field in ('title', 'sourceSha256', 'path'):
            bad = copy.deepcopy(current)
            bad['pages'][0][field] = 'changed'
            with self.assertRaises(ValueError):
                check_manifest(bad, baseline)

    def test_reading_cannot_remove_specific_conditions_or_change_body(self):
        prefix = ('분수 문제에서는 분모와 분자를 따로 읽은 뒤 같은 크기로 나누어진 부분인지 확인하는 과정이 필요합니다. '
                  '틀린 풀이를 다시 적을 때는 계산 결과뿐 아니라 처음 선택한 풀이의 이유를 한 문장으로 설명해 보는 것이 좋습니다.')
        generic = '영어와 수학을 함께 비교할 때는 상담에서 확인해 보세요.'
        record = {'intro': prefix + ' ' + generic}
        edit = {'field': 'intro', 'before': record['intro'], 'after': prefix}
        self.assertEqual(replay_reading(record, [edit])['intro'], prefix)
        with self.assertRaises(ValueError):
            replay_reading(record, [dict(edit, field='sections[0].paragraphs[0]')])
        protected = '영어와 수학을 함께 비교할 때는 운영 여부를 확인해 보세요.'
        with self.assertRaises(ValueError):
            replay_reading({'intro': prefix + ' ' + protected},
                           [dict(edit, before=prefix + ' ' + protected)])


if __name__ == '__main__':
    unittest.main()
