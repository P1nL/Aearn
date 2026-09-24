import pytest
from pydantic import ValidationError

from app.services.grounding.autonomous.contracts import (
    ContentCapture, LearningMaterialDemand, RagEvidenceRequest, SourceCandidate,
    SourceDiscoverySuggestion, SourcePreference, SubjectScope, revalidate,
)
from tests.grounding.rag_material_helpers import H, SCOPE, demand


def test_strict_bounded_demand_and_subject():
    with pytest.raises(ValidationError):
        LearningMaterialDemand.model_validate({**demand().model_dump(), "actor_id": "admin"})
    with pytest.raises(ValidationError):
        SubjectScope(subject_id="route.python", subject_version="3.12", facets=("queries",))
    with pytest.raises(ValidationError):
        SubjectScope(subject_id="route.python", subject_version="3.12", facets=("syntax", "syntax"))
    with pytest.raises(ValidationError):
        SourcePreference(kind="site", value="x" * 161, reason="prefer")
    with pytest.raises(ValidationError):
        SourceDiscoverySuggestion(demand_hash=H, query_terms=("SQL; DROP TABLE",), reason="coverage_gap")
    with pytest.raises(ValidationError):
        SourceDiscoverySuggestion(demand_hash=H, query_terms=("Python", "Python"), reason="coverage_gap")


def test_model_copy_and_construct_rechecked():
    with pytest.raises(ValidationError):
        revalidate(demand().model_copy(update={"scope": SCOPE.model_copy(update={"facets": ("queries",)})}),
                   LearningMaterialDemand)
    with pytest.raises(ValidationError):
        revalidate(LearningMaterialDemand.model_construct(**{**demand().model_dump(exclude={"scope"}),
                                                       "scope": SCOPE, "purpose": "admin"}),
                   LearningMaterialDemand)


def test_candidate_capture_and_immutable_revision_not_body_grants():
    none = ContentCapture(kind="none", captured_bytes=0)
    SourceCandidate(kind="landing", demand_hash=H, scope=SCOPE, url="https://example.org/intro", discovery_receipt_id="search.001", capture=none)
    with pytest.raises(ValidationError):
        ContentCapture(kind="prefix", captured_bytes=100, full_sha256=H)
    with pytest.raises(ValidationError):
        SourceCandidate(kind="repo_file", demand_hash=H, scope=SCOPE, url="https://github.com/x/y/blob/main/a.py",
                        discovery_receipt_id="search.001", capture=none)
    with pytest.raises(ValidationError):
        SourceCandidate(kind="landing", demand_hash=H, scope=SCOPE, url="https://example.org/intro", discovery_receipt_id="search.001",
                        capture=ContentCapture(kind="full", captured_bytes=10, full_sha256=H))


def test_formal_request_is_handle_only_no_url_sql_or_command():
    request = RagEvidenceRequest(scope=SCOPE, demand_hash=H, purpose="main_teaching",
                                 source_handles=("source.blog",))
    for forbidden in ("url", "db_target", "sql", "command", "source_candidate"):
        with pytest.raises(ValidationError):
            RagEvidenceRequest.model_validate({**request.model_dump(), forbidden: "https://example.org"})
    with pytest.raises(ValidationError):
        RagEvidenceRequest(scope=SCOPE, demand_hash=H, purpose="main_teaching",
                           source_handles=("https://example.org",))
    with pytest.raises(ValidationError):
        RagEvidenceRequest(scope=SCOPE, demand_hash=H, purpose="main_teaching",
                           source_handles=("source.blog", "source.blog"))


def test_preference_rank_rejects_unbounded_list_not_truncates_to_eight():
    from app.services.grounding.autonomous.source_preferences import preference_rank

    prefs = tuple(SourcePreference(kind="author", value=f"author{i}", reason="preference") for i in range(9))
    with pytest.raises(ValueError):
        preference_rank("source.blog", "example.org", "author8", prefs)


@pytest.mark.parametrize("kind", ["document", "landing", "repo_page", "repo_file"])
@pytest.mark.parametrize("repo_commit,repo_path", [
    (None, None), ("a" * 40, None), (None, "chapter/intro.md"), ("a" * 40, "chapter/intro.md"),
], ids=["neither", "commit-only", "path-only", "both"])
@pytest.mark.parametrize("via_copy", [False, True], ids=["constructor", "copy-boundary"])
def test_candidate_repo_coordinates_match_kind(kind, repo_commit, repo_path, via_copy):
    fields = dict(kind=kind, demand_hash=H, scope=SCOPE, url="https://example.org/material",
                  discovery_receipt_id="search.001", capture=ContentCapture(kind="none", captured_bytes=0))
    coordinates = dict(repo_commit=repo_commit, repo_path=repo_path)
    valid = ((repo_commit is not None and repo_path is not None) if kind == "repo_file"
             else repo_commit is None and repo_path is None)

    def validate():
        if via_copy:
            initial = dict(repo_commit="a" * 40, repo_path="chapter/intro.md") if kind == "repo_file" else {}
            candidate = SourceCandidate(**fields, **initial).model_copy(update=coordinates)
            return revalidate(candidate, SourceCandidate)
        return SourceCandidate(**fields, **coordinates)

    if valid:
        result = validate()
        assert result.repo_commit == repo_commit and result.repo_path == repo_path
    else:
        with pytest.raises(ValidationError):
            validate()
