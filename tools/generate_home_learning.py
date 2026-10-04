"""Enhance the existing home without replacing its brand, subject copy or contact flow."""
from pathlib import Path
from html import escape as E
from urllib.parse import quote
from PIL import Image
import argparse,hashlib,json,re

DATE='2026-10-05'
DOMAIN='https://xn--9p4bn5e3wjn0a.com'
DESCRIPTION='영수코칭의 영어·수학 학습관리와 수업 방식 비교를 살펴보고, 학습가이드·교육정보·커리큘럼과 지점 안내를 찾아보세요.'
STYLE='/assets/home-learning.css?v=20261005-1'
SITE_VERSION='20261005-2'
assert len(DESCRIPTION)<=80
HUBS=[
 ('학습가이드','공부 방법을 직접 실행하기','계획·복습·오답·과목별 공부법을 단계와 기록 양식으로 살펴보세요.','/학습가이드/','40개 상세 가이드'),
 ('교육정보','지금의 공부 고민에서 찾기','방학·시험·학습 습관·수업 선택의 질문과 실천 방법을 읽어보세요.','/교육정보/','30개 교육정보'),
 ('학습커리큘럼','학년과 과목의 연결 확인하기','초등·중등·고등의 학습 중점, 연습 순서와 학교별 확인 사항을 정리했습니다.','/학습커리큘럼/','12개 학년 · 66개 학년과목'),
 ('선생님찾기','지점별 선생님 소개 살펴보기','지점별 소개글을 읽고 상담에서 확인할 질문을 준비해보세요.','/선생님찾기/','192개 지점의 소개'),
 ('동네별 학원','우리 동네의 학습 안내 찾기','사는 동네와 과목을 기준으로 학원 안내를 살펴보세요.','/과목별학원/','지역·과목별 안내'),
 ('지점안내','가까운 지점의 정보 확인하기','주소와 연락처, 지점별 안내를 확인하고 실제 수업을 문의해보세요.','/지점안내/','지역별 지점 정보')]
TOPICS=[
 ('영어 문장이 어려울 때','/학습가이드/sentence-structure/'),('수학 개념부터 다시 볼 때','/학습가이드/math-start/'),
 ('오답을 반복할 때','/학습가이드/error-note/'),('계획이 자꾸 밀릴 때','/학습가이드/planner/'),
 ('학교 시험을 준비할 때','/교육정보/exam-plan-evidence/'),('수업을 고르기 전','/교육정보/class-selection-check/'),
 ('학부모가 과정을 확인할 때','/학습가이드/parent-progress/'),('학습 도구를 선택할 때','/교육정보/study-app-choice/')]
COMPARISON=[
 ('학습의 출발','같은 학년이나 공통 진도의 핵심 내용을 함께 설명하는 방식입니다.','최근 과제와 이해 상태를 살펴 학생마다 우선 확인할 내용을 정합니다.'),
 ('내용과 학교 진도','학교 진도·시험 범위에 맞춘 공통 설명과 유형 정리에 도움이 될 수 있습니다.','필요한 이전 개념을 보완하면서 현재 학교의 범위와 연결할 계획이 필요합니다.'),
 ('진도와 과제','함께 배울 범위와 일정이 분명합니다. 설명을 따라가기 어려운 부분은 별도 보완을 확인하세요.','단원과 과제의 조정이 가능합니다. 조정 기준과 다음 단계 판단을 확인하세요.'),
 ('질문과 참여','수업 중 질문 기회, 개별 답안 확인과 피드백 방법을 살펴보세요.','각자 풀기만 하는지, 설명·질문·교사의 점검이 어떻게 이어지는지 살펴보세요.'),
 ('이해의 확인','공통 평가와 과제에서 어떤 개념과 풀이가 부족한지 확인합니다.','설명 없이 해보기, 풀이 이유 말하기와 오답 재확인으로 다음 과제를 조정합니다.'),
 ('살펴볼 학생','공통 진도의 설명을 이해하고 함께 정해진 범위를 연습하려는 학생입니다.','영역별 차이가 크거나 필요한 개념부터 순서를 조정하려는 학생입니다.'),
 ('운영에서 중요한 조건','수준 차이에 대한 보완, 질문 기회와 수업 밖 복습의 연결이 중요합니다.','교사의 점검 빈도, 학습 기록, 학교 진도와의 연결이 중요합니다.'),
 ('상담에서 물어볼 것','공통 진도를 놓치면 어떤 자료와 피드백으로 따라갈 수 있나요?','무엇을 근거로 진도를 정하며, 스스로 해결했는지는 어떻게 확인하나요?')]
