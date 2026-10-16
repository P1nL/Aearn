"""C17 exact source-receiver delta and claim hash-domain contracts; offline only."""
from pathlib import Path
import re

from app.services.grounding.autonomous.assessment_contracts import ClaimEvidenceReceipt
from app.services.learning.item_bank.contracts import canonical_hash


SCHEMA = Path(__file__).resolve().parents[2] / 'app/db/schema'
FRAGMENT = '561_learning_item_private_source_claim_receipt_hash_v1.sql'
OLD_CLAIM = """       PERFORM 1 FROM rag_source_claim_receipts cr JOIN rag_source_admissions ad ON ad.id=cr.admission_id
         WHERE ad.receipt_handle=b->>'admission_receipt_id' AND cr.verification_receipt_hash=e->>'claim_receipt_hash'
           AND cr.revoked_at IS NULL AND cr.source_document_hash=r.document_hash FOR SHARE OF cr,ad;"""


def _parts() -> tuple[str, str, str]:
    sql = (SCHEMA / FRAGMENT).read_text(encoding='utf-8')
    old = sql.split('old_body constant text := $old561$', 1)[1].split('$old561$;', 1)[0]
    new = sql.split('new_body constant text := $new561$', 1)[1].split('$new561$;', 1)[0]
    return old, new, sql.split('$new561$;', 1)[1]


def _registered() -> str:
    return _parts()[1].split('         PERFORM 1 FROM rag_source_claim_receipts cr', 1)[1].split('       ELSE', 1)[0]


def test_561_changes_only_original_assessment_claim_query_and_preserves_legacy_branch() -> None:
    source = (SCHEMA / '524_learning_item_private_native_pack_authority_v1.sql').read_text(encoding='utf-8')
    match = re.search(
        r'CREATE OR REPLACE FUNCTION item_supply_internal\.private_native_source_current\(q jsonb\) RETURNS boolean\n'
        r'LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS \$\$'
        r'(.*?)\$\$;', source, re.S,
    )
    assert match is not None
    old, new, _ = _parts()
    assert old == match.group(1)
    start = new.index('       -- Registered isolated-execution claims have TWO distinct canonical hash domains.')
    end = new.index('       IF NOT FOUND THEN RETURN false; END IF;', start)
    addition = new[start:end]
    assert new[:start] + OLD_CLAIM + '\n' + new[end:] == old
    assert addition.split('       ELSE\n', 1)[1] == OLD_CLAIM + '\n       END IF;\n'
    assert old.count(OLD_CLAIM) == new.count(OLD_CLAIM) == 1


def test_561_branch_recognition_is_db_method_not_caller_hash_or_handle() -> None:
    _, new, _ = _parts()
    classifier = new.split('       IF r.assessment_evidence_id IS NOT NULL', 1)[1].split(' THEN', 1)[0]
    assert 'registered_admission.review_id=r.id' in classifier
    assert "registered_claim.method='isolated_execution'" in classifier
    assert 'e->' not in classifier and 'b->' not in classifier and 'q->' not in classifier
    assert 'claim_receipt_hash' not in classifier and 'verification_receipt_hash' not in classifier
    assert new.index("IF b->>'purpose'='assessment_evidence' THEN") < new.index('       IF r.assessment_evidence_id IS NOT NULL AND EXISTS(')


def test_561_full_claim_is_constructed_from_original_db_receipt_admission_review() -> None:
    registered = _registered()
    projection = registered.split("item_supply_internal.snapshot_hash(jsonb_build_object(", 1)[1].split('           FOR SHARE OF cr,ad;', 1)[0]
    for key in ClaimEvidenceReceipt.model_fields:
        assert f"'{key}'," in projection
    for field in ('primary_lineage_family', 'independent_lineage_family', 'independent_source_handle',
                  'independent_document_handle', 'independent_document_revision', 'independent_document_hash'):
        assert f"'{field}',NULL" in projection
    for fragment in (
        "'receipt_id',cr.receipt_handle", "'demand_hash',cr.demand_hash", "'admission_receipt_id',ad.receipt_handle",
        "'claim_hash',cr.claim_hash", "'subject_id',cr.subject_id", "'subject_version',cr.subject_version",
        "'facets',to_jsonb(cr.scope_facets)", "'source_handle',claim_review.source_handle",
        "'document_handle',claim_review.document_handle", "'document_revision',claim_review.document_hash",
        "'document_hash',cr.source_document_hash", "'applicability',cr.applicability", "'method',cr.method",
        "'independent_lineage_verified',false", "'execution_receipt_id',cr.execution_receipt_handle",
        "'execution_scope',cr.execution_scope_json", "'verified',true,'revoked',false",
    ):
        assert fragment in projection
    assert 'e->' not in projection and 'b->' not in projection and 'q->' not in projection


