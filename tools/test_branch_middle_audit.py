"""Regression checks for the narrow middle1/2/3 extension boundary."""
import copy
import json
import unittest

from audit_branch_middle_pages import exact_child_panel, restore_existing_html, scoped_grades, reviewed_school_lists, url, WRITING_NOTES


class MiddleAuditTests(unittest.TestCase):
    def fixture(self):
        parent = '/지점안내/서울/시험점/시험동영어학원/'
        old_children = [{'grade': g, 'path': parent + g + '/', 'title': '시험동 ' + g + ' 영어학원'}
                        for g in ('고1', '고2')]
        children = [{'grade': g, 'path': parent + g + '/', 'title': '시험동 ' + g + ' 영어학원'}
                    for g in ('중1', '중2', '중3')]
        nodes = [{'@type': 'WebPage', '@id': url(parent) + '#webpage',
                  'hasPart': [{'@id': url(parent) + '#questions'}, {'@id': url(parent) + '#child-pages'}]},
                 {'@type': 'ItemList', '@id': url(parent) + '#child-pages', 'numberOfItems': 2,
                  'name': '학년별 학습 안내', 'isPartOf': {'@id': url(parent) + '#webpage'},
                  'itemListElement': [{'@type': 'ListItem', 'position': i, 'name': r['title'], 'url': url(r['path'])}
                                      for i, r in enumerate(old_children, 1)]}]
        prefix = '<html><head><title>Keep title</title><link rel="canonical" href="' + url(parent) + '">'
        def shell(graph, panel):
            return prefix + '<script type="application/ld+json">' + json.dumps({'@graph': graph}, ensure_ascii=False) + '</script></head><body><article>Keep manuscript</article><section id="questions"><p>Keep answer</p></section>' + panel + '</body></html>'
        old_panel = exact_child_panel(old_children)
        current_panel = exact_child_panel(children + old_children)
        current = copy.deepcopy(nodes)
        current[-1]['numberOfItems'] = 5
        for old in current[-1]['itemListElement']:
            old['position'] += 3
        current[-1]['itemListElement'] = [
            {'@type': 'ListItem', 'position': i, 'name': r['title'], 'url': url(r['path'])}
            for i, r in enumerate(children, 1)] + current[-1]['itemListElement']
        return shell(nodes, old_panel), shell(current, current_panel), children

    def test_only_exact_three_middle_buttons_reverse(self):
        before, after, children = self.fixture()
        self.assertTrue(restore_existing_html(before, after, 'neighborhood', children))

    def test_old_high_links_schema_and_other_copy_cannot_change(self):
        before, after, children = self.fixture()
        for bad in (after.replace('/고2/', '/고3/'), after.replace('/고1/', '/초1/'),
                    after.replace('Keep manuscript', 'Changed'), after.replace('Keep title', 'Changed'),
                    after.replace('Keep answer', 'Changed'), after.replace('"position": 4', '"position": 3')):
            with self.assertRaises(ValueError):
                restore_existing_html(before, bad, 'neighborhood', children)

    def test_wrong_order_duplicate_and_non_faq_position_rejected(self):
        before, after, children = self.fixture()
        anchor = '<a class="branch-child-link" href="' + children[0]['path'] + '">' + children[0]['title'] + '</a>'
        for bad in (after.replace(anchor, '').replace('</nav>', anchor + '</nav>'),
                    after.replace(anchor, anchor * 2),
                    after.replace('<section class="branch-panel', '<p>Moved away from FAQ</p><section class="branch-panel')):
            with self.assertRaises(ValueError):
                restore_existing_html(before, bad, 'neighborhood', children)

    def test_middle_scope_and_school_level_never_inferred_from_high(self):
        center = {'subjects': {'영어': {'grades': ['고1', '고2']}}, 'availableSubjects': ['영어']}
        self.assertNotIn('중1', scoped_grades(center, {}, '영어'))
        center['subjects']['영어']['grades'].append('중2')
        self.assertIn('중2', scoped_grades(center, {}, '영어'))
        self.assertNotIn('중1', scoped_grades(center, {}, '영어'))
        ref = {'operations': {'subjectDisplay': {'영어': {'status': 'scope_confirmation_needed', 'includeInUnqualifiedAvailableSubjects': False}}}}
        self.assertEqual(scoped_grades(center, ref, '영어'), [])
        self.assertEqual(reviewed_school_lists('안내된 학교 정보에는 시험초, 시험중, 시험고가 제시되어 있습니다.', '중2'),
                         '안내된 학교 정보에는 시험중이 제시되어 있습니다.')
        history = '안내된 학교에는 시험초, 시험중, 시험고가 있고 고등 진학을 준비합니다.'
        self.assertEqual(reviewed_school_lists(history, '중2'), history)

    def test_learning_manuscript_is_not_a_writer_note(self):
        self.assertIsNone(WRITING_NOTES.search('학생이 원고 없이도 풀이의 핵심을 재구성하는지입니다.'))
        self.assertIsNotNone(WRITING_NOTES.search('이 원고에서 학원 운영 사실을 확인할 수 없습니다.'))
        self.assertIsNotNone(WRITING_NOTES.search('상담에서는 이 원고의 내용을 확인합니다.'))


if __name__ == '__main__':
    unittest.main()
