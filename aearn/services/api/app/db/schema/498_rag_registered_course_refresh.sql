-- 2026-10-06 only: five fixed fresh source-access grants, NOT a budget wallet.
-- Bootstrap grants nothing. Old schema bytes/rows/periods/unknown stay untouched.
CREATE TABLE IF NOT EXISTS rag_registered_course_refresh_authorizations (
 id uuid PRIMARY KEY,
 authorization_id text NOT NULL CHECK(authorization_id='aearn-development-20260927'),
 target_key text NOT NULL CHECK(target_key IN ('python_reference','sqlite_select','sqlite_expression','sqlite_functions','learnx_python')),
 canonical_original_attempt_id uuid NOT NULL REFERENCES rag_registered_fetch_attempts(id),
 canonical_accounting_root_id text NOT NULL REFERENCES rag_budget_authority_roots(root_id),
 latest_attempt_id uuid NOT NULL REFERENCES rag_registered_fetch_attempts(id),
 latest_capture_id uuid NOT NULL REFERENCES rag_registered_source_captures(id),
 latest_capture_sha256 text NOT NULL CHECK(latest_capture_sha256 ~ '^[0-9a-f]{64}$'),
 canonical_url_sha256 text NOT NULL CHECK(canonical_url_sha256 ~ '^[0-9a-f]{64}$'),
 lineage_snapshot jsonb NOT NULL CHECK(jsonb_typeof(lineage_snapshot)='object'),
 lineage_sha256 text NOT NULL CHECK(lineage_sha256 ~ '^[0-9a-f]{64}$'),
 supplemental_authorization_id uuid NOT NULL UNIQUE,
 dispatch_id uuid NOT NULL UNIQUE,
 policy_id text NOT NULL UNIQUE,
 generation integer NOT NULL CHECK(generation IN (2,4)),
 root_id text NOT NULL UNIQUE REFERENCES rag_budget_authority_roots(root_id),
 request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
 operation_key text NOT NULL UNIQUE CHECK(operation_key ~ '^course[.]refresh[.]20261006[.][0-9a-f]{32}$'),
 carried_dispatch_units integer NOT NULL CHECK(carried_dispatch_units IN (1,3)),
 carried_unknown_units integer NOT NULL CHECK(carried_unknown_units IN (0,1)),
 additional_dispatch_units integer NOT NULL DEFAULT 1 CHECK(additional_dispatch_units=1),
 cumulative_dispatch_ceiling integer NOT NULL CHECK(cumulative_dispatch_ceiling=carried_dispatch_units+1),
 issued_at timestamptz NOT NULL,
 source_permission_expires_at timestamptz NOT NULL,
 retention_permission_expires_at timestamptz NOT NULL,
 source_expires_at timestamptz NOT NULL,
 dispatch_expires_at timestamptz NOT NULL,
 CHECK(source_expires_at>issued_at AND source_expires_at<=issued_at+interval '7 days'
   AND source_expires_at<=source_permission_expires_at AND source_expires_at<=retention_permission_expires_at),
 CHECK(dispatch_expires_at>issued_at AND dispatch_expires_at<=issued_at+interval '30 minutes'
   AND dispatch_expires_at<=source_expires_at),
 CHECK(root_id='root.course-refresh.20261006.'||target_key),
 UNIQUE(authorization_id,canonical_original_attempt_id),
 UNIQUE(authorization_id,canonical_url_sha256),
 UNIQUE(id,supplemental_authorization_id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash),
 FOREIGN KEY(policy_id,generation,canonical_url_sha256)
   REFERENCES rag_registered_source_policies(policy_id,generation,canonical_url_sha256)
);
ALTER TABLE rag_registered_supplemental_authorizations
 ADD COLUMN IF NOT EXISTS course_refresh_authorization_id uuid;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='rag_registered_supplemental_authorizations'::regclass
  AND conname='fk_rag_course_refresh_supplemental') THEN
  ALTER TABLE rag_registered_supplemental_authorizations ADD CONSTRAINT fk_rag_course_refresh_supplemental
   FOREIGN KEY(course_refresh_authorization_id,id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash)
   REFERENCES rag_registered_course_refresh_authorizations
    (id,supplemental_authorization_id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash);
 END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_course_refresh_supplemental
 ON rag_registered_supplemental_authorizations(course_refresh_authorization_id)
 WHERE course_refresh_authorization_id IS NOT NULL;

