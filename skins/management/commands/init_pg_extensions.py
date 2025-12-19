from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Install required PostgreSQL extensions (pg_trgm, unaccent)"

    def handle(self, *args, **kwargs):
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            cursor.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
            cursor.execute("CREATE EXTENSION IF NOT EXISTS btree_gin;")

        self.stdout.write(
            self.style.SUCCESS("PostgreSQL extensions installed (or already present)")
        )
