from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

import app.db.schema as schema
from app.db.schema.governance import CandidateEditFacts


@pytest.fixture
def governed_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    legacy = ("020_second.sql", "010_first.sql")
    frozen = frozenset(legacy + schema.SCHEMA_FORWARD_FRAGMENT_NAMES)
    for name in frozen | set(schema.SCHEMA_DRAFT_FILE_NAMES):
        (tmp_path / name).write_text("SELECT 1;\n", encoding="utf-8")
    monkeypatch.setattr(schema, "SCHEMA_DIRECTORY", tmp_path)
    monkeypatch.setattr(schema, "SCHEMA_FRAGMENT_NAMES", legacy)
    monkeypatch.setattr(schema, "SCHEMA_FROZEN_FILE_NAMES", frozen)
    monkeypatch.setattr(schema, "SCHEMA_CANDIDATE_FACTS", {})
    return tmp_path


def inventory_rows() -> dict[str, dict[str, object]]:
    rows = cast(list[dict[str, object]], schema.schema_migration_inventory()["migrations"])
    return {str(row["name"]): row for row in rows}


def test_current_inventory_is_explicit_frozen_history_not_target_readiness() -> None:
    inventory = schema.schema_migration_inventory()
    assert json.loads(json.dumps(inventory)) == inventory
    assert inventory["target_database_installation"] == "not_observed"
    assert inventory["counts"] == {
        "installed_frozen": 167, "candidate": 0, "non_executable_draft": 1,
    }
    assert inventory["selected_fragment_names"] == list(schema.SCHEMA_FRAGMENT_NAMES)
    assert len(schema.SCHEMA_FRAGMENT_NAMES) == 163
    assert schema.SCHEMA_FROZEN_FILE_NAMES == frozenset(
        schema.SCHEMA_FRAGMENT_NAMES + schema.SCHEMA_FORWARD_FRAGMENT_NAMES
    )
    rows = inventory_rows()
    draft = rows[schema.SCHEMA_DRAFT_FILE_NAMES[0]]
    assert draft["lifecycle"] == "non_executable_draft"
    assert draft["execution_plans"] == []
    assert draft["in_place_editable"] is False
    for name in schema.SCHEMA_FROZEN_FILE_NAMES:
        assert rows[name]["lifecycle"] == "installed_frozen"
        assert rows[name]["in_place_editable"] is False
        assert rows[name]["candidate_facts"] is None


@pytest.mark.parametrize("storage_check", [False, True])
def test_inventory_preserves_fixed_forward_plan(storage_check: bool) -> None:
    inventory = schema.schema_migration_inventory(
        contract=schema.COMPLETION_CONTRACT_ID, storage_check=storage_check,
    )
    expected = schema.VALIDATION_FORWARD_FRAGMENT_NAMES if storage_check else schema.RUNTIME_FORWARD_FRAGMENT_NAMES
    assert inventory["selected_fragment_names"] == list(expected)
    validation = inventory_rows()["600_completion_non_b1d_validation.sql"]
    assert validation["execution_plans"] == [f"{schema.COMPLETION_CONTRACT_ID}:validation"]


@pytest.mark.parametrize(
    ("installed", "pinned", "promised", "blockers"),
    [
        (False, False, False, []),
        (None, False, False, ["installed_anywhere_unknown"]),
        (False, None, False, ["external_pin_unknown"]),
        (False, False, None, ["freeze_commitment_unknown"]),
        (True, False, False, ["installed_anywhere_confirmed"]),
        (False, True, False, ["external_pin_confirmed"]),
        (False, False, True, ["freeze_commitment_confirmed"]),
        (None, None, None, ["installed_anywhere_unknown", "external_pin_unknown", "freeze_commitment_unknown"]),
    ],
)
def test_candidate_edit_requires_three_explicit_negative_facts(
    governed_inventory: Path, monkeypatch: pytest.MonkeyPatch,
    installed: bool | None, pinned: bool | None, promised: bool | None,
    blockers: list[str],
) -> None:
    # A lower number than the frozen forwards is still not a freeze boundary.
    name = "015_fixture_candidate.sql"
    (governed_inventory / name).write_text("SELECT 'candidate';\n", encoding="utf-8")
    monkeypatch.setattr(schema, "SCHEMA_CANDIDATE_FACTS", {name: CandidateEditFacts(
        installed_anywhere=installed, external_pin=pinned, freeze_commitment=promised,
    )})
    row = inventory_rows()[name]
    assert row["lifecycle"] == "candidate"
    assert row["execution_plans"] == []
    assert row["edit_blockers"] == blockers
    assert row["in_place_editable"] is (not blockers)
    assert row["candidate_facts"] == {
        "installed_anywhere": installed, "external_pin": pinned, "freeze_commitment": promised,
    }
    assert name not in {fragment.name for fragment in schema.load_schema_fragments()}
    assert name not in schema.SCHEMA_FROZEN_FILE_NAMES


