"""The skin each player last wore in game.

Owns: storing a player's worn skin (`BonkPlayer.worn_skin_*`) when we see it,
with the newest sighting winning. Today the sightings are the player's own
bonk.io login (the active slot's skin) and a successful wear from Bonkverse
into the active slot.
Does not own: reading the login reply (integrations/bonk_api.py), wearing
skins (skins/wear_skin.py) or showing the skin anywhere.
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from core.bonk import InvalidSkinCode, SkinCode

from .models import BonkPlayer, WornSkinSource

logger = logging.getLogger(__name__)


def record_worn_skin(
    bonk_id: int | None,
    skin_code: str | None,
    source: WornSkinSource,
    *,
    seen_at: datetime | None = None,
) -> bool:
    """Remember that the player with `bonk_id` wore `skin_code` at `seen_at`.

    Kept only if it is at least as new as what is stored, so an older
    sighting arriving late can't replace a newer one. The code is stored
    URL-decoded (plain base64), and only if it parses as a skin. Never
    raises for bad input: a missing player or code, or a code that isn't a
    skin, stores nothing.

    Args:
        bonk_id: The player's bonk.io account id.
        skin_code: The skin code as bonk.io or the page sent it.
        source: Where it was seen.
        seen_at: When; now if omitted.

    Returns:
        Whether it was stored.
    """
    if bonk_id is None or not skin_code:
        return False
    code = SkinCode(skin_code)
    try:
        code.parse()
    except InvalidSkinCode as error:
        # The reason only; codes can be long and say nothing useful in a log.
        logger.warning(
            "worn skin from %s for bonk_id=%s isn't a skin code (%s); not stored",
            source,
            bonk_id,
            error.reason,
        )
        return False

    seen_at = seen_at or timezone.now()
    # One UPDATE with the age check in its WHERE, so two sightings racing
    # each other can't leave the older one stored.
    stored = (
        BonkPlayer.objects.filter(bonk_id=bonk_id)
        .filter(Q(worn_skin_seen_at__isnull=True) | Q(worn_skin_seen_at__lte=seen_at))
        .update(
            worn_skin_code=code.decoded,
            worn_skin_seen_at=seen_at,
            worn_skin_source=source,
            updated_at=timezone.now(),
        )
    )
    return stored > 0