-- Exclude ONLY the new explicit branch from frozen historical lineage.
-- UTC is fixed so session timezone cannot alter an immutable snapshot hash.
CREATE OR REPLACE FUNCTION rag_registered_course_refresh_lineage(url_hash text)
 RETURNS jsonb LANGUAGE sql SET TimeZone='UTC' AS $$
 SELECT jsonb_build_object(
 'attempts',coalesce((SELECT jsonb_agg(to_jsonb(a) ORDER BY a.dispatched_at,a.id)
   FROM rag_registered_fetch_attempts a WHERE a.canonical_url_sha256=url_hash),'[]'::jsonb),
 'captures',coalesce((SELECT jsonb_agg(to_jsonb(c)-'captured_body'-'transport_proof' ORDER BY c.fetched_at,c.id)
   FROM rag_registered_source_captures c JOIN rag_registered_fetch_attempts a ON a.id=c.fetch_attempt_id
   WHERE a.canonical_url_sha256=url_hash),'[]'::jsonb),
 'authorizations',coalesce((SELECT jsonb_agg(to_jsonb(s) ORDER BY s.created_at,s.id)
   FROM rag_registered_supplemental_authorizations s WHERE s.canonical_url_sha256=url_hash
     AND s.course_refresh_authorization_id IS NULL),'[]'::jsonb),
 'allowances',coalesce((SELECT jsonb_agg(to_jsonb(f) ORDER BY f.created_at,f.id)
   FROM rag_registered_final_followup_allowances f WHERE f.canonical_url_sha256=url_hash),'[]'::jsonb),
 'revocations',coalesce((SELECT jsonb_agg(to_jsonb(v) ORDER BY v.authorization_id)
   FROM rag_registered_supplemental_revocations v JOIN rag_registered_supplemental_authorizations s
   ON s.id=v.authorization_id WHERE s.canonical_url_sha256=url_hash),'[]'::jsonb),
 'policies',coalesce((SELECT jsonb_agg(to_jsonb(p) ORDER BY p.policy_id)
   FROM rag_registered_source_policies p WHERE p.policy_id IN
   (SELECT a.policy_id FROM rag_registered_fetch_attempts a WHERE a.canonical_url_sha256=url_hash)),'[]'::jsonb),
 'roots',coalesce((SELECT jsonb_agg(to_jsonb(r) ORDER BY r.root_id)
   FROM rag_budget_authority_roots r WHERE r.root_id IN
   (SELECT a.root_id FROM rag_registered_fetch_attempts a WHERE a.canonical_url_sha256=url_hash)),'[]'::jsonb),
 'periods',coalesce((SELECT jsonb_agg(to_jsonb(p) ORDER BY p.root_id,p.period_key)
   FROM rag_budget_periods p WHERE p.root_id IN
   (SELECT a.root_id FROM rag_registered_fetch_attempts a WHERE a.canonical_url_sha256=url_hash)),'[]'::jsonb),
 'reservations',coalesce((SELECT jsonb_agg(to_jsonb(b) ORDER BY b.id)
   FROM rag_budget_reservations b WHERE b.root_id IN
   (SELECT a.root_id FROM rag_registered_fetch_attempts a WHERE a.canonical_url_sha256=url_hash)),'[]'::jsonb));
$$;

