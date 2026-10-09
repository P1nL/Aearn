-- PRIVATE association only: existing PUBLIC corpus/document/signature bytes
-- remain unchanged. No private admission/document is registered in C history.
DO $$ BEGIN
  IF to_regprocedure('rag_actual_d_private_epoch(uuid,bigint,boolean)') IS NULL OR
     to_regprocedure('rag_actual_d_private_purge(uuid)') IS NULL THEN
    RAISE check_violation USING MESSAGE='504 requires503 private lifecycle';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='rag_assessment_source_evidence'::regclass
    AND conname='rag_actual_d_private_owner_key') THEN
    ALTER TABLE rag_assessment_source_evidence ADD CONSTRAINT rag_actual_d_private_owner_key
      UNIQUE(id,private_user_id,private_epoch);
  END IF;
END $$;
CREATE TABLE IF NOT EXISTS rag_actual_d_private_provenance (
  private_evidence_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  epoch bigint NOT NULL CHECK(epoch>=1),
  draft_id uuid NOT NULL,
  node_id text NOT NULL,
  goal_hash text NOT NULL CHECK(goal_hash ~ '^[0-9a-f]{64}$'),
  target_id text NOT NULL CHECK(target_id IN ('python-state-update-v1','python-kc-binding-v1','sqlite-predicate-order-v1')),
  public_evidence_id uuid NOT NULL REFERENCES rag_assessment_source_evidence(id) ON DELETE RESTRICT,
  corpus_id uuid NOT NULL,
  generation bigint NOT NULL CHECK(generation>=1),
  document_id text NOT NULL,
  document_hash text NOT NULL CHECK(document_hash ~ '^[0-9a-f]{64}$'),
  private_proof_hash text NOT NULL CHECK(private_proof_hash ~ '^[0-9a-f]{64}$'),
  public_proof_hash text NOT NULL CHECK(public_proof_hash ~ '^[0-9a-f]{64}$'),
  chunks_json jsonb NOT NULL CHECK(jsonb_typeof(chunks_json)='array' AND jsonb_array_length(chunks_json) BETWEEN 1 AND 16),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(private_evidence_id,user_id,epoch)
    REFERENCES rag_assessment_source_evidence(id,private_user_id,private_epoch) ON DELETE RESTRICT,
  FOREIGN KEY(corpus_id,document_id)
    REFERENCES grounding_corpus_documents(corpus_version_id,document_id) ON DELETE RESTRICT,
  CHECK(private_evidence_id<>public_evidence_id)
);
CREATE INDEX IF NOT EXISTS rag_actual_d_provenance_owner ON rag_actual_d_private_provenance(user_id,epoch);

