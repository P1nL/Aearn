"""Focused offline author-prompt checks, no actual provider/runner/authority IO."""
import json
from uuid import uuid4

from app.services.learning.item_bank.contracts import LearningItemSourceV1
from app.services.learning.item_supply.finite_candidate_factory import build_finite_candidate_spec, build_finite_generation_request
from app.services.learning.item_supply.generation import generate_candidate
from app.services.learning.item_supply.sandbox.python_goal_scorer import compile_goal_tests
from tests.learning.test_item_supply_finite_candidate_factory import materials_for
from tests.learning.test_item_supply_generation import SyntheticAuthority, SyntheticProvider, make_request
from tests.learning.test_item_supply_python_completion_template import completion_source


def finite_request_and_source():
    base, _ = make_request()
    materials = materials_for("python-state-update-v1")
    spec = build_finite_candidate_spec(target_id="python-state-update-v1",
        variant_id="python-state-update-v1:practice-1", seed=0,
        item_key="finite-prompt.accumulate", version="v1", materials=materials,
        runtime_profile_hash="a"*64, scorer_version="offline-v1", assistance_policy_hash="b"*64,
        policy_version="offline-v1", difficulty_profile=base.blueprint.difficulty_profile,
        publication_policy=base.blueprint.publication_policy)
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=base.profile,
        limits=base.limits, materials=materials)
    # Test-side authored return payload only, NEVER an input to the author prompt.
    source = LearningItemSourceV1.model_validate(dict(blueprint=spec.blueprint, public=spec.public_template,
        private=dict(item_key=request.item_key, version=request.version, kind="code", content=dict(
            type="code", standard_answer="total = 10\nincrease = 4\ndecrease = 3\ntotal += increase\ntotal -= decrease\nprint(total)",
            tests=[dict(id=kind, case_type=kind, order_index=i, input_json={}, expected_output_json={"stdout": "11\n"})
                   for i, kind in enumerate(("visible", "hidden"))],
            score_policy=dict(kind="all_tests", policy_version="all_tests_v1", threshold=1.0)))))
    return spec, request, source


def prompt_schema(provider):
    return json.loads(provider.messages[0]["content"].split("AUTHORITATIVE OUTPUT JSON SCHEMA:\n", 1)[1])


def test_exact_native_finite_prompt_freezes_public_and_compiles_without_source_mutation():
    spec, request, source = finite_request_and_source()
    original = source.model_dump(mode="json")
    provider = SyntheticProvider(original)
    result = generate_candidate(request, provider=provider, source_authority=SyntheticAuthority(), enabled=True)
    assert result.state == "staged" and result.source == source and provider.calls == 1
    system = provider.messages[0]["content"]
    user = json.loads(provider.messages[1]["content"])
    assert "exact service-owned public state-update semantics" in system
    assert "input_json={} and ordinary all_tests" in system
    assert "without mutating the staged generated source" in system
    assert "Do not hardcode final output" in system
    assert "finite D1 exercise" not in system
    assert prompt_schema(provider)["properties"]["blueprint"]["const"] == request.blueprint.model_dump(mode="json")
    assert prompt_schema(provider)["properties"]["public"]["const"] == request.public_template.model_dump(mode="json")
    assert user["public_template"] == spec.public_template.model_dump(mode="json")
    assert "private" not in user and "standard_answer" not in provider.messages[1]["content"]
    assert "11\n" not in provider.messages[1]["content"]
    compiled = compile_goal_tests(result.source)
    assert all(t["input_json"] == {"goal_contract": spec.python_goal.model_dump(mode="json")} for t in compiled)
    assert result.source.model_dump(mode="json") == original
    assert all(t.input_json == {} for t in result.source.private.content.tests)
    # A factory-looking marker and a copied template cannot authorize edited prose.
    altered = request.model_copy(update={"public_template": request.public_template.model_copy(
        update={"instruction_markdown": request.public_template.instruction_markdown + " Changed goal."})})
    unused = SyntheticProvider(original)
    authority = SyntheticAuthority()
    denied = generate_candidate(altered, provider=unused, source_authority=authority, enabled=True)
    assert denied.safe_reason == "invalid_request" and unused.calls == authority.calls == 0
    contradictory = source.model_dump(mode="json")
    contradictory["private"]["content"]["tests"][0]["input_json"] = {"goal_contract": "python_assignment_sum_print_v1"}
    denied = generate_candidate(request, provider=SyntheticProvider(contradictory),
                                source_authority=SyntheticAuthority(), enabled=True)
    assert denied.safe_reason == "invalid_candidate" and denied.source is None


