"""Generate the public sitemap and a curated RSS feed for 영수코칭."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from html import unescape
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "https://xn--9p4bn5e3wjn0a.com"
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
ATOM_NS = "http://www.w3.org/2005/Atom"
IGNORED_PARTS = {".git", ".vercel", "node_modules", "reports", "tmp", "tools"}

RSS_PATHS = (
    "학습가이드/index.html",
    "과목별학원/index.html",
    "과목별학원/고등학생수학학원/index.html",
    "과목별학원/고등학생영어학원/index.html",
    "과목별학원/중학생수학학원/index.html",
    "과목별학원/중학생영어학원/index.html",
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def meta_value(source: str, name: str) -> str:
    patterns = (
        rf'<meta\s+name=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)["\']',
        rf'<meta\s+content=["\']([^"\']*)["\'][^>]*name=["\']{re.escape(name)}["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            return unescape(match.group(1).strip())
    return ""


def page_title(source: str) -> str:
    match = re.search(r"<title>(.*?)</title>", source, flags=re.IGNORECASE | re.DOTALL)
    return unescape(re.sub(r"\s+", " ", match.group(1)).strip()) if match else "영수코칭"


def canonical_url(source: str, path: Path) -> str:
    patterns = (
        r'<link\s+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']',
        r'<link\s+href=["\']([^"\']+)["\'][^>]*rel=["\']canonical["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            return unescape(match.group(1).strip())

    relative = path.relative_to(ROOT)
    parts = relative.parts[:-1]
    return DOMAIN + ("/" if not parts else "/" + "/".join(parts) + "/")


def public_pages() -> list[tuple[str, Path]]:
    pages: list[tuple[str, Path]] = []
    for path in ROOT.rglob("index.html"):
        relative = path.relative_to(ROOT)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        source = read_text(path)
        pages.append((canonical_url(source, path), path))

    pages.sort(key=lambda item: (item[0].count("/"), item[0]))
    urls = [url for url, _ in pages]
    if len(urls) != len(set(urls)):
        raise ValueError("Duplicate canonical URLs found while generating sitemap.xml")
    if any(not url.startswith(DOMAIN + "/") for url in urls):
        raise ValueError("A sitemap URL points outside the production domain")
    return pages


def write_sitemap(pages: list[tuple[str, Path]]) -> None:
    ET.register_namespace("", SITEMAP_NS)
    root = ET.Element(ET.QName(SITEMAP_NS, "urlset"))
    for url, path in pages:
        item = ET.SubElement(root, ET.QName(SITEMAP_NS, "url"))
        ET.SubElement(item, ET.QName(SITEMAP_NS, "loc")).text = url
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date().isoformat()
        ET.SubElement(item, ET.QName(SITEMAP_NS, "lastmod")).text = modified
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(ROOT / "sitemap.xml", encoding="utf-8", xml_declaration=True)


def write_rss() -> None:
    ET.register_namespace("atom", ATOM_NS)
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "영수코칭 학습 소식"
    ET.SubElement(channel, "link").text = DOMAIN + "/"
    ET.SubElement(channel, "description").text = "영어·수학 학습관리와 과목별 지역 안내"
    ET.SubElement(channel, "language").text = "ko-KR"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))
    ET.SubElement(
        channel,
        ET.QName(ATOM_NS, "link"),
        {"href": DOMAIN + "/rss.xml", "rel": "self", "type": "application/rss+xml"},
    )

    for relative in RSS_PATHS:
        path = ROOT / relative
        if not path.exists():
            raise FileNotFoundError(f"RSS source page is missing: {relative}")
        source = read_text(path)
        url = canonical_url(source, path)
        title = page_title(source)
        description = meta_value(source, "description") or "영수코칭 학습 안내"
        published = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "link").text = url
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = url
        ET.SubElement(item, "pubDate").text = format_datetime(published)
        ET.SubElement(item, "description").text = description

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(ROOT / "rss.xml", encoding="utf-8", xml_declaration=True)


def main() -> None:
    pages = public_pages()
    write_sitemap(pages)
    write_rss()
    print(f"Generated sitemap.xml ({len(pages):,} URLs) and rss.xml ({len(RSS_PATHS)} items)")


if __name__ == "__main__":
    main()
