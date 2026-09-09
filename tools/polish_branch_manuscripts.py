"""Narrow, approved display-copy corrections; never rewrite manuscript files.

This pure overlay deep-copies a parsed record and changes only reviewed phrases
in visible fields. It does not change the source hashes, schema summary, case
meaning, student-writing terminology, or other uses of the word "입력".
"""
from __future__ import annotations

from copy import deepcopy
from collections import Counter
import re


# Longer reviewed contexts are deliberately explicit. In particular, replacing
# "이 원고" globally would also match a legitimate phrase like "학생이 원고를".
_RULES = (
    ('source-keywords', '원고 참고 키워드', '상담 참고 항목'),
    ('manuscript-search', '원고를 찾는 과정에서', '학습 정보를 찾는 과정에서'),
    ('manuscript-preparation', '원고를 준비하는 과정에서', '상담을 준비하는 과정에서'),
    ('manuscript-reader', '원고를 읽는 가정', '이 안내를 읽는 가정'),
    ('source-copy-reference', '이 원고에서 확인되지 않은', '이 안내에서 확인되지 않은'),
    ('source-copy-reference', '이 원고에 제공되지 않은', '이 안내에 제공되지 않은'),
    ('source-copy-reference', '이 원고에서 판단할 수 없으므로', '이 안내에서 판단할 수 없으므로'),
    ('input-school-info', '입력된 학교 정보', '참고 학교 정보'),
    ('input-information-limit', '입력 정보만으로', '이 안내만으로'),
    ('input-limit', '입력만으로', '이 안내만으로'),
    ('spreadsheet-school-reference', 'D열에 제시된 학교 중', '안내된 학교 중'),
)
_COMPILED_RULES = tuple(
    (name, before, after, re.compile(r'(?<![가-힣A-Za-z0-9_])' + re.escape(before)))
    for name, before, after in _RULES
)

