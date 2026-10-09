"""Pure purpose partitioning, never a source grant or a quality decision."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

PURPOSE_PARTITION_POLICY = "dynamic-c-purpose-v2"
LEGACY_AUDIT_POLICY = "dynamic-c-v1"
USAGES = frozenset(("main_teaching", "supplementary_explanation", "assessment_evidence"))


def document_usages(admitted: Iterable[str], reviewed: Iterable[str], *,
                    purpose: str, partitioned: bool) -> tuple[str, ...]:
    admitted, reviewed = tuple(admitted), tuple(reviewed)
    if purpose not in USAGES:
        raise ValueError("purpose denied")
    if not partitioned:
        if purpose not in admitted or purpose not in reviewed:
            raise ValueError("purpose denied")
        return (purpose,)
    if (not admitted or len(admitted) > 3 or len(set(admitted)) != len(admitted)
            or not set(admitted) <= USAGES or not set(admitted) <= set(reviewed)):
        raise ValueError("document usage partition denied")
    # Every admitted usage remains independently checked against current review
    # and policy. Irrelevant documents are never silently dropped from the audit.
    return tuple(sorted(admitted))


def purpose_facets(usages: Mapping[str, tuple[str, ...]],
                   facets: Mapping[str, set[str]]) -> dict[str, list[str]]:
    if set(usages) != set(facets):
        raise ValueError("partition document mismatch")
    return {purpose: sorted({facet for doc, granted in usages.items() if purpose in granted
                            for facet in facets[doc]}) for purpose in sorted(USAGES)}
