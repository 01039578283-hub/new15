"""Audit preserved pages, concrete link destinations and visible structured content."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin,unquote
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import argparse,hashlib,json,re,zipfile,xml.etree.ElementTree as ET
from generate_home_learning import cache_bust,DESCRIPTION,DOMAIN,HUBS,TOPICS,SITE_VERSION

class Page(HTMLParser):
    def __init__(self,text):
        super().__init__();self.nodes=[];self.feed(text)
    def handle_starttag(self,tag,attrs):self.nodes.append((tag,dict(attrs)))
    def attrs(self,tag):return [a for t,a in self.nodes if t==tag]

def run(root,out,label,public=False):
    errors=[];counts={};cache={}
    def check(ok,msg):
        if not ok:errors.append(msg)
    def read(rel):
        if rel not in cache:cache[rel]=(root/rel).read_bytes().decode('utf-8')
        return cache[rel]
    home=read('index.html');page=Page(home)
    with zipfile.ZipFile(out/(label+'-public-before.zip')) as z:
        oldhome=z.read('index.html').decode('utf-8')
        if not public:
            def preserved(rel):
                if rel in ['index.html','sitemap.xml','llms.txt']:return True
                before=z.read(rel);actual=(root/rel).read_bytes()
                expected=cache_bust(before.decode('utf-8')).encode('utf-8') if rel.endswith('.html') else before
                if rel=='rss.xml':expected=before.replace(b'\r\r\n',b'\r\n')
                return actual==expected
            with ThreadPoolExecutor(max_workers=12) as pool:
                results=list(pool.map(preserved,z.namelist()))
            failed=[p for p,ok in zip(z.namelist(),results) if not ok]
            check(not failed,'Unexpected old public changes: '+repr(failed[:10]));counts['preservedPublicFiles']=len(results)-3
        for tag in ['h1','title','header','footer']:
            pattern=r'<'+tag+r'\b[\s\S]*?</'+tag+'>'
            check(re.findall(pattern,home)==re.findall(pattern,oldhome),'Original '+tag+' changed')
        for cls,expected_count in [('subject-card',2),('process-item',5),('bento-card',5)]:
            pattern=r'<article class="'+cls+r'[^"\n]*"[\s\S]*?</article>'
            check(len(re.findall(pattern,oldhome))==expected_count,'Original section count '+cls)
            check(re.findall(pattern,home)==re.findall(pattern,oldhome),'Original '+cls+' changed')
        for img in Page(oldhome).attrs('img'):check(img in page.attrs('img'),'Original image changed')
        check(re.findall(r'href="tel:[^"]+"',home)==re.findall(r'href="tel:[^"]+"',oldhome),'Contact links changed')
        oldsitemap=z.read('sitemap.xml').decode('utf-8')
        expected=re.sub(r'(<url>\s*<loc>https://xn--9p4bn5e3wjn0a\.com/</loc>\s*<lastmod>)[^<]+',lambda m:m[1]+'2026-10-05',oldsitemap,count=1)
        check((root/'sitemap.xml').read_bytes().decode('utf-8').replace('\r\n','\n')==expected.replace('\r\n','\n'),'Unrelated sitemap entries changed')
        check((root/'llms.txt').read_bytes().startswith(z.read('llms.txt')),'Original llms content changed')
    check(len(page.attrs('h1'))==1,'H1 count')
    ids=[a['id'] for _,a in page.nodes if 'id' in a];check(len(ids)==len(set(ids)),'Duplicate IDs')
    for name in ['hub','compare','system','exam','planner']:
        check(home.count('<!-- home-learning:'+name+':start -->')==1,'Missing/duplicate section '+name)
    for title,question,copy,path,count in HUBS:check('href="'+path+'"' in home,'Missing hub '+title)
    for title,path in TOPICS:check('href="'+path+'"' in home,'Missing topic '+title)
    counts['comparisonRows']=len(re.findall(r'<tr><th scope="row">',home));check(counts['comparisonRows']==8,'Comparison rows')
    desc=next((a.get('content') for a in page.attrs('meta') if a.get('name')=='description'),None)
    check(desc==DESCRIPTION and len(desc)<=80 and desc.endswith('.'),'Home description')
    for key in ['og:description','twitter:description']:
        check(any(a.get('property',a.get('name'))==key and a.get('content')==desc for a in page.attrs('meta')),'Social description '+key)
    graph=json.loads(re.search(r'<script type="application/ld\+json">([\s\S]*?)</script>',home).group(1))['@graph']
    check(next(n for n in graph if n.get('@type')=='WebPage')['description']==desc,'WebPage description')
    faq=next(n for n in graph if n.get('@type')=='FAQPage')['mainEntity']
    visible=[re.sub('<[^>]+>','',v) for v in re.findall(r'<summary>([\s\S]*?)</summary>',home)]
    check([q['name'] for q in faq]==visible,'FAQ schema/questions mismatch');check(len(visible)==8,'FAQ count')
    for q in faq:check(q['acceptedAnswer']['text'] in home,'FAQ answer not visible: '+q['name'])
    items=next(n for n in graph if n.get('@type')=='ItemList')
    check(items['numberOfItems']==6 and len(items['itemListElement'])==6,'Hub ItemList')
    for item in items['itemListElement']:
        check('href="'+unquote(urlsplit(item['item']['url']).path)+'"' in home,'ItemList link not visible')
    refs=[]
    for tag,attrs in page.nodes:
        if tag not in ['a','img','script','link']:continue
        ref=attrs.get('href',attrs.get('src',''))
        if tag=='link' and attrs.get('rel') not in ['stylesheet','canonical']:continue
        target=urlsplit(urljoin(DOMAIN+'/',ref))
        if target.netloc!=urlsplit(DOMAIN).netloc:continue
        path=unquote(target.path).lstrip('/');rel=path+'index.html' if target.path.endswith('/') else path
        check((root/rel).is_file(),'Missing local home target: '+ref)
        if target.fragment and (root/rel).is_file():
            check(any(a.get('id')==unquote(target.fragment) for _,a in Page(read(rel)).nodes),'Missing home fragment: '+ref)
        refs.append(ref)
    counts['homeLocalReferences']=len(refs)
    check(not any(x in home for x in ['\ufffd','편집 원칙','editorial-policy']),'Public content unwanted text')
    check(len(page.attrs('img'))==5,'Home photo count')
    for image in page.attrs('img'):
        check(bool(image.get('alt')),'Missing image alt')
        path=root/unquote(urlsplit(image['src']).path).lstrip('/')
        with Image.open(path) as actual:
            check(actual.size==(int(image['width']),int(image['height'])),'Image dimensions: '+str(path))
    for family,expected in [('학습가이드',41),('선생님찾기',193),('교육정보',31),('학습커리큘럼',84)]:
        pages=list((root/family).rglob('index.html'));counts[family]=len(pages);check(len(pages)==expected,'Family count '+family)
    sitemap=ET.parse(root/'sitemap.xml');ns={'s':'http://www.sitemaps.org/schemas/sitemap/0.9'}
    urls=sitemap.findall('s:url',ns);counts['sitemapUrls']=len(urls);check(len(urls)==8730,'Sitemap count')
    for entry in urls:
        if entry.findtext('s:loc',namespaces=ns)==DOMAIN+'/':check(entry.findtext('s:lastmod',namespaces=ns)=='2026-10-05','Home lastmod')
    if not public:
        before=out/(label+'-before.zip')
        with zipfile.ZipFile(before) as z:
            old=json.loads(z.read('seo-descriptions.json'));new=json.loads((root/'seo-descriptions.json').read_text(encoding='utf-8'))
            old['pages']['/']=new['pages']['/'];check(old==new,'Unrelated description rules changed')
            check(new['pages']['/']['description']==desc,'Home description rule mismatch')
        if (root/'release-public-manifest.json').exists():
            manifest=json.loads((root/'release-public-manifest.json').read_text(encoding='utf-8'));counts['publicFiles']=len(manifest['files'])
            check(len(manifest['files'])==9740,'Public manifest count')
            check(not any(p.startswith(('tools/','reports/','.env','.vercel','AGENTS')) for p in manifest['files']),'Private manifest leak')
    result={'root':str(root),'publicBuild':public,'counts':counts,'errors':errors,'passed':not errors}
    (out/('audit-home-'+label+('-public' if public else '')+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));return bool(errors)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,required=True);p.add_argument('--label',choices=['source','worktree'],default='worktree');p.add_argument('--public',action='store_true');a=p.parse_args();raise SystemExit(run(a.root,a.out,a.label,a.public))
