"""Render reviewed teacher rows and add scoped navigation/branch links.

No workbook writes, API access, commit, push or deployment.
--scope contains existing public relative file paths, preserving other source pages.
"""
from pathlib import Path
from html import escape, unescape
from urllib.parse import quote
from collections import Counter
import argparse, hashlib, json, re, shutil
from teacher_directory_links import decorate_branch_body
from study_resource_links import decorate_study_page

DOMAIN='https://xn--9p4bn5e3wjn0a.com'
HUB='/선생님찾기/'
DATE='2026-10-04'
E=escape
URL=lambda path: DOMAIN+quote(path,safe='/#')
ROOT=Path(__file__).resolve().parents[1]

def menu(html):
    def inject(match):
        nav=match[0]
        if 'href="/선생님찾기/"' in nav: return nav
        return re.sub(r'(<a\b[^>]*href="/학습가이드/"[^>]*>학습가이드</a>)',r'\1<a href="/선생님찾기/">선생님찾기</a>',nav,count=1)
    html=re.sub(r'<nav class="nav"[^>]*>[\s\S]*?</nav>',inject,html)
    html=re.sub(r'<div class="footer-links"[^>]*>[\s\S]*?</div>',inject,html)
    return html

def patch_existing(text, rel, root):
    text=menu(text)
    path='/' if rel=='index.html' else '/'+rel.removesuffix('index.html')
    if path.startswith(('/지점안내/','/과목별학원/')):
        text=decorate_branch_body(text,path,root)
        if '<!-- teacher-directory:start -->' in text and 'href="/assets/teachers.css' not in text:
            text=text.replace('</head>','<link rel="stylesheet" href="/assets/teachers.css?v=20261004-1">\n</head>',1)
    return text

def run(root, scope, photos):
    data=json.loads((root/'tools/data/teachers/directory.json').read_text(encoding='utf-8'))
    branches=[b for b in data['branches'] if b['included']]
    branches.sort(key=lambda b:(b['region'],b['name']))
    used=[]; changed=[]; contexts=[]; added=[]
    descriptions={}
    def write(rel,text):
        if rel.endswith('index.html'): text=decorate_study_page(text,'/'+rel.removesuffix('index.html'))
        raw=text.encode('utf-8'); dest=root/rel
        if not dest.exists(): added.append(rel)
        if not dest.exists() or dest.read_bytes()!=raw:
            dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(raw); changed.append(rel)
        used.append(rel)
    for image in data['photos']:
        rel='assets/teachers/'+image['file']; dest=root/rel
        raw=(photos/image['file']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==image['sha256'], 'Photo changed: '+image['file']
        if not dest.exists() or dest.read_bytes()!=raw:
            dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(raw); changed.append(rel)
        used.append(rel)
    base=menu((root/'학습가이드/index.html').read_bytes().decode('utf-8'))
    header=re.search(r'<header class="site-header">[\s\S]*?</header>',base)[0]
    header=re.sub(r' aria-current="page"','',header)
    header=header.replace('<a href="/선생님찾기/">','<a href="/선생님찾기/" aria-current="page">')
    footer=re.search(r'<footer class="site-footer">[\s\S]*?</footer>',base)[0]
    floating=re.search(r'<aside class="floating-actions"[\s\S]*?</aside>',base)[0]
    def head(title,desc,path,items,crumbs):
        canonical=URL(path)
        graph=[{'@type':'WebSite','@id':DOMAIN+'/#website','name':'영수코칭','url':DOMAIN+'/','inLanguage':'ko-KR'},
          {'@type':'CollectionPage','@id':canonical+'#webpage','url':canonical,'name':title+' | 영수코칭','description':desc,'inLanguage':'ko-KR','datePublished':DATE,'dateModified':DATE,'isPartOf':{'@id':DOMAIN+'/#website'},'mainEntity':{'@id':canonical+'#profiles'},'breadcrumb':{'@id':canonical+'#breadcrumb'}},
          {'@type':'ItemList','@id':canonical+'#profiles','numberOfItems':len(items),'itemListElement':[{'@type':'ListItem','position':i,'name':n,'url':URL(p)} for i,(n,p) in enumerate(items,1)]},
          {'@type':'BreadcrumbList','@id':canonical+'#breadcrumb','itemListElement':[{'@type':'ListItem','position':i,'name':n,'item':URL(p)} for i,(n,p) in enumerate(crumbs,1)]}]
        descriptions[path.rstrip('/')]=desc
        return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)} | 영수코칭</title><meta name="description" content="{E(desc)}"><meta name="robots" content="index,follow,max-image-preview:large">
