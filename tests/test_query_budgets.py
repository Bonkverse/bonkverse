"""Database query budgets for the pages that show skin cards.

Two rules per page, logged out and logged in:
- **No per-card queries:** the page makes the same number of queries with 3
  skins as with 30. A card that asks the database for its own vote or
  favorite state (the old search page did, 100+ queries for 50 cards) fails
  this.
- **A budget:** at most the number of queries measured when this was
  written (2026-11-05). Lowering it is welcome: update the number. Raising it
  needs a reason in the PR.

Phase 3 replaces every card template with one `_skin_card.html` fed by one
decoration service; these keep that rewrite honest.
"""

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from skins.models import SkinVote
from tests.factories import SkinFactory, UserFactory

pytestmark = pytest.mark.django_db

FEW, MANY = 3, 30
OWNER = "Budget Tester"

# page: (logged-out budget, logged-in budget). None = login required.
# Search's count includes 6 queries that set and reset its 3 s time limit
# (docs/search.md).
# Signed in includes 1 query (2026-11-22) for whether the account menu shows
# "Skin reports" (skins/context_processors.py: the moderator role).
BUDGETS = {
    # Home (2026-11-18 redesign): 2 skin rows, skin total and today, known
    # players (cached an hour); signed in adds session, user and the header avatar.
    "/": (5, 9),
    "/search/": (16, 21),
    "/search/?q=Test": (14, 19),
    "/search/?sort=favorites": (16, 21),
    "/search/?sort=upvotes": (16, 21),
    # New and categories use the full skin card since 2026-11-09: one more
    # query for favorite counts, plus your votes and favorites when signed in.
    "/new/?period=all": (4, 9),
    "/category/minimalist/": (4, 9),
    "/leaderboards/upvoted/": (2, 5),
    "/leaderboards/favorited/": (2, 5),
    # Signed in, the skin page also reads the voter's bonk.io level (level 5
    # to vote, RFC-0003 phase 5, 2026-11-24).
    "DETAIL": (3, 9),
    # Your own profile's Skins tab (owner cards); signed in as OWNER only.
    "MY_SKINS": (None, 16),
}


def _make_skins(count):
    """`count` skins owned, voted on and favorited by OWNER, so every card has state."""
    user = UserFactory(username=OWNER)
    skins = [SkinFactory(creator=OWNER) for _ in range(count)]
    for skin in skins:
        SkinVote.objects.create(user=user, skin=skin, vote="up")
        skin.favorited_by.add(user)
    return user, skins


def _queries(client, page, skins) -> int:
    url = {"DETAIL": f"/skins/detail/{skins[0].id}", "MY_SKINS": f"/player/{OWNER}/skins/"}.get(
        page, page
    )
    # Cold cache every time, so a value cached by the first request (like the
    # header's skin avatar) can't make the second look cheaper.
    cache.clear()
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url)
    assert response.status_code == 200, url
    return len(ctx.captured_queries)


def _cases():
    for page, (logged_out, logged_in) in BUDGETS.items():
        if logged_out is not None:
            yield pytest.param(page, False, logged_out, id=f"{page} logged-out")
        yield pytest.param(page, True, logged_in, id=f"{page} logged-in")


@pytest.mark.parametrize("page,logged_in,budget", list(_cases()))
def test_queries_do_not_grow_with_cards(client, page, logged_in, budget):
    user, skins = _make_skins(FEW)
    if logged_in:
        client.force_login(user)
    few = _queries(client, page, skins)

    skins += [SkinFactory(creator=OWNER) for _ in range(MANY - FEW)]
    for skin in skins[FEW:]:
        SkinVote.objects.create(user=user, skin=skin, vote="up")
        skin.favorited_by.add(user)
    many = _queries(client, page, skins)

    assert many == few, f"{page}: {few} queries with {FEW} skins, {many} with {MANY}"


@pytest.mark.parametrize("page,logged_in,budget", list(_cases()))
def test_query_budget(client, page, logged_in, budget):
    user, skins = _make_skins(MANY)
    if logged_in:
        client.force_login(user)

    count = _queries(client, page, skins)

    assert count <= budget, f"{page}: {count} queries, budget {budget}"
