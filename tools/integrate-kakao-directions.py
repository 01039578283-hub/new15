"""Prepare a reviewed, additive map release without rerunning site generators.

python tools/integrate-kakao-directions.py --evidence-dir <private audit directory>
Input originals and authoring files are never changed by this preparation step.
"""
from pathlib import Path
import argparse,collections,concurrent.futures,hashlib,html,json,re
from urllib.parse import unquote,urlsplit
from lxml import html as lh

R=Path(__file__).resolve().parents[1]
DATE='2026-10-17'
def sha(b):return hashlib.sha256(b).hexdigest()
def esc(x):return html.escape(str(x),quote=True)
def route(p):return '/' if p=='index.html' else '/'+p.removesuffix('index.html')
BUS={'0101':'간선','0102':'지선','0103':'광역','0104':'순환','0105':'공항','0106':'일반','0107':'좌석','0108':'급행간선','0109':'마을','0110':'직행','0111':'외곽','0112':'시외','0113':'농어촌'}

def transport(data):
    groups=[]
    subway=[x['name'] for x in (data.get('subways') or []) if not x.get('ignore')]
    stops=[x['name'] for x in (data.get('busStops') or []) if not x.get('ignore')]
    buses=[{'type':k,'label':BUS[k],'names':[x['name'] for x in v]} for k,v in (data.get('busLines') or {}).items() if v]
    if subway:groups.append({'title':'주변 지하철','className':'kd-stations','items':subway})
    if stops:groups.append({'title':'주변 정류장','className':'kd-stops','items':stops})
    if buses:groups.append({'title':'주변 버스','className':'kd-buses','items':buses})
    return groups

