"""Private v2 review facts, not v1 governance or publication authority."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.services.learning.item_bank.contracts import (
    LearningItemKind,
    LearningItemReviewRole,
    LearningItemRiskTier,
    LearningItemSourceV1,
    LearningItemValidationReceiptV1,
    LearningItemValidationCheckType,
    canonical_hash,
    learning_item_handle,
)
from app.services.learning.item_bank.review_contracts import (
    REQUIRED_REVIEW_ROLES,
    LearningItemReviewSeverity,
    LearningItemReviewVerdict,
)
from app.services.learning.item_supply.contracts import Digest, Identifier
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2


ValidationReceiptV2 = Annotated[
    LearningItemValidationReceiptV1 | CandidateValidationV2, Field(discriminator="schema_version"),
]

REVIEW_DIAGNOSTIC_PROMPT_VERSION = "item-supply-private-review-diagnostic-v1"


class CandidateBindingV2(StorageContract):
    candidate_key: Identifier
    version_key: Identifier
    content_hash: Digest
    source_hash: Digest
    policy_hash: Digest
    profile_hash: Digest
    runtime_key: Identifier
    risk_tier: LearningItemRiskTier


class ProviderIdentityV2(StorageContract):
    identity: Identifier
    provider: Identifier
    model: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    model_version: Identifier = "unreported"

    @property
    def correlation_key(self) -> str:
        # Role labels, configured identities and claimed version labels cannot
        # disguise repeated calls to the same underlying provider/model.
        return canonical_hash({"provider": self.provider, "model": self.model.casefold()})


class ProviderRunV2(StorageContract):
    provider_identity: ProviderIdentityV2
    run_id: UUID
    prompt_version: Identifier
    input_hash: Digest
    output_hash: Digest
    profile_hash: Digest
    timeout_seconds: float = Field(gt=0, le=3600)
    max_output_tokens: int = Field(ge=1, le=100_000)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class BlindProblemV2(StorageContract):
    kind: LearningItemKind
    title: str = Field(min_length=1, max_length=240)
    problem_markdown: str = Field(min_length=1, max_length=16_000)
    starter: str | None = Field(default=None, max_length=48_000)
    interface_markdown: str | None = Field(default=None, max_length=48_000)
    language: Identifier | None = None
    response_kind: Literal[
        "single_choice", "multiple_choice", "prediction", "ordering", "code_range", "short_text"
    ] | None = None
    options: tuple[tuple[str, str], ...] = Field(default=(), max_length=12)


class BlindSolveInputV2(StorageContract):
    schema_version: Literal["item_supply_blind_input_v2"] = "item_supply_blind_input_v2"
    binding: CandidateBindingV2
    problem: BlindProblemV2

    @property
    def input_hash(self) -> str:
        return canonical_hash(checked_model(self, BlindSolveInputV2).model_dump(mode="json"))


class BlindSolveResultV2(StorageContract):
    """Ephemeral scorer input; never store this object in staging or evidence."""

    answer: str = Field(min_length=1, max_length=48_000, repr=False)
    run: ProviderRunV2


class BlindScoreV2(StorageContract):
    passed: bool
    scorer_identity: Identifier
    scorer_version: Identifier
    receipt_hash: Digest


class BlindSolveReceiptV2(StorageContract):
    schema_version: Literal["item_supply_blind_receipt_v2"] = "item_supply_blind_receipt_v2"
    state: Literal["completed"] = "completed"
    mode: Literal["public_only"] = "public_only"
    binding: CandidateBindingV2
    run: ProviderRunV2
    solution_hash: Digest
    score: BlindScoreV2

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(checked_model(self, BlindSolveReceiptV2).model_dump(mode="json"))


class ReviewInputV2(StorageContract):
    schema_version: Literal["item_supply_review_input_v2"] = "item_supply_review_input_v2"
    binding: CandidateBindingV2
    role: LearningItemReviewRole
    source: LearningItemSourceV1
    validation_receipt: ValidationReceiptV2
    validation_receipt_hash: Digest | None = None

    @model_validator(mode="before")
    @classmethod
    def original_typed_tree(cls, data: object) -> object:
        # A nested copied/constructed model must not be normalized by a base
        # field annotation before its original fields have been inspected.
        if isinstance(data, Mapping):
            source = data.get("source")
            receipt = data.get("validation_receipt")
            if isinstance(source, BaseModel):
                checked_model(source, LearningItemSourceV1)
            if isinstance(receipt, BaseModel):
                checked_validation_receipt(receipt)
        return data

    @model_validator(mode="after")
    def exact_subject(self) -> ReviewInputV2:
        check_subject(self.source, self.binding, self.validation_receipt)
        digest = receipt_digest(self.validation_receipt)
        if self.validation_receipt_hash is not None and self.validation_receipt_hash != digest:
            raise ValueError("stale review validation digest")
        object.__setattr__(self, "validation_receipt_hash", digest)
        return self

    @property
    def scoring_descriptor(self) -> dict[str, object] | None:
        """Program-owned scoring declaration, NOT a verdict or seal verifier.

        Raw author tests are retained. An empty input_json does not express the
        effective goal rules of this one exact server-versioned public task.
        Other profiles keep their original payload and hash unchanged.
        """
        from app.services.learning.item_supply.finite_review_descriptor import finite_scoring_descriptor

        native = finite_scoring_descriptor(self.source, self.validation_receipt, self.binding)
        if native is not None:
            return native
        from app.services.learning.item_supply.sandbox.python_goal_scorer import (
            PYTHON_GOAL_ID, PYTHON_GOAL_INSTRUCTION, PYTHON_GOAL_PROFILE,
            PYTHON_GOAL_SCORER_HASH, PYTHON_GOAL_SCORER_VERSION, compile_goal_tests,
            compile_python_test_bundle,
        )
        if self.source.public.instruction_markdown != PYTHON_GOAL_INSTRUCTION:
            return None
        from app.services.learning.item_supply.sandbox.probe_plans import build_candidate_probe_plan
        plan = build_candidate_probe_plan(self.source, profile_id=PYTHON_GOAL_PROFILE)
        validation = self.validation_receipt
        if (not isinstance(validation, CandidateValidationV2) or validation.state != "machine_verified"
                or validation.execution_evidence is None
                or validation.execution_evidence.scorer_version != PYTHON_GOAL_SCORER_VERSION):
            raise ValueError("review Python goal scoring declaration mismatch")
        tests = compile_goal_tests(self.source)
        cases = compile_python_test_bundle(tests)
        return {
            "schema_version": "python_goal_review_scoring_descriptor_v1",
            "authority": "program_owned_finite_declaration_not_review_verdict",
            "profile_id": PYTHON_GOAL_PROFILE, "goal_contract_id": PYTHON_GOAL_ID,
            "scorer_version": PYTHON_GOAL_SCORER_VERSION,
            "scoring_contract_hash": PYTHON_GOAL_SCORER_HASH,
            "server_fixture_hash": plan.server_fixture_hash,
            "source_hash": self.binding.source_hash, "content_hash": self.binding.content_hash,
            "binding_hash": canonical_hash(self.binding.model_dump(mode="json")),
            "validation_receipt_hash": self.validation_receipt_hash,
            "compiled_test_bundle_hash": canonical_hash(tests),
            "compiled_runtime_cases_hash": canonical_hash(cases),
            "case_compilation_rule": "For this exact public task and frozen blueprint version, the service compiles the mandatory goal_contract into every actual test case. Author input_json={} and all_tests_v1 metadata do not select stdout-only scoring. Explicit contradictory goal declarations are rejected; authored expected outputs are preserved.",
            "pass_rule": "Both existing newline-normalized stdout comparison and the actual sealed in-image AST goal facts must pass. goal_contract_id must match exactly and goal_satisfied must be the strict boolean true. A constant output or missing assignment does not pass merely because stdout matches.",
            "facts_boundary": "Candidate, reference, equivalent, wrong, boundary and blind scoring use the same goal-aware scorer after runner seal/request verification. Missing facts or infrastructure errors remain pending, not intentional wrong-answer proof. This declaration itself does not authenticate a receipt.",
            "finite_syntax_scope": "Only the two explicitly public sequential structures: numbers literal assignment followed by print(sum(numbers)), or numbers literal assignment followed by total=sum(numbers) and print(total). This is not a claim to accept arbitrary equivalent Python programs.",
            "completion_metadata_boundary": "Current CodeContent/Practice adapter carries code_blanks as concept/pattern metadata and imposes no mandatory starter-to-marker relation or automatic placeholder replacement. This declaration does not establish UI behavior or claim the starter is pedagogically sound; independently judge the public instruction, actual starter and blanks. The finite goal profile scores the declared starter as provided, without rewriting it. Negative evidence requires successful sealed case facts and semantic rejection; NameError, SyntaxError or infrastructure failure is not intentional wrong-answer evidence.",
        }

    @property
    def input_payload(self) -> dict[str, object]:
        request = checked_model(self, ReviewInputV2)
        payload = request.model_dump(mode="json")
        descriptor = request.scoring_descriptor
        if descriptor is not None:
            payload["scoring_descriptor"] = descriptor
        return payload

    @property
    def input_hash(self) -> str:
        return canonical_hash(self.input_payload)


class ReviewFindingV2(StorageContract):
    severity: LearningItemReviewSeverity
    blocking: bool
    safe_code: Literal[
        "curriculum_mismatch", "difficulty_mismatch", "technical_failure", "ambiguity", "security",
        "data_leakage", "unique_answer", "rubric_mismatch", "adversarial_exploit", "deterministic_failure",
        "profile_gap", "source_claim_missing", "source_version_mismatch", "coverage_gap", "minor_issue",
    ]
    evidence_hash: Digest

    @model_validator(mode="after")
    def material_blocker(self) -> ReviewFindingV2:
        if self.blocking and self.severity not in {
            LearningItemReviewSeverity.MAJOR, LearningItemReviewSeverity.CRITICAL,
        }:
            raise ValueError("blocking review finding must be material")
        return self


class ReviewReportV2(StorageContract):
    schema_version: Literal["item_supply_review_report_v2"] = "item_supply_review_report_v2"
    state: Literal["completed"] = "completed"
    mode: Literal["peer_blind"] = "peer_blind"
    binding: CandidateBindingV2
    role: LearningItemReviewRole
    run: ProviderRunV2
    verdict: LearningItemReviewVerdict
    findings: tuple[ReviewFindingV2, ...] = Field(default=(), max_length=24)

    @property
    def material_failure(self) -> bool:
        return self.verdict is not LearningItemReviewVerdict.APPROVED or any(
            f.blocking or f.safe_code in {
                "deterministic_failure", "security", "unique_answer", "rubric_mismatch", "data_leakage",
                "adversarial_exploit",
            } or f.severity in {LearningItemReviewSeverity.MAJOR, LearningItemReviewSeverity.CRITICAL}
            for f in self.findings
        )

    @property
    def report_hash(self) -> str:
        return canonical_hash(checked_model(self, ReviewReportV2).model_dump(mode="json"))


class ReviewDiagnosticReferenceV1(StorageContract):
    """Exact pointer within ReviewInputV2.input_payload, never an external path."""

    pointer: str = Field(min_length=2, max_length=512, pattern=r"^/(source|validation_receipt|scoring_descriptor)/")
    value_hash: Digest


class ReviewDiagnosticInputV1(StorageContract):
    """Explicit private diagnostic request; not a re-review or admission vote."""

    schema_version: Literal["item_supply_review_diagnostic_input_v1"] = "item_supply_review_diagnostic_input_v1"
    purpose: Literal["retrospective_diagnosis"] = "retrospective_diagnosis"
    source_authority: Literal["not_asserted_current", "expired_historical"] = "not_asserted_current"
    review_input: ReviewInputV2 = Field(repr=False)

    @model_validator(mode="before")
    @classmethod
    def original_input(cls, data: object) -> object:
        if isinstance(data, Mapping) and isinstance(data.get("review_input"), BaseModel):
            checked_model(data["review_input"], ReviewInputV2)
        return data

    @property
    def binding(self) -> CandidateBindingV2:
        return self.review_input.binding

    @property
    def evidence_index(self) -> tuple[ReviewDiagnosticReferenceV1, ...]:
        payload = checked_model(self.review_input, ReviewInputV2).input_payload
        refs: list[ReviewDiagnosticReferenceV1] = []

        def visit(value: object, pointer: str, depth: int) -> None:
            if depth > 24 or len(refs) >= 1024:
                raise ValueError("diagnostic evidence index limit")
            refs.append(ReviewDiagnosticReferenceV1(pointer=pointer, value_hash=canonical_hash(value)))
            if isinstance(value, dict):
                for key, child in sorted(value.items()):
                    token = key.replace("~", "~0").replace("/", "~1")
                    visit(child, pointer + "/" + token, depth + 1)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, pointer + "/" + str(index), depth + 1)

        for section in ("source", "validation_receipt", "scoring_descriptor"):
            value = payload.get(section)
            if isinstance(value, dict):
                for key, child in sorted(value.items()):
                    visit(child, "/" + section + "/" + key, 0)
        return tuple(refs)

    @property
    def input_payload(self) -> dict[str, object]:
        request = checked_model(self, ReviewDiagnosticInputV1)
        return {
            "schema_version": request.schema_version,
            "purpose": request.purpose,
            "source_authority": request.source_authority,
            "review_input": request.review_input.input_payload,
            "evidence_index": [ref.model_dump(mode="json") for ref in request.evidence_index],
        }

    @property
    def input_hash(self) -> str:
        return canonical_hash(self.input_payload)


class ReviewDiagnosticFindingV1(ReviewFindingV2):
    """Private, untrusted model claims. Never render as student feedback."""

    problem: str = Field(min_length=1, max_length=1200, pattern=r"\S", repr=False)
    expected_behavior: str = Field(min_length=1, max_length=1200, pattern=r"\S", repr=False)
    references: tuple[ReviewDiagnosticReferenceV1, ...] = Field(min_length=1, max_length=6)


class ReviewDiagnosticOutputV1(StorageContract):
    schema_version: Literal["item_supply_review_diagnostic_output_v1"]
    findings: tuple[ReviewDiagnosticFindingV1, ...] = Field(max_length=12, repr=False)


class ReviewDiagnosticReceiptV1(StorageContract):
    schema_version: Literal["item_supply_review_diagnostic_receipt_v1"] = "item_supply_review_diagnostic_receipt_v1"
    visibility: Literal["private_only"] = "private_only"
    admission_eligible: Literal[False] = False
    binding: CandidateBindingV2
    role: LearningItemReviewRole
    run: ProviderRunV2
    output: ReviewDiagnosticOutputV1 = Field(repr=False)

    def verify_input(self, request: ReviewDiagnosticInputV1) -> None:
        receipt = checked_model(self, ReviewDiagnosticReceiptV1)
        request = checked_model(request, ReviewDiagnosticInputV1)
        if (receipt.binding != request.binding or receipt.role != request.review_input.role
                or receipt.run.prompt_version != REVIEW_DIAGNOSTIC_PROMPT_VERSION
                or receipt.run.profile_hash != request.binding.profile_hash
                or receipt.run.input_hash != request.input_hash
                or receipt.run.output_hash != canonical_hash(receipt.output.model_dump(mode="json"))):
            raise ValueError("stale review diagnostic")
        refs = {ref.pointer: ref.value_hash for ref in request.evidence_index}
        for finding in receipt.output.findings:
            if (finding.evidence_hash != request.binding.content_hash
                    or any(refs.get(ref.pointer) != ref.value_hash for ref in finding.references)
                    or len({ref.pointer for ref in finding.references}) != len(finding.references)):
                raise ValueError("unbound review diagnostic evidence")

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(checked_model(self, ReviewDiagnosticReceiptV1).model_dump(mode="json"))


class EvidencedReviewInputV1(StorageContract):
    """Fresh opt-in vote input; old ReviewInputV2 bytes remain untouched."""

    schema_version: Literal["item_supply_evidenced_review_input_v1"] = "item_supply_evidenced_review_input_v1"
    review_input: ReviewInputV2 = Field(repr=False)

    @model_validator(mode="before")
    @classmethod
    def original_input(cls, data: object) -> object:
        if isinstance(data, Mapping) and isinstance(data.get("review_input"), BaseModel):
            checked_model(data["review_input"], ReviewInputV2)
        return data

    @property
    def binding(self) -> CandidateBindingV2:
        return self.review_input.binding

    @property
    def role(self) -> LearningItemReviewRole:
        return self.review_input.role

    @property
    def evidence_index(self) -> tuple[ReviewDiagnosticReferenceV1, ...]:
        return ReviewDiagnosticInputV1(review_input=self.review_input).evidence_index

    @property
    def input_payload(self) -> dict[str, object]:
        request = checked_model(self, EvidencedReviewInputV1)
        return {"schema_version": request.schema_version,
                "review_input": request.review_input.input_payload,
                "evidence_index": [ref.model_dump(mode="json") for ref in request.evidence_index]}

    @property
    def input_hash(self) -> str:
        return canonical_hash(self.input_payload)


class EvidencedReviewFindingV1(ReviewDiagnosticFindingV1):
    counterexample: str | None = Field(min_length=1, max_length=1200, pattern=r"\S", repr=False)

    @model_validator(mode="after")
    def fixed_scale(self) -> EvidencedReviewFindingV1:
        from app.services.learning.item_supply.review_rubrics import COUNTEREXAMPLE_CODES, HARD_CODES

        material = self.severity in {LearningItemReviewSeverity.MAJOR, LearningItemReviewSeverity.CRITICAL}
        if (self.severity is LearningItemReviewSeverity.NONE or self.blocking != material
                or (self.safe_code in HARD_CODES and not material)
                or (self.safe_code == "minor_issue" and material)):
            raise ValueError("contradictory evidenced severity")
        if self.problem.strip().casefold() == self.expected_behavior.strip().casefold():
            raise ValueError("unexplained evidenced finding")
        if self.safe_code in COUNTEREXAMPLE_CODES and (
            self.counterexample is None or self.counterexample.strip().casefold() == self.safe_code
        ):
            raise ValueError("concrete counterexample required")
        return self


class EvidencedReviewOutputV1(StorageContract):
    schema_version: Literal["item_supply_evidenced_review_output_v1"]
    verdict: LearningItemReviewVerdict
    findings: tuple[EvidencedReviewFindingV1, ...] = Field(max_length=12, repr=False)

    @model_validator(mode="after")
    def supported_verdict(self) -> EvidencedReviewOutputV1:
        expected = LearningItemReviewVerdict.APPROVED
        if any(f.blocking for f in self.findings):
            expected = LearningItemReviewVerdict.CHANGES_REQUIRED
        if any(f.severity is LearningItemReviewSeverity.CRITICAL for f in self.findings):
            expected = LearningItemReviewVerdict.REJECTED
        if self.verdict is not expected:
            raise ValueError("unsupported or contradictory evidenced verdict")
        return self


class EvidencedReviewReportV1(StorageContract):
    schema_version: Literal["item_supply_evidenced_review_report_v1"] = "item_supply_evidenced_review_report_v1"
    state: Literal["completed"] = "completed"
    mode: Literal["peer_blind"] = "peer_blind"
    binding: CandidateBindingV2
    role: LearningItemReviewRole
    run: ProviderRunV2
    verdict: LearningItemReviewVerdict
    findings: tuple[EvidencedReviewFindingV1, ...] = Field(max_length=12, repr=False)

    @property
    def output(self) -> EvidencedReviewOutputV1:
        return EvidencedReviewOutputV1(schema_version="item_supply_evidenced_review_output_v1", verdict=self.verdict, findings=self.findings)

    @model_validator(mode="after")
    def authentic_output(self) -> EvidencedReviewReportV1:
        from app.services.learning.item_supply.review_rubrics import EVIDENCED_REVIEW_PROMPT_VERSION, ROLE_CODES

        if (self.run.prompt_version != EVIDENCED_REVIEW_PROMPT_VERSION
                or self.run.profile_hash != self.binding.profile_hash
                or self.run.output_hash != canonical_hash(self.output.model_dump(mode="json"))
                or any(f.safe_code not in ROLE_CODES[self.role] for f in self.findings)):
            raise ValueError("unbound evidenced review output")
        return self

    def verify_input(self, request: EvidencedReviewInputV1) -> None:
        from app.services.learning.item_supply.review_rubrics import relevant_reference_groups

        report = checked_model(self, EvidencedReviewReportV1)
        request = checked_model(request, EvidencedReviewInputV1)
        if (report.binding != request.binding or report.role is not request.role
                or report.run.input_hash != request.input_hash):
            raise ValueError("stale evidenced review input")
        index = {ref.pointer: ref.value_hash for ref in request.evidence_index}
        for finding in report.findings:
            pointers = tuple(ref.pointer for ref in finding.references)
            groups = relevant_reference_groups(finding.safe_code)
            allowed = tuple(prefix for group in groups for prefix in group)
            if (finding.evidence_hash != request.binding.content_hash or len(set(pointers)) != len(pointers)
                    or any(index.get(ref.pointer) != ref.value_hash for ref in finding.references)
                    or any(not any(p.startswith(prefix) for prefix in allowed)
                           or p.rsplit("/", 1)[-1].endswith("_hash")
                           or p.rsplit("/", 1)[-1] in {"schema_version", "type", "item_key", "version"}
                           for p in pointers)
                    or any(not any(p.startswith(prefix) for p in pointers for prefix in group)
                           for group in groups)):
                raise ValueError("unrelated or tampered evidenced references")

    @property
    def material_failure(self) -> bool:
        return self.verdict is not LearningItemReviewVerdict.APPROVED or any(f.blocking for f in self.findings)

    @property
    def report_hash(self) -> str:
        return canonical_hash(checked_model(self, EvidencedReviewReportV1).model_dump(mode="json"))


ReviewReport = Annotated[ReviewReportV2 | EvidencedReviewReportV1, Field(discriminator="schema_version")]


class ReviewBundleV2(StorageContract):
    schema_version: Literal["item_supply_review_bundle_v2"] = "item_supply_review_bundle_v2"
    policy_version: Literal["autonomous_evidence_policy_v2"] = "autonomous_evidence_policy_v2"
    state: Literal["completed"] = "completed"
    mode: Literal["peer_blind"] = "peer_blind"
    publication_enabled: Literal[False] = False
    bundle_id: UUID
    bundle_version: int = Field(ge=1)
    binding: CandidateBindingV2
    author_identity: Identifier
    blind_solve: BlindSolveReceiptV2
    reports: tuple[ReviewReport, ...] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def identities_and_binding(self) -> ReviewBundleV2:
        if len({type(r) for r in self.reports}) != 1:
            raise ValueError("mixed review protocols")
        if tuple(r.role for r in self.reports) != REQUIRED_REVIEW_ROLES:
            raise ValueError("v2 bundle requires all six canonical roles")
        runs = (self.blind_solve.run,) + tuple(r.run for r in self.reports)
        identities = tuple(r.provider_identity.identity for r in runs)
        if self.author_identity in identities or len(set(identities)) != len(identities):
            raise ValueError("author, solver and reviewer identities must be separate")
        if len({r.run_id for r in runs}) != len(runs):
            raise ValueError("review runs cannot be reused")
        if self.blind_solve.binding != self.binding or any(r.binding != self.binding for r in self.reports):
            raise ValueError("v2 bundle contains stale evidence")
        if any(r.profile_hash != self.binding.profile_hash for r in runs):
            raise ValueError("v2 bundle profile mismatch")
        return self

    @property
    def correlation_groups(self) -> tuple[str, ...]:
        return tuple(sorted({r.run.provider_identity.correlation_key for r in self.reports}))

    @property
    def correlation_limited(self) -> bool:
        models = {r.run.provider_identity.model.casefold() for r in self.reports}
        return len(self.correlation_groups) != len(self.reports) or len(models) != len(self.reports)

    @property
    def bundle_hash(self) -> str:
        return canonical_hash(checked_model(self, ReviewBundleV2).model_dump(mode="json"))

    @property
    def receipt_hash(self) -> str:
        return self.bundle_hash


class ProbeOutcomeV2(StorageContract):
    probe: Literal["correct", "incorrect", "ambiguity", "equivalent", "known_wrong", "boundary", "scorer_counterexample"]
    passed: bool
    receipt_hash: Digest


class RiskEvidenceV2(StorageContract):
    schema_version: Literal["item_supply_risk_evidence_v2"] = "item_supply_risk_evidence_v2"
    state: Literal["completed"] = "completed"
    mode: Literal["trusted_adapter"] = "trusted_adapter"
    binding: CandidateBindingV2
    risk: Identifier
    adapter_version: Identifier
    profile_hash: Digest
    verifier_identity: Identifier
    verifier_version: Identifier
    receipt_hash: Digest
    passed: bool


class AdmissionEvidenceV2(StorageContract):
    """Trusted internal resolver snapshot. Never accept this from public clients."""

    schema_version: Literal["item_supply_admission_evidence_v2"] = "item_supply_admission_evidence_v2"
    binding: CandidateBindingV2
    validation_receipt_hash: Digest
    source_current: bool = False
    source_claim_receipt_hashes: tuple[Digest, ...] = Field(default=(), max_length=48)
    coverage_proof_hash: Digest | None = None
    probes: tuple[ProbeOutcomeV2, ...] = Field(default=(), max_length=7)
    execution_receipt_hash: Digest | None = None
    execution_isolated: bool = False
    runner_available: bool = False
    scorer_available: bool = False
    known_misjudgments: int = Field(default=0, ge=0)
    critical_risks: tuple[Identifier, ...] = Field(default=(), max_length=24)
    risk_evidence: tuple[RiskEvidenceV2, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def no_duplicate_facts(self) -> AdmissionEvidenceV2:
        for keys in (
            tuple(p.probe for p in self.probes), self.critical_risks,
            tuple(r.risk for r in self.risk_evidence), self.source_claim_receipt_hashes,
        ):
            if len(keys) != len(set(keys)):
                raise ValueError("duplicate admission evidence")
        if any(r.binding != self.binding for r in self.risk_evidence):
            raise ValueError("stale risk evidence")
        return self


class AdmissionEvaluationV2(StorageContract):
    schema_version: Literal["item_supply_admission_evaluation_v2"] = "item_supply_admission_evaluation_v2"
    policy_version: Literal["autonomous_evidence_policy_v2"] = "autonomous_evidence_policy_v2"
    state: Literal["evaluated"] = "evaluated"
    mode: Literal["internal_only"] = "internal_only"
    publication_enabled: Literal[False] = False
    binding: CandidateBindingV2
    disposition: Literal["blocked", "evidence_pending", "quarantine", "eligible_internal"]
    safe_reasons: tuple[Identifier, ...] = Field(min_length=1, max_length=32)
    bundle_hashes: tuple[Digest, ...] = Field(default=(), max_length=2)
    evidence_hash: Digest | None = None
    correlation_limited: bool = False

    @property
    def evaluation_hash(self) -> str:
        return canonical_hash(checked_model(self, AdmissionEvaluationV2).model_dump(mode="json"))

    @property
    def receipt_hash(self) -> str:
        return self.evaluation_hash


def check_subject(
    source: LearningItemSourceV1, binding: CandidateBindingV2,
    receipt: ValidationReceiptV2 | None = None,
) -> None:
    source = checked_model(source, LearningItemSourceV1)
    binding = checked_model(binding, CandidateBindingV2)
    if (source.content_hash != binding.content_hash or source.source_hash != binding.source_hash
            or source.blueprint.publication_policy.risk_tier is not binding.risk_tier):
        raise ValueError("stale v2 candidate binding")
    runtime_key = source.blueprint.runtime_profile_id
    if runtime_key is None and source.public.kind is LearningItemKind.KNOWLEDGE_CHECK:
        runtime_key = "static-exact-v1"
    if runtime_key != binding.runtime_key:
        raise ValueError("stale v2 runtime binding")
    if receipt is not None:
        receipt = checked_validation_receipt(receipt)
        if isinstance(receipt, LearningItemValidationReceiptV1):
            handle = learning_item_handle(source.public.item_key, source.public.version, source.content_hash)
            if receipt.item_handle != handle or receipt.content_hash != binding.content_hash:
                raise ValueError("stale deterministic validation")
        else:
            if (receipt.source_hash, receipt.content_hash) != (binding.source_hash, binding.content_hash):
                raise ValueError("stale candidate validation")
            if source.public.kind is LearningItemKind.KNOWLEDGE_CHECK:
                if receipt.mode != "static" or receipt.execution_evidence is not None or receipt.legacy_receipt is None:
                    raise ValueError("invalid static candidate validation")
                check_subject(source, binding, receipt.legacy_receipt)
                if tuple((check.check_type, check.status, check.safe_code, check.proof_hash) for check in receipt.checks) != tuple(
                    (check.check_type, check.status, check.safe_code, check.proof_hash) for check in receipt.legacy_receipt.checks
                ):
                    raise ValueError("static validation checks disagree")
            else:
                execution = receipt.execution_evidence
                if (receipt.mode != "live" or receipt.legacy_receipt is not None or execution is None
                        or execution.isolation != "approved_os_boundary"
                        or (execution.kind, execution.language, execution.runtime_profile_id, execution.dialect) != (
                            source.public.kind.value, source.blueprint.language_id, runtime_key,
                            "sqlite" if source.public.kind is LearningItemKind.SQL else None,
                        )):
                    raise ValueError("invalid live candidate validation")
                from app.services.learning.item_supply.finite_review_descriptor import review_required_probes

                probes = {probe.name: probe for probe in execution.probes}
                if (len(probes) != len(execution.probes)
                        or any(probe.status != "passed" for probe in execution.probes)
                        or not set(review_required_probes(source)) <= set(probes)):
                    raise ValueError("incomplete candidate execution profile")
                digest = execution_receipt_digest(receipt)
                execution_checks = {
                    LearningItemValidationCheckType.STANDARD_ANSWER,
                    LearningItemValidationCheckType.STARTER_NOT_PASSING,
                    LearningItemValidationCheckType.RUNTIME_OR_EVENT,
                }
                if any(check.status != "passed" or check.proof_hash != digest for check in receipt.checks if check.check_type in execution_checks):
                    raise ValueError("stale candidate execution checks")


def checked_validation_receipt(receipt: object) -> ValidationReceiptV2:
    """Read the actual discriminator/type before any potentially lossy dump."""
    if type(receipt) is LearningItemValidationReceiptV1:
        return checked_model(receipt, LearningItemValidationReceiptV1)
    if type(receipt) is CandidateValidationV2:
        return checked_model(receipt, CandidateValidationV2)
    raise ValueError("invalid review validation contract")


def validation_passed(receipt: ValidationReceiptV2) -> bool:
    receipt = checked_validation_receipt(receipt)
    if isinstance(receipt, LearningItemValidationReceiptV1):
        return receipt.passed
    return receipt.state == "machine_verified" and (receipt.legacy_receipt is None or receipt.legacy_receipt.passed)


def receipt_digest(receipt: ValidationReceiptV2) -> str:
    receipt = checked_validation_receipt(receipt)
    if isinstance(receipt, CandidateValidationV2):
        return receipt.evidence_hash
    return canonical_hash(receipt.model_dump(mode="json"))


def execution_receipt_digest(receipt: ValidationReceiptV2) -> str | None:
    receipt = checked_validation_receipt(receipt)
    if isinstance(receipt, CandidateValidationV2) and receipt.mode == "live" and receipt.execution_evidence is not None:
        return canonical_hash(receipt.execution_evidence.model_dump(mode="json"))
    return None
