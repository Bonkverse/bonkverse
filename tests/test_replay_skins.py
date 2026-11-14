"""Skins from replays: writing a skin code from a replay's avatar
(core/bonk/skin_codes.py SkinCode.from_avatar), storing them by name, newest
sighting winning (players/worn_skins.py record_replay_skins), and the replay
sync reading them (players/replay_sync.py)."""

import base64
from urllib.parse import parse_qs, urlparse
from datetime import UTC, datetime, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.bonk import InvalidSkinCode, SkinCode, SkinLayer
from players import replay_sync
from players.models import BonkPlayer, SyncCursor, WornSkinSource
from players.services import record_replay_skins, record_worn_skin
from tests.factories import SKIN_CODE, BonkPlayerFactory
from tests.test_skin_code_parse import REAL

REPLAYS = "http://replays.test"
NAMES_URL = f"{REPLAYS}/api/internal/replay-names"

# SKIN_CODE (one white-ish circle, shape 13) as a replay stores it.
AVATAR = {
    "layers": [
        {
            "id": 13,
            "scale": 0.15000000596046448,
            "angle": 0,
            "x": 0,
            "y": 0,
            "flipX": False,
            "flipY": False,
            "color": 16448250,
        }
    ],
    "bc": 0,
}
PLAIN = {"layers": [], "bc": 3854915}  # a plain colored skin, no shapes


# ── Writing codes ────────────────────────────────────────────────


class TestFromAvatar:
    def test_writes_the_editors_code_byte_for_byte(self):
        assert SkinCode.from_avatar(AVATAR).raw == SKIN_CODE

    def test_rebuilds_dense_gallery_codes_exactly(self):
        for code in (REAL["editor"], SkinCode(REAL["index_pairs"]).decoded):
            skin = SkinCode(code).parse()
            rebuilt = SkinCode.from_layers(skin.layers, skin.base_color)
            assert rebuilt.parse() == skin

    def test_codes_with_empty_slots_draw_the_same(self):
        skin = SkinCode(REAL["empty_first_slot"]).parse()
        assert SkinCode.from_layers(skin.layers, skin.base_color).parse() == skin

    def test_a_skin_with_no_layers(self):
        code = SkinCode.from_avatar(PLAIN)
        assert code.parse().layers == ()
        assert code.parse().base_color == 3854915

    def test_empty_slots_are_dropped_order_kept(self):
        layer = dict(AVATAR["layers"][0])
        avatar = {"layers": [None, layer, None, {**layer, "id": 7}], "bc": 1}
        shapes = [layer.shape_id for layer in SkinCode.from_avatar(avatar).parse().layers]
        assert shapes == [13, 7]

    def test_many_layers_use_a_two_byte_count(self):
        layers = [SkinLayer(13, 0.1, 0, 0, 0, False, False, 0)] * 100
        assert len(SkinCode.from_layers(layers, 0).parse().layers) == 100

    @pytest.mark.parametrize(
        "avatar",
        [
            None,
            "x",
            {"bc": 1},
            {"layers": "no"},
            {"layers": [{"scale": 1}], "bc": 0},  # no shape id
            {"layers": [{**AVATAR["layers"][0], "id": 999}], "bc": 0},  # no such shape
            {"layers": [{**AVATAR["layers"][0], "color": -1}], "bc": 0},
            {"layers": [{**AVATAR["layers"][0], "scale": "big"}], "bc": 0},
            {"layers": [], "bc": 0x1000000},
            {"layers": [AVATAR["layers"][0]] * 129, "bc": 0},
        ],
    )
    def test_refuses_what_isnt_an_avatar(self, avatar):
        with pytest.raises(InvalidSkinCode):
            SkinCode.from_avatar(avatar)

    def test_round_trip_decodes(self):
        raw = base64.b64decode(SkinCode.from_avatar(AVATAR).raw)
        assert raw.startswith(bytes([0x0A, 0x07, 0x03, 0x61, 0x00, 0x02, 0x09]))


# ── Storing by name ──────────────────────────────────────────────

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)


