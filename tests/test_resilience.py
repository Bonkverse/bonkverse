"""The site keeps serving when a dependency misbehaves, and runs with real concurrency.

Covers: Redis being unreachable (cache + rate limits fail open), production server
settings (gunicorn.conf.py), and secrets never being printed at startup.
"""

import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.django_db


@pytest.fixture
def redis_down(settings):
    """Point the cache at a port where nothing listens, configured like production."""
    settings.CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": "redis://127.0.0.1:1/0",
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "SOCKET_CONNECT_TIMEOUT": 1,
                "SOCKET_TIMEOUT": 1,
                "IGNORE_EXCEPTIONS": True,
            },
        }
    }
    settings.RATELIMIT_FAIL_OPEN = True


@pytest.mark.parametrize("url", ["/", "/search/?q=dog", "/categories/", "/api/players/search/?q=a"])
def test_pages_still_load_when_redis_is_down(client, skin, redis_down, url):
    """Regression: with Redis unreachable every rate-limited page returned 500."""
    response = client.get(url)

    assert response.status_code == 200


def test_rate_limits_let_requests_through_when_redis_is_down(client, settings, redis_down):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "browse": "1/m"}

    codes = {client.get("/categories/").status_code for _ in range(3)}

    assert codes == {200}


def _load_gunicorn_config(monkeypatch, **env):
    for name in ("WEB_CONCURRENCY", "GUNICORN_THREADS", "GUNICORN_TIMEOUT", "PORT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location("gunicorn_conf", ROOT / "gunicorn.conf.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGunicornConfig:
    def test_defaults_serve_many_requests_at_once(self, monkeypatch):
        """Regression: production ran one sync worker, so one slow request blocked
        every other visitor."""
        conf = _load_gunicorn_config(monkeypatch)

        assert conf.worker_class == "gthread"
        assert conf.workers * conf.threads >= 8
        assert conf.bind == "0.0.0.0:8080"

    def test_tunable_from_environment(self, monkeypatch):
        conf = _load_gunicorn_config(
            monkeypatch, WEB_CONCURRENCY="2", GUNICORN_THREADS="8", PORT="9000"
        )

        assert (conf.workers, conf.threads, conf.bind) == (2, 8, "0.0.0.0:9000")

    def test_bad_values_fall_back_to_defaults(self, monkeypatch):
        conf = _load_gunicorn_config(monkeypatch, WEB_CONCURRENCY="lots")

        assert conf.workers == 4

    def test_dockerfile_and_procfile_use_the_config(self):
        for name in ("Dockerfile", "Procfile"):
            text = (ROOT / name).read_text()
            assert "gunicorn -c gunicorn.conf.py" in text, name
            assert "--workers" not in text and " -b " not in text, name


def test_settings_never_print_the_redis_url(monkeypatch):
    """Regression: settings.py printed REDIS_URL, password included, on every start."""
    monkeypatch.setenv("REDIS_URL", "redis://default:hunter2-secret@redis.internal:6379")
    spec = importlib.util.spec_from_file_location(
        "settings_probe", ROOT / "bonk_skin_search" / "settings.py"
    )
    module = importlib.util.module_from_spec(spec)
    out = io.StringIO()

    with redirect_stdout(out):
        spec.loader.exec_module(module)

    assert "hunter2-secret" not in out.getvalue()
    assert out.getvalue() == ""
