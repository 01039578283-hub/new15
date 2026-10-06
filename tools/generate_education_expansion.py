"""Add the reviewed 30 articles while preserving the first 30 and all existing URLs.

Private selection/provenance is supplied with --out, never added to the public manifest.
Run in the reviewed release worktree; --mirror-source applies only verified changes.
"""
from pathlib import Path
from html import escape as E
from urllib.parse import quote,unquote
from concurrent.futures import ThreadPoolExecutor
from PIL import Image,ImageOps
import argparse,json,hashlib,re,shutil,zipfile
import generate_study_resources as G
from education_articles_data import ARTICLES as OLD
from education_expansion_20261006 import ARTICLES
from study_resource_links import decorate_study_page

DATE='2026-10-06'
VERSION='20261006-1'
SOURCES={**G.SOURCES,
 'maths':('EEF · 수학의 이해·문제 해결·진단에 관한 안내','https://educationendowmentfoundation.org.uk/education-evidence/guidance-reports/maths-ks-2-3/'),
 'collaboration':('EEF · 역할과 참여를 갖춘 협력 학습','https://educationendowmentfoundation.org.uk/education-evidence/teaching-learning-toolkit/collaborative-learning-approaches'),
 'suneung':('교육부 · 2027학년도 수능 학습·준비·Q&A 안내자료','https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=294&boardSeq=105763&lev=0&m=020402&s=moe')}
GUIDES=['planner','error-note','procrastination','sentence-structure','performance-task','vacation-plan','feedback-action','choose-materials','first-consultation','exam-plan','reading-evidence','exam-plan','retrieval','exam-plan','learning-question','exam-plan','first-consultation','parent-progress','parent-talk','word-problems','planner','error-note','exam-plan','performance-task','planner','high-transition','math-written','parent-progress','exam-last-week','math-start']
RELATED=[[3,28],[20,30],[21,28],[10,27],[24,27],[21,28],[22,9],[11,16],[7,22],[4,30],[16,27],[23,25],[4,20],[23,28],[13,27],[11,8],[18,19],[17,19],[18,9],[2,30],[25,6],[2,4],[12,29],[5,27],[21,12],[21,28],[4,24],[1,3],[23,30],[2,20]]
ALTS='잠자리에 누워 쉬는 학생|교재를 사이에 두고 설명하는 두 학생|교재와 물컵이 놓인 책상|수학 답안에 표시하는 연필|공책에 펜으로 쓰는 손|하루 점검표를 쓰는 손|책상과 칠판이 있는 빈 교실|교재 앞에 모인 교복 차림 학생들|휴대전화를 보는 아이와 옆에 앉은 보호자|교재 앞에 모인 교복 차림 학생들|공책에 연필로 기록하는 손|교실에서 교재를 읽는 학생들|학습 공간에서 함께 있는 사람들|태블릿으로 글을 읽는 손|교실에서 문제를 푸는 학생|노트북 앞에서 자료를 보는 사람|독서대의 교재를 읽는 학생|독서대와 타이머를 놓고 필기하는 손|독서대와 공책으로 공부하는 학생|메모와 시계가 놓인 책상|공책과 자가 놓인 책상|노트북과 교재를 함께 보는 학생들|책을 펼치고 함께 서 있는 두 학생|태블릿의 영어 학습 화면을 보는 학생|독서대와 공책으로 공부하는 학생|여러 권의 책을 안고 있는 사람|교복 차림으로 함께 서 있는 학생들|교실에서 교재를 읽는 학생들|교재에 필기하는 교복 차림 학생|태블릿과 공책 앞에 앉은 어린이|교재가 놓인 책상에서 공부하는 학생|독서대와 노트북으로 공부하는 학생|교재와 공책에 기록하는 손|교재를 함께 살펴보는 학생과 보호자|도서관에서 책을 읽는 두 학생|여러 메모를 붙여 정리하는 손|수식과 지우개가 놓인 책상|여러 교재와 공책으로 공부하는 학생|책을 머리 위에 올리고 있는 학생|독서대와 노트북으로 공부하는 학생|교복 차림으로 공책에 쓰는 학생|교복 차림으로 함께 서 있는 두 학생|조명과 태블릿이 놓인 책상|칠판 앞에서 자료를 보여 주는 두 학생|교재와 필기구가 놓인 책상|칠판과 책상이 있는 빈 학습 공간|교실에서 교재를 읽는 학생들|교재 앞에서 이야기하는 학생과 보호자|책장이 있는 도서관 내부|펼친 책에 필기하는 학생|영어 자료에 표시한 필기|책상 앞에서 생각하는 학생|공책에 필기하는 교복 차림 학생|수영장 옆에 놓인 수경과 수모|손을 얼굴에 대고 생각하는 학생|선택형 답안에 표시하는 연필|교재와 공책이 놓인 학교 책상|교재를 함께 확인하는 두 학생|교재에 필기하는 교복 차림 학생|칠판과 책상이 있는 빈 학습 공간|독서대의 교재와 공책을 보는 공부 장면|책과 STUDY 글자가 놓인 선반|가방을 메고 이야기하는 두 학생|노트북으로 설명을 듣는 학생|공책에 연필로 기록하는 손|노트북과 교재를 함께 보는 학생들|교복 차림으로 함께 서 있는 두 학생|공책에 연필로 필기하는 손|교재와 공책을 보며 필기하는 학생|교재 앞에서 생각하는 학생|노트북과 태블릿으로 공부하는 학생|노트북과 교재를 함께 보는 학생들|노트북 옆에 학습 메모를 정리하는 손|노트북과 교재를 보며 필기하는 학생|노트북과 교재를 보는 교복 차림 학생|태블릿의 자료를 함께 살펴보는 학생들|가방을 메고 함께 서 있는 두 학생|독서대와 태블릿으로 공부하는 장면|교복 차림으로 책을 든 두 학생|교재에 연필로 표시하는 손|책과 필기구가 놓인 책상|칠판의 영어 문장을 가리키는 학생|노트북과 책이 놓인 책상|한 손을 펼쳐 설명하는 사람|노트북과 교재를 함께 보는 학생들|교실 책상 앞에 앉아 있는 학생들|책 위에 놓인 알람 시계|학습 자료를 들고 함께 보는 두 학생|노트북과 교재를 보며 필기하는 학생|수식과 지우개가 놓인 책상'.split('|')
assert len(ALTS)==90

