"""Offline 500 SQL-shape checks, not PostgreSQL compilation/acceptance.

No connection, bootstrap, provider or dotenv loading. Paired projection tests
import only pure DTO/factory validators. The main session separately owns real
helper negatives and isolated DDL/replay evidence.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from pathlib import Path

import pytest

SCHEMA = Path(__file__).resolve().parents[2] / "app" / "db" / "schema"
SQL = (SCHEMA / "500_learning_item_flexible_public_spec.sql").read_text(encoding="utf-8")
HELPER = SQL.split("AS $helper$", 1)[1].split("$helper$;", 1)[0]
OLD_LOOKUP = (
    "SELECT * INTO facts FROM tutor_item_supply_shared_generation_artifacts "
    "WHERE id=NEW.generation_artifact_id\n"
    "      AND job_id=NEW.job_id AND lease_generation=NEW.lease_generation;"
)
NEW_LOOKUP = (
    "SELECT * INTO facts FROM tutor_item_supply_shared_generation_artifacts "
    "WHERE id=NEW.generation_artifact_id AND "
    "item_supply_internal.shared_stage_original_matches(NEW.job_id,NEW.lease_generation,"
    "NEW.generation_artifact_id,NEW.continuation_binding_hash);"
)
TARGETS = (
    "python-state-update-v1", "python-kc-binding-v1", "sqlite-predicate-order-v1",
)


def _constant(name: str) -> str:
    match = re.search(rf"{name} CONSTANT text := '((?:''|[^'])*)';", SQL)
    assert match is not None
    return match[1].replace("''", "'")


def _md5(body: str) -> str:
    return hashlib.md5(body.encode("utf-8"), usedforsecurity=False).hexdigest()


def _original_body() -> str:
    original = (SCHEMA / "489_learning_item_shared_pipeline.sql").read_text(encoding="utf-8")
    match = re.search(
        r"CREATE OR REPLACE FUNCTION enforce_item_supply_shared_pipeline_artifact\(\)"
        r".*? AS \$\$(.*?)\$\$;", original, re.DOTALL,
    )
    assert match is not None
    return match[1]


def _after_491(body: str) -> str:
    # Verify the checked-in transition, not an invented alternate continuation.
    transition = (SCHEMA / "491_learning_item_shared_continuation.sql").read_text(encoding="utf-8")
    encoded_old = "'" + OLD_LOOKUP.replace("\n", "'||chr(10)||'") + "'"
    assert "old_lookup:=" + encoded_old + ";" in transition
    assert "new_lookup:='" + NEW_LOOKUP + "';" in transition
    assert body.count(OLD_LOOKUP) == 1
    return body.replace(OLD_LOOKUP, NEW_LOOKUP)


def _apply_500_shape(body: str) -> str:
    """Model only the pinned body replacement; this does not execute SQL."""
    if _md5(body) == _constant("revised_md5"):
        return body
    old, new = _constant("old_clause"), _constant("new_clause")
    if _md5(body) != _constant("baseline_md5") or body.count(old) != 1:
        raise ValueError("unexpected baseline")
    revised = body.replace(old, new)
    assert _md5(revised) == _constant("revised_md5")
    return revised


def test_pinned_upstream_bytes_and_effective_prosrc() -> None:
    for name, expected in (
        ("489_learning_item_shared_pipeline.sql", "647026ac146cb333acd1498d044cc889908eefccee7cad8ce2f0c276c4b0274b"),
        ("491_learning_item_shared_continuation.sql", "30aa75a6f81a64e903e8f308d7cf8c61e812be9f8d06b511c2a5b0ec1f4f8066"),
    ):
        assert hashlib.sha256((SCHEMA / name).read_bytes()).hexdigest() == expected
    baseline = _after_491(_original_body())
    assert _md5(baseline) == _constant("baseline_md5")
    revised = _apply_500_shape(baseline)
    assert revised.count(_constant("new_clause")) == 1
    assert revised.replace(_constant("new_clause"), _constant("old_clause")) == baseline
    assert NEW_LOOKUP in revised
    assert OLD_LOOKUP not in revised
    assert "item_author.public_material.v2" in revised
    assert "NEW.request_json->'blueprint' IS DISTINCT FROM NEW.source_json->'blueprint'" in revised


def test_standalone_and_full_ordered_replay_body_shape() -> None:
    revised = _apply_500_shape(_after_491(_original_body()))
    assert _apply_500_shape(revised) == revised
    # Full ordered replay resets 489, then applies 491 and finally 500.
    assert _apply_500_shape(_after_491(_original_body())) == revised
    intervening = sorted(SCHEMA.glob("49[2-9]_*.sql"))
    assert len(intervening) == 8
    for path in intervening:
        assert "enforce_item_supply_shared_pipeline_artifact" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("mutation", ["unpatched_489", "other_guard", "extra_clause", "framing"])
def test_unexpected_prosrc_cannot_receive_a_partial_patch(mutation: str) -> None:
    baseline = _after_491(_original_body())
    unexpected = {
        "unpatched_489": _original_body(),
        "other_guard": baseline.replace("OR control.parent_deadline<=clock_timestamp()", "OR false"),
        "extra_clause": baseline + _constant("old_clause"),
        "framing": baseline + "\n",
    }[mutation]
    with pytest.raises(ValueError, match="unexpected baseline"):
        _apply_500_shape(unexpected)
    assert "md5(body) IS DISTINCT FROM baseline_md5" in SQL
    assert "md5(revised_body) IS DISTINCT FROM revised_md5" in SQL
    assert "SELECT md5(prosrc) FROM pg_proc WHERE oid=function_oid" in SQL
    assert "p.prorettype='pg_catalog.trigger'::regtype AND p.prosecdef" in SQL
    assert "p.proconfig=ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']" in SQL


def test_helper_has_no_authority_or_data_mutation() -> None:
    statements = re.sub(r"--[^\n]*", "", SQL)
    assert re.search(
        r"FUNCTION item_supply_internal.shared_public_template_matches\(\s*"
        r"request_payload jsonb, source_public jsonb, target_id text\s*\)"
        r" RETURNS boolean LANGUAGE plpgsql IMMUTABLE\s*"
        r"SET search_path=pg_catalog,pg_temp", statements,
    )
    assert "STRICT" not in statements
    assert "SECURITY DEFINER" not in statements
    assert "REVOKE ALL ON FUNCTION item_supply_internal.shared_public_template_matches(jsonb,jsonb,text) FROM PUBLIC;" in statements
    assert not re.search(r"\b(CREATE TABLE|ALTER TABLE|INSERT INTO|UPDATE|DELETE FROM|GRANT|COMMIT)\b", statements)
    assert _constant("new_clause").endswith("IS DISTINCT FROM true")


def test_required_shape_and_null_fences_precede_relaxation() -> None:
    branch = HELPER.index("IF blueprint->>'version'='finite-public-spec-v3'")
    for value in ("request_payload", "source_public", "blueprint", "template"):
        assert HELPER.index(f"jsonb_typeof({value}) IS DISTINCT FROM 'object'") < branch
    assert "blueprint:=request_payload->'blueprint'" in HELPER
    assert "template:=request_payload->'public_template'" in HELPER
    assert "blueprint->>'schema_version' IS DISTINCT FROM 'learning_item_blueprint_v1'" in HELPER
    assert "jsonb_typeof(blueprint->'version') IS DISTINCT FROM 'string'" in HELPER
    assert "FOREACH payload IN ARRAY ARRAY[template,source_public]" in HELPER
    required = re.search(r"FOREACH field_name IN ARRAY ARRAY\[(.*?)\] LOOP", HELPER, re.DOTALL)
    assert required is not None
    assert set(re.findall(r"'([^']+)'", required[1])) == {
        "schema_version", "item_key", "version", "kind", "purpose", "difficulty", "title", "instruction_markdown",
    }
    assert "jsonb_typeof(payload->field_name) IS DISTINCT FROM 'string'" in HELPER
    for field, kind in (
        ("allowed_interactions", "array"), ("source_references", "array"), ("content", "object"),
    ):
        assert f"jsonb_typeof(payload->'{field}') IS DISTINCT FROM '{kind}'" in HELPER
    assert HELPER.index("jsonb_typeof(payload->'allowed_interactions')") < HELPER.index("jsonb_array_length(payload->'allowed_interactions')")
    assert "jsonb_typeof(payload->'content'->'type') IS DISTINCT FROM 'string'" in HELPER
    assert "IS DISTINCT FROM (CASE target_id" in HELPER  # No bare scalar CASE in IF.
    assert "length(payload->>'title')>240" in HELPER
    assert "length(payload->>'instruction_markdown')>8000" in HELPER


def _projection_matches(template: dict, actual: dict, version: str, target: str) -> bool:
    """SQL-derived equality projection on well-shaped offline public fixtures.

    Shape tests above verify the guards separately. This is not a SQL evaluator.
    """
    target_match = re.search(r"target_id IN \((.*?)\)", HELPER)
    assert target_match is not None
    allowed_targets = re.findall(r"'([^']+)'", target_match[1])
    if target not in allowed_targets:
        return False
    allowed = re.search(r"RETURN \(template - ARRAY\[(.*?)\]\)", HELPER)
    assert allowed is not None
    fields = re.findall(r"'([^']+)'", allowed[1])
    assert fields == ["title", "instruction_markdown"]
    assert "(source_public - ARRAY['title','instruction_markdown'])" in HELPER
    assert "RETURN template=source_public;" in HELPER
    if version != "finite-public-spec-v3":
        return template == actual
    instruction, prose = template["instruction_markdown"], actual["instruction_markdown"]
    start, end = _constant("core_start"), _constant("core_end")
    if (not instruction.startswith(start) or not instruction.endswith(end)
            or instruction.count(start) != 1 or instruction.count(end) != 1
            or prose.count(start) != 1 or prose.count(end) != 1 or prose.count(instruction) != 1):
        return False
    return {k: v for k, v in template.items() if k not in fields} == {
        k: v for k, v in actual.items() if k not in fields
    }


def helper_fixture(target_id: str, public_spec_version: str = "finite-public-spec-v3") -> tuple[dict, dict]:
    """Minimal legal helper-input projection plus independent public JSON.

    Synthetic, offline, no source/claim/lease authority. The request projection
    is NOT a full GenerationRequestV2 or an insertable generation artifact.
    Main may pass these JSON objects directly to the three-argument SQL helper.
    """
    kind, purpose, interactions, content = {
        TARGETS[0]: ("code", "exercise", ["edit", "run"], {
            "type": "code", "language_id": "python", "editor_language": "python",
            "exercise_type": "code_completion", "starter_code": "a = 1\n# TODO",
            "code_blanks": [{"blank_key": "update", "expected_concept": "state update",
                             "acceptable_patterns": [{"type": "literal", "value": "a ="}], "is_core": True}],
            "required_patterns": [], "browser_rule_family": None, "preview_html": {},
        }),
        TARGETS[1]: ("knowledge_check", "knowledge_check", ["respond"], {
            "type": "knowledge_check", "response_kind": "single_choice",
            "prompt_markdown": "After a = 1, which statement changes a?",
            "options": [{"option_id": "choice-1", "label": "a = a + 1"},
                        {"option_id": "choice-2", "label": "print(a)"}],
        }),
        TARGETS[2]: ("sql", "exercise", ["query", "run"], {
            "type": "sql_v2", "dialect": "sqlite", "starter_query": "SELECT id FROM records;",
            "tables": [{"name": "records", "columns": [{"name": "id", "data_type": "INTEGER",
                        "nullable": False, "primary_key": True}], "foreign_keys": []}],
            "public_dataset": {"tables": [{"table": "records", "rows": [[1], [2]]}]},
            "comparison": "ordered", "max_rows": 50,
        }),
    }[target_id]
    public = {
        "schema_version": "learning_item_public_v1", "item_key": "finite.test", "version": "v1",
        "kind": kind, "purpose": purpose, "difficulty": "D1", "title": "Title",
        "instruction_markdown": "Authoritative task", "allowed_interactions": interactions,
        "source_references": [{"source_id": "official.source", "source_version": "v1", "locator": "unit",
                               "content_hash": "a" * 64}],
        "hints": [], "remediation_item_key": None, "content": content,
    }
    if public_spec_version == "finite-public-spec-v3":
        public["instruction_markdown"] = (
            _constant("core_start") + "\nAuthoritative task\n" + _constant("core_end")
        )
    request = {"item_key": public["item_key"], "version": public["version"],
               "blueprint": {"schema_version": "learning_item_blueprint_v1", "version": public_spec_version,
                             "item_kind": kind, "purpose": purpose},
               "public_template": deepcopy(public)}
    return request, public


def _public() -> dict:
    return helper_fixture(TARGETS[0])[1]


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("version", ["finite-public-spec-v1", "finite-public-spec-v2", "finite-public-spec-v3", "unknown"])
@pytest.mark.parametrize("field", ["title", "instruction_markdown"])
def test_only_exact_new_version_permits_prose_projection(target: str, version: str, field: str) -> None:
    request, template = helper_fixture(target, version)
    assert request["blueprint"]["version"] == version
    actual = deepcopy(template)
    assert _projection_matches(template, actual, version, target)
    actual[field] = ("New author presentation" if field == "title"
                     else "Intro\n" + template[field] + "\nClosing")
    assert _projection_matches(template, actual, version, target) is (version == "finite-public-spec-v3")


@pytest.mark.parametrize("field", [
    "schema_version", "item_key", "version", "kind", "purpose", "difficulty",
    "allowed_interactions", "source_references", "hints", "remediation_item_key", "content",
])
def test_every_other_public_field_remains_exact(field: str) -> None:
    template = _public()
    actual = deepcopy(template)
    actual[field] = {"changed": True}
    assert not _projection_matches(template, actual, "finite-public-spec-v3", TARGETS[0])
    actual = deepcopy(template)
    actual.pop(field)
    assert not _projection_matches(template, actual, "finite-public-spec-v3", TARGETS[0])


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("version", ["finite-public-spec-v1", "finite-public-spec-v2", "finite-public-spec-v3"])
@pytest.mark.parametrize("case", [
    "exact", "title", "surround", "replacement", "altered_core", "duplicate_core",
    "structured_content", "source_reference",
])
def test_sql_projection_and_real_python_field_fence_agree(target: str, version: str, case: str) -> None:
    """Paired pure inputs, not SQL execution or reconstructed-task authority.

    Use canonical template fixtures and fully parsed public DTOs on both sides;
    the helper intentionally is not the complete DTO/semantic validator.
    """
    from app.services.learning.item_bank.contracts import LearningItemPublicV1
    from app.services.learning.item_supply.finite_candidate_factory import check_finite_public_presentation

    _, template = helper_fixture(target, version)
    actual = deepcopy(template)
    if case == "title":
        actual["title"] = "New presentation"
    elif case == "surround":
        actual["instruction_markdown"] = "Introduction\n" + template["instruction_markdown"] + "\nClosing"
    elif case == "replacement":
        actual["instruction_markdown"] = "Different task"
    elif case == "altered_core":
        actual["instruction_markdown"] = template["instruction_markdown"].replace("Authoritative", "Changed")
    elif case == "duplicate_core":
        actual["instruction_markdown"] *= 2
    elif case == "structured_content":
        if target == TARGETS[0]:
            actual["content"]["starter_code"] += "\n# Changed starter"
        elif target == TARGETS[1]:
            actual["content"]["options"][0]["label"] = "Changed option"
        else:
            actual["content"]["public_dataset"]["tables"][0]["rows"] = [[3], [4]]
    elif case == "source_reference":
        actual["source_references"][0]["locator"] = "different-unit"

    expected_dto = LearningItemPublicV1.model_validate(template)
    actual_dto = LearningItemPublicV1.model_validate(actual)
    python_accepted = True
    try:
        check_finite_public_presentation(actual_dto, expected_dto, public_spec_version=version)
    except ValueError:
        python_accepted = False
    sql_projection_accepted = _projection_matches(
        expected_dto.model_dump(mode="json"), actual_dto.model_dump(mode="json"), version, target,
    )
    assert sql_projection_accepted is python_accepted
    assert python_accepted is (case == "exact" or (version == "finite-public-spec-v3" and case in {"title", "surround"}))


def test_unregistered_target_and_source_only_version_cannot_unlock() -> None:
    template = _public()
    actual = deepcopy(template)
    actual["title"] = "Changed"
    assert not _projection_matches(template, actual, "finite-public-spec-v3", "unregistered")
    # Helper receives only source.public; source.blueprint is not version authority.
    assert not _projection_matches(template, actual, "finite-public-spec-v1", TARGETS[0])
    assert "source_public->'blueprint'" not in HELPER
    assert "source_public->>'version'='finite-public-spec-v3'" not in HELPER


def test_v3_canonical_task_gate_has_same_markers_and_exact_counts() -> None:
    assert _constant("core_start") == "### finite-public-task-v3:start"
    assert _constant("core_end") == "### finite-public-task-v3:end"
    assert "left(expected_instruction,length(core_start)) IS DISTINCT FROM core_start" in HELPER
    assert "right(expected_instruction,length(core_end)) IS DISTINCT FROM core_end" in HELPER
    for text, needle in (
        ("expected_instruction", "core_start"), ("expected_instruction", "core_end"),
        ("actual_instruction", "core_start"), ("actual_instruction", "core_end"),
        ("actual_instruction", "expected_instruction"),
    ):
        assert f"(length({text})-length(replace({text},{needle},'')))/length({needle})<>1" in HELPER
    assert "2000" not in HELPER


@pytest.mark.parametrize("case", [
    "replacement", "altered_core", "duplicate_core", "duplicate_start", "duplicate_end",
    "template_no_markers", "template_reversed", "template_duplicate_start", "template_duplicate_end",
])
def test_v3_replaced_or_duplicated_task_and_noncanonical_templates_fail(case: str) -> None:
    _, template = helper_fixture(TARGETS[0])
    actual = deepcopy(template)
    start, end = _constant("core_start"), _constant("core_end")
    if case == "replacement":
        actual["instruction_markdown"] = "New arbitrary task"
    elif case == "altered_core":
        actual["instruction_markdown"] = template["instruction_markdown"].replace("Authoritative", "Changed")
    elif case == "duplicate_core":
        actual["instruction_markdown"] *= 2
    elif case == "duplicate_start":
        actual["instruction_markdown"] += start
    elif case == "duplicate_end":
        actual["instruction_markdown"] += end
    else:
        template["instruction_markdown"] = {
            "template_no_markers": "Authoritative task",
            "template_reversed": end + "\nAuthoritative task\n" + start,
            "template_duplicate_start": start + template["instruction_markdown"],
            "template_duplicate_end": template["instruction_markdown"] + end,
        }[case]
        actual["instruction_markdown"] = template["instruction_markdown"]
    assert not _projection_matches(template, actual, "finite-public-spec-v3", TARGETS[0])