<link rel="canonical" href="{canonical}"><link rel="alternate" type="application/rss+xml" title="영수코칭 학습 소식" href="/rss.xml"><link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/assets/site.css?v=20260920-1"><link rel="stylesheet" href="/assets/teachers.css?v=20261004-1">
<meta property="og:type" content="website"><meta property="og:locale" content="ko_KR"><meta property="og:site_name" content="영수코칭"><meta property="og:title" content="{E(title)} | 영수코칭"><meta property="og:description" content="{E(desc)}"><meta property="og:url" content="{canonical}"><meta property="og:image" content="{DOMAIN}/assets/images/og-share.png"><meta property="og:image:alt" content="영수코칭 영어·수학 학습 안내">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{E(title)} | 영수코칭"><meta name="twitter:description" content="{E(desc)}"><meta name="twitter:image" content="{DOMAIN}/assets/images/og-share.png">
<script type="application/ld+json">{json.dumps({'@context':'https://schema.org','@graph':graph},ensure_ascii=False,separators=(',',':'))}</script>
</head><body class="teacher-page"><a class="skip-link" href="#main">본문 바로가기</a>{header}'''
    def tail(search=False): return footer+floating+'<script src="/assets/site.js" defer></script>'+('<script src="/assets/teachers.js?v=20261004-1" defer></script>' if search else '')+'</body></html>'
    def crumbs(items): return '<nav class="teacher-breadcrumb" aria-label="현재 위치">'+''.join(('<span aria-hidden="true">›</span>' if i else '')+(f'<a href="{E(p)}">{E(n)}</a>' if i<len(items)-1 else f'<span aria-current="page">{E(n)}</span>') for i,(n,p) in enumerate(items))+'</nav>'
    for b in branches:
        items=[(p['name']+' 선생님 소개',b['path']+'#'+p['id']) for p in b['profiles']]
        title=b['name']+' 선생님 소개'
        desc=f'{b["name"]} 선생님의 지도 방향과 소개글을 살펴보고, 학생의 학습 고민과 상담에서 확인할 질문을 준비하세요.'
        assert len(desc)<=80
        trail=[('홈','/'),('선생님찾기',HUB),(b['name'],b['path'])]
        page=head(title,desc,b['path'],items,trail)
        page+=f'<main id="main"><header class="teacher-hero teacher-branch-hero teacher-shell"><div>{crumbs(trail)}<p class="teacher-eyebrow">{E(b["region"] or "선생님 소개")} · 우리 지점의 선생님</p><h1>{E(b["name"])}<br><em>선생님을 소개합니다.</em></h1><p class="teacher-lead">학생의 생각을 어떻게 듣고, 학습의 다음 단계를 어떻게 함께 정하는지 살펴보세요. 각 선생님의 지도 방향과 소개글을 모았습니다.</p><div class="teacher-actions">'
        if b['branchPath']: page+=f'<a class="teacher-action" href="{E(b["branchPath"])}">{E(b["name"])} 수업·방문 안내</a>'
        page+='<a class="teacher-action secondary" href="/상담문의/">상담 준비하기</a></div></div><aside class="teacher-consultation"><h2>소개를 읽으며 확인해 보세요</h2><ul><li>학생이 막힌 부분을 어떤 자료와 질문으로 살펴볼까요?</li><li>수업 뒤에는 무엇을 기록하고 다시 확인할까요?</li><li>희망 과목·학년의 담당 선생님과 가능한 일정은 상담에서 함께 확인하세요.</li></ul></aside></header><section class="teacher-library teacher-shell" aria-labelledby="teacher-profiles-title"><div class="teacher-library-heading"><h2 id="teacher-profiles-title">학생의 공부를 함께 살피는 선생님</h2><p class="teacher-count">선생님 소개 '+str(len(b['profiles']))+'건</p></div><div class="teacher-profile-grid">'
        for p in b['profiles']:
            sentences=re.split(r'(?<=\.)\s+',p['intro'])
            paragraphs=[' '.join(sentences[:3]),' '.join(sentences[3:])]
            page+=f'<article class="teacher-profile" id="{p["id"]}" data-profile="{p["id"]}"><div class="teacher-profile-head"><img class="teacher-photo" src="/assets/teachers/{E(p["photo"])}" alt="{E(b["name"])} {E(p["name"])} 선생님 프로필 이미지" width="{p["photoWidth"]}" height="{p["photoHeight"]}" loading="lazy" decoding="async"><div><p class="teacher-profile-label">{E(b["name"])}</p><h3>{E(p["name"])} 선생님</h3><div class="teacher-tags" aria-label="지도 방향">'+''.join(f'<span>{E(k)}</span>' for k in p['keywords'])+'</div></div></div><div class="teacher-profile-copy">'+''.join(f'<p>{E(t)}</p>' for t in paragraphs if t)+'</div></article>'
        page+='</div><p class="teacher-profile-note">소개글에서 학생을 지도할 때 중점을 두는 내용을 확인하세요. 현재 담당 과목·학년과 수업 일정, 원하는 선생님과의 상담 가능 여부는 지점에 문의해 주세요.</p>'
        if b['branchPath']:
            children=[]
            for file in (root/b['branchPath'].strip('/')).glob('*/index.html'):
                childtext=file.read_text(encoding='utf-8')
                heading=unescape(re.sub('<[^>]*>','',re.search(r'<h1[^>]*>(.*?)</h1>',childtext,re.S)[1]))
                children.append((heading,'/'+file.parent.relative_to(root).as_posix()+'/'))
            page+='<section class="teacher-related"><h2>우리 동네의 학습 안내도 함께 보세요</h2><p>수업·방문 정보와 동네별 학습 고민을 이어서 살펴볼 수 있습니다.</p><nav class="teacher-related-links" aria-label="같은 지점 학습 안내">'+f'<a href="{E(b["branchPath"])}">{E(b["name"])} 전체 안내</a>'+''.join(f'<a href="{E(p)}">{E(n)}</a>' for n,p in sorted(children))+'</nav></section>'
        page+='</section><section class="teacher-bottom teacher-shell"><h2>최근 풀이와 학생의 질문을 함께 가져오세요.</h2><p>좋아하는 설명 방식과 막힌 단원, 혼자 풀어 본 기록을 알려주시면 상담에서 확인할 내용을 구체적으로 정할 수 있습니다.</p><div class="teacher-actions"><a class="teacher-action" href="/학습가이드/first-consultation/">학습 상담 준비 가이드</a><a class="teacher-action secondary" href="/선생님찾기/">다른 지점 선생님 찾기</a></div></section></main>'+tail()
        write(b['path'].strip('/')+'/index.html',page)
    title='선생님찾기'
    desc='지역과 지점별 선생님의 지도 방향과 소개글을 찾아보고, 학생의 학습 고민에 맞는 상담 질문을 준비하세요.'
    trail=[('홈','/'),('선생님찾기',HUB)]
    page=head(title,desc,HUB,[(b['name']+' 선생님 소개',b['path']) for b in branches],trail)
    page+=f'<main id="main"><header class="teacher-hero teacher-shell"><div>{crumbs(trail)}<p class="teacher-eyebrow">MEET OUR TEACHERS</p><h1>학생의 생각을 듣고,<br><em>다음 공부를 함께.</em></h1><p class="teacher-lead">가까운 지점의 선생님을 만나보세요. 지도할 때 중점을 두는 내용과 소개글을 읽고, 학생에게 필요한 도움을 이야기해 보세요.</p><div class="teacher-actions"><a class="teacher-action" href="#teacher-directory">지점별 선생님 찾기</a><a class="teacher-action secondary" href="/학습가이드/first-consultation/">상담 준비 가이드</a></div></div><aside class="teacher-scene"><p>설명 · 질문 · 학습 기록</p><h2>공부하는 과정을<br>차근차근 살펴보는 선생님</h2><div class="teacher-portraits">'+''.join(f'<img src="/assets/teachers/{n}" alt="" width="171" height="280" decoding="async">' for n in ['collage-profile-01.png','collage-profile-08.png','collage-profile-03.png'])+'</div></aside></header>'
    regions=sorted({b['region'] for b in branches if b['region']})
    page+=f'<section id="teacher-directory" class="teacher-library teacher-shell" data-teacher-search aria-labelledby="teacher-directory-title"><div class="teacher-library-heading"><h2 id="teacher-directory-title">어느 지점의 선생님을 찾으세요?</h2><p class="teacher-count" data-teacher-count role="status" aria-live="polite">지점 {len(branches)}개</p></div><form class="teacher-tools" role="search"><label for="teacher-query">지점·이름·지도 키워드<input id="teacher-query" name="q" type="search" maxlength="100" placeholder="예: 명일, 김*, 오답 원인" aria-describedby="teacher-search-help" autocomplete="off"></label><label for="teacher-region">지역<select id="teacher-region" name="region"><option value="">모든 지역</option>'+''.join(f'<option>{E(r)}</option>' for r in regions)+'</select></label><button class="teacher-reset" type="button" data-teacher-reset>초기화</button></form><p id="teacher-search-help" class="teacher-search-help">이름은 안내된 표기 그대로 검색해 주세요. 원하는 담당 과목·학년·시간은 지점 상담에서 확인할 수 있습니다.</p><noscript><p>검색은 자바스크립트가 필요합니다. 아래의 모든 지점 링크에서 소개를 바로 읽을 수 있습니다.</p></noscript><div class="teacher-empty" data-teacher-empty hidden><h3>조건에 맞는 지점이 없습니다.</h3><p>검색어를 줄이거나 지역 조건을 바꿔 보세요.</p><button class="teacher-reset" type="button" data-teacher-reset>전체 지점 보기</button></div><div class="teacher-branch-grid">'
    for b in branches:
        tags=list(dict.fromkeys(k for p in b['profiles'] for k in p['keywords']))
        search=' '.join([b['name'],b['region']]+[p['name'] for p in b['profiles']]+tags)
        page+=f'<article class="teacher-branch-card" data-teacher-card data-region="{E(b["region"])}" data-search="{E(search)}"><p class="teacher-region">{E(b["region"] or "지점별 선생님")}</p><h3><a href="{E(b["path"])}">{E(b["name"])}</a></h3><p class="teacher-card-count">선생님 소개 {len(b["profiles"])}건</p><p class="teacher-card-names">'+E(' · '.join(p['name']+' 선생님' for p in b['profiles']))+'</p><div class="teacher-tags">'+''.join(f'<span>{E(k)}</span>' for k in tags[:3])+f'</div><a class="teacher-link" href="{E(b["path"])}">{E(b["name"])} 선생님 만나기 <span aria-hidden="true">↗</span></a></article>'
    page+='</div></section><section class="teacher-bottom teacher-shell"><h2>소개를 읽고, 학생에게 필요한 도움을 정해 보세요.</h2><p>최근 풀이에서 막힌 지점이나 수업에서 묻고 싶은 질문을 간단히 적어 보세요. 상담에서는 학생의 학교·학년과 희망 과목, 가능한 일정을 함께 확인합니다.</p><a class="teacher-action" href="/상담문의/">상담 준비하기</a></section></main>'+tail(True)
    write('선생님찾기/index.html',page)

    for rel in scope:
        dest=root/rel
        if not dest.exists(): continue
        original=dest.read_bytes().decode('utf-8')
        updated=patch_existing(original,rel,root)
        if '<!-- teacher-directory:start -->' in updated: contexts.append(rel)
        if updated!=original: write(rel,updated)
    # Extend the shared navigation at intermediate widths and on small screens.
    css=(root/'assets/site.css').read_bytes().decode('utf-8')
    marker='/* Teacher directory navigation */'
    if marker not in css:
        css+='\n'+marker+'\n@media (min-width:721px) and (max-width:1160px) { .site-header .header-cta { display:none; } .site-header .header-inner { gap:12px; } .site-header .nav a { padding-inline:11px; } }\n@media (max-width:720px) { .site-header .nav { grid-template-columns:repeat(3,minmax(0,1fr)); } .site-header .nav a { min-height:44px; font-size:13px; padding:7px 0; } }\n'
        write('assets/site.css',css)
    anchor_marker='/* Mobile anchor spacing for the six-item menu */'
    if anchor_marker not in css:
        css+='\n'+anchor_marker+'\n@media (max-width:720px) { .learning-page .guide-body section, .learning-page .guide-group, .branch-page .branch-panel, .branch-page .branch-city-section, .academy-page h2[id] { scroll-margin-top:180px; } }\n'
        write('assets/site.css',css)
    # Keep menus during future branch/subject generation. Other generator logic
    # stays intact; branch body decoration reads only the reviewed teacher map.
    for rel in ['tools/generate_subject_pages.py','tools/generate_branch_pages.py']:
        dest=root/rel
        original=dest.read_bytes().decode('utf-8'); updated=original
        if rel.endswith('generate_subject_pages.py'):
            if 'from teacher_directory_links import decorate_branch_body' not in updated:
                updated=updated.replace('from PIL import Image', 'from PIL import Image\nfrom teacher_directory_links import decorate_branch_body',1)
            if 'page = decorate_branch_body(page,' not in updated:
                needle='                (target / "index.html").write_text(page, encoding="utf-8")'
                replacement='                page = decorate_branch_body(page, f"/과목별학원/{config[\'slug\']}/{slug}/", ROOT)\n                if \'<!-- teacher-directory:start -->\' in page:\n                    page = page.replace(\'</head>\', \'<link rel="stylesheet" href="/assets/teachers.css?v=20261004-1">\\n</head>\', 1)\n'+needle
                updated=updated.replace(needle,replacement,1)
            if '("teachers", "/선생님찾기/", "선생님찾기")' not in updated:
                updated=updated.replace('("guide", "/학습가이드/", "학습가이드"),','("guide", "/학습가이드/", "학습가이드"),\n        ("teachers", "/선생님찾기/", "선생님찾기"),',1)
            if '<a href="/선생님찾기/">선생님찾기</a>' not in updated:
                updated=updated.replace('<a href="/학습가이드/">학습가이드</a>', '<a href="/학습가이드/">학습가이드</a><a href="/선생님찾기/">선생님찾기</a>',1)
        else:
            if 'from teacher_directory_links import decorate_branch_body' not in updated:
                updated=updated.replace('from branch_copy_corrections import apply_branch_copy_corrections','from branch_copy_corrections import apply_branch_copy_corrections\nfrom teacher_directory_links import decorate_branch_body',1)
                updated=updated.replace('def page(title, desc, path, crumbs, body, graph, detail=False):','def page(title, desc, path, crumbs, body, graph, detail=False):\n    body = decorate_branch_body(body, path, ROOT)',1)
                updated=updated.replace('    # Share the exact phone / message / consultation controls used by subject pages.', '    if \'<!-- teacher-directory:start -->\' in body:\n        head = head.replace(\'</head>\', \'<link rel="stylesheet" href="/assets/teachers.css?v=20261004-1">\\n</head>\')\n    # Share the exact phone / message / consultation controls used by subject pages.',1)
        if updated!=original: write(rel,updated)
    sitemap=(root/'sitemap.xml').read_bytes().decode('utf-8'); nl='\r\n' if '\r\n' in sitemap else '\n'
    new=[]
    for path in [HUB]+[b['path'] for b in branches]:
        loc=URL(path)
        if f'<loc>{loc}</loc>' not in sitemap: new.append(f'  <url><loc>{loc}</loc><lastmod>{DATE}</lastmod></url>'+nl)
    def lastmod(match):
        block=match[0]; loc=re.search(r'<loc>(.*?)</loc>',block)[1]
        path=__import__('urllib.parse',fromlist=['unquote']).unquote(loc.removeprefix(DOMAIN))
        if path.strip('/')+'/index.html' in contexts: block=re.sub(r'<lastmod>[^<]*</lastmod>',f'<lastmod>{DATE}</lastmod>',block)
        return block
    sitemap=re.sub(r'<url>[\s\S]*?</url>',lastmod,sitemap).replace('</urlset>',''.join(new)+'</urlset>')
    write('sitemap.xml',sitemap)
    rss=(root/'rss.xml').read_bytes().decode('utf-8'); nl='\r\n' if '\r\n' in rss else '\n'
    loc=URL(HUB)
    if f'<link>{loc}</link>' not in rss:
        entry=f'    <item><title>지점별 선생님 소개</title><link>{loc}</link><guid isPermaLink="true">{loc}</guid><description>{E(desc)}</description><pubDate>Sun, 04 Oct 2026 00:00:00 +0900</pubDate></item>'+nl
        rss=rss.replace('    <item>',entry+'    <item>',1)
    write('rss.xml',rss)
    llms=(root/'llms.txt').read_bytes().decode('utf-8'); nl='\r\n' if '\r\n' in llms else '\n'
    marker='## 지점별 선생님 소개'
    if marker in llms: llms=llms.split(marker)[0].rstrip()+nl
    llms+=nl+marker+nl+nl+'- 선생님찾기: '+URL(HUB)+nl+''.join('- '+b['name']+' 선생님 소개: '+URL(b['path'])+nl for b in branches)
    write('llms.txt',llms)
    mapping=json.loads((root/'seo-descriptions.json').read_text(encoding='utf-8'))
    for path,description in descriptions.items(): mapping['pages'][path]={'description':description,'sources':[description]}
    write('seo-descriptions.json',json.dumps(mapping,ensure_ascii=False,indent=2)+'\n')
    manifest_path=root/'release-public-manifest.json'
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        for name in used+['assets/teachers.css','assets/teachers.js']:
            if name.startswith('tools/') or name == 'seo-descriptions.json': continue
            raw=(root/name).read_bytes(); manifest['files'][name]=hashlib.sha256(raw).hexdigest()
            manifest['textSha256'][name]=hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()
        manifest['sitemapPages']=len(re.findall('<loc>',sitemap)); manifest['teacherBranches']=len(branches); manifest['teacherProfiles']=sum(len(b['profiles']) for b in branches); manifest['updatedAt']=DATE
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {'branches':len(branches),'profiles':sum(len(b['profiles']) for b in branches),'excludedBranches':len(data['branches'])-len(branches),'newPages':len(branches)+1,'contexts':len(contexts),'scopeHtml':len(scope),'changed':changed,'added':added,'contextFiles':contexts,'sitemapPages':len(re.findall('<loc>',sitemap))}

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,default=ROOT); parser.add_argument('--scope',type=Path,required=True); parser.add_argument('--photos',type=Path,required=True); parser.add_argument('--report',type=Path,required=True); args=parser.parse_args()
    scope=json.loads(args.scope.read_text(encoding='utf-8')); scope=[p for p in scope if p.endswith('.html')]
    result=run(args.root.resolve(),scope,args.photos)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if not isinstance(v,list)},ensure_ascii=False))
