from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
HTML_FILES = sorted(ROOT.rglob("*.html"))
errors: list[str] = []

for path in HTML_FILES:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(ROOT).as_posix()
    if len(re.findall(r"<h1\b", text, flags=re.I)) != 1:
        errors.append(f"{rel}: H1 count is not 1")
    if rel != "404.html":
        for marker in ('<title>', 'name="description"', 'rel="canonical"', 'property="og:url"'):
            if marker not in text:
                errors.append(f"{rel}: missing {marker}")
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, flags=re.I | re.S):
        try:
            json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{rel}: invalid JSON-LD ({exc})")
    for href in re.findall(r'href="([^"]+)"', text, flags=re.I):
        if href.startswith(("http://", "https://", "tel:", "mailto:", "#")):
            continue
        target = href.split("#", 1)[0].split("?", 1)[0]
        if not target:
            continue
        base = ROOT if target.startswith("/") else path.parent
        target_path = base / unquote(target.lstrip("/"))
        if target.endswith("/"):
            target_path /= "index.html"
        elif target_path.suffix == "":
            target_path /= "index.html"
        if not target_path.exists():
            errors.append(f"{rel}: broken internal link {href}")
    for src in re.findall(r'src="([^"]+)"', text, flags=re.I):
        if src.startswith(("http://", "https://", "data:")):
            continue
        base = ROOT if src.startswith("/") else path.parent
        if not (base / unquote(src.lstrip("/"))).exists():
            errors.append(f"{rel}: missing asset {src}")

if errors:
    print("VALIDATION FAILED")
    print("\n".join(f"- {item}" for item in errors))
    sys.exit(1)

print(f"VALIDATION PASSED: {len(HTML_FILES)} HTML files")
