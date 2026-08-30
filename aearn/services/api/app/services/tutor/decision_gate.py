"""Catalog-constrained decision validation before Tutor capability or effect boundaries."""
from __future__ import annotations

import hashlib

from typing import Protocol

from pydantic import ValidationError

from app.agents.harness.contracts import payload_mapping_from_fields

from app.agents.harness.skill_catalog import CatalogSkillReference, PublishedSkill, SkillCatalogSnapshot
from app.agents.harness.contracts import (
    TutorDecision,
    TutorDecisionGateResult,
    TutorDecisionGateStatus,
    TutorRunSnapshot,
)
from app.services.tutor.capability_policy import CapabilityPolicyContext, CapabilityPolicyResolver
from app.services.tutor.skill_selection import TutorSkillSelection, TutorSkillSelectionStore


class _TeachingContextRepository(Protocol):
    def teaching_context(self, *, user_id: str, run_id: str) -> dict[str, object] | None: ...


class _DecisionGate(Protocol):
    def validate(self, *, run: TutorRunSnapshot, decision: TutorDecision) -> TutorDecisionGateResult: ...


class CatalogTutorDecisionGate:
    """Accept only exact, policy-authorized catalog decisions without fallback."""

    def __init__(
        self,
        *,
        catalog: SkillCatalogSnapshot,
        policy_resolver: CapabilityPolicyResolver,
        selection_store: TutorSkillSelectionStore,
    ) -> None:
        self._catalog = catalog
        self._policy_resolver = policy_resolver
        self._selection_store = selection_store

    def validate(
        self,
        *,
        run: TutorRunSnapshot,
        decision: TutorDecision,
    ) -> TutorDecisionGateResult:
        policy = self._policy_resolver.resolve(run=run, catalog=self._catalog)
        if not policy.matches(run=run, catalog=self._catalog):
            return _deny("policy_context_stale")

        selected = self._selected_skill(run=run)
        if decision.skill_references:
            selected_result = self._validate_skill_reference(
                run=run,
                decision=decision,
                selected=selected,
                policy=policy,
            )
            if selected_result is not None:
                return selected_result
            selected = self._selected_skill(run=run)

        if decision.capability_requests or decision.effect_proposals:
            if selected is None:
                return self._select_unique_action_skill(
                    run=run,
                    decision=decision,
                    policy=policy,
                )
            selection, skill = selected
            if not policy.allows_skill(selection.reference):
                return _deny("skill_not_policy_eligible")
            capability_result = self._validate_capability_requests(
                decision=decision,
                skill=skill,
                policy=policy,
            )
            if capability_result is not None:
                return capability_result
            effect_result = self._validate_effect_proposals(
                decision=decision,
                skill=skill,
                policy=policy,
            )
            if effect_result is not None:
                return effect_result

        return TutorDecisionGateResult(status=TutorDecisionGateStatus.APPROVED)

    def _validate_skill_reference(
        self,
        *,
        run: TutorRunSnapshot,
        decision: TutorDecision,
        selected: tuple[TutorSkillSelection, PublishedSkill] | None,
        policy: CapabilityPolicyContext,
    ) -> TutorDecisionGateResult | None:
        if len(decision.skill_references) != 1:
            return _deny("multiple_skill_references")
        raw_reference = decision.skill_references[0]
        try:
            reference = CatalogSkillReference(skill_id=raw_reference.skill_id, version=raw_reference.version)
        except ValueError:
            return _deny("skill_version_invalid")
        skill = self._catalog.resolve_skill(reference.skill_id, reference.version)
        if skill is None:
            return _deny("unknown_skill_reference")
        if not policy.allows_skill(reference):
            return _deny("skill_not_policy_eligible")

        if selected is None or selected[0].reference != reference:
            if decision.capability_requests or decision.effect_proposals or decision.terminal_outcome is not None:
                return _deny("mixed_skill_selection_action")
            self._record_selection(run=run, skill=skill)
            return TutorDecisionGateResult(status=TutorDecisionGateStatus.REBUILD_CONTEXT)
        return None

    def _select_unique_action_skill(
        self,
        *,
        run: TutorRunSnapshot,
        decision: TutorDecision,
        policy: CapabilityPolicyContext,
    ) -> TutorDecisionGateResult:
        action_result = self._validate_unbound_actions(decision=decision, policy=policy)
        if action_result is not None:
            return action_result

        required_capability_ids = frozenset(
            request.capability_id for request in decision.capability_requests
        )
        required_effect_types = frozenset(
            proposal.effect_type for proposal in decision.effect_proposals
        )
        candidates = tuple(
            skill
            for skill in self._catalog.skills
            if policy.allows_skill(skill.reference)
            and required_capability_ids.issubset(skill.manifest.requires_capabilities)
            and required_effect_types.issubset(skill.manifest.allowed_effect_types)
        )
        if not candidates:
            return _deny("skill_selection_required")
        if len(candidates) != 1:
            return _deny("action_skill_ambiguous")

        self._record_selection(run=run, skill=candidates[0])
        return TutorDecisionGateResult(status=TutorDecisionGateStatus.REBUILD_CONTEXT)

    def _validate_unbound_actions(
        self,
        *,
        decision: TutorDecision,
        policy: CapabilityPolicyContext,
    ) -> TutorDecisionGateResult | None:
        for request in decision.capability_requests:
            descriptor = self._catalog.capability(request.capability_id)
            if descriptor is None:
                return _deny("unknown_capability")
            if not policy.allows_descriptor(descriptor):
                return _deny("capability_not_policy_eligible")
            keys = tuple(field.key for field in request.arguments)
            if len(keys) != len(set(keys)) or not set(keys).issubset(descriptor.input_field_names):
                return _deny("capability_arguments_invalid")

        for proposal in decision.effect_proposals:
            effect_descriptor = self._catalog.effect(proposal.effect_type)
            if effect_descriptor is None:
                return _deny("unknown_effect_type")
            if not policy.allows_effect(effect_descriptor):
                return _deny("effect_not_policy_eligible")
            payload = payload_mapping_from_fields(proposal.payload)
            if payload is None:
                return _deny("effect_arguments_invalid")
            try:
                effect_descriptor.proposal_model.model_validate(payload)
            except ValidationError:
                return _deny("effect_arguments_invalid")
        return None

    def _record_selection(self, *, run: TutorRunSnapshot, skill: PublishedSkill) -> None:
        self._selection_store.record(
            run_id=run.run_id,
            input_revision=run.input_revision,
            selection=TutorSkillSelection(
                reference=skill.reference,
                manifest_hash=skill.manifest_hash,
                instruction_hash=skill.instruction_hash,
            ),
        )

    def _validate_capability_requests(
        self,
        *,
        decision: TutorDecision,
        skill: PublishedSkill,
        policy: CapabilityPolicyContext,
    ) -> TutorDecisionGateResult | None:
        for request in decision.capability_requests:
            descriptor = self._catalog.capability(request.capability_id)
            if descriptor is None:
                return _deny("unknown_capability")
            if request.capability_id not in skill.manifest.requires_capabilities:
                return _deny("capability_not_required_by_skill")
            if not policy.allows_descriptor(descriptor):
                return _deny("capability_not_policy_eligible")
            keys = tuple(field.key for field in request.arguments)
            if len(keys) != len(set(keys)) or not set(keys).issubset(descriptor.input_field_names):
                return _deny("capability_arguments_invalid")
        return None

    def _validate_effect_proposals(
        self,
        *,
        decision: TutorDecision,
        skill: PublishedSkill,
        policy: CapabilityPolicyContext,
    ) -> TutorDecisionGateResult | None:
        for proposal in decision.effect_proposals:
            descriptor = self._catalog.effect(proposal.effect_type)
            if descriptor is None:
                return _deny("unknown_effect_type")
            if proposal.effect_type not in skill.manifest.allowed_effect_types:
                return _deny("effect_not_allowed_by_skill")
            if not policy.allows_effect(descriptor):
                return _deny("effect_not_policy_eligible")
            payload = payload_mapping_from_fields(proposal.payload)
            if payload is None:
                return _deny("effect_arguments_invalid")
            try:
                descriptor.proposal_model.model_validate(payload)
            except ValidationError:
                return _deny("effect_arguments_invalid")
        return None

    def _selected_skill(self, *, run: TutorRunSnapshot) -> tuple[TutorSkillSelection, PublishedSkill] | None:
        selection = self._selection_store.get(run_id=run.run_id, input_revision=run.input_revision)
        if selection is None:
            return None
        skill = self._catalog.resolve_skill(selection.reference.skill_id, selection.reference.version)
        if skill is None:
            return None
        if selection.manifest_hash != skill.manifest_hash or selection.instruction_hash != skill.instruction_hash:
            return None
        return selection, skill


