"""Startup checks for configuration read from the environment.

Owns: rejecting malformed connection settings when the app starts, so a bad value
fails the deploy instead of failing every request.
Does not own: reading the settings themselves (bonk_skin_search/settings.py).

Imported by settings.py, so it must not import anything that needs Django set up.
Error messages never include the value: connection URLs hold passwords.
"""

from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

REDIS_SCHEMES = ("redis", "rediss", "unix")


def check_redis_url(url: str) -> None:
    """Raise ImproperlyConfigured if `url` can't be used as a Redis connection URL.

    redis-py only parses the URL when it first connects, i.e. inside a request.
    On 2026-11-03 a password containing a URL-special character ("/", "#", "?",
    "@") made every request fail with "Port could not be cast to integer", which
    the cache's ignore-errors setting does not catch. Checking at startup turns
    that into a failed deploy, and Railway keeps the previous one serving.

    Args:
        url: The REDIS_URL value.

    Raises:
        ImproperlyConfigured: Describing what is wrong, without echoing the URL (it holds
            the password).
    """
    hint = (
        "If the password contains characters like / # ? @ :, URL-encode it or use "
        "Railway's ${{Redis.REDIS_URL}} reference."
    )
    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError when the port isn't a number
    except ValueError:
        raise ImproperlyConfigured(
            f"REDIS_URL is not a valid URL (bad host or port). {hint}"
        ) from None

    if parts.scheme not in REDIS_SCHEMES:
        raise ImproperlyConfigured(
            f"REDIS_URL must start with one of {', '.join(REDIS_SCHEMES)}://"
        )
    if parts.scheme == "unix":
        return
    if not parts.hostname:
        raise ImproperlyConfigured(f"REDIS_URL has no host. {hint}")
    if parts.fragment or (parts.query and port is None):
        # A "#" or "?" inside the password cuts the URL short and leaves no port.
        raise ImproperlyConfigured(f"REDIS_URL looks cut short. {hint}")
