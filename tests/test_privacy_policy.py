"""The privacy policy describes what Bonkverse does today (design review
2026-11-09: it still listed the removed win/loss leaderboards, and said
nothing about the public API)."""

import pytest

pytestmark = pytest.mark.django_db


def test_privacy_policy_no_longer_mentions_win_loss_leaderboards(client):
    html = client.get("/privacy/").content.decode()

    assert "win/loss" not in html


def test_privacy_policy_explains_the_public_api_and_api_keys(client):
    html = client.get("/privacy/").content.decode()

    assert "The public API" in html
    assert "API Keys" in html
    assert 'href="/developers/terms/"' in html
