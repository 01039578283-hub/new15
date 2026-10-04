"""Generate reviewed education/curriculum pages; patch only navigation and marked CTAs."""
from pathlib import Path
from html import escape as E
from urllib.parse import quote,unquote
from concurrent.futures import ThreadPoolExecutor
from PIL import Image,ImageOps
import argparse,hashlib,json,re
from education_articles_data import ARTICLES,CATEGORIES,SOURCES
from study_resource_links import decorate_study_page,CSS,MENU

DATE='2026-10-05'
DOMAIN='https://xn--9p4bn5e3wjn0a.com'
MOE='https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=141&boardSeq=93458&lev=0'
ROOT=Path(__file__).resolve().parents[1]
WRITTEN=[]; DESCRIPTIONS={}; NEW_PAGES=[]
def URL(path): return DOMAIN+quote(path,safe='/')
def write(rel,text):
    dest=ROOT/rel; dest.parent.mkdir(parents=True,exist_ok=True)
    raw=text if isinstance(text,bytes) else text.encode('utf-8')
    if not dest.exists() or dest.read_bytes()!=raw: dest.write_bytes(raw); WRITTEN.append(rel)
def read(rel): return (ROOT/rel).read_bytes().decode('utf-8')
def path_of(rel): return '/'+rel.removesuffix('index.html') if rel.endswith('index.html') else '/'+rel
def paras(text): return ''.join('<p>'+E(t)+'</p>' for t in text.split('\n') if t)
def fullgrade(grade): return {'초':'초등학교','중':'중학교','고':'고등학교'}[grade[0]]+' '+grade[1]+'학년'
def stageof(grade): return {'초':'초등','중':'중등','고':'고등'}[grade[0]]
def cr(grade,subject=None): return '/학습커리큘럼/'+stageof(grade)+'/'+grade+'/'+(subject+'/' if subject else '')
def special(grade,subject): return '선택 활동' if grade in ['초1','초2'] and subject=='영어' else '슬기로운 생활 연계' if grade in ['초1','초2'] and subject in ['사회','과학'] else ''
def display(grade,subject): return subject+(' · '+special(grade,subject) if special(grade,subject) else '')

ALT=[
'영어 글자가 놓인 책상에서 읽는 학생','교재와 태블릿을 함께 보며 공부하는 학생','책상에 앉아 있는 교복 차림 학생',
'노트북으로 설명을 듣는 학생','교실 책상 앞에 모인 학생들','책상에서 눈을 쉬는 학생',
'책장 앞에 펼쳐 놓은 책','교재와 노트북을 함께 사용하는 공부 장면','책을 펼치고 설명하는 학생',
'교실에서 문제를 푸는 학생','공책과 필기구가 놓인 책상','교실에서 설명을 듣는 학생들',
'책을 펴고 읽는 학생','칠판의 식을 함께 살펴보는 두 학생','교복 차림으로 모인 학생들',
'책상에서 질문하며 설명하는 학생','책과 노트북 앞에서 필기하는 학생','노트북과 교재를 보며 질문하는 학생',
'교실에서 생각하며 듣는 두 학생','조명 아래 교재를 펼친 학생','교재를 사이에 두고 상담하는 장면',
'교실에서 공책에 필기하는 학생','교재를 펴고 읽는 학생','책과 공책으로 공부하는 학생',
'노트북과 자료를 두고 이야기하는 장면','책상 위에 엎드려 쉬는 학생','칠판의 식을 설명하는 학생',
'노트북 화면 앞에서 작업하는 장면','펼친 교재에 표시하며 읽는 손','교재와 태블릿을 함께 보는 학생',
'독서대와 공책으로 공부하는 학생','종이 자료를 들고 설명하는 학생','학습 자료에 연필로 표시하는 손',
'할 일과 시간 기록이 적힌 학습 플래너','교복 차림으로 함께 서 있는 두 학생','공책에 필기하는 공부 장면',
'교실에서 문제를 푸는 학생들','칠판 앞에서 자료를 이야기하는 학생들','독서대의 교재와 공책을 보는 학생',
'교재를 들고 함께 서 있는 학생들','칠판의 식을 가리키는 설명 장면','타이머와 교재를 놓고 공부하는 학생',
'공책과 연필을 준비한 학생','자료를 함께 읽고 필기하는 공부 장면','학생의 공책을 함께 살펴보는 장면',
'태블릿과 공책으로 공부하는 학생','노트북 앞에서 생각하는 학생','여러 교재와 공책을 보며 필기하는 학생',
'칠판 앞에서 자료를 보여 주는 두 학생','교실에서 자료를 설명하는 장면','학생과 자료를 함께 보는 상담 장면',
'벽에 붙인 학습 자료를 살펴보는 학생','교재에 연필로 필기하는 손','지구본과 자료를 함께 보는 두 학생',
'학생의 교재를 함께 확인하는 장면','휴대전화로 뉴스 화면을 보는 손','책상에 앉아 공책에 필기하는 학생',
'판서 자료를 들고 설명하는 장면','교복 차림으로 함께 서 있는 학생들','교재 앞에서 생각하는 학생',
'교실 책상에서 문제를 푸는 손','칠판의 식을 함께 설명하는 두 학생','공책의 문제를 함께 살펴보는 두 학생',
'교재의 내용을 읽는 학생','메모가 붙은 벽 옆에서 생각하는 학생','노트북의 수업 화면과 교재를 보는 장면',
'교실에서 교재를 함께 확인하는 장면','공책에 펜으로 필기하는 손','교실에서 질문하는 학생',
'책상 앞에서 설명하는 학생','학습 계획과 과제 기록이 있는 플래너','달력과 책상 위의 메모를 정리하는 손',
'펼친 책 위에 놓인 시계','책과 자료를 들고 서 있는 두 학생','책상에서 머리를 기댄 채 쉬는 학생',
'벽에 붙인 노트를 살펴보는 학생','교실에서 설명을 듣는 학생들','교재를 들고 함께 서 있는 두 학생',
'책과 노트북을 놓고 공부하는 장면','함께 모여 웃고 있는 가족','교재와 독서대로 공부하는 학생',
'수첩과 교재를 펴고 메모하는 손','펼친 교재에 표시하는 손','칠판의 식을 함께 살펴보는 학생들',
'교실에서 학습 자료를 함께 확인하는 장면','독서대와 공책으로 공부하는 학생','교실에서 교재를 읽는 학생들',
'책상에서 교재와 자료를 정리하는 장면','학습 노트에 펜으로 기록하는 손','학생과 자료를 함께 보는 상담 장면']
assert len(ALT)==90

