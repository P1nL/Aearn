-- Actual-D signed v3 is conditional PRIVATE data, identified by signed format
-- and actual_d.draft.user_id, never by the reused physical public profile ID.
-- No historical payload update, retention adoption, public re-sign or wallet.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid='rag_assessment_source_evidence'::regclass
      AND attname='private_user_id' AND NOT attisdropped)
    AND EXISTS (SELECT 1 FROM rag_assessment_source_evidence
      WHERE signed_proof->'payload'->>'format'='aearn.rag.actual-d-finite-source.v3') THEN
    RAISE check_violation USING MESSAGE='unclassified historical actual D proofs require explicit reconciliation';
  END IF;
END $$;

ALTER TABLE rag_assessment_source_evidence ADD COLUMN IF NOT EXISTS private_user_id uuid
  REFERENCES tutor_item_supply_user_epochs(user_id) ON DELETE RESTRICT;
ALTER TABLE rag_assessment_source_evidence ADD COLUMN IF NOT EXISTS private_epoch bigint;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='rag_assessment_source_evidence'::regclass
      AND conname='rag_actual_d_private_classification') THEN
    ALTER TABLE rag_assessment_source_evidence ADD CONSTRAINT rag_actual_d_private_classification CHECK (
      (CASE WHEN signed_proof->'payload'->>'format'='aearn.rag.actual-d-finite-source.v3' THEN
        private_user_id IS NOT NULL AND private_epoch IS NOT NULL AND private_epoch>=1 AND
        (signed_proof->'payload'->'prepared'->'actual_d'->'draft'->>'user_id') IS NOT DISTINCT FROM private_user_id::text AND
        (signed_proof->'payload'->'prepared'->'actual_d'->>'user_epoch') IS NOT DISTINCT FROM private_epoch::text
      ELSE private_user_id IS NULL AND private_epoch IS NULL AND
        NOT (signed_proof->'payload'->'prepared' ? 'actual_d') END));
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS rag_actual_d_private_owner ON rag_assessment_source_evidence(private_user_id,private_epoch)
  WHERE private_user_id IS NOT NULL;

-- READ ONLY: original owner -> original epoch; no implicit epoch initialization.
CREATE OR REPLACE FUNCTION rag_actual_d_private_epoch(target_user uuid, expected_epoch bigint, nonblocking boolean)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE current_epoch bigint;
BEGIN
  IF target_user IS NULL OR (expected_epoch IS NOT NULL AND expected_epoch<1) OR nonblocking IS NULL THEN
    RAISE check_violation USING MESSAGE='actual D private owner context invalid';
  END IF;
  IF nonblocking THEN
    PERFORM id FROM users WHERE id=target_user AND deleted_at IS NULL FOR SHARE NOWAIT;
  ELSE
    PERFORM id FROM users WHERE id=target_user AND deleted_at IS NULL FOR SHARE;
  END IF;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='actual D private active owner missing'; END IF;
  IF nonblocking THEN
    SELECT epoch INTO current_epoch FROM tutor_item_supply_user_epochs WHERE user_id=target_user AND enabled FOR SHARE NOWAIT;
  ELSE
    SELECT epoch INTO current_epoch FROM tutor_item_supply_user_epochs WHERE user_id=target_user AND enabled FOR SHARE;
  END IF;
  IF NOT FOUND OR (expected_epoch IS NOT NULL AND current_epoch IS DISTINCT FROM expected_epoch) THEN
    RAISE check_violation USING MESSAGE='actual D private epoch stale';
  END IF;
  IF item_supply_internal.permitted(target_user) THEN
    RAISE check_violation USING MESSAGE='actual D private reset in progress';
  END IF;
  RETURN current_epoch;
END $$;

