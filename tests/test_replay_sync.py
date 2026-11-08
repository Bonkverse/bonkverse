"""Syncing with the replay site (players/replay_sync.py,
integrations/replay_sync.py): replay names come in as BonkPlayers with no
DBID, get their DBID when a friend list or login shows it, and DBIDs go out
to the replay site."""

import json
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from integrations.bonk_api import BonkFriend
from integrations.replay_sync import SyncError, fetch_replay_names, push_player_ids
from players import charts, replay_sync
from players.models import SyncCursor
from skins.friends_sync import adopt_replay_names, sync_friends_for_player
from skins.models import BonkPlayer

REPLAYS = "http://replays.test"
TOKEN = "s3cret"
NAMES_URL = f"{REPLAYS}/api/internal/replay-names"
IDS_URL = f"{REPLAYS}/api/internal/player-ids"


@pytest.fixture(autouse=True)
def _sync_settings(settings):
    settings.BONKVERSE_REPLAYS_URL = REPLAYS
    settings.BONKVERSE_SYNC_TOKEN = TOKEN
    settings.REPLAY_SYNC_INTERVAL_SECONDS = 3600


def names_page(names, next_, done):
    return {
        "names": [{"username": n, "level": 1, "games": 1} for n in names],
        "next": next_,
        "done": done,
    }


def posted(mocked_http):
    """The player lists sent to the replay site, one list per request."""
    return [
        json.loads(c.request.body)["players"]
        for c in mocked_http.calls
        if c.request.method == "POST"
    ]


# ── Client ───────────────────────────────────────────────────────


def test_client_sends_the_token(mocked_http):
    mocked_http.get(NAMES_URL, json=names_page(["a"], "6:1", True))
    result = fetch_replay_names(REPLAYS, TOKEN, after="5:9", limit=10)
    assert result.data["next"] == "6:1"
    request = mocked_http.calls[0].request
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert "after=5%3A9" in request.url and "limit=10" in request.url


@pytest.mark.parametrize(
    "status,error",
    [(401, SyncError.UNAUTHORIZED), (404, SyncError.UNAUTHORIZED), (503, SyncError.UNAVAILABLE)],
)
def test_client_errors(mocked_http, status, error):
    mocked_http.post(IDS_URL, json={"error": "x"}, status=status)
    assert push_player_ids(REPLAYS, TOKEN, [{"username": "a", "dbid": 1}]).error == error


def test_client_needs_url_and_token(mocked_http):
    assert fetch_replay_names(REPLAYS, "").error == SyncError.NOT_CONFIGURED
    assert len(mocked_http.calls) == 0


# ── Names in ─────────────────────────────────────────────────────


@pytest.mark.django_db
def test_pull_adds_new_names_without_a_dbid(mocked_http):
    BonkPlayer.objects.create(bonk_id=5, username="Known")
    mocked_http.get(NAMES_URL, json=names_page(["known", "(%)", "  spaced  "], "5:100", False))
    mocked_http.get(NAMES_URL, json=names_page(["(%)", "Later"], "6:7", True))
    result = replay_sync.pull_replay_names(max_batches=5)
    assert result == {"added": 3, "batches": 2, "done": True, "error": None}
    new = BonkPlayer.objects.filter(bonk_id__isnull=True).values_list("username", flat=True)
    assert sorted(new) == ["  spaced  ", "(%)", "Later"]  # sorted here: database collations differ
    assert SyncCursor.objects.get(name=replay_sync.NAMES_CURSOR).value == "6:7"
    # The next run starts after the cursor.
    mocked_http.get(NAMES_URL, json=names_page([], "6:7", True))
    replay_sync.pull_replay_names()
    assert "after=6%3A7" in mocked_http.calls[-1].request.url


@pytest.mark.django_db
def test_pull_stops_on_errors_and_keeps_its_place(mocked_http):
    SyncCursor.objects.create(name=replay_sync.NAMES_CURSOR, value="6:1")
    mocked_http.get(NAMES_URL, status=503, json={"error": "down"})
    result = replay_sync.pull_replay_names()
    assert result["error"] == SyncError.UNAVAILABLE
    assert SyncCursor.objects.get(name=replay_sync.NAMES_CURSOR).value == "6:1"


# ── Getting the DBID later ───────────────────────────────────────


@pytest.mark.django_db
def test_friend_sync_gives_a_replay_name_its_dbid():
    copy = BonkPlayer.objects.create(bonk_id=None, username="(%)")
    sync_friends_for_player(
        current_bonk_id=1, current_username="Me", friends=[BonkFriend(bonk_id=777, name="(%)")]
    )
    copy.refresh_from_db()
    assert copy.bonk_id == 777
    assert BonkPlayer.objects.filter(username="(%)").count() == 1


