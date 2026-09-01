from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.services.learning.item_bank.contracts import (
    LearningItemSourceV1,
    LearningItemValidationReceiptV1,
    canonical_hash,
)
from app.services.learning.item_bank.importer import (
    LearningItemImportArtifactV1,
    LearningItemImportFileError,
    import_curated_learning_item_sources,
)
from app.services.learning.item_bank.governance_repository import (
    LearningItemGovernanceConflict,
    PostgresLearningItemGovernanceRepository,
)
from app.services.learning.item_bank.practice_adapter import build_exercise_authority
from app.services.learning.item_bank.repository import (
    LearningItemImportConflict,
    PostgresLearningItemBankRepository,
)
from app.services.learning.item_bank.review_contracts import (
    REQUIRED_REVIEW_ROLES,
    LearningItemPilotDecision,
    LearningItemPilotTelemetryV1,
    LearningItemReviewReportV1,
)
from app.services.learning.item_bank.validation import validate_learning_item
from app.services.tutor.cutover import CUTOVER_SHARED_TUTOR_TABLES

_NOW = datetime(2026, 9, 1, 1, tzinfo=UTC)
_ITEM_TABLES = {
    "tutor_learning_item_blueprints",
    "tutor_learning_items",
    "tutor_learning_item_versions",
    "tutor_learning_item_public_contents",
    "tutor_learning_item_private_contents",
    "tutor_learning_item_validation_receipts",
    "tutor_learning_item_review_reports",
    "tutor_learning_item_review_adjudications",
    "tutor_learning_item_pilot_receipts",
    "tutor_learning_item_human_approvals",
    "tutor_learning_item_practice_materializations",
    "tutor_learning_item_publication_events",
    "tutor_learning_item_import_receipts",
}


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not available for Learning Item Bank tests.",
)


def _source(
    item_key: str,
    *,
    version: str = "1.0.0",
    knowledge_key: str = "python.variables",
    difficulty: str = "D1",
    capability: str = "python.variables",
    prompt_suffix: str = "",
    risk_tier: str = "low",
) -> tuple[LearningItemSourceV1, LearningItemValidationReceiptV1]:
    difficulty_band = int(difficulty.removeprefix("D"))
    source_reference = {
        "source_id": "python.tutorial",
        "source_version": "3.12",
        "locator": "variables",
        "content_hash": "1" * 64,
    }
    source = LearningItemSourceV1.model_validate(
        {
            "schema_version": "learning_item_source_v1",
            "blueprint": {
                "schema_version": "learning_item_blueprint_v1",
                "blueprint_key": f"blueprint.{item_key}",
                "version": version,
                "knowledge_key": knowledge_key,
                "item_kind": "knowledge_check",
                "purpose": "knowledge_check",
                "language_id": "python",
                "difficulty_profile": {
                    "base": difficulty,
                    "reasoning_depth": difficulty_band,
                    "concept_count": difficulty_band,
                    "context_novelty": difficulty_band,
                    "transfer_distance": difficulty_band,
                    "response_complexity": difficulty_band,
                    "scaffolding": 6 - difficulty_band,
                },
                "prerequisite_keys": [],
                "required_capabilities": [capability],
                "runtime_profile_id": None,
                "allowed_interactions": ["respond"],
                "remediation_policy": None,
                "publication_policy": {
                    "risk_tier": risk_tier,
                    "required_review_roles": [item.value for item in REQUIRED_REVIEW_ROLES],
                    "agent_review_required": True,
                    "pilot_required": True,
                    "human_approval_required": risk_tier == "high",
                },
                "source_references": [source_reference],
            },
            "public": {
                "schema_version": "learning_item_public_v1",
                "item_key": item_key,
                "version": version,
                "kind": "knowledge_check",
                "purpose": "knowledge_check",
                "title": f"Variable check {version}",
                "difficulty": difficulty,
                "instruction_markdown": f"Answer the bounded variable question. {prompt_suffix}".strip(),
                "allowed_interactions": ["respond"],
                "hints": [],
                "remediation_item_key": None,
                "source_references": [source_reference],
                "content": {
                    "type": "knowledge_check",
                    "response_kind": "short_text",
                    "prompt_markdown": f"What value is produced? {prompt_suffix}".strip(),
                    "options": [],
                },
            },
            "private": {
                "schema_version": "learning_item_private_v1",
                "item_key": item_key,
                "version": version,
                "kind": "knowledge_check",
                "content": {
                    "type": "knowledge_check",
                    "accepted_answers": ["42"],
                    "answer_explanation_markdown": "PRIVATE_REFERENCE_ANSWER_MARKER",
                    "tests": [
                        {
                            "id": "visible.case",
                            "case_type": "visible",
                            "input_json": {"answer": "42"},
                            "expected_output_json": {"accepted": True},
                            "weight": 1,
                            "is_critical": True,
                            "order_index": 0,
                        },
                        {
                            "id": "hidden.case",
                            "case_type": "hidden",
                            "input_json": {"answer": "private-hidden-input"},
                            "expected_output_json": {"accepted": False},
                            "weight": 1,
                            "is_critical": True,
                            "order_index": 1,
                        },
                    ],
                    "score_policy": {
                        "kind": "static_exact",
                        "policy_version": "knowledge.check.v1",
                        "threshold": 1,
                    },
                },
            },
        }
    )
    return source, validate_learning_item(source)


