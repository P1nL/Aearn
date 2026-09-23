"""Default-off, read-only plan coverage projection. Not a plan confirmation gate."""
from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol

from psycopg import Connection
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.grounding.retrieval_contracts import (
    ActiveCorpusSelector, CoverageReport, GroundingRetrievalRequest,
    GroundingRetrievalResultV2, stable_hash,
)
from app.services.grounding.subject_contracts import SubjectAssessment, SubjectCapabilityProjection
from app.services.grounding.subject_registry import capability_projection, get_grounding_subject
from app.services.learning.contracts import LearningPlan
from app.services.learning.item_bank.repository import PostgresLearningItemBankRepository

POLICY_VERSION = "rag-plan-preflight-shadow-v1"
LEGACY_ECOSYSTEM_BINDINGS = {"lc-overview": ("python.ai-applications", ("langchain-core",))}
NodeStatus = Literal["supported", "partial", "insufficient", "unavailable"]
RepairAction = Literal[
    "replace_node", "delete_optional_node", "downgrade_assessment",
    "defer_subject", "wait_for_release",
]
_HASH = r"^[0-9a-f]{64}$"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class NodeSourceRequirement(_Frozen):
    """A proposed exact Subject binding, never a claim that it is supported."""

    knowledge_key: str = Field(min_length=1, max_length=160)
    subject_id: str = Field(min_length=3, max_length=100)
    subject_version: str = Field(min_length=1, max_length=80)
    required_facets: tuple[str, ...] = Field(min_length=1, max_length=24)
    required_capabilities: tuple[SubjectAssessment, ...] = Field(min_length=1, max_length=6)
    expected_corpus_generation: int = Field(ge=1)
    expected_corpus_summary_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def unique_scope(self) -> NodeSourceRequirement:
        if (len(set(self.required_facets)) != len(self.required_facets)
                or len(set(self.required_capabilities)) != len(self.required_capabilities)):
            raise ValueError("duplicate node requirements")
        return self


class NodeCapabilityFacts(_Frozen):
    """Server-derived facts; a synthetic fixture and declarations cannot grant release."""

    coverage: CoverageReport
    projection: SubjectCapabilityProjection
    published_item_handles: tuple[str, ...]
    source_generation: int
    synthetic_fixture: bool
    runtime_verified: bool = False
    facts_hash: str = Field(pattern=_HASH)


class NodePreflightResult(_Frozen):
    knowledge_key: str
    subject_id: str
    subject_version: str
    is_core: bool
    required_for_activation: bool
    status: NodeStatus
    corpus_status: str
    corpus_id: str | None
    missing_facets: tuple[str, ...]
    required_capabilities: tuple[SubjectAssessment, ...]
    missing_capabilities: tuple[SubjectAssessment, ...]
    reason_codes: tuple[str, ...]
    allowed_actions: tuple[RepairAction, ...]
    source_generation: int
    source_summary_hash: str | None
    capability_hash: str
    published_item_handles: tuple[str, ...]
    runtime_verified: bool


class PlanPreflightReport(_Frozen):
    plan_hash: str = Field(pattern=_HASH)
    status: NodeStatus
    activation_blocked: bool
    nodes: tuple[NodePreflightResult, ...]
    policy_version: str
    report_hash: str = Field(pattern=_HASH)


class PlanPreflightConflict(ValueError):
    """A changed plan, corpus pointer, or inconsistent fact reader fails closed."""


class PlanFactReader(Protocol):
    def read(self, requirement: NodeSourceRequirement, *, query_text: str,
             item_knowledge_key: str | None,
             item_capabilities: tuple[str, ...]) -> NodeCapabilityFacts: ...


RetrievalPort = Callable[[Connection[dict[str, object]], GroundingRetrievalRequest], GroundingRetrievalResultV2]


def required_node_keys(plan: LearningPlan) -> frozenset[str]:
    """A required module cannot lose its only node, even if that node is marked optional."""
    keys = {node.knowledge_key for node in plan.nodes if node.is_core}
    for module in plan.modules:
        if (module.is_core or not module.is_skippable) and not any(
                node.knowledge_key in keys for node in module.nodes):
            # A required module with no core-marked node still needs one anchor.
            keys.add(min(module.nodes, key=lambda node: node.order_index).knowledge_key)
    return frozenset(keys)


