"""Rate limiting: who a request is from, how many it may make, and what it sees when limited.

Covers core/client_ip.py and core/ratelimits.py. The production request path is
visitor -> Cloudflare -> Railway edge -> Django; tests fake it with headers.
"""

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import path
from django_ratelimit.decorators import ratelimit

from bonk_skin_search import urls as site_urls
from core.client_ip import client_ip

pytestmark = pytest.mark.django_db

RAILWAY_PROXY = "100.64.0.7"  # REMOTE_ADDR in production: Railway's internal proxy
CLOUDFLARE_EDGE_V4 = "172.70.42.10"  # inside 172.64.0.0/13
CLOUDFLARE_EDGE_V6 = "2606:4700:10::ac43:1"  # inside 2606:4700::/32
VISITOR_A = "203.0.113.10"
VISITOR_B = "198.51.100.20"


def _via_cloudflare(visitor: str, edge: str = CLOUDFLARE_EDGE_V4) -> dict:
    """META for a request that went visitor -> Cloudflare -> Railway -> Django."""
    return {
        "REMOTE_ADDR": RAILWAY_PROXY,
        "HTTP_X_REAL_IP": edge,
        "HTTP_CF_CONNECTING_IP": visitor,
    }


@pytest.fixture
def behind_proxies(settings):
    settings.TRUST_PROXY_HEADERS = True


# ── Which IP is this request from? ────────────────────────────────────────────


class TestClientIp:
    def _ip(self, **meta):
        return client_ip(RequestFactory().get("/", **meta))

    def test_local_dev_uses_socket_address_and_ignores_headers(self, settings):
        settings.TRUST_PROXY_HEADERS = False

        ip = self._ip(REMOTE_ADDR="127.0.0.1", HTTP_X_REAL_IP="1.2.3.4")

        assert ip == "127.0.0.1"

    def test_cloudflare_request_uses_visitor_not_proxy(self, behind_proxies):
        assert self._ip(**_via_cloudflare(VISITOR_A)) == VISITOR_A

    def test_cloudflare_ipv6_edge_is_recognized(self, behind_proxies):
        assert self._ip(**_via_cloudflare(VISITOR_A, edge=CLOUDFLARE_EDGE_V6)) == VISITOR_A

    def test_direct_to_railway_uses_railway_reported_ip(self, behind_proxies):
        # Someone hitting *.up.railway.app directly, not through Cloudflare.
        ip = self._ip(REMOTE_ADDR=RAILWAY_PROXY, HTTP_X_REAL_IP=VISITOR_B)

        assert ip == VISITOR_B

    def test_forged_cloudflare_header_is_ignored_off_cloudflare(self, behind_proxies):
        # Railway overwrites X-Real-IP, so a direct caller cannot pretend to be
        # Cloudflare; their forged CF-Connecting-IP must not pick their bucket.
        ip = self._ip(
            REMOTE_ADDR=RAILWAY_PROXY,
            HTTP_X_REAL_IP=VISITOR_B,
            HTTP_CF_CONNECTING_IP="1.1.1.1",
        )

        assert ip == VISITOR_B

    @pytest.mark.parametrize("bad", ["", "not-an-ip", "999.1.1.1"])
    def test_bad_cloudflare_header_falls_back_to_edge(self, behind_proxies, bad):
        meta = {**_via_cloudflare(VISITOR_A), "HTTP_CF_CONNECTING_IP": bad}

        assert self._ip(**meta) == CLOUDFLARE_EDGE_V4

    @pytest.mark.parametrize("bad", ["", "garbage", "1.2.3"])
    def test_missing_or_bad_real_ip_falls_back_to_socket(self, behind_proxies, bad):
        assert self._ip(REMOTE_ADDR=RAILWAY_PROXY, HTTP_X_REAL_IP=bad) == RAILWAY_PROXY


# ── Limits are per visitor, not shared ────────────────────────────────────────


def test_visitors_behind_the_same_proxy_get_separate_limits(client, settings, behind_proxies):
    """Regression: every visitor arrived from Railway's proxy address, so they all
    shared one bucket and one person's searches blocked everyone else."""
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "search": "3/m"}
    for _ in range(3):
        assert client.get("/search/?q=x", **_via_cloudflare(VISITOR_A)).status_code == 200

    assert client.get("/search/?q=x", **_via_cloudflare(VISITOR_A)).status_code == 429
    assert client.get("/search/?q=x", **_via_cloudflare(VISITOR_B)).status_code == 200


def test_home_page_allows_normal_browsing(client):
    """Regression: the home page allowed only 5 views a minute."""
    codes = {client.get("/").status_code for _ in range(20)}

    assert codes == {200}


def test_search_allows_trying_every_sort_and_mode(client):
    """Regression: search allowed 10 a minute, so trying the sort/mode
    combinations (each one is a page load) hit the limit almost immediately."""
    urls = [
        f"/search/?q=dog&mode={mode}&sort={sort}"
        for mode in ("relevance", "name", "creator", "tags", "description")
        for sort in ("relevance", "newest", "favorites", "upvotes")
    ]

    codes = {client.get(url).status_code for url in urls}

    assert codes == {200}


# ── What a limited visitor sees ───────────────────────────────────────────────