def _import(
    repository: PostgresLearningItemBankRepository,
    source: LearningItemSourceV1,
    validation: LearningItemValidationReceiptV1,
    *,
    key: str,
):
    return repository.import_validated_source(
        source=source,
        validation=validation,
        import_key=key,
        source_path=f"tests/{key}.learning-item.json",
        source_file_hash=canonical_hash({"source": source.source_hash}),
        imported_at=_NOW,
    )


def _review_and_start_pilot(conn, handle: str, key: str):  # type: ignore[no-untyped-def]
    governance = PostgresLearningItemGovernanceRepository(conn)
    subject = governance.load_review_subject(handle=handle)
    reports = tuple(
        LearningItemReviewReportV1(
            item_handle=handle,
            content_hash=subject.source.content_hash,
            review_input_hash=subject.blind_input(role).review_input_hash,
            role=role,
            reviewer_identity=f"reviewer.{role.value}.{key[-8:]}",
            verdict="approved",
        )
        for role in REQUIRED_REVIEW_ROLES
    )
    review_result = governance.record_review_bundle(
        subject=subject,
        reports=reports,
        bundle_key=f"review:{key}",
        occurred_at=_NOW,
    )
    assert review_result.publication is not None
    assert review_result.publication.state == "agent_reviewed"
    pilot = governance.start_pilot(
        handle=handle,
        transition_key=f"pilot:{key}",
        occurred_at=_NOW,
    )
    assert pilot.state == "pilot"
    return governance, subject


def _publish(conn, handle: str, key: str):  # type: ignore[no-untyped-def]
    governance, subject = _review_and_start_pilot(conn, handle, key)
    result = governance.record_pilot_telemetry(
        handle=handle,
        telemetry=LearningItemPilotTelemetryV1(
            item_handle=handle,
            content_hash=subject.source.content_hash,
            observation_window_hash=canonical_hash({"pilot": key}),
            sample_count=1,
            completed_count=1,
            cohort_complete=True,
        ),
        expected_pilot_sequence=0,
        telemetry_key=f"telemetry:{key}",
        occurred_at=_NOW,
    )
    assert result.publication is not None
    return result.publication


