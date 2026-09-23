"""Read-only scenario manifest for synthetic RAG v2 architecture demonstrations.

This does not create corpus material. ``corpus_fixture_policy`` alone owns the
sealed fixture-v1 bytes and digests; no public learner path imports this module.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.grounding.corpus_fixture_policy import FIXTURE_VERSION, fixture_slices
from app.services.grounding.subject_registry import get_grounding_subject


@dataclass(frozen=True, slots=True)
class FixtureScenario:
    subject_id: str
    route_family: str
    query_text: str
    required_facets: tuple[str, ...]
    language_ids: tuple[str, ...]
    fixture_only: bool


# Explicit identities/facets catch taxonomy drift; content remains in the sealed
# neutral fixture policy. All four routes and six ecosystem packages are internal.
SCENARIOS: tuple[FixtureScenario, ...] = (
    FixtureScenario("route.python", "python", "Python syntax functions", ("fundamentals", "syntax", "functions"), ("python",), False),
    FixtureScenario("route.typescript-javascript", "typescript-javascript", "JavaScript TypeScript syntax types", ("fundamentals", "syntax", "types"), ("typescript", "javascript"), False),
    FixtureScenario("route.web-platform", "web-platform", "HTML CSS DOM styling accessibility", ("dom", "styling", "accessibility"), ("html", "css"), False),
    FixtureScenario("route.sql", "sql", "SQL queries schema", ("queries", "schema"), ("sql",), False),
    FixtureScenario("python.ai-applications", "python", "Python AI LLM tool calling handwritten RAG", ("llm-api", "tool-calling", "handwritten-rag"), ("python",), True),
    FixtureScenario("python.fastapi", "python", "FastAPI HTTP routing validation", ("http", "routing", "validation"), ("python",), True),
    FixtureScenario("typescript.nodejs", "typescript-javascript", "Node.js server runtime modules async", ("server-runtime", "modules", "async"), ("typescript", "javascript"), True),
    FixtureScenario("web.react", "web-platform", "React components state effects", ("components", "state", "effects"), ("javascript", "typescript", "html", "css"), True),
    FixtureScenario("web.platform", "web-platform", "Web APIs DOM styling accessibility", ("dom", "styling", "accessibility"), ("html", "css"), True),
    FixtureScenario("sql.postgresql-foundations", "sql", "PostgreSQL dialect schema transactions", ("postgresql-dialect", "schema", "transactions"), ("sql",), True),
)


def fixture_scenarios() -> tuple[FixtureScenario, ...]:
    return SCENARIOS


def validate_fixture_scenarios() -> tuple[str, ...]:
    """Check the manifest against registry-owned Subject and fixture scope."""
    errors: list[str] = []
    if len({item.subject_id for item in SCENARIOS}) != len(SCENARIOS):
        errors.append("DUPLICATE_SUBJECT")
    for item in SCENARIOS:
        subject = get_grounding_subject(item.subject_id)
        if subject is None or subject.subject_id != item.subject_id:
            errors.append(f"SUBJECT_UNKNOWN:{item.subject_id}")
            continue
        parent_route = subject.parent_subject_id or subject.subject_id
        if (subject.required_facets != item.required_facets or subject.language_ids != item.language_ids
                or item.route_family != parent_route.removeprefix("route.")
                or (subject.release_state == "fixture_only") != item.fixture_only
                or item.route_family not in {"python", "typescript-javascript", "web-platform", "sql"}
                or not item.query_text.strip()):
            errors.append(f"SCENARIO_SCOPE_INVALID:{item.subject_id}")
        slices = fixture_slices(subject)
        if (len(slices) != len(item.required_facets)
                or tuple(s.facet for s in slices) != item.required_facets
                or any(not s.url.startswith("https://fixtures.aearn.invalid/") for s in slices)):
            errors.append(f"FIXTURE_SCOPE_INVALID:{item.subject_id}")
    return tuple(errors)


def scenario_for_subject(subject_id: str) -> FixtureScenario | None:
    return next((item for item in SCENARIOS if item.subject_id == subject_id), None)


__all__ = ("FIXTURE_VERSION", "FixtureScenario", "fixture_scenarios", "scenario_for_subject", "validate_fixture_scenarios")
