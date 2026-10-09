"""OFFLINE V3 matrix. Protocol doubles never establish live PG/source/OS proof."""
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.admission import evaluate_admission, evaluate_admission_v2
from app.services.learning.item_supply.diagnostic_policy import (
    AdmissionEvaluationV3, AutonomousEvidencePolicyV3, ReviewBundleV3,
    SharedGenerationPolicyBindingV3, checked_bundle, checked_policy, completed_blind_allowed,
)
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.native_type_evidence import reconstruct_native_content
from app.services.learning.item_supply.review_contracts_v2 import ReviewBundleV2, ReviewReportV2
from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsPending, SharedAdmissionFactsOwner
from app.services.learning.item_supply.shared_admission_facts_contracts import IssuedSharedAdmissionFactsV1
from app.services.learning.item_supply.shared_pipeline_repository import SharedPipelineArtifactRepository
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
from tests.learning.test_item_supply_native_type_evidence import original_row
from tests.learning.test_item_supply_shared_admission_facts import _static_protocol


def evaluate(p, bundle, evidence, validation=None):
    with finite_review_context(p.source, spec=p.spec, materials=p.request.materials):
        return evaluate_admission(p.source, binding=p.binding, policy=AutonomousEvidencePolicyV3(),
            validation_receipt=p.validation if validation is None else validation,
            author_identity=p.author_identity, bundle=bundle, evidence=evidence, enabled=True)


def test_completed_wrong_493_501_roundtrip_and_issuer_current_fence(monkeypatch):
    row, owner, args, conn = original_row(monkeypatch, policy=AutonomousEvidencePolicyV3(), wrong=True)
    p, rr = args['review_prepared'], args['review_result']
    assert rr.blind.state == 'completed' and not rr.blind.score.passed
    assert len(rr.bundle.reports) == 6 and type(rr.bundle) is ReviewBundleV3
    resolved = reconstruct_native_content(row)
    facts = resolved.facts
    assert type(facts.evaluation) is AdmissionEvaluationV3 and facts.evaluation.disposition == 'eligible_internal'
    assert resolved.diagnostic_warnings == ('blind_solution_incorrect',)
    assert not facts.evaluation.publication_enabled
    assert facts.review_budget.actual is None and facts.review_budget.usage_state == 'unknown'
    roundtrip = IssuedSharedAdmissionFactsV1.model_validate_json(facts.model_dump_json())
    assert roundtrip == facts and roundtrip.receipt_hash == facts.receipt_hash
    assert owner.verify(facts, lease=args['lease']) == facts.evidence
    other = SharedAdmissionFactsOwner(conn, validation_pipeline=owner.validation_pipeline,
        review_pipeline=owner.review_pipeline, enabled=True)
    with pytest.raises(SharedAdmissionFactsPending, match='ORIGINAL_ISSUER_REQUIRED'):
        other.verify(roundtrip, lease=args['lease'])
    artifact = dict(request_json=p.request.model_dump(mode='json'), root_id=facts.root_id,
        job_id=p.lease.job_id, lease_generation=p.lease.generation)
    assert owner.artifacts.published_generation_policy(artifact).policy_hash == facts.evaluation.binding.policy_hash
    conn.current = False
    with pytest.raises(SharedAdmissionFactsPending, match='CURRENT_FENCE_LOST'):
        owner.verify(facts, lease=args['lease'])