CREATE OR REPLACE FUNCTION rag_registered_course_refresh_check(
 grant_row rag_registered_course_refresh_authorizations, dispatch_check boolean DEFAULT false
) RETURNS void LANGUAGE plpgsql SET TimeZone='UTC' AS $$
DECLARE original_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE middle_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE latest_capture rag_registered_source_captures%ROWTYPE;
DECLARE latest_policy rag_registered_source_policies%ROWTYPE;
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
DECLARE root_row rag_budget_authority_roots%ROWTYPE;
DECLARE latest_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE middle_auth rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE correction rag_registered_final_followup_allowances%ROWTYPE;
DECLARE snapshot jsonb;
DECLARE url text;
DECLARE subject text;
DECLARE facet text;
DECLARE license text;
DECLARE expected_count integer;
DECLARE expected_unknown integer;
DECLARE actual_count integer;
DECLARE actual_unknown integer;
DECLARE db_now timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR
    current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'course refresh owned database and read committed required' USING ERRCODE='23514';
 END IF;
 SELECT * INTO original_row FROM rag_registered_fetch_attempts
  WHERE id=grant_row.canonical_original_attempt_id FOR UPDATE;
 SELECT * INTO latest_row FROM rag_registered_fetch_attempts WHERE id=grant_row.latest_attempt_id FOR SHARE;
 SELECT * INTO latest_capture FROM rag_registered_source_captures WHERE id=grant_row.latest_capture_id FOR SHARE;
 SELECT * INTO latest_policy FROM rag_registered_source_policies WHERE policy_id=latest_row.policy_id FOR SHARE;
 SELECT * INTO policy_row FROM rag_registered_source_policies WHERE policy_id=grant_row.policy_id FOR SHARE;
 SELECT * INTO root_row FROM rag_budget_authority_roots WHERE root_id=grant_row.root_id FOR SHARE;
 db_now:=clock_timestamp();
 CASE grant_row.target_key
 WHEN 'python_reference' THEN url:='https://docs.python.org/3/reference/simple_stmts.html';subject:='route.python';facet:='fundamentals';license:='psf-2.0';
 WHEN 'sqlite_select' THEN url:='https://www.sqlite.org/lang_select.html';subject:='route.sql';facet:='queries';license:='sqlite-public-domain';
 WHEN 'sqlite_expression' THEN url:='https://www.sqlite.org/lang_expr.html';subject:='route.sql';facet:='queries';license:='sqlite-public-domain';
 WHEN 'sqlite_functions' THEN url:='https://www.sqlite.org/lang_corefunc.html';subject:='route.sql';facet:='queries';license:='sqlite-public-domain';
 WHEN 'learnx_python' THEN url:='https://learnxinyminutes.com/python/';subject:='route.python';facet:='fundamentals';license:='cc-by-sa-3.0';
 ELSE RAISE EXCEPTION 'course refresh unsupported target' USING ERRCODE='23514';
 END CASE;
 expected_count:=CASE WHEN grant_row.target_key='sqlite_select' THEN 3 ELSE 1 END;
 expected_unknown:=CASE WHEN expected_count=3 THEN 1 ELSE 0 END;
 SELECT count(*),count(*) FILTER(WHERE state='unknown') INTO actual_count,actual_unknown
  FROM rag_registered_fetch_attempts WHERE canonical_url_sha256=grant_row.canonical_url_sha256;
 snapshot:=rag_registered_course_refresh_lineage(grant_row.canonical_url_sha256);
 IF grant_row.authorization_id<>'aearn-development-20260927' OR
    grant_row.canonical_url_sha256<>encode(digest(url,'sha256'),'hex') OR
    original_row.id IS NULL OR original_row.supplemental_authorization_id IS NOT NULL OR
    original_row.state<>'settled' OR original_row.generation<>1 OR
    original_row.root_id<>grant_row.canonical_accounting_root_id OR
    original_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
    latest_row.id IS NULL OR latest_row.state<>'settled' OR
    latest_row.canonical_url_sha256<>grant_row.canonical_url_sha256 OR
    actual_count<>expected_count OR actual_unknown<>expected_unknown OR
    grant_row.carried_dispatch_units<>actual_count OR grant_row.carried_unknown_units<>actual_unknown OR
    grant_row.cumulative_dispatch_ceiling<>actual_count+1 OR grant_row.additional_dispatch_units<>1 OR
    grant_row.lineage_snapshot IS DISTINCT FROM snapshot OR
    grant_row.lineage_sha256<>encode(digest(snapshot::text,'sha256'),'hex') OR
    (SELECT count(*) FROM rag_registered_fetch_attempts WHERE canonical_url_sha256=grant_row.canonical_url_sha256
      AND supplemental_authorization_id IS NULL)<>1 OR
    EXISTS(SELECT 1 FROM rag_registered_course_refresh_authorizations r
      WHERE (r.canonical_original_attempt_id=original_row.id OR r.canonical_url_sha256=grant_row.canonical_url_sha256)
        AND r.id<>grant_row.id) OR
    grant_row.issued_at>db_now OR db_now-grant_row.issued_at>interval '30 minutes' OR
    grant_row.source_expires_at<=db_now OR grant_row.source_expires_at>grant_row.issued_at+interval '7 days' OR
    grant_row.source_expires_at>grant_row.source_permission_expires_at OR
    grant_row.source_expires_at>grant_row.retention_permission_expires_at OR
    (dispatch_check AND grant_row.dispatch_expires_at<=db_now) THEN
  RAISE EXCEPTION 'course refresh lineage counter or lifetime denied' USING ERRCODE='23514';
 END IF;
 -- Every old policy/root is naturally expired, not revived or silently widened.
 IF latest_policy.policy_id IS NULL OR latest_policy.canonical_url<>url OR
    latest_policy.subject_id<>subject OR latest_policy.subject_version<>'1.0' OR
    latest_policy.facets<>ARRAY[facet] OR latest_policy.license_id<>license OR
    latest_policy.origin<>(CASE WHEN grant_row.target_key='learnx_python' THEN 'tutorial' ELSE 'official' END) OR
    latest_policy.reading_level<>'beginner' OR
    latest_policy.allowed_usages<>(CASE WHEN grant_row.target_key='learnx_python' THEN ARRAY['main_teaching']
      WHEN grant_row.target_key='sqlite_select' THEN ARRAY['assessment_evidence']
      ELSE ARRAY['assessment_evidence','main_teaching'] END) OR
    EXISTS(SELECT 1 FROM rag_registered_source_policies p JOIN rag_registered_fetch_attempts a ON a.policy_id=p.policy_id
      JOIN rag_budget_authority_roots r ON r.root_id=a.root_id
      WHERE a.canonical_url_sha256=grant_row.canonical_url_sha256 AND
       (p.enabled IS NOT TRUE OR p.revoked_at IS NOT NULL OR p.expires_at>db_now OR p.retention_until>db_now
        OR p.immutable_history_allowed IS NOT TRUE OR r.enabled IS NOT TRUE OR r.delegation_expires_at>db_now
        OR r.period_end>db_now OR policy_row.max_captured_bytes>p.max_captured_bytes
        OR ROW(r.policy_id,r.policy_generation) IS DISTINCT FROM ROW(p.policy_id,p.generation)
        OR ROW(p.subject_id,p.subject_version,p.facets,p.origin,p.reading_level,p.canonical_url,p.host,p.path,p.license_id,p.allowed_usages)
          IS DISTINCT FROM ROW(latest_policy.subject_id,latest_policy.subject_version,latest_policy.facets,latest_policy.origin,
            latest_policy.reading_level,latest_policy.canonical_url,latest_policy.host,latest_policy.path,latest_policy.license_id,latest_policy.allowed_usages))) OR
    EXISTS(SELECT 1 FROM rag_registered_source_captures c JOIN rag_registered_fetch_attempts a ON a.id=c.fetch_attempt_id
      WHERE a.canonical_url_sha256=grant_row.canonical_url_sha256 AND
       (c.cleared_at IS NOT NULL OR c.captured_body IS NULL OR c.transport_proof IS NULL OR
        c.provider_attempt_id IS NOT NULL OR c.evidence_level<>'live_egress_attested' OR
        c.transport_proof_sha256 IS NULL OR c.attestor_key_sha256 IS NULL OR c.worker_image_sha256 IS NULL OR
        c.retention_until>db_now OR c.fetched_sha256<>a.response_sha256 OR c.captured_bytes<>a.response_bytes OR
        encode(digest(c.captured_body,'sha256'),'hex')<>c.fetched_sha256 OR
        octet_length(c.captured_body)<>c.captured_bytes OR
        encode(digest(c.transport_proof,'sha256'),'hex')<>c.transport_proof_sha256)) OR
    latest_capture.id IS NULL OR latest_capture.fetch_attempt_id<>latest_row.id OR
    latest_capture.fetched_sha256<>grant_row.latest_capture_sha256 OR latest_capture.cleared_at IS NOT NULL OR
    latest_capture.captured_body IS NULL OR latest_capture.transport_proof_sha256 IS NULL OR
    latest_capture.attestor_key_sha256 IS NULL OR latest_capture.worker_image_sha256 IS NULL THEN
  RAISE EXCEPTION 'course refresh historical authority denied' USING ERRCODE='23514';
 END IF;
 IF expected_count=1 THEN
  IF latest_row.id<>original_row.id OR jsonb_array_length(snapshot->'captures')<>1 OR
     jsonb_array_length(snapshot->'authorizations')<>0 OR jsonb_array_length(snapshot->'allowances')<>0 OR
     jsonb_array_length(snapshot->'revocations')<>0 THEN
   RAISE EXCEPTION 'course refresh ordinary lineage denied' USING ERRCODE='23514';
  END IF;
 ELSE
  SELECT * INTO middle_row FROM rag_registered_fetch_attempts WHERE canonical_url_sha256=grant_row.canonical_url_sha256 AND state='unknown';
  SELECT * INTO middle_auth FROM rag_registered_supplemental_authorizations WHERE id=middle_row.supplemental_authorization_id;
  SELECT * INTO latest_auth FROM rag_registered_supplemental_authorizations WHERE id=latest_row.supplemental_authorization_id;
  SELECT * INTO correction FROM rag_registered_final_followup_allowances WHERE id=latest_auth.explicit_followup_id;
  IF latest_row.generation<>3 OR middle_row.generation<>1 OR
     middle_row.error_code IS DISTINCT FROM 'EGRESS_UNVERIFIED_SIGNATURE_PID_NAMESPACE' OR
     middle_row.response_sha256 IS NOT NULL OR middle_row.response_bytes IS NOT NULL OR
     middle_row.settled_at IS NOT NULL OR middle_row.dispatched_at<original_row.settled_at OR
     latest_row.dispatched_at<middle_row.dispatched_at OR middle_auth.id IS NULL OR latest_auth.id IS NULL OR
     middle_auth.prior_attempt_id<>original_row.id OR middle_auth.dispatch_id<>middle_row.id OR
     middle_auth.explicit_followup_id IS NOT NULL OR middle_auth.replaces_authorization_id IS NOT NULL OR
     latest_auth.prior_attempt_id<>original_row.id OR latest_auth.dispatch_id<>latest_row.id OR
     correction.id IS NULL OR correction.generation<>3 OR correction.original_attempt_id<>original_row.id OR
     correction.latest_attempt_id<>middle_row.id OR correction.authorization_id<>latest_auth.id OR
     correction.settled_source_failed_authorization_id IS DISTINCT FROM middle_auth.id OR
     correction.settled_source_capture_id IS NULL OR correction.settled_source_capture_sha256 IS NULL OR
     NOT EXISTS(SELECT 1 FROM rag_registered_source_captures WHERE id=correction.settled_source_capture_id
       AND fetch_attempt_id=original_row.id AND fetched_sha256=correction.settled_source_capture_sha256) OR
     correction.settled_source_capture_sha256<>(SELECT fetched_sha256 FROM rag_registered_source_captures
       WHERE id=correction.settled_source_capture_id AND fetch_attempt_id=original_row.id) OR
     latest_policy.source_handle<>(SELECT source_handle FROM rag_registered_source_policies WHERE policy_id=middle_row.policy_id) OR
     jsonb_array_length(snapshot->'captures')<>2 OR jsonb_array_length(snapshot->'authorizations')<>2 OR
     jsonb_array_length(snapshot->'allowances')<>1 OR jsonb_array_length(snapshot->'revocations')<>0 THEN
   RAISE EXCEPTION 'course refresh exact SELECT correction chain denied' USING ERRCODE='23514';
  END IF;
 END IF;
 -- This new access root is NOT a core budget and has no new budget period/reservation.
 IF policy_row.policy_id IS NULL OR root_row.root_id IS NULL OR
    grant_row.root_id<>'root.course-refresh.20261006.'||grant_row.target_key OR
    policy_row.root_id<>root_row.root_id OR policy_row.generation<>latest_row.generation+1 OR
    grant_row.generation<>policy_row.generation OR policy_row.enabled IS NOT TRUE OR policy_row.revoked_at IS NOT NULL OR
    ROW(policy_row.source_handle,policy_row.subject_id,policy_row.subject_version,policy_row.facets,policy_row.origin,
      policy_row.reading_level,policy_row.canonical_url,policy_row.canonical_url_sha256,policy_row.host,policy_row.path,
      policy_row.license_id,policy_row.allowed_usages,policy_row.immutable_history_allowed)
      IS DISTINCT FROM ROW(latest_policy.source_handle,latest_policy.subject_id,latest_policy.subject_version,latest_policy.facets,
        latest_policy.origin,latest_policy.reading_level,latest_policy.canonical_url,latest_policy.canonical_url_sha256,latest_policy.host,
        latest_policy.path,latest_policy.license_id,latest_policy.allowed_usages,latest_policy.immutable_history_allowed) OR
    policy_row.max_captured_bytes>latest_policy.max_captured_bytes OR
    policy_row.expires_at<>grant_row.source_expires_at OR policy_row.retention_until<>grant_row.source_expires_at OR
    root_row.enabled IS NOT TRUE OR root_row.policy_id<>policy_row.policy_id OR root_row.policy_generation<>policy_row.generation OR
    root_row.cap_units<>grant_row.cumulative_dispatch_ceiling OR root_row.period_key<>'source-access-only.20261006' OR
    root_row.period_start<>grant_row.issued_at OR root_row.period_end<>grant_row.source_expires_at OR
    root_row.delegation_expires_at<>grant_row.source_expires_at OR root_row.delegation_generation<>1 OR
    root_row.delegation_id<>'delegation.course-refresh.'||replace(grant_row.id::text,'-','') OR
    EXISTS(SELECT 1 FROM rag_budget_periods WHERE root_id=root_row.root_id) OR
    EXISTS(SELECT 1 FROM rag_budget_reservations WHERE root_id=root_row.root_id) THEN
  RAISE EXCEPTION 'course refresh access root and exact rights denied' USING ERRCODE='23514';
 END IF;