# Reviewed source-description contexts only. No standalone "입력", "키워드"
# or "검색어" rule: those words also describe real learning activities.
_READER_RULES = (
    ('reader-noun-particle', r'상담 참고 항목로', '상담 참고 항목으로'),
    ('reader-school-source', r'입력에 (?:제시된|제공된|포함된) 학교', '안내된 학교'),
    ('reader-school-source', r'입력에 학교 정보', '안내된 학교 정보'),
    ('reader-school-source', r'입력에 학교명으로', '안내된 학교명으로'),
    ('reader-school-source', r'입력에 학교명이 제공된', '학교명이 안내된'),
    ('reader-school-source', r'입력된 학교', '안내된 학교'),
    ('reader-school-source', r'입력된 목록 중 우촌초', '안내된 목록 중 우촌초'),
    ('reader-school-source', r'학교명이 입력으로 확인되지 않은 상황', '학교명을 확인할 수 없는 상황'),
    ('reader-place-source', r'입력된 지역 정보', '안내된 지역 정보'),
    ('reader-place-source', r'입력된 위치', '안내된 위치'),
    ('reader-place-source', r'입력에는 경기 광명시', '위치 안내에는 경기 광명시'),
    ('reader-place-source', r'입력에 제공된 지역은', '안내된 지역은'),
    ('reader-source-limit', r'입력에 없는 (?=운영|사항|정보|조건|내용|수업|세부|사실)', '이 안내에 없는 '),
    ('reader-source-limit', r'입력에서 확인되지 않은', '이 안내에서 확인되지 않은'),
    ('reader-source-limit', r'입력에 제공되지 않은', '이 안내에 제공되지 않은'),
    ('reader-source-limit', r'입력(?:된)? 자료만으로', '이 안내만으로'),
    ('reader-source-limit', r'입력 자료에 없으므로', '이 안내에 없으므로'),
    ('reader-source-limit', r'입력된 정보만으로', '이 안내만으로'),
    ('reader-source-limit', r'입력된 표현만으로', '이 표현만으로'),
    ('reader-source-limit', r'입력된 범위 안에서 필요한', '안내된 범위 안에서 필요한'),
    ('reader-source-limit', r'입력된 자료에 맞는 별도의 학습 자료', '학생의 자료에 맞는 별도의 학습 자료'),
    ('reader-source-limit', r'입력에 없는 거리·교통 편의', '확인되지 않은 거리·교통 편의'),
    ('reader-source-limit', r'이때 비용은 입력에 정해진 사실이 없으므로 특정 금액을 비교하기보다', '비용을 비교할 때는'),
    ('reader-reference-label', r'입력된 상담 참고', '상담 참고'),
    ('reader-reference-label', r'입력된 보조 키워드인 영어 수학을 함께 고려한다면', '영어와 수학을 함께 고려한다면'),
    ('reader-reference-label', r'입력된 참고 표현처럼', '이 표현처럼'),
    ('reader-reference-label', r'안내된 지역 정보에는 영어 수학이라는 참고 키워드가 함께 있으므로, 두 과목을 모두 고려하는 가정이라면', '영어와 수학을 함께 고려하는 가정이라면'),
    ('reader-reference-label', r'‘학원상담자료’라는 보조 키워드를 찾는 경우에도', '상담 자료를 준비하는 경우에도'),
    ('reader-reference-label', r'학원교재실과 같은 보조 키워드를 확인할 때에도', '학원의 교재 관리 공간을 확인할 때에도'),
    ('reader-school-list', r'부흥초와 중흥초, 중흥중과 중원고 등이 입력되어 있으므로', '부흥초와 중흥초, 중흥중과 중원고 등이 안내되어 있으므로'),
    ('reader-school-list', r'제일고, 운양고, 운유고가 입력되어 있지만', '제일고, 운양고, 운유고가 안내되어 있지만'),
    ('reader-address-source', r'돋질로 300 4층’이 입력되어 있습니다', '돋질로 300 4층’이 안내되어 있습니다'),
    ('reader-column-reference', r'B열의 검색어는 영어학원이지만 G에는 영어 수학이 함께 제시되어 있습니다\.', '영어와 수학을 함께 고려할 때는 과목별 학습 상태를 나누어 확인해야 합니다.'),
    ('reader-column-reference', r'B열의 검색어는 수학학원이지만 참고 키워드에는 영어 수학이 함께 제시되어 있습니다\.', '영어와 수학을 함께 고려할 때는 과목별 학습 상태를 나누어 확인해야 합니다.'),
    ('reader-column-reference', r'B열의 검색어는 영어학원이지만 상담 참고 항목에 영어 수학이 함께 제시되어 있으므로,', '영어와 수학을 함께 고려한다면,'),
    ('reader-column-reference', r'B열의 검색 의도가 영어학원에 맞더라도', '영어학원을 알아보는 경우에도'),
    ('reader-column-reference', r'B열(?:의)? 검색어(?:는 영어학원이지만|가 수학학원이더라도)', '학원을 알아볼 때'),
    ('reader-column-reference', r'B열의 검색 맥락처럼', '학원을 알아보며'),
    ('reader-combined-search', r'(?:입력된 |입력 |참고 )?검색어(?:에|에는) 영어(?:와 | )수학이 함께 포함되어 있거나 두 과목을 동시에 (?:관리해야 한다면|관리하려는 상황이라면|상담하려는 경우에는|알아보는 가정이라면),?', '영어와 수학을 함께 고려한다면'),
    ('reader-combined-search', r'(?:입력된 |입력 |참고 )?검색어(?:에|에는) 영어(?:와 | )수학이 함께 포함되어 (?:있다면|있더라도)', '영어와 수학을 함께 고려한다면'),
    ('reader-combined-search', r'(?:입력된 |입력 |참고 )?검색어(?:에|에는) 영어(?:와 | )수학이 함께 포함되어 있으므로', '영어와 수학을 함께 고려할 때는'),
    ('reader-combined-search', r'(?:입력된 |입력 |참고 )?검색어에 영어 수학이 (?:함께 )?포함된 경우(?:에는|라면|에도)', '영어와 수학을 함께 고려한다면'),
    ('reader-combined-search', r'(?:입력된 |입력 )?검색어가 영어(?:와 | )수학을 함께 (?:포함하고 있다면|포함한다면|가리키고 있다면|가리키는 경우라도)', '영어와 수학을 함께 고려한다면'),
    ('reader-combined-search', r'입력된 검색어가 영어 수학을 함께 포함하므로', '영어와 수학을 함께 고려할 때는'),
    ('reader-combined-search', r'입력된 검색어가 두 과목을 함께 포함하더라도', '영어와 수학을 함께 고려하더라도'),
    ('reader-combined-search', r'입력된 검색어가 두 과목을 포함하더라도', '영어와 수학을 함께 고려하더라도'),
    ('reader-combined-search', r'검색어를 영어 수학으로 함께 살펴보는 가정이라면', '영어와 수학을 함께 살펴보는 가정이라면'),
    ('reader-combined-search', r'(?:입력 )?검색어에 영어 수학을 함께 고려(?:하고 있다면|하는 의도가 있다면)', '영어와 수학을 함께 고려한다면'),
    ('reader-combined-search', r'영어 수학이라는 검색어로 함께 알아보(?:더라도|는 경우에는)', '영어와 수학을 함께 알아보더라도'),
    ('reader-combined-search', r'입력 검색어(?:는 수학학원이지만|가 수학학원이더라도)', '수학학원을 알아보는 경우에도'),
    ('reader-combined-search', r'입력된 검색어에는 영어 수학을 함께 살펴보려는 의도가 포함되어 있으므로,', '영어와 수학을 함께 살펴본다면,'),
    ('reader-combined-search', r'키워드에 영어 수학이 함께 포함되어 있더라도', '영어와 수학을 함께 고려하더라도'),
    ('reader-combined-search', r'입력된 키워드가 두 과목을 함께 가리키더라도', '영어와 수학을 함께 고려하더라도'),
    ('reader-combined-search', r'입력된 상담 소재에 영어 수학이 함께 포함되어 있다면', '영어와 수학을 함께 고려한다면'),
    ('reader-combined-search', r'입력된 검색어에는 영어와 수학이 함께 제시되어 있으므로', '영어와 수학을 함께 고려한다면'),
    ('reader-combined-search', r'입력된 검색어가 수학학원(?:이라도|이더라도)', '수학학원을 알아보는 경우에도'),
    ('reader-combined-search', r'검색어에 영어 수학을 함께 넣었더라도', '영어와 수학을 함께 고려하더라도'),
    ('reader-combined-search', r'검색어에 영어 수학이 함께 포함된 가정이라면', '영어와 수학을 함께 고려하는 가정이라면'),
    ('reader-combined-search', r'입력 검색어에 영어와 수학이 함께 포함된 경우라도', '영어와 수학을 함께 고려하더라도'),
    ('reader-combined-search', r'입력된 (?:검색 맥락|검색 대상)', '학원 탐색 목적'),
    ('reader-combined-search', r'입력에 영어[· ]수학이 함께', '상담 항목에 영어와 수학이 함께'),
    ('reader-combined-search', r'입력에 영어 수학이라는', '상담 항목에 영어 수학이라는'),
    ('reader-combined-search', r'입력에 영어 수학을', '상담 항목에 영어와 수학을'),
    ('reader-search-wording', r'같은 영어학원 검색어로 (?:찾아도|찾아보더라도|상담을 받아도)', '같은 영어학원을 알아보더라도'),
    ('reader-search-wording', r'검색어가 영어학원이더라도', '영어학원을 알아보는 경우에도'),
    ('reader-search-wording', r'‘영어 수학’이라는 검색어만으로', '두 과목을 함께 다룬다는 말만으로'),
    ('reader-search-wording', r'검색어에 보이는 동네명', '검색할 때 보이는 동네명'),
    ('reader-search-wording', r'학교명이나 검색어에 맞춘 홍보 문구', '학교명을 내세운 홍보 문구'),
    ('reader-search-wording', r'학교명이나 검색어만으로', '학교명만으로'),
    ('reader-search-wording', r'지역과 검색어만으로', '지역만으로'),
    ('reader-search-wording', r'지역명이나 검색어에 끌리기보다', '지역명만 보고 판단하기보다'),
    ('reader-search-wording', r'검색어에만 머무르지 않고', '검색할 때 본 표현에만 머무르지 않고'),
    ('reader-search-wording', r'검색어만 보고 결정하는', '검색할 때 본 표현만으로 결정하는'),
    ('reader-search-wording', r'학원교재실이라는 검색어를 학원 상담에서 어떻게 확인하면 좋나요', '학원의 교재 관리 공간은 상담에서 어떻게 확인하면 좋나요'),
    ('reader-search-wording', r'같은 수학학원 검색어를 사용해도', '같은 수학학원을 알아보더라도'),
    ('reader-search-wording', r'제공된 검색어만으로', '학원을 함께 찾는다는 이유만으로'),
    ('reader-search-wording', r'검색어만으로 필요한 수업 비중', '두 과목을 함께 찾는다는 이유만으로 필요한 수업 비중'),
    ('reader-search-wording', r'‘입시관리학원’이라는 검색어가 눈에 들어오더라도', '‘입시관리학원’이라는 표현이 눈에 들어오더라도'),
    ('reader-operation-word', r'학원보강', '보강'),
    ('reader-operation-word', r'학원주차', '주차'),
)


