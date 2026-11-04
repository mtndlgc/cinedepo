"""Checks for scripts/find_site.py: address variants, mirror links, scoring, probing.

    python3 -m unittest discover -s scripts/tests -v

The "sites" are three local servers; no network and no dependencies.
"""
from __future__ import annotations

import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import find_site as fs  # noqa: E402


def page(title: str, prefix: str, *, nav=("/filmler", "/diziler"), form=True, cards=40) -> str:
    links = "".join(f'<a href="{prefix}/{i}">içerik</a>' for i in range(cards))
    navhtml = "".join(f'<a href="{path}">{path}</a>' for path in nav)
    formhtml = '<form action="/arama" method="get"><input type="search" name="q"></form>' if form else ""
    return (f'<html lang="tr"><head><title>{title}</title></head>'
            f"<body><nav>{navhtml}</nav>{formhtml}{links}</body></html>")


SIMILAR = page("Ornek Dizi - Film izle", "/filmler")
UNRELATED = page("Bambaşka Bir Şey", "/x", nav=("/a", "/b"), form=False)


class Handler(BaseHTTPRequestHandler):
    body = ""

    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        data = self.body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(body: str) -> ThreadingHTTPServer:
    handler = type("H", (Handler,), {"body": body})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class AddressTest(unittest.TestCase):
    def test_netloc_and_label(self):
        self.assertEqual(fs.netloc_of("https://www.Ornek.com/yol?x=1"), "www.ornek.com")
        self.assertEqual(fs.netloc_of("ornek.com"), "ornek.com")
        self.assertEqual(fs.label_of("www.hdfilmcehennemi.nl:8080"), "hdfilmcehennemi")

    def test_variants_keep_port_and_skip_ip(self):
        self.assertIn("ornek.com", fs.host_variants("www.ornek.com"))
        self.assertIn("ornek.net", fs.host_variants("ornek.com"))
        self.assertIn("ornek.com:8080", fs.host_variants("ornek.com:8080"))
        self.assertEqual(fs.host_variants("127.0.0.1:8080"), {"127.0.0.1:8080"})

    def test_plugin_name(self):
        self.assertEqual(fs.plugin_name_for("www.ornek-site.com"), "Orneksite")
        self.assertEqual(fs.plugin_name_for("127.0.0.1:8080"), "Site127")

    def test_mirror_links(self):
        html = ('<html><body>'
                '<a href="https://ayna.example.com">Yeni adres</a>'
                '<a href="https://ornek.net">ornek</a>'
                '<a href="https://baska.example.org">başka site</a>'
                '</body></html>')
        found = fs.mirror_links(html, "https://www.ornek.com/")
        self.assertIn("ayna.example.com", found)
        self.assertIn("ornek.net", found)          # aynı ad, başka TLD
        self.assertNotIn("baska.example.org", found)

    def test_similarity_orders_pages(self):
        reference = fs.signature(SIMILAR, "https://ornek.com/")
        same = fs.similarity(reference, fs.signature(SIMILAR, "https://mirror.ornek.net/"))
        other = fs.similarity(reference, fs.signature(UNRELATED, "https://baska.com/"))
        self.assertGreater(same, 0.9)
        self.assertLess(other, 0.2)


class ResolveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.similar = serve(SIMILAR)
        cls.other = serve(UNRELATED)
        cls.similar_url = f"http://127.0.0.1:{cls.similar.server_address[1]}"
        cls.other_url = f"http://127.0.0.1:{cls.other.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        for server in (cls.similar, cls.other):
            server.shutdown()
            server.server_close()

    def test_ranks_the_matching_site_first(self):
        results = fs.resolve(self.similar_url, candidates=[self.other_url], timeout=3, delay=0,
                             dedupe=False, log=lambda *_: None)
        self.assertEqual(results[0]["url"], self.similar_url)
        self.assertGreater(results[0]["score"], 0.8)
        unrelated = next(item for item in results if item["url"] == self.other_url)
        self.assertLess(unrelated["score"], 0.4)
        self.assertTrue(unrelated["reachable"])

    def test_dead_address_is_reported_not_raised(self):
        results = fs.resolve("127.0.0.1:9", timeout=2, delay=0, dedupe=False, log=lambda *_: None)
        self.assertFalse(results[0]["reachable"])
        self.assertEqual(results[0]["score"], 0.0)

    def test_best_domain_falls_back_to_a_candidate(self):
        # The address in the config is gone; the candidate still resembles a listing site.
        best = fs.best_domain("127.0.0.1:9", candidates=[self.similar_url], timeout=3, delay=0,
                              log=lambda *_: None)
        self.assertEqual(best, self.similar_url)

    def test_best_domain_returns_none_for_hopeless_input(self):
        self.assertIsNone(fs.best_domain("127.0.0.1:9", timeout=1, delay=0, log=lambda *_: None))


if __name__ == "__main__":
    unittest.main()
