"""Custom error pages render with the site layout (templates/error_base.html)."""

import pytest


@pytest.mark.django_db
def test_404_page_renders_with_site_layout(client, settings):
    settings.DEBUG = False  # Django only uses 404.html when DEBUG is off

    response = client.get("/this-page-does-not-exist/")

    assert response.status_code == 404
    assert b"Page not found" in response.content
    assert b"css/errors.css" in response.content