CREATE OR REPLACE FUNCTION rag_actual_d_private_provenance_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p rag_assessment_source_evidence%ROWTYPE;
DECLARE carrier rag_assessment_source_evidence%ROWTYPE;
DECLARE q jsonb;
DECLARE original jsonb;
DECLARE part jsonb;
DECLARE frozen_generation bigint;
DECLARE clock timestamptz;
DECLARE expected_chunks jsonb;
BEGIN
  IF TG_OP='DELETE' THEN
    IF rag_actual_d_private_delete_allowed(OLD.private_evidence_id) THEN RETURN OLD; END IF;
    RAISE check_violation USING MESSAGE='private provenance requires original reset permit';
  END IF;
  IF TG_OP<>'INSERT' THEN RAISE check_violation USING MESSAGE='private provenance immutable'; END IF;
  -- Keep original corpus-before-proof ordering. No caller-chosen authority flag.
  PERFORM id FROM grounding_corpus_versions WHERE id=NEW.corpus_id AND state='published' FOR UPDATE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='private provenance corpus stale'; END IF;
  SELECT * INTO p FROM rag_assessment_source_evidence WHERE id=NEW.private_evidence_id FOR SHARE;
  SELECT * INTO carrier FROM rag_assessment_source_evidence WHERE id=NEW.public_evidence_id FOR SHARE;
  q := p.signed_proof->'payload'->'prepared';
  original := carrier.signed_proof->'payload'->'prepared';
  IF p.private_user_id IS DISTINCT FROM NEW.user_id OR p.private_epoch IS DISTINCT FROM NEW.epoch OR
     p.signed_proof->'payload'->>'format' IS DISTINCT FROM 'aearn.rag.actual-d-finite-source.v3' OR
     carrier.private_user_id IS NOT NULL OR
     (carrier.signed_proof->'payload'->>'format') IS NULL OR
     (carrier.signed_proof->'payload'->>'format') NOT IN ('aearn.rag.fresh-assessment-source.v1','aearn.rag.fresh-assessment-source.v2') OR
     carrier.id IS NULL OR p.revoked_at IS NOT NULL OR carrier.revoked_at IS NOT NULL OR
     (p.capture_id,p.source_handle,p.document_hash,p.policy_id,p.policy_generation,p.root_id,p.profile_id) IS DISTINCT FROM
       (carrier.capture_id,carrier.source_handle,carrier.document_hash,carrier.policy_id,carrier.policy_generation,carrier.root_id,carrier.profile_id) OR
     NEW.private_proof_hash IS DISTINCT FROM p.proof_hash OR NEW.public_proof_hash IS DISTINCT FROM carrier.proof_hash OR
     NEW.document_id IS DISTINCT FROM carrier.document_handle OR NEW.document_hash IS DISTINCT FROM p.document_hash OR
     q->'spans' IS DISTINCT FROM original->'spans' OR q->'demand'->>'purpose' IS DISTINCT FROM 'assessment_evidence' OR
     original->'demand'->>'purpose' IS DISTINCT FROM 'assessment_evidence' OR
     q->'demand'->'scope' IS DISTINCT FROM original->'demand'->'scope' OR
     (q->'actual_d'->'draft'->>'draft_id',q->'actual_d'->>'node_id',q->'actual_d'->>'goal_hash',q->'actual_d'->>'target_id') IS DISTINCT FROM
       (NEW.draft_id::text,NEW.node_id,NEW.goal_hash,NEW.target_id) THEN
    RAISE check_violation USING MESSAGE='private provenance signed coordinates mismatch';
  END IF;
  PERFORM rag_actual_d_private_epoch(NEW.user_id,NEW.epoch,true);
  IF NOT EXISTS (SELECT 1 FROM rag_source_claim_receipts c JOIN rag_source_admissions a ON a.id=c.admission_id
    JOIN rag_source_reviews r ON r.id=a.review_id WHERE c.assessment_evidence_id=p.id AND c.revoked_at IS NULL
    AND r.assessment_evidence_id=p.id AND a.active AND a.revoked_at IS NULL
    AND a.allowed_usages=ARRAY['assessment_evidence']::text[]) THEN
    RAISE check_violation USING MESSAGE='private provenance original claim missing';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM rag_corpus_admission_links l JOIN rag_source_admissions a ON a.id=l.admission_id
    JOIN rag_source_reviews r ON r.id=a.review_id WHERE l.corpus_id=NEW.corpus_id AND l.document_id=NEW.document_id
    AND r.assessment_evidence_id=carrier.id AND a.active AND a.revoked_at IS NULL
    AND a.allowed_usages=ARRAY['assessment_evidence']::text[]) THEN
    RAISE check_violation USING MESSAGE='private provenance public assessment carrier missing';
  END IF;
  FOR part IN SELECT value FROM jsonb_array_elements(NEW.chunks_json) LOOP
    IF jsonb_typeof(part)<>'object' OR NOT (part ?& ARRAY['chunk_id','chunk_hash']) OR
       (part-'chunk_id'-'chunk_hash')<>'{}'::jsonb OR NOT EXISTS (
       SELECT 1 FROM grounding_corpus_chunks c WHERE c.corpus_version_id=NEW.corpus_id AND c.document_id=NEW.document_id
         AND c.chunk_id=part->>'chunk_id' AND c.chunk_hash=part->>'chunk_hash'
         AND c.chunk_hash=encode(digest(c.content,'sha256'),'hex')) THEN
      RAISE check_violation USING MESSAGE='private provenance exact chunks mismatch';
    END IF;
  END LOOP;
  SELECT jsonb_agg(jsonb_build_object('chunk_id',chunk_id,'chunk_hash',chunk_hash) ORDER BY chunk_id)
    INTO expected_chunks FROM grounding_corpus_chunks
    WHERE corpus_version_id=NEW.corpus_id AND document_id=NEW.document_id;
  IF expected_chunks IS DISTINCT FROM NEW.chunks_json THEN
    RAISE check_violation USING MESSAGE='private provenance complete public chunk membership required';
  END IF;
  SELECT generation INTO frozen_generation FROM grounding_active_corpora WHERE corpus_version_id=NEW.corpus_id FOR SHARE;
  clock := clock_timestamp();
  IF frozen_generation IS DISTINCT FROM NEW.generation OR p.issued_at>clock OR carrier.issued_at>clock OR
    LEAST(p.expires_at,carrier.expires_at)<=clock THEN
    RAISE check_violation USING MESSAGE='private provenance final source or generation stale';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION rag_actual_d_private_provenance_guard() FROM PUBLIC;
DROP TRIGGER IF EXISTS rag_actual_d_private_provenance_guard ON rag_actual_d_private_provenance;
CREATE TRIGGER rag_actual_d_private_provenance_guard BEFORE INSERT OR UPDATE OR DELETE ON rag_actual_d_private_provenance
  FOR EACH ROW EXECUTE FUNCTION rag_actual_d_private_provenance_guard();
