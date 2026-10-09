-- Private native finite content/relation/eligibility audit; issuer is the concrete
-- same-connection process owner, never a restored JSON capability. No502 forward FK.
CREATE TABLE IF NOT EXISTS tutor_item_supply_native_content_facts (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 epoch bigint NOT NULL CHECK(epoch>=1), version_id uuid NOT NULL,
 proof_id uuid NOT NULL REFERENCES tutor_learning_item_native_publication_proofs(id) ON DELETE RESTRICT,
 proof_hash text NOT NULL CHECK(proof_hash ~ '^[0-9a-f]{64}$'),
 content_json jsonb NOT NULL CHECK(jsonb_typeof(content_json)='object' AND octet_length(content_json::text)<=16384),
 content_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(content_json)) STORED,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(user_id,epoch,version_id,proof_id), UNIQUE(id,user_id,epoch),
 FOREIGN KEY(user_id) REFERENCES tutor_item_supply_user_epochs(user_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_native_relation_preparations (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 epoch bigint NOT NULL CHECK(epoch>=1), mapping_receipt_id uuid NOT NULL,
 anchor_version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
 root_id uuid NOT NULL, job_id uuid NOT NULL,
 reservation_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_reservations(id) ON DELETE RESTRICT,
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=262144),
 payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 checked_at timestamptz NOT NULL, valid_until timestamptz NOT NULL CHECK(valid_until>checked_at),
 evidence_valid_until timestamptz NOT NULL CHECK(evidence_valid_until>checked_at AND evidence_valid_until<=checked_at+interval '7 days'),
 UNIQUE(id,user_id,epoch),
 FOREIGN KEY(mapping_receipt_id,user_id,epoch) REFERENCES tutor_item_supply_finite_course_mappings(id,user_id,epoch) ON DELETE RESTRICT,
 FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_native_relation_batches (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 epoch bigint NOT NULL CHECK(epoch>=1), mapping_receipt_id uuid NOT NULL,
 preparation_id uuid NOT NULL UNIQUE, root_id uuid NOT NULL, job_id uuid NOT NULL,
 reservation_id uuid NOT NULL REFERENCES tutor_item_supply_shared_reservations(id) ON DELETE RESTRICT,
 request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
 payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576),
 payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 checked_at timestamptz NOT NULL, valid_until timestamptz NOT NULL CHECK(valid_until>checked_at),
 UNIQUE(id,user_id,epoch),
 FOREIGN KEY(mapping_receipt_id,user_id,epoch) REFERENCES tutor_item_supply_finite_course_mappings(id,user_id,epoch) ON DELETE RESTRICT,
 FOREIGN KEY(preparation_id,user_id,epoch) REFERENCES tutor_item_supply_native_relation_preparations(id,user_id,epoch) ON DELETE RESTRICT,
 FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_native_eligibility (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 epoch bigint NOT NULL CHECK(epoch>=1), mapping_receipt_id uuid NOT NULL,
 exposure_snapshot_id uuid NOT NULL, -- explicit502 owner verifies; NO forward FK
 request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
 inputs_hash text NOT NULL CHECK(inputs_hash ~ '^[0-9a-f]{64}$'),
 snapshot_json jsonb NOT NULL CHECK(jsonb_typeof(snapshot_json)='object' AND octet_length(snapshot_json::text)<=2097152
   AND snapshot_json->>'schema_version'='pack_snapshot_v2'),
 snapshot_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(snapshot_json)) STORED,
 candidate_version_ids uuid[] NOT NULL CHECK(cardinality(candidate_version_ids) BETWEEN 5 AND 16),
 relation_receipt_ids uuid[] NOT NULL CHECK(cardinality(relation_receipt_ids) BETWEEN 1 AND 16),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 checked_at timestamptz NOT NULL, valid_until timestamptz NOT NULL CHECK(valid_until>checked_at),
 txid bigint NOT NULL CHECK(txid>0), UNIQUE(id,user_id,epoch),
 FOREIGN KEY(mapping_receipt_id,user_id,epoch) REFERENCES tutor_item_supply_finite_course_mappings(id,user_id,epoch) ON DELETE RESTRICT
);

