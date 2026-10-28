"""CPU checks for the finite 600 receivers; never import/connect to PostgreSQL.

These check reviewable source contracts, not PG compilation or catalog identity.
Main owns installation and the eight actual PostgreSQL consumer scenarios.
"""
from pathlib import Path
import re


SCHEMA = Path(__file__).resolve().parents[2] / "app" / "db" / "schema"


def _body(source: str, name: str) -> str:
    matches = list(re.finditer(r"^CREATE (?:OR REPLACE )?FUNCTION " + re.escape(name)
        + r"\([^;]*?AS (\$\w*\$)(.*?)\1;", source, re.MULTILINE | re.DOTALL))
    assert len(matches) == 1, name
    return matches[0][2]


def test_600_overrides_match_the_actual_predecessor_bodies() -> None:
    validation = (SCHEMA / "600_completion_non_b1d_validation.sql").read_text(encoding="utf-8")
    baseline = (SCHEMA / "599_completion_non_b1d_baseline.sql").read_text(encoding="utf-8")
    # Main's saved actual prosrc (existing-functions.json) is byte-identical
    # to this fetch-only 320 body; the historical 430 file is NOT installed.
    registered = (SCHEMA / "320_rag_registered_source.sql").read_text(encoding="utf-8")
    names = ("completion_baseline_internal.enforce_closed_storage", "completion_baseline_internal.enforce_source_evidence_closed",
        "completion_baseline_internal.enforce_closed_native_consumer", "rag_actual_d_finite_lifetime_allowed",
        "public.rag_source_admission_guard", "public.rag_source_claim_guard")
    expected = {_body(baseline, name) for name in names}
    expected.add(_body(registered, "rag_registered_capture_guard"))
    actual = set(re.findall(r"IS DISTINCT FROM \$prior\$(.*?)\$prior\$", validation, re.DOTALL))
    assert len(actual) == 7 and actual == expected
    capture = _body(validation, "public.rag_registered_capture_guard")
    assert "provider_row" not in capture and "provider_attempt_id" not in capture
    assert "CREATE OR REPLACE FUNCTION rag_actual_d_private_purge" not in validation
    assert "CREATE OR REPLACE FUNCTION purge_item_supply_private" not in validation
    assert "DISABLE TRIGGER" not in validation and "session_replication_role" not in validation
    assert not re.search(r"^CREATE (?:OR REPLACE )?FUNCTION \w+\(", validation, re.MULTILINE)
    for signature in ("rag_actual_d_finite_lifetime_allowed(jsonb,text,timestamptz,timestamptz)",
                      "rag_source_admission_guard()", "rag_source_claim_guard()"):
        assert f"ALTER FUNCTION public.{signature} SET search_path=pg_catalog,public,item_supply_internal,pg_temp;" in validation
        assert f"ALTER FUNCTION public.{signature} SECURITY INVOKER;" in validation


def test_600_claim_guard_search_path_follows_its_final_replacement() -> None:
    source = (SCHEMA / "600_completion_non_b1d_validation.sql").read_text(encoding="utf-8")
    name = re.escape("public.rag_source_claim_guard")
    definitions = list(re.finditer(r"^CREATE (?:OR REPLACE )?FUNCTION " + name
        + r"\(\)[^;]*?AS (\$\w*\$)(.*?)\1;", source, re.MULTILINE | re.DOTALL))
    assert len(definitions) == 1
    settings = list(re.finditer(r"^ALTER FUNCTION " + name
        + r"\(\) (?:SET search_path|RESET search_path|RESET ALL)[^;]*;", source, re.MULTILINE))
    assert settings
    # CREATE OR REPLACE resets an earlier ALTER SET; presence alone is insufficient.
    assert settings[-1].start() > definitions[-1].end()
    assert settings[-1].group() == (
        "ALTER FUNCTION public.rag_source_claim_guard() "
        "SET search_path=pg_catalog,public,item_supply_internal,pg_temp;"
    )


