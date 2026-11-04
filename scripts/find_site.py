#!/usr/bin/env python3
"""
Find a site's working address, and turn a list of candidate sites into a plan.

Sites move to new domains, so the address in SiteConfig.kt goes stale. This script
starts from the address you have (or a list you keep), collects the addresses the
site itself points at, probes every candidate and ranks them by how much the page
resembles the original: same link structure, same title, same search form.

    python3 scripts/find_site.py https://ornek.com                  # sıralı adres listesi
    python3 scripts/find_site.py https://ornek.com --apply --plugin CineDepo --dry-run
    python3 scripts/find_site.py --candidates domains.txt --out domains.json
    python3 scripts/find_site.py --candidates domains.txt --plan sites.json

`--candidates` reads one address per line ('#' starts a comment); the file may mix
plain domains, URLs and ports. `--plan` also discovers the homepage rows and the
search path of every reachable site (see discover_site.py) and writes a config that
`auto_update.py --config sites.json` turns into one plugin module per site.

Only standard library is required. Only use this for sites whose terms allow
automated access.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import discover_site as ds  # noqa: E402
import site_registry as reg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TLDS = ("com", "net", "org", "io", "tv", "xyz", "nl", "co", "me", "info", "biz",
        "site", "online", "app", "de", "to", "cc", "ws")
MIN_SCORE = 0.35
MIRROR_TEXT = re.compile(
    r"(mirror|ayna|alternatif|alternate|yedek|yeni adres|g[uü]ncel|domain|adres|"
    r"yeni site|site adresi|linkler|adresler)", re.I)


class ResolveError(Exception):
    """Invalid input; the message is user-facing (Turkish)."""


def die(msg: str) -> None:
    raise ResolveError(msg)


# ---------------------------------------------------------------- addresses

def netloc_of(url: str) -> str:
    """'https://www.ornek.com/x' -> 'www.ornek.com'; a bare domain is accepted too."""
    value = url.strip()
    if "://" not in value:
        value = "http://" + value
    parts = urllib.parse.urlsplit(value)
    if not parts.netloc:
        die(f"geçersiz adres: {url!r}")
    return parts.netloc.lower()


def host_of(netloc: str) -> str:
    return netloc.split(":")[0].removeprefix("www.")


def label_of(netloc: str) -> str:
    """The site's own name, without www. / TLD / port: hdfilmcehennemi.nl -> hdfilmcehennemi."""
    return host_of(netloc).split(".")[0]


def is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def host_variants(netloc: str) -> set[str]:
    """The address itself, its www. form and the same name under other TLDs."""
    host, _, port = netloc.partition(":")
    host = host.removeprefix("www.")
    suffix = f":{port}" if port else ""
    if is_ip(host):
        return {netloc}  # no www. / TLD guessing for a bare IP
    out = {f"{host}{suffix}", f"www.{host}{suffix}"}
    if "." in host:
        name = host.split(".")[0]
        out.update(f"{name}.{tld}{suffix}" for tld in TLDS)
    return out


