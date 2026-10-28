-- M03 2026-10-19 exact three once grants + P1 same-byte current helper.
-- Installation issues nothing, changes no old rows, and installs no caller.
CREATE OR REPLACE FUNCTION public.rag_registered_m03_sqlite_recovery_check(
 grant_row public.rag_registered_course_refresh_authorizations, dispatch_check boolean
) RETURNS void LANGUAGE plpgsql SET TimeZone='UTC' AS $recovery584$
DECLARE
 parent public.rag_registered_course_refresh_authorizations%ROWTYPE;
 original public.rag_registered_fetch_attempts%ROWTYPE;
 latest public.rag_registered_fetch_attempts%ROWTYPE;
 capture public.rag_registered_source_captures%ROWTYPE;
 old_policy public.rag_registered_source_policies%ROWTYPE;
 policy public.rag_registered_source_policies%ROWTYPE;
 root public.rag_budget_authority_roots%ROWTYPE;
 supplemental public.rag_registered_supplemental_authorizations%ROWTYPE;
 spec record; snapshot jsonb; historical jsonb; key text; clock timestamptz;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR
    current_setting('transaction_isolation')<>'read committed' THEN
  RAISE check_violation USING MESSAGE='584 owned read committed required'; END IF;
 SELECT * INTO spec FROM (VALUES
 ('sqlite_select','2cbce7db-d8a6-5327-996c-4b8cc0917523'::uuid,'c4c70947-cf96-522c-819c-68b1c699b06d'::uuid,
  '8256098c-ddaa-4dd0-b387-0eea34b7596c'::uuid,'4ec45218-10a9-5b5a-8410-febf3e4b0820'::uuid,5,4,1,'https://www.sqlite.org/lang_select.html'),
 ('sqlite_expression','fd097ede-285d-5d68-9aae-3be0a2fbbd40'::uuid,'98fc47e2-0256-5cad-85ad-9663c43ffb9c'::uuid,
  'e68a79ad-0319-4109-b663-81f6c241d0fd'::uuid,'7c4f1791-8f69-5e83-9401-70da54abb3b1'::uuid,3,2,0,'https://www.sqlite.org/lang_expr.html'),
 ('sqlite_functions','618f9749-2130-50b7-8474-f5193ebb986c'::uuid,'3b47fb6f-84ae-546a-8ae9-58644e3475ce'::uuid,
  'bfd46b39-50b5-4444-ba85-32f54550f5d3'::uuid,'e8cf0b32-d1a8-5ed1-b80a-f965f5f008be'::uuid,3,2,0,'https://www.sqlite.org/lang_corefunc.html')
 ) AS v(target,aid,parent_id,original_id,latest_id,generation,carry,unknown,url)
 WHERE v.aid=grant_row.id AND v.target=grant_row.target_key;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='584 fixed grant required'; END IF;
 -- Same canonical lock as every old dispatcher, before all lineage observations.
 SELECT * INTO original FROM public.rag_registered_fetch_attempts WHERE id=spec.original_id FOR UPDATE;
 SELECT * INTO parent FROM public.rag_registered_course_refresh_authorizations WHERE id=spec.parent_id FOR SHARE;
 SELECT * INTO latest FROM public.rag_registered_fetch_attempts WHERE id=spec.latest_id FOR SHARE;
 SELECT * INTO capture FROM public.rag_registered_source_captures WHERE id=grant_row.latest_capture_id FOR SHARE;
 SELECT * INTO old_policy FROM public.rag_registered_source_policies WHERE policy_id=latest.policy_id FOR SHARE;
 SELECT * INTO policy FROM public.rag_registered_source_policies WHERE policy_id=grant_row.policy_id FOR SHARE;
 SELECT * INTO root FROM public.rag_budget_authority_roots WHERE root_id=grant_row.root_id FOR SHARE;
 SELECT * INTO supplemental FROM public.rag_registered_supplemental_authorizations
  WHERE id=latest.supplemental_authorization_id FOR SHARE;
 snapshot:=public.rag_registered_course_refresh_lineage(grant_row.canonical_url_sha256);
 clock:=clock_timestamp();
 IF original.id IS NULL OR parent.id IS NULL OR latest.id IS NULL OR capture.id IS NULL OR
    old_policy.policy_id IS NULL OR policy.policy_id IS NULL OR root.root_id IS NULL OR supplemental.id IS NULL OR
    ROW(grant_row.authorization_id,grant_row.canonical_original_attempt_id,grant_row.canonical_accounting_root_id,
        grant_row.latest_attempt_id,grant_row.latest_capture_sha256,grant_row.generation,
        grant_row.carried_dispatch_units,grant_row.carried_unknown_units,grant_row.additional_dispatch_units,
        grant_row.cumulative_dispatch_ceiling,grant_row.canonical_url_sha256,grant_row.policy_id,grant_row.root_id,
        grant_row.operation_key)
    IS DISTINCT FROM ROW('aearn-development-20260927'::text,original.id,original.root_id,latest.id,capture.fetched_sha256,
        spec.generation,spec.carry,spec.unknown,1,spec.carry+1,encode(digest(spec.url,'sha256'),'hex'),
        'source.course-refresh.20261019.m03.'||spec.target,
        'root.course-refresh.20261006.'||spec.target||'.m03.20261019',
        'course.refresh.20261006.'||replace(spec.aid::text,'-','')) OR
    original.supplemental_authorization_id IS NOT NULL OR original.state<>'settled' OR original.generation<>1 OR
    parent.dispatch_id<>latest.id OR parent.target_key<>spec.target OR
    parent.canonical_original_attempt_id<>original.id OR parent.canonical_accounting_root_id<>original.root_id OR
    parent.generation<>spec.generation-1 OR parent.policy_id<>latest.policy_id OR parent.root_id<>latest.root_id OR
    parent.canonical_url_sha256<>grant_row.canonical_url_sha256 OR parent.request_hash<>latest.request_hash OR
    parent.supplemental_authorization_id<>latest.supplemental_authorization_id OR
    supplemental.course_refresh_authorization_id<>parent.id OR supplemental.dispatch_id<>latest.id OR
    supplemental.policy_id<>latest.policy_id OR supplemental.generation<>latest.generation OR
    supplemental.root_id<>latest.root_id OR supplemental.request_hash<>latest.request_hash OR
    supplemental.prior_attempt_id<>parent.latest_attempt_id OR
    latest.state<>'settled' OR latest.generation<>spec.generation-1 OR latest.settled_at IS NULL OR
    latest.canonical_url_sha256<>grant_row.canonical_url_sha256 OR capture.fetch_attempt_id<>latest.id OR
    capture.fetched_sha256<>latest.response_sha256 OR capture.captured_bytes<>latest.response_bytes OR
    (grant_row.id='2cbce7db-d8a6-5327-996c-4b8cc0917523'::uuid AND (grant_row.supplemental_authorization_id<>'dff82f6f-1dca-5a56-b71d-91a35609fc58'::uuid OR grant_row.dispatch_id<>'525e9269-9159-55db-aaf8-48880f598787'::uuid)) OR
    (grant_row.id='fd097ede-285d-5d68-9aae-3be0a2fbbd40'::uuid AND (grant_row.supplemental_authorization_id<>'c2134625-4eb2-51a5-80dc-b4b4395c2123'::uuid OR grant_row.dispatch_id<>'e4bb0fae-c77e-50be-b967-fae11bb027d5'::uuid)) OR
    (grant_row.id='618f9749-2130-50b7-8474-f5193ebb986c'::uuid AND (grant_row.supplemental_authorization_id<>'cef103ea-927b-56e3-ad6c-b4b3e558a194'::uuid OR grant_row.dispatch_id<>'3f6a0866-462f-568d-b1da-e9bc97c819e0'::uuid)) OR
    grant_row.lineage_snapshot IS DISTINCT FROM snapshot OR
    grant_row.lineage_sha256<>encode(digest(snapshot::text,'sha256'),'hex') OR
    jsonb_array_length(snapshot->'attempts')<>spec.carry OR
    (SELECT count(*) FROM jsonb_array_elements(snapshot->'attempts') a WHERE a->>'state'='unknown')<>spec.unknown OR
    EXISTS(SELECT 1 FROM public.rag_registered_course_refresh_authorizations r
       WHERE r.canonical_url_sha256=grant_row.canonical_url_sha256 AND r.id NOT IN (parent.id,grant_row.id)) OR
    EXISTS(SELECT 1 FROM public.rag_registered_supplemental_revocations v
       JOIN public.rag_registered_supplemental_authorizations a ON a.id=v.authorization_id
       WHERE a.canonical_url_sha256=grant_row.canonical_url_sha256) THEN
  RAISE check_violation USING MESSAGE='584 exact parent and complete lineage denied'; END IF;
 -- Remove ONLY the actual settled parent dispatch facts. Every older fact, including
 -- the unpriced UNKNOWN and all original periods/reservations, must equal frozen498.
 historical:=snapshot;
 FOREACH key IN ARRAY ARRAY['attempts','captures','policies','roots'] LOOP
  historical:=jsonb_set(historical,ARRAY[key],coalesce((SELECT jsonb_agg(x.value ORDER BY x.ordinality)
   FROM jsonb_array_elements(snapshot->key) WITH ORDINALITY x(value,ordinality)
   WHERE CASE key WHEN 'attempts' THEN x.value->>'id'<>latest.id::text
    WHEN 'captures' THEN x.value->>'fetch_attempt_id'<>latest.id::text
    WHEN 'policies' THEN x.value->>'policy_id'<>latest.policy_id
    ELSE x.value->>'root_id'<>latest.root_id END),'[]'::jsonb));
 END LOOP;
 IF historical IS DISTINCT FROM parent.lineage_snapshot OR
    parent.lineage_sha256<>encode(digest(parent.lineage_snapshot::text,'sha256'),'hex') OR
    EXISTS(SELECT 1 FROM public.rag_registered_fetch_attempts a
      JOIN public.rag_registered_source_policies p ON p.policy_id=a.policy_id
      JOIN public.rag_budget_authority_roots r ON r.root_id=a.root_id
      WHERE a.canonical_url_sha256=grant_row.canonical_url_sha256 AND
       (p.enabled IS NOT TRUE OR p.revoked_at IS NOT NULL OR p.immutable_history_allowed IS NOT TRUE OR
        p.expires_at>clock OR p.retention_until>clock OR r.enabled IS NOT TRUE OR
        r.delegation_expires_at>clock OR r.period_end>clock OR
        ROW(p.source_handle,p.subject_id,p.subject_version,p.facets,p.origin,p.reading_level,p.canonical_url,p.host,p.path,p.license_id,p.allowed_usages)
        IS DISTINCT FROM ROW(CASE WHEN spec.target='sqlite_select'
          AND a.id='8256098c-ddaa-4dd0-b387-0eea34b7596c'::uuid
          AND p.policy_id='source.p6.sqlite.assessment.20261002' AND p.generation=1
          THEN 'source.p6.sqlite.official'::text ELSE old_policy.source_handle END,
          'route.sql'::text,'1.0'::text,ARRAY['queries']::text[],
          'official'::text,'beginner'::text,spec.url,'www.sqlite.org'::text,old_policy.path,'sqlite-public-domain'::text,
          CASE WHEN spec.target='sqlite_select' THEN ARRAY['assessment_evidence']::text[] ELSE ARRAY['assessment_evidence','main_teaching']::text[] END) OR
        ROW(r.policy_id,r.policy_generation) IS DISTINCT FROM ROW(p.policy_id,p.generation) OR
        policy.max_captured_bytes>p.max_captured_bytes)) OR
    EXISTS(SELECT 1 FROM public.rag_registered_source_captures c JOIN public.rag_registered_fetch_attempts a ON a.id=c.fetch_attempt_id
      WHERE a.canonical_url_sha256=grant_row.canonical_url_sha256 AND
       (c.cleared_at IS NOT NULL OR c.captured_body IS NULL OR c.transport_proof IS NULL OR
        c.provider_attempt_id IS NOT NULL OR c.evidence_level<>'live_egress_attested' OR
        c.transport_proof_sha256 IS NULL OR c.attestor_key_sha256 IS NULL OR c.worker_image_sha256 IS NULL OR
        c.retention_until>clock OR c.fetched_sha256<>a.response_sha256 OR c.captured_bytes<>a.response_bytes OR
        encode(digest(c.captured_body,'sha256'),'hex')<>c.fetched_sha256 OR octet_length(c.captured_body)<>c.captured_bytes OR
        encode(digest(c.transport_proof,'sha256'),'hex')<>c.transport_proof_sha256)) THEN
  RAISE check_violation USING MESSAGE='584 immutable expired historical authority denied'; END IF;
 IF grant_row.issued_at>clock OR clock-grant_row.issued_at>interval '30 minutes' OR
    grant_row.source_expires_at IS DISTINCT FROM LEAST(grant_row.issued_at+interval '7 days',
      grant_row.source_permission_expires_at,grant_row.retention_permission_expires_at,'2026-10-26 23:59:59+08'::timestamptz) OR
    grant_row.source_expires_at<=clock OR
    grant_row.dispatch_expires_at IS DISTINCT FROM LEAST(grant_row.source_expires_at,grant_row.issued_at+interval '30 minutes') OR
    (dispatch_check AND grant_row.dispatch_expires_at<=clock) OR
    ROW(policy.source_handle,policy.subject_id,policy.subject_version,policy.facets,policy.origin,policy.reading_level,
      policy.canonical_url,policy.canonical_url_sha256,policy.host,policy.path,policy.license_id,policy.immutable_history_allowed)
    IS DISTINCT FROM ROW(old_policy.source_handle,old_policy.subject_id,old_policy.subject_version,old_policy.facets,
      old_policy.origin,old_policy.reading_level,old_policy.canonical_url,old_policy.canonical_url_sha256,old_policy.host,
      old_policy.path,old_policy.license_id,old_policy.immutable_history_allowed) OR
    policy.allowed_usages IS DISTINCT FROM ARRAY['assessment_evidence']::text[] OR
    policy.root_id<>root.root_id OR policy.generation<>spec.generation OR policy.enabled IS NOT TRUE OR policy.revoked_at IS NOT NULL OR
    policy.expires_at<>grant_row.source_expires_at OR policy.retention_until<>grant_row.source_expires_at OR
    root.enabled IS NOT TRUE OR root.policy_id<>policy.policy_id OR root.policy_generation<>policy.generation OR
    root.cap_units<>spec.carry+1 OR root.period_key<>'source-access-only.20261006' OR
    root.period_start<>grant_row.issued_at OR root.period_end<>grant_row.source_expires_at OR
    root.delegation_expires_at<>grant_row.source_expires_at OR root.delegation_generation<>1 OR
    root.delegation_id<>'delegation.course-refresh.'||replace(grant_row.id::text,'-','') OR
    EXISTS(SELECT 1 FROM public.rag_budget_periods WHERE root_id=root.root_id) OR
    EXISTS(SELECT 1 FROM public.rag_budget_reservations WHERE root_id=root.root_id) THEN
  RAISE check_violation USING MESSAGE='584 bounded assessment-only access denied'; END IF;
