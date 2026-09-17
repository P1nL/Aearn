from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from starlette.routing import Route

from app.core.config import Settings
from app.db.schema import SCHEMA_FRAGMENT_NAMES, schema_fragment_paths
from app.main import app
from app.services.learning.artifacts.contracts import (
    TUTOR_LEARNING_ARTIFACT_SCHEMA_VERSION,
    TutorArtifactActionKind,
    TutorArtifactActionV1,
    TutorArtifactKind,
    TutorArtifactPresentationV1,
    TutorArtifactPurpose,
    TutorArtifactSourceReferenceV1,
    TutorPublicArtifactItem,
)
from app.services.tutor.conversation_contracts import (
    TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION,
    TUTOR_CONVERSATION_READABLE_SNAPSHOT_VERSIONS,
    TutorPublicItem,
    TutorPublicItemReference,
)
from app.services.tutor.decision_gate import TeachingTutorDecisionGate

_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_API_ROOT = Path(__file__).resolve().parents[2]
_DESKTOP_ROOT = _REPOSITORY_ROOT / "aearn" / "apps" / "desktop"
_CURRENT_TEACHING_SKILL = (
    f"{TeachingTutorDecisionGate._SKILL_ID}@{TeachingTutorDecisionGate._SKILL_VERSION}"
)
_EXPECTED_PRESENTATIONS = {
    "exercise_workspace_v1",
    "browser_preview_v1",
    "test_result_v1",
    "knowledge_check_v1",
    "model_code_review_v1",
    "model_code_review_v2",
    "sql_workspace_v1",
    "sql_workspace_v2",
    "demonstration_v1",
    "demonstration_v2",
    "source_inspector_v1",
}
_EXPECTED_ACTIONS = {
    "request_hint",
    "request_direct_answer",
    "run",
    "respond",
    "complete_review",
    "cancel",
    "acknowledge_demo_event",
    "complete_demo",
}
_EXPECTED_ARTIFACT_KINDS = {
    "exercise_workspace",
    "browser_preview",
    "test_result",
    "knowledge_check",
    "model_code_review",
    "sql_workspace",
    "demonstration",
    "source_inspector",
}
_EXPECTED_PURPOSES = {
    "exercise",
    "demonstration",
    "knowledge_check",
    "remediation",
    "transfer_check",
    "code_review",
    "sql_exploration",
    "result",
}
_EXPECTED_SOURCE_KINDS = {
    "lesson_document",
    "exercise_version",
    "attempt_result",
    "review_session",
    "teaching_checkpoint",
    "source_citation",
    "artifact",
}

_EXPECTED_ACTION_FIELDS = {
    "request_hint": {"action", "hint_level"},
    "request_direct_answer": {"action"},
    "run": {"action", "submission"},
    "respond": {"action", "response"},
    "complete_review": {"action", "review_submission"},
    "cancel": {"action", "reason"},
    "acknowledge_demo_event": {"action", "event_key", "event_nonce"},
    "complete_demo": {"action", "evidence"},
}

# This platform owns a named, ordered migration segment, not the total number
# of all present/future schema fragments. The complete manifest is separately
# pinned by tests/database/test_schema_manifest.py.
_REQUIRED_PLATFORM_SCHEMA_SEGMENT = (
    "120_learning_artifacts.sql",
    "130_learning_item_bank.sql",
    "140_learning_item_governance.sql",
    "150_tutor_branch_continuation.sql",
    "160_teaching_artifact_commit.sql",
    "170_teaching_demonstrations.sql",
    "180_knowledge_checks.sql",
    "190_model_review_artifacts.sql",
    "200_sql_learning_workspace.sql",
    "210_tutor_branch_supersession.sql",
    "220_plan_catalog_knowledge_scope.sql",
    "230_artifact_authority_supersession.sql",
    "240_deepseek_flash_runtime_cutover.sql",
)


