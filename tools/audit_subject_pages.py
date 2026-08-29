from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from generate_subject_pages import (
    CATEGORIES,
    DOMAIN,
    IGNORED_PUBLIC_DIRS,
    REPRESENTATIVE_CATEGORY_OFFSET,
    REPRESENTATIVE_MANIFEST,
    REPRESENTATIVE_POOL_SIZE,
    ROOT,
    SITE_NAME,
    all_schools_for,
    absolute_url,
    load_csv,
    schools_for,
)


REQUIRED_SCHEMA_TYPES = {
    "EducationalOrganization",
    "LocalBusiness",
    "WebPage",
    "BreadcrumbList",
    "Article",
    "Service",
    "FAQPage",
    "ItemList",
}
FORBIDDEN_SCHEMA_TYPES = {"Review", "AggregateRating"}
SCRIPT_RE = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
ATTR_RE = re.compile(r'\b(?:href|src)=["\']([^"\']+)["\']', re.IGNORECASE)
IMG_RE = re.compile(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
REPRESENTATIVE_IMG_RE = re.compile(
    r'<img\b(?=[^>]*\bclass=["\'][^"\']*\bacademy-representative-image\b[^"\']*["\'])[^>]*>',
    re.IGNORECASE,
)
REPRESENTATIVE_BEFORE_MAIN_RE = re.compile(
    r'<img\b(?=[^>]*\bclass=["\'][^"\']*\bacademy-representative-image\b[^"\']*["\'])[^>]*>'
    r'\s*<figure\b(?=[^>]*\bclass=["\'][^"\']*\bacademy-main-media\b[^"\']*["\'])[^>]*>',
    re.IGNORECASE,
)
MAP_CARD_IMG_RE = re.compile(
    r'<figure\b(?=[^>]*\bclass=["\'][^"\']*\bacademy-map-card\b[^"\']*["\'])[^>]*>'
    r'.*?(<img\b[^>]*>)',
    re.IGNORECASE | re.DOTALL,
)
MAIN_MEDIA_IMG_RE = re.compile(
    r'<figure\b(?=[^>]*\bclass=["\'][^"\']*\bacademy-main-media\b[^"\']*["\'])[^>]*>'
    r'.*?(<img\b[^>]*>)',
    re.IGNORECASE | re.DOTALL,
)
REPRESENTATIVE_ASSET_DIR = (ROOT / "assets" / "representative").resolve()


def plain_text(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", value))).strip()


def normalize_url(value: str) -> str:
    return html.unescape(value).strip()


def tag_attribute(tag: str, name: str) -> str:
    match = re.search(
        rf'\b{re.escape(name)}\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
        tag,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    return html.unescape(next(value for value in match.groups() if value is not None)).strip()


def schema_types(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        node_type = value.get("@type")
        if isinstance(node_type, str):
            found.add(node_type)
        elif isinstance(node_type, list):
            found.update(item for item in node_type if isinstance(item, str))
        for child in value.values():
            found.update(schema_types(child))
    elif isinstance(value, list):
        for child in value:
            found.update(schema_types(child))
    return found


def graph_node(data: object, wanted: str) -> dict:
    if not isinstance(data, dict):
        return {}
    graph = data.get("@graph", [])
    if not isinstance(graph, list):
        graph = [data]
    for node in graph:
        if not isinstance(node, dict):
            continue
        node_type = node.get("@type")
        if node_type == wanted or isinstance(node_type, list) and wanted in node_type:
            return node
    return {}


def parse_json_ld(source: str, slug: str, errors: list[str]) -> list[object]:
    blocks = SCRIPT_RE.findall(source)
    if not blocks:
        errors.append(f"jsonld-missing:{slug}")
        return []
    parsed: list[object] = []
    for index, block in enumerate(blocks, 1):
        try:
            parsed.append(json.loads(html.unescape(block).strip()))
        except json.JSONDecodeError as exc:
            errors.append(f"jsonld-invalid:{slug}:block-{index}:{exc.msg}")
    return parsed


def visible_faq(source: str) -> list[tuple[str, str]]:
    section = re.search(
        r'<section\b[^>]*class=["\'][^"\']*\bacademy-faq\b[^"\']*["\'][^>]*>'
        r"(.*?)</section>",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not section:
        return []
    return [
        (plain_text(question), plain_text(answer))
        for question, answer in re.findall(
            r"<details\b[^>]*>\s*<summary\b[^>]*>(.*?)</summary>\s*"
            r"<p\b[^>]*>(.*?)</p>\s*</details>",
            section.group(1),
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]


def schema_faq(data_blocks: list[object]) -> list[tuple[str, str]]:
    for data in data_blocks:
        node = graph_node(data, "FAQPage")
        if not node:
            continue
        result: list[tuple[str, str]] = []
        for item in node.get("mainEntity", []):
            if not isinstance(item, dict):
                continue
            answer = item.get("acceptedAnswer", {})
            if not isinstance(answer, dict):
                answer = {}
            result.append(
                (
                    plain_text(str(item.get("name", ""))),
                    plain_text(str(answer.get("text", ""))),
                )
            )
        return result
    return []


def supplied_school_name_present(text: str, name: str) -> bool:
    """Match a supplied school name without confusing it with an address."""
    return bool(re.search(
        re.escape(name) + r"(?=$|학교|[\s,·/()\[\]{}'\"“”‘’.:;!?])",
        text,
    ))


def visible_school_tags(source: str) -> list[str]:
    section = re.search(
        r'<div\b[^>]*class=["\'][^"\']*\bacademy-school-tags\b[^"\']*["\'][^>]*>'
        r"(.*?)</div>",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not section:
        return []
    return [
        plain_text(value)
        for value in re.findall(r"<span\b[^>]*>(.*?)</span>", section.group(1), re.IGNORECASE | re.DOTALL)
    ]


def article_school_mentions(data_blocks: list[object]) -> list[str]:
    for data in data_blocks:
        article = graph_node(data, "Article")
        if not article:
            continue
        names: list[str] = []
        for mention in article.get("mentions", []):
            if isinstance(mention, dict) and mention.get("@type") == "School":
                name = plain_text(str(mention.get("name", "")))
                if name:
                    names.append(name)
        return names
    return []


def local_target(page: Path, value: str) -> Path | None:
    value = normalize_url(value)
    if not value or value.startswith(("#", "tel:", "mailto:", "data:", "javascript:")):
        return None

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        domain = urlparse(DOMAIN)
        if parsed.netloc != domain.netloc:
            return None
        raw_path = unquote(parsed.path)
        candidate = ROOT / raw_path.lstrip("/")
    elif parsed.scheme or value.startswith("//"):
        return None
    else:
        raw_path = unquote(parsed.path)
        candidate = ROOT / raw_path.lstrip("/") if raw_path.startswith("/") else page.parent / raw_path

    if not raw_path or raw_path.endswith("/"):
        candidate = candidate / "index.html"
    return candidate.resolve()


def article_text(source: str) -> str:
    match = re.search(
        r'<article\b[^>]*class=["\'][^"\']*\bacademy-article\b[^"\']*["\'][^>]*>'
        r"(.*?)</article>",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return plain_text(match.group(1)) if match else ""


def masked_shingles(text: str, locality: str, title: str, size: int = 5) -> set[str]:
    masked = text.replace(title, " 페이지제목 ").replace(locality, " 지역명 ")
    masked = re.sub(r"\d+(?:[.,]\d+)?", " 수치 ", masked)
    tokens = re.findall(r"[가-힣A-Za-z]+", masked)
    return {
        "\x1f".join(tokens[index : index + size])
        for index in range(max(0, len(tokens) - size + 1))
    }


def similarity_worker(job: tuple[str, list[tuple[str, str, str, str]]]) -> tuple[str, dict]:
    category, records = job
    sets = [masked_shingles(text, locality, title) for _, locality, title, text in records]
    best = [0.0] * len(sets)
    best_peer = [-1] * len(sets)
    pairs_over_075 = 0

    for left_index, left in enumerate(sets):
        for right_index in range(left_index + 1, len(sets)):
            right = sets[right_index]
            intersection = len(left.intersection(right))
            union = len(left) + len(right) - intersection
            score = intersection / union if union else 1.0
            if score >= 0.75:
                pairs_over_075 += 1
            if score > best[left_index]:
                best[left_index] = score
                best_peer[left_index] = right_index
            if score > best[right_index]:
                best[right_index] = score
                best_peer[right_index] = left_index

    hashes = [hashlib.sha256(text.encode("utf-8")).hexdigest() for _, _, _, text in records]
    ordered = sorted(best)
    worst_index = max(range(len(best)), key=best.__getitem__) if best else 0
    peer_index = best_peer[worst_index] if best else -1
    result = {
        "pages": len(records),
        "unique_article_texts": len(set(hashes)),
        "exact_duplicate_articles": len(records) - len(set(hashes)),
        "masked_5_shingle_max_similarity": {
            "average": round(statistics.mean(best), 4) if best else 0.0,
            "median": round(statistics.median(best), 4) if best else 0.0,
            "p95": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 4) if ordered else 0.0,
            "worst": round(best[worst_index], 4) if best else 0.0,
            "worst_pair": (
                [records[worst_index][0], records[peer_index][0]]
                if peer_index >= 0
                else []
            ),
            "pairs_at_or_above_0_75": pairs_over_075,
        },
    }
    return category, result


def audit_category(
    config: dict[str, str], center_by_locality: dict[str, dict[str, str]],
) -> tuple[dict, list[tuple[str, str, str, str]], set[str], dict[str, str]]:
    category_slug = config["slug"]
    category_root = ROOT / "과목별학원" / category_slug
    errors: list[str] = []
    pages = sorted(category_root.glob("*/index.html")) if category_root.is_dir() else []
    if len(pages) != 371:
        errors.append(f"page-count:{category_slug}:expected-371:actual-{len(pages)}")

    titles: list[str] = []
    metas: list[str] = []
    records: list[tuple[str, str, str, str]] = []
    expected_urls: set[str] = {absolute_url("과목별학원", category_slug)}
    checked_links = 0
    checked_images = 0
    representative_assignments: dict[str, str] = {}
    school_claim_pages_checked = 0

    for page in pages:
        slug = page.parent.name
        source = page.read_text(encoding="utf-8")
        expected_url = absolute_url("과목별학원", category_slug, slug)
        expected_urls.add(expected_url)

        h1_matches = re.findall(r"<h1\b[^>]*>(.*?)</h1>", source, flags=re.IGNORECASE | re.DOTALL)
        if len(h1_matches) != 1:
            errors.append(f"h1-count:{category_slug}/{slug}:{len(h1_matches)}")
            title = ""
        else:
            title = plain_text(h1_matches[0])

        title_match = re.search(r"<title>(.*?)</title>", source, flags=re.IGNORECASE | re.DOTALL)
        meta_match = re.search(
            r'<meta\b[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\'][^>]*>',
            source,
            flags=re.IGNORECASE,
        )
        canonical_match = re.search(
            r'<link\b[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\'][^>]*>',
            source,
            flags=re.IGNORECASE,
        )
        og_match = re.search(
            r'<meta\b[^>]*property=["\']og:url["\'][^>]*content=["\']([^"\']+)["\'][^>]*>',
            source,
            flags=re.IGNORECASE,
        )

        if not title_match:
            errors.append(f"title-missing:{category_slug}/{slug}")
        else:
            document_title = plain_text(title_match.group(1))
            titles.append(document_title)
            if title and document_title != f"{title} | {SITE_NAME}":
                errors.append(f"title-mismatch:{category_slug}/{slug}")
        if not meta_match or not plain_text(meta_match.group(1)):
            errors.append(f"meta-missing:{category_slug}/{slug}")
            meta = ""
        else:
            meta = plain_text(meta_match.group(1))
            metas.append(meta)
            if not 70 <= len(meta) <= 100:
                errors.append(
                    f"meta-length:{category_slug}/{slug}:expected-70-100:actual-{len(meta)}"
                )
        if not canonical_match:
            errors.append(f"canonical-missing:{category_slug}/{slug}")
        elif normalize_url(canonical_match.group(1)) != expected_url:
            errors.append(f"canonical-mismatch:{category_slug}/{slug}")
        if not og_match:
            errors.append(f"og-url-missing:{category_slug}/{slug}")
        elif normalize_url(og_match.group(1)) != expected_url:
            errors.append(f"og-url-mismatch:{category_slug}/{slug}")

        blocks = parse_json_ld(source, f"{category_slug}/{slug}", errors)
        present_types: set[str] = set()
        for block in blocks:
            present_types.update(schema_types(block))
        missing_types = REQUIRED_SCHEMA_TYPES - present_types
        if missing_types:
            errors.append(f"schema-missing:{category_slug}/{slug}:{','.join(sorted(missing_types))}")
        forbidden_types = FORBIDDEN_SCHEMA_TYPES & present_types
        if forbidden_types:
            errors.append(f"schema-forbidden:{category_slug}/{slug}:{','.join(sorted(forbidden_types))}")

        row = center_by_locality.get(slug)
        if row is None:
            errors.append(f"center-row-missing:{category_slug}/{slug}")
        else:
            school_claim_pages_checked += 1
            allowed_schools = schools_for(row, config["school_field"])
            disallowed_schools = [
                name for name in all_schools_for(row) if name not in set(allowed_schools)
            ]
            visible_source = re.sub(
                r"<script\b.*?</script>", " ", source,
                flags=re.IGNORECASE | re.DOTALL,
            )
            wrong_names = [
                name for name in disallowed_schools
                if supplied_school_name_present(visible_source, name)
            ]
            if wrong_names:
                errors.append(
                    f"school-claim-out-of-scope:{category_slug}/{slug}:{','.join(wrong_names)}"
                )
            visible_schools = visible_school_tags(source)
            if visible_schools != allowed_schools:
                errors.append(
                    f"school-tags-mismatch:{category_slug}/{slug}:"
                    f"expected-{allowed_schools}:actual-{visible_schools}"
                )
            structured_schools = article_school_mentions(blocks)
            if structured_schools != allowed_schools:
                errors.append(
                    f"school-schema-mismatch:{category_slug}/{slug}:"
                    f"expected-{allowed_schools}:actual-{structured_schools}"
                )

        screen_faq = visible_faq(source)
        structured_faq = schema_faq(blocks)
        if not screen_faq:
            errors.append(f"faq-screen-missing:{category_slug}/{slug}")
        elif screen_faq != structured_faq:
            errors.append(f"faq-mismatch:{category_slug}/{slug}")

        images = IMG_RE.findall(source)
        if not images:
            errors.append(f"image-missing:{category_slug}/{slug}")
        checked_images += len(images)

        map_match = MAP_CARD_IMG_RE.search(source)
        if not map_match:
            errors.append(f"map-image-missing:{category_slug}/{slug}")
        else:
            map_tag = map_match.group(1)
            width = tag_attribute(map_tag, "width")
            height = tag_attribute(map_tag, "height")
            if not width.isdigit() or not height.isdigit() or int(width) <= 0 or int(height) <= 0:
                errors.append(
                    f"map-image-dimensions:{category_slug}/{slug}:{width}x{height}"
                )

        main_media_match = MAIN_MEDIA_IMG_RE.search(source)
        if not main_media_match:
            errors.append(f"main-media-missing:{category_slug}/{slug}")
        else:
            main_media_tag = main_media_match.group(1)
            width = tag_attribute(main_media_tag, "width")
            height = tag_attribute(main_media_tag, "height")
            srcset = tag_attribute(main_media_tag, "srcset")
            candidates = [item.strip().split()[0] for item in srcset.split(",") if item.strip()]
            if not width.isdigit() or not height.isdigit() or int(width) <= 0 or int(height) <= 0:
                errors.append(
                    f"main-media-dimensions:{category_slug}/{slug}:{width}x{height}"
                )
            if tag_attribute(main_media_tag, "loading") != "lazy":
                errors.append(f"main-media-loading:{category_slug}/{slug}")
            if tag_attribute(main_media_tag, "decoding") != "async":
                errors.append(f"main-media-decoding:{category_slug}/{slug}")
            if len(candidates) != 3 or not any("-480.webp" in value for value in candidates) or not any("-720.webp" in value for value in candidates):
                errors.append(f"main-media-srcset:{category_slug}/{slug}:{srcset}")
            for candidate in candidates:
                target = local_target(page, candidate)
                checked_links += 1
                if target is None or not target.is_file() or target.stat().st_size == 0:
                    errors.append(
                        f"main-media-srcset-resource:{category_slug}/{slug}:{candidate}"
                    )

        representative_tags = REPRESENTATIVE_IMG_RE.findall(source)
        if len(representative_tags) != 1:
            errors.append(
                f"representative-count:{category_slug}/{slug}:expected-1:actual-{len(representative_tags)}"
            )
        else:
            representative_tag = representative_tags[0]
            representative_src = tag_attribute(representative_tag, "src")
            representative_alt = tag_attribute(representative_tag, "alt")
            representative_style = tag_attribute(representative_tag, "style")
            if representative_alt != f"{title} 대표":
                errors.append(f"representative-alt:{category_slug}/{slug}:{representative_alt}")
            if representative_style != "display:none;":
                errors.append(f"representative-style:{category_slug}/{slug}:{representative_style}")
            if not REPRESENTATIVE_BEFORE_MAIN_RE.search(source):
                errors.append(f"representative-position:{category_slug}/{slug}")

            representative_target = local_target(page, representative_src)
            if representative_target is None:
                errors.append(f"representative-src-invalid:{category_slug}/{slug}:{representative_src}")
            else:
                try:
                    representative_target.relative_to(REPRESENTATIVE_ASSET_DIR)
                except ValueError:
                    errors.append(f"representative-src-outside:{category_slug}/{slug}:{representative_src}")
                else:
                    if representative_target.suffix.lower() != ".gif":
                        errors.append(f"representative-format:{category_slug}/{slug}:{representative_src}")
                    if not representative_target.is_file() or representative_target.stat().st_size == 0:
                        errors.append(f"representative-file-missing:{category_slug}/{slug}:{representative_src}")
                    representative_assignments[slug] = representative_target.name

        for value in ATTR_RE.findall(source):
            target = local_target(page, value)
            if target is None:
                continue
            checked_links += 1
            if not target.exists():
                errors.append(f"local-resource-missing:{category_slug}/{slug}:{value}")

        text = article_text(source)
        if not text:
            errors.append(f"article-missing:{category_slug}/{slug}")
        locality = title[: -len(config["label"])].strip() if title.endswith(config["label"]) else slug
        records.append((slug, locality, title, text))

    representative_counts = Counter(representative_assignments.values())
    if len(representative_assignments) == len(pages) and len(representative_counts) != len(pages):
        errors.append(
            f"representative-category-duplicates:{category_slug}:"
            f"unique-{len(representative_counts)}:pages-{len(pages)}"
        )

    report = {
        "category": config["label"],
        "slug": category_slug,
        "pages": len(pages),
        "errors": len(errors),
        "error_sample": errors[:30],
        "unique_titles": len(set(titles)),
        "unique_meta_descriptions": len(set(metas)),
        "meta_length": {
            "min": min(map(len, metas)) if metas else 0,
            "max": max(map(len, metas)) if metas else 0,
            "average": round(statistics.mean(map(len, metas)), 1) if metas else 0.0,
        },
        "checked_local_references": checked_links,
        "checked_images": checked_images,
        "representative_images": {
            "assigned": len(representative_assignments),
            "unique": len(representative_counts),
        },
        "school_claim_pages_checked": school_claim_pages_checked,
    }
    return report, records, expected_urls, representative_assignments


def sitemap_audit(expected_urls: set[str]) -> tuple[dict, list[str]]:
    path = ROOT / "sitemap.xml"
    errors: list[str] = []
    if not path.is_file():
        return {"exists": False, "urls": 0, "unique_urls": 0, "missing_expected": len(expected_urls)}, ["sitemap-missing"]
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        return {"exists": True, "urls": 0, "unique_urls": 0, "missing_expected": len(expected_urls)}, [f"sitemap-invalid:{exc}"]

    root = tree.getroot()
    urls = [normalize_url(node.text or "") for node in root.findall("{*}url/{*}loc")]
    duplicates = sorted({url for url in urls if urls.count(url) > 1})
    missing = sorted(expected_urls - set(urls))
    public_urls: set[str] = set()
    for page in ROOT.rglob("index.html"):
        relative = page.relative_to(ROOT)
        if any(part in IGNORED_PUBLIC_DIRS for part in relative.parts):
            continue
        route_parts = relative.parts[:-1]
        public_urls.add(
            DOMAIN + ("/" if not route_parts else quote("/" + "/".join(route_parts) + "/", safe="/"))
        )
    missing_public = sorted(public_urls - set(urls))
    extra = sorted(set(urls) - public_urls)
    if duplicates:
        errors.append(f"sitemap-duplicate-urls:{len(duplicates)}")
    if missing:
        errors.append(f"sitemap-missing-expected:{len(missing)}")
    if missing_public:
        errors.append(f"sitemap-missing-public:{len(missing_public)}")
    if extra:
        errors.append(f"sitemap-extra-nonpublic:{len(extra)}")
    report = {
        "exists": True,
        "urls": len(urls),
        "unique_urls": len(set(urls)),
        "duplicate_urls": len(duplicates),
        "missing_expected": len(missing),
        "public_html_urls": len(public_urls),
        "missing_public": len(missing_public),
        "extra_nonpublic": len(extra),
        "duplicate_sample": duplicates[:10],
        "missing_sample": missing[:10],
        "missing_public_sample": missing_public[:10],
        "extra_sample": extra[:10],
    }
    return report, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="영수코칭 과목별학원 6×371 정적 페이지 감사")
    parser.add_argument(
        "--category",
        action="append",
        choices=[config["slug"] for config in CATEGORIES],
        help="특정 카테고리만 검사합니다. 여러 번 지정할 수 있습니다.",
    )
    parser.add_argument("--skip-similarity", action="store_true", help="본문 유사도 계산을 생략합니다.")
    parser.add_argument("--json-out", type=Path, help="JSON 보고서를 지정 경로에도 저장합니다.")
    args = parser.parse_args()

    center_rows = load_csv("센터정보 정리.csv")
    if len(center_rows) != 371:
        raise ValueError(f"Expected 371 center rows, got {len(center_rows)}")
    center_by_locality = {row["근처 수업가능 동네"]: row for row in center_rows}
    if len(center_by_locality) != 371:
        raise ValueError("Center locality values are not unique")

    selected = [
        config for config in CATEGORIES
        if not args.category or config["slug"] in set(args.category)
    ]
    category_reports: list[dict] = []
    similarity_jobs: list[tuple[str, list[tuple[str, str, str, str]]]] = []
    expected_urls = {absolute_url("과목별학원")}
    representative_usage: Counter[str] = Counter()
    representative_by_locality: defaultdict[str, set[str]] = defaultdict(set)
    representative_assignments_by_category: dict[str, dict[str, str]] = {}
    representative_errors: list[str] = []

    for config in selected:
        report, records, urls, assignments = audit_category(config, center_by_locality)
        category_reports.append(report)
        similarity_jobs.append((config["slug"], records))
        expected_urls.update(urls)
        representative_usage.update(assignments.values())
        representative_assignments_by_category[config["slug"]] = assignments
        for locality, filename in assignments.items():
            representative_by_locality[locality].add(filename)

    if not args.category:
        manifest_names: list[str] = []
        if not REPRESENTATIVE_MANIFEST.is_file():
            representative_errors.append("representative-manifest-missing")
        else:
            try:
                manifest = json.loads(REPRESENTATIVE_MANIFEST.read_text(encoding="utf-8"))
                entries = manifest.get("images", []) if isinstance(manifest, dict) else []
                manifest_names = [str(entry.get("asset_name", "")) for entry in entries if isinstance(entry, dict)]
            except (OSError, json.JSONDecodeError) as exc:
                representative_errors.append(f"representative-manifest-invalid:{exc}")
            if len(manifest_names) != REPRESENTATIVE_POOL_SIZE or len(set(manifest_names)) != len(manifest_names):
                representative_errors.append(
                    f"representative-manifest-count:expected-{REPRESENTATIVE_POOL_SIZE}:actual-{len(manifest_names)}"
                )
        asset_files = sorted(
            path.name for path in REPRESENTATIVE_ASSET_DIR.glob("rep-*.gif") if path.is_file()
        ) if REPRESENTATIVE_ASSET_DIR.is_dir() else []
        if len(asset_files) != REPRESENTATIVE_POOL_SIZE:
            representative_errors.append(
                f"representative-asset-count:expected-{REPRESENTATIVE_POOL_SIZE}:actual-{len(asset_files)}"
            )
        if manifest_names and set(asset_files) != set(manifest_names):
            representative_errors.append("representative-manifest-asset-set-mismatch")
        if set(asset_files) != set(representative_usage):
            representative_errors.append(
                "representative-asset-reference-set-mismatch:"
                f"assets-{len(asset_files)}:referenced-{len(representative_usage)}"
            )
        bad_usage = sorted(
            (name, count) for name, count in representative_usage.items() if count != len(CATEGORIES)
        )
        if bad_usage:
            representative_errors.append(
                f"representative-unbalanced-usage:{bad_usage[:10]}"
            )
        bad_localities = sorted(
            locality for locality, names in representative_by_locality.items()
            if len(names) != len(CATEGORIES)
        )
        if bad_localities:
            representative_errors.append(
                f"representative-locality-collision:{bad_localities[:10]}"
            )
        if manifest_names and len(representative_by_locality) == 371:
            locality_indexes = {
                locality: index for index, locality in enumerate(sorted(representative_by_locality))
            }
            mapping_mismatches: list[str] = []
            for category_index, config in enumerate(CATEGORIES):
                assignments = representative_assignments_by_category.get(config["slug"], {})
                for locality, locality_index in locality_indexes.items():
                    expected = manifest_names[
                        (locality_index + category_index * REPRESENTATIVE_CATEGORY_OFFSET)
                        % len(manifest_names)
                    ]
                    if assignments.get(locality) != expected:
                        mapping_mismatches.append(f"{config['slug']}/{locality}")
            if mapping_mismatches:
                representative_errors.append(
                    f"representative-mapping-mismatch:{mapping_mismatches[:10]}"
                )

    similarity: dict[str, dict] = {}
    if not args.skip_similarity and similarity_jobs:
        workers = min(len(similarity_jobs), 4)
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(similarity_worker, job) for job in similarity_jobs]
            for future in as_completed(futures):
                category, result = future.result()
                similarity[category] = result

    sitemap_report, sitemap_errors = sitemap_audit(expected_urls)
    similarity_errors = [
        f"similarity-threshold:{category}:"
        f"pairs-{result['masked_5_shingle_max_similarity']['pairs_at_or_above_0_75']}:"
        f"duplicates-{result['exact_duplicate_articles']}"
        for category, result in similarity.items()
        if result["exact_duplicate_articles"]
        or result["masked_5_shingle_max_similarity"]["pairs_at_or_above_0_75"]
    ]
    structural_errors = (
        sum(report["errors"] for report in category_reports)
        + len(sitemap_errors)
        + len(representative_errors)
        + len(similarity_errors)
    )
    output = {
        "site": SITE_NAME,
        "root": str(ROOT),
        "categories_checked": len(selected),
        "detail_pages_checked": sum(report["pages"] for report in category_reports),
        "status": "pass" if structural_errors == 0 else "fail",
        "structural_errors": structural_errors,
        "categories": category_reports,
        "sitemap": sitemap_report,
        "sitemap_errors": sitemap_errors,
        "representative_images": {
            "assets": len(set(representative_usage)),
            "references": sum(representative_usage.values()),
            "localities_with_distinct_category_images": sum(
                1 for names in representative_by_locality.values()
                if len(names) == len(CATEGORIES)
            ),
            "errors": representative_errors,
        },
        "similarity": {key: similarity[key] for key in sorted(similarity)},
        "similarity_errors": similarity_errors,
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return 0 if structural_errors == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
