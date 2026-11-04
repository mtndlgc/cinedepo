#!/usr/bin/env python3
"""
Retarget the plugin at a site, bump its version and publish it in one command.

    python3 scripts/auto_update.py --config site.json            # see site.example.json
    python3 scripts/auto_update.py --url https://example.org \\
        --selector LIST_ITEM="div.film" --selector ITEM_TITLE="h2"
    python3 scripts/auto_update.py --config site.json --dry-run  # show the diff only

Steps:
  1. writes URL / name / language / search path / homepage rows / selectors
     into <plugin>/src/main/kotlin/.../SiteConfig.kt and the icon domain into
     <plugin>/build.gradle.kts,
  2. increments `version` in <plugin>/build.gradle.kts (the app only offers an
     update when the version grows),
  3. optionally checks the selectors against the live page (--check, needs
     `pip install beautifulsoup4`),
  4. commits only the files it changed and pushes; GitHub Actions then builds
     the .cs3 and publishes it to the `builds` branch.

Only standard library is required. Only use this for sites whose terms allow
automated access.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------- helpers

def die(msg: str) -> None:
    print(f"HATA: {msg}", file=sys.stderr)
    sys.exit(1)


def git(*args: str, capture: bool = False) -> str:
    res = subprocess.run(["git", *args], cwd=ROOT, text=True,
                         capture_output=capture, check=False)
    if res.returncode != 0:
        die(f"git {' '.join(args)} başarısız oldu" + (f":\n{res.stderr}" if capture else ""))
    return res.stdout if capture else ""


def kotlin_string(value: str) -> str:
    """Escape for a Kotlin "..." literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")


def to_const_name(key: str) -> str:
    """listItem / list-item / LIST_ITEM -> LIST_ITEM"""
    key = key.strip().replace("-", "_")
    if key.isupper() or "_" in key:
        return key.upper()
    return re.sub(r"(?<!^)(?=[A-Z])", "_", key).upper()


def normalize_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        die(f"geçersiz URL: {url!r} (https://alanadi.com biçiminde olmalı)")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def find_plugin(name: str | None) -> Path:
    candidates = sorted({p.parents[0] for p in ROOT.glob("*/src/main/kotlin/**/SiteConfig.kt")})
    modules = {c.relative_to(ROOT).parts[0]: c for c in candidates}
    if name:
        if name not in modules:
            die(f"eklenti bulunamadı: {name}. Mevcut: {', '.join(modules) or '-'}")
        return ROOT / name
    if len(modules) != 1:
        die(f"birden fazla eklenti var, --plugin ile seçin: {', '.join(modules)}")
    return ROOT / next(iter(modules))


# ----------------------------------------------------------------- editing

class ConfigEditor:
    def __init__(self, path: Path):
        self.path = path
        self.original = path.read_text(encoding="utf-8")
        self.text = self.original

    def set_const(self, name: str, value: str) -> None:
        pattern = re.compile(rf'(const val {re.escape(name)} = )"(?:[^"\\]|\\.)*"')
        if not pattern.search(self.text):
            known = re.findall(r'const val ([A-Z_]+) = "', self.text)
            die(f"{self.path.name} içinde '{name}' yok. Bilinen alanlar:\n  " + "\n  ".join(known))
        self.text = pattern.sub(lambda m: f'{m.group(1)}"{kotlin_string(value)}"', self.text, count=1)

    def set_list(self, name: str, kotlin_items: list[str], type_: str) -> None:
        pattern = re.compile(rf"(val {name}: {re.escape(type_)} = (?:listOf|setOf)\()(.*?)(\n    \))", re.S)
        if not pattern.search(self.text):
            # single-line form, e.g. setOf()
            pattern = re.compile(rf"(val {name}: {re.escape(type_)} = (?:listOf|setOf)\()(.*?)(\))")
            if not pattern.search(self.text):
                die(f"{self.path.name} içinde {name} bulunamadı")
            body = ", ".join(kotlin_items)
        else:
            body = "".join(f"\n        {item}," for item in kotlin_items)
        self.text = pattern.sub(lambda m: m.group(1) + body + m.group(3), self.text, count=1)

    def get_const(self, name: str) -> str | None:
        m = re.search(rf'const val {re.escape(name)} = "((?:[^"\\]|\\.)*)"', self.text)
        return m.group(1).encode().decode("unicode_escape") if m else None

    @property
    def changed(self) -> bool:
        return self.text != self.original

    def diff(self) -> str:
        return "".join(difflib.unified_diff(
            self.original.splitlines(True), self.text.splitlines(True),
            fromfile=f"a/{self.path.relative_to(ROOT)}", tofile=f"b/{self.path.relative_to(ROOT)}"))

    def save(self) -> None:
        self.path.write_text(self.text, encoding="utf-8")


