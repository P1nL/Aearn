"""Registry declaration tests, not runtime/source/inventory acceptance."""
from __future__ import annotations

import ast
import builtins
import os
import socket
import subprocess
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.services.learning.item_bank.contracts import (
    LearningItemInteraction,
    LearningItemKind,
    LearningItemPurpose,
    canonical_hash,
)
from app.services.learning.item_supply import exposure, matrix
from app.services.learning.item_supply.matrix import SupportMatrixSnapshot, build_support_matrix
from app.services.runners.language_capabilities import (
    LANGUAGE_CAPABILITIES,
    PUBLIC_COURSE_LANGUAGE_MAP,
)


def test_all_actual_language_fields_are_preserved_verbatim() -> None:
    result = build_support_matrix()
    assert tuple(row.language_id for row in result.languages) == tuple(sorted(LANGUAGE_CAPABILITIES))
    for row in result.languages:
        assert row.model_dump(mode="python") == asdict(LANGUAGE_CAPABILITIES[row.language_id])


def test_public_course_groups_and_aliases_are_not_parallel_language_ids() -> None:
    result = build_support_matrix()
    assert {row.course_language_id: row.language_ids for row in result.public_course_languages} == PUBLIC_COURSE_LANGUAGE_MAP
    languages = {row.language_id: row for row in result.languages}
    assert "html_css" not in languages
    assert languages["html"].current_public_course_language == "html_css"
    assert languages["css"].current_public_course_language == "html_css"
    assert languages["python"].aliases == ("py", "python3")
    assert languages["cpp"].aliases == ("c++",)
    assert "py" not in languages and "c++" not in languages


def test_partial_planned_and_nonpublic_declarations_are_not_ready() -> None:
    result = build_support_matrix()
    languages = {row.language_id: row for row in result.languages}
    assert languages["typescript"].capability_state == "partial"
    assert languages["sql"].capability_state == "partial"
    assert languages["rust"].capability_state == "planned"
    assert not languages["rust"].enabled_for_public_selection
    assert not languages["cpp"].enabled_for_public_selection
    assert result.authority == "declaration_only"
    assert result.runtime_readiness == result.source_readiness == result.inventory_readiness == "not_evaluated"
    assert result.gate_metadata_status == "separate_p0_snapshot"


def test_item_type_declarations_reuse_actual_enums() -> None:
    result = build_support_matrix()
    assert result.item_kinds == tuple(sorted(LearningItemKind, key=lambda item: item.value))
    assert result.item_purposes == tuple(sorted(LearningItemPurpose, key=lambda item: item.value))
    assert result.interactions == tuple(sorted(LearningItemInteraction, key=lambda item: item.value))
    assert all(type(kind) is LearningItemKind for kind in result.item_kinds)


def test_first_batch_is_three_explicit_versioned_targets_not_cartesian_support() -> None:
    rows = build_support_matrix().first_batch_slices
    assert tuple(row.slice_id for row in rows) == ("M01", "M02", "M03")
    assert tuple(row.language_id for row in rows) == ("python", "python", "sql")
    assert tuple(row.item_kind for row in rows) == (
        LearningItemKind.KNOWLEDGE_CHECK, LearningItemKind.CODE, LearningItemKind.SQL,
    )
    assert rows[0].content_contract_target == "single_choice"
    assert rows[0].gate_adapter_status == "existing_contract"
    assert rows[1].gate_adapter_status == rows[2].gate_adapter_status == "planned_adapter"
    assert rows[2].dialect == "sqlite"
    assert all(row.acceptance_status == "not_executed" for row in rows)
    assert all(row.version == "item_supply_first_batch_v1" for row in rows)


def test_snapshot_hash_is_canonical_and_repeatable() -> None:
    first = build_support_matrix()
    assert first.matrix_hash == first.snapshot_hash == canonical_hash(first.model_dump(mode="json"))
    assert first.matrix_hash == build_support_matrix().matrix_hash
    assert len(first.matrix_hash) == 64


def test_registry_iteration_order_does_not_change_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = build_support_matrix().matrix_hash
    monkeypatch.setattr(matrix, "LANGUAGE_CAPABILITIES", dict(reversed(tuple(LANGUAGE_CAPABILITIES.items()))))
    monkeypatch.setattr(matrix, "PUBLIC_COURSE_LANGUAGE_MAP", dict(reversed(tuple(PUBLIC_COURSE_LANGUAGE_MAP.items()))))
    assert build_support_matrix().matrix_hash == expected


def test_registry_change_changes_hash_but_does_not_mutate_old_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    old = build_support_matrix()
    old_hash = old.matrix_hash
    values = LANGUAGE_CAPABILITIES | {"python": replace(LANGUAGE_CAPABILITIES["python"], aliases=("py", "python3", "new-alias"))}
    monkeypatch.setattr(matrix, "LANGUAGE_CAPABILITIES", values)
    assert build_support_matrix().matrix_hash != old_hash
    assert old.matrix_hash == old_hash
    assert old.languages != build_support_matrix().languages


