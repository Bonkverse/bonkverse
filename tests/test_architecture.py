"""Import rules from RFC-0001, checked by reading the source (no imports run).

Only `integrations/` may import `requests`: one client per external system
owns its URLs, timeouts, parsing and token redaction.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"tests", "migrations", "staticfiles", "media", "backups", "node_modules", ".git"}

# Modules allowed to import requests for now, each with the phase that moves
# its calls into integrations/. Shrink only: the test fails if a listed file
# stops importing requests (delete it here) or an unlisted one starts.
REQUESTS_ALLOWED = {
    "skins/rerender.py",  # 2.3: integrations/editor_render.py (exists) + cloudflare.py
    "skins/bonkbot.py",  # 2.3: integrations/bonkbot.py
    "skins/discord_invite.py",  # 2.3: integrations/discord_api.py
    "skins/upload.py",  # 2.3: integrations/bl_skin_fetcher.py (exists)
    "skins/utils/tools/map_decode.py",  # 2.3: integrations/map_decoder.py
}


def _python_files():
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO)
        if SKIP_DIRS.isdisjoint(rel.parts):
            yield rel


def _imports_requests(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == "requests" for a in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "requests":
            return True
    return False


def test_only_integrations_import_requests():
    importers = {
        rel.as_posix()
        for rel in _python_files()
        if rel.parts[0] != "integrations" and _imports_requests(REPO / rel)
    }

    assert importers - REQUESTS_ALLOWED == set(), "move these HTTP calls into integrations/"
    assert REQUESTS_ALLOWED - importers == set(), "no longer import requests: remove from list"


def test_login_and_wear_go_through_the_bonk_client():
    for rel in ("skins/login.py", "skins/wear_skin.py", "skins/friends_sync.py"):
        assert not _imports_requests(REPO / rel), rel
        assert "bonk2.io" not in (REPO / rel).read_text(), rel


def test_integrations_import_no_models_or_views():
    """Integrations own HTTP; they never reach into the database or views."""
    for rel in (REPO / "integrations").rglob("*.py"):
        tree = ast.parse(rel.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith("skins"), (rel.name, module)
                assert not module.startswith("django.db"), (rel.name, module)
