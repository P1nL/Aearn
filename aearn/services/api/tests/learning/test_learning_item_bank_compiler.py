from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.learning.item_bank.compiler import (
    LearningItemCompiler,
    LearningItemSourceError,
    LearningItemSourceLoader,
    compile_curated_learning_item_catalog,
    curated_learning_item_source_root,
)
from app.services.learning.item_bank.contracts import (
    REQUIRED_LEARNING_ITEM_VALIDATION_CHECKS,
    LearningItemSourceV1,
)
from app.services.learning.item_bank.validation import validate_learning_item


NEGATIVE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "learning_item_bank" / "negative"


def _failed_codes(path: Path) -> set[str]:
    compiled = LearningItemCompiler().compile_file(path.parent, path.name)
    return {
        item.safe_code
        for item in compiled.validation.checks
        if item.status == "failed" and item.safe_code is not None
    }


def test_curated_catalog_compiles_all_minimum_kinds_deterministically() -> None:
    first = compile_curated_learning_item_catalog()
    second = compile_curated_learning_item_catalog()

    assert first == second
    assert first.digest == second.digest
    assert len(first.items) == 5
    assert {item.loaded.source.public.kind.value for item in first.items} == {
        "code",
        "sql",
        "demo",
        "knowledge_check",
        "model_review",
    }
    assert all(item.validation.passed for item in first.items)
    assert all(
        tuple(check.check_type for check in item.validation.checks)
        == REQUIRED_LEARNING_ITEM_VALIDATION_CHECKS
        for item in first.items
    )
    assert len({item.identity.version.handle for item in first.items}) == 5


@pytest.mark.parametrize("name", ["duplicate-key.json", "duplicate-key.yaml"])
def test_loader_rejects_duplicate_json_and_yaml_keys(name: str) -> None:
    with pytest.raises(LearningItemSourceError) as exc_info:
        LearningItemSourceLoader().load(NEGATIVE_ROOT, name)

    assert exc_info.value.code == "source_duplicate_key"


@pytest.mark.parametrize(
    ("name", "safe_code"),
    [
        ("malicious-markdown.json", "markdown_unsafe"),
        ("hint-answer-leak.json", "hint_answer_leakage"),
        ("difficulty-mismatch.json", "difficulty_profile_mismatch"),
        ("knowledge-ambiguous.json", "knowledge_answer_not_unique"),
        ("starter-passes.json", "starter_already_passing"),
        ("sql-unsafe.json", "sql_query_not_read_only"),
        ("demo-event-mismatch.json", "demo_event_contract_mismatch"),
        ("model-review-scorer-mismatch.json", "model_review_scorer_mismatch"),
    ],
)
def test_negative_sources_produce_safe_pure_receipts(name: str, safe_code: str) -> None:
    path = NEGATIVE_ROOT / name
    first = LearningItemCompiler().compile_file(NEGATIVE_ROOT, name)
    second = LearningItemCompiler().compile_file(NEGATIVE_ROOT, name)

    assert safe_code in _failed_codes(path)
    assert first.validation == second.validation
    assert first.validation.receipt_hash == second.validation.receipt_hash
    assert first.validation.passed is False


def test_canonical_raw_hash_normalizes_eol_while_preserving_exact_bytes(tmp_path: Path) -> None:
    source_path = curated_learning_item_source_root() / "knowledge-class-attribute-v1.json"
    text = source_path.read_text(encoding="utf-8")
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_bytes(text.encode("utf-8"))
    right.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))

    left_item = LearningItemCompiler().compile_file(tmp_path, left.name)
    right_item = LearningItemCompiler().compile_file(tmp_path, right.name)

    assert left_item.loaded.source_bytes_hash != right_item.loaded.source_bytes_hash
    assert left_item.loaded.raw_source_hash == right_item.loaded.raw_source_hash
    assert left_item.loaded.source_payload_hash == right_item.loaded.source_payload_hash
    assert left_item.identity == right_item.identity


def test_loader_enforces_utf8_size_and_root_relative_paths(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_bytes(b"\xff\xfe")
    with pytest.raises(LearningItemSourceError) as encoding_error:
        LearningItemSourceLoader().load(tmp_path, invalid.name)
    assert encoding_error.value.code == "source_encoding_invalid"

    large = tmp_path / "large.json"
    large.write_text(json.dumps({"value": "x" * 64}), encoding="utf-8")
    with pytest.raises(LearningItemSourceError) as size_error:
        LearningItemSourceLoader(max_source_bytes=16).load(tmp_path, large.name)
    assert size_error.value.code == "source_file_too_large"

    with pytest.raises(LearningItemSourceError) as path_error:
        LearningItemSourceLoader().load(tmp_path, "../outside.json")
    assert path_error.value.code == "source_path_invalid"


@pytest.mark.parametrize(
    ("source_name", "runtime_profile"),
    [
        ("sql-filter-track-v2.yaml", "browser_preview"),
        ("demo-click-event-v1.json", "sql_query_test"),
    ],
)
def test_kind_specific_runtime_profiles_fail_closed(
    source_name: str,
    runtime_profile: str,
) -> None:
    compiled = LearningItemCompiler().compile_file(
        curated_learning_item_source_root(),
        source_name,
        require_valid=True,
    )
    payload = compiled.loaded.source.model_dump(mode="json")
    payload["blueprint"]["runtime_profile_id"] = runtime_profile  # type: ignore[index]
    source = LearningItemSourceV1.model_validate(payload)

    receipt = validate_learning_item(source)

    assert receipt.passed is False
    assert "runtime_profile_mismatch" in {
        check.safe_code for check in receipt.checks if check.status == "failed"
    }


def test_sql_v2_rejects_mutating_standard_query_before_runner_execution() -> None:
    compiled = LearningItemCompiler().compile_file(
        curated_learning_item_source_root(),
        "sql-filter-track-v2.yaml",
        require_valid=True,
    )
    payload = compiled.loaded.source.model_dump(mode="json")
    payload["private"]["content"]["standard_query"] = (  # type: ignore[index]
        "UPDATE learners SET track = 'sql';"
    )
    source = LearningItemSourceV1.model_validate(payload)

    receipt = validate_learning_item(source)

    assert receipt.passed is False
    failed = {
        check.check_type.value: check.safe_code
        for check in receipt.checks
        if check.status == "failed"
    }
    assert failed["runtime_or_event"] == "sql_query_not_read_only"
    assert failed["standard_answer"] == "standard_answer_failed"


def test_sql_v2_requires_foreign_keys_to_reference_one_matching_primary_key() -> None:
    compiled = LearningItemCompiler().compile_file(
        curated_learning_item_source_root(),
        "sql-filter-track-v2.yaml",
        require_valid=True,
    )
    payload = compiled.loaded.source.model_dump(mode="json")
    payload["public"]["content"]["tables"][0]["columns"][0]["primary_key"] = False  # type: ignore[index]

    with pytest.raises(ValueError, match="matching published primary key"):
        LearningItemSourceV1.model_validate(payload)


def test_loader_rejects_symlinked_sources_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are not available in this environment")

    with pytest.raises(LearningItemSourceError) as exc_info:
        LearningItemSourceLoader().load(tmp_path, link.name)
    assert exc_info.value.code == "source_symlink_forbidden"
