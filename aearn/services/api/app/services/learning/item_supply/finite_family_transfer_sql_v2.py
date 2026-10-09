"""Unregistered SQL V2 twelve-direction plans; never execution/review witnesses.

The only transfer is identity on the ENTIRE source query and all five typed
columns and public parameters. No parser, rewriting, provider or runtime IO.
"""
from __future__ import annotations

from itertools import combinations
from typing import Literal

from pydantic import Field, TypeAdapter, model_validator

from aearn_shared.execution import ExecutionAction, SafeTableResultPresentationV1, SandboxInputV1
from app.services.learning.item_bank.contracts import canonical_hash, canonical_json
from app.services.learning.item_supply.contracts import Digest
from app.services.learning.item_supply.finite_targets.sqlite_predicates_v2 import (
    SQLITE_RUNTIME_PROFILE_V2,
    SQLITE_TASK_KINDS_V2,
    SqliteFamilyIdV2,
    SqlitePublicTaskV2,
    sqlite_fixture_hash_v2,
    sqlite_oracle_v2,
    sqlite_private_fixture_v2,
    sqlite_public_task_hash_v2,
    sqlite_target_hash_v2,
)
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model
from app.services.learning.practice.policies import GATE_PASS_POLICY_VERSION

_IDENTITY_SYMBOLS = tuple((name, name) for name in ("entries", "id", "name", "flag_a", "flag_b", "score"))
_DIGEST_ADAPTER: TypeAdapter[Digest] = TypeAdapter(Digest)


class SqliteTransferCheckV2(StorageContract):
    """Private, schedulable expected facts; no issued terminal/seal/receipt."""

    schema_version: Literal["sqlite_transfer_check_v2"] = "sqlite_transfer_check_v2"
    purpose: Literal["reference_success", "transfer_semantic_mismatch"]
    family_id: SqliteFamilyIdV2
    target_hash: Digest
    public_task: SqlitePublicTaskV2
    public_task_hash: Digest
    fixture_hash: Digest
    submission: str = Field(min_length=1, max_length=2000, repr=False)
    request: SandboxInputV1 = Field(repr=False)
    runtime_lock_hash: Digest
    scorer_version: str = GATE_PASS_POLICY_VERSION
    target_expected: SafeTableResultPresentationV1 = Field(repr=False)
    predicted_output: SafeTableResultPresentationV1 = Field(repr=False)
    # Completeness belongs to execution-case metadata, not the existing strict
    # learner presentation DTO (which deliberately has no truncated field).
    target_expected_truncated: Literal[False] = False
    predicted_output_truncated: Literal[False] = False
    required_scorer_result: Literal["pass", "reject"]
    required_terminal: Literal["successful_read_only_select"] = "successful_read_only_select"
    execution_status: Literal["not_performed"] = "not_performed"

    @model_validator(mode="after")
    def truthful_shape(self) -> SqliteTransferCheckV2:
        if (self.scorer_version != GATE_PASS_POLICY_VERSION
                or self.runtime_lock_hash == "0" * 64 or self.request.runtime_id != SQLITE_RUNTIME_PROFILE_V2
                or self.request.action != ExecutionAction.TEST or self.request.submission != self.submission):
            raise ValueError("sqlite_v2_transfer_runtime_binding")
        matches = self.predicted_output == self.target_expected
        if (self.required_scorer_result == "pass") != matches or (self.purpose == "reference_success") != matches:
            raise ValueError("sqlite_v2_transfer_scorer_prediction")
        return self


