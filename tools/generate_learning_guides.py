"""Generate only the learning-guide hub, its articles and discovery additions."""
from pathlib import Path
from html import escape
from urllib.parse import quote
import argparse, hashlib, json, re, subprocess
from learning_guides_data import GUIDES, SOURCES, CATEGORIES
from study_resource_links import decorate_study_page

DATE='2026-10-04'
DOMAIN='https://xn--9p4bn5e3wjn0a.com'
HUB='/학습가이드/'
ROOT=Path(__file__).resolve().parents[1]
E=escape
def url(path): return DOMAIN+quote(path,safe='/')
def route(g): return HUB+g['slug']+'/'
def link(g): return f'<a href="{route(g)}">{E(g["title"])}</a>'
BY_SLUG={g['slug']:g for g in GUIDES}
def readers(g): return '학부모' if g['slug'] in ['parent-talk','parent-progress'] else '학생,학부모'
parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,default=ROOT); args=parser.parse_args(); ROOT=args.root.resolve()
base=(ROOT/'학습가이드/index.html').read_text(encoding='utf-8')
header=re.search(r'<header class="site-header">[\s\S]*?</header>',base).group(0)
footer=re.search(r'<footer class="site-footer">[\s\S]*?</footer>',base).group(0)
floating=re.search(r'<aside class="floating-actions"[\s\S]*?</aside>',base).group(0)
written=[]
newline_styles={}
for discovery in ['sitemap.xml','rss.xml','llms.txt']:
    original=subprocess.run(['git','show','HEAD:'+discovery],cwd=ROOT,capture_output=True).stdout
    newline_styles[discovery]='\r\n' if b'\r\n' in original else '\n'
def write(path,text):
    if path.endswith('index.html'): text=decorate_study_page(text,'/'+path.removesuffix('index.html'))
    dest=ROOT/path; dest.parent.mkdir(parents=True,exist_ok=True)
    if path in newline_styles: text=text.replace('\r\n','\n').replace('\n',newline_styles[path])
    dest.write_text(text,encoding='utf-8',newline='\n'); written.append(path)
