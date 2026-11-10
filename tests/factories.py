"""factory_boy factories for Bonkverse models.

One factory per model that tests need; add new ones here rather than
building model instances by hand inside tests.
"""

import factory

from skins.models import BonkPlayer, BonkUser, Skin


# A real one-layer skin code (shape 13, light gray on a black base). Codes are
# checked (core.bonk.SkinCode.parse) wherever a client supplies one.
SKIN_CODE = "CgcDYQACCQMBCgcFYWwAAQANPhmZmgAAAAAAAAAAAAAAAAAAAPr6+gAAAAA="
# The same code URL-encoded twice, as some BonkLeagues/BonxBot codes arrive.
SKIN_CODE_DOUBLE_ENCODED = SKIN_CODE.replace("+", "%252B").replace("=", "%253D")


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BonkUser
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"tester{n}")
    is_staff = False


class BonkPlayerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BonkPlayer

    bonk_id = factory.Sequence(lambda n: 100_000 + n)
    username = factory.Sequence(lambda n: f"player{n}")


class SkinFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Skin

    name = factory.Sequence(lambda n: f"Test Skin {n}")
    creator = "tester0"
    skin_code = SKIN_CODE
    labels = {"style": "Minimalist", "themes": [], "objects": [], "colors": ["red"]}
