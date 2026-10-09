"""One OFFLINE collector/reservation case. No actual DB hooks or learner proof."""
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_bank.native_publication import NativePublishedItemQuery
from app.services.learning.item_supply.native_exposure import NativeExposureOwner
from app.services.learning.item_supply.native_exposure_contracts import (
    NATIVE_EXPOSURE_PRIVATE_PURGE_ORDER, NativeExposureBindingV1, NativeExposurePending,
)
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.storage import SupplyStorageError
from app.services.learning.item_supply.storage_tables import (
    NATIVE_EXPOSURE_UNSCOPED_TABLES, P7_NATIVE_EXPOSURE_TABLES, PRIVATE_TABLES,
)


class OfflineExposureConnection:
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.user, self.epoch, self.scope_id, self.birth = uuid4(), 1, uuid4(), None
        self.raw, self.events, self.watermarks, self.reservations, self.deliveries = [], {}, {}, {}, {}
        self.scope = {'visibility': 'private', 'owner_ref': f'user:{self.user}', 'knowledge_key': 'fixture.native'}
        self.sql = []

    def execute(self, text, params=()):
        sql = ' '.join(text.split())
        self.sql.append(sql)
        row, rows = None, []
        raw = [r for r in self.raw if r['epoch'] == self.epoch]
        if 'current_database()' in sql:
            row = {'db': 'aearn_b1d_sandbox_20261001'}
        elif sql.startswith('SELECT id FROM users'):
            row = {'id': self.user} if params[0] == self.user else None
        elif sql.startswith('INSERT INTO tutor_item_supply_user_epochs') or 'pg_advisory_xact_lock' in sql:
            pass
        elif sql.startswith('SELECT epoch,enabled'):
            row = {'epoch': self.epoch, 'enabled': True}
        elif sql.startswith('SELECT s.* FROM tutor_item_supply_private_scopes'):
            row = {'id': self.scope_id, 'snapshot_json': self.scope} if params == (self.scope_id, self.user, self.epoch) else None
        elif sql.startswith('SELECT i.*'):
            rows = raw
        elif sql.startswith('INSERT INTO tutor_item_supply_native_exposure_events'):
            self.events.setdefault(params[0], {'binding_hash': canonical_hash(params[5].obj), 'binding_json': params[5].obj})
        elif sql.startswith('SELECT binding_hash'):
            row = self.events.get(params[0])
        elif sql.startswith('SELECT id FROM tutor_item_supply_native_exposure_births'):
            row = {'id': self.birth} if self.birth and self.epoch == 1 else None
        elif 'native_exposure_hooks_current()' in sql:
            row = {'current': True}
        elif sql.startswith('SELECT COALESCE(max(sequence)'):
            row = {'watermark': max((r['sequence'] for r in raw), default=0), 'total': len(raw)}
        elif sql.startswith('SELECT i.id,i.kind'):
            rows = [{**r, **self.events[r['id']]} for r in raw if r['id'] in self.events]
        elif sql.startswith('INSERT INTO tutor_item_supply_native_exposure_watermarks'):
            key = canonical_hash(params[4].obj)
            if key not in self.watermarks:
                row = {'id': uuid4()}
                self.watermarks[key] = row
        elif sql.startswith('SELECT id FROM tutor_item_supply_native_exposure_watermarks'):
            row = self.watermarks.get(params[2])
        elif 'clock_timestamp()' in sql:
            row = {'now': datetime.now(UTC)}
        elif sql.startswith('INSERT INTO tutor_item_supply_native_exposure_reservations'):
            if params[3] not in self.reservations:
                row = {'id': uuid4(), 'request_hash': params[4], 'bindings_json': params[6].obj}
                self.reservations[params[3]] = row
        elif sql.startswith('SELECT id,request_hash FROM tutor_item_supply_native_exposure_reservations'):
            row = self.reservations.get(params[2])
        elif sql.startswith('SELECT * FROM tutor_item_supply_native_exposure_reservations'):
            row = self.reservations.get(params[3])
        elif sql.startswith('INSERT INTO tutor_item_supply_native_exposure_deliveries'):
            if params[6] not in self.deliveries:
                row = {'id': params[0], 'request_hash': params[7], 'current_tx': True}
                self.deliveries[params[6]] = row
        elif sql.startswith('SELECT id,request_hash,delivery_txid'):
            row = self.deliveries.get(params[2])
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: rows)


