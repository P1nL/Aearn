"""Offline guard tests: importing this module never contacts C, PG or provider."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

NAME = "aearn_rag260_c_d_test_01"
DSN = "postgresql://unused@127.0.0.1:5432/" + NAME
os.environ["DATABASE_URL"] = DSN
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["LLM_TYPE"] = "disabled"

MODULE = Path(__file__).resolve().parents[1] / "run.py"
spec = importlib.util.spec_from_file_location("rag_d_live", MODULE)
assert spec and spec.loader
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


@pytest.fixture(autouse=True)
def restore_runtime_env():
    before = {name: os.environ.get(name) for name in live.RUNTIME_FIELDS.values()}
    yield
    for name, value in before.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    live.get_settings.cache_clear()


def settings(**updates: object):
    return SimpleNamespace(database_url=DSN, rag_evidence_consumer_enabled=True,
                           llm_provider_type="deepseek", llm_configuration_status="configured", tutor_decision_max_output_tokens=1200,
                           tutor_context_window_capacity_tokens=9392, tutor_context_output_reserve_tokens=1200,
                           **updates)


def test_default_off_before_database_or_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live.psycopg, "connect", lambda *_a, **_k: pytest.fail("database contacted"))
    with pytest.raises(live.Denied, match="DEFAULT_OFF"):
        live.guard(False, NAME, DSN, settings(), 8)
    args = SimpleNamespace(execute=False)
    with pytest.raises(live.Denied, match="DEFAULT_OFF"):
        live.run(args)


@pytest.mark.parametrize("name", ["postgres", "aearn_rag260_c_live_20260925_01a0d3d4", "aearn_rag260_c_d_../../unsafe"])
def test_disposable_name_exactly_guarded(name: str) -> None:
    with pytest.raises(live.Denied, match="DATABASE_DENIED"):
        live.guard(True, name, DSN, settings(), 8)


def test_mismatched_dsn_and_gate_denied() -> None:
    with pytest.raises(live.Denied, match="DATABASE_DENIED"):
        live.guard(True, NAME, "postgresql://unused@127.0.0.1:5432/postgres", settings(), 8)
    off = SimpleNamespace(database_url=DSN, rag_evidence_consumer_enabled=False,
                          llm_provider_type="deepseek", tutor_decision_max_output_tokens=1200)
    with pytest.raises(live.Denied, match="GATE_CLOSED"):
        live.guard(True, NAME, DSN, off, 8)


@pytest.mark.parametrize("cap", [0, 9])
def test_http_bound_denied(cap: int) -> None:
    with pytest.raises(live.Denied, match="MODEL_BOUND_DENIED"):
        live.guard(True, NAME, DSN, settings(), cap)


def test_transport_counts_before_call_and_never_retries() -> None:
    class FailedClient:
        model = "configured-model"
        def complete_json(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("network unknown")
    counted = live.CountedClient(FailedClient(), 1)
    with pytest.raises(RuntimeError):
        counted.complete_json([])
    assert counted.count == 1 and counted.usage == [None]
    with pytest.raises(live.Denied, match="MODEL_HTTP_CAP"):
        counted.complete_json([])
    assert counted.count == 1


def test_parent_successor_window_preserves_historical_parent_cap() -> None:
    proof = live.parent_successor_http_window(
        {
            "prior_http_attempts": 25,
            "model_http_attempts": 3,
            "phase_http_cap": 4,
            "cumulative_http_cap": 29,
        },
        successor_prior_http_attempts=28,
        successor_phase_http_cap=6,
        successor_cumulative_http_cap=34,
    )
    assert proof == {
        "parent_prior_http_attempts": 25,
        "parent_phase_http_cap": 4,
        "parent_cumulative_http_cap": 29,
        "successor_prior_http_attempts": 28,
        "successor_phase_http_cap": 6,
        "successor_cumulative_http_cap": 34,
    }


def test_parent_successor_window_rejects_corrupt_parent_budget() -> None:
    with pytest.raises(live.Denied, match="PARENT_TRANSPORT_PROOF_MISSING"):
        live.parent_successor_http_window(
            {
                "prior_http_attempts": 25,
                "model_http_attempts": 3,
                "phase_http_cap": "4",
                "cumulative_http_cap": 29,
            },
            successor_prior_http_attempts=28,
            successor_phase_http_cap=6,
            successor_cumulative_http_cap=34,
        )


def test_parent_successor_window_rejects_ledger_reset_and_small_new_window() -> None:
    audit = {
        "prior_http_attempts": 25,
        "model_http_attempts": 3,
        "phase_http_cap": 4,
        "cumulative_http_cap": 29,
    }
    with pytest.raises(live.Denied, match="PARENT_LEDGER_MISMATCH"):
        live.parent_successor_http_window(
            audit,
            successor_prior_http_attempts=25,
            successor_phase_http_cap=6,
            successor_cumulative_http_cap=34,
        )
    with pytest.raises(live.Denied, match="CUMULATIVE_MODEL_BOUND_DENIED"):
        live.parent_successor_http_window(
            audit,
            successor_prior_http_attempts=28,
            successor_phase_http_cap=6,
            successor_cumulative_http_cap=33,
        )


def test_sql_policy_refuses_unrelated_plan_node() -> None:
    scope = SimpleNamespace(draft_id="draft", draft_version=1)
    with pytest.raises(live.Denied, match="PARENT_NODE_SCOPE_DENIED"):
        live.SqlRequirements("route.sql", "sqlite-docs-v1").resolve(scope, {"language_id": "sql"}, {"unrelated": {}})


def test_transport_audits_provider_usage_without_content() -> None:
    from app.services.llm.contracts import LLMUsage
    class RealShapeClient:
        model = "configured-model"
        def complete_json(self, *_args: object, **_kwargs: object):
            return SimpleNamespace(usage=LLMUsage(input_tokens=7, output_tokens=3), content={"private": "never logged"})
    counted = live.CountedClient(RealShapeClient(), 1)
    counted.complete_json([])
    assert counted.usage == [{"input_tokens": 7, "output_tokens": 3}]
    assert "private" not in str(counted.usage)


def test_shared_http_budget_counts_drafting_review_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request
    sent = []
    original = urllib.request.urlopen
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, **kwargs: sent.append(request))
    budget = live.SharedHttpBudget(SimpleNamespace(llm_base_url="https://example.invalid/v1"), 2)
    request = urllib.request.Request("https://example.invalid/v1/chat/completions", data=b"{}", method="POST")
    with budget.enforce():
        urllib.request.urlopen(request, timeout=1)  # drafting
        urllib.request.urlopen(request, timeout=1)  # semantic review (or retry)
        with pytest.raises(live.Denied, match="MODEL_HTTP_CAP"):
            urllib.request.urlopen(request, timeout=1)
    assert budget.count == len(sent) == 2
    assert urllib.request.urlopen is not original  # restored to the test's stub


def test_shared_http_budget_denies_source_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda request: pytest.fail("network contacted"))
    budget = live.SharedHttpBudget(SimpleNamespace(llm_base_url="https://example.invalid/v1"), 8)
    request = urllib.request.Request("https://www.sqlite.org/lang_select.html", method="GET")
    with budget.enforce(), pytest.raises(live.Denied, match="UNEXPECTED_NETWORK"):
        urllib.request.urlopen(request)
    assert budget.count == 0


def test_prepare_entry_is_default_off_without_api_or_database() -> None:
    import subprocess
    import sys
    result = subprocess.run([sys.executable, str(MODULE.with_name("prepare.py")),
                             "--control-config", "/missing-root-control.json"],
                            capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 2
    assert '"code": "DEFAULT_OFF"' in result.stderr
    assert "Traceback" not in result.stderr


def test_explicit_boundary_profile_constructs_without_product_default_change() -> None:
    from app.core.config import Settings
    config = Settings(
        llm_type="deepseek", deepseek_api_key="not-a-real-key",
        deepseek_base_url="https://example.invalid/v1", deepseek_model="deepseek-flash",
        tutor_deepseek_v4_flash_context_window_tokens=12288,
        tutor_deepseek_v4_flash_input_limit_tokens=8192,
        tutor_deepseek_v4_flash_max_output_tokens=4096,
        tutor_deepseek_v4_flash_decision_max_output_tokens=4096,
        tutor_deepseek_v4_flash_max_dynamic_target_tokens=512,
    )
    assert config.tutor_decision_max_output_tokens == 4096
    assert config.tutor_context_window_capacity_tokens - config.tutor_context_output_reserve_tokens == 8192
    live.guard(True, NAME, DSN, config.model_copy(update={"database_url": DSN,
               "rag_evidence_consumer_enabled": True}), 8, 4096, 8192, 240)


def test_sql_requirements_follow_validated_operator_version() -> None:
    scope = SimpleNamespace(draft_id="00000000-0000-0000-0000-000000000001", draft_version=1)
    node = {"knowledge_key": "sql.queries", "title": "SQL WHERE / LIMIT",
            "description": "Query filtering and limits", "is_core": True,
            "prerequisite_keys": [], "required_capabilities": ["sql"],
            "catalog_knowledge_key": None}
    result = live.SqlRequirements("route.sql", "sqlite-docs-v1").resolve(
        scope, {"language_id": "sql"}, {"sql.queries": node})
    assert len(result) == 2
    assert {x.demand.scope.subject_version for x in result} == {"sqlite-docs-v1"}
    assert {x.demand.purpose for x in result} == {"main_teaching", "supplementary_explanation"}


def test_per_instance_retry_bound_does_not_mutate_global_default() -> None:
    from app.core.config import Settings
    from app.services.llm.llm_client import OpenAICompatibleClient, LLM_PROVIDER_RETRY_ATTEMPTS
    config = Settings(llm_type="deepseek", deepseek_api_key="not-a-real-key",
                      deepseek_base_url="https://example.invalid/v1", deepseek_model="deepseek-flash")
    before = LLM_PROVIDER_RETRY_ATTEMPTS
    client = OpenAICompatibleClient(config, max_http_attempts=1)
    assert client._max_http_attempts == 1
    from app.services.llm import llm_client
    assert llm_client.LLM_PROVIDER_RETRY_ATTEMPTS == before


def formal_snapshot(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    from app.core.config import Settings
    monkeypatch.setenv("LLM_TYPE", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-not-a-real-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    config = Settings(
        tutor_deepseek_v4_flash_context_window_tokens=1_000_000,
        tutor_deepseek_v4_flash_input_limit_tokens=131_072,
        tutor_deepseek_v4_flash_max_output_tokens=61_440,
        tutor_deepseek_v4_flash_decision_max_output_tokens=16_384,
        tutor_deepseek_v4_flash_max_dynamic_target_tokens=130_688,
        tutor_deepseek_repair_thinking_disabled=True,
    )
    return live.runtime_profile(config)


def test_formal_profile_exports_only_allowlisted_nonsecret_effective_policy(monkeypatch):
    data = formal_snapshot(monkeypatch)
    assert set(data) == {"format", "provider_type", "model", "fields", "effective"}
    assert set(data["fields"]) == set(live.RUNTIME_FIELDS)
    assert data["effective"] == {
        "tutor_context_window_capacity_tokens": 192_512,
        "tutor_context_output_reserve_tokens": 61_440,
        "tutor_decision_max_output_tokens": 16_384,
        "deepseek_v4_flash_input_hard_limit_tokens": 131_072,
        "tutor_context_max_dynamic_target_capacity_tokens": 130_688,
    }
    assert data["fields"]["tutor_deepseek_repair_thinking_disabled"] is True
    for forbidden in ("offline-not-a-real-key", "DATABASE_URL", "api_key", "goal_text", "password"):
        assert forbidden not in str(data)
    monkeypatch.setattr(live, "_absolute", Path)
    monkeypatch.setattr(live, "_root_json", lambda _: (data, None))
    config = live.install_runtime_profile("/private/profile.json")
    assert live.runtime_profile(config) == data
    live.guard(True, NAME, DSN, config.model_copy(update={"database_url": DSN,
               "rag_evidence_consumer_enabled": True}), 4)


def test_profile_rejects_secrets_unknown_keys_and_silent_boundary(monkeypatch):
    data = formal_snapshot(monkeypatch)
    monkeypatch.setattr(live, "_absolute", Path)
    monkeypatch.setattr(live, "_root_json", lambda _: (data, None))
    with pytest.raises(live.Denied, match="BOUNDARY_PROFILE_REQUIRED"):
        live.install_runtime_profile("/private/profile.json", output_tokens=4096, input_tokens=8192)
    data["fields"]["deepseek_api_key"] = "secret"
    with pytest.raises(live.Denied, match="RUNTIME_PROFILE_DENIED"):
        live.install_runtime_profile("/private/profile.json")
    data["fields"].pop("deepseek_api_key")
    data["effective"]["tutor_context_window_capacity_tokens"] = 1_000_000
    with pytest.raises(live.Denied, match="RUNTIME_PROFILE_MISMATCH"):
        live.install_runtime_profile("/private/profile.json")


def test_explicit_boundary_profile_is_audited_without_forced_thinking(monkeypatch):
    data = formal_snapshot(monkeypatch)
    monkeypatch.setattr(live, "_absolute", Path)
    monkeypatch.setattr(live, "_root_json", lambda _: (data, None))
    config = live.install_runtime_profile("/private/profile.json", profile="boundary-test",
                                           output_tokens=4096, input_tokens=8192,
                                           dynamic_target_tokens=2048)
    actual = live.runtime_profile(config)
    assert actual["effective"]["tutor_decision_max_output_tokens"] == 4096
    assert actual["effective"]["deepseek_v4_flash_input_hard_limit_tokens"] == 8192
    assert actual["effective"]["tutor_context_max_dynamic_target_capacity_tokens"] == 2048
    assert actual["fields"]["tutor_deepseek_repair_thinking_disabled"] is True
    assert actual != data
