"""Server-owned handler for the exact learning.plan.draft capability."""
from __future__ import annotations

import json
import logging
from contextlib import nullcontext
from collections.abc import Iterable, Mapping
from typing import Literal

from psycopg import Connection
from pydantic import ValidationError

from app.agents.harness.capabilities import (
    LearningPlanDraftCapabilityInput,
    LearningPlanDraftCapabilityOutput,
)
from app.agents.harness.contracts import TutorCapabilityStatus, TutorPayloadField, TutorRunSnapshot
from app.services.grounding.grounding_sources import GroundingSource, sources_for_language
from app.services.learning.contracts import LearningPlanNode, stable_key
from app.services.learning.item_supply.finite_course_targets import finite_course_targets, finite_node_description
from app.services.learning.material_selection import PostgresMaterialPlanningConsumer, material_transaction
from app.services.grounding.material_binding_repository import MaterialBindingConflict
from app.services.grounding.current_authorization import EvidenceDenied
from app.services.learning.plan_drafting import (
    CompactPlanModule,
    CompactPlanNode,
    CompactPlanProfile,
    LearningPlanDraftArtifact,
    LearningPlanSourceSummary,
    build_plan_draft,
    decode_compact_modules,
    decode_compact_profile,
)
from app.services.learning.planning_facts import PlanningFactError, PostgresPlanningFactRepository
from app.services.learning.plan_repository import (
    LearningPlanDraftConflict,
    LearningPlanSessionConflict,
    LearningPlanSessionNotFound,
    PostgresLearningPlanSessionRepository,
)
from app.services.runners.language_capabilities import (
    LanguageCapability,
    capabilities_for_public_course_language,
    get_language_capability,
)


logger = logging.getLogger(__name__)

PLANNING_CATALOG_DESCRIPTOR_SCHEMA_VERSION = "learning-plan-catalog-descriptor-v1"
PLANNING_CATALOG_DESCRIPTOR_LIMIT = 8

# Only server-owned stages, fields and guidance may cross the capability boundary.
_INVALID_GUIDANCE = {
    "compact_profile": "Repair profile_json using the compact profile schema.",
    "compact_modules": "Repair module JSON using the compact module and node schemas.",
    "plan_domain": "Use unique module/node keys and an acyclic graph with existing prerequisites.",
    "catalog_mapping": "Use only exact published catalog mappings and their required capabilities.",
    "session_language": "Keep profile.language_id aligned with the planning session language.",
    "confirmed_fact_conflict": "Copy the exact confirmed planning fact; do not paraphrase or replace it.",
    "confirmed_fact_validation": "Check the profile against authoritative confirmed planning facts.",
}
_PROFILE_FIELDS = {name: f"profile.{name}" for name in CompactPlanProfile.model_fields}
_MODULE_FIELDS = {name: f"modules.{name}" for name in CompactPlanModule.model_fields}
_NODE_FIELDS = {name: f"modules.nodes.{name}" for name in CompactPlanNode.model_fields}
_KNOWN_VALIDATION_FIELDS = {"profile", "modules", "plan"} | set(
    (*_PROFILE_FIELDS.values(), *_MODULE_FIELDS.values(), *_NODE_FIELDS.values())
)
_FACT_CONFLICT_FIELDS = {
    f"plan profile conflicts with confirmed fact {fact}": _PROFILE_FIELDS[profile]
    for fact, profile in (
        ("language_id", "language_id"), ("goal_text", "goal_text"),
        ("target_level", "target_level"), ("weekly_minutes", "weekly_minutes"),
        ("experience_level", "experience_level"), ("teaching_preferences", "teaching_preferences"),
        ("pace_constraints", "pace_summary"),
    )
}