@pytest.mark.django_db
def test_login_player_adopts_their_replay_name():
    copy = BonkPlayer.objects.create(bonk_id=None, username="replay me")
    sync_friends_for_player(current_bonk_id=42, current_username="Replay Me", friends=[])
    copy.refresh_from_db()
    assert (copy.bonk_id, copy.username) == (42, "Replay Me")  # bonk.io's spelling wins


@pytest.mark.django_db
def test_adopt_leaves_copies_alone_when_the_id_already_has_a_row():
    BonkPlayer.objects.create(bonk_id=9, username="Real")
    copy = BonkPlayer.objects.create(bonk_id=None, username="real")
    assert adopt_replay_names({9: "Real"}) == set()
    copy.refresh_from_db()
    assert copy.bonk_id is None


# ── DBIDs out ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_push_sends_changed_players_with_join_days(mocked_http):
    BonkPlayer.objects.create(bonk_id=13159907, username="Dated")
    BonkPlayer.objects.create(bonk_id=None, username="no id")
    BonkPlayer.objects.create(bonk_id=-1, username="placeholder")
    mocked_http.post(IDS_URL, json={"ok": True, "received": 1, "written": 1, "skipped": 0})
    result = replay_sync.push_player_ids()
    assert result["sent"] == 1 and result["done"]
    assert posted(mocked_http) == [
        [{"username": "Dated", "dbid": 13159907, "joined": "2023-04-28"}]
    ]

    # Nothing changed: nothing sent. A rename: sent again.
    replay_sync.push_player_ids()
    assert len(posted(mocked_http)) == 1
    p = BonkPlayer.objects.get(bonk_id=13159907)
    p.username = "Dated2"
    p.save()
    replay_sync.push_player_ids()
    assert posted(mocked_http)[-1][0]["username"] == "Dated2"


@pytest.mark.django_db
def test_push_pages_through_rows_with_the_same_timestamp(mocked_http, monkeypatch):
    monkeypatch.setattr(replay_sync, "MAX_PLAYERS_PER_POST", 2)
    for i in range(5):
        BonkPlayer.objects.create(bonk_id=1000 + i, username=f"p{i}")
    BonkPlayer.objects.update(updated_at=timezone.now() - timedelta(days=1))
    mocked_http.post(IDS_URL, json={"ok": True})
    replay_sync.push_player_ids()
    sent = [row["dbid"] for batch in posted(mocked_http) for row in batch]
    assert sorted(sent) == [1000, 1001, 1002, 1003, 1004]


# ── Running ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_run_is_off_without_a_token(settings, mocked_http):
    settings.BONKVERSE_SYNC_TOKEN = ""
    assert "skipped" in replay_sync.run()
    assert replay_sync.maybe_start() is False
    assert len(mocked_http.calls) == 0


@pytest.mark.django_db
def test_maybe_start_runs_at_most_once_an_hour(monkeypatch):
    started = []
    monkeypatch.setattr(
        replay_sync.threading,
        "Thread",
        lambda **kw: type("T", (), {"start": lambda self: started.append(1)})(),
    )
    assert replay_sync.maybe_start() is True
    assert replay_sync.maybe_start() is False
    assert started == [1]


@pytest.mark.django_db
def test_players_page_starts_the_sync(client, mocked_http, monkeypatch):
    calls = []
    monkeypatch.setattr(replay_sync, "maybe_start", lambda: calls.append(1))
    mocked_http.get(f"{REPLAYS}/api/players/lookup", json={"results": []})
    client.get(reverse("players_directory"))
    assert calls == [1]


@pytest.mark.django_db
def test_command(mocked_http):
    mocked_http.get(NAMES_URL, json=names_page(["(%)"], "6:1", True))
    call_command("sync_replays", "--names-only")
    assert BonkPlayer.objects.filter(username="(%)", bonk_id__isnull=True).exists()


# ── On the Players page ──────────────────────────────────────────


@pytest.mark.django_db
def test_replay_only_players_show_on_the_players_page(client, mocked_http):
    BonkPlayer.objects.create(bonk_id=None, username="(%)")
    mocked_http.get(
        f"{REPLAYS}/api/players/lookup",
        json={"results": [{"username": "(%)", "games": 3, "level": 7}]},
    )
    html = client.get(reverse("players_directory") + "?q=%25").content.decode()
    assert "(%)" in html and "Seen in replays" in html and "DBID" not in html.split("pv-pcards")[1]
    assert charts.profile_path("(%)") in html
