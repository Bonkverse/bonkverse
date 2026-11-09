"""Revoke a public API key by its prefix.

    python manage.py revoke_api_key bvk_ab12cd34

Revoked keys get 401 invalid_api_key straight away (no cache in between).
"""

from django.core.management.base import BaseCommand, CommandError

from public_api.models import ApiKey


class Command(BaseCommand):
    help = "Revoke a public API key by its prefix (bvk_xxxxxxxx)."

    def add_arguments(self, parser):
        parser.add_argument("prefix")

    def handle(self, *args, prefix, **options):
        bare = prefix.removeprefix("bvk_").split("_")[0]
        api_key = ApiKey.objects.filter(prefix=bare).first()
        if api_key is None:
            raise CommandError(f"No key with prefix {prefix!r}.")
        if not api_key.is_active:
            self.stdout.write(f"{api_key} was already revoked.")
            return
        api_key.revoke()
        self.stdout.write(f"Revoked {api_key}.")
