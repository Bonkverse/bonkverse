"""Re-encrypt every stored bonk.io token with the newest BONK_TOKEN_KEYS key.

Run it after every key rotation (docs/operations/runbook.md, "bonk.io token
keys"). Dry run by default; `--run` writes. (It first ran on 2026-11-14 to
encrypt the tokens stored before ADR 0016.)

What it does, for account links (session and remember-me tokens) and for
unexpired site sessions:
- already encrypted with the newest key: left alone;
- readable with an older key: encrypted with the newest key;
- unreadable (no listed key opens it): with `--run`, removed. A token no key
  can open is useless; the player logs in again when they next need it.

Each write is conditional on the stored value not having changed since it
was read, so a login during the run is never overwritten. Prints counts
only, never a token or a key.
"""

from importlib import import_module

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import BonkAccountLink
from core import token_crypto
from core.bonk import session as bonk_session_keys


class Command(BaseCommand):
    help = (
        "Re-encrypt stored bonk.io tokens with the newest BONK_TOKEN_KEYS key (dry run by default)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--run", action="store_true", help="Write the changes.")

    def handle(self, *args, run=False, **options):
        mode = "" if run else " (dry run: nothing written; add --run)"
        links = self._links(run, "token_encrypted")
        self.stdout.write(f"account links{mode}: " + _summary(links))
        remember = self._links(run, "remember_token_encrypted")
        self.stdout.write(f"remember-me tokens{mode}: " + _summary(remember))
        sessions = self._sessions(run)
        if sessions is None:
            self.stdout.write(
                f"site sessions: skipped ({settings.SESSION_ENGINE} isn't in the database)"
            )
        else:
            self.stdout.write(f"site sessions{mode}: " + _summary(sessions))

    def _links(self, run: bool, field: str) -> dict:
        """Re-encrypt one encrypted column of every account link. Decrypts
        the stored value directly: an expired token is still re-encrypted
        (bonk_token() would read it as None)."""
        counts = _counter()
        rows = BonkAccountLink.objects.exclude(**{f"{field}__isnull": True}).exclude(**{field: ""})
        for pk, stored in rows.values_list("pk", field).iterator(chunk_size=500):
            if token_crypto.is_current(stored):
                counts["current"] += 1
                continue
            token = token_crypto.decrypt(stored)
            new = token_crypto.encrypt(token) if token is not None else None
            counts["redone" if token is not None else "unreadable"] += 1
            if run:
                changes = {field: new}
                if new is None and field == "remember_token_encrypted":
                    changes["remember_status"] = BonkAccountLink.REMEMBER_NONE
                written = BonkAccountLink.objects.filter(pk=pk, **{field: stored}).update(**changes)
                counts["changed meanwhile"] += 1 - written
        return counts

    def _sessions(self, run: bool) -> dict | None:
        if not settings.SESSION_ENGINE.endswith(("backends.db", "backends.cached_db")):
            return None
        store = import_module(settings.SESSION_ENGINE).SessionStore()
        counts = _counter()
        live = Session.objects.filter(expire_date__gt=timezone.now())
        for row in live.iterator(chunk_size=500):
            data = store.decode(row.session_data)
            stored = data.get(bonk_session_keys.TOKEN)
            if not stored:
                continue
            if token_crypto.is_current(stored):
                counts["current"] += 1
                continue
            token = token_crypto.decrypt(stored)
            if token is not None:
                counts["redone"] += 1
                data[bonk_session_keys.TOKEN] = token_crypto.encrypt(token)
            else:
                counts["unreadable"] += 1
                data.pop(bonk_session_keys.TOKEN, None)
                data.pop(bonk_session_keys.TOKEN_EXPIRES, None)
            if run:
                written = Session.objects.filter(
                    session_key=row.session_key, session_data=row.session_data
                ).update(session_data=store.encode(data))
                counts["changed meanwhile"] += 1 - written
        return counts


def _counter() -> dict:
    return {"current": 0, "redone": 0, "unreadable": 0, "changed meanwhile": 0}


def _summary(counts: dict) -> str:
    return (
        f"{counts['current']} already current, {counts['redone']} re-encrypted, "
        f"{counts['unreadable']} unreadable (removed with --run)"
        + (
            f", {counts['changed meanwhile']} skipped (changed during the run)"
            if counts["changed meanwhile"]
            else ""
        )
    )
