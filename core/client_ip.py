"""Resolve the real visitor IP behind Cloudflare and Railway.

Owns: the one definition of "which IP did this request come from", used by every
rate limit (settings.RATELIMIT_IP_META_KEY) and anything else that needs it.
Does not own: rate-limit policy (see core/ratelimits.py).

Production path: visitor -> Cloudflare -> Railway edge -> gunicorn -> Django.

- REMOTE_ADDR is Railway's internal proxy (100.64.0.0/10): the same few addresses
  for every visitor. Keying limits on it puts the whole site in one shared bucket.
- Railway's edge overwrites X-Real-IP with the address that connected to it, so a
  caller cannot forge it.
- When that address is a Cloudflare edge server, Cloudflare's CF-Connecting-IP
  holds the visitor. It is trusted only then; a request sent straight to the
  *.up.railway.app domain cannot pick its own bucket by forging the header.

Header trust is controlled by settings.TRUST_PROXY_HEADERS (on in production).
Locally there is no proxy, so the socket address is used and headers are ignored.
"""

from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

from django.conf import settings

# Cloudflare's published edge ranges: https://www.cloudflare.com/ips/
# (unchanged since 2023-09-28). If Cloudflare adds a range, visitors arriving
# through it are limited by the edge address instead, which is safe, just coarser.
CLOUDFLARE_NETWORKS = tuple(
    ip_network(cidr)
    for cidr in (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)


def _parse_ip(value: str) -> IPv4Address | IPv6Address | None:
    """Parse one IP address, unwrapping IPv4-mapped IPv6. None if invalid."""
    try:
        address = ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def is_cloudflare(address: IPv4Address | IPv6Address) -> bool:
    """True if the address belongs to one of Cloudflare's edge networks."""
    return any(
        address in network for network in CLOUDFLARE_NETWORKS if network.version == address.version
    )


def client_ip(request) -> str:
    """Return the visitor's IP address for this request.

    Args:
        request: A Django HttpRequest.

    Returns:
        The visitor IP as a string. Falls back to the next most specific address
        when a header is missing or malformed, never raises.
    """
    socket_ip = request.META.get("REMOTE_ADDR", "")
    if not getattr(settings, "TRUST_PROXY_HEADERS", False):
        return socket_ip

    edge = _parse_ip(request.META.get("HTTP_X_REAL_IP", ""))
    if edge is None:
        return socket_ip

    if is_cloudflare(edge):
        visitor = _parse_ip(request.META.get("HTTP_CF_CONNECTING_IP", ""))
        if visitor is not None:
            return str(visitor)

    return str(edge)
