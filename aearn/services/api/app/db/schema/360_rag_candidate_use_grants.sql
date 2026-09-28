-- C explicit formal-use grant for a B full capture. No grants are seeded by bootstrap.
-- B temporary store permission alone is never permanent corpus-history approval.
CREATE TABLE IF NOT EXISTS rag_candidate_use_grants (
  capture_id uuid PRIMARY KEY REFERENCES rag_candidate_captures(id) ON DELETE RESTRICT,
  capture_sha256 text NOT NULL CHECK (capture_sha256 ~ '^[0-9a-f]{64}$'),
  policy_id text NOT NULL REFERENCES rag_candidate_access_policies(policy_id) ON DELETE RESTRICT,
  policy_generation integer NOT NULL CHECK (policy_generation >= 1),
  root_id text NOT NULL REFERENCES rag_budget_authority_roots(root_id) ON DELETE RESTRICT,
  license_id text NOT NULL CHECK (license_id ~ '^[A-Za-z0-9][A-Za-z0-9.-]{0,79}$'),
  source_handle text NOT NULL CHECK (source_handle ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  subject_id text NOT NULL,
  subject_version text NOT NULL,
  facets text[] NOT NULL CHECK (cardinality(facets) BETWEEN 1 AND 24),
  origin text NOT NULL CHECK (origin IN ('official','maintainer','tutorial','repository','community','blog')),
  reading_level text NOT NULL CHECK (reading_level IN ('beginner','intermediate','advanced')),
  allowed_usages text[] NOT NULL DEFAULT '{}' CHECK (cardinality(allowed_usages) BETWEEN 1 AND 2
    AND allowed_usages <@ ARRAY['main_teaching','supplementary_explanation']::text[]),
  immutable_history_allowed boolean NOT NULL DEFAULT false,
  retained_until timestamptz NOT NULL,
  storage_receipt_id text NOT NULL UNIQUE CHECK (storage_receipt_id ~ '^[a-z][a-z0-9._:-]{2,159}$'),
  approval_ref text NOT NULL CHECK (char_length(approval_ref) BETWEEN 16 AND 256
    AND approval_ref ~ '^[A-Za-z0-9 ._:/+-]+$'),
  active boolean NOT NULL DEFAULT false,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (revoked_at IS NULL OR NOT active),
  CHECK (NOT active OR immutable_history_allowed)
);
CREATE OR REPLACE FUNCTION rag_candidate_use_grant_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR OLD.revoked_at IS NOT NULL OR OLD.active IS NOT TRUE OR
     NEW.active IS NOT FALSE OR NEW.revoked_at IS NULL OR
     (to_jsonb(NEW)-'active'-'revoked_at') IS DISTINCT FROM
       (to_jsonb(OLD)-'active'-'revoked_at') THEN
    RAISE EXCEPTION 'candidate formal-use grant immutable or revoked' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_rag_candidate_use_grant_guard ON rag_candidate_use_grants;
CREATE TRIGGER trg_rag_candidate_use_grant_guard BEFORE UPDATE OR DELETE ON rag_candidate_use_grants
  FOR EACH ROW EXECUTE FUNCTION rag_candidate_use_grant_guard();
-- A direct link writer must not treat B's temporary storage rule as a formal
-- history grant. Keep the registered path unchanged and add exact B binding.
CREATE OR REPLACE FUNCTION rag_corpus_link_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE review_row rag_source_reviews%ROWTYPE;
DECLARE registered_policy rag_registered_source_policies%ROWTYPE;
DECLARE formal_grant rag_candidate_use_grants%ROWTYPE;
BEGIN
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'corpus admission link immutable' USING ERRCODE='23514';
  END IF;
  SELECT review.* INTO review_row FROM rag_source_reviews review
    JOIN rag_source_admissions admission ON admission.review_id=review.id
    WHERE admission.id=NEW.admission_id AND admission.active FOR SHARE OF review,admission;
  IF NOT FOUND OR NOT review_row.immutable_history_allowed OR
     review_row.document_hash<>NEW.document_hash THEN
    RAISE EXCEPTION 'corpus content retention not admitted' USING ERRCODE='23514';
  END IF;
  IF review_row.registered_capture_id IS NOT NULL THEN
    SELECT * INTO registered_policy FROM rag_registered_source_policies
      WHERE policy_id=review_row.policy_id FOR SHARE;
    IF registered_policy.policy_id IS NULL OR
       registered_policy.generation<>review_row.policy_generation OR
       registered_policy.immutable_history_allowed IS NOT TRUE OR
       registered_policy.enabled IS NOT TRUE OR
       registered_policy.revoked_at IS NOT NULL THEN
      RAISE EXCEPTION 'registered formal history grant missing' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT * INTO formal_grant FROM rag_candidate_use_grants
      WHERE capture_id=review_row.candidate_capture_id FOR SHARE;
    IF formal_grant.capture_id IS NULL OR formal_grant.active IS NOT TRUE OR
       formal_grant.revoked_at IS NOT NULL OR
       formal_grant.immutable_history_allowed IS NOT TRUE OR
       formal_grant.capture_sha256<>review_row.document_hash OR
       formal_grant.policy_id<>review_row.policy_id OR
       formal_grant.policy_generation<>review_row.policy_generation OR
       formal_grant.root_id<>review_row.root_id OR
       formal_grant.source_handle<>review_row.source_handle OR
       formal_grant.subject_id<>review_row.subject_id OR
       formal_grant.subject_version<>review_row.subject_version OR
       NOT review_row.facets <@ formal_grant.facets OR
       NOT review_row.allowed_usages <@ formal_grant.allowed_usages OR
       formal_grant.retained_until<=clock_timestamp() THEN
      RAISE EXCEPTION 'candidate formal history grant missing' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
