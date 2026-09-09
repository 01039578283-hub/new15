"""Strict, read-only parser for owner-supplied neighborhood manuscript ZIPs.

The section/body/FAQ syntax follows generate_subject_pages.py's parsers, without
its content rewriting, image handling or page generation. Returned strings are
plain text: callers must HTML-escape them and render cases as consultation
situations, never as verified testimonials. No archive member is extracted.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata
from zipfile import BadZipFile, ZipFile


MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024
MAX_MEMBERS = 512
REQUIRED_BLOCKS = ('페이지타이틀', '메타설명', '본문', 'FAQ', '학부모후기', 'JSON-LD 요약')
_BLOCK = re.compile(r'^\[([^\]\n]+)\][ \t]*$', re.MULTILINE)
_HEADING = re.compile(r'^##[ \t]+([^\n]+?)[ \t]*$', re.MULTILINE)
_FAQ = re.compile(
    r'^Q(?P<number>\d+)\.[ \t]*(?P<question>[^\n]+)\n'
    r'A(?P<answer_number>\d*)\.[ \t]*(?P<answer>.*?)'
    r'(?=^Q\d+\.|\Z)', re.MULTILINE | re.DOTALL,
)
_CASE_NOTICE = re.compile(r'^※[^\n]*학부모 관점의 상황 예시입니다\.[ \t]*(?:\n|$)')


class ManuscriptFormatError(ValueError):
    """The supplied archive does not satisfy the plain-text source contract."""


def _normalize(value: str) -> str:
    return re.sub(r'\s+', ' ', value).strip()


def _blocks(text: str) -> dict[str, str]:
    matches = list(_BLOCK.finditer(text))
    if not matches or text[:matches[0].start()].strip():
        raise ManuscriptFormatError('Missing opening block or unexpected preamble')
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        label = match.group(1).strip()
        if label not in REQUIRED_BLOCKS:
            raise ManuscriptFormatError(f'Unknown block heading: {label}')
        if label in result:
            raise ManuscriptFormatError(f'Duplicate block heading: {label}')
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result[label] = text[match.end():end].strip()
        if not result[label]:
            raise ManuscriptFormatError(f'Empty block: {label}')
    if tuple(result) != REQUIRED_BLOCKS:
        raise ManuscriptFormatError(f'Missing or out-of-order blocks: {tuple(result)}')
    return result


def _body(text: str) -> tuple[str, list[dict]]:
    matches = list(_HEADING.finditer(text))
    if not matches:
        raise ManuscriptFormatError('Body has no ## subsection headings')
    if any(not re.match(r'^##[ \t]+', line) for line in text.splitlines()
           if re.match(r'^#{1,6}\s', line)):
        raise ManuscriptFormatError('Unsupported body heading level')
    intro = _normalize(text[:matches[0].start()])
    if not intro:
        raise ManuscriptFormatError('Missing body introduction')
    sections = []
    seen = set()
    for index, match in enumerate(matches):
        heading = _normalize(match.group(1))
        if heading in seen:
            raise ManuscriptFormatError(f'Duplicate body heading: {heading}')
        seen.add(heading)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        paragraphs = [_normalize(p) for p in re.split(r'\n\s*\n', text[match.end():end]) if p.strip()]
        if not paragraphs:
            raise ManuscriptFormatError(f'Empty body subsection: {heading}')
        sections.append({'heading': heading, 'paragraphs': paragraphs})
    return intro, sections


def _faq(text: str) -> list[dict[str, str]]:
    result = []
    cursor = 0
    questions = set()
    for index, match in enumerate(_FAQ.finditer(text), 1):
        if text[cursor:match.start()].strip():
            raise ManuscriptFormatError('Unparsed FAQ content')
        if int(match['number']) != index or match['answer_number'] not in ('', str(index)):
            raise ManuscriptFormatError('FAQ question/answer numbering mismatch')
        question, answer = _normalize(match['question']), _normalize(match['answer'])
        if not question or not answer or question in questions:
            raise ManuscriptFormatError('Empty or duplicate FAQ entry')
        if re.search(r'^A\d*\.', match['answer'], re.MULTILINE):
            raise ManuscriptFormatError('Unexpected answer marker inside FAQ answer')
        questions.add(question)
        result.append({'question': question, 'answer': answer})
        cursor = match.end()
    if not result or text[cursor:].strip():
        raise ManuscriptFormatError('Missing or malformed FAQ')
    return result


def _member_path(name: str, category: str, is_dir: bool) -> str:
    if '\\' in name or '\x00' in name or ':' in name:
        raise ManuscriptFormatError(f'Unsafe ZIP path: {name!r}')
    value = name[:-1] if is_dir and name.endswith('/') else name
    parts = value.split('/')
    if PurePosixPath(value).is_absolute() or any(p in ('', '.', '..') for p in parts):
        raise ManuscriptFormatError(f'Unsafe ZIP path: {name!r}')
    if is_dir:
        if parts != [category]:
            raise ManuscriptFormatError(f'Unexpected ZIP directory: {name}')
    elif not (len(parts) == 1 or (len(parts) == 2 and parts[0] == category)):
        raise ManuscriptFormatError(f'Unexpected ZIP member folder: {name}')
    return unicodedata.normalize('NFC', value)


def _parse(raw: bytes, member: str, subject: str, archive_sha: str) -> dict:
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ManuscriptFormatError(f'{member}: expected UTF-8 text') from exc
    if '\x00' in text:
        raise ManuscriptFormatError(f'{member}: NUL byte in text')
    text = re.sub(r'\r+\n', '\n', text).replace('\r', '\n')
    blocks = _blocks(text)
    title = _normalize(blocks['페이지타이틀'])
    suffix = f' {subject}학원'
    if len(blocks['페이지타이틀'].splitlines()) != 1 or not title.endswith(suffix):
        raise ManuscriptFormatError(f'{member}: title/subject mismatch: {title}')
    if title != PurePosixPath(member).stem:
        raise ManuscriptFormatError(f'{member}: title/filename mismatch: {title}')
    locality = title[:-len(suffix)]
    if not locality:
        raise ManuscriptFormatError(f'{member}: missing locality')
    intro, sections = _body(blocks['본문'])
    case_text = _CASE_NOTICE.sub('', blocks['학부모후기'], count=1).strip()
    cases = [_normalize(p) for p in re.split(r'\n\s*\n', case_text) if p.strip()]
    if not cases:
        raise ManuscriptFormatError(f'{member}: missing consultation situation')
    return {
        'locality': locality, 'subject': subject, 'title': title,
        'meta': _normalize(blocks['메타설명']), 'intro': intro, 'sections': sections,
        'faq': _faq(blocks['FAQ']), 'cases': cases,
        'schemaSummary': _normalize(blocks['JSON-LD 요약']),
        'sourceMember': member, 'sourceSha256': hashlib.sha256(raw).hexdigest(),
        'sourceArchiveSha256': archive_sha,
    }


def load_manuscript_archive(path: Path, subject: str) -> list[dict]:
    """Return one plain-text record per locality, sorted by locality.

    ``subject`` must be "영어" or "수학". ZIP paths, duplicate names/localities,
    block structure, FAQ numbering, and declared/actual sizes are validated.
    The known introductory case notice is removed solely because the caller
    renders a consultation-situation label; the situation prose is unchanged.
    """
    if subject not in ('영어', '수학'):
        raise ManuscriptFormatError(f'Unsupported subject: {subject}')
    path = Path(path)
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ManuscriptFormatError('Archive exceeds compressed size limit')
    archive_bytes = path.read_bytes()
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ManuscriptFormatError('Archive exceeds compressed size limit')
    archive_sha = hashlib.sha256(archive_bytes).hexdigest()
    result = []
    seen_members: set[str] = set()
    seen_localities: set[str] = set()
    try:
        with ZipFile(BytesIO(archive_bytes)) as archive:
            members = archive.infolist()
            if not members or len(members) > MAX_MEMBERS:
                raise ManuscriptFormatError('Archive member count outside limits')
            if sum(m.file_size for m in members) > MAX_UNCOMPRESSED_BYTES:
                raise ManuscriptFormatError('Archive exceeds uncompressed size limit')
            for info in members:
                member = _member_path(info.filename, subject + '학원', info.is_dir())
                if member in seen_members:
                    raise ManuscriptFormatError(f'Duplicate ZIP path: {member}')
                seen_members.add(member)
                if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                    raise ManuscriptFormatError(f'Link or encrypted ZIP member: {member}')
                if info.is_dir():
                    continue
                if not member.endswith('.txt') or not (0 < info.file_size <= MAX_MEMBER_BYTES):
                    raise ManuscriptFormatError(f'Unexpected member type or size: {member}')
                with archive.open(info) as stream:
                    raw = stream.read(MAX_MEMBER_BYTES + 1)
                if len(raw) != info.file_size or len(raw) > MAX_MEMBER_BYTES:
                    raise ManuscriptFormatError(f'Member exceeds actual size limit: {member}')
                try:
                    record = _parse(raw, member, subject, archive_sha)
                except ManuscriptFormatError as exc:
                    raise ManuscriptFormatError(f'{member}: {exc}') from exc
                locality_key = unicodedata.normalize('NFC', record['locality'])
                if locality_key in seen_localities:
                    raise ManuscriptFormatError(f'Duplicate locality: {record["locality"]}')
                seen_localities.add(locality_key)
                result.append(record)
    except BadZipFile as exc:
        raise ManuscriptFormatError(f'Invalid ZIP archive: {path.name}') from exc
    if not result:
        raise ManuscriptFormatError('Archive has no manuscript files')
    return sorted(result, key=lambda row: row['locality'])
