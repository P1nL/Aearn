"""Isolated C operator correction: no DNS, HTTP, provider or live DB."""
from __future__ import annotations

import hashlib
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from app.db.schema import load_schema_fragments
from app.services.grounding.autonomous import registered_source_repository as module
from tests.grounding.test_rag_c_registered_source_repository import (
    URL, _disposable_db, _seed, scope,
)


def _initial_unexpired(conn, repo, now, *, ttl=timedelta(minutes=5)):
    """Issue while valid, then simulate correction after the erroneous expiry."""
    original = scope()
    _seed(conn, original, now)
    repo.take_dispatch(original, operation_key='original.' + uuid4().hex,
                       request_hash='a' * 64, now=now)
    assert repo.mark_unknown(original, error_code='TRANSPORT_UNKNOWN', now=now)
    wrong_id, wrong_dispatch = uuid4(), uuid4()
    conn.execute(
        'INSERT INTO rag_registered_supplemental_authorizations '
        '(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,'
        'request_hash,prior_attempt_id,expires_at,approval_ref) '
        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (wrong_id, wrong_dispatch, original.policy_id, original.generation,
         hashlib.sha256(URL.encode()).hexdigest(), original.root_id,
         'b' * 64, original.dispatch_id, now + ttl,
         'operator.original.20260928'),
    )
    return original, wrong_id, wrong_dispatch


def _correct(repo, original, wrong_id, replacement, now):
    return repo.correct_unused_supplemental(
        original_authorization_id=wrong_id, prior_attempt_id=original.dispatch_id,
        replacement_authorization_id=uuid4(), scope=replacement,
        request_hash='c' * 64, expires_at=now + timedelta(minutes=20),
        approval_ref='operator.correction.20260928', now=now,
    )


