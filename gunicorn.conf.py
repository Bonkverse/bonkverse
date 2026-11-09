"""Gunicorn settings for production (used by the Dockerfile).

Why this file exists: production ran gunicorn's defaults, one sync worker that
handles one request at a time. A burst of slow searches queued every other
request behind them and stalled the whole site for minutes (2026-11-03).

Each worker is a separate process with several threads. Django is thread-safe,
and most of a request's time is spent waiting on Postgres, Redis or bonk.io, so
threads let one worker serve other requests while a query runs.

Tune without a code change via Railway variables:
    WEB_CONCURRENCY   worker processes      (default 4)
    GUNICORN_THREADS  threads per worker    (default 4)
    GUNICORN_TIMEOUT  seconds per request   (default 30)
Memory is roughly 150 MB per worker. Database connections in use at once are at
most workers x threads (16 by default), well under Postgres's default of 100.
"""

import os


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"

worker_class = "gthread"
workers = _int_env("WEB_CONCURRENCY", 4)
threads = _int_env("GUNICORN_THREADS", 4)

# A request that runs this long is killed and its worker replaced. Search queries
# are capped well below this (see SEARCH_STATEMENT_TIMEOUT_MS in settings).
timeout = _int_env("GUNICORN_TIMEOUT", 30)
graceful_timeout = 30
keepalive = 5

# Recycle workers now and then so slow memory growth can't build up. The jitter
# keeps them from all restarting at the same moment.
max_requests = 2000
max_requests_jitter = 200

# Log to stdout so Railway shows it. Railway's proxy already records each
# request (status, duration, path), so gunicorn's per-request access log is off.
accesslog = None
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# Same one-line JSON on stdout as Django's logs (core/logs.py), so Railway
# shows "Booting worker" as info rather than as an error. Gunicorn's default
# handler writes to stderr, which Railway labels as errors (2026-11-09).
logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"railway": {"()": "core.logs.RailwayJsonFormatter"}},
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "formatter": "railway",
            "stream": "ext://sys.stdout",
        },
    },
    "root": {"level": "WARNING", "handlers": ["stdout"]},
    "loggers": {
        "gunicorn.error": {
            "level": loglevel.upper(),
            "handlers": ["stdout"],
            "propagate": False,
            "qualname": "gunicorn.error",
        },
        "gunicorn.access": {
            "level": "INFO",
            "handlers": [],
            "propagate": False,
            "qualname": "gunicorn.access",
        },
    },
}
