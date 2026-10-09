"""Pure operator checks only. No live DB/provider/Docker/source/key operations."""
from __future__ import annotations

import ast
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

RESEARCH = Path(__file__).resolve().parents[5] / ".trellis/tasks/09-22-multi-agent-item-bank-sandbox/research"


@pytest.fixture(scope="module")
def operator():
    sys.path.insert(0, str(RESEARCH))
    spec = importlib.util.spec_from_file_location("native_v3_operator_pure_test", RESEARCH / "native-v3-candidate-chain-20261006.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("target", ("python-kc-binding-v1", "python-state-update-v1", "sqlite-predicate-order-v1"))
def test_registered_five_slot_plan_and_44_call_ceiling(operator, target):
    from native_v3_chain_support_20261006 import SLOTS, build_plan
    from app.services.learning.item_supply.finite_candidate_factory import FiniteSlotAllocationV2
    from app.services.learning.item_supply.finite_task_families import families_for_course

    plan = build_plan(target)
    assert plan == json.loads(json.dumps(plan))  # immutable checkpoint replay is exact
    assert tuple(s["slot"] for s in plan["slots"]) == SLOTS
    assert len({s["allocation"]["family_id"] for s in plan["slots"]}) == 3
    registered = {f.family_id for f in families_for_course(target)}
    for row in plan["slots"]:
        allocation = FiniteSlotAllocationV2.model_validate_json(json.dumps(row["allocation"]))
        assert allocation.family_id in registered
        assert allocation.definition_hash == row["allocation_hash"]
    assert plan["max_author_calls"] + plan["max_blind_and_item_role_calls"] + plan["reserved_relation_calls"] == 44
    assert sorted(c["requests"] for c in plan["root_caps"].values()) == [8, 36]
    assert plan["operator_HTTP_attempts"] == 40 and plan["reserved_relation_calls"] == 4
    assert not plan["relation_execution_in_this_operator"]
    assert plan["monetary_cost"] is None and not plan["monetary_budget_reset"]
    assert not plan["course_inventory_ready"] and not plan["seeds_prove_independence"]
    if target == "python-kc-binding-v1":
        assert [s["allocation"]["family_id"].rsplit(":", 1)[1] for s in plan["slots"]] == [
            "diagnose", "diagnose", "trace", "counterexample", "diagnose"]
        assert plan["global_caps"]["execution_seconds"] == 0


@pytest.mark.parametrize("seed", [-1, 252, True])
def test_seed_bound_is_frozen_no_silent_new_campaign(operator, seed):
    with pytest.raises(operator.OperatorPending):
        operator.build_plan("python-kc-binding-v1", seed)


@pytest.mark.parametrize("target", ("python-kc-binding-v1", "python-state-update-v1", "sqlite-predicate-order-v1"))
@pytest.mark.parametrize("admission_policy", ["strict-v2", "diagnostic-v3"])
def test_real_factory_preserves_canonical_root_for_all_primary_slots(operator, target, admission_policy):
    # Existing strictly offline synthetic MATERIAL DATA, not a current source proof.
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for

    plan = operator.build_plan(target, admission_policy=admission_policy)
    materials = materials_for(target)
    locks = {r: SimpleNamespace(fingerprint="a" * 64) for r in ("python-stdout-v1", "sqlite-query-v1")}
    specs = [operator.factory_spec(row, plan, materials, f"pure.synthetic.operator.{i}", locks)
        for i, row in enumerate(plan["slots"])]
    keys = [operator.canonical_obligation(s).canonical_key for s in specs]
    assert len(set(keys[:4])) == 1 and keys[4] != keys[0]
    assert all(s.blueprint.version == "finite-public-spec-v3" for s in specs)
    assert len({s.public_template.item_key for s in specs}) == 5
    assert specs[0].coverage_blueprint == specs[3].coverage_blueprint
    assert specs[0].coverage_blueprint.scope.assistance_policy_hash == specs[4].coverage_blueprint.scope.assistance_policy_hash
    legacy_plan = operator.build_plan(target)
    legacy = operator.factory_spec(legacy_plan["slots"][0], legacy_plan, materials, "pure.synthetic.same.root", locks)
    assert keys[0] == operator.canonical_obligation(legacy).canonical_key
    assert specs[0].coverage_blueprint == legacy.coverage_blueprint


@pytest.mark.parametrize("admission_policy", ["strict-v2", "diagnostic-v3"])
def test_inert_plan_does_not_open_source_credentials_database_or_write(operator, monkeypatch, capsys, admission_policy):
    import psycopg
    import dotenv

    def forbidden(*args, **kwargs):
        pytest.fail("inert plan attempted IO")
    for attr in ("source_helper", "settings_for_execute", "execute_slot", "save", "save_exact", "campaign_cases"):
        monkeypatch.setattr(operator, attr, forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(dotenv, "dotenv_values", forbidden)
    assert operator.main(["--plan", "--target", "python-kc-binding-v1", "--campaign-output", "not-created",
        "--admission-policy", admission_policy]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["provider_calls"] == 0 and result["database_io"] is False
    assert result["plan"]["max_HTTP_attempts"] == 44
    assert operator.selected_admission_policy(result["plan"]).policy_version == (
        "autonomous_evidence_policy_v3" if admission_policy == "diagnostic-v3" else "autonomous_evidence_policy_v2")
    assert operator.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_executed_offline_plan"


def test_exclusive_checkpoint_never_overwrites_failure_or_intent(operator, tmp_path):
    operator.save_exact(tmp_path / "receipt.json", {"usage": "unknown", "cost": None})
    operator.save_exact(tmp_path / "receipt.json", {"usage": "unknown", "cost": None})
    with pytest.raises(operator.OperatorPending, match="IMMUTABLE_CHECKPOINT_CONFLICT"):
        operator.save_exact(tmp_path / "receipt.json", {"usage": "known", "cost": 0})
    assert operator.read(tmp_path / "receipt.json")["cost"] is None


def test_all_campaign_case_ids_are_frozen_distinct_and_reused(operator, tmp_path):
    plan = operator.build_plan("python-kc-binding-v1")
    original = operator.campaign_cases(tmp_path, plan)
    assert operator.campaign_cases(tmp_path, plan) == original
    assert len({r["candidate_id"] for r in original["cases"].values()}) == 5
    assert len({r["item_key"] for r in original["cases"].values()}) == 5
    with pytest.raises(operator.OperatorPending, match="IMMUTABLE_CAMPAIGN_CASES_CONFLICT"):
        operator.campaign_cases(tmp_path, operator.build_plan("python-kc-binding-v1", 1))


@pytest.mark.parametrize("occupied_count", range(6))
def test_future_four_relation_calls_never_spent_by_completed_slots(operator, occupied_count):
    from native_v3_chain_support_20261006 import SLOTS, required_remaining
    plan = operator.build_plan("python-kc-binding-v1")
    totals, roots = required_remaining(plan, set(SLOTS[:occupied_count]))
    assert totals["requests"] == (5 - occupied_count) * 8 + 4
    assert sum(c["requests"] for c in roots.values()) == totals["requests"]
    assert roots["knowledge_check"]["requests"] >= 4


def test_491_continuation_funds_new_seven_ports_not_a_second_author(operator):
    from native_v3_chain_support_20261006 import required_remaining
    plan = operator.build_plan("python-kc-binding-v1")
    totals, roots = required_remaining(plan, {"practice-1"}, review_pending={"practice-1"})
    assert totals["requests"] == 43 and roots["knowledge_check"]["requests"] == 35
    assert totals["candidates"] == 4
    with pytest.raises(operator.OperatorPending):
        required_remaining(plan, set(), review_pending={"practice-1"})


@pytest.mark.parametrize("review_marker,continuation,artifact,published,expected", [
    (False, False, False, False, "pending_author_owner_lost_no_second_call"),
    (False, False, True, False, "fresh_491_continuation_required"),
    (True, False, True, False, "pending_original_review_owner_lost_no_retry"),
    (False, True, True, False, "pending_continuation_already_attempted"),
    (True, True, True, True, "published_readback_only"),
])
def test_restart_never_hydrates_seals_or_re_reviews_to_green(operator, tmp_path, review_marker, continuation, artifact, published, expected):
    from native_v3_chain_support_20261006 import resume_decision
    if review_marker:
        (tmp_path / "review-prepared.json").touch()
    if continuation:
        (tmp_path / "continuation-intent.json").touch()
    assert resume_decision(tmp_path, artifact_exists=artifact, publication_exists=published) == expected


@pytest.mark.parametrize("bad", ["..", ".", "../escape", "nested/campaign"])
def test_campaign_paths_cannot_escape(operator, tmp_path, bad):
    with pytest.raises(operator.OperatorPending):
        operator.campaign_path(bad, tmp_path)


def test_absolute_and_simple_campaign_paths_remain_under_private_runtime(operator, tmp_path):
    assert operator.campaign_path("campaign", tmp_path) == tmp_path / "campaign"
    assert operator.campaign_path(str(tmp_path / "campaign"), tmp_path) == tmp_path / "campaign"
    with pytest.raises(operator.OperatorPending):
        operator.campaign_path(str(tmp_path.parent / "escape"), tmp_path)


def test_ast_chain_owner_lifetimes_fenced_settlement_and_no_new_schema_modules(operator):
    source = (RESEARCH / "native-v3-candidate-chain-20261006.py").read_text(encoding="utf8")
    tree = ast.parse(source)
    imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any("native_type_evidence" in name or "native_exposure" in name for name in imported)
    assert "native-shared-generation-20261003.py" not in source
    assert "native-shared-full-chain-20261003.py" not in source
    assert "private_key" not in source and "sign_source" not in source
    chain = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute_slot")
    calls = sorted([n for n in ast.walk(chain) if isinstance(n, ast.Call)], key=lambda n: n.lineno)
    def at(name):
        return next(n.lineno for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == name)
    assert at("run_generation") < at("settle_generation") < at("commit_generation")
    assert at("run_validation") < at("settle_validation") < at("commit_validation")
    assert at("run_review") < at("settle_review") < at("commit_review") < at("issue") < at("publish_internal")
    assert not any(isinstance(n.func, ast.Attribute) and n.func.attr in ("complete", "heartbeat", "cancel") for n in calls)
    assert "source_authority=authority" in source
    assert "validation_prepared=validation_prepared, validation_result=validation_result" in source
    assert "review_result=review_result" in source


class FakeRows:
    def __init__(self, rows):
        self.rows = rows
    def fetchall(self):
        return self.rows
    def fetchone(self):
        return self.rows[0] if self.rows else None


class BudgetPreflightConnection:
    """No sockets; handles only the pre-existing global-window preflight queries."""
    def __init__(self, rows):
        self.rows = rows
        self.statements = []
        self.now = datetime.now(timezone.utc)
    def transaction(self):
        return nullcontext()
    def execute(self, sql, params=()):
        self.statements.append(sql)
        assert not sql.startswith(("INSERT", "UPDATE", "DELETE"))
        if "clock_timestamp()" in sql:
            return FakeRows([{"n": self.now}])
        if "to_jsonb(t)" in sql:
            return FakeRows([])
        if "runtime_global_limits WHERE window_start" in sql:
            return FakeRows(self.rows)
        if "pg_advisory" in sql:
            return FakeRows([])
        pytest.fail("unexpected pure preflight query")


@pytest.mark.parametrize("partial", [False, True])
def test_preexisting_global_limit_unknown_usage_denies_without_replacement(operator, monkeypatch, tmp_path, partial):
    import app.services.learning.item_supply.budget as budget_module
    from app.services.learning.item_supply.policies import RESOURCE_KINDS
    now = datetime.now(timezone.utc)
    rows = [dict(id=uuid4(), dimension_kind=dim, dimension_key=key, resource_kind=kind,
        window_start=now - timedelta(minutes=5), window_end=now + timedelta(minutes=30), cap_amount=44)
        for dim, key in (("system", "item-supply"), ("window", "item-supply"), ("pool", "base"), ("provider", "deepseek"))
        for kind in RESOURCE_KINDS]
    if partial:
        rows.pop()
    class UnknownBudget:
        def __init__(self, conn):
            pass
        def _global_used(self, identity, kind):
            # Original unknown reservation is NOT free/zero.
            assert isinstance(identity, UUID)
            return 1
        def register_global_limit(self, **kwargs):
            pytest.fail("must not replace existing active period")
    monkeypatch.setattr(budget_module, "ItemSupplyBudgetRepository", UnknownBudget)
    conn = BudgetPreflightConnection(rows)
    with pytest.raises(operator.OperatorPending, match="EXISTING_PARTIAL" if partial else "EXISTING_GLOBAL_REMAINING"):
        operator.prepare_campaign(conn, path=tmp_path, plan=operator.build_plan("python-kc-binding-v1"),
            specs=[], provider=SimpleNamespace(provider_key="deepseek", configured_model="configured-actual-model"))
    assert not (tmp_path / "resource-window.json").exists()


def test_stable_profile_key_versions_increment_without_root_variants(operator):
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for
    plan = operator.build_plan("python-kc-binding-v1")
    materials = materials_for(plan["target"])
    spec = operator.factory_spec(plan["slots"][0], plan, materials, "synthetic.profile-only", None)
    class ProfileConnection:
        latest = 7
        def execute(self, sql, params=()):
            return FakeRows([{"n": datetime.now(timezone.utc)}] if "clock_timestamp" in sql else [{"v": self.latest}])
    provider = SimpleNamespace(provider_key="deepseek", configured_model="deepseek-flash")
    conn = ProfileConnection()
    first = operator.fresh_profile(conn, provider, spec, materials)
    conn.latest = first.version  # enqueue registers the first legitimate version.
    continued = operator.fresh_profile(conn, provider, spec, materials, previous=first)
    assert (first.version, continued.version) == (8, 9)
    assert first.profile_key == continued.profile_key
    assert first.profile_key.agent_role == "native.shared.v3.author.python-kc-binding-v1"
    assert first.current.request_timeout_ms == 100_000
    assert first.ceiling == continued.ceiling
    assert first.profile_key.key_hash == continued.profile_key.key_hash


@pytest.mark.parametrize("failure", ["none", "requests", "global_time", "root_time"])
def test_existing_canonical_root_windows_reused_with_unknown_usage_never_replaced(operator, monkeypatch, tmp_path, failure):
    import app.services.learning.item_supply.budget as budget_module
    import app.services.learning.item_supply.repository as runtime_module
    import app.services.learning.item_supply.storage as storage_module
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for

    plan = operator.build_plan("python-kc-binding-v1")
    materials = materials_for(plan["target"])
    specs = [operator.factory_spec(row, plan, materials, f"pure.root.reuse.{i}", None) for i, row in enumerate(plan["slots"])]
    now = datetime.now(timezone.utc)
    roots = {purpose: uuid4() for purpose in plan["root_caps"]}
    windows = {root: dict(id=uuid4(), root_id=root, pool_key="base", provider_key="deepseek",
        window_start=now - timedelta(minutes=5), window_end=now + timedelta(minutes=30 if failure == "root_time" else 180),
        request_cap=1 if failure == "requests" else caps["requests"] + 7, token_cap=caps["tokens"] + 2,
        resource_cap=max(1, caps["resources"])) for purpose, caps in plan["root_caps"].items() for root in [roots[purpose]]}
    rows = [dict(id=uuid4(), dimension_kind=dim, dimension_key=key, resource_kind=kind,
        window_start=now - timedelta(minutes=5), window_end=now + timedelta(minutes=30 if failure == "global_time" else 180), cap_amount=max(1, cap) + 10)
        for dim, key in (("system", "item-supply"), ("window", "item-supply"), ("pool", "base"), ("provider", "deepseek"))
        for kind, cap in plan["global_caps"].items()]
    class RootConnection(BudgetPreflightConnection):
        def execute(self, sql, params=()):
            assert not sql.startswith(("INSERT", "UPDATE", "DELETE"))
            if "shared_budget_windows WHERE root_id" in sql:
                self.statements.append(sql)
                return FakeRows([windows[params[0]]])
            if "to_jsonb(t)" in sql:
                self.statements.append(sql)
                values = windows.values() if "shared_budget_windows" in sql else rows
                return FakeRows([{"v": value} for value in values])
            return super().execute(sql, params)
    class OriginalBudget:
        def __init__(self, conn):
            pass
        def _global_used(self, identity, kind):
            return 1
        def _root_used(self, namespace, root, window):
            assert namespace == "shared" and windows[root]["id"] == window
            return dict(requests=7, input_tokens=1, output_tokens=1)
        def register_global_limit(self, **kwargs):
            pytest.fail("active global limits must not be replaced")
    ensured = []
    class OriginalRuntime:
        def __init__(self, conn):
            pass
        def ensure_shared_root(self, *, blueprint_id, obligation, pool, provider_key):
            assert pool == "base" and provider_key == "deepseek"
            ensured.append(obligation.canonical_key)
            return roots[obligation.purpose]
    class SharedStorage:
        def __init__(self, conn):
            pass
        def register_policy(self, policy):
            pass
        def register_blueprint(self, blueprint):
            return roots[blueprint.scope.purpose.value]
    monkeypatch.setattr(budget_module, "ItemSupplyBudgetRepository", OriginalBudget)
    monkeypatch.setattr(runtime_module, "ItemSupplyRuntimeRepository", OriginalRuntime)
    monkeypatch.setattr(storage_module, "PostgresSharedSupplyStorage", SharedStorage)
    conn = RootConnection(rows)
    kwargs = dict(path=tmp_path, plan=plan, specs=specs,
        provider=SimpleNamespace(provider_key="deepseek", configured_model="deepseek-flash"))
    if failure != "none":
        code = {"requests": "EXISTING_ROOT_REMAINING", "global_time": "ORIGINAL_GLOBAL_WINDOW_TIME",
                "root_time": "ORIGINAL_ROOT_WINDOW_TIME"}[failure]
        with pytest.raises(operator.OperatorPending, match=code):
            operator.prepare_campaign(conn, **kwargs)
    else:
        receipt = operator.prepare_campaign(conn, **kwargs)
        assert receipt["new_global_limit_ids"] == [] and receipt["new_root_window_ids"] == []
        assert {r["root_id"] for r in receipt["roots"].values()} == {str(r) for r in roots.values()}
        assert len(ensured) == 2  # four primary slots did NOT create four roots.
        assert operator.prepare_campaign(conn, **kwargs) == receipt
        assert receipt["all_prior_usage_unknown_retained"]


@pytest.mark.parametrize("target", ("python-kc-binding-v1", "python-state-update-v1", "sqlite-predicate-order-v1"))
def test_new_time_budgets_cover_serial_calls_runner_and_control_margin(operator, target):
    from native_v3_chain_support_20261006 import remaining_time_plan
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for

    plan = operator.build_plan(target)
    wall, roots = remaining_time_plan(plan, set())
    assert plan["max_HTTP_attempts"] == 44 and plan["provider_timeout_seconds"] == 100
    assert wall == 4400 + plan["global_caps"]["execution_seconds"] + 5 * plan["control_margin_seconds"]
    assert plan["period_seconds"] > wall
    anchor_wall = 12 * 100 + plan["item_execution_seconds"] + plan["control_margin_seconds"]
    assert anchor_wall < plan["lease_seconds"] == plan["parent_seconds"] <= 3600
    assert roots[plan["relation_anchor_purpose"]] <= wall
    assert plan["recommended_execution_order"][-1] == "assessment-2"
    material = materials_for(target)
    locks = {r: SimpleNamespace(fingerprint="a" * 64) for r in ("python-stdout-v1", "sqlite-query-v1")}
    spec = operator.factory_spec(plan["slots"][0], plan, material, "pure.timed.spec", locks)
    conn = SimpleNamespace(execute=lambda sql, params=(): FakeRows([
        {"n": datetime.now(timezone.utc)} if "clock_timestamp" in sql else {"v": 0}]))
    provider = SimpleNamespace(provider_key="deepseek", configured_model="offline")
    profile = operator.fresh_profile(conn, provider, spec, material)
    assert profile.current.request_timeout_ms == 100_000
    assert profile.current.stage_deadline_ms == profile.current.parent_deadline_ms == plan["parent_seconds"] * 1000
    # An older insufficient frozen profile is history, not a reason to expand it.
    old_values = profile.current.model_copy(update={"stage_deadline_ms": 1_200_000, "parent_deadline_ms": 1_200_000})
    old = profile.model_copy(update={k: old_values for k in ("initial", "current", "last_stable", "floor", "ceiling")})
    before = old.model_dump_json()
    with pytest.raises(operator.OperatorPending, match="ORIGINAL_PROFILE_TIME_BOUND_INSUFFICIENT"):
        operator.fresh_profile(conn, provider, spec, material, previous=old)
    assert old.model_dump_json() == before


def test_imported_execute_seam_denies_wrong_database_before_writes(operator, monkeypatch, tmp_path):
    from psycopg.pq import TransactionStatus
    conn = SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE),
        transaction=nullcontext, execute=lambda *a: FakeRows([{"n": "wrong_database"}]))
    monkeypatch.setattr(operator, "campaign_cases", lambda *a: pytest.fail("no checkpoint before isolated DB gate"))
    with pytest.raises(operator.OperatorPending, match="EXACT_ISOLATED_DATABASE_REQUIRED"):
        operator.execute_slot(conn, settings=None, authority=None, materials=None, provider=None,
            plan=operator.build_plan("python-kc-binding-v1"), path=tmp_path, slot_name="practice-1", locks=None)
    assert not list(tmp_path.iterdir())


def test_execute_settings_pin_public_routes_and_schedulers_off(operator, monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *a: {"DEEPSEEK_API_KEY": "offline-test", "DEEPSEEK_MODEL": "offline"})
    for key in ("LEARNING_ITEM_SUPPLY_SCHEDULER_ENABLED", "LEARNING_ITEM_BANK_AGENT_REVIEW_ENABLED",
                "TUTOR_LEARNING_ARTIFACTS_ENABLED", "TUTOR_ARTIFACT_TEACHING_MODE_ENABLED",
                "TUTOR_PROACTIVE_SCHEDULER_ENABLED", "TUTOR_PROACTIVE_CUTOVER_ELIGIBLE"):
        monkeypatch.setenv(key, "true")
    settings = operator.settings_for_execute()  # dotenv fully substituted; no real key read.
    assert not any((settings.learning_item_supply_scheduler_enabled, settings.learning_item_bank_agent_review_enabled,
        settings.tutor_learning_artifacts_enabled, settings.tutor_artifact_teaching_mode_enabled,
        settings.tutor_proactive_scheduler_enabled, settings.tutor_proactive_cutover_eligible))


@pytest.mark.parametrize("target", ("python-kc-binding-v1", "python-state-update-v1", "sqlite-predicate-order-v1"))
def test_plan_covers_actual_generation_and_runner_resource_interfaces(operator, target):
    from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
    from app.services.learning.item_supply.finite_task_ambiguity import build_finite_ambiguity_plan, FiniteTaskAmbiguityOwner
    from app.services.learning.item_supply.sandbox.execution import SandboxCandidateExecutionPort
    from app.services.learning.item_supply.sandbox.blind_scorer import SandboxBlindAnswerScorer
    from app.services.learning.item_supply.shared_pipeline_repository import generation_resources
    from app.services.learning.item_supply.finite_candidate_factory import build_finite_generation_request
    from app.services.learning.item_supply.generation_contracts import GenerationLimitsV2
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for
    from tests.learning.test_item_supply_flexible_spec import proposed_source
    from tests.learning.test_item_supply_generation import make_request
    from tests.learning.test_item_supply_v2_execution_review import binding_for

    plan = operator.build_plan(target)
    materials = materials_for(target)
    locks = {r: SimpleNamespace(fingerprint="a" * 64) for r in ("python-stdout-v1", "sqlite-query-v1")}
    base, _ = make_request()
    runner = SimpleNamespace(run=lambda **kw: pytest.fail("resource planning must never execute"))
    execution_total = 0
    for i, row in enumerate(plan["slots"]):
        spec = operator.factory_spec(row, plan, materials, f"pure.resource.spec.{i}", locks)
        source = proposed_source(spec)
        request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=base.profile, materials=materials,
            limits=GenerationLimitsV2(max_input_bytes=131072, max_output_tokens=8192, max_output_bytes=65536))
        generated = generation_resources(request, 1)
        assert (generated.requests, generated.input_tokens, generated.output_tokens, generated.candidates) == (1, 131072, 8192, 1)
        inputs = prepare_finite_candidate_validation(source, spec=spec, materials=materials)
        ambiguity = build_finite_ambiguity_plan(source, spec=spec, inputs=inputs)
        deadline = datetime.now(timezone.utc) + timedelta(seconds=plan["lease_seconds"])
        ambiguity_work = FiniteTaskAmbiguityOwner(None if target == "python-kc-binding-v1" else runner,
            parent_deadline_at=deadline).resource_plan(ambiguity)
        if target == "python-kc-binding-v1":
            assert ambiguity_work.execution_seconds == 0 and inputs.static_facts is not None
            from app.core.config import Settings
            from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
            from app.services.learning.item_supply.review_provider import review_resource_plan
            settings = Settings(_env_file=None, llm_type="deepseek", deepseek_api_key="offline-only",
                deepseek_base_url="https://invalid.example", deepseek_model="offline", llm_timeout_seconds=100)
            solver, reviewers = operator.review_ports(settings, SimpleNamespace(profile=base.profile))
            binding = binding_for(source).model_copy(update={"profile_hash": base.profile.profile_hash})
            with finite_review_context(source, spec=spec, materials=materials):
                reviewed = review_resource_plan(source, binding=binding, validation_receipt=inputs.static_facts.validation,
                    solver=solver, reviewers=reviewers)
            assert reviewed.requests == 7 and reviewed.input_tokens <= 7 * 262144
            assert reviewed.output_tokens == 7 * 2048 and reviewed.candidates == 0
        else:
            validation_work = SandboxCandidateExecutionPort(runner, probe_plan=inputs.probe_plan,
                finite_spec=spec, parent_deadline_at=deadline).resource_plan(source)
            blind_work = SandboxBlindAnswerScorer(runner, binding=binding_for(source), finite_spec=spec,
                parent_deadline_at=deadline).resource_plan(source)
            execution = validation_work.execution_seconds + blind_work.execution_seconds + ambiguity_work.execution_seconds
            assert execution <= plan["item_execution_seconds"]
            execution_total += execution
    assert execution_total <= plan["global_caps"]["execution_seconds"]


