"""skins/static/ui/ is a copy of a Bonkverse/ui release (scripts/sync_ui.py).
These files are never edited here: change Bonkverse/ui, release, sync."""

import hashlib
import json
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "skins" / "static" / "ui"


def _manifest():
    return json.loads((UI / "MANIFEST.json").read_text())


def test_files_match_the_release():
    manifest = _manifest()
    changed = [
        rel
        for rel, digest in manifest["files"].items()
        if hashlib.sha256((UI / rel).read_bytes()).hexdigest() != digest
    ]
    assert not changed, (
        f"{', '.join(changed)} differ from Bonkverse/ui v{manifest['version']}. "
        "Make the change in Bonkverse/ui and run scripts/sync_ui.py instead."
    )


def test_no_extra_files():
    listed = set(_manifest()["files"]) | {"MANIFEST.json"}
    present = {str(p.relative_to(UI)) for p in UI.rglob("*") if p.is_file()}
    assert present == listed


def test_nav_version_matches_manifest():
    assert json.loads((UI / "nav.json").read_text())["version"] == _manifest()["version"]
