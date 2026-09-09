"""Bounded, non-writing tests for the scoped legacy postprocessor."""
import gzip
import json
import unittest

from bs4 import BeautifulSoup
from reconcile_branch_legacy_scope import BASELINE, target_pages, transform_html


class LegacyScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(BASELINE, 'rt', encoding='utf-8') as stream:
            cls.baseline = json.load(stream)
        cls.targets = target_pages()

    def test_scope_exactly_54(self):
        self.assertEqual(len(self.targets), 54)
        self.assertEqual(len({(t['locality'], t['subject']) for t in self.targets}), 18)
        self.assertNotIn('reference-경기-화성태안점', {t['centerId'] for t in self.targets})

    def test_full_scope_preserves_unrelated_blocks_and_is_idempotent(self):
        faq_changes = 0
        for target in self.targets:
            path = target['path'].strip('/') + '/index.html'
            before = self.baseline['pages'][path]['html']
            after, changes = transform_html(before, target)
            old, new = BeautifulSoup(before, 'html.parser'), BeautifulSoup(after, 'html.parser')
            with self.subTest(path=path):
                for selector in ('title', 'h1', '.academy-article', '.academy-cases', '.academy-media-section', '.academy-related'):
                    self.assertEqual(str(old.select_one(selector)), str(new.select_one(selector)))
                self.assertEqual([n.attrs for n in old.select('head meta,head link,img,a[href]')],
                                 [n.attrs for n in new.select('head meta,head link,img,a[href]')])
                self.assertEqual(len(new.select('.academy-scope-confirmation')), 1)
                self.assertEqual(len(new.select('.academy-faq details')), 4)
                self.assertEqual(transform_html(after, target)[0], after)
                graph = json.loads(new.select_one('script[type="application/ld+json"]').string)['@graph']
                self.assertFalse(any(n.get('@type') == 'Service' for n in graph))
                self.assertNotIn('#service', json.dumps(graph))
                self.assertFalse(any('educationalLevel' in n for n in graph if n.get('@type') == 'EducationalOrganization'))
                faqs = next(n for n in graph if n.get('@type') == 'FAQPage')['mainEntity']
                self.assertEqual([(n['name'], n['acceptedAnswer']['text']) for n in faqs],
                                 [(n.summary.get_text(), n.p.get_text()) for n in new.select('.academy-faq details')])
                faq_changes += len(changes['faq'])
        self.assertEqual(faq_changes, 18)

    def test_unexpected_markup_fails_closed(self):
        target = self.targets[0]
        html = self.baseline['pages'][target['path'].strip('/') + '/index.html']['html']
        with self.assertRaises(RuntimeError):
            transform_html(html.replace('<strong>수업 가능 학년</strong>', '<strong>UNKNOWN</strong>'), target)

    def test_no_unknown_scope_invention(self):
        target = next(t for t in self.targets if t['locality'] == '화곡동' and t['level'] == '고등학생')
        html = self.baseline['pages'][target['path'].strip('/') + '/index.html']['html']
        after, _ = transform_html(html, target)
        soup = BeautifulSoup(after, 'html.parser')
        notice = soup.select_one('.academy-scope-confirmation').get_text()
        self.assertIn('개설 여부와 대상 학년은 상담에서 확인', notice)
        self.assertNotIn('폐강', notice)
        self.assertNotIn('개설되지', notice)
        self.assertNotIn('고1·고2·고3 수업은 모두', soup.select_one('.academy-faq').get_text())


if __name__ == '__main__':
    unittest.main()
