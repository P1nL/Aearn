from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.agents.harness.actions import (
    ActionAuthorityKind,
    ActionAuthorityReference,
    ActionDescriptor,
    ActionExecutionResult,
    ActionExecutionStatus,
    ActionFenceSnapshot,
    ActionLifecycleStatus,
    ActionNetworkClass,
    ActionRecoveryKind,
    ActionResourceProfile,
    ActionResourceRequest,
    ActionRetryClass,
    ActionRetryPolicy,
    ActionSideEffectClass,
    ActionVerificationStatus,
    build_action_invocation,
    default_action_descriptors,
)
from app.agents.harness.contracts import (
    TutorCapabilityRequest,
    TutorCapabilityResult,
    TutorCapabilityStatus,
    TutorLease,
    TutorPayloadField,
    TutorPolicySnapshot,
    TutorRunSnapshot,
    payload_fields_from_mapping,
)
from app.services.grounding.grounding_processing import GroundingChunk
from app.services.repositories.local_user_data_repository import export_user_data, reset_user_data
from app.services.tutor.capability_gateway import CatalogCapabilityGateway
from app.services.tutor.capability_policy import CapabilityPolicyContext, InMemoryCapabilityPolicyResolver
from app.services.tutor.grounding_lookup import InMemoryGroundingLookup
from app.services.tutor.persistence import PostgresTutorSkillSelectionStore
from app.services.tutor.ports import FixedClock
from app.services.tutor.safe_projection import TutorSafeProjection
from app.services.tutor.skill_selection import TutorSkillSelection
from conftest import TutorPersistenceFixture
from app.services.tutor.action_adapters import (
    ControlledCapabilityGateway,
    ExistingExecutionJobActionAdapter,
    ExistingExecutionJobEvidence,
    _capability_output,
    PostgresGroundingActionVerifier,
)
from app.services.tutor.action_persistence import PostgresActionFence, PostgresActionReceiptStore
from app.services.tutor.action_runtime import (
    ActionRuntimeBudget,
    ActionRuntimeError,
    CallableActionAdapter,
    ControlledActionRuntime,
    InMemoryActionFence,
    InMemoryActionReceiptStore,
    SchemaActionVerifier,
)


NOW = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)


def _run() -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="action-run",
        conversation_id="action-conversation",
        user_id="action-user",
        origin="interactive",
        input_revision=3,
        policy=TutorPolicySnapshot(deadline=datetime(2030, 1, 1, tzinfo=UTC)),
        lease=TutorLease(
            run_id="action-run",
            owner_id="action-worker",
            generation=2,
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        ),
    )


def _grounding_descriptor() -> ActionDescriptor:
    return next(item for item in default_action_descriptors() if item.action_id == "grounding.retrieve")


def _invocation(
    *,
    invocation_id: str = "invocation-1",
    idempotency_key: str = "action-key-1",
    query_text: str = "function return values",
):
    descriptor = _grounding_descriptor()
    return build_action_invocation(
        descriptor=descriptor,
        run=_run(),
        invocation_id=invocation_id,
        idempotency_key=idempotency_key,
        arguments={
            "language_id_or_alias": "python",
            "query_text": query_text,
            "topic_tags": ["functions"],
            "top_k": 1,
        },
        resource_request=ActionResourceRequest(
            source_ids=("python-tutorial",),
            network_class=ActionNetworkClass.APPROVED_REGISTRY,
            input_bytes=200,
            expected_output_bytes=1000,
            cost_units=1,
        ),
        task_kind="plan_drafting",
        catalog_digest="a" * 64,
        policy_fingerprint="b" * 64,
        selected_skill_reference="tutor.registry-grounding@1.0.0",
        action_generation=1,
        requested_at=NOW,
    )


def _success_adapter(invocation):
    return ActionExecutionResult(
        status=ActionExecutionStatus.SUCCEEDED,
        authority=ActionAuthorityReference(
            ActionAuthorityKind.GROUNDING_RESULT,
            f"grounding:{invocation.invocation_id}",
            "c" * 64,
        ),
        output={"status": "completed", "source_ids": [], "citation_ids": [], "content_hashes": []},
        safe_summary="Approved grounding lookup completed.",
    )


