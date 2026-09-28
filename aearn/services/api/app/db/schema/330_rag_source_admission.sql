-- C review/admission facts are distinct from B quarantine and the six corpus tables.
-- A stored row does not authenticate reviewer or claim evidence: trusted repositories
-- must verify current policy and actual provenance before their one-shot writes.
CREATE TABLE IF NOT EXISTS rag_source_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  registered_capture_id uuid UNIQUE REFERENCES rag_registered_source_captures(id) ON DELETE RESTRICT,
  candidate_capture_id uuid UNIQUE REFERENCES rag_candidate_captures(id) ON DELETE RESTRICT,
  source_handle text NOT NULL CHECK (source_handle ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  document_handle text NOT NULL UNIQUE CHECK (document_handle ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  subject_id text NOT NULL,
  subject_version text NOT NULL,
  facets text[] NOT NULL CHECK (cardinality(facets) BETWEEN 1 AND 24),
  document_revision text NOT NULL CHECK (char_length(document_revision) BETWEEN 1 AND 80),
  document_hash text NOT NULL CHECK (document_hash ~ '^[0-9a-f]{64}$'),
  lineage_family text NOT NULL CHECK (lineage_family ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  origin text NOT NULL CHECK (origin IN ('official','maintainer','tutorial','repository','community','blog')),
  reading_level text NOT NULL CHECK (reading_level IN ('beginner','intermediate','advanced')),
  status text NOT NULL CHECK (status IN ('reviewed','quarantined')),
  quality_code text NOT NULL CHECK (quality_code ~ '^[A-Z][A-Z0-9_]{0,79}$'),
  reading_fit text NOT NULL CHECK (reading_fit IN ('suitable','unsuitable','unknown')),
  version_fit text NOT NULL CHECK (version_fit IN ('current','stale','unknown')),
  technical_status text NOT NULL CHECK (technical_status IN ('correct','incorrect','unknown')),
  conflict_status text NOT NULL CHECK (conflict_status IN ('resolved','unresolved','unknown')),
  known_error text NOT NULL CHECK (known_error IN ('absent','present','unknown')),
  covered_facets text[] NOT NULL CHECK (cardinality(covered_facets) BETWEEN 0 AND 24
    AND covered_facets <@ facets),
  quality_evidence_hash text NOT NULL CHECK (quality_evidence_hash ~ '^[0-9a-f]{64}$'),
  storage_receipt_id text NOT NULL CHECK (storage_receipt_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  license_id text NOT NULL CHECK (license_id ~ '^[A-Za-z0-9][A-Za-z0-9.-]{0,79}$'),
  allowed_usages text[] NOT NULL DEFAULT '{}' CHECK (cardinality(allowed_usages)<=3
    AND allowed_usages <@ ARRAY['main_teaching','supplementary_explanation','assessment_evidence']::text[]),
  immutable_history_allowed boolean NOT NULL DEFAULT false,
  policy_id text NOT NULL CHECK (policy_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  policy_generation integer NOT NULL CHECK (policy_generation>=1),
  root_id text NOT NULL REFERENCES rag_budget_authority_roots(root_id) ON DELETE RESTRICT,
  review_receipt_hash text NOT NULL CHECK (review_receipt_hash ~ '^[0-9a-f]{64}$'),
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((registered_capture_id IS NOT NULL) <> (candidate_capture_id IS NOT NULL)),
  CHECK (status='reviewed' OR (cardinality(allowed_usages)=0 AND NOT immutable_history_allowed)),
  UNIQUE(id,source_handle,document_handle,document_hash,subject_id,subject_version)
);
-- Additive replay of a partially bootstrapped disposable C database. Existing
-- reviews cannot be assigned fabricated verifier facts; nonempty tables fail the
-- NOT NULL promotion and require manual reconciliation instead.
ALTER TABLE rag_source_reviews ADD COLUMN IF NOT EXISTS reading_fit text;
ALTER TABLE rag_source_reviews ADD COLUMN IF NOT EXISTS version_fit text;
ALTER TABLE rag_source_reviews ADD COLUMN IF NOT EXISTS technical_status text;
ALTER TABLE rag_source_reviews ADD COLUMN IF NOT EXISTS conflict_status text;
ALTER TABLE rag_source_reviews ADD COLUMN IF NOT EXISTS known_error text;
ALTER TABLE rag_source_reviews ADD COLUMN IF NOT EXISTS covered_facets text[];
ALTER TABLE rag_source_reviews ADD COLUMN IF NOT EXISTS quality_evidence_hash text;
ALTER TABLE rag_source_reviews ADD COLUMN IF NOT EXISTS storage_receipt_id text;
ALTER TABLE rag_source_reviews ALTER COLUMN reading_fit SET NOT NULL;
ALTER TABLE rag_source_reviews ALTER COLUMN version_fit SET NOT NULL;
ALTER TABLE rag_source_reviews ALTER COLUMN technical_status SET NOT NULL;
ALTER TABLE rag_source_reviews ALTER COLUMN conflict_status SET NOT NULL;
ALTER TABLE rag_source_reviews ALTER COLUMN known_error SET NOT NULL;
ALTER TABLE rag_source_reviews ALTER COLUMN covered_facets SET NOT NULL;
ALTER TABLE rag_source_reviews ALTER COLUMN quality_evidence_hash SET NOT NULL;
ALTER TABLE rag_source_reviews ALTER COLUMN storage_receipt_id SET NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_rag_c_review_facts') THEN
    ALTER TABLE rag_source_reviews ADD CONSTRAINT chk_rag_c_review_facts CHECK (
      reading_fit IN ('suitable','unsuitable','unknown') AND
      version_fit IN ('current','stale','unknown') AND
      technical_status IN ('correct','incorrect','unknown') AND
      conflict_status IN ('resolved','unresolved','unknown') AND
      known_error IN ('absent','present','unknown') AND
      cardinality(covered_facets) BETWEEN 0 AND 24 AND covered_facets <@ facets AND
      quality_evidence_hash ~ '^[0-9a-f]{64}$' AND
      storage_receipt_id ~ '^[a-z][a-z0-9._:-]{2,159}$');
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_rag_source_reviews_scope
 ON rag_source_reviews(subject_id,subject_version,source_handle);
CREATE TABLE IF NOT EXISTS rag_source_admissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_id uuid NOT NULL UNIQUE REFERENCES rag_source_reviews(id) ON DELETE RESTRICT,
  receipt_handle text NOT NULL UNIQUE CHECK (receipt_handle ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  allowed_usages text[] NOT NULL CHECK (cardinality(allowed_usages) BETWEEN 1 AND 3
    AND allowed_usages <@ ARRAY['main_teaching','supplementary_explanation','assessment_evidence']::text[]),
  policy_generation integer NOT NULL CHECK (policy_generation>=1),
  receipt_hash text NOT NULL CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
  active boolean NOT NULL DEFAULT true,
  revoked_at timestamptz,
  admitted_at timestamptz NOT NULL DEFAULT now(),
  CHECK (revoked_at IS NULL OR NOT active),
  UNIQUE(id,review_id)
);
CREATE TABLE IF NOT EXISTS rag_source_claim_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  admission_id uuid NOT NULL REFERENCES rag_source_admissions(id) ON DELETE RESTRICT,
  claim_hash text NOT NULL CHECK (claim_hash ~ '^[0-9a-f]{64}$'),
  demand_hash text NOT NULL CHECK (demand_hash ~ '^[0-9a-f]{64}$'),
  subject_id text NOT NULL,
  subject_version text NOT NULL,
  source_document_hash text NOT NULL CHECK (source_document_hash ~ '^[0-9a-f]{64}$'),
  applicability_hash text NOT NULL CHECK (applicability_hash ~ '^[0-9a-f]{64}$'),
  method text NOT NULL CHECK (method IN ('independent_source','isolated_execution')),
  independent_admission_id uuid REFERENCES rag_source_admissions(id) ON DELETE RESTRICT,
  independent_document_hash text CHECK (independent_document_hash ~ '^[0-9a-f]{64}$'),
  execution_receipt_handle text CHECK (execution_receipt_handle ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  verification_receipt_hash text NOT NULL CHECK (verification_receipt_hash ~ '^[0-9a-f]{64}$'),
  verified_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  CHECK ((method='independent_source' AND independent_admission_id IS NOT NULL
           AND execution_receipt_handle IS NULL AND independent_admission_id<>admission_id AND independent_document_hash IS NOT NULL)
      OR (method='isolated_execution' AND independent_admission_id IS NULL
           AND independent_document_hash IS NULL AND execution_receipt_handle IS NOT NULL)),
  UNIQUE(admission_id,claim_hash,demand_hash,applicability_hash,method)
);

-- Additive replay for disposable C databases first bootstrapped before the
-- exact demand/scope claim coordinates were introduced. Existing nonempty rows
-- without these columns fail SET NOT NULL rather than being given fake values.
ALTER TABLE rag_source_claim_receipts ADD COLUMN IF NOT EXISTS demand_hash text;
ALTER TABLE rag_source_claim_receipts ADD COLUMN IF NOT EXISTS subject_id text;
ALTER TABLE rag_source_claim_receipts ADD COLUMN IF NOT EXISTS subject_version text;
ALTER TABLE rag_source_claim_receipts ADD COLUMN IF NOT EXISTS source_document_hash text;
ALTER TABLE rag_source_claim_receipts ADD COLUMN IF NOT EXISTS independent_document_hash text;
ALTER TABLE rag_source_claim_receipts ALTER COLUMN demand_hash SET NOT NULL;
ALTER TABLE rag_source_claim_receipts ALTER COLUMN subject_id SET NOT NULL;
ALTER TABLE rag_source_claim_receipts ALTER COLUMN subject_version SET NOT NULL;
ALTER TABLE rag_source_claim_receipts ALTER COLUMN source_document_hash SET NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_rag_c_claim_exact_hashes') THEN
    ALTER TABLE rag_source_claim_receipts ADD CONSTRAINT chk_rag_c_claim_exact_hashes
      CHECK (demand_hash ~ '^[0-9a-f]{64}$' AND source_document_hash ~ '^[0-9a-f]{64}$'
        AND (independent_document_hash IS NULL OR independent_document_hash ~ '^[0-9a-f]{64}$'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_rag_c_claim_independent_hash') THEN
    ALTER TABLE rag_source_claim_receipts ADD CONSTRAINT chk_rag_c_claim_independent_hash
      CHECK ((method='independent_source' AND independent_document_hash IS NOT NULL)
          OR (method='isolated_execution' AND independent_document_hash IS NULL));
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_c_claim_exact_demand
 ON rag_source_claim_receipts(admission_id,claim_hash,demand_hash,applicability_hash,method);
CREATE TABLE IF NOT EXISTS rag_corpus_admission_links (
  corpus_id uuid NOT NULL,
  source_id text NOT NULL,
  document_id text NOT NULL,
  admission_id uuid NOT NULL REFERENCES rag_source_admissions(id) ON DELETE RESTRICT,
  document_hash text NOT NULL CHECK (document_hash ~ '^[0-9a-f]{64}$'),
  scope_facets text[] NOT NULL CHECK (cardinality(scope_facets) BETWEEN 1 AND 24),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(corpus_id,document_id),
  UNIQUE(corpus_id,admission_id),
  FOREIGN KEY(corpus_id,document_id)
    REFERENCES grounding_corpus_documents(corpus_version_id,document_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS rag_corpus_validation_receipts (
  corpus_id uuid PRIMARY KEY REFERENCES grounding_corpus_versions(id) ON DELETE RESTRICT,
  validation_event_id uuid NOT NULL UNIQUE REFERENCES grounding_corpus_events(id) ON DELETE RESTRICT,
  admission_digest text NOT NULL CHECK (admission_digest ~ '^[0-9a-f]{64}$'),
  coverage_digest text NOT NULL CHECK (coverage_digest ~ '^[0-9a-f]{64}$'),
  review_policy_generation integer NOT NULL CHECK (review_policy_generation>=1),
  summary_hash text NOT NULL CHECK (summary_hash ~ '^[0-9a-f]{64}$'),
  partial_coverage boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION rag_source_review_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE original_hash text;
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'source review immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.registered_capture_id IS NOT NULL THEN
    SELECT capture.fetched_sha256 INTO original_hash
      FROM rag_registered_source_captures capture
      WHERE capture.id=NEW.registered_capture_id AND capture.cleared_at IS NULL
        AND capture.captured_body IS NOT NULL;
    SELECT policy.* INTO policy_row FROM rag_registered_source_policies policy
      JOIN rag_registered_source_captures capture ON capture.policy_id=policy.policy_id
        AND capture.generation=policy.generation
      WHERE capture.id=NEW.registered_capture_id;
    IF policy_row.policy_id IS NULL OR NEW.source_handle<>policy_row.source_handle OR
       NEW.subject_id<>policy_row.subject_id OR
       NEW.subject_version<>policy_row.subject_version OR
       NOT NEW.facets <@ policy_row.facets OR
       NEW.origin<>policy_row.origin OR NEW.reading_level<>policy_row.reading_level OR
       NEW.license_id<>policy_row.license_id OR
       NEW.policy_id<>policy_row.policy_id OR
       NEW.policy_generation<>policy_row.generation OR
       NEW.root_id<>policy_row.root_id OR
       NOT NEW.allowed_usages <@ policy_row.allowed_usages OR
       (NEW.immutable_history_allowed AND NOT policy_row.immutable_history_allowed) OR
       (NEW.status='reviewed' AND (policy_row.enabled IS NOT TRUE OR
            policy_row.revoked_at IS NOT NULL OR policy_row.expires_at<=clock_timestamp())) THEN
      RAISE EXCEPTION 'review source scope or permission mismatch' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT full_sha256 INTO original_hash FROM rag_candidate_captures
      WHERE id=NEW.candidate_capture_id AND capture_kind='full' AND cleared_at IS NULL;
  END IF;
  IF original_hash IS NULL OR original_hash<>NEW.document_hash THEN
    RAISE EXCEPTION 'review document hash mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_source_review_guard ON rag_source_reviews;
CREATE TRIGGER trg_rag_source_review_guard BEFORE INSERT OR UPDATE OR DELETE ON rag_source_reviews
 FOR EACH ROW EXECUTE FUNCTION rag_source_review_guard();
CREATE OR REPLACE FUNCTION rag_source_admission_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE reviewed rag_source_reviews%ROWTYPE;
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'source admission deletion denied' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL OR NEW.active OR
       (to_jsonb(NEW)-'active'-'revoked_at') IS DISTINCT FROM
       (to_jsonb(OLD)-'active'-'revoked_at') THEN
      RAISE EXCEPTION 'source admission immutable or revoked' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO reviewed FROM rag_source_reviews WHERE id=NEW.review_id;
  IF NOT FOUND OR reviewed.status<>'reviewed' OR
     NOT NEW.allowed_usages <@ reviewed.allowed_usages OR
     NEW.policy_generation<>reviewed.policy_generation THEN
    RAISE EXCEPTION 'source review not admitted' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_source_admission_guard ON rag_source_admissions;
CREATE TRIGGER trg_rag_source_admission_guard BEFORE INSERT OR UPDATE OR DELETE ON rag_source_admissions
 FOR EACH ROW EXECUTE FUNCTION rag_source_admission_guard();
CREATE OR REPLACE FUNCTION rag_corpus_link_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE review_row rag_source_reviews%ROWTYPE;
DECLARE registered_policy rag_registered_source_policies%ROWTYPE;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'corpus admission link immutable' USING ERRCODE='23514';
  END IF;
  SELECT review.* INTO review_row FROM rag_source_reviews review
    JOIN rag_source_admissions admission ON admission.review_id=review.id
    WHERE admission.id=NEW.admission_id AND admission.active FOR SHARE OF review,admission;
  IF NOT FOUND OR NOT review_row.immutable_history_allowed OR
     review_row.document_hash<>NEW.document_hash THEN
    RAISE EXCEPTION 'corpus content retention not admitted' USING ERRCODE='23514';
  END IF;
  IF review_row.registered_capture_id IS NOT NULL THEN
    SELECT * INTO registered_policy FROM rag_registered_source_policies
      WHERE policy_id=review_row.policy_id FOR SHARE;
    IF registered_policy.policy_id IS NULL OR
       registered_policy.generation<>review_row.policy_generation OR
       registered_policy.immutable_history_allowed IS NOT TRUE OR
       registered_policy.enabled IS NOT TRUE OR
       registered_policy.revoked_at IS NOT NULL THEN
      RAISE EXCEPTION 'registered formal history grant missing' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_corpus_link_guard ON rag_corpus_admission_links;
CREATE TRIGGER trg_rag_corpus_link_guard BEFORE INSERT OR UPDATE OR DELETE ON rag_corpus_admission_links
 FOR EACH ROW EXECUTE FUNCTION rag_corpus_link_guard();
CREATE OR REPLACE FUNCTION rag_source_claim_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE primary_review rag_source_reviews%ROWTYPE;
DECLARE secondary_review rag_source_reviews%ROWTYPE;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'claim receipt immutable' USING ERRCODE='23514';
  END IF;
  -- No execution verifier adapter is installed in C's default-off runtime.
  -- A text handle alone is not proof that a process was actually isolated/run.
  IF TG_TABLE_NAME='rag_source_claim_receipts' THEN
    IF NEW.method='isolated_execution' THEN
      RAISE EXCEPTION 'isolated execution verifier unavailable' USING ERRCODE='23514';
    END IF;
    SELECT review.* INTO primary_review FROM rag_source_reviews review
      JOIN rag_source_admissions admission ON admission.review_id=review.id
      WHERE admission.id=NEW.admission_id AND admission.active FOR SHARE OF review,admission;
    SELECT review.* INTO secondary_review FROM rag_source_reviews review
      JOIN rag_source_admissions admission ON admission.review_id=review.id
      WHERE admission.id=NEW.independent_admission_id AND admission.active FOR SHARE OF review,admission;
    IF primary_review.id IS NULL OR secondary_review.id IS NULL OR
       primary_review.document_hash<>NEW.source_document_hash OR
       secondary_review.document_hash<>NEW.independent_document_hash OR
       primary_review.lineage_family=secondary_review.lineage_family OR
       primary_review.subject_id<>NEW.subject_id OR
       secondary_review.subject_id<>NEW.subject_id OR
       primary_review.subject_version<>NEW.subject_version OR
       secondary_review.subject_version<>NEW.subject_version THEN
      RAISE EXCEPTION 'claim lineage or scope unverified' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_source_claim_guard ON rag_source_claim_receipts;
CREATE TRIGGER trg_rag_source_claim_guard BEFORE INSERT OR UPDATE OR DELETE ON rag_source_claim_receipts
 FOR EACH ROW EXECUTE FUNCTION rag_source_claim_guard();
DROP TRIGGER IF EXISTS trg_rag_corpus_validation_guard ON rag_corpus_validation_receipts;
CREATE TRIGGER trg_rag_corpus_validation_guard BEFORE UPDATE OR DELETE ON rag_corpus_validation_receipts
 FOR EACH ROW EXECUTE FUNCTION rag_source_claim_guard();
