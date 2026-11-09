"""Template filters for links that might not exist.

{% load bv_links %}
{% with url=skin.creator|profile_url %}{% if url %}<a href="{{ url }}">…{% endif %}{% endwith %}
"""

from django import template
from django.urls import NoReverseMatch, reverse

register = template.Library()


@register.filter
def profile_url(username):
    """The player profile for a bonk.io username, or "" when there's no
    name or it can't be in a profile URL (a "/" in it, for one)."""
    name = str(username or "").strip()
    if not name:
        return ""
    try:
        return reverse("player_profile", args=[name])
    except NoReverseMatch:
        return ""