def head(title,description,path,graph,kind='article'):
    canonical=url(path)
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)} | 영수코칭</title><meta name="description" content="{E(description)}"><meta name="robots" content="index,follow,max-image-preview:large">
<link rel="canonical" href="{canonical}"><link rel="alternate" type="application/rss+xml" title="영수코칭 학습 소식" href="/rss.xml"><link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/assets/site.css?v=20260920-1"><link rel="stylesheet" href="/assets/learning-guides.css?v=20261004-1">
<meta property="og:type" content="{kind}"><meta property="og:locale" content="ko_KR"><meta property="og:site_name" content="영수코칭"><meta property="og:title" content="{E(title)} | 영수코칭"><meta property="og:description" content="{E(description)}"><meta property="og:url" content="{canonical}"><meta property="og:image" content="{DOMAIN}/assets/images/og-share.png"><meta property="og:image:alt" content="영수코칭 영어·수학 학습 안내">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{E(title)} | 영수코칭"><meta name="twitter:description" content="{E(description)}"><meta name="twitter:image" content="{DOMAIN}/assets/images/og-share.png">
<script type="application/ld+json">{json.dumps({'@context':'https://schema.org','@graph':graph},ensure_ascii=False,separators=(',',':'))}</script>
</head><body class="learning-page"><a class="skip-link" href="#main">본문 바로가기</a>{header}'''
def tail(): return f'{footer}{floating}<script src="/assets/site.js" defer></script><script src="/assets/learning-guides.js?v=20261004-1" defer></script></body></html>'
org={'@type':'EducationalOrganization','@id':DOMAIN+'/#organization','name':'영수코칭','url':DOMAIN+'/','logo':DOMAIN+'/assets/favicon.png'}
website={'@type':'WebSite','@id':DOMAIN+'/#website','url':DOMAIN+'/','name':'영수코칭','inLanguage':'ko-KR','publisher':{'@id':org['@id']}}
def breadcrumb(title=None,path=None):
    items=[{'@type':'ListItem','position':1,'name':'홈','item':DOMAIN+'/'},{'@type':'ListItem','position':2,'name':'학습가이드','item':url(HUB)}]
    if title: items.append({'@type':'ListItem','position':3,'name':title,'item':url(path)})
    return {'@type':'BreadcrumbList','itemListElement':items}
def card(g,compact=False):
    search=' '.join([g['title'],g['description'],g['audience'],g['intro']])
    return f'''<article class="guide-card" data-category="{g['category']}" data-grade="{','.join(g['grades'])}" data-reader="{readers(g)}" data-search="{E(search)}"><div class="guide-tags"><span>{CATEGORIES[g['category']]}</span><span>{' · '.join(g['grades'])}</span></div><h3>{link(g)}</h3><p>{E(g['description'])}</p><span class="guide-card-audience">{E(g['audience'])}</span><a class="guide-open" href="{route(g)}">가이드 읽기 <span aria-hidden="true">↗</span><span class="sr-only"> · {E(g['title'])}</span></a></article>'''

for g in GUIDES:
    path=route(g); canonical=url(path); title=g['title']; desc=g['description']
    page={'@type':'WebPage','@id':canonical+'#webpage','url':canonical,'name':title+' | 영수코칭','description':desc,'inLanguage':'ko-KR','isPartOf':{'@id':website['@id']},'datePublished':DATE,'dateModified':DATE,'mainEntity':{'@id':canonical+'#article'}}
    article={'@type':'Article','@id':canonical+'#article','headline':title,'description':desc,'abstract':desc,'datePublished':DATE,'dateModified':DATE,'inLanguage':'ko-KR','author':{'@id':org['@id']},'publisher':{'@id':org['@id']},'image':DOMAIN+'/assets/images/og-share.png','mainEntityOfPage':{'@id':page['@id']},'articleSection':CATEGORIES[g['category']],'citation':[SOURCES[k][1] for k in g['sources']]}
    faq={'@type':'FAQPage','@id':canonical+'#faq','mainEntity':[{'@type':'Question','name':q,'acceptedAnswer':{'@type':'Answer','text':a}} for q,a in g['faq']]}
    toc=[('start','먼저 확인'),('steps','실행 순서'),('example','연습 예시'),('record','나의 기록'),('parent','학부모의 도움'),('faq','질문과 답'),('sources','참고 자료')]
    content=head(title,desc,path,[org,website,page,article,breadcrumb(title,path),faq])
    content+=f'''<main id="main"><header class="guide-article-hero guide-shell"><nav class="breadcrumb" aria-label="현재 위치"><a href="/">홈</a><span aria-hidden="true">›</span><a href="{HUB}">학습가이드</a><span aria-hidden="true">›</span><span>{CATEGORIES[g['category']]}</span></nav><p class="guide-kicker">{CATEGORIES[g['category']]} · 실천 가이드</p><h1>{E(title)}</h1><p class="guide-summary">{E(desc)}</p><div class="guide-meta"><span>{' · '.join(g['grades'])}</span><span>학생·학부모</span><span>내용 확인 <time datetime="{DATE}">2026.10.04</time></span></div><p class="guide-who">이런 분께 · {E(g['audience'])}</p></header>
