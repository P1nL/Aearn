"""CLI contracts: bounded JSON, safe errors, required idempotency and no bootstrap."""
from __future__ import annotations

import json
from contextlib import contextmanager
from urllib.parse import urlsplit

import psycopg
import pytest
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.services.grounding import corpus_cli


@pytest.fixture()
def cli_connection(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    if not urlsplit(get_settings().database_url).path.lstrip("/").startswith("aearn_rag260_cli_"):
        pytest.skip("requires disposable corpus CLI database")
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
        conn.execute("SELECT 1")
        @contextmanager
        def test_connect():  # type: ignore[no-untyped-def]
            yield conn
        monkeypatch.setattr(corpus_cli, "connect", test_connect)
        yield conn
        conn.rollback()


def test_cli_fixture_workflow_and_safe_projection(cli_connection, capsys: pytest.CaptureFixture[str]) -> None:  # type: ignore[no-untyped-def]
    def run(*args: str) -> tuple[int, dict[str, object]]:
        exit_code = corpus_cli.main(args)
        output = capsys.readouterr()
        assert output.err == "" and len(output.out) < 8192
        assert "postgresql://" not in output.out and "fixtures.aearn.invalid" not in output.out
        return exit_code, json.loads(output.out)
    assert run("reindex", "--subject", "python.ai-applications", "--subject-version", "fixture-v1",
               "--idempotency-key", "cli-test-1")[0] == 0
    # A second invocation with the same key is the same receipt, never duplicate snapshots.
    replay_code, replay = run("reindex", "--subject", "python.ai-applications", "--subject-version", "fixture-v1",
                              "--idempotency-key", "cli-test-1")
    assert replay_code == 0 and replay["code"] == "REINDEX_REPLAY"
    corpus_id = str(replay["corpus_id"])
    assert run("validate", "--corpus-id", corpus_id, "--expected-generation", "0",
               "--idempotency-key", "cli-test-validate")[0] == 0
    assert run("diff", "--candidate-id", corpus_id, "--idempotency-key", "cli-test-diff")[0] == 0
    assert run("status", "--subject", "python.ai-applications")[1]["active"] is None
    assert run("reindex", "--subject", "python.fastapi", "--subject-version", "fixture-v1",
               "--mode", "fetch", "--idempotency-key", "cli-no-fetch") == (2, {"ok": False, "code": "FETCH_NOT_READY"})
    assert run("activate", "--candidate-id", corpus_id, "--expected-generation", "0",
               "--summary-hash", "bad", "--idempotency-key", "cli-wrong-hash") == (3, {"ok": False, "code": "CORPUS_CONFLICT"})
    assert run("retire", "--corpus-id", "bad", "--idempotency-key", "cli-bad-id") == (2, {"ok": False, "code": "INVALID_REQUEST"})
    assert run("reindex", "--subject", "python.fastapi", "--subject-version", "fixture-v1") == (2, {"ok": False, "code": "INVALID_REQUEST"})


def test_cli_masks_connection_errors_and_never_prints_dsn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def failing_connect():  # type: ignore[no-untyped-def]
        raise RuntimeError("postgresql://operator:secret@127.0.0.1/private")
    monkeypatch.setattr(corpus_cli, "connect", failing_connect)
    assert corpus_cli.main(("status", "--subject", "route.sql")) == 4
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {"ok": False, "code": "INTERNAL_ERROR"}
