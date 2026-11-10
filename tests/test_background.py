"""The background-work standards, checked (docs/architecture/background-work.md).

Each test here is one rule from that page. They read the registered tasks,
the Celery settings and the source tree, so a new task or a new way of
queueing work that skips a rule fails CI instead of failing in production.
"""

import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from django.conf import settings

from bonk_skin_search.celery_app import app as celery_app
from core import background
from core.background import TaskContextFilter, enqueue
from core.logs import RailwayJsonFormatter

REPO = Path(__file__).resolve().parent.parent
# Directories that are not app code.
SKIP_DIRS = {".git", "tests", "staticfiles", "node_modules", "media", "backups", ".venv"}


def _app_tasks():
    """Every task this project defines (Celery's own built-ins left out)."""
    celery_app.loader.import_default_modules()
    return {name: task for name, task in celery_app.tasks.items() if not name.startswith("celery.")}


def _python_files():
    for path in REPO.rglob("*.py"):
        if SKIP_DIRS.isdisjoint(path.relative_to(REPO).parts):
            yield path


def test_project_has_tasks_to_check():
    assert "skins.tasks.refresh_discord_servers" in _app_tasks()


@pytest.mark.parametrize("name", sorted(_app_tasks()))
class TestEveryTask:
    def test_lives_in_a_tasks_module(self, name):
        module = _app_tasks()[name].__module__
        assert module.endswith(".tasks"), f"{name} is defined in {module}; put it in tasks.py"

    def test_sets_its_own_time_limits(self, name):
        task = _app_tasks()[name]
        assert task.soft_time_limit, f"{name}: set soft_time_limit on @shared_task"
        assert task.time_limit, f"{name}: set time_limit on @shared_task"
        assert task.soft_time_limit < task.time_limit, f"{name}: soft limit must come first"

    def test_redelivery_cannot_overlap_a_running_copy(self, name):
        task = _app_tasks()[name]
        if not task.acks_late:
            return
        visibility = settings.CELERY_BROKER_TRANSPORT_OPTIONS["visibility_timeout"]
        assert task.time_limit < visibility, (
            f"{name} may run {task.time_limit}s but Redis hands unfinished tasks out "
            f"again after {visibility}s; shorten the task or raise visibility_timeout"
        )


def test_schedules_name_real_tasks():
    tasks = _app_tasks()
    for entry, schedule in settings.CELERY_BEAT_SCHEDULE.items():
        assert schedule["task"] in tasks, f"schedule {entry!r} names an unknown task"


def test_scheduled_tasks_finish_before_their_next_run():
    tasks = _app_tasks()
    for entry, schedule in settings.CELERY_BEAT_SCHEDULE.items():
        task = tasks[schedule["task"]]
        assert task.time_limit < schedule["schedule"], f"{entry} could overlap its next run"


def test_discord_refresh_runs_at_most_once_per_schedule():
    """A repeat would write a second snapshot for servers already refreshed."""
    task = _app_tasks()["skins.tasks.refresh_discord_servers"]
    assert task.acks_late is False


def test_results_are_not_stored():
    assert settings.CELERY_TASK_IGNORE_RESULT is True
    assert settings.CELERY_RESULT_BACKEND is None
    assert settings.CELERY_RESULT_EXPIRES is None  # no daily backend_cleanup job


def test_work_is_queued_only_through_enqueue():
    """Queueing in one place means one retry policy and one failure log."""
    allowed = {REPO / "core" / "background.py"}
    pattern = re.compile(r"\.(delay|apply_async|send_task)\(")
    offenders = [
        str(path.relative_to(REPO))
        for path in _python_files()
        if path not in allowed and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"queue work with core.background.enqueue: {offenders}"


def test_no_new_background_threads():
    """Background work goes to the worker, which survives deploys; threads don't."""
    allowed = {
        # Load-test script run by hand, not part of the site.
        REPO / "scripts" / "load_test_search.py",
    }
    offenders = [
        str(path.relative_to(REPO))
        for path in _python_files()
        if path not in allowed and "threading.Thread(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"use a Celery task instead of a thread: {offenders}"


class TestEnqueue:
    def test_tests_run_queued_tasks_inline(self, settings):
        """Guards tests/conftest.py: without this, enqueue in a test tries a real broker."""
        from bonk_skin_search.celery_app import app

        assert app.conf.task_always_eager is True
        assert app.conf.task_eager_propagates is True

    def test_queues_with_the_arguments(self):
        task = mock.Mock(name="task")

        assert enqueue(task, 7, kind="friends") is True

        call = task.apply_async.call_args
        assert call.kwargs["args"] == (7,)
        assert call.kwargs["kwargs"] == {"kind": "friends"}
        assert call.kwargs["retry_policy"]["max_retries"] == 2

    def test_never_raises_and_logs_why(self, caplog):
        task = mock.Mock()
        task.name = "skins.tasks.example"
        task.apply_async.side_effect = ConnectionError("redis down")

        with caplog.at_level(logging.ERROR, logger="core.background"):
            assert enqueue(task, 7) is False

        assert "could not queue task skins.tasks.example" in caplog.text


class TestTaskContextFilter:
    def _record(self):
        return logging.LogRecord("skins.x", logging.INFO, __file__, 1, "hi", None, None)

    def test_empty_outside_a_task(self):
        record = self._record()

        assert TaskContextFilter().filter(record) is True
        assert record.task == ""

    def test_names_the_task_inside_one(self):
        fake = SimpleNamespace(
            name="skins.tasks.example", request=SimpleNamespace(id="0123456789abcdef")
        )
        record = self._record()

        with mock.patch.object(background, "current_task", fake):
            TaskContextFilter().filter(record)

        assert record.task == " [skins.tasks.example 01234567]"

    def test_logging_config_uses_it(self):
        assert "task_context" in settings.LOGGING["handlers"]["console"]["filters"]

    def test_json_lines_carry_the_task(self):
        fake = SimpleNamespace(
            name="skins.tasks.example", request=SimpleNamespace(id="0123456789abcdef")
        )
        record = self._record()
        with mock.patch.object(background, "current_task", fake):
            TaskContextFilter().filter(record)

        entry = json.loads(RailwayJsonFormatter().format(record))

        assert entry["message"] == "INFO skins.x [skins.tasks.example 01234567]: hi"
        assert entry["task"] == "skins.tasks.example"
        assert entry["task_id"] == "0123456789abcdef"

    def test_json_lines_outside_a_task_are_unchanged(self):
        record = self._record()
        TaskContextFilter().filter(record)

        entry = json.loads(RailwayJsonFormatter().format(record))

        assert entry["message"] == "INFO skins.x: hi"
        assert "task" not in entry and "task_id" not in entry


class TestWorkerDeployConfig:
    def _config(self, name):
        return json.loads((REPO / name).read_text(encoding="utf-8"))

    def test_worker_runs_celery_with_the_scheduler(self):
        deploy = self._config("railway.worker.json")["deploy"]

        assert deploy["startCommand"].startswith("celery -A bonk_skin_search worker")
        assert "--beat" in deploy["startCommand"]

    def test_worker_has_no_http_healthcheck(self):
        """The worker serves no pages; the web healthcheck would fail every deploy."""
        assert "healthcheckPath" not in self._config("railway.worker.json")["deploy"]

    def test_worker_builds_the_same_image_as_the_site(self):
        assert self._config("railway.worker.json")["build"] == self._config("railway.json")["build"]
