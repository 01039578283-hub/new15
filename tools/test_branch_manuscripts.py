"""Small independent parser tests; fixtures are created in a temporary folder."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
from zipfile import ZipFile

import branch_manuscripts as parser


def manuscript(locality='가경동'):
    return (
        f'[페이지타이틀]\n{locality} 영어학원\n\n[메타설명]\n상담 준비 안내입니다.\n\n'
        '[본문]\n학생에게 필요한 내용을 확인합니다.\n\n## 첫 질문\n'
        '과목과 학년을 알려주세요.\n\n[FAQ]\nQ1. 무엇을 준비하나요?\n'
        'A1. 교재를 준비해 주세요.\n\n[학부모후기]\n'
        f'※ {locality} 영어학원 상담을 준비할 때 참고할 수 있는 학부모 관점의 상황 예시입니다.\n'
        '보호자라면 상담 질문을 준비할 수 있습니다.\n\n[JSON-LD 요약]\n상담 질문 안내입니다.\n'
    )


class ManuscriptArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '영어학원.zip'

    def archive(self, entries):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with ZipFile(self.path, 'w') as archive:
                for name, content in entries:
                    archive.writestr(name, content)
        return self.path

    def load(self, text=None, name='영어학원/가경동 영어학원.txt'):
        raw = (manuscript() if text is None else text).encode('utf-8-sig')
        return parser.load_manuscript_archive(self.archive([(name, raw)]), '영어')

    def test_valid_sorted_records_and_raw_source_hashes(self):
        first = manuscript('나성동').encode('utf-8-sig')
        second = manuscript().replace('\n', '\r\r\n').encode('utf-8-sig')
        self.archive([('영어학원/나성동 영어학원.txt', first), ('영어학원/가경동 영어학원.txt', second)])
        before = self.path.read_bytes()
        records = parser.load_manuscript_archive(self.path, '영어')
        self.assertEqual([r['locality'] for r in records], ['가경동', '나성동'])
        self.assertEqual(records[0]['sourceSha256'], hashlib.sha256(second).hexdigest())
        self.assertEqual(records[0]['sourceArchiveSha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(records[0]['cases'], ['보호자라면 상담 질문을 준비할 수 있습니다.'])
        self.assertEqual(records[0]['faq'], [{'question':'무엇을 준비하나요?', 'answer':'교재를 준비해 주세요.'}])
        self.assertEqual(records[0]['sections'], [{'heading':'첫 질문', 'paragraphs':['과목과 학년을 알려주세요.']}])
        self.assertEqual(set(records[0]), {'locality','subject','title','meta','intro','sections','faq','cases','schemaSummary','sourceMember','sourceSha256','sourceArchiveSha256'})

    def test_plain_text_is_not_executed_or_rewritten(self):
        text = manuscript().replace('과목과 학년을 알려주세요.', '<script>unknown()</script> & 제공된 원문')
        self.assertEqual(self.load(text)[0]['sections'][0]['paragraphs'], ['<script>unknown()</script> & 제공된 원문'])

    def test_unknown_missing_duplicate_blocks(self):
        variants = [
            manuscript().replace('[메타설명]', '[알수없음]'),
            manuscript().replace('[FAQ]\nQ1. 무엇을 준비하나요?\nA1. 교재를 준비해 주세요.\n\n', ''),
            manuscript() + '\n[메타설명]\n중복 설명',
        ]
        for text in variants:
            with self.subTest(text=text[-50:]), self.assertRaises(parser.ManuscriptFormatError):
                self.load(text)

    def test_title_and_category_mismatch(self):
        for text in [manuscript('다른동'), manuscript().replace('가경동 영어학원', '가경동 수학학원')]:
            with self.subTest(text=text[:30]), self.assertRaises(parser.ManuscriptFormatError):
                self.load(text)

    def test_missing_or_mismatched_faq(self):
        for faq in ['질문 없이 답변만', 'Q1. 질문\nA2. 답변', 'Q2. 질문\nA2. 답변', 'Q1. 질문\nA1. ']:
            text = manuscript().replace('Q1. 무엇을 준비하나요?\nA1. 교재를 준비해 주세요.', faq)
            with self.subTest(faq=faq), self.assertRaises(parser.ManuscriptFormatError):
                self.load(text)

    def test_unsafe_member_paths(self):
        for name in ['../가경동 영어학원.txt', '/가경동 영어학원.txt', '영어학원/../가경동 영어학원.txt', 'C:/가경동 영어학원.txt']:
            with self.subTest(name=name), self.assertRaises(parser.ManuscriptFormatError):
                self.load(name=name)
        # On Windows ZipFile's writer converts backslashes to forward slashes.
        # Exercise the reader-side validation directly for this unsafe spelling.
        with self.assertRaises(parser.ManuscriptFormatError):
            parser._member_path('영어학원\\가경동 영어학원.txt','영어학원',False)

    def test_duplicate_member_or_locality(self):
        raw = manuscript().encode('utf-8-sig')
        for other in ['영어학원/가경동 영어학원.txt', '가경동 영어학원.txt']:
            self.archive([('영어학원/가경동 영어학원.txt',raw),(other,raw)])
            with self.subTest(other=other), self.assertRaises(parser.ManuscriptFormatError):
                parser.load_manuscript_archive(self.path,'영어')

    def test_size_limits(self):
        self.archive([('영어학원/가경동 영어학원.txt',manuscript().encode('utf-8-sig'))])
        for constant, limit in [('MAX_ARCHIVE_BYTES',1),('MAX_UNCOMPRESSED_BYTES',1),('MAX_MEMBER_BYTES',1),('MAX_MEMBERS',0)]:
            with self.subTest(constant=constant), patch.object(parser,constant,limit), self.assertRaises(parser.ManuscriptFormatError):
                parser.load_manuscript_archive(self.path,'영어')

    def test_wrong_encoding_or_empty_archive(self):
        for entries in [[('영어학원/가경동 영어학원.txt', manuscript().encode('cp949'))], []]:
            self.archive(entries)
            with self.subTest(entries=len(entries)), self.assertRaises(parser.ManuscriptFormatError):
                parser.load_manuscript_archive(self.path,'영어')


if __name__ == '__main__':
    unittest.main()
