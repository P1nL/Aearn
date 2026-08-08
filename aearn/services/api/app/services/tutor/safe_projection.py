"""Allowlisted, dual-pass diagnostic projection for Tutor persistence.

Tutor Harness diagnostics must never become a second conversation store. This
module is deliberately stricter than the shared runtime redactor: callers can
only persist a small set of stable metadata keys, and exports run the same
projection again in case a historic database row was malformed.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final
from urllib.parse import urlparse

from app.core.teaching_safety import redact_value


SAFE_PROJECTION_VERSION: Final[str] = "tutor_safe_projection_v1"
_OMIT: Final[object] = object()
_MAX_DEPTH: Final[int] = 5
_MAX_ITEMS: Final[int] = 24
_MAX_SAFE_TEXT_LENGTH: Final[int] = 160
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{24,64}$")
_ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$")
_CREDENTIAL_TOKEN = re.compile(r"(?i)\b(?:bearer\s+|sk-|api[_-]?key|auth(?:orization)?[_-]?token|secret[_-]?key)")
_HIDDEN_TEST_TOKEN = re.compile(r"(?i)\bhidden(?:[_ -]?test|[_ -]?case)\b")
_REFERENCE_TOKEN = re.compile(r"(?i)\b(?:solution[_ -]?reference|reference[_ -]?answer|secret solution)\b")
_TRACE_TOKEN = re.compile(r"(?i)(?:traceback|stack trace|\bFile \".*?\", line \d+)")
_PATH_TOKEN = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:home|tmp|var|workspace|app|container)/|\\\\)")
_SHELL_TOKEN = re.compile(r"(?i)^\s*(?:bash|cmd(?:\.exe)?|powershell|pwsh|curl|wget|python(?:\.exe)?|node|npm|sh)\b")
_SQL_TOKEN = re.compile(r"(?is)^\s*(?:select\b.+\bfrom\b|insert\s+into\b|update\s+\S+\s+set\b|delete\s+from\b|drop\s+(?:table|database)\b|alter\s+table\b)")
_CODE_TOKEN = re.compile(r"(?is)(?:```|\bdef\s+[A-Za-z_]\w*\s*\(|\bfunction\s+[A-Za-z_]\w*\s*\(|\bclass\s+[A-Za-z_]\w*\s*\{|\bimport\s+[A-Za-z_])")

_SAFE_KEYS = frozenset(
    {
        "schema_version", "redaction_version", "kind", "status", "state", "code", "diagnostic_code", "origin",
        "run_id", "conversation_id", "user_id", "message_id", "event_id", "event_sequence", "event_from_sequence",
        "event_to_sequence", "input_revision", "catalog_digest", "policy_version", "policy_fingerprint",
        "memory_setting_version", "skill_id", "skill_version", "manifest_hash", "instruction_hash", "evaluation_hash",
        "capability_id", "capability_version", "effect_id", "effect_type", "request_id", "request_hash", "result_hash",
        "payload_hash", "safe_hash", "idempotency_key", "event_key", "lease_owner_id", "lease_generation", "trigger", "priority",
        "outbox_id", "proposal_id", "trace_id", "commit_id", "source_id", "source_hash", "source_ids", "source_hashes",
        "execution_job_id", "execution_intent_id", "lock_fingerprint", "execution_state",
        "attempt_sequence", "cleanup_state", "availability_code",
        "source_count", "item_count", "count", "selected_count", "skipped_count", "token_budget", "consumed_tokens",
        "duration_ms", "confidence", "section", "sections", "section_counts", "retention_until", "stale_after",
        "created_at", "expires_at", "deadline", "max_iterations", "max_model_calls", "max_capability_calls",
        "max_effects", "context_token_budget", "lease_duration_seconds", "skills", "required_capability_ids",
        "allowed_effect_types", "policy_tags", "context_budget_policy", "budget_mode", "estimated_total_input_tokens", "optional_token_budget",
        "warning_reached", "critical_reached", "expansion_count", "estimator_version", "capability_version",
        "budget_policy_version", "truncated_count",
    }
)
_INTEGER_KEYS = frozenset(
    {
        "event_sequence", "event_from_sequence", "event_to_sequence", "input_revision", "lease_generation", "priority",
        "attempt_sequence",
        "source_count", "item_count", "count", "selected_count", "skipped_count", "token_budget", "consumed_tokens",
        "duration_ms", "max_iterations", "max_model_calls", "max_capability_calls", "max_effects",
        "context_token_budget", "lease_duration_seconds", "estimated_total_input_tokens", "optional_token_budget",
        "expansion_count", "truncated_count", "context_window_tokens", "max_output_reserve_tokens",
        "protocol_reserve_tokens", "safety_margin_tokens", "maximum_dynamic_target_tokens",
    }
)
_HASH_KEYS = frozenset(
    {
        "catalog_digest", "policy_fingerprint", "manifest_hash", "instruction_hash", "evaluation_hash", "request_hash",
        "result_hash", "payload_hash", "safe_hash", "source_hash", "lock_fingerprint",
    }
)


class TutorSafeProjectionError(ValueError):
    """Raised when a caller attempts to persist an unsafe diagnostic envelope."""


@dataclass(frozen=True)
class TutorSafeProjection:
    """Project only stable, learner-safe diagnostic metadata.

    The class is intentionally stateless so callers can use the same instance
    for database writes and later exports. Unknown keys are omitted rather than
    copied, including nested unknown keys.
    """

    version: str = SAFE_PROJECTION_VERSION

    def project(self, value: object) -> dict[str, object]:
        projected = self._project_mapping(value, depth=0)
        return {**projected, "redaction_version": self.version}

    def export(self, value: object) -> dict[str, object]:
        """Defensively re-project a database value before exposing it."""
        return self.project(value)

    def fingerprint(self, value: object) -> str:
        canonical = json.dumps(self.project(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def checkpoint(self, *, metadata: Mapping[str, object], status: str, reason: str, input_revision: int) -> dict[str, object]:
        return self.project(
            {
                **dict(metadata),
                "kind": "checkpoint",
                "status": status,
                "code": reason,
                "input_revision": input_revision,
            }
        )

    def compaction(self, value: Mapping[str, object]) -> dict[str, object]:
        return self.project({**dict(value), "kind": "compaction_request"})

    def _project_mapping(self, value: object, *, depth: int) -> dict[str, object]:
        if depth > _MAX_DEPTH or not isinstance(value, Mapping):
            return {}
        result: dict[str, object] = {}
        for index, raw_key in enumerate(sorted(value, key=lambda item: str(item))):
            if index >= _MAX_ITEMS:
                break
            key = str(raw_key)
            if key not in _SAFE_KEYS:
                continue
            projected = self._project_value(key, value[raw_key], depth=depth + 1)
            if projected is not _OMIT:
                result[key] = projected
        return result

    def _project_value(self, key: str, value: object, *, depth: int) -> object:
        if key in _INTEGER_KEYS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return _OMIT
            return value
        if key in _HASH_KEYS:
            normalized = str(value or "").lower()
            return normalized if _SHA256.fullmatch(normalized) else _OMIT
        if key == "source_hashes":
            return self._project_hashes(value)
        if key in {"source_ids", "required_capability_ids", "allowed_effect_types", "policy_tags"}:
            return self._project_identifiers(value)
        if key == "sections":
            return self._project_sections(value, depth=depth)
        if key == "section_counts":
            return self._project_section_counts(value)
        if key == "skills":
            return self._project_skills(value, depth=depth)
        if key in {"retention_until", "stale_after", "created_at", "expires_at", "deadline"}:
            return _safe_timestamp(value)
        if key == "context_budget_policy":
            return self._project_context_budget_policy(value, depth=depth)
        if key == "confidence":
            normalized = str(value or "").lower()
            return normalized if normalized in {"low", "medium", "high"} else _OMIT
        if key in {"warning_reached", "critical_reached"}:
            return value if isinstance(value, bool) else _OMIT
        if key == "budget_mode":
            normalized = str(value or "").lower()
            return normalized if normalized in {"compact", "normal", "complex", "extended"} else _OMIT
        return _safe_identifier(value)

    def _project_context_budget_policy(self, value: object, *, depth: int) -> dict[str, object] | object:
        if not isinstance(value, Mapping) or depth > _MAX_DEPTH:
            return _OMIT
        capability = value.get("capability")
        capability_result: dict[str, object] = {}
        if isinstance(capability, Mapping):
            for key in (
                "context_window_tokens",
                "max_output_reserve_tokens",
                "protocol_reserve_tokens",
                "safety_margin_tokens",
                "maximum_dynamic_target_tokens",
            ):
                projected = self._project_value(key, capability.get(key), depth=depth + 1)
                if projected is not _OMIT:
                    capability_result[key] = projected
            version = _safe_identifier(capability.get("capability_version"))
            if isinstance(version, str):
                capability_result["capability_version"] = version
        mode_targets_value = value.get("mode_targets")
        mode_targets: dict[str, int] = {}
        if isinstance(mode_targets_value, Mapping):
            for mode in ("compact", "normal", "complex", "extended"):
                projected = self._project_value("optional_token_budget", mode_targets_value.get(mode), depth=depth + 1)
                if isinstance(projected, int):
                    mode_targets[mode] = projected
        result: dict[str, object] = {
            "capability": capability_result,
            "mode_targets": mode_targets,
        }
        for key in ("warning_ratio", "critical_ratio"):
            raw = value.get(key)
            if isinstance(raw, int | float) and not isinstance(raw, bool) and 0 < raw <= 1:
                result[key] = float(raw)
        max_expansions = self._project_value("expansion_count", value.get("max_expansions"), depth=depth + 1)
        if isinstance(max_expansions, int):
            result["max_expansions"] = max_expansions
        for key in ("estimator_version", "policy_version"):
            normalized = _safe_identifier(value.get(key))
            if isinstance(normalized, str):
                result[key] = normalized
        fixed_mode = str(value.get("fixed_mode") or "")
        if fixed_mode in {"compact", "normal", "complex", "extended"}:
            result["fixed_mode"] = fixed_mode
        return result

    def _project_identifiers(self, value: object) -> list[str]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return []
        result: list[str] = []
        for item in value[:_MAX_ITEMS]:
            normalized = _safe_identifier(item)
            if isinstance(normalized, str):
                result.append(normalized)
        return result

    def _project_hashes(self, value: object) -> list[str]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return []
        return [
            normalized
            for item in value[:_MAX_ITEMS]
            if _SHA256.fullmatch(normalized := str(item or "").lower())
        ]

    def _project_sections(self, value: object, *, depth: int) -> list[dict[str, object]]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or depth > _MAX_DEPTH:
            return []
        return [
            self._project_mapping(item, depth=depth + 1)
            for item in value[:_MAX_ITEMS]
            if isinstance(item, Mapping)
        ]

    def _project_section_counts(self, value: object) -> dict[str, int]:
        if not isinstance(value, Mapping):
            return {}
        result: dict[str, int] = {}
        for index, raw_key in enumerate(sorted(value, key=lambda item: str(item))):
            if index >= _MAX_ITEMS:
                break
            identifier = _safe_identifier(raw_key)
            count = value[raw_key]
            if not isinstance(identifier, str) or isinstance(count, bool) or not isinstance(count, int) or count < 0:
                continue
            result[identifier] = count
        return result

    def _project_skills(self, value: object, *, depth: int) -> list[dict[str, object]]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or depth > _MAX_DEPTH:
            return []
        result: list[dict[str, object]] = []
        for item in value[:_MAX_ITEMS]:
            if not isinstance(item, Mapping):
                continue
            projected = self._project_mapping(item, depth=depth + 1)
            if projected:
                result.append(projected)
        return result


def _safe_identifier(value: object) -> str | object:
    if isinstance(value, (dict, list, tuple, set, bytes)) or value is None:
        return _OMIT
    text = str(redact_value(value)).strip()
    if not text or len(text) > _MAX_SAFE_TEXT_LENGTH or "\n" in text or "\r" in text:
        return _OMIT
    if _contains_protected_value(text):
        return _OMIT
    if not _SAFE_IDENTIFIER.fullmatch(text):
        return _OMIT
    return text


def _safe_timestamp(value: object) -> str | object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "")
    return text if _ISO_DATETIME.fullmatch(text) else _OMIT


def _contains_protected_value(value: str) -> bool:
    lowered = value.lower()
    if "[redacted" in lowered:
        return True
    if _CREDENTIAL_TOKEN.search(value) or _HIDDEN_TEST_TOKEN.search(value) or _REFERENCE_TOKEN.search(value):
        return True
    if _TRACE_TOKEN.search(value) or _PATH_TOKEN.search(value) or _SHELL_TOKEN.search(value) or _SQL_TOKEN.search(value):
        return True
    if _CODE_TOKEN.search(value):
        return True
    if "://" in value:
        parsed = urlparse(value)
        if parsed.username is not None or parsed.password is not None:
            return True
        return True
    return False
