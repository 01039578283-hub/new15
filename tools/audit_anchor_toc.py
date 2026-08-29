from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOC_START = "<!-- academy-page-toc:start -->"
TOC_END = "<!-- academy-page-toc:end -->"
TOC_RE = re.compile(
    rf"{re.escape(TOC_START)}(?P<body>.*?){re.escape(TOC_END)}",
    re.IGNORECASE | re.DOTALL,
)
MAIN_RE = re.compile(r"<main\b[^>]*>(?P<body>.*?)</main>", re.IGNORECASE | re.DOTALL)
H2_RE = re.compile(r"<h2\b(?P<attrs>[^>]*)>(?P<body>.*?)</h2\s*>", re.IGNORECASE | re.DOTALL)
ID_ATTR_RE = re.compile(r"\bid\s*=\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)')", re.IGNORECASE)
ALL_ID_RE = re.compile(r"\bid\s*=\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)')", re.IGNORECASE)
HREF_RE = re.compile(r"\bhref\s*=\s*(?:\"#(?P<double>[^\"]+)\"|'#(?P<single>[^']+)')", re.IGNORECASE)
ANCHOR_RE = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a\s*>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
NAV_RE = re.compile(
    r"<nav\b(?=[^>]*\bclass\s*=\s*['\"][^'\"]*\bacademy-page-toc\b[^'\"]*['\"])(?P<attrs>[^>]*)>(?P<body>.*?)</nav\s*>",
    re.IGNORECASE | re.DOTALL,
)
HERO_RE = re.compile(
    r"<header\b(?=[^>]*\bclass\s*=\s*['\"][^'\"]*\bacademy-hero\b[^'\"]*['\"])[^>]*>.*?</header\s*>",
    re.IGNORECASE | re.DOTALL,
)
MEDIA_RE = re.compile(
    r"<section\b(?=[^>]*\bclass\s*=\s*['\"][^'\"]*\bacademy-media-section\b[^'\"]*['\"])[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
ARIA_LABELLEDBY_RE = re.compile(
    r"\baria-labelledby\s*=\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)')",
    re.IGNORECASE,
)
ARIA_LABEL_RE = re.compile(
    r"\baria-label\s*=\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)')",
    re.IGNORECASE,
)


def detail_pages(root: Path) -> list[Path]:
    return sorted(
        (path for path in (root / "과목별학원").glob("*/*/index.html") if path.is_file()),
        key=lambda path: path.as_posix(),
    )


def attr(match: re.Match[str] | None) -> str:
    if not match:
        return ""
    return html.unescape(match.group("double") or match.group("single") or "").strip()


def plain_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def audit_css(root: Path) -> list[str]:
    path = root / "assets" / "site.css"
    try:
        css = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: {exc}"]
    requirements = {
        "TOC base selector": r"\.academy-page-toc\s*\{",
        "two-column desktop grid": r"\.academy-page-toc\s+ol\s*\{[^}]*grid-template-columns\s*:\s*repeat\(2\s*,",
        "56px tap target": r"\.academy-page-toc\s+a\s*\{[^}]*min-height\s*:\s*56px\s*;",
        "focus-visible treatment": r"\.academy-page-toc\s+a:focus-visible\s*\{",
        "sticky-header scroll margin": r"\.academy-page\s+h2\[id\]\s*\{[^}]*scroll-margin-top\s*:",
        "mobile one-column grid": r"@media\s*\(max-width\s*:\s*720px\)[\s\S]*?\.academy-page-toc\s+ol\s*\{[^}]*grid-template-columns\s*:\s*1fr\s*;",
        "reduced-motion rule": r"@media\s*\(prefers-reduced-motion\s*:\s*reduce\)[\s\S]*?\.academy-page-toc\s+a\s*\{",
    }
    return [f"{path}: missing {name}" for name, pattern in requirements.items() if not re.search(pattern, css, re.IGNORECASE)]


def audit_page(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"{path}: {exc}"]

    toc_matches = list(TOC_RE.finditer(source))
    if len(toc_matches) != 1:
        return [f"{path}: expected exactly one marked TOC, found {len(toc_matches)}"]
    toc_match = toc_matches[0]
    nav_matches = list(NAV_RE.finditer(toc_match.group("body")))
    if len(nav_matches) != 1:
        return [f"{path}: expected exactly one TOC nav, found {len(nav_matches)}"]
    nav = nav_matches[0]

    main_match = MAIN_RE.search(source)
    if not main_match:
        return [f"{path}: main element missing"]
    hero_matches = list(HERO_RE.finditer(main_match.group("body")))
    media_matches = list(MEDIA_RE.finditer(main_match.group("body")))
    if len(hero_matches) != 1 or len(media_matches) != 1:
        errors.append(f"{path}: expected one hero and one media section")
    else:
        main_start = main_match.start("body")
        hero_end = main_start + hero_matches[0].end()
        media_start = main_start + media_matches[0].start()
        if not (hero_end < toc_match.start() < toc_match.end() < media_start):
            errors.append(f"{path}: TOC is not between hero and media section")
        elif source[hero_end : toc_match.start()].strip() or source[toc_match.end() : media_start].strip():
            errors.append(f"{path}: TOC is not the direct block between hero and media section")

    source_without_toc = source[: toc_match.start()] + source[toc_match.end() :]
    main_without_toc = MAIN_RE.search(source_without_toc)
    if not main_without_toc:
        return errors + [f"{path}: main element missing after TOC removal"]
    headings: list[tuple[str, str]] = []
    for heading_match in H2_RE.finditer(main_without_toc.group("body")):
        target_id = attr(ID_ATTR_RE.search(heading_match.group("attrs")))
        label = plain_text(heading_match.group("body"))
        headings.append((target_id, label))
    if len(headings) != 12:
        errors.append(f"{path}: expected 12 content H2 headings, found {len(headings)}")
    if any(not target_id for target_id, _ in headings):
        errors.append(f"{path}: one or more content H2 headings lack ids")
    if any(not label for _, label in headings):
        errors.append(f"{path}: one or more content H2 headings have empty labels")
    heading_ids = [target_id for target_id, _ in headings]
    if len(heading_ids) != len(set(heading_ids)):
        errors.append(f"{path}: content H2 target ids are not unique")
    for semantic_id in ("summary-title", "facts-title", "article-title", "faq-title", "case-title"):
        if semantic_id not in heading_ids:
            errors.append(f"{path}: preserved semantic heading id missing: {semantic_id}")

    if attr(ARIA_LABEL_RE.search(nav.group("attrs"))) != "페이지 목차":
        errors.append(f"{path}: TOC nav lacks the expected aria-label")
    labelledby = attr(ARIA_LABELLEDBY_RE.search(nav.group("attrs")))
    if not labelledby:
        errors.append(f"{path}: TOC nav lacks aria-labelledby")
    toc_heading_matches = list(H2_RE.finditer(nav.group("body")))
    if len(toc_heading_matches) != 1:
        errors.append(f"{path}: TOC must have one H2 heading")
    else:
        toc_heading_id = attr(ID_ATTR_RE.search(toc_heading_matches[0].group("attrs")))
        if labelledby != toc_heading_id:
            errors.append(f"{path}: aria-labelledby does not reference the TOC heading")
        if plain_text(toc_heading_matches[0].group("body")) != "페이지 목차":
            errors.append(f"{path}: unexpected TOC heading label")

    links: list[tuple[str, str]] = []
    for anchor_match in ANCHOR_RE.finditer(nav.group("body")):
        target_id = attr(HREF_RE.search(anchor_match.group("attrs")))
        links.append((target_id, plain_text(anchor_match.group("body"))))
    if links != headings:
        errors.append(f"{path}: TOC href/id/label/order does not exactly match content H2 order")

    document_ids = [attr(match) for match in ALL_ID_RE.finditer(source)]
    duplicate_ids = sorted(value for value, count in Counter(document_ids).items() if value and count > 1)
    if "" in document_ids:
        errors.append(f"{path}: empty document id")
    if duplicate_ids:
        errors.append(f"{path}: duplicate document ids: {', '.join(duplicate_ids[:5])}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit exact anchor-TOC integrity on all subject locality pages.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Site repository root")
    parser.add_argument("--expected-per-category", type=int, default=371)
    parser.add_argument("--json-out", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    root = args.root.resolve()
    pages = detail_pages(root)
    errors = audit_css(root)

    by_category: dict[str, int] = defaultdict(int)
    for page in pages:
        by_category[page.parent.parent.name] += 1
        errors.extend(audit_page(page))

    if not pages:
        errors.append(f"{root / '과목별학원'}: no locality detail pages found")
    for category, count in sorted(by_category.items()):
        if count != args.expected_per_category:
            errors.append(
                f"{root / '과목별학원' / category}: expected {args.expected_per_category} detail pages, found {count}"
            )

    hub_paths = [root / "과목별학원" / "index.html"] + sorted((root / "과목별학원").glob("*/index.html"))
    contaminated_hubs: list[str] = []
    for hub in hub_paths:
        if hub.is_file() and "academy-page-toc" in hub.read_text(encoding="utf-8"):
            contaminated_hubs.append(str(hub))
    if contaminated_hubs:
        errors.append("TOC must not appear on hubs: " + ", ".join(contaminated_hubs))

    report = {
        "root": str(root),
        "categories": dict(sorted(by_category.items())),
        "category_count": len(by_category),
        "detail_pages": len(pages),
        "expected_per_category": args.expected_per_category,
        "hub_pages_checked": len([path for path in hub_paths if path.is_file()]),
        "errors": errors,
        "passed": not errors,
    }
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