@pytest.mark.parametrize("admission_policy", ["strict-v2", "diagnostic-v3"])
def test_operator_wiring_uses_actual_return_types_and_signatures_without_live_io(operator, monkeypatch, tmp_path, admission_policy):
    """Signature/transaction unit seam only: mocked owners are NOT live authority."""
    from contextlib import contextmanager
    from unittest.mock import create_autospec
    from psycopg.pq import TransactionStatus
    from app.services.learning.item_supply import shared_pipeline, shared_validation, shared_review, shared_admission_facts, shared_continuation
    from app.services.learning.item_bank import native_import, native_publication
    from app.services.learning.item_bank.repository import LearningItemImportResult
    from app.services.learning.item_supply.shared_pipeline_contracts import PreparedSharedGeneration, SharedPipelineStageResult
    from app.services.learning.item_supply.shared_validation_contracts import SharedValidationStageResult
    from app.services.learning.item_supply.shared_review import SharedReviewStageResult
    from app.services.learning.item_supply.generation import generate_candidate
    from tests.learning.test_item_supply_generation import SyntheticAuthority
    from app.services.learning.item_supply.generation_contracts import ProviderGenerationV2, ProviderReceiptV2
    from app.services.learning.item_supply.provider_adapter import GENERATION_PROMPT_VERSION
    from tests.learning import test_item_supply_shared_admission_facts as fixture
    from tests.learning.test_item_supply_flexible_native_consumers import native_query_fixture

    plan = operator.build_plan("python-kc-binding-v1", admission_policy=admission_policy)
    selected = operator.selected_admission_policy(plan)
    captured = {}
    original_protocol = fixture._static_protocol
    def capture(mp):
        result = original_protocol(mp, policy=selected, wrong=admission_policy == "diagnostic-v3")
        captured["args"] = result[1]
        return result
    monkeypatch.setattr(fixture, "_static_protocol", capture)
    _, _, _, proof, facts, spec, source, authority = native_query_fixture(monkeypatch)
    # This is a recording double, not a real publisher/current-query acceptance.
    # The existing helper builds a V2 proof; align only its mock return metadata.
    proof = proof.model_copy(update={"policy_hash": selected.policy_hash})
    args = captured["args"]
    vp0, vr0, rp0, rr0 = (args[k] for k in ("validation_prepared", "validation_result", "review_prepared", "review_result"))
    lease = args["lease"]
    events = []
    class Connection:
        info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        serial = 0
        @contextmanager
        def transaction(self):
            assert self.info.transaction_status == TransactionStatus.IDLE
            self.serial += 1
            self.info.transaction_status = TransactionStatus.INTRANS
            try:
                yield
            finally:
                self.info.transaction_status = TransactionStatus.IDLE
        def execute(self, sql, params=()):
            assert self.info.transaction_status == TransactionStatus.INTRANS
            assert "current_database" in sql or "clock_timestamp" in sql
            return FakeRows([{"n": operator.DATABASE if "current_database" in sql else datetime.now(timezone.utc)}])
    conn = Connection()
    def observed(name, value=None, callback=None):
        def call(*a, **kw):
            assert conn.info.transaction_status == (TransactionStatus.IDLE if name.startswith("run_") else TransactionStatus.INTRANS)
            events.append((name, conn.serial))
            return callback(*a, **kw) if callback else value
        return call
    def port(module, name):
        cls = getattr(module, name)
        factory = create_autospec(cls)
        instance = factory.return_value
        monkeypatch.setattr(module, name, factory)
        return instance
    gp = port(shared_pipeline, "SharedGenerationPipeline")
    vp = port(shared_validation, "SharedValidationPipeline")
    rp = port(shared_review, "SharedReviewPipeline")
    issuer = port(shared_admission_facts, "SharedAdmissionFactsOwner")
    importer = port(native_import, "NativeLearningItemBankImporter")
    publisher = port(native_publication, "NativeLearningItemPublicationService")
    port(shared_continuation, "SharedCandidateContinuationOwner")
    key = SimpleNamespace(provider="deepseek", model_version="offline")
    runtime = SimpleNamespace(enqueue=lambda **kw: lease.job_id, claim=lambda **kw: lease,
        refresh_lease=lambda value, **kw: lease)
    gp.runtime = vp.runtime = rp.runtime = runtime
    vp.artifacts = SimpleNamespace(context=lambda *a, **kw: {"key": key})
    monkeypatch.setattr(operator, "fresh_profile", lambda *a, **kw: SimpleNamespace(profile_key=key, model_dump=lambda **kw: {}))
    monkeypatch.setattr(operator, "factory_spec", lambda *a, **kw: spec)
    monkeypatch.setattr(operator, "prepare_campaign", lambda *a, **kw: {"roots": {"knowledge_check": {"root_id": str(facts.root_id)}}})
    monkeypatch.setattr(operator, "review_ports", lambda *a, **kw: (SimpleNamespace(provider_identity=SimpleNamespace(model="offline")), ()))
    gp.prepare_generation.side_effect = observed("prepare_generation", callback=lambda **kw:
        PreparedSharedGeneration(kw["lease"], kw["request"], uuid4(), (), 1, ("deepseek", "offline"),
            kw["evidence_policy"].policy_hash))
    class OfflineAuthor:
        request_attempt_bound = 1
        def generate(self, *, messages, limits, timeout_seconds):
            assert (limits.max_input_bytes, limits.max_output_tokens, limits.max_output_bytes) == (131072, 8192, 65536)
            assert 0 < timeout_seconds <= 100
            return ProviderGenerationV2(payload=source.model_dump(mode="json"), receipt=ProviderReceiptV2(
                provider="synthetic", provider_version="fixture.v2", configured_model="offline", model="offline",
                prompt_version=GENERATION_PROMPT_VERSION, run_id=uuid4(), request_attempt_bound=1, actual_requests=1,
                usage={"state": "unknown"}, mode="synthetic"))
    gp.run_generation.side_effect = observed("run_generation", callback=lambda prepared, provider:
        generate_candidate(prepared.request, provider=OfflineAuthor(), source_authority=SyntheticAuthority(), enabled=True))
    gp.settle_generation.side_effect = observed("settle_generation")
    gp.commit_generation.side_effect = observed("commit_generation", SharedPipelineStageResult("staged", "candidate_staged", facts.generation_artifact_id))
    vp.prepare_validation.side_effect = observed("prepare_validation", vp0)
    vp.run_validation.side_effect = observed("run_validation", vr0)
    vp.settle_validation.side_effect = observed("settle_validation")
    vp._result_payload.side_effect = lambda result: {"safe_reason": result.safe_reason}
    vp.commit_validation.side_effect = observed("commit_validation", SharedValidationStageResult("machine_verified", "validation_staged", facts.validation_receipt_id))
    rp.prepare_review.side_effect = observed("prepare_review", rp0)
    rp.run_review.side_effect = observed("run_review", rr0)
    rp.settle_review.side_effect = observed("settle_review")
    rp.commit_review.side_effect = observed("commit_review", SharedReviewStageResult("peer_review_staged", facts.blind_receipt_id, facts.review_receipt_id))
    issuer.issue.side_effect = observed("issue", facts)
    imported = LearningItemImportResult(str(facts.item_id), str(facts.version_id), proof.item_handle, source.content_hash,
        str(proof.bank_validation_id), str(uuid4()), str(uuid4()), "machine_verified", 1, False)
    importer.import_candidate.side_effect = observed("import_candidate", imported)
    publisher.publish_internal.side_effect = observed("publish_internal", proof)
    result = operator.execute_slot(conn, settings=None, authority=authority, materials=rp0.request.materials,
        provider=SimpleNamespace(provider_key="deepseek", configured_model="offline"), plan=plan,
        path=tmp_path, slot_name="assessment-2", locks=None)
    assert result.lease == lease and result.result["status"] == "published_internal_not_ready_pack"
    passed_policy = gp.prepare_generation.call_args.kwargs["evidence_policy"]
    assert type(passed_policy) is type(selected) and passed_policy == selected
    assert rr0.blind.score.passed is (admission_policy == "strict-v2")
    assert rr0.bundle.policy_version == facts.evaluation.policy_version == selected.policy_version
    if admission_policy == "diagnostic-v3":
        assert result.result["diagnostic_warnings"] == ["blind_solution_incorrect"]
        assert result.result["admission_policy"] == plan["admission_policy"]
    else:
        assert "admission_policy" not in result.result and "diagnostic_warnings" not in result.result
    assert gp.settle_generation.call_args.args[1].state == "staged"
    assert issuer.issue.call_args.kwargs["validation_prepared"] is vp0
    assert issuer.issue.call_args.kwargs["validation_result"] is vr0
    assert issuer.issue.call_args.kwargs["review_prepared"] is rp0
    assert issuer.issue.call_args.kwargs["review_result"] is rr0
    assert publisher.publish_internal.call_args.kwargs["facts_receipt"] is facts
    for stage in ("generation", "validation", "review"):
        names = [name for name, _ in events]
        assert names.index("prepare_" + stage) < names.index("run_" + stage) < names.index("settle_" + stage) < names.index("commit_" + stage)
        assert dict(events)["settle_" + stage] != dict(events)["commit_" + stage]
    anchor = operator.read(tmp_path / "slots/assessment-2/relation-anchor-lease-data.json")
    assert anchor["relation_anchor_eligible"] and anchor["relation_calls_reserved"] == 4
    assert anchor["lease_data"] == lease.model_dump(mode="json") and anchor["original_expiry_unchanged"]


