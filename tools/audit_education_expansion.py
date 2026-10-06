"""Whole-public-site links plus bounded preservation and every new article's content."""
from pathlib import Path
from html import unescape
from urllib.parse import urlsplit,urljoin,unquote,quote
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import argparse,json,re,hashlib,zipfile,difflib,xml.etree.ElementTree as ET
from education_expansion_20261006 import ARTICLES
from education_articles_data import ARTICLES as OLD
from study_resource_links import decorate_study_page

DOMAIN='https://xn--9p4bn5e3wjn0a.com'
DATE='2026-10-06'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def norm(raw):return raw.replace(b'\r\n',b'\n')
def visible(text):return unescape(re.sub('<[^>]+>',' ',text))

def run(root,out,label,public=False):
    errors=[];counts={};refs=0;ids={};new_paths=[]
    def check(ok,issue):
        if not ok:errors.append(issue)
    generation=json.loads((out/'generation.json').read_text(encoding='utf-8'))
    manifest=json.loads((Path(__file__).resolve().parents[1]/'release-public-manifest.json').read_text(encoding='utf-8'))
    selected=set(manifest['files']);baseline=json.loads((out/('baseline-'+label+'.json')).read_text(encoding='utf-8'))
    check(len(selected)==9860,{'manifest-count':len(selected)})
    check(not any(p.startswith(('tools/','reports/','.env','.vercel','AGENTS','tmp/','node_modules/')) for p in selected),'Private manifest path')
    def read_file(rel):return rel,(root/rel).read_bytes()
    with ThreadPoolExecutor(max_workers=12) as pool:contents=dict(pool.map(read_file,sorted(selected)))
    print('Read all public files',len(contents),flush=True)
    def target_ids(rel):
        if rel not in ids:
            ids[rel]=set(re.findall(r'\bid=["\']([^"\']+)',contents[rel].decode('utf-8')))
        return ids[rel]
    def resolve(ref,rel):
        nonlocal refs
        uri=urlsplit(urljoin(DOMAIN+'/'+quote(rel,safe='/'),unescape(ref)))
        if uri.netloc not in [urlsplit(DOMAIN).netloc,'영수코칭.com'] or uri.scheme not in ['http','https']:return
        refs+=1;p=unquote(uri.path).lstrip('/');target=p+'index.html' if uri.path.endswith('/') else p
        if target not in selected and target+'.html' in selected:target+='.html'
        if target not in selected:errors.append({'missing-target':target,'source':rel,'href':ref});return
        if uri.fragment and target.endswith('.html'):check(unquote(uri.fragment) in target_ids(target),{'missing-fragment':uri.fragment,'source':rel,'target':target})
    htmls=[p for p in selected if p.endswith('.html')]
    for iteration,rel in enumerate(sorted(htmls)):
        text=contents[rel].decode('utf-8')
        if not rel.startswith('google'):
            check(len(re.findall(r'<h1\b',text))==1,{'h1':rel})
            if rel!='404.html':
                expected=DOMAIN+'/'+quote(rel.removesuffix('index.html'),safe='/')
                canonical=re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"',text)
                check(bool(canonical) and canonical[1]==expected,{'canonical':rel})
        for tag in re.findall(r'<(?:a|img|script|link)\b[^>]*>',text):
            if tag.startswith('<link') and not any(x in tag for x in ['rel="stylesheet"','rel="alternate"']):continue
            for ref in re.findall(r'\b(?:href|src)=["\']([^"\']+)',tag):resolve(ref,rel)
        check('\ufffd' not in text,{'replacement-character':rel})
        if iteration%2000==0:print('Link audit',iteration,rel,flush=True)
    counts.update(htmlPages=len(htmls),internalReferences=refs)
    for family,count in [('교육정보',61),('학습가이드',41),('선생님찾기',193),('학습커리큘럼',84)]:
        actual=len([p for p in selected if p.startswith(family+'/') and p.endswith('/index.html')]);counts[family]=actual;check(actual==count,{'family-count':family,'actual':actual})
    hub=(root/'교육정보/index.html').read_text(encoding='utf-8')
    check(hub.count('data-edu-card')==60,'Hub must contain all 60 cards')
    check(hub.count('data-edition="20261006"')==30,'Hub must identify exactly 30 new cards')
    check('data-new-only' in hub and 'id="new-articles"' in hub,'New-article filter/anchor missing')
    hubgraph=json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',hub,re.S)[1])['@graph']
    itemlist=next(n for n in hubgraph if n['@type']=='ItemList')
    check(itemlist['numberOfItems']==60 and len(itemlist['itemListElement'])==60,'Hub ItemList count')
    check(len({x['item']['url'] for x in itemlist['itemListElement']})==60,'Hub ItemList duplicate')
    before_zip=out/(label+'-before.zip')
    if not public:
        allowed=set(generation['contextPages'])|{'index.html','교육정보/index.html','sitemap.xml','rss.xml','llms.txt','assets/education.css','assets/education.js'}
        with zipfile.ZipFile(before_zip) as z:
            for rel,oldsha in baseline['files'].items():
                raw=contents[rel]
                if rel not in allowed:check(sha(raw)==oldsha,{'unexpected-old-change':rel});continue
                if rel in generation['contextPages']:
                    old=z.read(rel).decode('utf-8');expected=decorate_study_page(old,'/'+rel.removesuffix('index.html'))
                    if rel=='index.html':expected=expected.replace('30개 교육정보','60개 교육정보').replace('<a href="/교육정보/">교육정보 전체 보기 →</a>','<a href="/교육정보/#new-articles">새로 추가된 교육정보 30편 보기 →</a>',1)
                    expected=re.sub(r'("dateModified"\s*:\s*")[^"]+(")',lambda m:m[1]+DATE+m[2],expected)
                    check(norm(raw)==norm(expected.encode('utf-8')),{'changed-outside-context':rel})
            for a in OLD:
                rel='교육정보/'+a['slug']+'/index.html';check((root/rel).read_bytes()==z.read(rel),{'old-article-changed':rel})
            oldurls=ET.fromstring(z.read('sitemap.xml'));oldentries={n.findtext('{*}loc'):n for n in oldurls}
            current=ET.parse(root/'sitemap.xml').getroot();entries={n.findtext('{*}loc'):n for n in current}
            check(set(oldentries).issubset(entries),'Existing URL removed or renamed')
            changed_uri={DOMAIN+'/'+quote(p.removesuffix('index.html'),safe='/') for p in generation['contextPages']+['교육정보/index.html']}
            for uri,entry in oldentries.items():
                actual=entries[uri];wanted=DATE if uri in changed_uri else entry.findtext('{*}lastmod')
                check(actual.findtext('{*}lastmod')==wanted,{'sitemap-lastmod':uri})
            check(set(entries)-set(oldentries)=={DOMAIN+quote(p,safe='/') for p in generation['newPages']},'New URL scope must be exactly 30')
            oldrss=ET.fromstring(z.read('rss.xml'));rss=ET.parse(root/'rss.xml').getroot()
            olditems={x.findtext('guid'):x for x in oldrss.findall('./channel/item')};newitems={x.findtext('guid'):x for x in rss.findall('./channel/item')}
            check(set(olditems).issubset(newitems),'Old RSS item missing')
            for key,node in olditems.items():check(ET.tostring(node)==ET.tostring(newitems[key]),{'old-rss-change':key})
            check((root/'llms.txt').read_bytes().startswith(z.read('llms.txt')),'Old llms information changed')
        oldrules=json.loads((out/'private-before'/label/'seo-descriptions.json').read_text(encoding='utf-8'));rules=json.loads((root/'seo-descriptions.json').read_text(encoding='utf-8'))
        oldrules['pages']['/교육정보']=rules['pages']['/교육정보']
        for path in generation['newPages']:rules['pages'].pop(path.rstrip('/'))
        check(oldrules==rules,'Unrelated description rules changed')
    source_selection=json.loads((out/'selection-reviewed.json').read_text(encoding='utf-8'));used=set(source_selection['oldPublishedFolders']);newfolders={x['sourceFolder'] for x in generation['sourceMapping']}
    check(len(newfolders)==30 and used.isdisjoint(newfolders),'Source folder duplicates')
    imagehashes=[];source_imagehashes=[];textchecks=[]
    for i,a in enumerate(ARTICLES):
        path='/교육정보/'+a['slug']+'/';rel=path.strip('/')+'/index.html';new_paths.append(rel);text=(root/rel).read_text(encoding='utf-8');mapping=generation['sourceMapping'][i]
        desc=a['intro'].split('. ')[0]+'.'
        check(0<len(desc)<=80 and desc.endswith('.'),{'description-length':rel})
        for pattern in [r'<meta name="description" content="([^"]*)"',r'<meta property="og:description" content="([^"]*)"',r'<meta name="twitter:description" content="([^"]*)"']:
            match=re.search(pattern,text);check(bool(match) and unescape(match[1])==desc,{'description-mismatch':rel})
        graph=json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',text,re.S)[1])['@graph'];article=next(n for n in graph if n['@type']=='Article');web=next(n for n in graph if n['@type']=='WebPage');faq=next(n for n in graph if n['@type']=='FAQPage')
        check(article['headline']==a['title'] and article['description']==desc and web['description']==desc,{'schema-content':rel})
        check(article['datePublished']==DATE and article['dateModified']==DATE,{'article-date':rel})
        check(article['citation']==mapping['sources'],{'sources':rel})
        summaries=[unescape(visible(q)).strip() for q in re.findall(r'<summary>(.*?)</summary>',text,re.S)]
        check(summaries==[q['name'] for q in faq['mainEntity']],{'faq-visible':rel})
        for q in faq['mainEntity']:check(q['acceptedAnswer']['text'] in unescape(text),{'faq-answer':rel})
        check(text.count('<figure class="edu-figure">')==3,{'photos-between-sections':rel})
        check(len(re.findall('data-local-picker',text))==1 and 'data-branch-link' in text and 'data-local-link' in text,{'local-links':rel})
        allids=re.findall(r'\bid="([^"]+)"',text);check(len(allids)==len(set(allids)),{'duplicate-ids':rel})
        check(not any(x in text for x in ['편집 원칙','편집원칙','C:\\Users','원고.txt','확실한 성적 향상','성적을 보장']),'Private/editorial or guarantee text '+rel)
        rawbody=' '.join([a['intro'],*[' '.join(s) for s in a['sections']],a['example'],a['parent'],*[' '.join(q) for q in a['faq']]])
        source=Path(mapping['sourceFile']).read_bytes();check(sha(source)==mapping['sourceSha256'],{'changed-source':rel})
        original=source.decode(source_selection['selection'][i]['encoding']);longest=max((b.size for b in difflib.SequenceMatcher(None,re.sub(r'\s+',' ',original),rawbody,autojunk=False).get_matching_blocks()),default=0)
        check(len(rawbody)>=1100 and longest<100,{'rewriting-length-or-copy':rel,'characters':len(rawbody),'longestSourceCopy':longest})
        textchecks.append({'path':path,'bodyCharacters':len(rawbody),'longestSourceCopy':longest})
        for im in mapping['images']:
            p=root/im['path'].lstrip('/');raw=p.read_bytes();imagehashes.append(sha(raw));source_imagehashes.append(im['sourceSha256'])
            with Image.open(p) as image:check(image.size==(im['width'],im['height']),{'image-size':str(p)})
            check(im['alt'] in text and im['width']<=1200 and im['height']<=1200,{'image-alt-or-limit':str(p)})
    check(len(set(imagehashes))==90 and len(set(source_imagehashes))==90,'New image duplicates')
    check(len(re.findall('<loc>',(root/'sitemap.xml').read_text(encoding='utf-8')))==8760,'Sitemap URL count')
    locations=json.loads((root/'assets/education/locations.json').read_text(encoding='utf-8'))
    for p,b in locations['branches'].items():resolve(p,'교육정보/index.html');[resolve(l['path'],'교육정보/index.html') for l in b['locals']]
    for p,b in locations['subjects'].items():resolve(p,'교육정보/index.html');check(b in locations['branches'],{'unknown-branch-context':p})
    baseline_locations=json.loads(zipfile.ZipFile(out/'worktree-before.zip').read('assets/education/locations.json'))
    branch_pages={'/'+p.removesuffix('index.html') for p in selected if p.startswith('지점안내/') and p.count('/')==3 and p.endswith('/index.html')}
    check(locations==baseline_locations,'Existing branch selection data changed')
    check(set(locations['branches'])==branch_pages,'Branch selector must match every existing branch page')
    if not public:
        for rel,expected in manifest['files'].items():
            raw=contents[rel];check(sha(raw)==expected or sha(norm(raw))==manifest['textSha256'].get(rel),{'manifest-hash':rel})
    counts.update(newArticles=30,newImages=90,oldArticlesPreserved=30,contextPages=len(generation['contextPages']),branches=len(branch_pages),sitemapUrls=8760,publicFiles=len(selected),internalReferences=refs)
    result={'label':label,'publicBuild':public,'counts':counts,'errors':errors,'passed':not errors,'textChecks':textchecks}
    (out/('audit-'+label+('-public' if public else '')+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['textChecks','errors']},ensure_ascii=False));print('Errors',len(errors),json.dumps(errors[:20],ensure_ascii=False));return bool(errors)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,required=True);p.add_argument('--label',choices=['worktree','source'],default='worktree');p.add_argument('--public',action='store_true');a=p.parse_args();raise SystemExit(run(a.root.resolve(),a.out.resolve(),a.label,a.public))