_PLANNING_CATALOG_DESCRIPTOR_SQL = """
WITH latest_published AS (
  SELECT DISTINCT ON (versions.knowledge_key)
         versions.knowledge_key,
         versions.required_capabilities_json,
         publication.occurred_at AS publication_occurred_at,
         publication.state_version AS publication_state_version,
         versions.created_at AS version_created_at,
         versions.id AS version_id
  FROM tutor_learning_item_versions AS versions
  JOIN LATERAL (
    SELECT publication.state, publication.state_version, publication.occurred_at
    FROM tutor_learning_item_publication_events AS publication
    WHERE publication.version_id = versions.id
    ORDER BY publication.state_version DESC
    LIMIT 1
  ) AS publication ON publication.state = 'published'
  WHERE versions.language_id = %s
    AND versions.required_capabilities_json <@ %s::jsonb
  ORDER BY versions.knowledge_key,
           publication.occurred_at DESC,
           publication.state_version DESC,
           versions.created_at DESC,
           versions.id DESC
)
SELECT knowledge_key, required_capabilities_json
FROM latest_published
ORDER BY knowledge_key
LIMIT %s
"""

_PLANNING_CATALOG_VALIDATION_SQL = """
SELECT versions.knowledge_key, versions.required_capabilities_json
FROM tutor_learning_item_versions AS versions
JOIN LATERAL (
  SELECT publication.state
  FROM tutor_learning_item_publication_events AS publication
  WHERE publication.version_id = versions.id
  ORDER BY publication.state_version DESC
  LIMIT 1
) AS publication ON publication.state = 'published'
WHERE versions.language_id = %s
  AND versions.knowledge_key = ANY(%s::text[])
"""