def digest(raw):return hashlib.sha256(raw).hexdigest()
def norm(raw):return raw.replace(b'\r\n',b'\n')
def save(out,name,obj): (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def run(root,out,mirror=None):
    before=json.loads((out/'baseline-worktree.json').read_text(encoding='utf-8'))
    manifest=json.loads((root/'release-public-manifest.json').read_text(encoding='utf-8'))
    selection=json.loads((out/'selection-reviewed.json').read_text(encoding='utf-8'))
    oldhub=(root/'교육정보/index.html').read_bytes().decode('utf-8')
    oldcards=[c for c in re.findall(r'<article class="edu-card"[\s\S]*?</article>',oldhub) if 'data-edition="20261006"' not in c]
    assert len(oldcards)==30
    assert {x['folder'] for x in selection['selection']}.isdisjoint(selection['oldPublishedFolders'])
    G.ROOT=root;G.DATE=DATE;G.ARTICLES=ARTICLES;G.SOURCES=SOURCES
    G.BRANCHES=json.loads((root/'assets/education/locations.json').read_text(encoding='utf-8'))['branches']
    base=(root/'index.html').read_bytes().decode('utf-8')
    for name,pattern in [('HEADER',r'<header class="site-header">[\s\S]*?</header>'),('FOOTER',r'<footer class="site-footer">[\s\S]*?</footer>'),('FLOATING',r'<aside class="floating-actions"[\s\S]*?</aside>')]:setattr(G,name,re.search(pattern,base)[0])
    images=[];mapping=[]
    def photo(job):
        i,j,src=job;rel=f'assets/education/images/new-20261006-{i+1:02d}-{j+1:02d}.webp'
        p=Path(src['source']);assert digest(p.read_bytes())==src['sha256']
        with Image.open(p) as im:
            im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((1200,1200),Image.Resampling.LANCZOS)
            dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True);im.save(dest,format='WEBP',quality=82,method=6);w,h=im.size
        return dict(path='/'+rel,width=w,height=h,alt=ALTS[i*3+j],source=str(p),sourceSha256=src['sha256'],bytes=dest.stat().st_size)
    jobs=[(i,j,im) for i,x in enumerate(selection['selection']) for j,im in enumerate(x['images'])]
    with ThreadPoolExecutor(max_workers=6) as pool:images=list(pool.map(photo,jobs))
    for i,a in enumerate(ARTICLES):
        src=selection['selection'][i];assert a['index']==src['selectionIndex'];assert digest(Path(src['file']).read_bytes())==src['sha256']
        assert not (a['slug'] in {x['slug'] for x in OLD})
        a['description']=a['intro'].split('. ')[0]+'.';assert len(a['description'])<=80
        a['images']=images[i*3:i*3+3];a['guide']=GUIDES[i]
        assert (root/f'학습가이드/{a["guide"]}/index.html').is_file()
        for key in a['sources']:assert key in SOURCES
        mapping.append(dict(index=i+1,sourceFolder=src['folder'],sourceFile=src['file'],sourceSha256=src['sha256'],title=a['title'],path='/교육정보/'+a['slug']+'/',images=a['images'],sources=[SOURCES[k][1] for k in a['sources']],sectionHeadings=[s[0] for s in a['sections']]))
    original_write=G.write
    allitems=[(a['title'],'/교육정보/'+a['slug']+'/') for a in ARTICLES]+[(a['title'],'/교육정보/'+a['slug']+'/') for a in OLD]
    def rendered_write(rel,text):
        text=text.replace('2026.10.05','2026.10.06').replace('/assets/site.css?v=20261005-1','/assets/site.css?v=20261005-2').replace('/assets/education.css?v=20261004-1','/assets/education.css?v='+VERSION).replace('/assets/education.js?v=20261005-1','/assets/education.js?v='+VERSION)
        if rel=='교육정보/index.html':
            text=text.replace('30개 글','60개 글').replace('30개의 질문','60개의 질문').replace('전체 30개','전체 60개')
            text=text.replace('<article class="edu-card"','<article class="edu-card" data-edition="20261006"').replace('<span class="edu-tags">','<span class="edu-tags"><span class="edu-new-badge">새 글</span> ')
            text=re.sub(r'(<div class="edu-grid">)([\s\S]*?)(</div></section>)',lambda m:m[1]+m[2]+''.join(oldcards)+m[3],text,count=1)
            text=text.replace('<div class="edu-library-heading">','<span id="new-articles" class="edu-new-anchor" aria-hidden="true"></span><div class="edu-library-heading">',1)
            text=text.replace('<div class="edu-category" role="group" aria-label="주제 선택">','<div class="edu-category" role="group" aria-label="주제 선택"><button type="button" data-new-only aria-pressed="false">새로 추가된 30편</button>',1)
            aside='<aside class="edu-hero-aside"><h2>새로 추가한 질문부터</h2>'+''.join(f'<a href="{E(p)}">{E(t)} →</a>' for t,p in [allitems[4],allitems[26],allitems[18]])+'<a href="#new-articles">새로 추가된 30편 보기 →</a></aside>'
            text=re.sub(r'<aside class="edu-hero-aside">[\s\S]*?</aside>',lambda _:aside,text,count=1)
            def collection(m):
                data=json.loads(m[1]); graph=data['@graph'];node=next(n for n in graph if n['@type']=='CollectionPage');node['description']=node['description'].replace('30개 글','60개 글');node['mainEntity']={'@id':G.URL('/교육정보/')+'#articles'}
                graph.append({'@type':'ItemList','@id':G.URL('/교육정보/')+'#articles','name':'학생·학부모 교육정보 전체 60편','numberOfItems':60,'itemListElement':[{'@type':'ListItem','position':i+1,'item':{'@type':'Article','name':t,'url':G.URL(p)}} for i,(t,p) in enumerate(allitems)]})
                return '<script type="application/ld+json">'+json.dumps(data,ensure_ascii=False,separators=(',',':'))+'</script>'
            text=re.sub(r'<script type="application/ld\+json">([\s\S]*?)</script>',collection,text,count=1)
            G.DESCRIPTIONS['/교육정보']=G.DESCRIPTIONS['/교육정보'].replace('30개 글','60개 글')
        else:
            a=next(x for x in ARTICLES if rel=='교육정보/'+x['slug']+'/index.html');related=[ARTICLES[i-1] for i in RELATED[a['index']-1]]
            section='<section class="edu-related"><h2>이 질문과 함께 읽어 보세요</h2>'+''.join(f'<a href="/교육정보/{E(b["slug"])}/">{E(b["title"])} →</a>' for b in related)+f'<a href="/학습가이드/{a["guide"]}/">실천과 기록을 위한 학습가이드 →</a><a href="/학습커리큘럼/">학년·과목별 학습 중점 확인 →</a><a href="/교육정보/">교육정보 전체 보기 →</a></section>'
            text=re.sub(r'<section class="edu-related">[\s\S]*?</section>',lambda _:section,text,count=1)
        original_write(rel,text)
    G.write=rendered_write
    try:G.education()
    finally:G.write=original_write
    css=root/'assets/education.css';raw=css.read_bytes().decode('utf-8');marker='/* Education additions 2026-10-06 */'
    if marker not in raw:original_write('assets/education.css',raw+'\n'+marker+'\n.edu-new-badge { display:inline-block; padding:2px 7px; margin-right:5px; border-radius:5px; background:#e5f2ed; color:#14665e; font-size:11px; line-height:1.7; }\n.edu-category button[data-new-only][aria-pressed="true"] { background:#28525f; border-color:#28525f; color:#fff; }\n.edu-new-anchor { display:block; scroll-margin-top:170px; }\n')
    raw=css.read_text(encoding='utf-8')
    if '.edu-card h3 a { display:block; }' not in raw:original_write('assets/education.css',raw+'\n.edu-card h3 a { display:block; }\n')
    contexts=[];context_hashes={}
    context_scope=[rel for rel in manifest['files'] if rel=='index.html' or (rel.endswith('/index.html') and rel.startswith(('지점안내/','과목별학원/')))]
    def patch_context(rel):
            beforetext=(root/rel).read_bytes().decode('utf-8');path=G.path_of(rel);after=decorate_study_page(beforetext,path)
            if rel=='index.html':
                after=after.replace('30개 교육정보','60개 교육정보')
                after=after.replace('<a href="/교육정보/">교육정보 전체 보기 →</a>','<a href="/교육정보/#new-articles">새로 추가된 교육정보 30편 보기 →</a>',1)
            after=re.sub(r'("dateModified"\s*:\s*")[^"]+(")',lambda m:m[1]+DATE+m[2],after)
            if after!=beforetext:original_write(rel,after)
            raw=after.encode('utf-8');return rel,digest(raw),digest(norm(raw))
    with ThreadPoolExecutor(max_workers=12) as pool:
        for iteration,(rel,raw_hash,normalized_hash) in enumerate(pool.map(patch_context,context_scope)):
            context_hashes[rel]=(raw_hash,normalized_hash)
            if normalized_hash!=before['normalized'][rel]:contexts.append(rel)
            if iteration%2000==0:print('Context progress',iteration,flush=True)
    hp=root/'tools/generate_home_learning.py';raw=hp.read_bytes().decode('utf-8').replace("'30개 교육정보'","'60개 교육정보'");hp.write_bytes(raw.encode('utf-8'))
    newpaths=['/교육정보/'+a['slug']+'/' for a in ARTICLES]
    changed_html=set(contexts)|{'교육정보/index.html'}
    sitemap=(root/'sitemap.xml').read_bytes().decode('utf-8');oldlocs=re.findall(r'<loc>(.*?)</loc>',sitemap);nl='\r\n' if '\r\n' in sitemap else '\n'
    changed_paths={G.path_of(p) for p in changed_html}
    def update(m):
        block=m[0];loc=re.search(r'<loc>(.*?)</loc>',block)[1]
        return re.sub(r'<lastmod>[^<]*</lastmod>',f'<lastmod>{DATE}</lastmod>',block) if unquote(loc.removeprefix(G.DOMAIN)) in changed_paths else block
    sitemap=re.sub(r'<url>[\s\S]*?</url>',update,sitemap)
    additions=''.join(f'  <url><loc>{G.URL(p)}</loc><lastmod>{DATE}</lastmod></url>{nl}' for p in newpaths if G.URL(p) not in oldlocs)
    original_write('sitemap.xml',sitemap.replace('</urlset>',additions+'</urlset>'))
    rss=(root/'rss.xml').read_bytes().decode('utf-8');rss=re.sub(r'<lastBuildDate>[^<]*</lastBuildDate>','<lastBuildDate>Tue, 06 Oct 2026 00:00:00 +0900</lastBuildDate>',rss);nl='\r\n' if '\r\n' in rss else '\n'
    items=''.join(f'    <item><title>{E(a["title"])}</title><link>{G.URL(p)}</link><guid isPermaLink="true">{G.URL(p)}</guid><description>{E(a["description"])}</description><pubDate>Tue, 06 Oct 2026 00:00:00 +0900</pubDate></item>{nl}' for a,p in zip(ARTICLES,newpaths) if '<link>'+G.URL(p)+'</link>' not in rss)
    if items:original_write('rss.xml',rss.replace('    <item>',items+'    <item>',1))
    llms=(root/'llms.txt').read_bytes().decode('utf-8');marker='## 교육정보 추가 글 · 2026-10-06'
    if marker in llms:llms=llms.split(marker)[0].rstrip()+'\n'
    original_write('llms.txt',llms+'\n'+marker+'\n\n'+''.join('- '+a['title']+': '+G.URL(p)+'\n' for a,p in zip(ARTICLES,newpaths)))
    descriptions=json.loads((root/'seo-descriptions.json').read_text(encoding='utf-8'))
    for p,d in G.DESCRIPTIONS.items():descriptions['pages'][p]={'description':d,'sources':[d]}
    (root/'seo-descriptions.json').write_text(json.dumps(descriptions,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for rel,(raw_hash,normalized_hash) in context_hashes.items():manifest['files'][rel]=raw_hash;manifest['textSha256'][rel]=normalized_hash
    for rel in set(G.WRITTEN)|{'assets/education.js','assets/education.css','교육정보/index.html','sitemap.xml','rss.xml','llms.txt'}|{p.strip('/')+'/index.html' for p in newpaths}|{x['path'].lstrip('/') for x in images}:
        if rel.startswith('tools/') or rel=='seo-descriptions.json':continue
        raw=(root/rel).read_bytes();manifest['files'][rel]=digest(raw);manifest['textSha256'][rel]=digest(norm(raw))
    manifest.update(updatedAt=DATE,sitemapPages=len(re.findall('<loc>',sitemap))+len(re.findall('<loc>',additions)),educationArticles=60,educationAdditionDate=DATE,educationAdditionArticles=30)
    (root/'release-public-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    actual_changed=[rel for rel,d in manifest['files'].items() if before['files'].get(rel)!=d]
    data=dict(date=DATE,seed=selection['seed'],existingArticles=30,addedArticles=30,totalArticles=60,newImages=90,newPages=newpaths,hub='/교육정보/',sourceMapping=mapping,contextPages=contexts,changedPublicFiles=actual_changed,manifestFiles=len(manifest['files']),sitemapUrls=manifest['sitemapPages'])
    save(out,'generation.json',data)
    private=root/'tools/data/education/expansion-20261006.json';private.parent.mkdir(parents=True,exist_ok=True);private.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if mirror:
        baseline=json.loads((out/'baseline-source.json').read_text(encoding='utf-8'))
        def mirror_one(rel):
            dest=mirror/rel
            raw=(root/rel).read_bytes()
            old=dest.read_bytes() if dest.exists() else None
            if old is not None:
                assert digest(old)==baseline['files'].get(rel) or norm(old)==norm(raw),('Source changed since baseline or path collision',rel)
                if norm(old)==norm(raw):return
                if rel.endswith('.html'):raw=norm(raw).replace(b'\n',b'\r\n') if b'\r\n' in old else norm(raw)
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(raw)
        with ThreadPoolExecutor(max_workers=12) as pool:
            for iteration,_ in enumerate(pool.map(mirror_one,actual_changed)):
                if iteration%2000==0:print('Source mirror progress',iteration,flush=True)
        for rel in ['seo-descriptions.json','tools/education_expansion_20261006.py','tools/generate_education_expansion.py','tools/audit_education_expansion.py','tools/study_resource_links.py','tools/generate_home_learning.py','tools/data/education/expansion-20261006.json']:
            dest=mirror/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/rel,dest)
    print(json.dumps({k:v for k,v in data.items() if not isinstance(v,list)},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,required=True);p.add_argument('--mirror-source',type=Path);a=p.parse_args();run(a.root.resolve(),a.out.resolve(),a.mirror_source.resolve() if a.mirror_source else None)
