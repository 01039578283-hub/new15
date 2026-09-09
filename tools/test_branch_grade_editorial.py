"""Exact reviewed overlays: API safety, full-source replay and fact preservation."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import branch_grade_editorial as editorial
from branch_grade_manuscripts import (
    SUPPORTED_GRADES, load_grade_archive, prepare_grade_manuscript,
    _SCHOOL, _NOT_SCHOOLS,
)

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return {'grade': '초5', 'subject': '영어', 'locality': '시험동',
            'sourceSha256': 'a', 'sourceArchiveSha256': 'b',
            'title': '시험동 초5 영어학원', 'intro': '상담 참고 항목는 영어입니다.',
            'meta': '기존 메타', 'sections': [{'heading': '제목', 'paragraphs': ['내용']}],
            'faq': [{'question': '질문?', 'answer': '답변.'}], 'cases': ['상황 예시.']}


def approval(record):
    return {editorial._key(record): {
        **{k: record[k] for k in ('grade', 'subject', 'locality', 'sourceSha256', 'sourceArchiveSha256')},
        'edits': [{'field': 'intro', 'before': record['intro'],
                   'after': '상담 참고 항목은 영어입니다.', 'rules': ['particle-topic-marker']}]}}


def diff_fields(a, b, prefix=''):
    if isinstance(a, dict):
        if a.keys() != b.keys():
            return [prefix + ':keys']
        return [p for k in a for p in diff_fields(a[k], b[k], f'{prefix}.{k}' if prefix else k)]
    if isinstance(a, list):
        if len(a) != len(b):
            return [prefix + ':length']
        return [p for i, (x, y) in enumerate(zip(a, b)) for p in diff_fields(x, y, f'{prefix}[{i}]')]
    return [] if a == b else [prefix]


class ReviewedEditorialUnitTests(unittest.TestCase):
    def test_independent_record_and_exact_full_field_log(self):
        original = fixture()
        snapshot = deepcopy(original)
        with patch.object(editorial, '_load_manifest', return_value=approval(original)):
            result, changes = editorial.apply_reviewed_edits(original)
        self.assertEqual(original, snapshot)
        self.assertEqual(result['intro'], '상담 참고 항목은 영어입니다.')
        self.assertEqual(changes[0]['stage'], 'reviewed-editorial')
        self.assertEqual(changes[0]['before'], original['intro'])
        self.assertEqual(changes[0]['after'], result['intro'])
        self.assertEqual(diff_fields(original, result), ['intro'])
        result['faq'][0]['answer'] = 'different'
        self.assertEqual(original['faq'][0]['answer'], '답변.')

    def test_unlisted_identity_is_independent_noop(self):
        original = fixture()
        with patch.object(editorial, '_load_manifest', return_value={}):
            result, changes = editorial.apply_reviewed_edits(original)
        self.assertEqual(result, original)
        self.assertIsNot(result, original)
        self.assertEqual(changes, [])

    def test_source_hash_mismatch_fails_closed(self):
        original = fixture()
        manifest = approval(original)
        for field in ('sourceSha256', 'sourceArchiveSha256'):
            changed = deepcopy(original)
            changed[field] = 'unknown'
            with self.subTest(field=field), patch.object(editorial, '_load_manifest', return_value=manifest):
                with self.assertRaises(editorial.ReviewedEditorialError):
                    editorial.apply_reviewed_edits(changed)

    def test_prepared_text_mismatch_fails_closed(self):
        original = fixture()
        manifest = approval(original)
        original['intro'] += ' Unreviewed change.'
        with patch.object(editorial, '_load_manifest', return_value=manifest):
            with self.assertRaises(editorial.ReviewedEditorialError):
                editorial.apply_reviewed_edits(original)

    def test_idempotent_without_duplicate_logs(self):
        original = fixture()
        with patch.object(editorial, '_load_manifest', return_value=approval(original)):
            once, _ = editorial.apply_reviewed_edits(original)
            twice, logs = editorial.apply_reviewed_edits(once)
        self.assertEqual(twice, once)
        self.assertEqual(logs, [])

    def test_title_and_nontext_fields_cannot_be_targeted(self):
        for field in ('title', 'sourceSha256', 'schemaSummary', 'schools[0]', 'sections[0]', '__class__'):
            with self.subTest(field=field), self.assertRaises(editorial.ReviewedEditorialError):
                editorial._container(fixture(), field)

    def test_normal_speech_manuscript_table_and_prerequisite_are_untouched(self):
        original = fixture()
        original['intro'] = '발표 원고를 찾는 시간을 줄입니다. 이 행에서 식으로 옮깁니다. 예전에 배운 자리값을 복습합니다.'
        with patch.object(editorial, '_load_manifest', return_value={}):
            result, changes = editorial.apply_reviewed_edits(original)
        self.assertEqual(result, original)
        self.assertEqual(changes, [])


class ReviewedEditorialManifestTests(unittest.TestCase):
    def test_manifest_scope_and_full_field_uniqueness(self):
        manifest = editorial._load_manifest()
        self.assertEqual(len(manifest), 86)
        self.assertEqual(sum(len(r['edits']) for r in manifest.values()), 118)
        counts = Counter()
        for record in manifest.values():
            for edit in record['edits']:
                self.assertTrue(edit['before'])
                self.assertTrue(edit['after'])
                self.assertNotEqual(edit['before'], edit['after'])
                for rule in edit['rules']:
                    counts[rule] += 1
        self.assertEqual(counts, {'source-reader-context': 48, 'particle-topic-marker': 5,
                                 'operator-topic-focus': 20, 'customer-reader-perspective': 32,
                                 'learning-topic-alignment': 13})

    def test_all_5194_source_records_replay_and_protected_fields(self):
        manifest = editorial._load_manifest()
        archive_manifest = json.loads((ROOT / 'tools/data/branch-grades/pages.json').read_text(encoding='utf-8'))
        expected_hashes = {Path(a['path']).name: a['sha256'] for a in archive_manifest['archives']}
        school_data = json.loads((ROOT / 'tools/data/branches/school-match-audit.json').read_text(encoding='utf-8'))
        school_names = {name for row in school_data['matches'] for names in row['targetSchools'].values() for name in names}
        school_names |= {name.replace('초등학교', '초').replace('중학교', '중').replace('고등학교', '고') for name in school_names}
        count = changed = log_count = 0
        applied = set()
        normal_examples_checked = set()
        for grade in SUPPORTED_GRADES:
            for subject in ('영어', '수학'):
                archive = ROOT / 'tools/data/branch-grades/sources' / f'{grade} {subject}학원.zip'
                before_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
                self.assertEqual(before_sha, expected_hashes[archive.name])
                for raw in load_grade_archive(archive, subject, grade):
                    prepared, _ = prepare_grade_manuscript(raw)
                    original = deepcopy(prepared)
                    result, logs = editorial.apply_reviewed_edits(prepared)
                    self.assertEqual(prepared, original)
                    expected = manifest.get(editorial._key(prepared), {}).get('edits', [])
                    self.assertEqual(set(diff_fields(prepared, result)), {e['field'] for e in expected})
                    self.assertEqual(len(logs), len(expected))
                    self.assertEqual(result['title'], raw['title'])
                    self.assertEqual(result['schemaSummary'], raw['schemaSummary'])
                    self.assertEqual(result['sourceSha256'], raw['sourceSha256'])
                    self.assertEqual(result['sourceArchiveSha256'], raw['sourceArchiveSha256'])
                    for log in logs:
                        self.assertEqual(log['stage'], 'reviewed-editorial')
                        # The old broad school matcher also catches verb endings
                        # such as 준비하고: count only supplied names/short forms.
                        schools = lambda value: Counter(m[1] for m in _SCHOOL.finditer(value) if m[1] in school_names)
                        self.assertEqual(schools(log['before']), schools(log['after']))
                        # Numeric examples are invariant (grade labels are page
                        # context, not formulas). No reviewed edit adds a claim.
                        numbers = lambda value: re.findall(r'\d+(?:[.,~]\d+)*', value.replace(grade, ''))
                        self.assertEqual(numbers(log['before']), numbers(log['after']))
                    if logs:
                        applied.add(editorial._key(prepared))
                    selected_normal = {
                        ('중2', '영어', '퇴계동'), ('고1', '수학', '남가좌동'),
                        ('중1', '수학', '진관동'), ('고1', '영어', '권선동'),
                        ('고2', '영어', '권선동'), ('중3', '수학', '명일동'),
                    }
                    if editorial._key(prepared) in selected_normal:
                        self.assertEqual(result, prepared)
                        normal_examples_checked.add(editorial._key(prepared))
                    count += 1
                    changed += bool(logs)
                    log_count += len(logs)
                self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), before_sha)
        self.assertEqual((count, changed, log_count), (5194, 86, 118))
        self.assertEqual(applied, set(manifest))
        self.assertEqual(len(normal_examples_checked), 6)

    def test_approved_topic_residuals_removed_without_facts_or_title_changes(self):
        manifest = editorial._load_manifest()
        target_patterns = {('초5', '수학', '명일동'): r'독후감',
                           ('초6', '수학', '광명동'): r'동화되는 소리',
                           ('초5', '영어', '명일동'): r'입시결과'}
        for identity, pattern in target_patterns.items():
            edits = manifest[identity]['edits']
            for edit in edits:
                self.assertNotRegex(edit['after'], pattern)
                self.assertNotEqual(edit['field'], 'title')
        for record in manifest.values():
            for edit in record['edits']:
                self.assertNotRegex(edit['after'], r'학원창업|학원매출관리|학원고객관리|ROW_DATA|[DE]열|항목는')


if __name__ == '__main__':
    unittest.main()