def test_600_named_receivers_require_real_verifier_and_current_original_scope() -> None:
    source = (SCHEMA / "600_completion_non_b1d_validation.sql").read_text(encoding="utf-8")
    caller = _body(source, "completion_baseline_internal.assert_validation_caller")
    assert "session_user<>'aearn_cb_verifier_20261027'" in caller
    assert "contract_identity()" in caller and "storage-validation-purpose" in caller
    scope = _body(source, "completion_baseline_internal.validation_scope")
    assert "assert_validation_caller()" in scope and "epoch=s.epoch AND enabled FOR SHARE" in scope
    assert "deleted_at IS NULL FOR UPDATE" in scope
    active_plan = "FROM tutor_track_active_plans WHERE track_id=s.track_id AND user_id=s.user_id AND revision_id=s.revision_id FOR SHARE"
    assert active_plan in scope and "active_plan_revision_id" not in scope
    journal = _body(source, "completion_baseline_internal.issue_journal_graph")
    assert active_plan in journal and "stale graph plan" in journal
    signatures = {"issue_native_binding_graph": "uuid,uuid,uuid", "issue_shared_subscription_graph": "uuid,uuid",
        "issue_actual_d_tail_graph": "uuid"}
    for name, args in signatures.items():
        full_name = "completion_baseline_internal." + name
        body = _body(source, full_name)
        assert "validation_scope(" in body and "validation_permits" in body
        assert f"ALTER FUNCTION {full_name}({args}) OWNER TO aearn_cb_schema_20261027;" in source
        assert f"REVOKE ALL ON FUNCTION {full_name}({args}) FROM PUBLIC,aearn_cb_runtime_20261027,aearn_cb_verifier_20261027;" in source
        assert f"GRANT EXECUTE ON FUNCTION {full_name}({args}) TO aearn_cb_verifier_20261027;" in source
        declaration = source[source.index("CREATE FUNCTION " + full_name):].split("RETURNS", 1)[0]
        assert "jsonb" not in declaration and "text" not in declaration


def test_600_synthetic_shapes_are_exact_finite_extensions_not_disabled_integrity() -> None:
    source = (SCHEMA / "600_completion_non_b1d_validation.sql").read_text(encoding="utf-8")
    shapes = source.split("DO $synthetic_shapes$", 1)[1].split("END $synthetic_shapes$;", 1)[0]
    assert shapes.count("$old$CHECK (") == 7 and "pg_get_constraintdef(oid)=r.predecessor" in shapes
    assert "count_found<>1" in shapes and "contype='c' AND convalidated AND conislocal" in shapes
    assert "FOREIGN KEY" not in shapes and "DROP TABLE" not in source and "TRUNCATE" not in source
    assert "completion_storage_validation" in shapes and "transport_proof IS NULL" in shapes
    assert "independent_admission_id IS NULL" in shapes and "NOT active AND revoked_at IS NOT NULL" in shapes
    assert "OR ((%s) IS TRUE)" in shapes
    assert "$old$CHECK ((evidence_level = 'live_egress_attested'::text))$old$" in shapes
    assert "provider_attempt_id" not in shapes


def test_600_shared_retention_preserves_null_unknown_and_cannot_claim_paid_usage() -> None:
    source = (SCHEMA / "600_completion_non_b1d_validation.sql").read_text(encoding="utf-8")
    assert source.count("CREATE TABLE ") == 1
    assert "FOREIGN KEY(reservation_id,job_id) REFERENCES tutor_item_supply_shared_reservations(id,job_id) ON DELETE RESTRICT" in source
    assert "CHECK(cost_amount IS NULL)" in source
    body = _body(source, "completion_baseline_internal.issue_shared_subscription_graph")
    assert "a.user_id=b.user_id" in body and "FOREACH scope IN ARRAY ARRAY[$1,$2]" in body
    assert "'completion.validation.synthetic.known','known',7,3,0,NULL" in body
    assert "'completion.validation.synthetic.unknown','unknown',NULL,NULL,NULL,NULL" in body
    assert "'scope',x.snapshot_json,'objective_hash',x.objective_hash,'learner_ref','user:'||x.user_id::text" in body
    assert "'publication_enabled',false" in body and "'disabled.synthetic'" in body


def test_600_actual_d_is_nonempty_unsigned_revoked_and_uses_original_tail() -> None:
    source = (SCHEMA / "600_completion_non_b1d_validation.sql").read_text(encoding="utf-8")
    body = _body(source, "completion_baseline_internal.issue_actual_d_tail_graph")
    for table in ("rag_assessment_source_evidence", "rag_source_reviews", "rag_source_admissions",
                  "rag_source_claim_receipts", "rag_actual_d_private_provenance"):
        assert "INSERT INTO " + table in body
    assert "'signature_status','unsigned'" in body and "'STORAGE_VALIDATION_NO_FETCH'" in body
    assert "'quarantined','STORAGE_VALIDATION_ONLY','unknown','unknown','unknown','unknown'" in body
    assert "SET state='failed',generation=1" in body and "grounding_active_corpora" not in body
    assert "'completion_storage_validation'" in body and "'live_egress_attested'" not in body
    assert "issued timestamptz:='2000-01-01T00:00:00Z'" in body
    assert "expiry timestamptz:='2000-01-01T00:01:00Z'" in body
    assert "rag_actual_d_private_delete_allowed" in _body(source, "completion_baseline_internal.enforce_source_evidence_closed")
