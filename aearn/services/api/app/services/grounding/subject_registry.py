"""Developer-governed Subject identities, read-only relative to public course selection."""
from __future__ import annotations

from collections.abc import Sequence

from pydantic import ValidationError
from app.services.grounding.subject_contracts import (
    KNOWN_SUBJECT_FACETS,
    GroundingSubject,
    SubjectCapabilityProjection,
    SubjectReleaseState,
)
from app.services.runners.language_capabilities import (
    PUBLIC_COURSE_LANGUAGE_MAP,
    LanguageCapability,
    all_language_capabilities,
    get_language_capability,
)

SUBJECTS: tuple[GroundingSubject, ...] = (
    GroundingSubject(
        subject_id="route.python", display_name="Python", subject_kind="language_core",
        language_ids=("python",), aliases=("python-core",), source_trust_policy="official",
        required_facets=("fundamentals", "syntax", "functions"), optional_facets=("modules", "async"),
        runtime_profile_keys=("python",),
        assessment_capabilities=("lesson", "practice", "execution", "tests", "static_analysis", "review"),
        release_state="shadow",
    ),
    GroundingSubject(
        subject_id="route.typescript-javascript", display_name="TypeScript / JavaScript",
        subject_kind="language_core", language_ids=("typescript", "javascript"),
        aliases=("js-ts-core",), source_trust_policy="official",
        required_facets=("fundamentals", "syntax", "types"), optional_facets=("async", "dom"),
        runtime_profile_keys=("node", "browser"),
        assessment_capabilities=("lesson", "practice", "execution", "tests", "static_analysis", "review"),
        release_state="shadow",
    ),
    GroundingSubject(
        subject_id="route.web-platform", display_name="HTML / CSS Web Platform",
        subject_kind="platform", language_ids=("html", "css"), aliases=("web-platform-core",),
        source_trust_policy="official", required_facets=("dom", "styling", "accessibility"),
        optional_facets=("fundamentals",), runtime_profile_keys=("browser",),
        assessment_capabilities=("lesson", "practice", "execution", "tests", "static_analysis", "review"),
        release_state="shadow",
    ),
    GroundingSubject(
        subject_id="route.sql", display_name="SQL", subject_kind="language_core",
        language_ids=("sql",), aliases=("sql-core",), source_trust_policy="trusted_de_facto",
        required_facets=("queries", "schema"), optional_facets=("transactions",),
        runtime_profile_keys=("sql",),
        assessment_capabilities=("lesson", "practice", "execution", "tests", "review"),
        release_state="shadow",
    ),
    GroundingSubject(
        subject_id="python.ai-applications", display_name="Python AI Applications", subject_kind="library",
        parent_subject_id="route.python", language_ids=("python",), aliases=("python-ai",),
        source_trust_policy="official", required_facets=("llm-api", "tool-calling", "handwritten-rag"),
        optional_facets=("langchain-core",), assessment_capabilities=("lesson",), release_state="fixture_only",
    ),
    GroundingSubject(
        subject_id="python.fastapi", display_name="FastAPI", subject_kind="framework",
        parent_subject_id="route.python", language_ids=("python",), aliases=("fastapi",),
        source_trust_policy="official", required_facets=("http", "routing", "validation"),
        assessment_capabilities=("lesson",), release_state="fixture_only",
    ),
    GroundingSubject(
        subject_id="typescript.nodejs", display_name="Node.js", subject_kind="platform",
        parent_subject_id="route.typescript-javascript", language_ids=("typescript", "javascript"),
        aliases=("nodejs",), source_trust_policy="official",
        required_facets=("server-runtime", "modules", "async"),
        assessment_capabilities=("lesson",), release_state="fixture_only",
    ),
    GroundingSubject(
        subject_id="web.react", display_name="React", subject_kind="framework",
        parent_subject_id="route.web-platform", language_ids=("javascript", "typescript", "html", "css"),
        aliases=("react",), source_trust_policy="official",
        required_facets=("components", "state", "effects"), optional_facets=("accessibility",),
        assessment_capabilities=("lesson",), release_state="fixture_only",
    ),
    GroundingSubject(
        subject_id="web.platform", display_name="Web Platform", subject_kind="platform",
        parent_subject_id="route.web-platform", language_ids=("html", "css"), aliases=("web-apis",),
        source_trust_policy="official", required_facets=("dom", "styling", "accessibility"),
        assessment_capabilities=("lesson",), release_state="fixture_only",
    ),
    GroundingSubject(
        subject_id="sql.postgresql-foundations", display_name="PostgreSQL Foundations", subject_kind="database",
        parent_subject_id="route.sql", language_ids=("sql",), aliases=("postgresql-foundations",),
        source_trust_policy="trusted_de_facto",
        required_facets=("postgresql-dialect", "schema", "transactions"),
        assessment_capabilities=("lesson",), release_state="fixture_only",
    ),
)


