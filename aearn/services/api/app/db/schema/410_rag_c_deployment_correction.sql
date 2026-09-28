-- Operator-only fourth credit following three spent terminal unknowns. No bootstrap grant.
-- Preserve schema 400 rows and auth fields; only extend the allowance cardinality by generation.
DO $$ DECLARE old_key text; BEGIN
  SELECT conname INTO old_key FROM pg_constraint
    WHERE conrelid='rag_registered_final_followup_allowances'::regclass
      AND contype='u' AND conkey=ARRAY[(SELECT attnum FROM pg_attribute
        WHERE attrelid='rag_registered_final_followup_allowances'::regclass
          AND attname='original_attempt_id')]::smallint[];
  IF old_key IS NOT NULL THEN
    EXECUTE format('ALTER TABLE rag_registered_final_followup_allowances DROP CONSTRAINT %I',old_key);
  END IF;
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='rag_registered_final_followup_allowances'::regclass
    AND conname='rag_registered_final_followup_allowances_generation_check') THEN
    ALTER TABLE rag_registered_final_followup_allowances
      DROP CONSTRAINT rag_registered_final_followup_allowances_generation_check;
  END IF;
END $$;
ALTER TABLE rag_registered_final_followup_allowances
  ADD CONSTRAINT rag_registered_final_followup_allowances_generation_check
  CHECK (generation IN (3,4));
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_followup_original_generation
  ON rag_registered_final_followup_allowances(original_attempt_id,generation);

CREATE OR REPLACE FUNCTION rag_registered_deployment_correction_check(
  grant_row rag_registered_final_followup_allowances
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE original_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE second_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE second_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE latest_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE third_credit rag_registered_final_followup_allowances%ROWTYPE;
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
DECLARE root_row rag_budget_authority_roots%ROWTYPE;
DECLARE db_now timestamptz;
BEGIN
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'deployment correction requires read committed' USING ERRCODE='23514';
  END IF;
  SELECT * INTO policy_row FROM rag_registered_source_policies
    WHERE policy_id=grant_row.policy_id FOR SHARE;
  SELECT * INTO root_row FROM rag_budget_authority_roots
    WHERE root_id=grant_row.root_id FOR SHARE;
  -- The original is the shared serialization point for issuance and dispatch.
  SELECT * INTO original_row FROM rag_registered_fetch_attempts
    WHERE id=grant_row.original_attempt_id FOR UPDATE;
  SELECT * INTO latest_row FROM rag_registered_fetch_attempts
    WHERE id=grant_row.latest_attempt_id FOR SHARE;
  SELECT * INTO latest_auth FROM rag_registered_supplemental_authorizations
    WHERE id=latest_row.supplemental_authorization_id FOR SHARE;
  SELECT * INTO third_credit FROM rag_registered_final_followup_allowances
    WHERE id=latest_auth.explicit_followup_id FOR SHARE;
  SELECT * INTO second_row FROM rag_registered_fetch_attempts
    WHERE id=third_credit.latest_attempt_id FOR SHARE;
  SELECT * INTO second_auth FROM rag_registered_supplemental_authorizations
    WHERE id=second_row.supplemental_authorization_id FOR SHARE;
  db_now := clock_timestamp();
  IF grant_row.generation<>4 OR
     grant_row.approval_ref !~ '^standingpolicy[.]deploymentcorrection[.]' OR
     original_row.id IS NULL OR
     original_row.generation<>1 OR original_row.state<>'unknown' OR
     original_row.supplemental_authorization_id IS NOT NULL OR
     latest_row.id IS NULL OR latest_row.generation<>3 OR latest_row.state<>'unknown' OR
     latest_auth.id IS NULL OR latest_auth.prior_attempt_id<>original_row.id OR
     latest_auth.dispatch_id<>latest_row.id OR latest_auth.generation<>3 OR
     third_credit.id IS NULL OR third_credit.generation<>3 OR
     third_credit.original_attempt_id<>original_row.id OR
     third_credit.latest_attempt_id<>second_row.id OR
     third_credit.authorization_id<>latest_auth.id OR
     third_credit.dispatch_id<>latest_row.id OR
     second_row.id IS NULL OR second_row.generation<>2 OR second_row.state<>'unknown' OR
     second_auth.id IS NULL OR second_auth.prior_attempt_id<>original_row.id OR
     second_auth.explicit_followup_id IS NOT NULL OR
     second_auth.dispatch_id<>second_row.id OR
     original_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     second_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     latest_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     grant_row.policy_id IN (original_row.policy_id,second_row.policy_id,latest_row.policy_id) OR
     grant_row.root_id IN (original_row.root_id,second_row.root_id,latest_row.root_id) OR
     EXISTS (SELECT 1 FROM rag_registered_source_policies history_policy
       WHERE history_policy.policy_id IN (original_row.policy_id,second_row.policy_id,latest_row.policy_id)
         AND (policy_row.source_handle IS DISTINCT FROM history_policy.source_handle OR
           policy_row.subject_id IS DISTINCT FROM history_policy.subject_id OR
           policy_row.subject_version IS DISTINCT FROM history_policy.subject_version OR
           policy_row.facets IS DISTINCT FROM history_policy.facets OR
           policy_row.canonical_url IS DISTINCT FROM history_policy.canonical_url OR
           policy_row.host IS DISTINCT FROM history_policy.host OR
           policy_row.path IS DISTINCT FROM history_policy.path OR
           NOT (policy_row.allowed_usages @> history_policy.allowed_usages) OR
           NOT (policy_row.allowed_usages <@ history_policy.allowed_usages) OR
           policy_row.max_captured_bytes>history_policy.max_captured_bytes)) OR
     (SELECT count(*) FROM rag_registered_fetch_attempts
       WHERE canonical_url_sha256=grant_row.canonical_url_sha256)<>3 OR
     EXISTS (SELECT 1 FROM rag_registered_supplemental_revocations
       WHERE authorization_id=latest_auth.id) OR
     policy_row.policy_id IS NULL OR policy_row.generation<>4 OR
     policy_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
     policy_row.root_id<>grant_row.root_id OR NOT policy_row.enabled OR
     policy_row.revoked_at IS NOT NULL OR
     root_row.root_id IS NULL OR NOT root_row.enabled OR
     root_row.policy_id<>grant_row.policy_id OR root_row.policy_generation<>4 OR
     root_row.period_start>db_now OR grant_row.expires_at<=db_now OR
     grant_row.expires_at>policy_row.expires_at OR
     grant_row.expires_at>policy_row.retention_until OR
     grant_row.expires_at>root_row.delegation_expires_at OR
     grant_row.expires_at>root_row.period_end OR
     EXISTS (SELECT 1 FROM rag_registered_fetch_attempts
       WHERE id=grant_row.dispatch_id OR
         (policy_id=grant_row.policy_id AND generation=4
           AND canonical_url_sha256=grant_row.canonical_url_sha256)) THEN
    RAISE EXCEPTION 'deployment correction history or target denied' USING ERRCODE='23514';
  END IF;
END $$;

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
     -- A final credit is not permission to change the historical teaching scope.
     -- These policy fields are immutable; no extra history-policy locks are needed.
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