EXAM=[
 ('학교 자료부터 모으기','시험 범위표·교과서·수업 필기·프린트·평가 안내를 함께 확인합니다. 어떤 자료가 부족한지 먼저 표시하세요.'),
 ('자료 없이 짧게 확인하기','설명을 읽기 전에 개념을 말하거나 대표 문제를 풀어보세요. 개념·조건 해석·계산·답안 표현 중 처음 막힌 곳을 찾습니다.'),
 ('남은 일의 순서 정하기','시험일과 과제 마감일, 현재 가능한 공부량을 놓고 필수 개념·학교 과제·오답 확인의 우선순위를 정합니다.'),
 ('피드백을 다음 과제로 연결하기','틀린 답을 고치는 것으로 끝내지 않고 필요한 설명을 확인한 뒤 비슷한 과제를 다시 해봅니다. 남은 질문을 다음 상담 자료로 가져가세요.')]
FOUR_C=[
 ('Check','진단','최근 답안에서 무엇을 혼자 설명할 수 있는지, 어디에서 막혔는지 확인합니다.','점수 외에 어떤 풀이와 설명을 확인하나요?'),
 ('Curriculum','계획','필요한 개념·현재 학교 진도·가능한 공부량을 연결하여 과제의 순서를 정합니다.','이 단원부터 시작하는 이유와 완료 기준은 무엇인가요?'),
 ('Consulting','상담','실행 기록과 남은 질문을 나누고 과제의 부담과 우선순위를 조정합니다.','미완료와 반복 오답을 어떤 자료로 함께 살펴보나요?'),
 ('Coaching','지도','질문·설명·피드백 후 학생이 다시 해보는 과정을 점검합니다.','도움을 받은 뒤 스스로 해결했는지는 어떻게 확인하나요?')]
NEW_FAQ=[
 ('개별진도 수업은 학교 진도와 따로 공부하는 방식인가요?','필요한 이전 개념을 보완하더라도 현재 학교 진도와 시험 범위를 함께 확인해야 합니다. 어디에서 시작하고 학교 과제와 언제 연결할지, 학생의 답안과 학교 자료를 놓고 상담하세요.'),
 ('학교 시험 준비에는 어떤 자료가 필요한가요?','시험 범위표, 교과서, 수업 필기와 프린트, 부교재 및 평가 안내를 준비해보세요. 학생이 혼자 가능한 내용과 설명이 필요한 부분을 표시하면 과제의 우선순위를 정하는 데 도움이 됩니다.'),
 ('공부 자료와 학년별 내용을 어디에서 찾을 수 있나요?','학습가이드는 실행 방법과 기록, 교육정보는 공부 고민과 선택 기준, 학습커리큘럼은 학년·과목별 중점과 확인 과제를 안내합니다. 선생님찾기와 지점안내에서는 지역별 소개와 연락처를 확인할 수 있습니다.'),
 ('모든 지점의 과목과 수업 방식이 같은가요?','운영 과목·대상 학년·시간·수업 방식은 지점마다 다를 수 있습니다. 홈페이지의 학습 예시를 해당 지점의 확정 운영표로 해석하지 말고 가까운 지점에서 희망 학년·과목·일정을 확인하세요.')]

def link(path,label,cls='hl-link'):
    return f'<a class="{cls}" href="{E(path)}">{E(label)} <span aria-hidden="true">→</span></a>'
