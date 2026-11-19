"""The team page (/staff/, site_pages/staff.html)."""

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_team_page_follows_the_design_review(client):
    html = client.get(reverse("site_pages:staff")).content.decode()
    assert 'class="content site-page"' in html
    assert "<h1>The team</h1>" in html and "🌟" not in html
    # No raw search URLs in bios; a profile and skins link instead.
    assert "bonkverse.io/search/" not in html
    assert 'href="/player/ButteredToast55/skins/"' in html
