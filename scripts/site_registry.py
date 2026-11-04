#!/usr/bin/env python3
"""
The site catalogue: where the addresses come from, when they were last checked, what happened.

`sites.json` is both the plan `auto_update.py --config` reads and the registry this module
writes. Every entry keeps its provenance so a list can be audited later:

    {
      "url": "https://ornek.com",
      "status": "ok",                 # candidate -> ok | unusable | unreachable -> planned
      "score": 0.93,                  # how much the page still looks like itself
      "title": "Örnek",
      "sources": ["domains.txt:12", "bookmarks.html:Filmler/Örnek"],
      "added": "2026-11-04",
      "checked": "2026-11-04",
      "plugin": "Ornek",
      "create": true,
      "name": "Örnek", "lang": "tr", "search_path": "/arama?q=%s", "home_sections": [...]
    }

Address lists are read from plain text, CSV/TSV, browser bookmarks (HTML) and Markdown.
Only the address itself is stored; nothing is fetched here.

Only standard library is required.
"""
from __future__ import annotations

import csv
import datetime
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

# Things that are never a content source: search engines, social networks, shops, references.
DENY_DOMAINS = (
    "google.com", "google.com.tr", "yandex.com", "yandex.com.tr", "yandex.ru", "bing.com",
    "duckduckgo.com", "search.brave.com", "yahoo.com", "wikipedia.org", "imdb.com",
    "youtube.com", "youtu.be", "dailymotion.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "tiktok.com", "pinterest.com", "reddit.com", "telegram.org",
    "amazon.com", "amazon.com.tr", "trendyol.com", "hepsiburada.com", "github.com",
    "gitlab.com", "medium.com", "blogspot.com", "wordpress.com", "netflix.com",
    "primevideo.com", "disneyplus.com", "blutv.com", "exxen.com", "todtv.com.tr",
    "mubi.com", "apple.com", "spotify.com",
)
SKIP_PREFIXES = ("#", "javascript:", "mailto:", "tel:", "data:", "file:", "chrome:", "about:")
URL_IN_TEXT = re.compile(r"https?://[^\s<>\"'\)\]]+", re.I)
BARE_HOST = re.compile(r"[\w-]+(\.[\w-]+)+(:\d+)?(/[^\s]*)?")
MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
ANCHOR = re.compile(r"<a\s[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")


class RegistryError(Exception):
    """The catalogue or an address list could not be read; the message is user-facing."""


def today() -> str:
    return datetime.date.today().isoformat()


# ---------------------------------------------------------------- addresses

def normalize(value: str) -> str | None:
    """'ornek.com/yol' -> 'https://ornek.com'; None for anything that is not a web address."""
    text = value.strip().strip("<>()[]\"'" + " \t")
    if not text or text.lower().startswith(SKIP_PREFIXES):
        return None
    if "://" not in text:
        if not BARE_HOST.fullmatch(text):
            return None
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def key_of(url: str) -> str:
    """What identifies a site across http/https, www. and paths: 'ornek.com'."""
    return (urlsplit(url).netloc or "").lower().removeprefix("www.")


def is_denied(netloc: str) -> bool:
    host = key_of(f"http://{netloc}")
    return any(host == domain or host.endswith("." + domain) for domain in DENY_DOMAINS)


def strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub(" ", html)).strip()


# ------------------------------------------------------------- list readers

def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise RegistryError(f"{path} okunamadı: {e}") from e


def _rows(path: Path) -> list[dict]:
    """One {url, title, source} per address found in the file."""
    suffix = path.suffix.lower()
    text = _read_text(path)
    if suffix in (".csv", ".tsv"):
        return _from_csv(path, text)
    if suffix in (".html", ".htm"):
        return _from_html(path, text)
    if suffix in (".md", ".markdown"):
        return _from_markdown(path, text)
    return _from_text(path, text)


def _from_text(path: Path, text: str) -> list[dict]:
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        match = URL_IN_TEXT.search(line)
        if match:
            candidate = match.group(0)
        else:
            candidate = line.split("|")[0].split(",")[0].strip()
            # Keep obvious non-web schemes so read_addresses() can report them as skipped.
            if not (BARE_HOST.fullmatch(candidate) or candidate.lower().startswith(SKIP_PREFIXES)):
                continue
        found.append({"url": candidate, "title": "", "source": f"{path.name}:{number}"})
    return found