def test_candidate_facts_have_no_implicit_negative_defaults() -> None:
    with pytest.raises(TypeError):
        CandidateEditFacts()  # type: ignore[call-arg]


def test_explicit_plan_membership_and_rehearsal_do_not_freeze_candidate(
    governed_inventory: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "015_fixture_candidate.sql"
    path = governed_inventory / name
    path.write_text("SELECT 'first candidate';\n", encoding="utf-8")
    monkeypatch.setattr(schema, "SCHEMA_CANDIDATE_FACTS", {name: CandidateEditFacts(
        installed_anywhere=False, external_pin=False, freeze_commitment=False,
    )})
    legacy = schema.SCHEMA_FRAGMENT_NAMES
    # Only the original manifest explicitly selects execution; metadata does not.
    monkeypatch.setattr(schema, "SCHEMA_FRAGMENT_NAMES", legacy + (name,))
    for contents in ("SELECT 'rehearsal';\n", "SELECT 'corrected candidate';\n"):
        path.write_text(contents, encoding="utf-8")
        fragments = schema.load_schema_fragments()
        assert tuple(fragment.name for fragment in fragments) == legacy + (name,)
        assert fragments[-1].sql == contents
        row = inventory_rows()[name]
        assert row["lifecycle"] == "candidate"
        assert row["execution_plans"] == ["legacy"]
        assert row["in_place_editable"] is True
    assert name not in schema.SCHEMA_FROZEN_FILE_NAMES


def test_new_execution_manifest_entry_requires_explicit_lifecycle(
    governed_inventory: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "015_fixture_candidate.sql"
    (governed_inventory / name).write_text("SELECT 1;\n", encoding="utf-8")
    monkeypatch.setattr(schema, "SCHEMA_FRAGMENT_NAMES", schema.SCHEMA_FRAGMENT_NAMES + (name,))
    with pytest.raises(RuntimeError, match="SCHEMA_LIFECYCLE_UNCLASSIFIED"):
        schema.load_schema_fragments()


def test_frozen_file_cannot_be_silently_removed_from_its_manifest(
    governed_inventory: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schema, "SCHEMA_FRAGMENT_NAMES", schema.SCHEMA_FRAGMENT_NAMES[:-1])
    with pytest.raises(RuntimeError, match="SCHEMA_FROZEN_FILES_REMOVED_FROM_MANIFEST"):
        schema.schema_migration_inventory()


@pytest.mark.parametrize("classification", ["frozen", "draft"])
def test_candidate_cannot_overlap_frozen_or_draft_classifications(
    governed_inventory: Path, monkeypatch: pytest.MonkeyPatch, classification: str,
) -> None:
    name = schema.SCHEMA_FRAGMENT_NAMES[0] if classification == "frozen" else schema.SCHEMA_DRAFT_FILE_NAMES[0]
    monkeypatch.setattr(schema, "SCHEMA_CANDIDATE_FACTS", {name: CandidateEditFacts(
        installed_anywhere=False, external_pin=False, freeze_commitment=False,
    )})
    with pytest.raises(RuntimeError, match="SCHEMA_LIFECYCLE_CLASSIFICATIONS_OVERLAP"):
        schema.schema_migration_inventory()


def test_missing_registered_candidate_fails_loader_and_inventory(
    governed_inventory: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schema, "SCHEMA_CANDIDATE_FACTS", {"missing_candidate.sql": CandidateEditFacts(
        installed_anywhere=None, external_pin=None, freeze_commitment=None,
    )})
    for consumer in (schema.load_schema_fragments, schema.schema_migration_inventory):
        with pytest.raises(RuntimeError, match="schema candidate file files are missing"):
            consumer()


def test_inventory_does_not_read_sql_contents(
    governed_inventory: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_read(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("inventory must not read SQL contents")

    monkeypatch.setattr(Path, "read_text", forbidden_read)
    assert schema.schema_migration_inventory()["target_database_installation"] == "not_observed"


def test_inventory_uses_same_unknown_file_rejection_as_loader(governed_inventory: Path) -> None:
    (governed_inventory / "unknown.sql").write_text("SELECT 1;\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="schema fragment files are not declared"):
        schema.schema_migration_inventory()
