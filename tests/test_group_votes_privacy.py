"""One vote per person, level 5 to vote, privacy "apply to all", "Also plays
as…" and shared API keys (RFC-0003 phase 5, PR 2).

A person's bonk.io accounts (a group, accounts/groups.py) share one vote per
skin, the latest wins; a new vote needs bonk.io level 5 on the account
casting it.
"""

import pytest

from accounts import groups
from accounts.models import BonkAccountLink
from core.bonk.levels import xp_for_level
from players.models import BonkPlayer, ProfileVisibility
from public_api.keys import create_key
from public_api.models import ApiKey
from skins.models import Skin, SkinVote
from skins.votes import VoteNotAllowed, cast_vote
from tests.factories import SkinFactory, UserFactory

pytestmark = pytest.mark.django_db

_bonk_ids = iter(range(70_000, 80_000))


def _at_level(user, level):
    """Give `user` a linked bonk.io account at `level` (XP as stored at sign-in)."""
    player = BonkPlayer.objects.create(
        bonk_id=next(_bonk_ids), username=user.username, xp=xp_for_level(level)
    )
    BonkAccountLink.objects.create(user=user, bonk_player=player)
    return user


def _group(*accounts):
    for account in accounts[1:]:
        groups.join(accounts[0], account)
    for account in accounts:
        account.refresh_from_db()
    return accounts[0].account_group


def _signed_in(client, *accounts):
    client.force_login(accounts[-1])
    session = client.session
    session[groups.SIGNED_IN_KEY] = [account.pk for account in accounts]
    session.save()
    return client


def _counts(skin):
    return tuple(Skin.objects.filter(pk=skin.pk).values_list("upvotes", "downvotes").get())


class TestOneVotePerPerson:
    def test_another_account_switching_the_vote_leaves_one_vote(self):
        main, alt = _at_level(UserFactory(), 10), _at_level(UserFactory(), 10)
        _group(main, alt)
        skin = SkinFactory()

        cast_vote(main, skin, "up")
        result = cast_vote(alt, skin, "down")

        assert (result.upvotes, result.downvotes) == (0, 1)
        assert list(SkinVote.objects.filter(skin=skin).values_list("user_id", "vote")) == [
            (alt.pk, "down")
        ]

    def test_clicking_the_groups_vote_again_takes_it_back(self):
        main, alt = _at_level(UserFactory(), 10), _at_level(UserFactory(), 10)
        _group(main, alt)
        skin = SkinFactory()
        cast_vote(main, skin, "up")

        result = cast_vote(alt, skin, "up")

        assert result.current_vote is None
        assert _counts(skin) == (0, 0)
        assert not SkinVote.objects.filter(skin=skin).exists()

    def test_every_account_sees_the_groups_vote(self, client):
        main, alt = _at_level(UserFactory(), 10), _at_level(UserFactory(), 10)
        _group(main, alt)
        skin = SkinFactory()
        cast_vote(main, skin, "up")
        client.force_login(alt)

        page = client.get(f"/skins/detail/{skin.id}").content.decode()

        assert 'data-vote="up" aria-label="Upvote"\n                  aria-pressed="true"' in page

    def test_votes_get_a_time(self):
        user = _at_level(UserFactory(), 10)
        skin = SkinFactory()

        cast_vote(user, skin, "up")

        assert SkinVote.objects.get(skin=skin).voted_at is not None

    def test_separate_people_still_vote_separately(self):
        a, b = _at_level(UserFactory(), 10), _at_level(UserFactory(), 10)
        skin = SkinFactory()

        cast_vote(a, skin, "up")
        result = cast_vote(b, skin, "up")

        assert result.upvotes == 2


class TestJoiningAGroup:
    def test_where_both_voted_the_groups_vote_stays(self):
        main, alt = _at_level(UserFactory(), 10), _at_level(UserFactory(), 10)
        both, only_alt = SkinFactory(), SkinFactory()
        cast_vote(main, both, "up")
        cast_vote(alt, both, "down")
        cast_vote(alt, only_alt, "up")

        _group(main, alt)

        assert list(SkinVote.objects.filter(skin=both).values_list("user_id", "vote")) == [
            (main.pk, "up")
        ]
        assert _counts(both) == (1, 0)
        # Votes where the group hadn't voted are untouched.
        assert SkinVote.objects.filter(skin=only_alt, user=alt).exists()
        assert _counts(only_alt) == (1, 0)