class LearningPlanDraftCapabilityError(ValueError):
    """Typed learner-safe capability failure that can cross transaction boundaries."""

    def __init__(
        self,
        *,
        code: str,
        diagnostic_code: str,
        status: TutorCapabilityStatus,
        validation_stage: str | None = None,
        validation_field: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.diagnostic_code = diagnostic_code
        self.status = status
        self.safe_diagnostics: tuple[TutorPayloadField, ...] = ()
        if validation_stage in _INVALID_GUIDANCE and validation_field in _KNOWN_VALIDATION_FIELDS:
            assert validation_stage is not None and validation_field is not None
            self.safe_diagnostics = (
                TutorPayloadField(key="stage", value=validation_stage),
                TutorPayloadField(key="field_path", value=validation_field),
                TutorPayloadField(key="repair_guidance", value=_INVALID_GUIDANCE[validation_stage]),
            )


class LearningPlanDraftCapabilityHandler:
    """Validate nested compact input and persist only the typed domain artifact."""

    def __init__(self, conn: Connection[dict[str, object]], *,
                 material_feedback_consumer: PostgresMaterialPlanningConsumer | None = None) -> None:
        self._conn = conn
        self._material_feedback_consumer = material_feedback_consumer
        self._repository = PostgresLearningPlanSessionRepository(conn)
        self._facts = PostgresPlanningFactRepository(conn)

    def generate(
        self,
        *,
        run: TutorRunSnapshot,
        capability_input: LearningPlanDraftCapabilityInput,
    ) -> LearningPlanDraftCapabilityOutput:
        session_id: str | None = None
        try:
            with (material_transaction(self._conn) if self._material_feedback_consumer is not None
                  else self._conn.transaction()):
                session = self._repository.active_session_for_run(
                    user_id=run.user_id,
                    run_id=run.run_id,
                    input_revision=run.input_revision,
                    for_update=True,
                )
                session_id = str(session["id"])
                artifact = self._artifact(session=session, capability_input=capability_input)
                facts_fingerprint, facts_revision = self._facts.validate_profile(
                    user_id=run.user_id,
                    session_id=session_id,
                    profile=artifact.profile.model_dump(mode="json"),
                    require_complete=False,
                )
                feedback = (self._material_feedback_consumer.validate_successor_before_append(
                    run, session, artifact, capability_input) if self._material_feedback_consumer is not None else None)
                row, _replayed = self._repository.append_draft(
                    user_id=run.user_id,
                    run_id=run.run_id,
                    input_revision=run.input_revision,
                    artifact=artifact,
                    facts_fingerprint=facts_fingerprint,
                    facts_revision=facts_revision,
                )
                if feedback is not None and not _replayed and self._material_feedback_consumer is not None:
                    self._material_feedback_consumer.after_successor_append(
                        run=run, row=row, feedback=feedback,
                    )
                return LearningPlanDraftCapabilityOutput(
                    status="completed",
                    draft_id=str(row["id"]),
                    draft_version=_int(row["draft_version"]),
                    content_hash=str(row["content_hash"]),
                    quality_status="passed",
                )
        except PlanningFactError as exc:
            if session_id is not None:
                self._repository.record_safe_error(
                    user_id=run.user_id,
                    session_id=session_id,
                    code="LEARNING_PLAN_DRAFT_INVALID",
                )
            # Exact fixed-message matching only: never expose exception text or values.
            field = next((field for message, field in _FACT_CONFLICT_FIELDS.items()
                          if exc.args == (message,)), None)
            raise _invalid(
                stage="confirmed_fact_conflict" if field is not None else "confirmed_fact_validation",
                field=field or "profile",
            ) from exc
        except LearningPlanDraftCapabilityError as exc:
            if session_id is not None:
                self._repository.record_safe_error(
                    user_id=run.user_id,
                    session_id=session_id,
                    code=exc.code,
                )
            raise
        except LearningPlanSessionNotFound as exc:
            raise LearningPlanDraftCapabilityError(
                code="LEARNING_PLAN_CAPABILITY_UNAVAILABLE",
                diagnostic_code="learning_plan_session_unavailable",
                status=TutorCapabilityStatus.DENIED,
            ) from exc
        except (LearningPlanDraftConflict, LearningPlanSessionConflict, MaterialBindingConflict, EvidenceDenied) as exc:
            if session_id is not None:
                self._repository.record_safe_error(
                    user_id=run.user_id,
                    session_id=session_id,
                    code="LEARNING_PLAN_DRAFT_INVALID",
                )
            raise LearningPlanDraftCapabilityError(
                code="LEARNING_PLAN_DRAFT_INVALID",
                diagnostic_code="learning_plan_draft_conflict",
                status=TutorCapabilityStatus.DENIED,
            ) from exc

    def _artifact(
        self,
        *,
        session: dict[str, object],
        capability_input: LearningPlanDraftCapabilityInput,
    ) -> LearningPlanDraftArtifact:
        stage = "compact_profile"
        try:
            profile = decode_compact_profile(capability_input.profile_json)
            stage = "compact_modules"
            modules = decode_compact_modules(capability_input.module_values())
            stage = "plan_domain"
            artifact = build_validated_learning_plan_artifact(
                session=session,
                profile=profile,
                modules=modules,
            )
            stage = "catalog_mapping"
            validate_planning_catalog_mappings(
                self._conn,
                language_id=artifact.profile.language_id,
                nodes=artifact.plan.nodes,
            )
            return artifact
        except LearningPlanDraftCapabilityError:
            raise
        except ValueError as exc:
            field = "profile" if stage == "compact_profile" else "modules"
            if isinstance(exc, ValidationError):
                # Locations are input-controlled for extra keys. Render only exact known shapes.
                location = exc.errors(include_input=False, include_context=False, include_url=False)[0]["loc"]
                if location and isinstance(location[0], str):
                    fields = _PROFILE_FIELDS if stage == "compact_profile" else _MODULE_FIELDS
                    field = fields.get(location[0], field)
                    if (stage == "compact_modules" and len(location) >= 3
                            and location[0] == "nodes" and isinstance(location[1], int)
                            and isinstance(location[2], str)):
                        field = _NODE_FIELDS.get(location[2], field)
            raise _invalid(stage=stage, field=field) from exc


def build_validated_learning_plan_artifact(
    *,
    session: Mapping[str, object],
    profile: CompactPlanProfile,
    modules: tuple[CompactPlanModule, ...],
    change_reason: str | None = None,
) -> LearningPlanDraftArtifact:
    """Build one domain artifact for both Harness and Codex typed tool facades."""

    canonical, language_capabilities = _language(profile.language_id)
    if not language_capabilities or not all(item.enabled_for_public_selection for item in language_capabilities):
        raise LearningPlanDraftCapabilityError(
            code="LEARNING_LANGUAGE_NOT_SELECTABLE",
            diagnostic_code="learning_language_not_selectable",
            status=TutorCapabilityStatus.DENIED,
        )
    preferred = str(session.get("preferred_language_id") or "")
    if preferred and preferred != canonical:
        raise _invalid(stage="session_language", field="profile.language_id")
    sources = _source_summaries(language_capabilities)
    if not sources:
        raise LearningPlanDraftCapabilityError(
            code="LEARNING_PLAN_DRAFT_QUALITY_BLOCKED",
            diagnostic_code="learning_plan_source_quality_blocked",
            status=TutorCapabilityStatus.UNAVAILABLE,
        )
    normalized_profile = profile.model_copy(update={"language_id": canonical})
    artifact = build_plan_draft(
        profile=normalized_profile,
        modules=modules,
        sources=sources,
        change_reason=change_reason
        or (
            "Create the learner-confirmable initial learning plan draft."
            if session.get("current_draft_id") is None
            else "Replace the current learning plan draft after learner-requested changes."
        ),
    )
    _validate_quality(
        artifact=artifact,
        capabilities=language_capabilities,
        canonical_language_id=canonical,
    )
    return artifact


def _safe_catalog_rows(
    conn: Connection[dict[str, object]],
    query: str,
    params: tuple[object, ...],
) -> tuple[Mapping[str, object], ...] | None:
    """Run optional catalog reads in a savepoint without poisoning the caller transaction."""

    try:
        transaction = getattr(conn, "transaction", None)
        with transaction() if callable(transaction) else nullcontext():
            return tuple(conn.execute(query, params).fetchall())
    except Exception:
        # Optional descriptor failure may omit guidance. Explicit mappings are
        # separately rejected below; they never inherit this optional fallback.
        return None


def canonical_learning_language_id(value: str) -> str | None:
    """Return the server canonical language id, or None for an unknown id."""

    try:
        canonical, _ = _language(value)
    except LearningPlanDraftCapabilityError:
        return None
    return canonical


def read_planning_catalog_descriptor(
    conn: Connection[dict[str, object]],
    *,
    language_id: str,
    limit: int = PLANNING_CATALOG_DESCRIPTOR_LIMIT,
) -> dict[str, object] | None:
    """Read only bounded, latest-published catalog metadata for planning context."""

    if not 1 <= limit <= PLANNING_CATALOG_DESCRIPTOR_LIMIT:
        raise ValueError("planning catalog descriptor limit is invalid")
    canonical = canonical_learning_language_id(language_id)
    if canonical is None:
        return None
    rows = _safe_catalog_rows(
        conn,
        _PLANNING_CATALOG_DESCRIPTOR_SQL,
        (canonical, json.dumps(_allowed_planning_capabilities(canonical)), limit),
    )
    if rows is None:
        # Legacy databases may not have the item-bank tables yet. The main
        # plan-node database fence remains authoritative when a draft is used.
        return None
    return project_planning_catalog_descriptor(
        rows,
        language_id=canonical,
        limit=limit,
    )


def project_planning_catalog_descriptor(
    rows: Iterable[Mapping[str, object]],
    *,
    language_id: str,
    limit: int = PLANNING_CATALOG_DESCRIPTOR_LIMIT,
) -> dict[str, object]:
    """Project DB rows into the model-visible key/capability allowlist only."""

    if not 1 <= limit <= PLANNING_CATALOG_DESCRIPTOR_LIMIT:
        raise ValueError("planning catalog descriptor limit is invalid")
    canonical = canonical_learning_language_id(language_id)
    if canonical is None:
        raise ValueError("planning catalog language is not selectable")
    entries: dict[str, list[str]] = {}
    allowed = set(_allowed_planning_capabilities(canonical))
    for row in rows:
        try:
            key = stable_key(str(row.get("knowledge_key") or ""), label="catalog knowledge key")
            capabilities = _catalog_capabilities(row.get("required_capabilities_json"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if set(capabilities).issubset(allowed):
            entries.setdefault(key, list(capabilities))
    return {
        "schema_version": PLANNING_CATALOG_DESCRIPTOR_SCHEMA_VERSION,
        "items": [
            {
                "knowledge_key": key,
                "required_capabilities": entries[key],
            }
            for key in sorted(entries)[:limit]
        ],
    }


def validate_planning_catalog_mappings(
    conn: Connection[dict[str, object]],
    *,
    language_id: str,
    nodes: Iterable[LearningPlanNode],
) -> None:
    """Preflight explicit mappings; PostgreSQL plan-node scope remains authoritative."""

    mapped_nodes = tuple(node for node in nodes if node.catalog_knowledge_key is not None)
    if not mapped_nodes:
        return
    canonical, _ = _language(language_id)
    keys = tuple(dict.fromkeys(
        stable_key(str(node.catalog_knowledge_key), label="catalog knowledge key")
        for node in mapped_nodes
    ))
    rows = _safe_catalog_rows(
        conn,
        _PLANNING_CATALOG_VALIDATION_SQL,
        (canonical, list(keys)),
    )
    if rows is None:
        raise _catalog_mapping_invalid()
    validate_planning_catalog_mapping_rows(rows, nodes=mapped_nodes)


def validate_planning_catalog_mapping_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    nodes: Iterable[LearningPlanNode],
) -> None:
    """Validate mapping rows using the same capability-subset rule as the DB fence."""

    available: dict[str, list[tuple[str, ...]]] = {}
    for row in rows:
        try:
            key = stable_key(str(row.get("knowledge_key") or ""), label="catalog knowledge key")
            capabilities = _catalog_capabilities(row.get("required_capabilities_json"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        available.setdefault(key, []).append(capabilities)
    for node in nodes:
        node_key = node.catalog_knowledge_key
        if node_key is None:
            continue
        candidates = available.get(node_key, ())
        if not candidates or not any(
            set(required).issubset(set(node.required_capabilities))
            for required in candidates
        ):
            raise _catalog_mapping_invalid()


def _catalog_capabilities(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, (list, tuple)) or isinstance(value, (bytes, bytearray)):
        raise ValueError("stored catalog capabilities are invalid")
    capabilities = tuple(stable_key(str(item), label="catalog capability") for item in value)
    if not capabilities or len(capabilities) != len(set(capabilities)):
        raise ValueError("stored catalog capabilities are invalid")
    return capabilities


def _catalog_mapping_invalid() -> LearningPlanDraftCapabilityError:
    return LearningPlanDraftCapabilityError(
        code="LEARNING_PLAN_DRAFT_INVALID",
        diagnostic_code="learning_plan_catalog_mapping_invalid",
        status=TutorCapabilityStatus.DENIED,
    )


def _allowed_planning_capabilities(language_id: str) -> tuple[str, ...]:
    canonical, capabilities = _language(language_id)
    allowed = {canonical}
    for capability in capabilities:
        allowed.add(capability.language_id)
        if capability.runner_key != "none":
            allowed.add(capability.runner_key)
    return tuple(sorted(allowed))


def _language(value: str) -> tuple[str, tuple[LanguageCapability, ...]]:
    normalized = value.strip().lower()
    direct = get_language_capability(normalized)
    if direct is not None:
        return direct.language_id, (direct,)
    public = capabilities_for_public_course_language(normalized)
    if public:
        return normalized, public
    raise LearningPlanDraftCapabilityError(
        code="LEARNING_LANGUAGE_NOT_SELECTABLE",
        diagnostic_code="learning_language_not_selectable",
        status=TutorCapabilityStatus.DENIED,
    )


def _source_summaries(capabilities: tuple[LanguageCapability, ...]) -> tuple[LearningPlanSourceSummary, ...]:
    accepted: list[GroundingSource] = []
    seen: set[str] = set()
    for capability in capabilities:
        for source in sources_for_language(capability.language_id):
            if source.source_id in seen or not _trust_matches(source.trust_tier, capability.source_trust_policy):
                continue
            seen.add(source.source_id)
            accepted.append(source)
    return tuple(
        LearningPlanSourceSummary(
            source_id=source.source_id,
            display_name=source.display_name,
            trust_tier=source.trust_tier,
        )
        for source in accepted[:8]
    )


def _trust_matches(trust_tier: str, policy: str) -> bool:
    if policy == "official":
        return trust_tier == "official"
    if policy == "trusted_de_facto":
        return trust_tier in {"official", "trusted_de_facto"}
    return trust_tier == "internal" if policy == "internal" else False


def _validate_quality(
    *,
    artifact: LearningPlanDraftArtifact,
    capabilities: tuple[LanguageCapability, ...],
    canonical_language_id: str,
) -> None:
    if not any(module.is_core for module in artifact.plan.modules) or not any(node.is_core for node in artifact.plan.nodes):
        _log_quality_rejection(artifact, capabilities, canonical_language_id, branch="core_shape_missing")
        raise _quality_blocked()
    allowed_capabilities = {canonical_language_id}
    for capability in capabilities:
        allowed_capabilities.add(capability.language_id)
        if capability.runner_key != "none":
            allowed_capabilities.add(capability.runner_key)
    for node in artifact.plan.nodes:
        if all(required in allowed_capabilities for required in node.required_capabilities):
            continue
        # Exact closed curriculum semantics may refine an already selectable
        # language. This grants no runtime/source/item authority or label prefix.
        if not any(capability.language_id == canonical_language_id and capability.enabled_for_public_selection
                   for capability in capabilities) or not any(
            target.language_id == canonical_language_id
            and node.required_capabilities == target.required_capabilities
            and node.description == finite_node_description(target.target_id)
            for target in finite_course_targets()
        ):
            _log_quality_rejection(artifact, capabilities, canonical_language_id,
                                   branch="capability_match_failed", node=node)
            raise _quality_blocked()


def _log_quality_rejection(
    artifact: LearningPlanDraftArtifact,
    capabilities: tuple[LanguageCapability, ...],
    canonical_language_id: str,
    *,
    branch: Literal["core_shape_missing", "capability_match_failed"],
    node: LearningPlanNode | None = None,
) -> None:
    """Internal shape/match diagnostics only; never serialize learner inputs."""
    module_index, node_index = next(
        ((mi, ni) for mi, module in enumerate(artifact.plan.modules)
         for ni, item in enumerate(module.nodes) if item is node), (None, None))
    payload = {
        "branch": branch,
        "module_count": len(artifact.plan.modules),
        "core_module_count": sum(module.is_core for module in artifact.plan.modules),
        "node_count": len(artifact.plan.nodes),
        "core_node_count": sum(item.is_core for item in artifact.plan.nodes),
        "module_index": module_index,
        "node_index": node_index,
        "description_length": None if node is None else len(node.description),
        "capability_count": None if node is None else len(node.required_capabilities),
        "language_selectable": any(capability.language_id == canonical_language_id
            and capability.enabled_for_public_selection for capability in capabilities),
        "registered_targets": [] if node is None else [
            {"target_id": target.target_id,
             "language_match": target.language_id == canonical_language_id,
             "description_exact": node.description == finite_node_description(target.target_id),
             "capabilities_exact": node.required_capabilities == target.required_capabilities}
            for target in finite_course_targets()
        ],
    }
    logger.warning("learning_plan_draft_quality_diagnostic %s",
                   json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _invalid(*, stage: str, field: str) -> LearningPlanDraftCapabilityError:
    return LearningPlanDraftCapabilityError(
        code="LEARNING_PLAN_DRAFT_INVALID",
        diagnostic_code="learning_plan_draft_invalid",
        status=TutorCapabilityStatus.DENIED,
        validation_stage=stage,
        validation_field=field,
    )


def _quality_blocked() -> LearningPlanDraftCapabilityError:
    return LearningPlanDraftCapabilityError(
        code="LEARNING_PLAN_DRAFT_QUALITY_BLOCKED",
        diagnostic_code="learning_plan_draft_quality_blocked",
        status=TutorCapabilityStatus.UNAVAILABLE,
    )


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
