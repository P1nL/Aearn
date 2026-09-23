from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from app.services.grounding.subject_contracts import GroundingSubject, SubjectCapabilityProjection
from app.services.grounding.subject_registry import (
    all_grounding_subjects,
    capability_projection,
    get_grounding_subject,
    is_public_subject_candidate,
    subjects_for_public_course_language,
    validate_grounding_subject_registry,
)
from app.services.runners.language_capabilities import PUBLIC_COURSE_LANGUAGE_MAP


def test_registry_identities_and_phase_one_admission() -> None:
    subjects = all_grounding_subjects()
    assert len(subjects) == 10
    assert {subject.subject_id for subject in subjects[:4]} == {
        "route.python", "route.typescript-javascript", "route.web-platform", "route.sql",
    }
    assert {subject.subject_id for subject in subjects[4:]} == {
        "python.ai-applications", "python.fastapi", "typescript.nodejs",
        "web.react", "web.platform", "sql.postgresql-foundations",
    }
    assert all(subject.release_state == "fixture_only" for subject in subjects[4:])
    assert all(subject.version_policy == "operator_locked" for subject in subjects)
    assert validate_grounding_subject_registry() == ()
    assert all(not is_public_subject_candidate(subject.subject_id) for subject in subjects)
    assert not is_public_subject_candidate("fastapi")


def test_aliases_and_legacy_html_css_are_read_only() -> None:
    assert get_grounding_subject("  FASTAPI ") == get_grounding_subject("python.fastapi")
    assert get_grounding_subject("missing") is None
    assert subjects_for_public_course_language("html_css") == (get_grounding_subject("route.web-platform"),)
    assert subjects_for_public_course_language("python") == (get_grounding_subject("route.python"),)
    assert subjects_for_public_course_language("rust") == ()
    assert PUBLIC_COURSE_LANGUAGE_MAP["html_css"] == ("html", "css")
    assert len(PUBLIC_COURSE_LANGUAGE_MAP) == 8


def test_contract_rejects_extra_mutation_unknown_facet_and_runtime() -> None:
    original = all_grounding_subjects()[4]
    with pytest.raises(ValidationError):
        GroundingSubject.model_validate({**original.model_dump(), "publicly_selectable": True})
    with pytest.raises(ValidationError):
        GroundingSubject.model_validate({**original.model_dump(), "runtime_profile_keys": ("arbitrary",)})
    with pytest.raises(ValidationError):
        GroundingSubject.model_validate({**original.model_dump(), "version_policy": "rolling"})
    with pytest.raises(ValidationError):
        GroundingSubject.model_validate({**original.model_dump(), "assessment_capabilities": ("magic",)})
    with pytest.raises(ValidationError):
        GroundingSubject.model_validate({**original.model_dump(), "required_facets": ("unknown",)})
    with pytest.raises(ValidationError):
        GroundingSubject.model_validate({**original.model_dump(), "release_state": "public"})
    with pytest.raises((ValidationError, FrozenInstanceError)):
        original.subject_id = "changed"  # type: ignore[misc]


def test_registry_validation_reports_graph_alias_language_runtime_and_release_errors() -> None:
    base = all_grounding_subjects()[4]
    other = all_grounding_subjects()[5]
    a = base.model_copy(update={"parent_subject_id": other.subject_id})
    b = other.model_copy(update={"parent_subject_id": base.subject_id, "aliases": base.aliases})
    errors = validate_grounding_subject_registry((a, b))
    assert any("parent cycle" in error for error in errors)
    assert any("Duplicate Subject alias" in error for error in errors)

    invalid = base.model_copy(update={
        "language_ids": ("unknown",), "required_facets": ("invalid-facet",),
        "runtime_profile_keys": ("compiled",), "release_state": "executable",
        "parent_subject_id": "missing",
    })
    errors = validate_grounding_subject_registry((invalid,))
    for fragment in ("unknown language", "unknown facets", "incompatible runtime", "inconsistent executable", "unknown parent"):
        assert any(fragment in error for error in errors)


def test_projection_is_conservative_and_public_subset_omits_internal_fields() -> None:
    fixture = capability_projection("python.fastapi")
    route = capability_projection("route.python")
    assert fixture is not None and route is not None
    assert fixture.source_coverage == "planned"  # taxonomy does not create a fixture corpus
    assert fixture.lesson_generation == "fixture_only"
    assert fixture.execution == "unavailable"
    assert fixture.public_release == "fixture_only"
    assert fixture.public_course_admissible is False
    assert route.release_state == "shadow"
    assert route.source_coverage == "planned"  # registered sources are not validated v2 coverage
    assert route.execution == "shadow"  # language runner is not Subject readiness
    assert route.public_course_admissible is False
    assert fixture.public_projection().model_dump() == {
        "subject_id": "python.fastapi", "availability": "unavailable",
    }
    with pytest.raises(ValidationError, match="Public Subject admission"):
        SubjectCapabilityProjection.model_validate({**fixture.model_dump(), "public_course_admissible": True})
    assert capability_projection("missing") is None


@pytest.mark.parametrize("state", [
    "implemented", "fixture_only", "shadow", "lesson_only", "static_only", "executable", "planned", "unavailable",
])
def test_projection_contract_represents_all_release_states(state: str) -> None:
    route = capability_projection("route.python")
    assert route is not None
    data = route.model_dump()
    data.update(release_state=state, public_release=state)
    for component in ("lesson_generation", "practice_generation", "execution", "tests", "static_analysis", "review"):
        data[component] = "unavailable"
    projection = SubjectCapabilityProjection.model_validate(data)
    assert projection.release_state == state
    assert projection.public_projection().model_dump().keys() == {"subject_id", "availability"}