class TestLevelFive:
    def test_below_level_5_a_new_vote_is_refused(self):
        user = _at_level(UserFactory(), 4)
        skin = SkinFactory()

        with pytest.raises(VoteNotAllowed) as refusal:
            cast_vote(user, skin, "up")

        assert "level 5" in refusal.value.message and "level 4" in refusal.value.message
        assert _counts(skin) == (0, 0)

    def test_the_api_says_why(self, client):
        user = _at_level(UserFactory(), 2)
        client.force_login(user)

        response = client.post(f"/api/skins/{SkinFactory().id}/vote/", {"vote": "up"})

        assert response.status_code == 403
        assert "Reach level 5" in response.json()["message"]

    def test_the_buttons_are_disabled_with_the_reason(self, client):
        client.force_login(_at_level(UserFactory(), 3))

        page = client.get(f"/skins/detail/{SkinFactory().id}").content.decode()

        assert 'aria-describedby="vote-blocked"' in page
        assert page.count(" disabled>") >= 2
        assert "Reach level 5 on bonk.io to vote. You&#x27;re level 3." in page

    def test_an_old_vote_can_still_be_taken_back(self):
        """Votes from before the rule stay, and their owners can remove them."""
        user = _at_level(UserFactory(), 2)
        skin = SkinFactory(upvotes=1)
        SkinVote.objects.create(user=user, skin=skin, vote="up")

        result = cast_vote(user, skin, "up")

        assert result.current_vote is None
        assert _counts(skin) == (0, 0)

    def test_an_account_with_no_stored_level_can_vote(self):
        """Signed in before Bonkverse kept XP; every new sign-in stores it."""
        result = cast_vote(UserFactory(), SkinFactory(), "up")

        assert result.current_vote == "up"

    def test_level_5_can_vote(self):
        assert cast_vote(_at_level(UserFactory(), 5), SkinFactory(), "down").downvotes == 1


class TestPrivacyApplyToAll:
    URL = "/settings/profile/apply-to-all/"

    def test_copies_this_accounts_switches_to_the_others(self, client):
        main, alt, third = UserFactory(), UserFactory(), UserFactory()
        _group(main, alt, third)
        ProfileVisibility.objects.create(user=alt, activity=False, friends=False)
        _signed_in(client, main, alt)

        client.post(self.URL)

        for account in (main, third):
            saved = ProfileVisibility.objects.get(user=account)
            assert (saved.activity, saved.friends, saved.skins) == (False, False, True)

    def test_needs_the_main_signed_in_here(self, client):
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        ProfileVisibility.objects.create(user=alt, activity=False)
        _signed_in(client, alt)

        client.post(self.URL)

        assert not ProfileVisibility.objects.filter(user=main).exists()

    def test_only_shown_with_more_than_one_account(self, logged_in_client):
        page = logged_in_client.get("/settings/profile/").content.decode()

        assert "Apply these to all my accounts" not in page


class TestAlsoPlaysAs:
    def test_off_by_default(self, client):
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)

        page = client.get(f"/player/{main.username}/").content.decode()

        assert "Also plays as" not in page

    def test_on_lists_the_other_accounts_on_each_profile(self, client):
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        _signed_in(client, main)

        client.post("/accounts/show-on-profiles/", {"show": "1"})
        page = client.get(f"/player/{alt.username}/").content.decode()

        assert "Also plays as" in page
        assert f"/player/{main.username}/" in page

    def test_needs_the_main_signed_in_here(self, client):
        main, alt = UserFactory(), UserFactory()
        group = _group(main, alt)
        _signed_in(client, alt)

        client.post("/accounts/show-on-profiles/", {"show": "1"})

        group.refresh_from_db()
        assert group.show_on_profiles is False


class TestSharedApiKeys:
    def _key(self, owner, name="k"):
        key, _ = create_key(name=name, owner=owner, contact=owner.username)
        return key

    def test_every_account_sees_and_can_revoke_the_groups_keys(self, client):
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        key = self._key(main, "main's bot")
        client.force_login(alt)

        page = client.get("/developers/keys/").content.decode()
        assert "main&#x27;s bot" in page or "main's bot" in page
        assert f"by {main.username}" in page

        client.post(f"/developers/keys/{key.prefix}/revoke/")
        key.refresh_from_db()
        assert key.is_active is False

    def test_someone_elses_key_stays_out_of_reach(self, client):
        key = self._key(UserFactory())
        client.force_login(UserFactory())

        client.post(f"/developers/keys/{key.prefix}/revoke/")

        key.refresh_from_db()
        assert key.is_active is True

    def test_the_key_limit_counts_the_whole_group(self, settings):
        from public_api import services

        settings.PUBLIC_API_MAX_KEYS_PER_USER = 2
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        self._key(main)
        self._key(main)
        services.accept_terms(alt)

        with pytest.raises(services.PortalError) as refusal:
            services.create_own_key(alt, name="one more")

        assert refusal.value.code == "too_many_keys"
        assert ApiKey.objects.filter(owner=alt).count() == 0
