"""Safety tests for the independent audit's allowed-change boundaries."""
import copy
import unittest

from audit_branch_improvements import (PARENT_NAVIGATION_JUMP, legacy_mask, normalize_parent_navigation,
                                       normalize_parent_navigation_css, parent_navigation_markup, replay_log)


class AuditBoundaryTests(unittest.TestCase):
    def navigation_fixture(self):
        children = [{'locality': '시험동', 'subject': subject, 'title': '시험동 ' + subject + '학원',
                     'path': '/지점안내/서울/시험점/시험동' + subject + '학원/'} for subject in ('영어', '수학')]
        new_panel, old_panel = parent_navigation_markup(children)
        shell = '<title>Keep</title><section class="branch-detail-hero"><div class="branch-actions">'
        after_hero = '<a href="tel:01068398283">Keep phone</a></div></section>'
        old = shell + after_hero + old_panel + '<article>Keep manuscript</article>'
        new = shell + PARENT_NAVIGATION_JUMP + after_hero + new_panel + '<article>Keep manuscript</article>'
        return children, old, new

    def test_parent_navigation_reverses_only_approved_changes(self):
        children, old, new = self.navigation_fixture()
        self.assertEqual(normalize_parent_navigation(new, children), (old, True))
        self.assertEqual(normalize_parent_navigation(old, children), (old, False))
        self.assertNotEqual(normalize_parent_navigation(new.replace('Keep manuscript', 'Changed'), children)[0], old)
        self.assertNotEqual(normalize_parent_navigation(new.replace('<title>Keep', '<title>Changed'), children)[0], old)

    def test_parent_navigation_rejects_bad_links_extra_copy_and_fake_center(self):
        children, _, new = self.navigation_fixture()
        for altered in (new.replace('시험동수학학원/', '다른동수학학원/'),
                        new.replace('자세히 볼 수 있습니다.', '반드시 성적이 오릅니다.'),
                        new.replace(PARENT_NAVIGATION_JUMP, PARENT_NAVIGATION_JUMP * 2)):
            with self.assertRaises(ValueError):
                normalize_parent_navigation(altered, children)
        with self.assertRaises(ValueError):
            normalize_parent_navigation(new, [])

    def test_parent_css_rejects_unreviewed_insertion(self):
        original = b'.branch-info { margin: 0; }\n'
        self.assertEqual(normalize_parent_navigation_css(original), (original, False))
        with self.assertRaises(ValueError):
            normalize_parent_navigation_css(b'.branch-neighborhood-navigation { display:none; }\n' + original)

    def test_legacy_mask_does_not_allow_title_or_article_edits(self):
        source = '<title>Original</title><article>Keep every word</article>'
        self.assertNotEqual(legacy_mask(source), legacy_mask(source.replace('Original', 'Changed')))
        self.assertNotEqual(legacy_mask(source), legacy_mask(source.replace('every', 'some')))

    def test_mask_only_allows_named_notice_not_other_added_copy(self):
        source = '<section>Keep</section>'
        self.assertEqual(legacy_mask(source), legacy_mask(source + '<p class="academy-scope-confirmation">Allowed field checked separately</p>'))
        self.assertNotEqual(legacy_mask(source), legacy_mask(source + '<p>Unapproved</p>'))

    def test_replay_rejects_unapproved_rule_and_lost_example(self):
        raw = {'locality': '시험동', 'subject': '수학', 'title': '시험동 수학학원', 'meta': 'Keep metadata',
               'intro': 'Keep intro.', 'sourceMember': '시험.txt', 'sourceSha256': 'abc', 'sourceArchiveSha256': 'def',
               'sections': [{'heading': 'Keep heading', 'paragraphs': ['24×13을 확인합니다. 일반 안내입니다.']}],
               'faq': [{'question': '질문?', 'answer': '답변입니다.'}], 'cases': ['상황입니다.']}
        original = copy.deepcopy(raw)
        errors = []
        check = lambda ok, *args: errors.append(args) if not ok else None
        log = [{'locality': '시험동', 'subject': '수학', 'stage': 'editorial',
                'field': 'sections[0].paragraphs', 'rule': 'unapproved', 'count': 1,
                'before': raw['sections'][0]['paragraphs'], 'after': ['일반 안내입니다.']}]
        replay_log({('시험동', '수학'): raw}, log, check)
        self.assertEqual(raw, original)
        self.assertTrue(any(e[0] == 'log-approved-editorial-rule-field' for e in errors))
        self.assertTrue(any(e[0] == 'protected-body-example-or-qualification' for e in errors))


if __name__ == '__main__':
    unittest.main()