def read_candidates(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        die(f"{path} okunamadı: {e}")
    items = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            items.append(line)
    if not items:
        die(f"{path} içinde adres yok")
    return items


# ----------------------------------------------------------------- scoring

def signature(html: str, page_url: str) -> dict:
    """What makes this site recognisable: its links, its title and whether it has a search box."""
    root = ds.parse_html(html)
    paths = set()
    for anchor in ds.anchors(root, page_url):
        path = anchor["path"].split("?")[0]
        if path and path != "/":
            paths.add(path)
    title = ""
    for node in root.walk():
        if node.tag == "title":
            title = node.text()
            break
    words = {word for word in re.findall(r"[a-z0-9]+", title.lower()) if len(word) > 2}
    return {"paths": paths, "title": title, "words": words,
            "form": ds.find_search(root, page_url) is not None}


def similarity(reference: dict, candidate: dict) -> float:
    """0..1: link overlap, title overlap, presence of a search form."""
    left, right = reference["paths"], candidate["paths"]
    links = len(left & right) / len(left | right) if left and right else 0.0
    words_l, words_r = reference["words"], candidate["words"]
    words = len(words_l & words_r) / len(words_l | words_r) if words_l and words_r else 0.0
    return round(0.6 * links + 0.3 * words + 0.1 * (1.0 if candidate["form"] else 0.0), 3)


def fallback_score(candidate: dict) -> float:
    """Used when the original address is unreachable: does this look like a listing site at all?"""
    score = 0.0
    if candidate["form"]:
        score += 0.3
    if len(candidate["paths"]) >= 30:
        score += 0.3
    if any(re.search(r"/(film|dizi|movie|serie|category|kategori)", p, re.I) for p in candidate["paths"]):
        score += 0.2
    return round(min(score, 0.8), 3)


def mirror_links(html: str, page_url: str) -> set[str]:
    """Addresses the page itself advertises: 'mirror' links and same-name domains."""
    root = ds.parse_html(html)
    own = netloc_of(page_url)
    own_label = label_of(own)
    found = set()
    for anchor in ds.anchors(root, page_url):
        other = netloc_of(anchor["url"])
        if other == own:
            continue
        if MIRROR_TEXT.search(anchor["text"]) or label_of(other) == own_label:
            found.add(other)
    return found


def probe(url: str, timeout: int) -> tuple[str, str]:
    return ds.fetch(url, timeout=timeout)


# ------------------------------------------------------------------ resolve

def resolve(seed: str, *, candidates: list[str] = (), timeout: int = 20, delay: float = 0.2,
            dedupe: bool = True, log=print) -> list[dict]:
    """Probes the seed and every address related to it; best match first."""
    seed_netloc = netloc_of(seed)
    page = final = None
    for scheme in ("https", "http"):
        try:
            page, final = probe(f"{scheme}://{seed_netloc}", timeout)
            break
        except ds.FetchError:
            continue
    if page is None:
        log(f"  uyarı: {seed_netloc} indirilemedi; yalnızca adaylar denenecek")
    reference = signature(page, final) if page and final else None

    targets = {seed_netloc, *(netloc_of(item) for item in candidates)}
    if page and final:
        targets |= host_variants(netloc_of(final))
        targets |= mirror_links(page, final)

    results = []
    for target in sorted(targets):
        entry = {"url": f"https://{target}", "netloc": target, "final": None,
                 "score": 0.0, "title": "", "reachable": False}
        for scheme in ("https", "http"):
            url = f"{scheme}://{target}"
            try:
                body, landed = probe(url, timeout)
            except ds.FetchError:
                continue
            sig = signature(body, landed)
            entry.update({
                "url": url,
                "final": landed,
                "title": sig["title"],
                "score": similarity(reference, sig) if reference else fallback_score(sig),
                "reachable": True,
            })
            break
        results.append(entry)
        time.sleep(delay)

    results.sort(key=lambda item: (item["reachable"], item["score"]), reverse=True)
    return _dedupe(results) if dedupe else results


def _dedupe(results: list[dict]) -> list[dict]:
    """One entry per site name; the other working addresses become that entry's mirrors."""
    best: dict[str, dict] = {}
    order: list[str] = []
    for entry in results:
        label = label_of(entry["netloc"])
        if label not in best:
            best[label] = dict(entry, mirrors=[])
            order.append(label)
        elif entry["reachable"]:
            best[label]["mirrors"].append(entry["url"])
    return [best[label] for label in order]


def best_domain(seed: str, *, min_score: float = MIN_SCORE, **kwargs) -> str | None:
    """The highest-scoring working address, or None."""
    for entry in resolve(seed, **kwargs):
        if entry["reachable"] and entry["score"] >= min_score:
            return entry["url"]
    return None


# --------------------------------------------------------------------- plan

def plugin_name_for(netloc: str) -> str:
    """hdfilmcehennemi.nl -> Hdfilmcehennemi (a valid Gradle module name)."""
    name = re.sub(r"[^A-Za-z0-9]", "", label_of(netloc))
    if not name:
        return ""
    name = name[0].upper() + name[1:]
    return ("Site" + name if name[0].isdigit() else name)[:31]


def existing_plugins() -> list[str]:
    names = set()
    for config in ROOT.glob("*/src/main/kotlin/**/SiteConfig.kt"):
        names.add(config.relative_to(ROOT).parts[0])
    return sorted(names)


def plan_entry(entry: dict, *, limit: int, timeout: int, log=print) -> dict | None:
    """Discovers one site's addresses and turns them into a `sites.json` entry."""
    plugin = plugin_name_for(entry["netloc"])
    if not plugin:
        log(f"  {entry['netloc']}: eklenti adı üretilemedi, atlandı")
        return None
    if plugin in existing_plugins():
        log(f"  {entry['netloc']}: {plugin} eklentisi zaten var, atlandı")
        return None
    try:
        site = ds.discover(entry["url"], limit=limit, timeout=timeout, log=log)
    except ds.FetchError as e:
        log(f"  {entry['netloc']}: atlandı ({e})")
        return None
    if not site["home_sections"]:
        log(f"  {entry['netloc']}: bölüm bulunamadı")
    log(f"  {entry['netloc']}: {len(site['home_sections'])} bölüm, "
        f"arama {site.get('search_path', '(bulunamadı)')}")
    return {"plugin": plugin, "create": True, **site}


# --------------------------------------------------------------------- main

def liveness(sig: dict) -> float:
    """How much a single page looks like a usable listing site (0..1)."""
    paths = len(sig["paths"])
    score = 0.0
    if paths >= 20:
        score += 0.4
    elif paths >= 5:
        score += 0.2
    if sig["form"]:
        score += 0.3
    if any(re.search(r"/(film|dizi|movie|serie|category|kategori)", path, re.I) for path in sig["paths"]):
        score += 0.3
    return round(min(score, 1.0), 2)


def _probe_entry(url: str, timeout: int) -> tuple[str, str] | None:
    """Fetches the entry's own address (https, then http); None when it does not answer."""
    netloc = netloc_of(url)
    for scheme in ("https", "http"):
        try:
            return probe(f"{scheme}://{netloc}", timeout)
        except ds.FetchError:
            continue
    return None


def check_entry(entry: dict, *, min_score: float, timeout: int, delay: float, log=print) -> dict:
    """Probes one catalogue entry, follows a moved domain and records the result."""
    url = entry["url"]
    entry["checked"] = reg.today()
    page = _probe_entry(url, timeout)
    if page is not None:
        body, landed = page
        sig = signature(body, landed)
        score = liveness(sig)
        entry.update(url=netloc_url(landed), score=score, title=sig["title"] or entry.get("title", ""))
        entry["status"] = "ok" if score >= 0.5 else "unusable"
        log(f"  {'çalışıyor  ' if entry['status'] == 'ok' else 'kullanılamaz'} {entry['url']} "
            f"({score:.2f})")
        return entry

    log(f"  yanıt yok   {url}: taşınmış olabilir, adres aranıyor…")
    found = [item for item in resolve(url, timeout=timeout, delay=delay, log=lambda *_: None)
             if item["reachable"] and item["score"] >= min_score]
    if not found:
        entry.update(status="unreachable", score=0.0)
        log(f"  yanıt yok   {url}: yeni adres bulunamadı")
        return entry
    best = max(found, key=lambda item: item["score"])
    entry.setdefault("previous_urls", []).append(url)
    entry.update(url=best["final"] or best["url"], status="ok", score=best["score"],
                 title=best["title"] or entry.get("title", ""))
    log(f"  taşındı     {url} -> {entry['url']} ({best['score']:.2f})")
    return entry


def netloc_url(url: str) -> str:
    """https://ornek.com/yol?x=1 -> https://ornek.com"""
    return f"{urlsplit_scheme(url)}://{netloc_of(url)}"


def urlsplit_scheme(url: str) -> str:
    return urllib.parse.urlsplit(url).scheme or "https"


def plan_catalog_entry(entry: dict, *, limit: int, timeout: int, log=print) -> bool:
    """Discovers the homepage rows / search path of one entry and marks it planned."""
    plugin = entry.get("plugin") or plugin_name_for(netloc_of(entry["url"]))
    if not plugin:
        log(f"  {entry['url']}: eklenti adı üretilemedi, atlandı")
        return False
    try:
        site = ds.discover(entry["url"], limit=limit, timeout=timeout, log=lambda *_: None)
    except ds.FetchError as e:
        entry.update(status="unreachable", checked=reg.today(), score=0.0)
        log(f"  {entry['url']}: atlandı ({e})")
        return False
    if not site["home_sections"] and not site.get("search_path"):
        entry.update(status="unusable", checked=reg.today())
        log(f"  {entry['url']}: bölüm ve arama bulunamadı")
        return False

    entry.update({
        "plugin": plugin,
        "create": plugin not in existing_plugins(),
        "url": site["url"],
        "name": site["name"],
        "lang": site["lang"],
        "home_sections": site["home_sections"],
        "status": "planned",
        "planned": reg.today(),
        "checked": reg.today(),
    })
    if site.get("search_path"):
        entry["search_path"] = site["search_path"]
    else:
        entry.pop("search_path", None)
    rows = ", ".join(section["title"] for section in site["home_sections"]) or "-"
    log(f"  {entry['url']}: {plugin}, {len(site['home_sections'])} bölüm ({rows})")
    return True


def catalog_flow(args, *, log=print) -> None:
    """--import / --check / --plan / --prune: keeps sites.json up to date."""
    catalog = Path(args.plan or args.catalog or "sites.json") if args.plan is not None \
        else Path(args.catalog or "sites.json")
    registry = reg.Registry(catalog)
    sources = list(args.import_files or [])
    if args.candidates:
        sources.append(args.candidates)
    pattern = re.compile(args.filter, re.I) if args.filter else None

    for path in sources:
        accepted, skipped = reg.read_addresses(Path(path), allow_denied=args.allow_denied)
        if pattern:
            accepted = [item for item in accepted
                        if pattern.search(f"{item['url']} {item['title']}")]
        added = sum(registry.upsert(item["url"], source=item["source"], title=item["title"])[1]
                    for item in accepted)
        log(f"{path}: {len(accepted)} adres okundu ({added} yeni), {len(skipped)} atlandı")
        for item in skipped[:5]:
            log(f"   - {item['value']} ({item['reason']})")
        if len(skipped) > 5:
            log(f"   - … {len(skipped) - 5} tane daha")

    if args.check:
        todo = [entry for entry in registry.sites if entry.get("status") in ("candidate", "ok", "planned")]
        log(f"{len(todo)} adres denetleniyor…")
        for entry in todo:
            check_entry(entry, min_score=args.min_score, timeout=args.timeout,
                        delay=args.delay, log=log)

    if args.plan is not None:
        todo = [entry for entry in registry.sites if entry.get("status") == "ok"]
        log(f"{len(todo)} site için bölüm/arama aranıyor…")
        for entry in todo:
            plan_catalog_entry(entry, limit=args.limit, timeout=args.timeout, log=log)

    if args.prune:
        dropped = registry.prune()
        log(f"{len(dropped)} kayıt silindi (yanıt vermeyen / kullanılamaz).")
        for entry in dropped:
            log(f"   - {entry.get('url')}")

    registry.save()
    counts = ", ".join(f"{status}: {count}" for status, count in sorted(registry.counts().items()))
    log(f"{catalog}: {len(registry.sites)} kayıt ({counts})")
    planned = sum(1 for entry in registry.sites if entry.get("status") == "planned")
    if planned:
        log(f"Sonraki adım: python3 scripts/auto_update.py --config {catalog} --dry-run")


def resolve_flow(args) -> None:
    """Address input without a catalogue: scan, optionally write --out / --apply."""
    candidates = read_candidates(args.candidates) if args.candidates else []
    seeds = list(args.seeds) or candidates
    if not seeds and args.plugin:
        import auto_update as au  # only needed to read the current address
        seeds = [au.read_state(args.plugin)["url"]]
    if not seeds:
        die("en az bir adres verin (ya da --import / --candidates / --plugin kullanın)")

    results: list[dict] = []
    for seed in seeds:
        results.extend(resolve(seed, candidates=candidates, timeout=args.timeout,
                               delay=args.delay, log=lambda m: print(m, file=sys.stderr)))
    results.sort(key=lambda item: (item["reachable"], item["score"]), reverse=True)
    results = _dedupe(results)

    workable = [item for item in results if item["reachable"]]
    print(f"{len(results)} adres denendi, {len(workable)} tanesi yanıt verdi:", file=sys.stderr)
    for item in results:
        mark = " " if item["reachable"] else "-"
        mirrors = f"  (+{len(item['mirrors'])} mirror)" if item.get("mirrors") else ""
        print(f" {mark} {item['score']:.2f}  {item['url']:<38} {item['title'][:40]}{mirrors}",
              file=sys.stderr)

    if args.out:
        try:
            args.out.write_text(
                json.dumps({"sites": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as e:
            die(f"{args.out} yazılamadı: {e}")
        print(f"{args.out} yazıldı.", file=sys.stderr)

    if args.apply:
        best = next((item for item in workable if item["score"] >= args.min_score), None)
        if best is None:
            die(f"benzerliği {args.min_score} üzerinde çalışan adres yok")
        import auto_update as au  # imported late: --apply is the only writing path
        target = best["final"] or best["url"]
        print(f"en iyi adres: {best['url']} (benzerlik {best['score']:.2f}) -> {target}",
              file=sys.stderr)
        au.run({"plugin": args.plugin, "url": target, "selectors": {}},
               dry_run=args.dry_run, no_commit=args.no_commit, no_push=args.no_push,
               allow_dirty=args.dry_run)
    elif not args.out:
        print(json.dumps({"sites": results}, ensure_ascii=False, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Sitenin çalışan adresini bul; adres listelerini kataloğa kaydet; plan üret.")
    ap.add_argument("seeds", nargs="*", help="başlangıç adresleri (örn. https://ornek.com)")
    ap.add_argument("--catalog", type=Path, default=Path("sites.json"),
                    help="katalog dosyası (varsayılan sites.json)")
    ap.add_argument("--import", dest="import_files", action="append", metavar="DOSYA",
                    help="adres listesi ekle: .txt, .csv/.tsv, .md, yer imleri .html (tekrarlanabilir)")
    ap.add_argument("--check", action="store_true", help="katalogdaki adresleri dene, durumu yaz")
    ap.add_argument("--plan", nargs="?", const="", metavar="DOSYA",
                    help="bölüm/arama bul ve plana çevir (dosya verilmezse --catalog)")
    ap.add_argument("--prune", action="store_true", help="yanıt vermeyen / kullanılamaz kayıtları sil")
    ap.add_argument("--filter", help="yalnız adresi/başlığı bu düzenli ifadeye uyanları al")
    ap.add_argument("--allow-denied", action="store_true",
                    help="arama motoru/sosyal medya adreslerini de kataloğa al")
    ap.add_argument("--candidates", type=Path, help="katalog modunda ek adres dosyası")
    ap.add_argument("--out", type=Path, help="tarama sonucunu JSON dosyasına yaz")
    ap.add_argument("--limit", type=int, default=6, help="planda site başına en fazla bölüm (varsayılan 6)")
    ap.add_argument("--min-score", type=float, default=MIN_SCORE,
                    help=f"bir adresi kabul etmek için en az benzerlik (varsayılan {MIN_SCORE})")
    ap.add_argument("--timeout", type=int, default=20, help="istek zaman aşımı, saniye")
    ap.add_argument("--delay", type=float, default=0.2, help="istekler arası bekleme, saniye")
    ap.add_argument("--apply", action="store_true", help="en iyi adresi eklentiye yaz")
    ap.add_argument("--plugin", help="--apply için eklenti dizini")
    ap.add_argument("--dry-run", action="store_true", help="--apply ile: yalnızca farkı göster")
    ap.add_argument("--no-commit", action="store_true", help="--apply ile: dosyaları yaz, commit atma")
    ap.add_argument("--no-push", action="store_true", help="--apply ile: commit at ama gönderme")
    args = ap.parse_args()

    catalog_mode = bool(args.import_files or args.check or args.prune or args.plan is not None)
    try:
        if catalog_mode:
            if args.apply:
                die("katalog modunda --apply kullanılmaz; planı uygulamak için "
                    "auto_update.py --config sites.json kullanın")
            catalog_flow(args)
        else:
            resolve_flow(args)
    except (ResolveError, reg.RegistryError) as e:
        print(f"HATA: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