def test_unused_misconfigured_auth_corrects_without_mutating_old_rows(monkeypatch):
    conn = _disposable_db()
    try:
        now = datetime.now(timezone.utc)
        repo = module.PostgresRegisteredSourceRepository('rollback-fixture')
        monkeypatch.setattr(module.psycopg, 'connect', lambda *_a, **_kw: nullcontext(conn))
        original, wrong_id, wrong_dispatch = _initial_unexpired(conn, repo, now)
        old = conn.execute('SELECT * FROM rag_registered_supplemental_authorizations WHERE id=%s',
                           (wrong_id,)).fetchone()
        assert old['replaces_authorization_id'] is None
        old_350 = {key: value for key, value in old.items()
                   if key != 'replaces_authorization_id'}
        replacement = scope()
        _seed(conn, replacement, now)
        replacement_id = _correct(repo, original, wrong_id, replacement, now)
        after = conn.execute('SELECT * FROM rag_registered_supplemental_authorizations WHERE id=%s',
                             (wrong_id,)).fetchone()
        assert {key: value for key, value in after.items()
                if key != 'replaces_authorization_id'} == old_350
        assert after['replaces_authorization_id'] is None
        assert conn.execute('SELECT state,supplemental_authorization_id FROM '
                            'rag_registered_fetch_attempts WHERE id=%s',
                            (original.dispatch_id,)).fetchone() == {
                                'state': 'unknown', 'supplemental_authorization_id': None}
        assert conn.execute('SELECT prior_attempt_id FROM rag_registered_supplemental_revocations '
                            'WHERE authorization_id=%s', (wrong_id,)).fetchone()['prior_attempt_id'] == original.dispatch_id
        assert conn.execute('SELECT replaces_authorization_id FROM '
                            'rag_registered_supplemental_authorizations WHERE id=%s',
                            (replacement_id,)).fetchone()['replaces_authorization_id'] == wrong_id
        another = scope()
        _seed(conn, another, now)
        with pytest.raises(module.RegisteredSourceDenied, match='CORRECTION_DENIED'):
            with conn.transaction():
                _correct(repo, original, wrong_id, another, now)
        with pytest.raises(module.RegisteredSourceDenied, match='SUPPLEMENTAL_DENIED'):
            repo.take_dispatch(
                replace(original, dispatch_id=wrong_dispatch),
                operation_key='revoked.' + uuid4().hex, request_hash='b' * 64,
                now=now, supplemental_authorization_id=wrong_id,
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute('INSERT INTO rag_registered_fetch_attempts '
                             '(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,'
                             'request_hash,supplemental_authorization_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                             (wrong_dispatch, original.policy_id, original.generation,
                              hashlib.sha256(URL.encode()).hexdigest(), original.root_id,
                              'sql.revoked.' + uuid4().hex, 'b' * 64, wrong_id))
        assert repo.take_dispatch(
            replacement, operation_key='correct.' + uuid4().hex, request_hash='c' * 64,
            now=now, supplemental_authorization_id=replacement_id,
        ) == replacement.dispatch_id
        assert repo.resolve(replacement, now=now) is not None
        with pytest.raises(module.RegisteredSourceDenied, match='ALREADY_DISPATCHED'):
            repo.take_dispatch(replacement, operation_key='replay.' + uuid4().hex,
                               request_hash='c' * 64, now=now,
                               supplemental_authorization_id=replacement_id)
        with pytest.raises(module.RegisteredSourceDenied, match='CORRECTION_DENIED'):
            _correct(repo, original, replacement_id, scope(), now)
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute('INSERT INTO rag_registered_supplemental_revocations '
                             '(authorization_id,prior_attempt_id,approval_ref) VALUES (%s,%s,%s)',
                             (replacement_id, original.dispatch_id, 'operator.second.20260928'))
        # The independent recovery triggers execute before the 350 SHARE-lock guards.
        for table, recovery_name, legacy_name in (
            ('rag_registered_supplemental_authorizations',
             'trg_00_rag_registered_supplemental_recovery_guard',
             'trg_rag_registered_supplemental_guard'),
            ('rag_registered_fetch_attempts',
             'trg_00_rag_registered_supplemental_recovery_dispatch_guard',
             'trg_rag_registered_supplemental_dispatch_guard'),
        ):
            names = [row['tgname'] for row in conn.execute(
                'SELECT tgname FROM pg_trigger WHERE tgrelid=%s::regclass AND NOT tgisinternal '
                'AND (tgtype & 2)=2 AND (tgtype & 4)=4 ORDER BY tgname',
                (table,),
            )]
            assert names.index(recovery_name) < names.index(legacy_name)
        fragments = load_schema_fragments()
        by_name = {fragment.name: fragment.sql for fragment in fragments}
        # Legacy-only fragment replay must not erase 390's independent guard.
        for _ in range(2):
            conn.execute(by_name['320_rag_registered_source.sql'])
            conn.execute(by_name['350_rag_c_supplemental_dispatch.sql'])
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute('INSERT INTO rag_registered_fetch_attempts '
                             '(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,'
                             'request_hash,supplemental_authorization_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                             (wrong_dispatch, original.policy_id, original.generation,
                              hashlib.sha256(URL.encode()).hexdigest(), original.root_id,
                              'legacy.revoked.' + uuid4().hex, 'b'*64, wrong_id))
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute('INSERT INTO rag_registered_supplemental_authorizations '
                             '(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,'
                             'request_hash,prior_attempt_id,expires_at,approval_ref) '
                             'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                             (uuid4(), uuid4(), replacement.policy_id, 1,
                              hashlib.sha256(URL.encode()).hexdigest(), replacement.root_id,
                              'd'*64, original.dispatch_id, now + timedelta(minutes=20),
                              'operator.third.20260928'))
        # Full fragment replay preserves the preexisting wrong and replacement histories.
        for _ in range(2):
            for fragment in fragments:
                conn.execute(fragment.sql)
        assert conn.execute('SELECT count(*) AS n FROM rag_registered_supplemental_authorizations '
                            'WHERE prior_attempt_id=%s', (original.dispatch_id,)).fetchone()['n'] == 2
    finally:
        conn.rollback()
        conn.close()


