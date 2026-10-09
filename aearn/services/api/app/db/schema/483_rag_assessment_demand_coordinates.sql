-- A current immutable capture may support independently executed/signed evidence
-- for different frozen demands. This never renews or changes an existing proof.
-- Keep duplicate capture/demand rejection even when document handles differ.
-- All source/proof/root/time/expiry guards and other uniqueness remain unchanged.
ALTER TABLE rag_assessment_source_evidence
  DROP CONSTRAINT IF EXISTS rag_assessment_source_evidence_capture_id_key;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'rag_assessment_source_evidence'::regclass
      AND conname = 'rag_assessment_source_evidence_capture_demand_key'
  ) THEN
    ALTER TABLE rag_assessment_source_evidence
      ADD CONSTRAINT rag_assessment_source_evidence_capture_demand_key
      UNIQUE (capture_id, demand_hash);
  END IF;
END $$;

-- Legacy reviews still allow only one registered review per capture. Signed
-- assessment reviews instead bind their unique evidence id and frozen demand.
ALTER TABLE rag_source_reviews
  DROP CONSTRAINT IF EXISTS rag_source_reviews_registered_capture_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_review_legacy_registered_capture
  ON rag_source_reviews(registered_capture_id)
  WHERE assessment_evidence_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_review_registered_capture_assessment
  ON rag_source_reviews(registered_capture_id, assessment_evidence_id)
  WHERE assessment_evidence_id IS NOT NULL;
