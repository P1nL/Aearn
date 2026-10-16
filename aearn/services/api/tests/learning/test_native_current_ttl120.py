"""C10 pure deadline/SQL seams, not PostgreSQL or Artifact acceptance."""
from datetime import datetime, timedelta
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.schema import SCHEMA_FRAGMENT_NAMES
from app.services.learning.item_supply.native_exposure_contracts import CURRENT_PACK_TTL
from app.services.learning.item_supply.native_type_contracts import IssuedNativePackCapability, NativeTypeEvidencePending
from app.services.learning.item_supply.native_type_evidence import NativeTypeEvidenceOwner, _CurrentPackData
from app.services.learning.item_supply.pack_builder import build_pack
from app.services.learning.item_supply.private_native_exposure import PrivateNativeExposureOwner
from tests.learning.test_item_supply_contracts import NOW
from tests.learning.test_item_supply_native_type_evidence import _private_base_union_scoped_fixture
from tests.learning.test_item_supply_type_evidence_pack_v2 import inputs_v2


@pytest.mark.parametrize('shortest', ('cap', 'source', 'exposure', 'relation', 'report'))
def test_candidate_ttl120_retains_each_original_upstream_minimum(monkeypatch, shortest):
    data = inputs_v2()
    bounds = {key: NOW+timedelta(seconds=300) for key in ('source', 'exposure', 'relation', 'report')}
    if shortest != 'cap':
        bounds[shortest] = NOW+timedelta(seconds=20)
    owner = object.__new__(NativeTypeEvidenceOwner)
    owner.conn, owner.user_id, owner.epoch = object(), data.request.learner_id, data.request.epoch
    owner.current_source_binding = None
    version = data.candidates[0].version_id
    exposure_owner = SimpleNamespace(type_owner=owner, conn=owner.conn, user_id=owner.user_id, epoch=owner.epoch)
    owner._pack_scope = _CurrentPackData(81, uuid4(), (version,), (uuid4(),), exposure_owner, None,
        source_deadlines={version: bounds['source']},
        observation=SimpleNamespace(exposure=data.exposure.model_copy(update={'valid_until': bounds['exposure']})),
        relation_rows={uuid4(): {'valid_until': bounds['relation'],
            'payload_json': {'reports': [{'valid_until': bounds['report'].isoformat()}]}}})
    resolved = SimpleNamespace(content=SimpleNamespace(version_id=version))
    assert CURRENT_PACK_TTL == timedelta(seconds=120)
    assert owner._deadline(resolved, NOW) == NOW+timedelta(seconds=120 if shortest == 'cap' else 20)
    # No-scope issuance still reads its original source deadline on every call.
    owner._pack_scope = None
    calls = []
    monkeypatch.setattr(owner, 'source_deadline', lambda value: calls.append(value) or bounds['source'])
    assert owner._deadline(resolved, NOW) == min(NOW+CURRENT_PACK_TTL, bounds['source'])
    assert calls == [resolved]


@pytest.mark.parametrize('public_seconds', (300, 20))
def test_private_exposure_ttl120_still_requires_and_obeys_public_upstream(monkeypatch, public_seconds):
    data = inputs_v2()
    public = SimpleNamespace(snapshot_id=uuid4(), exposure=data.exposure.model_copy(update={
        'observed_at': NOW, 'valid_until': NOW+timedelta(seconds=public_seconds)}))
    statements, stored, locks = [], {}, []
    def execute(sql, params=()):
        statements.append(sql)
        if sql.startswith('SELECT item_supply_internal.private_native_exposure_hooks_current'):
            return SimpleNamespace(fetchone=lambda: {'ok': True})
        if sql.startswith('SELECT * FROM tutor_item_supply_private_native_exposure_origins'):
            return SimpleNamespace(fetchall=lambda: [])
        if sql.startswith('INSERT INTO tutor_item_supply_private_native_exposure_snapshots'):
            assert params[3] == public.snapshot_id
            stored['payload'] = params[6].obj
            return None
        assert sql.startswith('SELECT item_supply_internal.private_native_exposure_current')
        return SimpleNamespace(fetchone=lambda: stored)
    owner = object.__new__(PrivateNativeExposureOwner)
    owner.conn = SimpleNamespace(execute=execute)
    owner.user_id, owner.epoch = data.request.learner_id, data.request.epoch
    owner.type_owner = SimpleNamespace(_guard=lambda: (NOW, 81))
    owner.public_owner = SimpleNamespace(snapshot_v2=lambda: public)
    monkeypatch.setattr(owner, '_lock', lambda: locks.append('lock'))
    observation = owner.snapshot_complete()
    assert observation.exposure.valid_until == NOW+timedelta(seconds=min(120, public_seconds))
    assert locks == ['lock', 'lock']
    assert 'private_native_exposure_current' in statements[-1]


