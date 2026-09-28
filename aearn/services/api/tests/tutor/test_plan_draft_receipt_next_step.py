"""The verified draft receipt gives a model-visible next step without forcing it."""
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime

from app.agents.harness.actions import (
    MAX_ACTION_SAFE_SUMMARY_LENGTH,
    ActionAuthorityKind,
    ActionAuthorityReference,
    ActionLifecycleStatus,
    ActionReceipt,
    ActionRecoveryDirective,
    ActionRecoveryKind,
    ActionVerificationStatus,
    is_verified_plan_draft_receipt,
)
from app.agents.harness.contracts import (
    TutorContextInput,
    TutorContextSource,
    TutorPolicySnapshot,
    TutorRunSnapshot,
)
from app.services.tutor.interactive import _PlanDraftCompletionContextLoader


def test_only_verified_plan_receipt_context_directs_completion_without_mutating_receipt() -> None:
    receipt = ActionReceipt(
        invocation_id="invocation-1", action_id="learning.plan.draft", action_version="1.0.0",
        stable_action_key="draft-key", status=ActionLifecycleStatus.VERIFIED,
        input_revision=1, action_generation=1, retry_index=0,
        authority=ActionAuthorityReference(ActionAuthorityKind.PLAN_DRAFT, "draft-id", "a" * 64),
        safe_summary="Learning plan draft authority verified.", result_hash="b" * 64,
        verification_status=ActionVerificationStatus.VERIFIED, verification_hash="c" * 64,
        diagnostic_code=None, recovery=ActionRecoveryDirective(ActionRecoveryKind.NONE, "verified"),
        terminal_at=datetime(2026, 9, 28, tzinfo=UTC),
    )
    original = receipt.as_safe_dict()
    original_hash = receipt.receipt_hash
    content = receipt.as_context_source().content
    assert isinstance(content, Mapping)
    summary = content["safe_summary"]
    assert isinstance(summary, str)
    assert summary == (
        "Draft persisted and verified. Do not call learning.plan.draft again this run. "
        "Reply, then turn_completed. A new revision requires new learner input."
    )
    assert len(summary) <= MAX_ACTION_SAFE_SUMMARY_LENGTH
    assert content["status"] == "verified"
    assert receipt.as_safe_dict() == original
    assert receipt.receipt_hash == original_hash
    unverified = replace(
        receipt, status=ActionLifecycleStatus.SUCCEEDED_UNVERIFIED,
        verification_status=ActionVerificationStatus.PENDING, terminal_at=None,
    )
    unverified_content = unverified.as_context_source().content
    assert isinstance(unverified_content, Mapping)
    assert unverified_content["safe_summary"] == receipt.safe_summary
    other_action = replace(receipt, action_id="grounding.retrieve")
    other_content = other_action.as_context_source().content
    assert isinstance(other_content, Mapping)
    assert other_content["safe_summary"] == receipt.safe_summary
    assert is_verified_plan_draft_receipt(content)
    assert not is_verified_plan_draft_receipt(unverified_content)


def test_verified_plan_receipt_removes_only_consumed_capability_affordance() -> None:
    receipt = TutorContextSource("action-receipt:plan", {
        "kind": "executed_action_receipt",
        "action_id": "learning.plan.draft",
        "status": "verified",
        "verification_status": "verified",
        "authority_kind": "plan_draft",
        "authority_id": "draft-id",
        "input_revision": 0,
    })
    context = TutorContextInput(
        run_id="run-plan", conversation_id="conversation-plan", input_revision=0,
        current_input_required=False,
        system_descriptors=(TutorContextSource("catalog:selected:tutor.learning-plan-draft@1.0.3", "selected"),),
        action_receipts=(receipt,),
        capability_schemas=(
            TutorContextSource("catalog:capability:learning.plan.draft@1.0.0", {"name": "learning.plan.draft"}),
            TutorContextSource("catalog:capability:grounding.retrieve@1.0.0", {"name": "grounding.retrieve"}),
        ),
    )

    class Loader:
        def __init__(self, value: TutorContextInput) -> None:
            self._value = value

        def load_context(self, snapshot: TutorRunSnapshot, *, input_revision: int) -> TutorContextInput:
            del snapshot, input_revision
            return self._value

    run = TutorRunSnapshot(
        run_id="run-plan", conversation_id="conversation-plan", user_id="user-plan",
        origin="interactive", input_revision=0,
        policy=TutorPolicySnapshot(deadline=datetime(2030, 1, 1, tzinfo=UTC)),
    )
    closed = _PlanDraftCompletionContextLoader(base_loader=Loader(context)).load_context(
        run, input_revision=0,
    )

    assert closed.action_receipts == (receipt,)
    assert closed.system_descriptors == context.system_descriptors
    assert len(closed.capability_schemas) == 1
    remaining_schema = closed.capability_schemas[0].content
    assert isinstance(remaining_schema, Mapping)
    assert remaining_schema["name"] == "grounding.retrieve"

    stale_context = replace(context, input_revision=1)
    stale_run = replace(run, input_revision=1)
    still_open = _PlanDraftCompletionContextLoader(
        base_loader=Loader(stale_context),
    ).load_context(stale_run, input_revision=1)
    assert still_open.capability_schemas == stale_context.capability_schemas
