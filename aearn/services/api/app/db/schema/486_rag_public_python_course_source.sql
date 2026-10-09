-- Native public finite Python source profiles. No private learner/DraftScope,
-- new permission roots, receipt renewal or public runtime/consumer registration.
-- Legacy signed profiles and all historical rows remain byte-for-byte unchanged.
ALTER TABLE rag_assessment_source_evidence
  DROP CONSTRAINT IF EXISTS rag_assessment_source_evidence_profile_id_check;
ALTER TABLE rag_assessment_source_evidence
  ADD CONSTRAINT rag_assessment_source_evidence_profile_id_check CHECK (
    profile_id IN ('python-sum-print-source-v1','sqlite-filter-order-source-v1','python-sum-print-source-v2','python-state-source-v1','python-binding-source-v1')
  ) NOT VALID;
-- Transitional bootstrap subset only; 488 restores the closed fully validated set.

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
     (NEW.profile_id='python-sum-print-source-v2' AND
       (policy.canonical_url<>'https://docs.python.org/3/builtins/functions.html' OR
        policy.subject_id<>'route.python' OR policy.facets<>ARRAY['fundamentals']::text[])) OR
     (NEW.profile_id='sqlite-filter-order-source-v1' AND
       (policy.canonical_url<>'https://www.sqlite.org/lang_select.html' OR
        policy.subject_id<>'route.sql' OR policy.facets<>ARRAY['queries']::text[])) OR
     (NEW.profile_id IN ('python-state-source-v1','python-binding-source-v1') AND
       (policy.canonical_url<>'https://docs.python.org/3/reference/simple_stmts.html' OR
        policy.subject_id<>'route.python' OR policy.subject_version<>'1.0' OR
        policy.facets<>ARRAY['fundamentals']::text[] OR
        (prepared->'demand'->>'node_ref') IS DISTINCT FROM
          CASE WHEN NEW.profile_id='python-state-source-v1'
            THEN 'target.python-state-update-v1' ELSE 'target.python-kc-binding-v1' END OR
        (prepared->'demand'->>'plan_ref') IS NULL OR
        (prepared->'demand'->>'plan_ref') NOT LIKE
          CASE WHEN NEW.profile_id='python-state-source-v1'
            THEN 'course.python-state-update-v1.%' ELSE 'course.python-kc-binding-v1.%' END)) OR
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
