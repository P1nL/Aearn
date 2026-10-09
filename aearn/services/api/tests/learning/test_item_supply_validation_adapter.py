from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.learning.item_bank.compiler import LearningItemSourceLoader, curated_learning_item_source_root
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.validation_adapter import (
    CandidateExecutionEvidenceV2, CandidateProbeV2, validate_candidate,
)
from app.services.learning.item_supply.validators.profiles import required_probes


def source(name: str = "python-variables-rebinding-prediction-v1.json") -> LearningItemSourceV1:
    return LearningItemSourceLoader().load(curated_learning_item_source_root(), name).source


def modified(item: LearningItemSourceV1, mutate) -> LearningItemSourceV1:
    payload = item.model_dump(mode="json")
    mutate(payload)
    return LearningItemSourceV1.model_validate(payload)


class SyntheticPort:
    def __init__(self, *, wrong_hash: bool = False, trusted: bool = True) -> None:
        self.wrong_hash = wrong_hash
        self.trusted = trusted

    def validate(self, item: LearningItemSourceV1) -> CandidateExecutionEvidenceV2:
        return CandidateExecutionEvidenceV2(
            source_hash="0" * 64 if self.wrong_hash else item.source_hash,
            content_hash=item.content_hash, kind=item.public.kind.value,
            language=item.blueprint.language_id, runtime_profile_id=item.blueprint.runtime_profile_id,
            dialect="sqlite" if item.public.kind.value == "sql" else None,
            runner_version="synthetic_runner_v1", scorer_version="synthetic_scorer_v1",
            run_id=uuid4(), mode="synthetic", isolation="synthetic",
            probes=tuple(CandidateProbeV2(name=name, status="passed", proof_hash=canonical_hash(name), profile_version="synthetic_profile_v1") for name in required_probes(item)),
        )

    def verify(self, evidence, item) -> bool:
        return self.trusted


def test_python_knowledge_reuses_all_legacy_checks() -> None:
    result = validate_candidate(source())
    assert result.state == "machine_verified"
    assert result.mode == "static"
    assert result.legacy_receipt is not None
    assert len(result.checks) == 11
    assert not any(check.status in {"failed", "pending"} for check in result.checks)


def test_invalid_knowledge_answer_rejected() -> None:
    item = modified(source("python-variables-rebinding-remediation-v2.json"), lambda p: p["private"]["content"].update(accepted_answers=["nonexistent_option"]))
    result = validate_candidate(item)
    assert result.state == "rejected"
    assert "knowledge_answer_not_unique" in result.safe_reasons


def test_sql_does_not_call_host_runner(monkeypatch) -> None:
    from app.services.learning.item_bank import validation

    def forbidden(*args, **kwargs):
        pytest.fail("host runner must not execute")

    monkeypatch.setattr(validation, "execute_sql_workspace_query", forbidden)
    result = validate_candidate(source("sql-filter-track-v2.yaml"))
    assert result.state == "blocked"
    assert result.safe_reasons == ("trusted_execution_unavailable",)
    assert result.legacy_receipt is None
    assert sum(check.status == "pending" for check in result.checks) == 3


def test_sql_hidden_dataset_reuse_rejected() -> None:
    item = modified(source("sql-filter-track-v2.yaml"), lambda p: p["private"]["content"]["tests"][1].update(dataset=p["public"]["content"]["public_dataset"]))
    result = validate_candidate(item)
    assert result.state == "rejected"
    assert "sql_public_hidden_dataset_reused" in result.safe_reasons


def test_sql_write_rejected_before_execution() -> None:
    item = modified(source("sql-filter-track-v2.yaml"), lambda p: p["private"]["content"].update(standard_query="DELETE FROM learners;"))
    result = validate_candidate(item)
    assert result.state == "rejected"
    assert "sql_query_not_read_only" in result.safe_reasons


def test_synthetic_probe_never_becomes_machine_verified() -> None:
    result = validate_candidate(source("sql-filter-track-v2.yaml"), execution_port=SyntheticPort())
    assert result.state == "blocked"
    assert result.mode == "synthetic"
    assert result.execution_evidence is not None
    assert result.safe_reasons == ("trusted_isolation_unavailable",)


def test_execution_stale_hash_rejected() -> None:
    result = validate_candidate(source("sql-filter-track-v2.yaml"), execution_port=SyntheticPort(wrong_hash=True))
    assert result.state == "rejected"
    assert result.safe_reasons == ("execution_receipt_identity_mismatch",)


def test_untrusted_receipt_blocked() -> None:
    result = validate_candidate(source("sql-filter-track-v2.yaml"), execution_port=SyntheticPort(trusted=False))
    assert result.state == "blocked"
    assert result.safe_reasons == ("execution_receipt_untrusted",)


def test_wrong_dialect_cannot_bypass_strict_source_revalidation() -> None:
    item = source("sql-filter-track-v2.yaml")
    forged_content = item.public.content.model_copy(update={"dialect": "postgres"})
    forged = item.model_copy(update={"public": item.public.model_copy(update={"content": forged_content})})
    with pytest.raises(ValueError, match="candidate_source_schema_invalid"):
        validate_candidate(forged)


def test_python_code_without_trusted_executor_is_blocked() -> None:
    item = source("html-browser-active-card-v1.yaml")
    def to_python(p):
        p["blueprint"].update(language_id="python", runtime_profile_id="python_stdout_test", required_capabilities=["python"])
        p["public"]["content"].update(language_id="python", editor_language="python", exercise_type="code_completion", browser_rule_family=None, starter_code="x = 0\nprint(x)", code_blanks=[{"blank_key": "value", "expected_concept": "assignment", "acceptable_patterns": [{"type": "literal", "value": "1"}], "is_core": True}], required_patterns=[], preview_html={})
        p["private"]["content"].update(standard_answer="x = 1\nprint(x)")
    result = validate_candidate(modified(item, to_python))
    assert result.state == "blocked"
    assert "trusted_execution_unavailable" in result.safe_reasons


def test_short_text_cannot_establish_independent_mastery() -> None:
    item = modified(source(), lambda p: p["public"]["content"].update(response_kind="short_text", options=[]))
    result = validate_candidate(item)
    assert result.state == "blocked"
    assert result.safe_reasons == ("short_text_independent_scoring_unavailable",)
    assert result.legacy_receipt is not None


def test_execution_exception_is_safe_and_blocked() -> None:
    class FailingPort(SyntheticPort):
        def validate(self, item):
            raise RuntimeError("private_answer_or_provider_body")

    result = validate_candidate(source("sql-filter-track-v2.yaml"), execution_port=FailingPort())
    assert result.state == "blocked"
    assert result.safe_reasons == ("execution_receipt_untrusted",)
    assert "private_answer" not in result.model_dump_json()
