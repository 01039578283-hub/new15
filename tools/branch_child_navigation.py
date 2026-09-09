"""Navigation for existing grade children declared in the reviewed manifest.

Read-only: no inference from folders, source-data mutation, generation or network.
Invalid routes, duplicate children and mixed parents raise ValueError; a missing
manifest simply means that no grade children have been published locally yet.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = 'https://xn--9p4bn5e3wjn0a.com'
MANIFEST = Path('tools/data/branch-grades/pages.json')
GRADES = tuple([f'초{i}' for i in range(1, 7)] + [f'중{i}' for i in range(1, 4)] + [f'고{i}' for i in range(1, 4)])
GRADE_ORDER = {grade: i for i, grade in enumerate(GRADES)}


def _route_parts(path, depth):
    if not isinstance(path, str) or not path.startswith('/') or not path.endswith('/'):
        raise ValueError('A child-navigation route must be an absolute local directory path')
    if re.search(r'[\\?#%:<>"|*\x00-\x1f\x7f]', path):
        raise ValueError(f'Unsafe child-navigation route: {path!r}')
    parts = path[1:-1].split('/')
    if len(parts) != depth or parts[0] != '지점안내' or any(not p or p in {'.', '..'} or p != p.strip() for p in parts):
        raise ValueError(f'Unexpected child-navigation hierarchy: {path!r}')
    return parts


def _validate_record(record):
    if not isinstance(record, dict):
        raise ValueError('A grade child record must be an object')
    for key in ('path', 'parentPath', 'centerId', 'locality', 'subject', 'grade', 'title'):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError(f'Grade child is missing a nonempty {key}')
    parent = _route_parts(record['parentPath'], 4)
    child = _route_parts(record['path'], 5)
    if record['subject'] not in {'영어', '수학'} or record['grade'] not in GRADE_ORDER:
        raise ValueError('Unexpected subject or grade in child navigation')
    if parent[-1] != record['locality'] + record['subject'] + '학원':
        raise ValueError('Grade child locality/subject does not match its parent')
    if child[:-1] != parent or child[-1] != record['grade'] or record['path'] != record['parentPath'] + record['grade'] + '/':
        raise ValueError('Grade child must be an immediate child of its declared parent')


def _validated(children, *, one_parent):
    if not isinstance(children, list):
        raise ValueError('Grade children must be a list')
    paths, parent_grades, identities = set(), set(), {}
    for record in children:
        _validate_record(record)
        pair = (record['parentPath'], record['grade'])
        if record['path'] in paths or pair in parent_grades:
            raise ValueError(f'Duplicate grade child: {record["path"]}')
        paths.add(record['path'])
        parent_grades.add(pair)
        identity = (record['centerId'], record['locality'], record['subject'])
        previous = identities.setdefault(record['parentPath'], identity)
        if previous != identity:
            raise ValueError('Conflicting identities under the same grade parent')
    if one_parent and len(identities) > 1:
        raise ValueError('One child-navigation block cannot contain different parents')
    return sorted(children, key=lambda child: (child['parentPath'], GRADE_ORDER[child['grade']]))


@lru_cache(maxsize=8)
def _manifest_cached(path, mtime_ns, size):
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or 'pages' not in manifest:
        raise ValueError('Grade manifest must contain pages')
    records = _validated(manifest['pages'], one_parent=False)
    parents = {}
    for record in records:
        parents.setdefault(record['parentPath'], []).append(record)
    return parents


def load_child_pages(parent_path, *, root=None):
    """Return sorted manifest records whose immediate parent is parent_path.

    Generate grade HTML before writing its manifest and regenerating parents.
    Manifest-listed selected children must exist inside their declared parent;
    a stale/missing file is an error, not a link to an unfinished route.
    """
    _route_parts(parent_path, 4)
    root = Path(root) if root is not None else ROOT
    manifest_path = root / MANIFEST
    if not manifest_path.is_file():
        return []
    stat = manifest_path.stat()
    parents = _manifest_cached(str(manifest_path), stat.st_mtime_ns, stat.st_size)
    selected = parents.get(parent_path, [])
    parent_dir = (root / parent_path.strip('/')).resolve()
    if not parent_dir.is_relative_to(root.resolve()):
        raise ValueError('Grade parent resolves outside the site root')
    for record in selected:
        destination = root / record['path'].strip('/') / 'index.html'
        if not destination.resolve().is_relative_to(parent_dir) or not destination.is_file():
            raise ValueError(f'Grade child file is missing or outside its parent: {record["path"]}')
    return deepcopy(selected)


def child_navigation_html(children):
    """Render one #child-pages panel using existing large-link CSS classes."""
    children = _validated(children, one_parent=True)
    if not children:
        return ''
    links = ''.join('<a class="branch-child-link" href="' + escape(child['path'], quote=True)
                    + '">' + escape(child['title']) + '</a>' for child in children)
    return ('<section class="branch-panel branch-child-navigation" id="child-pages" aria-labelledby="child-pages-title">'
            '<h2 id="child-pages-title">학년별 학습 안내</h2>'
            '<nav class="branch-child-links" aria-label="학년별 학습 안내">' + links + '</nav></section>')


def child_item_list(children):
    """Return the same ordered child links as schema ItemList, or None."""
    children = _validated(children, one_parent=True)
    if not children:
        return None
    return {'@type': 'ItemList', '@id': DOMAIN + quote(children[0]['parentPath'], safe='/') + '#child-pages',
            'name': '학년별 학습 안내', 'numberOfItems': len(children),
            'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': child['title'],
                                 'url': DOMAIN + quote(child['path'], safe='/')} for i, child in enumerate(children)]}
