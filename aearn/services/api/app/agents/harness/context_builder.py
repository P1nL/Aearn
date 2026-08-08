"""Deterministic, bounded context construction for Tutor runs."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import ceil
from collections.abc import Mapping, Sequence

from app.agents.harness.contracts import (
    CONTEXT_SECTION_PRIORITY,
    MAX_TUTOR_PUBLIC_MESSAGE_LENGTH,
    TokenEstimator,
    TutorCheckpointMetadata,
    TutorCompactionTrigger,
    TutorContextError,
    TutorContextInput,
    TutorContextItem,
    TutorCurrentInput,
    TutorCurrentInputMetadata,
    TutorContextSection,
    TutorContextSectionMetadata,
    TutorContextSelection,
    TutorContextSource,
    build_compaction_request,
)
from app.core.teaching_safety import limit_text, redact_value, sanitize_message_content, sanitize_summary_text


DEFAULT_SECTION_ITEM_LIMITS: tuple[tuple[TutorContextSection, int], ...] = (
    (TutorContextSection.SYSTEM, 3),
    (TutorContextSection.ACTIVE_PLAN, 1),
    (TutorContextSection.REVIEW, 1),
    (TutorContextSection.RECENT_MESSAGES, 4),
    (TutorContextSection.WORKING_SUMMARY, 1),
    (TutorContextSection.LEARNER_MEMORY, 4),
    (TutorContextSection.ACTIVITY, 4),
    (TutorContextSection.CAPABILITY_SCHEMAS, 4),
)

_HARNESS_REDACTED_FIELD_NAMES = frozenset(
    {
        "solutionreference",
        "referenceanswer",
        "rawprompt",
        "systemprompt",
        "providerpayload",
        "providererror",
        "apikey",
        "secret",
        "secretkey",
        "authtoken",
        "stacktrace",
        "traceback",
        "rawhistory",
        "fullhistory",
        "conversationhistory",
        "rawconversation",
        "fullconversation",
    }
)


@dataclass(frozen=True)
class TutorContextBuilderConfig:
    section_item_limits: tuple[tuple[TutorContextSection, int], ...] = DEFAULT_SECTION_ITEM_LIMITS
    max_source_characters: int = 1200
    high_water_ratio: float = 0.8

    def __post_init__(self) -> None:
        if self.max_source_characters <= 0:
            raise ValueError("max_source_characters must be positive")
        if not 0 < self.high_water_ratio <= 1:
            raise ValueError("high_water_ratio must be within (0, 1]")
        seen: set[TutorContextSection] = set()
        normalized: list[tuple[TutorContextSection, int]] = []
        for section, limit in self.section_item_limits:
            if section in seen:
                raise ValueError("context section limit must be unique")
            if limit < 0:
                raise ValueError("context section limit must be non-negative")
            seen.add(section)
            normalized.append((section, limit))
        object.__setattr__(self, "section_item_limits", tuple(normalized))

    def item_limit_for(self, section: TutorContextSection) -> int:
        for candidate, limit in self.section_item_limits:
            if candidate is section:
                return limit
        return 0


@dataclass(frozen=True)
class Utf8ByteTokenEstimator:
    """Conservative, provider-neutral token estimate based on UTF-8 bytes."""

    bytes_per_token: int = 4

    def __post_init__(self) -> None:
        if self.bytes_per_token <= 0:
            raise ValueError("bytes_per_token must be positive")

    def estimate_tokens(self, value: object) -> int:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return max(1, ceil(len(text.encode("utf-8")) / self.bytes_per_token))


class TutorContextBuilder:
    """Select safe, pre-scoped context in a fixed section order and budget."""

    def __init__(
        self,
        *,
        estimator: TokenEstimator | None = None,
        config: TutorContextBuilderConfig | None = None,
    ) -> None:
        self._estimator = estimator or Utf8ByteTokenEstimator()
        self._config = config or TutorContextBuilderConfig()

    def build(self, context_input: TutorContextInput, *, token_budget: int) -> TutorContextSelection:
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")

        current_input = self._select_current_input(context_input, token_budget=token_budget)
        consumed_tokens = current_input.token_estimate if current_input is not None else 0
        by_section = dict(context_input.section_sources())
        selected_items: list[TutorContextItem] = []
        section_metadata: list[TutorContextSectionMetadata] = []

        for section in CONTEXT_SECTION_PRIORITY:
            sources = by_section.get(section, ())
            selected_ids: list[str] = []
            selected_hashes: list[str] = []
            selected_count = 0
            skipped_count = 0
            item_limit = self._config.item_limit_for(section)

            if section is TutorContextSection.RECENT_MESSAGES:
                bounded_sources = sources[-item_limit:] if item_limit else ()
                skipped_count += len(sources) - len(bounded_sources)
                recent_items: list[TutorContextItem] = []
                for source in reversed(bounded_sources):
                    content = self._serialize_source(section, source)
                    estimate = max(1, self._estimator.estimate_tokens(content))
                    if consumed_tokens + estimate > token_budget:
                        skipped_count += 1
                        continue
                    recent_items.append(
                        TutorContextItem(
                            section=section,
                            source_id=source.source_id,
                            content=content,
                            source_hash=_source_hash(content),
                            token_estimate=estimate,
                        )
                    )
                    consumed_tokens += estimate
                for item in reversed(recent_items):
                    selected_items.append(item)
                    selected_ids.append(item.source_id)
                    selected_hashes.append(item.source_hash)
                selected_count = len(recent_items)
            else:
                bounded_sources = sources[:item_limit]
                skipped_count += len(sources) - len(bounded_sources)
                for source in bounded_sources:
                    content = self._serialize_source(section, source)
                    estimate = max(1, self._estimator.estimate_tokens(content))
                    if consumed_tokens + estimate > token_budget:
                        skipped_count += 1
                        continue
                    source_hash = _source_hash(content)
                    selected_items.append(
                        TutorContextItem(
                            section=section,
                            source_id=source.source_id,
                            content=content,
                            source_hash=source_hash,
                            token_estimate=estimate,
                        )
                    )
                    selected_ids.append(source.source_id)
                    selected_hashes.append(source_hash)
                    selected_count += 1
                    consumed_tokens += estimate

            section_metadata.append(
                TutorContextSectionMetadata(
                    section=section,
                    selected_count=selected_count,
                    skipped_count=skipped_count,
                    source_ids=tuple(selected_ids),
                    source_hashes=tuple(selected_hashes),
                )
            )

        metadata = TutorCheckpointMetadata(
            token_budget=token_budget,
            consumed_tokens=consumed_tokens,
            current_input=(
                TutorCurrentInputMetadata(
                    source_id=current_input.source_id,
                    source_hash=current_input.source_hash,
                    token_estimate=current_input.token_estimate,
                    truncated=current_input.truncated,
                )
                if current_input is not None
                else None
            ),
            sections=tuple(section_metadata),
        )
        high_water_request = None
        high_water_threshold = ceil(token_budget * self._config.high_water_ratio)
        if (current_input is not None or selected_items) and consumed_tokens >= high_water_threshold:
            high_water_request = build_compaction_request(
                run_id=context_input.run_id,
                conversation_id=context_input.conversation_id,
                input_revision=context_input.input_revision,
                trigger=TutorCompactionTrigger.CONTEXT_HIGH_WATER,
                metadata=metadata,
            )

        return TutorContextSelection(
            items=tuple(selected_items),
            checkpoint_metadata=metadata,
            current_input=current_input,
            high_water_compaction_request=high_water_request,
        )

    def _select_current_input(
        self,
        context_input: TutorContextInput,
        *,
        token_budget: int,
    ) -> TutorCurrentInput | None:
        source = context_input.current_input
        if source is None:
            if context_input.current_input_required:
                raise TutorContextError("TUTOR_CURRENT_INPUT_MISSING")
            return None

        raw_content = source.content
        if isinstance(raw_content, Mapping):
            raw_content = raw_content.get("content")
        normalized = str(raw_content or "").strip()
        max_current_input_characters = min(
            self._config.max_source_characters,
            MAX_TUTOR_PUBLIC_MESSAGE_LENGTH,
        )
        content = sanitize_message_content(
            role="user",
            content=normalized,
            max_length=max_current_input_characters,
        )
        if not content:
            raise TutorContextError("TUTOR_CURRENT_INPUT_EMPTY")

        estimate = max(1, self._estimator.estimate_tokens(content))
        truncated = len(normalized) > max_current_input_characters
        if estimate > token_budget:
            content = self._truncate_required_content(content, token_budget=token_budget)
            estimate = max(1, self._estimator.estimate_tokens(content))
            truncated = True

        return TutorCurrentInput(
            source_id=source.source_id,
            content=content,
            source_hash=_source_hash(content),
            token_estimate=estimate,
            truncated=truncated,
        )

    def _truncate_required_content(self, content: str, *, token_budget: int) -> str:
        for length in range(len(content) - 1, 0, -1):
            candidate = f"{content[:length].rstrip()}..."
            if candidate != "..." and self._estimator.estimate_tokens(candidate) <= token_budget:
                return candidate
        first_character = content[:1]
        if first_character and self._estimator.estimate_tokens(first_character) <= token_budget:
            return first_character
        raise TutorContextError("TUTOR_CURRENT_INPUT_UNREPRESENTABLE")

    def _serialize_source(self, section: TutorContextSection, source: TutorContextSource) -> str:
        safe_value = _sanitize_source_value(
            section=section,
            value=source.content,
            max_characters=self._config.max_source_characters,
        )
        if isinstance(safe_value, str):
            return safe_value
        return limit_text(
            json.dumps(safe_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            self._config.max_source_characters,
        )


def _sanitize_source_value(*, section: TutorContextSection, value: object, max_characters: int) -> object:
    redacted = _redact_harness_sensitive_fields(redact_value(value))
    if section is TutorContextSection.RECENT_MESSAGES and isinstance(redacted, Mapping):
        role = str(redacted.get("role") or "user")
        normalized_role = "assistant" if role in {"assistant", "agent"} else "user"
        return {
            "role": normalized_role,
            "content": sanitize_message_content(
                role=normalized_role,
                content=str(redacted.get("content") or ""),
                max_length=max_characters,
            ),
        }
    return _sanitize_value(redacted, max_characters=max_characters)


def _redact_harness_sensitive_fields(value: object) -> object:
    """Remove target-contract-only sensitive fields without changing Graph redaction."""
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _is_harness_sensitive_field_name(key):
                result[key] = "[REDACTED]"
                continue
            result[key] = _redact_harness_sensitive_fields(raw_value)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_redact_harness_sensitive_fields(item) for item in value]
    return value


def _is_harness_sensitive_field_name(value: object) -> bool:
    compact = "".join(character for character in str(value).lower() if character.isalnum())
    return compact in _HARNESS_REDACTED_FIELD_NAMES or compact.startswith("hiddentest")


def _sanitize_value(value: object, *, max_characters: int) -> object:
    if isinstance(value, str):
        return sanitize_summary_text(value, max_length=max_characters)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for index, (raw_key, raw_value) in enumerate(value.items()):
            if index >= 20:
                break
            key = limit_text(str(redact_value(raw_key)), 80) or "unknown"
            result[key] = _sanitize_value(raw_value, max_characters=max_characters)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_sanitize_value(item, max_characters=max_characters) for item in value[:12]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return "unsupported_value"


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:24]