END $$;

CREATE OR REPLACE FUNCTION rag_registered_course_refresh_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'course refresh immutable' USING ERRCODE='23514';
 END IF;
 PERFORM rag_registered_course_refresh_check(NEW,true);
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_course_refresh_guard ON rag_registered_course_refresh_authorizations;
CREATE TRIGGER trg_rag_course_refresh_guard BEFORE INSERT OR UPDATE OR DELETE
 ON rag_registered_course_refresh_authorizations FOR EACH ROW EXECUTE FUNCTION rag_registered_course_refresh_guard();

CREATE OR REPLACE FUNCTION rag_registered_course_refresh_auth_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE grant_row rag_registered_course_refresh_authorizations%ROWTYPE;
BEGIN
 IF NEW.course_refresh_authorization_id IS NULL THEN
  IF NEW.root_id LIKE 'root.course-refresh.20261006.%' THEN
   RAISE EXCEPTION 'source access root requires exact course refresh' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO grant_row FROM rag_registered_course_refresh_authorizations
  WHERE id=NEW.course_refresh_authorization_id FOR SHARE;
 IF grant_row.id IS NULL OR NEW.explicit_followup_id IS NOT NULL OR NEW.replaces_authorization_id IS NOT NULL OR
  ROW(NEW.id,NEW.dispatch_id,NEW.policy_id,NEW.generation,NEW.canonical_url_sha256,NEW.root_id,NEW.request_hash,
      NEW.prior_attempt_id,NEW.expires_at,NEW.approval_ref)
    IS DISTINCT FROM ROW(grant_row.supplemental_authorization_id,grant_row.dispatch_id,grant_row.policy_id,
      grant_row.generation,grant_row.canonical_url_sha256,grant_row.root_id,grant_row.request_hash,
      grant_row.latest_attempt_id,grant_row.dispatch_expires_at,'standingpolicy.course-refresh.20261006'::text) THEN
  RAISE EXCEPTION 'course refresh supplemental binding denied' USING ERRCODE='23514';
 END IF;
 PERFORM rag_registered_course_refresh_check(grant_row,true);
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_0000_rag_course_refresh_auth ON rag_registered_supplemental_authorizations;
CREATE TRIGGER trg_0000_rag_course_refresh_auth BEFORE INSERT ON rag_registered_supplemental_authorizations
 FOR EACH ROW EXECUTE FUNCTION rag_registered_course_refresh_auth_guard();

