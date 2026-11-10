from django.apps import AppConfig


class StatsConfig(AppConfig):
    """Leaderboards (one config entry per board, docs/apps/stats.md) and,
    later, larger stat tracking. The archived win/loss rows (PlayerWin,
    PlayerLoss) still live in skins/ until their move step."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "stats"
