from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote, urljoin
import argparse, collections, itertools, json, re, subprocess, xml.etree.ElementTree as ET
from learning_guides_data import GUIDES, SOURCES

parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]); parser.add_argument('--report',type=Path); parser.add_argument('--baseline-sitemap',type=Path); args=parser.parse_args(); ROOT=args.root.resolve()
DOMAIN='https://xn--9p4bn5e3wjn0a.com'; errors=[]
def check(ok,message):
    if not ok: errors.append(message)
class HTML(HTMLParser):
    def __init__(self,text):
        super().__init__(); self.nodes=[]; self.text=[]; self.feed(text)
    def handle_starttag(self,tag,attrs): self.nodes.append((tag,dict(attrs)))
    def handle_data(self,data): self.text.append(data)
    def attrs(self,tag): return [a for t,a in self.nodes if t==tag]
    def meta(self,name): return [a.get('content') for a in self.attrs('meta') if a.get('name',a.get('property'))==name]
    def canonical(self): return next(a['href'] for a in self.attrs('link') if a.get('rel')=='canonical')
pages=[ROOT/'학습가이드/index.html']+[ROOT/'학습가이드'/g['slug']/'index.html' for g in GUIDES]
descriptions=[]; lengths=[]; local_links=0
for file in pages:
    rel=file.relative_to(ROOT).as_posix(); text=file.read_text(encoding='utf-8'); p=HTML(text)
    check('편집' not in text and 'editorial-policy' not in text,rel+': unwanted public policy mention')
    check('\ufffd' not in text,rel+': replacement character')
    check(len(p.attrs('h1'))==1,rel+': h1 count')
    desc=p.meta('description'); check(len(desc)==1,rel+': description count')
    if not desc: continue
    d=desc[0]; descriptions.append(d); lengths.append(len(d))
    check(0<len(d)<=80 and d.endswith('.'),rel+': incomplete/long description')
    for key in ['og:description','twitter:description']: check(p.meta(key)==[d],rel+': '+key)
    expected=DOMAIN+'/'+__import__('urllib.parse',fromlist=['quote']).quote(str(file.parent.relative_to(ROOT)).replace('\\','/')+'/',safe='/')
    check(p.canonical()==expected,rel+': canonical')
    ids=[a['id'] for _,a in p.nodes if 'id' in a]; check(len(ids)==len(set(ids)),rel+': duplicate IDs')
    graph=json.loads(re.search(r'<script type="application/ld\+json">([\s\S]*?)</script>',text).group(1))['@graph']
    for node in graph:
        if node['@type'] in ['Article','WebPage','CollectionPage']: check(node['description']==d,rel+': JSON-LD description')
        if node['@type']=='Article': check(node['abstract']==d,rel+': article abstract')
    for tag in ['a','script','link','img']:
        for a in p.attrs(tag):
            href=a.get('href',a.get('src','')); target=urlsplit(urljoin(expected,href))
            if target.netloc!=urlsplit(DOMAIN).netloc: continue
            path=unquote(target.path).lstrip('/'); dest=ROOT/path
            if target.path.endswith('/'): dest=dest/'index.html'
            check(dest.is_file(),rel+': missing internal link '+href); local_links+=1
            if target.fragment and dest==file: check(unquote(target.fragment) in ids,rel+': missing fragment '+href)
    if file.parent.name!='학습가이드':
        g=next(g for g in GUIDES if g['slug']==file.parent.name)
        check(len(p.attrs('textarea'))==4,rel+': record fields')
        check(len(re.findall(r'<li><h3>',text))==4,rel+': steps')
        faq=next(n for n in graph if n['@type']=='FAQPage')
        check(len(faq['mainEntity'])==2,rel+': FAQ count')
        for q in faq['mainEntity']:
            check(q['name'] in ''.join(p.text) and q['acceptedAnswer']['text'] in ''.join(p.text),rel+': invisible FAQ')
        for key in g['sources']: check(SOURCES[key][1] in text,rel+': missing source')
        check(sum(len(g[k]) for k in ['intro','example','parent','caution','followup'])+sum(len(a)+len(b) for a,b in g['steps'])>=600,rel+': thin original activity')
        blank=ROOT/'assets/learning-guides/forms'/f'{g["slug"]}.txt'; data=blank.read_bytes()
        check(data.startswith(b'\xef\xbb\xbf') and b'\r\n' in data,rel+': download encoding')
        for field in g['fields']: check(field in data.decode('utf-8-sig'),rel+': record form mismatch')
