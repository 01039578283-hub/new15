import unittest
import json
from copy import deepcopy
from pathlib import Path
import tempfile
from unittest.mock import patch
from bs4 import BeautifulSoup
from generate_branch_grade_pages import grade_path, grade_school_row
import generate_branch_grade_pages as generation
from generate_branch_pages import ROOT, load_branch_data, url
from generate_branch_neighborhood_pages import render
from branch_reader_facts import _confirmed_grades


class GradeGenerationTests(unittest.TestCase):
    def setUp(self):
        self.parent = {'path': '/지점안내/대구/신월성점/신월성수학학원/', 'locality': '신월성', 'subject': '수학'}

    def test_grade_url_under_existing_parent(self):
        self.assertEqual(grade_path(self.parent, '고2'), self.parent['path'] + '고2/')
        self.assertEqual(grade_path(self.parent, '고1'), self.parent['path'] + '고1/')

    def test_invalid_grade_rejected(self):
        for grade in ('../고2', '고2/', '고4', '고2?x', ''):
            with self.assertRaises(ValueError):
                grade_path(self.parent, grade)

    def test_wrong_parent_rejected(self):
        for path in ('/지점안내/대구/신월성점/', '/다른메뉴/대구/신월성점/신월성수학학원/', '/지점안내/대구/신월성점/다른동수학학원/'):
            with self.assertRaises(ValueError):
                grade_path(dict(self.parent, path=path), '고2')

    def test_school_levels_only_current_grade_without_mutation(self):
        row = {'targetSchools': {'elementary': ['초등학교'], 'middle': ['중학교'], 'high': ['고등학교']}}
        filtered = grade_school_row(row, '고2')
        self.assertEqual(filtered['targetSchools'], {'high': ['고등학교']})
        self.assertEqual(len(row['targetSchools']), 3)
        filtered['targetSchools']['high'].append('추가')
        self.assertEqual(row['targetSchools']['high'], ['고등학교'])

    def test_empty_high_school_does_not_invent_a_list(self):
        self.assertEqual(grade_school_row({'targetSchools': {'middle': ['중학교']}}, '고2')['targetSchools'], {})

    def test_high1_and_high2_keep_only_same_high_school_list(self):
        row = {'sourceRow': 'fixture', 'targetSchools': {'elementary': ['초등학교'], 'middle': ['중학교'],
               'high': ['확정고등학교', '청솔고등학교 [2025 통계 휴·폐교]']}}
        before = deepcopy(row)
        for grade in ('고1', '고2'):
            filtered = grade_school_row(row, grade)
            self.assertEqual(filtered['targetSchools'], {'high': before['targetSchools']['high']})
            self.assertEqual(grade_school_row({'targetSchools': {'middle': ['중학교']}}, grade)['targetSchools'], {})
            filtered['targetSchools']['high'].append('fixture mutation')
            self.assertEqual(row, before)

    def test_high1_archive_snapshot_does_not_replace_high2(self):
        with tempfile.TemporaryDirectory(prefix='branch-grade-source-test-') as tmp:
            source, data = Path(tmp) / 'incoming', Path(tmp) / 'data'
            source.mkdir()
            (data / 'sources').mkdir(parents=True)
            high2 = data / 'sources/고2 영어학원.zip'
            high2.write_bytes(b'unchanged high2 snapshot fixture')
            high1 = source / '고1 영어학원.zip'
            high1.write_bytes(b'new high1 source fixture')
            with patch.object(generation, 'SOURCE', source), patch.object(generation, 'DATA', data):
                saved = generation.source_snapshot('고1', '영어')
                self.assertEqual(saved.read_bytes(), high1.read_bytes())
                self.assertEqual(high2.read_bytes(), b'unchanged high2 snapshot fixture')
                self.assertEqual(generation.source_snapshot('고1', '영어'), saved)
                high1.write_bytes(b'changed source must require review')
                with self.assertRaises(ValueError):
                    generation.source_snapshot('고1', '영어')
                self.assertEqual(saved.read_bytes(), b'new high1 source fixture')
                self.assertEqual(high2.read_bytes(), b'unchanged high2 snapshot fixture')

    def test_three_middle_grade_paths_are_siblings_not_nested(self):
        for grade in ('중1', '중2', '중3'):
            with self.subTest(grade=grade):
                self.assertEqual(grade_path(self.parent, grade), self.parent['path'] + grade + '/')
                for previous in ('중1', '중2', '중3', '고1', '고2'):
                    with self.assertRaises(ValueError):
                        grade_path(dict(self.parent, path=self.parent['path'] + previous + '/'), grade)

    def test_middle_school_filter_keeps_only_middle_without_mutation(self):
        row = {'sourceRow': 'fixture', 'targetSchools': {'elementary': ['초등학교'],
               'middle': ['확정중학교', '청솔중학교 [2025 통계 휴·폐교]'], 'high': ['고등학교']}}
        before = deepcopy(row)
        for grade in ('중1', '중2', '중3'):
            with self.subTest(grade=grade):
                filtered = grade_school_row(row, grade)
                self.assertEqual(filtered['targetSchools'], {'middle': before['targetSchools']['middle']})
                self.assertEqual(grade_school_row({'targetSchools': {'high': ['고등학교']}}, grade)['targetSchools'], {})
                filtered['targetSchools']['middle'].append('fixture mutation')
                self.assertEqual(row, before)

    def test_six_middle_snapshots_preserve_all_existing_high_sources(self):
        with tempfile.TemporaryDirectory(prefix='branch-middle-source-test-') as tmp:
            source, data = Path(tmp) / 'incoming', Path(tmp) / 'data'
            source.mkdir()
            (data / 'sources').mkdir(parents=True)
            preserved = {}
            for grade in ('고1', '고2'):
                for subject in ('영어', '수학'):
                    file = data / 'sources' / (grade + ' ' + subject + '학원.zip')
                    file.write_bytes(('immutable fixture: ' + grade + subject).encode('utf-8'))
                    preserved[file] = file.read_bytes()
            incoming = []
            for grade in ('중1', '중2', '중3'):
                for subject in ('영어', '수학'):
                    file = source / (grade + ' ' + subject + '학원.zip')
                    content = ('new fixture: ' + grade + subject).encode('utf-8')
                    file.write_bytes(content)
                    incoming.append((grade, subject, file, content))
            with patch.object(generation, 'SOURCE', source), patch.object(generation, 'DATA', data):
                for grade, subject, file, content in incoming:
                    saved = generation.source_snapshot(grade, subject)
                    self.assertEqual(saved.read_bytes(), content)
                    preserved[saved] = content
                    self.assertEqual(generation.source_snapshot(grade, subject), saved)
                    file.write_bytes(b'changed source must not replace snapshot')
                    with self.assertRaises(ValueError):
                        generation.source_snapshot(grade, subject)
                    for existing, expected in preserved.items():
                        self.assertEqual(existing.read_bytes(), expected)


    def test_elementary56_paths_are_immediate_not_nested(self):
        for grade in ('초5', '초6'):
            with self.subTest(grade=grade):
                self.assertEqual(grade_path(self.parent, grade), self.parent['path'] + grade + '/')
                for previous in ('초5', '초6', '중1', '중2', '중3', '고1', '고2'):
                    with self.assertRaises(ValueError):
                        grade_path(dict(self.parent, path=self.parent['path'] + previous + '/'), grade)

    def test_elementary56_school_filter_is_immutable(self):
        row = {'sourceRow': 'fixture', 'targetSchools': {'elementary': ['확정초등학교', '추가초등학교 [후보·지역 확인 필요]'],
                                                        'middle': ['중학교 표본'], 'high': ['고등학교 표본']}}
        before = deepcopy(row)
        for grade in ('초5', '초6'):
            with self.subTest(grade=grade):
                filtered = grade_school_row(row, grade)
                self.assertEqual(filtered['targetSchools'], {'elementary': before['targetSchools']['elementary']})
                self.assertEqual(grade_school_row({'targetSchools': {'middle': ['중학교 표본'], 'high': ['고등학교 표본']}}, grade)['targetSchools'], {})
                filtered['targetSchools']['elementary'].append('fixture mutation')
                self.assertEqual(row, before)

    def test_four_elementary56_snapshots_preserve_previous_ten_sources(self):
        with tempfile.TemporaryDirectory(prefix='branch-elementary56-source-test-') as tmp:
            source, data = Path(tmp) / 'incoming', Path(tmp) / 'data'
            source.mkdir()
            (data / 'sources').mkdir(parents=True)
            preserved = {}
            for grade in ('중1', '중2', '중3', '고1', '고2'):
                for subject in ('영어', '수학'):
                    file = data / 'sources' / (grade + ' ' + subject + '학원.zip')
                    file.write_bytes(('immutable fixture: ' + grade + subject).encode('utf-8'))
                    preserved[file] = file.read_bytes()
            self.assertEqual(len(preserved), 10)
            with patch.object(generation, 'SOURCE', source), patch.object(generation, 'DATA', data):
                for grade in ('초5', '초6'):
                    for subject in ('영어', '수학'):
                        file = source / (grade + ' ' + subject + '학원.zip')
                        content = ('new fixture: ' + grade + subject).encode('utf-8')
                        file.write_bytes(content)
                        saved = generation.source_snapshot(grade, subject)
                        self.assertEqual(saved.read_bytes(), content)
                        preserved[saved] = content
                        self.assertEqual(generation.source_snapshot(grade, subject), saved)
                        file.write_bytes(b'changed source must not replace snapshot')
                        with self.assertRaises(ValueError):
                            generation.source_snapshot(grade, subject)
                        for existing, expected in preserved.items():
                            self.assertEqual(existing.read_bytes(), expected)
                self.assertEqual(len(preserved), 14)


class GradeRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, centers, reference = load_branch_data()
        cls.centers = {c['id']: c for c in centers}
        cls.reference = reference['centers']
        cls.parents = json.loads((ROOT / 'tools/data/branch-neighborhoods/pages.json').read_text(encoding='utf-8'))['pages']

    def rendered(self, confirmed, grade='고2', parent=None, school_row=None):
        parent = parent or next(p for p in self.parents if (grade in _confirmed_grades(self.centers[p['centerId']], self.reference[p['centerId']], p['subject'])) == confirmed)
        center, reference = self.centers[parent['centerId']], self.reference[parent['centerId']]
        title = parent['locality'] + ' ' + grade + ' ' + parent['subject'] + '학원'
        manuscript = {'title': title, 'subject': parent['subject'], 'locality': parent['locality'], 'meta': '고2 학습 준비 안내입니다.',
                      'intro': '풀이 과정을 확인해 보세요.', 'sections': [{'heading': '학습 과정', 'paragraphs': ['최근 풀이를 정리합니다.']}],
                      'faq': [{'question': '무엇을 준비하나요?', 'answer': '최근 풀이를 준비합니다.'}], 'cases': ['보호자라면 질문을 메모하겠습니다.']}
        manuscript['meta'] = grade + ' 학습 준비 안내입니다.'
        context = {'grade': grade, 'path': parent['path'] + grade + '/', 'parentPath': parent['path'], 'parentTitle': parent['title']}
        path, html = render(center, reference, manuscript, parent['representative'], school_row or {}, [], page_context=context)
        self.assertEqual(path, context['path'])
        soup = BeautifulSoup(html, 'html.parser')
        graph = json.loads(soup.select_one('script[type="application/ld+json"]').string)['@graph']
        return parent, context, soup, graph

    def test_exact_grade_scope_and_parent_relationship(self):
        for confirmed in (True, False):
            with self.subTest(confirmed=confirmed):
                parent, context, soup, graph = self.rendered(confirmed)
                services = [n for n in graph if n.get('@type') == 'Service']
                self.assertEqual(len(services), int(confirmed))
                self.assertEqual(bool(soup.select_one('.branch-child-hero .branch-scope-notice')), not confirmed)
                web = next(n for n in graph if n.get('@type') == 'WebPage')
                self.assertEqual(web['isPartOf'], {'@id': url(parent['path']) + '#webpage'})
                crumb = next(n for n in graph if n.get('@type') == 'BreadcrumbList')['itemListElement']
                self.assertEqual(len(crumb), 6)
                self.assertEqual(crumb[-2]['item'], url(parent['path']))
                self.assertEqual(crumb[-1]['item'], url(context['path']))

    def test_media_order_and_faq_match(self):
        _, _, soup, graph = self.rendered(True)
        images = soup.select('.branch-primary-media img')
        self.assertEqual(len(images), 3)
        self.assertEqual(images[0]['style'], 'display:none;')
        self.assertTrue(images[0]['alt'].endswith('대표'))
        self.assertTrue(images[1]['alt'].endswith('본문'))
        self.assertTrue(images[2]['alt'].endswith('지도'))
        self.assertNotIn('display:none', images[1].get('style', ''))
        self.assertNotIn('display:none', images[2].get('style', ''))
        faq = next(n for n in graph if n.get('@type') == 'FAQPage')['mainEntity'][0]
        self.assertEqual(faq['name'], soup.select_one('#questions summary').text)
        self.assertEqual(faq['acceptedAnswer']['text'], soup.select_one('#questions p').text)

    def test_high1_scope_and_immediate_parent_are_not_high2(self):
        for confirmed in (True, False):
            with self.subTest(confirmed=confirmed):
                parent, context, soup, graph = self.rendered(confirmed, grade='고1')
                services = [n for n in graph if n.get('@type') == 'Service']
                self.assertEqual(len(services), int(confirmed))
                self.assertEqual(bool(soup.select_one('.branch-child-hero .branch-scope-notice')), not confirmed)
                for type_ in ('WebPage', 'Article'):
                    node = next(n for n in graph if n.get('@type') == type_)
                    self.assertEqual(node['isPartOf'], {'@id': url(parent['path']) + '#webpage'})
                article = next(n for n in graph if n.get('@type') == 'Article')
                self.assertEqual(article['educationalLevel'], '고1')
                crumbs = next(n for n in graph if n.get('@type') == 'BreadcrumbList')['itemListElement']
                self.assertEqual(len(crumbs), 6)
                self.assertEqual(crumbs[-2]['item'], url(parent['path']))
                self.assertEqual(crumbs[-1]['item'], url(context['path']))
                self.assertNotIn('/고2/', context['parentPath'])
                self.assertIn('고1', soup.h1.get_text())
                self.assertEqual([image['alt'].split()[-1] for image in soup.select('.branch-primary-media img')], ['대표', '본문', '지도'])

    def test_real_high1_only_scope_yields_service_for_high1_not_high2(self):
        parent = next(p for p in self.parents
                      if '고1' in _confirmed_grades(self.centers[p['centerId']], self.reference[p['centerId']], p['subject'])
                      and '고2' not in _confirmed_grades(self.centers[p['centerId']], self.reference[p['centerId']], p['subject']))
        for grade, confirmed in (('고1', True), ('고2', False)):
            with self.subTest(grade=grade, locality=parent['locality']):
                _, context, soup, graph = self.rendered(confirmed, grade=grade, parent=parent)
                self.assertEqual(len([n for n in graph if n.get('@type') == 'Service']), int(confirmed))
                self.assertEqual(bool(soup.select_one('.branch-child-hero .branch-scope-notice')), not confirmed)
                self.assertEqual(context['parentPath'], parent['path'])

    def test_both_grades_render_only_high_school_names(self):
        row = {'targetSchools': {'elementary': ['초등학교 표본'], 'middle': ['중학교 표본'],
                                'high': ['확정고등학교', '추가고등학교 [후보·지역 확인 필요]']}}
        for grade in ('고1', '고2'):
            with self.subTest(grade=grade):
                _, _, soup, _ = self.rendered(True, grade=grade, school_row=grade_school_row(row, grade))
                self.assertEqual([node.get_text() for node in soup.select('#schools li')], ['확정고등학교', '추가고등학교'])
                self.assertNotIn('확인 필요', soup.select_one('#schools').get_text())

    def test_each_middle_grade_has_exact_scope_and_immediate_parent(self):
        for grade in ('중1', '중2', '중3'):
            for confirmed in (True, False):
                with self.subTest(grade=grade, confirmed=confirmed):
                    parent, context, soup, graph = self.rendered(confirmed, grade=grade)
                    self.assertEqual(len([n for n in graph if n.get('@type') == 'Service']), int(confirmed))
                    self.assertEqual(bool(soup.select_one('.branch-child-hero .branch-scope-notice')), not confirmed)
                    for type_ in ('WebPage', 'Article'):
                        self.assertEqual(next(n for n in graph if n.get('@type') == type_)['isPartOf'],
                                         {'@id': url(parent['path']) + '#webpage'})
                    self.assertEqual(next(n for n in graph if n.get('@type') == 'Article')['educationalLevel'], grade)
                    crumbs = next(n for n in graph if n.get('@type') == 'BreadcrumbList')['itemListElement']
                    self.assertEqual(len(crumbs), 6)
                    self.assertEqual(crumbs[-2]['item'], url(parent['path']))
                    self.assertEqual(crumbs[-1]['item'], url(context['path']))
                    self.assertEqual(context['path'], parent['path'] + grade + '/')
                    self.assertIn(grade, soup.h1.get_text())

    def test_one_middle_grade_scope_is_not_reused_for_other_grades(self):
        # Current real data gives the same availability across 중1~중3. These
        # isolated copies catch accidental middle-wide or high2 scope checks.
        parent = self.parents[0]
        cid, subject = parent['centerId'], parent['subject']
        original_center, original_reference = deepcopy(self.centers[cid]), deepcopy(self.reference[cid])
        for offered in ('중1', '중2', '중3'):
            center, reference = deepcopy(original_center), deepcopy(original_reference)
            center['subjects'][subject]['grades'] = [offered]
            reference['operations']['subjectDisplay'][subject] = {
                'status': 'recorded', 'includeInUnqualifiedAvailableSubjects': True,
                'sourceGrades': [offered], 'summary': offered, 'detail': ''}
            with patch.dict(self.centers, {cid: center}), patch.dict(self.reference, {cid: reference}):
                for queried in ('중1', '중2', '중3', '고2'):
                    expected = offered == queried
                    with self.subTest(offered=offered, queried=queried):
                        _, _, soup, graph = self.rendered(expected, grade=queried, parent=parent)
                        self.assertEqual(len([n for n in graph if n.get('@type') == 'Service']), int(expected))
                        self.assertEqual(bool(soup.select_one('.branch-child-hero .branch-scope-notice')), not expected)
        self.assertEqual(self.centers[cid], original_center)
        self.assertEqual(self.reference[cid], original_reference)

    def test_three_middle_grades_render_only_middle_school_names(self):
        row = {'targetSchools': {'elementary': ['초등학교 표본'],
                                'middle': ['확정중학교', '추가중학교 [후보·지역 확인 필요]'], 'high': ['고등학교 표본']}}
        before = deepcopy(row)
        for grade in ('중1', '중2', '중3'):
            with self.subTest(grade=grade):
                _, _, soup, _ = self.rendered(True, grade=grade, school_row=grade_school_row(row, grade))
                self.assertEqual([node.get_text() for node in soup.select('#schools li')], ['확정중학교', '추가중학교'])
                self.assertNotIn('확인 필요', soup.select_one('#schools').get_text())
                self.assertEqual(row, before)

    def test_elementary56_exact_scope_and_immediate_parent(self):
        for grade in ('초5', '초6'):
            for subject in ('영어', '수학'):
                for confirmed in (True, False):
                    with self.subTest(grade=grade, subject=subject, confirmed=confirmed):
                        parent = next(p for p in self.parents if p['subject'] == subject
                                      and (grade in _confirmed_grades(self.centers[p['centerId']], self.reference[p['centerId']], subject)) == confirmed)
                        parent, context, soup, graph = self.rendered(confirmed, grade=grade, parent=parent)
                        self.assertEqual(len([n for n in graph if n.get('@type') == 'Service']), int(confirmed))
                        self.assertEqual(bool(soup.select_one('.branch-child-hero .branch-scope-notice')), not confirmed)
                        for type_ in ('WebPage', 'Article'):
                            self.assertEqual(next(n for n in graph if n.get('@type') == type_)['isPartOf'],
                                             {'@id': url(parent['path']) + '#webpage'})
                        self.assertEqual(next(n for n in graph if n.get('@type') == 'Article')['educationalLevel'], grade)
                        crumbs = next(n for n in graph if n.get('@type') == 'BreadcrumbList')['itemListElement']
                        self.assertEqual(len(crumbs), 6)
                        self.assertEqual(crumbs[-2]['item'], url(parent['path']))
                        self.assertEqual(crumbs[-1]['item'], url(context['path']))
                        self.assertEqual(context['path'], parent['path'] + grade + '/')
                        self.assertIn(grade, soup.h1.get_text())

    def test_elementary_scope_is_not_inferred_from_other_school_levels(self):
        # A real branch has 초6/중1 but not 초5: broad availability must not
        # produce an elementary grade5 Service automatically.
        parent = next(p for p in self.parents
                      if {'초6', '중1'}.issubset(_confirmed_grades(self.centers[p['centerId']], self.reference[p['centerId']], p['subject']))
                      and '초5' not in _confirmed_grades(self.centers[p['centerId']], self.reference[p['centerId']], p['subject']))
        for grade, confirmed in (('초5', False), ('초6', True), ('중1', True)):
            with self.subTest(real_locality=parent['locality'], grade=grade):
                _, _, soup, graph = self.rendered(confirmed, grade=grade, parent=parent)
                self.assertEqual(len([n for n in graph if n.get('@type') == 'Service']), int(confirmed))
                self.assertEqual(bool(soup.select_one('.branch-child-hero .branch-scope-notice')), not confirmed)
        cid, subject = parent['centerId'], parent['subject']
        original_center, original_reference = deepcopy(self.centers[cid]), deepcopy(self.reference[cid])
        for offered in ('초5', '초6', '중1', '고2'):
            center, reference = deepcopy(original_center), deepcopy(original_reference)
            center['subjects'][subject]['grades'] = [offered]
            reference['operations']['subjectDisplay'][subject] = {
                'status': 'recorded', 'includeInUnqualifiedAvailableSubjects': True,
                'sourceGrades': [offered], 'summary': offered, 'detail': ''}
            with patch.dict(self.centers, {cid: center}), patch.dict(self.reference, {cid: reference}):
                for queried in ('초5', '초6'):
                    expected = offered == queried
                    with self.subTest(offered=offered, queried=queried):
                        _, _, soup, graph = self.rendered(expected, grade=queried, parent=parent)
                        self.assertEqual(len([n for n in graph if n.get('@type') == 'Service']), int(expected))
                        self.assertEqual(bool(soup.select_one('.branch-child-hero .branch-scope-notice')), not expected)
        self.assertEqual(self.centers[cid], original_center)
        self.assertEqual(self.reference[cid], original_reference)

    def test_elementary56_render_only_elementary_school_names(self):
        row = {'targetSchools': {'elementary': ['확정초등학교', '추가초등학교 [후보·지역 확인 필요]'],
                                'middle': ['중학교 표본'], 'high': ['고등학교 표본']}}
        before = deepcopy(row)
        for grade in ('초5', '초6'):
            with self.subTest(grade=grade):
                _, _, soup, _ = self.rendered(True, grade=grade, school_row=grade_school_row(row, grade))
                self.assertEqual([node.get_text() for node in soup.select('#schools li')], ['확정초등학교', '추가초등학교'])
                self.assertNotIn('확인 필요', soup.select_one('#schools').get_text())
                self.assertEqual(row, before)


if __name__ == '__main__':
    unittest.main()