def test_consumed_auth_cannot_be_revoked(monkeypatch):
    conn = _disposable_db()
    try:
        now = datetime.now(timezone.utc)
        repo = module.PostgresRegisteredSourceRepository('rollback-fixture')
        monkeypatch.setattr(module.psycopg, 'connect', lambda *_a, **_kw: nullcontext(conn))
        original = scope()
        _seed(conn, original, now)
        repo.take_dispatch(original, operation_key='original.' + uuid4().hex,
                           request_hash='a' * 64, now=now)
        assert repo.mark_unknown(original, error_code='TRANSPORT_UNKNOWN', now=now)
        extra = scope()
        _seed(conn, extra, now)
        auth_id = uuid4()
        conn.execute('INSERT INTO rag_registered_supplemental_authorizations '
                     '(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,'
                     'request_hash,prior_attempt_id,expires_at,approval_ref) '
                     'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (auth_id, extra.dispatch_id, extra.policy_id, extra.generation,
                      hashlib.sha256(URL.encode()).hexdigest(), extra.root_id, 'c'*64,
                      original.dispatch_id, now + timedelta(minutes=20),
                      'operator.consumed.20260928'))
        repo.take_dispatch(extra, operation_key='extra.' + uuid4().hex,
                           request_hash='c'*64, now=now,
                           supplemental_authorization_id=auth_id)
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute('INSERT INTO rag_registered_supplemental_revocations '
                             '(authorization_id,prior_attempt_id,approval_ref) VALUES (%s,%s,%s)',
                             (auth_id, original.dispatch_id, 'operator.revoke.20260928'))
        assert conn.execute('SELECT count(*) AS n FROM rag_registered_supplemental_revocations '
                            'WHERE authorization_id=%s', (auth_id,)).fetchone()['n'] == 0
    finally:
        conn.rollback()
        conn.close()

# Concurrent tests use committed rows in the explicitly disposable test DB. Each
# source URL is unique so their immutable audit rows cannot affect other tests.
def _committed_scope(url_suffix: str):
    item = scope()
    path = '/recovery-' + url_suffix + '.html'
    return replace(item, path=path, url='https://www.sqlite.org' + path)


def test_parallel_correction_serializes_on_original_attempt():
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    dsn = os.environ.get('AEARN_RAG_C_TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('explicit C disposable PostgreSQL required')
    conn = _disposable_db()
    try:
        now = datetime.now(timezone.utc)
        original = _committed_scope(uuid4().hex)
        _seed(conn, original, now)
        conn.execute('INSERT INTO rag_registered_fetch_attempts '
                     '(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,'
                     'request_hash,state,error_code) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (original.dispatch_id, original.policy_id, 1,
                      hashlib.sha256(original.url.encode()).hexdigest(), original.root_id,
                      'original.' + uuid4().hex, 'a'*64, 'unknown', 'TRANSPORT_UNKNOWN'))
        wrong_id = uuid4()
        conn.execute('INSERT INTO rag_registered_supplemental_authorizations '
                     '(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,'
                     'request_hash,prior_attempt_id,expires_at,approval_ref) '
                     'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (wrong_id, uuid4(), original.policy_id, 1,
                      hashlib.sha256(original.url.encode()).hexdigest(), original.root_id,
                      'b'*64, original.dispatch_id, now + timedelta(minutes=20),
                      'operator.original.20260928'))
        replacements = [replace(scope(), url=original.url, path=original.path) for _ in range(2)]
        for item in replacements:
            _seed(conn, item, now)
        conn.commit()
    finally:
        conn.close()
    barrier = Barrier(2)

    def attempt(item):
        barrier.wait(timeout=10)
        try:
            repo = module.PostgresRegisteredSourceRepository(dsn)
            return _correct(repo, original, wrong_id, item, datetime.now(timezone.utc))
        except module.RegisteredSourceDenied:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, replacements))
    assert sum(result is not None for result in results) == 1
    with psycopg.connect(dsn) as verify:
        assert verify.execute('SELECT count(*) FROM rag_registered_supplemental_revocations '
                              'WHERE prior_attempt_id=%s', (original.dispatch_id,)).fetchone()[0] == 1
        assert verify.execute('SELECT count(*) FROM rag_registered_supplemental_authorizations '
                              'WHERE prior_attempt_id=%s', (original.dispatch_id,)).fetchone()[0] == 2


