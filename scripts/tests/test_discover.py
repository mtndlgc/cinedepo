"""Checks for scripts/discover_site.py against a local throw-away web server.

    python3 -m unittest discover -s scripts/tests -v

No network, no dependencies: the "site" is generated in memory.
"""
from __future__ import annotations

import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discover_site as ds  # noqa: E402


def listing(title: str, prefix: str, *, pages: bool = True, query_page: bool = False) -> str:
    cards = "".join(
        f'<article class="item"><a href="{prefix}/film-{i}"><img src="/p{i}.jpg" alt="Film {i}"></a></article>'
        for i in range(1, 8))
    pager = ""
    if pages:
        pager = f'<a href="{prefix}?sayfa=2">2</a>' if query_page else f'<a href="{prefix}/page/2">2</a>'
    return (f"<!doctype html><html><head><title>{title}</title></head>"
            f"<body><h1>{title}</h1>{cards}{pager}</body></html>")


HOME = """<!doctype html>
<html lang="tr"><head><title>Ornek Site - Film izle</title>
<meta property="og:site_name" content="Ornek Site"></head>
<body>
<header><a href="/">Ana sayfa</a></header>
<nav class="main-menu">
  <a href="/filmler">Filmler</a>
  <a href="/diziler">Diziler</a>
  <a href="/kategori/aksiyon">Aksiyon</a>
  <a href="/giris">Giriş</a>
</nav>
<form action="/arama" method="get"><input type="search" name="q"></form>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    routes: dict[str, str] = {}

    def log_message(self, *args):  # keep the test output clean
        pass

    def do_GET(self):  # noqa: N802
        body = self.routes.get(self.path)
        if body is None:
            body = listing("Filmler", "/filmler")
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class DiscoverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Handler.routes = {
            "/": HOME,
            "/filmler": listing("Filmler", "/filmler"),
            "/filmler/page/2": listing("Filmler", "/filmler"),
            "/diziler": listing("Diziler", "/diziler"),
            "/kategori/aksiyon": listing("Aksiyon", "/kategori/aksiyon"),
        }
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def discover(self, **kwargs):
        return ds.discover(self.base + "/", delay=0, timeout=5, log=lambda *_: None, **kwargs)

    def test_finds_sections_search_and_pagination(self):
        result = self.discover()
        paths = {s["path"]: s["title"] for s in result["home_sections"]}
        self.assertEqual(result["search_path"], "/arama?q=%s")
        self.assertEqual(result["name"], "Ornek Site")
        self.assertEqual(result["lang"], "tr")
        self.assertEqual(result["url"], self.base)
        self.assertIn("/filmler/page/%d", paths)
        self.assertIn("/diziler/page/%d", paths)
        self.assertIn("/kategori/aksiyon/page/%d", paths)
        self.assertEqual(paths["/diziler/page/%d"], "Diziler")
        self.assertNotIn("/giris", {p.removesuffix("/page/%d") for p in paths})

    def test_query_pagination(self):
        Handler.routes["/filmler"] = listing("Filmler", "/filmler", query_page=True)
        Handler.routes["/filmler?sayfa=2"] = listing("Filmler", "/filmler")
        try:
            result = self.discover()
        finally:
            Handler.routes["/filmler"] = listing("Filmler", "/filmler")
        self.assertIn("/filmler?sayfa=%d", [s["path"] for s in result["home_sections"]])

    def test_missing_search_form_is_reported(self):
        Handler.routes["/"] = HOME.replace("<form", "<!--<form").replace("</form>", "</form>-->")
        try:
            result = self.discover()
        finally:
            Handler.routes["/"] = HOME
        self.assertNotIn("search_path", result)

    def test_no_verify_keeps_candidate_paths(self):
        result = self.discover(verify=False)
        paths = [s["path"] for s in result["home_sections"]]
        self.assertIn("/filmler", paths)
        self.assertNotIn("/filmler/page/%d", paths)

    def test_ignores_offsite_and_detail_links(self):
        home = HOME.replace(
            '<a href="/filmler">Filmler</a>',
            '<a href="/filmler">Filmler</a>'
            '<a href="/film/ask-2012-1234">Aşk</a>'
            '<a href="https://baska.example/filmler">Başka site</a>')
        Handler.routes["/"] = home
        try:
            result = self.discover()
        finally:
            Handler.routes["/"] = HOME
        paths = [s["path"] for s in result["home_sections"]]
        self.assertNotIn("/film/ask-2012-1234", paths)
        self.assertFalse([p for p in paths if "baska" in p])


if __name__ == "__main__":
    unittest.main()
