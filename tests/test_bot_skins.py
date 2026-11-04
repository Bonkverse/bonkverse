"""Tests for BonxBot skin submissions (skins/apis/bot_skins.py, skins/skin_import.py)."""

import base64
import json

import pytest
import responses

from integrations.bonxbot_db import BotSkin
from skins.bonxbot_migration import migrate
from skins.models import Skin, SkinImage, UserEvent
from skins.skin_import import clean_creator, clean_skin_name
from tests.factories import SkinFactory

pytestmark = pytest.mark.django_db

URL = "/api/bot/skins/"
FETCHER = "https://fetcher.test/api/getSkin"
EDITOR = "https://editor.test"
TOKEN = "test-bot-token"
LINK = "https://bonkleagues.io/s/AbC1234"
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    '<rect width="10" height="10" fill="red"/></svg>'
)
PNG = b"\x89PNG fake"


@pytest.fixture(autouse=True)
def _bot_settings(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.BLSKIN_FETCHER_URL = FETCHER
    settings.BONKVERSE_RENDER_URL = EDITOR
    settings.BONXBOT_API_TOKEN = TOKEN


def _editor_renders(mocked_http, *, ok=True, status=200):
    body = {"ok": ok, "svg": SVG, "pngBase64": base64.b64encode(PNG).decode()}
    if not ok:
        body = {"ok": False, "error": "bad skin code"}
    mocked_http.add(responses.POST, f"{EDITOR}/api/render-bundle", json=body, status=status)


def _fetcher_replies(mocked_http, *, svg=SVG, status=200):
    body = {
        "skinCode": "CODE123",
        "media": {"svg": svg, "pngBase64": base64.b64encode(PNG).decode()},
    }
    mocked_http.add(responses.GET, FETCHER, json=body, status=status)


def _submit(client, token=TOKEN, **fields):
    data = {"link": LINK, "name": "Fire Dragon", "creator": "Some Artist", **fields}
    return client.post(
        URL,
        json.dumps(data),
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_creates_skin_with_images_and_discord_provenance(client, mocked_http, tmp_path):
    _fetcher_replies(mocked_http)

    response = _submit(client, discord_user_id=42, bonx_skin_id=7)

    assert response.status_code == 201
    skin = Skin.objects.get()
    assert (skin.name, skin.creator, skin.link, skin.skin_code) == (
        "Fire Dragon",
        "Some Artist",
        LINK,
        "CODE123",
    )
    assert response.json() == {
        "created": True,
        "skin": {
            "id": skin.id,
            "name": "Fire Dragon",
            "creator": "Some Artist",
            "url": skin.get_absolute_url(),
        },
    }
    assert sorted(SkinImage.objects.values_list("kind", flat=True)) == ["png", "svg", "thumbnail"]
    assert (tmp_path / f"skins/{skin.id}_thumb.png").read_bytes() == PNG  # falls back to the PNG
    event = UserEvent.objects.get(event_type="skin_uploaded")
    assert event.user is None
    assert event.metadata == {"source": "discord", "discord_user_id": 42, "bonx_skin_id": 7}


def test_same_link_again_returns_existing_skin_without_fetching(client, mocked_http):
    existing = SkinFactory(link=LINK)

    response = _submit(client)

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["skin"]["id"] == existing.id
    assert Skin.objects.count() == 1
    assert len(mocked_http.calls) == 0


@pytest.mark.parametrize("token", ["", "wrong-token"])
def test_rejects_missing_or_wrong_token(client, token):
    response = _submit(client, token=token)

    assert response.status_code == 401
    assert not Skin.objects.exists()


def test_refuses_everything_when_no_token_is_configured(client, settings):
    settings.BONXBOT_API_TOKEN = ""

    assert _submit(client, token="").status_code == 401


@pytest.mark.parametrize(
    "link",
    ["http://bonkleagues.io/s/AbC1234", "https://evil.example/s/AbC1234", "not a link", ""],
)
def test_non_bonkleagues_links_are_permanent_errors(client, link):
    response = _submit(client, link=link)

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_link", "retryable": False}


def test_link_longer_than_the_column_is_rejected_before_fetching(client, mocked_http):
    response = _submit(client, link=LINK + "?x=" + "a" * 300)

    assert response.status_code == 422
    assert response.json()["error"] == "link_too_long"
    assert len(mocked_http.calls) == 0


def test_fetcher_down_is_retryable_and_stores_nothing(client, mocked_http):
    _fetcher_replies(mocked_http, status=503)

    response = _submit(client)

    assert response.status_code == 502
    assert response.json() == {"error": "fetch_failed", "retryable": True}
    assert not Skin.objects.exists()


def test_unsafe_svg_is_rejected(client, mocked_http, tmp_path):
    _fetcher_replies(mocked_http, svg='<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>')

    response = _submit(client)

    assert response.status_code == 422
    assert response.json()["error"] == "unsafe_svg"
    assert not Skin.objects.exists()
    assert not (tmp_path / "skins").exists() or not any((tmp_path / "skins").iterdir())


def test_get_is_not_allowed(client):
    assert client.get(URL).status_code == 405


def test_bad_json_is_a_400(client):
    response = client.post(
        URL, "{nope", content_type="application/json", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("Fire🔥Dragon!!", "FireDragon"),
        ("  lots   of   space ", "lots of space"),
        ("snake_case 2", "snake_case 2"),
        ("🔥🔥", "UnnamedSkin"),
        (None, "UnnamedSkin"),
    ],
)
def test_clean_skin_name(raw, cleaned):
    assert clean_skin_name(raw) == cleaned


def test_clean_creator_keeps_spaces_but_fills_blanks():
    assert clean_creator(" Spaced  Name ") == " Spaced  Name "
    assert clean_creator("   ") == "UnknownSkinCreator"
    assert clean_creator(None) == "UnknownSkinCreator"


# ── With a skin code: the editor renders it, BonkLeagues is never contacted ──


def test_skin_code_is_rendered_by_the_editor_not_fetched(client, mocked_http):
    _editor_renders(mocked_http)

    response = _submit(client, skin_code="CgcDYQAC%252BCQk")  # double URL-encoded

    assert response.status_code == 201
    assert [c.request.url for c in mocked_http.calls] == [f"{EDITOR}/api/render-bundle"]
    assert json.loads(mocked_http.calls[0].request.body)["skinCode"] == "CgcDYQAC+CQk"
    skin = Skin.objects.get()
    assert skin.skin_code == "CgcDYQAC+CQk"
    assert SkinImage.objects.filter(skin=skin).count() == 3


def test_editor_refusing_the_code_is_retryable_and_stores_nothing(client, mocked_http):
    _editor_renders(mocked_http, ok=False)

    response = _submit(client, skin_code="CODE")

    assert response.status_code == 502
    assert response.json() == {"error": "render_failed", "retryable": True}
    assert not Skin.objects.exists()


def test_editor_down_is_retryable(client, mocked_http):
    _editor_renders(mocked_http, status=503)

    assert _submit(client, skin_code="CODE").json()["error"] == "render_failed"


def test_duplicate_with_code_renders_nothing(client, mocked_http):
    SkinFactory(link=LINK)

    assert _submit(client, skin_code="CODE").status_code == 200
    assert len(mocked_http.calls) == 0


# ── One-time migration (skins/bonxbot_migration.py) ──────────────────────────


class FakeBonxBotDB:
    """Stands in for integrations.bonxbot_db.BonxBotDB."""

    def __init__(self, rows):
        self.rows = rows
        self.synced, self.failed = {}, {}
        self.schema_ensured = False

    def ensure_sync_columns(self):
        self.schema_ensured = True

    def unsynced_skins(self, limit=None):
        return self.rows[:limit] if limit else list(self.rows)

    def mark_synced(self, bot_id, bonkverse_id):
        self.synced[bot_id] = bonkverse_id

    def mark_failed(self, bot_id, error):
        self.failed[bot_id] = error


def _rows():
    return [
        BotSkin(1, "Fire🔥Dragon", "https://bonkleagues.io/s/AAAAAA1", "artist", 111, "CODE1"),
        BotSkin(2, "On site already", "https://bonkleagues.io/s/EXISTS1", "x", 222, "CODE2"),
        BotSkin(3, "Imgur", "https://imgur.com/abc", "y", 333, "CODE3"),
        BotSkin(4, "No code", "https://bonkleagues.io/s/AAAAAA4", "z", 444, None),
    ]


def test_migration_dry_run_writes_and_renders_nothing(mocked_http):
    SkinFactory(link="https://bonkleagues.io/s/EXISTS1")
    db = FakeBonxBotDB(_rows())

    report = migrate(db, dry_run=True)

    assert dict(report.counts) == {
        "create_from_code": 1,
        "duplicate": 1,
        "invalid_link": 1,
        "create_from_bonkleagues": 1,
    }
    assert len(mocked_http.calls) == 0
    assert (db.synced, db.failed, db.schema_ensured) == ({}, {}, False)
    assert Skin.objects.count() == 1


def test_migration_imports_and_records_every_outcome_on_the_bot(mocked_http):
    on_site = SkinFactory(link="https://bonkleagues.io/s/EXISTS1")
    _editor_renders(mocked_http)
    _fetcher_replies(mocked_http)
    db = FakeBonxBotDB(_rows())
    pauses = []

    report = migrate(db, dry_run=False, sleep=pauses.append)

    created = Skin.objects.get(link="https://bonkleagues.io/s/AAAAAA1")
    from_bl = Skin.objects.get(link="https://bonkleagues.io/s/AAAAAA4")
    assert created.name == "FireDragon"
    assert db.synced == {1: created.id, 2: on_site.id, 4: from_bl.id}
    assert db.failed == {3: "invalid_link"}
    assert db.schema_ensured
    # Only the row without a code touched BonkLeagues, and it was paced.
    assert sum(1 for c in mocked_http.calls if c.request.url.startswith(FETCHER)) == 1
    assert len(pauses) == 1
    assert dict(report.counts) == {
        "created_from_code": 1,
        "duplicate": 1,
        "invalid_link": 1,
        "created_from_bonkleagues": 1,
    }
    events = UserEvent.objects.filter(event_type="skin_uploaded").order_by("id")
    assert [e.metadata["bonx_skin_id"] for e in events] == [1, 4]
    assert all(e.metadata["migrated"] for e in events)


def test_migration_leaves_render_failures_for_the_bot_to_retry(mocked_http):
    _editor_renders(mocked_http, status=503)
    db = FakeBonxBotDB([BotSkin(1, "A", "https://bonkleagues.io/s/AAAAAA1", "a", 1, "CODE")])

    report = migrate(db, dry_run=False, sleep=lambda _s: None)

    assert (db.synced, db.failed) == ({}, {})
    assert report.counts == {"retry_later": 1}
    assert report.retry_later[0][0] == 1


def test_migration_is_safe_to_rerun(mocked_http):
    _editor_renders(mocked_http)
    rows = _rows()[:1]

    migrate(FakeBonxBotDB(rows), dry_run=False)
    report = migrate(FakeBonxBotDB(rows), dry_run=False)  # bot write-back lost, say

    assert Skin.objects.count() == 1
    assert report.counts == {"duplicate": 1}
