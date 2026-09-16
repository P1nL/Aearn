"""Pure contracts; no database, provider or runtime initialization."""
from dataclasses import replace

import pytest

from app.services.learning.contracts import LearningPlan, canonical_plan_payload, calculate_plan_impact
from app.services.learning.plan_drafting import (
    CompactPlanModule, CompactPlanNode, CompactPlanProfile, build_plan_draft,
    LearningPlanExperienceLevel,
)
from app.services.learning.lesson_authoring import LessonAuthoringRequest, LessonAuthoringFailure, _assert_candidate_identity
from app.services.learning.lesson_contracts import ExerciseGateBlock, LessonDocumentDraft, lesson_author_block_examples
from tests.support.learning_track_support import sample_plan


def _node_payloads(plan: LearningPlan) -> list[dict[str, object]]:
    modules = canonical_plan_payload(plan)['modules']
    assert isinstance(modules, list)
    result: list[dict[str, object]] = []
    for module in modules:
        assert isinstance(module, dict) and isinstance(module['nodes'], list)
        for node in module['nodes']:
            assert isinstance(node, dict)
            result.append(node)
    return result


def test_catalog_mapping_is_hashed_without_changing_step_identity_or_legacy_payload() -> None:
    legacy = sample_plan()
    assert all('catalog_knowledge_key' not in n for n in _node_payloads(legacy))
    first = replace(legacy.nodes[0], knowledge_key='step.variables', catalog_knowledge_key='python.variables')
    second = replace(legacy.nodes[1], prerequisite_keys=('step.variables',))
    mapped = replace(legacy, modules=(replace(legacy.modules[0],nodes=(first,second)),))
    payload = _node_payloads(mapped)[0]
    assert payload['knowledge_key'] == 'step.variables'
    assert payload['catalog_knowledge_key'] == 'python.variables'
    assert mapped.content_hash != replace(mapped,modules=(replace(mapped.modules[0],nodes=(replace(first,catalog_knowledge_key=None),second)),)).content_hash
    assert legacy == sample_plan() and legacy.content_hash == sample_plan().content_hash


@pytest.mark.parametrize('key', ['', 'Python Variables', '../python.variables'])
def test_catalog_key_rejects_non_stable_aliases(key: str) -> None:
    with pytest.raises(ValueError):
        replace(sample_plan().nodes[0],catalog_knowledge_key=key)


def test_mapping_requires_explicit_capabilities() -> None:
    with pytest.raises(ValueError,match='explicit capabilities'):
        replace(sample_plan().nodes[0],catalog_knowledge_key='python.variables',required_capabilities=())


def test_catalog_or_capability_revision_is_not_reported_as_no_change() -> None:
    legacy = sample_plan()
    mapped = replace(legacy, modules=(replace(legacy.modules[0], nodes=(
        replace(legacy.nodes[0], catalog_knowledge_key='python.variables'), legacy.nodes[1],
    )),))
    impact = calculate_plan_impact(legacy, mapped, progress_keys={n.knowledge_key for n in legacy.nodes})
    assert impact.has_changes and impact.teaching_scope_changed == ('python.variables',)
    assert impact.retained_progress == ('python.functions','python.variables')
    assert impact.added == () and impact.removed == ()


def test_compact_draft_defaults_to_declared_language_and_preserves_explicit_mapping() -> None:
    profile = CompactPlanProfile(language_id='python',goal_text='Learn variables',target_level='beginner',
        weekly_minutes=60,experience_level=LearningPlanExperienceLevel.BEGINNER,pace_summary='Step by step',title='Variables')
    modules = tuple(CompactPlanModule(module_key=f'm{i}',title=f'Module {i}',nodes=[
        CompactPlanNode(knowledge_key=f'n{i}',title=f'Step {i}',catalog_knowledge_key='python.variables')
    ]) for i in (1,2))
    draft = build_plan_draft(profile=profile,modules=modules,sources=(),change_reason='Map content explicitly')
    assert [n.knowledge_key for n in draft.plan.nodes] == ['n1','n2']
    assert all(n.required_capabilities == ('python',) and n.catalog_knowledge_key == 'python.variables' for n in draft.plan.nodes)


def test_lesson_examples_do_not_invent_core_capability_and_owner_rejects_it() -> None:
    examples = lesson_author_block_examples(language_id='python',citation_handle='S1',required_capabilities=('python',))
    gate_example = examples['exercise_gate']
    assert isinstance(gate_example, dict) and gate_example['required_capabilities'] == ['python']
    request = LessonAuthoringRequest(document_kind='standard',language_id='python',knowledge_key='step.variables',
        title='Variables',goal_text='Learn variables',target_level='beginner',required_capabilities=('python',),
        mastery_level='unseen',mastery_confidence=0,evidence=())
    gate = ExerciseGateBlock(block_id='check',order_index=0,citation_ids=(),gate_key='check',gate_kind='knowledge_check',
        assessment_contract_version='knowledge_check_v1',required_capabilities=('python',),learner_prompt='Predict the output.')
    document = LessonDocumentDraft(title='Variables',language_id='python',knowledge_key='step.variables',
        content_standard_version='programming_language_lesson_v1',coverage_keys=('variables',),blocks=(gate,))
    _assert_candidate_identity(document,request)
    with pytest.raises(LessonAuthoringFailure) as error:
        _assert_candidate_identity(replace(document,blocks=(replace(gate,required_capabilities=('python.core',)),)),request)
    assert error.value.code == 'LESSON_DOCUMENT_INVALID'
    assert error.value.issues[0].code == 'LESSON_GATE_CAPABILITY_SCOPE_INVALID'
