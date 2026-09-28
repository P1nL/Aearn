-- One operator-approved generation-five freshness capture after a genuine
-- generation-four settlement has expired. This is a new GET, not a retry,
-- extension, or reuse of the expired captured bytes. Bootstrap grants nothing.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint
    WHERE conrelid='rag_registered_final_followup_allowances'::regclass
      AND conname='rag_registered_final_followup_allowances_generation_check') THEN
    ALTER TABLE rag_registered_final_followup_allowances
      DROP CONSTRAINT rag_registered_final_followup_allowances_generation_check;
  END IF;
END $$;
ALTER TABLE rag_registered_final_followup_allowances
  ADD CONSTRAINT rag_registered_final_followup_allowances_generation_check
  CHECK (generation IN (3,4,5));

CREATE OR REPLACE FUNCTION rag_registered_expired_source_refresh_check(
  grant_row rag_registered_final_followup_allowances
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE original_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE second_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE third_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE second_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE third_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE latest_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE third_credit rag_registered_final_followup_allowances%ROWTYPE;
DECLARE fourth_credit rag_registered_final_followup_allowances%ROWTYPE;
DECLARE latest_capture rag_registered_source_captures%ROWTYPE;
DECLARE latest_policy rag_registered_source_policies%ROWTYPE;
DECLARE latest_root rag_budget_authority_roots%ROWTYPE;
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
DECLARE root_row rag_budget_authority_roots%ROWTYPE;
DECLARE prior_credit_count integer;
DECLARE refresh_credit_count integer;
DECLARE db_now timestamptz;
BEGIN
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'source freshness refresh requires read committed' USING ERRCODE='23514';
  END IF;

  -- Generation one is the common serialization point for issue, authorization,
  -- and dispatch. No source/policy row is mutated by this check.
  SELECT * INTO original_row FROM rag_registered_fetch_attempts
    WHERE id=grant_row.original_attempt_id FOR UPDATE;
  SELECT * INTO latest_row FROM rag_registered_fetch_attempts
    WHERE id=grant_row.latest_attempt_id FOR SHARE;
  SELECT * INTO latest_auth FROM rag_registered_supplemental_authorizations
    WHERE id=latest_row.supplemental_authorization_id FOR SHARE;
  SELECT * INTO fourth_credit FROM rag_registered_final_followup_allowances
    WHERE id=latest_auth.explicit_followup_id FOR SHARE;
  SELECT * INTO third_row FROM rag_registered_fetch_attempts
    WHERE id=fourth_credit.latest_attempt_id FOR SHARE;
  SELECT * INTO third_auth FROM rag_registered_supplemental_authorizations
    WHERE id=third_row.supplemental_authorization_id FOR SHARE;
  SELECT * INTO third_credit FROM rag_registered_final_followup_allowances
    WHERE id=third_auth.explicit_followup_id FOR SHARE;
  SELECT * INTO second_row FROM rag_registered_fetch_attempts
    WHERE id=third_credit.latest_attempt_id FOR SHARE;
  SELECT * INTO second_auth FROM rag_registered_supplemental_authorizations
    WHERE id=second_row.supplemental_authorization_id FOR SHARE;
  SELECT * INTO latest_capture FROM rag_registered_source_captures
    WHERE fetch_attempt_id=latest_row.id FOR SHARE;
  SELECT * INTO latest_policy FROM rag_registered_source_policies
    WHERE policy_id=latest_row.policy_id FOR SHARE;
  SELECT * INTO latest_root FROM rag_budget_authority_roots
    WHERE root_id=latest_row.root_id FOR SHARE;
  SELECT * INTO policy_row FROM rag_registered_source_policies
    WHERE policy_id=grant_row.policy_id FOR SHARE;
  SELECT * INTO root_row FROM rag_budget_authority_roots
    WHERE root_id=grant_row.root_id FOR SHARE;
  SELECT count(*) INTO prior_credit_count
    FROM rag_registered_final_followup_allowances
    WHERE original_attempt_id=grant_row.original_attempt_id AND generation IN (3,4);
  SELECT count(*) INTO refresh_credit_count
    FROM rag_registered_final_followup_allowances
    WHERE original_attempt_id=grant_row.original_attempt_id AND generation=5;
  db_now := clock_timestamp();

  IF grant_row.generation<>5 OR
     grant_row.approval_ref !~ '^standingpolicy[.]sourcefreshness[.]' OR
     original_row.id IS NULL OR original_row.generation<>1 OR
     original_row.state<>'unknown' OR original_row.supplemental_authorization_id IS NOT NULL OR
     second_row.id IS NULL OR second_row.generation<>2 OR second_row.state<>'unknown' OR
     second_auth.id IS NULL OR second_auth.prior_attempt_id<>original_row.id OR
     second_auth.dispatch_id<>second_row.id OR second_auth.policy_id<>second_row.policy_id OR
     second_auth.generation<>2 OR second_auth.canonical_url_sha256<>second_row.canonical_url_sha256 OR
     second_auth.root_id<>second_row.root_id OR second_auth.request_hash<>second_row.request_hash OR
     second_auth.explicit_followup_id IS NOT NULL OR
     EXISTS (SELECT 1 FROM rag_registered_supplemental_revocations
       WHERE authorization_id=second_auth.id) OR
     third_row.id IS NULL OR third_row.generation<>3 OR third_row.state<>'unknown' OR
     third_auth.id IS NULL OR third_auth.prior_attempt_id<>original_row.id OR
     third_auth.dispatch_id<>third_row.id OR third_auth.policy_id<>third_row.policy_id OR
     third_auth.generation<>3 OR third_auth.canonical_url_sha256<>third_row.canonical_url_sha256 OR
     third_auth.root_id<>third_row.root_id OR third_auth.request_hash<>third_row.request_hash OR
     third_credit.id IS NULL OR third_credit.generation<>3 OR
     third_auth.explicit_followup_id<>third_credit.id OR
     third_credit.original_attempt_id<>original_row.id OR
     third_credit.latest_attempt_id<>second_row.id OR
     third_credit.authorization_id<>third_auth.id OR third_credit.dispatch_id<>third_row.id OR
     third_credit.policy_id<>third_row.policy_id OR third_credit.root_id<>third_row.root_id OR
     third_credit.request_hash<>third_row.request_hash OR
     EXISTS (SELECT 1 FROM rag_registered_supplemental_revocations
       WHERE authorization_id=third_auth.id) OR
     latest_row.id IS NULL OR latest_row.generation<>4 OR latest_row.state<>'settled' OR
     latest_auth.id IS NULL OR latest_auth.prior_attempt_id<>original_row.id OR
     latest_auth.dispatch_id<>latest_row.id OR latest_auth.policy_id<>latest_row.policy_id OR
     latest_auth.generation<>4 OR latest_auth.canonical_url_sha256<>latest_row.canonical_url_sha256 OR
     latest_auth.root_id<>latest_row.root_id OR latest_auth.request_hash<>latest_row.request_hash OR
     fourth_credit.id IS NULL OR fourth_credit.generation<>4 OR
     latest_auth.explicit_followup_id<>fourth_credit.id OR
     fourth_credit.original_attempt_id<>original_row.id OR
     fourth_credit.latest_attempt_id<>third_row.id OR
     fourth_credit.authorization_id<>latest_auth.id OR fourth_credit.dispatch_id<>latest_row.id OR
     fourth_credit.policy_id<>latest_row.policy_id OR fourth_credit.root_id<>latest_row.root_id OR
     fourth_credit.request_hash<>latest_row.request_hash OR
     fourth_credit.approval_ref !~ '^standingpolicy[.]deploymentcorrection[.]' OR
     EXISTS (SELECT 1 FROM rag_registered_supplemental_revocations
       WHERE authorization_id=latest_auth.id) OR
     original_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     second_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     third_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     latest_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     (SELECT count(*) FROM rag_registered_fetch_attempts
       WHERE canonical_url_sha256=grant_row.canonical_url_sha256)<>4 OR
     prior_credit_count<>2 OR refresh_credit_count>1 OR
     EXISTS (SELECT 1 FROM rag_registered_final_followup_allowances
       WHERE original_attempt_id=grant_row.original_attempt_id AND generation=5
         AND id<>grant_row.id) OR
     grant_row.dispatch_id IN (original_row.id,second_row.id,third_row.id,latest_row.id) OR
     latest_capture.id IS NULL OR latest_capture.cleared_at IS NOT NULL OR
     latest_capture.captured_body IS NULL OR latest_capture.transport_proof IS NULL OR
     latest_capture.transport_proof_sha256 IS NULL OR
     latest_capture.attestor_key_sha256 IS NULL OR latest_capture.worker_image_sha256 IS NULL OR
     latest_capture.fetch_attempt_id<>latest_row.id OR latest_capture.policy_id<>latest_row.policy_id OR
     latest_capture.generation<>4 OR latest_capture.fetched_sha256<>latest_row.response_sha256 OR
     latest_capture.captured_bytes<>latest_row.response_bytes OR
     latest_capture.retention_until>db_now OR latest_capture.fetched_at>db_now OR
     latest_row.dispatched_at>latest_capture.fetched_at OR
     latest_capture.fetched_at>latest_row.settled_at OR latest_row.settled_at>db_now OR
     latest_policy.policy_id IS NULL OR latest_policy.generation<>4 OR
     latest_policy.root_id<>latest_row.root_id OR latest_policy.enabled IS NOT TRUE OR
     latest_policy.revoked_at IS NOT NULL OR latest_policy.expires_at>db_now OR
     latest_policy.retention_until>db_now OR latest_auth.expires_at>db_now OR
     fourth_credit.expires_at>db_now OR
     latest_capture.final_url<>latest_policy.canonical_url OR
     latest_capture.request_chain->>0<>latest_policy.canonical_url OR
     latest_capture.license_id<>latest_policy.license_id OR
     latest_root.root_id IS NULL OR latest_root.enabled IS NOT TRUE OR
     latest_root.policy_id<>latest_policy.policy_id OR latest_root.policy_generation<>4 OR
     latest_root.delegation_expires_at>db_now OR latest_root.period_end>db_now OR
     policy_row.policy_id IS NULL OR policy_row.generation<>5 OR
     policy_row.root_id<>grant_row.root_id OR policy_row.enabled IS NOT TRUE OR
     policy_row.revoked_at IS NOT NULL OR policy_row.expires_at<=db_now OR
     policy_row.retention_until<=db_now OR policy_row.expires_at>db_now+interval '24 hours' OR
     policy_row.retention_until>db_now+interval '24 hours' OR
     policy_row.policy_id IN (original_row.policy_id,second_row.policy_id,third_row.policy_id,latest_row.policy_id) OR
     policy_row.source_handle IS DISTINCT FROM latest_policy.source_handle OR
     policy_row.subject_id IS DISTINCT FROM latest_policy.subject_id OR
     policy_row.subject_version IS DISTINCT FROM latest_policy.subject_version OR
     policy_row.facets IS DISTINCT FROM latest_policy.facets OR
     policy_row.origin IS DISTINCT FROM latest_policy.origin OR
     policy_row.reading_level IS DISTINCT FROM latest_policy.reading_level OR
     policy_row.canonical_url IS DISTINCT FROM latest_policy.canonical_url OR
     policy_row.canonical_url_sha256 IS DISTINCT FROM latest_policy.canonical_url_sha256 OR
     policy_row.host IS DISTINCT FROM latest_policy.host OR policy_row.path IS DISTINCT FROM latest_policy.path OR
     policy_row.license_id IS DISTINCT FROM latest_policy.license_id OR
     NOT (policy_row.allowed_usages @> latest_policy.allowed_usages) OR
     NOT (policy_row.allowed_usages <@ latest_policy.allowed_usages) OR
     policy_row.immutable_history_allowed IS DISTINCT FROM latest_policy.immutable_history_allowed OR
     policy_row.max_captured_bytes>latest_policy.max_captured_bytes OR
     root_row.root_id IS NULL OR root_row.enabled IS NOT TRUE OR
     root_row.policy_id<>policy_row.policy_id OR root_row.policy_generation<>5 OR
     root_row.root_id IN (original_row.root_id,second_row.root_id,third_row.root_id,latest_row.root_id) OR
     root_row.period_start>db_now OR root_row.period_end<=db_now OR
     root_row.delegation_expires_at<=db_now OR
     root_row.period_end>db_now+interval '24 hours' OR
     root_row.delegation_expires_at>db_now+interval '24 hours' OR
     grant_row.expires_at<=db_now OR grant_row.expires_at>policy_row.expires_at OR
     grant_row.expires_at>policy_row.retention_until OR
     grant_row.expires_at>root_row.delegation_expires_at OR
     grant_row.expires_at>root_row.period_end OR
     EXISTS (SELECT 1 FROM rag_registered_fetch_attempts WHERE id=grant_row.dispatch_id OR
       (policy_id=grant_row.policy_id AND generation=5
         AND canonical_url_sha256=grant_row.canonical_url_sha256)) THEN
    RAISE EXCEPTION 'expired source freshness history or target denied' USING ERRCODE='23514';
  END IF;
END $$;

-- Keep the generation-three and generation-four gates byte-for-byte equivalent
-- to schema 410, adding only the generation-five dispatch to the new check.
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