CREATE OR REPLACE FUNCTION rag_registered_course_refresh_dispatch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE grant_row rag_registered_course_refresh_authorizations%ROWTYPE;
BEGIN
 IF NEW.root_id NOT LIKE 'root.course-refresh.20261006.%' THEN RETURN NEW; END IF;
 SELECT * INTO grant_row FROM rag_registered_course_refresh_authorizations WHERE root_id=NEW.root_id FOR SHARE;
 IF grant_row.id IS NULL OR NEW.state<>'dispatched' OR
  ROW(NEW.id,NEW.policy_id,NEW.generation,NEW.canonical_url_sha256,NEW.root_id,NEW.request_hash,
      NEW.operation_key,NEW.supplemental_authorization_id)
    IS DISTINCT FROM ROW(grant_row.dispatch_id,grant_row.policy_id,grant_row.generation,
      grant_row.canonical_url_sha256,grant_row.root_id,grant_row.request_hash,
      grant_row.operation_key,grant_row.supplemental_authorization_id) THEN
  RAISE EXCEPTION 'course refresh dispatch binding denied' USING ERRCODE='23514';
 END IF;
 PERFORM rag_registered_course_refresh_check(grant_row,true);
 RETURN NEW; -- The existing unique ID/auth makes failure/unknown/crash non-refundable.
