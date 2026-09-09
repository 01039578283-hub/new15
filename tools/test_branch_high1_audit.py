"""Regression checks for the exact high1 extension and preservation boundaries."""
import copy
import json
import unittest

from audit_branch_high1_pages import exact_child_panel, restore_existing_html, scoped_grades, url


class High1AuditTests(unittest.TestCase):
    def fixture(self):
        parent = '/지점안내/서울/시험점/시험동영어학원/'
        old_child = {'path': parent + '고2/', 'title': '시험동 고2 영어학원'}
        child = {'path': parent + '고1/', 'title': '시험동 고1 영어학원'}
        nodes = [{'@type': 'WebPage', '@id': url(parent) + '#webpage',
                  'hasPart': [{'@id': url(parent) + '#questions'}, {'@id': url(parent) + '#child-pages'}]},
                 {'@type': 'ItemList', '@id': url(parent) + '#child-pages', 'numberOfItems': 1,
                  'name': '학년별 학습 안내', 'isPartOf': {'@id': url(parent) + '#webpage'},
                  'itemListElement': [{'@type': 'ListItem', 'position': 1, 'name': old_child['title'], 'url': url(old_child['path'])}]}]
        prefix = '<html><head><title>Keep title</title><link rel="canonical" href="' + url(parent) + '">'
        def shell(graph, panel):
            return prefix + '<script type="application/ld+json">' + json.dumps({'@graph': graph}, ensure_ascii=False) + '</script></head><body><article>Keep manuscript</article><section id="questions"><p>Keep answer</p></section>' + panel + '</body></html>'
        old_panel = exact_child_panel(old_child)
        anchor = '<a class="branch-child-link" href="' + child['path'] + '">' + child['title'] + '</a>'
        opening = '<nav class="branch-child-links" aria-label="학년별 학습 안내">'
        current_panel = old_panel.replace(opening, opening + anchor, 1)
        current = copy.deepcopy(nodes)
        current[-1]['numberOfItems'] = 2
        current[-1]['itemListElement'][0]['position'] = 2
        current[-1]['itemListElement'].insert(0, {'@type': 'ListItem', 'position': 1, 'name': child['title'], 'url': url(child['path'])})
        return shell(nodes, old_panel), shell(current, current_panel), child, anchor

    def test_only_exact_high1_prepend_reverses(self):
        before, after, child, _ = self.fixture()
        self.assertTrue(restore_existing_html(before, after, 'neighborhood', child))

    def test_existing_high2_link_and_other_copy_cannot_change(self):
        before, after, child, _ = self.fixture()
        for bad in (after.replace('/고2/', '/고3/'), after.replace('Keep manuscript', 'Changed'),
                    after.replace('Keep title', 'Changed'), after.replace('Keep answer', 'Changed')):
            with self.assertRaises(ValueError):
                restore_existing_html(before, bad, 'neighborhood', child)

    def test_high1_after_high2_order_or_duplicate_is_rejected(self):
        before, after, child, anchor = self.fixture()
        bad = after.replace(anchor, '').replace('</nav>', anchor + '</nav>')
        with self.assertRaises(ValueError):
            restore_existing_html(before, bad, 'neighborhood', child)
        with self.assertRaises(ValueError):
            restore_existing_html(before, after.replace(anchor, anchor * 2), 'neighborhood', child)

    def test_actual_high1_grade_not_inferred_from_other_grades(self):
        center = {'subjects': {'영어': {'grades': ['중3', '고2']}}, 'availableSubjects': ['영어']}
        self.assertNotIn('고1', scoped_grades(center, {}, '영어'))
        center['subjects']['영어']['grades'].append('고1')
        self.assertIn('고1', scoped_grades(center, {}, '영어'))
        ref = {'operations': {'subjectDisplay': {'영어': {'status': 'scope_confirmation_needed', 'includeInUnqualifiedAvailableSubjects': False}}}}
        self.assertEqual(scoped_grades(center, ref, '영어'), [])


if __name__ == '__main__':
    unittest.main()
