from __future__ import annotations

from pathlib import Path
from typing import cast

from psycopg import Connection
import pytest

import app.db.schema as schema
from app.db.bootstrap import apply_schema
from app.db.schema import (
    SCHEMA_DIRECTORY,
    SCHEMA_DRAFT_FILE_NAMES,
    SCHEMA_FRAGMENT_NAMES,
    load_schema_fragments,
    load_schema_text,
    schema_fragment_paths,
)


EXPECTED_SCHEMA_FRAGMENT_NAMES = (
    "000_foundation.sql",
    "010_core_learning.sql",
    "020_grounding.sql",
    "030_legacy_messages.sql",
    "040_tutor_runtime.sql",
    "050_tutor_learner_state.sql",
    "060_tutor_conversation.sql",
    "070_learning_tracks.sql",
    "080_lesson_teaching_practice.sql",
    "090_model_review.sql",
    "100_review_context.sql",
    "110_thread_turn_codex.sql",
    "120_learning_artifacts.sql",
    "130_learning_item_bank.sql",
    "140_learning_item_governance.sql",
    "150_tutor_branch_continuation.sql",
    "160_teaching_artifact_commit.sql",
    "170_teaching_demonstrations.sql",
    "180_knowledge_checks.sql",
    "190_model_review_artifacts.sql",
    "200_sql_learning_workspace.sql",
    "210_tutor_branch_supersession.sql",
    "220_plan_catalog_knowledge_scope.sql",
    "230_artifact_authority_supersession.sql",
    "240_deepseek_flash_runtime_cutover.sql",
    "250_source_inspection_artifacts.sql",
    "260_rag_subject_corpus.sql",
    "270_rag_discovery_jobs.sql",
    "280_rag_candidate_staging.sql",
    "290_rag_discovery_context.sql",
    "300_rag_candidate_policy.sql",
    "310_rag_campaign_authority.sql",
    "320_rag_registered_source.sql",
    "330_rag_source_admission.sql",
    "340_rag_c_capture_capacity.sql",
    "350_rag_c_supplemental_dispatch.sql",
    "360_rag_candidate_use_grants.sql",
    "370_rag_plan_material_bindings.sql",
    "380_rag_material_semantic_reviews.sql",
    "390_rag_c_supplemental_recovery.sql",
    "400_rag_c_final_followup.sql",
    "410_rag_c_deployment_correction.sql",
    "420_rag_c_expired_source_refresh.sql",
    "430_rag_tavily_extraction.sql",
    "440_learning_item_supply_sandbox.sql",
    "450_learning_item_supply_runtime.sql",
    "460_learning_item_supply_pipeline.sql",
    "470_learning_item_supply_sandbox_execution.sql",
    "480_rag_assessment_execution_authority.sql",
    "481_learning_item_supply_admission_facts.sql",
    "482_rag_python_canonical_assessment_source.sql",
    "483_rag_assessment_demand_coordinates.sql",
    "484_rag_c_settled_second_fresh_capture.sql",
    "485_learning_item_private_publication.sql",
    "486_rag_public_python_course_source.sql",
    "487_rag_corpus_usage_partitions.sql",
    "488_rag_public_sqlite_course_source.sql",
    "489_learning_item_shared_pipeline.sql",
    "490_learning_item_shared_execution.sql",
    "491_learning_item_shared_continuation.sql",
    "492_learning_item_native_validation_import.sql",
    "493_learning_item_shared_admission_facts.sql",
    "494_learning_item_native_publication.sql",
    "495_learning_item_native_exposure.sql",
    "496_learning_item_finite_course_mapping.sql",
    "497_rag_course_material_lifetime.sql",
    "498_rag_registered_course_refresh.sql",
    "499_rag_actual_d_finite_source.sql",
    "500_learning_item_flexible_public_spec.sql",
    "501_learning_item_native_type_evidence.sql",
    "502_learning_item_type_exposure.sql",
    "503_rag_actual_d_private_lifecycle.sql",
    "504_rag_actual_d_private_provenance.sql",
    "505_learning_item_diagnostic_blind_admission.sql",
    "506_rag_actual_d_private_insert_alias.sql",
    "507_learning_item_generation_rowtypes.sql",
    "508_learning_item_shared_review_investigation.sql",
    "509_learning_item_shared_revision_lineage.sql",
    "510_learning_item_shared_revision_recheck.sql",
    "511_learning_item_controlled_counterexample.sql",
    "512_learning_item_controlled_counterexample_root.sql",
    "513_learning_item_controlled_counterexample_v2.sql",
    "514_learning_item_shared_review_investigation_sender_v2.sql",
    "515_learning_item_controlled_counterexample_v3.sql",
    "516_learning_item_shared_revision_template_precedence.sql",
    "517_learning_item_development_model_accounting.sql",
    "518_learning_item_controlled_case_execution.sql",
    "519_learning_item_controlled_case_execution_followup.sql",
    "520_learning_item_native_relation_production_v2.sql",
    "521_learning_item_native_consumer_catalog_bridge.sql",
    "522_learning_item_normal_revision_readmission_v1.sql",
    "523_learning_item_persistent_pack_runtime_v1.sql",
    "524_learning_item_private_native_pack_authority_v1.sql",
    "525_learning_item_persistent_normal_revision_phase_v1.sql",
    "526_learning_item_private_enhancement_intent_v1.sql",
    "527_learning_item_private_native_phase_continuation_v1.sql",
    "528_learning_item_persistent_candidate_continuation_v1.sql",
    "529_learning_item_native_public_fallback_delivery_v1.sql",
    "530_learning_item_public_normal_source_ingress_v1.sql",
    "534_learning_item_persistent_normal_input_expression_fix.sql",
    "535_learning_item_persistent_prestart_recovery_v1.sql",
    "536_learning_item_persistent_explicit_recovery_v1.sql",
    "537_learning_item_persistent_revision_expression_fix.sql",
    "538_learning_item_persistent_revision_allocation_expression_fix.sql",
    "539_learning_item_fresh_committed_revision_execution_v1.sql",
    "540_learning_item_revision_frozen_child_blueprint_fix.sql",
    "541_learning_item_revision_generation_durability.sql",
    "542_learning_item_committed_revision_successor_v1.sql",
    "543_learning_item_source_mapping_successor_v1.sql",
    "544_rag_registered_course_refresh_successor.sql",
    "545_learning_item_revision_source_reference_successor.sql",
    "546_learning_item_committed_revision_recheck_v2.sql",
    "547_learning_item_committed_child_admission_v1.sql",
    "549_learning_item_current_pack_source_origin_v1.sql",
    "550_learning_item_native_relation_alias_fix.sql",
    "551_learning_item_private_development_model_accounting_v1.sql",
    "552_learning_item_private_slot_alias_fix.sql",
    "553_learning_item_zero_nonmodel_budget_caps.sql",
    "554_learning_item_private_base_union_alias_fix.sql",
    "555_learning_item_private_initial_author_recovery_v1.sql",
    "556_learning_item_current_pack_ttl120.sql",
    "557_learning_item_native_consumer_public_contract.sql",
    "558_learning_item_private_author_continuation_v1.sql",
    "559_learning_item_private_live_pipeline_actor_v1.sql",
    "560_learning_item_private_generation_durability_v1.sql",
    "561_learning_item_private_source_claim_receipt_hash_v1.sql",
    "562_learning_item_private_generation_persistence_phase_v1.sql",
    "563_learning_item_private_native_handle_identity_v1.sql",
    "564_learning_item_private_native_quality_phase_v1.sql",
    "565_learning_item_private_quality_persist_expression_v1.sql",
    "566_learning_item_private_quality_successor_v1.sql",
    "567_learning_item_private_known_generation_inheritance_v1.sql",
    "568_learning_item_private_bound_phase_window_v1.sql",
    "569_learning_item_private_resume_review_expression_v1.sql",
    "570_learning_item_private_revision_durability_v1.sql",
    "571_learning_item_private_normal_same_scene_v1.sql",
    "572_learning_item_private_revision_author_successor_v1.sql",
    "573_learning_item_private_revision_policy_successor_v1.sql",
    "574_learning_item_private_revision_kc_contract_successor_v1.sql",
    "575_learning_item_private_relation_prompt_receiver_v1.sql",
    "576_learning_item_mvp_relation_deferral_v1.sql",
    "577_learning_item_mvp_retained_delivery_v1.sql",
    "578_learning_item_mvp_eligibility_alias_v1.sql",
    "579_learning_item_mvp_new_window_v1.sql",
    "580_learning_item_private_native_binding_birth_v1.sql",
    "581_learning_item_private_action_receipt_handle_v1.sql",
    "582_learning_item_private_consumer_artifact_rowtype_v1.sql",
    "583_learning_item_private_artifact_mutation_hash_v1.sql",
    "584_rag_m03_sqlite_source_recovery.sql",
    "585_rag_m03_companion_dependency_continuity.sql",
    "586_rag_m03_p1_historical_base_once_receiver.sql",
    "587_learning_item_m03_p2_normal_loop.sql",
    "588_learning_item_incremental_quality.sql",
    "589_learning_item_adjudication_known_settlement.sql",
    "590_learning_item_adjudication_prestart_carry.sql",
    "591_learning_item_adjudication_schema_failure_carry.sql",
    "592_learning_item_adjudicated_publication_rowtype.sql",
    "593_learning_item_persistent_pack_execution_closure.sql",
    "594_m03_sqlite_teaching_companion.sql",
    "595_learning_item_persistent_pack_closure_jsonb_precedence.sql",
    "596_tutor_completion_execution.sql",
    "597_lesson_completion_stages.sql",
    "598_tutor_completion_sidecar_bindings.sql",
)

