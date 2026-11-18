"""site_pages seed_ui_checks: the data CI's browser checks run against
(.github/workflows/ci.yml, job "browser")."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import BonkUser
from skins.models import CategoryCover, Skin, SkinReport

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


def test_seeds_skins_with_drawn_images_and_a_staff_session(client, tmp_path):
    session_file = tmp_path / "session"

    call_command("seed_ui_checks", session_file=str(session_file))

    skin = Skin.objects.order_by("id").first()
    assert skin.image_url == f"/media/skins/{skin.id}.png"
    assert (tmp_path / "skins" / f"{skin.id}.png").stat().st_size > 0
    assert SkinReport.objects.filter(resolved=False).exists()
    assert CategoryCover.objects.exists()
    client.cookies["sessionid"] = session_file.read_text()
    assert client.get("/moderation/").status_code == 200  # a staff session


def test_running_twice_adds_nothing(tmp_path):
    call_command("seed_ui_checks")
    counts = (Skin.objects.count(), SkinReport.objects.count(), BonkUser.objects.count())

    call_command("seed_ui_checks")

    assert (Skin.objects.count(), SkinReport.objects.count(), BonkUser.objects.count()) == counts


def test_refuses_to_run_in_production(settings):
    settings.IS_PROD = True

    with pytest.raises(CommandError):
        call_command("seed_ui_checks")
    assert not BonkUser.objects.exists()
