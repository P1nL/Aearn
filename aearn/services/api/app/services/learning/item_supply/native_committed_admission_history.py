"""Exact 547 publication history. Read-only DATA, never an admission/source capability."""
from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_bank.native_publication_contracts import NativePublicationProofV1
from app.services.learning.item_supply.blind_protocol import SINGLE_CHOICE_BLIND_PROTOCOL
from app.services.learning.item_supply.diagnostic_policy import ReviewBundleV3, SharedGenerationPolicyBindingV3, checked_bundle
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.finite_static_blind_scorer import FiniteStaticBlindScorer
from app.services.learning.item_supply.finite_task_ambiguity import build_finite_ambiguity_plan
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, GenerationRequestV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending
from app.services.learning.item_supply.parameter_profiles import ExecutionParameterProfileV1
from app.services.learning.item_supply.review_contracts_v2 import BlindSolveReceiptV2
from app.services.learning.item_supply.review_provider import blind_input
from app.services.learning.item_supply.review_deliberation import substantive_revision_hash
from app.services.learning.item_supply.shared_admission_facts_contracts import IssuedSharedAdmissionFactsV1
from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationBindingV1, bind_shared_candidate_continuation
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2

VERSION = UUID("8ba4ca51-e8f4-540a-b52a-eaec8a0a6764")
ARTIFACT = UUID("4e230bc0-dceb-4d39-bd17-bb5b2a41d8a3")
ACTION = UUID("8bcf957c-d772-534e-9d97-786b609ca639")
LINEAGE = UUID("4228be3f-a129-4c06-a531-4d69a37c1d46")
RECHECK = UUID("f3c2a54f-7f4b-4181-a8c0-ef783f24c919")
SHARED = "tutor_item_supply_shared_"
HISTORY = "committed_admission_history"


def _model(model: type[Any], raw: Any) -> Any:
    return model.model_validate_json(json.dumps(raw))


def _time(value: Any) -> datetime:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("historical timestamp must be aware")
    return stamp


def _stored(conn: Connection[dict[str, Any]], table: str, identity: Any, key: str = "id") -> dict[str, Any]:
    # Table/key are closed call-site literals, never caller identifiers.
    rows = conn.execute("SELECT t.*,t.xmin::text::bigint AS history_xmin,"
        "t.xmin::text::bigint<>(txid_current() %% 4294967296) AS history_committed FROM "
        + table + " t WHERE " + key + "=%s FOR SHARE", (identity,)).fetchall()
    if len(rows) != 1 or rows[0]["history_committed"] is not True:
        raise NativeTypeEvidencePending("native_committed_admission_history_missing")
    return rows[0]


