#!/usr/bin/env python3
"""Copy a release of Bonkverse/ui into skins/static/ui/.

    python scripts/sync_ui.py v0.1.0

Downloads the tagged release from GitHub, copies the files the site uses
(the CSS, theme.js, ui.js, nav.json, fonts and the planet logo) into
skins/static/ui/, and writes MANIFEST.json with the version and a SHA-256 of
every file. tests/test_ui_package.py fails if a file there no longer matches
the manifest, so nobody edits them by hand: change Bonkverse/ui, release, and
run this again. Upgrading is its own PR with before/after screenshots
(RFC-0002).

Needs only the standard library. `--from <dir>` copies from a local
checkout instead of downloading (for trying out an unreleased change).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = "Bonkverse/ui"
DEST = Path(__file__).resolve().parent.parent / "skins" / "static" / "ui"
# What the site needs from the package; the gallery, scripts and samples stay behind.
FILES = [
    "tokens.css",
    "base.css",
    "components.css",
    "theme.js",
    "ui.js",
    "nav.json",
    "img/planet.png",
]
DIRS = ["fonts"]


def _wanted(rel: str) -> bool:
    return rel in FILES or any(rel.startswith(d + "/") for d in DIRS)


def _from_release(tag: str) -> dict[str, bytes]:
    url = f"https://codeload.github.com/{REPO}/tar.gz/refs/tags/{tag}"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            rel = member.name.split("/", 1)[1]  # drop the "ui-0.1.0/" folder
            if _wanted(rel):
                files[rel] = tar.extractfile(member).read()
    return files


def _from_dir(src: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(src)): p.read_bytes()
        for p in sorted(src.rglob("*"))
        if p.is_file() and _wanted(str(p.relative_to(src)))
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tag", help="release tag, like v0.1.0")
    parser.add_argument("--from", dest="src", type=Path, help="copy from a local checkout instead")
    args = parser.parse_args()

    files = _from_dir(args.src) if args.src else _from_release(args.tag)
    missing = [f for f in FILES if f not in files]
    if missing:
        print(f"{args.tag} is missing {', '.join(missing)}", file=sys.stderr)
        return 1
    version = json.loads(files["nav.json"])["version"]
    if f"v{version}" != args.tag:
        print(f"{args.tag} contains version {version}; check the tag", file=sys.stderr)
        return 1

    if DEST.exists():
        shutil.rmtree(DEST)
    for rel, data in files.items():
        path = DEST / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    manifest = {
        "package": REPO,
        "version": version,
        "note": "Copied by scripts/sync_ui.py. Don't edit these files; change Bonkverse/ui and sync a new release.",
        "files": {rel: hashlib.sha256(data).hexdigest() for rel, data in sorted(files.items())},
    }
    (DEST / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"Copied {len(files)} files from {REPO} {args.tag} into {DEST.relative_to(DEST.parents[2])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
