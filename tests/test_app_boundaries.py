"""App boundaries from RFC-0001, checked by reading the source (no imports run).

Each Django app owns one domain (skins, players, accounts, ...). Apps talk to
each other only through the other app's public modules:

- `services`: business rules and writes,
- `selectors`: read queries shaped for pages,
- `models`: model classes, for foreign keys and reading their fields.

Never another app's views, URLs, templates, tasks or helper modules: those
are its internals and change without notice. Writes to another app's data go
through its `services`, which this test can't check; reviews do.

`core/` and `integrations/` are shared by every app, so they import no app.

Exceptions are listed in `ALLOWED` with a reason. The list only shrinks:
`test_allowed_list_has_no_stale_entries` fails once an exception is gone,
so its entry gets removed. A new app is checked automatically (any top-level
folder with an `apps.py`).
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHARED_PACKAGES = {"core", "integrations"}
PUBLIC_MODULES = {"services", "selectors", "models"}

# (file, imported module) pairs allowed for now, each with the step that
# removes it. Remove an entry when its import is gone.
ALLOWED: dict[tuple[str, str], str] = {
    ("public_api/selectors.py", "players.calculator"): "players exposes account_age via selectors",
    ("public_api/selectors.py", "players.charts"): "players exposes profile_path via selectors",
    ("players/friends_sync.py", "skins.events"): "log_event's home (UserEvent) is decided in 5.6",
    ("accounts/sign_in.py", "skins.events"): "log_event's home (UserEvent) is decided in 5.6",
}


def _apps() -> set[str]:
    """Every local Django app: a top-level folder with an apps.py."""
    return {path.parent.name for path in REPO.glob("*/apps.py")}


def _files_owned_by(owner: str):
    for path in (REPO / owner).rglob("*.py"):
        rel = path.relative_to(REPO)
        if "migrations" not in rel.parts:
            yield rel


def _imported_modules(path: Path) -> set[str]:
    """Absolute module names a file imports, including inside functions."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
            # `from players import selectors` imports players.selectors.
            if "." not in node.module:
                found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _boundary_problems(apps: set[str]) -> dict[tuple[str, str], str]:
    """Every (file, module) import that crosses a boundary it shouldn't."""
    problems = {}
    for owner in sorted(apps | SHARED_PACKAGES):
        for rel in _files_owned_by(owner):
            for module in sorted(_imported_modules(REPO / rel)):
                parts = module.split(".")
                target = parts[0]
                if target not in apps or target == owner:
                    continue
                if owner in SHARED_PACKAGES:
                    problems[(rel.as_posix(), module)] = "shared code imports no app"
                elif len(parts) == 1:
                    # `from skins import x` is checked as skins.x above.
                    continue
                elif parts[1] not in PUBLIC_MODULES:
                    problems[(rel.as_posix(), module)] = f"{target} internals"
    return problems


def test_apps_use_each_other_only_through_public_modules():
    problems = {
        key: reason for key, reason in _boundary_problems(_apps()).items() if key not in ALLOWED
    }

    assert problems == {}, (
        "import another app's services/selectors/models instead (or add a "
        "selector there); see docs/apps/README.md"
    )


def test_allowed_list_has_no_stale_entries():
    current = _boundary_problems(_apps())

    stale = sorted(key for key in ALLOWED if key not in current)

    assert stale == [], "these exceptions are gone: remove them from ALLOWED"


def test_finds_every_local_app():
    assert {"skins", "players", "public_api", "accounts"} <= _apps()
    assert not SHARED_PACKAGES & _apps()


def test_detects_each_kind_of_crossing(tmp_path, monkeypatch):
    monkeypatch.setattr(f"{__name__}.REPO", tmp_path)
    for name in ("alpha", "beta"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "apps.py").write_text("")
    (tmp_path / "core").mkdir()
    (tmp_path / "integrations").mkdir()
    (tmp_path / "alpha" / "ok.py").write_text(
        "from beta.services import do\n"
        "from beta.selectors import read\n"
        "from beta.models import Thing\n"
        "from beta import services\n"
        "import beta.models\n"
    )
    (tmp_path / "alpha" / "bad.py").write_text(
        "from beta.views import page\n"
        "def f():\n"
        "    from beta import tasks\n"
        "    import beta.helpers\n"
    )
    (tmp_path / "core" / "shared.py").write_text("from alpha.models import Thing\n")
    (tmp_path / "alpha" / "migrations").mkdir()
    (tmp_path / "alpha" / "migrations" / "0001.py").write_text("from beta.views import x\n")

    problems = _boundary_problems({"alpha", "beta"})

    assert set(problems) == {
        ("alpha/bad.py", "beta.views"),
        ("alpha/bad.py", "beta.tasks"),
        ("alpha/bad.py", "beta.helpers"),
        ("core/shared.py", "alpha.models"),
    }
