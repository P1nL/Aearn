from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.errors import CheckViolation

import app.routes.learning_artifacts as artifact_routes
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services.learning.artifacts.contracts import (
    TutorArtifactActionKind,
    TutorArtifactCreate,
    TutorArtifactDemoInteractionEvidenceV1,
    TutorArtifactDemoVisibleClockEvidenceV1,
    TutorArtifactDifficulty,
    TutorArtifactKind,
    TutorArtifactOwnerKind,
    TutorArtifactPurpose,
    TutorArtifactState,
    TutorArtifactDemonstrationPresentationV2,
    canonical_hash,
)
from app.services.learning.artifacts.conversation_events import (
    PostgresTutorArtifactConversationEventSink,
)
from app.services.learning.artifacts.demonstrations import (
    _validate_completion_evidence,
    build_demonstration_presentation,
    calculate_static_demonstration_duration_seconds,
)
from app.services.learning.artifacts.owner_adapters import ArtifactOwnerActionInvalid
from app.services.learning.artifacts.repository import PostgresLearningArtifactRepository
from app.services.learning.item_bank.contracts import (
    LearningItemDemoContentV2,
    LearningItemSourceV1,
)
from app.services.learning.item_bank.governance_repository import (
    PostgresLearningItemGovernanceRepository,
)
from app.services.learning.item_bank.repository import PostgresLearningItemBankRepository
from app.services.learning.item_bank.review_contracts import (
    REQUIRED_REVIEW_ROLES,
    LearningItemPilotTelemetryV1,
    LearningItemReviewReportV1,
)
from app.services.learning.item_bank.validation import validate_learning_item
from app.services.learning.teaching_contracts import TeachingSessionMode
from app.services.learning.teaching_sessions import TeachingSessionRepository
from app.services.repositories.local_user_data_repository import (
    delete_user_data,
    export_user_data,
    reset_user_data,
)
from app.services.tutor.continuation import ContinuationSourceKind
from app.services.tutor.cutover import HarnessCutoverService
from tests.support.teaching_session_support import (
    connection as teaching_connection,
    create_teaching_scope,
    database_available,
)


_NOW = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _DemoRouteFixture:
    user_id: str
    conversation_id: str
    learning_track_id: str
    teaching_session_id: str
    artifact_id: str
    required_visible_ms: int
    expected_event_key: str | None
    expected_event_payload: dict[str, object] | None
    expected_event_payload_hash: str | None


def _content(mode: str = "static_duration") -> LearningItemDemoContentV2:
    event = (
        {"event_name": "demo.click.completed", "payload_json": {"count": 1}}
        if mode == "exact_event"
        else None
    )
    return LearningItemDemoContentV2.model_validate(
        {
            "type": "demo_v2",
            "language_id": "javascript",
            "source_version": "v2",
            "read_only": True,
            "completion_mode": mode,
            "expected_event": event,
            "steps": [
                {
                    "step_key": "observe",
                    "title": "Observe",
                    "instruction_markdown": "Watch the value.",
                    "source_code": (
                        '<button data-aearn-event="demo.click.completed" '
                        "data-aearn-event-payload='{" + '"count":1' + "}'>Run</button>"
                    ),
                    "duration_seconds": 6 if mode == "static_duration" else None,
                }
            ],
        }
    )


def test_duration_fallback_is_deterministic_and_curriculum_bounded() -> None:
    first = calculate_static_demonstration_duration_seconds(
        source_content="const value = 1;",
        instruction_markdown="Observe the value.",
    )
    assert first == calculate_static_demonstration_duration_seconds(
        source_content="const value = 1;",
        instruction_markdown="Observe the value.",
    )
    assert 6 <= first <= 30


def test_static_descriptor_materializes_server_owned_hashes_duration_and_split() -> None:
    content = _content().model_copy(
        update={
            "steps": (
                _content().steps[0].model_copy(
                    update={"source_code": "x" * 24_001, "duration_seconds": 6}
                ),
            )
        }
    )
    presentation = build_demonstration_presentation(
        content=content,
        item_version="provider-cannot-use-this-field",
        instruction_markdown="provider-cannot-use-this-field",
    )
    assert isinstance(presentation, TutorArtifactDemonstrationPresentationV2)
    assert presentation.demonstration_mode == "static"
    assert presentation.source_version == "v2"
    assert len(presentation.steps) == 3
    assert presentation.total_duration_seconds == sum(
        step.duration_seconds or 0 for step in presentation.steps
    )
    assert all(6 <= (step.duration_seconds or 0) <= 30 for step in presentation.steps)
    assert all(len(step.source_content) <= 12_000 for step in presentation.steps)
    assert all(
        step.instruction_markdown == content.steps[0].instruction_markdown
        for step in presentation.steps
    )


