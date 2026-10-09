-- Fresh-only bounded assessment source authority. No history reuse or new budget root.
-- Only the independent service can authenticate real sealed source oracle execution;
-- these SQL guards enforce coordinates/current grants, never claim FK/hash authenticity.
CREATE TABLE IF NOT EXISTS rag_assessment_source_evidence (
  id uuid PRIMARY KEY,
  capture_id uuid NOT NULL UNIQUE REFERENCES rag_registered_source_captures(id) ON DELETE RESTRICT,
  source_handle text NOT NULL CHECK (source_handle ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  document_handle text NOT NULL UNIQUE CHECK (document_handle ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  document_hash text NOT NULL CHECK (document_hash ~ '^[0-9a-f]{64}$'),
  policy_id text NOT NULL REFERENCES rag_registered_source_policies(policy_id) ON DELETE RESTRICT,
  policy_generation integer NOT NULL CHECK (policy_generation>=1),
  root_id text NOT NULL REFERENCES rag_budget_authority_roots(root_id) ON DELETE RESTRICT,
  profile_id text NOT NULL CHECK (profile_id IN ('python-sum-print-source-v1','sqlite-filter-order-source-v1')),
  demand_hash text NOT NULL CHECK (demand_hash ~ '^[0-9a-f]{64}$'),
  claim_hash text NOT NULL CHECK (claim_hash ~ '^[0-9a-f]{64}$'),
  execution_handle text NOT NULL UNIQUE CHECK (execution_handle ~ '^source-execution\.[0-9a-f]{32}$'),
  claim_handle text NOT NULL UNIQUE CHECK (claim_handle ~ '^source-claim\.[0-9a-f]{32}$'),
  service_key_id text NOT NULL CHECK (service_key_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  signed_proof jsonb NOT NULL CHECK (jsonb_typeof(signed_proof)='object'),
  proof_hash text NOT NULL CHECK (proof_hash ~ '^[0-9a-f]{64}$'),
  terminal_hash text NOT NULL CHECK (terminal_hash ~ '^[0-9a-f]{64}$'),
  issued_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  CHECK (issued_at<expires_at AND expires_at<=issued_at+interval '24 hours')
);
ALTER TABLE rag_source_reviews ADD COLUMN IF NOT EXISTS assessment_evidence_id uuid
  REFERENCES rag_assessment_source_evidence(id) ON DELETE RESTRICT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_review_assessment_evidence
  ON rag_source_reviews(assessment_evidence_id) WHERE assessment_evidence_id IS NOT NULL;
ALTER TABLE rag_source_claim_receipts ADD COLUMN IF NOT EXISTS assessment_evidence_id uuid
  REFERENCES rag_assessment_source_evidence(id) ON DELETE RESTRICT;
ALTER TABLE rag_source_claim_receipts ADD COLUMN IF NOT EXISTS receipt_handle text;
ALTER TABLE rag_source_claim_receipts ADD COLUMN IF NOT EXISTS applicability text;
ALTER TABLE rag_source_claim_receipts ADD COLUMN IF NOT EXISTS scope_facets text[];
ALTER TABLE rag_source_claim_receipts ADD COLUMN IF NOT EXISTS execution_scope_json jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_claim_receipt_handle
  ON rag_source_claim_receipts(receipt_handle) WHERE receipt_handle IS NOT NULL;

CREATE OR REPLACE FUNCTION rag_assessment_source_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE capture rag_registered_source_captures%ROWTYPE;
DECLARE policy rag_registered_source_policies%ROWTYPE;
DECLARE root rag_budget_authority_roots%ROWTYPE;
DECLARE proof jsonb;
DECLARE prepared jsonb;
DECLARE clock timestamptz := clock_timestamp();
BEGIN
  IF TG_OP='UPDATE' THEN
    IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL OR NEW.revoked_at<OLD.issued_at OR
       (to_jsonb(NEW)-'revoked_at') IS DISTINCT FROM (to_jsonb(OLD)-'revoked_at') THEN
      RAISE EXCEPTION 'assessment proof immutable' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP<>'INSERT' OR current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE EXCEPTION 'assessment proof isolated owner required' USING ERRCODE='23514';
  END IF;
  SELECT * INTO capture FROM rag_registered_source_captures WHERE id=NEW.capture_id FOR SHARE;
  SELECT * INTO policy FROM rag_registered_source_policies WHERE policy_id=NEW.policy_id FOR SHARE;
  SELECT * INTO root FROM rag_budget_authority_roots WHERE root_id=NEW.root_id FOR SHARE;
  proof := NEW.signed_proof->'payload';
  prepared := proof->'prepared';
  IF capture.id IS NULL OR policy.policy_id IS NULL OR root.root_id IS NULL OR
     capture.policy_id<>policy.policy_id OR capture.generation<>policy.generation OR
     capture.cleared_at IS NOT NULL OR capture.captured_body IS NULL OR
     capture.evidence_level<>'live_egress_attested' OR capture.transport_proof IS NULL OR
     capture.fetched_sha256<>NEW.document_hash OR capture.retention_until<=clock OR
     policy.enabled IS NOT TRUE OR policy.revoked_at IS NOT NULL OR
     policy.expires_at<=clock OR policy.retention_until<=clock OR
     policy.immutable_history_allowed IS NOT TRUE OR
     NOT 'assessment_evidence'=ANY(policy.allowed_usages) OR
     policy.source_handle<>NEW.source_handle OR policy.generation<>NEW.policy_generation OR
     policy.root_id<>NEW.root_id OR policy.origin<>'official' OR
     root.enabled IS NOT TRUE OR root.policy_id<>policy.policy_id OR
     root.policy_generation<>policy.generation OR root.period_start>clock OR
     root.period_end<=clock OR root.delegation_expires_at<=clock OR
     NEW.revoked_at IS NOT NULL OR NEW.issued_at>clock OR NEW.expires_at<=clock OR
     NEW.expires_at>LEAST(policy.expires_at,policy.retention_until,capture.retention_until,
                           root.period_end,root.delegation_expires_at) OR
     (NEW.profile_id='python-sum-print-source-v1' AND
       (policy.canonical_url<>'https://docs.python.org/3/library/functions.html' OR
        policy.subject_id<>'route.python' OR policy.facets<>ARRAY['fundamentals']::text[])) OR
     (NEW.profile_id='sqlite-filter-order-source-v1' AND
       (policy.canonical_url<>'https://www.sqlite.org/lang_select.html' OR
        policy.subject_id<>'route.sql' OR policy.facets<>ARRAY['queries']::text[])) OR
     (NEW.signed_proof->>'service_key_id') IS DISTINCT FROM NEW.service_key_id OR
     (NEW.signed_proof->>'signature_hex') IS NULL OR
     (NEW.signed_proof->>'signature_hex') !~ '^[0-9a-f]{128}$' OR
     (proof->>'format') IS DISTINCT FROM 'aearn.rag.fresh-assessment-source.v1' OR
     (proof->>'evidence_id') IS DISTINCT FROM NEW.id::text OR
     (prepared->>'capture_id') IS DISTINCT FROM NEW.capture_id::text OR
     (prepared->>'document_hash') IS DISTINCT FROM NEW.document_hash OR
     (prepared->>'source_handle') IS DISTINCT FROM NEW.source_handle OR
     (prepared->>'document_handle') IS DISTINCT FROM NEW.document_handle OR
     (prepared->>'policy_id') IS DISTINCT FROM NEW.policy_id OR
     (prepared->>'policy_generation') IS DISTINCT FROM NEW.policy_generation::text OR
     (prepared->'budget'->>'root_id') IS DISTINCT FROM NEW.root_id OR
     (prepared->'demand'->>'demand_hash') IS DISTINCT FROM NEW.demand_hash OR
     (prepared->'demand'->>'purpose') IS DISTINCT FROM 'assessment_evidence' OR
     (prepared->>'profile_id') IS DISTINCT FROM NEW.profile_id OR
     (proof->'terminal'->>'mode') IS DISTINCT FROM 'live' OR
     (proof->'terminal'->>'isolation') IS DISTINCT FROM 'approved_os_boundary' OR
     (proof->'terminal'->>'probe_name') IS DISTINCT FROM 'source_assessment_oracle' OR
     (proof->'terminal'->'result'->>'status') IS DISTINCT FROM 'success' OR
     NEW.execution_handle IS DISTINCT FROM ('source-execution.' || replace(NEW.id::text,'-','')) OR
     NEW.claim_handle IS DISTINCT FROM ('source-claim.' || replace(proof->>'claim_id','-','')) THEN
    RAISE EXCEPTION 'fresh assessment source proof coordinates denied' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_assessment_source_evidence_guard ON rag_assessment_source_evidence;
CREATE TRIGGER trg_rag_assessment_source_evidence_guard BEFORE INSERT OR UPDATE OR DELETE
  ON rag_assessment_source_evidence FOR EACH ROW EXECUTE FUNCTION rag_assessment_source_evidence_guard();

-- Additional proof branch, followed independently by unchanged original 330 review guard.
CREATE OR REPLACE FUNCTION rag_assessment_source_review_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE evidence rag_assessment_source_evidence%ROWTYPE;
BEGIN
  IF NEW.assessment_evidence_id IS NULL THEN
    IF 'assessment_evidence'=ANY(NEW.allowed_usages) THEN
      RAISE EXCEPTION 'signed assessment source proof required' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO evidence FROM rag_assessment_source_evidence WHERE id=NEW.assessment_evidence_id FOR SHARE;
  IF current_database()<>'aearn_b1d_sandbox_20261001' OR evidence.id IS NULL OR
     evidence.revoked_at IS NOT NULL OR evidence.expires_at<=clock_timestamp() OR
     NEW.allowed_usages<>ARRAY['assessment_evidence']::text[] OR
     NEW.id::text IS DISTINCT FROM evidence.signed_proof->'payload'->>'review_id' OR
     NEW.registered_capture_id IS DISTINCT FROM evidence.capture_id OR NEW.candidate_capture_id IS NOT NULL OR
     NEW.source_handle<>evidence.source_handle OR NEW.document_handle<>evidence.document_handle OR
     NEW.document_hash<>evidence.document_hash OR NEW.document_revision<>evidence.document_hash OR
     NEW.policy_id<>evidence.policy_id OR NEW.policy_generation<>evidence.policy_generation OR
     NEW.root_id<>evidence.root_id OR NEW.review_receipt_hash<>evidence.proof_hash OR
     NEW.quality_evidence_hash<>evidence.proof_hash OR NEW.status<>'reviewed' OR
     NEW.quality_code<>'QUALIFIED' THEN
    RAISE EXCEPTION 'assessment review proof binding denied' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_assessment_source_review_guard ON rag_source_reviews;
CREATE TRIGGER trg_rag_assessment_source_review_guard BEFORE INSERT ON rag_source_reviews
  FOR EACH ROW EXECUTE FUNCTION rag_assessment_source_review_guard();

CREATE OR REPLACE FUNCTION rag_source_claim_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE primary_review rag_source_reviews%ROWTYPE;
DECLARE secondary_review rag_source_reviews%ROWTYPE;
DECLARE evidence rag_assessment_source_evidence%ROWTYPE;
DECLARE primary_admission rag_source_admissions%ROWTYPE;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'claim receipt immutable' USING ERRCODE='23514';
  END IF;
  -- No execution verifier adapter is installed in C's default-off runtime.
  -- A text handle alone is not proof that a process was actually isolated/run.
  IF TG_TABLE_NAME='rag_source_claim_receipts' THEN
    IF NEW.method='isolated_execution' THEN
      SELECT * INTO evidence FROM rag_assessment_source_evidence WHERE id=NEW.assessment_evidence_id FOR SHARE;
      SELECT * INTO primary_admission FROM rag_source_admissions WHERE id=NEW.admission_id FOR SHARE;
      SELECT * INTO primary_review FROM rag_source_reviews WHERE id=primary_admission.review_id FOR SHARE;
      IF current_database()<>'aearn_b1d_sandbox_20261001' OR evidence.id IS NULL OR
         evidence.revoked_at IS NOT NULL OR evidence.expires_at<=clock_timestamp() OR
         primary_admission.id IS NULL OR primary_admission.active IS NOT TRUE OR
         primary_admission.revoked_at IS NOT NULL OR primary_review.id IS NULL OR
         primary_review.assessment_evidence_id IS DISTINCT FROM evidence.id OR
         primary_admission.allowed_usages<>ARRAY['assessment_evidence']::text[] OR
         NEW.id::text IS DISTINCT FROM evidence.signed_proof->'payload'->>'claim_id' OR
         primary_admission.id::text IS DISTINCT FROM evidence.signed_proof->'payload'->>'admission_id' OR
         NEW.receipt_handle IS DISTINCT FROM evidence.claim_handle OR
         NEW.execution_receipt_handle IS DISTINCT FROM evidence.execution_handle OR
         NEW.verification_receipt_hash<>evidence.proof_hash OR NEW.claim_hash<>evidence.claim_hash OR
         NEW.demand_hash<>evidence.demand_hash OR NEW.source_document_hash<>evidence.document_hash OR
         NEW.subject_id<>primary_review.subject_id OR NEW.subject_version<>primary_review.subject_version OR
         NEW.scope_facets IS DISTINCT FROM primary_review.facets OR
         NEW.applicability IS NULL OR NEW.execution_scope_json IS NULL OR
         NEW.revoked_at IS NOT NULL THEN
        RAISE EXCEPTION 'signed source execution claim binding denied' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
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

-- Existing trigger names remain installed by 330; only this fresh proof branch changes.