END $$;
DROP TRIGGER IF EXISTS trg_0000_rag_course_refresh_dispatch ON rag_registered_fetch_attempts;
CREATE TRIGGER trg_0000_rag_course_refresh_dispatch BEFORE INSERT ON rag_registered_fetch_attempts
 FOR EACH ROW EXECUTE FUNCTION rag_registered_course_refresh_dispatch_guard();

-- Copy the current400 recovery guard with ONLY an explicit checked498 branch;
-- legacy ordinary/correction/final-followup paths are otherwise byte-equivalent.
CREATE OR REPLACE FUNCTION rag_registered_supplemental_recovery_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior_row rag_registered_fetch_attempts%ROWTYPE;
DECLARE old_row rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE auth_count integer;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'supplemental authorization immutable' USING ERRCODE='23514';
  END IF;
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'supplemental correction requires read committed' USING ERRCODE='23514';
  END IF;
  IF NEW.course_refresh_authorization_id IS NOT NULL THEN
    PERFORM rag_registered_course_refresh_check(r,true)
      FROM rag_registered_course_refresh_authorizations r WHERE id=NEW.course_refresh_authorization_id;
    RETURN NEW; -- Exact binding is also enforced by FK and independent auth guard.
  END IF;
  IF NEW.explicit_followup_id IS NOT NULL THEN RETURN NEW; END IF;
  -- This row is the common serialization point for issue, revoke and dispatch.
  SELECT * INTO prior_row FROM rag_registered_fetch_attempts
    WHERE id=NEW.prior_attempt_id FOR UPDATE;
  IF prior_row.id IS NULL OR prior_row.state NOT IN ('unknown','settled') OR
     prior_row.supplemental_authorization_id IS NOT NULL OR
     prior_row.canonical_url_sha256<>NEW.canonical_url_sha256 OR
     NEW.expires_at<=clock_timestamp() THEN
    RAISE EXCEPTION 'supplemental authorization needs terminal original attempt' USING ERRCODE='23514';
  END IF;
  SELECT count(*) INTO auth_count FROM rag_registered_supplemental_authorizations
    WHERE prior_attempt_id=NEW.prior_attempt_id;
  IF auth_count=0 THEN
    IF NEW.replaces_authorization_id IS NOT NULL THEN
      RAISE EXCEPTION 'replacement has no original authorization' USING ERRCODE='23514';
    END IF;
  ELSIF auth_count=1 AND NEW.replaces_authorization_id IS NOT NULL THEN
    SELECT * INTO old_row FROM rag_registered_supplemental_authorizations
      WHERE id=NEW.replaces_authorization_id AND prior_attempt_id=NEW.prior_attempt_id FOR SHARE;
    IF old_row.id IS NULL OR old_row.replaces_authorization_id IS NOT NULL OR
       EXISTS (SELECT 1 FROM rag_registered_fetch_attempts a
         WHERE a.policy_id=NEW.policy_id AND a.generation=NEW.generation
           AND a.canonical_url_sha256=NEW.canonical_url_sha256) OR
       NOT EXISTS (SELECT 1 FROM rag_registered_supplemental_revocations r
         WHERE r.authorization_id=old_row.id AND r.prior_attempt_id=NEW.prior_attempt_id) OR
       EXISTS (SELECT 1 FROM rag_registered_fetch_attempts a
         WHERE a.supplemental_authorization_id=old_row.id) THEN
      RAISE EXCEPTION 'supplemental replacement denied' USING ERRCODE='23514';
    END IF;
  ELSE
    RAISE EXCEPTION 'supplemental limit exceeded' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;