check(len(descriptions)==len(set(descriptions)),'duplicate descriptions')
check(len({g['title'] for g in GUIDES})==40,'duplicate titles')
check(len({tuple(g['fields']) for g in GUIDES})==40,'duplicate record sets')
hub=(ROOT/'학습가이드/index.html').read_text(encoding='utf-8')
for anchor in ['english','math','planner','wrong-answer']: check(f'id="{anchor}"' in hub,'missing legacy anchor '+anchor)
sitemap=ET.parse(ROOT/'sitemap.xml'); ns={'s':'http://www.sitemaps.org/schemas/sitemap/0.9'}
urls=[n.text for n in sitemap.findall('.//s:loc',ns)]; check(len(urls)==len(set(urls)),'duplicate sitemap URLs')
guide_urls=[u for u in urls if unquote(urlsplit(u).path).startswith('/학습가이드/')]; check(len(guide_urls)==41,'guide sitemap coverage')
rss=ET.parse(ROOT/'rss.xml'); items=rss.findall('./channel/item'); rss_links=[i.findtext('link') for i in items]
for g in GUIDES: check(DOMAIN+'/학습가이드/'+g['slug']+'/' in [unquote(u) for u in rss_links],'RSS missing '+g['slug'])
script=(ROOT/'assets/learning-guides.js').read_text(encoding='utf-8')
check(not re.search(r'fetch\(|XMLHttpRequest|sendBeacon|localStorage|sessionStorage',script),'record script transmission/storage')
baseline=(args.baseline_sitemap.read_bytes() if args.baseline_sitemap else subprocess.run(['git','show','HEAD:sitemap.xml'],cwd=Path(__file__).resolve().parents[1],capture_output=True,check=True).stdout).decode('utf-8').replace('\r\n','\n')
old={re.search('<loc>(.*?)</loc>',e).group(1):e for e in re.findall(r'<url>[\s\S]*?</url>',baseline)}
current={re.search('<loc>(.*?)</loc>',e).group(1):e for e in re.findall(r'<url>[\s\S]*?</url>',(ROOT/'sitemap.xml').read_text(encoding='utf-8'))}
for loc,entry in old.items():
    if '/학습가이드/' not in unquote(loc): check(current.get(loc)==entry,'unrelated sitemap entry changed: '+loc)
similar=[]
for a,b in itertools.combinations(GUIDES,2):
    wa=set((a['intro']+' '+' '.join(t for _,t in a['steps'])).split()); wb=set((b['intro']+' '+' '.join(t for _,t in b['steps'])).split()); score=len(wa&wb)/len(wa|wb)
    similar.append((score,a['slug'],b['slug']))
top=max(similar); check(top[0]<.45,'near duplicate article activities')
report={'pages':len(pages),'articles':len(GUIDES),'categories':dict(collections.Counter(g['category'] for g in GUIDES)),'descriptionLengths':{'min':min(lengths),'max':max(lengths)},'checkedLocalLinks':local_links,'sitemapPages':len(urls),'guideSitemapPages':len(guide_urls),'uniqueRecordForms':40,'highestActivityJaccard':top,'errors':errors}
if args.report: args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({**report,'errors':errors[:10],'errorCount':len(errors)},ensure_ascii=False)); raise SystemExit(bool(errors))