def read_committed_admission_row(conn: Connection[dict[str, Any]], version_id: UUID) -> dict[str, Any] | None:
    """Fallback only for the exact547 normal-v3 publication. No legacy JOIN relaxation."""
    if version_id != VERSION:
        return None
    matches = conn.execute("SELECT n.id FROM tutor_learning_item_native_publication_proofs n "
        "JOIN tutor_item_supply_shared_normal_revision_readmissions nr ON nr.id=n.facts_receipt_id "
        "AND nr.payload_json->>'schema_version'='normal_revision_readmission_v3' "
        "WHERE n.version_id=%s AND n.generation_artifact_id=%s AND nr.id=%s", (VERSION, ARTIFACT, ACTION)).fetchall()
    if len(matches) != 1:
        return None
    h: dict[str, Any] = {}
    for name, table, identity in (
        ("publication", "tutor_learning_item_native_publication_proofs", matches[0]["id"]),
        ("action", SHARED + "persistent_pack_journal", ACTION),
        ("normal", SHARED + "normal_revision_readmissions", ACTION),
        ("facts", SHARED + "admission_facts", ACTION),
        ("artifact", SHARED + "generation_artifacts", ARTIFACT),
        ("lineage", SHARED + "revision_lineage", LINEAGE),
        ("revision", SHARED + "revision_preparations", LINEAGE),
        ("recheck", SHARED + "revision_recheck_receipts", RECHECK),
        ("recheck_preparation", SHARED + "revision_recheck_preparations", RECHECK),
    ):
        h[name] = _stored(conn, table, identity)
    action, facts, publication = h["action"]["payload_json"], h["facts"], h["publication"]
    q = action["quality"]
    for name, table, identity, key in (
        ("preparation", SHARED + "validation_preparations", facts["validation_preparation_id"], "id"),
        ("validation_evidence", SHARED + "validation_evidence", q["validation_evidence_id"], "id"),
        ("validation", SHARED + "pipeline_receipts", facts["validation_receipt_id"], "id"),
        ("blind", SHARED + "pipeline_receipts", facts["blind_receipt_id"], "id"),
        ("review", SHARED + "pipeline_receipts", facts["review_receipt_id"], "id"),
        ("evaluation", SHARED + "pipeline_receipts", publication["evaluation_receipt_id"], "id"),
        ("generation_output", SHARED + "revision_generation_outputs", LINEAGE, "preparation_id"),
        ("adoption", SHARED + "candidate_continuations", q["review_lease"]["job_id"], "job_id"),
        ("generation_policy", SHARED + "generation_policy_bindings", h["artifact"]["candidate_id"], "candidate_id"),
        ("review_reservation", SHARED + "reservations", q["review_budget"]["reservation_id"], "id"),
        ("review_settlement", SHARED + "runtime_settlements", q["review_budget"]["settlement_id"], "id"),
        ("bank_validation", "tutor_learning_item_validation_receipts", publication["proof_json"]["bank_validation_id"], "id"),
        ("import", "tutor_learning_item_import_receipts", publication["proof_json"]["bank_validation_id"], "validation_receipt_id"),
        ("event", "tutor_learning_item_publication_events", publication["publication_event_id"], "id"),
        ("materialization", "tutor_learning_item_practice_materializations", publication["materialization_id"], "id"),
        ("public", "tutor_learning_item_public_contents", VERSION, "version_id"),
    ):
        h[name] = _stored(conn, table, identity, key)
    versions = conn.execute("SELECT *,xmin::text::bigint AS history_xmin,"
        "xmin::text::bigint<>(txid_current() %% 4294967296) AS history_committed "
        "FROM tutor_item_supply_shared_persistent_pack_journal WHERE public_task_id=%s "
        "AND record_kind IN('version','qualified') AND payload_json->>'revision_id'=%s", (action["public_task_id"], action["revision_id"])).fetchall()
    if len(versions) != 2 or {v["record_kind"] for v in versions} != {"version", "qualified"}:
        raise NativeTypeEvidencePending("native_committed_admission_version_missing")
    h.update({v["record_kind"]: v for v in versions})
    h["generation_settlement"] = _stored(conn, SHARED + "runtime_settlements", h["generation_output"]["settlement_id"])
    h["parent"] = _stored(conn, SHARED + "generation_artifacts", h["lineage"]["parent_artifact_id"])
    h["ancestors"] = tuple(_stored(conn, SHARED + "pipeline_receipts", a["receipt_id"])
        for a in h["recheck_preparation"]["payload_json"]["ancestor_reviews"])
    h["profiles"] = tuple(_stored(conn, "tutor_item_supply_parameter_profiles", p, "profile_hash") for p in (
        h["artifact"]["request_json"]["profile"]["profile_hash"], q["review_lease"]["profile"]["profile_hash"], facts["profile_hash"]))
    jobs = conn.execute("SELECT id,root_id,parent_job_id,job_key,item_supply_internal.controlled_counterexample_held(id) AS held "
        "FROM tutor_item_supply_shared_jobs WHERE id=ANY(%s::uuid[]) FOR SHARE", ([h["artifact"]["job_id"],
        h["recheck"]["job_id"], facts["job_id"]],)).fetchall()
    h["jobs"] = jobs
    g = h["artifact"]
    original = conn.execute("SELECT g.*,roots.canonical_key,bp.snapshot_json AS coverage_json,ob.provider_key,"
        "EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=g.job_id AND cp.lease_generation=g.lease_generation "
        "AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=g.artifact_hash) AS generation_completed,"
        "EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=g.reservation_id "
        "AND s.settlement_key='generation.'||replace(g.candidate_id::text,'-','')) AS generation_settled "
        "FROM tutor_item_supply_shared_generation_artifacts g JOIN tutor_item_supply_shared_budget_roots roots ON roots.id=g.root_id "
        "JOIN tutor_item_supply_shared_blueprints bp ON bp.id=roots.blueprint_id "
        "JOIN tutor_item_supply_shared_obligations ob ON ob.root_id=roots.id WHERE g.id=%s", (ARTIFACT,)).fetchone()
    if original is None:
        raise NativeTypeEvidencePending("native_committed_admission_producer_missing")
    prep, material = h["preparation"], h["materialization"]
    return dict(proof_json=publication["proof_json"], proof_hash=publication["proof_hash"],
        runner_material_json=publication["runner_material_json"], source_json=g["source_json"], public_json=h["public"]["public_json"],
        request_json=g["request_json"], root_id=g["root_id"], job_id=g["job_id"], lease_generation=g["lease_generation"],
        facts_json=facts["payload_json"], facts_hash=facts["payload_hash"], preparation_json=prep["payload_json"],
        preparation_hash=prep["payload_hash"], preparation_profile_hash=prep["profile_hash"],
        continuation_row=h["adoption"], continuation_original=original, validation_json=h["validation"]["payload_json"],
        blind_json=h["blind"]["payload_json"], review_json=h["review"]["payload_json"], exercise_content_hash=material["exercise_content_hash"],
        rubric_hash=material["rubric_hash"], materialization_hash=material["receipt_hash"], published_at=h["event"]["occurred_at"],
        committed_admission_history=h)