END $recovery584$;
REVOKE ALL ON FUNCTION public.rag_registered_m03_sqlite_recovery_check(public.rag_registered_course_refresh_authorizations,boolean) FROM PUBLIC;

DO $patch584$
DECLARE actual record; verified record; source text; definition text; before_attrs jsonb; default_at integer;
 replacement constant text:=$body584$
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
DECLARE successor boolean := grant_row.id='fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid;
DECLARE predecessor rag_registered_course_refresh_authorizations%ROWTYPE;
BEGIN
 IF grant_row.id IN ('2cbce7db-d8a6-5327-996c-4b8cc0917523'::uuid,'fd097ede-285d-5d68-9aae-3be0a2fbbd40'::uuid,'618f9749-2130-50b7-8474-f5193ebb986c'::uuid) THEN
  PERFORM public.rag_registered_m03_sqlite_recovery_check(grant_row,dispatch_check); RETURN;
 END IF;
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
 expected_count:=CASE WHEN successor THEN 2 WHEN grant_row.target_key='sqlite_select' THEN 3 ELSE 1 END;
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
        AND r.id<>grant_row.id
        AND NOT (successor AND r.id='46207149-ab55-5054-9821-da9059c0a77a'::uuid)) OR
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
 IF successor THEN
  SELECT * INTO predecessor FROM rag_registered_course_refresh_authorizations
   WHERE id='46207149-ab55-5054-9821-da9059c0a77a'::uuid FOR SHARE;
  SELECT * INTO latest_auth FROM rag_registered_supplemental_authorizations
   WHERE id=latest_row.supplemental_authorization_id FOR SHARE;
  IF grant_row.target_key<>'python_reference' OR
     grant_row.canonical_original_attempt_id<>'6b01e22b-856e-413b-b8d8-05a7f1dfc61f'::uuid OR
     grant_row.canonical_accounting_root_id<>'root.course.python_reference.20261003' OR
     grant_row.latest_attempt_id<>'ee050b7c-a7ec-583f-8b01-d2b0259f3510'::uuid OR
     grant_row.latest_capture_id<>'7fabac26-245d-48d3-8d0e-8a176cbf4a86'::uuid OR
     grant_row.policy_id<>'source.course-refresh.20261013.python_reference' OR grant_row.generation<>3 OR
     grant_row.supplemental_authorization_id<>'f0662a63-3a94-55a6-ac82-139be4a0ed29'::uuid OR
     grant_row.dispatch_id<>'942b3631-a026-5c77-bc75-bae62dbf3e4a'::uuid OR
     grant_row.operation_key<>'course.refresh.20261006.fbfabcf0f3365b1298248b0b2782b69c' OR
     predecessor.id IS NULL OR latest_auth.id IS NULL OR
     latest_auth.id<>'26b2b080-1aa2-5fdd-a530-6fcbc5cb89e8'::uuid OR
     ROW(predecessor.canonical_original_attempt_id,predecessor.canonical_accounting_root_id,
         predecessor.canonical_url_sha256,predecessor.latest_attempt_id,predecessor.dispatch_id,
         predecessor.policy_id,predecessor.generation,predecessor.root_id,predecessor.supplemental_authorization_id)
       IS DISTINCT FROM ROW(original_row.id,original_row.root_id,grant_row.canonical_url_sha256,original_row.id,
         latest_row.id,latest_row.policy_id,2,latest_row.root_id,latest_auth.id) OR
     ROW(latest_auth.course_refresh_authorization_id,latest_auth.dispatch_id,latest_auth.prior_attempt_id,
         latest_auth.policy_id,latest_auth.generation,latest_auth.root_id,latest_auth.request_hash)
       IS DISTINCT FROM ROW(predecessor.id,latest_row.id,original_row.id,latest_row.policy_id,2,
         latest_row.root_id,latest_row.request_hash) OR
     latest_auth.explicit_followup_id IS NOT NULL OR latest_auth.replaces_authorization_id IS NOT NULL OR
     latest_row.generation<>2 OR latest_row.dispatched_at<original_row.settled_at OR
     latest_policy.source_handle<>'source.course.python_reference' OR
     jsonb_array_length(snapshot->'captures')<>2 OR jsonb_array_length(snapshot->'authorizations')<>0 OR
     jsonb_array_length(snapshot->'allowances')<>0 OR jsonb_array_length(snapshot->'revocations')<>0 OR
     EXISTS(SELECT 1 FROM rag_registered_supplemental_revocations WHERE authorization_id=latest_auth.id) THEN
   RAISE EXCEPTION '544 exact python reference successor lineage denied' USING ERRCODE='23514';
  END IF;
 ELSIF expected_count=1 THEN
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
    grant_row.root_id<>(CASE WHEN successor THEN 'root.course-refresh.20261006.python_reference.successor.20261013'
      ELSE 'root.course-refresh.20261006.'||grant_row.target_key END) OR
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
END $body584$;
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=5349838 AND p.oid=to_regprocedure('public.rag_registered_course_refresh_check(rag_registered_course_refresh_authorizations,boolean)');
 IF NOT FOUND OR actual.prosecdef IS DISTINCT FROM false OR
    actual.provolatile<>'v' OR actual.proacl IS NOT NULL OR
    pg_get_userbyid(actual.proowner)<>'aearn_b1d_runtime_20261001' OR
    to_jsonb(actual.proconfig) IS DISTINCT FROM '["TimeZone=UTC"]'::jsonb THEN
  RAISE check_violation USING MESSAGE='584 exact S0 function attributes required'; END IF;
 source:=actual.prosrc; before_attrs:=to_jsonb(actual)-'prosrc';
 IF encode(sha256(convert_to(source,'UTF8')),'hex')='24cc3acbfd461971803af8bc764dc9593b6ad37a88153074708b9d1b1f10109a' THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')<>'ba17bd890627d091faacae9cbcfe98d8cceac5cb7a4cc091a93982293cc2288a' THEN
  RAISE check_violation USING MESSAGE='584 exact S0 original body required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source) THEN
  RAISE check_violation USING MESSAGE='584 exact S0 framing required'; END IF;
 definition:=replace(definition,source,replacement);
 default_at:=strpos(definition,'DEFAULT false')-1+length('DEFAULT ');
 IF default_at<length('DEFAULT ') OR default_at>6433 THEN RAISE check_violation USING MESSAGE='584 default framing'; END IF;
 definition:=replace(definition,'DEFAULT false','DEFAULT '||repeat(' ',6433-default_at)||'false');
 EXECUTE definition;
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF (to_jsonb(verified)-'prosrc') IS DISTINCT FROM before_attrs OR
    encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex')<>'24cc3acbfd461971803af8bc764dc9593b6ad37a88153074708b9d1b1f10109a' THEN
  RAISE check_violation USING MESSAGE='584 replaced function metadata changed'; END IF;
