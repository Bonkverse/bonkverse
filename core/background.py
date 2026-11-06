"""Queueing background work, and logging from inside it.

Owns: `enqueue`, the only way app code hands work to the Celery worker, and
`TaskContextFilter`, which tags every log line written inside a task with the
task's name and id.
Does not own: the tasks themselves (each app's tasks.py) or Celery's settings
(the CELERY_* block in settings.py). Standards for both:
docs/architecture/background-work.md.
"""

import logging

from celery import current_task

logger = logging.getLogger(__name__)

# Two quick retries if Redis blinks, then give up: queueing must never hold up
# the request that asked for it (the broker's socket timeouts are short too).
_PUBLISH_RETRY_POLICY = {
    "max_retries": 2,
    "interval_start": 0,
    "interval_step": 0.2,
    "interval_max": 0.5,
}


def enqueue(task, *args, **kwargs) -> bool:
    """Queue `task` to run on the worker; never raise.

    Arguments must be plain JSON values (ids, strings, numbers), never model
    instances or secrets: the task loads what it needs when it runs.

    Args:
        task: a Celery task (the function decorated with @shared_task).
        *args, **kwargs: passed to the task.

    Returns:
        True if the task was queued. False if it couldn't be (Redis down,
        arguments not JSON); the reason is logged and the caller carries on
        without it.
    """
    try:
        task.apply_async(args=args, kwargs=kwargs, retry=True, retry_policy=_PUBLISH_RETRY_POLICY)
    except Exception:
        logger.exception("could not queue task %s", task.name)
        return False
    return True


class TaskContextFilter(logging.Filter):
    """Add `task` to every log record: " [task_name abc12345]" inside a task, "" outside.

    Attached to the console handler in settings.LOGGING, so any module's
    logger gets it with no extra code: a line from integrations/bonk_api.py
    written during a friend sync shows which task (and which run) it was.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        task = current_task
        request = getattr(task, "request", None) if task else None
        task_id = getattr(request, "id", None)
        if task and task_id:
            record.task = f" [{task.name} {task_id[:8]}]"
        else:
            record.task = ""
        return True