EXPECTED_SCHEMA_DRAFT_FILE_NAMES = (
    "531_learning_item_private_native_semantic_continuation_v1.sql",
)


class RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def test_schema_manifest_is_explicit_complete_and_not_natural_sort_dependent() -> None:
    assert SCHEMA_FRAGMENT_NAMES == EXPECTED_SCHEMA_FRAGMENT_NAMES
    paths = schema_fragment_paths()
    assert tuple(path.name for path in paths) == EXPECTED_SCHEMA_FRAGMENT_NAMES
    assert SCHEMA_DRAFT_FILE_NAMES == EXPECTED_SCHEMA_DRAFT_FILE_NAMES
    assert set(EXPECTED_SCHEMA_FRAGMENT_NAMES).isdisjoint(EXPECTED_SCHEMA_DRAFT_FILE_NAMES)
    assert {path.name for path in SCHEMA_DIRECTORY.glob("*.sql")} == (
        set(EXPECTED_SCHEMA_FRAGMENT_NAMES) | set(EXPECTED_SCHEMA_DRAFT_FILE_NAMES)
        | {"599_completion_non_b1d_baseline.sql", "601_completion_non_b1d_inventory_reads.sql",
           "602_completion_non_b1d_planning_catalog_reads.sql",
           "600_completion_non_b1d_validation.sql"}
    )
    assert not (SCHEMA_DIRECTORY.parent / "schema.sql").exists()


