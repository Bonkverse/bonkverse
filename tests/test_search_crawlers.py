"""Requests claiming to be a search engine's crawler must be one
(core/search_crawlers.py). DNS is faked here; the check is the one Google and
Bing document: reverse DNS in their domain, and forward DNS back to the IP.
"""

import socket
import time

import pytest
from django.core.cache import cache

from core import search_crawlers

pytestmark = pytest.mark.django_db

GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
BINGBOT_UA = "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:160.0) Gecko/20100101 Firefox/160.0"


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()


@pytest.fixture
def dns(monkeypatch):
    """Fake DNS: reverse = {ip: hostname}, forward = {hostname: [ips]}."""
    table = {"reverse": {}, "forward": {}, "calls": 0}

    def gethostbyaddr(ip):
        table["calls"] += 1
        if ip not in table["reverse"]:
            raise socket.herror("no PTR")
        return (table["reverse"][ip], [], [ip])

    def getaddrinfo(host, port):
        if host not in table["forward"]:
            raise socket.gaierror("no such host")
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in table["forward"][host]
        ]

    monkeypatch.setattr(search_crawlers.socket, "gethostbyaddr", gethostbyaddr)
    monkeypatch.setattr(search_crawlers.socket, "getaddrinfo", getaddrinfo)
    return table


def _get(client, ua, ip="66.249.66.1"):
    return client.get("/", HTTP_USER_AGENT=ua, REMOTE_ADDR=ip)


def test_real_googlebot_gets_in(client, dns):
    dns["reverse"]["66.249.66.1"] = "crawl-66-249-66-1.googlebot.com"
    dns["forward"]["crawl-66-249-66-1.googlebot.com"] = ["66.249.66.1"]
    assert _get(client, GOOGLEBOT_UA).status_code == 200


def test_fake_googlebot_from_an_ordinary_address_is_refused(client, dns):
    dns["reverse"]["203.0.113.9"] = "203-0-113-9.dsl.example-isp.net"
    response = _get(client, GOOGLEBOT_UA, ip="203.0.113.9")
    assert response.status_code == 403
    assert b"search engine" in response.content


@pytest.mark.parametrize(
    "hostname", ["googlebot.com.evil.net", "evilgooglebot.com", "googlebot.co"]
)
def test_lookalike_reverse_names_are_refused(client, dns, hostname):
    dns["reverse"]["203.0.113.9"] = hostname
    dns["forward"][hostname] = ["203.0.113.9"]
    assert _get(client, GOOGLEBOT_UA, ip="203.0.113.9").status_code == 403


def test_a_google_name_that_doesnt_point_back_is_refused(client, dns):
    # Anyone can set their own IP's reverse DNS to a google.com name; the
    # forward lookup is what proves it.
    dns["reverse"]["203.0.113.9"] = "crawl-66-249-66-1.googlebot.com"
    dns["forward"]["crawl-66-249-66-1.googlebot.com"] = ["66.249.66.1"]
    assert _get(client, GOOGLEBOT_UA, ip="203.0.113.9").status_code == 403


def test_no_reverse_dns_is_refused(client, dns):
    assert _get(client, GOOGLEBOT_UA, ip="203.0.113.9").status_code == 403


def test_bingbot_is_checked_against_bings_domain(client, dns):
    dns["reverse"]["157.55.39.1"] = "msnbot-157-55-39-1.search.msn.com"
    dns["forward"]["msnbot-157-55-39-1.search.msn.com"] = ["157.55.39.1"]
    assert _get(client, BINGBOT_UA, ip="157.55.39.1").status_code == 200
    # Bing's name is no good for a request claiming Googlebot.
    assert _get(client, GOOGLEBOT_UA, ip="157.55.39.1").status_code == 403


def test_ipv6_googlebot(client, dns):
    ip = "2001:4860:4801:10::1"
    dns["reverse"][ip] = "crawl-2001-4860-4801-10--1.googlebot.com"
    dns["forward"]["crawl-2001-4860-4801-10--1.googlebot.com"] = [ip]
    assert _get(client, GOOGLEBOT_UA, ip=ip).status_code == 200


def test_ordinary_visitors_cost_no_dns_lookup(client, dns):
    assert _get(client, BROWSER_UA, ip="203.0.113.9").status_code == 200
    assert dns["calls"] == 0


def test_the_answer_is_cached_per_address(client, dns):
    _get(client, GOOGLEBOT_UA, ip="203.0.113.9")
    _get(client, GOOGLEBOT_UA, ip="203.0.113.9")
    assert dns["calls"] == 1


def test_slow_dns_lets_the_request_through_and_isnt_retried_at_once(client, monkeypatch):
    calls = []

    def slow(ip):
        calls.append(ip)
        time.sleep(search_crawlers.DNS_TIMEOUT_S + 0.5)
        raise socket.herror("late")

    monkeypatch.setattr(search_crawlers.socket, "gethostbyaddr", slow)
    assert _get(client, GOOGLEBOT_UA, ip="203.0.113.9").status_code == 200
    assert _get(client, GOOGLEBOT_UA, ip="203.0.113.9").status_code == 200
    assert len(calls) == 1


def test_can_be_turned_off(client, dns, settings):
    settings.BLOCK_FAKE_SEARCH_CRAWLERS = False
    assert _get(client, GOOGLEBOT_UA, ip="203.0.113.9").status_code == 200
    assert dns["calls"] == 0


@pytest.mark.parametrize(
    "ua, name",
    [
        (GOOGLEBOT_UA, "Googlebot"),
        ("Googlebot-Image/1.0", "Googlebot"),
        (BINGBOT_UA, "Bingbot"),
        ("Mozilla/5.0 (Macintosh) Safari (Applebot/0.1)", "Applebot"),
        (BROWSER_UA, None),
        ("Discordbot/2.0", None),  # link previews aren't search crawlers
    ],
)
def test_which_user_agents_are_checked(ua, name):
    crawler = search_crawlers.claimed_crawler(ua)
    assert (crawler.name if crawler else None) == name
