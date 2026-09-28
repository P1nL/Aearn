"""One-shot C-admitted corpus -> real D internal planning successor acceptance.

Never fetches sources, seeds corpus, signs a review, creates an actor grant, or
replaces the configured provider's decision transport. Operator provisions an
API-created parent draft and a separate pending target run beforehand.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from contextlib import contextmanager
import urllib.request
from urllib.parse import urlsplit
from dataclasses import asdict
import hashlib
import json
import os
import signal
from pathlib import Path
import sys
import traceback
from typing import Any
from uuid import UUID

import psycopg

API = Path(__file__).resolve().parents[2] / "services" / "api"
C = Path(__file__).resolve().parents[1] / "rag-c-live"
CONTROL = Path(__file__).resolve().parents[1] / "rag-c-source-control"
for path in (API, CONTROL, C):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core.config import Settings, get_settings  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.services.grounding.autonomous.access_policy import AccessRequest, AuthoritySnapshot, AutonomousGates  # noqa: E402
from app.services.grounding.autonomous.contracts import LearningMaterialDemand, RagBudgetDelegation, SubjectScope  # noqa: E402
from app.services.grounding.autonomous.corpus_governance import CorpusGovernance, PostgresCorpusAuthority  # noqa: E402
from app.services.grounding.autonomous.registered_source_bridge_host import SignedDispatchProofVerifier  # noqa: E402
from app.services.grounding.autonomous.registered_source_provenance import PostgresCurrentCaptureProvenanceResolver  # noqa: E402
from app.services.grounding.autonomous.source_review_repository import SourceReviewRepository  # noqa: E402
from app.services.grounding.autonomous.sqlite_select_automated_review import SQLiteSelectAutomatedReviewVerifier  # noqa: E402
from app.services.grounding.evidence_binding_v2 import EvidenceSelection  # noqa: E402
from app.services.grounding.material_binding_repository import PostgresMaterialBindingRepository, goal_hash_for_node  # noqa: E402
from app.services.grounding.material_contracts_v2 import DraftScope, NodeMaterialRequirement, digest  # noqa: E402
from app.services.learning.material_planning_composition import build_internal_material_planning_dispatcher  # noqa: E402
from app.services.learning.material_semantics import PrimaryMaterialSemanticReviewer  # noqa: E402
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway  # noqa: E402
from app.services.llm.llm_client import OpenAICompatibleClient  # noqa: E402
from app.services.llm.provider_diagnostics import ProviderDiagnosticStore  # noqa: E402
from automated_admission import KEY_ID, SERVICE_PUBLIC_SHA256, _read_provisional  # noqa: E402
from control_runtime import CONFIG, DB, PIN, _absolute, _root_file, _root_json  # noqa: E402
from protocol import Scope  # noqa: E402
from app.services.grounding.subject_registry import get_grounding_subject  # noqa: E402


class Denied(ValueError):
    """Public safe error code; never include DB/provider exception details."""

class WallDeadlineExceeded(BaseException):
    """Not swallowed by gateway Exception handlers or bounded repair loops."""


def parent_successor_http_window(
    audit: Mapping[str, object],
    *,
    successor_prior_http_attempts: int,
    successor_phase_http_cap: int,
    successor_cumulative_http_cap: int,
) -> dict[str, int]:
    """Reconcile an immutable parent budget with a separately approved successor window."""
    try:
        parent_prior = audit["prior_http_attempts"]
        parent_actual = audit["model_http_attempts"]
        parent_phase_cap = audit["phase_http_cap"]
        parent_cumulative_cap = audit["cumulative_http_cap"]
        if (
            type(parent_prior) is not int
            or parent_prior < 0
            or type(parent_actual) is not int
            or not 1 <= parent_actual <= 8
            or type(parent_phase_cap) is not int
            or not 1 <= parent_phase_cap <= 8
            or parent_actual > parent_phase_cap
            or type(parent_cumulative_cap) is not int
            or parent_prior + parent_phase_cap > parent_cumulative_cap
        ):
            raise Denied("PARENT_TRANSPORT_PROOF_MISSING")
        if (
            type(successor_prior_http_attempts) is not int
            or successor_prior_http_attempts != parent_prior + parent_actual
        ):
            raise Denied("PARENT_LEDGER_MISMATCH")
        if (
            type(successor_phase_http_cap) is not int
            or not 1 <= successor_phase_http_cap <= 8
            or type(successor_cumulative_http_cap) is not int
            or successor_prior_http_attempts + successor_phase_http_cap
            > successor_cumulative_http_cap
        ):
            raise Denied("CUMULATIVE_MODEL_BOUND_DENIED")
        return {
            "parent_prior_http_attempts": parent_prior,
            "parent_phase_http_cap": parent_phase_cap,
            "parent_cumulative_http_cap": parent_cumulative_cap,
            "successor_prior_http_attempts": successor_prior_http_attempts,
            "successor_phase_http_cap": successor_phase_http_cap,
            "successor_cumulative_http_cap": successor_cumulative_http_cap,
        }
    except Denied:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise Denied("PARENT_TRANSPORT_PROOF_MISSING") from exc


def install_private_database(dsn: str) -> None:
    """Keep DB credentials out of Docker env/argv; process-local after root-file read."""
    if os.environ.get("DATABASE_URL"):
        raise Denied("DATABASE_ENV_ALREADY_SET")
    os.environ["DATABASE_URL"] = dsn
    get_settings.cache_clear()


def install_private_provider(path: str) -> None:
    """Strict root-owned JSON, never echo values or embed them in Docker metadata."""
    values, _ = _root_json(_absolute(path))
    kind = values.get("LLM_TYPE")
    required = ({"LLM_TYPE", "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"}
                if kind == "deepseek" else
                {"LLM_TYPE", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"}
                if kind == "openai" else set())
    if not required or set(values) != required or any(type(values[k]) is not str or not values[k].strip()
                                                       or "\n" in values[k] or "\r" in values[k] for k in required):
        raise Denied("PROVIDER_CONFIG_DENIED")
    if any(os.environ.get(k) for k in required):
        raise Denied("PROVIDER_ENV_ALREADY_SET")
    os.environ.update(values)
    get_settings.cache_clear()

# Explicit nonsecret Settings transport from the host effective configuration.
# Never export Settings wholesale: it contains provider keys, DSNs and user data.
RUNTIME_FIELDS = {
    "tutor_deepseek_v4_flash_context_window_tokens": "TUTOR_DEEPSEEK_V4_FLASH_CONTEXT_WINDOW_TOKENS",
    "tutor_deepseek_v4_flash_input_limit_tokens": "TUTOR_DEEPSEEK_V4_FLASH_INPUT_LIMIT_TOKENS",
    "tutor_deepseek_v4_flash_max_output_tokens": "TUTOR_DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS",
    "tutor_deepseek_v4_flash_decision_max_output_tokens": "TUTOR_DEEPSEEK_V4_FLASH_DECISION_MAX_OUTPUT_TOKENS",
    "tutor_deepseek_v4_flash_max_dynamic_target_tokens": "TUTOR_DEEPSEEK_V4_FLASH_MAX_DYNAMIC_TARGET_TOKENS",
    "tutor_default_context_window_tokens": "TUTOR_CONTEXT_WINDOW_TOKENS",
    "tutor_default_output_reserve_tokens": "TUTOR_CONTEXT_OUTPUT_RESERVE_TOKENS",
    "tutor_default_decision_max_output_tokens": "TUTOR_DECISION_MAX_OUTPUT_TOKENS",
    "tutor_context_protocol_reserve_tokens": "TUTOR_CONTEXT_PROTOCOL_RESERVE_TOKENS",
    "tutor_context_safety_margin_tokens": "TUTOR_CONTEXT_SAFETY_MARGIN_TOKENS",
    "tutor_context_max_dynamic_target_tokens": "TUTOR_CONTEXT_MAX_DYNAMIC_TARGET_TOKENS",
    "tutor_context_compact_target_tokens": "TUTOR_CONTEXT_COMPACT_TARGET_TOKENS",
    "tutor_context_normal_target_tokens": "TUTOR_CONTEXT_NORMAL_TARGET_TOKENS",
    "tutor_context_complex_target_tokens": "TUTOR_CONTEXT_COMPLEX_TARGET_TOKENS",
    "tutor_context_extended_target_tokens": "TUTOR_CONTEXT_EXTENDED_TARGET_TOKENS",
    "tutor_context_warning_ratio": "TUTOR_CONTEXT_WARNING_RATIO",
    "tutor_context_critical_ratio": "TUTOR_CONTEXT_CRITICAL_RATIO",
    "tutor_context_max_expansions": "TUTOR_CONTEXT_MAX_EXPANSIONS",
    "tutor_context_fixed_mode": "TUTOR_CONTEXT_FIXED_MODE",
    "tutor_deepseek_repair_thinking_disabled": "TUTOR_DEEPSEEK_REPAIR_THINKING_DISABLED",
    "tutor_deepseek_responses_json_schema_enabled": "TUTOR_DEEPSEEK_RESPONSES_JSON_SCHEMA_ENABLED",
}
EFFECTIVE_FIELDS = (
    "tutor_context_window_capacity_tokens", "tutor_context_output_reserve_tokens",
    "tutor_decision_max_output_tokens", "deepseek_v4_flash_input_hard_limit_tokens",
    "tutor_context_max_dynamic_target_capacity_tokens",
)


def runtime_profile(settings: Settings) -> dict[str, object]:
    """The only fields allowed into the export and operator audit."""
    return {"format": "rag_d_runtime_profile_v1", "provider_type": settings.llm_provider_type,
            "model": settings.llm_model, "fields": {key: getattr(settings, key) for key in RUNTIME_FIELDS},
            "effective": {key: getattr(settings, key) for key in EFFECTIVE_FIELDS}}


def install_runtime_profile(path: str, *, profile: str = "formal",
                            output_tokens: int | None = None, input_tokens: int | None = None,
                            dynamic_target_tokens: int | None = None) -> Settings:
    """Root-private, strict host snapshot; only explicit boundary-test reduces it."""
    data, _ = _root_json(_absolute(path))
    if (set(data) != {"format", "provider_type", "model", "fields", "effective"}
            or data["format"] != "rag_d_runtime_profile_v1" or type(data["fields"]) is not dict
            or set(data["fields"]) != set(RUNTIME_FIELDS) or type(data["effective"]) is not dict
            or set(data["effective"]) != set(EFFECTIVE_FIELDS)
            or any(type(value) is not int for value in data["effective"].values())):
        raise Denied("RUNTIME_PROFILE_DENIED")
    fields = data["fields"]
    for key, value in fields.items():
        expected = (str if key == "tutor_context_fixed_mode" else
                    bool if key in {"tutor_deepseek_repair_thinking_disabled", "tutor_deepseek_responses_json_schema_enabled"} else
                    float if key.endswith("_ratio") else int)
        if type(value) is not expected and not (key == "tutor_context_fixed_mode" and value is None):
            raise Denied("RUNTIME_PROFILE_DENIED")
    if profile not in {"formal", "boundary-test"}:
        raise Denied("RUNTIME_PROFILE_DENIED")
    try:
        baseline = Settings(**fields)
    except (ValueError, TypeError) as exc:
        raise Denied("RUNTIME_PROFILE_DENIED") from exc
    if (runtime_profile(baseline)["effective"] != data["effective"]
            or baseline.llm_provider_type != data["provider_type"] or baseline.llm_model != data["model"]):
        raise Denied("RUNTIME_PROFILE_MISMATCH")
    if profile == "formal":
        if any(value is not None for value in (output_tokens, input_tokens, dynamic_target_tokens)):
            raise Denied("BOUNDARY_PROFILE_REQUIRED")
    else:
        if (type(output_tokens) is not int or type(input_tokens) is not int or
                not 1200 <= output_tokens < baseline.tutor_decision_max_output_tokens or
                not 4096 <= input_tokens < baseline.deepseek_v4_flash_input_hard_limit_tokens or
                (dynamic_target_tokens is not None and
                 (type(dynamic_target_tokens) is not int or not 1 <= dynamic_target_tokens <= input_tokens
                  - fields["tutor_context_protocol_reserve_tokens"]
                  - fields["tutor_context_safety_margin_tokens"]))):
            raise Denied("MODEL_BOUND_DENIED")
        fields = {**fields,
                  "tutor_deepseek_v4_flash_context_window_tokens": input_tokens + output_tokens,
                  "tutor_deepseek_v4_flash_input_limit_tokens": input_tokens,
                  "tutor_deepseek_v4_flash_max_output_tokens": output_tokens,
                  "tutor_deepseek_v4_flash_decision_max_output_tokens": output_tokens,
                  "tutor_deepseek_v4_flash_max_dynamic_target_tokens": min(
                      fields["tutor_deepseek_v4_flash_max_dynamic_target_tokens"],
                      input_tokens - fields["tutor_context_protocol_reserve_tokens"]
                      - fields["tutor_context_safety_margin_tokens"],
                      dynamic_target_tokens if dynamic_target_tokens is not None else input_tokens),
                  "tutor_context_compact_target_tokens": min(fields["tutor_context_compact_target_tokens"], input_tokens),
                  "tutor_context_normal_target_tokens": min(fields["tutor_context_normal_target_tokens"], input_tokens),
                  "tutor_context_complex_target_tokens": min(fields["tutor_context_complex_target_tokens"], input_tokens),
                  "tutor_context_extended_target_tokens": min(fields["tutor_context_extended_target_tokens"], input_tokens)}
    if any(env in os.environ for env in RUNTIME_FIELDS.values()):
        raise Denied("RUNTIME_ENV_ALREADY_SET")
    try:
        settings = Settings(**fields)
    except (ValueError, TypeError) as exc:
        raise Denied("RUNTIME_PROFILE_DENIED") from exc
    for key, env in RUNTIME_FIELDS.items():
        value = fields[key]
        if value is not None:
            os.environ[env] = str(value).lower() if type(value) is bool else str(value)
    get_settings.cache_clear()
    return settings


def guarded_name(name: str) -> str:
    if not name.startswith("aearn_rag260_c_d_") or len(name) <= len("aearn_rag260_c_d_") or DB.fullmatch(name) is None:
        raise Denied("DATABASE_DENIED")
    return name

def guard(execute: bool, name: str, dsn: str, settings: Settings, cap: int,
          output_tokens: int | None = None, input_tokens: int | None = None, wall_seconds: int = 240) -> None:
    """No I/O; MUST precede DB, source and model calls."""
    if not execute:
        raise Denied("DEFAULT_OFF")
    guarded_name(name)
    if (psycopg.conninfo.conninfo_to_dict(dsn).get("dbname") != name
            or psycopg.conninfo.conninfo_to_dict(settings.database_url).get("dbname") != name):
        raise Denied("DATABASE_DENIED")
    if not settings.rag_evidence_consumer_enabled or settings.llm_configuration_status != "configured":
        raise Denied("GATE_CLOSED")
    output_tokens = settings.tutor_decision_max_output_tokens if output_tokens is None else output_tokens
    input_tokens = (settings.tutor_context_window_capacity_tokens - settings.tutor_context_output_reserve_tokens
                    if input_tokens is None else input_tokens)
    if (type(cap) is not int or not 1 <= cap <= 8 or not 30 <= wall_seconds <= 300
            or output_tokens != settings.tutor_decision_max_output_tokens
            or input_tokens != settings.tutor_context_window_capacity_tokens - settings.tutor_context_output_reserve_tokens
            or input_tokens != settings.deepseek_v4_flash_input_hard_limit_tokens):
        raise Denied("MODEL_BOUND_DENIED")


def db_guard(dsn: str, settings: Settings, name: str) -> None:
    for url in (dsn, settings.database_url):
        with psycopg.connect(url, connect_timeout=3) as conn:
            if conn.execute("SELECT current_database()").fetchone()[0] != name:
                raise Denied("DATABASE_DENIED")


class SqlRequirements:
    """Exact pilot node keys under the validated operator-locked C version."""

    def __init__(self, subject_id: str, subject_version: str) -> None:
        self.subject_id, self.subject_version = subject_id, subject_version

    def resolve(self, draft: DraftScope, profile: Mapping[str, object],
                nodes: Mapping[str, Mapping[str, object]]) -> tuple[NodeMaterialRequirement, ...]:
        if profile.get("language_id") != "sql" or "sql.queries" not in nodes or set(nodes) - {"sql.queries", "sql.schema"}:
            raise Denied("PARENT_NODE_SCOPE_DENIED")
        result = []
        for key, node in nodes.items():
            for purpose in ("main_teaching", "supplementary_explanation"):
                facets = ("queries",) if key == "sql.queries" else ("schema",)
                demand = LearningMaterialDemand(
                    scope=SubjectScope(subject_id=self.subject_id, subject_version=self.subject_version, facets=facets),
                    demand_hash=digest((draft.draft_id, key, purpose, facets)),
                    plan_ref=f"draft.{draft.draft_id}", node_ref=f"node.{key}",
                    draft_revision=draft.draft_version, purpose=purpose,
                    reading_level="beginner", language="en",
                )
                result.append(NodeMaterialRequirement(
                    node_id=key, goal_hash=goal_hash_for_node(node),
                    prerequisites=tuple(node["prerequisite_keys"]), demand=demand,
                ))
        return tuple(result)


class CurrentConsumptionActor:
    """Operator-owned service actor rechecks the persisted C policy/root each use.

    This actor may only consume; it cannot authorize fetch, review or admission.
    The complete demand comes from the immutable plan, not from the model.
    """
    def __init__(self, conn: Any, policy: dict[str, Any]) -> None:
        self.conn, self.policy = conn, policy
        self.requirement: NodeMaterialRequirement | None = None

    def request_for(self, requirement: NodeMaterialRequirement) -> AccessRequest:
        self.requirement = requirement
        p = self.policy
        row = self.conn.execute(
            "SELECT r.*,p.enabled AS source_enabled,p.revoked_at AS source_revoked,"
            "p.allowed_usages AS source_usages,p.retention_until AS source_retention,p.expires_at AS source_expiry, "
            "p.subject_id AS source_subject,p.subject_version AS source_version,p.facets AS source_facets "
            "FROM rag_budget_authority_roots r JOIN rag_registered_source_policies p ON p.root_id=r.root_id "
            "WHERE p.policy_id=%s AND p.generation=%s AND p.root_id=%s FOR SHARE OF r,p",
            (p["policy_id"], p["generation"], p["root_id"]),
        ).fetchone()
        now = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        if (row is None or not row["enabled"] or not row["source_enabled"] or row["source_revoked"] is not None
                or row["policy_id"] != p["policy_id"] or row["policy_generation"] != p["generation"]
                or row["source_subject"] != requirement.demand.scope.subject_id
                or row["source_version"] != requirement.demand.scope.subject_version
                or requirement.demand.scope.facets[0] not in {"queries", "schema"}
                or tuple(row["source_facets"]) != ("queries",)
                or not row["period_start"] <= now < row["period_end"]
                or now >= min(row["delegation_expires_at"], row["source_retention"], row["source_expiry"])):
            raise Denied("CURRENT_ROOT_DENIED")
        return AccessRequest(
            actor_id="service.rag-d-live", action="consume", demand_hash=requirement.demand.demand_hash,
            scope=requirement.demand.scope, purpose=requirement.demand.purpose,
            policy_id=p["policy_id"], policy_generation=p["generation"],
            budget=RagBudgetDelegation(root_id=p["root_id"], delegation_id=row["delegation_id"],
                                       generation=row["delegation_generation"], expires_at=row["delegation_expires_at"]),
        )

    def resolve(self, request: AccessRequest) -> AuthoritySnapshot | None:
        # request_for is called immediately before each check. Do not grant an
        # arbitrary demand merely because a client supplied a matching hash.
        if self.requirement is None or request != self.request_for(self.requirement):
            return None
        demand = self.requirement.demand
        return AuthoritySnapshot(
            demand=demand, demand_hash=demand.demand_hash, scope=demand.scope,
            purpose=demand.purpose, actor_id="service.rag-d-live", allowed_actions=("consume",),
            policy_id=request.policy_id, policy_generation=request.policy_generation,
            budget=request.budget, budget_active=True, authorized=True,
        )


class CountedClient:
    """Bounded acceptance calls; preserve gateway/repair thinking behavior."""
    def __init__(self, client: Any, limit: int) -> None:
        self.client, self.limit, self.count = client, limit, 0
        self.usage: list[dict[str, int] | None] = []
        self.response_models: list[str | None] = []

    @property
    def model(self) -> str:
        return self.client.model

    def complete_json(self, *args: Any, **kwargs: Any) -> Any:
        if self.count >= self.limit:
            raise Denied("MODEL_HTTP_CAP")
        self.count += 1  # count before I/O, failure is unknown usage
        self.usage.append(None)
        self.response_models.append(None)
        try:
            response = self.client.complete_json(*args, **kwargs)
        except Exception as exc:
            self.response_models[-1] = getattr(exc, "model", None) or self.model
            if getattr(exc, "usage", None) is not None:
                self.usage[-1] = {k: v for k, v in asdict(exc.usage).items() if type(v) is int} or None
            raise
        self.response_models[-1] = getattr(response, "model", None) or self.model
        if response.usage is not None:
            data = asdict(response.usage)
            self.usage[-1] = {k: v for k, v in data.items() if type(v) is int} or None
        return response


class SharedHttpBudget:
    """Hard cap at the common urllib transport, including semantic review/retries."""
    def __init__(self, settings: Settings, limit: int) -> None:
        self.limit, self.count = limit, 0
        base = urlsplit(settings.llm_base_url or "")
        if base.scheme != "https" or not base.netloc or base.username or base.password:
            raise Denied("PROVIDER_ENDPOINT_DENIED")
        self.origin = (base.scheme, base.netloc)
        self.path = base.path.rstrip("/")

    @contextmanager
    def enforce(self):
        previous = urllib.request.urlopen
        previous_redirect = urllib.request.HTTPRedirectHandler.redirect_request
        def no_redirect(*_args, **_kwargs):
            raise Denied("PROVIDER_REDIRECT_DENIED")
        def bounded(request, *args, **kwargs):
            if not isinstance(request, urllib.request.Request):
                raise Denied("UNEXPECTED_NETWORK")
            target = urlsplit(request.full_url)
            if (request.get_method() != "POST" or (target.scheme, target.netloc) != self.origin
                    or not target.path.startswith(self.path + "/")):
                raise Denied("UNEXPECTED_NETWORK")
            if self.count >= self.limit:
                raise Denied("MODEL_HTTP_CAP")
            self.count += 1  # reserve before actual socket, even if response is unknown
            return previous(request, *args, **kwargs)
        urllib.request.urlopen = bounded
        urllib.request.HTTPRedirectHandler.redirect_request = no_redirect
        try:
            yield self
        finally:
            urllib.request.urlopen = previous
            urllib.request.HTTPRedirectHandler.redirect_request = previous_redirect

@contextmanager
def wall_deadline(seconds: int):
    old = signal.getsignal(signal.SIGALRM)
    def expired(_signum, _frame):
        raise WallDeadlineExceeded("MODEL_WALL_DEADLINE")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)

def run(args: argparse.Namespace) -> dict[str, object]:
    if not args.execute:
        raise Denied("DEFAULT_OFF")
    if args.parent_kind == "real_provider" and not args.parent_provenance:
        raise Denied("PARENT_PROVENANCE_REQUIRED")
    if args.parent_kind == "test_owned_fixture" and args.parent_provenance:
        raise Denied("PARENT_PROVENANCE_MODE_MISMATCH")
    if os.name != "posix" or os.geteuid() != 0:
        raise Denied("ROOT_OPERATOR_REQUIRED")
    source_provider = getattr(args, "source_provider", "direct")
    if source_provider == "tavily":
        from tavily_acquire import load_tavily_config
        config, dsn, scope = load_tavily_config(_absolute(args.control_config))
    elif source_provider == "direct":
        config, _ = _root_json(_absolute(args.control_config))
        if set(config) != CONFIG or config["approved"] is not True:
            raise Denied("CONTROL_CONFIG_DENIED")
        dsn = _root_file(_absolute(config["dsn_secret_path"]), limit=4096)[0].decode().strip()
        scope = Scope.from_wire(config["scope"])
    else:
        raise Denied("SOURCE_PROVIDER_DENIED")
    install_private_database(dsn)
    install_private_provider(args.provider_config)
    install_runtime_profile(args.runtime_profile, profile=args.profile,
                            output_tokens=args.draft_output_tokens, input_tokens=args.input_limit_tokens,
                            dynamic_target_tokens=args.dynamic_target_tokens)
    settings = Settings(tutor_thread_turn_v2_enabled=True, tutor_codex_plan_drafting_enabled=False)
    guard(args.execute, config["database_name"], dsn, settings, args.max_http,
          wall_seconds=args.wall_seconds)
    if (args.parent_kind == "real_provider" and
            (type(args.prior_http_attempts) is not int or args.prior_http_attempts < 0 or
             type(args.cumulative_http_cap) is not int or
             args.prior_http_attempts + args.max_http > args.cumulative_http_cap)):
        raise Denied("CUMULATIVE_MODEL_BOUND_DENIED")
    db_guard(dsn, settings, config["database_name"])
    scope_data = config["scope"]
    subject = get_grounding_subject("route.sql")
    if (scope.subject_id != "route.sql" or scope.facets != ("queries",)
            or scope.url != "https://www.sqlite.org/lang_select.html"
            or scope.host != "www.sqlite.org" or scope.path != "/lang_select.html"
            or subject is None or "sql" not in subject.language_ids
            or subject.version_policy != "operator_locked"
            or not {"queries", "schema"} <= set(subject.required_facets)):
        raise Denied("SOURCE_SCOPE_DENIED")
    requirements = SqlRequirements(scope.subject_id, scope.subject_version)
    capture_id, corpus_id = UUID(args.capture_id), UUID(args.corpus_id)
    public = _root_file(_absolute(args.service_public_key), limit=64)[0]
    if hashlib.sha256(public).hexdigest() != SERVICE_PUBLIC_SHA256:
        raise Denied("SERVICE_PIN_DENIED")
    if source_provider == "tavily":
        from tavily_admission import read_tavily_receipt
        signed = read_tavily_receipt(_absolute(args.receipt), run_id=args.admission_run_id,
                                    corpus_id=corpus_id, capture_id=capture_id)
    else:
        signed = _read_provisional(_absolute(args.receipt), run_id=args.admission_run_id,
                                   corpus_id=corpus_id, capture_id=capture_id)
    if signed.service_key_id != KEY_ID or signed.payload.capture_id != capture_id:
        raise Denied("RECEIPT_MISMATCH")
    if source_provider == "direct":
        pin = config["b_attestor"]
        if set(pin) != PIN or hashlib.sha256(bytes.fromhex(pin["public_key_hex"])).hexdigest() != pin["public_key_sha256"]:
            raise Denied("TRANSPORT_PIN_DENIED")
        transport = SignedDispatchProofVerifier(
            public_key=bytes.fromhex(pin["public_key_hex"]), deployment_id=pin["deployment_id"],
            policy_sha256=pin["policy_sha256"], namespace_inode=pin["namespace_inode"],
            allowed_ips=frozenset(pin["allowed_ips"]),
        )

    def evidence_factory(conn: Any) -> EvidenceSelection:
        if source_provider == "tavily":
            from app.services.grounding.autonomous.tavily_capture_repository import TavilyCaptureRepository
            from app.services.grounding.autonomous.tavily_sqlite_review import TavilySQLiteReviewVerifier
            provider_captures = TavilyCaptureRepository(conn)
            reviews = SourceReviewRepository(conn, registered_provider_captures=provider_captures,
                verifier=TavilySQLiteReviewVerifier(review=signed, service_key_id=KEY_ID,
                    service_public_key=public, provenance=provider_captures, enabled=True))
        else:
            provenance = PostgresCurrentCaptureProvenanceResolver(
                conn, verifier=transport, worker_image_sha256=config["worker_image_sha256"])
            reviews = SourceReviewRepository(conn, verifier=SQLiteSelectAutomatedReviewVerifier(
                review=signed, service_key_id=KEY_ID, service_public_key=public,
                provenance=provenance, enabled=True))
        governance = CorpusGovernance(conn, authority=PostgresCorpusAuthority(),
                                      source_reviews=reviews, isolated_operator_enabled=True)
        actor = CurrentConsumptionActor(conn, scope_data)
        return EvidenceSelection(conn, governance=governance, request_for=actor.request_for,
                                 selections=PostgresMaterialBindingRepository(conn),
                                 gates=AutonomousGates(evidence_consumer=True),
                                 authority_resolver=actor, enabled=True)

    # No provider construction until the exact committed C artifact is verified.
    with connect() as conn:
        with conn.transaction():
            if conn.execute("SELECT current_database() AS name").fetchone()["name"] != config["database_name"]:
                raise Denied("DATABASE_DENIED")
            evidence = evidence_factory(conn)
            active = evidence.governance.repo.active("route.sql")
            if active is None or active.corpus_id != corpus_id:
                raise Denied("C_ACTIVE_MISMATCH")
            version = evidence.governance.repo.version(corpus_id)
            if (version.subject_id != scope.subject_id or version.subject_version != scope.subject_version
                    or version.coverage_summary != {"required": 2, "covered": 1, "gap": 1, "partial": True}):
                raise Denied("C_COVERAGE_MISMATCH")
            evidence.governance._verified(corpus_id, summary_hash=version.summary_hash,
                                          purpose="supplementary_explanation")
            links = evidence.governance._rows(corpus_id)[1]
            if len(links) != 1 or links[0]["registered_capture_id"] != capture_id:
                raise Denied("C_CAPTURE_MISMATCH")
            parent = conn.execute("SELECT * FROM tutor_learning_plan_drafts WHERE id=%s AND user_id=%s AND session_id=%s",
                                  (args.parent_draft_id, args.user_id, args.session_id)).fetchone()
            session = conn.execute("SELECT * FROM tutor_learning_plan_sessions WHERE id=%s AND user_id=%s",
                                   (args.session_id, args.user_id)).fetchone()
            if (parent is None or session is None or str(session["current_draft_id"]) != args.parent_draft_id
                    or str(parent["source_run_id"]) == args.target_run_id):
                raise Denied("PARENT_SESSION_DENIED")
            parent_proof: dict[str, object] = {"parent_kind": "test_owned_fixture", "parent_http_attempts": 0}
            if args.parent_kind == "real_provider":
                from parent_provenance import verify_parent_provenance, ParentProvenanceDenied
                audit, _ = _root_json(_absolute(args.parent_provenance))
                budget_proof = parent_successor_http_window(
                    audit,
                    successor_prior_http_attempts=args.prior_http_attempts,
                    successor_phase_http_cap=args.max_http,
                    successor_cumulative_http_cap=args.cumulative_http_cap,
                )
                try:
                    verified_parent = verify_parent_provenance(
                        conn, audit=audit, parent=parent, database_name=config["database_name"],
                        conversation_id=args.conversation_id, subject_id=requirements.subject_id,
                        subject_version=requirements.subject_version,
                        expected_runtime_profile=runtime_profile(settings), profile=args.profile,
                        prior_http_attempts=budget_proof["parent_prior_http_attempts"],
                        cumulative_http_cap=budget_proof["parent_cumulative_http_cap"])
                except ParentProvenanceDenied as exc:
                    raise Denied(str(exc)) from None
                parent_proof = {**verified_parent, **budget_proof}
            scope = DraftScope(user_id=args.user_id, conversation_id=args.conversation_id,
                               session_id=args.session_id, draft_id=args.parent_draft_id,
                               draft_version=parent["draft_version"], content_hash=parent["content_hash"],
                               source_run_id=str(parent["source_run_id"]),
                               source_input_revision=parent["source_input_revision"])
            nodes = {n["knowledge_key"]: n for m in parent["plan_json"]["modules"] for n in m["nodes"]}
            requirements.resolve(scope, parent["profile_json"], nodes)
            session_version = int(session["version"])
        counted = CountedClient(OpenAICompatibleClient(
            settings, diagnostic_store=ProviderDiagnosticStore.from_settings(settings),
            max_http_attempts=1,
        ), args.max_http)
        dispatcher = build_internal_material_planning_dispatcher(
            settings, server_opt_in=True, requirements=requirements,
            evidence_factory=evidence_factory,
            semantic_reviewer=PrimaryMaterialSemanticReviewer(settings, client=counted),
            provider_factory=lambda _: PrimaryTutorProviderGateway(
                settings=settings, client=counted, max_output_tokens=settings.tutor_decision_max_output_tokens),
        )
        factory = dispatcher._material_consumer_factory
        if factory is None:
            raise Denied("COMPOSITION_DENIED")
        # Persistent parent feedback and exact target CAS precede model I/O.
        with conn.transaction():
            factory(conn).assign_parent_feedback(
                parent=scope, target_run_id=args.target_run_id,
                target_input_revision=args.target_input_revision,
                expected_session_version=session_version)
    shared = SharedHttpBudget(settings, args.max_http)
    try:
        with shared.enforce(), wall_deadline(args.wall_seconds):
            outcome = dispatcher.dispatch(user_id=args.user_id, run_id=args.target_run_id)
    finally:
        print(json.dumps({"model_http_attempts": shared.count, "planning_and_review_client_calls": counted.count, "model": counted.model,
                          "runtime_profile": runtime_profile(settings), "profile": args.profile,
                          "prior_http_attempts": args.prior_http_attempts, "cumulative_http_cap": args.cumulative_http_cap,
                          "parent_phase_http_cap": parent_proof.get("parent_phase_http_cap"),
                          "parent_cumulative_http_cap": parent_proof.get("parent_cumulative_http_cap"),
                          "successor_phase_http_cap": args.max_http,
                          "successor_cumulative_http_cap": args.cumulative_http_cap,
                          "wall_seconds": args.wall_seconds,
                          "usage_per_attempt": counted.usage, "unknown_usage_count": shared.count - sum(v is not None for v in counted.usage)},
                         sort_keys=True))
    from app.agents.harness.contracts import TutorTerminalOutcome
    if outcome.terminal_outcome is not TutorTerminalOutcome.COMPLETED or outcome.capability_call_count < 1:
        raise Denied("TARGET_RUN_INCOMPLETE")
    with connect() as conn:
        successor = conn.execute(
            "SELECT * FROM tutor_learning_plan_drafts WHERE user_id=%s AND source_run_id=%s AND source_input_revision=%s",
            (args.user_id, args.target_run_id, args.target_input_revision)).fetchone()
        if (successor is None or str(successor["predecessor_draft_id"]) != args.parent_draft_id
                or successor["content_hash"] == parent["content_hash"]):
            raise Denied("SUCCESSOR_NOT_PERSISTED")
        def goals(plan: dict[str, Any]) -> dict[str, str]:
            return {n["knowledge_key"]: goal_hash_for_node(n)
                    for m in plan["modules"] for n in m["nodes"]}
        if goals(successor["plan_json"]) != goals(parent["plan_json"]):
            raise Denied("CORE_GOALS_CHANGED")
        rows = conn.execute("SELECT node_id,purpose,binding_json FROM rag_plan_material_bindings WHERE draft_id=%s",
                            (successor["id"],)).fetchall()
        if not rows or any(r["node_id"] != "sql.queries" or r["purpose"] != "supplementary_explanation"
                           or not r["binding_json"]["evidence"]
                           or any(e["corpus_version_id"] != str(corpus_id) for e in r["binding_json"]["evidence"])
                           for r in rows):
            raise Denied("BINDING_SCOPE_DENIED")
        selections = conn.execute("SELECT snapshot_json FROM rag_material_selections WHERE draft_id=%s",
                                  (successor["id"],)).fetchall()
        if len(selections) != 1:
            raise Denied("SUCCESSOR_SELECTION_MISSING")
        entries = selections[0]["snapshot_json"]["entries"]
        if (not any(e["node_id"] == "sql.queries" and e["purpose"] == "supplementary_explanation"
                    and e["status"] == "ready" for e in entries)
                or any(e["status"] == "ready" and e["purpose"] != "supplementary_explanation" for e in entries)):
            raise Denied("SOURCE_PURPOSE_DENIED")
        # Recheck the persisted exact binding against current C authority, not a
        # cached selection or the provisional service receipt alone.
        from app.services.grounding.material_contracts_v2 import EvidenceBindingV2
        with conn.transaction():
            evidence = evidence_factory(conn)
            for row in rows:
                evidence.authorize_binding(conn, EvidenceBindingV2.model_validate_json(json.dumps(row["binding_json"])))
        semantic = conn.execute(
            "SELECT review.id,review.reviewer_model FROM rag_material_semantic_reviews review "
            "JOIN tutor_provider_attempt_receipts provider ON provider.run_id=review.run_id "
            "AND provider.input_revision=review.input_revision AND provider.decision_iteration=review.decision_iteration "
            "AND provider.attempt_index=review.attempt_index AND provider.outcome='accepted' "
            "WHERE review.user_id=%s AND review.conversation_id=%s AND review.run_id=%s "
            "AND review.input_revision=%s AND review.parent_content_hash=%s "
            "AND review.review_status='settled' AND review.verdict='consistent' AND review.reason_code='supported'",
            (args.user_id, args.conversation_id, args.target_run_id, args.target_input_revision, parent["content_hash"]),
        ).fetchall()
        if not semantic or any(r["reviewer_model"] not in counted.response_models for r in semantic):
            raise Denied("REAL_SEMANTIC_RECEIPT_MISSING")
        return {"status": "passed_internal_only", "source_provider": source_provider, **parent_proof,
                **({"representation": "provider_extracted_markdown", "origin_transport_attested": False}
                   if source_provider == "tavily" else {}),
                "acceptance_tier": ("real_sources_real_parent_real_successor" if args.parent_kind == "real_provider"
                                    else "real_sources_fixture_parent_real_successor"),
                "successor_http_attempts": shared.count,
                "combined_http_attempts": int(parent_proof["parent_http_attempts"]) + shared.count,
                "actual_cumulative_http_attempts": (
                    args.prior_http_attempts + shared.count
                    if args.parent_kind == "real_provider" else None
                ),
                "runtime_profile": runtime_profile(settings), "profile": args.profile,
                "prior_http_attempts": args.prior_http_attempts, "cumulative_http_cap": args.cumulative_http_cap,
                "parent_draft_id": args.parent_draft_id, "successor_draft_id": str(successor["id"]),
                "successor_version": successor["draft_version"], "bindings": len(rows),
                "selection_statuses": [{"node_id": e["node_id"], "purpose": e["purpose"], "status": e["status"],
                                        "gaps": e["gaps"]} for e in entries],
                "goal_hashes_preserved": True, "capability_calls": outcome.capability_call_count,
                "semantic_review_ids": [str(r["id"]) for r in semantic],
                "source_coverage": version.coverage_summary, "global_source_gaps": ["schema"],
                "public_release": False}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--source-provider", choices=("tavily", "direct"), default="tavily",
                   help="source acquisition authority; no automatic fallback")
    p.add_argument("--provider-config", required=True, help="root-owned private JSON path, not secret values")
    p.add_argument("--runtime-profile", required=True, help="root-owned nonsecret Settings snapshot")
    p.add_argument("--profile", choices=("formal", "boundary-test"), default="formal")
    for name in ("control-config", "receipt", "service-public-key", "capture-id", "corpus-id",
                 "admission-run-id", "user-id", "session-id", "conversation-id", "parent-draft-id", "target-run-id"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--target-input-revision", type=int, required=True)
    p.add_argument("--parent-kind", choices=("real_provider", "test_owned_fixture"), required=True)
    p.add_argument("--parent-provenance", help="root-owned checked real-parent audit; required for real_provider")
    p.add_argument("--max-http", type=int, default=8)
    p.add_argument("--draft-output-tokens", type=int, help="boundary-test only")
    p.add_argument("--input-limit-tokens", type=int, help="boundary-test only")
    p.add_argument("--dynamic-target-tokens", type=int, help="boundary-test only; optional")
    p.add_argument("--prior-http-attempts", type=int, help="operator ledger count before this invocation")
    p.add_argument("--cumulative-http-cap", type=int, help="operator-approved cumulative bound")
    p.add_argument("--wall-seconds", type=int, default=240)
    return p


def main() -> int:
    try:
        if sys.argv[1:] == ["--export-runtime-profile"]:
            # Run from the host API venv with its effective .env; prints only allowlisted values.
            host = Settings()
            if host.llm_configuration_status != "configured":
                raise Denied("PROVIDER_CONFIG_DENIED")
            print(json.dumps(runtime_profile(host), sort_keys=True))
            return 0
        print(json.dumps(run(parser().parse_args()), sort_keys=True))
        return 0
    except (Exception, WallDeadlineExceeded) as exc:
        print(json.dumps({"status": "blocked", "code": str(exc) if type(exc) in {Denied, WallDeadlineExceeded} else "LIVE_E2E_INCOMPLETE",
                          "exception_type": type(exc).__name__,
                          "frames": [{"file": Path(frame.filename).name, "line": frame.lineno,
                                      "function": frame.name} for frame in traceback.extract_tb(exc.__traceback__)]}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
