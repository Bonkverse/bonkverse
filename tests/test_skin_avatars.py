"""A player's worn skin as their avatar: images rendered once per skin code
(skins/services.py, skins/skin_media.py), served at /player/<name>/skin.png
(players/views.py), and shown on profiles, people lists and player cards."""

import base64
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from players.models import BonkPlayer, WornSkinSource
from players.selectors import worn_skin_codes
from players.services import record_worn_skin
from skins import skin_media
from skins.services import code_digest, code_image
from tests.factories import SKIN_CODE, BonkPlayerFactory
from tests.test_players import REPLAYS, mock_player
from tests.test_players_directory import mock_lookup

pytestmark = pytest.mark.django_db

EDITOR = "https://editor.test"
RENDER_URL = f"{EDITOR}/api/render-bundle"
PNG = b"\x89PNG\r\n\x1a\n big"
THUMB = b"\x89PNG\r\n\x1a\n small"
ENCODED_SKIN_CODE = SKIN_CODE.replace("+", "%2B").replace("=", "%3D")
OTHER_SKIN_CODE = (
    "CgcDYQACCQkBCgcFYWwAAQBNPlt5PUI19d8/GMUDPsJvGgAAAAAAAAoFAAEATT5beT1CNfXfvvn8kL80i70B"
    "AAAAAAAKBQABAEs+gkonQjVq/L2vivk9L4r5AAAAzxsPCgUAAQANP1yl2D9VbKUAAAAAAAAAAAAAAM8bDwAAAAA="
)