@pytest.mark.parametrize('wrong', [False, True])
@pytest.mark.parametrize('failure,reason', [
    ('source','current_source_claim_missing'), ('claims','current_source_claim_missing'),
    ('coverage','coverage_proof_missing'), ('scorer','trusted_scorer_missing'),
    ('missing_probe','low_profile_incomplete'), ('probe','profile_probe_failed'),
    ('misjudgment','scorer_misjudgment'), ('validation','invalid_or_stale_evidence'),
    ('role','invalid_or_stale_evidence'), ('blocked_role','material_review_failure'),
    ('ambiguous','material_review_failure'),
])
def test_blind_never_overrides_other_hard_facts(monkeypatch, wrong, failure, reason):
    owner, args, _ = _static_protocol(monkeypatch, policy=AutonomousEvidencePolicyV3(), wrong=wrong)
    facts = owner.issue(**args)
    p, bundle = args['review_prepared'], args['review_result'].bundle
    evidence, validation = facts.evidence, p.validation
    if failure in ('source','claims','coverage','scorer','misjudgment'):
        field,value = {'source':('source_current',False),'claims':('source_claim_receipt_hashes',()),
            'coverage':('coverage_proof_hash',None),'scorer':('scorer_available',False),
            'misjudgment':('known_misjudgments',1)}[failure]
        evidence = evidence.model_copy(update={field:value})
    elif failure == 'missing_probe':
        evidence = evidence.model_copy(update={'probes':()})
    elif failure == 'probe':
        evidence = evidence.model_copy(update={'probes':(evidence.probes[0].model_copy(update={'passed':False}),)+evidence.probes[1:]})
    elif failure == 'validation':
        validation = validation.model_copy(update={'state':'blocked'})
    elif failure == 'role':
        bundle = bundle.model_copy(update={'reports':bundle.reports[:-1]})
    else:
        index = 3 if failure == 'ambiguous' else 4
        raw = bundle.reports[index].model_dump(mode='json')
        raw['findings'] = [dict(safe_code='ambiguity' if failure=='ambiguous' else 'security',
            severity='major', blocking=True, evidence_hash=p.binding.content_hash)]
        raw['run']['output_hash'] = canonical_hash(dict(verdict=raw['verdict'],findings=raw['findings']))
        reports = list(bundle.reports)
        reports[index] = ReviewReportV2.model_validate_json(json.dumps(raw))
        bundle = bundle.model_copy(update={'reports':tuple(reports)})
    result = evaluate(p,bundle,evidence,validation)
    assert result.disposition in ('quarantine','evidence_pending') and reason in result.safe_reasons
    assert not result.publication_enabled


def test_legacy_policy_digest_and_wrong_behavior_unchanged(monkeypatch):
    assert AutonomousEvidencePolicyV2().policy_hash == '7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab'
    owner,args,_ = _static_protocol(monkeypatch)
    facts = owner.issue(**args)
    p,original = args['review_prepared'],args['review_result'].bundle
    assert 'diagnostic_warnings' not in facts.evaluation.model_dump(mode='json')
    legacy = original.model_copy(update={'blind_solve':original.blind_solve.model_copy(update={
        'score':original.blind_solve.score.model_copy(update={'passed':False})})})
    with finite_review_context(p.source,spec=p.spec,materials=p.request.materials):
        result = evaluate_admission_v2(p.source,binding=p.binding,policy=AutonomousEvidencePolicyV2(),
            validation_receipt=p.validation,author_identity=p.author_identity,bundle=legacy,evidence=facts.evidence,enabled=True)
    assert result.disposition == 'quarantine' and 'blind_solve_failed' in result.safe_reasons
    assert not completed_blind_allowed(legacy.blind_solve,AutonomousEvidencePolicyV2())
    assert type(original) is ReviewBundleV2


@pytest.mark.parametrize('mutation',['policy_extra','policy_hash','bundle_v2','copied_run','lost_warning'])
def test_policy_and_native_tampering_denied(monkeypatch,mutation):
    row,owner,args,conn = original_row(monkeypatch,policy=AutonomousEvidencePolicyV3(),wrong=True)
    p,bundle = args['review_prepared'],args['review_result'].bundle
    facts = reconstruct_native_content(row).facts
    if mutation == 'policy_extra':
        with pytest.raises(ValueError):
            checked_policy(AutonomousEvidencePolicyV3().model_copy(update={'allow_failed_blind':True}))
    elif mutation == 'policy_hash':
        conn.policy_bindings[p.request.candidate_id]['policy_hash'] = AutonomousEvidencePolicyV2().policy_hash
        with pytest.raises(ValueError,match='POLICY_STALE'):
            owner.artifacts.generation_policy(p.lease,p.request,now=datetime.now(UTC))
    elif mutation == 'bundle_v2':
        raw = bundle.model_dump(mode='json')
        raw.update(schema_version='item_supply_review_bundle_v2',policy_version='autonomous_evidence_policy_v2')
        legacy = ReviewBundleV2.model_validate_json(json.dumps(raw))
        assert evaluate(p,legacy,facts.evidence).safe_reasons == ('invalid_or_stale_evidence',)
    elif mutation == 'copied_run':
        bad = bundle.reports[0].model_copy(update={'run':bundle.blind_solve.run})
        with pytest.raises(ValueError):
            checked_bundle(bundle.model_copy(update={'reports':(bad,)+bundle.reports[1:]}))
    else:
        changed = deepcopy(row)
        changed['facts_json']['evaluation']['diagnostic_warnings'] = []
        changed['facts_hash'] = canonical_hash(changed['facts_json'])
        with pytest.raises(ValueError):
            reconstruct_native_content(changed)


