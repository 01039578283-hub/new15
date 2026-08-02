from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, urlparse

from generate_subject_pages import CATEGORIES, DOMAIN, ROOT, SITE_NAME, absolute_url


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


def plain_text(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", value))).strip()


def normalize_url(value: str) -> str:
    return html.unescape(value).strip()


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


def audit_category(config: dict[str, str]) -> tuple[dict, list[tuple[str, str, str, str]], set[str]]:
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
    }
    return report, records, expected_urls


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
    if duplicates:
        errors.append(f"sitemap-duplicate-urls:{len(duplicates)}")
    if missing:
        errors.append(f"sitemap-missing-expected:{len(missing)}")
    report = {
        "exists": True,
        "urls": len(urls),
        "unique_urls": len(set(urls)),
        "duplicate_urls": len(duplicates),
        "missing_expected": len(missing),
        "duplicate_sample": duplicates[:10],
        "missing_sample": missing[:10],
    }
    return report, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="영수코칭 과목별학원 4×371 정적 페이지 감사")
    parser.add_argument(
        "--category",
        action="append",
        choices=[config["slug"] for config in CATEGORIES],
        help="특정 카테고리만 검사합니다. 여러 번 지정할 수 있습니다.",
    )
    parser.add_argument("--skip-similarity", action="store_true", help="본문 유사도 계산을 생략합니다.")
    parser.add_argument("--json-out", type=Path, help="JSON 보고서를 지정 경로에도 저장합니다.")
    args = parser.parse_args()

    selected = [
        config for config in CATEGORIES
        if not args.category or config["slug"] in set(args.category)
    ]
    category_reports: list[dict] = []
    similarity_jobs: list[tuple[str, list[tuple[str, str, str, str]]]] = []
    expected_urls = {absolute_url("과목별학원")}

    for config in selected:
        report, records, urls = audit_category(config)
        category_reports.append(report)
        similarity_jobs.append((config["slug"], records))
        expected_urls.update(urls)

    similarity: dict[str, dict] = {}
    if not args.skip_similarity and similarity_jobs:
        workers = min(len(similarity_jobs), 4)
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(similarity_worker, job) for job in similarity_jobs]
            for future in as_completed(futures):
                category, result = future.result()
                similarity[category] = result

    sitemap_report, sitemap_errors = sitemap_audit(expected_urls)
    structural_errors = sum(report["errors"] for report in category_reports) + len(sitemap_errors)
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
        "similarity": {key: similarity[key] for key in sorted(similarity)},
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
