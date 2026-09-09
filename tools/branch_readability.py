"""Lossless sentence-boundary grouping for long Korean reading paragraphs."""
from __future__ import annotations

import re


def reading_chunks(text: str, limit: int = 210) -> list[str]:
    """Split at complete sentence boundaries only; never shorten a sentence.

    Joining chunks with a single space reproduces whitespace-normalized input.
    Quoted examples and decimal numbers remain intact.
    """
    text = ' '.join(text.split())
    if len(text) <= limit:
        return [text] if text else []
    sentences = []
    start = 0
    stack = []
    pairs = {'‘': '’', '“': '”', '(': ')', '（': '）', '「': '」'}
    for i, ch in enumerate(text):
        if ch in pairs:
            stack.append(pairs[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
        if ch in '.!?' and not stack and (i + 1 == len(text) or text[i + 1].isspace()):
            # Do not split English abbreviations used within an example.
            if re.search(r'(?:e\.g|i\.e|Mr|Mrs|Dr)\.$', text[start:i + 1]):
                continue
            sentences.append(text[start:i + 1].strip())
            start = i + 1
    if text[start:].strip():
        sentences.append(text[start:].strip())
    result = []
    current = ''
    for sentence in sentences:
        if current and len(current) + 1 + len(sentence) > limit:
            result.append(current)
            current = sentence
        else:
            current = (current + ' ' + sentence).strip()
    if current:
        result.append(current)
    assert ' '.join(result) == text
    return result