END $patch584$;

DO $patch584$
DECLARE actual record; verified record; source text; definition text; before_attrs jsonb; default_at integer;
 replacement constant text:=$body584$
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
      grant_row.latest_attempt_id,grant_row.dispatch_expires_at,(CASE WHEN grant_row.id IN ('2cbce7db-d8a6-5327-996c-4b8cc0917523'::uuid,'fd097ede-285d-5d68-9aae-3be0a2fbbd40'::uuid,'618f9749-2130-50b7-8474-f5193ebb986c'::uuid) THEN 'standingpolicy.m03-sqlite-source-recovery.20261019'::text ELSE 'standingpolicy.course-refresh.20261006'::text END)) THEN
  RAISE EXCEPTION 'course refresh supplemental binding denied' USING ERRCODE='23514';
 END IF;
 PERFORM rag_registered_course_refresh_check(grant_row,true);
 RETURN NEW;
END $body584$;
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=5349842 AND p.oid=to_regprocedure('public.rag_registered_course_refresh_auth_guard()');
 IF NOT FOUND OR actual.prosecdef IS DISTINCT FROM false OR
    actual.provolatile<>'v' OR actual.proacl IS NOT NULL OR
    pg_get_userbyid(actual.proowner)<>'aearn_b1d_runtime_20261001' OR
    coalesce(to_jsonb(actual.proconfig),'null'::jsonb) IS DISTINCT FROM 'null'::jsonb THEN
  RAISE check_violation USING MESSAGE='584 exact S0 function attributes required'; END IF;
 source:=actual.prosrc; before_attrs:=to_jsonb(actual)-'prosrc';
 IF encode(sha256(convert_to(source,'UTF8')),'hex')='5652906306eb9343e7a287371f599d3957f24777be00eca7300ca7f661858a13' THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')<>'cfb37a2d532e93ab99f323dd4f7b1d2214ce28fdc109b78a5f7dd17a40871994' THEN
  RAISE check_violation USING MESSAGE='584 exact S0 original body required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source) THEN
  RAISE check_violation USING MESSAGE='584 exact S0 framing required'; END IF;
 definition:=replace(definition,source,replacement);
 EXECUTE definition;
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF (to_jsonb(verified)-'prosrc') IS DISTINCT FROM before_attrs OR
    encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex')<>'5652906306eb9343e7a287371f599d3957f24777be00eca7300ca7f661858a13' THEN
  RAISE check_violation USING MESSAGE='584 replaced function metadata changed'; END IF;
