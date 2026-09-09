"""Fact-preserving display editing for supplied neighborhood manuscripts.

No source archive or center data is written. This is selective sentence editing,
not a second manuscript generator. Complete examples and qualifications take
precedence over a rigid sentence or character target.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from itertools import combinations
import re

from polish_branch_manuscripts import polish_manuscript


_INTRO = {
    ('가경동', '영어'): '영어 정답지는 답을 확인하는 데서 끝내기보다 학생이 고른 근거와 해설이 달라진 지점을 찾는 데 활용해 보세요. 먼저 스스로 다시 풀고, 문장 속 근거를 표시한 뒤 비슷한 유형에도 같은 판단을 적용할 수 있는지 살펴보는 방법을 안내합니다.',
    ('명일동', '영어'): '사회 분야 영어 지문에서 막힐 때는 모르는 단어, 문맥에 맞는 뜻, 문장 구조를 나누어 살펴보세요. 개인 어휘 노트에 뜻만 적기보다 지문 속 쓰임과 예문을 남기고, 며칠 뒤 같은 표현을 다시 설명할 수 있는지 확인하는 방법을 안내합니다.',
    ('명일동', '수학'): '수학을 못한다는 말 뒤에는 개념 공백, 조건 해석의 어려움, 계산 실수, 시도하기 전 포기하는 습관이 서로 다르게 숨어 있을 수 있습니다. 최근 문제의 풀이와 멈춘 지점을 나누어 보고, 학생에게 필요한 첫 연습과 복습 기준을 정리해 보세요.',
    ('광명동', '수학'): '두 자릿수 곱셈의 원리를 다시 정리해야 하는 학생이라면 정답뿐 아니라 자리값과 부분곱을 설명할 수 있는지 살펴보세요. 24×13을 24×10과 24×3으로 나누어 보며, 세로셈의 각 줄이 뜻하는 것과 반복되는 실수의 원인을 확인합니다.',
    ('고잔동', '수학'): '학기 말 오답은 개념 부족, 조건 해석, 계산 실수, 시간 부족으로 나누어 보면 보완할 순서가 선명해집니다. 최근 시험지와 풀이 흔적에서 다음 단원에 영향을 주는 빈틈을 찾고, 틀린 이유를 기록해 다시 확인하는 방법을 살펴보세요.',
    ('단구동', '영어'): '단어를 외웠는데도 지문에서 표현이 바뀌면 막힌다면 상위어와 하위어의 관계를 살펴보세요. move와 walk·ride·drive처럼 넓은 개념과 구체적인 표현을 어휘 노트에 연결하고, 문장 속 쓰임까지 다시 확인하는 방법을 안내합니다.',
    ('당산동', '영어'): '영어 의견문은 문법 오류를 고치는 데서 끝내기보다 주장과 근거, 문단의 연결을 살펴보고 다시 써 보는 과정이 중요합니다. 학생의 초안과 수정본을 함께 놓고 무엇을 왜 고쳤는지 설명하게 하며, 다음 글에도 적용할 기준을 정리해 보세요.',
    ('교하', '영어'): '영어 장문에서 시간이 부족하다면 단어 해석, 중심 정보 선별, 근거 찾기, 불필요한 재독 중 어디에서 멈추는지 나누어 보세요. 최근 지문의 풀이 순서와 표시한 근거를 기록하면 속도만 재촉하기보다 먼저 연습할 부분을 찾는 데 도움이 됩니다.',
    ('교하', '수학'): '자리값을 헷갈리는 학생은 답을 맞혔는지보다 숫자의 위치와 0의 역할을 설명할 수 있는지 확인해 보세요. 472를 400+70+2로 나타내는 활동에서 출발해, 수의 분해와 자릿수 정렬이 계산과 응용으로 이어지는 방법을 살펴봅니다.',
    ('갈매동', '영어'): '다음 단계 영어 자료를 고를 때는 진도보다 학생이 혼자 해결하는 부분, 힌트가 필요한 부분, 다시 연습할 부분을 먼저 나누어 보세요. 단어·문장·독해의 오답 기록을 남기고, 자료의 난도와 복습 순서를 조정할 기준을 정리합니다.',
    ('위례', '수학'): '수학 과제가 밀릴 때는 분량만 줄이기보다 시간 부족, 개념 공백, 시작 순서를 잡지 못한 경우를 나누어 보세요. 최근 미완료 과제와 오답을 바탕으로 핵심 문제를 고르고, 학생이 수행할 수 있는 난도와 복습 순서를 살펴봅니다.',
    ('위례신도시', '수학'): '수학 문제 앞에서 멈춘 학생에게는 바로 풀이를 알려 주기보다 어느 조건과 풀이 줄에서 막혔는지 말할 시간을 주세요. 도움을 청하는 범위를 좁히고, 받은 힌트를 자기 말로 정리한 뒤 비슷한 문제를 혼자 풀어 보는 흐름을 안내합니다.',
    ('동삭동', '수학'): '좌표 문제의 오답은 축 혼동, 좌표를 읽는 순서, 조건 해석, 계산으로 나누어 보면 복습할 부분이 선명해집니다. 점과 도형의 관계를 말로 정리한 뒤 축과 원점을 표시하고, 계산 결과가 원래 조건에 맞는지 거꾸로 확인해 보세요.',
    ('북변동', '영어'): '관용표현은 뜻을 외우는 것과 문맥 속 의미를 이해하는 것이 다를 수 있습니다. 최근 지문에서 앞뒤 단서와 화자의 상황을 찾고, 같은 표현을 다른 문장이나 짧은 대화에 다시 사용해 보며 암기와 적용을 구분하는 방법을 살펴보세요.',
    ('진관동', '수학'): '수학 숙제 시간을 정할 때는 학생이 실제로 집중하는 시간과 미루는 이유부터 살펴보세요. 최근 일주일의 시작 시각, 막힌 문제, 오답을 처리한 방법을 기록하면 분량만 늘리기보다 생활 리듬에 맞는 과제와 복습 순서를 비교할 수 있습니다.',
    ('개운동', '영어'): '영어 이메일 쓰기에서는 완성본만 보기보다 내용 전달, 문장 구성, 어휘와 문법을 나누어 점검하는 과정이 중요합니다. 학생의 초안과 수정 기록을 함께 보며 어떤 기준으로 답안을 고쳤는지, 다음 과제에도 그 기준을 적용하는지 살펴보세요.',
    ('교문동', '영어'): '영어로 짧게 발표할 때 원고에만 시선이 머문다면 30초 말하기에서 한 문장을 설명하는 동안 시선을 어떻게 쓰는지 살펴보세요. 단어를 외웠는지뿐 아니라 뜻을 전하고 듣는 사람을 바라보는 과정까지 기록해 다음 연습의 기준으로 삼을 수 있습니다.',
    ('경화동', '영어'): '히스토그램을 영어로 읽을 때는 축과 항목의 의미를 이해하는 것과 수치를 문장으로 설명하는 것을 나누어 살펴보세요. 핵심 어휘와 비교 표현을 확인한 뒤, 다른 단원의 자료에도 같은 읽기·설명 방법을 적용하며 복습하는 흐름을 안내합니다.',
    ('옥정동', '영어'): '영어 지문에서 불규칙 복수형을 놓친다면 단어의 형태를 알아보는 것과 문장 전체의 뜻을 이해하는 과정을 나누어 보세요. 최근 지문과 오답에서 어떤 형태에 멈췄는지 기록하고, 새 문장에서도 같은 표현을 알아보는지 다시 확인하는 방법을 살펴봅니다.',
}

_FAQ = {
    ('광명동', '수학', '영어 수학을 함께 알아볼 때 무엇을 비교해야 하나요?'):
        '두 과목에서 어려운 부분과 필요한 학습 시간을 각각 확인하세요. 수학은 자리값·부분곱과 풀이 설명을, 영어는 어휘·문장 이해를 따로 살펴보고 과제와 복습 일정이 겹치는지 비교하면 됩니다.',
    ('교하', '수학', '영어 수학을 함께 공부할 때 어떤 점을 상담해야 하나요?'):
        '수학의 자리값 이해와 영어의 어휘·문장 이해를 서로 다른 자료로 확인하세요. 두 과목의 과제량과 복습일이 겹치는지 비교하되, 한 과목의 오답을 다른 과목의 실력으로 해석하지 않는 것이 좋습니다.',
    ('교하', '영어', '영어 수학을 함께 학습할 때 상담에서 확인할 점은 무엇인가요?'):
        '희망 과목과 학년의 수업 개설 여부를 먼저 확인한 뒤, 과목별 학습량과 복습 시간을 비교하세요. 영어 장문 풀이 기록과 수학 오답을 따로 준비하면 필요한 과제와 점검 일정을 구체적으로 물을 수 있습니다.',
}

_EXACT_CONTEXT = {
    ('광명동', '수학'): [
        ('수학 개념 이해와 영어 문장 해석을 어느 단계에서 나누어 살피는지도', '수학 개념 이해와 영어 어휘·문장 이해를 과목별로 확인하는지도'),
    ],
    ('교하', '수학'): [
        ('영어 수학 자료를 함께 사용하는 경우에는 영어 표현을 해석하는 부담 때문에 수학 개념의 오류가 가려질 수 있으므로, 먼저 수의 구조를 이해했는지 확인하고 그다음 용어와 문장 해석을 분리해 점검하는지 물어보세요.', '영어와 수학을 함께 공부한다면 수학의 자리값 설명과 영어의 어휘·문장 이해를 별도 자료로 확인하고, 과목별 복습 순서를 나누어 정하는지 물어보세요.'),
        ('영어 문장을 이해하지 못한 경우와 수학 개념을 모르는 경우를 나누어 적고', '영어의 어휘·문장 이해와 수학의 자리값 이해를 과목별로 나누어 적고'),
    ],
}

_GENERIC = ('상담', '확인', '영어', '수학', '자료', '학생', '학습', '기준', '비교',
            '학교', '복습', '과정', '준비', '수업', '방법', '고민', '따라', '기록',
            '피드백', '질문', '선택', '현재', '나누', '먼저', '연결', '필요', '점검',
            '학원', '어떻게', '무엇', '중요', '살펴', '정리', '좋습', '있습', '있을')
_SCOPE_NOTICE = '수업 개설 여부와 대상 학년을 먼저 확인해 주세요.'
_DEPENDENT_OPENING = re.compile(r'^(?:이를|이때|이런|이러한|이처럼|이렇게|따라서|그다음|그 뒤|그 결과|여기서|반대로|그러나|예를 들어)')


def _sentences(value):
    return [s for s in re.split(r'(?<=[.!?])\s+', value.strip()) if s]


def _combined(value):
    return '영어' in value and '수학' in value


def _concrete(value):
    """Never discard an equation, English example, or a quoted learner example."""
    return bool(re.search(r'\d|[A-Za-z]|[×÷=]|[‘“「]|예를 들어|예를 들면', value))


def _body_detail(value):
    return _concrete(value) or bool(re.search(r'분류|유형|시간|계획|목표|연습량', value))


def _qualification(value):
    return bool(re.search(r'^(?:다만|단,|하지만|그러나)|보장|단정|운영 여부|개설 여부|확인되지', value))


def _topic_terms(record):
    weighted = Counter()
    for i, section in enumerate(record.get('sections', [])[:3]):
        for token in re.findall(r'[가-힣A-Za-z0-9]+', section['heading']):
            if len(token) > 1 and not token.startswith(_GENERIC):
                weighted[token[:3]] += 3 if i < 2 else 1
    return weighted


def _topic_score(value, terms):
    return sum(weight for token, weight in terms.items() if token in value)


def _intro(record):
    key = (record.get('locality'), record.get('subject'))
    if key in _INTRO:
        return _INTRO[key]
    current = record.get('intro', '')
    sentences = _sentences(current)
    if 100 <= len(current) <= 180 and len(sentences) <= 2:
        return current
    terms = _topic_terms(record)
    # Prefer complete introductory sentences, with the first source paragraph
    # available when the distinctive topic appears after a generic opening.
    options = [(s, 'intro') for s in sentences]
    sections = record.get('sections', [])
    if sections and sections[0].get('paragraphs'):
        options += [(s, 'body') for s in _sentences(sections[0]['paragraphs'][0])[:2]]
    options = list(dict.fromkeys(options))
    candidates = []
    for size in (1, 2):
        for indices in combinations(range(len(options)), size):
            selected = [options[i] for i in indices]
            if _DEPENDENT_OPENING.match(selected[0][0]):
                continue
            if len(selected) == 2:
                if selected[0][0] == selected[1][0]:
                    continue
                if _DEPENDENT_OPENING.match(selected[1][0]) and not (indices[1] == indices[0] + 1 and selected[0][1] == selected[1][1]):
                    continue
            value = ' '.join(s for s, _ in selected)
            if value.startswith('특히 '):
                value = value[3:]
            if not 100 <= len(value) <= 180:
                continue
            score = _topic_score(value, terms) * 8
            score += sum(source == 'intro' for _, source in selected) * 3
            score -= sum(_combined(s) for s, _ in selected) * 30
            score -= sum(s.count('상담') for s, _ in selected) * 2
            if len(selected) == 2:
                first_terms = {t for t in terms if t in selected[0][0]}
                second_terms = {t for t in terms if t in selected[1][0]}
                if second_terms <= first_terms and not _concrete(selected[1][0]):
                    score -= 3
            score -= abs(140 - len(value)) / 100
            candidates.append((score, -min(indices), value))
    if candidates:
        return max(candidates)[2]
    # No hard truncation or incomplete clauses. A rare length exception is safer
    # than dropping the only topic-bearing sentence to meet a numeric target.
    standalone = [item for item in options if not _DEPENDENT_OPENING.match(item[0])]
    return max(standalone, key=lambda item: (_topic_score(item[0], terms) - 5 * _combined(item[0]), len(item[0])))[0] if standalone else current


def _faq_answer(answer):
    sentences = _sentences(answer)
    if len(sentences) <= 2:
        return answer
    # Keep the direct answer and the substantive example. A final qualification
    # outranks a generic "ask during consultation" sentence.
    required = {0, 1} | {i for i, s in enumerate(sentences)
                          if _concrete(s) or _qualification(s)
                          or (i > 1 and not re.match(r'^(?:상담|학원|이를 바탕|이런 자료|이러한 자료)', s))}
    # A three-sentence exception is preferable to losing a concrete example or
    # an important limitation merely to satisfy the usual two-sentence target.
    return ' '.join(sentences[i] for i in sorted(required))


def prepare_editorial(record: dict, scope_confirmed: bool = True) -> tuple[dict, list[dict]]:
    """Return independent display copy and losslessly traceable field changes.

    Existing polisher changes are phrase-level. Editorial changes have
    ``stage='editorial'`` and complete before/after field values (a paragraph
    list for section changes). Titles, metadata, headings and source fields are
    not editorial targets. A caller must visibly label the supplied cases.
    """
    result, changes = polish_manuscript(record)
    changes = deepcopy(changes)
    key = (result.get('locality'), result.get('subject'))

    def update(container, key, value, field, rule):
        before = container[key]
        if before != value:
            changes.append({'field': field, 'rule': rule, 'count': 1,
                            'before': deepcopy(before), 'after': deepcopy(value), 'stage': 'editorial'})
            container[key] = value

    if 'intro' in result:
        update(result, 'intro', _intro(result), 'intro', 'topic-focused-summary')
    combined_heading = any(_combined(s['heading']) for s in result.get('sections', []))
    combined_faq = any(_combined(f['question']) for f in result.get('faq', []))
    context = _EXACT_CONTEXT.get(key, [])
    terms = _topic_terms(result)
    for i, section in enumerate(result.get('sections', [])):
        paragraphs = []
        for paragraph in section['paragraphs']:
            for before, after in context:
                paragraph = paragraph.replace(before, after)
            sentences = _sentences(paragraph)
            if (combined_heading or combined_faq) and not _combined(section['heading']):
                keep = [s for s in sentences if not (
                    _combined(s) and re.match(r'^(?:영어|수학|두 과목)', s)
                    and not _body_detail(s) and not _qualification(s) and not _topic_score(s, terms))]
                if len(keep) >= 2:
                    paragraph = ' '.join(keep)
            paragraphs.append(paragraph)
        if _combined(section['heading']) and len(paragraphs) > 1:
            sentences = [s for p in paragraphs for s in _sentences(p)]
            # Preserve all concrete examples and fact-bound qualifications;
            # otherwise retain the first comparison plus subject-specific detail.
            required = {i for i, s in enumerate(sentences) if _body_detail(s) or _qualification(s) or _topic_score(s, terms)} | {0}
            details = [i for i, s in enumerate(sentences) if '영어는' in s or '수학은' in s or '수학에서는' in s or '영어에서는' in s]
            required.update(details[:1])
            required.update(range(min(2, len(sentences))))
            if len(required) < len(sentences):
                paragraphs = [' '.join(sentences[j] for j in sorted(required))]
        update(section, 'paragraphs', paragraphs, f'sections[{i}].paragraphs', 'retain-topic-trim-combined-repetition')
    for i, item in enumerate(result.get('faq', [])):
        override = _FAQ.get((*key, item['question']))
        answer = override or _faq_answer(item['answer'])
        rule = 'reviewed-faq-meaning' if override else 'faq-direct-answer'
        course_question = bool(re.search(r'개설|운영|수업.*(?:신청|등록|선택|받|가능)', item['question']))
        if not scope_confirmed and (_combined(item['question']) or course_question):
            if not re.search(r'개설 여부.*먼저|먼저.*개설 여부', answer):
                answer = _SCOPE_NOTICE + ' ' + answer
                rule = 'scope-before-course-choice'
        update(item, 'answer', answer, f'faq[{i}].answer', rule)
    for i, case in enumerate(result.get('cases', [])):
        for before, after in context:
            case = case.replace(before, after)
        # Keep every scenario sentence: mixed-subject sentences can also carry
        # the student's distinctive action. The renderer may collapse the panel.
        update(result['cases'], i, case, f'cases[{i}]', 'reviewed-scenario-meaning')
    return result, changes