def _from_csv(path: Path, text: str) -> list[dict]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    if delimiter == ",":
        try:
            delimiter = csv.Sniffer().sniff(text[:2048], delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
    rows = [row for row in csv.reader(text.splitlines(), delimiter=delimiter) if any(row)]
    if not rows:
        return []
    header = [cell.strip().lower() for cell in rows[0]]
    url_col = next((i for i, cell in enumerate(header)
                    if re.search(r"(^|\b)(url|link|adres|site|website|domain)", cell)), None)
    title_col = next((i for i, cell in enumerate(header)
                      if re.search(r"(^|\b)(title|name|ad|isim|başlık|baslik)", cell)), None)
    if url_col is not None:
        body, first_line = rows[1:], 2
    else:
        body, first_line, url_col = rows, 1, 0
    found = []
    for offset, row in enumerate(body):
        if url_col >= len(row):
            continue
        cell = row[url_col]
        title = row[title_col] if title_col is not None and title_col < len(row) else ""
        found.append({"url": cell, "title": title.strip(),
                      "source": f"{path.name}:{first_line + offset}"})
    return found


def _from_markdown(path: Path, text: str) -> list[dict]:
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        links = MARKDOWN_LINK.findall(line)
        if not links:
            links = [(match.group(0), match.group(0)) for match in URL_IN_TEXT.finditer(line)]
        for title, url in links:
            found.append({"url": url, "title": strip_tags(title),
                          "source": f"{path.name}:{number}"})
    return found


def _from_html(path: Path, text: str) -> list[dict]:
    """Browser bookmark exports and any other page with links."""
    found = []
    for number, (url, label) in enumerate(ANCHOR.findall(text), start=1):
        found.append({"url": url, "title": strip_tags(label),
                      "source": f"{path.name}:{number}"})
    return found


def read_addresses(path: Path, *, allow_denied: bool = False) -> tuple[list[dict], list[dict]]:
    """Parses [path]; returns (accepted, skipped). Skipped entries say why."""
    if not path.is_file():
        raise RegistryError(f"{path} bulunamadı")
    accepted, skipped, seen = [], [], set()
    for row in _rows(path):
        url = normalize(row["url"])
        if url is None:
            skipped.append({"value": row["url"], "source": row["source"], "reason": "geçersiz adres"})
            continue
        if not allow_denied and is_denied(key_of(url)):
            skipped.append({"value": url, "source": row["source"], "reason": "arama motoru/sosyal medya"})
            continue
        key = key_of(url)
        if key in seen:
            skipped.append({"value": url, "source": row["source"], "reason": "tekrar"})
            continue
        seen.add(key)
        accepted.append({"url": url, "title": row["title"], "source": row["source"]})
    return accepted, skipped


# ---------------------------------------------------------------- registry

class Registry:
    """Reads and writes sites.json without losing what is already known about a site."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict = {"version": 1, "sites": []}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as e:
                raise RegistryError(f"{self.path} okunamadı: {e}") from e
            if isinstance(loaded, list):
                loaded = {"version": 1, "sites": loaded}
            if not isinstance(loaded, dict) or not isinstance(loaded.get("sites"), list):
                raise RegistryError(f"{self.path} beklenen biçimde değil ({{'sites': [...]}})")
            self.data = loaded
            self.data.setdefault("version", 1)

    @property
    def sites(self) -> list[dict]:
        return self.data["sites"]

    def find(self, url: str) -> dict | None:
        key = key_of(url)
        return next((entry for entry in self.sites if entry.get("url") and key_of(entry["url"]) == key), None)

    def by_plugin(self, plugin: str) -> dict | None:
        return next((entry for entry in self.sites if entry.get("plugin") == plugin), None)

    def upsert(self, url: str, *, source: str | None = None, title: str | None = None,
               **fields) -> tuple[dict, bool]:
        """Adds the address or merges into the existing entry; returns (entry, created)."""
        entry = self.find(url)
        if entry is None:
            entry = {"url": url, "status": "candidate", "sources": [], "added": today()}
            self.sites.append(entry)
            created = True
        else:
            created = False
        if source and source not in entry.setdefault("sources", []):
            entry["sources"].append(source)
        if title and not entry.get("title"):
            entry["title"] = title
        for name, value in fields.items():
            if value is not None:
                entry[name] = value
        return entry, created

    def prune(self, statuses: tuple[str, ...] = ("unreachable", "unusable")) -> list[dict]:
        dropped = [entry for entry in self.sites if entry.get("status") in statuses]
        self.sites[:] = [entry for entry in self.sites if entry.get("status") not in statuses]
        return dropped

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.sites:
            status = entry.get("status") or "candidate"
            counts[status] = counts.get(status, 0) + 1
        return counts

    def save(self) -> None:
        body = json.dumps(self.data, ensure_ascii=False, indent=2) + "\n"
        try:
            self.path.write_text(body, encoding="utf-8")
        except OSError as e:  # locked by a sync client, read-only, a directory, ...
            raise RegistryError(f"{self.path} yazılamadı: {e}") from e

