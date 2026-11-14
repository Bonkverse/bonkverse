"""The public API (/api/v1/): keys, limits, the reply contract, privacy.

The replay site is mocked with `responses`; its lookup rows look like the
ones ReplayRenderer's /api/players/lookup returns.
"""

import json
from datetime import UTC, datetime
from io import StringIO
from urllib.parse import quote

import pytest
from django.core.management import call_command
from responses import matchers

from players.models import ProfileVisibility
from public_api.keys import create_key, find_active_key, hash_key
from public_api.models import ApiKey
from players.models import BonkPlayer, WornSkinSource
from players.services import record_worn_skin
from skins.services import code_digest
from tests.factories import SKIN_CODE, UserFactory
from tests.test_players import profile_json

pytestmark = pytest.mark.django_db

REPLAYS = "http://replays.test"
LOOKUP = f"{REPLAYS}/api/players/lookup"


@pytest.fixture(autouse=True)
def _replays_url(settings):
    settings.BONKVERSE_REPLAYS_URL = REPLAYS


@pytest.fixture
def raw_key(db):
    _key, raw = create_key(name="Test site")
    return raw


@pytest.fixture
def api(client, raw_key):
    """A client that sends a valid key on every request."""

    class Api:
        def get(self, path, **kw):
            return client.get(path, HTTP_AUTHORIZATION=f"Bearer {raw_key}", **kw)

        def post(self, path, body, **kw):
            return client.post(
                path,
                data=json.dumps(body),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {raw_key}",
                **kw,
            )

    return Api()


def lookup_row(username, level=87, **extra):
    return {
        "username": username,
        "games": 120,
        "level": level,
        "peak_level": level,
        "last": {"cycle": 6, "id": "344124"},
        "seen_at": "2026-11-08T03:00:00.000Z",
        "seen_day": "2026-11-08",
        "seen_estimated": False,
        **extra,
    }


def mock_lookup(mocked_http, rows, *, status=200):
    mocked_http.get(LOOKUP, json={"results": rows}, status=status)


# ── Keys ─────────────────────────────────────────────────────────────────────


def test_only_the_hash_is_stored(raw_key):
    stored = ApiKey.objects.get()
    assert raw_key.startswith(f"bvk_{stored.prefix}_")
    assert stored.key_hash == hash_key(raw_key)
    assert raw_key not in stored.key_hash


def test_find_active_key_rejects_wrong_secret_with_right_prefix(raw_key):
    tampered = raw_key[:-1] + ("A" if raw_key[-1] != "A" else "B")
    assert find_active_key(raw_key) is not None
    assert find_active_key(tampered) is None
    assert find_active_key("bvk_nope") is None


def test_create_and_revoke_commands():
    out = StringIO()
    call_command("create_api_key", name="Luna", contact="luna0051", tier="partner", stdout=out)
    raw = out.getvalue().strip().splitlines()[-1]
    key = find_active_key(raw)
    assert key.tier == ApiKey.TIER_PARTNER

    call_command("revoke_api_key", f"bvk_{key.prefix}", stdout=StringIO())
    assert find_active_key(raw) is None


# ── Auth ─────────────────────────────────────────────────────────────────────


def test_missing_key_is_401_with_contract(client):
    response = client.get("/api/v1/me/")
    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "missing_api_key", "auth": "api_key"}
    assert response["WWW-Authenticate"].startswith("Bearer")


def test_wrong_and_revoked_keys_are_401(client, raw_key):
    bad = client.get("/api/v1/me/", HTTP_AUTHORIZATION="Bearer bvk_aaaaaaaa_" + "x" * 43)
    assert bad.json()["error"] == "invalid_api_key"

    ApiKey.objects.get().revoke()
    revoked = client.get("/api/v1/me/", HTTP_AUTHORIZATION=f"Bearer {raw_key}")
    assert revoked.status_code == 401


def test_signed_in_session_gets_no_access_without_a_key(logged_in_client):
    assert logged_in_client.get("/api/v1/me/").status_code == 401


def test_me_describes_the_key_and_records_use(api):
    response = api.get("/api/v1/me/")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["name"] == "Test site"
    assert body["data"]["prefix"].startswith("bvk_")
    assert ApiKey.objects.get().last_used_at is not None
    assert response["X-Bonkverse-API-Version"] == "1"


def test_guessing_keys_from_one_ip_gets_429(client, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "api_auth_fail": "3/m"}
    codes = [
        client.get("/api/v1/me/", HTTP_AUTHORIZATION="Bearer bvk_guess").status_code
        for _ in range(5)
    ]
    assert codes == [401, 401, 401, 429, 429]


def test_wrong_method_is_405(api):
    response = api.post("/api/v1/me/", {})
    assert response.status_code == 405
    assert response.json()["error"] == "method_not_allowed"


# ── Rate limits ──────────────────────────────────────────────────────────────


