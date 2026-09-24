"""Synthetic server context for phase-II A contract tests, NOT B/C authority."""
from datetime import datetime, timezone

from app.services.grounding.autonomous.access_policy import AccessRequest, AuthoritySnapshot
from app.services.grounding.autonomous.assessment_contracts import ClaimEvidenceReceipt, ExecutionReceipt, ExecutionScope
from app.services.grounding.autonomous.contracts import (
    LearningMaterialDemand, RagBudgetDelegation, RagEvidenceBinding, SourceAssessment,
    SubjectScope,
)
from app.services.grounding.autonomous.source_policy import SourceAuthorization

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
H = "a" * 64
H2 = "b" * 64
SCOPE = SubjectScope(subject_id="route.python", subject_version="3.12", facets=("syntax",))
BUDGET = RagBudgetDelegation(root_id="root.001", delegation_id="delegation.001", generation=1,
                             expires_at=datetime(2026, 9, 25, tzinfo=timezone.utc))


def demand(purpose="main_teaching") -> LearningMaterialDemand:
    return LearningMaterialDemand(scope=SCOPE, demand_hash=H, plan_ref="plan.001", node_ref="node.001",
                                  draft_revision=1, purpose=purpose, reading_level="beginner", language="zh")


def access(action="discover", purpose="main_teaching") -> AccessRequest:
    return AccessRequest(demand_hash=H, scope=SCOPE, purpose=purpose, actor_id="actor.001", action=action,
                         policy_id="policy.001", policy_generation=2, budget=BUDGET)


class Authority:
    def __init__(self, purpose="main_teaching"):
        self.calls = 0
        self.purpose = purpose

    def resolve(self, request: AccessRequest) -> AuthoritySnapshot:
        self.calls += 1
        return AuthoritySnapshot(demand=demand(self.purpose), demand_hash=H, scope=SCOPE, purpose=self.purpose, actor_id="actor.001",
                                 allowed_actions=("discover", "probe", "store", "activate", "consume"),
                                 policy_id="policy.001", policy_generation=2,
                                 budget=BUDGET, budget_active=True, authorized=True)


def assessment(usages=("main_teaching",)) -> SourceAssessment:
    return SourceAssessment(scope=SCOPE, source_handle="source.blog", document_handle="document.001",
                            document_revision="v1", document_hash=H2, origin="blog",
                            reading_level="beginner", status="reviewed", allowed_usages=usages,
                            storage_receipt_id="store.001", admission_receipt_id="admission.001",
                            policy_generation=2)


class Sources:
    def __init__(self, usages=("main_teaching",)):
        self.usages = usages

    def resolve(self, source_handle: str, document_handle: str) -> SourceAuthorization:
        if source_handle == "source.official" and document_handle == "document.official":
            return SourceAuthorization(scope=SCOPE, source_handle="source.official",
                                       lineage_family="family.official", origin="official", reading_level="beginner",
                                       reviewed=True, document_handle="document.official",
                                       document_revision="v1", document_hash=H, storage_receipt_id="store.official",
                                       admission_receipt_id="admission.official",
                                       allowed_usages=("assessment_evidence",), policy_generation=2,
                                       revoked=False, readable=True)
        return SourceAuthorization(scope=SCOPE, source_handle="source.blog", lineage_family="family.blog", origin="blog", reading_level="beginner",
                                   reviewed=True, document_handle="document.001",
                                   document_revision="v1", document_hash=H2, storage_receipt_id="store.001",
                                   admission_receipt_id="admission.001", allowed_usages=self.usages,
                                   policy_generation=2, revoked=False, readable=True)


def binding(purpose="main_teaching", claim_receipt_id=None) -> RagEvidenceBinding:
    return RagEvidenceBinding(scope=SCOPE, demand_hash=H, purpose=purpose, source_handle="source.blog",
                              document_handle="document.001", document_revision="v1", document_hash=H2,
                              admission_receipt_id="admission.001", claim_receipt_id=claim_receipt_id)


def receipt(method="independent_source") -> ClaimEvidenceReceipt:
    fields = dict(primary_lineage_family="family.blog", independent_lineage_family="family.official",
                  independent_source_handle="source.official", independent_document_handle="document.official",
                  independent_document_revision="v1", independent_document_hash=H,
                  independent_lineage_verified=True) if method == "independent_source" else dict(
                      execution_receipt_id="execution.001",
                      execution_scope=ExecutionScope(runtime_profile="python.312", input_hash=H,
                                                     semantics_hash=H2))
    return ClaimEvidenceReceipt(receipt_id="claim.001", demand_hash=H, purpose="assessment_evidence",
                                admission_receipt_id="admission.001", claim_hash=H, scope=SCOPE,
                                source_handle="source.blog", document_handle="document.001",
                                document_revision="v1", document_hash=H2, applicability="Python 3.12 list indexing",
                                method=method, verified=True, revoked=False, **fields)


def execution_receipt() -> ExecutionReceipt:
    return ExecutionReceipt(receipt_id="execution.001", claim_hash=H, demand_hash=H,
                            scope=SCOPE, source_handle="source.blog", document_handle="document.001",
                            document_revision="v1", document_hash=H2,
                            execution_scope=receipt("isolated_execution").execution_scope,
                            verified=True, revoked=False)


class Executions:
    def __init__(self, value: ExecutionReceipt):
        self.value = value

    def resolve(self, receipt_id: str) -> ExecutionReceipt:
        return self.value


class Claims:
    def __init__(self, value: ClaimEvidenceReceipt):
        self.value = value

    def resolve(self, receipt_id: str) -> ClaimEvidenceReceipt:
        return self.value
