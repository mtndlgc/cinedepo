"""Checks for scripts/site_registry.py and the catalogue mode of find_site.py.

    python3 -m unittest discover -s scripts/tests -v

Reading lists needs no network; the catalogue flow is tested against local servers.
"""
from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

WORKDIR = ROOT / ".test-tmp"
_CREATED: list[Path] = []
_RUN = f"{os.getpid()}-{int(time.time())}"
_CASES = itertools.count(1)


def new_workdir() -> Path:
    """A fresh writable scratch directory: system temp first, then .test-tmp inside the repo."""
    for base in (Path(tempfile.gettempdir()), WORKDIR):
        work = base / f"cinedepo-tests-{_RUN}-{next(_CASES)}"
        try:
            work.mkdir(parents=True, exist_ok=True)
            marker = work / ".ok"
            marker.write_text("ok", encoding="utf-8")
            marker.unlink()
            _CREATED.append(work)
            return work
        except OSError:
            continue
    raise unittest.SkipTest("yazılabilir geçici dizin yok")

import find_site as fs  # noqa: E402
import site_registry as reg  # noqa: E402


def listing(prefix: str) -> str:
    cards = "".join(f'<article><a href="{prefix}/film-{i}">Film {i}</a></article>'
                    for i in range(1, 8))
    return f'<html><body><h1>{prefix}</h1>{cards}<a href="{prefix}/page/2">2</a></body></html>'


HOME = """<html lang="tr"><head><title>Ornek Film - izle</title></head><body>
<nav><a href="/filmler">Filmler</a><a href="/diziler">Diziler</a></nav>
<form action="/arama" method="get"><input type="search" name="q"></form></body></html>"""


class Handler(BaseHTTPRequestHandler):
    routes: dict[str, str] = {}

    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        body = self.routes.get(self.path, HOME)
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.dir = new_workdir()
        Handler.routes = {"/filmler": listing("/filmler"), "/diziler": listing("/diziler")}

    def write(self, name: str, body: str) -> Path:
        path = self.dir / name
        path.write_text(body, encoding="utf-8")
        return path

    def read(self, name: str, body: str, **kwargs):
        return reg.read_addresses(self.write(name, body), **kwargs)

    def test_plain_text(self):
        accepted, skipped = self.read("domains.txt", """# film listesi
https://ornek.com/yol
ornek.net   # yorum
mailto: biri@ornek.com
""")
        self.assertEqual([item["url"] for item in accepted], ["https://ornek.com", "https://ornek.net"])
        self.assertEqual(skipped[0]["reason"], "geçersiz adres")
        self.assertTrue(accepted[0]["source"].startswith("domains.txt:"))

    def test_csv_with_header(self):
        accepted, _ = self.read("siteler.csv", "URL,Başlık\nhttps://a.example,A Filmi\nb.example,B\n")
        self.assertEqual([item["url"] for item in accepted], ["https://a.example", "https://b.example"])
        self.assertEqual(accepted[0]["title"], "A Filmi")

    def test_csv_without_header(self):
        accepted, _ = self.read("liste.csv", "https://a.example\nhttps://b.example\n")
        self.assertEqual(len(accepted), 2)

    def test_markdown(self):
        accepted, _ = self.read("liste.md", "- [Örnek](https://ornek.com)\n| x | https://b.example |\n")
        self.assertEqual([item["url"] for item in accepted], ["https://ornek.com", "https://b.example"])
        self.assertEqual(accepted[0]["title"], "Örnek")

    def test_bookmarks_html(self):
        accepted, _ = self.read(
            "bookmarks.html",
            '<DL><DT><H3>Filmler</H3><DL><DT><A HREF="https://ornek.com">Örnek</A></DL></DL>')
        self.assertEqual([item["url"] for item in accepted], ["https://ornek.com"])
        self.assertEqual(accepted[0]["title"], "Örnek")

    def test_search_engine_and_duplicates_are_skipped(self):
        accepted, skipped = self.read("liste.txt", "https://www.google.com\nhttps://ornek.com\nhttp://ornek.com/x\n")
        self.assertEqual([item["url"] for item in accepted], ["https://ornek.com"])
        reasons = [item["reason"] for item in skipped]
        self.assertIn("arama motoru/sosyal medya", reasons)
        self.assertIn("tekrar", reasons)


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.path = new_workdir() / "sites.json"

    def test_upsert_keeps_provenance_and_identity(self):
        registry = reg.Registry(self.path)
        entry, created = registry.upsert("https://ornek.com", source="a.txt:1")
        self.assertTrue(created)
        self.assertEqual(entry["status"], "candidate")
        again, created = registry.upsert("http://www.ornek.com/yol", source="bmd.html:2", title="Örnek")
        self.assertFalse(created)
        self.assertEqual(len(registry.sites), 1)
        self.assertEqual(again["sources"], ["a.txt:1", "bmd.html:2"])
        self.assertEqual(again["title"], "Örnek")
        self.assertEqual(again["added"], entry["added"])
        again["status"] = "ok"
        registry.save()

        reopened = reg.Registry(self.path)
        self.assertEqual(reopened.sites[0]["status"], "ok")
        self.assertEqual(reopened.find("https://www.ornek.com")["status"], "ok")

    def test_unwritable_catalog_is_reported(self):
        target = new_workdir() / "kilitli.json"
        target.mkdir()  # a directory where the file should be: writing must fail cleanly
        registry = reg.Registry(new_workdir() / "s.json")
        registry.path = target
        with self.assertRaises(reg.RegistryError):
            registry.save()

    def test_prune_drops_only_dead_entries(self):
        registry = reg.Registry(self.path)
        good, _ = registry.upsert("https://iyi.example")
        bad, _ = registry.upsert("https://olu.example")
        good["status"] = "planned"
        bad["status"] = "unreachable"
        dropped = registry.prune()
        self.assertEqual([item["url"] for item in dropped], ["https://olu.example"])
        self.assertEqual([entry["url"] for entry in registry.sites], ["https://iyi.example"])

    def test_missing_file_starts_empty(self):
        registry = reg.Registry(self.path)
        self.assertEqual(registry.sites, [])

    def test_broken_file_is_reported(self):
        self.path.write_text("{bozuk", encoding="utf-8")
        with self.assertRaises(reg.RegistryError):
            reg.Registry(self.path)


