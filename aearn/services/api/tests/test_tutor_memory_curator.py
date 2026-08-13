from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.core.config import Settings
from app.services.tutor.curation import (
    CurationGatewayResult,
    CurationMemoryEntryProposalV1,
    PrimaryCurationGateway,
    TutorMemoryCurator,
)
from app.services.tutor.learner_state import TutorCurationSource, TutorLearnerStateRepository
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.proactive import TutorProactivePreference, TutorProactiveScheduler, TutorProactiveSchedulerConfig
from app.services.tutor.proactive_repository import PostgresTutorProactiveRepository
from tutor_learner_state_support import create_curation_outbox


_NOW = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)


def _config() -> TutorProactiveSchedulerConfig:
    return TutorProactiveSchedulerConfig(
        enabled=True,
        hard_paused=False,
        cutover_eligible=True,
        inferred_memory_enabled=True,
        proactive_daily_budget=1,
        curation_daily_budget=3,
        proactive_concurrency_limit=1,
        curation_concurrency_limit=1,
        proactive_cooldown_seconds=1,
        curation_cooldown_seconds=1,
        proactive_circuit_failure_threshold=2,
        curation_circuit_failure_threshold=2,
        circuit_window_seconds=60,
        candidate_lease_seconds=60,
        curation_lease_seconds=60,
        max_retry_attempts=2,
        retry_backoff_seconds=5,
    )


class _MemoryGateway:
    def __init__(self) -> None:
        self.calls: list[TutorCurationSource] = []

    def propose(self, *, source: TutorCurationSource) -> CurationGatewayResult:
        self.calls.append(source)
        return CurationGatewayResult(
            state="proposal",
            code="curation_proposal_ready",
            proposal=CurationMemoryEntryProposalV1(
                kind="memory_entry",
                category="learning-preference",
                statement="The learner benefits from a compact verification checkpoint.",
                confidence="medium",
            ),
        )


class _PrimaryClient:
    def __init__(self, content: dict[str, object]) -> None:
        self.content = content
        self.calls: list[tuple[object, object]] = []

    def complete_json(
        self,
        messages,
        *,
        temperature=None,
        max_tokens=None,
        timeout_seconds=None,
        output_schema=None,
        schema_name=None,
    ):
        del timeout_seconds
        self.calls.append(
            (
                messages,
                {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "output_schema": output_schema,
                    "schema_name": schema_name,
                },
            )
        )
        return SimpleNamespace(content=self.content)

class _NeverClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *args, **kwargs):
        del args, kwargs
        self.calls += 1
        raise AssertionError("zero-budget Curator must not call a provider")


def _enable_scheduler_preference(repository: PostgresTutorProactiveRepository, fixture) -> None:
    repository.upsert_preference(
        preference=TutorProactivePreference(user_id=fixture.user_id, enabled=True),
        now=_NOW,
    )


def test_curator_projects_one_inference_from_redacted_outbox_with_one_receipt(tutor_persistence) -> None:
    fixture = tutor_persistence
    learner_state = TutorLearnerStateRepository(fixture.connection)
    preference = learner_state.set_inferred_memory_preference(
        user_id=fixture.user_id,
        enabled=True,
        expected_setting_version="memory_settings_v1",
        now=_NOW,
    )
    assert preference.setting_version == "memory_settings_v1"
    outbox_id = create_curation_outbox(fixture, now=_NOW, memory_setting_version=preference.setting_version)
    scheduler_repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_scheduler_preference(scheduler_repository, fixture)
    gateway = _MemoryGateway()
    curator = TutorMemoryCurator(
        repository=PostgresTutorRepository(fixture.connection),
        learner_state=learner_state,
        gateway=gateway,
    )
    scheduler = TutorProactiveScheduler(
        store=scheduler_repository,
        config=_config(),
        curation_processor=curator,
    )

    seeded = scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id)
    result = scheduler.drain_curation(worker_id="curator-worker", now=_NOW, user_id=fixture.user_id)
    projection = fixture.connection.execute(
        """
        SELECT memory_kind, state, confidence, provenance_kind, policy_version,
               memory_setting_version, source_outbox_id::text AS source_outbox_id,
               source_proposal_id::text AS source_proposal_id
        FROM tutor_memory_entries
        WHERE user_id = %s
        """,
        (fixture.user_id,),
    ).fetchone()
    receipt = fixture.connection.execute(
        """
        SELECT state, target_kind, target_id::text AS target_id, code
        FROM tutor_curation_projection_receipts
        WHERE user_id = %s
        """,
        (fixture.user_id,),
    ).fetchone()
    proposal = fixture.connection.execute(
        "SELECT state, payload_json FROM tutor_curation_proposals WHERE outbox_id = %s",
        (outbox_id,),
    ).fetchone()

    assert len(seeded) == 1
    assert result.claimed == 1
    assert result.completed == 1
    assert gateway.calls and len(gateway.calls) == 1
    assert gateway.calls[0].outbox_id == outbox_id
    assert "content" not in gateway.calls[0].envelope
    assert projection is not None
    assert projection["memory_kind"] == "inference"
    assert projection["state"] == "active"
    assert projection["confidence"] == "medium"
    assert projection["provenance_kind"] == "curator"
    assert projection["policy_version"] == "tutor_policy_v1"
    assert projection["memory_setting_version"] == "memory_settings_v1"
    assert projection["source_outbox_id"] == outbox_id
    assert receipt is not None
    assert receipt["state"] == "committed"
    assert receipt["target_kind"] == "memory_entry"
    assert receipt["target_id"] is not None
    assert receipt["code"] == "curation_memory_entry_committed"
    assert proposal == {"state": "pending", "payload_json": {"kind": "memory_entry", "confidence": "medium", "safe_hash": proposal["payload_json"]["safe_hash"], "redaction_version": "tutor_safe_projection_v1"}}


