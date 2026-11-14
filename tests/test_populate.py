"""`manage.py populate_all` only calls commands that exist.

It called a removed `populate_player_stats` until RFC-0001 step 5.6a, so it
crashed partway through for anyone setting up a local database.
"""

from django.core.management import get_commands

from skins.management.commands.populate_all import COMMANDS


def test_populate_all_calls_only_existing_commands():
    assert set(COMMANDS) <= set(get_commands())


def test_every_command_of_ours_loads():
    """Importing a command is enough to catch a broken import (5.4b left three
    seed commands with `from .models`, which only failed when someone ran them)."""
    from django.core.management import load_command_class

    local = {
        name: app
        for name, app in get_commands().items()
        if not app.startswith(("django.", "django_"))
        and app not in {"rest_framework", "celery", "django_extensions"}
    }
    assert "populate_all" in local
    for name, app in local.items():
        load_command_class(app, name)