-- UUIDv5 must match the process-owned operational identity, not caller author IDs.
CREATE OR REPLACE FUNCTION item_supply_internal.native_type_actor(identity text) RETURNS uuid
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE h bytea;
BEGIN
 h:=substring(digest(decode('6ba7b8119dad11d180b400c04fd430c8','hex')||
   convert_to('aearn:item-author:'||identity,'UTF8'),'sha1') FROM 1 FOR 16);
 h:=set_byte(h,6,(get_byte(h,6)&15)|80);
 h:=set_byte(h,8,(get_byte(h,8)&63)|128);
 RETURN encode(h,'hex')::uuid;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.native_type_actor(text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_native_type_evidence_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE original record; mapping record; prep record; control record; settlement record;
 p jsonb; spec jsonb; semantics jsonb; c jsonb; report jsonb; pair jsonb; actor text; kind text;
 profile text; fixture text; stamp timestamptz; execution_deadline timestamptz; actors text[] := ARRAY[]::text[];
 roles text[] := ARRAY[]::text[]; covered text[]; r uuid;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed' THEN
   RAISE check_violation USING MESSAGE='native type evidence requires B1d read committed';
 END IF;
 PERFORM item_supply_internal.native_exposure_lock(NEW.user_id,NEW.epoch);
 IF TG_TABLE_NAME='tutor_item_supply_native_content_facts' THEN
   SELECT n.*,f.payload_json AS facts,p.payload_json AS preparation,g.source_json,
     r.payload_json AS review_json INTO original
   FROM tutor_learning_item_native_publication_proofs n
   JOIN tutor_item_supply_shared_admission_facts f ON f.id=n.facts_receipt_id
   JOIN tutor_item_supply_shared_validation_preparations p ON p.id=f.validation_preparation_id
   JOIN tutor_item_supply_shared_pipeline_receipts r ON r.id=f.review_receipt_id
   JOIN tutor_item_supply_shared_generation_artifacts g ON g.id=n.generation_artifact_id
   WHERE n.id=NEW.proof_id FOR SHARE OF n,f,p,g,r;
   IF NOT FOUND OR original.version_id<>NEW.version_id OR original.proof_hash<>NEW.proof_hash THEN
     RAISE check_violation USING MESSAGE='native content requires exact original publication';
   END IF;
   spec:=original.preparation->'spec'; c:=NEW.content_json;
   profile:=CASE spec->>'target_id' WHEN 'python-state-update-v1' THEN 'python'
     WHEN 'sqlite-predicate-order-v1' THEN 'sqlite' WHEN 'python-kc-binding-v1' THEN 'kc' ELSE NULL END;
   kind:=CASE profile WHEN 'python' THEN spec->'python_goal'->>'task_kind'
     WHEN 'sqlite' THEN spec->'sql_target'->>'task_kind'
     WHEN 'kc' THEN split_part(spec->'allocation'->>'family_id',':',2) ELSE NULL END;
   IF profile IS NULL OR kind IS NULL OR kind NOT IN ('accumulate','refresh','swap','transfer',
       'conjunction','override_fallback','exclusive','keyset_after','trace','diagnose','repair','counterexample') THEN
     RAISE check_violation USING MESSAGE='native content finite semantic profile missing';
   END IF;
   -- Task shape is previously checked by492/493/494, not accepted from a caller
   -- label. Normalization deliberately removes cosmetic seed/names/options.
   semantics:=jsonb_build_object('version','native-finite-semantic-v1','profile',profile,'decision',kind);
   fixture:=CASE profile WHEN 'kc' THEN original.preparation->'inputs'->'static_facts'->>'instance_hash'
     ELSE original.preparation->'inputs'->'probe_plan'->>'server_fixture_hash' END;
   IF NOT item_supply_internal.snapshot_keys(c,ARRAY['item_handle','version_id','content_hash',
       'actual_public_task_hash','actual_fixture_hash','decision_signature','answer_leakage_signature','author_id'])
     OR (c->>'item_handle',c->>'version_id',c->>'content_hash',c->>'actual_public_task_hash',c->>'actual_fixture_hash')
       IS DISTINCT FROM (original.proof_json->>'item_handle',NEW.version_id::text,
         original.proof_json->>'content_hash',original.facts->>'public_task_hash',fixture)
     OR c->>'decision_signature' IS DISTINCT FROM item_supply_internal.snapshot_hash(
       jsonb_build_object('domain','decision','semantics',semantics))
     OR c->>'answer_leakage_signature' IS DISTINCT FROM item_supply_internal.snapshot_hash(
       jsonb_build_object('domain','contextual-solution','semantics',semantics))
     OR (c->>'author_id')::uuid IS DISTINCT FROM item_supply_internal.native_type_actor(original.review_json->>'author_identity') THEN
     RAISE check_violation USING MESSAGE='native content immutable semantic fingerprint mismatch';
   END IF;
   RETURN NEW;
 END IF;
 SELECT * INTO mapping FROM tutor_item_supply_finite_course_mappings
   WHERE id=NEW.mapping_receipt_id AND user_id=NEW.user_id AND epoch=NEW.epoch FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='native type mapping owner mismatch'; END IF;
 stamp:=clock_timestamp();
 IF NEW.checked_at>stamp OR NEW.valid_until<=stamp OR NEW.checked_at>=NEW.valid_until THEN
   RAISE check_violation USING MESSAGE='native type deadline invalid';
 END IF;
 IF TG_TABLE_NAME='tutor_item_supply_native_eligibility' THEN
   p:=NEW.snapshot_json;
   IF NEW.txid<>txid_current() OR NEW.request_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(mapping.receipt_json->'pack_request')
     OR p->'request' IS DISTINCT FROM mapping.receipt_json->'pack_request'
     OR p->>'inputs_hash' IS DISTINCT FROM NEW.inputs_hash OR jsonb_array_length(p->'selected')<>5
     OR (p->>'checked_at')::timestamptz IS DISTINCT FROM NEW.checked_at
     OR (p->>'valid_until')::timestamptz IS DISTINCT FROM NEW.valid_until THEN
     RAISE check_violation USING MESSAGE='native eligibility exact request transaction mismatch';
   END IF;
   FOR c IN SELECT value FROM jsonb_array_elements(p->'selected') LOOP
     PERFORM 1 FROM tutor_item_supply_native_content_facts f
       JOIN tutor_learning_item_native_publication_proofs n ON n.id=f.proof_id
       WHERE f.user_id=NEW.user_id AND f.epoch=NEW.epoch AND f.version_id=(c->>'version_id')::uuid
         AND f.version_id=ANY(NEW.candidate_version_ids) AND f.proof_id=(c->>'proof_id')::uuid
         AND n.proof_hash=f.proof_hash AND f.content_json=c->'type_evidence'->'content';
     IF NOT FOUND THEN RAISE check_violation USING MESSAGE='native eligibility original content missing'; END IF;
     IF NOT EXISTS(SELECT 1 FROM tutor_learning_item_publication_events e
       WHERE e.version_id=(c->>'version_id')::uuid AND e.id=(c->>'publication_id')::uuid AND e.state='published'
       AND NOT EXISTS(SELECT 1 FROM tutor_learning_item_publication_events later
         WHERE later.version_id=e.version_id AND later.state_version>e.state_version)) THEN
       RAISE check_violation USING MESSAGE='native eligibility current publication missing';
     END IF;
   END LOOP;
   FOREACH r IN ARRAY NEW.relation_receipt_ids LOOP
     PERFORM 1 FROM tutor_item_supply_native_relation_batches b WHERE b.id=r AND b.user_id=NEW.user_id
       AND b.epoch=NEW.epoch AND b.mapping_receipt_id=NEW.mapping_receipt_id AND b.request_hash=NEW.request_hash
       AND b.valid_until>=NEW.valid_until;
     IF NOT FOUND THEN RAISE check_violation USING MESSAGE='native eligibility original relation missing'; END IF;
   END LOOP;
   -- Exposure complete/current/source/runtime recheck is by502 concrete owner and
   -- require_pack, NOT a digest that pretends to be a source grant.
   RETURN NEW;
 END IF;
 execution_deadline:=NEW.valid_until;
 IF TG_TABLE_NAME='tutor_item_supply_native_relation_batches' THEN
   SELECT * INTO prep FROM tutor_item_supply_native_relation_preparations
     WHERE id=NEW.preparation_id AND user_id=NEW.user_id AND epoch=NEW.epoch FOR SHARE;
   IF NOT FOUND OR (NEW.root_id,NEW.job_id,NEW.reservation_id,NEW.mapping_receipt_id)
       IS DISTINCT FROM (prep.root_id,prep.job_id,prep.reservation_id,prep.mapping_receipt_id)
       OR NEW.valid_until IS DISTINCT FROM prep.evidence_valid_until OR prep.valid_until<=stamp
       OR NEW.request_hash IS DISTINCT FROM prep.payload_json->>'request_hash'
       OR NEW.payload_json->'pairs' IS DISTINCT FROM prep.payload_json->'pairs'
       OR NEW.payload_json->'contents' IS DISTINCT FROM prep.payload_json->'contents' THEN
     RAISE check_violation USING MESSAGE='native relation batch original preparation mismatch';
   END IF;
   p:=prep.payload_json;
   execution_deadline:=prep.valid_until;
   SELECT s.*,s.xmin::text::bigint AS insertion_xid INTO settlement FROM tutor_item_supply_shared_runtime_settlements s
     WHERE reservation_id=NEW.reservation_id AND settlement_key='native.relation.'||replace(NEW.preparation_id::text,'-','');
   IF NOT FOUND OR settlement.usage_state<>'unknown' OR settlement.insertion_xid=(txid_current()%4294967296) THEN
     RAISE check_violation USING MESSAGE='native relation committed honest settlement required';
   END IF;
   IF jsonb_array_length(NEW.payload_json->'reports')<>4 THEN
     RAISE check_violation USING MESSAGE='native relation four reports required';
   END IF;
   FOR report IN SELECT value FROM jsonb_array_elements(NEW.payload_json->'reports') LOOP
     actor:=report->>'actor_id'; roles:=array_append(roles,report->>'role'); actors:=array_append(actors,actor);
     IF (actor)::uuid IS DISTINCT FROM item_supply_internal.native_type_actor(p->'identities'->(report->>'role')->>'identity')
       OR report->'run'->'provider_identity' IS DISTINCT FROM p->'identities'->(report->>'role')
       OR report->'run'->>'profile_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_hash'
       OR report->'run'->>'prompt_version' IS DISTINCT FROM 'native-content-relation-v1'
       OR (report->>'valid_until')::timestamptz<>NEW.valid_until
       OR (report->>'checked_at')::timestamptz>stamp
       OR (report->>'checked_at')::timestamptz>=(report->>'valid_until')::timestamptz
       OR jsonb_array_length(report->'judgments')<>jsonb_array_length(p->'pairs') THEN
       RAISE check_violation USING MESSAGE='native relation provider profile or coverage mismatch';
     END IF;
     FOR pair IN SELECT value FROM jsonb_array_elements(p->'pairs') LOOP
       IF (SELECT count(*) FROM jsonb_array_elements(report->'judgments') j
         WHERE j->>'binding_hash'=pair->>'binding_hash'
           AND j->>'conclusion' IN ('nonredundant','conflict','uncertain')
           AND j->>'rationale_evidence_hash' ~ '^[0-9a-f]{64}$')<>1 THEN
         RAISE check_violation USING MESSAGE='native relation exact pair verdict missing';
       END IF;
     END LOOP;
     IF EXISTS(SELECT 1 FROM jsonb_array_elements(p->'contents') c WHERE c->>'author_id'=actor) THEN
       RAISE check_violation USING MESSAGE='native relation author separation missing';
     END IF;
   END LOOP;
   IF (SELECT count(DISTINCT x) FROM unnest(actors) x)<>4
     OR (SELECT array_agg(x ORDER BY x) FROM unnest(roles) x) IS DISTINCT FROM
       ARRAY['adversarial','ambiguity','curriculum','technical']::text[] THEN
     RAISE check_violation USING MESSAGE='native relation independent responsibilities missing';
   END IF;
 ELSE
   p:=NEW.payload_json;
   IF (p->>'evidence_valid_until')::timestamptz IS DISTINCT FROM NEW.evidence_valid_until
     OR NEW.evidence_valid_until>NEW.checked_at+interval '7 days'
     OR NEW.evidence_valid_until>ANY(ARRAY(SELECT (d->>'valid_until')::timestamptz FROM jsonb_array_elements(p->'source_deadlines') d))
     OR jsonb_array_length(p->'source_deadlines')<>jsonb_array_length(p->'contents')
     OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'source_deadlines') d WHERE d->>'valid_until' IS NULL) THEN
     RAISE check_violation USING MESSAGE='native relation frozen evidence deadline mismatch';
   END IF;
   PERFORM 1 FROM tutor_learning_item_native_publication_proofs n
     WHERE n.version_id=NEW.anchor_version_id AND n.proof_json->'lease'=p->'lease'
       AND (n.proof_json->'lease'->>'job_id')::uuid=NEW.job_id;
   IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p->'contents') c
       WHERE c->>'version_id'=NEW.anchor_version_id::text)
       OR p->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(mapping.receipt_json->'pack_request') THEN
     RAISE check_violation USING MESSAGE='native relation genuine original published anchor required';
   END IF;
   PERFORM 1 FROM tutor_item_supply_shared_reservations r WHERE r.id=NEW.reservation_id
     AND r.job_id=NEW.job_id AND r.root_id=NEW.root_id AND r.lease_generation=(p->'lease'->>'generation')::integer;
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='native relation original reservation missing'; END IF;
 END IF;
 SELECT * INTO control FROM tutor_item_supply_shared_job_controls WHERE job_id=NEW.job_id FOR SHARE;
 stamp:=clock_timestamp();
 IF NOT FOUND OR control.state<>'leased' OR control.lease_owner IS DISTINCT FROM p->'lease'->>'lease_owner'
   OR control.lease_generation::text IS DISTINCT FROM p->'lease'->>'generation'
   OR control.state_version::text IS DISTINCT FROM p->'lease'->>'state_version'
   OR control.lease_expires_at<=stamp OR control.parent_deadline<=stamp
   OR execution_deadline>LEAST(control.lease_expires_at,control.parent_deadline)
   OR execution_deadline<=stamp
   OR p->'lease'->'profile' IS DISTINCT FROM (CASE
     WHEN control.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
     THEN control.profile_snapshot_json->'profile' ELSE control.profile_snapshot_json END) THEN
   RAISE check_violation USING MESSAGE='native relation original current lease missing';
 END IF;
 RETURN NEW;