class SqliteTransferDirectionV2(StorageContract):
    source_reference: SqliteTransferCheckV2 = Field(repr=False)
    target_reference: SqliteTransferCheckV2 = Field(repr=False)
    transfer_check: SqliteTransferCheckV2 = Field(repr=False)
    identity_symbol_pairs: tuple[tuple[str, str], ...] = Field(min_length=6, max_length=6)
    identity_parameter_pairs: tuple[tuple[str, str, int, int], ...] = Field(min_length=3, max_length=3)
    unchanged_query_hash: Digest
    reasoning_steps: Literal["no_steps_added_removed_or_reordered"] = "no_steps_added_removed_or_reordered"
    construction: Literal["planned"] = "planned"
    execution_status: Literal["not_performed"] = "not_performed"
    review_status: Literal["four_role_reviews_pending"] = "four_role_reviews_pending"
    authority: Literal["not_family_pair_evidence"] = "not_family_pair_evidence"

    @model_validator(mode="after")
    def full_identity_transfer(self) -> SqliteTransferDirectionV2:
        source, target, transfer = self.source_reference, self.target_reference, self.transfer_check
        parameters = source.public_task.target
        expected_parameters = tuple((name, name, value, value) for name, value in (
            ("min_score", parameters.min_score), ("cut_score", parameters.cut_score), ("cut_id", parameters.cut_id)))
        if (source.family_id == target.family_id or transfer.family_id != target.family_id
                or source.purpose != "reference_success" or target.purpose != "reference_success"
                or transfer.purpose != "transfer_semantic_mismatch"
                or source.public_task.target.seed != target.public_task.target.seed
                or transfer.public_task != target.public_task
                or source.public_task.content.tables != target.public_task.content.tables
                or source.public_task.content.public_dataset != target.public_task.content.public_dataset
                or self.identity_symbol_pairs != _IDENTITY_SYMBOLS
                or self.identity_parameter_pairs != expected_parameters
                or transfer.submission != source.submission
                or self.unchanged_query_hash != canonical_hash(source.submission)
                or transfer.predicted_output != source.target_expected
                or transfer.target_expected != target.target_expected
                or not transfer.predicted_output.rows or not transfer.target_expected.rows):
            raise ValueError("sqlite_v2_transfer_not_full_query_identity")
        return self


class SqliteFamilyPairPlanV2(StorageContract):
    forward: SqliteTransferDirectionV2
    backward: SqliteTransferDirectionV2
    construction: Literal["planned"] = "planned"
    review_status: Literal["four_role_reviews_pending"] = "four_role_reviews_pending"

    @model_validator(mode="after")
    def two_directions(self) -> SqliteFamilyPairPlanV2:
        if (self.forward.source_reference != self.backward.target_reference
                or self.forward.target_reference != self.backward.source_reference):
            raise ValueError("sqlite_v2_pair_direction_binding")
        return self


class SqliteFamilyTransferPlanV2(StorageContract):
    schema_version: Literal["sqlite_family_transfer_plan_v2"] = "sqlite_family_transfer_plan_v2"
    target_id: Literal["sqlite-predicate-order-v2"] = "sqlite-predicate-order-v2"
    public_spec_version: Literal["finite-sql-common-spec-v1"] = "finite-sql-common-spec-v1"
    seed: int = Field(ge=0, le=255)
    tasks: tuple[SqlitePublicTaskV2, ...] = Field(min_length=4, max_length=4)
    runtime_lock_hash: Digest
    pairs: tuple[SqliteFamilyPairPlanV2, ...] = Field(min_length=6, max_length=6, repr=False)
    construction: Literal["planned"] = "planned"
    execution_status: Literal["not_performed"] = "not_performed"
    review_status: Literal["four_role_reviews_pending"] = "four_role_reviews_pending"
    authority: Literal["not_family_pair_evidence"] = "not_family_pair_evidence"
    publication_enabled: Literal[False] = False


