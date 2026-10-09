"""One pure revision regression; synthetic materials are not current C/OS proof."""
import hashlib
import json
from uuid import uuid4

import pytest

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.finite_candidate_factory import (
    FACTORY_VERSION, PYTHON_FACTORY_VERSION_V2,
    build_finite_candidate_spec, build_finite_generation_request,
)
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_targets.python_state import _programs, python_state_expected_stdout
from app.services.learning.item_supply.sandbox.finite_probe_plans import public_python_state_target
from app.services.runners.runtime_runner import _matches_patterns
from tests.learning.test_item_supply_finite_candidate_validation import _context, _source
from tests.learning.test_item_supply_generation import make_request
from tests.learning.test_item_supply_python_state import _goal_module


def _args(spec, materials):
    scope = spec.coverage_blueprint.scope
    return dict(target_id=spec.target_id, variant_id=spec.allocation.variant_id,
        seed=spec.seed, item_key=spec.public_template.item_key, version=spec.public_template.version,
        materials=materials, runtime_profile_hash=None if spec.blueprint.runtime_profile_id is None else scope.runtime_profile_hash,
        scorer_version=scope.scorer_version, assistance_policy_hash=scope.assistance_policy_hash,
        policy_version=spec.coverage_blueprint.policy_version, difficulty_profile=spec.blueprint.difficulty_profile,
        publication_policy=spec.blueprint.publication_policy)


def test_python_v2_opt_in_preserves_v1_bytes_and_routes_exact_public_shapes():
    # Captured BEFORE this revision: all five Python intents plus SQL/KC defaults.
    legacy = [_context('python-state-update-v1', slot=i) for i in range(5)]
    legacy += [_context(t) for t in ('sqlite-predicate-order-v1', 'python-kc-binding-v1')]
    specs = [spec for spec, _ in legacy]
    assert FACTORY_VERSION == 'finite-public-spec-v1'
    assert hashlib.sha256(''.join(s.model_dump_json() for s in specs).encode()).hexdigest() == (
        '5a60a1f4583acfcabaae32c14f0dfe5228cf758eef2dd76b9fd2ba14e7ffbef5')
    assert canonical_hash([s.model_dump(mode='json') for s in specs]) == (
        '01fdbacf3c698b92bc257a3d89a3451b193abe4fca2138951bb28fcda4cc6428')
    for old, materials in legacy:
        explicit_v1 = build_finite_candidate_spec(**_args(old, materials), public_spec_version=FACTORY_VERSION)
        assert explicit_v1.model_dump_json() == old.model_dump_json()

    base, _ = make_request()
    rule = _goal_module()  # Pure trusted AST inspector; never executes submissions.
    shape_phrases = {
        'accumulate': '不允许临时变量、两项同时赋值或额外无效赋值',
        'refresh': '这些步骤均为简单赋值，不使用 +=/-= 或两项同时赋值',
        'swap': '或者只用一次两项同时赋值交换 left 与 right',
        'transfer': '也可只用一次两项同时赋值',
    }
    for old, materials in legacy[:5]:
        revised = build_finite_candidate_spec(**_args(old, materials), public_spec_version=PYTHON_FACTORY_VERSION_V2)
        assert revised.blueprint.version == 'finite-public-spec-v2'
        assert revised.specification_hash != old.specification_hash
        assert revised.public_template.public_hash != old.public_template.public_hash
        assert revised.python_goal == old.python_goal
        assert revised.coverage_blueprint == old.coverage_blueprint
        assert (revised.target_definition_hash, revised.family_definition_hash, revised.allocation) == (
            old.target_definition_hash, old.family_definition_hash, old.allocation)
        goal = revised.python_goal
        public = revised.public_template
        assert '独立初始化可重排' in public.instruction_markdown
        assert shape_phrases[goal.task_kind] in public.instruction_markdown
        assert '它不判定变量、顺序、数值或正确性' in public.instruction_markdown
        if revised.allocation.slot == 'remediation':
            assert public.purpose.value == 'remediation' and '先在草稿中建立状态表' in public.instruction_markdown
        content = public.content
        patterns = [p.model_dump() for p in content.code_blanks[0].acceptable_patterns]
        assert not _matches_patterns(content.starter_code, patterns)
        assert '不证明状态目标或正确性' in content.code_blanks[0].expected_concept
        _, _, reference, equivalent, _ = _programs(goal)
        for answer in (reference, equivalent):
            assert rule.inspect_python_state_goal(answer, goal.model_dump(mode='json'))['goal_satisfied'] is True
            assert _matches_patterns(answer, patterns)
            assert answer not in public.instruction_markdown

        request = build_finite_generation_request(revised, candidate_id=uuid4(), profile=base.profile,
            limits=base.limits, materials=materials)
        assert public_python_state_target(request.blueprint, request.public_template) == goal
        assert request.demand_binding is None
        private = dict(type='code', standard_answer=reference,
            tests=[dict(id=kind, case_type=kind, input_json={},
                expected_output_json={'stdout': python_state_expected_stdout(goal)}, order_index=i)
                for i, kind in enumerate(('visible', 'hidden'))],
            score_policy=dict(kind='all_tests', policy_version='all_tests_v1', threshold=1.0))
        source = _source(revised, private)
        inputs = prepare_finite_candidate_validation(source, spec=revised, materials=materials)
        assert inputs.specification_hash == revised.specification_hash and not inputs.publication_enabled
        assert all(t.input_json == {} for t in source.private.content.tests)
        payload = json.dumps(request.model_dump(mode='json'))
        assert 'standard_answer' not in payload and 'expected_output_json' not in payload

    # No V1 relabeling; Python-only opt-in is not a new language-wide framework.
    with pytest.raises(ValueError, match='finite_python_public_task_mismatch'):
        public_python_state_target(revised.blueprint, legacy[4][0].public_template)
    for old, materials in legacy[-2:]:
        with pytest.raises(ValueError, match='finite_public_spec_version_invalid'):
            build_finite_candidate_spec(**_args(old, materials), public_spec_version=PYTHON_FACTORY_VERSION_V2)