END $$;

-- Lexical AFTER trigger topology is executable:502 a01 removes its children,
--501 a02 removes eligibility -> relation batches -> preparations -> content,
--then original496 finite_course_mapping and495 native_exposure parents may purge.
-- No second reset entry point, no permit bypass, no edits to protected old bytes.
CREATE OR REPLACE FUNCTION item_supply_internal.purge_native_type_evidence_on_epoch_advance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.epoch IS DISTINCT FROM OLD.epoch+1
   OR item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='native type reset requires original permitted epoch advance';
 END IF;
 DELETE FROM tutor_item_supply_native_eligibility WHERE user_id=NEW.user_id;
 DELETE FROM tutor_item_supply_native_relation_batches WHERE user_id=NEW.user_id;
 DELETE FROM tutor_item_supply_native_relation_preparations WHERE user_id=NEW.user_id;
 DELETE FROM tutor_item_supply_native_content_facts WHERE user_id=NEW.user_id;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.purge_native_type_evidence_on_epoch_advance() FROM PUBLIC;
REVOKE ALL ON FUNCTION enforce_native_type_evidence_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS a02_native_type_evidence_epoch_purge ON tutor_item_supply_user_epochs;
CREATE TRIGGER a02_native_type_evidence_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW WHEN (OLD.epoch<NEW.epoch) EXECUTE FUNCTION item_supply_internal.purge_native_type_evidence_on_epoch_advance();
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['tutor_item_supply_native_content_facts','tutor_item_supply_native_relation_preparations',
   'tutor_item_supply_native_relation_batches','tutor_item_supply_native_eligibility'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS native_type_insert ON %I',t);
  EXECUTE format('CREATE TRIGGER native_type_insert BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_native_type_evidence_insert()',t);
  EXECUTE format('DROP TRIGGER IF EXISTS native_type_immutable ON %I',t);
  EXECUTE format('CREATE TRIGGER native_type_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''private'')',t);
 END LOOP;
END $$;