def test_revocation_and_dispatch_race_only_one_can_win():
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    dsn = os.environ.get('AEARN_RAG_C_TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('explicit C disposable PostgreSQL required')
    conn = _disposable_db()
    try:
        now = datetime.now(timezone.utc)
        original = _committed_scope(uuid4().hex)
        _seed(conn, original, now)
        conn.execute('INSERT INTO rag_registered_fetch_attempts '
                     '(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,'
                     'request_hash,state,error_code) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (original.dispatch_id, original.policy_id, 1,
                      hashlib.sha256(original.url.encode()).hexdigest(), original.root_id,
                      'original.' + uuid4().hex, 'a'*64, 'unknown', 'TRANSPORT_UNKNOWN'))
        active = replace(scope(), url=original.url, path=original.path)
        replacement = replace(scope(), url=original.url, path=original.path)
        _seed(conn, active, now)
        _seed(conn, replacement, now)
        auth_id = uuid4()
        conn.execute('INSERT INTO rag_registered_supplemental_authorizations '
                     '(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,'
                     'request_hash,prior_attempt_id,expires_at,approval_ref) '
                     'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (auth_id, active.dispatch_id, active.policy_id, 1,
                      hashlib.sha256(original.url.encode()).hexdigest(), active.root_id,
                      'b'*64, original.dispatch_id, now + timedelta(minutes=20),
                      'operator.original.20260928'))
        conn.commit()
    finally:
        conn.close()
    barrier = Barrier(2)

    def dispatch():
        barrier.wait(timeout=10)
        try:
            module.PostgresRegisteredSourceRepository(dsn).take_dispatch(
                active, operation_key='active.' + uuid4().hex, request_hash='b'*64,
                now=datetime.now(timezone.utc), supplemental_authorization_id=auth_id)
            return True
        except module.RegisteredSourceDenied:
            return False

    def revoke():
        barrier.wait(timeout=10)
        try:
            _correct(module.PostgresRegisteredSourceRepository(dsn), original, auth_id,
                     replacement, datetime.now(timezone.utc))
            return True
        except module.RegisteredSourceDenied:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        dispatched = pool.submit(dispatch)
        revoked = pool.submit(revoke)
        assert dispatched.result(timeout=15) != revoked.result(timeout=15)
    with psycopg.connect(dsn) as verify:
        has_attempt = verify.execute('SELECT count(*) FROM rag_registered_fetch_attempts '
                                     'WHERE supplemental_authorization_id=%s', (auth_id,)).fetchone()[0]
        has_revoke = verify.execute('SELECT count(*) FROM rag_registered_supplemental_revocations '
                                    'WHERE authorization_id=%s', (auth_id,)).fetchone()[0]
        assert has_attempt + has_revoke == 1

def test_expired_unused_original_authority_can_be_corrected(monkeypatch):
    import time

    conn = _disposable_db()
    try:
        now = datetime.now(timezone.utc)
        repo = module.PostgresRegisteredSourceRepository('rollback-fixture')
        monkeypatch.setattr(module.psycopg, 'connect', lambda *_a, **_kw: nullcontext(conn))
        original, old_auth, _old_dispatch = _initial_unexpired(
            conn, repo, now, ttl=timedelta(seconds=0.3))
        new = scope()
        _seed(conn, new, now)
        time.sleep(0.5)
        assert conn.execute('SELECT expires_at < clock_timestamp() AS expired FROM '
                            'rag_registered_supplemental_authorizations WHERE id=%s',
                            (old_auth,)).fetchone()['expired']
        replacement_id = _correct(repo, original, old_auth, new, datetime.now(timezone.utc))
        assert conn.execute('SELECT replaces_authorization_id FROM '
                            'rag_registered_supplemental_authorizations WHERE id=%s',
                            (replacement_id,)).fetchone()['replaces_authorization_id'] == old_auth
    finally:
        conn.rollback()
        conn.close()