def test_learning_item_schema_bootstrap_twice_and_shared_classification() -> None:
    bootstrap_database()
    bootstrap_database()
    with connect() as conn:
        tables = {
            str(row["table_name"])
            for row in conn.execute(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema='public' AND table_name=ANY(%s)""",
                (list(_ITEM_TABLES),),
            ).fetchall()
        }
        triggers = {
            str(row["tgname"])
            for row in conn.execute(
                """SELECT tgname FROM pg_trigger
                   WHERE NOT tgisinternal AND tgname LIKE 'trg_tutor_learning_item%'"""
            ).fetchall()
        }
        curated_count = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_learning_item_import_receipts WHERE source_path NOT LIKE 'tests/%'"
        ).fetchone()
    assert tables == _ITEM_TABLES
    assert curated_count is not None and curated_count["count"] >= 5
    assert {
        "trg_tutor_learning_item_versions_immutable",
        "trg_tutor_learning_item_private_contents_immutable",
        "trg_tutor_learning_item_publication_events_lineage",
        "trg_tutor_learning_item_publication_events_immutable",
        "trg_tutor_learning_item_import_receipts_immutable",
    }.issubset(triggers)
    assert _ITEM_TABLES <= CUTOVER_SHARED_TUTOR_TABLES


def test_import_replay_conflict_immutability_and_candidate_redaction() -> None:
    bootstrap_database()
    suffix = uuid4().hex
    item_key = f"test.item.{suffix}"
    source, validation = _source(item_key)
    with connect() as conn:
        repository = PostgresLearningItemBankRepository(conn)
        first = _import(repository, source, validation, key=f"import:{suffix}")
        replay = _import(repository, source, validation, key=f"import:{suffix}")
        assert replay.replayed is True
        assert replay.version_id == first.version_id
        changed, changed_validation = _source(item_key, prompt_suffix="changed")
        with pytest.raises(LearningItemImportConflict):
            _import(repository, changed, changed_validation, key=f"import:{suffix}")
        published = _publish(conn, first.handle, f"publish:{suffix}")
        assert published.state == "published"
        assert repository.published_candidates(
            knowledge_key="python.variables",
        ) == ()
        assert repository.published_candidates(
            knowledge_key="python.variables",
            available_capabilities=(),
        ) == ()
        candidates = repository.published_candidates(
            knowledge_key="python.variables",
            purpose="knowledge_check",
            difficulties=("D1",),
            available_capabilities=("python.variables",),
        )
        candidate = next(item for item in candidates if item.handle == first.handle)
        serialized = json.dumps(candidate.as_dict(), ensure_ascii=False, sort_keys=True)
        assert "PRIVATE_REFERENCE_ANSWER_MARKER" not in serialized
        assert "private-hidden-input" not in serialized
        assert "private_json" not in serialized
        stored_content = conn.execute(
            """
            SELECT public.public_json,private.private_json
            FROM tutor_learning_item_public_contents AS public
            JOIN tutor_learning_item_private_contents AS private
              ON private.version_id=public.version_id
            WHERE public.version_id=%s
            """,
            (first.version_id,),
        ).fetchone()
        assert stored_content is not None
        public_json = json.dumps(stored_content["public_json"], ensure_ascii=False)
        private_json = json.dumps(stored_content["private_json"], ensure_ascii=False)
        assert "PRIVATE_REFERENCE_ANSWER_MARKER" not in public_json
        assert "private-hidden-input" not in public_json
        assert "PRIVATE_REFERENCE_ANSWER_MARKER" in private_json
        assert "private-hidden-input" in private_json
        with pytest.raises(psycopg.errors.CheckViolation, match="immutable"):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_learning_item_public_contents SET title='mutated' WHERE version_id=%s",
                    (first.version_id,),
                )
        conn.rollback()


def test_retire_preserves_version_history_and_candidate_filters() -> None:
    bootstrap_database()
    suffix = uuid4().hex
    item_key = f"test.history.{suffix}"
    v1_source, v1_validation = _source(item_key, version="1.0.0", difficulty="D1")
    v2_source, v2_validation = _source(item_key, version="2.0.0", difficulty="D2", prompt_suffix="v2")
    with connect() as conn:
        repository = PostgresLearningItemBankRepository(conn)
        v1 = _import(repository, v1_source, v1_validation, key=f"import:{suffix}:v1")
        v2 = _import(repository, v2_source, v2_validation, key=f"import:{suffix}:v2")
        _publish(conn, v1.handle, f"publish:{suffix}:v1")
        _publish(conn, v2.handle, f"publish:{suffix}:v2")
        retired = repository.append_publication_state(
            handle=v1.handle,
            expected_state_version=4,
            next_state="retired",
            transition_key=f"retire:{suffix}:v1",
            authority_kind="operator",
            authority_hash=canonical_hash({"retire": v1.handle}),
            policy_version="learning.item.retire.test.v1",
            reason_code="superseded.version",
            occurred_at=_NOW,
        )
        assert retired.state_version == 5
        candidates = repository.published_candidates(
            knowledge_key="python.variables",
            difficulties=("D2",),
            available_capabilities=("python.variables",),
            unused_handles=(v1.handle,),
        )
        assert [item.handle for item in candidates if item.item_key == item_key] == [v2.handle]
        excluded = repository.published_candidates(
            knowledge_key="python.variables",
            available_capabilities=("python.variables",),
            unused_handles=(v2.handle,),
        )
        assert all(item.item_key != item_key for item in excluded)
        states = conn.execute(
            "SELECT state FROM tutor_learning_item_publication_events WHERE version_id=%s ORDER BY state_version",
            (v1.version_id,),
        ).fetchall()
        assert [str(row["state"]) for row in states] == [
            "machine_verified",
            "agent_reviewed",
            "pilot",
            "published",
            "retired",
        ]
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_learning_item_versions WHERE item_key=%s",
            (item_key,),
        ).fetchone()["count"] == 2
        conn.rollback()


def test_compiled_file_import_seam_is_deterministic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    bootstrap_database()
    suffix = uuid4().hex
    source, validation = _source(f"test.file.{suffix}")
    artifact = LearningItemImportArtifactV1(source=source, validation_receipt=validation)
    file_path = tmp_path / f"{suffix}.learning-item.json"
    file_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    with connect() as conn:
        first = import_curated_learning_item_sources(conn, source_root=tmp_path, imported_at=_NOW)
        second = import_curated_learning_item_sources(conn, source_root=tmp_path, imported_at=_NOW)
        assert len(first) == len(second) == 1
        assert first[0].replayed is False
        assert second[0].replayed is True
        conn.rollback()


def test_import_recomputes_complete_deterministic_validation() -> None:
    bootstrap_database()
    suffix = uuid4().hex
    source, validation = _source(f"test.validation.{suffix}")
    forged_payload = validation.model_dump(mode="json")
    forged_payload["checks"][0]["proof_hash"] = "f" * 64  # type: ignore[index]
    forged = LearningItemValidationReceiptV1.model_validate(forged_payload)

    with connect() as conn:
        repository = PostgresLearningItemBankRepository(conn)
        with pytest.raises(
            LearningItemImportConflict,
            match="current deterministic validation",
        ):
            _import(repository, source, forged, key=f"forged:{suffix}")
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_learning_item_versions WHERE item_key=%s",
            (source.public.item_key,),
        ).fetchone()["count"] == 0
        conn.rollback()


def test_high_risk_publish_requires_exact_human_approval_and_materializes_practice() -> None:
    bootstrap_database()
    suffix = uuid4().hex
    item_key = f"test.high-risk.{suffix}"
    source, validation = _source(item_key, risk_tier="high")

    with connect() as conn:
        repository = PostgresLearningItemBankRepository(conn)
        imported = _import(repository, source, validation, key=f"high-risk:{suffix}")
        governance, subject = _review_and_start_pilot(
            conn,
            imported.handle,
            f"high-risk:{suffix}",
        )
        pilot = governance.record_pilot_telemetry(
            handle=imported.handle,
            telemetry=LearningItemPilotTelemetryV1(
                item_handle=imported.handle,
                content_hash=source.content_hash,
                observation_window_hash=canonical_hash({"pilot": suffix}),
                sample_count=3,
                completed_count=3,
                cohort_complete=True,
            ),
            expected_pilot_sequence=0,
            telemetry_key=f"high-risk-telemetry:{suffix}",
            occurred_at=_NOW,
        )
        assert pilot.receipt.decision is LearningItemPilotDecision.AWAITING_HUMAN_APPROVAL
        assert pilot.publication is None
        assert repository.published_candidates(
            knowledge_key=source.blueprint.knowledge_key,
            available_capabilities=source.blueprint.required_capabilities,
        ) == ()

        approval = governance.approve_high_risk(
            handle=imported.handle,
            approver_identity="human.curriculum.owner",
            approval_key=f"approval:{suffix}",
            occurred_at=_NOW,
        )
        replay = governance.approve_high_risk(
            handle=imported.handle,
            approver_identity="human.curriculum.owner",
            approval_key=f"approval:{suffix}",
            occurred_at=_NOW,
        )
        assert approval.publication.state == "published"
        assert replay.replayed is True
        assert replay.approval_id == approval.approval_id
        assert replay.publication.event_id == approval.publication.event_id

        expected_material = build_exercise_authority(subject.source)
        assert expected_material is not None
        materialized = conn.execute(
            """
            SELECT materializations.*,exercises.content_hash AS stored_exercise_hash,
                   rubrics.rubric_hash AS stored_rubric_hash
            FROM tutor_learning_item_practice_materializations AS materializations
            JOIN tutor_exercise_versions AS exercises
              ON exercises.id=materializations.exercise_version_id
            JOIN tutor_exercise_private_rubrics AS rubrics
              ON rubrics.exercise_version_id=exercises.id
            WHERE materializations.version_id=%s
            """,
            (imported.version_id,),
        ).fetchone()
        assert materialized is not None
        assert materialized["stored_exercise_hash"] == expected_material.exercise.content_hash
        assert materialized["stored_rubric_hash"] == expected_material.rubric.rubric_hash
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_learning_item_human_approvals WHERE version_id=%s",
            (imported.version_id,),
        ).fetchone()["count"] == 1
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_learning_item_practice_materializations WHERE version_id=%s",
            (imported.version_id,),
        ).fetchone()["count"] == 1
        assert [
            item.handle
            for item in repository.published_candidates(
                knowledge_key=source.blueprint.knowledge_key,
                available_capabilities=source.blueprint.required_capabilities,
            )
            if item.item_key == item_key
        ] == [imported.handle]
        conn.rollback()


def test_pilot_quarantine_and_retire_preserve_history_and_block_candidates() -> None:
    bootstrap_database()
    suffix = uuid4().hex
    with connect() as conn:
        repository = PostgresLearningItemBankRepository(conn)
        outcomes: list[tuple[str, str, str]] = []
        for label, telemetry_fields, expected_state in (
            ("quarantine", {"ambiguity_count": 1}, "quarantined"),
            ("retire", {"security_incident_count": 1}, "retired"),
        ):
            item_key = f"test.pilot.{label}.{suffix}"
            source, validation = _source(item_key)
            imported = _import(
                repository,
                source,
                validation,
                key=f"pilot:{label}:{suffix}",
            )
            governance, _subject_value = _review_and_start_pilot(
                conn,
                imported.handle,
                f"pilot:{label}:{suffix}",
            )
            telemetry = LearningItemPilotTelemetryV1(
                item_handle=imported.handle,
                content_hash=source.content_hash,
                observation_window_hash=canonical_hash(
                    {"pilot": label, "suffix": suffix}
                ),
                sample_count=3,
                completed_count=3,
                cohort_complete=True,
                **telemetry_fields,
            )
            result = governance.record_pilot_telemetry(
                handle=imported.handle,
                telemetry=telemetry,
                expected_pilot_sequence=0,
                telemetry_key=f"pilot-result:{label}:{suffix}",
                occurred_at=_NOW,
            )
            replay = governance.record_pilot_telemetry(
                handle=imported.handle,
                telemetry=telemetry,
                expected_pilot_sequence=0,
                telemetry_key=f"pilot-result:{label}:{suffix}",
                occurred_at=_NOW,
            )
            assert result.publication is not None
            assert result.publication.state == expected_state
            assert replay.replayed is True
            assert replay.publication is not None
            assert replay.publication.event_id == result.publication.event_id
            with pytest.raises(
                LearningItemGovernanceConflict,
                match="current pilot state",
            ):
                governance.record_pilot_telemetry(
                    handle=imported.handle,
                    telemetry=telemetry.model_copy(
                        update={
                            "observation_window_hash": canonical_hash(
                                {"pilot": label, "next": suffix}
                            )
                        }
                    ),
                    expected_pilot_sequence=1,
                    telemetry_key=f"pilot-after-terminal:{label}:{suffix}",
                    occurred_at=_NOW,
                )
            assert all(
                item.item_key != item_key
                for item in repository.published_candidates(
                    knowledge_key=source.blueprint.knowledge_key,
                    available_capabilities=source.blueprint.required_capabilities,
                )
            )
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_learning_item_public_contents WHERE version_id=%s",
                (imported.version_id,),
            ).fetchone()["count"] == 1
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_learning_item_private_contents WHERE version_id=%s",
                (imported.version_id,),
            ).fetchone()["count"] == 1
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_learning_item_practice_materializations WHERE version_id=%s",
                (imported.version_id,),
            ).fetchone()["count"] == 0
            outcomes.append((item_key, imported.version_id, expected_state))

        assert len(outcomes) == 2
        conn.rollback()


def test_compiled_import_files_reject_duplicate_keys_links_size_and_empty_roots(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    bootstrap_database()
    suffix = uuid4().hex
    source, validation = _source(f"test.import-defense.{suffix}")
    artifact = LearningItemImportArtifactV1(
        source=source,
        validation_receipt=validation,
    )

    with connect() as conn:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(LearningItemImportFileError, match="no import artifacts"):
            import_curated_learning_item_sources(conn, source_root=empty, imported_at=_NOW)

        duplicate = tmp_path / "duplicate.learning-item.json"
        serialized = artifact.model_dump_json()
        duplicate.write_text(
            serialized.replace(
                '"schema_version":"learning_item_import_artifact_v1",',
                '"schema_version":"learning_item_import_artifact_v1",'
                '"schema_version":"learning_item_import_artifact_v1",',
                1,
            ),
            encoding="utf-8",
        )
        with pytest.raises(LearningItemImportFileError, match="file is invalid"):
            import_curated_learning_item_sources(conn, source_root=tmp_path, imported_at=_NOW)
        duplicate.unlink()

        oversized = tmp_path / "oversized.learning-item.json"
        oversized.write_bytes(b"x" * (1_048_576 + 1))
        with pytest.raises(LearningItemImportFileError, match="empty or too large"):
            import_curated_learning_item_sources(conn, source_root=tmp_path, imported_at=_NOW)
        oversized.unlink()

        target = tmp_path / "target.learning-item.json"
        target.write_text(artifact.model_dump_json(), encoding="utf-8")
        link = tmp_path / "link.learning-item.json"
        try:
            link.symlink_to(target)
        except OSError:
            target.unlink()
        else:
            with pytest.raises(LearningItemImportFileError, match="links or junctions"):
                import_curated_learning_item_sources(
                    conn,
                    source_root=tmp_path,
                    imported_at=_NOW,
                )
            link.unlink()
            target.unlink()

        repository = PostgresLearningItemBankRepository(conn)
        with pytest.raises(ValueError, match="safe relative path"):
            repository.import_validated_source(
                source=source,
                validation=validation,
                import_key=f"unsafe-path:{suffix}",
                source_path="C:/private/item.learning-item.json",
                source_file_hash=canonical_hash({"source": source.source_hash}),
                imported_at=_NOW,
            )
        conn.rollback()