def photo(name,alt):
    width,height={'coaching-scene':(626,417),'planner-coaching':(555,555),'learning-dialogue':(566,463)}[name]
    return f'<figure class="hl-photo"><img src="/assets/home-learning/{name}.webp" alt="{E(alt)}" width="{width}" height="{height}" loading="lazy" decoding="async"><figcaption>와와학습코칭센터 브랜드 안내 사진</figcaption></figure>'
def marked(name,body):return f'<!-- home-learning:{name}:start -->{body}<!-- home-learning:{name}:end -->'
def hub():
    cards=''.join(f'<article class="hl-hub-card"><span class="hl-card-number" aria-hidden="true">{i:02}</span><p class="hl-card-question">{E(question)}</p><h3>{link(path,title,"hl-card-title")}</h3><p>{E(copy)}</p><span class="hl-card-meta">{E(count)}</span></article>' for i,(title,question,copy,path,count) in enumerate(HUBS,1))
    return marked('hub',f'<section class="section home-learning hl-hub" id="learning-hub" aria-labelledby="learning-hub-title"><div class="section-head"><p class="eyebrow">학생·학부모의 질문에서 시작하세요</p><h2 id="learning-hub-title">필요한 공부 정보와<br>가까운 학원 안내를 한곳에서.</h2><p class="lead">공부 방법을 정리하고, 학년별 내용을 확인하고, 우리 동네의 지점과 선생님을 찾아보세요. 지금 필요한 질문에 맞춰 다음 페이지로 이어집니다.</p></div><div class="hl-hub-grid">{cards}</div><nav class="hl-topic-nav" aria-label="공부 고민별 바로가기"><strong>이런 질문이 있나요?</strong><div>'+''.join(link(path,title,'hl-topic-link') for title,path in TOPICS)+'</div></nav></section>')
def compare():
    rows=''.join(f'<tr><th scope="row">{E(name)}</th><td><span class="hl-cell-label" aria-hidden="true">공통 진도의 강의식 수업</span>{E(a)}</td><td><span class="hl-cell-label" aria-hidden="true">학생별 개별진도 수업</span>{E(b)}</td></tr>' for name,a,b in COMPARISON)
    return marked('compare',f'<section class="home-learning hl-tinted" id="lesson-comparison" aria-labelledby="lesson-comparison-title"><div class="section"><div class="section-head"><p class="eyebrow blue">설명 방식과 관리 조건을 함께 보기</p><h2 id="lesson-comparison-title">강의식과 개별진도 수업,<br>무엇을 비교해야 할까요?</h2><p class="lead">수업 이름 하나로 적합성을 결정하기 어렵습니다. 공통 설명이 필요한지, 특정 개념부터 순서를 조정해야 하는지와 질문·피드백 조건을 함께 살펴보세요.</p></div><table class="hl-compare"><caption>일반적인 수업 형식 비교 · 실제 운영은 지점 상담에서 확인하세요.</caption><thead><tr><th scope="col">살펴볼 기준</th><th scope="col">공통 진도의 강의식 수업</th><th scope="col">학생별 개별진도 수업</th></tr></thead><tbody>{rows}</tbody></table><div class="hl-after-table"><p>같은 수업 안에서도 설명식 지도와 개별 연습을 함께 사용할 수 있습니다. 학생의 현재 답안과 학교 과제를 가져가 실제 운영과 맞춰보세요.</p>{link("/교육정보/class-selection-check/","수업 선택의 질문 더 보기")}{link("/지점안내/","가까운 지점에서 확인하기")}</div></div></section>')