@pytest.mark.parametrize('upstream_seconds', (300, 20))
def test_union_new_ttl120_and_c7_hit_never_extend_issued_data(monkeypatch, upstream_seconds):
    fixture = _private_base_union_scoped_fixture(monkeypatch, issued=True)
    now = fixture.base.exposure.observed_at+timedelta(milliseconds=1)
    exposure = fixture.union.model_copy(update={'valid_until': now+timedelta(seconds=upstream_seconds)})
    monkeypatch.setattr(fixture.service.exposure_owner, 'snapshot_complete',
        lambda: SimpleNamespace(snapshot_id=uuid4(), exposure=exposure))
    payloads = []
    monkeypatch.setattr(fixture.service.core, '_private_event', lambda task, kind, payload, **kw: payloads.append(payload))
    cap = fixture.owner.resolve(fixture.task)
    payload = payloads[0]
    assert datetime.fromisoformat(payload['valid_until']) == min(cap.snapshot.valid_until, now+CURRENT_PACK_TTL)
    assert datetime.fromisoformat(payload['valid_until']) == now+timedelta(seconds=min(120, upstream_seconds))
    original = (cap.snapshot, cap.inputs, payload.copy(), fixture.owner._scope_union.seal)
    monkeypatch.setattr(fixture.service.type_owner, '_guard', lambda: (now+timedelta(seconds=10), 81))
    assert fixture.owner.resolve(fixture.task) is cap
    assert cap.snapshot is original[0] and cap.inputs is original[1]
    assert payload == original[2] and fixture.owner._scope_union.seal == original[3]
    assert len(payloads) == 1
    assert fixture.verifies.count('final-private-receiver') == 2


def test_original_30_second_data_expires_without_renewal(monkeypatch):
    data = inputs_v2()
    result = build_pack(data, now=NOW)
    assert result.snapshot is not None
    snapshot = result.snapshot.model_copy(update={'valid_until': NOW+timedelta(seconds=30)})
    cap = IssuedNativePackCapability(uuid4(), snapshot)
    owner = object.__new__(NativeTypeEvidenceOwner)
    owner.user_id, owner.epoch = data.request.learner_id, data.request.epoch
    owner._pack_scope = None
    owner._issued = {cap.eligibility_id: (cap, 81, snapshot.snapshot_hash, uuid4(),
        tuple(c.version_id for c in data.candidates), uuid4(), (uuid4(),))}
    calls, clock = [], [NOW]
    def execute(sql, params=()):
        assert sql.startswith('SELECT snapshot_hash FROM tutor_item_supply_native_eligibility')
        calls.append(sql)
        return SimpleNamespace(fetchone=lambda: {'snapshot_hash': snapshot.snapshot_hash})
    owner.conn = SimpleNamespace(execute=execute)
    monkeypatch.setattr(owner, '_guard', lambda: (clock[0], 81))
    assert owner._require_pack_identity(cap) == NOW
    clock[0] = snapshot.valid_until
    with pytest.raises(NativeTypeEvidencePending, match='native_pack_owner_capability_required'):
        owner._require_pack_identity(cap)
    assert len(calls) == 1 and cap.snapshot is snapshot
    assert cap.snapshot.valid_until == NOW+timedelta(seconds=30)


