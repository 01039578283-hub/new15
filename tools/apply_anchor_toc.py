from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUBJECT_ROOT = ROOT / "과목별학원"

TOC_START = "<!-- academy-page-toc:start -->"
TOC_END = "<!-- academy-page-toc:end -->"
TOC_BLOCK_RE = re.compile(
    rf"\s*{re.escape(TOC_START)}.*?{re.escape(TOC_END)}\s*",
    re.IGNORECASE | re.DOTALL,
)
MAIN_RE = re.compile(r"<main\b[^>]*>(?P<body>.*?)</main>", re.IGNORECASE | re.DOTALL)
H2_RE = re.compile(
    r"<h2\b(?P<attrs>[^>]*)>(?P<body>.*?)</h2\s*>",
    re.IGNORECASE | re.DOTALL,
)
ID_ATTR_RE = re.compile(
    r"\bid\s*=\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)')",
    re.IGNORECASE,
)
ALL_ID_RE = re.compile(
    r"\bid\s*=\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)')",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
HERO_RE = re.compile(
    r"<header\b(?=[^>]*\bclass\s*=\s*['\"][^'\"]*\bacademy-hero\b[^'\"]*['\"])[^>]*>.*?</header\s*>",
    re.IGNORECASE | re.DOTALL,
)
MEDIA_RE = re.compile(
    r"<section\b(?=[^>]*\bclass\s*=\s*['\"][^'\"]*\bacademy-media-section\b[^'\"]*['\"])[^>]*>",
    re.IGNORECASE | re.DOTALL,
)


class TocError(ValueError):
    """Raised when a locality page does not match the expected page contract."""


@dataclass(frozen=True)
class Heading:
    label: str
    target_id: str


def detail_pages(root: Path) -> list[Path]:
    """Return only category/locality detail pages; category hubs never match."""
    subject_root = root / "과목별학원"
    return sorted(
        (
            path
            for path in subject_root.glob("*/*/index.html")
            if path.is_file()
        ),
        key=lambda path: path.as_posix(),
    )


def attribute_value(attrs: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(attrs)
    if not match:
        return ""
    return html.unescape(match.group("double") or match.group("single") or "").strip()


def visible_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def unique_id(base: str, used_ids: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def add_heading_ids(main_body: str, used_ids: set[str], page: Path) -> tuple[str, list[Heading]]:
    headings: list[Heading] = []

    def replace(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        body = match.group("body")
        label = visible_text(body)
        if not label:
            raise TocError(f"{page}: empty H2 label")

        target_id = attribute_value(attrs, ID_ATTR_RE)
        if not target_id:
            target_id = unique_id(f"section-{len(headings) + 1}", used_ids)
            attrs = f'{attrs} id="{html.escape(target_id, quote=True)}"'

        headings.append(Heading(label=label, target_id=target_id))
        return f"<h2{attrs}>{body}</h2>"

    updated = H2_RE.sub(replace, main_body)
    if len(headings) != 12:
        raise TocError(f"{page}: expected 12 content H2 headings, found {len(headings)}")
    if len({heading.target_id for heading in headings}) != len(headings):
        raise TocError(f"{page}: duplicate H2 target ids")
    return updated, headings


def render_toc(headings: list[Heading], heading_id: str) -> str:
    links = "\n".join(
        "        <li><a href=\"#{target}\">{label}</a></li>".format(
            target=html.escape(heading.target_id, quote=True),
            label=html.escape(heading.label),
        )
        for heading in headings
    )
    return f'''{TOC_START}
    <nav class="academy-page-toc" aria-label="페이지 목차" aria-labelledby="{html.escape(heading_id, quote=True)}">
      <div class="academy-page-toc-inner">
        <h2 id="{html.escape(heading_id, quote=True)}">페이지 목차</h2>
        <ol>
{links}
        </ol>
      </div>
    </nav>
    {TOC_END}'''


def transform(source: str, page: Path) -> tuple[str, list[Heading]]:
    without_toc = TOC_BLOCK_RE.sub("\n\n", source)
    if TOC_START in without_toc or TOC_END in without_toc:
        raise TocError(f"{page}: incomplete or duplicate TOC marker")

    main_match = MAIN_RE.search(without_toc)
    if not main_match:
        raise TocError(f"{page}: main element not found")
    main_body = main_match.group("body")

    existing_ids = [
        html.unescape(match.group("double") or match.group("single") or "").strip()
        for match in ALL_ID_RE.finditer(without_toc)
    ]
    if "" in existing_ids:
        raise TocError(f"{page}: empty id attribute")
    if len(existing_ids) != len(set(existing_ids)):
        raise TocError(f"{page}: duplicate existing ids")
    used_ids = set(existing_ids)

    updated_main, headings = add_heading_ids(main_body, used_ids, page)
    toc_heading_id = unique_id("academy-page-toc-heading", used_ids)
    without_toc = (
        without_toc[: main_match.start("body")]
        + updated_main
        + without_toc[main_match.end("body") :]
    )

    main_match = MAIN_RE.search(without_toc)
    assert main_match is not None
    main_body = main_match.group("body")
    hero_matches = list(HERO_RE.finditer(main_body))
    media_matches = list(MEDIA_RE.finditer(main_body))
    if len(hero_matches) != 1 or len(media_matches) != 1:
        raise TocError(
            f"{page}: expected one academy hero and one media section, "
            f"found {len(hero_matches)} and {len(media_matches)}"
        )
    hero = hero_matches[0]
    media = media_matches[0]
    if hero.end() > media.start() or main_body[hero.end() : media.start()].strip():
        raise TocError(f"{page}: hero and media section are not adjacent")

    toc = render_toc(headings, toc_heading_id)
    updated_main = main_body[: hero.end()] + "\n\n    " + toc + "\n\n    " + main_body[media.start() :]
    output = (
        without_toc[: main_match.start("body")]
        + updated_main
        + without_toc[main_match.end("body") :]
    )
    return output, headings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add an accessible, idempotent 12-link anchor TOC to subject locality pages."
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="Site repository root")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; fail if any detail page is not already in canonical TOC form",
    )
    parser.add_argument("--json-out", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    root = args.root.resolve()
    pages = detail_pages(root)
    if not pages:
        print(f"No locality detail pages found under {root / '과목별학원'}", file=sys.stderr)
        return 1

    pending: dict[Path, str] = {}
    errors: list[str] = []
    heading_counts: list[int] = []
    for page in pages:
        try:
            source = page.read_text(encoding="utf-8")
            output, headings = transform(source, page)
            heading_counts.append(len(headings))
            if output != source:
                pending[page] = output
        except (OSError, UnicodeError, TocError) as exc:
            errors.append(str(exc))

    if not errors and not args.check:
        for page, output in pending.items():
            page.write_text(output, encoding="utf-8")

    categories = sorted({page.parent.parent.name for page in pages})
    report = {
        "root": str(root),
        "categories": categories,
        "category_count": len(categories),
        "detail_pages": len(pages),
        "changed_pages": len(pending),
        "unchanged_pages": len(pages) - len(pending),
        "content_h2_min": min(heading_counts) if heading_counts else 0,
        "content_h2_max": max(heading_counts) if heading_counts else 0,
        "check_mode": args.check,
        "errors": errors,
    }
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if errors:
        return 1
    if args.check and pending:
        print(f"TOC canonical-form check failed: {len(pending)} page(s) would change.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
