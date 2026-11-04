#!/usr/bin/env python3
"""
Create a second (third, ...) plugin module by copying the template module.

    python3 scripts/new_plugin.py --name FilmX
    python3 scripts/new_plugin.py --name FilmX --url https://filmx.example --display-name "Film X"
    python3 scripts/new_plugin.py --name FilmX --template CineDepo --package com.example.filmx

The new module gets its own Kotlin package (every .kt file is rewritten and moved),
`version = 1` and its own icon domain, so the plugins build and update independently.
settings.gradle.kts picks the directory up automatically and plugins.json lists both.

Only standard library is required. Only use this for sites whose terms allow
automated access.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import urllib.parse
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,30}")
PACKAGE_RE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")
LANG_RE = re.compile(r"[a-z]{2,3}")
COPY_IGNORE = shutil.ignore_patterns("build", ".gradle", "*.cs3", "__pycache__", ".git")


class PluginError(Exception):
    """Invalid input or an unexpected repo layout; the message is user-facing."""


def die(msg: str) -> None:
    raise PluginError(msg)


def kotlin_escape(value: str) -> str:
    """Escape a value for a Kotlin "..." literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")


def list_plugins(root: Path) -> list[str]:
    """Top-level module directories that contain a SiteConfig.kt."""
    names = set()
    for config in root.glob("*/src/main/kotlin/**/SiteConfig.kt"):
        names.add(config.relative_to(root).parts[0])
    return sorted(names)


def find_template(root: Path, name: str | None) -> Path:
    if name:
        if not (root / name / "build.gradle.kts").is_file():
            die(f"şablon eklenti bulunamadı: {name}")
        return root / name
    modules = list_plugins(root)
    if not modules:
        die(f"{root} altında SiteConfig.kt içeren eklenti yok")
    return root / ("CineDepo" if "CineDepo" in modules else modules[0])


def _set_gradle_string(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf'^(\s*{re.escape(key)}\s*=\s*)"(?:[^"\\]|\\.)*"', re.M)
    if not pattern.search(text):
        die(f"build.gradle.kts içinde '{key} = \"...\"' satırı yok")
    return pattern.sub(lambda m: f'{m.group(1)}"{kotlin_escape(value)}"', text, count=1)


def _set_version_one(text: str) -> str:
    new, count = re.subn(r"^version\s*=\s*\d+\s*$", "version = 1", text, count=1, flags=re.M)
    if not count:
        die("build.gradle.kts içinde 'version = N' satırı yok")
    return new


def _set_const(text: str, name: str, value: str) -> str:
    pattern = re.compile(rf'(const val {re.escape(name)} = )"(?:[^"\\]|\\.)*"')
    if not pattern.search(text):
        die(f"SiteConfig.kt içinde '{name}' yok")
    return pattern.sub(lambda m: f'{m.group(1)}"{kotlin_escape(value)}"', text, count=1)


