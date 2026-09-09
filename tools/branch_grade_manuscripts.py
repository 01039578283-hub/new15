"""Read-only, grade-specific manuscripts; no generic locality editorial overlay.

The strict source block parser is shared, but grade titles and topics stay
independent from the existing neighborhood manuscripts. Only reviewed wording
and safe complete-sentence introduction selection are applied for display.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
from itertools import combinations
from pathlib import Path
import re
import stat
import unicodedata
from zipfile import BadZipFile, ZipFile

from branch_manuscripts import (
    ManuscriptFormatError, MAX_ARCHIVE_BYTES, MAX_UNCOMPRESSED_BYTES,
    MAX_MEMBER_BYTES, MAX_MEMBERS, _member_path, _parse,
)
from polish_branch_manuscripts import polish_manuscript


EXPECTED_MANUSCRIPTS = 371
SUPPORTED_GRADES = ('초5', '초6', '중1', '중2', '중3', '고1', '고2')
INTRO_TARGET_MAX = 230
_GENERIC = ('고2', '영어', '수학', '학원', '학생', '학습', '상담', '확인', '기준',
            '비교', '학교', '자료', '준비', '질문', '선택', '과정', '방법', '먼저',
            '현재', '필요', '기록', '복습', '피드백', '나누', '살펴', '정리', '점검')
_GYOHA_PHRASES = (
    ('모르는 척 넘기는 습관', '모르는 부분을 숨기고 넘기는 습관'),
    ('모르는 척하는 순간을 먼저 구분해 보기', '모르는 부분을 숨기는 순간을 먼저 구분해 보기'),
    ('학생이 모르는 척 넘긴 문항', '학생이 모르는 부분을 숨기고 넘긴 문항'),
    ('모르는 척한다고 판단하는 기준', '모르는 부분을 숨긴다고 판단하는 기준'),
    ('모르는 척하는 학생은 수업을 따라가기 어려운 학생으로 봐야 하나요?',
     '모르는 부분을 숨기는 학생은 수업을 따라가기 어려운 학생으로 봐야 하나요?'),
)
_SCHOOL = re.compile(
    r'(?<![가-힣A-Za-z0-9])([가-힣0-9]{1,16}?(?:초등학교|중학교|고등학교|여중|여고|초|중|고))'
    r'(?=(?:이나|처럼|에서|은|는|이|가|을|를|와|과|로|의|,|·|/|\s|$))')
_NOT_SCHOOLS = {'참고', '그리고', '말고', '않고', '보고', '집중', '그중', '이중', '도중',
                '고등', '중고', '초중', '과정중', '수업중', '학습중', '재학중', '비중'}
_SCHOOL_CONTEXT = re.compile(
    r'(?:제공된|제시된|안내된|참고|입력된).{0,12}학교|학교.{0,30}(?:제공|제시|포함)|'
    r'학교명이 상담 대상|학교 가운데')
_KEEP_SCHOOL_HISTORY = re.compile(
    r'진학한|진학하기 전|학습 이력|학습한 경험|중학교 때|보조 자료|범위를 분리|'
    r'상담과 범위|이전에|출신|자료가 아니|확대해석|연결해 판단할 근거')
_SCHOOL_SEPARATOR = re.compile(r'(?:\s|,|·|/|와|과|및|또는|이나|나)*\Z')
_SCHOOL_FALLBACK = '고2 상담에서는 재학 중인 고등학교의 수업 자료와 현재 평가 범위를 준비해 주세요.'
# These additional source-column phrases were observed in the 고1 attachments.
# Keep them grade-scoped so an extension cannot alter an existing 고2 display.
_HIGH1_READER_PHRASES = (
    ('D열에 제공된 학교', '안내된 학교'),
    ('D열에 제시된 학교', '안내된 학교'),
    ('D에 제시된 학교', '안내된 학교'),
    ('D열에 수업 학교 정보가', '이 안내에 수업 학교 정보가'),
    ('D열에 학교 정보가', '이 안내에 학교 정보가'),
    ('ROW_DATA에 제시된 학교', '안내된 학교'),
    ('E열의 주소 정보', '안내된 주소 정보'),
    ('E열의 주소', '안내된 주소'),
    ('E열에 제공된 주소', '안내된 주소'),
    ('G열의 참고 표현인', '상담 참고 항목인'),
    ('G열의 참고 표현처럼 ', ''),
    ('G열의 ‘영어 수학’이라는 참고 표현처럼', '영어·수학을 함께 고려할 때처럼'),
    ('‘영어 수학’이라는 검색 의도만으로 두 과목의 운영을 추측하기보다',
     '영어·수학을 함께 찾고 있더라도 두 과목의 운영을 추측하기보다'),
    ('제공 사실로 간주하지 말고', '확인된 운영 사실로 간주하지 말고'),
    ('이 원고에서 판단하지 않습니다', '이 안내에서 판단하지 않습니다'),
    ('이 원고에서 확인할 수 없는 조건', '이 안내에서 확인할 수 없는 조건'),
    ('학교명을 입력하지 않은 상황이라면', '학교명이 확인되지 않은 상황이라면'),
    ('입력된 주소', '안내된 주소'),
    ('입력에 있는 주소', '안내된 주소'),
    ('입력에 있는 보조 위치 자료', '안내된 보조 위치 자료'),
    ('입력에 없는 교통 편의', '확인되지 않은 교통 편의'),
    ('입력에 없는 항목', '확인되지 않은 항목'),
    ('이번 입력에는 특정 수업학교', '이 안내에는 특정 수업학교'),
    ('이 입력에 제시된 것은 아닙니다', '이 안내에서 확인되는 것은 아닙니다'),
    ('입력된 참고 표현인', '상담 참고 항목인'),
    ('입력된 비교 키워드인', '상담 참고 항목인'),
    ('입력된 참고 키워드인', '상담 참고 항목인'),
    ('입력된 상담 소재', '상담 참고 항목'),
    ('입력 정보에 영어와 수학이 함께 제시된 경우처럼', '영어와 수학을 함께 고려하는 경우처럼'),
    ('입력 자료에 영어 수학이 함께 제시된 만큼', '영어와 수학을 함께 고려하는 경우'),
    ('입력 자료에 없는', '이 안내에서 확인되지 않은'),
    ('입력 자료와 상담 답변', '참고 자료와 상담 답변'),
    ('입력 사실만으로', '이 안내만으로'),
    ('입력으로 확인되지 않았으므로', '이 안내에서 확인되지 않았으므로'),
    ('입력에 제공되지 않았으므로', '이 안내에서 확인되지 않았으므로'),
    ('입력에 제시되지 않은 정보', '이 안내에서 확인되지 않은 정보'),
    ('입력에 제시된 노형초, 서중, 중앙중', '안내된 노형초, 서중, 중앙중'),
    ('수업학교로 입력된', '참고 학교로 안내된'),
    ('제일고, 이현고가 입력되어', '제일고, 이현고가 제시되어'),
    ('한빛고와 복정고 등이 입력되어', '한빛고와 복정고 등이 제시되어'),
)


def _high1_reader_context(value):
    for before, after in _HIGH1_READER_PHRASES:
        value = value.replace(before, after)
    # Sentence-initial source-preparation wording only. Speech/essay manuscripts
    # inside learning explanations (발표 원고, 원고 사용, 원고를 본 상태) stay intact.
    starts = (
        ('원고를 준비할 때 함께 확인하고 싶은 키워드가 영어 수학이라면',
         '상담에서 영어와 수학을 함께 알아본다면'),
        ('원고를 준비할 때 함께 확인할 소재로 영어 수학을 생각한다면',
         '상담에서 영어와 수학을 함께 알아본다면'),
        ('원고에서 함께 확인할 키워드가 영어 수학이라면', '영어와 수학을 함께 알아본다면'),
        ('원고에서 영어와 수학을 함께 검색하거나 상담하려는 경우에는',
         '영어와 수학을 함께 알아보거나 상담하려는 경우에는'),
        ('원고를 준비하면서', '상담을 준비하면서'),
        ('원고를 준비할 때', '상담을 준비할 때'),
        ('원고를 준비하는', '상담을 준비하는'),
        ('원고를 준비하며', '상담을 준비하며'),
        ('원고를 알아보는 과정에서', '학습 정보를 알아보는 과정에서'),
        ('원고를 검색하는 학부모', '학습 정보를 찾는 학부모'),
        ('원고를 찾는 학부모', '학습 정보를 찾는 학부모'),
    )
    for before, after in starts:
        value = re.sub(r'(\A|(?<=[.!?])\s+)' + re.escape(before),
                       lambda m: m[1] + after, value)
    return value


_MIDDLE_READER_PHRASES = (
    ('D열에 제시된 ', '안내된 '), ('D열에 학교명이', '이 안내에 학교명이'),
    ('D열에 학교 정보로 제시된', '참고 학교로 안내된'),
    ('D열에는 ', '참고 학교 정보에는 '),
    ('원고 참고 소재로 제시된', '상담 참고 항목인'),
    ('원고나 상담 자료에서 영어 수학을 함께 안내하더라도',
     '상담 자료에서 영어와 수학을 함께 안내하더라도'),
    ('이 원고에서 확인할 수 없는 항목', '이 안내에서 확인할 수 없는 항목'),
    ('이 원고에서 구체적인 수업 방식이나 성과를 알 수 없으므로',
     '이 안내에서 구체적인 수업 방식이나 성과를 알 수 없으므로'),
    ('이 원고에 없는 사항', '이 안내에 없는 사항'),
    ('학원 운영 여부는 원고에서 단정할 수 없습니다', '학원 운영 여부는 이 안내에서 단정할 수 없습니다'),
    ('제공 사실을 단정하지 말고', '확인된 운영 사실로 단정하지 말고'),
    ('‘영어 수학’이라는 검색 의도가 함께 있을 때도', '영어와 수학을 함께 알아볼 때도'),
    ('‘영어 수학’이라는 검색 의도가 함께 있다면', '영어와 수학을 함께 알아본다면'),
    ('‘영어 수학’이라는 검색 의도는', '영어와 수학을 함께 알아보려는 생각은'),
    ('입력된 검색 의도에는 영어와 수학을 함께 살펴보려는 필요가 포함될 수 있지만',
     '영어와 수학을 함께 살펴볼 필요가 있더라도'),
    ('학원추천이라는 검색 의도만으로 한 곳을 바로 정하기보다',
     '학원 추천만으로 한 곳을 바로 정하기보다'),
    ('학부모의 검색 의도로 연결해 볼 수 있습니다', '학부모의 상담 질문으로 연결해 볼 수 있습니다'),
    ('입력된 지역', '안내된 지역'), ('입력된 학원 주소', '안내된 학원 주소'),
    ('입력된 보조 위치 자료', '안내된 보조 위치 자료'),
    ('입력된 참고 키워드가', '상담 참고 항목이'),
    ('입력된 참고 키워드에', '상담 참고 항목에'),
    ('입력된 학원교재라는 키워드도', '학원 교재라는 상담 항목도'),
    ('입력에 함께 제시된', '상담 참고 항목인'),
    ('입력에 학교명이', '이 안내에 학교명이'),
    ('학교명이 입력되어 있지 않으므로', '학교명이 확인되지 않았으므로'),
    ('입력 자료에 포함된 학교', '안내된 학교'),
    ('입력에 없는 학교별 특성', '확인되지 않은 학교별 특성'),
    ('입력된 학습 관심사가', '학습 관심사가'),
    ('입력된 검색 관심사가', '학습 관심사가'),
    ('학교 정보로는 입력된 목록에', '참고 학교 목록에는'),
    ('입력 자료에 영어·수학이 함께 제시된 경우', '영어와 수학을 함께 고려하는 경우'),
    ('입력 정보에 포함되어 있더라도', '참고 정보에 포함되어 있더라도'),
    ('입력 정보에 없는 사항', '이 안내에서 확인되지 않은 사항'),
    ('입력 자료로 확인되지 않았으므로', '이 안내에서 확인되지 않았으므로'),
    ('입력 자료에 포함되어 있지 않으므로', '이 안내에서 확인되지 않았으므로'),
    ('입력에서 함께 확인할 키워드가', '상담에서 함께 확인할 항목이'),
    ('입력에 제시된 문시중과 세마중', '안내된 문시중과 세마중'),
    ('입력에 제시된 신용초, 용곡중, 신방중, 청수고, 쌍용고, 천안여고',
     '안내된 신용초, 용곡중, 신방중, 청수고, 쌍용고, 천안여고'),
    ('현재 입력에는', '현재 안내에는'),
    ('광주여고, 상일여고가 입력되어 있지만', '광주여고, 상일여고가 안내되어 있지만'),
)


def _middle_reader_context(value):
    value = _high1_reader_context(value)
    for before, after in _MIDDLE_READER_PHRASES:
        value = value.replace(before, after)
    starts = (
        ('원고를 찾는 보호자', '학습 정보를 찾는 보호자'),
        ('원고를 찾아보는 보호자', '학습 정보를 찾아보는 보호자'),
        ('원고를 찾는 가정', '학습 정보를 찾는 가정'),
        ('원고를 알아보는 가정', '학습 정보를 알아보는 가정'),
        ('원고를 참고할 때', '이 안내를 참고할 때'),
        ('원고를 참고하는', '이 안내를 참고하는'),
        ('원고를 확인하는 학부모', '이 안내를 확인하는 학부모'),
        ('원고에서 함께 살펴볼 보조 기준은', '함께 살펴볼 보조 기준은'),
        ('원고에서 확인할 보조 키워드가 영어와 수학인 만큼', '영어와 수학을 함께 알아보는 경우'),
        ('원고 영어와 수학을 함께 고려한다면', '영어와 수학을 함께 고려한다면'),
    )
    for before, after in starts:
        value = re.sub(r'(\A|(?<=[.!?])\s+)' + re.escape(before),
                       lambda m: m[1] + after, value)
    return value


_MIDDLE_SCHOOL = re.compile(_SCHOOL.pattern.replace('이나|처럼', '이나|나|처럼'))
_MIDDLE_HISTORY = re.compile(
    r'진학|출신|이전|과거|이력|초등학교 때|초등 시절|중학교 때|보조 자료|'
    r'범위를 분리|상담과 범위|고등.{0,15}(?:준비|과정|이후)|'
    r'고교.{0,15}(?:준비|과정|이후)|자료가 아니|확대해석|연결해 판단할 근거')


def _middle_school_lists(value, grade):
    """Retain middle-school names in clear current-student enumerations only.

    High-school progression, earlier education, and mixed background statements
    remain source text. No school alias is expanded and no school is invented.
    """
    fallback = f'{grade} 상담에서는 재학 중인 중학교의 수업 자료와 현재 평가 범위를 준비해 주세요.'

    def sentence(text):
        if text.endswith('?') or not _SCHOOL_CONTEXT.search(text) or _MIDDLE_HISTORY.search(text):
            return text
        names = [m for m in _MIDDLE_SCHOOL.finditer(text) if m[1] not in _NOT_SCHOOLS]
        groups = []
        for match in names:
            if groups and _SCHOOL_SEPARATOR.fullmatch(text[groups[-1][-1].end():match.start()]):
                groups[-1].append(match)
            else:
                groups.append([match])
        for group in reversed(groups):
            middle = [m[1] for m in group if m[1].endswith(('중', '중학교'))]
            others = [m for m in group if not m[1].endswith(('중', '중학교'))]
            if not others:
                continue
            if middle:
                start, end = group[0].start(), group[-1].end()
                tail = text[end:]
                consonant = (ord(middle[-1][-1]) - 0xAC00) % 28 != 0
                pairs = [('가 ', '이 '), ('는 ', '은 '), ('와 ', '과 '), ('를 ', '을 ')]
                if not consonant:
                    pairs = [(b, a) for a, b in pairs]
                for before, after in pairs:
                    if tail.startswith(before):
                        tail = after + tail[len(before):]
                        break
                text = text[:start] + ', '.join(middle) + tail
            elif (not any(m[1].endswith(('중', '중학교')) for m in names)
                  and not re.search(r'\d|[A-Za-z]|[×÷=]', text.replace(grade, ''))
                  and not re.search(r'지역 정보|이 학교들|이 이름들|그 학교|이것만으로', value)):
                # Only a self-contained list statement is safe to replace.
                # Longer clauses may contain progression or learning detail.
                if re.fullmatch(r'(?:제공된|안내된|참고) 학교 (?:정보|목록)(?:에는|에는|에) .+?'
                                r'(?:포함되어 있습니다|제시되어 있습니다|있습니다)\.', text):
                    return fallback
        return text

    return re.sub(r'[^.!?]+[.!?](?:[”’])?|[^.!?]+$',
                  lambda m: m[0][:len(m[0]) - len(m[0].lstrip())] + sentence(m[0].lstrip()), value)


_ELEMENTARY_READER_PHRASES = (
    ('G에 제공된 영어 수학', '상담 참고 항목인 영어와 수학'),
    ('D열에 기재된 동중', '안내된 동중'),
    ('D에 제시된 아람초와 행신초', '안내된 아람초와 행신초'),
    ('두 과목을 모두 살펴보고 싶다는 검색 의도로 연결할 수 있습니다',
     '두 과목을 모두 살펴보기 위한 상담 질문으로 연결할 수 있습니다'),
    ('두 과목을 모두 살펴보려는 검색 의도로 연결할 수 있습니다',
     '두 과목을 모두 살펴보기 위한 상담 질문으로 연결할 수 있습니다'),
    ('‘평일수업’이라는 검색 의도도', '평일 수업을 알아볼 때도'),
    ('‘조용한학원’이라는 검색 의도를 실제 비교 기준으로 바꿀 수 있습니다',
     '조용한 학습 환경을 실제로 비교할 수 있습니다'),
    ('원고에서 함께 확인할 키워드로 영어 수학을 생각하고 있다면',
     '영어와 수학을 함께 알아보고 있다면'),
    ('원고를 준비하거나 상담할 때', '상담을 준비하거나 진행할 때'),
    ('이 원고에서 확인되는 학교명', '이 안내에서 확인되는 학교명'),
    ('원고에서 영어와 수학을 함께 고려해야 한다면', '영어와 수학을 함께 고려해야 한다면'),
    ('원고에서 함께 확인할 보조 기준은 영어 수학 병행입니다',
     '함께 확인할 보조 기준은 영어와 수학의 병행입니다'),
    ('원고에서 함께 확인할 키워드인 영어와 수학은', '영어와 수학을 함께 알아볼 때는'),
    ('이 원고에 없는 운영 정보', '이 안내에서 확인되지 않은 운영 정보'),
    ('원고를 비교할 때 ‘영어 수학’이 함께 언급되는 경우에는',
     '영어와 수학을 함께 비교하는 경우에는'),
    ('원고에서 함께 확인할 키워드가 영어와 수학이라면', '영어와 수학을 함께 알아본다면'),
    ('원고나 상담 과정에서 영어 수학을 함께 고려한다면', '상담에서 영어와 수학을 함께 고려한다면'),
    ('입력에 없는 비용 정보', '확인되지 않은 비용 정보'),
    ('입력 자료의 상담 참고 항목인', '상담 참고 항목인'),
    ('입력된 검색 키워드에는 영어와 수학이 함께 포함되어 있습니다',
     '영어와 수학을 함께 알아보는 가정도 있을 수 있습니다'),
    ('입력에 제공된 사실이 아니므로', '이 안내에서 확인되지 않았으므로'),
    ('입력에 제공된 주소 정보', '안내된 주소 정보'),
    ('입력된 보조 주소', '안내된 보조 주소'),
    ('입력에 제시된 영어 수학', '상담 참고 항목인 영어와 수학'),
    ('입력에 제시된 영어·수학', '상담 참고 항목인 영어·수학'),
    ('입력에 제공된 보조 주소', '안내된 보조 주소'),
    ('학교별 시험 경향까지 입력된 것은 아닙니다', '학교별 시험 경향까지 확인된 것은 아닙니다'),
    ('입력된 참고 키워드처럼', '상담 참고 항목처럼'),
    ('입력에 있는 천보중, 효자중, 효자고, 경민it고', '안내된 천보중, 효자중, 효자고, 경민it고'),
    ('입력에 확인되어 있지 않으므로', '이 안내에서 확인되지 않았으므로'),
    ('입력에 있는 영어 수학 소재', '영어와 수학이라는 상담 소재'),
    ('입력된 두 과목을 실제 개설 과목', '안내된 두 과목을 실제 개설 과목'),
    ('입력에 제시된 상담 참고 항목는', '상담 참고 항목은'),
    ('입력에 포함된 염경초, 염동초, 백석초', '안내된 염경초, 염동초, 백석초'),
    ('입력 자료의 보조 키워드가 영어 수학인 만큼', '영어와 수학을 함께 고려하는 경우'),
    ('입력된 자료에는', '이 안내에는'),
    ('입력된 참고 표현에', '상담 참고 항목에'),
    ('입력에 성리초와 성리중이 함께 제시되어 있으므로',
     '참고 학교 정보에 성리초와 성리중이 함께 제시되어 있으므로'),
    ('입력에 없는 거리나 교통 편의', '확인되지 않은 거리나 교통 편의'),
    ('입력에 포함된 와룡초와 성산중', '안내된 와룡초와 성산중'),
    ('입력에 있는 ‘영어 수학’이라는 관심사', '영어와 수학을 함께 알아보려는 관심사'),
    ('입력된 정보가 없으므로', '이 안내에서 확인되지 않았으므로'),
    ('입력된 키워드만으로', '안내된 표현만으로'),
    ('학교 관련 입력에는', '참고 학교 정보에는'),
)


def _elementary_reader_context(value):
    value = _middle_reader_context(value)
    for before, after in _ELEMENTARY_READER_PHRASES:
        value = value.replace(before, after)
    return value


_ELEMENTARY_HISTORY = re.compile(
    r'진학|출신|이전|과거|이력|보조 자료|범위를 분리|상담과 범위|'
    r'중(?:학교|등|학).{0,20}(?:준비|과정|이후|연결|전환|대비)|'
    r'고(?:등학교|등|교).{0,20}(?:준비|과정|이후|연결|전환|대비)|'
    r'자료가 아니|확대해석|연결해 판단할 근거')


def _elementary_school_lists(value, grade):
    """Keep elementary names in current-student lists, not progression prose."""
    if _ELEMENTARY_HISTORY.search(value):
        return value
    fallback = f'{grade} 상담에서는 재학 중인 초등학교의 수업 자료와 현재 학습 범위를 준비해 주세요.'

    def sentence(text):
        if text.endswith('?') or not _SCHOOL_CONTEXT.search(text):
            return text
        names = [m for m in _MIDDLE_SCHOOL.finditer(text) if m[1] not in _NOT_SCHOOLS]
        groups = []
        for match in names:
            if groups and _SCHOOL_SEPARATOR.fullmatch(text[groups[-1][-1].end():match.start()]):
                groups[-1].append(match)
            else:
                groups.append([match])
        for group in reversed(groups):
            elementary = [m[1] for m in group if m[1].endswith(('초', '초등학교'))]
            others = [m for m in group if not m[1].endswith(('초', '초등학교'))]
            if not others:
                continue
            if elementary:
                start, end = group[0].start(), group[-1].end()
                tail = text[end:]
                # Original elementary spellings end in 초 or 교 (no 받침).
                for before, after in [('이 ', '가 '), ('은 ', '는 '), ('과 ', '와 '), ('을 ', '를 ')]:
                    if tail.startswith(before):
                        tail = after + tail[len(before):]
                        break
                text = text[:start] + ', '.join(elementary) + tail
            elif (not any(m[1].endswith(('초', '초등학교')) for m in names)
                  and not re.search(r'\d|[A-Za-z]|[×÷=]', text.replace(grade, ''))
                  and not re.search(r'지역 정보|이 학교들|이 이름들|그 학교|이것만으로', value)):
                if re.fullmatch(r'(?:제공된|안내된|참고) 학교 (?:정보|목록)(?:에는|에) .+?'
                                r'(?:포함되어 있습니다|제시되어 있습니다|있습니다)\.', text):
                    return fallback
        return text

    return re.sub(r'[^.!?]+[.!?](?:[”’])?|[^.!?]+$',
                  lambda m: m[0][:len(m[0]) - len(m[0].lstrip())] + sentence(m[0].lstrip()), value)


def _school_list_sentence(sentence, grade='고2'):
    """Narrow supplied-list correction; never infer or expand a school name.

    Historical middle-school references and explicitly separate family advice are
    retained. Only contiguous enumerations in supplied-school context qualify.
    Unclear prose is kept for review, not silently classified as a target list.
    """
    if (sentence.endswith('?') or not _SCHOOL_CONTEXT.search(sentence)
            or _KEEP_SCHOOL_HISTORY.search(sentence)):
        return sentence
    names = [m for m in _SCHOOL.finditer(sentence) if m[1] not in _NOT_SCHOOLS]
    groups = []
    for match in names:
        if groups and _SCHOOL_SEPARATOR.fullmatch(sentence[groups[-1][-1].end():match.start()]):
            groups[-1].append(match)
        else:
            groups.append([match])
    for group in reversed(groups):
        lower = [m for m in group if m[1].endswith(('초', '중', '초등학교', '중학교'))]
        if not lower:
            continue
        high = [m[1] for m in group if m[1].endswith(('고', '고등학교'))]
        if high:
            start, end = group[0].start(), group[-1].end()
            tail = sentence[end:]
            # Every retained spelling ends in 고 or 교, so use vowel particles.
            particles = [('이 ', '가 '), ('은 ', '는 '), ('과 ', '와 ')]
            if grade == '고1':
                particles.append(('을 ', '를 '))
            for before, after in particles:
                if tail.startswith(before):
                    tail = after + tail[len(before):]
                    break
            sentence = sentence[:start] + ', '.join(high) + tail
        else:
            # A no-high-school list is replaced only if it is an unmistakable
            # supplied-list statement. Preserve any subsequent caution clause.
            if (not re.search(r'학교.{0,8}(?:정보|명|목록)|학교명', sentence)
                    or not re.search(r'포함|적혀|제시|제공', sentence)
                    or any(m[1].endswith(('고', '고등학교')) for m in names)):
                continue
            if grade == '고1' and '제공된 지역 정보' in sentence:
                # Do not erase a mixed region/family background sentence just
                # to replace an all-lower-school list with generic advice.
                continue
            if re.search(r'\d|[A-Za-z]|[×÷=]', sentence.replace(grade, '')):
                continue
            caution = re.search(r'(?:하지만|있지만|으며|으므로|이므로|이며|이고),\s+(.+)', sentence)
            if caution and re.search(r'단정|추정|판단|별도로 확인', caution[1]):
                tail = caution[1]
                tail = re.sub(r'^(?:이 정보만으로|이 명칭만으로|학교명만으로)\s*',
                              '학교 이름만으로 ', tail)
                return _SCHOOL_FALLBACK.replace('고2', grade) + ' ' + tail
            return _SCHOOL_FALLBACK.replace('고2', grade)
    return sentence


def _school_lists(value, grade='고2'):
    # Keep original whitespace everywhere except a sentence that is corrected.
    result = re.sub(r'[^.!?]+[.!?](?:[”’])?|[^.!?]+$',
                    lambda m: (m[0][:len(m[0]) - len(m[0].lstrip())]
                               + _school_list_sentence(m[0].lstrip(), grade)), value)
    fallback = _SCHOOL_FALLBACK.replace('고2', grade)
    if fallback in result and fallback not in value:
        # Keep already qualified school references when removing the list would
        # strand a following demonstrative. These are reviewable, not targets.
        if re.search(r'이 학교들|이 이름들|그 학교|이것만으로', value):
            return value
    return result


def load_grade_archive(path: Path, subject: str, grade: str = '고2') -> list[dict]:
    """Load exactly 371 safe UTF-8 records, sorted by locality.

    ``subject`` is 영어/수학; a prefix matching the selected grade is also
    accepted. Returned ``subject`` is normalized and ``grade`` is added.
    The source title/member/hash are not rewritten. No ZIP member is extracted.
    """
    if grade not in SUPPORTED_GRADES:
        raise ManuscriptFormatError(f'Unsupported grade: {grade}')
    if subject.startswith(grade + ' '):
        subject = subject[len(grade) + 1:]
    if subject not in ('영어', '수학'):
        raise ManuscriptFormatError(f'Unsupported subject: {subject}')
    path = Path(path)
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ManuscriptFormatError('Archive exceeds compressed size limit')
    archive_bytes = path.read_bytes()
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ManuscriptFormatError('Archive exceeds actual compressed size limit')
    archive_sha = hashlib.sha256(archive_bytes).hexdigest()
    qualified_subject = grade + ' ' + subject
    category = qualified_subject + '학원'
    result, seen_members, seen_localities = [], set(), set()
    try:
        with ZipFile(BytesIO(archive_bytes)) as archive:
            members = archive.infolist()
            if not members or len(members) > MAX_MEMBERS:
                raise ManuscriptFormatError('Archive member count outside limits')
            if sum(m.file_size for m in members) > MAX_UNCOMPRESSED_BYTES:
                raise ManuscriptFormatError('Archive exceeds uncompressed size limit')
            for info in members:
                member = _member_path(info.filename, category, info.is_dir())
                if member in seen_members:
                    raise ManuscriptFormatError(f'Duplicate ZIP path: {member}')
                seen_members.add(member)
                if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                    raise ManuscriptFormatError(f'Link or encrypted ZIP member: {member}')
                if info.is_dir():
                    continue
                if not member.endswith('.txt') or not (0 < info.file_size <= MAX_MEMBER_BYTES):
                    raise ManuscriptFormatError(f'Unexpected member type or size: {member}')
                with archive.open(info) as stream:
                    raw = stream.read(MAX_MEMBER_BYTES + 1)
                if len(raw) != info.file_size or len(raw) > MAX_MEMBER_BYTES:
                    raise ManuscriptFormatError(f'Member exceeds actual size limit: {member}')
                record = _parse(raw, member, qualified_subject, archive_sha)
                locality_key = unicodedata.normalize('NFC', record['locality'])
                if locality_key in seen_localities:
                    raise ManuscriptFormatError(f'Duplicate locality: {record["locality"]}')
                seen_localities.add(locality_key)
                record['subject'] = subject
                record['grade'] = grade
                result.append(record)
    except (BadZipFile, NotImplementedError, RuntimeError) as exc:
        raise ManuscriptFormatError(f'Invalid or unsupported ZIP archive: {path.name}') from exc
    if len(result) != EXPECTED_MANUSCRIPTS:
        raise ManuscriptFormatError(f'Expected {EXPECTED_MANUSCRIPTS} manuscripts; found {len(result)}')
    return sorted(result, key=lambda row: row['locality'])


def _sentences(value):
    return [s for s in re.split(r'(?<=[.!?])\s+', value.strip()) if s]


def _short_intro(record):
    value = record['intro']
    if len(value) <= INTRO_TARGET_MAX:
        return value
    sentences = _sentences(value)
    terms = {word[:3] for section in record['sections'][:3]
             for word in re.findall(r'[가-힣A-Za-z]+', section['heading'])
             if len(word) > 1 and not word.startswith((record['grade'],) + _GENERIC)}
    coverage = {t for t in terms if t in value}
    # Preserve examples and qualifications, ignoring only the repeated grade
    # label when identifying concrete numbers. Always keep the initial premise.
    required = {0}
    for i, sentence in enumerate(sentences):
        without_grade = sentence.replace(record['grade'], '')
        if re.search(r'\d|[A-Za-z]|[×÷=]|[‘“「]|다만|단정|보장|개설|운영 여부', without_grade):
            required.add(i)
    candidates = []
    for size in (2, 1):
        for indices in combinations(range(len(sentences)), size):
            if not required <= set(indices):
                continue
            selected = ' '.join(sentences[i] for i in indices)
            if not 100 <= len(selected) <= INTRO_TARGET_MAX:
                continue
            if not coverage <= {t for t in terms if t in selected}:
                continue
            omitted = [sentences[i] for i in range(len(sentences)) if i not in indices]
            # Only omit consultation/combined-subject wrap-up, not an arbitrary
            # learning explanation to satisfy a character target.
            if any(not re.search(r'상담|영어.{0,8}수학|수학.{0,8}영어|비교|질문', s) for s in omitted):
                continue
            candidates.append((size, len(selected), selected))
    return max(candidates)[2] if candidates else value


def prepare_grade_manuscript(record: dict) -> tuple[dict, list[dict]]:
    """Return a deep-copied record and exact, auditable display changes.

    Existing polisher logs remain phrase-level. Grade-specific changes carry
    stage='grade-editorial' with the full before/after field string. Body, FAQ,
    and multi-paragraph cases are not automatically compressed. Titles, metadata,
    schemaSummary and source hashes remain original; only the explicitly approved
    교하 고2 영어 heading is corrected with its matching body/FAQ terminology.
    """
    if record.get('grade') not in SUPPORTED_GRADES or record.get('subject') not in ('영어', '수학'):
        raise ManuscriptFormatError('Expected normalized supported-grade 영어/수학 record')
    result = deepcopy(record)
    # Deliberately omit title/meta/headings so the generic phrase polisher cannot
    # modify them. Never import or call branch_editorial's locality overrides.
    visible = {'intro': result['intro'],
               'sections': [{'paragraphs': s['paragraphs']} for s in result['sections']],
               'faq': result['faq'], 'cases': result['cases']}
    polished, changes = polish_manuscript(visible)
    result['intro'], result['faq'], result['cases'] = polished['intro'], polished['faq'], polished['cases']
    for before, after in zip(result['sections'], polished['sections']):
        before['paragraphs'] = after['paragraphs']

    def update(container, key, value, field, rule):
        if container[key] != value:
            changes.append({'stage': 'grade-editorial', 'field': field, 'rule': rule,
                            'count': 1, 'before': container[key], 'after': value})
            container[key] = value

    def clean_visible(container, key, field):
        value = container[key]
        for before, after in [('G에 제시된', '안내된'), ('D에 제공된 학교', '안내된 학교')]:
            value = value.replace(before, after)
        update(container, key, value, field, 'grade-source-column-context')
        update(container, key, container[key].replace(
            '이 원고의 제공 사실에 포함되어 있지 않으므로',
            '이 안내에서 확인되지 않았으므로'), field, 'grade-source-copy-context')
        if result['grade'] == '고1':
            update(container, key, _high1_reader_context(container[key]), field,
                   'high1-reader-context')
        if result['grade'].startswith('초'):
            update(container, key, _elementary_reader_context(container[key]), field,
                   'elementary-reader-context')
            update(container, key, _elementary_school_lists(container[key], result['grade']), field,
                   'elementary-school-list-scope')
        elif result['grade'].startswith('중'):
            update(container, key, _middle_reader_context(container[key]), field,
                   'middle-reader-context')
            update(container, key, _middle_school_lists(container[key], result['grade']), field,
                   'middle-school-list-scope')
        else:
            update(container, key, _school_lists(container[key], result['grade']), field, 'grade-school-list-scope')

    clean_visible(result, 'intro', 'intro')
    for i, section in enumerate(result['sections']):
        for j in range(len(section['paragraphs'])):
            clean_visible(section['paragraphs'], j, f'sections[{i}].paragraphs[{j}]')
    for i, item in enumerate(result['faq']):
        for key in ('question', 'answer'):
            clean_visible(item, key, f'faq[{i}].{key}')
    for i in range(len(result['cases'])):
        clean_visible(result['cases'], i, f'cases[{i}]')

    if result['grade'] == '고2' and result['locality'] == '교하' and result['subject'] == '영어':
        def correct(container, key, field):
            value = container[key]
            for before, after in _GYOHA_PHRASES:
                value = value.replace(before, after)
            update(container, key, value, field, 'gyoha-concealed-understanding')
        correct(result, 'intro', 'intro')
        for i, section in enumerate(result['sections']):
            correct(section, 'heading', f'sections[{i}].heading')
            for j in range(len(section['paragraphs'])):
                correct(section['paragraphs'], j, f'sections[{i}].paragraphs[{j}]')
        for i, item in enumerate(result['faq']):
            for key in ('question', 'answer'):
                correct(item, key, f'faq[{i}].{key}')
        for i in range(len(result['cases'])):
            correct(result['cases'], i, f'cases[{i}]')
    update(result, 'intro', _short_intro(result), 'intro', 'grade-complete-sentence-intro')
    return result, changes
