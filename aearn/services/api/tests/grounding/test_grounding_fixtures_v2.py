"""Offline, synthetic-only 4-route/6-ecosystem scenario contracts."""
from __future__ import annotations

from dataclasses import replace
import ipaddress
import json
from pathlib import Path
from types import SimpleNamespace
import runpy
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.services.grounding.corpus_fixture_policy import (
    FIXTURE_DOMAIN, FIXTURE_VERSION, fixture_registry_digest, fixture_slices,
)
from app.services.grounding import fixtures_v2
from app.services.grounding.fixtures_v2 import fixture_scenarios, validate_fixture_scenarios
from app.services.grounding.subject_registry import (
    capability_projection, get_grounding_subject, is_public_subject_candidate,
)


def test_complete_deterministic_scenario_manifest_reuses_sealed_policy() -> None:
    scenarios = fixture_scenarios()
    assert scenarios is fixture_scenarios()
    assert validate_fixture_scenarios() == ()
    assert len(scenarios) == len({item.subject_id for item in scenarios}) == 10
    assert {item.route_family for item in scenarios} == {
        "python", "typescript-javascript", "web-platform", "sql",
    }
    assert sum(item.fixture_only for item in scenarios) == 6
    for item in scenarios:
        subject = get_grounding_subject(item.subject_id)
        assert subject is not None
        assert subject.language_ids == item.language_ids
        assert item.required_facets == subject.required_facets
        assert all(slice_.url.startswith(f"https://{FIXTURE_DOMAIN}/") for slice_ in fixture_slices(subject))
        assert len(fixture_registry_digest(subject)) == 64
        assert not is_public_subject_candidate(item.subject_id)
        projection = capability_projection(item.subject_id)
        assert projection is not None and not projection.public_course_admissible
        assert item.fixture_only is (projection.release_state == "fixture_only")
        assert all("Synthetic " in slice_.content for slice_ in fixture_slices(subject))


def test_cross_language_alias_sql_dialect_and_framework_scope() -> None:
    by_id = {item.subject_id: item for item in fixture_scenarios()}
    assert by_id["route.typescript-javascript"].language_ids == ("typescript", "javascript")
    assert by_id["route.web-platform"].language_ids == ("html", "css")
    assert by_id["web.react"].language_ids == ("javascript", "typescript", "html", "css")
    assert get_grounding_subject("react").subject_id == "web.react"  # type: ignore[union-attr]
    assert get_grounding_subject("js-ts-core").subject_id == "route.typescript-javascript"  # type: ignore[union-attr]
    assert get_grounding_subject("web-platform-core").subject_id == "route.web-platform"  # type: ignore[union-attr]
    assert "postgresql-dialect" in by_id["sql.postgresql-foundations"].required_facets
    assert "postgresql-dialect" not in by_id["route.sql"].required_facets
    assert set(by_id["web.react"].required_facets).isdisjoint(by_id["route.web-platform"].required_facets)
    assert FIXTURE_VERSION == "fixture-v1"


