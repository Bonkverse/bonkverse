"""Template context every page gets from the skins app.

Owns: `can_moderate`, whether the header's account menu shows "Skin reports"
(/moderation/). One query for a signed-in non-superuser, none otherwise;
lazy, so pages that never show the menu make none. The page itself still
checks the full permission (core.auth_guards.permission_required).
"""

from django.contrib.auth.models import Permission
from django.db.models import Q
from django.utils.functional import SimpleLazyObject


def _can_moderate(user) -> bool:
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    # user.has_perm would load all of the user's and their groups' permissions
    # (two queries) on every page; this asks for the one permission in one.
    return (
        Permission.objects.filter(content_type__app_label="skins", codename="moderate_skins")
        .filter(Q(group__user=user) | Q(user=user))
        .exists()
    )


def moderation(request):
    return {"can_moderate": SimpleLazyObject(lambda: _can_moderate(request.user))}
