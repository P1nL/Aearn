"""Final explicit credit tests: synthetic data, no HTTP and no model calls."""
from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest

from app.db.schema import load_schema_fragments
from app.services.grounding.autonomous import registered_source_repository as module
from tests.grounding.test_rag_c_registered_source_repository import _disposable_db, scope


def _seed(conn, item, now, *, allowed_usages=None):
    until = now + timedelta(hours=1)
    conn.execute(
        'INSERT INTO rag_budget_authority_roots '
        '(root_id,delegation_id,delegation_generation,delegation_expires_at,policy_id,'
        'policy_generation,period_key,period_start,period_end,cap_units,enabled) '
        'VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,1,true)',
        (item.root_id, 'delegation.'+uuid4().hex, until, item.policy_id, item.generation,
         'period.'+uuid4().hex, now-timedelta(minutes=1), until))
    conn.execute(
        'INSERT INTO rag_registered_source_policies '
        '(policy_id,generation,source_handle,subject_id,subject_version,facets,origin,'
        'reading_level,canonical_url,canonical_url_sha256,host,path,license_id,allowed_usages,'
        'immutable_history_allowed,max_captured_bytes,retention_until,expires_at,root_id,enabled) '
        "VALUES (%s,%s,%s,%s,%s,%s,'official','beginner',%s,%s,%s,%s,'Public-Domain',"
        '%s,true,%s,%s,%s,%s,true)',
        (item.policy_id, item.generation, item.source_handle, item.subject_id, item.subject_version,
         list(item.facets), item.url, hashlib.sha256(item.url.encode()).hexdigest(), item.host,
         item.path, allowed_usages or ['supplementary_explanation'], item.max_bytes, until, until, item.root_id))


def _auth(conn, item, auth_id, original_id, now, *, replacement=None, followup=None):
    conn.execute(
        'INSERT INTO rag_registered_supplemental_authorizations '
        '(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash,'
        'prior_attempt_id,expires_at,approval_ref,replaces_authorization_id,explicit_followup_id) '
        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (auth_id, item.dispatch_id, item.policy_id, item.generation,
         hashlib.sha256(item.url.encode()).hexdigest(), item.root_id, 'b'*64, original_id,
         now+timedelta(minutes=20), 'fixture.operator.final.credit', replacement, followup))


def _attempt(conn, item, *, auth_id=None):
    conn.execute(
        'INSERT INTO rag_registered_fetch_attempts '
        '(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,request_hash,supplemental_authorization_id) '
        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
        (item.dispatch_id, item.policy_id, item.generation, hashlib.sha256(item.url.encode()).hexdigest(),
         item.root_id, 'fixture.'+uuid4().hex, 'b'*64, auth_id))


def _unknown(conn, item):
    conn.execute("UPDATE rag_registered_fetch_attempts SET state='unknown',error_code='DEADLINE_EXCEEDED' WHERE id=%s",
                 (item.dispatch_id,))


def _chain(conn):
    now = datetime.now(timezone.utc)
    path = '/fixture-final-'+uuid4().hex+'.html'
    original, latest, target = [replace(scope(), generation=gen, path=path,
                                        url='https://www.sqlite.org'+path) for gen in (1, 2, 3)]
    for item in (original, latest, target):
        _seed(conn, item, now)
    _attempt(conn, original)
    _unknown(conn, original)
    bad_id, latest_id = uuid4(), uuid4()
    _auth(conn, replace(original, dispatch_id=uuid4()), bad_id, original.dispatch_id, now)
    conn.execute('INSERT INTO rag_registered_supplemental_revocations '
                 '(authorization_id,prior_attempt_id,approval_ref) VALUES (%s,%s,%s)',
                 (bad_id, original.dispatch_id, 'fixture.operator.unused.correction'))
    _auth(conn, latest, latest_id, original.dispatch_id, now, replacement=bad_id)
    _attempt(conn, latest, auth_id=latest_id)
    _unknown(conn, latest)
    return original, latest, target, bad_id, latest_id


