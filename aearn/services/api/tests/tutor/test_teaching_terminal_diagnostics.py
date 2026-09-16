import json
import logging

from app.services.tutor.persistence.adapters import _log_teaching_terminal_conflict


def test_terminal_diagnostics_hash_messages_without_leaking_values_or_traceback(caplog) -> None:
    inner = ValueError("untrusted candidate and private value must never be echoed")
    outer = RuntimeError("server wrapper")
    outer.__cause__ = inner
    with caplog.at_level(logging.WARNING):
        _log_teaching_terminal_conflict(outer, run_id="diagnostic-test-run")
    messages = [json.loads(record.message) for record in caplog.records]
    assert len(messages) == 2
    assert all(item["action_identifier"].startswith("sha256:") for item in messages)
    assert messages[1]["exception_class"] == "ValueError"
    assert "untrusted candidate" not in caplog.text
    assert "server wrapper" not in caplog.text
    assert "Traceback" not in caplog.text
