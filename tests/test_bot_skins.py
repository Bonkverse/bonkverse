"""Tests for BonxBot skin submissions (skins/apis/bot_skins.py, skins/skin_import.py)."""

import base64
import json

import pytest
import responses

import threading
import time

from django.db import connection

from core.bonk import SkinCode
from integrations.bonxbot_db import BotSkin
from integrations.editor_render import RenderedSkin, RenderResult
from skins.bonxbot_migration import migrate
from skins.models import Skin, SkinImage, UserEvent
from skins.skin_import import (
    canonical_link,
    clean_creator,
    clean_skin_name,
    existing_skin,
    import_bonkleagues_skin,
)
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
    [
        "https://evil.example/s/AbC1234",
        "https://bonkleagues.io.evil.example/s/AbC1234",
        "ftp://bonkleagues.io/s/AbC1234",
        "not a link",
        "",
    ],
)
def test_non_bonkleagues_links_are_permanent_errors(client, link):
    response = _submit(client, link=link)

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_link", "retryable": False}


def test_link_longer_than_the_column_is_rejected_before_fetching(client, mocked_http):
    response = _submit(client, link="https://bonkleagues.io/avatar.svg?skinCode=" + "a" * 300)

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


# ── Duplicates: one skin per BonkLeagues link, however it's written ──────────


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("https://bonkleagues.io/s/AbC1234", "https://bonkleagues.io/s/AbC1234"),
        ("http://www.BonkLeagues.io/s/AbC1234/", "https://bonkleagues.io/s/AbC1234"),
        ("https://bonkleagues.io/s/AbC1234?ref=discord#x", "https://bonkleagues.io/s/AbC1234"),
        ("  https://bonkleagues.io/s/AbC1234  ", "https://bonkleagues.io/s/AbC1234"),
        # Other pages keep their query: it may be what identifies the skin.
        (
            "https://www.bonkleagues.io/avatar.svg?skinCode=Cgc%2B#top",
            "https://bonkleagues.io/avatar.svg?skinCode=Cgc%2B",
        ),
        ("https://evil.example/s/AbC1234", None),
        ("javascript:alert(1)", None),
        (None, None),
    ],
)
def test_canonical_link(raw, canonical):
    assert canonical_link(raw) == canonical


def test_short_link_code_stays_case_sensitive():
    assert canonical_link("https://bonkleagues.io/s/AbC1234") != canonical_link(
        "https://bonkleagues.io/s/abc1234"
    )


@pytest.mark.parametrize(
    "stored",
    [
        "https://bonkleagues.io/s/AbC1234",
        "https://bonkleagues.io/s/AbC1234/",
        "https://www.bonkleagues.io/s/AbC1234",
        "http://bonkleagues.io/s/AbC1234",
    ],
)
def test_older_rows_match_in_any_spelling(stored):
    skin = SkinFactory(link=stored)

    assert existing_skin("http://www.bonkleagues.io/s/AbC1234/?utm=x") == skin


def test_different_case_is_a_different_skin():
    SkinFactory(link="https://bonkleagues.io/s/abc1234")

    assert existing_skin(LINK) is None


def test_variant_link_returns_existing_skin_without_rendering(client, mocked_http):
    existing = SkinFactory(link="https://www.bonkleagues.io/s/AbC1234/")

    response = _submit(client, link="http://bonkleagues.io/s/AbC1234?ref=discord", skin_code="C")

    assert response.status_code == 200
    assert response.json()["skin"]["id"] == existing.id
    assert len(mocked_http.calls) == 0


def test_new_skin_stores_the_canonical_link(client, mocked_http):
    _editor_renders(mocked_http)

    _submit(client, link="http://www.bonkleagues.io/s/AbC1234/?ref=discord", skin_code="C")

    assert Skin.objects.get().link == LINK


def test_migration_rows_that_are_spellings_of_one_link_make_one_skin(mocked_http):
    _editor_renders(mocked_http)
    db = FakeBonxBotDB(
        [
            BotSkin(1, "A", "https://bonkleagues.io/s/AbC1234", "a", 1, "CODE"),
            BotSkin(2, "A again", "https://www.bonkleagues.io/s/AbC1234/", "a", 2, "CODE"),
        ]
    )

    report = migrate(db, dry_run=False)

    skin = Skin.objects.get()
    assert db.synced == {1: skin.id, 2: skin.id}
    assert report.counts == {"created_from_code": 1, "duplicate": 1}
    assert len(mocked_http.calls) == 1


