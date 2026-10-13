"""Narrow, repeatable content migration; never run the old site generators.

Usage: python tools/improve-google-learning.py --report-dir <private directory> [--apply]
The fixed examples are learning aids, not statements of branch availability.
"""
import argparse
import collections
import hashlib
import html as escape_html
import json
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree as ET

from lxml import html

ROOT = Path(__file__).resolve().parents[1]
HOST = "https://xn--9p4bn5e3wjn0a.com"
DATE = "2026-10-14"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
PROFILES = json.loads((ROOT / "tools/google-learning-examples.json").read_text("utf8"))
PROFILE = {(p["grade"], p["subject"]): p for p in PROFILES["profiles"]}

def esc(s):
    return escape_html.escape(s, quote=True)

def example(p, preparation=None):
    label = f'{p["grade"]} {p["subject"]}: 직접 확인하는 학습 예시'
    pieces = [f'<div class="school-materials" data-learning-example="{esc(p["grade"] + "-" + p["subject"])}">', f'<h3>{label}</h3>']
    for title, text in [(None, p['focus']), ('해 보기', p['question']), ('풀이와 근거', p['answer']), ('다음 확인', p['next'])]:
        pieces.append('<p>' + (f'<strong>{title}:</strong> ' if title else '') + esc(text) + '</p>')
    if preparation:
        pieces.append('<h4>학교 자료와 연결해 준비하기</h4><ol>'+''.join('<li>'+x+'</li>' for x in preparation)+'</ol>')
    pieces.append('<p>학습 과정을 설명하기 위해 만든 예시입니다. 현재 학교 진도와 학생 수준에 맞춰 활용하며, 실제 시험 문제나 지점의 개설 수업을 뜻하지 않습니다.</p></div>')
    return ''.join(pieces)

def replace_preparation(s, items):
    # The existing box stays in the same position, with its heading and scope note.
    pattern = r'(<div class="school-materials"><h3>[^<]+</h3>)<ol>.*?</ol>'
    value = ''.join('<li>' + x + '</li>' for x in items)
    s, n = re.subn(pattern, lambda m: m[1] + '<ol>' + value + '</ol>', s, flags=re.S)
    assert n == 1, ('preparation box count', n)
    return s

