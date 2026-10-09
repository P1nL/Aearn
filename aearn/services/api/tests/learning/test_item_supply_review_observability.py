"""PRIVATE offline failure observations; never live provider/DB acceptance."""
from dataclasses import FrozenInstanceError, asdict, replace
import json
from types import SimpleNamespace
import urllib.error
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemReviewRole, canonical_hash
from app.services.learning.item_supply.pipeline import ItemSupplyPipeline, PreparedReview
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.review_observability import ReviewFailureObservation, observe_review_failure
from app.services.learning.item_supply.review_protocol import make_review_request
from app.services.learning.item_supply.review_provider import (
    AutonomousReviewError, BoundedOpenAIReviewClient, JsonReviewerV2,
    blind_solve_candidate, review_candidate_for_policy,
)
from app.services.learning.item_supply.shared_review import SharedReviewPipeline, SharedReviewResult
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
from app.services.llm.contracts import LLMResponseDiagnostics, LLMUsage
from app.services.llm.llm_client import (
    LLMCallError, LLMConfigurationError, LLMInvalidResponseError, LLMInvalidResponseKind, LLMJsonResponse,
)
from tests.learning.test_item_supply_autonomous_review import DIGEST, FakeScorer, identity, subject
from tests.learning.test_item_supply_evidenced_review import LabeledClient, evidenced_ports
from tests.learning.test_item_supply_generation import make_request
from tests.learning.test_item_supply_shared_validation import OfflineConnection

SECRET = "PRIVATE_SENTINEL_credential_url_body_model_prompt"
USAGE = LLMUsage(input_tokens=200, cached_input_tokens=80, output_tokens=32, total_tokens=232, reasoning_tokens=12)
META = LLMResponseDiagnostics(response_status="incomplete", incomplete_reason="max_output_tokens",
    requested_max_output_tokens=1024, requested_reasoning_effort="high", visible_output_chars=20)


class ObservedClient(LabeledClient):
    def __init__(self, *, error=None, content=None, mutation=None, diagnostics=META):
        super().__init__("field_bound_material_claim" if mutation else "known_good", mutation)
        self.error, self.content, self.diagnostics = error, content, diagnostics

    def complete_json(self, messages, **kwargs):
        if self.error is not None:
            raise self.error
        response = super().complete_json(messages, **kwargs)
        return LLMJsonResponse(response.content if self.content is None else self.content, self.model,
                               USAGE, response_diagnostics=self.diagnostics)


def port(client, role=LearningItemReviewRole.TECHNICAL):
    return JsonReviewerV2(client, role=role, identity=identity("observed."+role.value),
        profile_hash=DIGEST, timeout_seconds=1, max_output_tokens=1024, review_protocol="evidenced-v1")


def request_for(role=LearningItemReviewRole.TECHNICAL):
    s, v, b = subject()
    return make_review_request(s, binding=b, role=role, validation_receipt=v, protocol="evidenced-v1")


def failure(client):
    with pytest.raises(AutonomousReviewError) as caught:
        port(client).review(request_for())
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert SECRET not in repr(caught.value) + str(caught.value) + json.dumps(caught.value.observation_payload())
    return caught.value


@pytest.mark.parametrize("kind,code", [
    (LLMInvalidResponseKind.RESPONSE_INCOMPLETE, "response_incomplete"),
    (LLMInvalidResponseKind.RESPONSE_FAILED, "response_failed"),
    (LLMInvalidResponseKind.CONTENT_MISSING, "response_missing"),
    (LLMInvalidResponseKind.CONTENT_NOT_JSON_OBJECT, "response_non_json"),
    (LLMInvalidResponseKind.ENVELOPE_INVALID, "response_envelope_invalid"),
    (LLMInvalidResponseKind.UNKNOWN, "unknown_exception"),
])
def test_rejected_response_kind_retains_usage_and_closed_limits(kind, code):
    error = LLMInvalidResponseError(SECRET, kind=kind, usage=USAGE, model=SECRET, response_diagnostics=META)
    exc = failure(ObservedClient(error=error))
    assert str(exc) == "review_provider_failed"
    value = exc.observation_payload()
    assert value["safe_code"] == code and value["phase"] == "provider_call"
    assert value["failed_role"] == "technical"
    assert value["usage"] == asdict(USAGE) and value["response_diagnostics"] == asdict(META)
    assert value["logical_client_invocations"] == 1
    assert value["invocation_count_semantics"] == "logical_client_invocations_not_http_attempts"