def test_freeze_original_root_before_author_reservation_no_external_boolean(monkeypatch):
    _,args,_ = _static_protocol(monkeypatch)
    p,root_id = args['review_prepared'],uuid4()
    class Connection:
        info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        def __init__(self):
            self.row,self.inserts = None,[]
        def execute(self,sql,params=()):
            if 'current_database()' in sql:
                result = {'db':'aearn_b1d_sandbox_20261001'}
            elif 'to_regclass' in sql:
                result = {'table_id':'tutor_item_supply_shared_generation_policy_bindings'}
            elif sql.startswith('INSERT'):
                assert 'INSERT INTO tutor_item_supply_shared_generation_policy_bindings' in sql
                self.inserts.append(sql)
                data = params[-1].obj
                self.row = dict(payload_json=data,payload_hash=canonical_hash(data),candidate_id=params[0],
                    root_id=params[1],job_id=params[2],lease_generation=params[3],request_hash=params[4],profile_hash=params[5],policy_hash=params[6])
                result = None
            else:
                assert 'FROM tutor_item_supply_shared_generation_policy_bindings' in sql
                result = self.row
            return SimpleNamespace(fetchone=lambda:result)
    conn = Connection()
    owner = SharedPipelineArtifactRepository(conn,enabled=True)
    meta = dict(root_id=root_id,coverage=p.spec.coverage_blueprint)
    monkeypatch.setattr(owner,'request_context',lambda *a,**kw:meta)
    monkeypatch.setattr(owner,'context',lambda *a,**kw:meta)
    spent = [False]
    monkeypatch.setattr(owner.budget,'_reservation_by_key',lambda *a:{'id':uuid4()} if spent[0] else None)
    policy = owner.freeze_generation_policy(p.lease,p.request,policy=AutonomousEvidencePolicyV3(),now=datetime.now(UTC))
    assert len(conn.inserts)==1 and conn.row['root_id']==root_id
    frozen = SharedGenerationPolicyBindingV3.model_validate_json(json.dumps(conn.row['payload_json']))
    assert frozen.request_hash == canonical_hash(p.request.model_dump(mode='json'))
    assert owner.generation_policy(p.lease,p.request,now=datetime.now(UTC))==policy
    with pytest.raises(ValueError,match='POLICY_CONFLICT'):
        owner.freeze_generation_policy(p.lease,p.request,policy=AutonomousEvidencePolicyV2(),now=datetime.now(UTC))
    conn.row,spent[0] = None,True
    with pytest.raises(ValueError,match='TOO_LATE'):
        owner.freeze_generation_policy(p.lease,p.request,policy=policy,now=datetime.now(UTC))
    with pytest.raises(ValueError):
        owner.freeze_generation_policy(p.lease,p.request,policy=True,now=datetime.now(UTC))
    assert len(conn.inserts)==1


def test_505_complete_revision_pins_and_no_root_history_rewrites():
    text = (Path(__file__).parents[2]/'app/db/schema/505_learning_item_diagnostic_blind_admission.sql').read_text(encoding='utf-8')
    blocks = re.findall(r'DO \$pin\$.*?END \$pin\$;',text,re.S)
    assert len(blocks)==4 and '07047f3dd91453ee9942cf951a3fc499' in text
    for block in blocks:
        body = re.search(r'\$newbody\$(.*?)\$newbody\$',block,re.S).group(1)
        expected = re.search(r"revised_md5 CONSTANT text := '([0-9a-f]{32})'",block).group(1)
        assert hashlib.md5(body.encode()).hexdigest()==expected
        assert '505 unknown upstream prosrc' in block and 'p.prosecdef' in block and 'p.proconfig' in block
    assert 'UPDATE tutor_item_supply' not in text and 'INSERT INTO tutor_item_supply_shared_budget_roots' not in text
    assert 'diagnostic policy must freeze before original author reservation' in text