def test_556_exact_final554_body_has_only_one_duration_delta_and_explicit_registration():
    schema = Path(__file__).resolve().parents[2]/'app/db/schema'
    sql = (schema/'556_learning_item_current_pack_ttl120.sql').read_text(encoding='utf-8')
    predecessor = (schema/'554_learning_item_private_base_union_alias_fix.sql').read_text(encoding='utf-8')
    old = sql.split('old_body constant text := $old556$', 1)[1].split('$old556$;', 1)[0]
    new = sql.split('new_body constant text := $new556$', 1)[1].split('$new556$;', 1)[0]
    final554 = predecessor.split('new_body constant text := $new554$', 1)[1].split('$new554$;', 1)[0]
    assert old == final554
    duration = "(p->>'valid_until')::timestamptz<=(p->>'checked_at')::timestamptz+interval '30 seconds'"
    assert old.count(duration) == 1
    assert new == old.replace(duration, duration.replace('30 seconds', '120 seconds'))
    predecessor_index = SCHEMA_FRAGMENT_NAMES.index('555_learning_item_private_initial_author_recovery_v1.sql')
    assert SCHEMA_FRAGMENT_NAMES[predecessor_index:predecessor_index+2] == ('555_learning_item_private_initial_author_recovery_v1.sql',
        '556_learning_item_current_pack_ttl120.sql')
    assert SCHEMA_FRAGMENT_NAMES.count('556_learning_item_current_pack_ttl120.sql') == 1
    # Independent stage/creator contracts stay historical30; no full bootstrap.
    for filename in ('521_learning_item_native_consumer_catalog_bridge.sql',
                     '529_learning_item_native_public_fallback_delivery_v1.sql'):
        assert "interval '30 seconds'" in (schema/filename).read_text(encoding='utf-8')


def test_556_preflights_three_objects_preserves_metadata_and_never_writes_old_rows():
    schema = Path(__file__).resolve().parents[2]/'app/db/schema'
    sql = (schema/'556_learning_item_current_pack_ttl120.sql').read_text(encoding='utf-8')
    installer = sql.split('$new556$;', 1)[1]
    before_ddl, _ = installer.split("EXECUTE format('ALTER TABLE", 1)
    for guard in ('actual.prosrc IS DISTINCT FROM old_body AND actual.prosrc IS DISTINCT FROM new_body',
                  'matches<>1', 'original_check.convalidated', 'original_check.conislocal',
                  'original_check.connoinherit', 'original_check.conkey',
                  'check_definition IS DISTINCT FROM old_check', 'check_definition IS DISTINCT FROM new_check',
                  "privilege.grantee=0 AND privilege.privilege_type='EXECUTE'", 'before_checks:='):
        assert guard in before_ddl
    for table, old_name, new_name in (
        ('tutor_item_supply_type_exposure_snapshots', 'tutor_item_supply_type_exposure_snapshots_check',
         'type_exposure_ttl120_check'),
        ('tutor_item_supply_private_native_exposure_snapshots', 'tutor_item_supply_private_native_exposure_snapshots_check',
         'private_native_exposure_ttl120_check'),
    ):
        assert f"'{table}'" in before_ddl and f"'{old_name}','{new_name}'" in before_ddl
    assert "(to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')" in installer
    assert "to_jsonb(final_check)-ARRAY['oid','conname','conbin','conkey']" in installer
    assert 'verified.prosrc IS DISTINCT FROM new_body' in installer
    assert "saved->'metadata'->>'conname'=saved->>'old_name'" in installer
    assert "EXECUTE replace(definition,old_body,new_body)" in installer
    assert "'00:00:30'::interval" in sql and "'00:02:00'::interval" in sql
    assert not re.search(r'^\s*(?:UPDATE|DELETE|INSERT|COMMIT|GRANT|REVOKE)\b', installer, re.M | re.I)
    assert not re.search(r'DISABLE TRIGGER|session_replication_role|NOT VALID|DROP FUNCTION', installer, re.I)