def test_demo_guard_never_connects_without_explicit_local_offline_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path(__file__).resolve().parents[4] / "scripts" / "rag_v2_demo.py"
    script = runpy.run_path(str(path), run_name="rag_v2_demo_test")
    guard = script["_guard"]
    failure = script["DemoError"]
    scenarios = fixture_scenarios()
    key = script["_key"](0, scenarios[0].subject_id)
    assert key == "ragv2-demo-v1-0-route.python"
    assert script["_expected_corpus_id"](0, scenarios[0].subject_id) == uuid5(
        NAMESPACE_URL, f"aearn-corpus-fixture-v1:route.python:{FIXTURE_VERSION}:{key}-reindex"
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@127.0.0.1:5432/aearn_rag260_cli_retrieval_owned")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("LLM_TYPE", "disabled")
    monkeypatch.setenv("CODEX_RUNTIME_ENABLED", "false")
    for key in ("PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGHOST", "PGHOSTADDR",
                "PGDATABASE", "PGPORT", "PGPASSFILE", "PGTARGETSESSIONATTRS"):
        monkeypatch.delenv(key, raising=False)
    for consent in (None, "wrong_db", "aearn_rag260_cli_retrieval_other"):
        with pytest.raises(failure):
            guard(consent, True)
    with pytest.raises(failure):
        guard("aearn_rag260_cli_retrieval_owned", False)
    assert guard("aearn_rag260_cli_retrieval_owned", True).endswith("/aearn_rag260_cli_retrieval_owned")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@nonlocal.invalid/aearn_rag260_cli_retrieval_owned")
    with pytest.raises(failure):
        guard("aearn_rag260_cli_retrieval_owned", True)
    for override in ("host=remote.invalid", "dbname=business", "service=other",
                     "options=-csearch_path%3Dother", "passfile=%2Ftmp%2Fpgpass"):
        monkeypatch.setenv("DATABASE_URL", (
            "postgresql://secret@127.0.0.1/aearn_rag260_cli_retrieval_owned?" + override
        ))
        with pytest.raises(failure):
            guard("aearn_rag260_cli_retrieval_owned", True)
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@127.0.0.1/aearn_rag260_cli_retrieval_owned#fragment")
    with pytest.raises(failure):
        guard("aearn_rag260_cli_retrieval_owned", True)
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@127.0.0.1/aearn_rag260_cli_retrieval_owned")
    monkeypatch.setenv("LLM_TYPE", "real-provider")
    with pytest.raises(failure):
        guard("aearn_rag260_cli_retrieval_owned", True)


def test_manifest_rejects_route_family_parent_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    scenarios = fixture_scenarios()
    monkeypatch.setattr(fixtures_v2, "SCENARIOS", (
        *scenarios[:4], replace(scenarios[4], route_family="sql"), *scenarios[5:],
    ))
    assert "SCENARIO_SCOPE_INVALID:python.ai-applications" in validate_fixture_scenarios()


def test_demo_and_integration_strip_postgres_inet_mask_before_ip_parser() -> None:
    api_dir = Path(__file__).resolve().parents[2]
    demo = (api_dir.parents[1] / "scripts" / "rag_v2_demo.py").read_text(encoding="utf-8")
    integration = (api_dir / "tests" / "integration" / "test_rag_v2_architecture.py").read_text(encoding="utf-8")
    for source in (demo, integration):
        assert "host(inet_server_addr()) AS server_address" in source
        assert "inet_server_addr()::text AS server_address" not in source
    with pytest.raises(ValueError):
        ipaddress.ip_address("172.18.0.2/32")
    assert str(ipaddress.ip_address("172.18.0.2")) == "172.18.0.2"


def test_demo_replay_uses_stable_scoped_cli_keys_without_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path(__file__).resolve().parents[4] / "scripts" / "rag_v2_demo.py"
    script = runpy.run_path(str(path), run_name="rag_v2_demo_test")
    scenario = fixture_scenarios()[0]
    expected_id = script["_expected_corpus_id"](0, scenario.subject_id)
    calls: list[tuple[str, ...]] = []

    def fake_cli(*args: str) -> dict[str, object]:
        calls.append(args)
        return {
            "reindex": {"ok": True, "corpus_id": str(expected_id)},
            "validate": {"ok": True, "code": "VALIDATION_REPLAY",
                         "validation": {"passed": True}, "summary_hash": "a" * 64},
            "diff": {"ok": True, "code": "DIFF_REPLAY", "base_generation": 0},
            "activate": {"ok": True, "code": "ACTIVATION_REPLAY", "observed_generation": 1},
        }[args[0]]

    monkeypatch.setitem(script["_publish"].__globals__, "_cli", fake_cli)
    first = script["_publish"]((scenario,))
    second = script["_publish"]((scenario,))
    assert first == second == {scenario.subject_id: (expected_id, "a" * 64)}
    assert calls[:4] == calls[4:]
    assert [call[0] for call in calls[:4]] == ["reindex", "validate", "diff", "activate"]
    assert all("ragv2-demo-v1-0-route.python" in " ".join(call) for call in calls)


def test_demo_failure_output_never_echoes_exception_or_dsn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    path = Path(__file__).resolve().parents[4] / "scripts" / "rag_v2_demo.py"
    script = runpy.run_path(str(path), run_name="rag_v2_demo_test")

    def fail(_dsn: str, _name: str) -> None:
        raise RuntimeError("postgresql://credential@host/private provider body")

    monkeypatch.setitem(script["main"].__globals__, "_guard", lambda *_: "private-dsn")
    monkeypatch.setitem(script["main"].__globals__, "_demo", fail)
    assert script["main"](["--run-fixture-demo", "--confirm-disposable-db", "owned"]) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {"ok": False, "code": "DEMO_FAILED"}
    assert "credential" not in output.out and "private" not in output.out


def test_demo_parser_does_not_echo_unrecognized_secret_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = Path(__file__).resolve().parents[4] / "scripts" / "rag_v2_demo.py"
    main = runpy.run_path(str(path), run_name="rag_v2_demo_test")["main"]
    assert main(["--unknown", "postgresql://credential@host/private"]) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {"ok": False, "code": "ARGUMENTS_INVALID"}
    assert "credential" not in output.out


def test_demo_refuses_foreign_replay_events_before_any_operator_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No real connection: model the read-only identity and bounded inventory."""
    import psycopg

    path = Path(__file__).resolve().parents[4] / "scripts" / "rag_v2_demo.py"
    script = runpy.run_path(str(path), run_name="rag_v2_demo_test")
    scenarios = fixture_scenarios()
    name = "aearn_rag260_cli_retrieval_owned"
    versions = [{"id": script["_expected_corpus_id"](i, item.subject_id),
                 "subject_id": item.subject_id, "state": "published"}
                for i, item in enumerate(scenarios)]
    pointers = [{"subject_id": row["subject_id"], "corpus_version_id": row["id"], "generation": 1}
                for row in versions]
    events = [{"corpus_version_id": row["id"], "subject_id": row["subject_id"],
               "event_kind": kind, "idempotency_key": f"{script['_key'](i, row['subject_id'])}-{suffix}"}
              for i, row in enumerate(versions)
              for kind, suffix in (("reindex_started", "reindex"), ("reindex_completed", "reindex"),
                                   ("validation_passed", "validate"), ("diff_generated", "diff"),
                                   ("activated", "activate"))]

    class FakeConnection:
        info = SimpleNamespace(dbname=name, host="127.0.0.1")
        selected: object = None

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args):  # type: ignore[no-untyped-def]
            return None

        def transaction(self):  # type: ignore[no-untyped-def]
            return self

        def execute(self, sql, params=()):  # type: ignore[no-untyped-def]
            assert sql.startswith("SELECT ") or sql == "SET TRANSACTION READ ONLY"
            if "current_database()" in sql:
                self.selected = {"database": name, "server_address": "172.18.0.2"}
            elif "grounding_corpus_versions" in sql:
                self.selected = versions[:params[-1]]
            elif "grounding_active_corpora" in sql:
                self.selected = pointers[:params[-1]]
            elif "grounding_corpus_events" in sql:
                self.selected = events[:params[-1]]
            return self

        def fetchone(self):  # type: ignore[no-untyped-def]
            return self.selected

        def fetchall(self):  # type: ignore[no-untyped-def]
            return self.selected

    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: FakeConnection())

    class PublishReached(Exception):
        pass

    def publish(_scenarios):  # type: ignore[no-untyped-def]
        raise PublishReached

    monkeypatch.setitem(script["_demo"].__globals__, "_publish", publish)
    with pytest.raises(PublishReached):
        script["_demo"]("ignored-fake-dsn", name)
    events.append({**events[0], "idempotency_key": "foreign-diff", "event_kind": "diff_generated"})
    with pytest.raises(script["DemoError"]) as error:
        script["_demo"]("ignored-fake-dsn", name)
    assert error.value.code == "FOREIGN_OR_PARTIAL_CORPUS_DB"
