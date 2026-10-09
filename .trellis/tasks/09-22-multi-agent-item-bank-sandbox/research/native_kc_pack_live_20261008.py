"""Main-only KC pack composition; importing/--plan never opens runtime inputs.

Keep the ORIGINAL execute_slot LivePublication alive. No JSON can restore its
owners, and this helper never claims/refreshes/completes a job or retries review.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from app.services.learning.item_supply.native_relation_review import (
        NativeRelationReviewProducer, PreparedNativeRelationBatch,
    )
    from app.services.learning.item_supply.native_type_contracts import NativeResolvedContent
    from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
    from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2
    from app.services.learning.item_supply.pack_contracts import CompleteExposureV2

DATABASE = "aearn_b1d_sandbox_20261001"
TARGET = "python-kc-binding-v1"
SLOT_COUNTS = {"practice": 2, "assessment": 2, "remediation": 1}


@dataclass(frozen=True)
class PreparedKcPack:
    """Process-local references, not a new authority or serializable capability."""

    live: Any
    type_owner: NativeTypeEvidenceOwner
    relation_owner: NativeRelationReviewProducer
    exposure_owner: NativeExposureOwnerV2
    relation: PreparedNativeRelationBatch
    candidate_version_ids: tuple[UUID, ...]
    output_dir: Path


@dataclass(frozen=True)
class KcPackReservation:
    reservation_id: UUID
    operation_key: str
    prepared: PreparedKcPack


def _execute_required(execute: bool) -> None:
    if execute is not True:
        raise ValueError("native_kc_pack_main_execute_required")


def _idle(conn: Any) -> None:
    from psycopg.pq import TransactionStatus

    if conn.autocommit or conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("native_kc_pack_idle_connection_required")


def _save(folder: Path, name: str, payload: dict[str, Any]) -> None:
    # Exclusive, durable markers: never overwrite an earlier dispatch/failure.
    with (folder / name).open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _failure(folder: Path, stage: str, exc: Exception) -> None:
    from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending
    from app.services.learning.item_supply.native_type_exposure_contracts import NativeTypeExposurePending

    reason = str(exc) if isinstance(exc, (NativeTypeEvidencePending, NativeTypeExposurePending)) else "native_kc_pack_stage_failed"
    _save(folder, "failure.json", {"stage": stage, "safe_reason": reason,
        "error_type": type(exc).__name__, "retry_allowed": False,
        "usage_state": "unknown", "monetary_cost_cny": None,
        "delivered": False, "Attempt_Gate_mastery": False, "public_release": False})


def _owners(live: Any, owner: NativeTypeEvidenceOwner,
            relations: NativeRelationReviewProducer, exposure: NativeExposureOwnerV2) -> None:
    from app.services.learning.item_bank.native_publication import NativeLearningItemPublicationService
    from app.services.learning.item_supply.native_relation_review import NativeRelationReviewProducer
    from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
    from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2
    from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner

    if (type(owner) is not NativeTypeEvidenceOwner or type(relations) is not NativeRelationReviewProducer
            or type(exposure) is not NativeExposureOwnerV2 or relations.owner is not owner
            or exposure.type_owner is not owner or relations.conn is not owner.conn
            or exposure.conn is not owner.conn or exposure.user_id != owner.user_id or exposure.epoch != owner.epoch):
        raise ValueError("native_kc_pack_concrete_same_connection_owners_required")
    publisher, facts = live.publisher, live.facts_owner
    if (type(publisher) is not NativeLearningItemPublicationService or type(facts) is not SharedAdmissionFactsOwner
            or publisher.conn is not owner.conn or facts.conn is not owner.conn
            or publisher.facts_owner is not facts or facts.validation_pipeline is not live.validation_owner
            or facts.review_pipeline is not live.review_owner
            or live.validation_owner.conn is not owner.conn or live.review_owner.conn is not owner.conn
            or publisher.importer.authority is not owner.source_authority
            or owner.mapping_owner.runtime_owner is not owner.query
            or live.result.get("status") != "published_internal_not_ready_pack"
            or live.result.get("relation_anchor_eligible") is not True):
        raise ValueError("native_kc_pack_original_live_publication_required")


def _pairs(contents: tuple[NativeResolvedContent, ...], exposure: CompleteExposureV2
           ) -> tuple[tuple[UUID, UUID], ...]:
    """Exact pack_builder V2 comparisons, not all training/training combinations."""
    from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending
    from app.services.learning.item_supply.type_evidence import assessment_clone

    groups = {slot: [c.content for c in contents if c.spec.allocation.slot == slot] for slot in SLOT_COUNTS}
    if (len(contents) != 5 or {slot: len(items) for slot, items in groups.items()} != SLOT_COUNTS
            or any(c.spec.target_id != TARGET for c in contents)
            or len({c.content.version_id for c in contents}) != 5
            or len({c.content.item_handle for c in contents}) != 5
            or len({c.content.content_hash for c in contents}) != 5):
        raise NativeTypeEvidencePending("native_kc_pack_exact_221_distinct_contents_required")
    assessments = groups["assessment"]
    training = groups["practice"] + groups["remediation"]
    comparisons = [(assessments[0], assessments[1])]
    comparisons.extend((a, b) for a in assessments for b in training)
    comparisons.extend((a, e.content) for a in assessments for e in exposure.records)
    if any(assessment_clone(a, b) for a, b in comparisons):
        raise NativeTypeEvidencePending("native_kc_pack_assessment_clone_or_exposed")
    pairs = {(a.version_id, b.version_id) if str(a.version_id) < str(b.version_id)
             else (b.version_id, a.version_id) for a, b in comparisons}
    return tuple(sorted(pairs, key=lambda p: (str(p[0]), str(p[1]))))


def prepare_kc_pack(*, live: Any, type_owner: NativeTypeEvidenceOwner,
                    relation_owner: NativeRelationReviewProducer, exposure_owner: NativeExposureOwnerV2,
                    mapping_receipt_id: UUID, candidate_version_ids: tuple[UUID, ...],
                    output_dir: Path, execute: bool = False) -> PreparedKcPack:
    """Resolve original current inputs and COMMIT the original four-call reserve."""
    _execute_required(execute)
    _owners(live, type_owner, relation_owner, exposure_owner)
    conn = type_owner.conn
    _idle(conn)
    if (len(candidate_version_ids) != 5 or len(set(candidate_version_ids)) != 5
            or any(type(v) is not UUID for v in candidate_version_ids)):
        raise ValueError("native_kc_pack_exact_five_versions_required")
    folder = output_dir.resolve()
    runtime = Path(__file__).resolve().parents[4] / ".runtime"
    if not folder.is_relative_to(runtime.resolve()) or folder == runtime.resolve():
        raise ValueError("native_kc_pack_new_runtime_output_required")
    folder.mkdir(parents=True, exist_ok=False)
    try:
        with conn.transaction():
            row = conn.execute("SELECT current_database() AS name").fetchone()
            if row is None or row["name"] != DATABASE:
                raise ValueError("native_kc_pack_exact_isolated_database_required")
            mapping = type_owner.resolve_mapping(mapping_receipt_id)
            if mapping.target_id != TARGET:
                raise ValueError("native_kc_pack_KC_mapping_required")
            contents = tuple(type_owner.resolve_content(v, current=True) for v in candidate_version_ids)
            observation = exposure_owner.snapshot_v2()
            if observation.exposure is None or observation.snapshot_id is None:
                from app.services.learning.item_supply.native_type_exposure_contracts import NativeTypeExposurePending
                raise NativeTypeExposurePending(observation.safe_reason)
            pairs = _pairs(contents, observation.exposure)
            anchor = next((c for c in contents if c.spec.allocation.slot == "assessment"
                and str(c.content.version_id) == live.result["version_id"]), None)
            if anchor is None or anchor.publication.lease != live.lease:
                raise ValueError("native_kc_pack_original_anchor_lease_required")
            relation = relation_owner.prepare(mapping_receipt_id=mapping_receipt_id,
                anchor_version_id=anchor.content.version_id, lease=live.lease, pairs=pairs)
        _save(folder, "prepared.json", {"stage": "original_relation_reservation_committed",
            "mapping_receipt_id": str(mapping_receipt_id), "candidate_version_ids": list(map(str, candidate_version_ids)),
            "anchor_version_id": str(relation.anchor_version_id), "root_id": str(relation.root_id),
            "job_id": str(relation.lease.job_id), "preparation_id": str(relation.preparation_id),
            "reservation_id": str(relation.reservation_id), "pair_count": len(pairs),
            "reserved_requests": relation.resources.requests, "provider_calls_this_prepare": 0,
            "original_deadline": relation.valid_until.isoformat(), "replay_allowed": False})
        return PreparedKcPack(live, type_owner, relation_owner, exposure_owner, relation, candidate_version_ids, folder)
    except Exception as exc:
        _failure(folder, "prepare", exc)
        raise


def complete_kc_pack(prepared: PreparedKcPack, *, operation_key: str,
                     execute: bool = False) -> KcPackReservation:
    """One original role batch; UNKNOWN settlement commits before fenced persist.

    A conflict/pending result is retained, never retried. The final 502 call
    resolves/consumes 501's capability in its SAME transaction. No Artifact write.
    """
    _execute_required(execute)
    _owners(prepared.live, prepared.type_owner, prepared.relation_owner, prepared.exposure_owner)
    conn, producer, relation = prepared.type_owner.conn, prepared.relation_owner, prepared.relation
    _idle(conn)
    # An existing marker denies re-entry; deliberately outside the failure writer.
    _save(prepared.output_dir, "relation-dispatch.json", {"preparation_id": str(relation.preparation_id),
        "reservation_id": str(relation.reservation_id), "reserved_requests": relation.resources.requests,
        "usage_state": "unknown", "monetary_cost_cny": None, "retry_allowed": False})
    stage = "relation_run"
    try:
        run = producer.run(relation)
        stage = "relation_settle"
        _idle(conn)
        with conn.transaction():
            producer.settle(relation, run)
        _save(prepared.output_dir, "settled.json", {"usage_state": "unknown", "monetary_cost_cny": None,
            "safe_reason": run.safe_reason, "completed_roles": len(run.reports),
            "reports": [{"role": r.role, "receipt_id": str(r.receipt_id), "run_id": str(r.run.run_id),
                "input_tokens": r.run.input_tokens, "output_tokens": r.run.output_tokens,
                "conclusions": [j.conclusion for j in r.judgments]} for r in run.reports]})
        stage = "relation_persist"
        with conn.transaction():
            batch_id = producer.persist(relation, run)
        _save(prepared.output_dir, "relation-persisted.json", {"relation_receipt_id": str(batch_id)})
        stage = "pack_resolve_and_assessment_reserve"
        with conn.transaction():
            reservation = prepared.exposure_owner.reserve_assessment(
                mapping_receipt_id=relation.mapping_receipt_id, candidate_version_ids=prepared.candidate_version_ids,
                relation_receipt_ids=(batch_id,), operation_key=operation_key)
        _save(prepared.output_dir, "result.json", {"status": "assessment_reserved_internal_not_delivered",
            "reservation_id": str(reservation), "relation_receipt_id": str(batch_id),
            "candidate_version_ids": list(map(str, prepared.candidate_version_ids)),
            "delivered": False, "Attempt_Gate_mastery": False, "public_release": False, "E_complete": False})
        return KcPackReservation(reservation, operation_key, prepared)
    except Exception as exc:
        _failure(prepared.output_dir, stage, exc)
        raise


def prepare_kc_practice_delivery(reserved: KcPackReservation, *, version_id: UUID,
                                 delivery_key: str, execute: bool = False) -> UUID:
    """Original formal permit only: caller's Artifact writer MUST share this tx.

    This function neither commits nor manufactures a delivery/exposure event.
    Never serialize its return value to reuse in a later transaction.
    """
    _execute_required(execute)
    from psycopg.pq import TransactionStatus

    p = reserved.prepared
    _owners(p.live, p.type_owner, p.relation_owner, p.exposure_owner)
    owner = reserved.prepared.exposure_owner
    if owner.conn.autocommit or owner.conn.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("native_kc_pack_original_artifact_transaction_required")
    return owner.prepare_practice_delivery(reservation_key=reserved.operation_key,
        version_id=version_id, delivery_key=delivery_key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if args.execute:
        parser.error("main must import prepare_kc_pack/complete_kc_pack with ORIGINAL live owners; no standalone credential loader")
    print(json.dumps({"status": "inert_plan", "target": TARGET, "database": DATABASE,
        "slot_counts": SLOT_COUNTS, "database_io": False, "provider_calls": 0, "GETs": 0, "key_reads": 0,
        "relation_requests_reserved_only_by_original_owner": 4,
        "requires": ["five_current_published_versions", "confirmed_496_mapping", "original_assessment_anchor_LivePublication",
            "same_connection_501_relation_502_owners", "new_main_runtime_output"],
        "pack_passed": False, "delivery": "same_transaction_original_Artifact_writer_only"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
