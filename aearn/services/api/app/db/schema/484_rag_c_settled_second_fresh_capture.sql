-- One fresh generation-three capture after the exact second Python attempt
-- settles and expires. Both historical Python policies are generation one;
-- attempt order is not policy generation. No row, authorization, or budget is created by bootstrap.
-- NULL discriminators retain the 400/410/420 unknown-chain semantics unchanged.
ALTER TABLE rag_registered_final_followup_allowances
  ADD COLUMN IF NOT EXISTS settled_second_capture_id uuid;
ALTER TABLE rag_registered_final_followup_allowances
  ADD COLUMN IF NOT EXISTS settled_second_capture_sha256 text;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_capture_settled_second_exact
  ON rag_registered_source_captures(id,fetch_attempt_id,fetched_sha256);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
    WHERE conrelid='rag_registered_final_followup_allowances'::regclass
      AND conname='chk_rag_settled_second_capture') THEN
    ALTER TABLE rag_registered_final_followup_allowances
      ADD CONSTRAINT chk_rag_settled_second_capture CHECK (
        (settled_second_capture_id IS NULL AND settled_second_capture_sha256 IS NULL) OR
        (settled_second_capture_id IS NOT NULL AND settled_second_capture_sha256 IS NOT NULL
          AND settled_second_capture_sha256 ~ '^[0-9a-f]{64}$' AND generation=3));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
    WHERE conrelid='rag_registered_final_followup_allowances'::regclass
      AND conname='fk_rag_settled_second_capture_exact') THEN
    ALTER TABLE rag_registered_final_followup_allowances
      ADD CONSTRAINT fk_rag_settled_second_capture_exact
      FOREIGN KEY(settled_second_capture_id,latest_attempt_id,settled_second_capture_sha256)
      REFERENCES rag_registered_source_captures(id,fetch_attempt_id,fetched_sha256)
      ON DELETE RESTRICT;
  END IF;
END $$;

-- Separate operator-approved SQL deployment correction. The second actual GET
-- used a fresh generation-one policy; never relabel it as generation two.
ALTER TABLE rag_registered_final_followup_allowances
  ADD COLUMN IF NOT EXISTS settled_source_capture_id uuid;
ALTER TABLE rag_registered_final_followup_allowances
  ADD COLUMN IF NOT EXISTS settled_source_capture_sha256 text;
