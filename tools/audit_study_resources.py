"""Check new content coverage, links, metadata, images and exact old-page preservation."""
from pathlib import Path
from html.parser import HTMLParser
from html import escape
from urllib.parse import urlsplit,unquote
from concurrent.futures import ThreadPoolExecutor
import argparse,hashlib,json,re,zipfile,xml.etree.ElementTree as ET
from education_articles_data import ARTICLES
from study_resource_links import START,END,CSS,MENU,decorate_study_page

class Page(HTMLParser):
    def __init__(self,text):
        super().__init__(); self.refs=[]; self.ids=[]; self.meta={}; self.canonical=None; self.h1=0; self.images=[]; self.json=[]; self.injson=False; self.feed(text)
    def handle_starttag(self,tag,attributes):
        a=dict(attributes)
        if 'id' in a: self.ids.append(a['id'])
        if tag=='h1': self.h1+=1
        if tag=='a' and 'href' in a: self.refs.append(a['href'])
        if tag in ['img','script'] and 'src' in a: self.refs.append(a['src'])
        if tag=='link' and 'href' in a:
            if a.get('rel')=='canonical': self.canonical=a['href']
            elif a.get('rel')=='stylesheet': self.refs.append(a['href'])
        if tag=='meta': self.meta[a.get('name',a.get('property',''))]=a.get('content','')
        if tag=='img': self.images.append(a)
        if tag=='script' and a.get('type')=='application/ld+json': self.injson=True
    def handle_endtag(self,tag):
        if tag=='script': self.injson=False
    def handle_data(self,data):
        if self.injson: self.json.append(data)

