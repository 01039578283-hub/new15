"""Regression tests for center-to-neighborhood navigation only."""
import unittest
from bs4 import BeautifulSoup
from generate_branch_pages import neighborhood_navigation, page, base_graph, url


class NeighborhoodNavigationTests(unittest.TestCase):
    def setUp(self):
        self.children = [
            {'locality': '상인동', 'title': '상인동 수학학원', 'path': '/지점안내/대구/신월성점/상인동수학학원/'},
            {'locality': '상인동', 'title': '상인동 영어학원', 'path': '/지점안내/대구/신월성점/상인동영어학원/'},
            {'locality': '월성동', 'title': '월성동 수학학원', 'path': '/지점안내/대구/신월성점/월성동수학학원/'},
        ]

    def test_no_children_has_no_section(self):
        self.assertEqual(neighborhood_navigation([]), '')

    def test_groups_neighborhoods_and_preserves_link_order(self):
        soup = BeautifulSoup(neighborhood_navigation(self.children), 'html.parser')
        cards = soup.select('.branch-neighborhood-card')
        self.assertEqual([card.h3.text for card in cards], ['상인동', '월성동'])
        self.assertEqual([a['href'] for a in soup.select('a')], [p['path'] for p in self.children])
        self.assertEqual(len(cards[0].select('a')), 2)
        self.assertEqual(len(cards[1].select('a')), 1)

    def test_missing_subject_not_invented(self):
        soup = BeautifulSoup(neighborhood_navigation(self.children[-1:]), 'html.parser')
        self.assertEqual(len(soup.select('a')), 1)
        self.assertNotIn('월성동 영어학원', soup.get_text())

    def test_accessible_titles_and_real_links(self):
        soup = BeautifulSoup(neighborhood_navigation(self.children), 'html.parser')
        section = soup.select_one('#neighborhood-pages')
        self.assertEqual(section['aria-labelledby'], soup.h2['id'])
        for anchor, child in zip(soup.select('a'), self.children):
            self.assertEqual(anchor.find('span').text, child['title'])
            self.assertEqual(anchor.select_one('[aria-hidden="true"]').text, '→')
            self.assertNotIn('onclick', anchor.attrs)

    def test_labels_are_escaped(self):
        child = {'locality': '<동네>', 'title': 'A & B <학원>', 'path': '/지점안내/지역/점/a&b/'}
        soup = BeautifulSoup(neighborhood_navigation([child]), 'html.parser')
        self.assertEqual(soup.h3.text, child['locality'])
        self.assertEqual(soup.a.find('span').text, child['title'])
        self.assertEqual(soup.a['href'], child['path'])
        self.assertIsNone(soup.find('학원'))

    def test_section_remains_connected_in_structured_data(self):
        path = '/지점안내/대구/신월성점/'
        graph = base_graph('신월성점', '설명', path, [])
        part_id = url(path) + '#neighborhood-pages'
        graph.append({'@type': 'ItemList', '@id': part_id, 'numberOfItems': 3})
        page('신월성점', '설명', path, [], neighborhood_navigation(self.children), graph, detail=True)
        self.assertIn({'@id': part_id}, graph[1]['hasPart'])
        item = next(node for node in graph if node.get('@id') == part_id)
        self.assertEqual(item['name'], '동네별 영어·수학 학습 안내')
        self.assertEqual(item['isPartOf'], {'@id': url(path) + '#webpage'})
        self.assertEqual(item['@type'], 'ItemList')


if __name__ == '__main__':
    unittest.main()