def test_limit_is_per_key_with_headers(client, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "api": "2/m"}
    _a, key_a = create_key(name="A")
    _b, key_b = create_key(name="B")

    def call(key):
        return client.get("/api/v1/me/", HTTP_AUTHORIZATION=f"Bearer {key}")

    first = call(key_a)
    assert first["RateLimit-Limit"] == "2"
    assert first["RateLimit-Remaining"] == "1"
    assert call(key_a).status_code == 200
    limited = call(key_a)
    assert limited.status_code == 429
    assert limited.json()["error"] == "rate_limited"
    assert "Retry-After" in limited
    # Another key, same IP, still fine.
    assert call(key_b).status_code == 200


def test_partner_keys_get_the_partner_rate(client, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "api": "1/m", "api_partner": "5/m"}
    _k, raw = create_key(name="Partner", tier=ApiKey.TIER_PARTNER)
    response = client.get("/api/v1/me/", HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert response["RateLimit-Limit"] == "5"


# ── One player ───────────────────────────────────────────────────────────────


def test_player_level_with_seen_time(api, mocked_http):
    mock_lookup(mocked_http, [lookup_row("Ender")])

    response = api.get("/api/v1/players/ender/")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["username"] == "Ender"
    assert data["status"] == "found"
    assert data["level"] == {
        "value": 87,
        "peak": 87,
        "seen_at": "2026-11-08T03:00:00.000Z",
        "seen_day": "2026-11-08",
        "estimated": False,
        "source": "replays",
        "replay": {"cycle": 6, "id": "344124"},
    }
    assert data["profile_url"] == "http://testserver/player/Ender/"
    assert data["account"] is None
    assert response["Cache-Control"] == "private, max-age=300"


def test_known_bonk_account_adds_dbid_and_join_day(api, mocked_http):
    BonkPlayer.objects.create(bonk_id=13159907, username="Ender", xp=999_999)
    mock_lookup(mocked_http, [lookup_row("Ender")])

    data = api.get("/api/v1/players/ender/").json()["data"]

    assert data["account"]["dbid"] == 13159907
    assert data["account"]["joined"]  # YYYY-MM-DD, estimated from the ID
    assert len(data["account"]["joined"]) == 10
    assert data["account"]["joined_estimated"] is True


def test_known_account_without_replays_still_links_profile(api, mocked_http):
    BonkPlayer.objects.create(bonk_id=42, username="Quiet One")
    mock_lookup(mocked_http, [])

    data = api.post("/api/v1/lookup/players/", {"usernames": ["quiet one"]}).json()["data"]

    entry = data["players"][0]
    assert entry["status"] == "not_found"
    assert entry["username"] == "Quiet One"
    assert entry["account"]["dbid"] == 42
    assert entry["profile_url"].endswith("/player/Quiet%20One/")


def test_player_without_a_known_skin_has_skin_null(api, mocked_http):
    mock_lookup(mocked_http, [lookup_row("Ender")])

    assert api.get("/api/v1/players/ender/").json()["data"]["skin"] is None


def test_worn_skin_with_image_urls(api, mocked_http):
    player = BonkPlayer.objects.create(bonk_id=13159907, username="Ender")
    seen_at = datetime(2026, 11, 14, 8, 30, 15, 123456, tzinfo=UTC)
    record_worn_skin(player.bonk_id, SKIN_CODE, WornSkinSource.LOGIN, seen_at=seen_at)
    mock_lookup(mocked_http, [lookup_row("Ender")])

    skin = api.get("/api/v1/players/ender/").json()["data"]["skin"]

    version = code_digest(SKIN_CODE)[:12]
    assert skin == {
        "image_url": f"http://testserver/player/Ender/skin.png?v={version}",
        "thumbnail_url": f"http://testserver/player/Ender/skin-thumb.png?v={version}",
        "seen_at": "2026-11-14T08:30:15.123Z",
    }
    assert "login" not in json.dumps(skin)  # where we saw it stays internal


def test_the_skin_code_is_never_published(api, mocked_http):
    """The code is the skin itself: images only (2026-11-14)."""
    player = BonkPlayer.objects.create(bonk_id=13159907, username="Ender")
    record_worn_skin(player.bonk_id, SKIN_CODE, WornSkinSource.LOGIN)
    mock_lookup(mocked_http, [lookup_row("Ender")])

    single = api.get("/api/v1/players/ender/").content.decode()
    bulk = api.post("/api/v1/lookup/players/", {"usernames": ["Ender"]}).content.decode()

    for body in (single, bulk):
        assert "skin_code" not in body
        assert SKIN_CODE.split("+")[0] not in body  # not even escaped differently


def test_bulk_lookup_includes_skins_even_without_replays(api, mocked_http):
    player = BonkPlayer.objects.create(bonk_id=42, username="Quiet One")
    record_worn_skin(player.bonk_id, SKIN_CODE, WornSkinSource.WEAR)
    mock_lookup(mocked_http, [])

    entry = api.post("/api/v1/lookup/players/", {"usernames": ["quiet one"]}).json()["data"][
        "players"
    ][0]

    assert entry["status"] == "not_found"
    assert entry["skin"]["image_url"].startswith("http://testserver/player/Quiet%20One/skin.png")


def test_unknown_player_is_404(api, mocked_http):
    mock_lookup(mocked_http, [])
    response = api.get("/api/v1/players/nobody/")
    assert response.status_code == 404
    assert response.json() == {"ok": False, "error": "player_not_found"}


def test_replay_site_down_is_503_and_not_cached(api, mocked_http):
    mock_lookup(mocked_http, [], status=502)
    assert api.get("/api/v1/players/ender/").status_code == 503

    mocked_http.replace("GET", LOOKUP, json={"results": [lookup_row("Ender")]})
    assert api.get("/api/v1/players/ender/").status_code == 200


def test_hidden_level_section_hides_level_from_the_api(api, mocked_http):
    owner = UserFactory(username="Ender")
    ProfileVisibility.objects.create(user=owner, level_history=False)
    mock_lookup(mocked_http, [lookup_row("Ender")])

    data = api.get("/api/v1/players/Ender/").json()["data"]

    assert data["status"] == "private"
    assert data["level"] is None
    assert data["bonkverse_account"] is True


def test_dot_names_use_the_tilde_path(api, mocked_http):
    mocked_http.get(
        LOOKUP,
        json={"results": [lookup_row("..")]},
        match=[matchers.query_param_matcher({"names": ".."})],
    )
    response = api.get("/api/v1/players/~../")
    assert response.status_code == 200
    assert response.json()["data"]["username"] == ".."


# ── Level history ────────────────────────────────────────────────────────────


def test_level_history(api, mocked_http):
    mocked_http.get(f"{REPLAYS}/api/player/{quote('Saucy Tulip')}", json=profile_json())

    response = api.get(f"/api/v1/players/{quote('Saucy Tulip')}/level-history/")

    data = response.json()["data"]
    assert data["current_level"] == 54
    assert data["level_ups"][-1] == {
        "level": 54,
        "day": "2026-11-07",
        "at": "2026-11-07T03:10:00Z",
        "replay": {"cycle": 6, "id": "344000"},
    }
    assert data["days"][0] == {"day": "2025-03-05", "level": 40}


def test_level_history_private_is_403(api):
    owner = UserFactory(username="Shy")
    ProfileVisibility.objects.create(user=owner, level_history=False)
    response = api.get("/api/v1/players/Shy/level-history/")
    assert response.status_code == 403
    assert response.json()["error"] == "player_private"


# ── Bulk lookup ──────────────────────────────────────────────────────────────


def test_bulk_lookup_every_name_gets_a_status(api, mocked_http):
    shy = UserFactory(username="Shy")
    ProfileVisibility.objects.create(user=shy, level_history=False)
    mock_lookup(mocked_http, [lookup_row("Ender"), lookup_row("Shy", level=10)])

    response = api.post(
        "/api/v1/lookup/players/", {"usernames": ["ender", "Shy", "ghost", "ENDER"]}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [(p["requested"], p["status"]) for p in data["players"]] == [
        ("ender", "found"),
        ("Shy", "private"),
        ("ghost", "not_found"),
    ]
    assert data["counts"] == {"found": 1, "private": 1, "not_found": 1}


def test_bulk_lookup_chunks_to_the_replay_site_and_caches(api, mocked_http):
    names = [f"p{i}" for i in range(130)]
    mock_lookup(mocked_http, [lookup_row(n) for n in names])

    api.post("/api/v1/lookup/players/", {"usernames": names})
    calls_after_first = len(mocked_http.calls)
    api.post("/api/v1/lookup/players/", {"usernames": names})

    assert calls_after_first == 3  # 60 + 60 + 10
    assert len(mocked_http.calls) == calls_after_first  # second sync served from cache


@pytest.mark.parametrize(
    "body,error",
    [
        ({}, "usernames_required"),
        ({"usernames": []}, "usernames_required"),
        ({"usernames": "ender"}, "usernames_required"),
        ({"usernames": [""]}, "invalid_username"),
        ({"usernames": [7]}, "invalid_username"),
        ({"usernames": [f"p{i}" for i in range(251)]}, "too_many_usernames"),
    ],
)
def test_bulk_lookup_validation(api, body, error):
    response = api.post("/api/v1/lookup/players/", body)
    assert response.status_code == 400
    assert response.json()["error"] == error


def test_bulk_lookup_bad_json(client, raw_key):
    response = client.post(
        "/api/v1/lookup/players/",
        data="{nope",
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {raw_key}",
    )
    assert response.json()["error"] == "invalid_json"


def test_bulk_lookup_never_sends_login_xp(api, mocked_http):
    """BonkPlayer.xp comes from the player's own login; it's not for other sites."""
    BonkPlayer.objects.create(bonk_id=13159907, username="Ender", xp=123_456)
    mock_lookup(mocked_http, [lookup_row("Ender")])
    body = api.post("/api/v1/lookup/players/", {"usernames": ["Ender"]}).content.decode()
    assert '"xp"' not in body
    assert "123456" not in body
