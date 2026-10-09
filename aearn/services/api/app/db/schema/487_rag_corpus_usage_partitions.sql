-- Purpose-partitioned snapshots still use the existing single corpus owner/CAS.
-- A per-document policy generation is not a corpus-global generation counter.
-- No existing grants/reviews/signatures are upgraded or rewritten.
ALTER TABLE rag_corpus_validation_receipts
  ADD COLUMN IF NOT EXISTS audit_policy_version text NOT NULL DEFAULT 'dynamic-c-v1';
ALTER TABLE rag_corpus_validation_receipts
  ALTER COLUMN review_policy_generation DROP NOT NULL;
ALTER TABLE rag_corpus_validation_receipts
  DROP CONSTRAINT IF EXISTS rag_corpus_validation_audit_policy_check;
ALTER TABLE rag_corpus_validation_receipts
  ADD CONSTRAINT rag_corpus_validation_audit_policy_check CHECK (
    (audit_policy_version='dynamic-c-v1' AND review_policy_generation IS NOT NULL
      AND review_policy_generation>=1) OR
    (audit_policy_version='dynamic-c-purpose-v2' AND review_policy_generation IS NULL)
  );

CREATE OR REPLACE FUNCTION rag_corpus_usage_partition_receipt_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE corpus grounding_corpus_versions%ROWTYPE;
BEGIN
  SELECT * INTO corpus FROM grounding_corpus_versions WHERE id=NEW.corpus_id FOR SHARE;
  IF corpus.id IS NULL OR corpus.state<>'validated' OR corpus.summary_hash IS DISTINCT FROM NEW.summary_hash OR
     (corpus.coverage_policy_version='dynamic-c-purpose-v2' AND
       (NEW.audit_policy_version<>'dynamic-c-purpose-v2' OR NEW.review_policy_generation IS NOT NULL)) OR
     (corpus.coverage_policy_version<>'dynamic-c-purpose-v2' AND
       (NEW.audit_policy_version<>'dynamic-c-v1' OR NEW.review_policy_generation IS NULL)) THEN
    RAISE EXCEPTION 'corpus purpose audit receipt denied' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_corpus_usage_partition_receipt ON rag_corpus_validation_receipts;
CREATE TRIGGER trg_rag_corpus_usage_partition_receipt
  BEFORE INSERT ON rag_corpus_validation_receipts
  FOR EACH ROW EXECUTE FUNCTION rag_corpus_usage_partition_receipt_guard();