class PostgresPlanFactReader:
    """Real read-only adapters; retrieval implementation is explicitly injected internally.

    Keep the caller's transaction read-only/repeatable-read for a coherent pointer,
    publication and registry snapshot. No operator or runtime retrieval imports here.
    """

    def __init__(self, conn: Connection[dict[str, object]], *, retrieve: RetrievalPort) -> None:
        self._conn = conn
        self._retrieve = retrieve
        self._items = PostgresLearningItemBankRepository(conn)

    def read(self, requirement: NodeSourceRequirement, *, query_text: str,
             item_knowledge_key: str | None,
             item_capabilities: tuple[str, ...]) -> NodeCapabilityFacts:
        subject = get_grounding_subject(requirement.subject_id)
        projection = capability_projection(requirement.subject_id)
        if subject is None or subject.subject_id != requirement.subject_id or projection is None:
            raise PlanPreflightConflict("unknown or non-canonical Subject")
        if not set(requirement.required_facets) <= set((*subject.required_facets, *subject.optional_facets)):
            raise PlanPreflightConflict("Subject facet scope is undeclared")
        request = GroundingRetrievalRequest(
            subject_id=subject.subject_id, subject_version=requirement.subject_version,
            corpus_selector=ActiveCorpusSelector(
                expected_generation=requirement.expected_corpus_generation,
                expected_summary_hash=requirement.expected_corpus_summary_hash,
            ),
            query_text=query_text, required_facets=requirement.required_facets,
            stage="plan_preflight", embedding_mode="disabled",
        )
        result = self._retrieve(self._conn, request)
        coverage = CoverageReport.model_validate(result.coverage.model_dump())
        request_hash = stable_hash(request.model_dump(mode="json"))
        expected_result_hash = (
            stable_hash((request_hash, coverage.report_hash)) if result.plan is None
            else stable_hash((result.plan.plan_hash, coverage.report_hash,
                              tuple(item.model_dump(mode="json") for item in result.evidence)))
        )
        if (result.request_hash != request_hash or result.result_hash != expected_result_hash
                or (result.plan is None and result.evidence)):
            raise PlanPreflightConflict("retrieval result hash or request scope changed")
        if result.plan is not None and (
                result.plan.request_hash != request_hash or result.plan.subject_id != subject.subject_id
                or result.plan.subject_version != requirement.subject_version
                or result.plan.stage != "plan_preflight"
                or result.plan.required_facets != requirement.required_facets):
            raise PlanPreflightConflict("retrieval plan request scope changed")
        if (result.plan is None and coverage.status != "unavailable") or (
                result.plan is not None and (
                    result.plan.corpus_id != coverage.corpus_id
                    or result.plan.corpus_summary_hash != coverage.corpus_summary_hash)):
            raise PlanPreflightConflict("retrieval plan and coverage disagree")
        if (coverage.report_hash != stable_hash(coverage.model_dump(mode="json", exclude={"report_hash"}))
                or coverage.request_hash != stable_hash(request.model_dump(mode="json"))
                or coverage.subject_id != subject.subject_id
                or coverage.subject_version != requirement.subject_version
                or coverage.required_facets != requirement.required_facets
                or coverage.corpus_summary_hash not in (None, requirement.expected_corpus_summary_hash)):
            raise PlanPreflightConflict("retrieval result scope changed")
        handles: tuple[str, ...] = ()
        # A catalog binding is required; free-text plan keys are not item authority.
        # Published-candidate repository checks the latest publication event and
        # required runner capabilities on the same transaction snapshot.
        if item_knowledge_key is not None and len(subject.language_ids) == 1:
            candidates = self._items.published_candidates(
                knowledge_key=item_knowledge_key, language_id=subject.language_ids[0],
                available_capabilities=item_capabilities, limit=8,
            )
            handles = tuple(sorted({item.handle for item in candidates if item.purpose in {"exercise", "knowledge_check", "transfer_check"}}))
        synthetic_fixture = bool(result.plan and result.plan.synthetic_fixture)
        pointer = self._conn.execute(
            "SELECT generation,corpus_version_id FROM grounding_active_corpora WHERE subject_id=%s",
            (subject.subject_id,),
        ).fetchone()
        observed_generation = int(str(pointer["generation"])) if pointer is not None else 0
        if (pointer is not None and (observed_generation != requirement.expected_corpus_generation
                                      or (coverage.corpus_id is not None and
                                          pointer["corpus_version_id"] != coverage.corpus_id))):
            raise PlanPreflightConflict("active corpus pointer changed")
        payload = {
            "coverage_hash": coverage.report_hash, "projection": projection.model_dump(mode="json"),
            "handles": handles, "generation": observed_generation,
            "synthetic_fixture": synthetic_fixture, "runtime_verified": False,
        }
        return NodeCapabilityFacts(
            coverage=coverage, projection=projection, published_item_handles=handles,
            source_generation=observed_generation,
            synthetic_fixture=synthetic_fixture, runtime_verified=False, facts_hash=stable_hash(payload),
        )


