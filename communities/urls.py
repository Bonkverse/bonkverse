"""Routes for the Discord server directory. Paths and names are unchanged from
when these lived in skins/ (pinned by tests/test_url_snapshot.py)."""

from django.urls import path

from .views import pages, submit

urlpatterns = [
    path("serverlist/", pages.server_list, name="list"),
    path("<uuid:server_id>/", pages.server_detail, name="detail"),
    path("submit/", pages.submit_server_page, name="submit_server"),
    path("api/discords/submit/", submit.submit_server, name="api_submit_server"),
]
