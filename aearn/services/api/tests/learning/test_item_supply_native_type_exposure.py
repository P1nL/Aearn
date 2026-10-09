"""Offline protocol doubles only. No live DB, provider or native-proof acceptance."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4

from psycopg.pq import TransactionStatus
import pytest

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_bank.native_publication import NativePublishedItemQuery
from app.services.learning.item_supply.native_exposure_contracts import NativeExposureBindingV1, NativeExposurePending
from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner
from app.services.learning.item_supply.native_type_exposure import NativeExposureOwnerV2, _ids, _protected
from app.services.learning.item_supply.native_type_exposure_contracts import NativeTypeExposurePending
from app.services.learning.item_supply.pack_builder import build_pack
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.storage import SupplyStorageError
from tests.learning.test_item_supply_contracts import NOW
from tests.learning.test_item_supply_native_exposure import OfflineExposureConnection
from tests.learning.test_item_supply_type_evidence_pack_v2 import inputs_v2, with_relationships


class TypeConnection(OfflineExposureConnection):
    def __init__(self):
        super().__init__()
        self.birth = uuid4()
        self.snapshots, self.v2_reservations, self.v2_deliveries = {}, {}, {}
        self.isolation = 'read committed'
        self.now = NOW

    def execute(self, text, params=()):
        sql = ' '.join(text.split())
        row, rows = None, []
        if 'transaction_isolation' in sql:
            row = {'isolation': self.isolation}
        elif 'native_exposure_lock(' in sql:
            if params[1] != self.epoch:
                raise SupplyStorageError('supply_epoch_stale')
        elif 'type_exposure_current(' in sql:
            snapshot = self.snapshots[params[0]]
            watermark = max((r['sequence'] for r in self.raw), default=0)
            if snapshot['watermark'] != watermark:
                raise NativeTypeExposurePending('offline_current_ledger_changed')
            row = {'exposure': snapshot}
        elif sql.startswith('SELECT i.id,i.kind,e.version_id'):
            rows = [{**r, **self.events[r['id']]} for r in self.raw if r['id'] in self.events]
        elif sql.startswith('INSERT INTO tutor_item_supply_type_exposure_snapshots'):
            self.snapshots[params[0]] = params[4].obj
        elif sql.startswith('INSERT INTO tutor_item_supply_type_exposure_reservations'):
            if params[3] not in self.v2_reservations:
                row = dict(id=uuid4(), request_hash=params[4], request_json=params[5].obj,
                           scope_id=params[2], bindings_json=params[8].obj)
                self.v2_reservations[params[3]] = row
        elif 'FROM tutor_item_supply_type_exposure_reservations' in sql:
            row = self.v2_reservations.get(params[2])
        elif sql.startswith('INSERT INTO tutor_item_supply_type_exposure_deliveries'):
            if params[6] not in self.v2_deliveries:
                row = dict(id=params[0], request_hash=params[7], current_tx=True)
                self.v2_deliveries[params[6]] = row
        elif 'FROM tutor_item_supply_type_exposure_deliveries' in sql:
            row = self.v2_deliveries.get(params[2])
        else:
            return super().execute(text, params)
        self.sql.append(sql)
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: rows)


@pytest.fixture
def setup(monkeypatch):
    data = inputs_v2()
    conn = TypeConnection()
    conn.user = data.request.learner_id
    conn.scope_id = data.request.storage_scope_id
    query = NativePublishedItemQuery(conn, enabled=True)
    authority = RagSourceAuthority(SimpleNamespace(conn=conn), None)
    # Genuine concrete class, methods replaced ONLY in this explicitly offline test.
    issuer = object.__new__(NativeTypeEvidenceOwner)
    issuer.conn, issuer.user_id, issuer.epoch = conn, conn.user, 1
    issuer.query, issuer.source_authority = query, authority
    owner = NativeExposureOwnerV2(conn, user_id=conn.user, expected_epoch=1, type_owner=issuer, enabled=True)
    content = {c.version_id: c.type_evidence.content for c in data.candidates}
    calls, issued = [], {}
    state = {'current': True}

    def binding(version, *, current):
        c = next(c for c in data.candidates if c.version_id == version)
        return NativeExposureBindingV1(version_id=version, item_handle=c.candidate.item_handle,
            content_hash=c.candidate.content_hash, proof_id=uuid4(), proof_hash='a'*64,
            specification_hash='b'*64, family_id=c.member.family_id,
            family_definition_hash=c.member.family_definition_hash, semantic_signature=c.member.semantic_signature,
            allocation_slot=c.member.slot), None

    # Replayed historical bindings must retain exact proof identity.
    bindings = {v: binding(v, current=False) for v in content}
    monkeypatch.setattr(owner.collector, '_binding', lambda v, **kw: bindings[v])
    monkeypatch.setattr('app.services.learning.item_supply.native_exposure.server_clock', lambda *a: conn.now)
    monkeypatch.setattr('app.services.learning.item_supply.native_type_exposure.server_clock', lambda *a: conn.now)

    def resolve_content(version, *, current):
        calls.append((version, current))
        return SimpleNamespace(content=content[version])

    def resolve_pack(**kw):
        from app.services.learning.item_supply.pack_contracts import CompleteExposureV2
        observation = CompleteExposureV2.model_validate_json(json.dumps(conn.snapshots[kw['exposure_snapshot_id']]))
        current_data = data.model_copy(update={'exposure': observation})
        # These are offline relation projections; not actual501 issuer or reviews.
        result = build_pack(with_relationships(current_data), now=conn.now)
        if result.snapshot is None:
            raise NativeTypeExposurePending('offline_pack_gap')
        cap = SimpleNamespace(eligibility_id=uuid4(), snapshot=result.snapshot)
        issued[id(cap)] = cap
        return cap

    def require_pack(cap):
        if issued.get(id(cap)) is not cap or not state['current']:
            raise NativeTypeExposurePending('offline_capability_not_current')
        if conn.info.transaction_status != TransactionStatus.INTRANS:
            raise NativeTypeExposurePending('offline_transaction_required')
        return cap.snapshot

    monkeypatch.setattr(issuer, 'resolve_content', resolve_content)
    monkeypatch.setattr(issuer, 'resolve_pack', resolve_pack)
    monkeypatch.setattr(issuer, 'require_pack', require_pack)
    return SimpleNamespace(owner=owner, conn=conn, issuer=issuer, data=data, content=content,
        calls=calls, state=state, mapping=uuid4(), relations=(uuid4(),), candidates=tuple(content), bindings=bindings)


def reserve(s, key='test.reserve'):
    return s.owner.reserve_assessment(mapping_receipt_id=s.mapping, candidate_version_ids=s.candidates,
        relation_receipt_ids=s.relations, operation_key=key)


def expose(s, version, kind='shown'):
    s.conn.raw.append(dict(id=uuid4(), sequence=len(s.conn.raw)+1, epoch=s.conn.epoch,
                          version_id=version, kind=kind))


def test_same_family_221_actual_collector_and_current_delivery_idempotency(setup):
    s = setup
    first = reserve(s)
    assert reserve(s) == first
    assert len(s.conn.v2_reservations) == 1
    practice = next(c for c in s.data.candidates if c.member.slot == 'practice')
    did = s.owner.prepare_practice_delivery(reservation_key='test.reserve', version_id=practice.version_id, delivery_key='test.deliver')
    assert s.owner.prepare_practice_delivery(reservation_key='test.reserve', version_id=practice.version_id, delivery_key='test.deliver') == did
    assert len({c.member.family_id for c in s.data.candidates}) == 1
    assert all('native_exposure_reservations' not in q and 'native_exposure_deliveries' not in q for q in s.conn.sql)


def test_empty_or_unknown_history_is_never_assumed(setup):
    s = setup
    s.conn.birth = None
    assert s.owner.snapshot_v2().state == 'pending'
    s.conn.birth = uuid4()
    s.conn.raw.append(dict(id=uuid4(), sequence=1, epoch=1, version_id=None, kind='untracked'))
    assert s.owner.snapshot_v2().safe_reason == 'native_exposure_origin_unmapped'
    assert not s.conn.snapshots


def test_historical_retired_content_uses_current_false_and_immutable_manifest(setup):
    s = setup
    version = s.candidates[0]
    expose(s, version)
    observation = s.owner.snapshot_v2()
    assert observation.state == 'complete'
    assert s.calls == [(version, False)]
    original = next(iter(s.conn.watermarks))
    manifest = dict(original_watermark_id=str(observation.original_watermark_id), original_receipt_hash=original,
                    records=[r.model_dump(mode='json') for r in observation.exposure.records])
    assert observation.exposure.completeness_receipt_hash == canonical_hash(manifest)
    assert observation.exposure.watermark == 1


@pytest.mark.parametrize('kind', ['shown', 'hint', 'direct_answer', 'attempted'])
def test_new_assessment_exposure_denies_delivery_and_reservation(setup, kind):
    s = setup
    reserve(s)
    assessment = next(c for c in s.data.candidates if c.member.slot == 'assessment')
    practice = next(c for c in s.data.candidates if c.member.slot == 'practice')
    expose(s, assessment.version_id, kind)
    with pytest.raises(NativeTypeExposurePending):
        reserve(s)
    with pytest.raises(NativeTypeExposurePending):
        s.owner.prepare_practice_delivery(reservation_key='test.reserve', version_id=practice.version_id, delivery_key='new.delivery')
    assert not s.conn.v2_deliveries


def test_source_revocation_and_old_delivery_transaction_deny(setup):
    s = setup
    reserve(s)
    practice = next(c for c in s.data.candidates if c.member.slot == 'practice')
    s.state['current'] = False
    with pytest.raises(NativeTypeExposurePending, match='not_current'):
        s.owner.prepare_practice_delivery(reservation_key='test.reserve', version_id=practice.version_id, delivery_key='test.deliver')
    s.state['current'] = True
    s.owner.prepare_practice_delivery(reservation_key='test.reserve', version_id=practice.version_id, delivery_key='test.deliver')
    s.conn.v2_deliveries['test.deliver']['current_tx'] = False
    with pytest.raises(NativeTypeExposurePending, match='delivery_conflict'):
        s.owner.prepare_practice_delivery(reservation_key='test.reserve', version_id=practice.version_id, delivery_key='test.deliver')


def test_operation_conflict_and_nonselected_practice_deny(setup):
    s = setup
    reserve(s)
    s.mapping = uuid4()
    with pytest.raises(NativeTypeExposurePending, match='reservation_conflict'):
        reserve(s)
    with pytest.raises(NativeTypeExposurePending, match='selected_practice'):
        s.owner.prepare_practice_delivery(reservation_key='test.reserve', version_id=uuid4(), delivery_key='test.deliver')


def test_default_off_foreign_owner_repeatable_read_reset_and_late_worker(setup):
    s = setup
    with pytest.raises(NativeTypeExposurePending, match='concrete_owner'):
        NativeExposureOwnerV2(s.conn, user_id=uuid4(), expected_epoch=1, type_owner=s.issuer)
    for fake_owner in (SimpleNamespace(), True, lambda **kwargs: True):
        with pytest.raises(NativeTypeExposurePending, match='concrete_owner'):
            NativeExposureOwnerV2(s.conn, user_id=s.conn.user, expected_epoch=1, type_owner=fake_owner)
    off = NativeExposureOwnerV2(s.conn, user_id=s.conn.user, expected_epoch=1, type_owner=s.issuer)
    with pytest.raises((NativeExposurePending, NativeTypeExposurePending)):
        off.snapshot_v2()
    s.conn.isolation = 'repeatable read'
    with pytest.raises(NativeTypeExposurePending, match='read_committed'):
        s.owner.snapshot_v2()
    s.conn.isolation = 'read committed'
    s.conn.epoch = 2
    with pytest.raises(SupplyStorageError):
        s.owner.snapshot_v2()
    s.conn.epoch = 1
    s.conn.info.transaction_status = TransactionStatus.IDLE
    with pytest.raises(NativeExposurePending):
        s.owner.snapshot_v2()


@pytest.mark.parametrize('field', ['item_handle', 'content_hash', 'actual_public_task_hash', 'decision_signature', 'answer_leakage_signature'])
def test_pair_content_clone_defence_not_family_labels(setup, field):
    data = setup.data
    pack = build_pack(data, now=NOW).snapshot
    selected = list(pack.selected)
    indices = [i for i,c in enumerate(selected) if c.member.slot == 'assessment']
    a,b = indices
    content = selected[b].type_evidence.content.model_copy(update={field:getattr(selected[a].type_evidence.content, field)})
    selected[b] = selected[b].model_copy(update={'type_evidence': selected[b].type_evidence.model_copy(update={'content': content})})
    with pytest.raises(NativeTypeExposurePending, match='clone_or_exposed'):
        _protected(pack.model_copy(update={'selected':tuple(selected)}), data.exposure)


def test_raw_pack_capability_never_accepted_and_fresh_deadline(setup, monkeypatch):
    s = setup
    monkeypatch.setattr(s.issuer, 'resolve_pack', lambda **kw: build_pack(s.data, now=NOW).snapshot)
    with pytest.raises(NativeTypeExposurePending, match='not_current'):
        reserve(s)
    with pytest.raises(NativeTypeExposurePending):
        _ids((uuid4(),)*2, maximum=16)
    assert len(s.conn.v2_reservations) == 0


def test_sql_exact_original_bridge_private_order_and_proof_guards():
    schema = Path(__file__).parents[2]/'app/db/schema'
    original = (schema/'495_learning_item_native_exposure.sql').read_text(encoding='utf-8')
    sql = (schema/'502_learning_item_type_exposure.sql').read_text(encoding='utf-8')
    body = re.search(r'CREATE OR REPLACE FUNCTION capture_native_exposure_origin\(\)[\s\S]*?AS \$\$([\s\S]*?)\$\$;', original).group(1)
    assert hashlib.sha256(body.encode()).hexdigest() in sql
    old_branch = re.search(r'old_branch text := \$old\$([\s\S]*?)\$old\$;', sql).group(1)
    new_branch = re.search(r'new_branch text := \$new\$([\s\S]*?)\$new\$;', sql).group(1)
    assert body.count(old_branch) == 1
    patched = body.replace(old_branch, new_branch)
    assert hashlib.sha256(patched.encode()).hexdigest() in sql
    # Only this delivery predicate changes; the actual Artifact origin/slot
    # capture, inbox insertion, owner coordinates and trigger remain original.
    assert patched.replace(new_branch, old_branch) == body
    assert "IF slot IS DISTINCT FROM 'practice'" in patched
    assert "s.track_id::text=coordinates->>'track_id'" in new_branch
    assert "s.revision_id::text=coordinates->>'revision_id'" in new_branch
    assert "s.knowledge_key=coordinates->>'knowledge_key'" in new_branch
    assert "d.delivery_txid=txid_current()" in new_branch
    assert 'patched:=replace(body,old_branch,new_branch)' in sql
    assert '502 exact delivery predicate replacement required' in sql
    assert '502 installed capture body mismatch' in sql
    assert 'a01_native_type_exposure_epoch_purge' in sql
    assert sorted(['a01_native_type_exposure_epoch_purge','a02_native_type_evidence_epoch_purge',
                   'finite_course_mapping_epoch_purge','native_exposure_epoch_purge'])[0].startswith('a01_')
    purge = sql.split('FUNCTION item_supply_internal.purge_type_exposure_private')[1].split('END $$;')[0]
    assert purge.index('DELETE FROM tutor_item_supply_type_exposure_deliveries') < purge.index('DELETE FROM tutor_item_supply_type_exposure_reservations') < purge.index('DELETE FROM tutor_item_supply_type_exposure_snapshots')
    assert 'DELETE FROM tutor_item_supply_native_eligibility' not in purge
    assert 'item_supply_internal.permitted(target_user)' in purge
    for guard in ['tutor_item_supply_native_content_facts','f.proof_id=ev.proof_id','p.proof_hash=f.proof_hash',
                  'native_exposure_hooks_current','native_exposure_births','txid_current()',
                  'type_exposure_current','expired after lock wait','type_content_clone']:
        assert guard in sql
    assert 'CREATE TRIGGER native_exposure_origin_capture' not in sql
    assert '501 eligibility names502 by UUID only' in sql


def test_still_exposed_training_does_not_use_old_family_only_rule(setup):
    s = setup
    reserve(s)
    practice = next(c for c in s.data.candidates if c.member.slot == 'practice')
    expose(s, practice.version_id)
    # Existing exact assessment/training relations cover this immutable content.
    reserve(s)
    assert s.owner.prepare_practice_delivery(reservation_key='test.reserve', version_id=practice.version_id,
                                           delivery_key='test.after_training')


def test_post_capability_lock_wait_uses_fresh_clock_and_no_late_insert(setup, monkeypatch):
    s = setup
    original_require = s.issuer.require_pack

    def delayed(cap):
        result = original_require(cap)
        s.conn.now = NOW + timedelta(seconds=31)
        return result

    monkeypatch.setattr(s.issuer, 'require_pack', delayed)
    with pytest.raises(NativeTypeExposurePending, match='current_fence'):
        reserve(s)
    assert not s.conn.v2_reservations


def test_content_history_resolution_error_cannot_mint_complete_snapshot(setup, monkeypatch):
    s = setup
    expose(s, s.candidates[0])

    def missing(*args, **kwargs):
        from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending
        raise NativeTypeEvidencePending('offline_historical_origin_unmapped')

    monkeypatch.setattr(s.issuer, 'resolve_content', missing)
    assert s.owner.snapshot_v2().state == 'pending'
    assert not s.conn.snapshots


def actual496_shape():
    """Real496 _pack projection, still OFFLINE fixtures rather than actual D rows."""
    from app.services.learning.item_supply.contracts import ClauseCoverageV1
    from app.services.learning.item_supply.finite_course_mapping import _mapping_hash, _pack
    from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
    from app.services.learning.item_supply.pack_contracts import NativeScopedCandidateV2, NativeScopedProofV2, PackInputsV2
    from app.services.learning.item_supply.storage import FrozenPrivateScope
    from tests.learning.test_item_supply_finite_course_mapping import frozen, profile

    target = get_finite_course_target('python-state-update-v1')
    node, configuration = frozen(target), profile(target)
    mapping_hash = _mapping_hash(node, configuration)
    primary = FrozenPrivateScope(uuid4(), canonical_hash('offline496-primary'), canonical_hash('offline496-objective'))
    remediation = FrozenPrivateScope(uuid4(), canonical_hash('offline496-remediation'), primary.objective_hash)
    request = _pack(node, configuration, mapping_hash,
                    {'practice':primary, 'assessment':primary, 'remediation':remediation})
    data = inputs_v2()
    mapping_id, records = uuid4(), []
    for record in data.candidates:
        item = record.candidate
        entry = next(d for d in request.demands if d.slot == item.slot)
        scope = entry.demand.scope
        context = dict(mapping_receipt_id=mapping_id, learner_id=node.user_id, epoch=node.epoch,
                       storage_scope_id=entry.storage_scope_id, course_mapping_hash=mapping_hash)
        clauses = tuple(ClauseCoverageV1(clause_id=c.clause_id, clause_hash=c.clause_hash) for c in entry.blueprint.clauses)
        common = dict(scope_hash=scope.scope_hash, objective_hash=entry.demand.objective_hash,
            blueprint_hash=entry.blueprint.blueprint_hash, matrix_hash=entry.blueprint.matrix_hash,
            policy_version=entry.blueprint.policy_version, clauses=clauses)
        auth = item.current_authorization.model_copy(update={'scope_hash':scope.scope_hash, 'objective_hash':entry.demand.objective_hash})
        proof = NativeScopedProofV2.model_validate({**item.proof.model_dump(), **common, **context,
            'context_schema_version':'native_scoped_objective_coverage_v2', 'runtime_profile_id':scope.runtime_profile_id,
            'runtime_profile_hash':scope.runtime_profile_hash, 'scorer_version':scope.scorer_version,
            'assessment_contract_version':scope.assessment_contract_version,
            'assistance_policy_hash':scope.assistance_policy_hash})
        candidate_fields = {k:v for k,v in common.items() if k != 'scope_hash'}
        candidate = NativeScopedCandidateV2.model_validate({**item.model_dump(), **candidate_fields, **context,
            'schema_version':'native_scoped_candidate_v2', 'scope':scope, 'proof':proof,
            'current_authorization':auth})
        evidence = record.type_evidence.model_copy(update={'scope_hash':scope.scope_hash,
            'objective_hash':entry.demand.objective_hash, 'course_mapping_hash':mapping_hash,
            'runtime_profile_id':scope.runtime_profile_id, 'runtime_profile_hash':scope.runtime_profile_hash,
            'scorer_version':scope.scorer_version, 'assistance_policy_hash':scope.assistance_policy_hash})
        member = record.member.model_copy(update={'course_mapping_hash':mapping_hash})
        records.append(record.model_copy(update={'candidate':candidate, 'member':member, 'type_evidence':evidence,
            'storage_scope_id':entry.storage_scope_id, 'original_proof_hash':proof.proof_hash}))
    observation = data.exposure.model_copy(update={'learner_id':node.user_id})
    return with_relationships(PackInputsV2(request=request, candidates=tuple(records), exposure=observation))


def test_actual496_private_consumption_shape_keeps_public_shared_identity():
    data = actual496_shape()
    result = build_pack(data, now=NOW)
    assert result.snapshot is not None, result.reasons
    assert len(_protected(result.snapshot, data.exposure)) == 2
    assert data.request.demands[0].demand.scope.visibility == 'private'
    assert all(c.candidate.item_handle.startswith('li:') and c.candidate.visibility == 'public'
               and c.owner_id is None and c.epoch is None for c in result.snapshot.selected)
    assert all(c.candidate.learner_id == data.request.learner_id for c in result.snapshot.selected)


def test_new_inbox_origin_after_pack_resolution_is_not_hidden(setup, monkeypatch):
    s = setup
    original = s.issuer.require_pack

    def changed(cap):
        result = original(cap)
        s.conn.raw.append(dict(id=uuid4(), sequence=1, epoch=1, version_id=None, kind='untracked'))
        return result

    monkeypatch.setattr(s.issuer, 'require_pack', changed)
    with pytest.raises(NativeTypeExposurePending, match='ledger_changed'):
        reserve(s)
    assert not s.conn.v2_reservations


def test_sql_private_context_and_public_content_are_explicitly_separate():
    sql = (Path(__file__).parents[2]/'app/db/schema/502_learning_item_type_exposure.sql').read_text(encoding='utf-8')
    assert "receipt_json->'pack_request'=elig.snapshot_json->'request'" in sql
    assert "b->>'storage_scope_id' IS DISTINCT FROM sid::text" in sql
    assert 'AND practice_scope_id=NEW.scope_id' in sql
    assert "current_draft_id=mapping.draft_id" in sql
    assert "f.content_json=b->'type_evidence'->'content'" in sql
    assert "NEW.request_json->'candidate_version_ids' IS DISTINCT FROM to_jsonb(elig.candidate_version_ids)" in sql
    assert 'content.visibility' not in sql.replace('-- remains public. No scope.visibility=content.visibility condition is valid.', '')


def test_sql_actual501502_reset_topology_and_original_relationship_evidence():
    schema = Path(__file__).parents[2]/'app/db/schema'
    a = (schema/'501_learning_item_native_type_evidence.sql').read_text(encoding='utf-8')
    b = (schema/'502_learning_item_type_exposure.sql').read_text(encoding='utf-8')
    assert 'CREATE TRIGGER a02_native_type_evidence_epoch_purge' in a
    assert 'CREATE TRIGGER a01_native_type_exposure_epoch_purge' in b
    snapshot = b.split('CREATE TABLE IF NOT EXISTS tutor_item_supply_type_exposure_snapshots')[1].split('CREATE TABLE IF NOT EXISTS')[0]
    assert 'created_at timestamptz NOT NULL DEFAULT clock_timestamp()' in snapshot
    assert 'REFERENCES tutor_item_supply_type_exposure_snapshots' not in a
    assert 'REFERENCES tutor_item_supply_native_eligibility(id,user_id,epoch)' in b
    assert "'request_hash',req_hash,'contents',contents" in b
    assert "rb.payload_json->'contents' @> jsonb_build_array(a,b)" in b
    assert "j->>'conclusion'='nonredundant'" in b
    assert 'IF n<>1 THEN' in b
    assert 'type_relation_required(pair->0,pair->1' in b
    assert 'type_relation_required(b,c' in b


def test_final_sql_reconstruction_wait_gets_a_new_clock_before_effect(setup, monkeypatch):
    s = setup
    execute = s.conn.execute

    def delayed(text, params=()):
        result = execute(text, params)
        if 'type_exposure_current(' in text:
            # The preceding Python _lock clock was valid. This last SQL owner
            # reconstruction then crosses the original 30-second capability TTL.
            s.conn.now = NOW + timedelta(seconds=31)
        return result

    monkeypatch.setattr(s.conn, 'execute', delayed)
    with pytest.raises(NativeTypeExposurePending, match='pack_current_fence'):
        reserve(s)
    assert not s.conn.v2_reservations


def test_boolean_current_callback_is_not_the_reconstructed_exposure(setup, monkeypatch):
    s = setup
    execute = s.conn.execute

    def boolean_callback(text, params=()):
        if 'type_exposure_current(' in text:
            return SimpleNamespace(fetchone=lambda: {'exposure': True})
        return execute(text, params)

    monkeypatch.setattr(s.conn, 'execute', boolean_callback)
    with pytest.raises(NativeTypeExposurePending, match='exposure_current_fence'):
        reserve(s)
    assert not s.conn.v2_reservations


def test_sql_rejects_duplicate_training_and_binds_slot_to_original_statement():
    """SQL source control only; main must execute positive/negative PG controls."""
    sql = (Path(__file__).parents[2]/'app/db/schema/502_learning_item_type_exposure.sql').read_text(encoding='utf-8')
    for identity in ('version_id', 'item_handle', 'content_hash'):
        assert f"count(DISTINCT (x->'type_evidence'->'content'->>'{identity}'))" in sql
    for guard in (
        "b->'candidate'->'scope' IS DISTINCT FROM scoped.snapshot_json",
        "b->'candidate'->>'slot' IS DISTINCT FROM b->'member'->>'slot'",
        'af.id=p.facts_receipt_id AND af.version_id=p.version_id',
        'prep.id=af.validation_preparation_id',
        "b->'member'->>'slot' IS DISTINCT FROM spec->'allocation'->>'slot'",
        "b->'member'->>'purpose' IS DISTINCT FROM spec->'allocation'->>'purpose'",
        "b->'member'->>'purpose' IS DISTINCT FROM scoped.snapshot_json->>'purpose'",
        "b->'candidate'->>'visibility' IS DISTINCT FROM 'public'",
        "b->>'proof_id' IS DISTINCT FROM original.id::text",
        "b->>'publication_id' IS DISTINCT FROM original.publication_event_id::text",
        "b->>'materialization_id' IS DISTINCT FROM original.materialization_id::text",
        "p.proof_json->'clauses' AS clauses_json",
        "jsonb_build_array(upper(m->>'clause_id'),m->>'clause_hash')",
        'native_clauses IS DISTINCT FROM requested_clauses',
        "b->'candidate'->'clauses' IS DISTINCT FROM mapped_clauses",
        "b->'candidate'->'proof'->'clauses' IS DISTINCT FROM mapped_clauses",
        "spec->'coverage_blueprint'->'scope'->field IS DISTINCT FROM scoped.snapshot_json->field",
    ):
        assert guard in sql
    assert "'runtime_profile_id','runtime_profile_hash','scorer_version','assistance_policy_hash','assessment_contract_version'" in sql
    # A private consumption scope and public immutable content are not conflated.
    assert "b->'candidate'->>'visibility' IS DISTINCT FROM scoped.snapshot_json->>'visibility'" not in sql


def test_sql_current_exposure_returns_exact_reconstructed_json_not_boolean_permission():
    sql = (Path(__file__).parents[2]/'app/db/schema/502_learning_item_type_exposure.sql').read_text(encoding='utf-8')
    helper = sql.split('FUNCTION item_supply_internal.type_exposure_current')[1].split('END $$;')[0]
    assert 'RETURNS jsonb' in helper and 'RETURN s.snapshot_json' in helper
    assert 'RETURN true' not in helper
    assert 'item_supply_internal.snapshot_keys(s.snapshot_json' in helper
    assert "s.snapshot_json->'records' IS DISTINCT FROM records" in helper
    assert 'f.proof_id=ev.proof_id' in helper and 'p.proof_hash=f.proof_hash' in helper
    assert "i.kind<>'metadata' AND ev.id IS NULL" in helper
    assert "'original_receipt_hash',w.payload_hash,'records',records" in helper


def test_relation_consumption_uses_immutable_evidence_deadline_not_producer_io_lease():
    """The new501 first-issuance7day/source cap is not502 authority to extend it."""
    sql = (Path(__file__).parents[2]/'app/db/schema/502_learning_item_type_exposure.sql').read_text(encoding='utf-8')
    helper = sql.split('FUNCTION item_supply_internal.type_relation_required(')[1].split('END $$;')[0]
    assert 'tutor_item_supply_native_relation_batches' in helper
    assert 'clock_timestamp()>=batch.valid_until' in helper
    assert "(r->>'checked_at')::timestamptz>clock_timestamp()" in helper
    assert "clock_timestamp()>=(r->>'valid_until')::timestamptz" in helper
    assert "j->>'conclusion'='nonredundant'" in helper
    for producer_state in ('lease_expires_at', 'parent_deadline', 'shared_job_controls',
                           'native_relation_preparations', "state='leased'"):
        assert producer_state not in helper
    assert 'UPDATE ' not in helper and 'INSERT ' not in helper
    assert "interval '30 seconds'" in sql  # exposure/eligibility freshness remains short
