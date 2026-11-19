"""The privacy policy and terms of service (site_pages/privacy.html, terms.html)."""

import re

import pytest
from django.urls import reverse


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name,heading", [("privacy", "Privacy Policy"), ("terms", "Terms of Service")]
)
def test_legal_pages_are_on_components_with_contents(client, name, heading):
    html = client.get(reverse(f"site_pages:{name}")).content.decode()
    assert 'class="content site-page"' in html and "site_pages/css/legal.css" in html
    assert f"<h1>{heading}</h1>" in html and 'class="legal__toc"' in html
    # Every contents link has a section to go to.
    for anchor in re.findall(r'<li><a href="#([^"]+)">', html):
        assert f'id="{anchor}"' in html