def _runtime(*, adapter=None, fence=None, store=None, budget=None) -> ControlledActionRuntime:
    descriptor = _grounding_descriptor()
    return ControlledActionRuntime(
        descriptors=(descriptor,),
        adapters={descriptor.owner_adapter_id: adapter or CallableActionAdapter(_success_adapter)},
        verifiers={descriptor.verifier_id: SchemaActionVerifier()},
        fence=fence or InMemoryActionFence(),
        store=store or InMemoryActionReceiptStore(),
        clock=lambda: NOW,
        approved_source_ids=("python-tutorial",),
        budget=budget,
    )


def test_plan_capability_safe_result_preserves_raw_authority_fields() -> None:
    descriptor = next(
        item for item in default_action_descriptors() if item.action_id == "learning.plan.draft"
    )
    result = TutorCapabilityResult(
        request_id="plan-result",
        status=TutorCapabilityStatus.COMPLETED,
        safe_result=(
            TutorPayloadField("draft_id", "53e9d886-ad02-44f7-b466-ca3efa9961a0"),
            TutorPayloadField("draft_version", "2"),
            TutorPayloadField("content_hash", "a" * 64),
            TutorPayloadField("quality_status", "passed"),
        ),
    )

    assert _capability_output(descriptor, result) == {
        "status": "completed",
        "draft_id": "53e9d886-ad02-44f7-b466-ca3efa9961a0",
        "draft_version": 2,
        "content_hash": "a" * 64,
        "quality_status": "passed",
    }


def test_action_descriptors_are_stable_and_cover_first_migration_set() -> None:
    descriptors = default_action_descriptors()

    assert [item.action_id for item in descriptors] == [
        "grounding.retrieve",
        "learning.plan.draft",
        "runner.execute",
        "model-code-review.validate",
    ]
    assert all(len(item.contract_hash) == 64 for item in descriptors)
    assert descriptors[0].contract_hash == default_action_descriptors()[0].contract_hash
    assert descriptors[2].side_effect_class is ActionSideEffectClass.EXTERNAL_EXECUTION
    assert descriptors[3].allowed_origins == ("proactive",)
    assert descriptors[3].allowed_task_kinds == ("model_code_review",)


def test_controlled_runtime_verifies_and_deduplicates_current_action() -> None:
    store = InMemoryActionReceiptStore()
    adapter = CallableActionAdapter(_success_adapter)
    runtime = _runtime(adapter=adapter, store=store)

    first = runtime.execute(_invocation())
    second = runtime.execute(_invocation(invocation_id="invocation-2", idempotency_key="action-key-2"))

    assert first.receipt.status is ActionLifecycleStatus.VERIFIED
    assert first.receipt.verification_status is ActionVerificationStatus.VERIFIED
    assert first.receipt.authority is not None
    assert first.receipt.as_context_source().content["verification_status"] == "verified"
    assert second.deduplicated is True
    assert second.receipt.receipt_hash == first.receipt.receipt_hash
    assert len(adapter.calls) == 1


def test_action_idempotency_conflicts_across_input_revisions() -> None:
    store = InMemoryActionReceiptStore()
    runtime = _runtime(store=store)
    invocation = _invocation()
    runtime.execute(invocation)

    with pytest.raises(ActionRuntimeError):
        runtime.execute(
            replace(
                invocation,
                invocation_id="invocation-revision-4",
                input_revision=4,
            )
        )


def test_controlled_runtime_fences_stale_result_after_adapter_execution() -> None:
    fence = InMemoryActionFence(
        [
            ActionFenceSnapshot(input_revision=3, lease_generation=2),
            ActionFenceSnapshot(input_revision=4, lease_generation=2),
        ]
    )
    adapter = CallableActionAdapter(_success_adapter)

    outcome = _runtime(adapter=adapter, fence=fence).execute(_invocation())

    assert outcome.receipt.status is ActionLifecycleStatus.SUPERSEDED
    assert outcome.receipt.diagnostic_code == "action_superseded"
    assert outcome.receipt.recovery.kind is ActionRecoveryKind.REBUILD_CONTEXT
    assert outcome.adapter_invoked is True
    assert len(adapter.calls) == 1


