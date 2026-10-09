"""Exact offline 507 contracts, not PostgreSQL compilation/live acceptance."""
from hashlib import sha256
from pathlib import Path
import re

import pytest

SCHEMA = Path(__file__).resolve().parents[2] / "app/db/schema"
SQL = (SCHEMA / "507_learning_item_generation_rowtypes.sql").read_text(encoding="utf8")
LEGACY = (SCHEMA / "505_learning_item_diagnostic_blind_admission.sql").read_text(encoding="utf8")
PINS = re.findall(
    r"\('([^']+\(\))',\s*'([0-9a-f]{64})',\s*'([0-9a-f]{64})',\s*'([^']+)',\s*'([^']+)'\)", SQL)


def _bodies():
    result = {}
    for block in re.findall(r"DO \$pin\$(.*?)END \$pin\$;", LEGACY, re.S):
        name = re.search(r"function_oid:=to_regprocedure\('([^']+)'\)", block)[1]
        result[name] = re.search(r"\$newbody\$(.*?)\$newbody\$", block, re.S)[1]
    return result


def _apply(source, pin):
    """Model the checked declaration replacement only, not SQL evaluation."""
    _, old_hash, new_hash, old, new = pin
    source = source.replace("\r\n", "\n")
    if sha256(source.encode()).hexdigest() == new_hash:
        return source
    if sha256(source.encode()).hexdigest() != old_hash or source.count(old) != 1:
        raise ValueError("unknown baseline")
    revised = source.replace(old, new)
    assert sha256(revised.encode()).hexdigest() == new_hash
    return revised


def test_507_three_exact_generation_locals_and_full_body_pins():
    assert [pin[0] for pin in PINS] == [
        "public.enforce_item_supply_shared_pipeline_artifact()",
        "public.enforce_item_supply_shared_admission_facts()",
        "public.enforce_learning_item_native_publication_proof()",
    ]
    bodies = _bodies()
    for pin, variable in zip(PINS, ("facts", "a", "g"), strict=True):
        old = bodies[pin[0]]
        assert pin[3] == f" {variable} record;"
        assert pin[4] == f" {variable} public.tutor_item_supply_shared_generation_artifacts%ROWTYPE;"
        assert f"SELECT * INTO {variable} FROM tutor_item_supply_shared_generation_artifacts" in old
        assert f"{variable}::tutor_item_supply_shared_generation_artifacts" in old
        revised = _apply(old, pin)
        assert revised.replace(pin[4], pin[3]) == old
        assert revised.split("\nBEGIN\n", 1)[1] == old.split("\nBEGIN\n", 1)[1]


def test_507_same_fragment_and_505_ordered_replay_reject_unknown_body():
    bodies = _bodies()
    for pin in PINS:
        revised = _apply(bodies[pin[0]], pin)
        assert _apply(revised, pin) == revised
        assert _apply(bodies[pin[0]], pin) == revised  # 505 restores its known body.
        with pytest.raises(ValueError, match="unknown baseline"):
            _apply(bodies[pin[0]] + "\n-- unexpected upstream mutation", pin)
    assert "source_hash IS DISTINCT FROM spec.baseline_sha256" in SQL
    assert SQL.count("IS DISTINCT FROM spec.revised_sha256") == 2


def test_507_attributes_checked_before_replay_and_original_definition_preserved():
    attributes = SQL[SQL.index("IF NOT FOUND"):SQL.index("source:=replace")]
    for field in ("prokind", "lanname", "pronargs", "prorettype", "proretset", "proisstrict",
                  "prosecdef", "proleakproof", "provolatile", "proparallel", "provariadic",
                  "pronargdefaults", "proargnames", "proallargtypes", "proargmodes", "proconfig",
                  "procost", "prorows", "prosupport"):
        assert "actual." + field in attributes
    assert "OR NOT actual.prosecdef" in attributes
    assert "actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']" in attributes
    assert SQL.index("IF NOT FOUND") < SQL.index("IF source_hash=spec.revised_sha256")
    assert "definition:=pg_get_functiondef(actual.oid);" in SQL
    assert "EXECUTE replace(definition,actual.prosrc,repaired_source);" in SQL
    assert "FROM pg_proc p WHERE p.oid=actual.oid" in SQL


def test_507_leaves_typed_new_helpers_and_old_files_unchanged():
    assert sha256(LEGACY.encode()).hexdigest() == "c78f8febf9893d413e18addb8507f67a449e4d774c0afa0ce6bcfff5e22e7519"
    assert sha256((SCHEMA / "506_rag_actual_d_private_insert_alias.sql").read_bytes()).hexdigest() == "5856416e9a2c81ce7b2c0d9c4356260ddace1d59ce7d23f9ebbb728c874642a9"
    pipeline = _apply(_bodies()[PINS[0][0]], PINS[0])
    assert "shared_generation_policy_hash(NEW::tutor_item_supply_shared_generation_artifacts)" in pipeline
    assert "root_facts record;" in pipeline
    assert "g tutor_item_supply_shared_generation_artifacts, evaluation jsonb, review jsonb" in LEGACY
    executable = re.sub(r"--[^\n]*", "", SQL)
    assert not re.search(r"\b(COMMIT|ROLLBACK|GRANT|REVOKE|DROP|ALTER TABLE|INSERT INTO|UPDATE|DELETE FROM)\b", executable)
    assert "jsonb_populate_record" not in executable and "to_jsonb" not in executable
