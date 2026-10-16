"""显式、有序的 PostgreSQL Schema fragment manifest。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEMA_DIRECTORY = Path(__file__).parent
SCHEMA_FRAGMENT_NAMES: tuple[str, ...] = (
    '000_foundation.sql',
    '010_core_learning.sql',
    '020_grounding.sql',
    '030_legacy_messages.sql',
    '040_tutor_runtime.sql',
    '050_tutor_learner_state.sql',
    '060_tutor_conversation.sql',
    '070_learning_tracks.sql',
    '080_lesson_teaching_practice.sql',
    '090_model_review.sql',
    '100_review_context.sql',
    '110_thread_turn_codex.sql',
    '120_learning_artifacts.sql',
    '130_learning_item_bank.sql',
    '140_learning_item_governance.sql',
    '150_tutor_branch_continuation.sql',
    '160_teaching_artifact_commit.sql',
    '170_teaching_demonstrations.sql',
    '180_knowledge_checks.sql',
    '190_model_review_artifacts.sql',
    '200_sql_learning_workspace.sql',
    '210_tutor_branch_supersession.sql',
    '220_plan_catalog_knowledge_scope.sql',
    '230_artifact_authority_supersession.sql',
    '240_deepseek_flash_runtime_cutover.sql',
    '250_source_inspection_artifacts.sql',
    '260_rag_subject_corpus.sql',
    '270_rag_discovery_jobs.sql',
    '280_rag_candidate_staging.sql',
    '290_rag_discovery_context.sql',
    '300_rag_candidate_policy.sql',
    '310_rag_campaign_authority.sql',
    '320_rag_registered_source.sql',
    '330_rag_source_admission.sql',
    '340_rag_c_capture_capacity.sql',
    '350_rag_c_supplemental_dispatch.sql',
    '360_rag_candidate_use_grants.sql',
    '370_rag_plan_material_bindings.sql',
    '380_rag_material_semantic_reviews.sql',
    '390_rag_c_supplemental_recovery.sql',
    '400_rag_c_final_followup.sql',
    '410_rag_c_deployment_correction.sql',
    '420_rag_c_expired_source_refresh.sql',
    '430_rag_tavily_extraction.sql',
    '440_learning_item_supply_sandbox.sql',
    '450_learning_item_supply_runtime.sql',
    '460_learning_item_supply_pipeline.sql',
    '470_learning_item_supply_sandbox_execution.sql',
    '480_rag_assessment_execution_authority.sql',
    '481_learning_item_supply_admission_facts.sql',
    '482_rag_python_canonical_assessment_source.sql',
    '483_rag_assessment_demand_coordinates.sql',
    '484_rag_c_settled_second_fresh_capture.sql',
    '485_learning_item_private_publication.sql',
    '486_rag_public_python_course_source.sql',
    '487_rag_corpus_usage_partitions.sql',
    '488_rag_public_sqlite_course_source.sql',
    '489_learning_item_shared_pipeline.sql',
    '490_learning_item_shared_execution.sql',
    '491_learning_item_shared_continuation.sql',
    '492_learning_item_native_validation_import.sql',
    '493_learning_item_shared_admission_facts.sql',
    '494_learning_item_native_publication.sql',
    '495_learning_item_native_exposure.sql',
    '496_learning_item_finite_course_mapping.sql',
    '497_rag_course_material_lifetime.sql',
    '498_rag_registered_course_refresh.sql',
    '499_rag_actual_d_finite_source.sql',
    '500_learning_item_flexible_public_spec.sql',
    '501_learning_item_native_type_evidence.sql',
    '502_learning_item_type_exposure.sql',
    '503_rag_actual_d_private_lifecycle.sql',
    '504_rag_actual_d_private_provenance.sql',
    '505_learning_item_diagnostic_blind_admission.sql',
    '506_rag_actual_d_private_insert_alias.sql',
    '507_learning_item_generation_rowtypes.sql',
    '508_learning_item_shared_review_investigation.sql',
    '509_learning_item_shared_revision_lineage.sql',
    '510_learning_item_shared_revision_recheck.sql',
    '511_learning_item_controlled_counterexample.sql',
    '512_learning_item_controlled_counterexample_root.sql',
    '513_learning_item_controlled_counterexample_v2.sql',
    '514_learning_item_shared_review_investigation_sender_v2.sql',
    '515_learning_item_controlled_counterexample_v3.sql',
    '516_learning_item_shared_revision_template_precedence.sql',
    '517_learning_item_development_model_accounting.sql',
    '518_learning_item_controlled_case_execution.sql',
    '519_learning_item_controlled_case_execution_followup.sql',
    '520_learning_item_native_relation_production_v2.sql',
    '521_learning_item_native_consumer_catalog_bridge.sql',
    '522_learning_item_normal_revision_readmission_v1.sql',
    '523_learning_item_persistent_pack_runtime_v1.sql',
    '524_learning_item_private_native_pack_authority_v1.sql',
    '525_learning_item_persistent_normal_revision_phase_v1.sql',
    '526_learning_item_private_enhancement_intent_v1.sql',
    '527_learning_item_private_native_phase_continuation_v1.sql',
    '528_learning_item_persistent_candidate_continuation_v1.sql',
    '529_learning_item_native_public_fallback_delivery_v1.sql',
    '530_learning_item_public_normal_source_ingress_v1.sql',
    '534_learning_item_persistent_normal_input_expression_fix.sql',
    '535_learning_item_persistent_prestart_recovery_v1.sql',
    '536_learning_item_persistent_explicit_recovery_v1.sql',
    '537_learning_item_persistent_revision_expression_fix.sql',
    '538_learning_item_persistent_revision_allocation_expression_fix.sql',
    '539_learning_item_fresh_committed_revision_execution_v1.sql',
    '540_learning_item_revision_frozen_child_blueprint_fix.sql',
    '541_learning_item_revision_generation_durability.sql',
    '542_learning_item_committed_revision_successor_v1.sql',
    '543_learning_item_source_mapping_successor_v1.sql',
    '544_rag_registered_course_refresh_successor.sql',
    '545_learning_item_revision_source_reference_successor.sql',
    '546_learning_item_committed_revision_recheck_v2.sql',
    '547_learning_item_committed_child_admission_v1.sql',
    '549_learning_item_current_pack_source_origin_v1.sql',
    '550_learning_item_native_relation_alias_fix.sql',
    '551_learning_item_private_development_model_accounting_v1.sql',
    '552_learning_item_private_slot_alias_fix.sql',
    '553_learning_item_zero_nonmodel_budget_caps.sql',
    '554_learning_item_private_base_union_alias_fix.sql',
    '555_learning_item_private_initial_author_recovery_v1.sql',
    '556_learning_item_current_pack_ttl120.sql',
    '557_learning_item_native_consumer_public_contract.sql',
    '558_learning_item_private_author_continuation_v1.sql',
    '559_learning_item_private_live_pipeline_actor_v1.sql',
    '560_learning_item_private_generation_durability_v1.sql',
    '561_learning_item_private_source_claim_receipt_hash_v1.sql',
    '562_learning_item_private_generation_persistence_phase_v1.sql',
    '563_learning_item_private_native_handle_identity_v1.sql',
)


@dataclass(frozen=True)
class SchemaFragment:
    name: str
    path: Path
    sql: str


def schema_fragment_paths() -> tuple[Path, ...]:
    """按 manifest 顺序返回片段，并拒绝缺失或未登记 SQL。"""

    if len(SCHEMA_FRAGMENT_NAMES) != len(set(SCHEMA_FRAGMENT_NAMES)):
        raise RuntimeError("schema fragment manifest contains duplicate names")
    paths = tuple(SCHEMA_DIRECTORY / name for name in SCHEMA_FRAGMENT_NAMES)
    missing = tuple(path.name for path in paths if not path.is_file())
    if missing:
        raise RuntimeError(f"schema fragment files are missing: {missing}")
    declared = set(SCHEMA_FRAGMENT_NAMES)
    unexpected = tuple(sorted(path.name for path in SCHEMA_DIRECTORY.glob("*.sql") if path.name not in declared))
    if unexpected:
        raise RuntimeError(f"schema fragment files are not declared: {unexpected}")
    return paths


def load_schema_fragments() -> tuple[SchemaFragment, ...]:
    return tuple(
        SchemaFragment(name=path.name, path=path, sql=path.read_text(encoding="utf-8"))
        for path in schema_fragment_paths()
    )


def load_schema_text() -> str:
    """只读组合视图；不得另存为第二份聚合 Schema source。"""

    return "".join(fragment.sql for fragment in load_schema_fragments())
