"""Policy-filtered catalog decoration for the existing bounded Tutor context loader."""
from __future__ import annotations

from dataclasses import replace

from app.agents.harness.capabilities import CapabilitySchemaExporter
from app.agents.harness.contracts import TutorContextInput, TutorContextSource, TutorRunSnapshot
from app.agents.harness.skill_catalog import PublishedSkill, SkillCatalogSnapshot
from app.services.tutor.capability_policy import CapabilityPolicyContext, CapabilityPolicyResolver
from app.services.tutor.ports import TutorContextLoader
from app.services.tutor.skill_selection import TutorSkillSelection, TutorSkillSelectionStore


class CatalogContextLoader:
    """Expose catalog facts only after policy and exact-selection validation."""

    def __init__(
        self,
        *,
        base_loader: TutorContextLoader,
        catalog: SkillCatalogSnapshot,
        policy_resolver: CapabilityPolicyResolver,
        selection_store: TutorSkillSelectionStore,
    ) -> None:
        self._base_loader = base_loader
        self._catalog = catalog
        self._policy_resolver = policy_resolver
        self._selection_store = selection_store

    def load_context(self, snapshot: TutorRunSnapshot, *, input_revision: int) -> TutorContextInput:
        base = self._base_loader.load_context(snapshot, input_revision=input_revision)
        policy = self._policy_resolver.resolve(run=snapshot, catalog=self._catalog)
        if input_revision != snapshot.input_revision or not policy.matches(run=snapshot, catalog=self._catalog):
            return replace(base, capability_schemas=())

        selected = self._selected_skill(snapshot)
        if selected is not None and not policy.allows_skill(selected[0].reference):
            selected = None
        if selected is None:
            system_descriptors = self._summary_descriptors(base=base, policy=policy)
        else:
            selection, skill = selected
            system_descriptors = (
                TutorContextSource(
                    source_id=f"catalog:selected:{selection.reference.key}",
                    content={
                        "id": skill.manifest.id,
                        "version": skill.manifest.version,
                        "manifest_hash": skill.manifest_hash,
                        "instruction_hash": skill.instruction_hash,
                        "instruction": skill.instruction,
                    },
                ),
                *base.system_descriptors,
            )

        references = (selected[0].reference,) if selected is not None else policy.eligible_skill_references
        visible_descriptors = {
            descriptor.reference: descriptor
            for reference in references
            for capability_id in policy.eligible_capability_ids
            if (descriptor := self._catalog.capability_for_skill(capability_id, reference)) is not None
        }
        capability_schemas = tuple(
            TutorContextSource(
                source_id=f"catalog:capability:{descriptor.reference}",
                content=CapabilitySchemaExporter.export(descriptor),
            )
            for descriptor in visible_descriptors.values()
            if policy.allows_descriptor(descriptor)
            and policy.runtime_supports(descriptor)
            and policy.remaining_capability_budget > 0
        )
        return replace(
            base,
            system_descriptors=system_descriptors,
            capability_schemas=capability_schemas,
        )

    def _summary_descriptors(self, *, base: TutorContextInput, policy: CapabilityPolicyContext) -> tuple[TutorContextSource, ...]:
        summaries = [
            {
                "id": skill.manifest.id,
                "version": skill.manifest.version,
                "owner": skill.manifest.owner,
                "kind": skill.manifest.kind,
                "summary": skill.manifest.summary,
                "required_capabilities": list(skill.manifest.requires_capabilities),
                "policy_tags": list(skill.manifest.policy_tags),
            }
            for skill in self._catalog.skills
            if policy.allows_skill(skill.reference)
        ]
        if not summaries:
            return base.system_descriptors
        return (
            TutorContextSource(
                source_id="catalog:eligible-skills",
                content={"catalog_digest": self._catalog.digest, "skills": summaries},
            ),
            *base.system_descriptors,
        )

    def _selected_skill(self, snapshot: TutorRunSnapshot) -> tuple[TutorSkillSelection, PublishedSkill] | None:
        selection = self._selection_store.get(run_id=snapshot.run_id, input_revision=snapshot.input_revision)
        if selection is None:
            return None
        skill = self._catalog.resolve_skill(selection.reference.skill_id, selection.reference.version)
        if skill is None:
            return None
        if selection.manifest_hash != skill.manifest_hash or selection.instruction_hash != skill.instruction_hash:
            return None
        return selection, skill
