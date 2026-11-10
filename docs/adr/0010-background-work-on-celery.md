# ADR 0010: Background work runs on one Celery worker, queued through `enqueue`

**Status:** accepted, 2026-11-06 (RFC-0001 Phase 4, step 4.2)

**Context.** Celery and django-celery-beat were installed and configured, but
production had no worker or scheduler: the Railway project ran only gunicorn.
So the hourly Discord refresh (`refresh_discord_servers`) had no process to run
it. The one piece of real background work, the friend sync after login, ran in
a `threading.Thread` inside gunicorn. That thread dies with its gunicorn worker
on every deploy and every `max_requests` recycle (about every 2,000 requests),
with no error and no retry; the profile toast just gives up after ~12 s. More
background work is planned (syncing, data aggregation).

**Decision.**
- A Railway `worker` service runs `celery -A bonk_skin_search worker --beat`
  from the same Dockerfile (`railway.worker.json`), with **exactly one
  replica** because it also runs the scheduler.
- Queue work only with `core.background.enqueue`, which never raises (two
  quick retries, then logs and returns `False`). No `.delay()` elsewhere, no
  background threads.
- Tasks live in each app's `tasks.py`, are thin wrappers over services, take
  ids (never model instances or secrets), set their own time limits, and are
  safe to run twice. They are acknowledged after they finish (at-least-once);
  a task that must not repeat opts out with `acks_late=False`.
- Schedules are code (`CELERY_BEAT_SCHEDULE`), kept in the database by
  django-celery-beat's `DatabaseScheduler` for `last_run_at`.
- No result backend: tasks report through logs and the rows they write.
- Every log line inside a task carries the task name and id
  (`core.background.TaskContextFilter`).
- `tests/test_background.py` enforces the checkable rules.

Full standard: [architecture/background-work.md](../architecture/background-work.md).

**Alternatives considered.**
- *Keep threads behind a helper*: no new service, but jobs still vanish on
  deploys and compete with page requests; scheduled jobs would still have
  nothing to run them.
- *A database-backed queue (Django 6 tasks, django-q)*: one fewer moving
  part than Redis, but Celery and Redis are already in the stack, and the
  Discord schedule already depends on django-celery-beat.

**Consequences.**
- Scheduled jobs actually run; background work survives web deploys and can
  retry.
- One more always-on container on Railway, and one more service to check when
  something background-y breaks
  ([runbook](../operations/runbook.md#background-jobs-arent-running)).
- The worker has no media volume: tasks can't write skin files until media
  moves to object storage.
- Scaling past one worker means splitting `celery beat` into its own service.