def test_durable_origins_complete_start_reservation_and_irreversible_exposure(monkeypatch):
    conn = OfflineExposureConnection()
    query = NativePublishedItemQuery(conn, enabled=True)
    authority = RagSourceAuthority(SimpleNamespace(conn=conn), None)
    owner = NativeExposureOwner(conn, user_id=conn.user, expected_epoch=1, published_query=query,
                                source_authority=authority, enabled=True)
    bindings = tuple(NativeExposureBindingV1(version_id=uuid4(), item_handle='li:'+str(i)*64,
        content_hash=str(i)*64, proof_id=uuid4(), proof_hash='a'*64, specification_hash='b'*64,
        family_id='fixture.family.'+str(i), family_definition_hash=str(i)*64, semantic_signature=str(i)*64,
        allocation_slot='practice' if i == 3 else 'assessment') for i in (1, 2, 3))
    by_id = {b.version_id: b for b in bindings}
    source_state = {'current': True}
    spec = SimpleNamespace(coverage_blueprint=SimpleNamespace(scope=SimpleNamespace(
        model_dump=lambda **kw: {'visibility': 'public', 'owner_ref': None, 'knowledge_key': 'fixture.native'})))

    def published_binding(version, *, current):
        if current and not source_state['current']:
            raise NativeExposurePending('native_exposure_publication_stale')
        return by_id[version], spec

    monkeypatch.setattr(owner, '_binding', published_binding)
    assert owner.snapshot().state == 'pending'  # Empty native tables are not unseen.
    conn.birth = uuid4()  # Fixture of an actual users AFTER INSERT anchor, not an API argument.
    snapshot = owner.snapshot()
    assert snapshot.state == 'complete' and snapshot.exposure.watermark == 0
    reserved = owner.reserve_assessment(scope_id=conn.scope_id, version_ids=(bindings[0].version_id, bindings[1].version_id), operation_key='case.reserve')
    assert owner.reserve_assessment(scope_id=conn.scope_id, version_ids=(bindings[0].version_id, bindings[1].version_id), operation_key='case.reserve') == reserved
    with pytest.raises(NativeExposurePending, match='practice_reservation_conflict'):
        owner.prepare_practice_delivery(scope_id=conn.scope_id, version_id=bindings[0].version_id,
                                       reservation_key='case.reserve', delivery_key='assessment.as.practice')
    source_state['current'] = False
    with pytest.raises(NativeExposurePending, match='publication_stale'):
        owner.prepare_practice_delivery(scope_id=conn.scope_id, version_id=bindings[2].version_id,
                                       reservation_key='case.reserve', delivery_key='stale.delivery')
    source_state['current'] = True
    owner.prepare_practice_delivery(scope_id=conn.scope_id, version_id=bindings[2].version_id,
                                   reservation_key='case.reserve', delivery_key='practice.delivery')
    assert len(conn.deliveries) == 1
    # Four persisted owner events; display is not disguised as an Attempt.
    for index, kind in enumerate(('shown', 'hint', 'direct_answer', 'attempted'), 1):
        conn.raw.append({'id': uuid4(), 'epoch': 1, 'sequence': index, 'kind': kind,
                         'version_id': bindings[2 if index == 1 else 0].version_id})
    exposed = owner.snapshot()
    assert exposed.exposure.watermark == 4
    assert tuple(r.kind for r in exposed.exposure.records) == ('shown', 'hint', 'direct_answer', 'attempted')
    owner.collect()
    assert len(conn.events) == 4
    with pytest.raises(NativeExposurePending, match='reservation_exposed'):
        owner.prepare_practice_delivery(scope_id=conn.scope_id, version_id=bindings[2].version_id,
                                       reservation_key='case.reserve', delivery_key='practice.retry')
    conn.raw.append({'id': uuid4(), 'epoch': 1, 'sequence': 5, 'kind': 'untracked', 'version_id': None})
    assert owner.snapshot().state == 'pending'
    conn.epoch = 2
    with pytest.raises(SupplyStorageError, match='stale supply epoch'):
        owner.snapshot()
    after_reset = NativeExposureOwner(conn, user_id=conn.user, expected_epoch=2, published_query=query,
                                      source_authority=authority, enabled=True)
    assert after_reset.snapshot().state == 'pending'
    other = NativeExposureOwner(conn, user_id=uuid4(), expected_epoch=2, published_query=query,
                                source_authority=authority, enabled=True)
    with pytest.raises(SupplyStorageError, match='scope unavailable'):
        other.snapshot()
    ddl = (Path(__file__).parents[2] / 'app/db/schema/495_learning_item_native_exposure.sql').read_text(encoding='utf-8')
    assert "AFTER INSERT ON users" in ddl and 'native_exposure_origin_capture AFTER INSERT' in ddl
    assert 'current_database()' not in ddl  # Main chooses installation scope; no hidden public flag change.
    assert all(f'CREATE TABLE IF NOT EXISTS {table}' in ddl for table in NATIVE_EXPOSURE_PRIVATE_PURGE_ORDER)
    assert NATIVE_EXPOSURE_PRIVATE_PURGE_ORDER == P7_NATIVE_EXPOSURE_TABLES
    assert tuple(t for t in PRIVATE_TABLES if t in P7_NATIVE_EXPOSURE_TABLES) == P7_NATIVE_EXPOSURE_TABLES
    assert NATIVE_EXPOSURE_UNSCOPED_TABLES == NATIVE_EXPOSURE_PRIVATE_PURGE_ORDER[2:]
    deletes = [ddl.index(f'DELETE FROM {table} WHERE user_id=target_user;')
               for table in NATIVE_EXPOSURE_PRIVATE_PURGE_ORDER]
    assert deletes == sorted(deletes)
    reset_hook = ddl.split('CREATE OR REPLACE FUNCTION purge_native_exposure_on_epoch_advance()', 1)[1].split('END $$;', 1)[0]
    assert 'item_supply_internal.permitted(NEW.user_id) IS DISTINCT FROM true' in reset_hook
    assert 'NEW.epoch IS DISTINCT FROM OLD.epoch+1' in reset_hook
    assert 'PERFORM item_supply_internal.purge_native_exposure_private(NEW.user_id);' in reset_hook
    assert 'INSERT INTO' not in reset_hook and 'native_exposure_lock(' not in reset_hook
    assert 'AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs' in ddl
    assert 'WHEN (OLD.epoch < NEW.epoch)' in ddl
