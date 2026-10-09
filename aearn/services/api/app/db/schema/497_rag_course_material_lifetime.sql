-- New finite course proofs only. Historical 480-496 bytes, proof rows, grants,
-- accounting roots, one-shot dispatch, leases and runtime health remain intact.
-- 480/486 share the same format marker but NOT the final native/companion
-- fences. Require the exact 488 body (or our already-patched body) BEFORE DDL.
-- MD5 is only a source-drift check, never signature/provenance authority.
DO $$
DECLARE expected_guard_md5 constant text := 'b4e298afcef1fd2efe5d72e801baf70e';
DECLARE guard_body text;
DECLARE marker constant text := '(proof->>''format'') IS DISTINCT FROM ''aearn.rag.fresh-assessment-source.v1''';
DECLARE injected constant text := 'rag_course_material_proof_lifetime_allowed(NEW.signed_proof,NEW.profile_id,NEW.issued_at,NEW.expires_at) IS DISTINCT FROM true';
BEGIN
  SELECT prosrc INTO guard_body FROM pg_proc
    WHERE oid='rag_assessment_source_evidence_guard()'::regprocedure;
  IF md5(replace(replace(guard_body,injected,marker), E'\r', '')) IS DISTINCT FROM expected_guard_md5 THEN
    RAISE check_violation USING MESSAGE='497 requires exact final 488 source guard';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION rag_course_material_proof_lifetime_allowed(
  signed_proof jsonb, profile_id text, issued_at timestamptz, expires_at timestamptz
) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE proof jsonb := signed_proof->'payload';
DECLARE prepared jsonb := proof->'prepared';
DECLARE prepared_at timestamptz;
DECLARE authority_expires_at timestamptz;
DECLARE companion jsonb;
BEGIN
  IF issued_at IS NULL OR expires_at IS NULL OR issued_at>=expires_at THEN RETURN false; END IF;
  IF proof->>'format'='aearn.rag.fresh-assessment-source.v1' THEN
    -- Preserve the historical signed schema's original bound, not currentness.
    RETURN expires_at<=issued_at+interval '24 hours';
  END IF;
  IF (proof->>'format') IS DISTINCT FROM 'aearn.rag.fresh-assessment-source.v2' OR
     profile_id NOT IN ('python-state-source-v1','python-binding-source-v1','sqlite-predicate-source-v1') OR
     (prepared->>'profile_id') IS DISTINCT FROM profile_id OR
     (proof->>'issued_at') IS NULL OR (proof->>'expires_at') IS NULL OR
     (proof->>'issued_at')::timestamptz IS DISTINCT FROM issued_at OR
     (proof->>'expires_at')::timestamptz IS DISTINCT FROM expires_at OR
     expires_at>issued_at+interval '168 hours' THEN RETURN false; END IF;
  prepared_at := (prepared->>'prepared_at')::timestamptz;
  authority_expires_at := (prepared->>'authority_expires_at')::timestamptz;
  IF prepared_at IS NULL OR authority_expires_at IS NULL OR
     prepared_at>issued_at OR authority_expires_at<expires_at OR
     authority_expires_at>prepared_at+interval '168 hours' OR
     (prepared->'budget'->>'expires_at') IS NULL OR
     authority_expires_at>(prepared->'budget'->>'expires_at')::timestamptz THEN RETURN false; END IF;
  IF profile_id='sqlite-predicate-source-v1' THEN
    IF jsonb_typeof(prepared->'companions') IS DISTINCT FROM 'array' OR
       jsonb_array_length(prepared->'companions')<>2 THEN RETURN false; END IF;
    FOR companion IN SELECT value FROM jsonb_array_elements(prepared->'companions') LOOP
      IF (companion->>'authority_expires_at') IS NULL OR
         (companion->>'authority_expires_at')::timestamptz<authority_expires_at OR
         (companion->>'authority_expires_at')::timestamptz>prepared_at+interval '168 hours' OR
         (companion->'budget'->>'expires_at') IS NULL OR
         (companion->>'authority_expires_at')::timestamptz IS DISTINCT FROM
           (companion->'budget'->>'expires_at')::timestamptz THEN RETURN false; END IF;
    END LOOP;
  END IF;
  RETURN true;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow OR invalid_parameter_value THEN
  RETURN false;
END $$;

-- Replace only the original anonymous lifetime CHECK. Never UPDATE old rows.
DO $$ DECLARE definition text; BEGIN
  SELECT pg_get_constraintdef(oid) INTO definition FROM pg_constraint
    WHERE conrelid='rag_assessment_source_evidence'::regclass AND contype='c'
      AND conname='rag_assessment_source_evidence_check';
  IF definition IS NOT NULL THEN
    IF strpos(definition,'issued_at')=0 OR strpos(definition,'expires_at')=0 OR
       (strpos(definition,'24:00:00')=0 AND strpos(definition,'24 hours')=0) THEN
      RAISE check_violation USING MESSAGE='497 original lifetime constraint shape changed';
    END IF;
    ALTER TABLE rag_assessment_source_evidence DROP CONSTRAINT rag_assessment_source_evidence_check;
  END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_constraint
      WHERE conrelid='rag_assessment_source_evidence'::regclass
        AND conname='rag_assessment_source_evidence_versioned_lifetime_check') THEN
    ALTER TABLE rag_assessment_source_evidence
      ADD CONSTRAINT rag_assessment_source_evidence_versioned_lifetime_check CHECK (
        rag_course_material_proof_lifetime_allowed(signed_proof,profile_id,issued_at,expires_at) IS TRUE
      );
  END IF;
END $$;

-- Narrow version alternative inside the final 488 guard: all original current
-- capture/policy/root/companion fences and UPDATE/DELETE immutability stay intact.
DO $$ DECLARE definition text; marker text; injected text; BEGIN
  definition := pg_get_functiondef('rag_assessment_source_evidence_guard()'::regprocedure);
  marker := '(proof->>''format'') IS DISTINCT FROM ''aearn.rag.fresh-assessment-source.v1''';
  injected := 'rag_course_material_proof_lifetime_allowed(NEW.signed_proof,NEW.profile_id,NEW.issued_at,NEW.expires_at) IS DISTINCT FROM true';
  IF strpos(definition,injected)>0 THEN NULL;
  ELSIF strpos(definition,marker)=0 OR
        (length(definition)-length(replace(definition,marker,'')))/length(marker)<>1 THEN
    RAISE check_violation USING MESSAGE='497 source proof version guard shape changed';
  ELSE EXECUTE replace(definition,marker,injected); END IF;
END $$;