@pytest.mark.parametrize("target,golden", [
    ("python-kc-binding-v1", "c2ba61686a6832af121d9c1948f316412665707120932c3ac721f394f273d3fd"),
    ("python-state-update-v1", "1e858ae069ea9811ec447028ae8821ee2dd2b1ce8c0a11b3c1ac2f67b1e5cdc4"),
    ("sqlite-predicate-order-v1", "7d25ad499e2caff2c663285d7d5d4d4e9f302e3e82f7ec86a1ac487586164852"),
])
def test_legacy_plan_golden_and_diagnostic_selection_changes_only_new_metadata(operator, target, golden):
    legacy = operator.build_plan(target)
    assert "admission_policy" not in legacy and operator.digest(legacy) == golden
    assert operator.build_plan(target, admission_policy="strict-v2") == legacy
    diagnostic = operator.build_plan(target, admission_policy="diagnostic-v3")
    policy = operator.selected_admission_policy(diagnostic)
    assert policy.policy_hash == "97ff7042036eaa1bad8ca13ace439edc8eb1bdca9cd31f110751097cc199fae3"
    assert operator.digest(diagnostic) != golden
    assert {k:v for k,v in diagnostic.items() if k != "admission_policy"} == legacy
    assert policy.publication_enabled is False


@pytest.mark.parametrize("bad", [True, "autonomous_evidence_policy_v3", "diagnostic", None])
def test_policy_selection_never_falls_back_from_invalid_cli_or_boolean(operator, bad):
    with pytest.raises(operator.OperatorPending, match="PLAN_ADMISSION_POLICY_INVALID"):
        operator.build_plan("python-kc-binding-v1", admission_policy=bad)