def test_controlled_runtime_classifies_retryable_failure_with_bounded_recovery() -> None:
    adapter = CallableActionAdapter(
        lambda _invocation: ActionExecutionResult(
            status=ActionExecutionStatus.RETRYABLE_FAILED,
            safe_summary="Grounding service is temporarily unavailable.",
            diagnostic_code="grounding_lookup_unavailable",
        )
    )

    outcome = _runtime(adapter=adapter).execute(_invocation())

    assert outcome.receipt.status is ActionLifecycleStatus.RETRYABLE_FAILED
    assert outcome.receipt.recovery.kind is ActionRecoveryKind.RETRY
    assert outcome.receipt.recovery.retry_after_seconds == 1


def test_controlled_runtime_enforces_server_owned_action_and_verification_budgets() -> None:
    store = InMemoryActionReceiptStore()
    runtime = _runtime(
        store=store,
        budget=ActionRuntimeBudget(max_actions=1, max_verifications=1),
    )

    first = runtime.execute(_invocation())
    second = runtime.execute(
        _invocation(
            invocation_id="invocation-2",
            idempotency_key="action-key-2",
            query_text="function parameters",
        )
    )

    assert first.receipt.status is ActionLifecycleStatus.VERIFIED
    assert second.receipt.status is ActionLifecycleStatus.DENIED
    assert second.receipt.diagnostic_code == "action_budget_exhausted"

    verification_limited = _runtime(
        budget=ActionRuntimeBudget(max_actions=1, max_verifications=0),
    ).execute(_invocation(invocation_id="verification-limited", idempotency_key="verification-limited"))

    assert verification_limited.receipt.status is ActionLifecycleStatus.PERMANENT_FAILED
    assert verification_limited.receipt.diagnostic_code == "action_verification_budget_exhausted"
    assert verification_limited.receipt.recovery.kind is ActionRecoveryKind.SAFE_STOP


def test_controlled_runtime_stops_when_recovery_budget_is_exhausted() -> None:
    adapter = CallableActionAdapter(
        lambda _invocation: ActionExecutionResult(
            status=ActionExecutionStatus.RETRYABLE_FAILED,
            safe_summary="Grounding service is temporarily unavailable.",
            diagnostic_code="grounding_lookup_unavailable",
        )
    )

    outcome = _runtime(
        adapter=adapter,
        budget=ActionRuntimeBudget(max_recoveries=0),
    ).execute(_invocation())

    assert outcome.receipt.status is ActionLifecycleStatus.PERMANENT_FAILED
    assert outcome.receipt.recovery.kind is ActionRecoveryKind.SAFE_STOP
    assert outcome.receipt.recovery.code == "action_recovery_budget_exhausted"


def test_controlled_runtime_denies_resource_escalation_before_adapter() -> None:
    descriptor = _grounding_descriptor()
    invocation = build_action_invocation(
        descriptor=descriptor,
        run=_run(),
        invocation_id="resource-escalation",
        idempotency_key="resource-escalation",
        arguments={
            "language_id_or_alias": "python",
            "query_text": "function return values",
            "topic_tags": [],
            "top_k": 1,
        },
        resource_request=ActionResourceRequest(
            source_ids=("unreviewed-source",),
            network_class=ActionNetworkClass.APPROVED_REGISTRY,
            input_bytes=200,
            expected_output_bytes=1000,
            cost_units=1,
        ),
        task_kind="plan_drafting",
        catalog_digest="a" * 64,
        policy_fingerprint="b" * 64,
        selected_skill_reference="tutor.registry-grounding@1.0.0",
        action_generation=1,
        requested_at=NOW,
    )
    adapter = CallableActionAdapter(_success_adapter)

    outcome = _runtime(adapter=adapter).execute(invocation)

    assert outcome.receipt.status is ActionLifecycleStatus.DENIED
    assert outcome.receipt.diagnostic_code == "action_admission_denied"
    assert adapter.calls == []


def test_action_contract_rejects_model_selected_url_or_command() -> None:
    descriptor = _grounding_descriptor()

    with pytest.raises(ValueError):
        build_action_invocation(
            descriptor=descriptor,
            run=_run(),
            invocation_id="unsafe-invocation",
            idempotency_key="unsafe-invocation",
            arguments={
                "language_id_or_alias": "python",
                "query_text": "https://unreviewed.example/docs",
                "topic_tags": [],
                "top_k": 1,
            },
            resource_request=ActionResourceRequest(
                network_class=ActionNetworkClass.APPROVED_REGISTRY,
            ),
            task_kind="plan_drafting",
            catalog_digest="a" * 64,
            policy_fingerprint="b" * 64,
            selected_skill_reference=None,
            action_generation=1,
            requested_at=NOW,
        )


