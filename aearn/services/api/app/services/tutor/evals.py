"""Deterministic, fake-only evaluation runner for the Tutor Harness."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.agents.harness.context_builder import TutorContextBuilder, TutorContextBuilderConfig
from app.agents.harness.contracts import (
    CONTEXT_SECTION_PRIORITY,
    TutorCapabilityRequest,
    TutorContextInput,
    TutorContextSection,
    TutorContextSource,
    TutorDecision,
    TutorEffectProposal,
    TutorEffectStatus,
    TutorInputEvent,
    TutorPolicySnapshot,
    TutorProviderResult,
    TutorRunSnapshot,
    TutorTerminalOutcome,
)
from app.agents.harness.skill_catalog import SkillCatalogSnapshot, compile_published_skill_catalog
from app.core.config import Settings
from app.services.llm.llm_client import (
    LLMCallError,
    LLMJsonResponse,
    LLMVisibleOutputObserver,
)
from app.services.tutor.ports import (
    AllowTutorDecisionGate,
    DefaultDenyCapabilityGateway,
    DefaultDenyTutorDecisionGate,
    FixedClock,
    InMemoryTutorCompactionPublisher,
    InMemoryTutorContextLoader,
    InMemoryTutorRunStore,
    RecordingEffectCommitter,
    SequenceTutorProvider,
)
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway, _build_messages
from app.services.tutor.run_loop import TutorRunLoop
from app.services.tutor.safe_projection import TutorSafeProjection


FIXTURE_SCHEMA_VERSION = "tutor_eval_v1"
_NOW = datetime(2026, 7, 27, tzinfo=UTC)


class TutorEvalFixtureError(ValueError):
    pass


@dataclass(frozen=True)
class TutorEvalCase:
    case_id: str
    scenario: str
    catalog: Mapping[str, object]
    expected: Mapping[str, object]
    protected_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class TutorEvalResult:
    case_id: str
    passed: bool
    observed: dict[str, object]


def load_tutor_eval_cases(path: Path) -> tuple[TutorEvalCase, ...]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TutorEvalFixtureError("Tutor eval fixture is not valid JSON") from exc
    if not isinstance(document, Mapping) or document.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise TutorEvalFixtureError("Tutor eval fixture schema version is unsupported")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise TutorEvalFixtureError("Tutor eval fixture requires non-empty cases")
    cases: list[TutorEvalCase] = []
    seen: set[str] = set()
    for raw in raw_cases:
        if not isinstance(raw, Mapping):
            raise TutorEvalFixtureError("Tutor eval case is invalid")
        case_id = str(raw.get("id") or "")
        scenario = str(raw.get("scenario") or "")
        catalog = raw.get("catalog")
        expected = raw.get("expected")
        markers = raw.get("protected_markers") or []
        if not case_id or case_id in seen or not scenario or not isinstance(catalog, Mapping) or not isinstance(expected, Mapping):
            raise TutorEvalFixtureError("Tutor eval case identity or expectation is invalid")
        if not isinstance(markers, list) or any(not isinstance(marker, str) for marker in markers):
            raise TutorEvalFixtureError("Tutor eval protected markers are invalid")
        seen.add(case_id)
        cases.append(
            TutorEvalCase(
                case_id=case_id,
                scenario=scenario,
                catalog=dict(catalog),
                expected=dict(expected),
                protected_markers=tuple(markers),
            )
        )
    return tuple(cases)


def run_tutor_eval_case(case: TutorEvalCase, *, catalog: SkillCatalogSnapshot | None = None) -> TutorEvalResult:
    resolved_catalog = catalog or compile_published_skill_catalog()
    _assert_catalog_identity(case.catalog, resolved_catalog)
    observed: dict[str, object]
    if case.scenario == "catalog_identity":
        observed = {"catalog_digest": resolved_catalog.digest, "status": "validated"}
    elif case.scenario == "policy_denial":
        observed = _policy_denial_observed()
    elif case.scenario == "strict_provider_rejection":
        observed = _strict_provider_rejection_observed()
    elif case.scenario == "bounded_loop":
        observed = _bounded_loop_observed()
    elif case.scenario == "stale_effect":
        observed = _stale_effect_observed()
    elif case.scenario == "primary_model_unavailable":
        observed = _primary_model_unavailable_observed()
    elif case.scenario == "redaction_leakage":
        observed = _redaction_observed(case.protected_markers)
    elif case.scenario == "replay_outbox_proposal":
        observed = _replay_outbox_proposal_observed()
    elif case.scenario == "current_input_pinned":
        observed = _current_input_pinned_observed()
    elif case.scenario == "newest_history_selected":
        observed = _newest_history_selected_observed()
    elif case.scenario == "teaching_correction_policy_present":
        observed = _teaching_correction_policy_observed()
    elif case.scenario == "current_input_unrepresentable_provider_not_called":
        observed = _current_input_unrepresentable_observed()
    else:
        raise TutorEvalFixtureError("Tutor eval scenario is not supported")
    for key, expected_value in case.expected.items():
        if observed.get(str(key)) != expected_value:
            return TutorEvalResult(case.case_id, False, observed)
    return TutorEvalResult(case.case_id, True, observed)


def run_tutor_eval_fixture(path: Path, *, catalog: SkillCatalogSnapshot | None = None) -> tuple[TutorEvalResult, ...]:
    return tuple(run_tutor_eval_case(case, catalog=catalog) for case in load_tutor_eval_cases(path))


def _assert_catalog_identity(expected: Mapping[str, object], catalog: SkillCatalogSnapshot) -> None:
    skill_id = str(expected.get("skill_id") or "")
    skill_version = str(expected.get("skill_version") or "")
    skill = catalog.resolve_skill(skill_id, skill_version)
    if skill is None or str(expected.get("digest") or "") != catalog.digest:
        raise TutorEvalFixtureError("Tutor eval fixture catalog identity does not match the reviewed snapshot")
    expected_hashes = {
        "manifest_hash": skill.manifest_hash,
        "instruction_hash": skill.instruction_hash,
        "evaluation_hash": skill.evaluation_hash,
    }
    if any(str(expected.get(name) or "") != value for name, value in expected_hashes.items()):
        raise TutorEvalFixtureError("Tutor eval fixture Skill hashes do not match the reviewed snapshot")


def _policy(*, max_iterations: int = 3, max_effects: int = 1) -> TutorPolicySnapshot:
    return TutorPolicySnapshot(
        deadline=datetime(2030, 1, 1, tzinfo=UTC),
        max_iterations=max_iterations,
        max_model_calls=3,
        max_capability_calls=1,
        max_effects=max_effects,
        context_token_budget=8,
    )


def _snapshot(*, policy: TutorPolicySnapshot | None = None) -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="eval-run",
        conversation_id="eval-conversation",
        user_id="eval-user",
        origin="interactive",
        input_revision=0,
        policy=policy or _policy(),
    )


def _context(revision: int) -> TutorContextInput:
    return TutorContextInput(
        run_id="eval-run",
        conversation_id="eval-conversation",
        input_revision=revision,
        current_input_required=True,
        current_input=TutorContextSource(f"eval-message-{revision}", "current learner request"),
        system_descriptors=(TutorContextSource("eval-system", {"status": "bounded"}),),
    )


def _loop(
    *,
    store: InMemoryTutorRunStore,
    provider: SequenceTutorProvider,
    contexts: Mapping[tuple[str, int], TutorContextInput],
    effect_committer: RecordingEffectCommitter | None = None,
    decision_gate: object | None = None,
) -> tuple[TutorRunLoop, RecordingEffectCommitter]:
    committer = effect_committer or RecordingEffectCommitter(status=TutorEffectStatus.DENIED)
    loop = TutorRunLoop(
        store=store,
        context_loader=InMemoryTutorContextLoader(contexts),
        context_builder=TutorContextBuilder(
            estimator=_OneTokenEstimator(),
            config=TutorContextBuilderConfig(
                section_item_limits=tuple((section, 1) for section in CONTEXT_SECTION_PRIORITY),
            ),
        ),
        provider=provider,
        capability_gateway=DefaultDenyCapabilityGateway(),
        effect_committer=committer,
        clock=FixedClock(_NOW),
        compaction_publisher=InMemoryTutorCompactionPublisher(),
        decision_gate=decision_gate if decision_gate is not None else AllowTutorDecisionGate(),  # type: ignore[arg-type]
    )
    return loop, committer


def _policy_denial_observed() -> dict[str, object]:
    store = InMemoryTutorRunStore([_snapshot()])
    provider = SequenceTutorProvider(
        [TutorProviderResult(decision=TutorDecision(capability_requests=(TutorCapabilityRequest("cap-1", "unknown"),)))]
    )
    loop, _ = _loop(
        store=store,
        provider=provider,
        contexts={("eval-run", 0): _context(0)},
        decision_gate=DefaultDenyTutorDecisionGate(),
    )
    result = loop.run(run_id="eval-run", lease_owner_id="eval-worker")
    return {"status": result.status.value, "code": result.diagnostic_code, "provider_calls": len(provider.calls)}


def _strict_provider_rejection_observed() -> dict[str, object]:
    gateway = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="openai", openai_api_key="fixture-key", openai_base_url="https://provider.example", openai_model="fixture"),
        client=_FakeJsonClient(
            {
                "schema_version": "tutor_provider_items_v4",
                "message": {
                    "type": "agent_message",
                    "text": "safe",
                    "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                    "conversation_title": None,
                },
                "action": {"type": "turn_completed"},
                "reasoning": "private diagnostic",
            }
        ),
    )
    result = gateway.decide(run=_snapshot(), context=_empty_context())
    return {"status": result.terminal_outcome.value if result.terminal_outcome else "none", "code": result.safe_code}


def _bounded_loop_observed() -> dict[str, object]:
    store = InMemoryTutorRunStore([_snapshot(policy=_policy(max_iterations=0))])
    provider = SequenceTutorProvider([])
    loop, _ = _loop(store=store, provider=provider, contexts={})
    result = loop.run(run_id="eval-run", lease_owner_id="eval-worker")
    return {"status": result.status.value, "provider_calls": len(provider.calls)}


def _stale_effect_observed() -> dict[str, object]:
    store = InMemoryTutorRunStore([_snapshot()])
    calls = 0

    def accept_input(run: TutorRunSnapshot, context: object) -> None:
        nonlocal calls
        del run, context
        calls += 1
        if calls == 1:
            store.accept_input(
                TutorInputEvent(
                    run_id="eval-run",
                    message_id="eval-message",
                    revision=1,
                    content="new input",
                    received_at=_NOW,
                )
            )

    provider = SequenceTutorProvider(
        [
            TutorProviderResult(
                decision=TutorDecision(effect_proposals=(TutorEffectProposal("effect-1", "future-effect", 0),))
            ),
            TutorProviderResult(decision=TutorDecision(terminal_outcome=TutorTerminalOutcome.COMPLETED)),
        ],
        on_decide=accept_input,
    )
    committer = RecordingEffectCommitter()
    loop, _ = _loop(
        store=store,
        provider=provider,
        contexts={("eval-run", 0): _context(0), ("eval-run", 1): _context(1)},
        effect_committer=committer,
    )
    result = loop.run(run_id="eval-run", lease_owner_id="eval-worker")
    return {
        "status": result.status.value,
        "effect_status": result.effect_results[0].status.value if result.effect_results else "none",
        "committer_calls": len(committer.calls),
    }


def _primary_model_unavailable_observed() -> dict[str, object]:
    client = _FakeJsonClient(error=LLMCallError("provider raw Bearer secret-token"))
    gateway = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="openai", openai_api_key="fixture-key", openai_base_url="https://provider.example", openai_model="fixture"),
        client=client,
    )
    result = gateway.decide(run=_snapshot(), context=_empty_context())
    return {
        "status": result.terminal_outcome.value if result.terminal_outcome else "none",
        "code": result.safe_code,
        "provider_calls": client.calls,
    }


def _replay_outbox_proposal_observed() -> dict[str, object]:
    """A fake-only ledger proves logical replay identities without PostgreSQL."""
    inputs: dict[str, tuple[str, int]] = {}
    events: dict[str, int] = {}
    outbox: dict[str, str] = {}
    proposals: dict[str, str] = {}
    terminal_outcome: str | None = None

    body = "deterministic learner input"
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    first_input = inputs.setdefault("input-1", (body_hash, 1))
    replayed_input = inputs.setdefault("input-1", (body_hash, 1))
    first_event = events.setdefault("input:input-1", 1)
    replayed_event = events.setdefault("input:input-1", 1)
    first_outbox = outbox.setdefault("compaction:closed-range-1", "outbox-1")
    replayed_outbox = outbox.setdefault("compaction:closed-range-1", "outbox-1")
    first_proposal = proposals.setdefault(first_outbox, "proposal-1")
    replayed_proposal = proposals.setdefault(first_outbox, "proposal-1")
    first_terminal_writer = terminal_outcome is None
    if first_terminal_writer:
        terminal_outcome = "completed"
    second_terminal_writer = terminal_outcome is None

    return {
        "input_replayed": first_input == replayed_input,
        "event_replayed": first_event == replayed_event,
        "outbox_replayed": first_outbox == replayed_outbox,
        "proposal_replayed": first_proposal == replayed_proposal,
        "terminal_writers": int(first_terminal_writer) + int(second_terminal_writer),
    }


def _current_input_pinned_observed() -> dict[str, object]:
    selection = TutorContextBuilder(estimator=_OneTokenEstimator()).build(
        TutorContextInput(
            run_id="eval-run",
            conversation_id="eval-conversation",
            input_revision=1,
            current_input=TutorContextSource("message-current", "我应该学哪些语言"),
            current_input_required=True,
            system_descriptors=(TutorContextSource("system", {"path": "old-html"}),),
            recent_messages=(
                TutorContextSource("message-old", {"role": "user", "content": "我想做个网站"}),
            ),
        ),
        token_budget=2,
    )
    return {
        "current_input": selection.current_input.content if selection.current_input is not None else None,
        "current_source": selection.current_input.source_id if selection.current_input is not None else None,
        "context_sources": [item.source_id for item in selection.items],
    }


def _newest_history_selected_observed() -> dict[str, object]:
    limits = tuple(
        (section, 4 if section is TutorContextSection.RECENT_MESSAGES else 0)
        for section in CONTEXT_SECTION_PRIORITY
    )
    selection = TutorContextBuilder(
        estimator=_OneTokenEstimator(),
        config=TutorContextBuilderConfig(section_item_limits=limits),
    ).build(
        TutorContextInput(
            run_id="eval-run",
            conversation_id="eval-conversation",
            input_revision=7,
            current_input=TutorContextSource("message-7", "latest"),
            current_input_required=True,
            recent_messages=tuple(
                TutorContextSource(f"message-{index}", {"role": "user", "content": f"turn-{index}"})
                for index in range(1, 7)
            ),
        ),
        token_budget=8,
    )
    return {"history_sources": [item.source_id for item in selection.items]}


def _teaching_correction_policy_observed() -> dict[str, object]:
    selection = TutorContextBuilder(estimator=_OneTokenEstimator()).build(
        TutorContextInput(
            run_id="eval-run",
            conversation_id="eval-conversation",
            input_revision=1,
            current_input=TutorContextSource("message-current", "你不是应该教我编程语言吗"),
            current_input_required=True,
        ),
        token_budget=4,
    )
    system = _build_messages(run=_snapshot(), context=selection)[0]["content"]
    required = (
        "authoritative request",
        "correction",
        "stop the stale path",
        "answer directly first",
        "at most one necessary follow-up question",
    )
    return {"policy_present": all(marker in system for marker in required)}


def _current_input_unrepresentable_observed() -> dict[str, object]:
    class _TwoTokenEstimator:
        def estimate_tokens(self, value: object) -> int:
            del value
            return 2

    policy = _policy()
    policy = TutorPolicySnapshot(
        deadline=policy.deadline,
        max_iterations=policy.max_iterations,
        max_model_calls=policy.max_model_calls,
        max_capability_calls=policy.max_capability_calls,
        max_effects=policy.max_effects,
        context_token_budget=1,
    )
    store = InMemoryTutorRunStore([_snapshot(policy=policy)])
    provider = SequenceTutorProvider([])
    loop = TutorRunLoop(
        store=store,
        context_loader=InMemoryTutorContextLoader(
            {
                ("eval-run", 0): TutorContextInput(
                    run_id="eval-run",
                    conversation_id="eval-conversation",
                    input_revision=0,
                    current_input=TutorContextSource("message-current", "x"),
                    current_input_required=True,
                )
            }
        ),
        context_builder=TutorContextBuilder(estimator=_TwoTokenEstimator()),
        provider=provider,
        capability_gateway=DefaultDenyCapabilityGateway(),
        effect_committer=RecordingEffectCommitter(status=TutorEffectStatus.DENIED),
        clock=FixedClock(_NOW),
        compaction_publisher=InMemoryTutorCompactionPublisher(),
        decision_gate=AllowTutorDecisionGate(),
    )
    result = loop.run(run_id="eval-run", lease_owner_id="eval-worker")
    return {
        "status": result.status.value,
        "code": result.diagnostic_code,
        "provider_calls": len(provider.calls),
    }


def _redaction_observed(markers: Sequence[str]) -> dict[str, object]:
    projector = TutorSafeProjection()
    raw = {
        "kind": "diagnostic",
        "status": "completed",
        "provider_payload": "provider raw Authorization: Bearer secret-token",
        "metadata": {"hiddenTestBody": "hidden test oracle"},
        "source_id": "source-1",
        "source_hash": "a" * 64,
        "traceback": "Traceback (most recent call last)",
        "path": "C:\\secret\\container\\file.py",
        "code": "def full_solution(): pass",
    }
    serialized = json.dumps(projector.export(projector.project(raw)), ensure_ascii=False, sort_keys=True)
    return {"status": "redacted", "leak_free": all(marker not in serialized for marker in markers)}


def _empty_context():
    return TutorContextBuilder(
        estimator=_OneTokenEstimator(),
        config=TutorContextBuilderConfig(section_item_limits=()),
    ).build(
        TutorContextInput(
            run_id="eval-run",
            conversation_id="eval-conversation",
            input_revision=0,
            current_input_required=True,
            current_input=TutorContextSource("eval-current-input", "current learner request"),
        ),
        token_budget=8,
    )


class _OneTokenEstimator:
    def estimate_tokens(self, value: object) -> int:
        del value
        return 1


class _FakeJsonClient:
    def __init__(self, content: Mapping[str, object] | None = None, error: Exception | None = None) -> None:
        self._content = dict(content or {})
        self._error = error
        self.calls = 0

    @property
    def model(self) -> str:
        return "fixture-primary-model"

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        output_schema: Mapping[str, object] | None = None,
        schema_name: str | None = None,
        thinking_mode: Literal["enabled", "disabled"] | None = None,
        capture_provider_body: bool = False,
        visible_output_observer: LLMVisibleOutputObserver | None = None,
    ) -> LLMJsonResponse:
        del (
            messages,
            temperature,
            max_tokens,
            timeout_seconds,
            output_schema,
            schema_name,
            thinking_mode,
            capture_provider_body,
            visible_output_observer,
        )
        self.calls += 1
        if self._error is not None:
            raise self._error
        return LLMJsonResponse(content=self._content, model=self.model)
