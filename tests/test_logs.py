"""Log format and filtering (core/logs.py).

Regression for 2026-11-09: every line went to stderr as plain text, so Railway
showed INFO lines as errors, and each expected wear 503 added an ERROR line.
"""

import json
import logging
import sys

from core.logs import RailwayJsonFormatter, SkipExpectedErrors, mark_expected_error


def _record(level, msg="hello", name="skins.login", **extra):
    record = logging.LogRecord(name, level, __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_each_line_is_one_json_object_with_railways_level_names():
    fmt = RailwayJsonFormatter()
    levels = {
        logging.DEBUG: "debug",
        logging.INFO: "info",
        logging.WARNING: "warn",
        logging.ERROR: "error",
        logging.CRITICAL: "error",
    }
    for py_level, railway_level in levels.items():
        line = fmt.format(_record(py_level))
        assert "\n" not in line
        assert json.loads(line)["level"] == railway_level


def test_message_keeps_the_old_plain_text_shape():
    entry = json.loads(RailwayJsonFormatter().format(_record(logging.INFO, "bonk login")))

    assert entry["message"] == "INFO skins.login: bonk login"
    assert entry["logger"] == "skins.login"


def test_traceback_stays_on_one_line():
    try:
        raise ValueError("boom")
    except ValueError:
        record = _record(logging.ERROR, exc_info=sys.exc_info())

    line = RailwayJsonFormatter().format(record)

    assert "\n" not in line
    assert "ValueError: boom" in json.loads(line)["message"]


def test_expected_errors_are_dropped_and_others_kept():
    class Request:
        pass

    expected, unexpected = Request(), Request()
    mark_expected_error(expected)
    skip = SkipExpectedErrors()

    assert skip.filter(_record(logging.ERROR, request=expected)) is False
    assert skip.filter(_record(logging.ERROR, request=unexpected)) is True
    assert skip.filter(_record(logging.ERROR)) is True


def test_settings_log_json_to_stdout_and_filter_django_request(settings):
    logging_conf = settings.LOGGING

    assert logging_conf["handlers"]["console"]["stream"] == "ext://sys.stdout"
    assert logging_conf["formatters"]["railway"]["()"] == "core.logs.RailwayJsonFormatter"
    assert logging_conf["loggers"]["django.request"]["filters"] == ["skip_expected_errors"]
    assert "integrations" in logging_conf["loggers"]
