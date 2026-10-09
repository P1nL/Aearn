"""P4 deterministic candidate validation, with no implicit host execution.

The legacy SQL/browser validator executes submissions. Only KC uses its full
entrypoint; runtime kinds reuse its pure checks and leave execution pending.
Trusted execution ports are server dependencies, never provider-authored DTOs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.services.learning.item_bank import validation as legacy
from app.services.learning.item_bank.contracts import (
    LearningItemKind, LearningItemKnowledgeCheckContentV1, LearningItemSourceV1,
    LearningItemValidationCheckType, LearningItemValidationReceiptV1, canonical_hash,
)
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.validators.profiles import profile_errors, required_probes


if TYPE_CHECKING:
    from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CandidateProbeV2(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    status: Literal["passed", "failed", "pending"]
    proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")


class CandidateExecutionEvidenceV2(_Strict):
    schema_version: Literal["candidate_execution_v2"] = "candidate_execution_v2"
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["code", "sql"]
    language: Literal["python", "sql"]
    runtime_profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    dialect: Literal["sqlite"] | None = None
    runner_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    scorer_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    run_id: UUID
    origin: Literal["deterministic_probe"] = "deterministic_probe"
    mode: Literal["live", "synthetic"]
    isolation: Literal["approved_os_boundary", "host", "synthetic"]
    probes: tuple[CandidateProbeV2, ...] = Field(min_length=1, max_length=32)


class CandidateCheckV2(_Strict):
    check_type: LearningItemValidationCheckType
    status: Literal["passed", "failed", "not_applicable", "pending"]
    safe_code: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidateValidationV2(_Strict):
    schema_version: Literal["candidate_validation_v2"] = "candidate_validation_v2"
    state: Literal["machine_verified", "blocked", "rejected"]
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    legacy_receipt: LearningItemValidationReceiptV1 | None = None
    checks: tuple[CandidateCheckV2, ...] = Field(min_length=11, max_length=11)
    execution_evidence: CandidateExecutionEvidenceV2 | None = None
    safe_reasons: tuple[str, ...] = ()
    origin: Literal["deterministic_probe"] = "deterministic_probe"
    mode: Literal["static", "live", "synthetic"] = "static"

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> "CandidateValidationV2":
        if tuple(check.check_type for check in self.checks) != tuple(LearningItemValidationCheckType):
            raise ValueError("candidate_check_inventory_invalid")
        if self.legacy_receipt is not None and self.legacy_receipt.content_hash != self.content_hash:
            raise ValueError("candidate_legacy_receipt_stale")
        if self.execution_evidence is not None and self.mode != self.execution_evidence.mode:
            raise ValueError("candidate_execution_mode_mismatch")
        if self.state == "machine_verified":
            if self.safe_reasons or any(check.status in {"failed", "pending"} for check in self.checks):
                raise ValueError("candidate_verified_checks_incomplete")
            if self.mode == "synthetic":
                raise ValueError("candidate_synthetic_not_verified")
            if self.mode == "live":
                evidence = self.execution_evidence
                if evidence is None or evidence.isolation != "approved_os_boundary" or (
                    evidence.source_hash, evidence.content_hash
                ) != (self.source_hash, self.content_hash):
                    raise ValueError("candidate_execution_evidence_invalid")
            elif self.legacy_receipt is None:
                raise ValueError("candidate_static_receipt_missing")
        return self

    @property
    def evidence_hash(self) -> str:
        return canonical_hash(checked_model(self, CandidateValidationV2).model_dump(mode="json"))


class CandidateExecutionPort(Protocol):
    def validate(self, source: LearningItemSourceV1) -> CandidateExecutionEvidenceV2: ...

    def verify(self, evidence: CandidateExecutionEvidenceV2, source: LearningItemSourceV1) -> bool:
        """Authenticate a current, reproducible receipt from the approved executor."""
        ...


_STATIC = {
    LearningItemValidationCheckType.SOURCE_REFERENCES: legacy._source_references,
    LearningItemValidationCheckType.DIFFICULTY_PROFILE: legacy._difficulty,
    LearningItemValidationCheckType.PUBLIC_PRIVATE_BOUNDARY: legacy._public_private,
    LearningItemValidationCheckType.MARKDOWN_SAFETY: legacy._markdown,
    LearningItemValidationCheckType.HINT_LEAKAGE: legacy._hints,
    LearningItemValidationCheckType.PRACTICE_CONTRACT: legacy._practice,
    LearningItemValidationCheckType.SCORER: legacy._scorer,
}
_EXECUTION = frozenset({
    LearningItemValidationCheckType.STANDARD_ANSWER,
    LearningItemValidationCheckType.STARTER_NOT_PASSING,
    LearningItemValidationCheckType.RUNTIME_OR_EVENT,
})


def validate_candidate(
    source: LearningItemSourceV1, *, execution_port: CandidateExecutionPort | None = None,
    finite_spec: FiniteCandidateSpecV1 | None = None,
) -> CandidateValidationV2:
    """Validate strict content; source authorization and publication remain separate.

    Raises ValueError for malformed typed sources, without echoing private values.
    Runtime failure reasons are fixed codes; port exceptions never escape or log.
    """
    try:
        source = checked_model(source, LearningItemSourceV1)
    except (ValidationError, ValueError, TypeError, AttributeError):
        raise ValueError("candidate_source_schema_invalid") from None
    native_plan = None
    native_port_matches = True
    if finite_spec is not None:
        if source.public.kind is LearningItemKind.KNOWLEDGE_CHECK:
            raise ValueError("finite_static_use_typed_static_facts")
        from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
        from app.services.learning.item_supply.sandbox.execution import SandboxCandidateExecutionPort
        from app.services.learning.item_supply.sandbox.finite_probe_plans import build_finite_candidate_probe_plan

        finite_spec = checked_model(finite_spec, FiniteCandidateSpecV1)
        native_plan = build_finite_candidate_probe_plan(source, spec=finite_spec)
        native_port_matches = execution_port is None or (
            type(execution_port) is SandboxCandidateExecutionPort
            and execution_port._finite_spec == finite_spec and execution_port._plan == native_plan)
    required = required_probes(source, finite_spec=finite_spec)
    if source.public.kind is LearningItemKind.KNOWLEDGE_CHECK:
        receipt = legacy.validate_learning_item(source)
        checks = tuple(CandidateCheckV2.model_validate(check.model_dump(mode="json")) for check in receipt.checks)
        failures = tuple(check.safe_code for check in checks if check.status == "failed" and check.safe_code)
        content = source.public.content
        gaps: tuple[str, ...] = ("short_text_independent_scoring_unavailable",) if isinstance(content, LearningItemKnowledgeCheckContentV1) and content.response_kind == "short_text" else ()
        return CandidateValidationV2(
            state="rejected" if failures else "blocked" if gaps else "machine_verified",
            source_hash=source.source_hash, content_hash=source.content_hash,
            legacy_receipt=receipt, checks=checks, safe_reasons=failures or gaps,
        )

    supported = source.public.kind in {LearningItemKind.CODE, LearningItemKind.SQL}
    checks_list: list[CandidateCheckV2] = []
    for check_type in LearningItemValidationCheckType:
        status: Literal["passed", "failed", "not_applicable", "pending"] = "pending"
        code: str | None = None
        evidence: object = {"source_hash": source.source_hash}
        if check_type is LearningItemValidationCheckType.SCHEMA:
            status = "passed"
        elif supported and check_type in _STATIC:
            outcome = _STATIC[check_type](source)
            status, code, evidence = outcome.status, outcome.safe_code, dict(outcome.evidence)
        checks_list.append(CandidateCheckV2(
            check_type=check_type, status=status, safe_code=code,
            proof_hash=canonical_hash({"source_hash": source.source_hash, "check": check_type.value, "status": status, "evidence": evidence}),
        ))
    failures = tuple(check.safe_code for check in checks_list if check.status == "failed" and check.safe_code)
    profile_failures, gaps = profile_errors(source) if supported else ((), ("item_kind_not_supported",))
    failures += profile_failures
    execution: CandidateExecutionEvidenceV2 | None = None
    mode: Literal["static", "live", "synthetic"] = "static"
    if not failures and not gaps:
        if not native_port_matches:
            gaps = ("finite_execution_context_mismatch",)
        elif execution_port is None:
            gaps = ("trusted_execution_unavailable",)
        else:
            try:
                execution = checked_model(execution_port.validate(source), CandidateExecutionEvidenceV2)
                mode = execution.mode
                authenticated = execution_port.verify(execution, source)
            except Exception:
                execution = None
                authenticated = False
            if execution is None or authenticated is not True:
                gaps = ("execution_receipt_untrusted",)
            elif (execution.source_hash, execution.content_hash, execution.kind, execution.language, execution.runtime_profile_id, execution.dialect) != (
                source.source_hash, source.content_hash, source.public.kind.value, source.blueprint.language_id,
                source.blueprint.runtime_profile_id, "sqlite" if source.public.kind is LearningItemKind.SQL else None,
            ):
                failures = ("execution_receipt_identity_mismatch",)
            elif execution.mode != "live" or execution.isolation != "approved_os_boundary":
                gaps = ("trusted_isolation_unavailable",)
            else:
                probes = {probe.name: probe for probe in execution.probes}
                if len(probes) != len(execution.probes):
                    failures = ("execution_probe_duplicate",)
                elif native_plan is not None and (
                    tuple(probe.name for probe in execution.probes) != required
                    or any(probe.profile_version != native_plan.profile_id for probe in execution.probes)
                ):
                    failures = ("finite_execution_profile_mismatch",)
                elif any(probe.status == "failed" for probe in execution.probes):
                    failures = ("execution_probe_failed",)
                elif any(name not in probes or probes[name].status != "passed" for name in required):
                    gaps = ("execution_profile_evidence_incomplete",)
                else:
                    checks_list = [
                        CandidateCheckV2(check_type=check.check_type, status="passed", proof_hash=canonical_hash(execution.model_dump(mode="json")))
                        if check.check_type in _EXECUTION else check for check in checks_list
                    ]
    return CandidateValidationV2(
        state="rejected" if failures else "blocked" if gaps else "machine_verified",
        source_hash=source.source_hash, content_hash=source.content_hash,
        checks=tuple(checks_list), execution_evidence=execution,
        safe_reasons=failures or gaps, mode=mode,
    )
