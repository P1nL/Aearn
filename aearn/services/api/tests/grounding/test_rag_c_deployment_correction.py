"""Operator-only generation-four correction, synthetic PG; never fetches a URL."""
from __future__ import annotations

from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest

from app.db.schema import load_schema_fragments
from app.services.grounding.autonomous import registered_source_repository as module
from tests.grounding.test_rag_c_final_followup import (
    _attempt, _auth, _disposable_db, _issue, _seed, _unknown,
)


def _three(conn, monkeypatch, *, widen_usage=False, third_unknown=True):
    from tests.grounding.test_rag_c_registered_source_repository import scope

    now = datetime.now(timezone.utc)
    base = scope()
    url = 'https://www.sqlite.org/fixture-correction-'+uuid4().hex+'.html'
    items = [replace(base, generation=gen, url=url, path=url.split('org', 1)[1],
                     policy_id='registered.'+uuid4().hex, root_id='source.'+uuid4().hex,
                     dispatch_id=uuid4()) for gen in (1, 2, 3)]
    original, second, third = items
    for item in items:
        _seed(conn, item, now)
    _attempt(conn, original)
    _unknown(conn, original)
    old_unused_auth, second_auth = uuid4(), uuid4()
    _auth(conn, replace(original, dispatch_id=uuid4()), old_unused_auth,
          original.dispatch_id, now)
    conn.execute('INSERT INTO rag_registered_supplemental_revocations '
                 '(authorization_id,prior_attempt_id,approval_ref) VALUES (%s,%s,%s)',
                 (old_unused_auth, original.dispatch_id, 'fixture.operator.unused.correction'))
    _auth(conn, second, second_auth, original.dispatch_id, now,
          replacement=old_unused_auth)
    _attempt(conn, second, auth_id=second_auth)
    _unknown(conn, second)
    repo = module.PostgresRegisteredSourceRepository('rollback-fixture')
    monkeypatch.setattr(module.psycopg, 'connect', lambda *_a, **_kw: nullcontext(conn))
    third_auth = _issue(repo, original, second, third)
    _attempt(conn, third, auth_id=third_auth)
    if third_unknown:
        _unknown(conn, third)
    fourth = replace(third, generation=4, policy_id='registered.'+uuid4().hex,
                     root_id='source.'+uuid4().hex, dispatch_id=uuid4())
    _seed(conn, fourth, datetime.now(timezone.utc),
          allowed_usages=(["supplementary_explanation", "main_teaching"]
                          if widen_usage else None))
    return repo, original, second, third, fourth, (old_unused_auth, second_auth, third_auth)


def _fourth(repo, original, third, fourth, **changes):
    args = dict(allowance_id=uuid4(), authorization_id=uuid4(),
                original_attempt_id=original.dispatch_id, latest_attempt_id=third.dispatch_id,
                scope=fourth, request_hash='b'*64,
                expires_at=datetime.now(timezone.utc)+timedelta(minutes=10),
                approval_ref='standingpolicy.deploymentcorrection.operator20260928',
                now=datetime.now(timezone.utc))
    args.update(changes)
    return repo.authorize_final_followup(**args)


def test_three_terminal_unknowns_one_separate_fourth_credit_and_no_fifth(monkeypatch):
    conn = _disposable_db()
    try:
        repo, original, second, third, fourth, old_auths = _three(conn, monkeypatch)
        history = conn.execute('SELECT to_jsonb(a) AS row FROM rag_registered_fetch_attempts a '
                               'WHERE id=ANY(%s) ORDER BY id',
                               ([original.dispatch_id, second.dispatch_id, third.dispatch_id],)).fetchall()
        auth_history = conn.execute('SELECT to_jsonb(a) AS row FROM rag_registered_supplemental_authorizations a '
                                    'WHERE id=ANY(%s) ORDER BY id', (list(old_auths),)).fetchall()
        auth = _fourth(repo, original, third, fourth)
        assert conn.execute('SELECT generation FROM rag_registered_final_followup_allowances '
                            'WHERE original_attempt_id=%s ORDER BY generation',
                            (original.dispatch_id,)).fetchall() == [{'generation': 3}, {'generation': 4}]
        assert repo.take_dispatch(fourth, operation_key='fourth.'+uuid4().hex,
                                  request_hash='b'*64, now=datetime.now(timezone.utc),
                                  supplemental_authorization_id=auth) == fourth.dispatch_id
        _unknown(conn, fourth)
        assert conn.execute('SELECT to_jsonb(a) AS row FROM rag_registered_fetch_attempts a '
                            'WHERE id=ANY(%s) ORDER BY id',
                            ([original.dispatch_id, second.dispatch_id, third.dispatch_id],)).fetchall() == history
        assert conn.execute('SELECT to_jsonb(a) AS row FROM rag_registered_supplemental_authorizations a '
                            'WHERE id=ANY(%s) ORDER BY id', (list(old_auths),)).fetchall() == auth_history
        with pytest.raises(module.RegisteredSourceDenied):
            with conn.transaction():
                _fourth(repo, original, third, replace(fourth, dispatch_id=uuid4()))
        with pytest.raises(module.RegisteredSourceDenied):
            with conn.transaction():
                repo.take_dispatch(fourth, operation_key='fifth.'+uuid4().hex,
                                   request_hash='b'*64, now=datetime.now(timezone.utc),
                                   supplemental_authorization_id=auth)
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize('bad', ['wrong_original', 'wrong_latest', 'generation', 'expired',
                                 'reuse_root', 'widen_usage', 'wrong_url', 'third_not_unknown', 'wrong_approval'])