def _issue(repo, original, latest, target, **overrides):
    args = dict(allowance_id=uuid4(), authorization_id=uuid4(),
                original_attempt_id=original.dispatch_id, latest_attempt_id=latest.dispatch_id,
                scope=target, request_hash='b'*64, expires_at=datetime.now(timezone.utc)+timedelta(minutes=10),
                approval_ref='fixture.operator.explicit.final.credit', now=datetime.now(timezone.utc))
    args.update(overrides)
    return repo.authorize_final_followup(**args)


def test_two_unknowns_one_explicit_final_credit_audit_and_fourth_denied(monkeypatch):
    conn = _disposable_db()
    try:
        original, latest, target, bad_id, latest_id = _chain(conn)
        prior_attempts = conn.execute('SELECT to_jsonb(a) AS row FROM rag_registered_fetch_attempts a '
                                      'WHERE id=ANY(%s) ORDER BY id',
                                      ([original.dispatch_id, latest.dispatch_id],)).fetchall()
        before = conn.execute('SELECT to_jsonb(a) AS row FROM rag_registered_supplemental_authorizations a '
                              'WHERE id=ANY(%s) ORDER BY id', ([bad_id, latest_id],)).fetchall()
        assert all(row['row']['explicit_followup_id'] is None for row in before)
        repo = module.PostgresRegisteredSourceRepository('rollback-fixture')
        monkeypatch.setattr(module.psycopg, 'connect', lambda *_a, **_kw: nullcontext(conn))
        auth_id = _issue(repo, original, latest, target)
        assert repo.take_dispatch(target, operation_key='final.'+uuid4().hex, request_hash='b'*64,
                                  now=datetime.now(timezone.utc), supplemental_authorization_id=auth_id) == target.dispatch_id
        assert repo.resolve(target, now=datetime.now(timezone.utc)) is not None
        assert conn.execute('SELECT count(*) AS n FROM rag_registered_fetch_attempts WHERE canonical_url_sha256=%s',
                            (hashlib.sha256(target.url.encode()).hexdigest(),)).fetchone()['n'] == 3
        assert repo.mark_unknown(target, error_code='DEADLINE_EXCEEDED', now=datetime.now(timezone.utc))
        assert conn.execute('SELECT to_jsonb(a) AS row FROM rag_registered_fetch_attempts a '
                            'WHERE id=ANY(%s) ORDER BY id',
                            ([original.dispatch_id, latest.dispatch_id],)).fetchall() == prior_attempts
        assert conn.execute('SELECT to_jsonb(a) AS row FROM rag_registered_supplemental_authorizations a '
                            'WHERE id=ANY(%s) ORDER BY id', ([bad_id, latest_id],)).fetchall() == before
        with pytest.raises(module.RegisteredSourceDenied):
            with conn.transaction():
                _issue(repo, original, latest, replace(target, dispatch_id=uuid4()))
        with pytest.raises(module.RegisteredSourceDenied):
            repo.correct_unused_supplemental(
                original_authorization_id=auth_id, prior_attempt_id=original.dispatch_id,
                replacement_authorization_id=uuid4(), scope=target, request_hash='b'*64,
                expires_at=datetime.now(timezone.utc)+timedelta(minutes=1),
                approval_ref='fixture.forbidden.correction', now=datetime.now(timezone.utc))
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute('INSERT INTO rag_registered_supplemental_revocations '
                             '(authorization_id,prior_attempt_id,approval_ref) VALUES (%s,%s,%s)',
                             (auth_id, original.dispatch_id, 'fixture.forbidden.revocation'))
        with pytest.raises(module.RegisteredSourceDenied):
            with conn.transaction():
                repo.take_dispatch(target, operation_key='fourth.'+uuid4().hex, request_hash='b'*64,
                                   now=datetime.now(timezone.utc), supplemental_authorization_id=auth_id)
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize('bad', ['original', 'latest', 'generation', 'expired', 'root', 'request'])
def test_mismatched_or_expired_request_creates_no_allowance(monkeypatch, bad):
    conn = _disposable_db()
    try:
        original, latest, target, *_ = _chain(conn)
        repo = module.PostgresRegisteredSourceRepository('rollback-fixture')
        monkeypatch.setattr(module.psycopg, 'connect', lambda *_a, **_kw: nullcontext(conn))
        changes = {
            'original': {'original_attempt_id': uuid4()}, 'latest': {'latest_attempt_id': original.dispatch_id},
            'generation': {'scope': replace(target, generation=2)},
            'expired': {'expires_at': datetime.now(timezone.utc)-timedelta(seconds=1)},
            'root': {'scope': replace(target, root_id=original.root_id)}, 'request': {'request_hash': 'unsafe'},
        }
        with pytest.raises(module.RegisteredSourceDenied):
            with conn.transaction():
                _issue(repo, original, latest, target, **changes[bad])
        assert conn.execute('SELECT count(*) AS n FROM rag_registered_final_followup_allowances '
                            'WHERE original_attempt_id=%s', (original.dispatch_id,)).fetchone()['n'] == 0
    finally:
        conn.rollback()
        conn.close()


