"""Catalog-constrained decision validation before Tutor capability or effect boundaries."""
from __future__ import annotations

from app.agents.harness.skill_catalog import CatalogSkillReference, PublishedSkill, SkillCatalogSnapshot
from app.agents.harness.contracts import (
    TutorDecision,
    TutorDecisionGateResult,
    TutorDecisionGateStatus,
    TutorRunSnapshot,
)
from app.services.tutor.capability_policy import CapabilityPolicyContext, CapabilityPolicyResolver
from app.services.tutor.skill_selection import TutorSkillSelection, TutorSkillSelectionStore


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
                return _deny("skill_selection_required")
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
            self._selection_store.record(
                run_id=run.run_id,
                input_revision=run.input_revision,
                selection=TutorSkillSelection(
                    reference=reference,
                    manifest_hash=skill.manifest_hash,
                    instruction_hash=skill.instruction_hash,
                ),
            )
            return TutorDecisionGateResult(status=TutorDecisionGateStatus.REBUILD_CONTEXT)
        return None

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