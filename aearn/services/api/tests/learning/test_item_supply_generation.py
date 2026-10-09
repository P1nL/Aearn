"""Focused pure generation tests; transport/authority fixtures never access IO."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import Settings
from app.services.learning.item_bank.contracts import (
    LearningItemDifficulty, LearningItemKind, LearningItemPurpose, LearningItemSourceV1,
)
from app.services.learning.item_supply.evidence import material_digest
from app.services.learning.item_supply.generation import generate_candidate
from app.services.learning.item_supply.generation_contracts import (
    GenerationLimitsV2, GenerationRequestV2, ProviderGenerationV2, ProviderReceiptV2,
    ProviderUsageV2, SourceReceiptV2,
)
from app.services.learning.item_supply.parameter_profiles import FrozenProfileSnapshot, ParameterValuesV1
from app.services.learning.item_supply.provider_adapter import (
    GENERATION_PROMPT_VERSION, OpenAICompatibleGenerationProvider, response_usage,
)
from app.services.llm.contracts import LLMUsage
from tests.learning.test_item_supply_evidence import make_material


def make_request() -> tuple[GenerationRequestV2, dict[str, object]]:
    material, _ = make_material()
    source_path = Path(__file__).parents[2] / (
        "app/services/learning/item_bank/sources/curated/python-variables-rebinding-prediction-v1.json"
    )
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    ref = dict(source_id="source.python", source_version="v1", locator="document.python",
               content_hash=material.binding.evidence[0].binding.document_hash)
    payload["blueprint"]["source_references"] = [ref]
    payload["public"]["source_references"] = [ref]
    source = LearningItemSourceV1.model_validate(payload)
    now = datetime.now(timezone.utc)
    values = ParameterValuesV1(
        connection_timeout_ms=50, first_token_timeout_ms=50, stream_idle_timeout_ms=50,
        request_timeout_ms=1_000, stage_deadline_ms=10_000, parent_deadline_ms=20_000,
        discussion_rounds=1, revision_rounds=1, investigation_rounds=1,
    )
    profile = FrozenProfileSnapshot(
        profile_key_hash="1" * 64, profile_version=1, profile_hash="2" * 64, values=values,
        bound_at=now, parent_deadline_at=now + timedelta(seconds=20),
    )
    request = GenerationRequestV2(
        candidate_id=uuid4(), scope_hash="3" * 64, item_key=source.public.item_key,
        version=source.public.version, blueprint=source.blueprint, profile=profile,
        limits=GenerationLimitsV2(max_input_bytes=100_000, max_output_tokens=2_000,
                                  max_output_bytes=100_000), materials=(material,),
    )
    return request, payload


class SyntheticAuthority:
    def __init__(self) -> None:
        self.calls = 0

    def authorize(self, material) -> SourceReceiptV2:
        self.calls += 1
        c = material.binding.evidence[0]
        return SourceReceiptV2(
            material_digest=material_digest(material), binding_digest=material.binding.binding_digest,
            corpus_version_id=UUID(c.corpus_version_id), active_generation=c.active_generation,
            checked_at_iso=datetime.now(timezone.utc).isoformat(),
            claim_receipt_hashes=(c.claim_receipt_hash,), mode="synthetic",
        )

    def assert_current(self, material, expected) -> SourceReceiptV2:
        return self.authorize(material)


class SyntheticProvider:
    request_attempt_bound = 1

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0
        self.messages = ()

    def generate(self, *, messages, limits, timeout_seconds) -> ProviderGenerationV2:
        self.calls += 1
        self.messages = messages
        assert 0 < timeout_seconds <= 1.0 and limits.max_output_tokens == 2_000
        return ProviderGenerationV2(payload=self.payload, receipt=ProviderReceiptV2(
            provider="synthetic", provider_version="fixture.v2", configured_model="fixture",
            model="fixture", prompt_version=GENERATION_PROMPT_VERSION, run_id=uuid4(),
            request_attempt_bound=1, actual_requests=1,
            usage=ProviderUsageV2(state="unknown"), mode="synthetic",
        ))


def test_default_off_has_no_provider_or_authority_io() -> None:
    request, payload = make_request()
    provider, authority = SyntheticProvider(payload), SyntheticAuthority()
    result = generate_candidate(request, provider=provider, source_authority=authority)
    assert result.safe_reason == "generation_disabled"
    assert provider.calls == authority.calls == 0


def test_stages_strict_content_and_only_safe_summary() -> None:
    request, payload = make_request()
    provider, authority = SyntheticProvider(payload), SyntheticAuthority()
    result = generate_candidate(request, provider=provider, source_authority=authority, enabled=True)
    assert result.state == "staged" and result.source is not None and result.receipt is not None
    assert result.receipt.candidate_id == request.candidate_id
    assert result.receipt.provider.usage.input_tokens is None
    assert result.safe_summary() == {"state": "staged", "safe_reason": "staged"}
    prompt = str(provider.messages)
    assert str(request.candidate_id) not in prompt and "actor.worker" not in prompt
    # Output schema field names are public contract metadata, not private values.
    user_prompt = next(message["content"] for message in provider.messages if message["role"] == "user")
    assert "accepted_answers" not in user_prompt and "source_unavailable" not in repr(result)
    assert "AUTHORITATIVE OUTPUT JSON SCHEMA" in provider.messages[0]["content"]


def test_private_extra_and_stale_material_block_before_provider() -> None:
    request, payload = make_request()
    provider, authority = SyntheticProvider(payload), SyntheticAuthority()
    bad = request.model_copy(update={"private_chat": "never send"})
    result = generate_candidate(bad, provider=provider, source_authority=authority, enabled=True)
    assert result.safe_reason == "invalid_request"
    stale = request.materials[0].model_copy(update={"excerpt": "private code"})
    result = generate_candidate(request.model_copy(update={"materials": (stale,)}),
                                provider=provider, source_authority=authority, enabled=True)
    assert result.safe_reason == "source_unavailable"
    assert provider.calls == authority.calls == 0


def test_provider_cannot_mutate_identity_or_add_trust() -> None:
    request, payload = make_request()
    payload["self_verified"] = True
    result = generate_candidate(request, provider=SyntheticProvider(payload),
                                source_authority=SyntheticAuthority(), enabled=True)
    assert result.safe_reason == "invalid_candidate" and result.source is None
    del payload["self_verified"]
    payload["public"]["item_key"] = "different.item"
    payload["private"]["item_key"] = "different.item"
    result = generate_candidate(request, provider=SyntheticProvider(payload),
                                source_authority=SyntheticAuthority(), enabled=True)
    assert result.safe_reason == "candidate_mismatch"


def test_expired_profile_and_small_input_are_no_io() -> None:
    request, payload = make_request()
    provider, authority = SyntheticProvider(payload), SyntheticAuthority()
    old = datetime.now(timezone.utc) - timedelta(seconds=60)
    profile = request.profile.model_copy(update={"bound_at": old,
                                                "parent_deadline_at": old + timedelta(seconds=20)})
    result = generate_candidate(request.model_copy(update={"profile": profile}), provider=provider,
                                source_authority=authority, enabled=True)
    assert result.safe_reason == "deadline_exhausted"
    result = generate_candidate(request.model_copy(update={"limits": GenerationLimitsV2(
        max_input_bytes=1, max_output_tokens=2_000, max_output_bytes=100_000,
    )}), provider=provider, source_authority=authority, enabled=True)
    assert result.safe_reason == "input_limit"
    assert provider.calls == authority.calls == 0


def test_missing_partial_and_retry_usage_are_not_zero() -> None:
    assert response_usage(None, attempt_bound=1).input_tokens is None
    assert response_usage(LLMUsage(input_tokens=7), attempt_bound=1).state == "unknown"
    usage = LLMUsage(input_tokens=7, output_tokens=2, total_tokens=9)
    assert response_usage(usage, attempt_bound=1).state == "known"
    assert response_usage(usage, attempt_bound=3).state == "unknown"
    assert response_usage(usage, attempt_bound=1).cost is None


def test_existing_client_transport_provenance_usage_and_frozen_timeout() -> None:
    request, payload = make_request()
    calls = []

    def transport(url, headers, body, timeout):
        calls.append((body, timeout))
        return {"model": "actual.fixture.v1", "choices": [{"message": {"content": json.dumps(payload)}}],
                "usage": {"prompt_tokens": 17, "completion_tokens": 11, "total_tokens": 28}}

    settings = Settings(llm_type="deepseek", deepseek_api_key="fake-key",
                        deepseek_base_url="https://example.com", deepseek_model="fixture",
                        llm_timeout_seconds=90)
    provider = OpenAICompatibleGenerationProvider(settings, transport=transport, max_http_attempts=1)
    result = generate_candidate(request, provider=provider, source_authority=SyntheticAuthority(), enabled=True)
    assert result.state == "staged" and result.receipt is not None
    assert result.receipt.provider.model == "actual.fixture.v1"
    assert result.receipt.provider.usage.input_tokens == 17
    assert provider.request_attempt_bound == 1 and len(calls) == 1
    assert calls[0][1] <= 1.0 and calls[0][0]["max_tokens"] == 2_000


def test_public_template_is_fixed_public_prompt_data_and_counted_in_budget() -> None:
    request, payload = make_request()
    template = LearningItemSourceV1.model_validate(payload).public
    request = request.model_copy(update={"public_template": template})
    provider, authority = SyntheticProvider(payload), SyntheticAuthority()
    result = generate_candidate(request, provider=provider, source_authority=authority, enabled=True)
    assert result.state == "staged" and result.source is not None
    assert result.source.public == template
    assert "public_template" not in repr(request)
    prompt = json.loads(provider.messages[1]["content"])
    assert prompt["public_template"] == template.model_dump(mode="json")
    assert prompt["approved_excerpts"] == [material.excerpt for material in request.materials]
    assert "private" not in prompt and "accepted_answers" not in provider.messages[1]["content"]
    assert "fixed output constraint" in provider.messages[0]["content"]
    assert "AUTHORITATIVE OUTPUT JSON SCHEMA" in provider.messages[0]["content"]
    assert "stdin-free" in provider.messages[0]["content"]
    assert "input_json={}" in provider.messages[0]["content"]
    assert "stdout:string" in provider.messages[0]["content"]
    assert "sql_v2 typed tables and datasets" in provider.messages[0]["content"]
    assert "kind=table_result_v1" in provider.messages[0]["content"]
    envelope = {"messages": list(provider.messages),
                "output_schema": LearningItemSourceV1.model_json_schema()}
    input_bytes = len(json.dumps(envelope, ensure_ascii=False).encode("utf-8")) + 1_024
    limits = request.limits.model_copy(update={"max_input_bytes": input_bytes - 1})
    provider, authority = SyntheticProvider(payload), SyntheticAuthority()
    result = generate_candidate(request.model_copy(update={"limits": limits}), provider=provider,
                                source_authority=authority, enabled=True)
    assert result.safe_reason == "input_limit"
    assert provider.calls == authority.calls == 0


def test_invalid_public_template_blocks_before_provider_and_authority_io() -> None:
    request, payload = make_request()
    template = LearningItemSourceV1.model_validate(payload).public
    reference = template.source_references[0].model_copy(update={"locator": "other.document"})
    mismatches = (
        {"item_key": "other.item"}, {"version": "other.version"},
        {"kind": LearningItemKind.CODE},
        {"purpose": LearningItemPurpose.REMEDIATION},
        {"difficulty": LearningItemDifficulty.D5},
        {"source_references": (reference,)}, {"allowed_interactions": ()},
        {"private_scoring": "must never reach provider"},
    )
    for update in mismatches:
        provider, authority = SyntheticProvider(payload), SyntheticAuthority()
        bad_template = template.model_copy(update=update)
        result = generate_candidate(request.model_copy(update={"public_template": bad_template}),
                                    provider=provider, source_authority=authority, enabled=True)
        assert result.state == "blocked" and result.safe_reason == "invalid_request", update
        assert provider.calls == authority.calls == 0


def test_provider_changed_public_template_is_candidate_mismatch() -> None:
    request, payload = make_request()
    template = LearningItemSourceV1.model_validate(payload).public
    request = request.model_copy(update={"public_template": template})
    payload["public"]["instruction_markdown"] = "A different public task."
    provider, authority = SyntheticProvider(payload), SyntheticAuthority()
    result = generate_candidate(request, provider=provider, source_authority=authority, enabled=True)
    assert result.state == "failed" and result.safe_reason == "candidate_mismatch"
    assert result.source is None and result.receipt is not None
    assert provider.calls == authority.calls == 1
