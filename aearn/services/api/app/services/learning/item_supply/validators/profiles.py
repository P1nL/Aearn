"""First-batch runtime profiles and mandatory counterexample probes."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.learning.item_bank import validation as legacy
from app.services.learning.item_bank.contracts import (
    LearningItemKind, LearningItemSourceV1, LearningItemSqlContentV1,
    LearningItemSqlContentV2, LearningItemSqlPrivateV1, LearningItemSqlPrivateV2,
    canonical_hash,
)

if TYPE_CHECKING:
    from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1


COMMON_PROBES = (
    "reference", "starter_rejected", "equivalent", "wrong_rejected", "boundary",
    "scorer_counterexample", "public_hidden_isolation", "time_limit", "memory_limit", "output_limit",
)
SQL_PROBES = (
    "null", "duplicates", "empty", "order", "types", "joins", "read_only",
    "single_statement", "bounded_setup",
)


def required_probes(source: LearningItemSourceV1, *, finite_spec: FiniteCandidateSpecV1 | None = None) -> tuple[str, ...]:
    if finite_spec is not None:
        from app.services.learning.item_supply.sandbox.finite_probe_plans import build_finite_candidate_probe_plan

        plan = build_finite_candidate_probe_plan(source, spec=finite_spec)
        # Closed source/spec/plan reconstruction, never an arbitrary caller list.
        # Extra names denote actual requests, not generic engine-semantic aliases.
        names = COMMON_PROBES + tuple(probe.name for probe in plan.probes)
        if len(names) != len(set(names)):
            raise ValueError("finite_required_probes_duplicate")
        return names
    return COMMON_PROBES + (SQL_PROBES if source.public.kind is LearningItemKind.SQL else ())


def profile_errors(source: LearningItemSourceV1) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (rejections, readiness gaps), without running any submission."""
    if source.public.kind is LearningItemKind.CODE:
        if source.blueprint.language_id != "python":
            return (), ("language_not_supported",)
        if source.blueprint.runtime_profile_id != "python_stdout_test":
            return (), ("execution_profile_not_supported",)
        return (), ()
    public, private = source.public.content, source.private.content
    if not isinstance(public, (LearningItemSqlContentV1, LearningItemSqlContentV2)):
        return (), ("item_kind_not_supported",)
    if public.dialect != "sqlite":
        return ("sql_dialect_mismatch",), ()
    if source.blueprint.runtime_profile_id != "sql_query_test":
        return ("runtime_profile_mismatch",), ()
    outcome = legacy._runtime_or_event(source)
    if outcome.status == "failed":
        return (outcome.safe_code or "sql_static_invalid",), ()
    if isinstance(private, LearningItemSqlPrivateV1):
        return (), ("independent_sql_dataset_evidence_missing",)
    if isinstance(public, LearningItemSqlContentV2) and isinstance(private, LearningItemSqlPrivateV2):
        visible = {canonical_hash(public.public_dataset.model_dump(mode="json"))}
        visible.update(canonical_hash(test.dataset.model_dump(mode="json")) for test in private.tests if test.case_type == "visible")
        hidden = {canonical_hash(test.dataset.model_dump(mode="json")) for test in private.tests if test.case_type == "hidden"}
        if visible & hidden:
            return ("sql_public_hidden_dataset_reused",), ()
    return (), ()
