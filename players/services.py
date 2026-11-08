"""Changing who sees what on a player profile."""

from __future__ import annotations

from .models import ProfileVisibility


def update_visibility(user, shown: dict[str, bool]) -> ProfileVisibility:
    """Save the user's switches. Sections missing from `shown` become hidden,
    which is how an unticked checkbox arrives from a form."""
    values = {field: bool(shown.get(field)) for field, _, _ in ProfileVisibility.SECTIONS}
    visibility, _ = ProfileVisibility.objects.update_or_create(user=user, defaults=values)
    return visibility
