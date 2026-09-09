import unittest
from branch_readability import reading_chunks


class ReadingChunksTests(unittest.TestCase):
    def test_lossless_complete_sentences(self):
        text = '개념을 확인합니다. 풀이의 근거를 설명합니다. 다른 문제에도 적용해 봅니다.'
        chunks = reading_chunks(text, 23)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(' '.join(chunks), text)
        self.assertTrue(all(c.endswith('.') for c in chunks))

    def test_quoted_question_not_cut(self):
        text = '‘왜 이렇게 풀었나요? 다른 풀이도 있나요?’라는 질문에 답합니다. 풀이를 기록합니다.'
        chunks = reading_chunks(text, 12)
        self.assertIn('‘왜 이렇게 풀었나요? 다른 풀이도 있나요?’라는 질문에 답합니다.', chunks)
        self.assertEqual(' '.join(chunks), text)

    def test_long_sentence_not_truncated(self):
        text = '현재 학생의 학습 흔적을 살피고 풀이와 답안을 비교하여 다음 학습 과제를 찾습니다.'
        self.assertEqual(reading_chunks(text, 10), [text])

    def test_decimal_and_examples(self):
        text = '2.5와 0.5를 더한 이유를 설명합니다. 23×14의 부분곱을 계산합니다.'
        self.assertEqual(' '.join(reading_chunks(text, 25)), text)


if __name__ == '__main__':
    unittest.main()