@pytest.fixture(autouse=True)
def _settings(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.BONKVERSE_RENDER_URL = EDITOR
    settings.BONKVERSE_REPLAYS_URL = REPLAYS


def _renders(mocked_http, png=PNG, thumbnail=THUMB):
    return mocked_http.post(
        RENDER_URL,
        json={
            "ok": True,
            "svg": "<svg/>",
            "pngBase64": base64.b64encode(png).decode(),
            "thumbnailBase64": base64.b64encode(thumbnail).decode(),
        },
    )


def _wearing(username="Saucy Tulip", skin_code=SKIN_CODE):
    player = BonkPlayerFactory(username=username)
    record_worn_skin(player.bonk_id, skin_code, WornSkinSource.LOGIN)
    return player


class TestCodeImage:
    def test_renders_once_and_keeps_the_files(self, mocked_http, tmp_path):
        call = _renders(mocked_http)

        first = code_image(SKIN_CODE, "png")
        again = code_image(SKIN_CODE, "thumbnail")

        assert first == f"skin_codes/{code_digest(SKIN_CODE)}.png"
        assert (tmp_path / first).read_bytes() == PNG
        assert (tmp_path / again).read_bytes() == THUMB
        assert len(call.calls) == 1
        assert call.calls[0].request.body.decode().count(SKIN_CODE) == 1

    def test_url_encoded_code_shares_the_images(self, mocked_http):
        call = _renders(mocked_http)

        assert code_image(SKIN_CODE, "png") == code_image(ENCODED_SKIN_CODE, "png")
        assert len(call.calls) == 1

    def test_text_that_is_not_a_skin_is_never_rendered(self, mocked_http):
        call = _renders(mocked_http)

        assert code_image("POC-FINAL-002", "png") is None
        assert len(call.calls) == 0

    def test_failed_render_backs_off(self, mocked_http, tmp_path):
        call = mocked_http.post(RENDER_URL, json={"ok": False, "error": "boom"})

        assert code_image(SKIN_CODE, "png") is None
        assert code_image(SKIN_CODE, "png") is None
        assert len(call.calls) == 1
        assert not list(tmp_path.rglob("*.png"))

    def test_reply_that_is_not_png_is_not_saved(self, mocked_http, tmp_path):
        _renders(mocked_http, png=b"<html>oops</html>")

        assert code_image(SKIN_CODE, "png") is None
        assert not list(tmp_path.rglob("*.png"))

    def test_render_in_progress_elsewhere_waits(self, mocked_http):
        call = _renders(mocked_http)
        cache.add(f"skin_code_image:rendering:{code_digest(SKIN_CODE)}", 1)

        assert code_image(SKIN_CODE, "png") is None
        assert len(call.calls) == 0

    def test_write_failure_returns_none(self, mocked_http, monkeypatch):
        _renders(mocked_http)

        def broken(*args):
            raise OSError("disk full")

        monkeypatch.setattr(skin_media, "_write_all", broken)

        assert code_image(SKIN_CODE, "png") is None

    def test_unknown_kind_is_a_programming_error(self):
        with pytest.raises(ValueError):
            code_image(SKIN_CODE, "svg")


class TestSkinAvatarRoute:
    def test_serves_the_png_with_cache_headers(self, client, mocked_http):
        _renders(mocked_http)
        _wearing()

        response = client.get(reverse("player_skin_avatar", args=["saucy tulip"]))

        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert b"".join(response.streaming_content) == PNG
        assert "s-maxage" in response["Cache-Control"]

    def test_thumbnail_route(self, client, mocked_http):
        _renders(mocked_http)
        _wearing()

        response = client.get(reverse("player_skin_avatar_thumb", args=["Saucy Tulip"]))

        assert b"".join(response.streaming_content) == THUMB

    def test_newest_of_players_sharing_a_name_wins(self):
        older, newer = (
            BonkPlayerFactory(username="Saucy Tulip"),
            BonkPlayerFactory(username="saucy tulip", bonk_id=None),
        )
        now = timezone.now()
        record_worn_skin(older.bonk_id, OTHER_SKIN_CODE, WornSkinSource.LOGIN, seen_at=now)
        BonkPlayer.objects.filter(pk=newer.pk).update(
            worn_skin_code=SKIN_CODE, worn_skin_seen_at=now + timedelta(minutes=1)
        )

        assert worn_skin_codes(["SAUCY TULIP"]) == {"saucy tulip": SKIN_CODE}

    def test_player_without_a_skin_is_404(self, client, mocked_http):
        BonkPlayerFactory(username="Saucy Tulip")

        response = client.get(reverse("player_skin_avatar", args=["Saucy Tulip"]))

        assert response.status_code == 404
        assert "s-maxage" not in response.get("Cache-Control", "")

    def test_unknown_player_is_404(self, client):
        assert client.get(reverse("player_skin_avatar", args=["nobody"])).status_code == 404

    def test_render_failure_is_404(self, client, mocked_http):
        mocked_http.post(RENDER_URL, json={"ok": False})
        _wearing()

        assert client.get(reverse("player_skin_avatar", args=["Saucy Tulip"])).status_code == 404


class TestAvatarsOnPages:
    def test_profile_header_shows_the_worn_skin(self, client, mocked_http):
        mock_player(mocked_http, "Saucy Tulip")
        _wearing()

        html = client.get(reverse("player_profile", args=["Saucy Tulip"])).content.decode()

        digest = code_digest(SKIN_CODE)[:12]
        assert f"--skin: url('/player/Saucy%20Tulip/skin.png?v={digest}')" in html
        assert "pv-avatar--skin" in html

    def test_profile_without_a_skin_keeps_initials(self, client, mocked_http):
        mock_player(mocked_http, "Saucy Tulip")

        html = client.get(reverse("player_profile", args=["Saucy Tulip"])).content.decode()

        assert "pv-avatar--skin" not in html
        assert "skin.png" not in html

    def test_names_with_quotes_stay_inside_the_css_url(self, client, mocked_http):
        mock_player(mocked_http, "it's me")
        _wearing("it's me")

        html = client.get(reverse("player_profile", args=["it's me"])).content.decode()

        assert "url('/player/it%27s%20me/skin.png?v=" in html

    def test_people_lists_show_skins_of_players_we_know(self, client, mocked_http):
        mock_player(mocked_http, "Saucy Tulip")
        _wearing("Friend One")

        html = client.get(reverse("player_people", args=["Saucy Tulip"])).content.decode()

        assert "/player/Friend%20One/skin-thumb.png?v=" in html
        assert "/player/Rival%20Two/skin-thumb.png" not in html

    def test_overview_partners_show_skins(self, client, mocked_http):
        mock_player(mocked_http, "Saucy Tulip")
        _wearing("Friend One")

        html = client.get(reverse("player_profile", args=["Saucy Tulip"])).content.decode()

        assert "/player/Friend%20One/skin-thumb.png?v=" in html

    def test_directory_cards_show_skins(self, client, mocked_http):
        mock_lookup(mocked_http, [])
        _wearing("Saucy Tulip")
        BonkPlayerFactory(username="saucepan")

        html = client.get(reverse("players_directory") + "?q=sau").content.decode()

        assert "/player/Saucy%20Tulip/skin-thumb.png?v=" in html
        assert "/player/saucepan/skin-thumb.png" not in html

    def test_new_skin_changes_the_url(self, client, mocked_http):
        mock_player(mocked_http, "Saucy Tulip")
        player = _wearing()
        before = client.get(reverse("player_profile", args=["Saucy Tulip"])).content.decode()
        other = skin_media.code_digest(ENCODED_SKIN_CODE)
        assert other == code_digest(SKIN_CODE)  # same skin, encoded: same URL

        record_worn_skin(player.bonk_id, OTHER_SKIN_CODE, WornSkinSource.WEAR)
        cache.clear()
        after = client.get(reverse("player_profile", args=["Saucy Tulip"])).content.decode()

        assert code_digest(SKIN_CODE)[:12] in before
        assert code_digest(SKIN_CODE)[:12] not in after
