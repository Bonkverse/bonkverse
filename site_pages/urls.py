"""Routes for the site's own pages. Paths and names are unchanged from when
these lived in skins/ (pinned by tests/test_url_snapshot.py)."""

from django.urls import path

from .views import pages, tools

urlpatterns = [
    path("", pages.home, name="home"),
    path("staff/", pages.staff_page, name="staff"),
    path("privacy/", pages.privacy, name="privacy"),
    path("terms/", pages.terms, name="terms"),
    path("tools/map-decode/", tools.map_decode_page, name="map_decode_page"),
    path("api/tools/map-decode/", tools.api_map_decode, name="api_map_decode"),
]