@pytest.mark.django_db
class TestRecordReplaySkins:
    def test_every_player_with_the_name_gets_it(self):
        real = BonkPlayerFactory(username="Saucy Tulip")
        copy = BonkPlayerFactory(username="saucy tulip", bonk_id=None)
        other = BonkPlayerFactory(username="someone")

        changed = record_replay_skins({"SAUCY TULIP": (SKIN_CODE, NOW)})

        assert changed == 2
        for player in (real, copy):
            player.refresh_from_db()
            assert (player.worn_skin_code, player.worn_skin_seen_at) == (SKIN_CODE, NOW)
            assert player.worn_skin_source == WornSkinSource.REPLAY
        other.refresh_from_db()
        assert other.worn_skin_code is None

    def test_a_newer_login_keeps_its_skin(self):
        player = BonkPlayerFactory(username="Tulip")
        plain = SkinCode.from_avatar(PLAIN).raw
        record_worn_skin(player.bonk_id, plain, WornSkinSource.LOGIN, seen_at=NOW)

        assert record_replay_skins({"Tulip": (SKIN_CODE, NOW - timedelta(days=3))}) == 0

        player.refresh_from_db()
        assert (player.worn_skin_code, player.worn_skin_source) == (plain, WornSkinSource.LOGIN)

    def test_a_newer_replay_replaces_an_older_login(self):
        player = BonkPlayerFactory(username="Tulip")
        plain = SkinCode.from_avatar(PLAIN).raw
        record_worn_skin(player.bonk_id, plain, WornSkinSource.LOGIN, seen_at=NOW - timedelta(1))

        record_replay_skins({"Tulip": (SKIN_CODE, NOW)})

        player.refresh_from_db()
        assert player.worn_skin_source == WornSkinSource.REPLAY

    def test_codes_that_are_not_skins_are_skipped(self):
        player = BonkPlayerFactory(username="Tulip")

        assert record_replay_skins({"Tulip": ("POC-FINAL-002", NOW), "": (SKIN_CODE, NOW)}) == 0

        player.refresh_from_db()
        assert player.worn_skin_code is None

    def test_leaves_updated_at_alone(self):
        """updated_at is the DBID push cursor; a skin isn't a DBID change."""
        player = BonkPlayerFactory(username="Tulip")
        before = BonkPlayer.objects.get(pk=player.pk).updated_at

        record_replay_skins({"Tulip": (SKIN_CODE, NOW)})

        assert BonkPlayer.objects.get(pk=player.pk).updated_at == before


# ── The sync ─────────────────────────────────────────────────────


@pytest.fixture
def _sync_settings(settings):
    settings.BONKVERSE_REPLAYS_URL = REPLAYS
    settings.BONKVERSE_SYNC_TOKEN = "s3cret"


def page(names, avatars, *, next_="6:9", done=True):
    return {"names": names, "avatars": avatars, "next": next_, "done": done}


@pytest.mark.django_db
@pytest.mark.usefixtures("_sync_settings")
class TestSyncReadsSkins:
    def test_new_and_known_names_get_their_replay_skin(self, mocked_http):
        known = BonkPlayerFactory(username="Known One")
        mocked_http.get(
            NAMES_URL,
            json=page(
                [
                    {
                        "username": "Known One",
                        "skin": "h1",
                        "skin_seen_at": "2026-11-14T09:00:00+00:00",
                    },
                    {
                        "username": "New Two",
                        "skin": "h2",
                        "skin_seen_at": "2025-04-10T00:00:00+00:00",
                    },
                    {"username": "No Skin", "skin": None, "skin_seen_at": None},
                    {"username": "Bad Skin", "skin": "h3", "skin_seen_at": "2026-11-14T09:00:00Z"},
                ],
                {"h1": AVATAR, "h2": PLAIN, "h3": {"layers": [{"id": 999}], "bc": 0}},
            ),
        )

        result = replay_sync.pull_replay_names(max_batches=1)

        assert result["skins"] == 2
        known.refresh_from_db()
        assert known.worn_skin_code == SKIN_CODE
        assert known.worn_skin_seen_at == datetime(2026, 11, 14, 9, tzinfo=UTC)
        new = BonkPlayer.objects.get(username="New Two")
        assert new.worn_skin_code == SkinCode.from_avatar(PLAIN).raw
        assert BonkPlayer.objects.get(username="No Skin").worn_skin_code is None
        assert BonkPlayer.objects.get(username="Bad Skin").worn_skin_code is None

    def test_answers_without_skins_still_sync_names(self, mocked_http):
        mocked_http.get(
            NAMES_URL,
            json={
                "names": [{"username": "Old Api", "level": 1, "games": 1}],
                "next": "6:1",
                "done": True,
            },
        )

        result = replay_sync.pull_replay_names(max_batches=1)

        assert (result["added"], result["skins"]) == (1, 0)

    def test_from_start_reads_the_archive_again(self, mocked_http):
        SyncCursor.objects.create(name=replay_sync.NAMES_CURSOR, value="6:500")
        mocked_http.get(NAMES_URL, json=page([], {}, next_="6:9"))

        call_command("sync_replays", "--names-only", "--from-start", "--batches=1")

        after = parse_qs(urlparse(mocked_http.calls[0].request.url).query).get("after", [""])
        assert after == [""]  # from the beginning, not after 6:500
        assert SyncCursor.objects.get(name=replay_sync.NAMES_CURSOR).value == "6:9"


def test_sightings_skip_naive_or_missing_times():
    names = [
        {"username": "A", "skin": "h", "skin_seen_at": "2026-11-14T09:00:00"},  # no zone
        {"username": "B", "skin": "h"},
        {"username": "C", "skin": "h", "skin_seen_at": "2026-11-14T09:00:00+00:00"},
        "junk",
    ]
    out = replay_sync.replay_skin_sightings(names, {"h": AVATAR})
    assert list(out) == ["C"]
    assert out["C"] == (SKIN_CODE, datetime(2026, 11, 14, 9, tzinfo=UTC))
    assert timezone.is_aware(out["C"][1])
