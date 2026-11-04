#!/usr/bin/env python3
"""
Find the addresses a provider needs for one site, without opening DevTools.

Given a homepage URL this script looks at the HTML and works out

  * the navigation links that look like listing pages  -> HOME_SECTIONS,
  * how those listings paginate ("/filmler/page/%d")   -> HOME_SECTIONS paths,
  * the search form's address and field ("/arama?q=%s") -> SEARCH_PATH,

and prints the result as JSON that `auto_update.py` accepts as a config file.

    python3 scripts/discover_site.py https://ornek.com
    python3 scripts/discover_site.py https://ornek.com --out site.json
    python3 scripts/discover_site.py https://ornek.com --out sites.json --append --plugin Ornek
    python3 scripts/discover_site.py https://ornek.com --apply --plugin Ornek --dry-run

The candidate listing pages are fetched once each to check that they really are
listings (a page with several links below the same path) and to read the
pagination link. Pass --no-verify to skip those extra requests.

Only standard library is required. Only use this for sites whose terms allow
automated access: it is your responsibility to check robots.txt and the terms.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (compatible; cinedepo-discover/1.0)"
MIN_CARDS = 5

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}

NAV_TAGS = {"nav", "header", "footer"}
NAV_HINT = re.compile(r"(menu|nav|header|footer|categor|kategori|genre|dropdown)", re.I)
LIST_HINT = re.compile(
    r"(film|dizi|movie|serie|show|anime|belgesel|document|program|category|kategori|"
    r"genre|tur|trend|populer|popular|latest|yeni|son|bolum|episode|list|arsiv|archive)", re.I)
SKIP_HINT = re.compile(
    r"(login|giris|register|kayit|signup|uye|logout|cikis|privacy|gizlilik|kvkk|contact|"
    r"iletisim|about|hakkimizda|dmca|terms|kullanim|kosul|search|arama|sitemap|feed|rss|"
    r"wp-admin|wp-login|facebook|twitter|instagram|telegram|discord|youtube|tiktok|"
    r"whatsapp|pinterest|mailto|javascript|\.xml$|\.txt$|\.css$|\.js$|\.ico$)", re.I)

PAGE_KEYS = ("page", "sayfa", "p", "pg", "s", "page_no", "sayfa_no", "paged")
PAGE_IN_PATH = re.compile(r"/(?:page|sayfa|p)/(\d+)/?$", re.I)

SEARCH_NAMES = ("s", "q", "query", "search", "ara", "arama", "keyword", "kelime", "term")
SEARCH_FIELD_TYPES = ("text", "search", "")


class FetchError(Exception):
    """The page could not be downloaded; the message is user-facing."""


# --------------------------------------------------------------------- fetch

def fetch(url: str, *, timeout: int = 20, ua: str = UA) -> tuple[str, str]:
    """Downloads [url]; returns (html, final url after redirects)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "tr,en;q=0.8",
        "Accept-Encoding": "identity",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read(4 * 1024 * 1024)
            charset = res.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, "replace"), res.geturl()
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FetchError(str(getattr(e, "reason", e))) from e


def _require_http(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise FetchError(f"geçersiz adres: {url!r} (https://alanadi.com biçiminde olmalı)")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")


# ----------------------------------------------------------------- mini DOM
# A tiny tree is enough for the heuristics below and keeps the script dependency free.

class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict | None = None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[Node] = []
        self.parent = parent

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.tag}>"

    def get(self, key: str, default: str = "") -> str:
        value = self.attrs.get(key)
        return default if value is None else value

    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    def walk(self):
        yield self
        for child in self.children:
            if child.tag != "#text":
                yield from child.walk()

    def text(self) -> str:
        parts: list[str] = []

        def visit(node: "Node") -> None:
            for child in node.children:
                if child.tag == "#text":
                    parts.append(child.attrs.get("data", ""))
                elif child.tag not in ("script", "style", "noscript", "template", "svg"):
                    visit(child)

        visit(self)
        return re.sub(r"\s+", " ", "".join(parts)).strip()


class _DomBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        # Close the nearest matching ancestor; browsers do the same for unclosed <p>/<li>.
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            self.stack[-1].children.append(Node("#text", {"data": data}, self.stack[-1]))


