"""The Celery app: background work for the Django site.

Settings come from Django settings (the CELERY_* block in settings.py);
tasks are found in each installed app's tasks.py. Standards for writing,
queueing and running tasks: docs/architecture/background-work.md.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bonk_skin_search.settings")

app = Celery("bonk_skin_search")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