def system():
    cards=''.join(f'<article class="hl-system-card"><p class="hl-step-label">{E(name)}</p><h3>{E(title)}</h3><p>{E(copy)}</p><p class="hl-ask"><strong>물어볼 질문</strong>{E(question)}</p></article>' for name,title,copy,question in FOUR_C)
    return marked('system',f'<section class="section home-learning" id="coaching-system" aria-labelledby="coaching-system-title"><div class="section-head"><p class="eyebrow">4C를 학생의 실제 자료에서 확인하기</p><h2 id="coaching-system-title">진단 뒤에는 계획·상담·지도가 이어져야 합니다.</h2><p class="lead">와와의 4C는 Check·Curriculum·Consulting·Coaching의 연결을 설명합니다. 용어보다 학생의 자료에서 다음 행동이 어떻게 정해지는지 살펴보세요.</p></div><div class="hl-system-grid">{cards}</div><div class="hl-dialogue">{photo("coaching-scene","교재를 사이에 두고 학생과 대화하는 코치")}<div><p class="eyebrow blue">둥지학습의 질문과 피드백</p><h3>설명을 들은 뒤,<br>학생이 자기 말로 말해보는 과정.</h3><p>브랜드가 소개하는 둥지학습은 코치와 학생의 질문·대화를 중심으로 학습을 점검하는 구조입니다. 좌석 배치와 함께 학생에게 설명할 기회가 있는지, 질문 뒤 다시 풀어볼 과제가 있는지 확인해보세요.</p><div class="hl-question-list"><p><b>학생</b>어디까지 알았고, 첫 질문은 무엇인가요?</p><p><b>코치</b>어떤 설명과 작은 과제가 필요한가요?</p><p><b>재확인</b>설명 없이 다음 과제를 해볼 수 있나요?</p></div>{link("/학습가이드/learning-question/","질문을 준비하는 방법")}{link("/선생님찾기/","지점별 선생님 소개 보기")}</div></div><a class="hl-reference" href="https://www.wawacenter.com/intro/coachingSystem" target="_blank" rel="noopener noreferrer">와와학습코칭센터의 학습관리·4C 안내 ↗<span class="sr-only"> 새 창</span></a></section>')
def exam():
    steps=''.join(f'<li><span aria-hidden="true">{i:02}</span><div><h3>{E(title)}</h3><p>{E(copy)}</p></div></li>' for i,(title,copy) in enumerate(EXAM,1))
    return marked('exam',f'<section class="home-learning hl-exam-band" id="school-exam" aria-labelledby="school-exam-title"><div class="section"><div class="hl-exam-layout"><div class="section-head"><p class="eyebrow">우리 학교 자료에서 출발하기</p><h2 id="school-exam-title">시험 준비는 범위·과제·오답을 함께 봅니다.</h2><p class="lead">교과서와 학교 자료에서 확인한 범위를 학생의 실제 이해와 연결하세요. 남은 기간만큼 과제를 늘리기보다 먼저 막힌 부분과 다음 확인 과제를 좁히는 과정이 필요합니다.</p>{link("/교육정보/exam-plan-evidence/","내신 계획의 우선순위 정하기")}{link("/학습가이드/performance-task/","서술형·수행평가 준비하기")}</div><ol class="hl-exam-steps">{steps}</ol></div><p class="hl-scope-note">학교별 시험 일정과 평가 기준은 학교의 최신 안내에서, 지점의 수업·평가 관리 방식은 해당 지점에서 확인하세요.</p></div></section>')
def planner():
    return marked('planner',f'<section class="section home-learning" id="planner-example" aria-labelledby="planner-example-title"><div class="section-head"><p class="eyebrow blue">계획 → 실행 → 피드백 → 다음 확인</p><h2 id="planner-example-title">플래너에 남길 것은 분량과 다음 질문입니다.</h2><p class="lead">완료 표시만으로 이해 여부를 알기는 어렵습니다. 무엇을 해봤고 어디에서 멈췄는지 기록하면 다음 과제를 정할 자료가 생깁니다.</p></div><div class="hl-planner-grid"><div><p class="hl-example-label">설명용 기록 예시</p><dl class="hl-planner-record"><dt>오늘의 과제</dt><dd>수학: 약분 문제 두 개의 이유 설명하기.<br>영어: 문장 하나의 주어·동사와 뜻 연결하기.</dd><dt>실행한 뒤 남길 것</dt><dd>혼자 가능한 부분과 설명이 필요한 부분을 나누고, 처음 막힌 줄이나 표현을 표시합니다.</dd><dt>도움과 피드백</dt><dd>약분의 공통 약수, 문장의 기본 구조 등 표시한 부분에 필요한 설명을 확인합니다.</dd><dt>다음 확인</dt><dd>비슷한 문제나 문장을 답 없이 다시 해보고 남은 질문을 기록합니다.</dd></dl><div class="hl-inline-links">{link("/학습가이드/planner/","내 플래너 기록 양식 열기")}{link("/학습가이드/feedback-action/","피드백을 다음 행동으로 바꾸기")}{link("/학습가이드/parent-progress/","학부모가 함께 확인할 질문")}</div></div><div class="hl-photo-stack">{photo("planner-coaching","플래너를 함께 살펴보며 설명하는 코치와 학생")}{photo("learning-dialogue","태블릿과 교재를 보며 대화하는 학생과 코치")}</div></div></section>')