-- Do not change400's partial index. New physical predecessor is the actual
-- terminal latest attempt; canonical original is separately immutable/unique.
-- This also lets a complete old400 -> new498 manifest replay rebuild that index.

-- 390 also guards every actual dispatch. The SELECT498 physical predecessor is
-- the latest supplemental terminal, so only this exact checked branch may bypass
-- 390's original-only predecessor rule; legacy revocation/expiry checks stay intact.
CREATE OR REPLACE FUNCTION rag_registered_supplemental_recovery_dispatch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE auth_row rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE prior_row rag_registered_fetch_attempts%ROWTYPE;
BEGIN
  IF NEW.supplemental_authorization_id IS NULL THEN RETURN NEW; END IF;
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'supplemental dispatch requires read committed' USING ERRCODE='23514';
  END IF;
  SELECT * INTO auth_row FROM rag_registered_supplemental_authorizations
    WHERE id=NEW.supplemental_authorization_id;
  IF auth_row.id IS NULL THEN
    RAISE EXCEPTION 'supplemental dispatch denied' USING ERRCODE='23514';
  END IF;
  IF auth_row.course_refresh_authorization_id IS NOT NULL THEN
    PERFORM rag_registered_course_refresh_check(r,true)
      FROM rag_registered_course_refresh_authorizations r WHERE id=auth_row.course_refresh_authorization_id;
    RETURN NEW; -- Independent498 dispatch guard/composite FK binds every coordinate.
  END IF;
  SELECT * INTO prior_row FROM rag_registered_fetch_attempts
    WHERE id=auth_row.prior_attempt_id FOR UPDATE;
  SELECT * INTO auth_row FROM rag_registered_supplemental_authorizations
    WHERE id=NEW.supplemental_authorization_id FOR SHARE;
  IF auth_row.id IS NULL OR auth_row.expires_at<=clock_timestamp() OR
     EXISTS (SELECT 1 FROM rag_registered_supplemental_revocations r
       WHERE r.authorization_id=auth_row.id) OR
     NEW.id<>auth_row.dispatch_id OR NEW.policy_id<>auth_row.policy_id OR
     NEW.generation<>auth_row.generation OR NEW.canonical_url_sha256<>auth_row.canonical_url_sha256 OR
     NEW.root_id<>auth_row.root_id OR NEW.request_hash<>auth_row.request_hash OR
     NEW.state<>'dispatched' OR prior_row.id IS NULL OR
     prior_row.state NOT IN ('unknown','settled') OR
     prior_row.supplemental_authorization_id IS NOT NULL OR
     prior_row.canonical_url_sha256<>NEW.canonical_url_sha256 THEN
    RAISE EXCEPTION 'supplemental dispatch denied' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;

