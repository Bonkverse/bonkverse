"""Unit tests for core/bonk/: plain Python, no database or Django needed."""

import pytest

from core.bonk import AvatarSlot, BonkSession, BonkUsername, InvalidUsername, SkinCode
from core.bonk.session import TOKEN_TTL_SECONDS


class TestAvatarSlot:
    @pytest.mark.parametrize("value", [1, 5, "3", " 2 ", AvatarSlot(4)])
    def test_parses_valid_slots(self, value):
        assert AvatarSlot.parse(value) is not None

    @pytest.mark.parametrize("value", [0, 6, -1, "abc", "", None, True, 2.5j, []])
    def test_rejects_everything_else(self, value):
        assert AvatarSlot.parse(value) is None

    def test_constructor_refuses_out_of_range(self):
        with pytest.raises(ValueError):
            AvatarSlot(6)

    @pytest.mark.parametrize(
        "requested,active,expected",
        [("2", 4, 2), ("9", 4, 4), (None, 5, 5), ("x", None, 3), (None, 0, 3)],
    )
    def test_choose_prefers_requested_then_active_then_default(self, requested, active, expected):
        assert AvatarSlot.choose(requested, active).number == expected

    def test_formats_as_its_number(self):
        assert str(AvatarSlot(2)) == "2"
        assert int(AvatarSlot(2)) == 2


class TestBonkUsername:
    """Rules come from real bonk.io data (docs/bonk/accounts.md), not the
    new-account rules: older accounts break those, and we must accept them."""

    @pytest.mark.parametrize(
        "value",
        [
            "a",  # 1 character
            "07",
            "x" * 35,  # an older limit; real accounts this long exist
            " LeadingSpace",  # leading space
            "a b c d ",  # trailing space
            "x    y",  # repeated spaces
            "Guest1234",  # a registered account, not a guest
            "Guestimate",
            "a.j",
            "1/2",
            "-.-",
            "$$",
            "Chaz",
        ],
    )
    def test_accepts_names_real_accounts_have(self, value):
        assert BonkUsername(value).value == value  # kept exactly, never trimmed

    @pytest.mark.parametrize(
        "value,message",
        [("", "required"), ("x" * 65, "at most 64"), ("bad\nname", "doesn't allow")],
    )
    def test_rejects_only_impossible_names(self, value, message):
        with pytest.raises(InvalidUsername, match=message):
            BonkUsername(value)

    def test_key_ignores_case_but_keeps_spaces(self):
        assert BonkUsername("Saucy").key == BonkUsername("sAUCY").key
        assert BonkUsername(" Saucy").key != BonkUsername("Saucy").key

    def test_model_validator_uses_the_same_rules(self):
        from django.core.exceptions import ValidationError

        from core.validators import validate_bonk_username

        validate_bonk_username("Guest99")
        with pytest.raises(ValidationError, match="required"):
            validate_bonk_username("")

    def test_old_validator_path_still_imports(self):
        """skins migration 0016 imports skins.models.validate_username."""
        from core.validators import validate_bonk_username
        from skins.models import validate_username

        assert validate_username is validate_bonk_username


class TestSkinCode:
    def test_plain_code_is_unchanged(self):
        assert SkinCode("CgcDYQACCQ/A+==").decoded == "CgcDYQACCQ/A+=="

    def test_decodes_once_or_twice_encoded_codes(self):
        assert SkinCode("Cgc%2FA").decoded == "Cgc/A"
        assert SkinCode("Cgc%252FA").decoded == "Cgc/A"  # BonkLeagues double encoding

    def test_from_image_url(self):
        url = "https://bonkleagues.io/render?skinCode=Cgc%2FA&size=512"

        assert SkinCode.from_image_url(url).decoded == "Cgc/A"
        assert SkinCode.from_image_url("https://bonkverse.io/media/skins/1.png") is None

    def test_empty_code_is_refused(self):
        with pytest.raises(ValueError):
            SkinCode("")


class FakeSession(dict):
    modified = False


class TestBonkSession:
    @pytest.fixture
    def now(self):
        return [1_000_000.0]

    @pytest.fixture
    def bonk(self, now):
        return BonkSession(FakeSession(), clock=lambda: now[0])

    def test_no_token_by_default(self, bonk):
        assert bonk.token is None
        assert bonk.is_expired

    def test_stored_token_lives_for_the_ttl(self, bonk, now):
        bonk.store_token("tok")

        assert bonk.token == "tok"
        assert bonk.expires_in_seconds == TOKEN_TTL_SECONDS
        now[0] += TOKEN_TTL_SECONDS
        assert bonk.token is None

    def test_storing_again_slides_expiry(self, bonk, now):
        bonk.store_token("tok")
        now[0] += 1000

        bonk.store_token("tok")

        assert bonk.expires_in_seconds == TOKEN_TTL_SECONDS

    def test_active_slot_ignores_invalid_values(self, bonk):
        bonk.store_active_slot("9")
        assert bonk.active_slot is None

        bonk.store_active_slot("4")
        assert bonk.active_slot == AvatarSlot(4)

    def test_uses_the_existing_session_keys(self, now):
        """Existing logged-in sessions must keep working after this refactor."""
        store = FakeSession()
        bonk = BonkSession(store, clock=lambda: now[0])

        bonk.store_token("tok")
        bonk.store_active_slot(2)
        bonk.store_identity("Saucy", 123)

        assert store == {
            "bonk_token": "tok",
            "bonk_token_expires": now[0] + TOKEN_TTL_SECONDS,
            "bonk_active_slot": 2,
            "bonk_username": "Saucy",
            "bonk_user_id": 123,
        }
        assert store.modified

    def test_clear_removes_everything_bonk(self, now):
        store = FakeSession(other="kept")
        bonk = BonkSession(store, clock=lambda: now[0])
        bonk.store_token("tok")
        bonk.store_identity("Saucy", 1)

        bonk.clear()

        assert store == {"other": "kept"}


def test_core_bonk_does_not_import_django_or_http():
    """core/bonk is the seed of a bonk.io SDK: keep it free of Django and requests."""
    from pathlib import Path

    folder = Path(__file__).resolve().parent.parent / "core" / "bonk"
    for path in folder.glob("*.py"):
        text = path.read_text()
        assert "import django" not in text and "from django" not in text, path.name
        assert "import requests" not in text, path.name