class PlanCoveragePreflightService:
    def __init__(self, facts: PlanFactReader) -> None:
        self._facts = facts

    def evaluate(self, plan: LearningPlan, requirements: tuple[NodeSourceRequirement, ...], *,
                 expected_plan_hash: str) -> PlanPreflightReport:
        if plan.content_hash != expected_plan_hash:
            raise PlanPreflightConflict("plan revision changed")
        by_key = {item.knowledge_key: item for item in requirements}
        if len(by_key) != len(requirements) or set(by_key) != {node.knowledge_key for node in plan.nodes}:
            raise PlanPreflightConflict("node requirements must cover the exact plan")
        required_keys = required_node_keys(plan)
        depended_on = {key for node in plan.nodes for key in node.prerequisite_keys}
        module_sizes = {
            node.knowledge_key: len(module.nodes)
            for module in plan.modules for node in module.nodes
        }
        results: list[NodePreflightResult] = []
        for node in plan.nodes:
            req = NodeSourceRequirement.model_validate(by_key[node.knowledge_key].model_dump())
            # Every learning node promises both teaching and practice. A caller may
            # demand more, but cannot omit these to manufacture readiness.
            if not {"lesson", "practice"} <= set(req.required_capabilities):
                raise PlanPreflightConflict("required assessment scope omitted")
            subject = get_grounding_subject(req.subject_id)
            if subject is None or subject.subject_id != req.subject_id:
                raise PlanPreflightConflict("unknown or non-canonical Subject")
            binding = LEGACY_ECOSYSTEM_BINDINGS.get(req.knowledge_key)
            if binding is not None and (req.subject_id, req.required_facets) != binding:
                raise PlanPreflightConflict("legacy ecosystem mapping changed")
            if not set(req.required_facets) <= set((*subject.required_facets, *subject.optional_facets)):
                raise PlanPreflightConflict("Subject facet scope is undeclared")
            facts = NodeCapabilityFacts.model_validate(
                self._facts.read(req, query_text=node.title,
                                 item_knowledge_key=node.catalog_knowledge_key,
                                 item_capabilities=node.required_capabilities).model_dump()
            )
            coverage = facts.coverage
            if coverage.report_hash != stable_hash(coverage.model_dump(mode="json", exclude={"report_hash"})):
                raise PlanPreflightConflict("coverage report hash changed")
            if node.catalog_knowledge_key is None and facts.published_item_handles:
                raise PlanPreflightConflict("unbound Learning Item facts")
            canonical_projection = capability_projection(req.subject_id)
            expected_facts_hash = stable_hash({
                "coverage_hash": coverage.report_hash,
                "projection": facts.projection.model_dump(mode="json"),
                "handles": facts.published_item_handles,
                "generation": facts.source_generation,
                "synthetic_fixture": facts.synthetic_fixture, "runtime_verified": facts.runtime_verified,
            })
            if (facts.projection.subject_id != req.subject_id or coverage.subject_id != req.subject_id
                    or canonical_projection != facts.projection
                    or facts.facts_hash != expected_facts_hash
                    or coverage.subject_version != req.subject_version
                    or coverage.required_facets != req.required_facets
                    or (facts.source_generation != req.expected_corpus_generation
                        and not (coverage.status == "unavailable" and facts.source_generation == 0))
                    or coverage.corpus_summary_hash not in (None, req.expected_corpus_summary_hash)):
                raise PlanPreflightConflict("source or capability facts changed")
            if "CORPUS_STALE" in coverage.reason_codes or coverage.freshness_state == "stale":
                raise PlanPreflightConflict("corpus pointer changed")
            missing = tuple(cap for cap in req.required_capabilities if not _capability_ready(cap, facts))
            reasons: list[str] = list(coverage.reason_codes)
            if facts.synthetic_fixture:
                reasons.append("SYNTHETIC_FIXTURE_ONLY")
            if not facts.projection.public_course_admissible:
                reasons.append("PUBLIC_RELEASE_UNAVAILABLE")
            if missing:
                reasons.append("CAPABILITY_MISSING")
            if any(cap in {"practice", "review", "tests"} for cap in missing) and not facts.published_item_handles:
                reasons.append("PUBLISHED_ITEM_MISSING")
            if not facts.runtime_verified and any(cap in {"execution", "tests", "static_analysis"} for cap in req.required_capabilities):
                reasons.append("RUNTIME_UNVERIFIED")
            if coverage.status == "unavailable" or facts.projection.release_state in {"fixture_only", "unavailable", "planned"}:
                status: NodeStatus = "unavailable"
            elif coverage.status == "insufficient":
                status = "insufficient"
            elif coverage.status == "partial" or missing or not facts.projection.public_course_admissible or facts.synthetic_fixture:
                status = "partial"
            else:
                status = "supported"
            actions: tuple[RepairAction, ...] = ()
            if status != "supported":
                is_required = node.knowledge_key in required_keys
                if is_required:
                    actions = ("wait_for_release",)
                else:
                    actions = ("defer_subject",)
                    if node.knowledge_key not in depended_on and module_sizes[node.knowledge_key] > 1:
                        actions = ("delete_optional_node", *actions)
                if (missing and "lesson" in req.required_capabilities
                        and "lesson" not in missing and not is_required
                        and coverage.status == "satisfied" and not facts.synthetic_fixture
                        and facts.projection.public_course_admissible):
                    actions += ("downgrade_assessment",)
            results.append(NodePreflightResult(
                knowledge_key=node.knowledge_key, subject_id=req.subject_id,
                subject_version=req.subject_version, is_core=node.is_core,
                required_for_activation=node.knowledge_key in required_keys,
                status=status, corpus_status=coverage.status,
                corpus_id=str(coverage.corpus_id) if coverage.corpus_id else None,
                missing_facets=coverage.missing_facets,
                required_capabilities=req.required_capabilities,
                missing_capabilities=missing, reason_codes=tuple(dict.fromkeys(reasons)),
                allowed_actions=actions, source_generation=facts.source_generation,
                source_summary_hash=coverage.corpus_summary_hash,
                capability_hash=facts.facts_hash, published_item_handles=facts.published_item_handles,
                runtime_verified=facts.runtime_verified,
            ))
        blocked = any(node.required_for_activation and node.status != "supported" for node in results)
        status = ("unavailable" if any(node.status == "unavailable" for node in results)
                  else "insufficient" if any(node.status == "insufficient" for node in results)
                  else "partial" if any(node.status == "partial" for node in results) else "supported")
        payload: dict[str, object] = {
            "plan_hash": expected_plan_hash, "status": status, "activation_blocked": blocked,
            "nodes": tuple(results), "policy_version": POLICY_VERSION,
        }
        hash_payload = {**payload, "nodes": tuple(item.model_dump(mode="json") for item in results)}
        return PlanPreflightReport.model_validate({**payload, "report_hash": stable_hash(hash_payload)})


def _capability_ready(cap: SubjectAssessment, facts: NodeCapabilityFacts) -> bool:
    projection = facts.projection
    component = {
        "lesson": projection.lesson_generation, "practice": projection.practice_generation,
        "execution": projection.execution, "tests": projection.tests,
        "static_analysis": projection.static_analysis, "review": projection.review,
    }[cap]
    if component not in {"implemented", "executable"}:
        return False
    if cap in {"execution", "tests", "static_analysis"} and not facts.runtime_verified:
        return False
    if cap in {"practice", "review", "tests"} and not facts.published_item_handles:
        return False
    return True


class PlanCoverageShadowAdapter:
    """Internal opt-in seam; disabled by default and never touches the fact reader then."""

    def __init__(self, preflight: PlanCoveragePreflightService, *, enabled: bool = False) -> None:
        self._preflight = preflight
        self._enabled = enabled

    def evaluate(self, plan: LearningPlan, requirements: tuple[NodeSourceRequirement, ...], *,
                 expected_plan_hash: str) -> PlanPreflightReport | None:
        if not self._enabled:
            return None
        return self._preflight.evaluate(plan, requirements, expected_plan_hash=expected_plan_hash)