END $patch584$;

DO $check584$
DECLARE expected text; actual text;
BEGIN
 ALTER TABLE public.rag_registered_course_refresh_authorizations ADD CONSTRAINT m03_584_expected CHECK ((((carried_dispatch_units = ANY (ARRAY[1, 3])) OR ((id = 'fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid) AND (target_key = 'python_reference'::text) AND (carried_dispatch_units = 2))) OR (id='2cbce7db-d8a6-5327-996c-4b8cc0917523'::uuid AND target_key='sqlite_select'::text AND carried_dispatch_units=4) OR (id='fd097ede-285d-5d68-9aae-3be0a2fbbd40'::uuid AND target_key='sqlite_expression'::text AND carried_dispatch_units=2) OR (id='618f9749-2130-50b7-8474-f5193ebb986c'::uuid AND target_key='sqlite_functions'::text AND carried_dispatch_units=2)));
 SELECT pg_get_constraintdef(oid) INTO expected FROM pg_constraint
  WHERE conrelid='public.rag_registered_course_refresh_authorizations'::regclass AND conname='m03_584_expected';
 SELECT pg_get_constraintdef(oid) INTO actual FROM pg_constraint
  WHERE conrelid='public.rag_registered_course_refresh_authorizations'::regclass AND conname='rag_registered_course_refresh_auth_carried_dispatch_units_check' AND convalidated;
 IF actual IS NOT DISTINCT FROM $expected584$CHECK (((carried_dispatch_units = ANY (ARRAY[1, 3])) OR ((id = 'fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid) AND (target_key = 'python_reference'::text) AND (carried_dispatch_units = 2))))$expected584$ THEN
  ALTER TABLE public.rag_registered_course_refresh_authorizations DROP CONSTRAINT rag_registered_course_refresh_auth_carried_dispatch_units_check;
  ALTER TABLE public.rag_registered_course_refresh_authorizations RENAME CONSTRAINT m03_584_expected TO rag_registered_course_refresh_auth_carried_dispatch_units_check;
 ELSIF actual IS NOT DISTINCT FROM expected THEN
  ALTER TABLE public.rag_registered_course_refresh_authorizations DROP CONSTRAINT m03_584_expected;
 ELSE RAISE check_violation USING MESSAGE='584 exact CHECK precondition required'; END IF;
END $check584$;
DO $check584$
DECLARE expected text; actual text;
BEGIN
 ALTER TABLE public.rag_registered_course_refresh_authorizations ADD CONSTRAINT m03_584_expected CHECK ((((root_id = ('root.course-refresh.20261006.'::text || target_key)) OR ((id = 'fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid) AND (target_key = 'python_reference'::text) AND (root_id = 'root.course-refresh.20261006.python_reference.successor.20261013'::text))) OR (id='2cbce7db-d8a6-5327-996c-4b8cc0917523'::uuid AND target_key='sqlite_select'::text AND root_id='root.course-refresh.20261006.sqlite_select.m03.20261019'::text) OR (id='fd097ede-285d-5d68-9aae-3be0a2fbbd40'::uuid AND target_key='sqlite_expression'::text AND root_id='root.course-refresh.20261006.sqlite_expression.m03.20261019'::text) OR (id='618f9749-2130-50b7-8474-f5193ebb986c'::uuid AND target_key='sqlite_functions'::text AND root_id='root.course-refresh.20261006.sqlite_functions.m03.20261019'::text)));
 SELECT pg_get_constraintdef(oid) INTO expected FROM pg_constraint
  WHERE conrelid='public.rag_registered_course_refresh_authorizations'::regclass AND conname='m03_584_expected';
 SELECT pg_get_constraintdef(oid) INTO actual FROM pg_constraint
  WHERE conrelid='public.rag_registered_course_refresh_authorizations'::regclass AND conname='rag_registered_course_refresh_authorizations_check3' AND convalidated;
 IF actual IS NOT DISTINCT FROM $expected584$CHECK (((root_id = ('root.course-refresh.20261006.'::text || target_key)) OR ((id = 'fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid) AND (target_key = 'python_reference'::text) AND (root_id = 'root.course-refresh.20261006.python_reference.successor.20261013'::text))))$expected584$ THEN
  ALTER TABLE public.rag_registered_course_refresh_authorizations DROP CONSTRAINT rag_registered_course_refresh_authorizations_check3;
  ALTER TABLE public.rag_registered_course_refresh_authorizations RENAME CONSTRAINT m03_584_expected TO rag_registered_course_refresh_authorizations_check3;
 ELSIF actual IS NOT DISTINCT FROM expected THEN
  ALTER TABLE public.rag_registered_course_refresh_authorizations DROP CONSTRAINT m03_584_expected;
 ELSE RAISE check_violation USING MESSAGE='584 exact CHECK precondition required'; END IF;
END $check584$;
DO $check584$
DECLARE expected text; actual text;
BEGIN
 ALTER TABLE public.rag_registered_course_refresh_authorizations ADD CONSTRAINT m03_584_expected CHECK ((((generation = ANY (ARRAY[2, 4])) OR ((id = 'fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid) AND (target_key = 'python_reference'::text) AND (generation = 3))) OR (id='2cbce7db-d8a6-5327-996c-4b8cc0917523'::uuid AND target_key='sqlite_select'::text AND generation=5) OR (id='fd097ede-285d-5d68-9aae-3be0a2fbbd40'::uuid AND target_key='sqlite_expression'::text AND generation=3) OR (id='618f9749-2130-50b7-8474-f5193ebb986c'::uuid AND target_key='sqlite_functions'::text AND generation=3)));
 SELECT pg_get_constraintdef(oid) INTO expected FROM pg_constraint
  WHERE conrelid='public.rag_registered_course_refresh_authorizations'::regclass AND conname='m03_584_expected';
 SELECT pg_get_constraintdef(oid) INTO actual FROM pg_constraint
  WHERE conrelid='public.rag_registered_course_refresh_authorizations'::regclass AND conname='rag_registered_course_refresh_authorizations_generation_check' AND convalidated;
 IF actual IS NOT DISTINCT FROM $expected584$CHECK (((generation = ANY (ARRAY[2, 4])) OR ((id = 'fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid) AND (target_key = 'python_reference'::text) AND (generation = 3))))$expected584$ THEN
  ALTER TABLE public.rag_registered_course_refresh_authorizations DROP CONSTRAINT rag_registered_course_refresh_authorizations_generation_check;
  ALTER TABLE public.rag_registered_course_refresh_authorizations RENAME CONSTRAINT m03_584_expected TO rag_registered_course_refresh_authorizations_generation_check;
 ELSIF actual IS NOT DISTINCT FROM expected THEN
  ALTER TABLE public.rag_registered_course_refresh_authorizations DROP CONSTRAINT m03_584_expected;
 ELSE RAISE check_violation USING MESSAGE='584 exact CHECK precondition required'; END IF;
END $check584$;
DO $index584$
DECLARE actual record; expected record;
BEGIN
 CREATE UNIQUE INDEX m03_584_expected ON public.rag_registered_course_refresh_authorizations (authorization_id, canonical_original_attempt_id) WHERE (id <> ALL (ARRAY['fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid,'2cbce7db-d8a6-5327-996c-4b8cc0917523'::uuid,'fd097ede-285d-5d68-9aae-3be0a2fbbd40'::uuid,'618f9749-2130-50b7-8474-f5193ebb986c'::uuid]));
 SELECT * INTO actual FROM pg_index WHERE indexrelid=to_regclass('public.uq_rag_course_refresh_544_original');
 SELECT * INTO expected FROM pg_index WHERE indexrelid='public.m03_584_expected'::regclass;
 IF actual.indexrelid IS NULL OR NOT actual.indisunique OR NOT actual.indisvalid OR NOT actual.indisready OR
   actual.indrelid<>expected.indrelid OR actual.indnkeyatts<>expected.indnkeyatts OR actual.indnatts<>expected.indnatts OR
   actual.indkey<>expected.indkey OR actual.indcollation<>expected.indcollation OR actual.indclass<>expected.indclass OR
   actual.indoption<>expected.indoption OR actual.indexprs::text IS DISTINCT FROM expected.indexprs::text OR
   (pg_get_indexdef(actual.indexrelid) IS DISTINCT FROM $oldindex584$CREATE UNIQUE INDEX uq_rag_course_refresh_544_original ON public.rag_registered_course_refresh_authorizations USING btree (authorization_id, canonical_original_attempt_id) WHERE (id <> 'fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid)$oldindex584$ AND
    pg_get_expr(actual.indpred,actual.indrelid) IS DISTINCT FROM pg_get_expr(expected.indpred,expected.indrelid)) THEN
  RAISE check_violation USING MESSAGE='584 exact old once index required'; END IF;
 DROP INDEX public.uq_rag_course_refresh_544_original;
 ALTER INDEX public.m03_584_expected RENAME TO uq_rag_course_refresh_544_original;
END $index584$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_course_refresh_584_original ON public.rag_registered_course_refresh_authorizations (authorization_id, canonical_original_attempt_id) WHERE (id IN ('2cbce7db-d8a6-5327-996c-4b8cc0917523'::uuid,'fd097ede-285d-5d68-9aae-3be0a2fbbd40'::uuid,'618f9749-2130-50b7-8474-f5193ebb986c'::uuid));
DO $index584$
DECLARE actual record; expected record;
BEGIN
 CREATE UNIQUE INDEX m03_584_expected ON public.rag_registered_course_refresh_authorizations (authorization_id, canonical_url_sha256) WHERE (id <> ALL (ARRAY['fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid,'2cbce7db-d8a6-5327-996c-4b8cc0917523'::uuid,'fd097ede-285d-5d68-9aae-3be0a2fbbd40'::uuid,'618f9749-2130-50b7-8474-f5193ebb986c'::uuid]));
 SELECT * INTO actual FROM pg_index WHERE indexrelid=to_regclass('public.uq_rag_course_refresh_544_url');
 SELECT * INTO expected FROM pg_index WHERE indexrelid='public.m03_584_expected'::regclass;
 IF actual.indexrelid IS NULL OR NOT actual.indisunique OR NOT actual.indisvalid OR NOT actual.indisready OR
   actual.indrelid<>expected.indrelid OR actual.indnkeyatts<>expected.indnkeyatts OR actual.indnatts<>expected.indnatts OR
   actual.indkey<>expected.indkey OR actual.indcollation<>expected.indcollation OR actual.indclass<>expected.indclass OR
   actual.indoption<>expected.indoption OR actual.indexprs::text IS DISTINCT FROM expected.indexprs::text OR
   (pg_get_indexdef(actual.indexrelid) IS DISTINCT FROM $oldindex584$CREATE UNIQUE INDEX uq_rag_course_refresh_544_url ON public.rag_registered_course_refresh_authorizations USING btree (authorization_id, canonical_url_sha256) WHERE (id <> 'fbfabcf0-f336-5b12-9824-8b0b2782b69c'::uuid)$oldindex584$ AND
    pg_get_expr(actual.indpred,actual.indrelid) IS DISTINCT FROM pg_get_expr(expected.indpred,expected.indrelid)) THEN
  RAISE check_violation USING MESSAGE='584 exact old once index required'; END IF;
 DROP INDEX public.uq_rag_course_refresh_544_url;
 ALTER INDEX public.m03_584_expected RENAME TO uq_rag_course_refresh_544_url;
END $index584$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_course_refresh_584_url ON public.rag_registered_course_refresh_authorizations (authorization_id, canonical_url_sha256) WHERE (id IN ('2cbce7db-d8a6-5327-996c-4b8cc0917523'::uuid,'fd097ede-285d-5d68-9aae-3be0a2fbbd40'::uuid,'618f9749-2130-50b7-8474-f5193ebb986c'::uuid));

-- Explicit, no-caller, default-off P1-only receiver. This is a DB current-facts
-- fence, not a replacement for original Python signature/provenance owners.
CREATE OR REPLACE FUNCTION public.native_consumer_m03_p1_source_current(
 p_proof uuid, p_materialization uuid, p_current_materials jsonb, p_enabled boolean DEFAULT false
) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $p1current584$
DECLARE
 frozen public.tutor_learning_item_native_publication_proofs%ROWTYPE;
 old_material jsonb; material jsonb; old_e jsonb; e jsonb; b jsonb; claim jsonb; old_claim jsonb;
 old_source public.rag_assessment_source_evidence%ROWTYPE;
 new_source public.rag_assessment_source_evidence%ROWTYPE;
 old_prepared jsonb; new_prepared jsonb; old_coordinate jsonb; coordinate jsonb;
 old_capture public.rag_registered_source_captures%ROWTYPE;
 new_capture public.rag_registered_source_captures%ROWTYPE;
 grant_row public.rag_registered_course_refresh_authorizations%ROWTYPE;
 current_policy public.rag_registered_source_policies%ROWTYPE; old_policy public.rag_registered_source_policies%ROWTYPE;
 current_root public.rag_budget_authority_roots%ROWTYPE;
 role_name text; target_name text; aid uuid; r record; i integer; j integer; k integer;
 t timestamptz; deadline timestamptz:='infinity'::timestamptz;
 source_id uuid; corpus_id uuid; active_gen bigint; all_chunks integer;
BEGIN
 IF p_enabled IS DISTINCT FROM true OR current_database()<>'aearn_b1d_sandbox_20261001' OR
    current_setting('transaction_isolation')<>'read committed' OR
    p_proof IS DISTINCT FROM '7fd1e0ae-3634-51b5-a0cb-706ffa83c82d'::uuid OR
    p_materialization IS DISTINCT FROM 'b2eacc91-4e50-5635-90b4-7dcb1bfa4fe3'::uuid OR
    jsonb_typeof(p_current_materials) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 PERFORM txid_current(); -- caller's current TOP; no autonomous transaction/cache.
 SELECT * INTO frozen FROM public.tutor_learning_item_native_publication_proofs
  WHERE id=p_proof AND materialization_id=p_materialization
   AND version_id='1fe141fb-66f8-5b42-8258-116a1c5d04d0'::uuid
   AND publication_event_id='faffac6b-8431-5fa7-9de9-0b8e4a6bbd2e'::uuid FOR SHARE;
 IF NOT FOUND OR jsonb_typeof(frozen.proof_json->'materials') IS DISTINCT FROM 'array' OR
    jsonb_array_length(frozen.proof_json->'materials') NOT BETWEEN 1 AND 12 OR
    jsonb_array_length(p_current_materials)<>jsonb_array_length(frozen.proof_json->'materials') THEN RETURN false; END IF;
 -- Do not reinterpret historical publication/quality or update its proof/deadline.
 FOR i IN 0..jsonb_array_length(p_current_materials)-1 LOOP
  material:=p_current_materials->i; old_material:=frozen.proof_json->'materials'->i;
  IF material->>'classification' IS DISTINCT FROM 'approved_public' OR
     (material-'binding'-'access_request'-'exact_claims') IS DISTINCT FROM
       (old_material-'binding'-'access_request'-'exact_claims') OR
     ((material->'binding')-'evidence'-'binding_digest') IS DISTINCT FROM
       ((old_material->'binding')-'evidence'-'binding_digest') OR
     ((material->'access_request')-'policy_id'-'policy_generation'-'budget') IS DISTINCT FROM
       ((old_material->'access_request')-'policy_id'-'policy_generation'-'budget') OR
     material->'binding'->>'purpose' IS DISTINCT FROM 'assessment_evidence' OR
     jsonb_typeof(material->'binding'->'evidence') IS DISTINCT FROM 'array' OR
     jsonb_array_length(material->'binding'->'evidence') NOT BETWEEN 1 AND 12 OR
     jsonb_array_length(material->'binding'->'evidence')<>jsonb_array_length(old_material->'binding'->'evidence') OR
     jsonb_typeof(material->'exact_claims') IS DISTINCT FROM 'array' OR
     jsonb_array_length(material->'exact_claims')<>jsonb_array_length(old_material->'exact_claims') OR
     jsonb_array_length(material->'exact_claims')<>1 THEN RETURN false; END IF;
  FOR j IN 0..jsonb_array_length(material->'binding'->'evidence')-1 LOOP
   e:=material->'binding'->'evidence'->j; old_e:=old_material->'binding'->'evidence'->j; b:=e->'binding';
   IF (b-'document_handle'-'admission_receipt_id'-'claim_receipt_id') IS DISTINCT FROM
      ((old_e->'binding')-'document_handle'-'admission_receipt_id'-'claim_receipt_id') OR
      (e-ARRAY['binding','corpus_version_id','active_generation','summary_hash','validation_hash','registry_digest','source_review_id','source_policy_id','source_policy_generation','chunk_id','retrieval_hash','coverage_hash','claim_id','claim_receipt_hash','execution_receipt_id']::text[]) IS DISTINCT FROM (old_e-ARRAY['binding','corpus_version_id','active_generation','summary_hash','validation_hash','registry_digest','source_review_id','source_policy_id','source_policy_generation','chunk_id','retrieval_hash','coverage_hash','claim_id','claim_receipt_hash','execution_receipt_id']::text[]) OR
      e->>'subject_id' IS DISTINCT FROM old_e->>'subject_id' OR
      e->>'chunk_hash' IS DISTINCT FROM old_e->>'chunk_hash' OR
      e->>'approved_excerpt_hash' IS DISTINCT FROM old_e->>'approved_excerpt_hash' OR
      b->>'purpose' IS DISTINCT FROM 'assessment_evidence' OR
      e->>'chunk_hash' IS DISTINCT FROM encode(digest(material->>'excerpt','sha256'),'hex') THEN RETURN false; END IF;
   SELECT se.* INTO old_source FROM public.rag_assessment_source_evidence se
    JOIN public.rag_source_reviews rv ON rv.assessment_evidence_id=se.id
    JOIN public.rag_source_admissions ad ON ad.review_id=rv.id
    WHERE rv.id=(old_e->>'source_review_id')::uuid AND
      ad.receipt_handle=old_e->'binding'->>'admission_receipt_id'
      AND rv.document_hash=old_e->'binding'->>'document_hash'
      AND se.document_hash=rv.document_hash AND se.revoked_at IS NULL
      AND ad.revoked_at IS NULL AND ad.active AND rv.status='reviewed'
      AND se.issued_at<=(frozen.proof_json->>'checked_at')::timestamptz
      AND se.expires_at>(frozen.proof_json->>'checked_at')::timestamptz FOR SHARE OF se,rv,ad;
   IF NOT FOUND THEN RETURN false; END IF;
   SELECT se.* INTO new_source FROM public.rag_assessment_source_evidence se
    JOIN public.rag_source_reviews rv ON rv.assessment_evidence_id=se.id
    JOIN public.rag_source_admissions ad ON ad.review_id=rv.id
    WHERE rv.id=(e->>'source_review_id')::uuid AND ad.receipt_handle=b->>'admission_receipt_id'
      AND se.document_handle=b->>'document_handle' AND se.document_hash=b->>'document_hash'
      AND se.capture_id=rv.registered_capture_id AND se.policy_id=rv.policy_id
      AND se.policy_generation=rv.policy_generation AND se.source_handle=rv.source_handle
      AND se.document_hash=rv.document_hash AND se.root_id=rv.root_id
      AND ad.active AND ad.revoked_at IS NULL AND se.revoked_at IS NULL FOR SHARE OF se,rv,ad;
   IF NOT FOUND THEN RETURN false; END IF;
   IF source_id IS NOT NULL AND (source_id<>new_source.id OR corpus_id<>(e->>'corpus_version_id')::uuid OR
       active_gen<>(e->>'active_generation')::bigint) THEN RETURN false; END IF;
   source_id:=new_source.id; corpus_id:=(e->>'corpus_version_id')::uuid; active_gen:=(e->>'active_generation')::bigint;
   old_prepared:=old_source.signed_proof->'payload'->'prepared';
   new_prepared:=new_source.signed_proof->'payload'->'prepared';
   IF old_prepared->>'profile_id' IS DISTINCT FROM 'sqlite-predicate-source-v1' OR
      new_prepared->>'profile_id' IS DISTINCT FROM old_prepared->>'profile_id' OR
      old_prepared->'demand' IS DISTINCT FROM new_prepared->'demand' OR
      old_prepared->'spans' IS DISTINCT FROM new_prepared->'spans' OR
      jsonb_array_length(new_prepared->'spans')<>5 OR
      jsonb_typeof(new_prepared->'companions') IS DISTINCT FROM 'array' OR
      jsonb_array_length(new_prepared->'companions')<>2 OR
      old_prepared->>'document_hash' IS DISTINCT FROM new_prepared->>'document_hash' OR
      old_prepared->>'license_id' IS DISTINCT FROM new_prepared->>'license_id' OR
      old_prepared->>'origin' IS DISTINCT FROM new_prepared->>'origin' OR
      old_prepared->>'reading_level' IS DISTINCT FROM new_prepared->>'reading_level' OR
      new_source.signed_proof->'payload'->>'evidence_id' IS DISTINCT FROM new_source.id::text OR
      new_source.document_hash IS DISTINCT FROM new_prepared->>'document_hash' OR
      new_source.capture_id IS DISTINCT FROM (new_prepared->>'capture_id')::uuid OR
      new_source.issued_at>clock_timestamp() OR new_source.expires_at<=clock_timestamp() THEN RETURN false; END IF;
   -- All three fresh captures, not a select-only receipt. Complete document bytes
   -- and exact spans stay equal; handles/claim hashes are independently new.
   FOR k IN 0..2 LOOP
    role_name:=CASE k WHEN 0 THEN 'select' WHEN 1 THEN 'expression' ELSE 'corefunc' END;
    target_name:=CASE k WHEN 0 THEN 'sqlite_select' WHEN 1 THEN 'sqlite_expression' ELSE 'sqlite_functions' END;
    aid:=CASE k WHEN 0 THEN '2cbce7db-d8a6-5327-996c-4b8cc0917523'::uuid
      WHEN 1 THEN 'fd097ede-285d-5d68-9aae-3be0a2fbbd40'::uuid ELSE '618f9749-2130-50b7-8474-f5193ebb986c'::uuid END;
    old_coordinate:=CASE WHEN k=0 THEN old_prepared ELSE old_prepared->'companions'->(k-1) END;
    coordinate:=CASE WHEN k=0 THEN new_prepared ELSE new_prepared->'companions'->(k-1) END;
    IF (k>0 AND (coordinate->>'role' IS DISTINCT FROM role_name OR old_coordinate->>'role' IS DISTINCT FROM role_name)) OR
       coordinate->>'source_handle' IS DISTINCT FROM old_coordinate->>'source_handle' OR
       coordinate->>'document_hash' IS DISTINCT FROM old_coordinate->>'document_hash' OR
       coordinate->>'license_id' IS DISTINCT FROM old_coordinate->>'license_id' OR
       coordinate->>'reading_level' IS DISTINCT FROM old_coordinate->>'reading_level' OR
       coordinate->'spans' IS DISTINCT FROM old_coordinate->'spans' OR
       jsonb_array_length(coordinate->'spans')<>(CASE k WHEN 0 THEN 5 WHEN 1 THEN 4 ELSE 1 END) THEN RETURN false; END IF;
    SELECT * INTO old_capture FROM public.rag_registered_source_captures WHERE id=(old_coordinate->>'capture_id')::uuid FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO old_policy FROM public.rag_registered_source_policies WHERE policy_id=old_capture.policy_id FOR SHARE;
    IF NOT FOUND OR old_policy.enabled IS DISTINCT FROM true OR old_policy.revoked_at IS NOT NULL OR
       old_policy.immutable_history_allowed IS DISTINCT FROM true OR old_capture.cleared_at IS NOT NULL OR
       old_capture.captured_body IS NULL OR old_capture.transport_proof IS NULL THEN RETURN false; END IF;
    SELECT * INTO grant_row FROM public.rag_registered_course_refresh_authorizations WHERE id=aid AND target_key=target_name FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT c.* INTO new_capture FROM public.rag_registered_source_captures c
     JOIN public.rag_registered_fetch_attempts a ON a.id=c.fetch_attempt_id
     WHERE c.id=(coordinate->>'capture_id')::uuid AND a.id=grant_row.dispatch_id AND a.state='settled'
       AND a.supplemental_authorization_id=grant_row.supplemental_authorization_id
       AND a.policy_id=grant_row.policy_id AND a.generation=grant_row.generation AND a.root_id=grant_row.root_id
       AND a.request_hash=grant_row.request_hash AND a.response_sha256=c.fetched_sha256 AND a.response_bytes=c.captured_bytes
       AND c.policy_id=grant_row.policy_id AND c.generation=grant_row.generation FOR SHARE OF c,a;
    IF NOT FOUND OR new_capture.fetched_sha256 IS DISTINCT FROM old_capture.fetched_sha256 OR
       new_capture.captured_body IS DISTINCT FROM old_capture.captured_body OR
       new_capture.fetched_sha256 IS DISTINCT FROM coordinate->>'document_hash' OR
       new_capture.cleared_at IS NOT NULL OR new_capture.captured_body IS NULL OR new_capture.transport_proof IS NULL OR
       new_capture.evidence_level<>'live_egress_attested' OR new_capture.attestor_key_sha256 IS NULL OR
       new_capture.worker_image_sha256 IS NULL OR new_capture.provider_attempt_id IS NOT NULL OR
       encode(digest(new_capture.captured_body,'sha256'),'hex')<>new_capture.fetched_sha256 OR
       encode(digest(new_capture.transport_proof,'sha256'),'hex') IS DISTINCT FROM new_capture.transport_proof_sha256 OR
       (SELECT count(*) FROM public.rag_registered_fetch_attempts WHERE canonical_url_sha256=grant_row.canonical_url_sha256)
         <>grant_row.cumulative_dispatch_ceiling THEN RETURN false; END IF;
    SELECT * INTO current_policy FROM public.rag_registered_source_policies WHERE policy_id=grant_row.policy_id FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO current_root FROM public.rag_budget_authority_roots WHERE root_id=grant_row.root_id FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    t:=clock_timestamp();
    deadline:=LEAST(deadline,new_source.expires_at,grant_row.source_expires_at,current_policy.expires_at,current_policy.retention_until,
      new_capture.retention_until,current_root.period_end,current_root.delegation_expires_at,(coordinate->>'authority_expires_at')::timestamptz);
    IF current_policy.enabled IS DISTINCT FROM true OR current_policy.revoked_at IS NOT NULL OR
       current_policy.allowed_usages IS DISTINCT FROM ARRAY['assessment_evidence']::text[] OR
       current_policy.immutable_history_allowed IS DISTINCT FROM true OR current_policy.root_id<>current_root.root_id OR
       current_policy.generation<>grant_row.generation OR current_policy.generation<>(coordinate->>'policy_generation')::integer OR
       current_policy.policy_id IS DISTINCT FROM coordinate->>'policy_id' OR current_root.enabled IS DISTINCT FROM true OR
       current_root.policy_id<>current_policy.policy_id OR current_root.policy_generation<>current_policy.generation OR current_root.period_start>t OR
       new_capture.retention_until<=t OR deadline<=t OR
       ROW(current_policy.canonical_url,current_policy.subject_id,current_policy.subject_version,current_policy.facets,current_policy.origin,current_policy.license_id,current_policy.reading_level)
        IS DISTINCT FROM ROW(old_policy.canonical_url,old_policy.subject_id,old_policy.subject_version,old_policy.facets,
          old_policy.origin,old_policy.license_id,old_policy.reading_level) THEN RETURN false; END IF;
   END LOOP;
     PERFORM 1 FROM grounding_active_corpora a JOIN grounding_corpus_versions c ON c.id=a.corpus_version_id
       WHERE a.subject_id=e->>'subject_id' AND a.corpus_version_id=(e->>'corpus_version_id')::uuid
         AND a.generation=(e->>'active_generation')::integer AND c.summary_hash=e->>'summary_hash'
         AND c.state='published' FOR SHARE OF a,c;
     IF NOT FOUND THEN RETURN false; END IF;
     SELECT review.*, policy.enabled AS policy_enabled,policy.revoked_at AS policy_revoked,
       policy.generation AS current_generation,policy.allowed_usages AS policy_usages,
       policy.retention_until AS policy_retention,policy.expires_at AS policy_expires,
       capture.retention_until AS capture_retention,capture.cleared_at,
       (capture.captured_body IS NOT NULL) AS capture_body_available,
       capture.fetched_sha256,capture.generation AS capture_generation,
       admission.active AS admission_active,admission.revoked_at AS admission_revoked,
       admission.policy_generation AS admission_generation,admission.allowed_usages AS admission_usages,
       root.enabled AS root_enabled,root.period_start,root.period_end,root.delegation_expires_at,
       root.policy_id AS root_policy,root.policy_generation AS root_generation,
       evidence.expires_at AS evidence_expires,evidence.revoked_at AS evidence_revoked
       INTO r FROM rag_source_reviews review
       JOIN rag_registered_source_policies policy ON policy.policy_id=review.policy_id AND policy.source_handle=review.source_handle
       JOIN rag_registered_source_captures capture ON capture.id=review.registered_capture_id AND capture.policy_id=policy.policy_id
       JOIN rag_source_admissions admission ON admission.review_id=review.id
       JOIN rag_budget_authority_roots root ON root.root_id=review.root_id AND root.root_id=policy.root_id
       LEFT JOIN rag_assessment_source_evidence evidence ON evidence.id=review.assessment_evidence_id
       WHERE review.id=(e->>'source_review_id')::uuid AND review.source_handle=b->>'source_handle'
         AND review.document_handle=b->>'document_handle' AND review.document_hash=b->>'document_hash'
         AND review.policy_id=e->>'source_policy_id' AND review.policy_generation=(e->>'source_policy_generation')::integer
         AND admission.receipt_handle=b->>'admission_receipt_id'
       FOR SHARE OF review,policy,capture,admission,root;
     IF NOT FOUND THEN RETURN false; END IF;
     -- Clock follows every possible lock wait; no entry-time deadline authority.
     t:=clock_timestamp();
     deadline:=LEAST(deadline,r.policy_retention,r.policy_expires,r.capture_retention,
       r.period_end,r.delegation_expires_at,r.evidence_expires);
     IF r.policy_enabled IS DISTINCT FROM true OR r.policy_revoked IS NOT NULL
       OR r.current_generation<>r.policy_generation OR r.capture_generation<>r.policy_generation OR r.admission_generation<>r.policy_generation
       OR r.policy_retention<=t OR r.policy_expires<=t OR r.capture_retention<=t OR r.cleared_at IS NOT NULL OR r.capture_body_available IS DISTINCT FROM true
       OR r.fetched_sha256<>r.document_hash OR r.admission_active IS DISTINCT FROM true OR r.admission_revoked IS NOT NULL
       OR NOT (b->>'purpose'=ANY(r.policy_usages) AND b->>'purpose'=ANY(r.admission_usages) AND b->>'purpose'=ANY(r.allowed_usages))
       OR r.status<>'reviewed' OR r.reading_fit<>'suitable' OR r.version_fit<>'current' OR r.technical_status<>'correct'
       OR r.conflict_status<>'resolved' OR r.known_error<>'absent' OR r.root_enabled IS DISTINCT FROM true
       OR NOT(r.period_start<=t AND t<r.period_end AND t<r.delegation_expires_at)
       OR r.root_policy<>r.policy_id OR r.root_generation<>r.policy_generation
       OR (r.assessment_evidence_id IS NOT NULL AND (r.evidence_expires IS NULL OR r.evidence_expires<=t OR r.evidence_revoked IS NOT NULL)) THEN RETURN false; END IF;
     IF b->>'purpose'='assessment_evidence' THEN
       PERFORM 1 FROM rag_source_claim_receipts cr JOIN rag_source_admissions ad ON ad.id=cr.admission_id
         WHERE ad.receipt_handle=b->>'admission_receipt_id' AND cr.verification_receipt_hash=e->>'claim_receipt_hash'
           AND cr.revoked_at IS NULL AND cr.source_document_hash=r.document_hash FOR SHARE OF cr,ad;
       IF NOT FOUND THEN RETURN false; END IF;
     END IF;


   -- Corpus bytes are original-owner stored, not caller-hashed invented excerpts.
   PERFORM 1 FROM public.grounding_corpus_chunks c JOIN public.grounding_corpus_documents doc
    ON doc.corpus_version_id=c.corpus_version_id AND doc.document_id=c.document_id
    WHERE c.corpus_version_id=corpus_id AND c.chunk_id=e->>'chunk_id'
      AND c.chunk_hash=e->>'chunk_hash' AND c.content=material->>'excerpt'
      AND c.document_hash=b->>'document_hash' AND c.document_id=b->>'document_handle'
      AND doc.canonical_url='https://www.sqlite.org/lang_select.html' FOR SHARE OF c,doc;
   IF NOT FOUND THEN RETURN false; END IF;
  END LOOP;
  claim:=material->'exact_claims'->0; old_claim:=old_material->'exact_claims'->0;
  IF (claim-'claim_hash'-'claim_receipt_id'-'binding') IS DISTINCT FROM (old_claim-'claim_hash'-'claim_receipt_id'-'binding') OR
     ((claim->'binding')-'document_handle'-'admission_receipt_id'-'claim_receipt_id') IS DISTINCT FROM
       ((old_claim->'binding')-'document_handle'-'admission_receipt_id'-'claim_receipt_id') OR
     claim->>'claim_receipt_id' IS DISTINCT FROM claim->'binding'->>'claim_receipt_id' THEN RETURN false; END IF;
  PERFORM 1 FROM public.rag_source_claim_receipts cr JOIN public.rag_source_admissions ad ON ad.id=cr.admission_id
    WHERE cr.receipt_handle=claim->>'claim_receipt_id' AND cr.claim_hash=claim->>'claim_hash'
      AND cr.demand_hash=claim->'binding'->>'demand_hash' AND cr.source_document_hash=claim->'binding'->>'document_hash'
      AND ad.receipt_handle=claim->'binding'->>'admission_receipt_id'
      AND cr.assessment_evidence_id=source_id AND cr.execution_receipt_handle=new_source.execution_handle
      AND cr.execution_scope_json=claim->'execution_scope' AND cr.applicability=claim->>'applicability'
      AND cr.revoked_at IS NULL AND ad.active AND ad.revoked_at IS NULL FOR SHARE OF cr,ad;
  IF NOT FOUND THEN RETURN false; END IF;
 END LOOP;
 -- Original PUBLIC factory must publish all five exact select spans, even when
 -- the frozen P1 material subset has fewer entries. No missing companion/excerpt.
 SELECT count(DISTINCT c.chunk_id) INTO all_chunks FROM public.grounding_corpus_chunks c
  WHERE c.corpus_version_id=corpus_id AND c.document_id=new_prepared->>'document_handle';
 IF all_chunks<>5 OR EXISTS(SELECT 1 FROM jsonb_array_elements(new_prepared->'spans') span
   WHERE NOT EXISTS(SELECT 1 FROM public.grounding_corpus_chunks c WHERE c.corpus_version_id=corpus_id
    AND c.document_id=new_prepared->>'document_handle' AND c.chunk_hash=span->>'sha256'
    AND octet_length(c.content)=(span->>'end_byte')::integer-(span->>'start_byte')::integer)) THEN RETURN false; END IF;
 RETURN clock_timestamp()<deadline;
END $p1current584$;
REVOKE ALL ON FUNCTION public.native_consumer_m03_p1_source_current(uuid,uuid,jsonb,boolean) FROM PUBLIC;
