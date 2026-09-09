"""Original checks plus middle/high-grade navigation regression fixtures.

Run: python tools/test_branch_child_navigation.py
No website HTML, CSS, source data, or deployment is changed.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from html import unescape
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import unquote, urlsplit

import branch_child_navigation as navigation


class BranchGeneratorPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (navigation.ROOT / 'tools/generate_branch_pages.py').read_text(encoding='utf-8')
        tree = ast.parse(cls.source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'center_page')
        cls.center_source = ast.get_source_segment(cls.source, function)

    def test_01_generator_syntax(self):
        self.assertIsInstance(ast.parse(self.source), ast.Module)

    def test_02_neighborhood_block_follows_faq(self):
        source = self.center_source
        self.assertLess(source.index("body += panel('questions'"), source.index('body += neighborhood_navigation(children)'))
        self.assertLess(source.index('body += neighborhood_navigation(children)'), source.index("body += panel('other-centers'"))
        self.assertEqual(source.count('body += neighborhood_navigation(children)'), 1)

    def test_03_hero_shortcut_retained(self):
        self.assertIn('branch-neighborhood-jump', self.center_source)
        self.assertIn('href="#neighborhood-pages"', self.center_source)

    def test_04_toc_order(self):
        self.assertIn("'questions', 'neighborhood-pages', 'learning-space'", self.center_source)

    def test_05_schema_item_list_follows_faq(self):
        self.assertLess(self.center_source.index("graph.append({'@type': 'FAQPage'"),
                        self.center_source.index("graph.append({'@type': 'ItemList'"))


class ChildNavigationTests(unittest.TestCase):
    parent = '/지점안내/서울/명일점/명일동영어학원/'

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='branch-child-navigation-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = self.root / navigation.MANIFEST

    def record(self, grade):
        return {'path': self.parent + grade + '/', 'parentPath': self.parent,
                'centerId': 'center-row-054', 'locality': '명일동', 'subject': '영어',
                'grade': grade, 'title': '명일동 ' + grade + ' 영어학원'}

    def save_manifest(self, records):
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.write_text(json.dumps({'pages': records}, ensure_ascii=False), encoding='utf-8')

    def save_destinations(self, records):
        for record in records:
            file = self.root / record['path'].strip('/') / 'index.html'
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('<h1>temporary fixture</h1>', encoding='utf-8')

    def test_06_empty_behavior(self):
        self.assertEqual(navigation.child_navigation_html([]), '')
        self.assertIsNone(navigation.child_item_list([]))
        self.assertEqual(navigation.load_child_pages(self.parent, root=self.root), [])

    def test_07_grade_ordering(self):
        records = [self.record('고2'), self.record('초1'), self.record('중3')]
        self.save_manifest(records)
        self.save_destinations(records)
        self.assertEqual([r['grade'] for r in navigation.load_child_pages(self.parent, root=self.root)], ['초1', '중3', '고2'])
        html = navigation.child_navigation_html(records)
        self.assertLess(html.index('명일동 초1'), html.index('명일동 중3'))
        self.assertLess(html.index('명일동 중3'), html.index('명일동 고2'))

    def test_08_html_schema_link_parity(self):
        records = [self.record('고2'), self.record('초1'), self.record('중3')]
        html = navigation.child_navigation_html(records)
        schema = navigation.child_item_list(records)
        self.assertIn('id="child-pages"', html)
        self.assertIn('class="branch-child-links"', html)
        self.assertEqual(html.count('class="branch-child-link"'), 3)
        self.assertEqual([unescape(path) for path in re.findall(r'href="([^"]+)"', html)],
                         [unquote(urlsplit(item['url']).path) for item in schema['itemListElement']])
        self.assertEqual([item['name'] for item in schema['itemListElement']],
                         ['명일동 초1 영어학원', '명일동 중3 영어학원', '명일동 고2 영어학원'])

    def test_09_unsafe_hierarchy_and_invalid_grade_rejected(self):
        invalid = [dict(self.record('고2'), path=self.parent + '../고2/'),
                   dict(self.record('고2'), path=self.parent + '%EA%B3%A02/'),
                   dict(self.record('고2'), grade='고4'),
                   dict(self.record('고2'), parentPath='/지점안내/경기/명일점/명일동영어학원/')]
        for record in invalid:
            with self.subTest(record=record), self.assertRaises(ValueError):
                navigation.child_navigation_html([record])

    def test_10_duplicate_and_identity_conflicts_rejected(self):
        invalid = [[self.record('고2'), self.record('고2')],
                   [self.record('고2'), dict(self.record('초1'), centerId='other')]]
        for records in invalid:
            with self.subTest(records=records), self.assertRaises(ValueError):
                navigation.child_navigation_html(records)

    def test_11_missing_file_rejected(self):
        self.save_manifest([self.record('고2')])
        with self.assertRaises(ValueError):
            navigation.load_child_pages(self.parent, root=self.root)

    def test_12_manifest_reload_after_change(self):
        records = [self.record('고2'), self.record('초1'), self.record('중3')]
        self.save_manifest(records)
        self.save_destinations(records)
        self.assertEqual(len(navigation.load_child_pages(self.parent, root=self.root)), 3)
        previous = self.manifest.stat()
        self.save_manifest([self.record('고2')])
        os.utime(self.manifest, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
        self.assertEqual([r['grade'] for r in navigation.load_child_pages(self.parent, root=self.root)], ['고2'])

    def test_13_return_value_isolated_from_cache(self):
        records = [self.record('고2')]
        self.save_manifest(records)
        self.save_destinations(records)
        result = navigation.load_child_pages(self.parent, root=self.root)
        original = deepcopy(result)
        result[0]['title'] = 'not persisted'
        self.assertEqual(navigation.load_child_pages(self.parent, root=self.root), original)

    def test_14_existing_high2_and_new_high1_have_stable_order(self):
        # Use a real reviewed 고2 manifest record; only the new grade fixture is
        # projected. Real website HTML remains read-only.
        real = json.loads((navigation.ROOT / navigation.MANIFEST).read_text(encoding='utf-8'))['pages']
        high2 = deepcopy(next(r for r in real if r['parentPath'] == self.parent and r['grade'] == '고2'))
        high1 = dict(high2, grade='고1', path=self.parent + '고1/', title='명일동 고1 영어학원')
        self.save_manifest([high2, high1])
        self.save_destinations([high2, high1])
        children = navigation.load_child_pages(self.parent, root=self.root)
        self.assertEqual([r['grade'] for r in children], ['고1', '고2'])
        self.assertEqual(children[1], high2)
        self.assertTrue(all(r['parentPath'] == self.parent and r['path'] == self.parent + r['grade'] + '/' for r in children))
        html = navigation.child_navigation_html(children)
        self.assertLess(html.index('명일동 고1'), html.index('명일동 고2'))
        schema = navigation.child_item_list(children)
        self.assertEqual([unquote(urlsplit(item['url']).path) for item in schema['itemListElement']],
                         [self.parent + '고1/', self.parent + '고2/'])

    def test_15_both_grades_filter_to_exact_neighborhood_subject_parent(self):
        english = [self.record('고2'), self.record('고1')]
        math_parent = self.parent.replace('영어학원/', '수학학원/')
        math = [dict(self.record(grade), parentPath=math_parent, path=math_parent + grade + '/',
                     subject='수학', title='명일동 ' + grade + ' 수학학원') for grade in ('고2', '고1')]
        self.save_manifest(english + math)
        self.save_destinations(english + math)
        for parent, subject in ((self.parent, '영어'), (math_parent, '수학')):
            children = navigation.load_child_pages(parent, root=self.root)
            self.assertEqual([r['grade'] for r in children], ['고1', '고2'])
            self.assertEqual({r['subject'] for r in children}, {subject})
            self.assertTrue(all(r['parentPath'] == parent for r in children))

    def test_16_high1_cannot_be_nested_under_high2(self):
        nested_parent = self.parent + '고2/'
        record = dict(self.record('고1'), parentPath=nested_parent, path=nested_parent + '고1/')
        with self.assertRaises(ValueError):
            navigation.child_navigation_html([record])

    def test_17_cache_refresh_adds_high1_without_changing_high2(self):
        high2, high1 = self.record('고2'), self.record('고1')
        self.save_manifest([high2])
        self.save_destinations([high2, high1])
        before = navigation.load_child_pages(self.parent, root=self.root)
        self.assertEqual(before, [high2])
        stat = self.manifest.stat()
        self.save_manifest([high2, high1])
        os.utime(self.manifest, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        after = navigation.load_child_pages(self.parent, root=self.root)
        self.assertEqual(after, [high1, high2])
        self.assertEqual(after[1], before[0])

    def test_18_middle_grades_before_existing_high_grades(self):
        real = json.loads((navigation.ROOT / navigation.MANIFEST).read_text(encoding='utf-8'))['pages']
        high = [deepcopy(next(r for r in real if r['parentPath'] == self.parent and r['grade'] == grade))
                for grade in ('고1', '고2')]
        middle = [self.record(grade) for grade in ('중3', '중1', '중2')]
        self.save_manifest(high[::-1] + middle)
        self.save_destinations(high + middle)
        children = navigation.load_child_pages(self.parent, root=self.root)
        expected = ['중1', '중2', '중3', '고1', '고2']
        self.assertEqual([r['grade'] for r in children], expected)
        self.assertEqual(children[-2:], high)
        html = navigation.child_navigation_html(children)
        self.assertEqual([unescape(path) for path in re.findall(r'href="([^"]+)"', html)],
                         [self.parent + grade + '/' for grade in expected])
        self.assertEqual([unquote(urlsplit(item['url']).path) for item in navigation.child_item_list(children)['itemListElement']],
                         [self.parent + grade + '/' for grade in expected])

    def test_19_each_middle_grade_is_an_immediate_subject_child(self):
        records = []
        for subject in ('영어', '수학'):
            parent = self.parent.replace('영어학원/', subject + '학원/')
            records += [dict(self.record(grade), subject=subject, parentPath=parent, path=parent + grade + '/',
                             title='명일동 ' + grade + ' ' + subject + '학원') for grade in ('중3', '중1', '중2')]
        self.save_manifest(records)
        self.save_destinations(records)
        for subject in ('영어', '수학'):
            parent = self.parent.replace('영어학원/', subject + '학원/')
            children = navigation.load_child_pages(parent, root=self.root)
            self.assertEqual([r['grade'] for r in children], ['중1', '중2', '중3'])
            self.assertTrue(all(r['subject'] == subject and r['parentPath'] == parent
                                and r['path'] == parent + r['grade'] + '/' for r in children))
            for child in children:
                nested = dict(child, parentPath=parent + '고2/', path=parent + '고2/' + child['grade'] + '/')
                with self.subTest(subject=subject, grade=child['grade']), self.assertRaises(ValueError):
                    navigation.child_navigation_html([nested])

    def test_20_middle_append_refresh_keeps_existing_high_records(self):
        higher = [self.record('고1'), self.record('고2')]
        self.save_manifest(higher)
        self.save_destinations(higher)
        before = navigation.load_child_pages(self.parent, root=self.root)
        for index, grade in enumerate(('중1', '중2', '중3'), 1):
            middle = [self.record(g) for g in ('중1', '중2', '중3')[:index]]
            stat = self.manifest.stat()
            self.save_manifest(higher + middle)
            self.save_destinations(middle)
            os.utime(self.manifest, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
            children = navigation.load_child_pages(self.parent, root=self.root)
            self.assertEqual([r['grade'] for r in children], [r['grade'] for r in middle] + ['고1', '고2'])
            self.assertEqual(children[-2:], before)

    def test_21_elementary56_before_existing_middle_high_grades(self):
        real = json.loads((navigation.ROOT / navigation.MANIFEST).read_text(encoding='utf-8'))['pages']
        prior_grades = ('중1', '중2', '중3', '고1', '고2')
        previous = [deepcopy(next(r for r in real if r['parentPath'] == self.parent and r['grade'] == grade))
                    for grade in prior_grades]
        elementary = [self.record('초6'), self.record('초5')]
        self.save_manifest(previous[::-1] + elementary)
        self.save_destinations(previous + elementary)
        children = navigation.load_child_pages(self.parent, root=self.root)
        expected = ['초5', '초6', *prior_grades]
        self.assertEqual([r['grade'] for r in children], expected)
        self.assertEqual(children[2:], previous)
        html_paths = [unescape(path) for path in re.findall(r'href="([^"]+)"', navigation.child_navigation_html(children))]
        schema_paths = [unquote(urlsplit(item['url']).path) for item in navigation.child_item_list(children)['itemListElement']]
        self.assertEqual(html_paths, [self.parent + grade + '/' for grade in expected])
        self.assertEqual(schema_paths, html_paths)

    def test_22_elementary56_are_immediate_children_for_both_subjects(self):
        records = []
        for subject in ('영어', '수학'):
            parent = self.parent.replace('영어학원/', subject + '학원/')
            records += [dict(self.record(grade), subject=subject, parentPath=parent, path=parent + grade + '/',
                             title='명일동 ' + grade + ' ' + subject + '학원') for grade in ('초6', '초5')]
        self.save_manifest(records)
        self.save_destinations(records)
        for subject in ('영어', '수학'):
            parent = self.parent.replace('영어학원/', subject + '학원/')
            children = navigation.load_child_pages(parent, root=self.root)
            self.assertEqual([r['grade'] for r in children], ['초5', '초6'])
            self.assertTrue(all(r['subject'] == subject and r['parentPath'] == parent
                                and r['path'] == parent + r['grade'] + '/' for r in children))
            for child in children:
                for nested_grade in ('초5', '초6', '중1', '중2', '중3', '고1', '고2'):
                    nested_parent = parent + nested_grade + '/'
                    with self.subTest(subject=subject, grade=child['grade'], nested=nested_grade), self.assertRaises(ValueError):
                        navigation.child_navigation_html([dict(child, parentPath=nested_parent,
                                                              path=nested_parent + child['grade'] + '/')])

    def test_23_elementary56_cache_append_preserves_previous_five_grades(self):
        previous = [self.record(grade) for grade in ('중1', '중2', '중3', '고1', '고2')]
        self.save_manifest(previous)
        self.save_destinations(previous)
        before = navigation.load_child_pages(self.parent, root=self.root)
        for index in (1, 2):
            elementary = [self.record(grade) for grade in ('초5', '초6')[:index]]
            stat = self.manifest.stat()
            self.save_manifest(previous + elementary)
            self.save_destinations(elementary)
            os.utime(self.manifest, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
            after = navigation.load_child_pages(self.parent, root=self.root)
            self.assertEqual(after[:index], elementary)
            self.assertEqual(after[index:], before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
