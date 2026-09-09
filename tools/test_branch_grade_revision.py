"""Contracts for a scoped grade-only reader revision and topic-by-topic generation."""
import json
import unittest
from copy import deepcopy

from bs4 import BeautifulSoup
from generate_branch_grade_pages import EDITORIAL_REVISION, selected_subjects, keep_other_groups, merge_archives
from generate_branch_neighborhood_pages import render
from generate_branch_pages import ROOT, load_branch_data, url
from branch_reader_facts import _confirmed_grades
from refresh_branch_hierarchy import audit_script


class GroupSelectionTests(unittest.TestCase):
    def test_one_topic_does_not_remove_other_subject_or_grade(self):
        rows = [{'grade': g, 'subject': s, 'path': g + s} for g in ('고1', '고2') for s in ('수학', '영어')]
        before = deepcopy(rows)
        remaining = keep_other_groups(rows, '고2', selected_subjects('영어'))
        self.assertEqual([r['path'] for r in remaining], ['고1수학', '고1영어', '고2수학'])
        self.assertEqual(rows, before)

    def test_default_both_subjects_and_invalid_subject(self):
        self.assertEqual(selected_subjects(), ('수학', '영어'))
        self.assertEqual(selected_subjects('수학'), ('수학',))
        with self.assertRaises(ValueError):
            selected_subjects('국어')

    def test_source_archive_order_and_other_groups_are_preserved(self):
        rows = [{'grade': g, 'subject': s, 'sha256': g + s} for g in ('고1', '고2') for s in ('수학', '영어')]
        before = deepcopy(rows)
        self.assertEqual(merge_archives(rows, [deepcopy(rows[-1])]), before)
        self.assertEqual(rows, before)

    def test_new_revision_uses_own_checkpoint_but_legacy_is_preserved(self):
        grades = ['초5', '초6', '중1', '중2', '중3', '고1', '고2']
        self.assertEqual(audit_script(grades, EDITORIAL_REVISION), 'audit_branch_grade_improvements.py')
        self.assertEqual(audit_script(grades), 'audit_branch_elementary_pages.py')
        with self.assertRaises(ValueError):
            audit_script(grades[:-1], EDITORIAL_REVISION)
        with self.assertRaises(ValueError):
            audit_script(grades, 'unreviewed')


class ReaderRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, centers, references = load_branch_data()
        cls.centers = {c['id']: c for c in centers}
        cls.references = references['centers']
        cls.parents = json.loads((ROOT / 'tools/data/branch-neighborhoods/pages.json').read_text(encoding='utf-8'))['pages']

    def fixture(self, confirmed=True, revised=True):
        parent = next(p for p in self.parents if ('고2' in _confirmed_grades(self.centers[p['centerId']], self.references[p['centerId']], p['subject'])) == confirmed)
        title = parent['locality'] + ' 고2 ' + parent['subject'] + '학원'
        text = '풀이에서 빠뜨린 조건을 표시해 보세요. ' + '정답을 고친 뒤에는 풀이의 첫 단계와 사용한 근거를 설명하고 다음 문제에서도 같은 조건을 확인할 수 있는지 살펴봅니다. ' * 4
        manuscript = {'title': title, 'subject': parent['subject'], 'locality': parent['locality'],
                      'meta': '최근 풀이와 조건을 점검하는 안내입니다.', 'intro': '최근 풀이를 점검해 보세요.',
                      'sections': [{'heading': '빠뜨린 조건 찾기', 'paragraphs': [text.strip()]}],
                      'faq': [{'question': '무엇을 준비하나요?', 'answer': '최근 풀이를 준비합니다.'}], 'cases': []}
        context = {'grade': '고2', 'path': parent['path'] + '고2/', 'parentPath': parent['path'], 'parentTitle': parent['title']}
        if revised:
            context.update(editorialRevision=EDITORIAL_REVISION,
                           readingPoints=[{'text': '풀이에서 빠뜨린 조건을 표시해 보세요.', 'sectionIndex': 1, 'paragraphIndex': 1}])
        return parent, manuscript, context

    def page(self, parent, manuscript, context):
        _, html = render(self.centers[parent['centerId']], self.references[parent['centerId']], manuscript,
                         parent['representative'], {}, [], page_context=context)
        return BeautifulSoup(html, 'html.parser')

    def test_shortcuts_precede_intro_and_excerpt_has_source_coordinates(self):
        parent, manuscript, context = self.fixture()
        before = deepcopy(manuscript)
        soup = self.page(parent, manuscript, context)
        hero = soup.select_one('.branch-child-hero')
        elements = list(hero.children)
        self.assertLess(elements.index(hero.select_one('.branch-reading-shortcuts')), elements.index(hero.select_one('.branch-manuscript-intro')))
        point = hero.select_one('.branch-grade-takeaways li')
        self.assertEqual(point['data-source-section'], '1')
        self.assertIn(point.text, manuscript['sections'][0]['paragraphs'][0])
        self.assertEqual(manuscript, before)

    def test_invented_excerpt_and_negative_source_index_are_rejected(self):
        for point in ({'text': '성적 향상을 보장합니다.', 'sectionIndex': 1, 'paragraphIndex': 1},
                      {'text': '풀이에서 빠뜨린 조건을 표시해 보세요.', 'sectionIndex': 0, 'paragraphIndex': 1}):
            parent, manuscript, context = self.fixture()
            context['readingPoints'] = [point]
            with self.assertRaises(ValueError):
                self.page(parent, manuscript, context)

    def test_other_grade_panel_follows_faq_and_points_to_parent_selector(self):
        parent, manuscript, context = self.fixture()
        soup = self.page(parent, manuscript, context)
        self.assertEqual(soup.select_one('#questions').find_next_sibling('section')['id'], 'other-grades')
        self.assertEqual(soup.select_one('#other-grades a')['href'], parent['path'] + '#child-pages')
        self.assertIsNotNone(soup.select_one('#article-toc a[href="#other-grades"]'))
        graph = json.loads(soup.select_one('script[type="application/ld+json"]').string)['@graph']
        part = next(x for x in graph if x.get('@id') == url(context['path']) + '#other-grades')
        self.assertEqual(part['@type'], 'WebPageElement')

    def test_scope_badge_does_not_invent_service(self):
        for confirmed in (True, False):
            parent, manuscript, context = self.fixture(confirmed=confirmed)
            soup = self.page(parent, manuscript, context)
            graph = json.loads(soup.select_one('script[type="application/ld+json"]').string)['@graph']
            self.assertEqual(len([x for x in graph if x.get('@type') == 'Service']), int(confirmed))
            self.assertEqual(bool(soup.select_one('.branch-grade-scope-badge')), not confirmed)
            self.assertIn('학습 안내 대상', soup.select_one('.branch-child-quick').text)

    def test_sentence_wrapping_is_lossless_and_original_media_stays_untouched(self):
        parent, manuscript, context = self.fixture()
        soup = self.page(parent, manuscript, context)
        actual = soup.select_one('#section-1 .branch-manuscript-unit').get_text(' ', strip=True)
        self.assertEqual(actual, ' '.join(manuscript['sections'][0]['paragraphs'][0].split()))
        self.assertGreater(len(soup.select('#section-1 .branch-manuscript-paragraph')), 1)
        images = soup.select('.branch-primary-media img')
        self.assertEqual(len(images), 3)
        self.assertEqual(images[0]['style'], 'display:none;')
        self.assertEqual([x['alt'].split()[-1] for x in images], ['대표', '본문', '지도'])

    def test_legacy_context_does_not_receive_new_assets_or_navigation(self):
        parent, manuscript, context = self.fixture(revised=False)
        soup = self.page(parent, manuscript, context)
        self.assertNotIn('branch-grade-page', soup.body['class'])
        self.assertIsNone(soup.select_one('link[href="/assets/branch-grades.css"]'))
        self.assertIsNone(soup.select_one('#other-grades'))
        self.assertIsNone(soup.select_one('.branch-grade-takeaways'))


if __name__ == '__main__':
    unittest.main()