def test_interactive_completion_requires_exact_event_key_payload_and_bridge_shape() -> None:
    presentation = build_demonstration_presentation(
        content=_content("exact_event"),
        item_version="ignored",
        instruction_markdown="ignored",
    )
    expected = presentation.expected_event
    assert expected is not None
    evidence = TutorArtifactDemoInteractionEvidenceV1(
        event_key=expected.event_key,
        payload_json=expected.payload_json,
        payload_hash=expected.payload_hash,
        preview_nonce="a" * 64,
        preview_generation=1,
        preview_sequence=1,
    )
    _validate_completion_evidence(presentation=presentation, evidence=evidence)
    for mismatched in (
        evidence.model_copy(update={"event_key": "demo.other"}),
        evidence.model_copy(
            update={
                "payload_json": {"count": 2},
                "payload_hash": canonical_hash({"count": 2}),
            }
        ),
    ):
        with pytest.raises(ArtifactOwnerActionInvalid, match="exactly match"):
            _validate_completion_evidence(
                presentation=presentation,
                evidence=mismatched,
            )
    with pytest.raises(ValueError, match="preview_nonce"):
        TutorArtifactDemoInteractionEvidenceV1(
            event_key=expected.event_key,
            payload_json=expected.payload_json,
            payload_hash=expected.payload_hash,
            preview_nonce="spoofed",
            preview_generation=1,
            preview_sequence=1,
        )
    for identity_field in ("preview_generation", "preview_sequence"):
        with pytest.raises(ValueError):
            TutorArtifactDemoInteractionEvidenceV1(
                event_key=expected.event_key,
                payload_json=expected.payload_json,
                payload_hash=expected.payload_hash,
                preview_nonce="a" * 64,
                **{
                    "preview_generation": 1,
                    "preview_sequence": 1,
                    identity_field: 2_147_483_648,
                },
            )


def test_demo_event_payload_is_limited_to_the_isolated_preview_bridge_shape() -> None:
    oversized = {"message": "x" * 2_100}
    with pytest.raises(ValueError, match="demo event payload is too large"):
        TutorArtifactDemoInteractionEvidenceV1(
            event_key="demo.click.completed",
            payload_json=oversized,
            payload_hash=canonical_hash(oversized),
            preview_nonce="a" * 64,
            preview_generation=1,
            preview_sequence=1,
        )

    deeply_nested: dict[str, object] = {"leaf": True}
    for index in range(7):
        deeply_nested = {f"level{index}": deeply_nested}
    with pytest.raises(ValueError, match="unsupported JSON shape"):
        TutorArtifactDemoInteractionEvidenceV1(
            event_key="demo.click.completed",
            payload_json=deeply_nested,
            payload_hash=canonical_hash(deeply_nested),
            preview_nonce="a" * 64,
            preview_generation=1,
            preview_sequence=1,
        )

    published = _content("exact_event").model_dump(mode="json")
    published["expected_event"] = {
        "event_name": "demo.click.completed",
        "payload_json": oversized,
    }
    with pytest.raises(ValueError, match="demo event payload"):
        LearningItemDemoContentV2.model_validate(published)


def test_static_completion_requires_exact_bounded_visible_elapsed_time() -> None:
    presentation = build_demonstration_presentation(
        content=_content(),
        item_version="ignored",
        instruction_markdown="ignored",
    )
    assert presentation.total_duration_seconds == 6
    accepted = TutorArtifactDemoVisibleClockEvidenceV1(
        clock_session_id="clock-session-1",
        visible_elapsed_ms=6_000,
    )
    _validate_completion_evidence(presentation=presentation, evidence=accepted)
    for elapsed in (5_999, 8_001):
        with pytest.raises((ValueError, ArtifactOwnerActionInvalid)):
            candidate = TutorArtifactDemoVisibleClockEvidenceV1(
                clock_session_id="clock-session-1",
                visible_elapsed_ms=elapsed,
            )
            _validate_completion_evidence(
                presentation=presentation,
                evidence=candidate,
            )


@pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")
@pytest.mark.parametrize(
    ("mode", "expected_source_kind"),
    [
        ("exact_event", ContinuationSourceKind.EXPECTED_INTERACTIVE_EVENT),
        ("static_duration", ContinuationSourceKind.STATIC_DISPLAY_TIMER),
    ],
)
def test_complete_demo_http_route_persists_receipt_continuation_and_exact_replay(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_source_kind: ContinuationSourceKind,
) -> None:
    bootstrap_database()
    fixture = _seed_demo_route_fixture(mode=mode)
    dispatches: list[tuple[str, str]] = []
    _configure_artifact_routes(monkeypatch, enabled=True)
    monkeypatch.setattr(
        artifact_routes,
        "enqueue_tutor_interactive_dispatch",
        lambda job_id, *, runtime_kind: dispatches.append((job_id, runtime_kind)),
    )
    endpoint = (
        f"/api/tutor/conversations/{fixture.conversation_id}"
        f"/artifacts/{fixture.artifact_id}/actions"
    )
    body = _completion_payload(fixture, mode=mode, client_action_id="body-demo-complete")
    key = f"demo-route-{mode}-{uuid4().hex}"
    try:
        with TestClient(app) as client:
            first = client.post(endpoint, headers={"Idempotency-Key": key}, json=body)
            replay = client.post(endpoint, headers={"Idempotency-Key": key}, json=body)
            collision = client.post(
                endpoint,
                headers={"Idempotency-Key": key},
                json=_completion_payload(
                    fixture,
                    mode=mode,
                    client_action_id="body-demo-collision",
                    changed=True,
                ),
            )

        assert first.status_code == 200, first.text
        assert first.json()["artifact"]["state"] == "completed"
        assert first.json()["artifact"]["version"] == 2
        assert first.json()["artifact"]["active_attempt"] is None
        assert first.json()["idempotent_replayed"] is False
        assert replay.status_code == 200, replay.text
        assert replay.json()["idempotent_replayed"] is True
        _assert_error(collision, "IDEMPOTENCY_CONFLICT", 409)
        assert "preview_nonce" not in first.text
        assert "clock_session_id" not in first.text

        with connect() as conn:
            receipt = conn.execute(
                """
                SELECT id::text AS id, completion_kind, source_nonce,
                       source_generation, source_sequence, visible_elapsed_ms,
                       required_visible_ms, request_hash
                FROM tutor_demonstration_completion_receipts
                WHERE artifact_id = %s AND user_id = %s
                """,
                (fixture.artifact_id, fixture.user_id),
            ).fetchone()
            assert receipt is not None
            assert receipt["completion_kind"] == (
                "interactive_event" if mode == "exact_event" else "visible_clock"
            )
            intent = conn.execute(
                """
                SELECT source_kind, source_id, source_version,
                       state, consumed_run_id::text AS run_id
                FROM tutor_continuation_intents
                WHERE artifact_id = %s AND user_id = %s
                """,
                (fixture.artifact_id, fixture.user_id),
            ).fetchone()
            assert intent is not None
            assert intent["source_kind"] == expected_source_kind.value
            assert intent["state"] == "consumed"
            assert intent["run_id"] is not None
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_runs WHERE user_id = %s",
                (fixture.user_id,),
            ).fetchone() == {"count": 1}
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_demonstration_completion_receipts WHERE artifact_id = %s",
                (fixture.artifact_id,),
            ).fetchone() == {"count": 1}
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_continuation_intents WHERE artifact_id = %s",
                (fixture.artifact_id,),
            ).fetchone() == {"count": 1}
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_exercise_attempts WHERE user_id = %s",
                (fixture.user_id,),
            ).fetchone() == {"count": 0}
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_mastery_evidence WHERE user_id = %s",
                (fixture.user_id,),
            ).fetchone() == {"count": 0}
            assert conn.execute(
                "SELECT progress_version AS version FROM tutor_teaching_sessions WHERE id = %s",
                (fixture.teaching_session_id,),
            ).fetchone() == {"version": 1}
        assert len(dispatches) == 1
        assert dispatches[0][1] == "harness_v1"
    finally:
        _cleanup_user(fixture.user_id)


@pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")
def test_demo_schema_bootstrap_append_only_export_cutover_and_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_database()
    bootstrap_database()
    fixture = _seed_demo_route_fixture(mode="exact_event")
    _configure_artifact_routes(monkeypatch, enabled=True)
    monkeypatch.setattr(
        artifact_routes,
        "enqueue_tutor_interactive_dispatch",
        lambda *_args, **_kwargs: None,
    )
    try:
        _complete_via_route(fixture, mode="exact_event")
        with teaching_connection() as conn:
            trigger = conn.execute(
                """
                SELECT tgname FROM pg_trigger
                WHERE tgrelid = 'tutor_demonstration_completion_receipts'::regclass
                  AND NOT tgisinternal
                """
            ).fetchall()
            assert {str(row["tgname"]) for row in trigger} == {
                "trg_tutor_demo_completion_receipts_guard"
            }
            with pytest.raises(CheckViolation, match="append-only"):
                conn.execute(
                    "UPDATE tutor_demonstration_completion_receipts SET completed_at = now() WHERE artifact_id = %s",
                    (fixture.artifact_id,),
                )
            conn.rollback()
            with pytest.raises(CheckViolation, match="append-only"):
                conn.execute(
                    "DELETE FROM tutor_demonstration_completion_receipts WHERE artifact_id = %s",
                    (fixture.artifact_id,),
                )
            conn.rollback()

            exported = cast(dict[str, Any], export_user_data(conn, fixture.user_id))
            assert len(exported["demonstration_completion_summaries"]) == 1
            demo_export = exported["demonstration_completion_summaries"][0]
            for protected in (
                "source_nonce",
                "source_generation",
                "source_sequence",
                "event_payload_hash",
                "request_hash",
                "idempotency_key",
            ):
                assert protected not in demo_export
            assert (
                exported["redaction"][
                    "demonstration_completion_nonces_and_request_hashes"
                ]
                == "omitted"
            )
            inventory = HarnessCutoverService(conn)._inventory(fixture.user_id)
            assert inventory.target_counts[
                "tutor_demonstration_completion_receipts"
            ] == 1
            reset = cast(dict[str, Any], reset_user_data(conn, fixture.user_id))
            assert reset["summary"]["counts"]["demonstration_completions"] == 0
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_demonstration_completion_receipts WHERE user_id = %s",
                (fixture.user_id,),
            ).fetchone() == {"count": 0}
            conn.commit()
            fixture = replace(fixture, user_id="")
    finally:
        if fixture.user_id:
            _cleanup_user(fixture.user_id)



@pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")
def test_demo_completion_receipt_user_delete_uses_child_first_purge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_database()
    fixture = _seed_demo_route_fixture(mode="exact_event")
    _configure_artifact_routes(monkeypatch, enabled=True)
    monkeypatch.setattr(
        artifact_routes,
        "enqueue_tutor_interactive_dispatch",
        lambda *_args, **_kwargs: None,
    )
    try:
        _complete_via_route(fixture, mode="exact_event")
        with teaching_connection() as conn:
            deleted = cast(dict[str, Any], delete_user_data(conn, fixture.user_id))
            assert deleted["deleted_user_id"] == fixture.user_id
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_demonstration_completion_receipts WHERE user_id = %s",
                (fixture.user_id,),
            ).fetchone() == {"count": 0}
            assert conn.execute(
                "SELECT deleted_at IS NOT NULL AS deleted FROM users WHERE id = %s",
                (fixture.user_id,),
            ).fetchone() == {"deleted": True}
            conn.commit()
            fixture = replace(fixture, user_id="")
    finally:
        if fixture.user_id:
            _cleanup_user(fixture.user_id)


