"""Policy facts and deterministic resolvers for catalog-bound Tutor capabilities."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

from app.agents.harness.capabilities import CapabilityDescriptor, EffectDescriptor, is_catalog_identifier
from app.agents.harness.skill_catalog import CatalogSkillReference, SkillCatalogSnapshot
from app.agents.harness.contracts import TutorRunSnapshot


TutorRunOrigin = Literal["interactive", "proactive"]


@dataclass(frozen=True)
class CapabilityPolicyContext:
    """Authoritative facts for one run revision; model output cannot alter them."""

    run_id: str
    user_id: str
    origin: TutorRunOrigin
    input_revision: int
    catalog_digest: str
    eligible_skill_references: tuple[CatalogSkillReference, ...] = ()
    eligible_capability_ids: tuple[str, ...] = ()
    eligible_effect_types: tuple[str, ...] = ()
    granted_policy_tags: tuple[str, ...] = ()
    allowed_origins: tuple[TutorRunOrigin, ...] = ()
    consent_granted: bool = False
    runtime_available_capability_ids: tuple[str, ...] = ()
    remaining_capability_budget: int = 0
    allowed_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id or not self.user_id:
            raise ValueError("capability policy requires run and user scope")
        if self.origin not in {"interactive", "proactive"}:
            raise ValueError("capability policy origin is invalid")
        if self.input_revision < 0:
            raise ValueError("capability policy revision must be non-negative")
        if len(self.catalog_digest) != 64 or any(character not in "0123456789abcdef" for character in self.catalog_digest):
            raise ValueError("capability policy requires a catalog digest")
        if self.remaining_capability_budget < 0:
            raise ValueError("capability policy budget must be non-negative")
        origins = tuple(self.allowed_origins)
        if len(set(origins)) != len(origins) or any(origin not in {"interactive", "proactive"} for origin in origins):
            raise ValueError("allowed_origins must contain unique supported origins")
        object.__setattr__(self, "allowed_origins", origins)
        for name in (
            "eligible_capability_ids",
            "eligible_effect_types",
            "granted_policy_tags",
            "runtime_available_capability_ids",
            "allowed_source_ids",
        ):
            values = tuple(getattr(self, name))
            if len(set(values)) != len(values) or any(not is_catalog_identifier(value) for value in values):
                raise ValueError(f"{name} must contain unique stable identifiers")
            object.__setattr__(self, name, values)
        references = tuple(self.eligible_skill_references)
        if len({reference.key for reference in references}) != len(references):
            raise ValueError("eligible Skill references must be unique")
        object.__setattr__(self, "eligible_skill_references", references)

    def matches(self, *, run: TutorRunSnapshot, catalog: SkillCatalogSnapshot) -> bool:
        return (
            self.run_id == run.run_id
            and self.user_id == run.user_id
            and self.input_revision == run.input_revision
            and self.catalog_digest == catalog.digest
        )

    def allows_skill(self, reference: CatalogSkillReference) -> bool:
        return self.origin in self.allowed_origins and reference in self.eligible_skill_references

    def allows_descriptor(self, descriptor: CapabilityDescriptor) -> bool:
        return (
            self.consent_granted
            and self.origin in self.allowed_origins
            and descriptor.capability_id in self.eligible_capability_ids
            and set(descriptor.policy_tags).issubset(self.granted_policy_tags)
        )

    def runtime_supports(self, descriptor: CapabilityDescriptor) -> bool:
        return descriptor.capability_id in self.runtime_available_capability_ids

    def allows_effect(self, descriptor: EffectDescriptor) -> bool:
        return (
            self.consent_granted
            and self.origin in self.allowed_origins
            and descriptor.effect_type in self.eligible_effect_types
            and set(descriptor.policy_tags).issubset(self.granted_policy_tags)
        )


class CapabilityPolicyResolver(Protocol):
    def resolve(
        self,
        *,
        run: TutorRunSnapshot,
        catalog: SkillCatalogSnapshot,
    ) -> CapabilityPolicyContext: ...


class DefaultDenyCapabilityPolicyResolver:
    """Production-safe placeholder until durable policy facts are composed."""

    def resolve(
        self,
        *,
        run: TutorRunSnapshot,
        catalog: SkillCatalogSnapshot,
    ) -> CapabilityPolicyContext:
        return CapabilityPolicyContext(
            run_id=run.run_id,
            user_id=run.user_id,
            origin="interactive",
            input_revision=run.input_revision,
            catalog_digest=catalog.digest,
        )


class InMemoryCapabilityPolicyResolver:
    """Revision-indexed fake for focused tests; it never infers permissions."""

    def __init__(self, contexts: Iterable[CapabilityPolicyContext] = ()) -> None:
        self._contexts: dict[tuple[str, int], CapabilityPolicyContext] = {}
        self.calls: list[tuple[str, int]] = []
        for context in contexts:
            self.add(context)

    def add(self, context: CapabilityPolicyContext) -> None:
        self._contexts[(context.run_id, context.input_revision)] = context

    def resolve(
        self,
        *,
        run: TutorRunSnapshot,
        catalog: SkillCatalogSnapshot,
    ) -> CapabilityPolicyContext:
        self.calls.append((run.run_id, run.input_revision))
        return self._contexts.get(
            (run.run_id, run.input_revision),
            DefaultDenyCapabilityPolicyResolver().resolve(run=run, catalog=catalog),
        )