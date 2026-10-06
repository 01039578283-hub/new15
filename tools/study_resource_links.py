"""Idempotent contextual education and curriculum links for existing page generators."""
from html import escape as E
from urllib.parse import quote
import re

START='<!-- study-resources:start -->'
END='<!-- study-resources:end -->'
CSS='<link rel="stylesheet" href="/assets/education.css?v=20261004-1">'
MENU='<a href="/교육정보/">교육정보</a><a href="/학습커리큘럼/">학습커리큘럼</a>'

def fresh_choices(path):
    if path=='/':
        return [('수행평가-보고서-체크리스트','수행평가 보고서 제출 점검하기'),('수학-유형별-오답노트','수학 오답의 첫 오류 찾기'),('자녀와-공부대화-시작하기','부모와 학생의 공부 대화 시작하기')]
    stage=curriculum_target(path)
    if '수학' in path:
        return [('중학교수학-기초부터-기말준비','중학교 수학의 막힌 기초 확인하기')] if '중등' in stage else [('수학-변형문제-접근','수학 변형 문제의 조건 살피기')] if '고등' in stage else [('국영수-설명으로-이해확인','국영수 이해를 설명으로 확인하기')]
    if '영어' in path:
        return [('영어내신-어법독해-검토','영어 내신의 문장과 답 근거 확인하기')] if '중등' in stage or '고등' in stage else [('국영수-설명으로-이해확인','영어 표현을 문장으로 확인하기')]
    if '고등' in stage:return [('서술형-조건근거-답안쓰기','서술형 답안의 조건과 근거 점검하기')]
    if '중등' in stage:return [('중학생-월별목표-수정','중학생 월별 목표 조절하기')]
    if '초등' in stage:return [('공부중-방해요소-줄이기','공부 중 끊기는 순간 줄이기')]
    return [('자녀와-공부대화-시작하기','부모와 학생의 공부 대화 시작하기')]

def curriculum_target(path):
    grade=re.search(r'(초[1-6]|중[1-3]|고[1-3])',path)
    subject=next((s for s in ['국어','영어','수학','사회','과학','역사'] if s in path),None)
    if grade:
        grade=grade[0]; stage={'초':'초등','중':'중등','고':'고등'}[grade[0]]
        return f'/학습커리큘럼/{stage}/{grade}/'+(subject+'/' if subject and not(subject=='역사' and stage=='초등') else '')
    stage=next((s for s in ['초등','중등','고등'] if s in path),None)
    return '/학습커리큘럼/'+(stage+'/' if stage else '')

def block(path):
    target=curriculum_target(path)
    stage='고등' if '고등' in target else '중등' if '중등' in target else '초등' if '초등' in target else ''
    choices=[('after-class-review','수업 뒤 복습을 어떻게 할까요?'),('year-end-consultation','상담에서 무엇을 확인할까요?')]
    if stage in ['중등','고등']: choices=[('exam-plan-evidence','내신 계획의 우선순위 정하기'),('grade-change-signals','학년이 바뀔 때 확인할 신호')]
    if stage=='초등': choices=[('self-directed-cycle','스스로 공부를 시작하는 순서'),('semester-ready','새학기 전에 확인할 공부의 연결')]
    if path=='/': choices=[('focus-restart','공부가 손에 잡히지 않을 때'),('class-selection-check','수업을 고르기 전에 확인할 것'),('exam-plan-evidence','내신 계획의 우선순위 정하기')]
    choices+=fresh_choices(path)
    suffix='?from='+quote(path,safe='') if path.startswith(('/지점안내/','/과목별학원/')) else ''
    title='지금의 질문에서, 다음 공부로' if path=='/' else '수업과 함께 살펴볼 공부 정보'
    links=''.join(f'<a href="/교육정보/{slug}/{suffix}">{E(title)} <span aria-hidden="true">↗</span></a>' for slug,title in choices)
    return START+f'<section class="study-context" id="study-resources" aria-labelledby="study-resource-title"><div><p class="edu-kicker">학생·학부모를 위한 읽을거리</p><h2 id="study-resource-title">{title}</h2><p>계획·복습·상담의 질문을 정리하고, 학년과 과목에 맞는 학습 중점을 확인해 보세요.</p></div><div class="study-context-links">{links}<a class="study-context-all" href="/교육정보/{suffix}">교육정보 전체 보기 →</a><a class="study-context-curriculum" href="{target}{suffix}">{E(stage+' ' if stage else '')}학년·과목별 커리큘럼 보기 →</a></div></section>'+END

def decorate_study_page(text,path):
    if '<nav class="nav"' in text and 'href="/교육정보/"' not in re.search(r'<nav class="nav"[\s\S]*?</nav>',text)[0]:
        text=text.replace('<a href="/선생님찾기/">선생님찾기</a>','<a href="/선생님찾기/">선생님찾기</a>'+MENU,1)
        if 'href="/교육정보/"' not in re.search(r'<nav class="nav"[\s\S]*?</nav>',text)[0]:
            text=text.replace('<a href="/학습가이드/">학습가이드</a>','<a href="/학습가이드/">학습가이드</a>'+MENU,1)
    if path!='/404.html' and '</main>' in text and START not in text:
        text=text.replace('</main>',block(path)+'</main>',1)
    elif START in text and (path=='/' or path.startswith(('/지점안내/','/과목별학원/'))):
        text=re.sub(re.escape(START)+r'[\s\S]*?'+re.escape(END),lambda _:block(path),text,count=1)
    if START in text and CSS not in text: text=text.replace('</head>',CSS+'\n</head>',1)
    return text
