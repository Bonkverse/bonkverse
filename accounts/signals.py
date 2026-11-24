"""Signals the accounts app sends for other apps to act on.

Owns: the signal definitions. Receivers live in the app that acts (ADR 0018:
accounts doesn't import the apps that depend on it).
"""

from django.dispatch import Signal

# Sent inside the transaction of groups.join, after `account` joined `group`.
# Receivers merge per-account data that is one per group (skins: votes).
# kwargs: account (BonkUser), group (AccountGroup), others (list of the ids of
# the accounts that were in the group before it joined).
account_joined_group = Signal()
