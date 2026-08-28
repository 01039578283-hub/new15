from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import shutil
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import date, datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT.parent / "참고자료"
SOURCE_DIR = REFERENCE / "사용한 원고" / "새 홈페이지15 추가 원고"
COMMON_DIR = REFERENCE / "공통자료"
REPRESENTATIVE_SOURCE_DIR = COMMON_DIR / "대표이미지"
REPRESENTATIVE_ASSET_DIR = ROOT / "assets" / "representative"
REPRESENTATIVE_MANIFEST = REPRESENTATIVE_ASSET_DIR / "manifest.json"
TARGET_ROOT = ROOT / "과목별학원"
DOMAIN = "https://xn--9p4bn5e3wjn0a.com"
SITE_NAME = "영수코칭"
PHONE = "010-6839-8283"
PHONE_LINK = "01068398283"
TODAY = date.today().isoformat()
SHARE_IMAGE_URL = DOMAIN + "/assets/images/og-share.png"
SHARE_IMAGE_ALT = "영어와 수학의 학습 흐름을 연결하는 영수코칭 안내 이미지"
REPRESENTATIVE_POOL_SIZE = 371
REPRESENTATIVE_CATEGORY_OFFSET = 97
IGNORED_PUBLIC_DIRS = {
    ".git",
    ".vercel",
    "node_modules",
    "reports",
    "test-results",
    "playwright-report",
    "tmp",
    "tools",
    "__pycache__",
}

CATEGORIES = [
    {
        "label": "고등학생 수학학원",
        "slug": "고등학생수학학원",
        "zip": "고등학생 수학학원.zip",
        "level": "고등학생",
        "subject": "수학",
        "school_field": "타깃학교\n(고)",
        "grade_field": "가능학년\n(수학)",
        "english": "HIGH SCHOOL MATH",
        "summary": "내신 범위와 모의 학습, 개념·문제 해석·서술형 풀이를 함께 확인하는 지역별 고등 수학 안내입니다.",
    },
    {
        "label": "고등학생 영어학원",
        "slug": "고등학생영어학원",
        "zip": "고등학생 영어학원.zip",
        "level": "고등학생",
        "subject": "영어",
        "school_field": "타깃학교\n(고)",
        "grade_field": "가능학년\n(영어)",
        "english": "HIGH SCHOOL ENGLISH",
        "summary": "학교 지문과 어휘·문법·독해·서술형의 연결을 확인하는 지역별 고등 영어 안내입니다.",
    },
    {
        "label": "중학생 수학학원",
        "slug": "중학생수학학원",
        "zip": "중학생 수학학원.zip",
        "level": "중학생",
        "subject": "수학",
        "school_field": "타깃학교\n(중)",
        "grade_field": "가능학년\n(수학)",
        "english": "MIDDLE SCHOOL MATH",
        "summary": "학교 진도와 시험 범위, 개념·계산·응용·오답 재학습을 확인하는 지역별 중등 수학 안내입니다.",
    },
    {
        "label": "중학생 영어학원",
        "slug": "중학생영어학원",
        "zip": "중학생 영어학원.zip",
        "level": "중학생",
        "subject": "영어",
        "school_field": "타깃학교\n(중)",
        "grade_field": "가능학년\n(영어)",
        "english": "MIDDLE SCHOOL ENGLISH",
        "summary": "학교 교과와 어휘·문법·독해·서술형 대비를 연결하는 지역별 중등 영어 안내입니다.",
    },
]


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def absolute_url(*parts: str) -> str:
    path = "/" + "/".join(part.strip("/") for part in parts if part) + "/"
    return DOMAIN + quote(path, safe="/")


def load_csv(name: str) -> list[dict[str, str]]:
    with (COMMON_DIR / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def parse_sections(text: str) -> dict[str, str]:
    marker = re.compile(r"^\[([^\]]+)\]\s*$", re.MULTILINE)
    matches = list(marker.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).strip()] = text[match.end():end].strip()
    return sections