def _payload(row: dict[str, Any], hash_key: str = "payload_hash", data_key: str = "payload_json") -> dict[str, Any]:
    if row["history_committed"] is not True or canonical_hash(row[data_key]) != row[hash_key]:
        raise ValueError("committed547 immutable history hash mismatch")
    return row[data_key]  # type: ignore[no-any-return]


def _historical_interval(lease: JobLeaseV1, start: Any, end: Any, deadline: Any) -> None:
    """Issuance-time check only; intentionally has no current clock or renewal."""
    ceiling = min(lease.expires_at, lease.parent_deadline, lease.profile.parent_deadline_at, _time(deadline))
    if not lease.profile.bound_at <= _time(start) <= _time(end) < ceiling:
        raise ValueError("committed547 historical issuance outside its original bound")


def _historical_review_interval(lease: JobLeaseV1, audit_start: Any, receipt_at: Any, deadline: Any) -> None:
    # Preparation created_at is PostgreSQL TOP-start audit DATA, not an issued_at.
    # Keep its ordering, independently of the original payload's profile bind time.
    if _time(audit_start) > _time(receipt_at):
        raise ValueError("committed547 historical review audit order changed")
    _historical_interval(lease, lease.profile.bound_at, receipt_at, deadline)


def verify_committed_admission_history(row: dict[str, Any], request: GenerationRequestV2,
        spec: FiniteCandidateSpecV1, facts: IssuedSharedAdmissionFactsV1) -> str:
    """Return the proven HISTORICAL quality profile, not permission to run anything."""
    h = row[HISTORY]
    if any(isinstance(r, dict) and "history_committed" in r and r["history_committed"] is not True for r in h.values()):
        raise ValueError("committed547 history must be committed")
    a, n, f = (_payload(h[k]) for k in ("action", "normal", "facts"))
    q = a["quality"]
    proof = _model(NativePublicationProofV1, _payload(h["publication"], "proof_hash", "proof_json"))
    g, vp, ve = h["artifact"], h["preparation"], h["validation_evidence"]
    rp, line, rr, rrp = (_payload(h[k], "snapshot_hash") for k in ("revision", "lineage", "recheck", "recheck_preparation"))
    output = _payload(h["generation_output"], "snapshot_hash")
    _payload(vp)
    _payload(ve)
    lease, review_lease, validation_lease = (_model(JobLeaseV1, data) for data in (a["lease"], q["review_lease"], q["validation_lease"]))
    source = _model(LearningItemSourceV1, g["source_json"])
    generation = _model(GenerationReceiptV2, g["receipt_json"])
    validation = _model(CandidateValidationV2, _payload(h["validation"], "receipt_hash"))
    blind = _model(BlindSolveReceiptV2, _payload(h["blind"], "receipt_hash"))
    bundle = _model(ReviewBundleV3, _payload(h["review"], "receipt_hash"))
    checked_bundle(bundle)
    inputs = prepare_finite_candidate_validation(source, spec=spec, materials=request.materials)
    if (a["schema_version"] != "committed_child_admission_v1" or a["purpose"] != "admission_only_no_provider"
            or UUID(a["admission_id"]) != ACTION or UUID(a["artifact_id"]) != ARTIFACT or facts.version_id != VERSION
            or UUID(a["lineage_id"]) != LINEAGE or UUID(q["recheck_receipt_id"]) != RECHECK or a["provider_requests"] != 0
            or h["action"]["record_kind"] != "committed_admission" or h["action"]["id"] != ACTION
            or h["action"]["job_id"] != lease.job_id or h["action"]["phase_id"] != ACTION
            or h["action"]["public_task_id"] != UUID(a["public_task_id"]) or h["action"]["root_id"] != facts.root_id
            or a["operation_key"] != "committed.admission." + RECHECK.hex or h["action"]["operation_key"] != a["operation_key"]
            or facts.model_dump(mode="json") != f or facts.lease != lease or proof.lease != lease
            or facts.receipt_id != ACTION or facts.generation_artifact_id != ARTIFACT or facts.continuation_binding_hash is not None
            or facts.profile_hash != lease.profile.profile_hash or facts.evidence.binding != bundle.binding
            or facts.ambiguity.model_dump(mode="json") != a["ambiguity"] or facts.review_budget.model_dump(mode="json") != q["review_budget"]
            or row["preparation_json"] != vp["payload_json"] or row["facts_json"] != f
            or a["version"] != _payload(h["version"]) or a["version"]["artifact_id"] != str(ARTIFACT)
            or a["version"]["public_task_id"] != a["public_task_id"] or a["version"]["public_slot_id"] != a["public_slot_id"]
            or a["version"]["revision_id"] != a["revision_id"] or a["version"]["root_id"] != str(facts.root_id)
            or a["version"]["specification"] != spec.model_dump(mode="json")):
        raise ValueError("committed547 exact action/facts/version DATA required")
    if (n["schema_version"] != "normal_revision_readmission_v3" or n["admission_action_id"] != str(ACTION)
            or n["admission_action_hash"] != h["action"]["payload_hash"] or n["facts_payload"] != f
            or n["facts_payload_hash"] != facts.receipt_hash or h["normal"]["facts_payload_hash"] != facts.receipt_hash
            or n["historical_findings_discharged"] is not False or n["publication_enabled"] is not False
            or h["normal"]["historical_findings_discharged"] is not False or h["normal"]["publication_enabled"] is not False
            or n["lease"] != a["lease"] or n["binding"] != q["binding"]
            or any(n[k] != q[k] for k in ("artifact_id", "artifact_hash", "lineage_id", "lineage_hash", "recheck_receipt_id", "recheck_hash",
                "validation_preparation_id", "validation_receipt_id", "validation_hash", "blind_receipt_id", "blind_hash", "review_receipt_id", "review_hash"))
            or n["policy_hash"] != bundle.binding.policy_hash or n["receipt_id"] != str(ACTION) or n["facts_receipt_id"] != str(ACTION)
            or n["root_id"] != str(facts.root_id) or _time(n["checked_at"]) != facts.checked_at or _time(n["valid_until"]) != facts.valid_until):
        raise ValueError("committed547 exact original normal v3 required")
    if (h["normal"]["job_id"] != lease.job_id or h["normal"]["generation_artifact_id"] != ARTIFACT
            or h["normal"]["root_id"] != facts.root_id or h["normal"]["lineage_id"] != LINEAGE
            or h["normal"]["recheck_receipt_id"] != RECHECK or h["facts"]["job_id"] != lease.job_id
            or h["facts"]["profile_hash"] != facts.profile_hash or h["facts"]["root_id"] != facts.root_id
            or h["facts"]["lease_generation"] != lease.generation or h["facts"]["lease_state_version"] != lease.state_version
            or h["facts"]["lease_owner"] != lease.lease_owner or h["facts"]["generation_artifact_id"] != ARTIFACT
            or h["facts"]["continuation_binding_hash"] is not None or h["facts"]["validation_preparation_id"] != vp["id"]
            or h["facts"]["publication_enabled"] is not False):
        raise ValueError("committed547 action and normal/facts scalar coordinates required")
    if (canonical_hash({"source": g["source_json"], "receipt": g["receipt_json"], "request": g["request_json"]}) != g["artifact_hash"]
            or request.model_dump(mode="json") != g["request_json"] or facts.artifact_hash != g["artifact_hash"]
            or g["job_id"] != h["revision"]["child_job_id"] or h["generation_output"]["job_id"] != g["job_id"]
            or h["lineage"]["child_artifact_id"] != ARTIFACT or h["lineage"]["child_job_id"] != g["job_id"]
            or h["lineage"]["preparation_id"] != LINEAGE or h["lineage"]["parent_artifact_id"] != h["parent"]["id"]
            or output["preparation_hash"] != h["revision"]["snapshot_hash"] or output["returned_state"] != "staged"
            or output["result"]["source"] != g["source_json"] or output["result"]["receipt"] != g["receipt_json"]
            or output["request"] != g["request_json"] or output["author_input"] != line["author_input"]
            or line["child_artifact_hash"] != g["artifact_hash"]
            or line["child_substantive_hash"] != substantive_revision_hash(source)
            or substantive_revision_hash(source) == substantive_revision_hash(_model(LearningItemSourceV1, h["parent"]["source_json"]))
            or rp["context"]["persistent_family_revision"]["child_specification"] != spec.model_dump(mode="json")
            or h["generation_output"]["settlement_id"] != h["generation_settlement"]["id"]
            or h["lineage"]["settlement_id"] != h["generation_settlement"]["id"]
            or h["generation_settlement"]["reservation_id"] != g["reservation_id"]
            or h["generation_settlement"]["settlement_key"] != "generation." + request.candidate_id.hex
            or row["continuation_original"]["generation_completed"] is not True or row["continuation_original"]["generation_settled"] is not True):
        raise ValueError("committed547 original541 generation provenance required")
    frozen = _model(SharedGenerationPolicyBindingV3, _payload(h["generation_policy"]))
    if (frozen.job_id != g["job_id"] or frozen.root_id != facts.root_id or frozen.candidate_id != request.candidate_id
            or frozen.lease_generation != g["lease_generation"] or frozen.request_hash != canonical_hash(g["request_json"])
            or frozen.profile_hash != request.profile.profile_hash or frozen.policy.policy_hash != bundle.binding.policy_hash):
        raise ValueError("committed547 producer policy is not admission policy binding")
    for snapshot, profile in zip((request.profile, review_lease.profile, lease.profile), h["profiles"], strict=True):
        original_profile = _model(ExecutionParameterProfileV1, profile["profile_json"])
        if (original_profile.profile_hash != snapshot.profile_hash or profile["profile_hash"] != snapshot.profile_hash
                or original_profile.current != snapshot.values or original_profile.version != snapshot.profile_version
                or original_profile.profile_key.key_hash != snapshot.profile_key_hash):
            raise ValueError("committed547 historical immutable profile required")
    if (len(h["jobs"]) != 3 or {j["id"] for j in h["jobs"]} != {g["job_id"], review_lease.job_id, lease.job_id}
            or any(j["held"] is not False or j["root_id"] != facts.root_id for j in h["jobs"])):
        raise ValueError("committed547 controlled ancestry held")
    adoption = _model(SharedCandidateContinuationBindingV1, _payload(h["adoption"], "binding_hash", "binding_json"))
    expected, _, _, _, _ = bind_shared_candidate_continuation(artifact=row["continuation_original"], spec=spec,
        lease=adoption.adoption_lease, operation_key=adoption.operation_key)
    if (adoption != expected or adoption.binding_hash != q["historical_continuation_hash"]
            or adoption.adoption_lease.job_id != review_lease.job_id or adoption.adoption_lease.profile != review_lease.profile
            or validation_lease.job_id != review_lease.job_id or validation_lease.profile != review_lease.profile
            or vp["payload_json"]["lease"] != q["validation_lease"] or vp["profile_hash"] != review_lease.profile.profile_hash
            or vp["job_id"] != review_lease.job_id or vp["lease_generation"] != review_lease.generation
            or vp["root_id"] != facts.root_id or vp["generation_artifact_id"] != ARTIFACT
            or h["adoption"]["job_id"] != review_lease.job_id or h["adoption"]["original_job_id"] != g["job_id"]
            or h["adoption"]["generation_artifact_id"] != ARTIFACT or h["adoption"]["root_id"] != facts.root_id
            or h["adoption"]["original_lease_generation"] != g["lease_generation"]
            or vp["payload_json"]["request"] != g["request_json"] or vp["payload_json"]["inputs"] != inputs.model_dump(mode="json")
            or ve["payload_json"]["validation"] != validation.model_dump(mode="json") or ve["preparation_id"] != vp["id"]
            or ve["reservation_id"] is not None or ve["payload_json"]["terminals"] != [] or ve["payload_json"]["actual"] is not None
            or inputs.static_facts is None or validation != inputs.static_facts.validation):
        raise ValueError("committed547 original491/static validation required")
    with finite_review_context(source, spec=spec, materials=request.materials):
        answer = FiniteStaticBlindScorer.verify_committed_single_choice(source, spec=spec, materials=request.materials, blind=blind)
        if blind.run.input_hash != blind_input(source, bundle.binding, blind_protocol=SINGLE_CHOICE_BLIND_PROTOCOL).input_hash:
            raise ValueError("committed547 historical blind subject required")
    # Reuse the DATA-only context's closed original projection; no owner, frame or registry is reconstructed.
    from app.services.learning.item_supply.committed_admission_quality import CommittedChildQuality
    quality = CommittedChildQuality(g, h["lineage"], h["recheck"], h["recheck_preparation"], h["validation"], vp, ve,
        h["blind"], h["review"], review_lease, validation_lease, source, request, generation, spec, inputs,
        validation, blind, bundle, facts.review_budget, answer)
    if q != quality.payload() or rr["lease"] != q["review_lease"] or rr["preparation_hash"] != h["recheck_preparation"]["snapshot_hash"]:
        raise ValueError("committed547 full historical quality changed")
    if (h["recheck"]["job_id"] != review_lease.job_id or h["recheck"]["generation_artifact_id"] != ARTIFACT
            or h["recheck"]["root_id"] != facts.root_id or h["recheck_preparation"]["lineage_id"] != LINEAGE
            or rr["schema_version"] != "native_shared_revision_recheck_receipt_v2"
            or rrp["schema_version"] != "native_shared_revision_recheck_preparation_v2"
            or any(h["recheck"][key] != h[k]["id"] for key, k in (("validation_receipt_id", "validation"),
                ("blind_receipt_id", "blind"), ("review_receipt_id", "review")))):
        raise ValueError("committed547 historical recheck producer required")
    runs = (blind.run, *(r.run for r in bundle.reports))
    forbidden = {UUID(r) for r in rrp["forbidden_run_ids"]}
    if (len({r.run_id for r in runs}) != 7 or forbidden.intersection(r.run_id for r in runs)
            or any(r.max_output_tokens != 61440 or r.profile_hash != review_lease.profile.profile_hash for r in runs)
            or {str(r["id"]): r["receipt_hash"] for r in h["ancestors"]} != {r["receipt_id"]: r["receipt_hash"] for r in rrp["ancestor_reviews"]}
            or rr["blockers_discharged"] is not False or rr["admission_eligible"] is not False):
        raise ValueError("committed547 historical independent seven runs required")
    for name, kind in (("validation", "validation"), ("blind", "blind_solve"), ("review", "review_bundle")):
        stage = h[name]
        if (stage["job_id"] != review_lease.job_id or stage["lease_generation"] != review_lease.generation
                or stage["lease_owner"] != review_lease.lease_owner or stage["generation_artifact_id"] != ARTIFACT
                or stage["artifact_kind"] != kind or stage["continuation_binding_hash"] != adoption.binding_hash
                or (stage["source_hash"], stage["content_hash"]) != (source.source_hash, source.content_hash)):
            raise ValueError("committed547 historical stage producer mismatch")
        _historical_review_interval(review_lease, h["recheck_preparation"]["created_at"], stage["created_at"], h["recheck_preparation"]["valid_until"])
    _historical_review_interval(review_lease, h["recheck_preparation"]["created_at"], h["recheck"]["created_at"], h["recheck_preparation"]["valid_until"])
    reservation, settled = h["review_reservation"], h["review_settlement"]
    if (reservation["job_id"] != review_lease.job_id or reservation["root_id"] != facts.root_id or reservation["requests"] != 7
            or reservation["lease_generation"] != review_lease.generation or settled["reservation_id"] != reservation["id"]
            or settled["settlement_key"] != facts.review_budget.settlement_key or settled["usage_state"] != "unknown"
            or settled["cost_amount"] is not None or settled["receipt_hash"] is not None):
        raise ValueError("committed547 historical UNKNOWN budget changed")
    # Interpret persisted static observation DATA with the original pure plan.
    # The live owner's _receipt checks its clock and must NOT be revived with a fake clock.
    original_plan = build_finite_ambiguity_plan(source, spec=spec, inputs=inputs)
    propositions = json.loads(original_plan.option_propositions_json)
    if (facts.ambiguity.plan != original_plan or facts.ambiguity.mode != "static_options" or facts.ambiguity.terminals
            or facts.ambiguity.selected_case_results != tuple(p["accepted"] for p in propositions if p["accepted"])
            or facts.ambiguity.alternative_case_results != tuple(p["accepted"] for p in propositions if not p["accepted"])
            or facts.ambiguity.alternative_predictions_matched != tuple(True for p in propositions if not p["accepted"])
            or facts.ambiguity.parent_deadline_at != _time(a["valid_until"])
            or not _time(a["checked_at"]) <= facts.ambiguity.started_at <= facts.ambiguity.completed_at <= facts.checked_at):
        raise ValueError("committed547 actual admission ambiguity changed")
    _historical_interval(lease, a["checked_at"], h["normal"]["created_at"], a["valid_until"])
    _historical_interval(lease, facts.checked_at, row["published_at"], facts.valid_until)
    _historical_interval(lease, facts.checked_at, h["qualified"]["created_at"], facts.valid_until)
    if _payload(h["qualified"]) != dict(a["version"], published_version_id=str(VERSION)):
        raise ValueError("committed547 exact same-slot qualified history required")
    if (facts.valid_until > _time(a["valid_until"]) or facts.valid_until > _time(a["source_valid_until"])
            or any(_time(d["retained_until"]) < facts.valid_until for d in rp["source_deadlines"])):
        raise ValueError("committed547 historical source bound mismatch")
    _publication_history(h, a, facts, proof)
    return str(review_lease.profile.profile_hash)


