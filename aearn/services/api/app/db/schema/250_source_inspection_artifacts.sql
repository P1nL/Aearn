-- Readonly source-inspection Artifact purpose and lifecycle shape.
ALTER TABLE tutor_learning_artifacts
  DROP CONSTRAINT IF EXISTS tutor_learning_artifacts_purpose_check;
ALTER TABLE tutor_learning_artifacts
  DROP CONSTRAINT IF EXISTS chk_tutor_learning_artifacts_purpose;
ALTER TABLE tutor_learning_artifacts
  ADD CONSTRAINT chk_tutor_learning_artifacts_purpose CHECK (
    purpose IN (
      'exercise', 'demonstration', 'knowledge_check', 'remediation',
      'transfer_check', 'code_review', 'sql_exploration', 'source_inspection',
      'result'
    )
  );

ALTER TABLE tutor_learning_artifacts
  DROP CONSTRAINT IF EXISTS chk_tutor_learning_artifacts_source_inspection_shape;
ALTER TABLE tutor_learning_artifacts
  ADD CONSTRAINT chk_tutor_learning_artifacts_source_inspection_shape CHECK (
    purpose <> 'source_inspection'
    OR (
      artifact_kind = 'source_inspector'
      AND presentation_kind = 'source_inspector_v1'
      AND state IN ('ready', 'superseded')
      AND NOT blocking
      AND allowed_actions_json = '[]'::jsonb
      AND active_attempt_id IS NULL
      AND active_attempt_summary_json IS NULL
    )
  );
