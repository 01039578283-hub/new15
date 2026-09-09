"""Fail-closed boundaries for high2 navigation and sentence-selection audit."""
import copy
import json
import unittest

from audit_branch_high2_pages import (complete_sentence_selection, exact_child_panel,
                                     restore_existing_html, reviewed_school_lists, scoped_grades, url)


def html(nodes, content):
    return ('<html><head><title>Keep title</title><link rel="canonical" href="' + url('/지점안내/서울/시험점/시험동영어학원/')
            + '"><script type="application/ld+json">' + json.dumps({'@graph': nodes}, ensure_ascii=False)
            + '</script></head><body>' + content + '</body></html>')


class High2AuditTests(unittest.TestCase):
    def test_school_filter_preserves_original_high_names_and_history(self):
        before = '제공된 학교 정보에는 서현초, 서현중, 서원고, 청주외고가 포함되어 있습니다. 학교별 시험 경향을 단정해서는 안 됩니다.'
        after = '제공된 학교 정보에는 서원고, 청주외고가 포함되어 있습니다. 학교별 시험 경향을 단정해서는 안 됩니다.'
        self.assertEqual(reviewed_school_lists(before), after)
        history = '제공된 학교 정보에는 서현중, 서원고가 있으며 중학교 때 학습 이력을 함께 살펴보세요.'
        self.assertEqual(reviewed_school_lists(history), history)

    def test_center_movement_does_not_hide_content_or_schema_edits(self):
        canonical = url('/지점안내/서울/시험점/시험동영어학원/')
        nodes = [{'@type': 'WebPage', '@id': canonical + '#webpage', 'hasPart': [
            {'@id': canonical + '#neighborhood-pages'}, {'@id': canonical + '#questions'}]}]
        panel = '<section id="neighborhood-pages"><h2>Keep links</h2></section>'
        faq = '<section id="questions"><h2>Keep FAQ</h2><p>Keep answer</p></section>'
        before = html(nodes, panel + '<nav class="branch-toc"></nav>' + faq)
        expected_nodes = copy.deepcopy(nodes)
        expected_nodes[0]['hasPart'].reverse()
        after = html(expected_nodes, '<nav class="branch-toc"><a href="#neighborhood-pages">동네별 학습 안내</a></nav>' + faq + panel)
        self.assertTrue(restore_existing_html(before, after, 'center'))
        for altered in (after.replace('Keep answer', 'Changed answer'), after.replace('Keep title', 'Changed title'),
                        after.replace('Keep links', 'Wrong links')):
            with self.assertRaises(ValueError):
                restore_existing_html(before, altered, 'center')

    def test_child_panel_has_exact_source_title_and_target(self):
        child = {'path': '/지점안내/서울/시험점/시험동영어학원/고2/', 'title': '시험동 고2 영어학원'}
        canonical = url('/지점안내/서울/시험점/시험동영어학원/')
        nodes = [{'@type': 'WebPage', '@id': canonical + '#webpage', 'hasPart': [{'@id': canonical + '#questions'}]}]
        faq = '<section id="questions"><p>Keep answer</p></section>'
        before = html(nodes, '<nav id="article-toc"></nav>' + faq)
        new = copy.deepcopy(nodes)
        new[0]['hasPart'].append({'@id': canonical + '#child-pages'})
        new.append({'@type': 'ItemList', '@id': canonical + '#child-pages', 'name': '학년별 학습 안내', 'numberOfItems': 1,
                    'itemListElement': [{'@type': 'ListItem', 'position': 1, 'name': child['title'], 'url': url(child['path'])}],
                    'isPartOf': {'@id': canonical + '#webpage'}})
        after = html(new, '<nav id="article-toc"><a href="#child-pages">학년별 학습 안내</a></nav>' + faq + exact_child_panel(child))
        self.assertTrue(restore_existing_html(before, after, 'neighborhood', child))
        with self.assertRaises(ValueError):
            restore_existing_html(before, after.replace('/고2/', '/고1/'), 'neighborhood', child)

    def test_high2_is_not_inferred_from_subject_or_high1(self):
        center = {'subjects': {'영어': {'grades': ['중3', '고1']}}, 'availableSubjects': ['영어']}
        self.assertNotIn('고2', scoped_grades(center, {}, '영어'))
        center['subjects']['영어']['grades'].append('고2')
        self.assertIn('고2', scoped_grades(center, {}, '영어'))
        override = {'operations': {'subjectDisplay': {'영어': {'status': 'scope_confirmation_needed', 'includeInUnqualifiedAvailableSubjects': False}}}}
        self.assertEqual(scoped_grades(center, override, '영어'), [])

    def test_intro_selection_rejects_new_copy_and_lost_example(self):
        sentence = '고2 영어에서는 문장의 주어와 동사를 표시한 다음 목적어가 필요한 동사와 그렇지 않은 동사의 차이를 실제 문장에서 확인하고, 틀린 문제의 판단 근거를 설명하면서 문장 구조를 이해하는 과정부터 살펴봅니다.'
        before = sentence + ' 상담에서는 영어와 수학의 시간 배분을 함께 비교해 보세요.'
        self.assertTrue(complete_sentence_selection(before, sentence))
        self.assertFalse(complete_sentence_selection(before, sentence.replace('주어와 동사', '학생의 성적')))
        self.assertFalse(complete_sentence_selection(sentence + ' 24개 문장을 기록해 상담에서 확인하세요.', sentence))


if __name__ == '__main__':
    unittest.main()