def _published_demo_item(
    conn: Connection[dict[str, object]],
    *,
    mode: str,
) -> tuple[LearningItemSourceV1, str, int, str]:
    suffix = uuid4().hex
    capability = f"javascript.demo.{suffix[:12]}"
    item_key = f"javascript.demo.{mode}.{suffix}"
    source_reference = {
        "source_id": "aearn.docs",
        "source_version": "2026.09",
        "locator": f"demo.{suffix}",
        "content_hash": canonical_hash({"source": suffix}),
    }
    content = _content(mode)
    source = LearningItemSourceV1.model_validate(
        {
            "schema_version": "learning_item_source_v1",
            "blueprint": {
                "schema_version": "learning_item_blueprint_v1",
                "blueprint_key": f"blueprint.{item_key}",
                "version": "v1",
                "knowledge_key": "python.variables",
                "item_kind": "demo",
                "purpose": "demonstration",
                "language_id": "javascript",
                "difficulty_profile": {
                    "base": "D1",
                    "reasoning_depth": 1,
                    "concept_count": 1,
                    "context_novelty": 1,
                    "transfer_distance": 1,
                    "response_complexity": 1,
                    "scaffolding": 5,
                },
                "prerequisite_keys": [],
                "required_capabilities": [capability],
                "runtime_profile_id": "browser_preview",
                "allowed_interactions": ["observe"],
                "publication_policy": {
                    "risk_tier": "low",
                    "required_review_roles": [
                        role.value for role in REQUIRED_REVIEW_ROLES
                    ],
                    "agent_review_required": True,
                    "pilot_required": True,
                    "human_approval_required": False,
                },
                "source_references": [source_reference],
            },
            "public": {
                "schema_version": "learning_item_public_v1",
                "item_key": item_key,
                "version": "v1",
                "kind": "demo",
                "purpose": "demonstration",
                "title": f"Published {mode} demonstration",
                "difficulty": "D1",
                "instruction_markdown": "Observe the published demonstration.",
                "allowed_interactions": ["observe"],
                "hints": [],
                "source_references": [source_reference],
                "content": content.model_dump(mode="json"),
            },
            "private": {
                "schema_version": "learning_item_private_v1",
                "item_key": item_key,
                "version": "v1",
                "kind": "demo",
                "content": {
                    "type": "demo_v2",
                    "expected_events": (
                        [content.expected_event.model_dump(mode="json")]
                        if content.expected_event is not None
                        else []
                    ),
                    "validation_policy_version": "demo_event_v2",
                },
            },
        }
    )
    validation = validate_learning_item(source)
    imported = PostgresLearningItemBankRepository(conn).import_validated_source(
        source=source,
        validation=validation,
        import_key=f"demo-import:{suffix}",
        source_path=f"tests/demo-{suffix}.learning-item.json",
        source_file_hash=canonical_hash({"source_hash": source.source_hash}),
        imported_at=_NOW,
    )
    governance = PostgresLearningItemGovernanceRepository(conn)
    subject = governance.load_review_subject(handle=imported.handle)
    reports = tuple(
        LearningItemReviewReportV1(
            item_handle=imported.handle,
            content_hash=source.content_hash,
            review_input_hash=subject.blind_input(role).review_input_hash,
            role=role,
            reviewer_identity=f"reviewer.{role.value}.{suffix[:8]}",
            verdict="approved",
        )
        for role in REQUIRED_REVIEW_ROLES
    )
    review = governance.record_review_bundle(
        subject=subject,
        reports=reports,
        bundle_key=f"demo-review:{suffix}",
        occurred_at=_NOW,
    )
    assert review.publication is not None
    pilot = governance.start_pilot(
        handle=imported.handle,
        transition_key=f"demo-pilot:{suffix}",
        occurred_at=_NOW,
    )
    assert pilot.state == "pilot"
    publication = governance.record_pilot_telemetry(
        handle=imported.handle,
        telemetry=LearningItemPilotTelemetryV1(
            item_handle=imported.handle,
            content_hash=source.content_hash,
            observation_window_hash=canonical_hash({"pilot": suffix}),
            sample_count=1,
            completed_count=1,
            cohort_complete=True,
        ),
        expected_pilot_sequence=0,
        telemetry_key=f"demo-telemetry:{suffix}",
        occurred_at=_NOW,
    ).publication
    assert publication is not None and publication.state == "published"
    return source, imported.version_id, publication.state_version, capability