def test_parallel_direct_issuance_is_serialized_without_prior_unique_constraint():
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    dsn = os.environ.get('AEARN_RAG_C_TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('explicit C disposable PostgreSQL required')
    conn = _disposable_db()
    try:
        now = datetime.now(timezone.utc)
        original = _committed_scope(uuid4().hex)
        _seed(conn, original, now)
        conn.execute('INSERT INTO rag_registered_fetch_attempts '
                     '(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,'
                     'request_hash,state,error_code) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (original.dispatch_id, original.policy_id, 1,
                      hashlib.sha256(original.url.encode()).hexdigest(), original.root_id,
                      'original.' + uuid4().hex, 'a'*64, 'unknown', 'TRANSPORT_UNKNOWN'))
        options = [replace(scope(), url=original.url, path=original.path) for _ in range(2)]
        for item in options:
            _seed(conn, item, now)
        conn.commit()
    finally:
        conn.close()
    barrier = Barrier(2)

    def issue(item):
        barrier.wait(timeout=10)
        try:
            with psycopg.connect(dsn) as db:
                db.execute('INSERT INTO rag_registered_supplemental_authorizations '
                           '(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,'
                           'request_hash,prior_attempt_id,expires_at,approval_ref) '
                           'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                           (uuid4(), item.dispatch_id, item.policy_id, 1,
                            hashlib.sha256(original.url.encode()).hexdigest(), item.root_id,
                            'b'*64, original.dispatch_id,
                            datetime.now(timezone.utc) + timedelta(minutes=20),
                            'operator.parallel.20260928'))
            return True
        except psycopg.errors.CheckViolation:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(issue, options))
    assert sorted(results) == [False, True]
    with psycopg.connect(dsn) as verify:
        assert verify.execute('SELECT count(*) FROM rag_registered_supplemental_authorizations '
                              'WHERE prior_attempt_id=%s', (original.dispatch_id,)).fetchone()[0] == 1

def test_repeatable_read_cannot_issue_revoke_or_dispatch_direct_sql():
    conn = _disposable_db()
    try:
        now = datetime.now(timezone.utc)
        original = _committed_scope(uuid4().hex)
        _seed(conn, original, now)
        conn.execute('INSERT INTO rag_registered_fetch_attempts '
                     '(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,'
                     'request_hash,state,error_code) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (original.dispatch_id, original.policy_id, 1,
                      hashlib.sha256(original.url.encode()).hexdigest(), original.root_id,
                      'original.' + uuid4().hex, 'a'*64, 'unknown', 'TRANSPORT_UNKNOWN'))
        active = replace(scope(), url=original.url, path=original.path)
        _seed(conn, active, now)
        auth_id = uuid4()
        conn.execute('INSERT INTO rag_registered_supplemental_authorizations '
                     '(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,'
                     'request_hash,prior_attempt_id,expires_at,approval_ref) '
                     'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (auth_id, active.dispatch_id, active.policy_id, 1,
                      hashlib.sha256(original.url.encode()).hexdigest(), active.root_id,
                      'b'*64, original.dispatch_id, now + timedelta(minutes=20),
                      'operator.original.20260928'))
        conn.commit()
        actions = [
            ('INSERT INTO rag_registered_supplemental_authorizations '
             '(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,'
             'request_hash,prior_attempt_id,expires_at,approval_ref) '
             'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
             (uuid4(), uuid4(), active.policy_id, 1,
              hashlib.sha256(original.url.encode()).hexdigest(), active.root_id,
              'c'*64, original.dispatch_id, now + timedelta(minutes=20),
              'operator.repeatable.20260928')),
            ('INSERT INTO rag_registered_supplemental_revocations '
             '(authorization_id,prior_attempt_id,approval_ref) VALUES (%s,%s,%s)',
             (auth_id, original.dispatch_id, 'operator.repeatable.20260928')),
            ('INSERT INTO rag_registered_fetch_attempts '
             '(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,'
             'request_hash,supplemental_authorization_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
             (active.dispatch_id, active.policy_id, 1,
              hashlib.sha256(original.url.encode()).hexdigest(), active.root_id,
              'rr.dispatch.' + uuid4().hex, 'b'*64, auth_id)),
        ]
        for sql, params in actions:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            with pytest.raises(psycopg.errors.CheckViolation, match='read committed'):
                conn.execute(sql, params)
            conn.rollback()
    finally:
        conn.rollback()
        conn.close()

