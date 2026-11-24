from django.apps import AppConfig


class SkinsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "skins"

    def ready(self):
        from core import lookups

        lookups.register()

        # One vote per person: an account joining a group gives up its votes
        # where the group already voted (RFC-0003 phase 5, skins/votes.py).
        from accounts.services import account_joined_group

        account_joined_group.connect(_merge_votes, dispatch_uid="skins.merge_votes")


def _merge_votes(sender, account, group, others, **kwargs):
    from skins.votes import merge_votes_into_group

    merge_votes_into_group(account.pk, others)