-- Existing350 trigger bodies, with ONLY the independently checked498 branch.
CREATE OR REPLACE FUNCTION rag_registered_supplemental_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior_row rag_registered_fetch_attempts%ROWTYPE;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'supplemental authorization immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.course_refresh_authorization_id IS NOT NULL THEN
    PERFORM rag_registered_course_refresh_check(r,true)
      FROM rag_registered_course_refresh_authorizations r WHERE id=NEW.course_refresh_authorization_id;
    RETURN NEW; -- Independent498 auth guard/composite FK binds every coordinate.
  END IF;
  SELECT * INTO prior_row FROM rag_registered_fetch_attempts
    WHERE id=NEW.prior_attempt_id FOR SHARE;
  IF prior_row.id IS NULL OR prior_row.state NOT IN ('unknown','settled') OR
     prior_row.supplemental_authorization_id IS NOT NULL OR
     prior_row.canonical_url_sha256<>NEW.canonical_url_sha256 OR
     NEW.expires_at<=clock_timestamp() THEN
    RAISE EXCEPTION 'supplemental authorization needs terminal original attempt' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION rag_registered_supplemental_dispatch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE auth_row rag_registered_supplemental_authorizations%ROWTYPE;
DECLARE prior_row rag_registered_fetch_attempts%ROWTYPE;
BEGIN
  IF NEW.supplemental_authorization_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT * INTO auth_row FROM rag_registered_supplemental_authorizations
    WHERE id=NEW.supplemental_authorization_id FOR SHARE;
  IF auth_row.course_refresh_authorization_id IS NOT NULL THEN
    PERFORM rag_registered_course_refresh_check(r,true)
      FROM rag_registered_course_refresh_authorizations r WHERE id=auth_row.course_refresh_authorization_id;
    RETURN NEW; -- Independent498 dispatch guard/composite FK binds every coordinate.
  END IF;
  SELECT * INTO prior_row FROM rag_registered_fetch_attempts
    WHERE id=auth_row.prior_attempt_id FOR SHARE;
  IF auth_row.id IS NULL OR auth_row.expires_at<=clock_timestamp() OR
     NEW.id<>auth_row.dispatch_id OR NEW.policy_id<>auth_row.policy_id OR
     NEW.generation<>auth_row.generation OR NEW.canonical_url_sha256<>auth_row.canonical_url_sha256 OR
     NEW.root_id<>auth_row.root_id OR NEW.request_hash<>auth_row.request_hash OR
     NEW.state<>'dispatched' OR prior_row.id IS NULL OR
     prior_row.state NOT IN ('unknown','settled') OR
     prior_row.supplemental_authorization_id IS NOT NULL OR
     prior_row.canonical_url_sha256<>NEW.canonical_url_sha256 THEN
    RAISE EXCEPTION 'supplemental dispatch denied' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
