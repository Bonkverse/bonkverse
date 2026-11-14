"""The site account model after its move from skins/ to accounts/ (RFC-0001
5.5c, ADR 0017): same tables, history pinned, content type relabelled."""

import ast
import importlib
from pathlib import Path

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from accounts.models import BonkUser

REPO = Path(__file__).resolve().parent.parent
MOVE = importlib.import_module("accounts.migrations.0002_bonkuser_links_point_at_accounts")

# Migrations written while the user model was skins.BonkUser. Each spells it
# out so the switch can't change what it did (ADR 0017).
PINNED = [
    "skins/migrations/0004_skin_downvotes_skin_favorited_by_skin_upvotes_and_more.py",
    "skins/migrations/0005_bonkplayer_friendcounthistory_bonkaccountlink_and_more.py",
    "skins/migrations/0006_flashfriend_flashfriendship.py",
    "skins/migrations/0020_skinreport.py",
    "skins/migrations/0022_userevent.py",
    "players/migrations/0001_initial.py",
    "players/migrations/0005_move_player_models_from_skins.py",
    "public_api/migrations/0001_initial.py",
    "public_api/migrations/0002_terms_acceptance.py",
    "accounts/migrations/0001_initial.py",
]


def test_the_user_model_is_accounts_bonkuser():
    assert settings.AUTH_USER_MODEL == "accounts.BonkUser"
    assert get_user_model() is BonkUser


def test_it_keeps_its_tables():
    """Changing these would make Django rename the real tables."""
    assert BonkUser._meta.db_table == "skins_bonkuser"
    assert BonkUser.groups.through._meta.db_table == "skins_bonkuser_groups"
    assert BonkUser.user_permissions.through._meta.db_table == "skins_bonkuser_user_permissions"


@pytest.mark.parametrize("path", PINNED)
def test_old_migrations_name_skins_bonkuser_not_the_setting(path):
    """A migration that says settings.AUTH_USER_MODEL means whatever the
    setting is now; these must keep meaning skins.BonkUser."""
    tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
    uses_setting = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "AUTH_USER_MODEL"
    ]

    assert uses_setting == []


def test_every_user_field_points_at_the_moved_model():
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if field.is_relation and field.related_model is not None and field.concrete:
                assert field.related_model._meta.label != "skins.BonkUser", (model, field.name)


@pytest.mark.django_db
def test_migration_relabels_the_content_type_both_ways():
    ContentType.objects.filter(model="bonkuser").delete()
    old = ContentType.objects.create(app_label="skins", model="bonkuser")

    MOVE.relabel_content_type(apps, None)
    assert ContentType.objects.get(model="bonkuser").app_label == "accounts"
    assert ContentType.objects.get(model="bonkuser").id == old.id

    MOVE.unlabel_content_type(apps, None)
    assert ContentType.objects.get(model="bonkuser").app_label == "skins"


@pytest.mark.django_db
def test_relabel_leaves_a_fresh_database_alone():
    """A fresh database has no skins.bonkuser row at all."""
    ContentType.objects.filter(model="bonkuser").delete()
    made = ContentType.objects.create(app_label="accounts", model="bonkuser")

    MOVE.relabel_content_type(apps, None)

    assert list(ContentType.objects.filter(model="bonkuser").values_list("id", "app_label")) == [
        (made.id, "accounts")
    ]


@pytest.mark.django_db
def test_relabel_replaces_an_empty_row_left_by_a_rollback():
    """After `migrate accounts 0001`, Django makes an empty accounts.bonkuser;
    migrating forward again must still move the real row (its id is on the
    permissions and admin history)."""
    from django.contrib.auth.models import Permission

    ContentType.objects.filter(model="bonkuser").delete()
    real = ContentType.objects.create(app_label="skins", model="bonkuser")
    empty = ContentType.objects.create(app_label="accounts", model="bonkuser")
    Permission.objects.create(content_type=empty, codename="add_bonkuser", name="x")

    MOVE.relabel_content_type(apps, None)

    assert list(ContentType.objects.filter(model="bonkuser").values_list("id", "app_label")) == [
        (real.id, "accounts")
    ]


@pytest.mark.django_db
def test_relabel_leaves_a_row_in_use_alone():
    from django.contrib.auth.models import Group, Permission

    ContentType.objects.filter(model="bonkuser").delete()
    ContentType.objects.create(app_label="skins", model="bonkuser")
    used = ContentType.objects.create(app_label="accounts", model="bonkuser")
    permission = Permission.objects.create(content_type=used, codename="x_bonkuser", name="x")
    Group.objects.create(name="g").permissions.add(permission)

    MOVE.relabel_content_type(apps, None)

    assert ContentType.objects.filter(model="bonkuser").count() == 2