def parse_html(html: str) -> Node:
    builder = _DomBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def anchors(root: Node, base: str) -> list[dict]:
    """Every <a href> as {url, path, host, text, node}."""
    out = []
    for node in root.walk():
        if node.tag != "a":
            continue
        href = node.get("href").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        url = urllib.parse.urljoin(base, href)
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https"):
            continue
        out.append({
            "url": url,
            "path": urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, "")),
            "host": _host(url),
            "text": node.text(),
            "node": node,
        })
    return out


def _in_nav(node: Node) -> bool:
    current = node.parent
    while current is not None:
        if current.tag in NAV_TAGS or current.get("role") == "navigation":
            return True
        if any(NAV_HINT.search(c) for c in current.classes()) or NAV_HINT.search(current.get("id")):
            return True
        current = current.parent
    return False


def meta_content(root: Node, *names: str) -> str:
    wanted = {n.lower() for n in names}
    for node in root.walk():
        if node.tag != "meta":
            continue
        key = (node.get("property") or node.get("name")).lower()
        if key in wanted:
            return node.get("content").strip()
    return ""


def document_lang(root: Node) -> str:
    for node in root.walk():
        if node.tag == "html":
            value = node.get("lang").strip().lower()
            value = re.split(r"[-_]", value)[0]
            if re.fullmatch(r"[a-z]{2,3}", value):
                return value
    return ""


def site_name(root: Node) -> str:
    name = meta_content(root, "og:site_name", "application-name")
    if name:
        return name[:60]
    for node in root.walk():
        if node.tag == "title":
            # "Site - Film izle" -> "Site"
            return re.split(r"\s+[|–—]\s+|\s+-\s+", node.text())[0][:60].strip()
    return ""


# ------------------------------------------------------------- heuristics

def find_sections(root: Node, base: str, limit: int = 8) -> list[dict]:
    """Navigation links that look like listing pages, best first."""
    host = _host(base)
    ranked, seen = [], set()
    for order, a in enumerate(anchors(root, base)):
        if a["host"] != host:
            continue
        path, title = a["path"], a["text"]
        if not title or len(title) > 40 or path in ("/", "") or path in seen:
            continue
        if SKIP_HINT.search(path) or SKIP_HINT.search(title):
            continue
        # Detail pages end in an id or a year: /film/adi-2012-1234
        if re.search(r"/\d{3,}", path) or re.search(r"/\d+$", path):
            continue
        score = 0
        if _in_nav(a["node"]):
            score += 3
        if LIST_HINT.search(path):
            score += 3
        if LIST_HINT.search(title):
            score += 2
        if "?" not in path:
            score += 1
        if path.count("/") <= 3:
            score += 1
        if score < 5:
            continue
        seen.add(path)
        ranked.append({"path": path, "title": title, "score": score, "order": order})
    ranked.sort(key=lambda c: (-c["score"], c["order"]))
    return ranked[:limit]


def _count_cards(root: Node, page_url: str) -> int:
    """How many links on the page point below the page's own path."""
    prefix = urllib.parse.urlsplit(page_url).path.rstrip("/") + "/"
    host = _host(page_url)
    count = 0
    for a in anchors(root, page_url):
        if a["host"] != host or not a["path"].startswith(prefix):
            continue
        rest = a["path"][len(prefix):]
        if not rest or re.fullmatch(r"(page|sayfa|p)/\d+/?", rest):
            continue
        count += 1
    return count


def _query_template(parts: urllib.parse.SplitResult, key: str) -> str:
    fields = [f"{k}=%d" if k == key else f"{k}={v}"
              for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)]
    return f"{parts.path or '/'}?{'&'.join(fields)}"