ALTER TABLE rag_registered_final_followup_allowances
  ADD COLUMN IF NOT EXISTS settled_source_failed_authorization_id uuid;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_settled_source_failed_attempt_exact
  ON rag_registered_fetch_attempts(id,supplemental_authorization_id,canonical_url_sha256);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
    WHERE conrelid='rag_registered_final_followup_allowances'::regclass
      AND conname='chk_rag_settled_source_correction') THEN
    ALTER TABLE rag_registered_final_followup_allowances
      ADD CONSTRAINT chk_rag_settled_source_correction CHECK (
        (settled_source_capture_id IS NULL AND settled_source_capture_sha256 IS NULL
          AND settled_source_failed_authorization_id IS NULL) OR
        (settled_source_capture_id IS NOT NULL AND settled_source_capture_sha256 IS NOT NULL
          AND settled_source_capture_sha256 ~ '^[0-9a-f]{64}$'
          AND settled_source_failed_authorization_id IS NOT NULL AND generation=3
          AND settled_second_capture_id IS NULL AND settled_second_capture_sha256 IS NULL));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
    WHERE conrelid='rag_registered_final_followup_allowances'::regclass
      AND conname='fk_rag_settled_source_capture_exact') THEN
    ALTER TABLE rag_registered_final_followup_allowances
      ADD CONSTRAINT fk_rag_settled_source_capture_exact
      FOREIGN KEY(settled_source_capture_id,original_attempt_id,settled_source_capture_sha256)
      REFERENCES rag_registered_source_captures(id,fetch_attempt_id,fetched_sha256)
      ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
    WHERE conrelid='rag_registered_final_followup_allowances'::regclass
      AND conname='fk_rag_settled_source_failed_auth_exact') THEN
    ALTER TABLE rag_registered_final_followup_allowances
      ADD CONSTRAINT fk_rag_settled_source_failed_auth_exact
      FOREIGN KEY(latest_attempt_id,settled_source_failed_authorization_id,canonical_url_sha256)
      REFERENCES rag_registered_fetch_attempts(id,supplemental_authorization_id,canonical_url_sha256)
      ON DELETE RESTRICT;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION rag_registered_settled_source_correction_once_check(
  grant_row rag_registered_final_followup_allowances
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE original_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE original_capture rag_registered_source_captures%ROWTYPE;
DECLARE original_policy rag_registered_source_policies%ROWTYPE;
DECLARE latest_policy rag_registered_source_policies%ROWTYPE;
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
DECLARE original_root rag_budget_authority_roots%ROWTYPE;
DECLARE latest_root rag_budget_authority_roots%ROWTYPE;
DECLARE root_row rag_budget_authority_roots%ROWTYPE;
DECLARE db_now timestamptz;
BEGIN
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'settled source correction requires read committed' USING ERRCODE='23514';
  END IF;
  SELECT * INTO original_row FROM rag_registered_fetch_attempts
    WHERE id=grant_row.original_attempt_id FOR UPDATE;
  SELECT * INTO latest_row FROM rag_registered_fetch_attempts
    WHERE id=grant_row.latest_attempt_id FOR SHARE;
  SELECT * INTO latest_auth FROM rag_registered_supplemental_authorizations
    WHERE id=grant_row.settled_source_failed_authorization_id FOR SHARE;
  SELECT * INTO original_capture FROM rag_registered_source_captures
    WHERE id=grant_row.settled_source_capture_id FOR SHARE;
  SELECT * INTO original_policy FROM rag_registered_source_policies
    WHERE policy_id=original_row.policy_id FOR SHARE;
  SELECT * INTO latest_policy FROM rag_registered_source_policies
    WHERE policy_id=latest_row.policy_id FOR SHARE;
  SELECT * INTO original_root FROM rag_budget_authority_roots
    WHERE root_id=original_row.root_id FOR SHARE;
  SELECT * INTO latest_root FROM rag_budget_authority_roots
    WHERE root_id=latest_row.root_id FOR SHARE;
  SELECT * INTO policy_row FROM rag_registered_source_policies
    WHERE policy_id=grant_row.policy_id FOR SHARE;
  SELECT * INTO root_row FROM rag_budget_authority_roots
    WHERE root_id=grant_row.root_id FOR SHARE;
  db_now := clock_timestamp();

  IF grant_row.generation<>3 OR grant_row.settled_source_capture_id IS NULL OR
     grant_row.settled_source_capture_sha256 IS NULL OR
     grant_row.settled_source_failed_authorization_id IS NULL OR
     grant_row.settled_second_capture_id IS NOT NULL OR
     grant_row.approval_ref !~ '^standingpolicy[.]settledsourcecorrection[.]' OR
     original_row.id IS NULL OR original_row.generation<>1 OR original_row.state<>'settled' OR
     original_row.supplemental_authorization_id IS NOT NULL OR
     latest_row.id IS NULL OR latest_row.generation<>1 OR latest_row.state<>'unknown' OR
     latest_row.error_code IS DISTINCT FROM 'EGRESS_UNVERIFIED_SIGNATURE_PID_NAMESPACE' OR
     latest_row.response_sha256 IS NOT NULL OR latest_row.response_bytes IS NOT NULL OR
     latest_row.settled_at IS NOT NULL OR latest_row.dispatched_at>db_now OR
     latest_row.dispatched_at<original_row.settled_at OR
     EXISTS (SELECT 1 FROM rag_registered_source_captures WHERE fetch_attempt_id=latest_row.id) OR
     latest_auth.id IS NULL OR latest_row.supplemental_authorization_id IS DISTINCT FROM latest_auth.id OR
     latest_auth.explicit_followup_id IS NOT NULL OR latest_auth.replaces_authorization_id IS NOT NULL OR
     ROW(latest_auth.prior_attempt_id,latest_auth.dispatch_id,latest_auth.policy_id,
       latest_auth.generation,latest_auth.canonical_url_sha256,latest_auth.root_id,latest_auth.request_hash)
       IS DISTINCT FROM ROW(original_row.id,latest_row.id,latest_row.policy_id,
         latest_row.generation,latest_row.canonical_url_sha256,latest_row.root_id,latest_row.request_hash) OR
     latest_auth.expires_at<=latest_row.dispatched_at OR
     EXISTS (SELECT 1 FROM rag_registered_supplemental_revocations WHERE authorization_id=latest_auth.id) OR
     (SELECT count(*) FROM rag_registered_supplemental_authorizations
       WHERE prior_attempt_id=original_row.id AND explicit_followup_id IS NULL)<>1 OR
     original_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     latest_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     (SELECT count(*) FROM rag_registered_fetch_attempts
       WHERE canonical_url_sha256=grant_row.canonical_url_sha256)<>2 OR
     EXISTS (SELECT 1 FROM rag_registered_final_followup_allowances
       WHERE original_attempt_id=original_row.id AND id<>grant_row.id) OR
     EXISTS (SELECT 1 FROM rag_registered_fetch_attempts
       WHERE id=grant_row.dispatch_id OR policy_id=grant_row.policy_id OR root_id=grant_row.root_id) OR
     (SELECT count(DISTINCT id) FROM unnest(ARRAY[grant_row.id,grant_row.authorization_id,
       grant_row.dispatch_id,original_row.id,latest_row.id,original_capture.id,latest_auth.id]) AS ids(id))<>7 THEN
    RAISE EXCEPTION 'settled source exact deployment failure denied' USING ERRCODE='23514';
  END IF;

  IF original_capture.id IS NULL OR original_capture.cleared_at IS NOT NULL OR
     original_capture.captured_body IS NULL OR original_capture.provider_attempt_id IS NOT NULL OR
     original_capture.evidence_level<>'live_egress_attested' OR
     original_capture.transport_proof IS NULL OR original_capture.transport_proof_sha256 IS NULL OR
     original_capture.attestor_key_sha256 IS NULL OR original_capture.worker_image_sha256 IS NULL OR
     ROW(original_capture.fetch_attempt_id,original_capture.policy_id,original_capture.generation,
       original_capture.fetched_sha256,original_capture.captured_bytes)
       IS DISTINCT FROM ROW(original_row.id,original_row.policy_id,1,
         original_row.response_sha256,original_row.response_bytes) OR
     original_capture.fetched_sha256<>grant_row.settled_source_capture_sha256 OR
     encode(digest(original_capture.captured_body,'sha256'),'hex')<>original_capture.fetched_sha256 OR
     octet_length(original_capture.captured_body)<>original_capture.captured_bytes OR
     encode(digest(original_capture.transport_proof,'sha256'),'hex')<>original_capture.transport_proof_sha256 OR
     original_capture.fetched_at<original_row.dispatched_at OR
     original_capture.fetched_at>original_row.settled_at OR original_row.settled_at>db_now OR
     original_capture.retention_until>db_now OR
     original_capture.retention_until>original_policy.retention_until OR
     original_capture.final_url IS DISTINCT FROM original_policy.canonical_url OR
     original_capture.request_chain->>0 IS DISTINCT FROM original_policy.canonical_url OR
     original_capture.license_id IS DISTINCT FROM original_policy.license_id THEN
    RAISE EXCEPTION 'settled source expired original capture denied' USING ERRCODE='23514';
  END IF;

  -- Only the original is required to be expired. The failed supplemental is
  -- already consumed: its valid-at-dispatch window is not an unused grant.
  IF original_policy.policy_id IS NULL OR latest_policy.policy_id IS NULL OR
     original_root.root_id IS NULL OR latest_root.root_id IS NULL OR
     original_policy.generation<>1 OR latest_policy.generation<>1 OR
     original_policy.root_id<>original_row.root_id OR latest_policy.root_id<>latest_row.root_id OR
     original_policy.policy_id=latest_policy.policy_id OR original_root.root_id=latest_root.root_id OR
     original_policy.enabled IS NOT TRUE OR latest_policy.enabled IS NOT TRUE OR
     original_policy.revoked_at IS NOT NULL OR latest_policy.revoked_at IS NOT NULL OR
     original_policy.expires_at>db_now OR original_policy.retention_until>db_now OR
     original_root.enabled IS NOT TRUE OR latest_root.enabled IS NOT TRUE OR
     ROW(original_root.policy_id,original_root.policy_generation)
       IS DISTINCT FROM ROW(original_policy.policy_id,1) OR
     ROW(latest_root.policy_id,latest_root.policy_generation)
       IS DISTINCT FROM ROW(latest_policy.policy_id,1) OR
     original_root.delegation_expires_at>db_now OR original_root.period_end>db_now OR
     latest_policy.expires_at<=latest_row.dispatched_at OR
     latest_policy.retention_until<=latest_row.dispatched_at OR
     latest_root.period_start>latest_row.dispatched_at OR
     latest_root.delegation_expires_at<=latest_row.dispatched_at OR
     latest_root.period_end<=latest_row.dispatched_at THEN
    RAISE EXCEPTION 'settled source original expiry or failed authority denied' USING ERRCODE='23514';
  END IF;

  IF policy_row.policy_id IS NULL OR policy_row.generation<>3 OR
     policy_row.enabled IS NOT TRUE OR policy_row.revoked_at IS NOT NULL OR
     policy_row.canonical_url<>'https://www.sqlite.org/lang_select.html' OR
     policy_row.host<>'www.sqlite.org' OR policy_row.path<>'/lang_select.html' OR
     policy_row.subject_id<>'route.sql' OR policy_row.subject_version<>'1.0' OR
     policy_row.facets<>ARRAY['queries']::text[] OR policy_row.origin<>'official' OR
     policy_row.allowed_usages<>ARRAY['assessment_evidence']::text[] OR
     policy_row.immutable_history_allowed IS NOT TRUE OR
     policy_row.source_handle IS DISTINCT FROM latest_policy.source_handle OR
     policy_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     policy_row.root_id<>grant_row.root_id OR
     policy_row.policy_id IN (original_row.policy_id,latest_row.policy_id) OR
     -- The original handle may differ: 350 already authorized the second handle.
     -- All semantic scope/rights fields remain identical to BOTH old policies.
     EXISTS (SELECT 1 FROM rag_registered_source_policies history_policy
       WHERE history_policy.policy_id IN (original_row.policy_id,latest_row.policy_id)
         AND (ROW(policy_row.subject_id,policy_row.subject_version,policy_row.facets,
           policy_row.origin,policy_row.reading_level,policy_row.canonical_url,
           policy_row.canonical_url_sha256,policy_row.host,policy_row.path,policy_row.license_id,
           policy_row.allowed_usages,policy_row.immutable_history_allowed)
           IS DISTINCT FROM ROW(history_policy.subject_id,history_policy.subject_version,
             history_policy.facets,history_policy.origin,history_policy.reading_level,
             history_policy.canonical_url,history_policy.canonical_url_sha256,
             history_policy.host,history_policy.path,history_policy.license_id,
             history_policy.allowed_usages,history_policy.immutable_history_allowed)
           OR policy_row.max_captured_bytes>history_policy.max_captured_bytes)) OR
     root_row.root_id IS NULL OR root_row.enabled IS NOT TRUE OR
     root_row.policy_id<>policy_row.policy_id OR root_row.policy_generation<>3 OR
     root_row.root_id IN (original_row.root_id,latest_row.root_id) OR
     root_row.period_start>db_now OR root_row.period_end<=db_now OR
     root_row.delegation_expires_at<=db_now OR
     policy_row.expires_at<=db_now OR policy_row.retention_until<=db_now OR
     policy_row.expires_at>db_now+interval '24 hours' OR
     policy_row.retention_until>db_now+interval '24 hours' OR
     root_row.period_end>db_now+interval '24 hours' OR
     root_row.delegation_expires_at>db_now+interval '24 hours' OR
     grant_row.expires_at<=db_now OR grant_row.expires_at>db_now+interval '24 hours' OR
     grant_row.expires_at>policy_row.expires_at OR grant_row.expires_at>policy_row.retention_until OR
     grant_row.expires_at>root_row.delegation_expires_at OR grant_row.expires_at>root_row.period_end THEN
    RAISE EXCEPTION 'settled source correction target denied' USING ERRCODE='23514';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION rag_registered_settled_second_fresh_once_check(
  grant_row rag_registered_final_followup_allowances
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE original_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE replaced_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE revocation rag_registered_supplemental_revocations%ROWTYPE;
DECLARE latest_capture rag_registered_source_captures%ROWTYPE;
DECLARE original_policy rag_registered_source_policies%ROWTYPE;
DECLARE latest_policy rag_registered_source_policies%ROWTYPE;
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
DECLARE original_root rag_budget_authority_roots%ROWTYPE;
DECLARE latest_root rag_budget_authority_roots%ROWTYPE;
DECLARE root_row rag_budget_authority_roots%ROWTYPE;
DECLARE db_now timestamptz;
BEGIN
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'settled second freshness requires read committed' USING ERRCODE='23514';
  END IF;
  -- Same serialization point at allowance issuance, auth insertion and dispatch.
  SELECT * INTO original_row FROM rag_registered_fetch_attempts
    WHERE id=grant_row.original_attempt_id FOR UPDATE;
  SELECT * INTO latest_row FROM rag_registered_fetch_attempts
    WHERE id=grant_row.latest_attempt_id FOR SHARE;
  SELECT * INTO latest_auth FROM rag_registered_supplemental_authorizations
    WHERE id=latest_row.supplemental_authorization_id FOR SHARE;
  SELECT * INTO replaced_auth FROM rag_registered_supplemental_authorizations
    WHERE id=latest_auth.replaces_authorization_id FOR SHARE;
  SELECT * INTO revocation FROM rag_registered_supplemental_revocations
    WHERE authorization_id=latest_auth.replaces_authorization_id FOR SHARE;
  SELECT * INTO latest_capture FROM rag_registered_source_captures
    WHERE id=grant_row.settled_second_capture_id FOR SHARE;
  SELECT * INTO original_policy FROM rag_registered_source_policies
    WHERE policy_id=original_row.policy_id FOR SHARE;
  SELECT * INTO latest_policy FROM rag_registered_source_policies
    WHERE policy_id=latest_row.policy_id FOR SHARE;
  SELECT * INTO original_root FROM rag_budget_authority_roots
    WHERE root_id=original_row.root_id FOR SHARE;
  SELECT * INTO latest_root FROM rag_budget_authority_roots
    WHERE root_id=latest_row.root_id FOR SHARE;
  SELECT * INTO policy_row FROM rag_registered_source_policies
    WHERE policy_id=grant_row.policy_id FOR SHARE;
  SELECT * INTO root_row FROM rag_budget_authority_roots
    WHERE root_id=grant_row.root_id FOR SHARE;
  db_now := clock_timestamp(); -- never use transaction-start time after waiting

  IF grant_row.generation<>3 OR grant_row.settled_second_capture_id IS NULL OR
     grant_row.settled_second_capture_sha256 IS NULL OR
     grant_row.approval_ref !~ '^standingpolicy[.]settledsecondfreshness[.]' OR
     original_row.id IS NULL OR original_row.generation<>1 OR original_row.state<>'unknown' OR
     original_row.supplemental_authorization_id IS NOT NULL OR
     latest_row.id IS NULL OR latest_row.generation<>1 OR latest_row.state<>'settled' OR
     latest_auth.id IS NULL OR latest_auth.explicit_followup_id IS NOT NULL OR
     ROW(latest_auth.prior_attempt_id,latest_auth.dispatch_id,latest_auth.policy_id,
       latest_auth.generation,latest_auth.canonical_url_sha256,latest_auth.root_id,latest_auth.request_hash)
       IS DISTINCT FROM ROW(original_row.id,latest_row.id,latest_row.policy_id,
         latest_row.generation,latest_row.canonical_url_sha256,latest_row.root_id,latest_row.request_hash) OR
     original_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     latest_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     latest_auth.expires_at>db_now OR
     EXISTS (SELECT 1 FROM rag_registered_supplemental_revocations
       WHERE authorization_id=latest_auth.id) OR
     (SELECT count(*) FROM rag_registered_fetch_attempts
       WHERE canonical_url_sha256=grant_row.canonical_url_sha256)<>2 OR
     EXISTS (SELECT 1 FROM rag_registered_final_followup_allowances
       WHERE original_attempt_id=original_row.id AND id<>grant_row.id) OR
     EXISTS (SELECT 1 FROM rag_registered_fetch_attempts
       WHERE id=grant_row.dispatch_id OR policy_id=grant_row.policy_id OR root_id=grant_row.root_id) OR
     (SELECT count(DISTINCT id) FROM unnest(ARRAY[grant_row.id,grant_row.authorization_id,
       grant_row.dispatch_id,original_row.id,latest_row.id,latest_capture.id]) AS ids(id))<>6 OR
     grant_row.id=latest_auth.id OR grant_row.authorization_id=latest_auth.id OR
     grant_row.dispatch_id=latest_auth.id THEN
    RAISE EXCEPTION 'settled second freshness history denied' USING ERRCODE='23514';
  END IF;

  -- A corrected supplemental is legitimate only if the replaced grant really
  -- was unspent and was revoked by the existing append-only correction owner.
  IF latest_auth.replaces_authorization_id IS NOT NULL THEN
    IF replaced_auth.id IS NULL OR revocation.authorization_id IS NULL OR
       replaced_auth.prior_attempt_id<>original_row.id OR
       replaced_auth.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
       replaced_auth.replaces_authorization_id IS NOT NULL OR
       replaced_auth.explicit_followup_id IS NOT NULL OR
       revocation.prior_attempt_id<>original_row.id OR
       revocation.created_at>latest_auth.created_at OR
       ROW(replaced_auth.policy_id,replaced_auth.generation)=ROW(latest_auth.policy_id,latest_auth.generation) OR
       EXISTS (SELECT 1 FROM rag_registered_fetch_attempts
         WHERE supplemental_authorization_id=replaced_auth.id OR id=replaced_auth.dispatch_id) OR
       grant_row.policy_id=replaced_auth.policy_id OR grant_row.root_id=replaced_auth.root_id OR
       grant_row.id IN (replaced_auth.id,replaced_auth.dispatch_id) OR
       grant_row.authorization_id IN (replaced_auth.id,replaced_auth.dispatch_id) OR
       grant_row.dispatch_id IN (replaced_auth.id,replaced_auth.dispatch_id) THEN
      RAISE EXCEPTION 'settled second correction chain denied' USING ERRCODE='23514';
    END IF;
  END IF;
  IF (SELECT count(*) FROM rag_registered_supplemental_authorizations
      WHERE prior_attempt_id=original_row.id AND explicit_followup_id IS NULL)
      <> (CASE WHEN latest_auth.replaces_authorization_id IS NULL THEN 1 ELSE 2 END) THEN
    RAISE EXCEPTION 'settled second supplemental history denied' USING ERRCODE='23514';
  END IF;

  IF latest_capture.id IS NULL OR latest_capture.cleared_at IS NOT NULL OR
     latest_capture.captured_body IS NULL OR latest_capture.provider_attempt_id IS NOT NULL OR
     latest_capture.evidence_level<>'live_egress_attested' OR
     latest_capture.transport_proof IS NULL OR latest_capture.transport_proof_sha256 IS NULL OR
     latest_capture.attestor_key_sha256 IS NULL OR latest_capture.worker_image_sha256 IS NULL OR
     ROW(latest_capture.fetch_attempt_id,latest_capture.policy_id,latest_capture.generation,
       latest_capture.fetched_sha256,latest_capture.captured_bytes)
       IS DISTINCT FROM ROW(latest_row.id,latest_row.policy_id,1,
         latest_row.response_sha256,latest_row.response_bytes) OR
     latest_capture.fetched_sha256<>grant_row.settled_second_capture_sha256 OR
     encode(digest(latest_capture.captured_body,'sha256'),'hex')<>latest_capture.fetched_sha256 OR
     octet_length(latest_capture.captured_body)<>latest_capture.captured_bytes OR
     encode(digest(latest_capture.transport_proof,'sha256'),'hex')<>latest_capture.transport_proof_sha256 OR
     latest_capture.fetched_at<latest_row.dispatched_at OR
     latest_capture.fetched_at>latest_row.settled_at OR latest_row.settled_at>db_now OR
     latest_capture.retention_until>db_now OR
     latest_capture.retention_until>latest_policy.retention_until OR
     latest_capture.final_url IS DISTINCT FROM latest_policy.canonical_url OR
     latest_capture.request_chain->>0 IS DISTINCT FROM latest_policy.canonical_url OR
     latest_capture.license_id IS DISTINCT FROM latest_policy.license_id THEN
    RAISE EXCEPTION 'settled second complete capture denied' USING ERRCODE='23514';
  END IF;

  -- Both old authorities must have naturally expired, never revoked/disabled.
  IF original_policy.policy_id IS NULL OR latest_policy.policy_id IS NULL OR
     original_root.root_id IS NULL OR latest_root.root_id IS NULL OR
     original_policy.generation<>1 OR latest_policy.generation<>1 OR
     original_policy.root_id<>original_row.root_id OR latest_policy.root_id<>latest_row.root_id OR
     original_policy.enabled IS NOT TRUE OR latest_policy.enabled IS NOT TRUE OR
     original_policy.revoked_at IS NOT NULL OR latest_policy.revoked_at IS NOT NULL OR
     original_policy.expires_at>db_now OR original_policy.retention_until>db_now OR
     latest_policy.expires_at>db_now OR latest_policy.retention_until>db_now OR
     original_root.enabled IS NOT TRUE OR latest_root.enabled IS NOT TRUE OR
     ROW(original_root.policy_id,original_root.policy_generation)
       IS DISTINCT FROM ROW(original_policy.policy_id,1) OR
     ROW(latest_root.policy_id,latest_root.policy_generation)
       IS DISTINCT FROM ROW(latest_policy.policy_id,1) OR
     original_root.delegation_expires_at>db_now OR original_root.period_end>db_now OR
     latest_root.delegation_expires_at>db_now OR latest_root.period_end>db_now THEN
    RAISE EXCEPTION 'settled second natural expiry required' USING ERRCODE='23514';
  END IF;

  IF policy_row.policy_id IS NULL OR policy_row.generation<>3 OR
     policy_row.enabled IS NOT TRUE OR policy_row.revoked_at IS NOT NULL OR
     policy_row.canonical_url<>'https://docs.python.org/3/builtins/functions.html' OR
     policy_row.host<>'docs.python.org' OR policy_row.path<>'/3/builtins/functions.html' OR
     policy_row.subject_id<>'route.python' OR policy_row.subject_version<>'1.0' OR
     policy_row.facets<>ARRAY['fundamentals']::text[] OR policy_row.origin<>'official' OR
     policy_row.allowed_usages<>ARRAY['assessment_evidence']::text[] OR
     policy_row.immutable_history_allowed IS NOT TRUE OR
     policy_row.source_handle IS DISTINCT FROM latest_policy.source_handle OR
     policy_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     policy_row.root_id<>grant_row.root_id OR
     policy_row.policy_id IN (original_row.policy_id,latest_row.policy_id) OR
     EXISTS (SELECT 1 FROM rag_registered_source_policies history_policy
       WHERE history_policy.policy_id IN (original_row.policy_id,latest_row.policy_id)
         AND (ROW(policy_row.subject_id,policy_row.subject_version,
           policy_row.facets,policy_row.origin,policy_row.reading_level,policy_row.canonical_url,
           policy_row.canonical_url_sha256,policy_row.host,policy_row.path,policy_row.license_id,
           policy_row.allowed_usages,policy_row.immutable_history_allowed)
           IS DISTINCT FROM ROW(history_policy.subject_id,
             history_policy.subject_version,history_policy.facets,history_policy.origin,
             history_policy.reading_level,history_policy.canonical_url,history_policy.canonical_url_sha256,
             history_policy.host,history_policy.path,history_policy.license_id,
             history_policy.allowed_usages,history_policy.immutable_history_allowed)
           OR policy_row.max_captured_bytes>history_policy.max_captured_bytes)) OR
     root_row.root_id IS NULL OR root_row.enabled IS NOT TRUE OR
     root_row.policy_id<>policy_row.policy_id OR root_row.policy_generation<>3 OR
     root_row.root_id IN (original_row.root_id,latest_row.root_id) OR
     root_row.period_start>db_now OR root_row.period_end<=db_now OR
     root_row.delegation_expires_at<=db_now OR
     policy_row.expires_at<=db_now OR policy_row.retention_until<=db_now OR
     policy_row.expires_at>db_now+interval '24 hours' OR
     policy_row.retention_until>db_now+interval '24 hours' OR
     root_row.period_end>db_now+interval '24 hours' OR
     root_row.delegation_expires_at>db_now+interval '24 hours' OR
     grant_row.expires_at<=db_now OR grant_row.expires_at>db_now+interval '24 hours' OR
     grant_row.expires_at>policy_row.expires_at OR grant_row.expires_at>policy_row.retention_until OR
     grant_row.expires_at>root_row.delegation_expires_at OR grant_row.expires_at>root_row.period_end THEN
    RAISE EXCEPTION 'settled second fresh target denied' USING ERRCODE='23514';
  END IF;
END $$;

-- All 400 allowance/auth/dispatch guards still call this shared checker. Keep
-- the old NULL branch exactly as 420; a spent freshness grant is never a credit
-- in the older unknown-chain correction/refresh protocol.
CREATE OR REPLACE FUNCTION rag_registered_final_followup_check(
  grant_row rag_registered_final_followup_allowances
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE original_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
DECLARE root_row rag_budget_authority_roots%ROWTYPE;
DECLARE db_now timestamptz;
BEGIN
  IF grant_row.settled_second_capture_id IS NOT NULL THEN
    PERFORM rag_registered_settled_second_fresh_once_check(grant_row);
    RETURN;
  END IF;
  IF EXISTS (SELECT 1 FROM rag_registered_final_followup_allowances
    WHERE original_attempt_id=grant_row.original_attempt_id
      AND settled_second_capture_id IS NOT NULL) THEN
    RAISE EXCEPTION 'settled second freshness cannot fund another followup' USING ERRCODE='23514';
  END IF;
  IF grant_row.settled_source_capture_id IS NOT NULL THEN
    PERFORM rag_registered_settled_source_correction_once_check(grant_row);
    RETURN;
  END IF;
  IF EXISTS (SELECT 1 FROM rag_registered_final_followup_allowances
    WHERE original_attempt_id=grant_row.original_attempt_id
      AND settled_source_capture_id IS NOT NULL) THEN
    RAISE EXCEPTION 'settled source correction cannot fund another followup' USING ERRCODE='23514';
  END IF;
  IF grant_row.generation=5 THEN
    PERFORM rag_registered_expired_source_refresh_check(grant_row);
    RETURN;
  END IF;
  IF grant_row.generation=4 THEN
    PERFORM rag_registered_deployment_correction_check(grant_row);
    RETURN;
  END IF;
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'final followup requires read committed' USING ERRCODE='23514';
  END IF;
  SELECT * INTO policy_row FROM rag_registered_source_policies
    WHERE policy_id=grant_row.policy_id FOR SHARE;
  SELECT * INTO root_row FROM rag_budget_authority_roots
    WHERE root_id=grant_row.root_id FOR SHARE;
  SELECT * INTO original_row FROM rag_registered_fetch_attempts
    WHERE id=grant_row.original_attempt_id FOR UPDATE;
  SELECT * INTO latest_row FROM rag_registered_fetch_attempts
    WHERE id=grant_row.latest_attempt_id FOR SHARE;
  SELECT * INTO latest_auth FROM rag_registered_supplemental_authorizations
    WHERE id=latest_row.supplemental_authorization_id FOR SHARE;
  db_now := clock_timestamp();
  IF original_row.id IS NULL OR original_row.state<>'unknown' OR
     original_row.supplemental_authorization_id IS NOT NULL OR
     latest_row.id IS NULL OR latest_row.state<>'unknown' OR latest_auth.id IS NULL OR
     latest_auth.prior_attempt_id<>original_row.id OR latest_auth.explicit_followup_id IS NOT NULL OR
     original_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     latest_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     EXISTS (SELECT 1 FROM rag_registered_source_policies history_policy
       WHERE history_policy.policy_id IN (original_row.policy_id,latest_row.policy_id)
         AND (policy_row.subject_id IS DISTINCT FROM history_policy.subject_id OR
           policy_row.subject_version IS DISTINCT FROM history_policy.subject_version OR
           policy_row.facets IS DISTINCT FROM history_policy.facets OR
           NOT (policy_row.allowed_usages @> history_policy.allowed_usages) OR
           NOT (policy_row.allowed_usages <@ history_policy.allowed_usages) OR
           policy_row.max_captured_bytes>history_policy.max_captured_bytes)) OR
     grant_row.original_attempt_id=grant_row.latest_attempt_id OR grant_row.generation<>3 OR
     grant_row.policy_id IN (original_row.policy_id,latest_row.policy_id) OR
     grant_row.root_id IN (original_row.root_id,latest_row.root_id) OR
     (SELECT count(*) FROM rag_registered_fetch_attempts
       WHERE canonical_url_sha256=grant_row.canonical_url_sha256)<>2 OR
     EXISTS (SELECT 1 FROM rag_registered_supplemental_revocations WHERE authorization_id=latest_auth.id) OR
     policy_row.policy_id IS NULL OR policy_row.generation<>grant_row.generation OR
     policy_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR policy_row.root_id<>grant_row.root_id OR
     NOT policy_row.enabled OR policy_row.revoked_at IS NOT NULL OR
     root_row.root_id IS NULL OR NOT root_row.enabled OR root_row.policy_id<>grant_row.policy_id OR
     root_row.policy_generation<>grant_row.generation OR root_row.period_start>db_now OR
     grant_row.expires_at<=db_now OR grant_row.expires_at>policy_row.expires_at OR
     grant_row.expires_at>policy_row.retention_until OR grant_row.expires_at>root_row.delegation_expires_at OR
     grant_row.expires_at>root_row.period_end OR
     EXISTS (SELECT 1 FROM rag_registered_fetch_attempts WHERE id=grant_row.dispatch_id OR
       (policy_id=grant_row.policy_id AND generation=grant_row.generation
         AND canonical_url_sha256=grant_row.canonical_url_sha256)) THEN
    RAISE EXCEPTION 'final followup history or target denied' USING ERRCODE='23514';
  END IF;
END $$;