class _ExecutionReader:
    def __init__(self, evidence: ExistingExecutionJobEvidence | None) -> None:
        self.evidence = evidence
        self.calls: list[tuple[str, str]] = []

    def read_action_job(self, *, user_id: str, intent_proof_id: str) -> ExistingExecutionJobEvidence | None:
        self.calls.append((user_id, intent_proof_id))
        return self.evidence


def _runner_invocation(*, invocation_id: str = "runner-action-1"):
    descriptor = next(item for item in default_action_descriptors() if item.action_id == "runner.execute")
    return descriptor, build_action_invocation(
        descriptor=descriptor,
        run=_run(),
        invocation_id=invocation_id,
        idempotency_key=invocation_id,
        arguments={"intent_proof_id": "intent-proof-1"},
        resource_request=ActionResourceRequest(
            network_class=ActionNetworkClass.EXECUTOR_MANAGED,
            temporary_workspace=True,
            input_bytes=128,
            expected_output_bytes=1024,
            cost_units=1,
        ),
        task_kind="exercise_feedback",
        catalog_digest="a" * 64,
        policy_fingerprint="b" * 64,
        selected_skill_reference=None,
        action_generation=1,
        requested_at=NOW,
    )


def test_runner_action_reads_existing_durable_job_without_launching_execution() -> None:
    descriptor, invocation = _runner_invocation()
    reader = _ExecutionReader(
        ExistingExecutionJobEvidence(
            job_id="execution-job-1",
            state="completed",
            evidence_hash="e" * 64,
        )
    )
    runtime = ControlledActionRuntime(
        descriptors=(descriptor,),
        adapters={descriptor.owner_adapter_id: ExistingExecutionJobActionAdapter(reader)},
        verifiers={descriptor.verifier_id: SchemaActionVerifier()},
        fence=InMemoryActionFence(),
        store=InMemoryActionReceiptStore(),
        clock=lambda: NOW,
    )

    outcome = runtime.execute(invocation)

    assert outcome.receipt.status is ActionLifecycleStatus.VERIFIED
    assert outcome.receipt.authority is not None
    assert outcome.receipt.authority.kind is ActionAuthorityKind.EXECUTION_JOB
    assert reader.calls == [(invocation.user_id, "intent-proof-1")]


def test_runner_action_keeps_nonterminal_job_retryable() -> None:
    descriptor, invocation = _runner_invocation(invocation_id="runner-action-pending")
    reader = _ExecutionReader(
        ExistingExecutionJobEvidence(
            job_id="execution-job-pending",
            state="running",
            evidence_hash="f" * 64,
        )
    )
    runtime = ControlledActionRuntime(
        descriptors=(descriptor,),
        adapters={descriptor.owner_adapter_id: ExistingExecutionJobActionAdapter(reader)},
        verifiers={descriptor.verifier_id: SchemaActionVerifier()},
        fence=InMemoryActionFence(),
        store=InMemoryActionReceiptStore(),
        clock=lambda: NOW,
    )

    outcome = runtime.execute(invocation)

    assert outcome.receipt.status is ActionLifecycleStatus.RETRYABLE_FAILED
    assert outcome.receipt.recovery.kind is ActionRecoveryKind.RETRY


class _ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact_id: str = Field(min_length=1, max_length=80)


class _ReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str


