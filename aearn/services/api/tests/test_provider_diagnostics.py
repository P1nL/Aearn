from __future__ import annotations

import base64
import io
import urllib.error
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.agents.harness.context_builder import (
    TutorContextBuilder,
    TutorContextBuilderConfig,
)
from app.agents.harness.contracts import (
    TutorContextInput,
    TutorContextSource,
    TutorPolicySnapshot,
    TutorRunSnapshot,
)
from app.core.config import Settings
from app.services.llm.llm_client import OpenAICompatibleClient
from app.services.llm.provider_diagnostics import (
    ProviderDiagnosticMetadata,
    ProviderDiagnosticStore,
)
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway


def _capture_key() -> tuple[bytes, str]:
    key = AESGCM.generate_key(bit_length=256)
    return key, base64.b64encode(key).decode("ascii")


def _settings(tmp_path: Path, *, key_base64: str) -> Settings:
    return Settings(
        llm_type="openai",
        openai_api_key="test-key",
        openai_base_url="https://provider.example/v1",
        openai_model="provider-model",
        tutor_provider_debug_capture_mode="rejected",
        tutor_provider_debug_capture_key=key_base64,
        tutor_provider_debug_capture_directory=str(tmp_path),
        tutor_provider_debug_capture_max_bytes=4096,
        tutor_provider_debug_capture_retention_hours=24,
    )


def _run() -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="run-provider-diagnostic",
        conversation_id="conversation-provider-diagnostic",
        user_id="user-provider-diagnostic",
        origin="interactive",
        input_revision=3,
        policy=TutorPolicySnapshot(
            deadline=datetime(2030, 1, 1, tzinfo=timezone.utc),
            max_capability_calls=1,
            max_effects=1,
        ),
    )


def _context():
    return TutorContextBuilder(
        config=TutorContextBuilderConfig(section_item_limits=())
    ).build(
        TutorContextInput(
            run_id="run-provider-diagnostic",
            conversation_id="conversation-provider-diagnostic",
            input_revision=3,
            current_input_required=True,
            current_input=TutorContextSource("message-current", "请解释变量作用域。"),
        ),
        token_budget=1200,
    )


def _provider_response(content: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "model": "provider-model",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(content, ensure_ascii=False),
                    }
                ],
            }
        ],
    }


def test_provider_diagnostic_store_encrypts_body_and_authenticates_metadata(
    tmp_path: Path,
) -> None:
    key, key_base64 = _capture_key()
    settings = _settings(tmp_path, key_base64=key_base64)
    store = ProviderDiagnosticStore.from_settings(settings)
    assert store is not None
    capture = store.begin_capture()
    plaintext = b"provider body with Authorization: Bearer private-token"
    capture.append(plaintext)

    artifact = capture.commit(
        ProviderDiagnosticMetadata(
            run_id="run-provider-diagnostic",
            attempt_index=1,
            provider_type="openai",
            protocol="responses",
            model="provider-model",
            diagnostic_code="TUTOR_PROVIDER_DECISION_EXTRA_FIELD",
            contract_hash="a" * 64,
        )
    )

    assert artifact is not None
    serialized = artifact.path.read_bytes()
    assert plaintext not in serialized
    assert b"private-token" not in serialized
    assert store.decrypt_artifact(artifact.path) == plaintext
    assert key not in serialized


def test_provider_diagnostic_capture_is_bounded_and_marks_truncation(
    tmp_path: Path,
) -> None:
    _, key_base64 = _capture_key()
    settings = _settings(tmp_path, key_base64=key_base64)
    store = ProviderDiagnosticStore.from_settings(settings)
    assert store is not None
    capture = store.begin_capture()
    capture.append(b"x" * 5000)

    artifact = capture.commit(
        ProviderDiagnosticMetadata(
            run_id="run-provider-diagnostic",
            attempt_index=1,
            provider_type="openai",
            protocol="responses",
            model="provider-model",
            diagnostic_code="TUTOR_PROVIDER_RESPONSE_INVALID",
            contract_hash="b" * 64,
        )
    )

    assert artifact is not None
    assert artifact.captured_bytes == 4096
    assert artifact.truncated is True
    assert store.decrypt_artifact(artifact.path) == b"x" * 4096