CREATE OR REPLACE FUNCTION rag_actual_d_private_insert() RETURNS trigger LANGUAGE plpgsql AS $$
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
      JOIN rag_assessment_source_evidence e ON e.id=r.assessment_evidence_id
      WHERE a.id=NEW.independent_admission_id AND e.private_user_id IS NOT NULL) THEN
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
END $$;
DO $$ DECLARE tab text; BEGIN
  FOREACH tab IN ARRAY ARRAY['rag_assessment_source_evidence','rag_source_reviews','rag_source_admissions','rag_source_claim_receipts'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS aaa_actual_d_private_insert ON %I',tab);
    EXECUTE format('CREATE TRIGGER aaa_actual_d_private_insert BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION rag_actual_d_private_insert()',tab);
  END LOOP;
END $$;

-- Existing immutable C corpus has no private purge authority. Do not invent one.
-- Exact original handles/IDs/private hashes are protected, not shared raw hashes.
CREATE OR REPLACE FUNCTION rag_actual_d_private_reference_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE refs text[];
DECLARE e rag_assessment_source_evidence%ROWTYPE;
DECLARE owner_text text := to_jsonb(NEW)->>'user_id';
BEGIN
  SELECT array_agg(value #>> '{}') INTO refs FROM jsonb_path_query(to_jsonb(NEW),'$.** ? (@.type() == "string")') AS scalars(value);
  FOR e IN SELECT * FROM rag_assessment_source_evidence WHERE private_user_id IS NOT NULL AND
    ARRAY[id::text,document_handle,execution_handle,claim_handle,proof_hash,demand_hash,
      signed_proof->'payload'->>'review_id',signed_proof->'payload'->>'admission_id',
      signed_proof->'payload'->>'claim_id',signed_proof->'payload'->>'admission_handle'] && refs FOR SHARE LOOP
    IF owner_text IS NULL THEN
      RAISE check_violation USING MESSAGE='actual D private reference to shared corpus blocked';
    END IF;
    IF owner_text IS DISTINCT FROM e.private_user_id::text THEN
      RAISE check_violation USING MESSAGE='actual D private cross owner reference denied';
    END IF;
    PERFORM rag_actual_d_private_epoch(e.private_user_id,e.private_epoch,true);
  END LOOP;
  RETURN NEW;
END $$;
DO $$ DECLARE tab text; BEGIN
  FOREACH tab IN ARRAY ARRAY['rag_corpus_admission_links','grounding_corpus_versions','grounding_corpus_source_snapshots',
    'grounding_corpus_documents','grounding_corpus_chunks','grounding_corpus_events','grounding_active_corpora',
    'rag_corpus_validation_receipts','rag_material_selections','rag_plan_material_bindings','tutor_item_supply_finite_course_mappings'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS aaa_actual_d_private_reference ON %I',tab);
    EXECUTE format('CREATE TRIGGER aaa_actual_d_private_reference BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION rag_actual_d_private_reference_guard()',tab);
  END LOOP;
END $$;

-- Only original protected reset permit AND an advanced epoch can delete private
-- children. Public rows, another owner, source captures and budgets cannot pass.
CREATE OR REPLACE FUNCTION rag_actual_d_private_delete_allowed(evidence_id uuid) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT EXISTS (SELECT 1 FROM rag_assessment_source_evidence e JOIN tutor_item_supply_user_epochs u
    ON u.user_id=e.private_user_id WHERE e.id=evidence_id AND
    e.signed_proof->'payload'->>'format'='aearn.rag.actual-d-finite-source.v3' AND
    u.epoch>e.private_epoch AND item_supply_internal.permitted(e.private_user_id))
$$;
REVOKE ALL ON FUNCTION rag_actual_d_private_delete_allowed(uuid) FROM PUBLIC;

-- Patch exact original guard bodies, preserving every INSERT/UPDATE rule. A
-- full manifest replay restores originals before this fragment; direct replay
-- recognizes only our marked body plus the exact preceding original body.
DO $$ DECLARE spec record; definition text; body text; original_body text; clause text; BEGIN
  FOR spec IN SELECT * FROM (VALUES
    ('rag_assessment_source_evidence_guard','a547c4cf6f0710e894f294380f40f351','OLD.id'),
    ('rag_source_review_guard','6894300a6cf1b8f31bf6c3f9284b22ec','OLD.assessment_evidence_id'),
    ('rag_source_admission_guard','13104409dae8049b31adc7c77fdbcec1','(SELECT assessment_evidence_id FROM rag_source_reviews WHERE id=OLD.review_id)'),
    ('rag_source_claim_guard','7e473752ae96a43c5d455a5c2a931444','OLD.assessment_evidence_id')
  ) AS x(name,expected_hash,coordinate) LOOP
    SELECT prosrc INTO body FROM pg_proc WHERE oid=(spec.name||'()')::regprocedure;
    clause := '  --503 conditional private deletion'||chr(10)||
      '  IF TG_OP=''DELETE'''||(CASE WHEN spec.name='rag_source_claim_guard' THEN ' AND TG_TABLE_NAME=''rag_source_claim_receipts''' ELSE '' END)||' THEN'||chr(10)||
      '    IF rag_actual_d_private_delete_allowed('||spec.coordinate||') THEN RETURN OLD; END IF;'||chr(10)||
      '  END IF;'||chr(10);
    original_body := replace(body,clause,'');
    IF md5(original_body) IS DISTINCT FROM spec.expected_hash THEN
      RAISE check_violation USING MESSAGE='503 requires exact original or503 conditional source guard';
    END IF;
    IF body=original_body THEN
      definition := pg_get_functiondef((spec.name||'()')::regprocedure);
      definition := replace(definition,'BEGIN'||chr(10),'BEGIN'||chr(10)||clause);
      EXECUTE definition;
    END IF;
  END LOOP;
END $$;

-- Original470 closes its permit before Python removes D children. Only when
-- actual-D proofs still exist, retain that SAME permit until the original D
-- owner's tail call. No new permit, caller GUC, new purge owner or epoch reset.
DO $$ DECLARE body text; original_body text; definition text; original_tail text; new_tail text; BEGIN
  SELECT prosrc INTO body FROM pg_proc WHERE oid='purge_item_supply_private(uuid,boolean)'::regprocedure;
  original_tail := '  DELETE FROM item_supply_internal.reset_permits WHERE transaction_id=txid_current() AND user_id=target_user;';
  new_tail := '  --503 retain original permit until original D children are removed'||chr(10)||
    '  IF NOT EXISTS (SELECT 1 FROM rag_assessment_source_evidence WHERE private_user_id=target_user) THEN'||chr(10)||
    original_tail||chr(10)||'  END IF;';
  original_body := replace(body,new_tail,original_tail);
  IF md5(original_body) IS DISTINCT FROM '550fef67701f985e654e310defe7858f' THEN
    RAISE check_violation USING MESSAGE='503 requires exact470 or503 original reset owner';
  END IF;
  IF body=original_body THEN
    definition := pg_get_functiondef('purge_item_supply_private(uuid,boolean)'::regprocedure);
    EXECUTE replace(definition,original_tail,new_tail);
  END IF;
END $$;

CREATE OR REPLACE FUNCTION rag_actual_d_private_purge(target_user uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE active_epoch bigint;
BEGIN
  IF target_user IS NULL THEN RAISE check_violation USING MESSAGE='actual D private purge owner missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM rag_assessment_source_evidence WHERE private_user_id=target_user) THEN RETURN; END IF;
  SELECT epoch INTO active_epoch FROM tutor_item_supply_user_epochs WHERE user_id=target_user FOR SHARE;
  IF target_user IS NULL OR active_epoch IS NULL OR item_supply_internal.permitted(target_user) IS DISTINCT FROM true OR
    EXISTS (SELECT 1 FROM rag_assessment_source_evidence WHERE private_user_id=target_user AND private_epoch>=active_epoch) THEN
    RAISE check_violation USING MESSAGE='actual D tail requires original permitted advanced epoch';
  END IF;
  IF EXISTS (SELECT 1 FROM rag_plan_material_bindings WHERE user_id=target_user) OR
     EXISTS (SELECT 1 FROM rag_material_semantic_reviews WHERE user_id=target_user) OR
     EXISTS (SELECT 1 FROM rag_material_selections WHERE user_id=target_user) THEN
    RAISE check_violation USING MESSAGE='actual D source purge requires original D children first';
  END IF;
  -- No DELETE on corpus/link history: invalid shared references are blocked at
  -- creation; an unexpected historical FK still denies/rolls back this purge.
  IF to_regclass('public.rag_actual_d_private_provenance') IS NOT NULL THEN
    EXECUTE 'DELETE FROM public.rag_actual_d_private_provenance WHERE user_id=$1 AND epoch<$2'
      USING target_user,active_epoch;
  END IF;
  DELETE FROM rag_source_claim_receipts c USING rag_assessment_source_evidence e
    WHERE c.assessment_evidence_id=e.id AND e.private_user_id=target_user AND e.private_epoch<active_epoch;
  DELETE FROM rag_source_admissions a USING rag_source_reviews r,rag_assessment_source_evidence e
    WHERE a.review_id=r.id AND r.assessment_evidence_id=e.id AND e.private_user_id=target_user AND e.private_epoch<active_epoch;
  DELETE FROM rag_source_reviews r USING rag_assessment_source_evidence e
    WHERE r.assessment_evidence_id=e.id AND e.private_user_id=target_user AND e.private_epoch<active_epoch;
  DELETE FROM rag_assessment_source_evidence WHERE private_user_id=target_user AND private_epoch<active_epoch;
  DELETE FROM item_supply_internal.reset_permits WHERE transaction_id=txid_current() AND user_id=target_user;
END $$;
REVOKE ALL ON FUNCTION rag_actual_d_private_purge(uuid) FROM PUBLIC;

-- A forgotten original-owner tail is an explicit BLOCKED transaction, never
-- anonymous retention or a deferred second purger. Only checks, no mutation.
CREATE OR REPLACE FUNCTION item_supply_internal.assert_actual_d_private_reset_complete() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM rag_assessment_source_evidence WHERE private_user_id=NEW.user_id AND private_epoch<NEW.epoch) OR
    item_supply_internal.permitted(NEW.user_id) THEN
    RAISE check_violation USING MESSAGE='actual D original reset tail incomplete';
  END IF;
  RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_actual_d_private_reset_complete() FROM PUBLIC;
DROP TRIGGER IF EXISTS rag_actual_d_private_reset_complete ON tutor_item_supply_user_epochs;
CREATE CONSTRAINT TRIGGER rag_actual_d_private_reset_complete AFTER UPDATE ON tutor_item_supply_user_epochs
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (OLD.epoch < NEW.epoch)
  EXECUTE FUNCTION item_supply_internal.assert_actual_d_private_reset_complete();
