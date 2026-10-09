"""Narrow OFFLINE operator tests; not real D/source/lifecycle acceptance."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

RESEARCH = Path(__file__).resolve().parents[5] / ".trellis/tasks/09-22-multi-agent-item-bank-sandbox/research"


@pytest.fixture(scope="module")
def operator():
    spec = importlib.util.spec_from_file_location("actual_d_native_operator", RESEARCH / "actual-d-native-live-20261007.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_and_explicit_plan_never_open_runtime_or_write(operator, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("zero-IO plan attempted IO")
    monkeypatch.setattr(operator, "helper", forbidden)
    monkeypatch.setattr(operator, "save", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    for args in ([], ["--plan"]):
        assert operator.main(args) == 0
        report = json.loads(capsys.readouterr().out)
        assert not report["database_io"] and not report["live_D_authorized"]
        assert report["provider_calls"] == report["GETs"] == report["signing_key_reads"] == 0


def test_known_owner_fixture_cannot_be_called_live(operator):
    assert operator.fixture_marked({"generator_version": "p6-source-owner-fixture-v1"})
    assert operator.fixture_marked({"input_source": "fixture"})
    assert not operator.fixture_marked({"generator_version": "genuine-unknown"})
    assert not operator.base_report()["live_D_authorized"]  # lack of marker is NOT positive authority


def test_all_missing_chain_steps_reported_without_claiming_authority(operator):
    item = {"fixture_marked": True, "draft_hash_valid": True, "owner_epoch_enabled": False,
        "accepted_provider_count": 0, "verified_exact_plan_action_count": 0,
        "finite_nodes": [], "teaching_selections": [], "status": "draft_ready",
        "chain_counts": dict(private_proof=0, private_bridge=0, assessment_binding=0, confirmed_mapping=0)}
    reasons = operator.missing_reasons(item)
    assert "EXPLICIT_PREPARATION_FIXTURE_NOT_LIVE_D" in reasons
    assert "ORIGINAL_ACTIVE_USER_EPOCH_MISSING" in reasons
    assert "WHOLE_DRAFT_READY_TEACHING_SELECTION_MISSING" in reasons
    assert "NEW_ACTUAL_D_ORACLE_SIGNED_PROOF_MISSING" in reasons
    assert "496_CONFIRMED_MAPPING_MISSING" in reasons
    assert len(reasons) == 11


def test_wrong_database_denies_before_any_schema_or_candidate_read(operator):
    class Offline:
        def execute(self, query):
            assert query == "SELECT current_database() AS name"
            return SimpleNamespace(fetchone=lambda: {"name": "business_database"})
    report = operator.base_report()
    operator.preflight(Offline(), None, report)
    assert report["safe_reason"] == "EXACT_ISOLATED_DATABASE_REQUIRED"
    assert "candidates" not in report


def test_execute_failure_retained_without_credentials_or_error_body(operator, monkeypatch, tmp_path, capsys):
    def denied():
        raise ValueError("postgresql://admin:SECRET_PASSWORD@host/SECRET_DB")
    monkeypatch.setattr(operator, "helper", denied)
    monkeypatch.setattr(operator, "OUTPUT", tmp_path)
    assert operator.main(["--execute"]) == 2
    assert "SECRET" not in capsys.readouterr().out
    results = list(tmp_path.glob("*/result.json"))
    assert len(results) == 1
    result = json.loads(results[0].read_text(encoding="utf8"))
    assert result["safe_reason"] == "DETAILS_WITHHELD" and not result["committed"]
    assert "SECRET" not in results[0].read_text(encoding="utf8")
    assert operator.main(["--execute"]) == 2
    assert len(list(tmp_path.glob("*/result.json"))) == 2  # failure never overwritten


@pytest.fixture(scope="module")
def finite_operator():
    spec = importlib.util.spec_from_file_location("actual_d_finite_draft_operator", RESEARCH / "actual-d-finite-draft-live-20261007.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_finite_plan_is_exact_within_original_bound_and_no_IO(finite_operator, monkeypatch, capsys):
    import psycopg
    from app.services.learning.item_supply.finite_course_mapping import finite_node_description
    def forbidden(*args, **kwargs):
        pytest.fail("finite plan attempted live IO")
    monkeypatch.setattr(finite_operator, "load_existing", forbidden)
    monkeypatch.setattr(finite_operator, "save", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    assert finite_operator.main(["--plan"]) == 0
    report = json.loads(capsys.readouterr().out)
    prepared = report["plan"]
    assert prepared["module_characters"] == 323 and prepared["original_module_bound"] == 360
    assert prepared["module"]["nodes"][0]["description"] == finite_node_description("python-kc-binding-v1")
    assert prepared["input_runs"] == 1 and not report["database_io"]
    assert len(prepared["learner_request"]) <= 1100
    assert prepared["refresher_characters"] <= 360
    assert prepared["refresher_module"]["nodes"][0]["required_capabilities"] == ["python"]


def test_finite_execute_cannot_reset_existing_http_window(finite_operator, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid window reached execution")
    monkeypatch.setattr(finite_operator, "load_existing", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    with pytest.raises(SystemExit) as denied:
        finite_operator.main(["--execute"])
    assert denied.value.code == 2
    with pytest.raises(SystemExit):
        finite_operator.main(["--execute", "--prior-http-attempts", "7", "--cumulative-http-cap", "8"])


def test_finite_validation_uses_original_draft_artifact_not_output_repair(finite_operator):
    from app.services.learning.plan_drafting import (
        CompactPlanModule, CompactPlanProfile, LearningPlanSourceSummary, build_plan_draft)
    from app.services.learning.contracts import canonical_plan_payload
    from uuid import uuid4
    prepared = finite_operator.plan()
    profile = CompactPlanProfile(language_id="python", goal_text=prepared["facts"]["goal_text"],
        target_level="beginner", weekly_minutes=60, experience_level="beginner", pace_summary="Short session", title="Bindings")
    def row(description):
        requested = json.loads(json.dumps(prepared["module"]))
        requested["nodes"][0]["description"] = description
        artifact = build_plan_draft(profile=profile, modules=(CompactPlanModule.model_validate(prepared["refresher_module"]),
            CompactPlanModule.model_validate(requested)),
            sources=(LearningPlanSourceSummary("offline.test", "OFFLINE data, not source authority", "internal"),),
            change_reason="OFFLINE operator validation only")
        return dict(id=uuid4(), draft_version=1, source_run_id=uuid4(), source_input_revision=1,
            content_hash=artifact.content_hash, profile_json=profile.model_dump(mode="json"),
            plan_json=canonical_plan_payload(artifact.plan), source_summary_json=[s.as_dict() for s in artifact.sources],
            generator_version=artifact.plan.generator_version, policy_version=artifact.plan.policy_version,
            change_reason=artifact.plan.change_reason)
    valid = row(prepared["module"]["nodes"][0]["description"])
    assert finite_operator.validate_finite(valid)["draft_id"] == str(valid["id"])
    invalid = row("Different learning goal")
    before = invalid["plan_json"]["modules"][1]["nodes"][0]["description"]
    with pytest.raises(finite_operator.Pending, match="EXACT_FINITE_NODE_SEMANTICS_MISMATCH"):
        finite_operator.validate_finite(invalid)
    assert invalid["plan_json"]["modules"][1]["nodes"][0]["description"] == before


def test_existing_parent_composition_imports_without_IO(finite_operator, monkeypatch):
    import psycopg
    import dotenv
    def forbidden(*args, **kwargs):
        pytest.fail("composition import attempted live IO or secret loading")
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(dotenv, "dotenv_values", forbidden)
    parent, source, candidate = finite_operator.load_existing()
    assert parent.CountedClient.__module__ == "run"
    assert parent.SharedHttpBudget.__module__ == "run"
    assert parent.TutorInteractiveRunDispatcher.__module__ == "app.services.tutor.interactive"
    assert source["DB"] == "aearn_b1d_sandbox_20261001"
    assert callable(candidate["settings_for_execute"])


@pytest.fixture(scope="module")
def preparation_helper():
    import sys
    spec = importlib.util.spec_from_file_location("actual_d_preparation_helper", RESEARCH / "actual_d_native_live_support_20261007.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_preparation_disabled_or_missing_teaching_owner_is_zero_IO(preparation_helper):
    from uuid import uuid4
    class NoIO:
        def __getattr__(self, name):
            pytest.fail("missing teaching owner attempted IO")
    args = dict(user_id=uuid4(), session_id=uuid4(), draft_id=uuid4(), receipts=NoIO(),
        capture_id=uuid4(), document_handle="document.private.pending")
    closed = preparation_helper.prepare_kc_actual_d(NoIO(), **args)
    assert closed.status == "disabled"
    missing = preparation_helper.prepare_kc_actual_d(NoIO(), **args, enabled=True)
    assert missing.reason == "TEACHING_CONSUMPTION_OWNER_REQUIRED"
    assert missing.selection is None and missing.prepared is None
    assert missing.safe_report()["source_oracle_executed"] is False


def test_preparation_rejects_assessment_resolver_as_teaching(preparation_helper):
    from app.services.grounding.evidence_binding_v2 import EvidenceSelection
    from app.services.grounding.autonomous.assessment_receipt_repository import (
        AssessmentReceiptRepository, PostgresAssessmentConsumeAuthority)
    # Deliberately incomplete OFFLINE objects are only negative protocol inputs.
    # No signature, current callback, selection or source proof is simulated.
    conn = object()
    receipts = object.__new__(AssessmentReceiptRepository)
    receipts.conn = conn
    teaching = object.__new__(EvidenceSelection)
    teaching.conn = conn
    teaching.governance = SimpleNamespace(conn=conn)
    teaching.selections = SimpleNamespace(conn=conn)
    teaching.authority_resolver = PostgresAssessmentConsumeAuthority(receipts)
    with pytest.raises(preparation_helper.PreparationPending, match="TEACHING_CONSUMPTION_OWNER_REQUIRED"):
        preparation_helper._ports(conn, teaching, receipts)


def test_preparation_requirements_cover_exact_both_goals_without_source_authority(preparation_helper, finite_operator):
    from uuid import uuid4
    from app.services.grounding.material_contracts_v2 import DraftScope
    from app.services.learning.plan_drafting import CompactPlanModule
    prepared = finite_operator.plan()
    nodes = {n.knowledge_key: n.model_dump(mode="json") for module in
        (prepared["refresher_module"], prepared["module"])
        for n in CompactPlanModule.model_validate(module).nodes}
    scope = DraftScope(user_id=str(uuid4()), session_id=str(uuid4()), conversation_id=str(uuid4()),
        draft_id=str(uuid4()), draft_version=1, content_hash="a"*64, source_run_id=str(uuid4()), source_input_revision=1)
    resolver = preparation_helper.KcTeachingRequirements()
    requirements = resolver.resolve(scope, {"language_id": "python"}, nodes)
    assert {r.node_id for r in requirements} == {"python.basics", "python.bind"}
    assert len({r.demand.demand_hash for r in requirements}) == 2
    assert all(r.demand.purpose == "main_teaching" and r.demand.scope.facets == ("fundamentals",)
        and r.demand.plan_ref == "draft."+scope.draft_id for r in requirements)
    assert requirements == resolver.resolve(scope, {"language_id": "python"}, nodes)
    newer = scope.model_copy(update={"source_input_revision": 2})
    assert requirements != resolver.resolve(newer, {"language_id": "python"}, nodes)
    with pytest.raises(preparation_helper.PreparationPending, match="WHOLE_DRAFT"):
        resolver.resolve(scope, {"language_id": "python"}, {"python.bind": nodes["python.bind"]})
    changed = dict(nodes)
    changed["python.bind"] = dict(nodes["python.bind"], description="Different goal")
    with pytest.raises(preparation_helper.PreparationPending, match="GOAL_REQUIRED"):
        resolver.resolve(scope, {"language_id": "python"}, changed)


def test_kc_teaching_compose_installs_concrete_request_and_resolver_without_IO(preparation_helper):
    from app.services.grounding.autonomous.corpus_governance import CorpusGovernance, PostgresCorpusAuthority
    from app.services.grounding.autonomous.public_python_teaching_review import PublicPythonTeachingVerifier
    from app.services.grounding.evidence_binding_v2 import EvidenceSelection
    conn = object()
    verifier = object.__new__(PublicPythonTeachingVerifier)
    verifier.conn, verifier.enabled = conn, True
    governance = object.__new__(CorpusGovernance)
    governance.conn, governance.authority = conn, PostgresCorpusAuthority()
    governance.source_reviews = SimpleNamespace(conn=conn, teaching_verifier=verifier)
    # Composition only: intentionally no current receipt/signature/source data.
    selector = preparation_helper.compose_kc_teaching(conn, draft=None, governance=governance, enabled=True)
    assert type(selector) is EvidenceSelection and selector.conn is conn and selector.selections.conn is conn
    owner = selector.authority_resolver
    assert type(owner) is preparation_helper.KcTeachingConsumptionOwner
    assert selector.request_for.__self__ is owner and owner.verifier is verifier
    with pytest.raises(preparation_helper.PreparationPending):
        preparation_helper.compose_kc_teaching(conn, draft=None, governance=governance)


def test_kc_consumer_denies_missing_current_corpus_not_shape_approval(preparation_helper, monkeypatch):
    from app.services.grounding.autonomous.corpus_governance import PostgresQualificationAuthority
    owner = object.__new__(preparation_helper.KcTeachingConsumptionOwner)
    requirement = SimpleNamespace(demand=object())
    owner.governance = object()
    owner.verifier = SimpleNamespace(review=SimpleNamespace(payload=SimpleNamespace(prepared=object())))
    monkeypatch.setattr(owner, "_requirements", lambda: (requirement,))
    monkeypatch.setattr(PostgresQualificationAuthority, "resolve", lambda *_: None)
    with pytest.raises(preparation_helper.PreparationPending, match="CURRENT_MAIN_TEACHING_CORPUS_REQUIRED"):
        owner.request_for(requirement)


def test_kc_consumer_does_not_accept_arbitrary_or_assessment_demand(preparation_helper, monkeypatch):
    owner = object.__new__(preparation_helper.KcTeachingConsumptionOwner)
    requirement = SimpleNamespace(demand=SimpleNamespace(demand_hash="a"*64))
    monkeypatch.setattr(owner, "_requirements", lambda: (requirement,))
    def forbidden(*args, **kwargs):
        pytest.fail("unmatched demand reached source/root authority")
    monkeypatch.setattr(owner, "_current_snapshot", forbidden)
    assert owner.resolve(SimpleNamespace(demand_hash="b"*64, action="consume", purpose="main_teaching")) is None
    assert owner.resolve(SimpleNamespace(demand_hash="a"*64, action="consume", purpose="assessment_evidence")) is None
