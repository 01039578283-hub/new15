"""Exact branch-to-profile links, shared by the generator and scoped patcher."""
from functools import lru_cache
from html import escape
from pathlib import Path
import json, re

START='<!-- teacher-directory:start -->'
END='<!-- teacher-directory:end -->'

@lru_cache(maxsize=8)
def directory_links(root, mtime):
    data=json.loads((Path(root)/'tools/data/teachers/directory.json').read_text(encoding='utf-8'))
    return {'branches':{b['branchPath']:b for b in data['branches'] if b['included'] and b['branchPath']},'subjects':data.get('subjectPages',{})}

def decorate_branch_body(body, path, root):
    data=Path(root)/'tools/data/teachers/directory.json'
    if not data.exists() or not path.startswith(('/지점안내/','/과목별학원/')): return body
    pieces=path.strip('/').split('/')
    if len(pieces)<3: return body
    links=directory_links(str(Path(root).resolve()),data.stat().st_mtime_ns)
    is_subject=pieces[0]=='과목별학원'
    parent=links['subjects'].get(path.strip('/')+'/index.html') if is_subject else '/'+'/'.join(pieces[:3])+'/'
    branch=links['branches'].get(parent)
    if not branch: return body
    if START in body: return body
    name=escape(branch['name'])
    tags=list(dict.fromkeys(k for p in branch['profiles'] for k in p['keywords']))[:3]
    detail=' · '.join(escape(k) for k in tags)
    block=(START+f'<section class="teacher-context" id="teacher-team" aria-labelledby="teacher-team-title"><h2 id="teacher-team-title">{name} 선생님을 만나보세요</h2>'
        f'<p>학생의 공부를 어떻게 돕는지 선생님의 소개글에서 살펴보세요. {detail} 등 지도할 때 중점을 두는 내용을 확인할 수 있습니다.</p>'
        f'<a href="{escape(branch["path"])}">{name} 선생님 소개 보기 <span aria-hidden="true">→</span></a></section>'+END)
    if is_subject:
        block='<div class="teacher-context-wrap shell">'+block+'</div>'
        anchor=r'<section class="academy-related"[^>]*>'
    else: anchor=r'<section\b[^>]*\bid="'+('programs' if len(pieces)==3 else 'contact')+r'"[^>]*>'
    match=re.search(anchor,body)
    if not match: raise ValueError('No contextual insertion point: '+path)
    return body[:match.start()]+block+body[match.start():]
