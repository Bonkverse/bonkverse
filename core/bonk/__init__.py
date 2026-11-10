"""bonk.io concepts as small, typed values.

Owns: the rules for skin codes, bonk.io usernames, avatar slots and the bonk.io
session we keep for a signed-in player.
Does not own: talking to bonk.io (integrations/bonk_api.py) or Django models.

Deliberately free of Django and HTTP so it can become the first piece of a
bonk.io SDK (RFC-0001, "Path to an SDK").
"""

from core.bonk.session import BonkSession
from core.bonk.skin_codes import InvalidSkinCode, ParsedSkin, SkinCode, SkinLayer
from core.bonk.slots import AvatarSlot
from core.bonk.usernames import BonkUsername, InvalidUsername

__all__ = [
    "AvatarSlot",
    "BonkSession",
    "BonkUsername",
    "InvalidSkinCode",
    "InvalidUsername",
    "ParsedSkin",
    "SkinCode",
    "SkinLayer",
]
