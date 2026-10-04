from pathlib import Path
from html.parser import HTMLParser
from html import unescape, escape
from urllib.parse import unquote, urlsplit, urljoin, quote
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import argparse, hashlib, json, re, sys, zipfile, xml.etree.ElementTree as ET
from generate_teacher_directory import patch_existing

parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]); parser.add_argument('--data-root',type=Path); parser.add_argument('--baseline',type=Path); parser.add_argument('--report',type=Path,required=True); args=parser.parse_args()
root=args.root.resolve(); data_root=(args.data_root or args.root).resolve()
data=json.loads((data_root/'tools/data/teachers/directory.json').read_text(encoding='utf-8'))
branches=[b for b in data['branches'] if b['included']]; errors=[]
manifest_path=data_root/'release-public-manifest.json'
manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else None
if not manifest: raise ValueError('Supply --data-root with the reviewed public manifest')
def read_item(rel): return (root/rel,(root/rel).read_bytes())
with ThreadPoolExecutor(max_workers=12) as pool: raw_cache=dict(pool.map(read_item,manifest['files']))
def raw_bytes(path): return raw_cache[path] if path in raw_cache else path.read_bytes()
def html_text(path): return raw_bytes(path).decode('utf-8')
def check(ok,message):
    if not ok: errors.append(message)
class HTML(HTMLParser):
    def __init__(self,text): super().__init__(); self.nodes=[]; self.feed(text)
    def handle_starttag(self,tag,attrs): self.nodes.append((tag,dict(attrs)))
    def attrs(self,tag): return [a for t,a in self.nodes if t==tag]
    def meta(self,name): return [a.get('content') for a in self.attrs('meta') if a.get('name',a.get('property'))==name]
domain='https://xn--9p4bn5e3wjn0a.com'
E=escape
pages=['선생님찾기/index.html']+[b['path'].strip('/')+'/index.html' for b in branches]
descriptions=[]; links=0; ids_cache={}; profiles=0
for rel in pages:
    path=root/rel
    if not path.is_file(): check(False,'Missing page '+rel); continue
    text=html_text(path); doc=HTML(text)
    check(len(doc.attrs('h1'))==1,rel+': h1')
    check('\ufffd' not in text,rel+': replacement character')
    ids=[a['id'] for _,a in doc.nodes if 'id' in a]
    check(len(ids)==len(set(ids)),rel+': duplicate anchor')
    canonical=next(a['href'] for a in doc.attrs('link') if a.get('rel')=='canonical')
    expected=domain+'/'+quote(str(path.parent.relative_to(root)).replace('\\','/')+'/',safe='/')
    check(canonical==expected,rel+': canonical')
    desc=doc.meta('description'); check(len(desc)==1 and 0<len(desc[0])<=80 and desc[0].endswith('.'),rel+': description')
    descriptions+=desc
    for key in ['og:description','twitter:description']: check(doc.meta(key)==desc,rel+': '+key)
    graph=json.loads(re.search(r'<script type="application/ld\+json">([\s\S]*?)</script>',text)[1])['@graph']
    collection=next(g for g in graph if g['@type']=='CollectionPage')
    items=next(g for g in graph if g['@type']=='ItemList')
    check(collection['description']==desc[0],rel+': schema description')
    check(items['numberOfItems']==len(items['itemListElement']),rel+': schema count')
    check(len(re.findall(r'<nav class="nav"[^>]*>[\s\S]*?href="/선생님찾기/" aria-current="page"',text))==1,rel+': current menu')
    b=next((b for b in branches if b['path'].strip('/')+'/index.html'==rel),None)
    if b:
        check(items['numberOfItems']==len(b['profiles']),rel+': profile schema count')
        check(len([a for a in doc.attrs('article') if 'data-profile' in a])==len(b['profiles']),rel+': profile card count')
        photos=[p['photo'] for p in b['profiles']]; check(len(set(photos))==len(photos),rel+': repeated photo')
        for p in b['profiles']:
            profiles+=1
            card=re.search(r'<article class="teacher-profile" id="'+p['id']+r'"[\s\S]*?</article>',text)
            if not card: check(False,rel+': missing '+p['id']); continue
            card=card[0]
            copy=re.search(r'<div class="teacher-profile-copy">([\s\S]*?)</div>',card)[1]
            copy=' '.join(unescape(t) for t in re.findall(r'<p>(.*?)</p>',copy,re.S))
            check(copy==p['intro'],rel+': source introduction mismatch '+p['id'])
            check(E(p['name'])+' 선생님</h3>' in card,rel+': source name '+p['id'])
            for k in p['keywords']: check('<span>'+E(k)+'</span>' in card,rel+': missing source keyword '+p['id'])
            check('/assets/teachers/'+p['photo'] in card,rel+': photo mapping '+p['id'])
        if b['branchPath']: check('href="'+b['branchPath']+'"' in text,rel+': branch backlink')
    else:
        check(items['numberOfItems']==len(branches),'Hub schema branch count')
        check(len([a for a in doc.attrs('article') if 'data-teacher-card' in a])==len(branches),'Hub card count')
    targets=[a.get('href',a.get('src','')) for tag in ['a','img','link','script'] for a in doc.attrs(tag)]+[g['url'] for g in items['itemListElement']]
    for href in targets:
        target=urlsplit(urljoin(canonical,href))
        if target.netloc!=urlsplit(domain).netloc: continue
        dest=root/unquote(target.path).lstrip('/')
        if target.path.endswith('/'): dest=dest/'index.html'
        check(dest.is_file(),rel+': missing internal URL '+href); links+=1
        if target.fragment and dest.is_file() and dest.suffix=='.html':
            if dest not in ids_cache: ids_cache[dest]={a['id'] for _,a in HTML(html_text(dest)).nodes if 'id' in a}
            check(unquote(target.fragment) in ids_cache[dest],rel+': missing linked anchor '+href)