def test_curator_preference_disable_and_zero_output_budget_never_call_provider(tutor_persistence) -> None:
    fixture = tutor_persistence
    learner_state = TutorLearnerStateRepository(fixture.connection)
    preference = learner_state.set_inferred_memory_preference(
        user_id=fixture.user_id,
        enabled=True,
        expected_setting_version="memory_settings_v1",
        now=_NOW,
    )
    create_curation_outbox(fixture, now=_NOW, memory_setting_version=preference.setting_version)
    scheduler_repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_scheduler_preference(scheduler_repository, fixture)
    gateway = _MemoryGateway()
    curator = TutorMemoryCurator(
        repository=PostgresTutorRepository(fixture.connection),
        learner_state=learner_state,
        gateway=gateway,
    )
    scheduler = TutorProactiveScheduler(
        store=scheduler_repository,
        config=_config(),
        curation_processor=curator,
    )
    scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id)
    learner_state.set_inferred_memory_preference(
        user_id=fixture.user_id,
        enabled=False,
        expected_setting_version=preference.setting_version,
        now=_NOW,
    )

    result = scheduler.drain_curation(
        worker_id="preference-disabled-worker", now=_NOW, user_id=fixture.user_id
    )

    assert result.claimed == 1
    assert result.no_action == 1
    assert gateway.calls == []

    client = _NeverClient()
    primary = PrimaryCurationGateway(settings=Settings(), client=client, max_output_tokens=0)
    no_call = primary.propose(
        source=TutorCurationSource(
            job_id="job-1",
            outbox_id="outbox-1",
            run_id="run-1",
            user_id="user-1",
            lease_owner_id="worker-1",
            lease_generation=1,
            policy_version="tutor_policy_v1",
            memory_setting_version="memory_settings_v1",
            envelope={"kind": "compaction_request"},
            source_ids=("evt-1",),
            source_hashes=("a" * 64,),
            retention_until=_NOW,
            stale_after=_NOW,
        )
    )
    assert no_call.state == "no_action"
    assert no_call.code == "curation_output_disabled"
    assert client.calls == 0

def test_primary_curation_gateway_uses_one_injected_primary_and_never_falls_back() -> None:
    source = TutorCurationSource(
        job_id="job-1",
        outbox_id="outbox-1",
        run_id="run-1",
        user_id="user-1",
        lease_owner_id="worker-1",
        lease_generation=1,
        policy_version="tutor_policy_v1",
        memory_setting_version="memory_settings_v1",
        envelope={"kind": "compaction_request", "source_ids": ["evt-1"]},
        source_ids=("evt-1",),
        source_hashes=("a" * 64,),
        retention_until=_NOW,
        stale_after=_NOW,
    )
    client = _PrimaryClient(
        {
            "kind": "context_summary",
            "summary": "Keep the next verification checkpoint compact.",
            "confidence": "low",
        }
    )
    gateway = PrimaryCurationGateway(settings=Settings(), client=client, max_output_tokens=17)

    result = gateway.propose(source=source)

    assert result.state == "proposal"
    assert result.proposal is not None
    assert result.proposal.kind == "context_summary"
    assert len(client.calls) == 1
    assert client.calls[0][1]["temperature"] is None
    assert client.calls[0][1]["max_tokens"] == 17
    assert client.calls[0][1]["schema_name"] == "tutor_curation_output_v1"
    assert isinstance(client.calls[0][1]["output_schema"], dict)
    serialized_messages = str(client.calls[0][0])
    assert "evt-1" in serialized_messages
    assert "provider_reasoning" not in serialized_messages

    invalid_client = _PrimaryClient({"kind": "unsupported"})
    invalid_result = PrimaryCurationGateway(
        settings=Settings(), client=invalid_client, max_output_tokens=17
    ).propose(source=source)
    assert invalid_result.state == "retryable"
    assert invalid_result.code == "curation_model_unavailable"
    assert len(invalid_client.calls) == 1