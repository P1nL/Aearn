"""Catalog-aware, default-deny dispatch for the sole registry-only Tutor capability."""
from __future__ import annotations

import json

from urllib.parse import urlparse

from pydantic import ValidationError

from app.agents.harness.capabilities import (
    GROUNDING_RETRIEVE_CAPABILITY_ID,
    CapabilityMode,
    GroundingCitationOutput,
    GroundingRetrieveInput,
    GroundingRetrieveOutput,
)
from app.agents.harness.contracts import (
    MAX_TUTOR_PAYLOAD_VALUE_LENGTH,
    TutorCapabilityRequest,
    TutorCapabilityResult,
    TutorCapabilityStatus,
    TutorPayloadField,
    payload_mapping_from_fields,
    TutorRunSnapshot,
)
from app.agents.harness.skill_catalog import SkillCatalogSnapshot
from app.services.grounding.grounding_sources import GroundingSource, get_grounding_source, sources_for_language
from app.services.tutor.capability_policy import CapabilityPolicyResolver
from app.services.tutor.grounding_lookup import GroundingLookup, GroundingLookupItem, GroundingLookupQuery
from app.services.tutor.skill_selection import TutorSkillSelectionStore


class CatalogCapabilityGateway:
    """Dispatch descriptor-first only; no model field can select an external target."""

    def __init__(
        self,
        *,
        catalog: SkillCatalogSnapshot,
        policy_resolver: CapabilityPolicyResolver,
        selection_store: TutorSkillSelectionStore,
        grounding_lookup: GroundingLookup,
    ) -> None:
        self._catalog = catalog
        self._policy_resolver = policy_resolver
        self._selection_store = selection_store
        self._grounding_lookup = grounding_lookup

    def dispatch(
        self,
        *,
        run: TutorRunSnapshot,
        request: TutorCapabilityRequest,
    ) -> TutorCapabilityResult:
        policy = self._policy_resolver.resolve(run=run, catalog=self._catalog)
        if not policy.matches(run=run, catalog=self._catalog):
            return _denied(request, "policy_context_stale")
        descriptor = self._catalog.capability(request.capability_id)
        if descriptor is None or descriptor.capability_id != GROUNDING_RETRIEVE_CAPABILITY_ID:
            return _denied(request, "unknown_capability")
        if descriptor.mode is not CapabilityMode.READ:
            return _denied(request, "capability_mode_not_allowed")
        if not policy.allows_descriptor(descriptor):
            return _denied(request, "capability_not_policy_eligible")
        if not policy.runtime_supports(descriptor):
            return _unavailable(request, "capability_runtime_unavailable")
        if policy.remaining_capability_budget <= 0 or run.capability_call_count >= run.policy.max_capability_calls:
            return _denied(request, "capability_budget_exhausted")

        selected = self._selection_store.get(run_id=run.run_id, input_revision=run.input_revision)
        if selected is None:
            return _denied(request, "skill_selection_required")
        skill = self._catalog.resolve_skill(selected.reference.skill_id, selected.reference.version)
        if skill is None or selected.manifest_hash != skill.manifest_hash or selected.instruction_hash != skill.instruction_hash:
            return _denied(request, "selected_skill_not_resolved")
        if not policy.allows_skill(selected.reference):
            return _denied(request, "skill_not_policy_eligible")
        if descriptor.capability_id not in skill.manifest.requires_capabilities:
            return _denied(request, "capability_not_required_by_skill")

        arguments = _decode_declared_arguments(request=request, declared_fields=descriptor.input_field_names)
        if arguments is None:
            return _denied(request, "capability_arguments_invalid")
        try:
            grounding_input = GroundingRetrieveInput.model_validate(arguments)
        except ValidationError:
            return _denied(request, "grounding_input_invalid")

        registry_sources = sources_for_language(grounding_input.language_id_or_alias)
        if not registry_sources:
            return _unavailable(request, "unsupported_grounding_language")
        registry_source_ids = {source.source_id for source in registry_sources}
        source_ids = tuple(sorted(registry_source_ids & set(policy.allowed_source_ids)))
        if not source_ids:
            return _denied(request, "grounding_source_scope_denied")

        try:
            results = self._grounding_lookup.lookup(
                query=GroundingLookupQuery(
                    language_id_or_alias=grounding_input.language_id_or_alias,
                    query_text=grounding_input.query_text,
                    topic_tags=grounding_input.topic_tags,
                    top_k=grounding_input.top_k,
                ),
                source_ids=source_ids,
            )
        except Exception:
            return _unavailable(request, "grounding_lookup_unavailable")

        filtered = tuple(
            item
            for item in results
            if _matches_registry_scope(
                item=item,
                source_ids=source_ids,
                registry_sources=registry_sources,
            )
        )[: grounding_input.top_k]
        try:
            output = _validated_grounding_output(filtered)
        except ValidationError:
            return _unavailable(request, "grounding_lookup_invalid_result")
        if not output.snippets:
            return TutorCapabilityResult(
                request_id=request.request_id,
                status=TutorCapabilityStatus.COMPLETED,
                safe_result=(TutorPayloadField(key="grounding_status", value="empty"),),
                diagnostic_code="grounding_empty",
            )
        return TutorCapabilityResult(
            request_id=request.request_id,
            status=TutorCapabilityStatus.COMPLETED,
            safe_result=_safe_grounding_fields(output),
            diagnostic_code="grounding_completed",
        )


