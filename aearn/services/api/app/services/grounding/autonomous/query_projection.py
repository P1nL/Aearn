"""Server-vocabulary-only B1 query projection; never forward model query text.

The resolver is a trusted service-side context port, not a model or learner
payload. Without exact full-demand attestation no terms are issued.
"""
from __future__ import annotations

from typing import Protocol

from pydantic import Field

from app.services.grounding.subject_registry import get_grounding_subject

from .contracts import (
    FrozenContract, HANDLE, LearningMaterialDemand, SourceDiscoverySuggestion,
    revalidate, valid_query_terms,
)

# Only reviewed public taxonomy labels may leave the server. Plan/node refs,
# version, model preferences and query_terms are never interpolated.
SUBJECT_TERMS = {
    "route.python": "Python",
    "route.typescript-javascript": "TypeScript JavaScript",
    "route.web-platform": "Web Platform",
    "route.sql": "SQL",
    "python.ai-applications": "Python AI Applications",
    "python.fastapi": "FastAPI",
    "typescript.nodejs": "Node.js",
    "web.react": "React",
    "web.platform": "Web Platform",
    "sql.postgresql-foundations": "PostgreSQL",
}


class TrustedQueryContext(FrozenContract):
    demand: LearningMaterialDemand
    approved_facets: tuple[str, ...] = Field(min_length=1, max_length=6)
    receipt_id: str = Field(pattern=HANDLE)
    authorized: bool


class QueryContextAuthority(Protocol):
    """Server-side full demand and approved public taxonomy, never dialogue."""

    def resolve(self, demand: LearningMaterialDemand) -> TrustedQueryContext | None: ...


class ServerQueryProjectionResolver:
    """Implements QueryProjectionResolver with deterministic public terms."""

    def __init__(self, authority: QueryContextAuthority | None) -> None:
        self._authority = authority

    def project(self, demand: LearningMaterialDemand,
                suggestion: SourceDiscoverySuggestion) -> tuple[str, ...] | None:
        try:
            full = revalidate(demand, LearningMaterialDemand)
            proposed = revalidate(suggestion, SourceDiscoverySuggestion)
            if self._authority is None or proposed.demand_hash != full.demand_hash:
                return None
            raw = self._authority.resolve(full)
            if raw is None:
                return None
            context = revalidate(raw, TrustedQueryContext)
            subject = get_grounding_subject(full.scope.subject_id)
            if (not context.authorized or context.demand != full
                    or subject is None or subject.subject_id != full.scope.subject_id
                    or context.approved_facets != full.scope.facets
                    or set(context.approved_facets) - set(subject.required_facets + subject.optional_facets)):
                return None
            label = SUBJECT_TERMS.get(subject.subject_id)
            if label is None:
                return None
            locale = "中文 教程" if full.language == "zh" else "English tutorial"
            terms = (label, *(facet.replace("-", " ") for facet in context.approved_facets), locale)
            return terms if len(terms) <= 8 and valid_query_terms(terms) else None
        except Exception:
            return None
