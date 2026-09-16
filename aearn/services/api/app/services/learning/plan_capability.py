"""Server-owned handler for the exact learning.plan.draft capability."""
from __future__ import annotations

import json
from contextlib import nullcontext
from collections.abc import Iterable, Mapping

from psycopg import Connection

from app.agents.harness.capabilities import (
    LearningPlanDraftCapabilityInput,
    LearningPlanDraftCapabilityOutput,
)
from app.agents.harness.contracts import TutorCapabilityStatus, TutorRunSnapshot
from app.services.grounding.grounding_sources import GroundingSource, sources_for_language
from app.services.learning.contracts import LearningPlanNode, stable_key
from app.services.learning.plan_drafting import (
    CompactPlanModule,
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


PLANNING_CATALOG_DESCRIPTOR_SCHEMA_VERSION = "learning-plan-catalog-descriptor-v1"
PLANNING_CATALOG_DESCRIPTOR_LIMIT = 8

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
    ) -> None:
        super().__init__(code)
        self.code = code
        self.diagnostic_code = diagnostic_code
        self.status = status


class LearningPlanDraftCapabilityHandler:
    """Validate nested compact input and persist only the typed domain artifact."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn
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
            with self._conn.transaction():
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
                row, _replayed = self._repository.append_draft(
                    user_id=run.user_id,
                    run_id=run.run_id,
                    input_revision=run.input_revision,
                    artifact=artifact,
                    facts_fingerprint=facts_fingerprint,
                    facts_revision=facts_revision,
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
            raise _invalid() from exc
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
        except (LearningPlanDraftConflict, LearningPlanSessionConflict) as exc:
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
        try:
            profile = decode_compact_profile(capability_input.profile_json)
            modules = decode_compact_modules(capability_input.module_values())
            artifact = build_validated_learning_plan_artifact(
                session=session,
                profile=profile,
                modules=modules,
            )
            validate_planning_catalog_mappings(
                self._conn,
                language_id=artifact.profile.language_id,
                nodes=artifact.plan.nodes,
            )
            return artifact
        except LearningPlanDraftCapabilityError:
            raise
        except ValueError as exc:
            raise _invalid() from exc


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
        raise _invalid()
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
        raise _quality_blocked()
    allowed_capabilities = {canonical_language_id}
    for capability in capabilities:
        allowed_capabilities.add(capability.language_id)
        if capability.runner_key != "none":
            allowed_capabilities.add(capability.runner_key)
    if any(
        required not in allowed_capabilities
        for node in artifact.plan.nodes
        for required in node.required_capabilities
    ):
        raise _quality_blocked()


def _invalid() -> LearningPlanDraftCapabilityError:
    return LearningPlanDraftCapabilityError(
        code="LEARNING_PLAN_DRAFT_INVALID",
        diagnostic_code="learning_plan_draft_invalid",
        status=TutorCapabilityStatus.DENIED,
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