def all_grounding_subjects() -> tuple[GroundingSubject, ...]:
    return SUBJECTS


def get_grounding_subject(subject_id_or_alias: str) -> GroundingSubject | None:
    key = subject_id_or_alias.strip().casefold()
    return next((subject for subject in SUBJECTS if key == subject.subject_id or key in
                 {alias.casefold() for alias in subject.aliases}), None)


def subjects_for_public_course_language(course_language: str) -> tuple[GroundingSubject, ...]:
    """Read legacy language grouping, without enabling a new public Subject candidate."""
    language_ids = frozenset(PUBLIC_COURSE_LANGUAGE_MAP.get(course_language, ()))
    if not language_ids:
        return ()
    return tuple(subject for subject in SUBJECTS if subject.subject_id.startswith("route.")
                 and language_ids <= set(subject.language_ids))


# Phase I has no v2 public admission, even if an identity is later declared implemented.
_PUBLIC_SUBJECT_IDS: frozenset[str] = frozenset()


def is_public_subject_candidate(subject_id_or_alias: str) -> bool:
    subject = get_grounding_subject(subject_id_or_alias)
    return (subject is not None and subject.subject_id in _PUBLIC_SUBJECT_IDS
            and subject.release_state in {"implemented", "executable"})


def _component(subject: GroundingSubject, name: str, supported: bool) -> SubjectReleaseState:
    if name not in subject.assessment_capabilities or subject.release_state == "unavailable":
        return "unavailable"
    if subject.release_state == "fixture_only":
        return "fixture_only"  # Fixture content, never a live executor claim.
    if subject.release_state == "planned" or not supported:
        return "planned"
    if subject.release_state == "shadow":
        return "shadow"
    if subject.release_state in {"lesson_only", "static_only"}:
        return subject.release_state
    if name in {"practice", "execution", "tests"} and subject.release_state == "executable":
        return "executable"
    return "implemented"


def capability_projection(subject_id_or_alias: str) -> SubjectCapabilityProjection | None:
    subject = get_grounding_subject(subject_id_or_alias)
    if subject is None:
        return None
    languages = tuple(get_language_capability(language_id) for language_id in subject.language_ids)
    if any(language is None for language in languages):
        return None
    capabilities: tuple[LanguageCapability, ...] = tuple(language for language in languages if language is not None)
    # Source registration does not prove a validated v2 corpus; runtime declarations do not prove live health.
    return SubjectCapabilityProjection(
        subject_id=subject.subject_id, language_ids=subject.language_ids,
        release_state=subject.release_state,
        source_coverage="unavailable" if subject.release_state == "unavailable" else "planned",
        lesson_generation=_component(subject, "lesson", all(c.lesson_generation == "full" for c in capabilities)),
        practice_generation=_component(subject, "practice", all(c.exercise_generation == "executable" for c in capabilities)),
        execution=_component(subject, "execution", all(c.supports_execution for c in capabilities)),
        tests=_component(subject, "tests", all(c.supports_tests for c in capabilities)),
        static_analysis=_component(subject, "static_analysis", all(c.static_analysis == "syntax_only" for c in capabilities)),
        review=_component(subject, "review", all(c.review_feedback == "full" for c in capabilities)),
        public_release=subject.release_state,
        public_course_admissible=is_public_subject_candidate(subject.subject_id)
        and all(c.enabled_for_public_selection for c in capabilities),
    )