def _decode_declared_arguments(
    *,
    request: TutorCapabilityRequest,
    declared_fields: frozenset[str],
) -> dict[str, object] | None:
    if any(field.key not in declared_fields for field in request.arguments):
        return None
    return payload_mapping_from_fields(request.arguments)


def _matches_registry_scope(
    *,
    item: GroundingLookupItem,
    source_ids: tuple[str, ...],
    registry_sources: tuple[GroundingSource, ...],
) -> bool:
    if item.source_id not in source_ids:
        return False
    source = get_grounding_source(item.source_id)
    if source is None or source not in registry_sources:
        return False
    if item.language_id != source.language_id or item.trust_tier != source.trust_tier:
        return False
    return _url_is_allowlisted(item.canonical_url, source)


def _url_is_allowlisted(canonical_url: str, source: GroundingSource) -> bool:
    parsed = urlparse(canonical_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    hostname = (parsed.hostname or "").lower()
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in source.allowlisted_domains)


def _validated_grounding_output(items: tuple[GroundingLookupItem, ...]) -> GroundingRetrieveOutput:
    return GroundingRetrieveOutput.model_validate(
        {
            "status": "completed",
            "snippets": [
                {
                    "content": item.content,
                    "citation": {
                        "source_id": item.source_id,
                        "citation_id": item.citation_id,
                        "title": item.title,
                        "canonical_url": item.canonical_url,
                        "section_path": item.section_path,
                        "trust_tier": item.trust_tier,
                        "content_hash": item.content_hash,
                        "relevance_score": item.relevance_score,
                        "match_reasons": item.match_reasons,
                    },
                }
                for item in items
            ],
        }
    )


def _safe_grounding_fields(output: GroundingRetrieveOutput) -> tuple[TutorPayloadField, ...]:
    fields: list[TutorPayloadField] = []
    for index, snippet in enumerate(output.snippets, start=1):
        fields.extend(
            (
                TutorPayloadField(key=f"snippet_{index}", value=_bounded_text(snippet.content, 160)),
                TutorPayloadField(key=f"citation_{index}", value=_citation_json(snippet.citation)),
                TutorPayloadField(key=f"content_hash_{index}", value=snippet.citation.content_hash),
            )
        )
    return tuple(fields)


def _citation_json(citation: GroundingCitationOutput) -> str:
    candidates = (
        {
            "source_id": citation.source_id,
            "citation_id": citation.citation_id,
            "title": _bounded_text(citation.title, 40),
            "canonical_url": _bounded_text(citation.canonical_url, 88),
            "section_path": [_bounded_text(value, 20) for value in citation.section_path[:2]],
            "trust_tier": citation.trust_tier,
            "relevance_score": round(citation.relevance_score, 3),
            "match_reasons": list(citation.match_reasons[:3]),
        },
        {
            "source_id": citation.source_id,
            "citation_id": citation.citation_id,
            "title": _bounded_text(citation.title, 32),
            "canonical_url": _bounded_text(citation.canonical_url, 72),
            "trust_tier": citation.trust_tier,
            "match_reasons": list(citation.match_reasons[:2]),
        },
        {
            "source_id": citation.source_id,
            "citation_id": citation.citation_id,
            "canonical_url": _bounded_text(citation.canonical_url, 64),
            "trust_tier": citation.trust_tier,
        },
    )
    for candidate in candidates:
        serialized = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(serialized) <= MAX_TUTOR_PAYLOAD_VALUE_LENGTH:
            return serialized
    return json.dumps({"source_id": citation.source_id, "citation_id": citation.citation_id}, separators=(",", ":"))


def _bounded_text(value: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= maximum:
        return normalized
    if maximum <= 3:
        return "." * maximum
    return normalized[: maximum - 3].rstrip() + "..."


def _denied(request: TutorCapabilityRequest, code: str) -> TutorCapabilityResult:
    return TutorCapabilityResult(
        request_id=request.request_id,
        status=TutorCapabilityStatus.DENIED,
        safe_result=(TutorPayloadField(key="code", value=code),),
        diagnostic_code=code,
    )


def _unavailable(request: TutorCapabilityRequest, code: str) -> TutorCapabilityResult:
    return TutorCapabilityResult(
        request_id=request.request_id,
        status=TutorCapabilityStatus.UNAVAILABLE,
        safe_result=(TutorPayloadField(key="code", value=code),),
        diagnostic_code=code,
    )