<div class="guide-layout guide-shell"><aside class="guide-toc"><nav aria-label="이 글의 목차"><strong>이 글에서 해 볼 일</strong>{''.join(f'<a href="#{i}">{t}</a>' for i,t in toc)}<a class="guide-back" href="{HUB}">← 가이드 전체</a></nav></aside><article class="guide-body">
<section id="start"><p class="guide-section-no">01 · 먼저 확인</p><h2>지금의 자료에서 시작하세요</h2><p>{E(g['intro'])}</p><ul class="guide-checks">{''.join(f'<li>{E(c)}</li>' for c in g['checks'])}</ul></section>
<section id="steps"><p class="guide-section-no">02 · 실행 순서</p><h2>오늘 해 볼 네 가지 행동</h2><ol class="guide-steps">{''.join(f'<li><h3>{E(t)}</h3><p>{E(p)}</p></li>' for t,p in g['steps'])}</ol></section>
<section id="example"><p class="guide-section-no">03 · 연습 예시</p><h2>설명을 실제 행동으로 바꾸기</h2><div class="guide-example"><p>{E(g['example'])}</p><small>실제 학생 사례가 아닌 설명용 예시입니다. 자신의 자료에 맞게 바꿔 사용하세요.</small></div></section>
<section id="record"><p class="guide-section-no">04 · 나의 기록</p><h2>오늘의 확인을 짧게 남기세요</h2><p>학교·이름 없이 학습 내용만 적어도 충분합니다. 다음 행동 한 가지를 찾는 데 사용하세요.</p><a class="guide-download" download href="/assets/learning-guides/forms/{g['slug']}.txt">빈 기록 양식 받기 ↓ <small>TXT</small></a><form class="guide-record" data-title="{E(title)}" data-slug="{g['slug']}">{''.join(f'<label for="record-{i}"><span>{E(f)}</span><textarea id="record-{i}" name="record-{i}" rows="3" maxlength="4000" placeholder="확인한 내용이나 아직 남은 질문을 적어 보세요."></textarea></label>' for i,f in enumerate(g['fields'],1))}<div class="guide-record-actions"><button type="button" data-save>작성 내용 TXT 저장 ↓</button><button type="button" data-print>이 페이지 인쇄</button><button type="button" data-clear>입력 비우기</button></div><p class="guide-record-notice">기록은 전송하거나 자동 보관하지 않습니다. 페이지를 떠나기 전에 TXT로 저장하세요.</p><p class="guide-save-status" role="status" aria-live="polite"></p><noscript><p>작성 내용 저장 기능은 자바스크립트가 필요합니다. 빈 양식을 받아 사용하거나 브라우저의 인쇄 기능을 이용하세요.</p></noscript></form><div class="guide-next-action"><h3>다음에 확인할 것</h3><p>{E(g['followup'])}</p></div></section>
<section id="parent"><p class="guide-section-no">05 · 함께 돕기</p><h2>학부모는 이렇게 도와주세요</h2><p>{E(g['parent'])}</p><aside class="guide-note"><strong>적용할 때 확인하세요</strong><p>{E(g['caution'])}</p></aside></section>
<section id="faq"><h2>자주 묻는 질문</h2><div class="guide-faq">{''.join(f'<details><summary>{E(q)}</summary><p>{E(a)}</p></details>' for q,a in g['faq'])}</div></section>
<section id="sources"><h2>더 살펴볼 참고 자료</h2><p>아래 자료의 학습 원리를 참고해 실행 순서와 예시를 구성했습니다. 외국의 교수 자료는 국내 학교의 출제·채점 기준과 구분해 읽고, 실제 과제·시험 조건은 학교 안내를 확인하세요.</p><ol class="guide-sources">{''.join(f'<li><a href="{E(SOURCES[k][1])}" target="_blank" rel="noopener noreferrer">{E(SOURCES[k][0])} ↗<span class="sr-only"> 새 창</span></a><span>{E(SOURCES[k][2])} · {E(SOURCES[k][3])}</span></li>' for k in g['sources'])}</ol></section>
<section class="guide-related"><h2>다음 질문에 맞는 가이드</h2><ul>{''.join(f'<li>{link(BY_SLUG[s])}</li>' for s in g['related'])}</ul><a href="{HUB}">학습가이드 전체 보기 →</a></section></article></div><section class="guide-bottom guide-shell"><h2>최근 자료와 남은 질문을 함께 정리해 보세요.</h2><p>학생이 시도한 풀이와 필요한 도움을 가져가면 상담의 시작점을 구체적으로 정할 수 있습니다.</p><a class="btn btn-primary" href="/상담문의/">상담 준비하기</a></section></main>'''+tail()
    write('학습가이드/'+g['slug']+'/index.html',content)
    write('assets/learning-guides/forms/'+g['slug']+'.txt','\ufeff'+title+'\r\n영수코칭 · 빈 학습 기록\r\n\r\n'+'\r\n\r\n'.join(f+'\r\n'+'_'*36 for f in g['fields'])+'\r\n\r\n다음에 확인할 것\r\n'+g['followup']+'\r\n')

desc='영어·수학, 계획과 복습, 학년·시험, 학부모 상담의 질문별 가이드와 연습·기록 양식을 안내합니다.'
collection={'@type':'CollectionPage','@id':url(HUB)+'#webpage','url':url(HUB),'name':'학생·학부모 학습가이드 | 영수코칭','description':desc,'inLanguage':'ko-KR','datePublished':'2026-08-02','dateModified':DATE,'isPartOf':{'@id':website['@id']},'mainEntity':{'@id':url(HUB)+'#guides'}}
items={'@type':'ItemList','@id':url(HUB)+'#guides','numberOfItems':len(GUIDES),'itemListElement':[{'@type':'ListItem','position':i,'url':url(route(g)),'name':g['title']} for i,g in enumerate(GUIDES,1)]}
hub=head('학생·학부모 학습가이드',desc,HUB,[org,website,collection,items,breadcrumb()],kind='website')
hub+=f'''<main id="main"><header class="guide-hub-hero guide-shell"><div class="guide-hero-copy"><nav class="breadcrumb" aria-label="현재 위치"><a href="/">홈</a><span aria-hidden="true">›</span><span aria-current="page">학습가이드</span></nav><p class="guide-kicker">STUDY GUIDES · 40개의 작은 시작</p><h1>영어와 수학의 막힌 순간,<br><em>오늘의 공부로</em> 이어가세요.</h1><p class="guide-summary">공부한 시간보다 무엇이 어려운지 먼저 살펴보세요. 나의 자료에서 질문을 찾고, 직접 해 보고, 다음 공부를 정할 수 있도록 안내합니다.</p><div class="guide-hero-facts"><span><strong>40</strong>주제별 가이드</span><span><strong>5</strong>고민별 분야</span><span><strong>TXT</strong>나만의 기록</span></div></div><aside class="guide-start-panel"><p>무엇부터 볼지 고민된다면</p><h2>지금의 질문 하나로<br>시작해 보세요.</h2>{''.join(f'<a href="{route(BY_SLUG[s])}"><span>{i:02d}</span><strong>{t}</strong><span aria-hidden="true">↗</span></a>' for i,(s,t) in enumerate([('math-start','수학, 어디서 막히는지 모르겠어요'),('sentence-structure','단어는 아는데 해석이 어려워요'),('planner','계획이 실제 공부로 이어지지 않아요'),('first-consultation','상담에서 무엇을 물어봐야 할까요')],1))}</aside></header>
<section class="guide-paths guide-shell" aria-labelledby="guide-path-title"><div><p class="guide-section-no">필요한 질문부터</p><h2 id="guide-path-title">지금 상황에 맞는 읽기 순서</h2></div><div class="guide-path-grid">{''.join(f'<article><h3>{t}</h3><p>{" → ".join(link(BY_SLUG[s]) for s in slugs)}</p></article>' for t,slugs in [('수학의 기초를 다시 볼 때',['math-start','calculation','worked-example']),('영어가 문장에서 막힐 때',['vocabulary','sentence-structure','reading-evidence']),('시험 계획을 세울 때',['exam-plan','exam-last-week','error-note']),('함께 공부를 도울 때',['parent-talk','homework','parent-progress'])])}</div></section>
<section id="guide-library" class="guide-library guide-shell" aria-labelledby="library-title"><div class="guide-library-head"><div><p class="guide-section-no">나에게 필요한 가이드</p><h2 id="library-title">오늘의 질문을 찾아보세요</h2><p>제목과 내용에서 검색하고 학년·독자를 골라 볼 수 있습니다.</p></div><span class="guide-count" aria-live="polite">전체 40개</span></div><form class="guide-filters" role="search"><label for="guide-search">질문이나 키워드<input id="guide-search" type="search" name="q" placeholder="예: 계산 실수, 영어 듣기, 숙제, 수행평가" autocomplete="off"></label><label for="guide-grade">학년<select id="guide-grade"><option value="">모든 학년</option><option>초등</option><option>중등</option><option>고등</option></select></label><label for="guide-reader">독자<select id="guide-reader"><option value="">학생·학부모</option><option>학생</option><option>학부모</option></select></label><button class="guide-reset" type="button" data-reset>초기화</button></form><div class="guide-category-buttons" role="group" aria-label="분야 선택"><button type="button" data-filter="" aria-pressed="true">전체 <span>40</span></button>{''.join(f'<button type="button" data-filter="{c}" aria-pressed="false">{label} <span>{sum(g["category"]==c for g in GUIDES)}</span></button>' for c,label in CATEGORIES.items())}</div><noscript><p>검색은 자바스크립트가 필요합니다. 아래의 모든 글을 바로 읽을 수 있습니다.</p></noscript><div class="guide-empty" hidden><h3>조건에 맞는 가이드가 없습니다.</h3><p>검색어를 짧게 바꾸거나 학년·분야 조건을 풀어 보세요.</p><button type="button" data-reset>전체 가이드 보기</button></div>'''
for c,label in CATEGORIES.items():
    ident={'math':'math','english':'english','habits':'planner','exam':'grade-guide','parent':'parents'}[c]
    hub+=f'<section class="guide-group" id="{ident}" data-group="{c}">'+('<span id="wrong-answer" class="guide-anchor-alias"></span>' if c=='habits' else '')+f'<div class="guide-group-head"><h2>{label}</h2><span>{sum(g["category"]==c for g in GUIDES)}개</span></div><div class="guide-grid">'+''.join(card(g) for g in GUIDES if g['category']==c)+'</div></section>'
hub+='</section><section class="guide-bottom guide-shell"><div><p class="guide-section-no">기록에서 다음 공부로</p><h2>정답보다, 다음에 바꿀 행동 하나.</h2><p>각 가이드의 기록 양식에 오늘 해 본 내용과 남은 질문을 적어 보세요.<br>TXT 저장과 인쇄로 다음 공부나 상담에 가져갈 수 있습니다.</p></div><a class="btn btn-primary" href="/상담문의/">상담 준비하기</a></section></main>'+tail()
write('학습가이드/index.html',hub)

# Preserve unrelated discovery entries and dates.
sitemap=(ROOT/'sitemap.xml').read_text(encoding='utf-8')
hub_url=url(HUB)
def refresh_hub(m):
    item=m.group(0)
    if re.search(r'<loc>'+re.escape(hub_url)+r'</loc>',item):
        item=re.sub(r'<lastmod>[^<]*</lastmod>',f'<lastmod>{DATE}</lastmod>',item)
    return item
sitemap=re.sub(r'<url>[\s\S]*?</url>',refresh_hub,sitemap)
new=[]
for g in GUIDES:
    loc=url(route(g))
    if f'<loc>{loc}</loc>' not in sitemap: new.append(f'  <url><loc>{loc}</loc><lastmod>{DATE}</lastmod></url>\n')
sitemap=sitemap.replace('</urlset>',''.join(new)+'</urlset>')
write('sitemap.xml',sitemap)
rss=(ROOT/'rss.xml').read_text(encoding='utf-8')
rss=re.sub(r'<lastBuildDate>[^<]*</lastBuildDate>','<lastBuildDate>Sun, 04 Oct 2026 00:00:00 +0900</lastBuildDate>',rss)
new=[]
for g in GUIDES:
    loc=url(route(g))
    if f'<link>{loc}</link>' not in rss:
        new.append(f'    <item><title>{E(g["title"])}</title><link>{loc}</link><guid isPermaLink="true">{loc}</guid><description>{E(g["description"])}</description><pubDate>Sun, 04 Oct 2026 00:00:00 +0900</pubDate></item>\n')
rss=rss.replace('    <item>',''.join(new)+'    <item>',1)
write('rss.xml',rss)
llms=(ROOT/'llms.txt').read_text(encoding='utf-8')
marker='\n## 질문별 학습가이드\n'
if marker in llms: llms=llms.split(marker)[0]
llms+=marker+'\n'+''.join(f'- {g["title"]}: {url(route(g))}\n' for g in GUIDES)
write('llms.txt',llms)

# The existing postprocessor uses an approved description map.
description_path=ROOT/'seo-descriptions.json'
if description_path.exists():
    mapping=json.loads(description_path.read_text(encoding='utf-8'))
    for path,description in [(HUB,desc)]+[(route(g),g['description']) for g in GUIDES]:
        key=path.rstrip('/')
        old=mapping['pages'].get(key,{})
        sources=list(dict.fromkeys(old.get('sources',[])+([old['description']] if old.get('description') else [])+[description]))
        mapping['pages'][key]={'description':description,'sources':sources}
    description_path.write_text(json.dumps(mapping,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

# Refresh only generated public entries in the snapshot manifest.
manifest_path=ROOT/'release-public-manifest.json'
if manifest_path.exists():
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    for name in written+['assets/learning-guides.css','assets/learning-guides.js']:
        data=(ROOT/name).read_bytes(); manifest['files'][name]=hashlib.sha256(data).hexdigest()
        if 'textSha256' in manifest: manifest['textSha256'][name]=hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()
    manifest['sitemapPages']=len(re.findall(r'<loc>',sitemap)); manifest['updatedAt']=DATE; manifest['learningGuides']=len(GUIDES)
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'guides':len(GUIDES),'categories':{v:sum(g['category']==k for g in GUIDES) for k,v in CATEGORIES.items()},'generatedFiles':len(written),'sitemapPages':len(re.findall(r'<loc>',sitemap))},ensure_ascii=False))