def render_home(html):
    for name in ['hub','compare','system','exam','planner']:
        html=re.sub(r'<!-- home-learning:'+name+r':start -->[\s\S]*?<!-- home-learning:'+name+r':end -->(?:\r?\n    )?','',html)
    # Use stable existing section boundaries rather than replacing the original main.
    anchors=[('<section class="section" aria-labelledby="subject-title">',hub()),('<section class="process-band"',compare()),('<section class="section" aria-labelledby="situation-title">',system()+exam()),('<section class="section section-compact" aria-labelledby="grade-title">',planner())]
    for anchor,fragment in anchors:
        assert html.count(anchor)==1,anchor
        html=html.replace(anchor,fragment+'\n    '+anchor,1)
    html=html.replace('<body>','<body class="home-page">',1)
    html=html.replace('href="/학습가이드/">학습관리 방식 보기','href="#learning-hub">공부 정보 찾아보기',1)
    for old,new in [('/학습가이드/#english','/학습가이드/sentence-structure/'),('/학습가이드/#math','/학습가이드/math-start/'),('/학습가이드/#wrong-answer','/학습가이드/error-note/')]:html=html.replace('href="'+old+'"','href="'+new+'"')
    for stage in ['초등','중등','고등']:
        anchor=f'<h3>{stage}</h3>'
        # One stage-specific button in each existing grade card.
        html=re.sub(re.escape(anchor)+r'(<p>[\s\S]*?</p>)(</article>)',lambda m:anchor+m[1]+link('/학습커리큘럼/'+stage+'/',stage+' 학년·과목 안내')+m[2],html,count=1)
    for question,answer in NEW_FAQ:
        if question not in html:
            item=f'<details><summary>{E(question)}</summary><p>{E(answer)}</p></details>'
            start=html.index('<div class="faq-list')
            end=html.index('</div>',start)
            html=html[:end]+item+html[end:]
    for field in ['description','og:description','twitter:description']:
        html=re.sub(r'(<meta\s+(?:name|property)="'+re.escape(field)+r'"\s+content=")[^"]*(")',lambda m:m[1]+E(DESCRIPTION)+m[2],html)
    pattern=r'(<script type="application/ld\+json">)([\s\S]*?)(</script>)'
    def graph(match):
        data=json.loads(match[2]);nodes=data['@graph'];page=next(n for n in nodes if n.get('@type')=='WebPage');page.update(description=DESCRIPTION,dateModified=DATE,mainEntity=[{'@id':DOMAIN+'/#learning-hub-links'},{'@id':DOMAIN+'/#faq'}])
        faq=next(n for n in nodes if n.get('@type')=='FAQPage')
        for question,answer in NEW_FAQ:
            if not any(q['name']==question for q in faq['mainEntity']):faq['mainEntity'].append({'@type':'Question','name':question,'acceptedAnswer':{'@type':'Answer','text':answer}})
        nodes[:]=[n for n in nodes if n.get('@id')!=DOMAIN+'/#learning-hub-links']
        nodes.append({'@type':'ItemList','@id':DOMAIN+'/#learning-hub-links','name':'공부 정보와 지역별 학원 안내','numberOfItems':len(HUBS),'itemListElement':[{'@type':'ListItem','position':i,'item':{'@type':'WebPage','name':title,'url':DOMAIN+quote(path,safe='/')}} for i,(title,question,copy,path,count) in enumerate(HUBS,1)]})
        return match[1]+json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')+match[3]
    html=re.sub(pattern,graph,html,count=1)
    if STYLE not in html:html=html.replace('</head>','<link rel="stylesheet" href="'+STYLE+'">\n</head>',1)
    return cache_bust(html)