def pagination_template(root: Node, page_url: str) -> str | None:
    """The listing's second-page URL with the page number replaced by %d."""
    host = _host(page_url)
    best: tuple[int, str] | None = None
    for a in anchors(root, page_url):
        if a["host"] != host:
            continue
        parts = urllib.parse.urlsplit(a["url"])
        candidate: str | None = None
        number = 0
        match = PAGE_IN_PATH.search(parts.path)
        if match and not parts.query:
            number = int(match.group(1))
            candidate = re.sub(r"/\d+/?$", "/%d", parts.path)
        else:
            for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
                if key.lower() in PAGE_KEYS and value.isdigit():
                    candidate = _query_template(parts, key)
                    number = max(number, int(value))
        if candidate and number >= 2 and (best is None or number > best[0]):
            best = (number, candidate)
    return best[1] if best else None


def find_search(root: Node, base: str) -> str | None:
    """The GET search form as '/path?field=%s', or None."""
    host = _host(base)
    for form in (n for n in root.walk() if n.tag == "form"):
        if (form.get("method") or "get").strip().lower() != "get":
            continue
        fields = [
            (inp.get("type").strip().lower(), inp.get("name").strip())
            for inp in form.walk()
            if inp.tag == "input"
            and (inp.get("type") or "text").strip().lower() in SEARCH_FIELD_TYPES
            and inp.get("name").strip()
        ]
        field = next((name for kind, name in fields if kind == "search"), None)
        if field is None:
            field = next((name for _, name in fields if name.lower() in SEARCH_NAMES), None)
        if field is None:
            continue
        action = form.get("action").strip() or base
        url = urllib.parse.urljoin(base, action)
        if _host(url) != host:
            continue
        parts = urllib.parse.urlsplit(url)
        query = [f"{k}={v}" for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)]
        query.append(f"{field}=%s")
        return f"{parts.path or '/'}?{'&'.join(query)}"
    return None


# ------------------------------------------------------------------- main

def normalize_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{path}"


def discover(url: str, *, limit: int = 8, verify: bool = True, timeout: int = 20,
             delay: float = 0.3, log=print) -> dict:
    """Works out url / name / lang / search_path / home_sections for one site."""
    url = _require_http(url)
    html, final_url = fetch(url, timeout=timeout)
    root = parse_html(html)
    base = normalize_url(final_url)
    notes: list[str] = []

    candidates = find_sections(root, final_url, limit=max(limit * 2, 8))
    if not candidates:
        notes.append("ana sayfada bölüm bağlantısı bulunamadı "
                     "(site JavaScript ile oluşuyorsa HTML'de bağlantı yoktur)")

    sections: list[dict] = []
    for candidate in candidates:
        if len(sections) >= limit:
            break
        path, title = candidate["path"], candidate["title"]
        if not verify:
            sections.append({"path": path, "title": title})
            continue
        page_url = urllib.parse.urljoin(final_url, path)
        try:
            page_html, _ = fetch(page_url, timeout=timeout)
        except FetchError as e:
            notes.append(f"{path}: atlandı ({e})")
            continue
        page_root = parse_html(page_html)
        if _count_cards(page_root, page_url) < MIN_CARDS:
            notes.append(f"{path}: liste sayfası gibi görünmedi, atlandı")
            continue
        template = pagination_template(page_root, page_url)
        if template is None:
            notes.append(f"{title}: sayfalama bağlantısı bulunamadı, %d eklenmedi")
            template = path
        sections.append({"path": template, "title": title})
        time.sleep(delay)

    if candidates and not sections:
        notes.append("adayların hiçbiri doğrulanamadı; doğrulanmamış hâlleriyle yazıldı "
                     "(--no-verify ile de çalıştırabilirsiniz)")
        sections = [{"path": c["path"], "title": c["title"]} for c in candidates[:limit]]

    search_path = find_search(root, final_url)
    if search_path is None:
        notes.append("arama formu bulunamadı; SEARCH_PATH'i elle girin")

    result: dict = {
        "url": base,
        "name": site_name(root) or _host(base),
        "lang": document_lang(root) or "tr",
    }
    if search_path:
        result["search_path"] = search_path
    result["home_sections"] = sections

    for note in notes:
        log(f"  not: {note}")
    return result