def test_schema_draft_is_explicitly_retained_but_never_loaded_or_applied() -> None:
    draft_name = EXPECTED_SCHEMA_DRAFT_FILE_NAMES[0]
    assert (SCHEMA_DIRECTORY / draft_name).is_file()
    assert draft_name not in SCHEMA_FRAGMENT_NAMES
    assert draft_name not in {path.name for path in schema_fragment_paths()}
    fragments = load_schema_fragments()
    assert tuple(fragment.name for fragment in fragments) == EXPECTED_SCHEMA_FRAGMENT_NAMES
    assert load_schema_text() == "".join(fragment.sql for fragment in fragments)
    recorder = RecordingConnection()
    apply_schema(cast(Connection[dict[str, object]], recorder))
    assert recorder.statements == [fragment.sql for fragment in fragments]


@pytest.fixture
def schema_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    active_names = ("020_second.sql", "010_first.sql")
    for name, sql in zip(active_names, ("SELECT 2;\n", "SELECT 1;\n"), strict=True):
        (tmp_path / name).write_text(sql, encoding="utf-8")
    (tmp_path / EXPECTED_SCHEMA_DRAFT_FILE_NAMES[0]).write_text(
        "SELECT 'DRAFT MUST NOT BE APPLIED';\n", encoding="utf-8"
    )
    (tmp_path / "599_completion_non_b1d_baseline.sql").write_text(
        "SELECT 'FORWARD ONLY';\n", encoding="utf-8"
    )
    (tmp_path / "601_completion_non_b1d_inventory_reads.sql").write_text(
        "SELECT 'INVENTORY READS ONLY';\n", encoding="utf-8"
    )
    (tmp_path / "602_completion_non_b1d_planning_catalog_reads.sql").write_text(
        "SELECT 'PLANNING CATALOG READS ONLY';\n", encoding="utf-8"
    )
    (tmp_path / "600_completion_non_b1d_validation.sql").write_text(
        "SELECT 'VALIDATION ONLY';\n", encoding="utf-8"
    )
    monkeypatch.setattr(schema, "SCHEMA_DIRECTORY", tmp_path)
    monkeypatch.setattr(schema, "SCHEMA_FRAGMENT_NAMES", active_names)
    monkeypatch.setattr(schema, "SCHEMA_DRAFT_FILE_NAMES", EXPECTED_SCHEMA_DRAFT_FILE_NAMES)
    monkeypatch.setattr(
        schema, "SCHEMA_FROZEN_FILE_NAMES",
        frozenset(active_names + schema.SCHEMA_FORWARD_FRAGMENT_NAMES),
    )
    return tmp_path