def test_561_both_hashes_and_actual_claim_execution_evidence_association_are_required() -> None:
    registered = _registered()
    for condition in (
        'claim_review.id=ad.review_id', 'registered.id=cr.assessment_evidence_id',
        'registered.id=claim_review.assessment_evidence_id', 'claim_review.id=r.id AND registered.id=r.assessment_evidence_id',
        "ad.receipt_handle=b->>'admission_receipt_id' AND ad.active AND ad.revoked_at IS NULL",
        "cr.method='isolated_execution' AND cr.revoked_at IS NULL AND cr.source_document_hash=r.document_hash",
        "cr.receipt_handle=e->>'claim_id' AND cr.receipt_handle=b->>'claim_receipt_id'",
        'registered.claim_handle=cr.receipt_handle', "cr.execution_receipt_handle=e->>'execution_receipt_id'",
        'registered.execution_handle=cr.execution_receipt_handle', 'registered.claim_hash=cr.claim_hash',
        'registered.document_hash=cr.source_document_hash', 'registered.revoked_at IS NULL',
        'cr.verification_receipt_hash=item_supply_internal.snapshot_hash(registered.signed_proof)',
        "e->>'claim_receipt_hash'=item_supply_internal.snapshot_hash(jsonb_build_object(",
    ):
        assert condition in registered
    assert "cr.verification_receipt_hash=e->>'claim_receipt_hash'" not in registered
    assert ' OR ' not in registered and 'COALESCE' not in registered
    assert 'FOR SHARE OF cr,ad;' in registered


def test_561_real_claim_model_serializes_all_default_fields_and_hashes_distinct_object() -> None:
    claim = ClaimEvidenceReceipt.model_validate({
        'receipt_id': 'claim.001', 'demand_hash': 'a'*64, 'purpose': 'assessment_evidence',
        'admission_receipt_id': 'admission.001', 'claim_hash': 'b'*64,
        'scope': {'subject_id': 'route.python', 'subject_version': '1.0', 'facets': ('fundamentals',)},
        'source_handle': 'source.001', 'document_handle': 'document.001',
        'document_revision': 'c'*64, 'document_hash': 'c'*64,
        'applicability': 'Integer binding source claim.', 'method': 'isolated_execution',
        'execution_receipt_id': 'execution.001',
        'execution_scope': {'runtime_profile': 'python-stdout-v1', 'input_hash': 'd'*64, 'semantics_hash': 'e'*64},
        'verified': True, 'revoked': False,
    })
    projected = claim.model_dump(mode='json')
    assert set(projected) == set(ClaimEvidenceReceipt.model_fields)
    assert projected['independent_lineage_verified'] is False
    assert projected['primary_lineage_family'] is None and projected['independent_document_revision'] is None
    # Distinct domain; never accept a signed-assessment hash as a full claim alias.
    signed_proof = {'payload': {'claim_hash': claim.claim_hash}, 'signature': 'offline-contract-fixture'}
    assert canonical_hash(projected) != canonical_hash(signed_proof)
    assert canonical_hash(projected) != canonical_hash(claim.model_dump(mode='json', exclude_none=True))


def test_561_corpus_namespace_retention_goal_and_final_exact_claim_fences_unchanged() -> None:
    old, new, _ = _parts()
    before = "     IF b->>'purpose'='assessment_evidence' THEN"
    after = "   FOR claim IN SELECT value FROM jsonb_array_elements(material->'exact_claims') LOOP"
    assert new.split(before, 1)[0] == old.split(before, 1)[0]
    assert new.split(after, 1)[1] == old.split(after, 1)[1]
    assert "RETURN clock_timestamp()<deadline;" in new
    for old_guard in ('FOR SHARE OF a,c;', 'FOR SHARE OF review,policy,capture,admission,root;',
                      'se.private_user_id', 'se.private_epoch', 'r.policy_enabled', 'r.root_enabled',
                      'r.evidence_revoked', 'r.capture_body_available'):
        assert old_guard in old and old_guard in new


def test_561_single_target_exact_replay_preserves_all_nonbody_metadata() -> None:
    _, _, installer = _parts()
    replay = installer.index('IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;')
    replacement = installer.index('EXECUTE replace(definition,old_body,new_body);')
    assert installer.count("to_regprocedure('item_supply_internal.private_native_source_current(jsonb)')") == 1
    for guard in ('actual.pronamespace', 'actual.proname', 'actual.lanname', 'actual.prokind', 'actual.proretset',
                  'actual.proisstrict', 'actual.prosecdef', 'actual.proleakproof', 'actual.provolatile', 'actual.proparallel',
                  'actual.prorettype', 'actual.pronargs', 'actual.proargtypes', 'actual.proargnames', 'actual.proallargtypes',
                  'actual.proargmodes', 'actual.provariadic', 'actual.pronargdefaults', 'actual.proargdefaults',
                  'actual.probin', 'actual.prosqlbody', 'actual.protrftypes', 'actual.procost', 'actual.prorows',
                  'actual.prosupport', 'actual.proconfig', 'privilege.grantee=0'):
        assert installer.index(guard) < replay
    assert "actual.proargnames IS DISTINCT FROM ARRAY['q']" in installer
    assert "'pg_catalog.jsonb'::regtype::oid" in installer
    assert replay < installer.index('IF actual.prosrc IS DISTINCT FROM old_body') < replacement
    assert installer.index("length(definition)-length(replace(definition,old_body,''))<>length(old_body)") < replacement
    assert "WHERE p.oid=actual.oid" in installer[replacement:]
    assert "(to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')" in installer[replacement:]
    assert 'verified.prosrc IS DISTINCT FROM new_body' in installer[replacement:]
    assert installer.count('EXECUTE ') == 1
    assert not re.search(r'(?im)^\s*(?:UPDATE|DELETE|INSERT|COMMIT|GRANT|REVOKE|ALTER|DROP|CREATE)\b', installer)