class TestTooManyRequests:
    @pytest.fixture(autouse=True)
    def _tight_search(self, settings):
        settings.RATE_LIMITS = {**settings.RATE_LIMITS, "search": "2/m"}

    def _exhaust(self, client, url, **extra):
        for _ in range(2):
            client.get(url, **extra)
        return client.get(url, **extra)

    def test_page_gets_friendly_429_with_retry_after(self, client):
        response = self._exhaust(client, "/search/?q=x")

        assert response.status_code == 429
        assert 0 < int(response["Retry-After"]) <= 60
        assert b"Slow down" in response.content
        assert b"403 Forbidden" not in response.content

    def test_page_view_gets_live_countdown_that_reloads(self, client):
        response = self._exhaust(client, "/search/?q=x")
        seconds = response["Retry-After"]

        assert f'data-seconds="{seconds}"'.encode() in response.content
        assert b'data-reload="true"' in response.content
        assert b"js/ratelimit.js" in response.content

    def test_api_gets_json_error_contract(self, client):
        response = self._exhaust(client, "/api/players/search/?q=x")

        assert response.status_code == 429
        assert response.json() == {
            "ok": False,
            "error": "rate_limited",
            "retry_after": int(response["Retry-After"]),
        }

    def test_ajax_request_gets_json(self, client):
        response = self._exhaust(client, "/search/?q=x", HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        assert response.status_code == 429
        assert response.json()["error"] == "rate_limited"

    def test_limits_are_per_view(self, client):
        self._exhaust(client, "/search/?q=x")

        assert client.get("/").status_code == 200


def test_limits_can_be_changed_from_settings(client, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "browse": "1/m"}

    assert client.get("/categories/").status_code == 200
    assert client.get("/categories/").status_code == 429


def test_login_limit_counts_only_attempts_not_page_views(client, settings, mocked_http):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "login": "1/h"}
    mocked_http.post(
        "https://bonk2.io/scripts/login_legacy.php", json={"r": "fail", "e": "password"}
    )

    assert client.get("/login/").status_code == 200
    assert client.get("/login/").status_code == 200
    assert client.post("/login/", {"username": "a", "password": "b"}).status_code == 200
    response = client.post("/login/", {"username": "a", "password": "b"})
    assert response.status_code == 429
    # A blocked form submission must never auto-reload: the browser would resubmit
    # the login form. It counts down and says when to submit again instead.
    assert b'data-reload="true"' not in response.content
    assert b"then submit again" in response.content


# ── Views still on the old @ratelimit decorator ───────────────────────────────


@ratelimit(key="ip", rate="1/m", block=True)
def _legacy_view(request):
    return HttpResponse("ok")


# The real routes are included so the 429 page (which renders the navbar) can reverse URLs.
urlpatterns = [path("legacy/", _legacy_view), *site_urls.urlpatterns]


def test_legacy_decorator_also_returns_429_not_403(client, settings):
    """Views not yet moved to core.ratelimits.limit (e.g. the retiring tracker API)
    get the same 429 response through django-ratelimit's middleware."""
    settings.ROOT_URLCONF = __name__

    client.get("/legacy/")
    response = client.get("/legacy/")

    assert response.status_code == 429
    assert b"Slow down" in response.content


# ── manage.py audit_rate_limits ───────────────────────────────────────────────


def test_audit_lists_every_route_with_its_tier(settings):
    from io import StringIO

    from django.core.management import call_command

    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "search": "60/m"}
    out = StringIO()

    call_command("audit_rate_limits", stdout=out)
    text = out.getvalue()

    search_line = next(line for line in text.splitlines() if line.strip().startswith("/search/"))
    assert "search" in search_line and "60/m" in search_line
    login_line = next(line for line in text.splitlines() if line.strip().startswith("/login/"))
    assert "login" in login_line and "POST" in login_line
    assert not any(line.strip().startswith("/api/wins/") for line in text.splitlines())


# Routes allowed to have no tier, each with the PR that removes it from this list.
# Shrink only: the guard test fails if a listed route gains a tier (delete it here)
# or if any route not listed here has no tier (add @limit to it).
UNTIERED_ALLOWED: set[str] = set()  # every route has a tier since RFC-0001 Phase 1


def test_every_route_has_a_rate_limit_tier():
    """New pages and endpoints must ship with @limit(...). Lists the offenders."""
    from skins.management.commands.audit_rate_limits import collect_rows

    untiered = {route for route, _view, tier, _rate, _methods in collect_rows() if tier is None}

    assert untiered - UNTIERED_ALLOWED == set(), "add @limit(...) to these routes"
    assert UNTIERED_ALLOWED - untiered == set(), "now tiered: remove from UNTIERED_ALLOWED"


def test_bonk_login_for_wear_cannot_be_used_to_guess_passwords(
    logged_in_client, settings, mocked_http
):
    """Regression: /api/bonk/login/ had no limit, so a logged-in user could try
    bonk.io passwords through Bonkverse as fast as they liked."""
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "login": "2/h"}
    mocked_http.post(
        "https://bonk2.io/scripts/login_legacy.php", json={"r": "fail", "e": "password"}
    )
    attempt = {"bonk_username": "victim", "bonk_password": "guess"}

    codes = [logged_in_client.post("/api/bonk/login/", attempt).status_code for _ in range(3)]

    assert codes == [401, 401, 429]
