"""Conservative grade-only display reading aids; source paragraphs stay intact.

Call after reviewed editorial corrections. No file access, inference of center
operations, FAQ rewriting, paraphrasing, or changes to identity/source fields.
Points are exact, independently readable sentence excerpts from source sections.
"""
from __future__ import annotations

from copy import deepcopy
import re


MAX_POINTS = 2
MAX_POINT_CHARS = 170
MAX_TOTAL_CHARS = 320
_SUPPORTED = {'초5', '초6', '중1', '중2', '중3', '고1', '고2'}
_GENERIC = {
    '영어', '수학', '학원', '초등', '중등', '고등', '초등학교', '중학교', '고등학교',
    '학생', '아이', '학부모', '보호자', '학습', '공부', '상담', '확인', '기준',
    '비교', '학교', '자료', '준비', '질문', '선택', '과정', '방법', '먼저', '현재',
    '필요', '기록', '복습', '피드백', '살펴', '정리', '점검', '최근', '함께',
    '어떻게', '무엇', '어떤', '구체적', '실제', '좋습니다', '있습니다', '해야',
    '하는', '있는', '되는', '수업', '때는', '단순히', '알아볼', '고를', '찾는다면',
    '중요합니다', '우선입니다', '바탕', '통해', '뒤에는', '때문', '특히', '이후',
    '시간', '계획', '순서', '방식', '조정', '나누어', '살펴보', '설명', '문제',
}
_PARTICLES = re.compile(r'(?:에서는|으로는|에는|부터|보다|처럼|까지|에게|에서|으로|대로|을|를|은|는|이|가|의|도|과|와|로)$')
_UNSAFE_CONTENT = re.compile(
    r'상담|질문|물어|문의|요청|학원|센터|강사|교사|원장|보강|특강|수강|'
    r'정원|원비|교육비|비용|할인|등록|개설|운영|제공|제시|진행|실시|지도하|관리하|'
    r'학교|입시|합격|성과|보장|입력|원고|키워드|검색어|ROW_DATA|[D-G]열|'
    r'이 행|이 안내|본문|하겠습니다|드립니다|저희|우리 학|있나요|하나요|인가요|'
    r'수업 적합|수업을 비교|수업 선택|안내되는|보호자가 확인할|진단 뒤|결과를 어떤 말로')
_DEPENDENT = re.compile(
    r'^(?:이때|이를|이것|그것|이렇게|그렇게|이런|그런|이러한|그러한|이 경우|그 경우|'
    r'또한|다만|하지만|그러나|따라서|그러므로|반면|즉,|그래서|그다음|그리고|예를|예컨대|'
    r'첫째|둘째|셋째|넷째|다섯째|마지막으로|이후|두 문제|두 문장|두 가지|세 가지)|'
    r'이 (?:과정|방법|기록|방식|문제|설명|단계|연습|활동|예시|문장|표현|식)|'
    r'그 (?:과정|방법|기록|방식|문제|설명|단계|결과|예시|문장)|'
    r'앞서|앞 문장|뒤 문장|위의|아래의|앞에서|앞뒤|다음과 같|다음처럼|때문입니다\.$')
_FORMULA = re.compile(r'[=×÷<>≤≥√^]|\b[A-Za-z]\b|\d\s*[+−*/]\s*\d')
_LEARNING = re.compile(
    r'단어|어휘|문장|문법|독해|지문|읽|쓰|듣|발음|철자|해석|영작|작문|표현|어순|'
    r'풀이|계산|개념|조건|도형|수식|공식|함수|그래프|단원|오답|노트|공책|교재|'
    r'개요|분류|근거|암기|녹음|어법|서술|제곱|분수|소수|부피|넓이|비율|기억|집중')
_ACTION_OR_EXPLANATION = re.compile(
    r'적어|적는|적고|적은|표시|나누|구분|비교|설명|읽어|읽는|다시|고쳐|고치|'
    r'기록|정리|분류|확인|점검|찾아|찾는|연결|바꿔|바꾸|남겨|남기|남는|'
    r'필요|도움|어렵|부담|다릅니다|때문|않습니다|아닙니다|뜻합니다')
_REDUNDANT_TAIL = re.compile(
    r'^(?:특히 )?영어(?:와 |·| )수학을 함께 (?:관리|비교|상담|고려).+'
    r'(?:질문해야 합니다|확인해 보세요|비교해 보세요|물어보세요)\.$')
_TAIL_PROTECTED = re.compile(
    r'\d|[A-Za-z=×÷<>]|[‘’“”]|학교|개설|운영|보장|확정|단정|않|못|아니|'
    r'비용|정원|시간|학년|어휘|문법|독해|지문|계산|조건|함수|그래프|교재|'
    r'증감표|서술|오답|시험|평가|특강|진도|어순|개념')


def _sentences(value: str) -> list[str]:
    """Exact substrings, without splitting balanced quotes/parentheses/decimals."""
    spans = []
    start = 0
    stack = []
    pairs = {'‘': '’', '“': '”', '(': ')', '（': '）', '「': '」', '[': ']'}
    for i, char in enumerate(value):
        if char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        if (char in '.!?' and not stack
                and (i + 1 == len(value) or value[i + 1].isspace())):
            if re.search(r'(?:e\.g|i\.e|Mr|Mrs|Dr)\.$', value[start:i + 1]):
                continue
            spans.append(value[start:i + 1].strip())
            start = i + 1
    if value[start:].strip():
        spans.append(value[start:].strip())
    return spans