@pytest.mark.parametrize("error,code", [
    (TimeoutError(SECRET), "provider_timeout"),
    (ConnectionError(SECRET), "provider_transport"),
    (LLMConfigurationError(SECRET), "provider_configuration"),
    (RuntimeError(SECRET), "unknown_exception"),
])
def test_failure_types_are_safe_and_do_not_guess_fake_effort_or_usage(error, code):
    value = failure(ObservedClient(error=error)).observation_payload()
    assert value["safe_code"] == code and value["usage"] is None
    assert value["response_diagnostics"] == asdict(LLMResponseDiagnostics(requested_max_output_tokens=1024))


@pytest.mark.parametrize("cause", [TimeoutError(SECRET), urllib.error.URLError(TimeoutError(SECRET)),
                                  urllib.error.HTTPError(SECRET, 503, SECRET, {}, None)])
def test_trusted_core_transport_wrapper_classifies_bounded_cause_types(cause):
    wrapped = LLMCallError(SECRET)
    wrapped.__cause__ = cause
    value = failure(ObservedClient(error=wrapped)).observation_payload()
    assert value["safe_code"] == ("provider_transport" if isinstance(cause, urllib.error.HTTPError) else "provider_timeout")


def test_missing_terminal_is_not_misreported_as_non_json():
    error = LLMInvalidResponseError(SECRET, kind=LLMInvalidResponseKind.CONTENT_NOT_JSON_OBJECT,
        usage=USAGE, response_diagnostics=LLMResponseDiagnostics(response_status="missing_terminal"))
    value = failure(ObservedClient(error=error)).observation_payload()
    assert value["safe_code"] == "response_missing"
    assert value["response_diagnostics"]["requested_max_output_tokens"] == 1024
    assert value["response_diagnostics"]["requested_reasoning_effort"] is None


def test_parsed_json_schema_failure_retains_usage_without_raw_validation_input():
    value = failure(ObservedClient(content={SECRET: SECRET}, diagnostics=None)).observation_payload()
    assert value["phase"] == "output_schema" and value["safe_code"] == "schema_validation"
    assert value["usage"] == asdict(USAGE)
    assert value["response_diagnostics"] == asdict(LLMResponseDiagnostics(requested_max_output_tokens=1024))


def test_evidenced_field_verification_retains_response_metadata():
    def mutation(out, _):
        out["findings"][0]["references"][0]["value_hash"] = "f"*64
    exc = failure(ObservedClient(mutation=mutation))
    assert str(exc) == "evidenced_review_failed"
    value = exc.observation_payload()
    assert value["phase"] == "evidence_verification" and value["safe_code"] == "evidence_verification"
    assert value["usage"] == asdict(USAGE) and value["response_diagnostics"] == asdict(META)


def test_late_role_keeps_original_cause_actual_role_and_completed_reports():
    source, validation, binding = subject()
    solver, roles, _ = evidenced_ports()
    roles = list(roles)
    roles[3] = port(ObservedClient(error=LLMInvalidResponseError(SECRET,
        kind=LLMInvalidResponseKind.RESPONSE_INCOMPLETE, usage=USAGE, response_diagnostics=META)), roles[3].role)
    blind = blind_solve_candidate(source, binding=binding, author_identity="author", solver=solver, scorer=FakeScorer())
    with pytest.raises(AutonomousReviewError, match="^review_bundle_failed$") as caught:
        review_candidate_for_policy(source, binding=binding, validation_receipt=validation, author_identity="author",
            blind_solve_receipt=blind, reviewers=tuple(roles), policy=AutonomousEvidencePolicyV2())
    exc = caught.value
    assert tuple(r.role for r in exc.partial_reports) == tuple(LearningItemReviewRole)[:3]
    value = exc.observation_payload()
    assert value["failed_role"] == LearningItemReviewRole.AMBIGUITY.value
    assert value["safe_code"] == "response_incomplete" and value["phase"] == "provider_call"
    assert value["usage"] == asdict(USAGE) and value["logical_client_invocations"] == 1
    assert exc.__cause__ is None and exc.__suppress_context__


