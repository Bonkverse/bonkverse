# 2026-11-10: New scheduled jobs didn't run for three hours after the worker started

**Impact:** the hourly Discord directory refresh and replay name sync, both new
that day, didn't run from the worker's first start (05:57 UTC) until 09:18
UTC. No data was lost: the Discord counts and the replay names just stayed
three hours older than they should have been.
**Trigger:** five deploys within about an hour, each restarting the worker.
**Fixed in:** #77.

## What happened

1. The `worker` service started at 05:57 UTC with two schedules from
   `CELERY_BEAT_SCHEDULE`, each hourly. django-celery-beat copies them into
   its `PeriodicTask` table at start.
2. A schedule that has never run has no `last_run_at`, so django-celery-beat
   counts its first hour from the row's `date_changed`, and every worker start
   saves the row again.
3. Merges #72 to #76 redeployed the worker at 06:30, 06:31, 06:47, 06:58 and
   07:18. Each restart pushed the first run another hour out, so at a 07:42
   check neither job had run once.

## What changed

- `core.beat.Scheduler` (now `CELERY_BEAT_SCHEDULER`) runs a schedule that has
  never run as soon as the worker starts, then every interval after. A
  schedule that has run keeps its interval across restarts. Tested by starting
  a real worker twice; after #77 deployed, both jobs ran within a minute
  (09:18 UTC).
- [background-work.md](../architecture/background-work.md#schedules) and the
  [runbook](../operations/runbook.md#background-jobs-arent-running) say what
  to expect in the worker log (`schedule <name> has never run: running it now`).
- Side effect to know: if the worker restarts before beat saves a first run
  (every few minutes), that first run happens once more. Scheduled tasks must
  be safe to run twice, which the standard already requires.
