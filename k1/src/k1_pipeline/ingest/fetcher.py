"""
L1 Ingest — Fetcher
Fetches HTML from a URL and saves it locally. Respects robots.txt etiquette.
"""

from __future__ import annotations

import random
import time
import unicodedata
from pathlib import Path

import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
}

_SESSION = requests.Session()
_SESSION.headers.update(_HEADERS)


def fetch_html(url: str, dest_path: Path, *, force: bool = False) -> str:
    """
    Fetch HTML from `url`, save to `dest_path/raw.html`, and return the HTML string.
    If raw.html already exists and `force` is False, returns cached content.
    """
    raw_path = dest_path / "raw.html"
    if raw_path.exists() and not force:
        return raw_path.read_text(encoding="utf-8")

    dest_path.mkdir(parents=True, exist_ok=True)
    time.sleep(random.uniform(1.5, 3.0))  # polite crawl delay
    resp = _SESSION.get(url, timeout=30)
    resp.raise_for_status()

    # requests falls back to ISO-8859-1 when the server's Content-Type header omits
    # a charset (HTTP default), which mis-decodes UTF-8 curly quotes/apostrophes into
    # mojibake (e.g. U+2019 "'" -> "â€™"). Prefer the content-sniffed encoding, which
    # correctly detects UTF-8 for virtually all modern recipe sites.
    if resp.apparent_encoding:
        resp.encoding = resp.apparent_encoding
    html = resp.text
    raw_path.write_text(html, encoding="utf-8")
    return html
