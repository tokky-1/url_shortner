import json
import logging

from core.logging import JsonFormatter


def test_request_logs_are_json_and_exclude_query_strings(client, caplog):
    caplog.set_level(logging.INFO)
    response = client.get("/abc?token=secret-value", follow_redirects=False)

    assert response.status_code == 404
    record = next(
        record
        for record in caplog.records
        if record.name == "core.logging" and record.getMessage() == "request completed"
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