def test_strict_contract_rejects_coercion_lists_and_whitespace() -> None:
    data = all_grounding_subjects()[4].model_dump()
    for change in (
        {"subject_id": " python.fastapi"}, {"display_name": "   "},
        {"aliases": (" fastapi",)}, {"language_ids": ["python"]},
        {"assessment_capabilities": (True,)}, {"runtime_profile_keys": (False,)},
        {"subject_kind": True},
    ):
        with pytest.raises(ValidationError):
            GroundingSubject.model_validate({**data, **change})
    route = capability_projection("route.python")
    assert route is not None
    with pytest.raises(ValidationError):
        SubjectCapabilityProjection.model_validate({**route.model_dump(), "public_course_admissible": "false"})


def test_release_constraints_and_projection_never_infer_fixture_execution() -> None:
    fixture = all_grounding_subjects()[4]
    for change in (
        {"assessment_capabilities": ("lesson", "execution")},
        {"assessment_capabilities": ("lesson", "tests")},
        {"runtime_profile_keys": ("python",)},
        {"release_state": "lesson_only", "assessment_capabilities": ("lesson", "practice")},
        {"release_state": "static_only", "assessment_capabilities": ("lesson", "tests")},
        {"release_state": "executable", "assessment_capabilities": ("execution",)},
    ):
        with pytest.raises(ValidationError):
            GroundingSubject.model_validate({**fixture.model_dump(), **change})
    projection = capability_projection("python.fastapi")
    assert projection is not None
    with pytest.raises(ValidationError, match="Fixture cannot claim"):
        SubjectCapabilityProjection.model_validate({**projection.model_dump(), "execution": "fixture_only"})
    with pytest.raises(ValidationError, match="unreleased state"):
        SubjectCapabilityProjection.model_validate({**projection.model_dump(), "lesson_generation": "implemented"})


def test_registry_handles_invalid_model_copy_tuples_without_crashing() -> None:
    subject = all_grounding_subjects()[4]
    malformed = subject.model_copy(update={"aliases": [True]})
    errors = validate_grounding_subject_registry((malformed,))
    assert any("invalid aliases" in error for error in errors)
    assert validate_grounding_subject_registry((malformed,)) == errors


def test_executable_release_requires_language_runner_support() -> None:
    subject = all_grounding_subjects()[4]
    rust = subject.model_copy(update={
        "subject_id": "rust.sample", "language_ids": ("rust",),
        "parent_subject_id": None, "aliases": (), "runtime_profile_keys": ("compiled",),
        "assessment_capabilities": ("execution",), "release_state": "executable",
    })
    errors = validate_grounding_subject_registry((rust,))
    assert any("cannot claim executable language support" in error for error in errors)


def test_registry_rejects_unsupported_assessment_and_id_alias_collision() -> None:
    base = all_grounding_subjects()[4]
    claimed = base.model_copy(update={
        "subject_id": "rust.sample", "language_ids": ("rust",),
        "parent_subject_id": None, "aliases": ("python.ai-applications",),
        "assessment_capabilities": ("lesson",), "release_state": "lesson_only",
    })
    errors = validate_grounding_subject_registry((base, claimed))
    assert any("Duplicate Subject alias: python.ai-applications" in error for error in errors)
    assert any("cannot claim full lesson support" in error for error in errors)
    with pytest.raises(ValidationError):
        GroundingSubject.model_validate({**base.model_dump(), "source_trust_policy": "random_blog"})


def test_projection_rejects_components_exceeding_release_state() -> None:
    route = capability_projection("route.python")
    assert route is not None
    data = route.model_dump()
    for change in (
        {"release_state": "planned", "lesson_generation": "shadow"},
        {"release_state": "unavailable", "lesson_generation": "fixture_only"},
        {"release_state": "lesson_only", "execution": "implemented"},
        {"release_state": "static_only", "execution": "implemented"},
    ):
        with pytest.raises(ValidationError):
            SubjectCapabilityProjection.model_validate({**data, **change})


def test_registry_skips_malformed_parent_in_graph_validation() -> None:
    base = all_grounding_subjects()[0]
    malformed = base.model_copy(update={"parent_subject_id": ["route.sql"]})
    errors = validate_grounding_subject_registry((malformed,))
    assert errors == ("Subject route.python has invalid parent_subject_id",)
    assert validate_grounding_subject_registry((malformed,)) == errors


@pytest.mark.parametrize("malformed_first", [False, True])
def test_registry_parent_checks_ignore_malformed_subject_ids(malformed_first: bool) -> None:
    parent = all_grounding_subjects()[0]
    child = all_grounding_subjects()[4]
    malformed = parent.model_copy(update={"subject_id": ["route.python"]})
    subjects = (malformed, child, parent) if malformed_first else (child, parent, malformed)
    errors = validate_grounding_subject_registry(subjects)
    assert errors == ("Subject ['route.python'] has invalid subject_id",)
    assert validate_grounding_subject_registry(subjects) == errors
    # A malformed entry is not a valid parent even if its intended id looks right.
    assert any("unknown parent: route.python" in error
               for error in validate_grounding_subject_registry((child, malformed)))
