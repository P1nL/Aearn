"""Explicit P2 partitions; never imported by the pure package entry point."""

P7_PRIVATE_TABLES: tuple[str, ...] = (
    "tutor_item_supply_private_materializations",
    "tutor_item_supply_private_publication_events",
    "tutor_item_supply_private_publication_proofs",
)

# Child-to-parent order for the native collector; no public/shared exposure data.
P7_NATIVE_EXPOSURE_TABLES: tuple[str, ...] = (
    "tutor_item_supply_native_exposure_deliveries",
    "tutor_item_supply_native_exposure_reservations",
    "tutor_item_supply_native_exposure_watermarks",
    "tutor_item_supply_native_exposure_events",
    "tutor_item_supply_native_exposure_inbox",
    "tutor_item_supply_native_exposure_births",
)
NATIVE_EXPOSURE_UNSCOPED_TABLES: tuple[str, ...] = P7_NATIVE_EXPOSURE_TABLES[2:]

# Explicit new V2 private sidecars. SQL a01/a02 epoch hooks enforce this order;
# public item references do not make learner-bound judgments shared audit.
P7_NATIVE_TYPE_EXPOSURE_TABLES: tuple[str, ...] = (
    "tutor_item_supply_type_exposure_deliveries",
    "tutor_item_supply_type_exposure_reservations",
    "tutor_item_supply_type_exposure_snapshots",
)
P7_NATIVE_TYPE_EVIDENCE_TABLES: tuple[str, ...] = (
    "tutor_item_supply_native_eligibility",
    "tutor_item_supply_native_relation_batches",
    "tutor_item_supply_native_relation_preparations",
    "tutor_item_supply_native_content_facts",
)
NATIVE_TYPE_UNSCOPED_TABLES: tuple[str, ...] = (
    *P7_NATIVE_TYPE_EVIDENCE_TABLES,
    "tutor_item_supply_type_exposure_snapshots",
)

# One private receipt spans three original scopes; safe export has no single scope_id.
P7_FINITE_COURSE_MAPPING_TABLES: tuple[str, ...] = (
    "tutor_item_supply_finite_course_mappings",
)

P7_SHARED_PIPELINE_TABLES: tuple[str, ...] = (
    "tutor_item_supply_shared_generation_policy_bindings",
    "tutor_item_supply_shared_generation_artifacts",
    "tutor_item_supply_shared_pipeline_receipts",
    "tutor_item_supply_shared_validation_preparations",
    "tutor_item_supply_shared_validation_evidence",
    "tutor_item_supply_shared_candidate_continuations",
    "tutor_item_supply_shared_admission_facts",
    "tutor_item_supply_shared_review_investigation_preparations",
    "tutor_item_supply_shared_review_investigation_receipts",
    "tutor_item_supply_shared_revision_preparations",
    "tutor_item_supply_shared_revision_lineage",
    "tutor_item_supply_shared_revision_recheck_preparations",
    "tutor_item_supply_shared_revision_recheck_receipts",
    "tutor_item_supply_shared_controlled_counterexample_preparations",
    "tutor_item_supply_shared_controlled_counterexample_receipts",
)

SHARED_TABLES: tuple[str, ...] = (
    "tutor_item_supply_shared_matrices",
    "tutor_item_supply_shared_policies",
    "tutor_item_supply_shared_blueprints",
    "tutor_item_supply_shared_slots",
    "tutor_item_supply_shared_budget_roots",
    "tutor_item_supply_shared_budget_windows",
    "tutor_item_supply_shared_jobs",
    "tutor_item_supply_shared_job_events",
    "tutor_item_supply_shared_reservations",
    "tutor_item_supply_shared_usage_events",
    "tutor_item_supply_shared_evidence",
    "tutor_item_supply_shared_observations",
    "tutor_item_supply_shared_proofs",
    "tutor_item_supply_shared_admissions",
    "tutor_item_supply_runtime_global_limits",
    "tutor_item_supply_shared_obligations",
    "tutor_item_supply_parameter_profiles",
    "tutor_item_supply_shared_job_controls",
    "tutor_item_supply_shared_checkpoints",
    "tutor_item_supply_runtime_global_reservation_amounts",
    "tutor_item_supply_shared_runtime_settlements",
    "tutor_item_supply_shared_runtime_settlement_amounts",
    "tutor_item_supply_profile_observations",
    "tutor_item_supply_profile_events",
    "tutor_item_supply_runtime_global_usage_facts",
    *P7_SHARED_PIPELINE_TABLES,
)
PRIVATE_TABLES: tuple[str, ...] = (
    "tutor_item_supply_private_subscriptions",
    "tutor_item_supply_private_result_items",
    "tutor_item_supply_private_bindings",
    "tutor_item_supply_private_cache",
    "tutor_item_supply_private_results",
    "tutor_item_supply_private_demands",
    "tutor_item_supply_private_publication_refs",
    "tutor_item_supply_private_admissions",
    "tutor_item_supply_private_proofs",
    "tutor_item_supply_private_observations",
    "tutor_item_supply_private_evidence",
    "tutor_item_supply_private_usage_events",
    "tutor_item_supply_private_reservations",
    "tutor_item_supply_private_job_events",
    "tutor_item_supply_private_jobs",
    "tutor_item_supply_private_budget_windows",
    "tutor_item_supply_private_budget_roots",
    "tutor_item_supply_private_staging",
    "tutor_item_supply_private_versions",
    "tutor_item_supply_private_candidates",
    "tutor_item_supply_private_materials",
    "tutor_item_supply_private_scopes",
    "tutor_item_supply_private_runtime_settlement_amounts",
    "tutor_item_supply_private_runtime_settlements",
    "tutor_item_supply_private_runtime_reservation_amounts",
    "tutor_item_supply_private_checkpoints",
    "tutor_item_supply_private_job_controls",
    "tutor_item_supply_private_obligations",
    "tutor_item_supply_private_runtime_user_limits",
    "tutor_item_supply_private_generation_artifacts",
    "tutor_item_supply_private_pipeline_receipts",
    "tutor_item_supply_private_execution_intents",
    "tutor_item_supply_private_sandbox_runs",
    "tutor_item_supply_private_sandbox_observations",
    "tutor_item_supply_private_admission_facts",
    *P7_PRIVATE_TABLES,
    *P7_NATIVE_TYPE_EXPOSURE_TABLES,
    *P7_NATIVE_TYPE_EVIDENCE_TABLES,
    *P7_NATIVE_EXPOSURE_TABLES,
    *P7_FINITE_COURSE_MAPPING_TABLES,
)
EPOCH_TABLE = "tutor_item_supply_user_epochs"

P2_SHARED_TABLES: tuple[str, ...] = SHARED_TABLES[:14]
P2_PRIVATE_TABLES: tuple[str, ...] = PRIVATE_TABLES[:22]
# Preserve the historical P3 family; later native staging is classified separately.
P3_SHARED_TABLES: tuple[str, ...] = SHARED_TABLES[14:26]
P3_PRIVATE_TABLES: tuple[str, ...] = PRIVATE_TABLES[22:29]
P4_PRIVATE_TABLES: tuple[str, ...] = PRIVATE_TABLES[29:31]
# Keep the historical 470 execution-only family stable as later private facts
# join the exhaustive PRIVATE_TABLES inventory/export/cutover derivation.
P6_PRIVATE_TABLES: tuple[str, ...] = PRIVATE_TABLES[31:34]
