"""Tests for reading a bonk.io token's own expiry (core/bonk/tokens.py) and
the session using it (core/bonk/session.py).

RFC-0003 Part 1, item 7: bonk.io session tokens last about 24 hours, but
Bonkverse assumed 14 days, so a wear a day after login spent an
avatar_update.php call just to hear "token".
"""

import pytest

from core.bonk import BonkSession
from core.bonk.session import EXPIRY_MARGIN_SECONDS, TOKEN_TTL_SECONDS
from core.bonk.tokens import token_expiry
from tests.conftest import make_bonk_token

NOW = 1_800_000_000.0


class TestTokenExpiry:
    def test_reads_exp(self):
        assert token_expiry(make_bonk_token(exp=NOW + 86400)) == NOW + 86400

    @pytest.mark.parametrize(
        "token",
        [
            None,
            "",
            "test-bonk-token",
            "a.b",
            "a.!!!.c",
            "a.bm90IGpzb24.c",  # "not json"
            "a.WzFd.c",  # [1], not an object
            "a.eyJleHAiOiJzb29uIn0.c",  # {"exp": "soon"}
            "a.eyJleHAiOnRydWV9.c",  # {"exp": true}
        ],
    )
    def test_anything_unreadable_has_no_known_expiry(self, token):
        assert token_expiry(token) is None


class TestSession:
    def _session(self, now=NOW):
        store = {}
        return store, BonkSession(store, clock=lambda: now)

    def test_keeps_a_token_until_just_before_its_exp(self):
        store, bonk = self._session()
        bonk.store_token(make_bonk_token(exp=NOW + 86400))

        assert store["bonk_token_expires"] == NOW + 86400 - EXPIRY_MARGIN_SECONDS

    def test_a_token_without_exp_keeps_the_old_cap(self):
        store, bonk = self._session()
        bonk.store_token("test-bonk-token")

        assert store["bonk_token_expires"] == NOW + TOKEN_TTL_SECONDS

    def test_a_token_past_its_exp_is_gone_even_with_an_old_stored_expiry(self):
        """Sessions saved before this change carry a 14-day expiry."""
        token = make_bonk_token(exp=NOW + 30)  # inside the margin
        store = {"bonk_token": token, "bonk_token_expires": NOW + 13 * 86400}
        bonk = BonkSession(store, clock=lambda: NOW)

        assert bonk.token is None

    def test_a_live_token_is_returned(self):
        token = make_bonk_token(exp=NOW + 3600)
        store = {"bonk_token": token, "bonk_token_expires": NOW + 3000}
        bonk = BonkSession(store, clock=lambda: NOW)

        assert bonk.token == token