LEVEL_CHECKS = {
    ('초등', '수학'): ('계산한 답만 보지 말고 그림·말·식으로 같은 뜻을 설명할 수 있는지 확인합니다. 분수·소수·측정은 현재 학교 단원에서 고릅니다.', '학생이 처음 쓴 식과 고친 식을 함께 남기고, 단위·자릿값·연산 중 어느 부분에서 멈췄는지 적습니다.'),
    ('중등', '수학'): ('문장 조건을 식·도형·그래프로 옮기는 과정과 계산을 나누어 봅니다. 현재 단원에서 조건을 하나 바꾸면 풀이도 바뀌는 문제를 준비합니다.', '처음 틀린 줄과 사용한 개념을 표시하고, 해를 원래 조건에 넣어 확인한 기록을 남깁니다.'),
    ('고등', '수학'): ('공통수학·대수·미적분·확률과 통계·기하 등 실제 이수 과목명을 먼저 적습니다. 과목 이름은 예시이며 학교별 개설과 지점의 상담 가능 여부를 확인합니다.', '조건에서 식을 선택한 근거와 적용 범위를 적습니다. 답이 맞은 문제도 풀이를 설명하지 못했다면 별도로 표시합니다.'),
    ('초등', '영어'): ('현재 배우는 짧은 대화나 글에서 누가 무엇을 하는지 찾고 자신의 상황으로 한 문장을 바꾸어 봅니다.', '듣고 이해한 표현, 읽고 이해한 표현, 보지 않고 쓸 수 있는 표현을 구분합니다. 단어 시험 점수만으로 같은 수준이라고 판단하지 않습니다.'),
    ('중등', '영어'): ('교과서 문장 하나의 주어·시간·연결어를 바꾼 뒤 뜻과 형태가 함께 맞는지 확인합니다.', '해석의 근거와 직접 쓴 문장을 나란히 준비합니다. 어휘 부족, 문장 구조, 글의 관계, 쓰기 오류를 구분해 기록합니다.'),
    ('고등', '영어'): ('공통영어 또는 학교의 실제 선택 영어 과목명과 평가 범위를 적고, 한 지문의 주장·근거·조건을 표시합니다.', '원문의 근거를 찾는 과제와 자신의 말로 요약하는 과제를 나누어 준비합니다. 원문에 없는 내용을 추측해 넣은 부분은 따로 표시합니다.')
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-dir', required=True, type=Path)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    paths = [unquote(urlsplit(x.text).path) for x in ET.parse(ROOT/'sitemap.xml').getroot().iter(NS+'loc')]
    changes, planned, errors = [], {}, []
    for url in paths:
        file = ROOT / url.lstrip('/') / 'index.html'
        original = file.read_bytes()
        s = original.decode('utf8')
        parts = url.strip('/').split('/')
        kind = 'grade' if parts[0]=='지점안내' and len(parts)==5 else 'local' if parts[0]=='지점안내' and len(parts)==4 else 'comparison' if parts[0]=='과목별학원' and len(parts)==3 else None
        grammar = {x:s.count(x) for x in ['학부모는 학부모가', '이유을'] if x in s}
        if not kind and not grammar:
            continue
        try:
            assert 'data-learning-example=' not in s, 'Migration already applied'
            s = s.replace('학부모는 학부모가', '학부모가').replace('이유을','이유를')
            d = html.fromstring(s)
            if kind in ['grade', 'local']:
                subject = '수학' if parts[3].endswith('수학학원') else '영어' if parts[3].endswith('영어학원') else None
                assert subject, 'Unknown subject'
                heading = d.xpath('//section[@id="center-info"]/h2/text()')
                assert len(heading)==1 and heading[0].endswith('에서 상담하기'), heading
                branch = heading[0][:-len('에서 상담하기')]
                branch_url = '/' + '/'.join(parts[:3]) + '/'
                assert (ROOT / branch_url.lstrip('/') / 'index.html').is_file()
                location = f'<a href="{quote(branch_url)}#directions">{esc(branch)} 위치 안내</a>'
                if kind=='grade':
                    p = PROFILE[(parts[4], subject)]
                    items = [esc(p['school']), esc(p['record']), '자료마다 ‘혼자 설명할 수 있음·도움 후 가능·다시 확인’을 표시하고, 다음에 확인할 문제나 문장을 한 개 정합니다.', f'{esc(branch)} 상담에서는 준비한 자료로 우선 복습할 내용을 정리하고, 위에 안내된 수업 가능 학년과 실제 상담 가능한 과목·시간을 확인합니다.']
                    has_preparation = bool(d.xpath('//section[@id="schools"]//div[@class="school-materials"]'))
                    if has_preparation:
                        s = replace_preparation(s, items)
                    pattern = r'(<section class="branch-panel" id="section-2">.*?)(</section>)'
                    s, n = re.subn(pattern, lambda m: m[1]+example(p, None if has_preparation else items)+m[2], s, flags=re.S)
                    assert n==1, ('learning section count',n)
                else:
                    neighborhood = parts[3][:-len(subject+'학원')]
                    task = '최근 문제에서 처음 쓴 식, 풀이가 멈춘 줄, 단위를 함께 남깁니다. 정답을 베껴 쓴 오답 노트보다 처음 생각을 확인할 수 있는 자료가 도움이 됩니다.' if subject=='수학' else '현재 배우는 글에서 근거를 찾아 답한 자료와 보지 않고 직접 쓴 문장을 함께 준비합니다. 어휘·구조·내용 이해·쓰기 중 어려운 부분을 구분합니다.'
                    items = [f'{esc(neighborhood)}에서 다닐 {subject} 수업을 비교하기 전에 학생의 실제 학교·학년, 교과서, 현재 단원을 적습니다. 아래 학년별 안내에서는 해당 단계의 학습 예시를 확인할 수 있습니다.', esc(task), f'이 페이지가 안내하는 상담 지점은 {esc(branch)}입니다. 동네 이름과 지점 이름이 다를 수 있으므로 위의 수업 가능 학년과 상담 지점을 함께 확인합니다.', f'{location}에서 주소를 확인하고 학교·집에서 오가는 경로, 하교 후 가능한 시간과 귀가 방법을 적어 상담합니다. 이동 시간이나 차량 운행 여부는 별도로 확인합니다.']
                    s = replace_preparation(s,items)
            elif kind=='comparison':
                subject = '수학' if '수학' in parts[1] else '영어' if '영어' in parts[1] else None
                level = '중등' if parts[1].startswith('중학생') else next((k for k in ['초등','고등'] if parts[1].startswith(k)),None)
                assert subject and level,(subject,level)
                first, second = LEVEL_CHECKS[(level,subject)]
                cards = {''.join(x.xpath('./strong/text()')):''.join(x.xpath('./span/text()')) for x in d.xpath('//div[@class="academy-fact-card"]')}
                assert cards.get('센터') and cards.get('주소'),cards
                items = [esc(first),esc(second),f'위에 안내된 {esc(cards["센터"])}의 수업 가능 학년과 학생의 실제 학년·과목이 맞는지 확인합니다. 학습 방법을 소개한 내용만으로 개설 수업을 판단하지 않습니다.', '상담 답변은 ‘현재 어려운 내용·먼저 할 과제·다시 확인할 기준’ 세 칸으로 정리합니다. 비용과 등·하원 조건은 별도로 확인하고, 다른 수업과 비교할 때도 같은 질문을 사용합니다.']
                s = replace_preparation(s,items)
            assert s != original.decode('utf8')
            b=s.encode('utf8')
            planned[file]=b
            changes.append({'url':HOST+url,'path':file.relative_to(ROOT).as_posix(),'category':kind,'grammar':grammar,'before':hashlib.sha256(original).hexdigest(),'after':hashlib.sha256(b).hexdigest()})
        except Exception as e:
            errors.append({'url':url,'error':str(e)})
    report={'date':DATE,'pagesExamined':len(paths),'changes':len(changes),'categories':dict(collections.Counter(x['category'] for x in changes)),'grammarPages':sum(bool(x['grammar']) for x in changes),'errors':errors}
    (args.report_dir/'content-plan.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (args.report_dir/'content-changes.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    assert not errors, 'No files were written; resolve classification or preservation conflicts first.'
    assert report['grammarPages']==224, report
    assert report['categories']=={'comparison':2226,'local':742,'grade':5194} or report['categories']=={'local':742,'grade':5194,'comparison':2226},report
    if args.apply:
        for file,b in planned.items(): file.write_bytes(b)
        sitemap=(ROOT/'sitemap.xml').read_bytes().decode('utf8')
        changed={unquote(urlsplit(x['url']).path) for x in changes}
        def stamp(m):
            block=m[0];loc=re.search(r'<loc>(.*?)</loc>',block)[1]
            if unquote(urlsplit(escape_html.unescape(loc)).path) in changed:
                assert re.search(r'<lastmod>[^<]+</lastmod>',block)
                return re.sub(r'<lastmod>[^<]+</lastmod>',f'<lastmod>{DATE}</lastmod>',block)
            return block
        sitemap=re.sub(r'<url>.*?</url>',stamp,sitemap,flags=re.S)
        (ROOT/'sitemap.xml').write_bytes(sitemap.encode('utf8'))
        manifest=json.loads((ROOT/'release-public-manifest.json').read_text('utf8'))
        for name in [x['path'] for x in changes]+['sitemap.xml']:
            b=(ROOT/name).read_bytes()
            manifest['files'][name]=hashlib.sha256(b).hexdigest()
            manifest.setdefault('textSha256',{})[name]=hashlib.sha256(b.replace(b'\r\n',b'\n')).hexdigest()
        manifest['updatedAt']=DATE
        (ROOT/'release-public-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print('Applied content migration and updated only changed sitemap dates/public hashes.',flush=True)

if __name__=='__main__':main()