def prepare(out):
    selection=json.loads((out/'selection.json').read_text(encoding='utf-8'))
    replacement=json.loads((out/'image-replacement-review.json').read_text(encoding='utf-8'))
    chosen=selection['selection']; chosen[1]['images'][2]=replacement['replacement']
    inventory=[]
    def image_task(pair):
        i,j,source,article=pair
        rel=f'assets/education/images/{article["slug"]}-{j+1:02d}.webp'
        with Image.open(source['path']) as original:
            im=ImageOps.exif_transpose(original).convert('RGB')
            im.thumbnail((1200,1200),Image.Resampling.LANCZOS)
            dest=ROOT/rel; dest.parent.mkdir(parents=True,exist_ok=True)
            im.save(dest,format='WEBP',quality=82,method=6)
            w,h=im.size
        return {'article':article['slug'],'slot':j+1,'path':'/'+rel,'width':w,'height':h,'alt':ALT[i*3+j],'source':source['path'],'sourceSha256':hashlib.sha256(Path(source['path']).read_bytes()).hexdigest(),'bytes':dest.stat().st_size}
    jobs=[(i,j,source,a) for i,(p,a) in enumerate(zip(chosen,ARTICLES)) for j,source in enumerate(p['images'])]
    with ThreadPoolExecutor(max_workers=6) as pool: inventory=list(pool.map(image_task,jobs))
    for i,a in enumerate(ARTICLES):
        a['description']=a['intro'].split('。')[0].split('. ')[0].rstrip('.')+'.'
        if len(a['description'])>80: raise ValueError('Long description: '+a['slug'])
        if a['guide']=='grade-transition': a['guide']='middle-transition'
        a['images']=inventory[i*3:i*3+3]
        assert (ROOT/f'학습가이드/{a["guide"]}/index.html').exists(),a['guide']
    write('tools/data/education/selection.json',json.dumps(selection,ensure_ascii=False,indent=2)+'\n')
    write('tools/data/education/images.json',json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    book=json.loads((out/'curriculum-workbook.json').read_text(encoding='utf-8'))
    write('tools/data/curriculum/workbook.json',json.dumps(book,ensure_ascii=False,indent=2)+'\n')
    return book['sheets'],inventory

def locations(scope):
    branches={}; subjects={}
    for rel in scope:
        parts=rel.split('/')
        if len(parts)==4 and parts[0]=='지점안내' and parts[-1]=='index.html':
            path=path_of(rel); branches[path]={'name':parts[2],'region':parts[1],'locals':[]}
    for rel in scope:
        parts=rel.split('/')
        if len(parts)==5 and parts[0]=='지점안내' and parts[-1]=='index.html':
            parent='/'+'/'.join(parts[:3])+'/'
            if parent in branches: branches[parent]['locals'].append({'name':parts[3],'path':path_of(rel)})
    data=json.loads(read('tools/data/teachers/directory.json'))
    for rel,parent in data.get('subjectPages',{}).items():
        if parent in branches: subjects[path_of(rel)]=parent
    for b in branches.values(): b['locals'].sort(key=lambda l:l['name'])
    write('assets/education/locations.json',json.dumps({'branches':branches,'subjects':subjects},ensure_ascii=False,separators=(',',':'))+'\n')
    return branches

def crumbs(trail):
    return '<nav class="breadcrumb" aria-label="현재 위치"><a href="/">홈</a>'+''.join('<span aria-hidden="true">›</span>'+(f'<a href="{E(path)}">{E(label)}</a>' if path else f'<span aria-current="page">{E(label)}</span>') for label,path in trail)+'</nav>'
def page(title,desc,path,content,trail,kind='WebPage',citations=None,image=None,faq=None):
    DESCRIPTIONS[path.rstrip('/')]=desc; NEW_PAGES.append(path)
    canonical=URL(path)
    h=HEADER.replace(' aria-current="page"','')
    menu='/교육정보/' if path.startswith('/교육정보/') else '/학습커리큘럼/'
    h=h.replace(f'<a href="{menu}">',f'<a href="{menu}" aria-current="page">',1)
    org={'@type':'EducationalOrganization','@id':DOMAIN+'/#organization','name':'영수코칭','url':DOMAIN+'/'}
    web={'@type':'WebPage' if kind=='Article' else kind,'@id':canonical+'#webpage','url':canonical,'name':title+' | 영수코칭','description':desc,'inLanguage':'ko-KR','datePublished':DATE,'dateModified':DATE,'isPartOf':{'@id':DOMAIN+'/#website'}}
    graph=[org,{'@type':'WebSite','@id':DOMAIN+'/#website','name':'영수코칭','url':DOMAIN+'/','publisher':{'@id':org['@id']}},web]
    if kind=='Article':
        graph.append({'@type':'Article','@id':canonical+'#article','headline':title,'description':desc,'datePublished':DATE,'dateModified':DATE,'author':{'@id':org['@id']},'publisher':{'@id':org['@id']},'inLanguage':'ko-KR','mainEntityOfPage':{'@id':web['@id']},'image':DOMAIN+image,'citation':citations or []})
        web['mainEntity']={'@id':canonical+'#article'}
    graph.append({'@type':'BreadcrumbList','itemListElement':[{'@type':'ListItem','position':i+1,'name':label,'item':URL(p or path)} for i,(label,p) in enumerate([('홈','/')]+trail)]})
    if faq: graph.append({'@type':'FAQPage','mainEntity':[{'@type':'Question','name':q,'acceptedAnswer':{'@type':'Answer','text':a}} for q,a in faq]})
    og=DOMAIN+(image or '/assets/images/og-share.png')
    html=f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{E(title)} | 영수코칭</title><meta name="description" content="{E(desc)}"><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="{canonical}"><link rel="icon" href="/assets/favicon.svg" type="image/svg+xml"><link rel="alternate" type="application/rss+xml" href="/rss.xml" title="영수코칭 학습 소식"><link rel="stylesheet" href="/assets/site.css?v=20261005-1">{CSS}<meta property="og:type" content="{'article' if kind=='Article' else 'website'}"><meta property="og:locale" content="ko_KR"><meta property="og:site_name" content="영수코칭"><meta property="og:title" content="{E(title)} | 영수코칭"><meta property="og:description" content="{E(desc)}"><meta property="og:url" content="{canonical}"><meta property="og:image" content="{og}"><meta property="og:image:alt" content="{E(title)} 본문 참고 이미지"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{E(title)} | 영수코칭"><meta name="twitter:description" content="{E(desc)}"><meta name="twitter:image" content="{og}"><script type="application/ld+json">{json.dumps({'@context':'https://schema.org','@graph':graph},ensure_ascii=False,separators=(',',':'))}</script></head><body class="edu-page"><a class="skip-link" href="#main">본문 바로가기</a>{h}<main id="main">{content}{local_picker()}</main>{FOOTER}{FLOATING}<script src="/assets/site.js" defer></script><script src="/assets/education.js?v=20261005-1" defer></script></body></html>'''
    write(path.strip('/')+'/index.html',html)
def local_picker():
    options=''.join(f'<option value="{E(p)}">{E(b["region"]+" · "+b["name"])}</option>' for p,b in sorted(BRANCHES.items(),key=lambda item:(item[1]['region'],item[1]['name'])))
    return f'<section class="edu-local edu-shell" data-local-picker aria-labelledby="local-title"><h2 id="local-title">읽은 내용을, 가까운 상담에서 이어 보세요.</h2><p>최근 학습 자료와 남은 질문을 준비해 지점의 실제 수업 안내를 확인해 보세요.</p><div class="edu-local-picker"><label for="local-branch">가까운 지점<select id="local-branch" data-branch-select><option value="">지역·지점 선택</option>{options}</select></label><label for="local-neighborhood">연결된 동네 안내<select id="local-neighborhood" data-local-select disabled><option value="">지점을 먼저 선택해 주세요</option></select></label></div><div class="edu-local-links"><a href="/지점안내/" data-branch-link>가까운 지점 안내 보기 →</a><a href="/과목별학원/" data-local-link>동네별 학원 안내 보기 →</a><a href="/상담문의/">상담 전 확인할 내용 →</a></div><p class="edu-local-status" data-local-status role="status" aria-live="polite">지점을 고르면 연결된 동네 안내도 선택할 수 있습니다.</p><noscript><p>지점 선택 기능은 자바스크립트가 필요합니다. 위의 전체 지점·동네 안내 버튼으로 찾아보세요.</p></noscript></section>'
def figure(image):
    return f'<figure class="edu-figure"><img src="{image["path"]}" width="{image["width"]}" height="{image["height"]}" alt="{E(image["alt"])}" loading="lazy" decoding="async"><figcaption>{E(image["alt"])} · 학습 참고 사진</figcaption></figure>'
def article_card(a):
    im=a['images'][0]
    return f'<article class="edu-card" data-edu-card data-stage="{",".join(a["stages"])}" data-category="{a["category"]}" data-search="{E(a["title"]+" "+a["intro"]+" "+CATEGORIES[a["category"]])}"><img src="{im["path"]}" width="{im["width"]}" height="{im["height"]}" alt="{E(a["title"]+" 본문 참고 사진: "+im["alt"])}" loading="lazy" decoding="async"><div class="edu-card-copy"><span class="edu-tags">{CATEGORIES[a["category"]]} · {' · '.join(a["stages"])}</span><h3><a href="/교육정보/{a["slug"]}/">{E(a["title"])}</a></h3><p>{E(a["description"])}</p><a class="edu-open" href="/교육정보/{a["slug"]}/">글 읽기 ↗<span class="sr-only"> · {E(a["title"])}</span></a></div></article>'
def filters(curriculum=False):
    third='<label for="edu-subject">과목<select id="edu-subject" data-subject-input><option value="">모든 과목</option>'+''.join('<option>'+s+'</option>' for s in ['국어','영어','수학','사회','과학','역사'])+'</select></label>' if curriculum else ''
    return '<form class="edu-filters" role="search"><label for="edu-search">찾고 싶은 질문·키워드<input id="edu-search" data-search-input type="search" autocomplete="off" placeholder="예: 복습, 수면, 상담, 수학"></label><label for="edu-stage">학교급<select id="edu-stage" data-stage-input><option value="">모든 학교급</option><option>초등</option><option>중등</option><option>고등</option></select></label>'+third+'<button type="button" class="edu-reset" data-reset>초기화</button></form>'
def empty(): return '<div class="edu-empty" data-empty hidden><h3>조건에 맞는 글이 없습니다.</h3><p>검색어를 짧게 바꾸거나 선택 조건을 풀어 보세요.</p><button class="edu-reset" type="button" data-reset>전체 보기</button></div><noscript><p>검색 없이도 아래의 모든 페이지를 바로 읽을 수 있습니다.</p></noscript>'
def education():
    for i,a in enumerate(ARTICLES):
        path='/교육정보/'+a['slug']+'/'
        trail=[('교육정보','/교육정보/'),(CATEGORIES[a['category']],None)]
        toc=[(f's{j}',t) for j,(t,_) in enumerate(a['sections'],1)]+[('example','연습 예시와 점검'),('parent','학부모의 도움'),('faq','질문과 답'),('sources','참고 자료')]
        content=f'<header class="edu-article-hero edu-shell">{crumbs(trail)}<p class="edu-kicker">{CATEGORIES[a["category"]]} · 학생과 학부모</p><h1>{E(a["title"])}</h1><p class="edu-lead">{E(a["intro"])}</p><div class="edu-article-meta"><span>{" · ".join(a["stages"])}</span><span>내용 확인 <time datetime="{DATE}">2026.10.05</time></span></div></header><div class="edu-layout edu-shell"><aside class="edu-toc"><nav aria-label="이 글의 목차"><strong>이 글에서 확인할 것</strong>'+''.join(f'<a href="#{ident}">{E(label)}</a>' for ident,label in toc)+'<a href="/교육정보/">← 교육정보 전체</a></nav></aside><article class="edu-body">'
        for j,(heading,text) in enumerate(a['sections'],1):
            content+=f'<section id="s{j}"><p class="edu-section-no">{j:02d} · 실행하기</p><h2>{E(heading)}</h2>{paras(text)}</section>'
            if j in [1,2,4]: content+=figure(a['images'][[1,2,4].index(j)])
        content+=f'<section id="example"><h2>내 자료에 적용해 보기</h2><div class="edu-example">{paras(a["example"])}<small>실제 학생의 성과 사례가 아닌 설명용 예시입니다. 자신의 교과서와 과제에 맞춰 사용하세요.</small></div><h3>공부를 마친 뒤 확인할 질문</h3><ul class="edu-checks">'+''.join('<li>'+E(c)+'</li>' for c in a['checks'])+f'</ul></section><section id="parent"><h2>학부모는 이렇게 도와주세요</h2>{paras(a["parent"])}</section><section id="faq"><h2>자주 묻는 질문</h2><div class="edu-faq">'+''.join(f'<details><summary>{E(q)}</summary>{paras(ans)}</details>' for q,ans in a['faq'])+'</div></section><section id="sources"><h2>더 살펴볼 참고 자료</h2><ul class="edu-sources">'+''.join(f'<li><a href="{E(SOURCES[k][1])}" target="_blank" rel="noopener noreferrer">{E(SOURCES[k][0])} ↗<span class="sr-only"> 새 창</span></a></li>' for k in a['sources'])+'</ul></section>'
        related=[b for b in ARTICLES if b['category']==a['category'] and b['slug']!=a['slug']][:2]
        content+='<section class="edu-related"><h2>다음 질문에 맞는 읽을거리</h2>'+''.join(f'<a href="/교육정보/{b["slug"]}/">{E(b["title"])} →</a>' for b in related)+f'<a href="/학습가이드/{a["guide"]}/">실천과 기록을 위한 학습가이드 →</a><a href="/학습커리큘럼/">학년·과목별 학습 중점 확인 →</a><a href="/교육정보/">교육정보 전체 보기 →</a></section></article></div>'
        page(a['title'],a['description'],path,content,trail,'Article',[SOURCES[k][1] for k in a['sources']],a['images'][0]['path'],a['faq'])
    title='학생·학부모를 위한 교육정보'; desc='공부 습관, 시험과 복습, 방학·새학기, 학부모 상담과 학습 도구의 질문을 30개 글로 안내합니다.'
    content=f'<header class="edu-hero edu-shell"><div>{crumbs([("교육정보",None)])}<p class="edu-kicker">공부와 생활을 잇는 30개의 질문</p><h1>오늘의 고민을,<br><em>다음 공부의 행동으로.</em></h1><p class="edu-lead">계획이 밀릴 때, 시험을 준비할 때, 수업을 고를 때.<br>학생과 학부모가 함께 확인할 질문과 실천 방법을 모았습니다.</p></div><aside class="edu-hero-aside"><h2>지금 필요한 질문부터</h2><a href="/교육정보/focus-restart/">공부가 손에 잡히지 않을 때 →</a><a href="/교육정보/exam-plan-evidence/">내신 계획의 우선순위 정하기 →</a><a href="/교육정보/class-selection-check/">수업을 고르기 전에 확인할 것 →</a><a href="/학습커리큘럼/">학년·과목별 커리큘럼 확인 →</a></aside></header><section class="edu-library edu-shell" data-edu-library id="education-library" aria-labelledby="education-library-title"><div class="edu-library-heading"><h2 id="education-library-title">나에게 필요한 교육정보</h2><span class="edu-count" data-count role="status" aria-live="polite">전체 30개</span></div>'+filters()+'<div class="edu-category" role="group" aria-label="주제 선택"><button type="button" data-category="" aria-pressed="true">전체</button>'+''.join(f'<button type="button" data-category="{key}" aria-pressed="false">{label}</button>' for key,label in CATEGORIES.items())+'</div>'+empty()+'<div class="edu-grid">'+''.join(article_card(a) for a in ARTICLES)+'</div></section>'
    page(title,desc,'/교육정보/',content,[('교육정보',None)],'CollectionPage')

def overview_notice():
    return '<aside class="curr-notice"><p><strong>2026학년도 적용을 먼저 확인하세요.</strong> 초1~6·중1~2·고1~2는 2022 개정, 중3·고3은 2015 개정 교육과정입니다. 2027년에는 중3·고3에도 2022 개정이 적용되므로 이 안내의 고3·중3 범위를 그대로 다음 해에 사용하지 마세요.</p><p>개별 학년의 순서와 확인 과제는 학습 예시입니다. 실제 교과서·진도·평가 계획과 과목 편성을 학교에서 확인하세요. 초1·2의 영어는 선택 활동, 사회·과학은 슬기로운 생활 연계 내용입니다.</p><a href="'+E(MOE)+'" target="_blank" rel="noopener noreferrer">교육부 교육과정 고시와 적용 일정 확인 ↗<span class="sr-only"> 새 창</span></a></aside>'
def subject_card(row):
    grade,subject=row[:2]; label=display(grade,subject)
    return f'<article class="curr-subject-card" data-edu-card data-stage="{stageof(grade)}" data-subject="{subject}" data-search="{E(fullgrade(grade)+" "+grade+" "+label+" "+row[4]+" "+row[6])}"><span class="edu-tags">{E(fullgrade(grade))} · {E(row[2])}</span><h3><a href="{cr(grade,subject)}">{E(label)}</a></h3><p>{E(row[4])}</p><a href="{cr(grade,subject)}">학습 순서·확인 과제 보기 →</a></article>'
def grade_cards(grades):
    return '<div class="curr-grade-grid">'+''.join(f'<a href="{cr(g[1])}">{E(fullgrade(g[1]))}<small>{E(g[2])}</small></a>' for g in grades)+'</div>'
def curriculum(sheets):
    grades=sheets['학년별개요'][5:]; rows=sheets['초등과목'][5:]+sheets['중등과목'][5:]+sheets['고등과목'][5:]
    levels=sheets['반별운영'][5:]; electives=sheets['고등선택과목'][5:]; checks=sheets['학교별적용'][5:]
    assert (len(grades),len(rows),len(levels),len(electives),len(checks))==(12,66,45,29,12)
    title='학년·과목별 학습커리큘럼'; desc='초등·중등·고등 12개 학년의 과목별 학습 중점과 확인 과제, 수준별 연습과 학교별 확인 사항을 안내합니다.'
    content='<header class="edu-hero edu-shell"><div>'+crumbs([('학습커리큘럼',None)])+'<p class="edu-kicker">12개 학년 · 66개 학년·과목 안내</p><h1>어디까지 배웠고,<br><em>무엇을 확인할까요?</em></h1><p class="edu-lead">학년과 과목을 고르고 학습 중점, 연습 순서, 확인 과제를 살펴보세요. 지금 필요한 도움을 정리해 학교 진도와 상담에 연결할 수 있습니다.</p></div><aside class="edu-hero-aside"><h2>학교급부터 고르기</h2>'+''.join(f'<a href="/학습커리큘럼/{s}/">{s} 학년별 안내 →</a>' for s in ['초등','중등','고등'])+'<a href="/학습커리큘럼/고등선택과목/">고등 공통·선택과목 비교 →</a><a href="/학습커리큘럼/학교별확인/">학교 자료에서 확인할 것 →</a></aside></header><section class="edu-shell">'+overview_notice()+grade_cards(grades)+'</section><section class="edu-library edu-shell" data-edu-library aria-labelledby="curr-library-title"><div class="edu-library-heading"><h2 id="curr-library-title">학년과 과목으로 찾아보기</h2><span class="edu-count" data-count role="status" aria-live="polite">전체 66개</span></div>'+filters(True)+empty()+'<div class="edu-grid">'+''.join(subject_card(r) for r in rows)+'</div></section>'
    page(title,desc,'/학습커리큘럼/',content,[('학습커리큘럼',None)],'CollectionPage')
    for stage in ['초등','중등','고등']:
        group=[g for g in grades if stageof(g[1])==stage]; subgroup=[r for r in rows if stageof(r[0])==stage]
        title=stage+' 학년·과목별 학습 안내'; desc=stage+' 각 학년의 학습 중점과 과목별 연습 순서, 확인 과제를 학교 진도와 함께 살펴보도록 안내합니다.'
        content='<header class="edu-article-hero edu-shell">'+crumbs([('학습커리큘럼','/학습커리큘럼/'),(stage,None)])+f'<p class="edu-kicker">{stage} 학습의 연결</p><h1>{title}</h1><p class="edu-lead">학생이 혼자 할 수 있는 내용과 설명이 필요한 부분을 나누어 보세요. 학년별로 확인할 연결과 과목별 과제를 안내합니다.</p></header><section class="edu-library edu-shell">'+overview_notice()+grade_cards(group)+'<div class="edu-grid">'+''.join(subject_card(r) for r in subgroup)+'</div></section>'
        page(title,desc,'/학습커리큘럼/'+stage+'/',content,[('학습커리큘럼','/학습커리큘럼/'),(stage,None)],'CollectionPage')
    for g in grades:
        stage=stageof(g[1]); selected=[r for r in rows if r[0]==g[1]]
        title=fullgrade(g[1])+' 학습커리큘럼'; desc=fullgrade(g[1])+'의 과목별 학습 중점과 확인 과제, 교과서·진도·평가에서 살펴볼 사항을 안내합니다.'
        content='<header class="edu-article-hero edu-shell">'+crumbs([('학습커리큘럼','/학습커리큘럼/'),(stage,'/학습커리큘럼/'+stage+'/'),(fullgrade(g[1]),None)])+f'<p class="edu-kicker">2026학년도 · {E(g[2])}</p><h1>{title}</h1><p class="edu-lead">{E(g[4])}에 중점을 두고, 현재 학교 자료에서 가능한 내용과 필요한 도움을 확인하세요.</p></header><section class="edu-library edu-shell">'+overview_notice()+f'<aside class="curr-notice"><p><strong>이 학년에서 살펴볼 것</strong> · {E(g[4])}</p><p><strong>학교에서 확인</strong> · {E(g[5])}</p><p>최근 과제 하나를 자료 없이 해 본 뒤 막힌 지점을 표시하고 아래 과목 안내에서 연습 순서를 골라 보세요.</p></aside><div class="edu-grid">'+''.join(subject_card(r) for r in selected)+'</div><div class="edu-related"><h2>학습 계획과 학교 자료 함께 보기</h2><a href="/학습커리큘럼/학교별확인/">교과서·진도·평가 확인 목록 →</a><a href="/교육정보/grade-change-signals/">학년이 바뀔 때 확인할 신호 →</a>'+('<a href="/학습커리큘럼/고등선택과목/">입학 연도와 고등 선택과목 확인 →</a>' if stage=='고등' else '')+'</div></section>'
        page(title,desc,cr(g[1]),content,[('학습커리큘럼','/학습커리큘럼/'),(stage,'/학습커리큘럼/'+stage+'/'),(fullgrade(g[1]),None)],'CollectionPage')
    advice={
     '국어':('읽은 내용의 근거와 표현을 함께 확인하세요. 답안을 길게 쓰기보다 질문이 요구한 내용과 범위를 맞추는 연습이 필요합니다.','학생이 고친 문장 한 개를 함께 읽고, 무엇을 근거로 바꾸었는지 들어 주세요.'),
     '영어':('어휘·문장·글의 의미를 연결해 보세요. 뜻을 외웠더라도 문장 안에서 역할과 의미를 설명할 수 있는지 확인합니다.','읽기나 듣기에서 막힌 부분을 표시하도록 돕고, 해석 답을 대신 알려 주기보다 질문을 들어 주세요.'),
     '수학':('답과 풀이의 이유를 구분해 확인하세요. 조건에서 식이나 그림으로 옮기는 단계, 계산, 결과의 검증 중 처음 막힌 곳을 표시합니다.','정답 여부만 묻기보다 첫 식을 세운 이유를 들어 주세요. 반복 실수는 계산한 줄과 조건을 함께 살펴봅니다.'),
     '사회':('자료의 시기·지역·비교 기준을 읽고 개념과 연결하세요. 용어의 뜻을 외우는 것과 사례에 적용해 설명하는 것을 나누어 확인합니다.','지도나 자료의 출처를 함께 확인하고 학생이 관찰한 사실과 해석을 구분해 말하도록 도와주세요.'),
     '과학':('관찰과 설명의 근거를 구분하세요. 변인·측정·단위·자료의 관계를 확인하고 실험 결과가 어떤 조건에서 나온 것인지 기록합니다.','관찰 결과와 추측을 따로 들어 주세요. 실험은 학교의 안전 안내와 보호자의 확인 아래 진행합니다.'),
     '역사':('연표·지도·사료를 연결하고 사건의 원인과 결과를 설명하세요. 시기의 순서와 자료가 말하는 범위를 함께 확인합니다.','연도를 대신 외워 주기보다 두 사건의 연결을 학생이 설명하도록 질문해 주세요.')}
    for row in rows:
        grade,subject,revision,scope,focus,flow,task,adjust,copy,source,source_range=row
        stage=stageof(grade); label=display(grade,subject); path=cr(grade,subject)
        title=fullgrade(grade)+' '+label+' 학습 안내'; desc=fullgrade(grade)+' '+label+'의 학습 중점과 연습 순서, 이해를 확인할 과제와 학교별 조정 사항을 안내합니다.'
        low=grade in ['초1','초2'] and subject in ['영어','사회','과학']
        task_advice,parent_advice=advice[subject]
        if low:
            task_advice,parent_advice={
                '영어':('노래와 그림의 소리를 듣고 짧게 반응하며 즐겁게 참여하는지 살펴보세요. 읽기나 문장 해석을 필수로 요구하지 않고 익숙한 인사와 표현을 놀이 속에서 사용해 봅니다.','학생이 좋아하는 노래나 그림을 함께 고르고 듣고 따라 하는 활동에 가볍게 참여해 주세요. 정확한 발음이나 해석을 반복해서 검사하기보다 즐겁게 참여할 수 있는지 확인합니다.'),
                '사회':('학교와 생활 주변의 모습에서 본 것을 그림이나 말로 표현해 보세요. 우리 생활에서 지킬 약속과 서로 도울 수 있는 일을 실제 경험에 연결합니다.','등굣길이나 교실에서 경험한 일을 함께 이야기하고 학생이 직접 본 것부터 말하도록 도와주세요. 어려운 용어를 외우게 하기보다 생활 속 질문을 나눕니다.'),
                '과학':('주변 사물과 계절의 모습을 관찰하고 달라진 점을 그림이나 말로 나타내 보세요. 측정이나 변인 용어를 앞세우기보다 무엇을 보았고 어떤 점이 궁금한지 이야기합니다.','관찰한 모습과 궁금한 점을 따로 들어 주세요. 산책이나 안전한 관찰 활동에서 학생이 찾은 작은 차이를 함께 살펴보고, 재료와 활동은 학교의 안전 안내에 맞춥니다.')
            }[subject]
        level_stage={'초등':'초등학생','중등':'중학생','고등':'고등학생'}[stage]
        chosen=[l for l in levels if l[0]==level_stage and l[1]==subject] if not low else []
        if not low and subject!='역사':
            assert len(chosen)==3, (grade,subject,'missing level plans')
        trail=[('학습커리큘럼','/학습커리큘럼/'),(fullgrade(grade),cr(grade)),(label,None)]
        toc=[('focus','학습 중점'),('flow','연습 순서'),('task','확인 과제'),('levels','필요한 도움 고르기'),('school','학교와 함께 확인'),('family','학부모의 도움')]
        content='<header class="edu-article-hero edu-shell">'+crumbs(trail)+f'<p class="edu-kicker">2026학년도 · {E(revision)} · {E(scope)}</p><h1>{E(title)}</h1><p class="edu-lead">{E(copy)}</p></header><div class="edu-layout edu-shell"><aside class="edu-toc"><nav aria-label="학습 안내 목차"><strong>학습을 정리하는 순서</strong>'+''.join(f'<a href="#{i}">{t}</a>' for i,t in toc)+f'<a href="{cr(grade)}">← {E(fullgrade(grade))} 전체</a></nav></aside><article class="edu-body">'
        content+=f'<section id="focus"><h2>이번 학습에서 확인할 중점</h2>{paras(focus)}<aside class="edu-note"><strong>범위와 실제 진도를 구분하세요.</strong>{paras(adjust)}<p>위 내용은 학습을 준비하는 안내이며, 해당 지점의 실제 수업 개설이나 학교의 확정 단원 순서를 뜻하지 않습니다.</p></aside></section><section id="flow"><h2>현재 수준에서 시작하는 연습 순서</h2><p>이 순서는 예시입니다. 최근 교과서와 과제에서 혼자 가능한 단계를 확인하고, 막힌 단계의 설명과 연습부터 골라 보세요.</p><ol class="curr-flow">'+''.join('<li>'+E(s.strip())+'</li>' for s in flow.split('→'))+f'</ol></section><section id="task"><h2>이해를 확인하는 과제</h2><div class="edu-example">{paras(task)}<small>학교가 지정한 실제 제출 과제를 대신하는 안내가 아닙니다. 학습 확인용으로 분량과 자료를 조절하세요.</small></div>{paras(task_advice)}<ul class="edu-checks"><li>자료 없이 어디까지 설명하거나 수행했나요?</li><li>처음 막힌 개념·조건·표현을 표시했나요?</li><li>설명을 받은 뒤 혼자 다시 확인할 과제가 있나요?</li></ul></section><section id="levels"><h2>지금 필요한 도움과 과제 고르기</h2>'
        if chosen:
            content+='<p>기초·표준·심화는 과제를 고르는 예시이며 공식 성취등급이나 지점의 개설 반 명칭이 아닙니다. 점수 하나로 고정하지 말고 영역별 수행을 확인하며 조절하세요.</p>'
            for l in chosen:
                content+='<article class="curr-level"><h3>'+E(l[2].removesuffix('반'))+' 연습 예시</h3><dl>'+''.join(f'<dt>{label}</dt><dd>{E(l[idx])}</dd>' for label,idx in [('이럴 때 살펴보기',3),('연습의 연결',4),('확인할 과제',5),('다음 단계 판단',6)])+'</dl></article>'
            content+='<details class="curr-level"><summary>교재·자료를 고를 때 확인할 후보</summary><p>다음은 자료 후보입니다. 해당 지점의 실제 사용 교재나 구매 권장을 뜻하지 않습니다. 학년·학기·개정판·현재 과제에 맞는지 확인하세요.</p><ul>'+''.join(f'<li>{E(l[2].removesuffix("반"))}: {E(l[7])}</li>' for l in chosen)+'</ul><a href="'+E(chosen[0][9])+'" target="_blank" rel="noopener noreferrer">자료 제공처의 실제 안내 확인 ↗<span class="sr-only"> 새 창</span></a></details>'
        elif low:
            content+='<p>'+('초1·2 영어는 정규 영어 교과의 필수 선행이 아닌 선택 활동입니다. 학생의 흥미와 참여 의사를 먼저 확인하고 짧은 듣기·반응 활동에서 부담을 조절하세요.' if subject=='영어' else '초1·2의 이 내용은 별도의 정규 '+subject+' 교과가 아닌 슬기로운 생활 연계 활동입니다. 학교 통합교과의 실제 주제와 관찰·말하기 과제에 맞춰 사용하세요.')+'</p><p>과제의 양이나 난이도를 늘리기 전에 학생이 활동을 이해하고 말할 수 있는지 확인합니다. 완료 기간과 수업 시간은 이 안내에서 정하지 않습니다.</p>'
        else:
            content+='<p>역사는 연표·지도·자료 읽기와 설명 과제에서 필요한 도움을 먼저 확인하세요. 정해진 수준별 반을 제시하기보다 실제 이수 범위와 최근 답안에서 시작합니다.</p><p>자료를 이해하지 못했다면 어휘·시기·공간을 먼저 확인하고, 설명은 가능하지만 비교가 어렵다면 사건 간 변화와 지속의 근거를 나누어 연습합니다.</p>'
        content+=f'</section><section id="school"><h2>학교 진도와 함께 확인하세요</h2>{paras(adjust)}<p>학습 안내 기준은 2026학년도입니다. 특히 중3·고3의 2015 개정 범위는 2027학년도에 다시 확인해야 합니다.</p>'+('<p>중학교 사회·역사의 실제 이수 학년·학기는 학교 편제에 따라 달라집니다. 고등학생은 입학 연도별 교육과정과 실제 개설 과목·선이수·학기를 확인하세요.</p>' if subject in ['사회','역사'] or stage=='고등' else '')+'<a href="/학습커리큘럼/학교별확인/">교과서·진도·평가 확인 목록 →</a></section><section id="family"><h2>학부모가 도울 수 있는 방법</h2>'+paras(parent_advice)+'<p>상담에는 최근 과제와 학생이 남긴 질문을 가져가세요. 희망 학년·과목·가능한 일정은 지점에서 실제 운영 여부를 확인합니다.</p></section><section><h2>교육과정 참고 자료</h2><ul class="edu-sources"><li><a href="'+E(source)+'" target="_blank" rel="noopener noreferrer">교육과정 원문 안내 ↗<span class="sr-only"> 새 창</span></a> · '+E(source_range)+'</li></ul></section><section class="edu-related"><h2>이어서 살펴보기</h2><a href="'+cr(grade)+'">'+E(fullgrade(grade))+' 다른 과목 보기 →</a><a href="/교육정보/after-class-review/">수업 뒤 복습의 네 가지 확인 →</a><a href="/교육정보/adaptive-learning/">현재 이해와 피드백으로 도움 고르기 →</a>'+('<a href="/학습커리큘럼/고등선택과목/#elective-'+subject+'">'+subject+' 공통·선택과목 비교 →</a>' if stage=='고등' else '')+'</section></article></div>'
        page(title,desc,path,content,trail)
    title='고등 공통·선택과목 준비와 비교'; desc='2022 개정의 고등 공통·선택과목 29개 항목을 내용과 준비 개념으로 비교하고 실제 학교 개설을 확인하도록 안내합니다.'
    trail=[('학습커리큘럼','/학습커리큘럼/'),('고등 공통·선택과목',None)]
    content='<header class="edu-article-hero edu-shell">'+crumbs(trail)+f'<p class="edu-kicker">2022 개정 · 공통과 선택을 구분하기</p><h1>{title}</h1><p class="edu-lead">과목 이름이 비슷해도 내용과 준비 개념은 다를 수 있습니다. 입학 연도별 적용 교육과정과 학교의 실제 개설 과목을 먼저 확인하세요.</p></header><div class="edu-layout edu-shell"><aside class="edu-toc"><nav aria-label="선택과목 분야"><strong>교과별 살펴보기</strong>'+''.join('<a href="#elective-'+s+'">'+s+'</a>' for s in ['국어','수학','영어','사회','역사','과학'])+'</nav></aside><article class="edu-body"><aside class="curr-notice"><p>아래 항목은 2022 개정의 대표 공통·선택과목 안내입니다. 모든 선택과목을 망라한 목록이나 모든 학교의 개설표가 아닙니다.</p><p>2026학년도 고3은 2015 개정 교육과정을 적용합니다. 고3의 실제 과목명·이수 범위를 아래 목록으로 바꾸어 해석하지 마세요.</p></aside>'
    for subject in ['국어','수학','영어','사회','역사','과학']:
        content+='<section id="elective-'+subject+'"><h2>'+subject+' 과목의 연결</h2>'
        for e in [e for e in electives if e[0]==subject]:
            content+=f'<article class="curr-elective"><span class="edu-tags">{E(e[1])}</span><h3>{E(e[2])}</h3><dl>'+''.join(f'<dt>{label}</dt><dd>{E(e[idx])}</dd>' for label,idx in [('내용 범위',3),('준비 개념',4),('학습 연결 예시',5),('학교에서 확인',6)])+'</dl></article>'
        content+='</section>'
    content+='<section><h2>선택 전에 준비할 질문</h2><ul class="edu-checks"><li>내 입학 연도에 적용되는 교육과정인가요?</li><li>학교에서 실제 개설하는 학년·학기와 선택 조건은 무엇인가요?</li><li>필요한 이전 개념과 선이수를 확인했나요?</li><li>진로와 관심을 이유·자료로 설명할 수 있나요?</li></ul><a href="/학습커리큘럼/학교별확인/">학교 자료 확인 목록 →</a></section><section><h2>과목별 교육과정 원문</h2><ul class="edu-sources"><li><a href="'+E(MOE)+'" target="_blank" rel="noopener noreferrer">교육부 2022 개정 교육과정 총론·각론 ↗<span class="sr-only"> 새 창</span></a></li></ul></section></article></div>'
    page(title,desc,'/학습커리큘럼/고등선택과목/',content,trail)
    title='학교별 교과서·진도·평가 확인 목록'; desc='학교와 학년·학기, 적용 교육과정, 교과서·진도·평가 계획을 확인하고 학습 과제를 조절하는 12가지 질문을 안내합니다.'
    trail=[('학습커리큘럼','/학습커리큘럼/'),('학교별 확인',None)]
    content='<header class="edu-article-hero edu-shell">'+crumbs(trail)+f'<p class="edu-kicker">학교 자료에서 확인하기</p><h1>{title}</h1><p class="edu-lead">학교명과 실제 자료가 확인되기 전에는 공통 학습 안내를 학교의 확정 계획으로 사용하지 마세요. 아래 항목을 확인해 학생의 과제와 상담 질문을 구체적으로 정리할 수 있습니다.</p></header><div class="edu-layout edu-shell"><aside class="edu-toc"><nav aria-label="학교 확인 목차"><strong>12가지 확인 항목</strong>'+''.join(f'<a href="#check-{i}">{E(c[1])}</a>' for i,c in enumerate(checks,1))+'</nav></aside><article class="edu-body">'
    for i,c in enumerate(checks,1):
        content+=f'<section id="check-{i}"><p class="edu-section-no">{i:02d} · {E(c[0])}</p><h2>{E(c[1])}</h2><p><strong>확인할 자료·경로</strong> · {E(c[2])}</p><p><strong>학습에 연결하기</strong> · {E(c[3])}</p><aside class="edu-note">{paras(c[4])}</aside></section>'
    content+='<section class="edu-related"><h2>자료를 확인한 뒤 이어 보기</h2><a href="/학습커리큘럼/">학년·과목별 중점 다시 보기 →</a><a href="/교육정보/exam-plan-evidence/">학교 자료로 내신 계획 정하기 →</a><a href="/교육정보/year-end-consultation/">상담 질문과 자료 준비하기 →</a></section></article></div>'
    page(title,desc,'/학습커리큘럼/학교별확인/',content,trail)

def patch_existing(scope):
    def patch(rel):
        before=read(rel); after=decorate_study_page(before,path_of(rel))
        if before!=after: write(rel,after); return rel
    with ThreadPoolExecutor(max_workers=12) as pool: changed=[r for r in pool.map(patch,scope) if r]
    css=read('assets/site.css'); marker='/* Education and curriculum navigation */'
    if marker not in css:
        css+='\n'+marker+'\n.site-header .nav a { white-space:nowrap; padding-inline:9px; }\n@media (min-width:721px) and (max-width:1160px) { .site-header .header-inner { display:grid; grid-template-columns:1fr; gap:10px; padding-block:12px; } .site-header .brand { justify-self:center; } .site-header .nav { display:grid; width:100%; grid-template-columns:repeat(8,minmax(0,1fr)); } .site-header .nav a { padding:9px 2px; font-size:13px; } }\n@media (max-width:720px) { .site-header .nav { grid-template-columns:repeat(4,minmax(0,1fr)); } .site-header .nav a { font-size:12px; padding:8px 1px; } }\n@media (max-width:350px) { .site-header .nav a { font-size:11px; } }\n'
        write('assets/site.css',css)
    # Future generation uses the same guarded decorator, preserving the menu and CTAs.
    text=read('tools/generate_subject_pages.py')
    if 'from study_resource_links import decorate_study_page' not in text:
        text=text.replace('from teacher_directory_links import decorate_branch_body','from teacher_directory_links import decorate_branch_body\nfrom study_resource_links import decorate_study_page',1)
        text=text.replace('                (target / "index.html").write_text(page, encoding="utf-8")','                page = decorate_study_page(page, f"/과목별학원/{config[\'slug\']}/{slug}/")\n                (target / "index.html").write_text(page, encoding="utf-8")',1)
        # Shared navigation also feeds the branch page generator.
        text=text.replace('("teachers", "/선생님찾기/", "선생님찾기"),','("teachers", "/선생님찾기/", "선생님찾기"),\n        ("education", "/교육정보/", "교육정보"),\n        ("curriculum", "/학습커리큘럼/", "학습커리큘럼"),',1)
        text=text.replace('<a href="/선생님찾기/">선생님찾기</a>','<a href="/선생님찾기/">선생님찾기</a>'+MENU,1)
        write('tools/generate_subject_pages.py',text)
    text=read('tools/generate_branch_pages.py')
    if 'from study_resource_links import decorate_study_page' not in text:
        text=text.replace('from teacher_directory_links import decorate_branch_body','from teacher_directory_links import decorate_branch_body\nfrom study_resource_links import decorate_study_page',1)
        old="    return '<!DOCTYPE html>\\n<html lang=\"ko\">\\n' + head"
        assert old in text
        text=text.replace(old,"    html = '<!DOCTYPE html>\\n<html lang=\"ko\">\\n' + head",1)
        text=text.replace('\n\n\ndef search_controls(', '\n    return decorate_study_page(html, path)\n\n\ndef search_controls(',1)
        write('tools/generate_branch_pages.py',text)
    text=read('tools/generate_learning_guides.py')
    if 'from study_resource_links import decorate_study_page' not in text:
        text=text.replace('from learning_guides_data import GUIDES, SOURCES, CATEGORIES','from learning_guides_data import GUIDES, SOURCES, CATEGORIES\nfrom study_resource_links import decorate_study_page',1)
        text=text.replace("    dest=ROOT/path; dest.parent.mkdir", "    if path.endswith('index.html'): text=decorate_study_page(text,'/'+path.removesuffix('index.html'))\n    dest=ROOT/path; dest.parent.mkdir",1)
        write('tools/generate_learning_guides.py',text)
    text=read('tools/generate_teacher_directory.py')
    if 'from study_resource_links import decorate_study_page' not in text:
        text=text.replace('from teacher_directory_links import decorate_branch_body','from teacher_directory_links import decorate_branch_body\nfrom study_resource_links import decorate_study_page',1)
        # This generator's writer is nested under run; keep byte preservation behavior.
        needle="        raw=text.encode('utf-8'); dest=root/rel"
        assert needle in text
        text=text.replace(needle,"        if rel.endswith('index.html'): text=decorate_study_page(text,'/'+rel.removesuffix('index.html'))\n"+needle,1)
        write('tools/generate_teacher_directory.py',text)
    return changed

def discovery(changed,images):
    sitemap=read('sitemap.xml'); nl='\r\n' if '\r\n' in sitemap else '\n'
    paths=set(NEW_PAGES)|{path_of(r) for r in changed}
    def update(match):
        text=match[0]; loc=re.search(r'<loc>(.*?)</loc>',text)[1]
        if unquote(loc.removeprefix(DOMAIN)) in paths: text=re.sub(r'<lastmod>[^<]*</lastmod>',f'<lastmod>{DATE}</lastmod>',text)
        return text
    sitemap=re.sub(r'<url>[\s\S]*?</url>',update,sitemap)
    add=''.join(f'  <url><loc>{URL(p)}</loc><lastmod>{DATE}</lastmod></url>'+nl for p in NEW_PAGES if '<loc>'+URL(p)+'</loc>' not in sitemap)
    write('sitemap.xml',sitemap.replace('</urlset>',add+'</urlset>'))
    rss=read('rss.xml'); nl='\r\n' if '\r\n' in rss else '\n'
    rss=re.sub(r'<lastBuildDate>[^<]*</lastBuildDate>','<lastBuildDate>Mon, 05 Oct 2026 00:00:00 +0900</lastBuildDate>',rss)
    entries=[(a['title'],'/교육정보/'+a['slug']+'/',a['description']) for a in ARTICLES]+[('학년·과목별 학습커리큘럼','/학습커리큘럼/',DESCRIPTIONS['/학습커리큘럼'])]
    additions=''.join(f'    <item><title>{E(t)}</title><link>{URL(p)}</link><guid isPermaLink="true">{URL(p)}</guid><description>{E(d)}</description><pubDate>Mon, 05 Oct 2026 00:00:00 +0900</pubDate></item>'+nl for t,p,d in entries if '<link>'+URL(p)+'</link>' not in rss)
    write('rss.xml',rss.replace('    <item>',additions+'    <item>',1))
    llms=read('llms.txt'); marker='## 교육정보와 학년별 커리큘럼'
    if marker in llms: llms=llms.split(marker)[0].rstrip()+'\n'
    llms+='\n'+marker+'\n\n'+''.join('- '+t+': '+URL(p)+'\n' for t,p,_ in entries)+''.join('- '+s+' 학습 안내: '+URL('/학습커리큘럼/'+s+'/')+'\n' for s in ['초등','중등','고등'])
    write('llms.txt',llms)
    mapping=json.loads(read('seo-descriptions.json'))
    for p,d in DESCRIPTIONS.items():
        assert len(d)<=80,(p,d)
        mapping['pages'][p]={'description':d,'sources':[d]}
    write('seo-descriptions.json',json.dumps(mapping,ensure_ascii=False,indent=2)+'\n')
    mp=ROOT/'release-public-manifest.json'
    if mp.exists():
        manifest=json.loads(mp.read_text(encoding='utf-8'))
        for name in set(WRITTEN)|{'assets/education.css','assets/education.js','assets/education/locations.json'}|{im['path'].lstrip('/') for im in images}:
            if name.startswith(('tools/','reports/')) or name=='seo-descriptions.json': continue
            raw=(ROOT/name).read_bytes(); manifest['files'][name]=hashlib.sha256(raw).hexdigest(); manifest['textSha256'][name]=hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()
        manifest.update(sitemapPages=len(re.findall('<loc>',sitemap))+len(re.findall('<loc>',add)),updatedAt=DATE,educationArticles=30,curriculumPages=84)
        mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def run(root,out,scope,prepared=False,pages_only=False):
    global ROOT,HEADER,FOOTER,FLOATING,BRANCHES
    ROOT=root
    if not prepared: sheets,images=prepare(out)
    else:
        sheets=json.loads(read('tools/data/curriculum/workbook.json'))['sheets']
        images=json.loads(read('tools/data/education/images.json'))
        for i,a in enumerate(ARTICLES):
            a['description']=a['intro'].split('. ')[0].rstrip('.')+'.'; a['images']=images[i*3:i*3+3]
            if a['guide']=='grade-transition': a['guide']='middle-transition'
    BRANCHES=locations(scope)
    base=decorate_study_page(read('index.html'),'/')
    HEADER=re.search(r'<header class="site-header">[\s\S]*?</header>',base)[0]
    FOOTER=re.search(r'<footer class="site-footer">[\s\S]*?</footer>',base)[0]
    FLOATING=re.search(r'<aside class="floating-actions"[\s\S]*?</aside>',base)[0]
    education(); curriculum(sheets)
    changed=[] if pages_only else patch_existing(scope)
    assert len(NEW_PAGES)==115,len(NEW_PAGES)
    discovery(changed,images)
    result={'date':DATE,'educationArticles':30,'educationPages':31,'curriculumPages':84,'curriculumSubjects':66,'images':len(images),'imageBytes':sum(im['bytes'] for im in images),'branches':len(BRANCHES),'subjectContexts':len(json.loads(read('assets/education/locations.json'))['subjects']),'newPages':NEW_PAGES,'patchedHtml':changed,'written':sorted(set(WRITTEN))}
    label='worktree' if (root/'release-public-manifest.json').exists() else 'authoring'
    (out/(label+('-pages-regenerate' if pages_only else '-generate')+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if not isinstance(v,list)},ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,default=ROOT); p.add_argument('--out',type=Path,required=True); p.add_argument('--scope',type=Path,required=True); p.add_argument('--prepared',action='store_true'); p.add_argument('--pages-only',action='store_true'); a=p.parse_args()
    scope=json.loads(a.scope.read_text(encoding='utf-8')); scope=list(scope.get('files',scope)) if isinstance(scope,dict) else scope
    run(a.root.resolve(),a.out.resolve(),[r for r in scope if r.endswith('.html')],a.prepared,a.pages_only)