def test_legacy_replay_cannot_issue_final_credit_latest_bootstrap_restores(monkeypatch):
    conn = _disposable_db()
    try:
        original, latest, target, *_ = _chain(conn)
        repo = module.PostgresRegisteredSourceRepository('rollback-fixture')
        monkeypatch.setattr(module.psycopg, 'connect', lambda *_a, **_kw: nullcontext(conn))
        fragments = {x.name: x.sql for x in load_schema_fragments()}
        for _ in range(2):
            for name in ('320_rag_registered_source.sql', '350_rag_c_supplemental_dispatch.sql',
                         '390_rag_c_supplemental_recovery.sql'):
                conn.execute(fragments[name])
            with pytest.raises(module.RegisteredSourceDenied):
                with conn.transaction():
                    _issue(repo, original, latest, target)
        for _ in range(2):
            for sql in fragments.values():
                conn.execute(sql)
        assert _issue(repo, original, latest, target)
    finally:
        conn.rollback()
        conn.close()


def test_parallel_final_allowance_issue_only_one_commits():
    conn = _disposable_db()
    try:
        original, latest, target, *_ = _chain(conn)
        conn.commit()
    finally:
        conn.close()
    dsn = os.environ['AEARN_RAG_C_TEST_DATABASE_URL']
    barrier = Barrier(2)

    def issue():
        barrier.wait(timeout=10)
        try:
            return _issue(module.PostgresRegisteredSourceRepository(dsn), original, latest, target)
        except module.RegisteredSourceDenied:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: issue(), range(2)))
    assert sum(x is not None for x in outcomes) == 1
    auth_id = next(x for x in outcomes if x is not None)
    barrier = Barrier(2)

    def dispatch():
        barrier.wait(timeout=10)
        try:
            module.PostgresRegisteredSourceRepository(dsn).take_dispatch(
                target, operation_key='final.race.'+uuid4().hex, request_hash='b'*64,
                now=datetime.now(timezone.utc), supplemental_authorization_id=auth_id)
            return True
        except module.RegisteredSourceDenied:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: dispatch(), range(2)))
    assert sorted(outcomes) == [False, True]