def _publication_history(h: dict[str, Any], action: dict[str, Any], facts: IssuedSharedAdmissionFactsV1,
                         proof: NativePublicationProofV1) -> None:
    # Published records are separately committed DATA. SAVEPOINT writes can have
    # subtransaction xmin, so never pretend xmin equals the recorded TOP txid.
    # Original capture/publication TOP ids and receiver timestamps bind the history.
    ax, fx, px = (h[name]["history_xmin"] for name in ("action", "facts", "publication"))
    evaluation, bank, imported, event = (h[name] for name in ("evaluation", "bank_validation", "import", "event"))
    if (len({ax, fx, px}) != 3 or action["capture_txid"] >= h["publication"]["publication_txid"]
            or not _time(h["action"]["created_at"]) <= _time(h["facts"]["created_at"])
                <= _time(h["normal"]["created_at"]) <= _time(h["publication"]["created_at"]) < facts.valid_until
            or evaluation["payload_json"] != facts.evaluation.model_dump(mode="json")
            or _payload(evaluation, "receipt_hash") != facts.evaluation.model_dump(mode="json")
            or evaluation["id"] != proof.evaluation_receipt_id or evaluation["artifact_kind"] != "admission_evaluation"
            or evaluation["job_id"] != facts.lease.job_id or evaluation["continuation_binding_hash"] is not None
            or evaluation["lease_generation"] != facts.lease.generation or evaluation["lease_state_version"] != facts.lease.state_version
            or bank["native_import_lease_json"] != action["lease"] or bank["receipt_json"] != h["validation"]["payload_json"]
            or bank["native_generation_artifact_id"] != ARTIFACT or bank["native_validation_receipt_id"] != facts.validation_receipt_id
            or bank["native_validation_evidence_id"] != h["validation_evidence"]["id"]
            or bank["native_specification_hash"] != facts.specification_hash or bank["passed"] is not None
            or imported["validation_receipt_id"] != bank["id"] or imported["version_id"] != VERSION
            or imported["importer_version"] != "learning_item_native_repository_v2"
            or event["id"] != proof.publication_event_id or event["version_id"] != VERSION or event["state"] != "published"
            or event["authority_reference_id"] != proof.proof_id):
        raise ValueError("committed547 original committed import/publication chain required")