def _deny(code: str) -> TutorDecisionGateResult:
    return TutorDecisionGateResult(status=TutorDecisionGateStatus.DENIED, diagnostic_code=code)

class TeachingTutorDecisionGate:
    """Require one exact lesson-teaching Skill and one closed action for teaching runs."""

    _SKILL_ID = "tutor.lesson-teaching"
    _SKILL_VERSION = "1.1.0"
    _FREE_READING_ACTIONS = frozenset({
        "answer_question", "explain_concept", "show_example", "compare_examples", "wait_for_input",
    })
    _FREE_READING_DOMAIN_ACTIONS = frozenset({
        "summarize_progress", "explain_feedback", "remediate_prerequisite", "recommend_pause",
        "wait_for_input",
    })

    def __init__(
        self, *, base: _DecisionGate, catalog: SkillCatalogSnapshot,
        selection_store: TutorSkillSelectionStore, teaching: _TeachingContextRepository,
    ) -> None:
        self._base = base
        self._catalog = catalog
        self._selection_store = selection_store
        self._teaching = teaching

    def validate(self, *, run: TutorRunSnapshot, decision: TutorDecision) -> TutorDecisionGateResult:
        try:
            context = self._teaching.teaching_context(user_id=run.user_id, run_id=run.run_id)
        except ValueError:
            return _deny("teaching_authority_stale")
        base_validate = self._base.validate
        if context is None:
            if decision.teaching_step is not None:
                return _deny("teaching_scope_unexpected")
            return base_validate(run=run, decision=decision)
        base_result = base_validate(run=run, decision=decision)
        if base_result.status is not TutorDecisionGateStatus.APPROVED:
            return base_result
        if decision.teaching_step is None:
            return _deny("teaching_step_required")
        selection = self._selection_store.get(run_id=run.run_id, input_revision=run.input_revision)
        skill = self._catalog.resolve_skill(self._SKILL_ID, self._SKILL_VERSION)
        if selection is None or skill is None or selection.reference != skill.reference:
            return _deny("teaching_skill_required")
        if selection.manifest_hash != skill.manifest_hash or selection.instruction_hash != skill.instruction_hash:
            return _deny("teaching_skill_stale")
        step = decision.teaching_step
        objective = context.get("objective")
        active_focus = context.get("active_focus")
        suspended = context.get("suspended_focuses")
        session = context.get("session")
        if not isinstance(objective, dict) or not isinstance(session, dict):
            return _deny("teaching_context_invalid")
        if step.objective_id != str(objective.get("objective_id") or ""):
            return _deny("teaching_objective_invalid")
        allowed_handles = context.get("allowed_source_handles")
        if not isinstance(allowed_handles, list) or not set(step.source_handles).issubset({str(item) for item in allowed_handles}):
            return _deny("teaching_source_handle_invalid")
        candidate_focus_id = str(context.get("candidate_focus_id") or "")
        active_focus_id = str(active_focus.get("focus_id") or "") if isinstance(active_focus, dict) else ""
        if not isinstance(suspended, list):
            return _deny("teaching_context_invalid")
        suspended_ids = {
            str(item.get("focus_id") or "") for item in suspended if isinstance(item, dict)
        }
        resolution = step.focus_resolution.value
        if resolution == "push_child" and step.focus_id != candidate_focus_id:
            return _deny("teaching_child_focus_invalid")
        if resolution == "stay" and step.focus_id not in {active_focus_id, candidate_focus_id}:
            return _deny("teaching_active_focus_invalid")
        if resolution == "resolve_and_resume_parent" and step.focus_id not in suspended_ids:
            return _deny("teaching_parent_focus_invalid")
        if resolution == "replace_objective" and step.focus_id not in {
            str(objective.get("objective_id") or ""), candidate_focus_id,
        }:
            return _deny("teaching_replacement_focus_invalid")
        if resolution == "abandon_branch" and step.focus_id != active_focus_id:
            return _deny("teaching_abandoned_focus_invalid")
        if resolution == "wait" and step.focus_id not in {active_focus_id, candidate_focus_id}:
            return _deny("teaching_wait_focus_invalid")
        moves = tuple(item.value for item in step.teaching_moves or ())
        response_mode = step.learner_response_mode.value if step.learner_response_mode is not None else None
        if len(moves) < 2 or len(moves) > 4 or len(moves) != len(set(moves)) or response_mode is None:
            return _deny("teaching_step_v2_required")
        diagnostic_moves = {"prediction", "error_detection", "misconception_contrast", "micro_transfer"}
        if response_mode == "composer":
            if step.action.value not in {"check_understanding", "wait_for_input"} or not diagnostic_moves.intersection(moves):
                return _deny("teaching_response_mode_invalid")
        elif step.action.value in {"check_understanding", "wait_for_input"}:
            return _deny("teaching_response_mode_invalid")

        mode = str(session.get("mode") or "")
        stimulus = context.get("stimulus")
        domain_event = isinstance(stimulus, dict) and stimulus.get("kind") == "domain_event"
        free_reading_actions = (
            self._FREE_READING_ACTIONS | self._FREE_READING_DOMAIN_ACTIONS
            if domain_event else self._FREE_READING_ACTIONS
        )
        if mode == "free_reading" and step.action.value not in free_reading_actions:
            return _deny("free_reading_action_invalid")
        control_key = str(stimulus.get("control_key") or "") if isinstance(stimulus, dict) else ""
        if control_key == "change_example" and not {"worked_example", "counterexample"}.intersection(moves):
            return _deny("teaching_change_example_move_required")
        if control_key == "continue":
            recent_units = context.get("recent_teaching_units")
            if not isinstance(recent_units, list):
                return _deny("teaching_context_invalid")
            candidate_hash = hashlib.sha256(step.public_message.encode("utf-8")).hexdigest()
            candidate_signature = (step.action.value, tuple(sorted(moves)), response_mode)
            for unit in recent_units:
                if not isinstance(unit, dict) or unit.get("schema_version") != "teaching_action_receipt_v2":
                    continue
                if str(unit.get("public_message_hash") or "") == candidate_hash:
                    return _deny("teaching_unit_not_advanced")
                recent_moves = unit.get("teaching_moves")
                if not isinstance(recent_moves, list):
                    return _deny("teaching_context_invalid")
                recent_signature = (
                    str(unit.get("action") or ""),
                    tuple(sorted(str(item) for item in recent_moves)),
                    str(unit.get("learner_response_mode") or ""),
                )
                if str(unit.get("focus_id") or "") == step.focus_id and recent_signature == candidate_signature:
                    return _deny("teaching_unit_not_advanced")
        progress_completed = str(session.get("progress_status") or "") == "completed"
        completion_pause = step.pause_kind.value == "completion_pause"
        if completion_pause != progress_completed:
            return _deny("teaching_completion_pause_invalid")
        return TutorDecisionGateResult(status=TutorDecisionGateStatus.APPROVED)
