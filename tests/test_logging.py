import json
import logging

import pytest

from core.log_config import JsonFormatter, setup_logging


def test_request_logs_are_json_and_exclude_query_strings(client, caplog):
    caplog.set_level(logging.INFO)
    response = client.get("/abc?token=secret-value", follow_redirects=False)

    assert response.status_code == 404
    record = next(
        record
        for record in caplog.records
        if record.name == "core.log_config" and record.getMessage() == "request completed"
    )
    log_entry = json.loads(JsonFormatter().format(record))

    assert log_entry["timestamp"]
    assert log_entry["level"] == "INFO"
    assert log_entry["message"] == "request completed"
    assert log_entry["request_id"]
    assert log_entry["method"] == "GET"
    assert log_entry["path"] == "/abc"
    assert log_entry["status"] == 404
    assert isinstance(log_entry["duration_ms"], (int, float))
    assert "secret-value" not in json.dumps(log_entry)


def _record(**kwargs) -> logging.LogRecord:
    defaults = dict(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="boom",
        args=(),
        exc_info=None,
    )
    defaults.update(kwargs)
    return logging.LogRecord(**defaults)


def test_formatter_includes_traceback_when_exc_info_present():
    # Without the exc_info branch in JsonFormatter the stack is dropped and
    # production sees only "Exception in ASGI application".
    try:
        raise ValueError("kaboom")
    except ValueError:
        import sys

        record = _record(exc_info=sys.exc_info())

    log_entry = json.loads(JsonFormatter().format(record))

    assert "Traceback (most recent call last)" in log_entry["exception"]
    assert "ValueError: kaboom" in log_entry["exception"]


def test_formatter_omits_exception_field_without_exc_info():
    log_entry = json.loads(JsonFormatter().format(_record()))

    assert "exception" not in log_entry
    assert log_entry["level"] == "ERROR"


@pytest.fixture
def configured_logging():
    """Install the app's real logging config, then put the root logger back.

    setup_logging() clears the root handlers, so without the restore its
    JSON handler would stay attached for the rest of the session and every
    later test would log to stdout.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        yield setup_logging
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_logger_exception_emits_one_json_line_with_the_traceback(
    configured_logging, capsys
):
    # The end-to-end version of the formatter test above: this one goes
    # through setup_logging() and the real handler, so it also catches a
    # formatter that is built correctly but never wired to the root logger.
    configured_logging("INFO")

    try:
        raise ValueError("kaboom")
    except ValueError:
        logging.getLogger("test.exception").exception("boom")

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]

    # One line, not several: the traceback's newlines must be escaped inside
    # the JSON string, or a log shipper would split the stack into records.
    assert len(lines) == 1
    log_entry = json.loads(lines[0])
    assert log_entry["level"] == "ERROR"
    assert log_entry["message"] == "boom"
    assert "Traceback (most recent call last)" in log_entry["exception"]
    assert "ValueError: kaboom" in log_entry["exception"]