def parse_body(body: str) -> tuple[str, list[tuple[str, list[str]]]]:
    heading = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(heading.finditer(body))
    intro = body[: matches[0].start()].strip() if matches else body.strip()
    sections: list[tuple[str, list[str]]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content = body[match.end():end].strip()
        paragraphs = [normalize(part) for part in re.split(r"\n\s*\n", content) if normalize(part)]
        sections.append((normalize(match.group(1)), paragraphs))
    return normalize(intro), sections


def parse_faq(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r"^Q(\d+)\.\s*(.+?)\s*\nA(?:\1)?\.\s*(.+?)(?=\n\s*\nQ\d+\.|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    return [(normalize(question), normalize(answer)) for _, question, answer in pattern.findall(text)]


def parse_cases(text: str) -> list[str]:
    value = text.strip()
    if not value:
        return []
    chunks = re.split(r"(?=후기\s*(?:예시|형\s*문안)?\s*\d+\.)", value)
    cases = [normalize(chunk) for chunk in chunks if normalize(chunk)]
    if len(cases) == 1:
        paragraphs = [normalize(part) for part in re.split(r"\n\s*\n", value) if normalize(part)]
        return paragraphs or cases
    return cases


def stable_choice(seed: str, values: list[str]) -> str:
    """Return a repeatable variant without relying on process-randomized hash()."""
    if not values:
        return ""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return values[int.from_bytes(digest[:4], "big") % len(values)]


def representative_source_files() -> list[Path]:
    """Select a stable, duplicate-free pool of lightweight source images."""
    if not REPRESENTATIVE_SOURCE_DIR.is_dir():
        raise FileNotFoundError(REPRESENTATIVE_SOURCE_DIR)

    if REPRESENTATIVE_MANIFEST.is_file():
        manifest = json.loads(REPRESENTATIVE_MANIFEST.read_text(encoding="utf-8"))
        entries = manifest.get("images", []) if isinstance(manifest, dict) else []
        if len(entries) != REPRESENTATIVE_POOL_SIZE:
            raise ValueError(f"대표이미지 manifest 항목 수 오류: {len(entries)}")
        selected: list[Path] = []
        seen_hashes: set[str] = set()
        for index, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                raise ValueError(f"대표이미지 manifest 형식 오류: {index}")
            source_name = str(entry.get("source_name", ""))
            expected_hash = str(entry.get("sha256", ""))
            expected_asset = f"rep-{index:03d}.gif"
            if entry.get("asset_name") != expected_asset:
                raise ValueError(f"대표이미지 manifest 자산명 오류: {index}")
            source = REPRESENTATIVE_SOURCE_DIR / source_name
            if not source.is_file() or source.suffix.lower() != ".gif":
                raise FileNotFoundError(source)
            actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(f"대표이미지 원본 해시 불일치: {source_name}")
            if actual_hash in seen_hashes:
                raise ValueError(f"대표이미지 manifest 내용 중복: {source_name}")
            seen_hashes.add(actual_hash)
            selected.append(source)
        return selected

    unique_by_digest: dict[str, Path] = {}
    for path in sorted(REPRESENTATIVE_SOURCE_DIR.glob("*.gif"), key=lambda item: item.name):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        unique_by_digest.setdefault(digest, path)

    ordered = sorted(
        unique_by_digest.items(),
        key=lambda item: hashlib.sha256(
            f"{SITE_NAME}|representative-pool|{item[0]}".encode("utf-8")
        ).digest(),
    )
    selected = [path for _digest, path in ordered[:REPRESENTATIVE_POOL_SIZE]]
    if len(selected) != REPRESENTATIVE_POOL_SIZE:
        raise ValueError(
            f"대표이미지 고유 GIF가 부족합니다: expected={REPRESENTATIVE_POOL_SIZE} actual={len(selected)}"
        )
    return selected


def prepare_representative_images(*, apply: bool = True) -> list[str]:
    """Copy the selected pool to stable ASCII filenames and return those names."""
    sources = representative_source_files()
    if apply:
        REPRESENTATIVE_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    expected: set[str] = set()

    for index, source in enumerate(sources, 1):
        name = f"rep-{index:03d}{source.suffix.lower()}"
        expected.add(name)
        destination = REPRESENTATIVE_ASSET_DIR / name
        if apply and (
            not destination.is_file()
            or destination.stat().st_size != source.stat().st_size
            or hashlib.sha256(destination.read_bytes()).digest()
            != hashlib.sha256(source.read_bytes()).digest()
        ):
            shutil.copy2(source, destination)
        names.append(name)

    manifest = {
        "version": 1,
        "selection": "371 unique GIF files, deterministic SHA-256 order",
        "images": [
            {
                "asset_name": name,
                "source_name": source.name,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            for name, source in zip(names, sources)
        ],
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if apply:
        if REPRESENTATIVE_MANIFEST.is_file():
            if REPRESENTATIVE_MANIFEST.read_text(encoding="utf-8") != manifest_text:
                raise ValueError("대표이미지 manifest가 계산 결과와 일치하지 않습니다")
        else:
            REPRESENTATIVE_MANIFEST.write_text(manifest_text, encoding="utf-8")

    if apply:
        for stale in REPRESENTATIVE_ASSET_DIR.glob("rep-*"):
            if stale.is_file() and stale.name not in expected:
                stale.unlink()
    return names


def representative_image_name(
    names: list[str], *, category_index: int, locality_index: int,
) -> str:
    if len(names) != REPRESENTATIVE_POOL_SIZE:
        raise ValueError(f"대표이미지 풀 크기 오류: {len(names)}")
    index = (locality_index + category_index * REPRESENTATIVE_CATEGORY_OFFSET) % len(names)
    return names[index]


def korean_josa(value: str, pair: str) -> str:
    """Attach a Korean particle, including the ㄹ + 로 exception."""
    pairs = {
        "은/는": ("은", "는"),
        "이/가": ("이", "가"),
        "을/를": ("을", "를"),
        "과/와": ("과", "와"),
        "으로/로": ("으로", "로"),
    }
    with_batchim, without_batchim = pairs[pair]
    last_hangul = next((char for char in reversed(normalize(value)) if "가" <= char <= "힣"), "")
    if not last_hangul:
        return value + without_batchim
    jongseong = (ord(last_hangul) - 0xAC00) % 28
    if pair == "으로/로" and jongseong in {0, 8}:
        particle = without_batchim
    else:
        particle = with_batchim if jongseong else without_batchim
    return value + particle


def content_context(
    *, title: str, locality: str, slug: str, row: dict[str, str], config: dict[str, str],
) -> dict[str, object]:
    return {
        "seed": f"{config['slug']}|{slug}|{locality}",
        "title": title,
        "locality": locality,
        "region": normalize(f"{row.get('지역', '')} {row.get('시or구', '')}"),
        "center": normalize(row.get("센터명", "")) or f"{locality} 학습센터",
        "address": normalize(row.get("센터 주소", "")),
        "schools": schools_for(row, config["school_field"]),
        "grades": normalize(row.get(config["grade_field"], "")),
        "level": config["level"],
        "subject": config["subject"],
        "category": config["slug"],
    }


def repair_named_josa(value: str, context: dict[str, object]) -> str:
    """Correct particles attached to generated locality/center strings."""
    text = value
    for noun in (str(context["locality"]), str(context["center"])):
        if not noun:
            continue
        for pair, forms in {
            "은/는": ("은", "는"),
            "이/가": ("이", "가"),
            "을/를": ("을", "를"),
            "과/와": ("과", "와"),
            "으로/로": ("으로", "로"),
        }.items():
            suffix = "(?:으)?로" if pair == "으로/로" else "(?:" + "|".join(forms) + ")"
            text = re.sub(
                re.escape(noun) + suffix + r"(?=\s|[,.;:!?]|$)",
                lambda _match, word=noun, particle_pair=pair: korean_josa(word, particle_pair),
                text,
            )
    address = str(context["address"])
    if address:
        # A raw address often ends in 호/층/점. Appending 로 mechanically makes
        # malformed strings, so express the relation with "기준으로" instead.
        text = re.sub(
            re.escape(address) + r"(?:으)?로(?=\s|[,.;:!?]|$)",
            address + " 기준으로",
            text,
        )
    return text.replace("주소+로", "주소를 기준으로").replace("주소 + 로", "주소를 기준으로")


def enforce_verified_school_claims(
    value: str, context: dict[str, object], seed_suffix: str,
) -> str:
    """Keep school claims aligned with the category-specific center-data column."""
    if seed_suffix.startswith("heading") or seed_suffix == "meta-description":
        return value
    markers = ("수업학교", "수업 학교", "학교 정보", "학교명", "학교 기준", "학교군", "학교 범위")
    if not any(marker in value for marker in markers):
        return value
    schools = [str(item) for item in context["schools"]]
    level = str(context["level"])
    subject = str(context["subject"])
    locality = str(context["locality"])

    if seed_suffix.startswith("faq-question"):
        if schools:
            choices = [
                f"{locality} {level} {subject} 상담에서 학교별 내신 대비는 어떻게 확인하나요?",
                f"{locality} {level} {subject} 수업은 재학 학교 자료를 어떻게 반영하나요?",
                f"{locality} 학생의 학교 시험 범위는 상담에서 어떻게 확인하나요?",
            ]
        else:
            choices = [
                f"{locality} {level} {subject} 상담에서 재학 학교 정보는 어떻게 확인하나요?",
                f"제공 자료에 학교명이 없으면 {locality} 학생의 시험 대비는 어떻게 정하나요?",
                f"{locality} 학생의 실제 학교와 시험 범위는 언제 확인하나요?",
            ]
        return stable_choice(f"{context['seed']}|verified-school-question|{seed_suffix}", choices)

    def verified_sentence(original: str, index: int) -> str:
        if schools:
            names = ", ".join(schools)
            choices = [
                f"제공된 {level} {subject} 수업 학교 정보는 {names}입니다.",
                f"센터 자료에서 확인되는 {level} {subject} 관련 학교는 {names}입니다.",
                f"{locality} 안내에는 제공 자료의 {names} 학교 정보만 반영했습니다.",
            ]
        else:
            choices = [
                f"제공된 센터 자료에는 {level} {subject} 관련 학교명이 별도로 기재되어 있지 않습니다. 상담에서는 학생의 실제 재학 학교와 최신 시험 범위를 확인해야 합니다.",
                f"{locality} 센터 자료에는 {level} {subject} 학교 정보가 따로 제공되지 않았습니다. 특정 학교를 가정하지 않고 상담에서 실제 학교와 시험 범위를 확인합니다.",
                f"이 안내에는 확인되지 않은 {level} 학교명을 임의로 넣지 않았습니다. {subject} 상담 때 학생의 재학 학교와 최신 범위표를 함께 확인하는 편이 정확합니다.",
            ]
        scope = "faq" if seed_suffix.startswith("faq-") else "summary" if seed_suffix == "summary" else "article"
        return stable_choice(f"{context['seed']}|verified-school|{scope}", choices)

    sentences = [item for item in re.split(r"(?<=[.!?])\s+", value) if normalize(item)]
    normalized = []
    for index, sentence in enumerate(sentences):
        has_marker = any(marker in sentence for marker in markers)
        is_claim = has_marker
        normalized.append(verified_sentence(sentence, index) if is_claim else sentence)
    return " ".join(normalized)


def naturalize_text(value: str, context: dict[str, object], seed_suffix: str) -> str:
    """Remove authoring instructions while keeping the supplied facts intact."""
    text = normalize(value)
    if not text:
        return text
    seed = f"{context['seed']}|{seed_suffix}"

    def keyword_variant(term: str, offset: str) -> str:
        term = normalize(term)
        return stable_choice(
            f"{seed}|keyword|{offset}|{term}",
            [f"‘{term}’ 확인 기준", f"‘{term}’ 관리 방식", f"‘{term}’ 운영 항목"],
        )

    text = re.sub(
        r"(?:원고\s*)?(?:참고\s*)?키워드\s*항목\s*\(\s*([^)]+?)\s*\)",
        lambda match: keyword_variant(match.group(1), str(match.start())),
        text,
    )
    text = re.sub(
        r"(?:원고\s*)?(?:참고\s*)?키워드\s*[‘“\"']([^’”\"']+)[’”\"']\s*(?:항목)?",
        lambda match: keyword_variant(match.group(1), str(match.start())),
        text,
    )
    text = re.sub(
        r"(?:참고\s*)?키워드\s+([가-힣A-Za-z0-9·_-]+)(?:\s+항목)?",
        lambda match: stable_choice(
            f"{seed}|plain-keyword|{match.start()}",
            [f"{match.group(1)} 관련 정보", f"{match.group(1)} 확인 기준", f"{match.group(1)} 운영 방식"],
        ),
        text,
    )
    text = re.sub(
        r"운영\s*키워드로\s*제공된\s*([가-힣A-Za-z0-9·_-]+)",
        lambda match: f"제공 자료의 {match.group(1)} 항목",
        text,
    )
    text = re.sub(r"D열에\s*제공된\s*학교\s*정보", "제공된 수업 학교 정보", text)
    text = re.sub(r"D열의\s*학교\s*정보", "제공된 학교 정보", text)
    text = text.replace("D열", "제공 자료")

    replacements = (
        ("정보성 문서 형태로 정리한 원고입니다", "상담 전에 확인할 기준을 정리한 안내입니다"),
        ("페이지에 맞춰 작성한 후기형 문안입니다", "상담 전에 살필 상황을 정리한 예시입니다"),
        ("페이지에 맞춘 학부모 후기 형식 예시입니다", "학부모 상담에서 살필 상황을 정리한 예시입니다"),
        ("페이지 원고입니다", "학습 안내입니다"),
        ("학부모 후기 형식 예시", "학부모 상담 상황 예시"),
        ("학부모 후기입니다", "학부모 상담 상황입니다"),
        ("학부모 후기", "학부모 상담 상황"),
        ("후기형 문안", "상담 상황"),
        ("후기 예시", "상담 상황"),
        ("검색자가", "학부모가"),
        ("검색자", "학부모"),
        ("이 원고에서는", "이 안내에서는"),
        ("이 원고는", "이 안내는"),
        ("원고에서는", "안내에서는"),
        ("원고에서", "안내에서"),
        ("원고의", "안내의"),
        ("원고를", "안내를"),
        ("원고가", "안내가"),
        ("원고입니다", "안내입니다"),
        ("페이지에 맞춘", "이 지역 상황을 반영한"),
        ("페이지에 맞춰", "이 지역 상황에 맞춰"),
        ("이 페이지에서는", "이 안내에서는"),
        ("이 페이지는", "이 안내는"),
        ("페이지에서는", "안내에서는"),
        ("페이지에서", "안내에서"),
        ("페이지를", "안내를"),
        ("페이지가", "안내가"),
        ("페이지입니다", "안내입니다"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    text = text.replace("원고", "안내").replace("키워드", "확인 항목")
    text = re.sub(r"‘([^’]+)’\s*(?:확인 기준|관리 방식|운영 항목)\s*(?:체크|점검)\s*기준", r"‘\1’ 점검 기준", text)
    text = re.sub(r"(관련 정보|확인 기준|운영 방식)\s+항목", r"\1", text)
    text = re.sub(r"(확인 기준|관리 방식|운영 항목)\s+관점", r"\1의 관점", text)
    text = re.sub(r"상담 상황\s*(?:형식\s*)?예시", "상담 상황 예시", text)
    text = re.sub(r"안내\s+안내", "학습 안내", text)
    text = text.replace("구조화 데이터 설명문으로 요약하기 좋습니다", "상담 전에 핵심 기준을 확인할 수 있도록 정리했습니다")
    text = text.replace("구조화 데이터", "핵심 안내")
    text = text.replace("설명문으로 요약하기 좋습니다", "상담 전에 핵심을 확인할 수 있도록 정리했습니다")
    text = text.replace("학원주소", "학원 주소").replace("수업학교", "수업 학교")
    text = text.replace("안내하는 안내입니다", "설명하는 자료입니다")
    text = text.replace("참고할 수 있는 정보형 안내입니다", "확인할 수 있도록 정리했습니다")
    text = text.replace("페이지는", "안내에서는").replace("페이지의", "안내의").replace("페이지를", "안내를")
    text = re.sub(
        r"([가-힣A-Za-z0-9·_-]+)\s+관점\s+학습\s+관리",
        lambda match: f"{korean_josa(match.group(1), '으로/로')} 확인할 학습 관리",
        text,
    )
    text = re.sub(
        r"([가-힣A-Za-z0-9·_-]+)(?:을|를)\s+검색한\s+(?:이유|목적)",
        lambda match: f"{match.group(1)} 정보를 알아본 이유",
        text,
    )
    text = re.sub(
        r"([가-힣A-Za-z0-9·_-]+)(?:을|를)\s+검색한",
        lambda match: f"{match.group(1)} 정보를 알아보는",
        text,
    )
    text = text.replace("학원하원", "등·하원")
    text = text.replace("실제 페이지에 사용할 때", "실제 상담 기준으로 살필 때")
    text = text.replace("학습 기준 학습 방식", "학습 방식")
    text = re.sub(r"상담\s+상담", "상담", text)
    text = re.sub(r"항목(?=중심|관련|기준|관점)", "항목 ", text)
    text = re.sub(
        r"제공 자료의\s+([가-힣A-Za-z0-9·_-]+)(?:은|는)\s+항목",
        r"제공 자료에서 확인되는 \1 항목은",
        text,
    )
    text = re.sub(r"관리 방식을\s+점검 기준으로", "관리 방식을 점검할 때 기준으로", text)
    text = text.replace("학원알림톡가", "학원알림톡이")
    text = text.replace("관리 방식을 점검할 때 기준으로 두면", "관리 방식을 점검 기준으로 삼으면")
    text = text.replace("관리 방식과 연결된 관리 방식", "관리 방식과 연결된 학습 기록")
    text = text.replace("확인 기준관점의", "확인 기준에 따른")
    text = text.replace("확인 기준기반", "확인 기준에 기반한")
    text = text.replace("라는 질문을 궁금해한다면", "라는 질문에 대한 답이 궁금하다면")
    text = text.replace("라는 질문을 걱정하는 가정이라면", "라는 질문에 대한 답이 필요한 가정이라면")
    text = re.sub(r"(관리 방식|확인 기준)(?=중심|관련|기록|기반|관점)", r"\1 ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = enforce_verified_school_claims(text, context, seed_suffix)
    return normalize(repair_named_josa(text, context))


def select_student_situation(
    intro: str, body_sections: list[tuple[str, list[str]]], context: dict[str, object],
) -> str:
    source = " ".join([intro] + [paragraph for _, paragraphs in body_sections for paragraph in paragraphs])
    sentences = [normalize(item) for item in re.split(r"(?<=[.!?])\s+", source) if normalize(item)]
    signals = ("학생", "중1", "중2", "중3", "고1", "고2", "고3", "예비", "오답", "시험", "단원", "문법", "독해", "서술형")
    candidates = [
        sentence for sentence in sentences
        if 45 <= len(sentence) <= 260 and sum(signal in sentence for signal in signals) >= 2
    ]
    if not candidates:
        candidates = [sentence for sentence in sentences if 35 <= len(sentence) <= 260]
    if not candidates:
        return ""
    # Prefer a concrete sentence, then select deterministically among the best few.
    ranked = sorted(candidates, key=lambda item: (-sum(signal in item for signal in signals), len(item)))[:8]
    return naturalize_text(
        stable_choice(f"{context['seed']}|student-situation", ranked),
        context,
        "student-situation",
    )


def factual_context_paragraphs(
    context: dict[str, object], situation: str,
) -> list[str]:
    locality = str(context["locality"])
    center = str(context["center"])
    address = str(context["address"])
    subject = str(context["subject"])
    grades = str(context["grades"])
    seed = str(context["seed"])

    center_variants = [
        f"{locality}에서 이용 가능한 센터로 제공된 곳은 {center}입니다. 센터 주소는 {address}입니다.",
        f"제공된 센터 자료를 기준으로 {locality} 상담과 연결된 곳은 {center}이며, 실제 방문 주소는 {address}입니다.",
        f"{locality} 학습 상담에 연결된 센터 정보는 {center}입니다. 방문 위치는 {address}로 제공되어 있습니다.",
    ]
    center_fact = stable_choice(f"{seed}|center-fact", center_variants)
    if address and locality not in address:
        center_fact += " 지역 안내명과 실제 센터 주소가 다를 수 있으므로 방문 전에 위치를 함께 확인하는 것이 좋습니다."

    facts = [center_fact]
    if grades:
        facts.append(stable_choice(
            f"{seed}|grade-fact",
            [
                f"제공된 {subject} 수업 가능 학년은 {grades}입니다. 학생의 현재 학년과 필요한 보강 범위는 상담에서 구체적으로 확인할 수 있습니다.",
                f"학년 정보는 자료상 {grades}로 제공되어 있습니다. 같은 학년이라도 현재 단원과 오답 유형을 확인한 뒤 학습 순서를 정하는 것이 필요합니다.",
                f"{center}의 제공 자료에는 {subject} 가능 학년이 {grades}로 표시되어 있습니다. 상담 전 현재 교재와 최근 시험지를 준비하면 출발점을 더 분명히 정할 수 있습니다.",
            ],
        ))
    if situation:
        facts.append(stable_choice(
            f"{seed}|situation-lead",
            [
                f"학생 상황을 구체화할 때 먼저 살필 예시는 다음과 같습니다. {situation}",
                f"이 지역 상담에서 출발점으로 삼을 학생 상황은 다음과 같습니다. {situation}",
                f"수업 순서를 정하기 전에 확인할 학습 상황 예시는 다음과 같습니다. {situation}",
            ],
        ))
    return [normalize(repair_named_josa(value, context)) for value in facts if normalize(value)]


def diversify_title_references(
    intro: str, body_sections: list[tuple[str, list[str]]], context: dict[str, object], keep: int,
) -> tuple[str, list[tuple[str, list[str]]]]:
    title = str(context["title"])
    replacements = [
        f"{context['locality']} {context['subject']} 학습",
        f"해당 {context['level']} {context['subject']} 상담",
        f"{context['center']} {context['subject']} 학습 기준",
        f"이 {context['subject']} 관리 기준",
        f"{context['region']} {context['subject']} 학습 상담",
    ]
    count = 0

    def vary(value: str, label: str) -> str:
        nonlocal count

        def replacement(_match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            if count <= keep:
                return title
            return stable_choice(f"{context['seed']}|title-ref|{label}|{count}", replacements)

        return re.sub(re.escape(title), replacement, value)

    varied_intro = vary(intro, "intro")
    varied_sections = []
    for section_index, (heading, paragraphs) in enumerate(body_sections):
        varied_sections.append((
            vary(heading, f"heading-{section_index}"),
            [vary(paragraph, f"paragraph-{section_index}-{index}") for index, paragraph in enumerate(paragraphs)],
        ))
    return varied_intro, varied_sections


def final_polish_text(value: str) -> str:
    """Remove awkward joins that can appear after deterministic title substitution."""
    text = normalize(value)
    while "상담 상담" in text:
        text = text.replace("상담 상담", "상담")
    text = re.sub(r"([가-힣]+)\s+기준\s+학습\s+방식", r"\1 방식", text)
    text = re.sub(r"([가-힣]+)\s+기준\s+학습\s+관리", r"\1 관리", text)
    text = text.replace("기준 기준", "기준")
    text = re.sub(r"항목(?=중심|관련|기준|관점)", "항목 ", text)
    return normalize(text)


def dedupe_article_sentences(
    intro: str, sections: list[tuple[str, list[str]]],
) -> tuple[str, list[tuple[str, list[str]]]]:
    """Remove exact repeats within each section while preserving section context."""

    def dedupe(value: str, seen: set[str]) -> str:
        kept = []
        for sentence in [item for item in re.split(r"(?<=[.!?])\s+", value) if normalize(item)]:
            key = normalize(sentence)
            if key in seen:
                continue
            seen.add(key)
            kept.append(sentence)
        clean = normalize(" ".join(kept))
        orphan_leads = {
            "학생 상황을 구체화할 때 먼저 살필 예시는 다음과 같습니다.",
            "이 지역 상담에서 출발점으로 삼을 학생 상황은 다음과 같습니다.",
            "수업 순서를 정하기 전에 확인할 학습 상황 예시는 다음과 같습니다.",
        }
        return "" if clean in orphan_leads else clean

    clean_intro = dedupe(intro, set())
    clean_sections = []
    for heading, paragraphs in sections:
        section_seen: set[str] = set()
        clean_paragraphs = [
            clean for paragraph in paragraphs if (clean := dedupe(paragraph, section_seen))
        ]
        clean_sections.append((heading, clean_paragraphs))
    return clean_intro, clean_sections


def individualize_body(
    intro: str, body_sections: list[tuple[str, list[str]]], context: dict[str, object],
) -> tuple[str, list[tuple[str, list[str]]]]:
    situation = select_student_situation(intro, body_sections, context)
    natural_intro = naturalize_text(intro, context, "intro")
    natural_sections = [
        (
            naturalize_text(heading, context, f"heading-{section_index}"),
            [
                naturalize_text(paragraph, context, f"paragraph-{section_index}-{paragraph_index}")
                for paragraph_index, paragraph in enumerate(paragraphs)
            ],
        )
        for section_index, (heading, paragraphs) in enumerate(body_sections)
    ]

    category = str(context["category"])
    intensive_categories = {"중학생수학학원", "중학생영어학원", "고등학생영어학원"}
    if category in intensive_categories and len(natural_sections) == 6:
        # Keep the opening/closing intent but use one of up to 24 meaningful middle
        # orders, derived from each locality's actual headings and facts.
        middle = list(range(1, 5))
        middle.sort(key=lambda index: hashlib.sha256(
            f"{context['seed']}|section-order|{natural_sections[index][0]}".encode("utf-8")
        ).hexdigest())
        natural_sections = [natural_sections[index] for index in [0, *middle, 5]]

    fact_limit = {"중학생수학학원": 4, "중학생영어학원": 3, "고등학생영어학원": 3}.get(category, 1)
    facts = factual_context_paragraphs(context, situation)[:fact_limit]
    if natural_sections:
        slot_order = list(range(len(natural_sections)))
        slot_order.sort(key=lambda index: hashlib.sha256(
            f"{context['seed']}|fact-slot|{index}".encode("utf-8")
        ).hexdigest())
        for fact_index, fact in enumerate(facts):
            slot = slot_order[fact_index]
            heading, paragraphs = natural_sections[slot]
            natural_sections[slot] = (heading, [fact, *paragraphs])

    keep = 3 if category == "중학생수학학원" else 4
    varied_intro, varied_sections = diversify_title_references(
        natural_intro, natural_sections, context, keep
    )
    polished = (
        final_polish_text(varied_intro),
        [
            (final_polish_text(heading), [final_polish_text(paragraph) for paragraph in paragraphs])
            for heading, paragraphs in varied_sections
        ],
    )
    return dedupe_article_sentences(*polished)


def naturalize_cases(cases: list[str], context: dict[str, object]) -> list[str]:
    natural_cases = []
    for index, case in enumerate(cases, 1):
        value = final_polish_text(naturalize_text(case, context, f"case-{index}"))
        sentences = [normalize(item) for item in re.split(r"(?<=[.!?])\s+", value) if normalize(item)]
        while sentences and (
            (sentences[0].startswith("아래는 ") and "예시입니다" in sentences[0])
            or ("정리한 예시입니다" in sentences[0] and "상담" in sentences[0])
            or ("실제 특정 학생의 결과를 단정하지 않고" in sentences[0] and "상담 상황" in sentences[0])
        ):
            sentences.pop(0)
        value = " ".join(sentences) or value
        value = re.sub(r"^상담 상황\s*\d+\.\s*", "", value)
        natural_cases.append(f"상담 상황 {index}. {normalize(value)}")
    return natural_cases


def compact_meta(original: str, title: str, row: dict[str, str], config: dict[str, str]) -> str:
    original = normalize(original)
    if 70 <= len(original) <= 100:
        return original
    region = normalize(f"{row['지역']} {row['시or구']}")
    value = (
        f"{region} {title}의 학교·학년별 학습 기준과 {config['subject']} 진단, "
        "과제·오답 관리, 상담 전 확인할 센터 정보를 정리했습니다."
    )
    if len(value) > 100:
        value = value[:97].rstrip(" ,·") + "."
    return value


def paragraph_html(value: str, css: str = "") -> str:
    class_attr = f' class="{css}"' if css else ""
    return f"<p{class_attr}>{esc(normalize(value))}</p>"


def schema_script(graph: list[dict]) -> str:
    value = {"@context": "https://schema.org", "@graph": graph}
    return '<script type="application/ld+json">' + json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "</script>"


def site_header(active: str = "subjects") -> str:
    links = [
        ("home", "/", "홈"),
        ("guide", "/학습가이드/", "학습가이드"),
        ("contact", "/상담문의/", "상담문의"),
        ("subjects", "/과목별학원/", "과목별학원"),
    ]
    nav = "".join(
        f'<a href="{href}"' + (' aria-current="page"' if key == active else "") + f'>{label}</a>'
        for key, href, label in links
    )
    return (
        '<a class="skip-link" href="#main">본문 바로가기</a>'
        '<header class="site-header"><div class="header-inner shell">'
        '<a class="brand" href="/" aria-label="영수코칭 홈"><span class="brand-mark" aria-hidden="true">YS</span>'
        '<span class="brand-copy"><strong>영수코칭</strong><small>ENGLISH × MATH COACHING</small></span></a>'
        f'<nav class="nav" aria-label="주요 메뉴">{nav}</nav>'
        '<a class="header-cta" href="/상담문의/">상담 준비하기</a>'
        '</div></header>'
    )


def site_footer() -> str:
    return (
        '<footer class="site-footer"><div class="footer-inner shell">'
        '<div class="footer-brand"><strong>영수코칭</strong><span>와와학습코칭센터의 영어·수학 학습관리 방식과 지역별 센터 정보를 안내합니다.<br>실제 운영 과목·대상 학년·수업 방식은 지점별로 다를 수 있으므로 상담 시 확인하세요.</span></div>'
        '<div class="footer-links"><a href="/">홈</a><a href="/학습가이드/">학습가이드</a>'
        '<a href="/상담문의/">상담문의</a><a href="/과목별학원/">과목별학원</a><a href="/sitemap.xml">사이트맵</a></div>'
        '</div></footer>'
        f'<aside class="floating-actions" aria-label="빠른 상담"><a href="tel:{PHONE_LINK}">전화</a>'
        f'<a href="https://blogsms.net/{PHONE_LINK}" target="_blank" rel="noopener">문자</a>'
        '<a href="https://docs.google.com/forms/d/e/1FAIpQLSdb2oE5Qk5YS0TfYDxyV1w-IOTkhkjOCmmpAKTI9FmqpVj6Yg/viewform" target="_blank" rel="noopener">상담</a></aside>'
    )


def page_head(
    *, title: str, description: str, canonical: str, asset_prefix: str,
    image_url: str, graph: list[dict], page_type: str = "article",
) -> str:
    return f'''<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <meta name="robots" content="index,follow,max-image-preview:large">
  <link rel="canonical" href="{esc(canonical)}">
  <link rel="alternate" type="application/rss+xml" title="영수코칭 학습 소식" href="/rss.xml">
  <link rel="icon" href="{asset_prefix}assets/favicon.svg" type="image/svg+xml">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700;800;900&amp;display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{asset_prefix}assets/site.css">
  <meta property="og:type" content="{page_type}">
  <meta property="og:locale" content="ko_KR">
  <meta property="og:site_name" content="영수코칭">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{esc(canonical)}">
  <meta property="og:image" content="{esc(SHARE_IMAGE_URL)}">
  <meta property="og:image:width" content="1731">
  <meta property="og:image:height" content="909">
  <meta property="og:image:alt" content="{esc(SHARE_IMAGE_ALT)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(title)}">
  <meta name="twitter:description" content="{esc(description)}">
  <meta name="twitter:image" content="{esc(SHARE_IMAGE_URL)}">
  <meta name="twitter:image:alt" content="{esc(SHARE_IMAGE_ALT)}">
  {schema_script(graph)}
</head>'''


def address_schema(row: dict[str, str]) -> dict:
    return {
        "@type": "PostalAddress",
        "streetAddress": normalize(row.get("센터 주소", "")),
        "addressLocality": normalize(row.get("시or구", "")),
        "addressRegion": normalize(row.get("지역", "")),
        "addressCountry": "KR",
    }


def offer_schema(row: dict[str, str]) -> list[dict]:
    url = normalize(row.get("센터 교습비", ""))
    if not url:
        return []
    return [{"@type": "Offer", "name": "센터 교습비 안내", "url": url}]


def schools_for(row: dict[str, str], field: str) -> list[str]:
    return [normalize(value) for value in row.get(field, "").split(",") if normalize(value)]


def resolve_map_file(raw_name: str, slug: str) -> str:
    map_dir = ROOT / "assets" / "maps"
    raw_name = normalize(raw_name)
    candidates = [
        raw_name,
        raw_name.replace(" ", "-"),
        raw_name.replace(" ", ""),
        f"{slug}.jpg",
        f"{slug}.png",
        f"{slug}.webp",
    ]
    for candidate in candidates:
        if candidate and (map_dir / candidate).is_file():
            return candidate
    key = re.sub(r"[^a-z0-9]", "", Path(raw_name).stem.lower())
    slug_key = re.sub(r"[^a-z0-9]", "", slug.lower())
    matches = [
        path.name for path in map_dir.iterdir()
        if path.is_file() and re.sub(r"[^a-z0-9]", "", path.stem.lower()) in {key, slug_key}
    ]
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(f"Map missing or ambiguous: raw={raw_name!r}, slug={slug!r}, matches={matches}")


def detail_graph(
    *, title: str, description: str, canonical: str, locality: str, slug: str,
    row: dict[str, str], config: dict[str, str], faq: list[tuple[str, str]],
    body_sections: list[tuple[str, list[str]]], image_url: str,
) -> list[dict]:
    org_id = canonical + "#organization"
    local_id = canonical + "#localbusiness"
    service_id = canonical + "#service"
    webpage_id = canonical + "#webpage"
    schools = schools_for(row, config["school_field"])
    school_nodes = [{"@type": "School", "name": name} for name in schools]
    offers = offer_schema(row)
    grades = [normalize(value) for value in row.get(config["grade_field"], "").split(",") if normalize(value)]
    organization: dict = {
        "@type": "EducationalOrganization", "@id": org_id,
        "name": normalize(row.get("센터명", "")) or f"{locality} 학습센터",
        "url": canonical, "telephone": "+82-10-6839-8283",
        "address": address_schema(row),
        "areaServed": {"@type": "Place", "name": locality},
    }
    if row.get("교육지원청 등록번호"):
        organization["identifier"] = normalize(row["교육지원청 등록번호"])
    if grades:
        organization["educationalLevel"] = grades
    if offers:
        organization["makesOffer"] = offers
    local_business = {
        "@type": "LocalBusiness", "@id": local_id,
        "name": organization["name"], "url": canonical,
        "telephone": "+82-10-6839-8283", "address": address_schema(row),
        "areaServed": {"@type": "Place", "name": locality},
    }
    service: dict = {
        "@type": "Service", "@id": service_id,
        "name": title, "serviceType": config["label"],
        "provider": {"@id": org_id},
        "areaServed": {"@type": "Place", "name": locality},
        "audience": {"@type": "EducationalAudience", "educationalRole": "student", "audienceType": config["level"]},
    }
    if offers:
        service["offers"] = offers
    webpage = {
        "@type": "WebPage", "@id": webpage_id, "url": canonical,
        "name": title, "description": description, "inLanguage": "ko-KR",
        "isPartOf": {"@id": DOMAIN + "/#website"},
        "about": [{"@id": org_id}, {"@id": service_id}],
        "mainEntity": {"@id": service_id},
        "breadcrumb": {"@id": canonical + "#breadcrumb"},
        "primaryImageOfPage": {"@type": "ImageObject", "contentUrl": image_url, "caption": f"{title} 수업 안내"},
        "dateModified": TODAY,
    }
    article = {
        "@type": "Article", "@id": canonical + "#article",
        "headline": title, "description": description,
        "mainEntityOfPage": {"@id": webpage_id},
        "author": {"@id": org_id},
        "publisher": {"@type": "Organization", "name": SITE_NAME, "url": DOMAIN + "/"},
        "image": {"@type": "ImageObject", "url": image_url, "caption": f"{title} 수업 안내"},
        "about": [{"@id": service_id}, {"@type": "Thing", "name": locality}, {"@type": "Thing", "name": config["subject"]}],
        "mentions": school_nodes,
        "articleSection": ["과목별학원", config["label"], row.get("지역", ""), row.get("시or구", ""), locality],
        "hasPart": [{"@type": "WebPageElement", "name": heading} for heading, _ in body_sections],
        "datePublished": TODAY, "dateModified": TODAY, "inLanguage": "ko-KR",
    }
    breadcrumb = {
        "@type": "BreadcrumbList", "@id": canonical + "#breadcrumb",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "홈", "item": DOMAIN + "/"},
            {"@type": "ListItem", "position": 2, "name": "과목별학원", "item": absolute_url("과목별학원")},
            {"@type": "ListItem", "position": 3, "name": config["label"], "item": absolute_url("과목별학원", config["slug"])},
            {"@type": "ListItem", "position": 4, "name": title, "item": canonical},
        ],
    }
    faq_page = {
        "@type": "FAQPage", "@id": canonical + "#faq",
        "mainEntity": [
            {"@type": "Question", "name": question, "acceptedAnswer": {"@type": "Answer", "text": answer}}
            for question, answer in faq
        ],
    }
    related = []
    related_categories = [item for item in CATEGORIES if item["slug"] != config["slug"]]
    for position, item in enumerate(related_categories, 1):
        related.append({
            "@type": "ListItem", "position": position,
            "name": f"{locality} {item['label']}",
            "url": absolute_url("과목별학원", item["slug"], slug),
        })
    item_list = {"@type": "ItemList", "@id": canonical + "#related", "name": f"{locality} 관련 학원 안내", "itemListElement": related}
    return [organization, local_business, webpage, breadcrumb, article, service, faq_page, item_list]


def detail_page(
    *, config: dict[str, str], sections: dict[str, str], locality: str,
    slug: str, row: dict[str, str], map_file: str, representative_image: str,
) -> str:
    title = normalize(sections["페이지타이틀"])
    context = content_context(title=title, locality=locality, slug=slug, row=row, config=config)
    description = final_polish_text(naturalize_text(
        compact_meta(sections["메타설명"], title, row, config), context, "meta-description"
    ))
    raw_intro, raw_body_sections = parse_body(sections["본문"])
    intro, body_sections = individualize_body(raw_intro, raw_body_sections, context)
    # The same transformed FAQ list feeds both the visible accordions and
    # FAQPage JSON-LD, so their questions and answers cannot drift apart.
    faq = [
        (
            final_polish_text(naturalize_text(question, context, f"faq-question-{index}")),
            final_polish_text(naturalize_text(answer, context, f"faq-answer-{index}")),
        )
        for index, (question, answer) in enumerate(parse_faq(sections["FAQ"]), 1)
    ]
    cases = naturalize_cases(parse_cases(sections["학부모후기"]), context)
    summary = final_polish_text(naturalize_text(sections["JSON-LD 요약"], context, "summary"))
    if len(faq) != 4 or len(body_sections) != 6:
        raise ValueError(f"Unexpected content shape: {title}: body={len(body_sections)} faq={len(faq)}")
    canonical = absolute_url("과목별학원", config["slug"], slug)
    body_image_name = "seoul6839.webp" if row.get("지역") == "서울" else "local6839.webp"
    body_image = f"../../../assets/centers/common/{body_image_name}"
    map_image = f"../../../assets/maps/{map_file}"
    image_url = DOMAIN + f"/assets/centers/common/{body_image_name}"
    graph = detail_graph(
        title=title, description=description, canonical=canonical, locality=locality, slug=slug,
        row=row, config=config, faq=faq, body_sections=body_sections, image_url=image_url,
    )
    body_sections_html = "".join(
        '<section class="academy-article-section">'
        f'<h2>{esc(heading)}</h2>' + "".join(paragraph_html(value) for value in paragraphs) + "</section>"
        for heading, paragraphs in body_sections
    )
    faq_html = "".join(
        f'<details><summary>{esc(question)}</summary><p>{esc(answer)}</p></details>'
        for question, answer in faq
    )
    cases_html = "".join(f'<blockquote class="academy-case-card">{esc(value)}</blockquote>' for value in cases)
    schools = schools_for(row, config["school_field"])
    school_tags = "".join(f"<span>{esc(value)}</span>" for value in schools)
    grades = normalize(row.get(config["grade_field"], "")) or "상담 시 현재 학년과 과목을 확인합니다."
    identifier = normalize(row.get("교육지원청 등록번호", "")) or "제공 자료에서 확인 후 안내"
    tuition = normalize(row.get("센터 교습비", ""))
    tuition_html = (
        f'<a class="btn btn-outline academy-fee-link" href="{esc(tuition)}" target="_blank" rel="noopener">센터 교습비 안내 확인</a>'
        if tuition else ""
    )
    related_links = "".join(
        f'<a href="/과목별학원/{item["slug"]}/{esc(slug)}/">{esc(locality)} {esc(item["label"])}</a>'
        for item in CATEGORIES if item["slug"] != config["slug"]
    )
    head = page_head(
        title=f"{title} | {SITE_NAME}", description=description, canonical=canonical,
        asset_prefix="../../../", image_url=image_url, graph=graph,
    )
    return f'''<!doctype html>
<html lang="ko">
{head}
<body class="academy-page">
  {site_header("subjects")}
  <main id="main">
    <header class="academy-hero reveal">
      <div class="academy-hero-copy">
        <nav class="academy-breadcrumb" aria-label="현재 위치"><a href="/">홈</a><span>›</span><a href="/과목별학원/">과목별학원</a><span>›</span><a href="/과목별학원/{esc(config['slug'])}/">{esc(config['label'])}</a><span>›</span><span aria-current="page">{esc(title)}</span></nav>
        <p class="eyebrow">{esc(config['english'])} · LOCAL GUIDE</p>
        <h1>{esc(title)}</h1>
        <p class="lead">{esc(description)}</p>
      </div>
      <aside class="academy-hero-aside"><strong>{esc(locality)}</strong><span>{esc(row.get('지역'))} · {esc(row.get('시or구'))} 학습 안내</span></aside>
    </header>

    <section class="academy-media-section" aria-label="{esc(title)} 이미지 안내">
      <div class="academy-media-grid">
        <img class="academy-representative-image" src="{esc(representative_image)}" alt="{esc(title)} 대표" style="display:none;">
        <figure class="academy-main-media reveal"><img src="{esc(body_image)}" width="1300" height="1900" alt="{esc(title)} 수업 안내 {esc(SITE_NAME)}" fetchpriority="high"><figcaption>{esc(title)} 학습관리 안내</figcaption></figure>
        <figure class="academy-map-card reveal"><img src="{esc(map_image)}" alt="{esc(title)} 지도 {esc(SITE_NAME)}" loading="lazy"><figcaption>{esc(locality)} 센터 위치 참고 지도</figcaption></figure>
      </div>
    </section>

    <div class="academy-content-wrap">
      <section class="academy-summary reveal" aria-labelledby="summary-title"><h2 id="summary-title">30초 핵심 요약</h2><p>{esc(summary)}</p></section>

      <section class="academy-facts reveal" aria-labelledby="facts-title">
        <p class="eyebrow">Verified Center Information</p><h2 id="facts-title">상담 전에 확인할 센터 정보</h2>
        <div class="academy-fact-grid">
          <div class="academy-fact-card"><strong>센터</strong><span>{esc(row.get('센터명'))}</span></div>
          <div class="academy-fact-card"><strong>주소</strong><span>{esc(row.get('센터 주소'))}</span></div>
          <div class="academy-fact-card"><strong>수업 가능 학년</strong><span>{esc(grades)}</span></div>
          <div class="academy-fact-card"><strong>교육지원청 등록 정보</strong><span>{esc(identifier)}</span></div>
        </div>
        {('<div class="academy-school-tags" aria-label="제공 자료에 포함된 수업 학교">' + school_tags + '</div>') if school_tags else ''}
        {tuition_html}
      </section>

      <article class="academy-article reveal" aria-labelledby="article-title">
        <p class="eyebrow">Local Learning Article</p><h2 id="article-title">{esc(title)} 선택과 학습관리 기준</h2>
        {paragraph_html(intro, 'lead')}
        {body_sections_html}
      </article>

      <section class="academy-faq reveal" aria-labelledby="faq-title"><p class="eyebrow">Frequently Asked Questions</p><h2 id="faq-title">{esc(title)} 자주 묻는 질문</h2><div class="faq-list">{faq_html}</div></section>

      <section class="academy-cases reveal" aria-labelledby="case-title"><p class="eyebrow blue">Consultation Scenarios</p><h2 id="case-title">상담 상황 예시</h2><p class="academy-case-note">아래 내용은 학생의 학습 상황을 설명하기 위한 예시이며 실제 학생의 후기나 성과를 뜻하지 않습니다.</p><div class="academy-case-list">{cases_html}</div></section>
    </div>

    <section class="academy-related"><div class="academy-related-panel reveal"><p class="eyebrow">Related Local Guides</p><h2>{esc(locality)} 다른 과목·학년 안내</h2><div class="academy-related-grid">{related_links}<a href="/과목별학원/{esc(config['slug'])}/">{esc(config['label'])} 전체 지역</a><a href="/과목별학원/">과목별학원 전체 보기</a></div></div></section>
  </main>
  {site_footer()}
  <script src="../../../assets/site.js" defer></script>
</body>
</html>'''


def directory_html(rows: list[dict[str, str]], config: dict[str, str]) -> str:
    grouped: OrderedDict[str, OrderedDict[str, list[dict[str, str]]]] = OrderedDict()
    for row in rows:
        grouped.setdefault(row["지역"], OrderedDict()).setdefault(row["시or구"], []).append(row)
    groups = []
    for region, cities in grouped.items():
        city_html = []
        region_count = sum(len(values) for values in cities.values())
        for city, values in cities.items():
            links = "".join(
                f'<a class="academy-local-link" data-locality="{esc(value["근처 수업가능 동네"])}" href="/과목별학원/{esc(config["slug"])}/{esc(value["근처 수업가능 동네"])}/"><span>{esc(value["근처 수업가능 동네"])}</span></a>'
                for value in values
            )
            city_html.append(
                f'<section class="academy-city-group" data-city="{esc(city)}"><h3 class="academy-city-title">{esc(city)} <small>{len(values)}곳</small></h3><div class="academy-local-grid">{links}</div></section>'
            )
        groups.append(
            f'<details class="academy-region-group" data-region="{esc(region)}"><summary><span class="academy-region-heading"><strong>{esc(region)}</strong><small>{len(cities)}개 시군구 · {region_count}개 동네</small></span><span class="academy-region-toggle" aria-hidden="true"></span></summary><div class="academy-region-content">{"".join(city_html)}</div></details>'
        )
    return "".join(groups)


def category_hub(rows: list[dict[str, str]], config: dict[str, str]) -> str:
    canonical = absolute_url("과목별학원", config["slug"])
    title = f"지역별 {config['label']} 안내 | {SITE_NAME}"
    description = f"전국 371개 동네의 {config['label']} 학습 기준과 센터 정보를 지역·시군구별로 찾아볼 수 있도록 정리했습니다."
    item_list = {
        "@type": "ItemList", "@id": canonical + "#directory", "name": f"지역별 {config['label']}",
        "numberOfItems": len(rows),
        "itemListElement": [
            {"@type": "ListItem", "position": index, "name": f"{row['근처 수업가능 동네']} {config['label']}", "url": absolute_url("과목별학원", config["slug"], row["근처 수업가능 동네"])}
            for index, row in enumerate(rows, 1)
        ],
    }
    graph = [
        {"@type": "CollectionPage", "@id": canonical + "#webpage", "url": canonical, "name": title, "description": description, "isPartOf": {"@id": DOMAIN + "/#website"}, "about": {"@type": "Thing", "name": config["label"]}, "dateModified": TODAY, "inLanguage": "ko-KR"},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "홈", "item": DOMAIN + "/"},
            {"@type": "ListItem", "position": 2, "name": "과목별학원", "item": absolute_url("과목별학원")},
            {"@type": "ListItem", "position": 3, "name": config["label"], "item": canonical},
        ]},
        item_list,
    ]
    head = page_head(title=title, description=description, canonical=canonical, asset_prefix="../../", image_url=DOMAIN + "/assets/images/english-math-coaching.webp", graph=graph, page_type="website")
    directory = directory_html(rows, config)
    return f'''<!doctype html><html lang="ko">{head}<body class="academy-page">{site_header("subjects")}<main id="main">
      <header class="academy-hero reveal"><div class="academy-hero-copy"><nav class="academy-breadcrumb" aria-label="현재 위치"><a href="/">홈</a><span>›</span><a href="/과목별학원/">과목별학원</a><span>›</span><span aria-current="page">{esc(config['label'])}</span></nav><p class="eyebrow">{esc(config['english'])} DIRECTORY</p><h1>지역별 {esc(config['label'])} 안내</h1><p class="lead">{esc(description)}</p></div><aside class="academy-hero-aside"><strong>371</strong><span>제공된 지역·센터 정보와 개별 학습 안내를 연결한 동네별 자료</span></aside></header>
      <section class="section section-compact"><div class="academy-directory reveal"><div class="academy-directory-head"><div><p class="eyebrow">Local Academy Directory</p><h2>동네 이름으로 빠르게 찾기</h2><p>광역지역과 시군구를 펼치거나 동네 이름을 검색해 해당 페이지로 이동하세요.</p></div><label class="academy-search-label">동네 검색<input class="academy-search-input" type="search" placeholder="예: 명일동, 불당동" autocomplete="off"></label></div><div class="academy-directory-tools"><button type="button" data-action="expand">모두 펼치기</button><button type="button" data-action="collapse">모두 접기</button><span class="academy-result-count" aria-live="polite">전체 371개 동네</span></div><div class="academy-region-list">{directory}</div></div></section>
      <section class="cta-section"><div class="cta-panel shell reveal"><p class="eyebrow">Compare With A Clear Standard</p><h2>지역 이름보다 학생의 현재 학습 상태를 먼저 확인하세요.</h2><p class="lead">각 동네 페이지에서 학습 안내, 수업 가능 학년, 학교 자료와 상담 전 확인 기준을 살펴볼 수 있습니다.</p><div class="actions"><a class="btn btn-primary" href="/상담문의/">상담 준비하기</a><a class="btn btn-blue" href="/과목별학원/">다른 카테고리 보기</a></div></div></section>
    </main>{site_footer()}<script src="../../assets/site.js" defer></script></body></html>'''


def subject_hub() -> str:
    canonical = absolute_url("과목별학원")
    title = f"과목별학원 | {SITE_NAME}"
    description = "고등학생·중학생 영어와 수학의 지역별 학습 안내를 과목과 학년 단계에 따라 찾아볼 수 있도록 정리했습니다."
    items = [
        {"@type": "ListItem", "position": index, "name": config["label"], "url": absolute_url("과목별학원", config["slug"])}
        for index, config in enumerate(CATEGORIES, 1)
    ]
    graph = [
        {"@type": "CollectionPage", "@id": canonical + "#webpage", "url": canonical, "name": title, "description": description, "isPartOf": {"@id": DOMAIN + "/#website"}, "dateModified": TODAY, "inLanguage": "ko-KR"},
        {"@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": 1, "name": "홈", "item": DOMAIN + "/"}, {"@type": "ListItem", "position": 2, "name": "과목별학원", "item": canonical}]},
        {"@type": "ItemList", "name": "과목별학원 카테고리", "numberOfItems": len(items), "itemListElement": items},
    ]
    cards = "".join(
        f'<a class="academy-category-card reveal" href="/과목별학원/{esc(config["slug"])}/"><span class="tag">{esc(config["english"])}</span><h2>{esc(config["label"])}</h2><p>{esc(config["summary"])}</p><span class="arrow" aria-hidden="true">→</span></a>'
        for config in CATEGORIES
    )
    head = page_head(title=title, description=description, canonical=canonical, asset_prefix="../", image_url=DOMAIN + "/assets/images/english-math-coaching.webp", graph=graph, page_type="website")
    return f'''<!doctype html><html lang="ko">{head}<body class="academy-page">{site_header("subjects")}<main id="main">
      <header class="academy-hero reveal"><div class="academy-hero-copy"><nav class="academy-breadcrumb" aria-label="현재 위치"><a href="/">홈</a><span>›</span><span aria-current="page">과목별학원</span></nav><p class="eyebrow">Subject &amp; Grade Academy Guide</p><h1>과목과 학년을 먼저 고르고,<br>동네별 안내를 확인하세요.</h1><p class="lead">영어와 수학은 학년 단계에 따라 확인할 학교 학습과 관리 기준이 달라집니다. 필요한 카테고리를 선택하면 371개 동네별 학습 안내와 제공된 센터 정보를 확인할 수 있습니다.</p></div><aside class="academy-hero-aside"><strong>4 × 371</strong><span>4개 카테고리 · 1,484개 지역별 학습 안내</span></aside></header>
      <section class="section"><div class="section-head reveal"><p class="eyebrow blue">Choose A Learning Track</p><h2>현재 학년과 과목에 맞는 안내</h2><p class="lead">학년과 과목별로 확인할 기준을 나누고, 동네 페이지는 제공된 개별 학습 안내와 실제 센터 자료를 기반으로 구성했습니다.</p></div><div class="academy-category-grid">{cards}</div></section>
      <section class="process-band"><div class="section"><div class="process-intro reveal"><p class="eyebrow">How To Use</p><h2>페이지를 확인하는 순서</h2><p class="lead">광고 문구보다 학생에게 적용할 수 있는 정보가 있는지 차례로 확인하세요.</p></div><div class="process-list"><article class="process-item reveal"><div><h3>학년·과목 선택</h3><p>고등학생과 중학생, 영어와 수학 중 현재 필요한 카테고리를 고릅니다.</p></div></article><article class="process-item reveal"><div><h3>동네·센터 정보 확인</h3><p>지역 검색을 사용해 주소, 수업 가능 학년, 학교와 교습비 안내 자료를 확인합니다.</p></div></article><article class="process-item reveal"><div><h3>학습 안내와 FAQ 비교</h3><p>학생 상황, 학교 학습, 과제·오답 관리 기준과 상담 질문을 읽어봅니다.</p></div></article><article class="process-item reveal"><div><h3>상담 전 우선순위 정리</h3><p>최근 학습 결과와 어려운 단원을 준비해 먼저 해결할 문제를 정합니다.</p></div></article></div></div></section>
      <section class="cta-section"><div class="cta-panel shell reveal"><p class="eyebrow">Start With The Student</p><h2>카테고리를 고른 뒤에는 학생의 현재 기록을 함께 보세요.</h2><p class="lead">같은 동네와 학년이어도 필요한 수업 순서는 다를 수 있습니다. 최근 자료를 기준으로 상담의 첫 질문을 정리해보세요.</p><div class="actions"><a class="btn btn-primary" href="/상담문의/">상담 준비하기</a><a class="btn btn-blue" href="/학습가이드/">학습가이드 보기</a></div></div></section>
    </main>{site_footer()}<script src="../assets/site.js" defer></script></body></html>'''


def write_sitemap() -> int:
    pages: list[tuple[str, Path]] = []
    for path in ROOT.rglob("index.html"):
        relative_parts = path.relative_to(ROOT).parts
        if any(part in IGNORED_PUBLIC_DIRS for part in relative_parts):
            continue
        rel = path.relative_to(ROOT)
        parts = list(rel.parts[:-1])
        url = DOMAIN + ("/" if not parts else quote("/" + "/".join(parts) + "/", safe="/"))
        pages.append((url, path))
    pages.sort(key=lambda item: (item[0].count("/"), item[0]))
    urls = [url for url, _ in pages]
    if len(urls) != len(set(urls)):
        raise ValueError("Duplicate sitemap URLs")
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("", namespace)
    root = ET.Element(ET.QName(namespace, "urlset"))
    for url, path in pages:
        item = ET.SubElement(root, ET.QName(namespace, "url"))
        ET.SubElement(item, ET.QName(namespace, "loc")).text = url
        ET.SubElement(item, ET.QName(namespace, "lastmod")).text = (
            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date().isoformat()
        )
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(ROOT / "sitemap.xml", encoding="utf-8", xml_declaration=True)
    return len(urls)


def write_rss() -> None:
    build_date = format_datetime(datetime.now(timezone.utc))
    entries = [
        ("영어·수학 학습가이드", absolute_url("학습가이드"), "영어와 수학의 진단, 실행관리, 오답 재학습 기준을 안내합니다."),
        ("과목별학원", absolute_url("과목별학원"), "고등학생·중학생 영어와 수학의 지역별 안내를 정리했습니다."),
    ] + [
        (config["label"], absolute_url("과목별학원", config["slug"]), config["summary"])
        for config in CATEGORIES
    ]
    items = "\n".join(
        f"    <item><title>{esc(title)}</title><link>{esc(url)}</link><guid isPermaLink=\"true\">{esc(url)}</guid><pubDate>{build_date}</pubDate><description>{esc(description)}</description></item>"
        for title, url, description in entries
    )
    rss = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>
  <title>영수코칭 학습 소식</title><link>{DOMAIN}/</link><description>영어·수학 학습관리와 과목별 지역 안내</description><language>ko-KR</language><lastBuildDate>{build_date}</lastBuildDate>
  <atom:link href="{DOMAIN}/rss.xml" rel="self" type="application/rss+xml" />
{items}
</channel></rss>
'''
    (ROOT / "rss.xml").write_text(rss, encoding="utf-8")


def write_llms() -> None:
    lines = [
        "# 영수코칭", "", "영수코칭은 영어와 수학의 학습 상태를 과목별로 진단하고 계획·실행·오답 재학습을 연결하는 학습 안내 사이트입니다.", "",
        "## 주요 페이지", f"- 홈: {DOMAIN}/", f"- 학습가이드: {absolute_url('학습가이드')}", f"- 상담문의: {absolute_url('상담문의')}", f"- 과목별학원: {absolute_url('과목별학원')}",
    ]
    lines.extend(f"- {config['label']}: {absolute_url('과목별학원', config['slug'])}" for config in CATEGORIES)
    lines.extend(["", "## 콘텐츠 원칙", "- 지역 상세페이지는 제공된 개별 학습 안내와 371개 센터 자료를 기반으로 합니다.", "- 학교명·주소·수업 가능 학년·교습비 링크는 제공 자료에 있을 때만 표시합니다.", "- 영수코칭은 와와학습코칭센터의 영어·수학 학습관리 방식과 지역별 센터 정보를 안내합니다.", "- 실제 운영 과목·대상 학년·수업 방식은 지점별로 다를 수 있으므로 상담 시 확인해야 합니다.", "- 상담 상황 예시는 실제 학생의 후기나 성과를 뜻하지 않습니다.", ""])
    (ROOT / "llms.txt").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    center_rows = load_csv("센터정보 정리.csv")
    map_rows = load_csv("이미지링크.csv")
    if len(center_rows) != 371 or len(map_rows) != 371:
        raise ValueError(f"Expected 371 data rows: centers={len(center_rows)} maps={len(map_rows)}")
    center_by_locality = {row["근처 수업가능 동네"]: row for row in center_rows}
    map_by_locality = {row["제목"]: row["지도"] for row in map_rows}
    if set(center_by_locality) != set(map_by_locality):
        raise ValueError("Center and map locality sets differ")
    TARGET_ROOT.mkdir(parents=True, exist_ok=True)
    representative_images = prepare_representative_images()
    locality_indexes = {
        locality: index for index, locality in enumerate(sorted(center_by_locality))
    }
    (TARGET_ROOT / "index.html").write_text(subject_hub(), encoding="utf-8")
    generated = 0
    category_report = {}
    all_titles: set[str] = set()
    for category_index, config in enumerate(CATEGORIES):
        zip_path = SOURCE_DIR / config["zip"]
        if not zip_path.exists():
            raise FileNotFoundError(zip_path)
        category_dir = TARGET_ROOT / config["slug"]
        if category_dir.exists():
            shutil.rmtree(category_dir)
        category_dir.mkdir(parents=True, exist_ok=True)
        with ZipFile(zip_path) as archive:
            names = sorted(name for name in archive.namelist() if name.lower().endswith(".txt"))
            if len(names) != 371:
                raise ValueError(f"{config['zip']}: expected 371 TXT, got {len(names)}")
            seen_localities = set()
            meta_lengths = []
            for name in names:
                raw = archive.read(name).decode("utf-8-sig")
                sections = parse_sections(raw)
                required = ["페이지타이틀", "메타설명", "본문", "FAQ", "학부모후기", "JSON-LD 요약"]
                if list(sections) != required:
                    raise ValueError(f"{name}: section mismatch: {list(sections)}")
                title = normalize(sections["페이지타이틀"])
                suffix = " " + config["label"]
                if not title.endswith(suffix):
                    raise ValueError(f"{name}: title/category mismatch: {title}")
                locality = title[: -len(suffix)].strip()
                if locality not in center_by_locality:
                    raise ValueError(f"{name}: no center mapping for {locality}")
                if locality in seen_localities:
                    raise ValueError(f"{name}: duplicate locality {locality}")
                seen_localities.add(locality)
                if title in all_titles:
                    raise ValueError(f"Duplicate title across categories: {title}")
                all_titles.add(title)
                row = center_by_locality[locality]
                slug = locality
                map_file = resolve_map_file(map_by_locality[locality], row["동 영어"])
                representative_image = "../../../assets/representative/" + representative_image_name(
                    representative_images,
                    category_index=category_index,
                    locality_index=locality_indexes[locality],
                )
                target = category_dir / slug
                target.mkdir(parents=True, exist_ok=True)
                page = detail_page(
                    config=config,
                    sections=sections,
                    locality=locality,
                    slug=slug,
                    row=row,
                    map_file=map_file,
                    representative_image=representative_image,
                )
                (target / "index.html").write_text(page, encoding="utf-8")
                meta = compact_meta(sections["메타설명"], title, row, config)
                meta_lengths.append(len(meta))
                generated += 1
            if seen_localities != set(center_by_locality):
                raise ValueError(f"{config['zip']}: locality set mismatch")
        (category_dir / "index.html").write_text(category_hub(center_rows, config), encoding="utf-8")
        category_report[config["slug"]] = {"pages": len(seen_localities), "meta_min": min(meta_lengths), "meta_max": max(meta_lengths)}
    sitemap_count = write_sitemap()
    write_rss()
    write_llms()
    report = {
        "generated_detail_pages": generated,
        "category_hubs": len(CATEGORIES),
        "representative_images": len(representative_images),
        "sitemap_urls": sitemap_count,
        "categories": category_report,
        "date": TODAY,
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "subject_generation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
