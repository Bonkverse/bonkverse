"""Tests for skin submitters (skins/submitters.py) and the backfill command.

Which path records which submitter is pinned next to each path: test_upload.py,
test_publish_skin.py and test_bot_skins.py.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from accounts.services import log_event
from skins.models import Skin
from core.discord import discord_id_or_none
from skins.submitters import (
    CreatorChoice,
    Submission,
    backfill_submitters,
    resolve_creator,
)
from tests.factories import SkinFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "value, expected",
    [
        (42, 42),
        ("1009876543210987654", 1009876543210987654),
        (" 7 ", 7),
        (None, None),
        ("", None),
        ("abc", None),
        (0, None),
        (-5, None),
        (2**63, None),  # does not fit a bigint
        (True, None),
        (4.0, 4),
    ],
)
def test_discord_id_or_none(value, expected):
    assert discord_id_or_none(value) == expected


def test_submission_skin_fields():
    user = UserFactory()

    fields = Submission(source="website", creator_source="submitter", user=user).skin_fields()

    assert fields == {
        "submitted_by": user,
        "submitted_by_discord_id": None,
        "submission_source": "website",
        "creator_source": "submitter",
    }


def test_new_skins_default_to_legacy():
    skin = SkinFactory()
    skin.refresh_from_db()

    assert (skin.submission_source, skin.creator_source) == ("legacy", "legacy")
    assert (skin.submitted_by, skin.submitted_by_discord_id) == (None, None)


# --- resolve_creator ----------------------------------------------------------


@pytest.mark.parametrize(
    "author, made_it, expected",
    [
        (None, None, CreatorChoice("The Saucy Tulip", "submitter")),
        ("  ", None, CreatorChoice("The Saucy Tulip", "submitter")),
        ("the saucy TULIP", None, CreatorChoice("The Saucy Tulip", "submitter")),
        ("Somepoop", True, CreatorChoice("The Saucy Tulip", "submitter")),
        ("Somepoop", False, CreatorChoice("Somepoop", "bonkleagues")),
        ("Somepoop", None, None),  # ask
        (" The Saucy Tulip", None, None),  # spaces count: another account
    ],
)
def test_resolve_creator(author, made_it, expected):
    assert resolve_creator("The Saucy Tulip", author, made_it) == expected


# --- backfill ---------------------------------------------------------------


def _uploaded(skin, user=None, **metadata):
    log_event(user, "skin_uploaded", skin=skin, **metadata)


def test_backfill_upload_form_skin_made_by_the_uploader():
    user = UserFactory(username="Maker")
    skin = SkinFactory(creator="maker")  # case doesn't matter
    _uploaded(skin, user, source="bonkleagues")

    backfill_submitters()

    skin.refresh_from_db()
    assert skin.submitted_by == user
    assert (skin.submission_source, skin.creator_source) == ("website", "submitter")


def test_backfill_editor_skin_whose_creator_was_changed_is_as_entered():
    user = UserFactory(username="Maker")
    skin = SkinFactory(creator="Someone Else")
    _uploaded(skin, user, source="editor")

    backfill_submitters()

    skin.refresh_from_db()
    assert skin.submitted_by == user
    assert (skin.submission_source, skin.creator_source) == ("editor", "as_entered")


def test_backfill_discord_skin_keeps_the_discord_id():
    skin = SkinFactory()
    _uploaded(skin, source="discord", discord_user_id=1009876543210987654, bonx_skin_id=3)

    backfill_submitters()

    skin.refresh_from_db()
    assert (skin.submitted_by, skin.submitted_by_discord_id) == (None, 1009876543210987654)
    assert (skin.submission_source, skin.creator_source) == ("discord", "as_entered")


def test_backfill_uses_the_first_upload_event():
    first, later = UserFactory(username="First"), UserFactory(username="Later")
    skin = SkinFactory(creator="First")
    _uploaded(skin, first, source="bonkleagues")
    _uploaded(skin, later, source="editor")

    backfill_submitters()

    skin.refresh_from_db()
    assert (skin.submitted_by, skin.submission_source) == (first, "website")


def test_backfill_leaves_skins_without_a_usable_event_alone():
    no_event = SkinFactory()
    odd_source = SkinFactory()
    _uploaded(odd_source, source="somewhere_new")

    report = backfill_submitters()

    assert report.updated == 0
    assert report.counts["unknown_source"] == 1
    assert report.counts["still_legacy"] == 2
    for skin in (no_event, odd_source):
        skin.refresh_from_db()
        assert skin.submission_source == "legacy"


def test_backfill_never_touches_skins_already_recorded():
    user = UserFactory()
    skin = SkinFactory(submission_source="discord", submitted_by_discord_id=42)
    _uploaded(skin, user, source="bonkleagues")

    report = backfill_submitters()

    skin.refresh_from_db()
    assert report.updated == 0
    assert (skin.submission_source, skin.submitted_by) == ("discord", None)


def test_backfill_is_safe_to_rerun():
    _uploaded(SkinFactory(creator="Maker"), UserFactory(username="Maker"), source="bonkleagues")

    assert backfill_submitters().updated == 1
    assert backfill_submitters().updated == 0


def test_backfill_dry_run_writes_nothing():
    skin = SkinFactory(creator="Maker")
    _uploaded(skin, UserFactory(username="Maker"), source="bonkleagues")

    report = backfill_submitters(dry_run=True)

    skin.refresh_from_db()
    assert report.updated == 1
    assert report.counts["still_legacy"] == 0
    assert skin.submission_source == "legacy"


def test_backfill_writes_in_batches(monkeypatch):
    monkeypatch.setattr("skins.submitters.BACKFILL_BATCH_SIZE", 2)
    user = UserFactory(username="Maker")
    for _ in range(5):
        _uploaded(SkinFactory(creator="Maker"), user, source="bonkleagues")

    report = backfill_submitters()

    assert report.updated == 5
    assert not Skin.objects.filter(submission_source="legacy").exists()


def test_command_dry_run_and_write():
    skin = SkinFactory(creator="Maker")
    _uploaded(skin, UserFactory(username="Maker"), source="bonkleagues")

    dry = StringIO()
    call_command("backfill_skin_submitters", "--dry-run", stdout=dry)
    skin.refresh_from_db()
    assert skin.submission_source == "legacy"
    assert "Would update 1 skin(s)." in dry.getvalue()
    assert "website: 1" in dry.getvalue()

    real = StringIO()
    call_command("backfill_skin_submitters", stdout=real)
    skin.refresh_from_db()
    assert skin.submission_source == "website"
    assert "Updated 1 skin(s)." in real.getvalue()
