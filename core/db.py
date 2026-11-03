"""Database helpers shared across apps.

Owns: running a block of queries under a Postgres time limit (and other
temporary Postgres settings).
Does not own: any queries themselves.
"""

from contextlib import contextmanager

from django.db import connection, transaction


def _set_local(cursor, name: str, value: str) -> None:
    cursor.execute("SELECT set_config(%s, %s, true)", [name, value])


@contextmanager
def time_limited_queries(timeout_ms: int, **pg_settings):
    """Run the enclosed queries with a per-query time limit.

    Any single query running longer than `timeout_ms` is cancelled by Postgres and
    raises django.db.OperationalError, so a slow query can't hold a web worker
    hostage.

    The settings apply only inside the block. SET LOCAL alone would last until the
    end of the *outermost* transaction, so when this runs inside another
    transaction (tests, or a view wrapped in atomic) the previous values are put
    back explicitly on the way out.

    Args:
        timeout_ms: Per-query limit in milliseconds.
        **pg_settings: Extra temporary settings, with "__" for ".",
            e.g. pg_trgm__similarity_threshold=0.2.

    Raises:
        django.db.OperationalError: When a query exceeds the time limit.
    """
    wanted = {"statement_timeout": f"{timeout_ms}ms"}
    wanted.update({name.replace("__", "."): str(value) for name, value in pg_settings.items()})

    with transaction.atomic():
        with connection.cursor() as cursor:
            previous = {}
            for name in wanted:
                # missing_ok=true: custom settings (pg_trgm.*) may not be set yet.
                cursor.execute("SELECT current_setting(%s, true)", [name])
                previous[name] = cursor.fetchone()[0]
            for name, value in wanted.items():
                _set_local(cursor, name, value)
        yield
        # Normal exit: put the previous values back. (If the block raised, the
        # atomic block rolls back to before it, which undoes the settings anyway.)
        with connection.cursor() as cursor:
            for name, value in previous.items():
                if value is not None:
                    _set_local(cursor, name, value)
