"""Root URL conf: mounts each app's routes.

RFC-0001 Phase 5 moves routes out of this file into each app's own `urls.py`,
included here, one app per step. Every path is pinned by
`tests/test_url_snapshot.py`, so a move can't change one.

Order matters: Django answers with the first pattern that matches.
"""

from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from django.conf import settings
from django.conf.urls.static import static

from core.ratelimits import limit


urlpatterns = [
    # Site accounts moved from skins to accounts (RFC-0001 5.5c); old admin
    # bookmarks land on the same page under its new address.
    re_path(
        r"^admin/skins/bonkuser/(?P<rest>.*)$",
        limit("browse")(
            RedirectView.as_view(url="/admin/accounts/bonkuser/%(rest)s", query_string=True)
        ),
    ),
    path("admin/", admin.site.urls),
    # Skins: search, skin pages, browsing, your skins, upload, skin-card APIs
    # and /media/ (skins/urls.py).
    path("", include("skins.urls")),
    # Home, privacy, terms, staff, map decoder (site_pages/, docs/apps/site_pages.md).
    path("", include("site_pages.urls")),
    # Log in and out with bonk.io, /api/me/ (accounts/, docs/apps/accounts.md).
    path("", include("accounts.urls")),
    # Public, versioned API for other sites and bots (public_api/, ADR 0011).
    path("api/v1/", include("public_api.urls")),
    # BonxBot's read endpoints, token-authenticated (public_api/views/bot.py).
    path("api/bot/", include("public_api.bot_urls")),
    # Developer portal: API terms and your own API keys (public_api/, ADR 0012).
    path("developers/", include("public_api.portal_urls")),
    # Leaderboards: one page per stats/leaderboards.py entry (stats/, docs/apps/stats.md).
    path("", include("stats.urls")),
    # Discord server directory (communities/, docs/apps/communities.md).
    path("", include("communities.urls")),
    # Player profiles, directory, search APIs, social stats, XP calculator (players/).
    path("", include("players.urls")),
]

# Static files (WhiteNoise serves them in production; this covers DEBUG).
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
