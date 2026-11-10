"""The Celery beat scheduler: django-celery-beat's DatabaseScheduler, plus one fix.

Owns: running a schedule that has never run as soon as the worker starts.
Does not own: the schedules themselves (CELERY_BEAT_SCHEDULE in settings) or
queueing (core/background.py). Standards: docs/architecture/background-work.md.

Why: a schedule with no last run counts its first interval from the row's
`date_changed`, and the worker re-saves every schedule from settings at each
start, which moves `date_changed` to now. So every deploy pushed a new
schedule's first run another interval out; on 2026-11-10 four deploys in an
hour kept the new hourly jobs from ever running. Once a schedule has run,
its saved last run counts and restarts don't delay it.

Kept out of core/background.py: importing django-celery-beat needs Django's
apps loaded, and core.background is imported while logging is configured.
"""

import datetime
import logging

from django_celery_beat.models import PeriodicTask
from django_celery_beat.schedulers import DatabaseScheduler

logger = logging.getLogger(__name__)

# Old enough that any interval or crontab is due.
_LONG_AGO = datetime.timedelta(days=365 * 30)


class Scheduler(DatabaseScheduler):
    def update_from_dict(self, mapping):
        # New rows (not in the table yet) count as never run too.
        has_run = set(
            PeriodicTask.objects.filter(name__in=mapping, last_run_at__isnull=False).values_list(
                "name", flat=True
            )
        )
        never_run = set(mapping) - has_run
        super().update_from_dict(mapping)
        for name in never_run:
            entry = self.schedule.get(name)
            if entry is None:
                continue
            entry.last_run_at = entry.model.last_run_at = entry._default_now() - _LONG_AGO
            logger.info("schedule %s has never run: running it now", name)
