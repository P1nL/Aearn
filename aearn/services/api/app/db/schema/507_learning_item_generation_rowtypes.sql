-- Additive repair of three 505 generation-row locals (SQLSTATE 42846).
-- Only the identified declarations change. NEW and already-typed parameters,
-- casts, policy/warnings, immutable identities and every lease/owner fence stay.
-- The caller owns the atomic migration transaction; no data or grant mutation.
DO $repair$
DECLARE
  spec record;
  actual record;
  source text;
  source_hash text;
  repaired_source text;
  definition text;
BEGIN
  FOR spec IN SELECT * FROM (VALUES
    ('public.enforce_item_supply_shared_pipeline_artifact()',
     '5f440f8f989c02bd2cb92d02c0124e3c1b9fb6ec77586094f1c4fc3688d6977d',
     'a9475fd94420a0c04f4647ef7618df31d3d9e89d3fe0415f81308b78f4f8a65e',
     ' facts record;', ' facts public.tutor_item_supply_shared_generation_artifacts%ROWTYPE;'),
    ('public.enforce_item_supply_shared_admission_facts()',
     '2883f07c4be110dd74069e4d053812b04f4fbfdbaef17bb597ffcb105c40db67',
     '3c10ae9c08a194c8cdf3e1758011f5a41a6cc034d71393f3a1be3cbb1c9580ee',
     ' a record;', ' a public.tutor_item_supply_shared_generation_artifacts%ROWTYPE;'),
    ('public.enforce_learning_item_native_publication_proof()',
     '1fe224d154e952f8da8acc04cca0c37a6419b4f8dc852cd81f855212f985c46f',
     '2968c704081ddb8f336edb62212d0b06c2c47f3fb084e22992ccba10b8f5ea08',
     ' g record;', ' g public.tutor_item_supply_shared_generation_artifacts%ROWTYPE;')
  ) AS pins(signature,baseline_sha256,revised_sha256,old_declaration,new_declaration) LOOP
    SELECT p.*,l.lanname INTO actual FROM pg_proc p
      JOIN pg_language l ON l.oid=p.prolang
      WHERE p.oid=to_regprocedure(spec.signature);
    IF NOT FOUND OR actual.prokind<>'f' OR actual.lanname<>'plpgsql'
      OR actual.pronargs<>0 OR actual.prorettype<>'pg_catalog.trigger'::regtype OR actual.proretset
      OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
      OR actual.provolatile<>'v' OR actual.proparallel<>'u'
      OR actual.provariadic<>0 OR actual.pronargdefaults<>0
      OR actual.proargnames IS NOT NULL OR actual.proallargtypes IS NOT NULL
      OR actual.proargmodes IS NOT NULL
      OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
      OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0 THEN
      RAISE check_violation USING MESSAGE='507 generation-row guard attributes differ from reviewed baseline';
    END IF;
    source:=replace(actual.prosrc,E'\r\n',E'\n');
    source_hash:=encode(sha256(convert_to(source,'UTF8')),'hex');
    IF source_hash=spec.revised_sha256 THEN
      CONTINUE; -- Same-fragment replay still checked all original attributes.
    END IF;
    IF source_hash IS DISTINCT FROM spec.baseline_sha256
      OR (length(source)-length(replace(source,spec.old_declaration,'')))/length(spec.old_declaration)<>1 THEN
      RAISE check_violation USING MESSAGE='507 unknown generation-row guard body';
    END IF;
    repaired_source:=replace(source,spec.old_declaration,spec.new_declaration);
    IF encode(sha256(convert_to(repaired_source,'UTF8')),'hex') IS DISTINCT FROM spec.revised_sha256 THEN
      RAISE check_violation USING MESSAGE='507 unexpected generation-row declaration repair';
    END IF;
    -- Keep the original function definition, owner/ACL, security and settings.
    definition:=pg_get_functiondef(actual.oid);
    IF (length(definition)-length(replace(definition,actual.prosrc,'')))/length(actual.prosrc)<>1 THEN
      RAISE check_violation USING MESSAGE='507 generation-row guard body framing mismatch';
    END IF;
    EXECUTE replace(definition,actual.prosrc,repaired_source);
    IF (SELECT encode(sha256(convert_to(replace(p.prosrc,E'\r\n',E'\n'),'UTF8')),'hex')
        FROM pg_proc p WHERE p.oid=actual.oid) IS DISTINCT FROM spec.revised_sha256 THEN
      RAISE check_violation USING MESSAGE='507 generation-row guard verification failed';
    END IF;
  END LOOP;
END $repair$;
