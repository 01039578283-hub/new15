"""Apply reviewed exact-field corrections after prepare_grade_manuscript.

No live regex rewriting, source parsing, generic summarization or fact inference
occurs here. A versioned manifest binds each correction to the source hashes,
grade, subject, locality and the complete prepared field value reviewed by a
human. ZIPs and input records are never mutated.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re

MANIFEST_PATH = Path(__file__).resolve().parent / 'data/branch-grades/editorial-revision-2026-09-10.json'
STAGE = 'reviewed-editorial'
_FIELD = re.compile(r'(?:meta|intro|sections\[\d+\]\.(?:heading|paragraphs\[\d+\])|faq\[\d+\]\.(?:question|answer)|cases\[\d+\])\Z')


class ReviewedEditorialError(ValueError):
    """The input or exact approved correction no longer matches its baseline."""


def _key(record):
    return tuple(record.get(k) for k in ('grade', 'subject', 'locality'))


def _container(record, field):
    if not _FIELD.fullmatch(field):
        raise ReviewedEditorialError(f'Unapproved editorial field: {field}')
    parts = re.findall(r'[A-Za-z]+|\d+', field)
    current = record
    try:
        for part in parts[:-1]:
            current = current[int(part) if part.isdigit() else part]
        key = int(parts[-1]) if parts[-1].isdigit() else parts[-1]
        if not isinstance(current[key], str):
            raise TypeError('Expected a text field')
        return current, key
    except (KeyError, IndexError, TypeError) as exc:
        raise ReviewedEditorialError(f'Missing editorial field: {field}') from exc


@lru_cache(maxsize=1)
def _load_manifest():
    data = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    if data.get('version') != 1 or data.get('stage') != STAGE:
        raise ReviewedEditorialError('Unsupported reviewed editorial manifest')
    indexed = {}
    for record in data['records']:
        key = _key(record)
        if None in key or key in indexed:
            raise ReviewedEditorialError(f'Duplicate or missing manuscript identity: {key}')
        seen = set()
        for edit in record['edits']:
            field = edit['field']
            if not _FIELD.fullmatch(field) or field in seen:
                raise ReviewedEditorialError(f'Duplicate or protected editorial field: {field}')
            if (not isinstance(edit['before'], str) or not isinstance(edit['after'], str)
                    or not edit['after'].strip() or edit['before'] == edit['after']):
                raise ReviewedEditorialError(f'Invalid editorial correction: {key} {field}')
            seen.add(field)
        indexed[key] = record
    return indexed


def apply_reviewed_edits(record: dict) -> tuple[dict, list[dict]]:
    """Return an independent display record and full-field, exact change logs.

    Order: source parser -> existing prepare -> this function -> reading layer.
    A second application is a no-op. Unapproved input changes fail closed rather
    than silently applying an outdated correction. Title, school data, source
    hashes, mathematical examples and other unlisted fields remain untouched.
    """
    result = deepcopy(record)
    approved = _load_manifest().get(_key(record))
    if approved is None:
        return result, []
    for name in ('sourceSha256', 'sourceArchiveSha256'):
        if record.get(name) != approved[name]:
            raise ReviewedEditorialError(f'Source hash mismatch: {_key(record)} {name}')
    changes = []
    for edit in approved['edits']:
        container, key = _container(result, edit['field'])
        value = container[key]
        if value == edit['after']:
            continue
        if value != edit['before']:
            raise ReviewedEditorialError(f'Prepared text mismatch: {_key(record)} {edit["field"]}')
        container[key] = edit['after']
        changes.append({
            'stage': STAGE, 'field': edit['field'], 'rule': 'reviewed-exact-field',
            'rules': list(edit['rules']), 'count': 1,
            'before': value, 'after': edit['after'],
            'grade': record['grade'], 'subject': record['subject'],
            'locality': record['locality'],
        })
    return result, changes
