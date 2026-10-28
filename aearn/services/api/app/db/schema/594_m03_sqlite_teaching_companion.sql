-- Exact M03 teaching companion. No rows, permissions, policy or active state seeded.
-- Only this table and two new functions; installed source guard gains one narrow branch.
DO $pin$
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR
    md5((SELECT prosrc FROM pg_proc WHERE oid='public.rag_source_review_guard()'::regprocedure))
       NOT IN ('698e295048bbe7806967fc7d2ef3c7f8','a736658e0cde5cab2905ede6a77f93ad') OR
    NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid='public.rag_source_review_guard()'::regprocedure
      AND pg_get_userbyid(proowner)='aearn_b1d_runtime_20261001' AND proacl IS NULL
      AND prosecdef=false AND proconfig IS NULL AND provolatile='v' AND proparallel='u' AND NOT proisstrict) THEN
   RAISE EXCEPTION 'M03 installed source guard pin mismatch' USING ERRCODE='23514';
 END IF;
END $pin$;
CREATE TABLE IF NOT EXISTS public.rag_m03_capture_teaching_authorizations (
 id uuid PRIMARY KEY,
 record_kind text NOT NULL CHECK(record_kind IN ('capture_use_grant','teaching_review_evidence')),
 profile text NOT NULL CHECK(profile='m03-sqlite-teaching-excerpts-v1'),
 target_id text NOT NULL CHECK(target_id='sqlite-predicate-order-v1'),
 target_definition_hash text NOT NULL CHECK(target_definition_hash='333d8108ac641f79580e5c36df2a41fe9cc1271853d536c4d735f97b535b7b54'),
 goal_hashes_json jsonb NOT NULL CHECK(goal_hashes_json='["c5326a6daa36d990d630cff9d11cbddeace25392e1302979390c609367414308","498ed84503add2a4ea6dcc104519163b1afacde666ee80d076ab85a92aec39d4"]'::jsonb),
 subject_id text NOT NULL DEFAULT 'route.sql' CHECK(subject_id='route.sql'),
 subject_version text NOT NULL DEFAULT '1.0' CHECK(subject_version='1.0'),
 source_handle text NOT NULL,
 capture_id uuid NOT NULL REFERENCES public.rag_registered_source_captures(id)
   CHECK(capture_id IN ('b7fced2a-ebfc-4905-b48e-3d3172d2313f','b4a6f08d-4512-4842-8cd6-86cb466f387f','1833499a-2f8a-46d4-a175-cafe93e1d4a4')),
 original_fetch_attempt_id uuid NOT NULL REFERENCES public.rag_registered_fetch_attempts(id),
 original_policy_id text NOT NULL,
 original_policy_generation integer NOT NULL,
 original_root_id text NOT NULL REFERENCES public.rag_budget_authority_roots(root_id),
 teaching_policy_id text NOT NULL,
 teaching_policy_generation integer NOT NULL CHECK(teaching_policy_generation>=1),
 teaching_root_id text NOT NULL REFERENCES public.rag_budget_authority_roots(root_id),
 document_hash text NOT NULL CHECK(document_hash ~ '^[0-9a-f]{64}$'),
 captured_bytes integer NOT NULL CHECK(captured_bytes>0),
 provenance_hash text NOT NULL CHECK(provenance_hash ~ '^[0-9a-f]{64}$'),
 active_anchor_corpus_id uuid NOT NULL CHECK(active_anchor_corpus_id='1f25a966-1ba1-53e9-acf6-e20dc168c435'),
 active_anchor_generation bigint NOT NULL CHECK(active_anchor_generation=5),
 active_anchor_activation_event_id uuid NOT NULL CHECK(active_anchor_activation_event_id='1a193fff-60ed-426d-8e6d-7231053cae56'),
 parent_grant_id uuid,
 parent_grant_digest text CHECK(parent_grant_digest ~ '^[0-9a-f]{64}$'),
 review_id uuid,
 admission_id uuid,
 document_handle text,
 companion_id uuid REFERENCES public.grounding_corpus_versions(id),
 signed_quality_json jsonb,
 quality_evidence_hash text CHECK(quality_evidence_hash ~ '^[0-9a-f]{64}$'),
 cohort_hash text CHECK(cohort_hash ~ '^[0-9a-f]{64}$'),
 issued_at timestamptz NOT NULL,
 valid_until timestamptz NOT NULL,
 issued_top_txid bigint NOT NULL,
 immutable_digest text NOT NULL CHECK(immutable_digest ~ '^[0-9a-f]{64}$'),
 UNIQUE(id,immutable_digest),
 FOREIGN KEY(parent_grant_id,parent_grant_digest) REFERENCES public.rag_m03_capture_teaching_authorizations(id,immutable_digest),
 FOREIGN KEY(original_policy_id,original_policy_generation) REFERENCES public.rag_registered_source_policies(policy_id,generation),
 FOREIGN KEY(teaching_policy_id,teaching_policy_generation) REFERENCES public.rag_registered_source_policies(policy_id,generation),
 CONSTRAINT m03_teaching_review_exact FOREIGN KEY(review_id,source_handle,document_handle,document_hash,subject_id,subject_version)
   REFERENCES public.rag_source_reviews(id,source_handle,document_handle,document_hash,subject_id,subject_version)
   DEFERRABLE INITIALLY DEFERRED,
 CONSTRAINT m03_teaching_admission_pair FOREIGN KEY(admission_id,review_id)
   REFERENCES public.rag_source_admissions(id,review_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(valid_until>issued_at),
 CHECK((record_kind='capture_use_grant' AND parent_grant_id IS NULL AND parent_grant_digest IS NULL
   AND review_id IS NULL AND admission_id IS NULL AND document_handle IS NULL AND companion_id IS NULL
   AND signed_quality_json IS NULL AND quality_evidence_hash IS NULL AND cohort_hash IS NULL)
 OR (record_kind='teaching_review_evidence' AND parent_grant_id IS NOT NULL AND parent_grant_digest IS NOT NULL
   AND review_id IS NOT NULL AND admission_id IS NOT NULL AND document_handle IS NOT NULL AND companion_id IS NOT NULL
   AND signed_quality_json IS NOT NULL AND jsonb_typeof(signed_quality_json)='object'
   AND octet_length(convert_to(signed_quality_json::text,'UTF8'))<=262144
   AND quality_evidence_hash IS NOT NULL AND cohort_hash IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS m03_teaching_grant_once ON public.rag_m03_capture_teaching_authorizations(capture_id,profile,target_id,active_anchor_corpus_id,active_anchor_generation)
 WHERE record_kind='capture_use_grant';
CREATE UNIQUE INDEX IF NOT EXISTS m03_teaching_evidence_once ON public.rag_m03_capture_teaching_authorizations(parent_grant_id)
 WHERE record_kind='teaching_review_evidence';
CREATE UNIQUE INDEX IF NOT EXISTS m03_teaching_review_once ON public.rag_m03_capture_teaching_authorizations(review_id)
 WHERE record_kind='teaching_review_evidence';
CREATE UNIQUE INDEX IF NOT EXISTS m03_teaching_admission_once ON public.rag_m03_capture_teaching_authorizations(admission_id)
 WHERE record_kind='teaching_review_evidence';

CREATE OR REPLACE FUNCTION public.enforce_rag_m03_capture_teaching_authorization() RETURNS trigger LANGUAGE plpgsql AS $guard$
DECLARE c public.rag_registered_source_captures%ROWTYPE;
 a public.rag_registered_fetch_attempts%ROWTYPE;
 op public.rag_registered_source_policies%ROWTYPE;
 tp public.rag_registered_source_policies%ROWTYPE;
 rt public.rag_budget_authority_roots%ROWTYPE;
 g public.rag_m03_capture_teaching_authorizations%ROWTYPE;
 v public.grounding_corpus_versions%ROWTYPE;
 stamp timestamptz;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'M03 teaching authorization append only' USING ERRCODE='23514'; END IF;
 IF TG_WHEN='AFTER' THEN
   -- Deferred closure is distinct from the BEFORE input audit: validation exists now.
   SELECT * INTO v FROM public.grounding_corpus_versions WHERE id=NEW.companion_id FOR SHARE;
   IF NOT FOUND OR v.state<>'validated' OR v.generation<>1 OR v.published_at IS NOT NULL OR
      v.coverage_policy_version<>'m03-sqlite-teaching-cohort-v1' OR
      NOT EXISTS(SELECT 1 FROM public.rag_corpus_validation_receipts vr JOIN public.grounding_corpus_events ve
        ON ve.id=vr.validation_event_id WHERE vr.corpus_id=v.id AND vr.summary_hash=v.summary_hash
        AND ve.corpus_version_id=v.id AND ve.summary_hash=v.summary_hash AND ve.event_kind='validation_passed') OR
      (SELECT count(DISTINCT capture_id) FROM public.rag_m03_capture_teaching_authorizations WHERE companion_id=v.id)<>3 OR
      (SELECT count(DISTINCT teaching_policy_generation) FROM public.rag_m03_capture_teaching_authorizations WHERE companion_id=v.id)<>1 OR
      (SELECT count(*) FROM public.rag_m03_capture_teaching_authorizations e WHERE e.companion_id=v.id
         AND e.record_kind='teaching_review_evidence' AND e.cohort_hash=NEW.cohort_hash
         AND e.signed_quality_json=NEW.signed_quality_json)<>3 OR
      NOT EXISTS(SELECT 1 FROM public.rag_corpus_admission_links l
        JOIN public.rag_source_reviews r ON r.id=NEW.review_id
        JOIN public.rag_source_admissions ad ON ad.id=NEW.admission_id AND ad.review_id=r.id
        JOIN public.grounding_corpus_documents d ON d.corpus_version_id=l.corpus_id AND d.document_id=l.document_id
        WHERE l.corpus_id=v.id AND l.admission_id=ad.id AND l.source_id=NEW.source_handle
          AND l.document_id=NEW.document_handle AND l.document_hash=NEW.document_hash
          AND d.document_hash=NEW.document_hash AND d.parse_status='parsed'
          AND r.quality_evidence_hash=NEW.quality_evidence_hash AND r.allowed_usages=ARRAY['main_teaching']::text[]
          AND ad.allowed_usages=r.allowed_usages AND ad.active AND ad.revoked_at IS NULL) OR
      NOT EXISTS(SELECT 1 FROM public.grounding_corpus_chunks ch WHERE ch.corpus_version_id=v.id
        AND ch.document_id=NEW.document_handle AND ch.document_hash=NEW.document_hash) THEN
     RAISE EXCEPTION 'M03 deferred teaching closure missing' USING ERRCODE='23514';
   END IF;
   -- Recheck current source identities/expiry below too, at deferred execution.
 ELSE
   NEW.issued_at:=clock_timestamp();
   NEW.issued_top_txid:=txid_current(); -- OUTER TOP, not a subtransaction xmin.
 END IF;
 SELECT * INTO c FROM public.rag_registered_source_captures WHERE id=NEW.capture_id FOR SHARE;
 SELECT * INTO a FROM public.rag_registered_fetch_attempts WHERE id=NEW.original_fetch_attempt_id FOR SHARE;
 SELECT * INTO op FROM public.rag_registered_source_policies WHERE policy_id=NEW.original_policy_id FOR SHARE;
 SELECT * INTO tp FROM public.rag_registered_source_policies WHERE policy_id=NEW.teaching_policy_id FOR SHARE;
 IF c.id IS NULL OR a.id IS NULL OR op.policy_id IS NULL OR tp.policy_id IS NULL OR
    c.fetch_attempt_id<>a.id OR c.policy_id<>op.policy_id OR c.generation<>op.generation OR
    op.generation<>NEW.original_policy_generation OR op.root_id<>NEW.original_root_id OR
    a.policy_id<>op.policy_id OR a.generation<>op.generation OR a.root_id<>op.root_id OR a.state<>'settled' OR
    a.response_sha256<>c.fetched_sha256 OR a.response_bytes<>c.captured_bytes OR
    c.cleared_at IS NOT NULL OR c.captured_body IS NULL OR c.fetched_sha256<>NEW.document_hash OR
    c.captured_bytes<>NEW.captured_bytes OR octet_length(c.captured_body)<>c.captured_bytes OR
    encode(digest(c.captured_body,'sha256'),'hex')<>c.fetched_sha256 OR
    c.evidence_level<>'live_egress_attested' OR c.provider_attempt_id IS NOT NULL OR
    c.transport_proof IS NULL OR c.attestor_key_sha256 IS NULL OR c.worker_image_sha256 IS NULL OR
    c.transport_proof_sha256<>NEW.provenance_hash OR
    encode(digest(c.transport_proof,'sha256'),'hex')<>NEW.provenance_hash OR
    c.final_url<>op.canonical_url OR c.request_chain<>jsonb_build_array(op.canonical_url) OR
    c.final_url IS DISTINCT FROM (CASE c.id
      WHEN 'b7fced2a-ebfc-4905-b48e-3d3172d2313f'::uuid THEN 'https://www.sqlite.org/lang_select.html'
      WHEN 'b4a6f08d-4512-4842-8cd6-86cb466f387f'::uuid THEN 'https://www.sqlite.org/lang_expr.html'
      WHEN '1833499a-2f8a-46d4-a175-cafe93e1d4a4'::uuid THEN 'https://www.sqlite.org/lang_corefunc.html' END) OR
    op.source_handle<>NEW.source_handle OR op.subject_id<>'route.sql' OR op.subject_version<>'1.0' OR
    op.facets<>ARRAY['queries']::text[] OR op.origin<>'official' OR op.reading_level<>'beginner' OR
    op.allowed_usages<>ARRAY['assessment_evidence']::text[] OR
    tp.policy_id=op.policy_id OR tp.generation<>NEW.teaching_policy_generation OR tp.root_id<>NEW.teaching_root_id OR
    tp.source_handle<>op.source_handle OR tp.subject_id<>op.subject_id OR tp.subject_version<>op.subject_version OR
    tp.facets<>op.facets OR tp.canonical_url<>op.canonical_url OR tp.license_id<>op.license_id OR
    tp.origin<>op.origin OR tp.reading_level<>op.reading_level OR
    tp.allowed_usages<>ARRAY['main_teaching']::text[] OR
    op.enabled IS NOT TRUE OR tp.enabled IS NOT TRUE OR op.revoked_at IS NOT NULL OR tp.revoked_at IS NOT NULL OR
    op.immutable_history_allowed IS NOT TRUE OR tp.immutable_history_allowed IS NOT TRUE OR
    op.canonical_url NOT IN ('https://www.sqlite.org/lang_select.html','https://www.sqlite.org/lang_expr.html','https://www.sqlite.org/lang_corefunc.html') THEN
   RAISE EXCEPTION 'M03 teaching source scope mismatch' USING ERRCODE='23514';
 END IF;
 FOR rt IN SELECT * FROM public.rag_budget_authority_roots WHERE root_id IN (op.root_id,tp.root_id) ORDER BY root_id FOR SHARE LOOP
   stamp:=clock_timestamp();
   IF (rt.root_id=op.root_id AND (rt.policy_id<>op.policy_id OR rt.policy_generation<>op.generation)) OR
      (rt.root_id=tp.root_id AND (rt.policy_id<>tp.policy_id OR rt.policy_generation<>tp.generation)) OR
      rt.enabled IS NOT TRUE OR rt.period_start>stamp OR rt.period_end<=stamp OR rt.delegation_expires_at<=stamp OR
      NEW.valid_until>least(rt.period_end,rt.delegation_expires_at) THEN
     RAISE EXCEPTION 'M03 teaching root stale' USING ERRCODE='23514';
   END IF;
 END LOOP;
 IF NEW.record_kind='teaching_review_evidence' THEN
   SELECT * INTO g FROM public.rag_m03_capture_teaching_authorizations WHERE id=NEW.parent_grant_id FOR SHARE;
   IF NOT FOUND OR g.record_kind<>'capture_use_grant' OR g.immutable_digest<>NEW.parent_grant_digest OR
      g.issued_top_txid=txid_current() OR g.valid_until<NEW.valid_until OR
      (to_jsonb(NEW)-ARRAY['id','record_kind','parent_grant_id','parent_grant_digest','review_id','admission_id','document_handle','companion_id','signed_quality_json','quality_evidence_hash','cohort_hash','issued_at','issued_top_txid','immutable_digest','valid_until'])
       IS DISTINCT FROM
      (to_jsonb(g)-ARRAY['id','record_kind','parent_grant_id','parent_grant_digest','review_id','admission_id','document_handle','companion_id','signed_quality_json','quality_evidence_hash','cohort_hash','issued_at','issued_top_txid','immutable_digest','valid_until']) THEN
     RAISE EXCEPTION 'M03 teaching parent not prior committed exact grant' USING ERRCODE='23514';
   END IF;
 END IF;
 SELECT * INTO v FROM public.grounding_corpus_versions WHERE id=NEW.active_anchor_corpus_id FOR SHARE;
 IF NOT FOUND OR v.state<>'published' OR
    NOT EXISTS(SELECT 1 FROM public.grounding_active_corpora ac WHERE ac.subject_id='route.sql'
       AND ac.corpus_version_id=NEW.active_anchor_corpus_id AND ac.generation=NEW.active_anchor_generation
       AND ac.activation_event_id=NEW.active_anchor_activation_event_id FOR SHARE) THEN
   RAISE EXCEPTION 'M03 teaching active anchor stale' USING ERRCODE='23514';
 END IF;
 stamp:=clock_timestamp();
 IF NEW.valid_until<=stamp OR NEW.valid_until>least(c.retention_until,op.retention_until,op.expires_at,tp.retention_until,tp.expires_at) THEN
   RAISE EXCEPTION 'M03 teaching source expiry' USING ERRCODE='23514';
 END IF;
 IF TG_WHEN='BEFORE' THEN
   NEW.immutable_digest:=encode(digest(convert_to((to_jsonb(NEW)-'immutable_digest')::text,'UTF8'),'sha256'),'hex');
 END IF;
 RETURN NEW;
END $guard$;
DO $triggers$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='public.rag_m03_capture_teaching_authorizations'::regclass AND tgname='m03_teaching_authorization_guard') THEN
CREATE TRIGGER m03_teaching_authorization_guard BEFORE INSERT OR UPDATE OR DELETE ON public.rag_m03_capture_teaching_authorizations
 FOR EACH ROW EXECUTE FUNCTION public.enforce_rag_m03_capture_teaching_authorization();
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='public.rag_m03_capture_teaching_authorizations'::regclass AND tgname='m03_teaching_evidence_closure') THEN
CREATE CONSTRAINT TRIGGER m03_teaching_evidence_closure AFTER INSERT ON public.rag_m03_capture_teaching_authorizations
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.record_kind='teaching_review_evidence')
 EXECUTE FUNCTION public.enforce_rag_m03_capture_teaching_authorization();
 END IF;
END $triggers$;

-- SQL does not authenticate Ed25519 or teaching truth. Concrete Python verifier
-- and this relation/current fence are both mandatory at the caller.
CREATE OR REPLACE FUNCTION public.rag_m03_teaching_companion_current(p jsonb) RETURNS boolean LANGUAGE plpgsql AS $current$
DECLARE v public.grounding_corpus_versions%ROWTYPE;
 vr public.rag_corpus_validation_receipts%ROWTYPE;
 e public.rag_m03_capture_teaching_authorizations%ROWTYPE;
 g public.rag_m03_capture_teaching_authorizations%ROWTYPE;
 c public.rag_registered_source_captures%ROWTYPE;
 op public.rag_registered_source_policies%ROWTYPE;
 tp public.rag_registered_source_policies%ROWTYPE;
 rt public.rag_budget_authority_roots%ROWTYPE;
 item jsonb; companion jsonb:=p->'companion'; anchor jsonb:=p->'active_anchor';
 seen uuid[]:='{}'; capsules jsonb; generation integer; stamp timestamptz; bound timestamptz:='infinity';
BEGIN
 IF jsonb_typeof(p)<>'object' OR jsonb_typeof(p->'evidence')<>'array' OR
    jsonb_array_length(p->'evidence')<3 OR jsonb_array_length(p->'evidence')>512 OR
    anchor->>'subject_id' IS DISTINCT FROM 'route.sql' OR
    anchor->>'corpus_id' IS DISTINCT FROM '1f25a966-1ba1-53e9-acf6-e20dc168c435' OR
    (anchor->>'generation')::bigint IS DISTINCT FROM 5 OR
    anchor->>'activation_event_id' IS DISTINCT FROM '1a193fff-60ed-426d-8e6d-7231053cae56' THEN RETURN false; END IF;
 -- Stable version order first, then immutable members, mutable source, pointer last.
 PERFORM 1 FROM public.grounding_corpus_versions WHERE id IN
   ((companion->>'corpus_id')::uuid,(anchor->>'corpus_id')::uuid) ORDER BY id FOR SHARE;
 SELECT * INTO v FROM public.grounding_corpus_versions WHERE id=(companion->>'corpus_id')::uuid;
 SELECT * INTO vr FROM public.rag_corpus_validation_receipts WHERE corpus_id=v.id FOR SHARE;
 IF v.id IS NULL OR vr.corpus_id IS NULL OR v.state<>'validated' OR v.generation<>1 OR v.published_at IS NOT NULL OR
    v.subject_id<>'route.sql' OR v.subject_version<>'1.0' OR
    v.coverage_policy_version<>'m03-sqlite-teaching-cohort-v1' OR
    v.generation IS DISTINCT FROM (companion->>'sealed_generation')::bigint OR
    v.summary_hash IS DISTINCT FROM companion->>'summary_hash' OR
    vr.summary_hash IS DISTINCT FROM v.summary_hash OR
    vr.validation_event_id IS DISTINCT FROM (companion->>'validation_event_id')::uuid OR
    v.registry_digest IS DISTINCT FROM companion->>'registry_digest' OR
    EXISTS(SELECT 1 FROM public.grounding_active_corpora WHERE corpus_version_id=v.id) OR
    NOT EXISTS(SELECT 1 FROM public.grounding_corpus_events ve WHERE ve.id=vr.validation_event_id
      AND ve.corpus_version_id=v.id AND ve.event_kind='validation_passed' AND ve.summary_hash=v.summary_hash) THEN RETURN false; END IF;
 -- Corpus summaries contain only bounded flat scalars; recreate sorted compact JSON.
 IF encode(digest(convert_to((SELECT '{' || string_agg(to_json(key)::text || ':' || value::text,',' ORDER BY key) || '}'
       FROM jsonb_each(v.validation_summary_json)),'UTF8'),'sha256'),'hex') IS DISTINCT FROM companion->>'validation_hash' OR
    encode(digest(convert_to((SELECT '{' || string_agg(to_json(key)::text || ':' || value::text,',' ORDER BY key) || '}'
       FROM jsonb_each(v.coverage_summary_json)),'UTF8'),'sha256'),'hex') IS DISTINCT FROM companion->>'coverage_hash' OR
    encode(digest(convert_to(to_json(v.retrieval_policy_version)::text,'UTF8'),'sha256'),'hex') IS DISTINCT FROM companion->>'retrieval_hash'
 THEN RETURN false; END IF;
 PERFORM 1 FROM public.rag_corpus_admission_links l
   JOIN public.grounding_corpus_documents d ON d.corpus_version_id=l.corpus_id AND d.document_id=l.document_id
   JOIN public.rag_source_admissions ad ON ad.id=l.admission_id
   JOIN public.rag_source_reviews r ON r.id=ad.review_id
   WHERE l.corpus_id=v.id ORDER BY l.document_id FOR SHARE OF l,d,ad,r;
 PERFORM 1 FROM public.grounding_corpus_chunks WHERE corpus_version_id=v.id ORDER BY chunk_id FOR SHARE;
 FOR item IN SELECT value FROM jsonb_array_elements(p->'evidence') ORDER BY value#>>'{teaching_authorization,id}' LOOP
   IF item->>'kind' IS DISTINCT FROM 'm03_teaching_companion_v1' OR item->'companion' IS DISTINCT FROM companion OR
      item->'active_anchor' IS DISTINCT FROM anchor OR item#>>'{binding,purpose}' IS DISTINCT FROM 'main_teaching' OR
      item#>>'{teaching_authorization,profile}' IS DISTINCT FROM 'm03-sqlite-teaching-excerpts-v1' THEN RETURN false; END IF;
   SELECT * INTO e FROM public.rag_m03_capture_teaching_authorizations
     WHERE id=(item#>>'{teaching_authorization,id}')::uuid FOR SHARE;
   IF NOT FOUND OR e.record_kind<>'teaching_review_evidence' OR e.companion_id<>v.id OR
      e.immutable_digest IS DISTINCT FROM item#>>'{teaching_authorization,exact_payload_digest}' OR
      e.capture_id IS DISTINCT FROM (item#>>'{source,capture_id}')::uuid OR
      e.original_fetch_attempt_id IS DISTINCT FROM (item#>>'{source,original_fetch_attempt_id}')::uuid OR
      e.original_policy_id IS DISTINCT FROM item#>>'{source,original_policy_id}' OR
      e.original_policy_generation IS DISTINCT FROM (item#>>'{source,original_policy_generation}')::integer OR
      e.original_root_id IS DISTINCT FROM item#>>'{source,original_root_id}' OR
      e.teaching_policy_id IS DISTINCT FROM item#>>'{source,teaching_policy_id}' OR
      e.teaching_policy_generation IS DISTINCT FROM (item#>>'{source,teaching_policy_generation}')::integer OR
      e.teaching_root_id IS DISTINCT FROM item#>>'{source,teaching_root_id}' OR
      e.review_id IS DISTINCT FROM (item#>>'{source,review_id}')::uuid OR
      e.admission_id IS DISTINCT FROM (item#>>'{source,admission_id}')::uuid OR
      e.quality_evidence_hash IS DISTINCT FROM item#>>'{source,quality_receipt_hash}' OR
      e.source_handle IS DISTINCT FROM item#>>'{binding,source_handle}' OR
      e.document_handle IS DISTINCT FROM item#>>'{binding,document_handle}' OR
      e.document_hash IS DISTINCT FROM item#>>'{binding,document_hash}' OR
      e.document_hash IS DISTINCT FROM item#>>'{binding,document_revision}' OR
      item#>>'{binding,scope,subject_id}' IS DISTINCT FROM 'route.sql' OR
      item#>>'{binding,scope,subject_version}' IS DISTINCT FROM '1.0' OR
      item#>'{binding,scope,facets}' IS DISTINCT FROM '["queries"]'::jsonb OR
      item#>>'{binding,claim_receipt_id}' IS NOT NULL OR
      e.target_id IS DISTINCT FROM item#>>'{goal,target_id}' OR
      e.target_definition_hash IS DISTINCT FROM item#>>'{goal,target_definition_hash}' OR
      NOT e.goal_hashes_json ? (item#>>'{goal,exact_server_goal_hash}') THEN RETURN false; END IF;
   SELECT * INTO g FROM public.rag_m03_capture_teaching_authorizations WHERE id=e.parent_grant_id FOR SHARE;
   IF NOT FOUND OR g.record_kind<>'capture_use_grant' OR g.issued_top_txid=txid_current() OR
      g.immutable_digest<>e.parent_grant_digest OR g.capture_id<>e.capture_id OR
      g.teaching_policy_id<>e.teaching_policy_id OR g.valid_until<e.valid_until THEN RETURN false; END IF;
   IF capsules IS NOT NULL AND capsules<>e.signed_quality_json THEN RETURN false; END IF;
   capsules:=e.signed_quality_json;
   IF generation IS NOT NULL AND generation<>e.teaching_policy_generation THEN RETURN false; END IF;
   generation:=e.teaching_policy_generation;
   SELECT * INTO c FROM public.rag_registered_source_captures WHERE id=e.capture_id FOR SHARE;
   SELECT * INTO op FROM public.rag_registered_source_policies WHERE policy_id=e.original_policy_id FOR SHARE;
   SELECT * INTO tp FROM public.rag_registered_source_policies WHERE policy_id=e.teaching_policy_id FOR SHARE;
   IF c.id IS NULL OR op.policy_id IS NULL OR tp.policy_id IS NULL OR c.cleared_at IS NOT NULL OR c.captured_body IS NULL OR
      c.policy_id<>op.policy_id OR c.generation<>op.generation OR op.generation<>e.original_policy_generation OR
      c.fetch_attempt_id<>e.original_fetch_attempt_id OR c.fetched_sha256<>e.document_hash OR
      encode(digest(c.captured_body,'sha256'),'hex')<>e.document_hash OR octet_length(c.captured_body)<>e.captured_bytes OR
      c.transport_proof_sha256<>e.provenance_hash OR encode(digest(c.transport_proof,'sha256'),'hex')<>e.provenance_hash OR
      tp.generation<>e.teaching_policy_generation OR tp.root_id<>e.teaching_root_id OR op.root_id<>e.original_root_id OR
      op.enabled IS NOT TRUE OR tp.enabled IS NOT TRUE OR op.revoked_at IS NOT NULL OR tp.revoked_at IS NOT NULL OR
      op.immutable_history_allowed IS NOT TRUE OR tp.immutable_history_allowed IS NOT TRUE OR
      tp.allowed_usages<>ARRAY['main_teaching']::text[] OR tp.source_handle<>e.source_handle OR
      tp.canonical_url<>op.canonical_url OR c.final_url<>op.canonical_url THEN RETURN false; END IF;
   bound:=least(bound,e.valid_until,g.valid_until,c.retention_until,op.retention_until,op.expires_at,tp.retention_until,tp.expires_at);
   FOR rt IN SELECT * FROM public.rag_budget_authority_roots WHERE root_id IN (op.root_id,tp.root_id) ORDER BY root_id FOR SHARE LOOP
     IF (rt.root_id=op.root_id AND (rt.policy_id<>op.policy_id OR rt.policy_generation<>op.generation)) OR
        (rt.root_id=tp.root_id AND (rt.policy_id<>tp.policy_id OR rt.policy_generation<>tp.generation)) OR
        rt.enabled IS NOT TRUE OR rt.period_start>clock_timestamp() THEN RETURN false; END IF;
     bound:=least(bound,rt.period_end,rt.delegation_expires_at);
   END LOOP;
   IF NOT EXISTS(SELECT 1 FROM public.rag_corpus_admission_links l
      JOIN public.rag_source_reviews r ON r.id=e.review_id
      JOIN public.rag_source_admissions ad ON ad.id=e.admission_id AND ad.review_id=r.id
      JOIN public.grounding_corpus_documents d ON d.corpus_version_id=l.corpus_id AND d.document_id=l.document_id
      JOIN public.grounding_corpus_chunks ch ON ch.corpus_version_id=d.corpus_version_id AND ch.document_id=d.document_id
      WHERE l.corpus_id=v.id AND l.admission_id=ad.id AND l.source_id=e.source_handle AND l.document_id=e.document_handle
        AND l.document_hash=e.document_hash AND d.document_hash=e.document_hash AND d.parse_status='parsed'
        AND r.registered_capture_id=e.capture_id AND r.source_handle=e.source_handle AND r.document_hash=e.document_hash
        AND r.policy_id=e.teaching_policy_id AND r.policy_generation=e.teaching_policy_generation AND r.root_id=e.teaching_root_id
        AND r.status='reviewed' AND r.quality_code='QUALIFIED' AND r.reading_fit='suitable' AND r.version_fit='current'
        AND r.technical_status='correct' AND r.conflict_status='resolved' AND r.known_error='absent'
        AND r.lineage_family='family.sqlite' AND r.quality_evidence_hash=e.quality_evidence_hash
        AND r.allowed_usages=ARRAY['main_teaching']::text[] AND ad.allowed_usages=r.allowed_usages
        AND ad.policy_generation=r.policy_generation AND ad.active AND ad.revoked_at IS NULL
        AND ad.receipt_handle=item#>>'{binding,admission_receipt_id}'
        AND ch.chunk_id=item#>>'{chunk,id}' AND ch.chunk_hash=item#>>'{chunk,hash}'
        AND ch.chunk_hash=item#>>'{chunk,approved_excerpt_hash}'
        AND encode(digest(convert_to(ch.content,'UTF8'),'sha256'),'hex')=ch.chunk_hash
        AND position(convert_to(ch.content,'UTF8') IN c.captured_body)>0 FOR SHARE OF l,r,ad,d,ch) THEN RETURN false; END IF;
   IF NOT e.id=ANY(seen) THEN seen:=array_append(seen,e.id); END IF;
 END LOOP;
 IF cardinality(seen)<>3 OR
    (SELECT count(*) FROM public.rag_m03_capture_teaching_authorizations WHERE companion_id=v.id)<>3 OR
    (SELECT count(DISTINCT capture_id) FROM public.rag_m03_capture_teaching_authorizations WHERE id=ANY(seen))<>3 OR
    (SELECT count(*) FROM public.rag_corpus_admission_links WHERE corpus_id=v.id)<>3 THEN RETURN false; END IF;
 PERFORM 1 FROM public.grounding_active_corpora ac WHERE ac.subject_id='route.sql'
   AND ac.corpus_version_id=(anchor->>'corpus_id')::uuid AND ac.generation=(anchor->>'generation')::bigint
   AND ac.activation_event_id=(anchor->>'activation_event_id')::uuid FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 stamp:=clock_timestamp();
 RETURN bound>stamp;
END $current$;

-- Original installed body retained, including SQL503 deletion exception.
CREATE OR REPLACE FUNCTION public.rag_source_review_guard() RETURNS trigger LANGUAGE plpgsql AS $review$
DECLARE original_hash text;
DECLARE policy_row rag_registered_source_policies%ROWTYPE;
DECLARE teaching public.rag_m03_capture_teaching_authorizations%ROWTYPE;
BEGIN
  --503 conditional private deletion
  IF TG_OP='DELETE' THEN
    IF rag_actual_d_private_delete_allowed(OLD.assessment_evidence_id) THEN RETURN OLD; END IF;
  END IF;
  IF TG_OP<>'INSERT' THEN
    RAISE EXCEPTION 'source review immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.registered_capture_id IS NOT NULL THEN
    SELECT capture.fetched_sha256 INTO original_hash
      FROM rag_registered_source_captures capture
      WHERE capture.id=NEW.registered_capture_id AND capture.cleared_at IS NULL
        AND capture.captured_body IS NOT NULL;
    SELECT e.* INTO teaching FROM public.rag_m03_capture_teaching_authorizations e
      JOIN public.rag_m03_capture_teaching_authorizations g ON g.id=e.parent_grant_id
      WHERE e.record_kind='teaching_review_evidence' AND g.record_kind='capture_use_grant'
        AND g.issued_top_txid<>txid_current() AND g.immutable_digest=e.parent_grant_digest
        AND e.review_id=NEW.id AND e.capture_id=NEW.registered_capture_id
        AND e.source_handle=NEW.source_handle AND e.document_handle=NEW.document_handle
        AND e.document_hash=NEW.document_hash AND e.subject_id=NEW.subject_id AND e.subject_version=NEW.subject_version
        AND e.teaching_policy_id=NEW.policy_id AND e.teaching_policy_generation=NEW.policy_generation
        AND e.teaching_root_id=NEW.root_id AND e.quality_evidence_hash=NEW.quality_evidence_hash
        AND least(e.valid_until,g.valid_until)>clock_timestamp()
        AND NEW.assessment_evidence_id IS NULL AND NEW.candidate_capture_id IS NULL
        AND NEW.allowed_usages=ARRAY['main_teaching']::text[] AND NEW.status='reviewed'
        AND NEW.quality_code='QUALIFIED' AND NEW.reading_fit='suitable' AND NEW.version_fit='current'
        AND NEW.technical_status='correct' AND NEW.conflict_status='resolved' AND NEW.known_error='absent'
        AND NEW.covered_facets=ARRAY['queries']::text[] AND NEW.facets=ARRAY['queries']::text[]
        AND NEW.lineage_family='family.sqlite' AND NEW.immutable_history_allowed
        AND NEW.document_revision=NEW.document_hash
        AND NEW.storage_receipt_id='storage.m03.' || e.id::text
        AND NEW.review_receipt_hash=e.quality_evidence_hash FOR SHARE OF e,g;
    IF FOUND THEN
      SELECT * INTO policy_row FROM rag_registered_source_policies WHERE policy_id=teaching.teaching_policy_id FOR SHARE;
    ELSE
    SELECT policy.* INTO policy_row FROM rag_registered_source_policies policy
      JOIN rag_registered_source_captures capture ON capture.policy_id=policy.policy_id
        AND capture.generation=policy.generation
      WHERE capture.id=NEW.registered_capture_id;
    END IF;
    IF policy_row.policy_id IS NULL OR NEW.source_handle<>policy_row.source_handle OR
       NEW.subject_id<>policy_row.subject_id OR
       NEW.subject_version<>policy_row.subject_version OR
       NOT NEW.facets <@ policy_row.facets OR
       NEW.origin<>policy_row.origin OR NEW.reading_level<>policy_row.reading_level OR
       NEW.license_id<>policy_row.license_id OR
       NEW.policy_id<>policy_row.policy_id OR
       NEW.policy_generation<>policy_row.generation OR
       NEW.root_id<>policy_row.root_id OR
       NOT NEW.allowed_usages <@ policy_row.allowed_usages OR
       (NEW.immutable_history_allowed AND NOT policy_row.immutable_history_allowed) OR
       (NEW.status='reviewed' AND (policy_row.enabled IS NOT TRUE OR
            policy_row.revoked_at IS NOT NULL OR policy_row.expires_at<=clock_timestamp())) THEN
      RAISE EXCEPTION 'review source scope or permission mismatch' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT full_sha256 INTO original_hash FROM rag_candidate_captures
      WHERE id=NEW.candidate_capture_id AND capture_kind='full' AND cleared_at IS NULL;
  END IF;
  IF original_hash IS NULL OR original_hash<>NEW.document_hash THEN
    RAISE EXCEPTION 'review document hash mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $review$;
