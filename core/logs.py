"""How Bonkverse's logs are written, so Railway shows each line's real level.

Owns: the one-line JSON format Railway parses for log levels, and the filter
that keeps expected "bonk.io is limiting us" responses out of the error log.
Does not own: what gets logged (each module's own logger) or Sentry setup
(bonk_skin_search/settings.py).

Why: Railway labels plain-text lines by stream, and Python's StreamHandler
writes to stderr, so every line, INFO included, showed as an error in Railway
(2026-11-09). Railway reads `level` from single-line JSON on stdout instead:
https://docs.railway.com/observability/logs#structured-logs

Free of Django at import time: gunicorn.conf.py uses the formatter before
Django starts.
"""

import json
import logging

# Python level -> the level names Railway understands (debug, info, warn, error).
_RAILWAY_LEVELS = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warn",
    logging.ERROR: "error",
    logging.CRITICAL: "error",
}


class RailwayJsonFormatter(logging.Formatter):
    """One JSON object per line: message, level and logger.

    `message` keeps the old plain-text shape ("WARNING integrations.bonk_api:
    ...") so searches written for the old logs still match. Tracebacks are
    folded into `message` so the whole entry stays one line. Query extra
    fields in Railway with @logger:skins.login.

    Inside a Celery task (core.background.TaskContextFilter), `message` names
    the task after the logger ("INFO skins.tasks [skins.tasks.x 0d4fcc8a]: ...")
    and the entry gains `task` and `task_id`: find one run with @task_id:<id>.
    """

    def format(self, record: logging.LogRecord) -> str:
        task_tag = getattr(record, "task", "") or ""
        message = f"{record.levelname} {record.name}{task_tag}: {record.getMessage()}"
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            message = f"{message}\n{self.formatStack(record.stack_info)}"
        entry = {
            "message": message,
            "level": _RAILWAY_LEVELS.get(record.levelno, "info"),
            "logger": record.name,
        }
        task_name = getattr(record, "task_name", None)
        if task_name:
            entry["task"] = task_name
            entry["task_id"] = getattr(record, "task_id", None)
        status_code = getattr(record, "status_code", None)
        if isinstance(status_code, int):
            entry["status_code"] = status_code
        return json.dumps(entry, ensure_ascii=False, default=str)


# Set on a request by a view whose error response is expected and already
# logged with more detail (see mark_expected_error).
EXPECTED_ERROR_ATTR = "bonkverse_expected_error"


def mark_expected_error(request) -> None:
    """Keep this request's 5xx response out of Django's error log.

    For failures that aren't bugs and are already logged at the right level,
    e.g. a wear answered 503 because bonk.io is rate-limiting us (logged as a
    WARNING by integrations/bonk_api.py). Otherwise Django adds
    "ERROR django.request: Service Unavailable" for each one, and Sentry
    records every one of them as an error event.
    """
    setattr(request, EXPECTED_ERROR_ATTR, True)


class SkipExpectedErrors(logging.Filter):
    """Drops django.request records for requests marked by mark_expected_error.

    Attach it to the django.request *logger* (not a handler), so the record is
    dropped before Sentry's logging integration sees it too.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        request = getattr(record, "request", None)
        return not getattr(request, EXPECTED_ERROR_ATTR, False)
