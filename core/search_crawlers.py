"""Refusing requests that claim to be a search engine's crawler but aren't.

Owns: which user agents count as which search engine's crawler, checking a
claim the way the search engines document (reverse DNS of the visitor IP must
end in their domain, and that name must resolve back to the same IP), caching
the answer per IP, and the middleware that answers fakes with 403.
Does not own: the visitor IP (core/client_ip.py) or the AI crawlers Cloudflare
already blocks by name (its managed robots.txt and "Block AI bots").

Why: a scraper can send "Googlebot" in its user agent to look welcome. On
2026-11-25 a request claiming Googlebot from a non-Google IP got 200, while
GPTBot got 403 from Cloudflare. Real Googlebot, Bingbot and the rest still get
in: only claims that their own DNS contradicts are refused.

If DNS can't answer in time, the request is let through (not cached for
long): briefly serving a fake is better than turning away the real Googlebot.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseForbidden

from core.client_ip import client_ip
from core.pseudonym import pseudonym

logger = logging.getLogger(__name__)

DNS_TIMEOUT_S = 1.5
VERIFIED_TTL = 24 * 3600
FAKE_TTL = 24 * 3600
UNKNOWN_TTL = 5 * 60


@dataclass(frozen=True)
class Crawler:
    name: str
    token: str  # lowercase substring of the user agent
    domains: tuple[str, ...]  # its reverse-DNS names end in one of these


# From each search engine's documentation on verifying its crawler.
CRAWLERS = (
    Crawler("Googlebot", "googlebot", ("googlebot.com", "google.com")),
    Crawler("Bingbot", "bingbot", ("search.msn.com",)),
    Crawler("Applebot", "applebot", ("applebot.apple.com",)),
    Crawler("YandexBot", "yandexbot", ("yandex.ru", "yandex.net", "yandex.com")),
)

_dns = ThreadPoolExecutor(max_workers=4, thread_name_prefix="crawler-dns")


def claimed_crawler(user_agent: str) -> Crawler | None:
    """The search engine this user agent claims to be, if any."""
    ua = (user_agent or "").lower()
    return next((c for c in CRAWLERS if c.token in ua), None)


def _in_domains(hostname: str, domains: tuple[str, ...]) -> bool:
    host = hostname.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


def _lookup(ip: str, domains: tuple[str, ...]) -> bool:
    """Reverse DNS in the crawler's domains, and forward DNS back to `ip`."""
    try:
        hostname = socket.gethostbyaddr(ip)[0]
    except OSError:
        return False  # no reverse DNS at all: not a search engine's crawler
    if not _in_domains(hostname, domains):
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except OSError:
        return False
    wanted = ipaddress.ip_address(ip)
    return any(ipaddress.ip_address(a.split("%")[0]) == wanted for a in addresses)


def verify(crawler: Crawler, ip: str) -> bool | None:
    """True if `ip` really is `crawler`, False if it's a fake, None if DNS
    couldn't answer in time. Cached per crawler and IP."""
    key = f"crawler:{crawler.name}:{ip}"
    cached = cache.get(key)
    if cached is not None:
        return None if cached == "unknown" else cached == "real"
    try:
        real = _dns.submit(_lookup, ip, crawler.domains).result(timeout=DNS_TIMEOUT_S)
    except FutureTimeout:
        cache.set(key, "unknown", UNKNOWN_TTL)  # don't stall every request from it
        return None
    cache.set(key, "real" if real else "fake", VERIFIED_TTL if real else FAKE_TTL)
    return real


class FakeSearchCrawlerMiddleware:
    """403 for requests whose user agent claims a search engine's crawler
    that the search engine's own DNS doesn't confirm."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "BLOCK_FAKE_SEARCH_CRAWLERS", True):
            crawler = claimed_crawler(request.META.get("HTTP_USER_AGENT", ""))
            if crawler is not None:
                ip = client_ip(request)
                if verify(crawler, ip) is False:
                    logger.info(
                        "fake search crawler refused | claims=%s | ip=%s",
                        crawler.name,
                        pseudonym("ip", ip),
                    )
                    return HttpResponseForbidden(
                        "This request claims to be a search engine's crawler, "
                        "but its address doesn't belong to that search engine.",
                        content_type="text/plain",
                    )
        return self.get_response(request)
