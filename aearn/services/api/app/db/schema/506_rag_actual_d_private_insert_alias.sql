-- Additive repair of the populated actual-D claim path (503 is immutable).
-- Only a local SQL table alias changes; signed ownership, epoch and privacy
-- fences, historical rows, grants and function permissions remain unchanged.
DO $repair$
DECLARE
  actual record;
  source_hash text;
  repaired_source constant text := $body$
DECLARE e rag_assessment_source_evidence%ROWTYPE;
DECLARE proof jsonb;
BEGIN
  IF TG_TABLE_NAME='rag_assessment_source_evidence' THEN
    IF NEW.signed_proof->'payload'->>'format'='aearn.rag.actual-d-finite-source.v3' THEN
      proof := NEW.signed_proof->'payload';
      IF NEW.private_user_id IS NULL OR NEW.private_epoch IS NULL OR
        proof->'prepared'->'actual_d'->'draft'->>'user_id' IS DISTINCT FROM NEW.private_user_id::text OR
        proof->'prepared'->'actual_d'->>'user_epoch' IS DISTINCT FROM NEW.private_epoch::text THEN
        RAISE check_violation USING MESSAGE='actual D private signed owner mismatch';
      END IF;
      PERFORM rag_actual_d_private_epoch(NEW.private_user_id,NEW.private_epoch,false);
    END IF;
    RETURN NEW;
  ELSIF TG_TABLE_NAME='rag_source_reviews' THEN
    SELECT * INTO e FROM rag_assessment_source_evidence WHERE id=NEW.assessment_evidence_id FOR SHARE;
    IF e.private_user_id IS NOT NULL AND NEW.id::text IS DISTINCT FROM e.signed_proof->'payload'->>'review_id' THEN
      RAISE check_violation USING MESSAGE='actual D private review identity mismatch';
    END IF;
  ELSIF TG_TABLE_NAME='rag_source_admissions' THEN
    SELECT evidence.* INTO e FROM rag_assessment_source_evidence evidence JOIN rag_source_reviews r
      ON r.assessment_evidence_id=evidence.id WHERE r.id=NEW.review_id FOR SHARE OF evidence,r;
    IF e.private_user_id IS NOT NULL AND NEW.id::text IS DISTINCT FROM e.signed_proof->'payload'->>'admission_id' THEN
      RAISE check_violation USING MESSAGE='actual D private admission identity mismatch';
    END IF;
  ELSE
    -- Independent/private crossover is not an owned dependency and is denied.
    IF EXISTS (SELECT 1 FROM rag_source_admissions a JOIN rag_source_reviews r ON r.id=a.review_id
      JOIN rag_assessment_source_evidence private_evidence ON private_evidence.id=r.assessment_evidence_id
      WHERE a.id=NEW.independent_admission_id AND private_evidence.private_user_id IS NOT NULL) THEN
      RAISE check_violation USING MESSAGE='actual D private independent reference denied';
    END IF;
    SELECT evidence.* INTO e FROM rag_assessment_source_evidence evidence JOIN rag_source_reviews r
      ON r.assessment_evidence_id=evidence.id JOIN rag_source_admissions adm ON adm.review_id=r.id
      WHERE adm.id=NEW.admission_id FOR SHARE OF evidence,r,adm;
    IF e.private_user_id IS NOT NULL AND (NEW.assessment_evidence_id IS DISTINCT FROM e.id OR
      NEW.id::text IS DISTINCT FROM e.signed_proof->'payload'->>'claim_id' OR NEW.method<>'isolated_execution') THEN
      RAISE check_violation USING MESSAGE='actual D private claim identity mismatch';
    END IF;
    IF EXISTS (SELECT 1 FROM rag_assessment_source_evidence evidence
      WHERE evidence.id=NEW.assessment_evidence_id AND evidence.private_user_id IS NOT NULL AND evidence.id IS DISTINCT FROM e.id) THEN
      RAISE check_violation USING MESSAGE='actual D private cross admission reference denied';
    END IF;
  END IF;
  IF e.private_user_id IS NOT NULL THEN
    PERFORM rag_actual_d_private_epoch(e.private_user_id,e.private_epoch,false);
  END IF;
  RETURN NEW;
END $body$;
BEGIN
  SELECT p.*,l.lanname INTO actual FROM pg_proc p
    JOIN pg_namespace n ON n.oid=p.pronamespace
    JOIN pg_language l ON l.oid=p.prolang
    WHERE n.nspname='public' AND p.proname='rag_actual_d_private_insert'
      AND p.pronargs=0;
  IF NOT FOUND OR actual.prokind<>'f' OR actual.lanname<>'plpgsql'
    OR actual.prorettype<>'trigger'::regtype OR actual.proretset
    OR actual.proisstrict OR actual.prosecdef OR actual.proleakproof
    OR actual.provolatile<>'v' OR actual.proparallel<>'u'
    OR actual.provariadic<>0 OR actual.pronargdefaults<>0
    OR actual.proargnames IS NOT NULL OR actual.proallargtypes IS NOT NULL
    OR actual.proconfig IS NOT NULL OR actual.procost<>100 OR actual.prorows<>0
    OR actual.prosupport<>0 THEN
    RAISE check_violation USING MESSAGE='actual D private insert function attributes differ from reviewed baseline';
  END IF;
  source_hash:=encode(sha256(convert_to(replace(actual.prosrc,E'\r\n',E'\n'),'UTF8')),'hex');
  IF source_hash='1e8f6e8636b755f07856c9aed52a6ace50f032fa99085dfa02a6a4e48f7a7874' THEN
    RETURN;
  END IF;
  IF source_hash<>'1145b1bf366834a6eb11f4c1515ed296a5531f3f01fc692f2452ca3e0ffa4243'
    OR encode(sha256(convert_to(repaired_source,'UTF8')),'hex')<>'1e8f6e8636b755f07856c9aed52a6ace50f032fa99085dfa02a6a4e48f7a7874' THEN
    RAISE check_violation USING MESSAGE='actual D private insert function body differs from reviewed baseline';
  END IF;
  EXECUTE format('CREATE OR REPLACE FUNCTION public.rag_actual_d_private_insert() '
    'RETURNS trigger LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER '
    'PARALLEL UNSAFE COST 100 AS %L',repaired_source);
END $repair$;