def run(root,out,before,public=False):
    errors=[]; counts={}; old=json.loads(before.read_text(encoding='utf-8')); snapshot=out/('authoring-before.zip' if before.name.startswith('authoring') else 'worktree-before.zip')
    new=list((root/'교육정보').rglob('index.html'))+list((root/'학습커리큘럼').rglob('index.html'))
    if len(new)!=115: errors.append(('new-count',len(new)))
    ids={}; pagecache={}; existing=set(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and not p.relative_to(root).parts[0].startswith('.') and not p.relative_to(root).parts[0] in ['node_modules','tools','reports','tmp','test-results'])
    def parse_file(path):
        rel=path.relative_to(root).as_posix(); text=path.read_text(encoding='utf-8'); p=Page(text); return rel,text,p
    with ThreadPoolExecutor(max_workers=12) as pool: parsed=list(pool.map(parse_file,new))
    workbook=json.loads((Path(__file__).resolve().parent/'data/curriculum/workbook.json').read_text(encoding='utf-8'))['sheets']
    curriculum_rows=workbook['초등과목'][5:]+workbook['중등과목'][5:]+workbook['고등과목'][5:]
    text_by_path={rel:text for rel,text,p in parsed}
    level_pages=0
    for row in curriculum_rows:
        grade,subject=row[:2]
        stage={'초':'초등','중':'중등','고':'고등'}[grade[0]]
        rel=f'학습커리큘럼/{stage}/{grade}/{subject}/index.html'
        text=text_by_path.get(rel,'')
        low=grade in ['초1','초2'] and subject in ['영어','사회','과학']
        level_stage={'초등':'초등학생','중등':'중학생','고등':'고등학생'}[stage]
        selected=[l for l in workbook['반별운영'][5:] if l[0]==level_stage and l[1]==subject] if not low else []
        if text.count('<article class="curr-level">')!=len(selected): errors.append(('level-count',rel,len(selected)))
        if selected:
            level_pages+=1
            for level in selected:
                for value in level[3:8]:
                    if escape(value,quote=True) not in text: errors.append(('missing-level-content',rel,level[2],value))
        elif not low and subject!='역사': errors.append(('missing-workbook-level',rel))
        if low and '문장 안에서 역할과 의미' in text: errors.append(('low-grade-language',rel))
    for rel,text,p in parsed:
        pagecache[rel]=p; ids[rel]=set(p.ids)
        if p.h1!=1: errors.append(('h1',rel,p.h1))
        if len(p.ids)!=len(set(p.ids)): errors.append(('duplicate-id',rel))
        description=p.meta.get('description','')
        if not description or len(description)>80 or not description.endswith('.'): errors.append(('description',rel,description))
        if p.meta.get('og:description')!=description or p.meta.get('twitter:description')!=description: errors.append(('social-description',rel))
        expected='https://xn--9p4bn5e3wjn0a.com/'+__import__('urllib.parse',fromlist=['quote']).quote(rel.removesuffix('index.html'),safe='/')
        if p.canonical!=expected or p.meta.get('og:url')!=expected: errors.append(('canonical',rel))
        if 'noindex' in p.meta.get('robots',''): errors.append(('noindex',rel))
        if '편집 원칙' in text or '편집원칙' in text or 'C:\\Users' in text: errors.append(('private-policy',rel))
        graph=json.loads(''.join(p.json))['@graph']
        web=[g for g in graph if g.get('@id')==expected+'#webpage'][0]
        if web['description']!=description: errors.append(('schema-description',rel))
        for image in p.images:
            if not image.get('alt') and image.get('src','').startswith('/assets/education/'): errors.append(('image-alt',rel))
        if rel.startswith('교육정보/') and rel!='교육정보/index.html':
            article_images=[i for i in p.images if i.get('src','').startswith('/assets/education/')]
            if len(article_images)!=3 or len({i['src'] for i in article_images})!=3: errors.append(('three-images',rel))
            if text.count('<details>')!=2: errors.append(('article-faq',rel))
    # Verify every new button, file, and fragment, not only sampled pages.
    for rel,text,p in parsed:
        for ref in p.refs:
            u=urlsplit(ref)
            if u.scheme or u.netloc: continue
            dest=unquote(u.path)
            if dest.startswith('/'):
                target=(dest.strip('/')+'/' if dest.strip('/') else '')+'index.html' if dest.endswith('/') else dest.strip('/')
            elif dest: target=(Path(rel).parent/dest).as_posix()
            else: target=rel
            if target not in existing: errors.append(('missing-link',rel,ref)); continue
            if u.fragment and target.endswith('.html'):
                if target not in ids: ids[target]=set(Page((root/target).read_text(encoding='utf-8')).ids)
                if unquote(u.fragment) not in ids[target]: errors.append(('missing-anchor',rel,ref))
    # Removing only the declared insertions must recover each original page exactly.
    preserved=0; menus=0; contexts=0
    with zipfile.ZipFile(snapshot) as z:
        for rel in old:
            if not rel.endswith('.html'): continue
            original=z.read(rel).decode('utf-8'); current=(root/rel).read_bytes().decode('utf-8')
            if public:
                # Analytics/metadata transforms are separately verified by their builders.
                current=current.replace('\r\n','\n'); original=original.replace('\r\n','\n')
                if '<nav class="nav"' in current and '/교육정보/' not in re.search(r'<nav class="nav"[\s\S]*?</nav>',current)[0]: errors.append(('old-menu',rel))
                continue
            expected=decorate_study_page(original,'/'+rel.removesuffix('index.html'))
            if current!=expected: errors.append(('old-content-changed',rel))
            else: preserved+=1
            if '<nav class="nav"' in current:
                menus+=1
                nav=re.search(r'<nav class="nav"[\s\S]*?</nav>',current)[0]
                if nav.count('href="/교육정보/"')!=1 or nav.count('href="/학습커리큘럼/"')!=1: errors.append(('old-menu',rel))
            if START in current:
                contexts+=1
                if current.count(START)!=1: errors.append(('context-duplicate',rel))
                block=re.search(re.escape(START)+r'[\s\S]*?'+re.escape(END),current)[0]
                for ref in Page(block).refs:
                    dest=unquote(urlsplit(ref).path).strip('/')+'/index.html'
                    if dest not in existing: errors.append(('old-context-link',rel,ref))
    sitemap=ET.parse(root/'sitemap.xml'); locs=[e.text for e in sitemap.findall('.//{*}loc')]
    if len(locs)!=len(set(locs)): errors.append(('duplicate-sitemap',))
    for rel,_,p in parsed:
        if p.canonical not in locs: errors.append(('missing-sitemap',rel))
    images=list((root/'assets/education/images').glob('*.webp'))
    if len(images)!=90: errors.append(('image-count',len(images)))
    actual=json.loads((root/'assets/education/locations.json').read_text(encoding='utf-8'))
    for bpath,b in actual['branches'].items():
        for path in [bpath]+[l['path'] for l in b['locals']]:
            if path.strip('/')+'/index.html' not in existing: errors.append(('location-link',path))
    lengths=[len(a['intro'])+sum(len(p) for _,p in a['sections'])+len(a['example'])+len(a['parent'])+sum(len(q)+len(ans) for q,ans in a['faq']) for a in ARTICLES]
    result={'root':str(root),'newPages':len(new),'educationArticles':len(ARTICLES),'curriculumSubjects':len(curriculum_rows),'levelPages':level_pages,'articleCharsMin':min(lengths),'articleCharsMean':round(sum(lengths)/30),'images':len(images),'imageBytes':sum(p.stat().st_size for p in images),'preservedHtml':preserved,'existingMenus':menus,'existingContexts':contexts,'sitemapUrls':len(locs),'errors':errors}
    report=out/('public-audit.json' if public else 'authoring-audit.json' if before.name.startswith('authoring') else 'worktree-audit.json')
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='errors'},ensure_ascii=False)); print('errors',len(errors)); print(json.dumps(errors[:12],ensure_ascii=False))
    return bool(errors)
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]); p.add_argument('--out',type=Path,required=True); p.add_argument('--before',type=Path,required=True); p.add_argument('--public',action='store_true'); a=p.parse_args()
    raise SystemExit(run(a.root,a.out,a.before,a.public))
