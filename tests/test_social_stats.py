"""The Community stats page (/social-stats/, players/social_stats.py)."""

import pytest
from django.urls import reverse

from players.models import BonkPlayer, Friendship


@pytest.mark.django_db
def test_community_stats_follow_the_design_review(client):
    """Numbers with separators, plain names, no graph density, no emoji,
    players linked to their profiles, nobody with zero friends ranked."""
    a = BonkPlayer.objects.create(bonk_id=5, username="Saucy Tulip", last_friend_count=1234)
    b = BonkPlayer.objects.create(bonk_id=6, username="Lonely", last_friend_count=0)
    Friendship.objects.create(player_low=a, player_high=b)
    html = client.get(reverse("players:social_stats")).content.decode()
    assert 'class="content site-page"' in html
    assert ">1,234<" in html and "Friendships" in html
    assert "density" not in html.lower() and "Friendship edges" not in html
    assert "🌐" not in html
    assert 'href="/player/Saucy%20Tulip/"' in html
    most_friends = html.split('id="ss-connected"')[1].split("</section>")[0]
    assert "Lonely" not in most_friends