def test_legacy_sum_completion_prompt_and_staged_bytes_are_unchanged():
    base, _ = make_request()
    source = completion_source(base.blueprint.source_references)
    original = source.model_dump(mode="json")
    request = base.model_copy(update={"blueprint": source.blueprint, "public_template": source.public,
        "item_key": source.public.item_key, "version": source.public.version})
    provider = SyntheticProvider(original)
    result = generate_candidate(request, provider=provider, source_authority=SyntheticAuthority(), enabled=True)
    assert result.state == "staged" and result.source.model_dump(mode="json") == original
    assert "finite D1 exercise" in provider.messages[0]["content"]
    assert "exact public assignment/sum/print structure" in provider.messages[0]["content"]
    assert "public state-update semantics" not in provider.messages[0]["content"]
    assert prompt_schema(provider)["properties"]["public"]["const"] == original["public"]
    assert prompt_schema(provider)["properties"]["blueprint"]["const"] == original["blueprint"]
    assert source.model_dump(mode="json") == original


def test_native_kc_prompt_declares_all_option_protocol_without_answer_key():
    base, _ = make_request()
    materials = materials_for("python-kc-binding-v1")
    spec = build_finite_candidate_spec(target_id="python-kc-binding-v1",
        variant_id="python-kc-binding-v1:practice-1", seed=0,
        item_key="finite-prompt.kc-trace", version="v1", materials=materials,
        runtime_profile_hash=None, scorer_version="static_exact_v1", assistance_policy_hash="b"*64,
        policy_version="offline-v1", difficulty_profile=base.blueprint.difficulty_profile,
        publication_policy=base.blueprint.publication_policy)
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=base.profile,
        limits=base.limits, materials=materials)
    # Empty synthetic response deliberately never supplies a private answer.
    provider = SyntheticProvider({})
    result = generate_candidate(request, provider=provider, source_authority=SyntheticAuthority(), enabled=True)
    assert provider.calls == 1 and result.safe_reason == "invalid_candidate"
    protocol = provider.messages[0]["content"].split("AUTHORITATIVE OUTPUT JSON SCHEMA:", 1)[0]
    assert "exactly four tests" in protocol and "without duplicates or omissions" in protocol
    assert '{"answer": option_id}' in protocol
    assert '{"accepted": a strict JSON boolean}' in protocol
    assert "Exactly one option must be accepted" in protocol
    assert '{"kind":"static_exact","policy_version":"static_exact_v1","threshold":1}' in protocol
    assert "independent semantic validator" in protocol
    assert all(option.option_id not in protocol for option in spec.public_template.content.options)
    assert prompt_schema(provider)["properties"]["public"]["const"] == spec.public_template.model_dump(mode="json")
    assert prompt_schema(provider)["properties"]["blueprint"]["const"] == spec.blueprint.model_dump(mode="json")
    user = json.loads(provider.messages[1]["content"])
    assert "private" not in user and "accepted_answers" not in provider.messages[1]["content"]
    altered = request.model_copy(update={"public_template": request.public_template.model_copy(
        update={"instruction_markdown": "Always select the first option."})})
    unused, authority = SyntheticProvider({}), SyntheticAuthority()
    denied = generate_candidate(altered, provider=unused, source_authority=authority, enabled=True)
    assert denied.safe_reason == "invalid_request" and unused.calls == authority.calls == 0
