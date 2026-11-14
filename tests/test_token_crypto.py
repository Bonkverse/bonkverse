"""bonk.io tokens are stored encrypted (core/token_crypto.py, ADR 0016)."""

import base64
from io import StringIO

import pytest
from cryptography.fernet import Fernet
from django.contrib.sessions.backends.db import SessionStore
from django.core import signing
from django.core.management import call_command

from accounts.models import BonkAccountLink
from core import token_crypto
from core.bonk import BonkSession
from players.models import BonkPlayer
from tests.factories import UserFactory


def _made_up_token() -> str:
    """Shaped like a bonk.io token (a JWT: three base64url parts), made up.

    Built here rather than written out: secret scanners flag anything that
    looks like a JWT in the source.
    """

    def part(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return ".".join(
        (part(b'{"alg":"none"}'), part(b'{"uid":123,"un":"alpha"}'), part(b"not-a-signature"))
    )


TOKEN = _made_up_token()


@pytest.fixture
def keys(settings):
    """Two fresh keys, newest first, in use for the test."""
    new, old = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings.BONK_TOKEN_KEYS = [new, old]
    return new, old


def _encrypt_with(key: str, token: str) -> str:
    return Fernet(key).encrypt(token.encode()).decode()


class TestEncryption:
    def test_round_trip_and_nothing_readable_stored(self, keys):
        stored = token_crypto.encrypt(TOKEN)

        assert TOKEN not in stored
        assert "eyJ" not in stored
        assert token_crypto.decrypt(stored) == TOKEN

    def test_a_key_not_listed_opens_nothing(self, keys):
        stored = _encrypt_with(Fernet.generate_key().decode(), TOKEN)

        assert token_crypto.decrypt(stored) is None

    def test_rotation_reads_older_keys_and_writes_the_newest(self, keys):
        new, old = keys
        stored_with_old = _encrypt_with(old, TOKEN)

        assert token_crypto.decrypt(stored_with_old) == TOKEN
        assert not token_crypto.is_current(stored_with_old)
        assert token_crypto.is_current(token_crypto.encrypt(TOKEN))

    @pytest.mark.parametrize("value", [None, "", "not encrypted", TOKEN, "gAAAAA!!"])
    def test_anything_else_decrypts_to_none(self, keys, value):
        assert token_crypto.decrypt(value) is None
        assert not token_crypto.is_current(value)


class TestKeys:
    def test_production_needs_keys(self):
        with pytest.raises(token_crypto.TokenKeyError, match="not set"):
            token_crypto.parse_keys("", required=True)

    def test_a_bad_key_is_named_by_position_never_by_value(self):
        good = Fernet.generate_key().decode()
        with pytest.raises(token_crypto.TokenKeyError) as error:
            token_crypto.parse_keys(f"{good}, not-a-real-key-123", required=True)

        assert "key 2" in str(error.value)
        assert "not-a-real-key-123" not in str(error.value)
        assert good not in str(error.value)

    def test_keys_keep_their_order_newest_first(self):
        a, b = Fernet.generate_key().decode(), Fernet.generate_key().decode()

        assert token_crypto.parse_keys(f" {a} ,{b},", required=True) == [a, b]

    def test_outside_production_a_development_key_is_used(self):
        assert token_crypto.parse_keys(None, required=False) == [token_crypto.dev_key()]

    def test_settings_refuse_to_start_in_production_without_keys(self, monkeypatch):
        from tests.test_resilience import _load_settings

        monkeypatch.delenv("BONK_TOKEN_KEYS", raising=False)
        monkeypatch.delenv("DJANGO_ALLOW_DUMMY_SECRET", raising=False)
        with pytest.raises(token_crypto.TokenKeyError):
            _load_settings(monkeypatch, ENV="production")

    def test_the_dummy_secret_flag_does_not_excuse_production(self, monkeypatch):
        """The image sets DJANGO_ALLOW_DUMMY_SECRET for good, so production must
        still refuse to fall back to the public development key."""
        from tests.test_resilience import _load_settings

        monkeypatch.delenv("BONK_TOKEN_KEYS", raising=False)
        with pytest.raises(token_crypto.TokenKeyError):
            _load_settings(monkeypatch, ENV="production", DJANGO_ALLOW_DUMMY_SECRET="true")

    def test_the_image_build_needs_no_keys(self, monkeypatch):
        """collectstatic runs in the Docker build without ENV=production."""
        from tests.test_resilience import _load_settings

        monkeypatch.delenv("BONK_TOKEN_KEYS", raising=False)
        monkeypatch.delenv("ENV", raising=False)
        module = _load_settings(monkeypatch, DJANGO_ALLOW_DUMMY_SECRET="true")

        assert module.BONK_TOKEN_KEYS == [token_crypto.dev_key()]


class TestSessionToken:
    def _session(self, store):
        return BonkSession(
            store, encrypt=token_crypto.encrypt, decrypt=token_crypto.decrypt, clock=lambda: 1000
        )

    def test_stored_encrypted_and_read_back(self, keys):
        store = {}
        self._session(store).store_token(TOKEN)

        assert TOKEN not in str(store)
        assert self._session(store).token == TOKEN

    def test_unreadable_values_mean_no_token(self, keys):
        """Including a plain token: every session was encrypted on 2026-11-14,
        so a plain value can only have been written by something else."""
        other = _encrypt_with(Fernet.generate_key().decode(), TOKEN)
        for stored in (other, TOKEN, "not-a-token"):
            store = {"bonk_token": stored, "bonk_token_expires": 5000}
            assert self._session(store).token is None

    def test_requests_use_the_encrypting_session(self, keys, rf):
        request = rf.get("/")
        request.session = {}

        token_crypto.bonk_session(request).store_token(TOKEN)

        assert request.session["bonk_token"] != TOKEN
        assert token_crypto.bonk_session(request).token == TOKEN


def _link(token_value):
    player = BonkPlayer.objects.create(bonk_id=7, username="alpha")
    return BonkAccountLink.objects.create(
        user=UserFactory(), bonk_player=player, token_encrypted=token_value
    )


def _signed_the_old_way(token: str) -> str:
    """How links stored tokens before ADR 0016: signed, not encrypted."""
    return signing.dumps({"t": token}, salt="bonk_token")


@pytest.mark.django_db
class TestAccountLinkToken:
    def test_stored_encrypted(self, keys):
        link = _link(BonkAccountLink.encrypt_token(TOKEN))

        assert TOKEN not in link.token_encrypted
        assert BonkAccountLink.objects.get(pk=link.pk).bonk_token() == TOKEN

    def test_values_signed_the_old_way_are_not_read(self, keys):
        assert _link(_signed_the_old_way(TOKEN)).bonk_token() is None

    def test_a_key_not_listed_means_no_token(self, keys):
        link = _link(_encrypt_with(Fernet.generate_key().decode(), TOKEN))

        assert link.bonk_token() is None


@pytest.mark.django_db
class TestReencryptCommand:
    def _run(self, *args) -> str:
        out = StringIO()
        call_command("reencrypt_bonk_tokens", *args, stdout=out)
        return out.getvalue()

    def _session_with(self, value) -> str:
        store = SessionStore()
        store["bonk_token"] = value
        store["bonk_token_expires"] = 9e12
        store.create()
        return store.session_key

    def _session_token(self, key):
        return SessionStore(session_key=key).load().get("bonk_token")

    def test_dry_run_counts_and_writes_nothing(self, keys):
        new, old = keys
        link = _link(_encrypt_with(old, TOKEN))
        before = link.token_encrypted
        key = self._session_with(_encrypt_with(old, TOKEN))
        session_before = self._session_token(key)

        output = self._run()

        assert "dry run" in output
        assert "1 re-encrypted" in output
        link.refresh_from_db()
        assert link.token_encrypted == before
        assert self._session_token(key) == session_before

    def test_run_brings_every_copy_to_the_newest_key(self, keys):
        new, old = keys
        rotated = _link(_encrypt_with(old, TOKEN))
        rotated_session = self._session_with(_encrypt_with(old, TOKEN))

        output = self._run("--run")

        rotated.refresh_from_db()
        assert token_crypto.is_current(rotated.token_encrypted)
        assert rotated.bonk_token() == TOKEN
        stored = self._session_token(rotated_session)
        assert token_crypto.is_current(stored)
        assert token_crypto.decrypt(stored) == TOKEN
        assert TOKEN not in output

    def test_run_removes_tokens_no_key_opens(self, keys):
        """A lost key, or a value in the old signed or plain form."""
        lost_key = Fernet.generate_key().decode()
        link = _link(_encrypt_with(lost_key, TOKEN))
        signed = BonkAccountLink.objects.create(
            user=UserFactory(),
            bonk_player=BonkPlayer.objects.create(bonk_id=8, username="beta"),
            token_encrypted=_signed_the_old_way(TOKEN),
        )
        lost = self._session_with(_encrypt_with(lost_key, TOKEN))
        plain = self._session_with(TOKEN)

        output = self._run("--run")

        for row in (link, signed):
            row.refresh_from_db()
            assert row.token_encrypted is None
        assert self._session_token(lost) is None
        assert self._session_token(plain) is None
        assert "2 unreadable" in output

    def test_a_second_run_finds_everything_current(self, keys):
        new, old = keys
        _link(_encrypt_with(old, TOKEN))
        self._run("--run")

        assert "1 already current, 0 re-encrypted" in self._run()