def polish_manuscript(record: dict) -> tuple[dict, list[dict]]:
    """Return (independent display record, exact phrase-change records).

    Each change has ``field``, ``rule``, ``count``, ``before`` and ``after``.
    Before/after describe the exact replaced phrase, not the whole paragraph.
    Only title/meta/intro, section headings/paragraphs, FAQ and cases are visited.
    Callers must retain a visible consultation-situation label for the cases.
    """
    polished = deepcopy(record)
    changes: list[dict] = []

    def update(container: dict | list, key: str | int, field: str) -> None:
        value = container[key]
        if not isinstance(value, str):
            return
        for rule, before, after, pattern in _COMPILED_RULES:
            value, count = pattern.subn(after, value)
            if count:
                changes.append({
                    'field': field, 'rule': rule, 'count': count,
                    'before': before, 'after': after,
                })
        # This later review does not change source titles, metadata, or headings.
        if field not in ('title', 'meta') and not field.endswith('.heading'):
            for rule, expression, after in _READER_RULES:
                matches = Counter(re.findall(expression, value))
                if matches:
                    value = re.sub(expression, lambda _: after, value)
                    for before, count in matches.items():
                        changes.append({'field': field, 'rule': rule, 'count': count,
                                        'before': before, 'after': after})
        container[key] = value

    for field in ('title', 'meta', 'intro'):
        if field in polished:
            update(polished, field, field)
    for index, section in enumerate(polished.get('sections', [])):
        if 'heading' in section:
            update(section, 'heading', f'sections[{index}].heading')
        for paragraph_index in range(len(section.get('paragraphs', []))):
            update(section['paragraphs'], paragraph_index, f'sections[{index}].paragraphs[{paragraph_index}]')
    for index, item in enumerate(polished.get('faq', [])):
        for field in ('question', 'answer'):
            if field in item:
                update(item, field, f'faq[{index}].{field}')
    for index in range(len(polished.get('cases', []))):
        update(polished['cases'], index, f'cases[{index}]')
    return polished, changes