def write_sites_file(path: Path, entry: dict, *, append: bool) -> None:
    """Writes {sites: [...]}; with append=True the entry replaces one with the same key."""
    sites: list[dict] = []
    if append and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            raise FetchError(f"{path} geçerli JSON değil: {e}") from e
        sites = data.get("sites", []) if isinstance(data, dict) else []
    key = entry.get("plugin") or entry["url"]
    sites = [s for s in sites if (s.get("plugin") or s.get("url")) != key]
    sites.append(entry)
    path.write_text(json.dumps({"sites": sites}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Bir sitenin bölüm adreslerini, arama yolunu ve sayfalamasını bul.")
    ap.add_argument("url", help="sitenin ana adresi (https://...)")
    ap.add_argument("--out", help="JSON dosyasına yaz (varsayılan: ekrana yaz)")
    ap.add_argument("--append", action="store_true", help="--out dosyasındaki sites listesine ekle")
    ap.add_argument("--plugin", help="hangi eklenti modülüne ait (çok eklentili depo için)")
    ap.add_argument("--name", help="uygulamada görünecek ad (varsayılan: sitenin kendi adı)")
    ap.add_argument("--lang", help="içerik dili (varsayılan: <html lang>)")
    ap.add_argument("--limit", type=int, default=8, help="en fazla bölüm sayısı (varsayılan 8)")
    ap.add_argument("--no-verify", action="store_true", help="aday sayfaları indirip denetleme")
    ap.add_argument("--timeout", type=int, default=20, help="istek zaman aşımı, saniye")
    ap.add_argument("--delay", type=float, default=0.3, help="istekler arası bekleme, saniye")
    ap.add_argument("--apply", action="store_true", help="sonucu doğrudan eklentiye yaz")
    ap.add_argument("--create", action="store_true",
                    help="--apply sırasında eklenti yoksa şablondan oluştur")
    ap.add_argument("--resolve", action="store_true",
                    help="önce sitenin çalışan adresini bul (find_site.py), sonra onu kullan")
    ap.add_argument("--dry-run", action="store_true", help="--apply ile: yalnızca farkı göster")
    ap.add_argument("--no-commit", action="store_true", help="--apply ile: dosyaları yaz, commit atma")
    ap.add_argument("--no-push", action="store_true", help="--apply ile: commit at ama gönderme")
    args = ap.parse_args()

    if args.resolve:
        import find_site  # imported late: only needed with --resolve
        try:
            best = find_site.best_domain(args.url, timeout=args.timeout,
                                         log=lambda m: print(m, file=sys.stderr))
        except find_site.ResolveError as e:
            print(f"HATA: {e}", file=sys.stderr)
            sys.exit(1)
        if best:
            print(f"adres: {args.url} -> {best}", file=sys.stderr)
            args.url = best
        else:
            print("uyarı: çalışan adres bulunamadı, verilen adres denenecek", file=sys.stderr)

    try:
        entry = discover(args.url, limit=args.limit, verify=not args.no_verify,
                         timeout=args.timeout, delay=args.delay, log=lambda m: print(m, file=sys.stderr))
    except FetchError as e:
        print(f"HATA: {e}", file=sys.stderr)
        sys.exit(1)

    if args.name:
        entry["name"] = args.name
    if args.lang:
        entry["lang"] = args.lang
    if args.plugin:
        entry["plugin"] = args.plugin
    if args.create:
        entry["create"] = True

    if args.out:
        try:
            write_sites_file(Path(args.out), entry, append=args.append)
        except (FetchError, OSError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"{args.out} yazıldı.", file=sys.stderr)

    if entry.get("home_sections"):
        print(f"  {len(entry['home_sections'])} bölüm bulundu:", file=sys.stderr)
        for section in entry["home_sections"]:
            print(f"    {section['path']:<34} {section['title']}", file=sys.stderr)

    if args.apply:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import auto_update as au  # noqa: E402  (imported late: only needed with --apply)

        settings = {k: v for k, v in entry.items() if k != "create"}
        settings["selectors"] = {}
        if entry.get("create"):
            settings["create"] = True
        try:
            au.run(settings, dry_run=args.dry_run, no_commit=args.no_commit,
                   no_push=args.no_push, allow_dirty=args.dry_run)
        except au.UpdateError as e:
            print(f"HATA: {e}", file=sys.stderr)
            sys.exit(1)
    elif not args.out:
        print(json.dumps(entry, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