class CatalogFlowTest(unittest.TestCase):
    """--import / --check / --plan through the command line, against a local site."""

    @classmethod
    def setUpClass(cls):
        Handler.routes = {"/filmler": listing("/filmler"), "/diziler": listing("/diziler")}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-B", "scripts/find_site.py", *args],
                              cwd=ROOT, text=True, capture_output=True, timeout=180)

    def test_import_check_plan(self):
        work = new_workdir()
        catalog = work / "sites.json"
        domains = work / "domains.txt"
        domains.write_text(f"# liste\nhttp://127.0.0.1:{self.port}\nhttp://127.0.0.1:9\n",
                           encoding="utf-8")

        result = self.run_cli("--import", str(domains), "--catalog", str(catalog),
                              "--check", "--plan", "--timeout", "5", "--delay", "0")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(catalog.read_text(encoding="utf-8"))
        by_url = {entry["url"]: entry for entry in data["sites"]}
        self.assertEqual(len(data["sites"]), 2, data)

        live = by_url[f"http://127.0.0.1:{self.port}"]
        self.assertEqual(live["status"], "planned")
        self.assertTrue(live["home_sections"])
        self.assertEqual(live["plugin"], "Site127")
        self.assertTrue(live["create"])
        self.assertIn("domains.txt:2", live["sources"])
        self.assertTrue(live["added"] and live["checked"])

        dead = by_url["http://127.0.0.1:9"]
        self.assertEqual(dead["status"], "unreachable")

    def test_prune_removes_dead_entries(self):
        work = new_workdir()
        catalog = work / "sites.json"
        catalog.write_text(json.dumps({"sites": [
            {"url": "https://olu.example", "status": "unreachable", "sources": []},
            {"url": "https://iyi.example", "status": "planned", "sources": []},
        ]}), encoding="utf-8")
        result = self.run_cli("--catalog", str(catalog), "--prune")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(catalog.read_text(encoding="utf-8"))
        self.assertEqual([entry["url"] for entry in data["sites"]], ["https://iyi.example"])


def tearDownModule() -> None:
    for work in _CREATED:
        shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(WORKDIR, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()



