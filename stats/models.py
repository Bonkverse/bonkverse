"""Archived win/loss rows from the retired win/loss tracker userscript.

Read-only: nothing writes these any more (the tracker's endpoints were
removed in RFC-0001 Phase 1), and no page shows them. Kept as data for
future stat tracking.

Moved from skins/ in RFC-0001 Phase 5.3b without moving any data: each model
keeps its original table (`db_table`). Renaming it would make Django rename
the real table.
"""

from django.db import models

from core.validators import validate_bonk_username


class PlayerWin(models.Model):
    username = models.CharField(max_length=35, db_index=True, validators=[validate_bonk_username])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "skins_playerwin"

    def __str__(self):
        return f"{self.username} win at {self.created_at}"


class PlayerLoss(models.Model):
    username = models.CharField(max_length=35, db_index=True, validators=[validate_bonk_username])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "skins_playerloss"

    def __str__(self):
        return f"{self.username} loss at {self.created_at}"