def test_auth_expiry_during_prior_lock_wait_cannot_dispatch(monkeypatch):
    import os
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    dsn = os.environ.get('AEARN_RAG_C_TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('explicit C disposable PostgreSQL required')
    conn = _disposable_db()
    try:
        now = datetime.now(timezone.utc)
        original = _committed_scope(uuid4().hex)
        _seed(conn, original, now)
        conn.execute('INSERT INTO rag_registered_fetch_attempts '
                     '(id,policy_id,generation,canonical_url_sha256,root_id,operation_key,'
                     'request_hash,state,error_code) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (original.dispatch_id, original.policy_id, 1,
                      hashlib.sha256(original.url.encode()).hexdigest(), original.root_id,
                      'original.' + uuid4().hex, 'a'*64, 'unknown', 'TRANSPORT_UNKNOWN'))
        active = replace(scope(), url=original.url, path=original.path)
        _seed(conn, active, now)
        auth_id = uuid4()
        conn.execute('INSERT INTO rag_registered_supplemental_authorizations '
                     '(id,dispatch_id,policy_id,generation,canonical_url_sha256,root_id,'
                     'request_hash,prior_attempt_id,expires_at,approval_ref) '
                     'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (auth_id, active.dispatch_id, active.policy_id, 1,
                      hashlib.sha256(original.url.encode()).hexdigest(), active.root_id,
                      'b'*64, original.dispatch_id, now + timedelta(seconds=2),
                      'operator.expiry.20260928'))
        conn.commit()
    finally:
        conn.close()
    passed_first_policy_check = Event()
    real_current = module._current

    def observed_current(*args, **kwargs):
        result = real_current(*args, **kwargs)
        passed_first_policy_check.set()
        return result

    monkeypatch.setattr(module, '_current', observed_current)

    def dispatch():
        repo = module.PostgresRegisteredSourceRepository(dsn)
        try:
            repo.take_dispatch(active, operation_key='expiry.' + uuid4().hex,
                               request_hash='b'*64, now=datetime.now(timezone.utc),
                               supplemental_authorization_id=auth_id)
            return True
        except module.RegisteredSourceDenied:
            return False

    with psycopg.connect(dsn) as blocker:
        blocker.execute('SELECT id FROM rag_registered_fetch_attempts WHERE id=%s FOR UPDATE',
                        (original.dispatch_id,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(dispatch)
            assert passed_first_policy_check.wait(timeout=5)
            time.sleep(2.2)
            assert not pending.done()  # blocked on the original attempt, not a DNS call
            blocker.commit()
            assert pending.result(timeout=5) is False
    with psycopg.connect(dsn) as verify:
        assert verify.execute('SELECT count(*) FROM rag_registered_fetch_attempts '
                              'WHERE supplemental_authorization_id=%s',
                              (auth_id,)).fetchone()[0] == 0
