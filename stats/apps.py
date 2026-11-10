from django.apps import AppConfig


class StatsConfig(AppConfig):
    """Leaderboards (one config entry per board, docs/apps/stats.md), the
    archived win/loss rows (PlayerWin, PlayerLoss), and later larger stat
    tracking."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "stats"