def traffic_html(groups):
    if not groups:return '<p class="kd-empty">이 약도에는 주변 교통 정보가 표시되지 않습니다. 지도와 지점 주소를 확인해 주세요.</p>'
    out=[]
    for g in groups:
        items=[]
        for i,x in enumerate(g['items'],1):
            if isinstance(x,str):
                number=f'<span class="kd-stop-number" aria-hidden="true">{i}</span>' if g['className']=='kd-stops' else ''
                items.append('<li>'+number+'<span>'+esc(x)+'</span></li>')
            else:
                items.append('<li><span class="kd-bus-type kd-bus-'+esc(x['type'])+'">'+esc(x['label'])+'</span><span class="kd-bus-numbers">'+''.join('<span>'+esc(v)+'</span>' for v in x['names'])+'</span></li>')
        tag='ol' if g['className']=='kd-stops' else 'ul'
        out.append('<li><h3>'+g['title']+'</h3><'+tag+' class="'+g['className']+'">'+''.join(items)+'</'+tag+'></li>')
    return '<ul class="kd-traffic">'+''.join(out)+'</ul>'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--evidence-dir',type=Path,required=True);a=ap.parse_args();O=a.evidence_dir
    def read(n):return json.loads((O/n).read_text('utf8'))
    def save(n,v):(O/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    stage=O/'staged-public';assert not stage.exists();stage.mkdir()
    roots=read('branch-roots.json');pages=read('page-mapping.json');provided=read('provider-data.json');base=read('baseline.json');manifest=read('before-release-public-manifest.json')
    byname={x['branch']:x for x in provided}
    # These six old pages have no branch link, but their named center and street
    # address explicitly match the newly supplied source. Keep operating warnings.
    reviewed=[]
    for e in read('mapping-errors.json'):
        p=e['file'];d=lh.fromstring((R/p).read_bytes())
        cards={''.join(x.xpath('./strong/text()')):''.join(x.xpath('./span/text()')) for x in d.xpath('//div[@class="academy-fact-card"]')}
        assert '/화성태안/' in '/'+p and cards['센터']=='와와학습코칭센터 화성태안점'
        assert '병점중앙로 87' in cards['주소'] and '병점중앙로 87' in byname['화성태안점']['data']['address']
        path=next(k for k,v in roots.items() if v['branch']=='화성태안점')
        pages.append({'file':p,'route':route(p),'branchPath':path,'branch':'화성태안점','legacyAddress':cards['주소'],'mappingBasis':'기존 센터명 및 병점중앙로 87 408호가 제공 소스의 등록 지점·주소와 일치. 현재 운영 확인 안내 유지.'})
        reviewed.append(p)
    assert len(reviewed)==6 and len(pages)==8355
    maps={};new={};assets={}
    for n in ['kakao-directions.css','kakao-directions.js','kakao-frame.css','kakao-frame.js']:
        b=(R/'tools/kakao-directions'/n).read_bytes();stem,suffix=n.rsplit('.',1);path='assets/'+stem+'.'+sha(b)[:12]+'.'+suffix;new[path]=b;assets[n]='/'+path
    for path,c in roots.items():
        m=byname[c['branch']];stamp=m['timestamp'];key=m['key']
        assert re.fullmatch(r'\d+',stamp) and re.fullmatch(r'[a-zA-Z0-9]+',key)
        frame=('''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,follow"><meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests"><title>'''+esc(c['branch'])+''' 위치 지도</title><link rel="stylesheet" href="'''+assets['kakao-frame.css']+'''"></head><body>
<div id="daumRoughmapContainer'''+stamp+'''" class="root_daum_roughmap root_daum_roughmap_landing"></div>
<script charset="UTF-8" class="daum_roughmap_loader_script" src="https://t1.kakaocdn.net/kakaomapweb/roughmap/loader/prod/roughmapLoader.js"></script>
<script>window.wawaLocationMap=new daum.roughmap.Lander({timestamp:"'''+stamp+'''",key:"'''+key+'''",mapWidth:String(document.documentElement.clientWidth),mapHeight:String(Math.max(240,innerHeight-36))});window.wawaLocationMap.render();</script>
<script src="'''+assets['kakao-frame.js']+'''"></script></body></html>''').encode('utf8')
        framepath='assets/kakao-maps/'+stamp+'/index.html';new[framepath]=frame
        groups=transport(m['data']);raw=json.dumps(groups,ensure_ascii=False,separators=(',',':')).encode('utf8');trafficpath='assets/kakao-traffic/'+stamp+'.json';new[trafficpath]=raw
        # Keep the site's reviewed floor/unit information. The vague historical
        # root gets the clearly labelled address from its supplied map source.
        vague=c['branch']=='화성태안점'
        address=m['data']['address'] if vague else c['address']
        maps[c['branch']]={'branch':c['branch'],'branchPath':path,'address':address,'addressLabel':'약도 등록 주소' if vague else '주소','timestamp':stamp,'key':key,'sourceFile':m['file'],'sourceSha':m['sourceSha'],'providerAddress':m['data'].get('address',''),'providerName':m['data'].get('name',''),'frame':'/assets/kakao-maps/'+stamp+'/?v='+sha(frame)[:12],'traffic':'/'+trafficpath+'?v='+sha(raw)[:12],'groups':groups,'needsOperatingConfirmation':vague}

    def shell(m):
        return '<div class="kd-map-shell"><div class="kd-map-status" aria-hidden="true">지도 위치를 자동으로 불러옵니다.</div><iframe title="'+esc(m['branch'])+' 위치 지도" data-kakao-src="'+esc(m['frame'])+'" loading="lazy" width="900" height="420" sandbox="allow-scripts allow-same-origin" referrerpolicy="strict-origin-when-cross-origin"></iframe></div>'
    def info(m):
        return '<dl class="kd-address"><dt>'+m['addressLabel']+'</dt><dd>'+esc(m['address'])+'</dd></dl><div class="kd-traffic-holder">'+traffic_html(m['groups'])+'</div>'
    source='<p class="kd-source">주변 교통 정보는 카카오맵 약도 기준입니다. 운행 노선과 정류장은 변경될 수 있으므로 방문할 지점·건물·층수를 함께 확인해 주세요.</p>'
    def section(m):
        note='<p class="kd-empty">제공된 약도의 등록 위치입니다. 현재 운영 여부와 방문 가능 여부는 상담 시 확인해 주세요.</p>' if m['needsOperatingConfirmation'] else ''
        return '<section class="kakao-directions" id="kakao-directions" data-kakao-branch="'+esc(m['branch'])+'"><h2>찾아오시는 길</h2><p class="kd-intro">'+esc(m['branch'])+'의 위치와 주변 교통편을 확인하세요.</p>'+shell(m)+info(m)+note+source+'<noscript><p>기존 지도 이미지와 주소·교통 안내를 확인해 주세요.</p></noscript></section>'
    critical='<style data-kakao-critical="20261017">.kakao-directions{box-sizing:border-box;grid-column:1/-1;width:100%;max-width:1160px;margin:24px auto;padding:clamp(18px,3vw,32px)}.kd-map-column{min-width:0;align-self:start}.kd-map-shell{position:relative;width:100%;height:420px;overflow:hidden}.kd-map-shell iframe{display:block;width:100%;height:100%;border:0}.kd-map-status{position:absolute;inset:0;display:grid;place-items:center;background:#fff;padding:24px;text-align:center;pointer-events:none}.kd-map-shell[data-map-ready] .kd-map-status{display:none}@media(max-width:640px){.kakao-directions{margin:20px auto;padding:20px 12px}.kd-map-shell{height:360px}}</style>'
    inject=critical+'<link rel="stylesheet" href="'+assets['kakao-directions.css']+'" media="print" onload="this.media=\'all\'" data-kakao-style="20261017"><noscript><link rel="stylesheet" href="'+assets['kakao-directions.css']+'"></noscript><script defer src="'+assets['kakao-directions.js']+'" data-kakao-script="20261017"></script>'
    changed={};records=[]
    def register(p,s,record):
        assert sha((R/p).read_bytes())==base['files'][p]['release'] and s.count('</head>')==1
        assert 'data-kakao-style' not in s
        changed[p]=s.replace('</head>',inject+'</head>',1).encode('utf8');records.append({'file':p,**record})
    for p in pages:
        name=p['file'];m=maps[p['branch']];s=(R/name).read_bytes().decode('utf8')
        figures=[x for x in re.finditer(r'<figure\b[^>]*>[\s\S]*?</figure>',s) if re.search(r'<img\b[^>]*(?:alt=["\'][^"\']*지도|data-media=["\']map["\'])',x[0])]
        assert len(figures)==1,name
        f=figures[0];block=section(m);wrapped='academy-map-card' in f[0]
        if wrapped:
            replacement='<div class="kd-map-column" data-kakao-column="20261017">'+f[0]+block+'</div><!-- kakao-column-end -->'
            s=s[:f.start()]+replacement+s[f.end():]
        else:s=s[:f.end()]+block+s[f.end():]
        register(name,s,{'kind':'detail','branch':p['branch'],'branchPath':p['branchPath'],'frame':m['frame'],'wrappedMapColumn':wrapped,'source':m['sourceFile']})
    hubs=[]
    for p in manifest['files']:
        if p in changed or not p.endswith('index.html'):continue
        bits=p.split('/')
        hub=p=='index.html' or p.startswith('지점안내/') and len(bits)<=3 or p.startswith('과목별학원/') and len(bits)<=3
        if not hub:continue
        prefix=route(p)
        choices=list(dict.fromkeys(x['branch'] for x in pages if x['route'].startswith(prefix)))
        assert choices,p
        choices.sort(key=lambda n:(maps[n]['branchPath'].split('/')[2],n))
        first=maps[choices[0]]
        option_data=[{'name':n,'frame':maps[n]['frame'],'address':maps[n]['address'],'traffic':maps[n]['traffic']} for n in choices]
        def option(x):return '<option value="'+esc(x['frame'])+'" data-address="'+esc(x['address'])+'" data-traffic="'+esc(x['traffic'])+'">'+esc(x['name'])+'</option>'
        if len(choices)>=12:
            raw=json.dumps(option_data,ensure_ascii=False,separators=(',',':')).encode('utf8');path='assets/kakao-hubs/'+sha(raw)[:16]+'.json';new[path]=raw
            opts=option(option_data[0]);attr=' data-kakao-hub-options="/'+path+'"'
        else:opts=''.join(map(option,option_data));attr=''
        block='<section class="kakao-directions" id="kakao-directions" data-kakao-hub="20261017"><h2>지점 위치와 찾아오시는 길</h2><p class="kd-intro">방문할 지점을 선택해 지도와 주변 교통편을 확인하세요.</p><label class="kd-hub-label" for="kakao-branch-select">지점 선택</label><select id="kakao-branch-select" class="kd-hub-select" data-kakao-select'+attr+'>'+opts+'</select><p class="kd-hub-status" role="status" aria-live="polite">'+esc(first['branch'])+'의 위치를 표시합니다.</p>'+shell(first)+info(first)+source+'<noscript><p>기존 지점 목록에서 각 지점의 지도 이미지와 주소를 확인할 수 있습니다.</p></noscript></section>'
        s=(R/p).read_bytes().decode('utf8');assert s.count('</main>')==1
        register(p,s.replace('</main>',block+'</main>',1),{'kind':'hub','choices':choices,'frame':first['frame']});hubs.append({'file':p,'choices':choices})
    changedroutes={route(x['file']) for x in records}
    def stamp(m):
        block=m[0];loc=re.search(r'<loc>(.*?)</loc>',block)[1]
        return re.sub(r'<lastmod>[^<]*</lastmod>','<lastmod>'+DATE+'</lastmod>',block) if unquote(urlsplit(html.unescape(loc)).path) in changedroutes else block
    changed['sitemap.xml']=re.sub(r'<url>.*?</url>',stamp,(R/'sitemap.xml').read_bytes().decode('utf8'),flags=re.S).encode('utf8')
    analytics=(R/'wawa-analytics-build.mjs').read_bytes();assert analytics.count(b"'test','tests'")==1
    (O/'analytics-after.mjs').write_bytes(analytics.replace(b"'test','tests'",b"'test','tests','kakao-maps'"))
    def write(item):
        p,b=item;dest=stage/p;dest.parent.mkdir(parents=True,exist_ok=True);assert not dest.exists();dest.write_bytes(b)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:list(pool.map(write,{**changed,**new}.items()))
    save('resolved-historical-mapping.json',reviewed);save('prepared-maps.json',maps);save('new-assets.json',{p:sha(b) for p,b in new.items()});save('changes.json',records);save('hub-mapping.json',hubs)
    summary={'date':DATE,'branches':len(maps),'detailPages':len(pages),'hubPages':len(hubs),'changedPages':len(records),'newFiles':len(new),'newFrames':len(maps),'assets':assets,'changedFiles':list(changed),'newFilesList':list(new),'unusedSources':sorted(set(byname)-set(maps)),'emptyTransport':[n for n,m in maps.items() if not m['groups']]}
    save('prepare-summary.json',summary);print(json.dumps({k:v for k,v in summary.items() if k not in ['changedFiles','newFilesList']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