def _allowance(conn, original, latest, target, *, lifetime=timedelta(minutes=10)):
    row = dict(id=uuid4(), original_attempt_id=original.dispatch_id, latest_attempt_id=latest.dispatch_id,
               authorization_id=uuid4(), dispatch_id=target.dispatch_id, policy_id=target.policy_id,
               generation=target.generation, canonical_url_sha256=hashlib.sha256(target.url.encode()).hexdigest(),
               root_id=target.root_id, request_hash='b'*64,
               expires_at=datetime.now(timezone.utc)+lifetime, approval_ref='fixture.operator.explicit.final.credit')
    conn.execute('INSERT INTO rag_registered_final_followup_allowances '
                 '(id,original_attempt_id,latest_attempt_id,authorization_id,dispatch_id,policy_id,generation,'
                 'canonical_url_sha256,root_id,request_hash,expires_at,approval_ref) '
                 'VALUES (%(id)s,%(original_attempt_id)s,%(latest_attempt_id)s,%(authorization_id)s,%(dispatch_id)s,'
                 '%(policy_id)s,%(generation)s,%(canonical_url_sha256)s,%(root_id)s,%(request_hash)s,%(expires_at)s,%(approval_ref)s)', row)
    return row


def _raw_final_auth(conn, allowance, **changes):
    row = dict(allowance, id=allowance['authorization_id'], explicit_followup_id=allowance['id'])
    row.update(changes)
    conn.execute('INSERT INTO rag_registered_supplemental_authorizations '
                 '(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,request_hash,prior_attempt_id,'
                 'expires_at,approval_ref,explicit_followup_id) VALUES (%(id)s,%(dispatch_id)s,%(policy_id)s,'
                 '%(generation)s,%(canonical_url_sha256)s,%(root_id)s,%(request_hash)s,%(original_attempt_id)s,'
                 '%(expires_at)s,%(approval_ref)s,%(explicit_followup_id)s)', row)


def test_direct_sql_auth_exact_binding_immutable_allowance_and_repeatable_read():
    conn = _disposable_db()
    try:
        original, latest, target, *_ = _chain(conn)
        allowance = _allowance(conn, original, latest, target)
        for change in (
            {'id': uuid4()}, {'dispatch_id': uuid4()}, {'request_hash': 'c'*64},
            {'root_id': original.root_id}, {'generation': 2}, {'original_attempt_id': latest.dispatch_id},
            {'approval_ref': 'fixture.wrong.explicit.approval'},
            {'expires_at': allowance['expires_at']+timedelta(seconds=1)}, {'explicit_followup_id': uuid4()},
        ):
            with pytest.raises(psycopg.IntegrityError):
                with conn.transaction():
                    _raw_final_auth(conn, allowance, **change)
        for sql in ('UPDATE rag_registered_final_followup_allowances SET approval_ref=approval_ref WHERE id=%s',
                    'DELETE FROM rag_registered_final_followup_allowances WHERE id=%s'):
            with pytest.raises(psycopg.errors.CheckViolation):
                with conn.transaction():
                    conn.execute(sql, (allowance['id'],))
        _raw_final_auth(conn, allowance)
        conn.commit()  # own unique synthetic URL, retained only in explicit fixture database
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        with pytest.raises(psycopg.errors.CheckViolation, match='read committed'):
            _attempt(conn, target, auth_id=allowance['authorization_id'])
        conn.rollback()
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        with pytest.raises(psycopg.errors.CheckViolation, match='read committed'):
            _allowance(conn, original, latest, target)
        conn.rollback()
    finally:
        conn.rollback()
        conn.close()


def test_expired_final_allowance_cannot_dispatch(monkeypatch):
    import time

    conn = _disposable_db()
    try:
        original, latest, target, *_ = _chain(conn)
        allowance = _allowance(conn, original, latest, target, lifetime=timedelta(seconds=0.3))
        _raw_final_auth(conn, allowance)
        time.sleep(0.5)
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                _attempt(conn, target, auth_id=allowance['authorization_id'])
        assert conn.execute('SELECT count(*) AS n FROM rag_registered_fetch_attempts WHERE canonical_url_sha256=%s',
                            (allowance['canonical_url_sha256'],)).fetchone()['n'] == 2
    finally:
        conn.rollback()
        conn.close()