def test_new_review_adapter_registers_without_changing_runtime_state_machine() -> None:
    descriptor = ActionDescriptor(
        action_id="model-code-review.validate",
        version="1.0.0",
        input_model=_ReviewInput,
        output_model=_ReviewOutput,
        owner_adapter_id="review-validator",
        owner_adapter_version="1.0.0",
        allowed_origins=("interactive",),
        allowed_task_kinds=("model_code_review",),
        resource_profile=ActionResourceProfile(
            profile_id="review-validator-v1",
            allowed_artifact_kinds=("review_candidate",),
        ),
        timeout_seconds=30,
        side_effect_class=ActionSideEffectClass.READ_ONLY,
        retry_policy=ActionRetryPolicy(retry_class=ActionRetryClass.NEVER),
        verifier_id="review-contract-verifier",
        verifier_version="1.0.0",
        recovery_kinds=(ActionRecoveryKind.SAFE_STOP,),
    )
    invocation = build_action_invocation(
        descriptor=descriptor,
        run=_run(),
        invocation_id="review-invocation",
        idempotency_key="review-invocation",
        arguments={"artifact_id": "candidate-1"},
        resource_request=ActionResourceRequest(
            artifact_ids=("candidate-1",),
            artifact_kinds=("review_candidate",),
        ),
        task_kind="model_code_review",
        catalog_digest="a" * 64,
        policy_fingerprint="b" * 64,
        selected_skill_reference=None,
        action_generation=1,
        requested_at=NOW,
    )
    adapter = CallableActionAdapter(
        lambda _invocation: ActionExecutionResult(
            status=ActionExecutionStatus.SUCCEEDED,
            authority=ActionAuthorityReference(
                ActionAuthorityKind.GROUNDING_RESULT,
                "review-candidate-1",
                "d" * 64,
            ),
            output={"status": "completed"},
            safe_summary="Review candidate passed pre-publication validation.",
        )
    )
    runtime = ControlledActionRuntime(
        descriptors=(descriptor,),
        adapters={descriptor.owner_adapter_id: adapter},
        verifiers={descriptor.verifier_id: SchemaActionVerifier()},
        fence=InMemoryActionFence(),
        store=InMemoryActionReceiptStore(),
        clock=lambda: NOW,
        approved_artifact_ids=("candidate-1",),
    )

    outcome = runtime.execute(invocation)

    assert outcome.receipt.status is ActionLifecycleStatus.VERIFIED
    assert len(adapter.calls) == 1


def test_action_safe_projection_is_lossless_for_safe_metadata_and_omits_raw_values() -> None:
    receipt = _runtime().execute(_invocation()).receipt

    projected = TutorSafeProjection().project(
        {
            **receipt.as_safe_dict(),
            "provider_payload": {"raw": "secret"},
            "safe_summary": r"cmd.exe /c type C:\\private\\answer.txt",
        }
    )

    assert projected["action_id"] == "grounding.retrieve"
    assert projected["action_generation"] == 1
    assert projected["authority_hash"] == "c" * 64
    assert projected["verification_status"] == "verified"
    assert "provider_payload" not in projected
    assert "safe_summary" not in projected


def test_controlled_runtime_records_cancel_request_before_cancelled_terminal() -> None:
    store = InMemoryActionReceiptStore()
    fence = InMemoryActionFence(
        [ActionFenceSnapshot(input_revision=3, lease_generation=2, cancelled=True)]
    )

    outcome = _runtime(store=store, fence=fence).execute(_invocation())

    assert outcome.receipt.status is ActionLifecycleStatus.CANCELLED
    assert store.transitions == [
        ("invocation-1", ActionLifecycleStatus.REQUESTED, ActionLifecycleStatus.ADMITTED),
        ("invocation-1", ActionLifecycleStatus.ADMITTED, ActionLifecycleStatus.CANCEL_REQUESTED),
        ("invocation-1", ActionLifecycleStatus.CANCEL_REQUESTED, ActionLifecycleStatus.CANCELLED),
    ]


def _postgres_invocation(fixture: TutorPersistenceFixture):
    now = datetime.now(UTC)
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="action-runtime-test",
        now=now,
        duration_seconds=120,
    )
    assert lease is not None
    run = fixture.repository.load_snapshot(user_id=fixture.user_id, run_id=fixture.run.run_id)
    assert run is not None and run.lease is not None
    policy = fixture.connection.execute(
        "SELECT policy_fingerprint FROM tutor_runs WHERE id = %s",
        (run.run_id,),
    ).fetchone()
    assert policy is not None
    descriptor = _grounding_descriptor()
    return build_action_invocation(
        descriptor=descriptor,
        run=run,
        invocation_id="postgres-action-1",
        idempotency_key="postgres-action-1",
        arguments={
            "language_id_or_alias": "python",
            "query_text": "function return values",
            "topic_tags": ["functions"],
            "top_k": 1,
        },
        resource_request=ActionResourceRequest(
            source_ids=("python-tutorial",),
            network_class=ActionNetworkClass.APPROVED_REGISTRY,
            input_bytes=200,
            expected_output_bytes=1000,
            cost_units=1,
        ),
        task_kind="plan_drafting",
        catalog_digest=fixture.catalog.digest,
        policy_fingerprint=str(policy["policy_fingerprint"]),
        selected_skill_reference="tutor.registry-grounding@1.0.0",
        action_generation=1,
        requested_at=now,
    )


