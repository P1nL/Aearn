"""Main-only atomic native schema checks; optional505, no native supply claims."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[4]
DB = 'aearn_b1d_sandbox_20261001'
NAMES = ('501_learning_item_native_type_evidence.sql',
         '502_learning_item_type_exposure.sql', '503_rag_actual_d_private_lifecycle.sql',
         '504_rag_actual_d_private_provenance.sql')
DIAGNOSTIC_FRAGMENT = '505_learning_item_diagnostic_blind_admission.sql'


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--rehearse', action='store_true', help='Run all checks then roll back all DDL and fixtures')
    parser.add_argument('--include-blind-diagnostic', action='store_true', help='Explicitly include505 after review')
    args = parser.parse_args()
    selected_names = NAMES + ((DIAGNOSTIC_FRAGMENT,) if args.include_blind_diagnostic else ())
    last = '505' if args.include_blind_diagnostic else '504'
    label = '501_' + last
    if not (args.execute or args.rehearse):
        print(json.dumps({'status': 'not_executed', 'database_io': False, 'fragments': selected_names}))
        return 0
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    os.environ['LLM_ENABLED'] = 'false'
    sys.path.insert(0, str(ROOT / 'aearn/services/api'))
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from app.db.schema import load_schema_fragments

    output = ROOT / '.runtime/e-native-type-20261006' / ('schema-501-' + last + '-' + uuid4().hex[:12])
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'pending', 'database': DB, 'provider_calls': 0, 'public_release': False,
        'mode': 'rollback_rehearsal' if args.rehearse else 'execute', 'ddl_committed': False,
        'ordered_manifest_replay_through': last,
        'E_complete': False, 'not_tested': ['populated_native_relation_eligibility',
            'real_type_pack_reservation_delivery', 'actual_D_signed_source_and_populated_private_reset', 'formal_Gate']}
    stage = 'connect'
    try:
        cfg = json.loads((ROOT / '.runtime/item-supply-sandbox-20261001/database.json').read_text(encoding='utf8'))
        if cfg['database'] != DB:
            raise ValueError('wrong_database')
        with psycopg.connect(host=cfg['host'], port=cfg['port'], dbname=cfg['database'], user=cfg['role'],
            password=cfg['password'], row_factory=dict_row, connect_timeout=5,
            options='-c statement_timeout=30000 -c lock_timeout=5000',
            application_name='aearn-reviewed-native-501-' + last) as conn:
            del cfg
            with conn.transaction(force_rollback=args.rehearse):
                assert conn.execute('SELECT current_database() AS n').fetchone()['n'] == DB
                conn.execute('SELECT pg_advisory_xact_lock(%s)', (0x414541524E534348,))
                names = [r['tablename'] for r in conn.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
                columns = {name: [r['column_name'] for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema='public' "
                    'AND table_name=%s ORDER BY ordinal_position', (name,))] for name in names}

                def snapshot():
                    return {name: conn.execute(sql.SQL(
                        "SELECT count(*) AS rows,md5(coalesce(string_agg(md5(to_jsonb(t)::text),'' "
                        "ORDER BY md5(to_jsonb(t)::text)),'')) AS content_hash FROM (SELECT {} FROM {}) t"
                    ).format(sql.SQL(',').join(sql.Identifier(c) for c in columns[name]),
                        sql.Identifier('public', name))).fetchone() for name in names}

                all_fragments = load_schema_fragments()
                # Never install a later, unselected migration as a side effect
                # of replay. The complete ordered prefix ends at this opt-in.
                end = next(i for i, f in enumerate(all_fragments) if f.name == selected_names[-1])
                fragments = all_fragments[:end + 1]
                selected = [f for f in fragments if f.name in selected_names]
                assert tuple(f.name for f in selected) == selected_names
                function_sql = ("SELECT p.oid::text AS id,md5(pg_get_functiondef(p.oid)) AS hash "
                    "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname IN ('public','item_supply_internal') AND p.prokind='f' ORDER BY p.oid")
                original_functions = conn.execute(function_sql).fetchall()
                before = snapshot()
                report['fragment_sha256'] = {f.name: hashlib.sha256(f.sql.encode()).hexdigest() for f in selected}
                stage = 'atomic_additive_' + label
                for fragment in selected:
                    report['active_fragment'] = fragment.name
                    conn.execute(fragment.sql)
                assert snapshot() == before, 'new_fragments_changed_old_column_data'
                for fragment in selected:
                    report['active_fragment'] = fragment.name
                    conn.execute(fragment.sql)
                assert snapshot() == before, 'same_fragment_replay_changed_old_data'
                report['same_fragment_replay'] = 'passed'
                stage = 'ordered_manifest_replay'
                for fragment in fragments:
                    report['active_fragment'] = fragment.name
                    conn.execute(fragment.sql)
                assert snapshot() == before, 'ordered_replay_changed_old_data'
                report['ordered_manifest_replay'] = 'passed'
                report['preserved_existing_tables'] = len(names)
                report['existing_table_hashes'] = before
                report['original_column_projections'] = columns
                report['new_tables'] = [r['tablename'] for r in conn.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename") if r['tablename'] not in names]
                # Check reset within the atomic DDL transaction, before any commit.
                # A failing reset must not leave a partly accepted installation.
                stage = 'original_reset_empty_new_tables_rollback_control'
                with conn.transaction(force_rollback=True):
                    uid = uuid4()
                    conn.execute('INSERT INTO users(id,display_name) VALUES(%s,%s)', (uid, 'native501-' + last + ' rollback-only engineering QA'))
                    assert conn.execute('SELECT count(*) AS n FROM tutor_item_supply_native_exposure_births WHERE user_id=%s',
                        (uid,)).fetchone()['n'] == 1
                    assert conn.execute('SELECT purge_item_supply_private(%s,false) AS epoch', (uid,)).fetchone()['epoch'] == 2
                    assert conn.execute('SELECT count(*) AS n FROM tutor_item_supply_native_exposure_births WHERE user_id=%s',
                        (uid,)).fetchone()['n'] == 0
                    for name in report['new_tables']:
                        user_column = conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
                            "AND table_name=%s AND column_name='user_id'", (name,)).fetchone()
                        if user_column is not None:
                            assert conn.execute(sql.SQL('SELECT count(*) AS n FROM {} WHERE user_id=%s').format(
                                sql.Identifier('public', name)), (uid,)).fetchone()['n'] == 0
                assert snapshot() == before, 'reset_fixture_rollback_changed_historical_data'
            report['ddl_committed'] = not args.rehearse
            with conn.transaction():
                assert snapshot() == before, 'reset_fixture_rollback_changed_historical_data'
                if args.rehearse:
                    assert names == [r['tablename'] for r in conn.execute(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
                    assert conn.execute(function_sql).fetchall() == original_functions
                    report['functions_rolled_back_unchanged'] = True
                    report['all_ddl_rolled_back'] = True
                report['verified_at'] = conn.execute('SELECT clock_timestamp() AS n').fetchone()['n'].isoformat()
            report['empty_table_reset_control'] = 'passed_fixture_rolled_back_not_populated_lifecycle_acceptance'
            report.pop('active_fragment', None)
            report['status'] = ('passed_rollback_rehearsal_' if args.rehearse
                                else 'passed_bounded_schema_') + label
    except Exception as exc:
        report.update(status='failed_retained', failure_stage=stage, error_type=type(exc).__name__,
            sqlstate=getattr(exc, 'sqlstate', None))
        if getattr(exc, 'diag', None):
            report['safe_database_diagnostic'] = exc.diag.message_primary
    (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('existing_table_hashes', 'original_column_projections')}, ensure_ascii=False))
    print(str(output / 'result.json'))
    return 0 if report['status'] in ('passed_bounded_schema_' + label, 'passed_rollback_rehearsal_' + label) else 1


if __name__ == '__main__':
    raise SystemExit(main())
