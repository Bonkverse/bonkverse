"""Django field validators for bonk.io values.

The rules themselves live in core/bonk/ (no Django there); these wrap them as
model-field validators that raise ValidationError.
"""

from django.core.exceptions import ValidationError

from core.bonk import BonkUsername, InvalidUsername


def validate_bonk_username(value: str) -> None:
    """Model-field validator for bonk.io usernames (rules in core/bonk/usernames.py)."""
    try:
        BonkUsername.validate(value)
    except InvalidUsername as error:
        raise ValidationError(str(error)) from None