def test_postgres_action_receipt_replays_projects_exports_and_resets(
    tutor_persistence: TutorPersistenceFixture,
) -> None:
    fixture = tutor_persistence
    invocation = _postgres_invocation(fixture)
    descriptor = _grounding_descriptor()
    store = PostgresActionReceiptStore(fixture.connection)
    runtime = ControlledActionRuntime(
        descriptors=(descriptor,),
        adapters={descriptor.owner_adapter_id: CallableActionAdapter(_success_adapter)},
        verifiers={descriptor.verifier_id: SchemaActionVerifier()},
        fence=PostgresActionFence(fixture.connection),
        store=store,
        clock=lambda: datetime.now(UTC),
        approved_source_ids=("python-tutorial",),
    )

    first = runtime.execute(invocation)
    replay = runtime.execute(invocation)
    current = fixture.repository.load_snapshot(
        user_id=fixture.user_id, run_id=fixture.run.run_id
    )
    assert current is not None
    dedupe = runtime.execute(
        build_action_invocation(
            descriptor=descriptor,
            run=current,
            invocation_id="postgres-action-2",
            idempotency_key="postgres-action-2",
            arguments=invocation.arguments,
            resource_request=invocation.resource_request,
            task_kind=invocation.task_kind,
            catalog_digest=invocation.catalog_digest,
            policy_fingerprint=invocation.policy_fingerprint,
            selected_skill_reference=invocation.selected_skill_reference,
            action_generation=2,
            requested_at=datetime.now(UTC),
        )
    )

    assert first.receipt.status is ActionLifecycleStatus.VERIFIED
    assert replay.replayed is True
    assert dedupe.deduplicated is True
    persisted = fixture.connection.execute(
        "SELECT receipt_json FROM tutor_action_receipts WHERE invocation_id = %s",
        (invocation.invocation_id,),
    ).fetchone()
    assert persisted is not None
    assert persisted["receipt_json"]["authority_hash"] == "c" * 64
    assert "arguments" not in persisted["receipt_json"]
    assert len(
        store.list_context_receipts(
            user_id=fixture.user_id,
            run_id=fixture.run.run_id,
            input_revision=invocation.input_revision,
        )
    ) == 1
    assert store.list_context_receipts(
        user_id="00000000-0000-0000-0000-000000000000",
        run_id=fixture.run.run_id,
        input_revision=invocation.input_revision,
    ) == ()

    exported = export_user_data(fixture.connection, fixture.user_id)
    assert exported["summary"]["counts"]["action_receipts"] == 1
    assert exported["action_receipt_summaries"][0]["action_id"] == "grounding.retrieve"
    assert "result_hash" not in exported["action_receipt_summaries"][0]

    reset = reset_user_data(fixture.connection, fixture.user_id)
    assert reset["summary"]["counts"]["action_receipts"] == 0
    remaining = fixture.connection.execute(
        "SELECT count(*) AS count FROM tutor_action_invocations WHERE user_id = %s",
        (fixture.user_id,),
    ).fetchone()
    assert remaining is not None and remaining["count"] == 0