def test_snapshot_and_nested_rows_are_frozen_and_detached() -> None:
    result = build_support_matrix()
    with pytest.raises(ValidationError):
        result.authority = "declaration_only"
    with pytest.raises(ValidationError):
        result.languages[0].capability_state = "planned"
    payload = result.model_dump(mode="python")
    copied = SupportMatrixSnapshot.model_validate(payload)
    payload["languages"][0]["display_name"] = "not the copied name"
    assert copied.languages[0].display_name == result.languages[0].display_name


@pytest.mark.parametrize("field,bad", [
    ("runtime_readiness", "ready"), ("authority", "publication"),
    ("languages", []), ("item_kinds", ("code",)),
    ("matrix_hash", "a" * 64), ("version", "unknown"),
])
def test_strict_snapshot_rejects_mutability_readiness_and_extra_hash(field: str, bad: Any) -> None:
    with pytest.raises(ValidationError):
        SupportMatrixSnapshot.model_validate(build_support_matrix().model_dump(mode="python") | {field: bad})


@pytest.mark.parametrize("field,bad", [
    ("language_id", []), ("enabled_for_public_selection", 1),
    ("aliases", ["mutable"]), ("capability_state", "ready"),
    ("display_name", ""), ("display_name", "x" * 1001),
])
def test_copy_construct_nested_rows_revalidate(field: str, bad: Any) -> None:
    result = build_support_matrix()
    row = result.languages[0]
    for forged in (
        row.model_copy(update={field: bad}),
        type(row).model_construct(**(row.model_dump(mode="python") | {field: bad})),
    ):
        with pytest.raises(ValidationError):
            SupportMatrixSnapshot.model_validate(result.model_copy(update={"languages": (forged,) + result.languages[1:]}))


def test_duplicate_languages_and_unknown_group_members_rejected() -> None:
    result = build_support_matrix()
    with pytest.raises(ValidationError):
        SupportMatrixSnapshot.model_validate(result.model_copy(update={"languages": result.languages + (result.languages[0],)}))
    first = result.public_course_languages[0].model_copy(update={"language_ids": ("unknown",)})
    with pytest.raises(ValidationError):
        SupportMatrixSnapshot.model_validate(result.model_copy(update={"public_course_languages": (first,) + result.public_course_languages[1:]}))


def test_mismatched_registry_identity_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(matrix, "LANGUAGE_CAPABILITIES", LANGUAGE_CAPABILITIES | {"py": LANGUAGE_CAPABILITIES["python"]})
    with pytest.raises(ValueError, match="invalid language registry identity"):
        build_support_matrix()


@pytest.mark.parametrize("field,bad", [
    ("language_id", "sql"), ("dialect", "sqlite"),
    ("gate_contract_target", "fabricated_gate_v1"),
    ("item_kind", LearningItemKind.CODE), ("gate_adapter_status", "planned_adapter"),
])
def test_delivery_slice_identity_cannot_be_rebound(field: str, bad: Any) -> None:
    result = build_support_matrix()
    row = result.first_batch_slices[0].model_copy(update={field: bad})
    with pytest.raises(ValidationError):
        SupportMatrixSnapshot.model_validate(result.model_copy(update={
            "first_batch_slices": (row,) + result.first_batch_slices[1:],
        }))


@pytest.mark.parametrize("values", [
    {"capability_state": "secret-provider-error"}, {"raw_answer": "secret-provider-error"},
])
def test_hash_revalidates_hidden_nested_copy_state_with_safe_errors(values: dict[str, Any]) -> None:
    result = build_support_matrix()
    forged = result.languages[0].model_copy(update=values)
    result = result.model_copy(update={"languages": (forged,) + result.languages[1:]})
    with pytest.raises(ValueError, match="^invalid support snapshot$"):
        _ = result.matrix_hash


def test_pure_functions_make_zero_storage_network_process_or_env_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        calls.append("forbidden IO")
        raise AssertionError("pure supply function attempted IO")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(subprocess, "Popen", forbidden)
        patch.setattr(os, "getenv", forbidden)
        result = build_support_matrix()
        assert len(result.matrix_hash) == 64
        empty = exposure.ExposureSnapshotV1(learner_ref="learner-1", scope_hash="a" * 64)
        assert exposure.check_exposure(
            empty, learner_ref="learner-1", scope_hash="a" * 64,
            item_handle="li:" + "b" * 64, candidate_family_id="family-1", independent=True,
        ).allowed
    assert calls == []


def test_pure_modules_have_only_explicit_safe_imports() -> None:
    allowed = {
        "__future__", "dataclasses", "typing", "pydantic",
        "app.services.grounding.autonomous.contracts",
        "app.services.learning.item_bank.contracts",
        "app.services.runners.language_capabilities",
    }
    for module in (matrix, exposure):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module in allowed
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "eval", "exec", "__import__"}
