"""Score the two elementary subject collections with independent hard gates.

The 100-point score is a transparent content/release rubric, not a Naver
ranking prediction. Factual or structural failures remain hard errors and can
never be offset by points earned elsewhere.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from apply_anchor_toc import detail_pages as toc_detail_pages
from audit_anchor_toc import audit_page as audit_toc_page
from audit_subject_pages import (
    FORBIDDEN_SCHEMA_TYPES,
    MAIN_MEDIA_IMG_RE,
    MAP_CARD_IMG_RE,
    REPRESENTATIVE_IMG_RE,
    REQUIRED_SCHEMA_TYPES,
    article_school_mentions,
    article_text,
    masked_shingles,
    parse_json_ld,
    plain_text,
    schema_faq,
    schema_types,
    supplied_school_name_present,
    tag_attribute,
    visible_faq,
    visible_school_tags,
)
from generate_subject_pages import (
    CATEGORIES,
    ROOT,
    SITE_NAME,
    absolute_url,
    all_schools_for,
    load_csv,
    schools_for,
)


ELEMENTARY_SLUGS = ("초등학생영어학원", "초등학생수학학원")
EXPECTED_PER_CATEGORY = 371
REQUIRED_MIN_SCORE = 90
REQUIRED_MEAN_SCORE = 95

WEIGHTS = {
    "technical_identity": 10,
    "technical_schema_faq": 10,
    "technical_media_toc": 10,
    "content_length": 6,
    "content_sections": 5,
    "content_faq_cases": 5,
    "content_reader_relevance": 5,
    "content_natural_h2": 4,
    "content_faq_concise": 5,
    "factual_school_tags": 8,
    "factual_school_schema": 5,
    "factual_no_wrong_school": 7,
    "factual_safe_copy": 5,
    "uniqueness_exact": 5,
    "uniqueness_similarity": 10,
}

TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.IGNORECASE | re.DOTALL)
ARTICLE_RE = re.compile(
    r'<article\b[^>]*class=["\'][^"\']*\bacademy-article\b[^"\']*["\'][^>]*>'
    r"(.*?)</article>",
    re.IGNORECASE | re.DOTALL,
)
ARTICLE_SECTION_RE = re.compile(
    r'<section\b[^>]*class=["\'][^"\']*\bacademy-article-section\b[^"\']*["\'][^>]*>'
    r"(.*?)</section>",
    re.IGNORECASE | re.DOTALL,
)
H2_RE = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
LEAD_RE = re.compile(
    r'<p\b[^>]*class=["\'][^"\']*\blead\b[^"\']*["\'][^>]*>(.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)
CASE_RE = re.compile(r'<blockquote\b[^>]*class=["\'][^"\']*\bacademy-case-card\b', re.IGNORECASE)
META_RE = re.compile(
    r'<meta\b[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\'][^>]*>',
    re.IGNORECASE,
)
CANONICAL_RE = re.compile(
    r'<link\b[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']*)["\'][^>]*>',
    re.IGNORECASE,
)
OG_URL_RE = re.compile(
    r'<meta\b[^>]*property=["\']og:url["\'][^>]*content=["\']([^"\']*)["\'][^>]*>',
    re.IGNORECASE,
)
READER_RE = re.compile(r"학생|자녀|아이|학부모|보호자|가정")
ACTION_OR_PROBLEM_RE = re.compile(
    r"확인|점검|준비|정리|비교|어렵|막히|실수|오답|부담|고민|부족|헷갈|반복"
)
AUTHORING_RE = re.compile(r"원고|키워드|검색자|(?<![A-Za-z])SEO(?![A-Za-z])|JSON-LD|구조화 데이터|D열", re.IGNORECASE)
IRRELEVANT_OFFICE_RE = re.compile(
    r"학원(?:매출관리|운영자|회원관리|고객관리|데스크|관리솔루션|창업|휴게실)"
)
STRONG_CLAIM_RE = re.compile(
    r"(?:성적|등급|합격|입시\s*결과).{0,25}보장|보장.{0,25}(?:성적|등급|합격|입시\s*결과)|100\s*%",
    re.IGNORECASE,
)
NEGATION_RE = re.compile(
    r"보장하지\s*않|보장할\s*수\s*없|보장으로\s*(?:해석|확대)해서는\s*안|"
    r"보장하는\s*표현(?:이\s*아닙니다|으로\s*받아들이지\s*마세요)|"
    r"단정하지\s*않|실제.*뜻하지\s*않"
)


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", value))).strip()


def attr_value(pattern: re.Pattern[str], source: str) -> str:
    match = pattern.search(source)
    return plain_text(match.group(1)) if match else ""


def document_title(source: str) -> str:
    match = re.search(r"<title>(.*?)</title>", source, re.IGNORECASE | re.DOTALL)
    return clean(match.group(1)) if match else ""


def h1_value(source: str) -> str:
    matches = re.findall(r"<h1\b[^>]*>(.*?)</h1>", source, re.IGNORECASE | re.DOTALL)
    return clean(matches[0]) if len(matches) == 1 else ""


def sentence_count(value: str) -> int:
    return len([item for item in re.split(r"(?<=[.!?])\s+", value) if item.strip()])


def page_similarity(records: list[dict[str, object]]) -> tuple[list[float], int]:
    sets = [record["shingles"] for record in records]
    best = [0.0] * len(sets)
    over = 0
    for left_index, left in enumerate(sets):
        assert isinstance(left, set)
        for right_index in range(left_index + 1, len(sets)):
            right = sets[right_index]
            assert isinstance(right, set)
            intersection = len(left & right)
            union = len(left) + len(right) - intersection
            score = intersection / union if union else 1.0
            if score >= 0.75:
                over += 1
            if score > best[left_index]:
                best[left_index] = score
            if score > best[right_index]:
                best[right_index] = score
    return best, over


def initial_record(
    page: Path, config: dict[str, str], row: dict[str, str], sitemap_urls: set[str],
) -> dict[str, object]:
    source = page.read_text(encoding="utf-8")
    slug = page.parent.name
    expected_h1 = f"{slug} {config['label']}"
    expected_url = absolute_url("과목별학원", config["slug"], slug)
    h1 = h1_value(source)
    meta = attr_value(META_RE, source)
    identity_ok = (
        h1 == expected_h1
        and document_title(source) == f"{expected_h1} | {SITE_NAME}"
        and 70 <= len(meta) <= 100
        and attr_value(CANONICAL_RE, source) == expected_url
        and attr_value(OG_URL_RE, source) == expected_url
        and expected_url in sitemap_urls
    )

    parse_errors: list[str] = []
    blocks = parse_json_ld(source, f"{config['slug']}/{slug}", parse_errors)
    present_types: set[str] = set()
    for block in blocks:
        present_types.update(schema_types(block))
    screen_faq = visible_faq(source)
    schema_pairs = schema_faq(blocks)
    schema_ok = (
        not parse_errors
        and REQUIRED_SCHEMA_TYPES <= present_types
        and not (FORBIDDEN_SCHEMA_TYPES & present_types)
        and len(screen_faq) == 4
        and screen_faq == schema_pairs
    )

    representative = REPRESENTATIVE_IMG_RE.findall(source)
    main_media = MAIN_MEDIA_IMG_RE.search(source)
    map_media = MAP_CARD_IMG_RE.search(source)
    media_ok = len(representative) == 1 and not audit_toc_page(page)
    if representative:
        media_ok = media_ok and tag_attribute(representative[0], "style") == "display:none;"
        media_ok = media_ok and tag_attribute(representative[0], "alt") == f"{expected_h1} 대표"
    if not main_media or not map_media:
        media_ok = False
    else:
        main_tag = main_media.group(1)
        map_tag = map_media.group(1)
        srcset = tag_attribute(main_tag, "srcset")
        media_ok = media_ok and tag_attribute(main_tag, "loading") == "lazy"
        media_ok = media_ok and tag_attribute(main_tag, "decoding") == "async"
        media_ok = media_ok and "-480.webp" in srcset and "-720.webp" in srcset
        media_ok = media_ok and tag_attribute(main_tag, "width").isdigit() and tag_attribute(main_tag, "height").isdigit()
        media_ok = media_ok and tag_attribute(map_tag, "width").isdigit() and tag_attribute(map_tag, "height").isdigit()

    article_match = ARTICLE_RE.search(source)
    article_markup = article_match.group(1) if article_match else ""
    article = article_text(source)
    article_chars = len(article.replace(" ", ""))
    sections = ARTICLE_SECTION_RE.findall(article_markup)
    headings = [clean(match.group(1)) for section in sections if (match := H2_RE.search(section))]
    lead_match = LEAD_RE.search(article_markup)
    opening = clean(lead_match.group(1)) if lead_match else ""
    cases = len(CASE_RE.findall(source))
    natural_h2 = (
        len(headings) == 6
        and all(0 < len(value) <= 78 and not AUTHORING_RE.search(value) for value in headings)
    )
    faq_concise = bool(screen_faq) and all(
        len(answer) <= 240 and sentence_count(answer) <= 3
        for _question, answer in screen_faq
    )

    allowed_schools = schools_for(row, config["school_field"])
    disallowed_schools = [
        name for name in all_schools_for(row) if name not in set(allowed_schools)
    ]
    visible_without_scripts = SCRIPT_RE.sub(" ", source)
    wrong_schools = [
        name for name in disallowed_schools
        if supplied_school_name_present(visible_without_scripts, name)
    ]
    safe_copy_source = " ".join(
        [article]
        + [question + " " + answer for question, answer in screen_faq]
        + [clean(value) for value in re.findall(r'<blockquote\b[^>]*>(.*?)</blockquote>', source, re.IGNORECASE | re.DOTALL)]
    )
    strong_claims = [
        match.group(0) for match in STRONG_CLAIM_RE.finditer(safe_copy_source)
        if not NEGATION_RE.search(safe_copy_source[max(0, match.start() - 45): match.end() + 45])
    ]

    criteria = {
        "technical_identity": identity_ok,
        "technical_schema_faq": schema_ok,
        "technical_media_toc": media_ok,
        "content_length": 2000 <= article_chars <= 7500,
        "content_sections": len(sections) == 6,
        "content_faq_cases": len(screen_faq) == 4 and cases >= 1,
        "content_reader_relevance": slug in opening and bool(READER_RE.search(opening)) and bool(ACTION_OR_PROBLEM_RE.search(opening)),
        "content_natural_h2": natural_h2,
        "content_faq_concise": faq_concise,
        "factual_school_tags": visible_school_tags(source) == allowed_schools,
        "factual_school_schema": article_school_mentions(blocks) == allowed_schools,
        "factual_no_wrong_school": not wrong_schools,
        "factual_safe_copy": not strong_claims and not AUTHORING_RE.search(safe_copy_source) and not IRRELEVANT_OFFICE_RE.search(safe_copy_source),
        "uniqueness_exact": True,
        "uniqueness_similarity": True,
    }
    return {
        "slug": slug,
        "path": page.relative_to(ROOT).as_posix(),
        "article": article,
        "article_hash": hashlib.sha256(article.encode("utf-8")).hexdigest(),
        "shingles": masked_shingles(article, slug, expected_h1),
        "criteria": criteria,
        "wrong_schools": wrong_schools,
        "parse_errors": parse_errors,
        "article_chars": article_chars,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score 영수코칭 elementary subject pages out of 100.")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    configs = {item["slug"]: item for item in CATEGORIES if item["slug"] in ELEMENTARY_SLUGS}
    if set(configs) != set(ELEMENTARY_SLUGS):
        raise ValueError(f"Elementary category config mismatch: {sorted(configs)}")
    rows = load_csv("센터정보 정리.csv")
    center_by_locality = {row["근처 수업가능 동네"]: row for row in rows}
    sitemap_text = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    sitemap_urls = set(re.findall(r"<loc>(.*?)</loc>", sitemap_text))

    all_results: dict[str, dict[str, object]] = {}
    strict_errors: list[str] = []
    overall_scores: list[int] = []
    for category_slug in ELEMENTARY_SLUGS:
        config = configs[category_slug]
        pages = sorted((ROOT / "과목별학원" / category_slug).glob("*/index.html"))
        if len(pages) != EXPECTED_PER_CATEGORY:
            strict_errors.append(
                f"page-count:{category_slug}:expected-{EXPECTED_PER_CATEGORY}:actual-{len(pages)}"
            )
        if {page.parent.name for page in pages} != set(center_by_locality):
            strict_errors.append(f"locality-set:{category_slug}")
        records = [
            initial_record(page, config, center_by_locality[page.parent.name], sitemap_urls)
            for page in pages
        ]
        hash_counts = Counter(str(record["article_hash"]) for record in records)
        similarities, pairs_over = page_similarity(records)
        for record, best_similarity in zip(records, similarities):
            criteria = record["criteria"]
            assert isinstance(criteria, dict)
            criteria["uniqueness_exact"] = hash_counts[str(record["article_hash"])] == 1
            criteria["uniqueness_similarity"] = best_similarity < 0.75
            record["best_similarity"] = round(best_similarity, 4)
            record["score"] = sum(WEIGHTS[name] for name, passed in criteria.items() if passed)

        issue_counts: Counter[str] = Counter()
        issue_examples: defaultdict[str, list[str]] = defaultdict(list)
        scores: list[int] = []
        hard_prefixes = ("technical_", "factual_", "uniqueness_")
        for record in records:
            criteria = record["criteria"]
            assert isinstance(criteria, dict)
            score = int(record["score"])
            scores.append(score)
            overall_scores.append(score)
            for name, passed in criteria.items():
                if passed:
                    continue
                issue_counts[name] += 1
                if len(issue_examples[name]) < 5:
                    issue_examples[name].append(str(record["path"]))
                if name.startswith(hard_prefixes):
                    strict_errors.append(f"{name}:{record['path']}")
            if score < REQUIRED_MIN_SCORE:
                strict_errors.append(f"score-min:{record['path']}:{score}")
        mean_score = round(statistics.mean(scores), 2) if scores else 0.0
        if mean_score < REQUIRED_MEAN_SCORE:
            strict_errors.append(f"score-mean:{category_slug}:{mean_score}")
        if pairs_over:
            strict_errors.append(f"similarity-pairs:{category_slug}:{pairs_over}")
        worst = sorted(records, key=lambda item: (int(item["score"]), -float(item["best_similarity"]), str(item["slug"])))[:10]
        all_results[category_slug] = {
            "pages": len(records),
            "score_min": min(scores) if scores else 0,
            "score_mean": mean_score,
            "score_median": round(statistics.median(scores), 2) if scores else 0.0,
            "pages_below_90": sum(score < REQUIRED_MIN_SCORE for score in scores),
            "exact_duplicate_pages": sum(count for count in hash_counts.values() if count > 1),
            "pairs_at_or_above_0_75": pairs_over,
            "max_similarity": round(max(similarities), 4) if similarities else 0.0,
            "criteria_pass_ratio": {
                name: round(sum(bool(record["criteria"][name]) for record in records) / len(records), 4)
                if records else 0.0
                for name in WEIGHTS
            },
            "issue_counts": dict(sorted(issue_counts.items())),
            "issue_examples": dict(sorted(issue_examples.items())),
            "worst_pages": [
                {"path": item["path"], "score": item["score"], "best_similarity": item["best_similarity"]}
                for item in worst
            ],
        }

    report = {
        "site": SITE_NAME,
        "scope": list(ELEMENTARY_SLUGS),
        "score_type": "transparent content and release quality score; not a search ranking prediction",
        "weights": WEIGHTS,
        "required_min_page_score": REQUIRED_MIN_SCORE,
        "required_mean_category_score": REQUIRED_MEAN_SCORE,
        "strict_pass": not strict_errors,
        "strict_errors": strict_errors[:100],
        "overall": {
            "pages": len(overall_scores),
            "score_min": min(overall_scores) if overall_scores else 0,
            "score_mean": round(statistics.mean(overall_scores), 2) if overall_scores else 0.0,
            "score_median": round(statistics.median(overall_scores), 2) if overall_scores else 0.0,
        },
        "categories": all_results,
        "toc_detail_pages_discovered": len(toc_detail_pages(ROOT)),
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["strict_pass"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