def _terms(value: str) -> set[str]:
    result = set()
    for token in re.findall(r'[가-힣]{2,}', value):
        stem = _PARTICLES.sub('', token)
        if len(stem) >= 2 and stem not in _GENERIC:
            result.add(stem)
    return result


def _standalone(sentence: str) -> bool:
    if not 45 <= len(sentence) <= MAX_POINT_CHARS or not sentence.endswith('.'):
        return False
    if _UNSAFE_CONTENT.search(sentence) or _DEPENDENT.search(sentence) or _FORMULA.search(sentence):
        return False
    # Do not elevate an isolated quotation, numerical example, incomplete clause,
    # or unsupported institution action into a standalone summary.
    if sentence.startswith(('‘', '“', '"', "'")) or re.search(r'\b(?:예시|예컨대)\b', sentence):
        return False
    return bool(_LEARNING.search(sentence) and _ACTION_OR_EXPLANATION.search(sentence))


def _shorten_intro(record: dict, changes: list[dict]) -> None:
    before = record.get('intro', '')
    parts = _sentences(before)
    # Existing two-sentence summaries remain verbatim. Only a third, generic
    # cross-subject consultation sign-off can go; no clause-level surgery.
    if len(parts) != 3 or not 100 <= len(' '.join(parts[:2])) <= 260:
        return
    tail = parts[-1]
    if not _REDUNDANT_TAIL.fullmatch(tail) or _TAIL_PROTECTED.search(tail):
        return
    topic_terms = _terms(parts[0])
    if any(term in tail for term in topic_terms):
        return
    # Removing the final sentence leaves the exact retained introduction prefix.
    end = before.rfind(tail)
    after = before[:end].rstrip()
    if not after.endswith('.'):
        return
    record['intro'] = after
    changes.append({'stage': 'grade-reading', 'field': 'intro',
                    'rule': 'trim-generic-third-intro', 'count': 1,
                    'before': before, 'after': after,
                    'reason': 'Retained two complete topical sentences; removed only a generic third cross-subject consultation sign-off.'})


def improve_grade_reading(record: dict) -> tuple[dict, list[dict], list[dict]]:
    """Return a copy, editorial change log, and up to two traceable exact excerpts.

    Each point has text / sectionIndex / paragraphIndex (both 1-based). The
    source paragraph is never shortened or rewritten. [] is a valid outcome.
    Points are learning explanations/advice, never claims of offered services.
    FAQ is deliberately preserved because shortening context-safe answers by a
    corpus-wide rule could remove a condition or concrete example.
    """
    result = deepcopy(record)
    changes = []
    if record.get('grade') not in _SUPPORTED or record.get('subject') not in ('영어', '수학'):
        return result, changes, []
    _shorten_intro(result, changes)
    topic = _terms(result.get('intro', '') + ' ' + result.get('meta', ''))
    topic -= _terms(result.get('locality', ''))
    candidates = []
    for section_index, section in enumerate(result.get('sections', []), 1):
        heading = section.get('heading', '')
        # School, operation and final consultation sections are not summary tips.
        if re.search(r'학교|상담|학원|질문|비용|수업 적합|선택 기준|비교 기준', heading):
            continue
        for paragraph_index, paragraph in enumerate(section.get('paragraphs', []), 1):
            for sentence_index, sentence in enumerate(_sentences(paragraph)):
                if not _standalone(sentence):
                    continue
                if ('수학' if result['subject'] == '영어' else '영어') in sentence:
                    continue
                matches = {term for term in topic if term in sentence}
                if not matches:
                    continue
                score = 4 * min(len(matches), 4) + min(len(_terms(heading) & _terms(sentence)), 3)
                score += 2 if re.search(r'적어|표시|나누|구분|기록|분류|고쳐|다시 풀', sentence) else 0
                candidates.append((score, section_index, paragraph_index, sentence_index, sentence))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2], c[3]))
    points = []
    used_sections = set()
    intro = result.get('intro', '')
    for _, section_index, paragraph_index, _, sentence in candidates:
        if section_index in used_sections or sentence in intro or any(p['text'] == sentence for p in points):
            continue
        # Two points should not merely repeat the same content-word set.
        terms = _terms(sentence)
        if any(len(terms & _terms(p['text'])) / max(1, len(terms | _terms(p['text']))) > .45 for p in points):
            continue
        # Different wording for the same 'classify errors' action is one point,
        # not a reason to fill a second slot from another section.
        if (re.search(r'나누|구분|분류', sentence)
                and any(re.search(r'나누|구분|분류', p['text']) for p in points)):
            continue
        if sum(len(p['text']) for p in points) + len(sentence) > MAX_TOTAL_CHARS:
            continue
        source = result['sections'][section_index - 1]['paragraphs'][paragraph_index - 1]
        assert sentence in source
        points.append({'text': sentence, 'sectionIndex': section_index, 'paragraphIndex': paragraph_index})
        used_sections.add(section_index)
        if len(points) == MAX_POINTS:
            break
    points.sort(key=lambda p: (p['sectionIndex'], p['paragraphIndex']))
    return result, changes, points