def _seed_demo_route_fixture(*, mode: str) -> _DemoRouteFixture:
    with teaching_connection() as conn:
        source, version_id, publication_version, capability = _published_demo_item(
            conn,
            mode=mode,
        )
        scope = create_teaching_scope(conn, required_capabilities=(capability,))
        teaching = TeachingSessionRepository(conn)
        with conn.transaction():
            authority = teaching.resolve_authority(
                user_id=str(scope["user_id"]),
                track_id=str(scope["track_id"]),
                knowledge_key=str(scope["knowledge_key"]),
                conversation_id=str(scope["conversation_id"]),
                for_update=True,
            )
            session_row, created = teaching.open_or_resume(
                authority=authority,
                mode=TeachingSessionMode.GUIDED,
            )
        assert created is True
        session = teaching.project_session(session_row)
        presentation = build_demonstration_presentation(
            content=cast(LearningItemDemoContentV2, source.public.content),
            item_version=source.public.version,
            instruction_markdown=source.public.instruction_markdown,
        )
        created_artifact = PostgresLearningArtifactRepository(
            conn,
            conversation_events=PostgresTutorArtifactConversationEventSink(conn),
        ).create_artifact(
            TutorArtifactCreate(
                user_id=str(scope["user_id"]),
                conversation_id=str(scope["conversation_id"]),
                learning_track_id=str(scope["track_id"]),
                knowledge_key=str(scope["knowledge_key"]),
                teaching_session_id=str(session["session_id"]),
                checkpoint_id=str(session["checkpoint_id"]),
                track_version=int(scope["track_version"]),
                progress_version=int(scope["progress_version"]),
                assignment_version=int(scope["assignment_version"]),
                owner_kind=TutorArtifactOwnerKind.LEARNING_ITEM,
                owner_id=version_id,
                owner_version=publication_version,
                owner_context_version=int(session["session_version"]),
                artifact_kind=TutorArtifactKind.DEMONSTRATION,
                purpose=TutorArtifactPurpose.DEMONSTRATION,
                state=TutorArtifactState.ACTIVE,
                blocking=True,
                title=source.public.title,
                instruction_markdown=source.public.instruction_markdown,
                difficulty=TutorArtifactDifficulty.D1,
                presentation=presentation,
                allowed_actions=(
                    TutorArtifactActionKind.COMPLETE_DEMO,
                    TutorArtifactActionKind.CANCEL,
                ),
            ),
            creation_key=f"demo-artifact:{uuid4().hex}",
            occurred_at=_NOW,
        )
        conn.commit()
        expected = presentation.expected_event
        return _DemoRouteFixture(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            learning_track_id=str(scope["track_id"]),
            teaching_session_id=str(session["session_id"]),
            artifact_id=created_artifact.artifact.id,
            required_visible_ms=int(presentation.total_duration_seconds or 0) * 1_000,
            expected_event_key=expected.event_key if expected is not None else None,
            expected_event_payload=(
                dict(expected.payload_json) if expected is not None else None
            ),
            expected_event_payload_hash=(
                expected.payload_hash if expected is not None else None
            ),
        )


def _completion_payload(
    fixture: _DemoRouteFixture,
    *,
    mode: str,
    client_action_id: str,
    changed: bool = False,
) -> dict[str, object]:
    if mode == "exact_event":
        payload = dict(fixture.expected_event_payload or {})
        if changed:
            payload["count"] = 2
        evidence: dict[str, object] = {
            "kind": "interactive_event",
            "event_key": fixture.expected_event_key,
            "payload_json": payload,
            "payload_hash": canonical_hash(payload),
            "preview_nonce": ("b" if changed else "a") * 64,
            "preview_generation": 2 if changed else 1,
            "preview_sequence": 2 if changed else 1,
        }
    else:
        evidence = {
            "kind": "visible_clock",
            "clock_session_id": "clock-session-2" if changed else "clock-session-1",
            "visible_elapsed_ms": fixture.required_visible_ms + (1 if changed else 0),
            "foreground": True,
            "current": True,
            "visible": True,
            "render_ready": True,
        }
    return {
        "user_id": fixture.user_id,
        "learning_track_id": fixture.learning_track_id,
        "teaching_session_id": fixture.teaching_session_id,
        "client_action_id": client_action_id,
        "expected_artifact_version": 1,
        "action": {"action": "complete_demo", "evidence": evidence},
    }


def _complete_via_route(fixture: _DemoRouteFixture, *, mode: str) -> None:
    with TestClient(app) as client:
        response = client.post(
            f"/api/tutor/conversations/{fixture.conversation_id}"
            f"/artifacts/{fixture.artifact_id}/actions",
            headers={"Idempotency-Key": f"demo-lifecycle-{uuid4().hex}"},
            json=_completion_payload(
                fixture,
                mode=mode,
                client_action_id="demo-lifecycle-body",
            ),
        )
    assert response.status_code == 200, response.text


def _configure_artifact_routes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool,
) -> None:
    settings = Settings(
        llm_type="disabled",
        tutor_learning_artifacts_enabled=enabled,
        tutor_artifact_teaching_mode_enabled=True,
        tutor_thread_turn_v2_enabled=True,
    )
    monkeypatch.setattr(artifact_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(artifact_routes, "runtime_gate_error", lambda **_kwargs: None)
    monkeypatch.setattr(
        artifact_routes,
        "thread_turn_v2_gate_error",
        lambda **_kwargs: None,
    )


def _assert_error(response: Any, code: str, status_code: int) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["request_id"], str)


def _cleanup_user(user_id: str) -> None:
    with teaching_connection() as conn:
        reset_user_data(conn, user_id)
        conn.commit()
