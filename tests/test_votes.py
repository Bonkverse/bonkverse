"""Vote counters stay equal to the votes behind them (skins/votes.py).

The rules tests pin what a click does. The concurrency tests send votes at
the same moment from separate database connections, the way gunicorn's
threads do in production; before RFC-0001 4.1 they lost updates. The audit
tests cover the command that repairs counters from before the fix.
"""

import threading
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.test import Client

from skins.models import Skin, SkinVote
from skins.votes import cast_vote, fix_vote_counts, recount_votes
from tests.factories import SkinFactory, UserFactory


def _counters(skin):
    skin.refresh_from_db()
    return skin.upvotes, skin.downvotes


@pytest.mark.django_db
class TestCastVote:
    def test_first_vote_adds_one(self):
        skin, user = SkinFactory(), UserFactory()

        result = cast_vote(user, skin, "up")

        assert (result.upvotes, result.downvotes, result.current_vote) == (1, 0, "up")
        assert _counters(skin) == (1, 0)
        assert SkinVote.objects.get(user=user, skin=skin).vote == "up"

    def test_same_direction_again_removes_it(self):
        skin, user = SkinFactory(), UserFactory()
        cast_vote(user, skin, "down")

        result = cast_vote(user, skin, "down")

        assert (result.upvotes, result.downvotes, result.current_vote) == (0, 0, None)
        assert not SkinVote.objects.exists()

    def test_other_direction_switches_it(self):
        skin, user = SkinFactory(), UserFactory()
        cast_vote(user, skin, "up")

        result = cast_vote(user, skin, "down")

        assert (result.upvotes, result.downvotes, result.current_vote) == (0, 1, "down")
        assert SkinVote.objects.get(user=user, skin=skin).vote == "down"

    def test_result_counts_other_voters(self):
        skin = SkinFactory()
        cast_vote(UserFactory(), skin, "up")

        result = cast_vote(UserFactory(), skin, "up")

        assert result.upvotes == 2

    def test_removing_never_goes_below_zero(self):
        # A counter that drifted to 0 while a vote row still exists.
        skin, user = SkinFactory(), UserFactory()
        SkinVote.objects.create(user=user, skin=skin, vote="up")

        result = cast_vote(user, skin, "up")

        assert (result.upvotes, result.downvotes) == (0, 0)

    def test_rejects_unknown_direction(self):
        with pytest.raises(ValueError):
            cast_vote(UserFactory(), SkinFactory(), "sideways")


def _at_once(jobs):
    """Run each job in its own thread, released together; re-raise any error."""
    barrier = threading.Barrier(len(jobs))
    errors = []

    def run(job):
        try:
            barrier.wait()
            job()
        except Exception as exc:  # surfaced to the test below
            errors.append(exc)
        finally:
            connection.close()  # each thread has its own connection

    threads = [threading.Thread(target=run, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors


@pytest.mark.django_db(transaction=True)
class TestConcurrentVotes:
    def test_simultaneous_voters_are_all_counted(self):
        skin = SkinFactory()
        users = [UserFactory() for _ in range(8)]

        _at_once([lambda user=user: cast_vote(user, skin, "up") for user in users])

        assert _counters(skin) == (8, 0)
        assert SkinVote.objects.filter(skin=skin).count() == 8

    def test_simultaneous_requests_through_the_endpoint(self):
        skin = SkinFactory()
        clients = []
        for _ in range(8):
            client = Client()
            client.force_login(UserFactory())
            clients.append(client)

        _at_once(
            [
                lambda client=client: client.post(f"/api/skins/{skin.id}/vote/", {"vote": "up"})
                for client in clients
            ]
        )

        assert _counters(skin) == (8, 0)

    def test_double_click_leaves_counters_matching_rows(self):
        skin, user = SkinFactory(), UserFactory()

        _at_once([lambda: cast_vote(user, skin, "up"), lambda: cast_vote(user, skin, "up")])

        # Two clicks of the same button, applied one after the other: on, then off.
        assert _counters(skin) == (0, 0)
        assert not SkinVote.objects.filter(skin=skin).exists()


@pytest.mark.django_db
class TestAudit:
    def _drifted_skin(self):
        skin = SkinFactory()
        SkinVote.objects.create(user=UserFactory(), skin=skin, vote="up")
        SkinVote.objects.create(user=UserFactory(), skin=skin, vote="up")
        SkinVote.objects.create(user=UserFactory(), skin=skin, vote="down")
        Skin.objects.filter(id=skin.id).update(upvotes=1, downvotes=4)
        return skin

    def test_recount_lists_only_wrong_skins(self):
        SkinFactory()  # no votes, counters 0/0: correct
        skin = self._drifted_skin()

        assert recount_votes() == [(skin.id, 1, 4, 2, 1)]

    def test_fix_sets_real_counts(self):
        skin = self._drifted_skin()

        assert fix_vote_counts(recount_votes()) == 1
        assert _counters(skin) == (2, 1)
        assert recount_votes() == []

    def test_command_dry_run_changes_nothing(self):
        skin = self._drifted_skin()
        out = StringIO()

        call_command("audit_vote_counts", stdout=out)

        assert "1 skin(s) have wrong counters" in out.getvalue()
        assert "Dry run" in out.getvalue()
        assert _counters(skin) == (1, 4)

    def test_command_fix_repairs(self):
        skin = self._drifted_skin()
        out = StringIO()

        call_command("audit_vote_counts", "--fix", stdout=out)

        assert "Fixed 1 skin(s)." in out.getvalue()
        assert _counters(skin) == (2, 1)

    def test_command_reports_clean(self):
        SkinFactory()
        out = StringIO()

        call_command("audit_vote_counts", stdout=out)

        assert "All vote counters match" in out.getvalue()

    def test_fix_skips_a_skin_deleted_since_the_count(self):
        skin = self._drifted_skin()
        drifted = recount_votes()
        skin.delete()

        assert fix_vote_counts(drifted) == 0
