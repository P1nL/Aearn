"""Required candidate authority must outrank optional unit history."""
import copy
import json
from dataclasses import replace

import pytest

from app.agents.harness.context_budget import TutorContextBudgetPlanner
from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorContextBudgetMode,
    TutorContextBudgetPolicy,
    TutorContextError,
    TutorContextInput,
    TutorContextSection,
    TutorContextSource,
    TutorProviderContextCapability,
)
from app.services.learning.teaching_candidates import (
    TeachingArtifactCandidateBuildError,
    bound_teaching_artifact_candidates,
    project_teaching_provider_context,
)
from tests.tutor.test_tutor_teaching_candidates import _candidate_set, _rich_context, _run


def test_optional_recent_units_do_not_displace_the_available_candidate():
    candidates = _candidate_set()
    context = _rich_context(candidates)
    context['recent_teaching_units'] = [{'unit_id': 'older', 'summary': 'a' * 300},
                                       {'unit_id': 'newer', 'summary': 'b' * 300}]
    original = copy.deepcopy(context)
    selected = bound_teaching_artifact_candidates(context=context, candidates=candidates)
    assert selected.candidates == candidates.candidates
    projection = project_teaching_provider_context(context)
    assert len(json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')) <= 1200
    assert projection['artifact_candidates'][0]['handle'] == candidates.candidates[0].handle
    assert 'recent_teaching_units' not in projection
    assert projection['session']['checkpoint_id'] == context['session']['checkpoint_id']
    assert context == original


def test_oversized_no_candidate_base_also_compacts_optional_history():
    context = _rich_context(_candidate_set(candidates=()))
    context['recent_teaching_units'] = [{'unit_id': 'older', 'summary': '学' * 1400}]
    projection = project_teaching_provider_context(context)
    assert 'artifact_candidates' not in projection
    assert 'recent_teaching_units' not in projection
    assert projection['objective'] == context['objective']


def test_required_candidate_or_base_cannot_be_truncated_to_fit():
    candidates = _candidate_set()
    context = _rich_context(candidates)
    with pytest.raises(ValueError, match='unrepresentable'):
        bound_teaching_artifact_candidates(context=context, candidates=candidates,
                                          minimum_candidates=1, max_characters=100)
    context['objective'] = {'objective_id': '学' * 1400}
    with pytest.raises(TeachingArtifactCandidateBuildError, match='unrepresentable'):
        project_teaching_provider_context(context)


def test_required_serializer_preserves_character_cap_and_utf8_token_budget():
    value = {'objective': {'objective_id': '学' * 600}}
    text, overflow = TutorContextBuilder()._serialize_source(
        TutorContextSection.TEACHING_SESSION, TutorContextSource('teaching-current', value),
    )
    assert len(text) < 1200 < len(text.encode('utf-8'))
    assert overflow is False
    assert json.loads(text) == value
    context = TutorContextInput(run_id='run-current', conversation_id='conversation-current',
        input_revision=1, current_input_required=False,
        teaching_session=(TutorContextSource('teaching-current', value),))
    with pytest.raises(TutorContextError, match='TUTOR_TEACHING_SESSION_UNREPRESENTABLE'):
        TutorContextBuilder().build(context, token_budget=100)


def test_teaching_provider_contract_states_artifact_pause_pairing():
    from app.agents.harness.provider_request import TutorProviderRequestSerializer
    projection = project_teaching_provider_context(_rich_context(_candidate_set()))
    context = TutorContextInput(run_id='run-current', conversation_id='conversation-current',
        input_revision=0, current_input_required=False,
        teaching_session=(TutorContextSource('teaching-current', projection),))
    selected = TutorContextBuilder().build(context, token_budget=4096)
    messages = TutorProviderRequestSerializer().build_messages(run=_run(), context=selected)
    assert 'interaction.mode=artifact with pause_kind=evidence_pause' in messages[0]['content']
    assert 'learner_response_mode=artifact' not in messages[0]['content']
    assert 'never soft_pause' in messages[0]['content']
    from app.services.tutor.decision_protocol import tutor_teaching_enum_contract
    from app.services.learning.teaching_contracts import TeachingAction, TeachingMove
    vocabulary = json.loads(tutor_teaching_enum_contract())
    assert vocabulary['action'] == [item.value for item in TeachingAction]
    assert vocabulary['teaching_moves'] == [item.value for item in TeachingMove]
    assert tutor_teaching_enum_contract() in messages[0]['content']


def test_teaching_provider_contract_fits_conservative_required_request_budget():
    projection = project_teaching_provider_context(_rich_context(_candidate_set()))
    context = TutorContextInput(
        run_id='run-current', conversation_id='conversation-current',
        input_revision=0, current_input_required=False,
        teaching_session=(TutorContextSource('teaching-current', projection),),
    )
    capability = TutorProviderContextCapability(
        context_window_tokens=5296,
        max_output_reserve_tokens=1200,
        protocol_reserve_tokens=128,
        safety_margin_tokens=256,
        maximum_dynamic_target_tokens=512,
        capability_version='configured-conservative-provider-v1',
    )
    policy = TutorContextBudgetPolicy(
        capability=capability,
        mode_targets=(
            (TutorContextBudgetMode.COMPACT, 128),
            (TutorContextBudgetMode.NORMAL, 256),
            (TutorContextBudgetMode.COMPLEX, 384),
            (TutorContextBudgetMode.EXTENDED, 512),
        ),
        fixed_mode=TutorContextBudgetMode.COMPACT,
    )
    run = _run()
    run = replace(
        run,
        policy=replace(
            run.policy,
            context_token_budget=capability.maximum_dynamic_target_tokens,
            context_budget_policy=policy,
        ),
    )

    selected = TutorContextBudgetPlanner().build_context(
        run=run,
        context_input=context,
        builder=TutorContextBuilder(),
    )

    assert selected.checkpoint_metadata.estimated_total_input_tokens is not None
    assert selected.checkpoint_metadata.estimated_total_input_tokens <= capability.input_hard_limit