def _assert_platform_schema_segment(names: tuple[str, ...]) -> None:
    assert len(names) == len(set(names)), "schema fragments must remain unique"
    assert set(_REQUIRED_PLATFORM_SCHEMA_SEGMENT) <= set(names), "required platform fragment missing"
    assert "110_thread_turn_codex.sql" in names
    start = names.index(_REQUIRED_PLATFORM_SCHEMA_SEGMENT[0])
    end = names.index(_REQUIRED_PLATFORM_SCHEMA_SEGMENT[-1]) + 1
    assert names[start:end] == _REQUIRED_PLATFORM_SCHEMA_SEGMENT
    assert names.index("110_thread_turn_codex.sql") < start


def _assert_document_section(text: str, heading: str, markers: tuple[str, ...]) -> None:
    assert heading in text, f"missing current heading: {heading}"
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    for marker in markers:
        assert marker in section, f"{heading} missing current marker: {marker}"


def _discriminator_values(contract: object) -> set[str]:
    schema = TypeAdapter(contract).json_schema()
    discriminator = schema.get("discriminator")
    assert isinstance(discriminator, dict)
    mapping = discriminator.get("mapping")
    assert isinstance(mapping, dict)
    return {str(item) for item in mapping}


def _typescript_object_keys(path: Path, start: str, end: str) -> set[str]:
    source = path.read_text(encoding="utf-8")
    segment = source.split(start, 1)[1].split(end, 1)[0]
    return set(re.findall(r"^  ([a-z0-9_]+):", segment, flags=re.MULTILINE))


def _discriminator_property_keys(contract: object) -> dict[str, set[str]]:
    schema = TypeAdapter(contract).json_schema()
    discriminator = schema["discriminator"]
    definitions = schema["$defs"]
    assert isinstance(discriminator, dict) and isinstance(definitions, dict)
    mapping = discriminator["mapping"]
    assert isinstance(mapping, dict)
    result: dict[str, set[str]] = {}
    for value, reference in mapping.items():
        definition = definitions[str(reference).rsplit("/", 1)[-1]]
        assert isinstance(definition, dict)
        properties = definition["properties"]
        assert isinstance(properties, dict)
        result[str(value)] = set(properties)
    return result


def test_backend_desktop_artifact_contract_matrix_is_closed_and_aligned() -> None:
    assert TUTOR_LEARNING_ARTIFACT_SCHEMA_VERSION == "tutor_learning_artifact_v1"
    assert _discriminator_values(TutorArtifactPresentationV1) == _EXPECTED_PRESENTATIONS
    assert _discriminator_values(TutorArtifactActionV1) == _EXPECTED_ACTIONS
    assert _discriminator_property_keys(TutorArtifactActionV1) == _EXPECTED_ACTION_FIELDS
    assert _discriminator_values(TutorPublicItem) == {
        "message", "process", "elicitation", "approval", "error", "artifact",
    }
    item_reference_schema = TutorPublicItemReference.model_json_schema()
    assert set(item_reference_schema["properties"]["item_kind"]["enum"]) == {
        "message", "process", "elicitation", "approval", "error", "artifact",
    }
    artifact_schema = TutorPublicArtifactItem.model_json_schema()
    assert artifact_schema["properties"]["artifact_version"]["const"] == 1
    assert {item.value for item in TutorArtifactActionKind} == _EXPECTED_ACTIONS
    assert {item.value for item in TutorArtifactKind} == _EXPECTED_ARTIFACT_KINDS
    assert {item.value for item in TutorArtifactPurpose} == _EXPECTED_PURPOSES

    source_schema = TutorArtifactSourceReferenceV1.model_json_schema()
    source_kinds = source_schema["properties"]["kind"]["enum"]
    assert set(source_kinds) == _EXPECTED_SOURCE_KINDS

    registry = _typescript_object_keys(
        _DESKTOP_ROOT / "src/features/tutor/artifacts/ArtifactRendererRegistry.tsx",
        "const ARTIFACT_RENDERER_REGISTRY = {",
        "} satisfies Record<ArtifactPresentationType, ArtifactRenderer>;",
    )
    action_labels = _typescript_object_keys(
        _DESKTOP_ROOT / "src/features/tutor/artifacts/InlineArtifactMessage.tsx",
        "const ACTION_LABELS: Record<TutorArtifactAction, string> = {",
        "};",
    )
    assert registry == _EXPECTED_PRESENTATIONS
    assert action_labels == _EXPECTED_ACTIONS

    desktop_contract = (_DESKTOP_ROOT / "src/contracts/tutor.ts").read_text(encoding="utf-8")
    desktop_api = (_DESKTOP_ROOT / "src/api/tutor.ts").read_text(encoding="utf-8")
    assert 'artifact_version: 1;' in desktop_contract
    assert 'export type TutorHistoryItem = TutorHistoryMessage | TutorPublicProcess | TutorInteractionRequestItem | TutorHistoryError | TutorPublicArtifactItem;' in desktop_contract
    for shape in (
        '{ action: "request_hint"; hint_level: number | null }',
        '{ action: "request_direct_answer" }',
        '{ action: "run"; submission: string }',
        '{ action: "respond"; response: TutorArtifactResponse }',
        '{ action: "complete_review"; review_submission: ModelCodeReviewSubmission | ModelCodeReviewSubmissionV2 }',
        '{ action: "cancel"; reason: "learner_cancelled" }',
        '{ action: "acknowledge_demo_event"; event_key: string; event_nonce: string }',
        'action: "complete_demo";',
        'evidence:',
    ):
        assert shape in desktop_contract
    desktop_snapshot_versions = set(re.findall(r'tutor_conversation_snapshot_v[2-5]', desktop_api))
    assert desktop_snapshot_versions == {
        "tutor_conversation_snapshot_v2",
        "tutor_conversation_snapshot_v3",
        "tutor_conversation_snapshot_v4",
        "tutor_conversation_snapshot_v5",
    }