def test_private_pipeline_preserves_observation_and_unknown_settlement(monkeypatch):
    source, validation, binding = subject()
    solver, roles, _ = evidenced_ports()
    roles = list(roles)
    roles[3] = port(ObservedClient(content={SECRET: SECRET}), roles[3].role)
    conn = OfflineConnection()
    conn.info.transaction_status = TransactionStatus.IDLE
    owner = ItemSupplyPipeline(conn, Settings())
    lease = SimpleNamespace(profile=None)
    p = PreparedReview(lease, uuid4(), uuid4(), source, validation, binding, "author", uuid4(), "synthetic",
                       (1,)*7, review_protocol="evidenced-v1")
    monkeypatch.setattr(owner.runtime, "refresh_lease", lambda *a, **k: lease)
    with pytest.raises(AutonomousReviewError) as caught:
        owner.run_review(p, solver=solver, scorer=FakeScorer(), reviewers=tuple(roles))
    assert owner.review_observations[p.reservation_id].payload() == caught.value.observation_payload()
    assert len(owner.partial_review_reports[p.reservation_id]) == 3
    with pytest.raises(PipelineRepositoryError, match="REVIEW_ALREADY_DISPATCHED"):
        owner.run_review(p, solver=solver, scorer=FakeScorer(), reviewers=tuple(roles))
    settled = []
    monkeypatch.setattr(owner.budget, "settle", lambda **kw: settled.append(kw))
    owner.settle_review(p, None)
    assert settled[0]["usage_state"] == "unknown" and settled[0]["actual"] is None


def test_shared_result_hash_binds_observation_and_legacy_empty_hash_is_identical(monkeypatch):
    result = SharedReviewResult(None, None, "review_pending")
    assert result.observation_payload() is None
    assert AutonomousReviewError("review_provider_failed").observation_payload() is None
    old_hash = canonical_hash({"blind": None, "bundle": None, "reason": "review_pending", "ambiguity": None})
    assert SharedReviewPipeline._result_hash(result) == old_hash
    observed = replace(result, observation=observe_review_failure(TimeoutError(SECRET), phase="provider_call"))
    assert SharedReviewPipeline._result_hash(observed) != old_hash
    assert "observation=" not in repr(observed)
    p = SimpleNamespace(reservation_id=uuid4())
    owner = object.__new__(SharedReviewPipeline)
    owner._results = {p.reservation_id: (observed, owner._result_hash(observed))}
    monkeypatch.setattr(owner, "_issued", lambda _: (None, None, None, "scorer"))
    assert owner._result(p, observed) == "scorer"
    object.__setattr__(observed, "observation", replace(observed.observation, safe_code="provider_transport"))
    with pytest.raises(PipelineRepositoryError, match="RESULT_UNAVAILABLE"):
        owner._result(p, observed)


def test_observation_is_frozen_closed_and_returned_payload_is_detached():
    observation = ReviewFailureObservation("provider_call", LearningItemReviewRole.TECHNICAL, "provider_timeout", USAGE, META, 1)
    with pytest.raises(FrozenInstanceError):
        observation.safe_code = "unknown_exception"
    payload = observation.payload()
    payload["usage"]["output_tokens"] = 0
    assert observation.payload()["usage"]["output_tokens"] == 32
    for change in ({"safe_code": SECRET}, {"failed_role": SECRET}, {"phase": SECRET}, {"logical_client_invocations": 7}):
        with pytest.raises(ValueError, match="invalid_review_observation"):
            replace(observation, **change)
    object.__setattr__(observation, "safe_code", SECRET)
    with pytest.raises(ValueError, match="invalid_review_observation"):
        observation.payload()


@pytest.mark.parametrize("timeout", [True, False])
def test_bounded_chat_failure_has_trusted_high_request_limits_but_no_invented_stop(timeout):
    base, _ = make_request()
    settings = Settings(llm_type="deepseek", deepseek_model="deepseek-v4-pro", deepseek_api_key="offline",
                        deepseek_base_url="https://invalid.example")
    def transport(*args):
        if timeout:
            raise TimeoutError(SECRET)
        return {"model": settings.llm_model, "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
    client = BoundedOpenAIReviewClient(settings, profile=base.profile, transport=transport)
    adapter = JsonReviewerV2(client, role=LearningItemReviewRole.TECHNICAL,
        identity=identity("bounded.offline", "deepseek", settings.llm_model),
        profile_hash=base.profile.profile_hash, timeout_seconds=1, max_output_tokens=1024, review_protocol="evidenced-v1")
    s, v, b = subject()
    b = b.model_copy(update={"profile_hash": base.profile.profile_hash})
    request = make_review_request(s, binding=b, role=adapter.role, validation_receipt=v, protocol="evidenced-v1")
    with pytest.raises(AutonomousReviewError) as caught:
        adapter.review(request)
    value = caught.value.observation_payload()
    assert value["safe_code"] == ("provider_timeout" if timeout else "schema_validation")
    assert value["response_diagnostics"] == asdict(LLMResponseDiagnostics(requested_max_output_tokens=1024, requested_reasoning_effort="high"))
    assert SECRET not in json.dumps(value)
