"""Turn site accounts linked to several bonk.io accounts into groups.

Before RFC-0003 phase 5 one site account could hold links to more than one
bonk.io account. Now each bonk.io account is its own site account and a group
ties them together (ADR 0023). For every site account with links to bonk.io
accounts other than its own name, this:

1. finds or creates the site account of each other bonk.io account,
2. moves the link there (its tokens go with it; if that account already has
   its own link to the same bonk.io account, the older of the two is
   dropped),
3. puts them all in one group. The main is the account of the most recently
   connected link (RFC-0003 decisions; BonxBot's main replaces it when its
   links are imported, phase 7).

Favorites, votes, uploads and privacy stay with the site account they were
saved under: the site never recorded which bonk.io account was in use, so
they can't be split.

Dry run by default (counts only, no names); `--run` makes the changes, one
account at a time, each in its own transaction. Safe to run again: accounts
already converted have nothing left to move.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Q

from accounts import groups
from accounts.models import AccountGroup, BonkAccountLink, BonkUser
from accounts.sign_in import site_account_for
from core.bonk import BonkUsername


class Command(BaseCommand):
    help = "Turn site accounts linked to several bonk.io accounts into groups (dry run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--run", action="store_true", help="Make the changes.")

    def handle(self, *args, run=False, **options):
        owners = (
            BonkUser.objects.annotate(
                links=Count("bonk_accounts", filter=Q(bonk_accounts__active=True))
            )
            .filter(links__gt=1)
            .order_by("pk")
        )
        counts = {"site accounts": 0, "links moved": 0, "accounts created": 0, "skipped": 0}
        for owner in owners.iterator():
            moved, created, skipped = self._convert(owner, run=run)
            counts["site accounts"] += 1
            counts["links moved"] += moved
            counts["accounts created"] += created
            counts["skipped"] += skipped
        summary = ", ".join(f"{name}: {n}" for name, n in counts.items())
        if run:
            self.stdout.write(f"Done. {summary}")
        else:
            self.stdout.write(f"Dry run (add --run). Would convert {summary}")

    def _convert(self, owner: BonkUser, *, run: bool) -> tuple[int, int, int]:
        links = list(
            BonkAccountLink.objects.select_related("bonk_player")
            .filter(user=owner, active=True)
            .order_by("connected_at")
        )
        others = [
            link
            for link in links
            if link.bonk_player.username.casefold() != owner.username.casefold()
        ]
        if not others:
            # Several links to its own bonk.io account under different ids:
            # nothing to group.
            return 0, 0, 1
        created = sum(
            1
            for link in others
            if not BonkUser.objects.filter(username__iexact=link.bonk_player.username).exists()
        )
        if not run:
            return len(others), created, 0
        with transaction.atomic():
            accounts = {owner.pk: owner}
            for link in others:
                account = site_account_for(BonkUsername(link.bonk_player.username))
                accounts[account.pk] = account
                existing = BonkAccountLink.objects.filter(
                    user=account, bonk_player=link.bonk_player
                ).first()
                if existing is None:
                    BonkAccountLink.objects.filter(pk=link.pk).update(user=account)
                elif existing.updated_at >= link.updated_at:
                    link.delete()
                else:
                    existing.delete()
                    BonkAccountLink.objects.filter(pk=link.pk).update(user=account)
            newest = max(links, key=lambda link: link.connected_at)
            main = next(
                (
                    account
                    for account in accounts.values()
                    if account.username.casefold() == newest.bonk_player.username.casefold()
                ),
                owner,
            )
            for account in accounts.values():
                if account.pk != main.pk:
                    groups.join(main, account)
            main.refresh_from_db()
            AccountGroup.objects.filter(pk=main.account_group_id).update(main=main)
        return len(others), created, 0