@pytest.mark.django_db(transaction=True)
def test_two_imports_of_one_link_at_once_make_one_skin(settings, tmp_path):
    """Regression: the bot's instant push and its retry loop could import the
    same link at the same moment; both passed the duplicate check before either
    saved, leaving two skins."""
    settings.MEDIA_ROOT = tmp_path
    renders = []

    def slow_render(code):
        renders.append(code)
        time.sleep(0.3)  # long enough that both imports overlap without the lock
        return RenderResult(skin=RenderedSkin(svg=SVG, png=PNG, thumbnail=PNG))

    results = []

    def run(link):
        try:
            results.append(
                import_bonkleagues_skin(link, "A", "a", skin_code="C", render=slow_render)
            )
        finally:
            connection.close()  # each thread has its own connection

    threads = [
        threading.Thread(target=run, args=(LINK,)),
        threading.Thread(target=run, args=("https://www.bonkleagues.io/s/AbC1234/",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert Skin.objects.count() == 1
    assert len(renders) == 1
    assert sorted(r.created for r in results) == [False, True]
    assert len({r.skin.id for r in results}) == 1


@pytest.mark.django_db(transaction=True)
def test_lock_is_released_after_a_failed_import(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path

    failed = import_bonkleagues_skin(
        LINK, "A", "a", skin_code="C", render=lambda _c: RenderResult(error="render_status_503")
    )
    ok = import_bonkleagues_skin(
        LINK,
        "A",
        "a",
        skin_code="C",
        render=lambda _c: RenderResult(skin=RenderedSkin(svg=SVG, png=PNG, thumbnail=PNG)),
    )

    assert failed.error == "render_failed"
    assert ok.created
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")
        assert cursor.fetchone()[0] == 0


# ── Older bot rows: no skin_code, but final_url may carry it ─────────────────

REDIRECT = "https://bonkleagues.io/skins.html#Fire%20Dragon%7Csome%20artist%7CCgcDYQAC%2BCQk%3D"


@pytest.mark.parametrize(
    ("url", "code"),
    [
        (REDIRECT, "CgcDYQAC+CQk="),
        ("https://bonkleagues.io/skins.html#Name|Author|CgcDYQ", "CgcDYQ"),
        ("https://bonkleagues.io/api/avatar.svg?skinCode=CgcDYQAC%252BCQk", "CgcDYQAC+CQk"),
        ("https://bonkleagues.io/s/AbC1234", None),  # og:url page link: no code in it
        ("https://bonkleagues.io/skins.html#Name|Author|<script>", None),  # not base64
        ("https://bonkleagues.io/skins.html#only|two", None),
        ("", None),
        (None, None),
    ],
)
def test_skin_code_from_bonkleagues_url(url, code):
    found = SkinCode.from_bonkleagues_url(url)
    assert (found.decoded if found else None) == code


def test_migration_uses_the_code_in_final_url_instead_of_bonkleagues(mocked_http):
    _editor_renders(mocked_http)
    db = FakeBonxBotDB([BotSkin(1, "Fire Dragon", LINK, "artist", 1, None, REDIRECT)])

    report = migrate(db, dry_run=False, sleep=lambda _s: pytest.fail("should not pace"))

    assert report.counts == {"created_from_final_url": 1}
    assert [c.request.url for c in mocked_http.calls] == [f"{EDITOR}/api/render-bundle"]
    assert Skin.objects.get().skin_code == "CgcDYQAC+CQk="


def test_dry_run_reports_where_each_code_comes_from():
    db = FakeBonxBotDB(
        [
            BotSkin(1, "A", "https://bonkleagues.io/s/AAAAAA1", "a", 1, "CODE"),
            BotSkin(2, "B", "https://bonkleagues.io/s/AAAAAA2", "b", 2, None, REDIRECT),
            BotSkin(3, "C", "https://bonkleagues.io/s/AAAAAA3", "c", 3, None, LINK),
        ]
    )

    report = migrate(db, dry_run=True)

    assert dict(report.counts) == {
        "create_from_code": 1,
        "create_from_final_url": 1,
        "create_from_bonkleagues": 1,
    }


def test_no_bonkleagues_skips_rows_only_bonkleagues_can_fill(mocked_http):
    SkinFactory(link="https://bonkleagues.io/s/DUPDUP1")
    db = FakeBonxBotDB(
        [
            BotSkin(1, "Needs BL", "https://bonkleagues.io/s/AAAAAA3", "c", 3, None, None),
            BotSkin(2, "Dup, no code", "https://bonkleagues.io/s/DUPDUP1", "d", 4, None, None),
        ]
    )

    planned = migrate(db, dry_run=True, skip_bonkleagues=True)
    report = migrate(db, dry_run=False, skip_bonkleagues=True)

    assert dict(planned.counts) == {"skipped_needs_bonkleagues": 1, "duplicate": 1}
    assert dict(report.counts) == {"skipped_needs_bonkleagues": 1, "duplicate": 1}
    assert len(mocked_http.calls) == 0
    assert 1 not in db.synced and 1 not in db.failed  # left for a later run
    assert 2 in db.synced  # duplicates still get linked; that needs no fetch
