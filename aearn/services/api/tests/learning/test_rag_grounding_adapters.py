"""No-network, fake-read-only-DB checks for the internal RAG v2 shadow adapter."""
from __future__ import annotations

import ast
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from psycopg import Connection

from app.services.grounding.corpus_fixture_policy import (
    FIXTURE_DOMAIN, FIXTURE_FETCHED_AT, FIXTURE_VERSION, fixture_registry_digest, fixture_slices,
)
from app.services.grounding.coverage import select_evidence
from app.services.grounding.retrieval_planner import resolve_plan
from app.services.grounding.retrieval_contracts import (
    ActiveCorpusSelector,
    GroundingRetrievalRequest, GroundingRetrievalResultV2, RetrievalCandidate, stable_hash,
)
from app.services.grounding.subject_registry import all_grounding_subjects, get_grounding_subject
from app.services.learning.grounding_adapters import (
    project_v2_legacy_shadow, shadow_grounding_status,
)
from app.services.learning.lesson_contracts import LessonSourceSnapshot
from app.services.grounding.grounding_citations import AgentGroundingItem


class ReadOnlyFake:
    def __init__(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        self.rows = rows
        self.reads: list[str] = []
        self.selected: list[dict[str, Any]] = []

    def execute(self, sql: str, params: tuple[object, ...]) -> ReadOnlyFake:
        assert sql.startswith("SELECT ") and " FOR UPDATE" not in sql
        self.reads.append(sql)
        if "grounding_active_corpora" in sql:
            self.selected = self.rows["pointer"]
        elif "grounding_corpus_versions" in sql:
            self.selected = self.rows["version"]
        else:
            self.selected = next(
                value for key, value in self.rows.items() if key in sql and key not in {"pointer", "version"}
            )
        if "LIMIT %s" in sql:
            self.selected = self.selected[: cast(int, params[-1])]
        return self

    def fetchone(self) -> dict[str, Any] | None:
        return self.selected[0] if self.selected else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.selected


def _case(subject_id: str = "route.python", stage: str = "lesson_authoring",
          budget_profile: str = "standard") -> tuple[ReadOnlyFake, GroundingRetrievalRequest, GroundingRetrievalResultV2]:
    subject = get_grounding_subject(subject_id)
    assert subject is not None
    corpus_id = UUID("00000000-0000-0000-0000-000000000001")
    trust = "official" if subject.source_trust_policy == "official" else "trusted_de_facto"
    rows: dict[str, list[dict[str, Any]]] = {
        "pointer": [{"corpus_version_id": corpus_id, "generation": 1}],
        "version": [], "grounding_corpus_source_snapshots": [],
        "grounding_corpus_documents": [], "grounding_corpus_chunks": [],
    }
    for item in fixture_slices(subject):
        sh = stable_hash({
            "subject_id": subject_id, "subject_version": FIXTURE_VERSION,
            "source_id": item.source_id, "trust_tier": trust, "source_kind": "fixture",
            "source_version": FIXTURE_VERSION, "allowed_domains": (FIXTURE_DOMAIN,),
            "seed_urls": (item.url,), "facets": (item.facet,),
        })
        ch = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
        document_id = f"{item.source_id}:document"
        rows["grounding_corpus_source_snapshots"].append({
            "source_id": item.source_id, "source_hash": sh, "trust_tier": trust,
            "source_kind": "fixture", "source_version": FIXTURE_VERSION,
            "allowed_domains_json": [FIXTURE_DOMAIN], "seed_urls_json": [item.url],
            "facets_json": [item.facet],
        })
        rows["grounding_corpus_documents"].append({
            "document_id": document_id, "source_id": item.source_id,
            "source_hash": sh, "trust_tier": trust, "canonical_url": item.url,
            "final_url": item.url, "content_type": "text/plain",
            "document_version": FIXTURE_VERSION, "fetched_at": FIXTURE_FETCHED_AT,
            "document_hash": ch, "parse_status": "parsed",
        })
        rows["grounding_corpus_chunks"].append({
            "chunk_id": f"{item.source_id}:chunk", "document_id": document_id,
            "source_id": item.source_id, "source_hash": sh, "trust_tier": trust,
            "document_hash": ch, "ordinal": 0,
            "title": f"Fixture: {subject_id} / {item.facet}",
            "section_path": item.facet, "content": item.content,
            "facets_json": [item.facet], "topic_tags_json": [], "chunk_hash": ch,
        })
    for name in ("grounding_corpus_source_snapshots", "grounding_corpus_documents", "grounding_corpus_chunks"):
        key = {"grounding_corpus_source_snapshots": "source_id", "grounding_corpus_documents": "document_id", "grounding_corpus_chunks": "chunk_id"}[name]
        rows[name].sort(key=lambda row: row[key])
    sources = rows["grounding_corpus_source_snapshots"]
    documents = rows["grounding_corpus_documents"]
    chunks = rows["grounding_corpus_chunks"]
    source_hash = stable_hash([{"source_id": row["source_id"], "source_hash": row["source_hash"]} for row in sources])
    content_hash = stable_hash([
        [{"document_id": row["document_id"], "source_id": row["source_id"],
          "document_hash": row["document_hash"]} for row in documents],
        [{"chunk_id": row["chunk_id"], "document_id": row["document_id"],
          "chunk_hash": row["chunk_hash"]} for row in chunks],
    ])
    registry = fixture_registry_digest(subject)
    validation: dict[str, object] = {"ok": True}
    coverage: dict[str, object] = {"count": len(chunks)}
    summary = stable_hash([str(corpus_id), registry, source_hash, content_hash, validation, coverage,
                           "fixture-fts-v1", "fixture-facets-v1"])
    rows["version"].append({
        "id": corpus_id, "subject_id": subject_id, "subject_version": FIXTURE_VERSION,
        "state": "published", "registry_digest": registry, "summary_hash": summary,
        "source_set_hash": source_hash, "content_hash": content_hash,
        "validation_summary_json": validation, "coverage_summary_json": coverage,
        "retrieval_policy_version": "fixture-fts-v1", "coverage_policy_version": "fixture-facets-v1",
    })
    facet = subject.required_facets[0]
    request = GroundingRetrievalRequest(
        subject_id=subject_id, subject_version=FIXTURE_VERSION,
        corpus_selector=ActiveCorpusSelector(expected_generation=1, expected_summary_hash=summary),
        query_text=facet, required_facets=(facet,), stage=cast(Any, stage),
        budget_profile=cast(Any, budget_profile),
    )
    req_hash = stable_hash(request.model_dump(mode="json"))
    # Produce the same server-owned plan a published fixture corpus would return,
    # rather than constructing a self-consistent but invalid budget by hand.
    plan, reason = resolve_plan(_conn(ReadOnlyFake(rows)), request)
    assert reason is None and plan is not None
    chunk = next(row for row in chunks if row["section_path"] == facet)
    candidate = RetrievalCandidate(
        chunk_id=chunk["chunk_id"], source_id=chunk["source_id"],
        document_id=chunk["document_id"], title=chunk["title"],
        section_path=chunk["section_path"], content=chunk["content"],
        facets=tuple(chunk["facets_json"]), trust_tier=trust,
        source_hash=chunk["source_hash"], document_hash=chunk["document_hash"],
        chunk_hash=chunk["chunk_hash"], fts_rank=1,
    )
    evidence, report = select_evidence(plan, (candidate,))
    result = GroundingRetrievalResultV2(
        request_hash=req_hash, plan=plan, evidence=evidence, coverage=report,
        result_hash=stable_hash((plan.plan_hash, report.report_hash,
                                tuple(item.model_dump(mode="json") for item in evidence))),
    )
    return ReadOnlyFake(rows), request, result


def _conn(fake: ReadOnlyFake) -> Connection[dict[str, Any]]:
    return cast(Connection[dict[str, Any]], fake)


@pytest.mark.parametrize("subject_id", [subject.subject_id for subject in all_grounding_subjects()])
@pytest.mark.parametrize("stage", ["lesson_authoring", "tutor_focus"])
@pytest.mark.parametrize("budget_profile", ["standard", "compact"])
def test_internal_shadow_shapes_are_synthetic_and_public_blocked(
    subject_id: str, stage: str, budget_profile: str,
) -> None:
    fake, request, result = _case(subject_id, stage, budget_profile)
    before = deepcopy(fake.rows)
    output = project_v2_legacy_shadow(_conn(fake), request, result, enabled=True)
    assert output.status.corpus_state == "active_fixture"
    assert output.status.public_availability == "unavailable" and output.public_blocked
    assert result.plan is not None
    assert output.corpus_id == result.plan.corpus_id
    assert output.corpus_summary_hash == result.plan.corpus_summary_hash
    assert output.corpus_content_hash == result.plan.corpus_content_hash
    assert output.registry_digest == result.plan.registry_digest
    assert output.evidence_identities[0].chunk_id == result.evidence[0].chunk_id
    assert len(output.lesson_sources) == len(output.tutor_items) == 1
    lesson, tutor = output.lesson_sources[0], output.tutor_items[0]
    assert isinstance(lesson, LessonSourceSnapshot) and isinstance(tutor, AgentGroundingItem)
    assert lesson.trust_tier == tutor.citation.source_trust_tier == "internal"
    assert lesson.evidence_excerpt == tutor.content == result.evidence[0].content
    assert lesson.chunk_content_hash == tutor.citation.content_hash == result.evidence[0].chunk_hash
    assert lesson.document_content_hash == tutor.citation.document_content_hash == result.evidence[0].document_hash
    assert lesson.fetched_at == lesson.snapshotted_at == FIXTURE_FETCHED_AT
    assert lesson.canonical_url == tutor.citation.canonical_url
    assert lesson.citation_id == tutor.citation.citation_id
    assert lesson.grounding_chunk_id.startswith("v2-shadow:")
    assert fake.rows == before and all(sql.startswith("SELECT ") for sql in fake.reads)
    assert project_v2_legacy_shadow(_conn(fake), request, result, enabled=True) == output


def test_disabled_gate_never_reads_db() -> None:
    fake, request, result = _case()
    assert shadow_grounding_status(_conn(fake), request.subject_id).corpus_state == "disabled"
    output = project_v2_legacy_shadow(_conn(fake), request, result)
    assert output.status.corpus_state == "disabled" and not output.lesson_sources and not output.tutor_items
    assert not fake.reads
    assert shadow_grounding_status(_conn(fake), request.subject_id, enabled=True).corpus_state == "active_fixture"
    assert shadow_grounding_status(_conn(fake), request.subject_id, enabled=True).public_availability == "unavailable"


@pytest.mark.parametrize("mutation", [
    "candidate", "retired", "wrong_version", "wrong_summary", "wrong_source", "wrong_url",
    "wrong_content", "extra_chunk", "extra_source", "stale_generation", "forged_evidence", "forged_result",
    "wrong_scope", "partial_coverage", "forged_coverage_count", "wrong_corpus",
    "extra_document", "unselected_content", "wrong_fetched_at",
])
def test_untrusted_or_unpublished_evidence_fails_closed(mutation: str) -> None:
    fake, request, result = _case("python.fastapi")
    version = fake.rows["version"][0]
    if mutation in {"candidate", "retired"}:
        version["state"] = mutation
    elif mutation == "wrong_version":
        version["subject_version"] = "other-v1"
    elif mutation == "wrong_summary":
        version["summary_hash"] = "a" * 64
    elif mutation == "wrong_source":
        fake.rows["grounding_corpus_source_snapshots"][0]["source_hash"] = "b" * 64
    elif mutation == "wrong_url":
        fake.rows["grounding_corpus_documents"][0]["canonical_url"] = "https://evil.example/"
    elif mutation == "wrong_content":
        fake.rows["grounding_corpus_chunks"][0]["content"] = "forged text"
    elif mutation == "extra_chunk":
        fake.rows["grounding_corpus_chunks"].append(deepcopy(fake.rows["grounding_corpus_chunks"][0]))
    elif mutation == "extra_document":
        fake.rows["grounding_corpus_documents"].append(deepcopy(fake.rows["grounding_corpus_documents"][0]))
    elif mutation == "unselected_content":
        fake.rows["grounding_corpus_chunks"][1]["content"] = "other forged fixture"
    elif mutation == "wrong_fetched_at":
        fake.rows["grounding_corpus_documents"][0]["fetched_at"] = None
    elif mutation == "extra_source":
        fake.rows["grounding_corpus_source_snapshots"].append(
            {**fake.rows["grounding_corpus_source_snapshots"][0], "source_id": "unjoined-extra"}
        )
    elif mutation == "stale_generation":
        fake.rows["pointer"][0]["generation"] = 2
    elif mutation == "forged_evidence":
        result = result.model_copy(update={"evidence": (result.evidence[0].model_copy(update={"content": "forged"}),)})
    elif mutation == "forged_result":
        result = result.model_copy(update={"result_hash": "c" * 64})
    elif mutation == "wrong_scope":
        request = request.model_copy(update={"subject_version": "other-v1"})
    elif mutation == "wrong_corpus":
        fake.rows["pointer"][0]["corpus_version_id"] = UUID("00000000-0000-0000-0000-000000000002")
    elif mutation == "forged_coverage_count":
        report = result.coverage.model_copy(update={"source_count": 2})
        fields = report.model_dump(exclude={"report_hash"})
        report = report.model_copy(update={"report_hash": stable_hash(fields)})
        result = result.model_copy(update={
            "coverage": report, "result_hash": stable_hash((result.plan.plan_hash, report.report_hash,
                tuple(item.model_dump(mode="json") for item in result.evidence))),
        })
    else:
        result = result.model_copy(update={"coverage": result.coverage.model_copy(update={"status": "partial"})})
    output = project_v2_legacy_shadow(_conn(fake), request, result, enabled=True)
    assert output.status.corpus_state == "unavailable" and output.public_blocked
    assert not output.lesson_sources and not output.tutor_items
    assert all(sql.startswith("SELECT ") for sql in fake.reads)


@pytest.mark.parametrize("field", ["budget", "allowed_source_ids", "allowed_trust_tiers"])
def test_rehashed_caller_plan_cannot_override_server_policy(field: str) -> None:
    fake, request, result = _case("python.fastapi")
    plan = result.plan
    assert plan is not None
    change: object
    if field == "budget":
        change = plan.budget.model_copy(update={"max_characters": plan.budget.max_characters + 1})
    elif field == "allowed_source_ids":
        change = (*plan.allowed_source_ids, "fixture.forged")
    else:
        change = (*plan.allowed_trust_tiers, "trusted_de_facto")
    altered = plan.model_copy(update={field: change})
    altered = altered.model_copy(update={
        "plan_hash": stable_hash(altered.model_dump(exclude={"plan_hash"})),
    })
    forged = result.model_copy(update={
        "plan": altered,
        "result_hash": stable_hash((altered.plan_hash, result.coverage.report_hash,
                                    tuple(item.model_dump(mode="json") for item in result.evidence))),
    })
    output = project_v2_legacy_shadow(_conn(fake), request, forged, enabled=True)
    assert output.status.corpus_state == "unavailable" and not output.lesson_sources
    assert all(sql.startswith("SELECT ") for sql in fake.reads)


def _imports_shadow_adapter(source: str) -> bool:
    """Check direct Python imports, including literal dynamic imports."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name.endswith(".grounding_adapters") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").endswith("grounding_adapters"):
                return True
            if (node.module in {"app.services.learning", "services.learning", "learning", None}
                    and any(alias.name == "grounding_adapters" for alias in node.names)):
                return True
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            target = node.func
            if (isinstance(node.args[0].value, str)
                    and "grounding_adapters" in node.args[0].value
                    and (isinstance(target, ast.Name) and target.id in {"__import__", "import_module"}
                         or isinstance(target, ast.Attribute) and target.attr == "import_module")):
                return True
    return False


@pytest.mark.parametrize("source", [
    "import app.services.learning.grounding_adapters",
    "from app.services.learning.grounding_adapters import project_v2_legacy_shadow",
    "from app.services.learning import grounding_adapters",
    "from . import grounding_adapters",
    "importlib.import_module('app.services.learning.grounding_adapters')",
])
def test_static_import_audit_detects_direct_consumers(source: str) -> None:
    assert _imports_shadow_adapter(source)
    assert not _imports_shadow_adapter("from app.services.learning import lesson_contracts")
    assert not _imports_shadow_adapter("# grounding_adapters is not imported\npass")


def test_no_app_route_consumer_worker_or_startup_imports_shadow_adapter() -> None:
    api_root = Path(__file__).resolve().parents[2]
    roots = (api_root / "app", api_root.parent / "worker")
    owner = api_root / "app" / "services" / "learning" / "grounding_adapters.py"
    assert all(root.is_dir() for root in roots)
    violations = [str(path.relative_to(api_root.parent))
                  for root in roots for path in sorted(root.rglob("*.py"))
                  if path != owner and _imports_shadow_adapter(path.read_text(encoding="utf-8"))]
    assert not violations, f"Shadow compatibility must not be imported by app/worker: {violations}"
    startup = api_root.parents[1] / "scripts" / "start-dev.ps1"
    assert startup.is_file()
    active_lines = [line for line in startup.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    assert not [line for line in active_lines if "grounding_adapters" in line]


def test_rehashed_embedding_degradation_cannot_be_claimed_when_disabled() -> None:
    fake, request, result = _case()
    report = result.coverage.model_copy(update={"reason_codes": ("EMBEDDING_UNAVAILABLE",)})
    report = report.model_copy(update={"report_hash": stable_hash(report.model_dump(exclude={"report_hash"}))})
    assert result.plan is not None
    forged = result.model_copy(update={
        "coverage": report,
        "result_hash": stable_hash((result.plan.plan_hash, report.report_hash,
                                    tuple(item.model_dump(mode="json") for item in result.evidence))),
    })
    output = project_v2_legacy_shadow(_conn(fake), request, forged, enabled=True)
    assert output.status.corpus_state == "unavailable" and not output.lesson_sources


def test_shadow_adapter_has_no_mutation_sql_operator_or_provider_imports() -> None:
    api_root = Path(__file__).resolve().parents[2]
    path = api_root / "app" / "services" / "learning" / "grounding_adapters.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
               for alias in node.names]
    imports.extend(f"{node.module or ''}.{alias.name}" for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom) for alias in node.names)
    forbidden = ("corpus_service", "corpus_repository", "corpus_cli", "corpus_operator",
                 "provider", "httpx", "requests", "urllib")
    assert not [name for name in imports if any(part in name for part in forbidden)]
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)]
    assert not [node for node in calls if node.func.attr in {"commit", "rollback", "executemany"}]
    queries = [node.args[0] for node in calls if node.func.attr == "execute"]
    assert queries and all(isinstance(sql, ast.Constant) and isinstance(sql.value, str)
                           and sql.value.startswith("SELECT ") and " FOR UPDATE" not in sql.value
                           for sql in queries)