def _kotlin_package(path: Path) -> str | None:
    match = re.search(r"^package\s+([\w.]+)", path.read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else None


def _prune_empty_dirs(start: Path, stop: Path) -> None:
    """Removes the now empty package directories, best effort (Windows may keep a handle)."""
    current = start
    while current != stop and stop in current.parents:
        try:
            if not current.is_dir() or any(current.iterdir()):
                return
            current.rmdir()
        except OSError:
            return  # a leftover empty directory is harmless
        current = current.parent


def _relocate_sources(module: Path, old_pkg: str, new_pkg: str) -> int:
    """Moves every .kt file from the old package directory to the new one, rewriting the package."""
    if old_pkg == new_pkg:
        return 0
    moved = 0
    for kotlin_root in (module / "src/main/kotlin", module / "src/test/kotlin"):
        old_dir = kotlin_root / old_pkg.replace(".", "/")
        if not old_dir.is_dir():
            continue
        new_dir = kotlin_root / new_pkg.replace(".", "/")
        for path in sorted(old_dir.rglob("*.kt")):
            text = path.read_text(encoding="utf-8")
            text = text.replace(f"package {old_pkg}", f"package {new_pkg}")
            text = text.replace(f"import {old_pkg}.", f"import {new_pkg}.")
            destination = new_dir / path.relative_to(old_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
            path.unlink()
            moved += 1
        _prune_empty_dirs(old_dir, kotlin_root)
    return moved


def create_plugin(name: str, *, template: str | None = None, package: str | None = None,
                  url: str | None = None, lang: str | None = None, display_name: str | None = None,
                  description: str | None = None, root: Path | None = None,
                  log=print) -> dict:
    """Copies the template module to a new directory named [name]. Returns a summary dict."""
    root = root or ROOT
    if not NAME_RE.fullmatch(name):
        die(f"eklenti adı harf/rakam olmalı, harfle başlamalı: {name!r}")
    new_pkg = package or f"com.example.{name.lower()}"
    if not PACKAGE_RE.fullmatch(new_pkg):
        die(f"geçersiz paket adı: {new_pkg!r} (örn. com.ornek.filmx)")
    if lang and not LANG_RE.fullmatch(lang):
        die(f"dil kodu 2-3 küçük harf olmalı: {lang!r}")
    target = root / name
    if target.exists():
        die(f"{name} zaten var: {target}")

    source = find_template(root, template)
    old_pkg = next((pkg for pkg in (_kotlin_package(p) for p in sorted(source.glob("src/main/kotlin/**/*.kt")))
                    if pkg), None)
    if not old_pkg:
        die(f"{source.name} içinde Kotlin paketi bulunamadı")

    log(f"{source.name} -> {name} (paket: {old_pkg} -> {new_pkg})")
    try:
        shutil.copytree(source, target, ignore=COPY_IGNORE)
        moved = _relocate_sources(target, old_pkg, new_pkg)

        gradle_path = target / "build.gradle.kts"
        gradle = _set_version_one(gradle_path.read_text(encoding="utf-8"))
        if description:
            gradle = _set_gradle_string(gradle, "description", description)
        if url:
            gradle = re.sub(r"(favicons\?domain=)[^&\"]+",
                            lambda m: m.group(1) + urllib.parse.urlsplit(url).netloc, gradle)
        if lang:
            gradle = re.sub(r'(language\s*=\s*)"[^"]*"', rf'\1"{lang}"', gradle)
        gradle_path.write_text(gradle, encoding="utf-8")

        config_path = next(target.glob("src/main/kotlin/**/SiteConfig.kt"))
        config = config_path.read_text(encoding="utf-8")
        config = _set_const(config, "NAME", display_name or name)
        if url:
            config = _set_const(config, "MAIN_URL", url.rstrip("/"))
        if lang:
            config = _set_const(config, "LANG", lang)
        config_path.write_text(config, encoding="utf-8")
    except Exception:
        shutil.rmtree(target, ignore_errors=True)  # do not leave a half-created module behind
        raise

    log(f"  {moved} Kotlin dosyası taşındı; sürüm 1, paket {new_pkg}")
    log(f"  Sonraki adım: python3 scripts/discover_site.py <site> --plugin {name} --create --apply")
    return {"path": target, "package": new_pkg, "template": source.name, "files": moved}


def main() -> None:
    ap = argparse.ArgumentParser(description="Şablon eklentiden yeni bir eklenti modülü oluştur.")
    ap.add_argument("--name", required=True, help="yeni modül/dizin adı (örn. FilmX)")
    ap.add_argument("--template", help="kopyalanacak eklenti (varsayılan: CineDepo)")
    ap.add_argument("--package", help="Kotlin paketi (varsayılan: com.example.<ad>)")
    ap.add_argument("--url", help="sitenin ana adresi (MAIN_URL ve iconUrl)")
    ap.add_argument("--display-name", dest="display_name", help="uygulamada görünecek ad")
    ap.add_argument("--lang", help="içerik dili (ISO 639-1)")
    ap.add_argument("--description", help="eklenti açıklaması")
    args = ap.parse_args()

    try:
        create_plugin(args.name, template=args.template, package=args.package, url=args.url,
                      lang=args.lang, display_name=args.display_name, description=args.description)
    except PluginError as e:
        print(f"HATA: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