def test_controlled_grounding_gateway_persists_one_authority_and_replays(
    tutor_persistence: TutorPersistenceFixture,
) -> None:
    fixture = tutor_persistence
    now = datetime.now(UTC)
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="controlled-grounding-test",
        now=now,
        duration_seconds=120,
    )
    assert lease is not None
    run = fixture.repository.load_snapshot(user_id=fixture.user_id, run_id=fixture.run.run_id)
    assert run is not None and run.lease is not None
    policy_row = fixture.connection.execute(
        "SELECT policy_fingerprint FROM tutor_runs WHERE id = %s",
        (run.run_id,),
    ).fetchone()
    assert policy_row is not None
    skill = next(
        item
        for item in fixture.catalog.skills
        if item.reference.key == "tutor.registry-grounding@1.0.0"
    )
    selection_store = PostgresTutorSkillSelectionStore(
        repository=fixture.repository,
        user_id=fixture.user_id,
    )
    selection_store.record(
        run_id=run.run_id,
        input_revision=run.input_revision,
        selection=TutorSkillSelection(
            reference=skill.reference,
            manifest_hash=skill.manifest_hash,
            instruction_hash=skill.instruction_hash,
        ),
    )
    policy = CapabilityPolicyContext(
        run_id=run.run_id,
        user_id=run.user_id,
        origin=run.origin,
        input_revision=run.input_revision,
        catalog_digest=fixture.catalog.digest,
        eligible_skill_references=(skill.reference,),
        eligible_capability_ids=("grounding.retrieve",),
        granted_policy_tags=("registry-grounding",),
        allowed_origins=("interactive",),
        consent_granted=True,
        runtime_available_capability_ids=("grounding.retrieve",),
        remaining_capability_budget=2,
        allowed_source_ids=("python-tutorial",),
    )
    lookup = InMemoryGroundingLookup(
        (
            GroundingChunk(
                chunk_id="controlled-python-functions",
                source_id="python-tutorial",
                language_id="python",
                title="Functions",
                section_path=("Python Tutorial", "Functions"),
                canonical_url="https://docs.python.org/3/tutorial/controlflow.html#defining-functions",
                source_type="tutorial",
                source_trust_tier="official",
                fetched_at=now,
                content_hash="9" * 64,
                text="A return statement sends a value back to the function caller.",
                topic_tags=("functions",),
                source_version_label="python-3",
                source_version_kind="rolling",
                document_content_hash="8" * 64,
            ),
        )
    )
    resolver = InMemoryCapabilityPolicyResolver((policy,))
    clock = FixedClock(now)
    store = PostgresActionReceiptStore(fixture.connection)
    gateway = ControlledCapabilityGateway(
        catalog=fixture.catalog,
        policy_resolver=resolver,
        selection_store=selection_store,
        authority_gateway=CatalogCapabilityGateway(
            catalog=fixture.catalog,
            policy_resolver=resolver,
            selection_store=selection_store,
            grounding_lookup=lookup,
        ),
        authority_recorder=fixture.repository,
        receipt_store=store,
        fence=PostgresActionFence(fixture.connection),
        clock=clock,
        policy_fingerprint_loader=lambda _run: str(policy_row["policy_fingerprint"]),
        verifier_factory=lambda _descriptor: PostgresGroundingActionVerifier(fixture.connection),
    )
    request = TutorCapabilityRequest(
        request_id="controlled-grounding-1",
        capability_id="grounding.retrieve",
        arguments=payload_fields_from_mapping(
            {
                "language_id_or_alias": "python",
                "query_text": "What does a function return?",
                "topic_tags": ["functions"],
                "top_k": 1,
            }
        ),
    )

    first = gateway.dispatch(run=run, request=request)
    replay = gateway.dispatch(run=run, request=request)

    assert first.status is TutorCapabilityStatus.COMPLETED
    assert first.continue_run is True
    assert replay.status is TutorCapabilityStatus.COMPLETED
    assert replay.diagnostic_code == "action_replayed"
    counts = fixture.connection.execute(
        """
        SELECT
          (SELECT count(*) FROM tutor_capability_invocations WHERE run_id = %s) AS capabilities,
          (SELECT count(*) FROM tutor_action_invocations WHERE run_id = %s) AS actions,
          (SELECT count(*) FROM tutor_action_receipts WHERE run_id = %s AND status = 'verified') AS receipts
        """,
        (run.run_id, run.run_id, run.run_id),
    ).fetchone()
    assert counts is not None
    assert counts["capabilities"] == 1
    assert counts["actions"] == 1
    assert counts["receipts"] == 1
    authority = fixture.connection.execute(
        """
        SELECT receipts.authority_kind, receipts.authority_id, capabilities.id::text AS capability_id
        FROM tutor_action_receipts AS receipts
        JOIN tutor_capability_invocations AS capabilities ON capabilities.id::text = receipts.authority_id
        WHERE receipts.run_id = %s
        """,
        (run.run_id,),
    ).fetchone()
    assert authority is not None
    assert authority["authority_kind"] == "capability_invocation"
    assert authority["authority_id"] == authority["capability_id"]
