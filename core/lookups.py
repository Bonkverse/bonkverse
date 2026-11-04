"""Custom ORM lookups for Postgres.

Owns: `field__ilike_contains="dog"`, a case-insensitive "contains" that Postgres
can answer from a pg_trgm GIN index (GinIndex(fields=[...], opclasses=["gin_trgm_ops"])).

Why not Django's `icontains`: on Postgres it compiles to UPPER(col) LIKE UPPER(%s),
which only an index on UPPER(col) can serve. `ILIKE` gives the same matches and
uses the plain trigram index on the column, so one index covers both this lookup
and fuzzy `trigram_similar` matching.

Registered on CharField and TextField from SkinsConfig.ready() (skins/apps.py).
"""

from django.db.models import CharField, Lookup, TextField


class ILikeContains(Lookup):
    """`col ILIKE '%value%'`, with %, _ and \\ in the value matched literally."""

    lookup_name = "ilike_contains"
    prepare_rhs = False

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        pattern = f"%{connection.ops.prep_for_like_query(str(self.rhs))}%"
        return f"{lhs} ILIKE %s", [*lhs_params, pattern]


def register():
    CharField.register_lookup(ILikeContains)
    TextField.register_lookup(ILikeContains)
