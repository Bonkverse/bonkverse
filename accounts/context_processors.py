"""Template context every page gets from the accounts app.

Owns: `viewer_accounts`, the signed-in visitor's other bonk.io accounts for
the header's account switcher (RFC-0003 phase 5, groups.py). Lazy, and
empty without a query for players with one account (most of them).
"""

from django.utils.functional import SimpleLazyObject

from players import selectors as player_selectors

from . import groups


def viewer_accounts(request):
    """{"viewer_accounts": [...]}: the group's accounts other than the one in
    use, each with its worn-skin thumbnail (cached per account), or []."""

    def build():
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or user.account_group_id is None:
            return []
        rows = [row for row in groups.accounts_for(request) if not row["active"]]
        by_id = {account.pk: account for account in groups.members(user)}
        for row in rows:
            account = by_id.get(row["id"])
            row["thumbnail"] = (
                player_selectors.user_skin_avatars(account).get("thumbnail") if account else None
            )
        return rows

    return {"viewer_accounts": SimpleLazyObject(build)}