contexts=0; subject_contexts=0; navigation=0; preserved=0
branchmap={b['branchPath']:b for b in branches if b['branchPath']}
existing=[p for p in manifest['files'] if p.endswith('.html') and not p.startswith('선생님찾기/')] if manifest else []
for rel in existing:
    text=html_text(root/rel)
    nav=re.search(r'<nav class="nav"[^>]*>[\s\S]*?</nav>',text)
    footer=re.search(r'<div class="footer-links"[^>]*>[\s\S]*?</div>',text)
    if nav:
        check(nav[0].count('href="/선생님찾기/"')==1,rel+': menu link count'); navigation+=1
    if footer: check(footer[0].count('href="/선생님찾기/"')==1,rel+': footer link count')
    pieces=rel.split('/')
    branch='/'+'/'.join(pieces[:3])+'/' if pieces[0]=='지점안내' and len(pieces)>3 else None
    is_subject=rel in data.get('subjectPages',{})
    if is_subject: branch=data['subjectPages'][rel]
    count=text.count('<!-- teacher-directory:start -->')
    check(count==(1 if branch in branchmap else 0),rel+': branch context count')
    if count:
        if is_subject: subject_contexts+=1
        else: contexts+=1
        block=re.search(r'<!-- teacher-directory:start -->[\s\S]*?<!-- teacher-directory:end -->',text)[0]
        check('href="'+branchmap[branch]['path']+'"' in block,rel+': wrong teacher branch link')
        check('href="/assets/teachers.css' in text,rel+': missing context stylesheet')
if args.baseline:
    with zipfile.ZipFile(args.baseline) as archive:
        for name in archive.namelist():
            if not name.endswith('.html'): continue
            before=archive.read(name).decode('utf-8')
            expected=patch_existing(before,name,data_root).encode('utf-8')
            check(raw_bytes(root/name)==expected,name+': unrelated HTML changed')
            preserved+=1
        sitemap_before=ET.fromstring(archive.read('sitemap.xml'))
        beforelocs={n.find('{*}loc').text:n.find('{*}lastmod').text for n in sitemap_before.findall('{*}url')}
else: beforelocs={}
sitemap=ET.parse(root/'sitemap.xml')
locs=[n.find('{*}loc').text for n in sitemap.findall('{*}url')]
check(len(set(locs))==len(locs),'Duplicate sitemap URL')
check(set(beforelocs).issubset(locs),'Removed sitemap URLs')
for rel in pages:
    check(domain+'/'+quote(rel.removesuffix('index.html'),safe='/') in locs,'Missing sitemap teacher URL '+rel)
check(len(set(descriptions))==len(pages),'Repeated teacher descriptions')
for p in data['photos']:
    dest=root/'assets/teachers'/p['file']
    check(dest.exists() and hashlib.sha256(raw_bytes(dest)).hexdigest()==p['sha256'],'Photo modified '+p['file'])
if manifest and root==data_root:
    for rel,expected in manifest['files'].items():
        raw=raw_bytes(root/rel); exact=hashlib.sha256(raw).hexdigest()==expected
        if not exact and re.search(r'\.(?:html|css|js|json|xml|txt|svg|webmanifest)$',rel):
            lf=raw.replace(b'\r\n',b'\n')
            exact=hashlib.sha256(lf).hexdigest() in [expected,manifest.get('textSha256',{}).get(rel)] or hashlib.sha256(lf.replace(b'\n',b'\r\n')).hexdigest()==expected
        check(exact,'Public snapshot hash '+rel)
    check(not any(p.startswith(('tools/','reports/','.')) or p.endswith('.xlsx') for p in manifest['files']),'Private files in public snapshot')
result={'root':str(root),'teacherPages':len(pages),'branches':len(branches),'profileRecords':profiles,'photoFiles':len(data['photos']),'maxProfilesPerBranch':max(len(b['profiles']) for b in branches),'descriptionMin':min(map(len,descriptions)),'descriptionMax':max(map(len,descriptions)),'teacherLinksChecked':links,'existingMenus':navigation,'branchContextPages':contexts,'subjectContextPages':subject_contexts,'preservedHtmlPages':preserved,'sitemapPages':len(locs),'excludedBranches':len(data['branches'])-len(branches),'errors':errors}
args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False)); sys.exit(bool(errors))
