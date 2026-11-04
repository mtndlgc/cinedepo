#!/usr/bin/env python3
"""
Desktop editor for the plugin's site settings, in your browser.

    python3 scripts/site_editor.py            # opens http://127.0.0.1:8765
    python3 scripts/site_editor.py --port 9000 --no-browser

Shows the current SiteConfig.kt values (URL, name, language, search path,
homepage rows, extra hosts, every CSS selector). "Önizle" shows the diff,
"Kaydet" writes the files and bumps the version, "Kaydet ve gönder" also
commits and pushes, which starts the GitHub Actions build.

Only the Python 3 standard library is needed. The server listens on
127.0.0.1 only and every write request needs a per-run token, so other
websites open in your browser cannot drive it.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.dont_write_bytecode = True  # no scripts/__pycache__ in the working tree
sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_update as au  # noqa: E402

TOKEN = secrets.token_urlsafe(24)
LOCK = threading.Lock()
MAX_BODY = 256 * 1024


def settings_from_payload(p: dict) -> dict:
    s = {
        "plugin": p.get("plugin") or None,
        "url": str(p.get("url", "")).strip(),
        "name": str(p.get("name", "")).strip(),
        "lang": str(p.get("lang", "")).strip(),
        "search_path": str(p.get("search_path", "")).strip(),
        "home_sections": [
            {"path": str(h.get("path", "")).strip(), "title": str(h.get("title", "")).strip()}
            for h in p.get("home_sections", []) if str(h.get("path", "")).strip()
        ],
        "extra_hosts": [h.strip() for h in p.get("extra_hosts", []) if h.strip()],
        "selectors": {str(k): str(v) for k, v in (p.get("selectors") or {}).items()},
    }
    for key in ("url", "name", "lang", "search_path"):
        if not s[key]:
            raise au.UpdateError(f"'{key}' boş bırakılamaz")
    for key, value in s["selectors"].items():
        if not value.strip():
            raise au.UpdateError(f"{key} seçicisi boş bırakılamaz")
    return s


class Handler(BaseHTTPRequestHandler):
    server_version = "CineDepoEditor"

    def log_message(self, fmt, *args):  # quieter console
        sys.stderr.write("  %s\n" % (fmt % args))

    # --------------------------------------------------------------- utils
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: dict) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    # ---------------------------------------------------------------- GET
    def do_GET(self):  # noqa: N802
        if not self._host_ok():
            return self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
        url = urlparse(self.path)
        if url.path == "/":
            html = PAGE.replace("__TOKEN__", TOKEN).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(html)
            return
        if url.path == "/api/state":
            if self.headers.get("X-Token") != TOKEN:
                return self._json(HTTPStatus.FORBIDDEN, {"error": "geçersiz anahtar"})
            plugin = (parse_qs(url.query).get("plugin") or [None])[0] or (au.list_plugins() or [None])[0]
            try:
                return self._json(HTTPStatus.OK, au.read_state(plugin))
            except au.UpdateError as e:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
        self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

    # --------------------------------------------------------------- POST
    def do_POST(self):  # noqa: N802
        if not self._host_ok() or self.headers.get("X-Token") != TOKEN:
            return self._json(HTTPStatus.FORBIDDEN, {"error": "geçersiz istek"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "istek çok büyük"})
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "geçersiz JSON"})

        mode = urlparse(self.path).path
        if mode not in ("/api/preview", "/api/save", "/api/publish"):
            return self._json(HTTPStatus.NOT_FOUND, {"error": "bilinmeyen işlem"})

        lines: list[str] = []
        try:
            settings = settings_from_payload(payload)
            with LOCK:
                result = au.run(
                    settings,
                    dry_run=mode == "/api/preview",
                    no_bump=not payload.get("bump", True),
                    no_commit=mode != "/api/publish",
                    no_push=mode != "/api/publish",
                    check=bool(payload.get("check")) and mode == "/api/preview",
                    log=lambda *a: lines.append(" ".join(str(x) for x in a)),
                )
        except au.UpdateError as e:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e), "log": lines})
        # the diff is returned separately; keep the log readable
        log = [line for line in lines if line != result.get("diff")]
        return self._json(HTTPStatus.OK, {**result, "log": log})


PAGE = r"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CineDepo Site Düzenleyici</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#1d2128;--muted:#5d6675;--line:#dde1e7;--accent:#2f6fde;--accent-fg:#fff;
--ok:#1f7a3f;--err:#b3261e;--add:#e6f4ea;--del:#fce8e6;--add-fg:#155c2e;--del-fg:#8c1d18;--code:#f0f2f5}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--card:#1a1e24;--fg:#e6e9ee;--muted:#9aa3b2;--line:#2c323b;
--accent:#6d9cf0;--accent-fg:#0b1220;--ok:#6fcf97;--err:#f28b82;--add:#16301f;--del:#3a1a18;--add-fg:#a8e6bd;--del-fg:#f6b9b3;--code:#14181d}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{padding:20px 16px 8px;max-width:1100px;margin:0 auto}
header h1{margin:0;font-size:22px}
header p{margin:4px 0 0;color:var(--muted)}
main{max-width:1100px;margin:0 auto;padding:8px 16px 140px;display:grid;gap:16px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
section h2{margin:0 0 12px;font-size:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
label{display:block;font-size:13px;color:var(--muted);margin-bottom:4px}
input[type=text],select,textarea{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:7px;
background:var(--bg);color:var(--fg);font:14px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
input:focus,select:focus,textarea:focus{outline:2px solid var(--accent);outline-offset:-1px}
.hint{font-size:12px;color:var(--muted);margin-top:3px}
.row{display:grid;grid-template-columns:2fr 1.4fr auto;gap:8px;margin-bottom:8px}
.sel{display:grid;grid-template-columns:minmax(180px,260px) 1fr;gap:4px 12px;align-items:start;
padding:8px 0;border-top:1px solid var(--line)}
.sel:first-of-type{border-top:0}
.sel code{font-size:12px;color:var(--muted)}
.group{margin:16px 0 4px;font-weight:600}
.group:first-child{margin-top:0}
button{font:inherit;border-radius:7px;border:1px solid var(--line);background:var(--card);color:var(--fg);
padding:8px 14px;cursor:pointer}
button.primary{background:var(--accent);color:var(--accent-fg);border-color:var(--accent);font-weight:600}
button:disabled{opacity:.5;cursor:wait}
button.icon{padding:6px 10px}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line)}
.bar .in{max-width:1100px;margin:0 auto;padding:12px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.bar .opts{display:flex;gap:14px;flex-wrap:wrap;margin-right:auto;color:var(--muted);font-size:14px}
.bar .opts label{display:inline;color:inherit;font-size:inherit}
#status{font-size:14px}
.ok{color:var(--ok)}.err{color:var(--err)}
pre{margin:0;background:var(--code);border:1px solid var(--line);border-radius:7px;padding:10px;overflow:auto;
font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;max-height:460px;white-space:pre}
pre .a{background:var(--add);color:var(--add-fg)}pre .d{background:var(--del);color:var(--del-fg)}pre .h{color:var(--muted)}
.log{white-space:pre-wrap;margin-top:10px}
@media (max-width:640px){main{padding-bottom:240px}.row{grid-template-columns:1fr 1fr}.row button{grid-column:span 2}.sel{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <h1>CineDepo Site Düzenleyici</h1>
  <p>Eklentinin hedef sitesini ve CSS seçicilerini buradan düzenle. Yalnızca kullanım koşulları otomatik erişime izin veren siteleri hedefle.</p>
</header>
<main>
  <section>
    <h2>Eklenti</h2>
    <div class="grid">
      <div><label for="plugin">Eklenti dizini</label><select id="plugin"></select></div>
      <div><label>Eklenti sürümü (yereldeki)</label><div id="version" style="padding:8px 0;font-weight:600">-</div></div>
    </div>
  </section>

  <section>
    <h2>Site</h2>
    <div class="grid">
      <div><label for="url">Site adresi</label><input type="text" id="url" placeholder="https://site.com" autocomplete="off">
        <div class="hint">https:// ile başlat, sona / koyma.</div></div>
      <div><label for="name">Uygulamada görünen ad</label><input type="text" id="name"></div>
      <div><label for="lang">İçerik dili</label><input type="text" id="lang" maxlength="3">
        <div class="hint">ISO kodu: tr, en, de…</div></div>
      <div><label for="search_path">Arama yolu</label><input type="text" id="search_path" placeholder="/arama?q=%s">
        <div class="hint">%s = aranan kelime</div></div>
    </div>
  </section>

  <section>
    <h2>Ana sayfa satırları</h2>
    <div class="hint" style="margin:-6px 0 10px">Her satır uygulamanın ana sayfasında bir liste olur. %d = sayfa numarası.</div>
    <div id="home"></div>
    <button type="button" id="addHome">+ Satır ekle</button>
  </section>

  <section>
    <h2>Ek alan adları</h2>
    <label for="hosts">Bölüm ve liste bağlantılarının gidebileceği diğer alan adları (her satıra bir tane)</label>
    <textarea id="hosts" rows="3" placeholder="cdn.site.com"></textarea>
  </section>

  <section>
    <h2>CSS seçicileri</h2>
    <div class="hint" style="margin:-6px 0 10px">Tarayıcıda sağ tık &gt; İncele ile bul, konsolda <code>document.querySelectorAll("…")</code> ile dene.</div>
    <div id="selectors"></div>
  </section>

  <section id="outSec" hidden>
    <h2>Sonuç</h2>
    <pre id="diff"></pre>
    <pre id="log" class="log" hidden></pre>
  </section>
</main>

<div class="bar"><div class="in">
  <div class="opts">
    <label><input type="checkbox" id="bump" checked> Sürümü artır</label>
    <label><input type="checkbox" id="check"> Önizlemede seçicileri canlı sayfada dene</label>
  </div>
  <span id="status"></span>
  <button type="button" id="preview">Önizle</button>
  <button type="button" id="save">Kaydet</button>
  <button type="button" id="publish" class="primary">Kaydet ve GitHub'a gönder</button>
</div></div>

<script>
const TOKEN = "__TOKEN__";
const GROUPS = {
  "Listing pages (homepage rows and search results)": "Liste sayfaları (ana sayfa ve arama)",
  "Detail page": "Film / dizi detay sayfası",
  "Series": "Dizi bölümleri",
  "Player / video sources": "Oynatıcı ve video kaynakları"
};
const LABELS = {
  LIST_ITEM:"Her film/dizi kartı", ITEM_TITLE:"Karttaki başlık", ITEM_LINK:"Karttaki bağlantı", ITEM_POSTER:"Karttaki afiş",
  ITEM_IS_SERIES:"Yalnız dizi kartlarında olan öğe", NEXT_PAGE:"Sonraki sayfa bağlantısı",
  DETAIL_TITLE:"Başlık", DETAIL_POSTER:"Afiş", DETAIL_PLOT:"Özet", DETAIL_YEAR:"Yıl", DETAIL_TAGS:"Türler",
  DETAIL_ACTORS:"Oyuncular", DETAIL_TRAILER:"Fragman", DETAIL_RECOMMENDED:"Önerilen içerik kartları",
  SEASON_BLOCK:"Sezon kutusu", SEASON_NUMBER_ATTR:"Sezon numarası özniteliği", EPISODE_ITEM:"Bölüm öğesi",
  EPISODE_LINK:"Bölüm bağlantısı", EPISODE_NAME:"Bölüm adı", EPISODE_NUMBER_ATTR:"Bölüm numarası özniteliği",
  EPISODE_THUMB:"Bölüm görseli", PLAYER_IFRAME:"Oynatıcı iframe", DIRECT_SOURCE:"Doğrudan video kaynağı",
  SUBTITLE_TRACK:"Altyazı", PLAYER_SCRIPT:"Oynatıcı ayarı içeren script"
};
const $ = id => document.getElementById(id);
let busy = false;

async function api(path, body) {
  const opt = {headers: {"X-Token": TOKEN}};
  if (body !== undefined) { opt.method = "POST"; opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({error: "sunucu yanıtı okunamadı"}));
  if (!r.ok) throw Object.assign(new Error(data.error || r.statusText), {data});
  return data;
}

function homeRow(path = "", title = "") {
  const row = document.createElement("div"); row.className = "row";
  row.innerHTML = '<input type="text" placeholder="/filmler/sayfa/%d" aria-label="Yol">' +
                  '<input type="text" placeholder="Başlık" aria-label="Başlık">' +
                  '<button type="button" class="icon" aria-label="Satırı sil">Sil</button>';
  const [p, t] = row.querySelectorAll("input"); p.value = path; t.value = title;
  row.querySelector("button").onclick = () => row.remove();
  $("home").appendChild(row);
}

function render(st) {
  $("plugin").innerHTML = "";
  for (const p of st.plugins) { const o = new Option(p, p, false, p === st.plugin); $("plugin").add(o); }
  $("version").textContent = st.version ?? "-";
  for (const k of ["url", "name", "lang", "search_path"]) $(k).value = st[k] || "";
  $("home").innerHTML = ""; (st.home_sections.length ? st.home_sections : [{path:"",title:""}]).forEach(h => homeRow(h.path, h.title));
  $("hosts").value = st.extra_hosts.join("\n");
  const box = $("selectors"); box.innerHTML = ""; let g = null;
  for (const s of st.selectors) {
    if (s.group !== g) { g = s.group; const h = document.createElement("div"); h.className = "group"; h.textContent = GROUPS[g] || g; box.appendChild(h); }
    const row = document.createElement("div"); row.className = "sel";
    const left = document.createElement("div");
    const lab = document.createElement("label"); lab.htmlFor = "sel_" + s.key; lab.textContent = LABELS[s.key] || s.key;
    lab.style.color = "var(--fg)"; lab.style.fontSize = "14px";
    const code = document.createElement("code"); code.textContent = s.key;
    left.append(lab, code);
    const right = document.createElement("div");
    const inp = document.createElement("input"); inp.type = "text"; inp.id = "sel_" + s.key; inp.dataset.key = s.key; inp.value = s.value;
    right.appendChild(inp);
    if (s.note) { const n = document.createElement("div"); n.className = "hint"; n.textContent = s.note; right.appendChild(n); }
    row.append(left, right); box.appendChild(row);
  }
}

function collect() {
  const selectors = {};
  document.querySelectorAll("#selectors input[data-key]").forEach(i => selectors[i.dataset.key] = i.value);
  return {
    plugin: $("plugin").value, url: $("url").value, name: $("name").value, lang: $("lang").value,
    search_path: $("search_path").value,
    home_sections: [...document.querySelectorAll("#home .row")].map(r => { const [p, t] = r.querySelectorAll("input"); return {path: p.value, title: t.value}; }),
    extra_hosts: $("hosts").value.split("\n"),
    selectors, bump: $("bump").checked, check: $("check").checked
  };
}

function showDiff(diff, log) {
  $("outSec").hidden = false;
  const pre = $("diff"); pre.textContent = "";
  if (!diff) { pre.textContent = "Fark yok."; }
  for (const line of (diff || "").split("\n")) {
    const span = document.createElement("span");
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) span.className = "h";
    else if (line.startsWith("+")) span.className = "a";
    else if (line.startsWith("-")) span.className = "d";
    span.textContent = line + "\n"; pre.appendChild(span);
  }
  const lg = $("log"); lg.hidden = !(log && log.length); lg.textContent = (log || []).join("\n");
}

function status(msg, cls) { const s = $("status"); s.textContent = msg; s.className = cls || ""; }

async function act(kind) {
  if (busy) return;
  if (kind === "publish" && !confirm("Değişiklikler commit'lenip GitHub'a gönderilecek ve derleme başlayacak. Devam edilsin mi?")) return;
  busy = true; document.querySelectorAll(".bar button").forEach(b => b.disabled = true);
  status(kind === "preview" ? "Önizleniyor…" : kind === "save" ? "Kaydediliyor…" : "Gönderiliyor…");
  try {
    const r = await api("/api/" + kind, collect());
    showDiff(r.diff, r.log);
    if (!r.changed) status("Değişecek bir şey yok.", "ok");
    else if (r.pushed) status("Gönderildi. GitHub Actions derlemeyi başlattı (~2 dk).", "ok");
    else if (r.written) status("Kaydedildi (commit atılmadı).", "ok");
    else status("Önizleme hazır; dosyalar yazılmadı.", "ok");
    if (r.written) await load($("plugin").value, true);
  } catch (e) {
    status("Hata: " + e.message, "err");
    if (e.data && e.data.log && e.data.log.length) showDiff("", e.data.log);
  } finally {
    busy = false; document.querySelectorAll(".bar button").forEach(b => b.disabled = false);
  }
}

async function load(plugin, keepStatus) {
  try {
    render(await api("/api/state" + (plugin ? "?plugin=" + encodeURIComponent(plugin) : "")));
    if (!keepStatus) status("");
  } catch (e) { status("Hata: " + e.message, "err"); }
}

$("addHome").onclick = () => homeRow();
$("plugin").onchange = e => load(e.target.value);
$("preview").onclick = () => act("preview");
$("save").onclick = () => act("save");
$("publish").onclick = () => act("publish");
load();
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="CineDepo site düzenleyicisi (tarayıcıda açılır).")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="tarayıcıyı otomatik açma")
    args = ap.parse_args()

    if not au.list_plugins():  # fail early if the repo layout is wrong
        print(f"HATA: {au.ROOT} altında SiteConfig.kt içeren eklenti bulunamadı", file=sys.stderr)
        sys.exit(1)

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)  # port busy: pick a free one
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Site düzenleyici: {url}  (kapatmak için Ctrl+C)")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nKapatıldı.")


if __name__ == "__main__":
    main()
