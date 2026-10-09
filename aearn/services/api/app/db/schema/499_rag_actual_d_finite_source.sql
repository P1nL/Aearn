-- NEW actual-D finite source proofs, not public-proof relabeling. No row/grant,
-- old expiry, dispatch, budget, health lease or historical migration is changed.
-- The legacy profile_id COLUMN remains the finite semantic storage key so the
-- validated 486/488 CHECKs can replay before499 on a populated full bootstrap.
-- New signed prepared.profile_id and v3 domain remain distinct and exact.
DO $$ DECLARE body text; BEGIN
  SELECT replace(prosrc,E'\r','') INTO body FROM pg_proc
    WHERE oid='rag_assessment_source_evidence_guard()'::regprocedure;
  IF md5(body) NOT IN ('70fb15cca39df859ed34f721b3485f0d','7f6901741a6d9730f8dad452effe9033','fa47494d7ea1a7af5474b43b788fe39a','a547c4cf6f0710e894f294380f40f351') OR body IS NULL THEN
    RAISE check_violation USING MESSAGE='499 requires exact497 or499 source guard';
  END IF;
  SELECT replace(prosrc,E'\r','') INTO body FROM pg_proc
    WHERE oid='rag_course_material_proof_lifetime_allowed(jsonb,text,timestamp with time zone,timestamp with time zone)'::regprocedure;
  IF md5(body) NOT IN ('44d10e4ba1a5f0f28fd2c0bdf4f06497','eaaa355a2e5aed985b5c5f8958d55b90') OR body IS NULL THEN
    RAISE check_violation USING MESSAGE='499 requires exact497 or499 lifetime guard';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION rag_actual_d_finite_storage_profile(profile text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE profile
    WHEN 'python-state-actual-d-source-v1' THEN 'python-state-source-v1'
    WHEN 'python-binding-actual-d-source-v1' THEN 'python-binding-source-v1'
    WHEN 'sqlite-predicate-actual-d-source-v1' THEN 'sqlite-predicate-source-v1'
    ELSE NULL END
$$;

CREATE OR REPLACE FUNCTION rag_actual_d_finite_lifetime_allowed(
  signed_proof jsonb, profile_id text, issued_at timestamptz, expires_at timestamptz
) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE p jsonb := signed_proof->'payload';
DECLARE q jsonb := p->'prepared';
DECLARE a jsonb := q->'actual_d';
DECLARE prepared_at timestamptz;
DECLARE authority_until timestamptz;
DECLARE companion jsonb;
BEGIN
  IF (p->>'format') IS DISTINCT FROM 'aearn.rag.actual-d-finite-source.v3' OR
     rag_actual_d_finite_storage_profile(q->>'profile_id') IS NULL OR
     rag_actual_d_finite_storage_profile(q->>'profile_id') IS DISTINCT FROM profile_id OR
     (a->>'contract_version') IS DISTINCT FROM 'rag_actual_d_finite_source_scope_v1' OR
     (a->>'oracle_run_id') IS NULL OR
     (p->'terminal'->>'run_id') IS DISTINCT FROM a->>'oracle_run_id' OR
     (p->'terminal'->>'probe_name') IS DISTINCT FROM 'actual_d_finite_source_oracle' OR
     issued_at IS NULL OR expires_at IS NULL OR issued_at>=expires_at OR
     expires_at>issued_at+interval '168 hours' OR
     (p->>'issued_at') IS NULL OR (p->>'expires_at') IS NULL OR
     (p->>'issued_at')::timestamptz IS DISTINCT FROM issued_at OR
     (p->>'expires_at')::timestamptz IS DISTINCT FROM expires_at THEN RETURN false; END IF;
  PERFORM (a->>'oracle_run_id')::uuid;
  prepared_at := (q->>'prepared_at')::timestamptz;
  authority_until := (q->>'authority_expires_at')::timestamptz;
  IF prepared_at IS NULL OR authority_until IS NULL OR prepared_at>issued_at OR
     authority_until<expires_at OR authority_until>prepared_at+interval '168 hours' OR
     (q->'budget'->>'expires_at') IS NULL OR
     authority_until>(q->'budget'->>'expires_at')::timestamptz THEN RETURN false; END IF;
  IF profile_id='sqlite-predicate-source-v1' THEN
    IF jsonb_typeof(q->'companions') IS DISTINCT FROM 'array' OR
       jsonb_array_length(q->'companions')<>2 THEN RETURN false; END IF;
    FOR companion IN SELECT value FROM jsonb_array_elements(q->'companions') LOOP
      IF (companion->>'authority_expires_at') IS NULL OR
         (companion->'budget'->>'expires_at') IS NULL OR
         (companion->>'authority_expires_at')::timestamptz<authority_until OR
         (companion->>'authority_expires_at')::timestamptz>prepared_at+interval '168 hours' OR
         (companion->>'authority_expires_at')::timestamptz IS DISTINCT FROM
           (companion->'budget'->>'expires_at')::timestamptz THEN RETURN false; END IF;
    END LOOP;
  ELSIF q ? 'companions' THEN RETURN false;
  END IF;
  RETURN true;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow OR invalid_parameter_value OR invalid_text_representation THEN
  RETURN false;
END $$;

CREATE OR REPLACE FUNCTION rag_actual_d_finite_source_scope_check(e rag_assessment_source_evidence)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE p jsonb := e.signed_proof->'payload';
DECLARE q jsonb := p->'prepared';
DECLARE a jsonb := q->'actual_d';
DECLARE ds jsonb := a->'draft';
DECLARE s tutor_learning_plan_sessions%ROWTYPE;
DECLARE d tutor_learning_plan_drafts%ROWTYPE;
DECLARE r tutor_runs%ROWTYPE;
DECLARE b rag_material_selections%ROWTYPE;
DECLARE nodes jsonb;
DECLARE node jsonb;
DECLARE mains jsonb;
DECLARE main jsonb;
DECLARE target text;
DECLARE target_hash text;
DECLARE description_hash text;
DECLARE expected_language text;
DECLARE expected_capabilities jsonb;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' OR
     rag_actual_d_finite_lifetime_allowed(e.signed_proof,e.profile_id,e.issued_at,e.expires_at) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='actual D source proof contract denied';
  END IF;
  -- New source issuance is draft_ready only. Later confirmed reads are an exact
  -- frozen-plan service path, never authority to insert a new proof afterwards.
  PERFORM id FROM users WHERE id=(ds->>'user_id')::uuid AND deleted_at IS NULL FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='actual D active source owner missing'; END IF;
  SELECT * INTO s FROM tutor_learning_plan_sessions
    WHERE id=(ds->>'session_id')::uuid AND user_id=(ds->>'user_id')::uuid FOR SHARE;
  SELECT * INTO d FROM tutor_learning_plan_drafts
    WHERE id=(ds->>'draft_id')::uuid AND session_id=s.id AND user_id=s.user_id FOR SHARE;
  SELECT * INTO r FROM tutor_runs WHERE id=d.source_run_id FOR SHARE;
  SELECT * INTO b FROM rag_material_selections WHERE handle=a->>'base_selection_handle'
    AND draft_id=d.id AND session_id=s.id AND user_id=s.user_id FOR SHARE;
  IF s.id IS NULL OR d.id IS NULL OR r.id IS NULL OR b.handle IS NULL OR
     s.status<>'draft_ready' OR s.current_draft_id IS DISTINCT FROM d.id OR
     s.conversation_id::text IS DISTINCT FROM ds->>'conversation_id' OR
     d.draft_version::text IS DISTINCT FROM ds->>'draft_version' OR
     d.content_hash IS DISTINCT FROM ds->>'content_hash' OR
     d.source_run_id::text IS DISTINCT FROM ds->>'source_run_id' OR
     d.source_input_revision::text IS DISTINCT FROM ds->>'source_input_revision' OR
     r.user_id IS DISTINCT FROM s.user_id OR r.conversation_id IS DISTINCT FROM s.conversation_id OR
     r.input_revision IS DISTINCT FROM d.source_input_revision OR
     b.snapshot_json->'draft' IS DISTINCT FROM ds OR
     b.selection_digest IS DISTINCT FROM a->>'base_selection_digest' OR
     b.snapshot_json->>'selection_digest' IS DISTINCT FROM b.selection_digest OR
     b.snapshot_json->>'handle' IS DISTINCT FROM b.handle THEN
    RAISE check_violation USING MESSAGE='actual D source draft or selection stale';
  END IF;
  CASE q->>'profile_id'
    WHEN 'python-state-actual-d-source-v1' THEN
      target := 'python-state-update-v1'; target_hash := '185544231076d15cb9c50539e57bb1bf115ff748d68c35d0ae04d6e4346e3891';
      description_hash := 'fa664ab0bec601ba901827abca1a1c5da63af92b8bb7c58d7ecf17dc350bf610';
    WHEN 'python-binding-actual-d-source-v1' THEN
      target := 'python-kc-binding-v1'; target_hash := 'ac716c31c68c112c9b73ecc68b90c0ccb7e29f1694a77e23038375c4d4795abd';
      description_hash := 'c96cda545db2cee905f536d01a9dc5879500f901de2440a196241795ebfa90d1';
    WHEN 'sqlite-predicate-actual-d-source-v1' THEN
      target := 'sqlite-predicate-order-v1'; target_hash := '333d8108ac641f79580e5c36df2a41fe9cc1271853d536c4d735f97b535b7b54';
      description_hash := 'de948281c0ad32fb72d6c9191514f3ecf272d32891f2edeffe176c9c2cef813d';
    ELSE RAISE check_violation USING MESSAGE='actual D source profile denied';
  END CASE;
  expected_language := CASE WHEN e.profile_id='sqlite-predicate-source-v1' THEN 'sql' ELSE 'python' END;
  expected_capabilities := CASE WHEN expected_language='sql' THEN '["sql.select.where","sql.order_by"]'::jsonb
                               ELSE '["python.assignment"]'::jsonb END;
  SELECT jsonb_agg(n.value) INTO nodes FROM jsonb_array_elements(d.plan_json->'modules') m
    CROSS JOIN LATERAL jsonb_array_elements(m.value->'nodes') n WHERE n.value->>'knowledge_key'=a->>'node_id';
  SELECT jsonb_agg(v.value) INTO mains FROM jsonb_array_elements(b.snapshot_json->'requirements') v
    WHERE v.value->>'node_id'=a->>'node_id' AND v.value->'demand'->>'purpose'='main_teaching';
  IF jsonb_array_length(nodes) IS DISTINCT FROM 1 OR jsonb_array_length(mains) IS DISTINCT FROM 1 THEN
    RAISE check_violation USING MESSAGE='actual D source exact node required';
  END IF;
  node := nodes->0; main := mains->0;
  IF (a->>'target_id') IS DISTINCT FROM target OR (a->>'target_definition_hash') IS DISTINCT FROM target_hash OR
     (a->>'goal_hash') IS DISTINCT FROM main->>'goal_hash' OR
     (main->'prerequisites') IS DISTINCT FROM node->'prerequisite_keys' OR
     encode(digest(node->>'description','sha256'),'hex') IS DISTINCT FROM description_hash OR
     d.profile_json->>'language_id' IS DISTINCT FROM expected_language OR
     node->'required_capabilities' IS DISTINCT FROM expected_capabilities OR
     q->'demand'->>'plan_ref' IS DISTINCT FROM ('draft.'||d.id::text) OR
     q->'demand'->>'node_ref' IS DISTINCT FROM ('node.'||(a->>'node_id')) OR
     q->'demand'->>'draft_revision' IS DISTINCT FROM d.draft_version::text OR
     q->'demand'->>'purpose' IS DISTINCT FROM 'assessment_evidence' OR
     q->'demand'->'scope' IS DISTINCT FROM main->'demand'->'scope' OR
     q->'demand'->>'reading_level' IS DISTINCT FROM main->'demand'->>'reading_level' OR
     q->'demand'->>'language' IS DISTINCT FROM main->'demand'->>'language' OR
     q->'demand'->'scope'->>'subject_version' IS DISTINCT FROM '1.0' OR
     q->'demand'->'scope'->>'subject_id' IS DISTINCT FROM ('route.'||expected_language) OR
     q->'demand'->'scope'->'facets' IS DISTINCT FROM
       (CASE WHEN expected_language='sql' THEN '["queries"]'::jsonb ELSE '["fundamentals"]'::jsonb END) THEN
    RAISE check_violation USING MESSAGE='actual D finite node demand mismatch';
  END IF;
  -- This substitutes only the public-demand restriction, not the source fence.
  IF NOT EXISTS(SELECT 1 FROM rag_registered_source_policies policy
    JOIN rag_registered_source_captures capture ON capture.policy_id=policy.policy_id
    WHERE policy.policy_id=e.policy_id AND capture.id=e.capture_id
      AND policy.canonical_url=CASE WHEN expected_language='sql' THEN 'https://www.sqlite.org/lang_select.html'
                                  ELSE 'https://docs.python.org/3/reference/simple_stmts.html' END
      AND policy.subject_id='route.'||expected_language AND policy.subject_version='1.0'
      AND to_jsonb(policy.facets)=q->'demand'->'scope'->'facets'
      AND capture.final_url=policy.canonical_url AND capture.request_chain=jsonb_build_array(policy.canonical_url)) THEN
    RAISE check_violation USING MESSAGE='actual D finite source identity denied';
  END IF;
END $$;

DO $$ DECLARE definition text; BEGIN
  definition := pg_get_functiondef('rag_assessment_source_evidence_guard()'::regprocedure);
  IF strpos(definition,'rag_actual_d_finite_source_scope_check(NEW)')=0 THEN
    definition := replace(definition,
      '  SELECT * INTO capture FROM rag_registered_source_captures WHERE id=NEW.capture_id FOR SHARE;',
      '  IF (NEW.signed_proof->''payload''->>''format'')=''aearn.rag.actual-d-finite-source.v3'' THEN'||chr(10)||
      '    PERFORM rag_actual_d_finite_source_scope_check(NEW);'||chr(10)||'  END IF;'||chr(10)||
      '  SELECT * INTO capture FROM rag_registered_source_captures WHERE id=NEW.capture_id FOR SHARE;');
    definition := replace(definition,
      '(NEW.profile_id IN (''python-state-source-v1'',''python-binding-source-v1'') AND',
      '(NEW.profile_id IN (''python-state-source-v1'',''python-binding-source-v1'') AND (proof->>''format'') IS DISTINCT FROM ''aearn.rag.actual-d-finite-source.v3'' AND');
    definition := replace(definition,'(NEW.profile_id=''sqlite-predicate-source-v1'' AND',
      '(NEW.profile_id=''sqlite-predicate-source-v1'' AND (proof->>''format'') IS DISTINCT FROM ''aearn.rag.actual-d-finite-source.v3'' AND');
    definition := replace(definition,'(prepared->>''profile_id'') IS DISTINCT FROM NEW.profile_id',
      '(CASE WHEN proof->>''format''=''aearn.rag.actual-d-finite-source.v3'' THEN rag_actual_d_finite_storage_profile(prepared->>''profile_id'') ELSE prepared->>''profile_id'' END) IS DISTINCT FROM NEW.profile_id');
    definition := replace(definition,'(proof->''terminal''->>''probe_name'') IS DISTINCT FROM ''source_assessment_oracle''',
      '(proof->''terminal''->>''probe_name'') IS DISTINCT FROM (CASE WHEN proof->>''format''=''aearn.rag.actual-d-finite-source.v3'' THEN ''actual_d_finite_source_oracle'' ELSE ''source_assessment_oracle'' END)');
    EXECUTE definition;
  END IF;
  -- Recheck after ALL common/companion lock waits, only for NEW v3 proofs.
  -- Keep the original 497 and historical v1/v2 behavior byte-preserved.
  IF strpos(definition,'actual D source proof expired after locks')=0 THEN
    definition := replace(definition,'  RETURN NEW;'||chr(10)||'END ',
      '  IF proof->>''format''=''aearn.rag.actual-d-finite-source.v3'' THEN'||chr(10)||
      '    clock := clock_timestamp();'||chr(10)||
      '    IF NEW.issued_at>clock OR NEW.expires_at<=clock THEN'||chr(10)||
      '      RAISE check_violation USING MESSAGE=''actual D source proof expired after locks'';'||chr(10)||
      '    END IF;'||chr(10)||'  END IF;'||chr(10)||'  RETURN NEW;'||chr(10)||'END ');
    EXECUTE definition;
  END IF;
  definition := pg_get_functiondef('rag_course_material_proof_lifetime_allowed(jsonb,text,timestamp with time zone,timestamp with time zone)'::regprocedure);
  IF strpos(definition,'rag_actual_d_finite_lifetime_allowed(signed_proof,profile_id,issued_at,expires_at)')=0 THEN
    definition := replace(definition,'BEGIN'||chr(10),'BEGIN'||chr(10)||
      '  IF proof->>''format''=''aearn.rag.actual-d-finite-source.v3'' THEN'||chr(10)||
      '    RETURN rag_actual_d_finite_lifetime_allowed(signed_proof,profile_id,issued_at,expires_at);'||chr(10)||
      '  END IF;'||chr(10));
    EXECUTE definition;
  END IF;
END $$;
