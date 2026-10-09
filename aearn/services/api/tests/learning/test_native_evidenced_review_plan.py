"""Fresh native entry freezes new review, never upgrades old campaigns or budgets."""
import copy
import json
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.learning.item_supply.review_protocol import configured_review_protocol, evidenced_protocol_marker
from tests.learning.test_native_v3_operator_plan import operator as operator


@pytest.mark.parametrize("target", ["python-kc-binding-v1", "python-state-update-v1", "sqlite-predicate-order-v1"])
def test_fresh_marker_preserves_old_plan_and_full_frozen_caps(operator, target, tmp_path):
    from native_v3_chain_support_20261006 import selected_review_protocol, save_exact
    old = operator.build_plan(target, admission_policy="diagnostic-v3")
    new = operator.build_plan(target, admission_policy="diagnostic-v3", review_protocol="evidenced-v1")
    assert "review_protocol" not in old and selected_review_protocol(old) == "legacy-v2"
    assert new["review_protocol"] == evidenced_protocol_marker()
    stripped = dict(new)
    del stripped["review_protocol"]
    assert stripped == old and selected_review_protocol(new) == "evidenced-v1"
    assert new["global_caps"] == old["global_caps"] and new["root_caps"] == old["root_caps"]
    assert new["max_HTTP_attempts"] == 44 and new["max_http_attempts_each"] == 1
    path = tmp_path / "campaign-plan.json"
    save_exact(path, old)
    with pytest.raises(operator.OperatorPending):
        save_exact(path, new)
    assert json.loads(path.read_text()) == old
    changed = copy.deepcopy(new)
    changed["review_protocol"]["reasoning_effort"] = "max"
    with pytest.raises(operator.OperatorPending, match="PLAN_REVIEW_PROTOCOL_INVALID"):
        selected_review_protocol(changed)


def test_actual_native_ports_use_explicit_plan_selection_and_inert_entry(operator, monkeypatch, capsys):
    from native_v3_chain_support_20261006 import selected_review_protocol
    from tests.learning.test_item_supply_generation import make_request
    request, _ = make_request()
    settings = Settings(llm_type="deepseek", deepseek_api_key="offline-not-secret",
        deepseek_base_url="https://invalid.example", deepseek_model="deepseek-flash")
    fresh = operator.build_plan("python-kc-binding-v1", review_protocol="evidenced-v1")
    solver, reviewers = operator.review_ports(settings, SimpleNamespace(profile=request.profile),
        review_protocol=selected_review_protocol(fresh))
    assert configured_review_protocol(reviewers) == "evidenced-v1"
    assert solver.request_attempt_bound == 1 and all(r.request_attempt_bound == 1 for r in reviewers)
    assert all(r._max_output_tokens == 2048 for r in reviewers)
    _, old = operator.review_ports(settings, SimpleNamespace(profile=request.profile))
    assert configured_review_protocol(old) == "legacy-v2"
    def forbidden(*args, **kwargs):
        pytest.fail("inert evidenced plan attempted real IO")
    monkeypatch.setattr(operator, "source_helper", forbidden)
    monkeypatch.setattr(operator, "execute_slot", forbidden)
    assert operator.main(["--admission-policy", "diagnostic-v3"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["database_io"] is False and result["provider_calls"] == 0
    assert result["plan"]["review_protocol"]["reasoning_effort"] == "high"
    assert operator.main(["--review-protocol", "legacy-v2"]) == 0
    legacy = json.loads(capsys.readouterr().out)
    assert "review_protocol" not in legacy["plan"]
    assert selected_review_protocol(legacy["plan"]) == "legacy-v2"


@pytest.mark.parametrize("entry", ["execute_slot", "prepare_campaign"])
@pytest.mark.parametrize("case", ["tampered_marker", "old_campaign_mismatch"])
def test_imported_native_seams_reject_protocol_mismatch_before_io(operator, tmp_path, entry, case):
    class NoIO:
        def __getattr__(self, name):
            pytest.fail(f"protocol mismatch reached IO: {name}")

    old = operator.build_plan("python-kc-binding-v1")
    plan = operator.build_plan("python-kc-binding-v1", review_protocol="evidenced-v1")
    if case == "tampered_marker":
        plan["review_protocol"]["reasoning_effort"] = "max"
        reason = "PLAN_REVIEW_PROTOCOL_INVALID"
    else:
        operator.save_exact(tmp_path / "campaign-plan.json", old)
        reason = "IMMUTABLE_CAMPAIGN_POLICY_PLAN_CONFLICT"
    with pytest.raises(operator.OperatorPending, match=reason):
        if entry == "execute_slot":
            operator.execute_slot(NoIO(), settings=None, authority=NoIO(), materials=(),
                provider=NoIO(), plan=plan, path=tmp_path, slot_name="practice-1", locks=None)
        else:
            operator.prepare_campaign(NoIO(), path=tmp_path, plan=plan, specs=[], provider=NoIO())
