"""CPU coverage of the real create_run admission seam, not PostgreSQL acceptance."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import pytest
from psycopg import Connection

from app.agents.harness.contracts import TutorPolicySnapshot
from app.core.config import Settings
from app.services.tutor.completion_execution import COMPLETION_POLICY_VERSION, completion_admission_policy
from app.services.tutor.persistence.repository import PostgresTutorRepository

NOW = datetime(2026, 10, 27, tzinfo=UTC)
USER = "00000000-0000-4000-8000-000000000001"
CONVERSATION = "00000000-0000-4000-8000-000000000002"
DIGEST = "a" * 64


class InsertReached(RuntimeError):
    pass


class Row:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def fetchone(self) -> dict[str, object]:
        return self.value


class AdmissionProbe:
    def __init__(self) -> None:
        self.calls = 0
        self.insert_params: tuple[object, ...] | None = None

    def execute(self, query: str, params: tuple[object, ...]) -> Row:
        self.calls += 1
        command = " ".join(query.split())
        if command.startswith("SELECT id FROM tutor_conversations"):
            return Row({"id": CONVERSATION})
        if command.startswith("SELECT digest FROM tutor_catalog_snapshots"):
            return Row({"digest": DIGEST})
        if command.startswith("INSERT INTO tutor_runs"):
            self.insert_params = params
            raise InsertReached
        raise AssertionError("Unexpected SQL in the narrow admission probe")


def invoke(probe: AdmissionProbe, *, profile: bool, version: str,
           origin: Literal["interactive", "proactive"] = "interactive") -> None:
    settings = Settings(llm_type="disabled", openai_api_key=None, deepseek_api_key=None)
    repository = PostgresTutorRepository(cast(Connection[dict[str, object]], probe), settings=settings)
    policy = TutorPolicySnapshot(deadline=NOW + timedelta(minutes=5), context_token_budget=1024)
    if profile:
        policy = completion_admission_policy(policy, now=NOW)
    repository.create_run(user_id=USER, conversation_id=CONVERSATION,
                          catalog_digest=DIGEST, policy=policy, origin=origin, policy_version=version)


@pytest.mark.parametrize("version", ["tutor_policy_v1", "tutor_interactive_policy_v1", COMPLETION_POLICY_VERSION])
def test_new_completion_admission_persists_only_canonical_version(version: str) -> None:
    probe = AdmissionProbe()
    with pytest.raises(InsertReached):
        invoke(probe, profile=True, version=version)
    assert probe.calls == 3 and probe.insert_params is not None
    assert probe.insert_params[5] == COMPLETION_POLICY_VERSION
    assert json.loads(str(probe.insert_params[4]))["execution_profile"] == "completion_driven_v1"


def test_legacy_normal_interactive_version_is_unchanged() -> None:
    probe = AdmissionProbe()
    with pytest.raises(InsertReached):
        invoke(probe, profile=False, version="tutor_interactive_policy_v1")
    assert probe.insert_params is not None
    assert probe.insert_params[5] == "tutor_interactive_policy_v1"
    assert json.loads(str(probe.insert_params[4])).get("execution_profile") is None


@pytest.mark.parametrize("version", ["tutor_retry_policy_v1", "tutor_queue_claim_policy_v1",
                                    "tutor_interaction_response_policy_v1", "unknown_policy_v9"])
def test_other_completion_admission_labels_still_deny_before_sql(version: str) -> None:
    probe = AdmissionProbe()
    with pytest.raises(ValueError, match="completion admission policy version mismatch"):
        invoke(probe, profile=True, version=version)
    assert probe.calls == 0 and probe.insert_params is None


def test_normal_interactive_alias_does_not_authorize_proactive_admission() -> None:
    probe = AdmissionProbe()
    with pytest.raises(ValueError, match="completion admission policy version mismatch"):
        invoke(probe, profile=True, version="tutor_interactive_policy_v1", origin="proactive")
    assert probe.calls == 0