def cache_bust(html):
    return re.sub(r'(href=["\'][^"\']*assets/site\.css)(?:\?[^"\']*)?(["\'])',lambda m:m[1]+'?v='+SITE_VERSION+m[2],html)
def write(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists() or path.read_bytes()!=raw:path.write_bytes(raw)
def run(root,out):
    manifest=root/'release-public-manifest.json'
    scope=json.loads((out/'reviewed-public-before-hashes.json').read_text(encoding='utf-8'))
    changed=[]
    for name in scope:
        if not name.endswith('.html'):continue
        path=root/name
        before=path.read_bytes();html=before.decode('utf-8');html=render_home(html) if name=='index.html' else cache_bust(html);raw=html.encode('utf-8')
        if raw!=before:write(path,raw);changed.append(name)
    pictures=[]
    for source,name in [('brand_info_coach.png','coaching-scene'),('sys_2.png','planner-coaching'),('sys_3.png','learning-dialogue')]:
        path=out/source
        with Image.open(path) as image:
            image.convert('RGB').save(root/'assets/home-learning'/f'{name}.webp','WEBP',quality=86,method=6)
        dest=root/'assets/home-learning'/f'{name}.webp'
        pictures.append({'file':dest.relative_to(root).as_posix(),'sourceUrl':'https://www.wawacenter.com/assets/img/'+source,'originalSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':dest.stat().st_size})
    descriptions=json.loads((root/'seo-descriptions.json').read_text(encoding='utf-8'));descriptions['pages']['/']={'description':DESCRIPTION,'sources':['영어·수학 학습관리, 수업 형식 비교와 지역 안내','학습가이드·교육정보·학습커리큘럼·선생님찾기·지점 연결']}
    write(root/'seo-descriptions.json',(json.dumps(descriptions,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    sitemap=(root/'sitemap.xml').read_bytes().decode('utf-8')
    sitemap=re.sub(r'(<url>\s*<loc>https://xn--9p4bn5e3wjn0a\.com/</loc>\s*<lastmod>)[^<]+',lambda m:m[1]+DATE,sitemap,count=1)
    write(root/'sitemap.xml',sitemap.encode('utf-8'))
    llms=(root/'llms.txt').read_bytes().decode('utf-8')
    marker='## 메인 학습 안내'
    if marker not in llms:llms+='\n'+marker+'\n- 메인에서 학습가이드·교육정보·학습커리큘럼·선생님찾기·동네·지점 안내를 찾을 수 있습니다.\n- 수업 형식 비교, 4C 확인 질문, 학교 시험 준비와 플래너 기록 예시는 실제 운영을 상담할 때 함께 확인합니다.\n'
    write(root/'llms.txt',llms.encode('utf-8'))
    new=['assets/home-learning.css']+[p['file'] for p in pictures]
    if manifest.exists():
        data=json.loads(manifest.read_text(encoding='utf-8'))
        for name in set(changed+new+['sitemap.xml','llms.txt']):
            raw=(root/name).read_bytes();data['files'][name]=hashlib.sha256(raw).hexdigest();data['textSha256'][name]=hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()
        data.update(updatedAt=DATE,homepageLearningUpgrade=DATE)
        write(manifest,(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    result={'root':str(root),'homeDescription':DESCRIPTION,'descriptionChars':len(DESCRIPTION),'hubLinks':6,'topicLinks':8,'comparisonRows':8,'faqQuestions':8,'referenceImages':pictures,'cacheBustPages':len(changed),'changedHtml':changed}
    label='worktree' if manifest.exists() else 'source'
    (out/(label+'-generated.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['referenceImages','changedHtml']},ensure_ascii=False))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();(args.root/'assets/home-learning').mkdir(parents=True,exist_ok=True);run(args.root,args.out)