def _check(public: SqlitePublicTaskV2, lock: str, *, source: SqlitePublicTaskV2 | None = None) -> SqliteTransferCheckV2:
    fixture = sqlite_private_fixture_v2(public.target)
    public_hash, fixture_hash = sqlite_public_task_hash_v2(public), sqlite_fixture_hash_v2(fixture)
    dataset = public.content.public_dataset
    truth = sqlite_oracle_v2(public.target, dataset)
    program = fixture.equivalent_queries[0] if source is None else sqlite_private_fixture_v2(source.target).equivalent_queries[0]
    predicted = truth if source is None else sqlite_oracle_v2(source.target, dataset)
    cases = ({"id": "sql-v2-common-fifteen", "case_type": "hidden",
              "tables": [table.model_dump(mode="json") for table in public.content.tables],
              "dataset": dataset.model_dump(mode="json"), "max_rows": public.content.max_rows},)
    request = SandboxInputV1(runtime_id=SQLITE_RUNTIME_PROFILE_V2, action=ExecutionAction.TEST, submission=program,
        hidden_test_bundle_json=canonical_json(cases), test_reference_hash=canonical_hash(cases),
        source_reference_hash=canonical_hash({"registered_reference_fixture": fixture_hash, "public_task": public_hash}))
    if len(request.wire_bytes()) > 98_304:
        raise ValueError("sqlite_v2_transfer_wire_bound")
    return SqliteTransferCheckV2(purpose="reference_success" if source is None else "transfer_semantic_mismatch",
        family_id=fixture.family_id, target_hash=sqlite_target_hash_v2(public.target), public_task=public,
        public_task_hash=public_hash, fixture_hash=fixture_hash, submission=program, request=request,
        runtime_lock_hash=lock, scorer_version=GATE_PASS_POLICY_VERSION, target_expected=truth,
        predicted_output=predicted, required_scorer_result="pass" if source is None else "reject")


def _direction(source: SqliteTransferCheckV2, target: SqliteTransferCheckV2, lock: str) -> SqliteTransferDirectionV2:
    parameters = source.public_task.target
    return SqliteTransferDirectionV2(source_reference=source, target_reference=target,
        transfer_check=_check(target.public_task, lock, source=source.public_task),
        identity_symbol_pairs=_IDENTITY_SYMBOLS,
        identity_parameter_pairs=tuple((name, name, value, value) for name, value in (
            ("min_score", parameters.min_score), ("cut_score", parameters.cut_score), ("cut_id", parameters.cut_id))),
        unchanged_query_hash=canonical_hash(source.submission))


def build_sqlite_family_transfer_plan_v2(tasks: tuple[SqlitePublicTaskV2, ...], *, runtime_lock_hash: str) -> SqliteFamilyTransferPlanV2:
    """Exact four unguided tasks with ONE seed, not fallback/search for negatives.

    A supplied lock digest is only a later execution pin, NOT a current-health or
    runtime attestation. Consumers remain disabled until integrated/verified.
    """
    lock = _DIGEST_ADAPTER.validate_python(runtime_lock_hash, strict=True)
    if lock == "0" * 64 or type(tasks) is not tuple or len(tasks) != 4:
        raise ValueError("sqlite_v2_four_tasks_and_nonzero_lock_required")
    checked = tuple(checked_model(task, SqlitePublicTaskV2) for task in tasks)
    if (len({task.target.task_kind for task in checked}) != 4 or len({task.target.seed for task in checked}) != 1
            or any(task.guided or task.purpose != "exercise" for task in checked)):
        raise ValueError("sqlite_v2_four_unguided_tasks_same_seed_required")
    for task in checked:
        sqlite_public_task_hash_v2(task)  # Exact rebuild, including all nested public fields.
    by_kind = {task.target.task_kind: task for task in checked}
    ordered = tuple(by_kind[kind] for kind in SQLITE_TASK_KINDS_V2)
    references = tuple(_check(task, lock) for task in ordered)
    pairs = tuple(SqliteFamilyPairPlanV2(forward=_direction(left, right, lock), backward=_direction(right, left, lock))
                  for left, right in combinations(references, 2))
    return SqliteFamilyTransferPlanV2(seed=ordered[0].target.seed, tasks=ordered, runtime_lock_hash=lock, pairs=pairs)


def sqlite_family_transfer_plan_hash_v2(plan: SqliteFamilyTransferPlanV2) -> str:
    plan = checked_model(plan, SqliteFamilyTransferPlanV2)
    if plan != build_sqlite_family_transfer_plan_v2(plan.tasks, runtime_lock_hash=plan.runtime_lock_hash):
        raise ValueError("sqlite_v2_transfer_plan_not_exact")
    return canonical_hash(plan.model_dump(mode="json"))