def test_fourth_fails_closed_without_a_new_credit(monkeypatch, bad):
    conn = _disposable_db()
    try:
        repo, original, second, third, fourth, _ = _three(
            conn, monkeypatch, widen_usage=bad == 'widen_usage',
            third_unknown=bad != 'third_not_unknown')
        overrides = {
            'wrong_original': {'original_attempt_id': second.dispatch_id},
            'wrong_latest': {'latest_attempt_id': second.dispatch_id},
            'generation': {'scope': replace(fourth, generation=3)},
            'expired': {'expires_at': datetime.now(timezone.utc)-timedelta(seconds=1)},
            'wrong_approval': {'approval_ref': 'fixture.operator.unrelated.credit'},
            'reuse_root': {'scope': replace(fourth, root_id=third.root_id)},
            'wrong_url': {'scope': replace(fourth, path='/other.html',
                                            url='https://www.sqlite.org/other.html')},
        }
        with pytest.raises((module.RegisteredSourceDenied, psycopg.IntegrityError)):
            with conn.transaction():
                _fourth(repo, original, third, fourth, **overrides.get(bad, {}))
        assert conn.execute('SELECT count(*) AS n FROM rag_registered_final_followup_allowances '
                            'WHERE original_attempt_id=%s AND generation=4',
                            (original.dispatch_id,)).fetchone()['n'] == 0
    finally:
        conn.rollback()
        conn.close()


def test_full_manifest_replay_preserves_fourth_credit(monkeypatch):
    conn = _disposable_db()
    try:
        repo, original, _, third, fourth, _ = _three(conn, monkeypatch)
        auth = _fourth(repo, original, third, fourth)
        before = conn.execute('SELECT to_jsonb(a) AS row FROM rag_registered_final_followup_allowances a '
                              'WHERE original_attempt_id=%s ORDER BY generation',
                              (original.dispatch_id,)).fetchall()
        for _ in range(2):
            for fragment in load_schema_fragments():
                conn.execute(fragment.sql)
        assert conn.execute('SELECT to_jsonb(a) AS row FROM rag_registered_final_followup_allowances a '
                            'WHERE original_attempt_id=%s ORDER BY generation',
                            (original.dispatch_id,)).fetchall() == before
        assert repo.take_dispatch(fourth, operation_key='fourth.'+uuid4().hex,
                                  request_hash='b'*64, now=datetime.now(timezone.utc),
                                  supplemental_authorization_id=auth) == fourth.dispatch_id
    finally:
        conn.rollback()
        conn.close()

def test_parallel_fourth_issue_and_dispatch_each_commit_once(monkeypatch):
    conn = _disposable_db()
    try:
        with monkeypatch.context() as isolated_patch:
            _, original, _, third, fourth, _ = _three(conn, isolated_patch)
        conn.commit()  # Unique synthetic URL in the explicit disposable test database.
    finally:
        conn.close()
    dsn = os.environ['AEARN_RAG_C_TEST_DATABASE_URL']
    barrier = Barrier(2)

    def issue():
        barrier.wait(timeout=10)
        try:
            return _fourth(module.PostgresRegisteredSourceRepository(dsn), original, third, fourth)
        except module.RegisteredSourceDenied:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: issue(), range(2)))
    assert sum(result is not None for result in results) == 1
    authorization_id = next(result for result in results if result is not None)
    barrier = Barrier(2)

    def dispatch():
        barrier.wait(timeout=10)
        try:
            module.PostgresRegisteredSourceRepository(dsn).take_dispatch(
                fourth, operation_key='fourth.race.'+uuid4().hex, request_hash='b'*64,
                now=datetime.now(timezone.utc), supplemental_authorization_id=authorization_id)
            return True
        except module.RegisteredSourceDenied:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: dispatch(), range(2))) == [False, True]
