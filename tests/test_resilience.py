"""The site keeps serving when a dependency misbehaves, and runs with real concurrency.

Covers: Redis being unreachable (cache + rate limits fail open), a malformed
REDIS_URL being refused at startup, production server settings (gunicorn.conf.py),
Railway building from the Dockerfile, and secrets never being printed at startup.
"""

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from core.config import check_redis_url

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

    def test_dockerfile_uses_the_config(self):
        text = (ROOT / "Dockerfile").read_text()

        assert "gunicorn -c gunicorn.conf.py" in text
        assert "--workers" not in text and " -b " not in text


class TestRailwayBuild:
    """Railway must build from the Dockerfile: it is the only build that runs
    collectstatic and migrate. The builder used to be a dashboard setting only."""

    def test_railway_json_pins_the_dockerfile_and_a_healthcheck(self):
        config = json.loads((ROOT / "railway.json").read_text())

        assert config["build"]["builder"] == "DOCKERFILE"
        assert config["deploy"]["healthcheckPath"] == "/"

    def test_dockerfile_collects_static_and_migrates(self):
        text = (ROOT / "Dockerfile").read_text()

        assert "collectstatic" in text
        assert "manage.py migrate" in text

    def test_no_procfile_to_compete_with_the_dockerfile(self):
        assert not (ROOT / "Procfile").exists()

    def test_healthcheck_host_is_allowed_in_production(self, monkeypatch):
        module = _load_settings(monkeypatch, ENV="production")

        assert "healthcheck.railway.app" in module.ALLOWED_HOSTS


def _load_settings(monkeypatch, **env):
    """Execute settings.py afresh with the given environment; returns the module."""
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location(
        "settings_probe", ROOT / "bonk_skin_search" / "settings.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_settings_never_print_the_redis_url(monkeypatch):
    """Regression: settings.py printed REDIS_URL, password included, on every start."""
    out = io.StringIO()

    with redirect_stdout(out):
        _load_settings(monkeypatch, REDIS_URL="redis://default:hunter2-secret@redis.internal:6379")

    assert "hunter2-secret" not in out.getvalue()
    assert out.getvalue() == ""


class TestRedisUrlCheck:
    """Regression (2026-11-03): a Redis password with a URL-special character made
    every request fail with "Port could not be cast to integer". Settings must
    refuse such a URL at startup, without echoing the password."""

    @pytest.mark.parametrize(
        "url",
        [
            "redis://default:abc123@redis.railway.internal:6379",
            "redis://default:abc123@redis.railway.internal:6379/0",
            "rediss://default:abc123@redis.example.com:6380",
            "redis://localhost:6379",
            "redis://redis",
            "redis://default:a%2Fb%23c@redis.railway.internal:6379",  # encoded / and #
        ],
    )
    def test_accepts_usable_urls(self, url):
        check_redis_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "redis://default:Secret/xyz@redis.railway.internal:6379",
            "redis://default:Secret#xyz@redis.railway.internal:6379",
            "redis://default:Secret?xyz@redis.railway.internal:6379",
            "redis://:6379",
            "http://redis.railway.internal:6379",
            "redis.railway.internal:6379",
        ],
    )
    def test_rejects_unusable_urls_without_revealing_them(self, url):
        with pytest.raises(ImproperlyConfigured) as error:
            check_redis_url(url)

        assert "Secret" not in str(error.value)

    def test_settings_refuse_to_start_with_a_bad_url(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured):
            _load_settings(monkeypatch, REDIS_URL="redis://default:Secret/xyz@redis:6379")