def test_routes_flags_schema_and_import_boundaries_are_reconciled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TUTOR_LEARNING_ARTIFACTS_ENABLED",
        "TUTOR_ARTIFACT_TEACHING_MODE_ENABLED",
        "LEARNING_ITEM_BANK_AGENT_REVIEW_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.tutor_learning_artifacts_enabled is False
    assert settings.tutor_artifact_teaching_mode_enabled is False
    assert settings.learning_item_bank_agent_review_enabled is False

    routes = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, Route)
        for method in route.methods or set()
    }
    assert {
        ("GET", "/api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}"),
        ("POST", "/api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}/actions"),
        ("GET", "/api/tutor/conversations/{conversation_id}/artifacts/{artifact_id}/attempts/{attempt_id}"),
        ("POST", "/api/learning-tracks/{track_id}/lesson-references/{conversation_id}/resolve"),
    } <= routes

    _assert_platform_schema_segment(SCHEMA_FRAGMENT_NAMES)
    assert tuple(path.name for path in schema_fragment_paths()) == SCHEMA_FRAGMENT_NAMES
    fragment_110 = (_API_ROOT / "app/db/schema/110_thread_turn_codex.sql").read_text(encoding="utf-8")
    assert "tutor_conversation_event_v3" in fragment_110
    assert "chk_tutor_conversation_events_projection_version" in fragment_110

    artifact_init = _API_ROOT / "app/services/learning/artifacts/__init__.py"
    tree = ast.parse(artifact_init.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imported_modules == {"contracts"}
    assert (_REPOSITORY_ROOT / "docs/design/learning-agent-claude-desktop-framework.html").is_file()

    env_example = (_REPOSITORY_ROOT / "aearn/.env.example").read_text(encoding="utf-8")
    for line in (
        "TUTOR_LEARNING_ARTIFACTS_ENABLED=false",
        "TUTOR_ARTIFACT_TEACHING_MODE_ENABLED=false",
        "LEARNING_ITEM_BANK_AGENT_REVIEW_ENABLED=false",
    ):
        assert line in env_example


def test_platform_schema_guard_accepts_append_only_followup() -> None:
    _assert_platform_schema_segment((*SCHEMA_FRAGMENT_NAMES, "250_future_increment.sql"))


@pytest.mark.parametrize("change", ("missing", "reordered", "duplicate", "early_owner_late"))
def test_platform_schema_guard_keeps_missing_reorder_duplicate_and_early_owner_fences(change: str) -> None:
    names = list(SCHEMA_FRAGMENT_NAMES)
    if change == "missing":
        names.remove("230_artifact_authority_supersession.sql")
    elif change == "reordered":
        first = names.index("220_plan_catalog_knowledge_scope.sql")
        second = names.index("230_artifact_authority_supersession.sql")
        names[first], names[second] = names[second], names[first]
    elif change == "duplicate":
        names.append("240_deepseek_flash_runtime_cutover.sql")
    else:
        names.remove("110_thread_turn_codex.sql")
        names.append("110_thread_turn_codex.sql")
    with pytest.raises(AssertionError):
        _assert_platform_schema_segment(tuple(names))


def test_current_document_markers_cannot_be_satisfied_by_historical_sections() -> None:
    text = "## Current\ncurrent facts\n## Historical\nold green evidence"
    _assert_document_section(text, "## Current", ("current facts",))
    with pytest.raises(AssertionError, match="missing current marker"):
        _assert_document_section(text, "## Current", ("old green evidence",))


def test_every_artifact_family_has_reproducible_happy_and_bad_path_evidence() -> None:
    evidence = {
        "html_preview": (
            ("aearn/services/api/tests/tutor/test_tutor_teaching_artifact_commit.py", "test_artifact_teaching_commit_is_atomic_and_materializes_exact_learning_item", "test_publication_change_after_decision_context_rolls_back_message_checkpoint_and_artifact"),
            ("aearn/apps/desktop/src/features/tutor/artifacts/CodeEditorArtifact.test.tsx", "sends the exact latest draft only on explicit Run", "keeps terminal Artifacts read-only and denies Run"),
            ("aearn/apps/desktop/src-tauri/src/preview_host.rs", "host_uses_custom_protocol_and_script_only_sandbox", "bridge_rejects_nonce_scope_version_replay_and_oversized_messages"),
        ),
        "result": (
            ("aearn/services/api/tests/learning/test_execution_result_artifacts.py", "test_postgres_projector_is_atomic_idempotent_and_keeps_run_history", "test_postgres_projector_rejects_partial_source_only_persistence"),
            ("aearn/apps/desktop/src/features/tutor/artifacts/ExecutionResultArtifact.test.tsx", "loads scoped Attempt v2 detail", "fails closed when a typed loader returns another Artifact scope"),
        ),
        "demonstration": (
            ("aearn/services/api/tests/learning/test_teaching_demonstrations.py", "test_complete_demo_http_route_persists_receipt_continuation_and_exact_replay", "test_interactive_completion_requires_exact_event_key_payload_and_bridge_shape"),
            ("aearn/apps/desktop/src/features/tutor/artifacts/DemonstrationArtifact.test.tsx", "counts only visible foreground time", "accepts only the exact Preview event payload"),
        ),
        "knowledge_hint_remediation": (
            ("aearn/services/api/tests/learning/test_knowledge_checks.py", "test_answered_presentation_is_locked_and_result_fields_are_atomic", "test_knowledge_check_contract_rejects_extra_fields_and_invalid_hint_order"),
            ("aearn/apps/desktop/src/features/tutor/artifacts/KnowledgeCheckArtifact.test.tsx", "submits a structured response and keeps the original immutable", "unlocks each hint only through an explicit server action"),
        ),
        "model_review": (
            ("aearn/services/api/tests/learning/test_model_review_artifacts.py", "test_model_review_artifact_receipt_remediation_and_continuation_are_authoritative", "test_failed_model_review_without_published_remediation_rolls_back_everything"),
            ("aearn/apps/desktop/src/features/tutor/artifacts/ModelCodeReviewArtifact.test.tsx", "submits one closed v2 finding payload", "fails closed when an active review does not advertise complete_review"),
        ),
        "sql": (
            ("aearn/services/api/tests/runners/test_sql_query_runner.py", "test_sql_workspace_executes_public_and_hidden_datasets_independently", "test_sql_workspace_rejects_unpublished_tables_and_excess_columns"),
            ("aearn/apps/desktop/src/features/tutor/artifacts/SqlWorkspaceArtifact.test.tsx", "runs only the exact latest query", "keeps terminal and pending workspaces non-runnable"),
        ),
        "source": (
            ("aearn/services/api/tests/learning/test_lesson_documents.py", "test_missing_prepare_ready_start_refresh_and_explicit_migration", "test_verified_scope_locked_node_cross_user_and_idempotency_conflict"),
            ("aearn/apps/desktop/src/features/learning/tests/LessonDocumentDrawer.test.tsx", "loads the exact document, scrolls only its own panel", "aborts an in-flight retry before retargeting"),
        ),
        "branch_recovery": (
            ("aearn/services/api/tests/tutor/test_tutor_branch_continuation.py", "test_reconnect_snapshot_recovers_active_then_resolved_branch_membership", "test_branch_schema_bootstrap_twice_and_cross_scope_rejection"),
            ("aearn/apps/desktop/src/features/tutor/tests/TutorConversationSurface.test.tsx", "anchors a depth-one branch to its exact Artifact", "does not collapse a terminal Artifact for a learner message that predates completion"),
        ),
        "item_bank": (
            ("aearn/services/api/tests/learning/test_learning_item_bank_review.py", "test_orchestrator_uses_six_blind_independent_reviewer_ports", "test_creator_and_reviewer_independence_is_fail_closed"),
            ("aearn/services/api/tests/learning/test_learning_item_bank_compiler.py", "test_curated_catalog_compiles_all_minimum_kinds_deterministically", "test_negative_sources_produce_safe_pure_receipts"),
        ),
    }
    for family, cases in evidence.items():
        for relative, happy_path, bad_path in cases:
            path = _REPOSITORY_ROOT / relative
            assert path.is_file(), f"{family} evidence missing: {relative}"
            source = path.read_text(encoding="utf-8")
            assert happy_path in source, f"{family} happy-path evidence missing: {relative}::{happy_path}"
            assert bad_path in source, f"{family} bad-path evidence missing: {relative}::{bad_path}"


def test_source_of_truth_documents_cover_platform_and_non_claims() -> None:
    docs = {
        "docs/README.md": (
            "## 2026-09-16 Artifact platform current contract",
            _CURRENT_TEACHING_SKILL,
            "not a release approval",
        ),
        "docs/architecture/tutor-harness-runtime.md": (
            "## 2026-09-16：Artifact platform current contract",
            _CURRENT_TEACHING_SKILL,
            "TUTOR_LEARNING_ARTIFACTS_ENABLED",
        ),
        "docs/architecture/api-contract.md": (
            "## 2026-09-16：Learning Artifact current contract reconciliation",
            "lesson_document_reference_v1",
        ),
        "docs/architecture/database-schema.md": (
            "## 2026-09-16：Learning Artifact current schema reconciliation",
            f"{len(SCHEMA_FRAGMENT_NAMES)} fragments",
            "230_artifact_authority_supersession.sql",
            "240_deepseek_flash_runtime_cutover.sql",
        ),
        "docs/setup/development-environment.md": (
            "## 2026-09-02：Learning Artifact platform final local verification",
            "not executed",
        ),
        "docs/qa/acceptance-test-plan.md": (
            "## 2026-09-16 Artifact platform current verification matrix",
            "Parent AC1-AC20 evidence map",
        ),
        "docs/qa/tutor-harness-release-readiness.md": (
            "## 2026-09-02：Tutor Conversation Learning Artifact platform Child12 integration gate",
            "Pre-check evidence is 98 serial API/PostgreSQL tests",
            "remain not executed",
        ),
    }
    for relative, required in docs.items():
        text = (_REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        # Dated historical command ledgers remain historical; current contract
        # markers must occur in their own section, never pass via old text.
        _assert_document_section(text, required[0], required[1:])

    assert TUTOR_CONVERSATION_EVENT_PROJECTION_VERSION == "tutor_conversation_event_v3"
    assert TUTOR_CONVERSATION_READABLE_SNAPSHOT_VERSIONS == {
        "tutor_conversation_snapshot_v3",
        "tutor_conversation_snapshot_v4",
        "tutor_conversation_snapshot_v5",
    }