def bump_version(gradle: ConfigEditor) -> tuple[int, int]:
    m = re.search(r"^version\s*=\s*(\d+)\s*$", gradle.text, re.M)
    if not m:
        die(f"{gradle.path} içinde 'version = N' satırı yok")
    old = int(m.group(1))
    gradle.text = gradle.text[:m.start(1)] + str(old + 1) + gradle.text[m.end(1):]
    return old, old + 1


def set_icon_domain(gradle: ConfigEditor, url: str) -> None:
    host = urllib.parse.urlparse(url).netloc
    gradle.text = re.sub(r"(favicons\?domain=)[^&\"]+", lambda m: m.group(1) + host, gradle.text)


# ----------------------------------------------------------------- live check

def check_selectors(url: str, selectors: dict[str, str]) -> None:
    """Fetches the homepage/listing and reports how many elements each list selector matches."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        print("  (--check atlandı: 'pip install beautifulsoup4' gerekli)")
        return
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cinedepo auto_update)"})
    try:
        html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print(f"  (--check: {url} indirilemedi: {e})")
        return
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(selectors["LIST_ITEM"]) if selectors.get("LIST_ITEM") else []
    print(f"  {url}: LIST_ITEM -> {len(items)} kart")
    if items:
        first = items[0]
        for key in ("ITEM_TITLE", "ITEM_LINK", "ITEM_POSTER"):
            if selectors.get(key):
                hit = first.select_one(selectors[key])
                print(f"    ilk kartta {key}: {'bulundu' if hit else 'YOK'}")
    elif selectors.get("LIST_ITEM"):
        print("  UYARI: liste seçicisi bu sayfada hiçbir şey bulmadı "
              "(sayfa JavaScript ile oluşuyor olabilir).")


# ----------------------------------------------------------------- main

def load_settings(args: argparse.Namespace) -> dict:
    data: dict = {}
    if args.config:
        try:
            data = json.loads(Path(args.config).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            die(f"{args.config} okunamadı: {e}")
    for key in ("url", "name", "lang", "search_path", "plugin"):
        val = getattr(args, key)
        if val is not None:
            data[key] = val
    if args.home:
        data["home_sections"] = []
        for item in args.home:
            if "|" not in item:
                die(f"--home 'yol|Başlık' biçiminde olmalı: {item!r}")
            path, title = item.split("|", 1)
            data["home_sections"].append({"path": path, "title": title})
    if args.extra_host:
        data["extra_hosts"] = args.extra_host
    sel = dict(data.get("selectors", {}))
    for item in args.selector or []:
        if "=" not in item:
            die(f"--selector ANAHTAR=DEĞER biçiminde olmalı: {item!r}")
        k, v = item.split("=", 1)
        sel[k] = v
    data["selectors"] = {to_const_name(k): v for k, v in sel.items()}
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Eklentiyi bir siteye uyarla, sürümü artır, gönder.")
    ap.add_argument("--config", help="JSON ayar dosyası (bkz. site.example.json)")
    ap.add_argument("--plugin", help="eklenti dizini (tek eklenti varsa gerekmez)")
    ap.add_argument("--url", help="hedef sitenin ana adresi")
    ap.add_argument("--name", help="uygulamada görünen sağlayıcı adı")
    ap.add_argument("--lang", help="içerik dili (ISO 639-1, örn. tr)")
    ap.add_argument("--search-path", dest="search_path", help="arama yolu, %%s = sorgu")
    ap.add_argument("--home", action="append", help="ana sayfa satırı 'yol|Başlık', %%d = sayfa (tekrarlanabilir)")
    ap.add_argument("--extra-host", action="append", dest="extra_host", help="izin verilen ek alan adı")
    ap.add_argument("--selector", action="append", help="LIST_ITEM=\"div.film\" gibi (tekrarlanabilir)")
    ap.add_argument("--no-bump", action="store_true", help="sürümü artırma")
    ap.add_argument("--check", action="store_true", help="seçicileri canlı sayfada dene (beautifulsoup4)")
    ap.add_argument("--dry-run", action="store_true", help="yalnızca farkı göster, dosya yazma")
    ap.add_argument("--no-push", action="store_true", help="commit at ama gönderme")
    ap.add_argument("--no-commit", action="store_true", help="dosyaları yaz, commit atma")
    ap.add_argument("--allow-dirty", action="store_true", help="çalışma alanında başka değişiklik varken de devam et")
    args = ap.parse_args()

    s = load_settings(args)
    plugin = find_plugin(s.get("plugin"))
    config_path = next(plugin.glob("src/main/kotlin/**/SiteConfig.kt"))
    cfg = ConfigEditor(config_path)
    gradle = ConfigEditor(plugin / "build.gradle.kts")

    if not args.dry_run and not args.no_commit and not args.allow_dirty:
        if git("status", "--porcelain", capture=True).strip():
            die("çalışma alanında commit'lenmemiş değişiklik var. Önce commit'leyin ya da --allow-dirty verin.")

    if "url" in s:
        s["url"] = normalize_url(s["url"])
        cfg.set_const("MAIN_URL", s["url"])
        set_icon_domain(gradle, s["url"])
    if "name" in s:
        cfg.set_const("NAME", s["name"])
    if "lang" in s:
        if not re.fullmatch(r"[a-z]{2,3}", s["lang"]):
            die(f"dil kodu 2-3 küçük harf olmalı: {s['lang']!r}")
        cfg.set_const("LANG", s["lang"])
        gradle.text = re.sub(r'(language = )"[^"]*"', rf'\1"{s["lang"]}"', gradle.text)
    if "search_path" in s:
        if "%s" not in s["search_path"]:
            die("search_path içinde sorgu için %s olmalı")
        cfg.set_const("SEARCH_PATH", s["search_path"])
    if "home_sections" in s:
        items = []
        for sec in s["home_sections"]:
            path, title = sec["path"], sec["title"]
            if not path.startswith("/"):
                die(f"ana sayfa yolu '/' ile başlamalı: {path!r}")
            items.append(f'"{kotlin_string(path)}" to "{kotlin_string(title)}"')
        if not items:
            die("home_sections boş olamaz")
        cfg.set_list("HOME_SECTIONS", items, "List<Pair<String, String>>")
    if "extra_hosts" in s:
        cfg.set_list("ALLOWED_EXTRA_HOSTS", [f'"{kotlin_string(h.lower())}"' for h in s["extra_hosts"]], "Set<String>")
    for key, value in s["selectors"].items():
        cfg.set_const(key, value)

    if not cfg.changed and not gradle.changed:
        print("Değişecek bir şey yok (ayarlar zaten aynı).")
        return

    if not args.no_bump:
        old, new = bump_version(gradle)
        print(f"Sürüm: {old} -> {new}")

    print(cfg.diff() + gradle.diff())

    if args.check:
        base = s.get("url") or cfg.get_const("MAIN_URL")
        all_sel = {k: cfg.get_const(k) for k in ("LIST_ITEM", "ITEM_TITLE", "ITEM_LINK", "ITEM_POSTER")}
        first = (s.get("home_sections") or [{"path": ""}])[0]["path"].replace("%d", "1")
        check_selectors(base + first, all_sel)

    if args.dry_run:
        print("--dry-run: dosyalar yazılmadı.")
        return

    cfg.save()
    gradle.save()
    print("Dosyalar güncellendi.")
    if args.no_commit:
        return

    changed = [str(p.path.relative_to(ROOT)) for p in (cfg, gradle) if p.changed]
    git("add", "--", *changed)
    target = s.get("url") or "ayarlar"
    git("commit", "-m", f"Auto-update {plugin.name}: {target}")
    print("Commit atıldı.")
    if args.no_push:
        return
    branch = git("rev-parse", "--abbrev-ref", "HEAD", capture=True).strip()
    git("push", "origin", branch)
    print(f"'{branch}' dalına gönderildi. GitHub Actions derlemeyi başlattı; "
          f"bittiğinde uygulamada Eklentiler ekranında güncelleme görünür.")


if __name__ == "__main__":
    main()