def test_schema_manifest_keeps_declared_order_and_excludes_draft(schema_inventory: Path) -> None:
    assert schema.schema_fragment_paths() == (
        schema_inventory / "020_second.sql",
        schema_inventory / "010_first.sql",
    )
    fragments = schema.load_schema_fragments()
    assert tuple(fragment.name for fragment in fragments) == ("020_second.sql", "010_first.sql")
    assert [fragment.sql for fragment in fragments] == ["SELECT 2;\n", "SELECT 1;\n"]
    assert schema.load_schema_text() == "SELECT 2;\nSELECT 1;\n"
    recorder = RecordingConnection()
    apply_schema(cast(Connection[dict[str, object]], recorder))
    assert recorder.statements == ["SELECT 2;\n", "SELECT 1;\n"]


def test_schema_manifest_rejects_unknown_sql_even_with_declared_draft(schema_inventory: Path) -> None:
    (schema_inventory / "999_unregistered.sql").write_text("SELECT 999;\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"schema fragment files are not declared: .*999_unregistered\.sql"):
        schema.schema_fragment_paths()


@pytest.mark.parametrize(
    ("invalid_inventory", "error"),
    (
        ("missing-active", "schema fragment files are missing"),
        ("missing-draft", "schema draft files are missing"),
        ("duplicate-active", "schema fragment manifest contains duplicate names"),
        ("duplicate-draft", "schema draft file manifest contains duplicate names"),
        ("overlap", "schema fragment and draft file manifests overlap"),
    ),
)
def test_schema_manifest_rejects_invalid_declared_inventory(
    schema_inventory: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_inventory: str,
    error: str,
) -> None:
    if invalid_inventory == "missing-active":
        (schema_inventory / "020_second.sql").unlink()
    elif invalid_inventory == "missing-draft":
        (schema_inventory / EXPECTED_SCHEMA_DRAFT_FILE_NAMES[0]).unlink()
    elif invalid_inventory == "duplicate-active":
        monkeypatch.setattr(schema, "SCHEMA_FRAGMENT_NAMES", schema.SCHEMA_FRAGMENT_NAMES * 2)
    elif invalid_inventory == "duplicate-draft":
        monkeypatch.setattr(schema, "SCHEMA_DRAFT_FILE_NAMES", schema.SCHEMA_DRAFT_FILE_NAMES * 2)
    elif invalid_inventory == "overlap":
        monkeypatch.setattr(
            schema, "SCHEMA_DRAFT_FILE_NAMES", (*schema.SCHEMA_DRAFT_FILE_NAMES, "020_second.sql")
        )
    with pytest.raises(RuntimeError, match=error):
        schema.schema_fragment_paths()


def test_completion_fragments_follow_the_frozen_schema_in_dependency_order() -> None:
    completion_fragments = (
        "596_tutor_completion_execution.sql",
        "597_lesson_completion_stages.sql",
        "598_tutor_completion_sidecar_bindings.sql",
    )
    assert SCHEMA_FRAGMENT_NAMES[-3:] == completion_fragments
    assert SCHEMA_FRAGMENT_NAMES[-4] == "595_learning_item_persistent_pack_closure_jsonb_precedence.sql"
    for name in completion_fragments:
        assert SCHEMA_FRAGMENT_NAMES.count(name) == 1
        assert (SCHEMA_DIRECTORY / name).is_file()


def test_schema_combined_view_and_apply_order_match_the_manifest() -> None:
    fragments = load_schema_fragments()
    assert tuple(fragment.name for fragment in fragments) == EXPECTED_SCHEMA_FRAGMENT_NAMES
    assert load_schema_text() == "".join(fragment.sql for fragment in fragments)
    assert fragments[0].sql.startswith("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    by_name = {fragment.name: fragment.sql for fragment in fragments}
    assert 'Child 09 conversation-native SQL workspace' in by_name['200_sql_learning_workspace.sql']
    assert 'tutor_branch_authority_replacement_valid' in by_name['210_tutor_branch_supersession.sql']
    assert 'tutor_plan_catalog_knowledge_key' in by_name['220_plan_catalog_knowledge_scope.sql']
    assert 'tutor_artifact_supersession_successor' in by_name['230_artifact_authority_supersession.sql']
    assert 'deepseek-flash' in by_name['240_deepseek_flash_runtime_cutover.sql']
    assert 'source_inspection' in by_name['250_source_inspection_artifacts.sql']
    assert 'grounding_corpus_versions' in by_name['260_rag_subject_corpus.sql']
    assert 'rag_budget_periods' in by_name['270_rag_discovery_jobs.sql']
    assert 'rag_candidate_captures' in by_name['280_rag_candidate_staging.sql']
    assert 'rag_discovery_private_contexts' in by_name['290_rag_discovery_context.sql']
    assert 'rag_candidate_access_policies' in by_name['300_rag_candidate_policy.sql']
    assert 'rag_campaign_principals' in by_name['310_rag_campaign_authority.sql']
    assert 'rag_registered_source_policies' in by_name['320_rag_registered_source.sql']
    assert 'rag_source_reviews' in by_name['330_rag_source_admission.sql']
    assert 'chk_rag_c_capture_body_8m' in by_name['340_rag_c_capture_capacity.sql']
    assert 'rag_registered_supplemental_authorizations' in by_name['350_rag_c_supplemental_dispatch.sql']
    assert 'rag_candidate_use_grants' in by_name['360_rag_candidate_use_grants.sql']
    assert 'rag_material_selections' in by_name['370_rag_plan_material_bindings.sql']
    assert 'rag_plan_material_bindings' in by_name['370_rag_plan_material_bindings.sql']
    assert 'rag_registered_supplemental_revocations' in by_name['390_rag_c_supplemental_recovery.sql']
    assert 'rag_registered_final_followup_allowances' in by_name['410_rag_c_deployment_correction.sql']
    assert 'rag_provider_extraction_attempts' in by_name['430_rag_tavily_extraction.sql']
    assert "evidence_level='provider_extracted'" in by_name['430_rag_tavily_extraction.sql']

    recorder = RecordingConnection()
    apply_schema(cast(Connection[dict[str, object]], recorder))
    assert recorder.statements == [fragment.sql for fragment in fragments]


def test_schema_fragments_do_not_own_transaction_commits() -> None:
    for fragment in load_schema_fragments():
        normalized = fragment.sql.upper()
        assert "\nCOMMIT;" not in normalized, fragment.name
        assert "\nROLLBACK;" not in normalized, fragment.name


def test_bootstrap_retries_the_complete_transaction_after_deadlock(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from psycopg.errors import DeadlockDetected

    import app.db.bootstrap as bootstrap

    # This unit test owns only legacy transaction retry. Keep dotenv selection
    # and real startup/catalog checks outside this offline fake connection.
    monkeypatch.setattr(bootstrap, "import_module", lambda _name: None)
    monkeypatch.setattr(bootstrap, "selected_contract", lambda: None)
    monkeypatch.setattr(bootstrap, "ensure_startup_contract", lambda **_kwargs: None)

    class RetryConnection:
        def __init__(self, *, fail: bool) -> None:
            self.fail = fail
            self.committed = False

        def execute(self, _statement: str, _params: object = None) -> None:
            if self.fail:
                self.fail = False
                raise DeadlockDetected("test bootstrap deadlock")

        def commit(self) -> None:
            self.committed = True

    class ConnectionContext:
        def __init__(self, connection: RetryConnection) -> None:
            self.connection = connection

        def __enter__(self) -> RetryConnection:
            return self.connection

        def __exit__(self, *_args: object) -> None:
            return None

    connections = [RetryConnection(fail=True), RetryConnection(fail=False)]
    sleeps: list[float] = []
    monkeypatch.setattr(bootstrap, "connect", lambda: ConnectionContext(connections.pop(0)))
    monkeypatch.setattr(bootstrap, "sleep", sleeps.append)
    for name in (
        "apply_schema",
        "seed_runtime_profiles",
        "seed_language_courses",
        "archive_language_courses",
        "seed_learning_intents",
        "seed_language_course_intent_tags",
        "require_language_course_intent_coverage",
        "import_curated_learning_item_sources",
    ):
        monkeypatch.setattr(bootstrap, name, lambda _conn: None)

    bootstrap.bootstrap_database()

    assert sleeps == [bootstrap._BOOTSTRAP_RETRY_DELAY_SECONDS]
    assert not connections


def test_c_capture_capacity_upgrade_has_new_idempotent_constraints() -> None:
    sql = {fragment.name: fragment.sql for fragment in load_schema_fragments()}[
        "340_rag_c_capture_capacity.sql"
    ]
    assert "DROP CONSTRAINT IF EXISTS rag_registered_source_policies_max_captured_bytes_check" in sql
    assert "DROP CONSTRAINT IF EXISTS rag_registered_fetch_attempts_response_bytes_check" in sql
    assert "DROP CONSTRAINT IF EXISTS rag_registered_source_captures_captured_bytes_check" in sql
    assert sql.count("BETWEEN 1 AND 8388608") == 2
    assert "response_bytes BETWEEN 0 AND 8388608" in sql
    assert sql.count("IF NOT EXISTS (SELECT 1 FROM pg_constraint") == 3


def test_forward_manifest_is_an_independent_literal_plan(schema_inventory: Path) -> None:
    runtime = (
        "599_completion_non_b1d_baseline.sql", "601_completion_non_b1d_inventory_reads.sql",
        "602_completion_non_b1d_planning_catalog_reads.sql",
    )
    validation = runtime + ("600_completion_non_b1d_validation.sql",)
    assert schema.SCHEMA_FORWARD_FRAGMENT_NAMES == validation
    assert schema.RUNTIME_FORWARD_FRAGMENT_NAMES == runtime
    assert schema.VALIDATION_FORWARD_FRAGMENT_NAMES == validation
    assert tuple(p.name for p in schema.schema_fragment_paths(
        contract="completion_non_b1d_v1", storage_check=True,
    )) == validation
    assert tuple(p.name for p in schema.schema_fragment_paths(contract="completion_non_b1d_v1")) == runtime
    assert [f.sql for f in schema.load_schema_fragments(contract="completion_non_b1d_v1")] == [
        "SELECT 'FORWARD ONLY';\n", "SELECT 'INVENTORY READS ONLY';\n", "SELECT 'PLANNING CATALOG READS ONLY';\n",
    ]
    assert [f.sql for f in schema.load_schema_fragments(
        contract="completion_non_b1d_v1", storage_check=True,
    )] == [
        "SELECT 'FORWARD ONLY';\n", "SELECT 'INVENTORY READS ONLY';\n",
        "SELECT 'PLANNING CATALOG READS ONLY';\n", "SELECT 'VALIDATION ONLY';\n",
    ]
    assert schema.load_schema_text() == "SELECT 2;\nSELECT 1;\n"


@pytest.mark.parametrize("invalid", ["missing", "missing-inventory", "missing-planning", "duplicate", "active-overlap", "draft-overlap", "unknown-contract"])
def test_forward_inventory_fails_closed(
    schema_inventory: Path, monkeypatch: pytest.MonkeyPatch, invalid: str,
) -> None:
    if invalid == "missing":
        (schema_inventory / "599_completion_non_b1d_baseline.sql").unlink()
    elif invalid == "missing-inventory":
        (schema_inventory / "601_completion_non_b1d_inventory_reads.sql").unlink()
    elif invalid == "missing-planning":
        (schema_inventory / "602_completion_non_b1d_planning_catalog_reads.sql").unlink()
    elif invalid == "duplicate":
        monkeypatch.setattr(schema, "SCHEMA_FORWARD_FRAGMENT_NAMES", schema.SCHEMA_FORWARD_FRAGMENT_NAMES * 2)
    elif invalid == "active-overlap":
        monkeypatch.setattr(schema, "SCHEMA_FORWARD_FRAGMENT_NAMES", ("020_second.sql",))
    elif invalid == "draft-overlap":
        monkeypatch.setattr(schema, "SCHEMA_FORWARD_FRAGMENT_NAMES", EXPECTED_SCHEMA_DRAFT_FILE_NAMES)
    with pytest.raises(RuntimeError):
        schema.schema_fragment_paths(contract="unknown" if invalid == "unknown-contract" else "completion_non_b1d_v1")


def test_validation_only_fragment_cannot_cross_classifications(
    schema_inventory: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schema, "RUNTIME_FORWARD_FRAGMENT_NAMES", (
        "599_completion_non_b1d_baseline.sql", "601_completion_non_b1d_inventory_reads.sql",
        "602_completion_non_b1d_planning_catalog_reads.sql",
        "600_completion_non_b1d_validation.sql",
    ))
    with pytest.raises(RuntimeError, match="FORWARD_CLASSIFICATION_REJECTED"):
        schema.schema_fragment_paths(contract="completion_non_b1d_v1")


def test_validation_requires_named_contract(schema_inventory: Path) -> None:
    with pytest.raises(RuntimeError, match="CONTRACT_REQUIRED"):
        schema.schema_fragment_paths(storage_check=True)