def test_gateway_commits_rejected_provider_bodies_but_discards_accepted_body(
    tmp_path: Path,
) -> None:
    _, key_base64 = _capture_key()
    settings = _settings(tmp_path, key_base64=key_base64)
    rejected_body = {
        "schema_version": "tutor_provider_items_v2",
        "message": {
            "type": "agent_message",
            "text": "继续。",
            "public_thinking_steps": ["当前目标可以收敛为一个可验证的小步骤。"],
            "conversation_title": None,
        },
        "action": {"type": "turn_completed"},
        "reasoning": "private provider chain Authorization: Bearer private-token",
    }

    rejected = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(
            settings,
            transport=lambda url, headers, payload, timeout: _provider_response(
                rejected_body
            ),
            diagnostic_store=ProviderDiagnosticStore.from_settings(settings),
        ),
    ).decide(run=_run(), context=_context())

    artifacts = sorted(tmp_path.glob("*.aearn-provider-debug"))
    assert rejected.terminal_outcome is not None
    assert rejected.safe_code == "TUTOR_PROVIDER_DECISION_EXTRA_FIELD"
    assert len(artifacts) == 2
    assert "private-token" not in repr(rejected)
    assert "private provider chain" not in repr(rejected)
    assert all(
        "private-token" not in path.read_text(encoding="utf-8") for path in artifacts
    )

    accepted_body = {
        "schema_version": "tutor_provider_items_v2",
        "message": {
            "type": "agent_message",
            "text": "先看一个小例子。",
            "public_thinking_steps": ["当前目标可以收敛为一个可验证的小步骤。"],
            "conversation_title": None,
        },
        "action": {"type": "turn_completed"},
    }
    accepted = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(
            settings,
            transport=lambda url, headers, payload, timeout: _provider_response(
                accepted_body
            ),
            diagnostic_store=ProviderDiagnosticStore.from_settings(settings),
        ),
    ).decide(run=_run(), context=_context())

    assert accepted.decision is not None
    assert len(list(tmp_path.glob("*.aearn-provider-debug"))) == 2


def test_http_error_body_is_encrypted_without_entering_safe_result(
    tmp_path: Path,
) -> None:
    _, key_base64 = _capture_key()
    settings = _settings(tmp_path, key_base64=key_base64)
    private_body = b'{"error":"Authorization: Bearer private-http-token"}'

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        del headers, payload, timeout
        raise urllib.error.HTTPError(
            url,
            400,
            "rejected",
            hdrs=None,
            fp=io.BytesIO(private_body),
        )

    result = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(
            settings,
            transport=transport,
            diagnostic_store=ProviderDiagnosticStore.from_settings(settings),
        ),
    ).decide(run=_run(), context=_context())

    artifacts = list(tmp_path.glob("*.aearn-provider-debug"))
    store = ProviderDiagnosticStore.from_settings(settings)
    assert store is not None
    assert result.safe_code == "TUTOR_PROVIDER_REQUEST_REJECTED"
    assert len(artifacts) == 1
    assert store.decrypt_artifact(artifacts[0]) == private_body
    assert "private-http-token" not in repr(result)
    assert "private-http-token" not in artifacts[0].read_text(encoding="utf-8")


def test_capture_configuration_is_fail_closed_and_secret_repr_is_masked(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="requires an encryption key"):
        Settings(
            tutor_provider_debug_capture_mode="rejected",
            tutor_provider_debug_capture_directory=str(tmp_path),
        )

    malformed = Settings(
        tutor_provider_debug_capture_mode="rejected",
        tutor_provider_debug_capture_key="not-base64",
        tutor_provider_debug_capture_directory=str(tmp_path),
    )
    with pytest.raises(ValueError, match="valid base64"):
        ProviderDiagnosticStore.from_settings(malformed)

    configured_malformed = Settings(
        llm_type="openai",
        openai_api_key="test-key",
        openai_base_url="https://provider.example/v1",
        openai_model="provider-model",
        tutor_provider_debug_capture_mode="rejected",
        tutor_provider_debug_capture_key="not-base64",
        tutor_provider_debug_capture_directory=str(tmp_path),
    )
    unavailable = PrimaryTutorProviderGateway(settings=configured_malformed).decide(
        run=_run(),
        context=_context(),
    )
    assert unavailable.safe_code == "TUTOR_PROVIDER_CONFIGURATION_UNAVAILABLE"

    _, key_base64 = _capture_key()
    settings = _settings(tmp_path, key_base64=key_base64)

    assert key_base64 not in repr(settings)
    assert "**********" in repr(settings.tutor_provider_debug_capture_key)
