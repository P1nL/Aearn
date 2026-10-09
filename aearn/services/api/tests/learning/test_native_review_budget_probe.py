"""Frozen single-slot accounting only; no real source, provider, DB or runner IO."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from tests.learning.test_native_v3_operator_plan import operator as operator


def probe_plan(operator, **kwargs):
    return operator.build_plan("python-kc-binding-v1", 21, admission_policy="diagnostic-v3",
        review_protocol="evidenced-v1", probe_slot="practice-2", **kwargs)


@pytest.mark.parametrize("target", ["python-kc-binding-v1", "python-state-update-v1", "sqlite-predicate-order-v1"])
def test_probe_is_one_real_frozen_row_and_one_purpose_without_relations(operator, target):
    from native_v3_chain_support_20261006 import required_remaining, remaining_time_plan, validate_plan

    full = operator.build_plan(target, 21, review_protocol="evidenced-v1")
    probe = operator.build_plan(target, 21, review_protocol="evidenced-v1", probe_slot="practice-2")
    assert probe["slots"] == [full["slots"][1]]
    assert probe["recommended_execution_order"] == ["practice-2"]
    assert probe["max_HTTP_attempts"] == probe["operator_HTTP_attempts"] == 8
    assert probe["reserved_relation_calls"] == 0 and probe["relation_anchor_purpose"] is None
    assert probe["execution_scope"]["pack_ready"] is False
    assert probe["execution_scope"]["relation_anchor_eligible"] is False
    assert not probe["course_inventory_ready"] and not probe["public_release"]
    validate_plan(probe, slot_name="practice-2")
    totals, roots = required_remaining(probe, set())
    assert totals == probe["global_caps"] and roots == probe["root_caps"]
    assert totals["requests"] == 8 and len(roots) == 1
    assert totals["input_tokens"] == 131072 + 7 * 262144
    assert totals["output_tokens"] == 8192 + 7 * 2048
    assert sum(row["tokens"] for row in roots.values()) == totals["input_tokens"] + totals["output_tokens"]
    wall, root_wall = remaining_time_plan(probe, set())
    assert wall == probe["minimum_campaign_seconds"] == 1100 + totals["execution_seconds"]
    assert list(root_wall.values()) == [wall]
    consumed, consumed_roots = required_remaining(probe, {"practice-2"})
    assert consumed["requests"] == consumed["output_tokens"] == 0
    assert all(row == {"requests": 0, "tokens": 0, "resources": 0} for row in consumed_roots.values())
    with pytest.raises(operator.OperatorPending, match="OUTSIDE_SCOPE"):
        required_remaining(probe, {"practice-1"})


def test_probe_cases_freeze_only_selected_identity_and_cannot_upgrade(operator, tmp_path):
    plan = probe_plan(operator)
    cases = operator.campaign_cases(tmp_path, plan)
    assert set(cases["cases"]) == {"practice-2"}
    assert operator.campaign_cases(tmp_path, plan) == cases
    with pytest.raises(operator.OperatorPending, match="IMMUTABLE_CAMPAIGN_CASES_CONFLICT"):
        operator.campaign_cases(tmp_path, operator.build_plan("python-kc-binding-v1", 21,
            admission_policy="diagnostic-v3", review_protocol="evidenced-v1"))
    assert not (tmp_path / "slots").exists()


class NoIO:
    def __getattr__(self, name):
        pytest.fail(f"scope/plan denial reached IO: {name}")


@pytest.mark.parametrize("entry", ["execute_slot", "prepare_campaign"])
@pytest.mark.parametrize("change", ["scope_extra", "scope_partial", "call_cap", "foreign_row", "scope_removed", "extra_plan"])
def test_scope_or_plan_tamper_denied_before_imported_io_and_writes(operator, tmp_path, entry, change):
    plan = probe_plan(operator)
    if change == "scope_extra":
        plan["execution_scope"]["extra"] = True
    elif change == "scope_partial":
        del plan["execution_scope"]["pack_ready"]
    elif change == "call_cap":
        plan["global_caps"]["requests"] = 44
    elif change == "foreign_row":
        plan["slots"].append(copy.deepcopy(plan["slots"][0]))
    elif change == "scope_removed":
        del plan["execution_scope"]
    else:
        plan["caller_budget"] = 100
    with pytest.raises(operator.OperatorPending, match="PLAN_"):
        if entry == "execute_slot":
            operator.execute_slot(NoIO(), settings=NoIO(), authority=NoIO(), materials=(), provider=NoIO(),
                plan=plan, path=tmp_path, slot_name="practice-2", locks=None)
        else:
            operator.prepare_campaign(NoIO(), path=tmp_path, plan=plan, specs=[], provider=NoIO())
    assert list(tmp_path.iterdir()) == []


def test_selected_slot_mismatch_before_any_db_or_checkpoint(operator, tmp_path):
    with pytest.raises(operator.OperatorPending, match="PLAN_SELECTED_SLOT_OUTSIDE_SCOPE"):
        operator.execute_slot(NoIO(), settings=NoIO(), authority=NoIO(), materials=(), provider=NoIO(),
            plan=probe_plan(operator), path=tmp_path, slot_name="practice-1", locks=None)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("freeze", ["plan", "cases", "accounting"])
def test_old_frozen_campaign_cannot_become_probe_before_io(operator, tmp_path, freeze):
    old = operator.build_plan("python-kc-binding-v1", 21, admission_policy="diagnostic-v3", review_protocol="evidenced-v1")
    if freeze == "plan":
        operator.save_exact(tmp_path / "campaign-plan.json", old)
    elif freeze == "cases":
        operator.campaign_cases(tmp_path, old)
    else:
        operator.save_exact(tmp_path / "resource-window.json", {"plan_hash": operator.digest(old)})
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(operator.OperatorPending, match="IMMUTABLE_CAMPAIGN"):
        operator.prepare_campaign(NoIO(), path=tmp_path, plan=probe_plan(operator), specs=[], provider=NoIO())
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_probe_plan_cli_zero_io_and_requires_explicit_slot(operator, monkeypatch, capsys):
    import dotenv
    import psycopg

    def forbidden(*args, **kwargs):
        pytest.fail("offline probe plan reached IO")
    for name in ("source_helper", "settings_for_execute", "execute_slot", "save", "save_exact", "campaign_cases"):
        monkeypatch.setattr(operator, name, forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(dotenv, "dotenv_values", forbidden)
    assert operator.main(["--plan", "--probe-only", "--slot", "practice-2",
        "--peer-review-max-output-tokens", "61440"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["database_io"] is False and result["provider_calls"] == 0
    assert len(result["plan"]["slots"]) == 1 and result["plan"]["max_HTTP_attempts"] == 8
    assert result["plan"]["global_caps"]["output_tokens"] == 378880
    with pytest.raises(SystemExit):
        operator.main(["--plan", "--probe-only"])


def test_probe_prepare_rejects_extra_specs_before_budget_owner(operator, tmp_path):
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for
    plan = probe_plan(operator)
    spec = operator.factory_spec(plan["slots"][0], plan, materials_for(plan["target"]), "pure.probe.scope", None)
    with pytest.raises(operator.OperatorPending, match="PLAN_SPEC_SCOPE_MISMATCH"):
        operator.prepare_campaign(NoIO(), path=tmp_path, plan=plan, specs=[spec, spec],
            provider=SimpleNamespace(provider_key="deepseek", configured_model="offline"))


def test_production_peer_cap_wire_and_full_probe_resource_math(operator):
    from app.core.config import DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS, Settings
    from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
    from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
    from app.services.learning.item_supply.review_provider import review_resource_plan
    from native_v3_chain_support_20261006 import required_remaining, selected_peer_output_cap
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for
    from tests.learning.test_item_supply_flexible_spec import proposed_source
    from tests.learning.test_item_supply_generation import make_request
    from tests.learning.test_item_supply_v2_execution_review import binding_for

    cap = DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
    settings = Settings(_env_file=None, llm_type="deepseek", deepseek_api_key="offline-only",
        deepseek_base_url="https://invalid.example", deepseek_model="deepseek-flash")
    assert cap == settings.tutor_max_output_tokens == 61440
    plan = probe_plan(operator, peer_review_max_output_tokens=cap)
    assert selected_peer_output_cap(plan) == cap
    totals, roots = required_remaining(plan, set())
    assert totals["requests"] == 8 and totals["output_tokens"] == 378880
    assert roots["knowledge_check"]["tokens"] == 2344960
    full = operator.build_plan(plan["target"], 21, review_protocol="evidenced-v1", peer_review_max_output_tokens=cap)
    assert full["global_caps"]["output_tokens"] == 5 * 378880 + 4 * 2048
    assert full["root_caps"]["knowledge_check"]["tokens"] == 4 * 2344960 + 4 * (262144 + 2048)
    continued, _ = required_remaining(plan, {"practice-2"}, review_pending={"practice-2"})
    assert continued["requests"] == 7 and continued["output_tokens"] == 2048 + 6 * cap
    base, _ = make_request()
    solver, reviewers = operator.review_ports(settings, SimpleNamespace(profile=base.profile),
        review_protocol="evidenced-v1", peer_review_max_output_tokens=selected_peer_output_cap(plan))
    assert solver._max_output_tokens == 2048
    assert len(reviewers) == 6 and all(r._max_output_tokens == cap for r in reviewers)
    assert all(r.request_attempt_bound == 1 and r._timeout_seconds == 100 for r in (solver, *reviewers))
    materials = materials_for(plan["target"])
    spec = operator.factory_spec(plan["slots"][0], plan, materials, "pure.production.output", None)
    source = proposed_source(spec)
    inputs = prepare_finite_candidate_validation(source, spec=spec, materials=materials)
    binding = binding_for(source).model_copy(update={"profile_hash": base.profile.profile_hash})
    with finite_review_context(source, spec=spec, materials=materials):
        resources = review_resource_plan(source, binding=binding, validation_receipt=inputs.static_facts.validation,
            solver=solver, reviewers=reviewers)
    assert resources.requests == 7 and resources.output_tokens == 370688
    assert resources.output_tokens + 8192 == totals["output_tokens"]


def test_cap_markers_and_nonproduction_options_reject_before_imported_io(operator, tmp_path):
    from native_v3_chain_support_20261006 import production_peer_output_cap
    cap = production_peer_output_cap()
    for invalid in (8192, 16384, True):
        with pytest.raises(operator.OperatorPending, match="PLAN_PEER_OUTPUT_BUDGET_INVALID"):
            probe_plan(operator, peer_review_max_output_tokens=invalid)
        with pytest.raises(operator.OperatorPending, match="PLAN_PEER_OUTPUT_BUDGET_INVALID"):
            operator.review_ports(NoIO(), NoIO(), review_protocol="evidenced-v1", peer_review_max_output_tokens=invalid)
    for change in ("extra", "partial", "blind", "mixed", "removed"):
        plan = probe_plan(operator, peer_review_max_output_tokens=cap)
        if change == "extra":
            plan["peer_review_output_budget"]["caller_cap"] = cap
        elif change == "partial":
            del plan["peer_review_output_budget"]["limit_source"]
        elif change == "blind":
            plan["peer_review_output_budget"]["blind_max_output_tokens"] = cap
        elif change == "mixed":
            del plan["review_protocol"]
        else:
            del plan["peer_review_output_budget"]
        for entry in ("execute", "prepare"):
            with pytest.raises(operator.OperatorPending, match="PLAN_"):
                if entry == "execute":
                    operator.execute_slot(NoIO(), settings=NoIO(), authority=NoIO(), materials=(), provider=NoIO(),
                        plan=plan, path=tmp_path, slot_name="practice-2", locks=None)
                else:
                    operator.prepare_campaign(NoIO(), path=tmp_path, plan=plan, specs=[], provider=NoIO())
    assert list(tmp_path.iterdir()) == []


def test_actual_original_global_output_headroom_denies_entire_production_probe(operator, monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    import app.services.learning.item_supply.budget as budget_module
    from native_v3_chain_support_20261006 import production_peer_output_cap
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for
    from tests.learning.test_native_v3_operator_plan import BudgetPreflightConnection

    plan = probe_plan(operator, peer_review_max_output_tokens=production_peer_output_cap())
    spec = operator.factory_spec(plan["slots"][0], plan, materials_for(plan["target"]), "pure.pending.production", None)
    old = operator.build_plan(plan["target"])
    now = datetime.now(timezone.utc)
    rows = [dict(id=uuid4(), dimension_kind=dim, dimension_key=key, resource_kind=kind,
        window_start=now - timedelta(minutes=5), window_end=now + timedelta(minutes=60), cap_amount=max(1, amount))
        for dim, key in (("system", "item-supply"), ("window", "item-supply"), ("pool", "base"), ("provider", "deepseek"))
        for kind, amount in old["global_caps"].items()]
    seen = []
    class OriginalBudget:
        def __init__(self, conn):
            pass
        def _global_used(self, identity, kind):
            seen.append(kind)
            return 16482 if kind == "output_tokens" else 8 if kind == "requests" else 0
        def register_global_limit(self, **kwargs):
            pytest.fail("never replace or raise original limits")
    monkeypatch.setattr(budget_module, "ItemSupplyBudgetRepository", OriginalBudget)
    for state in ("output_shortfall", "partial", "absent"):
        selected = rows if state == "output_shortfall" else rows[:-1] if state == "partial" else []
        conn = BudgetPreflightConnection(selected)
        with pytest.raises(operator.OperatorPending, match={"output_shortfall": "EXISTING_GLOBAL_REMAINING",
                "partial": "EXISTING_PARTIAL_GLOBAL", "absent": "PROBE_ORIGINAL_GLOBAL_LIMITS"}[state]):
            operator.prepare_campaign(conn, path=tmp_path, plan=plan, specs=[spec],
                provider=SimpleNamespace(provider_key="deepseek", configured_model="deepseek-flash"))
        assert not any(sql.startswith(("INSERT", "UPDATE", "DELETE")) for sql in conn.statements)
    assert "output_tokens" in seen and old["global_caps"]["output_tokens"] - 16482 == 104350
    assert list(tmp_path.iterdir()) == []


def test_production_cap_config_drift_denied_before_author_database_io(operator, tmp_path):
    from app.core.config import Settings
    from native_v3_chain_support_20261006 import production_peer_output_cap
    settings = Settings(_env_file=None, llm_type="deepseek", deepseek_api_key="offline-only",
        deepseek_base_url="https://invalid.example", deepseek_model="deepseek-flash",
        tutor_deepseek_v4_flash_max_output_tokens=production_peer_output_cap() - 1)
    with pytest.raises(operator.OperatorPending, match="PRODUCTION_PEER_OUTPUT_SETTING_MISMATCH"):
        operator.execute_slot(NoIO(), settings=settings, authority=NoIO(), materials=(), provider=NoIO(),
            plan=probe_plan(operator, peer_review_max_output_tokens=production_peer_output_cap()),
            path=tmp_path, slot_name="practice-2", locks=None)
    assert list(tmp_path.iterdir()) == []


def test_executable_probe_requires_original_root_execution_headroom(operator, monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    import app.services.learning.item_supply.budget as budget_module
    import app.services.learning.item_supply.repository as runtime_module
    import app.services.learning.item_supply.storage as storage_module
    from tests.learning.test_item_supply_finite_candidate_factory import materials_for
    from tests.learning.test_native_v3_operator_plan import BudgetPreflightConnection, FakeRows

    plan = operator.build_plan("python-state-update-v1", 21, review_protocol="evidenced-v1",
        peer_review_max_output_tokens=61440, probe_slot="practice-2")
    locks = {"python-stdout-v1": SimpleNamespace(fingerprint="a" * 64)}
    spec = operator.factory_spec(plan["slots"][0], plan, materials_for(plan["target"]),
        "pure.execution.headroom", locks)
    now = datetime.now(timezone.utc)
    root, window_id = uuid4(), uuid4()
    window = dict(id=window_id, root_id=root, pool_key="base", provider_key="deepseek",
        window_start=now - timedelta(minutes=5), window_end=now + timedelta(hours=3),
        request_cap=8, token_cap=next(iter(plan["root_caps"].values()))["tokens"], resource_cap=900)
    rows = [dict(id=uuid4(), dimension_kind=dim, dimension_key=key, resource_kind=kind,
        window_start=window["window_start"], window_end=window["window_end"], cap_amount=max(1, cap) + 10)
        for dim, key in (("system", "item-supply"), ("window", "item-supply"),
                        ("pool", "base"), ("provider", "deepseek"))
        for kind, cap in plan["global_caps"].items()]

    class Connection(BudgetPreflightConnection):
        def execute(self, sql, params=()):
            assert not sql.startswith(("INSERT", "UPDATE", "DELETE"))
            if "shared_budget_roots" in sql:
                return FakeRows([dict(id=root, blueprint_id=root)])
            if "shared_budget_windows WHERE root_id" in sql:
                return FakeRows([window])
            return super().execute(sql, params)

    class Budget:
        def __init__(self, conn):
            pass
        def _global_used(self, identity, kind):
            return 1 if kind == "execution_seconds" else 0
        def _root_used(self, namespace, identity, window_identity):
            assert namespace == "shared" and identity == root and window_identity == window_id
            return dict(requests=0, input_tokens=0, output_tokens=0, execution_seconds=1)

    class Runtime:
        def __init__(self, conn):
            pass
        def ensure_shared_root(self, **kwargs):
            return root

    class Storage:
        def __init__(self, conn):
            pass
        def register_policy(self, policy):
            pass
        def register_blueprint(self, blueprint):
            return root

    monkeypatch.setattr(budget_module, "ItemSupplyBudgetRepository", Budget)
    monkeypatch.setattr(runtime_module, "ItemSupplyRuntimeRepository", Runtime)
    monkeypatch.setattr(storage_module, "PostgresSharedSupplyStorage", Storage)
    with pytest.raises(operator.OperatorPending, match="EXISTING_ROOT_REMAINING_CAP_INSUFFICIENT_NO_RESET"):
        operator.prepare_campaign(Connection(rows), path=tmp_path, plan=plan, specs=[spec],
            provider=SimpleNamespace(provider_key="deepseek", configured_model="deepseek-flash"))
    assert list(tmp_path.iterdir()) == []