def validate_grounding_subject_registry(subjects: Sequence[GroundingSubject] = SUBJECTS) -> tuple[str, ...]:
    """Deterministic validation errors, including for untrusted constructed test registries."""
    errors: list[str] = []
    languages = {language.language_id: language for language in all_language_capabilities()}
    by_id: dict[str, GroundingSubject] = {}
    structurally_valid: list[GroundingSubject] = []
    aliases: set[str] = set()
    for subject in subjects:
        try:
            GroundingSubject.model_validate(subject.model_dump(warnings=False))
        except ValidationError as exc:
            for field in sorted({str(issue["loc"][0]) for issue in exc.errors() if issue["loc"]}):
                errors.append(f"Subject {subject.subject_id} has invalid {field}")
            for issue in exc.errors():
                if not issue["loc"]:
                    errors.append(str(issue["msg"]))
            # model_copy(update=...) bypasses validation. Never traverse malformed tuples/ids.
            structural = {"subject_id", "parent_subject_id", "language_ids", "aliases",
                          "required_facets", "optional_facets", "runtime_profile_keys",
                          "assessment_capabilities"}
            if any(issue["loc"] and issue["loc"][0] in structural for issue in exc.errors()):
                continue
        structurally_valid.append(subject)
        if subject.subject_id in by_id:
            errors.append(f"Duplicate Subject id: {subject.subject_id}")
        else:
            by_id[subject.subject_id] = subject
        for alias in (subject.subject_id, *subject.aliases):
            key = alias.strip().casefold()
            if not key or key in aliases:
                errors.append(f"Duplicate Subject alias: {key}")
            aliases.add(key)
        for language_id in subject.language_ids:
            if language_id not in languages:
                errors.append(f"Subject {subject.subject_id} has unknown language: {language_id}")
        unknown = (set(subject.required_facets) | set(subject.optional_facets)) - KNOWN_SUBJECT_FACETS
        if unknown:
            errors.append(f"Subject {subject.subject_id} has unknown facets: {', '.join(sorted(unknown))}")
        allowed_runtimes = {languages[language_id].runner_key for language_id in subject.language_ids
                            if language_id in languages}
        for runtime in subject.runtime_profile_keys:
            if runtime not in {"browser", "python", "node", "sql", "compiled"} or runtime not in allowed_runtimes:
                errors.append(f"Subject {subject.subject_id} has incompatible runtime: {runtime}")
        if subject.release_state == "executable" and (
            "execution" not in subject.assessment_capabilities or not subject.runtime_profile_keys
        ):
            errors.append(f"Subject {subject.subject_id} has inconsistent executable release state")
        if subject.release_state in {"implemented", "executable", "lesson_only", "static_only"}:
            known_languages = [languages[language_id] for language_id in subject.language_ids
                               if language_id in languages]
            if "lesson" in subject.assessment_capabilities and (
                not known_languages or not all(language.lesson_generation == "full" for language in known_languages)
            ):
                errors.append(f"Subject {subject.subject_id} cannot claim full lesson support")
            if "practice" in subject.assessment_capabilities and (
                not known_languages or not all(language.exercise_generation == "executable" for language in known_languages)
            ):
                errors.append(f"Subject {subject.subject_id} cannot claim practice support")
            if "static_analysis" in subject.assessment_capabilities and (
                not known_languages or not all(language.static_analysis == "syntax_only" for language in known_languages)
            ):
                errors.append(f"Subject {subject.subject_id} cannot claim static analysis support")
            if "review" in subject.assessment_capabilities and (
                not known_languages or not all(language.review_feedback in {"full", "static_only"}
                                               for language in known_languages)
            ):
                errors.append(f"Subject {subject.subject_id} cannot claim review support")
            if "execution" in subject.assessment_capabilities and (
                not subject.runtime_profile_keys or not known_languages
                or not all(language.supports_execution for language in known_languages)
            ):
                errors.append(f"Subject {subject.subject_id} cannot claim executable language support")
            if "tests" in subject.assessment_capabilities and (
                not known_languages or not all(language.supports_tests for language in known_languages)
            ):
                errors.append(f"Subject {subject.subject_id} cannot claim test support")
    # Both parent lookup and graph traversal use only structurally checked entries.
    for subject in structurally_valid:
        if subject.parent_subject_id and subject.parent_subject_id not in by_id:
            errors.append(f"Subject {subject.subject_id} has unknown parent: {subject.parent_subject_id}")
        seen: set[str] = set()
        current = subject
        while current.parent_subject_id and current.parent_subject_id in by_id:
            if current.subject_id in seen:
                errors.append(f"Subject {subject.subject_id} has parent cycle")
                break
            seen.add(current.subject_id)
            parent = by_id[current.parent_subject_id]
            if not set(current.language_ids) & set(parent.language_ids):
                errors.append(f"Subject {current.subject_id} has incompatible parent languages")
            current = parent
    return tuple(errors)
