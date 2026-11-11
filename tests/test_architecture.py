"""Import rules from RFC-0001, checked by reading the source (no imports run).

Only `integrations/` makes outside HTTP calls: one client per external
system owns its URLs, timeouts, parsing and token redaction. Phase 2.3
moved the last callers there, so there are no exceptions in the site code.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"tests", "migrations", "staticfiles", "media", "backups", "node_modules", ".git"}

# Libraries that make outside HTTP calls. Only integrations/ may import them.
HTTP_CLIENTS = {"requests", "httpx", "aiohttp", "urllib.request", "http.client", "urllib3"}

# Standalone tools run by hand, never by the site. Add here only with a reason.
HTTP_ALLOWED_OUTSIDE_INTEGRATIONS = {
    "scripts/load_test_search.py",  # dev load test; refuses to target production
    "scripts/sync_ui.py",  # dev tool: downloads a Bonkverse/ui release into static/ui
}


def _python_files():
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO)
        if SKIP_DIRS.isdisjoint(rel.parts):
            yield rel


def _http_imports(path: Path) -> set[str]:
    """The HTTP client libraries a file imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            # `from urllib import request` imports urllib.request.
            names = [module] + [f"{module}.{alias.name}" for alias in node.names]
        else:
            continue
        for name in names:
            for client in HTTP_CLIENTS:
                if name == client or name.startswith(f"{client}."):
                    found.add(client)
    return found


def test_only_integrations_make_http_calls():
    offenders = {
        rel.as_posix(): sorted(_http_imports(REPO / rel))
        for rel in _python_files()
        if rel.parts[0] != "integrations"
        and rel.as_posix() not in HTTP_ALLOWED_OUTSIDE_INTEGRATIONS
        and _http_imports(REPO / rel)
    }

    assert offenders == {}, "move these outside calls into integrations/"


def test_allowed_list_has_no_stale_entries():
    for rel in HTTP_ALLOWED_OUTSIDE_INTEGRATIONS:
        path = REPO / rel
        assert path.exists() and _http_imports(path), f"remove {rel} from the allowed list"


def test_detects_every_import_form(tmp_path):
    for source in (
        "import requests",
        "import requests.adapters",
        "from requests import post",
        "import urllib.request",
        "from urllib import request",
        "from urllib.request import urlopen",
        "import httpx",
    ):
        path = tmp_path / "m.py"
        path.write_text(source)
        assert _http_imports(path), source
    (tmp_path / "ok.py").write_text("from urllib.parse import urlparse\nimport http\n")
    assert not _http_imports(tmp_path / "ok.py")


def test_login_and_wear_go_through_the_bonk_client():
    for rel in (
        "accounts/views.py",
        "accounts/login_attempts.py",
        "accounts/sign_in.py",
        "skins/wear_skin.py",
        "players/friends_sync.py",
        "players/flash_friends_sync.py",
    ):
        assert not _http_imports(REPO / rel), rel
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
