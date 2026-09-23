r"""Opt-in, no-network RAG v2 fixture demonstration on a caller-owned DB.

From aearn/services/api (PowerShell 7), after separately provisioning and
bootstrapping the exclusive disposable DB and setting DATABASE_URL,
PYTHON_DOTENV_DISABLED=1, LLM_TYPE=disabled, CODEX_RUNTIME_ENABLED=false:

  uv run python ../../scripts/rag_v2_demo.py --run-fixture-demo --confirm-disposable-db aearn_rag260_cli_retrieval_<name>

Never creates, bootstraps or drops a database. Does not fetch or call a provider.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import ipaddress
import subprocess
import sys
from typing import Any, NoReturn
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

API_DIR = Path(__file__).resolve().parents[1] / "services" / "api"
DB_PREFIX = "aearn_rag260_cli_retrieval_"


class DemoError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse otherwise echoes unrecognized user-supplied DSNs on stderr.
        raise DemoError("ARGUMENTS_INVALID")


def _guard(confirmation: str | None, run: bool) -> str:
    """No app imports, subprocesses, connections or writes before this guard."""
    if (not run or not confirmation or len(confirmation) > 63
            or not re.fullmatch(r"aearn_rag260_cli_retrieval_[a-z0-9][a-z0-9_]*", confirmation)):
        raise DemoError("OPT_IN_REQUIRED")
    if (os.getenv("PYTHON_DOTENV_DISABLED") != "1"
            or os.getenv("LLM_TYPE") != "disabled"
            or os.getenv("CODEX_RUNTIME_ENABLED") != "false"
            or any(os.getenv(key, "false").lower() not in {"false", "0", ""} for key in (
                "RAG_V2_ENABLED", "RAG_V2_SHADOW_ENABLED", "RAG_V2_OPTIONAL_EMBEDDING_ENABLED"
            ))):
        raise DemoError("OFFLINE_GATES_REQUIRED")
    dsn = os.getenv("DATABASE_URL", "")
    try:
        if (not dsn or any(ord(char) < 32 or ord(char) == 127 for char in dsn)
                or any(os.getenv(key) for key in (
                    "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGHOST", "PGHOSTADDR",
                    "PGDATABASE", "PGPORT", "PGPASSFILE", "PGTARGETSESSIONATTRS",
                ))):
            raise ValueError("ambiguous connection")
        url = urlsplit(dsn)
        query = parse_qsl(url.query, strict_parsing=True, keep_blank_values=True)
        if (url.fragment or len({key for key, _ in query}) != len(query)
                or any(key not in {"sslmode", "connect_timeout"} for key, _ in query)
                or any(key == "sslmode" and value != "disable" for key, value in query)
                or any(key == "connect_timeout" and (not value.isdecimal() or not 1 <= int(value) <= 10)
                       for key, value in query)):
            raise ValueError("connection override")
        database = unquote(url.path.lstrip("/"))
        if (url.scheme not in {"postgresql", "postgres"}
                or url.hostname not in {"127.0.0.1", "localhost", "::1"}
                or database != confirmation or not database.startswith(DB_PREFIX)
                or any(c in database for c in ("/", "\\", "?", "#"))):
            raise ValueError("scope")
        _ = url.port
        # Libpq's parsed identity, not URL path/hostname alone, is authoritative.
        from psycopg.conninfo import conninfo_to_dict
        resolved = conninfo_to_dict(dsn)
        if (resolved.get("dbname") != confirmation
                or resolved.get("host") not in {"127.0.0.1", "localhost", "::1"}
                or resolved.get("hostaddr") or resolved.get("service") or resolved.get("options")):
            raise ValueError("resolved scope")
    except Exception as exc:
        raise DemoError("DISPOSABLE_DB_REQUIRED") from exc
    return dsn


def _cli(*args: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "app.services.grounding.corpus_cli", *args],
        cwd=API_DIR, env=os.environ.copy(), capture_output=True, text=True,
        encoding="utf-8", timeout=60, check=False,
    )
    try:
        receipt = json.loads(completed.stdout.strip())
        if not isinstance(receipt, dict) or not receipt.get("ok") or completed.returncode:
            raise ValueError("not successful")
    except (json.JSONDecodeError, ValueError) as exc:
        # CLI error output is intentionally not echoed (nor is the DSN/stderr).
        raise DemoError("OPERATOR_STEP_FAILED") from exc
    return receipt


def _key(index: int, subject_id: str) -> str:
    return f"ragv2-demo-v1-{index}-{subject_id}"


def _expected_corpus_id(index: int, subject_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"aearn-corpus-fixture-v1:{subject_id}:fixture-v1:{_key(index, subject_id)}-reindex")


def _publish(scenarios: tuple[Any, ...]) -> dict[str, tuple[UUID, str]]:
    from app.services.grounding.corpus_fixture_policy import FIXTURE_VERSION

    published: dict[str, tuple[UUID, str]] = {}
    for index, scenario in enumerate(scenarios):
        key = _key(index, scenario.subject_id)
        created = _cli("reindex", "--subject", scenario.subject_id,
                       "--subject-version", FIXTURE_VERSION, "--mode", "fixture",
                       "--idempotency-key", f"{key}-reindex")
        corpus_id = UUID(created["corpus_id"])
        validated = _cli("validate", "--corpus-id", str(corpus_id),
                         "--expected-generation", "0", "--idempotency-key", f"{key}-validate")
        if validated.get("code") not in {"VALIDATED", "VALIDATION_REPLAY"} or not validated.get("validation", {}).get("passed"):
            raise DemoError("VALIDATION_FAILED")
        summary_hash = validated["summary_hash"]
        difference = _cli("diff", "--candidate-id", str(corpus_id),
                          "--idempotency-key", f"{key}-diff")
        if difference.get("base_generation") != 0:
            raise DemoError("NONEMPTY_BASELINE")
        activated = _cli("activate", "--candidate-id", str(corpus_id),
                         "--expected-generation", "0", "--summary-hash", summary_hash,
                         "--idempotency-key", f"{key}-activate")
        if activated.get("code") not in {"ACTIVATED", "ACTIVATION_REPLAY"} or activated.get("observed_generation") != 1:
            raise DemoError("ACTIVATION_FAILED")
        published[scenario.subject_id] = corpus_id, summary_hash
    return published


def _read_back(conn: Any, scenarios: tuple[Any, ...],
               published: dict[str, tuple[UUID, str]]) -> dict[str, Any]:
    from app.services.grounding.hybrid_retrieval import (
        DeterministicFakeEmbeddingRetriever, EmbeddingCandidate,
        SyntheticEmbeddingConfig, retrieve_grounding_v2, synthetic_embedding_receipt,
    )
    from app.services.grounding.retrieval_contracts import (
        ActiveCorpusSelector, GroundingRetrievalRequest,
    )
    from app.services.grounding.subject_registry import capability_projection
    from app.services.learning.contracts import LearningPlan, LearningPlanModule, LearningPlanNode
    from app.services.learning.plan_coverage import (
        NodeSourceRequirement, PlanCoveragePreflightService,
        PlanCoverageShadowAdapter, PostgresPlanFactReader,
    )

    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        corpus_id, summary_hash = published[scenario.subject_id]
        request = GroundingRetrievalRequest(
            subject_id=scenario.subject_id, subject_version="fixture-v1",
            corpus_selector=ActiveCorpusSelector(expected_generation=1, expected_summary_hash=summary_hash),
            query_text=scenario.query_text, required_facets=scenario.required_facets,
            stage="lesson_authoring", embedding_mode="disabled",
        )
        result = retrieve_grounding_v2(conn, request)
        projection = capability_projection(scenario.subject_id)
        if (result.plan is None or result.plan.corpus_id != corpus_id
                or not result.plan.synthetic_fixture or result.coverage.status != "satisfied"
                or result.coverage.covered_facets != scenario.required_facets
                or projection is None or projection.public_course_admissible
                or projection.release_state != ("fixture_only" if scenario.fixture_only else "shadow")):
            raise DemoError("FIXTURE_RETRIEVAL_FAILED")
        results.append({"subject": scenario.subject_id, "route_family": scenario.route_family,
                        "release_state": projection.release_state,
                        "synthetic_fixture": True, "active_fixture_corpus": True,
                        "public_course_admissible": projection.public_course_admissible,
                        "coverage_basis": "synthetic_fixture", "coverage": result.coverage.status,
                        "facets": list(result.coverage.covered_facets),
                        "sources": result.coverage.source_count, "evidence_count": len(result.evidence),
                        "corpus_id": str(corpus_id), "corpus_summary_hash": summary_hash,
                        "retrieval_hash": result.result_hash, "coverage_hash": result.coverage.report_hash,
                        "public": False})

    # Augmentation is a synthetic ID port, never a real embedding provider.
    first = scenarios[0]
    request = GroundingRetrievalRequest(
        subject_id=first.subject_id, subject_version="fixture-v1",
        corpus_selector=ActiveCorpusSelector(), query_text=first.query_text,
        required_facets=first.required_facets, stage="lesson_authoring", embedding_mode="optional",
    )
    baseline = retrieve_grounding_v2(conn, request)
    if baseline.plan is None or not baseline.evidence:
        raise DemoError("FAKE_EMBEDDING_BASELINE_FAILED")
    config = SyntheticEmbeddingConfig(model_id="fake-demo-v1", dimension=3,
                                      normalization_version="unit-v1")
    evidence = baseline.evidence[0]
    candidate = EmbeddingCandidate(
        corpus_id=baseline.plan.corpus_id, chunk_id=evidence.chunk_id,
        chunk_hash=evidence.chunk_hash,
        synthetic_receipt=synthetic_embedding_receipt(baseline.plan, config),
        model_id=config.model_id, dimension=config.dimension,
        normalization_version=config.normalization_version,
    )
    valid = retrieve_grounding_v2(
        conn, request, embedding=DeterministicFakeEmbeddingRetriever((candidate,)),
        synthetic_config=config,
    )
    invalid = retrieve_grounding_v2(
        conn, request, embedding=DeterministicFakeEmbeddingRetriever((
            candidate.model_copy(update={"chunk_hash": "0" * 64}),
        )), synthetic_config=config,
    )

    class FailingFake:
        def search(self, _request: Any) -> tuple[Any, ...]:
            raise RuntimeError("fake adapter failed")

    failed = retrieve_grounding_v2(conn, request, embedding=FailingFake(), synthetic_config=config)
    if (valid.coverage.status != "satisfied" or "EMBEDDING_UNAVAILABLE" in valid.coverage.reason_codes
            or invalid != baseline or failed != baseline):
        raise DemoError("FAKE_EMBEDDING_FALLBACK_FAILED")

    # No learner tables, plan persistence or public confirmation. The optional
    # LangChain facet has no fixture-v1 slice, and fixture-only blocks regardless.
    _, ai_hash = published["python.ai-applications"]
    draft = LearningPlan(
        title="Synthetic LangChain goal", target_level="beginner",
        generator_version="fixture-v1", policy_version="fixture-v1", change_reason="demo",
        modules=(LearningPlanModule(
            module_key="m1", title="LangChain", description="", order_index=0,
            is_core=True, is_skippable=False,
            nodes=(LearningPlanNode(
                knowledge_key="lc-overview", title="LangChain core", description="",
                order_index=0, is_core=True, prerequisite_keys=(),
                required_capabilities=("lesson", "practice"),
            ),),
        ),),
    )
    requirement = NodeSourceRequirement(
        knowledge_key="lc-overview", subject_id="python.ai-applications",
        subject_version="fixture-v1", required_facets=("langchain-core",),
        required_capabilities=("lesson", "practice"), expected_corpus_generation=1,
        expected_corpus_summary_hash=ai_hash,
    )
    adapter = PlanCoverageShadowAdapter(PlanCoveragePreflightService(
        PostgresPlanFactReader(conn, retrieve=retrieve_grounding_v2)), enabled=True)
    shadow = adapter.evaluate(draft, (requirement,), expected_plan_hash=draft.content_hash)
    if (shadow is None or not shadow.activation_blocked or shadow.nodes[0].status == "supported"
            or "wait_for_release" not in shadow.nodes[0].allowed_actions
            or shadow.nodes[0].missing_facets != ("langchain-core",)):
        raise DemoError("PREFLIGHT_NOT_BLOCKED")
    return {
        "subjects": results,
        "fake_embedding": {"synthetic_valid": valid.coverage.status == "satisfied",
                           "invalid_fallback_to_fts": invalid == baseline,
                           "failing_fallback_to_fts": failed == baseline,
                           "real_provider": False},
        "shadow_preflight": {"subject": "python.ai-applications", "node": "lc-overview",
                             "core_goal": True, "coverage": shadow.nodes[0].corpus_status,
                             "activation_blocked": shadow.activation_blocked,
                             "reason_codes": list(shadow.nodes[0].reason_codes),
                             "action": "wait_for_release", "preflight_hash": shadow.report_hash,
                             "public": False},
    }


def _demo(dsn: str, confirmed_name: str) -> dict[str, Any]:
    # App modules load only after the guard has checked explicit opt-in and scope.
    sys.path.insert(0, str(API_DIR))
    import psycopg
    from psycopg.rows import dict_row

    from app.services.grounding.fixtures_v2 import fixture_scenarios, validate_fixture_scenarios

    scenarios = fixture_scenarios()
    if validate_fixture_scenarios() or len(scenarios) != 10:
        raise DemoError("SCENARIO_MANIFEST_INVALID")
    # Accept only a fresh corpus DB or this exact demo's already-published
    # identities/pointers. Never repair partial or foreign state automatically.
    with psycopg.connect(dsn, row_factory=dict_row, autocommit=True, connect_timeout=10) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            identity = conn.execute(
                "SELECT current_database() AS database, host(inet_server_addr()) AS server_address"
            ).fetchone()
            if (identity is None or identity["database"] != confirmed_name
                    or conn.info.dbname != identity["database"]
                    or conn.info.host not in {"127.0.0.1", "localhost", "::1"}
                    or identity["server_address"] is None):
                raise DemoError("CONNECTED_DB_SCOPE_INVALID")
            address = ipaddress.ip_address(identity["server_address"])
            # Docker bridge addresses can be private rather than loopback on the server.
            if address.is_unspecified or address.is_multicast or not (address.is_loopback or address.is_private):
                raise DemoError("CONNECTED_DB_SCOPE_INVALID")
            versions = conn.execute(
                "SELECT id,subject_id,state FROM grounding_corpus_versions ORDER BY id LIMIT %s",
                (len(scenarios) + 1,),
            ).fetchall()
            pointers = conn.execute(
                "SELECT subject_id,corpus_version_id,generation FROM grounding_active_corpora ORDER BY subject_id LIMIT %s",
                (len(scenarios) + 1,),
            ).fetchall()
            events = conn.execute(
                "SELECT corpus_version_id,subject_id,event_kind,idempotency_key FROM grounding_corpus_events ORDER BY id LIMIT %s",
                (len(scenarios) * 5 + 1,),
            ).fetchall()
            expected = {item.subject_id: _expected_corpus_id(index, item.subject_id)
                        for index, item in enumerate(scenarios)}
            expected_events = {
                (corpus_id, scenario.subject_id, kind, f"{_key(index, scenario.subject_id)}-{suffix}")
                for index, scenario in enumerate(scenarios)
                for corpus_id in (expected[scenario.subject_id],)
                for kind, suffix in (("reindex_started", "reindex"),
                                     ("reindex_completed", "reindex"),
                                     ("validation_passed", "validate"),
                                     ("diff_generated", "diff"),
                                     ("activated", "activate"))
            }
            if versions or pointers or events:
                observed = {row["subject_id"]: row["id"] for row in versions}
                active = {row["subject_id"]: row["corpus_version_id"] for row in pointers}
                observed_events = {(row["corpus_version_id"], row["subject_id"],
                                    row["event_kind"], row["idempotency_key"]) for row in events}
                if (len(versions) != len(scenarios) or observed != expected or active != expected
                        or any(row["state"] != "published" for row in versions)
                        or any(row["generation"] != 1 for row in pointers)
                        or len(events) != len(expected_events) or observed_events != expected_events):
                    raise DemoError("FOREIGN_OR_PARTIAL_CORPUS_DB")
    published = _publish(scenarios)
    with psycopg.connect(dsn, row_factory=dict_row, autocommit=True, connect_timeout=10) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            evidence = _read_back(conn, scenarios, published)
    return {"ok": True, "mode": "fixture_only", "shadow": True, "public": False,
            "real_source": False, "real_embedding": False, "live_runtime": False,
            "learner_writes": False, "deployment_approved": False, **evidence}


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(description="Offline fixture-only RAG v2 evidence")
    parser.add_argument("--run-fixture-demo", action="store_true")
    parser.add_argument("--confirm-disposable-db")
    try:
        args = parser.parse_args(argv)
        dsn = _guard(args.confirm_disposable_db, args.run_fixture_demo)
        report = _demo(dsn, args.confirm_disposable_db)
    except DemoError as exc:
        report = {"ok": False, "code": exc.code}
    except Exception:
        # No arbitrary exception, subprocess stderr, credentials or DSN in output.
        report = {"ok": False, "code": "DEMO_FAILED"}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
