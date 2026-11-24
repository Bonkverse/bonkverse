"""Revoke every stored bonk.io remember-me token, on bonk.io and here.

For when BONK_TOKEN_KEYS may have leaked (docs/operations/runbook.md, "bonk.io
token keys"): a remember-me token works like the player's password until
bonk.io revokes it. Dry run by default; `--run` calls login_clearauto.php
for each one (at most PER_SECOND a second), then deletes it from the link
even if bonk.io couldn't be reached. Players then see "Reconnect" the next
time they wear a skin.

During bonk.io's login pause nothing may be sent (a request seems to restart
the block), and a revoke that isn't sent leaves bonk.io's copy working. So the
command waits for the pause to end before each revoke instead of skipping it.

Prints counts only, never a token or a key. Run it on the `bonkverse`
service after rotating the keys.
"""

import math
import time

from django.core.management.base import BaseCommand

from accounts import bonk_tokens
from accounts.models import BonkAccountLink
from integrations.bonk_api import CLEARAUTO_SCRIPT, rate_limit_cooldowns

PER_SECOND = 2


class Command(BaseCommand):
    help = "Revoke every stored bonk.io remember-me token (dry run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--run", action="store_true", help="Revoke and delete them.")

    def handle(self, *args, run=False, **options):
        links = BonkAccountLink.objects.select_related("bonk_player").filter(
            remember_status=BonkAccountLink.REMEMBER_ACTIVE
        )
        total = links.count()
        if not run:
            self.stdout.write(f"{total} remember-me tokens would be revoked (dry run; add --run)")
            return
        done = 0
        for link in links.iterator(chunk_size=200):
            self._wait_for_bonk()
            bonk_tokens.forget_remember_token(link)
            done += 1
            time.sleep(1 / PER_SECOND)
        self.stdout.write(f"{done} of {total} remember-me tokens revoked and deleted")

    def _wait_for_bonk(self) -> None:
        """Sleep through a login pause (or a pause on login_clearauto.php)."""
        while (left := rate_limit_cooldowns.remaining(CLEARAUTO_SCRIPT)) > 0:
            self.stdout.write(f"bonk.io is pausing logins; waiting {math.ceil(left)}s")
            time.sleep(min(left, 60))
