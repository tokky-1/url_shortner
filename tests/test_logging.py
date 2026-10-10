import json
import logging

from core.log_config import JsonFormatter


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
