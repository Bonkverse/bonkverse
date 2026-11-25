"""Settings refuse to start instead of running a production site insecurely.

ENV used to default to "local", so a deploy that lost or misspelled it ran
with DEBUG on, non-Secure cookies and the public development token key. The
image also set DJANGO_ALLOW_DUMMY_SECRET for good, so a missing SECRET_KEY fell
back to a key anyone can read.
"""

from pathlib import Path

import pytest

from core import token_crypto
from tests.test_resilience import _load_settings

ROOT = Path(__file__).resolve().parent.parent
PROD = {"ENV": "production", "BONK_TOKEN_KEYS": token_crypto.dev_key()}


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    # settings.py calls load_dotenv(); a developer's .env must not leak in.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)


class TestEnv:
    def test_a_missing_env_refuses_to_start(self, monkeypatch):
        monkeypatch.delenv("ENV", raising=False)
        with pytest.raises(RuntimeError, match="ENV must be one of"):
            _load_settings(monkeypatch)

    @pytest.mark.parametrize("value", ["prod", "Production", "production ", "staging"])
    def test_an_unknown_env_refuses_to_start(self, monkeypatch, value):
        with pytest.raises(RuntimeError, match="ENV must be one of"):
            _load_settings(monkeypatch, ENV=value)

    @pytest.mark.parametrize("value", ["local", "ci", "build"])
    def test_known_development_values_run_in_debug(self, monkeypatch, value):
        module = _load_settings(monkeypatch, ENV=value)
        assert module.DEBUG is True

    def test_production_is_not_debug(self, monkeypatch):
        module = _load_settings(monkeypatch, SECRET_KEY="x" * 50, **PROD)
        assert module.DEBUG is False


class TestSecretKey:
    def test_production_refuses_the_dummy_even_when_allowed(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError, match="SECRET_KEY is not set"):
            _load_settings(monkeypatch, DJANGO_ALLOW_DUMMY_SECRET="true", **PROD)

    @pytest.mark.parametrize(
        "key",
        ["build-time-secret-key", "dev-insecure-secret-key", "django-insecure-abc123"],
    )
    def test_production_refuses_publicly_known_keys(self, monkeypatch, key):
        with pytest.raises(RuntimeError, match="publicly known"):
            _load_settings(monkeypatch, SECRET_KEY=key, **PROD)

    def test_the_build_may_use_the_dummy(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        module = _load_settings(monkeypatch, ENV="build", DJANGO_ALLOW_DUMMY_SECRET="true")
        assert module.SECRET_KEY == "build-time-secret-key"


def test_the_image_allows_the_dummy_key_only_while_building():
    text = (ROOT / "Dockerfile").read_text()
    env_block = text.split("ENV ", 1)[1].split("\n\n", 1)[0]

    assert "DJANGO_ALLOW_DUMMY_SECRET" not in env_block
    assert "ENV=build DJANGO_ALLOW_DUMMY_SECRET=true python manage.py collectstatic" in text
