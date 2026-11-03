"""factory_boy factories for Bonkverse models.

One factory per model that tests need; add new ones here rather than
building model instances by hand inside tests.
"""

import factory

from skins.models import BonkPlayer, BonkUser, Skin


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
    skin_code = "CgcDYQACCQkBCgcFYWwAAQBNPlt5PUI19d8"
    labels = {"style": "Minimalist", "themes": [], "objects": [], "colors": ["red"]}