@pytest.mark.parametrize("field,value", [
    ("mode", "strict-v2"), ("policy_version", "autonomous_evidence_policy_v2"),
    ("policy_hash", "7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab"),
])
def test_mixed_policy_plan_denied_before_imported_execution_io(operator, tmp_path, field, value):
    plan = operator.build_plan("python-kc-binding-v1", admission_policy="diagnostic-v3")
    plan["admission_policy"][field] = value
    with pytest.raises(operator.OperatorPending, match="PLAN_ADMISSION_POLICY_INVALID"):
        operator.execute_slot(object(), settings=None, authority=None, materials=None, provider=None,
            plan=plan, path=tmp_path, slot_name="practice-1", locks=None)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("original,new", [("strict-v2", "diagnostic-v3"), ("diagnostic-v3", "strict-v2")])
def test_existing_campaign_or_failed_slot_cannot_relabel_policy(operator, tmp_path, original, new):
    legacy = operator.build_plan("python-kc-binding-v1", admission_policy=original)
    changed = operator.build_plan("python-kc-binding-v1", admission_policy=new)
    operator.save_exact(tmp_path / "campaign-plan.json", legacy)
    operator.campaign_cases(tmp_path, legacy)
    failure = tmp_path / "slots/practice-1/review.json"
    operator.save(failure, dict(safe_reason="blind_solution_rejected", usage_state="unknown", monetary_cost=None))
    before = {p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(operator.OperatorPending, match="IMMUTABLE_CAMPAIGN_POLICY_PLAN_CONFLICT"):
        operator.execute_slot(object(), settings=None, authority=None, materials=None, provider=None,
            plan=changed, path=tmp_path, slot_name="practice-1", locks=None)
    with pytest.raises(operator.OperatorPending, match="IMMUTABLE_CAMPAIGN_CASES_CONFLICT"):
        operator.campaign_cases(tmp_path, changed)
    assert before == {p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
