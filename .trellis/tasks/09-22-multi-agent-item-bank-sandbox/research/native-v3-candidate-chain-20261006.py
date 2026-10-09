"""Main-only fresh V3 item operator. Default --plan is strictly offline/inert.

One slot per invocation. All five slots share one immutable campaign; four
relation calls are held for the distinct native relation owner, never run here.
Do not call --execute from a subagent. No source GET/dispatch/signing or schema IO.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any
from uuid import UUID, uuid4

from native_v3_chain_support_20261006 import (
    AUTHOR_INPUT, AUTHOR_OUTPUT, REVIEW_INPUT, REVIEW_OUTPUT,
    ADMISSION_POLICIES, SLOTS, TARGETS, OperatorPending, build_plan, campaign_cases, campaign_path, digest, read,
    remaining_time_plan, required_remaining, resume_decision, save, save_exact, selected_admission_policy, time_bounds,
)

ROOT = Path(__file__).resolve().parents[4]
RUNTIME = ROOT / ".runtime/e-native-type-20261006"
DATABASE = "aearn_b1d_sandbox_20261001"
IMAGE = "aearn-item-supply-sandbox@sha256:ea418cfbd855d76f43291cc96e4e1813709599da24781c579136f48aa60e8d90"


def configure_offline_imports() -> None:
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    api = str(ROOT / "aearn/services/api")
    if api not in sys.path:
        sys.path.insert(0, api)


def source_helper() -> Any:
    path = Path(__file__).with_name("native-type-live-support-20261006.py")
    spec = importlib.util.spec_from_file_location("native_v3_current_source_composition", path)
    if spec is None or spec.loader is None:
        raise OperatorPending("CURRENT_SOURCE_COMPOSITION_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def settings_for_execute() -> Any:
    # This function is reachable only AFTER --execute and a fresh source preflight.
    from dotenv import dotenv_values
    from app.core.config import Settings

    values = dotenv_values(ROOT / "aearn/.env")
    settings = Settings(_env_file=None, llm_type="deepseek", deepseek_api_key=values.get("DEEPSEEK_API_KEY"),
        deepseek_base_url=values.get("DEEPSEEK_BASE_URL"), deepseek_model=values.get("DEEPSEEK_MODEL", "deepseek-flash"),
        llm_timeout_seconds=100, learning_item_supply_enabled=True, learning_item_generation_enabled=True,
        learning_item_network_enabled=True, learning_item_v2_admission_enabled=True,
        learning_item_supply_scheduler_enabled=False, learning_item_bank_agent_review_enabled=False,
        tutor_learning_artifacts_enabled=False, tutor_artifact_teaching_mode_enabled=False,
        tutor_proactive_scheduler_enabled=False, tutor_proactive_cutover_eligible=False)
    del values
    return settings


def event(folder: Path, stage: str, **facts: Any) -> None:
    with (folder / "events.jsonl").open("a", encoding="utf8") as stream:
        stream.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), stage=stage,
            monetary_cost=None, **facts), ensure_ascii=False, default=str, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def dbnow(conn: Any) -> datetime:
    return conn.execute("SELECT clock_timestamp() AS n").fetchone()["n"].astimezone(timezone.utc)


def require_idle(conn: Any) -> None:
    from psycopg.pq import TransactionStatus
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise OperatorPending("EXTERNAL_IO_REQUIRES_IDLE")


def canonical_obligation(spec: Any) -> Any:
    from app.services.learning.item_supply.policies import CoverageObligationV1, derive_runtime_contract_hash
    coverage = spec.coverage_blueprint
    return CoverageObligationV1(blueprint_hash=coverage.blueprint_hash, scope_hash=coverage.scope.scope_hash,
        objective_hash=coverage.objective_hash, purpose=coverage.scope.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(coverage.scope), visibility="public",
        policy_version=coverage.policy_version)


def factory_spec(slot: dict[str, Any], plan: dict[str, Any], materials: Any, item_key: str, locks: Any) -> Any:
    from app.services.learning.item_bank.contracts import (
        LearningItemDifficultyProfileV1, LearningItemPublicationPolicyV1, canonical_hash,
    )
    from app.services.learning.item_supply.finite_candidate_factory import (
        FLEXIBLE_FACTORY_VERSION, FiniteSlotAllocationV2, build_finite_candidate_spec,
    )
    from app.services.learning.item_supply.finite_targets.python_kc import PYTHON_KC_SCORER_VERSION
    from app.services.learning.item_supply.sandbox.python_state_scorer import PYTHON_STATE_SCORER_VERSION
    from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
    from app.services.learning.practice.policies import GATE_PASS_POLICY_VERSION

    # Canonical coverage/accounting stays V2 even for diagnostic admission.
    # Changing this policy would fork roots and bypass cumulative usage.
    policy = AutonomousEvidencePolicyV2()
    target = plan["target"]
    allocation = FiniteSlotAllocationV2.model_validate_json(json.dumps(slot["allocation"]))
    if allocation.definition_hash != slot["allocation_hash"]:
        raise OperatorPending("FACTORY_ALLOCATION_CHANGED")
    scorer = {TARGETS[0]: PYTHON_KC_SCORER_VERSION, TARGETS[1]: PYTHON_STATE_SCORER_VERSION,
        TARGETS[2]: GATE_PASS_POLICY_VERSION}[target]
    runtime = "python-stdout-v1" if target == TARGETS[1] else "sqlite-query-v1"
    spec = build_finite_candidate_spec(target_id=target, variant_id=allocation.variant_id,
        seed=slot["seed"], item_key=item_key, version="v1", materials=materials,
        runtime_profile_hash=None if target == TARGETS[0] else locks[runtime].fingerprint,
        scorer_version=scorer,
        # EXACT previous canonical assistance contract, also for KC/remediation.
        assistance_policy_hash=canonical_hash({"visibility": "public", "purpose": "exercise",
            "no_learner_attempt": True, "evidence_policy": policy.policy_hash}),
        policy_version=policy.policy_version,
        difficulty_profile=LearningItemDifficultyProfileV1.model_validate_json(json.dumps(dict(base="D1", reasoning_depth=1,
            concept_count=2, context_novelty=1, transfer_distance=1, response_complexity=1, scaffolding=5))),
        publication_policy=LearningItemPublicationPolicyV1.model_validate_json(json.dumps(dict(risk_tier="low",
            required_review_roles=["curriculum", "difficulty", "technical", "ambiguity", "security", "adversarial"],
            agent_review_required=True, pilot_required=True, human_approval_required=False))),
        public_spec_version=FLEXIBLE_FACTORY_VERSION, allocation=allocation)
    # Verify V3 did not manufacture a coverage/root change from the legacy factory.
    legacy_variant = ":guided-remediation" if allocation.slot == "remediation" else ":practice-1"
    legacy = build_finite_candidate_spec(target_id=target, variant_id=target + legacy_variant, seed=0,
        item_key="native.canonical.reference", version="v1", materials=materials,
        runtime_profile_hash=None if target == TARGETS[0] else locks[runtime].fingerprint,
        scorer_version=scorer, assistance_policy_hash=spec.coverage_blueprint.scope.assistance_policy_hash,
        policy_version=policy.policy_version, difficulty_profile=spec.blueprint.difficulty_profile,
        publication_policy=spec.blueprint.publication_policy)
    if spec.coverage_blueprint != legacy.coverage_blueprint:
        raise OperatorPending("V3_MUST_PRESERVE_LEGACY_CANONICAL_ROOT")
    return spec


def fresh_profile(conn: Any, provider: Any, spec: Any, materials: Any, *, previous: Any = None) -> Any:
    from app.services.learning.item_supply.parameter_profiles import ExecutionParameterProfileV1, ParameterValuesV1, ProfileKeyV1
    from app.services.learning.item_supply.provider_adapter import GENERATION_PROMPT_VERSION

    key = previous.profile_key if previous is not None else ProfileKeyV1(provider=provider.provider_key,
        model_version=provider.configured_model, agent_role="native.shared.v3.author." + spec.target_id,
        item_kind=spec.public_template.kind.value, risk_tier="low", difficulty="basic",
        input_size_bucket="bounded-131072", runtime=spec.blueprint.runtime_profile_id or "static-exact-v1",
        provider_version="openai-compatible-v1", prompt_version=GENERATION_PROMPT_VERSION,
        validator_version="finite-native-v1", output_size_bucket="bounded-65536", load_bucket="single",
        complexity_version=spec.target_id)
    if (key.provider, key.model_version) != (provider.provider_key, provider.configured_model):
        raise OperatorPending("CURRENT_PROVIDER_PROFILE_MISMATCH")
    latest = conn.execute("SELECT max(profile_version) AS v FROM tutor_item_supply_parameter_profiles WHERE profile_key_hash=%s",
        (key.key_hash,)).fetchone()["v"]
    now = dbnow(conn)
    bounds = time_bounds(spec.target_id)
    if previous is not None:
        if min(previous.current.stage_deadline_ms, previous.current.parent_deadline_ms) < bounds["parent_seconds"] * 1000:
            raise OperatorPending("ORIGINAL_PROFILE_TIME_BOUND_INSUFFICIENT_NO_RENEWAL")
        payload = previous.model_dump(mode="json")
        payload.update(version=int(latest or 0) + 1, measurement_window_started_at=now.isoformat(),
            change_reason="native_v3_same_root_491_continuation")
        return ExecutionParameterProfileV1.model_validate_json(json.dumps(payload))
    # Keep the existing 100s request bound; explicitly authorized generous NEW
    # stage/parent bounds cover item + future relation IO and control margin.
    values = ParameterValuesV1(connection_timeout_ms=20_000, first_token_timeout_ms=100_000,
        stream_idle_timeout_ms=100_000, request_timeout_ms=100_000, stage_deadline_ms=bounds["parent_seconds"] * 1000,
        parent_deadline_ms=bounds["parent_seconds"] * 1000, discussion_rounds=1, revision_rounds=1, investigation_rounds=1)
    return ExecutionParameterProfileV1(profile_key=key, version=int(latest or 0) + 1, state="frozen",
        initial=values, current=values, last_stable=values, floor=values, ceiling=values,
        measurement_window_started_at=now, change_reason="native_v3_bounded_fresh_item",
        trusted_initial_evidence=(materials[0].exact_claims[0].claim_receipt_id, spec.target_definition_hash))


def _json_rows(rows: Any) -> Any:
    return json.loads(json.dumps(rows, default=str))


def prepare_campaign(conn: Any, *, path: Path, plan: dict[str, Any], specs: list[Any], provider: Any, review_pending: set[str] | None = None) -> dict[str, Any]:
    """Reuse ALL active limits; never append overlapping periods to evade a cap."""
    from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
    from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository
    from app.services.learning.item_supply.storage import PostgresSharedSupplyStorage
    from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2

    receipt_path = path / "resource-window.json"
    expected = read(receipt_path) if receipt_path.exists() else None
    occupied = {s for s in SLOTS if (path / "slots" / s / "author-invoked.json").exists()}
    needs, root_needs = required_remaining(plan, occupied, review_pending=review_pending)
    wall_need, root_wall_need = remaining_time_plan(plan, occupied, review_pending=review_pending)
    budget = ItemSupplyBudgetRepository(conn)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('native-v3-canonical-period',0))")
        now = dbnow(conn)
        old_globals = conn.execute("SELECT to_jsonb(t) AS v FROM tutor_item_supply_runtime_global_limits t ORDER BY id").fetchall()
        old_roots = conn.execute("SELECT to_jsonb(t) AS v FROM tutor_item_supply_shared_budget_windows t ORDER BY id").fetchall()
        dimensions = (("system", "item-supply"), ("window", "item-supply"), ("pool", "base"), ("provider", provider.provider_key))
        active = conn.execute("SELECT * FROM tutor_item_supply_runtime_global_limits WHERE window_start<=%s AND window_end>%s "
            "AND ((dimension_kind='system' AND dimension_key='item-supply') OR (dimension_kind='window' AND dimension_key='item-supply') "
            "OR (dimension_kind='pool' AND dimension_key='base') OR (dimension_kind='provider' AND dimension_key=%s)) "
            "ORDER BY dimension_kind,dimension_key,resource_kind,id FOR UPDATE", (now, now, provider.provider_key)).fetchall()
        new_global_ids = []
        if expected is not None:
            if {str(r["id"]) for r in active} != set(expected["global_limit_ids"]):
                raise OperatorPending("ORIGINAL_CAMPAIGN_GLOBAL_PERIOD_NOT_CURRENT")
        elif active:
            if {(r["dimension_kind"], r["dimension_key"], r["resource_kind"]) for r in active} != {
                    (dim, key, kind) for dim, key in dimensions for kind in plan["global_caps"]}:
                raise OperatorPending("EXISTING_PARTIAL_GLOBAL_CONFIGURATION_NO_REPLACEMENT")
        else:
            end = now + timedelta(seconds=plan["period_seconds"])
            for dim, key in dimensions:
                for kind, cap in plan["global_caps"].items():
                    new_global_ids.append(str(budget.register_global_limit(dimension_kind=dim, dimension_key=key,
                        resource_kind=kind, window_start=now, window_end=end, cap_amount=max(1, cap))))
            active = conn.execute("SELECT * FROM tutor_item_supply_runtime_global_limits WHERE id=ANY(%s::uuid[]) "
                "ORDER BY dimension_kind,dimension_key,resource_kind,id FOR UPDATE", (new_global_ids,)).fetchall()
        global_used = {}
        for limit in active:
            used_amount = budget._global_used(UUID(str(limit["id"])), limit["resource_kind"])
            global_used[str(limit["id"])] = dict(resource_kind=limit["resource_kind"], used_amount=used_amount)
            if used_amount + needs[limit["resource_kind"]] > limit["cap_amount"]:
                raise OperatorPending("EXISTING_GLOBAL_REMAINING_CAP_INSUFFICIENT_NO_RESET")
        start = max(r["window_start"] for r in active)
        end = min(r["window_end"] for r in active)
        if (end - dbnow(conn)).total_seconds() < wall_need:
            raise OperatorPending("ORIGINAL_GLOBAL_WINDOW_TIME_INSUFFICIENT_NO_REPLACEMENT")
        storage, runtime = PostgresSharedSupplyStorage(conn), ItemSupplyRuntimeRepository(conn)
        storage.register_policy(AutonomousEvidencePolicyV2())
        roots: dict[str, Any] = {}
        root_used = {}
        new_root_window_ids: list[str] = []
        for spec in specs:
            purpose = spec.coverage_blueprint.scope.purpose.value
            if purpose in roots:
                if canonical_obligation(spec).canonical_key != roots[purpose]["canonical_key"]:
                    raise OperatorPending("SAME_PURPOSE_MUST_SHARE_CANONICAL_ROOT")
                continue
            blueprint = storage.register_blueprint(spec.coverage_blueprint)
            obligation = canonical_obligation(spec)
            root = runtime.ensure_shared_root(blueprint_id=blueprint, obligation=obligation,
                pool="base", provider_key=provider.provider_key)
            windows = conn.execute("SELECT * FROM tutor_item_supply_shared_budget_windows WHERE root_id=%s "
                "AND window_start<=%s AND window_end>%s ORDER BY id FOR UPDATE", (root, now, now)).fetchall()
            if not windows and expected is None:
                caps = plan["root_caps"][purpose]
                window = conn.execute("INSERT INTO tutor_item_supply_shared_budget_windows "
                    "(root_id,pool_key,provider_key,window_start,window_end,request_cap,token_cap,resource_cap) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *", (root, "base", provider.provider_key,
                    start, end, caps["requests"], caps["tokens"], max(1, caps["resources"]))).fetchone()
                windows = [window]
                new_root_window_ids.append(str(window["id"]))
            if len(windows) != 1:
                raise OperatorPending("ORIGINAL_ROOT_WINDOW_NOT_UNIQUE_OR_CURRENT")
            window = windows[0]
            if (window["pool_key"], window["provider_key"]) != ("base", provider.provider_key):
                raise OperatorPending("ORIGINAL_ROOT_PROVIDER_POOL_MISMATCH")
            if (window["window_end"] - dbnow(conn)).total_seconds() < root_wall_need[purpose]:
                raise OperatorPending("ORIGINAL_ROOT_WINDOW_TIME_INSUFFICIENT_NO_REPLACEMENT")
            used = budget._root_used("shared", root, UUID(str(window["id"])))
            root_used[purpose] = used
            required = root_needs[purpose]
            if used["requests"] + required["requests"] > window["request_cap"] or (
                    used["input_tokens"] + used["output_tokens"] + required["tokens"] > window["token_cap"]):
                raise OperatorPending("EXISTING_ROOT_REMAINING_CAP_INSUFFICIENT_NO_RESET")
            roots[purpose] = dict(root_id=str(root), canonical_key=obligation.canonical_key,
                blueprint_id=str(blueprint), window_id=str(window["id"]), window_start=window["window_start"].isoformat(),
                window_end=window["window_end"].isoformat(), caps=dict(requests=window["request_cap"],
                    tokens=window["token_cap"], resources=window["resource_cap"]))
        preserved_globals = conn.execute("SELECT to_jsonb(t) AS v FROM tutor_item_supply_runtime_global_limits t "
            "WHERE NOT(id=ANY(%s::uuid[])) ORDER BY id", (new_global_ids,)).fetchall()
        preserved_roots = conn.execute("SELECT to_jsonb(t) AS v FROM tutor_item_supply_shared_budget_windows t "
            "WHERE NOT(id=ANY(%s::uuid[])) ORDER BY id", (new_root_window_ids,)).fetchall()
        if digest(_json_rows(old_globals)) != digest(_json_rows(preserved_globals)) or digest(_json_rows(old_roots)) != digest(_json_rows(preserved_roots)):
            raise OperatorPending("PRIOR_WINDOW_HISTORY_CHANGED")
        bindings = dict(plan_hash=digest(plan), provider=provider.provider_key, model=provider.configured_model,
            global_limit_ids=[str(r["id"]) for r in active], start=start.isoformat(), end=end.isoformat(), roots=roots)
        if expected is not None and any(expected[k] != value for k, value in bindings.items()):
            raise OperatorPending("ORIGINAL_CAMPAIGN_ACCOUNTING_BINDING_CHANGED")
        receipt = expected or dict(**bindings, new_global_limit_ids=new_global_ids,
            new_root_window_ids=new_root_window_ids, previous_global_hash=digest(_json_rows(old_globals)),
            previous_root_window_hash=digest(_json_rows(old_roots)), monetary_budget_reset=False,
            monetary_cost=None, sql_positive_unused_cap_placeholder=1, all_prior_usage_unknown_retained=True)
        if expected is None:
            receipt.update(initial_global_used=global_used, initial_root_used=root_used,
                initial_remaining_plan=needs, initial_root_remaining_plan=root_needs)
    save_exact(receipt_path, receipt)
    return receipt


def review_ports(settings: Any, lease: Any) -> tuple[Any, tuple[Any, ...]]:
    from app.services.learning.item_bank.review_contracts import REQUIRED_REVIEW_ROLES
    from app.services.learning.item_supply.review_contracts_v2 import ProviderIdentityV2
    from app.services.learning.item_supply.review_provider import BoundedOpenAIReviewClient, JsonBlindSolverV2, JsonReviewerV2

    ports = []
    for role in ("blind_solver", *[r.value for r in REQUIRED_REVIEW_ROLES]):
        client = BoundedOpenAIReviewClient(settings, profile=lease.profile)
        identity = ProviderIdentityV2(identity=f"{client.configured_provider}.native.v3.{role}",
            provider=client.configured_provider, model=client.model)
        options = dict(identity=identity, profile_hash=lease.profile.profile_hash,
            timeout_seconds=100, max_output_tokens=REVIEW_OUTPUT, max_input_bytes=REVIEW_INPUT)
        ports.append(JsonBlindSolverV2(client, **options) if role == "blind_solver" else
            JsonReviewerV2(client, role=next(r for r in REQUIRED_REVIEW_ROLES if r.value == role), **options))
    return ports[0], tuple(ports[1:])


def original_artifact(conn: Any, candidate_id: str) -> Any:
    with conn.transaction():
        rows = conn.execute("SELECT * FROM tutor_item_supply_shared_generation_artifacts WHERE candidate_id=%s",
            (UUID(candidate_id),)).fetchall()
        if len(rows) > 1:
            raise OperatorPending("CANDIDATE_ARTIFACT_IDENTITY_CONFLICT")
    return rows[0] if rows else None


def published_readback(conn: Any, artifact: Any, folder: Path) -> dict[str, Any] | None:
    """Read original494 DATA; never restore original issuer/runner capabilities."""
    from app.services.learning.item_bank.native_publication_contracts import NativePublicationProofV1
    with conn.transaction():
        rows = conn.execute("SELECT p.proof_json,p.proof_hash,e.state,e.id AS event_id,m.id AS material_id "
            "FROM tutor_learning_item_native_publication_proofs p "
            "JOIN tutor_learning_item_publication_events e ON e.version_id=p.version_id "
            "JOIN tutor_learning_item_practice_materializations m ON m.id=p.materialization_id "
            "WHERE p.generation_artifact_id=%s AND e.state_version=(SELECT max(state_version) "
            "FROM tutor_learning_item_publication_events WHERE version_id=p.version_id)", (artifact["id"],)).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise OperatorPending("PUBLICATION_READBACK_CONFLICT")
    row = rows[0]
    proof = NativePublicationProofV1.model_validate_json(json.dumps(row["proof_json"]))
    if (proof.proof_hash != row["proof_hash"] or proof.generation_artifact_id != artifact["id"]
            or proof.version_id != artifact["version_id"] or proof.content_hash != artifact["content_hash"]
            or proof.source_hash != artifact["source_hash"] or proof.materialization_id != row["material_id"]):
        raise OperatorPending("PUBLICATION_READBACK_BINDING_MISMATCH")
    result = dict(status="published_original_data_readback_not_current_permit", target=proof.target_id,
        handle=proof.item_handle, version_id=str(proof.version_id), publication_event_id=str(proof.publication_event_id),
        latest_state=row["state"], materialization_id=str(proof.materialization_id), facts_receipt_id=str(proof.facts_receipt_id),
        provider_calls_this_invocation=0, course_inventory_ready=False, public_release=False, E_complete=False)
    event(folder, "published_readback_only", version_id=str(proof.version_id), current_permit=False)
    return result


@dataclass
class LivePublication:
    """Keep concrete semantic owners alive for an importing main, never serialize them."""
    result: dict[str, Any]
    lease: Any
    validation_owner: Any
    review_owner: Any
    facts_owner: Any
    publisher: Any
    runner: Any
    continuation_owner: Any


def execute_slot(conn: Any, *, settings: Any, authority: Any, materials: Any, provider: Any,
                 plan: dict[str, Any], path: Path, slot_name: str, locks: Any) -> LivePublication | dict[str, Any]:
    """Main library seam; same connection/owners through validation493/publication494."""
    from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1, build_finite_generation_request
    from app.services.learning.item_supply.generation_contracts import GenerationLimitsV2
    from app.services.learning.item_supply.shared_pipeline import SharedGenerationPipeline
    from app.services.learning.item_supply.shared_pipeline_repository import SharedPipelineArtifactRepository
    from app.services.learning.item_supply.diagnostic_policy import completed_blind_allowed, diagnostic_warnings
    from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner
    from app.services.learning.item_supply.shared_validation import SharedValidationPipeline
    from app.services.learning.item_supply.shared_review import SharedReviewPipeline
    from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner
    from app.services.learning.item_supply.parameter_profiles import ExecutionParameterProfileV1
    from app.services.learning.item_supply.policies import RetryPolicyV1
    from app.services.learning.item_supply.sandbox.execution_contracts import RUNNER_VERSION
    from app.services.learning.item_bank.native_import import NativeLearningItemBankImporter
    from app.services.learning.item_bank.native_publication import NativeLearningItemPublicationService
    from app.services.learning.item_bank.native_publication_contracts import NativeInternalRuntimeBindingV1

    # Reject mixed policy plans before this imported seam touches the DB too.
    evidence_policy = selected_admission_policy(plan)
    campaign_plan = path / "campaign-plan.json"
    if campaign_plan.exists() and read(campaign_plan) != plan:
        raise OperatorPending("IMMUTABLE_CAMPAIGN_POLICY_PLAN_CONFLICT")
    # The importing-main seam must be just as isolated as the CLI, before writes.
    require_idle(conn)
    with conn.transaction():
        if conn.execute("SELECT current_database() AS n").fetchone()["n"] != DATABASE:
            raise OperatorPending("EXACT_ISOLATED_DATABASE_REQUIRED")
    slot = next(s for s in plan["slots"] if s["slot"] == slot_name)
    cases = campaign_cases(path, plan)
    folder = path / "slots" / slot_name
    folder.mkdir(parents=True, exist_ok=True)
    intent_path = folder / "candidate-intent.json"
    existed = intent_path.exists()
    artifact = None
    if existed:
        intent = read(intent_path)
        if intent["plan_hash"] != digest(plan) or intent["slot"] != slot_name:
            raise OperatorPending("IMMUTABLE_CANDIDATE_INTENT_CONFLICT")
        if any(intent[k] != v for k, v in cases["cases"][slot_name].items()):
            raise OperatorPending("IMMUTABLE_CANDIDATE_INTENT_CONFLICT")
        artifact = original_artifact(conn, intent["candidate_id"])
        if artifact is not None:
            with conn.transaction():
                original_policy = SharedPipelineArtifactRepository(conn, enabled=True).published_generation_policy(artifact)
                if original_policy != evidence_policy:
                    raise OperatorPending("ORIGINAL_CANDIDATE_ADMISSION_POLICY_CHANGED")
        publication = None if artifact is None else published_readback(conn, artifact, folder)
        decision = resume_decision(folder, artifact_exists=artifact is not None, publication_exists=publication is not None)
        if publication is not None:
            return publication
        if decision != "fresh_491_continuation_required":
            raise OperatorPending("PARTIAL_OWNER_LIFETIME_RUN_PENDING_NO_AUTOMATIC_RETRY")
        # DB is an independent dispatch fence, even if the local marker write was lost.
        with conn.transaction():
            used_review = conn.execute("SELECT 1 FROM tutor_item_supply_shared_reservations WHERE root_id=%s "
                "AND reservation_key=%s LIMIT 1", (artifact["root_id"], "review." + artifact["id"].hex)).fetchone()
        if used_review is not None:
            raise OperatorPending("ORIGINAL_REVIEW_RESERVATION_SPENT_NO_REVIEW_TO_GREEN")
    previews = [factory_spec(s, plan, materials, f"native.v3.preview.{plan['target']}.{s['slot']}", locks)
        for s in plan["slots"]]
    accounting = prepare_campaign(conn, path=path, plan=plan, specs=previews, provider=provider,
        review_pending={slot_name} if existed else None)
    continuation = SharedCandidateContinuationOwner(conn, settings, enabled=True)
    retry = RetryPolicyV1(max_transient_attempts=1, initial_backoff_ms=1, maximum_backoff_ms=1)
    if not existed:
        candidate = UUID(cases["cases"][slot_name]["candidate_id"])
        intent = dict(plan_hash=digest(plan), slot=slot_name, candidate_id=str(candidate),
            item_key=cases["cases"][slot_name]["item_key"], new_author_call_bound=1)
        save(intent_path, intent)
        spec = factory_spec(slot, plan, materials, intent["item_key"], locks)
        with conn.transaction():
            profile = fresh_profile(conn, provider, spec, materials)
            key = profile.profile_key

            gp = SharedGenerationPipeline(conn, settings, enabled=True,
                trusted_model_bindings={(key.provider, key.model_version): provider.configured_model})
            root = UUID(accounting["roots"][spec.coverage_blueprint.scope.purpose.value]["root_id"])
            now = dbnow(conn)
            job = gp.runtime.enqueue(root_id=root, stage_key="native.v3.author." + candidate.hex,
                profile=profile, now=now, priority=100, aging_seconds=60, visibility="public", retry_policy=retry)
            lease = gp.runtime.claim(root_id=root, lease_owner="worker.native.v3." + candidate.hex,
                now=now, lease_seconds=plan["lease_seconds"], visibility="public")
            if lease is None or lease.job_id != job:
                raise OperatorPending("EXACT_NEW_JOB_NOT_CLAIMED")
            request = build_finite_generation_request(spec, candidate_id=candidate, profile=lease.profile,
                materials=materials, limits=GenerationLimitsV2(max_input_bytes=AUTHOR_INPUT,
                    max_output_tokens=AUTHOR_OUTPUT, max_output_bytes=65_536))
            generation_prepared = gp.prepare_generation(lease=lease, request=request, provider=provider,
                source_authority=authority, evidence_policy=evidence_policy)
            if generation_prepared is None:
                raise OperatorPending("ORIGINAL_AUTHOR_RESERVATION_DENIED_NO_CALL")
            if generation_prepared.evidence_policy_hash != evidence_policy.policy_hash:
                raise OperatorPending("ORIGINAL_AUTHOR_POLICY_BINDING_MISMATCH")
        save(folder / "frozen.json", dict(spec=spec.model_dump(mode="json"), request=request.model_dump(mode="json"),
            profile=profile.model_dump(mode="json"), lease_data=lease.model_dump(mode="json"), root_id=str(root),
            job_id=str(job), reservation_id=str(generation_prepared.reservation_id), database=DATABASE,
            provider=provider.provider_key, model=provider.configured_model))
        save(folder / "author-invoked.json", dict(candidate_id=str(candidate), reservation_id=str(generation_prepared.reservation_id),
            max_HTTP_attempts=1, monetary_cost=None, state="dispatch_intent_usage_unknown_until_settled"))
        event(folder, "author_dispatch_intent", candidate_id=str(candidate), max_HTTP_attempts=1)
        require_idle(conn)
        generated = gp.run_generation(generation_prepared, provider)
        with conn.transaction():
            gp.settle_generation(generation_prepared, generated)
        save(folder / "generation.json", generated.model_dump(mode="json"))
        event(folder, "author_settled", candidate_id=str(candidate), state=generated.state,
            usage=None if generated.receipt is None else generated.receipt.provider.usage.model_dump(mode="json"))
        with conn.transaction():
            staged = gp.commit_generation(generation_prepared, generated, source_authority=authority)
        save(folder / "generation-staged.json", asdict(staged))
        if staged.state != "staged" or staged.artifact_id is None:
            raise OperatorPending("AUTHOR_FAILED_OR_QUARANTINED_NO_RETRY")
        artifact_id = staged.artifact_id
        with conn.transaction():
            lease = gp.runtime.refresh_lease(lease, now=dbnow(conn))
    else:
        assert artifact is not None
        frozen = read(folder / "frozen.json")
        spec = FiniteCandidateSpecV1.model_validate_json(json.dumps(frozen["spec"]))
        expected_spec = factory_spec(slot, plan, materials, intent["item_key"], locks)
        if spec != expected_spec or str(artifact["root_id"]) != accounting["roots"][spec.coverage_blueprint.scope.purpose.value]["root_id"]:
            raise OperatorPending("CONTINUATION_SPEC_OR_CANONICAL_ROOT_CHANGED")
        artifact_id = UUID(str(artifact["id"]))
        operation = "v3.resume." + uuid4().hex
        save(folder / "continuation-intent.json", dict(operation=operation, artifact_id=str(artifact_id),
            candidate_id=intent["candidate_id"], new_author_calls=0, original_seals_restored=False))
        with conn.transaction():
            row = conn.execute("SELECT p.profile_json FROM tutor_item_supply_shared_job_controls c "
                "JOIN tutor_item_supply_parameter_profiles p ON p.id=c.profile_id WHERE c.job_id=%s",
                (artifact["job_id"],)).fetchone()
            if row is None:
                raise OperatorPending("ORIGINAL_PROFILE_UNAVAILABLE")
            previous = ExecutionParameterProfileV1.model_validate_json(json.dumps(row["profile_json"]))
            profile = fresh_profile(conn, provider, spec, materials, previous=previous)
            adopted = continuation.adopt(artifact_id=artifact_id, spec=spec, operation_key=operation,
                profile=profile, retry_policy=retry, source_authority=authority,
                lease_owner="worker.native.v3.resume." + uuid4().hex, lease_seconds=plan["lease_seconds"],
                priority=100, aging_seconds=60)
            if adopted is None or str(adopted.binding.root_id) != frozen["root_id"]:
                raise OperatorPending("ACTUAL_491_ADOPTION_NOT_CLAIMED")
            lease = adopted.lease
        save(folder / "continuation.json", adopted.binding.model_dump(mode="json"))
    runner = None
    if plan["target"] != TARGETS[0]:
        from aearn_executor.item_supply_bridge import ItemSupplyRunnerBridge
        require_idle(conn)
        runner = ItemSupplyRunnerBridge.from_docker(locks=locks)
    vp = SharedValidationPipeline(conn, settings, enabled=True, continuation_owner=continuation)
    with conn.transaction():
        validation_prepared = vp.prepare_validation(lease=lease, artifact_id=artifact_id, spec=spec,
            source_authority=authority, runner=runner)
        if validation_prepared is None:
            raise OperatorPending("NEW_VALIDATION_PREPARATION_DENIED")
    # Different filenames permit exactly one genuine491 continuation, no seal hydration.
    prefix = "continued-" if existed else ""
    save(folder / (prefix + "validation-prepared.json"), dict(preparation_id=str(validation_prepared.preparation_id),
        reservation_id=None if validation_prepared.reservation_id is None else str(validation_prepared.reservation_id),
        lease_data=lease.model_dump(mode="json")))
    require_idle(conn)
    validation_result = vp.run_validation(validation_prepared)
    with conn.transaction():
        vp.settle_validation(validation_prepared, validation_result)
    save(folder / (prefix + "validation.json"), vp._result_payload(validation_result))
    with conn.transaction():
        validated = vp.commit_validation(validation_prepared, validation_result)
    save(folder / (prefix + "validation-staged.json"), asdict(validated))
    if validated.state != "machine_verified" or validated.validation_receipt_id is None:
        raise OperatorPending("NATIVE_VALIDATION_NOT_VERIFIED_NO_RETRY")
    with conn.transaction():
        lease = vp.runtime.refresh_lease(validation_prepared.lease, now=dbnow(conn))
        profile_key = vp.artifacts.context(lease, now=dbnow(conn))["key"]
    solver, reviewers = review_ports(settings, lease)
    rp = SharedReviewPipeline(conn, settings, enabled=True, continuation_owner=continuation,
        trusted_model_bindings={(profile_key.provider, profile_key.model_version): solver.provider_identity.model})
    with conn.transaction():
        review_prepared = rp.prepare_review(lease=lease, artifact_id=artifact_id,
            validation_receipt_id=validated.validation_receipt_id, spec=spec,
            source_authority=authority, solver=solver, reviewers=reviewers, runner=runner)
        if review_prepared is None or review_prepared.resources.requests != 7:
            raise OperatorPending("EXACT_SEVEN_PORT_REVIEW_RESERVATION_DENIED")
        if review_prepared.binding.policy_hash != evidence_policy.policy_hash:
            raise OperatorPending("ORIGINAL_REVIEW_POLICY_BINDING_MISMATCH")
    save(folder / "review-prepared.json", dict(reservation_id=str(review_prepared.reservation_id),
        lease_data=lease.model_dump(mode="json"), binding=review_prepared.binding.model_dump(mode="json"),
        resources=review_prepared.resources.model_dump(mode="json")))
    save(folder / "review-invoked.json", dict(reservation_id=str(review_prepared.reservation_id), max_HTTP_attempts=7,
        blind_solver_calls=1, peer_blind_item_role_calls=6, monetary_cost=None, no_re_review_to_green=True))
    event(folder, "review_dispatch_intent", reservation_id=str(review_prepared.reservation_id), max_HTTP_attempts=7)
    require_idle(conn)
    review_result = rp.run_review(review_prepared)
    with conn.transaction():
        rp.settle_review(review_prepared, review_result)
    save(folder / "review.json", dict(safe_reason=review_result.safe_reason,
        blind=None if review_result.blind is None else review_result.blind.model_dump(mode="json"),
        bundle=None if review_result.bundle is None else review_result.bundle.model_dump(mode="json"),
        ambiguity=None if review_result.ambiguity is None else review_result.ambiguity.model_dump(mode="json"),
        usage_state="unknown", monetary_cost=None))
    event(folder, "review_settled", safe_reason=review_result.safe_reason, usage_state="unknown")
    with conn.transaction():
        reviewed = rp.commit_review(review_prepared, review_result)
    save(folder / "review-staged.json", asdict(reviewed))
    if reviewed.blind_receipt_id is None or reviewed.review_receipt_id is None:
        raise OperatorPending("NATIVE_REVIEW_INCOMPLETE_OR_VETOED_RETAINED")
    # Consistency only: the original review owner committed/verified these exact
    # objects, and the original facts issuer below repeats all hard/current fences.
    # Completed wrong is allowed solely by the frozen V3 policy, never by a bool.
    if (review_result.blind is None or review_result.bundle is None
            or review_result.bundle.policy_version != evidence_policy.policy_version
            or review_result.bundle.binding.policy_hash != evidence_policy.policy_hash
            or not completed_blind_allowed(review_result.blind, evidence_policy)):
        raise OperatorPending("NATIVE_REVIEW_POLICY_RESULT_MISMATCH")
    issuer = SharedAdmissionFactsOwner(conn, validation_pipeline=vp, review_pipeline=rp, enabled=True)
    with conn.transaction():
        facts = issuer.issue(lease=lease, validation_prepared=validation_prepared, validation_result=validation_result,
            validation_receipt_id=validated.validation_receipt_id, review_prepared=review_prepared,
            review_result=review_result, blind_receipt_id=reviewed.blind_receipt_id, review_receipt_id=reviewed.review_receipt_id)
    save(folder / "facts.json", facts.model_dump(mode="json"))
    if (facts.evaluation.policy_version != evidence_policy.policy_version
            or facts.evaluation.binding.policy_hash != evidence_policy.policy_hash):
        raise OperatorPending("NATIVE_ADMISSION_POLICY_MISMATCH")
    if facts.evaluation.disposition != "eligible_internal":
        raise OperatorPending("NATIVE_ADMISSION_NOT_ELIGIBLE_RETAINED_NO_PUBLISH")
    scope = spec.coverage_blueprint.scope
    approved = NativeInternalRuntimeBindingV1(target_id=plan["target"], runtime_id=scope.runtime_profile_id,
        runtime_profile_hash=scope.runtime_profile_hash, scorer_version=scope.scorer_version,
        runner_version=None if runner is None else RUNNER_VERSION,
        runtime_lock=None if runner is None else locks[scope.runtime_profile_id])
    importer = NativeLearningItemBankImporter(conn, settings, artifacts=vp.artifacts, source_authority=authority,
        continuation_owner=continuation, enabled=True)
    publisher = NativeLearningItemPublicationService(conn, settings, importer=importer, facts_owner=issuer,
        approved_internal_bindings=(approved,), enabled=True)
    with conn.transaction():
        imported = importer.import_candidate(lease=lease, artifact_id=artifact_id,
            validation_receipt_id=validated.validation_receipt_id, spec=spec, import_key="native.v3." + lease.job_id.hex)
        proof = publisher.publish_internal(imported, lease=lease, spec=spec, facts_receipt=facts)
    save(folder / "import.json", asdict(imported))
    save(folder / "publication.json", proof.model_dump(mode="json"))
    # Do NOT complete/cancel the job or extend any deadline. A's distinct owner may
    # resolve this original lease DATA while its original DB authority is current.
    with conn.transaction():
        current_lease = rp.runtime.refresh_lease(lease, now=dbnow(conn))
    save(folder / "relation-anchor-lease-data.json", dict(lease_data=current_lease.model_dump(mode="json"),
        root_id=str(facts.root_id), artifact_id=str(artifact_id), facts_receipt_id=str(facts.receipt_id),
        version_id=str(proof.version_id),
        relation_calls_reserved=4 if scope.purpose.value == plan["relation_anchor_purpose"] else 0,
        relation_anchor_eligible=scope.purpose.value == plan["relation_anchor_purpose"],
        relation_reservation_issued=False,  # Count above is budget headroom, not A's permit.
        lease_is_data_not_capability=True, original_expiry_unchanged=True))
    result = dict(status="published_internal_not_ready_pack", target=plan["target"], slot=slot_name,
        candidate_id=intent["candidate_id"], handle=proof.item_handle, version_id=str(proof.version_id),
        publication_event_id=str(proof.publication_event_id), materialization_id=str(proof.materialization_id),
        facts_receipt_id=str(facts.receipt_id), root_id=str(facts.root_id), job_id=str(lease.job_id),
        lease_expires_at=current_lease.expires_at.isoformat(),
        relation_anchor_eligible=scope.purpose.value == plan["relation_anchor_purpose"],
        max_HTTP_attempts_this_invocation=7 if existed else 8, monetary_cost=None,
        course_inventory_ready=False, public_release=False, formal_Practice_or_Gate_verified=False, E_complete=False)
    if "admission_policy" in plan:
        result.update(admission_policy=plan["admission_policy"], diagnostic_warnings=list(diagnostic_warnings(facts.evaluation)))
    save(folder / "result.json", result)
    event(folder, "per_item_publication_committed", version_id=str(proof.version_id), inventory_ready=False)
    return LivePublication(result, current_lease, vp, rp, issuer, publisher, runner, continuation)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="offline/inert (also the default)")
    mode.add_argument("--execute", action="store_true", help="MAIN ONLY: explicit isolated DB/provider/runtime IO")
    parser.add_argument("--target", choices=TARGETS, default=TARGETS[0])
    parser.add_argument("--slot", choices=SLOTS)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--admission-policy", choices=ADMISSION_POLICIES, default="strict-v2",
        help="strict-v2 is the unchanged default; diagnostic-v3 requires a new immutable campaign plan")
    parser.add_argument("--campaign-output", help="exact shared campaign directory under .runtime/e-native-type-20261006")
    args = parser.parse_args(argv)
    configure_offline_imports()
    plan = build_plan(args.target, args.seed, admission_policy=args.admission_policy)
    if not args.execute:
        print(json.dumps(dict(status="not_executed_offline_plan", database_io=False, provider_calls=0,
            selected_slot=args.slot, campaign_output=args.campaign_output, plan=plan), ensure_ascii=False, indent=2))
        return 0
    if args.slot is None or args.campaign_output is None:
        parser.error("--execute requires --slot and --campaign-output; reuse the SAME path for all five slots")
    path = campaign_path(args.campaign_output, RUNTIME)
    path.mkdir(parents=True, exist_ok=True)
    lock = path / "operator-active.lock"
    # File presence is a safety fence, not a lease. A crashed run requires main's
    # deliberate stale-lock inspection; the script never steals another worker.
    with lock.open("x", encoding="utf8") as stream:
        stream.write(json.dumps(dict(pid=os.getpid(), at=datetime.now(timezone.utc).isoformat())))
    attempt = path / "attempts" / uuid4().hex
    attempt.mkdir(parents=True)
    try:
        save_exact(path / "campaign-plan.json", plan)
        helper = source_helper()
        helper.configure_imports()
        with helper.connection() as conn:
            with conn.transaction():
                if conn.execute("SELECT current_database() AS n").fetchone()["n"] != DATABASE:
                    raise OperatorPending("EXACT_ISOLATED_DATABASE_REQUIRED")
                authority = helper.public_authority(conn)
                materials = helper.current_materials()[args.target]
                current_sources = [authority.authorize(m).model_dump(mode="json") for m in materials]
            save(attempt / "current-source-preflight.json", dict(target=args.target, sources=current_sources,
                new_GETs=0, signing_key_reads=0, same_connection=True))
            settings = settings_for_execute()
            from app.services.learning.item_supply.provider_adapter import OpenAICompatibleGenerationProvider
            provider = OpenAICompatibleGenerationProvider(settings, max_http_attempts=1)
            locks = None
            if args.target != TARGETS[0]:
                from aearn_executor.item_supply_bridge import candidate_locks
                locks = candidate_locks(IMAGE)
            live = execute_slot(conn, settings=settings, authority=authority, materials=materials, provider=provider,
                plan=plan, path=path, slot_name=args.slot, locks=locks)
            result = live.result if isinstance(live, LivePublication) else live
            save(attempt / "result.json", result)
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Never log ValueError/provider/DB text, DSNs, URLs, traceback or bodies.
        failure = dict(status="pending_or_failed_retained_no_retry", error_type=type(exc).__name__,
            safe_code=str(exc) if type(exc) is OperatorPending else "DETAILS_WITHHELD",
            slot=args.slot, monetary_cost=None, usage_unknown_not_zero=True,
            no_new_author_on_retry=True, no_seal_hydration=True, course_inventory_ready=False,
            public_release=False, E_complete=False)
        save(attempt / "failure.json", failure)
        print(json.dumps(failure), file=sys.stderr)
        return 2
    finally:
        lock.unlink()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps(dict(status="not_executed_or_pending", error_type=type(exc).__name__,
            safe_code=str(exc) if type(exc) is OperatorPending else "DETAILS_WITHHELD",
            monetary_cost=None, public_release=False)), file=sys.stderr)
        raise SystemExit(2) from None
